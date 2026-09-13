"""One human-vs-policy match with a JSON API.

The session owns the engine and two seats: an external human (any client that
speaks the JSON API) and a policy seat. Exactly one policy forward happens per
env c_step, whoever decides (native evaluation-mode recurrence). The human can
only submit an action id taken from the legal list of the current state
version, so an illegal engine action can never reach c_step.

API (all payloads JSON-serializable):
  state()               match state in absolute pitch coordinates
  legal()               prompt + legal actions annotated and grouped for a UI
  submit(request)       {"action_id", "state_version"} or {"action": {...}, ...};
                        optional "follow": {"type", "arg"} applies a second legal
                        action when it is offered next (ACTIVATE then DECLARE,
                        DECLINE_REROLL then CHOOSE_DIE)
  submit_path(request)  {"state_version", "player", "squares": [[x, y], ...]}:
                        one STEP per square while the move prompt continues
  clock_end_turn()      the soft turn clock: ends the human's team turn through
                        legal actions only
  decision_view(step)   the policy's options at one of its decisions
  flag(note, step, reasons)  record state + the policy's action and options
  survey(answers)       post-game survey answers
  save(out_dir, extra)  game.json + policy_logits.npz
"""
from __future__ import annotations

import json
from collections import Counter
import os
import time

import numpy as np

from . import engine as E
from . import narrate as N
from .alternatives import conditional_argmax_row, legal_array, ranked
from .policy import NONE_TUPLE, PolicySeat

SCHEMA = "bbplay-game-v1"
FLAG_SCHEMA = "bbplay-flag-v1"

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

# Soft turn clock: when time runs out the first offered action type in this
# order is applied, repeatedly, until the human's team turn is over. Windows
# with none of these (block dice, push squares, forced declarations) fall back
# to the engine's contact-bot choice, which is always a member of the legal set.
CLOCK_PRIORITY = ("END_TURN", "END_ACTIVATION", "DECLINE_REROLL", "DECLINE_SKILL")

BOOKKEEPING = {"END_ACTIVATION", "DECLINE_REROLL", "DECLINE_SKILL"}


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
        "in_team_turn": [N.in_team_turn(match, 0), N.in_team_turn(match, 1)],
        "in_kickoff": any(E.PROCS[match.stack[i].proc] == "KICKOFF" for i in range(match.stack_top)),
        "players": players,
    }


def formation(match, team):
    """Setup checklist numbers for one team, wide zones named from the coach's facing."""
    los_x = 12 if team == 0 else 13
    base = team * 16
    on_pitch = los = low_y = high_y = available = 0
    for s in range(base, base + 16):
        p = match.players[s]
        if p.location in (0, 1):
            available += 1
        if p.location != 0:
            continue
        on_pitch += 1
        if p.x == los_x and 4 <= p.y <= 10:
            los += 1
        if p.y <= 3:
            low_y += 1
        if p.y >= 11:
            high_y += 1
    left, right = (low_y, high_y) if team == 0 else (high_y, low_y)
    return {"on_pitch": on_pitch, "want_on_pitch": min(11, available), "los": los,
            "want_los": min(3, on_pitch), "left_wide": left, "right_wide": right,
            "max_wide": 2, "los_x": los_x, "half_x": [0, 12] if team == 0 else [13, 25],
            "left_is_low_y": team == 0}


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
                 away_team=-1, max_decisions=4096, meta=None, observer=None):
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
        self.observer = observer
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
        self.policy_windows = {}
        self._pre_states = []
        self._legal_cache = None
        self.started_at = time.time()
        self._advance()

    # ---- core loop -------------------------------------------------------
    def _tick(self, human_index=None, actor=None):
        eng = self.engine
        deciding_team = eng.decision_team
        policy_decides = deciding_team == self.seat.seat
        if policy_decides == (human_index is not None):
            raise IntegrityError("tick called for the wrong coach")
        legal = eng.legal()
        pre_bytes = bytes(eng.match())
        pre = E.BbMatch.from_buffer_copy(pre_bytes)
        out = _seat_step(self.seat, eng, policy_decides)   # one forward per c_step
        if policy_decides:
            tup = tuple(out["tuple"])
            actor = "policy"
        else:
            tup = legal[human_index].tuple
            actor = actor or "human"
        idx = eng.tuple_index(*tup)
        if idx < 0:
            raise IntegrityError(f"{actor} tuple {tup} outside exact support ({idx})")
        action = legal[idx]
        tests = self._step_tests(pre, action)
        rc = eng.step(*tup)
        if rc < 0:
            raise IntegrityError(f"engine refused {actor} tuple {tup}: rc={rc}")
        self._pre_states.append(pre_bytes)
        self._legal_cache = None
        record = {
            "step": self.version, "decision_team": deciding_team, "actor": actor,
            "action": [action.type, action.arg, action.x, action.y],
            "action_type": action.type_name, "tuple": list(tup),
            "digest": f"{eng.digest():016x}", "policy_forward": self.seat.forwards,
        }
        if tests:
            record["tests"] = tests
        if out.get("value") is not None:
            record["policy_value"] = round(out["value"], 6)
        if policy_decides and out.get("logprob") is not None:
            record["policy_logprob"] = round(out["logprob"], 6)
        if policy_decides:
            self.policy_windows[self.version] = legal_array(legal)
            if out.get("logits") is not None:
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
        if self.observer is not None:
            self.observer(self, record, pre)
        return rc

    def _step_tests(self, pre, action):
        if action.type_name not in ("STEP", "JUMP"):
            return None
        top = N.top_frame(pre)
        if top is None or E.PROCS[top.proc] != "MOVE" or top.a >= 32:
            return None
        blitz = top.b < len(E.ACT_KINDS) and E.ACT_KINDS[top.b] == "BLITZ"
        tests, probs = self.engine.step_success(int(top.a), action.x, action.y, blitz)
        if not any(tests):
            return None
        return {"rush": bool(tests[0]), "dodge": bool(tests[1]), "pickup": bool(tests[2]),
                "p": [round(v, 4) for v in probs]}

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

    def current_match(self):
        return self.engine.final_match() if self.over else self.engine.match()

    def state(self):
        match = self.current_match()
        out = match_json(self.engine, match)
        out.update({"state_version": self.version, "awaiting": self.awaiting(),
                    "human_seat": self.human_seat, "result": self.result})
        return out

    def _prompt(self, match, obs):
        top = match.stack[match.stack_top - 1] if match.stack_top > 0 else None
        if top is None:
            return {"kind": "unknown"}
        eng = self.engine
        proc = E.PROCS[top.proc]
        kind = PROMPTS.get((proc, int(top.phase))) or PROMPTS.get((proc, None)) or "unknown"
        prompt = {"kind": kind, "proc": proc, "phase": int(top.phase)}
        if proc in ("MOVE", "ACTIVATION") and top.a < 32:
            prompt["player"] = int(top.a)
            if proc == "MOVE":
                prompt["act_kind"] = E.ACT_KINDS[top.b] if top.b < len(E.ACT_KINDS) else int(top.b)
            if proc == "ACTIVATION" and int(top.phase) == 2:
                prompt["target"] = int(obs[768 + 8])
        if proc == "BLOCK":
            nd = ((top.data >> 9) & 3) + 1
            faces = [(top.data >> (3 * i)) & 7 for i in range(nd)]
            prompt["dice"] = [BLOCK_FACES.get(f, f) for f in faces]
            prompt["dice_keys"] = [N.FACE_KEYS.get(f, "push") for f in faces]
            prompt["defender_chooses"] = bool((top.data >> 11) & 1)
            prompt["attacker"], prompt["defender"] = int(top.a), int(top.b)
            if top.a < 32 and top.b < 32:
                pa, pd = match.players[top.a], match.players[top.b]
                prompt["strength"] = [int(pa.st) + eng.count_assists(top.a, top.b),
                                      int(pd.st) + eng.count_assists(top.b, top.a)]
        if proc == "TEST":
            prompt["test_kind"] = int(obs[784 + 21]) - 1
            prompt["target"] = int(obs[768 + 8])
            kind_i = int(top.b)
            prompt["test_name"] = N.TEST_NAMES.get(N.TEST_KINDS[kind_i], "Roll") \
                if kind_i < len(N.TEST_KINDS) else "Roll"
            if top.a < 32:
                prompt["player"] = int(top.a)
        if proc == "PUSH":
            prompt["pusher"], prompt["pushee"] = int(top.a), int(top.b)
            prompt["origin"] = [int(top.x), int(top.y)]
            if int(top.phase) == 3:
                prompt["vacated"] = [int(top.x), int(top.y)]
        if proc in ("CASUALTY", "KO_RECOVERY") and top.a < 32:
            prompt["player"] = int(top.a)
        if proc == "FOUL":
            prompt["player"], prompt["victim"] = int(top.a), int(top.b)
        if proc == "PASS":
            prompt["player"] = int(top.a)
            prompt["target_square"] = [int(top.x), int(top.y)]
        if kind == "setup" or kind in ("solid_defence", "quick_snap", "charge"):
            prompt["placements_left"] = max(0, int(obs[784 + 27]) - 1)
        if kind == "setup":
            prompt["formation"] = formation(match, self.human_seat)
            prompt["budget"] = 24
            prompt["kicking"] = int(match.kicking_team) == self.human_seat
        if kind == "apothecary_result":
            prompt["rolls"] = [int(obs[784 + 24]), int(obs[784 + 25])]
        if kind == "apothecary":
            prompt["rolls"] = [int(obs[784 + 24])]
        return prompt

    def _annotate(self, la, match, prompt, option_table):
        name = la.type_name
        item = {"id": la.index, "type": name, "surface": SURFACE.get(name, "dialog"),
                "arg": la.arg, "x": la.x, "y": la.y}
        mover = prompt.get("player")
        is_blitz = prompt.get("act_kind") == "BLITZ"
        if name in ("SETUP_PLACE", "SETUP_REMOVE", "ACTIVATE"):
            item["player"] = la.arg
        if name == "ACTIVATE":
            after = self.engine.peek_legal(*la.tuple)
            item["declare"] = sorted({E.ACT_KINDS[a.arg] for a in (after or [])
                                      if a.type_name == "DECLARE"})
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
        if name != "SETUP_PLACE":
            item["label"] = N.label_action(self.engine, match, la.type, la.arg, la.x, la.y)
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
                p_att, p_def = match.players[mover], match.players[target]
                att = int(p_att.st) + self.engine.count_assists(mover, target)
                dfn = int(p_def.st) + self.engine.count_assists(target, mover)
                dice = 1 if att == dfn else (2 if max(att, dfn) <= 2 * min(att, dfn) else 3)
                item["dice"] = dice
                item["who_picks"] = "you" if att >= dfn else "them"
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
                if item["player"] is not None:
                    item["label"] = N.player_name(self.engine, match, item["player"])
        return item

    def _reach(self, mover):
        dodges, gfis, length, prev = self.engine.reach(mover)
        squares = []
        for i in np.nonzero(length)[0].tolist():
            if dodges[i] == 0xFF:
                continue
            squares.append([i % E.PITCH_LEN, i // E.PITCH_LEN, int(length[i]), int(dodges[i]),
                            int(gfis[i]), int(prev[i][0]), int(prev[i][1])])
        return squares

    def legal(self):
        if self._legal_cache is not None and self._legal_cache[0] == self.version:
            return self._legal_cache[1]
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
        if prompt["kind"] == "move" and "player" in prompt and "STEP" in groups:
            prompt["reach"] = self._reach(prompt["player"])
        if prompt["kind"] in ("select_player", "charge"):
            prompt["can_act"] = len(groups.get("ACTIVATE", []))
            ball = match.ball
            if ball.state == 2 and ball.carrier < 32 and (ball.carrier >> 4) == self.human_seat:
                carrier = int(ball.carrier)
                activatable = {a["player"] for a in actions if a["type"] == "ACTIVATE"}
                if carrier in activatable and eng.can_score_without_dice(carrier):
                    prompt["stalling_carrier"] = carrier
        # Setup offers every (reserve player x free square) pair, thousands of
        # actions; they travel as compact [id, player, x, y] rows instead.
        compact = {}
        if "SETUP_PLACE" in groups:
            compact["SETUP_PLACE"] = [[a["id"], a["arg"], a["x"], a["y"]] for a in actions
                                      if a["type"] == "SETUP_PLACE"]
            actions = [a for a in actions if a["type"] != "SETUP_PLACE"]
        base.update({"prompt": prompt, "actions": actions, "groups": groups, "compact": compact})
        self._legal_cache = (self.version, base)
        return base

    def _check_request(self, request):
        if self.over:
            return self._reject("match_over")
        if self.engine.decision_team != self.human_seat:
            return self._reject("not_your_decision")
        if request.get("state_version") != self.version:
            return self._reject("stale_state_version")
        return None

    def submit(self, request):
        bad = self._check_request(request)
        if bad:
            return bad
        legal = self.engine.legal()
        idx = request.get("action_id")
        if idx is None and isinstance(request.get("action"), dict):
            a = request["action"]
            want = (a.get("type"), a.get("arg"), a.get("x"), a.get("y"))
            idx = next((la.index for la in legal if (la.type, la.arg, la.x, la.y) == want), None)
        if isinstance(idx, bool) or not isinstance(idx, int) or not 0 <= idx < len(legal):
            return self._reject("unknown_action")
        self.submitted_types.add(legal[idx].type_name)
        before = self.version
        self._tick(idx)
        policy_steps = self._advance()
        follow = request.get("follow")
        followed = False
        if isinstance(follow, dict) and not self.over and self.awaiting() == "human":
            want_type, want_arg = follow.get("type"), follow.get("arg")
            nxt = next((la for la in self.engine.legal()
                        if la.type_name == want_type and la.arg == want_arg), None)
            if nxt is not None:
                self.submitted_types.add(nxt.type_name)
                self._tick(nxt.index)
                policy_steps += self._advance()
                followed = True
        return {"ok": True, "state_version": self.version, "over": self.over,
                "applied": self.trace[before:], "policy_steps": policy_steps,
                "followed": followed}

    def submit_path(self, request):
        bad = self._check_request(request)
        if bad:
            return bad
        player = request.get("player")
        squares = request.get("squares")
        if not isinstance(player, int) or not isinstance(squares, list) or not squares:
            return self._reject("bad_path")
        before = self.version
        done = 0
        policy_steps = 0
        for sq in squares[:32]:
            if self.over or self.awaiting() != "human":
                break
            if not (isinstance(sq, (list, tuple)) and len(sq) == 2):
                break
            match = self.engine.match()
            top = N.top_frame(match)
            if top is None or E.PROCS[top.proc] != "MOVE" or int(top.a) != player:
                break
            step = next((la for la in self.engine.legal()
                         if la.type_name == "STEP" and (la.x, la.y) == (sq[0], sq[1])), None)
            if step is None:
                break
            self.submitted_types.add("STEP")
            self._tick(step.index)
            policy_steps += self._advance()
            done += 1
            if not self.over:
                p = self.engine.match().players[player]
                if p.location != 0 or (p.x, p.y) != (sq[0], sq[1]) or p.stance != 0:
                    break
        if done == 0:
            return self._reject("path_not_legal")
        return {"ok": True, "state_version": self.version, "over": self.over,
                "applied": self.trace[before:], "policy_steps": policy_steps,
                "steps_applied": done, "steps_requested": len(squares)}

    def turn_key(self):
        """(half, turn) while the human's own team turn is in progress, else None."""
        if self.over:
            return None
        match = self.engine.match()
        if not N.in_team_turn(match, self.human_seat):
            return None
        return (int(match.half), int(match.turn[self.human_seat]))

    def clock_end_turn(self, max_steps=600):
        """End the human's team turn through legal actions (soft turn clock)."""
        key = self.turn_key()
        if key is None or self.awaiting() != "human":
            return {"ok": False, "error": "not_your_turn", "state_version": self.version}
        before = self.version
        n = 0
        while not self.over and self.awaiting() == "human" and self.turn_key() == key:
            legal = self.engine.legal()
            by_type = {}
            for la in legal:
                by_type.setdefault(la.type_name, la)
            pick = next((by_type[t] for t in CLOCK_PRIORITY if t in by_type), None)
            if pick is None:
                if "DECLARE" in by_type:
                    pick = next((la for la in legal if la.type_name == "DECLARE" and la.arg == 0),
                                by_type["DECLARE"])
                else:
                    idx = self.engine.contact_bot_index()
                    if idx < 0:
                        raise IntegrityError("clock found no legal action")
                    pick = legal[idx]
            self._tick(pick.index, actor="clock")
            self._advance()
            n += 1
            if n > max_steps:
                raise IntegrityError("clock could not end the turn")
        return {"ok": True, "state_version": self.version, "over": self.over,
                "applied": self.trace[before:], "clock_steps": n}

    def _reject(self, reason):
        self.api_rejections += 1
        return {"ok": False, "error": reason, "state_version": self.version}

    def bot_suggestion(self):
        """Contact-bot action id for the current human decision (drivers, hints)."""
        if self.awaiting() != "human":
            return None
        return self.engine.contact_bot_index()

    # ---- policy decision views ------------------------------------------
    def pre_match(self, step):
        return E.BbMatch.from_buffer_copy(self._pre_states[step])

    def _ranked_lines(self, step):
        logits = self.policy_logits.get(step)
        rows = self.policy_windows.get(step)
        if logits is None or rows is None:
            return None
        pre = self.pre_match(step)
        rec = self.trace[step]
        taken = tuple(rec["tuple"])
        lines = []
        argmax = conditional_argmax_row(logits, rows)
        for i, p in ranked(logits, rows):
            row = rows[i]
            tup = (int(row[0]), int(row[4]), int(row[5]))
            lines.append({"label": N.label_action(self.engine, pre, int(row[0]), int(row[1]),
                                                  int(row[2]), int(row[3])),
                          "p": p, "taken": tup == taken, "argmax": i == argmax,
                          "action": [int(row[0]), int(row[1]), int(row[2]), int(row[3])]})
        return lines

    def decision_view(self, step, k=5):
        """The policy's options at one of its decisions, exact over the joint support.

        An ACTIVATE decision and the DECLARE that follows it are joined into one
        list: "Blitz with #6 Blitzer" carries p(activate #6) * p(blitz | #6).
        """
        if not 0 <= step < len(self.trace) or self.trace[step]["actor"] != "policy":
            return None
        rec = self.trace[step]
        if rec["action_type"] == "ACTIVATE" and step + 1 < len(self.trace) and \
                self.trace[step + 1]["actor"] == "policy" and \
                self.trace[step + 1]["action_type"] == "DECLARE":
            step, rec = step + 1, self.trace[step + 1]
        lines = self._ranked_lines(step)
        joined = False
        if lines is None:
            return {"step": step, "record": rec, "alternatives": [], "value": rec.get("policy_value"),
                    "taken_rank": None, "sampled_first": None, "mode": self.seat.mode,
                    "joined": False}
        if rec["action_type"] == "DECLARE" and step > 0 and \
                self.trace[step - 1]["actor"] == "policy" and \
                self.trace[step - 1]["action_type"] == "ACTIVATE":
            act_lines = self._ranked_lines(step - 1)
            if act_lines:
                chosen = next((ln for ln in act_lines if ln["taken"]), None)
                if chosen is not None:
                    joined = True
                    merged = [dict(ln, p=ln["p"] * chosen["p"]) for ln in lines]
                    merged += [ln for ln in act_lines if not ln["taken"]]
                    lines = sorted(merged, key=lambda ln: -ln["p"])
        for rank, ln in enumerate(lines, 1):
            ln["rank"] = rank
        taken = next((ln for ln in lines if ln["taken"]), None)
        top = [dict(ln, p=round(ln["p"], 5)) for ln in lines[:k]]
        if taken is not None and taken["rank"] > k:
            top.append(dict(taken, p=round(taken["p"], 5)))
        return {"step": step, "record": rec, "alternatives": top,
                "value": rec.get("policy_value"),
                "taken_rank": taken["rank"] if taken else None,
                "sampled_first": bool(taken and taken["rank"] == 1),
                "argmax_taken": bool(taken and taken.get("argmax")),
                "options": len(lines), "mode": self.seat.mode, "joined": joined}

    # ---- feedback --------------------------------------------------------
    def flag(self, note="", step=None, reasons=None):
        policy_steps = [r["step"] for r in self.trace if r["actor"] == "policy"]
        if step is None:
            if not policy_steps:
                return {"ok": False, "error": "no_policy_move"}
            step = policy_steps[-1]
        if isinstance(step, bool) or not isinstance(step, int) or not 0 <= step < len(self.trace):
            return {"ok": False, "error": "unknown_step"}
        rec = self.trace[step]
        if rec["actor"] != "policy":
            return {"ok": False, "error": "not_a_policy_step"}
        logits = self.policy_logits.get(step)
        entry = {"schema": FLAG_SCHEMA, "step": step, "note": str(note)[:4000],
                 "reasons": [str(r)[:64] for r in (reasons or [])][:16],
                 "flagged_at": time.time(), "record": rec,
                 "pre_state_hex": self._pre_states[step].hex(),
                 "has_logits": logits is not None,
                 "view": self.decision_view(step)}
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

    def save(self, out_dir, extra=None):
        os.makedirs(out_dir, exist_ok=True)
        doc = {"header": self.header(), "result": self.result, "integrity": self.integrity(),
               "trace": self.trace, "flags": self.flags, "survey": self.survey_answers}
        if extra:
            for key, value in extra.items():
                doc.setdefault(key, value)
        tmp = os.path.join(out_dir, "game.json.tmp")
        with open(tmp, "w") as f:
            json.dump(doc, f, indent=1)
        os.replace(tmp, os.path.join(out_dir, "game.json"))
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
