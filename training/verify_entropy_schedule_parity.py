#!/usr/bin/env python3
"""Independent oracle and artifact verifier for entropy schedule parity.

This module intentionally does not import PufferLib, PyTorch, NumPy, or the
native extension for its schedule and artifact checks.  It defines the proof
contract those implementations must satisfy and validates raw JSON-compatible
evidence emitted by the three execution cells.

The optional ``verify-torch`` command imports an explicitly selected PufferLib
source tree only after its source-level helper and telemetry contract has been
checked.  That path is an integration probe, not part of the oracle.
"""

from __future__ import annotations

import argparse
import ast
from fractions import Fraction
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import struct
import sys
from typing import Any, Iterable, Mapping, Sequence


CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"
SCHEMA_VERSION = 1
MAX_SAFE_INTEGER = (1 << 53) - 1
MAX_TRACE_UPDATES = 100_000
BACKENDS = ("torch", "native_eager", "native_graph")

SCHEDULE_KEYS = frozenset(
    {
        "contract",
        "base_coefficient",
        "anneal_enabled",
        "min_coefficient_ratio",
        "total_updates",
    }
)
TRAINING_KEYS = frozenset(
    {
        "total_timesteps",
        "total_agents",
        "horizon",
        "batch_size",
        "replay_ratio",
        "minibatch_size",
        "total_updates",
        "minibatches_per_update",
    }
)
IDENTITY_KEYS = frozenset(
    {
        "puffer_git_commit",
        "torch_source_sha256",
        "native_source_sha256",
        "patch_sha256",
    }
)
TRACE_KEYS = frozenset(
    {
        "schema_version",
        "backend",
        "contract",
        "schedule_sha256",
        "identity",
        "total_updates",
        "minibatches_per_update",
        "updates",
    }
)
UPDATE_KEYS = frozenset(
    {
        "update_index",
        "progress",
        "c_real",
        "c_applied",
        "entropy",
        "entropy_term",
        "minibatch_count",
        "graph_train_count_delta",
        "eager_train_count_delta",
    }
)
PAYLOAD_KEYS = frozenset(
    {
        "contract",
        "schedule",
        "training",
        "identity",
        "cells",
    }
)
ENVELOPE_KEYS = frozenset({"schema_version", "payload", "payload_sha256"})
POINT_KEYS = frozenset(
    {"contract", "update_index", "progress", "c_real", "c_applied"}
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_GIT_COMMIT_RE = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
_REQUIRED_TORCH_TELEMETRY = frozenset(
    {
        "entropy_schedule_contract",
        "entropy_applied_update_index",
        "entropy_c_real",
        "entropy_c_applied",
        "entropy_term",
    }
)


class VerificationError(ValueError):
    """Raised when an entropy parity contract or artifact is invalid."""


def _fail(message: str) -> None:
    raise VerificationError(message)


def _require_mapping(value: Any, label: str) -> dict[str, Any]:
    if type(value) is not dict:
        _fail(f"{label} must be a raw object, got {type(value).__name__}")
    return value


def _require_exact_keys(
    value: Mapping[str, Any], expected: frozenset[str], label: str
) -> None:
    actual = frozenset(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    extra = sorted(actual - expected)
    details = []
    if missing:
        details.append(f"missing={missing}")
    if extra:
        details.append(f"extra={extra}")
    _fail(f"{label} has a non-closed schema ({', '.join(details)})")


def _require_bool(value: Any, label: str) -> bool:
    if type(value) is not bool:
        _fail(f"{label} must be a boolean")
    return value


def _require_int(
    value: Any,
    label: str,
    *,
    minimum: int = 0,
    maximum: int = MAX_SAFE_INTEGER,
) -> int:
    if type(value) is not int:
        _fail(f"{label} must be an integer (booleans are not integers here)")
    if value < minimum or value > maximum:
        _fail(f"{label} must be in [{minimum}, {maximum}], got {value}")
    return value


def _require_finite_number(value: Any, label: str) -> float:
    if type(value) not in (int, float):
        _fail(f"{label} must be a finite JSON number")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        _fail(f"{label} is outside binary64 range")
    if not math.isfinite(result):
        _fail(f"{label} must be finite")
    return result


def _require_nonnegative_number(value: Any, label: str) -> float:
    result = _require_finite_number(value, label)
    if result < 0.0:
        _fail(f"{label} must be nonnegative")
    return result


def _binary32(value: float, label: str) -> float:
    """Round a finite Python binary64 value to IEEE-754 binary32."""

    try:
        encoded = struct.pack("!f", value)
    except (OverflowError, struct.error):
        _fail(f"{label} overflows IEEE binary32")
    result = struct.unpack("!f", encoded)[0]
    if not math.isfinite(result):
        _fail(f"{label} rounds to a non-finite IEEE binary32 value")
    return result


def _require_binary32(value: Any, label: str) -> float:
    result = _require_finite_number(value, label)
    rounded = _binary32(result, label)
    if result != rounded:
        _fail(f"{label} must be an exact IEEE binary32 value")
    return result


def _close_binary64(actual: float, expected: float) -> bool:
    if actual == expected:
        return True
    tolerance = 16.0 * max(math.ulp(actual), math.ulp(expected))
    return abs(actual - expected) <= tolerance


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical JSON representation used for evidence digests."""

    try:
        rendered = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        _fail(f"value is not canonical JSON: {exc}")
    return rendered.encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def total_updates(
    total_timesteps: int, total_agents: int, horizon: int
) -> int:
    """Return floor(total_timesteps / (total_agents * horizon)).

    Counts are constrained to JSON's exactly representable integer range so a
    Python verifier and native/PyTorch emitters cannot silently disagree after
    serialization.
    """

    timesteps = _require_int(
        total_timesteps, "total_timesteps", minimum=1
    )
    agents = _require_int(total_agents, "total_agents", minimum=1)
    rollout_horizon = _require_int(horizon, "horizon", minimum=1)
    batch_size = agents * rollout_horizon
    if batch_size > MAX_SAFE_INTEGER:
        _fail("total_agents * horizon exceeds the exact integer range")
    result = timesteps // batch_size
    if result <= 0:
        _fail(
            "training has zero complete updates: total_timesteps must be at "
            "least total_agents * horizon"
        )
    return result


def _exact_ratio(value: Any, label: str) -> Fraction:
    if type(value) is bool:
        _fail(f"{label} must be a nonnegative rational value")
    if type(value) is int:
        result = Fraction(value, 1)
    elif type(value) is float:
        if not math.isfinite(value):
            _fail(f"{label} must be finite")
        result = Fraction(repr(value))
    elif type(value) is str:
        if not value or value != value.strip():
            _fail(f"{label} must be a nonempty, unpadded rational string")
        try:
            result = Fraction(value)
        except (ValueError, ZeroDivisionError):
            _fail(f"{label} is not a valid rational string")
    else:
        _fail(f"{label} must be an integer, float, or exact rational string")
    if result < 0:
        _fail(f"{label} must be nonnegative")
    return result


def minibatches_per_update(
    replay_ratio: int | float | str,
    batch_size: int,
    minibatch_size: int,
) -> int:
    """Compute floor(replay_ratio_fp32 * batch_size / minibatch_size).

    The configuration ratio is narrowed once to finite IEEE binary32, matching
    the trainer configuration boundary. The remaining arithmetic is exact over
    that binary32 value so a near-integer boundary cannot depend on Python,
    C++, or CUDA intermediate precision.
    """

    ratio = _exact_ratio(replay_ratio, "replay_ratio")
    try:
        ratio_real = float(ratio)
    except OverflowError:
        _fail("replay_ratio is outside binary64 range")
    if not math.isfinite(ratio_real):
        _fail("replay_ratio is outside binary64 range")
    ratio_fp32 = _binary32(ratio_real, "replay_ratio")
    narrowed_ratio = Fraction.from_float(ratio_fp32)
    batch = _require_int(batch_size, "batch_size", minimum=1)
    minibatch = _require_int(minibatch_size, "minibatch_size", minimum=1)
    numerator = narrowed_ratio.numerator * batch
    denominator = narrowed_ratio.denominator * minibatch
    result = numerator // denominator
    if result <= 0:
        _fail(
            "training has zero minibatches per update; increase replay_ratio "
            "or batch_size, or decrease minibatch_size"
        )
    if result > MAX_SAFE_INTEGER:
        _fail("minibatches_per_update exceeds the exact integer range")
    return result


def validate_raw_schedule(raw: Any) -> dict[str, Any]:
    """Validate and normalize a closed raw schedule object."""

    schedule = _require_mapping(raw, "schedule")
    _require_exact_keys(schedule, SCHEDULE_KEYS, "schedule")
    if schedule["contract"] != CONTRACT:
        _fail(
            f"schedule.contract must be {CONTRACT!r}, "
            f"got {schedule['contract']!r}"
        )
    base = _require_nonnegative_number(
        schedule["base_coefficient"], "schedule.base_coefficient"
    )
    enabled = _require_bool(
        schedule["anneal_enabled"], "schedule.anneal_enabled"
    )
    ratio = _require_finite_number(
        schedule["min_coefficient_ratio"],
        "schedule.min_coefficient_ratio",
    )
    if ratio < 0.0 or ratio > 1.0:
        _fail("schedule.min_coefficient_ratio must be in [0, 1]")
    _binary32(ratio, "schedule.min_coefficient_ratio")
    updates = _require_int(
        schedule["total_updates"], "schedule.total_updates", minimum=1
    )
    floor = base * ratio
    if not math.isfinite(floor):
        _fail("base_coefficient * min_coefficient_ratio overflows binary64")
    _binary32(base, "schedule.base_coefficient")
    _binary32(floor, "schedule coefficient floor")
    return {
        "contract": CONTRACT,
        "base_coefficient": base,
        "anneal_enabled": enabled,
        "min_coefficient_ratio": ratio,
        "total_updates": updates,
    }


def entropy_schedule_point(raw_schedule: Any, update_index: int) -> dict[str, Any]:
    """Evaluate the canonical schedule at a zero-based applied update index.

    ``c_real`` is calculated with Python's binary64 floats. ``c_applied`` is
    then explicitly rounded to IEEE binary32.  Legal training updates are
    ``0 .. total_updates - 1``.  Asking for a later point is supported so the
    post-final floor can be verified independently.
    """

    schedule = validate_raw_schedule(raw_schedule)
    index = _require_int(
        update_index,
        "update_index",
        minimum=-MAX_SAFE_INTEGER,
    )
    updates = schedule["total_updates"]
    progress = min(max(float(index) / float(updates), 0.0), 1.0)
    base = schedule["base_coefficient"]
    if schedule["anneal_enabled"]:
        floor = base * schedule["min_coefficient_ratio"]
        coefficient = floor + 0.5 * (base - floor) * (
            1.0 + math.cos(math.pi * progress)
        )
    else:
        coefficient = base
    if not math.isfinite(coefficient):
        _fail("schedule evaluation produced a non-finite binary64 coefficient")
    applied = _binary32(coefficient, "schedule c_real")
    return {
        "contract": CONTRACT,
        "update_index": index,
        "progress": progress,
        "c_real": coefficient,
        "c_applied": applied,
    }


def validate_raw_training(raw: Any) -> dict[str, Any]:
    """Validate training counts and recompute both derived loop counts."""

    training = _require_mapping(raw, "training")
    _require_exact_keys(training, TRAINING_KEYS, "training")
    timesteps = _require_int(
        training["total_timesteps"], "training.total_timesteps", minimum=1
    )
    agents = _require_int(
        training["total_agents"], "training.total_agents", minimum=1
    )
    horizon = _require_int(training["horizon"], "training.horizon", minimum=1)
    batch = _require_int(
        training["batch_size"], "training.batch_size", minimum=1
    )
    expected_batch = agents * horizon
    if expected_batch > MAX_SAFE_INTEGER:
        _fail("training total_agents * horizon exceeds exact integer range")
    if batch != expected_batch:
        _fail(
            f"training.batch_size={batch} does not equal "
            f"total_agents*horizon={expected_batch}"
        )
    replay_ratio = training["replay_ratio"]
    if type(replay_ratio) is not str:
        _fail("training.replay_ratio must be an exact rational string")
    _exact_ratio(replay_ratio, "training.replay_ratio")
    minibatch_size = _require_int(
        training["minibatch_size"], "training.minibatch_size", minimum=1
    )
    declared_updates = _require_int(
        training["total_updates"], "training.total_updates", minimum=1
    )
    expected_updates = total_updates(timesteps, agents, horizon)
    if declared_updates != expected_updates:
        _fail(
            f"training.total_updates={declared_updates} does not equal "
            f"floor(total_timesteps/batch_size)={expected_updates}"
        )
    declared_minibatches = _require_int(
        training["minibatches_per_update"],
        "training.minibatches_per_update",
        minimum=1,
    )
    expected_minibatches = minibatches_per_update(
        replay_ratio, batch, minibatch_size
    )
    if declared_minibatches != expected_minibatches:
        _fail(
            f"training.minibatches_per_update={declared_minibatches} does not "
            f"equal floor(replay_ratio*batch_size/minibatch_size)="
            f"{expected_minibatches}"
        )
    return {
        "total_timesteps": timesteps,
        "total_agents": agents,
        "horizon": horizon,
        "batch_size": batch,
        "replay_ratio": replay_ratio,
        "minibatch_size": minibatch_size,
        "total_updates": declared_updates,
        "minibatches_per_update": declared_minibatches,
    }


def validate_identity(raw: Any) -> dict[str, str]:
    identity = _require_mapping(raw, "identity")
    _require_exact_keys(identity, IDENTITY_KEYS, "identity")
    commit = identity["puffer_git_commit"]
    if type(commit) is not str or _GIT_COMMIT_RE.fullmatch(commit) is None:
        _fail("identity.puffer_git_commit must be a lowercase 40/64-hex commit")
    result = {"puffer_git_commit": commit}
    for field in (
        "torch_source_sha256",
        "native_source_sha256",
        "patch_sha256",
    ):
        value = identity[field]
        if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
            _fail(f"identity.{field} must be a lowercase SHA-256 digest")
        result[field] = value
    return result


def _expected_counter_deltas(
    backend: str, minibatches: int
) -> tuple[int, int]:
    if backend == "native_graph":
        return minibatches, 0
    if backend == "native_eager":
        return 0, minibatches
    if backend == "torch":
        return 0, 0
    _fail(f"unknown backend {backend!r}")


def validate_update_trace(
    raw: Any,
    *,
    schedule: Any,
    training: Any,
    identity: Any,
    expected_backend: str,
) -> dict[str, Any]:
    """Validate one complete, raw per-update backend trace."""

    trace = _require_mapping(raw, f"{expected_backend} trace")
    _require_exact_keys(trace, TRACE_KEYS, f"{expected_backend} trace")
    normalized_schedule = validate_raw_schedule(schedule)
    normalized_training = validate_raw_training(training)
    normalized_identity = validate_identity(identity)
    if expected_backend not in BACKENDS:
        _fail(f"unsupported expected backend {expected_backend!r}")
    if trace["schema_version"] != SCHEMA_VERSION:
        _fail(f"{expected_backend} trace has an unsupported schema_version")
    if trace["backend"] != expected_backend:
        _fail(
            f"{expected_backend} trace backend is {trace['backend']!r}"
        )
    if trace["contract"] != CONTRACT:
        _fail(f"{expected_backend} trace has the wrong schedule contract")
    expected_schedule_digest = canonical_sha256(schedule)
    if trace["schedule_sha256"] != expected_schedule_digest:
        _fail(f"{expected_backend} trace has the wrong schedule_sha256")
    trace_identity = validate_identity(trace["identity"])
    if trace_identity != normalized_identity:
        _fail(f"{expected_backend} trace identity does not match its parent")
    total = _require_int(
        trace["total_updates"],
        f"{expected_backend} trace.total_updates",
        minimum=1,
    )
    if total != normalized_schedule["total_updates"]:
        _fail(f"{expected_backend} trace total_updates mismatches schedule")
    if total != normalized_training["total_updates"]:
        _fail(f"{expected_backend} trace total_updates mismatches training")
    if total > MAX_TRACE_UPDATES:
        _fail(
            f"{expected_backend} trace has {total} updates; verifier limit is "
            f"{MAX_TRACE_UPDATES}"
        )
    minibatches = _require_int(
        trace["minibatches_per_update"],
        f"{expected_backend} trace.minibatches_per_update",
        minimum=1,
    )
    if minibatches != normalized_training["minibatches_per_update"]:
        _fail(
            f"{expected_backend} trace minibatches_per_update mismatches "
            "training"
        )
    updates = trace["updates"]
    if type(updates) is not list:
        _fail(f"{expected_backend} trace.updates must be a raw array")
    if len(updates) != total:
        _fail(
            f"{expected_backend} trace has {len(updates)} records, expected "
            f"exactly {total}"
        )
    expected_graph, expected_eager = _expected_counter_deltas(
        expected_backend, minibatches
    )
    for expected_index, raw_update in enumerate(updates):
        label = f"{expected_backend} trace.updates[{expected_index}]"
        update = _require_mapping(raw_update, label)
        _require_exact_keys(update, UPDATE_KEYS, label)
        index = _require_int(update["update_index"], f"{label}.update_index")
        if index != expected_index:
            _fail(
                f"{label}.update_index={index}, expected contiguous "
                f"zero-based index {expected_index}"
            )
        expected = entropy_schedule_point(
            normalized_schedule, expected_index
        )
        progress = _require_finite_number(
            update["progress"], f"{label}.progress"
        )
        if not _close_binary64(progress, expected["progress"]):
            _fail(f"{label}.progress does not match update_index/total_updates")
        c_real = _require_nonnegative_number(
            update["c_real"], f"{label}.c_real"
        )
        if not _close_binary64(c_real, expected["c_real"]):
            _fail(f"{label}.c_real does not match the binary64 oracle")
        c_applied = _require_binary32(
            update["c_applied"], f"{label}.c_applied"
        )
        if c_applied != expected["c_applied"]:
            _fail(f"{label}.c_applied does not match IEEE binary32 oracle")
        entropy = _require_finite_number(
            update["entropy"], f"{label}.entropy"
        )
        if entropy <= 0.0:
            _fail(
                f"{label}.entropy must be strictly positive so loss sign and "
                "coefficient application are observable"
            )
        entropy_term = _require_finite_number(
            update["entropy_term"], f"{label}.entropy_term"
        )
        expected_term = -c_applied * entropy
        tolerance = max(1e-44, abs(expected_term) * 2e-6)
        if not math.isclose(
            entropy_term, expected_term, rel_tol=0.0, abs_tol=tolerance
        ):
            _fail(
                f"{label}.entropy_term does not equal "
                "-c_applied * entropy"
            )
        if c_applied > 0.0 and not entropy_term < 0.0:
            _fail(f"{label}.entropy_term has the wrong sign")
        count = _require_int(
            update["minibatch_count"],
            f"{label}.minibatch_count",
            minimum=1,
        )
        if count != minibatches:
            _fail(f"{label}.minibatch_count mismatches the loop contract")
        graph_delta = _require_int(
            update["graph_train_count_delta"],
            f"{label}.graph_train_count_delta",
        )
        eager_delta = _require_int(
            update["eager_train_count_delta"],
            f"{label}.eager_train_count_delta",
        )
        if graph_delta != expected_graph or eager_delta != expected_eager:
            _fail(
                f"{label} execution counters do not prove the "
                f"{expected_backend} cell"
            )
    return trace


def seal_cell_matrix(payload: Any) -> dict[str, Any]:
    """Create a detached, hash-sealed envelope for a raw cell payload."""

    payload_object = _require_mapping(payload, "payload")
    detached = json.loads(canonical_json_bytes(payload_object).decode("utf-8"))
    return {
        "schema_version": SCHEMA_VERSION,
        "payload": detached,
        "payload_sha256": canonical_sha256(detached),
    }


def validate_cell_matrix(raw: Any) -> dict[str, Any]:
    """Validate a closed three-cell proof artifact and all raw update rows."""

    envelope = _require_mapping(raw, "artifact")
    _require_exact_keys(envelope, ENVELOPE_KEYS, "artifact")
    if envelope["schema_version"] != SCHEMA_VERSION:
        _fail("artifact has an unsupported schema_version")
    payload = _require_mapping(envelope["payload"], "artifact.payload")
    digest = envelope["payload_sha256"]
    if type(digest) is not str or _SHA256_RE.fullmatch(digest) is None:
        _fail("artifact.payload_sha256 must be a lowercase SHA-256 digest")
    expected_digest = canonical_sha256(payload)
    if digest != expected_digest:
        _fail("artifact payload digest mismatch (artifact was tampered with)")
    _require_exact_keys(payload, PAYLOAD_KEYS, "artifact.payload")
    if payload["contract"] != CONTRACT:
        _fail("artifact payload has the wrong schedule contract")
    schedule = validate_raw_schedule(payload["schedule"])
    training = validate_raw_training(payload["training"])
    identity = validate_identity(payload["identity"])
    if schedule["total_updates"] != training["total_updates"]:
        _fail("schedule and training disagree about total_updates")
    cells = _require_mapping(payload["cells"], "artifact.payload.cells")
    _require_exact_keys(cells, frozenset(BACKENDS), "artifact.payload.cells")
    for backend in BACKENDS:
        validate_update_trace(
            cells[backend],
            schedule=payload["schedule"],
            training=payload["training"],
            identity=payload["identity"],
            expected_backend=backend,
        )
    return {
        "contract": CONTRACT,
        "payload_sha256": digest,
        "total_updates": schedule["total_updates"],
        "minibatches_per_update": training["minibatches_per_update"],
        "identity": identity,
        "validated_cells": list(BACKENDS),
    }


def _read_bounded_text(
    path: Path, *, label: str, limit: int = 4_000_000
) -> str:
    try:
        size = path.stat().st_size
    except OSError as exc:
        _fail(f"cannot stat {label} {path}: {exc}")
    if not path.is_file():
        _fail(f"{label} is not a regular file: {path}")
    if size > limit:
        _fail(f"{label} exceeds the {limit}-byte verifier limit")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        _fail(f"cannot read {label} {path}: {exc}")


def validate_torch_source_contract(puffer_root: str | Path) -> Path:
    """Require the named schedule helper and telemetry in a Puffer source tree."""

    root = Path(puffer_root).expanduser().resolve()
    source_path = (root / "pufferlib" / "torch_pufferl.py").resolve()
    try:
        source_path.relative_to(root)
    except ValueError:
        _fail("Torch source resolves outside the selected Puffer root")
    source = _read_bounded_text(source_path, label="Torch source")
    try:
        tree = ast.parse(source, filename=str(source_path))
    except SyntaxError as exc:
        _fail(f"Torch source does not parse: {exc}")

    contract_found = False
    helper_found = False
    string_literals: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "entropy_schedule_point":
                helper_found = True
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "ENTROPY_SCHEDULE_CONTRACT"
                    and isinstance(node.value, ast.Constant)
                    and node.value.value == CONTRACT
                ):
                    contract_found = True
        elif isinstance(node, ast.AnnAssign):
            if (
                isinstance(node.target, ast.Name)
                and node.target.id == "ENTROPY_SCHEDULE_CONTRACT"
                and isinstance(node.value, ast.Constant)
                and node.value.value == CONTRACT
            ):
                contract_found = True
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            string_literals.add(node.value)

    missing = []
    if not contract_found:
        missing.append(f"ENTROPY_SCHEDULE_CONTRACT={CONTRACT!r}")
    if not helper_found:
        missing.append("entropy_schedule_point helper")
    missing.extend(sorted(_REQUIRED_TORCH_TELEMETRY - string_literals))
    if missing:
        _fail(
            "Torch source lacks entropy parity integration: "
            + ", ".join(missing)
        )
    return source_path


def _validate_actual_point(
    raw_point: Any, expected: Mapping[str, Any], label: str
) -> dict[str, Any]:
    point = _require_mapping(raw_point, label)
    _require_exact_keys(point, POINT_KEYS, label)
    if point["contract"] != CONTRACT:
        _fail(f"{label}.contract is wrong")
    index = _require_int(point["update_index"], f"{label}.update_index")
    if index != expected["update_index"]:
        _fail(f"{label}.update_index is wrong")
    progress = _require_finite_number(point["progress"], f"{label}.progress")
    if not _close_binary64(progress, expected["progress"]):
        _fail(f"{label}.progress differs from the independent oracle")
    c_real = _require_nonnegative_number(point["c_real"], f"{label}.c_real")
    if not _close_binary64(c_real, expected["c_real"]):
        _fail(f"{label}.c_real differs from the independent oracle")
    c_applied = _require_binary32(
        point["c_applied"], f"{label}.c_applied"
    )
    if c_applied != expected["c_applied"]:
        _fail(f"{label}.c_applied differs from the independent oracle")
    return point


def execute_torch_source_schedule(
    puffer_root: str | Path,
    raw_schedule: Any,
    update_indices: Iterable[int],
) -> list[dict[str, Any]]:
    """Execute the required helper from an explicitly selected source tree.

    This fails before importing third-party code when the helper or telemetry
    contract is absent. Import/dependency errors are reported as clean
    ``VerificationError`` instances.
    """

    source_path = validate_torch_source_contract(puffer_root)
    root = source_path.parents[1]
    module_name = (
        "_entropy_schedule_probe_"
        + hashlib.sha256(str(source_path).encode("utf-8")).hexdigest()[:12]
    )
    spec = importlib.util.spec_from_file_location(module_name, source_path)
    if spec is None or spec.loader is None:
        _fail(f"cannot construct an import spec for {source_path}")
    module = importlib.util.module_from_spec(spec)
    old_path = list(sys.path)
    sys.path.insert(0, str(root))
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        _fail(
            "Torch source integration import failed "
            f"({type(exc).__name__}: {exc})"
        )
    finally:
        sys.path[:] = old_path
    helper = getattr(module, "entropy_schedule_point", None)
    if not callable(helper):
        _fail("Torch source entropy_schedule_point is not callable")

    schedule = validate_raw_schedule(raw_schedule)
    results = []
    for ordinal, raw_index in enumerate(update_indices):
        index = _require_int(
            raw_index, f"update_indices[{ordinal}]", minimum=0
        )
        expected = entropy_schedule_point(schedule, index)
        try:
            actual = helper(
                base_coefficient=schedule["base_coefficient"],
                anneal_enabled=schedule["anneal_enabled"],
                min_coefficient_ratio=schedule["min_coefficient_ratio"],
                update_index=index,
                total_updates=schedule["total_updates"],
            )
        except Exception as exc:
            _fail(
                f"Torch entropy_schedule_point failed at update {index} "
                f"({type(exc).__name__}: {exc})"
            )
        _validate_actual_point(
            actual, expected, f"Torch helper result[{ordinal}]"
        )
        results.append(actual)
    if not results:
        _fail("at least one update index is required for source execution")
    return results


def _load_json_artifact(path: Path) -> Any:
    text = _read_bounded_text(
        path, label="artifact", limit=128_000_000
    )
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        _fail(f"artifact is not valid JSON: {exc}")


def _parse_indices(value: str) -> list[int]:
    pieces = value.split(",")
    if not pieces or any(not piece for piece in pieces):
        raise argparse.ArgumentTypeError(
            "indices must be comma-separated nonnegative integers"
        )
    try:
        indices = [int(piece, 10) for piece in pieces]
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            "indices must be comma-separated nonnegative integers"
        ) from exc
    if any(index < 0 for index in indices):
        raise argparse.ArgumentTypeError("indices must be nonnegative")
    return indices


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    artifact_parser = subparsers.add_parser(
        "validate-artifact", help="validate a sealed three-cell JSON artifact"
    )
    artifact_parser.add_argument("artifact", type=Path)

    torch_parser = subparsers.add_parser(
        "verify-torch",
        help="execute the schedule helper from a selected Puffer source tree",
    )
    torch_parser.add_argument("--puffer-root", type=Path, required=True)
    torch_parser.add_argument("--base-coefficient", type=float, required=True)
    torch_parser.add_argument(
        "--min-coefficient-ratio", type=float, required=True
    )
    anneal_group = torch_parser.add_mutually_exclusive_group(required=True)
    anneal_group.add_argument(
        "--anneal-enabled", dest="anneal_enabled", action="store_true"
    )
    anneal_group.add_argument(
        "--anneal-disabled", dest="anneal_enabled", action="store_false"
    )
    torch_parser.add_argument("--total-updates", type=int, required=True)
    torch_parser.add_argument(
        "--indices",
        type=_parse_indices,
        help="comma-separated indices; defaults to 0,N-1,N",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate-artifact":
            result = validate_cell_matrix(_load_json_artifact(args.artifact))
        else:
            schedule = {
                "contract": CONTRACT,
                "base_coefficient": args.base_coefficient,
                "anneal_enabled": args.anneal_enabled,
                "min_coefficient_ratio": args.min_coefficient_ratio,
                "total_updates": args.total_updates,
            }
            indices = args.indices
            if indices is None:
                indices = [0, args.total_updates - 1, args.total_updates]
            result = execute_torch_source_schedule(
                args.puffer_root, schedule, indices
            )
    except (VerificationError, OSError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(canonical_json_bytes(result).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
