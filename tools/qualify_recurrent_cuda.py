#!/usr/bin/env python3
"""Fail-closed recurrent CUDA qualification for the native Blood Bowl backend.

Correctness cells run in fresh subprocesses. Qualification artifacts are
diagnostic-only and may never be admitted as checkpoint ancestry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import socket
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping

import numpy as np


SCHEMA_VERSION = 2
QUALIFICATION_ONLY = True
MANDATORY_GATES = (
    "construction_state",
    "graph_parity",
    "terminal_reset",
    "ratio",
    "throughput",
)
SNAPSHOT_FIELDS = (
    "observations",
    "actions",
    "values",
    "logprobs",
    "rewards",
    "terminals",
    "action_mask",
)
EXACT_SNAPSHOT_FIELDS = (
    "observations",
    "actions",
    "rewards",
    "terminals",
    "action_mask",
)
FLOAT_SNAPSHOT_FIELDS = ("values", "logprobs")
HARD_INTEGRITY_KEYS = (
    "illegal_frac",
    "reward_clip_frac",
    "reward_clip_frac_nonzero",
    "reward_clip_excess",
    "reward_clip_signed_delta",
    "reward_clipped_samples_per_episode",
    "reward_clip_terminal_samples_per_episode",
    "reward_clip_nonterminal_samples_per_episode",
    "reward_nonfinite_frac",
    "reward_nonfinite_samples_per_episode",
    "reward_clip_episodes",
    "reward_nonfinite_episodes",
    "reward_component_mismatch_samples_per_episode",
    "reward_component_nonfinite_samples_per_episode",
    "error_episodes",
    "demo_fallbacks",
)
TRANSITION_CELL_KINDS = frozenset({
    "rollout",
    "terminal_auto",
    "terminal_control",
    "ratio",
    "throughput",
})
# Qualification is deliberately fp32-only. In BF16, the behavior log
# probability is rounded before PPO recomputation, so a correct unchanged
# policy can exceed a tolerance derived from one BF16 ULP around ratio one.
GRAPH_ATOL_BY_PRECISION = {4: 1.0e-6}
RATIO_ATOL_BY_PRECISION = {4: 2.0e-5}
DEFAULT_RATIO_CALL_LIMIT = 64
DEFAULT_MAX_REGRESSION_FRACTION = 0.10
# Match the frozen exact-action canary rather than allocating train activations
# for its entire 2,048 x 64 rollout quantum at once.
DEFAULT_THROUGHPUT_MINIBATCH_SIZE = 16384
BACKEND_SOURCE_FILES = (
    "pufferlib/pufferl.py",
    "pufferlib/torch_pufferl.py",
    "src/bindings.cu",
    "src/bindings_cpu.cpp",
    "src/kernels.cu",
    "src/pufferlib.cu",
    "src/vecenv.h",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
GIT_COMMIT_PATTERN = re.compile(r"^[0-9a-f]{40}$")
PREDECESSOR_SOURCE_COMMIT = "afc8008933548438ca93c41341f5f08fdd294386"
CANDIDATE_SOURCE_COMMIT = "a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3"
PROTECTED_RECOVERY_ROOT = Path("/home/rache/bloodbowl-rl-recovery-20260719")


class QualificationError(RuntimeError):
    """A missing, malformed, drifted, or failed qualification predicate."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise QualificationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def backend_source_hash(puffer_root: Path) -> str:
    """Reproduce install_puffer_env.sh's path-bound backend source digest."""
    root = Path(puffer_root).resolve()
    manifest = bytearray()
    for relative in BACKEND_SOURCE_FILES:
        path = root / relative
        if not path.is_file():
            raise QualificationError(f"backend source is missing: {path}")
        manifest.extend(f"{sha256(path)}  {relative}\n".encode("utf-8"))
    return hashlib.sha256(manifest).hexdigest()


def installed_snapshot_hash(puffer_root: Path) -> str:
    path = Path(puffer_root).resolve() / "ocean" / "bloodbowl" / ".content_hash"
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise QualificationError(f"installed snapshot digest is unavailable: {exc}") from exc
    return _require_sha256(value, "installed snapshot digest")


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def write_npz_atomic(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.tmp.", suffix=".npz", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            np.savez(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualificationError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise QualificationError(f"{label} must be finite")
    return result


def _state_entries(
    report: Mapping[str, Any], expected_banks: int, expected_buffers: int
) -> list[Mapping[str, Any]]:
    if report.get("num_banks") != expected_banks or report.get(
        "num_buffers"
    ) != expected_buffers:
        raise QualificationError("state report bank/buffer dimensions mismatch")
    entries = report.get("entries")
    if not isinstance(entries, list):
        raise QualificationError("state report entries must be a list")
    expected = {
        (bank, buffer)
        for bank in range(expected_banks)
        for buffer in range(expected_buffers)
    }
    observed: set[tuple[int, int]] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise QualificationError("state entry must be an object")
        bank = entry.get("bank")
        buffer = entry.get("buffer")
        if isinstance(bank, bool) or not isinstance(bank, int):
            raise QualificationError("state bank must be an integer")
        if isinstance(buffer, bool) or not isinstance(buffer, int):
            raise QualificationError("state buffer must be an integer")
        key = (bank, buffer)
        if key in observed:
            raise QualificationError(f"duplicate state entry {key}")
        observed.add(key)
    if observed != expected:
        raise QualificationError(
            f"state coverage mismatch: expected {sorted(expected)}, "
            f"observed {sorted(observed)}"
        )
    return entries


def _validate_state_shape(entry: Mapping[str, Any]) -> None:
    shape = entry.get("shape")
    if not isinstance(shape, list) or len(shape) < 3 or not all(
        isinstance(value, int) and not isinstance(value, bool) and value > 0
        for value in shape
    ):
        raise QualificationError("state tensor shape is malformed")
    elements = entry.get("elements")
    if elements != math.prod(shape):
        raise QualificationError("state tensor element count differs from shape")
    active_rows = entry.get("active_rows")
    if (isinstance(active_rows, bool) or not isinstance(active_rows, int)
            or active_rows <= 0 or active_rows > shape[1]):
        raise QualificationError("state active-row count is invalid")
    active_elements = entry.get("active_elements")
    expected_active = math.prod(shape) // shape[1] * active_rows
    if active_elements != expected_active:
        raise QualificationError("state active element count differs from shape")


def derive_row_partition(
    report: Mapping[str, Any], *, total_agents: int
) -> tuple[set[int], set[int]]:
    num_banks = report.get("num_banks")
    num_buffers = report.get("num_buffers")
    agents_per_buffer = report.get("agents_per_buffer")
    layout = report.get("bank_layout")
    for label, value in (
        ("num_banks", num_banks),
        ("num_buffers", num_buffers),
        ("agents_per_buffer", agents_per_buffer),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise QualificationError(f"row partition {label} is invalid")
    if total_agents != num_buffers * agents_per_buffer:
        raise QualificationError("row partition total-agent count is inconsistent")
    if not isinstance(layout, list) or len(layout) != num_banks + 1 or not all(
        isinstance(value, int) and not isinstance(value, bool) for value in layout
    ):
        raise QualificationError("row partition bank layout is malformed")
    if layout[0] != 0 or layout[-1] != agents_per_buffer or any(
        left >= right for left, right in zip(layout, layout[1:])
    ):
        raise QualificationError("row partition bank layout is not a strict partition")
    if num_banks < 2:
        raise QualificationError("ratio qualification requires a real frozen bank")
    primary: set[int] = set()
    frozen: set[int] = set()
    for buffer in range(num_buffers):
        offset = buffer * agents_per_buffer
        primary.update(range(offset + layout[0], offset + layout[1]))
        frozen.update(range(offset + layout[1], offset + layout[-1]))
    if not primary or not frozen or primary & frozen or primary | frozen != set(
        range(total_agents)
    ):
        raise QualificationError("row partition does not cover disjoint learner/frozen rows")
    return primary, frozen


def validate_zero_state(
    report: Mapping[str, Any], *, expected_banks: int, expected_buffers: int
) -> None:
    for entry in _state_entries(report, expected_banks, expected_buffers):
        _validate_state_shape(entry)
        nonzero = entry.get("nonzero")
        nonfinite = entry.get("nonfinite")
        if nonzero != 0 or nonfinite != 0:
            raise QualificationError(
                f"state is not exactly zero/finite at bank={entry['bank']} "
                f"buffer={entry['buffer']}: nonzero={nonzero}, "
                f"nonfinite={nonfinite}"
            )
        if _finite_number(entry.get("max_abs"), "state max_abs") != 0.0:
            raise QualificationError("state max_abs is not exactly zero")
        if entry.get("active_nonzero") != 0 or entry.get("active_nonfinite") != 0:
            raise QualificationError("active recurrent state is not exactly zero/finite")
        if _finite_number(
            entry.get("active_max_abs"), "active state max_abs"
        ) != 0.0:
            raise QualificationError("active state max_abs is not exactly zero")


def validate_nonzero_state(
    report: Mapping[str, Any], *, expected_banks: int, expected_buffers: int
) -> None:
    for entry in _state_entries(report, expected_banks, expected_buffers):
        _validate_state_shape(entry)
        nonzero = entry.get("active_nonzero")
        nonfinite = entry.get("nonfinite")
        if isinstance(nonzero, bool) or not isinstance(nonzero, int) or nonzero <= 0:
            raise QualificationError(
                f"state path was not exercised at bank={entry['bank']} "
                f"buffer={entry['buffer']}"
            )
        if nonfinite != 0 or entry.get("active_nonfinite") != 0:
            raise QualificationError("exercised recurrent state contains non-finite values")
        if _finite_number(entry.get("active_max_abs"), "active state max_abs") <= 0.0:
            raise QualificationError("nonzero state has non-positive max_abs")


def _validate_array_pair(
    key: str, left: Any, right: Any
) -> tuple[np.ndarray, np.ndarray]:
    if not isinstance(left, np.ndarray) or not isinstance(right, np.ndarray):
        raise QualificationError(f"snapshot field {key} is not an ndarray")
    if left.dtype != np.dtype(np.float32) or right.dtype != np.dtype(np.float32):
        raise QualificationError(f"snapshot field {key} is not normalized float32")
    if left.shape != right.shape:
        raise QualificationError(
            f"snapshot field {key} shape mismatch: {left.shape} != {right.shape}"
        )
    if not np.isfinite(left).all() or not np.isfinite(right).all():
        raise QualificationError(f"snapshot field {key} contains non-finite values")
    return left, right


def compare_snapshots(
    left: Mapping[str, np.ndarray],
    right: Mapping[str, np.ndarray],
    *,
    atol: float,
    require_all_terminal: bool = False,
) -> dict[str, float]:
    atol_value = _finite_number(atol, "snapshot atol")
    if atol_value < 0:
        raise QualificationError("snapshot atol must be nonnegative")
    for key in SNAPSHOT_FIELDS:
        if key not in left or key not in right:
            raise QualificationError(f"snapshot field {key} is missing")
    maxima: dict[str, float] = {}
    for key in EXACT_SNAPSHOT_FIELDS:
        a, b = _validate_array_pair(key, left[key], right[key])
        if not np.array_equal(a, b):
            raise QualificationError(f"exact snapshot field {key} differs")
        maxima[key] = 0.0
    for key in FLOAT_SNAPSHOT_FIELDS:
        a, b = _validate_array_pair(key, left[key], right[key])
        maximum = float(np.max(np.abs(a - b))) if a.size else 0.0
        if maximum > atol_value:
            raise QualificationError(
                f"snapshot field {key} max abs error {maximum} exceeds {atol_value}"
            )
        maxima[key] = maximum
    if require_all_terminal:
        terminals = left["terminals"]
        if terminals.size == 0 or not np.array_equal(
            terminals, np.ones_like(terminals)
        ):
            raise QualificationError("post-terminal snapshot does not mark every row terminal")
    return maxima


def compare_decoder_outputs(
    left: Mapping[str, np.ndarray], right: Mapping[str, np.ndarray], *, atol: float
) -> dict[str, float]:
    keys_left = {key for key in left if key.startswith("decoder_bank_")}
    keys_right = {key for key in right if key.startswith("decoder_bank_")}
    if not keys_left or keys_left != keys_right:
        raise QualificationError("decoder bank/buffer coverage mismatch")
    maxima: dict[str, float] = {}
    for key in sorted(keys_left):
        a, b = _validate_array_pair(key, left[key], right[key])
        maximum = float(np.max(np.abs(a - b))) if a.size else 0.0
        if maximum > atol:
            raise QualificationError(
                f"decoder field {key} max abs error {maximum} exceeds {atol}"
            )
        maxima[key] = maximum
    return maxima


def validate_ratio_calls(
    calls: Iterable[Mapping[str, np.ndarray]],
    *,
    primary_rows: set[int],
    frozen_rows: set[int],
    atol: float,
) -> dict[str, Any]:
    if not primary_rows or primary_rows & frozen_rows:
        raise QualificationError("ratio row partition is invalid")
    tolerance = _finite_number(atol, "ratio atol")
    if tolerance < 0:
        raise QualificationError("ratio atol must be nonnegative")
    covered: set[int] = set()
    maximum = 0.0
    count = 0
    attempts = 0
    for call in calls:
        attempts += 1
        selected = call.get("selected_rows")
        ratios = call.get("ratios")
        if not isinstance(selected, np.ndarray) or selected.dtype != np.dtype(np.int32):
            raise QualificationError("selected ratio rows must be int32")
        if not isinstance(ratios, np.ndarray) or ratios.dtype != np.dtype(np.float32):
            raise QualificationError("recomputed ratios must be float32")
        selected = selected.reshape(-1)
        if ratios.ndim < 1 or ratios.shape[0] != selected.size:
            raise QualificationError("selected-row and ratio leading dimensions differ")
        if not np.isfinite(ratios).all():
            raise QualificationError("recomputed ratios contain non-finite values")
        delta = np.abs(ratios - np.float32(1.0))
        observed_max = float(np.max(delta)) if delta.size else 0.0
        maximum = max(maximum, observed_max)
        if observed_max > tolerance:
            raise QualificationError(
                f"recomputed ratio error {observed_max} exceeds {tolerance}"
            )
        for raw_row in selected.tolist():
            row = int(raw_row)
            if row in frozen_rows:
                raise QualificationError(f"PPO selected frozen row {row}")
            if row not in primary_rows:
                raise QualificationError(f"PPO selected unknown row {row}")
            covered.add(row)
        count += int(ratios.size)
    if covered != primary_rows:
        raise QualificationError(
            f"ratio coverage incomplete: covered={sorted(covered)}, "
            f"required={sorted(primary_rows)}"
        )
    return {
        "attempts": attempts,
        "ratio_elements": count,
        "covered_primary_rows": sorted(covered),
        "max_abs_ratio_minus_one": maximum,
        "atol": tolerance,
    }


def validate_weight_identity(before: str, after: str) -> None:
    for label, value in (("before", before), ("after", after)):
        if not isinstance(value, str) or len(value) != 64:
            raise QualificationError(f"weight digest {label} is malformed")
    if before != after:
        raise QualificationError("learning_rate=0 changed primary weight bytes")


def validate_hard_integrity(env: Mapping[str, Any]) -> dict[str, float]:
    result: dict[str, float] = {}
    for key in HARD_INTEGRITY_KEYS:
        if key not in env:
            raise QualificationError(f"hard-integrity field is missing: {key}")
        value = _finite_number(env[key], f"hard-integrity field {key}")
        if value != 0.0:
            raise QualificationError(f"hard-integrity field is nonzero: {key}={value}")
        result[key] = value
    return result


def bind_transition_integrity(
    backend: Any,
    pufferl: Any,
    record: dict[str, Any],
    *,
    additional_rollouts: int = 0,
) -> dict[str, float]:
    """Finish a bounded telemetry interval and bind its exact-zero verdict."""
    if (isinstance(additional_rollouts, bool)
            or not isinstance(additional_rollouts, int)
            or additional_rollouts < 0):
        raise QualificationError("additional integrity rollouts are invalid")
    for _ in range(additional_rollouts):
        backend.rollouts(pufferl)
    log = backend.log(pufferl)
    if not isinstance(log, Mapping) or not isinstance(log.get("env"), Mapping):
        raise QualificationError("transition integrity log/env telemetry is missing")
    integrity = validate_hard_integrity(log["env"])
    record["hard_integrity"] = integrity
    record["hard_integrity_zero"] = True
    return integrity


def validate_transition_cell_integrity(
    record: Mapping[str, Any], kind: str
) -> dict[str, float]:
    """Revalidate integrity evidence for one transition-executing cell."""
    if kind not in TRANSITION_CELL_KINDS:
        raise QualificationError(f"qualification cell {kind} does not execute transitions")
    if record.get("kind") != kind:
        raise QualificationError(f"qualification cell kind mismatch for {kind}")
    payload = record.get("throughput") if kind == "throughput" else record
    if not isinstance(payload, Mapping):
        raise QualificationError(f"qualification cell integrity payload is missing: {kind}")
    integrity = validate_hard_integrity(payload.get("hard_integrity", {}))
    if payload.get("hard_integrity_zero") is not True:
        raise QualificationError(
            f"qualification cell hard-integrity verdict is not zero: {kind}"
        )
    return integrity


def validate_throughput(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    max_regression_fraction: float,
) -> dict[str, float]:
    _validate_throughput_record(candidate, "candidate")
    _validate_throughput_record(baseline, "baseline")
    regression_limit = _finite_number(
        max_regression_fraction, "throughput regression fraction"
    )
    if regression_limit < 0 or regression_limit >= 1:
        raise QualificationError("throughput regression fraction must be in [0, 1)")
    for key in ("host", "gpu", "precision_bytes", "config_sha256"):
        if candidate.get(key) != baseline.get(key):
            raise QualificationError(f"throughput identity mismatch for {key}")
    if candidate.get("hard_integrity_zero") is not True:
        raise QualificationError("candidate throughput hard-integrity gate is not zero")
    if baseline.get("hard_integrity_zero") is not True:
        raise QualificationError("baseline throughput hard-integrity gate is not zero")
    candidate_sps = _finite_number(
        candidate.get("steps_per_second"), "candidate throughput"
    )
    baseline_sps = _finite_number(
        baseline.get("steps_per_second"), "baseline throughput"
    )
    if candidate_sps <= 0 or baseline_sps <= 0:
        raise QualificationError("throughput must be positive")
    floor = baseline_sps * (1.0 - regression_limit)
    if candidate_sps < floor:
        raise QualificationError(
            f"candidate throughput {candidate_sps} is below floor {floor}"
        )
    return {
        "candidate_steps_per_second": candidate_sps,
        "baseline_steps_per_second": baseline_sps,
        "minimum_steps_per_second": floor,
        "regression_fraction": max(0.0, 1.0 - candidate_sps / baseline_sps),
        "relative_change_fraction": candidate_sps / baseline_sps - 1.0,
    }


def _validate_throughput_record(record: Mapping[str, Any], label: str) -> None:
    if not isinstance(record.get("host"), str) or not record.get("host"):
        raise QualificationError(f"{label} throughput host is missing")
    if not isinstance(record.get("gpu"), str) or not record.get("gpu"):
        raise QualificationError(f"{label} throughput GPU is missing")
    if record.get("precision_bytes") not in GRAPH_ATOL_BY_PRECISION:
        raise QualificationError(f"{label} throughput precision is unsupported")
    _require_sha256(record.get("config_sha256"), f"{label} throughput config")
    steps = record.get("steps")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
        raise QualificationError(f"{label} throughput step count is invalid")
    elapsed = _finite_number(
        record.get("elapsed_seconds"), f"{label} throughput elapsed time"
    )
    sps = _finite_number(
        record.get("steps_per_second"), f"{label} throughput rate"
    )
    if elapsed <= 0 or sps <= 0 or not math.isclose(
        sps, steps / elapsed, rel_tol=1.0e-12, abs_tol=0.0
    ):
        raise QualificationError(f"{label} throughput rate is internally inconsistent")
    median = _finite_number(
        record.get("median_rollout_seconds"), f"{label} median rollout"
    )
    p95 = _finite_number(record.get("p95_rollout_seconds"), f"{label} p95 rollout")
    if median <= 0 or p95 <= 0 or p95 < median:
        raise QualificationError(f"{label} throughput rollout timing is invalid")
    if not isinstance(record.get("utilization"), Mapping):
        raise QualificationError(f"{label} throughput utilization is missing")
    validate_hard_integrity(record.get("hard_integrity", {}))
    if record.get("hard_integrity_zero") is not True:
        raise QualificationError(f"{label} throughput hard-integrity gate is not zero")


def validate_baseline_artifact(path: Path) -> dict[str, Any]:
    wrapper_path = Path(path).resolve()
    wrapper = _read_json(wrapper_path)
    required_wrapper_keys = {
        "schema_version", "qualification_only", "role", "identity",
        "expected_predecessor", "predecessor_source", "runner_source",
        "throughput", "cell_record", "cell_record_sha256", "runner_sha256",
    }
    if set(wrapper) != required_wrapper_keys:
        raise QualificationError("throughput baseline wrapper schema is not exact")
    if wrapper.get("schema_version") != SCHEMA_VERSION:
        raise QualificationError("throughput baseline schema version mismatch")
    if wrapper.get("qualification_only") is not True or wrapper.get("role") != (
        "preceding_exact_action_throughput_baseline"
    ):
        raise QualificationError("throughput baseline role is invalid")
    current_runner_hash = sha256(Path(__file__).resolve())
    if wrapper.get("runner_sha256") != current_runner_hash:
        raise QualificationError("throughput baseline runner identity drifted")
    runner_source = current_runner_source_identity()
    if wrapper.get("runner_source") != runner_source:
        raise QualificationError("throughput baseline runner checkout drifted")
    cell_path = Path(str(wrapper.get("cell_record", ""))).resolve()
    try:
        cell_path.relative_to(wrapper_path.parent)
    except ValueError as exc:
        raise QualificationError("throughput baseline cell escapes its artifact directory") from exc
    expected_cell_hash = _require_sha256(
        wrapper.get("cell_record_sha256"), "throughput baseline cell digest"
    )
    if not cell_path.is_file() or sha256(cell_path) != expected_cell_hash:
        raise QualificationError("throughput baseline cell record drifted")
    cell = _read_json(cell_path)
    if (cell.get("schema_version") != SCHEMA_VERSION
            or cell.get("qualification_only") is not True
            or cell.get("accepted") is not True
            or cell.get("kind") != "throughput"
            or cell.get("preceding_runtime") is not True
            or cell.get("runner_sha256") != current_runner_hash):
        raise QualificationError("throughput predecessor cell role is invalid")
    identity = cell.get("identity")
    if not isinstance(identity, Mapping):
        raise QualificationError("throughput predecessor identity is missing")
    identity = validate_module_identity(identity, qualification_surface=False)
    validate_current_identity_files(identity)
    expected_predecessor = wrapper.get("expected_predecessor")
    if not isinstance(expected_predecessor, Mapping):
        raise QualificationError("throughput predecessor expectation is missing")
    validate_expected_predecessor_identity(identity, expected_predecessor)
    predecessor_source = wrapper.get("predecessor_source")
    if not isinstance(predecessor_source, Mapping):
        raise QualificationError("throughput predecessor source identity is missing")
    predecessor_source = validate_source_checkout_record(
        predecessor_source,
        expected_commit=str(expected_predecessor["source_commit"]),
        role="predecessor",
    )
    if cell.get("predecessor_source") != predecessor_source:
        raise QualificationError("throughput wrapper/cell source identity mismatch")
    if cell.get("runner_source") != runner_source:
        raise QualificationError("throughput wrapper/cell runner identity mismatch")
    if identity.get("puffer_root") != predecessor_source["puffer_root"]:
        raise QualificationError("throughput module is outside predecessor source checkout")
    if wrapper.get("identity") != identity:
        raise QualificationError("throughput wrapper/cell identity mismatch")
    throughput = cell.get("throughput")
    if not isinstance(throughput, Mapping) or wrapper.get("throughput") != throughput:
        raise QualificationError("throughput wrapper/cell metrics mismatch")
    if throughput.get("config_sha256") != cell.get("config_sha256"):
        raise QualificationError("throughput predecessor config digest mismatch")
    validate_hard_integrity(throughput.get("hard_integrity", {}))
    if throughput.get("hard_integrity_zero") is not True:
        raise QualificationError("throughput predecessor integrity verdict is not zero")
    return {
        "identity": identity,
        "expected_predecessor": dict(expected_predecessor),
        "predecessor_source": predecessor_source,
        "runner_source": runner_source,
        "throughput": dict(throughput),
        "cell": cell,
        "cell_path": str(cell_path),
        "cell_sha256": expected_cell_hash,
    }


def validate_predecessor_transition(
    predecessor: Mapping[str, Any], candidate: Mapping[str, Any]
) -> None:
    for key in (
        "compiled_env", "environment_sha256", "observation_abi",
        "observation_version", "action_abi", "precision_bytes",
    ):
        if predecessor.get(key) != candidate.get(key):
            raise QualificationError(f"predecessor/candidate lineage mismatch for {key}")
    if predecessor.get("qualification_surface") is not False or candidate.get(
        "qualification_surface"
    ) is not True:
        raise QualificationError("predecessor/candidate qualification roles are invalid")
    if predecessor.get("compiled_backend_sha256") == candidate.get(
        "compiled_backend_sha256"
    ):
        raise QualificationError("candidate backend digest did not change from predecessor")
    if predecessor.get("module_sha256") == candidate.get("module_sha256"):
        raise QualificationError("candidate module binary did not change from predecessor")


def combine_gate_verdicts(gates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if set(gates) != set(MANDATORY_GATES):
        raise QualificationError(
            f"mandatory gate set mismatch: {sorted(gates)} != "
            f"{sorted(MANDATORY_GATES)}"
        )
    accepted = all(gate.get("accepted") is True for gate in gates.values())
    return {
        "accepted": accepted,
        "mandatory_gates": list(MANDATORY_GATES),
        "failed_gates": sorted(
            name for name, gate in gates.items() if gate.get("accepted") is not True
        ),
    }


def _decode_tensor(record: Mapping[str, Any]) -> np.ndarray:
    dtype = record.get("dtype")
    shape_raw = record.get("shape")
    data = record.get("data")
    if not isinstance(shape_raw, list) or not all(
        isinstance(value, int) and not isinstance(value, bool) and value >= 0
        for value in shape_raw
    ):
        raise QualificationError("native tensor shape is malformed")
    if not isinstance(data, bytes):
        raise QualificationError("native tensor payload is not bytes")
    shape = tuple(shape_raw)
    elements = math.prod(shape) if shape else 0
    if dtype == "f32":
        if len(data) != elements * 4:
            raise QualificationError("fp32 tensor byte count mismatch")
        array = np.frombuffer(data, dtype="<f4").copy()
    elif dtype == "bf16":
        if len(data) != elements * 2:
            raise QualificationError("bf16 tensor byte count mismatch")
        words = np.frombuffer(data, dtype="<u2").astype(np.uint32)
        array = (words << np.uint32(16)).view(np.float32).copy()
    elif dtype == "i32":
        if len(data) != elements * 4:
            raise QualificationError("int32 tensor byte count mismatch")
        return np.frombuffer(data, dtype="<i4").copy().reshape(shape)
    else:
        raise QualificationError(f"unsupported native tensor dtype: {dtype!r}")
    return array.reshape(shape).astype(np.float32, copy=False)


def decode_snapshot(raw: Mapping[str, Any]) -> dict[str, np.ndarray]:
    tensors = raw.get("tensors")
    decoders = raw.get("decoder_outputs")
    num_banks = raw.get("num_banks")
    num_buffers = raw.get("num_buffers")
    if (not isinstance(tensors, Mapping) or not isinstance(decoders, list)
            or isinstance(num_banks, bool) or not isinstance(num_banks, int)
            or isinstance(num_buffers, bool) or not isinstance(num_buffers, int)
            or num_banks <= 0 or num_buffers <= 0):
        raise QualificationError("native snapshot structure is malformed")
    arrays = {str(key): _decode_tensor(value) for key, value in tensors.items()}
    seen: set[tuple[int, int]] = set()
    for entry in decoders:
        if not isinstance(entry, Mapping):
            raise QualificationError("decoder snapshot entry is malformed")
        bank, buffer = entry.get("bank"), entry.get("buffer")
        active_rows = entry.get("active_rows")
        if (isinstance(bank, bool) or not isinstance(bank, int)
                or isinstance(buffer, bool) or not isinstance(buffer, int)
                or isinstance(active_rows, bool) or not isinstance(active_rows, int)
                or active_rows <= 0):
            raise QualificationError("decoder snapshot index is malformed")
        key = (bank, buffer)
        if key in seen:
            raise QualificationError(f"duplicate decoder snapshot {key}")
        seen.add(key)
        decoded = _decode_tensor(entry.get("tensor"))
        if decoded.ndim < 1 or decoded.shape[0] != active_rows:
            raise QualificationError("decoder snapshot includes inactive rows")
        arrays[f"decoder_bank_{bank}_buffer_{buffer}"] = decoded
    expected = {
        (bank, buffer)
        for bank in range(num_banks)
        for buffer in range(num_buffers)
    }
    if seen != expected:
        raise QualificationError("decoder snapshot bank/buffer coverage is incomplete")
    return arrays


def qualification_args(
    *,
    cudagraphs: int,
    seed: int,
    total_agents: int,
    num_buffers: int,
    num_threads: int,
    horizon: int,
    max_decisions: int,
    hidden_size: int,
    num_layers: int,
    frozen_banks: int,
    frozen_bank_pct: float,
    learning_rate: float,
    replay_ratio: int = 1,
    minibatch_size: int | None = None,
) -> dict[str, Any]:
    if num_buffers <= 0 or total_agents <= 0 or total_agents % num_buffers:
        raise QualificationError("total_agents must be positive and buffer-divisible")
    if total_agents % 2:
        raise QualificationError("Blood Bowl qualification requires paired agents")
    if horizon <= 0:
        raise QualificationError("qualification horizon must be positive")
    rollout_quantum = total_agents * horizon
    if minibatch_size is None:
        minibatch_size = rollout_quantum
    minibatch_size = validate_throughput_minibatch(
        total_agents, horizon, minibatch_size
    )
    return {
        "env_name": "bloodbowl",
        "reset_state": True,
        "cudagraphs": cudagraphs,
        "profile": False,
        "rank": 0,
        "world_size": 1,
        "gpu_id": 0,
        "nccl_id": "",
        "seed": seed,
        "vec": {
            "total_agents": total_agents,
            "num_buffers": num_buffers,
            "num_threads": num_threads,
            "num_frozen_banks": frozen_banks,
            "frozen_bank_pct": frozen_bank_pct if frozen_banks else 0.0,
            "frozen_bank_hidden_size": hidden_size,
            "frozen_bank_num_layers": num_layers,
        },
        "env": {"seed": seed, "max_decisions": max_decisions},
        "policy": {"hidden_size": hidden_size, "num_layers": num_layers},
        "train": {
            "horizon": horizon,
            "learning_rate": learning_rate,
            "min_lr_ratio": 1.0,
            "anneal_lr": False,
            "beta1": 0.9,
            "beta2": 0.95,
            "eps": 1.0e-8,
            "minibatch_size": minibatch_size,
            "replay_ratio": replay_ratio,
            "total_timesteps": max(minibatch_size * 256, 1),
            "max_grad_norm": 1.0,
            "clip_coef": 0.2,
            "vf_clip_coef": 0.2,
            "vf_coef": 0.5,
            "ent_coef": 0.0,
            "min_ent_coef_ratio": 1.0,
            "anneal_ent_coef": False,
            "gamma": 0.995,
            "gae_lambda": 0.95,
            "vtrace_rho_clip": 1.0,
            "vtrace_c_clip": 1.0,
            "prio_alpha": 0.0,
            "prio_beta0": 1.0,
        },
    }


def validate_throughput_minibatch(
    total_agents: int, horizon: int, minibatch_size: int
) -> int:
    rollout_quantum = total_agents * horizon
    if (
        total_agents <= 0
        or horizon <= 0
        or minibatch_size <= 0
        or minibatch_size % horizon
        or minibatch_size > rollout_quantum
        or rollout_quantum % minibatch_size
    ):
        raise QualificationError(
            "minibatch_size must be positive, horizon-divisible, no larger than "
            "the rollout quantum, and divide it exactly"
        )
    return minibatch_size


def _load_backend(puffer_root: Path, *, require_qualification: bool = True):
    root = Path(puffer_root).resolve()
    sys.path.insert(0, str(root))
    from pufferlib import _C  # type: ignore

    module = Path(_C.__file__).resolve()
    try:
        module.relative_to(root)
    except ValueError as exc:
        raise QualificationError(
            f"imported native module is outside Puffer root: {module}"
        ) from exc
    required = [
        "create_pufferl",
        "rollouts",
        "log",
        "get_utilization",
        "save_weights",
        "load_frozen_bank",
    ]
    if require_qualification:
        required.extend((
            "set_evaluation_mode",
            "train",
            "qualification_recurrent_state",
            "qualification_snapshot",
        ))
    missing = [name for name in required if not hasattr(_C, name)]
    if missing:
        raise QualificationError(f"compiled qualification surface is missing: {missing}")
    return _C, module


def _module_identity(_C, module: Path, puffer_root: Path) -> dict[str, Any]:
    root = Path(puffer_root).resolve()
    return {
        "module": str(module),
        "puffer_root": str(root),
        "module_sha256": sha256(module),
        "compiled_backend_sha256": str(_C.exact_action_source_hash),
        "backend_sources_sha256": backend_source_hash(root),
        "environment_sha256": str(_C.environment_source_hash),
        "installed_snapshot_sha256": installed_snapshot_hash(root),
        "observation_abi": str(_C.observation_abi),
        "observation_version": int(_C.observation_version),
        "action_abi": str(_C.action_abi),
        "precision_bytes": int(_C.precision_bytes),
        "compiled_env": str(_C.env_name),
        "qualification_surface": all(hasattr(_C, name) for name in (
            "qualification_recurrent_state", "qualification_snapshot",
        )),
    }


def validate_module_identity(
    identity: Mapping[str, Any], *, qualification_surface: bool
) -> dict[str, Any]:
    if identity.get("compiled_env") != "bloodbowl":
        raise QualificationError("compiled environment is not bloodbowl")
    if identity.get("observation_abi") != "obs-v5" or identity.get(
        "observation_version"
    ) != 5:
        raise QualificationError("compiled observation lineage is not obs-v5")
    if identity.get("action_abi") != "exact-joint-v1":
        raise QualificationError("compiled action lineage is not exact-joint-v1")
    if identity.get("precision_bytes") not in GRAPH_ATOL_BY_PRECISION:
        raise QualificationError("compiled precision is unsupported")
    if identity.get("qualification_surface") is not qualification_surface:
        raise QualificationError("compiled qualification-surface role is wrong")
    for key in (
        "module_sha256", "compiled_backend_sha256", "backend_sources_sha256",
        "environment_sha256", "installed_snapshot_sha256",
    ):
        _require_sha256(identity.get(key), f"module identity {key}")
    if identity.get("compiled_backend_sha256") != identity.get(
        "backend_sources_sha256"
    ):
        raise QualificationError("compiled module differs from backend source digest")
    if identity.get("environment_sha256") != identity.get(
        "installed_snapshot_sha256"
    ):
        raise QualificationError("compiled module differs from installed environment digest")
    module = Path(str(identity.get("module", ""))).resolve()
    root = Path(str(identity.get("puffer_root", ""))).resolve()
    try:
        module.relative_to(root)
    except ValueError as exc:
        raise QualificationError("compiled module is outside recorded Puffer root") from exc
    return dict(identity)


def validate_current_identity_files(identity: Mapping[str, Any]) -> None:
    root = Path(str(identity.get("puffer_root", ""))).resolve()
    module = Path(str(identity.get("module", ""))).resolve()
    if not module.is_file() or sha256(module) != identity.get("module_sha256"):
        raise QualificationError("compiled module binary drifted after qualification")
    if backend_source_hash(root) != identity.get("backend_sources_sha256"):
        raise QualificationError("Puffer backend sources drifted after qualification")
    if installed_snapshot_hash(root) != identity.get("installed_snapshot_sha256"):
        raise QualificationError("installed environment snapshot drifted after qualification")


def validate_expected_candidate_identity(
    identity: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    mapping = {
        "module_sha256": "module_sha256",
        "compiled_backend_sha256": "backend_sha256",
        "environment_sha256": "environment_sha256",
    }
    if set(expected) != {"source_commit", *mapping.values()}:
        raise QualificationError("frozen candidate identity schema is not exact")
    for key in ("module_sha256", "backend_sha256", "environment_sha256"):
        _require_sha256(expected.get(key), f"frozen candidate {key}")
    source_commit = expected.get("source_commit")
    if not isinstance(source_commit, str) or GIT_COMMIT_PATTERN.fullmatch(
        source_commit
    ) is None:
        raise QualificationError("frozen candidate source commit is malformed")
    if source_commit != CANDIDATE_SOURCE_COMMIT:
        raise QualificationError("frozen candidate source commit is not canonical")
    for identity_key, expected_key in mapping.items():
        if identity.get(identity_key) != expected.get(expected_key):
            raise QualificationError(
                f"candidate identity differs from frozen {expected_key}"
            )


def validate_expected_predecessor_identity(
    identity: Mapping[str, Any], expected: Mapping[str, Any]
) -> None:
    mapping = {
        "module_sha256": "module_sha256",
        "compiled_backend_sha256": "backend_sha256",
        "environment_sha256": "environment_sha256",
    }
    if set(expected) != {"source_commit", *mapping.values()}:
        raise QualificationError("frozen predecessor identity schema is not exact")
    source_commit = expected.get("source_commit")
    if not isinstance(source_commit, str) or GIT_COMMIT_PATTERN.fullmatch(
        source_commit
    ) is None:
        raise QualificationError("frozen predecessor source commit is malformed")
    if source_commit != PREDECESSOR_SOURCE_COMMIT:
        raise QualificationError("frozen predecessor source commit is not canonical")
    for expected_key in mapping.values():
        _require_sha256(expected.get(expected_key), f"frozen predecessor {expected_key}")
    for identity_key, expected_key in mapping.items():
        if identity.get(identity_key) != expected.get(expected_key):
            raise QualificationError(
                f"predecessor identity differs from frozen {expected_key}"
            )


def _load_frozen_from_primary(_C, pufferl, directory: Path, banks: int) -> None:
    if not banks:
        return
    weight_path = directory / f"primary-{os.getpid()}.bin"
    try:
        _C.save_weights(pufferl, str(weight_path))
        for bank in range(banks):
            _C.load_frozen_bank(pufferl, bank, str(weight_path))
    finally:
        weight_path.unlink(missing_ok=True)


def _cell_config(kind: str, cudagraphs: int, args: argparse.Namespace) -> dict[str, Any]:
    if kind in {"construction", "rollout", "terminal_auto", "terminal_control"}:
        return qualification_args(
            cudagraphs=cudagraphs,
            seed=args.seed,
            total_agents=2,
            num_buffers=1,
            num_threads=1,
            horizon=1,
            max_decisions=1 if kind.startswith("terminal_") else 16,
            hidden_size=64,
            num_layers=1,
            frozen_banks=1,
            frozen_bank_pct=0.5,
            learning_rate=0.0,
        )
    if kind == "ratio":
        return qualification_args(
            cudagraphs=0,
            seed=args.seed,
            total_agents=8,
            num_buffers=2,
            num_threads=2,
            horizon=8,
            max_decisions=4,
            hidden_size=64,
            num_layers=1,
            frozen_banks=1,
            frozen_bank_pct=0.5,
            learning_rate=0.0,
        )
    if kind == "throughput":
        return qualification_args(
            cudagraphs=0,
            seed=args.seed,
            total_agents=args.throughput_agents,
            num_buffers=args.throughput_buffers,
            num_threads=args.throughput_threads,
            horizon=args.throughput_horizon,
            max_decisions=64,
            hidden_size=args.throughput_hidden,
            num_layers=args.throughput_layers,
            frozen_banks=1,
            frozen_bank_pct=0.1,
            learning_rate=0.0,
            minibatch_size=args.throughput_minibatch_size,
        )
    raise QualificationError(f"unknown qualification cell: {kind}")


def run_cell(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json).resolve()
    output_npz = Path(args.output_npz).resolve() if args.output_npz else None
    if args.preceding_runtime and args.kind != "throughput":
        raise QualificationError("preceding-runtime mode is throughput-only")
    _C, module = _load_backend(
        Path(args.puffer_root), require_qualification=not args.preceding_runtime
    )
    qualification_surface = all(hasattr(_C, name) for name in (
        "qualification_recurrent_state", "qualification_snapshot",
    ))
    if args.preceding_runtime and qualification_surface:
        raise QualificationError(
            "throughput predecessor unexpectedly exposes qualification bindings"
        )
    config = _cell_config(args.kind, args.cudagraphs, args)
    pufferl = None
    arrays: dict[str, np.ndarray] = {}
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "qualification_only": QUALIFICATION_ONLY,
        "runner_sha256": sha256(Path(__file__).resolve()),
        "kind": args.kind,
        "identity": _module_identity(_C, module, Path(args.puffer_root)),
        "config": config,
        "config_sha256": canonical_hash(config),
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "seed": args.seed,
        "preceding_runtime": bool(args.preceding_runtime),
        "accepted": False,
    }
    validate_module_identity(
        result["identity"], qualification_surface=not args.preceding_runtime
    )
    try:
        pufferl = _C.create_pufferl(config)
        frozen = int(config["vec"]["num_frozen_banks"])
        directory = output_json.parent
        _load_frozen_from_primary(_C, pufferl, directory, frozen)
        if args.kind == "construction":
            state = _C.qualification_recurrent_state(pufferl, False)
            validate_zero_state(state, expected_banks=2, expected_buffers=1)
            result["state"] = state
        elif args.kind == "rollout":
            state = _C.qualification_recurrent_state(pufferl, False)
            validate_zero_state(state, expected_banks=2, expected_buffers=1)
            _C.rollouts(pufferl)
            arrays = decode_snapshot(_C.qualification_snapshot(pufferl))
            result["state_before"] = state
            # Preserve the first-rollout parity snapshot, then deterministically
            # cross max_decisions so at least one complete episode contributes
            # integrity telemetry to this isolated cell.
            bind_transition_integrity(
                _C,
                pufferl,
                result,
                additional_rollouts=int(config["env"]["max_decisions"]),
            )
        elif args.kind in {"terminal_auto", "terminal_control"}:
            _C.set_evaluation_mode(pufferl, True)
            _C.rollouts(pufferl)
            exercised = _C.qualification_recurrent_state(pufferl, False)
            validate_nonzero_state(exercised, expected_banks=2, expected_buffers=1)
            result["state_after_first_rollout"] = exercised
            if args.kind == "terminal_control":
                cleared = _C.qualification_recurrent_state(pufferl, True)
                validate_zero_state(cleared, expected_banks=2, expected_buffers=1)
                result["state_after_control_clear"] = cleared
            _C.rollouts(pufferl)
            arrays = decode_snapshot(_C.qualification_snapshot(pufferl))
            terminals = arrays.get("terminals")
            if terminals is None or terminals.size == 0 or not np.array_equal(
                terminals, np.ones_like(terminals)
            ):
                raise QualificationError("terminal cell did not exercise every row")
            bind_transition_integrity(_C, pufferl, result)
        elif args.kind == "ratio":
            layout_report = _C.qualification_recurrent_state(pufferl, False)
            primary_rows, frozen_rows = derive_row_partition(
                layout_report, total_agents=int(config["vec"]["total_agents"])
            )
            result["row_partition"] = {
                "primary_rows": sorted(primary_rows),
                "frozen_rows": sorted(frozen_rows),
                "state_layout": layout_report,
            }
            _C.rollouts(pufferl)
            bind_transition_integrity(_C, pufferl, result)
            before_path = output_json.parent / f"ratio-before-{os.getpid()}.bin"
            after_path = output_json.parent / f"ratio-after-{os.getpid()}.bin"
            try:
                _C.save_weights(pufferl, str(before_path))
                before_digest = sha256(before_path)
                covered: set[int] = set()
                calls = 0
                while covered != primary_rows and calls < args.ratio_call_limit:
                    _C.train(pufferl)
                    snapshot = decode_snapshot(_C.qualification_snapshot(pufferl))
                    selected = snapshot["selected_rows"].astype(np.int32, copy=False)
                    ratios = snapshot["mb_ratio"].astype(np.float32, copy=False)
                    arrays[f"selected_{calls}"] = selected
                    arrays[f"ratio_{calls}"] = ratios
                    selected_values = {
                        int(value) for value in selected.reshape(-1).tolist()
                    }
                    if selected_values & frozen_rows:
                        raise QualificationError("PPO selected a frozen-bank row")
                    if not selected_values <= primary_rows:
                        raise QualificationError("PPO selected a row outside the bank layout")
                    covered.update(selected_values)
                    calls += 1
                _C.save_weights(pufferl, str(after_path))
                after_digest = sha256(after_path)
            finally:
                before_path.unlink(missing_ok=True)
                after_path.unlink(missing_ok=True)
            validate_weight_identity(before_digest, after_digest)
            result["weights_before_sha256"] = before_digest
            result["weights_after_sha256"] = after_digest
            result["ratio_calls"] = calls
        elif args.kind == "throughput":
            for _ in range(args.throughput_warmup_rollouts):
                _C.rollouts(pufferl)
            _C.log(pufferl)
            start_step = int(pufferl.global_step)
            durations: list[float] = []
            started = time.perf_counter_ns()
            for _ in range(args.throughput_timed_rollouts):
                one = time.perf_counter_ns()
                _C.rollouts(pufferl)
                durations.append((time.perf_counter_ns() - one) / 1.0e9)
            elapsed = (time.perf_counter_ns() - started) / 1.0e9
            end_step = int(pufferl.global_step)
            steps = end_step - start_step
            log = _C.log(pufferl)
            integrity = validate_hard_integrity(dict(log["env"]))
            utilization = dict(_C.get_utilization(0))
            gpu = os.environ.get("QUALIFICATION_GPU_NAME", "")
            if not gpu:
                probe = subprocess.run(
                    ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                    text=True, capture_output=True, check=True, timeout=10,
                )
                gpu = probe.stdout.strip().splitlines()[0]
            result["throughput"] = {
                "host": socket.gethostname(),
                "gpu": gpu,
                "precision_bytes": int(_C.precision_bytes),
                "config_sha256": canonical_hash(config),
                "steps": steps,
                "elapsed_seconds": elapsed,
                "steps_per_second": steps / elapsed,
                "median_rollout_seconds": statistics.median(durations),
                "p95_rollout_seconds": float(np.percentile(durations, 95)),
                "hard_integrity_zero": True,
                "hard_integrity": integrity,
                "utilization": utilization,
            }
        else:  # pragma: no cover - guarded by parser choices
            raise QualificationError(f"unsupported cell {args.kind}")

        if arrays:
            if output_npz is None:
                raise QualificationError("cell produced arrays without an NPZ path")
            write_npz_atomic(output_npz, arrays)
            result["artifact"] = str(output_npz)
            result["artifact_sha256"] = sha256(output_npz)
        result["accepted"] = True
        write_json_atomic(output_json, result)
        return 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        write_json_atomic(output_json, result)
        raise
    finally:
        if pufferl is not None:
            # Puffer 4.0's close path dereferences the absent rollout-graph
            # array when cudagraphs=-1. Graph-off cells are process-isolated,
            # so let process teardown release that CUDA context rather than
            # turning a successful parity cell into an unrelated close crash.
            if int(config["cudagraphs"]) >= 0:
                _C.close(pufferl)


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON artifact is not an object: {path}")
    return value


def _read_npz(path: Path, expected_sha256: str) -> dict[str, np.ndarray]:
    if sha256(path) != expected_sha256:
        raise QualificationError(f"NPZ artifact digest mismatch: {path}")
    try:
        with np.load(path, allow_pickle=False) as payload:
            return {key: payload[key].copy() for key in payload.files}
    except (OSError, ValueError) as exc:
        raise QualificationError(f"cannot read NPZ artifact {path}: {exc}") from exc


def _run_worker(
    args: argparse.Namespace,
    *,
    kind: str,
    name: str,
    cudagraphs: int,
    output: Path,
    preceding_runtime: bool = False,
) -> dict[str, Any]:
    python = Path(args.python).expanduser().absolute() if args.python else (
        Path(args.puffer_root).resolve() / ".venv" / "bin" / "python"
    )
    if not python.is_file():
        raise QualificationError(f"Puffer Python is missing: {python}")
    json_path = output / f"{name}.json"
    npz_path = output / f"{name}.npz"
    command = [
        str(python), str(Path(__file__).resolve()), "cell",
        "--puffer-root", str(Path(args.puffer_root).resolve()),
        "--kind", kind,
        "--cudagraphs", str(cudagraphs),
        "--seed", str(args.seed),
        "--output-json", str(json_path),
        "--output-npz", str(npz_path),
        "--ratio-call-limit", str(args.ratio_call_limit),
        "--throughput-agents", str(args.throughput_agents),
        "--throughput-buffers", str(args.throughput_buffers),
        "--throughput-threads", str(args.throughput_threads),
        "--throughput-horizon", str(args.throughput_horizon),
        "--throughput-hidden", str(args.throughput_hidden),
        "--throughput-layers", str(args.throughput_layers),
        "--throughput-minibatch-size", str(args.throughput_minibatch_size),
        "--throughput-warmup-rollouts", str(args.throughput_warmup_rollouts),
        "--throughput-timed-rollouts", str(args.throughput_timed_rollouts),
    ]
    if preceding_runtime:
        command.append("--preceding-runtime")
    completed = subprocess.run(
        command,
        cwd=Path(args.puffer_root).resolve(),
        text=True,
        capture_output=True,
        timeout=args.cell_timeout_seconds,
    )
    if completed.returncode != 0:
        detail = completed.stderr[-4000:] or completed.stdout[-4000:]
        raise QualificationError(f"qualification cell {name} failed: {detail}")
    record = _read_json(json_path)
    if record.get("accepted") is not True or record.get("qualification_only") is not True:
        raise QualificationError(f"qualification cell {name} is not accepted/isolated")
    if kind in TRANSITION_CELL_KINDS:
        validate_transition_cell_integrity(record, kind)
    record["record_path"] = str(json_path)
    record["record_sha256"] = sha256(json_path)
    return record


def _require_same_identity(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(records)
    if not records:
        raise QualificationError("no cell identities were supplied")
    reference = records[0].get("identity")
    if not isinstance(reference, Mapping):
        raise QualificationError("cell identity is missing")
    for record in records[1:]:
        if record.get("identity") != reference:
            raise QualificationError("compiled module identity drifted between cells")
    return validate_module_identity(reference, qualification_surface=True)


def _require_clean_source_and_external_output(output: Path) -> Path:
    output = Path(output).resolve()
    source_root = Path(__file__).resolve().parents[1]
    try:
        output.relative_to(source_root)
    except ValueError:
        pass
    else:
        raise QualificationError("qualification output must be outside the source checkout")
    source_status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=source_root,
        text=True,
        capture_output=True,
        check=True,
    ).stdout
    if source_status:
        raise QualificationError("qualification source checkout is not clean")
    if output.exists() and any(output.iterdir()):
        raise QualificationError(f"qualification output is not empty: {output}")
    return source_root


def current_runner_source_identity() -> dict[str, str]:
    source_root = Path(__file__).resolve().parents[1]
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"], cwd=source_root,
            text=True, capture_output=True, check=True, timeout=30,
        ).stdout.strip()
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=source_root,
            text=True, capture_output=True, check=True, timeout=30,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=source_root, text=True, capture_output=True, check=True, timeout=30,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise QualificationError(f"cannot inspect control-runner checkout: {exc}") from exc
    if Path(top).resolve() != source_root or status:
        raise QualificationError("control-runner checkout is not exact and clean")
    if GIT_COMMIT_PATTERN.fullmatch(commit) is None:
        raise QualificationError("control-runner commit is malformed")
    try:
        source_root.relative_to(PROTECTED_RECOVERY_ROOT)
    except ValueError:
        pass
    else:
        raise QualificationError("control runner cannot use the protected recovery root")
    return {
        "source_root": str(source_root),
        "source_commit": commit,
        "runner_sha256": sha256(Path(__file__).resolve()),
    }


def validate_source_checkout(
    source_root: Path,
    puffer_root: Path,
    *,
    expected_commit: str,
    role: str,
) -> dict[str, str]:
    """Bind one built Puffer tree to a clean, exact source checkout."""
    if role not in {"candidate", "predecessor"}:
        raise QualificationError("source checkout role is invalid")
    if not isinstance(expected_commit, str) or GIT_COMMIT_PATTERN.fullmatch(
        expected_commit
    ) is None:
        raise QualificationError(f"{role} source commit must be a full lowercase Git SHA")
    canonical_commit = {
        "candidate": CANDIDATE_SOURCE_COMMIT,
        "predecessor": PREDECESSOR_SOURCE_COMMIT,
    }[role]
    if expected_commit != canonical_commit:
        raise QualificationError(f"{role} source commit is not the frozen canonical commit")
    source_root = Path(source_root).resolve()
    puffer_root = Path(puffer_root).resolve()
    try:
        source_root.relative_to(PROTECTED_RECOVERY_ROOT)
    except ValueError:
        pass
    else:
        raise QualificationError(f"{role} cannot use the protected recovery root")
    if puffer_root != source_root / "vendor" / "PufferLib":
        raise QualificationError(
            f"{role} Puffer root is not the isolated tree inside its source checkout"
        )
    try:
        top = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=source_root,
            text=True,
            capture_output=True,
            timeout=30,
        )
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=source_root,
            text=True,
            capture_output=True,
            timeout=30,
        )
        status = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all"],
            cwd=source_root,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except OSError as exc:
        raise QualificationError(f"cannot inspect {role} source checkout: {exc}") from exc
    if top.returncode != 0 or Path(top.stdout.strip()).resolve() != source_root:
        raise QualificationError(f"{role} source root is not an exact Git checkout root")
    if head.returncode != 0 or head.stdout.strip() != expected_commit:
        raise QualificationError(f"{role} source checkout is not at the frozen commit")
    if status.returncode != 0 or status.stdout:
        raise QualificationError(f"{role} source checkout is not clean")
    installer = source_root / "tools" / "install_puffer_env.sh"
    if not installer.is_file():
        raise QualificationError(f"{role} source installer is missing")
    try:
        installer_check = subprocess.run(
            [str(installer), "--check", str(puffer_root)],
            cwd=source_root,
            text=True,
            capture_output=True,
            timeout=300,
        )
    except OSError as exc:
        raise QualificationError(f"cannot check {role} installed runtime: {exc}") from exc
    if installer_check.returncode != 0:
        detail = installer_check.stderr[-4000:] or installer_check.stdout[-4000:]
        raise QualificationError(f"{role} source/module drift check failed: {detail}")
    return {
        "role": role,
        "source_root": str(source_root),
        "source_commit": expected_commit,
        "puffer_root": str(puffer_root),
        "installer_check_sha256": canonical_hash({
            "stdout": installer_check.stdout,
            "stderr": installer_check.stderr,
        }),
    }


def validate_source_checkout_record(
    record: Mapping[str, Any], *, expected_commit: str, role: str
) -> dict[str, str]:
    required = {
        "role", "source_root", "source_commit", "puffer_root",
        "installer_check_sha256",
    }
    if set(record) != required or record.get("role") != role:
        raise QualificationError(f"recorded {role} source identity schema is not exact")
    if record.get("source_commit") != expected_commit:
        raise QualificationError(f"recorded {role} source commit drifted")
    _require_sha256(
        record.get("installer_check_sha256"), f"recorded {role} installer-check digest"
    )
    observed = validate_source_checkout(
        Path(str(record.get("source_root", ""))),
        Path(str(record.get("puffer_root", ""))),
        expected_commit=expected_commit,
        role=role,
    )
    if dict(record) != observed:
        raise QualificationError(f"recorded {role} source checkout drifted")
    return observed


def require_output_outside_source(output: Path, source_root: Path, *, role: str) -> None:
    try:
        Path(output).resolve().relative_to(Path(source_root).resolve())
    except ValueError:
        return
    raise QualificationError(f"qualification output must be outside the {role} checkout")


def require_distinct_source_roots(*roots: Path) -> None:
    resolved = [Path(root).resolve() for root in roots]
    if len(set(resolved)) != len(resolved):
        raise QualificationError("control-runner, predecessor, and candidate roots must differ")


def require_predecessor_source_root(
    supplied_root: Path, recorded_source: Mapping[str, Any]
) -> Path:
    """Require the independently supplied predecessor root to match its artifact."""
    supplied_root = Path(supplied_root).resolve()
    recorded_root = Path(str(recorded_source.get("source_root", ""))).resolve()
    if supplied_root != recorded_root:
        raise QualificationError(
            "baseline predecessor source root differs from the independently supplied root"
        )
    return supplied_root


def _failure_record_output(
    output: Path, args: argparse.Namespace | None = None
) -> Path | None:
    """Return a path that this invocation may safely use for failure evidence."""
    output = Path(output).resolve()
    forbidden = [Path(__file__).resolve().parents[1], PROTECTED_RECOVERY_ROOT]
    if args is not None:
        supplied = vars(args)
        for name in ("candidate_source_root", "predecessor_source_root"):
            value = supplied.get(name)
            if value is not None:
                forbidden.append(Path(value).resolve())
        baseline = supplied.get("baseline_throughput")
        if baseline is not None:
            try:
                wrapper = _read_json(Path(baseline).resolve())
                recorded = wrapper.get("predecessor_source")
                required = {
                    "role", "source_root", "source_commit", "puffer_root",
                    "installer_check_sha256",
                }
                if not isinstance(recorded, Mapping) or set(recorded) != required:
                    raise QualificationError(
                        "baseline predecessor source identity schema is not exact"
                    )
                source_root_value = recorded.get("source_root")
                puffer_root_value = recorded.get("puffer_root")
                expected_commit = supplied.get("expected_predecessor_source_commit")
                if (
                    recorded.get("role") != "predecessor"
                    or not isinstance(source_root_value, str)
                    or not isinstance(puffer_root_value, str)
                    or recorded.get("source_commit") != expected_commit
                ):
                    raise QualificationError(
                        "baseline predecessor source identity is malformed"
                    )
                _require_sha256(
                    recorded.get("installer_check_sha256"),
                    "baseline predecessor installer-check digest",
                )
                source_root = Path(source_root_value)
                puffer_root = Path(puffer_root_value)
                if (
                    not source_root.is_absolute()
                    or puffer_root.resolve()
                    != source_root.resolve() / "vendor" / "PufferLib"
                ):
                    raise QualificationError(
                        "baseline predecessor source paths are malformed"
                    )
                forbidden.append(source_root.resolve())
            except (QualificationError, OSError, TypeError, ValueError):
                return None
    for root in forbidden:
        try:
            output.relative_to(Path(root).resolve())
        except ValueError:
            continue
        return None
    if output.exists():
        if not output.is_dir() or any(output.iterdir()):
            return None
    return output


def run_qualification(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    runner_source_root = _require_clean_source_and_external_output(output)
    runner_source = current_runner_source_identity()
    expected_candidate = {
        "source_commit": args.expected_source_commit,
        "module_sha256": args.expected_candidate_module_sha256,
        "backend_sha256": args.expected_candidate_backend_sha256,
        "environment_sha256": args.expected_environment_sha256,
    }
    expected_predecessor = {
        "source_commit": args.expected_predecessor_source_commit,
        "module_sha256": args.expected_predecessor_module_sha256,
        "backend_sha256": args.expected_predecessor_backend_sha256,
        "environment_sha256": args.expected_environment_sha256,
    }
    candidate_source = validate_source_checkout(
        args.candidate_source_root,
        args.puffer_root,
        expected_commit=expected_candidate["source_commit"],
        role="candidate",
    )
    require_output_outside_source(
        output, Path(candidate_source["source_root"]), role="candidate source"
    )
    baseline_record = validate_baseline_artifact(
        Path(args.baseline_throughput).resolve()
    )
    predecessor_source_root = require_predecessor_source_root(
        args.predecessor_source_root,
        baseline_record["predecessor_source"],
    )
    require_distinct_source_roots(
        runner_source_root,
        Path(candidate_source["source_root"]),
        predecessor_source_root,
    )
    require_output_outside_source(
        output,
        predecessor_source_root,
        role="predecessor source",
    )
    if baseline_record["runner_source"] != runner_source:
        raise QualificationError("baseline was not captured by this control runner")
    if baseline_record["expected_predecessor"] != expected_predecessor:
        raise QualificationError("baseline differs from frozen predecessor identity")
    if expected_candidate["backend_sha256"] != backend_source_hash(args.puffer_root):
        raise QualificationError("current backend sources differ from frozen candidate")
    if expected_candidate["environment_sha256"] != installed_snapshot_hash(
        args.puffer_root
    ):
        raise QualificationError("installed environment differs from frozen candidate")
    output.mkdir(parents=True, exist_ok=True)
    gates: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []

    construction = _run_worker(
        args, kind="construction", name="construction", cudagraphs=0, output=output
    )
    records.append(construction)
    construction_identity = construction.get("identity")
    if not isinstance(construction_identity, Mapping):
        raise QualificationError("construction module identity is missing")
    validate_expected_candidate_identity(construction_identity, expected_candidate)
    if construction_identity.get("puffer_root") != candidate_source["puffer_root"]:
        raise QualificationError("candidate module is outside its frozen source checkout")
    validate_zero_state(
        construction["state"], expected_banks=2, expected_buffers=1
    )
    gates["construction_state"] = {"accepted": True}

    graph_off = _run_worker(
        args, kind="rollout", name="graph-off", cudagraphs=-1, output=output
    )
    graph_on = _run_worker(
        args, kind="rollout", name="graph-on", cudagraphs=0, output=output
    )
    records.extend((graph_off, graph_on))
    identity = _require_same_identity(records)
    validate_current_identity_files(identity)
    precision = int(identity["precision_bytes"])
    graph_atol = GRAPH_ATOL_BY_PRECISION.get(precision)
    if graph_atol is None:
        raise QualificationError(f"unsupported native precision: {precision}")
    graph_off_arrays = _read_npz(
        Path(graph_off["artifact"]), graph_off["artifact_sha256"]
    )
    graph_on_arrays = _read_npz(
        Path(graph_on["artifact"]), graph_on["artifact_sha256"]
    )
    graph_metrics = compare_snapshots(
        graph_off_arrays, graph_on_arrays, atol=graph_atol
    )
    decoder_metrics = compare_decoder_outputs(
        graph_off_arrays, graph_on_arrays, atol=graph_atol
    )
    gates["graph_parity"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        "atol": graph_atol,
        "snapshot_max_abs": graph_metrics,
        "decoder_max_abs": decoder_metrics,
    }

    terminal_auto = _run_worker(
        args, kind="terminal_auto", name="terminal-auto", cudagraphs=0, output=output
    )
    terminal_control = _run_worker(
        args,
        kind="terminal_control",
        name="terminal-control",
        cudagraphs=0,
        output=output,
    )
    records.extend((terminal_auto, terminal_control))
    _require_same_identity(records)
    auto_arrays = _read_npz(
        Path(terminal_auto["artifact"]), terminal_auto["artifact_sha256"]
    )
    control_arrays = _read_npz(
        Path(terminal_control["artifact"]), terminal_control["artifact_sha256"]
    )
    terminal_metrics = compare_snapshots(
        auto_arrays,
        control_arrays,
        atol=graph_atol,
        require_all_terminal=True,
    )
    terminal_decoder = compare_decoder_outputs(
        auto_arrays, control_arrays, atol=graph_atol
    )
    gates["terminal_reset"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        "atol": graph_atol,
        "snapshot_max_abs": terminal_metrics,
        "decoder_max_abs": terminal_decoder,
    }

    ratio = _run_worker(
        args, kind="ratio", name="ratio", cudagraphs=0, output=output
    )
    records.append(ratio)
    _require_same_identity(records)
    ratio_arrays = _read_npz(Path(ratio["artifact"]), ratio["artifact_sha256"])
    row_partition = ratio.get("row_partition")
    if not isinstance(row_partition, Mapping) or not isinstance(
        row_partition.get("state_layout"), Mapping
    ):
        raise QualificationError("ratio row partition evidence is missing")
    primary_rows, frozen_rows = derive_row_partition(
        row_partition["state_layout"],
        total_agents=int(ratio["config"]["vec"]["total_agents"]),
    )
    if row_partition.get("primary_rows") != sorted(primary_rows) or row_partition.get(
        "frozen_rows"
    ) != sorted(frozen_rows):
        raise QualificationError("ratio row partition record differs from bank layout")
    calls = []
    for index in range(int(ratio["ratio_calls"])):
        calls.append(
            {
                "selected_rows": ratio_arrays[f"selected_{index}"].astype(
                    np.int32, copy=False
                ),
                "ratios": ratio_arrays[f"ratio_{index}"].astype(
                    np.float32, copy=False
                ),
            }
        )
    ratio_atol = RATIO_ATOL_BY_PRECISION[precision]
    ratio_metrics = validate_ratio_calls(
        calls, primary_rows=primary_rows, frozen_rows=frozen_rows, atol=ratio_atol
    )
    validate_weight_identity(
        ratio["weights_before_sha256"], ratio["weights_after_sha256"]
    )
    gates["ratio"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        **ratio_metrics,
        "weights_sha256": ratio["weights_before_sha256"],
    }

    throughput = _run_worker(
        args, kind="throughput", name="throughput", cudagraphs=0, output=output
    )
    records.append(throughput)
    _require_same_identity(records)
    validate_predecessor_transition(baseline_record["identity"], identity)
    baseline = baseline_record["throughput"]
    throughput_metrics = validate_throughput(
        throughput["throughput"],
        baseline,
        max_regression_fraction=args.max_regression_fraction,
    )
    gates["throughput"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        **throughput_metrics,
    }

    combined = combine_gate_verdicts(gates)
    final = {
        "schema_version": SCHEMA_VERSION,
        "qualification_only": QUALIFICATION_ONLY,
        "identity": identity,
        "expected_candidate": expected_candidate,
        "expected_predecessor": expected_predecessor,
        "candidate_source": candidate_source,
        "runner_source_commit": subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=runner_source_root,
            text=True,
            capture_output=True,
            check=True,
        ).stdout.strip(),
        "runner_sha256": sha256(Path(__file__).resolve()),
        "source_files": {
            str(path.relative_to(runner_source_root)): sha256(path)
            for path in (
                runner_source_root / "training/puffer_exact_joint_actions.patch",
                runner_source_root / "training/puffer_recurrent_eval_state.patch",
                runner_source_root / "training/puffer_frozen_prio_mask.patch",
                runner_source_root / "training/puffer_recurrent_cuda_qualification.patch",
                runner_source_root / "tools/install_puffer_env.sh",
                Path(__file__).resolve(),
            )
        },
        "max_regression_fraction": args.max_regression_fraction,
        "gates": gates,
        "cells": [
            {
                "name": Path(record["record_path"]).stem,
                "kind": record["kind"],
                "record": record["record_path"],
                "record_sha256": record["record_sha256"],
                "artifact": record.get("artifact"),
                "artifact_sha256": record.get("artifact_sha256"),
            }
            for record in records
        ],
        "throughput_baseline": {
            "path": str(Path(args.baseline_throughput).resolve()),
            "sha256": sha256(Path(args.baseline_throughput).resolve()),
            "cell_record": baseline_record["cell_path"],
            "cell_record_sha256": baseline_record["cell_sha256"],
        },
        "installer_check_sha256": candidate_source["installer_check_sha256"],
        **combined,
    }
    write_json_atomic(output / "QUALIFICATION.json", final)
    return 0 if final["accepted"] else 1


def validate_qualification(path: Path) -> dict[str, Any]:
    qualification_path = Path(path).resolve()
    final = _read_json(qualification_path)
    if final.get("schema_version") != SCHEMA_VERSION:
        raise QualificationError("qualification schema version mismatch")
    if final.get("qualification_only") is not True or final.get("accepted") is not True:
        raise QualificationError("qualification is not an accepted isolated artifact")
    if final.get("runner_sha256") != sha256(Path(__file__).resolve()):
        raise QualificationError("qualification runner identity drifted")
    source_root = Path(__file__).resolve().parents[1]
    current_commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=source_root, text=True,
        capture_output=True, check=True,
    ).stdout.strip()
    current_status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=source_root, text=True,
        capture_output=True, check=True,
    ).stdout
    if current_status or final.get("runner_source_commit") != current_commit:
        raise QualificationError("qualification runner checkout/commit drifted")
    expected_source_files = {
        str(path.relative_to(source_root)): sha256(path)
        for path in (
            source_root / "training/puffer_exact_joint_actions.patch",
            source_root / "training/puffer_recurrent_eval_state.patch",
            source_root / "training/puffer_frozen_prio_mask.patch",
            source_root / "training/puffer_recurrent_cuda_qualification.patch",
            source_root / "tools/install_puffer_env.sh",
            Path(__file__).resolve(),
        )
    }
    if final.get("source_files") != expected_source_files:
        raise QualificationError("qualification source-file identity drifted")
    cells_raw = final.get("cells")
    if not isinstance(cells_raw, list):
        raise QualificationError("qualification cell manifest is missing")
    expected_kinds = {
        "construction": "construction",
        "graph-off": "rollout",
        "graph-on": "rollout",
        "terminal-auto": "terminal_auto",
        "terminal-control": "terminal_control",
        "ratio": "ratio",
        "throughput": "throughput",
    }
    cells: dict[str, dict[str, Any]] = {}
    for entry in cells_raw:
        if not isinstance(entry, Mapping):
            raise QualificationError("qualification cell manifest entry is malformed")
        name = entry.get("name")
        if not isinstance(name, str) or name in cells:
            raise QualificationError("qualification cell name is missing or duplicated")
        record_path = Path(str(entry.get("record", ""))).resolve()
        try:
            record_path.relative_to(qualification_path.parent)
        except ValueError as exc:
            raise QualificationError(
                f"qualification cell record escapes its artifact directory: {name}"
            ) from exc
        expected_record_hash = entry.get("record_sha256")
        if sha256(record_path) != expected_record_hash:
            raise QualificationError(f"qualification cell record drifted: {name}")
        record = _read_json(record_path)
        if (record.get("schema_version") != SCHEMA_VERSION
                or record.get("accepted") is not True
                or record.get("qualification_only") is not True
                or record.get("preceding_runtime") is not False
                or record.get("runner_sha256") != final.get("runner_sha256")):
            raise QualificationError(f"qualification cell is not accepted: {name}")
        if (record.get("kind") != entry.get("kind")
                or expected_kinds.get(name) != record.get("kind")):
            raise QualificationError(f"qualification cell kind drifted: {name}")
        if record["kind"] in TRANSITION_CELL_KINDS:
            validate_transition_cell_integrity(record, record["kind"])
        artifact = entry.get("artifact")
        artifact_hash = entry.get("artifact_sha256")
        expects_artifact = name not in {"construction", "throughput"}
        if (artifact is not None) is not expects_artifact:
            raise QualificationError(f"qualification artifact presence is wrong: {name}")
        if artifact is None:
            if artifact_hash is not None:
                raise QualificationError(f"qualification artifact hash without path: {name}")
        else:
            artifact_path = Path(str(artifact)).resolve()
            try:
                artifact_path.relative_to(qualification_path.parent)
            except ValueError as exc:
                raise QualificationError(
                    f"qualification cell artifact escapes its directory: {name}"
                ) from exc
            if sha256(artifact_path) != artifact_hash:
                raise QualificationError(f"qualification cell artifact drifted: {name}")
            if record.get("artifact") != str(artifact_path) or record.get(
                    "artifact_sha256") != artifact_hash:
                raise QualificationError(f"qualification cell artifact record mismatch: {name}")
        cells[name] = record
    if set(cells) != set(expected_kinds):
        raise QualificationError(
            f"qualification cell set mismatch: {sorted(cells)} != "
            f"{sorted(expected_kinds)}"
        )

    identity = _require_same_identity(cells.values())
    if final.get("identity") != identity:
        raise QualificationError("qualification final identity differs from its cells")
    validate_current_identity_files(identity)
    expected_candidate = final.get("expected_candidate")
    if not isinstance(expected_candidate, Mapping):
        raise QualificationError("frozen candidate identity is missing")
    validate_expected_candidate_identity(identity, expected_candidate)
    candidate_source_raw = final.get("candidate_source")
    if not isinstance(candidate_source_raw, Mapping):
        raise QualificationError("frozen candidate source identity is missing")
    candidate_source = validate_source_checkout_record(
        candidate_source_raw,
        expected_commit=str(expected_candidate.get("source_commit", "")),
        role="candidate",
    )
    if identity.get("puffer_root") != candidate_source["puffer_root"]:
        raise QualificationError("candidate module/source checkout binding drifted")
    _require_sha256(
        final.get("installer_check_sha256"), "qualification installer-check digest"
    )
    if final.get("installer_check_sha256") != candidate_source[
        "installer_check_sha256"
    ]:
        raise QualificationError("qualification candidate installer-check digest drifted")
    precision = int(identity["precision_bytes"])
    if precision not in GRAPH_ATOL_BY_PRECISION or precision not in RATIO_ATOL_BY_PRECISION:
        raise QualificationError(f"unsupported qualification precision: {precision}")

    gates: dict[str, dict[str, Any]] = {}
    validate_zero_state(
        cells["construction"]["state"], expected_banks=2, expected_buffers=1
    )
    gates["construction_state"] = {"accepted": True}

    graph_off = _read_npz(
        Path(cells["graph-off"]["artifact"]),
        cells["graph-off"]["artifact_sha256"],
    )
    graph_on = _read_npz(
        Path(cells["graph-on"]["artifact"]),
        cells["graph-on"]["artifact_sha256"],
    )
    graph_atol = GRAPH_ATOL_BY_PRECISION[precision]
    gates["graph_parity"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        "atol": graph_atol,
        "snapshot_max_abs": compare_snapshots(
            graph_off, graph_on, atol=graph_atol
        ),
        "decoder_max_abs": compare_decoder_outputs(
            graph_off, graph_on, atol=graph_atol
        ),
    }

    terminal_auto = _read_npz(
        Path(cells["terminal-auto"]["artifact"]),
        cells["terminal-auto"]["artifact_sha256"],
    )
    terminal_control = _read_npz(
        Path(cells["terminal-control"]["artifact"]),
        cells["terminal-control"]["artifact_sha256"],
    )
    validate_nonzero_state(
        cells["terminal-auto"]["state_after_first_rollout"],
        expected_banks=2,
        expected_buffers=1,
    )
    validate_nonzero_state(
        cells["terminal-control"]["state_after_first_rollout"],
        expected_banks=2,
        expected_buffers=1,
    )
    validate_zero_state(
        cells["terminal-control"]["state_after_control_clear"],
        expected_banks=2,
        expected_buffers=1,
    )
    gates["terminal_reset"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        "atol": graph_atol,
        "snapshot_max_abs": compare_snapshots(
            terminal_auto,
            terminal_control,
            atol=graph_atol,
            require_all_terminal=True,
        ),
        "decoder_max_abs": compare_decoder_outputs(
            terminal_auto, terminal_control, atol=graph_atol
        ),
    }

    ratio_record = cells["ratio"]
    validate_hard_integrity(ratio_record["hard_integrity"])
    ratio_arrays = _read_npz(
        Path(ratio_record["artifact"]), ratio_record["artifact_sha256"]
    )
    ratio_calls = [
        {
            "selected_rows": ratio_arrays[f"selected_{index}"].astype(
                np.int32, copy=False
            ),
            "ratios": ratio_arrays[f"ratio_{index}"].astype(
                np.float32, copy=False
            ),
        }
        for index in range(int(ratio_record["ratio_calls"]))
    ]
    validate_weight_identity(
        ratio_record["weights_before_sha256"],
        ratio_record["weights_after_sha256"],
    )
    row_partition = ratio_record.get("row_partition")
    if not isinstance(row_partition, Mapping) or not isinstance(
        row_partition.get("state_layout"), Mapping
    ):
        raise QualificationError("ratio row partition evidence is missing")
    primary_rows, frozen_rows = derive_row_partition(
        row_partition["state_layout"],
        total_agents=int(ratio_record["config"]["vec"]["total_agents"]),
    )
    if row_partition.get("primary_rows") != sorted(primary_rows) or row_partition.get(
        "frozen_rows"
    ) != sorted(frozen_rows):
        raise QualificationError("ratio row partition record differs from bank layout")
    gates["ratio"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        **validate_ratio_calls(
            ratio_calls,
            primary_rows=primary_rows,
            frozen_rows=frozen_rows,
            atol=RATIO_ATOL_BY_PRECISION[precision],
        ),
        "weights_sha256": ratio_record["weights_before_sha256"],
    }

    baseline_entry = final.get("throughput_baseline")
    if not isinstance(baseline_entry, Mapping):
        raise QualificationError("throughput baseline manifest is missing")
    baseline_path = Path(str(baseline_entry.get("path", ""))).resolve()
    if sha256(baseline_path) != baseline_entry.get("sha256"):
        raise QualificationError("throughput baseline artifact drifted")
    baseline_record = validate_baseline_artifact(baseline_path)
    require_distinct_source_roots(
        source_root,
        Path(candidate_source["source_root"]),
        Path(baseline_record["predecessor_source"]["source_root"]),
    )
    if (baseline_entry.get("cell_record") != baseline_record["cell_path"]
            or baseline_entry.get("cell_record_sha256") != baseline_record[
                "cell_sha256"
            ]):
        raise QualificationError("throughput baseline cell manifest drifted")
    validate_predecessor_transition(baseline_record["identity"], identity)
    expected_predecessor = final.get("expected_predecessor")
    if (not isinstance(expected_predecessor, Mapping)
            or baseline_record["expected_predecessor"] != expected_predecessor):
        raise QualificationError("frozen predecessor identity drifted")
    validate_expected_predecessor_identity(
        baseline_record["identity"], expected_predecessor
    )
    baseline = baseline_record["throughput"]
    candidate = cells["throughput"]["throughput"]
    validate_hard_integrity(candidate["hard_integrity"])
    validate_hard_integrity(baseline["hard_integrity"])
    regression_fraction = _finite_number(
        final.get("max_regression_fraction"), "recorded regression fraction"
    )
    if regression_fraction != DEFAULT_MAX_REGRESSION_FRACTION:
        raise QualificationError("throughput regression budget is not the frozen value")
    gates["throughput"] = {
        "accepted": True,
        "hard_integrity_zero": True,
        **validate_throughput(
            candidate,
            baseline,
            max_regression_fraction=regression_fraction,
        ),
    }

    if final.get("gates") != gates:
        raise QualificationError("recorded gate metrics differ from recomputed artifacts")
    combined = combine_gate_verdicts(gates)
    if final.get("accepted") != combined["accepted"] or final.get(
            "failed_gates") != combined["failed_gates"]:
        raise QualificationError("top-level qualification verdict is inconsistent")
    return {"accepted": True, "gates": gates, "identity": identity}


def capture_throughput(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    runner_source_root = _require_clean_source_and_external_output(output)
    runner_source = current_runner_source_identity()
    predecessor_source = validate_source_checkout(
        args.predecessor_source_root,
        args.puffer_root,
        expected_commit=args.expected_predecessor_source_commit,
        role="predecessor",
    )
    require_output_outside_source(
        output, Path(predecessor_source["source_root"]), role="predecessor source"
    )
    require_distinct_source_roots(
        runner_source_root, Path(predecessor_source["source_root"])
    )
    output.mkdir(parents=True, exist_ok=True)
    record = _run_worker(
        args, kind="throughput", name="throughput-baseline", cudagraphs=0,
        output=output, preceding_runtime=True,
    )
    expected_predecessor = {
        "source_commit": args.expected_predecessor_source_commit,
        "module_sha256": args.expected_predecessor_module_sha256,
        "backend_sha256": args.expected_predecessor_backend_sha256,
        "environment_sha256": args.expected_environment_sha256,
    }
    validate_expected_predecessor_identity(record["identity"], expected_predecessor)
    if record["identity"].get("puffer_root") != predecessor_source["puffer_root"]:
        raise QualificationError("predecessor module is outside its frozen source checkout")
    cell_path = Path(record["record_path"])
    cell = _read_json(cell_path)
    cell["predecessor_source"] = predecessor_source
    cell["runner_source"] = runner_source
    write_json_atomic(cell_path, cell)
    record["record_sha256"] = sha256(cell_path)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "qualification_only": True,
        "role": "preceding_exact_action_throughput_baseline",
        "runner_sha256": record["runner_sha256"],
        "identity": record["identity"],
        "expected_predecessor": expected_predecessor,
        "predecessor_source": predecessor_source,
        "runner_source": runner_source,
        "throughput": record["throughput"],
        "cell_record": record["record_path"],
        "cell_record_sha256": record["record_sha256"],
    }
    baseline_path = output / "THROUGHPUT_BASELINE.json"
    write_json_atomic(baseline_path, payload)
    validate_baseline_artifact(baseline_path)
    return 0


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--puffer-root", required=True, type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--seed", type=int, default=271828)
    parser.add_argument("--ratio-call-limit", type=int, default=DEFAULT_RATIO_CALL_LIMIT)
    parser.add_argument("--cell-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--throughput-agents", type=int, default=4096)
    parser.add_argument("--throughput-buffers", type=int, default=2)
    parser.add_argument("--throughput-threads", type=int, default=20)
    parser.add_argument("--throughput-horizon", type=int, default=64)
    parser.add_argument("--throughput-hidden", type=int, default=512)
    parser.add_argument("--throughput-layers", type=int, default=1)
    parser.add_argument(
        "--throughput-minibatch-size",
        type=int,
        default=DEFAULT_THROUGHPUT_MINIBATCH_SIZE,
    )
    parser.add_argument("--throughput-warmup-rollouts", type=int, default=2)
    parser.add_argument("--throughput-timed-rollouts", type=int, default=8)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="run every mandatory gate")
    add_common_arguments(run)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--baseline-throughput", required=True, type=Path)
    run.add_argument("--candidate-source-root", required=True, type=Path)
    run.add_argument("--predecessor-source-root", required=True, type=Path)
    run.add_argument("--expected-source-commit", required=True)
    run.add_argument("--expected-candidate-module-sha256", required=True)
    run.add_argument("--expected-candidate-backend-sha256", required=True)
    run.add_argument("--expected-environment-sha256", required=True)
    run.add_argument("--expected-predecessor-source-commit", required=True)
    run.add_argument("--expected-predecessor-module-sha256", required=True)
    run.add_argument("--expected-predecessor-backend-sha256", required=True)
    run.add_argument(
        "--max-regression-fraction",
        type=float,
        default=DEFAULT_MAX_REGRESSION_FRACTION,
    )

    capture = subparsers.add_parser(
        "capture-throughput", help="capture the preceding-runtime control"
    )
    add_common_arguments(capture)
    capture.add_argument("--output", required=True, type=Path)
    capture.add_argument("--predecessor-source-root", required=True, type=Path)
    capture.add_argument("--expected-predecessor-source-commit", required=True)
    capture.add_argument("--expected-predecessor-module-sha256", required=True)
    capture.add_argument("--expected-predecessor-backend-sha256", required=True)
    capture.add_argument("--expected-environment-sha256", required=True)

    validate = subparsers.add_parser(
        "validate", help="independently recompute an existing qualification"
    )
    validate.add_argument("qualification", type=Path)

    cell = subparsers.add_parser("cell", help=argparse.SUPPRESS)
    add_common_arguments(cell)
    cell.add_argument(
        "--kind",
        required=True,
        choices=(
            "construction", "rollout", "terminal_auto", "terminal_control",
            "ratio", "throughput",
        ),
    )
    cell.add_argument("--cudagraphs", type=int, required=True)
    cell.add_argument("--output-json", required=True, type=Path)
    cell.add_argument("--output-npz", type=Path)
    cell.add_argument("--preceding-runtime", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "validate":
        validate_qualification(args.qualification)
        return 0
    if args.ratio_call_limit <= 0:
        raise QualificationError("ratio call limit must be positive")
    if args.throughput_warmup_rollouts < 0 or args.throughput_timed_rollouts <= 0:
        raise QualificationError("throughput rollout counts are invalid")
    if (
        args.command in {"run", "capture-throughput"}
        and args.throughput_minibatch_size
        != DEFAULT_THROUGHPUT_MINIBATCH_SIZE
    ):
        raise QualificationError(
            "operator throughput minibatch is frozen at the exact-action "
            f"canary value {DEFAULT_THROUGHPUT_MINIBATCH_SIZE}"
        )
    validate_throughput_minibatch(
        args.throughput_agents,
        args.throughput_horizon,
        args.throughput_minibatch_size,
    )
    if args.command == "cell":
        return run_cell(args)
    if args.command == "capture-throughput":
        return capture_throughput(args)
    if args.command == "run":
        if args.max_regression_fraction != DEFAULT_MAX_REGRESSION_FRACTION:
            raise QualificationError("throughput regression budget is frozen at 0.10")
        failure_output = _failure_record_output(args.output, args)
        try:
            return run_qualification(args)
        except Exception as exc:
            if failure_output is not None:
                try:
                    write_json_atomic(failure_output / "QUALIFICATION.json", {
                        "schema_version": SCHEMA_VERSION,
                        "qualification_only": QUALIFICATION_ONLY,
                        "accepted": False,
                        "error": f"{type(exc).__name__}: {exc}",
                        "mandatory_gates": list(MANDATORY_GATES),
                    })
                except Exception:
                    # Preserve the qualification error if best-effort failure
                    # evidence cannot be written.
                    pass
            raise
    raise QualificationError(f"unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QualificationError as exc:
        print(f"qualification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
