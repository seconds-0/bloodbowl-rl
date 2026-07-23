#!/usr/bin/env python3
"""per_team_baseline.py — per-roster human baselines from the FUMBBL cache.

Aggregate baselines (D61) hide huge roster variance: Wood Elf passing and
Dwarf passing are different sports (Alex, 2026-06-10). This measures, PER
ROSTER, per-game rates for: passes, hand-offs, tds, blocks, dodges, gfis,
pickups — attributing each event to the side that performed it.

Attribution sources inside a replay (.json.gz, FFB command stream):
  - pass/handoff: turnDataSetPassUsed / turnDataSetHandOverUsed model changes
    with value true, keyed "home"/"away".
  - tds: final score per side (teamResultSetScore, or last gameSetScore*).
  - blocks/dodges/gfis/pickups: report types (blockRoll/dodgeRoll/goForItRoll/
    pickUpRoll) attributed via the acting player's team, using the playerId ->
    team map from the game snapshot (teamHome/teamAway player arrays).
Roster names come from the cached match_<id>.json (team1/team2.roster.name),
joined via manifest.json (matchId -> replayId).

Usage (on the cache box, japan):
  python3 tools/per_team_baseline.py [--sample N] [--out docs/per-team-baseline.json]
Runs nice'd; single-threaded; ~0.3s/replay.
"""
import argparse
import gzip
import json
import os
import sys
from collections import defaultdict

CACHE = "validation/replay_cache"

ROLL_KEYS = {  # reportId -> metric name (blockRoll handled separately via choosingTeamId)
    "dodgeRoll": "dodges",
    "goForItRoll": "gfis",
    "pickUpRoll": "pickups",
}

def load_manifest():
    with open(os.path.join(CACHE, "manifest.json")) as f:
        man = json.load(f)
    out = []
    for m in man.values():
        rid, mid = m.get("replayId"), m.get("matchId")
        if rid and mid:
            out.append((rid, mid))
    return out

def match_rosters(mid):
    p = os.path.join(CACHE, f"match_{mid}.json")
    if not os.path.exists(p):
        return None
    with open(p) as f:
        d = json.load(f)
    try:
        return (d["team1"]["roster"]["name"], d["team2"]["roster"]["name"])
    except (KeyError, TypeError):
        return None

def replay_stats(rid):
    """Return per-side dict: {'home': {...}, 'away': {...}} or None."""
    p = os.path.join(CACHE, f"replay_{rid}.json.gz")
    if not os.path.exists(p):
        p2 = os.path.join(CACHE, f"replay_{rid}.json")
        if not os.path.exists(p2):
            return None
        raw = open(p2, "rb").read()
    else:
        raw = gzip.open(p, "rb").read()
    try:
        d = json.loads(raw)
    except Exception:
        return None
    game = d.get("game", {})
    # playerId -> side map from the end-state snapshot
    side_of = {}
    team_side = {}
    for side, key in (("home", "teamHome"), ("away", "teamAway")):
        t = game.get(key, {}) or {}
        tid = t.get("teamId")
        if tid is not None:
            team_side[str(tid)] = side
        for pl in t.get("playerArray", []) or []:
            pid = pl.get("playerId")
            if pid is not None:
                side_of[str(pid)] = side
    S = {s: defaultdict(int) for s in ("home", "away")}
    cmds = (d.get("gameLog", {}) or {}).get("commandArray", []) or []
    for c in cmds:
        for mc in (c.get("modelChangeList", {}) or {}).get("modelChangeArray", []) or []:
            mid_ = mc.get("modelChangeId", "")
            if mid_ in ("turnDataSetPassUsed", "turnDataSetHandOverUsed") and mc.get("modelChangeValue") is True:
                k = mc.get("modelChangeKey")
                if k in S:
                    S[k]["passes" if mid_ == "turnDataSetPassUsed" else "handoffs"] += 1
            elif mid_ == "teamResultSetScore":
                k = mc.get("modelChangeKey")
                if k in S:
                    S[k]["tds"] = max(S[k]["tds"], int(mc.get("modelChangeValue") or 0))
        # roll reports, attributed by acting player
        rl = (c.get("reportList", {}) or {}).get("reports", []) or []
        for r in rl:
            rid_ = r.get("reportId", "")
            if rid_ == "blockRoll":
                side = team_side.get(str(r.get("choosingTeamId")))
                if side:
                    S[side]["blocks"] += 1
            elif rid_ in ROLL_KEYS:
                pid = r.get("playerId") or r.get("actingPlayerId")
                side = side_of.get(str(pid))
                if side:
                    S[side][ROLL_KEYS[rid_]] += 1
    return S

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=0, help="0 = full corpus")
    ap.add_argument("--out", default="docs/per-team-baseline.json")
    a = ap.parse_args()
    pairs = load_manifest()
    if a.sample:
        pairs = pairs[: a.sample]
    agg = defaultdict(lambda: defaultdict(float))  # roster -> metric -> sum
    games = defaultdict(int)
    done = 0
    for rid, mid in pairs:
        rosters = match_rosters(mid)
        if not rosters:
            continue
        st = replay_stats(rid)
        if not st:
            continue
        for side, roster in zip(("home", "away"), rosters):
            games[roster] += 1
            for k, v in st[side].items():
                agg[roster][k] += v
        done += 1
        if done % 200 == 0:
            print(f"  {done} replays processed", file=sys.stderr)
    out = {"_games_processed": done, "_note": "per-roster per-game rates; side-attributed", "rosters": {}}
    for roster, n in sorted(games.items(), key=lambda kv: -kv[1]):
        if n < 20:
            continue  # too few games for a stable rate
        row = {"games": n}
        for k in ("passes", "handoffs", "tds", "blocks", "dodges", "gfis", "pickups"):
            row[k + "_per_game"] = round(agg[roster][k] / n, 3)
        out["rosters"][roster] = row
    with open(a.out, "w") as f:
        json.dump(out, f, indent=2)
    print(f"wrote {a.out}: {len(out['rosters'])} rosters, {done} games")
    # console summary: extremes on passes
    rs = out["rosters"]
    by_pass = sorted(rs.items(), key=lambda kv: -kv[1]["passes_per_game"])
    print("\ntop passers:        " + ", ".join(f"{k} {v['passes_per_game']}" for k, v in by_pass[:5]))
    print("bottom passers:     " + ", ".join(f"{k} {v['passes_per_game']}" for k, v in by_pass[-5:]))

if __name__ == "__main__":
    main()
