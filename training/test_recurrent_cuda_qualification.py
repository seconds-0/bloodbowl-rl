"""Contracts for the recurrent CUDA qualification smoke test.

Every test here maps to a bug this repo actually hit: recurrent state that was
not zero at construction, cudagraph capture that diverged from the graph-off
path, PPO sampling frozen rows at prio_alpha=0, a compiled module whose obs ABI
did not match its source tree, reward counters that were silently absent rather
than zero, and a CUDA runtime that reported no device because `_C` was imported
before the first CUDART call.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import os
import pathlib
import re
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from tools import puffer_cuda_runtime as cuda_runtime


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_recurrent_cuda_qualification.patch"
PRIO_PATCH = ROOT / "training" / "puffer_frozen_prio_mask.patch"
LEAGUE_PATCH = ROOT / "training" / "selfplay_league.patch"
STRICT_CONFIG_PATCH = (
    ROOT / "training" / "puffer_strict_environment_config.patch"
)
ROLLOUT_TRANSITION_PATCH = (
    ROOT / "training" / "puffer_rollout_transition_closure.patch"
)
ENTROPY_SCHEDULE_PATCH = (
    ROOT / "training" / "puffer_entropy_schedule_parity.patch"
)
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
RUNNER = ROOT / "tools" / "qualify_recurrent_cuda.py"
CUDA_RUNTIME_WRAPPER = ROOT / "tools" / "puffer_cuda_runtime.py"
COMPILED_BACKEND_LEDGER = (
    ROOT / "training" / "puffer_compiled_backend_sources.txt"
)
TEST_RUN_NONCE = "a" * 64
TEST_CELL_NONCE = "b" * 64
ENTROPY_SCHEDULE_CONTRACT = (
    "cosine-update-index-over-total-updates-fp32-v1"
)
ENTROPY_TELEMETRY_CONTRACT = "direct-device-coefficient-loss-decomposition-v1"
ENTROPY_GRADIENT_CONTRACT = "ppo-entropy-preclip-gradient-v1"
ENTROPY_OVERRUN_STATE_CONTRACT = "entropy-overrun-state-v1"
ENTROPY_SCHEDULE_CELL_KINDS = (
    "entropy_native_eager_annealed",
    "entropy_native_graph_annealed",
    "entropy_native_graph_anneal_disabled",
    "entropy_torch_annealed",
    "entropy_torch_anneal_disabled",
)
ENTROPY_GRADIENT_CONTROL_CELL_KINDS = (
    "entropy_native_eager_anneal_disabled",
)
ENTROPY_QUALIFICATION_CELL_KINDS = (
    *ENTROPY_SCHEDULE_CELL_KINDS,
    *ENTROPY_GRADIENT_CONTROL_CELL_KINDS,
)
ENTROPY_RAW_ARRAY_FIELDS = (
    "update_index",
    "device_coefficient",
    "host_coefficient",
    "policy_loss",
    "value_loss",
    "entropy",
    "signed_entropy_term",
    "total_loss",
    "loss_count",
)


def entropy_schedule_descriptor(*, enabled: bool = True) -> dict:
    base = 0.5
    min_ratio = 0.1
    total_updates = 20
    floor = base * min_ratio

    def coefficient(update_index: int) -> float:
        if not enabled:
            return base
        progress = min(1.0, max(0.0, update_index / total_updates))
        return floor + 0.5 * (base - floor) * (
            1.0 + math.cos(math.pi * progress)
        )

    return {
        "base": base,
        "enabled": enabled,
        "min_ratio": min_ratio,
        "total_updates": total_updates,
        "first_coefficient": coefficient(0),
        "last_legal_coefficient": coefficient(total_updates - 1),
        "floor_coefficient": floor,
        "contract": ENTROPY_SCHEDULE_CONTRACT,
    }


def entropy_raw_evidence(kind: str) -> tuple[dict, dict[str, np.ndarray]]:
    enabled = kind not in {
        "entropy_native_graph_anneal_disabled",
        "entropy_torch_anneal_disabled",
        *ENTROPY_GRADIENT_CONTROL_CELL_KINDS,
    }
    descriptor = entropy_schedule_descriptor(enabled=enabled)
    total_updates = descriptor["total_updates"]
    update_index = np.arange(total_updates, dtype=np.int64)
    if enabled:
        floor = descriptor["floor_coefficient"]
        base = descriptor["base"]
        coefficients = np.asarray(
            [
                floor
                + 0.5
                * (base - floor)
                * (1.0 + math.cos(math.pi * int(index) / total_updates))
                for index in update_index
            ],
            dtype=np.float32,
        )
    else:
        coefficients = np.full(
            total_updates,
            descriptor["base"],
            dtype=np.float32,
        )
    entropy = np.linspace(0.75, 1.5, total_updates, dtype=np.float32)
    policy = np.linspace(0.1, 0.2, total_updates, dtype=np.float32)
    value = np.linspace(0.2, 0.4, total_updates, dtype=np.float32)
    vf_coef = np.float32(0.5)
    signed_entropy = -coefficients * entropy
    total = policy + vf_coef * value + signed_entropy
    arrays = {
        "update_index": update_index,
        "device_coefficient": coefficients,
        "host_coefficient": coefficients.copy(),
        "policy_loss": policy,
        "value_loss": value,
        "entropy": entropy,
        "signed_entropy_term": signed_entropy,
        "total_loss": total,
        "loss_count": np.ones(total_updates, dtype=np.int64),
    }
    evidence = {
        "kind": kind,
        "telemetry_contract": ENTROPY_TELEMETRY_CONTRACT,
        "schedule": descriptor,
        "vf_coef": float(vf_coef),
        "weights_before_sha256": "c" * 64,
        "weights_after_sha256": "c" * 64,
        "raw_array_fields": list(ENTROPY_RAW_ARRAY_FIELDS),
    }
    return evidence, arrays


def entropy_execution_evidence(
    runner,
    kind: str,
) -> tuple[dict, dict, dict[str, np.ndarray]]:
    """Build ordinary execution evidence with backend-owned NPZ fields."""

    native = kind in runner.ENTROPY_NATIVE_CELL_KINDS
    total = runner.ENTROPY_SCHEDULE_TOTAL_UPDATES
    total_agents = 2
    buffers = 1
    horizon = 2
    quantum = total_agents * horizon
    config = {
        "vec": {
            "total_agents": total_agents,
            "num_buffers": buffers,
        },
        "train": {
            "horizon": horizon,
            "total_timesteps": total * quantum,
            "minibatch_size": quantum,
            "replay_ratio": 1,
            "learning_rate": 0.0,
            "ent_coef": runner.ENTROPY_SCHEDULE_BASE,
            "min_ent_coef_ratio": runner.ENTROPY_SCHEDULE_MIN_RATIO,
            "anneal_ent_coef": runner._entropy_schedule_enabled(kind),
            "vf_coef": 0.5,
        },
    }
    mode = (
        "eager"
        if kind
        in {
            "entropy_native_eager_annealed",
            "entropy_native_eager_anneal_disabled",
            *runner.ENTROPY_TORCH_CELL_KINDS,
        }
        else "graph"
    )
    execution = {
        "kind": kind,
        "backend": "native" if native else "torch",
        "mode": mode,
        "update_count": total,
        "rollout_count": total,
        "train_count": total,
        "log_count": total,
        "rollout_quantum": quantum,
        "hard_integrity_intervals": [
            {key: 0.0 for key in runner.HARD_INTEGRITY_KEYS}
            for _ in range(total)
        ],
    }
    before = np.arange(total, dtype=np.int64) * np.int64(quantum)
    arrays = {
        "global_step_before": before,
        "global_step_after": before + np.int64(quantum),
        "tail_valid_before_train": np.full(
            total,
            buffers,
            dtype=np.int64,
        ),
        "tail_valid_after_train": np.zeros(total, dtype=np.int64),
    }
    if native:
        arrays.update(
            {
                name: np.zeros(total, dtype=np.int64)
                for name in runner.ENTROPY_NATIVE_EXECUTION_COUNTER_ARRAY_FIELDS
            }
        )
        prefix = "graph" if mode == "graph" else "eager"
        arrays[f"{prefix}_rollout_delta"][:] = horizon * buffers
        arrays[f"{prefix}_tail_delta"][:] = buffers
        arrays[f"{prefix}_train_delta"][:] = 1
    return execution, config, arrays


def entropy_overrun_evidence(
    runner,
    kind: str,
) -> tuple[dict, dict, dict[str, np.ndarray]]:
    """Build closed evidence for a rejected public train call at e=N."""

    native = kind in runner.ENTROPY_NATIVE_CELL_KINDS
    _, arrays = entropy_raw_evidence(kind)
    total = runner.ENTROPY_SCHEDULE_TOTAL_UPDATES
    total_agents = 2
    horizon = 3
    config = {
        "vec": {
            "total_agents": total_agents,
            "num_buffers": 2,
        },
        "policy": {
            "hidden_size": runner.HETEROGENEOUS_PRIMARY_HIDDEN_SIZE,
            "num_layers": runner.HETEROGENEOUS_PRIMARY_NUM_LAYERS,
        },
        "train": {
            "horizon": horizon,
            "learning_rate": 0.0,
            "anneal_lr": False,
            "minibatch_size": total_agents * horizon,
            "replay_ratio": 1,
            "total_timesteps": total * total_agents * horizon,
        },
    }
    hidden = config["policy"]["hidden_size"]
    layers = config["policy"]["num_layers"]
    output_size = runner.BLOODBOWL_ACTION_LOGITS + 1
    parameter_count = (
        runner.BLOODBOWL_INPUT_SIZE * hidden
        + output_size * hidden
        + layers * 3 * hidden * hidden
    )
    master = np.linspace(
        -1.0,
        1.0,
        parameter_count,
        dtype=np.float32,
    )
    momentum = (master * np.float32(0.5) + np.float32(0.125)).astype(
        np.float32
    )

    def tensor_metadata(name, value, *, expose_values):
        value = np.asarray(value, dtype=np.float32)
        payload = value.tobytes(order="C")
        return {
            "name": name,
            "dtype": "f32",
            "shape": list(value.shape),
            "present": True,
            "elements": int(value.size),
            "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(),
            "nonzero": int(np.count_nonzero(value)),
            "nonfinite": int(np.count_nonzero(~np.isfinite(value))),
            "values": value.tolist() if expose_values else None,
        }

    native_snapshot = None
    weights_digest = "a" * 64
    if native:
        applied = np.float32(arrays["device_coefficient"][-1])
        last_loss = np.float32(arrays["total_loss"][-1])
        tensors = {
            "device_entropy_coefficient": tensor_metadata(
                "device_entropy_coefficient",
                np.asarray((applied,), dtype=np.float32),
                expose_values=True,
            ),
            "loss_accumulator": tensor_metadata(
                "loss_accumulator",
                np.zeros(10, dtype=np.float32),
                expose_values=True,
            ),
            "scalar_loss": tensor_metadata(
                "scalar_loss",
                np.asarray((last_loss,), dtype=np.float32),
                expose_values=True,
            ),
            "master_weights": tensor_metadata(
                "master_weights",
                master,
                expose_values=False,
            ),
            "optimizer_momentum": tensor_metadata(
                "optimizer_momentum",
                momentum,
                expose_values=False,
            ),
            "optimizer_learning_rate": tensor_metadata(
                "optimizer_learning_rate",
                np.zeros(1, dtype=np.float32),
                expose_values=True,
            ),
            "optimizer_learning_rate_derived": tensor_metadata(
                "optimizer_learning_rate_derived",
                np.zeros(2, dtype=np.float32),
                expose_values=True,
            ),
        }
        used = sum(tensor["bytes"] for tensor in tensors.values())
        state = {
            "contract": ENTROPY_OVERRUN_STATE_CONTRACT,
            "max_bytes": runner.QUALIFICATION_POLICY_MAX_BYTES,
            "used_bytes": used,
            "host": {
                "epoch": total,
                "global_step": total * total_agents * horizon,
                "training_failed": False,
                "current_ent_coef": float(applied),
                "current_ent_epoch": total - 1,
                "entropy_schedule_update_count": 0,
                "entropy_loss_minibatch_count": 0,
                "entropy_first_update": -1,
                "entropy_last_update": -1,
                "entropy_first_coefficient": 0.0,
                "entropy_last_coefficient": 0.0,
                "entropy_schedule_valid": False,
                "defer_entropy_schedule_commit": False,
                "entropy_schedule_commit_pending": False,
                "pending_entropy_update": -1,
                "pending_entropy_minibatches": 0,
                "pending_entropy_coefficient": 0.0,
            },
            "tensors": tensors,
        }
        native_snapshot = {
            "before": state,
            "after": json.loads(json.dumps(state)),
        }
        for boundary in ("before", "after"):
            arrays[f"overrun_state_{boundary}_master_weights"] = (
                master.copy()
            )
            arrays[f"overrun_state_{boundary}_optimizer_momentum"] = (
                momentum.copy()
            )
        weights_digest = tensors["master_weights"]["sha256"]

    evidence = {
        "kind": kind,
        "backend": "native" if native else "torch",
        "attempted_update_index": total,
        "exception_type": "RuntimeError",
        "exception_message": (
            "training update exceeds configured total updates"
            if native
            else "training update exceeds configured total_updates"
        ),
        "epoch_before": total,
        "epoch_after": total,
        "global_step_before": total * total_agents * horizon,
        "global_step_after": total * total_agents * horizon,
        "tail_valid_before": 0,
        "tail_valid_after": 0,
        "weights_before_sha256": weights_digest,
        "weights_after_sha256": weights_digest,
        "execution_counter_deltas": (
            {
                mode: {
                    role: 0 for role in ("rollout", "tail", "train")
                }
                for mode in ("graph", "eager")
            }
            if native
            else None
        ),
        "native_state": native_snapshot,
    }
    return evidence, config, arrays


def entropy_gradient_pair_evidence(
    runner,
    *,
    enabled_kind: str,
    disabled_kind: str,
) -> tuple[
    tuple[dict, dict[str, np.ndarray]],
    tuple[dict, dict[str, np.ndarray]],
]:
    """Build closed raw gradient evidence with an analytic entropy delta."""

    total = runner.ENTROPY_SCHEDULE_TOTAL_UPDATES
    agents = 2
    horizon = 2
    logits_count = runner.BLOODBOWL_ACTION_LOGITS
    action_heads = tuple(runner.BLOODBOWL_ACTION_HEAD_SIZES)
    _, enabled_raw = entropy_raw_evidence(enabled_kind)
    _, disabled_raw = entropy_raw_evidence(disabled_kind)

    one_decoder = np.zeros(
        (agents, horizon, logits_count + 1),
        dtype=np.float32,
    )
    one_decoder[..., :logits_count] = np.linspace(
        -0.35,
        0.4,
        logits_count,
        dtype=np.float32,
    )
    one_decoder[..., logits_count] = np.float32(0.125)
    decoder = np.repeat(one_decoder[np.newaxis, ...], total, axis=0)
    masks = np.ones(
        (total, agents, horizon, logits_count),
        dtype=np.float32,
    )
    actions = np.zeros(
        (total, agents, horizon, len(action_heads)),
        dtype=np.float32,
    )
    coefficient_delta = (
        enabled_raw["device_coefficient"]
        - disabled_raw["device_coefficient"]
    ).astype(np.float64)
    expected_delta = np.zeros(
        (total, agents, horizon, logits_count),
        dtype=np.float64,
    )
    joint_entropy = np.zeros(
        (total, agents, horizon),
        dtype=np.float64,
    )
    offset = 0
    for size in action_heads:
        head_masks = masks[..., offset : offset + size]
        head_logits = decoder[
            ..., offset : offset + size
        ].astype(np.float64)
        masked_logits = np.where(
            head_masks == np.float32(1.0),
            head_logits,
            -np.inf,
        )
        maximum = np.max(masked_logits, axis=-1, keepdims=True)
        exponentials = np.where(
            head_masks == np.float32(1.0),
            np.exp(masked_logits - maximum),
            0.0,
        )
        probabilities = exponentials / np.sum(
            exponentials,
            axis=-1,
            keepdims=True,
        )
        log_probabilities = np.where(
            head_masks == np.float32(1.0),
            np.log(
                np.maximum(
                    probabilities,
                    np.finfo(np.float64).tiny,
                )
            ),
            0.0,
        )
        entropy = -np.sum(
            probabilities * log_probabilities,
            axis=-1,
            keepdims=True,
        )
        joint_entropy += entropy[..., 0]
        entropy_derivative = probabilities * (
            -entropy - log_probabilities
        )
        expected_delta[..., offset : offset + size] = (
            -coefficient_delta[:, np.newaxis, np.newaxis, np.newaxis]
            * entropy_derivative
            / float(agents * horizon)
        )
        offset += size

    forward_entropy = np.mean(
        joint_entropy,
        axis=(1, 2),
        dtype=np.float64,
    ).astype(np.float32)
    for raw in (enabled_raw, disabled_raw):
        raw["entropy"] = forward_entropy.copy()
        raw["signed_entropy_term"] = (
            -raw["device_coefficient"] * raw["entropy"]
        ).astype(np.float32)
        raw["total_loss"] = (
            raw["policy_loss"]
            + np.float32(0.5) * raw["value_loss"]
            + raw["signed_entropy_term"]
        ).astype(np.float32)

    common = {
        "gradient_decoder_output": decoder,
        "gradient_grad_values": np.zeros(
            (total, agents, horizon),
            dtype=np.float32,
        ),
        "gradient_grad_logstd": np.empty(
            (total, 0),
            dtype=np.float32,
        ),
        "gradient_mb_actions": actions,
        "gradient_mb_logprobs": np.zeros(
            (total, agents, horizon),
            dtype=np.float32,
        ),
        "gradient_mb_advantages": np.zeros(
            (total, agents, horizon),
            dtype=np.float32,
        ),
        "gradient_mb_prio": np.ones(
            (total, agents),
            dtype=np.float32,
        ),
        "gradient_mb_action_mask": masks,
        "gradient_act_sizes": np.repeat(
            np.asarray(action_heads, dtype=np.int32)[np.newaxis, :],
            total,
            axis=0,
        ),
    }
    disabled_arrays = {
        **disabled_raw,
        **{key: value.copy() for key, value in common.items()},
        "gradient_grad_logits": np.zeros(
            (total, agents, horizon, logits_count),
            dtype=np.float32,
        ),
        "gradient_entropy_coefficient": disabled_raw[
            "device_coefficient"
        ][:, np.newaxis].copy(),
    }
    enabled_arrays = {
        **enabled_raw,
        **{key: value.copy() for key, value in common.items()},
        "gradient_grad_logits": expected_delta.astype(np.float32),
        "gradient_entropy_coefficient": enabled_raw[
            "device_coefficient"
        ][:, np.newaxis].copy(),
    }

    declared_shapes = {
        "decoder_output": (agents, horizon, logits_count + 1),
        "grad_logits": (agents, horizon, logits_count),
        "grad_values": (agents, horizon),
        "grad_logstd": (agents, horizon, logits_count),
        "mb_actions": (agents, horizon, len(action_heads)),
        "mb_logprobs": (agents, horizon),
        "mb_advantages": (agents, horizon),
        "mb_prio": (agents,),
        "mb_action_mask": (agents, horizon, logits_count),
        "act_sizes": (len(action_heads),),
        "entropy_coefficient": (1,),
    }

    def gradient_record(
        kind: str,
        arrays: dict[str, np.ndarray],
    ) -> dict:
        snapshots = []
        for update in range(total):
            tensors = {}
            used_bytes = 0
            for name in runner.ENTROPY_GRADIENT_TENSOR_FIELDS:
                present = name != "grad_logstd"
                payload = (
                    b""
                    if not present
                    else arrays[f"gradient_{name}"][update].tobytes(
                        order="C"
                    )
                )
                tensors[name] = {
                    "name": name,
                    "dtype": "i32" if name == "act_sizes" else "f32",
                    "shape": list(declared_shapes[name]),
                    "present": present,
                    "bytes": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
                used_bytes += len(payload)
            snapshots.append(
                {
                    "contract": ENTROPY_GRADIENT_CONTRACT,
                    "completed_update_index": update,
                    "committed_epoch": update + 1,
                    "is_continuous": False,
                    "precision": "f32",
                    "max_bytes": runner.QUALIFICATION_POLICY_MAX_BYTES,
                    "used_bytes": used_bytes,
                    "tensors": tensors,
                }
            )
        return {
            "kind": kind,
            "backend": (
                "native"
                if kind in runner.ENTROPY_NATIVE_CELL_KINDS
                else "torch"
            ),
            "contract": ENTROPY_GRADIENT_CONTRACT,
            "raw_array_fields": list(
                runner.ENTROPY_GRADIENT_ARRAY_FIELDS
            ),
            "snapshots": snapshots,
        }

    return (
        (
            gradient_record(enabled_kind, enabled_arrays),
            enabled_arrays,
        ),
        (
            gradient_record(disabled_kind, disabled_arrays),
            disabled_arrays,
        ),
    )


def cuda_runtime_evidence() -> dict:
    return {
        "schema_version": 1,
        "library": {
            "requested_soname": "libcudart.so.12",
            "resolved_path": "/usr/lib/x86_64-linux-gnu/libcudart.so.12.4.127",
            "sha256": "d" * 64,
        },
        "cuda_visible_devices": "0",
        "before_extension_import": {
            "stage": "before_extension_import",
            "return_code": 0,
            "device_count": 1,
            "error_name": "cudaSuccess",
            "error_string": "no error",
        },
        "after_extension_import": {
            "stage": "after_extension_import",
            "return_code": 0,
            "device_count": 1,
            "error_name": "cudaSuccess",
            "error_string": "no error",
        },
    }


def load_runner():
    spec = importlib.util.spec_from_file_location("qualify_recurrent_cuda", RUNNER)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {RUNNER}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bound_json_result(module, path, record):
    encoded = (
        json.dumps(record, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    return record, module.ValidatedArtifact(
        pathlib.Path(path),
        encoded,
        hashlib.sha256(encoded).hexdigest(),
    )


def heterogeneous_weight_descriptor(
    *,
    bank=1,
    role="frozen",
    hidden_size=32,
    num_layers=2,
    slice_size=2,
    weights=None,
):
    input_size = 2782
    action_logits = 454
    output_size = action_logits + 1
    decoder_offset = input_size * hidden_size
    value_row_offset = decoder_offset + action_logits * hidden_size
    parameter_count = (
        decoder_offset
        + output_size * hidden_size
        + num_layers * 3 * hidden_size * hidden_size
    )
    if weights is None:
        weights = bytes(parameter_count * 4)
    return {
        "bank": bank,
        "role": role,
        "slice_size": slice_size,
        "input_size": input_size,
        "hidden_size": hidden_size,
        "num_layers": num_layers,
        "action_logits": action_logits,
        "output_size": output_size,
        "parameter_count": parameter_count,
        "parameter_bytes": parameter_count * 4,
        "decoder_offset": decoder_offset,
        "decoder_shape": [output_size, hidden_size],
        "value_row_offset": value_row_offset,
        "weights": weights,
    }


def heterogeneous_rollout_fixture(value_coefficient=0.5):
    horizon = 8
    total_agents = 8
    frozen_rows = (2, 3, 6, 7)
    live_values = (
        (0.0,) * horizon
        if value_coefficient == 0.0
        else (3.0, 4.5, 5.25, 5.625, 5.8125, 5.90625, 5.953125, 5.9765625)
    )
    tail_value = 0.0 if value_coefficient == 0.0 else 3.0
    arrays = {
        "actions": np.zeros((horizon, total_agents, 3), np.float32),
        "action_mask": np.ones((horizon, total_agents, 454), np.float32),
        "values": np.zeros((horizon, total_agents), np.float32),
        "logprobs": np.zeros((horizon, total_agents), np.float32),
        "tail_terminals": np.zeros(total_agents, np.float32),
        "tail_values": np.zeros(total_agents, np.float32),
        "tail_valid": np.ones(2, np.int32),
    }
    arrays["actions"][:, frozen_rows, :] = np.array(
        [29.0, 32.0, 390.0], np.float32
    )
    arrays["values"][:, frozen_rows] = np.asarray(
        live_values, dtype=np.float32
    )[:, np.newaxis]
    arrays["tail_values"][list(frozen_rows)] = np.float32(tail_value)
    for buffer in range(2):
        arrays[f"decoder_bank_1_buffer_{buffer}"] = np.zeros(
            (2, 455), np.float32
        )
        arrays[f"decoder_bank_1_buffer_{buffer}"][:, -1] = np.float32(
            live_values[-1]
        )
        arrays[f"tail_decoder_bank_1_buffer_{buffer}"] = np.zeros(
            (2, 455), np.float32
        )
        arrays[f"tail_decoder_bank_1_buffer_{buffer}"][:, -1] = np.float32(
            tail_value
        )
    entries = []
    for bank, layers, hidden in ((0, 1, 64), (1, 2, 32)):
        for buffer in range(2):
            elements = layers * 2 * hidden
            entry = {
                "bank": bank,
                "buffer": buffer,
                "shape": [layers, 2, hidden],
                "elements": elements,
                "active_rows": 2,
                "active_elements": elements,
                "nonzero": elements,
                "nonfinite": 0,
                "max_abs": 0.498046875,
                "active_nonzero": elements,
                "active_nonfinite": 0,
                "active_max_abs": 0.498046875,
                "active_min": 0.498046875,
                "active_max": 0.498046875,
            }
            entries.append(entry)
    state = {
        "cleared": False,
        "num_banks": 2,
        "num_buffers": 2,
        "agents_per_buffer": 4,
        "bank_layout": [0, 2, 4],
        "entries": entries,
    }
    return arrays, state


def integrated_advantage_fixture(module):
    """Closed vector-width fixture with a nonzero primary tail signal."""

    arrays, state = heterogeneous_rollout_fixture(value_coefficient=0.0)
    total_agents = 8
    horizon = module.HETEROGENEOUS_HORIZON
    primary_rows = (0, 1, 4, 5)
    arrays["values"] = np.zeros((horizon, total_agents), np.float32)
    arrays["logprobs"] = np.zeros((horizon, total_agents), np.float32)
    tail_rewards = np.zeros(total_agents, np.float32)
    tail_rewards[list(primary_rows)] = np.array(
        [2.0, 3.0, 4.0, 5.0],
        np.float32,
    )
    arrays.update(
        rewards=np.zeros((horizon, total_agents), np.float32),
        terminals=np.zeros((horizon, total_agents), np.float32),
        tail_rewards=tail_rewards,
        tail_terminals=np.ones(total_agents, np.float32),
        tail_valid_after_train=np.zeros(2, np.int32),
        selected_rows_after_train=np.array(
            [0, 1, 4, 5], dtype=np.int32
        ),
    )
    advantages = np.zeros((total_agents, horizon), np.float32)
    gamma = np.float32(0.995)
    gae_lambda = np.float32(0.95)
    for row in primary_rows:
        accumulator = tail_rewards[row]
        for timestep in range(horizon - 1, -1, -1):
            advantages[row, timestep] = accumulator
            accumulator *= gamma * gae_lambda
    arrays["advantages_after_train"] = advantages
    config = module.qualification_args(
        cudagraphs=-1,
        seed=123,
        total_agents=total_agents,
        num_buffers=2,
        num_threads=2,
        horizon=horizon,
        max_decisions=16,
        hidden_size=64,
        num_layers=1,
        frozen_banks=1,
        frozen_bank_pct=0.5,
        frozen_hidden_size=32,
        frozen_num_layers=2,
        learning_rate=0.0,
    )
    return arrays, state, config


class FakeStrictStageVec:
    def __init__(self, backend):
        self.backend = backend
        self.closed = False

    def close(self):
        self.closed = True
        self.backend.closed_vecs += 1


class FakeStrictStageBackend:
    """CPU-only behavioral model of the test-role constructor counters."""

    def __init__(self, *, invalid_team=30, leak_constructor=None):
        self.invalid_team = invalid_team
        self.leak_constructor = leak_constructor
        self.counters = {
            "normalize_calls": 0,
            "normalize_gil_held_calls": 0,
            "create_static_vec_calls": 0,
            "cuda_get_device_count_calls": 0,
            "create_pufferl_impl_calls": 0,
        }
        self.closed_vecs = 0
        self.closed_pufferls = 0

    def strict_env_config_test_stages(self, reset=False):
        snapshot = dict(self.counters)
        if reset:
            self.counters = dict.fromkeys(self.counters, 0)
        return snapshot

    def _normalize(self, config, constructor):
        self.counters["normalize_calls"] += 1
        self.counters["normalize_gil_held_calls"] += 1
        if config["env"].get("force_home_team") == self.invalid_team:
            if self.leak_constructor == constructor:
                key = (
                    "create_static_vec_calls"
                    if constructor == "create_vec"
                    else "cuda_get_device_count_calls"
                )
                self.counters[key] += 1
            raise ValueError(
                "force_home_team must be integer -1 or "
                f"0..BB_TEAM_COUNT-1; got {self.invalid_team}"
            )

    def create_vec(self, config, *, gpu):
        self._normalize(config, "create_vec")
        if gpu != 1 or not isinstance(config["vec"]["total_agents"], int):
            raise TypeError("dangerous vec input was reached")
        self.counters["create_static_vec_calls"] += 1
        return FakeStrictStageVec(self)

    def create_pufferl(self, config):
        self._normalize(config, "create_pufferl")
        if not isinstance(config["vec"]["total_agents"], int):
            raise TypeError("dangerous vec input was reached")
        if not isinstance(config["train"], dict):
            raise TypeError("dangerous train input was reached")
        if not isinstance(config["policy"], dict):
            raise TypeError("dangerous policy input was reached")
        if not isinstance(config["gpu_id"], int):
            raise TypeError("dangerous device input was reached")
        self.counters["cuda_get_device_count_calls"] += 1
        self.counters["create_pufferl_impl_calls"] += 1
        return object()

    def close(self, _pufferl):
        self.closed_pufferls += 1


class QualificationValidatorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.q = load_runner()

    # ------------------------------------------------------- recurrent state

    def test_state_gate_requires_every_primary_and_frozen_buffer_exactly_zero(self):
        clean = {
            "num_banks": 2,
            "num_buffers": 1,
            "entries": [
                {"bank": 0, "buffer": 0, "shape": [1, 2, 4],
                 "elements": 8, "active_rows": 1, "active_elements": 4,
                 "nonzero": 0, "nonfinite": 0, "max_abs": 0.0,
                 "active_nonzero": 0, "active_nonfinite": 0,
                 "active_max_abs": 0.0},
                {"bank": 1, "buffer": 0, "shape": [1, 1, 4],
                 "elements": 4, "active_rows": 1, "active_elements": 4,
                 "nonzero": 0, "nonfinite": 0, "max_abs": 0.0,
                 "active_nonzero": 0, "active_nonfinite": 0,
                 "active_max_abs": 0.0},
            ]
        }
        self.q.validate_zero_state(clean, expected_banks=2, expected_buffers=1)
        for key, value in (("nonzero", 1), ("nonfinite", 1), ("max_abs", 1e-8)):
            bad = json.loads(json.dumps(clean))
            bad["entries"][1][key] = value
            with self.subTest(key=key), self.assertRaises(self.q.QualificationError):
                self.q.validate_zero_state(
                    bad, expected_banks=2, expected_buffers=1)
        # A missing frozen bank/buffer is a coverage failure, not a pass.
        partial = json.loads(json.dumps(clean))
        del partial["entries"][1]
        with self.assertRaisesRegex(
            self.q.QualificationError, "state coverage mismatch"
        ):
            self.q.validate_zero_state(
                partial, expected_banks=2, expected_buffers=1)

    def test_nonzero_state_gate_requires_activity_in_every_bank_buffer(self):
        report = {"num_banks": 2, "num_buffers": 1, "entries": [
            {"bank": 0, "buffer": 0, "shape": [1, 2, 4],
             "elements": 8, "active_rows": 1, "active_elements": 4,
             "nonzero": 2, "nonfinite": 0, "max_abs": 0.5,
             "active_nonzero": 2, "active_nonfinite": 0,
             "active_max_abs": 0.5},
            {"bank": 1, "buffer": 0, "shape": [1, 1, 4],
             "elements": 4, "active_rows": 1, "active_elements": 4,
             "nonzero": 1, "nonfinite": 0, "max_abs": 0.25,
             "active_nonzero": 1, "active_nonfinite": 0,
             "active_max_abs": 0.25},
        ]}
        self.q.validate_nonzero_state(
            report, expected_banks=2, expected_buffers=1)
        report["entries"][1]["active_nonzero"] = 0
        report["entries"][1]["active_max_abs"] = 0.0
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_nonzero_state(
                report, expected_banks=2, expected_buffers=1)

    def test_row_partition_is_derived_from_recorded_bank_layout(self):
        report = {
            "num_banks": 2, "num_buffers": 2, "agents_per_buffer": 4,
            "bank_layout": [0, 2, 4],
        }
        primary, frozen = self.q.derive_row_partition(report, total_agents=8)
        self.assertEqual(primary, {0, 1, 4, 5})
        self.assertEqual(frozen, {2, 3, 6, 7})
        for bad_layout in ([0, 4], [0, 0, 4], [1, 2, 4], [0, 2, 5]):
            with self.subTest(layout=bad_layout), self.assertRaises(
                    self.q.QualificationError):
                self.q.derive_row_partition(
                    dict(report, bank_layout=bad_layout), total_agents=8)
        # One bank means no real frozen partition to prove disjointness against.
        with self.assertRaisesRegex(
            self.q.QualificationError, "real frozen bank"
        ):
            self.q.derive_row_partition(
                {"num_banks": 1, "num_buffers": 2, "agents_per_buffer": 4,
                 "bank_layout": [0, 4]},
                total_agents=8,
            )

    # -------------------------------------- heterogeneous frozen-policy oracle

    def test_heterogeneous_weight_layout_and_donors_are_exact(self):
        descriptor = heterogeneous_weight_descriptor()
        layout = self.q.validate_policy_weight_descriptor(
            descriptor,
            expected_bank=1,
            expected_role="frozen",
            expected_hidden_size=32,
            expected_num_layers=2,
            expected_slice_size=2,
        )
        self.assertEqual(layout["decoder_offset"], 89_024)
        self.assertEqual(layout["value_row_offset"], 103_552)
        self.assertEqual(layout["parameter_count"], 109_728)
        self.assertEqual(layout["parameter_bytes"], 438_912)

        zero = self.q.build_heterogeneous_frozen_donor(
            layout, value_coefficient=0.0
        )
        positive = self.q.build_heterogeneous_frozen_donor(
            layout, value_coefficient=0.5
        )
        self.assertEqual(
            hashlib.sha256(zero).hexdigest(),
            "d4565fed83a63b06a5db51ed34c03175058dd331a3baf7aaee0ef9fcca41f85c",
        )
        self.assertEqual(
            hashlib.sha256(positive).hexdigest(),
            "dda4adcadb2c6ab47acec9461d1e54d0f0a196d6c95de45d629c72c6f7b954bf",
        )
        zero_values = np.frombuffer(zero, dtype="<f4")
        positive_values = np.frombuffer(positive, dtype="<f4")
        changed = np.flatnonzero(zero_values != positive_values)
        np.testing.assert_array_equal(
            changed,
            np.arange(
                layout["value_row_offset"],
                layout["value_row_offset"] + 32,
            ),
        )
        self.assertTrue(np.all(positive_values[changed] == np.float32(0.5)))
        decoder = zero_values[
            layout["decoder_offset"]:
            layout["decoder_offset"] + 455 * 32
        ].reshape(455, 32)
        for row, expected in (
            (0, 0.0),
            (29, 32.0 * 29),
            (30, 0.0),
            (62, 32.0 * 32),
            (63, 0.0),
            (453, 32.0 * 390),
        ):
            self.assertTrue(np.all(decoder[row] == np.float32(expected)))

    def test_heterogeneous_weight_descriptor_is_fail_closed(self):
        descriptor = heterogeneous_weight_descriptor()
        cases = {
            "wrong decoder shape": dict(descriptor, decoder_shape=[455, 64]),
            "wrong input ABI": dict(descriptor, input_size=2783),
            "wrong action ABI": dict(descriptor, action_logits=455),
            "wrong output ABI": dict(descriptor, output_size=454),
            "wrong count": dict(descriptor, parameter_count=109_729),
            "wrong bytes": dict(descriptor, parameter_bytes=438_908),
            "mutable bytes": dict(
                descriptor, weights=bytearray(descriptor["weights"])
            ),
            "wrong bank": dict(descriptor, bank=0),
            "wrong role": dict(descriptor, role="primary"),
            "wrong slice": dict(descriptor, slice_size=1),
            "extra key": dict(descriptor, unexpected=True),
        }
        for label, changed in cases.items():
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_policy_weight_descriptor(
                    changed,
                    expected_bank=1,
                    expected_role="frozen",
                    expected_hidden_size=32,
                    expected_num_layers=2,
                    expected_slice_size=2,
                )
        oversized = heterogeneous_weight_descriptor()
        oversized["parameter_bytes"] = self.q.QUALIFICATION_POLICY_MAX_BYTES + 4
        oversized["parameter_count"] = oversized["parameter_bytes"] // 4
        oversized["weights"] = bytes(oversized["parameter_bytes"])
        with self.assertRaisesRegex(
            self.q.QualificationError, "limit|oversized|bytes"
        ):
            self.q.validate_policy_weight_descriptor(
                oversized,
                expected_bank=1,
                expected_role="frozen",
                expected_hidden_size=32,
                expected_num_layers=2,
                expected_slice_size=2,
            )

    def test_authenticated_frozen_loader_detects_native_silent_noop(self):
        descriptor = heterogeneous_weight_descriptor()

        class Backend:
            def __init__(self, apply_load):
                self.apply_load = apply_load
                self.weights = descriptor["weights"]
                self.paths = []

            def load_frozen_bank(self, _pufferl, bank, path):
                self.assertions = (bank, pathlib.Path(path).is_file())
                self.paths.append(path)
                if self.apply_load:
                    self.weights = pathlib.Path(path).read_bytes()

            def qualification_policy_weights(self, _pufferl, bank, max_bytes):
                if max_bytes != 64 * 1024 * 1024:
                    raise AssertionError(max_bytes)
                return dict(descriptor, bank=bank, weights=self.weights)

        with tempfile.TemporaryDirectory() as temporary:
            applied = Backend(True)
            evidence = self.q.install_authenticated_frozen_donor(
                applied,
                object(),
                pathlib.Path(temporary),
                descriptor,
                name="positive-value",
                value_coefficient=0.5,
            )
            self.assertEqual(applied.assertions, (0, True))
            self.assertTrue(evidence["readback_matches_donor"])
            self.assertEqual(
                evidence["expected_sha256"], evidence["readback_sha256"]
            )
            self.assertFalse(
                any(pathlib.Path(path).exists() for path in applied.paths)
            )

            silent = Backend(False)
            with self.assertRaisesRegex(
                self.q.QualificationError, "readback|load|bytes"
            ):
                self.q.install_authenticated_frozen_donor(
                    silent,
                    object(),
                    pathlib.Path(temporary),
                    descriptor,
                    name="silent-noop",
                    value_coefficient=0.5,
                )

    def test_zero_intervention_tail_is_consumed_before_positive_rollout(self):
        primary = heterogeneous_weight_descriptor(
            bank=0,
            role="primary",
            hidden_size=64,
            num_layers=1,
            weights=bytes([7]) * 877_824,
        )
        frozen_layout = heterogeneous_weight_descriptor()
        frozen = dict(
            frozen_layout,
            weights=self.q.build_heterogeneous_frozen_donor(
                frozen_layout, value_coefficient=0.0
            ),
        )

        class Backend:
            def __init__(self, mutate=False):
                self.mutate = mutate
                self.train_calls = 0

            def train(self, _pufferl):
                self.train_calls += 1

            def qualification_snapshot(self, _pufferl):
                return {}

            def qualification_graph_execution(self, _pufferl):
                return {
                    "cudagraphs": -1,
                    "captured": {
                        "rollout": False,
                        "tail": False,
                        "train": False,
                    },
                    "handles_ready": {
                        "rollout": False,
                        "tail": False,
                        "train": False,
                    },
                    "graph_launch_counts": {
                        "rollout": 0,
                        "tail": 0,
                        "train": 0,
                    },
                    "eager_execution_counts": {
                        "rollout": 3,
                        "tail": 3,
                        "train": 1,
                    },
                }

            def qualification_policy_weights(self, _pufferl, bank, _max_bytes):
                descriptor = primary if bank == 0 else frozen
                if self.mutate and bank == 0:
                    changed = bytearray(descriptor["weights"])
                    changed[0] ^= 1
                    return dict(descriptor, weights=bytes(changed))
                return descriptor

        backend = Backend()
        with mock.patch.object(
            self.q,
            "decode_snapshot",
            return_value={"tail_valid": np.zeros(2, np.int32)},
        ):
            evidence = self.q.consume_heterogeneous_tail_record(
                backend,
                object(),
                primary,
                frozen,
                num_buffers=2,
            )
        self.assertEqual(backend.train_calls, 1)
        self.assertTrue(evidence["tail_consumed"])
        self.assertTrue(evidence["primary_weights_unchanged"])
        self.assertTrue(evidence["frozen_weights_unchanged"])

        with mock.patch.object(
            self.q,
            "decode_snapshot",
            return_value={"tail_valid": np.ones(2, np.int32)},
        ), self.assertRaisesRegex(
            self.q.QualificationError, "tail|validity|consum"
        ):
            self.q.consume_heterogeneous_tail_record(
                Backend(),
                object(),
                primary,
                frozen,
                num_buffers=2,
            )
        with mock.patch.object(
            self.q,
            "decode_snapshot",
            return_value={"tail_valid": np.zeros(2, np.int32)},
        ), self.assertRaisesRegex(
            self.q.QualificationError, "weight|bytes|changed"
        ):
            self.q.consume_heterogeneous_tail_record(
                Backend(mutate=True),
                object(),
                primary,
                frozen,
                num_buffers=2,
            )

        source = RUNNER.read_text(encoding="utf-8")
        body = source[
            source.index("def _measure_heterogeneous_rollout("):
            source.index("def _measure_ratio(")
        ]
        zero = body.index('zero_arrays, zero_state, zero_oracle = variant(')
        consume = body.index("consume_heterogeneous_tail_record(")
        positive = body.index(
            "positive_arrays, positive_state, positive_oracle = variant("
        )
        self.assertLess(zero, consume)
        self.assertLess(consume, positive)

    def test_heterogeneous_rollout_oracle_is_exact_and_fail_closed(self):
        positive, state = heterogeneous_rollout_fixture(0.5)
        verdict = self.q.validate_heterogeneous_rollout_oracle(
            positive,
            state,
            total_agents=8,
            num_buffers=2,
            horizon=self.q.HETEROGENEOUS_HORIZON,
            value_coefficient=0.5,
            atol=1.0e-6,
        )
        self.assertEqual(
            verdict["frozen_behavior_values"],
            list(self.q.HETEROGENEOUS_POSITIVE_VALUE_SEQUENCE),
        )
        self.assertEqual(verdict["frozen_tail_value"], 3.0)
        self.assertEqual(
            verdict["frozen_live_state"],
            self.q.HETEROGENEOUS_FROZEN_STATE_SEQUENCE[-1],
        )
        self.assertTrue(verdict["all_frozen_actions_max_legal"])
        self.assertEqual(verdict["max_abs_frozen_logprob"], 0.0)
        self.assertTrue(verdict["ordinary_decoder_preserved"])

        zero, zero_state = heterogeneous_rollout_fixture(0.0)
        zero_verdict = self.q.validate_heterogeneous_rollout_oracle(
            zero,
            zero_state,
            total_agents=8,
            num_buffers=2,
            horizon=self.q.HETEROGENEOUS_HORIZON,
            value_coefficient=0.0,
            atol=1.0e-6,
        )
        self.assertEqual(
            zero_verdict["frozen_behavior_values"],
            [0.0] * self.q.HETEROGENEOUS_HORIZON,
        )
        self.assertEqual(zero_verdict["frozen_tail_value"], 0.0)

        mutations = []
        changed = {key: value.copy() for key, value in positive.items()}
        changed["tail_values"][2] = np.float32(4.5)
        mutations.append(("carried tail state", changed, state))
        changed = {key: value.copy() for key, value in positive.items()}
        changed["tail_values"][2] = np.float32(4.5)
        changed["tail_decoder_bank_1_buffer_0"][0, -1] = np.float32(4.5)
        mutations.append(("forged tail decoder", changed, state))
        changed = {key: value.copy() for key, value in positive.items()}
        changed["decoder_bank_1_buffer_0"][0, -1] = np.float32(3.0)
        mutations.append(("ordinary decoder clobbered", changed, state))
        changed = {key: value.copy() for key, value in positive.items()}
        changed["tail_terminals"][2] = np.float32(1.0)
        changed["tail_values"][2] = np.float32(0.0)
        mutations.append(("terminal sentinel", changed, state))
        changed = {key: value.copy() for key, value in positive.items()}
        changed["actions"][0, 2, 0] = np.float32(28.0)
        mutations.append(("non-maximal action", changed, state))
        changed = {key: value.copy() for key, value in positive.items()}
        changed["action_mask"][0, 2, 29] = np.float32(0.0)
        mutations.append(("disabled action", changed, state))
        changed = {key: value.copy() for key, value in positive.items()}
        changed["logprobs"][0, 2] = np.float32(1.0e-4)
        mutations.append(("nonzero logprob", changed, state))
        changed = {key: value.copy() for key, value in positive.items()}
        changed["logprobs"][0, 2] = np.float32(np.nan)
        mutations.append(("nonfinite logprob", changed, state))
        changed_state = json.loads(json.dumps(state))
        changed_state["entries"][2]["active_min"] = 0.25
        mutations.append(("clobbered live state", positive, changed_state))

        for label, changed_arrays, changed_state in mutations:
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_heterogeneous_rollout_oracle(
                    changed_arrays,
                    changed_state,
                    total_agents=8,
                    num_buffers=2,
                    horizon=self.q.HETEROGENEOUS_HORIZON,
                    value_coefficient=0.5,
                    atol=1.0e-6,
                )

    def test_rollout_cell_uses_heterogeneous_architecture_and_vector_horizon(self):
        args = SimpleNamespace(
            seed=123,
            throughput_agents=4096,
            throughput_buffers=2,
            throughput_threads=20,
            throughput_horizon=64,
            throughput_hidden=512,
            throughput_layers=1,
            throughput_minibatch_size=16384,
        )
        config = self.q._cell_config("rollout", -1, args)
        self.assertEqual(
            config["train"]["horizon"],
            self.q.HETEROGENEOUS_HORIZON,
        )
        self.assertEqual(config["vec"]["total_agents"], 8)
        self.assertEqual(config["vec"]["num_buffers"], 2)
        self.assertEqual(
            config["policy"],
            {"hidden_size": 64, "num_layers": 1},
        )
        self.assertEqual(config["vec"]["frozen_bank_hidden_size"], 32)
        self.assertEqual(config["vec"]["frozen_bank_num_layers"], 2)
        self.assertEqual(config["vec"]["frozen_bank_pct"], 0.5)

    def test_parent_reconstructs_heterogeneous_donors_and_oracles(self):
        primary = heterogeneous_weight_descriptor(
            bank=0,
            role="primary",
            hidden_size=64,
            num_layers=1,
            weights=bytes([1]) * 877_824,
        )
        frozen = heterogeneous_weight_descriptor()

        def architecture(descriptor, *, digests):
            result = {
                key: value
                for key, value in descriptor.items()
                if key != "weights"
            }
            if digests:
                start = 4 * descriptor["value_row_offset"]
                stop = start + 4 * descriptor["hidden_size"]
                result.update(
                    weights_sha256=hashlib.sha256(
                        descriptor["weights"]
                    ).hexdigest(),
                    value_row_sha256=hashlib.sha256(
                        descriptor["weights"][start:stop]
                    ).hexdigest(),
                )
            return result

        zero_bytes = self.q.build_heterogeneous_frozen_donor(
            frozen, value_coefficient=0.0
        )
        positive_bytes = self.q.build_heterogeneous_frozen_donor(
            frozen, value_coefficient=0.5
        )
        zero_arrays, zero_state = heterogeneous_rollout_fixture(0.0)
        positive_arrays, positive_state = heterogeneous_rollout_fixture(0.5)
        arrays = dict(positive_arrays)
        arrays.update({
            f"{self.q.HETEROGENEOUS_ZERO_PREFIX}{key}": value
            for key, value in zero_arrays.items()
        })
        record = {
            "config": {
                "policy": {"hidden_size": 64, "num_layers": 1},
                "vec": {
                    "total_agents": 8,
                    "num_buffers": 2,
                    "num_frozen_banks": 1,
                    "frozen_bank_pct": 0.5,
                    "frozen_bank_hidden_size": 32,
                    "frozen_bank_num_layers": 2,
                },
                "train": {
                    "horizon": self.q.HETEROGENEOUS_HORIZON,
                    "learning_rate": 0.0,
                    "replay_ratio": 1,
                    "minibatch_size": (
                        8 * self.q.HETEROGENEOUS_HORIZON
                    ),
                },
            },
            "heterogeneous_policy": {
                "primary_architecture": architecture(primary, digests=True),
                "frozen_architecture": architecture(frozen, digests=False),
                "donors": {
                    "zero_value": {
                        "value_coefficient": 0.0,
                        "expected_sha256": hashlib.sha256(zero_bytes).hexdigest(),
                        "readback_sha256": hashlib.sha256(zero_bytes).hexdigest(),
                        "changed_float_indices": 0,
                        "readback_matches_donor": True,
                    },
                    "positive_value": {
                        "value_coefficient": 0.5,
                        "expected_sha256": hashlib.sha256(
                            positive_bytes
                        ).hexdigest(),
                        "readback_sha256": hashlib.sha256(
                            positive_bytes
                        ).hexdigest(),
                        "changed_float_indices": 32,
                        "readback_matches_donor": True,
                    },
                },
            },
            "heterogeneous_zero_state": zero_state,
            "heterogeneous_positive_state": positive_state,
            "heterogeneous_zero_tail_consumption": {
                "tail_consumed": True,
                "primary_weights_unchanged": True,
                "frozen_weights_unchanged": True,
                "primary_sha256": hashlib.sha256(
                    primary["weights"]
                ).hexdigest(),
                "frozen_sha256": hashlib.sha256(zero_bytes).hexdigest(),
            },
        }
        record["heterogeneous_zero_oracle"] = (
            self.q.validate_heterogeneous_rollout_oracle(
                zero_arrays,
                zero_state,
                total_agents=8,
                num_buffers=2,
                horizon=self.q.HETEROGENEOUS_HORIZON,
                value_coefficient=0.0,
                atol=1.0e-6,
            )
        )
        record["heterogeneous_positive_oracle"] = (
            self.q.validate_heterogeneous_rollout_oracle(
                positive_arrays,
                positive_state,
                total_agents=8,
                num_buffers=2,
                horizon=self.q.HETEROGENEOUS_HORIZON,
                value_coefficient=0.5,
                atol=1.0e-6,
            )
        )
        verdict = self.q.validate_heterogeneous_policy_evidence(
            record, arrays, atol=1.0e-6
        )
        self.assertTrue(verdict["readback_matches_donor"])
        self.assertTrue(verdict["primary_frozen_architectures_differ"])
        self.assertEqual(
            verdict["positive_value"]["frozen_behavior_values"],
            list(self.q.HETEROGENEOUS_POSITIVE_VALUE_SEQUENCE),
        )

        changed = json.loads(json.dumps(record))
        changed["heterogeneous_policy"]["donors"]["positive_value"][
            "expected_sha256"
        ] = "0" * 64
        with self.assertRaisesRegex(
            self.q.QualificationError, "donor|digest|SHA"
        ):
            self.q.validate_heterogeneous_policy_evidence(
                changed, arrays, atol=1.0e-6
            )
        changed = json.loads(json.dumps(record))
        changed["config"]["policy"]["num_layers"] = True
        with self.assertRaisesRegex(
            self.q.QualificationError, "architecture|configuration|integer"
        ):
            self.q.validate_heterogeneous_policy_evidence(
                changed, arrays, atol=1.0e-6
            )
        changed = json.loads(json.dumps(record))
        changed["config"]["train"]["learning_rate"] = 1.0e-4
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "learning|zero|configuration|intervention",
        ):
            self.q.validate_heterogeneous_policy_evidence(
                changed, arrays, atol=1.0e-6
            )
        changed_arrays = {key: value.copy() for key, value in arrays.items()}
        changed_arrays["actions"][0, 2, 0] = np.float32(28.0)
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_heterogeneous_policy_evidence(
                record, changed_arrays, atol=1.0e-6
            )

    # ------------------------------------------------- rollout / PPO evidence

    def test_snapshot_comparison_is_exact_for_discrete_and_tolerant_for_float(self):
        left = {
            "observations": np.array([[[1, 2]]], dtype=np.float32),
            "actions": np.array([[[2, 3, 4]]], dtype=np.float32),
            "terminals": np.array([[1]], dtype=np.float32),
            "action_mask": np.array([[[1, 0, 1]]], dtype=np.float32),
            "rewards": np.array([[0]], dtype=np.float32),
            "values": np.array([[0.125]], dtype=np.float32),
            "logprobs": np.array([[-0.75]], dtype=np.float32),
        }
        right = {key: value.copy() for key, value in left.items()}
        right["values"][0, 0] += 5e-7
        self.q.compare_snapshots(left, right, atol=1e-6, require_all_terminal=True)
        right["actions"][0, 0, 0] = 1
        with self.assertRaises(self.q.QualificationError):
            self.q.compare_snapshots(left, right, atol=1e-6)

    def test_snapshot_rejects_nonfinite_shape_dtype_and_missing_fields(self):
        base = {
            "observations": np.zeros((1, 2, 3), np.float32),
            "actions": np.zeros((1, 2, 3), np.float32),
            "terminals": np.ones((1, 2), np.float32),
            "action_mask": np.ones((1, 2, 4), np.float32),
            "rewards": np.zeros((1, 2), np.float32),
            "values": np.zeros((1, 2), np.float32),
            "logprobs": np.zeros((1, 2), np.float32),
        }
        for mutate in ("missing", "shape", "dtype", "nan"):
            other = {key: value.copy() for key, value in base.items()}
            if mutate == "missing":
                del other["values"]
            elif mutate == "shape":
                other["values"] = np.zeros((2, 1), np.float32)
            elif mutate == "dtype":
                other["values"] = np.zeros((1, 2), np.float64)
            else:
                other["values"][0, 0] = np.nan
            with self.subTest(mutate=mutate), self.assertRaises(
                    self.q.QualificationError):
                self.q.compare_snapshots(base, other, atol=1e-6)

    def test_decoder_parity_requires_matching_bank_buffer_coverage(self):
        left = {
            "decoder_bank_0_buffer_0": np.zeros((2, 3), np.float32),
            "decoder_bank_1_buffer_0": np.zeros((2, 3), np.float32),
        }
        right = {key: value.copy() for key, value in left.items()}
        self.q.compare_decoder_outputs(left, right, atol=1e-6)
        del right["decoder_bank_1_buffer_0"]
        with self.assertRaisesRegex(
            self.q.QualificationError, "coverage mismatch"
        ):
            self.q.compare_decoder_outputs(left, right, atol=1e-6)

    def test_tail_snapshot_is_typed_complete_valid_and_graph_comparable(self):
        left = {
            "tail_rewards": np.array([0.25, -0.5], np.float32),
            "tail_terminals": np.array([0.0, 1.0], np.float32),
            "tail_values": np.array([1.25, 0.0], np.float32),
            "tail_valid": np.array([1], np.int32),
        }
        right = {key: value.copy() for key, value in left.items()}
        right["tail_values"][0] += 5.0e-7
        verdict = self.q.compare_tail_snapshots(
            left,
            right,
            total_agents=2,
            num_buffers=1,
            atol=1.0e-6,
        )
        self.assertLessEqual(verdict["tail_values"], 1.0e-6)
        for label, mutate in (
            ("missing", lambda value: value.pop("tail_values")),
            (
                "wrong shape",
                lambda value: value.update(
                    tail_rewards=np.zeros((1, 2), np.float32)
                ),
            ),
            (
                "wrong float dtype",
                lambda value: value.update(
                    tail_values=np.zeros(2, np.float64)
                ),
            ),
            (
                "nonfinite",
                lambda value: value["tail_values"].__setitem__(0, np.nan),
            ),
            (
                "nonbinary terminal",
                lambda value: value["tail_terminals"].__setitem__(0, 0.5),
            ),
            (
                "terminal bootstrap",
                lambda value: value["tail_values"].__setitem__(1, 1.0),
            ),
            (
                "invalid callback count",
                lambda value: value["tail_valid"].__setitem__(0, 0),
            ),
            (
                "wrong validity dtype",
                lambda value: value.update(
                    tail_valid=np.ones(1, np.float32)
                ),
            ),
        ):
            changed = {key: array.copy() for key, array in left.items()}
            mutate(changed)
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_tail_snapshot(
                    changed,
                    total_agents=2,
                    num_buffers=1,
                )

    def test_tail_values_match_each_primary_and_frozen_decoder_value(self):
        snapshot = {
            "tail_rewards": np.array([0.0, 0.0, 0.0, 0.0], np.float32),
            "tail_terminals": np.array([0.0, 1.0, 0.0, 0.0], np.float32),
            "tail_values": np.array([1.5, 0.0, 2.5, 3.5], np.float32),
            "tail_valid": np.array([1, 1], np.int32),
            "tail_decoder_bank_0_buffer_0": np.array(
                [[10.0, 1.5]], np.float32
            ),
            "tail_decoder_bank_1_buffer_0": np.array(
                [[20.0, 99.0]], np.float32
            ),
            "tail_decoder_bank_0_buffer_1": np.array(
                [[30.0, 2.5]], np.float32
            ),
            "tail_decoder_bank_1_buffer_1": np.array(
                [[40.0, 3.5]], np.float32
            ),
        }
        verdict = self.q.validate_tail_value_routing(
            snapshot,
            total_agents=4,
            num_buffers=2,
            atol=1.0e-6,
        )
        self.assertEqual(
            set(verdict),
            {
                "tail_decoder_buffer_0",
                "tail_decoder_buffer_1",
            },
        )
        changed = {key: value.copy() for key, value in snapshot.items()}
        changed["tail_values"][3] = -3.5
        with self.assertRaisesRegex(
            self.q.QualificationError, "tail decoder"
        ):
            self.q.validate_tail_value_routing(
                changed,
                total_agents=4,
                num_buffers=2,
                atol=1.0e-6,
            )
        changed = {key: value.copy() for key, value in snapshot.items()}
        del changed["tail_decoder_bank_1_buffer_1"]
        with self.assertRaisesRegex(
            self.q.QualificationError, "coverage"
        ):
            self.q.validate_tail_value_routing(
                changed,
                total_agents=4,
                num_buffers=2,
                atol=1.0e-6,
            )

    def test_frozen_advantages_are_finite_exactly_zero_and_shape_locked(self):
        advantages = np.array(
            [
                [1.0, -1.0],
                [0.0, 0.0],
                [2.0, -2.0],
                [0.0, 0.0],
            ],
            np.float32,
        )
        verdict = self.q.validate_frozen_advantages(
            advantages,
            primary_rows={0, 2},
            frozen_rows={1, 3},
            horizon=2,
        )
        self.assertEqual(verdict["frozen_rows_zero"], [1, 3])
        for label, changed in (
            ("nonzero frozen", advantages.copy()),
            ("nonfinite primary", advantages.copy()),
            ("wrong shape", advantages[:, :1].copy()),
            ("wrong dtype", advantages.astype(np.float64)),
        ):
            if label == "nonzero frozen":
                changed[1, 0] = np.float32(1.0e-20)
            elif label == "nonfinite primary":
                changed[0, 0] = np.nan
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_frozen_advantages(
                    changed,
                    primary_rows={0, 2},
                    frozen_rows={1, 3},
                    horizon=self.q.HETEROGENEOUS_HORIZON,
                )

    def test_snapshot_decoder_distinguishes_behavior_and_tail_coverage(self):
        def tensor(value):
            array = np.asarray(value, dtype="<f4")
            return {
                "dtype": "f32",
                "shape": list(array.shape),
                "data": array.tobytes(),
            }

        raw = {
            "num_banks": 2,
            "num_buffers": 1,
            "tensors": {
                "tail_values": tensor([1.0, 2.0]),
            },
            "decoder_outputs": [
                {
                    "bank": bank,
                    "buffer": 0,
                    "active_rows": 1,
                    "tensor": tensor([[bank, bank + 1.0]]),
                }
                for bank in range(2)
            ],
            "tail_decoder_outputs": [
                {
                    "bank": bank,
                    "buffer": 0,
                    "active_rows": 1,
                    "tensor": tensor([[bank + 2.0, bank + 3.0]]),
                }
                for bank in range(2)
            ],
        }
        arrays = self.q.decode_snapshot(raw)
        self.assertIn("decoder_bank_1_buffer_0", arrays)
        self.assertIn("tail_decoder_bank_1_buffer_0", arrays)
        raw["tail_decoder_outputs"].pop()
        with self.assertRaisesRegex(
            self.q.QualificationError, "tail decoder.*coverage"
        ):
            self.q.decode_snapshot(raw)

    def test_ratio_aggregation_requires_finite_unity_and_complete_primary_coverage(self):
        calls = [
            {"selected_rows": np.array([0, 0], np.int32),
             "ratios": np.ones((2, 2), np.float32)},
            {"selected_rows": np.array([1, 0], np.int32),
             "ratios": np.ones((2, 2), np.float32)},
        ]
        verdict = self.q.validate_ratio_calls(
            calls, primary_rows={0, 1}, frozen_rows={2, 3}, atol=1e-6)
        self.assertEqual(verdict["covered_primary_rows"], [0, 1])

        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                calls[:1], primary_rows={0, 1}, frozen_rows={2, 3}, atol=1e-6)
        bad = [{"selected_rows": np.array([0], np.int32),
                "ratios": np.array([[1.01]], np.float32)}]
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                bad, primary_rows={0}, frozen_rows={1}, atol=1e-6)
        nonfinite = [{"selected_rows": np.array([0], np.int32),
                      "ratios": np.array([[np.nan]], np.float32)}]
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                nonfinite, primary_rows={0}, frozen_rows={1}, atol=1e-6)
        frozen = [{"selected_rows": np.array([2], np.int32),
                   "ratios": np.ones((1, 2), np.float32)}]
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_ratio_calls(
                frozen, primary_rows={0}, frozen_rows={2}, atol=1e-6)

    def test_each_ratio_attempt_refreshes_and_consumes_one_tail_record(self):
        source = RUNNER.read_text(encoding="utf-8")
        body = source[
            source.index("def _measure_ratio("):
            source.index("def _measure_throughput(")
        ]
        loop = body[body.index("while covered != primary_rows"):]
        rollout_at = loop.index("_C.rollouts(pufferl)")
        train_at = loop.index("_C.train(pufferl)")
        consumed_at = loop.index('arrays[f"tail_valid_after_train_{calls}"]')
        integrity_at = loop.index("bind_transition_integrity(")
        self.assertLess(rollout_at, train_at)
        self.assertLess(train_at, consumed_at)
        self.assertLess(consumed_at, integrity_at)
        self.assertIn('arrays[f"advantages_{calls}"]', loop)
        self.assertIn("TAIL_FLOAT_SNAPSHOT_FIELDS", loop)
        self.assertIn('arrays[f"{key}_{calls}"]', loop)

    def test_weight_identity_and_throughput_comparison_are_fail_closed(self):
        digest = hashlib.sha256(b"same weights").hexdigest()
        self.q.validate_weight_identity(digest, digest)
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_weight_identity(digest, "0" * 64)

        baseline = {
            "host": "rtx2070", "gpu": "RTX 2070",
            "gpu_uuid": "GPU-00000000", "precision_bytes": 4,
            "config": {"cudagraphs": 10, "vec": {"total_agents": 4096}},
            "steps_per_second": 1000.0,
            "hard_integrity_zero": True,
            "steps": 1000, "elapsed_seconds": 1.0,
            "median_rollout_seconds": 0.1, "p95_rollout_seconds": 0.2,
            "hard_integrity": {
                key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
            },
            "warmup_hard_integrity_zero": True,
            "warmup_hard_integrity": {
                key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
            },
            "tail_records_explicitly_discarded": 10,
            "utilization": {},
        }
        candidate = dict(baseline, steps=950, steps_per_second=950.0)
        self.q.validate_throughput(
            candidate, baseline, max_regression_fraction=0.10)
        candidate["steps"] = 899
        candidate["steps_per_second"] = 899.0
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_throughput(
                candidate, baseline, max_regression_fraction=0.10)
        # A faster number measured on a different GPU or config is not a pass.
        for key, value in (
            ("gpu", "different"),
            ("gpu_uuid", "GPU-different"),
            ("host", "other-host"),
            ("config", {"cudagraphs": 10, "vec": {"total_agents": 512}}),
        ):
            candidate = dict(
                baseline, steps=2000, steps_per_second=2000.0, **{key: value}
            )
            with self.subTest(key=key), self.assertRaisesRegex(
                self.q.QualificationError, key
            ):
                self.q.validate_throughput(
                    candidate, baseline, max_regression_fraction=0.10)
        # Missing integrity counters cannot be read as zero counters.
        candidate = dict(baseline, hard_integrity={})
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_throughput(
                candidate, baseline, max_regression_fraction=0.10)

    # -------------------------------------------------- integrity counters

    def test_hard_integrity_rejects_redundant_nonzero_reward_counters(self):
        self.assertEqual(self.q.HARD_INTEGRITY_KEYS, (
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
        ))
        counters = (
            "reward_clip_signed_delta",
            "reward_clipped_samples_per_episode",
            "reward_clip_terminal_samples_per_episode",
            "reward_clip_nonterminal_samples_per_episode",
            "reward_nonfinite_samples_per_episode",
        )
        for key in counters:
            integrity = {
                field: 0.0 for field in self.q.HARD_INTEGRITY_KEYS
            }
            integrity[key] = 1e-12
            with self.subTest(key=key), self.assertRaisesRegex(
                    self.q.QualificationError, key):
                self.q.validate_hard_integrity(integrity)
        missing = {
            field: 0.0 for field in self.q.HARD_INTEGRITY_KEYS
            if field != "reward_clip_signed_delta"
        }
        with self.assertRaisesRegex(
                self.q.QualificationError, "reward_clip_signed_delta"):
            self.q.validate_hard_integrity(missing)

    def test_every_transition_cell_requires_bound_exact_zero_integrity(self):
        self.assertEqual(
            self.q.TRANSITION_CELL_KINDS,
            frozenset({
                "rollout", "terminal_auto", "terminal_control", "ratio",
                "throughput",
            }),
        )
        integrity = {key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS}
        for kind in sorted(self.q.TRANSITION_CELL_KINDS):
            payload = {
                "hard_integrity": dict(integrity),
                "hard_integrity_zero": True,
            }
            record = {
                "kind": kind,
                **({"throughput": payload} if kind == "throughput" else payload),
            }
            with self.subTest(kind=kind):
                self.q.validate_transition_cell_integrity(record, kind)

            bad = json.loads(json.dumps(record))
            target = bad["throughput"] if kind == "throughput" else bad
            target["hard_integrity"]["reward_clip_signed_delta"] = 1e-12
            with self.subTest(kind=kind, mutation="nonzero"), self.assertRaisesRegex(
                    self.q.QualificationError, "reward_clip_signed_delta"):
                self.q.validate_transition_cell_integrity(bad, kind)

            missing = json.loads(json.dumps(record))
            target = missing["throughput"] if kind == "throughput" else missing
            del target["hard_integrity"]
            with self.subTest(kind=kind, mutation="missing"), self.assertRaises(
                    self.q.QualificationError):
                self.q.validate_transition_cell_integrity(missing, kind)

        with self.assertRaisesRegex(
                self.q.QualificationError, "does not execute transitions"):
            self.q.validate_transition_cell_integrity(
                {"kind": "construction"}, "construction"
            )

    def test_integrity_probe_runs_bounded_rollouts_and_binds_record(self):
        integrity = {key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS}
        backend = mock.Mock()
        backend.log.return_value = {"env": integrity}
        pufferl = object()
        record = {}

        self.q.bind_transition_integrity(
            backend, pufferl, record, additional_rollouts=16
        )

        self.assertEqual(backend.rollouts.call_count, 16)
        backend.log.assert_called_once_with(pufferl)
        self.assertEqual(record["hard_integrity"], integrity)
        self.assertIs(record["hard_integrity_zero"], True)

    # --------------------------------------------------- compiled provenance

    def test_qualification_surface_rejects_either_partial_binding(self):
        for binding in self.q.QUALIFICATION_SURFACE_BINDINGS:
            with self.subTest(binding=binding), self.assertRaisesRegex(
                self.q.QualificationError, "qualification surface is partial"
            ):
                self.q.qualification_surface_state(
                    SimpleNamespace(**{binding: object()})
                )
        self.assertIs(self.q.qualification_surface_state(SimpleNamespace()), False)
        self.assertIs(
            self.q.qualification_surface_state(SimpleNamespace(**{
                binding: object()
                for binding in self.q.QUALIFICATION_SURFACE_BINDINGS
            })),
            True,
        )

    def test_backend_identity_changes_with_selfplay_and_rejects_its_absence(self):
        self.assertEqual(
            self.q.BACKEND_SOURCE_FILES,
            (
                "build.sh",
                "pufferlib/pufferl.py",
                "pufferlib/selfplay.py",
                "pufferlib/sweep.py",
                "pufferlib/torch_pufferl.py",
                "src/bindings.cu",
                "src/bindings_cpu.cpp",
                "src/cudnn_conv2d.cu",
                "src/kernels.cu",
                "src/models.cu",
                "src/muon.cu",
                "src/ocean.cu",
                "src/pufferlib.cu",
                "src/tensor.h",
                "src/vecenv.h",
            ),
        )
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            for index, relative in enumerate(self.q.BACKEND_SOURCE_FILES):
                path = puffer / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"surface-{index}\n".encode())
            before = self.q.backend_source_hash(puffer)
            selfplay = puffer / "pufferlib/selfplay.py"
            selfplay.write_bytes(b"changed-selfplay-semantics\n")
            self.assertNotEqual(before, self.q.backend_source_hash(puffer))
            selfplay.unlink()
            with self.assertRaises(self.q.QualificationError):
                self.q.backend_source_hash(puffer)

    def test_compiled_digest_must_equal_source_and_installed_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            for index, relative in enumerate(self.q.BACKEND_SOURCE_FILES):
                path = puffer / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"candidate-{index}\n".encode())
            module = puffer / "pufferlib/_C.so"
            module.write_bytes(b"candidate-module\n")
            snapshot = puffer / "ocean/bloodbowl/.content_hash"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_text("b" * 64 + "\n", encoding="ascii")

            compiled = self.q.backend_source_hash(puffer)
            backend = SimpleNamespace(
                exact_action_source_hash=compiled,
                environment_source_hash="b" * 64,
                observation_abi="obs-v6",
                observation_version=6,
                action_abi="exact-joint-v1",
                rollout_transition_contract=
                    self.q.ROLLOUT_TRANSITION_CONTRACT,
                environment_config_schema=
                    self.q.ENVIRONMENT_CONFIG_SCHEMA,
                strict_env_config_testing=False,
                precision_bytes=4,
                env_name="bloodbowl",
                qualification_recurrent_state=object(),
                qualification_policy_weights=object(),
                qualification_snapshot=object(),
                qualification_entropy_gradient_state=object(),
                qualification_entropy_overrun_state=object(),
                qualification_graph_execution=object(),
                qualification_consume_tail=object(),
            )
            identity = self.q._module_identity(backend, module, puffer)
            self.assertIs(identity["qualification_surface"], True)
            self.assertEqual(identity["backend_sources_sha256"], compiled)
            self.assertEqual(
                identity["installed_snapshot_sha256"],
                identity["environment_sha256"],
            )
            self.q.validate_module_identity(identity)

            # A module built from other bytes than the tree it sits in fails,
            # and so does one whose installed snapshot lags its own build.
            with self.assertRaisesRegex(
                self.q.QualificationError, "backend source digest"
            ):
                self.q.validate_module_identity(
                    dict(identity, compiled_backend_sha256="c" * 64)
                )
            with self.assertRaisesRegex(
                self.q.QualificationError, "installed environment digest"
            ):
                self.q.validate_module_identity(
                    dict(identity, installed_snapshot_sha256="c" * 64)
                )
            with self.assertRaisesRegex(
                self.q.QualificationError, "backend_sources_sha256"
            ):
                incomplete = dict(identity)
                del incomplete["backend_sources_sha256"]
                self.q.validate_module_identity(incomplete)

    def test_module_identity_requires_exact_bloodbowl_obs_v6_fp32_lineage(self):
        digest = "a" * 64
        identity = {
            "module": "/puffer/pufferlib/_C.so",
            "puffer_root": "/puffer",
            "module_sha256": digest,
            "compiled_backend_sha256": digest,
            "backend_sources_sha256": digest,
            "environment_sha256": "b" * 64,
            "installed_snapshot_sha256": "b" * 64,
            "observation_abi": "obs-v6",
            "observation_version": 6,
            "action_abi": "exact-joint-v1",
            "rollout_transition_contract":
                self.q.ROLLOUT_TRANSITION_CONTRACT,
            "environment_config_schema": self.q.ENVIRONMENT_CONFIG_SCHEMA,
            "strict_env_config_testing": False,
            "precision_bytes": 4,
            "compiled_env": "bloodbowl",
            "qualification_surface": True,
        }
        self.q.validate_module_identity(identity)
        # obs-v4, obs-v5 and obs-v6 are all 2782 bytes: only this provenance
        # separates them, and BF16 cannot satisfy the ratio contract.
        for key, value in (
            ("compiled_env", "other"),
            ("observation_abi", "obs-v4"),
            ("observation_version", 4),
            ("action_abi", "marginal"),
            ("rollout_transition_contract", "other"),
            ("environment_config_schema", "other"),
            ("strict_env_config_testing", True),
            ("strict_env_config_testing", 0),
            ("precision_bytes", 2),
            ("environment_sha256", "bad"),
            ("qualification_surface", False),
            ("module", "/elsewhere/pufferlib/_C.so"),
        ):
            with self.subTest(key=key), self.assertRaises(
                    self.q.QualificationError):
                self.q.validate_module_identity(dict(identity, **{key: value}))

    def test_strict_config_cell_set_has_exact_negative_and_positive_roles(self):
        self.assertEqual(
            self.q.STRICT_CONFIG_NEGATIVE_CELL_KINDS,
            (
                "strict_negative_create_vec",
                "strict_negative_create_pufferl",
            ),
        )
        self.assertEqual(
            self.q.STRICT_CONFIG_POSITIVE_CELL_KINDS,
            ("strict_positive_full", "strict_positive_sparse"),
        )
        self.assertIn("strict_environment_config", self.q.MANDATORY_GATES)

    def test_cuda_advantage_oracle_is_a_mandatory_authenticated_gate(self):
        self.assertIn("cuda_advantage_oracle", self.q.MANDATORY_GATES)
        evidence = {
            "schema_version": self.q.CUDA_ADVANTAGE_ORACLE_SCHEMA_VERSION,
            "contract": self.q.ROLLOUT_TRANSITION_CONTRACT,
            "device": "cuda",
            "precision_bytes": 4,
            "case_names": list(self.q.CUDA_ADVANTAGE_ORACLE_CASES),
            "case_count": len(self.q.CUDA_ADVANTAGE_ORACLE_CASES),
            "exact_once": True,
            "verifier_path": str(
                self.q.ROLLOUT_TRANSITION_VERIFIER.resolve()
            ),
            "verifier_sha256": self.q.sha256(
                self.q.ROLLOUT_TRANSITION_VERIFIER
            ),
        }
        accepted = self.q.validate_cuda_advantage_oracle_evidence(
            evidence,
            rehash_files=True,
        )
        self.assertEqual(
            accepted["case_names"],
            list(self.q.CUDA_ADVANTAGE_ORACLE_CASES),
        )
        mutations = (
            ("case_names", list(self.q.CUDA_ADVANTAGE_ORACLE_CASES[:-1])),
            ("case_count", len(self.q.CUDA_ADVANTAGE_ORACLE_CASES) - 1),
            ("exact_once", False),
            ("precision_bytes", 2),
            ("verifier_sha256", "0" * 64),
        )
        for key, value in mutations:
            with self.subTest(key=key), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_cuda_advantage_oracle_evidence(
                    dict(evidence, **{key: value}),
                    rehash_files=True,
                )

    def test_rollout_cells_execute_cuda_advantage_oracle_before_acceptance(self):
        source = RUNNER.read_text(encoding="utf-8")
        body = source[
            source.index("def run_cell("):
            source.index("def _git_output(")
        ]
        self.assertIn(
            'if args.kind == "rollout":',
            body,
        )
        self.assertIn(
            "execute_cuda_advantage_oracle(_C)",
            body,
        )
        parent = source[
            source.index("def _run_worker("):
            source.index("def _require_same_identity(")
        ]
        self.assertIn(
            "validate_cuda_advantage_oracle_evidence(",
            parent,
        )

    def test_integrated_rollout_train_oracle_reconstructs_every_slot(self):
        self.assertEqual(
            self.q.HETEROGENEOUS_HORIZON,
            8,
            "the real rollout-to-train oracle must exercise the vector kernel",
        )
        arrays, state, config = integrated_advantage_fixture(self.q)
        accepted = self.q.validate_integrated_advantage_oracle(
            arrays,
            state,
            config,
            atol=2.0e-5,
        )
        self.assertEqual(accepted["nonzero_primary_last_rows"], [0, 1, 4, 5])
        self.assertTrue(accepted["frozen_rows_exact_zero"])
        self.assertTrue(accepted["tail_consumed"])

        mutations = []
        changed = {key: value.copy() for key, value in arrays.items()}
        changed["advantages_after_train"][0, -1] = np.float32(0.0)
        mutations.append(("zero final primary slot", changed, state, config))
        changed = {key: value.copy() for key, value in arrays.items()}
        changed["advantages_after_train"][0, 0] += np.float32(0.25)
        mutations.append(("wrong earlier primary slot", changed, state, config))
        changed = {key: value.copy() for key, value in arrays.items()}
        changed["advantages_after_train"][2, 0] = np.nextafter(
            np.float32(0.0),
            np.float32(1.0),
        )
        mutations.append(("nonzero frozen slot", changed, state, config))
        changed = {key: value.copy() for key, value in arrays.items()}
        changed["tail_valid_after_train"][0] = np.int32(1)
        mutations.append(("unconsumed tail", changed, state, config))
        changed = {key: value.copy() for key, value in arrays.items()}
        changed["tail_rewards"][0] += np.float32(1.0)
        mutations.append(("wrong tail wiring", changed, state, config))
        changed = {key: value.copy() for key, value in arrays.items()}
        changed["rewards"][1, 0] = np.float32(2.0)
        mutations.append(("wrong delayed field wiring", changed, state, config))

        for label, changed, changed_state, changed_config in mutations:
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_integrated_advantage_oracle(
                    changed,
                    changed_state,
                    changed_config,
                    atol=2.0e-5,
                )

    def test_integrated_oracle_rejects_degenerate_last_slot_and_open_config(self):
        arrays, state, config = integrated_advantage_fixture(self.q)
        degenerate = {key: value.copy() for key, value in arrays.items()}
        degenerate["tail_rewards"][[0, 1, 4, 5]] = np.float32(0.0)
        degenerate["advantages_after_train"].fill(np.float32(0.0))
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "nondegenerate|non-degenerate|last",
        ):
            self.q.validate_integrated_advantage_oracle(
                degenerate,
                state,
                config,
                atol=2.0e-5,
            )

        for path, value in (
            (("train", "learning_rate"), 1.0e-4),
            (("train", "replay_ratio"), 2),
            (("train", "minibatch_size"), 8),
            (("train", "anneal_lr"), True),
            (("train", "gamma"), 0.9),
            (("train", "gae_lambda"), 0.8),
            (("train", "vtrace_rho_clip"), 0.75),
            (("train", "vtrace_c_clip"), 0.5),
            (("reset_state",), False),
        ):
            changed = json.loads(json.dumps(config))
            target = changed
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_integrated_advantage_oracle(
                    arrays,
                    state,
                    changed,
                    atol=2.0e-5,
                )

    def test_graph_modes_require_full_and_last_advantage_parity(self):
        arrays, state, config = integrated_advantage_fixture(self.q)
        primary_rows, _ = self.q.derive_row_partition(
            state,
            total_agents=8,
        )
        accepted = self.q.compare_integrated_advantage_parity(
            arrays["advantages_after_train"],
            arrays["advantages_after_train"].copy(),
            primary_rows=primary_rows,
            horizon=self.q.HETEROGENEOUS_HORIZON,
            atol=2.0e-5,
        )
        self.assertEqual(accepted["full_max_abs"], 0.0)
        self.assertEqual(accepted["last_slot_max_abs"], 0.0)

        for index in (
            (0, 0),
            (0, self.q.HETEROGENEOUS_HORIZON - 1),
        ):
            changed = arrays["advantages_after_train"].copy()
            changed[index] += np.float32(0.25)
            with self.subTest(index=index), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.compare_integrated_advantage_parity(
                    arrays["advantages_after_train"],
                    changed,
                    primary_rows=primary_rows,
                    horizon=self.q.HETEROGENEOUS_HORIZON,
                    atol=2.0e-5,
                )

    def test_integrated_rollout_train_oracle_is_parent_recomputed(self):
        source = RUNNER.read_text(encoding="utf-8")
        consume = source[
            source.index("def consume_heterogeneous_tail_record("):
            source.index("# ---------------------------------------------------------------- state evidence")
        ]
        self.assertIn("backend.train(pufferl)", consume)
        self.assertIn("qualification_snapshot", consume)
        self.assertIn("advantages_after_train", consume)
        worker = source[
            source.index("def _run_worker("):
            source.index("def _require_same_identity(")
        ]
        self.assertIn("validate_integrated_advantage_oracle(", worker)
        driver = source[
            source.index("def run_qualification("):
            source.index("def add_common_arguments(")
        ]
        self.assertIn("compare_integrated_advantage_parity(", driver)

    def test_strict_negative_records_require_exact_valueerror_diagnostic(self):
        record = {
            "strict_config_rejection": {
                "constructor": "create_vec",
                "exception_type": "ValueError",
                "field": "force_home_team",
                "domain": "integer -1 or 0..BB_TEAM_COUNT-1",
                "value": 30,
                "message": (
                    "force_home_team must be integer -1 or "
                    "0..BB_TEAM_COUNT-1; got 30"
                ),
                "expected_rejection": True,
            }
        }
        observed = self.q.validate_strict_rejection_record(
            record, constructor="create_vec"
        )
        self.assertEqual(observed["value"], 30)
        for field, value in (
            ("constructor", "create_pufferl"),
            ("exception_type", "RuntimeError"),
            ("expected_rejection", False),
            ("message", "CUDA device discovery failed"),
        ):
            with self.subTest(field=field), self.assertRaises(
                self.q.QualificationError
            ):
                changed = {"strict_config_rejection": dict(
                    record["strict_config_rejection"], **{field: value}
                )}
                self.q.validate_strict_rejection_record(
                    changed, constructor="create_vec"
                )

    def test_strict_positive_record_requires_both_closed_constructors(self):
        constructors = {
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
        record = {
            "strict_config_profile": "sparse",
            "strict_config_constructors": constructors,
        }
        self.assertEqual(
            self.q.validate_positive_strict_record(
                record, profile="sparse"
            ),
            constructors,
        )
        changed = {
            "strict_config_profile": "sparse",
            "strict_config_constructors": {
                **constructors,
                "create_vec": {
                    **constructors["create_vec"],
                    "closed": False,
                },
            },
        }
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_positive_strict_record(
                changed, profile="sparse"
            )

    def test_negative_constructor_worker_accepts_only_expected_valueerror(self):
        class Backend:
            def create_vec(self, config, *, gpu):
                self.config = config
                self.gpu = gpu
                raise ValueError(
                    "force_home_team must be integer -1 or "
                    "0..BB_TEAM_COUNT-1; got 30"
                )

        backend = Backend()
        config = {"env": {"force_home_team": 30}}
        record = self.q._exercise_expected_strict_rejection(
            backend,
            config,
            constructor="create_vec",
            invalid_team=30,
        )
        self.assertIs(record["expected_rejection"], True)
        self.assertEqual(backend.gpu, 1)
        self.assertIs(backend.config, config)

        backend.create_vec = lambda config, *, gpu: (_ for _ in ()).throw(
            RuntimeError("CUDA device discovery failed")
        )
        with self.assertRaisesRegex(
            self.q.QualificationError, "unrelated failure"
        ):
            self.q._exercise_expected_strict_rejection(
                backend,
                config,
                constructor="create_vec",
                invalid_team=30,
            )

    def test_full_and_sparse_strict_profiles_are_closed_and_numeric(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            config = puffer / "config/bloodbowl.ini"
            config.parent.mkdir(parents=True)
            config.write_text(
                "[env]\n"
                + "\n".join(
                    f"key_{index} = {index}"
                    for index in range(self.q.ENVIRONMENT_CONFIG_KEY_COUNT)
                )
                + "\n",
                encoding="utf-8",
            )
            observed = self.q._installed_environment_config(puffer)
            self.assertEqual(
                len(observed), self.q.ENVIRONMENT_CONFIG_KEY_COUNT
            )
            self.assertEqual(observed["key_50"], 50.0)

            config.write_text(
                "[env]\n"
                + "\n".join(
                    (
                        "seed = nan"
                        if index == 0
                        else f"key_{index} = {index}"
                    )
                    for index in range(self.q.ENVIRONMENT_CONFIG_KEY_COUNT)
                )
                + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                self.q.QualificationError, "not finite"
            ):
                self.q._installed_environment_config(puffer)

    def test_invalid_team_value_is_derived_from_the_installed_enum(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary)
            header = puffer / "ocean/bloodbowl/bb/gen_teams.h"
            header.parent.mkdir(parents=True)
            header.write_text(
                "// generated team names include UTF-8: Résumé\n"
                "typedef enum {\n"
                "  BB_TEAM_ONE,\n"
                "  BB_TEAM_TWO,\n"
                "  BB_TEAM_THREE,\n"
                "  BB_TEAM_COUNT\n"
                "} bb_team_id;\n",
                encoding="utf-8",
            )
            self.assertEqual(self.q._installed_team_count(puffer), 3)

    def test_strict_cuda_stage_matrix_rejects_before_every_downstream_stage(self):
        backend = FakeStrictStageBackend(invalid_team=30)
        observed = self.q._exercise_strict_cuda_stage_order(
            backend,
            seed=123,
            invalid_team=30,
        )
        self.assertEqual(
            {
                (record["constructor"], record["hazard"])
                for record in observed["invalid_cases"]
            },
            {
                (constructor, hazard)
                for constructor in ("create_vec", "create_pufferl")
                for hazard in self.q.STRICT_STAGE_HAZARDS
            },
        )
        for record in observed["invalid_cases"]:
            self.assertEqual(record["stages"], self.q.STRICT_STAGE_REJECTED)
            self.assertIs(record["constructed"], False)
        self.assertEqual(
            observed["positive_controls"]["create_vec"]["stages"],
            self.q.STRICT_STAGE_POSITIVE["create_vec"],
        )
        self.assertEqual(
            observed["positive_controls"]["create_pufferl"]["stages"],
            self.q.STRICT_STAGE_POSITIVE["create_pufferl"],
        )
        self.assertEqual(observed["cleanup_stages"], self.q.STRICT_STAGE_ZERO)
        self.assertEqual(backend.closed_vecs, 1)
        self.assertEqual(backend.closed_pufferls, 1)

    def test_strict_cuda_stage_matrix_detects_one_downstream_leak(self):
        backend = FakeStrictStageBackend(
            invalid_team=30,
            leak_constructor="create_pufferl",
        )
        with self.assertRaisesRegex(
            self.q.QualificationError, "rejection stages differ"
        ):
            self.q._exercise_strict_cuda_stage_order(
                backend,
                seed=123,
                invalid_team=30,
            )

    def test_strict_cuda_stage_counters_have_an_exact_typed_schema(self):
        clean = dict(self.q.STRICT_STAGE_ZERO)
        self.q._require_strict_stage_counts(
            clean,
            self.q.STRICT_STAGE_ZERO,
            label="test",
        )
        mutations = []
        missing = dict(clean)
        missing.pop("normalize_calls")
        mutations.append(missing)
        mutations.append({**clean, "unexpected": 0})
        mutations.append({**clean, "normalize_calls": True})
        mutations.append({**clean, "normalize_calls": -1})
        for mutation in mutations:
            with self.subTest(mutation=mutation), self.assertRaises(
                self.q.QualificationError
            ):
                self.q._require_strict_stage_counts(
                    mutation,
                    self.q.STRICT_STAGE_ZERO,
                    label="test",
                )

    def _strict_stage_evidence_fixture(self, *, root="/isolated/PufferLib"):
        digest = "a" * 64
        identity = {
            "module": f"{root}/pufferlib/_C.so",
            "puffer_root": root,
            "module_sha256": digest,
            "compiled_backend_sha256": digest,
            "backend_sources_sha256": digest,
            "environment_sha256": "b" * 64,
            "installed_snapshot_sha256": "b" * 64,
            "observation_abi": "obs-v6",
            "observation_version": 6,
            "action_abi": "exact-joint-v1",
            "rollout_transition_contract":
                self.q.ROLLOUT_TRANSITION_CONTRACT,
            "environment_config_schema": self.q.ENVIRONMENT_CONFIG_SCHEMA,
            "strict_env_config_testing": True,
            "precision_bytes": 4,
            "compiled_env": "bloodbowl",
            "qualification_surface": True,
            "gpu": 1,
            "strict_stage_surface": True,
        }
        receipt = {
            "schema_version": self.q.STRICT_STAGE_SCHEMA_VERSION,
            "evidence_kind": self.q.STRICT_STAGE_RECEIPT_KIND,
            "puffer_root": root,
            "git_head": self.q.PINNED_PUFFER_COMMIT,
            "initial_status": "",
            "initial_status_sha256": hashlib.sha256(b"").hexdigest(),
            "separate_from_repo_vendor_checkout": True,
            "confirmed_isolated_test_checkout": True,
            "build_absent": True,
            "environment_absent": True,
            "module_absent": True,
            "detached_head": True,
            "interpreter": f"{root}/.venv/bin/python",
            "interpreter_identity": {
                "executable": f"{root}/.venv/bin/python",
                "executable_sha256": "9" * 64,
                "prefix": f"{root}/.venv",
                "base_prefix": "/usr/local",
                "ext_suffix": ".so",
                "python_version": "3.14.0",
                "pybind11_path": (
                    f"{root}/.venv/lib/python/site-packages/"
                    "pybind11/__init__.py"
                ),
                "numpy_path": (
                    f"{root}/.venv/lib/python/site-packages/"
                    "numpy/__init__.py"
                ),
            },
            "origin": "https://github.com/PufferAI/PufferLib.git",
        }
        invalid_cases = []
        for constructor in ("create_vec", "create_pufferl"):
            for hazard in self.q.STRICT_STAGE_HAZARDS:
                invalid_cases.append(
                    {
                        "constructor": constructor,
                        "hazard": hazard,
                        "malformed_path": {
                            "vec": "vec.total_agents",
                            "train": "train",
                            "policy": "policy",
                            "device": "gpu_id",
                        }[hazard],
                        "invalid_team": 30,
                        "exception_type": "ValueError",
                        "message": (
                            "force_home_team must be integer -1 or "
                            "0..BB_TEAM_COUNT-1; got 30"
                        ),
                        "expected_rejection": True,
                        "constructed": False,
                        "stages": dict(self.q.STRICT_STAGE_REJECTED),
                    }
                )
        return {
            "schema_version": self.q.STRICT_STAGE_SCHEMA_VERSION,
            "evidence_kind": self.q.STRICT_STAGE_EVIDENCE_KIND,
            "qualification_only": True,
            "mandatory_external_gpu_gate": True,
            "accepted": True,
            "identity": identity,
            "cuda_runtime_preflight": cuda_runtime_evidence(),
            "isolation": {
                "receipt": receipt,
                "receipt_sha256": "c" * 64,
            },
            "patch_identity": {
                "puffer_git_head": self.q.PINNED_PUFFER_COMMIT,
                "strict_environment_config_patch": {
                    "path": "/repo/training/puffer_strict_environment_config.patch",
                    "sha256": "d" * 64,
                    "reverse_applicable": True,
                },
                "rollout_transition_patch": {
                    "path": (
                        "/repo/training/"
                        "puffer_rollout_transition_closure.patch"
                    ),
                    "sha256": "1" * 64,
                    "reverse_applicable": True,
                },
                "qualifier": {
                    "path": "/repo/tools/qualify_recurrent_cuda.py",
                    "sha256": "e" * 64,
                },
                "compiled_backend_source_ledger": {
                    "path": "/repo/training/puffer_compiled_backend_sources.txt",
                    "sha256": "f" * 64,
                },
            },
            "invalid_cases": invalid_cases,
            "positive_controls": {
                constructor: {
                    "constructor": constructor,
                    "constructed": True,
                    "closed": True,
                    "stages": dict(
                        self.q.STRICT_STAGE_POSITIVE[constructor]
                    ),
                }
                for constructor in ("create_vec", "create_pufferl")
            },
            "cleanup_stages": dict(self.q.STRICT_STAGE_ZERO),
            "production_identity_rejection": {
                "rejected": True,
                "exception_type": "QualificationError",
                "message": (
                    "compiled strict-config module must have the production role"
                ),
            },
            "host": "gpu-host",
            "platform": "Linux",
            "seed": 123,
        }

    def test_strict_stage_evidence_validator_is_fail_closed(self):
        evidence = self._strict_stage_evidence_fixture()
        self.q.validate_strict_stage_evidence(evidence)
        mutations = (
            (
                "schema",
                lambda value: value.update(
                    schema_version=self.q.STRICT_STAGE_SCHEMA_VERSION + 1
                ),
            ),
            ("accepted", lambda value: value.update(accepted=False)),
            (
                "test role",
                lambda value: value["identity"].update(
                    strict_env_config_testing=False
                ),
            ),
            (
                "counter",
                lambda value: value["invalid_cases"][0]["stages"].update(
                    create_static_vec_calls=1
                ),
            ),
            (
                "patch hash",
                lambda value: value["patch_identity"]["qualifier"].update(
                    sha256="bad"
                ),
            ),
            (
                "production rejection",
                lambda value: value["production_identity_rejection"].update(
                    rejected=False
                ),
            ),
        )
        for label, mutate in mutations:
            changed = json.loads(json.dumps(evidence))
            mutate(changed)
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_strict_stage_evidence(changed)

    def test_strict_stage_identity_requires_exact_integer_scalars_and_keys(self):
        evidence = self._strict_stage_evidence_fixture()
        mutations = (
            (
                "gpu bool",
                lambda value: value["identity"].update(gpu=True),
            ),
            (
                "gpu float",
                lambda value: value["identity"].update(gpu=1.0),
            ),
            (
                "schema float",
                lambda value: value.update(
                    schema_version=float(self.q.STRICT_STAGE_SCHEMA_VERSION)
                ),
            ),
            (
                "observation version float",
                lambda value: value["identity"].update(
                    observation_version=6.0
                ),
            ),
            (
                "precision float",
                lambda value: value["identity"].update(precision_bytes=4.0),
            ),
            (
                "seed float",
                lambda value: value.update(seed=123.0),
            ),
            (
                "counter float",
                lambda value: value["invalid_cases"][0]["stages"].update(
                    normalize_calls=1.0
                ),
            ),
            (
                "invalid team float",
                lambda value: value["invalid_cases"][0].update(
                    invalid_team=30.0
                ),
            ),
            (
                "extra identity key",
                lambda value: value["identity"].update(unexpected=True),
            ),
        )
        for label, mutate in mutations:
            changed = json.loads(json.dumps(evidence))
            mutate(changed)
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_strict_stage_evidence(changed)

    def test_strict_stage_hazard_names_are_bound_to_exact_malformed_paths(self):
        evidence = self._strict_stage_evidence_fixture()
        expected = {
            "vec": "vec.total_agents",
            "train": "train",
            "policy": "policy",
            "device": "gpu_id",
        }
        for hazard, wrong_path in (
            ("vec", expected["train"]),
            ("train", expected["policy"]),
            ("policy", expected["device"]),
            ("device", expected["vec"]),
        ):
            changed = json.loads(json.dumps(evidence))
            record = next(
                item
                for item in changed["invalid_cases"]
                if item["constructor"] == "create_pufferl"
                and item["hazard"] == hazard
            )
            record["malformed_path"] = wrong_path
            with self.subTest(hazard=hazard), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_strict_stage_evidence(changed)

    def test_strict_stage_invalid_team_matches_installed_bb_team_count(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = (pathlib.Path(temporary) / "PufferLib").resolve()
            header = root / "ocean/bloodbowl/bb/gen_teams.h"
            header.parent.mkdir(parents=True)
            header.write_text(
                "typedef enum {\n"
                "  BB_TEAM_ONE,\n"
                "  BB_TEAM_TWO,\n"
                "  BB_TEAM_THREE,\n"
                "  BB_TEAM_COUNT\n"
                "} bb_team_id;\n",
                encoding="utf-8",
            )
            evidence = self._strict_stage_evidence_fixture(root=str(root))
            for record in evidence["invalid_cases"]:
                record["invalid_team"] = 30
            interpreter = root / ".venv/bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"isolated-python")
            for key in ("pybind11_path", "numpy_path"):
                dependency = pathlib.Path(
                    evidence["isolation"]["receipt"][
                        "interpreter_identity"
                    ][key]
                )
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_bytes(b"dependency")
            evidence["isolation"]["receipt"]["interpreter_identity"][
                "executable_sha256"
            ] = self.q.sha256(interpreter)
            with self.assertRaisesRegex(
                self.q.QualificationError,
                "BB_TEAM_COUNT|invalid team",
            ):
                self.q.validate_strict_stage_evidence(
                    evidence,
                    expected_puffer_root=root,
                    rehash_files=True,
                )

    def test_strict_stage_evidence_rejects_oversized_strings(self):
        evidence = self._strict_stage_evidence_fixture()
        oversized = "x" * (self.q.STRICT_STAGE_MAX_JSON_BYTES + 1)
        mutations = (
            ("host", lambda value: value.update(host=oversized)),
            ("platform", lambda value: value.update(platform=oversized)),
            (
                "patch path",
                lambda value: value["patch_identity"]["qualifier"].update(
                    path=oversized
                ),
            ),
            (
                "production rejection",
                lambda value: value["production_identity_rejection"].update(
                    message=(
                        "compiled strict-config module must have the "
                        "production role " + oversized
                    )
                ),
            ),
        )
        for label, mutate in mutations:
            changed = json.loads(json.dumps(evidence))
            mutate(changed)
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_strict_stage_evidence(changed)

    def test_oversized_strict_stage_evidence_is_rejected_before_json_parse(self):
        with tempfile.TemporaryDirectory() as temporary:
            evidence = pathlib.Path(temporary) / "STRICT_STAGE_ORDER.json"
            evidence.write_bytes(
                b'{"padding":"'
                + b"x" * self.q.STRICT_STAGE_MAX_JSON_BYTES
                + b'"}'
            )
            with mock.patch.object(
                self.q.json,
                "loads",
                side_effect=AssertionError("oversized JSON was parsed"),
            ) as loads, self.assertRaisesRegex(
                self.q.QualificationError,
                "bytes|large|limit|size",
            ):
                self.q._read_json(
                    evidence,
                    maximum_bytes=self.q.STRICT_STAGE_MAX_JSON_BYTES,
                )
            loads.assert_not_called()

    def test_strict_stage_receipt_and_evidence_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            target = directory / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            for name in ("ISOLATION.json", "STRICT_STAGE_ORDER.json"):
                artifact = directory / name
                artifact.symlink_to(target)
                with self.subTest(name=name), self.assertRaisesRegex(
                    self.q.QualificationError,
                    "regular non-symlink",
                ):
                    self.q._read_json(
                        artifact,
                        maximum_bytes=self.q.STRICT_STAGE_MAX_JSON_BYTES,
                        require_regular=True,
                    )

    def test_require_regular_json_rejects_path_swap_while_opening(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            artifact = directory / "cell.json"
            replacement = directory / "replacement.json"
            artifact.write_text('{"accepted":true}\n', encoding="utf-8")
            replacement.write_text('{"accepted":false}\n', encoding="utf-8")
            original_open = os.open

            def swap_then_open(path, *args, **kwargs):
                os.replace(replacement, artifact)
                return original_open(path, *args, **kwargs)

            with mock.patch.object(
                os,
                "open",
                new=swap_then_open,
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "changed type or identity while opening",
            ):
                self.q._read_json(artifact, require_regular=True)

    def test_strict_stage_atomic_json_is_bounded_and_non_destructive(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "evidence.json"
            with self.assertRaisesRegex(
                self.q.QualificationError, "limit is 64"
            ):
                self.q.write_bounded_json_atomic(
                    output,
                    {"message": "x" * 100},
                    maximum_bytes=64,
                )
            self.assertFalse(output.exists())
            self.assertEqual(list(output.parent.glob(".evidence.json.tmp.*")), [])

    def test_cell_json_writer_does_not_follow_predictable_temp_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            output = directory / "cell.json"
            victim = directory / "external-victim.json"
            original = b'{"authority":"external"}\n'
            victim.write_bytes(original)
            predictable = directory / f".cell.json.tmp.{os.getpid()}"
            predictable.symlink_to(victim)

            self.q.write_json_atomic(output, {"accepted": True})

            self.assertEqual(victim.read_bytes(), original)
            self.assertTrue(predictable.is_symlink())
            self.assertEqual(
                json.loads(output.read_text(encoding="utf-8")),
                {"accepted": True},
            )
            self.assertLessEqual(
                output.stat().st_size,
                self.q.CELL_MAX_JSON_BYTES,
            )

    def test_strict_stage_cli_requires_explicit_isolation_confirmation(self):
        common = [
            "strict-stage-order",
            "--isolated-puffer-root",
            "/tmp/PufferLib",
            "--output",
            "/tmp/evidence",
        ]
        with self.assertRaises(SystemExit):
            self.q.parse_args(common)
        parsed = self.q.parse_args(
            [*common, "--confirm-isolated-test-checkout"]
        )
        self.assertEqual(parsed.command, "strict-stage-order")
        self.assertIs(parsed.confirm_isolated_test_checkout, True)
        worker = self.q.parse_args(
            [
                "strict-stage-worker",
                "--puffer-root",
                "/tmp/PufferLib",
                "--output-json",
                "/tmp/evidence.json",
                "--isolation-receipt",
                "/tmp/receipt.json",
            ]
        )
        self.assertEqual(worker.command, "strict-stage-worker")

    def test_strict_stage_child_environment_strips_shell_and_python_injection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "PufferLib"
            interpreter = root / ".venv/bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"python")
            ambient = {
                "PATH": "/ambient/bin",
                "BASH_ENV": "/ambient/bash-env",
                "BASH_FUNC_python%%": "() { echo ambient-function; }",
                "ENV": "/ambient/sh-env",
                "BASHOPTS": "sourcepath",
                "SHELLOPTS": "braceexpand",
                "PYTHONHOME": "/ambient/python-home",
                "PYTHONPATH": "/ambient/python-path",
                "PYTHONSTARTUP": "/ambient/python-startup.py",
                "PYTHONINSPECT": "1",
                "PYTHONUSERBASE": "/ambient/python-user-base",
                "PYTHONWARNINGS": "error",
                "PYTHONMALLOC": "debug",
                "PYTHONHASHSEED": "0",
                "PYTHONNOUSERSITE": "0",
                "KEEP_ME": "yes",
            }
            with mock.patch.dict(
                self.q.os.environ,
                ambient,
                clear=True,
            ):
                environment = self.q._strict_stage_child_environment(
                    interpreter
                )
            for key in (
                "BASH_ENV",
                "BASH_FUNC_python%%",
                "ENV",
                "BASHOPTS",
                "SHELLOPTS",
                "PYTHONHOME",
                "PYTHONPATH",
                "PYTHONSTARTUP",
                "PYTHONINSPECT",
                "PYTHONUSERBASE",
                "PYTHONWARNINGS",
                "PYTHONMALLOC",
                "PYTHONHASHSEED",
            ):
                with self.subTest(key=key):
                    self.assertNotIn(key, environment)
            self.assertEqual(environment["PYTHONNOUSERSITE"], "1")
            self.assertEqual(
                environment["PUFFER_INSTALL_PYTHON"],
                str(interpreter.absolute()),
            )
            self.assertTrue(
                pathlib.Path(environment["PUFFER_INSTALL_PYTHON"]).is_absolute()
            )
            self.assertEqual(
                {
                    key
                    for key in environment
                    if key.startswith("PYTHON")
                },
                {"PYTHONNOUSERSITE"},
            )
            self.assertEqual(environment["KEEP_ME"], "yes")

    def test_strict_stage_sanitized_bash_resolves_checkout_python_not_function(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "PufferLib"
            interpreter = root / ".venv/bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            interpreter.chmod(0o755)
            bash_env = pathlib.Path(temporary) / "ambient-bash-env"
            bash_env.write_text(
                "python() { printf '%s\\n' ambient-function; }\n"
                "export -f python\n",
                encoding="utf-8",
            )
            ambient = {
                "PATH": "/usr/bin:/bin",
                "BASH_ENV": str(bash_env),
                "BASH_FUNC_python%%": (
                    "() { printf '%s\\n' ambient-exported-function; }"
                ),
                "ENV": str(bash_env),
                "BASHOPTS": "sourcepath",
                "SHELLOPTS": "braceexpand",
                "PYTHONHOME": "/ambient/python-home",
                "PYTHONPATH": "/ambient/python-path",
                "PYTHONSTARTUP": "/ambient/python-startup.py",
            }
            with mock.patch.dict(
                self.q.os.environ,
                ambient,
                clear=True,
            ):
                environment = self.q._strict_stage_child_environment(
                    interpreter
                )
            completed = subprocess.run(
                ["/bin/bash", "-c", "command -v python"],
                env=environment,
                text=True,
                capture_output=True,
                check=True,
                timeout=10,
            )
            self.assertEqual(completed.stdout.strip(), str(interpreter))

    def test_strict_stage_installer_cannot_fall_back_to_python3(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            root = directory / "PufferLib"
            venv_bin = root / ".venv/bin"
            ambient_bin = directory / "ambient-bin"
            venv_bin.mkdir(parents=True)
            ambient_bin.mkdir()
            selected_python = venv_bin / "python"
            ambient_python3 = ambient_bin / "python3"
            selected_python.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' selected >> \"$ROUTE_LOG\"\n"
                "exit 37\n",
                encoding="utf-8",
            )
            ambient_python3.write_text(
                "#!/bin/sh\n"
                "printf '%s\\n' ambient >> \"$ROUTE_LOG\"\n"
                "exit 38\n",
                encoding="utf-8",
            )
            selected_python.chmod(0o755)
            ambient_python3.chmod(0o755)
            command = [
                "/bin/bash",
                str(INSTALLER),
                "--state-bank-kind",
                "strict",
                "--state-bank",
                str(directory / "bank.bbs"),
                "--state-bank-sha256",
                "a" * 64,
                "--state-bank-producer-manifest",
                str(directory / "producer.json"),
                "--state-bank-producer-manifest-sha256",
                "b" * 64,
                "--state-bank-contract",
                str(directory / "contract.json"),
                "--state-bank-contract-sha256",
                "c" * 64,
            ]
            for variant in ("missing", "divergent"):
                python3 = venv_bin / "python3"
                python3.unlink(missing_ok=True)
                if variant == "divergent":
                    python3.write_text(
                        "#!/bin/sh\n"
                        "printf '%s\\n' divergent >> \"$ROUTE_LOG\"\n"
                        "exit 39\n",
                        encoding="utf-8",
                    )
                    python3.chmod(0o755)
                route_log = directory / f"{variant}.log"
                ambient = {
                    "PATH": f"{ambient_bin}{os.pathsep}/usr/bin:/bin",
                    "ROUTE_LOG": str(route_log),
                }
                with mock.patch.dict(
                    self.q.os.environ,
                    ambient,
                    clear=True,
                ):
                    environment = self.q._strict_stage_child_environment(
                        selected_python
                    )
                completed = subprocess.run(
                    command,
                    env=environment,
                    text=True,
                    capture_output=True,
                    timeout=10,
                )
                with self.subTest(variant=variant):
                    self.assertEqual(completed.returncode, 37)
                    self.assertEqual(
                        route_log.read_text(encoding="utf-8").splitlines(),
                        ["selected"],
                    )

    def test_strict_stage_children_share_one_sanitized_local_venv_environment(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = pathlib.Path(temporary)
            root = (temporary_path / "PufferLib").resolve()
            output = temporary_path / "evidence"
            interpreter = root / ".venv/bin/python"
            receipt_path = output / "ISOLATION.json"
            receipt = {"interpreter": str(interpreter)}
            args = SimpleNamespace(
                puffer_root=root,
                output=output,
                python=None,
                confirm_isolated_test_checkout=True,
                install_timeout_seconds=1.0,
                build_timeout_seconds=1.0,
                worker_timeout_seconds=1.0,
                seed=123,
            )
            ambient = {
                "PATH": "/ambient/bin",
                "VIRTUAL_ENV": "/ambient/venv",
                "PYTHONHOME": "/ambient/python-home",
                "PYTHONPATH": "/ambient/python-path",
                "KEEP_ME": "yes",
            }
            expected = {
                "PATH": f"{interpreter.parent}{os.pathsep}/ambient/bin",
                "VIRTUAL_ENV": str(interpreter.parent.parent),
                "PYTHONNOUSERSITE": "1",
                "PUFFER_STRICT_ENV_CONFIG_TESTING": "1",
                "PUFFER_INSTALL_PYTHON": str(interpreter),
                "KEEP_ME": "yes",
            }
            with mock.patch.dict(
                self.q.os.environ,
                ambient,
                clear=True,
            ), mock.patch.object(
                self.q,
                "_prepare_strict_stage_isolation",
                return_value=(
                    interpreter,
                    receipt_path,
                    receipt,
                    expected,
                ),
            ), mock.patch.object(
                self.q, "write_bounded_json_atomic"
            ), mock.patch.object(
                self.q, "_run_strict_stage_command"
            ) as run, mock.patch.object(
                self.q,
                "_git_output",
                return_value=self.q.PINNED_PUFFER_COMMIT,
            ), mock.patch.object(
                self.q, "_require_detached_head"
            ), mock.patch.object(
                self.q, "_read_json", return_value={}
            ), mock.patch.object(
                self.q, "validate_strict_stage_evidence"
            ), mock.patch.object(
                self.q, "_require_strict_patch_reverse_applicable"
            ), mock.patch.object(
                self.q,
                "_require_rollout_transition_patch_reverse_applicable",
            ), mock.patch("builtins.print"):
                self.assertEqual(self.q.run_strict_stage_order(args), 0)
            self.assertEqual(len(run.call_args_list), 3)
            child_environments = [
                call.kwargs.get("environment")
                for call in run.call_args_list
            ]
            self.assertEqual(child_environments, [expected, expected, expected])
            self.assertEqual(run.call_args_list[0].args[0][0], "/bin/bash")
            for environment in child_environments:
                self.assertNotIn("PYTHONHOME", environment)
                self.assertNotIn("PYTHONPATH", environment)

    def test_strict_stage_prebuild_probe_records_exact_interpreter_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = pathlib.Path(temporary)
            root = (temporary_path / "PufferLib").resolve()
            output = temporary_path / "evidence"
            (root / ".git").mkdir(parents=True)
            (root / "pufferlib").mkdir()
            (root / "build.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            venv = root / ".venv"
            interpreter = venv / "bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"checkout-local-python")
            interpreter.chmod(0o755)
            (venv / "pyvenv.cfg").write_text(
                "home = /usr/local/bin\n",
                encoding="utf-8",
            )
            pybind11_path = (
                venv / "lib/python/site-packages/pybind11/__init__.py"
            )
            numpy_path = venv / "lib/python/site-packages/numpy/__init__.py"
            pybind11_path.parent.mkdir(parents=True)
            numpy_path.parent.mkdir(parents=True)
            pybind11_path.write_text("", encoding="utf-8")
            numpy_path.write_text("", encoding="utf-8")
            identity = {
                "executable": str(interpreter),
                "executable_sha256": self.q.sha256(interpreter),
                "prefix": str(venv),
                "base_prefix": "/usr/local",
                "ext_suffix": ".cpython-test-x86_64-linux-gnu.so",
                "python_version": "3.14.0",
                "pybind11_path": str(pybind11_path),
                "numpy_path": str(numpy_path),
            }

            def git_output(_root, *arguments):
                if arguments == ("rev-parse", "--show-toplevel"):
                    return str(root)
                if arguments == ("rev-parse", "HEAD"):
                    return self.q.PINNED_PUFFER_COMMIT
                if arguments == (
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ):
                    return ""
                if arguments == ("symbolic-ref", "-q", "HEAD"):
                    return ""
                if arguments == ("config", "--get", "remote.origin.url"):
                    return "https://github.com/PufferAI/PufferLib.git"
                raise AssertionError(arguments)

            completed = mock.Mock(
                returncode=0,
                stdout=json.dumps(identity),
                stderr="",
            )

            def subprocess_run(command, **_kwargs):
                if command[:4] == [
                    "git",
                    "-C",
                    str(root),
                    "symbolic-ref",
                ]:
                    return mock.Mock(returncode=1, stdout="", stderr="")
                if command[:2] == ["python", "-c"]:
                    return completed
                if command[:4] == [
                    "/bin/bash",
                    "--noprofile",
                    "--norc",
                    "-c",
                ]:
                    return completed
                raise AssertionError(command)

            ambient = {
                "PATH": "/ambient/bin",
                "VIRTUAL_ENV": "/ambient/venv",
                "PYTHONHOME": "/ambient/python-home",
                "PYTHONPATH": "/ambient/python-path",
            }
            with mock.patch.dict(
                self.q.os.environ,
                ambient,
                clear=True,
            ), mock.patch.object(
                self.q,
                "_git_output",
                side_effect=git_output,
            ), mock.patch.object(
                self.q.subprocess,
                "run",
                side_effect=subprocess_run,
            ) as probe:
                selected, _, receipt, child_environment = (
                    self.q._prepare_strict_stage_isolation(
                        puffer_root=root,
                        output=output,
                        python=None,
                        confirmed=True,
                    )
                )
            self.assertEqual(selected, interpreter)
            self.assertEqual(
                set(receipt["interpreter_identity"]),
                {
                    "executable",
                    "executable_sha256",
                    "prefix",
                    "base_prefix",
                    "ext_suffix",
                    "python_version",
                    "pybind11_path",
                    "numpy_path",
                },
            )
            self.assertEqual(receipt["interpreter_identity"], identity)
            direct_probe_calls = [
                call
                for call in probe.call_args_list
                if call.args[0][:2] == ["python", "-c"]
            ]
            bash_probe_calls = [
                call
                for call in probe.call_args_list
                if call.args[0][:4]
                == ["/bin/bash", "--noprofile", "--norc", "-c"]
            ]
            self.assertEqual(len(direct_probe_calls), 1)
            self.assertEqual(len(bash_probe_calls), 1)
            command = direct_probe_calls[0].args[0]
            self.assertEqual(command[0], "python")
            for call in (*direct_probe_calls, *bash_probe_calls):
                self.assertEqual(call.kwargs["env"], child_environment)
            probe_environment = direct_probe_calls[0].kwargs["env"]
            self.assertEqual(
                probe_environment["PATH"].split(os.pathsep)[0],
                str(interpreter.parent),
            )
            self.assertEqual(probe_environment["VIRTUAL_ENV"], str(venv))
            self.assertNotIn("PYTHONHOME", probe_environment)
            self.assertNotIn("PYTHONPATH", probe_environment)

    def test_strict_stage_isolation_requires_detached_head(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = pathlib.Path(temporary)
            root = (temporary_path / "PufferLib").resolve()
            (root / ".git").mkdir(parents=True)
            (root / "pufferlib").mkdir()
            (root / "build.sh").write_text("#!/bin/sh\n", encoding="utf-8")
            interpreter = root / ".venv/bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"python")
            (root / ".venv/pyvenv.cfg").write_text("", encoding="utf-8")

            def git_output(_root, *arguments):
                if arguments == ("rev-parse", "--show-toplevel"):
                    return str(root)
                if arguments == ("rev-parse", "HEAD"):
                    return self.q.PINNED_PUFFER_COMMIT
                if arguments == (
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ):
                    return ""
                if arguments == ("symbolic-ref", "-q", "HEAD"):
                    return "refs/heads/release"
                if arguments == ("config", "--get", "remote.origin.url"):
                    return "https://github.com/PufferAI/PufferLib.git"
                raise AssertionError(arguments)

            with mock.patch.object(
                self.q,
                "_git_output",
                side_effect=git_output,
            ), mock.patch.object(
                self.q.subprocess,
                "run",
                return_value=mock.Mock(
                    returncode=0,
                    stdout="refs/heads/release\n",
                    stderr="",
                ),
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "detached",
            ):
                self.q._prepare_strict_stage_isolation(
                    puffer_root=root,
                    output=temporary_path / "evidence",
                    python=None,
                    confirmed=True,
                )

    def test_strict_stage_isolation_rejects_symlinked_dot_venv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "PufferLib"
            real_venv = root / "real-venv"
            interpreter = real_venv / "bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"python")
            (real_venv / "pyvenv.cfg").write_text("", encoding="utf-8")
            (root / ".venv").symlink_to(real_venv, target_is_directory=True)
            with self.assertRaisesRegex(
                self.q.QualificationError,
                "symlink|real",
            ):
                self.q._strict_stage_interpreter(root, None)

    def test_strict_stage_isolation_requires_exact_dot_venv(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary) / "PufferLib"
            other_venv = root / "other-venv"
            other_python = other_venv / "bin/python"
            other_python.parent.mkdir(parents=True)
            other_python.write_bytes(b"python")
            (other_venv / "pyvenv.cfg").write_text("", encoding="utf-8")
            with self.assertRaisesRegex(
                self.q.QualificationError,
                r"\.venv|exact",
            ):
                self.q._strict_stage_interpreter(root, other_python)

    def test_strict_stage_worker_rejects_runtime_interpreter_identity_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = pathlib.Path(temporary)
            root = (temporary_path / "PufferLib").resolve()
            receipt_path = temporary_path / "ISOLATION.json"
            output = temporary_path / "STRICT_STAGE_ORDER.json"
            receipt = self._strict_stage_evidence_fixture(
                root=str(root)
            )["isolation"]["receipt"]
            interpreter = root / ".venv/bin/python"
            interpreter.parent.mkdir(parents=True)
            interpreter.write_bytes(b"isolated-python")
            for key in ("pybind11_path", "numpy_path"):
                dependency = pathlib.Path(
                    receipt["interpreter_identity"][key]
                )
                dependency.parent.mkdir(parents=True, exist_ok=True)
                dependency.write_bytes(b"dependency")
            receipt["interpreter_identity"]["executable_sha256"] = (
                self.q.sha256(interpreter)
            )
            running_identity = dict(receipt["interpreter_identity"])
            running_identity["python_version"] = "3.13.0"
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            args = SimpleNamespace(
                puffer_root=root,
                isolation_receipt=receipt_path,
                output_json=output,
                seed=123,
            )
            with mock.patch.object(
                self.q,
                "_git_output",
                return_value=self.q.PINNED_PUFFER_COMMIT,
            ), mock.patch.object(
                self.q,
                "_require_detached_head",
            ), mock.patch.object(
                self.q,
                "_read_json",
                return_value=receipt,
            ), mock.patch.object(
                self.q,
                "write_bounded_json_atomic",
            ), mock.patch.object(
                self.q,
                "_require_strict_patch_reverse_applicable",
            ), mock.patch.object(
                self.q,
                "_strict_stage_current_interpreter_identity",
                return_value=running_identity,
            ), mock.patch.object(
                self.q,
                "_load_backend",
            ) as load_backend, self.assertRaisesRegex(
                self.q.QualificationError,
                "active interpreter|running interpreter|"
                r"sys\.executable|executable differs|"
                "differs from pre-build probe",
            ):
                self.q.run_strict_stage_worker(args)
            load_backend.assert_not_called()

    def test_cells_must_share_one_module_identity(self):
        identity = {"module_sha256": "a" * 64}
        with mock.patch.object(
            self.q, "validate_module_identity", side_effect=lambda value: dict(value)
        ):
            self.assertEqual(
                self.q._require_same_identity(
                    [{"identity": identity}, {"identity": dict(identity)}]
                ),
                identity,
            )
            with self.assertRaisesRegex(
                self.q.QualificationError, "identity drifted between cells"
            ):
                self.q._require_same_identity(
                    [{"identity": identity}, {"identity": {"module_sha256": "b" * 64}}]
                )

    def test_transition_patch_identity_rehashes_pin_patch_and_applied_tree(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = pathlib.Path(temporary)
            puffer = directory / "PufferLib"
            puffer.mkdir()
            subprocess.run(
                ["git", "init", "-q"],
                cwd=puffer,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.email", "qualification@example.test"],
                cwd=puffer,
                check=True,
            )
            subprocess.run(
                ["git", "config", "user.name", "Qualification Test"],
                cwd=puffer,
                check=True,
            )
            source = puffer / "surface.txt"
            source.write_text("before\n", encoding="utf-8")
            subprocess.run(["git", "add", "surface.txt"], cwd=puffer, check=True)
            subprocess.run(
                ["git", "commit", "-qm", "baseline"],
                cwd=puffer,
                check=True,
            )
            head = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=puffer,
                text=True,
                capture_output=True,
                check=True,
            ).stdout.strip()
            source.write_text("after\n", encoding="utf-8")
            patch = directory / "transition.patch"
            patch.write_text(
                subprocess.run(
                    ["git", "diff", "--", "surface.txt"],
                    cwd=puffer,
                    text=True,
                    capture_output=True,
                    check=True,
                ).stdout,
                encoding="utf-8",
            )
            with mock.patch.object(
                self.q, "PINNED_PUFFER_COMMIT", head
            ), mock.patch.object(
                self.q, "ROLLOUT_TRANSITION_PATCH", patch
            ):
                identity = self.q._rollout_transition_patch_identity(puffer)
                self.assertEqual(identity["puffer_git_head"], head)
                self.assertEqual(
                    identity["rollout_transition_patch"]["sha256"],
                    self.q.sha256(patch),
                )
                self.q.validate_rollout_transition_patch_identity(
                    identity,
                    expected_puffer_root=puffer,
                    rehash_files=True,
                )
                source.write_text("drifted\n", encoding="utf-8")
                with self.assertRaisesRegex(
                    self.q.QualificationError, "reverse-applicable"
                ):
                    self.q.validate_rollout_transition_patch_identity(
                        identity,
                        expected_puffer_root=puffer,
                        rehash_files=True,
                    )

    def test_cells_must_share_one_transition_patch_identity(self):
        identity = {
            "puffer_git_head": self.q.PINNED_PUFFER_COMMIT,
            "rollout_transition_patch": {
                "path": str(ROLLOUT_TRANSITION_PATCH),
                "sha256": "a" * 64,
                "reverse_applicable": True,
            },
        }
        self.assertEqual(
            self.q._require_same_patch_identity(
                [
                    {"patch_identity": identity},
                    {"patch_identity": json.loads(json.dumps(identity))},
                ]
            ),
            identity,
        )
        changed = json.loads(json.dumps(identity))
        changed["rollout_transition_patch"]["sha256"] = "b" * 64
        with self.assertRaisesRegex(
            self.q.QualificationError, "patch identity drifted"
        ):
            self.q._require_same_patch_identity(
                [
                    {"patch_identity": identity},
                    {"patch_identity": changed},
                ]
            )

    def test_transition_patch_identity_schema_is_fail_closed(self):
        identity = {
            "puffer_git_head": self.q.PINNED_PUFFER_COMMIT,
            "rollout_transition_patch": {
                "path": str(ROLLOUT_TRANSITION_PATCH),
                "sha256": "a" * 64,
                "reverse_applicable": True,
            },
        }
        self.q.validate_rollout_transition_patch_identity(identity)
        mutations = (
            (
                "head",
                lambda value: value.update(puffer_git_head="b" * 40),
            ),
            (
                "path",
                lambda value: value["rollout_transition_patch"].update(
                    path="relative.patch"
                ),
            ),
            (
                "hash",
                lambda value: value["rollout_transition_patch"].update(
                    sha256="bad"
                ),
            ),
            (
                "reverse flag",
                lambda value: value["rollout_transition_patch"].update(
                    reverse_applicable=False
                ),
            ),
            (
                "extra key",
                lambda value: value["rollout_transition_patch"].update(
                    unbound=True
                ),
            ),
        )
        for label, mutate in mutations:
            changed = json.loads(json.dumps(identity))
            mutate(changed)
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_rollout_transition_patch_identity(changed)

    # ------------------------------------------------------- CUDA init order

    def test_backend_load_preflights_cudart_before_importing_the_extension(self):
        source = RUNNER.read_text(encoding="utf-8")
        body = source[source.index("def _load_backend("):source.index("def _module_identity(")]
        begin = body.index("begin_cuda_runtime_preflight()")
        imported = body.index("from pufferlib import _C")
        finish = body.index("finish_cuda_runtime_preflight(")
        self.assertLess(begin, imported, "CUDART must initialize before _C import")
        self.assertLess(imported, finish, "device count must be rechecked after import")
        self.assertIn('"rollout_transition_contract"', body)

    def test_cuda_runtime_evidence_is_fail_closed(self):
        evidence = cuda_runtime_evidence()
        self.q.validate_cuda_runtime_evidence(evidence)
        mutations = (
            ("before_extension_import", "return_code", 100),
            ("before_extension_import", "device_count", 0),
            ("after_extension_import", "return_code", 100),
            ("after_extension_import", "device_count", 2),
            ("library", "sha256", "bad"),
        )
        for section, key, value in mutations:
            mutated = json.loads(json.dumps(evidence))
            mutated[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(
                self.q.CudaRuntimePreflightError
            ):
                self.q.validate_cuda_runtime_evidence(mutated)
        malformed = json.loads(json.dumps(evidence))
        malformed["unexpected"] = True
        with self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.validate_cuda_runtime_evidence(malformed)
        malformed = json.loads(json.dumps(evidence))
        del malformed["cuda_visible_devices"]
        with self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.validate_cuda_runtime_evidence(malformed)
        malformed = json.loads(json.dumps(evidence))
        malformed["before_extension_import"]["error_name"] = "cudaErrorNoDevice"
        with self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.validate_cuda_runtime_evidence(malformed)

        with tempfile.TemporaryDirectory() as temporary:
            library = pathlib.Path(temporary) / "libcudart.so.12.4.127"
            library.write_bytes(b"frozen CUDA runtime")
            current = cuda_runtime_evidence()
            current["library"]["resolved_path"] = str(library.resolve())
            current["library"]["sha256"] = hashlib.sha256(
                library.read_bytes()
            ).hexdigest()
            cuda_runtime.validate_cuda_runtime_library_file(current)
            library.write_bytes(b"drifted CUDA runtime")
            with self.assertRaisesRegex(
                cuda_runtime.CudaRuntimePreflightError, "digest drifted"
            ):
                cuda_runtime.validate_cuda_runtime_library_file(current)

    def test_cuda_runtime_native_probe_checks_return_code_and_count(self):
        runtime = SimpleNamespace()

        def device_count(pointer):
            pointer._obj.value = 1
            return 0

        runtime.cudaGetDeviceCount = mock.Mock(side_effect=device_count)
        runtime.cudaGetErrorName = mock.Mock(return_value=b"cudaSuccess")
        runtime.cudaGetErrorString = mock.Mock(return_value=b"no error")
        with mock.patch.object(
            cuda_runtime.ctypes, "CDLL", return_value=runtime
        ), mock.patch.object(
            cuda_runtime, "_resolved_cuda_runtime_path",
            return_value=pathlib.Path(__file__),
        ):
            handle, evidence = cuda_runtime.begin_cuda_runtime_preflight()
            completed = cuda_runtime.finish_cuda_runtime_preflight(handle, evidence)
        self.assertEqual(completed["before_extension_import"]["device_count"], 1)
        self.assertEqual(completed["after_extension_import"]["device_count"], 1)
        self.assertEqual(runtime.cudaGetDeviceCount.call_count, 2)

        def no_device(pointer):
            pointer._obj.value = 1
            return 100

        runtime.cudaGetDeviceCount = mock.Mock(side_effect=no_device)
        runtime.cudaGetErrorName = mock.Mock(return_value=b"cudaErrorNoDevice")
        runtime.cudaGetErrorString = mock.Mock(return_value=b"no device")
        with mock.patch.object(
            cuda_runtime.ctypes, "CDLL", return_value=runtime
        ), mock.patch.object(
            cuda_runtime, "_resolved_cuda_runtime_path",
            return_value=pathlib.Path(__file__),
        ), self.assertRaisesRegex(
            cuda_runtime.CudaRuntimePreflightError, "return_code=100"
        ):
            cuda_runtime.begin_cuda_runtime_preflight()

    def test_qualification_cells_require_one_cuda_runtime_identity(self):
        evidence = cuda_runtime_evidence()
        records = [
            {"cuda_runtime_preflight": evidence},
            {"cuda_runtime_preflight": json.loads(json.dumps(evidence))},
        ]
        self.assertEqual(self.q._require_same_cuda_runtime(records), evidence)
        records[1]["cuda_runtime_preflight"]["library"]["sha256"] = "e" * 64
        with self.assertRaisesRegex(
            self.q.QualificationError, "CUDA runtime drifted"
        ):
            self.q._require_same_cuda_runtime(records)

    def test_puffer_entrypoint_preflights_before_import_and_rechecks_after(self):
        events = []
        handle = object()
        evidence = cuda_runtime_evidence()

        def begin():
            events.append("begin")
            return handle, evidence

        def import_main():
            events.append("import")

            def puffer_main():
                events.append("main")
                return 0

            return puffer_main

        def finish(observed_handle, observed_evidence):
            self.assertIs(observed_handle, handle)
            self.assertIs(observed_evidence, evidence)
            events.append("finish")
            return evidence

        def publish(observed_evidence):
            self.assertIs(observed_evidence, evidence)
            events.append("publish")
            return {"schema_version": 1}

        with mock.patch.object(
            cuda_runtime, "begin_cuda_runtime_preflight", side_effect=begin
        ), mock.patch.object(
            cuda_runtime, "_import_puffer_main", side_effect=import_main
        ), mock.patch.object(
            cuda_runtime, "finish_cuda_runtime_preflight", side_effect=finish
        ), mock.patch.object(
            cuda_runtime, "validate_cuda_runtime_evidence"
        ), mock.patch.object(
            cuda_runtime, "_publish_runtime_evidence", side_effect=publish
        ), mock.patch("builtins.print"):
            self.assertEqual(cuda_runtime.main(), 0)
        self.assertEqual(
            events, ["begin", "import", "finish", "publish", "main"]
        )

        with mock.patch.object(
            cuda_runtime,
            "begin_cuda_runtime_preflight",
            side_effect=cuda_runtime.CudaRuntimePreflightError("no device"),
        ), mock.patch.object(cuda_runtime, "_import_puffer_main") as imported, \
                self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.main()
        imported.assert_not_called()

        puffer_main = mock.Mock(return_value=0)
        with mock.patch.object(
            cuda_runtime,
            "begin_cuda_runtime_preflight",
            return_value=(handle, evidence),
        ), mock.patch.object(
            cuda_runtime, "_import_puffer_main", return_value=puffer_main
        ), mock.patch.object(
            cuda_runtime,
            "finish_cuda_runtime_preflight",
            side_effect=cuda_runtime.CudaRuntimePreflightError("poisoned"),
        ), self.assertRaises(cuda_runtime.CudaRuntimePreflightError):
            cuda_runtime.main()
        puffer_main.assert_not_called()
        wrapper_source = CUDA_RUNTIME_WRAPPER.read_text(encoding="utf-8")
        self.assertIn("from pufferlib import _C", wrapper_source)
        self.assertIn("_remove_script_directory_from_import_path()", wrapper_source)

        puffer_main = mock.Mock(return_value=0)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(
            cuda_runtime,
            "begin_cuda_runtime_preflight",
            return_value=(handle, evidence),
        ), mock.patch.object(
            cuda_runtime, "_import_puffer_main", return_value=puffer_main
        ), mock.patch.object(
            cuda_runtime,
            "finish_cuda_runtime_preflight",
            return_value=evidence,
        ), mock.patch.object(
            cuda_runtime, "validate_cuda_runtime_evidence"
        ), self.assertRaisesRegex(
            cuda_runtime.CudaRuntimePreflightError, "paths are mandatory"
        ):
            cuda_runtime.main()
        puffer_main.assert_not_called()

    def test_trainer_wrapper_publishes_its_own_runtime_evidence_before_main(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            manifest_path = root / "run.manifest.json"
            evidence_path = root / "run.cuda-runtime.json"
            evidence = cuda_runtime_evidence()
            manifest = {
                "schema_version": 1,
                "cuda_runtime_wrapper_sha256": hashlib.sha256(
                    CUDA_RUNTIME_WRAPPER.read_bytes()
                ).hexdigest(),
                "cuda_runtime_evidence_status": "pending",
                "cuda_runtime_evidence_path": str(evidence_path),
                "cuda_launcher_probe_library_path": evidence["library"][
                    "resolved_path"
                ],
                "cuda_launcher_probe_library_sha256": evidence["library"][
                    "sha256"
                ],
                "cuda_launcher_probe_device_count": "1",
                "cuda_launcher_probe_visible_devices": "0",
            }
            manifest_path.write_text(
                json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8"
            )
            events = []
            puffer_main = mock.Mock(side_effect=lambda: events.append("main"))
            with mock.patch.dict(
                os.environ,
                {
                    "PUFFER_CUDA_RUNTIME_MANIFEST": str(manifest_path),
                    "PUFFER_CUDA_RUNTIME_EVIDENCE": str(evidence_path),
                },
                clear=False,
            ), mock.patch.object(
                cuda_runtime,
                "begin_cuda_runtime_preflight",
                return_value=(object(), evidence),
            ), mock.patch.object(
                cuda_runtime, "_import_puffer_main", return_value=puffer_main
            ), mock.patch.object(
                cuda_runtime,
                "finish_cuda_runtime_preflight",
                return_value=evidence,
            ), mock.patch.object(
                cuda_runtime, "validate_cuda_runtime_evidence"
            ), mock.patch("builtins.print"):
                self.assertEqual(cuda_runtime.main(), 0)
            self.assertEqual(events, ["main"])
            finalized = json.loads(manifest_path.read_text(encoding="utf-8"))
            sidecar = json.loads(evidence_path.read_text(encoding="utf-8"))
            self.assertEqual(finalized["cuda_runtime_evidence_status"], "accepted")
            self.assertEqual(finalized["cuda_runtime_evidence"], evidence)
            self.assertEqual(sidecar["runtime_evidence"], evidence)

            # The trainer's own evidence must match the launcher's expectation.
            puffer_main.reset_mock()
            finalized["cuda_runtime_evidence_status"] = "pending"
            finalized["cuda_launcher_probe_device_count"] = "2"
            finalized.pop("cuda_runtime_evidence")
            finalized.pop("cuda_runtime_evidence_sha256")
            manifest_path.write_text(
                json.dumps(finalized, sort_keys=True) + "\n", encoding="utf-8"
            )
            evidence_path.unlink()
            with mock.patch.dict(
                os.environ,
                {
                    "PUFFER_CUDA_RUNTIME_MANIFEST": str(manifest_path),
                    "PUFFER_CUDA_RUNTIME_EVIDENCE": str(evidence_path),
                },
                clear=False,
            ), mock.patch.object(
                cuda_runtime,
                "begin_cuda_runtime_preflight",
                return_value=(object(), evidence),
            ), mock.patch.object(
                cuda_runtime, "_import_puffer_main", return_value=puffer_main
            ), mock.patch.object(
                cuda_runtime,
                "finish_cuda_runtime_preflight",
                return_value=evidence,
            ), mock.patch.object(
                cuda_runtime, "validate_cuda_runtime_evidence"
            ), mock.patch("builtins.print"), self.assertRaises(
                cuda_runtime.CudaRuntimePreflightError
            ):
                cuda_runtime.main()
            puffer_main.assert_not_called()

    # ------------------------------------------------- graph capture / config

    def test_graph_capture_requires_production_warmup_boundary(self):
        args = mock.Mock(
            seed=271828,
            throughput_agents=2048,
            throughput_buffers=2,
            throughput_threads=16,
            throughput_horizon=64,
            throughput_hidden=512,
            throughput_layers=3,
            throughput_minibatch_size=16384,
        )
        self.assertEqual(self.q.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS, 10)
        for kind in self.q.CELL_KINDS:
            with self.subTest(kind=kind):
                self.assertEqual(self.q.validate_cell_cudagraphs(kind, 10), 10)
                self.assertEqual(
                    self.q._cell_config(kind, 10, args)["cudagraphs"], 10
                )
                # 0 captures the graph before CUDA lazy initialization.
                with self.assertRaises(self.q.QualificationError):
                    self.q.validate_cell_cudagraphs(kind, 0)
        self.assertEqual(self.q.validate_cell_cudagraphs("rollout", -1), -1)
        for kind in set(self.q.CELL_KINDS) - {"rollout"}:
            with self.subTest(graph_off_kind=kind), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_cell_cudagraphs(kind, -1)

    def test_cell_rejects_zero_warmup_before_runtime_dispatch(self):
        argv = [
            "cell",
            "--puffer-root", "/tmp/puffer",
            "--kind", "throughput",
            "--cudagraphs", "0",
            "--run-nonce", TEST_RUN_NONCE,
            "--cell-nonce", TEST_CELL_NONCE,
            "--output-json", "/tmp/throughput.json",
        ]
        with mock.patch.object(self.q, "run_cell") as run_cell, self.assertRaises(
            self.q.QualificationError
        ):
            self.q.main(argv)
        run_cell.assert_not_called()

    def test_cell_record_must_report_the_graph_mode_it_ran(self):
        record = {
            "config": {"cudagraphs": 10},
            "cuda_runtime_preflight": cuda_runtime_evidence(),
        }
        self.q.validate_cell_cudagraph_record(record, expected=10)
        for observed in (0, -1, 10.0, None):
            with self.subTest(observed=observed), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_cell_cudagraph_record(
                    dict(record, config={"cudagraphs": observed}), expected=10
                )
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_cell_cudagraph_record(
                {"config": {"cudagraphs": 10}, "cuda_runtime_preflight": {}},
                expected=10,
            )

    def test_graph_on_requires_captured_handles_and_real_launches(self):
        expected_counts = {
            "rollout": 288,
            "tail": 36,
            "train": 1,
        }
        graph_on = {
            "workload": "rollout",
            "cudagraphs": 10,
            "captured": {
                "rollout": True,
                "tail": True,
                "train": True,
            },
            "handles_ready": {
                "rollout": True,
                "tail": True,
                "train": True,
            },
            "graph_launch_counts": {
                "rollout": 288,
                "tail": 36,
                "train": 1,
            },
            "eager_execution_counts": {
                "rollout": 0,
                "tail": 0,
                "train": 0,
            },
        }
        accepted = self.q.validate_graph_execution_evidence(
            graph_on,
            expected_cudagraphs=10,
            expected_workload="rollout",
            expected_counts=expected_counts,
        )
        self.assertEqual(accepted, graph_on)

        for section, key, value in (
            ("captured", "tail", False),
            ("handles_ready", "rollout", False),
            ("graph_launch_counts", "rollout", 0),
            ("graph_launch_counts", "tail", 0),
            ("graph_launch_counts", "train", 0),
            ("eager_execution_counts", "rollout", 1),
        ):
            changed = json.loads(json.dumps(graph_on))
            changed[section][key] = value
            with self.subTest(section=section, key=key), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_graph_execution_evidence(
                    changed,
                    expected_cudagraphs=10,
                    expected_workload="rollout",
                    expected_counts=expected_counts,
                )

        graph_off = {
            "workload": "rollout",
            "cudagraphs": -1,
            "captured": {
                "rollout": False,
                "tail": False,
                "train": False,
            },
            "handles_ready": {
                "rollout": False,
                "tail": False,
                "train": False,
            },
            "graph_launch_counts": {
                "rollout": 0,
                "tail": 0,
                "train": 0,
            },
            "eager_execution_counts": {
                "rollout": 288,
                "tail": 36,
                "train": 1,
            },
        }
        self.q.validate_graph_execution_evidence(
            graph_off,
            expected_cudagraphs=-1,
            expected_workload="rollout",
            expected_counts=expected_counts,
        )
        changed = json.loads(json.dumps(graph_off))
        changed["eager_execution_counts"]["tail"] = 35
        with self.assertRaises(self.q.QualificationError):
            self.q.validate_graph_execution_evidence(
                changed,
                expected_cudagraphs=-1,
                expected_workload="rollout",
                expected_counts=expected_counts,
            )

    def test_qualification_tail_discard_is_explicit_and_closed(self):
        backend = SimpleNamespace(
            qualification_consume_tail=mock.Mock(
                return_value={
                    "before": [1, 1],
                    "after": [0, 0],
                }
            )
        )
        accepted = self.q.consume_qualification_tail(
            backend,
            object(),
            num_buffers=2,
            label="throughput",
        )
        self.assertEqual(accepted["before"], [1, 1])
        self.assertEqual(accepted["after"], [0, 0])
        backend.qualification_consume_tail.assert_called_once()

        for malformed in (
            {"before": [0, 1], "after": [0, 0]},
            {"before": [1, 1], "after": [0, 1]},
            {"before": [1, 1], "after": [0, 0], "extra": True},
        ):
            backend.qualification_consume_tail.return_value = malformed
            with self.subTest(malformed=malformed), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.consume_qualification_tail(
                    backend,
                    object(),
                    num_buffers=2,
                    label="throughput",
                )

    def test_throughput_minibatch_matches_rollout_quantum(self):
        args = mock.Mock(
            seed=271828,
            throughput_agents=2048,
            throughput_buffers=2,
            throughput_threads=16,
            throughput_horizon=64,
            throughput_hidden=512,
            throughput_layers=3,
            throughput_minibatch_size=16384,
        )
        config = self.q._cell_config("throughput", 10, args)
        self.assertEqual(
            config["vec"]["total_agents"] * config["train"]["horizon"], 131072
        )
        self.assertEqual(config["train"]["minibatch_size"], 16384)
        self.assertEqual(config["cudagraphs"], 10)
        self.assertEqual(config["env"]["max_decisions"], 4096)
        self.assertEqual(config["policy"], {
            "hidden_size": 512,
            "num_layers": 3,
        })
        self.assertEqual(self.q.DEFAULT_THROUGHPUT_MINIBATCH_SIZE, 16384)
        parsed = self.q.parse_args([
            "cell",
            "--puffer-root", "/tmp/puffer",
            "--kind", "throughput",
            "--cudagraphs", "10",
            "--run-nonce", TEST_RUN_NONCE,
            "--cell-nonce", TEST_CELL_NONCE,
            "--output-json", "/tmp/throughput.json",
        ])
        self.assertEqual(parsed.throughput_minibatch_size, 16384)
        self.assertEqual(parsed.throughput_agents, 4096)
        self.assertEqual(parsed.throughput_buffers, 2)
        self.assertEqual(parsed.throughput_threads, 20)
        self.assertEqual(parsed.throughput_horizon, 64)
        self.assertEqual(parsed.throughput_hidden, 512)
        self.assertEqual(parsed.throughput_layers, 3)

    def test_qualification_minibatch_must_fit_rollout_contract(self):
        base = {
            "cudagraphs": 10,
            "seed": 271828,
            "total_agents": 2048,
            "num_buffers": 2,
            "num_threads": 16,
            "horizon": 64,
            "max_decisions": 64,
            "hidden_size": 512,
            "num_layers": 3,
            "frozen_banks": 1,
            "frozen_bank_pct": 0.1,
            "learning_rate": 0.0,
        }
        for invalid in (0, 6144, 16383, 24576, 131136):
            with self.subTest(minibatch_size=invalid), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.qualification_args(**base, minibatch_size=invalid)

    def test_invalid_throughput_minibatch_fails_before_worker_dispatch(self):
        argv = [
            "cell",
            "--puffer-root", "/tmp/puffer",
            "--kind", "throughput",
            "--cudagraphs", "10",
            "--run-nonce", TEST_RUN_NONCE,
            "--cell-nonce", TEST_CELL_NONCE,
            "--output-json", "/tmp/throughput.json",
            "--throughput-agents", "2048",
            "--throughput-horizon", "64",
            "--throughput-minibatch-size", "6144",
        ]
        with mock.patch.object(self.q, "run_cell") as run_cell, self.assertRaises(
            self.q.QualificationError
        ):
            self.q.main(argv)
        run_cell.assert_not_called()

    # ------------------------------------------------------- driver behaviour

    def test_cell_artifact_path_is_exact_and_kind_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            expected = root / "graph-off.npz"
            np.savez(expected, values=np.zeros(1, dtype=np.float32))
            accepted = {
                "artifact": str(expected),
                "artifact_bytes": expected.stat().st_size,
                "artifact_sha256": hashlib.sha256(
                    expected.read_bytes()
                ).hexdigest(),
            }
            self.q.validate_cell_artifact_path(
                accepted,
                kind="rollout",
                expected=expected,
            )
            expected.write_bytes(b"replaced after worker")
            with self.assertRaises(self.q.QualificationError):
                self.q.validate_cell_artifact_path(
                    accepted,
                    kind="rollout",
                    expected=expected,
                )
            for record, kind in (
                ({}, "rollout"),
                ({"artifact": str(root / "redirected.npz")}, "rollout"),
                (accepted, "construction"),
            ):
                with self.subTest(record=record, kind=kind), self.assertRaises(
                    self.q.QualificationError
                ):
                    self.q.validate_cell_artifact_path(
                        record,
                        kind=kind,
                        expected=expected,
                    )

    def test_cell_artifact_hash_and_npz_parse_use_one_exact_byte_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary).resolve()
            artifact = root / "cell.npz"
            replacement = root / "replacement.npz"
            np.savez(artifact, values=np.array([1.0, 2.0], dtype=np.float32))
            np.savez(replacement, values=np.array([9.0, 8.0], dtype=np.float32))
            self.assertEqual(artifact.stat().st_size, replacement.stat().st_size)
            record = {
                "artifact": str(artifact),
                "artifact_bytes": artifact.stat().st_size,
                "artifact_sha256": hashlib.sha256(
                    artifact.read_bytes()
                ).hexdigest(),
            }
            validated = self.q.validate_cell_artifact_path(
                record,
                kind="rollout",
                expected=artifact,
            )
            os.replace(replacement, artifact)
            arrays = self.q._read_npz(validated)
            np.testing.assert_array_equal(
                arrays["values"],
                np.array([1.0, 2.0], dtype=np.float32),
            )

    def test_parent_owns_cell_record_identity_and_nested_throughput_config(self):
        source = RUNNER.read_text(encoding="utf-8")
        worker = source[
            source.index("def _run_worker("):
            source.index("def _require_same_identity(")
        ]
        for fragment in (
            '"record_path"',
            '"record_bytes"',
            '"record_sha256"',
            "spoofed parent-owned record metadata",
            'throughput_payload.get("config") != record["config"]',
            "throughput payload config differs from parent request",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, worker)

    def test_worker_cannot_accept_stale_cells_when_child_writes_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            python = root / "python"
            python.write_text("binary placeholder\n", encoding="utf-8")
            stale_json = root / "construction.json"
            stale_npz = root / "construction.npz"
            victim_json = root / "outside-victim.json"
            victim_npz = root / "outside-victim.npz"
            victim_json.write_text(
                json.dumps({
                    "schema_version": self.q.SCHEMA_VERSION,
                    "accepted": True,
                    "run_nonce": TEST_RUN_NONCE,
                    "cell_nonce": TEST_CELL_NONCE,
                }),
                encoding="utf-8",
            )
            victim_npz.write_bytes(b"stale GPU evidence")
            stale_json.symlink_to(victim_json)
            stale_npz.symlink_to(victim_npz)
            args = mock.Mock(
                python=python,
                puffer_root=root,
                seed=1,
                ratio_call_limit=64,
                throughput_agents=2048,
                throughput_buffers=2,
                throughput_threads=16,
                throughput_horizon=64,
                throughput_hidden=512,
                throughput_layers=3,
                throughput_minibatch_size=16384,
                throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8,
                cell_timeout_seconds=1800,
            )
            with mock.patch.object(
                self.q.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "missing|cannot read",
            ):
                self.q._run_worker(
                    args,
                    kind="construction",
                    name="construction",
                    cudagraphs=10,
                    output=root,
                    run_nonce=TEST_RUN_NONCE,
                    cell_nonce=TEST_CELL_NONCE,
                )
            self.assertFalse(stale_json.exists())
            self.assertFalse(stale_npz.exists())
            self.assertTrue(victim_json.is_file())
            self.assertEqual(victim_npz.read_bytes(), b"stale GPU evidence")

    def test_final_verdict_retains_execution_evidence_and_rechecks_cell_bytes(self):
        source = RUNNER.read_text(encoding="utf-8")
        driver = source[
            source.index("def run_qualification("):
            source.index("def add_common_arguments(")
        ]
        for fragment in (
            '"graph_off_execution": graph_off["graph_execution"]',
            '"graph_on_execution": graph_on["graph_execution"]',
            '"graph_execution": ratio["graph_execution"]',
            '"graph_execution": throughput_cell["graph_execution"]',
            '"record_bytes": record["record_bytes"]',
            '"record_sha256": record["record_sha256"]',
            "JSON artifact drifted",
            "NPZ artifact drifted",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, driver)

    def test_npz_reader_rejects_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            target = root / "target.npz"
            np.savez(target, values=np.zeros(1, dtype=np.float32))
            artifact = root / "artifact.npz"
            artifact.symlink_to(target)
            with self.assertRaisesRegex(
                self.q.QualificationError,
                "regular non-symlink",
            ):
                self.q._read_npz(artifact)

    def test_worker_preserves_explicit_venv_python_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            base_python = root / "managed-python"
            base_python.write_text("binary placeholder\n", encoding="utf-8")
            venv_python = root / "venv" / "bin" / "python"
            venv_python.parent.mkdir(parents=True)
            venv_python.symlink_to(base_python)
            puffer = root / "puffer"
            output = root / "output"
            puffer.mkdir()
            output.mkdir()
            args = mock.Mock(
                python=venv_python,
                puffer_root=puffer,
                seed=271828,
                ratio_call_limit=64,
                throughput_agents=2048,
                throughput_buffers=2,
                throughput_threads=16,
                throughput_horizon=64,
                throughput_hidden=512,
                throughput_layers=3,
                throughput_minibatch_size=16384,
                throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8,
                cell_timeout_seconds=1800,
            )
            record = {
                "schema_version": self.q.SCHEMA_VERSION,
                "accepted": True,
                "run_nonce": TEST_RUN_NONCE,
                "cell_nonce": TEST_CELL_NONCE,
                "config": {"cudagraphs": 10},
                "cuda_runtime_preflight": cuda_runtime_evidence(),
            }
            expected_record = bound_json_result(
                self.q,
                output / "construction.json",
                dict(record),
            )[1]
            with mock.patch.object(
                self.q.subprocess, "run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ) as run, mock.patch.object(
                self.q,
                "_read_json_artifact",
                side_effect=lambda path, **_kwargs: bound_json_result(
                    self.q, path, record
                ),
            ), mock.patch.object(
                self.q, "_cell_config", return_value=record["config"]
            ), mock.patch.object(
                self.q, "validate_rollout_transition_patch_identity"
            ):
                observed = self.q._run_worker(
                    args, kind="construction", name="construction",
                    cudagraphs=10, output=output,
                    run_nonce=TEST_RUN_NONCE,
                    cell_nonce=TEST_CELL_NONCE,
                )
            command = run.call_args.args[0]
            # Resolving the symlink would run the base interpreter, not the venv.
            self.assertEqual(command[0], str(venv_python.absolute()))
            self.assertNotEqual(command[0], str(base_python.resolve()))
            self.assertEqual(command[command.index("--cudagraphs") + 1], "10")
            self.assertEqual(
                command[command.index("--throughput-minibatch-size") + 1], "16384"
            )
            self.assertEqual(
                observed["record_path"],
                str((output / "construction.json").resolve()),
            )
            self.assertEqual(
                observed["record_bytes"],
                len(expected_record.encoded),
            )
            self.assertEqual(
                observed["record_sha256"],
                expected_record.sha256,
            )
            self.assertIsNone(observed["_artifact_arrays"])

    def test_worker_rejects_a_cell_that_ran_a_different_graph_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            python = root / "python"
            python.write_text("binary placeholder\n", encoding="utf-8")
            args = mock.Mock(
                python=python, puffer_root=root, seed=1, ratio_call_limit=64,
                throughput_agents=2048, throughput_buffers=2,
                throughput_threads=16, throughput_horizon=64,
                throughput_hidden=512, throughput_layers=3,
                throughput_minibatch_size=16384, throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8, cell_timeout_seconds=1800,
            )
            record = {
                "schema_version": self.q.SCHEMA_VERSION,
                "accepted": True,
                "run_nonce": TEST_RUN_NONCE,
                "cell_nonce": TEST_CELL_NONCE,
                "config": {"cudagraphs": 10},
                "cuda_runtime_preflight": cuda_runtime_evidence(),
            }
            with mock.patch.object(
                self.q.subprocess, "run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ), mock.patch.object(
                self.q,
                "_read_json_artifact",
                side_effect=lambda path, **_kwargs: bound_json_result(
                    self.q, path, record
                ),
            ), mock.patch.object(
                self.q, "validate_rollout_transition_patch_identity"
            ), self.assertRaisesRegex(
                self.q.QualificationError, "cudagraph warmup"
            ):
                self.q._run_worker(
                    args, kind="rollout", name="graph-off", cudagraphs=-1,
                    output=root,
                    run_nonce=TEST_RUN_NONCE,
                    cell_nonce=TEST_CELL_NONCE,
                )

    def test_parent_rehashes_transition_patch_identity_for_every_worker_record(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            python = root / "python"
            python.write_text("binary placeholder\n", encoding="utf-8")
            args = mock.Mock(
                python=python, puffer_root=root, seed=1, ratio_call_limit=64,
                throughput_agents=2048, throughput_buffers=2,
                throughput_threads=16, throughput_horizon=64,
                throughput_hidden=512, throughput_layers=3,
                throughput_minibatch_size=16384, throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8, cell_timeout_seconds=1800,
            )
            patch_identity = {
                "puffer_git_head": self.q.PINNED_PUFFER_COMMIT,
                "rollout_transition_patch": {
                    "path": str(ROLLOUT_TRANSITION_PATCH),
                    "sha256": "a" * 64,
                    "reverse_applicable": True,
                },
            }
            record = {
                "schema_version": self.q.SCHEMA_VERSION,
                "accepted": True,
                "run_nonce": TEST_RUN_NONCE,
                "cell_nonce": TEST_CELL_NONCE,
                "patch_identity": patch_identity,
                "config": {"cudagraphs": 10},
                "cuda_runtime_preflight": cuda_runtime_evidence(),
            }
            with mock.patch.object(
                self.q.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout="", stderr=""),
            ), mock.patch.object(
                self.q,
                "_read_json_artifact",
                side_effect=lambda path, **_kwargs: bound_json_result(
                    self.q, path, record
                ),
            ), mock.patch.object(
                self.q, "_cell_config", return_value=record["config"]
            ), mock.patch.object(
                self.q, "validate_rollout_transition_patch_identity"
            ) as validate:
                self.q._run_worker(
                    args,
                    kind="construction",
                    name="construction",
                    cudagraphs=10,
                    output=root,
                    run_nonce=TEST_RUN_NONCE,
                    cell_nonce=TEST_CELL_NONCE,
                )
            validate.assert_called_once_with(
                patch_identity,
                expected_puffer_root=root,
                rehash_files=True,
            )

    def test_parent_rejects_missing_stale_or_noninteger_cell_schema(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            python = root / "python"
            python.write_text("binary placeholder\n", encoding="utf-8")
            args = mock.Mock(
                python=python, puffer_root=root, seed=1, ratio_call_limit=64,
                throughput_agents=2048, throughput_buffers=2,
                throughput_threads=16, throughput_horizon=64,
                throughput_hidden=512, throughput_layers=3,
                throughput_minibatch_size=16384, throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8, cell_timeout_seconds=1800,
            )
            base = {
                "accepted": True,
                "run_nonce": TEST_RUN_NONCE,
                "cell_nonce": TEST_CELL_NONCE,
                "config": {"cudagraphs": 10},
                "cuda_runtime_preflight": cuda_runtime_evidence(),
            }
            for label, schema in (
                ("missing", None),
                ("stale", self.q.SCHEMA_VERSION - 1),
                ("float", float(self.q.SCHEMA_VERSION)),
                ("bool", True),
            ):
                record = dict(base)
                if schema is not None:
                    record["schema_version"] = schema
                with mock.patch.object(
                    self.q.subprocess,
                    "run",
                    return_value=mock.Mock(
                        returncode=0,
                        stdout="",
                        stderr="",
                    ),
                ), mock.patch.object(
                    self.q,
                    "_read_json_artifact",
                    side_effect=lambda path, **_kwargs: bound_json_result(
                        self.q, path, record
                    ),
                ), mock.patch.object(
                    self.q, "validate_rollout_transition_patch_identity"
                ) as validate, self.subTest(label=label), self.assertRaisesRegex(
                    self.q.QualificationError, "schema"
                ):
                    self.q._run_worker(
                        args,
                        kind="construction",
                        name="construction",
                        cudagraphs=10,
                        output=root,
                        run_nonce=TEST_RUN_NONCE,
                        cell_nonce=TEST_CELL_NONCE,
                    )
                validate.assert_not_called()

    def test_graph_off_cell_closes_normally_before_writing_acceptance(self):
        class Backend:
            precision_bytes = 4

            def __init__(self, *, close_error=False):
                self.close_error = close_error
                self.close_calls = 0
                self.pufferl = object()

            def create_pufferl(self, _config):
                return self.pufferl

            def qualification_recurrent_state(self, _pufferl, _clear):
                return {}

            def rollouts(self, _pufferl):
                return None

            def qualification_snapshot(self, _pufferl):
                return {}

            def qualification_graph_execution(self, _pufferl):
                return {
                    "cudagraphs": -1,
                    "captured": {
                        "rollout": False,
                        "tail": False,
                        "train": False,
                    },
                    "handles_ready": {
                        "rollout": False,
                        "tail": False,
                        "train": False,
                    },
                    "graph_launch_counts": {
                        "rollout": 0,
                        "tail": 0,
                        "train": 0,
                    },
                    "eager_execution_counts": {
                        "rollout": 3,
                        "tail": 3,
                        "train": 1,
                    },
                }

            def close(self, pufferl):
                self.close_calls += 1
                if pufferl is not self.pufferl:
                    raise AssertionError("wrong trainer closed")
                if self.close_error:
                    raise RuntimeError("close failed")

        config = {
            "cudagraphs": -1,
            "vec": {
                "num_frozen_banks": 0,
                "total_agents": 2,
                "num_buffers": 1,
            },
            "env": {"max_decisions": 1},
            "train": {
                "horizon": 1,
                "minibatch_size": 2,
                "replay_ratio": 1,
            },
        }
        arrays = {
            "tail_rewards": np.zeros(2, np.float32),
            "tail_terminals": np.zeros(2, np.float32),
            "tail_values": np.zeros(2, np.float32),
            "tail_valid": np.ones(1, np.int32),
        }
        for close_error in (False, True):
            with self.subTest(close_error=close_error), tempfile.TemporaryDirectory(
            ) as temporary:
                root = pathlib.Path(temporary)
                output_json = root / "cell.json"
                args = SimpleNamespace(
                    output_json=output_json,
                    output_npz=root / "cell.npz",
                    puffer_root=root,
                    kind="rollout",
                    cudagraphs=-1,
                    seed=1,
                    run_nonce=TEST_RUN_NONCE,
                    cell_nonce=TEST_CELL_NONCE,
                )
                backend = Backend(close_error=close_error)
                patches = (
                    mock.patch.object(
                        self.q,
                        "_rollout_transition_patch_identity",
                        return_value={"verified": True},
                    ),
                    mock.patch.object(
                        self.q,
                        "_load_backend",
                        return_value=(backend, root / "_C.so", {}),
                    ),
                    mock.patch.object(
                        self.q, "_cell_config", return_value=config
                    ),
                    mock.patch.object(
                        self.q, "_module_identity", return_value={}
                    ),
                    mock.patch.object(
                        self.q,
                        "execute_cuda_advantage_oracle",
                        return_value={"accepted": True},
                    ),
                    mock.patch.object(self.q, "validate_module_identity"),
                    mock.patch.object(self.q, "validate_zero_state"),
                    mock.patch.object(
                        self.q,
                        "_measure_heterogeneous_rollout",
                        return_value=arrays,
                    ),
                    mock.patch.object(
                        self.q,
                        "validate_tail_snapshot",
                        return_value={"valid_buffers": 1},
                    ),
                    mock.patch.object(
                        self.q,
                        "validate_tail_value_routing",
                        return_value={},
                    ),
                    mock.patch.object(self.q, "bind_transition_integrity"),
                )
                with patches[0], patches[1], patches[2], patches[3], patches[
                    4
                ], patches[5], patches[6], patches[7], patches[8], patches[
                    9
                ], patches[10]:
                    if close_error:
                        with self.assertRaisesRegex(RuntimeError, "close failed"):
                            self.q.run_cell(args)
                    else:
                        self.assertEqual(self.q.run_cell(args), 0)
                self.assertEqual(backend.close_calls, 1)
                record = json.loads(output_json.read_text(encoding="utf-8"))
                self.assertIs(record["accepted"], not close_error)
                if close_error:
                    self.assertIn("close failed", record["error"])

    def test_run_is_rerunnable_over_an_existing_output_directory(self):
        """A failed rerun atomically invalidates any prior accepted verdict."""
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "qualification"
            output.mkdir()
            stale = output / "QUALIFICATION.json"
            stale.write_text("stale verdict\n", encoding="utf-8")
            baseline = root / "baseline.json"
            throughput = {
                "host": "rtx2070",
                "gpu": "RTX 2070",
                "gpu_uuid": "GPU-00000000",
                "precision_bytes": 4,
                "config": {"cudagraphs": 10},
                "steps_per_second": 1000.0,
                "hard_integrity_zero": True,
                "steps": 1000,
                "elapsed_seconds": 1.0,
                "median_rollout_seconds": 0.1,
                "p95_rollout_seconds": 0.2,
                "hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "warmup_hard_integrity_zero": True,
                "warmup_hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "tail_records_explicitly_discarded": 10,
                "utilization": {},
            }
            baseline.write_text(
                json.dumps({"throughput": throughput}),
                encoding="utf-8",
            )
            args = mock.Mock(
                output=output,
                baseline_throughput=baseline,
                max_regression_fraction=0.10,
                ratio_call_limit=64,
                throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8,
                throughput_agents=2048,
                throughput_horizon=64,
                throughput_minibatch_size=16384,
            )
            with mock.patch.object(
                self.q, "_run_worker", side_effect=RuntimeError("worker reached")
            ) as worker, self.assertRaisesRegex(RuntimeError, "worker reached"):
                self.q.run_qualification(args)
            worker.assert_called_once()
            receipt = json.loads(stale.read_text(encoding="utf-8"))
            self.assertIs(receipt["accepted"], False)
            self.assertEqual(receipt["status"], "in_progress")

    def test_invalid_run_arguments_also_invalidate_a_stale_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "qualification"
            output.mkdir()
            final = output / "QUALIFICATION.json"
            final.write_text('{"accepted":true}\n', encoding="utf-8")
            args = mock.Mock(
                output=output,
                ratio_call_limit=0,
                throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8,
                throughput_agents=2048,
                throughput_horizon=64,
                throughput_minibatch_size=16384,
            )
            with self.assertRaisesRegex(
                self.q.QualificationError,
                "ratio call limit",
            ):
                self.q.run_qualification(args)
            receipt = json.loads(final.read_text(encoding="utf-8"))
            self.assertIs(receipt["accepted"], False)
            self.assertEqual(receipt["status"], "in_progress")

    def test_cli_parse_failure_invalidates_an_identifiable_stale_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "qualification"
            output.mkdir()
            final = output / "QUALIFICATION.json"
            final.write_text(
                '{"accepted":true,"status":"accepted"}\n',
                encoding="utf-8",
            )
            with self.assertRaises(SystemExit):
                self.q.main([
                    "run",
                    "--puffer-root", str(root / "puffer"),
                    "--output", str(output),
                    "--baseline-throughput", str(root / "baseline.json"),
                    "--max-regression-fraction", "not-a-number",
                ])
            receipt = json.loads(final.read_text(encoding="utf-8"))
            self.assertIs(receipt["accepted"], False)
            self.assertEqual(receipt["status"], "argument_parse_failed")
            self.assertRegex(receipt["run_nonce"], r"^[0-9a-f]{64}$")

    def test_cli_help_does_not_invalidate_an_accepted_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "qualification"
            output.mkdir()
            final = output / "QUALIFICATION.json"
            accepted = b'{"accepted":true,"status":"accepted"}\n'
            final.write_bytes(accepted)
            with self.assertRaisesRegex(SystemExit, "0"):
                self.q.main([
                    "run",
                    "--output", str(output),
                    "--help",
                ])
            self.assertEqual(final.read_bytes(), accepted)

    def test_run_requires_and_preflights_immutable_throughput_baseline(self):
        with self.assertRaises(SystemExit):
            self.q.parse_args([
                "run",
                "--puffer-root",
                "/tmp/puffer",
                "--output",
                "/tmp/qualification",
            ])

        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "qualification"
            args = mock.Mock(
                output=output,
                baseline_throughput=None,
                max_regression_fraction=0.10,
                ratio_call_limit=64,
                throughput_warmup_rollouts=2,
                throughput_timed_rollouts=8,
                throughput_agents=2048,
                throughput_horizon=64,
                throughput_minibatch_size=16384,
            )
            with mock.patch.object(self.q, "_run_worker") as worker, \
                    self.assertRaises(self.q.QualificationError):
                self.q.run_qualification(args)
            worker.assert_not_called()
            receipt = json.loads(
                (output / "QUALIFICATION.json").read_text(encoding="utf-8")
            )
            self.assertIs(receipt["accepted"], False)
            self.assertEqual(receipt["status"], "in_progress")

    def test_throughput_baseline_is_bounded_external_and_digest_bound(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "qualification"
            baseline = root / "baseline.json"
            throughput = {
                "host": "rtx2070",
                "gpu": "RTX 2070",
                "gpu_uuid": "GPU-00000000",
                "precision_bytes": 4,
                "config": {"cudagraphs": 10},
                "steps_per_second": 1000.0,
                "hard_integrity_zero": True,
                "steps": 1000,
                "elapsed_seconds": 1.0,
                "median_rollout_seconds": 0.1,
                "p95_rollout_seconds": 0.2,
                "hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "warmup_hard_integrity_zero": True,
                "warmup_hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "tail_records_explicitly_discarded": 10,
                "utilization": {},
            }
            baseline.write_text(
                json.dumps({"throughput": throughput}),
                encoding="utf-8",
            )
            observed, identity = self.q.load_required_throughput_baseline(
                baseline,
                output=output,
            )
            self.assertEqual(observed, throughput)
            self.assertEqual(identity["path"], str(baseline.resolve()))
            self.assertEqual(identity["sha256"], self.q.sha256(baseline))

            output.mkdir()
            internal = output / "baseline.json"
            internal.write_bytes(baseline.read_bytes())
            with self.assertRaises(self.q.QualificationError):
                self.q.load_required_throughput_baseline(
                    internal,
                    output=output,
                )
            parent_alias = root / "qualification-alias"
            parent_alias.symlink_to(output, target_is_directory=True)
            with self.assertRaises(self.q.QualificationError):
                self.q.load_required_throughput_baseline(
                    parent_alias / internal.name,
                    output=output,
                )
            symlink = root / "baseline-link.json"
            symlink.symlink_to(baseline)
            with self.assertRaises(self.q.QualificationError):
                self.q.load_required_throughput_baseline(
                    symlink,
                    output=output,
                )

    def test_throughput_baseline_hashes_the_exact_bytes_it_parses(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / "qualification"
            baseline = root / "baseline.json"
            valid = {
                "host": "rtx2070",
                "gpu": "RTX 2070",
                "gpu_uuid": "GPU-00000000",
                "precision_bytes": 4,
                "config": {"cudagraphs": 10},
                "steps_per_second": 1000.0,
                "hard_integrity_zero": True,
                "steps": 1000,
                "elapsed_seconds": 1.0,
                "median_rollout_seconds": 0.1,
                "p95_rollout_seconds": 0.2,
                "hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "warmup_hard_integrity_zero": True,
                "warmup_hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "tail_records_explicitly_discarded": 10,
                "utilization": {},
            }
            encoded = json.dumps({"throughput": valid}).encode("utf-8")
            baseline.write_bytes(b"not the bytes returned by the one-read helper")
            with mock.patch.object(
                self.q,
                "_read_bounded_regular_bytes",
                return_value=encoded,
            ) as read_once:
                observed, identity = (
                    self.q.load_required_throughput_baseline(
                        baseline,
                        output=output,
                    )
                )
            self.assertEqual(observed, valid)
            self.assertEqual(
                identity["sha256"],
                hashlib.sha256(encoded).hexdigest(),
            )
            self.assertEqual(identity["bytes"], len(encoded))
            read_once.assert_called_once()

    def test_throughput_baseline_reads_the_canonical_checked_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            real_parent = root / "real-baseline"
            real_parent.mkdir()
            alias_parent = root / "baseline-alias"
            alias_parent.symlink_to(real_parent, target_is_directory=True)
            aliased = alias_parent / "baseline.json"
            canonical = real_parent / "baseline.json"
            canonical.write_text("{}\n", encoding="utf-8")
            valid = {
                "host": "rtx2070",
                "gpu": "RTX 2070",
                "gpu_uuid": "GPU-00000000",
                "precision_bytes": 4,
                "config": {"cudagraphs": 10},
                "steps_per_second": 1000.0,
                "hard_integrity_zero": True,
                "steps": 1000,
                "elapsed_seconds": 1.0,
                "median_rollout_seconds": 0.1,
                "p95_rollout_seconds": 0.2,
                "hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "warmup_hard_integrity_zero": True,
                "warmup_hard_integrity": {
                    key: 0.0 for key in self.q.HARD_INTEGRITY_KEYS
                },
                "tail_records_explicitly_discarded": 10,
                "utilization": {},
            }
            encoded = json.dumps({"throughput": valid}).encode("utf-8")
            with mock.patch.object(
                self.q,
                "_read_bounded_regular_bytes",
                return_value=encoded,
            ) as read:
                _, identity = self.q.load_required_throughput_baseline(
                    aliased,
                    output=root / "candidate",
                )
            self.assertEqual(read.call_args.args[0], canonical.resolve())
            self.assertEqual(identity["path"], str(canonical.resolve()))

    def test_verifier_digest_binds_the_exact_source_bytes_executed(self):
        source = textwrap.dedent(
            """
            def reference_advantages(**kwargs):
                return [[1.0]]

            def verification_cases():
                return []

            def verify_backend(backend, torch, device):
                return {"device": device}
            """
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as temporary:
            verifier = pathlib.Path(temporary) / "verifier.py"
            verifier.write_bytes(source)
            with mock.patch.object(
                self.q,
                "ROLLOUT_TRANSITION_VERIFIER",
                verifier,
            ):
                module, identity = (
                    self.q._load_rollout_transition_verifier()
                )
            verifier.write_text("raise RuntimeError('replacement')\n", encoding="utf-8")
            self.assertEqual(
                module.verify_backend(None, None, "cuda"),
                {"device": "cuda"},
            )
            self.assertEqual(
                identity["sha256"],
                hashlib.sha256(source).hexdigest(),
            )

    def test_top_level_acceptance_is_and_of_all_named_mandatory_gates(self):
        gates = {name: {"accepted": True} for name in self.q.MANDATORY_GATES}
        verdict = self.q.combine_gate_verdicts(gates)
        self.assertTrue(verdict["accepted"])
        gates["ratio"]["accepted"] = False
        verdict = self.q.combine_gate_verdicts(gates)
        self.assertFalse(verdict["accepted"])
        del gates["throughput"]
        with self.assertRaises(self.q.QualificationError):
            self.q.combine_gate_verdicts(gates)


class EntropyScheduleQualificationContractTests(unittest.TestCase):
    """Red contracts for schema-11 parent-owned objective-parity evidence."""

    @classmethod
    def setUpClass(cls):
        cls.q = load_runner()

    def test_schema_11_requires_entropy_gate_and_exact_five_cell_matrix(self):
        self.assertEqual(self.q.SCHEMA_VERSION, 11)
        self.assertIn("entropy_schedule_parity", self.q.MANDATORY_GATES)
        self.assertEqual(
            self.q.ENTROPY_SCHEDULE_CONTRACT,
            ENTROPY_SCHEDULE_CONTRACT,
        )
        self.assertEqual(
            self.q.ENTROPY_TELEMETRY_CONTRACT,
            ENTROPY_TELEMETRY_CONTRACT,
        )
        self.assertEqual(
            self.q.ENTROPY_OVERRUN_STATE_CONTRACT,
            ENTROPY_OVERRUN_STATE_CONTRACT,
        )
        self.assertEqual(
            tuple(self.q.ENTROPY_SCHEDULE_CELL_KINDS),
            ENTROPY_SCHEDULE_CELL_KINDS,
        )
        self.assertEqual(
            len(set(self.q.ENTROPY_SCHEDULE_CELL_KINDS)),
            len(ENTROPY_SCHEDULE_CELL_KINDS),
        )
        self.assertEqual(
            tuple(self.q.ENTROPY_GRADIENT_CONTROL_CELL_KINDS),
            ENTROPY_GRADIENT_CONTROL_CELL_KINDS,
        )
        self.assertEqual(
            tuple(self.q.ENTROPY_QUALIFICATION_CELL_KINDS),
            ENTROPY_QUALIFICATION_CELL_KINDS,
        )
        self.assertTrue(
            set(ENTROPY_QUALIFICATION_CELL_KINDS).issubset(
                self.q.CELL_KINDS
            )
        )
        self.assertTrue(
            set(ENTROPY_QUALIFICATION_CELL_KINDS).issubset(
                self.q.ARRAY_CELL_KINDS
            )
        )

    def test_entropy_gate_omission_is_always_fatal(self):
        gates = {
            name: {"accepted": True}
            for name in self.q.MANDATORY_GATES
        }
        self.assertTrue(self.q.combine_gate_verdicts(gates)["accepted"])
        del gates["entropy_schedule_parity"]
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "mandatory gate set mismatch",
        ):
            self.q.combine_gate_verdicts(gates)

    def test_ordinary_entropy_execution_npz_schema_is_backend_owned(self):
        common_fields = set(
            self.q.ENTROPY_COMMON_EXECUTION_ARRAY_FIELDS
        )
        native_counter_fields = set(
            self.q.ENTROPY_NATIVE_EXECUTION_COUNTER_ARRAY_FIELDS
        )
        fixtures = {}
        for kind in (
            "entropy_native_graph_annealed",
            "entropy_torch_annealed",
        ):
            execution, config, arrays = entropy_execution_evidence(
                self.q,
                kind,
            )
            fixtures[kind] = (execution, config, arrays)
            native = kind in self.q.ENTROPY_NATIVE_CELL_KINDS
            expected_fields = (
                common_fields | native_counter_fields
                if native
                else common_fields
            )
            with self.subTest(kind=kind, mutation="none"):
                self.assertEqual(set(arrays), expected_fields)
                summary = self.q.validate_entropy_execution_evidence(
                    execution,
                    arrays,
                    expected_kind=kind,
                    config=config,
                )
                self.assertEqual(
                    summary["backend"],
                    "native" if native else "torch",
                )

            raw_evidence, raw_arrays = entropy_raw_evidence(kind)
            complete_arrays = {
                **raw_arrays,
                **arrays,
            }
            with self.subTest(kind=kind, schema="complete"):
                self.q.validate_entropy_schedule_cell_evidence(
                    raw_evidence,
                    complete_arrays,
                    expected_kind=kind,
                    expected_schedule=raw_evidence["schedule"],
                )

            for field in common_fields:
                changed = {
                    name: value.copy()
                    for name, value in arrays.items()
                    if name != field
                }
                with self.subTest(
                    kind=kind,
                    mutation=f"missing common {field}",
                ), self.assertRaisesRegex(
                    self.q.QualificationError,
                    "common execution NPZ arrays are incomplete",
                ):
                    self.q.validate_entropy_execution_evidence(
                        execution,
                        changed,
                        expected_kind=kind,
                        config=config,
                    )

        native_kind = "entropy_native_graph_annealed"
        native_execution, native_config, native_arrays = fixtures[
            native_kind
        ]
        native_raw_evidence, native_raw_arrays = entropy_raw_evidence(
            native_kind
        )
        for field in native_counter_fields:
            changed = {
                name: value.copy()
                for name, value in native_arrays.items()
                if name != field
            }
            with self.subTest(
                kind=native_kind,
                mutation=f"missing native counter {field}",
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "native entropy execution counter NPZ arrays are incomplete",
            ):
                self.q.validate_entropy_execution_evidence(
                    native_execution,
                    changed,
                    expected_kind=native_kind,
                    config=native_config,
                )
            with self.subTest(
                kind=native_kind,
                schema=f"missing native counter {field}",
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "entropy NPZ array schema differs",
            ):
                self.q.validate_entropy_schedule_cell_evidence(
                    native_raw_evidence,
                    {
                        **native_raw_arrays,
                        **changed,
                    },
                    expected_kind=native_kind,
                    expected_schedule=native_raw_evidence["schedule"],
                )

        changed_native = {
            name: value.copy()
            for name, value in native_arrays.items()
        }
        changed_native["graph_train_delta"][7] += np.int64(1)
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "entropy execution counter differs",
        ):
            self.q.validate_entropy_execution_evidence(
                native_execution,
                changed_native,
                expected_kind=native_kind,
                config=native_config,
            )

        torch_kind = "entropy_torch_annealed"
        torch_execution, torch_config, torch_arrays = fixtures[torch_kind]
        torch_raw_evidence, torch_raw_arrays = entropy_raw_evidence(
            torch_kind
        )
        for field in native_counter_fields:
            injected = {
                name: value.copy()
                for name, value in torch_arrays.items()
            }
            injected[field] = np.zeros(
                self.q.ENTROPY_SCHEDULE_TOTAL_UPDATES,
                dtype=np.int64,
            )
            with self.subTest(
                kind=torch_kind,
                mutation=f"fabricated native counter {field}",
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "Torch entropy execution NPZ contains native-only counters",
            ):
                self.q.validate_entropy_execution_evidence(
                    torch_execution,
                    injected,
                    expected_kind=torch_kind,
                    config=torch_config,
                )
            with self.subTest(
                kind=torch_kind,
                schema=f"fabricated native counter {field}",
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "entropy NPZ array schema differs",
            ):
                self.q.validate_entropy_schedule_cell_evidence(
                    torch_raw_evidence,
                    {
                        **torch_raw_arrays,
                        **injected,
                    },
                    expected_kind=torch_kind,
                    expected_schedule=torch_raw_evidence["schedule"],
                )

    def test_worker_never_synthesizes_torch_native_execution_counters(self):
        source = RUNNER.read_text(encoding="utf-8")
        worker = source[
            source.index("def _measure_entropy_schedule_cell("):
            source.index("def run_cell(")
        ]
        self.assertIn("common_execution_values", worker)
        self.assertIn("native_execution_counter_values", worker)
        self.assertNotIn(
            'execution_values[f"{mode}_{role}_delta"].append(0)',
            worker,
        )
        self.assertNotIn(
            "native_execution_counter_values"
            '[f"{mode}_{role}_delta"].append(0)',
            worker,
        )

    def test_all_gradient_pairs_and_native_mode_parity_are_mandatory(self):
        pairs = (
            (
                "entropy_native_eager_annealed",
                "entropy_native_eager_anneal_disabled",
                "native_eager",
            ),
            (
                "entropy_native_graph_annealed",
                "entropy_native_graph_anneal_disabled",
                "native_graph",
            ),
            (
                "entropy_torch_annealed",
                "entropy_torch_anneal_disabled",
                "torch",
            ),
        )
        enabled_by_kind = {}
        for enabled_kind, disabled_kind, expected_role in pairs:
            (enabled, disabled) = entropy_gradient_pair_evidence(
                self.q,
                enabled_kind=enabled_kind,
                disabled_kind=disabled_kind,
            )
            enabled_evidence, enabled_arrays = enabled
            disabled_evidence, disabled_arrays = disabled
            enabled_by_kind[enabled_kind] = enabled_arrays
            with self.subTest(pair=expected_role, evidence="enabled"):
                self.q.validate_entropy_gradient_cell_evidence(
                    enabled_evidence,
                    enabled_arrays,
                    expected_kind=enabled_kind,
                )
            with self.subTest(pair=expected_role, evidence="disabled"):
                self.q.validate_entropy_gradient_cell_evidence(
                    disabled_evidence,
                    disabled_arrays,
                    expected_kind=disabled_kind,
                )
            with self.subTest(pair=expected_role, mutation="none"):
                summary = self.q.validate_entropy_gradient_pair(
                    enabled_arrays,
                    disabled_arrays,
                    enabled_kind=enabled_kind,
                    disabled_kind=disabled_kind,
                )
                self.assertEqual(summary["role"], expected_role)
                self.assertGreater(
                    summary["max_observed_gradient_delta"],
                    2.0e-7,
                )
            corrupted = {
                key: value.copy()
                for key, value in enabled_arrays.items()
            }
            corrupted["gradient_grad_logits"][10, 0, 0, 0] += np.float32(
                0.25
            )
            with self.subTest(
                pair=expected_role,
                mutation="gradient",
            ), self.assertRaisesRegex(
                self.q.QualificationError,
                "gradient scale/sign",
            ):
                self.q.validate_entropy_gradient_pair(
                    corrupted,
                    disabled_arrays,
                    enabled_kind=enabled_kind,
                    disabled_kind=disabled_kind,
                )

        parity = self.q.validate_entropy_native_mode_gradient_parity(
            enabled_by_kind["entropy_native_eager_annealed"],
            enabled_by_kind["entropy_native_graph_annealed"],
        )
        self.assertIs(parity["all_raw_gradient_arrays_equal"], True)
        corrupted_graph = {
            key: value.copy()
            for key, value in enabled_by_kind[
                "entropy_native_graph_annealed"
            ].items()
        }
        corrupted_graph["gradient_grad_values"][3, 0, 0] = np.float32(
            1.0
        )
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "native eager/graph entropy gradient differs",
        ):
            self.q.validate_entropy_native_mode_gradient_parity(
                enabled_by_kind["entropy_native_eager_annealed"],
                corrupted_graph,
            )

    def test_entropy_gradient_pair_rejects_systematic_scale_error(self):
        pairs = (
            (
                "entropy_native_eager_annealed",
                "entropy_native_eager_anneal_disabled",
            ),
            (
                "entropy_native_graph_annealed",
                "entropy_native_graph_anneal_disabled",
            ),
            (
                "entropy_torch_annealed",
                "entropy_torch_anneal_disabled",
            ),
        )
        for enabled_kind, disabled_kind in pairs:
            (enabled, disabled) = entropy_gradient_pair_evidence(
                self.q,
                enabled_kind=enabled_kind,
                disabled_kind=disabled_kind,
            )
            _, enabled_arrays = enabled
            _, disabled_arrays = disabled
            baseline = disabled_arrays["gradient_grad_logits"]
            delta = (
                enabled_arrays["gradient_grad_logits"] - baseline
            )
            for scale in (np.float32(0.971), np.float32(0.99)):
                changed = {
                    key: value.copy()
                    for key, value in enabled_arrays.items()
                }
                changed["gradient_grad_logits"] = (
                    baseline + scale * delta
                ).astype(np.float32)
                with self.subTest(
                    enabled_kind=enabled_kind,
                    scale=float(scale),
                ), self.assertRaisesRegex(
                    self.q.QualificationError,
                    "gradient scale/sign",
                ):
                    self.q.validate_entropy_gradient_pair(
                        changed,
                        disabled_arrays,
                        enabled_kind=enabled_kind,
                        disabled_kind=disabled_kind,
                    )

    def test_entropy_gradient_cell_rejects_coordinated_forward_entropy_offset(
        self,
    ):
        kind = "entropy_native_eager_annealed"
        (enabled, _) = entropy_gradient_pair_evidence(
            self.q,
            enabled_kind=kind,
            disabled_kind="entropy_native_eager_anneal_disabled",
        )
        evidence, arrays = enabled
        changed = {
            key: value.copy()
            for key, value in arrays.items()
        }
        for offset in (np.float32(1.0), np.float32(1.0e-3)):
            corrupted = {
                key: value.copy()
                for key, value in changed.items()
            }
            corrupted["entropy"] += offset
            corrupted["signed_entropy_term"] = (
                -corrupted["device_coefficient"] * corrupted["entropy"]
            ).astype(np.float32)
            corrupted["total_loss"] = (
                corrupted["policy_loss"]
                + np.float32(0.5) * corrupted["value_loss"]
                + corrupted["signed_entropy_term"]
            ).astype(np.float32)
            with self.subTest(offset=float(offset)), self.assertRaisesRegex(
                self.q.QualificationError,
                "forward entropy",
            ):
                self.q.validate_entropy_gradient_cell_evidence(
                    evidence,
                    corrupted,
                    expected_kind=kind,
                )

    def test_parent_validates_native_and_torch_overrun_evidence(self):
        for kind in (
            "entropy_native_graph_annealed",
            "entropy_torch_annealed",
        ):
            evidence, config, arrays = entropy_overrun_evidence(self.q, kind)
            with self.subTest(kind=kind):
                summary = self.q.validate_entropy_overrun_evidence(
                    evidence,
                    expected_kind=kind,
                    config=config,
                    arrays=arrays,
                )
                self.assertEqual(summary["kind"], kind)
                self.assertEqual(
                    summary["attempted_update_index"],
                    self.q.ENTROPY_SCHEDULE_TOTAL_UPDATES,
                )
                self.assertIs(
                    summary["state_unchanged"]["execution_counters"],
                    (
                        True
                        if kind.startswith("entropy_native_")
                        else None
                    ),
                )
                self.assertNotIn("accepted", summary)
                self.assertNotIn("passed", summary)
                if kind.startswith("entropy_native_"):
                    snapshot = evidence["native_state"]["before"]
                    self.assertEqual(
                        snapshot["tensors"]["master_weights"]["elements"],
                        219_456,
                    )
                    self.assertEqual(
                        snapshot["tensors"]["master_weights"]["bytes"],
                        877_824,
                    )
                    self.assertEqual(
                        snapshot["used_bytes"],
                        1_755_708,
                    )

    def test_parent_rejects_every_overrun_evidence_mutation(self):
        for kind in (
            "entropy_native_graph_annealed",
            "entropy_torch_annealed",
        ):
            evidence, config, arrays = entropy_overrun_evidence(self.q, kind)

            def reject(label, changed, changed_config=None):
                with self.subTest(kind=kind, mutation=label), self.assertRaises(
                    self.q.QualificationError
                ):
                    self.q.validate_entropy_overrun_evidence(
                        changed,
                        expected_kind=kind,
                        config=(
                            config
                            if changed_config is None
                            else changed_config
                        ),
                        arrays=arrays,
                    )

            for key in tuple(evidence):
                changed = json.loads(json.dumps(evidence))
                del changed[key]
                reject(f"missing top-level key {key}", changed)
            for extra in ("accepted", "passed", "worker_verdict"):
                changed = json.loads(json.dumps(evidence))
                changed[extra] = True
                reject(f"extra top-level key {extra}", changed)

            for key, value in (
                ("kind", "entropy_native_eager_annealed"),
                (
                    "backend",
                    "torch" if evidence["backend"] == "native" else "native",
                ),
                ("exception_type", "ValueError"),
                ("exception_message", "rejected"),
            ):
                changed = json.loads(json.dumps(evidence))
                changed[key] = value
                reject(f"wrong {key}", changed)

            for key in (
                "attempted_update_index",
                "epoch_before",
                "epoch_after",
                "global_step_before",
                "global_step_after",
                "tail_valid_before",
                "tail_valid_after",
            ):
                changed = json.loads(json.dumps(evidence))
                changed[key] += 1
                reject(f"wrong {key}", changed)
                changed = json.loads(json.dumps(evidence))
                changed[key] = float(changed[key])
                reject(f"float impostor {key}", changed)
            for key in ("tail_valid_before", "tail_valid_after"):
                changed = json.loads(json.dumps(evidence))
                changed[key] = False
                reject(f"boolean impostor {key}", changed)

            changed = json.loads(json.dumps(evidence))
            changed["weights_before_sha256"] = "malformed"
            reject("malformed before digest", changed)
            changed = json.loads(json.dumps(evidence))
            changed["weights_after_sha256"] = "b" * 64
            reject("changed weights digest", changed)

            if evidence["backend"] == "native":
                for mode in ("graph", "eager"):
                    changed = json.loads(json.dumps(evidence))
                    del changed["execution_counter_deltas"][mode]
                    reject(f"missing mode {mode}", changed)
                changed = json.loads(json.dumps(evidence))
                changed["execution_counter_deltas"]["other"] = {}
                reject("extra execution mode", changed)

                for mode in ("graph", "eager"):
                    for role in ("rollout", "tail", "train"):
                        changed = json.loads(json.dumps(evidence))
                        del changed["execution_counter_deltas"][mode][role]
                        reject(f"missing role {mode}/{role}", changed)
                        changed = json.loads(json.dumps(evidence))
                        changed["execution_counter_deltas"][mode]["other"] = 0
                        reject(f"extra role {mode}", changed)
                        for value in (1, -1, 0.0, False):
                            changed = json.loads(json.dumps(evidence))
                            changed["execution_counter_deltas"][mode][role] = value
                            reject(
                                f"counter {mode}/{role}={value!r}",
                                changed,
                            )
            else:
                changed = json.loads(json.dumps(evidence))
                changed["execution_counter_deltas"] = {
                    mode: {
                        role: 0
                        for role in ("rollout", "tail", "train")
                    }
                    for mode in ("graph", "eager")
                }
                reject("fabricated Torch execution counters", changed)

            for section, key in (
                ("vec", "total_agents"),
                ("vec", "num_buffers"),
                ("train", "horizon"),
            ):
                changed_config = json.loads(json.dumps(config))
                changed_config[section][key] = float(
                    changed_config[section][key]
                )
                reject(
                    f"float config impostor {section}/{key}",
                    evidence,
                    changed_config,
                )

    def test_parent_rejects_native_overrun_state_mutations(self):
        kind = "entropy_native_graph_annealed"
        evidence, config, arrays = entropy_overrun_evidence(self.q, kind)

        def changed():
            return json.loads(json.dumps(evidence))

        def reject(label, record, changed_arrays=None):
            with self.subTest(mutation=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_entropy_overrun_evidence(
                    record,
                    expected_kind=kind,
                    config=config,
                    arrays=(
                        arrays
                        if changed_arrays is None
                        else changed_arrays
                    ),
                )

        record = changed()
        record["native_state"] = None
        reject("native state absent", record)

        for key in ("before", "after"):
            record = changed()
            del record["native_state"][key]
            reject(f"missing native-state boundary {key}", record)
        record = changed()
        record["native_state"]["worker_verdict"] = True
        reject("extra native-state verdict", record)

        for boundary in ("before", "after"):
            snapshot = evidence["native_state"][boundary]
            for key in tuple(snapshot):
                record = changed()
                del record["native_state"][boundary][key]
                reject(f"missing snapshot {boundary}/{key}", record)
            record = changed()
            record["native_state"][boundary]["accepted"] = True
            reject(f"extra snapshot verdict {boundary}", record)

            for field, original in snapshot["host"].items():
                record = changed()
                host = record["native_state"][boundary]["host"]
                if type(original) is bool:
                    host[field] = not original
                elif type(original) is int:
                    host[field] = original + 1
                else:
                    host[field] = float(
                        np.nextafter(
                            np.float32(original),
                            np.float32(np.inf),
                        )
                    )
                reject(f"changed host {boundary}/{field}", record)

                record = changed()
                host = record["native_state"][boundary]["host"]
                if type(original) is bool:
                    host[field] = int(original)
                elif type(original) is int:
                    host[field] = float(original)
                else:
                    host[field] = int(original)
                reject(f"type impostor host {boundary}/{field}", record)

            record = changed()
            del record["native_state"][boundary]["host"]["epoch"]
            reject(f"missing host field {boundary}", record)
            record = changed()
            record["native_state"][boundary]["host"]["other"] = 0
            reject(f"extra host field {boundary}", record)

            for tensor_name, tensor in snapshot["tensors"].items():
                record = changed()
                del record["native_state"][boundary]["tensors"][
                    tensor_name
                ]
                reject(
                    f"missing tensor {boundary}/{tensor_name}",
                    record,
                )
                metadata_mutations = {
                    "name": "other",
                    "dtype": "f64",
                    "shape": [tensor["shape"][0] + 1],
                    "present": False,
                    "elements": tensor["elements"] + 1,
                    "bytes": tensor["bytes"] + 4,
                    "sha256": "b" * 64,
                    "nonzero": tensor["elements"] + 1,
                    "nonfinite": 1,
                    "values": (
                        []
                        if tensor["values"] is None
                        else [
                            float(
                                np.nextafter(
                                    np.float32(tensor["values"][0]),
                                    np.float32(np.inf),
                                )
                            ),
                            *tensor["values"][1:],
                        ]
                    ),
                }
                for field, value in metadata_mutations.items():
                    record = changed()
                    record["native_state"][boundary]["tensors"][
                        tensor_name
                    ][field] = value
                    reject(
                        f"tensor metadata {boundary}/{tensor_name}/{field}",
                        record,
                    )
                record = changed()
                record["native_state"][boundary]["tensors"][
                    tensor_name
                ]["worker_verdict"] = True
                reject(
                    f"extra tensor metadata {boundary}/{tensor_name}",
                    record,
                )

            record = changed()
            record["native_state"][boundary]["tensors"]["other"] = {}
            reject(f"extra tensor {boundary}", record)

        record = changed()
        record["native_state"]["before"]["max_bytes"] -= 1
        reject("wrong snapshot byte limit", record)
        record = changed()
        record["native_state"]["before"]["used_bytes"] += 4
        reject("wrong snapshot byte ledger", record)

        changed_arrays = {
            key: value.copy() for key, value in arrays.items()
        }
        changed_arrays["device_coefficient"][-1] = np.nextafter(
            changed_arrays["device_coefficient"][-1],
            np.float32(np.inf),
        )
        reject("snapshot coefficient differs from NPZ", evidence, changed_arrays)
        changed_arrays = {
            key: value.copy() for key, value in arrays.items()
        }
        changed_arrays["total_loss"][-1] = np.nextafter(
            changed_arrays["total_loss"][-1],
            np.float32(np.inf),
        )
        reject("snapshot scalar loss differs from NPZ", evidence, changed_arrays)

        torch_kind = "entropy_torch_annealed"
        torch_evidence, torch_config, torch_arrays = entropy_overrun_evidence(
            self.q,
            torch_kind,
        )
        torch_evidence["native_state"] = evidence["native_state"]
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "contains native state",
        ):
            self.q.validate_entropy_overrun_evidence(
                torch_evidence,
                expected_kind=torch_kind,
                config=torch_config,
                arrays=torch_arrays,
            )

    def test_parent_rejects_coordinated_native_overrun_claims(self):
        kind = "entropy_native_graph_annealed"
        evidence, config, arrays = entropy_overrun_evidence(self.q, kind)

        def record_copy():
            return json.loads(json.dumps(evidence))

        def arrays_copy():
            return {
                key: value.copy()
                for key, value in arrays.items()
            }

        def reject(
            label,
            record=None,
            changed_config=None,
            changed_arrays=None,
        ):
            with self.subTest(mutation=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q.validate_entropy_overrun_evidence(
                    evidence if record is None else record,
                    expected_kind=kind,
                    config=(
                        config
                        if changed_config is None
                        else changed_config
                    ),
                    arrays=(
                        arrays
                        if changed_arrays is None
                        else changed_arrays
                    ),
                )

        record = record_copy()
        for boundary in ("before", "after"):
            snapshot = record["native_state"][boundary]
            removed = 0
            for name in ("master_weights", "optimizer_momentum"):
                tensor = snapshot["tensors"][name]
                removed += tensor["bytes"] - 4
                tensor["shape"] = [1]
                tensor["elements"] = 1
                tensor["bytes"] = 4
                tensor["nonzero"] = 1
            snapshot["used_bytes"] -= removed
        reject("coordinated large-tensor shrink", record=record)

        record = record_copy()
        for boundary in ("before", "after"):
            record["native_state"][boundary]["tensors"][
                "optimizer_momentum"
            ]["sha256"] = "b" * 64
        reject("coordinated arbitrary momentum digest", record=record)

        record = record_copy()
        for boundary in ("before", "after"):
            tensors = record["native_state"][boundary]["tensors"]
            tensors["optimizer_momentum"]["sha256"] = tensors[
                "master_weights"
            ]["sha256"]
            tensors["optimizer_momentum"]["nonzero"] = tensors[
                "master_weights"
            ]["nonzero"]
        reject("momentum aliases master weights", record=record)

        for name in self.q.ENTROPY_OVERRUN_SMALL_TENSORS:
            record = record_copy()
            for boundary in ("before", "after"):
                record["native_state"][boundary]["tensors"][name][
                    "sha256"
                ] = "b" * 64
            reject(
                f"coordinated small-tensor digest {name}",
                record=record,
            )

        for name in ("master_weights", "optimizer_momentum"):
            record = record_copy()
            for boundary in ("before", "after"):
                record["native_state"][boundary]["tensors"][name][
                    "nonzero"
                ] = 1
            reject(
                f"coordinated false nonzero count {name}",
                record=record,
            )

        record = record_copy()
        for boundary in ("before", "after"):
            host = record["native_state"][boundary]["host"]
            host["current_ent_coef"] += 1.0e-12
        reject("noncanonical host f32 alias", record=record)

        record = record_copy()
        for boundary in ("before", "after"):
            values = record["native_state"][boundary]["tensors"][
                "device_entropy_coefficient"
            ]["values"]
            values[0] += 1.0e-12
        reject("noncanonical tensor f32 alias", record=record)

        for section, key, value in (
            ("train", "learning_rate", 0.5),
            ("train", "anneal_lr", True),
            ("train", "minibatch_size", 1),
            ("train", "replay_ratio", 9),
            ("train", "total_timesteps", 1),
            ("policy", "hidden_size", 32),
            ("policy", "num_layers", 2),
        ):
            changed_config = json.loads(json.dumps(config))
            changed_config[section][key] = value
            reject(
                f"configuration drift {section}/{key}",
                changed_config=changed_config,
            )

        for label, value in (
            ("integer zero", 0),
            ("boolean false", False),
            ("negative zero", -0.0),
            ("sub-f32 epsilon", 1.0e-12),
        ):
            changed_config = json.loads(json.dumps(config))
            changed_config["train"]["learning_rate"] = value
            reject(
                f"learning-rate spelling {label}",
                changed_config=changed_config,
            )

        changed_arrays = arrays_copy()
        changed_arrays[
            "overrun_state_after_optimizer_momentum"
        ][0] = np.nextafter(
            changed_arrays[
                "overrun_state_after_optimizer_momentum"
            ][0],
            np.float32(np.inf),
        )
        reject(
            "raw momentum differs after rejection",
            changed_arrays=changed_arrays,
        )

        changed_arrays = arrays_copy()
        changed_arrays["overrun_state_extra"] = np.zeros(
            1,
            dtype=np.float32,
        )
        reject(
            "extra overrun NPZ namespace field",
            changed_arrays=changed_arrays,
        )

        torch_kind = "entropy_torch_annealed"
        torch_evidence, torch_config, torch_arrays = (
            entropy_overrun_evidence(self.q, torch_kind)
        )
        torch_arrays["overrun_state_extra"] = np.zeros(
            1,
            dtype=np.float32,
        )
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "NPZ array namespace differs",
        ):
            self.q.validate_entropy_overrun_evidence(
                torch_evidence,
                expected_kind=torch_kind,
                config=torch_config,
                arrays=torch_arrays,
            )

    def test_native_overrun_raw_state_decoder_is_closed_and_bounded(self):
        evidence, _, arrays = entropy_overrun_evidence(
            self.q,
            "entropy_native_graph_annealed",
        )
        expected = evidence["native_state"]["before"]
        raw_values = {
            "device_entropy_coefficient": np.asarray(
                expected["tensors"]["device_entropy_coefficient"]["values"],
                dtype=np.float32,
            ),
            "loss_accumulator": np.asarray(
                expected["tensors"]["loss_accumulator"]["values"],
                dtype=np.float32,
            ),
            "scalar_loss": np.asarray(
                expected["tensors"]["scalar_loss"]["values"],
                dtype=np.float32,
            ),
            "master_weights": arrays[
                "overrun_state_before_master_weights"
            ],
            "optimizer_momentum": arrays[
                "overrun_state_before_optimizer_momentum"
            ],
            "optimizer_learning_rate": np.zeros(1, dtype=np.float32),
            "optimizer_learning_rate_derived": np.zeros(
                2,
                dtype=np.float32,
            ),
        }
        raw = {
            "contract": ENTROPY_OVERRUN_STATE_CONTRACT,
            "max_bytes": self.q.QUALIFICATION_POLICY_MAX_BYTES,
            "used_bytes": sum(value.nbytes for value in raw_values.values()),
            "host": json.loads(json.dumps(expected["host"])),
            "tensors": {
                name: {
                    "name": name,
                    "dtype": "f32",
                    "shape": list(value.shape),
                    "present": True,
                    "data": value.tobytes(order="C"),
                    "bytes": value.nbytes,
                }
                for name, value in raw_values.items()
            },
        }
        captured = {}
        self.assertEqual(
            self.q._decode_entropy_overrun_state(
                raw,
                captured_arrays=captured,
                boundary="before",
            ),
            expected,
        )
        self.assertEqual(
            set(captured),
            {
                "overrun_state_before_master_weights",
                "overrun_state_before_optimizer_momentum",
            },
        )
        self.assertTrue(
            np.array_equal(
                captured["overrun_state_before_master_weights"],
                raw_values["master_weights"],
            )
        )
        self.assertTrue(
            np.array_equal(
                captured["overrun_state_before_optimizer_momentum"],
                raw_values["optimizer_momentum"],
            )
        )

        mutations = []
        changed = json.loads(
            json.dumps(raw, default=lambda value: value.hex())
        )
        # Reconstitute payloads after the JSON structural copy.
        for name, tensor in changed["tensors"].items():
            tensor["data"] = bytes.fromhex(tensor["data"])
        changed["used_bytes"] += 4
        mutations.append(("used-byte ledger", changed))

        changed = {
            **raw,
            "host": dict(raw["host"]),
            "tensors": {
                name: dict(tensor)
                for name, tensor in raw["tensors"].items()
            },
        }
        changed["host"]["epoch"] = float(changed["host"]["epoch"])
        mutations.append(("integer impostor", changed))

        changed = {
            **raw,
            "host": dict(raw["host"]),
            "tensors": {
                name: dict(tensor)
                for name, tensor in raw["tensors"].items()
            },
        }
        changed["tensors"]["scalar_loss"]["data"] = np.asarray(
            (np.nan,),
            dtype=np.float32,
        ).tobytes()
        mutations.append(("nonfinite tensor", changed))

        changed = {
            **raw,
            "host": dict(raw["host"]),
            "tensors": {
                name: dict(tensor)
                for name, tensor in raw["tensors"].items()
            },
        }
        changed["tensors"]["master_weights"]["data"] = b"\x00"
        mutations.append(("truncated tensor", changed))

        for label, changed in mutations:
            with self.subTest(mutation=label), self.assertRaises(
                self.q.QualificationError
            ):
                self.q._decode_entropy_overrun_state(changed)

    def test_discrete_absent_grad_logstd_retains_declared_shape(self):
        (enabled, _) = entropy_gradient_pair_evidence(
            self.q,
            enabled_kind="entropy_native_eager_annealed",
            disabled_kind="entropy_native_eager_anneal_disabled",
        )
        evidence, arrays = enabled
        summary = self.q.validate_entropy_gradient_cell_evidence(
            evidence,
            arrays,
            expected_kind="entropy_native_eager_annealed",
        )
        self.assertEqual(
            arrays["gradient_grad_logstd"].shape,
            (self.q.ENTROPY_SCHEDULE_TOTAL_UPDATES, 0),
        )
        metadata = evidence["snapshots"][0]["tensors"]["grad_logstd"]
        self.assertEqual(
            metadata["shape"],
            [2, 2, self.q.BLOODBOWL_ACTION_LOGITS],
        )
        self.assertIs(metadata["present"], False)
        self.assertEqual(metadata["bytes"], 0)
        self.assertEqual(
            metadata["sha256"],
            hashlib.sha256(b"").hexdigest(),
        )
        self.assertEqual(
            summary["contract"],
            ENTROPY_GRADIENT_CONTRACT,
        )

        update = 4
        snapshot = evidence["snapshots"][update]
        raw_tensors = {}
        for name in self.q.ENTROPY_GRADIENT_TENSOR_FIELDS:
            metadata = snapshot["tensors"][name]
            raw_tensors[name] = {
                key: metadata[key]
                for key in (
                    "name",
                    "dtype",
                    "shape",
                    "present",
                    "bytes",
                )
            }
            raw_tensors[name]["data"] = (
                b""
                if not metadata["present"]
                else arrays[f"gradient_{name}"][update].tobytes(
                    order="C"
                )
            )
        raw_state = {
            key: snapshot[key]
            for key in (
                "contract",
                "completed_update_index",
                "committed_epoch",
                "is_continuous",
                "precision",
                "max_bytes",
                "used_bytes",
            )
        }
        raw_state["tensors"] = raw_tensors
        normalized, decoded = self.q._decode_entropy_gradient_state(
            raw_state,
            expected_update_index=update,
            expected_backend="torch",
        )
        self.assertEqual(
            normalized["tensors"]["grad_logstd"]["shape"],
            [2, 2, self.q.BLOODBOWL_ACTION_LOGITS],
        )
        self.assertEqual(decoded["gradient_grad_logstd"].shape, (0,))
        for name in self.q.ENTROPY_GRADIENT_TENSOR_FIELDS:
            if name == "grad_logstd":
                continue
            np.testing.assert_array_equal(
                decoded[f"gradient_{name}"],
                arrays[f"gradient_{name}"][update],
            )

        malformed = json.loads(json.dumps(evidence))
        malformed["snapshots"][0]["tensors"]["grad_logstd"]["shape"] = [0]
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "tensor identity differs",
        ):
            self.q.validate_entropy_gradient_cell_evidence(
                malformed,
                arrays,
                expected_kind="entropy_native_eager_annealed",
            )

        coefficient_evidence = json.loads(json.dumps(evidence))
        coefficient_arrays = {
            key: value.copy() for key, value in arrays.items()
        }
        coefficient_arrays["gradient_entropy_coefficient"][
            7, 0
        ] = np.nextafter(
            coefficient_arrays["gradient_entropy_coefficient"][7, 0],
            np.float32(np.inf),
        )
        coefficient_payload = coefficient_arrays[
            "gradient_entropy_coefficient"
        ][7].tobytes(order="C")
        coefficient_metadata = coefficient_evidence["snapshots"][7][
            "tensors"
        ]["entropy_coefficient"]
        coefficient_metadata["bytes"] = len(coefficient_payload)
        coefficient_metadata["sha256"] = hashlib.sha256(
            coefficient_payload
        ).hexdigest()
        with self.assertRaisesRegex(
            self.q.QualificationError,
            "gradient/forward coefficient telemetry disagrees",
        ):
            self.q.validate_entropy_gradient_cell_evidence(
                coefficient_evidence,
                coefficient_arrays,
                expected_kind="entropy_native_eager_annealed",
            )

    def test_entropy_patch_and_compiled_contract_are_exact_identity(self):
        self.assertTrue(
            ENTROPY_SCHEDULE_PATCH.is_file(),
            "the entropy schedule must be one exact ordered Puffer patch",
        )
        self.assertEqual(
            pathlib.Path(self.q.ENTROPY_SCHEDULE_PATCH),
            ENTROPY_SCHEDULE_PATCH,
        )
        self.assertIn(
            "entropy_schedule_contract",
            self.q.BACKEND_IDENTITY_KEYS,
        )
        source = RUNNER.read_text(encoding="utf-8")
        worker = source[
            source.index("def _run_worker("):
            source.index("def _require_same_identity(")
        ]
        self.assertIn(
            "validate_entropy_schedule_patch_identity(",
            worker,
        )
        self.assertIn(
            '"entropy_schedule_contract"',
            source[
                source.index("def _module_identity("):
                source.index("def validate_module_identity(")
            ],
        )

    def test_torch_gradient_capture_surface_is_bound_into_qualification_patch(
        self,
    ):
        patch = PATCH.read_text(encoding="utf-8")
        for fragment in (
            "def enable_entropy_gradient_qualification(self):",
            "def qualification_entropy_gradient_state(",
            "part.retain_grad()",
            "newvalue.retain_grad()",
            "qualification_pending",
            "'grad_logits'",
            "'grad_values'",
            "'grad_logstd'",
            ENTROPY_GRADIENT_CONTRACT,
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, patch)

    def test_entropy_patch_identity_schema_rejects_every_mutation(self):
        validator = getattr(
            self.q,
            "validate_entropy_schedule_patch_identity",
            None,
        )
        self.assertTrue(
            callable(validator),
            "schema 11 needs a parent-side entropy patch identity validator",
        )
        identity = {
            "puffer_git_head": self.q.PINNED_PUFFER_COMMIT,
            "entropy_schedule_patch": {
                "path": str(ENTROPY_SCHEDULE_PATCH.resolve()),
                "sha256": "a" * 64,
                "reverse_applicable": True,
            },
            "entropy_schedule_contract": ENTROPY_SCHEDULE_CONTRACT,
        }
        self.assertEqual(validator(identity), identity)
        mutations = (
            (
                "wrong pin",
                lambda value: value.update(puffer_git_head="b" * 40),
            ),
            (
                "relative patch path",
                lambda value: value["entropy_schedule_patch"].update(
                    path="training/puffer_entropy_schedule_parity.patch"
                ),
            ),
            (
                "bad patch hash",
                lambda value: value["entropy_schedule_patch"].update(
                    sha256="bad"
                ),
            ),
            (
                "not reverse applicable",
                lambda value: value["entropy_schedule_patch"].update(
                    reverse_applicable=False
                ),
            ),
            (
                "wrong compiled contract",
                lambda value: value.update(
                    entropy_schedule_contract="other-contract"
                ),
            ),
            (
                "unbound extra key",
                lambda value: value.update(worker_claimed_pass=True),
            ),
        )
        for label, mutate in mutations:
            changed = json.loads(json.dumps(identity))
            mutate(changed)
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                validator(changed)

    def test_parent_validates_raw_json_npz_for_all_five_cells(self):
        validator = getattr(
            self.q,
            "validate_entropy_schedule_cell_evidence",
            None,
        )
        self.assertTrue(
            callable(validator),
            "schema 11 needs a parent-owned raw entropy evidence validator",
        )
        for kind in ENTROPY_SCHEDULE_CELL_KINDS:
            evidence, arrays = entropy_raw_evidence(kind)
            with self.subTest(kind=kind):
                summary = validator(
                    evidence,
                    arrays,
                    expected_kind=kind,
                    expected_schedule=evidence["schedule"],
                )
                self.assertNotIn("accepted", summary)
                self.assertNotIn("passed", summary)
                self.assertEqual(summary["kind"], kind)
                self.assertEqual(
                    summary["update_count"],
                    evidence["schedule"]["total_updates"],
                )
                self.assertEqual(
                    summary["schedule"],
                    evidence["schedule"],
                )

    def test_parent_rejects_entropy_evidence_mutations_and_worker_verdicts(self):
        validator = getattr(
            self.q,
            "validate_entropy_schedule_cell_evidence",
            None,
        )
        self.assertTrue(
            callable(validator),
            "schema 11 needs mutation-rejecting parent validation",
        )
        kind = "entropy_native_graph_annealed"
        evidence, arrays = entropy_raw_evidence(kind)
        expected_schedule = json.loads(json.dumps(evidence["schedule"]))

        def changed():
            return (
                json.loads(json.dumps(evidence)),
                {key: value.copy() for key, value in arrays.items()},
            )

        mutations = []

        record, data = changed()
        record["accepted"] = True
        mutations.append(("worker-authored verdict", record, data))

        record, data = changed()
        record["telemetry_contract"] = "telemetry-only"
        mutations.append(("missing telemetry marker", record, data))

        record, data = changed()
        record["schedule"]["base"] = 0.25
        mutations.append(("wrong base", record, data))

        record, data = changed()
        record["schedule"]["floor_coefficient"] = 0.0
        mutations.append(("wrong floor", record, data))

        record, data = changed()
        record["schedule"]["total_updates"] -= 1
        mutations.append(("wrong denominator", record, data))

        record, data = changed()
        record["weights_after_sha256"] = "d" * 64
        mutations.append(("weights changed at zero learning rate", record, data))

        record, data = changed()
        data["device_coefficient"][:] = data["device_coefficient"][0]
        mutations.append(("frozen graph coefficient", record, data))

        record, data = changed()
        data["host_coefficient"][3] = np.nextafter(
            data["host_coefficient"][3],
            np.float32(np.inf),
        )
        mutations.append(("host/device disagreement", record, data))

        record, data = changed()
        data["update_index"][4] = 3
        mutations.append(("duplicate epoch", record, data))

        record, data = changed()
        data["signed_entropy_term"] *= -1
        mutations.append(("wrong entropy sign", record, data))

        record, data = changed()
        data["entropy"][:] = 0.0
        data["signed_entropy_term"][:] = 0.0
        data["total_loss"][:] = (
            data["policy_loss"]
            + np.float32(record["vf_coef"]) * data["value_loss"]
        )
        mutations.append(("zero entropy false pass", record, data))

        record, data = changed()
        data["total_loss"][5] = np.nan
        mutations.append(("nonfinite loss", record, data))

        record, data = changed()
        del data["loss_count"]
        mutations.append(("missing raw array", record, data))

        for label, record, data in mutations:
            with self.subTest(label=label), self.assertRaises(
                self.q.QualificationError
            ):
                validator(
                    record,
                    data,
                    expected_kind=kind,
                    expected_schedule=expected_schedule,
                )

    def test_driver_retains_raw_entropy_artifacts_and_owns_the_only_gate(self):
        source = RUNNER.read_text(encoding="utf-8")
        worker = source[
            source.index("def _run_worker("):
            source.index("def _require_same_identity(")
        ]
        measurement = source[
            source.index("def _measure_entropy_schedule_cell("):
            source.index("def run_cell(")
        ]
        driver = source[
            source.index("def run_qualification("):
            source.index("def add_common_arguments(")
        ]
        for fragment in (
            "ENTROPY_SCHEDULE_CELL_KINDS",
            "validate_entropy_schedule_cell_evidence(",
            "validate_entropy_gradient_cell_evidence(",
            '"entropy_schedule_parity"',
            '"qualification_only": True',
            '"record_bytes": record["record_bytes"]',
            '"record_sha256": record["record_sha256"]',
            '"artifact_bytes": record.get("artifact_bytes")',
            '"artifact_sha256": record.get("artifact_sha256")',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, driver)
        self.assertIn(
            "ENTROPY_SCHEDULE_CELL_KINDS",
            worker,
        )
        self.assertIn(
            "worker-authored entropy verdict",
            worker,
        )
        self.assertIn(
            '"qualification_only": True',
            driver,
        )
        for fragment in (
            '"enable_entropy_gradient_qualification"',
            '"qualification_entropy_gradient_state"',
            "ENTROPY_OVERRUN_STATE_SURFACE_BINDING",
            "_decode_entropy_overrun_state(",
            "captured_arrays=overrun_state_arrays",
            'boundary="before"',
            'boundary="after"',
            "ENTROPY_OVERRUN_ARRAY_FIELDS",
            '"native_state"',
            '"Torch entropy cell seed"',
            "torch.manual_seed(cell_seed)",
            'record["torch_manual_seed"] = cell_seed',
        ):
            with self.subTest(measurement_fragment=fragment):
                self.assertIn(fragment, measurement)
        self.assertLess(
            measurement.index("torch.manual_seed(cell_seed)"),
            measurement.index("PuffeRL.create_pufferl("),
            "Torch RNG must be seeded before policy construction so the "
            "enabled/disabled subprocess cells share identical baselines",
        )
        self.assertIn(
            'expected_entropy_keys.add("torch_manual_seed")',
            worker,
        )
        self.assertIn(
            "Torch manual seed differs",
            worker,
        )
        self.assertEqual(
            driver.count("validate_entropy_gradient_pair("),
            3,
        )
        self.assertEqual(
            driver.count(
                "validate_entropy_native_mode_gradient_parity("
            ),
            1,
        )


class QualificationPatchContractTests(unittest.TestCase):
    """The native patch exposes bounded evidence and explicit tail consumption."""

    def test_native_constructor_supports_graph_entropy_annealing_after_repair(self):
        runner = load_runner()
        patch = PATCH.read_text(encoding="utf-8")
        guard = (
            "if (hypers.cudagraphs >= 0 && hypers.anneal_ent_coef)"
        )
        stale_message = (
            "CUDA graph training with entropy annealing is disabled until "
            "the runtime coefficient is device-backed and qualified"
        )
        self.assertNotIn(guard, patch)
        self.assertNotIn(stale_message, patch)
        self.assertEqual(
            runner.validate_entropy_cell_cudagraphs(
                "entropy_native_graph_annealed",
                runner.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS,
            ),
            runner.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS,
        )
        entropy_patch = ENTROPY_SCHEDULE_PATCH.read_text(encoding="utf-8")
        for fragment in (
            "FloatTensor ent_coef;",
            "float current_ent_coef;",
            "cudaMemcpyAsync(",
            "pufferl.ppo_bufs_puf.ent_coef.data",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, entropy_patch)
        self.assertIn(
            "entropy_native_graph_annealed",
            RUNNER.read_text(encoding="utf-8"),
        )

    def test_native_patch_exposes_only_bounded_evidence_surfaces(self):
        patch = PATCH.read_text(encoding="utf-8")
        for fragment in (
            "qualification_recurrent_state",
            "qualification_snapshot",
            "qualification_entropy_gradient_state",
            "qualification_entropy_overrun_state",
            "qualification_graph_execution",
            "qualification_consume_tail",
            "QUALIFICATION_MAX_SNAPSHOT_BYTES",
            "snapshot exceeds qualification byte limit",
            'm.def("qualification_recurrent_state"',
            'm.def("qualification_snapshot"',
            'm.def("qualification_entropy_gradient_state"',
            'm.def("qualification_entropy_overrun_state"',
            'm.def("qualification_graph_execution"',
            'm.def("qualification_consume_tail"',
            "graph_launch_counts",
            "cudaError_t device_status = cudaGetDeviceCount(&device_count)",
            "device_status != cudaSuccess || device_count <= 0",
            "CUDA device discovery failed:",
            'tensors["tail_rewards"]',
            'tensors["tail_terminals"]',
            'tensors["tail_values"]',
            'tensors["tail_valid"]',
            'tensors["advantages"]',
            'result["tail_decoder_outputs"]',
        ):
            self.assertIn(fragment, patch)
        self.assertIn(
            '-    assert(device_count > 0 && "CUDA is not available");', patch
        )
        for forbidden in (
            "set_weights_ptr", "set_observations", "set_terminals",
            "set_rng_state", "set_actions",
        ):
            self.assertNotIn(forbidden, patch)

    def test_native_overrun_surface_maps_every_claimed_tensor_locally(self):
        patch = PATCH.read_text(encoding="utf-8")
        start = patch.index(
            "+py::dict qualification_entropy_overrun_state("
        )
        end = patch.index(
            "+py::dict qualification_snapshot(",
            start,
        )
        body = patch[start:end]
        mappings = {
            "device_entropy_coefficient": (
                "pufferl.ppo_bufs_puf.ent_coef"
            ),
            "loss_accumulator": "pufferl.losses_puf",
            "scalar_loss": "pufferl.ppo_bufs_puf.loss_output",
            "master_weights": "pufferl.master_weights",
            "optimizer_momentum": "pufferl.muon.mb_puf",
            "optimizer_learning_rate": "pufferl.muon.lr_puf",
            "optimizer_learning_rate_derived": (
                "pufferl.muon.lr_derived_puf"
            ),
        }
        for name, source in mappings.items():
            with self.subTest(tensor=name):
                assignment = f'tensors["{name}"]'
                self.assertEqual(body.count(assignment), 1)
                at = body.index(assignment)
                local = body[at : at + 300]
                self.assertIn(
                    f'"{name}"',
                    local,
                )
                self.assertIn(source, local)

    def test_policy_weight_surface_is_bounded_fp32_and_read_only(self):
        patch = PATCH.read_text(encoding="utf-8")
        start = patch.index("+py::dict qualification_policy_weights(")
        end = patch.index(
            "+py::dict qualification_precision_tensor(",
            start,
        )
        body = patch[start:end]
        for fragment in (
            "QUALIFICATION_MAX_SNAPSHOT_BYTES = 64ULL << 20",
            "if (USE_BF16)",
            "requires fp32",
            "max_bytes > QUALIFICATION_MAX_SNAPSHOT_BYTES",
            "cudaDeviceSynchronize()",
            "cudaMemcpyDeviceToHost",
            "decoder range exceeds the master bank",
            "value row exceeds the master bank",
            'result["slice_size"]',
            'result["decoder_offset"]',
            'result["value_row_offset"]',
            'result["weights"] = py::bytes',
            'm.def("qualification_policy_weights"',
            'entry["active_min"]',
            'entry["active_max"]',
        ):
            self.assertIn(fragment, patch if fragment.startswith(
                ("QUALIFICATION_", 'm.def', 'entry["active_')
            ) else body)
        for forbidden in (
            "cudaMemcpyHostToDevice",
            "cudaMemset",
            "puf_zero",
            "fopen",
            "ofstream",
            "load_frozen_bank",
            "load_weights",
            "set_weights",
        ):
            self.assertNotIn(forbidden, body)
        for mutation in (r"master->data\s*=(?!=)", r"params->data\s*=(?!=)"):
            self.assertNotRegex(body, mutation)

    def test_graph_off_and_graph_on_cells_both_use_normal_native_close(self):
        source = RUNNER.read_text(encoding="utf-8")
        body = source[
            source.index("def run_cell("):
            source.index("# ---------------------------------------- isolated strict-stage")
        ]
        finally_body = body[body.index("    finally:"):]
        self.assertIn("if pufferl is not None:", finally_body)
        self.assertIn("_C.close(pufferl)", finally_body)
        self.assertNotIn('config["cudagraphs"]', finally_body)
        self.assertNotIn("process teardown", finally_body)

    def test_state_report_covers_primary_and_every_frozen_bank_buffer(self):
        patch = PATCH.read_text(encoding="utf-8")
        for fragment in (
            "1 + pufferl.num_frozen_banks",
            "pufferl.frozen_banks[bank - 1].buffer_states",
            "pufferl.hypers.num_buffers",
            'entry["nonzero"]',
            'entry["nonfinite"]',
            'entry["max_abs"]',
            'entry["active_nonzero"]',
            'entry["active_nonfinite"]',
            'entry["active_max_abs"]',
            "cudaStreamSynchronize(pufferl.default_stream)",
        ):
            self.assertIn(fragment, patch)

    def test_state_nonfinite_diagnostics_are_strict_json_finite_sentinels(self):
        patch = PATCH.read_text(encoding="utf-8")
        start = patch.index("+py::dict qualification_state_entry(")
        end = patch.index("+py::dict qualification_recurrent_state(", start)
        body = patch[start:end]
        self.assertIn("std::isfinite(value)", body)
        self.assertRegex(
            body,
            r"if\s*\(nonfinite\s*!=\s*0\)\s*"
            r"(?:\{\s*)?max_abs\s*=\s*0\.0f;",
        )
        self.assertRegex(
            body,
            r"if\s*\(active_nonfinite\s*!=\s*0\)\s*\{"
            r"[^}]*active_max_abs\s*=\s*0\.0f;"
            r"[^}]*active_min\s*=\s*0\.0f;"
            r"[^}]*active_max\s*=\s*0\.0f;",
        )

    def test_ratio_report_exposes_selected_rows_and_real_recomputed_tensor(self):
        patch = PATCH.read_text(encoding="utf-8")
        self.assertIn("pufferl.train_buf.mb_ratio", patch)
        self.assertIn("pufferl.prio_bufs.idx", patch)
        self.assertNotIn("from_float(1.0f), numel(pufferl.train_buf.mb_ratio", patch)

    def test_priority_patch_masks_frozen_rows_even_at_zero_alpha(self):
        patch = PRIO_PATCH.read_text(encoding="utf-8")
        for fragment in (
            "t % agents_per_buffer < primary_per_buffer",
            ": 0.0f",
            "eligible_agents",
            "bufs.mb_prio.data, eligible_agents",
            "last_eligible",
            "i == last_eligible ? 1.0f",
            "invalid prioritized replay row layout",
        ):
            self.assertIn(fragment, patch)
        # Zero advantage raised to the zero power has unit weight, so the ratio
        # cell has to run at prio_alpha=0 with a real frozen bank present.
        runner = RUNNER.read_text(encoding="utf-8")
        self.assertIn('"prio_alpha": 0.0', runner)
        self.assertIn("frozen_banks=1", runner)
        self.assertIn("total_agents=8", runner)
        self.assertIn("num_buffers=2", runner)
        self.assertIn('"PPO selected a frozen-bank row"', runner)

    def test_decoder_snapshot_is_limited_to_recorded_active_rows(self):
        patch = PATCH.read_text(encoding="utf-8")
        self.assertIn("active_output.shape[0] = active_rows", patch)
        self.assertIn('entry["active_rows"] = active_rows', patch)

    def test_strict_config_patch_has_two_helpers_and_three_constructor_calls(self):
        patch = STRICT_CONFIG_PATCH.read_text(encoding="utf-8")
        self.assertEqual(
            re.findall(r"^diff --git a/(\S+) b/\1$", patch, re.MULTILINE),
            ["build.sh", "src/bindings.cu", "src/bindings_cpu.cpp"],
        )
        self.assertEqual(
            patch.count(
                "static py::dict bloodbowl_normalize_and_preflight_env("
                "py::dict source)"
            ),
            2,
        )
        self.assertEqual(
            patch.count(
                "env_kwargs = "
                "bloodbowl_normalize_and_preflight_env(env_kwargs);"
            ),
            3,
        )
        self.assertEqual(
            patch.count('m.attr("environment_config_schema")'),
            2,
        )
        self.assertEqual(
            patch.count('m.attr("strict_env_config_testing") = true;'),
            2,
        )
        self.assertEqual(
            patch.count('m.attr("strict_env_config_testing") = false;'),
            2,
        )
        for marker in (
            "#define PUFFER_HAS_STRICT_ENV_CONFIG 1",
            "PUFFER_STRICT_ENV_CONFIG=1",
            "PUFFER_STRICT_ENV_CONFIG_TESTING=1",
            "#define create_static_vec(...)",
            "#define cudaGetDeviceCount(...)",
            "#define create_pufferl_impl(...)",
            "my_environment_config_preflight(",
            "PyGILState_Check()",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, patch)

    def test_cpu_and_cuda_strict_normalizer_bodies_are_byte_identical(self):
        patch = STRICT_CONFIG_PATCH.read_text(encoding="utf-8")
        needle = (
            "static py::dict bloodbowl_normalize_and_preflight_env("
            "py::dict source) {"
        )

        def added_helper(relative):
            marker = f"diff --git a/{relative} b/{relative}\n"
            section = patch.split(marker, 1)[1].split("\ndiff --git ", 1)[0]
            added = "\n".join(
                line[1:]
                for line in section.splitlines()
                if line.startswith("+") and not line.startswith("+++")
            )
            start = added.index(needle)
            helper = added[start:]
            depth = 0
            lines = []
            for line in helper.splitlines():
                lines.append(line)
                depth += line.count("{") - line.count("}")
                if depth == 0:
                    break
            self.assertGreater(len(lines), 100)
            return "\n".join(lines)

        self.assertEqual(
            added_helper("src/bindings.cu"),
            added_helper("src/bindings_cpu.cpp"),
            "CPU and CUDA must execute byte-identical normalization/preflight",
        )

    def test_strict_stage_driver_locks_isolation_build_and_worker_order(self):
        source = RUNNER.read_text(encoding="utf-8")
        prepare = source[
            source.index("def _prepare_strict_stage_isolation("):
            source.index("def _run_strict_stage_command(")
        ]
        for fragment in (
            "root.relative_to(REPO_ROOT)",
            '\"rev-parse\", \"HEAD\"',
            "PINNED_PUFFER_COMMIT",
            '\"status\", \"--porcelain=v1\", \"--untracked-files=all\"',
            'root / \"build\"',
            'root / \"ocean/bloodbowl\"',
            "_strict_stage_module_artifacts(root)",
            "strict-stage evidence output must be outside",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, prepare)

        driver = source[
            source.index("def run_strict_stage_order("):
            source.index("# ------------------------------------------------------------------------ driver")
        ]
        prepared_at = driver.index("_prepare_strict_stage_isolation(")
        receipt_at = driver.index("write_bounded_json_atomic(receipt_path")
        installer_at = driver.index("tools/install_puffer_env.sh")
        build_at = driver.index('[\"./build.sh\", \"bloodbowl\"]')
        worker_at = driver.index('\"strict-stage-worker\"')
        validate_at = driver.index("validate_strict_stage_evidence(")
        self.assertLess(prepared_at, receipt_at)
        self.assertLess(receipt_at, installer_at)
        self.assertLess(installer_at, build_at)
        self.assertLess(build_at, worker_at)
        self.assertLess(worker_at, validate_at)
        self.assertEqual(
            driver.count("environment=test_build_environment"),
            3,
            "installer, build, and worker must share the prepared environment",
        )

        child_environment = source[
            source.index("def _strict_stage_child_environment("):
            source.index("def _strict_stage_interpreter_probe(")
        ]
        for fragment in (
            'environment["PUFFER_STRICT_ENV_CONFIG_TESTING"] = "1"',
            'environment["VIRTUAL_ENV"] = str(venv)',
            '"BASH",',
            '"PYTHON",',
            '"SHELLOPTS",',
            '"ENV",',
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, child_environment)

        worker = source[
            source.index("def run_strict_stage_worker("):
            source.index("def run_strict_stage_order(")
        ]
        test_identity_at = worker.index("validate_strict_stage_module_identity(")
        production_reject_at = worker.index("validate_module_identity(identity)")
        exercise_at = worker.index("_exercise_strict_cuda_stage_order(")
        self.assertLess(test_identity_at, production_reject_at)
        self.assertLess(production_reject_at, exercise_at)
        signature = source[
            source.index("def validate_module_identity("):
            source.index(") -> dict[str, Any]:", source.index(
                "def validate_module_identity("
            ))
        ]
        self.assertIn("strict_env_config_testing: bool = False", signature)

    def test_installer_routes_every_python_call_through_one_owned_variable(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        assignment = (
            'INSTALL_PYTHON="${PUFFER_INSTALL_PYTHON:-python3}"'
        )
        self.assertEqual(installer.count(assignment), 1)
        # Seven invocations plus the nonempty/command-availability checks.
        self.assertEqual(installer.count('"$INSTALL_PYTHON"'), 9)
        self.assertEqual(installer.count("python3"), 1)
        for fragment in (
            (
                'if "$INSTALL_PYTHON" -B -I -S \\\n'
                '            '
                '"$ROOT/tools/state_bank_contract.py" validate-request'
            ),
            (
                '"$INSTALL_PYTHON" -B -I -S '
                '"$ROOT/tools/state_bank_contract.py" \\\n'
                "        environment-source-sha256"
            ),
            (
                '"$INSTALL_PYTHON" -B -I -S '
                '"$ROOT/tools/puffer_source_manifest.py"'
            ),
            (
                'if ! "$INSTALL_PYTHON" -B -I -S \\\n'
                '            '
                '"$ROOT/tools/state_bank_contract.py" check-no-bank'
            ),
            (
                '"$INSTALL_PYTHON" -B -I -S \\\n'
                '            '
                '"$ROOT/tools/state_bank_contract.py" show-installed'
            ),
            ('"$INSTALL_PYTHON" -B -I -S -c',),
            (
                '"$INSTALL_PYTHON" -B -I -S \\\n'
                '    '
                '"$ROOT/tools/state_bank_contract.py" install-no-bank'
            ),
        ):
            expected = fragment[0] if isinstance(fragment, tuple) else fragment
            with self.subTest(fragment=expected):
                self.assertIn(expected, installer)

    def test_installer_applies_patch_last_and_hashes_compiled_surfaces(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("puffer_recurrent_cuda_qualification.patch", installer)
        self.assertIn("training/selfplay_league.patch", installer)
        recurrent_at = installer.index(
            'echo "applied:   recurrent evaluation-state boundaries'
        )
        frozen_at = installer.index(
            'echo "applied:   exact frozen-row exclusion'
        )
        qualification_at = installer.index(
            'echo "applied:   bounded recurrent CUDA qualification evidence'
        )
        strict_at = installer.index(
            'echo "applied:   strict Blood Bowl environment boundary'
        )
        digest_at = installer.index('EXACT_BACKEND_HASH="$(exact_backend_hash)"')
        league_at = installer.index(
            'echo "applied:   training/selfplay_league.patch ->'
        )
        self.assertLess(recurrent_at, qualification_at)
        self.assertLess(recurrent_at, frozen_at)
        self.assertLess(frozen_at, qualification_at)
        self.assertLess(league_at, digest_at)
        self.assertLess(qualification_at, digest_at)
        self.assertLess(qualification_at, strict_at)
        self.assertLess(strict_at, digest_at)
        backend_hash = installer[
            installer.index("exact_backend_hash()"):
            installer.index('if [ "$MODE" = "check" ]')
        ]
        self.assertIn("tools/puffer_source_manifest.py", backend_hash)
        self.assertIn("COMPILED_BACKEND_LEDGER", backend_hash)
        expected_source_count = len(
            COMPILED_BACKEND_LEDGER.read_text(
                encoding="utf-8"
            ).splitlines()
        )
        self.assertIn(
            f"--expected-count {expected_source_count}",
            backend_hash,
        )
        self.assertIn("--require-native-extension-closure", backend_hash)
        self.assertIn("strict_environment_config_sources_valid()", installer)
        self.assertIn('"$STRICT_ENV_CONFIG_PATCH"', installer)
        self.assertEqual(
            COMPILED_BACKEND_LEDGER.read_text(encoding="utf-8").splitlines(),
            list(load_runner().BACKEND_SOURCE_FILES),
        )
        self.assertIn(
            'git -C "$PUFFER" apply --reverse --check --no-index',
            installer,
        )
        league_patch = LEAGUE_PATCH.read_text(encoding="utf-8")
        self.assertIn("Patch copy: training/selfplay_league.patch", league_patch)
        self.assertIn("league_preseed", league_patch)
        for marker in (
            "eligible_agents", "qualification_recurrent_state",
            "qualification_policy_weights", "qualification_snapshot",
            "qualification_entropy_gradient_state",
            "qualification_graph_execution", "qualification_consume_tail",
            "apply --reverse --check --no-index",
            "Patch copy: training/selfplay_league.patch",
        ):
            self.assertIn(marker, installer)

    def test_real_installer_selfplay_state_machine_is_fail_closed(self):
        upstream_selfplay = textwrap.dedent('''\
            """Pool storage is disk-only (paths held in memory; weights only on GPU when
            loaded as the frozen bank). Stride-eviction preserves temporal coverage when
            the pool exceeds its cap.
            """
            import os

            import numpy as np
            ''') + ("# fixture padding\n" * 150) + textwrap.dedent('''\
            def setup(pufferl, backend, args, run_id):
                sp = args['selfplay']
                num_banks = 2
                perm = []
                tags = []
                backend.set_agent_perm(pufferl, perm)
                backend.set_env_tags(pufferl, tags)

                pool_dir = os.path.join(args['checkpoint_dir'], args['env_name'], run_id, 'pool')
                os.makedirs(pool_dir, exist_ok=True)
                bootstrap_path = os.path.join(pool_dir, f'{pufferl.global_step:016d}.bin')
                backend.save_weights(pufferl, bootstrap_path)
                # Load bootstrap into every bank — they'll diverge as each bank's swap fires.
                for b in range(num_banks):
                    backend.load_frozen_bank(pufferl, b, bootstrap_path)

                elo_init = float(sp.get('elo_init', 0.0))
                elo_k    = float(sp.get('elo_k',    16.0))
                banks_state = []
                for b in range(num_banks):
                    banks_state.append({
                        'cur_opp_path': bootstrap_path,
                        'cur_opp_elo': elo_init,
                        'hist_score': 0.0,
                        'hist_n': 0.0,
                    })

                # state fixture padding 1
                # state fixture padding 2
                # state fixture padding 3
                # state fixture padding 4
                # state fixture padding 5
                # state fixture padding 6
                # state fixture padding 7
                # state fixture padding 8
                # state fixture padding 9

                return {
                    'pool_dir': pool_dir,
                    'pool': [{'path': bootstrap_path, 'elo': elo_init}],
                    'rng': rng,
                    'max_size': int(sp['max_size']),
                    'min_games': int(sp['min_games']),
                }
            ''')
        dashboard_markers = "\n".join((
            "if i == 160:",
            "PUFFER_ENV_JSON",
            "'_puffer_schema': 2",
            "'_puffer_final_reprint'",
            "'_puffer_eval_episodes_completed'",
            "phase_eval=phase_eval, phase_epoch=epoch",
            "metrics.setdefault",
        ))
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary) / "PufferLib"
            (puffer / "pufferlib").mkdir(parents=True)
            (puffer / "src").mkdir()
            (puffer / "config").mkdir()
            # The real installer now owns one exact patch against the pinned
            # standalone FLAGS block. Keep that upstream surface in this
            # deliberately partial fixture so the test still reaches the
            # selfplay state machine it is designed to exercise.
            (puffer / "build.sh").write_text(textwrap.dedent("""\
                if [ "$MODE" = "local" ] || [ "$MODE" = "fast" ]; then
                    FLAGS=(
                        "${INCLUDES[@]}"
                        "$SRC_DIR/$ENV.c" $EXTRA_SRC -o "$OUTPUT_NAME"
                        "${LINK_ARCHIVES[@]}"
                        "${EXTRA_LDFLAGS[@]}"
            """), encoding="utf-8")
            (puffer / "pufferlib/pufferl.py").write_text(
                dashboard_markers, encoding="utf-8"
            )
            (puffer / "pufferlib/torch_pufferl.py").write_text(
                "historical full-pickle state dicts\nsample_joint_logits\n",
                encoding="utf-8",
            )
            selfplay = puffer / "pufferlib/selfplay.py"
            selfplay.write_text(upstream_selfplay, encoding="utf-8")
            (puffer / "pufferlib/sweep.py").write_text(
                "match_enemy_model_path\n", encoding="utf-8"
            )
            # The installer now applies one exact capacity patch before the
            # selfplay patch. Preserve every reachable upstream log-allocation
            # surface in this deliberately partial fixture so installation
            # reaches the selfplay state machine this test owns.
            for relative, contents in {
                "src/vecenv.h": textwrap.dedent("""\
                    static inline DictItem* dict_get(Dict* dict, const char* key) {
                        return NULL;
                    }

                    static inline void dict_set(Dict* dict, const char* key, double value) {
                        assert(dict->size < dict->capacity);
                        DictItem* item = dict_get_unsafe(dict, key);
                        if (item != NULL) {
                            item->value = value;
                            return;
                        }
                        dict->items[dict->size].key = key;
                        dict->items[dict->size].value = value;
                        dict->size++;
                    }
                    joint_action_offsets
                """),
                "src/pufferlib.cu": textwrap.dedent("""\
                    Dict* log_environments_impl(PuffeRL& pufferl) {
                        // Capacity raised from 32 to 64 to accommodate chess's per-bank
                        // hist_score_bank_<b> / hist_n_bank_<b> entries (16 keys for 8 banks).
                        Dict* out = create_dict(64);
                        static_vec_log(pufferl.vec, out);
                        return out;
                    }
                    fixture stops after selfplay
                """),
                "src/bindings.cu": textwrap.dedent("""\
                    pybind11::dict puf_eval_log(pybind11::object pufferl_obj) {
                        pybind11::dict env_dict;
                        // Capacity 64 to fit chess's per-bank hist_score_bank/hist_n_bank entries
                        // (16 keys across 8 banks) on top of base env-log fields.
                        Dict* env_out = create_dict(64);
                        static_vec_eval_log(pufferl.vec, env_out);
                        for (int i = 0; i < env_out->size; i++) {
                            env_dict[env_out->items[i].key] = env_out->items[i].value;
                        }
                    }

                    void cpu_vec_step_py(VecEnv& ve, long long actions_ptr) {
                    }

                    py::dict vec_log(VecEnv& ve) {
                        Dict* out = create_dict(32);
                        static_vec_log(ve.vec, out);
                        py::dict result;
                        for (int i = 0; i < out->size; i++) {
                    }
                """),
                "src/bindings_cpu.cpp": textwrap.dedent("""\
                    static void cpu_vec_step_py(VecEnv& ve, long long actions_ptr) {
                    }

                    static py::dict vec_log(VecEnv& ve) {
                        Dict* out = create_dict(32);
                        static_vec_log(ve.vec, out);
                        py::dict result;
                        for (int i = 0; i < out->size; i++)
                    }
                """),
                "src/kernels.cu": "fixture\n",
            }.items():
                (puffer / relative).write_text(contents, encoding="utf-8")

            def install(*arguments: str) -> subprocess.CompletedProcess[str]:
                real_git = shutil.which("git")
                self.assertIsNotNone(real_git)
                physical_puffer = puffer.resolve()
                shim_dir = pathlib.Path(temporary) / "git-shim"
                shim_dir.mkdir(exist_ok=True)
                shim = shim_dir / "git"
                shim.write_text(textwrap.dedent(f"""\
                    #!/bin/sh
                    if [ "$1" = "-C" ] && [ "$2" = "{physical_puffer}" ] && \
                       [ "$3" = "rev-parse" ]; then
                        if [ "$4" = "--show-toplevel" ]; then
                            printf '%s\\n' "{physical_puffer}"
                            exit 0
                        fi
                        if [ "$4" = "--verify" ] && \
                           [ "$5" = "HEAD^{{commit}}" ]; then
                            printf '%s\\n' "{load_runner().PINNED_PUFFER_COMMIT}"
                            exit 0
                        fi
                    fi
                    exec "{real_git}" "$@"
                """), encoding="utf-8")
                shim.chmod(0o755)
                environment = dict(os.environ)
                environment["PATH"] = (
                    str(shim_dir) + os.pathsep + environment.get("PATH", "")
                )
                return subprocess.run(
                    [str(INSTALLER), *arguments, str(puffer)],
                    cwd=ROOT,
                    text=True,
                    capture_output=True,
                    timeout=60,
                    env=environment,
                )

            applicable = subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--check",
                    "--no-index", str(LEAGUE_PATCH),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(applicable.returncode, 0, applicable.stderr)
            first = install()
            self.assertNotEqual(first.returncode, 0)
            self.assertIn(
                "applied:   training/selfplay_league.patch",
                first.stdout,
                first.stderr,
            )
            self.assertIn(
                "exact joint-action patch is neither applicable nor installed",
                first.stderr,
            )
            patched = selfplay.read_bytes()
            self.assertIn(b"Patch copy: training/selfplay_league.patch", patched)
            subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--reverse", "--check",
                    "--no-index", str(LEAGUE_PATCH),
                ],
                check=True,
                capture_output=True,
            )

            second = install()
            self.assertNotEqual(second.returncode, 0)
            self.assertNotIn("applied:   training/selfplay_league.patch", second.stdout)
            self.assertNotIn("selfplay league patch", second.stderr)
            self.assertEqual(selfplay.read_bytes(), patched)

            # This deliberately partial fixture stops installation before the
            # normal authority-last no-bank publisher. Seed that exact
            # prerequisite explicitly so --check can continue to the
            # selfplay/exact-action marker ordering this test owns.
            no_bank = subprocess.run(
                [
                    "python3",
                    str(ROOT / "tools/state_bank_contract.py"),
                    "install-no-bank",
                    "--puffer-root", str(puffer),
                    "--exact-action-source-hash", "0" * 64,
                    "--environment-source-hash", "1" * 64,
                    "--observation-abi", "obs-v6",
                    "--observation-version", "6",
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                timeout=60,
            )
            self.assertEqual(no_bank.returncode, 0, no_bank.stderr)

            checked = install("--check")
            self.assertNotEqual(checked.returncode, 0)
            self.assertNotIn("selfplay league patch", checked.stderr)
            self.assertIn("exact-action backend marker missing", checked.stderr)

            subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--reverse",
                    "--no-index", str(LEAGUE_PATCH),
                ],
                check=True,
                capture_output=True,
            )
            self.assertEqual(selfplay.read_text(encoding="utf-8"), upstream_selfplay)
            unapplied = install("--check")
            self.assertNotEqual(unapplied.returncode, 0)
            self.assertIn("installed selfplay league patch is missing or stale", unapplied.stderr)

            subprocess.run(
                [
                    "git", "-C", str(puffer), "apply", "--no-index",
                    str(LEAGUE_PATCH),
                ],
                check=True,
                capture_output=True,
            )
            partial = selfplay.read_text(encoding="utf-8").replace(
                "        seed_paths = [bootstrap_path] * num_banks\n", "", 1
            )
            self.assertIn("Patch copy: training/selfplay_league.patch", partial)
            selfplay.write_text(partial, encoding="utf-8")
            stale = install("--check")
            self.assertNotEqual(stale.returncode, 0)
            self.assertIn("installed selfplay league patch is missing or stale", stale.stderr)

            selfplay.unlink()
            missing = install("--check")
            self.assertNotEqual(missing.returncode, 0)
            self.assertIn("installed selfplay league patch is missing or stale", missing.stderr)


if __name__ == "__main__":
    unittest.main()
