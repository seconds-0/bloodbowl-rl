#!/usr/bin/env python3
"""Aggregate human ball-advancement stats from lockstep replay re-sims."""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import statistics
import subprocess
import sys
from datetime import datetime, timezone


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RUNNER = os.path.join(ROOT, "build", "bb_ballstats")
DEFAULT_INPUT = os.path.join(ROOT, "validation", "lockstep")
DEFAULT_OUTPUT = os.path.join(ROOT, "docs", "human-ball-advancement.json")


METHOD = (
    "Re-sim of validation/lockstep human replays through the engine; ball "
    "tracking mirrors the env ball_fwd_adv/ball_path_len helpers "
    "(carrier-position ball xy, team-oriented forward coord, Chebyshev path, "
    "same possession-transition rules); aggregated per-game and "
    "per-team-turn, not per-possession."
)

CAVEAT = (
    "human = FULL-GAME (kickoff->end); the live agent's dashboard number is "
    "per-EPISODE from CURRICULUM starts, so a fair agent comparison needs a "
    "full-game agent eval (demo_reset_pct 0) reporting the SAME "
    "per-game/per-team-turn units."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runner", default=DEFAULT_RUNNER)
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--keep-going",
        action="store_true",
        default=True,
        help="Skip failed replays and aggregate successes (default).",
    )
    return parser.parse_args()


def q(sorted_values: list[float], p: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * p
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def round6(x: float) -> float:
    return round(float(x), 6)


def run_one(runner: str, path: str) -> dict:
    proc = subprocess.run(
        [runner, path],
        cwd=ROOT,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if proc.returncode != 0:
        return {
            "replay": os.path.splitext(os.path.basename(path))[0],
            "path": path,
            "success": False,
            "fail_class": "runner",
            "fail_reason": proc.stderr.strip() or f"exit {proc.returncode}",
        }
    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return {
            "replay": os.path.splitext(os.path.basename(path))[0],
            "path": path,
            "success": False,
            "fail_class": "runner",
            "fail_reason": "no JSON output",
        }
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        return {
            "replay": os.path.splitext(os.path.basename(path))[0],
            "path": path,
            "success": False,
            "fail_class": "runner",
            "fail_reason": f"invalid JSON output: {exc}",
        }


def main() -> int:
    args = parse_args()
    paths = sorted(glob.glob(os.path.join(args.input, "*.jsonl")))
    if not paths:
        print(f"no replay files found under {args.input}", file=sys.stderr)
        return 2
    if not os.path.exists(args.runner):
        print(f"runner not found: {args.runner}", file=sys.stderr)
        return 2

    rows = [run_one(args.runner, path) for path in paths]
    ok = [row for row in rows if row.get("success")]
    failed = [row for row in rows if not row.get("success")]
    if not ok:
        fail_classes = collections.Counter(
            row.get("fail_class", "?") for row in failed
        )
        result = {
            "_status": "blocked_no_complete_replayed_games",
            "_reason": (
                "All local validation/lockstep replay scripts diverged before "
                "engine MATCH_OVER, so no full-game human ball-advancement "
                "baseline can be computed without either improving lockstep "
                "conformance or changing the methodology."
            ),
            "_method": METHOD,
            "_caveat": CAVEAT,
            "_source": "validation/lockstep/*.jsonl",
            "_generated_utc": datetime.now(timezone.utc).isoformat(),
            "_input_games": len(paths),
            "games_processed": 0,
            "games_failed": len(failed),
            "total_possessions": 0,
            "total_team_turns": 0,
            "team_turns_per_game": None,
            "possessions_per_game": None,
            "ball_fwd_adv_per_game": None,
            "ball_path_len_per_game": None,
            "ball_fwd_adv_per_team_turn": None,
            "ball_path_len_per_team_turn": None,
            "ball_fwd_adv_per_game_distribution": {
                "p25": None,
                "median": None,
                "p75": None,
            },
            "_fwd_adv_per_possession_mean": None,
            "_failure_class_counts": dict(sorted(fail_classes.items())),
            "_failed_replays_sample": [
                {
                    "replay": row.get("replay", "?"),
                    "fail_class": row.get("fail_class", "?"),
                    "fail_reason": row.get("fail_reason", "?"),
                }
                for row in failed[:10]
            ],
        }
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2, sort_keys=False)
            f.write("\n")
        print(
            "processed=0 failed={failed_n}; no complete engine re-simulated "
            "games reached MATCH_OVER, so no baseline numbers were written".format(
                failed_n=len(failed)
            )
        )
        return 1

    games = len(ok)
    total_fwd = sum(float(row["ball_fwd_adv"]) for row in ok)
    total_path = sum(float(row["ball_path_len"]) for row in ok)
    total_possessions = sum(int(row["possessions"]) for row in ok)
    total_team_turns = sum(int(row["team_turns"]) for row in ok)
    fwd_per_game_values = sorted(float(row["ball_fwd_adv"]) for row in ok)
    team_turns_per_game = total_team_turns / games

    result = {
        "_method": METHOD,
        "_caveat": CAVEAT,
        "_source": "validation/lockstep/*.jsonl",
        "_generated_utc": datetime.now(timezone.utc).isoformat(),
        "_input_games": len(paths),
        "games_processed": games,
        "games_failed": len(failed),
        "total_possessions": total_possessions,
        "total_team_turns": total_team_turns,
        "team_turns_per_game": round6(team_turns_per_game),
        "possessions_per_game": round6(total_possessions / games),
        "ball_fwd_adv_per_game": round6(total_fwd / games),
        "ball_path_len_per_game": round6(total_path / games),
        "ball_fwd_adv_per_team_turn": round6(total_fwd / total_team_turns)
        if total_team_turns
        else 0.0,
        "ball_path_len_per_team_turn": round6(total_path / total_team_turns)
        if total_team_turns
        else 0.0,
        "ball_fwd_adv_per_game_distribution": {
            "p25": round6(q(fwd_per_game_values, 0.25)),
            "median": round6(statistics.median(fwd_per_game_values)),
            "p75": round6(q(fwd_per_game_values, 0.75)),
        },
        "_fwd_adv_per_possession_mean": round6(total_fwd / total_possessions)
        if total_possessions
        else 0.0,
        "_failed_replays_sample": [
            {
                "replay": row.get("replay", "?"),
                "fail_class": row.get("fail_class", "?"),
                "fail_reason": row.get("fail_reason", "?"),
            }
            for row in failed[:10]
        ],
    }

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, sort_keys=False)
        f.write("\n")

    print(
        "processed={games} failed={failed_n} team_turns={turns} "
        "team_turns/game={ttg:.3f} possessions={poss} "
        "fwd/game={fpg:.6f} path/game={ppg:.6f} "
        "fwd/team_turn={fpt:.6f} path/team_turn={ppt:.6f}".format(
            games=games,
            failed_n=len(failed),
            turns=total_team_turns,
            ttg=team_turns_per_game,
            poss=total_possessions,
            fpg=result["ball_fwd_adv_per_game"],
            ppg=result["ball_path_len_per_game"],
            fpt=result["ball_fwd_adv_per_team_turn"],
            ppt=result["ball_path_len_per_team_turn"],
        )
    )
    dist = result["ball_fwd_adv_per_game_distribution"]
    print(
        "fwd_adv/game distribution: "
        f"p25={dist['p25']:.6f} median={dist['median']:.6f} p75={dist['p75']:.6f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
