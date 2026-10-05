#!/usr/bin/env python3
"""ffb_fold.py: fold a FUMBBL replay's model-change log into full game state.

A FUMBBL (FFB) replay stores the END-of-game snapshot in `game` and, in
`gameLog.commandArray`, every incremental model change the server sent. This
module replays those changes in command order, so the complete public FFB model
is available after ANY command: where every player is, each player's state
(base and flag bits), the ball, the score, the half, whose turn it is, both
turn counters, both re-roll pools, apothecaries, inducements and the weather.

It exists for turn-boundary re-seat (validation/README.md, "Re-seat"): the
lockstep mapper attaches the folded state at each team-turn boundary to its
expect op, and tools/bb_lockstep.c can put the engine into that state.

The fold is checked against the replay itself: `check_final()` compares the
fully folded state with the END-of-game snapshot in `game` and returns every
field that differs. An empty list means the fold reproduced the server's own
final state from the change log alone.

Usage:
  python3 validation/ffb_fold.py 1898990          # self-check one replay
  python3 validation/ffb_fold.py --all             # self-check the cache
Stock python3, stdlib only.
"""
import argparse
import copy
import glob
import gzip
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE_DIR = os.path.join(HERE, "replay_cache")

# PlayerState bits (vendor/ffb PlayerState.java).
BASE_MASK = 0xFF
BIT_ACTIVE = 0x00100
BIT_CONFUSED = 0x00200
BIT_ROOTED = 0x00400
BIT_HYPNOTIZED = 0x00800
BIT_USED_PRO = 0x02000
BIT_EYE_GOUGED = 0x20000
# Selection highlights (stab / blitz / block / gaze target): UI state, not rules.
SELECTION_BITS = 0x01000 | 0x04000 | 0x08000 | 0x10000

# turnData model change id -> (field name, default)
TURN_FIELDS = {
    "turnDataSetTurnNr": "turnNr",
    "turnDataSetReRolls": "reRolls",
    "turnDataSetReRollsSingleUse": "singleUseReRolls",
    "turnDataSetReRollsBrilliantCoachingOneDrive": "rerollBrilliantCoachingOneDrive",
    "turnDataSetReRollsPumpUpTheCrowdOneDrive": "rerollPumpUpTheCrowdOneDrive",
    "turnDataSetReRollsShowStarOneDrive": "rerollShowStarOneDrive",
    "turnDataSetApothecaries": "apothecaries",
    "turnDataSetWanderingApothecaries": "wanderingApothecaries",
    "turnDataSetPlagueDoctors": "plagueDoctors",
    "turnDataSetBlitzUsed": "blitzUsed",
    "turnDataSetFoulUsed": "foulUsed",
    "turnDataSetHandOverUsed": "handOverUsed",
    "turnDataSetPassUsed": "passUsed",
    "turnDataSetTtmUsed": "ttmUsed",
    "turnDataSetKtmUsed": "ktmUsed",
    "turnDataSecureTheBallUsed": "secureTheBallUsed",
    "turnDataSetCoachBanned": "coachBanned",
    "turnDataSetLeaderState": "leaderState",
    "turnDataSetTurnStarted": "turnStarted",
    "turnDataSetFirstTurnAfterKickoff": "firstTurnAfterKickoff",
}
TURN_DEFAULTS = {
    "turnNr": 0, "reRolls": 0, "singleUseReRolls": 0,
    "rerollBrilliantCoachingOneDrive": 0, "rerollPumpUpTheCrowdOneDrive": 0,
    "rerollShowStarOneDrive": 0, "apothecaries": 0,
    "wanderingApothecaries": 0, "plagueDoctors": 0, "blitzUsed": False,
    "foulUsed": False, "handOverUsed": False, "passUsed": False,
    "ttmUsed": False, "ktmUsed": False, "secureTheBallUsed": False,
    "coachBanned": False, "leaderState": "none", "turnStarted": False,
    "firstTurnAfterKickoff": False,
}
# Fields of the END-of-game turnData snapshot the fold is checked against.
TURN_CHECKED = ("turnNr", "reRolls", "rerollBrilliantCoachingOneDrive",
                "rerollPumpUpTheCrowdOneDrive", "apothecaries",
                "wanderingApothecaries", "plagueDoctors", "coachBanned",
                "blitzUsed", "foulUsed", "handOverUsed", "passUsed", "ttmUsed",
                "ktmUsed", "secureTheBallUsed")


def on_pitch(xy):
    return bool(xy) and 0 <= xy[0] <= 25 and 0 <= xy[1] <= 14


# Dugout boxes are coordinates too (FieldCoordinate.java): the home boxes run
# x = -1 (Reserves) to -7 (Missing), the away boxes x = 30 to 36. A player's
# box therefore names their state even before the log sets one.
BOX_BASE = {1: 9, 2: 5, 3: 6, 4: 7, 5: 8, 6: 13, 7: 10}


def box_base(xy):
    """PlayerState base implied by a dugout-box coordinate, else 0."""
    if not xy or on_pitch(xy):
        return 0
    x = xy[0]
    return BOX_BASE.get(-x if x < 0 else x - 29, 0)


def base_of(player):
    """A player's PlayerState base. The log does not state the initial
    Reserves state of a player whose first state change comes later; until
    then the dugout box they sit in says it."""
    base = player["state"] & BASE_MASK
    return base if base else box_base(player["xy"])


def new_state(player_ids):
    return {
        "players": {pid: {"xy": None, "state": 0} for pid in player_ids},
        "ball": {"xy": None, "inPlay": False, "moving": False},
        "half": 0,
        "homePlaying": None,
        "turnMode": "startGame",
        "weather": "Nice Weather",
        "score": {"home": 0, "away": 0},
        "turn": {"home": dict(TURN_DEFAULTS), "away": dict(TURN_DEFAULTS)},
        "inducements": {"home": {}, "away": {}},
        "prayers": {"home": [], "away": []},
    }


def apply_change(st, ch):
    """Apply one model change to the folded state. Unknown ids are ignored:
    the rest of the model is client-side decoration (move squares, track
    numbers, dice decorations, markers) or post-match bookkeeping."""
    cid = ch.get("modelChangeId")
    key = ch.get("modelChangeKey")
    val = ch.get("modelChangeValue")
    if cid == "fieldModelSetPlayerCoordinate":
        p = st["players"].setdefault(str(key), {"xy": None, "state": 0})
        p["xy"] = list(val) if isinstance(val, (list, tuple)) else None
    elif cid == "fieldModelRemovePlayer":
        p = st["players"].setdefault(str(key), {"xy": None, "state": 0})
        p["xy"] = None
    elif cid == "fieldModelSetPlayerState":
        p = st["players"].setdefault(str(key), {"xy": None, "state": 0})
        p["state"] = int(val) if isinstance(val, int) else 0
    elif cid == "fieldModelSetBallCoordinate":
        st["ball"]["xy"] = list(val) if isinstance(val, (list, tuple)) else None
    elif cid == "fieldModelSetBallInPlay":
        st["ball"]["inPlay"] = bool(val)
    elif cid == "fieldModelSetBallMoving":
        st["ball"]["moving"] = bool(val)
    elif cid == "fieldModelSetWeather":
        st["weather"] = val
    elif cid == "gameSetHalf":
        st["half"] = val
    elif cid == "gameSetHomePlaying":
        st["homePlaying"] = bool(val)
    elif cid == "gameSetTurnMode":
        st["turnMode"] = val
    elif cid == "teamResultSetScore":
        if key in st["score"]:
            st["score"][key] = val
    elif cid in TURN_FIELDS:
        if key in st["turn"]:
            st["turn"][key][TURN_FIELDS[cid]] = val
    elif cid == "inducementSetAddInducement":
        if key in st["inducements"] and isinstance(val, dict):
            st["inducements"][key][val.get("inducementType")] = {
                "value": val.get("value") or 0, "uses": val.get("uses") or 0}
    elif cid == "inducementSetRemoveInducement":
        if key in st["inducements"] and isinstance(val, dict):
            st["inducements"][key].pop(val.get("inducementType"), None)
    elif cid == "inducementSetAddPrayer":
        if key in st["prayers"]:
            st["prayers"][key].append(val)
    elif cid == "inducementSetRemovePrayer":
        if key in st["prayers"] and val in st["prayers"][key]:
            st["prayers"][key].remove(val)


def roster_ids(raw):
    game = raw.get("game", {})
    ids = []
    for side in ("teamHome", "teamAway"):
        for p in (game.get(side) or {}).get("playerArray", []) or []:
            ids.append(str(p.get("playerId")))
    return ids


def seed_untouched(raw, st):
    """A player the change log never touches (missing the game, or sat in the
    reserves box from before the first logged command) has no initial value in
    the log. Its END-of-game value is then also its value at every earlier
    command, so seed it from the snapshot. Players the log does touch are
    never seeded: their first logged change is their initial value."""
    touched = {"fieldModelSetPlayerCoordinate": set(),
               "fieldModelRemovePlayer": set(),
               "fieldModelSetPlayerState": set()}
    for cmd in raw.get("gameLog", {}).get("commandArray", []):
        for ch in (cmd.get("modelChangeList") or {}).get("modelChangeArray", []):
            s = touched.get(ch.get("modelChangeId"))
            if s is not None:
                s.add(str(ch.get("modelChangeKey")))
    moved = touched["fieldModelSetPlayerCoordinate"] | touched["fieldModelRemovePlayer"]
    fm = (raw.get("game", {}) or {}).get("fieldModel", {}) or {}
    for pd in fm.get("playerDataArray", []) or []:
        pid = str(pd.get("playerId"))
        p = st["players"].setdefault(pid, {"xy": None, "state": 0})
        if pid not in moved:
            xy = pd.get("playerCoordinate")
            p["xy"] = list(xy) if isinstance(xy, (list, tuple)) else None
        if pid not in touched["fieldModelSetPlayerState"]:
            p["state"] = pd.get("playerState") or 0


class Folder:
    """The fold itself: applies the logged commands in order, one call at a
    time, so a consumer that walks the replay (the lockstep mapper asks at
    each team-turn boundary) pays for one pass."""

    def __init__(self, raw):
        self.state = new_state(roster_ids(raw))
        seed_untouched(raw, self.state)
        self.cmds = [c for c in raw.get("gameLog", {}).get("commandArray", [])
                     if c.get("netCommandId") == "serverModelSync"]
        self.i = 0

    def step(self):
        """Apply the next command (all its changes: FFB sends a command's
        changes as one atomic sync) and return its commandNr."""
        cmd = self.cmds[self.i]
        self.i += 1
        for ch in (cmd.get("modelChangeList") or {}).get("modelChangeArray", []):
            apply_change(self.state, ch)
        return cmd.get("commandNr") or 0

    def at(self, cmd_nr):
        """The live state after every logged command up to and including
        cmd_nr. Not a copy: read it before asking for a later command."""
        while self.i < len(self.cmds) and \
                (self.cmds[self.i].get("commandNr") or 0) <= cmd_nr:
            self.step()
        return self.state


def fold(raw, at_cmds=None):
    """Fold the whole change log. Returns (snapshots, final) where snapshots
    maps each requested commandNr to a deep copy of the state right after
    that command and final is the state after the last command."""
    want = set(at_cmds or ())
    folder = Folder(raw)
    snaps = {}
    while folder.i < len(folder.cmds):
        nr = folder.step()
        if nr in want:
            snaps[nr] = copy.deepcopy(folder.state)
    return snaps, folder.state


def check_final(raw, final):
    """Compare the folded final state with the replay's END-of-game snapshot.
    Returns a list of (field, folded, snapshot) for every difference."""
    game = raw.get("game", {})
    fm = game.get("fieldModel", {}) or {}
    diffs = []

    def cmp(name, a, b):
        if a != b:
            diffs.append((name, a, b))

    for pd in fm.get("playerDataArray", []) or []:
        pid = str(pd.get("playerId"))
        mine = final["players"].get(pid, {"xy": None, "state": 0})
        cmp(f"player[{pid}].xy", mine["xy"], pd.get("playerCoordinate"))
        cmp(f"player[{pid}].state", mine["state"], pd.get("playerState"))
        # Box coordinates must agree with the stated base (the inference
        # base_of relies on). Exhausted / setup-prevented players sit in
        # the Reserves box.
        snap_base = (pd.get("playerState") or 0) & BASE_MASK
        implied = box_base(pd.get("playerCoordinate"))
        if implied and snap_base and implied != snap_base and \
                not (implied == 9 and snap_base in (14, 20)):
            diffs.append((f"player[{pid}].box", implied, snap_base))
    cmp("ball.xy", final["ball"]["xy"], fm.get("ballCoordinate"))
    cmp("ball.inPlay", final["ball"]["inPlay"], bool(fm.get("ballInPlay")))
    cmp("ball.moving", final["ball"]["moving"], bool(fm.get("ballMoving")))
    cmp("weather", final["weather"], fm.get("weather"))
    cmp("half", final["half"], game.get("half"))
    cmp("homePlaying", final["homePlaying"], game.get("homePlaying"))
    cmp("turnMode", final["turnMode"], game.get("turnMode"))
    res = game.get("gameResult", {}) or {}
    for side, rk in (("home", "teamResultHome"), ("away", "teamResultAway")):
        cmp(f"score.{side}", final["score"][side], (res.get(rk) or {}).get("score"))
    for side, tk in (("home", "turnDataHome"), ("away", "turnDataAway")):
        td = game.get(tk, {}) or {}
        for f in TURN_CHECKED:
            if f in td:
                cmp(f"turn.{side}.{f}", final["turn"][side][f], td[f])
        snap_ind = {i.get("inducementType"): {"value": i.get("value") or 0,
                                              "uses": i.get("uses") or 0}
                    for i in (td.get("inducementSet") or {}).get("inducementArray", [])}
        cmp(f"inducements.{side}", final["inducements"][side], snap_ind)
    return diffs


def load_raw(spec):
    path = spec if os.path.exists(spec) else \
        os.path.join(CACHE_DIR, f"replay_{spec}.json.gz")
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("specs", nargs="*")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args()
    specs = list(a.specs)
    if a.all:
        specs += sorted(glob.glob(os.path.join(CACHE_DIR, "replay_*.json.gz")))
    if not specs:
        ap.error("give replay ids/paths or --all")
    bad = 0
    fields = {}
    for n, spec in enumerate(specs, 1):
        raw = load_raw(spec)
        _, final = fold(raw)
        diffs = check_final(raw, final)
        if diffs:
            bad += 1
            for name, _, _ in diffs:
                k = name.split("[")[0] + (name.split("]")[1] if "]" in name else "")
                fields[k] = fields.get(k, 0) + 1
            print(f"{os.path.basename(spec)}: {len(diffs)} differences, first "
                  f"{diffs[:3]}", flush=True)
        if n % 50 == 0:
            print(f"[{n}/{len(specs)}] {bad} replays with differences", flush=True)
    print(f"checked {len(specs)} replays: {len(specs) - bad} reproduce the "
          f"end-of-game snapshot exactly, {bad} differ; by field: {fields}")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
