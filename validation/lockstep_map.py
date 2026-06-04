#!/usr/bin/env python3
"""lockstep_map.py — normalized FUMBBL JSONL -> engine lockstep script JSONL.

Validation layer 7 (v0): translate the observation stream produced by
normalize_replay.py into a script of engine operations that tools/bb_lockstep.c
replays through the real engine (bb_apply + bb_rng SCRIPT mode), checking
legality and diffing state at every FUMBBL turn boundary.

Output ops (one JSON object per line):
  {"op":"init", "replay":.., "home":{...}, "away":{...}, "receiving":0|1,
   "weather":<bb_weather int>, "rerolls":[h,a], "apo":[h,a], "dice":[...]}
  {"op":"place","cmd":N,"team":0|1,"slot":S,"x":..,"y":..}
  {"op":"act","cmd":N,"type":<bb_action_type>,"arg":..,"x":..,"y":..,
   "dice":[...], "hk":[t,s]?, "note":"..."}
  {"op":"expect","cmd":N,"players":[[t,s,x,y,state],...],"ball":[x,y,held],
   "score":[h,a]}
  {"op":"skip","cmd":N,"what":"...","detail":"..."}

Semantics: dice attached to an op are exactly the values the engine consumes
during that op's apply+advance transition (init dice cover the very first
bb_advance). Anything v0 cannot map becomes a skip op — logged, never silent.

COORDINATES (verified against replay 1907296 kickoff formation + FFB
FieldCoordinate.java): FUMBBL and engine agree: x 0..25 (home half x<=12,
home dugout x<0/x>25 codes off-pitch), y 0..14, same orientation. Identity
mapping. Direction names map to engine D8 faces via OUR DIR8 table
(NW=1,N=2,NE=3,W=4,E=5,SW=6,S=7,SE=8) — FFB rolls a different face order, so
faces are re-derived from the reported direction NAME, never the raw roll.
Block die faces are identical in both engines (1=skull..6=pow,3/4=push):
FUMBBL blockRoll values feed straight through.

Usage:
  python3 validation/lockstep_map.py 1907296            # one replay
  python3 validation/lockstep_map.py --all              # whole corpus
Output: validation/lockstep/<replayId>.jsonl + skip histogram on stdout.
"""

import argparse
import collections
import glob
import gzip
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
NORM_DIR = os.path.join(HERE, "normalized")
CACHE_DIR = os.path.join(HERE, "replay_cache")
OUT_DIR = os.path.join(HERE, "lockstep")
SPEC_DIR = os.path.join(ROOT, "engine", "data", "spec")

# --- bb_actions.h mirrors (stable enums per header contract) ------------------
A_SETUP_PLACE, A_SETUP_REMOVE, A_SETUP_DONE, A_KICK_TARGET, A_TOUCHBACK = 1, 2, 3, 4, 5
A_ACTIVATE, A_DECLARE, A_END_TURN = 6, 7, 8
A_STEP, A_STAND_UP, A_JUMP, A_BLOCK_TARGET, A_PASS_TARGET = 9, 10, 11, 12, 13
A_HANDOFF_TARGET, A_FOUL_TARGET, A_TTM_TARGET, A_SECURE_BALL = 14, 15, 16, 17
A_END_ACTIVATION = 19
A_CHOOSE_DIE, A_PUSH_SQUARE, A_FOLLOW_UP = 20, 21, 22
A_USE_REROLL, A_DECLINE_REROLL = 23, 24
A_APOTHECARY, A_CHOOSE_OPTION, A_SPECIAL_TARGET = 27, 28, 29

ACT_MOVE, ACT_BLOCK, ACT_BLITZ, ACT_PASS, ACT_HANDOFF, ACT_FOUL = 0, 1, 2, 3, 4, 5
ACT_TTM, ACT_SECURE, ACT_STAB, ACT_GAZE, ACT_KTM = 6, 7, 8, 9, 10
ACT_CHAINSAW, ACT_BREATHE_FIRE, ACT_VOMIT = 11, 12, 13

RR_TEAM, RR_SKILL, RR_PRO = 0, 1, 2

# Engine D8: roll-1 indexes {-1,-1},{0,-1},{1,-1},{-1,0},{1,0},{-1,1},{0,1},{1,1}
DIR_TO_FACE = {  # FFB direction name (FieldCoordinate deltas) -> our D8 face
    "Northwest": 1, "North": 2, "Northeast": 3, "West": 4,
    "East": 5, "Southwest": 6, "South": 7, "Southeast": 8,
}
DIR_DELTA = {
    "North": (0, -1), "Northeast": (1, -1), "East": (1, 0), "Southeast": (1, 1),
    "South": (0, 1), "Southwest": (-1, 1), "West": (-1, 0), "Northwest": (-1, -1),
}

WEATHER_NAME = {  # FUMBBL weather name -> bb_weather
    "Sweltering Heat": 0, "Very Sunny": 1, "Nice Weather": 2,
    "Pouring Rain": 3, "Blizzard": 4,
}

# FFB PlayerState bases (vendor/ffb PlayerState.java) -> canonical state codes
# 0 standing / 1 prone / 2 stunned / 3 reserves / 4 KO / 5 CAS / 6 sent-off.
# MOVING(2) / BLOCKED(12) are transient selection states that say nothing
# about stance (a prone player stays prone while selected) — no mapping, so
# the mirror keeps the last stable stance.
BASE_STATE = {1: 0, 3: 1, 11: 1, 4: 2, 5: 4, 6: 5, 7: 5, 8: 5, 9: 3, 13: 6}

PLAYER_ACTION_KIND = {
    "move": ACT_MOVE, "block": ACT_BLOCK,
    "blitz": ACT_BLITZ, "blitzMove": ACT_BLITZ, "blitzSelect": ACT_BLITZ,
    "standUpBlitz": ACT_BLITZ,
    "pass": ACT_PASS, "passMove": ACT_PASS, "hailMaryPass": ACT_PASS,
    "handOver": ACT_HANDOFF, "handOverMove": ACT_HANDOFF,
    "foul": ACT_FOUL, "foulMove": ACT_FOUL,
    "secureTheBall": ACT_SECURE, "stab": ACT_STAB,
    "gaze": ACT_GAZE, "gazeMove": ACT_GAZE, "gazeSelect": ACT_GAZE,
    "chainsaw": ACT_CHAINSAW, "breatheFire": ACT_BREATHE_FIRE,
    "projectileVomit": ACT_VOMIT,
    "throwTeamMate": ACT_TTM, "throwTeamMateMove": ACT_TTM,
    "kickTeamMate": ACT_KTM, "kickTeamMateMove": ACT_KTM,
}
UNMAPPED_ACTIONS = {"throwBomb", "hailMaryBomb", "multipleBlock", "swoop",
                    "punt", "puntMove", "lookIntoMyEyes", "balefulHex"}

# Kickoff-event free-action turn modes (engine treats the events as no-ops
# past their dice, D21). Pure repositioning modes can be baked into the setup
# placements when the result is still a legal formation.
KICKOFF_FREE_MODES = {"blitz", "quickSnap", "solidDefence", "kickoffReturn"}
KICKOFF_BAKE_MODES = {"quickSnap", "solidDefence", "kickoffReturn"}
# The events' own D3 rolls ARE rolled by the engine — never drop these.
KICKOFF_EVENT_ROLLS = {"blitzRoll", "solidDefenceRoll", "quickSnapRoll"}

# Negatrait activation gates: engine D6 target (BB_SKILL_GATE registrations).
# FFB applies situational modifiers (e.g. Really Stupid's +2 helper) that the
# engine lacks; gate dice are outcome-adjusted against these flat targets.
GATE_SKILLS = {"Bone Head": 2, "Really Stupid": 4,
               "Unchannelled Fury": 4, "Take Root": 2}
DECLARE_ROLL_SKILLS = {"Animal Savagery", "Bloodlust", "Animosity"}
TEST_RR_SKILL = {  # engine BB_SKILL_REROLL registrations
    "dodgeRoll": "Dodge", "goForItRoll": "Sure Feet", "pickUpRoll": "Sure Hands",
    "passRoll": "Pass", "catchRoll": "Catch",
}


def slug(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def skill_slug(s):
    """Skill-name slug: parameter suffixes like '(4+)' / '(X+)' are stripped
    so FUMBBL 'Loner' matches our 'Loner (X+)' display."""
    return slug(re.sub(r"\([^)]*\)", "", s or ""))


def load_yaml_lite(path):
    """Minimal YAML loader for engine/data/spec files (no PyYAML dependency).

    Extracts only what the mapper needs: for teams files the (display,
    positions[].display) tree; for skills the display list. The spec files are
    machine-generated with stable 2-space indentation.
    """
    teams, skills = [], []
    cur_team, cur_pos, in_positions = None, None, False
    for raw in open(path, encoding="utf-8"):
        line = raw.rstrip("\n")
        if not line.strip() or line.strip().startswith("#"):
            continue
        m = re.match(r"^(\s*)(- )?([A-Za-z_]+):\s*(.*)$", line)
        if not m:
            continue
        indent, dash, key, val = len(m.group(1)), m.group(2), m.group(3), m.group(4)
        val = val.strip().strip('"').strip("'")
        if key == "name" and dash and indent == 2:       # new team / skill
            cur_team = {"name": val, "display": val, "positions": []}
            teams.append(cur_team)
            skills.append(cur_team)  # same shape works for skills.yaml
            in_positions = False
        elif key == "display" and indent == 4 and cur_team and not in_positions:
            cur_team["display"] = val
        elif key == "positions":
            in_positions = True
        elif key == "name" and dash and in_positions and cur_team is not None:
            cur_pos = {"name": val, "display": val}
            cur_team["positions"].append(cur_pos)
        elif key == "display" and in_positions and cur_pos is not None:
            cur_pos["display"] = val
    return teams


def load_engine_spec():
    teams = []
    for f in ("teams_a.yaml", "teams_b.yaml"):
        teams += [t for t in load_yaml_lite(os.path.join(SPEC_DIR, f))
                  if t.get("positions")]
    skills = [t["display"] for t in load_yaml_lite(os.path.join(SPEC_DIR, "skills.yaml"))]
    return teams, skills


def resolve_position(team_positions, pos_name):
    """stage_spectator_art.py approach: slug match, word-strip, containment."""
    ps = slug(pos_name)
    by_slug = {slug(p["display"]): i for i, p in enumerate(team_positions)}
    if ps in by_slug:
        return by_slug[ps]
    words = re.findall(r"[A-Za-z0-9]+", pos_name or "")
    for i in range(1, len(words)):
        cand = slug("".join(words[i:]))
        if cand in by_slug:
            return by_slug[cand]
    contains = [i for s, i in by_slug.items() if ps and (ps in s or s in ps)]
    if len(contains) == 1:
        return contains[0]
    return -1


class Mapper:
    def __init__(self, records, raw_replay=None):
        self.recs = [r for r in records if r.get("type") not in ("coverage",)]
        self.meta = self.recs[0]
        assert self.meta["type"] == "meta"
        self.recs = self.recs[1:]
        self.raw = raw_replay
        self.ops = []
        self.skips = collections.Counter()
        self.consumed = set()      # record indices consumed by lookahead
        self.engine_teams, self.engine_skills = load_engine_spec()
        self.skill_by_slug = {skill_slug(s): s for s in self.engine_skills}
        self._build_roster()
        # --- mirror state ---
        self.pos = {}              # playerId -> (x,y) or None
        self.base = {}             # playerId -> last stable canonical state
        self.ball = None           # (x,y) or None
        self.carrier = None        # playerId or None
        self.score = [0, 0]
        self.kicking = None        # team int
        self.half = 1
        self.rerolls = [0, 0]
        self.apo = [0, 0]
        self.skill_rr_used = collections.defaultdict(set)  # playerId -> kinds
        self.active_team = None
        self.activation = None     # dict: player, kind, gate_failed, ...
        self.acts_this_turn = 0
        self.used_this_turn = set()  # pids the ENGINE saw activate this turn
        self.turnover = False
        self.setup_segments = 0
        self.pending_block = None  # block resolution state
        self.stood_block = None    # engine auto-applied Stand Firm: {att,def,def_sq}
        self.pending_step = None   # buffered STEP awaiting its (later) rolls
        self.pre_dice = []         # dice before next STEP/JUMP/BLOCK_TARGET
        self.pre_route = False     # route dice/rerolls to pre_dice (block rush)
        self.turnend_dice = []     # dice consumed during END_TURN transition
        self.pickmeup = []         # (gslot, roll) Pick Me Up dice this boundary
        self.last_ball_cmd = None  # cmd of the last ball record seen
        self.ball_diverged = False # engine ball state unrepresentable (skill gap)
        self.last_injury_key = None
        self.in_kickoff_resolution = False
        # Engine stun rollover mirror: pid -> "fresh" (stunned this turn) or
        # "aged" (started its own team turn stunned = engine STUNNED_USED).
        # The engine flips aged players to prone at the END of their own
        # team's turn; FFB emits the prone record at the START of that turn —
        # the mirror holds state 2 until the engine's boundary.
        self.stun_stage = {}
        # Known-divergence pids the engine cannot represent: positions and/or
        # states excluded from expect ops (e.g. Swarming extra players,
        # kickoff free-move repositioning the engine treats as a no-op).
        self.ignore_pos = set()
        self.ignore_state = set()
        self.ignore_all = set()    # player absent engine-side (Swarming)
        self.move_from = None      # origin square of the current move record
        self.last_both_down = None # {att,def,cmd} of the last Both Down
        self.suppress_injury = set()  # pids whose next injury dice are FFB-only
        self.baked_moves = {}      # pid -> final square baked into setup

    # --- roster ---------------------------------------------------------------
    def _build_roster(self):
        self.slot_of = {}          # playerId -> (team, slot)
        self.skillnames = {}       # playerId -> set of canonical skill names
        self.team_specs = []
        pos_names = {}
        if self.raw:
            for side in ("teamHome", "teamAway"):
                ros = (self.raw.get("game", {}).get(side, {}) or {}).get("roster", {}) or {}
                for p in ros.get("positionArray", []) or []:
                    pos_names[str(p.get("positionId"))] = p.get("positionName")
        self.ma_of = {}            # playerId -> MA (rush bookkeeping mirror)
        # Rosters can exceed the engine's 16 slots (induced stars/mercs).
        # Prioritize the players who actually take the pitch (any formation
        # appearance) so the placements all have slots.
        participants = set()
        for rec in self.recs:
            if rec.get("type") == "formation":
                participants.update(str(p) for p in rec.get("players", {}))
        for team, key in ((0, "teamHome"), (1, "teamAway")):
            tm = self.meta[key]
            race = tm.get("race") or ""
            eteam = -1
            rs = slug(race)
            for i, t in enumerate(self.engine_teams):
                if slug(t["display"]) == rs:
                    eteam = i
                    break
            positions = self.engine_teams[eteam]["positions"] if eteam >= 0 else []
            players = []
            roster = tm.get("players", [])
            if len(roster) > 16:
                roster = sorted(roster, key=lambda p: (
                    str(p["playerId"]) not in participants))
            for i, p in enumerate(roster):
                if i >= 16:
                    self.skip(0, "roster_overflow", f"{key} player {p.get('name')}")
                    continue
                self.slot_of[str(p["playerId"])] = (team, i)
                self.ma_of[str(p["playerId"])] = p.get("ma") or 0
                canon = []
                names = set()
                for sk in p.get("skills", []) or []:
                    c = self.skill_by_slug.get(skill_slug(sk))
                    if c:
                        canon.append(c)
                        names.add(c)
                    else:
                        self.skip(0, "skill_unmapped", sk)
                self.skillnames[str(p["playerId"])] = names
                pname = pos_names.get(str(p.get("positionId")), "")
                pidx = resolve_position(positions, pname) if positions else -1
                if pidx < 0 and pname:
                    self.skip(0, "position_unmapped", f"{race}/{pname}")
                players.append({
                    "slot": i, "name": p.get("name") or "",
                    "position": pname or "", "pos": pidx,
                    "ma": p.get("ma") or 0, "st": p.get("st") or 0,
                    "ag": p.get("ag") or 0, "pa": p.get("pa") or 0,
                    "av": p.get("av") or 0, "skills": canon,
                })
            self.team_specs.append({"race": race, "team": eteam, "players": players})

    def pid_team(self, pid):
        ts = self.slot_of.get(str(pid))
        return ts[0] if ts else None

    def has_skill(self, pid, name):
        return name in self.skillnames.get(str(pid), ())

    # --- op emission ----------------------------------------------------------
    def skip(self, cmd, what, detail=""):
        self.skips[what] += 1
        self.ops.append({"op": "skip", "cmd": cmd, "what": what,
                         "detail": str(detail)[:120]})

    def act(self, cmd, typ, arg=0, x=0, y=0, dice=None, _noflush=False, **extra):
        if not _noflush:
            self.flush_step(cmd)
        op = {"op": "act", "cmd": cmd, "type": typ, "arg": arg, "x": x, "y": y,
              "dice": list(dice or [])}
        op.update(extra)
        self.ops.append(op)
        return op

    def flush_step(self, cmd):
        """Emit the buffered STEP (FFB reports the coordinate change BEFORE the
        rolls that resolve it, so steps wait for their dice)."""
        ps, self.pending_step = self.pending_step, None
        if not ps:
            return
        items = ps["items"]
        dice, segs, cur = [], [], None
        for item in items:
            if item[0] == "die":
                (cur[2] if cur else dice).append(item[1])
            else:
                cur = (item[1], item[2], [])
                if item[3] is not None:
                    cur[2].append(item[3])
                segs.append(cur)
        self.act(ps["cmd"], A_STEP, 0, ps["x"], ps["y"], dice=dice,
                 _noflush=True)
        self.flush_reroll_acts(ps["cmd"], segs)

    def route_die(self, cmd, value, what="dice"):
        if self.pre_route:
            self.pre_dice.append(("die", int(value)))
        elif self.pending_step is not None:
            self.pending_step["items"].append(("die", int(value)))
        else:
            self.attach(cmd, [int(value)], what)

    def route_reroll(self, cmd, source, skill=0, loner_die=None):
        marker = ("reroll", source, skill, loner_die)
        if self.pre_route:
            self.pre_dice.append(marker)
            return
        if self.pending_step is not None:
            self.pending_step["items"].append(marker)
            return
        dice = [loner_die] if loner_die is not None else []
        if source == "decline":
            self.act(cmd, A_DECLINE_REROLL, dice=dice)
        elif source == "team":
            self.act(cmd, A_USE_REROLL, RR_TEAM, dice=dice)
        elif source == "pro":
            self.act(cmd, A_USE_REROLL, RR_PRO, dice=dice)
        else:
            self.act(cmd, A_USE_REROLL, RR_SKILL, x=skill or 0, dice=dice)

    def attach(self, cmd, dice, what="dice"):
        """Append dice to the pending step or most recent dice-consuming op."""
        if self.pending_step is not None:
            self.pending_step["items"].extend(("die", int(d)) for d in dice)
            return
        for op in reversed(self.ops):
            if op["op"] in ("act", "init"):
                op["dice"].extend(int(d) for d in dice)
                return
        self.skip(cmd, "orphan_dice", f"{what}:{dice}")

    # --- record helpers ---------------------------------------------------------
    def lookahead(self, i, pred, limit=14):
        for j in range(i + 1, min(i + 1 + limit, len(self.recs))):
            if j in self.consumed:
                continue
            r = self.recs[j]
            if pred(r):
                return j
        return -1

    def track(self, i, r):
        t = r["type"]
        if t == "move":
            pid = str(r["player"])
            x, y = r["to"]
            self.move_from = self.pos.get(pid)
            self.pos[pid] = (x, y) if 0 <= x <= 25 and 0 <= y <= 14 else None
            if self.carrier == pid:
                if self.has_skill(pid, "Fumblerooski") and \
                        (r.get("cmd") or 0) != self.last_ball_cmd:
                    # No ball record accompanied the carrier's move: the
                    # ball was deliberately left behind (Fumblerooski). The
                    # engine has no such window — ball state diverges until
                    # the next drive.
                    self.carrier = None
                    self.ball_diverged = True
                    self.skip(r.get("cmd") or 0, "fumblerooski_divergence", pid)
                else:
                    # The ball travels with its carrier (FFB also emits a
                    # ball record, but it precedes the move — see below).
                    self.ball = self.pos[pid]
        elif t == "state":
            st = BASE_STATE.get(r["base"], -1)
            pid = str(r["player"])
            if st >= 0:
                if st == 1 and self.stun_stage.get(pid):
                    # FFB rolls stunned players over at the START of their
                    # team's turn; the engine at the END. Hold the mirror at
                    # stunned until the engine's flip boundary (rep_turnEnd).
                    return
                if st == 2:
                    self.stun_stage.setdefault(pid, "fresh")
                else:
                    self.stun_stage.pop(pid, None)
                self.base[pid] = st
                if st != 0 and self.carrier == pid:
                    self.carrier = None
                if st >= 3:
                    self.pos[pid] = None
        elif t == "ball":
            self.last_ball_cmd = r.get("cmd") or 0
            self.ball = tuple(r["at"]) if 0 <= r["at"][0] <= 25 else None
            if self.carrier and self.pos.get(self.carrier) != self.ball:
                # FFB emits the ball-follows-carrier record BEFORE the
                # carrier's own move record at the same cmd: only clear the
                # carrier if no such move follows immediately.
                pid = self.carrier
                follows = False
                for k in range(i + 1, min(i + 5, len(self.recs))):
                    rk = self.recs[k]
                    if rk.get("type") == "move" and str(rk.get("player")) == pid:
                        follows = tuple(rk["to"]) == self.ball
                        break
                    if rk.get("type") not in ("ball", "state"):
                        break
                if not follows:
                    self.carrier = None

    # --- expects -----------------------------------------------------------------
    def emit_expect(self, cmd, skip_ball=False):
        players = []
        for pid, (team, sl) in sorted(self.slot_of.items(), key=lambda kv: kv[1]):
            p = self.pos.get(pid)
            st = self.base.get(pid, -1)
            x, y = (p if p else (255, 255))
            if pid in self.ignore_all or pid in self.ignore_pos:
                x, y = 255, 255
            if pid in self.ignore_all or pid in self.ignore_state:
                st = -1
            players.append([team, sl, x, y, st])
        if skip_ball or self.ball is None or self.ball_diverged or \
                self.carrier in self.ignore_all:
            ball = [255, 255, -1]
        else:
            ball = [self.ball[0], self.ball[1], 1 if self.carrier else 0]
        self.ops.append({"op": "expect", "cmd": cmd, "players": players,
                         "ball": ball, "score": list(self.score)})

    # --- activation plumbing -------------------------------------------------------
    def close_activation(self, cmd):
        a = self.activation
        self.activation = None
        self.flush_step(cmd)
        # A block at the very end of an activation can leave the engine
        # waiting on the follow-up (or push) decision: resolve it first.
        self.resolve_pending_followup(cmd)
        if not a:
            return
        if a.get("closed"):
            return
        self.act(cmd, A_END_ACTIVATION, note=f"end {a['pid']}")

    def fail_likely_turnover(self, pid):
        if self.pid_team(pid) == self.active_team:
            self.turnover = True
            if self.activation and self.activation["pid"] == str(pid):
                self.activation["closed"] = True

    def age_stunned(self, team):
        """Engine turn_start(team): stunned players of that team become
        STUNNED_USED — they roll over to prone at the END of this turn."""
        if team is None:
            return
        for pid, (t, _) in self.slot_of.items():
            if t == team and self.stun_stage.get(pid) == "fresh":
                self.stun_stage[pid] = "aged"

    def engine_turn_open(self):
        """True iff the engine still has an activatable player this turn.

        The engine auto-ends a team turn when no player can activate, so an
        explicit END_TURN then would land on the NEXT team's fresh turn."""
        team = self.active_team
        if team is None:
            return True
        for pid, (t, _) in self.slot_of.items():
            if t != team or pid in self.used_this_turn:
                continue
            if self.pos.get(pid) and self.base.get(pid, 0) in (0, 1):
                return True
        return False

    # --- main ---------------------------------------------------------------------
    def run(self):
        meta = self.meta
        self.rerolls = [meta["teamHome"].get("reRolls") or 0,
                        meta["teamAway"].get("reRolls") or 0]
        self.apo = [meta["teamHome"].get("apothecaries") or 0,
                    meta["teamAway"].get("apothecaries") or 0]
        # Engine PREGAME grants +1 re-roll per Leader on the roster.
        for t in (0, 1):
            if any("Leader" in self.skillnames.get(pid, ()) for pid, (tt, _)
                   in self.slot_of.items() if tt == t):
                self.rerolls[t] += 1
        rc = meta.get("receiveChoice") or {}
        recv_team_id = str(rc.get("teamId"))
        home_id = str(meta["teamHome"].get("teamId"))
        chooser = 0 if recv_team_id == home_id else 1
        receive = bool(rc.get("receive"))
        receiving = chooser if receive else 1 - chooser
        if meta.get("homeFirstOffense") is not None:
            receiving = 0 if meta["homeFirstOffense"] else 1
        self.kicking = 1 - receiving

        init = {"op": "init", "replay": meta.get("replayId"),
                "home": self.team_specs[0], "away": self.team_specs[1],
                "receiving": receiving, "weather": 2,
                "rerolls": [meta["teamHome"].get("reRolls") or 0,
                            meta["teamAway"].get("reRolls") or 0],
                "apo": list(self.apo), "dice": []}
        self.ops.append(init)
        self.init_op = init

        i = -1
        while i + 1 < len(self.recs):
            i += 1
            if i in self.consumed:
                continue
            r = self.recs[i]
            if r.get("type") == "ball" and r.get("mode") == "touchback" and \
                    self.in_kickoff_resolution:
                self.handle_touchback(r)
            self.track(i, r)
            t = r["type"]
            cmd = r.get("cmd") or 0
            if t == "formation":
                self.handle_formation(i, r)
            elif t == "move":
                self.handle_move(i, r)
            elif t in ("dice", "action", "event"):
                self.handle_report(i, r)
            # state/ball already tracked
        return self.ops

    def handle_touchback(self, r):
        """Kick went out of play / into the kicking half: the receiving coach
        gives the ball to any standing player (engine KICKOFF phase 2,
        A_TOUCHBACK arg = global slot; arg 0xFF + square if nobody stands)."""
        cmd = r.get("cmd") or 0
        x, y = r["at"]
        pid = next((p for p, q in self.pos.items() if q == (x, y)
                    and self.slot_of.get(p)), None)
        receiving = 1 - self.kicking if self.kicking is not None else None
        if pid is not None and self.slot_of[pid][0] == receiving and \
                self.base.get(pid, 0) == 0:
            team, sl = self.slot_of[pid]
            self.act(cmd, A_TOUCHBACK, team * 16 + sl)
            self.carrier = pid
        else:
            self.act(cmd, A_TOUCHBACK, 0xFF, x, y)
            self.carrier = None
        self.ball = (x, y)

    # --- formation / setup ----------------------------------------------------------
    def kickoff_repositioning(self, i, r):
        """Final positions of kickoff-event pure-repositioning moves (Solid
        Defence / Quick Snap / Kick-off Return) following this formation.

        The engine treats these events as no-ops (D21): baking the final
        positions into the setup placements reproduces the post-event board
        exactly — the landing catch then rolls against the same tackle zones
        FFB used. Only applied when the result is still a setup-legal
        formation (Solid Defence re-setups always are by rule; Quick Snap
        single steps occasionally are not)."""
        finals = {}
        for j in range(i + 1, min(i + 600, len(self.recs))):
            rj = self.recs[j]
            if rj.get("type") == "formation":
                break
            if rj.get("report") == "turnEnd" or rj.get("mode") == "regular":
                break
            if rj.get("type") == "move" and rj.get("mode") in KICKOFF_BAKE_MODES:
                pid = str(rj.get("player"))
                x, y = rj["to"]
                if 0 <= x <= 25 and 0 <= y <= 14 and pid in r["players"]:
                    finals[pid] = (x, y)
        return finals

    @staticmethod
    def setup_legal_formation(team, coords):
        """Mirror of the engine's setup_constraints_ok for one team's
        placement list [(x, y), ...] (count is unchanged by repositioning)."""
        los_x = 12 if team == 0 else 13
        xmin, xmax = (0, 12) if team == 0 else (13, 25)
        los = wz_top = wz_bot = 0
        for x, y in coords:
            if not (xmin <= x <= xmax and 0 <= y <= 14):
                return False
            if x == los_x and 4 <= y <= 10:
                los += 1
            if y <= 3:
                wz_top += 1
            if y >= 11:
                wz_bot += 1
        need_los = min(3, len(coords))
        return los >= need_los and wz_top <= 2 and wz_bot <= 2

    def handle_formation(self, i, r):
        cmd = r.get("cmd") or 0
        self.stun_stage.clear()    # drive boundary: everyone re-set-up
        self.ignore_pos.clear()    # repositioning divergences reset with it
        self.ball_diverged = False
        self.pickmeup = []
        finals = self.kickoff_repositioning(i, r)
        if finals:
            coords = dict(r["players"])
            coords.update({p: list(v) for p, v in finals.items()})
            ok = len({tuple(v) for v in coords.values()}) == len(coords)
            for team in (0, 1):
                tc = [tuple(v) for p, v in coords.items()
                      if self.slot_of.get(str(p), (None,))[0] == team]
                if tc and not self.setup_legal_formation(team, tc):
                    ok = False
            if ok:
                self.baked_moves = dict(finals)
                self.skips["kickoff_reposition_baked"] += len(finals)
            else:
                self.baked_moves = {}
                for pid in finals:
                    self.ignore_pos.add(pid)
                self.skips["kickoff_reposition_unbakeable"] += len(finals)
                finals = {}
        else:
            self.baked_moves = {}
        placements = {0: [], 1: []}
        for pid, (x, y) in r["players"].items():
            ts = self.slot_of.get(str(pid))
            if not ts:
                self.skip(cmd, "formation_unknown_player", pid)
                continue
            fx, fy = finals.get(str(pid), (x, y))
            placements[ts[0]].append((ts[1], fx, fy))
            self.pos[str(pid)] = (fx, fy)
            self.base[str(pid)] = 0
        order = [self.kicking, 1 - self.kicking]
        for team in order:
            for sl, x, y in sorted(placements[team]):
                self.ops.append({"op": "place", "cmd": cmd, "team": team,
                                 "slot": sl, "x": x, "y": y})
            self.act(cmd, A_SETUP_DONE, note=f"setup done team {team}")
        self.setup_segments += 1
        self.turnover = False
        self.acts_this_turn = 0
        self.used_this_turn = set()
        self.in_kickoff_resolution = True

    # --- moves ------------------------------------------------------------------------
    def handle_move(self, i, r):
        cmd = r.get("cmd") or 0
        pid = str(r["player"])
        mode = r.get("mode")
        x, y = r["to"]
        on_pitch = 0 <= x <= 25 and 0 <= y <= 14
        if mode in ("startGame", "setup"):
            return
        if mode == "swarming":
            # Swarming: extra players enter the pitch during setup — the
            # engine has no Swarming (setup wants exactly 11). Known engine
            # divergence: the player exists only FFB-side from here on.
            self.ignore_all.add(pid)
            self.skip(cmd, "swarming_player_unrepresented", f"{pid} -> {x},{y}")
            return
        if pid in self.ignore_all:
            return  # ghost player relocating: mirror tracks, engine ignores
        if self.in_kickoff_resolution and mode in KICKOFF_FREE_MODES:
            # Kickoff-event free move. Baked moves are already part of the
            # setup placements; everything else is the documented D21
            # repositioning divergence (engine keeps the kicked formation).
            if pid in self.baked_moves:
                self.skips["kickoff_reposition_baked_move"] += 1
            else:
                self.ignore_pos.add(pid)
                self.skip(cmd, f"kickoff_free_move_{mode}", f"{pid} -> {x},{y}")
            return
        # Block resolution relocations (push square / follow-up) take priority.
        if self.pending_block:
            pb = self.pending_block
            if pb["phase"] == "push" and pid == pb["def"]:
                if pb.get("chain"):
                    if not self.emit_chain_push(cmd, x, y, on_pitch):
                        return
                elif on_pitch:
                    self.act(cmd, A_PUSH_SQUARE, 0, x, y)
                else:
                    self.emit_crowd_push(cmd)
                if pb.get("forced_followup"):
                    pb["phase"] = "att_forced"  # engine auto-follows up
                elif pb["no_followup"]:
                    self.pending_block = None
                else:
                    pb["phase"] = "followup"
                return
            if pb["phase"] == "att_forced" and pid == pb["att"]:
                # Frenzy forced follow-up: the engine placed the attacker
                # during the push transition — consume the move, no op.
                self.pending_block = None
                return
            if pb["phase"] == "push" and pid != pb["def"] and \
                    self.pid_team(pid) is not None:
                if pid == pb["att"]:
                    # attacker relocating before the defender's push square
                    # is known: not a chain shape we can reconstruct
                    self.skip(cmd, "chain_push_unmatched", f"att {pid} moved")
                    self.pending_block = None
                    return
                # Someone else relocating mid-push: a chain push. FFB emits
                # the chained players innermost-first, the defender last —
                # buffer the links; the defender's move triggers emission of
                # the whole PUSH_SQUARE decision sequence (emit_chain_push).
                pb.setdefault("chain", []).append(
                    {"pid": pid, "from": self.move_from,
                     "to": (x, y) if on_pitch else None})
                return
            if pb["phase"] == "followup" and pid == pb["att"]:
                self.act(cmd, A_FOLLOW_UP, 1)
                self.pending_block = None
                return
        # FFB declined an auto-applied Stand Firm: the engine kept attacker
        # and defender in place, so their FFB relocations cannot be mirrored.
        sb = self.stood_block
        if sb and (pid == sb["def"] or
                   (pid == sb["att"] and sb["def_sq"] == (x, y))):
            self.skip(cmd, "stand_firm_decline_divergence", f"{pid} -> {x},{y}")
            return
        if mode not in ("regular", "blitz"):
            self.skip(cmd, f"move_in_mode_{mode}", f"{pid} -> {x},{y}")
            return
        a = self.activation
        if not a or a["pid"] != pid or a.get("closed"):
            if self.pid_team(pid) is not None:
                self.skip(cmd, "move_without_activation", f"{pid} -> {x},{y}")
            return
        if not on_pitch:
            return
        # Flush any pending follow-up decision from an earlier block first.
        self.resolve_pending_followup(cmd)
        self.flush_step(cmd)
        items = []
        for item in self.pre_dice:   # tentacle holds etc. roll pre-step
            items.append(item)
        self.pre_dice = []
        self.pre_route = False
        # Mirror the engine's moved counter: a step beyond MA is a rush.
        is_rush = a.get("moved", 0) >= self.ma_of.get(pid, 0)
        a["moved"] = a.get("moved", 0) + 1
        self.pending_step = {"cmd": cmd, "x": x, "y": y, "items": items,
                             "is_rush": is_rush}

    def split_pre_dice(self):
        """Pre-step dice buffer -> (dice for the step op, reroll act segments)."""
        dice, segs, cur = [], [], None
        for item in self.pre_dice:
            if item[0] == "die":
                (cur[2] if cur else dice).append(item[1])
            else:  # ("reroll", source, skill, loner_die or None)
                cur = (item[1], item[2], [])
                if item[3] is not None:
                    cur[2].append(item[3])
                segs.append(cur)
        self.pre_dice = []
        return dice, segs

    def flush_reroll_acts(self, cmd, segs):
        for source, skill, dice in segs:
            if source == "decline":
                self.act(cmd, A_DECLINE_REROLL, dice=dice)
            elif source == "team":
                self.act(cmd, A_USE_REROLL, RR_TEAM, dice=dice)
            elif source == "pro":
                self.act(cmd, A_USE_REROLL, RR_PRO, dice=dice)
            else:
                self.act(cmd, A_USE_REROLL, RR_SKILL, x=skill or 0, dice=dice)

    def resolve_pending_followup(self, cmd):
        if self.pending_block and self.pending_block["phase"] == "followup":
            self.act(cmd, A_FOLLOW_UP, 0)
            self.pending_block = None
        elif self.pending_block and self.pending_block["phase"] == "att_forced":
            self.pending_block = None  # forced follow-up never materialized
        elif self.pending_block and self.pending_block["phase"] == "push":
            # push never materialized (e.g. defender removed some other way)
            self.skip(cmd, "push_unresolved", self.pending_block["def"])
            self.pending_block = None

    # --- reports -------------------------------------------------------------------------
    REPORT_PID_KEYS = ("playerId", "actingPlayerId", "defenderId", "attackerId",
                       "catcherId")

    def handle_report(self, i, r):
        rep = r.get("report")
        cmd = r.get("cmd") or 0
        if self.ignore_all:
            # Records about players the engine cannot represent (Swarming
            # extras): consume without attaching dice or emitting acts.
            pids = [str(r.get(k)) for k in self.REPORT_PID_KEYS if r.get(k)]
            if pids and any(p in self.ignore_all for p in pids):
                if rep == "injury" and str(r.get("attackerId")) in self.ignore_all \
                        and str(r.get("defenderId")) not in self.ignore_all:
                    # A ghost player injured a real one: the victim's state
                    # diverges from here on; classify and stop checking it.
                    self.ignore_state.add(str(r.get("defenderId")))
                self.skip(cmd, "unrepresented_player_report",
                          f"{rep}/{pids[0]}")
                return
        if self.in_kickoff_resolution and r.get("mode") in KICKOFF_FREE_MODES \
                and rep not in KICKOFF_EVENT_ROLLS:
            # Rolls/blocks inside a kickoff free action (Blitz!/Charge runs
            # whole activations): the engine never rolls these (D21 no-op).
            if rep == "injury" and r.get("defenderId"):
                self.ignore_state.add(str(r.get("defenderId")))
            self.skip(cmd, "kickoff_free_report_dropped", rep)
            return
        h = getattr(self, "rep_" + (rep or "none"), None)
        if h:
            h(i, r, cmd)
        elif rep in ("startHalf",):
            self.half = r.get("half") or self.half
        elif r.get("type") == "dice":
            self.skip(cmd, "unmapped_dice_report", rep)
        else:
            self.skip(cmd, "unmapped_report", rep)

    # pregame ------------------------------------------------------------------------------
    def rep_fanFactor(self, i, r, cmd):
        self.skips["fan_factor_roll_dropped"] += 1  # engine rolls no fans

    def rep_dedicatedFans(self, i, r, cmd):
        self.skips["fan_factor_roll_dropped"] += 1

    def rep_weather(self, i, r, cmd):
        roll = r.get("weatherRoll") or []
        if not self.ops or self.ops[-1]["op"] == "init":
            self.init_op["dice"].extend(roll)
            self.init_op["weather"] = WEATHER_NAME.get(r.get("weather"), 2)
        else:
            self.attach(cmd, roll, "weather")  # Changing Weather re-roll

    def rep_coinThrow(self, i, r, cmd):
        pass  # decision encoded via receiveChoice

    def rep_receiveChoice(self, i, r, cmd):
        chooser = 0 if str(r.get("teamId")) == str(self.meta["teamHome"]["teamId"]) else 1
        receive = 1 if r.get("receiveChoice") else 0
        # Engine: d2 toss decides the chooser (1=home), then CHOOSE_OPTION.
        self.init_op["dice"].append(chooser + 1)
        self.act(cmd, A_CHOOSE_OPTION, receive, note="pregame kick/receive")

    def rep_prayerRoll(self, i, r, cmd):
        self.skip(cmd, "prayer_unmapped", r.get("teamName"))

    # kickoff ------------------------------------------------------------------------------
    def rep_kickoffScatter(self, i, r, cmd):
        end = r.get("ballCoordinateEnd") or [13, 7]
        dname = r.get("scatterDirection")
        dist = int(r.get("rollScatterDistance") or 1)
        delta = DIR_DELTA.get(dname, (0, 0))
        eff = dist
        # KICK skill on a kicking-team pitch player halves the distance.
        for pid, (tt, _) in self.slot_of.items():
            if tt == self.kicking and self.pos.get(pid) and self.has_skill(pid, "Kick"):
                eff = dist // 2
                break
        tx, ty = end[0] - delta[0] * eff, end[1] - delta[1] * eff
        tx = min(max(tx, 0), 25)
        ty = min(max(ty, 0), 14)
        face = DIR_TO_FACE.get(dname, 1)
        self.act(cmd, A_KICK_TARGET, 0, tx, ty, dice=[face, dist])
        self.in_kickoff_resolution = True

    def rep_kickoffResult(self, i, r, cmd):
        roll = r.get("kickoffRoll") or []
        self.attach(cmd, roll, "kickoff")
        result = r.get("kickoffResult") or ""
        if result == "High Kick":
            j = self.lookahead(i, lambda x: x.get("type") == "move" and
                               x.get("mode") in ("highKick", "kickoff") and
                               self.pid_team(x.get("player")) == 1 - self.kicking,
                               limit=20)
            if j >= 0:
                self.consumed.add(j)
                pid = str(self.recs[j]["player"])
                x, y = self.recs[j]["to"]
                self.pos[pid] = (x, y)
                team, sl = self.slot_of[pid]
                self.act(cmd, A_CHOOSE_OPTION, 0, dice=[], hk=[team, sl],
                         note="high kick placement")
            else:
                self.act(cmd, A_CHOOSE_OPTION, 0xFE, note="high kick declined")
        elif result in ("Solid Defence", "Quick Snap", "Blitz", "Charge!", "Charge"):
            pass  # d3 attaches via the *Roll report that follows
        elif result == "Dodgy Snack":
            pass  # fully mapped via rep_kickoffDodgySnack
        elif result in ("Pitch Invasion", "Officious Ref"):
            self.skip(cmd, "kickoff_event_partial", result)

    def rep_quickSnapRoll(self, i, r, cmd):
        v = int(r.get("roll") or 1)
        self.attach(cmd, [v if 1 <= v <= 3 else 1], "quick snap d3")

    rep_solidDefenceRoll = rep_quickSnapRoll
    rep_blitzRoll = rep_quickSnapRoll

    def rep_cheeringFans(self, i, r, cmd):
        rh, ra = r.get("rollHome"), r.get("rollAway")
        if rh and ra:
            self.attach(cmd, [rh, ra], "cheering fans")

    rep_extraReRoll = rep_cheeringFans

    def rep_brilliantCoachingReRoll(self, i, r, cmd):
        pass  # dice arrive via extraReRoll/cheeringFans

    def rep_kickoffPitchInvasion(self, i, r, cmd):
        """Pitch Invasion: D6 home + D6 away (FFB adds Dedicated Fans the
        engine lacks — outcome-adjusted), then per losing team a D3 count +
        one pick roll per victim over its slot-sorted standing players
        (mirrors stun_random_players exactly, like Dodgy Snack)."""
        rh, ra = int(r.get("rollHome") or 0), int(r.get("rollAway") or 0)
        if not rh or not ra:
            self.skip(cmd, "pitch_invasion_partial", "missing 2d6")
            return
        victims = [str(p) for p in (r.get("playerIds") or [])]
        vict_by_team = {0: [p for p in victims if self.pid_team(p) == 0],
                        1: [p for p in victims if self.pid_team(p) == 1]}
        losers = {t for t in (0, 1) if vict_by_team[t]}
        # Engine loser rule from the raw dice: home iff rh<=ra, away iff
        # ra<=rh. Adjust outcome-preservingly when fan modifiers flipped it.
        want = losers or ({0, 1} if rh == ra else ({0} if rh < ra else {1}))
        eng = {t for t, ok in ((0, rh <= ra), (1, ra <= rh)) if ok}
        if victims and want != eng:
            rh, ra = {frozenset({0}): (1, 2), frozenset({1}): (2, 1),
                      frozenset({0, 1}): (1, 1)}[frozenset(want)]
            self.skips["pitch_invasion_dice_adjusted"] += 1
        dice = [rh, ra]
        stunned = set()
        for team in (0, 1):
            if team not in want or not victims:
                continue
            vs = vict_by_team[team]
            if not vs or len(vs) > 3:
                self.skip(cmd, "pitch_invasion_selection", r.get("playerIds"))
                return
            dice.append(len(vs))  # the engine's D3 count
            vset = set(vs)
            for vic in vs:
                # Engine candidates: standing on-pitch players in slot order.
                # FFB's stun state records can precede this report, so the
                # event's own victims count as standing.
                cands = sorted(sl for pid2, (t2, sl) in self.slot_of.items()
                               if t2 == team and self.pos.get(pid2)
                               and (pid2 in vset or
                                    self.base.get(pid2, 0) == 0)
                               and pid2 not in stunned)
                if self.slot_of[vic][1] not in cands:
                    self.skip(cmd, "pitch_invasion_selection", vic)
                    return
                dice.append(cands.index(self.slot_of[vic][1]) + 1)
                stunned.add(vic)
        self.attach(cmd, dice, "pitch invasion")

    def rep_kickoffDodgySnack(self, i, r, cmd):
        """Dodgy Snack (kickoff 11): engine rolls D6 home, D6 away, then for
        each losing team (both on a tie, home first) a victim pick over its
        on-pitch players sorted by slot, then the victim's D6 (2+ = -1 MA/AV
        for the drive, 1 = Reserves). FFB reports the 2d6 + the victim ids +
        a dodgySnackRoll per victim; the pick die is reconstructed from the
        victim's index in the slot-ordered on-pitch list."""
        rh, ra = r.get("rollHome"), r.get("rollAway")
        if not rh or not ra:
            self.skip(cmd, "dodgy_snack_partial", "missing 2d6")
            return
        dice = [int(rh), int(ra)]
        victims = [str(p) for p in (r.get("playerIds") or [])]
        losers = ([0] if rh <= ra else []) + ([1] if ra <= rh else [])
        for team in losers:
            vic = next((p for p in victims if self.pid_team(p) == team), None)
            cands = sorted(sl for pid2, (t2, sl) in self.slot_of.items()
                           if t2 == team and self.pos.get(pid2))
            if vic is None or self.slot_of[vic][1] not in cands:
                self.skip(cmd, "dodgy_snack_victim_unknown", f"team {team}")
                return
            dice.append(cands.index(self.slot_of[vic][1]) + 1)
            j = self.lookahead(i, lambda x, v=vic:
                               x.get("report") == "dodgySnackRoll" and
                               str(x.get("playerId")) == v, limit=6)
            if j < 0:
                self.skip(cmd, "dodgy_snack_roll_missing", vic)
                return
            self.consumed.add(j)
            roll = int(self.recs[j].get("roll") or 1)
            dice.append(roll)
            if roll >= 2 and self.ma_of.get(vic, 0) > 1:
                self.ma_of[vic] -= 1  # mirror the engine's -1 MA debuff
            # roll == 1: victim to Reserves — FFB state records mirror it.
        self.attach(cmd, dice, "dodgy snack")

    def rep_kickoffOfficiousRef(self, i, r, cmd):
        self.skip(cmd, "officious_ref_unmapped", "")

    # turn flow -----------------------------------------------------------------------------
    def rep_turnEnd(self, i, r, cmd):
        td = r.get("playerIdTouchdown")
        if td:
            team = self.pid_team(td)
            if team is not None:
                self.score[team] += 1
                self.kicking = team
            self.turnover = True  # engine auto-unwinds on TD
        mode = r.get("mode")
        if mode in ("startGame", "setup", "kickoff"):
            self.in_kickoff_resolution = False
            return
        # KO recovery (drive end): engine rolls per KO player in slot order.
        ko = []
        for e in r.get("knockoutRecoveryArray") or []:
            if str(e.get("playerId")) in self.ignore_all:
                continue  # engine never saw this player KO'd
            ts = self.slot_of.get(str(e.get("playerId")))
            if ts and e.get("roll"):
                ko.append((ts[0] * 16 + ts[1], e["roll"]))
                if e.get("recovering"):
                    self.base[str(e["playerId"])] = 3
        ko_dice = [v for _, v in sorted(ko)]
        self.flush_step(cmd)
        if self.activation and not self.activation.get("closed"):
            self.close_activation(cmd)
        else:
            self.resolve_pending_followup(cmd)
        if self.in_kickoff_resolution:
            # boundary after the kick settles: receiver's turn 1 begins
            self.in_kickoff_resolution = False
            if ko_dice:
                self.attach(cmd, ko_dice, "ko recovery")
            # Engine turn_start(receiving): players who enter their own turn
            # stunned become STUNNED_USED (flip at that turn's end).
            self.age_stunned(1 - self.kicking if self.kicking is not None else None)
            self.emit_expect(cmd, skip_ball=bool(td))
            self.acts_this_turn = 0
            self.used_this_turn = set()
            self.turnover = False
            self.activation = None
            return
        boundary_dice = [v for _, v in sorted(self.pickmeup)] + \
            list(self.turnend_dice) + ko_dice
        if not self.turnover and self.engine_turn_open():
            self.act(cmd, A_END_TURN, dice=boundary_dice)
        else:
            # Turnover or every player used: the engine auto-ends the team
            # turn during the last act's advance — an explicit END_TURN here
            # would land on the NEXT team's fresh turn and skip it.
            if boundary_dice:
                self.attach(cmd, boundary_dice, "turn end")
        self.turnend_dice = []
        self.pickmeup = []
        # Engine boundary bookkeeping: turn_end(T) flips T's aged stunned
        # players to prone; turn_start(1-T) ages the next team's fresh ones.
        ended = self.active_team
        if ended is not None:
            for pid, (t, _) in self.slot_of.items():
                if t == ended and self.stun_stage.get(pid) == "aged":
                    del self.stun_stage[pid]
                    self.base[pid] = 1
            self.age_stunned(1 - ended)
        self.emit_expect(cmd, skip_ball=bool(td))
        self.acts_this_turn = 0
        self.used_this_turn = set()
        self.turnover = False
        self.activation = None
        self.pending_block = None
        self.stood_block = None
        self.pending_step = None
        self.pre_dice = []
        self.pre_route = False

    def rep_swarmingPlayersRoll(self, i, r, cmd):
        self.skip(cmd, "swarming_divergence", f"d3={r.get('roll')}")

    def rep_playerAction(self, i, r, cmd):
        pid = str(r.get("actingPlayerId"))
        action = r.get("playerAction") or ""
        # (Kickoff-event free actions are dropped wholesale by the
        # KICKOFF_FREE_MODES guard in handle_report.)
        ts = self.slot_of.get(pid)
        if not ts:
            self.skip(cmd, "activation_unknown_player", pid)
            return
        team, sl = ts
        a = self.activation
        if a and a["pid"] == pid and not a.get("closed"):
            # secondary report inside the same activation
            if action == "standUp":
                if a.get("stood"):
                    return  # implicit stand-up already emitted at DECLARE
                self.resolve_pending_followup(cmd)
                self.act(cmd, A_STAND_UP)
                self.base[pid] = 0
                a["moved"] = 3  # engine: standing up costs 3 MA
                a["stood"] = True
                return
            if action in ("blitzMove", "blitz", "passMove", "foulMove",
                          "handOverMove", "gazeMove", "throwTeamMateMove",
                          "kickTeamMateMove", "move"):
                return  # stage transition, already declared
        if action in UNMAPPED_ACTIONS:
            self.close_activation(cmd)
            self.skip(cmd, "player_action_unmapped", action)
            self.activation = {"pid": pid, "kind": None, "closed": True}
            return
        if self.activation_aborted(i, pid):
            return  # select-then-deselect: FFB does not consume the activation
        # new activation
        self.resolve_pending_followup(cmd)
        if self.activation and not self.activation.get("closed"):
            self.close_activation(cmd)
        self.pending_block = None
        self.stood_block = None
        self.pre_dice = []
        self.pre_route = False
        self.active_team = team
        self.acts_this_turn += 1
        gslot = team * 16 + sl
        gate_dice, gate_failed = [], False
        if self.skillnames.get(pid, set()) & {s for s in GATE_SKILLS}:
            j = self.lookahead(i, lambda x: x.get("report") == "confusionRoll" and
                               str(x.get("playerId")) == pid)
            if j >= 0:
                self.consumed.add(j)
                final = self.recs[j]
                # FFB allows a team re-roll on a failed gate; the engine's
                # gate is a single inline die. Consume the re-roll chain and
                # feed the FINAL outcome through the one engine die.
                for k in range(j + 1, min(j + 4, len(self.recs))):
                    rk = self.recs[k]
                    rep_k = rk.get("report")
                    if rep_k == "reRoll" and str(rk.get("playerId")) == pid:
                        self.consumed.add(k)
                        src = rk.get("reRollSource") or ""
                        if src in ("Team ReRoll", "Brilliant Coaching ReRoll",
                                   "Leader", "Mascot TRR"):
                            team_rr = self.pid_team(pid)
                            if team_rr is not None and self.rerolls[team_rr] > 0:
                                self.rerolls[team_rr] -= 1
                        self.skips["gate_reroll_folded"] += 1
                    elif rep_k == "confusionRoll" and \
                            str(rk.get("playerId")) == pid:
                        self.consumed.add(k)
                        final = rk
                    elif rk.get("type") in ("dice", "action", "event",
                                            "formation"):
                        break
                roll = int(final.get("roll") or 1)
                ok = bool(final.get("successful"))
                gate_failed = not ok
                # Outcome-preserving die adjustment: FFB applies situational
                # modifiers (Really Stupid's +2 helper) the engine lacks —
                # feed a die that reproduces FFB's pass/fail against the
                # engine's flat target. Engine gap recorded for cycle 2.
                target = min(GATE_SKILLS[s] for s in
                             (self.skillnames.get(pid, set()) & set(GATE_SKILLS)))
                if ok and roll < target:
                    roll = target
                    self.skips["gate_die_outcome_adjusted"] += 1
                elif not ok and roll >= target:
                    roll = target - 1
                    self.skips["gate_die_outcome_adjusted"] += 1
                gate_dice = [roll]
        self.act(cmd, A_ACTIVATE, gslot, dice=gate_dice,
                 note=f"activate {pid} {action}")
        self.used_this_turn.add(pid)
        if gate_failed or action == "removeConfusion":
            if not gate_failed and action == "removeConfusion":
                # gate passed but FUMBBL only cleared confusion: burn the
                # activation as a bare Move.
                self.act(cmd, A_DECLARE, ACT_MOVE)
                self.act(cmd, A_END_ACTIVATION)
            self.activation = {"pid": pid, "kind": None, "closed": True}
            return
        kind = PLAYER_ACTION_KIND.get(action)
        stand_first = action in ("standUp", "standUpBlitz")
        if kind is None and action == "standUp":
            kind = ACT_MOVE
        if kind is None:
            self.skip(cmd, "player_action_unknown", action)
            kind = ACT_MOVE
        dec_dice = []
        if self.skillnames.get(pid, set()) & DECLARE_ROLL_SKILLS:
            j = self.lookahead(i, lambda x: x.get("report") in
                               ("animalSavageryRoll", "confusionRoll") and
                               str(x.get("playerId")) == pid)
            if j >= 0:
                self.consumed.add(j)
                dec_dice = [self.recs[j].get("roll") or 1]
        self.act(cmd, A_DECLARE, kind, dice=dec_dice)
        self.activation = {"pid": pid, "kind": kind, "closed": False,
                           "blocks": 0, "moved": 0}
        # A prone player stands up first whatever the declared action; FFB
        # leaves the stand-up implicit unless the action IS "standUp".
        if stand_first or self.base.get(pid) == 1:
            self.act(cmd, A_STAND_UP)
            self.base[pid] = 0
            self.activation["moved"] = 3  # engine: standing up costs 3 MA
            self.activation["stood"] = True
        if action == "secureTheBall":
            pass  # steps follow; pickup test rides on the step

    def activation_aborted(self, i, pid):
        """FFB lets a coach select a player, declare an action, and deselect
        without doing anything — the player is NOT used and may activate
        later. Signature: the next record about this pid is a state revert to
        standing/prone (FFB base 1/3) with the active flag (bit 256) still
        set, with no move or roll for the pid in between."""
        for j in range(i + 1, min(i + 1 + 8, len(self.recs))):
            if j in self.consumed:
                continue
            r = self.recs[j]
            t = r.get("type")
            if t == "state" and str(r.get("player")) == pid:
                if r.get("base") == 2:   # MOVING: still selected
                    continue
                return r.get("base") in (1, 3) and \
                    bool((r.get("flags") or 0) & 256)
            if t == "move" and str(r.get("player")) == pid:
                return False
            if t == "dice" and str(r.get("playerId") or "") == pid:
                return False
            if t in ("action", "event", "formation"):
                return False
        return False

    def rep_selectBlitzTarget(self, i, r, cmd):
        if self.activation:
            self.activation["blitz_target"] = str(r.get("defenderId"))

    # tests ----------------------------------------------------------------------------------
    def _test_record(self, i, r, cmd, pre=True):
        """Common d6-test handling with re-roll chains and decline mirroring."""
        del pre  # routing is uniform: pending step if open, else last act
        pid = str(r.get("playerId"))
        roll = int(r.get("roll") or 1)
        ok = bool(r.get("successful"))
        rerolled = bool(r.get("reRolled"))
        self.route_die(cmd, roll, r.get("report"))
        if not ok and not rerolled:
            # final failure (or failure awaiting a reRoll record next)
            j = self.lookahead(i, lambda x: x.get("report") in ("reRoll",) and
                               str(x.get("playerId")) == pid, limit=3)
            if j < 0:
                if self.mirror_reroll_available(pid, r.get("report")):
                    self.route_reroll(cmd, "decline")
                self.fail_likely_turnover(pid)
            else:
                # A re-roll was attempted, but a failed Pro (3+) or a failed
                # Loner gate wastes it: no second test record follows and the
                # failure stands.
                k = self.lookahead(j, lambda x: x.get("report") ==
                                   r.get("report") and
                                   str(x.get("playerId")) == pid, limit=4)
                if k < 0:
                    self.fail_likely_turnover(pid)
        if not ok and rerolled:
            self.fail_likely_turnover(pid)

    def mirror_reroll_available(self, pid, report):
        team = self.pid_team(pid)
        if team is None:
            return False
        team_ok = (self.rerolls[team] > 0 and team == self.active_team and
                   not self.in_kickoff_resolution)
        sk = TEST_RR_SKILL.get(report)
        skill_ok = sk and self.has_skill(pid, sk) and \
            sk not in self.skill_rr_used[pid]
        pro_ok = self.has_skill(pid, "Pro")
        return bool(team_ok or skill_ok or pro_ok)

    def rep_goForItRoll(self, i, r, cmd):
        # A rush that is NOT for the pending step is the blitz's
        # rush-for-block: the engine rolls it during the BLOCK_TARGET
        # transition, so the whole test chain routes to the pre-block buffer.
        a = self.activation
        if (a and not a.get("closed") and a.get("kind") == ACT_BLITZ and
                (self.pending_step is None or
                 not self.pending_step.get("is_rush"))):
            self.pre_route = True
        self._test_record(i, r, cmd, pre=True)
        if r.get("successful") or r.get("reRolled"):
            self.pre_route = False
        elif self.lookahead(i, lambda x: x.get("report") == "reRoll" and
                            str(x.get("playerId")) == str(r.get("playerId")),
                            limit=3) < 0:
            self.pre_route = False  # final failure: chain over

    def rep_dodgeRoll(self, i, r, cmd):
        self._test_record(i, r, cmd, pre=True)

    rep_jumpRoll = rep_dodgeRoll
    rep_leapRoll = rep_dodgeRoll

    def rep_pickUpRoll(self, i, r, cmd):
        self._test_record(i, r, cmd, pre=False)
        if r.get("successful"):
            self.carrier = str(r.get("playerId"))
            a = self.activation
            if a and a.get("kind") == ACT_SECURE:
                a["closed"] = True  # engine: securing the ball ends the activation

    def rep_catchRoll(self, i, r, cmd):
        # Catches during kickoff resolution get no team re-roll (engine M4).
        self._test_record(i, r, cmd, pre=False)
        if r.get("successful"):
            self.carrier = str(r.get("playerId"))

    def rep_standUpRoll(self, i, r, cmd):
        self._test_record(i, r, cmd, pre=False)

    def rep_passRoll(self, i, r, cmd):
        # PASS_TARGET: the ball record at this cmd is the declared target.
        target = self.ball
        if self.activation and not self.activation.get("closed"):
            if target:
                self.resolve_pending_followup(cmd)
                self.act(cmd, A_PASS_TARGET, 0, target[0], target[1])
            else:
                self.skip(cmd, "pass_target_unknown", r.get("playerId"))
        self.carrier = None
        self._test_record(i, r, cmd, pre=False)
        if self.activation:
            self.activation["closed"] = True  # pass ends the activation

    def rep_interceptionRoll(self, i, r, cmd):
        self.skip(cmd, "interception_window", r.get("playerId"))
        self.attach(cmd, [r.get("roll") or 1], "interception")

    def rep_confusionRoll(self, i, r, cmd):
        # Normally consumed by activation lookahead; leftovers are skips.
        self.skip(cmd, "confusion_roll_unattached", r.get("confusionSkill"))

    def rep_animalSavageryRoll(self, i, r, cmd):
        self.skip(cmd, "animal_savagery_unattached", r.get("playerId"))

    def rep_tentaclesShadowingRoll(self, i, r, cmd):
        if (r.get("skill") or "") == "Tentacles":
            if self.pending_step is not None:
                self.pending_step["items"].append(("die", int(r.get("roll") or 1)))
            else:
                self.pre_dice.append(("die", int(r.get("roll") or 1)))
        else:
            self.route_die(cmd, int(r.get("roll") or 1), "shadowing")

    def rep_steadyFootingRoll(self, i, r, cmd):
        self.route_die(cmd, int(r.get("roll") or 1), "steady footing")

    def rep_dauntlessRoll(self, i, r, cmd):
        self.pre_dice.append(("die", int(r.get("roll") or 1)))

    def rep_foulAppearanceRoll(self, i, r, cmd):
        self.skips["foul_appearance_roll_dropped"] += 1  # engine: FA not implemented

    def rep_pickMeUp(self, i, r, cmd):
        """Pick Me Up rolls at the end of the opponent's turn. The engine
        only rolls for players that are PRONE when pick_me_up runs — players
        still stunned/stunned_used at that moment (they flip later, in
        turn_end) are not candidates even though FFB already rolled for
        them. Engine rolls iterate slots ascending: buffer (slot, roll) and
        sort at the boundary."""
        pid = str(r.get("playerId"))
        ts = self.slot_of.get(pid)
        candidate = (ts is not None and self.base.get(pid) == 1 and
                     not self.stun_stage.get(pid) and self.pos.get(pid))
        if candidate:
            helped = False
            px, py = self.pos[pid]
            for hid, (ht, _) in self.slot_of.items():
                if ht != ts[0] or hid == pid:
                    continue
                if self.base.get(hid) != 0 or not self.pos.get(hid):
                    continue
                if not self.has_skill(hid, "Pick Me Up"):
                    continue
                hx, hy = self.pos[hid]
                if max(abs(hx - px), abs(hy - py)) <= 3:
                    helped = True
                    break
            candidate = helped
        if candidate:
            self.pickmeup.append((ts[0] * 16 + ts[1], int(r.get("roll") or 1)))
        else:
            self.skip(cmd, "pick_me_up_engine_no_candidate", pid)

    def rep_regenerationRoll(self, i, r, cmd):
        self.skip(cmd, "regeneration_unattached", r.get("playerId"))

    # re-rolls --------------------------------------------------------------------------------
    def rep_reRoll(self, i, r, cmd):
        src = r.get("reRollSource") or ""
        pid = str(r.get("playerId"))
        if src == "Loner":
            return  # consumed by the Team ReRoll record's lookahead
        loner_die = None
        j = self.lookahead(i, lambda x: x.get("report") == "reRoll" and
                           x.get("reRollSource") == "Loner", limit=2)
        loner_ok = True
        if j >= 0:
            self.consumed.add(j)
            loner_die = int(self.recs[j].get("roll") or 1)
            loner_ok = bool(self.recs[j].get("successful"))
        team = self.pid_team(pid)
        if src in ("Team ReRoll", "Brilliant Coaching ReRoll", "Leader",
                   "Mascot TRR"):
            if team is not None and self.rerolls[team] > 0:
                self.rerolls[team] -= 1
            if self.pending_block:
                self.pending_block["team_rr"] = True
                self.pending_block["loner_die"] = loner_die
                self.pending_block["loner_ok"] = loner_ok
                return
            self.route_reroll(cmd, "team", loner_die=loner_die)
        elif src == "Pro":
            if self.pending_block:
                self.skip(cmd, "block_pro_reroll", pid)
                return
            self.route_reroll(cmd, "pro", loner_die=int(r.get("roll") or 0) or None)
        else:
            sk = self.skill_by_slug.get(skill_slug(src))
            if sk:
                self.skill_rr_used[pid].add(sk)
                if self.pending_block:
                    self.skip(cmd, "block_skill_reroll", src)
                    return
                self.route_reroll(cmd, "skill", skill=self.skill_id(sk))
            else:
                self.skip(cmd, "reroll_source_unmapped", src)
                if self.pending_block:
                    self.pending_block["unmapped_rr"] = True

    def skill_id(self, display):
        try:
            return self.engine_skills.index(display)
        except ValueError:
            return 0

    def rep_mascotUsed(self, i, r, cmd):
        """Team Mascot re-roll: FFB rolls a d6 activation check (4+) and on
        success re-rolls like a team re-roll without spending one. The engine
        has no mascot — map a successful use to A_USE_REROLL/RR_TEAM (which
        spends an engine re-roll; mirrored below) and drop the activation d6
        the engine never rolls."""
        self.skips["mascot_activation_roll_dropped"] += 1
        if not r.get("successful"):
            return  # failed activation: no re-roll happened
        team = 0 if str(r.get("teamId")) == str(self.meta["teamHome"]["teamId"]) else 1
        if self.rerolls[team] > 0:
            self.rerolls[team] -= 1  # mirror the ENGINE's reroll spend
        if self.pending_block:
            self.pending_block["team_rr"] = True
            return
        self.route_reroll(cmd, "team")

    def rep_blockReRoll(self, i, r, cmd):
        src = r.get("reRollSource") or ""
        if self.pending_block:
            if src in ("Brawler",):
                self.pending_block["brawler"] = [int(v) for v in
                                                 (r.get("blockRoll") or [])]
            else:
                self.pending_block["unmapped_rr"] = True
                self.skip(cmd, "block_reroll_unmapped", src)
        else:
            self.skip(cmd, "block_reroll_orphan", src)

    # blocks ---------------------------------------------------------------------------------
    def rep_block(self, i, r, cmd):
        defender = str(r.get("defenderId"))
        if self.pending_block and self.pending_block.get("def") == defender and \
                not self.pending_block.get("chosen"):
            return  # re-emitted block event around a re-roll
        a = self.activation
        if not a or a.get("closed"):
            self.skip(cmd, "block_without_activation", defender)
            return
        frenzy_second = bool(self.pending_block is None and a.get("blocks", 0) > 0
                             and a.get("last_def") == defender and
                             self.has_skill(a["pid"], "Frenzy"))
        self.resolve_pending_followup(cmd)
        self.flush_step(cmd)
        self.stood_block = None
        self.pending_block = {"att": a["pid"], "def": defender, "pools": [],
                              "team_rr": False, "loner_die": None,
                              "loner_ok": True, "brawler": None,
                              "unmapped_rr": False, "chosen": False,
                              "phase": "dice", "no_followup": False,
                              "stood_firm": False,
                              "from_blitz": a.get("kind") == ACT_BLITZ,
                              "frenzy_second": frenzy_second, "cmd": cmd}
        a["blocks"] = a.get("blocks", 0) + 1
        a["last_def"] = defender
        if a.get("kind") == ACT_BLITZ and not frenzy_second:
            a["moved"] = a.get("moved", 0) + 1  # blitz block costs a square

    def rep_blockRoll(self, i, r, cmd):
        pool = [int(v) for v in (r.get("blockRoll") or [])]
        if not self.pending_block:
            self.skip(cmd, "block_roll_orphan", pool)
            return
        pb = self.pending_block
        if pb["team_rr"] and not pb["loner_ok"] and pb["pools"]:
            return  # wasted loner re-roll: FFB re-reports the unchanged pool
        pb["pools"].append(pool)

    def rep_blockChoice(self, i, r, cmd):
        pb = self.pending_block
        if not pb:
            self.skip(cmd, "block_choice_orphan", r.get("blockResult"))
            return
        pb["chosen"] = True
        a = self.activation
        att = pb["att"]
        team = self.pid_team(att)
        final_pool = [int(v) for v in (r.get("blockRoll") or [])] or \
            (pb["pools"][-1] if pb["pools"] else [])
        first_pool = pb["pools"][0] if pb["pools"] else final_pool
        if pb["unmapped_rr"]:
            first_pool = final_pool  # pretend FUMBBL's special reroll never was
            pb["team_rr"] = False
        # BLOCK_TARGET act (skip for the auto frenzy second block)
        if not pb["frenzy_second"]:
            dpos = self.pos.get(pb["def"])
            if not dpos:
                self.skip(cmd, "block_target_unknown_pos", pb["def"])
                self.pending_block = None
                return
            pre, segs = self.split_pre_dice()
            pool = list(first_pool)
            if pb["brawler"] and not pb["team_rr"]:
                pool += pb["brawler"]
            if segs:
                # A pre-block test (rush-for-block etc.) was re-rolled: the
                # engine rolls the block pool during the re-roll act's
                # advance, not during BLOCK_TARGET's.
                segs[-1][2].extend(pool)
                self.act(pb["cmd"], A_BLOCK_TARGET, 0, dpos[0], dpos[1],
                         dice=pre)
                self.flush_reroll_acts(cmd, segs)
            else:
                self.act(pb["cmd"], A_BLOCK_TARGET, 0, dpos[0], dpos[1],
                         dice=pre + pool)
        else:
            # The engine starts the frenzy second block inside the first
            # block's push/follow-up transition: any rush-for-block test
            # (buffered in pre_dice) rolls there, then the second pool — all
            # attached to the already-emitted push op.
            pre, segs = self.split_pre_dice()
            pool = list(first_pool)
            if pb["brawler"] and not pb["team_rr"]:
                pool += pb["brawler"]
            if segs:
                # Re-rolled pre-block test: the engine pauses mid-push for
                # the re-roll decision; the new pool rolls in its advance.
                segs[-1][2].extend(pool)
                self.attach(cmd, pre, "frenzy second rush")
                self.flush_reroll_acts(cmd, segs)
            else:
                self.attach(cmd, pre + pool, "frenzy second pool")
        # Engine pauses for the team re-roll offer whenever one is available.
        engine_offers = (team is not None and self.rerolls[team] >= 0 and
                         team == self.active_team)
        mirror_has_rr = team is not None and \
            (self.rerolls[team] + (1 if pb["team_rr"] else 0)) > 0
        if pb["team_rr"]:
            rr_dice = ([pb["loner_die"]] if pb["loner_die"] else [])
            if pb["loner_ok"]:
                rr_dice += final_pool
                if pb["brawler"]:
                    rr_dice += pb["brawler"]
            self.act(cmd, A_USE_REROLL, RR_TEAM, dice=rr_dice)
        elif engine_offers and mirror_has_rr and not self.in_kickoff_resolution:
            self.act(cmd, A_DECLINE_REROLL)
        idx = int(r.get("diceIndex") or 0)
        nd = abs(int(r.get("nrOfDice") or len(final_pool)) or 1)
        self.act(cmd, A_CHOOSE_DIE, idx if idx < max(nd, 1) else 0)
        result = (r.get("blockResult") or "").upper()
        att_skills = self.skillnames.get(att, set())
        def_skills = self.skillnames.get(pb["def"], set())
        if result in ("PUSHBACK", "POW/PUSH", "POW"):
            stood = ("Stand Firm" in def_skills and not
                     (pb.get("from_blitz") and "Juggernaut" in att_skills))
            if stood:
                # Engine auto-applies Stand Firm (no push/follow-up
                # decisions). FFB lets the coach DECLINE it: if push/follow
                # moves arrive next they are a known engine-policy
                # divergence, flagged via stood_block in handle_move.
                self.stood_block = {"att": att, "def": pb["def"],
                                    "def_sq": self.pos.get(pb["def"])}
                self.pending_block = None
                return
            pb["phase"] = "push"
            # Engine PUSH phase 3 order: Fend (Juggernaut on a blitz cancels)
            # kills the follow-up; otherwise Frenzy FORCES it (no decision,
            # attacker auto-placed during the push transition).
            fend = "Fend" in def_skills and not \
                (pb["from_blitz"] and "Juggernaut" in att_skills)
            frenzy = "Frenzy" in att_skills
            pb["no_followup"] = fend or frenzy
            pb["forced_followup"] = frenzy and not fend
        elif result == "SKULL":
            self.fail_likely_turnover(att)
            self.pending_block = None
        elif result == "BOTH DOWN":
            self.last_both_down = {"att": att, "def": pb["def"], "cmd": cmd}
            wrestle = "Wrestle" in att_skills or "Wrestle" in def_skills
            att_block = "Block" in att_skills
            if not wrestle and not att_block:
                self.fail_likely_turnover(att)
            if wrestle and self.carrier in (att, pb["def"]):
                if self.pid_team(self.carrier) == self.active_team:
                    self.turnover = True
            self.pending_block = None
        else:
            self.pending_block = None

    CHAIN_DIRS = [(-1, -1), (0, -1), (1, -1), (1, 0), (1, 1), (0, 1),
                  (-1, 1), (-1, 0)]  # engine push_candidates ring order

    def chain_crowd_square(self, origin, pushee):
        """Engine crowd candidate for a chained player pushed off the pitch:
        the off-pitch square among the three 'behind' candidates (primary
        direction preferred), clamped exactly like push_legal encodes it."""
        dx, dy = pushee[0] - origin[0], pushee[1] - origin[1]
        try:
            main = self.CHAIN_DIRS.index((dx, dy))
        except ValueError:
            return None
        order = [main, (main + 7) % 8, (main + 1) % 8]
        for k in order:
            cx = pushee[0] + self.CHAIN_DIRS[k][0]
            cy = pushee[1] + self.CHAIN_DIRS[k][1]
            if not (0 <= cx <= 25 and 0 <= cy <= 14):
                return (min(max(cx, 0), 25), min(max(cy, 0), 14))
        return None

    def emit_chain_push(self, cmd, x, y, on_pitch):
        """The defender's relocation arrived with buffered chain links
        (innermost players move first in FFB). Engine decision order is the
        reverse: parent PUSH_SQUARE (arg 2 = occupied), then one decision per
        chained pushee, deepest last (arg 0 empty / arg 1 crowd). Returns
        False (with a classified skip) when the buffered moves do not form a
        consistent chain."""
        pb = self.pending_block
        chain = pb.get("chain") or []
        ok = on_pitch and chain and chain[-1]["from"] == (x, y)
        for j in range(len(chain) - 1):
            if chain[j + 1]["to"] != chain[j]["from"] or not chain[j]["from"]:
                ok = False
        if not (ok and chain[0]["from"]):
            self.skip(cmd, "chain_push_unmatched",
                      f"def->{x},{y} links={len(chain)}")
            self.pending_block = None
            return False
        self.act(cmd, A_PUSH_SQUARE, 2, x, y)  # parent: into the occupied sq
        rev = list(reversed(chain))            # decision order: shallow->deep
        for idx, link in enumerate(rev):
            deepest = idx == len(rev) - 1
            if not deepest:
                self.act(cmd, A_PUSH_SQUARE, 2, link["to"][0], link["to"][1])
            elif link["to"] is not None:
                self.act(cmd, A_PUSH_SQUARE, 0, link["to"][0], link["to"][1])
            else:
                # Chained player surfed: the push origin is the previous
                # pushee's square BEFORE its own relocation (engine spawns
                # the child before the parent relocates).
                origin = rev[idx - 1]["from"] if idx else self.move_from
                sq = self.chain_crowd_square(origin, link["from"]) \
                    if origin else None
                if sq is None:
                    self.skip(cmd, "chain_push_unmatched", "crowd geometry")
                    self.pending_block = None
                    return False
                self.act(cmd, A_PUSH_SQUARE, 1, sq[0], sq[1], note="chain crowd")
        return True

    def emit_crowd_push(self, cmd):
        pb = self.pending_block
        apos = self.pos.get(pb["att"])
        dpos = self.pos.get(pb["def"])
        if not apos or not dpos:
            self.skip(cmd, "crowd_push_unknown_pos", pb["def"])
            return
        dx, dy = dpos[0] - apos[0], dpos[1] - apos[1]
        x = min(max(dpos[0] + dx, 0), 25)
        y = min(max(dpos[1] + dy, 0), 14)
        self.act(cmd, A_PUSH_SQUARE, 1, x, y, note="crowd")

    def rep_pushback(self, i, r, cmd):
        pass  # the defender's move record carries the chosen square

    # skillUse reports where the engine's automatic behavior matches what FFB
    # reported (pure information for us — like move-square UI noise). Pairs
    # are (skill, skillUse); a used:false record never matches this table.
    SKILL_USE_AUTO = {
        ("Dodge", "avoidFalling"),          # Dodge-on-Stumble, engine auto
        ("Steady Footing", "avoidFalling"),
        ("Horns", "increaseStrengthBy1"),   # blitz ST bonus, engine auto
        ("Eye Gouge", "eyeGouged"),
        ("Fend", "stayAwayFromOpponent"),   # mirrored via pb["no_followup"]
        ("Tackle", "cancelDodge"),
        ("Kick", "halveKickoffScatter"),    # mirrored in rep_kickoffScatter
        ("Break Tackle", "wouldNotHelp"),
        ("Diving Tackle", "wouldNotHelp"),
        ("Stand Firm", "noTackleZone"),
        ("Sidestep", "noTackleZone"),
        ("Sure Hands", "noTackleZone"),
        ("Sure Hands", "cancelStripBall"),  # engine Monstrous Mouth-style cancel
        ("Strip Ball", "stealBall"),        # engine auto on push
        ("Juggernaut", "cancelStandFirm"),
        ("Juggernaut", "pushBackOpponent"),
        ("Wrestle", "bringDownOppponent"),  # engine auto-applies on Both Down
        ("Taunt", "forceFollowUp"),         # follow-up mapped from the move
    }

    def rep_skillUse(self, i, r, cmd):
        sk = r.get("skill") or ""
        use = r.get("skillUse") or ""
        used = bool(r.get("used"))
        if sk == "Stand Firm" and use == "avoidPush":
            # engine auto-applies Stand Firm; FFB agreed -> no divergence
            self.pending_block = None
            self.stood_block = None
            return
        if sk == "Wrestle" and not used:
            # The coach declined Wrestle on a Both Down; the engine
            # auto-applies it (both placed prone, no armour). Genuine engine
            # divergence (no USE_SKILL window yet): the participants' states
            # and the decline-path armour dice cannot be mirrored.
            bd = self.last_both_down or {}
            for pid in (bd.get("att"), bd.get("def")):
                if pid:
                    self.ignore_state.add(pid)
                    self.suppress_injury.add(pid)
            self.skip(cmd, "wrestle_decline_divergence",
                      f"{bd.get('att')} vs {bd.get('def')}")
            return
        if used and (sk, use) in self.SKILL_USE_AUTO:
            self.skips["skill_use_auto_matched"] += 1
            return
        self.skip(cmd, "skill_use_unmapped", f"{sk}/{use}")

    # injuries ---------------------------------------------------------------------------------
    def rep_injury(self, i, r, cmd):
        key = (cmd, str(r.get("defenderId")), json.dumps(r.get("armorRoll")),
               json.dumps(r.get("injuryRoll")), json.dumps(r.get("casualtyRoll")))
        if key == self.last_injury_key:
            return  # FFB duplicates injury reports verbatim
        self.last_injury_key = key
        pid = str(r.get("defenderId"))
        if pid in self.suppress_injury:
            # Injury from a path the engine resolved differently (declined
            # Wrestle, demoted foul): FFB-only dice, never fed to the engine.
            self.suppress_injury.discard(pid)
            self.ignore_state.add(pid)
            self.skip(cmd, "suppressed_injury_dice", pid)
            return
        team = self.pid_team(pid)
        dice = []
        if r.get("armorRoll"):
            dice += [int(v) for v in r["armorRoll"]]
        if r.get("injuryRoll"):
            dice += [int(v) for v in r["injuryRoll"]]
        injured_base = r.get("injury")
        cas = r.get("casualtyRoll")
        regen_ok = False
        if cas and self.has_skill(pid, "Regeneration"):
            j = self.lookahead(i, lambda x: x.get("report") == "regenerationRoll"
                               and str(x.get("playerId")) == pid, limit=20)
            if j >= 0:
                self.consumed.add(j)
                dice.append(int(self.recs[j].get("roll") or 1))
                regen_ok = bool(self.recs[j].get("successful"))
        if cas and not regen_ok:
            dice.append(int(cas[0]))
            if len(cas) > 1:
                self.skips["casualty_lasting_d6_dropped"] += 1
        if self.pending_block and pid == self.pending_block.get("def") and \
                self.pending_block["phase"] in ("push", "followup"):
            # injury arrived before push/follow-up ops: resolve them first
            self.resolve_pending_followup(cmd)
        self.attach(cmd, dice, "injury")
        if self.pid_team(pid) == self.active_team:
            # knocked-down active-team player: engine latches a turnover
            if injured_base is None or injured_base >= 3 or r.get("armorRoll"):
                self.fail_likely_turnover(pid)
        if self.carrier == pid:
            self.carrier = None
        # Apothecary windows.
        if team is None:
            return
        is_ko = injured_base == 5
        is_cas = bool(cas) and not regen_ok
        # FFB decline signature (StepApothecary DO_NOT_USE_APOTHECARY): an
        # apothecaryRoll report with every field null. A used apothecary
        # reports the new casualty roll (cas) or an apothecaryChoice (KO).
        def apo_decline(x):
            return (x.get("report") == "apothecaryRoll" and
                    str(x.get("playerId")) == pid and
                    not x.get("casualtyRoll") and x.get("playerState") is None)
        if is_ko and self.apo[team] > 0:
            jd = self.lookahead(i, apo_decline, limit=10)
            ju = self.lookahead(i, lambda x: x.get("report") == "apothecaryChoice"
                                and str(x.get("playerId")) == pid, limit=10)
            used = ju >= 0 and (jd < 0 or ju < jd)
            if used:
                self.consumed.add(ju)
                self.apo[team] -= 1
                self.stun_stage.setdefault(pid, "fresh")  # patched: stunned
            elif jd >= 0:
                self.consumed.add(jd)
            self.act(cmd, A_APOTHECARY, 1 if used else 0, note="ko window")
        elif is_cas and self.apo[team] > 0:
            j = self.lookahead(i, lambda x: x.get("report") == "apothecaryRoll"
                               and str(x.get("playerId")) == pid, limit=12)
            if j >= 0 and apo_decline(self.recs[j]):
                self.consumed.add(j)
                self.act(cmd, A_APOTHECARY, 0, note="casualty apo declined")
            elif j >= 0:
                self.consumed.add(j)
                self.apo[team] -= 1
                cas2 = self.recs[j].get("casualtyRoll") or [1]
                jc = self.lookahead(j, lambda x: x.get("report") ==
                                    "apothecaryChoice" and
                                    str(x.get("playerId")) == pid, limit=8)
                if jc >= 0:
                    self.consumed.add(jc)
                self.act(cmd, A_APOTHECARY, 1, dice=[int(cas2[0])],
                         note="casualty apothecary")
            else:
                self.act(cmd, A_APOTHECARY, 0, note="casualty declined")

    def rep_apothecaryRoll(self, i, r, cmd):
        self.skip(cmd, "apothecary_roll_unattached", r.get("playerId"))

    def rep_apothecaryChoice(self, i, r, cmd):
        self.skip(cmd, "apothecary_choice_unattached", r.get("playerId"))

    # fouls / misc actions ------------------------------------------------------------------------
    def rep_foul(self, i, r, cmd):
        a = self.activation
        defender = str(r.get("defenderId"))
        dpos = self.pos.get(defender)
        if not a or a.get("closed") or not dpos:
            self.skip(cmd, "foul_unmapped", defender)
            return
        self.resolve_pending_followup(cmd)
        self.act(cmd, A_FOUL_TARGET, 0, dpos[0], dpos[1])
        a["foul_def"] = defender

    def rep_referee(self, i, r, cmd):
        # Engine asks Argue-the-Call only when the armour/injury dice showed a
        # natural double; mirror from the foul's last injury record.
        if not self.last_injury_key:
            return
        try:
            arm = json.loads(self.last_injury_key[2]) or []
            inj = json.loads(self.last_injury_key[3]) or []
        except (json.JSONDecodeError, TypeError):
            arm, inj = [], []
        doubles = (len(arm) == 2 and arm[0] == arm[1]) or \
                  (len(inj) == 2 and inj[0] == inj[1])
        if not doubles:
            return
        j = self.lookahead(i, lambda x: x.get("report") == "argueTheCall",
                           limit=6)
        if j >= 0:
            self.consumed.add(j)
            roll = int(self.recs[j].get("roll") or 1)
            self.act(cmd, A_CHOOSE_OPTION, 1, dice=[roll], note="argue the call")
        else:
            self.act(cmd, A_CHOOSE_OPTION, 0, note="accept send-off")
        self.turnover = True
        if self.activation:
            self.activation["closed"] = True

    def rep_argueTheCall(self, i, r, cmd):
        self.skip(cmd, "argue_unattached", r.get("playerId"))

    def rep_handOver(self, i, r, cmd):
        a = self.activation
        catcher = str(r.get("catcherId"))
        cpos = self.pos.get(catcher)
        if not a or a.get("closed") or not cpos:
            self.skip(cmd, "handoff_unmapped", catcher)
            return
        self.resolve_pending_followup(cmd)
        self.act(cmd, A_HANDOFF_TARGET, 0, cpos[0], cpos[1])
        self.carrier = None
        a["closed"] = True  # hand-off ends the activation

    def rep_scatterBall(self, i, r, cmd):
        faces = [DIR_TO_FACE.get(d, 1) for d in (r.get("directionArray") or [])]
        self.attach(cmd, faces, "scatter")

    def rep_scatterPlayer(self, i, r, cmd):
        self.skip(cmd, "scatter_player_unmapped", r.get("playerId"))

    def rep_throwIn(self, i, r, cmd):
        dname = r.get("direction")
        dist = r.get("distanceRoll") or []
        if not self.ball or dname not in DIR_DELTA:
            self.skip(cmd, "throw_in_unmapped", dname)
            return
        x, y = self.ball
        left, right = x <= 0, x >= 25
        top, bottom = y <= 0, y >= 14
        ix = 1 if left else (-1 if right else 0)
        iy = 1 if top else (-1 if bottom else 0)
        if ix and iy:
            dirs = [(ix, 0), (ix, iy), (0, iy)]
            die_for = lambda k: k + 1  # d3
        elif ix:
            dirs = [(ix, -1), (ix, 0), (ix, 1)]
            die_for = lambda k: 2 * k + 1  # d6 bands
        else:
            dirs = [(-1, iy), (0, iy), (1, iy)]
            die_for = lambda k: 2 * k + 1
        delta = DIR_DELTA[dname]
        try:
            k = dirs.index(delta)
        except ValueError:
            self.skip(cmd, "throw_in_direction_mismatch", dname)
            return
        dice = [die_for(k)] + [int(v) for v in dist][:2]
        self.attach(cmd, dice, "throw in")

    # special actions -------------------------------------------------------------------------------
    def rep_stabRoll(self, i, r, cmd):
        self.attach(cmd, [int(r.get("roll") or 1)], "stab")

    def rep_animalSavagery(self, i, r, cmd):
        pass  # roll handled at DECLARE; lash-out resolution measured as-is

    def rep_stallerDetected(self, i, r, cmd):
        pass

    def rep_leader(self, i, r, cmd):
        pass

    def rep_raiseDead(self, i, r, cmd):
        # A new player materializes mid-game (Necromancer raise): the engine
        # roster is fixed at init — the zombie exists only FFB-side.
        pid = str(r.get("playerId") or "")
        if pid:
            self.ignore_all.add(pid)
        self.skip(cmd, "raise_dead_unrepresented", pid)

    def rep_hitAndRun(self, i, r, cmd):
        self.skip(cmd, "hit_and_run_unmapped", "")

    def rep_kickoffTimeout(self, i, r, cmd):
        pass

    def rep_inducement(self, i, r, cmd):
        self.skip(cmd, "inducement_unmapped", "")

    def rep_secretWeaponBan(self, i, r, cmd):
        self.skips["secret_weapon_ban_roll_dropped"] += 1

    def rep_winnings(self, i, r, cmd):
        self.skips["postgame_roll_dropped"] += 1

    def rep_masterChefRoll(self, i, r, cmd):
        self.skip(cmd, "master_chef_unmapped", "")

    def rep_officiousRefRoll(self, i, r, cmd):
        self.skip(cmd, "officious_ref_unmapped", "")


def load_raw(replay_id):
    path = os.path.join(CACHE_DIR, f"replay_{replay_id}.json.gz")
    if os.path.exists(path):
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    return None


def process(path, quiet=False):
    records = [json.loads(l) for l in open(path, encoding="utf-8")]
    replay_id = os.path.basename(path).replace(".jsonl", "")
    mapper = Mapper(records, raw_replay=load_raw(replay_id))
    ops = mapper.run()
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{replay_id}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for op in ops:
            f.write(json.dumps(op, ensure_ascii=False) + "\n")
    n_act = sum(1 for o in ops if o["op"] == "act")
    n_place = sum(1 for o in ops if o["op"] == "place")
    n_skip = sum(1 for o in ops if o["op"] == "skip")
    n_exp = sum(1 for o in ops if o["op"] == "expect")
    if not quiet:
        print(f"{replay_id}: {len(ops)} ops -> {out_path}  "
              f"(acts={n_act} places={n_place} expects={n_exp} skips={n_skip})")
        if mapper.skips:
            top = ", ".join(f"{k}:{v}" for k, v in mapper.skips.most_common(8))
            print(f"  skips: {top}")
    return out_path, mapper.skips


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("specs", nargs="*", help="replay ids or normalized .jsonl paths")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args()
    specs = list(args.specs)
    if args.all:
        specs += sorted(glob.glob(os.path.join(NORM_DIR, "*.jsonl")))
    if not specs:
        ap.error("give replay ids/paths or --all")
    agg = collections.Counter()
    for spec in specs:
        path = spec if os.path.exists(spec) else os.path.join(NORM_DIR, f"{spec}.jsonl")
        _, skips = process(path, quiet=args.quiet)
        agg.update(skips)
    if len(specs) > 1:
        print("\n=== aggregate skip histogram ===")
        for k, v in agg.most_common():
            print(f"  {v:6d}  {k}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
