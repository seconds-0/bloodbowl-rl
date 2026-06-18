#!/usr/bin/env python3
"""Replay/check the protocol-v1 teamstats accumulator.

The recorded fixture predates the teamstats field, so this script feeds each
delta through the same accumulator used by game.py and checks monotonicity and
shape invariants. A small synthetic sequence exercises rows the old fixture
does not contain.
"""
import argparse
import json
from pathlib import Path

from game import TEAMSTAT_SIDES, TeamStatsAccumulator, _side_from_active


SCALAR_KEYS = ("blocks", "turnovers", "pass", "handoff", "foul")
PAIR_KEYS = ("dodge", "gfi", "pickup")


def _assert_shape(stats):
    for side in TEAMSTAT_SIDES:
        team = stats[side]
        assert sum(team["tier"]) == team["blocks"], (side, team)
        for key in PAIR_KEYS:
            succ, att = team[key]
            assert 0 <= succ <= att, (side, key, team[key])


def _assert_monotonic(prev, cur):
    for side in TEAMSTAT_SIDES:
        a, b = prev[side], cur[side]
        for key in SCALAR_KEYS:
            assert b[key] >= a[key], (side, key, a[key], b[key])
        for key in PAIR_KEYS:
            assert b[key][0] >= a[key][0], (side, key, a[key], b[key])
            assert b[key][1] >= a[key][1], (side, key, a[key], b[key])
        for i in range(3):
            assert b["tier"][i] >= a["tier"][i], (side, "tier", a["tier"], b["tier"])
    _assert_shape(cur)


def replay_fixture(path):
    acc = TeamStatsAccumulator()
    prev = acc.snapshot()
    changed = 0
    deltas = 0
    saw_match = False

    with open(path) as fh:
        for line in fh:
            msg = json.loads(line)
            if msg.get("t") == "match_start":
                acc = TeamStatsAccumulator()
                prev = acc.snapshot()
                saw_match = True
            elif msg.get("t") == "delta":
                deltas += 1
                side = _side_from_active(msg.get("active_team"))
                if acc.update_from_delta(msg, side):
                    changed += 1
                    cur = acc.snapshot()
                    _assert_monotonic(prev, cur)
                    prev = cur

    stats = acc.snapshot()
    _assert_shape(stats)
    assert saw_match, "fixture did not contain match_start"
    assert deltas > 0, "fixture did not contain deltas"
    assert stats["home"]["blocks"] + stats["away"]["blocks"] > 0, stats
    return {"fixture": str(path), "deltas": deltas, "changed": changed, "teamstats": stats}


def synthetic_check():
    acc = TeamStatsAccumulator()
    events = [
        {"action": {"type": "BLOCK", "actor": 3}, "ev": {"p_def_down": 0.72, "p_att_down": 0.04}},
        {"action": {"type": "BLOCK", "actor": 19}, "ev": {"p_def_down": 0.18, "p_att_down": 0.36}},
        {"action": {"type": "MOVE", "actor": 4}, "dice": {"kind": "d6", "label": "Dodge", "roll": 5, "target": 3, "ok": True},
         "feed": [{"kind": "dodge", "side": "home", "text": "dodges free"}]},
        {"action": {"type": "MOVE", "actor": 5}, "dice": {"kind": "d6", "label": "GFI", "roll": 1, "target": 2, "ok": False},
         "feed": [{"kind": "gfi", "side": "home", "text": "stumbles going for it"},
                  {"kind": "turnover", "side": "home", "text": "Turnover!"}]},
        {"action": {"type": "MOVE", "actor": 20},
         "feed": [{"kind": "pickup", "side": "away", "text": "reaches for ball"},
                  {"kind": "pickup", "side": "away", "text": "PICKS UP!"}]},
        {"action": {"type": "PASS", "actor": 20}, "feed": [{"kind": "pass", "side": "away", "text": "passes"}]},
        {"action": {"type": "HANDOFF", "actor": 20}, "feed": [{"kind": "handoff", "side": "away", "text": "hands off"}]},
        {"action": {"type": "FOUL", "actor": 20}, "feed": [{"kind": "foul", "side": "away", "text": "Foul!"}]},
    ]
    prev = acc.snapshot()
    for msg in events:
        acc.update_from_delta(msg, _side_from_active(msg.get("active_team")))
        cur = acc.snapshot()
        _assert_monotonic(prev, cur)
        prev = cur

    stats = acc.snapshot()
    assert stats["home"]["blocks"] == 1 and stats["home"]["tier"] == [1, 0, 0], stats
    assert stats["away"]["blocks"] == 1 and stats["away"]["tier"] == [0, 0, 1], stats
    assert stats["home"]["dodge"] == [1, 1], stats
    assert stats["home"]["gfi"] == [0, 1], stats
    assert stats["away"]["pickup"] == [1, 1], stats
    assert stats["home"]["turnovers"] == 1, stats
    assert stats["away"]["pass"] == 1, stats
    assert stats["away"]["handoff"] == 1, stats
    assert stats["away"]["foul"] == 1, stats
    return {"synthetic_events": len(events), "teamstats": stats}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", default=Path(__file__).with_name("fixture_match.jsonl"))
    args = ap.parse_args()
    result = {
        "fixture": replay_fixture(Path(args.fixture)),
        "synthetic": synthetic_check(),
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
