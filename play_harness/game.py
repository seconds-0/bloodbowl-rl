"""Game controller: lobby options, one match, bot playback frames, clock, records.

The controller wraps a GameSession for the web server. It adds nothing the
engine decides: rosters, sides and seeds become engine parameters, the turn
clock ends a turn through GameSession.clock_end_turn (legal actions only), and
every applied step is turned into a playback frame (state after the step, log
lines, and for policy decisions the policy's options).
"""
from __future__ import annotations

import datetime as _dt
import os
import random
import re
import secrets
import threading
import time

from . import engine as E
from . import narrate as N
from .policy import PolicySeat, load_checkpoint, read_lineage, sha256_file, verify_lineage
from .session import BOOKKEEPING, GameSession, match_json

ROOT = E.ROOT
ARTIFACTS = os.path.join(ROOT, ".play-artifacts")
CHECKPOINT_DIR = os.path.join(ARTIFACTS, "checkpoints")
GAMES_DIR = os.path.join(ARTIFACTS, "games")
DEFAULT_CHECKPOINT = os.path.join(CHECKPOINT_DIR, "chain25", "0000002999975936.bin")

ROSTER_MODES = ("random", "both", "mine")
SIDES = ("home", "away", "random")
MODES = ("sample", "argmax")
CLOCK_MODES = ("off", "display", "soft")
CLOCK_MIN_SECONDS, CLOCK_MAX_SECONDS = 15, 1800
THINK_MAX_MS = 5000
SEED_MAX = 2 ** 31 - 1
FLAG_REASONS = ("Too risky", "Wrong player", "Better move existed", "Wasted time",
                "Looks like a bug")
SURVEY_KEYS = {"strength": (1, 2, 3, 4, 5), "ball_protection": ("yes", "sometimes", "no"),
               "stalling": ("yes", "no")}


class OptionError(ValueError):
    pass


def team_list(lib=None):
    lib = lib or E.load_library()
    out = []
    for tid in range(lib.bbp_team_count()):
        name = lib.bbp_team_display(tid)
        key = lib.bbp_team_key(tid)
        out.append({"id": tid, "name": name.decode() if name else str(tid),
                    "key": key.decode() if key else str(tid)})
    return out


_CKPT_CACHE = {}


def list_checkpoints(dirs=None):
    """Local checkpoints that carry a lineage sidecar, newest first by step."""
    found = []
    for base in dirs or [CHECKPOINT_DIR]:
        if not os.path.isdir(base):
            continue
        for dirpath, _, files in os.walk(base):
            for fn in files:
                if not fn.endswith(".bin") or fn + ".lineage.json" not in files:
                    continue
                path = os.path.join(dirpath, fn)
                st = os.stat(path)
                key = (path, st.st_mtime, st.st_size)
                if key not in _CKPT_CACHE:
                    info = {"path": path, "name": os.path.basename(dirpath) or fn,
                            "file": fn, "bytes": st.st_size}
                    try:
                        lineage = read_lineage(path)
                        digest = sha256_file(path)
                        verify_lineage(path, lineage, digest)
                        info.update({"sha8": digest[:8], "ok": True, "error": None,
                                     "obs": lineage["compatibility"]["observation_abi"],
                                     "action_abi": lineage["compatibility"]["action_abi"]})
                    except (ValueError, KeyError, OSError) as exc:
                        info.update({"sha8": None, "ok": False, "error": str(exc)})
                    m = re.match(r"(\d+)\.bin$", fn)
                    info["step"] = int(m.group(1)) if m else None
                    info["label"] = _checkpoint_label(info)
                    _CKPT_CACHE[key] = info
                found.append(_CKPT_CACHE[key])
    found.sort(key=lambda c: (c["path"] != DEFAULT_CHECKPOINT, c["name"], -(c["step"] or 0)))
    return found


def _checkpoint_label(info):
    name = info["name"].replace("chain", "Chain ").replace("_", " ").strip()
    if info.get("step"):
        return f"{name} · {info['step'] / 1e9:.2f}B steps"
    return name


def normalize_options(raw, n_teams=30, checkpoints=None):
    """Validate lobby options; return a complete, JSON-serializable dict."""
    raw = dict(raw or {})
    opts = {}
    ck = raw.get("checkpoint") or DEFAULT_CHECKPOINT
    if checkpoints is not None:
        allowed = {c["path"]: c for c in checkpoints}
        if ck not in allowed:
            raise OptionError("unknown_checkpoint")
        if not allowed[ck]["ok"]:
            raise OptionError("checkpoint_lineage_invalid")
    opts["checkpoint"] = ck
    mode = raw.get("roster_mode", "random")
    if mode not in ROSTER_MODES:
        raise OptionError("bad_roster_mode")
    opts["roster_mode"] = mode

    def team(key):
        v = raw.get(key)
        if isinstance(v, bool) or not isinstance(v, int) or not 0 <= v < n_teams:
            raise OptionError(f"bad_{key}")
        return v

    opts["human_team"] = team("human_team") if mode in ("both", "mine") else None
    opts["bot_team"] = team("bot_team") if mode == "both" else None
    side = raw.get("human_side", "home")
    if side not in SIDES:
        raise OptionError("bad_human_side")
    opts["human_side"] = side
    play = raw.get("mode", "sample")
    if play not in MODES:
        raise OptionError("bad_mode")
    opts["mode"] = play
    think = raw.get("think_ms", 600)
    if isinstance(think, bool) or not isinstance(think, (int, float)) or not 0 <= think <= THINK_MAX_MS:
        raise OptionError("bad_think_ms")
    opts["think_ms"] = int(think)
    clock = raw.get("clock_mode", "display")
    if clock not in CLOCK_MODES:
        raise OptionError("bad_clock_mode")
    opts["clock_mode"] = clock
    secs = raw.get("clock_seconds", 240)
    if isinstance(secs, bool) or not isinstance(secs, (int, float)) or \
            not CLOCK_MIN_SECONDS <= secs <= CLOCK_MAX_SECONDS:
        raise OptionError("bad_clock_seconds")
    opts["clock_seconds"] = int(secs)
    seed = raw.get("seed")
    if seed in (None, ""):
        seed = secrets.randbelow(SEED_MAX - 1) + 1
    if isinstance(seed, str) and seed.strip().isdigit():
        seed = int(seed.strip())
    if isinstance(seed, bool) or not isinstance(seed, int) or not 1 <= seed <= SEED_MAX:
        raise OptionError("bad_seed")
    opts["seed"] = seed
    opts["kernel"] = raw.get("kernel", "native") if raw.get("kernel") in ("native", "torch") else "native"
    return opts


def resolve_match(opts):
    """Lobby options -> engine and seat parameters. Deterministic in the seed."""
    rng = random.Random(opts["seed"])
    side = opts["human_side"]
    if side == "random":
        side = rng.choice(("home", "away"))
    human_seat = 0 if side == "home" else 1
    human_team = opts["human_team"] if opts["roster_mode"] in ("both", "mine") else -1
    bot_team = opts["bot_team"] if opts["roster_mode"] == "both" else -1
    home_team, away_team = (human_team, bot_team) if human_seat == 0 else (bot_team, human_team)
    policy_seed = (opts["seed"] * 2654435761 + 97) % SEED_MAX
    return {"human_seat": human_seat, "side": side, "home_team": home_team,
            "away_team": away_team, "engine_seed": opts["seed"], "policy_seed": policy_seed}


_POLICIES = {}
_POLICY_LOCK = threading.Lock()


def default_policy_loader(path, kernel="native"):
    with _POLICY_LOCK:
        key = (path, kernel)
        if key not in _POLICIES:
            _POLICIES[key] = load_checkpoint(path, kernel=kernel)
        return _POLICIES[key]


class GameController:
    def __init__(self, options, policy_loader=None, games_dir=GAMES_DIR, now=time.monotonic,
                 save_records=True):
        self.options = options
        self.now = now
        self.games_dir = games_dir
        self.save_records = save_records
        self.lock = threading.RLock()
        self.match_params = resolve_match(options)
        loader = policy_loader or default_policy_loader
        policy, provenance = loader(options["checkpoint"], options.get("kernel", "native"))
        self.provenance = provenance
        mp = self.match_params
        seat = PolicySeat(policy, 1 - mp["human_seat"], mode=options["mode"],
                          seed=mp["policy_seed"], provenance=provenance)
        self.frames = []
        self.log = []
        self._narrator = None
        self.clock_turn = None
        self.clock_started = None
        self.clock_events = []
        meta = {"options": options, "match_params": mp, "ui": "play_harness.web v1"}
        self._booting = True
        self.session = GameSession(seat, human_seat=mp["human_seat"], seed=mp["engine_seed"],
                                   home_team=mp["home_team"], away_team=mp["away_team"],
                                   meta=meta, observer=self._observe)
        self._booting = False
        stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        teams = [t["name"] for t in self.session.state()["teams"]]
        slug = "-".join(re.sub(r"[^a-z0-9]+", "", n.lower()) for n in teams)
        self.record_dir = os.path.join(games_dir, f"{stamp}-{slug}-{options['seed']}")
        self.saved = False
        self._maybe_save()

    # ---- frames ----------------------------------------------------------
    @property
    def narrator(self):
        if self._narrator is None:
            self._narrator = N.Narrator(self.session.engine if hasattr(self, "session") else None)
        return self._narrator

    def _observe(self, session, record, pre):
        if self._narrator is None:
            self._narrator = N.Narrator(session.engine)
        post = session.current_match()
        entries = self._narrator.on_step(record, pre, post, over=session.over)
        self.log.extend(entries)
        state = match_json(session.engine, post)
        state.update({"state_version": session.version, "awaiting": session.awaiting(),
                      "human_seat": session.human_seat})
        frame = {"step": record["step"], "actor": record["actor"],
                 "team": record["decision_team"], "action_type": record["action_type"],
                 "action": record["action"], "state": state, "log": entries,
                 "think": record["actor"] == "policy" and record["action_type"] not in BOOKKEEPING}
        if record["actor"] == "policy":
            frame["pre_procedure"] = N.proc_name(pre)[0]
        self.frames.append(frame)

    def take_frames(self):
        frames, self.frames = self.frames, []
        # Policy views are computed when the frame leaves, so an ACTIVATE that is
        # followed by its DECLARE in the same batch can show the joined options.
        for fr in frames:
            if fr["actor"] == "policy":
                fr["view"] = self.session.decision_view(fr["step"])
        return frames

    # ---- snapshots -------------------------------------------------------
    def header(self):
        mp = self.match_params
        prov = {k: v for k, v in self.provenance.items() if k != "lineage"}
        lineage = self.provenance.get("lineage") or {}
        return {"options": self.options, "match": mp,
                "checkpoint": {"path": self.options["checkpoint"],
                               "sha8": (prov.get("checkpoint_sha256") or "")[:8],
                               "name": os.path.basename(os.path.dirname(self.options["checkpoint"])),
                               "kernel": prov.get("kernel"),
                               "obs": (lineage.get("compatibility") or {}).get("observation_abi")},
                "record_dir": os.path.relpath(self.record_dir, ROOT),
                "flag_reasons": list(FLAG_REASONS)}

    def snapshot(self):
        s = self.session
        out = {"header": self.header(), "state": s.state(), "legal": s.legal(),
               "log": self.log[-200:], "clock": self.clock_info(),
               "flags": self.flag_summaries()}
        if s.over:
            out["over"] = self.over_payload()
        return out

    def flag_summaries(self):
        out = []
        for i, f in enumerate(self.session.flags):
            view = f.get("view") or {}
            taken = next((a for a in view.get("alternatives", []) if a.get("taken")), None)
            pre = self.session.pre_match(f["step"])
            out.append({"index": i, "step": f["step"], "note": f["note"], "reasons": f["reasons"],
                        "label": taken["label"] if taken else f["record"]["action_type"],
                        "p": taken["p"] if taken else None,
                        "half": int(pre.half), "turn": int(pre.turn[1 - self.session.human_seat])})
        return out

    def over_payload(self):
        s = self.session
        final = s.current_match()
        stats = self.narrator.stats(final, s.engine.stall_counts(), s.human_seat)
        return {"result": s.result, "stats": stats, "integrity": s.integrity(),
                "record_dir": os.path.relpath(self.record_dir, ROOT),
                "survey": s.survey_answers}

    # ---- actions ---------------------------------------------------------
    def _after_action(self, response):
        if response.get("ok"):
            self._clock_update()
            if self.session.over:
                self._maybe_save(force=True)
        return response

    def submit(self, request):
        with self.lock:
            return self._after_action(self.session.submit(request))

    def submit_path(self, request):
        with self.lock:
            return self._after_action(self.session.submit_path(request))

    def path_odds(self, request):
        with self.lock:
            s = self.session
            if request.get("state_version") != s.version or s.awaiting() != "human":
                return {"ok": False, "error": "stale_state_version"}
            legal = s.legal()
            prompt = legal.get("prompt") or {}
            player = prompt.get("player")
            squares = request.get("squares") or []
            if prompt.get("kind") != "move" or player is None or not isinstance(squares, list):
                return {"ok": False, "error": "no_move"}
            clean = [(int(q[0]), int(q[1])) for q in squares[:32]
                     if isinstance(q, (list, tuple)) and len(q) == 2]
            steps = s.engine.path_odds(player, clean, prompt.get("act_kind") == "BLITZ")
            total = 1.0
            out = []
            for sq, st in zip(clean, steps):
                p = st["probs"][0] * st["probs"][1] * st["probs"][2]
                total *= p
                targets = [max(2, min(6, round(7 - 6 * v))) if t else None
                           for t, v in zip(st["tests"], st["probs"])]
                out.append({"x": sq[0], "y": sq[1], "rush": targets[0], "dodge": targets[1],
                            "pickup": targets[2], "p": round(p, 4)})
            return {"ok": True, "state_version": s.version, "steps": out,
                    "p_success": round(total, 4)}

    def flag(self, request):
        with self.lock:
            reasons = [r for r in (request.get("reasons") or []) if isinstance(r, str)]
            step = request.get("step")
            res = self.session.flag(note=request.get("note", ""), step=step, reasons=reasons)
            if res.get("ok"):
                self._maybe_save(force=True)
                res["flags"] = self.flag_summaries()
            return res

    def survey(self, request):
        with self.lock:
            answers = request.get("answers")
            if not isinstance(answers, dict):
                return {"ok": False, "error": "bad_survey"}
            clean = {}
            for key, allowed in SURVEY_KEYS.items():
                v = answers.get(key)
                if v is not None and (isinstance(v, bool) or type(v) is not type(allowed[0])
                                      or v not in allowed):
                    return {"ok": False, "error": f"bad_{key}"}
                clean[key] = v
            clean["rules_bugs"] = str(answers.get("rules_bugs") or "")[:4000]
            clean["notes"] = str(answers.get("notes") or "")[:4000]
            clean["saved_at"] = time.time()
            self.session.survey(clean)
            self._maybe_save(force=True)
            return {"ok": True, "record_dir": os.path.relpath(self.record_dir, ROOT)}

    def view(self, step):
        with self.lock:
            return self.session.decision_view(step)

    def replay_flag(self, index):
        with self.lock:
            s = self.session
            if not isinstance(index, int) or not 0 <= index < len(s.flags):
                return {"ok": False, "error": "unknown_flag"}
            f = s.flags[index]
            step = f["step"]
            pre = s.pre_match(step)
            post = s.pre_match(step + 1) if step + 1 < len(s._pre_states) else s.current_match()
            eng = s.engine
            return {"ok": True, "index": index, "flag": {k: v for k, v in f.items()
                                                          if k != "pre_state_hex"},
                    "pre": match_json(eng, pre), "post": match_json(eng, post)}

    # ---- turn clock ------------------------------------------------------
    def _clock_update(self):
        key = self.session.turn_key()
        if key != self.clock_turn:
            self.clock_turn = key
            self.clock_started = None

    def client_ready(self, state_version):
        """The client has finished bot playback and shows the human's options."""
        with self.lock:
            self._clock_update()
            if state_version == self.session.version and self.clock_turn is not None and \
                    self.clock_started is None and self.session.awaiting() == "human":
                self.clock_started = self.now()
            return self.clock_info()

    def clock_info(self):
        mode = self.options["clock_mode"]
        info = {"mode": mode, "seconds": self.options["clock_seconds"], "running": False,
                "used": 0.0, "remaining": None, "warn": False, "in_turn": self.clock_turn is not None}
        if mode == "off" or self.clock_turn is None or self.clock_started is None:
            return info
        used = max(0.0, self.now() - self.clock_started)
        info.update({"running": True, "used": round(used, 2)})
        if mode == "soft":
            remaining = self.options["clock_seconds"] - used
            info["remaining"] = round(max(0.0, remaining), 2)
            info["warn"] = remaining <= max(10.0, 0.2 * self.options["clock_seconds"])
        return info

    def tick_clock(self):
        """Apply the soft limit. Returns the clock response when a turn was ended."""
        with self.lock:
            if self.options["clock_mode"] != "soft" or self.clock_started is None:
                return None
            self._clock_update()
            if self.clock_turn is None or self.clock_started is None:
                return None
            if self.now() - self.clock_started < self.options["clock_seconds"]:
                return None
            res = self.session.clock_end_turn()
            if res.get("ok"):
                self.clock_events.append({"turn": list(self.clock_turn), "step": res["applied"][0]["step"]
                                          if res["applied"] else None, "clock_steps": res["clock_steps"]})
            self._after_action(res)
            return res

    # ---- records ---------------------------------------------------------
    def _maybe_save(self, force=False):
        if not self.save_records:
            return
        s = self.session
        if not force and not s.over:
            return
        extra = {"ui": {"options": self.options, "match_params": self.match_params,
                        "clock_events": self.clock_events,
                        "stats": self.over_payload()["stats"] if s.over else None}}
        s.save(self.record_dir, extra=extra)
        self.saved = True

    def abandon(self):
        with self.lock:
            if self.session.trace and not self.session.over:
                self.session.meta["abandoned_at"] = time.time()
                self._maybe_save(force=True)
