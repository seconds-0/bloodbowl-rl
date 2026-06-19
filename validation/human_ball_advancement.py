#!/usr/bin/env python3
"""Recorded FUMBBL human ball-advancement baseline.

This intentionally parses validation/normalized/*.jsonl directly. It does not
run the engine or any lockstep replay script: the normalized replay trajectory
is the source of truth for the human baseline.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import statistics
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from lockstep_map import Mapper  # noqa: E402


NORM_GLOB = os.path.join(HERE, "normalized", "*.jsonl")
OUT_PATH = os.path.join(ROOT, "docs", "human-ball-advancement.json")
FIELD_MAX_X = 25


@dataclass
class Possession:
    team: int
    pickup_fwd: int
    last_ball: tuple[int, int]
    path_len: int = 0
    start_cmd: int = 0


@dataclass
class GameResult:
    replay: str
    fwd_adv: int
    path_len: int
    possessions: int
    team_turns: int
    td_possessions: list[int] = field(default_factory=list)
    path_violations: int = 0


def read_jsonl(path: str) -> list[dict[str, Any]]:
    records = []
    with open(path, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise ValueError(f"bad json line {line_no}: {exc}") from exc
    if not records:
        raise ValueError("empty normalized replay")
    if records[0].get("type") != "meta":
        raise ValueError("first record is not meta")
    return records


def forward_coord(team: int, x: int) -> int:
    """Team-oriented x progress.

    lockstep_map documents identity FUMBBL/engine coordinates with team 0
    (home) set up on x<=12 and team 1 (away) on x>=13, so home attacks +x and
    away attacks -x.
    """
    if team == 0:
        return x
    if team == 1:
        return FIELD_MAX_X - x
    raise ValueError(f"unknown team: {team}")


def chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac


def receiving_team(meta: dict[str, Any]) -> int:
    rc = meta.get("receiveChoice") or {}
    recv_team_id = str(rc.get("teamId"))
    home_id = str(meta["teamHome"].get("teamId"))
    chooser = 0 if recv_team_id == home_id else 1
    receive = bool(rc.get("receive"))
    receiving = chooser if receive else 1 - chooser
    if meta.get("homeFirstOffense") is not None:
        receiving = 0 if meta["homeFirstOffense"] else 1
    return receiving


def touchback_carrier(mapper: Mapper, ball: tuple[int, int]) -> str | None:
    receiving = 1 - mapper.kicking if mapper.kicking is not None else None
    for pid, pos in mapper.pos.items():
        if pos != ball:
            continue
        team = mapper.pid_team(pid)
        if team == receiving and mapper.base.get(pid, 0) == 0:
            return pid
    return None


def held_team(mapper: Mapper) -> int | None:
    if not mapper.carrier or mapper.ball is None:
        return None
    return mapper.pid_team(mapper.carrier)


def process_game(path: str) -> GameResult:
    records = read_jsonl(path)
    meta = records[0]
    replay = str(meta.get("replayId") or os.path.splitext(os.path.basename(path))[0])
    if not meta.get("finished"):
        raise ValueError("replay is not marked finished")

    mapper = Mapper(records)
    mapper.kicking = 1 - receiving_team(meta)

    active: Possession | None = None
    possessions = 0
    total_fwd = 0
    total_path = 0
    team_turns = 0
    td_possessions: list[int] = []
    path_violations = 0

    def close_possession(cmd: int, reason: str) -> None:
        nonlocal active, total_fwd, total_path, path_violations
        if active is None:
            return
        ball = mapper.ball if reason in ("td", "half_end", "eof") else active.last_ball
        ball = ball or active.last_ball
        fwd_adv = forward_coord(active.team, ball[0]) - active.pickup_fwd
        total_fwd += fwd_adv
        total_path += active.path_len
        if active.path_len < abs(fwd_adv):
            path_violations += 1
        if reason == "td":
            td_possessions.append(fwd_adv)
        active = None

    def reconcile(cmd: int) -> None:
        nonlocal active, possessions
        team = held_team(mapper)
        ball = mapper.ball
        if active is not None:
            if team == active.team and ball is not None:
                if ball != active.last_ball:
                    active.path_len += chebyshev(active.last_ball, ball)
                    active.last_ball = ball
                return
            close_possession(cmd, "loose")
        if team is not None and ball is not None:
            active = Possession(
                team=team,
                pickup_fwd=forward_coord(team, ball[0]),
                last_ball=ball,
                start_cmd=cmd,
            )
            possessions += 1

    for i, record in enumerate(mapper.recs):
        cmd = int(record.get("cmd") or 0)
        typ = record.get("type")

        if typ == "formation":
            mapper.carrier = None
            for pid, xy in (record.get("players") or {}).items():
                x, y = xy
                if 0 <= x <= FIELD_MAX_X and 0 <= y <= 14:
                    mapper.pos[str(pid)] = (x, y)
                    mapper.base[str(pid)] = 0
            continue

        if (
            typ == "ball"
            and record.get("mode") == "touchback"
            and record.get("at")
        ):
            at = tuple(record["at"])
            if 0 <= at[0] <= FIELD_MAX_X and 0 <= at[1] <= 14:
                mapper.ball = at
                mapper.carrier = touchback_carrier(mapper, at)

        if not (record.get("mode") == "setup" and typ in ("move", "state")):
            mapper.track(i, record)

        report = record.get("report")
        if report == "turnEnd" and int(record.get("half") or 0) >= 1:
            team_turns += 1

        if report == "pickUpRoll":
            if record.get("successful"):
                mapper.carrier = str(record.get("playerId"))
        elif report == "catchRoll":
            if record.get("successful"):
                mapper.carrier = str(record.get("playerId"))
            else:
                if mapper.carrier == str(record.get("playerId")):
                    mapper.carrier = None
        elif report == "passRoll":
            mapper.carrier = None
        elif report == "handOver":
            mapper.carrier = None
        elif report == "injury":
            for key in ("defenderId", "playerId"):
                pid = record.get(key)
                if pid and mapper.carrier == str(pid):
                    mapper.carrier = None
        elif report == "turnEnd":
            td = record.get("playerIdTouchdown")
            if td:
                close_possession(cmd, "td")
                team = mapper.pid_team(td)
                if team is not None:
                    mapper.kicking = team
                mapper.carrier = None
            elif typ == "event" and record.get("mode") == "setup":
                close_possession(cmd, "half_end")
                mapper.carrier = None

        reconcile(cmd)

    close_possession(int(mapper.recs[-1].get("cmd") or 0), "eof")

    return GameResult(
        replay=replay,
        fwd_adv=total_fwd,
        path_len=total_path,
        possessions=possessions,
        team_turns=team_turns,
        td_possessions=td_possessions,
        path_violations=path_violations,
    )


def round_or_none(value: float | None, ndigits: int = 4) -> float | None:
    if value is None:
        return None
    return round(value, ndigits)


def aggregate(results: list[GameResult], failures: list[dict[str, str]], input_games: int) -> dict[str, Any]:
    games = len(results)
    total_fwd = sum(g.fwd_adv for g in results)
    total_path = sum(g.path_len for g in results)
    total_possessions = sum(g.possessions for g in results)
    total_team_turns = sum(g.team_turns for g in results)
    sorted_fwd = sorted(float(g.fwd_adv) for g in results)
    all_td = [v for g in results for v in g.td_possessions]
    large_td = [v for v in all_td if v >= 10]

    return {
        "_method": (
            "parsed RECORDED FUMBBL ball trajectory from validation/normalized "
            "via lockstep_map parsing; full finished games; mirrors env "
            "ball_fwd_adv/ball_path_len; per-game + per-team-turn"
        ),
        "_caveat": (
            "human = full recorded games; the live agent dashboard number is "
            "per-EPISODE from CURRICULUM starts, so a fair agent comparison "
            "needs a full-game agent eval (demo_reset_pct 0) in the same units."
        ),
        "_source": "validation/normalized/*.jsonl",
        "_generated_utc": datetime.now(timezone.utc).isoformat(),
        "_input_games": input_games,
        "games_processed": games,
        "games_failed": len(failures),
        "total_possessions": total_possessions,
        "total_team_turns": total_team_turns,
        "team_turns_per_game": round_or_none(total_team_turns / games if games else None, 4),
        "possessions_per_game": round_or_none(total_possessions / games if games else None, 4),
        "ball_fwd_adv_per_game": round_or_none(total_fwd / games if games else None, 4),
        "ball_path_len_per_game": round_or_none(total_path / games if games else None, 4),
        "ball_fwd_adv_per_team_turn": round_or_none(total_fwd / total_team_turns if total_team_turns else None, 6),
        "ball_path_len_per_team_turn": round_or_none(total_path / total_team_turns if total_team_turns else None, 6),
        "ball_fwd_adv_per_game_distribution": {
            "p25": round_or_none(percentile(sorted_fwd, 0.25), 4),
            "median": round_or_none(statistics.median(sorted_fwd) if sorted_fwd else None, 4),
            "p75": round_or_none(percentile(sorted_fwd, 0.75), 4),
        },
        "_fwd_adv_per_possession_mean": round_or_none(total_fwd / total_possessions if total_possessions else None, 6),
        "_td_orientation_sanity": {
            "td_possessions": len(all_td),
            "min_td_fwd_adv": min(all_td) if all_td else None,
            "median_td_fwd_adv": statistics.median(all_td) if all_td else None,
            "td_nonnegative": all(v >= 0 for v in all_td),
            "td_large_positive_count_ge_10": len(large_td),
            "td_large_positive_examples": large_td[:12],
            "sample_td_fwd_adv": all_td[:12],
        },
        "_sanity_checks": {
            "team_turns_per_game_in_30_40_band": bool(games and 30.0 <= total_team_turns / games <= 40.0),
            "fwd_adv_positive_on_average": bool(games and total_fwd / games > 0.0),
            "path_len_ge_abs_fwd_adv_violations": sum(g.path_violations for g in results),
            "td_orientation_large_positive_examples_present": len(large_td) >= 3,
        },
        "_failed_replays_sample": failures[:20],
        "_authoritative_note": (
            "tools/bb_ballstats.c is an engine re-simulation helper and is "
            "conformance-limited; this recorded-trajectory parser is the "
            "authoritative human baseline source."
        ),
    }


def print_summary(doc: dict[str, Any]) -> None:
    print("Human recorded ball advancement baseline")
    print(f"  games processed/failed: {doc['games_processed']}/{doc['games_failed']}")
    print(f"  possessions: {doc['total_possessions']}")
    print(f"  team turns: {doc['total_team_turns']} ({doc['team_turns_per_game']}/game)")
    print(f"  ball_fwd_adv_per_game: {doc['ball_fwd_adv_per_game']}")
    print(f"  ball_path_len_per_game: {doc['ball_path_len_per_game']}")
    print(f"  ball_fwd_adv_per_team_turn: {doc['ball_fwd_adv_per_team_turn']}")
    print(f"  ball_path_len_per_team_turn: {doc['ball_path_len_per_team_turn']}")
    dist = doc["ball_fwd_adv_per_game_distribution"]
    print(f"  fwd_adv/game p25/median/p75: {dist['p25']}/{dist['median']}/{dist['p75']}")
    td = doc["_td_orientation_sanity"]
    print(
        "  TD sanity: "
        f"n={td['td_possessions']} min={td['min_td_fwd_adv']} "
        f"median={td['median_td_fwd_adv']} "
        f"large_examples={td['td_large_positive_examples'][:6]}"
    )
    sanity = doc["_sanity_checks"]
    print(
        "  checks: "
        f"turns_30_40={sanity['team_turns_per_game_in_30_40_band']} "
        f"avg_fwd_positive={sanity['fwd_adv_positive_on_average']} "
        f"path_violations={sanity['path_len_ge_abs_fwd_adv_violations']} "
        f"td_large_examples={sanity['td_orientation_large_positive_examples_present']}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input-glob", default=NORM_GLOB)
    ap.add_argument("--output", default=OUT_PATH)
    ap.add_argument("--limit", type=int, default=0, help="process first N files")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    paths = sorted(glob.glob(args.input_glob))
    if args.limit:
        paths = paths[: args.limit]
    failures: list[dict[str, str]] = []
    results: list[GameResult] = []

    for path in paths:
        replay = os.path.splitext(os.path.basename(path))[0]
        try:
            results.append(process_game(path))
        except Exception as exc:  # noqa: BLE001 - malformed games are counted.
            failures.append({"replay": replay, "reason": str(exc)[:200]})

    doc = aggregate(results, failures, len(paths))
    if not args.no_write:
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(doc, f, indent=2)
            f.write("\n")
    print_summary(doc)
    return 0 if results else 1


if __name__ == "__main__":
    raise SystemExit(main())
