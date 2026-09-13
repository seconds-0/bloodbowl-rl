"""One human-vs-policy match with a JSON API.

The session owns the engine and two seats: an external human (any client that
speaks the JSON API) and a policy seat. Exactly one policy forward happens per
env c_step, whoever decides (native evaluation-mode recurrence). The human can
only submit an action id taken from the legal list of the current state
version, so an illegal engine action can never reach c_step.

API (all payloads JSON-serializable):
  state()            match state in absolute pitch coordinates
  legal()            prompt + legal actions annotated and grouped for a UI
  submit(request)    {"action_id", "state_version"} or {"action": {...}, ...}
  flag(note, step)   record state + the policy's action and logits for review
  survey(answers)    post-game survey answers
  save(out_dir)      game.json + policy_logits.npz
"""
from __future__ import annotations

import json
from collections import Counter
import os
import time

import numpy as np

from . import engine as E
from .policy import NONE_TUPLE, PolicySeat

SCHEMA = "bbplay-game-v1"

BLOCK_FACES = {1: "attacker_down", 2: "both_down", 3: "push", 4: "push",
               5: "stumble", 6: "pow"}

SPECIAL_VARIANTS = {1: "stab", 2: "hypnotic_gaze", 4: "chainsaw", 5: "breathe_fire",
                    6: "projectile_vomit", 7: "throw_team_mate_pick", 9: "hit_and_run"}

PUSH_KINDS = {0: "push", 1: "crowd", 2: "chain"}

# Prompt kind by (proc, phase); phase None matches any phase.
PROMPTS = {
    ("PREGAME", 1): "coin_toss_choice",
    ("SETUP", None): "setup",
    ("KICKOFF", 0): "kick_target",
    ("KICKOFF", 2): "touchback",
    ("KICKOFF", 4): "high_kick",
    ("KICKOFF", 5): "solid_defence",
    ("KICKOFF", 6): "quick_snap",
    ("KICKOFF", 7): "charge",
    ("TEAM_TURN", None): "select_player",
    ("ACTIVATION", 0): "declare_action",
    ("ACTIVATION", 2): "activation_reroll",
    ("MOVE", None): "move",
    ("TEST", None): "test_reroll",
    ("BLOCK", 1): "block_reroll",
    ("BLOCK", 2): "block_choose_die",
    ("BLOCK", 4): "wrestle_attacker",
    ("BLOCK", 5): "wrestle_defender",
    ("PUSH", 0): "push_square",
    ("PUSH", 3): "follow_up",
    ("PUSH", 4): "stand_firm",
    ("PASS", 2): "interception_choice",
    ("CASUALTY", 1): "apothecary",
    ("CASUALTY", 2): "apothecary_result",
    ("KO_RECOVERY", None): "apothecary_ko",
    ("FOUL", 2): "argue_the_call",
}

# UI interaction surface per action type.
SURFACE = {
    "SETUP_PLACE": "drag_player", "SETUP_REMOVE": "player", "SETUP_DONE": "button",
    "KICK_TARGET": "square", "TOUCHBACK": "player", "ACTIVATE": "player",
    "DECLARE": "menu", "END_TURN": "button", "STEP": "square", "STAND_UP": "menu",
    "JUMP": "square", "BLOCK_TARGET": "square", "PASS_TARGET": "square",
    "HANDOFF_TARGET": "square", "FOUL_TARGET": "square", "TTM_TARGET": "square",
    "SECURE_BALL": "menu", "PICKUP_DECLINE": "dialog", "END_ACTIVATION": "menu",
    "CHOOSE_DIE": "dialog", "PUSH_SQUARE": "square", "FOLLOW_UP": "dialog",
    "USE_REROLL": "dialog", "DECLINE_REROLL": "dialog", "USE_SKILL": "dialog",
    "DECLINE_SKILL": "dialog", "APOTHECARY": "dialog", "CHOOSE_OPTION": "dialog",
    "SPECIAL_TARGET": "square",
}


class IntegrityError(RuntimeError):
    pass


class ScriptedSeat:
    """Forward-free stand-in for the policy seat (tests and bot opponents)."""

    def __init__(self, seat, kind="contact", seed=0):
        import random
        self.seat = seat
        self.kind = kind
        self.seed = seed
        self._rng = random.Random(seed)
        self.forwards = 0
        self.decisions = 0
        self.provenance = {"scripted": kind}
        self.mode = kind

    def reset_match(self):
        import random
        self._rng = random.Random(self.seed)
        self.forwards = 0
        self.decisions = 0

    def step_env(self, engine, deciding):
        self.forwards += 1
        if not deciding:
            return {"tuple": NONE_TUPLE, "logprob": 0.0, "value": None, "logits": None}
        legal = engine.legal()
        if self.kind == "contact":
            idx = engine.contact_bot_index()
        else:
            idx = self._rng.randrange(len(legal))
        self.decisions += 1
        return {"tuple": legal[idx].tuple, "logprob": None, "value": None, "logits": None}


def _seat_step(seat, engine, deciding):
    if isinstance(seat, PolicySeat):
        return seat.step(engine.obs(seat.seat), engine.joint_support(seat.seat), deciding)
    return seat.step_env(engine, deciding)


def _player_json(engine, match, slot):
    p = match.players[slot]
    team = slot >> 4
    on_pitch = p.location == 0
    flags = [name for bit, name in enumerate(E.PLAYER_FLAGS) if p.flags & (1 << bit)]
    return {
        "slot": slot, "team": team, "number": (slot & 15) + 1,
        "position": engine.position_display(match.team_id[team], p.position_id),
        "x": int(p.x) if on_pitch else None, "y": int(p.y) if on_pitch else None,
        "location": E.LOCATIONS[p.location] if p.location < len(E.LOCATIONS) else p.location,
        "stance": E.STANCES[p.stance] if p.stance < len(E.STANCES) else p.stance,
        "flags": flags,
        "ma": p.ma, "st": p.st, "ag": p.ag, "pa": p.pa, "av": p.av,
        "moved": p.moved, "rushes": p.rushes,
        "skills": [engine.skill_display(s) for s in E.skills_of(p)],
        "has_ball": match.ball.state == 2 and match.ball.carrier == slot,
    }


def match_json(engine, match):
    players = [_player_json(engine, match, s) for s in range(E.NUM_PLAYERS)
               if match.players[s].location != 5]
    top = match.stack[match.stack_top - 1] if match.stack_top > 0 else None
    ball = match.ball
    return {
        "teams": [{"id": int(match.team_id[t]), "name": engine.team_display(match.team_id[t]),
                   "score": int(match.score[t]), "turn": int(match.turn[t]),
                   "rerolls": int(match.rerolls[t]), "bonus_rerolls": int(match.bonus_rerolls[t]),
                   "apothecary": int(match.apothecary[t]), "bribes": int(match.bribes[t])}
                  for t in (0, 1)],
        "half": int(match.half), "active_team": int(match.active_team),
        "kicking_team": int(match.kicking_team),
        "weather": E.WEATHER[match.weather] if match.weather < len(E.WEATHER) else match.weather,
        "used_this_turn": {k: int(getattr(match, f"{k}_used")) for k in
                           ("blitz", "pass", "handoff", "foul", "ttm", "ktm", "secure")},
        "ball": {"state": E.BALL_STATES[ball.state], "x": int(ball.x), "y": int(ball.y),
                 "carrier": None if ball.carrier == 0xFF else int(ball.carrier)},
        "status": int(match.status), "decision_team": int(match.decision_team),
        "procedure": None if top is None else {
            "proc": E.PROCS[top.proc], "phase": int(top.phase), "a": int(top.a),
            "b": int(top.b), "x": int(top.x), "y": int(top.y), "data": int(top.data)},
        "players": players,
    }


def _option_table(obs, agent):
    table = []
    base = 784 + 32
    for i in range(16):
        v = int(obs[base + i])
        if v == 0:
            table.append(None)
        else:
            ego = v - 1
            table.append(ego ^ 16 if agent == 1 else ego)
    return table


class GameSession:
    def __init__(self, policy_seat, human_seat=0, seed=1, episode=0, home_team=-1,
                 away_team=-1, max_decisions=4096, meta=None):
        if human_seat not in (0, 1):
            raise ValueError("human_seat must be 0 (HOME) or 1 (AWAY)")
        if policy_seat.seat != 1 - human_seat:
            raise ValueError("policy seat must be the other team")
        self.human_seat = human_seat
        self.seat = policy_seat
        self.params = {"seed": int(seed), "episode": int(episode),
                       "home_team": int(home_team), "away_team": int(away_team),
                       "max_decisions": int(max_decisions)}
        self.engine = E.Engine(seed, episode=episode, home_team=home_team,
                               away_team=away_team, max_decisions=max_decisions)
        self.seat.reset_match()
        self.meta = dict(meta or {})
        self.version = 0
        self.over = False
        self.result = None
        self.trace = []
        self.flags = []
        self.survey_answers = None
        self.api_rejections = 0
        self.presented_types = set()
        self.presented_counts = Counter()
        self.submitted_types = set()
        self.presented_prompts = set()
        self.policy_logits = {}
        self._pre_states = []
        self.started_at = time.time()
        self._advance()

    # ---- core loop -------------------------------------------------------
    def _tick(self, human_index=None):
        eng = self.engine
        deciding_team = eng.decision_team
        policy_decides = deciding_team == self.seat.seat
        if policy_decides == (human_index is not None):
            raise IntegrityError("tick called for the wrong coach")
        legal = eng.legal() if not policy_decides else None
        pre_match = bytes(eng.match())
        out = _seat_step(self.seat, eng, policy_decides)   # one forward per c_step
        if policy_decides:
            tup = tuple(out["tuple"])
            actor = "policy"
        else:
            tup = legal[human_index].tuple
            actor = "human"
        idx = eng.tuple_index(*tup)
        if idx < 0:
            raise IntegrityError(f"{actor} tuple {tup} outside exact support ({idx})")
        action = eng.legal()[idx] if legal is None else legal[idx]
        rc = eng.step(*tup)
        if rc < 0:
            raise IntegrityError(f"engine refused {actor} tuple {tup}: rc={rc}")
        self._pre_states.append(pre_match)
        record = {
            "step": self.version, "decision_team": deciding_team, "actor": actor,
            "action": [action.type, action.arg, action.x, action.y],
            "action_type": action.type_name, "tuple": list(tup),
            "digest": f"{eng.digest():016x}", "policy_forward": self.seat.forwards,
        }
        if out.get("value") is not None:
            record["policy_value"] = round(out["value"], 6)
        if policy_decides and out.get("logprob") is not None:
            record["policy_logprob"] = round(out["logprob"], 6)
        if policy_decides and out.get("logits") is not None:
            self.policy_logits[self.version] = out["logits"]
        self.trace.append(record)
        self.version += 1
        if rc == E.STEP_TERMINAL:
            self.over = True
            final = eng.final_match()
            counters = eng.counters()
            self.result = {
                "score": [int(final.score[0]), int(final.score[1])],
                "natural_completion": final.status == E.STATUS_MATCH_OVER,
                "final_status": int(final.status), "half": int(final.half),
                "turns": [int(final.turn[0]), int(final.turn[1])],
                "decisions": counters["decisions_at_terminal"],
            }
        return rc

    def _advance(self):
        n = 0
        while not self.over and self.engine.status == E.STATUS_DECISION and \
                self.engine.decision_team == self.seat.seat:
            self._tick(None)
            n += 1
        if not self.over and self.engine.status != E.STATUS_DECISION:
            raise IntegrityError(f"engine left DECISION without terminal: "
                                 f"status={self.engine.status}")
        return n

    # ---- JSON API --------------------------------------------------------
    def awaiting(self):
        if self.over:
            return "over"
        return "human" if self.engine.decision_team == self.human_seat else "policy"

    def state(self):
        match = self.engine.final_match() if self.over else self.engine.match()
        out = match_json(self.engine, match)
        out.update({"state_version": self.version, "awaiting": self.awaiting(),
                    "human_seat": self.human_seat, "result": self.result})
        return out

    def _prompt(self, match, obs):
        top = match.stack[match.stack_top - 1] if match.stack_top > 0 else None
        if top is None:
            return {"kind": "unknown"}
        proc = E.PROCS[top.proc]
        kind = PROMPTS.get((proc, int(top.phase))) or PROMPTS.get((proc, None)) or "unknown"
        prompt = {"kind": kind, "proc": proc, "phase": int(top.phase)}
        if proc in ("MOVE", "ACTIVATION") and top.a < 32:
            prompt["player"] = int(top.a)
            if proc == "MOVE":
                prompt["act_kind"] = E.ACT_KINDS[top.b] if top.b < len(E.ACT_KINDS) else int(top.b)
        if proc == "BLOCK":
            nd = ((top.data >> 9) & 3) + 1
            faces = [(top.data >> (3 * i)) & 7 for i in range(nd)]
            prompt["dice"] = [BLOCK_FACES.get(f, f) for f in faces]
            prompt["defender_chooses"] = bool((top.data >> 11) & 1)
            prompt["attacker"], prompt["defender"] = int(top.a), int(top.b)
        if proc == "TEST":
            prompt["test_kind"] = int(obs[784 + 21]) - 1
            prompt["target"] = int(obs[768 + 8])
        if kind == "setup" or kind in ("solid_defence", "quick_snap"):
            prompt["placements_left"] = max(0, int(obs[784 + 27]) - 1)
        if kind == "apothecary_result":
            prompt["rolls"] = [int(obs[784 + 24]), int(obs[784 + 25])]
        return prompt

    def _annotate(self, la, match, prompt, option_table):
        name = la.type_name
        item = {"id": la.index, "type": name, "surface": SURFACE.get(name, "dialog"),
                "arg": la.arg, "x": la.x, "y": la.y}
        mover = prompt.get("player")
        is_blitz = prompt.get("act_kind") == "BLITZ"
        if name in ("SETUP_PLACE", "SETUP_REMOVE", "ACTIVATE"):
            item["player"] = la.arg
        if name == "TOUCHBACK":
            if la.arg == 0xFF:
                item["surface"] = "square"
            else:
                item["player"] = la.arg
        if name in ("SETUP_REMOVE", "ACTIVATE", "DECLARE", "END_TURN", "STAND_UP",
                    "END_ACTIVATION", "SETUP_DONE", "FOLLOW_UP", "DECLINE_REROLL",
                    "APOTHECARY", "CHOOSE_DIE", "USE_REROLL", "USE_SKILL",
                    "DECLINE_SKILL", "CHOOSE_OPTION"):
            item["x"] = item["y"] = None
        if name == "DECLARE":
            item["kind"] = E.ACT_KINDS[la.arg] if la.arg < len(E.ACT_KINDS) else la.arg
        elif name == "STEP" and mover is not None:
            tests, probs = self.engine.step_success(mover, la.x, la.y, is_blitz)
            item["rush"] = tests[0] or None
            item["dodge"] = tests[1] or None
            item["pickup"] = tests[2] or None
            item["p_success"] = round(probs[0] * probs[1] * probs[2], 4)
        elif name in ("BLOCK_TARGET", "FOUL_TARGET", "HANDOFF_TARGET", "SPECIAL_TARGET",
                      "PASS_TARGET", "TTM_TARGET"):
            target = int(match.grid[la.x][la.y]) - 1
            item["target_player"] = target if target >= 0 else None
            if name == "BLOCK_TARGET" and target >= 0 and mover is not None:
                item["ev"] = self.engine.block_ev(mover, target, is_blitz)
            if name == "SPECIAL_TARGET":
                item["variant"] = SPECIAL_VARIANTS.get(la.arg, la.arg)
        elif name == "CHOOSE_DIE":
            dice = prompt.get("dice", [])
            item["die_index"] = la.arg
            item["face"] = dice[la.arg] if la.arg < len(dice) else None
        elif name == "PUSH_SQUARE":
            item["push_kind"] = PUSH_KINDS.get(la.arg, la.arg)
        elif name == "FOLLOW_UP":
            item["follow"] = bool(la.arg)
        elif name == "USE_REROLL":
            item["source"] = E.REROLL_SOURCES[la.arg] if la.arg < len(E.REROLL_SOURCES) else la.arg
            if la.arg == 1:
                item["skill"] = self.engine.skill_display(la.x)
        elif name in ("USE_SKILL", "DECLINE_SKILL"):
            item["skill"] = self.engine.skill_display(la.arg)
        elif name == "APOTHECARY":
            item["use"] = bool(la.arg)
        elif name == "CHOOSE_OPTION":
            item["option"] = None if la.arg == 0xFE else la.arg
            item["decline"] = la.arg == 0xFE
            if prompt["kind"] in ("high_kick", "interception_choice") and la.arg < 16:
                item["player"] = option_table[la.arg]
        return item

    def legal(self):
        base = {"state_version": self.version, "awaiting": self.awaiting(),
                "human_seat": self.human_seat}
        if self.over or self.awaiting() != "human":
            base.update({"prompt": None, "actions": [], "groups": {}})
            return base
        eng = self.engine
        match = eng.match()
        obs = eng.obs(self.human_seat)
        prompt = self._prompt(match, obs)
        option_table = _option_table(obs, self.human_seat)
        actions = [self._annotate(la, match, prompt, option_table) for la in eng.legal()]
        groups = {}
        for item in actions:
            groups.setdefault(item["type"], []).append(item["id"])
            self.presented_types.add(item["type"])
        for type_name in groups:
            self.presented_counts[type_name] += 1
        self.presented_prompts.add(prompt["kind"])
        base.update({"prompt": prompt, "actions": actions, "groups": groups})
        return base

    def submit(self, request):
        if self.over:
            return self._reject("match_over")
        if self.engine.decision_team != self.human_seat:
            return self._reject("not_your_decision")
        if request.get("state_version") != self.version:
            return self._reject("stale_state_version")
        legal = self.engine.legal()
        idx = request.get("action_id")
        if idx is None and isinstance(request.get("action"), dict):
            a = request["action"]
            want = (a.get("type"), a.get("arg"), a.get("x"), a.get("y"))
            idx = next((la.index for la in legal if (la.type, la.arg, la.x, la.y) == want), None)
        if not isinstance(idx, int) or not 0 <= idx < len(legal):
            return self._reject("unknown_action")
        self.submitted_types.add(legal[idx].type_name)
        before = self.version
        self._tick(idx)
        policy_steps = self._advance()
        return {"ok": True, "state_version": self.version, "over": self.over,
                "applied": self.trace[before:], "policy_steps": policy_steps}

    def _reject(self, reason):
        self.api_rejections += 1
        return {"ok": False, "error": reason, "state_version": self.version}

    def bot_suggestion(self):
        """Contact-bot action id for the current human decision (drivers, hints)."""
        if self.awaiting() != "human":
            return None
        return self.engine.contact_bot_index()

    # ---- feedback --------------------------------------------------------
    def flag(self, note="", step=None):
        policy_steps = [r["step"] for r in self.trace if r["actor"] == "policy"]
        if step is None:
            if not policy_steps:
                return {"ok": False, "error": "no_policy_move"}
            step = policy_steps[-1]
        if not 0 <= step < len(self.trace):
            return {"ok": False, "error": "unknown_step"}
        rec = self.trace[step]
        logits = self.policy_logits.get(step)
        entry = {"step": step, "note": str(note), "flagged_at": time.time(),
                 "record": rec, "pre_state_hex": self._pre_states[step].hex(),
                 "has_logits": logits is not None}
        self.flags.append(entry)
        return {"ok": True, "flag_index": len(self.flags) - 1, "step": step}

    def survey(self, answers):
        self.survey_answers = dict(answers)
        return {"ok": True}

    def integrity(self):
        c = self.engine.counters()
        return {"illegal": c["illegal"], "projection_collision": c["projection_collision"],
                "error_episodes": c["error_episodes"],
                "engine_rejections": c["rejected_submissions"],
                "precheck_collisions": c["precheck_collisions"],
                "api_rejections": self.api_rejections,
                "forwards": self.seat.forwards, "c_steps": self.version,
                "natural_completion": bool(self.result and self.result["natural_completion"])}

    def header(self):
        return {"schema": SCHEMA, "params": self.params, "human_seat": self.human_seat,
                "policy_seat": self.seat.seat, "policy_mode": self.seat.mode,
                "policy": self.seat.provenance, "obs_version": E.OBS_VERSION,
                "started_at": self.started_at, "meta": self.meta}

    def save(self, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        doc = {"header": self.header(), "result": self.result, "integrity": self.integrity(),
               "trace": self.trace, "flags": self.flags, "survey": self.survey_answers}
        with open(os.path.join(out_dir, "game.json"), "w") as f:
            json.dump(doc, f, indent=1)
        if self.policy_logits:
            steps = np.array(sorted(self.policy_logits), dtype=np.int32)
            logits = np.stack([self.policy_logits[s] for s in steps])
            np.savez_compressed(os.path.join(out_dir, "policy_logits.npz"),
                                steps=steps, logits=logits)
        return out_dir


def replay_trace(header, trace):
    """Re-apply a recorded trace on a fresh engine; return the first digest
    mismatch as (step, want, got) or None when every step reproduces."""
    p = header["params"]
    eng = E.Engine(p["seed"], episode=p["episode"], home_team=p["home_team"],
                   away_team=p["away_team"], max_decisions=p["max_decisions"])
    for rec in trace:
        rc = eng.step(*rec["tuple"])
        got = f"{eng.digest():016x}"
        if rc < 0 or got != rec["digest"]:
            return rec["step"], rec["digest"], got
    return None
