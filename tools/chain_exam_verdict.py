#!/usr/bin/env python3
"""Register the verdict of one chain stage's scripted-bot exam.

tools/chain_stage.sh runs three cells per exam seed (contact AWAY, contact
HOME, offense AWAY) and then calls this. It reads the six cell logs with the
same two functions the as-run readout prints from
(game_stats.weighted_dashboard, then contact_bot_stats.bot_perspective), so
the numbers here are the numbers in each cell's .out file, unrounded.

Files written to --output-dir, each by temp file plus rename:

  EXAM_VERDICT.json       always, and last. Its presence makes the verdict
                          final: chain_stage.sh never runs another exam.
  EXAM_VERDICT_PASS.json  only when the rule passes, and first. This is the
                          campaign supervisor's success artifact.

Fail closed. A missing log, a manifest that does not match its cell, mixed
checkpoints, too few games, a non-finite number or an existing verdict all
exit 2 and write nothing. The stage then retries the exam in a new attempt
directory, up to the supervisor's attempt cap.

The env-layer restriction no_early_end_turn (docs/no-early-end-turn-2026-10-05.md)
is read from every cell's eval manifest. A checkpoint trained under it must be
examined under it, so the cells must all agree with --no-early-end-turn (off
when the option is not given); a mismatch is no verdict. Each cell's own panel
must agree as well (game_stats.no_early_end_turn_evidence_failure):
end_turn_removed above zero under the rule, zero or absent without it. Under the rule a cell is also refused
unless its panel carries truncated_episodes and it is exactly zero: a game cut
by the env's decision cap is not an error episode, and the exam must not read
one (game_stats.no_early_end_turn_truncation_failure). When the exam ran under
the rule, the verdict and each cell record no_early_end_turn: 1, and each cell
its end_turn_removed and its truncated_episodes.

Rules:

  none         passes whenever every cell is valid. For pre-registered paired
               arms that never stop automatically.
  drift-guard  FAILS only when all three hold for --guard-cell: seed 42
               champion touchdowns per game below --guard-floor-s42, AND seed
               43 below --guard-floor-s43, AND the two-seed mean below
               --guard-floor-mean. Comparisons are strict and use the
               unrounded values. The floors are the caller's registered
               numbers; this tool has no defaults for them.

Exit status: 0 the rule passed, 3 the rule failed (verdict written), 2 no
verdict could be produced.
"""

from __future__ import annotations

import argparse
import datetime
import json
import math
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from contact_bot_stats import bot_perspective  # noqa: E402
from game_stats import (  # noqa: E402
    no_early_end_turn_evidence_failure, no_early_end_turn_truncation_failure,
    weighted_dashboard)

SCHEMA_VERSION = 1
MANIFEST_PREFIX = "BB_EVAL_MANIFEST "
# name, bot_type, bot_team: the three cells rig_exam.sh ran, in its order.
CELLS = (
    ("contact_away", 0, 1),
    ("contact_home", 0, 0),
    ("offense_away", 1, 1),
)
GUARD_SEEDS = (42, 43)
VERDICT_NAME = "EXAM_VERDICT.json"
PASS_NAME = "EXAM_VERDICT_PASS.json"


class VerdictError(Exception):
    """The exam evidence cannot support any verdict."""


def read_manifest(log: Path) -> dict:
    with log.open(encoding="utf-8", errors="replace") as handle:
        first = handle.readline()
    if not first.startswith(MANIFEST_PREFIX):
        raise VerdictError(f"{log}: first line is not a {MANIFEST_PREFIX.strip()}")
    try:
        manifest = json.loads(first[len(MANIFEST_PREFIX):])
    except json.JSONDecodeError as exc:
        raise VerdictError(f"{log}: unreadable eval manifest: {exc}") from exc
    if not isinstance(manifest, dict):
        raise VerdictError(f"{log}: eval manifest is not an object")
    return manifest


def manifest_threads(manifest: dict) -> int | None:
    command = manifest.get("command")
    if not isinstance(command, list):
        return None
    for index, word in enumerate(command[:-1]):
        if word == "--vec.num-threads":
            try:
                return int(command[index + 1])
            except (TypeError, ValueError):
                return None
    return None


def manifest_no_early_end_turn(log: Path, manifest: dict) -> bool:
    """Whether this cell ran under the rule, from its key AND its command."""
    recorded = manifest.get("no_early_end_turn", 0)
    if recorded not in (0, 1) or isinstance(recorded, bool):
        raise VerdictError(
            f"{log}: manifest no_early_end_turn={recorded!r} is not 0 or 1")
    command = manifest.get("command")
    words = command if isinstance(command, list) else []
    flagged = [words[index + 1] if index + 1 < len(words) else None
               for index, word in enumerate(words)
               if word == "--env.no-early-end-turn"]
    in_command = flagged == ["1"]
    if (flagged and not in_command) or in_command != bool(recorded):
        raise VerdictError(
            f"{log}: manifest no_early_end_turn={recorded!r} disagrees with "
            f"its command (--env.no-early-end-turn {flagged})")
    return bool(recorded)


def read_cell(exam_dir: Path, seed: int, name: str, bot_type: int,
              bot_team: int, min_games: int) -> dict:
    log = exam_dir / f"s{seed}" / f"{name}.log"
    if not log.is_file():
        raise VerdictError(f"missing cell log: {log}")
    manifest = read_manifest(log)
    for key, want in (("seed", seed), ("bot_type", bot_type),
                      ("bot_team", bot_team)):
        if manifest.get(key) != want:
            raise VerdictError(
                f"{log}: manifest {key}={manifest.get(key)!r}, this cell "
                f"needs {want!r}")
    checkpoint_sha = manifest.get("checkpoint_sha256")
    if not isinstance(checkpoint_sha, str) or len(checkpoint_sha) != 64:
        raise VerdictError(f"{log}: manifest has no checkpoint_sha256")
    try:
        values = weighted_dashboard(str(log))
    except ValueError as exc:
        raise VerdictError(f"{log}: {exc}") from exc
    if not values:
        raise VerdictError(f"{log}: no completed-episode eval windows")
    try:
        view = bot_perspective(values, bot_team)
    except KeyError as exc:
        raise VerdictError(f"{log}: dashboard is missing {exc}") from exc
    games = values.get("n", 0.0)
    numbers = {
        "games": games,
        "champion_tds": view["champion_tds"],
        "bot_tds": view["bot_tds"],
        "champion_score": view["champion_score"],
        "bot_score": view["bot_score"],
    }
    for key, value in numbers.items():
        if not isinstance(value, (int, float)) or not math.isfinite(value):
            raise VerdictError(f"{log}: {key} is not a finite number")
    if games < min_games:
        raise VerdictError(
            f"{log}: {games:g} completed games, fewer than {min_games}")
    cell = {
        "seed": seed,
        "cell": name,
        "bot_type": bot_type,
        "bot_team": bot_team,
        "champion_team": view["champion_team"],
        "log": str(log),
        "checkpoint": manifest.get("checkpoint"),
        "checkpoint_sha256": checkpoint_sha,
        "num_threads": manifest_threads(manifest),
        **numbers,
    }
    rule_on = manifest_no_early_end_turn(log, manifest)
    # The manifest says what the cell was asked to run; the env's own panel
    # says what it ran.
    reason = no_early_end_turn_evidence_failure(values, rule_on)
    if reason:
        raise VerdictError(f"{log}: {reason}")
    # Under the rule a cell with a game cut by the decision cap is no evidence
    # (D416 amendment); a cell without the rule is not judged on this.
    reason = no_early_end_turn_truncation_failure(values, rule_on)
    if reason:
        raise VerdictError(f"{log}: {reason}")
    if rule_on:
        cell["no_early_end_turn"] = 1
        cell["end_turn_removed"] = values["end_turn_removed"]
        cell["truncated_episodes"] = values["truncated_episodes"]
    return cell


def drift_guard(cells: list[dict], guard_cell: str, floors: dict) -> dict:
    by_seed = {
        cell["seed"]: cell["champion_tds"]
        for cell in cells if cell["cell"] == guard_cell
    }
    for seed in GUARD_SEEDS:
        if seed not in by_seed:
            raise VerdictError(
                f"drift-guard needs {guard_cell} at seed {seed}; the exam "
                f"seeds must include {GUARD_SEEDS[0]} and {GUARD_SEEDS[1]}")
    s42, s43 = by_seed[42], by_seed[43]
    mean = (s42 + s43) / 2.0
    clauses = {
        "s42_below_floor": s42 < floors["s42"],
        "s43_below_floor": s43 < floors["s43"],
        "mean_below_floor": mean < floors["mean"],
    }
    return {
        "cell": guard_cell,
        "metric": "champion_tds",
        "s42": s42,
        "s43": s43,
        "mean": mean,
        "floors": floors,
        "clauses": clauses,
        # Registered semantics: the guard fires only on the conjunction.
        "fired": all(clauses.values()),
    }


def write_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    tmp.replace(path)
    # The verdict must survive a host death one second later, or the next
    # launch would run a second exam.
    directory = os.open(str(path.parent), os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def build_verdict(args: argparse.Namespace) -> dict:
    exam_dir = args.exam_dir
    if not exam_dir.is_dir():
        raise VerdictError(f"exam dir not found: {exam_dir}")
    if len(set(args.seeds)) != len(args.seeds):
        raise VerdictError(f"duplicate exam seeds: {args.seeds}")
    cells = [
        read_cell(exam_dir, seed, name, bot_type, bot_team, args.min_games)
        for seed in args.seeds
        for name, bot_type, bot_team in CELLS
    ]
    checkpoints = sorted({cell["checkpoint_sha256"] for cell in cells})
    if len(checkpoints) != 1:
        raise VerdictError(f"cells examined different checkpoints: {checkpoints}")
    if args.checkpoint_sha256 and checkpoints[0] != args.checkpoint_sha256:
        raise VerdictError(
            f"cells examined checkpoint {checkpoints[0]}, the stage expected "
            f"{args.checkpoint_sha256}")

    expected_rule = bool(args.no_early_end_turn)
    for cell in cells:
        if bool(cell.get("no_early_end_turn", 0)) != expected_rule:
            raise VerdictError(
                f"{cell['log']}: the cell ran with no_early_end_turn "
                f"{'on' if cell.get('no_early_end_turn') else 'off'}, the "
                f"stage needs it {'on' if expected_rule else 'off'} (a "
                "checkpoint trained under the rule is examined under it, and "
                "only then)")

    guard = None
    passed = True
    if args.rule == "drift-guard":
        floors = {}
        for key in ("s42", "s43", "mean"):
            value = getattr(args, f"guard_floor_{key}")
            if value is None or not math.isfinite(value):
                raise VerdictError(
                    f"drift-guard needs a finite --guard-floor-{key}")
            floors[key] = value
        if args.guard_cell not in {name for name, _, _ in CELLS}:
            raise VerdictError(f"unknown --guard-cell: {args.guard_cell}")
        guard = drift_guard(cells, args.guard_cell, floors)
        passed = not guard["fired"]

    verdict = {
        "schema_version": SCHEMA_VERSION,
        "tool": "tools/chain_exam_verdict.py",
        "rule": args.rule,
        "pass": passed,
        "exam_dir": str(exam_dir),
        "seeds": list(args.seeds),
        "min_games": args.min_games,
        "checkpoint_sha256": checkpoints[0],
        "cells": cells,
        "guard": guard,
        "written_utc": datetime.datetime.now(
            datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if expected_rule:
        # Present only when the exam ran under the rule, so every other
        # verdict keeps the keys it always had.
        verdict["no_early_end_turn"] = 1
    return verdict


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--exam-dir", type=Path, required=True,
                        help="directory holding s<seed>/<cell>.log")
    parser.add_argument("--seeds", type=int, nargs="+", required=True)
    parser.add_argument("--rule", choices=("none", "drift-guard"), required=True)
    parser.add_argument("--guard-cell", default="offense_away")
    parser.add_argument("--guard-floor-s42", type=float)
    parser.add_argument("--guard-floor-s43", type=float)
    parser.add_argument("--guard-floor-mean", type=float)
    parser.add_argument("--min-games", type=int, default=2000,
                        help="completed games every cell must reach")
    parser.add_argument("--checkpoint-sha256",
                        help="sha256 every cell manifest must name")
    parser.add_argument("--no-early-end-turn", type=int, choices=(0, 1),
                        default=0,
                        help="1 when the rung trained under the rule: every "
                             "cell must then have run under it (default 0: "
                             "none may have)")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)

    verdict_path = args.output_dir / VERDICT_NAME
    pass_path = args.output_dir / PASS_NAME
    try:
        if not args.output_dir.is_dir():
            raise VerdictError(f"output dir not found: {args.output_dir}")
        for existing in (verdict_path, pass_path):
            if existing.exists():
                raise VerdictError(
                    f"a verdict is already registered and is final: {existing}")
        verdict = build_verdict(args)
    except VerdictError as exc:
        print(f"chain exam verdict: NO VERDICT: {exc}", file=sys.stderr)
        return 2

    for cell in verdict["cells"]:
        print(
            f"  s{cell['seed']} {cell['cell']:<13} games {cell['games']:.0f}  "
            f"tds champion {cell['champion_tds']:.3f} bot {cell['bot_tds']:.3f}  "
            f"score champion {cell['champion_score']:.3f} "
            f"bot {cell['bot_score']:.3f}")
    guard = verdict["guard"]
    if guard is not None:
        print(
            f"  drift-guard {guard['cell']}: s42 {guard['s42']:.4f} "
            f"(floor {guard['floors']['s42']}), s43 {guard['s43']:.4f} "
            f"(floor {guard['floors']['s43']}), mean {guard['mean']:.4f} "
            f"(floor {guard['floors']['mean']}); clauses {guard['clauses']}")
    # PASS first: a host death between the two writes then leaves the success
    # artifact, never a final verdict that reads as a failure.
    if verdict["pass"]:
        write_atomic(pass_path, verdict)
    write_atomic(verdict_path, verdict)
    print(f"chain exam verdict: rule {verdict['rule']} "
          f"{'PASS' if verdict['pass'] else 'FAIL'} -> {verdict_path}")
    return 0 if verdict["pass"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
