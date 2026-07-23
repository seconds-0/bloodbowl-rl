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

if __package__:
    from .live_integrity_guard import HARD_INTEGRITY_KEYS
else:
    from live_integrity_guard import HARD_INTEGRITY_KEYS


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

PAIRED_CANDIDATES = ("possession_only", "gain_only", "neither")
PAIRED_FINAL_SEEDS = (42, 43, 44)
CONTROL_FINAL_SCHEDULE = (("both", 42), ("both", 43), ("both", 44))
EXACT_ACTION_CANARY_SCHEDULE = (("both", 42),)
EXACT_ACTION_CANARY_PREFIX = "exact-action-canary-50m-s42-v4"
EXACT_ACTION_CANARY_REQUESTED_STEPS = 50_000_000
EXACT_ACTION_CANARY_TOTAL_AGENTS = 2_048
EXACT_ACTION_CANARY_HORIZON = 64
EXACT_ACTION_CANARY_MINIBATCH_SIZE = 16_384
EXACT_ACTION_CANARY_ROLLOUT_QUANTUM = (
    EXACT_ACTION_CANARY_TOTAL_AGENTS * EXACT_ACTION_CANARY_HORIZON)
EXACT_ACTION_CANARY_FINAL_STEPS = (
    EXACT_ACTION_CANARY_REQUESTED_STEPS
    // EXACT_ACTION_CANARY_ROLLOUT_QUANTUM
    * EXACT_ACTION_CANARY_ROLLOUT_QUANTUM)
EXACT_ACTION_CANARY_CHECKPOINT_BYTES = 16_066_560
# The replacement candidate freezes the complete control registry live. The
# rejected a52fc6e2 manifest remains historical evidence with its narrower
# registry and is never relabeled or accepted by this replacement contract.
EXACT_ACTION_CANARY_MANIFEST_HARD_INTEGRITY_KEYS = HARD_INTEGRITY_KEYS

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
    if profile == "control-final":
        return {
            "profile": profile,
            "candidate_arm": "both",
            "schedule": CONTROL_FINAL_SCHEDULE,
            "seeds": PAIRED_FINAL_SEEDS,
            "reward_sha256": {
                "both": POSSESSION_GAIN_REWARD_SHA256["both"],
            },
            "factors": {"both": {"control": True}},
            "effect_definitions": {},
        }
    if profile == "exact-action-canary":
        return {
            "profile": profile,
            "candidate_arm": "both",
            "schedule": EXACT_ACTION_CANARY_SCHEDULE,
            "seeds": (42,),
            "reward_sha256": {
                "both": POSSESSION_GAIN_REWARD_SHA256["both"],
            },
            "factors": {"both": {"qualification": True}},
            "effect_definitions": {},
        }
    if profile in ("paired-confirmation", "paired-final"):
        candidate = contract.get("candidate_arm")
        if candidate not in PAIRED_CANDIDATES:
            raise AnalysisError(
                f"{profile} candidate_arm must be one of "
                + ", ".join(PAIRED_CANDIDATES)
            )
        return {
            "profile": profile,
            "candidate_arm": candidate,
            "schedule": (
                (
                    ("both", 42), (candidate, 42),
                    (candidate, 43), ("both", 43),
                )
                if profile == "paired-confirmation"
                else (
                    ("both", 42), (candidate, 42),
                    (candidate, 43), ("both", 43),
                    ("both", 44), (candidate, 44),
                )
            ),
            "seeds": (
                (42, 43)
                if profile == "paired-confirmation"
                else PAIRED_FINAL_SEEDS
            ),
            "reward_sha256": {
                arm: POSSESSION_GAIN_REWARD_SHA256[arm]
                for arm in ("both", candidate)
            },
            "factors": {
                "both": {"candidate": False},
                candidate: {"candidate": True},
            },
            "effect_definitions": {
                "candidate_minus_both": (
                    f"{candidate} - both; positive favors the simpler candidate"
                ),
            },
        }
    raise AnalysisError(f"unsupported reward-screen profile: {profile!r}")


def _validate_exact_action_canary_contract(contract: dict[str, Any]) -> None:
    if contract.get("qualification_only") is not True:
        raise AnalysisError(
            "exact-action-canary contract must be qualification_only")
    if contract.get("warm") is not None or contract.get("pool") is not None:
        raise AnalysisError("exact-action-canary contract must have null warm/pool")
    if contract.get("prefix") != EXACT_ACTION_CANARY_PREFIX:
        raise AnalysisError(
            "exact-action-canary prefix does not match the replacement authority"
        )

    requested_steps = _need_int(
        contract.get("requested_steps"), "exact-action-canary requested_steps")
    if requested_steps != EXACT_ACTION_CANARY_REQUESTED_STEPS:
        raise AnalysisError(
            "exact-action-canary requested_steps must equal 50000000")
    rollout_quantum = _need_int(
        contract.get("rollout_quantum"), "exact-action-canary rollout_quantum")
    if rollout_quantum != EXACT_ACTION_CANARY_ROLLOUT_QUANTUM:
        raise AnalysisError(
            "exact-action-canary rollout_quantum mismatch: "
            f"{rollout_quantum} != {EXACT_ACTION_CANARY_ROLLOUT_QUANTUM}")
    final_steps = _need_int(
        contract.get("final_steps"), "exact-action-canary final_steps")
    if final_steps != EXACT_ACTION_CANARY_FINAL_STEPS:
        raise AnalysisError(
            "exact-action-canary final_steps do not match the frozen "
            f"complete-rollout budget: {final_steps} != "
            f"{EXACT_ACTION_CANARY_FINAL_STEPS}")

    bootstrap = _need_mapping(
        contract.get("bootstrap"), "exact-action-canary bootstrap")
    expected_bootstrap = {
        "mode": "fresh-v5-qualification",
        "observation_abi": "obs-v5",
        "observation_version": 5,
        "action_abi": "exact-joint-v1",
        "initialization": "fresh",
        "warm_lineage_sha256": "",
        "pool_lineage_bundle_sha256": "",
    }
    for field, expected in expected_bootstrap.items():
        if bootstrap.get(field) != expected:
            raise AnalysisError(
                f"exact-action-canary bootstrap {field} mismatch: "
                f"{bootstrap.get(field)!r} != {expected!r}")

    settings = _need_mapping(
        contract.get("settings"), "exact-action-canary settings")
    for field, expected in (
        ("total_agents", EXACT_ACTION_CANARY_TOTAL_AGENTS),
        ("horizon", EXACT_ACTION_CANARY_HORIZON),
        ("minibatch_size", EXACT_ACTION_CANARY_MINIBATCH_SIZE),
        ("expected_checkpoint_bytes", EXACT_ACTION_CANARY_CHECKPOINT_BYTES),
        ("num_frozen_banks", 0),
        ("frozen_bank_pct", 0),
        ("native_precision_bytes", 4),
        ("policy_hidden_size", 512),
        ("policy_num_layers", 3),
        ("policy_expansion_factor", 1),
        ("min_train_games", 1),
        ("min_eval_games", 10_000),
        ("eval_episodes", 10_000),
    ):
        observed = _need_int(
            settings.get(field), f"exact-action-canary settings.{field}")
        if observed != expected:
            raise AnalysisError(
                f"exact-action-canary settings.{field} mismatch: "
                f"{observed} != {expected}")

    error_budget = _need_mapping(
        contract.get("error_budget"), "exact-action-canary error_budget")
    if _need_int(
            error_budget.get("contamination_budget"),
            "exact-action-canary contamination_budget") != 0:
        raise AnalysisError(
            "exact-action-canary contamination_budget must be exactly zero")
    hard_keys = error_budget.get("hard_integrity_keys")
    if hard_keys != list(EXACT_ACTION_CANARY_MANIFEST_HARD_INTEGRITY_KEYS):
        raise AnalysisError(
            "exact-action-canary hard_integrity_keys do not match the complete "
            "replacement live registry")
    poll_seconds = _need_int(
        error_budget.get("detection_poll_seconds"),
        "exact-action-canary detection_poll_seconds",
    )
    if not 1 <= poll_seconds <= 60:
        raise AnalysisError(
            "exact-action-canary detection_poll_seconds must be in 1..60")
    if _need_int(
            error_budget.get("max_panel_silence_seconds"),
            "exact-action-canary max_panel_silence_seconds") != 180:
        raise AnalysisError(
            "exact-action-canary max_panel_silence_seconds must equal 180")

    implementation = _need_mapping(
        contract.get("implementation"), "exact-action-canary implementation")
    implementation_hashes = (
        "screen_script_sha256",
        "game_stats_sha256",
        "live_integrity_guard_sha256",
        "checkpoint_lineage_sha256",
        "status_wrapper_sha256",
        "cuda_runtime_wrapper_sha256",
        "canary_authority_tool_sha256",
        "launcher_sha256",
        "source_sha256",
        "compiled_module_sha256",
        "puffer_patch_bundle_sha256",
        "vendor_source_sha256",
    )
    for field in implementation_hashes:
        _need_sha256(
            implementation.get(field),
            f"exact-action-canary implementation.{field}",
        )
    compiled = _need_mapping(
        implementation.get("compiled_semantic_contract"),
        "exact-action-canary compiled_semantic_contract",
    )
    expected_compiled = {
        "env_name": "bloodbowl",
        "gpu": 1,
        "precision_bytes": 4,
        "observation_abi": "obs-v5",
        "observation_version": 5,
        "action_abi": "exact-joint-v1",
    }
    for field, expected in expected_compiled.items():
        observed = (
            _need_int(compiled.get(field), f"exact-action-canary compiled {field}")
            if isinstance(expected, int) else compiled.get(field)
        )
        if observed != expected:
            raise AnalysisError(
                f"exact-action-canary compiled {field} mismatch: "
                f"{observed!r} != {expected!r}")
    _need_sha256(
        compiled.get("exact_action_source_sha256"),
        "exact-action-canary compiled exact_action_source_sha256",
    )
    environment_source_sha = _need_sha256(
        compiled.get("environment_source_sha256"),
        "exact-action-canary compiled environment_source_sha256",
    )
    if environment_source_sha != implementation["source_sha256"]:
        raise AnalysisError(
            "exact-action-canary compiled environment source does not match "
            "the installed source identity")

    authority = _need_mapping(
        contract.get("canary_authority"),
        "exact-action-canary canary_authority",
    )
    for field in ("plan_authorization", "qualification"):
        value = authority.get(field)
        if not isinstance(value, str) or not Path(value).is_absolute():
            raise AnalysisError(
                f"exact-action-canary authority {field} must be absolute"
            )
    for field in (
        "plan_authorization_sha256",
        "qualification_sha256",
        "cuda_runtime_library_sha256",
    ):
        _need_sha256(
            authority.get(field), f"exact-action-canary authority {field}"
        )
    cuda_path = authority.get("cuda_runtime_library_path")
    if not isinstance(cuda_path, str) or not Path(cuda_path).is_absolute():
        raise AnalysisError(
            "exact-action-canary authority CUDA runtime path must be absolute"
        )
    if _need_int(
        authority.get("cuda_runtime_device_count"),
        "exact-action-canary authority CUDA device count",
    ) <= 0:
        raise AnalysisError(
            "exact-action-canary authority CUDA device count must be positive"
        )


def _validate_exact_action_canary_launch_record(
    directory: Path, contract: dict[str, Any], manifest_sha: str
) -> dict[str, Any]:
    path = directory / "CANARY_LAUNCH_RECORD.json"
    if not path.is_file() or path.is_symlink():
        raise AnalysisError(
            "exact-action-canary launch record is missing or not regular"
        )
    record = _load_json(path, "exact-action-canary launch record")
    if (
        record.get("schema_version") != 1
        or record.get("kind") != "exact_action_canary_launch_record"
        or record.get("qualification_only") is not True
        or record.get("eligible") is not False
    ):
        raise AnalysisError("exact-action-canary launch record contract drifted")
    if record.get("reward_evidence_eligible") is not False:
        raise AnalysisError(
            "exact-action-canary launch record must exclude reward evidence"
        )
    authority = _need_mapping(
        contract.get("canary_authority"), "exact-action-canary authority"
    )
    expected = {
        "plan_authorization": authority["plan_authorization"],
        "plan_authorization_sha256": authority["plan_authorization_sha256"],
        "qualification": authority["qualification"],
        "qualification_sha256": authority["qualification_sha256"],
        "screen_manifest_sha256": manifest_sha,
    }
    for field, value in expected.items():
        if record.get(field) != value:
            raise AnalysisError(
                f"exact-action-canary launch record {field} drifted"
            )
    screen_manifest = record.get("screen_manifest")
    expected_manifest = (directory / "SCREEN_MANIFEST.json").resolve()
    if not isinstance(screen_manifest, str) or screen_manifest != str(
        expected_manifest
    ):
        raise AnalysisError(
            "exact-action-canary launch record screen manifest path drifted"
        )
    launch_path = record.get("launch_authorization")
    if not isinstance(launch_path, str) or not Path(launch_path).is_absolute():
        raise AnalysisError(
            "exact-action-canary launch record authorization path must be absolute"
        )
    launch_sha = _need_sha256(
        record.get("launch_authorization_sha256"),
        "exact-action-canary launch authorization SHA-256",
    )
    return {
        "file": path.name,
        "sha256": _sha256(path),
        "launch_authorization": launch_path,
        "launch_authorization_sha256": launch_sha,
        "qualification_sha256": authority["qualification_sha256"],
        "cuda_runtime_library_sha256": authority[
            "cuda_runtime_library_sha256"
        ],
        "cuda_runtime_device_count": authority["cuda_runtime_device_count"],
    }


def _validate_exact_action_canary_result_authority(
    result: dict[str, Any], launch: dict[str, Any], label: str
) -> None:
    expected = {
        "canary_launch_record_sha256": launch["sha256"],
        "canary_launch_authorization_sha256": launch[
            "launch_authorization_sha256"
        ],
        "canary_qualification_sha256": launch["qualification_sha256"],
        "expected_cuda_runtime_library_sha256": launch[
            "cuda_runtime_library_sha256"
        ],
    }
    for field, value in expected.items():
        if result.get(field) != value:
            raise AnalysisError(f"{label} {field} authority binding drifted")
    if _need_int(
        result.get("expected_cuda_runtime_device_count"),
        f"{label} expected_cuda_runtime_device_count",
    ) != launch["cuda_runtime_device_count"]:
        raise AnalysisError(f"{label} qualified CUDA device count drifted")


def _validate_exact_action_canary_result(
        result: dict[str, Any], label: str, contract: dict[str, Any]) -> str:
    if result.get("qualification_only") is not True:
        raise AnalysisError(f"{label} must be qualification_only")
    if result.get("acceptance_failures") != []:
        raise AnalysisError(
            f"{label} must record an exactly empty acceptance_failures array")

    settings = _need_mapping(contract.get("settings"), "screen settings")
    for phase, minimum_field in (
        ("train", "min_train_games"), ("eval", "min_eval_games")):
        metrics = _need_mapping(
            result.get(f"{phase}_metrics"), f"{label} {phase}_metrics")
        observed_n = _finite_number(
            metrics.get("n"), f"{label} {phase}_metrics.n")
        minimum_n = _need_int(
            settings.get(minimum_field),
            f"screen settings {minimum_field}",
        )
        if observed_n < minimum_n:
            raise AnalysisError(
                f"{label} {phase}_metrics.n is below the frozen minimum: "
                f"{observed_n} < {minimum_n}")
        for key in HARD_INTEGRITY_KEYS:
            observed = _finite_number(
                metrics.get(key), f"{label} {phase}_metrics.{key}")
            if observed != 0.0:
                raise AnalysisError(
                    f"{label} {phase}_metrics.{key} must be exactly zero")

    lineage_path = result.get("checkpoint_lineage")
    if not isinstance(lineage_path, str) or not lineage_path:
        raise AnalysisError(f"{label} checkpoint_lineage must be a non-empty path")
    return _need_sha256(
        result.get("checkpoint_lineage_sha256"),
        f"{label} checkpoint_lineage_sha256",
    )


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
    checkpoint_lineage_sha = None
    if contract.get("screen_profile") == "exact-action-canary":
        checkpoint_lineage_sha = _validate_exact_action_canary_result(
            result, label, contract)
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
    if checkpoint_lineage_sha is not None:
        summary["checkpoint_lineage_sha256"] = checkpoint_lineage_sha
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
        raise AnalysisError(
            f"completion proof must contain all {len(schedule)} results")

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
        if results[key].get("qualification_only") is True:
            recorded_lineage_sha = _need_sha256(
                recorded.get("checkpoint_lineage_sha256"),
                f"completion checkpoint_lineage_sha256 for {arm}/seed {seed}",
            )
            if recorded_lineage_sha != results[key].get(
                    "checkpoint_lineage_sha256"):
                raise AnalysisError(
                    "completion checkpoint lineage hash mismatch for "
                    f"{arm}/seed {seed}")

    return {
        "present": True,
        "file": path.name,
        "sha256": _sha256(path),
        "completed_utc": complete.get("completed_utc"),
    }


def _factorial_effects(
    cells: dict[str, float], profile: str,
) -> dict[str, float]:
    if profile in ("control-final", "exact-action-canary"):
        return {}
    if profile == "distance-possession":
        r0, r1, r2, r3 = (cells[arm] for arm in ("r0", "r1", "r2", "r3"))
        return {
            "possession_main": ((r0 + r1) - (r2 + r3)) / 2.0,
            "distance_main": ((r0 + r2) - (r1 + r3)) / 2.0,
            "interaction": r0 - r1 - r2 + r3,
        }
    both = cells["both"]
    if profile in ("paired-confirmation", "paired-final"):
        candidates = [arm for arm in cells if arm != "both"]
        if len(candidates) != 1:
            raise AnalysisError(
                f"{profile} requires exactly one candidate cell")
        return {"candidate_minus_both": cells[candidates[0]] - both}
    possession = cells["possession_only"]
    gain = cells["gain_only"]
    neither = cells["neither"]
    return {
        "possession_main": ((both + possession) - (gain + neither)) / 2.0,
        "gain_main": ((both + gain) - (possession + neither)) / 2.0,
        "interaction": both - possession - gain + neither,
    }


def _describe_seed_values(
    values: dict[str, float], seeds: Sequence[int]
) -> dict[str, Any]:
    ordered = [values[str(seed)] for seed in seeds]
    return {
        "values_by_seed": values,
        "mean": statistics.fmean(ordered),
        "sample_sd": statistics.stdev(ordered) if len(ordered) > 1 else 0.0,
        "min": min(ordered),
        "max": max(ordered),
        "seed_count": len(ordered),
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
    if spec["profile"] == "exact-action-canary":
        _validate_exact_action_canary_contract(contract)
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
    canary_launch = (
        _validate_exact_action_canary_launch_record(
            directory, contract, manifest_sha
        )
        if spec["profile"] == "exact-action-canary"
        else None
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
        if canary_launch is not None:
            _validate_exact_action_canary_result_authority(
                result, canary_launch, path.name
            )
        key = (arm, seed)
        raw_results[key] = result
        result_paths[key] = path
        runs.append(summary)

    seeds = tuple(spec.get("seeds", (42, 43)))
    if spec["profile"] == "exact-action-canary":
        warnings = [
            (
                "This is a qualification-only runtime canary. Its checkpoint is "
                "permanently ineligible as training ancestry, and its metrics are "
                "not causal reward or policy-strength evidence."
            ),
        ]
    else:
        warnings = [
            (
                f"Only n={len(seeds)} seeds are available. Across-seed means and "
                "sample SDs are descriptive; they are not confidence intervals, "
                "hypothesis tests, or a strength claim."
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
    elif spec["profile"] == "exact-action-canary":
        raise AnalysisError(
            "exact-action-canary requires the atomic SCREEN_COMPLETE.json proof")
    else:
        completion = {"present": False}
        warnings.append(
            f"SCREEN_COMPLETE.json is absent: {len(schedule)} accepted results were "
            "verified, but the atomic screen completion proof is unavailable."
        )

    per_seed: dict[str, Any] = {}
    for seed in seeds:
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
                for seed in seeds
            }
            cell_summaries[arm][metric] = _describe_seed_values(values, seeds)

    effect_summaries: dict[str, Any] = {}
    for metric in metrics:
        effect_summaries[metric] = {}
        for effect in spec["effect_definitions"]:
            values = {
                str(seed): per_seed[str(seed)]["effects"][metric][effect]
                for seed in seeds
            }
            effect_summaries[metric][effect] = _describe_seed_values(values, seeds)

    report = {
        "schema_version": 1,
        "analysis": (
            "exact_action_canary_qualification"
            if spec["profile"] == "exact-action-canary"
            else (
                "control_reward_replication"
                if spec["profile"] == "control-final"
                else (
                    "paired_reward_confirmation"
                    if spec["profile"] in ("paired-confirmation", "paired-final")
                    else "paired_reward_screen_2x2"
                )
            )
        ),
        "screen": {
            "directory": str(directory),
            "prefix": prefix,
            "profile": spec["profile"],
            "candidate_arm": spec.get("candidate_arm"),
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
    if canary_launch is not None:
        report["screen"]["canary_launch"] = canary_launch
    return report


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
    if screen["profile"] == "exact-action-canary":
        lines.append("Qualification verdict")
        lines.append(
            "  accepted fixed one-arm runtime canary; no reward contrasts computed")
    else:
        lines.append(
            "Per-seed paired contrasts"
            if screen["profile"] in ("paired-confirmation", "paired-final")
            else (
                "Per-seed control summaries"
                if screen["profile"] == "control-final"
                else "Per-seed 2x2 effects"
            )
        )
        for seed in report["per_seed"]:
            lines.append(f"  seed {seed}")
            for metric in report["metrics"]:
                effects = report["per_seed"][seed]["effects"][metric]
                lines.append(f"    {metric}: " + " ".join(
                    f"{effect}={_format_number(effects[effect])}"
                    for effect in report["effect_definitions"]
                ))

        lines.append("")
        seed_count = len(report["per_seed"])
        lines.append(f"Across {seed_count} seeds (descriptive means)")
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
