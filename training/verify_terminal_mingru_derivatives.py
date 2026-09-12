#!/usr/bin/env python3
"""Verify terminal-aware native MinGRU forward/backward against float64 autograd."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import qualify_recurrent_cuda as q


FIELDS = (
    "combined", "inputs", "initial_state", "terminals", "outputs",
    "final_state", "grad_outputs", "grad_combined", "grad_inputs",
    "grad_initial_state",
)
CASES = (
    np.array([[1, 0, 0, 0], [0, 0, 1, 0]], dtype=np.float32),
    np.array([[0, 1, 0, 1], [0, 0, 0, 0]], dtype=np.float32),
    np.array([[1, 1, 0, 0], [0, 1, 1, 0]], dtype=np.float32),
)
ATOL = 3e-5
MAX_BYTES = 16 << 20


def require_finite(arrays: dict[str, np.ndarray], label: str) -> None:
    for name, value in arrays.items():
        if not np.isfinite(np.asarray(value)).all():
            raise RuntimeError(f"{label}.{name} contains non-finite values")


def persist_case(output: Path, case: int, arrays: dict[str, np.ndarray]) -> dict:
    path = output / f"TERMINAL_DERIVATIVE_{case}.raw.npz"
    q.write_npz_atomic(path, arrays)
    return {"path": str(path.resolve()), "sha256": q.sha256(path)}


def reference(arrays: dict[str, np.ndarray], torch, fast_sigmoid) -> dict[str, np.ndarray]:
    combined = torch.tensor(arrays["combined"], dtype=torch.float64, requires_grad=True)
    inputs = torch.tensor(arrays["inputs"], dtype=torch.float64, requires_grad=True)
    initial = torch.tensor(
        arrays["initial_state"], dtype=torch.float64, requires_grad=True
    )
    terminals = torch.tensor(arrays["terminals"], dtype=torch.bool)
    hidden, gate, projection = combined.chunk(3, dim=-1)
    state = initial
    outputs = []
    for step in range(inputs.shape[1]):
        # torch.where makes this a real graph cut: when reset is true, neither
        # the segment initial state nor the pre-terminal recurrence receives an
        # adjoint from this or later timesteps.
        state = torch.where(terminals[:, step, None], torch.zeros_like(state), state)
        candidate = torch.where(
            hidden[:, step] >= 0,
            hidden[:, step] + 0.5,
            fast_sigmoid(hidden[:, step]),
        )
        state = torch.lerp(state, candidate, torch.sigmoid(gate[:, step]))
        highway = torch.sigmoid(projection[:, step])
        outputs.append(highway * state + (1 - highway) * inputs[:, step])
    output = torch.stack(outputs, dim=1)
    grad_outputs = torch.tensor(arrays["grad_outputs"], dtype=torch.float64)
    (output * grad_outputs).sum().backward()
    return {
        "outputs": output.detach().numpy(),
        "final_state": state.detach().numpy(),
        "grad_combined": combined.grad.detach().numpy(),
        "grad_inputs": inputs.grad.detach().numpy(),
        "grad_initial_state": initial.grad.detach().numpy(),
    }


def check_case(C, terminal_mask, output, case_index, torch, fast_sigmoid):
    raw = C.qualification_terminal_mingru_derivatives(terminal_mask, MAX_BYTES)
    if raw.get("contract") != "terminal-mingru-derivatives-fp32-v1":
        raise RuntimeError("native terminal derivative contract mismatch")
    arrays = {name: q._decode_tensor(raw["tensors"][name]) for name in FIELDS}
    artifact = persist_case(output, case_index, arrays)
    require_finite(arrays, "native")
    if not np.array_equal(arrays["terminals"], terminal_mask):
        raise RuntimeError("native terminal fixture changed the requested mask")
    refs = reference(arrays, torch, fast_sigmoid)
    require_finite(refs, "reference")
    errors = {}
    for name, expected in refs.items():
        actual = arrays[name].astype(np.float64)
        if actual.shape != expected.shape:
            raise RuntimeError(f"{name} shape mismatch: {actual.shape} != {expected.shape}")
        errors[name] = float(np.max(np.abs(actual - expected)))
    if not all(math.isfinite(value) for value in errors.values()):
        raise RuntimeError(f"terminal derivative error is non-finite: {errors}")
    if max(errors.values()) > ATOL:
        raise RuntimeError(f"terminal derivative mismatch: {errors}")
    reset_at_zero = terminal_mask[:, 0] == 1
    if reset_at_zero.any() and not np.array_equal(
        arrays["grad_initial_state"][reset_at_zero],
        np.zeros_like(arrays["grad_initial_state"][reset_at_zero]),
    ):
        raise RuntimeError("terminal at timestep zero did not cut initial-state gradient")
    return {"case": case_index, "terminal_mask": terminal_mask.tolist(),
            "raw_artifact": artifact, "max_abs": errors}


def identity(path: Path) -> dict:
    path = path.resolve()
    return {"path": str(path), "sha256": q.sha256(path)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puffer-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    result_path = args.output / "TERMINAL_MINGRU_DERIVATIVES.json"
    here = Path(__file__).resolve().parent
    result = {
        "status": "FAIL", "error": None, "cases": [],
        "config": {"atol": ATOL, "max_bytes": MAX_BYTES},
        "identity": {
            "runner": identity(Path(__file__)),
            "native_patch": identity(here / "puffer_terminal_aware_native.patch"),
            "models_source": identity(args.puffer_root / "src/models.cu"),
        },
    }
    try:
        C, module, runtime = q._load_backend(args.puffer_root)
        module_identity = q._module_identity(C, module, args.puffer_root)
        q.validate_module_identity(module_identity)
        result["identity"]["module"] = module_identity
        result["identity"]["cuda_runtime_preflight"] = runtime
        if getattr(C, "rollout_transition_contract", None) != "terminal-aware-tbptt-v1":
            raise RuntimeError("compiled terminal-aware recurrent contract is absent")
        if not hasattr(C, "qualification_terminal_mingru_derivatives"):
            raise RuntimeError("native terminal derivative hook is absent")
        import torch
        from verify_mingru_direct_derivatives import fast_sigmoid
        for index, terminal_mask in enumerate(CASES):
            result["cases"].append(check_case(
                C, terminal_mask, args.output, index, torch, fast_sigmoid
            ))
            q.write_json_atomic(result_path, result)
        result["status"] = "PASS"
    except BaseException as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        q.write_json_atomic(result_path, result)
        raise
    finally:
        q.write_json_atomic(result_path, result)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
