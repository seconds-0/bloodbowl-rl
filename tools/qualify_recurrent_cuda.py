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


SCHEMA_VERSION = 4
MANDATORY_GATES = (
    "construction_state", "graph_parity", "terminal_reset", "ratio", "throughput",
)
SNAPSHOT_FIELDS = (
    "observations", "actions", "values", "logprobs", "rewards", "terminals",
    "action_mask",
)
EXACT_SNAPSHOT_FIELDS = (
    "observations", "actions", "rewards", "terminals", "action_mask",
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
CELL_KINDS = ("construction", *sorted(TRANSITION_CELL_KINDS))
GRAPH_ATOL_BY_PRECISION = {4: 1.0e-6}
RATIO_ATOL_BY_PRECISION = {4: 2.0e-5}
DEFAULT_RATIO_CALL_LIMIT = 64
DEFAULT_MAX_REGRESSION_FRACTION = 0.10
# Puffer's cudagraph setting is a warmup-epoch count, not a boolean. 0 captures
# the first execution before CUDA lazy initialization; -1 means graphs off.
DEFAULT_CUDAGRAPH_WARMUP_EPOCHS = 10
DEFAULT_THROUGHPUT_MINIBATCH_SIZE = 16384
BACKEND_SOURCE_FILES = (
    "pufferlib/pufferl.py", "pufferlib/selfplay.py", "pufferlib/torch_pufferl.py",
    "src/bindings.cu", "src/bindings_cpu.cpp", "src/kernels.cu",
    "src/pufferlib.cu", "src/vecenv.h",
)
QUALIFICATION_SURFACE_BINDINGS = (
    "qualification_recurrent_state", "qualification_snapshot",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


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


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
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
        if (rows > shape[1] or entry.get("elements") != elements
                or entry.get("active_elements") != elements // shape[1] * rows):
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
            raise QualificationError("exercised recurrent state contains non-finite values")
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
    if layout[0] != 0 or layout[-1] != per_buffer or any(
        left >= right for left, right in zip(layout, layout[1:])
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
    if not primary or not frozen or primary & frozen or primary | frozen != set(
        range(total_agents)
    ):
        raise QualificationError("row partition does not cover disjoint learner/frozen rows")
    return primary, frozen


# ------------------------------------------------------- rollout / PPO evidence


def _validate_array_pair(key: str, left: Any, right: Any) -> tuple[np.ndarray, np.ndarray]:
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
        if terminals.size == 0 or not np.array_equal(terminals, np.ones_like(terminals)):
            raise QualificationError("post-terminal snapshot does not mark every row terminal")
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
    return {key: _max_abs_error(key, left[key], right[key], atol) for key in sorted(keys)}


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
            raise QualificationError(f"recomputed ratio error {observed} exceeds {tolerance}")
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
    for _ in range(_int(additional_rollouts, "additional integrity rollouts", minimum=0)):
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
    if elapsed <= 0 or sps <= 0 or not math.isclose(
        sps, steps / elapsed, rel_tol=1.0e-12, abs_tol=0.0
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
        record.get("dtype"), record.get("shape"), record.get("data")
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
    if (total_agents <= 0 or horizon <= 0 or minibatch_size <= 0
            or minibatch_size % horizon or minibatch_size > quantum
            or quantum % minibatch_size):
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
        total_agents, horizon,
        total_agents * horizon if minibatch_size is None else minibatch_size,
    )
    return {
        "env_name": "bloodbowl", "reset_state": True, "cudagraphs": cudagraphs,
        "profile": False, "rank": 0, "world_size": 1, "gpu_id": 0, "nccl_id": "",
        "seed": seed,
        "vec": {
            "total_agents": total_agents, "num_buffers": num_buffers,
            "num_threads": num_threads, "num_frozen_banks": frozen_banks,
            "frozen_bank_pct": frozen_bank_pct if frozen_banks else 0.0,
            "frozen_bank_hidden_size": hidden_size,
            "frozen_bank_num_layers": num_layers,
        },
        "env": {"seed": seed, "max_decisions": max_decisions},
        "policy": {"hidden_size": hidden_size, "num_layers": num_layers},
        "train": {
            "horizon": horizon, "learning_rate": learning_rate,
            "min_lr_ratio": 1.0, "anneal_lr": False, "beta1": 0.9, "beta2": 0.95,
            "eps": 1.0e-8, "minibatch_size": minibatch_size,
            "replay_ratio": replay_ratio,
            "total_timesteps": max(minibatch_size * 256, 1),
            "max_grad_norm": 1.0, "clip_coef": 0.2, "vf_clip_coef": 0.2,
            "vf_coef": 0.5, "ent_coef": 0.0, "min_ent_coef_ratio": 1.0,
            "anneal_ent_coef": False, "gamma": 0.995, "gae_lambda": 0.95,
            "vtrace_rho_clip": 1.0, "vtrace_c_clip": 1.0,
            "prio_alpha": 0.0, "prio_beta0": 1.0,
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
        raise QualificationError(f"qualification CUDA runtime evidence failed: {exc}") from exc
    return dict(config)


def _cell_config(kind: str, cudagraphs: int, args: argparse.Namespace) -> dict[str, Any]:
    cudagraphs = validate_cell_cudagraphs(kind, cudagraphs)
    if kind in {"construction", "rollout", "terminal_auto", "terminal_control"}:
        return qualification_args(
            cudagraphs=cudagraphs, seed=args.seed, total_agents=2, num_buffers=1,
            num_threads=1, horizon=1,
            max_decisions=1 if kind.startswith("terminal_") else 16,
            hidden_size=64, num_layers=1, frozen_banks=1, frozen_bank_pct=0.5,
            learning_rate=0.0,
        )
    if kind == "ratio":
        return qualification_args(
            cudagraphs=cudagraphs, seed=args.seed, total_agents=8, num_buffers=2,
            num_threads=2, horizon=8, max_decisions=4, hidden_size=64,
            num_layers=1, frozen_banks=1, frozen_bank_pct=0.5, learning_rate=0.0,
        )
    if kind == "throughput":
        return qualification_args(
            cudagraphs=cudagraphs, seed=args.seed,
            total_agents=args.throughput_agents,
            num_buffers=args.throughput_buffers,
            num_threads=args.throughput_threads,
            horizon=args.throughput_horizon, max_decisions=64,
            hidden_size=args.throughput_hidden, num_layers=args.throughput_layers,
            frozen_banks=1, frozen_bank_pct=0.1, learning_rate=0.0,
            minibatch_size=args.throughput_minibatch_size,
        )
    raise QualificationError(f"unknown qualification cell: {kind}")


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
    root = Path(puffer_root).resolve()
    manifest = bytearray()
    for relative in source_files:
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
        raise QualificationError(f"CUDA runtime post-import gate failed: {exc}") from exc
    module = Path(_C.__file__).resolve()
    try:
        module.relative_to(root)
    except ValueError as exc:
        raise QualificationError(
            f"imported native module is outside Puffer root: {module}"
        ) from exc
    missing = [
        name for name in (
            "create_pufferl", "rollouts", "log", "get_utilization", "save_weights",
            "load_frozen_bank", "set_evaluation_mode", "train",
            *QUALIFICATION_SURFACE_BINDINGS,
        ) if not hasattr(_C, name)
    ]
    if missing:
        raise QualificationError(f"compiled qualification surface is missing: {missing}")
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
        "precision_bytes": int(_C.precision_bytes),
        "compiled_env": str(_C.env_name),
        "qualification_surface": qualification_surface_state(_C),
    }


def validate_module_identity(
    identity: Mapping[str, Any], *, qualification_surface: bool = True
) -> dict[str, Any]:
    """The imported module really is obs-v6 / exact-joint-v1 / fp32.

    obs-v4, obs-v5 and obs-v6 are all 2782 bytes, so only this provenance
    separates them; a mixup already wasted a 12B-step run. The two digest equalities are
    compiled == on-disk source and compiled == installed snapshot: the build
    compiles the snapshot, not your edit.
    """
    if identity.get("compiled_env") != "bloodbowl":
        raise QualificationError("compiled environment is not bloodbowl")
    if identity.get("observation_abi") != "obs-v6" or identity.get(
        "observation_version"
    ) != 6:
        raise QualificationError("compiled observation lineage is not obs-v6")
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
    if identity["compiled_backend_sha256"] != identity["backend_sources_sha256"]:
        raise QualificationError("compiled module differs from backend source digest")
    if identity["environment_sha256"] != identity["installed_snapshot_sha256"]:
        raise QualificationError("compiled module differs from installed environment digest")
    module = Path(str(identity.get("module", ""))).resolve()
    try:
        module.relative_to(Path(str(identity.get("puffer_root", ""))).resolve())
    except ValueError as exc:
        raise QualificationError("compiled module is outside recorded Puffer root") from exc
    return dict(identity)


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
    _C, pufferl, result: dict[str, Any], arrays: dict[str, np.ndarray],
    directory: Path, config: Mapping[str, Any], call_limit: int,
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
    _C, pufferl, config: Mapping[str, Any], evidence: Mapping[str, Any],
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
        gpu = subprocess.run(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True, capture_output=True, check=True, timeout=10,
        ).stdout.strip().splitlines()[0]
    return {
        "host": socket.gethostname(), "gpu": gpu,
        "precision_bytes": int(_C.precision_bytes), "config": dict(config),
        "steps": steps, "elapsed_seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "median_rollout_seconds": statistics.median(durations),
        "p95_rollout_seconds": float(np.percentile(durations, 95)),
        "hard_integrity_zero": True, "hard_integrity": integrity,
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
                _C, pufferl, result,
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
                expected_banks=2, expected_buffers=1,
            )
            if args.kind == "terminal_control":
                result["state_after_control_clear"] = _C.qualification_recurrent_state(
                    pufferl, True
                )
                validate_zero_state(
                    result["state_after_control_clear"],
                    expected_banks=2, expected_buffers=1,
                )
            _C.rollouts(pufferl)
            arrays = decode_snapshot(_C.qualification_snapshot(pufferl))
            terminals = arrays.get("terminals")
            if terminals is None or terminals.size == 0 or not np.array_equal(
                terminals, np.ones_like(terminals)
            ):
                raise QualificationError("terminal cell did not exercise every row")
            bind_transition_integrity(_C, pufferl, result)
        elif args.kind == "ratio":
            _measure_ratio(
                _C, pufferl, result, arrays, output_json.parent, config,
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


# ------------------------------------------------------------------------ driver


def _run_worker(
    args: argparse.Namespace, *, kind: str, name: str, cudagraphs: int, output: Path
) -> dict[str, Any]:
    python = Path(args.python).expanduser().absolute() if args.python else (
        Path(args.puffer_root).resolve() / ".venv" / "bin" / "python"
    )
    # Absolute, not resolved: resolving a venv's python symlink escapes the venv.
    if not python.is_file():
        raise QualificationError(f"Puffer Python is missing: {python}")
    json_path = output / f"{name}.json"
    command = [
        str(python), str(Path(__file__).resolve()), "cell",
        "--puffer-root", str(Path(args.puffer_root).resolve()),
        "--kind", kind,
        "--cudagraphs", str(cudagraphs),
        "--seed", str(args.seed),
        "--output-json", str(json_path),
        "--output-npz", str(output / f"{name}.npz"),
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
    completed = subprocess.run(
        command, cwd=Path(args.puffer_root).resolve(), text=True,
        capture_output=True, timeout=args.cell_timeout_seconds,
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
        reference = validate_cuda_runtime_evidence(records[0].get("cuda_runtime_preflight"))
    except CudaRuntimePreflightError as exc:
        raise QualificationError(f"qualification CUDA runtime evidence failed: {exc}") from exc
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
        "accepted": True, "atol": atol,
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
        "accepted": True, "atol": atol,
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
            primary_rows=primary_rows, frozen_rows=frozen_rows,
            atol=RATIO_ATOL_BY_PRECISION[int(identity["precision_bytes"])],
        ),
        "weights_sha256": ratio["weights_before_sha256"],
    }

    throughput = cell("throughput", "throughput")["throughput"]
    _require_same_cuda_runtime(records)
    _validate_throughput_record(throughput, "candidate")
    gates["throughput"] = {
        "accepted": True, "steps_per_second": throughput["steps_per_second"],
    }
    if args.baseline_throughput:
        baseline = _read_json(Path(args.baseline_throughput)).get("throughput")
        if not isinstance(baseline, Mapping):
            raise QualificationError(
                "baseline artifact has no throughput record to compare against"
            )
        gates["throughput"].update(
            validate_throughput(
                throughput, baseline,
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
    parser.add_argument("--ratio-call-limit", type=int, default=DEFAULT_RATIO_CALL_LIMIT)
    parser.add_argument("--cell-timeout-seconds", type=float, default=1800.0)
    parser.add_argument("--throughput-agents", type=int, default=4096)
    parser.add_argument("--throughput-buffers", type=int, default=2)
    parser.add_argument("--throughput-threads", type=int, default=20)
    parser.add_argument("--throughput-horizon", type=int, default=64)
    parser.add_argument("--throughput-hidden", type=int, default=512)
    parser.add_argument("--throughput-layers", type=int, default=1)
    parser.add_argument(
        "--throughput-minibatch-size", type=int,
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
        "--baseline-throughput", type=Path,
        help="previous QUALIFICATION.json to compare steps/second against",
    )
    run.add_argument(
        "--max-regression-fraction", type=float,
        default=DEFAULT_MAX_REGRESSION_FRACTION,
    )

    cell = subparsers.add_parser("cell", help=argparse.SUPPRESS)
    add_common_arguments(cell)
    cell.add_argument("--kind", required=True, choices=CELL_KINDS)
    cell.add_argument("--cudagraphs", type=int, required=True)
    cell.add_argument("--output-json", required=True, type=Path)
    cell.add_argument("--output-npz", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.ratio_call_limit <= 0:
        raise QualificationError("ratio call limit must be positive")
    if args.throughput_warmup_rollouts < 0 or args.throughput_timed_rollouts <= 0:
        raise QualificationError("throughput rollout counts are invalid")
    validate_throughput_minibatch(
        args.throughput_agents, args.throughput_horizon,
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
