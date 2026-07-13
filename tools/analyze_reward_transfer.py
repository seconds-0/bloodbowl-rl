#!/usr/bin/env python3
"""Verify and summarize the frozen R0-vs-R2 scripted-bot transfer matrix.

The exact matrix contains both training seeds, both deterministic bot styles,
and both home/away bot orientations. Cells are equal-weighted; games are only
weighted within a cell. The result is descriptive transfer evidence, not a
tournament confidence interval.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path

from contact_bot_stats import bot_perspective
from game_stats import dashboard_windows, weighted_dashboard


ARMS = ("r0", "r2")
SEEDS = (42, 43)
BOT_TYPES = (0, 1)
BOT_TEAMS = (0, 1)
EXPECTED_STEPS = 131_072
EXPECTED_GAMES = 1_000
EXPECTED_CONFIG_SHA = (
    "e15beab94a13704164fab297995539336c240107f54653a2a2fcd940c71b63ed"
)
EXPECTED_MODULE_SHA = (
    "5fb1b1df2ca1d13d1af88adf663e4ef3a6690228f820afb2f4132b87db277de4"
)
EXPECTED_PUFFERL_SHA = (
    "1c2d0ce96e270e12113a037a77f488e850d39ec76e240650ad7e0214bc04dd81"
)
EXPECTED_LAUNCHER_SHA = (
    "0623753810353def62de995c8cbfa6b1502fb1a5c590e54e1f41b4bed9296464"
)
EXPECTED_CHECKPOINT_SHA = {
    ("r0", 42): "296d1df0a3dd6de104033b00e4b61e4186db5c303d04866c12da21855a5537c2",
    ("r2", 42): "3cb37336e3354d0238773954c44ecf9dce51b31091aed5d0efa40efdcafa0837",
    ("r0", 43): "151294ea8e3d5d3fef8e5487b631ee1a3ebd92ba08443960f8844af068bfcfd6",
    ("r2", 43): "ea9967b26163fa82a02315f7e4fb031fbd0bd194faf7fa11a08e662a21ddff48",
}
METRICS = (
    "champion_score", "win_rate", "draw_rate", "loss_rate",
    "champion_tds", "bot_tds", "champion_blocks", "bot_blocks",
)
INTEGRITY = (
    "reward_clip_episodes", "reward_nonfinite_episodes", "error_episodes",
    "demo_episodes", "demo_fallbacks",
)
MANIFEST_PREFIX = "BB_EVAL_MANIFEST "


class TransferError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finite(value, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransferError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise TransferError(f"{label} must be finite")
    return value


def _manifest(path: Path) -> dict:
    with path.open(errors="ignore", encoding="utf-8") as handle:
        first = handle.readline().rstrip("\n")
    if not first.startswith(MANIFEST_PREFIX):
        raise TransferError(f"{path.name}: missing first-line eval manifest")
    try:
        value = json.loads(first[len(MANIFEST_PREFIX):])
    except json.JSONDecodeError as exc:
        raise TransferError(f"{path.name}: invalid eval manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise TransferError(f"{path.name}: eval manifest must be an object")
    return value


def _option(command: list, name: str):
    indices = [index for index, value in enumerate(command) if value == name]
    if len(indices) != 1 or indices[0] + 1 >= len(command):
        raise TransferError(f"command must contain exactly one {name}")
    return command[indices[0] + 1]


def _validate_log(path: Path, arm: str, seed: int,
                  bot_type: int, bot_team: int) -> dict:
    if not path.is_file():
        raise TransferError(f"missing transfer cell: {path}")
    manifest = _manifest(path)
    expected = {
        "schema_version": 1,
        "mode": "scripted_bot_frozen",
        "requested_train_steps": EXPECTED_STEPS,
        "seed": seed,
        "bot_type": bot_type,
        "bot_team": bot_team,
        "eval_episodes": EXPECTED_GAMES,
        "min_eval_games": EXPECTED_GAMES,
        "config_sha256": EXPECTED_CONFIG_SHA,
        "compiled_module_sha256": EXPECTED_MODULE_SHA,
        "pufferl_sha256": EXPECTED_PUFFERL_SHA,
        "launcher_sha256": EXPECTED_LAUNCHER_SHA,
        "checkpoint_sha256": EXPECTED_CHECKPOINT_SHA[(arm, seed)],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise TransferError(
                f"{path.name}: manifest {key}={manifest.get(key)!r}, "
                f"expected {value!r}")
    command = manifest.get("command")
    if not isinstance(command, list) or not all(
            isinstance(value, str) for value in command):
        raise TransferError(f"{path.name}: manifest command must be strings")
    for name, value in (
        ("--train.total-timesteps", EXPECTED_STEPS),
        ("--eval-episodes", EXPECTED_GAMES),
        ("--seed", seed),
        ("--train.seed", seed),
        ("--env.seed", seed),
        ("--env.scripted-opponent-type", bot_type),
        ("--env.scripted-opponent-team", bot_team),
    ):
        if _option(command, name) != str(value):
            raise TransferError(f"{path.name}: command mismatch for {name}")

    windows = dashboard_windows(path)
    if not windows:
        raise TransferError(f"{path.name}: no telemetry windows")
    if any(int(window.get("_puffer_schema", 0)) < 2 for window in windows):
        raise TransferError(f"{path.name}: pre-schema-2 telemetry")
    finals = [
        window for window in windows
        if window.get("_puffer_final_reprint", 0) > 0
        and window.get("_puffer_phase_eval", 0) > 0
    ]
    if len(finals) != 1:
        raise TransferError(
            f"{path.name}: expected one final eval reprint, got {len(finals)}")
    completed = _finite(
        finals[0].get("_puffer_eval_episodes_completed"),
        f"{path.name} cumulative eval games")
    if completed < EXPECTED_GAMES:
        raise TransferError(
            f"{path.name}: cumulative eval games {completed} < {EXPECTED_GAMES}")

    values = weighted_dashboard(path)
    games = _finite(values.get("n"), f"{path.name} eval games")
    if games < EXPECTED_GAMES:
        raise TransferError(f"{path.name}: eval sample {games} < {EXPECTED_GAMES}")
    bad = {
        key: _finite(values.get(key, 0), f"{path.name} {key}")
        for key in INTEGRITY if values.get(key, 0) != 0
    }
    if bad:
        raise TransferError(f"{path.name}: integrity failure {bad}")

    perspective = bot_perspective(values, bot_team)
    score = _finite(perspective["champion_score"], f"{path.name} score")
    draw = _finite(values.get("draw_rate"), f"{path.name} draw rate")
    win = score - 0.5 * draw
    loss = 1.0 - win - draw
    result = {
        "arm": arm,
        "seed": seed,
        "bot_type": bot_type,
        "bot_team": bot_team,
        "games": games,
        "eval_episodes_completed": completed,
        "log": path.name,
        "log_sha256": _sha256(path),
        "checkpoint_sha256": EXPECTED_CHECKPOINT_SHA[(arm, seed)],
        "champion_score": score,
        "win_rate": win,
        "draw_rate": draw,
        "loss_rate": loss,
        "champion_tds": _finite(
            perspective["champion_tds"], f"{path.name} champion TDs"),
        "bot_tds": _finite(perspective["bot_tds"], f"{path.name} bot TDs"),
        "champion_blocks": _finite(
            perspective["champion_blocks"], f"{path.name} champion blocks"),
        "bot_blocks": _finite(
            perspective["bot_blocks"], f"{path.name} bot blocks"),
    }
    if min(win, draw, loss) < -1e-6 or max(win, draw, loss) > 1 + 1e-6:
        raise TransferError(f"{path.name}: impossible derived W/D/L")
    return result


def _summary(rows: list[dict]) -> dict:
    return {
        metric: {
            "mean": statistics.fmean(row[metric] for row in rows),
            "sample_sd": statistics.stdev(row[metric] for row in rows)
                         if len(rows) > 1 else 0.0,
            "min": min(row[metric] for row in rows),
            "max": max(row[metric] for row in rows),
        }
        for metric in METRICS
    }


def analyze(directory: str | Path) -> dict:
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise TransferError(f"transfer directory does not exist: {directory}")
    rows = []
    for arm in ARMS:
        for seed in SEEDS:
            for bot_type in BOT_TYPES:
                for bot_team in BOT_TEAMS:
                    path = directory / (
                        f"{arm}-s{seed}-b{bot_type}-t{bot_team}.log")
                    rows.append(_validate_log(
                        path, arm, seed, bot_type, bot_team))

    paired = []
    for seed in SEEDS:
        for bot_type in BOT_TYPES:
            for bot_team in BOT_TEAMS:
                cells = {
                    row["arm"]: row for row in rows
                    if row["seed"] == seed
                    and row["bot_type"] == bot_type
                    and row["bot_team"] == bot_team
                }
                paired.append({
                    "seed": seed,
                    "bot_type": bot_type,
                    "bot_team": bot_team,
                    **{
                        metric: cells["r2"][metric] - cells["r0"][metric]
                        for metric in METRICS
                    },
                })
    return {
        "schema_version": 1,
        "analysis": "reward_transfer_r2_minus_r0",
        "directory": str(directory),
        "cell_count": len(rows),
        "equal_weighted_games": sum(row["games"] for row in rows),
        "runs": rows,
        "arm_summaries": {
            arm: _summary([row for row in rows if row["arm"] == arm])
            for arm in ARMS
        },
        "by_bot_type": {
            str(bot_type): {
                arm: _summary([
                    row for row in rows
                    if row["arm"] == arm and row["bot_type"] == bot_type
                ])
                for arm in ARMS
            }
            for bot_type in BOT_TYPES
        },
        "paired_r2_minus_r0": {
            "cells": paired,
            "summary": _summary(paired),
            "positive_cells": {
                metric: sum(row[metric] > 0 for row in paired)
                for metric in METRICS
            },
        },
        "warning": (
            "Two training seeds and deterministic scripted opponents provide "
            "descriptive transfer evidence only; cells are not independent "
            "tournament replicates or a confidence interval."
        ),
    }


def render(report: dict) -> str:
    lines = [
        f"Verified {report['cell_count']} frozen transfer cells; "
        f"{report['equal_weighted_games']:.0f} total full games",
        "",
        "Equal-cell arm means",
    ]
    for arm in ARMS:
        summary = report["arm_summaries"][arm]
        lines.append("  " + arm + " " + " ".join(
            f"{metric}={summary[metric]['mean']:.6g}" for metric in METRICS))
    lines.extend(["", "Paired R2 - R0 mean (8 seed/style/side cells)"])
    paired = report["paired_r2_minus_r0"]
    for metric in METRICS:
        value = paired["summary"][metric]
        lines.append(
            f"  {metric}: mean={value['mean']:.6g} "
            f"sd={value['sample_sd']:.6g} range="
            f"[{value['min']:.6g}, {value['max']:.6g}] "
            f"positive={paired['positive_cells'][metric]}/8")
    lines.extend(["", "Warning", "  " + report["warning"]])
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--output", type=Path,
        help="also write the complete verified analysis JSON to this path",
    )
    args = parser.parse_args(argv)
    try:
        report = analyze(args.directory)
    except (OSError, TransferError, ValueError) as exc:
        print(f"reward-transfer analysis failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    if args.json:
        print(rendered, end="")
    else:
        print(render(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
