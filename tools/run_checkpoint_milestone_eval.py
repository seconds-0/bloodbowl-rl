#!/usr/bin/env python3
"""Freeze, run, and verify a long-horizon checkpoint milestone matrix.

This is a post-run evaluator for an accepted ``control-final`` reward screen.
It resolves predeclared target steps to exact native checkpoints, hashes every
input, and evaluates each seed/milestone against fixed learned anchors in both
native backend roles.  It never changes a reward, training queue, checkpoint,
or production default.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import itertools
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
CONTROL_SEEDS = (42, 43, 44)
FIXED_TARGET_STEPS = (
    0,
    1_000_000_000,
    2_000_000_000,
    4_000_000_000,
    6_000_000_000,
    8_000_000_000,
    10_000_000_000,
    12_000_000_000,
)
FIXED_MAX_TARGET_GAP_STEPS = 50_000_000
FIXED_GAMES_PER_CELL = 2_048
FIXED_ANCHOR_SHA256 = {
    "statmatch1": "85315d26a40f26a387ef28742b7f3306583ca73b488aae01e06c72566f5ab435",
    "league7b": "2bf0815f506ac98e4972744903164673d40bee27b0b0c9197268b4c094fcdec1",
    "exploiter1": "6373cfa349bab8eee133933d42b353e796d2693e4e85b5a285c999647b11771a",
    "gen1": "62f6fcbc111e3b319ac0158358f0211e8aaf460c88f49eee86ff4639a148945a",
}
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
SHA_PATTERN = re.compile(r"[0-9a-f]{64}")
SPEC_KEYS = {
    "schema_version",
    "matrix_id",
    "root",
    "out_dir",
    "screen_complete",
    "screen_complete_sha256",
    "target_steps",
    "max_target_gap_steps",
    "games_per_cell",
    "anchors",
    "orientations",
}


class MilestoneEvalError(ValueError):
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
    temporary = destination.with_suffix(destination.suffix + f".tmp.{os.getpid()}")
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
        raise MilestoneEvalError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MilestoneEvalError(f"{label} must be a JSON object: {path}")
    return value


def need_sha(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA_PATTERN.fullmatch(value) is None:
        raise MilestoneEvalError(f"{label} must be a lowercase SHA-256")
    return value


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise MilestoneEvalError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise MilestoneEvalError(f"{label} must be finite")
    return result


def positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise MilestoneEvalError(f"{label} must be a positive integer")
    return value


def absolute_file(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise MilestoneEvalError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise MilestoneEvalError(f"missing {label}: {path}")
    return path


def under_root(path: Path, root: Path, label: str) -> Path:
    path = path.expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise MilestoneEvalError(f"{label} escapes root {root}: {path}") from exc
    return path


def validate_spec(path: Path) -> dict[str, Any]:
    raw = load_object(path, "milestone spec")
    if set(raw) != SPEC_KEYS:
        raise MilestoneEvalError(
            "milestone spec fields differ; "
            f"unknown={sorted(set(raw) - SPEC_KEYS)}, "
            f"missing={sorted(SPEC_KEYS - set(raw))}"
        )
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise MilestoneEvalError("unsupported milestone spec schema")
    matrix_id = raw.get("matrix_id")
    if not isinstance(matrix_id, str) or NAME_PATTERN.fullmatch(matrix_id) is None:
        raise MilestoneEvalError("matrix_id has unsupported characters")
    root_value = raw.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise MilestoneEvalError("root must be an absolute path")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise MilestoneEvalError(f"root is missing: {root}")
    if root != Path(__file__).resolve().parents[1]:
        raise MilestoneEvalError("spec root differs from the runner checkout")
    out_value = raw.get("out_dir")
    if not isinstance(out_value, str) or not Path(out_value).is_absolute():
        raise MilestoneEvalError("out_dir must be an absolute path")
    out_dir = under_root(Path(out_value), root, "out_dir")
    screen_complete = under_root(
        absolute_file(raw.get("screen_complete"), "screen completion"),
        root,
        "screen completion",
    )
    if screen_complete.name != "SCREEN_COMPLETE.json":
        raise MilestoneEvalError("screen completion must be SCREEN_COMPLETE.json")
    try:
        out_dir.relative_to(screen_complete.parent)
    except ValueError:
        try:
            screen_complete.parent.relative_to(out_dir)
        except ValueError:
            pass
        else:
            raise MilestoneEvalError(
                "out_dir must not contain the source screen artifact tree"
            )
    else:
        raise MilestoneEvalError(
            "out_dir must be separate from the source screen artifact tree"
        )
    if out_dir == root:
        raise MilestoneEvalError("out_dir cannot be the checkout root")
    expected_screen_sha = need_sha(
        raw.get("screen_complete_sha256"), "screen completion SHA-256"
    )
    if sha256(screen_complete) != expected_screen_sha:
        raise MilestoneEvalError("screen completion SHA-256 drift")
    targets = raw.get("target_steps")
    if (
        not isinstance(targets, list)
        or not targets
        or any(isinstance(v, bool) or not isinstance(v, int) or v < 0 for v in targets)
        or targets != sorted(set(targets))
        or targets[0] != 0
    ):
        raise MilestoneEvalError(
            "target_steps must be unique increasing nonnegative integers starting at 0"
        )
    if tuple(targets) != FIXED_TARGET_STEPS:
        raise MilestoneEvalError(
            "target_steps differ from the predeclared 0/1/2/4/6/8/10/12B protocol"
        )
    max_gap = positive_int(raw.get("max_target_gap_steps"), "max_target_gap_steps")
    if max_gap != FIXED_MAX_TARGET_GAP_STEPS:
        raise MilestoneEvalError(
            f"max_target_gap_steps must be {FIXED_MAX_TARGET_GAP_STEPS}"
        )
    games = positive_int(raw.get("games_per_cell"), "games_per_cell")
    if games != FIXED_GAMES_PER_CELL:
        raise MilestoneEvalError(
            f"games_per_cell must be the predeclared {FIXED_GAMES_PER_CELL}"
        )
    orientations = raw.get("orientations")
    if orientations != [0, 1]:
        raise MilestoneEvalError("orientations must be exactly [0, 1]")
    anchors_raw = raw.get("anchors")
    if not isinstance(anchors_raw, list) or len(anchors_raw) != len(
        FIXED_ANCHOR_SHA256
    ):
        raise MilestoneEvalError("the exact four predeclared anchors are required")
    anchors = []
    names: set[str] = set()
    hashes: set[str] = set()
    for index, record in enumerate(anchors_raw, 1):
        if not isinstance(record, dict) or set(record) != {
            "name",
            "path",
            "bytes",
            "sha256",
        }:
            raise MilestoneEvalError(
                f"anchor {index} must contain name/path/bytes/sha256"
            )
        name = record.get("name")
        if not isinstance(name, str) or NAME_PATTERN.fullmatch(name) is None:
            raise MilestoneEvalError(f"anchor {index} has an invalid name")
        if name in names:
            raise MilestoneEvalError(f"duplicate anchor name: {name}")
        names.add(name)
        anchor = under_root(
            absolute_file(record.get("path"), f"anchor {name}"), root, f"anchor {name}"
        )
        size = positive_int(record.get("bytes"), f"anchor {name} bytes")
        if size != EXPECTED_NATIVE_BYTES or anchor.stat().st_size != size:
            raise MilestoneEvalError(f"anchor {name} architecture/size drift")
        expected = need_sha(record.get("sha256"), f"anchor {name} SHA-256")
        if sha256(anchor) != expected:
            raise MilestoneEvalError(f"anchor {name} SHA-256 drift")
        if expected in hashes:
            raise MilestoneEvalError(f"anchor {name} duplicates another checkpoint")
        hashes.add(expected)
        anchors.append(
            {"name": name, "path": str(anchor), "bytes": size, "sha256": expected}
        )
    observed_anchors = {record["name"]: record["sha256"] for record in anchors}
    if observed_anchors != FIXED_ANCHOR_SHA256:
        raise MilestoneEvalError(
            "anchor names/hashes differ from the predeclared transfer set"
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "matrix_id": matrix_id,
        "root": str(root),
        "out_dir": str(out_dir),
        "screen_complete": str(screen_complete),
        "screen_complete_sha256": expected_screen_sha,
        "target_steps": targets,
        "max_target_gap_steps": max_gap,
        "games_per_cell": games,
        "anchors": anchors,
        "orientations": orientations,
        "spec_path": str(path.resolve()),
        "spec_sha256": sha256(path),
    }


def checkpoint_files(run_dir: Path) -> list[tuple[int, Path]]:
    rows = []
    for path in run_dir.glob("*.bin"):
        if path.stem.isdigit():
            rows.append((int(path.stem), path.resolve()))
    rows.sort()
    if not rows:
        raise MilestoneEvalError(f"run has no native checkpoints: {run_dir}")
    if len({step for step, _ in rows}) != len(rows):
        raise MilestoneEvalError(f"run has duplicate embedded steps: {run_dir}")
    return rows


def resolve_target(
    rows: list[tuple[int, Path]], target: int, max_gap: int
) -> tuple[int, Path]:
    eligible = [row for row in rows if row[0] <= target]
    if not eligible:
        raise MilestoneEvalError(f"no checkpoint exists at or before {target}")
    step, path = eligible[-1]
    if target - step > max_gap:
        raise MilestoneEvalError(
            f"checkpoint gap exceeds contract at target {target}: {target - step}"
        )
    return step, path


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
        raise MilestoneEvalError(f"native module probe failed: {probe.stdout[-2000:]}")
    lines = [line.strip() for line in probe.stdout.splitlines() if line.strip()]
    if len(lines) != 2:
        raise MilestoneEvalError(f"unexpected native module probe: {probe.stdout!r}")
    module = Path(lines[0]).resolve()
    try:
        env_name, gpu, precision = lines[1].split()
    except ValueError as exc:
        raise MilestoneEvalError(f"unexpected native probe fields: {lines[1]}") from exc
    if (env_name, gpu, precision) != ("bloodbowl", "1", "4"):
        raise MilestoneEvalError(
            f"milestone eval requires bloodbowl GPU fp32; got {lines[1]}"
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
        "tree_hasher": root / "tools/run_reward_candidate_transfer.py",
    }
    for label, path in files.items():
        if not path.is_file():
            raise MilestoneEvalError(f"missing implementation file {label}: {path}")
    config_tree = root / "vendor/PufferLib/config"
    return {
        "env_name": env_name,
        "gpu": int(gpu),
        "precision_bytes": int(precision),
        "config_tree_path": str(config_tree.resolve()),
        "config_tree_sha256": run_reward_candidate_transfer.tree_sha256(config_tree),
        **{f"{key}_path": str(path) for key, path in files.items()},
        **{f"{key}_sha256": sha256(path) for key, path in files.items()},
    }


def source_screen(spec: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    complete = Path(spec["screen_complete"])
    directory = complete.parent
    completion = load_object(complete, "screen completion")
    manifest_sha = need_sha(
        completion.get("screen_manifest_sha256"),
        "screen completion manifest SHA-256",
    )
    report = analyze_reward_screen.analyze_screen(
        directory,
        analyze_reward_screen.DEFAULT_METRICS,
        expected_screen_sha=manifest_sha,
    )
    if report["screen"]["profile"] != "control-final":
        raise MilestoneEvalError("milestone eval requires a control-final screen")
    proof = report["screen"]["completion"]
    if (
        not proof.get("present")
        or proof.get("sha256") != spec["screen_complete_sha256"]
    ):
        raise MilestoneEvalError("screen completion evidence is not exact")
    manifest_path = directory / "SCREEN_MANIFEST.json"
    manifest = load_object(manifest_path, "screen manifest")
    if sha256(manifest_path) != manifest_sha:
        raise MilestoneEvalError("screen manifest SHA-256 drift")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise MilestoneEvalError("screen manifest has no contract")
    schedule = contract.get("schedule")
    expected_schedule = [
        {"index": index + 1, "arm": "both", "seed": seed}
        for index, seed in enumerate(CONTROL_SEEDS)
    ]
    if schedule != expected_schedule:
        raise MilestoneEvalError("control-final screen schedule is not seeds 42/43/44")
    if spec["target_steps"][-1] != int(contract.get("requested_steps", -1)):
        raise MilestoneEvalError("last target must equal screen requested_steps")
    return report, manifest


def resolve_checkpoints(
    spec: dict[str, Any], report: dict[str, Any], manifest: dict[str, Any]
) -> dict[str, list[dict[str, Any]]]:
    root = Path(spec["root"])
    directory = Path(spec["screen_complete"]).parent
    prefix = report["screen"]["prefix"]
    warm_record = manifest["contract"].get("warm")
    if not isinstance(warm_record, dict):
        raise MilestoneEvalError("screen manifest has no warm checkpoint identity")
    warm = under_root(
        absolute_file(warm_record.get("path"), "warm checkpoint"),
        root,
        "warm checkpoint",
    )
    if warm.stat().st_size != EXPECTED_NATIVE_BYTES:
        raise MilestoneEvalError("warm checkpoint architecture/size drift")
    warm_sha = need_sha(warm_record.get("sha256"), "warm checkpoint SHA-256")
    if sha256(warm) != warm_sha:
        raise MilestoneEvalError("warm checkpoint SHA-256 drift")
    checkpoints: dict[str, list[dict[str, Any]]] = {}
    for seed in CONTROL_SEEDS:
        result_path = directory / f"{prefix}-both-s{seed}.result.json"
        result = load_object(result_path, f"screen result seed {seed}")
        if result.get("acceptance_pass") is not True or result.get("seed") != seed:
            raise MilestoneEvalError(f"seed {seed} result is not accepted/exact")
        final_path = under_root(
            absolute_file(result.get("checkpoint"), f"seed {seed} final"),
            root,
            f"seed {seed} final",
        )
        if final_path.stat().st_size != EXPECTED_NATIVE_BYTES:
            raise MilestoneEvalError(f"seed {seed} final checkpoint size drift")
        final_sha = need_sha(
            result.get("checkpoint_sha256"), f"seed {seed} final SHA-256"
        )
        if sha256(final_path) != final_sha:
            raise MilestoneEvalError(f"seed {seed} final checkpoint SHA-256 drift")
        if not final_path.stem.isdigit():
            raise MilestoneEvalError(
                f"seed {seed} final checkpoint has no embedded step"
            )
        final_embedded = int(final_path.stem)
        final_target = spec["target_steps"][-1]
        if (
            final_embedded > final_target
            or final_target - final_embedded > spec["max_target_gap_steps"]
        ):
            raise MilestoneEvalError(
                f"seed {seed} final checkpoint misses the target-step contract"
            )
        run_dir = under_root(final_path.parent, root, f"seed {seed} run directory")
        run_manifest = run_dir / "RUN_MANIFEST.json"
        if not run_manifest.is_file():
            raise MilestoneEvalError(f"seed {seed} run manifest is missing")
        if sha256(run_manifest) != result.get("run_manifest_sha256"):
            raise MilestoneEvalError(f"seed {seed} run manifest SHA-256 drift")
        rows = checkpoint_files(run_dir)
        records = [
            {
                "target_steps": 0,
                "embedded_steps": 0,
                "native": str(warm),
                "native_bytes": warm.stat().st_size,
                "native_sha256": warm_sha,
                "source": "warm",
            }
        ]
        for target in spec["target_steps"][1:-1]:
            embedded, checkpoint = resolve_target(
                rows, target, spec["max_target_gap_steps"]
            )
            if checkpoint.stat().st_size != EXPECTED_NATIVE_BYTES:
                raise MilestoneEvalError(
                    f"seed {seed} target {target} checkpoint size drift"
                )
            records.append(
                {
                    "target_steps": target,
                    "embedded_steps": embedded,
                    "native": str(checkpoint),
                    "native_bytes": checkpoint.stat().st_size,
                    "native_sha256": sha256(checkpoint),
                    "source": "interval",
                }
            )
        records.append(
            {
                "target_steps": spec["target_steps"][-1],
                "embedded_steps": final_embedded,
                "native": str(final_path),
                "native_bytes": final_path.stat().st_size,
                "native_sha256": final_sha,
                "source": "accepted_final",
            }
        )
        for record in records:
            record.update(
                {
                    "training_seed": seed,
                    "screen_result": str(result_path.resolve()),
                    "screen_result_sha256": sha256(result_path),
                    "run_manifest": str(run_manifest.resolve()),
                    "run_manifest_sha256": sha256(run_manifest),
                }
            )
        checkpoints[str(seed)] = records
    return checkpoints


def freeze_manifest(spec: dict[str, Any]) -> dict[str, Any]:
    report, screen_manifest = source_screen(spec)
    root = Path(spec["root"])
    checkpoints = resolve_checkpoints(spec, report, screen_manifest)
    focal_hashes = {
        record["native_sha256"]
        for seed_records in checkpoints.values()
        for record in seed_records
    }
    overlap = sorted(
        anchor["name"] for anchor in spec["anchors"] if anchor["sha256"] in focal_hashes
    )
    if overlap:
        raise MilestoneEvalError(
            "transfer anchors duplicate a warm/milestone checkpoint: "
            + ", ".join(overlap)
        )
    core = {
        "schema_version": SCHEMA_VERSION,
        "matrix_id": spec["matrix_id"],
        "root": spec["root"],
        "spec": spec["spec_path"],
        "spec_sha256": spec["spec_sha256"],
        "screen_complete": spec["screen_complete"],
        "screen_complete_sha256": spec["screen_complete_sha256"],
        "screen_manifest": str(
            (Path(spec["screen_complete"]).parent / "SCREEN_MANIFEST.json").resolve()
        ),
        "screen_manifest_sha256": report["screen"]["manifest_sha256"],
        "profile": "control-final",
        "training_seeds": list(CONTROL_SEEDS),
        "target_steps": spec["target_steps"],
        "max_target_gap_steps": spec["max_target_gap_steps"],
        "games_per_cell": spec["games_per_cell"],
        "orientations": spec["orientations"],
        "anchors": spec["anchors"],
        "checkpoints": checkpoints,
        "implementation": implementation_identity(root),
    }
    out_dir = Path(spec["out_dir"])
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "MILESTONE_EVAL_MANIFEST.json"
    if path.exists():
        recorded = load_object(path, "milestone manifest")
        if {key: recorded.get(key) for key in core} != core:
            raise MilestoneEvalError(
                "existing milestone manifest differs from recomputed plan"
            )
        return recorded
    payload = {**core, "created_utc": utc_now()}
    atomic_json(path, payload)
    return payload


def checkpoint_record(plan: dict[str, Any], seed: int, target: int) -> dict[str, Any]:
    matches = [
        row for row in plan["checkpoints"][str(seed)] if row["target_steps"] == target
    ]
    if len(matches) != 1:
        raise MilestoneEvalError(f"missing/duplicate seed {seed} target {target}")
    return matches[0]


def validate_plan_contract(plan: dict[str, Any]) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise MilestoneEvalError("unsupported milestone manifest schema")
    if plan.get("profile") != "control-final":
        raise MilestoneEvalError("milestone manifest is not control-final")
    if plan.get("training_seeds") != list(CONTROL_SEEDS):
        raise MilestoneEvalError("milestone manifest seeds differ from 42/43/44")
    if tuple(plan.get("target_steps", ())) != FIXED_TARGET_STEPS:
        raise MilestoneEvalError("milestone manifest target steps drifted")
    if plan.get("max_target_gap_steps") != FIXED_MAX_TARGET_GAP_STEPS:
        raise MilestoneEvalError("milestone manifest target-gap contract drifted")
    if plan.get("games_per_cell") != FIXED_GAMES_PER_CELL:
        raise MilestoneEvalError("milestone manifest game count drifted")
    if plan.get("orientations") != [0, 1]:
        raise MilestoneEvalError("milestone manifest orientations drifted")
    anchors = plan.get("anchors")
    if (
        not isinstance(anchors, list)
        or {
            record.get("name"): record.get("sha256")
            for record in anchors
            if isinstance(record, dict)
        }
        != FIXED_ANCHOR_SHA256
    ):
        raise MilestoneEvalError("milestone manifest anchor contract drifted")
    checkpoints = plan.get("checkpoints")
    if not isinstance(checkpoints, dict) or set(checkpoints) != {
        str(seed) for seed in CONTROL_SEEDS
    }:
        raise MilestoneEvalError("milestone manifest checkpoint seeds are incomplete")
    for seed in CONTROL_SEEDS:
        records = checkpoints[str(seed)]
        if not isinstance(records, list) or [
            record.get("target_steps") for record in records if isinstance(record, dict)
        ] != list(FIXED_TARGET_STEPS):
            raise MilestoneEvalError(
                f"milestone manifest seed {seed} targets are incomplete"
            )


def cell_filename(seed: int, target: int, anchor: str, orientation: int) -> str:
    return f"s{seed}-t{target:012d}-{anchor}-o{orientation}.json"


def expected_cells(plan: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for seed_index, seed in enumerate(plan["training_seeds"]):
        for target in plan["target_steps"]:
            for anchor_index, anchor in enumerate(plan["anchors"]):
                for orientation in plan["orientations"]:
                    rows.append(
                        {
                            "training_seed": seed,
                            "target_steps": target,
                            "anchor": anchor["name"],
                            "orientation": orientation,
                            # Common across milestones in the same stratum.
                            "match_seed": (
                                30_000
                                + seed_index * 1_000
                                + anchor_index * 10
                                + orientation
                            ),
                            "path": cell_filename(
                                seed, target, anchor["name"], orientation
                            ),
                        }
                    )
    return rows


def validate_cell(
    path: Path, plan: dict[str, Any], expected: dict[str, Any]
) -> dict[str, Any]:
    cell = load_object(path, "milestone cell")
    if cell.get("schema_version") != SCHEMA_VERSION:
        raise MilestoneEvalError(f"unsupported cell schema: {path.name}")
    identity = {
        "training_seed": expected["training_seed"],
        "target_steps": expected["target_steps"],
        "anchor": expected["anchor"],
        "orientation": expected["orientation"],
        "match_seed": expected["match_seed"],
        "games_requested": plan["games_per_cell"],
        "milestone_eval_manifest_sha256": sha256(
            path.parent / "MILESTONE_EVAL_MANIFEST.json"
        ),
    }
    for key, value in identity.items():
        if cell.get(key) != value:
            raise MilestoneEvalError(
                f"{path.name} {key}={cell.get(key)!r}, expected {value!r}"
            )
    if cell.get("implementation") != plan.get("implementation"):
        raise MilestoneEvalError(f"{path.name} implementation identity drift")
    checkpoint = checkpoint_record(
        plan, expected["training_seed"], expected["target_steps"]
    )
    anchor = next(x for x in plan["anchors"] if x["name"] == expected["anchor"])
    if cell.get("focal_checkpoint_sha256") != checkpoint["native_sha256"]:
        raise MilestoneEvalError(f"{path.name} focal checkpoint drift")
    if cell.get("anchor_checkpoint_sha256") != anchor["sha256"]:
        raise MilestoneEvalError(f"{path.name} anchor checkpoint drift")
    games = finite(cell.get("games"), f"{path.name} games")
    if games < plan["games_per_cell"]:
        raise MilestoneEvalError(f"{path.name} completed too few games")
    focal = finite(cell.get("focal_score"), f"{path.name} focal score")
    opponent = finite(cell.get("opponent_score"), f"{path.name} opponent score")
    draw = finite(cell.get("draw_rate"), f"{path.name} draw rate")
    focal_win = finite(cell.get("focal_win_rate"), f"{path.name} focal win rate")
    focal_loss = finite(cell.get("focal_loss_rate"), f"{path.name} focal loss rate")
    focal_tds = finite(cell.get("focal_tds"), f"{path.name} focal TDs")
    opponent_tds = finite(cell.get("opponent_tds"), f"{path.name} opponent TDs")
    if min(focal, opponent, draw) < -1e-6 or max(focal, opponent, draw) > 1 + 1e-6:
        raise MilestoneEvalError(f"{path.name} contains impossible rates")
    if abs(focal + opponent - 1.0) > 2e-4:
        raise MilestoneEvalError(f"{path.name} slot scores do not sum to one")
    if (
        abs(focal_win - (focal - 0.5 * draw)) > 2e-4
        or abs(focal_loss - (opponent - 0.5 * draw)) > 2e-4
        or min(focal_win, focal_loss) < -1e-6
    ):
        raise MilestoneEvalError(f"{path.name} contains inconsistent W/D/L rates")
    if focal_tds < 0 or opponent_tds < 0:
        raise MilestoneEvalError(f"{path.name} contains impossible TD rates")
    integrity = cell.get("integrity")
    if not isinstance(integrity, dict) or set(integrity) != set(INTEGRITY_KEYS):
        raise MilestoneEvalError(f"{path.name} integrity fields are incomplete")
    parsed_integrity = {
        key: finite(value, f"{path.name} integrity.{key}")
        for key, value in integrity.items()
    }
    bad = {key: value for key, value in parsed_integrity.items() if value != 0.0}
    if bad:
        raise MilestoneEvalError(f"{path.name} integrity counters nonzero: {bad}")
    return {
        **identity,
        "embedded_steps": checkpoint["embedded_steps"],
        "games": games,
        "focal_score": focal,
        "opponent_score": opponent,
        "draw_rate": draw,
        "focal_win_rate": focal_win,
        "focal_loss_rate": focal_loss,
        "focal_tds": focal_tds,
        "opponent_tds": opponent_tds,
        "focal_checkpoint_sha256": checkpoint["native_sha256"],
        "anchor_checkpoint_sha256": anchor["sha256"],
        "file": path.name,
        "file_sha256": sha256(path),
    }


def verify_implementation(plan: dict[str, Any]) -> None:
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
        "tree_hasher",
    ):
        path = Path(implementation[f"{key}_path"])
        if not path.is_file() or sha256(path) != implementation[f"{key}_sha256"]:
            raise MilestoneEvalError(f"implementation drift before cell: {key}")
    config_tree = Path(implementation["config_tree_path"])
    if (
        not config_tree.is_dir()
        or run_reward_candidate_transfer.tree_sha256(config_tree)
        != implementation["config_tree_sha256"]
    ):
        raise MilestoneEvalError("implementation drift before cell: config_tree")


def verify_file_identity(path_value: Any, expected: Any, label: str) -> Path:
    path = absolute_file(path_value, label)
    if sha256(path) != need_sha(expected, f"{label} SHA-256"):
        raise MilestoneEvalError(f"{label} SHA-256 drift")
    return path


def verify_plan_sources(
    plan: dict[str, Any], expected: dict[str, Any] | None = None
) -> None:
    validate_plan_contract(plan)
    verify_file_identity(plan.get("spec"), plan.get("spec_sha256"), "milestone spec")
    verify_file_identity(
        plan.get("screen_complete"),
        plan.get("screen_complete_sha256"),
        "source screen completion",
    )
    verify_file_identity(
        plan.get("screen_manifest"),
        plan.get("screen_manifest_sha256"),
        "source screen manifest",
    )
    seeds = (
        [expected["training_seed"]]
        if expected is not None
        else list(plan["training_seeds"])
    )
    targets = (
        [expected["target_steps"]]
        if expected is not None
        else list(plan["target_steps"])
    )
    for seed in seeds:
        for target in targets:
            checkpoint = checkpoint_record(plan, seed, target)
            verify_file_identity(
                checkpoint.get("screen_result"),
                checkpoint.get("screen_result_sha256"),
                f"seed {seed} screen result",
            )
            verify_file_identity(
                checkpoint.get("run_manifest"),
                checkpoint.get("run_manifest_sha256"),
                f"seed {seed} run manifest",
            )
            verify_file_identity(
                checkpoint.get("native"),
                checkpoint.get("native_sha256"),
                f"seed {seed} target {target} checkpoint",
            )
    anchor_names = (
        [expected["anchor"]]
        if expected is not None
        else [record["name"] for record in plan["anchors"]]
    )
    for name in anchor_names:
        anchor = next(record for record in plan["anchors"] if record["name"] == name)
        verify_file_identity(anchor.get("path"), anchor.get("sha256"), f"anchor {name}")
    verify_implementation(plan)


def require_idle_gpu() -> None:
    result = subprocess.run(
        [
            "nvidia-smi",
            "--query-compute-apps=pid,process_name",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=15,
    )
    if result.returncode != 0:
        raise MilestoneEvalError(
            f"cannot prove an idle evaluation GPU: {result.stdout[-1000:]}"
        )
    owners = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if owners:
        raise MilestoneEvalError(
            "evaluation GPU is not exclusive; existing compute owners: "
            + "; ".join(owners)
        )
    viewer = subprocess.run(
        ["pgrep", "-af", "[f]ollow_latest.py"],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
        timeout=10,
    )
    if viewer.returncode not in (0, 1):
        raise MilestoneEvalError(
            f"cannot prove BBTV is quiescent: {viewer.stdout[-1000:]}"
        )
    viewer_owners = [
        line.strip() for line in viewer.stdout.splitlines() if line.strip()
    ]
    if viewer_owners:
        raise MilestoneEvalError(
            "BBTV follower is active; pause it explicitly before evaluation: "
            + "; ".join(viewer_owners)
        )


def run_cell(root: Path, plan_path: Path, cell_path: Path) -> int:
    plan = load_object(plan_path, "milestone manifest")
    validate_plan_contract(plan)
    expected = next(
        (row for row in expected_cells(plan) if row["path"] == cell_path.name), None
    )
    if expected is None:
        raise MilestoneEvalError(f"unplanned milestone cell: {cell_path}")
    verify_plan_sources(plan, expected)
    require_idle_gpu()
    checkpoint = checkpoint_record(
        plan, expected["training_seed"], expected["target_steps"]
    )
    anchor = next(x for x in plan["anchors"] if x["name"] == expected["anchor"])
    for record, path_key, hash_key, label in (
        (checkpoint, "native", "native_sha256", "focal"),
        (anchor, "path", "sha256", "anchor"),
    ):
        path = Path(record[path_key])
        if not path.is_file() or sha256(path) != record[hash_key]:
            raise MilestoneEvalError(f"{label} checkpoint drift before cell")
    sys.path.insert(0, str(root / "vendor/PufferLib"))
    from pufferlib import _C  # type: ignore
    from pufferlib import pufferl  # type: ignore

    implementation = plan["implementation"]
    imported = Path(_C.__file__).resolve()
    if (
        getattr(_C, "env_name", None) != "bloodbowl"
        or not bool(getattr(_C, "gpu", False))
        or int(_C.precision_bytes) != 4
        or imported != Path(implementation["compiled_module_path"]).resolve()
        or sha256(imported) != implementation["compiled_module_sha256"]
    ):
        raise MilestoneEvalError("cell imported the wrong native module")
    args = pufferl.load_config("bloodbowl")
    args["train"]["gpus"] = 1
    args["train"]["seed"] = expected["match_seed"]
    args["env"]["seed"] = expected["match_seed"]
    args["env"]["macro_moves"] = 0
    args["env"]["demo_reset_pct"] = 0.0
    args["env"]["scripted_opponent"] = 0
    args["env"]["exclude_team"] = -1
    args["env"]["force_home_team"] = -1
    args["env"]["force_away_team"] = -1
    args["vec"]["num_threads"] = 16
    focal_path = checkpoint["native"]
    anchor_path = anchor["path"]
    if expected["orientation"] == 0:
        policy_a, policy_b = focal_path, anchor_path
        focal_key, opponent_key = "env/slot_0_score", "env/slot_1_score"
        focal_tds_key, opponent_tds_key = "env/tds_t0", "env/tds_t1"
    else:
        policy_a, policy_b = anchor_path, focal_path
        focal_key, opponent_key = "env/slot_1_score", "env/slot_0_score"
        focal_tds_key, opponent_tds_key = "env/tds_t1", "env/tds_t0"
    logs = pufferl.match(
        env_name="bloodbowl",
        policy_a_path=policy_a,
        policy_b_path=policy_b,
        num_games=plan["games_per_cell"],
        args=args,
        verbose=False,
    )
    numeric = {
        key: finite(value, f"match log {key}")
        for key, value in logs.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
    }
    required = [
        "env/n",
        focal_key,
        opponent_key,
        "env/draw_rate",
        focal_tds_key,
        opponent_tds_key,
        *(f"env/{key}" for key in INTEGRITY_KEYS),
    ]
    missing = [key for key in required if key not in numeric]
    if missing:
        raise MilestoneEvalError(f"match omitted required keys: {missing}")
    if numeric["env/n"] < plan["games_per_cell"]:
        raise MilestoneEvalError("match returned too few completed games")
    integrity = {key: numeric[f"env/{key}"] for key in INTEGRITY_KEYS}
    bad = {key: value for key, value in integrity.items() if value != 0.0}
    if bad:
        raise MilestoneEvalError(f"match integrity counters nonzero: {bad}")
    atomic_json(
        cell_path,
        {
            "schema_version": SCHEMA_VERSION,
            "created_utc": utc_now(),
            "milestone_eval_manifest_sha256": sha256(plan_path),
            **{
                key: expected[key]
                for key in (
                    "training_seed",
                    "target_steps",
                    "anchor",
                    "orientation",
                    "match_seed",
                )
            },
            "embedded_steps": checkpoint["embedded_steps"],
            "games_requested": plan["games_per_cell"],
            "games": numeric["env/n"],
            "focal_score": numeric[focal_key],
            "opponent_score": numeric[opponent_key],
            "draw_rate": numeric["env/draw_rate"],
            "focal_win_rate": (numeric[focal_key] - 0.5 * numeric["env/draw_rate"]),
            "focal_loss_rate": (numeric[opponent_key] - 0.5 * numeric["env/draw_rate"]),
            "focal_tds": numeric[focal_tds_key],
            "opponent_tds": numeric[opponent_tds_key],
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
                for key, value in numeric.items()
                if key.startswith("env/")
            },
        },
    )
    validate_cell(cell_path, plan, expected)
    return 0


def mean(values: list[float]) -> float:
    if not values:
        raise MilestoneEvalError("cannot summarize an empty list")
    return statistics.fmean(values)


def percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise MilestoneEvalError("cannot take a percentile of an empty list")
    if not 0.0 <= probability <= 1.0:
        raise MilestoneEvalError("percentile probability is outside [0, 1]")
    position = (len(sorted_values) - 1) * probability
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return sorted_values[lower]
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def exact_cluster_bootstrap(values: list[float]) -> dict[str, Any]:
    """Exact ordinary bootstrap over the three declared seed strata."""
    if len(values) != len(CONTROL_SEEDS):
        raise MilestoneEvalError(
            f"cluster bootstrap requires exactly {len(CONTROL_SEEDS)} seed strata"
        )
    resampled = sorted(
        mean(list(sample)) for sample in itertools.product(values, repeat=len(values))
    )
    return {
        "mean": mean(values),
        "sample_sd": statistics.stdev(values),
        "lower_95": percentile(resampled, 0.025),
        "upper_95": percentile(resampled, 0.975),
        "clusters": len(values),
        "exact_resamples": len(resampled),
    }


def nominate(points: list[dict[str, Any]]) -> dict[str, Any]:
    trained = [point for point in points if point["target_steps"] > 0]
    best_score = max(point["macro_score"] for point in trained)
    for index, point in enumerate(trained):
        if point["macro_score"] < best_score - 0.01:
            continue
        later = trained[index + 1 : index + 3]
        if all(
            next_point["macro_score"] <= point["macro_score"] + 0.02
            for next_point in later
        ):
            return {
                "target_steps": point["target_steps"],
                "embedded_steps": point["embedded_steps"],
                "rule": "earliest_within_0.01_of_max_without_next_two_gt_0.02",
                "exploratory": False,
            }
    best = max(trained, key=lambda point: point["macro_score"])
    return {
        "target_steps": best["target_steps"],
        "embedded_steps": best["embedded_steps"],
        "rule": "highest_scoring_fallback",
        "exploratory": True,
    }


def analyze(directory: str | Path) -> dict[str, Any]:
    directory = Path(directory).expanduser().resolve()
    plan_path = directory / "MILESTONE_EVAL_MANIFEST.json"
    plan = load_object(plan_path, "milestone manifest")
    validate_plan_contract(plan)
    rows = [
        validate_cell(directory / expected["path"], plan, expected)
        for expected in expected_cells(plan)
    ]
    trajectories: dict[str, list[dict[str, Any]]] = {}
    nominations = {}
    for seed in plan["training_seeds"]:
        points = []
        for target in plan["target_steps"]:
            cells = [
                row
                for row in rows
                if row["training_seed"] == seed and row["target_steps"] == target
            ]
            checkpoint = checkpoint_record(plan, seed, target)
            point = {
                "target_steps": target,
                "embedded_steps": checkpoint["embedded_steps"],
                "macro_score": mean([row["focal_score"] for row in cells]),
                "macro_tds_for": mean([row["focal_tds"] for row in cells]),
                "macro_tds_against": mean([row["opponent_tds"] for row in cells]),
                "by_anchor": {
                    anchor["name"]: mean(
                        [
                            row["focal_score"]
                            for row in cells
                            if row["anchor"] == anchor["name"]
                        ]
                    )
                    for anchor in plan["anchors"]
                },
                "by_orientation": {
                    str(orientation): mean(
                        [
                            row["focal_score"]
                            for row in cells
                            if row["orientation"] == orientation
                        ]
                    )
                    for orientation in plan["orientations"]
                },
            }
            if points:
                point["score_delta_previous"] = (
                    point["macro_score"] - points[-1]["macro_score"]
                )
            points.append(point)
        warm = points[0]
        for point in points:
            point["score_delta_warm"] = point["macro_score"] - warm["macro_score"]
            point["tds_for_delta_warm"] = point["macro_tds_for"] - warm["macro_tds_for"]
            point["tds_against_delta_warm"] = (
                point["macro_tds_against"] - warm["macro_tds_against"]
            )
        trajectories[str(seed)] = points
        nominations[str(seed)] = nominate(points)
    aggregate_trajectory = []
    for index, target in enumerate(plan["target_steps"]):
        seed_points = [
            trajectories[str(seed)][index] for seed in plan["training_seeds"]
        ]
        aggregate_trajectory.append(
            {
                "target_steps": target,
                "embedded_steps_by_seed": {
                    str(seed): trajectories[str(seed)][index]["embedded_steps"]
                    for seed in plan["training_seeds"]
                },
                "score": exact_cluster_bootstrap(
                    [point["macro_score"] for point in seed_points]
                ),
                "score_delta_warm": exact_cluster_bootstrap(
                    [point["score_delta_warm"] for point in seed_points]
                ),
                "tds_for_delta_warm": exact_cluster_bootstrap(
                    [point["tds_for_delta_warm"] for point in seed_points]
                ),
                "tds_against_delta_warm": exact_cluster_bootstrap(
                    [point["tds_against_delta_warm"] for point in seed_points]
                ),
                "cluster_unit": (
                    "evaluation_seed_batch_for_shared_warm_policy"
                    if target == 0
                    else "training_seed"
                ),
            }
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis": "control_final_checkpoint_milestones",
        "directory": str(directory),
        "manifest": {"path": str(plan_path), "sha256": sha256(plan_path)},
        "screen_complete_sha256": plan["screen_complete_sha256"],
        "cell_count": len(rows),
        "total_games": sum(row["games"] for row in rows),
        "runs": rows,
        "trajectories": trajectories,
        "aggregate_trajectory": aggregate_trajectory,
        "stage_b_nominations": nominations,
        "warning": (
            "These anchors are unseen exact checkpoints but lineage-connected. "
            "The fixed nomination compresses Stage B evaluation; it is not a "
            "reward or production promotion gate. Exact ordinary bootstrap "
            "intervals use only three seed strata and must be read with the "
            "raw paired strata, not as high-powered confidence claims."
        ),
    }


def complete(directory: Path) -> None:
    report = analyze(directory)
    analysis_path = directory / "ANALYSIS.json"
    atomic_json(analysis_path, report)
    core = {
        "schema_version": SCHEMA_VERSION,
        "milestone_eval_manifest_sha256": sha256(
            directory / "MILESTONE_EVAL_MANIFEST.json"
        ),
        "analysis_sha256": sha256(analysis_path),
        "screen_complete_sha256": report["screen_complete_sha256"],
        "cells": [
            {"file": row["file"], "sha256": row["file_sha256"]}
            for row in report["runs"]
        ],
    }
    completion_path = directory / "MILESTONE_EVAL_COMPLETE.json"
    if completion_path.exists():
        recorded = load_object(completion_path, "milestone completion")
        if {key: recorded.get(key) for key in core} != core:
            raise MilestoneEvalError("existing milestone completion is stale")
    else:
        atomic_json(completion_path, {**core, "completed_utc": utc_now()})


def validate_completion(
    path: str | Path, expected_sha256: str | None = None
) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    if path.name != "MILESTONE_EVAL_COMPLETE.json":
        raise MilestoneEvalError(
            "completion must be named MILESTONE_EVAL_COMPLETE.json"
        )
    if expected_sha256 is not None and sha256(path) != need_sha(
        expected_sha256, "expected milestone completion SHA-256"
    ):
        raise MilestoneEvalError("milestone completion SHA-256 mismatch")
    completion = load_object(path, "milestone completion")
    if completion.get("schema_version") != SCHEMA_VERSION:
        raise MilestoneEvalError("unsupported milestone completion schema")
    directory = path.parent
    plan = load_object(directory / "MILESTONE_EVAL_MANIFEST.json", "milestone manifest")
    verify_plan_sources(plan)
    report = analyze(directory)
    stored = load_object(directory / "ANALYSIS.json", "milestone analysis")
    if stored != report:
        raise MilestoneEvalError("stored milestone analysis is stale")
    if sha256(directory / "ANALYSIS.json") != completion.get("analysis_sha256"):
        raise MilestoneEvalError("milestone analysis hash chain is invalid")
    if sha256(directory / "MILESTONE_EVAL_MANIFEST.json") != completion.get(
        "milestone_eval_manifest_sha256"
    ):
        raise MilestoneEvalError("milestone manifest hash chain is invalid")
    if completion.get("screen_complete_sha256") != report["screen_complete_sha256"]:
        raise MilestoneEvalError("milestone source-screen hash chain is invalid")
    expected_cells_chain = [
        {"file": row["file"], "sha256": row["file_sha256"]} for row in report["runs"]
    ]
    if completion.get("cells") != expected_cells_chain:
        raise MilestoneEvalError("milestone completion cell chain is invalid")
    return report


def write_status(
    path: Path, state: str, completed: int, total: int, message: str
) -> None:
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
    plan_path = directory / "MILESTONE_EVAL_MANIFEST.json"
    cells = expected_cells(plan)
    status_path = directory / "MILESTONE_EVAL_STATUS.json"
    completed = 0
    for expected in cells:
        cell_path = directory / expected["path"]
        if cell_path.exists():
            validate_cell(cell_path, plan, expected)
        else:
            write_status(
                status_path,
                "running",
                completed,
                len(cells),
                (
                    f"running seed {expected['training_seed']} target "
                    f"{expected['target_steps']} anchor {expected['anchor']} "
                    f"orientation {expected['orientation']}"
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
                raise MilestoneEvalError(
                    f"milestone cell exited {result.returncode}: {cell_path}\n"
                    f"{result.stdout[-4000:]}"
                )
            validate_cell(cell_path, plan, expected)
        completed += 1
        write_status(status_path, "running", completed, len(cells), "cell validated")
    complete(directory)
    write_status(
        status_path,
        "complete",
        len(cells),
        len(cells),
        "milestone matrix complete and validated",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--spec", type=Path)
    parser.add_argument("--plan-only", action="store_true")
    parser.add_argument("--run-cell", nargs=2, metavar=("PLAN", "CELL"))
    parser.add_argument("--validate-complete", type=Path)
    parser.add_argument("--expected-complete-sha256")
    args = parser.parse_args(argv)
    try:
        root = Path(__file__).resolve().parents[1]
        if args.run_cell:
            if (
                args.spec
                or args.plan_only
                or args.validate_complete
                or args.expected_complete_sha256
            ):
                raise MilestoneEvalError("--run-cell cannot be combined")
            return run_cell(root, Path(args.run_cell[0]), Path(args.run_cell[1]))
        if args.validate_complete:
            if args.spec or args.plan_only:
                raise MilestoneEvalError("--validate-complete cannot be combined")
            report = validate_completion(
                args.validate_complete, args.expected_complete_sha256
            )
            print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
            return 0
        if args.expected_complete_sha256:
            raise MilestoneEvalError(
                "--expected-complete-sha256 requires --validate-complete"
            )
        if not args.spec:
            parser.error("--spec is required")
        spec = validate_spec(args.spec.expanduser().resolve())
        directory = Path(spec["out_dir"])
        directory.mkdir(parents=True, exist_ok=True)
        lock_path = directory / ".milestone-eval.lock"
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise MilestoneEvalError(
                    "another milestone evaluator holds the output lock"
                ) from exc
            with Path("/tmp/bloodbowl-rl-reward-ablation.lock").open("a+") as gpu_lock:
                try:
                    fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise MilestoneEvalError(
                        "training/evaluation GPU lock is already held"
                    ) from exc
                plan = freeze_manifest(spec)
                if args.plan_only:
                    print(
                        "MILESTONE EVAL PLAN VERIFIED: "
                        f"{directory / 'MILESTONE_EVAL_MANIFEST.json'}"
                    )
                    return 0
                run_matrix(root, directory, plan)
                print(f"MILESTONE EVAL COMPLETE: {directory}")
                return 0
    except (
        OSError,
        subprocess.TimeoutExpired,
        MilestoneEvalError,
        analyze_reward_screen.AnalysisError,
        ValueError,
    ) as exc:
        print(f"milestone evaluator failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
