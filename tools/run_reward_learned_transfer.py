#!/usr/bin/env python3
"""Run and verify a paired reward transfer matrix against learned anchors.

The source must be a completed ``paired-confirmation`` reward screen.  Each
reference/candidate checkpoint is matched against every hash-pinned learned
anchor with the focal policy loaded once as the primary policy and once as the
frozen-bank policy.  The two orientations expose backend-role asymmetry even
though Puffer's match environment independently randomizes team colour.

Every cell is restart-validating and content-addressed.  The final gate is a
conservative routing gate for longer confirmation, never reward promotion.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Any

import analyze_reward_screen
import run_reward_candidate_transfer


SCHEMA_VERSION = 1
EXPECTED_NATIVE_BYTES = 16_066_560
INTEGRITY_KEYS = (
    "reward_clip_frac",
    "reward_clip_frac_nonzero",
    "reward_clip_excess",
    "reward_nonfinite_frac",
    "reward_clip_episodes",
    "reward_nonfinite_episodes",
    "error_episodes",
    "demo_episodes",
    "demo_fallbacks",
)
NAME_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")


class LearnedTransferError(ValueError):
    pass


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(
        destination.suffix + f".tmp.{os.getpid()}"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LearnedTransferError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise LearnedTransferError(f"{label} must be a JSON object: {path}")
    return value


def need_sha(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise LearnedTransferError(f"{label} must be a lowercase SHA-256")
    return value


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LearnedTransferError(f"{label} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise LearnedTransferError(f"{label} must be finite")
    return parsed


def positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise LearnedTransferError(f"{label} must be a positive integer")
    return value


def validate_anchor_config(path: Path) -> dict[str, Any]:
    config = load_object(path, "learned-anchor config")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise LearnedTransferError("unsupported learned-anchor config schema")
    games = positive_int(config.get("games_per_cell"), "games_per_cell")
    if games < 1_000:
        raise LearnedTransferError("games_per_cell must be at least 1000")
    anchors = config.get("anchors")
    if not isinstance(anchors, list) or len(anchors) < 2:
        raise LearnedTransferError("anchor config requires at least two anchors")
    normalized = []
    names: set[str] = set()
    hashes: set[str] = set()
    for index, record in enumerate(anchors, 1):
        if not isinstance(record, dict):
            raise LearnedTransferError(f"anchor {index} must be an object")
        if set(record) != {"name", "path", "bytes", "sha256"}:
            raise LearnedTransferError(f"anchor {index} has unknown/missing fields")
        name = record.get("name")
        if not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None:
            raise LearnedTransferError(f"anchor {index} has invalid name")
        if name in names:
            raise LearnedTransferError(f"duplicate anchor name: {name}")
        names.add(name)
        path_value = record.get("path")
        if not isinstance(path_value, str) or not Path(path_value).is_absolute():
            raise LearnedTransferError(f"anchor {name} path must be absolute")
        checkpoint = Path(path_value).expanduser().resolve()
        if not checkpoint.is_file():
            raise LearnedTransferError(f"missing anchor checkpoint: {checkpoint}")
        expected_bytes = positive_int(record.get("bytes"), f"anchor {name} bytes")
        if expected_bytes != EXPECTED_NATIVE_BYTES:
            raise LearnedTransferError(
                f"anchor {name} bytes must be {EXPECTED_NATIVE_BYTES}"
            )
        if checkpoint.stat().st_size != expected_bytes:
            raise LearnedTransferError(f"anchor {name} size drift")
        expected_sha = need_sha(record.get("sha256"), f"anchor {name} sha256")
        observed_sha = sha256(checkpoint)
        if observed_sha != expected_sha:
            raise LearnedTransferError(f"anchor {name} SHA-256 drift")
        if expected_sha in hashes:
            raise LearnedTransferError(f"anchor {name} duplicates another checkpoint")
        hashes.add(expected_sha)
        normalized.append(
            {
                "name": name,
                "path": str(checkpoint),
                "bytes": expected_bytes,
                "sha256": expected_sha,
            }
        )
    gates = config.get("gates")
    if not isinstance(gates, dict) or set(gates) != {
        "mean_score_delta_min",
        "seed_mean_score_delta_min",
        "anchor_mean_score_delta_min",
        "orientation_mean_score_delta_min",
        "cell_score_delta_min",
    }:
        raise LearnedTransferError("learned-anchor config gates are incomplete")
    normalized_gates = {
        key: finite(value, f"gates.{key}") for key, value in gates.items()
    }
    if normalized_gates["cell_score_delta_min"] > normalized_gates[
        "anchor_mean_score_delta_min"
    ]:
        raise LearnedTransferError(
            "cell_score_delta_min must not exceed anchor_mean_score_delta_min"
        )
    if normalized_gates["cell_score_delta_min"] > normalized_gates[
        "seed_mean_score_delta_min"
    ]:
        raise LearnedTransferError(
            "cell_score_delta_min must not exceed seed_mean_score_delta_min"
        )
    if normalized_gates["cell_score_delta_min"] > normalized_gates[
        "orientation_mean_score_delta_min"
    ]:
        raise LearnedTransferError(
            "cell_score_delta_min must not exceed orientation_mean_score_delta_min"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "games_per_cell": games,
        "anchors": normalized,
        "gates": normalized_gates,
        "path": str(path.resolve()),
        "sha256": sha256(path),
    }


def screen_inputs(
    complete_path: Path,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]], tuple[str, str]]:
    complete_path = complete_path.expanduser().resolve()
    complete = load_object(complete_path, "screen completion")
    if complete_path.name != "SCREEN_COMPLETE.json":
        raise LearnedTransferError("source must be named SCREEN_COMPLETE.json")
    expected_manifest_sha = need_sha(
        complete.get("screen_manifest_sha256"),
        "screen completion manifest SHA-256",
    )
    report = analyze_reward_screen.analyze_screen(
        complete_path.parent,
        analyze_reward_screen.DEFAULT_METRICS,
        expected_screen_sha=expected_manifest_sha,
    )
    completion = report["screen"]["completion"]
    if not completion.get("present") or completion.get("sha256") != sha256(
        complete_path
    ):
        raise LearnedTransferError("screen completion evidence is not exact")
    if report["screen"]["profile"] != "paired-confirmation":
        raise LearnedTransferError(
            "learned transfer requires a paired-confirmation screen"
        )
    candidate = report["screen"].get("candidate_arm")
    if candidate not in run_reward_candidate_transfer.FULL_ARMS[1:]:
        raise LearnedTransferError("paired screen has an invalid candidate")
    checkpoints, arms = run_reward_candidate_transfer.screen_checkpoints(
        complete_path.parent, expected_manifest_sha
    )
    if arms != ("both", candidate):
        raise LearnedTransferError("paired checkpoint arms differ from candidate")
    return report, checkpoints, ("both", candidate)


def implementation_identity(root: Path) -> dict[str, Any]:
    python = root / "vendor/PufferLib/.venv/bin/python"
    probe = subprocess.run(
        [
            str(python),
            "-c",
            (
                "from pufferlib import _C; print(_C.__file__); "
                "print(_C.env_name, int(bool(_C.gpu)), int(_C.precision_bytes))"
            ),
        ],
        cwd=root / "vendor/PufferLib",
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    if probe.returncode != 0:
        raise LearnedTransferError(
            f"native module probe failed: {probe.stdout[-2000:]}"
        )
    lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        raise LearnedTransferError(f"unexpected native module probe: {probe.stdout!r}")
    module = Path(lines[0]).resolve()
    try:
        env_name, gpu, precision = lines[1].split()
    except ValueError as exc:
        raise LearnedTransferError(f"unexpected native probe fields: {lines[1]}") from exc
    if (env_name, gpu, precision) != ("bloodbowl", "1", "4"):
        raise LearnedTransferError(
            f"learned transfer requires bloodbowl GPU fp32; got {lines[1]}"
        )
    files = {
        "compiled_module": module,
        "package_init": root / "vendor/PufferLib/pufferlib/__init__.py",
        "default_config": root / "vendor/PufferLib/config/default.ini",
        "env_config": root / "vendor/PufferLib/config/bloodbowl.ini",
        "pufferl": root / "vendor/PufferLib/pufferlib/pufferl.py",
        "models": root / "vendor/PufferLib/pufferlib/models.py",
        "selfplay": root / "vendor/PufferLib/pufferlib/selfplay.py",
        "runner": Path(__file__).resolve(),
        "screen_analyzer": root / "tools/analyze_reward_screen.py",
        "screen_transfer": root / "tools/run_reward_candidate_transfer.py",
    }
    return {
        "env_name": env_name,
        "gpu": int(gpu),
        "precision_bytes": int(precision),
        "config_tree_path": str((root / "vendor/PufferLib/config").resolve()),
        "config_tree_sha256": run_reward_candidate_transfer.tree_sha256(
            root / "vendor/PufferLib/config"
        ),
        **{f"{key}_path": str(path) for key, path in files.items()},
        **{f"{key}_sha256": sha256(path) for key, path in files.items()},
    }


def learned_contract_identity(
    root: Path, anchor_config: dict[str, Any]
) -> dict[str, Any]:
    """Return every non-lineage input that must match between matrices."""
    return {
        "training_seeds": list(run_reward_candidate_transfer.SEEDS),
        "orientations": [0, 1],
        "games_per_cell": anchor_config["games_per_cell"],
        "anchor_config": anchor_config["path"],
        "anchor_config_sha256": anchor_config["sha256"],
        "anchors": anchor_config["anchors"],
        "gates": anchor_config["gates"],
        "implementation": implementation_identity(root),
    }


def freeze_manifest(
    path: Path,
    root: Path,
    complete_path: Path,
    screen_report: dict[str, Any],
    checkpoints: dict[str, dict[str, Any]],
    arms: tuple[str, str],
    anchor_config: dict[str, Any],
) -> dict[str, Any]:
    core = {
        "schema_version": SCHEMA_VERSION,
        "matrix_id": path.parent.name,
        "source_screen_complete": str(complete_path),
        "source_screen_complete_sha256": sha256(complete_path),
        "source_screen_manifest_sha256": screen_report["screen"][
            "manifest_sha256"
        ],
        "reference_arm": arms[0],
        "candidate_arm": arms[1],
        **learned_contract_identity(root, anchor_config),
        "checkpoints": checkpoints,
    }
    if path.exists():
        recorded = load_object(path, "learned-transfer manifest")
        if {key: recorded.get(key) for key in core} != core:
            raise LearnedTransferError(
                "existing learned-transfer manifest differs from recomputed plan"
            )
        return recorded
    payload = {**core, "created_utc": utc_now()}
    atomic_json(path, payload)
    return payload


def cell_filename(arm: str, seed: int, anchor: str, orientation: int) -> str:
    return f"{arm}-s{seed}-{anchor}-o{orientation}.json"


def expected_cells(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for arm in (plan["reference_arm"], plan["candidate_arm"]):
        for seed_index, seed in enumerate(plan["training_seeds"]):
            for anchor_index, anchor in enumerate(plan["anchors"]):
                for orientation in plan["orientations"]:
                    rows.append(
                        {
                            "arm": arm,
                            "training_seed": seed,
                            "anchor": anchor["name"],
                            "orientation": orientation,
                            # Identical match seed for reference/candidate in a
                            # stratum; the policy arm is intentionally omitted.
                            "match_seed": (
                                20_000
                                + seed_index * 1_000
                                + anchor_index * 10
                                + orientation
                            ),
                            "path": cell_filename(
                                arm, seed, anchor["name"], orientation
                            ),
                        }
                    )
    return rows


def validate_cell(
    path: Path, plan: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    cell = load_object(path, "learned-transfer cell")
    if cell.get("schema_version") != SCHEMA_VERSION:
        raise LearnedTransferError(f"unsupported cell schema: {path.name}")
    identity = {
        "arm": expected["arm"],
        "training_seed": expected["training_seed"],
        "anchor": expected["anchor"],
        "orientation": expected["orientation"],
        "match_seed": expected["match_seed"],
        "games_requested": plan["games_per_cell"],
        "learned_transfer_manifest_sha256": sha256(
            path.parent / "LEARNED_TRANSFER_MANIFEST.json"
        ),
    }
    for key, value in identity.items():
        if cell.get(key) != value:
            raise LearnedTransferError(
                f"{path.name} {key}={cell.get(key)!r}, expected {value!r}"
            )
    if cell.get("implementation") != plan.get("implementation"):
        raise LearnedTransferError(f"{path.name} implementation identity drift")
    checkpoint = plan["checkpoints"][expected["arm"]][
        str(expected["training_seed"])
    ]
    anchor = next(
        item for item in plan["anchors"] if item["name"] == expected["anchor"]
    )
    if cell.get("focal_checkpoint_sha256") != checkpoint["native_sha256"]:
        raise LearnedTransferError(f"{path.name} focal checkpoint drift")
    if cell.get("anchor_checkpoint_sha256") != anchor["sha256"]:
        raise LearnedTransferError(f"{path.name} anchor checkpoint drift")
    games = finite(cell.get("games"), f"{path.name} games")
    if games < plan["games_per_cell"]:
        raise LearnedTransferError(f"{path.name} completed too few games")
    focal = finite(cell.get("focal_score"), f"{path.name} focal score")
    opponent = finite(cell.get("opponent_score"), f"{path.name} opponent score")
    draw = finite(cell.get("draw_rate"), f"{path.name} draw rate")
    focal_tds = finite(cell.get("focal_tds"), f"{path.name} focal TDs")
    opponent_tds = finite(cell.get("opponent_tds"), f"{path.name} opponent TDs")
    if min(focal, opponent, draw) < -1e-6 or max(focal, opponent, draw) > 1 + 1e-6:
        raise LearnedTransferError(f"{path.name} contains impossible rates")
    if abs(focal + opponent - 1.0) > 2e-4:
        raise LearnedTransferError(f"{path.name} slot scores do not sum to one")
    if (
        focal_tds < 0
        or opponent_tds < 0
        or focal - 0.5 * draw < -1e-6
        or opponent - 0.5 * draw < -1e-6
    ):
        raise LearnedTransferError(f"{path.name} contains impossible W/D/L or TDs")
    integrity = cell.get("integrity")
    if not isinstance(integrity, dict) or set(integrity) != set(INTEGRITY_KEYS):
        raise LearnedTransferError(f"{path.name} integrity fields are incomplete")
    bad = {
        key: finite(value, f"{path.name} integrity.{key}")
        for key, value in integrity.items()
        if finite(value, f"{path.name} integrity.{key}") != 0.0
    }
    if bad:
        raise LearnedTransferError(f"{path.name} integrity counters nonzero: {bad}")
    return {
        **identity,
        "games": games,
        "focal_score": focal,
        "opponent_score": opponent,
        "draw_rate": draw,
        "focal_tds": focal_tds,
        "opponent_tds": opponent_tds,
        "focal_checkpoint_sha256": checkpoint["native_sha256"],
        "anchor_checkpoint_sha256": anchor["sha256"],
        "file": path.name,
        "file_sha256": sha256(path),
    }


def run_cell(root: Path, plan_path: Path, cell_path: Path) -> int:
    plan = load_object(plan_path, "learned-transfer manifest")
    expected = next(
        (row for row in expected_cells(plan) if row["path"] == cell_path.name),
        None,
    )
    if expected is None:
        raise LearnedTransferError(f"unplanned learned-transfer cell: {cell_path}")
    manifest_sha = sha256(plan_path)
    implementation = plan["implementation"]
    for key in (
        "compiled_module",
        "package_init",
        "default_config",
        "env_config",
        "pufferl",
        "models",
        "selfplay",
        "runner",
        "screen_analyzer",
        "screen_transfer",
    ):
        source = Path(implementation[f"{key}_path"])
        if not source.is_file() or sha256(source) != implementation[f"{key}_sha256"]:
            raise LearnedTransferError(f"implementation drift before cell: {key}")
    config_tree = Path(implementation["config_tree_path"])
    if (
        not config_tree.is_dir()
        or run_reward_candidate_transfer.tree_sha256(config_tree)
        != implementation["config_tree_sha256"]
    ):
        raise LearnedTransferError("implementation drift before cell: config_tree")
    checkpoint = plan["checkpoints"][expected["arm"]][
        str(expected["training_seed"])
    ]
    anchor = next(
        item for item in plan["anchors"] if item["name"] == expected["anchor"]
    )
    for record, label in ((checkpoint, "focal"), (anchor, "anchor")):
        key = "native" if label == "focal" else "path"
        hash_key = "native_sha256" if label == "focal" else "sha256"
        file_path = Path(record[key])
        if not file_path.is_file() or sha256(file_path) != record[hash_key]:
            raise LearnedTransferError(f"{label} checkpoint drift before cell")

    sys.path.insert(0, str(root / "vendor/PufferLib"))
    from pufferlib import _C  # type: ignore
    from pufferlib import pufferl  # type: ignore

    if (
        getattr(_C, "env_name", None) != "bloodbowl"
        or not bool(getattr(_C, "gpu", False))
        or int(_C.precision_bytes) != 4
    ):
        raise LearnedTransferError("cell imported the wrong native module")
    imported_module = Path(_C.__file__).resolve()
    expected_module = Path(implementation["compiled_module_path"]).resolve()
    if (
        imported_module != expected_module
        or sha256(imported_module) != implementation["compiled_module_sha256"]
    ):
        raise LearnedTransferError(
            "cell imported a native module outside the frozen implementation"
        )
    args = pufferl.load_config("bloodbowl")
    args["train"]["gpus"] = 1
    args["train"]["seed"] = expected["match_seed"]
    args["env"]["seed"] = expected["match_seed"]
    args["env"]["macro_moves"] = 0
    args["env"]["demo_reset_pct"] = 0.0
    args["env"]["scripted_opponent"] = 0
    args["vec"]["num_threads"] = 16
    focal_path = checkpoint["native"]
    anchor_path = anchor["path"]
    if expected["orientation"] == 0:
        policy_a, policy_b, focal_key = focal_path, anchor_path, "env/slot_0_score"
        opponent_key = "env/slot_1_score"
        focal_tds_key, opponent_tds_key = "env/tds_t0", "env/tds_t1"
    else:
        policy_a, policy_b, focal_key = anchor_path, focal_path, "env/slot_1_score"
        opponent_key = "env/slot_0_score"
        focal_tds_key, opponent_tds_key = "env/tds_t1", "env/tds_t0"
    logs = pufferl.match(
        env_name="bloodbowl",
        policy_a_path=policy_a,
        policy_b_path=policy_b,
        num_games=plan["games_per_cell"],
        args=args,
        verbose=False,
    )
    numeric_logs = {
        key: finite(value, f"match log {key}")
        for key, value in logs.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    games = finite(numeric_logs.get("env/n"), "match env/n")
    if games < plan["games_per_cell"]:
        raise LearnedTransferError("match returned too few completed games")
    missing = [key for key in INTEGRITY_KEYS if f"env/{key}" not in numeric_logs]
    missing.extend(
        key for key in (
            focal_key, opponent_key, "env/draw_rate",
            focal_tds_key, opponent_tds_key,
        )
        if key not in numeric_logs
    )
    if missing:
        raise LearnedTransferError(f"match omitted required keys: {missing}")
    integrity = {key: numeric_logs[f"env/{key}"] for key in INTEGRITY_KEYS}
    bad = {key: value for key, value in integrity.items() if value != 0.0}
    if bad:
        raise LearnedTransferError(f"match integrity counters nonzero: {bad}")
    atomic_json(
        cell_path,
        {
            "schema_version": SCHEMA_VERSION,
            "created_utc": utc_now(),
            "learned_transfer_manifest_sha256": manifest_sha,
            "arm": expected["arm"],
            "training_seed": expected["training_seed"],
            "anchor": expected["anchor"],
            "orientation": expected["orientation"],
            "match_seed": expected["match_seed"],
            "games_requested": plan["games_per_cell"],
            "games": games,
            "focal_score": numeric_logs[focal_key],
            "opponent_score": numeric_logs[opponent_key],
            "draw_rate": numeric_logs["env/draw_rate"],
            "focal_tds": numeric_logs[focal_tds_key],
            "opponent_tds": numeric_logs[opponent_tds_key],
            "focal_checkpoint": focal_path,
            "focal_checkpoint_sha256": checkpoint["native_sha256"],
            "anchor_checkpoint": anchor_path,
            "anchor_checkpoint_sha256": anchor["sha256"],
            "policy_a": policy_a,
            "policy_b": policy_b,
            "implementation": implementation,
            "integrity": integrity,
            "raw_env_metrics": {
                key.removeprefix("env/"): value
                for key, value in numeric_logs.items()
                if key.startswith("env/")
            },
        },
    )
    validate_cell(cell_path, plan, expected)
    return 0


def summary(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise LearnedTransferError("cannot summarize an empty value list")
    return {
        "mean": statistics.fmean(values),
        "sample_sd": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
        "count": len(values),
    }


def analyze(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory).expanduser().resolve()
    plan_path = directory / "LEARNED_TRANSFER_MANIFEST.json"
    plan = load_object(plan_path, "learned-transfer manifest")
    rows = [
        validate_cell(directory / expected["path"], plan, expected)
        for expected in expected_cells(plan)
    ]
    reference = plan["reference_arm"]
    candidate = plan["candidate_arm"]
    paired = []
    for seed in plan["training_seeds"]:
        for anchor in plan["anchors"]:
            for orientation in plan["orientations"]:
                matching = {
                    row["arm"]: row
                    for row in rows
                    if row["training_seed"] == seed
                    and row["anchor"] == anchor["name"]
                    and row["orientation"] == orientation
                }
                if set(matching) != {reference, candidate}:
                    raise LearnedTransferError("incomplete paired learned-transfer cell")
                paired.append(
                    {
                        "training_seed": seed,
                        "anchor": anchor["name"],
                        "orientation": orientation,
                        "reference_score": matching[reference]["focal_score"],
                        "candidate_score": matching[candidate]["focal_score"],
                        "score_delta": (
                            matching[candidate]["focal_score"]
                            - matching[reference]["focal_score"]
                        ),
                        "candidate_tds_delta": (
                            matching[candidate]["focal_tds"]
                            - matching[reference]["focal_tds"]
                        ),
                        "candidate_opponent_tds_delta": (
                            matching[candidate]["opponent_tds"]
                            - matching[reference]["opponent_tds"]
                        ),
                    }
                )
    deltas = [row["score_delta"] for row in paired]
    aggregate = summary(deltas)
    by_training_seed = {
        str(seed): summary([
            row["score_delta"] for row in paired
            if row["training_seed"] == seed
        ])
        for seed in plan["training_seeds"]
    }
    by_anchor = {
        anchor["name"]: summary(
            [
                row["score_delta"]
                for row in paired
                if row["anchor"] == anchor["name"]
            ]
        )
        for anchor in plan["anchors"]
    }
    by_orientation = {
        str(orientation): summary([
            row["score_delta"] for row in paired
            if row["orientation"] == orientation
        ])
        for orientation in plan["orientations"]
    }
    gates = plan["gates"]
    failures = []
    if aggregate["mean"] < gates["mean_score_delta_min"]:
        failures.append("mean_score_delta")
    if min(value["mean"] for value in by_training_seed.values()) < gates[
        "seed_mean_score_delta_min"
    ]:
        failures.append("seed_mean_score_delta")
    if min(value["mean"] for value in by_anchor.values()) < gates[
        "anchor_mean_score_delta_min"
    ]:
        failures.append("anchor_mean_score_delta")
    if min(value["mean"] for value in by_orientation.values()) < gates[
        "orientation_mean_score_delta_min"
    ]:
        failures.append("orientation_mean_score_delta")
    if aggregate["min"] < gates["cell_score_delta_min"]:
        failures.append("cell_score_delta")
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis": "paired_reward_learned_anchor_transfer",
        "directory": str(directory),
        "learned_transfer_manifest": {
            "path": str(plan_path),
            "sha256": sha256(plan_path),
        },
        "source_screen_complete_sha256": plan[
            "source_screen_complete_sha256"
        ],
        "reference_arm": reference,
        "candidate_arm": candidate,
        "cell_count": len(rows),
        "total_games": sum(row["games"] for row in rows),
        "runs": rows,
        "paired_candidate_minus_reference": {
            "cells": paired,
            "summary": aggregate,
            "by_training_seed": by_training_seed,
            "by_anchor": by_anchor,
            "by_orientation": by_orientation,
        },
        "gates": gates,
        "eligible_for_longer_confirmation": not failures,
        "gate_failures": failures,
        "warning": (
            "This is a deterministic fixed-stratum routing gate. Training "
            "seeds, anchors, and backend orientations are repeated strata, "
            "not independent replicates; no confidence interval or reward-"
            "promotion claim is made."
        ),
    }


def complete(directory: Path) -> None:
    analysis_path = directory / "ANALYSIS.json"
    report = analyze(directory)
    atomic_json(analysis_path, report)
    completion_path = directory / "LEARNED_TRANSFER_COMPLETE.json"
    core = {
        "schema_version": SCHEMA_VERSION,
        "learned_transfer_manifest_sha256": sha256(
            directory / "LEARNED_TRANSFER_MANIFEST.json"
        ),
        "analysis_sha256": sha256(analysis_path),
        "source_screen_complete_sha256": report[
            "source_screen_complete_sha256"
        ],
        "candidate_arm": report["candidate_arm"],
        "eligible_for_longer_confirmation": report[
            "eligible_for_longer_confirmation"
        ],
        "cells": [
            {"file": row["file"], "sha256": row["file_sha256"]}
            for row in report["runs"]
        ],
    }
    if completion_path.exists():
        recorded = load_object(completion_path, "learned-transfer completion")
        if {key: recorded.get(key) for key in core} != core:
            raise LearnedTransferError("existing learned-transfer completion is stale")
    else:
        atomic_json(completion_path, {**core, "completed_utc": utc_now()})


def validate_completion(
    complete_path: str | Path, *, expected_sha256: str | None = None
) -> dict[str, Any]:
    complete_path = Path(complete_path).expanduser().resolve()
    if expected_sha256 is not None and sha256(complete_path) != need_sha(
        expected_sha256, "expected learned-transfer completion SHA-256"
    ):
        raise LearnedTransferError("learned-transfer completion SHA-256 mismatch")
    complete_record = load_object(complete_path, "learned-transfer completion")
    if complete_record.get("schema_version") != SCHEMA_VERSION:
        raise LearnedTransferError("unsupported learned-transfer completion schema")
    directory = complete_path.parent
    report = analyze(directory)
    analysis_path = directory / "ANALYSIS.json"
    stored = load_object(analysis_path, "learned-transfer analysis")
    if stored != report:
        raise LearnedTransferError("stored learned-transfer analysis is stale")
    if sha256(analysis_path) != complete_record.get("analysis_sha256"):
        raise LearnedTransferError("learned-transfer analysis hash chain is invalid")
    manifest_path = directory / "LEARNED_TRANSFER_MANIFEST.json"
    if sha256(manifest_path) != complete_record.get(
        "learned_transfer_manifest_sha256"
    ):
        raise LearnedTransferError("learned-transfer manifest hash chain is invalid")
    if complete_record.get("candidate_arm") != report["candidate_arm"]:
        raise LearnedTransferError("learned-transfer candidate differs from analysis")
    if complete_record.get("eligible_for_longer_confirmation") != report[
        "eligible_for_longer_confirmation"
    ]:
        raise LearnedTransferError("learned-transfer eligibility differs from analysis")
    expected_cells = [
        {"file": row["file"], "sha256": row["file_sha256"]}
        for row in report["runs"]
    ]
    if complete_record.get("cells") != expected_cells:
        raise LearnedTransferError("learned-transfer completion cell chain is invalid")
    return report


def write_status(path: Path, state: str, completed: int, total: int, message: str) -> None:
    atomic_json(
        path,
        {
            "schema_version": SCHEMA_VERSION,
            "state": state,
            "completed_cells": completed,
            "total_cells": total,
            "message": message,
            "pid": os.getpid(),
            "updated_utc": utc_now(),
        },
    )


def run_matrix(root: Path, directory: Path, plan: dict[str, Any]) -> None:
    plan_path = directory / "LEARNED_TRANSFER_MANIFEST.json"
    cells = expected_cells(plan)
    status_path = directory / "LEARNED_TRANSFER_STATUS.json"
    completed_count = 0
    for expected in cells:
        cell_path = directory / expected["path"]
        if cell_path.exists():
            validate_cell(cell_path, plan, expected)
        else:
            write_status(
                status_path,
                "running",
                completed_count,
                len(cells),
                (
                    f"running {expected['arm']}/seed {expected['training_seed']}/"
                    f"{expected['anchor']}/orientation {expected['orientation']}"
                ),
            )
            command = [
                str(root / "vendor/PufferLib/.venv/bin/python"),
                str(Path(__file__).resolve()),
                "--run-cell",
                str(plan_path),
                str(cell_path),
            ]
            result = subprocess.run(
                command,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=3600,
            )
            if result.returncode != 0:
                raise LearnedTransferError(
                    f"learned-transfer cell exited {result.returncode}: "
                    f"{cell_path}\n{result.stdout[-4000:]}"
                )
            validate_cell(cell_path, plan, expected)
        completed_count += 1
        write_status(
            status_path,
            "running",
            completed_count,
            len(cells),
            "cell validated",
        )
    complete(directory)
    write_status(
        status_path,
        "complete",
        len(cells),
        len(cells),
        "learned-anchor matrix complete and validated",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen-complete", type=Path)
    parser.add_argument("--anchor-config", type=Path)
    parser.add_argument("--out-dir", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--validate-complete", type=Path)
    parser.add_argument("--expected-complete-sha256")
    parser.add_argument("--run-cell", nargs=2, metavar=("PLAN", "CELL"))
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parents[1]
        if args.run_cell:
            if any(
                value is not None
                for value in (
                    args.screen_complete,
                    args.anchor_config,
                    args.out_dir,
                    args.validate_complete,
                )
            ) or args.plan_only or args.expected_complete_sha256:
                raise LearnedTransferError("--run-cell cannot be combined")
            return run_cell(root, Path(args.run_cell[0]), Path(args.run_cell[1]))
        if args.validate_complete:
            if any(
                value is not None
                for value in (
                    args.screen_complete,
                    args.anchor_config,
                    args.out_dir,
                )
            ) or args.plan_only:
                raise LearnedTransferError("--validate-complete cannot be combined")
            report = validate_completion(
                args.validate_complete,
                expected_sha256=args.expected_complete_sha256,
            )
            print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
            return 0
        if not args.screen_complete or not args.anchor_config or not args.out_dir:
            parser.error(
                "--screen-complete, --anchor-config, and --out-dir are required"
            )
        complete_path = args.screen_complete.expanduser().resolve()
        out_dir = args.out_dir.expanduser().resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
        lock_path = out_dir / ".learned-transfer.lock"
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise LearnedTransferError(
                    "another learned-transfer runner holds the lock"
                ) from exc
            with Path("/tmp/bloodbowl-rl-reward-ablation.lock").open("a+") as gpu_lock:
                try:
                    fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise LearnedTransferError(
                        "training/evaluation GPU lock is already held"
                    ) from exc
                screen_report, checkpoints, arms = screen_inputs(complete_path)
                anchor_config = validate_anchor_config(
                    args.anchor_config.expanduser().resolve()
                )
                plan = freeze_manifest(
                    out_dir / "LEARNED_TRANSFER_MANIFEST.json",
                    root,
                    complete_path,
                    screen_report,
                    checkpoints,
                    arms,
                    anchor_config,
                )
                if args.plan_only:
                    print(
                        "LEARNED TRANSFER PLAN VERIFIED: "
                        f"{out_dir / 'LEARNED_TRANSFER_MANIFEST.json'}"
                    )
                    return 0
                run_matrix(root, out_dir, plan)
                print(f"LEARNED TRANSFER COMPLETE: {out_dir}")
                return 0
    except (
        OSError,
        subprocess.TimeoutExpired,
        LearnedTransferError,
        analyze_reward_screen.AnalysisError,
        run_reward_candidate_transfer.RunnerError,
        ValueError,
    ) as exc:
        print(f"learned-transfer runner failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
