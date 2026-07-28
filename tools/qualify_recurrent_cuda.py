#!/usr/bin/env python3
"""Recurrent CUDA smoke test for the native Blood Bowl backend.

Every measurement runs in a fresh subprocess, because CUDA runtime
initialization order, graph capture, and recurrent state all have to start
clean. Re-run it whenever you rebuild; it overwrites its own output directory.

    tools/qualify_recurrent_cuda.py run --puffer-root <tree> --output <dir>
        [--baseline-throughput <previous QUALIFICATION.json>]

Gates, and the bug each one caught:

  construction_state  recurrent state exactly zero in every primary and frozen
                      bank/buffer at construction.
  graph_parity        cudagraph-on and cudagraph-off first rollouts agree:
                      bitwise on discrete fields, within fp32 tolerance on
                      values/logprobs and decoder outputs.
  terminal_reset      state nonzero after a rollout, and the automatic terminal
                      reset matches an explicit all-bank zero control.
  ratio               real PPO calls at learning_rate=0 recompute ratio == 1
                      over every learner row, never select a frozen row (even
                      at prio_alpha=0), and leave the weight bytes unchanged.
  throughput          steps/second on the target GPU, optionally compared
                      against a previous run's number.

Every transition-executing cell must also report all 16 hard-integrity
counters at exactly zero. Qualification is fp32-only: BF16 rounds the stored
behavior log probability before recomputation, so the near-unity ratio contract
does not hold there. These artifacts are diagnostic, never checkpoint ancestry.
"""

from __future__ import annotations

import argparse
import configparser
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import re
import socket
import stat
import statistics
import subprocess
import sys
import tempfile
import time
from typing import Any, Iterable, Mapping

import numpy as np

try:
    from puffer_source_manifest import (
        read_source_ledger,
        source_manifest_sha256,
    )
except ModuleNotFoundError:  # Imported as tools.qualify_recurrent_cuda in tests.
    from tools.puffer_source_manifest import (
        read_source_ledger,
        source_manifest_sha256,
    )

try:
    from puffer_cuda_runtime import (
        CudaRuntimePreflightError,
        begin_cuda_runtime_preflight,
        finish_cuda_runtime_preflight,
        validate_cuda_runtime_evidence,
        validate_cuda_runtime_library_file,
    )
except ModuleNotFoundError:  # Imported as tools.qualify_recurrent_cuda in tests.
    from tools.puffer_cuda_runtime import (
        CudaRuntimePreflightError,
        begin_cuda_runtime_preflight,
        finish_cuda_runtime_preflight,
        validate_cuda_runtime_evidence,
        validate_cuda_runtime_library_file,
    )


SCHEMA_VERSION = 5
ENVIRONMENT_CONFIG_SCHEMA = "bloodbowl-environment-config-v1"
ENVIRONMENT_CONFIG_KEY_COUNT = 51
MANDATORY_GATES = (
    "strict_environment_config",
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
TRANSITION_CELL_KINDS = frozenset(
    {"rollout", "terminal_auto", "terminal_control", "ratio", "throughput"}
)
STRICT_CONFIG_NEGATIVE_CELL_KINDS = (
    "strict_negative_create_vec",
    "strict_negative_create_pufferl",
)
STRICT_CONFIG_POSITIVE_CELL_KINDS = (
    "strict_positive_full",
    "strict_positive_sparse",
)
STRICT_CONFIG_CELL_KINDS = (
    *STRICT_CONFIG_NEGATIVE_CELL_KINDS,
    *STRICT_CONFIG_POSITIVE_CELL_KINDS,
)
CELL_KINDS = (
    "construction",
    *STRICT_CONFIG_CELL_KINDS,
    *sorted(TRANSITION_CELL_KINDS),
)
GRAPH_ATOL_BY_PRECISION = {4: 1.0e-6}
RATIO_ATOL_BY_PRECISION = {4: 2.0e-5}
DEFAULT_RATIO_CALL_LIMIT = 64
DEFAULT_MAX_REGRESSION_FRACTION = 0.10
# Puffer's cudagraph setting is a warmup-epoch count, not a boolean. 0 captures
# the first execution before CUDA lazy initialization; -1 means graphs off.
DEFAULT_CUDAGRAPH_WARMUP_EPOCHS = 10
DEFAULT_THROUGHPUT_MINIBATCH_SIZE = 16384
REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_PUFFER_COMMIT = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"
STRICT_STAGE_SCHEMA_VERSION = 1
STRICT_STAGE_EVIDENCE_KIND = "bloodbowl-strict-cuda-stage-order"
STRICT_STAGE_RECEIPT_KIND = "bloodbowl-strict-cuda-stage-isolation"
STRICT_STAGE_MAX_JSON_BYTES = 64 * 1024
STRICT_STAGE_MESSAGE_MAX_BYTES = 512
STRICT_STAGE_PATH_MAX_BYTES = 4096
STRICT_STAGE_HOST_MAX_BYTES = 255
STRICT_STAGE_PLATFORM_MAX_BYTES = 512
STRICT_STAGE_KEYS = (
    "normalize_calls",
    "normalize_gil_held_calls",
    "create_static_vec_calls",
    "cuda_get_device_count_calls",
    "create_pufferl_impl_calls",
)
STRICT_STAGE_ZERO = dict.fromkeys(STRICT_STAGE_KEYS, 0)
STRICT_STAGE_REJECTED = {
    **STRICT_STAGE_ZERO,
    "normalize_calls": 1,
    "normalize_gil_held_calls": 1,
}
STRICT_STAGE_POSITIVE = {
    "create_vec": {
        **STRICT_STAGE_REJECTED,
        "create_static_vec_calls": 1,
    },
    "create_pufferl": {
        **STRICT_STAGE_REJECTED,
        "cuda_get_device_count_calls": 1,
        "create_pufferl_impl_calls": 1,
    },
}
STRICT_STAGE_HAZARDS = ("vec", "train", "policy", "device")
STRICT_STAGE_HAZARD_PATHS = {
    "vec": "vec.total_agents",
    "train": "train",
    "policy": "policy",
    "device": "gpu_id",
}
STRICT_STAGE_MODULE_IDENTITY_KEYS = (
    "module",
    "puffer_root",
    "module_sha256",
    "compiled_backend_sha256",
    "backend_sources_sha256",
    "environment_sha256",
    "installed_snapshot_sha256",
    "observation_abi",
    "observation_version",
    "action_abi",
    "environment_config_schema",
    "strict_env_config_testing",
    "precision_bytes",
    "compiled_env",
    "qualification_surface",
    "gpu",
    "strict_stage_surface",
)
STRICT_STAGE_INTERPRETER_IDENTITY_KEYS = (
    "executable",
    "executable_sha256",
    "prefix",
    "base_prefix",
    "ext_suffix",
    "python_version",
    "pybind11_path",
    "numpy_path",
)
STRICT_ENV_CONFIG_PATCH = REPO_ROOT / "training/puffer_strict_environment_config.patch"
COMPILED_BACKEND_SOURCE_LEDGER = (
    REPO_ROOT / "training/puffer_compiled_backend_sources.txt"
)
BACKEND_SOURCE_FILES = read_source_ledger(
    COMPILED_BACKEND_SOURCE_LEDGER,
    expected_count=9,
)
QUALIFICATION_SURFACE_BINDINGS = (
    "qualification_recurrent_state",
    "qualification_snapshot",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STRICT_INVALID_TEAM_DIAGNOSTIC = (
    "force_home_team must be integer -1 or 0..BB_TEAM_COUNT-1"
)


class QualificationError(RuntimeError):
    """A missing, malformed, drifted, or failed qualification predicate."""


def _num(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise QualificationError(f"{label} must be numeric")
    if not math.isfinite(float(value)):
        raise QualificationError(f"{label} must be finite")
    return float(value)


def _int(value: Any, label: str, *, minimum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise QualificationError(f"{label} must be an integer")
    if minimum is not None and value < minimum:
        raise QualificationError(f"{label} must be at least {minimum}")
    return value


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise QualificationError(f"{label} must be a lowercase SHA-256 digest")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def write_bounded_json_atomic(
    path: Path,
    payload: Mapping[str, Any],
    *,
    maximum_bytes: int = STRICT_STAGE_MAX_JSON_BYTES,
) -> None:
    """Durably replace one bounded JSON object without a partial artifact."""

    if maximum_bytes <= 0:
        raise QualificationError("bounded JSON maximum must be positive")
    try:
        encoded = (
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise QualificationError(f"bounded JSON payload is invalid: {exc}") from exc
    if len(encoded) > maximum_bytes:
        raise QualificationError(
            f"bounded JSON payload is {len(encoded)} bytes; "
            f"limit is {maximum_bytes}"
        )
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.tmp.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _bounded_text(
    value: Any, maximum_bytes: int = STRICT_STAGE_MESSAGE_MAX_BYTES
) -> str:
    """Return a UTF-8-safe diagnostic whose encoded size is strictly bounded."""

    text = str(value)
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= maximum_bytes:
        return text
    suffix = b"..."
    clipped = encoded[: maximum_bytes - len(suffix)]
    while clipped:
        try:
            return clipped.decode("utf-8") + suffix.decode("ascii")
        except UnicodeDecodeError:
            clipped = clipped[:-1]
    return suffix.decode("ascii")


def write_npz_atomic(path: Path, arrays: Mapping[str, np.ndarray]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.tmp.", suffix=".npz", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            np.savez(handle, **arrays)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _read_json(
    path: Path,
    *,
    maximum_bytes: int | None = None,
    require_regular: bool = False,
) -> dict[str, Any]:
    artifact = Path(path)
    try:
        if maximum_bytes is not None:
            if maximum_bytes <= 0:
                raise QualificationError("JSON artifact byte limit must be positive")
            metadata = artifact.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise QualificationError(
                    f"JSON artifact is not a regular non-symlink file: {artifact}"
                )
            if metadata.st_size > maximum_bytes:
                raise QualificationError(
                    f"JSON artifact exceeds {maximum_bytes} bytes: {artifact}"
                )
        elif require_regular:
            metadata = artifact.lstat()
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
                raise QualificationError(
                    f"JSON artifact is not a regular non-symlink file: {artifact}"
                )

        if maximum_bytes is None:
            encoded = artifact.read_bytes()
        else:
            with artifact.open("rb") as handle:
                opened = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_dev != metadata.st_dev
                    or opened.st_ino != metadata.st_ino
                ):
                    raise QualificationError(
                        f"JSON artifact changed type while opening: {artifact}"
                    )
                encoded = handle.read(maximum_bytes + 1)
            if len(encoded) > maximum_bytes:
                raise QualificationError(
                    f"JSON artifact exceeds {maximum_bytes} bytes: {artifact}"
                )
        value = json.loads(encoded.decode("utf-8"))
    except QualificationError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON artifact is not an object: {path}")
    return value


def _read_npz(path: Path) -> dict[str, np.ndarray]:
    try:
        with np.load(path, allow_pickle=False) as payload:
            return {key: payload[key].copy() for key in payload.files}
    except (OSError, ValueError) as exc:
        raise QualificationError(f"cannot read NPZ artifact {path}: {exc}") from exc


# ---------------------------------------------------------------- state evidence


def _state_entries(
    report: Mapping[str, Any], banks: int, buffers: int
) -> list[Mapping[str, Any]]:
    """Every (bank, buffer) appears exactly once with a self-coherent shape."""
    if report.get("num_banks") != banks or report.get("num_buffers") != buffers:
        raise QualificationError("state report bank/buffer dimensions mismatch")
    entries = report.get("entries")
    if not isinstance(entries, list):
        raise QualificationError("state report entries must be a list")
    observed: set[tuple[int, int]] = set()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise QualificationError("state entry must be an object")
        key = (
            _int(entry.get("bank"), "state bank"),
            _int(entry.get("buffer"), "state buffer"),
        )
        if key in observed:
            raise QualificationError(f"duplicate state entry {key}")
        observed.add(key)
        shape = entry.get("shape")
        if not isinstance(shape, list) or len(shape) < 3:
            raise QualificationError("state tensor shape is malformed")
        for value in shape:
            _int(value, "state tensor dimension", minimum=1)
        rows = _int(entry.get("active_rows"), "state active-row count", minimum=1)
        elements = math.prod(shape)
        if (
            rows > shape[1]
            or entry.get("elements") != elements
            or entry.get("active_elements") != elements // shape[1] * rows
        ):
            raise QualificationError("state element counts differ from shape")
    if observed != {(b, f) for b in range(banks) for f in range(buffers)}:
        raise QualificationError(f"state coverage mismatch: {sorted(observed)}")
    return entries


def validate_zero_state(
    report: Mapping[str, Any], *, expected_banks: int, expected_buffers: int
) -> None:
    """Exact zero, not near zero, in every bank/buffer and every active row."""
    for entry in _state_entries(report, expected_banks, expected_buffers):
        for key in ("nonzero", "nonfinite", "active_nonzero", "active_nonfinite"):
            if entry.get(key) != 0:
                raise QualificationError(
                    f"state {key}={entry.get(key)} is not zero at "
                    f"bank={entry['bank']} buffer={entry['buffer']}"
                )
        for key in ("max_abs", "active_max_abs"):
            if _num(entry.get(key), f"state {key}") != 0.0:
                raise QualificationError(f"state {key} is not exactly zero")


def validate_nonzero_state(
    report: Mapping[str, Any], *, expected_banks: int, expected_buffers: int
) -> None:
    """The recurrent path really ran in every bank/buffer, and stayed finite."""
    for entry in _state_entries(report, expected_banks, expected_buffers):
        if _int(entry.get("active_nonzero"), "active nonzero count") <= 0:
            raise QualificationError(
                f"state path was not exercised at bank={entry['bank']} "
                f"buffer={entry['buffer']}"
            )
        if entry.get("nonfinite") != 0 or entry.get("active_nonfinite") != 0:
            raise QualificationError(
                "exercised recurrent state contains non-finite values"
            )
        if _num(entry.get("active_max_abs"), "active state max_abs") <= 0.0:
            raise QualificationError("nonzero state has non-positive max_abs")


def derive_row_partition(
    report: Mapping[str, Any], *, total_agents: int
) -> tuple[set[int], set[int]]:
    """Split rows into learner-owned and frozen-bank from the native layout."""
    banks = _int(report.get("num_banks"), "row partition num_banks", minimum=1)
    buffers = _int(report.get("num_buffers"), "row partition num_buffers", minimum=1)
    per_buffer = _int(
        report.get("agents_per_buffer"), "row partition agents_per_buffer", minimum=1
    )
    layout = report.get("bank_layout")
    if total_agents != buffers * per_buffer:
        raise QualificationError("row partition total-agent count is inconsistent")
    if not isinstance(layout, list) or len(layout) != banks + 1:
        raise QualificationError("row partition bank layout is malformed")
    for value in layout:
        _int(value, "row partition bank boundary")
    if (
        layout[0] != 0
        or layout[-1] != per_buffer
        or any(left >= right for left, right in zip(layout, layout[1:]))
    ):
        raise QualificationError("row partition bank layout is not a strict partition")
    if banks < 2:
        raise QualificationError("ratio qualification requires a real frozen bank")
    primary: set[int] = set()
    frozen: set[int] = set()
    for buffer in range(buffers):
        offset = buffer * per_buffer
        primary.update(range(offset, offset + layout[1]))
        frozen.update(range(offset + layout[1], offset + per_buffer))
    if (
        not primary
        or not frozen
        or primary & frozen
        or primary | frozen != set(range(total_agents))
    ):
        raise QualificationError(
            "row partition does not cover disjoint learner/frozen rows"
        )
    return primary, frozen


# ------------------------------------------------------- rollout / PPO evidence


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
    """Discrete fields must be bitwise equal; floats within one fp32 tolerance."""
    tolerance = _num(atol, "snapshot atol")
    if tolerance < 0:
        raise QualificationError("snapshot atol must be nonnegative")
    missing = [key for key in SNAPSHOT_FIELDS if key not in left or key not in right]
    if missing:
        raise QualificationError(f"snapshot fields are missing: {missing}")
    maxima: dict[str, float] = {}
    for key in EXACT_SNAPSHOT_FIELDS:
        a, b = _validate_array_pair(key, left[key], right[key])
        if not np.array_equal(a, b):
            raise QualificationError(f"exact snapshot field {key} differs")
        maxima[key] = 0.0
    for key in FLOAT_SNAPSHOT_FIELDS:
        maxima[key] = _max_abs_error(key, left[key], right[key], tolerance)
    if require_all_terminal:
        terminals = left["terminals"]
        if terminals.size == 0 or not np.array_equal(
            terminals, np.ones_like(terminals)
        ):
            raise QualificationError(
                "post-terminal snapshot does not mark every row terminal"
            )
    return maxima


def _max_abs_error(key: str, left: Any, right: Any, tolerance: float) -> float:
    a, b = _validate_array_pair(key, left, right)
    maximum = float(np.max(np.abs(a - b))) if a.size else 0.0
    if maximum > tolerance:
        raise QualificationError(
            f"field {key} max abs error {maximum} exceeds {tolerance}"
        )
    return maximum


def compare_decoder_outputs(
    left: Mapping[str, np.ndarray], right: Mapping[str, np.ndarray], *, atol: float
) -> dict[str, float]:
    keys = {key for key in left if key.startswith("decoder_bank_")}
    if not keys or keys != {key for key in right if key.startswith("decoder_bank_")}:
        raise QualificationError("decoder bank/buffer coverage mismatch")
    return {
        key: _max_abs_error(key, left[key], right[key], atol) for key in sorted(keys)
    }


def validate_ratio_calls(
    calls: Iterable[Mapping[str, np.ndarray]],
    *,
    primary_rows: set[int],
    frozen_rows: set[int],
    atol: float,
) -> dict[str, Any]:
    """Ratio == 1 at lr=0, every learner row covered, no frozen row selected."""
    if not primary_rows or primary_rows & frozen_rows:
        raise QualificationError("ratio row partition is invalid")
    tolerance = _num(atol, "ratio atol")
    if tolerance < 0:
        raise QualificationError("ratio atol must be nonnegative")
    covered: set[int] = set()
    maximum, elements, attempts = 0.0, 0, 0
    for call in calls:
        attempts += 1
        selected, ratios = call.get("selected_rows"), call.get("ratios")
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
        observed = float(np.max(delta)) if delta.size else 0.0
        maximum = max(maximum, observed)
        if observed > tolerance:
            raise QualificationError(
                f"recomputed ratio error {observed} exceeds {tolerance}"
            )
        for raw in selected.tolist():
            row = int(raw)
            if row in frozen_rows:
                raise QualificationError(f"PPO selected frozen row {row}")
            if row not in primary_rows:
                raise QualificationError(f"PPO selected unknown row {row}")
            covered.add(row)
        elements += int(ratios.size)
    if covered != primary_rows:
        raise QualificationError(
            f"ratio coverage incomplete: covered={sorted(covered)}, "
            f"required={sorted(primary_rows)}"
        )
    return {
        "attempts": attempts,
        "ratio_elements": elements,
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


# ------------------------------------------------------ hard-integrity counters


def validate_hard_integrity(env: Mapping[str, Any]) -> dict[str, float]:
    """All 16 counters present and at literal zero. Missing != explicit zero."""
    result: dict[str, float] = {}
    for key in HARD_INTEGRITY_KEYS:
        if key not in env:
            raise QualificationError(f"hard-integrity field is missing: {key}")
        value = _num(env[key], f"hard-integrity field {key}")
        if value != 0.0:
            raise QualificationError(f"hard-integrity field is nonzero: {key}={value}")
        result[key] = value
    return result


def bind_transition_integrity(
    backend: Any, pufferl: Any, record: dict[str, Any], *, additional_rollouts: int = 0
) -> dict[str, float]:
    """Finish a bounded telemetry interval and bind its exact-zero verdict."""
    for _ in range(
        _int(additional_rollouts, "additional integrity rollouts", minimum=0)
    ):
        backend.rollouts(pufferl)
    log = backend.log(pufferl)
    if not isinstance(log, Mapping) or not isinstance(log.get("env"), Mapping):
        raise QualificationError("transition integrity log/env telemetry is missing")
    record["hard_integrity"] = validate_hard_integrity(log["env"])
    record["hard_integrity_zero"] = True
    return record["hard_integrity"]


def validate_transition_cell_integrity(
    record: Mapping[str, Any], kind: str
) -> dict[str, float]:
    if kind not in TRANSITION_CELL_KINDS:
        raise QualificationError(
            f"qualification cell {kind} does not execute transitions"
        )
    if record.get("kind") != kind:
        raise QualificationError(f"qualification cell kind mismatch for {kind}")
    payload = record.get("throughput") if kind == "throughput" else record
    if not isinstance(payload, Mapping):
        raise QualificationError(
            f"qualification cell integrity payload is missing: {kind}"
        )
    integrity = validate_hard_integrity(payload.get("hard_integrity", {}))
    if payload.get("hard_integrity_zero") is not True:
        raise QualificationError(
            f"qualification cell hard-integrity verdict is not zero: {kind}"
        )
    return integrity


# ------------------------------------------------------------------- throughput


def _validate_throughput_record(record: Mapping[str, Any], label: str) -> None:
    for key in ("host", "gpu"):
        if not isinstance(record.get(key), str) or not record.get(key):
            raise QualificationError(f"{label} throughput {key} is missing")
    if record.get("precision_bytes") not in GRAPH_ATOL_BY_PRECISION:
        raise QualificationError(f"{label} throughput precision is unsupported")
    steps = _int(record.get("steps"), f"{label} throughput step count", minimum=1)
    elapsed = _num(record.get("elapsed_seconds"), f"{label} throughput elapsed time")
    sps = _num(record.get("steps_per_second"), f"{label} throughput rate")
    if (
        elapsed <= 0
        or sps <= 0
        or not math.isclose(sps, steps / elapsed, rel_tol=1.0e-12, abs_tol=0.0)
    ):
        raise QualificationError(f"{label} throughput rate is internally inconsistent")
    median = _num(record.get("median_rollout_seconds"), f"{label} median rollout")
    p95 = _num(record.get("p95_rollout_seconds"), f"{label} p95 rollout")
    if median <= 0 or p95 < median:
        raise QualificationError(f"{label} throughput rollout timing is invalid")
    validate_hard_integrity(record.get("hard_integrity", {}))
    if record.get("hard_integrity_zero") is not True:
        raise QualificationError(f"{label} throughput hard-integrity gate is not zero")


def validate_throughput(
    candidate: Mapping[str, Any],
    baseline: Mapping[str, Any],
    *,
    max_regression_fraction: float,
) -> dict[str, float]:
    """Compare two throughput records measured on the same host/GPU/config."""
    _validate_throughput_record(candidate, "candidate")
    _validate_throughput_record(baseline, "baseline")
    limit = _num(max_regression_fraction, "throughput regression fraction")
    if limit < 0 or limit >= 1:
        raise QualificationError("throughput regression fraction must be in [0, 1)")
    for key in ("host", "gpu", "precision_bytes", "config"):
        if candidate.get(key) != baseline.get(key):
            raise QualificationError(f"throughput identity mismatch for {key}")
    candidate_sps = float(candidate["steps_per_second"])
    baseline_sps = float(baseline["steps_per_second"])
    floor = baseline_sps * (1.0 - limit)
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


def combine_gate_verdicts(gates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    if set(gates) != set(MANDATORY_GATES):
        raise QualificationError(
            f"mandatory gate set mismatch: {sorted(gates)} != {sorted(MANDATORY_GATES)}"
        )
    return {
        "accepted": all(gate.get("accepted") is True for gate in gates.values()),
        "mandatory_gates": list(MANDATORY_GATES),
        "failed_gates": sorted(
            name for name, gate in gates.items() if gate.get("accepted") is not True
        ),
    }


# -------------------------------------------------------- native tensor decoding


def _decode_tensor(record: Mapping[str, Any]) -> np.ndarray:
    dtype, shape_raw, data = (
        record.get("dtype"),
        record.get("shape"),
        record.get("data"),
    )
    if not isinstance(shape_raw, list):
        raise QualificationError("native tensor shape is malformed")
    for value in shape_raw:
        _int(value, "native tensor dimension", minimum=0)
    if not isinstance(data, bytes):
        raise QualificationError("native tensor payload is not bytes")
    shape = tuple(shape_raw)
    elements = math.prod(shape) if shape else 0
    width = {"f32": 4, "bf16": 2, "i32": 4}.get(str(dtype))
    if width is None:
        raise QualificationError(f"unsupported native tensor dtype: {dtype!r}")
    if len(data) != elements * width:
        raise QualificationError(f"{dtype} tensor byte count mismatch")
    if dtype == "i32":
        return np.frombuffer(data, dtype="<i4").copy().reshape(shape)
    if dtype == "f32":
        array = np.frombuffer(data, dtype="<f4").copy()
    else:
        words = np.frombuffer(data, dtype="<u2").astype(np.uint32)
        array = (words << np.uint32(16)).view(np.float32).copy()
    return array.reshape(shape).astype(np.float32, copy=False)


def decode_snapshot(raw: Mapping[str, Any]) -> dict[str, np.ndarray]:
    tensors, decoders = raw.get("tensors"), raw.get("decoder_outputs")
    if not isinstance(tensors, Mapping) or not isinstance(decoders, list):
        raise QualificationError("native snapshot structure is malformed")
    banks = _int(raw.get("num_banks"), "snapshot num_banks", minimum=1)
    buffers = _int(raw.get("num_buffers"), "snapshot num_buffers", minimum=1)
    arrays = {str(key): _decode_tensor(value) for key, value in tensors.items()}
    seen: set[tuple[int, int]] = set()
    for entry in decoders:
        if not isinstance(entry, Mapping):
            raise QualificationError("decoder snapshot entry is malformed")
        key = (
            _int(entry.get("bank"), "decoder bank"),
            _int(entry.get("buffer"), "decoder buffer"),
        )
        rows = _int(entry.get("active_rows"), "decoder active rows", minimum=1)
        if key in seen:
            raise QualificationError(f"duplicate decoder snapshot {key}")
        seen.add(key)
        decoded = _decode_tensor(entry.get("tensor"))
        if decoded.ndim < 1 or decoded.shape[0] != rows:
            raise QualificationError("decoder snapshot includes inactive rows")
        arrays[f"decoder_bank_{key[0]}_buffer_{key[1]}"] = decoded
    if seen != {(b, f) for b in range(banks) for f in range(buffers)}:
        raise QualificationError("decoder snapshot bank/buffer coverage is incomplete")
    return arrays


# ------------------------------------------------------------ cell configuration


def validate_throughput_minibatch(
    total_agents: int, horizon: int, minibatch_size: int
) -> int:
    quantum = total_agents * horizon
    if (
        total_agents <= 0
        or horizon <= 0
        or minibatch_size <= 0
        or minibatch_size % horizon
        or minibatch_size > quantum
        or quantum % minibatch_size
    ):
        raise QualificationError(
            "minibatch_size must be positive, horizon-divisible, no larger than "
            "the rollout quantum, and divide it exactly"
        )
    return minibatch_size


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
    minibatch_size = validate_throughput_minibatch(
        total_agents,
        horizon,
        total_agents * horizon if minibatch_size is None else minibatch_size,
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


def validate_cell_cudagraphs(kind: str, cudagraphs: int) -> int:
    """Graphs off is -1 and only meaningful for the parity rollout cell."""
    if cudagraphs == -1:
        if kind == "rollout":
            return cudagraphs
        raise QualificationError(
            "cudagraphs=-1 is reserved for the explicit graph-off rollout cell"
        )
    if cudagraphs != DEFAULT_CUDAGRAPH_WARMUP_EPOCHS:
        raise QualificationError(
            "graph-enabled qualification cells require the trainer's warmup "
            f"boundary {DEFAULT_CUDAGRAPH_WARMUP_EPOCHS}; 0 captures before CUDA "
            "lazy initialization"
        )
    return cudagraphs


def validate_cell_cudagraph_record(
    record: Mapping[str, Any], *, expected: int, rehash_cuda_runtime: bool = False
) -> dict[str, Any]:
    """A cell must report the graph mode and CUDA runtime it actually ran."""
    config = record.get("config")
    if not isinstance(config, Mapping):
        raise QualificationError("qualification cell config is missing")
    if _int(config.get("cudagraphs"), "qualification cell cudagraphs") != expected:
        raise QualificationError(
            "qualification cell cudagraph warmup differs from its requested role"
        )
    try:
        evidence = record.get("cuda_runtime_preflight")
        validate_cuda_runtime_evidence(evidence)
        if rehash_cuda_runtime:
            validate_cuda_runtime_library_file(evidence)
    except CudaRuntimePreflightError as exc:
        raise QualificationError(
            f"qualification CUDA runtime evidence failed: {exc}"
        ) from exc
    return dict(config)


def _cell_config(
    kind: str, cudagraphs: int, args: argparse.Namespace
) -> dict[str, Any]:
    cudagraphs = validate_cell_cudagraphs(kind, cudagraphs)
    if kind in STRICT_CONFIG_CELL_KINDS:
        return qualification_args(
            cudagraphs=cudagraphs,
            seed=args.seed,
            total_agents=2,
            num_buffers=1,
            num_threads=1,
            horizon=1,
            max_decisions=16,
            hidden_size=64,
            num_layers=1,
            frozen_banks=0,
            frozen_bank_pct=0.0,
            learning_rate=0.0,
        )
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
            cudagraphs=cudagraphs,
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
            cudagraphs=cudagraphs,
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


# --------------------------------------------------- strict-config construction


def _installed_environment_config(puffer_root: Path) -> dict[str, float]:
    """Load the installed full `[env]` dictionary as inert numeric built-ins."""

    config_path = Path(puffer_root).resolve() / "config/bloodbowl.ini"
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    try:
        with config_path.open(encoding="utf-8") as handle:
            parser.read_file(handle)
    except (OSError, configparser.Error, UnicodeError) as exc:
        raise QualificationError(
            f"cannot read installed Blood Bowl config: {exc}"
        ) from exc
    if "env" not in parser:
        raise QualificationError("installed Blood Bowl config has no [env] section")
    raw = dict(parser["env"])
    if len(raw) != ENVIRONMENT_CONFIG_KEY_COUNT:
        raise QualificationError(
            "installed Blood Bowl config has "
            f"{len(raw)} environment keys; expected {ENVIRONMENT_CONFIG_KEY_COUNT}"
        )
    result: dict[str, float] = {}
    for key, value in raw.items():
        try:
            parsed = float(value)
        except ValueError as exc:
            raise QualificationError(
                f"installed Blood Bowl config value is not numeric: {key}"
            ) from exc
        if not math.isfinite(parsed):
            raise QualificationError(
                f"installed Blood Bowl config value is not finite: {key}"
            )
        result[key] = parsed
    return result


def _installed_team_count(puffer_root: Path) -> int:
    """Derive the current generated `BB_TEAM_COUNT` enum value."""

    header = Path(puffer_root).resolve() / "ocean/bloodbowl/bb/gen_teams.h"
    try:
        source = header.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise QualificationError(
            f"cannot read installed generated team ledger: {exc}"
        ) from exc
    match = re.search(
        r"typedef\s+enum\s*\{(?P<body>.*?)\bBB_TEAM_COUNT\b",
        source,
        re.DOTALL,
    )
    if match is None:
        raise QualificationError(
            "installed generated team ledger has no BB_TEAM_COUNT enum"
        )
    count = len(re.findall(r"\bBB_TEAM_[A-Z0-9_]+\b", match.group("body")))
    if count <= 0 or count > 1000:
        raise QualificationError(
            f"installed generated team count is implausible: {count}"
        )
    return count


def _close_vec(vec: Any) -> None:
    close = getattr(vec, "close", None)
    if not callable(close):
        raise QualificationError("create_vec result has no close method")
    close()


def _exercise_positive_strict_constructors(
    _C: Any,
    config: dict[str, Any],
) -> dict[str, Any]:
    """Construct, reset/step, and close both CUDA entry points."""

    vec = None
    vec_record = {
        "constructed": False,
        "reset": False,
        "closed": False,
    }
    try:
        vec = _C.create_vec(config, gpu=1)
        vec_record["constructed"] = True
        vec.reset()
        vec_record["reset"] = True
    finally:
        if vec is not None:
            _close_vec(vec)
            vec_record["closed"] = True

    pufferl = None
    pufferl_record = {
        "constructed": False,
        "rollout": False,
        "closed": False,
    }
    try:
        pufferl = _C.create_pufferl(config)
        pufferl_record["constructed"] = True
        _C.rollouts(pufferl)
        pufferl_record["rollout"] = True
    finally:
        if pufferl is not None:
            _C.close(pufferl)
            pufferl_record["closed"] = True

    return {
        "create_vec": vec_record,
        "create_pufferl": pufferl_record,
    }


def _exercise_expected_strict_rejection(
    _C: Any,
    config: dict[str, Any],
    *,
    constructor: str,
    invalid_team: int,
) -> dict[str, Any]:
    """Require the production module's exact pre-allocation ValueError."""

    constructed = None
    try:
        if constructor == "create_vec":
            constructed = _C.create_vec(config, gpu=1)
        elif constructor == "create_pufferl":
            constructed = _C.create_pufferl(config)
        else:  # pragma: no cover - caller owns the closed constructor set
            raise AssertionError(constructor)
    except ValueError as exc:
        message = str(exc)
        if STRICT_INVALID_TEAM_DIAGNOSTIC not in message:
            raise QualificationError(
                f"{constructor} rejected strict config with the wrong "
                f"diagnostic: {message}"
            ) from exc
        return {
            "constructor": constructor,
            "exception_type": "ValueError",
            "field": "force_home_team",
            "domain": "integer -1 or 0..BB_TEAM_COUNT-1",
            "value": invalid_team,
            "message": message,
            "expected_rejection": True,
        }
    except Exception as exc:
        raise QualificationError(
            f"{constructor} reached an unrelated failure before strict "
            f"environment rejection: {type(exc).__name__}: {exc}"
        ) from exc
    finally:
        if constructed is not None:
            if constructor == "create_vec":
                _close_vec(constructed)
            else:
                _C.close(constructed)
    raise QualificationError(f"{constructor} accepted force_home_team=BB_TEAM_COUNT")


def validate_strict_rejection_record(
    record: Mapping[str, Any],
    *,
    constructor: str,
) -> dict[str, Any]:
    rejection = record.get("strict_config_rejection")
    if not isinstance(rejection, Mapping):
        raise QualificationError(
            f"{constructor} strict-config rejection record is missing"
        )
    expected = {
        "constructor": constructor,
        "exception_type": "ValueError",
        "field": "force_home_team",
        "domain": "integer -1 or 0..BB_TEAM_COUNT-1",
        "expected_rejection": True,
    }
    for key, value in expected.items():
        if rejection.get(key) != value:
            raise QualificationError(
                f"{constructor} strict-config rejection {key} differs"
            )
    if not isinstance(rejection.get("value"), int) or isinstance(
        rejection.get("value"), bool
    ):
        raise QualificationError(
            f"{constructor} strict-config rejection value is not an integer"
        )
    message = rejection.get("message")
    if not isinstance(message, str) or STRICT_INVALID_TEAM_DIAGNOSTIC not in message:
        raise QualificationError(
            f"{constructor} strict-config rejection diagnostic differs"
        )
    return dict(rejection)


def validate_positive_strict_record(
    record: Mapping[str, Any],
    *,
    profile: str,
) -> dict[str, Any]:
    if record.get("strict_config_profile") != profile:
        raise QualificationError(
            f"strict-config positive cell profile differs: {profile}"
        )
    constructors = record.get("strict_config_constructors")
    if not isinstance(constructors, Mapping):
        raise QualificationError(
            f"strict-config positive cell constructors are missing: {profile}"
        )
    expected = {
        "create_vec": {
            "constructed": True,
            "reset": True,
            "closed": True,
        },
        "create_pufferl": {
            "constructed": True,
            "rollout": True,
            "closed": True,
        },
    }
    if constructors != expected:
        raise QualificationError(
            f"strict-config positive cell did not complete both constructors: "
            f"{profile}"
        )
    return dict(constructors)


# ------------------------------------------------------- compiled-module identity


def qualification_surface_state(module: Any) -> bool:
    """Accept only a completely absent or completely present evidence surface."""
    present = tuple(hasattr(module, name) for name in QUALIFICATION_SURFACE_BINDINGS)
    if any(present) and not all(present):
        raise QualificationError("compiled qualification surface is partial")
    return all(present)


def backend_source_hash(
    puffer_root: Path, *, source_files: Iterable[str] = BACKEND_SOURCE_FILES
) -> str:
    """Reproduce install_puffer_env.sh's path-bound backend source digest."""
    try:
        return source_manifest_sha256(puffer_root, source_files)
    except ValueError as exc:
        raise QualificationError(f"backend source manifest failed: {exc}") from exc


def installed_snapshot_hash(puffer_root: Path) -> str:
    path = Path(puffer_root).resolve() / "ocean" / "bloodbowl" / ".content_hash"
    try:
        value = path.read_text(encoding="ascii").strip()
    except (OSError, UnicodeError) as exc:
        raise QualificationError(
            f"installed snapshot digest is unavailable: {exc}"
        ) from exc
    return _require_sha256(value, "installed snapshot digest")


def _load_backend(puffer_root: Path):
    """Initialize CUDART before importing _C (D225), then probe the module.

    Importing the nvcc-built `_C` before the first CUDART call leaves a fresh
    WSL process at cudaErrorNoDevice, so the runtime probe has to happen in this
    process, before this import, and be rechecked afterwards.
    """
    root = Path(puffer_root).resolve()
    try:
        cuda_runtime, evidence = begin_cuda_runtime_preflight()
    except CudaRuntimePreflightError as exc:
        raise QualificationError(f"CUDA runtime pre-import gate failed: {exc}") from exc
    sys.path.insert(0, str(root))
    from pufferlib import _C  # type: ignore

    try:
        evidence = finish_cuda_runtime_preflight(cuda_runtime, evidence)
        validate_cuda_runtime_evidence(evidence)
    except CudaRuntimePreflightError as exc:
        raise QualificationError(
            f"CUDA runtime post-import gate failed: {exc}"
        ) from exc
    module = Path(_C.__file__).resolve()
    try:
        module.relative_to(root)
    except ValueError as exc:
        raise QualificationError(
            f"imported native module is outside Puffer root: {module}"
        ) from exc
    missing = [
        name
        for name in (
            "create_vec",
            "create_pufferl",
            "rollouts",
            "log",
            "get_utilization",
            "save_weights",
            "load_frozen_bank",
            "set_evaluation_mode",
            "train",
            "environment_config_schema",
            "strict_env_config_testing",
            *QUALIFICATION_SURFACE_BINDINGS,
        )
        if not hasattr(_C, name)
    ]
    if missing:
        raise QualificationError(
            f"compiled qualification surface is missing: {missing}"
        )
    return _C, module, evidence


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
        "environment_config_schema": str(_C.environment_config_schema),
        "strict_env_config_testing": _C.strict_env_config_testing,
        "precision_bytes": int(_C.precision_bytes),
        "compiled_env": str(_C.env_name),
        "qualification_surface": qualification_surface_state(_C),
    }


def validate_module_identity(
    identity: Mapping[str, Any],
    *,
    qualification_surface: bool = True,
    strict_env_config_testing: bool = False,
) -> dict[str, Any]:
    """The imported module really is obs-v6 / exact-joint-v1 / fp32.

    obs-v4, obs-v5 and obs-v6 are all 2782 bytes, so only this provenance
    separates them; a mixup already wasted a 12B-step run. The two digest equalities are
    compiled == on-disk source and compiled == installed snapshot: the build
    compiles the snapshot, not your edit.
    """
    if identity.get("compiled_env") != "bloodbowl":
        raise QualificationError("compiled environment is not bloodbowl")
    if (
        identity.get("observation_abi") != "obs-v6"
        or identity.get("observation_version") != 6
    ):
        raise QualificationError("compiled observation lineage is not obs-v6")
    if identity.get("action_abi") != "exact-joint-v1":
        raise QualificationError("compiled action lineage is not exact-joint-v1")
    if identity.get("environment_config_schema") != ENVIRONMENT_CONFIG_SCHEMA:
        raise QualificationError(
            "compiled environment-config schema is not " f"{ENVIRONMENT_CONFIG_SCHEMA}"
        )
    if identity.get("strict_env_config_testing") is not strict_env_config_testing:
        role = "test" if strict_env_config_testing else "production"
        raise QualificationError(
            f"compiled strict-config module must have the {role} role"
        )
    if identity.get("precision_bytes") not in GRAPH_ATOL_BY_PRECISION:
        raise QualificationError("compiled precision is unsupported")
    if identity.get("qualification_surface") is not qualification_surface:
        raise QualificationError("compiled qualification-surface role is wrong")
    for key in (
        "module_sha256",
        "compiled_backend_sha256",
        "backend_sources_sha256",
        "environment_sha256",
        "installed_snapshot_sha256",
    ):
        _require_sha256(identity.get(key), f"module identity {key}")
    if identity["compiled_backend_sha256"] != identity["backend_sources_sha256"]:
        raise QualificationError("compiled module differs from backend source digest")
    if identity["environment_sha256"] != identity["installed_snapshot_sha256"]:
        raise QualificationError(
            "compiled module differs from installed environment digest"
        )
    module = Path(str(identity.get("module", ""))).resolve()
    try:
        module.relative_to(Path(str(identity.get("puffer_root", ""))).resolve())
    except ValueError as exc:
        raise QualificationError(
            "compiled module is outside recorded Puffer root"
        ) from exc
    return dict(identity)


# -------------------------------- strict CUDA constructor-stage release gate


def _require_exact_keys(
    value: Mapping[str, Any], expected: Iterable[str], label: str
) -> None:
    observed = set(value)
    required = set(expected)
    if observed != required:
        missing = sorted(required - observed)
        extra = sorted(observed - required)
        raise QualificationError(
            f"{label} keys differ: missing={missing}, extra={extra}"
        )


def _require_bounded_string(
    value: Any,
    label: str,
    *,
    maximum_bytes: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise QualificationError(f"{label} must be a string")
    try:
        encoded = value.encode("utf-8")
    except UnicodeError as exc:
        raise QualificationError(f"{label} is not valid UTF-8") from exc
    if (not allow_empty and not encoded) or len(encoded) > maximum_bytes:
        minimum = 0 if allow_empty else 1
        raise QualificationError(
            f"{label} must contain {minimum}..{maximum_bytes} UTF-8 bytes"
        )
    return value


def _require_bounded_absolute_path(value: Any, label: str) -> Path:
    text = _require_bounded_string(
        value,
        label,
        maximum_bytes=STRICT_STAGE_PATH_MAX_BYTES,
    )
    if "\x00" in text:
        raise QualificationError(f"{label} contains NUL")
    path = Path(text)
    if not path.is_absolute():
        raise QualificationError(f"{label} must be absolute")
    return path


def _require_exact_json_int(
    value: Any,
    label: str,
    *,
    minimum: int | None = None,
) -> int:
    if type(value) is not int:
        raise QualificationError(f"{label} must be an exact JSON integer")
    if minimum is not None and value < minimum:
        raise QualificationError(f"{label} must be at least {minimum}")
    return value


def _strict_stage_snapshot(_C: Any, *, reset: bool) -> dict[str, int]:
    surface = getattr(_C, "strict_env_config_test_stages", None)
    if not callable(surface):
        raise QualificationError("compiled strict-config test-stage surface is missing")
    raw = surface(reset)
    if not isinstance(raw, Mapping):
        raise QualificationError("strict-config test-stage snapshot is not a mapping")
    _require_exact_keys(raw, STRICT_STAGE_KEYS, "strict-config test-stage snapshot")
    result: dict[str, int] = {}
    for key in STRICT_STAGE_KEYS:
        value = raw[key]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise QualificationError(
                f"strict-config test-stage {key} must be a nonnegative integer"
            )
        result[key] = value
    return result


def _require_strict_stage_counts(
    observed: Mapping[str, Any],
    expected: Mapping[str, int],
    *,
    label: str,
) -> dict[str, int]:
    _require_exact_keys(observed, STRICT_STAGE_KEYS, f"{label} stages")
    normalized = {
        key: _require_exact_json_int(
            observed.get(key), f"{label} stage {key}", minimum=0
        )
        for key in STRICT_STAGE_KEYS
    }
    if normalized != dict(expected):
        raise QualificationError(
            f"{label} stages differ: observed={normalized}, "
            f"expected={dict(expected)}"
        )
    return normalized


def _strict_stage_safe_config(seed: int) -> dict[str, Any]:
    return qualification_args(
        cudagraphs=DEFAULT_CUDAGRAPH_WARMUP_EPOCHS,
        seed=seed,
        total_agents=2,
        num_buffers=1,
        num_threads=1,
        horizon=1,
        max_decisions=16,
        hidden_size=64,
        num_layers=1,
        frozen_banks=0,
        frozen_bank_pct=0.0,
        learning_rate=0.0,
    )


def _strict_stage_hazard_config(
    base: Mapping[str, Any],
    *,
    hazard: str,
    invalid_team: int,
) -> tuple[dict[str, Any], str]:
    config = copy.deepcopy(base)
    config["env"] = {
        "seed": config["seed"],
        "max_decisions": 16,
        "force_home_team": invalid_team,
    }
    if hazard == "vec":
        config["vec"]["total_agents"] = "dangerous-not-an-integer"
    elif hazard == "train":
        config["train"] = "dangerous-not-a-dictionary"
    elif hazard == "policy":
        config["policy"] = "dangerous-not-a-dictionary"
    elif hazard == "device":
        config["gpu_id"] = "dangerous-not-an-integer"
    else:  # pragma: no cover - the closed matrix is owned by the caller
        raise AssertionError(hazard)
    return config, STRICT_STAGE_HAZARD_PATHS[hazard]


def _invoke_strict_stage_constructor(
    _C: Any, constructor: str, config: dict[str, Any]
) -> Any:
    if constructor == "create_vec":
        return _C.create_vec(config, gpu=1)
    if constructor == "create_pufferl":
        return _C.create_pufferl(config)
    raise AssertionError(constructor)  # pragma: no cover - closed caller set


def _close_strict_stage_constructor(
    _C: Any, constructor: str, constructed: Any
) -> None:
    if constructor == "create_vec":
        _close_vec(constructed)
    else:
        _C.close(constructed)


def _exercise_strict_stage_rejection(
    _C: Any,
    config: dict[str, Any],
    *,
    constructor: str,
    hazard: str,
    malformed_path: str,
    invalid_team: int,
) -> dict[str, Any]:
    baseline = _strict_stage_snapshot(_C, reset=True)
    _require_strict_stage_counts(
        baseline, STRICT_STAGE_ZERO, label=f"{constructor}/{hazard} baseline"
    )
    constructed = None
    caught: Exception | None = None
    try:
        constructed = _invoke_strict_stage_constructor(_C, constructor, config)
    except Exception as exc:
        caught = exc
    try:
        stages = _strict_stage_snapshot(_C, reset=True)
    finally:
        if constructed is not None:
            _close_strict_stage_constructor(_C, constructor, constructed)
    _require_strict_stage_counts(
        stages,
        STRICT_STAGE_REJECTED,
        label=f"{constructor}/{hazard} rejection",
    )
    if constructed is not None:
        raise QualificationError(
            f"{constructor}/{hazard} accepted force_home_team=BB_TEAM_COUNT"
        )
    if not isinstance(caught, ValueError):
        if caught is None:
            detail = "no exception"
        else:
            detail = f"{type(caught).__name__}: {_bounded_text(caught)}"
        raise QualificationError(
            f"{constructor}/{hazard} reached an unrelated failure: {detail}"
        )
    message = _bounded_text(caught)
    if STRICT_INVALID_TEAM_DIAGNOSTIC not in message:
        raise QualificationError(
            f"{constructor}/{hazard} rejected with the wrong diagnostic: {message}"
        )
    return {
        "constructor": constructor,
        "hazard": hazard,
        "malformed_path": malformed_path,
        "invalid_team": invalid_team,
        "exception_type": "ValueError",
        "message": message,
        "expected_rejection": True,
        "constructed": False,
        "stages": stages,
    }


def _exercise_strict_stage_positive(
    _C: Any,
    config: dict[str, Any],
    *,
    constructor: str,
) -> dict[str, Any]:
    baseline = _strict_stage_snapshot(_C, reset=True)
    _require_strict_stage_counts(
        baseline, STRICT_STAGE_ZERO, label=f"{constructor} positive baseline"
    )
    constructed = None
    closed = False
    try:
        constructed = _invoke_strict_stage_constructor(_C, constructor, config)
        stages = _strict_stage_snapshot(_C, reset=True)
        _require_strict_stage_counts(
            stages,
            STRICT_STAGE_POSITIVE[constructor],
            label=f"{constructor} positive",
        )
    except Exception:
        # Leave the test-only counter surface clean even when construction or
        # validation fails, then preserve the original exception.
        _strict_stage_snapshot(_C, reset=True)
        raise
    finally:
        if constructed is not None:
            _close_strict_stage_constructor(_C, constructor, constructed)
            closed = True
    return {
        "constructor": constructor,
        "constructed": True,
        "closed": closed,
        "stages": stages,
    }


def _exercise_strict_cuda_stage_order(
    _C: Any,
    *,
    seed: int,
    invalid_team: int,
) -> dict[str, Any]:
    """Prove invalid env rejection precedes every named CUDA allocation stage."""

    if invalid_team <= 0:
        raise QualificationError("installed BB_TEAM_COUNT must be positive")
    base = _strict_stage_safe_config(seed)
    invalid_cases: list[dict[str, Any]] = []
    for constructor in ("create_vec", "create_pufferl"):
        for hazard in STRICT_STAGE_HAZARDS:
            config, malformed_path = _strict_stage_hazard_config(
                base,
                hazard=hazard,
                invalid_team=invalid_team,
            )
            invalid_cases.append(
                _exercise_strict_stage_rejection(
                    _C,
                    config,
                    constructor=constructor,
                    hazard=hazard,
                    malformed_path=malformed_path,
                    invalid_team=invalid_team,
                )
            )
    positive_controls = {
        constructor: _exercise_strict_stage_positive(
            _C,
            copy.deepcopy(base),
            constructor=constructor,
        )
        for constructor in ("create_vec", "create_pufferl")
    }
    cleanup = _strict_stage_snapshot(_C, reset=True)
    _require_strict_stage_counts(
        cleanup, STRICT_STAGE_ZERO, label="strict-stage cleanup"
    )
    return {
        "invalid_cases": invalid_cases,
        "positive_controls": positive_controls,
        "cleanup_stages": cleanup,
    }


def _strict_stage_module_identity(
    _C: Any, module: Path, puffer_root: Path
) -> dict[str, Any]:
    identity = _module_identity(_C, module, puffer_root)
    identity["gpu"] = getattr(_C, "gpu", None)
    identity["strict_stage_surface"] = callable(
        getattr(_C, "strict_env_config_test_stages", None)
    )
    return identity


def validate_strict_stage_module_identity(
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    _require_exact_keys(
        identity,
        STRICT_STAGE_MODULE_IDENTITY_KEYS,
        "strict-stage module identity",
    )
    for key in (
        "module",
        "puffer_root",
        "observation_abi",
        "action_abi",
        "environment_config_schema",
        "compiled_env",
    ):
        maximum = (
            STRICT_STAGE_PATH_MAX_BYTES
            if key in {"module", "puffer_root"}
            else STRICT_STAGE_MESSAGE_MAX_BYTES
        )
        _require_bounded_string(
            identity.get(key),
            f"strict-stage module identity {key}",
            maximum_bytes=maximum,
        )
    _require_bounded_absolute_path(
        identity.get("module"), "strict-stage module identity module"
    )
    _require_bounded_absolute_path(
        identity.get("puffer_root"), "strict-stage module identity Puffer root"
    )
    if (
        _require_exact_json_int(
            identity.get("observation_version"),
            "strict-stage observation version",
        )
        != 6
    ):
        raise QualificationError("strict-stage observation version differs")
    if (
        _require_exact_json_int(
            identity.get("precision_bytes"),
            "strict-stage precision bytes",
            minimum=1,
        )
        not in GRAPH_ATOL_BY_PRECISION
    ):
        raise QualificationError("strict-stage precision is unsupported")
    if _require_exact_json_int(identity.get("gpu"), "strict-stage gpu", minimum=0) != 1:
        raise QualificationError("strict-stage module is not the CUDA backend")
    for key in (
        "strict_env_config_testing",
        "qualification_surface",
        "strict_stage_surface",
    ):
        if identity.get(key) is not True:
            raise QualificationError(f"strict-stage module identity {key} is not true")
    validated = validate_module_identity(
        identity,
        strict_env_config_testing=True,
    )
    return validated


def _validate_strict_stage_interpreter_identity(
    identity: Mapping[str, Any],
    *,
    puffer_root: Path,
    expected_interpreter: Path | None = None,
    rehash_executable: bool = False,
) -> dict[str, Any]:
    _require_exact_keys(
        identity,
        STRICT_STAGE_INTERPRETER_IDENTITY_KEYS,
        "strict-stage interpreter identity",
    )
    root = Path(puffer_root).resolve()
    venv = root / ".venv"
    executable = _require_bounded_absolute_path(
        identity.get("executable"), "strict-stage interpreter executable"
    )
    prefix = _require_bounded_absolute_path(
        identity.get("prefix"), "strict-stage interpreter prefix"
    )
    base_prefix = _require_bounded_absolute_path(
        identity.get("base_prefix"), "strict-stage interpreter base prefix"
    )
    pybind11_path = _require_bounded_absolute_path(
        identity.get("pybind11_path"), "strict-stage pybind11 path"
    )
    numpy_path = _require_bounded_absolute_path(
        identity.get("numpy_path"), "strict-stage NumPy path"
    )
    expected = (
        Path(expected_interpreter).absolute()
        if expected_interpreter is not None
        else venv / "bin/python"
    )
    if executable != expected or prefix != venv:
        raise QualificationError(
            "strict-stage interpreter is not the selected checkout-local venv"
        )
    for label, dependency_path in (
        ("pybind11", pybind11_path),
        ("NumPy", numpy_path),
    ):
        try:
            dependency_path.resolve().relative_to(venv.resolve())
        except ValueError as exc:
            raise QualificationError(
                f"strict-stage {label} is outside the checkout-local venv"
            ) from exc
    if base_prefix.resolve() == prefix.resolve():
        raise QualificationError("strict-stage interpreter is not a virtualenv")
    suffix = _require_bounded_string(
        identity.get("ext_suffix"),
        "strict-stage interpreter extension suffix",
        maximum_bytes=255,
    )
    if (
        not suffix.startswith(".")
        or "/" in suffix
        or "\\" in suffix
        or re.fullmatch(r"[A-Za-z0-9._-]+", suffix) is None
    ):
        raise QualificationError(
            "strict-stage interpreter extension suffix is malformed"
        )
    version = _require_bounded_string(
        identity.get("python_version"),
        "strict-stage Python version",
        maximum_bytes=64,
    )
    if re.fullmatch(r"[0-9]+(?:\.[0-9]+){1,3}", version) is None:
        raise QualificationError("strict-stage Python version is malformed")
    executable_sha = _require_sha256(
        identity.get("executable_sha256"),
        "strict-stage interpreter executable SHA-256",
    )
    if rehash_executable:
        if venv.is_symlink() or not venv.is_dir():
            raise QualificationError(
                "strict-stage checkout-local .venv is not a real directory"
            )
        if (
            not executable.is_file()
            or not pybind11_path.is_file()
            or not numpy_path.is_file()
            or sha256(executable) != executable_sha
        ):
            raise QualificationError(
                "strict-stage interpreter or dependency bytes drifted"
            )
    return dict(identity)


def _validate_strict_stage_receipt(
    receipt: Mapping[str, Any],
    *,
    expected_puffer_root: Path | None = None,
    rehash_executable: bool = False,
) -> dict[str, Any]:
    expected_keys = (
        "schema_version",
        "evidence_kind",
        "puffer_root",
        "git_head",
        "initial_status",
        "initial_status_sha256",
        "separate_from_repo_vendor_checkout",
        "confirmed_isolated_test_checkout",
        "build_absent",
        "environment_absent",
        "module_absent",
        "detached_head",
        "interpreter",
        "interpreter_identity",
        "origin",
    )
    _require_exact_keys(receipt, expected_keys, "strict-stage isolation receipt")
    if (
        _require_exact_json_int(
            receipt.get("schema_version"),
            "strict-stage isolation receipt schema",
        )
        != STRICT_STAGE_SCHEMA_VERSION
    ):
        raise QualificationError("strict-stage isolation receipt schema differs")
    if receipt.get("evidence_kind") != STRICT_STAGE_RECEIPT_KIND:
        raise QualificationError("strict-stage isolation receipt kind differs")
    if receipt.get("git_head") != PINNED_PUFFER_COMMIT:
        raise QualificationError("strict-stage isolation checkout is not exact-pinned")
    if receipt.get("initial_status") != "":
        raise QualificationError("strict-stage isolation checkout was not pristine")
    if receipt.get("initial_status_sha256") != hashlib.sha256(b"").hexdigest():
        raise QualificationError("strict-stage isolation status digest differs")
    for key in (
        "separate_from_repo_vendor_checkout",
        "confirmed_isolated_test_checkout",
        "build_absent",
        "environment_absent",
        "module_absent",
        "detached_head",
    ):
        if receipt.get(key) is not True:
            raise QualificationError(f"strict-stage isolation receipt {key} is false")
    root = _require_bounded_absolute_path(
        receipt.get("puffer_root"), "strict-stage isolation Puffer root"
    ).resolve()
    if (
        expected_puffer_root is not None
        and root != Path(expected_puffer_root).resolve()
    ):
        raise QualificationError("strict-stage isolation receipt root differs")
    if root == (REPO_ROOT / "vendor/PufferLib").resolve():
        raise QualificationError("strict-stage checkout is the production vendor tree")
    interpreter = _require_bounded_absolute_path(
        receipt.get("interpreter"), "strict-stage isolation interpreter"
    )
    try:
        interpreter.relative_to(root)
    except ValueError as exc:
        raise QualificationError(
            "strict-stage isolation interpreter is outside the checkout"
        ) from exc
    if interpreter != root / ".venv/bin/python":
        raise QualificationError(
            "strict-stage isolation interpreter is not .venv/bin/python"
        )
    interpreter_identity = receipt.get("interpreter_identity")
    if not isinstance(interpreter_identity, Mapping):
        raise QualificationError(
            "strict-stage isolation interpreter identity is missing"
        )
    _validate_strict_stage_interpreter_identity(
        interpreter_identity,
        puffer_root=root,
        expected_interpreter=interpreter,
        rehash_executable=rehash_executable,
    )
    _require_bounded_string(
        receipt.get("origin"),
        "strict-stage isolation origin",
        maximum_bytes=2048,
        allow_empty=True,
    )
    return dict(receipt)


def _validate_strict_stage_cuda_runtime_claim(evidence: Any) -> dict[str, Any]:
    if not isinstance(evidence, Mapping):
        raise QualificationError("strict-stage CUDA runtime evidence is missing")
    if (
        _require_exact_json_int(
            evidence.get("schema_version"),
            "strict-stage CUDA runtime schema",
        )
        != 1
    ):
        raise QualificationError("strict-stage CUDA runtime schema differs")
    library = evidence.get("library")
    if not isinstance(library, Mapping):
        raise QualificationError("strict-stage CUDA runtime library is missing")
    for key in ("requested_soname", "resolved_path"):
        _require_bounded_string(
            library.get(key),
            f"strict-stage CUDA runtime library {key}",
            maximum_bytes=STRICT_STAGE_PATH_MAX_BYTES,
        )
    _require_bounded_string(
        evidence.get("cuda_visible_devices"),
        "strict-stage CUDA_VISIBLE_DEVICES",
        maximum_bytes=STRICT_STAGE_MESSAGE_MAX_BYTES,
    )
    for stage in ("before_extension_import", "after_extension_import"):
        probe = evidence.get(stage)
        if not isinstance(probe, Mapping):
            raise QualificationError(
                f"strict-stage CUDA runtime {stage} evidence is missing"
            )
        for key in ("stage", "error_name", "error_string"):
            _require_bounded_string(
                probe.get(key),
                f"strict-stage CUDA runtime {stage} {key}",
                maximum_bytes=STRICT_STAGE_MESSAGE_MAX_BYTES,
            )
    try:
        return validate_cuda_runtime_evidence(evidence)
    except CudaRuntimePreflightError as exc:
        raise QualificationError(
            f"strict-stage CUDA runtime evidence failed: {exc}"
        ) from exc


def validate_strict_stage_evidence(
    payload: Mapping[str, Any],
    *,
    expected_puffer_root: Path | None = None,
    expected_receipt_path: Path | None = None,
    rehash_files: bool = False,
) -> dict[str, Any]:
    """Fail closed over the bounded external-NVIDIA stage-order artifact."""

    expected_keys = (
        "schema_version",
        "evidence_kind",
        "qualification_only",
        "mandatory_external_gpu_gate",
        "accepted",
        "identity",
        "cuda_runtime_preflight",
        "isolation",
        "patch_identity",
        "invalid_cases",
        "positive_controls",
        "cleanup_stages",
        "production_identity_rejection",
        "host",
        "platform",
        "seed",
    )
    _require_exact_keys(payload, expected_keys, "strict-stage evidence")
    if (
        _require_exact_json_int(
            payload.get("schema_version"), "strict-stage evidence schema"
        )
        != STRICT_STAGE_SCHEMA_VERSION
    ):
        raise QualificationError("strict-stage evidence schema differs")
    if payload.get("evidence_kind") != STRICT_STAGE_EVIDENCE_KIND:
        raise QualificationError("strict-stage evidence kind differs")
    for key in ("qualification_only", "mandatory_external_gpu_gate", "accepted"):
        if payload.get(key) is not True:
            raise QualificationError(f"strict-stage evidence {key} is not true")
    identity = payload.get("identity")
    if not isinstance(identity, Mapping):
        raise QualificationError("strict-stage module identity is missing")
    validate_strict_stage_module_identity(identity)
    root = _require_bounded_absolute_path(
        identity.get("puffer_root"), "strict-stage evidence Puffer root"
    ).resolve()
    if (
        expected_puffer_root is not None
        and root != Path(expected_puffer_root).resolve()
    ):
        raise QualificationError("strict-stage evidence Puffer root differs")
    _validate_strict_stage_cuda_runtime_claim(payload.get("cuda_runtime_preflight"))

    isolation = payload.get("isolation")
    if not isinstance(isolation, Mapping):
        raise QualificationError("strict-stage isolation evidence is missing")
    _require_exact_keys(
        isolation, ("receipt", "receipt_sha256"), "strict-stage isolation evidence"
    )
    receipt = isolation.get("receipt")
    if not isinstance(receipt, Mapping):
        raise QualificationError("strict-stage isolation receipt is missing")
    _validate_strict_stage_receipt(
        receipt,
        expected_puffer_root=root,
        rehash_executable=rehash_files,
    )
    receipt_sha = _require_sha256(
        isolation.get("receipt_sha256"), "strict-stage isolation receipt SHA-256"
    )
    if expected_receipt_path is not None:
        receipt_path = Path(os.path.abspath(Path(expected_receipt_path)))
        retained_receipt = _read_json(
            receipt_path,
            maximum_bytes=STRICT_STAGE_MAX_JSON_BYTES,
            require_regular=True,
        )
        if retained_receipt != dict(receipt):
            raise QualificationError(
                "strict-stage retained isolation receipt content differs"
            )
        if sha256(receipt_path) != receipt_sha:
            raise QualificationError("strict-stage isolation receipt bytes drifted")
    suffix = receipt["interpreter_identity"]["ext_suffix"]
    if not Path(identity["module"]).name.endswith(suffix):
        raise QualificationError(
            "strict-stage module suffix differs from the isolated interpreter"
        )

    patch_identity = payload.get("patch_identity")
    if not isinstance(patch_identity, Mapping):
        raise QualificationError("strict-stage patch identity is missing")
    _require_exact_keys(
        patch_identity,
        (
            "puffer_git_head",
            "strict_environment_config_patch",
            "qualifier",
            "compiled_backend_source_ledger",
        ),
        "strict-stage patch identity",
    )
    if patch_identity.get("puffer_git_head") != PINNED_PUFFER_COMMIT:
        raise QualificationError("strict-stage patch identity has the wrong Puffer pin")
    for key in (
        "strict_environment_config_patch",
        "qualifier",
        "compiled_backend_source_ledger",
    ):
        record = patch_identity.get(key)
        if not isinstance(record, Mapping):
            raise QualificationError(f"strict-stage patch identity {key} is missing")
        required = (
            ("path", "sha256", "reverse_applicable")
            if key == ("strict_environment_config_patch")
            else ("path", "sha256")
        )
        _require_exact_keys(record, required, f"strict-stage patch identity {key}")
        _require_sha256(record.get("sha256"), f"strict-stage {key} SHA-256")
        _require_bounded_absolute_path(record.get("path"), f"strict-stage {key} path")
        if (
            key == "strict_environment_config_patch"
            and record.get("reverse_applicable") is not True
        ):
            raise QualificationError("strict environment patch is not installed")

    invalid_cases = payload.get("invalid_cases")
    if not isinstance(invalid_cases, list):
        raise QualificationError("strict-stage invalid-case evidence is missing")
    expected_pairs = {
        (constructor, hazard)
        for constructor in ("create_vec", "create_pufferl")
        for hazard in STRICT_STAGE_HAZARDS
    }
    observed_pairs: set[tuple[Any, Any]] = set()
    invalid_teams: set[int] = set()
    for record in invalid_cases:
        if not isinstance(record, Mapping):
            raise QualificationError("strict-stage invalid-case record is malformed")
        _require_exact_keys(
            record,
            (
                "constructor",
                "hazard",
                "malformed_path",
                "invalid_team",
                "exception_type",
                "message",
                "expected_rejection",
                "constructed",
                "stages",
            ),
            "strict-stage invalid-case record",
        )
        pair = (record.get("constructor"), record.get("hazard"))
        if pair in observed_pairs:
            raise QualificationError(f"duplicate strict-stage invalid case: {pair}")
        observed_pairs.add(pair)
        constructor, hazard = pair
        expected_path = STRICT_STAGE_HAZARD_PATHS.get(hazard)
        if (
            constructor not in {"create_vec", "create_pufferl"}
            or expected_path is None
            or record.get("malformed_path") != expected_path
        ):
            raise QualificationError(f"strict-stage malformed path differs for {pair}")
        invalid_team = _require_exact_json_int(
            record.get("invalid_team"), "strict-stage invalid team", minimum=1
        )
        invalid_teams.add(invalid_team)
        if (
            record.get("exception_type") != "ValueError"
            or record.get("expected_rejection") is not True
            or record.get("constructed") is not False
        ):
            raise QualificationError("strict-stage invalid rejection verdict differs")
        message = record.get("message")
        if isinstance(message, str):
            _require_bounded_string(
                message,
                "strict-stage invalid diagnostic",
                maximum_bytes=STRICT_STAGE_MESSAGE_MAX_BYTES,
            )
        if (
            not isinstance(message, str)
            or STRICT_INVALID_TEAM_DIAGNOSTIC not in message
        ):
            raise QualificationError("strict-stage invalid diagnostic differs")
        stages = record.get("stages")
        if not isinstance(stages, Mapping):
            raise QualificationError("strict-stage invalid counters are missing")
        _require_strict_stage_counts(
            stages,
            STRICT_STAGE_REJECTED,
            label=f"{pair[0]}/{pair[1]} evidence",
        )
    if observed_pairs != expected_pairs or len(invalid_teams) != 1:
        raise QualificationError("strict-stage invalid-case matrix is incomplete")
    if rehash_files:
        installed_team_count = _installed_team_count(root)
        if invalid_teams != {installed_team_count}:
            raise QualificationError(
                "strict-stage invalid team differs from installed BB_TEAM_COUNT"
            )

    controls = payload.get("positive_controls")
    if not isinstance(controls, Mapping):
        raise QualificationError("strict-stage positive controls are missing")
    _require_exact_keys(
        controls, ("create_vec", "create_pufferl"), "strict-stage positive controls"
    )
    for constructor in ("create_vec", "create_pufferl"):
        record = controls.get(constructor)
        if not isinstance(record, Mapping):
            raise QualificationError(
                f"strict-stage {constructor} positive control is malformed"
            )
        _require_exact_keys(
            record,
            ("constructor", "constructed", "closed", "stages"),
            f"strict-stage {constructor} positive control",
        )
        if (
            record.get("constructor") != constructor
            or record.get("constructed") is not True
            or record.get("closed") is not True
        ):
            raise QualificationError(
                f"strict-stage {constructor} positive control did not close"
            )
        stages = record.get("stages")
        if not isinstance(stages, Mapping):
            raise QualificationError(
                f"strict-stage {constructor} positive counters are missing"
            )
        _require_strict_stage_counts(
            stages,
            STRICT_STAGE_POSITIVE[constructor],
            label=f"{constructor} positive evidence",
        )
    cleanup = payload.get("cleanup_stages")
    if not isinstance(cleanup, Mapping):
        raise QualificationError("strict-stage cleanup counters are missing")
    _require_strict_stage_counts(
        cleanup, STRICT_STAGE_ZERO, label="strict-stage cleanup evidence"
    )

    rejection = payload.get("production_identity_rejection")
    if not isinstance(rejection, Mapping):
        raise QualificationError("production identity rejection proof is missing")
    _require_exact_keys(
        rejection,
        ("rejected", "exception_type", "message"),
        "production identity rejection proof",
    )
    rejection_message = rejection.get("message")
    if isinstance(rejection_message, str):
        _require_bounded_string(
            rejection_message,
            "production identity rejection message",
            maximum_bytes=STRICT_STAGE_MESSAGE_MAX_BYTES,
        )
    if (
        rejection.get("rejected") is not True
        or rejection.get("exception_type") != "QualificationError"
        or not isinstance(rejection_message, str)
        or "production role" not in rejection_message
    ):
        raise QualificationError("production identity did not reject the test role")
    _require_exact_json_int(payload.get("seed"), "strict-stage seed")
    _require_bounded_string(
        payload.get("host"),
        "strict-stage evidence host",
        maximum_bytes=STRICT_STAGE_HOST_MAX_BYTES,
    )
    _require_bounded_string(
        payload.get("platform"),
        "strict-stage evidence platform",
        maximum_bytes=STRICT_STAGE_PLATFORM_MAX_BYTES,
    )

    if rehash_files:
        module_path = Path(str(identity["module"])).resolve()
        if sha256(module_path) != identity["module_sha256"]:
            raise QualificationError("strict-stage module bytes drifted")
        if backend_source_hash(root) != identity["backend_sources_sha256"]:
            raise QualificationError("strict-stage backend sources drifted")
        if installed_snapshot_hash(root) != identity["installed_snapshot_sha256"]:
            raise QualificationError("strict-stage installed snapshot drifted")
        expected_files = {
            "strict_environment_config_patch": STRICT_ENV_CONFIG_PATCH,
            "qualifier": Path(__file__).resolve(),
            "compiled_backend_source_ledger": COMPILED_BACKEND_SOURCE_LEDGER,
        }
        for key, path in expected_files.items():
            record = patch_identity[key]
            if Path(str(record["path"])).resolve() != path.resolve():
                raise QualificationError(f"strict-stage {key} path drifted")
            if sha256(path) != record["sha256"]:
                raise QualificationError(f"strict-stage {key} bytes drifted")
    return dict(payload)


# ------------------------------------------ cell worker: one process per measurement


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


def _measure_ratio(
    _C,
    pufferl,
    result: dict[str, Any],
    arrays: dict[str, np.ndarray],
    directory: Path,
    config: Mapping[str, Any],
    call_limit: int,
) -> None:
    layout = _C.qualification_recurrent_state(pufferl, False)
    primary_rows, frozen_rows = derive_row_partition(
        layout, total_agents=int(config["vec"]["total_agents"])
    )
    result["row_partition"] = {
        "primary_rows": sorted(primary_rows),
        "frozen_rows": sorted(frozen_rows),
        "state_layout": layout,
    }
    _C.rollouts(pufferl)
    bind_transition_integrity(_C, pufferl, result)
    before_path = directory / f"ratio-before-{os.getpid()}.bin"
    after_path = directory / f"ratio-after-{os.getpid()}.bin"
    try:
        _C.save_weights(pufferl, str(before_path))
        before = sha256(before_path)
        covered: set[int] = set()
        calls = 0
        while covered != primary_rows and calls < call_limit:
            _C.train(pufferl)
            snapshot = decode_snapshot(_C.qualification_snapshot(pufferl))
            selected = snapshot["selected_rows"].astype(np.int32, copy=False)
            arrays[f"selected_{calls}"] = selected
            arrays[f"ratio_{calls}"] = snapshot["mb_ratio"].astype(
                np.float32, copy=False
            )
            rows = {int(value) for value in selected.reshape(-1).tolist()}
            if rows & frozen_rows:
                raise QualificationError("PPO selected a frozen-bank row")
            if not rows <= primary_rows:
                raise QualificationError("PPO selected a row outside the bank layout")
            covered.update(rows)
            calls += 1
        _C.save_weights(pufferl, str(after_path))
        after = sha256(after_path)
    finally:
        before_path.unlink(missing_ok=True)
        after_path.unlink(missing_ok=True)
    validate_weight_identity(before, after)
    result.update(
        weights_before_sha256=before, weights_after_sha256=after, ratio_calls=calls
    )


def _measure_throughput(
    _C,
    pufferl,
    config: Mapping[str, Any],
    evidence: Mapping[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
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
    steps = int(pufferl.global_step) - start_step
    integrity = validate_hard_integrity(dict(_C.log(pufferl)["env"]))
    gpu = os.environ.get("QUALIFICATION_GPU_NAME", "")
    if not gpu:
        gpu = (
            subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )
            .stdout.strip()
            .splitlines()[0]
        )
    return {
        "host": socket.gethostname(),
        "gpu": gpu,
        "precision_bytes": int(_C.precision_bytes),
        "config": dict(config),
        "steps": steps,
        "elapsed_seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "median_rollout_seconds": statistics.median(durations),
        "p95_rollout_seconds": float(np.percentile(durations, 95)),
        "hard_integrity_zero": True,
        "hard_integrity": integrity,
        "utilization": dict(_C.get_utilization(0)),
    }


def run_cell(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json).resolve()
    output_npz = Path(args.output_npz).resolve() if args.output_npz else None
    _C, module, evidence = _load_backend(Path(args.puffer_root))
    config = _cell_config(args.kind, args.cudagraphs, args)
    pufferl = None
    arrays: dict[str, np.ndarray] = {}
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": args.kind,
        "identity": _module_identity(_C, module, Path(args.puffer_root)),
        "cuda_runtime_preflight": evidence,
        "config": config,
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "seed": args.seed,
        "accepted": False,
    }
    validate_module_identity(result["identity"])
    try:
        if args.kind in STRICT_CONFIG_NEGATIVE_CELL_KINDS:
            invalid_team = _installed_team_count(Path(args.puffer_root))
            config["env"] = {
                "seed": args.seed,
                "max_decisions": 16,
                "force_home_team": invalid_team,
            }
            constructor = (
                "create_vec"
                if args.kind == "strict_negative_create_vec"
                else "create_pufferl"
            )
            result["strict_config_rejection"] = _exercise_expected_strict_rejection(
                _C,
                config,
                constructor=constructor,
                invalid_team=invalid_team,
            )
            result["accepted"] = True
            write_json_atomic(output_json, result)
            return 0
        if args.kind in STRICT_CONFIG_POSITIVE_CELL_KINDS:
            profile = "full" if args.kind == "strict_positive_full" else "sparse"
            config["env"] = (
                _installed_environment_config(Path(args.puffer_root))
                if profile == "full"
                else {"seed": args.seed, "max_decisions": 16}
            )
            result["strict_config_profile"] = profile
            result["strict_config_key_count"] = len(config["env"])
            result["strict_config_constructors"] = (
                _exercise_positive_strict_constructors(_C, config)
            )
            result["accepted"] = True
            write_json_atomic(output_json, result)
            return 0

        pufferl = _C.create_pufferl(config)
        _load_frozen_from_primary(
            _C, pufferl, output_json.parent, int(config["vec"]["num_frozen_banks"])
        )
        if args.kind == "construction":
            result["state"] = _C.qualification_recurrent_state(pufferl, False)
            validate_zero_state(result["state"], expected_banks=2, expected_buffers=1)
        elif args.kind == "rollout":
            result["state_before"] = _C.qualification_recurrent_state(pufferl, False)
            validate_zero_state(
                result["state_before"], expected_banks=2, expected_buffers=1
            )
            _C.rollouts(pufferl)
            arrays = decode_snapshot(_C.qualification_snapshot(pufferl))
            # Keep the first-rollout parity snapshot, then deterministically
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
            result["state_after_first_rollout"] = _C.qualification_recurrent_state(
                pufferl, False
            )
            validate_nonzero_state(
                result["state_after_first_rollout"],
                expected_banks=2,
                expected_buffers=1,
            )
            if args.kind == "terminal_control":
                result["state_after_control_clear"] = _C.qualification_recurrent_state(
                    pufferl, True
                )
                validate_zero_state(
                    result["state_after_control_clear"],
                    expected_banks=2,
                    expected_buffers=1,
                )
            _C.rollouts(pufferl)
            arrays = decode_snapshot(_C.qualification_snapshot(pufferl))
            terminals = arrays.get("terminals")
            if (
                terminals is None
                or terminals.size == 0
                or not np.array_equal(terminals, np.ones_like(terminals))
            ):
                raise QualificationError("terminal cell did not exercise every row")
            bind_transition_integrity(_C, pufferl, result)
        elif args.kind == "ratio":
            _measure_ratio(
                _C,
                pufferl,
                result,
                arrays,
                output_json.parent,
                config,
                args.ratio_call_limit,
            )
        else:
            result["throughput"] = _measure_throughput(
                _C, pufferl, config, evidence, args
            )
        if arrays:
            if output_npz is None:
                raise QualificationError("cell produced arrays without an NPZ path")
            write_npz_atomic(output_npz, arrays)
            result["artifact"] = str(output_npz)
        result["accepted"] = True
        write_json_atomic(output_json, result)
        return 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        write_json_atomic(output_json, result)
        raise
    finally:
        if pufferl is not None and int(config["cudagraphs"]) >= 0:
            # Puffer 4.0's close path dereferences the absent rollout-graph
            # array when cudagraphs=-1. Graph-off cells are process-isolated,
            # so let process teardown release that CUDA context rather than
            # turning a successful parity cell into an unrelated close crash.
            _C.close(pufferl)


# ---------------------------------------- isolated strict-stage worker/driver


def _git_output(puffer_root: Path, *arguments: str) -> str:
    command = ["git", "-C", str(Path(puffer_root).resolve()), *arguments]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(
            f"strict-stage Git command failed: {_bounded_text(exc)}"
        ) from exc
    if completed.returncode != 0:
        detail = _bounded_text(completed.stderr or completed.stdout)
        raise QualificationError(
            f"strict-stage Git command failed ({' '.join(arguments)}): {detail}"
        )
    return completed.stdout.strip()


def _git_optional_output(puffer_root: Path, *arguments: str) -> str:
    try:
        return _git_output(puffer_root, *arguments)
    except QualificationError:
        return ""


def _require_strict_patch_reverse_applicable(puffer_root: Path) -> None:
    command = [
        "git",
        "-C",
        str(Path(puffer_root).resolve()),
        "apply",
        "--reverse",
        "--check",
        "--no-index",
        str(STRICT_ENV_CONFIG_PATCH),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(
            f"strict environment patch check failed: {_bounded_text(exc)}"
        ) from exc
    if completed.returncode != 0:
        detail = _bounded_text(completed.stderr or completed.stdout)
        raise QualificationError(
            f"strict environment patch is not reverse-applicable: {detail}"
        )


def _strict_stage_interpreter(puffer_root: Path, requested: Path | None) -> Path:
    root = Path(puffer_root).resolve()
    venv = root / ".venv"
    if venv.is_symlink() or not venv.is_dir():
        raise QualificationError(
            "strict-stage checkout-local .venv must be a real directory"
        )
    interpreter = (
        Path(os.path.abspath(Path(requested).expanduser()))
        if requested is not None
        else venv / "bin/python"
    )
    expected = venv / "bin/python"
    if interpreter != expected:
        raise QualificationError(
            "strict-stage Python must be the isolated checkout's " ".venv/bin/python"
        )
    if not interpreter.is_file():
        raise QualificationError(
            f"strict-stage isolated Python is missing: {interpreter}"
        )
    if not (venv / "pyvenv.cfg").is_file():
        raise QualificationError(
            "strict-stage Python is not from a checkout-local virtualenv"
        )
    return interpreter


def _strict_stage_child_environment(interpreter: Path) -> dict[str, str]:
    """Build one venv-pinned environment for install, build, and execution."""

    executable = Path(interpreter).absolute()
    venv = executable.parent.parent
    blocked_exact = {
        "ENV",
        "SHELLOPTS",
        "CDPATH",
        "GLOBIGNORE",
        "POSIXLY_CORRECT",
        "LD_PRELOAD",
        "LD_AUDIT",
        "DYLD_INSERT_LIBRARIES",
        "DYLD_FORCE_FLAT_NAMESPACE",
    }
    blocked_prefixes = (
        "BASH",
        "PYTHON",
        "VIRTUAL_ENV",
        "CONDA_",
    )
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in blocked_exact
        and not any(key.startswith(prefix) for prefix in blocked_prefixes)
    }
    prior_path = environment.get("PATH", "")
    environment["PATH"] = str(executable.parent) + (
        os.pathsep + prior_path if prior_path else ""
    )
    environment["VIRTUAL_ENV"] = str(venv)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PUFFER_INSTALL_PYTHON"] = str(executable)
    environment["PUFFER_STRICT_ENV_CONFIG_TESTING"] = "1"
    return environment


def _strict_stage_interpreter_probe(
    *,
    interpreter: Path,
    puffer_root: Path,
    environment: Mapping[str, str],
) -> dict[str, Any]:
    """Prove bare `python` and its build dependencies come from one venv."""

    probe_source = (
        "import json, platform, sys, sysconfig\n"
        "import numpy, pybind11\n"
        "print(json.dumps({"
        "'executable': sys.executable,"
        "'prefix': sys.prefix,"
        "'base_prefix': sys.base_prefix,"
        "'ext_suffix': sysconfig.get_config_var('EXT_SUFFIX'),"
        "'python_version': platform.python_version(),"
        "'pybind11_path': pybind11.__file__,"
        "'numpy_path': numpy.__file__"
        "}, sort_keys=True))\n"
    )
    commands = (
        ("direct", ["python", "-c", probe_source]),
        (
            "Bash",
            [
                "/bin/bash",
                "--noprofile",
                "--norc",
                "-c",
                'python "$@"',
                "strict-stage-python",
                "-c",
                probe_source,
            ],
        ),
    )
    identities: list[dict[str, Any]] = []
    for label, command in commands:
        try:
            completed = subprocess.run(
                command,
                cwd=Path(puffer_root).resolve(),
                env=dict(environment),
                text=True,
                capture_output=True,
                check=True,
                timeout=30,
            )
        except (
            OSError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            raise QualificationError(
                f"strict-stage isolated {label} Python probe failed: "
                f"{_bounded_text(exc)}"
            ) from exc
        if len(completed.stdout.encode("utf-8", errors="replace")) > (
            STRICT_STAGE_MAX_JSON_BYTES
        ):
            raise QualificationError(
                f"strict-stage isolated {label} Python probe is oversized"
            )
        try:
            identity = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise QualificationError(
                f"strict-stage isolated {label} Python probe returned " "malformed JSON"
            ) from exc
        if not isinstance(identity, dict):
            raise QualificationError(
                f"strict-stage isolated {label} Python probe did not return "
                "an object"
            )
        identity["executable_sha256"] = sha256(interpreter)
        identities.append(
            _validate_strict_stage_interpreter_identity(
                identity,
                puffer_root=Path(puffer_root).resolve(),
                expected_interpreter=Path(interpreter).absolute(),
                rehash_executable=True,
            )
        )
    if identities[0] != identities[1]:
        raise QualificationError(
            "strict-stage Bash Python identity differs from the direct probe"
        )
    return identities[0]


def _strict_stage_current_interpreter_identity() -> dict[str, Any]:
    import pybind11

    suffix = __import__("sysconfig").get_config_var("EXT_SUFFIX")
    identity = {
        "executable": sys.executable,
        "executable_sha256": sha256(Path(sys.executable)),
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "ext_suffix": suffix,
        "python_version": platform.python_version(),
        "pybind11_path": pybind11.__file__,
        "numpy_path": np.__file__,
    }
    return identity


def _require_detached_head(puffer_root: Path) -> None:
    command = [
        "git",
        "-C",
        str(Path(puffer_root).resolve()),
        "symbolic-ref",
        "--quiet",
        "HEAD",
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(
            f"strict-stage detached-HEAD check failed: {_bounded_text(exc)}"
        ) from exc
    if completed.returncode == 0:
        raise QualificationError("strict-stage checkout must use a detached HEAD")
    if completed.returncode != 1:
        detail = _bounded_text(completed.stderr or completed.stdout)
        raise QualificationError(f"strict-stage detached-HEAD check failed: {detail}")


def _strict_stage_module_artifacts(puffer_root: Path) -> list[str]:
    directory = Path(puffer_root).resolve() / "pufferlib"
    if not directory.is_dir():
        return []
    suffixes = (".so", ".pyd", ".dylib")
    return sorted(
        str(path.relative_to(puffer_root))
        for path in directory.glob("_C*")
        if path.is_file() and path.name.endswith(suffixes)
    )


def _prepare_strict_stage_isolation(
    *,
    puffer_root: Path,
    output: Path,
    python: Path | None,
    confirmed: bool,
) -> tuple[Path, Path, dict[str, Any], dict[str, str]]:
    if not confirmed:
        raise QualificationError(
            "--confirm-isolated-test-checkout is required for the test-role build"
        )
    root = Path(puffer_root).resolve()
    output = Path(output).resolve()
    if not (root / ".git").exists() or not (root / "build.sh").is_file():
        raise QualificationError("strict-stage target is not a Puffer Git checkout")
    try:
        root.relative_to(REPO_ROOT)
    except ValueError:
        pass
    else:
        raise QualificationError(
            "strict-stage checkout must be outside this repository"
        )
    try:
        output.relative_to(root)
    except ValueError:
        pass
    else:
        raise QualificationError(
            "strict-stage evidence output must be outside the isolated checkout"
        )
    top = Path(_git_output(root, "rev-parse", "--show-toplevel")).resolve()
    if top != root:
        raise QualificationError("strict-stage target is not the Git checkout root")
    head = _git_output(root, "rev-parse", "HEAD")
    if head != PINNED_PUFFER_COMMIT:
        raise QualificationError(
            f"strict-stage checkout must be detached at {PINNED_PUFFER_COMMIT}"
        )
    _require_detached_head(root)
    status = _git_output(root, "status", "--porcelain=v1", "--untracked-files=all")
    if status:
        raise QualificationError(
            "strict-stage checkout must be pristine before installer mutation"
        )
    interpreter = _strict_stage_interpreter(root, python)
    child_environment = _strict_stage_child_environment(interpreter)
    interpreter_identity = _strict_stage_interpreter_probe(
        interpreter=interpreter,
        puffer_root=root,
        environment=child_environment,
    )
    build_absent = not (root / "build").exists()
    environment_absent = not (root / "ocean/bloodbowl").exists()
    module_absent = not _strict_stage_module_artifacts(root)
    if not build_absent:
        raise QualificationError("strict-stage checkout already has a build directory")
    if not environment_absent:
        raise QualificationError(
            "strict-stage checkout already has an installed Blood Bowl environment"
        )
    if not module_absent:
        raise QualificationError(
            "strict-stage checkout already has a compiled native module"
        )
    final_path = output / "STRICT_STAGE_ORDER.json"
    receipt_path = output / "ISOLATION.json"
    if final_path.exists() or receipt_path.exists():
        raise QualificationError(
            "strict-stage output already contains a final artifact or receipt"
        )
    receipt = {
        "schema_version": STRICT_STAGE_SCHEMA_VERSION,
        "evidence_kind": STRICT_STAGE_RECEIPT_KIND,
        "puffer_root": str(root),
        "git_head": head,
        "initial_status": status,
        "initial_status_sha256": hashlib.sha256(status.encode("utf-8")).hexdigest(),
        "separate_from_repo_vendor_checkout": True,
        "confirmed_isolated_test_checkout": True,
        "build_absent": build_absent,
        "environment_absent": environment_absent,
        "module_absent": module_absent,
        "detached_head": True,
        "interpreter": str(interpreter),
        "interpreter_identity": interpreter_identity,
        "origin": _bounded_text(
            _git_optional_output(root, "config", "--get", "remote.origin.url"),
            2048,
        ),
    }
    _validate_strict_stage_receipt(
        receipt,
        expected_puffer_root=root,
        rehash_executable=True,
    )
    return interpreter, receipt_path, receipt, child_environment


def _run_strict_stage_command(
    command: list[str],
    *,
    cwd: Path,
    timeout: float,
    label: str,
    environment: Mapping[str, str] | None = None,
) -> None:
    if not math.isfinite(timeout) or timeout <= 0:
        raise QualificationError(f"{label} timeout must be positive and finite")
    try:
        subprocess.run(
            command,
            cwd=cwd,
            env=None if environment is None else dict(environment),
            check=True,
            timeout=timeout,
        )
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise QualificationError(f"{label} failed: {_bounded_text(exc)}") from exc


def run_strict_stage_worker(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json).resolve()
    root = Path(args.puffer_root).resolve()
    failure: dict[str, Any] = {
        "schema_version": STRICT_STAGE_SCHEMA_VERSION,
        "evidence_kind": STRICT_STAGE_EVIDENCE_KIND,
        "qualification_only": True,
        "mandatory_external_gpu_gate": True,
        "accepted": False,
    }
    try:
        if _git_output(root, "rev-parse", "HEAD") != PINNED_PUFFER_COMMIT:
            raise QualificationError("strict-stage worker Puffer pin drifted")
        _require_detached_head(root)
        receipt_path = Path(os.path.abspath(Path(args.isolation_receipt)))
        receipt = _read_json(
            receipt_path,
            maximum_bytes=STRICT_STAGE_MAX_JSON_BYTES,
            require_regular=True,
        )
        _validate_strict_stage_receipt(
            receipt,
            expected_puffer_root=root,
            rehash_executable=True,
        )
        current_interpreter_identity = _validate_strict_stage_interpreter_identity(
            _strict_stage_current_interpreter_identity(),
            puffer_root=root,
            expected_interpreter=Path(receipt["interpreter"]),
            rehash_executable=True,
        )
        if current_interpreter_identity != receipt["interpreter_identity"]:
            raise QualificationError(
                "strict-stage worker interpreter identity differs from pre-build probe"
            )
        receipt_sha = sha256(receipt_path)
        _require_strict_patch_reverse_applicable(root)
        _C, module, cuda_evidence = _load_backend(root)
        identity = _strict_stage_module_identity(_C, module, root)
        validate_strict_stage_module_identity(identity)
        try:
            validate_module_identity(identity)
        except QualificationError as exc:
            production_rejection = {
                "rejected": True,
                "exception_type": "QualificationError",
                "message": _bounded_text(exc),
            }
        else:
            raise QualificationError(
                "production module identity accepted the test-role module"
            )
        exercised = _exercise_strict_cuda_stage_order(
            _C,
            seed=args.seed,
            invalid_team=_installed_team_count(root),
        )
        result = {
            "schema_version": STRICT_STAGE_SCHEMA_VERSION,
            "evidence_kind": STRICT_STAGE_EVIDENCE_KIND,
            "qualification_only": True,
            "mandatory_external_gpu_gate": True,
            "accepted": True,
            "identity": identity,
            "cuda_runtime_preflight": cuda_evidence,
            "isolation": {
                "receipt": receipt,
                "receipt_sha256": receipt_sha,
            },
            "patch_identity": {
                "puffer_git_head": PINNED_PUFFER_COMMIT,
                "strict_environment_config_patch": {
                    "path": str(STRICT_ENV_CONFIG_PATCH.resolve()),
                    "sha256": sha256(STRICT_ENV_CONFIG_PATCH),
                    "reverse_applicable": True,
                },
                "qualifier": {
                    "path": str(Path(__file__).resolve()),
                    "sha256": sha256(Path(__file__).resolve()),
                },
                "compiled_backend_source_ledger": {
                    "path": str(COMPILED_BACKEND_SOURCE_LEDGER.resolve()),
                    "sha256": sha256(COMPILED_BACKEND_SOURCE_LEDGER),
                },
            },
            **exercised,
            "production_identity_rejection": production_rejection,
            "host": socket.gethostname(),
            "platform": platform.platform(),
            "seed": args.seed,
        }
        validate_strict_stage_evidence(
            result,
            expected_puffer_root=root,
            expected_receipt_path=receipt_path,
            rehash_files=True,
        )
        write_bounded_json_atomic(output_json, result)
        print(f"strict CUDA stage-order qualification accepted -> {output_json}")
        return 0
    except Exception as exc:
        failure["error"] = f"{type(exc).__name__}: {_bounded_text(exc)}"
        write_bounded_json_atomic(output_json, failure)
        raise


def run_strict_stage_order(args: argparse.Namespace) -> int:
    root = Path(args.puffer_root).resolve()
    output = Path(args.output).resolve()
    (
        interpreter,
        receipt_path,
        receipt,
        test_build_environment,
    ) = _prepare_strict_stage_isolation(
        puffer_root=root,
        output=output,
        python=args.python,
        confirmed=args.confirm_isolated_test_checkout,
    )
    output.mkdir(parents=True, exist_ok=True)
    write_bounded_json_atomic(receipt_path, receipt)

    _run_strict_stage_command(
        ["/bin/bash", str(REPO_ROOT / "tools/install_puffer_env.sh"), str(root)],
        cwd=REPO_ROOT,
        timeout=args.install_timeout_seconds,
        label="strict-stage isolated installer",
        environment=test_build_environment,
    )
    if _git_output(root, "rev-parse", "HEAD") != PINNED_PUFFER_COMMIT:
        raise QualificationError("strict-stage isolated installer changed the Git pin")
    _require_detached_head(root)
    _run_strict_stage_command(
        ["./build.sh", "bloodbowl"],
        cwd=root,
        timeout=args.build_timeout_seconds,
        label="strict-stage isolated CUDA build",
        environment=test_build_environment,
    )
    final_path = output / "STRICT_STAGE_ORDER.json"
    _run_strict_stage_command(
        [
            str(interpreter),
            str(Path(__file__).resolve()),
            "strict-stage-worker",
            "--puffer-root",
            str(root),
            "--seed",
            str(args.seed),
            "--output-json",
            str(final_path),
            "--isolation-receipt",
            str(receipt_path),
        ],
        cwd=root,
        timeout=args.worker_timeout_seconds,
        label="strict-stage isolated worker",
        environment=test_build_environment,
    )
    evidence = _read_json(
        final_path,
        maximum_bytes=STRICT_STAGE_MAX_JSON_BYTES,
        require_regular=True,
    )
    validate_strict_stage_evidence(
        evidence,
        expected_puffer_root=root,
        expected_receipt_path=receipt_path,
        rehash_files=True,
    )
    _require_strict_patch_reverse_applicable(root)
    print(f"strict CUDA stage-order release gate accepted -> {final_path}")
    return 0


# ------------------------------------------------------------------------ driver


def _run_worker(
    args: argparse.Namespace, *, kind: str, name: str, cudagraphs: int, output: Path
) -> dict[str, Any]:
    python = (
        Path(args.python).expanduser().absolute()
        if args.python
        else (Path(args.puffer_root).resolve() / ".venv" / "bin" / "python")
    )
    # Absolute, not resolved: resolving a venv's python symlink escapes the venv.
    if not python.is_file():
        raise QualificationError(f"Puffer Python is missing: {python}")
    json_path = output / f"{name}.json"
    command = [
        str(python),
        str(Path(__file__).resolve()),
        "cell",
        "--puffer-root",
        str(Path(args.puffer_root).resolve()),
        "--kind",
        kind,
        "--cudagraphs",
        str(cudagraphs),
        "--seed",
        str(args.seed),
        "--output-json",
        str(json_path),
        "--output-npz",
        str(output / f"{name}.npz"),
        "--ratio-call-limit",
        str(args.ratio_call_limit),
        "--throughput-agents",
        str(args.throughput_agents),
        "--throughput-buffers",
        str(args.throughput_buffers),
        "--throughput-threads",
        str(args.throughput_threads),
        "--throughput-horizon",
        str(args.throughput_horizon),
        "--throughput-hidden",
        str(args.throughput_hidden),
        "--throughput-layers",
        str(args.throughput_layers),
        "--throughput-minibatch-size",
        str(args.throughput_minibatch_size),
        "--throughput-warmup-rollouts",
        str(args.throughput_warmup_rollouts),
        "--throughput-timed-rollouts",
        str(args.throughput_timed_rollouts),
    ]
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
    if record.get("accepted") is not True:
        raise QualificationError(f"qualification cell {name} is not accepted")
    validate_cell_cudagraph_record(record, expected=cudagraphs)
    if kind in TRANSITION_CELL_KINDS:
        validate_transition_cell_integrity(record, kind)
    elif kind in STRICT_CONFIG_NEGATIVE_CELL_KINDS:
        validate_strict_rejection_record(
            record,
            constructor=(
                "create_vec"
                if kind == "strict_negative_create_vec"
                else "create_pufferl"
            ),
        )
    elif kind in STRICT_CONFIG_POSITIVE_CELL_KINDS:
        validate_positive_strict_record(
            record,
            profile="full" if kind == "strict_positive_full" else "sparse",
        )
    record["record_path"] = str(json_path)
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
    return validate_module_identity(reference)


def _require_same_cuda_runtime(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    records = list(records)
    if not records:
        raise QualificationError("no cell CUDA runtime evidence was supplied")
    try:
        reference = validate_cuda_runtime_evidence(
            records[0].get("cuda_runtime_preflight")
        )
    except CudaRuntimePreflightError as exc:
        raise QualificationError(
            f"qualification CUDA runtime evidence failed: {exc}"
        ) from exc
    for record in records[1:]:
        if record.get("cuda_runtime_preflight") != reference:
            raise QualificationError("qualification cell CUDA runtime drifted")
    return reference


def run_qualification(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    records: list[dict[str, Any]] = []

    def cell(kind: str, name: str, cudagraphs: int = DEFAULT_CUDAGRAPH_WARMUP_EPOCHS):
        record = _run_worker(
            args, kind=kind, name=name, cudagraphs=cudagraphs, output=output
        )
        records.append(record)
        _require_same_identity(records)
        return record

    gates: dict[str, dict[str, Any]] = {}

    strict_negative_vec = cell(
        "strict_negative_create_vec",
        "strict-negative-create-vec",
    )
    strict_negative_pufferl = cell(
        "strict_negative_create_pufferl",
        "strict-negative-create-pufferl",
    )
    strict_positive_full = cell(
        "strict_positive_full",
        "strict-positive-full",
    )
    strict_positive_sparse = cell(
        "strict_positive_sparse",
        "strict-positive-sparse",
    )
    gates["strict_environment_config"] = {
        "accepted": True,
        "negative_subcells": [
            validate_strict_rejection_record(
                strict_negative_vec,
                constructor="create_vec",
            ),
            validate_strict_rejection_record(
                strict_negative_pufferl,
                constructor="create_pufferl",
            ),
        ],
        "positive_profiles": {
            "full": validate_positive_strict_record(
                strict_positive_full,
                profile="full",
            ),
            "sparse": validate_positive_strict_record(
                strict_positive_sparse,
                profile="sparse",
            ),
        },
    }

    construction = cell("construction", "construction")
    validate_zero_state(construction["state"], expected_banks=2, expected_buffers=1)
    gates["construction_state"] = {"accepted": True}

    graph_off = cell("rollout", "graph-off", cudagraphs=-1)
    graph_on = cell("rollout", "graph-on")
    # Every cell recomputes the backend/snapshot digests from the live tree in
    # its own process, so an identity that agrees across cells also rules out a
    # rebuild landing mid-qualification.
    identity = _require_same_identity(records)
    atol = GRAPH_ATOL_BY_PRECISION[int(identity["precision_bytes"])]
    off_arrays = _read_npz(Path(graph_off["artifact"]))
    on_arrays = _read_npz(Path(graph_on["artifact"]))
    gates["graph_parity"] = {
        "accepted": True,
        "atol": atol,
        "snapshot_max_abs": compare_snapshots(off_arrays, on_arrays, atol=atol),
        "decoder_max_abs": compare_decoder_outputs(off_arrays, on_arrays, atol=atol),
    }

    auto = cell("terminal_auto", "terminal-auto")
    control = cell("terminal_control", "terminal-control")
    validate_nonzero_state(
        auto["state_after_first_rollout"], expected_banks=2, expected_buffers=1
    )
    validate_zero_state(
        control["state_after_control_clear"], expected_banks=2, expected_buffers=1
    )
    auto_arrays = _read_npz(Path(auto["artifact"]))
    control_arrays = _read_npz(Path(control["artifact"]))
    gates["terminal_reset"] = {
        "accepted": True,
        "atol": atol,
        "snapshot_max_abs": compare_snapshots(
            auto_arrays, control_arrays, atol=atol, require_all_terminal=True
        ),
        "decoder_max_abs": compare_decoder_outputs(
            auto_arrays, control_arrays, atol=atol
        ),
    }

    ratio = cell("ratio", "ratio")
    layout = ratio.get("row_partition")
    if not isinstance(layout, Mapping) or not isinstance(
        layout.get("state_layout"), Mapping
    ):
        raise QualificationError("ratio row partition evidence is missing")
    primary_rows, frozen_rows = derive_row_partition(
        layout["state_layout"],
        total_agents=int(ratio["config"]["vec"]["total_agents"]),
    )
    if layout.get("primary_rows") != sorted(primary_rows) or layout.get(
        "frozen_rows"
    ) != sorted(frozen_rows):
        raise QualificationError("ratio row partition record differs from bank layout")
    ratio_arrays = _read_npz(Path(ratio["artifact"]))
    validate_weight_identity(
        ratio["weights_before_sha256"], ratio["weights_after_sha256"]
    )
    gates["ratio"] = {
        "accepted": True,
        **validate_ratio_calls(
            [
                {
                    "selected_rows": ratio_arrays[f"selected_{index}"].astype(
                        np.int32, copy=False
                    ),
                    "ratios": ratio_arrays[f"ratio_{index}"].astype(
                        np.float32, copy=False
                    ),
                }
                for index in range(int(ratio["ratio_calls"]))
            ],
            primary_rows=primary_rows,
            frozen_rows=frozen_rows,
            atol=RATIO_ATOL_BY_PRECISION[int(identity["precision_bytes"])],
        ),
        "weights_sha256": ratio["weights_before_sha256"],
    }

    throughput = cell("throughput", "throughput")["throughput"]
    _require_same_cuda_runtime(records)
    _validate_throughput_record(throughput, "candidate")
    gates["throughput"] = {
        "accepted": True,
        "steps_per_second": throughput["steps_per_second"],
    }
    if args.baseline_throughput:
        baseline = _read_json(Path(args.baseline_throughput)).get("throughput")
        if not isinstance(baseline, Mapping):
            raise QualificationError(
                "baseline artifact has no throughput record to compare against"
            )
        gates["throughput"].update(
            validate_throughput(
                throughput,
                baseline,
                max_regression_fraction=args.max_regression_fraction,
            )
        )

    final = {
        "schema_version": SCHEMA_VERSION,
        "qualification_only": True,
        "identity": identity,
        "cuda_runtime_preflight": records[0]["cuda_runtime_preflight"],
        "host": socket.gethostname(),
        "gates": gates,
        "throughput": throughput,
        "cells": [
            {
                "name": Path(record["record_path"]).stem,
                "kind": record["kind"],
                "record": record["record_path"],
                "artifact": record.get("artifact"),
            }
            for record in records
        ],
        **combine_gate_verdicts(gates),
    }
    write_json_atomic(output / "QUALIFICATION.json", final)
    print(
        f"qualification accepted={final['accepted']} "
        f"steps_per_second={throughput['steps_per_second']:.1f} "
        f"-> {output / 'QUALIFICATION.json'}"
    )
    return 0 if final["accepted"] else 1


def add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--puffer-root", required=True, type=Path)
    parser.add_argument("--python", type=Path)
    parser.add_argument("--seed", type=int, default=271828)
    parser.add_argument(
        "--ratio-call-limit", type=int, default=DEFAULT_RATIO_CALL_LIMIT
    )
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

    run = subparsers.add_parser("run", help="run every gate, write QUALIFICATION.json")
    add_common_arguments(run)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument(
        "--baseline-throughput",
        type=Path,
        help="previous QUALIFICATION.json to compare steps/second against",
    )
    run.add_argument(
        "--max-regression-fraction",
        type=float,
        default=DEFAULT_MAX_REGRESSION_FRACTION,
    )

    cell = subparsers.add_parser("cell", help=argparse.SUPPRESS)
    add_common_arguments(cell)
    cell.add_argument("--kind", required=True, choices=CELL_KINDS)
    cell.add_argument("--cudagraphs", type=int, required=True)
    cell.add_argument("--output-json", required=True, type=Path)
    cell.add_argument("--output-npz", type=Path)

    strict_stage = subparsers.add_parser(
        "strict-stage-order",
        help=(
            "build and qualify a test-role CUDA module in a pristine external "
            "Puffer checkout"
        ),
    )
    strict_stage.add_argument(
        "--isolated-puffer-root",
        dest="puffer_root",
        required=True,
        type=Path,
    )
    strict_stage.add_argument("--output", required=True, type=Path)
    strict_stage.add_argument("--python", type=Path)
    strict_stage.add_argument("--seed", type=int, default=271828)
    strict_stage.add_argument("--install-timeout-seconds", type=float, default=600.0)
    strict_stage.add_argument("--build-timeout-seconds", type=float, default=1800.0)
    strict_stage.add_argument("--worker-timeout-seconds", type=float, default=300.0)
    strict_stage.add_argument(
        "--confirm-isolated-test-checkout",
        action="store_true",
        required=True,
        help=(
            "confirm this disposable exact-pin checkout is not a production "
            "or vendored Puffer tree"
        ),
    )

    strict_stage_worker = subparsers.add_parser(
        "strict-stage-worker", help=argparse.SUPPRESS
    )
    strict_stage_worker.add_argument("--puffer-root", required=True, type=Path)
    strict_stage_worker.add_argument("--seed", type=int, default=271828)
    strict_stage_worker.add_argument("--output-json", required=True, type=Path)
    strict_stage_worker.add_argument("--isolation-receipt", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "strict-stage-order":
        return run_strict_stage_order(args)
    if args.command == "strict-stage-worker":
        return run_strict_stage_worker(args)
    if args.ratio_call_limit <= 0:
        raise QualificationError("ratio call limit must be positive")
    if args.throughput_warmup_rollouts < 0 or args.throughput_timed_rollouts <= 0:
        raise QualificationError("throughput rollout counts are invalid")
    validate_throughput_minibatch(
        args.throughput_agents,
        args.throughput_horizon,
        args.throughput_minibatch_size,
    )
    if args.command == "cell":
        validate_cell_cudagraphs(args.kind, args.cudagraphs)
        return run_cell(args)
    if args.command == "run":
        return run_qualification(args)
    raise QualificationError(f"unknown command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except QualificationError as exc:
        print(f"qualification failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
