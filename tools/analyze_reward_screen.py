#!/usr/bin/env python3
"""Verify and summarize a completed paired 2x2 reward screen.

The screen is a 2x2 factorial:

    r0 = possession/gain ON,  distance ON
    r1 = possession/gain ON,  distance OFF
    r2 = possession/gain OFF, distance ON
    r3 = possession/gain OFF, distance OFF

The original profile crosses possession/gain with distance.  The current
``possession-gain`` profile keeps distance on and separates the possession
annuity from the one-time gain event.  This analyzer verifies the profile's
frozen schedule, canonical rewards, accepted results, and completion proof
before calculating descriptive final-policy eval contrasts.  It never reads
trainer logs or checkpoints and never mutates screen artifacts.

Examples:

    python3 tools/analyze_reward_screen.py runs/reward-screens/my-screen
    python3 tools/analyze_reward_screen.py runs/reward-screens/my-screen \
        --json > reward-screen-analysis.json
    python3 tools/analyze_reward_screen.py runs/reward-screens/my-screen \
        --json --metrics tds perf possession_rate illegal_frac
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import statistics
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence


EXPECTED_SCHEDULE = (
    ("r0", 42),
    ("r3", 42),
    ("r1", 42),
    ("r2", 42),
    ("r2", 43),
    ("r1", 43),
    ("r3", 43),
    ("r0", 43),
)

CANONICAL_REWARD_SHA256 = {
    "r0": "14b718f28b2c925ea3279444dfbc679631c0cceea0f84d9e3547e3318ce6e90e",
    "r1": "13f8522fa08def678111a4a0592bf37d91fe65455fe8d971a69a23526ddb6c93",
    "r2": "5e31a13e5885c71c89af90f2ab504bbf7fcb94230ea33c834ba2d45fc9b930ae",
    "r3": "0a486e01c326e51f14d873c85b8fc9f364dc00baabc6714a3f16159703ce08de",
}

FACTORS = {
    "r0": {"possession_gain": True, "distance": True},
    "r1": {"possession_gain": True, "distance": False},
    "r2": {"possession_gain": False, "distance": True},
    "r3": {"possession_gain": False, "distance": False},
}

DEFAULT_METRICS = (
    "tds",
    "perf",
    "draw_rate",
    "possession_rate",
    "blocks_thrown",
    "block_2d_frac",
    "block_2dred_frac",
    "illegal_frac",
    "episode_length",
    "ball_fwd_adv",
    "ball_path_len",
)

EFFECT_DEFINITIONS = {
    "possession_main": (
        "((r0 + r1) - (r2 + r3)) / 2; mean change when the "
        "possession/ball-gain family is enabled"
    ),
    "distance_main": (
        "((r0 + r2) - (r1 + r3)) / 2; mean change when the "
        "distance family is enabled"
    ),
    "interaction": (
        "r0 - r1 - r2 + r3; difference-in-differences (departure "
        "from additive possession and distance effects)"
    ),
}

POSSESSION_GAIN_SCHEDULE = (
    ("both", 42),
    ("neither", 42),
    ("possession_only", 42),
    ("gain_only", 42),
    ("gain_only", 43),
    ("possession_only", 43),
    ("neither", 43),
    ("both", 43),
)

POSSESSION_GAIN_REWARD_SHA256 = {
    "both": CANONICAL_REWARD_SHA256["r0"],
    "possession_only":
        "e5e6744b95085f9b5cd8c0e280cf532e90b39b539114cfaf9692dd2221f6026f",
    "gain_only":
        "627468ec2e5d238b01606227cc5ffcfed764e391227fc76b517a946d29e7459d",
    "neither": CANONICAL_REWARD_SHA256["r2"],
}

POSSESSION_GAIN_FACTORS = {
    "both": {"possession": True, "gain": True},
    "possession_only": {"possession": True, "gain": False},
    "gain_only": {"possession": False, "gain": True},
    "neither": {"possession": False, "gain": False},
}

POSSESSION_GAIN_EFFECT_DEFINITIONS = {
    "possession_main": (
        "((both + possession_only) - (gain_only + neither)) / 2; "
        "mean change when the possession annuity is enabled"
    ),
    "gain_main": (
        "((both + gain_only) - (possession_only + neither)) / 2; "
        "mean change when the ball-gain event is enabled"
    ),
    "interaction": (
        "both - possession_only - gain_only + neither; "
        "difference-in-differences"
    ),
}

SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class AnalysisError(ValueError):
    """The screen artifact set is incomplete, stale, or inconsistent."""


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise AnalysisError(f"missing {label}: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise AnalysisError(f"{label} must contain a JSON object: {path}")
    return value


def _need_mapping(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AnalysisError(f"{label} must be an object")
    return value


def _need_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise AnalysisError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisError(f"{label} must be an integer") from exc
    if isinstance(value, float) and parsed != value:
        raise AnalysisError(f"{label} must be an integer")
    return parsed


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AnalysisError(f"{label} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise AnalysisError(f"{label} must be finite")
    return parsed


def _need_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise AnalysisError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _screen_spec(contract: dict[str, Any]) -> dict[str, Any]:
    profile = contract.get("screen_profile", "distance-possession")
    if profile == "distance-possession":
        return {
            "profile": profile,
            "schedule": EXPECTED_SCHEDULE,
            "reward_sha256": CANONICAL_REWARD_SHA256,
            "factors": FACTORS,
            "effect_definitions": EFFECT_DEFINITIONS,
        }
    if profile == "possession-gain":
        return {
            "profile": profile,
            "schedule": POSSESSION_GAIN_SCHEDULE,
            "reward_sha256": POSSESSION_GAIN_REWARD_SHA256,
            "factors": POSSESSION_GAIN_FACTORS,
            "effect_definitions": POSSESSION_GAIN_EFFECT_DEFINITIONS,
        }
    raise AnalysisError(f"unsupported reward-screen profile: {profile!r}")


def _validate_schedule(
        contract: dict[str, Any], expected_schedule: Sequence[tuple[str, int]],
) -> list[dict[str, int | str]]:
    schedule = contract.get("schedule")
    if not isinstance(schedule, list):
        raise AnalysisError("screen schedule must be an array")
    normalized = []
    for position, entry in enumerate(schedule, 1):
        if not isinstance(entry, dict):
            raise AnalysisError(f"screen schedule entry {position} must be an object")
        index = _need_int(entry.get("index"), f"screen schedule entry {position} index")
        arm = entry.get("arm")
        seed = _need_int(entry.get("seed"), f"screen schedule entry {position} seed")
        if index != position or not isinstance(arm, str):
            raise AnalysisError(f"invalid screen schedule entry {position}")
        normalized.append({"index": index, "arm": arm, "seed": seed})

    observed = tuple((entry["arm"], entry["seed"]) for entry in normalized)
    if observed != tuple(expected_schedule):
        raise AnalysisError(
            f"screen schedule does not match the frozen paired contract: {observed!r}"
        )
    return normalized


def _validate_reward_plan(
        contract: dict[str, Any], canonical_rewards: dict[str, str],
) -> None:
    rewards = _need_mapping(contract.get("rewards"), "screen rewards")
    observed_arms = set(rewards)
    expected_arms = set(canonical_rewards)
    if observed_arms != expected_arms:
        raise AnalysisError(
            "screen rewards do not match the canonical profile arms"
        )
    for arm, expected_sha in canonical_rewards.items():
        reward = _need_mapping(rewards.get(arm), f"screen reward {arm}")
        observed_sha = _need_sha256(
            reward.get("reward_sha256"), f"screen reward {arm} reward_sha256"
        )
        if observed_sha != expected_sha:
            raise AnalysisError(
                f"canonical factorial reward hash mismatch for {arm}: "
                f"{observed_sha} != {expected_sha}"
            )


def _selected_eval_metrics(
        result: dict[str, Any], metrics: Sequence[str], label: str) -> dict[str, float]:
    evaluated = _need_mapping(result.get("eval_metrics"), f"{label} eval_metrics")
    n = _finite_number(evaluated.get("n"), f"{label} eval_metrics.n")
    if n <= 0:
        raise AnalysisError(f"{label} eval_metrics.n must be positive")
    selected = {"n": n}
    for metric in metrics:
        if metric == "n":
            continue
        if metric not in evaluated:
            raise AnalysisError(f"{label} is missing selected eval metric {metric!r}")
        selected[metric] = _finite_number(
            evaluated[metric], f"{label} eval_metrics.{metric}")
    return selected


def _validate_result(
        path: Path,
        entry: dict[str, int | str],
        contract: dict[str, Any],
        manifest_sha: str,
        metrics: Sequence[str],
        factors: dict[str, dict[str, bool]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    result = _load_json(path, "screen result")
    label = path.name
    schema = _need_int(result.get("schema_version"), f"{label} schema_version")
    if schema < 2:
        raise AnalysisError(f"{label} is not a validated schema-2 result")
    if result.get("trainer_complete") is not True:
        raise AnalysisError(f"{label} trainer is not complete")
    if result.get("acceptance_pass") is not True:
        raise AnalysisError(f"{label} is not accepted")
    failures = result.get("acceptance_failures")
    if failures not in (None, []):
        raise AnalysisError(f"{label} is accepted but records acceptance failures")

    arm = str(entry["arm"])
    seed = int(entry["seed"])
    prefix = contract["prefix"]
    expected_tag = f"{prefix}-{arm}-s{seed}"
    identity = {
        "arm": arm,
        "seed": seed,
        "tag": expected_tag,
        "screen_manifest_sha256": manifest_sha,
    }
    for key, expected in identity.items():
        if result.get(key) != expected:
            raise AnalysisError(
                f"{label} {key} mismatch: {result.get(key)!r} != {expected!r}"
            )

    rewards = _need_mapping(contract.get("rewards"), "screen rewards")
    reward = _need_mapping(rewards.get(arm), f"screen reward {arm}")
    expected_reward_sha = _need_sha256(
        reward.get("reward_sha256"), f"screen reward {arm} reward_sha256"
    )
    if result.get("reward_sha256") != expected_reward_sha:
        raise AnalysisError(f"{label} reward hash does not match the screen plan")

    settings = _need_mapping(contract.get("settings"), "screen settings")
    expected_bytes = _need_int(
        settings.get("expected_checkpoint_bytes"),
        "screen settings expected_checkpoint_bytes",
    )
    if _need_int(result.get("checkpoint_bytes"), f"{label} checkpoint_bytes") != expected_bytes:
        raise AnalysisError(f"{label} checkpoint size does not match the screen plan")
    checkpoint_sha = _need_sha256(
        result.get("checkpoint_sha256"), f"{label} checkpoint_sha256"
    )
    provenance_sha = {
        field.removesuffix("_sha256"): _need_sha256(
            result.get(field), f"{label} {field}"
        )
        for field in (
            "log_sha256",
            "status_sha256",
            "process_sha256",
            "run_manifest_sha256",
        )
    }

    selected = _selected_eval_metrics(result, metrics, label)
    summary = {
        "index": int(entry["index"]),
        "arm": arm,
        "seed": seed,
        "factors": factors[arm],
        "result_file": path.name,
        "result_sha256": _sha256(path),
        "checkpoint_sha256": checkpoint_sha,
        "reward_sha256": expected_reward_sha,
        "provenance_sha256": provenance_sha,
        "eval": selected,
    }
    return result, summary


def _validate_completion(
        path: Path,
        manifest_sha: str,
        schedule: Sequence[dict[str, int | str]],
        result_paths: dict[tuple[str, int], Path],
        results: dict[tuple[str, int], dict[str, Any]],
) -> dict[str, Any]:
    complete = _load_json(path, "screen completion proof")
    if _need_int(complete.get("schema_version"), "completion schema_version") != 1:
        raise AnalysisError("unsupported SCREEN_COMPLETE.json schema")
    if complete.get("screen_manifest_sha256") != manifest_sha:
        raise AnalysisError("completion proof belongs to another screen plan")
    entries = complete.get("results")
    if not isinstance(entries, list) or len(entries) != len(schedule):
        raise AnalysisError("completion proof must contain all eight results")

    for expected, recorded in zip(schedule, entries):
        if not isinstance(recorded, dict):
            raise AnalysisError("completion result entry must be an object")
        arm = str(expected["arm"])
        seed = int(expected["seed"])
        key = (arm, seed)
        for field, value in (
            ("index", int(expected["index"])),
            ("arm", arm),
            ("seed", seed),
        ):
            if recorded.get(field) != value:
                raise AnalysisError(
                    f"completion result schedule mismatch for {arm}/seed {seed}"
                )
        result_path = result_paths[key]
        recorded_path = recorded.get("path")
        if not isinstance(recorded_path, str) or Path(recorded_path).name != result_path.name:
            raise AnalysisError(
                f"completion result path mismatch for {arm}/seed {seed}"
            )
        recorded_result_sha = _need_sha256(
            recorded.get("sha256"),
            f"completion result sha256 for {arm}/seed {seed}",
        )
        if recorded_result_sha != _sha256(result_path):
            raise AnalysisError(
                f"completion result hash mismatch for {arm}/seed {seed}"
            )
        recorded_checkpoint_sha = _need_sha256(
            recorded.get("checkpoint_sha256"),
            f"completion checkpoint_sha256 for {arm}/seed {seed}",
        )
        if recorded_checkpoint_sha != results[key].get("checkpoint_sha256"):
            raise AnalysisError(
                f"completion checkpoint hash mismatch for {arm}/seed {seed}"
            )

    return {
        "present": True,
        "file": path.name,
        "sha256": _sha256(path),
        "completed_utc": complete.get("completed_utc"),
    }


def _factorial_effects(
        cells: dict[str, float], profile: str,
) -> dict[str, float]:
    if profile == "distance-possession":
        r0, r1, r2, r3 = (cells[arm] for arm in ("r0", "r1", "r2", "r3"))
        return {
            "possession_main": ((r0 + r1) - (r2 + r3)) / 2.0,
            "distance_main": ((r0 + r2) - (r1 + r3)) / 2.0,
            "interaction": r0 - r1 - r2 + r3,
        }
    both = cells["both"]
    possession = cells["possession_only"]
    gain = cells["gain_only"]
    neither = cells["neither"]
    return {
        "possession_main": ((both + possession) - (gain + neither)) / 2.0,
        "gain_main": ((both + gain) - (possession + neither)) / 2.0,
        "interaction": both - possession - gain + neither,
    }


def _describe_two_seed_values(values: dict[str, float]) -> dict[str, Any]:
    ordered = [values[str(seed)] for seed in (42, 43)]
    return {
        "values_by_seed": values,
        "mean": statistics.fmean(ordered),
        "sample_sd": statistics.stdev(ordered),
        "min": min(ordered),
        "max": max(ordered),
        "seed_count": 2,
    }


def analyze_screen(
        screen_directory: str | Path,
        metrics: Sequence[str] = DEFAULT_METRICS,
        *,
        expected_screen_sha: str | None = None,
) -> dict[str, Any]:
    directory = Path(screen_directory).expanduser().resolve()
    if not directory.is_dir():
        raise AnalysisError(f"screen directory does not exist: {directory}")
    metrics = tuple(dict.fromkeys(metrics))
    if not metrics:
        raise AnalysisError("select at least one metric")
    if any(not isinstance(metric, str) or not metric for metric in metrics):
        raise AnalysisError("metric names must be non-empty strings")
    if "n" in metrics:
        raise AnalysisError(
            "eval metric 'n' is always reported as the sample count and "
            "cannot be used as a factorial outcome"
        )

    manifest_path = directory / "SCREEN_MANIFEST.json"
    manifest = _load_json(manifest_path, "screen manifest")
    if _need_int(manifest.get("schema_version"), "manifest schema_version") != 1:
        raise AnalysisError("unsupported SCREEN_MANIFEST.json schema")
    contract = _need_mapping(manifest.get("contract"), "screen contract")
    spec = _screen_spec(contract)
    prefix = contract.get("prefix")
    if not isinstance(prefix, str) or not prefix:
        raise AnalysisError("screen contract has no prefix")
    manifest_sha = _sha256(manifest_path)
    if expected_screen_sha is not None:
        expected_screen_sha = _need_sha256(
            expected_screen_sha, "expected screen manifest SHA-256"
        )
        if manifest_sha != expected_screen_sha:
            raise AnalysisError(
                "screen manifest SHA-256 does not match --expected-screen-sha: "
                f"{manifest_sha} != {expected_screen_sha}"
            )
    schedule = _validate_schedule(contract, spec["schedule"])
    _validate_reward_plan(contract, spec["reward_sha256"])

    expected_names = {
        f"{prefix}-{entry['arm']}-s{entry['seed']}.result.json"
        for entry in schedule
    }
    observed_names = {path.name for path in directory.glob("*.result.json")}
    missing = sorted(expected_names - observed_names)
    unexpected = sorted(observed_names - expected_names)
    if missing:
        raise AnalysisError("missing scheduled screen results: " + ", ".join(missing))
    if unexpected:
        raise AnalysisError("unexpected screen result files: " + ", ".join(unexpected))

    raw_results: dict[tuple[str, int], dict[str, Any]] = {}
    result_paths: dict[tuple[str, int], Path] = {}
    runs = []
    for entry in schedule:
        arm = str(entry["arm"])
        seed = int(entry["seed"])
        path = directory / f"{prefix}-{arm}-s{seed}.result.json"
        result, summary = _validate_result(
            path, entry, contract, manifest_sha, metrics, spec["factors"]
        )
        key = (arm, seed)
        raw_results[key] = result
        result_paths[key] = path
        runs.append(summary)

    warnings = [
        (
            "Only n=2 seeds are available. Across-seed means and sample SDs "
            "are descriptive; they are not confidence intervals, hypothesis "
            "tests, or a strength claim."
        ),
        (
            "These contrasts summarize final-policy self-play evaluation "
            "metrics. Promotion still requires paired held-out match-strength "
            "and behavioral checks."
        ),
    ]
    completion_path = directory / "SCREEN_COMPLETE.json"
    if completion_path.exists():
        completion = _validate_completion(
            completion_path, manifest_sha, schedule, result_paths, raw_results
        )
    else:
        completion = {"present": False}
        warnings.append(
            "SCREEN_COMPLETE.json is absent: eight accepted results were "
            "verified, but the atomic screen completion proof is unavailable."
        )

    per_seed: dict[str, Any] = {}
    for seed in (42, 43):
        cells: dict[str, dict[str, float]] = {
            arm: next(
                run["eval"] for run in runs
                if run["arm"] == arm and run["seed"] == seed
            )
            for arm in spec["factors"]
        }
        effects = {}
        for metric in metrics:
            metric_cells = {
                arm: cells[arm][metric] for arm in spec["factors"]
            }
            effects[metric] = _factorial_effects(
                metric_cells, spec["profile"])
        per_seed[str(seed)] = {"cells": cells, "effects": effects}

    cell_summaries: dict[str, Any] = {}
    for arm in spec["factors"]:
        cell_summaries[arm] = {}
        for metric in metrics:
            values = {
                str(seed): per_seed[str(seed)]["cells"][arm][metric]
                for seed in (42, 43)
            }
            cell_summaries[arm][metric] = _describe_two_seed_values(values)

    effect_summaries: dict[str, Any] = {}
    for metric in metrics:
        effect_summaries[metric] = {}
        for effect in spec["effect_definitions"]:
            values = {
                str(seed): per_seed[str(seed)]["effects"][metric][effect]
                for seed in (42, 43)
            }
            effect_summaries[metric][effect] = _describe_two_seed_values(values)

    return {
        "schema_version": 1,
        "analysis": "paired_reward_screen_2x2",
        "screen": {
            "directory": str(directory),
            "prefix": prefix,
            "profile": spec["profile"],
            "manifest_file": manifest_path.name,
            "manifest_sha256": manifest_sha,
            "requested_steps": contract.get("requested_steps"),
            "final_steps": contract.get("final_steps"),
            "schedule": schedule,
            "completion": completion,
        },
        "factor_mapping": spec["factors"],
        "canonical_reward_sha256": spec["reward_sha256"],
        "effect_definitions": spec["effect_definitions"],
        "metrics": list(metrics),
        "runs": runs,
        "per_seed": per_seed,
        "across_seeds": {
            "cell_summaries": cell_summaries,
            "effects": effect_summaries,
        },
        "warnings": warnings,
    }


def _format_number(value: float) -> str:
    return f"{value:.6g}"


def render_text(report: dict[str, Any]) -> str:
    lines = []
    screen = report["screen"]
    completion = screen["completion"]
    lines.append(
        f"Verified {len(report['runs'])} accepted reward-screen results "
        f"for {screen['prefix']}"
    )
    lines.append(f"screen manifest sha256: {screen['manifest_sha256']}")
    lines.append(
        "completion proof: " +
        (f"verified ({completion['sha256']})" if completion["present"] else "absent")
    )
    lines.append("")
    lines.append("Per-arm/per-seed final-policy eval summaries")
    for run in report["runs"]:
        values = " ".join(
            f"{metric}={_format_number(run['eval'][metric])}"
            for metric in report["metrics"]
        )
        lines.append(
            f"  seed={run['seed']} arm={run['arm']} n={run['eval']['n']:.0f} "
            f"{values}"
        )

    lines.append("")
    lines.append("Per-seed 2x2 effects")
    for seed in ("42", "43"):
        lines.append(f"  seed {seed}")
        for metric in report["metrics"]:
            effects = report["per_seed"][seed]["effects"][metric]
            lines.append(f"    {metric}: " + " ".join(
                f"{effect}={_format_number(effects[effect])}"
                for effect in report["effect_definitions"]
            ))

    lines.append("")
    lines.append("Across two seeds (descriptive means)")
    for metric in report["metrics"]:
        summaries = report["across_seeds"]["effects"][metric]
        lines.append(
            f"  {metric}: " + " ".join(
                f"{effect}={_format_number(summaries[effect]['mean'])}"
                for effect in report["effect_definitions"]
            )
        )
    lines.append("")
    lines.append("Warnings")
    lines.extend(f"  - {warning}" for warning in report["warnings"])
    return "\n".join(lines)


def _normalize_metrics(values: Iterable[str]) -> tuple[str, ...]:
    metrics = []
    for value in values:
        metrics.extend(part.strip() for part in value.split(",") if part.strip())
    return tuple(dict.fromkeys(metrics))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("screen_directory", type=Path)
    parser.add_argument(
        "--json", action="store_true",
        help="emit the complete machine-readable analysis JSON",
    )
    parser.add_argument(
        "--metrics", nargs="+", default=list(DEFAULT_METRICS),
        help="eval metric names (space- or comma-separated)",
    )
    parser.add_argument(
        "--expected-screen-sha",
        help="require this exact lowercase SCREEN_MANIFEST.json SHA-256",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report = analyze_screen(
            args.screen_directory,
            _normalize_metrics(args.metrics),
            expected_screen_sha=args.expected_screen_sha,
        )
    except AnalysisError as exc:
        print(f"reward-screen analysis failed: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
