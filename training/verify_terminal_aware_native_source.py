#!/usr/bin/env python3
"""Source-level contract verifier for the native terminal-aware TBPTT patch.

This is deliberately a source gate, not CUDA acceptance. The target qualifier
must still execute graph/eager rollout, tail, gather, and PPO kernels.
"""

from __future__ import annotations

import argparse
from pathlib import Path


CONTRACT = "terminal-aware-tbptt-v1"


def require(text: str, needle: str, label: str, errors: list[str]) -> None:
    if needle not in text:
        errors.append(f"missing {label}: {needle!r}")


def verify(root: Path) -> list[str]:
    errors: list[str] = []
    source = root / "src" if (root / "src").is_dir() else root
    models = (source / "models.cu").read_text()
    native = (source / "pufferlib.cu").read_text()
    bindings = (source / "bindings.cu").read_text()
    cpu = (source / "bindings_cpu.cpp").read_text()

    require(bindings, f'rollout_transition_contract") = "{CONTRACT}"',
            "native compiled contract", errors)
    require(cpu, f'rollout_transition_contract") = "{CONTRACT}"',
            "CPU compiled contract", errors)
    require(native, "PrecisionTensor segment_initial_states",
            "detached segment initial-state storage", errors)
    require(native, ".shape = {num_layers, total_agents, hidden_size}",
            "global physical-row initial-state layout", errors)
    require(native, "PrecisionTensor mb_terminals",
            "stable gathered observation-terminal masks", errors)
    require(native, "case 7:", "same-index initial-state gather channel", errors)
    require(native, "segment_initial_states[(layer * total_rows + src_row)",
            "global sampled-row ownership", errors)
    require(native, "tail_input_states", "detached tail input state", errors)
    require(native, "puf_copy(&tail_state, input_state, stream)",
            "separate tail work state", errors)
    require(native, "training requires exactly one segment-initial record and ",
            "training lifecycle gate", errors)
    require(native, "if (t == 0 && b == 0)",
            "post-clear primary segment snapshot", errors)
    require(native, "pufferl->evaluation_mode_puf);",
            "device-gated graph-captured segment snapshot", errors)
    require(bindings, "rollout would overwrite unconsumed segment initial state",
            "rollout initial-state lifecycle guard", errors)
    if "Zero state buffers (primary + every frozen bank" in bindings:
        errors.append("rollout still clears recurrent state at every training window")
    require(bindings, "mode change would discard unconsumed recurrent evidence",
            "mode-change lifecycle guard", errors)

    kernel_start = native.find("__global__ void reset_recurrent_state_on_terminal")
    kernel_end = native.find("\n}\n", kernel_start)
    reset_kernel = native[kernel_start:kernel_end]
    if "evaluation_mode" in reset_kernel:
        errors.append("terminal clearing is still conditional on evaluation mode")
    require(models, "precision_t* terminal_ptr", "MinGRU terminal input", errors)
    require(models, "state = 0.0f;", "pre-forward recurrent reset", errors)
    require(models, "? 0.0f\n            : to_float(from_float(",
            "zero effective previous state in gate derivative", errors)
    require(models, "grad_state = 0.0f;", "backward recurrent graph cut", errors)
    require(models, "puf_zero(&a->grad_next_state, stream)",
            "ordinary PPO final-state adjoint reset", errors)

    for hook in (
        "qualification_set_memory_fixture",
        "qualification_set_terminals",
        "qualification_run_rollout_step",
        "qualification_run_tail",
        "qualification_set_segment_initial_row",
        "qualification_memory_snapshot",
        "qualification_terminal_mingru_derivatives",
    ):
        require(bindings, f'm.def("{hook}"', f"qualification hook {hook}", errors)
    for field in (
        "segment_initial_states",
        "rollout_observation_terminals",
        "mb_initial_states",
        "mb_observation_terminals",
        "tail_input_states",
        "tail_work_states",
        "tail_values",
        "tail_terminals",
    ):
        require(bindings, f'["{field}"]', f"qualification field {field}", errors)
    if "py::dict b = py::dict(meta)" in bindings or \
            "py::dict ti = py::dict(meta)" in bindings or \
            "py::dict tw = py::dict(meta)" in bindings:
        errors.append(
            "qualification memory snapshot aliases behavior/tail dictionaries")
    require(bindings, 'b["tensor"] = qualification_precision_tensor(',
            "independent behavior-state snapshot dictionary", errors)
    require(bindings, 'ti["tensor"] = qualification_precision_tensor(',
            "independent tail-input snapshot dictionary", errors)
    require(bindings, 'tw["tensor"] = qualification_precision_tensor(',
            "independent tail-work snapshot dictionary", errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    args = parser.parse_args()
    errors = verify(args.source_root)
    if errors:
        for error in errors:
            print(error)
        return 1
    print(f"verified native recurrent contract: {CONTRACT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
