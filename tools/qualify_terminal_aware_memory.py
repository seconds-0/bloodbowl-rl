#!/usr/bin/env python3
"""Qualification-only driver for terminal-aware recurrent PPO state.

This runs only against a native module that exposes the explicitly named
qualification hooks below.  The hooks are not part of live training control.
Each graph mode runs in a fresh subprocess so CUDA initialization and capture
start clean.  The resulting artifacts prove fixture behavior, not match play.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping

import numpy as np

try:
    import qualify_recurrent_cuda as base
except ModuleNotFoundError:
    from tools import qualify_recurrent_cuda as base


SCHEMA_VERSION = 1
CONTRACT = "terminal-aware-tbptt-v1"
HOOKS = (
    "qualification_set_memory_fixture",
    "qualification_run_rollout_step",
    "qualification_set_terminals",
    "qualification_run_tail",
    "qualification_set_segment_initial_row",
    "qualification_memory_snapshot",
    "qualification_terminal_mingru_derivatives",
    "qualification_graph_execution",
)
REQUIRED_ARRAYS = {
    "initial_states": 3,              # [layers, physical rows, hidden]
    "observation_terminals": 2,       # [time, physical rows]
    "behavior_state_in": 4,           # [time, layers, physical rows, hidden]
    "behavior_state_out": 4,
    "persistent_state_before_tail": 3,
    "persistent_state_after_tail": 3,
    "tail_state_input": 3,
    "tail_terminals": 1,
    "tail_values": 1,
    "selected_rows": 1,
    "mb_initial_states": 3,           # [layers, selected segments, hidden]
    "mb_terminals": 2,                # [selected segments, time]
    "mb_ratio": 2,
}
FLOAT32_ARRAYS = frozenset(REQUIRED_ARRAYS) - {"selected_rows"}
EXACT_ZERO_ATOL = 0.0


class MemoryQualificationError(base.QualificationError):
    pass


def _array(value: Any, name: str, ndim: int) -> np.ndarray:
    if not isinstance(value, np.ndarray):
        raise MemoryQualificationError(f"{name} must be an ndarray")
    if value.ndim != ndim:
        raise MemoryQualificationError(
            f"{name} rank {value.ndim} differs from required rank {ndim}")
    expected = np.int32 if name == "selected_rows" else np.float32
    if value.dtype != np.dtype(expected):
        raise MemoryQualificationError(f"{name} must be {np.dtype(expected)}")
    if name != "selected_rows" and not np.isfinite(value).all():
        raise MemoryQualificationError(f"{name} contains non-finite values")
    if any(size <= 0 for size in value.shape):
        raise MemoryQualificationError(f"{name} has an empty dimension")
    return value


def validate_snapshot_schema(
    arrays: Mapping[str, np.ndarray], metadata: Mapping[str, Any]
) -> dict[str, int]:
    """Validate dimensions, physical ownership, and exact mask alignment."""
    missing = sorted(set(REQUIRED_ARRAYS) - set(arrays))
    if missing:
        raise MemoryQualificationError(f"memory snapshot fields missing: {missing}")
    parsed = {k: _array(arrays[k], k, n) for k, n in REQUIRED_ARRAYS.items()}
    layers = base._int(metadata.get("layers"), "memory layers", minimum=1)
    agents = base._int(metadata.get("total_agents"), "memory agents", minimum=1)
    hidden = base._int(metadata.get("hidden"), "memory hidden", minimum=1)
    horizon = base._int(metadata.get("horizon"), "memory horizon", minimum=1)
    segments = parsed["selected_rows"].size
    expected = {
        "initial_states": (layers, agents, hidden),
        "observation_terminals": (horizon, agents),
        "behavior_state_in": (horizon, layers, agents, hidden),
        "behavior_state_out": (horizon, layers, agents, hidden),
        "persistent_state_before_tail": (layers, agents, hidden),
        "persistent_state_after_tail": (layers, agents, hidden),
        "tail_state_input": (layers, agents, hidden),
        "tail_terminals": (agents,),
        "tail_values": (agents,),
        "selected_rows": (segments,),
        "mb_initial_states": (layers, segments, hidden),
        "mb_terminals": (segments, horizon),
        "mb_ratio": (segments, horizon),
    }
    for name, shape in expected.items():
        if parsed[name].shape != shape:
            raise MemoryQualificationError(
                f"{name} shape {parsed[name].shape} differs from {shape}")
    rows = parsed["selected_rows"]
    if np.any(rows < 0) or np.any(rows >= agents):
        raise MemoryQualificationError("selected_rows contains an out-of-range row")
    if np.any((parsed["observation_terminals"] != 0)
              & (parsed["observation_terminals"] != 1)):
        raise MemoryQualificationError("observation terminals are not binary")
    if np.any((parsed["tail_terminals"] != 0) & (parsed["tail_terminals"] != 1)):
        raise MemoryQualificationError("tail terminals are not binary")
    return {"layers": layers, "total_agents": agents, "hidden": hidden,
            "horizon": horizon, "segments": segments}


def validate_terminal_forward(arrays: Mapping[str, np.ndarray]) -> dict[str, Any]:
    """Terminal at slot t means exact-zero effective state before obs[t]."""
    terminals = arrays["observation_terminals"]
    state_in = arrays["behavior_state_in"]
    reset_cells = 0
    continuity_cells = 0
    for t in range(terminals.shape[0]):
        for row in range(terminals.shape[1]):
            if terminals[t, row] == 1:
                if np.count_nonzero(state_in[t, :, row, :]) != 0:
                    raise MemoryQualificationError(
                        f"terminal row {row} at observation slot {t} was not reset")
                reset_cells += 1
            elif t:
                if not np.array_equal(
                    state_in[t, :, row, :], arrays["behavior_state_out"][t-1, :, row, :]
                ):
                    raise MemoryQualificationError(
                        f"nonterminal row {row} lost carry before slot {t}")
                continuity_cells += 1
    if reset_cells == 0 or continuity_cells == 0:
        raise MemoryQualificationError(
            "fixture must exercise terminal reset and nonterminal carry")
    return {"terminal_reset_cells": reset_cells,
            "nonterminal_continuity_cells": continuity_cells}


def validate_tail_nonmutation(arrays: Mapping[str, np.ndarray]) -> dict[str, Any]:
    before = arrays["persistent_state_before_tail"]
    after = arrays["persistent_state_after_tail"]
    if not np.array_equal(before, after):
        raise MemoryQualificationError("tail forward mutated persistent behavior state")
    expected = before.copy()
    expected[:, arrays["tail_terminals"].astype(bool), :] = 0
    if not np.array_equal(arrays["tail_state_input"], expected):
        raise MemoryQualificationError("tail input is not terminal-masked final carry")
    if np.any(arrays["tail_values"][arrays["tail_terminals"].astype(bool)] != 0):
        raise MemoryQualificationError("terminal tail has nonzero bootstrap value")
    return {"persistent_state_byte_identical": True,
            "terminal_tail_rows": int(np.count_nonzero(arrays["tail_terminals"]))}


def validate_gather_and_ratio(
    arrays: Mapping[str, np.ndarray], metadata: Mapping[str, Any], *, atol: float,
    require_full_coverage: bool = True,
) -> dict[str, Any]:
    rows = arrays["selected_rows"]
    layout = metadata.get("state_layout")
    if not isinstance(layout, Mapping):
        raise MemoryQualificationError("state_layout metadata is missing")
    try:
        primary, frozen = base.derive_row_partition(
            layout, total_agents=arrays["initial_states"].shape[1])
    except base.QualificationError as exc:
        raise MemoryQualificationError(str(exc)) from exc
    expected_states = arrays["initial_states"][:, rows, :]
    if not np.array_equal(arrays["mb_initial_states"], expected_states):
        raise MemoryQualificationError("minibatch initial-state gather is misindexed")
    expected_terminals = arrays["observation_terminals"][:, rows].T
    if not np.array_equal(arrays["mb_terminals"], expected_terminals):
        raise MemoryQualificationError("minibatch terminal-mask gather is misindexed")
    call = {"selected_rows": rows, "ratios": arrays["mb_ratio"]}
    if require_full_coverage:
        try:
            return base.validate_ratio_calls(
                [call], primary_rows=primary, frozen_rows=frozen, atol=atol)
        except base.QualificationError as exc:
            raise MemoryQualificationError(str(exc)) from exc
    selected_set = {int(row) for row in rows.tolist()}
    if selected_set & frozen or not selected_set <= primary:
        raise MemoryQualificationError("memory trial selected a non-primary row")
    ratios = arrays["mb_ratio"]
    if not np.isfinite(ratios).all():
        raise MemoryQualificationError("memory trial ratios contain non-finite values")
    maximum = float(np.max(np.abs(ratios - np.float32(1))))
    if maximum > atol:
        raise MemoryQualificationError(
            f"memory trial ratio error {maximum} exceeds {atol}")
    return {"covered_primary_rows": sorted(selected_set),
            "ratio_elements": int(ratios.size),
            "max_abs_ratio_minus_one": maximum, "atol": atol}


def compare_graph_modes(
    eager: Mapping[str, np.ndarray], graph: Mapping[str, np.ndarray], *, atol: float
) -> dict[str, float]:
    if set(eager) != set(graph):
        raise MemoryQualificationError("graph/eager memory snapshot field sets differ")
    maxima: dict[str, float] = {}
    exact = {"selected_rows", "observation_terminals", "tail_terminals",
             "mb_terminals", "live_first_tail_terminals"}
    for name in sorted(eager):
        a, b = eager[name], graph[name]
        if not isinstance(a, np.ndarray) or not isinstance(b, np.ndarray):
            raise MemoryQualificationError(f"graph field {name} is not an ndarray")
        if a.shape != b.shape or a.dtype != b.dtype:
            raise MemoryQualificationError(f"graph field {name} shape/dtype differs")
        if name in exact:
            if not np.array_equal(a, b):
                raise MemoryQualificationError(f"graph exact field {name} differs")
            maxima[name] = 0.0
        else:
            if not np.isfinite(a).all() or not np.isfinite(b).all():
                raise MemoryQualificationError(f"graph field {name} is non-finite")
            error = float(np.max(np.abs(a.astype(np.float64)-b.astype(np.float64))))
            if error > atol:
                raise MemoryQualificationError(
                    f"graph field {name} max error {error} exceeds {atol}")
            maxima[name] = error
    return maxima


def validate_live_crosswindow_arrays(
    first_final: np.ndarray, tail_terminals: np.ndarray,
    second_initial: np.ndarray, *, primary_rows: set[int] | None = None,
) -> None:
    for name, value, rank in (("first final", first_final, 3),
                              ("tail terminals", tail_terminals, 1),
                              ("second initial", second_initial, 3)):
        if not isinstance(value, np.ndarray) or value.ndim != rank:
            raise MemoryQualificationError(f"live {name} tensor is malformed")
    if first_final.dtype != np.float32 or second_initial.dtype != np.float32:
        raise MemoryQualificationError("live recurrent states must be float32")
    if tail_terminals.dtype != np.float32 or not np.isfinite(tail_terminals).all():
        raise MemoryQualificationError("live tail terminals must be finite float32")
    if first_final.shape != second_initial.shape or first_final.shape[1] != tail_terminals.size:
        raise MemoryQualificationError("live cross-window shapes disagree")
    if np.any((tail_terminals != 0) & (tail_terminals != 1)):
        raise MemoryQualificationError("live tail terminals are not binary")
    expected = first_final.copy()
    expected[:, tail_terminals.astype(bool), :] = 0
    rows = sorted(primary_rows) if primary_rows is not None else list(range(first_final.shape[1]))
    if not rows or any(row < 0 or row >= first_final.shape[1] for row in rows):
        raise MemoryQualificationError("live primary-row selection is invalid")
    if not np.array_equal(second_initial[:, rows, :], expected[:, rows, :]):
        raise MemoryQualificationError(
            "ordinary _C.rollouts did not carry terminal-masked state across windows")


def validate_action_sensitivity(arrays: Mapping[str, np.ndarray]) -> dict[str, Any]:
    masks = arrays.get("action_mask")
    logprobs = arrays.get("logprobs")
    if (not isinstance(masks, np.ndarray) or masks.dtype != np.float32
            or masks.ndim != 3):
        raise MemoryQualificationError("action-sensitivity mask is malformed")
    if (not isinstance(logprobs, np.ndarray) or logprobs.dtype != np.float32
            or logprobs.shape != masks.shape[:2] or not np.isfinite(logprobs).all()):
        raise MemoryQualificationError("action-sensitivity log probabilities are malformed")
    enabled = np.sum(masks != 0, axis=2)
    # Three factored heads require at least three singleton choices. More than
    # three proves at least one head had a real alternative.
    multi = enabled > 3
    if not np.any(multi):
        raise MemoryQualificationError("fixture contains no multi-option action row")
    if not np.any(np.abs(logprobs[multi]) > np.float32(1e-7)):
        raise MemoryQualificationError(
            "multi-option fixture has only insensitive zero log probabilities")
    return {"multi_option_rows": int(np.count_nonzero(multi)),
            "max_abs_logprob": float(np.max(np.abs(logprobs[multi])))}


def _decode_native_snapshot(raw: Any, *, state_layout: Mapping[str, Any] | None = None
                            ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    if not isinstance(raw, Mapping):
        raise MemoryQualificationError("native memory snapshot is not an object")
    tensors = raw.get("tensors")
    metadata = raw.get("metadata", {})
    if not isinstance(tensors, Mapping) or not isinstance(metadata, Mapping):
        raise MemoryQualificationError("native memory snapshot lacks tensors")
    arrays = {str(name): base._decode_tensor(value) for name, value in tensors.items()}
    initial = arrays.get("segment_initial_states")
    obs_terms = arrays.get("rollout_observation_terminals")
    if initial is None or initial.ndim != 3 or obs_terms is None or obs_terms.ndim != 2:
        raise MemoryQualificationError("native memory snapshot core shapes are missing")
    metadata = dict(metadata)
    metadata.setdefault("layers", initial.shape[0])
    metadata.setdefault("total_agents", initial.shape[1])
    metadata.setdefault("hidden", initial.shape[2])
    metadata.setdefault("horizon", obs_terms.shape[0])
    if state_layout is not None:
        metadata["state_layout"] = dict(state_layout)
    def stitch(entries: Any, label: str) -> np.ndarray:
        if not isinstance(entries, list) or not entries:
            raise MemoryQualificationError(f"{label} entries are missing")
        decoded = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise MemoryQualificationError(f"{label} entry is malformed")
            decoded.append((base._int(entry.get("physical_row_start"), f"{label} row"),
                            base._int(entry.get("active_rows"), f"{label} active rows", minimum=1),
                            base._decode_tensor(entry.get("tensor"))))
        layers = base._int(metadata.get("layers"), "memory layers", minimum=1)
        agents = base._int(metadata.get("total_agents"), "memory agents", minimum=1)
        hidden = base._int(metadata.get("hidden"), "memory hidden", minimum=1)
        out = np.empty((layers, agents, hidden), np.float32)
        covered = np.zeros(agents, bool)
        for start, active, tensor in decoded:
            # Bank-local state tensors are [L, active_rows, H].
            if tensor.ndim != 3 or tensor.shape[0] != layers or tensor.shape[2] != hidden:
                raise MemoryQualificationError(f"{label} tensor shape is malformed")
            if active > tensor.shape[1]:
                raise MemoryQualificationError(f"{label} active rows exceed tensor")
            tensor = tensor[:, :active, :]
            stop = start + active
            if start < 0 or stop > agents or covered[start:stop].any():
                raise MemoryQualificationError(f"{label} physical rows overlap/out of range")
            out[:, start:stop] = tensor
            covered[start:stop] = True
        if not covered.all():
            raise MemoryQualificationError(f"{label} physical rows are incomplete")
        return out
    arrays["behavior_current"] = stitch(raw.get("behavior_states"), "behavior state")
    arrays["tail_input_current"] = stitch(raw.get("tail_input_states"), "tail input state")
    arrays["tail_work_current"] = stitch(raw.get("tail_work_states"), "tail work state")
    if "selected_rows" in arrays:
        # Generic precision decoders normalize to fp32; the native hook must
        # provide selected rows as an explicit JSON integer array when needed.
        arrays["selected_rows"] = np.asarray(
            raw.get("selected_rows", arrays["selected_rows"]), dtype=np.int32)
    return arrays, dict(metadata)


def decode_and_validate_derivatives(raw: Any) -> dict[str, np.ndarray]:
    if not isinstance(raw, Mapping) or raw.get("contract") != "terminal-mingru-derivatives-fp32-v1":
        raise MemoryQualificationError("terminal derivative contract is missing or wrong")
    T = base._int(raw.get("T"), "terminal derivative horizon", minimum=1)
    if raw.get("B") != 2 or raw.get("H") != 5:
        raise MemoryQualificationError("terminal derivative fixed geometry is wrong")
    tensors = raw.get("tensors")
    if not isinstance(tensors, Mapping):
        raise MemoryQualificationError("terminal derivative tensors are missing")
    arrays = {str(k): base._decode_tensor(v) for k, v in tensors.items()}
    shapes = {"combined":(2,T,15), "inputs":(2,T,5), "outputs":(2,T,5),
              "grad_outputs":(2,T,5), "grad_inputs":(2,T,5),
              "initial_state":(2,5), "final_state":(2,5),
              "grad_initial_state":(2,5), "terminals":(2,T),
              "grad_combined":(2,T,15)}
    missing = sorted(set(shapes)-set(arrays))
    if missing:
        raise MemoryQualificationError(f"terminal derivative tensors missing: {missing}")
    for name, shape in shapes.items():
        value = _array(arrays[name], name, len(shape))
        if value.shape != shape:
            raise MemoryQualificationError(f"terminal derivative {name} shape differs")
    terminals = arrays["terminals"]
    if np.any((terminals != 0) & (terminals != 1)):
        raise MemoryQualificationError("terminal derivative mask is not binary")
    for row in range(2):
        if terminals[row, 0] == 1 and np.count_nonzero(arrays["grad_initial_state"][row]):
            raise MemoryQualificationError(
                "terminal at timestep zero leaked gradient to initial state")
    return arrays


def _config(graphs: int, seed: int) -> dict[str, Any]:
    return base.qualification_args(
        cudagraphs=graphs, seed=seed, total_agents=8, num_buffers=2,
        num_threads=2, horizon=4, max_decisions=32, hidden_size=64,
        # frozen_bank_pct applies to each bank. With four rows per buffer,
        # 0.25 yields primary=2, frozen-A=1, frozen-B=1. A value of 0.5 with
        # two banks consumes all four rows and makes primary tail allocation
        # fail because primary_slice is zero.
        num_layers=2, frozen_banks=2, frozen_bank_pct=0.25,
        learning_rate=0.0, minibatch_size=16,
    )


def run_fixture_trial(
    _C: Any, pufferl: Any, state_values: np.ndarray, terminals: np.ndarray,
    tail_terminals: np.ndarray, state_layout: Mapping[str, Any],
) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Collect and consume one fresh controlled LR-zero PPO transaction."""
    _C.qualification_set_memory_fixture(pufferl, state_values, terminals)
    for timestep in range(terminals.shape[0]):
        for buffer in range(base._int(state_layout.get("num_buffers"),
                                      "trial num_buffers", minimum=1)):
            _C.qualification_run_rollout_step(pufferl, buffer, timestep)
    _C.qualification_set_terminals(pufferl, tail_terminals)
    for buffer in range(base._int(state_layout.get("num_buffers"),
                                  "trial num_buffers", minimum=1)):
        _C.qualification_run_tail(pufferl, buffer)
    _C.train(pufferl)
    memory, metadata = _decode_native_snapshot(
        _C.qualification_memory_snapshot(pufferl), state_layout=state_layout)
    ordinary = base.decode_snapshot(_C.qualification_snapshot(pufferl))
    for target, source in (("selected_rows", "selected_rows"),
                           ("mb_ratio", "mb_ratio")):
        if source not in ordinary:
            raise MemoryQualificationError(
                f"ordinary qualification snapshot lacks {source}")
        memory[target] = ordinary[source].astype(
            np.int32 if target == "selected_rows" else np.float32, copy=False)
    trial = {
        "initial_states": memory["segment_initial_states"],
        "observation_terminals": memory["rollout_observation_terminals"],
        "selected_rows": memory["selected_rows"],
        "mb_initial_states": memory["mb_initial_states"],
        "mb_terminals": memory["mb_observation_terminals"],
        "mb_ratio": memory["mb_ratio"],
    }
    # Return every decoded native array for immutable diagnostics as well as
    # the normalized subset used by the validator.
    raw = {f"native_{key}": value for key, value in memory.items()
           if isinstance(value, np.ndarray)}
    raw.update({f"normalized_{key}": value for key, value in trial.items()})
    return trial, {"metadata": metadata, "raw": raw}


def run_step_zero_control(
    _C: Any, config: Mapping[str, Any], directory: Path, weights_path: Path,
    effective_state: np.ndarray, state_layout: Mapping[str, Any],
) -> tuple[np.ndarray, dict[str, np.ndarray]]:
    """Run the actual timestep-zero callback from an explicit effective state."""
    control = _C.create_pufferl(config)
    try:
        _C.load_weights(control, str(weights_path))
        base._load_frozen_from_primary(_C, control, directory, 2)
        zero_terminals = np.zeros((int(config["train"]["horizon"]),
                                   int(config["vec"]["total_agents"])), np.float32)
        _C.qualification_set_memory_fixture(
            control, np.ascontiguousarray(effective_state, dtype=np.float32),
            zero_terminals)
        for buffer in range(int(config["vec"]["num_buffers"])):
            _C.qualification_run_rollout_step(control, buffer, 0)
        memory, _ = _decode_native_snapshot(
            _C.qualification_memory_snapshot(control), state_layout=state_layout)
        ordinary = base.decode_snapshot(_C.qualification_snapshot(control))
        decoders = {key:value for key,value in ordinary.items()
                    if key.startswith("decoder_bank_")}
        return memory["behavior_current"].copy(), decoders
    finally:
        if int(config["cudagraphs"]) >= 0:
            _C.close(control)


def validate_step_control(
    actual_state: np.ndarray, control_state: np.ndarray,
    actual_decoders: Mapping[str, np.ndarray],
    control_decoders: Mapping[str, np.ndarray], *, atol: float,
) -> dict[str, float]:
    if actual_state.shape != control_state.shape:
        raise MemoryQualificationError("terminal step behavior-state control shape differs")
    state_error = float(np.max(np.abs(
        actual_state.astype(np.float64)-control_state.astype(np.float64))))
    if state_error > atol:
        raise MemoryQualificationError(
            f"terminal step behavior-state control error {state_error} exceeds {atol}")
    try:
        decoder_errors = base.compare_decoder_outputs(
            actual_decoders, control_decoders, atol=atol)
    except base.QualificationError as exc:
        raise MemoryQualificationError(str(exc)) from exc
    return {"behavior_state":state_error, **decoder_errors}


def validate_execution_counts(
    before: Mapping[str, Any], after: Mapping[str, Any],
    config: Mapping[str, Any], *, trials: int,
) -> dict[str, Any]:
    required = {"cudagraphs", "captured", "handles_ready",
                "graph_launch_counts", "eager_execution_counts"}
    if set(before) != required or set(after) != required:
        raise MemoryQualificationError("graph execution evidence schema differs")
    trials = base._int(trials, "memory fixture trials", minimum=1)
    roles = ("rollout", "tail", "train")
    expected = {
        "rollout": trials * int(config["train"]["horizon"])
                   * int(config["vec"]["num_buffers"]),
        "tail": trials * int(config["vec"]["num_buffers"]),
        "train": trials * (int(config["vec"]["total_agents"])
                   * int(config["train"]["horizon"])
                   // int(config["train"]["minibatch_size"])
                   * int(config["train"]["replay_ratio"])),
    }
    graph_mode = int(config["cudagraphs"]) >= 0
    active_key = "graph_launch_counts" if graph_mode else "eager_execution_counts"
    inactive_key = "eager_execution_counts" if graph_mode else "graph_launch_counts"
    active_delta, inactive_delta = {}, {}
    for snapshot in (before, after):
        if snapshot["cudagraphs"] != config["cudagraphs"]:
            raise MemoryQualificationError("graph execution mode differs from config")
        for field in ("captured", "handles_ready", "graph_launch_counts",
                      "eager_execution_counts"):
            if not isinstance(snapshot[field], Mapping) or set(snapshot[field]) != set(roles):
                raise MemoryQualificationError(f"graph execution {field} roles differ")
    for role in roles:
        for field in ("captured", "handles_ready"):
            expected_flag = graph_mode
            if before[field][role] is not expected_flag or after[field][role] is not expected_flag:
                raise MemoryQualificationError(
                    f"{role} {field} does not prove requested graph mode")
        active_delta[role] = base._int(after[active_key][role], f"after {role} counter", minimum=0) \
            - base._int(before[active_key][role], f"before {role} counter", minimum=0)
        inactive_delta[role] = base._int(after[inactive_key][role], f"after inactive {role}", minimum=0) \
            - base._int(before[inactive_key][role], f"before inactive {role}", minimum=0)
        if active_delta[role] != expected[role] or inactive_delta[role] != 0:
            raise MemoryQualificationError(
                f"{role} execution delta active={active_delta[role]} "
                f"inactive={inactive_delta[role]} expected={expected[role]}/0")
    return {"mode":"graph" if graph_mode else "eager", "expected":expected,
            "active_delta":active_delta, "inactive_delta":inactive_delta}


def run_live_crosswindow(_C: Any, config: Mapping[str, Any], directory: Path,
                         state_layout: Mapping[str, Any]
                         ) -> tuple[dict[str, np.ndarray], dict[str, Any]]:
    """Exercise ordinary `_C.rollouts` twice; this catches binding-level resets."""
    live = _C.create_pufferl(config)
    try:
        base._load_frozen_from_primary(_C, live, directory, 2)
        _C.rollouts(live)
        first, first_meta = _decode_native_snapshot(
            _C.qualification_memory_snapshot(live), state_layout=state_layout)
        first_final = first["behavior_current"].copy()
        first_tail_terminals = first["tail_terminals"].copy()
        _C.train(live)
        _C.rollouts(live)
        second, _ = _decode_native_snapshot(
            _C.qualification_memory_snapshot(live), state_layout=state_layout)
        observed = second["segment_initial_states"]
        primary, _ = base.derive_row_partition(
            state_layout, total_agents=first_final.shape[1])
        validate_live_crosswindow_arrays(
            first_final, first_tail_terminals, observed, primary_rows=primary)
        evidence = {
            "live_first_final_state": first_final,
            "live_first_tail_terminals": first_tail_terminals,
            "live_second_initial_state": observed.copy(),
        }
        _C.train(live)
        return evidence, first_meta
    finally:
        if int(config["cudagraphs"]) >= 0:
            _C.close(live)


def run_cell(args: argparse.Namespace) -> int:
    output_json = Path(args.output_json).resolve()
    output_npz = Path(args.output_npz).resolve()
    result: dict[str, Any] = {"schema_version": SCHEMA_VERSION,
        "qualification_only": True, "accepted": False}
    pufferl = None
    _C, module, cuda = base._load_backend(Path(args.puffer_root))
    missing = [name for name in HOOKS if not hasattr(_C, name)]
    if missing:
        raise MemoryQualificationError(f"terminal-memory hook surface missing: {missing}")
    config = _config(args.cudagraphs, args.seed)
    result.update(identity=base._module_identity(_C, module, Path(args.puffer_root)),
                  cuda_runtime_preflight=cuda, config=config)
    base.validate_module_identity(result["identity"])
    try:
        pufferl = _C.create_pufferl(config)
        base._load_frozen_from_primary(_C, pufferl, output_json.parent, 2)
        state_layout = _C.qualification_recurrent_state(pufferl, False)
        weights_before_path = output_json.parent / f".{output_json.stem}-weights-before.bin"
        weights_after_path = output_json.parent / f".{output_json.stem}-weights-after.bin"
        _C.save_weights(pufferl, str(weights_before_path))
        weights_before = base.sha256(weights_before_path)
        execution_before = dict(_C.qualification_graph_execution(pufferl))
        terminals = np.array([
            [0, 0, 0, 0, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 1, 0, 0],
            [0, 1, 0, 0, 0, 0, 1, 0],
            [0, 0, 0, 1, 1, 0, 0, 0],
        ], dtype=np.float32)
        # Unique, exactly representable sentinels catch row/layer swaps and
        # missing buffer offsets.  The separate segment-row setter is reserved
        # for a negative recompute-mismatch cell; it intentionally does not
        # mutate behavior state.
        # H64 is the smallest native geometry already exercised by the generic
        # CUDA qualification. Tiny H8 can fail constructor allocation/setup in
        # the custom matmul path before this fixture reaches recurrent logic.
        state_values = np.empty((2, 8, 64), dtype=np.float32)
        for layer in range(2):
            for row in range(8):
                state_values[layer, row] = (np.float32(1 + 100*layer + 10*row)
                    + np.arange(64, dtype=np.float32)/np.float32(128))
        _C.qualification_set_memory_fixture(pufferl, state_values, terminals)
        state_inputs, state_outputs, step_decoders = [], [], []
        for t in range(4):
            before, _ = _decode_native_snapshot(
                _C.qualification_memory_snapshot(pufferl), state_layout=state_layout)
            effective = before["behavior_current"].copy()
            effective[:, terminals[t].astype(bool), :] = 0
            state_inputs.append(effective)
            for buffer in range(2):
                _C.qualification_run_rollout_step(pufferl, buffer, t)
            after, _ = _decode_native_snapshot(
                _C.qualification_memory_snapshot(pufferl), state_layout=state_layout)
            state_outputs.append(after["behavior_current"].copy())
            ordinary_step = base.decode_snapshot(_C.qualification_snapshot(pufferl))
            step_decoders.append({key:value.copy() for key,value in ordinary_step.items()
                                  if key.startswith("decoder_bank_")})
        step_control_arrays: dict[str, np.ndarray] = {}
        step_control_errors: dict[str, dict[str, float]] = {}
        control_atol = base.GRAPH_ATOL_BY_PRECISION[int(_C.precision_bytes)]
        for timestep in range(1, terminals.shape[0]):
            if not np.any(terminals[timestep]):
                continue
            control_state, control_decoders = run_step_zero_control(
                _C, config, output_json.parent, weights_before_path,
                state_inputs[timestep], state_layout)
            step_control_errors[str(timestep)] = validate_step_control(
                state_outputs[timestep], control_state,
                step_decoders[timestep], control_decoders, atol=control_atol)
            step_control_arrays[f"step_{timestep}_actual_state"] = state_outputs[timestep]
            step_control_arrays[f"step_{timestep}_control_state"] = control_state
            for key, value in step_decoders[timestep].items():
                step_control_arrays[f"step_{timestep}_actual_{key}"] = value
            for key, value in control_decoders.items():
                step_control_arrays[f"step_{timestep}_control_{key}"] = value
        before_tail, _ = _decode_native_snapshot(
            _C.qualification_memory_snapshot(pufferl), state_layout=state_layout)
        tail_terminals = np.array([0, 1, 0, 0, 1, 0, 0, 1], dtype=np.float32)
        _C.qualification_set_terminals(pufferl, tail_terminals)
        for buffer in range(2):
            _C.qualification_run_tail(pufferl, buffer)
        after_tail, _ = _decode_native_snapshot(
            _C.qualification_memory_snapshot(pufferl), state_layout=state_layout)
        # Actual LR=0 PPO owns gather/recompute and must consume the fixture tail.
        _C.train(pufferl)
        arrays, metadata = _decode_native_snapshot(
            _C.qualification_memory_snapshot(pufferl), state_layout=state_layout)
        ordinary = base.decode_snapshot(_C.qualification_snapshot(pufferl))
        # PPO selection/ratio remain owned by the existing bounded snapshot;
        # the new memory hook need not duplicate those runtime tensors.
        for target, source in (("selected_rows", "selected_rows"),
                               ("mb_ratio", "mb_ratio"),
                               ("action_mask", "action_mask"),
                               ("logprobs", "logprobs")):
            if source not in ordinary:
                raise MemoryQualificationError(
                    f"ordinary qualification snapshot lacks {source}")
            arrays[target] = ordinary[source].astype(
                np.int32 if target == "selected_rows" else np.float32,
                copy=False)
        arrays.update(
            initial_states=arrays.pop("segment_initial_states"),
            observation_terminals=arrays.pop("rollout_observation_terminals"),
            behavior_state_in=np.stack(state_inputs, axis=0),
            behavior_state_out=np.stack(state_outputs, axis=0),
            persistent_state_before_tail=before_tail["behavior_current"],
            persistent_state_after_tail=after_tail["behavior_current"],
            tail_state_input=after_tail["tail_input_current"],
            mb_initial_states=arrays.pop("mb_initial_states"),
            mb_terminals=arrays.pop("mb_observation_terminals"),
        )
        arrays.update(step_control_arrays)
        # Preserve the complete first trial before any semantic validator can
        # reject it. Failed evidence is diagnostic and must remain inspectable.
        trial_prefix = output_json.stem
        first_trial_path = output_json.parent / f"{trial_prefix}-fixture-trial-00.npz"
        base.write_npz_atomic(first_trial_path, arrays)
        dimensions = validate_snapshot_schema(arrays, metadata)
        atol = base.RATIO_ATOL_BY_PRECISION[int(_C.precision_bytes)]
        result["terminal"] = validate_terminal_forward(arrays)
        result["terminal_step_zero_controls"] = step_control_errors
        result["tail"] = validate_tail_nonmutation(arrays)
        first_ratio = validate_gather_and_ratio(
            arrays, metadata, atol=atol, require_full_coverage=False)
        primary, frozen = base.derive_row_partition(
            state_layout, total_agents=state_values.shape[1])
        ratio_calls = [{"selected_rows": arrays["selected_rows"],
                        "ratios": arrays["mb_ratio"]}]
        covered = set(first_ratio["covered_primary_rows"])
        trial_paths = [str(first_trial_path)]
        for trial_index in range(1, 32):
            if covered == primary:
                break
            trial, evidence = run_fixture_trial(
                _C, pufferl, state_values, terminals, tail_terminals,
                state_layout)
            trial_path = output_json.parent / (
                f"{trial_prefix}-fixture-trial-{trial_index:02d}.npz")
            base.write_npz_atomic(trial_path, evidence["raw"])
            trial_paths.append(str(trial_path))
            verdict = validate_gather_and_ratio(
                trial, evidence["metadata"], atol=atol,
                require_full_coverage=False)
            covered.update(verdict["covered_primary_rows"])
            ratio_calls.append({"selected_rows": trial["selected_rows"],
                                "ratios": trial["mb_ratio"]})
            arrays[f"trial_{trial_index:02d}_selected_rows"] = trial["selected_rows"]
            arrays[f"trial_{trial_index:02d}_mb_ratio"] = trial["mb_ratio"]
        try:
            result["gather_ratio"] = base.validate_ratio_calls(
                ratio_calls, primary_rows=primary, frozen_rows=frozen,
                atol=atol)
        except base.QualificationError as exc:
            raise MemoryQualificationError(str(exc)) from exc
        result["fixture_trial_artifacts"] = trial_paths
        execution_after = dict(_C.qualification_graph_execution(pufferl))
        result["graph_execution"] = validate_execution_counts(
            execution_before, execution_after, config, trials=len(ratio_calls))
        result["graph_execution_before"] = execution_before
        result["graph_execution_after"] = execution_after
        _C.save_weights(pufferl, str(weights_after_path))
        weights_after = base.sha256(weights_after_path)
        base.validate_weight_identity(weights_before, weights_after)
        result["weights_before_sha256"] = weights_before
        result["weights_after_sha256"] = weights_after
        result["action_sensitivity"] = validate_action_sensitivity(arrays)
        result["dimensions"] = dimensions
        result["metadata"] = metadata
        derivative_mask = np.array([[1, 0, 0, 0], [0, 0, 1, 0]], np.float32)
        derivative_arrays = decode_and_validate_derivatives(
            _C.qualification_terminal_mingru_derivatives(derivative_mask))
        arrays.update({f"derivative_{key}": value
                       for key, value in derivative_arrays.items()})
        result["derivatives"] = {"accepted": True,
            "terminal_at_zero_grad_initial_exact_zero": True}
        live_arrays, _ = run_live_crosswindow(
            _C, config, output_json.parent, state_layout)
        arrays.update(live_arrays)
        result["live_crosswindow"] = {"accepted": True,
            "terminal_rows": int(np.count_nonzero(
                live_arrays["live_first_tail_terminals"]))}
        result["accepted"] = True
        base.write_npz_atomic(output_npz, arrays)
        result["artifact"] = str(output_npz)
        base.write_json_atomic(output_json, result)
        return 0
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        base.write_json_atomic(output_json, result)
        raise
    finally:
        for name in (f".{output_json.stem}-weights-before.bin",
                     f".{output_json.stem}-weights-after.bin"):
            (output_json.parent / name).unlink(missing_ok=True)
        if pufferl is not None and args.cudagraphs >= 0:
            _C.close(pufferl)


def run(args: argparse.Namespace) -> int:
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    python = Path(args.python).absolute() if args.python else (
        Path(args.puffer_root).resolve() / ".venv/bin/python")
    records = []
    for name, graphs in (("eager", -1), ("graph", base.DEFAULT_CUDAGRAPH_WARMUP_EPOCHS)):
        json_path, npz_path = out / f"{name}.json", out / f"{name}.npz"
        cmd = [str(python), str(Path(__file__).resolve()), "cell",
               "--puffer-root", str(Path(args.puffer_root).resolve()),
               "--cudagraphs", str(graphs), "--seed", str(args.seed),
               "--output-json", str(json_path), "--output-npz", str(npz_path)]
        try:
            done = subprocess.run(cmd, cwd=Path(args.puffer_root).resolve(),
                                  text=True, capture_output=True,
                                  timeout=args.timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            def timeout_text(value: str | bytes | None) -> str:
                if value is None:
                    return ""
                return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else value
            (out / f"{name}.stdout.log").write_text(
                timeout_text(exc.stdout), encoding="utf-8")
            (out / f"{name}.stderr.log").write_text(
                timeout_text(exc.stderr), encoding="utf-8")
            raise MemoryQualificationError(
                f"{name} cell timed out after {args.timeout_seconds} seconds") from exc
        # Preserve both streams even on success. Native constructor and CUDA
        # diagnostics are often emitted only on stderr; a truncated exception
        # string is not an adequate immutable failure artifact.
        (out / f"{name}.stdout.log").write_text(done.stdout, encoding="utf-8")
        (out / f"{name}.stderr.log").write_text(done.stderr, encoding="utf-8")
        if done.returncode:
            raise MemoryQualificationError(
                f"{name} cell failed: {(done.stderr or done.stdout)[-4000:]}")
        record = base._read_json(json_path)
        if record.get("accepted") is not True or record.get("qualification_only") is not True:
            raise MemoryQualificationError(f"{name} cell is not accepted qualification evidence")
        records.append(record)
    identity = base._require_same_identity(records)
    eager, graph = (base._read_npz(Path(record["artifact"])) for record in records)
    atol = base.GRAPH_ATOL_BY_PRECISION[int(identity["precision_bytes"])]
    result = {"schema_version": SCHEMA_VERSION, "qualification_only": True,
              "contract": CONTRACT, "accepted": True, "identity": identity,
              "cells": [record["artifact"] for record in records],
              "graph_max_abs": compare_graph_modes(eager, graph, atol=atol)}
    base.write_json_atomic(out / "TERMINAL_AWARE_MEMORY_QUALIFICATION.json", result)
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    run_p = sub.add_parser("run")
    run_p.add_argument("--puffer-root", required=True)
    run_p.add_argument("--output", required=True)
    run_p.add_argument("--python")
    run_p.add_argument("--seed", type=int, default=4242)
    run_p.add_argument("--timeout-seconds", type=int, default=900)
    cell = sub.add_parser("cell")
    cell.add_argument("--puffer-root", required=True)
    cell.add_argument("--cudagraphs", type=int, required=True)
    cell.add_argument("--seed", type=int, required=True)
    cell.add_argument("--output-json", required=True)
    cell.add_argument("--output-npz", required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        return run_cell(args) if args.command == "cell" else run(args)
    except (MemoryQualificationError, base.QualificationError, OSError,
            subprocess.SubprocessError, ValueError) as exc:
        print(f"terminal-aware memory qualification failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
