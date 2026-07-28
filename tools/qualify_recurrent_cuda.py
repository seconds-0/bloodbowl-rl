#!/usr/bin/env python3
"""Recurrent CUDA smoke test for the native Blood Bowl backend.

Every measurement runs in a fresh subprocess, because CUDA runtime
initialization order, graph capture, and recurrent state all have to start
clean. Re-run it whenever you rebuild; it overwrites its own output directory.

    tools/qualify_recurrent_cuda.py run --puffer-root <tree> --output <dir>
        --baseline-throughput <external baseline JSON>

Gates, and the bug each one caught:

  construction_state  recurrent state exactly zero in every primary and frozen
                      bank/buffer at construction.
  graph_parity        cudagraph-on and cudagraph-off first rollouts agree:
                      bitwise on discrete fields, within fp32 tolerance on
                      values/logprobs, behavior/tail decoder outputs, and
                      per-bank post-horizon bootstrap values; both modes close.
  heterogeneous_frozen_policy
                      graph-on/off H64/L1 primary versus H32/L2 frozen cells
                      authenticate two deterministic donor checkpoints, then
                      prove exact value, state, action, and logprob oracles.
  terminal_reset      state nonzero after a rollout, and the automatic terminal
                      reset matches an explicit all-bank zero control.
  ratio               real PPO calls at learning_rate=0 recompute ratio == 1
                      over every learner row, refresh and consume one tail
                      record per call, keep frozen advantages exactly zero,
                      never select a frozen row (even at prio_alpha=0), and
                      leave the weight bytes unchanged.
  throughput          steps/second on the target GPU, compared against one
                      bounded, digest-bound same-host/configuration artifact.

Every transition-executing cell must also report all 16 hard-integrity
counters at exactly zero. Qualification is fp32-only: BF16 rounds the stored
behavior log probability before recomputation, so the near-unity ratio contract
does not hold there. Every subprocess independently authenticates the pinned
Puffer HEAD and reverse-applicable rollout-transition patch, and the parent
rehashes/rechecks both. These artifacts are diagnostic, never checkpoint
ancestry. The current baseline gate binds bytes and same-host/configuration
fields but does not authenticate the artifact's producer; it is not release
authority.
"""

from __future__ import annotations

import argparse
import configparser
import copy
import fcntl
import functools
import hashlib
import io
import json
import math
import os
from pathlib import Path
import platform
import re
import secrets
import socket
import stat
import statistics
import subprocess
import sys
import tempfile
import time
import types
from typing import Any, Iterable, Mapping, NamedTuple

import numpy as np

try:
    from puffer_source_manifest import (
        native_extension_source_manifest_sha256,
        read_source_ledger,
    )
except ModuleNotFoundError:  # Imported as tools.qualify_recurrent_cuda in tests.
    from tools.puffer_source_manifest import (
        native_extension_source_manifest_sha256,
        read_source_ledger,
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


SCHEMA_VERSION = 10
ENVIRONMENT_CONFIG_SCHEMA = "bloodbowl-environment-config-v1"
ENVIRONMENT_CONFIG_KEY_COUNT = 51
ROLLOUT_TRANSITION_CONTRACT = "tail-bootstrap-v1"
MANDATORY_GATES = (
    "strict_environment_config",
    "construction_state",
    "graph_parity",
    "cuda_advantage_oracle",
    "heterogeneous_frozen_policy",
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
TAIL_FLOAT_SNAPSHOT_FIELDS = (
    "tail_rewards",
    "tail_terminals",
    "tail_values",
)
TAIL_EXACT_SNAPSHOT_FIELDS = (
    "tail_rewards",
    "tail_terminals",
    "tail_valid",
)
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
ARRAY_CELL_KINDS = frozenset(
    {"rollout", "terminal_auto", "terminal_control", "ratio"}
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
CELL_MAX_JSON_BYTES = 2 * 1024 * 1024
CELL_MAX_NPZ_BYTES = 256 * 1024 * 1024
FINAL_MAX_JSON_BYTES = 16 * 1024 * 1024
VERIFIER_MAX_SOURCE_BYTES = 2 * 1024 * 1024
QUALIFICATION_POLICY_MAX_BYTES = 64 * 1024 * 1024
BLOODBOWL_INPUT_SIZE = 2782
BLOODBOWL_ACTION_HEAD_SIZES = (30, 33, 391)
BLOODBOWL_ACTION_LOGITS = sum(BLOODBOWL_ACTION_HEAD_SIZES)
HETEROGENEOUS_PRIMARY_HIDDEN_SIZE = 64
HETEROGENEOUS_PRIMARY_NUM_LAYERS = 1
HETEROGENEOUS_FROZEN_HIDDEN_SIZE = 32
HETEROGENEOUS_FROZEN_NUM_LAYERS = 2
HETEROGENEOUS_TOTAL_AGENTS = 8
HETEROGENEOUS_NUM_BUFFERS = 2
HETEROGENEOUS_HORIZON = 8
HETEROGENEOUS_SLICE_SIZE = 2
HETEROGENEOUS_VALUE_COEFFICIENTS = {
    "zero_value": 0.0,
    "positive_value": 0.5,
}
HETEROGENEOUS_FROZEN_STATE_SEQUENCE = tuple(
    0.5 * (1.0 - 0.5 ** (step + 1))
    for step in range(HETEROGENEOUS_HORIZON)
)
HETEROGENEOUS_POSITIVE_VALUE_SEQUENCE = tuple(
    12.0 * state for state in HETEROGENEOUS_FROZEN_STATE_SEQUENCE
)
HETEROGENEOUS_ZERO_PREFIX = "heterogeneous_zero__"
REPO_ROOT = Path(__file__).resolve().parents[1]
PINNED_PUFFER_COMMIT = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"
ROLLOUT_TRANSITION_VERIFIER = (
    REPO_ROOT / "training" / "verify_rollout_transition_closure.py"
)
CUDA_ADVANTAGE_ORACLE_SCHEMA_VERSION = 1
CUDA_ADVANTAGE_ORACLE_CASES = (
    "terminal-tail-nan-h1",
    "terminal-tail-posinf-h1",
    "terminal-tail-neginf-h1",
    "positive-tail-clamp-h1",
    "negative-tail-clamp-h1",
    "all-zero-h1",
    "nonterminal-tail-h1",
    "vector-width-h4",
    "vector-multichunk-h8",
    "scalar-width-h5",
    "multirow-distinct-rho-c-h3",
    "vector-terminal-nan-h4",
    "vector-positive-tail-clamp-h4",
    "vector-negative-tail-clamp-h4",
)
INTEGRATED_ADVANTAGE_ORACLE_SCHEMA_VERSION = 1
INTEGRATED_ADVANTAGE_CONTRACT = "zero-lr-rollout-train-v1"
INTEGRATED_IMPORTANCE_CONTRACT = "first-train-pass-all-ones-v1"
STRICT_STAGE_SCHEMA_VERSION = 2
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
    "rollout_transition_contract",
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
ROLLOUT_TRANSITION_PATCH = (
    REPO_ROOT / "training/puffer_rollout_transition_closure.patch"
)
COMPILED_BACKEND_SOURCE_LEDGER = (
    REPO_ROOT / "training/puffer_compiled_backend_sources.txt"
)
BACKEND_SOURCE_FILES = read_source_ledger(
    COMPILED_BACKEND_SOURCE_LEDGER,
    expected_count=14,
)
QUALIFICATION_SURFACE_BINDINGS = (
    "qualification_recurrent_state",
    "qualification_snapshot",
    "qualification_policy_weights",
    "qualification_graph_execution",
    "qualification_consume_tail",
)
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
STRICT_INVALID_TEAM_DIAGNOSTIC = (
    "force_home_team must be integer -1 or 0..BB_TEAM_COUNT-1"
)


class QualificationError(RuntimeError):
    """A missing, malformed, drifted, or failed qualification predicate."""


class ValidatedArtifact(NamedTuple):
    """One bounded regular-file byte snapshot used for identity and parsing."""

    path: Path
    encoded: bytes
    sha256: str


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


def _load_rollout_transition_verifier() -> tuple[Any, dict[str, Any]]:
    """Compile and execute the exact bounded source bytes whose digest is returned."""

    path = ROLLOUT_TRANSITION_VERIFIER.resolve()
    encoded = _read_bounded_regular_bytes(
        path,
        maximum_bytes=VERIFIER_MAX_SOURCE_BYTES,
        label="rollout transition verifier",
    )
    module = types.ModuleType("_puffer_rollout_transition_verifier")
    module.__file__ = str(path)
    module.__package__ = ""
    try:
        code = compile(encoded, str(path), "exec", dont_inherit=True)
        exec(code, module.__dict__)
    except Exception as exc:
        raise QualificationError(
            f"cannot import rollout transition verifier {path}: {exc}"
        ) from exc
    for name in ("reference_advantages", "verification_cases", "verify_backend"):
        if not callable(getattr(module, name, None)):
            raise QualificationError(
                f"rollout transition verifier lacks callable {name}"
            )
    return module, {
        "path": str(path),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
    }


def execute_cuda_advantage_oracle(backend: Any) -> dict[str, Any]:
    """Execute scalar and vector CUDA recurrence fixtures on the loaded module."""

    try:
        import torch
    except (ImportError, OSError) as exc:
        raise QualificationError(
            f"CUDA advantage oracle cannot import Torch: {exc}"
        ) from exc
    if not torch.cuda.is_available():
        raise QualificationError(
            "CUDA advantage oracle requires a visible Torch CUDA device"
        )
    verifier, verifier_identity = _load_rollout_transition_verifier()
    try:
        summary = verifier.verify_backend(backend, torch, "cuda")
    except Exception as exc:
        raise QualificationError(f"CUDA advantage oracle failed: {exc}") from exc
    if not isinstance(summary, Mapping):
        raise QualificationError("CUDA advantage oracle summary is not a mapping")
    evidence = {
        "schema_version": CUDA_ADVANTAGE_ORACLE_SCHEMA_VERSION,
        **dict(summary),
        "verifier_path": verifier_identity["path"],
        "verifier_sha256": verifier_identity["sha256"],
    }
    return validate_cuda_advantage_oracle_evidence(
        evidence,
        rehash_files=True,
    )


def validate_cuda_advantage_oracle_evidence(
    evidence: Any,
    *,
    rehash_files: bool = False,
) -> dict[str, Any]:
    """Validate the closed, authenticated CUDA recurrence-oracle receipt."""

    expected_keys = {
        "schema_version",
        "contract",
        "device",
        "precision_bytes",
        "case_names",
        "case_count",
        "exact_once",
        "verifier_path",
        "verifier_sha256",
    }
    if not isinstance(evidence, Mapping):
        raise QualificationError("CUDA advantage oracle evidence is not a mapping")
    _require_exact_keys(evidence, expected_keys, "CUDA advantage oracle")
    if (
        _require_exact_json_int(
            evidence.get("schema_version"),
            "CUDA advantage oracle schema",
        )
        != CUDA_ADVANTAGE_ORACLE_SCHEMA_VERSION
    ):
        raise QualificationError("CUDA advantage oracle schema differs")
    if evidence.get("contract") != ROLLOUT_TRANSITION_CONTRACT:
        raise QualificationError("CUDA advantage oracle contract differs")
    if evidence.get("device") != "cuda":
        raise QualificationError("CUDA advantage oracle device differs")
    if (
        _require_exact_json_int(
            evidence.get("precision_bytes"),
            "CUDA advantage oracle precision",
            minimum=1,
        )
        != 4
    ):
        raise QualificationError("CUDA advantage oracle requires fp32")
    names = evidence.get("case_names")
    if (
        not isinstance(names, list)
        or any(type(name) is not str for name in names)
        or names != list(CUDA_ADVANTAGE_ORACLE_CASES)
    ):
        raise QualificationError("CUDA advantage oracle case set differs")
    if (
        _require_exact_json_int(
            evidence.get("case_count"),
            "CUDA advantage oracle case count",
            minimum=1,
        )
        != len(CUDA_ADVANTAGE_ORACLE_CASES)
    ):
        raise QualificationError("CUDA advantage oracle case count differs")
    if evidence.get("exact_once") is not True:
        raise QualificationError(
            "CUDA advantage oracle did not prove exact-once tail accounting"
        )
    verifier_path = _require_bounded_absolute_path(
        evidence.get("verifier_path"),
        "CUDA advantage oracle verifier path",
    )
    expected_path = ROLLOUT_TRANSITION_VERIFIER.resolve()
    if verifier_path != expected_path:
        raise QualificationError("CUDA advantage oracle verifier path differs")
    verifier_sha = _require_sha256(
        evidence.get("verifier_sha256"),
        "CUDA advantage oracle verifier digest",
    )
    if rehash_files:
        current_verifier = _read_bounded_regular_bytes(
            expected_path,
            maximum_bytes=VERIFIER_MAX_SOURCE_BYTES,
            label="CUDA advantage oracle verifier",
        )
        if hashlib.sha256(current_verifier).hexdigest() != verifier_sha:
            raise QualificationError("CUDA advantage oracle verifier bytes drifted")
    return dict(evidence)


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    """Write one bounded cell record through an exclusive random descriptor."""

    write_bounded_json_atomic(
        path,
        payload,
        maximum_bytes=CELL_MAX_JSON_BYTES,
    )


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
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_fd = os.open(path.parent, directory_flags)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
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


def _read_bounded_regular_bytes(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
) -> bytes:
    """Read one non-symlink regular-file snapshot through one checked descriptor."""

    if maximum_bytes <= 0:
        raise QualificationError(f"{label} byte limit must be positive")
    artifact = Path(path)
    try:
        before = artifact.lstat()
        if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
            raise QualificationError(
                f"{label} is not a regular non-symlink file: {artifact}"
            )
        if before.st_size > maximum_bytes:
            raise QualificationError(
                f"{label} exceeds {maximum_bytes} bytes: {artifact}"
            )
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(artifact, flags)
        opened_by_file = False
        try:
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                opened_by_file = True
                opened = os.fstat(handle.fileno())
                if (
                    not stat.S_ISREG(opened.st_mode)
                    or opened.st_dev != before.st_dev
                    or opened.st_ino != before.st_ino
                ):
                    raise QualificationError(
                        f"{label} changed type or identity while opening: "
                        f"{artifact}"
                    )
                if opened.st_size > maximum_bytes:
                    raise QualificationError(
                        f"{label} exceeds {maximum_bytes} bytes: {artifact}"
                    )
                encoded = handle.read(maximum_bytes + 1)
                after = os.fstat(handle.fileno())
                if (
                    after.st_dev != opened.st_dev
                    or after.st_ino != opened.st_ino
                    or after.st_size != opened.st_size
                    or after.st_mtime_ns != opened.st_mtime_ns
                    or len(encoded) != after.st_size
                ):
                    raise QualificationError(
                        f"{label} changed while being read: {artifact}"
                    )
        finally:
            if not opened_by_file:
                os.close(descriptor)
        if len(encoded) > maximum_bytes:
            raise QualificationError(
                f"{label} exceeds {maximum_bytes} bytes: {artifact}"
            )
        return encoded
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError(f"cannot read {label} {artifact}: {exc}") from exc


def _decode_json_object(encoded: bytes, path: Path) -> dict[str, Any]:
    try:
        value = json.loads(encoded.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise QualificationError(f"cannot read JSON artifact {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QualificationError(f"JSON artifact is not an object: {path}")
    return value


def _read_json_artifact(
    path: Path,
    *,
    maximum_bytes: int,
    label: str,
) -> tuple[dict[str, Any], ValidatedArtifact]:
    artifact_path = Path(path)
    encoded = _read_bounded_regular_bytes(
        artifact_path,
        maximum_bytes=maximum_bytes,
        label=label,
    )
    artifact = ValidatedArtifact(
        path=artifact_path,
        encoded=encoded,
        sha256=hashlib.sha256(encoded).hexdigest(),
    )
    return _decode_json_object(encoded, artifact_path), artifact


def _read_json(
    path: Path,
    *,
    maximum_bytes: int | None = None,
    require_regular: bool = False,
) -> dict[str, Any]:
    artifact = Path(path)
    try:
        if maximum_bytes is not None or require_regular:
            encoded = _read_bounded_regular_bytes(
                artifact,
                maximum_bytes=(
                    CELL_MAX_JSON_BYTES
                    if maximum_bytes is None
                    else maximum_bytes
                ),
                label="JSON artifact",
            )
        else:
            encoded = artifact.read_bytes()
    except QualificationError:
        raise
    except OSError as exc:
        raise QualificationError(f"cannot read JSON artifact {path}: {exc}") from exc
    return _decode_json_object(encoded, artifact)


def _read_npz(path: Path | ValidatedArtifact) -> dict[str, np.ndarray]:
    artifact = path.path if isinstance(path, ValidatedArtifact) else Path(path)
    try:
        encoded = (
            path.encoded
            if isinstance(path, ValidatedArtifact)
            else _read_bounded_regular_bytes(
                artifact,
                maximum_bytes=CELL_MAX_NPZ_BYTES,
                label="NPZ artifact",
            )
        )
        with np.load(io.BytesIO(encoded), allow_pickle=False) as payload:
            return {key: payload[key].copy() for key in payload.files}
    except QualificationError:
        raise
    except (OSError, ValueError) as exc:
        raise QualificationError(f"cannot read NPZ artifact {path}: {exc}") from exc


# ----------------------------------------- frozen-policy weight authentication


POLICY_WEIGHT_DESCRIPTOR_KEYS = (
    "bank",
    "role",
    "slice_size",
    "input_size",
    "hidden_size",
    "num_layers",
    "action_logits",
    "output_size",
    "parameter_count",
    "parameter_bytes",
    "decoder_offset",
    "decoder_shape",
    "value_row_offset",
    "weights",
)


def validate_policy_weight_descriptor(
    raw: Mapping[str, Any],
    *,
    expected_bank: int,
    expected_role: str,
    expected_hidden_size: int,
    expected_num_layers: int,
    expected_slice_size: int,
) -> dict[str, Any]:
    """Validate the exact bounded fp32 layout returned by the native surface."""

    if not isinstance(raw, Mapping):
        raise QualificationError("policy-weight descriptor is not a mapping")
    observed_keys = set(raw)
    expected_keys = set(POLICY_WEIGHT_DESCRIPTOR_KEYS)
    if observed_keys != expected_keys:
        raise QualificationError(
            "policy-weight descriptor keys differ: "
            f"missing={sorted(expected_keys - observed_keys)}, "
            f"extra={sorted(observed_keys - expected_keys)}"
        )
    bank = _int(expected_bank, "expected policy bank", minimum=0)
    hidden = _int(
        expected_hidden_size, "expected policy hidden size", minimum=1
    )
    layers = _int(
        expected_num_layers, "expected policy layer count", minimum=1
    )
    slice_size = _int(
        expected_slice_size, "expected policy slice size", minimum=1
    )
    if expected_role not in {"primary", "frozen"}:
        raise QualificationError("expected policy role is invalid")
    if _int(raw.get("bank"), "policy bank", minimum=0) != bank:
        raise QualificationError("policy-weight descriptor bank differs")
    if raw.get("role") != expected_role:
        raise QualificationError("policy-weight descriptor role differs")
    if _int(raw.get("slice_size"), "policy slice size", minimum=1) != slice_size:
        raise QualificationError("policy-weight descriptor slice size differs")
    if (
        _int(raw.get("input_size"), "policy input size", minimum=1)
        != BLOODBOWL_INPUT_SIZE
    ):
        raise QualificationError("policy-weight input ABI differs")
    if _int(raw.get("hidden_size"), "policy hidden size", minimum=1) != hidden:
        raise QualificationError("policy-weight hidden size differs")
    if _int(raw.get("num_layers"), "policy layer count", minimum=1) != layers:
        raise QualificationError("policy-weight layer count differs")
    if (
        _int(raw.get("action_logits"), "policy action-logit count", minimum=1)
        != BLOODBOWL_ACTION_LOGITS
    ):
        raise QualificationError("policy-weight action ABI differs")
    output_size = _int(raw.get("output_size"), "policy output size", minimum=1)
    if output_size != BLOODBOWL_ACTION_LOGITS + 1:
        raise QualificationError("policy-weight output ABI differs")

    parameter_bytes = _int(
        raw.get("parameter_bytes"), "policy parameter bytes", minimum=1
    )
    if parameter_bytes > QUALIFICATION_POLICY_MAX_BYTES:
        raise QualificationError(
            "policy parameter bytes exceed the qualification limit"
        )
    parameter_count = _int(
        raw.get("parameter_count"), "policy parameter count", minimum=1
    )
    decoder_offset = _int(
        raw.get("decoder_offset"), "policy decoder offset", minimum=0
    )
    value_row_offset = _int(
        raw.get("value_row_offset"), "policy value-row offset", minimum=0
    )
    expected_decoder_offset = BLOODBOWL_INPUT_SIZE * hidden
    expected_value_row_offset = (
        expected_decoder_offset + BLOODBOWL_ACTION_LOGITS * hidden
    )
    expected_parameter_count = (
        expected_decoder_offset
        + output_size * hidden
        + layers * 3 * hidden * hidden
    )
    if decoder_offset != expected_decoder_offset:
        raise QualificationError("policy decoder offset differs from architecture")
    if value_row_offset != expected_value_row_offset:
        raise QualificationError("policy value-row offset differs from architecture")
    if parameter_count != expected_parameter_count:
        raise QualificationError("policy parameter count differs from architecture")
    if parameter_bytes != 4 * parameter_count:
        raise QualificationError("policy parameter byte count is not fp32")
    decoder_shape = raw.get("decoder_shape")
    if (
        not isinstance(decoder_shape, list)
        or len(decoder_shape) != 2
        or any(type(value) is not int for value in decoder_shape)
        or decoder_shape != [output_size, hidden]
    ):
        raise QualificationError("policy decoder shape differs from architecture")
    weights = raw.get("weights")
    if type(weights) is not bytes:
        raise QualificationError("policy readback weights must be immutable bytes")
    if len(weights) != parameter_bytes:
        raise QualificationError("policy readback byte count differs")
    return dict(raw)


def _validated_frozen_weight_descriptor(
    descriptor: Mapping[str, Any],
) -> dict[str, Any]:
    return validate_policy_weight_descriptor(
        descriptor,
        expected_bank=1,
        expected_role="frozen",
        expected_hidden_size=HETEROGENEOUS_FROZEN_HIDDEN_SIZE,
        expected_num_layers=HETEROGENEOUS_FROZEN_NUM_LAYERS,
        expected_slice_size=HETEROGENEOUS_SLICE_SIZE,
    )


def build_heterogeneous_frozen_donor(
    descriptor: Mapping[str, Any],
    *,
    value_coefficient: float,
) -> bytes:
    """Build a flat H32/L2 checkpoint with an analytic action/value decoder."""

    layout = _validated_frozen_weight_descriptor(descriptor)
    coefficient = _num(value_coefficient, "donor value coefficient")
    if coefficient not in HETEROGENEOUS_VALUE_COEFFICIENTS.values():
        raise QualificationError("donor value coefficient is not a closed variant")
    values = np.zeros(layout["parameter_count"], dtype="<f4")
    hidden = layout["hidden_size"]
    row = 0
    for head_size in BLOODBOWL_ACTION_HEAD_SIZES:
        for local_action in range(head_size):
            start = layout["decoder_offset"] + row * hidden
            values[start : start + hidden] = np.float32(hidden * local_action)
            row += 1
    value_start = layout["value_row_offset"]
    values[value_start : value_start + hidden] = np.float32(coefficient)
    payload = values.tobytes(order="C")
    if len(payload) != layout["parameter_bytes"]:
        raise QualificationError("constructed donor byte count differs")
    return payload


def _write_binary_atomic(path: Path, payload: bytes) -> None:
    if type(payload) is not bytes or not payload:
        raise QualificationError("binary artifact payload must be nonempty bytes")
    if len(payload) > QUALIFICATION_POLICY_MAX_BYTES:
        raise QualificationError("binary artifact exceeds the qualification limit")
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=f".{destination.name}.tmp.",
        dir=destination.parent,
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _policy_weight_summary(descriptor: Mapping[str, Any]) -> dict[str, Any]:
    weights = descriptor["weights"]
    hidden = descriptor["hidden_size"]
    value_start = 4 * descriptor["value_row_offset"]
    value_stop = value_start + 4 * hidden
    return {
        key: copy.deepcopy(value)
        for key, value in descriptor.items()
        if key != "weights"
    } | {
        "weights_sha256": hashlib.sha256(weights).hexdigest(),
        "value_row_sha256": hashlib.sha256(
            weights[value_start:value_stop]
        ).hexdigest(),
    }


def install_authenticated_frozen_donor(
    backend: Any,
    pufferl: Any,
    directory: Path,
    descriptor: Mapping[str, Any],
    *,
    name: str,
    value_coefficient: float,
) -> dict[str, Any]:
    """Load through production, then require exact native whole-bank readback."""

    layout = _validated_frozen_weight_descriptor(descriptor)
    if not isinstance(name, str) or re.fullmatch(r"[a-z0-9-]{1,64}", name) is None:
        raise QualificationError("donor name is invalid")
    donor = build_heterogeneous_frozen_donor(
        layout, value_coefficient=value_coefficient
    )
    expected_sha256 = hashlib.sha256(donor).hexdigest()
    path = Path(directory).resolve() / f"frozen-{name}-{os.getpid()}.bin"
    try:
        _write_binary_atomic(path, donor)
        backend.load_frozen_bank(pufferl, 0, str(path))
        raw_readback = backend.qualification_policy_weights(
            pufferl, 1, QUALIFICATION_POLICY_MAX_BYTES
        )
        readback = _validated_frozen_weight_descriptor(raw_readback)
        for key in POLICY_WEIGHT_DESCRIPTOR_KEYS:
            if key == "weights":
                continue
            if readback[key] != layout[key]:
                raise QualificationError(
                    f"frozen policy readback layout differs after load: {key}"
                )
        if readback["weights"] != donor:
            raise QualificationError(
                "frozen policy readback bytes differ after production load"
            )
        readback_sha256 = hashlib.sha256(readback["weights"]).hexdigest()
        if readback_sha256 != expected_sha256:
            raise QualificationError("frozen policy readback digest differs")
    finally:
        path.unlink(missing_ok=True)
    return {
        "value_coefficient": float(value_coefficient),
        "expected_sha256": expected_sha256,
        "readback_sha256": readback_sha256,
        "changed_float_indices": (
            0 if value_coefficient == 0.0 else layout["hidden_size"]
        ),
        "readback_matches_donor": True,
    }


def consume_heterogeneous_tail_record(
    backend: Any,
    pufferl: Any,
    primary_before: Mapping[str, Any],
    frozen_before: Mapping[str, Any],
    *,
    num_buffers: int,
    arrays: dict[str, np.ndarray] | None = None,
) -> dict[str, Any]:
    """Consume one tail record at lr=0 without changing either policy bank."""

    buffers = _int(
        num_buffers, "heterogeneous tail-consumption buffers", minimum=1
    )
    primary = validate_policy_weight_descriptor(
        primary_before,
        expected_bank=0,
        expected_role="primary",
        expected_hidden_size=HETEROGENEOUS_PRIMARY_HIDDEN_SIZE,
        expected_num_layers=HETEROGENEOUS_PRIMARY_NUM_LAYERS,
        expected_slice_size=HETEROGENEOUS_SLICE_SIZE,
    )
    frozen = _validated_frozen_weight_descriptor(frozen_before)
    backend.train(pufferl)
    snapshot = decode_snapshot(backend.qualification_snapshot(pufferl))
    validate_tail_validity(
        snapshot.get("tail_valid"),
        num_buffers=buffers,
        expected=0,
        label="intervention post-train tail",
    )
    if arrays is not None:
        if not isinstance(arrays, dict):
            raise QualificationError(
                "integrated advantage destination must be a dictionary"
            )
        advantages_after_train = snapshot.get("advantages")
        if not isinstance(advantages_after_train, np.ndarray):
            raise QualificationError(
                "integrated post-train advantages are missing"
            )
        arrays["advantages_after_train"] = advantages_after_train
        arrays["tail_valid_after_train"] = snapshot["tail_valid"]
        arrays["selected_rows_after_train"] = snapshot["selected_rows"]
    primary_after = validate_policy_weight_descriptor(
        backend.qualification_policy_weights(
            pufferl, 0, QUALIFICATION_POLICY_MAX_BYTES
        ),
        expected_bank=0,
        expected_role="primary",
        expected_hidden_size=HETEROGENEOUS_PRIMARY_HIDDEN_SIZE,
        expected_num_layers=HETEROGENEOUS_PRIMARY_NUM_LAYERS,
        expected_slice_size=HETEROGENEOUS_SLICE_SIZE,
    )
    frozen_after = _validated_frozen_weight_descriptor(
        backend.qualification_policy_weights(
            pufferl, 1, QUALIFICATION_POLICY_MAX_BYTES
        )
    )
    if primary_after != primary:
        raise QualificationError(
            "zero-learning-rate intervention train changed primary weight bytes"
        )
    if frozen_after != frozen:
        raise QualificationError(
            "intervention train changed frozen policy weight bytes"
        )
    return {
        "tail_consumed": True,
        "primary_weights_unchanged": True,
        "frozen_weights_unchanged": True,
        "primary_sha256": hashlib.sha256(primary["weights"]).hexdigest(),
        "frozen_sha256": hashlib.sha256(frozen["weights"]).hexdigest(),
    }


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


def validate_heterogeneous_rollout_oracle(
    arrays: Mapping[str, np.ndarray],
    state_report: Mapping[str, Any],
    *,
    total_agents: int,
    num_buffers: int,
    horizon: int,
    value_coefficient: float,
    atol: float,
) -> dict[str, Any]:
    """Prove the H32/L2 frozen bank with independent analytic rollout oracles."""

    agents = _int(total_agents, "heterogeneous total agents", minimum=1)
    buffers = _int(num_buffers, "heterogeneous buffers", minimum=1)
    steps = _int(horizon, "heterogeneous horizon", minimum=1)
    tolerance = _num(atol, "heterogeneous oracle atol")
    coefficient = _num(value_coefficient, "heterogeneous value coefficient")
    if (
        agents != HETEROGENEOUS_TOTAL_AGENTS
        or buffers != HETEROGENEOUS_NUM_BUFFERS
        or steps != HETEROGENEOUS_HORIZON
        or coefficient not in HETEROGENEOUS_VALUE_COEFFICIENTS.values()
        or tolerance < 0
    ):
        raise QualificationError("heterogeneous oracle role is not the closed cell")

    primary_rows, frozen_rows = derive_row_partition(
        state_report, total_agents=agents
    )
    expected_primary = {0, 1, 4, 5}
    expected_frozen = {2, 3, 6, 7}
    if primary_rows != expected_primary or frozen_rows != expected_frozen:
        raise QualificationError("heterogeneous row partition differs")

    required_shapes = {
        "actions": (steps, agents, len(BLOODBOWL_ACTION_HEAD_SIZES)),
        "action_mask": (steps, agents, BLOODBOWL_ACTION_LOGITS),
        "values": (steps, agents),
        "logprobs": (steps, agents),
        "tail_terminals": (agents,),
        "tail_values": (agents,),
    }
    for key, shape in required_shapes.items():
        value = arrays.get(key)
        if (
            not isinstance(value, np.ndarray)
            or value.dtype != np.dtype(np.float32)
            or value.shape != shape
            or not np.isfinite(value).all()
        ):
            raise QualificationError(
                f"heterogeneous oracle field {key} is not finite float32 {shape}"
            )
    validate_tail_validity(
        arrays.get("tail_valid"),
        num_buffers=buffers,
        expected=1,
        label="heterogeneous intervention tail",
    )

    expected_behavior = np.asarray(
        (
            (0.0,) * HETEROGENEOUS_HORIZON
            if coefficient == 0.0
            else HETEROGENEOUS_POSITIVE_VALUE_SEQUENCE
        ),
        dtype=np.float32,
    )
    expected_tail = np.float32(0.0 if coefficient == 0.0 else 3.0)
    frozen_index = sorted(frozen_rows)
    observed_values = arrays["values"][:, frozen_index]
    tiled_values = np.repeat(
        expected_behavior[:, np.newaxis], len(frozen_index), axis=1
    )
    if not np.array_equal(observed_values, tiled_values):
        raise QualificationError(
            "frozen behavior values differ from the analytic H8 oracle"
        )
    if not np.array_equal(
        arrays["tail_terminals"][frozen_index],
        np.zeros(len(frozen_index), np.float32),
    ):
        raise QualificationError(
            "heterogeneous frozen tail sentinel must be nonterminal"
        )
    if not np.array_equal(
        arrays["tail_values"][frozen_index],
        np.full(len(frozen_index), expected_tail, np.float32),
    ):
        raise QualificationError(
            "frozen tail values differ from the fresh-zero analytic oracle"
        )

    max_abs_logprob = 0.0
    offsets: list[int] = []
    offset = 0
    for head_size in BLOODBOWL_ACTION_HEAD_SIZES:
        offsets.append(offset)
        offset += head_size
    for row in frozen_index:
        for step in range(steps):
            logprob = float(arrays["logprobs"][step, row])
            max_abs_logprob = max(max_abs_logprob, abs(logprob))
            if abs(logprob) > tolerance:
                raise QualificationError(
                    "heterogeneous frozen log probability is not zero"
                )
            for head, (head_size, head_offset) in enumerate(
                zip(BLOODBOWL_ACTION_HEAD_SIZES, offsets)
            ):
                mask = arrays["action_mask"][
                    step, row, head_offset : head_offset + head_size
                ]
                if not np.isin(mask, np.array([0.0, 1.0], np.float32)).all():
                    raise QualificationError(
                        "heterogeneous frozen conditional mask is not binary"
                    )
                enabled = np.flatnonzero(mask == np.float32(1.0))
                if enabled.size == 0:
                    raise QualificationError(
                        "heterogeneous frozen action head has no legal action"
                    )
                raw_action = float(arrays["actions"][step, row, head])
                if not raw_action.is_integer():
                    raise QualificationError(
                        "heterogeneous frozen action is not an integer"
                    )
                action = int(raw_action)
                if action < 0 or action >= head_size or mask[action] != 1.0:
                    raise QualificationError(
                        "heterogeneous frozen action is mask-disabled"
                    )
                if action != int(enabled[-1]):
                    raise QualificationError(
                        "heterogeneous frozen action is not maximum legal"
                    )

    per_buffer = agents // buffers
    for buffer in range(buffers):
        start = buffer * per_buffer + HETEROGENEOUS_SLICE_SIZE
        stop = start + HETEROGENEOUS_SLICE_SIZE
        for prefix, expected_value in (
            ("decoder", expected_behavior[-1]),
            ("tail_decoder", expected_tail),
        ):
            key = f"{prefix}_bank_1_buffer_{buffer}"
            decoder = arrays.get(key)
            expected_shape = (
                HETEROGENEOUS_SLICE_SIZE,
                BLOODBOWL_ACTION_LOGITS + 1,
            )
            if (
                not isinstance(decoder, np.ndarray)
                or decoder.dtype != np.dtype(np.float32)
                or decoder.shape != expected_shape
                or not np.isfinite(decoder).all()
            ):
                raise QualificationError(
                    f"heterogeneous {prefix} evidence is malformed"
                )
            if not np.array_equal(
                decoder[:, -1],
                np.full(HETEROGENEOUS_SLICE_SIZE, expected_value, np.float32),
            ):
                raise QualificationError(
                    f"heterogeneous {prefix} value oracle differs"
                )
            actual = (
                arrays["values"][-1, start:stop]
                if prefix == "decoder"
                else arrays["tail_values"][start:stop]
            )
            if not np.array_equal(actual, decoder[:, -1]):
                raise QualificationError(
                    f"heterogeneous {prefix} diagnostic differs from rollout data"
                )

    entries = _state_entries(state_report, banks=2, buffers=buffers)
    frozen_entries = [entry for entry in entries if entry["bank"] == 1]
    if len(frozen_entries) != buffers:
        raise QualificationError("heterogeneous frozen state coverage differs")
    expected_live_state = HETEROGENEOUS_FROZEN_STATE_SEQUENCE[-1]
    for entry in frozen_entries:
        if (
            entry["shape"]
            != [
                HETEROGENEOUS_FROZEN_NUM_LAYERS,
                HETEROGENEOUS_SLICE_SIZE,
                HETEROGENEOUS_FROZEN_HIDDEN_SIZE,
            ]
            or entry["active_rows"] != HETEROGENEOUS_SLICE_SIZE
            or _int(
                entry.get("active_nonzero"),
                "frozen state active_nonzero",
                minimum=0,
            )
            != _int(
                entry.get("active_elements"),
                "frozen state active_elements",
                minimum=1,
            )
            or _int(
                entry.get("active_nonfinite"),
                "frozen state active_nonfinite",
                minimum=0,
            )
            != 0
            or _num(entry.get("active_min"), "frozen state active_min")
            != expected_live_state
            or _num(entry.get("active_max"), "frozen state active_max")
            != expected_live_state
            or _num(
                entry.get("active_max_abs"), "frozen state active_max_abs"
            )
            != expected_live_state
        ):
            raise QualificationError(
                "heterogeneous frozen live state differs from the exact H8 oracle"
            )

    return {
        "frozen_rows": frozen_index,
        "frozen_behavior_values": [
            float(value) for value in expected_behavior
        ],
        "frozen_tail_value": float(expected_tail),
        "frozen_live_state": expected_live_state,
        "all_frozen_actions_max_legal": True,
        "max_abs_frozen_logprob": max_abs_logprob,
        "ordinary_decoder_preserved": True,
        "tail_uses_fresh_zero_state": True,
    }


def _architecture_descriptor(
    raw: Mapping[str, Any],
    *,
    expected_bank: int,
    expected_role: str,
    expected_hidden_size: int,
    expected_num_layers: int,
    expected_slice_size: int,
    include_digests: bool,
) -> tuple[dict[str, Any], dict[str, Any]]:
    architecture_keys = set(POLICY_WEIGHT_DESCRIPTOR_KEYS) - {"weights"}
    expected_keys = set(architecture_keys)
    if include_digests:
        expected_keys.update({"weights_sha256", "value_row_sha256"})
    if not isinstance(raw, Mapping) or set(raw) != expected_keys:
        raise QualificationError(
            f"{expected_role} policy architecture record keys differ"
        )
    parameter_bytes = _int(
        raw.get("parameter_bytes"),
        f"{expected_role} policy architecture bytes",
        minimum=1,
    )
    if parameter_bytes > QUALIFICATION_POLICY_MAX_BYTES:
        raise QualificationError(
            f"{expected_role} policy architecture exceeds the byte limit"
        )
    synthetic = {
        key: copy.deepcopy(raw[key])
        for key in architecture_keys
    }
    synthetic["weights"] = bytes(parameter_bytes)
    descriptor = validate_policy_weight_descriptor(
        synthetic,
        expected_bank=expected_bank,
        expected_role=expected_role,
        expected_hidden_size=expected_hidden_size,
        expected_num_layers=expected_num_layers,
        expected_slice_size=expected_slice_size,
    )
    if include_digests:
        _require_sha256(
            raw.get("weights_sha256"),
            f"{expected_role} policy weight digest",
        )
        _require_sha256(
            raw.get("value_row_sha256"),
            f"{expected_role} policy value-row digest",
        )
    return descriptor, dict(raw)


def _heterogeneous_namespace(
    arrays: Mapping[str, np.ndarray],
    prefix: str,
) -> dict[str, np.ndarray]:
    selected = {
        key[len(prefix) :]: value
        for key, value in arrays.items()
        if key.startswith(prefix)
    }
    if not selected:
        raise QualificationError(
            f"heterogeneous array namespace is missing: {prefix}"
        )
    return selected


def validate_heterogeneous_policy_evidence(
    record: Mapping[str, Any],
    arrays: Mapping[str, np.ndarray],
    *,
    atol: float,
) -> dict[str, Any]:
    """Parent-side reconstruction of donor identity and analytic GPU evidence."""

    tolerance = _num(atol, "heterogeneous evidence atol")
    if tolerance < 0:
        raise QualificationError("heterogeneous evidence tolerance is negative")
    config = record.get("config")
    if not isinstance(config, Mapping):
        raise QualificationError("heterogeneous cell config is missing")
    policy_config = config.get("policy")
    vec_config = config.get("vec")
    train_config = config.get("train")
    if (
        not isinstance(policy_config, Mapping)
        or not isinstance(vec_config, Mapping)
        or not isinstance(train_config, Mapping)
    ):
        raise QualificationError(
            "heterogeneous cell architecture/configuration differs"
        )
    typed_config = {
        "primary hidden size": _int(
            policy_config.get("hidden_size"), "primary hidden size", minimum=1
        ),
        "primary layers": _int(
            policy_config.get("num_layers"), "primary layers", minimum=1
        ),
        "total agents": _int(
            vec_config.get("total_agents"), "total agents", minimum=1
        ),
        "buffers": _int(vec_config.get("num_buffers"), "buffers", minimum=1),
        "frozen banks": _int(
            vec_config.get("num_frozen_banks"), "frozen banks", minimum=0
        ),
        "frozen hidden size": _int(
            vec_config.get("frozen_bank_hidden_size"),
            "frozen hidden size",
            minimum=1,
        ),
        "frozen layers": _int(
            vec_config.get("frozen_bank_num_layers"),
            "frozen layers",
            minimum=1,
        ),
        "horizon": _int(
            train_config.get("horizon"), "heterogeneous horizon", minimum=1
        ),
        "replay ratio": _int(
            train_config.get("replay_ratio"),
            "heterogeneous replay ratio",
            minimum=1,
        ),
        "minibatch size": _int(
            train_config.get("minibatch_size"),
            "heterogeneous minibatch size",
            minimum=1,
        ),
    }
    expected_config = {
        "primary hidden size": HETEROGENEOUS_PRIMARY_HIDDEN_SIZE,
        "primary layers": HETEROGENEOUS_PRIMARY_NUM_LAYERS,
        "total agents": HETEROGENEOUS_TOTAL_AGENTS,
        "buffers": HETEROGENEOUS_NUM_BUFFERS,
        "frozen banks": 1,
        "frozen hidden size": HETEROGENEOUS_FROZEN_HIDDEN_SIZE,
        "frozen layers": HETEROGENEOUS_FROZEN_NUM_LAYERS,
        "horizon": HETEROGENEOUS_HORIZON,
        "replay ratio": 1,
        "minibatch size": HETEROGENEOUS_TOTAL_AGENTS * HETEROGENEOUS_HORIZON,
    }
    frozen_pct = _num(
        vec_config.get("frozen_bank_pct"), "frozen bank percentage"
    )
    learning_rate = _num(
        train_config.get("learning_rate"),
        "heterogeneous intervention learning rate",
    )
    if (
        typed_config != expected_config
        or frozen_pct != 0.5
        or learning_rate != 0.0
    ):
        raise QualificationError(
            "heterogeneous cell architecture/configuration differs"
        )

    evidence = record.get("heterogeneous_policy")
    if not isinstance(evidence, Mapping) or set(evidence) != {
        "primary_architecture",
        "frozen_architecture",
        "donors",
    }:
        raise QualificationError("heterogeneous policy evidence is malformed")
    primary, primary_record = _architecture_descriptor(
        evidence["primary_architecture"],
        expected_bank=0,
        expected_role="primary",
        expected_hidden_size=HETEROGENEOUS_PRIMARY_HIDDEN_SIZE,
        expected_num_layers=HETEROGENEOUS_PRIMARY_NUM_LAYERS,
        expected_slice_size=HETEROGENEOUS_SLICE_SIZE,
        include_digests=True,
    )
    frozen, frozen_record = _architecture_descriptor(
        evidence["frozen_architecture"],
        expected_bank=1,
        expected_role="frozen",
        expected_hidden_size=HETEROGENEOUS_FROZEN_HIDDEN_SIZE,
        expected_num_layers=HETEROGENEOUS_FROZEN_NUM_LAYERS,
        expected_slice_size=HETEROGENEOUS_SLICE_SIZE,
        include_digests=False,
    )
    if (
        primary["hidden_size"] == frozen["hidden_size"]
        or primary["num_layers"] == frozen["num_layers"]
        or primary["parameter_bytes"] == frozen["parameter_bytes"]
    ):
        raise QualificationError("primary/frozen policy architectures do not differ")

    donor_records = evidence.get("donors")
    if not isinstance(donor_records, Mapping) or set(donor_records) != set(
        HETEROGENEOUS_VALUE_COEFFICIENTS
    ):
        raise QualificationError("heterogeneous donor record set differs")
    reconstructed: dict[str, bytes] = {}
    validated_donors: dict[str, dict[str, Any]] = {}
    donor_keys = {
        "value_coefficient",
        "expected_sha256",
        "readback_sha256",
        "changed_float_indices",
        "readback_matches_donor",
    }
    for name, coefficient in HETEROGENEOUS_VALUE_COEFFICIENTS.items():
        donor_record = donor_records.get(name)
        if not isinstance(donor_record, Mapping) or set(donor_record) != donor_keys:
            raise QualificationError(f"heterogeneous donor record is malformed: {name}")
        if _num(
            donor_record.get("value_coefficient"),
            f"{name} donor coefficient",
        ) != coefficient:
            raise QualificationError(f"heterogeneous donor coefficient differs: {name}")
        donor = build_heterogeneous_frozen_donor(
            frozen, value_coefficient=coefficient
        )
        reconstructed[name] = donor
        expected_sha256 = hashlib.sha256(donor).hexdigest()
        if (
            _require_sha256(
                donor_record.get("expected_sha256"),
                f"{name} expected donor digest",
            )
            != expected_sha256
            or _require_sha256(
                donor_record.get("readback_sha256"),
                f"{name} readback donor digest",
            )
            != expected_sha256
            or donor_record.get("readback_matches_donor") is not True
        ):
            raise QualificationError(
                f"heterogeneous donor/readback digest differs: {name}"
            )
        changed = _int(
            donor_record.get("changed_float_indices"),
            f"{name} changed-float count",
            minimum=0,
        )
        expected_changed = (
            0 if coefficient == 0.0 else HETEROGENEOUS_FROZEN_HIDDEN_SIZE
        )
        if changed != expected_changed:
            raise QualificationError(
                f"heterogeneous donor value-row mutation count differs: {name}"
            )
        validated_donors[name] = dict(donor_record)

    zero_values = np.frombuffer(reconstructed["zero_value"], dtype="<f4")
    positive_values = np.frombuffer(reconstructed["positive_value"], dtype="<f4")
    changed_indices = np.flatnonzero(zero_values != positive_values)
    expected_indices = np.arange(
        frozen["value_row_offset"],
        frozen["value_row_offset"] + frozen["hidden_size"],
    )
    if not np.array_equal(changed_indices, expected_indices):
        raise QualificationError(
            "heterogeneous donors differ outside the exact value row"
        )
    value_start = 4 * frozen["value_row_offset"]
    value_stop = value_start + 4 * frozen["hidden_size"]
    donor_value_row_digests = {
        hashlib.sha256(payload[value_start:value_stop]).hexdigest()
        for payload in reconstructed.values()
    }
    if primary_record["value_row_sha256"] in donor_value_row_digests:
        raise QualificationError(
            "primary value row is not independent from frozen donors"
        )
    donor_digests = {
        hashlib.sha256(payload).hexdigest() for payload in reconstructed.values()
    }
    if primary_record["weights_sha256"] in donor_digests:
        raise QualificationError(
            "primary policy bytes are not independent from frozen donors"
        )
    consumption = record.get("heterogeneous_zero_tail_consumption")
    consumption_keys = {
        "tail_consumed",
        "primary_weights_unchanged",
        "frozen_weights_unchanged",
        "primary_sha256",
        "frozen_sha256",
    }
    if (
        not isinstance(consumption, Mapping)
        or set(consumption) != consumption_keys
        or consumption.get("tail_consumed") is not True
        or consumption.get("primary_weights_unchanged") is not True
        or consumption.get("frozen_weights_unchanged") is not True
        or _require_sha256(
            consumption.get("primary_sha256"),
            "intervention primary weight digest",
        )
        != primary_record["weights_sha256"]
        or _require_sha256(
            consumption.get("frozen_sha256"),
            "intervention frozen weight digest",
        )
        != donor_records["zero_value"]["expected_sha256"]
    ):
        raise QualificationError(
            "heterogeneous zero-tail consumption evidence differs"
        )

    zero_arrays = _heterogeneous_namespace(
        arrays, HETEROGENEOUS_ZERO_PREFIX
    )
    zero_oracle = validate_heterogeneous_rollout_oracle(
        zero_arrays,
        record.get("heterogeneous_zero_state", {}),
        total_agents=HETEROGENEOUS_TOTAL_AGENTS,
        num_buffers=HETEROGENEOUS_NUM_BUFFERS,
        horizon=HETEROGENEOUS_HORIZON,
        value_coefficient=HETEROGENEOUS_VALUE_COEFFICIENTS["zero_value"],
        atol=tolerance,
    )
    positive_oracle = validate_heterogeneous_rollout_oracle(
        arrays,
        record.get("heterogeneous_positive_state", {}),
        total_agents=HETEROGENEOUS_TOTAL_AGENTS,
        num_buffers=HETEROGENEOUS_NUM_BUFFERS,
        horizon=HETEROGENEOUS_HORIZON,
        value_coefficient=HETEROGENEOUS_VALUE_COEFFICIENTS["positive_value"],
        atol=tolerance,
    )
    if record.get("heterogeneous_zero_oracle") != zero_oracle:
        raise QualificationError("worker zero-value oracle summary differs")
    if record.get("heterogeneous_positive_oracle") != positive_oracle:
        raise QualificationError("worker positive-value oracle summary differs")

    return {
        "readback_matches_donor": True,
        "primary_frozen_architectures_differ": True,
        "primary_architecture": primary_record,
        "frozen_architecture": frozen_record,
        "donors": validated_donors,
        "zero_value": zero_oracle,
        "positive_value": positive_oracle,
    }


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


def compare_tail_decoder_outputs(
    left: Mapping[str, np.ndarray],
    right: Mapping[str, np.ndarray],
    *,
    atol: float,
) -> dict[str, float]:
    keys = {key for key in left if key.startswith("tail_decoder_bank_")}
    if not keys or keys != {
        key for key in right if key.startswith("tail_decoder_bank_")
    }:
        raise QualificationError("tail decoder bank/buffer coverage mismatch")
    return {
        key: _max_abs_error(key, left[key], right[key], atol)
        for key in sorted(keys)
    }


def validate_tail_snapshot(
    snapshot: Mapping[str, np.ndarray],
    *,
    total_agents: int,
    num_buffers: int,
) -> dict[str, Any]:
    """Require one finite post-horizon tail record from every rollout worker."""

    agents = _int(total_agents, "tail snapshot total agents", minimum=1)
    buffers = _int(num_buffers, "tail snapshot buffers", minimum=1)
    if agents % buffers:
        raise QualificationError("tail snapshot agents are not buffer-divisible")
    missing = [
        key
        for key in (*TAIL_FLOAT_SNAPSHOT_FIELDS, "tail_valid")
        if key not in snapshot
    ]
    if missing:
        raise QualificationError(f"tail snapshot fields are missing: {missing}")
    for key in TAIL_FLOAT_SNAPSHOT_FIELDS:
        value = snapshot[key]
        if not isinstance(value, np.ndarray):
            raise QualificationError(f"tail snapshot field {key} is not an ndarray")
        if value.dtype != np.dtype(np.float32):
            raise QualificationError(f"tail snapshot field {key} is not float32")
        if value.shape != (agents,):
            raise QualificationError(
                f"tail snapshot field {key} shape {value.shape} != {(agents,)}"
            )
        if not np.isfinite(value).all():
            raise QualificationError(
                f"tail snapshot field {key} contains non-finite values"
            )
    terminals = snapshot["tail_terminals"]
    if not np.isin(terminals, np.array([0.0, 1.0], np.float32)).all():
        raise QualificationError("tail terminal flags are not binary")
    terminal_values = snapshot["tail_values"][terminals == 1.0]
    if not np.array_equal(terminal_values, np.zeros_like(terminal_values)):
        raise QualificationError("terminal tail values are not exactly zero")
    valid = validate_tail_validity(
        snapshot["tail_valid"],
        num_buffers=buffers,
        expected=1,
        label="tail callback",
    )
    return {
        "total_agents": agents,
        "num_buffers": buffers,
        "valid_buffers": int(valid.sum()),
        "terminal_rows": int(np.count_nonzero(terminals)),
    }


def validate_tail_validity(
    valid: Any,
    *,
    num_buffers: int,
    expected: int,
    label: str,
) -> np.ndarray:
    buffers = _int(num_buffers, f"{label} buffers", minimum=1)
    expected_value = _int(expected, f"{label} expected validity", minimum=0)
    if expected_value not in {0, 1}:
        raise QualificationError(f"{label} expected validity must be zero or one")
    if not isinstance(valid, np.ndarray) or valid.dtype != np.dtype(np.int32):
        raise QualificationError(f"{label} validity flags are not int32")
    if valid.shape != (buffers,):
        raise QualificationError(
            f"{label} validity shape {valid.shape} != {(buffers,)}"
        )
    expected_array = np.full(buffers, expected_value, dtype=np.int32)
    if not np.array_equal(valid, expected_array):
        raise QualificationError(
            f"{label} validity flags are not all {expected_value}"
        )
    return valid


def consume_qualification_tail(
    backend: Any,
    pufferl: Any,
    *,
    num_buffers: int,
    label: str,
) -> dict[str, list[int]]:
    """Explicitly discard one qualification-only tail without allowing overwrite."""

    buffers = _int(num_buffers, f"{label} tail-discard buffers", minimum=1)
    surface = getattr(backend, "qualification_consume_tail", None)
    if not callable(surface):
        raise QualificationError(
            f"{label} qualification tail-consumption surface is missing"
        )
    try:
        evidence = surface(pufferl)
    except Exception as exc:
        raise QualificationError(
            f"{label} qualification tail consumption failed: {exc}"
        ) from exc
    if not isinstance(evidence, Mapping):
        raise QualificationError(
            f"{label} qualification tail-consumption evidence is not a mapping"
        )
    _require_exact_keys(
        evidence,
        ("before", "after"),
        f"{label} qualification tail-consumption evidence",
    )
    expected = {
        "before": [1] * buffers,
        "after": [0] * buffers,
    }
    result: dict[str, list[int]] = {}
    for key, wanted in expected.items():
        value = evidence.get(key)
        if (
            not isinstance(value, list)
            or any(type(item) is not int for item in value)
            or value != wanted
        ):
            raise QualificationError(
                f"{label} qualification tail {key} counts differ"
            )
        result[key] = list(value)
    return result


def compare_tail_snapshots(
    left: Mapping[str, np.ndarray],
    right: Mapping[str, np.ndarray],
    *,
    total_agents: int,
    num_buffers: int,
    atol: float,
) -> dict[str, float]:
    """Tail rewards/terminals/validity are exact; bootstrap values are fp32-close."""

    tolerance = _num(atol, "tail snapshot atol")
    if tolerance < 0:
        raise QualificationError("tail snapshot atol must be nonnegative")
    validate_tail_snapshot(
        left,
        total_agents=total_agents,
        num_buffers=num_buffers,
    )
    validate_tail_snapshot(
        right,
        total_agents=total_agents,
        num_buffers=num_buffers,
    )
    maxima: dict[str, float] = {}
    for key in TAIL_EXACT_SNAPSHOT_FIELDS:
        if not np.array_equal(left[key], right[key]):
            raise QualificationError(f"exact tail snapshot field {key} differs")
        maxima[key] = 0.0
    maxima["tail_values"] = _max_abs_error(
        "tail_values",
        left["tail_values"],
        right["tail_values"],
        tolerance,
    )
    return maxima


def validate_tail_value_routing(
    snapshot: Mapping[str, np.ndarray],
    *,
    total_agents: int,
    num_buffers: int,
    atol: float,
) -> dict[str, float]:
    """Each primary/frozen tail segment must come from its own decoder value."""

    agents = _int(total_agents, "tail routing total agents", minimum=1)
    buffers = _int(num_buffers, "tail routing buffers", minimum=1)
    tolerance = _num(atol, "tail routing atol")
    if tolerance < 0 or agents % buffers:
        raise QualificationError("tail routing dimensions or tolerance are invalid")
    validate_tail_snapshot(
        snapshot,
        total_agents=agents,
        num_buffers=buffers,
    )
    pattern = re.compile(r"tail_decoder_bank_([0-9]+)_buffer_([0-9]+)")
    decoded: dict[tuple[int, int], np.ndarray] = {}
    for key, value in snapshot.items():
        match = pattern.fullmatch(key)
        if match is None:
            continue
        location = (int(match.group(1)), int(match.group(2)))
        if location in decoded:
            raise QualificationError(f"duplicate tail decoder snapshot {location}")
        if not isinstance(value, np.ndarray) or value.dtype != np.dtype(np.float32):
            raise QualificationError(f"tail decoder snapshot {key} is not float32")
        if value.ndim < 2 or value.shape[0] <= 0 or value.shape[-1] <= 0:
            raise QualificationError(f"tail decoder snapshot {key} shape is malformed")
        if not np.isfinite(value).all():
            raise QualificationError(
                f"tail decoder snapshot {key} contains non-finite values"
            )
        decoded[location] = value
    banks = sorted({bank for bank, _ in decoded})
    if not banks or banks != list(range(len(banks))):
        raise QualificationError("tail decoder bank coverage is incomplete")
    expected = {(bank, buffer) for bank in banks for buffer in range(buffers)}
    if set(decoded) != expected:
        raise QualificationError("tail decoder bank/buffer coverage is incomplete")

    per_buffer = agents // buffers
    terminals = snapshot["tail_terminals"]
    tail_values = snapshot["tail_values"]
    maxima: dict[str, float] = {}
    for buffer in range(buffers):
        decoder_values = np.concatenate(
            [decoded[(bank, buffer)][:, -1] for bank in banks]
        ).astype(np.float32, copy=False)
        if decoder_values.shape != (per_buffer,):
            raise QualificationError(
                "tail decoder active-row coverage differs from the agent partition"
            )
        start = buffer * per_buffer
        stop = start + per_buffer
        expected_values = np.where(
            terminals[start:stop] == 0.0,
            decoder_values,
            np.zeros(per_buffer, dtype=np.float32),
        ).astype(np.float32, copy=False)
        maxima[f"tail_decoder_buffer_{buffer}"] = _max_abs_error(
            f"tail decoder buffer {buffer}",
            tail_values[start:stop],
            expected_values,
            tolerance,
        )
    return maxima


def validate_frozen_advantages(
    advantages: Any,
    *,
    primary_rows: set[int],
    frozen_rows: set[int],
    horizon: int,
) -> dict[str, Any]:
    """The native GAE buffer is finite and all frozen rows are exactly zero."""

    steps = _int(horizon, "advantage horizon", minimum=1)
    if not isinstance(advantages, np.ndarray):
        raise QualificationError("advantages evidence is not an ndarray")
    if advantages.dtype != np.dtype(np.float32):
        raise QualificationError("advantages evidence is not float32")
    if advantages.ndim != 2 or advantages.shape[1] != steps:
        raise QualificationError(
            f"advantages shape {advantages.shape} is not (*, {steps})"
        )
    rows = set(range(advantages.shape[0]))
    if (
        not primary_rows
        or not frozen_rows
        or primary_rows & frozen_rows
        or primary_rows | frozen_rows != rows
    ):
        raise QualificationError("advantage row partition is invalid")
    if not np.isfinite(advantages).all():
        raise QualificationError("advantages evidence contains non-finite values")
    frozen = advantages[sorted(frozen_rows)]
    if not np.array_equal(frozen, np.zeros_like(frozen)):
        raise QualificationError("frozen-bank advantages are not exactly zero")
    primary = advantages[sorted(primary_rows)]
    return {
        "shape": list(advantages.shape),
        "frozen_rows_zero": sorted(frozen_rows),
        "primary_max_abs": (
            float(np.max(np.abs(primary))) if primary.size else 0.0
        ),
    }


def _canonical_float32_sha256(value: np.ndarray) -> str:
    array = np.asarray(value, dtype="<f4", order="C")
    return hashlib.sha256(array.tobytes(order="C")).hexdigest()


def validate_integrated_advantage_oracle(
    arrays: Mapping[str, np.ndarray],
    state_report: Mapping[str, Any],
    config: Mapping[str, Any],
    *,
    atol: float,
) -> dict[str, Any]:
    """Reconstruct a real zero-LR rollout→train advantage tensor independently."""

    tolerance = _num(atol, "integrated advantage oracle atol")
    if tolerance < 0:
        raise QualificationError(
            "integrated advantage oracle tolerance is negative"
        )
    if not isinstance(config, Mapping):
        raise QualificationError("integrated advantage config is missing")
    vec = config.get("vec")
    train = config.get("train")
    if not isinstance(vec, Mapping) or not isinstance(train, Mapping):
        raise QualificationError("integrated advantage config sections are missing")
    agents = _int(
        vec.get("total_agents"),
        "integrated advantage total agents",
        minimum=1,
    )
    buffers = _int(
        vec.get("num_buffers"),
        "integrated advantage buffers",
        minimum=1,
    )
    horizon = _int(
        train.get("horizon"),
        "integrated advantage horizon",
        minimum=1,
    )
    minibatch = _int(
        train.get("minibatch_size"),
        "integrated advantage minibatch",
        minimum=1,
    )
    replay_ratio = _int(
        train.get("replay_ratio"),
        "integrated advantage replay ratio",
        minimum=1,
    )
    frozen_banks = _int(
        vec.get("num_frozen_banks"),
        "integrated advantage frozen banks",
        minimum=0,
    )
    cudagraphs = _int(
        config.get("cudagraphs"),
        "integrated advantage cudagraph setting",
    )
    if (
        agents != HETEROGENEOUS_TOTAL_AGENTS
        or buffers != HETEROGENEOUS_NUM_BUFFERS
        or horizon != HETEROGENEOUS_HORIZON
        or frozen_banks != 1
        or _num(
            vec.get("frozen_bank_pct"),
            "integrated advantage frozen percentage",
        )
        != 0.5
        or minibatch != agents * horizon
        or replay_ratio != 1
        or _num(
            train.get("learning_rate"),
            "integrated advantage learning rate",
        )
        != 0.0
        or train.get("anneal_lr") is not False
        or config.get("reset_state") is not True
        or cudagraphs not in {-1, DEFAULT_CUDAGRAPH_WARMUP_EPOCHS}
    ):
        raise QualificationError(
            "integrated advantage oracle requires the closed zero-LR "
            "single-full-batch rollout configuration"
        )

    primary_rows, frozen_rows = derive_row_partition(
        state_report,
        total_agents=agents,
    )
    float_shapes = {
        "values": (horizon, agents),
        "rewards": (horizon, agents),
        "terminals": (horizon, agents),
        "tail_values": (agents,),
        "tail_rewards": (agents,),
        "tail_terminals": (agents,),
        "advantages_after_train": (agents, horizon),
    }
    normalized: dict[str, np.ndarray] = {}
    for key, shape in float_shapes.items():
        value = arrays.get(key)
        if (
            not isinstance(value, np.ndarray)
            or value.dtype != np.dtype(np.float32)
            or value.shape != shape
            or not np.isfinite(value).all()
        ):
            raise QualificationError(
                f"integrated advantage field {key} is not finite float32 {shape}"
            )
        normalized[key] = value
    for key in ("terminals", "tail_terminals"):
        if not np.isin(
            normalized[key],
            np.array([0.0, 1.0], dtype=np.float32),
        ).all():
            raise QualificationError(
                f"integrated advantage field {key} is not binary"
            )
    validate_tail_validity(
        arrays.get("tail_valid"),
        num_buffers=buffers,
        expected=1,
        label="integrated pre-train tail",
    )
    validate_tail_validity(
        arrays.get("tail_valid_after_train"),
        num_buffers=buffers,
        expected=0,
        label="integrated post-train tail",
    )
    selected_rows = arrays.get("selected_rows_after_train")
    if (
        not isinstance(selected_rows, np.ndarray)
        or selected_rows.dtype != np.dtype(np.int32)
        or selected_rows.ndim != 1
        or selected_rows.size == 0
    ):
        raise QualificationError(
            "integrated selected-row evidence is not nonempty int32"
        )
    selected_set = {
        int(value) for value in selected_rows.reshape(-1).tolist()
    }
    if not selected_set <= primary_rows or selected_set & frozen_rows:
        raise QualificationError(
            "integrated train selected a row outside the learner bank"
        )

    gamma = _num(train.get("gamma"), "integrated advantage gamma")
    gae_lambda = _num(
        train.get("gae_lambda"),
        "integrated advantage lambda",
    )
    rho_clip = _num(
        train.get("vtrace_rho_clip"),
        "integrated advantage rho clip",
    )
    c_clip = _num(
        train.get("vtrace_c_clip"),
        "integrated advantage c clip",
    )
    expected_coefficients = (0.995, 0.95, 1.0, 1.0)
    if (gamma, gae_lambda, rho_clip, c_clip) != expected_coefficients:
        raise QualificationError(
            "integrated advantage recurrence coefficients differ from the "
            "closed production fixture"
        )
    verifier, verifier_identity = _load_rollout_transition_verifier()
    expected = np.asarray(
        verifier.reference_advantages(
            values=normalized["values"].T.tolist(),
            rewards=normalized["rewards"].T.tolist(),
            terminals=normalized["terminals"].T.tolist(),
            importance=np.ones((agents, horizon), np.float32).tolist(),
            tail_values=normalized["tail_values"].tolist(),
            tail_rewards=normalized["tail_rewards"].tolist(),
            tail_terminals=normalized["tail_terminals"].tolist(),
            gamma=gamma,
            gae_lambda=gae_lambda,
            rho_clip=rho_clip,
            c_clip=c_clip,
        ),
        dtype=np.float32,
    )
    if expected.shape != (agents, horizon) or not np.isfinite(expected).all():
        raise QualificationError(
            "integrated independent recurrence produced malformed advantages"
        )
    expected[sorted(frozen_rows)] = np.float32(0.0)
    observed = normalized["advantages_after_train"]
    validate_frozen_advantages(
        observed,
        primary_rows=primary_rows,
        frozen_rows=frozen_rows,
        horizon=horizon,
    )
    primary_index = sorted(primary_rows)
    error = np.abs(observed[primary_index] - expected[primary_index])
    full_error = float(np.max(error)) if error.size else 0.0
    if full_error > tolerance:
        raise QualificationError(
            "integrated production advantages differ from the independent "
            f"recurrence: {full_error} > {tolerance}"
        )
    last_expected = np.abs(expected[primary_index, horizon - 1])
    nonzero_positions = np.flatnonzero(last_expected > tolerance)
    if nonzero_positions.size == 0:
        raise QualificationError(
            "integrated fixture has no nondegenerate primary last-slot signal"
        )
    nonzero_rows = [primary_index[int(index)] for index in nonzero_positions]
    last_error = float(np.max(error[:, horizon - 1]))
    return {
        "schema_version": INTEGRATED_ADVANTAGE_ORACLE_SCHEMA_VERSION,
        "contract": INTEGRATED_ADVANTAGE_CONTRACT,
        "importance_contract": INTEGRATED_IMPORTANCE_CONTRACT,
        "cudagraphs": cudagraphs,
        "total_agents": agents,
        "num_buffers": buffers,
        "horizon": horizon,
        "gamma": gamma,
        "gae_lambda": gae_lambda,
        "rho_clip": rho_clip,
        "c_clip": c_clip,
        "verifier_path": verifier_identity["path"],
        "verifier_sha256": verifier_identity["sha256"],
        "verifier_bytes": verifier_identity["bytes"],
        "primary_rows": primary_index,
        "frozen_rows": sorted(frozen_rows),
        "expected_advantages_sha256": _canonical_float32_sha256(expected),
        "observed_advantages_sha256": _canonical_float32_sha256(observed),
        "selected_rows": [
            int(value) for value in selected_rows.reshape(-1).tolist()
        ],
        "selected_rows_sha256": hashlib.sha256(
            np.ascontiguousarray(selected_rows.astype("<i4", copy=False)).tobytes()
        ).hexdigest(),
        "primary_max_abs_error": full_error,
        "primary_last_slot_max_abs_error": last_error,
        "primary_last_slot_max_expected_abs": float(np.max(last_expected)),
        "nonzero_primary_last_rows": nonzero_rows,
        "frozen_rows_exact_zero": True,
        "tail_consumed": True,
    }


def compare_integrated_advantage_parity(
    left: np.ndarray,
    right: np.ndarray,
    *,
    primary_rows: set[int],
    horizon: int,
    atol: float,
) -> dict[str, float]:
    """Require graph-off/on parity across the full and final-slot tensors."""

    steps = _int(horizon, "integrated parity horizon", minimum=1)
    tolerance = _num(atol, "integrated parity atol")
    if tolerance < 0:
        raise QualificationError("integrated parity tolerance is negative")
    left_array, right_array = _validate_array_pair(
        "integrated advantages",
        left,
        right,
    )
    if (
        left_array.ndim != 2
        or left_array.shape[1] != steps
        or not primary_rows
        or not primary_rows <= set(range(left_array.shape[0]))
    ):
        raise QualificationError("integrated parity shape/row contract differs")
    delta = np.abs(left_array - right_array)
    full = float(np.max(delta)) if delta.size else 0.0
    last = float(np.max(delta[sorted(primary_rows), steps - 1]))
    if full > tolerance:
        raise QualificationError(
            f"graph-mode full advantage parity error {full} exceeds {tolerance}"
        )
    if last > tolerance:
        raise QualificationError(
            f"graph-mode last-slot parity error {last} exceeds {tolerance}"
        )
    return {
        "full_max_abs": full,
        "last_slot_max_abs": last,
        "atol": tolerance,
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
    backend: Any,
    pufferl: Any,
    record: dict[str, Any],
    *,
    additional_rollouts: int = 0,
    consume_tail_each: bool = False,
    num_buffers: int | None = None,
) -> dict[str, float]:
    """Finish a bounded telemetry interval and bind its exact-zero verdict."""
    rollouts = _int(
        additional_rollouts,
        "additional integrity rollouts",
        minimum=0,
    )
    if type(consume_tail_each) is not bool:
        raise QualificationError(
            "additional integrity tail-consumption flag is not boolean"
        )
    if consume_tail_each:
        buffers = _int(
            num_buffers,
            "additional integrity tail-consumption buffers",
            minimum=1,
        )
    else:
        buffers = 0
    discards = 0
    for index in range(rollouts):
        backend.rollouts(pufferl)
        if consume_tail_each:
            consume_qualification_tail(
                backend,
                pufferl,
                num_buffers=buffers,
                label=f"integrity rollout {index}",
            )
            discards += 1
    record["integrity_tail_discards"] = discards
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
    for key in ("host", "gpu", "gpu_uuid"):
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
    validate_hard_integrity(record.get("warmup_hard_integrity", {}))
    if record.get("warmup_hard_integrity_zero") is not True:
        raise QualificationError(
            f"{label} throughput warmup hard-integrity gate is not zero"
        )
    _int(
        record.get("tail_records_explicitly_discarded"),
        f"{label} throughput tail discard count",
        minimum=1,
    )


def _load_required_throughput_baseline_binding(
    path: Path,
    *,
    output: Path,
) -> tuple[dict[str, Any], dict[str, Any], bytes]:
    """Preflight one bounded external baseline and bind its immutable bytes."""

    if path is None:
        raise QualificationError("baseline throughput artifact is required")
    baseline_path = Path(path).expanduser().absolute()
    output_path = Path(output).expanduser().absolute()
    try:
        baseline_metadata = baseline_path.lstat()
    except OSError as exc:
        raise QualificationError(
            f"cannot inspect throughput baseline artifact {baseline_path}: {exc}"
        ) from exc
    if (
        stat.S_ISLNK(baseline_metadata.st_mode)
        or not stat.S_ISREG(baseline_metadata.st_mode)
    ):
        raise QualificationError(
            "throughput baseline artifact is not a regular non-symlink file: "
            f"{baseline_path}"
        )
    try:
        baseline_path.relative_to(output_path)
    except ValueError:
        pass
    else:
        raise QualificationError(
            "baseline throughput artifact must be outside candidate output"
        )
    try:
        canonical_baseline = baseline_path.resolve(strict=True)
        canonical_metadata = canonical_baseline.lstat()
    except OSError as exc:
        raise QualificationError(
            f"cannot resolve throughput baseline artifact {baseline_path}: {exc}"
        ) from exc
    if (
        not stat.S_ISREG(canonical_metadata.st_mode)
        or canonical_metadata.st_dev != baseline_metadata.st_dev
        or canonical_metadata.st_ino != baseline_metadata.st_ino
    ):
        raise QualificationError(
            "throughput baseline artifact changed identity while resolving"
        )
    canonical_output = output_path.resolve()
    try:
        canonical_baseline.relative_to(canonical_output)
    except ValueError:
        pass
    else:
        raise QualificationError(
            "baseline throughput artifact resolves inside candidate output"
        )
    encoded = _read_bounded_regular_bytes(
        canonical_baseline,
        maximum_bytes=CELL_MAX_JSON_BYTES,
        label="throughput baseline artifact",
    )
    try:
        final_metadata = baseline_path.lstat()
    except OSError as exc:
        raise QualificationError(
            f"cannot recheck throughput baseline artifact {baseline_path}: {exc}"
        ) from exc
    if (
        final_metadata.st_dev != baseline_metadata.st_dev
        or final_metadata.st_ino != baseline_metadata.st_ino
        or final_metadata.st_size != baseline_metadata.st_size
        or final_metadata.st_mtime_ns != baseline_metadata.st_mtime_ns
    ):
        raise QualificationError(
            "throughput baseline artifact changed while being bound"
        )
    baseline_path = canonical_baseline
    artifact = _decode_json_object(encoded, baseline_path)
    baseline = artifact.get("throughput")
    if not isinstance(baseline, Mapping):
        raise QualificationError(
            "baseline artifact has no throughput record to compare against"
        )
    _validate_throughput_record(baseline, "baseline")
    identity = {
        "path": str(baseline_path),
        "sha256": hashlib.sha256(encoded).hexdigest(),
        "bytes": len(encoded),
    }
    return dict(baseline), identity, encoded


def load_required_throughput_baseline(
    path: Path,
    *,
    output: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Public preflight API returning the validated record and byte identity."""

    baseline, identity, _ = _load_required_throughput_baseline_binding(
        path,
        output=output,
    )
    return baseline, identity


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
    for key in ("host", "gpu", "gpu_uuid", "precision_bytes", "config"):
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
    tensors = raw.get("tensors")
    decoders = raw.get("decoder_outputs")
    tail_decoders = raw.get("tail_decoder_outputs")
    if (
        not isinstance(tensors, Mapping)
        or not isinstance(decoders, list)
        or not isinstance(tail_decoders, list)
    ):
        raise QualificationError("native snapshot structure is malformed")
    banks = _int(raw.get("num_banks"), "snapshot num_banks", minimum=1)
    buffers = _int(raw.get("num_buffers"), "snapshot num_buffers", minimum=1)
    arrays = {str(key): _decode_tensor(value) for key, value in tensors.items()}

    def bind_decoders(
        entries: list[Any],
        *,
        prefix: str,
        label: str,
    ) -> None:
        seen: set[tuple[int, int]] = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise QualificationError(f"{label} snapshot entry is malformed")
            key = (
                _int(entry.get("bank"), f"{label} bank"),
                _int(entry.get("buffer"), f"{label} buffer"),
            )
            rows = _int(
                entry.get("active_rows"),
                f"{label} active rows",
                minimum=1,
            )
            if key in seen:
                raise QualificationError(f"duplicate {label} snapshot {key}")
            seen.add(key)
            decoded = _decode_tensor(entry.get("tensor"))
            if decoded.ndim < 1 or decoded.shape[0] != rows:
                raise QualificationError(
                    f"{label} snapshot includes inactive rows"
                )
            arrays[f"{prefix}_bank_{key[0]}_buffer_{key[1]}"] = decoded
        if seen != {(bank, buffer) for bank in range(banks) for buffer in range(buffers)}:
            raise QualificationError(
                f"{label} snapshot bank/buffer coverage is incomplete"
            )

    bind_decoders(decoders, prefix="decoder", label="decoder")
    bind_decoders(
        tail_decoders,
        prefix="tail_decoder",
        label="tail decoder",
    )
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
    frozen_hidden_size: int | None = None,
    frozen_num_layers: int | None = None,
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
            "frozen_bank_hidden_size": (
                hidden_size
                if frozen_hidden_size is None
                else frozen_hidden_size
            ),
            "frozen_bank_num_layers": (
                num_layers
                if frozen_num_layers is None
                else frozen_num_layers
            ),
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


def _expected_graph_execution_counts(
    kind: str,
    config: Mapping[str, Any],
    record: Mapping[str, Any],
    args: argparse.Namespace,
) -> dict[str, int]:
    """Derive exact post-construction callback executions for one closed cell."""

    if kind not in TRANSITION_CELL_KINDS:
        raise QualificationError(
            f"graph execution counts are undefined for cell kind {kind}"
        )
    vec = config.get("vec")
    train = config.get("train")
    env = config.get("env")
    if not isinstance(vec, Mapping) or not isinstance(train, Mapping):
        raise QualificationError("graph execution config is incomplete")
    horizon = _int(train.get("horizon"), "graph execution horizon", minimum=1)
    buffers = _int(vec.get("num_buffers"), "graph execution buffers", minimum=1)
    agents = _int(vec.get("total_agents"), "graph execution agents", minimum=1)

    if kind == "rollout":
        if not isinstance(env, Mapping):
            raise QualificationError("rollout graph execution env config is missing")
        rollout_calls = 2 + _int(
            env.get("max_decisions"),
            "rollout graph integrity calls",
            minimum=1,
        )
        tail_calls = rollout_calls
        train_calls = 1
    elif kind in {"terminal_auto", "terminal_control"}:
        rollout_calls = 2
        tail_calls = 0
        train_calls = 0
    elif kind == "ratio":
        rollout_calls = _int(
            record.get("ratio_calls"),
            "ratio graph execution calls",
            minimum=1,
        )
        tail_calls = rollout_calls
        train_calls = rollout_calls
    elif kind == "throughput":
        warmup = _int(
            args.throughput_warmup_rollouts,
            "throughput graph warmup rollouts",
            minimum=0,
        )
        timed = _int(
            args.throughput_timed_rollouts,
            "throughput graph timed rollouts",
            minimum=1,
        )
        rollout_calls = warmup + timed
        tail_calls = rollout_calls
        train_calls = 0
    else:  # pragma: no cover - closed by TRANSITION_CELL_KINDS
        raise AssertionError(kind)

    minibatch_executions = 0
    if train_calls:
        batch = agents * horizon
        minibatch = _int(
            train.get("minibatch_size"),
            "graph execution minibatch size",
            minimum=1,
        )
        replay = _int(
            train.get("replay_ratio"),
            "graph execution replay ratio",
            minimum=1,
        )
        if batch % minibatch:
            raise QualificationError(
                "graph execution batch is not divisible by minibatch size"
            )
        minibatch_executions = train_calls * replay * (batch // minibatch)
    return {
        "rollout": rollout_calls * horizon * buffers,
        "tail": tail_calls * buffers,
        "train": minibatch_executions,
    }


def validate_graph_execution_evidence(
    evidence: Any,
    *,
    expected_cudagraphs: int,
    expected_workload: str,
    expected_counts: Mapping[str, Any],
) -> dict[str, Any]:
    """Prove graph configuration through capture, handles, and live launches."""

    expected = _int(
        expected_cudagraphs,
        "graph-execution expected cudagraph setting",
    )
    if expected not in {-1, DEFAULT_CUDAGRAPH_WARMUP_EPOCHS}:
        raise QualificationError(
            "graph-execution evidence has an unsupported expected mode"
        )
    if (
        not isinstance(expected_workload, str)
        or expected_workload not in TRANSITION_CELL_KINDS
    ):
        raise QualificationError("graph-execution workload is invalid")
    if not isinstance(evidence, Mapping):
        raise QualificationError("graph-execution evidence is not a mapping")
    _require_exact_keys(
        evidence,
        (
            "workload",
            "cudagraphs",
            "captured",
            "handles_ready",
            "graph_launch_counts",
            "eager_execution_counts",
        ),
        "graph-execution evidence",
    )
    if evidence.get("workload") != expected_workload:
        raise QualificationError("graph-execution workload differs")
    if (
        _require_exact_json_int(
            evidence.get("cudagraphs"),
            "graph-execution cudagraph setting",
        )
        != expected
    ):
        raise QualificationError("graph-execution cudagraph setting differs")
    roles = ("rollout", "tail", "train")
    captured = evidence.get("captured")
    handles = evidence.get("handles_ready")
    graph_launches = evidence.get("graph_launch_counts")
    eager_executions = evidence.get("eager_execution_counts")
    for section, value in (
        ("captured", captured),
        ("handles_ready", handles),
        ("graph_launch_counts", graph_launches),
        ("eager_execution_counts", eager_executions),
    ):
        if not isinstance(value, Mapping):
            raise QualificationError(
                f"graph-execution {section} section is missing"
            )
        _require_exact_keys(value, roles, f"graph-execution {section}")

    if not isinstance(expected_counts, Mapping):
        raise QualificationError("graph-execution expected counts are missing")
    _require_exact_keys(
        expected_counts,
        roles,
        "graph-execution expected counts",
    )
    closed_counts = {
        role: _require_exact_json_int(
            expected_counts[role],
            f"graph-execution expected {role} count",
            minimum=0,
        )
        for role in roles
    }
    graph_enabled = expected == DEFAULT_CUDAGRAPH_WARMUP_EPOCHS
    for role in roles:
        if type(captured[role]) is not bool or type(handles[role]) is not bool:
            raise QualificationError(
                f"graph-execution {role} capture/handle evidence is not boolean"
            )
        if captured[role] is not graph_enabled:
            raise QualificationError(
                f"graph-execution {role} capture flag differs"
            )
        if handles[role] is not graph_enabled:
            raise QualificationError(
                f"graph-execution {role} handle readiness differs"
            )
        graph_count = _require_exact_json_int(
            graph_launches[role],
            f"graph-execution {role} graph launch count",
            minimum=0,
        )
        eager_count = _require_exact_json_int(
            eager_executions[role],
            f"graph-execution {role} eager count",
            minimum=0,
        )
        expected_graph = closed_counts[role] if graph_enabled else 0
        expected_eager = 0 if graph_enabled else closed_counts[role]
        if graph_count != expected_graph:
            raise QualificationError(
                f"graph-execution {role} graph count differs: "
                f"{graph_count} != {expected_graph}"
            )
        if eager_count != expected_eager:
            raise QualificationError(
                f"graph-execution {role} eager count differs: "
                f"{eager_count} != {expected_eager}"
            )
    return copy.deepcopy(dict(evidence))


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
    if kind == "rollout":
        return qualification_args(
            cudagraphs=cudagraphs,
            seed=args.seed,
            total_agents=HETEROGENEOUS_TOTAL_AGENTS,
            num_buffers=HETEROGENEOUS_NUM_BUFFERS,
            num_threads=HETEROGENEOUS_NUM_BUFFERS,
            horizon=HETEROGENEOUS_HORIZON,
            max_decisions=16,
            hidden_size=HETEROGENEOUS_PRIMARY_HIDDEN_SIZE,
            num_layers=HETEROGENEOUS_PRIMARY_NUM_LAYERS,
            frozen_banks=1,
            frozen_bank_pct=0.5,
            frozen_hidden_size=HETEROGENEOUS_FROZEN_HIDDEN_SIZE,
            frozen_num_layers=HETEROGENEOUS_FROZEN_NUM_LAYERS,
            learning_rate=0.0,
        )
    if kind in {"construction", "terminal_auto", "terminal_control"}:
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
            max_decisions=4096,
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


def _expected_cell_config(
    kind: str,
    cudagraphs: int,
    args: argparse.Namespace,
    puffer_root: Path,
) -> dict[str, Any]:
    """Reconstruct the exact child configuration, including strict profiles."""

    config = _cell_config(kind, cudagraphs, args)
    if kind in STRICT_CONFIG_NEGATIVE_CELL_KINDS:
        config["env"] = {
            "seed": args.seed,
            "max_decisions": 16,
            "force_home_team": _installed_team_count(puffer_root),
        }
    elif kind in STRICT_CONFIG_POSITIVE_CELL_KINDS:
        config["env"] = (
            _installed_environment_config(puffer_root)
            if kind == "strict_positive_full"
            else {"seed": args.seed, "max_decisions": 16}
        )
    return config


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
        source_files = tuple(source_files)
        return native_extension_source_manifest_sha256(
            puffer_root,
            source_files,
        )
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
            "rollout_transition_contract",
            *QUALIFICATION_SURFACE_BINDINGS,
        )
        if not hasattr(_C, name)
    ]
    if missing:
        raise QualificationError(
            f"compiled qualification surface is missing: {missing}"
        )
    if _C.rollout_transition_contract != ROLLOUT_TRANSITION_CONTRACT:
        raise QualificationError(
            "compiled rollout-transition contract is missing or wrong"
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
        "rollout_transition_contract": str(_C.rollout_transition_contract),
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
    if identity.get("rollout_transition_contract") != ROLLOUT_TRANSITION_CONTRACT:
        raise QualificationError(
            "compiled rollout-transition contract is not "
            f"{ROLLOUT_TRANSITION_CONTRACT}"
        )
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
        "rollout_transition_contract",
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
            "rollout_transition_patch",
            "qualifier",
            "compiled_backend_source_ledger",
        ),
        "strict-stage patch identity",
    )
    if patch_identity.get("puffer_git_head") != PINNED_PUFFER_COMMIT:
        raise QualificationError("strict-stage patch identity has the wrong Puffer pin")
    for key in (
        "strict_environment_config_patch",
        "rollout_transition_patch",
        "qualifier",
        "compiled_backend_source_ledger",
    ):
        record = patch_identity.get(key)
        if not isinstance(record, Mapping):
            raise QualificationError(f"strict-stage patch identity {key} is missing")
        patch_artifact = key in {
            "strict_environment_config_patch",
            "rollout_transition_patch",
        }
        required = (
            ("path", "sha256", "reverse_applicable")
            if patch_artifact
            else ("path", "sha256")
        )
        _require_exact_keys(record, required, f"strict-stage patch identity {key}")
        _require_sha256(record.get("sha256"), f"strict-stage {key} SHA-256")
        _require_bounded_absolute_path(record.get("path"), f"strict-stage {key} path")
        if patch_artifact and record.get("reverse_applicable") is not True:
            raise QualificationError(f"strict-stage {key} is not installed")

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
            "rollout_transition_patch": ROLLOUT_TRANSITION_PATCH,
            "qualifier": Path(__file__).resolve(),
            "compiled_backend_source_ledger": COMPILED_BACKEND_SOURCE_LEDGER,
        }
        patch_artifacts = {
            "strict_environment_config_patch",
            "rollout_transition_patch",
        }
        for key, path in expected_files.items():
            record = patch_identity[key]
            if Path(str(record["path"])).resolve() != path.resolve():
                raise QualificationError(f"strict-stage {key} path drifted")
            observed_sha = (
                _required_file_sha256(path, f"strict-stage {key}")
                if key in patch_artifacts
                else sha256(path)
            )
            if observed_sha != record["sha256"]:
                raise QualificationError(f"strict-stage {key} bytes drifted")
        _require_strict_patch_reverse_applicable(root)
        _require_rollout_transition_patch_reverse_applicable(root)
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


def _measure_heterogeneous_rollout(
    _C: Any,
    pufferl: Any,
    result: dict[str, Any],
    directory: Path,
    config: Mapping[str, Any],
) -> dict[str, np.ndarray]:
    total_agents = int(config["vec"]["total_agents"])
    num_buffers = int(config["vec"]["num_buffers"])
    horizon = int(config["train"]["horizon"])
    atol = GRAPH_ATOL_BY_PRECISION[int(_C.precision_bytes)]
    primary = validate_policy_weight_descriptor(
        _C.qualification_policy_weights(
            pufferl, 0, QUALIFICATION_POLICY_MAX_BYTES
        ),
        expected_bank=0,
        expected_role="primary",
        expected_hidden_size=HETEROGENEOUS_PRIMARY_HIDDEN_SIZE,
        expected_num_layers=HETEROGENEOUS_PRIMARY_NUM_LAYERS,
        expected_slice_size=HETEROGENEOUS_SLICE_SIZE,
    )
    frozen = _validated_frozen_weight_descriptor(
        _C.qualification_policy_weights(
            pufferl, 1, QUALIFICATION_POLICY_MAX_BYTES
        )
    )
    if (
        primary["parameter_bytes"] == frozen["parameter_bytes"]
        or primary["hidden_size"] == frozen["hidden_size"]
        or primary["num_layers"] == frozen["num_layers"]
    ):
        raise QualificationError(
            "qualification primary/frozen policy architectures do not differ"
        )
    primary_architecture = _policy_weight_summary(primary)
    frozen_architecture = {
        key: copy.deepcopy(value)
        for key, value in frozen.items()
        if key != "weights"
    }
    donors: dict[str, dict[str, Any]] = {}

    def variant(
        name: str, coefficient: float
    ) -> tuple[dict[str, np.ndarray], Mapping[str, Any], dict[str, Any]]:
        cleared = _C.qualification_recurrent_state(pufferl, True)
        validate_zero_state(
            cleared,
            expected_banks=2,
            expected_buffers=num_buffers,
        )
        donors[name] = install_authenticated_frozen_donor(
            _C,
            pufferl,
            directory,
            frozen,
            name=name.replace("_", "-"),
            value_coefficient=coefficient,
        )
        _C.rollouts(pufferl)
        snapshot = decode_snapshot(_C.qualification_snapshot(pufferl))
        state = _C.qualification_recurrent_state(pufferl, False)
        oracle = validate_heterogeneous_rollout_oracle(
            snapshot,
            state,
            total_agents=total_agents,
            num_buffers=num_buffers,
            horizon=horizon,
            value_coefficient=coefficient,
            atol=atol,
        )
        return snapshot, state, oracle

    zero_arrays, zero_state, zero_oracle = variant(
        "zero_value", HETEROGENEOUS_VALUE_COEFFICIENTS["zero_value"]
    )
    zero_frozen = dict(frozen)
    zero_frozen["weights"] = build_heterogeneous_frozen_donor(
        frozen,
        value_coefficient=HETEROGENEOUS_VALUE_COEFFICIENTS["zero_value"],
    )
    result["heterogeneous_zero_tail_consumption"] = (
        consume_heterogeneous_tail_record(
            _C,
            pufferl,
            primary,
            zero_frozen,
            num_buffers=num_buffers,
            arrays=zero_arrays,
        )
    )
    result["integrated_advantage_oracle"] = (
        validate_integrated_advantage_oracle(
            zero_arrays,
            zero_state,
            config,
            atol=RATIO_ATOL_BY_PRECISION[int(_C.precision_bytes)],
        )
    )
    positive_arrays, positive_state, positive_oracle = variant(
        "positive_value",
        HETEROGENEOUS_VALUE_COEFFICIENTS["positive_value"],
    )
    result["heterogeneous_positive_tail_discard"] = (
        consume_qualification_tail(
            _C,
            pufferl,
            num_buffers=num_buffers,
            label="heterogeneous positive-value rollout",
        )
    )
    result["heterogeneous_policy"] = {
        "primary_architecture": primary_architecture,
        "frozen_architecture": frozen_architecture,
        "donors": donors,
    }
    result["heterogeneous_zero_state"] = zero_state
    result["heterogeneous_positive_state"] = positive_state
    result["heterogeneous_zero_oracle"] = zero_oracle
    result["heterogeneous_positive_oracle"] = positive_oracle
    arrays = dict(positive_arrays)
    arrays.update(
        {
            f"{HETEROGENEOUS_ZERO_PREFIX}{key}": value
            for key, value in zero_arrays.items()
        }
    )
    validate_heterogeneous_policy_evidence(result, arrays, atol=atol)
    return arrays


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
    before_path = directory / f"ratio-before-{os.getpid()}.bin"
    after_path = directory / f"ratio-after-{os.getpid()}.bin"
    try:
        _C.save_weights(pufferl, str(before_path))
        before = sha256(before_path)
        covered: set[int] = set()
        calls = 0
        while covered != primary_rows and calls < call_limit:
            # Native train consumes and clears the one-tail-per-buffer record.
            # Every replay attempt therefore needs a fresh environment rollout.
            _C.rollouts(pufferl)
            before_train = decode_snapshot(_C.qualification_snapshot(pufferl))
            validate_tail_snapshot(
                before_train,
                total_agents=int(config["vec"]["total_agents"]),
                num_buffers=int(config["vec"]["num_buffers"]),
            )
            validate_tail_value_routing(
                before_train,
                total_agents=int(config["vec"]["total_agents"]),
                num_buffers=int(config["vec"]["num_buffers"]),
                atol=GRAPH_ATOL_BY_PRECISION[int(_C.precision_bytes)],
            )
            for key in (*TAIL_FLOAT_SNAPSHOT_FIELDS, "tail_valid"):
                arrays[f"{key}_{calls}"] = before_train[key]
            for key, value in before_train.items():
                if key.startswith("tail_decoder_bank_"):
                    arrays[f"{key}_attempt_{calls}"] = value
            _C.train(pufferl)
            snapshot = decode_snapshot(_C.qualification_snapshot(pufferl))
            selected = snapshot["selected_rows"].astype(np.int32, copy=False)
            arrays[f"selected_{calls}"] = selected
            arrays[f"ratio_{calls}"] = snapshot["mb_ratio"].astype(
                np.float32, copy=False
            )
            advantages = snapshot["advantages"]
            validate_frozen_advantages(
                advantages,
                primary_rows=primary_rows,
                frozen_rows=frozen_rows,
                horizon=int(config["train"]["horizon"]),
            )
            arrays[f"advantages_{calls}"] = advantages
            consumed = snapshot["tail_valid"]
            validate_tail_validity(
                consumed,
                num_buffers=int(config["vec"]["num_buffers"]),
                expected=0,
                label="post-train tail",
            )
            arrays[f"tail_valid_after_train_{calls}"] = consumed
            rows = {int(value) for value in selected.reshape(-1).tolist()}
            if rows & frozen_rows:
                raise QualificationError("PPO selected a frozen-bank row")
            if not rows <= primary_rows:
                raise QualificationError("PPO selected a row outside the bank layout")
            covered.update(rows)
            calls += 1
        bind_transition_integrity(_C, pufferl, result)
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
    num_buffers = int(config["vec"]["num_buffers"])
    tail_discards = 0
    for _ in range(args.throughput_warmup_rollouts):
        _C.rollouts(pufferl)
        consume_qualification_tail(
            _C,
            pufferl,
            num_buffers=num_buffers,
            label="throughput warmup",
        )
        tail_discards += 1
    warmup_log = _C.log(pufferl)
    if (
        not isinstance(warmup_log, Mapping)
        or not isinstance(warmup_log.get("env"), Mapping)
    ):
        raise QualificationError("throughput warmup integrity telemetry is missing")
    warmup_integrity = validate_hard_integrity(warmup_log["env"])
    start_step = int(pufferl.global_step)
    durations: list[float] = []
    for _ in range(args.throughput_timed_rollouts):
        one = time.perf_counter_ns()
        _C.rollouts(pufferl)
        durations.append((time.perf_counter_ns() - one) / 1.0e9)
        consume_qualification_tail(
            _C,
            pufferl,
            num_buffers=num_buffers,
            label="throughput timed rollout",
        )
        tail_discards += 1
    elapsed = sum(durations)
    steps = int(pufferl.global_step) - start_step
    integrity = validate_hard_integrity(dict(_C.log(pufferl)["env"]))
    try:
        import torch

        logical_device = torch.cuda.current_device()
        properties = torch.cuda.get_device_properties(logical_device)
        gpu = str(properties.name).strip()
        gpu_uuid = str(getattr(properties, "uuid", "")).strip()
    except (ImportError, OSError, RuntimeError) as exc:
        raise QualificationError(
            f"cannot bind throughput to the selected CUDA device: {exc}"
        ) from exc
    if not gpu or not gpu_uuid:
        raise QualificationError(
            "selected CUDA device has no stable name/UUID identity"
        )
    return {
        "host": socket.gethostname(),
        "gpu": gpu,
        "gpu_uuid": gpu_uuid,
        "precision_bytes": int(_C.precision_bytes),
        "config": dict(config),
        "steps": steps,
        "elapsed_seconds": elapsed,
        "steps_per_second": steps / elapsed,
        "median_rollout_seconds": statistics.median(durations),
        "p95_rollout_seconds": float(np.percentile(durations, 95)),
        "hard_integrity_zero": True,
        "hard_integrity": integrity,
        "warmup_hard_integrity_zero": True,
        "warmup_hard_integrity": warmup_integrity,
        "tail_records_explicitly_discarded": tail_discards,
        "utilization": dict(_C.get_utilization(0)),
    }


def run_cell(args: argparse.Namespace) -> int:
    run_nonce = _require_sha256(args.run_nonce, "qualification run nonce")
    cell_nonce = _require_sha256(args.cell_nonce, "qualification cell nonce")
    raw_output_json = Path(args.output_json).expanduser().absolute()
    output_json = raw_output_json.parent.resolve() / raw_output_json.name
    if args.output_npz:
        raw_output_npz = Path(args.output_npz).expanduser().absolute()
        output_npz = raw_output_npz.parent.resolve() / raw_output_npz.name
    else:
        output_npz = None
    puffer_root = Path(args.puffer_root).resolve()
    patch_identity = _rollout_transition_patch_identity(puffer_root)
    _C, module, evidence = _load_backend(puffer_root)
    config = _cell_config(args.kind, args.cudagraphs, args)
    pufferl = None
    arrays: dict[str, np.ndarray] = {}
    result: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "kind": args.kind,
        "run_nonce": run_nonce,
        "cell_nonce": cell_nonce,
        "identity": _module_identity(_C, module, puffer_root),
        "patch_identity": patch_identity,
        "cuda_runtime_preflight": evidence,
        "config": config,
        "host": socket.gethostname(),
        "platform": platform.platform(),
        "seed": args.seed,
        "accepted": False,
    }
    validate_module_identity(result["identity"])
    try:
        if args.kind == "rollout":
            result["cuda_advantage_oracle"] = (
                execute_cuda_advantage_oracle(_C)
            )
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
        if args.kind != "rollout":
            _load_frozen_from_primary(
                _C,
                pufferl,
                output_json.parent,
                int(config["vec"]["num_frozen_banks"]),
            )
        if args.kind == "construction":
            result["state"] = _C.qualification_recurrent_state(pufferl, False)
            validate_zero_state(result["state"], expected_banks=2, expected_buffers=1)
        elif args.kind == "rollout":
            result["state_before"] = _C.qualification_recurrent_state(pufferl, False)
            validate_zero_state(
                result["state_before"],
                expected_banks=2,
                expected_buffers=int(config["vec"]["num_buffers"]),
            )
            arrays = _measure_heterogeneous_rollout(
                _C,
                pufferl,
                result,
                output_json.parent,
                config,
            )
            result["tail_snapshot"] = validate_tail_snapshot(
                arrays,
                total_agents=int(config["vec"]["total_agents"]),
                num_buffers=int(config["vec"]["num_buffers"]),
            )
            result["tail_value_routing"] = validate_tail_value_routing(
                arrays,
                total_agents=int(config["vec"]["total_agents"]),
                num_buffers=int(config["vec"]["num_buffers"]),
                atol=GRAPH_ATOL_BY_PRECISION[int(_C.precision_bytes)],
            )
            # Keep the first-rollout parity snapshot, then deterministically
            # cross max_decisions so at least one complete episode contributes
            # integrity telemetry to this isolated cell.
            bind_transition_integrity(
                _C,
                pufferl,
                result,
                additional_rollouts=int(config["env"]["max_decisions"]),
                consume_tail_each=True,
                num_buffers=int(config["vec"]["num_buffers"]),
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
        if args.kind in TRANSITION_CELL_KINDS:
            raw_execution = _C.qualification_graph_execution(pufferl)
            if not isinstance(raw_execution, Mapping):
                raise QualificationError(
                    "native graph-execution evidence is not a mapping"
                )
            bound_execution = dict(raw_execution)
            bound_execution["workload"] = args.kind
            result["graph_execution"] = validate_graph_execution_evidence(
                bound_execution,
                expected_cudagraphs=int(config["cudagraphs"]),
                expected_workload=args.kind,
                expected_counts=_expected_graph_execution_counts(
                    args.kind,
                    config,
                    result,
                    args,
                ),
            )
        if arrays:
            if output_npz is None:
                raise QualificationError("cell produced arrays without an NPZ path")
            write_npz_atomic(output_npz, arrays)
            result["artifact"] = str(output_npz)
            result["artifact_bytes"] = output_npz.lstat().st_size
            result["artifact_sha256"] = sha256(output_npz)
        if pufferl is not None:
            constructed = pufferl
            pufferl = None
            _C.close(constructed)
        result["accepted"] = True
        write_json_atomic(output_json, result)
        return 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        write_json_atomic(output_json, result)
        raise
    finally:
        if pufferl is not None:
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


def _require_patch_reverse_applicable(
    puffer_root: Path,
    patch: Path,
    *,
    label: str,
) -> None:
    command = [
        "git",
        "-C",
        str(Path(puffer_root).resolve()),
        "apply",
        "--reverse",
        "--check",
        "--no-index",
        str(Path(patch).resolve()),
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
            f"{label} check failed: {_bounded_text(exc)}"
        ) from exc
    if completed.returncode != 0:
        detail = _bounded_text(completed.stderr or completed.stdout)
        raise QualificationError(
            f"{label} is not reverse-applicable: {detail}"
        )


def _require_strict_patch_reverse_applicable(puffer_root: Path) -> None:
    _require_patch_reverse_applicable(
        puffer_root,
        STRICT_ENV_CONFIG_PATCH,
        label="strict environment patch",
    )


def _require_rollout_transition_patch_reverse_applicable(
    puffer_root: Path,
) -> None:
    _require_patch_reverse_applicable(
        puffer_root,
        ROLLOUT_TRANSITION_PATCH,
        label="rollout transition patch",
    )


def _required_file_sha256(path: Path, label: str) -> str:
    artifact = Path(path)
    try:
        metadata = artifact.lstat()
    except OSError as exc:
        raise QualificationError(f"{label} is unavailable: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise QualificationError(f"{label} is not a regular non-symlink file")
    try:
        return sha256(artifact)
    except OSError as exc:
        raise QualificationError(f"{label} cannot be hashed: {exc}") from exc


def _rollout_transition_patch_identity(puffer_root: Path) -> dict[str, Any]:
    root = Path(puffer_root).resolve()
    head = _git_output(root, "rev-parse", "HEAD")
    if head != PINNED_PUFFER_COMMIT:
        raise QualificationError("rollout transition Puffer checkout is not exact-pinned")
    patch_sha = _required_file_sha256(
        ROLLOUT_TRANSITION_PATCH,
        "rollout transition patch",
    )
    _require_rollout_transition_patch_reverse_applicable(root)
    return {
        "puffer_git_head": head,
        "rollout_transition_patch": {
            "path": str(ROLLOUT_TRANSITION_PATCH.resolve()),
            "sha256": patch_sha,
            "reverse_applicable": True,
        },
    }


def validate_rollout_transition_patch_identity(
    identity: Any,
    *,
    expected_puffer_root: Path | None = None,
    rehash_files: bool = False,
) -> dict[str, Any]:
    if not isinstance(identity, Mapping):
        raise QualificationError("rollout transition patch identity is missing")
    _require_exact_keys(
        identity,
        ("puffer_git_head", "rollout_transition_patch"),
        "rollout transition patch identity",
    )
    if identity.get("puffer_git_head") != PINNED_PUFFER_COMMIT:
        raise QualificationError("rollout transition patch identity has the wrong pin")
    record = identity.get("rollout_transition_patch")
    if not isinstance(record, Mapping):
        raise QualificationError("rollout transition patch record is missing")
    _require_exact_keys(
        record,
        ("path", "sha256", "reverse_applicable"),
        "rollout transition patch record",
    )
    recorded_path = _require_bounded_absolute_path(
        record.get("path"),
        "rollout transition patch path",
    )
    recorded_sha = _require_sha256(
        record.get("sha256"),
        "rollout transition patch SHA-256",
    )
    if record.get("reverse_applicable") is not True:
        raise QualificationError("rollout transition patch is not installed")
    if rehash_files:
        if expected_puffer_root is None:
            raise QualificationError(
                "rollout transition patch revalidation requires a Puffer root"
            )
        root = Path(expected_puffer_root).resolve()
        if _git_output(root, "rev-parse", "HEAD") != PINNED_PUFFER_COMMIT:
            raise QualificationError(
                "rollout transition Puffer checkout pin drifted"
            )
        expected_patch = ROLLOUT_TRANSITION_PATCH.resolve()
        if recorded_path.resolve() != expected_patch:
            raise QualificationError("rollout transition patch path drifted")
        if (
            _required_file_sha256(
                expected_patch,
                "rollout transition patch",
            )
            != recorded_sha
        ):
            raise QualificationError("rollout transition patch bytes drifted")
        _require_rollout_transition_patch_reverse_applicable(root)
    return {
        "puffer_git_head": identity["puffer_git_head"],
        "rollout_transition_patch": dict(record),
    }


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
        _require_rollout_transition_patch_reverse_applicable(root)
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
                    "sha256": _required_file_sha256(
                        STRICT_ENV_CONFIG_PATCH,
                        "strict environment patch",
                    ),
                    "reverse_applicable": True,
                },
                "rollout_transition_patch": {
                    "path": str(ROLLOUT_TRANSITION_PATCH.resolve()),
                    "sha256": _required_file_sha256(
                        ROLLOUT_TRANSITION_PATCH,
                        "rollout transition patch",
                    ),
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
    _require_rollout_transition_patch_reverse_applicable(root)
    print(f"strict CUDA stage-order release gate accepted -> {final_path}")
    return 0


# ------------------------------------------------------------------------ driver


def validate_cell_artifact_path(
    record: Mapping[str, Any],
    *,
    kind: str,
    expected: Path,
) -> ValidatedArtifact | None:
    """Bind array-producing cells to the exact parent-selected NPZ path."""

    expected_path = Path(expected)
    if not expected_path.is_absolute():
        raise QualificationError("expected cell artifact path must be absolute")
    required = kind in ARRAY_CELL_KINDS
    raw = record.get("artifact")
    if raw is None:
        if required or any(
            key in record for key in ("artifact_bytes", "artifact_sha256")
        ):
            raise QualificationError(
                f"qualification cell {kind} omitted its NPZ artifact"
            )
        return None
    if not required:
        raise QualificationError(
            f"qualification cell {kind} produced an unexpected NPZ artifact"
        )
    observed = _require_bounded_absolute_path(raw, "cell NPZ artifact path")
    if observed != expected_path:
        raise QualificationError(
            "qualification cell redirected its NPZ artifact: "
            f"{observed} != {expected_path}"
        )
    expected_bytes = _require_exact_json_int(
        record.get("artifact_bytes"),
        "cell NPZ artifact bytes",
        minimum=1,
    )
    if expected_bytes > CELL_MAX_NPZ_BYTES:
        raise QualificationError("cell NPZ artifact exceeds its byte limit")
    expected_sha256 = _require_sha256(
        record.get("artifact_sha256"),
        "cell NPZ artifact digest",
    )
    encoded = _read_bounded_regular_bytes(
        observed,
        maximum_bytes=CELL_MAX_NPZ_BYTES,
        label="cell NPZ artifact",
    )
    if len(encoded) != expected_bytes:
        raise QualificationError("cell NPZ artifact byte count drifted")
    observed_sha256 = hashlib.sha256(encoded).hexdigest()
    if observed_sha256 != expected_sha256:
        raise QualificationError("cell NPZ artifact bytes drifted")
    return ValidatedArtifact(
        path=observed,
        encoded=encoded,
        sha256=observed_sha256,
    )


def _invalidate_cell_artifacts(*paths: Path) -> None:
    """Remove fixed-name artifacts before a child may publish fresh evidence."""

    for path in paths:
        path = Path(path)
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise QualificationError(
                f"cannot inspect stale qualification cell artifact {path}: {exc}"
            ) from exc
        if stat.S_ISDIR(metadata.st_mode):
            raise QualificationError(
                f"qualification cell artifact path is a directory: {path}"
            )
        try:
            path.unlink()
        except OSError as exc:
            raise QualificationError(
                f"cannot invalidate stale qualification cell artifact {path}: {exc}"
            ) from exc


def _run_worker(
    args: argparse.Namespace,
    *,
    kind: str,
    name: str,
    cudagraphs: int,
    output: Path,
    run_nonce: str,
    cell_nonce: str,
) -> dict[str, Any]:
    run_nonce = _require_sha256(run_nonce, "qualification run nonce")
    cell_nonce = _require_sha256(cell_nonce, "qualification cell nonce")
    python = (
        Path(args.python).expanduser().absolute()
        if args.python
        else (Path(args.puffer_root).resolve() / ".venv" / "bin" / "python")
    )
    # Absolute, not resolved: resolving a venv's python symlink escapes the venv.
    if not python.is_file():
        raise QualificationError(f"Puffer Python is missing: {python}")
    output_root = Path(output).resolve()
    json_path = output_root / f"{name}.json"
    npz_path = output_root / f"{name}.npz"
    _invalidate_cell_artifacts(json_path, npz_path)
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
        "--run-nonce",
        run_nonce,
        "--cell-nonce",
        cell_nonce,
        "--output-json",
        str(json_path),
        "--output-npz",
        str(npz_path),
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
    record, record_artifact = _read_json_artifact(
        json_path,
        maximum_bytes=CELL_MAX_JSON_BYTES,
        label=f"qualification cell {name} JSON artifact",
    )
    reserved_record_keys = {
        "record_path",
        "record_bytes",
        "record_sha256",
        "_artifact_arrays",
    }
    if reserved_record_keys & set(record):
        raise QualificationError(
            f"qualification cell {name} spoofed parent-owned record metadata"
        )
    if (
        _require_exact_json_int(
            record.get("schema_version"),
            f"qualification cell {name} schema",
        )
        != SCHEMA_VERSION
    ):
        raise QualificationError(f"qualification cell {name} schema differs")
    if record.get("accepted") is not True:
        raise QualificationError(f"qualification cell {name} is not accepted")
    if record.get("run_nonce") != run_nonce:
        raise QualificationError(
            f"qualification cell {name} run nonce differs"
        )
    if record.get("cell_nonce") != cell_nonce:
        raise QualificationError(
            f"qualification cell {name} nonce differs"
        )
    validate_rollout_transition_patch_identity(
        record.get("patch_identity"),
        expected_puffer_root=Path(args.puffer_root),
        rehash_files=True,
    )
    validate_cell_cudagraph_record(record, expected=cudagraphs)
    expected_config = _expected_cell_config(
        kind,
        cudagraphs,
        args,
        Path(args.puffer_root),
    )
    if record.get("config") != expected_config:
        raise QualificationError(
            f"qualification cell {name} config differs from parent request"
        )
    if kind in TRANSITION_CELL_KINDS:
        validate_transition_cell_integrity(record, kind)
        validate_graph_execution_evidence(
            record.get("graph_execution"),
            expected_cudagraphs=cudagraphs,
            expected_workload=kind,
            expected_counts=_expected_graph_execution_counts(
                kind,
                record["config"],
                record,
                args,
            ),
        )
        if kind == "throughput":
            throughput_payload = record.get("throughput")
            if not isinstance(throughput_payload, Mapping):
                raise QualificationError(
                    "throughput cell payload is missing"
                )
            if throughput_payload.get("config") != record["config"]:
                raise QualificationError(
                    "throughput payload config differs from parent request"
                )
            expected_discards = (
                _int(
                    args.throughput_warmup_rollouts,
                    "throughput warmup rollouts",
                    minimum=0,
                )
                + _int(
                    args.throughput_timed_rollouts,
                    "throughput timed rollouts",
                    minimum=1,
                )
            )
            if (
                _int(
                    throughput_payload.get(
                        "tail_records_explicitly_discarded"
                    ),
                    "throughput tail discard count",
                    minimum=1,
                )
                != expected_discards
            ):
                raise QualificationError(
                    "throughput tail discard count differs from executed "
                    "warmup/timed rollouts"
                )
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
    artifact_path = validate_cell_artifact_path(
        record, kind=kind, expected=npz_path
    )
    artifact_arrays = (
        _read_npz(artifact_path) if artifact_path is not None else None
    )
    if kind == "rollout":
        if artifact_arrays is None:  # pragma: no cover - closed by path validator
            raise QualificationError("rollout cell has no bound NPZ artifact")
        identity = record.get("identity")
        if not isinstance(identity, Mapping):
            raise QualificationError("rollout cell module identity is missing")
        precision = _int(
            identity.get("precision_bytes"),
            "rollout cell precision bytes",
            minimum=1,
        )
        if precision not in GRAPH_ATOL_BY_PRECISION:
            raise QualificationError("rollout cell precision is unsupported")
        cuda_oracle = validate_cuda_advantage_oracle_evidence(
            record.get("cuda_advantage_oracle"),
            rehash_files=True,
        )
        validate_heterogeneous_policy_evidence(
            record,
            artifact_arrays,
            atol=GRAPH_ATOL_BY_PRECISION[precision],
        )
        integrated = validate_integrated_advantage_oracle(
            _heterogeneous_namespace(
                artifact_arrays,
                HETEROGENEOUS_ZERO_PREFIX,
            ),
            record.get("heterogeneous_zero_state", {}),
            record.get("config", {}),
            atol=RATIO_ATOL_BY_PRECISION[precision],
        )
        if (
            integrated["verifier_path"] != cuda_oracle["verifier_path"]
            or integrated["verifier_sha256"] != cuda_oracle["verifier_sha256"]
        ):
            raise QualificationError(
                "synthetic and integrated advantage oracles used different "
                "verifier bytes"
            )
        if record.get("integrated_advantage_oracle") != integrated:
            raise QualificationError(
                "worker integrated advantage oracle summary differs"
            )
    record["record_path"] = str(json_path)
    record["record_bytes"] = len(record_artifact.encoded)
    record["record_sha256"] = record_artifact.sha256
    record["_artifact_arrays"] = artifact_arrays
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


def _require_same_patch_identity(
    records: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    records = list(records)
    if not records:
        raise QualificationError("no cell patch identities were supplied")
    reference = records[0].get("patch_identity")
    validated = validate_rollout_transition_patch_identity(reference)
    for record in records[1:]:
        if record.get("patch_identity") != reference:
            raise QualificationError(
                "rollout transition patch identity drifted between cells"
            )
    return validated


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


def _with_qualification_output_lock(function):
    """Serialize writers that target the same qualification output directory."""

    @functools.wraps(function)
    def locked(args: argparse.Namespace) -> int:
        output = Path(args.output).resolve()
        if output.exists() and not output.is_dir():
            raise QualificationError(
                f"qualification output is not a directory: {output}"
            )
        output.mkdir(parents=True, exist_ok=True)
        lock_path = output / ".qualification.lock"
        flags = os.O_RDWR | os.O_CREAT
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise QualificationError(
                f"cannot open qualification output lock {lock_path}: {exc}"
            ) from exc
        with os.fdopen(descriptor, "r+b", closefd=True) as lock:
            metadata = os.fstat(lock.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise QualificationError(
                    f"qualification output lock is not regular: {lock_path}"
                )
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise QualificationError(
                    f"another qualification writer holds {lock_path}"
                ) from exc
            try:
                return function(args)
            finally:
                fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    return locked


@_with_qualification_output_lock
def _invalidate_receipt_after_run_parse_failure(args: argparse.Namespace) -> int:
    """Invalidate an identifiable prior verdict when full CLI parsing fails."""

    output = Path(args.output).resolve()
    write_bounded_json_atomic(
        output / "QUALIFICATION.json",
        {
            "schema_version": SCHEMA_VERSION,
            "qualification_only": True,
            "accepted": False,
            "status": "argument_parse_failed",
            "run_nonce": secrets.token_hex(32),
        },
        maximum_bytes=FINAL_MAX_JSON_BYTES,
    )
    return 0


def _unparsed_run_output(argv: Iterable[str]) -> Path | None:
    """Recover argparse's final explicit run output without parsing other fields."""

    arguments = list(argv)
    if not arguments or arguments[0] != "run":
        return None
    observed: list[str] = []
    for index, argument in enumerate(arguments[1:], 1):
        if (
            argument == "--output"
            and index + 1 < len(arguments)
            and not arguments[index + 1].startswith("-")
        ):
            observed.append(arguments[index + 1])
        elif argument.startswith("--output="):
            observed.append(argument.partition("=")[2])
    if not observed or not observed[-1]:
        return None
    try:
        return Path(observed[-1])
    except (TypeError, ValueError):
        return None


@_with_qualification_output_lock
def run_qualification(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    final_path = output / "QUALIFICATION.json"
    run_nonce = secrets.token_hex(32)
    in_progress = {
        "schema_version": SCHEMA_VERSION,
        "qualification_only": True,
        "accepted": False,
        "status": "in_progress",
        "run_nonce": run_nonce,
    }
    output_existed = output.exists()
    if output_existed:
        if not output.is_dir():
            raise QualificationError(
                f"qualification output is not a directory: {output}"
            )
        write_bounded_json_atomic(
            final_path,
            in_progress,
            maximum_bytes=FINAL_MAX_JSON_BYTES,
        )
    if args.ratio_call_limit <= 0:
        raise QualificationError("ratio call limit must be positive")
    if (
        args.throughput_warmup_rollouts < 0
        or args.throughput_timed_rollouts <= 0
    ):
        raise QualificationError("throughput rollout counts are invalid")
    validate_throughput_minibatch(
        args.throughput_agents,
        args.throughput_horizon,
        args.throughput_minibatch_size,
    )
    limit = _num(
        args.max_regression_fraction,
        "throughput regression fraction",
    )
    if limit < 0 or limit >= 1:
        raise QualificationError(
            "throughput regression fraction must be in [0, 1)"
        )
    baseline_throughput, baseline_identity, baseline_encoded = (
        _load_required_throughput_baseline_binding(
            args.baseline_throughput,
            output=output,
        )
    )
    output.mkdir(parents=True, exist_ok=True)
    if not output_existed:
        write_bounded_json_atomic(
            final_path,
            in_progress,
            maximum_bytes=FINAL_MAX_JSON_BYTES,
        )
    records: list[dict[str, Any]] = []

    def cell(kind: str, name: str, cudagraphs: int = DEFAULT_CUDAGRAPH_WARMUP_EPOCHS):
        cell_nonce = secrets.token_hex(32)
        record = _run_worker(
            args,
            kind=kind,
            name=name,
            cudagraphs=cudagraphs,
            output=output,
            run_nonce=run_nonce,
            cell_nonce=cell_nonce,
        )
        records.append(record)
        _require_same_identity(records)
        _require_same_patch_identity(records)
        return record

    def cell_arrays(record: Mapping[str, Any]) -> dict[str, np.ndarray]:
        arrays = record.get("_artifact_arrays")
        if not isinstance(arrays, dict) or any(
            not isinstance(value, np.ndarray) for value in arrays.values()
        ):
            raise QualificationError("retained array cell omitted its artifact")
        return arrays

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
    patch_identity = _require_same_patch_identity(records)
    atol = GRAPH_ATOL_BY_PRECISION[int(identity["precision_bytes"])]
    off_arrays = cell_arrays(graph_off)
    on_arrays = cell_arrays(graph_on)
    off_zero_arrays = _heterogeneous_namespace(
        off_arrays, HETEROGENEOUS_ZERO_PREFIX
    )
    on_zero_arrays = _heterogeneous_namespace(
        on_arrays, HETEROGENEOUS_ZERO_PREFIX
    )
    graph_total_agents = int(graph_off["config"]["vec"]["total_agents"])
    graph_buffers = int(graph_off["config"]["vec"]["num_buffers"])
    off_heterogeneous = validate_heterogeneous_policy_evidence(
        graph_off, off_arrays, atol=atol
    )
    on_heterogeneous = validate_heterogeneous_policy_evidence(
        graph_on, on_arrays, atol=atol
    )
    if graph_off.get("heterogeneous_policy") != graph_on.get(
        "heterogeneous_policy"
    ):
        raise QualificationError(
            "heterogeneous architecture/donor identity differs across graph modes"
        )
    gates["graph_parity"] = {
        "accepted": True,
        "graph_off_execution": graph_off["graph_execution"],
        "graph_on_execution": graph_on["graph_execution"],
        "atol": atol,
        "snapshot_max_abs": compare_snapshots(off_arrays, on_arrays, atol=atol),
        "decoder_max_abs": compare_decoder_outputs(off_arrays, on_arrays, atol=atol),
        "tail_snapshot_max_abs": compare_tail_snapshots(
            off_arrays,
            on_arrays,
            total_agents=graph_total_agents,
            num_buffers=graph_buffers,
            atol=atol,
        ),
        "tail_decoder_max_abs": compare_tail_decoder_outputs(
            off_arrays,
            on_arrays,
            atol=atol,
        ),
        "graph_off_tail_routing_max_abs": validate_tail_value_routing(
            off_arrays,
            total_agents=graph_total_agents,
            num_buffers=graph_buffers,
            atol=atol,
        ),
        "graph_on_tail_routing_max_abs": validate_tail_value_routing(
            on_arrays,
            total_agents=graph_total_agents,
            num_buffers=graph_buffers,
            atol=atol,
        ),
        "zero_value_snapshot_max_abs": compare_snapshots(
            off_zero_arrays, on_zero_arrays, atol=atol
        ),
        "zero_value_decoder_max_abs": compare_decoder_outputs(
            off_zero_arrays, on_zero_arrays, atol=atol
        ),
        "zero_value_tail_snapshot_max_abs": compare_tail_snapshots(
            off_zero_arrays,
            on_zero_arrays,
            total_agents=graph_total_agents,
            num_buffers=graph_buffers,
            atol=atol,
        ),
        "zero_value_tail_decoder_max_abs": compare_tail_decoder_outputs(
            off_zero_arrays,
            on_zero_arrays,
            atol=atol,
        ),
        "heterogeneous_donor_identity_equal": True,
    }
    off_cuda_oracle = validate_cuda_advantage_oracle_evidence(
        graph_off.get("cuda_advantage_oracle"),
        rehash_files=True,
    )
    on_cuda_oracle = validate_cuda_advantage_oracle_evidence(
        graph_on.get("cuda_advantage_oracle"),
        rehash_files=True,
    )
    if off_cuda_oracle != on_cuda_oracle:
        raise QualificationError(
            "synthetic CUDA advantage evidence differs across graph cells"
        )
    integrated_atol = RATIO_ATOL_BY_PRECISION[
        int(identity["precision_bytes"])
    ]
    off_integrated = validate_integrated_advantage_oracle(
        off_zero_arrays,
        graph_off.get("heterogeneous_zero_state", {}),
        graph_off.get("config", {}),
        atol=integrated_atol,
    )
    on_integrated = validate_integrated_advantage_oracle(
        on_zero_arrays,
        graph_on.get("heterogeneous_zero_state", {}),
        graph_on.get("config", {}),
        atol=integrated_atol,
    )
    if graph_off.get("integrated_advantage_oracle") != off_integrated:
        raise QualificationError(
            "graph-off integrated advantage summary differs"
        )
    if graph_on.get("integrated_advantage_oracle") != on_integrated:
        raise QualificationError(
            "graph-on integrated advantage summary differs"
        )
    integrated_primary, _ = derive_row_partition(
        graph_off.get("heterogeneous_zero_state", {}),
        total_agents=graph_total_agents,
    )
    integrated_parity = compare_integrated_advantage_parity(
        off_zero_arrays["advantages_after_train"],
        on_zero_arrays["advantages_after_train"],
        primary_rows=integrated_primary,
        horizon=HETEROGENEOUS_HORIZON,
        atol=integrated_atol,
    )
    if not np.array_equal(
        off_zero_arrays["selected_rows_after_train"],
        on_zero_arrays["selected_rows_after_train"],
    ):
        raise QualificationError(
            "graph modes selected different learner rows for the integrated train"
        )
    gates["cuda_advantage_oracle"] = {
        "accepted": True,
        "synthetic": {
            "graph_off": off_cuda_oracle,
            "graph_on": on_cuda_oracle,
            "same_evidence": True,
        },
        "integrated": {
            "graph_off": off_integrated,
            "graph_on": on_integrated,
            "graph_mode_parity": integrated_parity,
            "selected_rows_equal": True,
        },
    }

    auto = cell("terminal_auto", "terminal-auto")
    control = cell("terminal_control", "terminal-control")
    validate_nonzero_state(
        auto["state_after_first_rollout"], expected_banks=2, expected_buffers=1
    )
    validate_zero_state(
        control["state_after_control_clear"], expected_banks=2, expected_buffers=1
    )
    auto_arrays = cell_arrays(auto)
    control_arrays = cell_arrays(control)
    gates["terminal_reset"] = {
        "accepted": True,
        "automatic_execution": auto["graph_execution"],
        "control_execution": control["graph_execution"],
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
    ratio_arrays = cell_arrays(ratio)
    validate_weight_identity(
        ratio["weights_before_sha256"], ratio["weights_after_sha256"]
    )
    ratio_call_count = _int(
        ratio.get("ratio_calls"),
        "ratio call count",
        minimum=1,
    )
    ratio_horizon = _int(
        ratio["config"]["train"]["horizon"],
        "ratio horizon",
        minimum=1,
    )
    ratio_total_agents = _int(
        ratio["config"]["vec"]["total_agents"],
        "ratio total agents",
        minimum=1,
    )
    ratio_buffers = _int(
        ratio["config"]["vec"]["num_buffers"],
        "ratio buffers",
        minimum=1,
    )
    frozen_advantage_evidence: list[dict[str, Any]] = []
    ratio_tail_evidence: list[dict[str, Any]] = []
    for index in range(ratio_call_count):
        tail_snapshot = {
            key: ratio_arrays[f"{key}_{index}"]
            for key in (*TAIL_FLOAT_SNAPSHOT_FIELDS, "tail_valid")
        }
        suffix = f"_attempt_{index}"
        for key, value in ratio_arrays.items():
            if key.startswith("tail_decoder_bank_") and key.endswith(suffix):
                tail_snapshot[key[: -len(suffix)]] = value
        tail_summary = validate_tail_snapshot(
            tail_snapshot,
            total_agents=ratio_total_agents,
            num_buffers=ratio_buffers,
        )
        routing = validate_tail_value_routing(
            tail_snapshot,
            total_agents=ratio_total_agents,
            num_buffers=ratio_buffers,
            atol=atol,
        )
        validate_tail_validity(
            ratio_arrays[f"tail_valid_after_train_{index}"],
            num_buffers=ratio_buffers,
            expected=0,
            label="post-train tail",
        )
        ratio_tail_evidence.append(
            {
                **tail_summary,
                "routing_max_abs": routing,
                "consumed_after_train": True,
            }
        )
        frozen_advantage_evidence.append(
            validate_frozen_advantages(
                ratio_arrays[f"advantages_{index}"],
                primary_rows=primary_rows,
                frozen_rows=frozen_rows,
                horizon=ratio_horizon,
            )
        )
    if not any(
        evidence["primary_max_abs"] > 0.0
        for evidence in frozen_advantage_evidence
    ):
        raise QualificationError(
            "learner advantages are all zero across every ratio attempt"
        )
    gates["ratio"] = {
        "accepted": True,
        "graph_execution": ratio["graph_execution"],
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
                for index in range(ratio_call_count)
            ],
            primary_rows=primary_rows,
            frozen_rows=frozen_rows,
            atol=RATIO_ATOL_BY_PRECISION[int(identity["precision_bytes"])],
        ),
        "weights_sha256": ratio["weights_before_sha256"],
        "tail_attempts": ratio_tail_evidence,
        "frozen_advantages": frozen_advantage_evidence,
    }
    if not all(
        evidence["frozen_rows_zero"] == sorted(frozen_rows)
        for evidence in frozen_advantage_evidence
    ):
        raise QualificationError(
            "heterogeneous frozen-policy gate is not linked to ratio masking"
        )
    gates["heterogeneous_frozen_policy"] = {
        "accepted": True,
        "graph_off": off_heterogeneous,
        "graph_on": on_heterogeneous,
        "same_donor_bytes_across_graph_modes": True,
        "ratio_frozen_rows_zero": sorted(frozen_rows),
        "ratio_attempts": len(frozen_advantage_evidence),
    }

    throughput_cell = cell("throughput", "throughput")
    throughput = throughput_cell["throughput"]
    _require_same_cuda_runtime(records)
    _validate_throughput_record(throughput, "candidate")
    gates["throughput"] = {
        "accepted": True,
        "graph_execution": throughput_cell["graph_execution"],
        "steps_per_second": throughput["steps_per_second"],
        "baseline_artifact": baseline_identity,
        **validate_throughput(
            throughput,
            baseline_throughput,
            max_regression_fraction=limit,
        ),
    }
    final_baseline_encoded = _read_bounded_regular_bytes(
        Path(baseline_identity["path"]),
        maximum_bytes=CELL_MAX_JSON_BYTES,
        label="throughput baseline artifact final recheck",
    )
    if (
        final_baseline_encoded != baseline_encoded
        or len(final_baseline_encoded) != baseline_identity["bytes"]
        or hashlib.sha256(final_baseline_encoded).hexdigest()
        != baseline_identity["sha256"]
    ):
        raise QualificationError(
            "throughput baseline artifact changed during qualification"
        )

    for record in records:
        current_record = _read_bounded_regular_bytes(
            Path(record["record_path"]),
            maximum_bytes=CELL_MAX_JSON_BYTES,
            label=f"qualification cell {record['kind']} final JSON recheck",
        )
        if (
            len(current_record) != record["record_bytes"]
            or hashlib.sha256(current_record).hexdigest()
            != record["record_sha256"]
        ):
            raise QualificationError(
                f"qualification cell {record['kind']} JSON artifact drifted"
            )
        if record.get("artifact") is not None:
            current_npz = _read_bounded_regular_bytes(
                Path(record["artifact"]),
                maximum_bytes=CELL_MAX_NPZ_BYTES,
                label=f"qualification cell {record['kind']} final NPZ recheck",
            )
            if (
                len(current_npz) != record["artifact_bytes"]
                or hashlib.sha256(current_npz).hexdigest()
                != record["artifact_sha256"]
            ):
                raise QualificationError(
                    f"qualification cell {record['kind']} NPZ artifact drifted"
                )

    final = {
        "schema_version": SCHEMA_VERSION,
        "qualification_only": True,
        "run_nonce": run_nonce,
        "identity": identity,
        "patch_identity": patch_identity,
        "cuda_runtime_preflight": records[0]["cuda_runtime_preflight"],
        "host": socket.gethostname(),
        "gates": gates,
        "throughput": throughput,
        "throughput_baseline": baseline_identity,
        "cells": [
            {
                "name": Path(record["record_path"]).stem,
                "kind": record["kind"],
                "cell_nonce": record["cell_nonce"],
                "record": record["record_path"],
                "record_bytes": record["record_bytes"],
                "record_sha256": record["record_sha256"],
                "artifact": record.get("artifact"),
                "artifact_bytes": record.get("artifact_bytes"),
                "artifact_sha256": record.get("artifact_sha256"),
            }
            for record in records
        ],
        **combine_gate_verdicts(gates),
    }
    write_bounded_json_atomic(
        final_path,
        final,
        maximum_bytes=FINAL_MAX_JSON_BYTES,
    )
    print(
        f"qualification accepted={final['accepted']} "
        f"steps_per_second={throughput['steps_per_second']:.1f} "
        f"-> {final_path}"
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
    parser.add_argument("--throughput-layers", type=int, default=3)
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
        required=True,
        help="external bounded JSON throughput artifact (diagnostic only)",
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
    cell.add_argument("--run-nonce", required=True)
    cell.add_argument("--cell-nonce", required=True)
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
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        args = parse_args(raw_argv)
    except SystemExit as exc:
        if exc.code not in (None, 0):
            output = _unparsed_run_output(raw_argv)
            if output is not None:
                _invalidate_receipt_after_run_parse_failure(
                    argparse.Namespace(output=output)
                )
        raise
    if args.command == "strict-stage-order":
        return run_strict_stage_order(args)
    if args.command == "strict-stage-worker":
        return run_strict_stage_worker(args)
    if args.command == "cell":
        if args.ratio_call_limit <= 0:
            raise QualificationError("ratio call limit must be positive")
        if (
            args.throughput_warmup_rollouts < 0
            or args.throughput_timed_rollouts <= 0
        ):
            raise QualificationError("throughput rollout counts are invalid")
        validate_throughput_minibatch(
            args.throughput_agents,
            args.throughput_horizon,
            args.throughput_minibatch_size,
        )
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
