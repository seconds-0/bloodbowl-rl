#!/usr/bin/env python3
"""human_possession.py — measure human possession_rate from the FUMBBL cache,
matching the engine's metric: fraction of team-turns that END with the active
team holding the ball (a player of that team on the ball's square, ball not
moving). Walks each replay's modelChange stream maintaining ball + player
coords + active team; scores at each gameSetHomePlaying flip (= turn end).
Run on japan: python3 tools/human_possession.py [--sample N]
"""
import argparse, glob, gzip, json, os, sys
from collections import defaultdict

CACHE = "validation/replay_cache"

def side_map(game):
    m = {}
    for side, key in (("home", "teamHome"), ("away", "teamAway")):
        for pl in (game.get(key, {}) or {}).get("playerArray", []) or []:
            pid = pl.get("playerId")
            if pid is not None:
                m[str(pid)] = side
    return m

def replay_possession(path):
    raw = gzip.open(path, "rb").read() if path.endswith(".gz") else open(path, "rb").read()
    try: d = json.loads(raw)
    except Exception: return None
    side = side_map(d.get("game", {}))
    if not side: return None
    pos = {}            # pid -> (x,y)
    bx = by = None
    ball_moving = False
    playing = None      # "home"/"away" currently acting
    score = {"home": 0, "away": 0}
    scored_this_turn = None   # side that scored since last flip
    turn_ends = held_ends = 0
    for c in (d.get("gameLog", {}) or {}).get("commandArray", []) or []:
        for mc in (c.get("modelChangeList", {}) or {}).get("modelChangeArray", []) or []:
            mid = mc.get("modelChangeId", ""); k = mc.get("modelChangeKey"); v = mc.get("modelChangeValue")
            if mid == "fieldModelSetPlayerCoordinate" and k is not None and isinstance(v, list) and len(v) == 2:
                pos[str(k)] = (v[0], v[1])
            elif mid == "fieldModelSetBallCoordinate" and isinstance(v, list) and len(v) == 2:
                bx, by = v[0], v[1]
            elif mid == "fieldModelSetBallMoving":
                ball_moving = bool(v)
            elif mid == "teamResultSetScore":
                if k in score and isinstance(v, int) and v > score[k]:
                    score[k] = v
                    scored_this_turn = k
            elif mid == "gameSetHomePlaying":
                # the team that WAS playing just ended its turn
                if playing is not None and bx is not None:
                    turn_ends += 1
                    if scored_this_turn == playing:
                        held_ends += 1          # D90: carried it in = held
                    elif not ball_moving:
                        holder = None
                        for pid, (px, py) in pos.items():
                            if px == bx and py == by:
                                holder = side.get(pid); break
                        if holder == playing:
                            held_ends += 1
                scored_this_turn = None
                playing = "home" if v is True else "away" if v is False else playing
    return (turn_ends, held_ends)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--sample", type=int, default=0)
    a = ap.parse_args()
    files = sorted(glob.glob(os.path.join(CACHE, "replay_*.json.gz")))
    if a.sample: files = files[:a.sample]
    T = H = 0; games = 0
    for i, f in enumerate(files):
        r = replay_possession(f)
        if not r: continue
        te, he = r
        if te < 4: continue   # skip stunted/conceded
        T += te; H += he; games += 1
        if games % 300 == 0: print(f"  {games} games", file=sys.stderr)
    print(f"games={games}  team_turns={T}  held_ends={H}")
    print(f"human possession_rate = {H/T:.3f}" if T else "no data")

if __name__ == "__main__":
    main()
