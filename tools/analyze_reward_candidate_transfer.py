#!/usr/bin/env python3
"""Verify a manifested multi-candidate scripted-opponent transfer matrix.

This is a conservative gate between a self-play reward screen and longer
confirmation. It can select a candidate for *further testing*, never promote a
reward. All cells are equal-weighted and the limitations of deterministic bots
remain explicit in the output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import sys
from pathlib import Path
from typing import Any

from contact_bot_stats import bot_perspective
from game_stats import dashboard_windows, weighted_dashboard


MANIFEST_PREFIX = "BB_EVAL_MANIFEST "
INTEGRITY = (
    "reward_clip_episodes", "reward_nonfinite_episodes", "error_episodes",
    "demo_episodes", "demo_fallbacks",
)
METRICS = (
    "champion_score", "win_rate", "draw_rate", "loss_rate",
    "champion_tds", "bot_tds", "champion_blocks", "bot_blocks",
)


class TransferError(ValueError):
    pass


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise TransferError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise TransferError(f"{label} must be a JSON object: {path}")
    return value


def _finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TransferError(f"{label} must be numeric")
    value = float(value)
    if not math.isfinite(value):
        raise TransferError(f"{label} must be finite")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TransferError(f"{label} must be a positive integer")
    return value


def _int_list(value: Any, label: str, allowed: set[int] | None = None) -> list[int]:
    if (not isinstance(value, list) or not value or
            not all(isinstance(item, int) and not isinstance(item, bool)
                    for item in value) or len(set(value)) != len(value)):
        raise TransferError(f"{label} must contain unique integers")
    if allowed is not None and not set(value) <= allowed:
        raise TransferError(f"{label} contains unsupported values")
    return value


def _arms(value: Any, label: str) -> list[str]:
    if (not isinstance(value, list) or not value or
            not all(isinstance(item, str) and item for item in value) or
            len(set(value)) != len(value)):
        raise TransferError(f"{label} must contain unique nonempty strings")
    return value


def _sha(value: Any, label: str) -> str:
    if (not isinstance(value, str) or len(value) != 64 or
            any(char not in "0123456789abcdef" for char in value)):
        raise TransferError(f"{label} must be a lowercase SHA-256")
    return value


def _eval_manifest(path: Path) -> dict[str, Any]:
    try:
        with path.open(errors="ignore", encoding="utf-8") as handle:
            first = handle.readline().rstrip("\n")
    except OSError as exc:
        raise TransferError(f"cannot read transfer cell {path}: {exc}") from exc
    if not first.startswith(MANIFEST_PREFIX):
        raise TransferError(f"{path.name}: missing first-line eval manifest")
    try:
        value = json.loads(first[len(MANIFEST_PREFIX):])
    except json.JSONDecodeError as exc:
        raise TransferError(f"{path.name}: invalid eval manifest: {exc}") from exc
    if not isinstance(value, dict):
        raise TransferError(f"{path.name}: eval manifest must be an object")
    return value


def _option(command: list[Any], name: str) -> str:
    indices = [index for index, value in enumerate(command) if value == name]
    if len(indices) != 1 or indices[0] + 1 >= len(command):
        raise TransferError(f"command must contain exactly one {name}")
    value = command[indices[0] + 1]
    if not isinstance(value, str):
        raise TransferError(f"command value for {name} must be a string")
    return value


def _validate_plan(directory: Path) -> dict[str, Any]:
    path = directory / "TRANSFER_MANIFEST.json"
    plan = _load_object(path, "transfer manifest")
    if plan.get("schema_version") != 1:
        raise TransferError("transfer manifest schema_version must be 1")
    reference = plan.get("reference_arm")
    if not isinstance(reference, str) or not reference:
        raise TransferError("reference_arm must be a nonempty string")
    candidates = _arms(plan.get("candidate_arms"), "candidate_arms")
    if reference in candidates:
        raise TransferError("reference_arm cannot also be a candidate")
    preference = _arms(plan.get("preference_order"), "preference_order")
    if set(preference) != set(candidates):
        raise TransferError("preference_order must contain every candidate exactly once")
    seeds = _int_list(plan.get("seeds"), "seeds")
    bot_types = _int_list(plan.get("bot_types"), "bot_types", {0, 1})
    bot_teams = _int_list(plan.get("bot_teams"), "bot_teams", {0, 1})
    settings = plan.get("settings")
    implementation = plan.get("implementation")
    checkpoints = plan.get("checkpoints")
    gates = plan.get("gates")
    if not all(isinstance(item, dict) for item in (
            settings, implementation, checkpoints, gates)):
        raise TransferError(
            "settings, implementation, checkpoints, and gates must be objects")
    for key in ("requested_train_steps", "eval_episodes", "min_eval_games"):
        _positive_int(settings.get(key), f"settings.{key}")
    for key in (
        "config_sha256", "compiled_module_sha256", "pufferl_sha256",
        "launcher_sha256",
    ):
        _sha(implementation.get(key), f"implementation.{key}")
    for arm in (reference, *candidates):
        by_seed = checkpoints.get(arm)
        if not isinstance(by_seed, dict):
            raise TransferError(f"missing checkpoint map for {arm}")
        for seed in seeds:
            record = by_seed.get(str(seed))
            if not isinstance(record, dict):
                raise TransferError(f"missing checkpoint for {arm}/seed {seed}")
            _sha(record.get("torch_sha256"), f"{arm}/seed {seed} torch_sha256")
    for key in (
        "mean_score_delta_min", "cell_score_delta_min",
        "max_champion_td_relative_drop", "max_bot_td_relative_rise",
    ):
        _finite(gates.get(key), f"gates.{key}")
    return {
        **plan,
        "_path": str(path),
        "_sha256": _sha256(path),
        "_arms": [reference, *candidates],
        "_seeds": seeds,
        "_bot_types": bot_types,
        "_bot_teams": bot_teams,
    }


def _validate_cell(
    path: Path, plan: dict[str, Any], arm: str, seed: int,
    bot_type: int, bot_team: int,
) -> dict[str, Any]:
    if not path.is_file():
        raise TransferError(f"missing transfer cell: {path}")
    manifest = _eval_manifest(path)
    settings = plan["settings"]
    expected = {
        "schema_version": 1,
        "mode": "scripted_bot_frozen",
        "checkpoint_sha256": plan["checkpoints"][arm][str(seed)]["torch_sha256"],
        "requested_train_steps": settings["requested_train_steps"],
        "seed": seed,
        "bot_type": bot_type,
        "bot_team": bot_team,
        "eval_episodes": settings["eval_episodes"],
        "min_eval_games": settings["min_eval_games"],
        **plan["implementation"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise TransferError(
                f"{path.name}: manifest {key}={manifest.get(key)!r}, "
                f"expected {value!r}")
    command = manifest.get("command")
    if (not isinstance(command, list) or
            not all(isinstance(value, str) for value in command)):
        raise TransferError(f"{path.name}: manifest command must be strings")
    for name, value in (
        ("--train.total-timesteps", settings["requested_train_steps"]),
        ("--eval-episodes", settings["eval_episodes"]),
        ("--seed", seed), ("--train.seed", seed), ("--env.seed", seed),
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
        f"{path.name} cumulative eval games",
    )
    if completed < settings["min_eval_games"]:
        raise TransferError(f"{path.name}: cumulative game gate failed")
    values = weighted_dashboard(path)
    games = _finite(values.get("n"), f"{path.name} games")
    if games < settings["min_eval_games"]:
        raise TransferError(f"{path.name}: sample too small")
    bad = {key: values.get(key, 0) for key in INTEGRITY
           if values.get(key, 0) != 0}
    if bad:
        raise TransferError(f"{path.name}: integrity counters nonzero: {bad}")
    perspective = bot_perspective(values, bot_team)
    score = _finite(perspective["champion_score"], f"{path.name} score")
    draw = _finite(values.get("draw_rate"), f"{path.name} draw rate")
    win = score - 0.5 * draw
    loss = 1.0 - win - draw
    if min(win, draw, loss) < -1e-6 or max(win, draw, loss) > 1 + 1e-6:
        raise TransferError(f"{path.name}: impossible derived W/D/L")
    return {
        "arm": arm, "seed": seed, "bot_type": bot_type,
        "bot_team": bot_team, "games": games,
        "eval_episodes_completed": completed, "log": path.name,
        "log_sha256": _sha256(path),
        "checkpoint_sha256": expected["checkpoint_sha256"],
        "champion_score": score, "win_rate": win, "draw_rate": draw,
        "loss_rate": loss,
        "champion_tds": _finite(
            perspective["champion_tds"], f"{path.name} champion TDs"),
        "bot_tds": _finite(perspective["bot_tds"], f"{path.name} bot TDs"),
        "champion_blocks": _finite(
            perspective["champion_blocks"], f"{path.name} champion blocks"),
        "bot_blocks": _finite(
            perspective["bot_blocks"], f"{path.name} bot blocks"),
    }


def _summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
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


def _relative_delta(candidate: float, reference: float) -> float:
    if reference <= 0:
        raise TransferError("relative gate reference must be positive")
    return (candidate - reference) / reference


def analyze(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory).expanduser().resolve()
    if not directory.is_dir():
        raise TransferError(f"transfer directory does not exist: {directory}")
    plan = _validate_plan(directory)
    rows = []
    for arm in plan["_arms"]:
        for seed in plan["_seeds"]:
            for bot_type in plan["_bot_types"]:
                for bot_team in plan["_bot_teams"]:
                    path = directory / f"{arm}-s{seed}-b{bot_type}-t{bot_team}.log"
                    rows.append(_validate_cell(
                        path, plan, arm, seed, bot_type, bot_team))
    summaries = {
        arm: _summary([row for row in rows if row["arm"] == arm])
        for arm in plan["_arms"]
    }
    reference = plan["reference_arm"]
    contrasts: dict[str, Any] = {}
    for candidate in plan["candidate_arms"]:
        paired = []
        for seed in plan["_seeds"]:
            for bot_type in plan["_bot_types"]:
                for bot_team in plan["_bot_teams"]:
                    key = (seed, bot_type, bot_team)
                    cells = {
                        row["arm"]: row for row in rows
                        if (row["seed"], row["bot_type"], row["bot_team"]) == key
                        and row["arm"] in (reference, candidate)
                    }
                    paired.append({
                        "seed": seed, "bot_type": bot_type, "bot_team": bot_team,
                        **{metric: cells[candidate][metric] - cells[reference][metric]
                           for metric in METRICS},
                    })
        summary = _summary(paired)
        gates = plan["gates"]
        candidate_summary = summaries[candidate]
        reference_summary = summaries[reference]
        td_drop = -_relative_delta(
            candidate_summary["champion_tds"]["mean"],
            reference_summary["champion_tds"]["mean"],
        )
        bot_td_rise = _relative_delta(
            candidate_summary["bot_tds"]["mean"],
            reference_summary["bot_tds"]["mean"],
        )
        failures = []
        if summary["champion_score"]["mean"] < gates["mean_score_delta_min"]:
            failures.append("mean_score_delta")
        if summary["champion_score"]["min"] < gates["cell_score_delta_min"]:
            failures.append("cell_score_delta")
        if td_drop > gates["max_champion_td_relative_drop"]:
            failures.append("champion_td_relative_drop")
        if bot_td_rise > gates["max_bot_td_relative_rise"]:
            failures.append("bot_td_relative_rise")
        contrasts[candidate] = {
            "cells": paired,
            "summary": summary,
            "champion_td_relative_drop": td_drop,
            "bot_td_relative_rise": bot_td_rise,
            "eligible": not failures,
            "gate_failures": failures,
        }
    eligible = [arm for arm in plan["preference_order"]
                if contrasts[arm]["eligible"]]
    selected = eligible[0] if eligible else reference
    return {
        "schema_version": 1,
        "analysis": "reward_candidate_scripted_transfer",
        "directory": str(directory),
        "transfer_manifest": {
            "path": plan["_path"], "sha256": plan["_sha256"],
        },
        "reference_arm": reference,
        "candidate_arms": plan["candidate_arms"],
        "cell_count": len(rows),
        "total_games": sum(row["games"] for row in rows),
        "runs": rows,
        "arm_summaries": summaries,
        "candidate_contrasts": contrasts,
        "recommendation": {
            "arm": selected,
            "eligible_candidates_in_preference_order": eligible,
            "purpose": "candidate for longer confirmation only",
        },
        "warning": (
            "Deterministic scripted opponents are a conservative transfer gate, "
            "not learned-opponent, roster-grid, confidence-interval, or reward-"
            "promotion evidence."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = analyze(args.directory)
    except (OSError, TransferError, ValueError) as exc:
        print(f"candidate-transfer analysis failed: {exc}", file=sys.stderr)
        return 2
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(rendered, encoding="utf-8")
        temporary.replace(args.output)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
