#!/usr/bin/env python3
"""Narrow executable proof for native CUDA entropy gradients and updates.

Runs the real ``pufferlib._C`` rollout/train path with identical seeded
positive- and zero-entropy cells in eager and captured-graph modes.  LR=0
schedule cells isolate the pre-clip logits-gradient contribution for all 20
updates and independently reconstruct it at updates 0, 10, and 19.  Separate
positive-LR cells prove that the entropy contribution changes saved policy
parameters from an identical initial checkpoint.  This does not replace the
full recurrent/F5 qualification.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import pickle
import subprocess
import sys
import struct
from typing import Any

import numpy as np

CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"
GRADIENT_CONTRACT = "ppo-entropy-preclip-gradient-v1"
TOTAL_UPDATES = 20
POINTS = (0, 10, 19)
BASE = 0.2
MIN_RATIO = 0.1
SEED = 93041
MAX_BYTES = 64 << 20


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_coefficient(index: int, base: float) -> float:
    progress = min(max(index / TOTAL_UPDATES, 0.0), 1.0)
    floor = base * MIN_RATIO
    real = floor + 0.5 * (base - floor) * (
        1.0 + math.cos(math.pi * progress))
    return struct.unpack("<f", struct.pack("<f", real))[0]


def runtime_identity(evidence: dict[str, Any]) -> dict[str, Any]:
    library = evidence.get("library", {})
    before = evidence.get("before_extension_import", {})
    after = evidence.get("after_extension_import", {})
    return {
        "library_path": library.get("resolved_path"),
        "library_sha256": library.get("sha256"),
        "cuda_visible_devices": evidence.get("cuda_visible_devices"),
        "before_return_code": before.get("return_code"),
        "before_device_count": before.get("device_count"),
        "after_return_code": after.get("return_code"),
        "after_device_count": after.get("device_count"),
    }


def load_runtime_helper(path: Path):
    spec = importlib.util.spec_from_file_location("cuda_runtime_helper", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load CUDA runtime helper")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def config(*, graphs: bool, coefficient: float, updates: int,
           learning_rate: float) -> dict[str, Any]:
    agents, horizon = 2, 2
    batch = agents * horizon
    return {
        "env_name": "bloodbowl", "reset_state": True,
        "cudagraphs": 10 if graphs else -1, "profile": False,
        "rank": 0, "world_size": 1, "gpu_id": 0, "nccl_id": "",
        "seed": SEED,
        "vec": {"total_agents": agents, "num_buffers": 1,
                "num_threads": 1, "num_frozen_banks": 0,
                "frozen_bank_pct": 0.0, "frozen_bank_hidden_size": 64,
                "frozen_bank_num_layers": 1},
        "env": {"seed": SEED, "max_decisions": 64},
        "policy": {"hidden_size": 64, "num_layers": 1},
        "train": {
            "horizon": horizon, "learning_rate": learning_rate,
            "min_lr_ratio": 1.0, "anneal_lr": False,
            "beta1": 0.9, "beta2": 0.95, "eps": 1e-8,
            "minibatch_size": batch, "replay_ratio": 1,
            "total_timesteps": batch * updates, "max_grad_norm": 1.0,
            "clip_coef": 0.2, "vf_clip_coef": 0.2, "vf_coef": 0.5,
            "ent_coef": coefficient, "min_ent_coef_ratio": MIN_RATIO,
            "anneal_ent_coef": True, "gamma": 0.995,
            "gae_lambda": 0.95, "vtrace_rho_clip": 1.0,
            "vtrace_c_clip": 1.0, "prio_alpha": 0.0,
            "prio_beta0": 1.0,
        },
    }


def decode_tensor(raw: Any) -> np.ndarray:
    if not isinstance(raw, dict) or raw.get("present") is not True:
        raise RuntimeError("required native tensor is absent")
    dtype = {"f32": "<f4", "i32": "<i4"}.get(raw.get("dtype"))
    shape = raw.get("shape")
    data = raw.get("data")
    if dtype is None or not isinstance(shape, list) or not isinstance(data, bytes):
        raise RuntimeError("malformed native tensor descriptor")
    array = np.frombuffer(data, dtype=dtype).copy()
    if array.size != math.prod(shape):
        raise RuntimeError("native tensor byte/shape mismatch")
    return array.reshape(tuple(shape))


FIELDS = ("decoder_output", "grad_logits", "grad_values", "mb_actions",
          "mb_logprobs", "mb_advantages", "mb_prio", "mb_action_mask",
          "act_sizes", "entropy_coefficient")
INVARIANTS = tuple(name for name in FIELDS
                   if name not in {"grad_logits", "entropy_coefficient"})


def gradient_state(_C, trainer, index: int) -> dict[str, np.ndarray]:
    raw = _C.qualification_entropy_gradient_state(trainer, MAX_BYTES)
    if (raw.get("contract") != GRADIENT_CONTRACT
            or raw.get("completed_update_index") != index
            or raw.get("committed_epoch") != index + 1
            or raw.get("precision") != "f32"
            or raw.get("is_continuous") is not False):
        raise RuntimeError("native gradient state identity differs")
    tensors = raw.get("tensors")
    if not isinstance(tensors, dict):
        raise RuntimeError("native gradient tensors missing")
    return {name: decode_tensor(tensors[name]) for name in FIELDS}


def graph_state(_C, trainer) -> dict[str, Any]:
    raw = _C.qualification_graph_execution(trainer)
    required = {"cudagraphs", "captured", "handles_ready",
                "graph_launch_counts", "eager_execution_counts"}
    if not isinstance(raw, dict) or set(raw) != required:
        raise RuntimeError("graph execution evidence schema differs")
    return raw


def counter_delta(before: dict[str, Any], after: dict[str, Any],
                  mode: str, role: str) -> int:
    key = "graph_launch_counts" if mode == "graph" else "eager_execution_counts"
    return int(after[key][role]) - int(before[key][role])


def checkpoint(_C, trainer, directory: Path, label: str) -> tuple[str, bytes]:
    path = directory / f"{label}.bin"
    _C.save_weights(trainer, str(path))
    data = path.read_bytes()
    return hashlib.sha256(data).hexdigest(), data


def run_cell(_C, *, graphs: bool, coefficient: float, updates: int,
             learning_rate: float, directory: Path, label: str):
    trainer = _C.create_pufferl(config(
        graphs=graphs, coefficient=coefficient, updates=updates,
        learning_rate=learning_rate))
    try:
        initial_graph = graph_state(_C, trainer)
        initial_sha, initial_bytes = checkpoint(_C, trainer, directory,
                                                label + "-before")
        selected: dict[int, dict[str, np.ndarray]] = {}
        coefficients: list[float] = []
        previous = initial_graph
        deltas = []
        for index in range(updates):
            _C.rollouts(trainer)
            _C.train(trainer)
            state = gradient_state(_C, trainer, index)
            coefficient_value = float(state["entropy_coefficient"].reshape(-1)[0])
            coefficients.append(coefficient_value)
            if index in POINTS or updates == 1:
                selected[index] = state
            current = graph_state(_C, trainer)
            mode = "graph" if graphs else "eager"
            deltas.append({role: counter_delta(previous, current, mode, role)
                           for role in ("rollout", "tail", "train")})
            other = "eager" if graphs else "graph"
            if any(counter_delta(previous, current, other, role)
                   for role in ("rollout", "tail", "train")):
                raise RuntimeError("execution occurred through the wrong mode")
            previous = current
            log = _C.log(trainer)
            schedule = log.get("entropy_schedule")
            if (not isinstance(schedule, dict)
                    or schedule.get("entropy_schedule_contract") != CONTRACT
                    or schedule.get("last_update_index") != index
                    or abs(float(schedule["last_effective_coefficient"])
                           - coefficient_value) > 1e-8):
                raise RuntimeError("native entropy log disagrees with device state")
        final_sha, final_bytes = checkpoint(_C, trainer, directory,
                                            label + "-after")
        return {"initial_sha256": initial_sha, "final_sha256": final_sha,
                "initial_bytes": initial_bytes, "final_bytes": final_bytes,
                "coefficients": coefficients, "selected": selected,
                "initial_graph": initial_graph, "final_graph": previous,
                "execution_deltas": deltas}
    finally:
        # The integrated native runtime has a documented graph-off teardown
        # defect: close assumes the rollout-graph pointer array exists.  Eager
        # cells therefore run in one-purpose worker processes and let process
        # teardown reclaim the allocation.  Graph cells exercise normal close.
        if graphs:
            _C.close(trainer)


def expected_gradient_delta(positive: dict[str, np.ndarray],
                            zero: dict[str, np.ndarray]) -> tuple[float, float]:
    for name in INVARIANTS:
        if not np.array_equal(positive[name], zero[name]):
            raise RuntimeError(f"coefficient pair changed gradient input {name}")
    logits = positive["decoder_output"][..., :-1].astype(np.float64)
    masks = positive["mb_action_mask"].astype(bool)
    act_sizes = positive["act_sizes"].reshape(-1).astype(int)
    observed = (positive["grad_logits"] - zero["grad_logits"]).astype(np.float64)
    coefficient_delta = float(positive["entropy_coefficient"].reshape(-1)[0]
                              - zero["entropy_coefficient"].reshape(-1)[0])
    expected = np.zeros_like(observed)
    offset = 0
    batch = math.prod(logits.shape[:-1])
    for size in act_sizes:
        head = logits[..., offset:offset + size]
        legal = masks[..., offset:offset + size]
        masked = np.where(legal, head, -np.inf)
        maximum = np.max(masked, axis=-1, keepdims=True)
        exp = np.where(legal, np.exp(masked - maximum), 0.0)
        probabilities = exp / exp.sum(axis=-1, keepdims=True)
        logp = np.where(legal, np.log(np.maximum(probabilities, 1e-300)), 0.0)
        entropy = -np.sum(probabilities * logp, axis=-1, keepdims=True)
        d_entropy = np.where(legal, probabilities * (-entropy - logp), 0.0)
        expected[..., offset:offset + size] = -coefficient_delta * d_entropy / batch
        offset += size
    if offset != logits.shape[-1]:
        raise RuntimeError("action-head sizes do not cover decoder logits")
    error = float(np.max(np.abs(observed - expected)))
    signal = float(np.max(np.abs(expected)))
    if signal <= 2e-7 or error > 5e-8 + 5e-3 * signal:
        raise RuntimeError(f"entropy gradient oracle failed: signal={signal} error={error}")
    return signal, error


def worker(args: argparse.Namespace) -> int:
    helper = load_runtime_helper(args.runtime_helper.resolve())
    runtime, runtime_evidence = helper.begin_cuda_runtime_preflight()
    sys.path.insert(0, str(args.puffer_root.resolve()))
    from pufferlib import _C
    runtime_evidence = helper.finish_cuda_runtime_preflight(runtime, runtime_evidence)
    if not bool(_C.gpu) or int(_C.precision_bytes) != 4:
        raise RuntimeError("native verifier requires a GPU fp32 extension")
    for name in ("qualification_entropy_gradient_state",
                 "qualification_graph_execution", "save_weights"):
        if not callable(getattr(_C, name, None)):
            raise RuntimeError(f"native qualification surface is missing: {name}")
    spec = json.loads(args.worker_spec)
    result = run_cell(
        _C, graphs=bool(spec["graphs"]), coefficient=float(spec["coefficient"]),
        updates=int(spec["updates"]), learning_rate=float(spec["learning_rate"]),
        directory=args.worker_output.parent, label=str(spec["label"]))
    result["runtime_evidence"] = runtime_evidence
    extension = Path(_C.__file__).resolve()
    result["identity"] = {
        "extension_path": str(extension), "extension_sha256": digest(extension),
        "extension_env_name": str(_C.env_name), "extension_gpu": bool(_C.gpu),
        "extension_precision_bytes": int(_C.precision_bytes),
        "native_source_sha256": digest(args.puffer_root.resolve() / "src" / "pufferlib.cu"),
    }
    with args.worker_output.open("wb") as handle:
        pickle.dump(result, handle, protocol=5)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puffer-root", type=Path, required=True)
    parser.add_argument("--runtime-helper", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--worker-spec")
    parser.add_argument("--worker-output", type=Path)
    args = parser.parse_args()
    if args.worker_spec is not None:
        if args.worker_output is None:
            raise RuntimeError("worker output is required")
        return worker(args)

    directory = args.output.resolve().with_suffix(".artifacts")
    directory.mkdir(parents=True, exist_ok=True)
    if True:
        worker_results = []

        def isolated(**cell):
            output = directory / f"worker-{len(worker_results)}.pickle"
            command = [sys.executable, str(Path(__file__).resolve()),
                "--puffer-root", str(args.puffer_root.resolve()),
                "--runtime-helper", str(args.runtime_helper.resolve()),
                "--output", str(args.output.resolve()),
                "--worker-spec", json.dumps(cell, sort_keys=True),
                "--worker-output", str(output)]
            completed = subprocess.run(command, env=dict(os.environ),
                                       capture_output=True, text=True)
            if completed.returncode:
                raise RuntimeError("native entropy worker failed: "
                                   + completed.stderr[-8000:])
            with output.open("rb") as handle:
                result = pickle.load(handle)
            worker_results.append(result)
            return result

        schedule = {}
        update = {}
        for graphs in (False, True):
            mode = "graph" if graphs else "eager"
            zero = isolated(graphs=graphs, coefficient=0.0,
                            updates=TOTAL_UPDATES, learning_rate=0.0,
                            label=f"schedule-{mode}-zero")
            positive = isolated(graphs=graphs, coefficient=BASE,
                                updates=TOTAL_UPDATES, learning_rate=0.0,
                                label=f"schedule-{mode}-positive")
            if zero["initial_sha256"] != positive["initial_sha256"]:
                raise RuntimeError("schedule pair did not start from identical weights")
            if zero["initial_sha256"] != zero["final_sha256"] \
                    or positive["initial_sha256"] != positive["final_sha256"]:
                raise RuntimeError("LR=0 schedule cell changed weights")
            for index, (zero_coefficient, positive_coefficient) in enumerate(
                    zip(zero["coefficients"], positive["coefficients"], strict=True)):
                expected = expected_coefficient(index, BASE)
                if zero_coefficient != 0.0:
                    raise RuntimeError(
                        f"zero control applied entropy at update {index}")
                if abs(positive_coefficient - expected) > 1e-8:
                    raise RuntimeError(
                        "native device coefficient differs from independent "
                        f"cosine oracle at update {index}: "
                        f"{positive_coefficient} != {expected}")
            point_evidence = []
            for index in POINTS:
                signal, error = expected_gradient_delta(
                    positive["selected"][index], zero["selected"][index])
                point_evidence.append({"update_index": index,
                    "coefficient": positive["coefficients"][index],
                    "maximum_expected_gradient_delta": signal,
                    "maximum_gradient_error": error})
            schedule[mode] = {"points": point_evidence,
                "execution_deltas": positive["execution_deltas"],
                "initial_graph": positive["initial_graph"],
                "final_graph": positive["final_graph"],
                "initial_weights_sha256": positive["initial_sha256"]}

            zero_u = isolated(graphs=graphs, coefficient=0.0, updates=1,
                              learning_rate=1e-3, label=f"update-{mode}-zero")
            pos_u = isolated(graphs=graphs, coefficient=BASE, updates=1,
                             learning_rate=1e-3, label=f"update-{mode}-positive")
            signal, error = expected_gradient_delta(
                pos_u["selected"][0], zero_u["selected"][0])
            if zero_u["initial_sha256"] != pos_u["initial_sha256"]:
                raise RuntimeError("parameter pair did not start identically")
            if zero_u["final_sha256"] == pos_u["final_sha256"]:
                raise RuntimeError("entropy gradient did not change policy parameters")
            differing = sum(a != b for a, b in zip(
                zero_u["final_bytes"], pos_u["final_bytes"], strict=True))
            if differing <= 0:
                raise RuntimeError("parameter checkpoints lack a byte delta")
            update[mode] = {"initial_weights_sha256": pos_u["initial_sha256"],
                "zero_final_weights_sha256": zero_u["final_sha256"],
                "positive_final_weights_sha256": pos_u["final_sha256"],
                "differing_checkpoint_bytes": differing,
                "maximum_expected_gradient_delta": signal,
                "maximum_gradient_error": error,
                "execution_delta": pos_u["execution_deltas"][0]}

        for index in POINTS:
            left = schedule["eager"]["points"][POINTS.index(index)]
            right = schedule["graph"]["points"][POINTS.index(index)]
            if left != right:
                raise RuntimeError("eager/graph entropy gradient oracle differs")
        if update["eager"]["initial_weights_sha256"] != update["graph"]["initial_weights_sha256"]:
            raise RuntimeError("eager/graph update cells started from different weights")
        if (update["eager"]["zero_final_weights_sha256"]
                != update["graph"]["zero_final_weights_sha256"]
                or update["eager"]["positive_final_weights_sha256"]
                != update["graph"]["positive_final_weights_sha256"]):
            raise RuntimeError("eager/graph parameter updates differ")

    identities = [result["identity"] for result in worker_results]
    if any(identity != identities[0] for identity in identities[1:]):
        raise RuntimeError("native module identity drifted between workers")
    runtime_evidence = worker_results[0]["runtime_evidence"]
    bound_runtime = runtime_identity(runtime_evidence)
    if any(runtime_identity(result["runtime_evidence"]) != bound_runtime
           for result in worker_results[1:]):
        raise RuntimeError("CUDA runtime identity drifted between workers")
    artifacts = []
    for path in sorted(directory.iterdir()):
        if path.is_file():
            artifacts.append({"name": path.name, "bytes": path.stat().st_size,
                              "sha256": digest(path)})
    evidence = {"schema_version": 1,
        "claim": "native-cuda-entropy-gradient-graph-and-update-v1",
        "scope_limit": "Not the full recurrent/F5 qualification.",
        "identity": {"verifier_sha256": digest(Path(__file__).resolve()),
                     **identities[0]},
        "cuda_runtime_preflight": runtime_evidence,
        "worker_artifacts": {"directory": str(directory), "files": artifacts},
        "fixture": {"seed": SEED, "total_updates": TOTAL_UPDATES,
            "point_indices": list(POINTS), "base_coefficient": BASE,
            "min_coefficient_ratio": MIN_RATIO,
            "schedule_learning_rate": 0.0, "update_learning_rate": 1e-3,
            "worker_processes": len(worker_results),
            "eager_teardown": "process-exit-known-close-defect"},
        "schedule_gradient": schedule, "parameter_update": update,
        "passed": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": True, "output": str(args.output)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
