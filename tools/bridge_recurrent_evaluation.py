#!/usr/bin/env python3
"""Read-only, stepwise bridge between two frozen recurrent eval runtimes.

The controller launches one fresh process per runtime.  The worker runs H=1
native evaluation and records the actual qualification snapshot after every
rollout.  It never calls ``train``.  The resulting comparison is an inference
compatibility gate, not checkpoint ancestry or policy-strength evidence.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping

import numpy as np

try:
    from live_integrity_guard import HARD_INTEGRITY_KEYS
except ModuleNotFoundError:
    from tools.live_integrity_guard import HARD_INTEGRITY_KEYS


SCHEMA_VERSION = 1
STYLES = {"contact": 0, "cage": 1}
SIDES = {"home": 0, "away": 1}
TRACE_FIELDS = (
    "observations", "action_mask", "actions", "rewards", "terminals",
    "logprobs", "values",
)
EXACT_FIELDS = ("observations", "action_mask", "actions", "terminals")
NUMERIC_FIELDS = ("rewards", "logprobs", "values")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
DEFAULT_SEEDS = (2026090501, 2026090502)
DEFAULT_GAMES_PER_SEED = 2
DEFAULT_MAX_TRACE_BYTES = 32 * 1024 * 1024
EXPECTED_ENVIRONMENT_SHA256 = "6fbd67f7201ce9830b3f282f19d3a98768ea197b8f3e5b9357991460884526f1"


class BridgeFailure(RuntimeError):
    """A frozen bridge input, runtime, trace, or acceptance gate failed."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_safe(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise BridgeFailure(f"effective config contains unsupported {type(value).__name__}")


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        json_safe(value), sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()


def validate_serialized_weights(before: Path, after: Path | None,
                                checkpoint_sha256: str) -> str:
    before_sha = sha256_file(before)
    if before_sha != checkpoint_sha256:
        raise BridgeFailure(
            "serialized pre-evaluation weights differ from the pinned checkpoint")
    if after is not None and sha256_file(after) != before_sha:
        raise BridgeFailure("inference changed serialized policy weights")
    return before_sha


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _sha(value: str, label: str) -> str:
    if not SHA256_RE.fullmatch(value):
        raise BridgeFailure(f"{label} must be a lowercase SHA-256")
    return value


def validate_plan(plan: Mapping[str, Any]) -> None:
    if plan.get("schema_version") != SCHEMA_VERSION:
        raise BridgeFailure("bridge plan schema is not 1")
    if plan.get("horizon") != 1 or plan.get("demo_reset_pct") != 0:
        raise BridgeFailure("bridge requires horizon=1 and demo_reset_pct=0")
    if plan.get("styles") != list(STYLES) or plan.get("sides") != list(SIDES):
        raise BridgeFailure("bridge requires contact/cage and home/away in canonical order")
    seeds = plan.get("seeds")
    if (not isinstance(seeds, list) or len(seeds) != 2 or len(set(seeds)) != 2
            or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in seeds)):
        raise BridgeFailure("bridge requires exactly two distinct nonnegative seeds")
    if plan.get("games_per_seed") != DEFAULT_GAMES_PER_SEED:
        raise BridgeFailure("bounded bridge requires exactly two games per seed")
    if plan.get("policy") != {"hidden_size": 512, "num_layers": 3}:
        raise BridgeFailure("bridge requires the frozen H512 L3 policy shape")
    if plan.get("environment_sha256") != EXPECTED_ENVIRONMENT_SHA256:
        raise BridgeFailure("bridge environment identity is not the frozen obs-v7 source")
    if plan.get("qualification_only") is not True or plan.get("lineage_promotion") is not False:
        raise BridgeFailure("bridge must remain qualification-only and ineligible for promotion")
    cap = plan.get("max_trace_bytes")
    if isinstance(cap, bool) or not isinstance(cap, int) or not 0 < cap <= DEFAULT_MAX_TRACE_BYTES:
        raise BridgeFailure("trace cap must be positive and no larger than 32 MiB")
    for key in ("atol", "rtol"):
        value = plan.get(key)
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value < 0):
            raise BridgeFailure(f"{key} must be finite and nonnegative")
    _sha(str(plan.get("checkpoint_sha256", "")), "checkpoint_sha256")
    cudart = Path(str(plan.get("cudart", "")))
    if not cudart.is_absolute() or cudart.name != "libcudart.so.12":
        raise BridgeFailure("cudart must be an absolute libcudart.so.12 path")
    for name in ("old", "new"):
        arm = plan.get("arms", {}).get(name)
        if not isinstance(arm, Mapping):
            raise BridgeFailure(f"missing {name} arm")
        root = Path(str(arm.get("runtime_root", "")))
        python = Path(str(arm.get("python", "")))
        if not root.is_absolute() or not python.is_absolute():
            raise BridgeFailure("runtime roots and Python executables must be absolute")
        _sha(str(arm.get("expected_module_sha256", "")), f"{name} module SHA-256")
        contract = arm.get("expected_contract")
        expected = "tail-bootstrap-v1" if name == "old" else "terminal-aware-tbptt-v1"
        if contract != expected:
            raise BridgeFailure(f"{name} arm contract must be {expected}")


def worker_command(script: Path, plan_path: Path, output: Path, arm: str) -> list[str]:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan)
    python = str(plan["arms"][arm]["python"])
    return [python, str(script), "worker", "--plan", str(plan_path),
            "--arm", arm, "--output", str(output)]


def worker_environment(plan: Mapping[str, Any], arm: str) -> dict[str, str]:
    root = Path(plan["arms"][arm]["runtime_root"])
    env = dict(os.environ)
    # Replace, rather than extend, PYTHONPATH: imports must come from the arm.
    env["PYTHONPATH"] = os.pathsep.join((str(root / "vendor/PufferLib"), str(root / "tools")))
    env["CUDA_VISIBLE_DEVICES"] = str(plan["gpu_id"])
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["OMP_NUM_THREADS"] = "16"
    env["OPENBLAS_NUM_THREADS"] = "16"
    env["LD_PRELOAD"] = str(plan["cudart"])
    env["PATH"] = str(Path(plan["arms"][arm]["python"]).parent) + os.pathsep + env["PATH"]
    return env


def _array_record(value: Any, *, include_values: bool) -> dict[str, Any]:
    array = np.asarray(value)
    if array.dtype == object or not np.isfinite(array).all():
        raise BridgeFailure("qualification snapshot contains object or non-finite data")
    contiguous = np.ascontiguousarray(array)
    record: dict[str, Any] = {
        "dtype": contiguous.dtype.str,
        "shape": list(contiguous.shape),
        "sha256": hashlib.sha256(contiguous.tobytes()).hexdigest(),
    }
    if include_values:
        record["values"] = contiguous.reshape(-1).tolist()
    return record


def snapshot_record(snapshot: Mapping[str, Any], *, step: int, cell: Mapping[str, Any]) -> dict[str, Any]:
    missing = [field for field in TRACE_FIELDS if field not in snapshot]
    if missing:
        raise BridgeFailure(f"actual qualification snapshot lacks {missing}")
    fields = {
        field: _array_record(
            snapshot[field], include_values=field not in ("observations", "action_mask")
        )
        for field in TRACE_FIELDS
    }
    return {"schema_version": 1, "step": step, "cell": dict(cell), "fields": fields}


def _decode_tensor(record: Mapping[str, Any]) -> np.ndarray:
    if not isinstance(record, Mapping):
        raise BridgeFailure("native qualification tensor record is malformed")
    dtype = record.get("dtype")
    shape_raw = record.get("shape")
    data = record.get("data")
    if (not isinstance(shape_raw, list)
            or any(isinstance(value, bool) or not isinstance(value, int) or value < 0
                   for value in shape_raw)):
        raise BridgeFailure("native qualification tensor shape is malformed")
    if not isinstance(data, bytes):
        raise BridgeFailure("native qualification tensor payload is not bytes")
    shape = tuple(shape_raw)
    elements = math.prod(shape) if shape else 0
    width = {"f32": 4, "bf16": 2, "i32": 4}.get(str(dtype))
    if width is None:
        raise BridgeFailure(f"unsupported native qualification dtype: {dtype!r}")
    if len(data) != elements * width:
        raise BridgeFailure("native qualification tensor byte count differs from shape")
    if dtype == "i32":
        return np.frombuffer(data, dtype="<i4").copy().reshape(shape)
    if dtype == "f32":
        array = np.frombuffer(data, dtype="<f4").copy()
    else:
        words = np.frombuffer(data, dtype="<u2").astype(np.uint32)
        array = (words << np.uint32(16)).view(np.float32).copy()
    return array.reshape(shape).astype(np.float32, copy=False)


def _decode_snapshot(raw: Mapping[str, Any]) -> dict[str, np.ndarray]:
    # This duplicates the proven decoder in qualify_recurrent_cuda.py locally
    # so importing the bridge never invokes that qualifier's current-contract
    # constants against the intentionally historical arm.
    source = raw.get("tensors")
    if not isinstance(source, Mapping):
        raise BridgeFailure("native qualification snapshot lacks its tensor mapping")
    return {field: _decode_tensor(source[field])
            for field in TRACE_FIELDS if field in source}


def _flat_log(pufferl: Any, backend: Any, runner: Any) -> dict[str, Any]:
    return dict(pufferl.unroll_nested_dict(backend.eval_log(runner)))


def completed_games(logs: Mapping[str, Any], previous: int) -> int:
    raw = logs.get("env/n")
    if raw is None and previous == 0 and not any(
            str(key).startswith("env/") for key in logs):
        # Native eval_log has no episode panel until the first game completes.
        # Metadata-only startup output is not evidence of a completed game.
        return 0
    if (isinstance(raw, bool) or not isinstance(raw, (int, float))
            or not math.isfinite(float(raw)) or float(raw) != int(raw)):
        keys = sorted(str(key) for key in logs)
        raise BridgeFailure(
            "evaluation log env/n is missing or not an exact integer; "
            f"actual keys={keys}")
    current = int(raw)
    if current < previous or current - previous > 1:
        raise BridgeFailure("one-env H=1 evaluation game count is not cumulative by zero or one")
    return current


def _cell_config(base: dict[str, Any], cell: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    args = copy.deepcopy(base)
    seed = int(cell["seed"])
    bot_team = 1 - SIDES[str(cell["side"])]
    args["reset_state"] = False
    args["seed"] = seed
    args["nccl_id"] = b""
    args["train"].update({"seed": seed, "horizon": 1, "minibatch_size": 2,
                          "replay_ratio": 1.0})
    args["policy"].update({"hidden_size": 512, "num_layers": 3})
    args["vec"].update({"num_buffers": 1, "total_agents": 2,
                        "num_frozen_banks": 0, "frozen_bank_pct": 0.0})
    args.setdefault("selfplay", {})["enabled"] = 0
    args["env"].update({
        "seed": seed, "max_decisions": int(plan["max_decisions"]),
        "demo_reset_pct": 0.0, "scripted_opponent": 1,
        "scripted_opponent_type": STYLES[str(cell["style"])],
        "scripted_opponent_team": bot_team, "scripted_bank_tag": 0,
        "scripted_bank_mask": 0,
    })
    return args


def run_worker(plan_path: Path, arm_name: str, output: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan)
    if output.exists():
        raise BridgeFailure(f"refusing to overwrite worker output: {output}")
    arm = plan["arms"][arm_name]
    root = Path(arm["runtime_root"])
    expected_python = str(arm["python"])
    # Lexical identity is intentional: resolving symlinks would erase which
    # shared venv entry point the controller invoked.
    if sys.executable != expected_python:
        raise BridgeFailure(f"worker Python differs lexically: {sys.executable!r}")
    if os.environ.get("PYTHONPATH") != worker_environment(plan, arm_name)["PYTHONPATH"]:
        raise BridgeFailure("worker PYTHONPATH differs from the explicit arm path")
    sys.path.insert(0, str(root / "tools"))
    from puffer_cuda_runtime import (begin_cuda_runtime_preflight,
        finish_cuda_runtime_preflight, validate_cuda_runtime_evidence)
    pending, cuda_evidence = begin_cuda_runtime_preflight()
    sys.path.insert(0, str(root / "vendor/PufferLib"))
    from pufferlib import _C as backend
    from pufferlib import pufferl
    cuda_evidence = finish_cuda_runtime_preflight(pending, cuda_evidence)
    validate_cuda_runtime_evidence(cuda_evidence)
    if not bool(getattr(backend, "gpu", False)) or int(getattr(backend, "precision_bytes", 0)) != 4:
        raise BridgeFailure("bridge requires native CUDA fp32")
    module = Path(backend.__file__).resolve()
    module_sha = sha256_file(module)
    if module_sha != arm["expected_module_sha256"]:
        raise BridgeFailure("imported module SHA-256 differs from pinned arm")
    actual_contract = str(getattr(backend, "rollout_transition_contract", "<missing>"))
    if actual_contract != arm["expected_contract"]:
        raise BridgeFailure("compiled recurrent contract differs from pinned arm")
    if getattr(backend, "env_name", None) != "bloodbowl":
        raise BridgeFailure("compiled environment is not bloodbowl")
    if (getattr(backend, "observation_abi", None) != "obs-v7"
            or int(getattr(backend, "observation_version", -1)) != 7):
        raise BridgeFailure("compiled observation contract is not obs-v7")
    if getattr(backend, "action_abi", None) != "exact-joint-v1":
        raise BridgeFailure("compiled action contract is not exact-joint-v1")
    if str(getattr(backend, "environment_source_hash", "<missing>")) != plan["environment_sha256"]:
        raise BridgeFailure("compiled environment SHA-256 differs from frozen obs-v7 source")
    checkpoint = Path(plan["checkpoint"])
    if sha256_file(checkpoint) != plan["checkpoint_sha256"]:
        raise BridgeFailure("checkpoint SHA-256 differs before evaluation")
    output.mkdir(parents=True)
    before = output / "weights-before.bin"
    after = output / "weights-after.bin"
    trace_path = output / "TRACE.jsonl"
    startup_log_schema_path = output / "STARTUP_LOG_SCHEMA.json"
    cells = [{"style": style, "side": side, "seed": seed}
             for style in plan["styles"] for side in plan["sides"] for seed in plan["seeds"]]
    saved_argv = sys.argv
    try:
        sys.argv = [saved_argv[0]]
        base = pufferl.load_config("bloodbowl")
    finally:
        sys.argv = saved_argv
    step = 0
    cell_results = []
    with trace_path.open("xb") as trace:
        for cell in cells:
            effective_config = _cell_config(base, cell, plan)
            effective_config_sha256 = canonical_sha256(effective_config)
            runner = backend.create_pufferl(effective_config)
            try:
                backend.load_weights(runner, str(checkpoint))
                backend.set_evaluation_mode(runner, True)
                backend.save_weights(runner, str(before))
                validate_serialized_weights(
                    before, None, str(plan["checkpoint_sha256"]))
                start_games = 0
                previous_games = start_games
                target = int(plan["games_per_seed"])
                rollouts = 0
                final_log: dict[str, Any] = {}
                while True:
                    if rollouts >= int(plan["max_rollouts_per_cell"]):
                        raise BridgeFailure(f"cell exceeded rollout bound: {cell}")
                    backend.rollouts(runner)
                    rollouts += 1
                    raw = backend.qualification_snapshot(runner)
                    row = snapshot_record(_decode_snapshot(raw), step=step, cell=cell)
                    encoded = (json.dumps(row, sort_keys=True, separators=(",", ":"),
                                          allow_nan=False) + "\n").encode()
                    if trace.tell() + len(encoded) > int(plan["max_trace_bytes"]):
                        raise BridgeFailure("trace exceeded frozen byte cap")
                    trace.write(encoded)
                    step += 1
                    final_log = _flat_log(pufferl, backend, runner)
                    if "env/n" not in final_log and not startup_log_schema_path.exists():
                        write_json_atomic(startup_log_schema_path, {
                            "schema_version": 1,
                            "keys": sorted(str(key) for key in final_log),
                            "types": {str(key): type(value).__name__
                                      for key, value in sorted(final_log.items())},
                        })
                    current_games = completed_games(final_log, previous_games)
                    previous_games = current_games
                    games = current_games - start_games
                    if games == target:
                        break
                    if games > target:
                        raise BridgeFailure("cell completion overshot requested full games")
                missing = [key for key in HARD_INTEGRITY_KEYS if f"env/{key}" not in final_log]
                if missing:
                    raise BridgeFailure(f"cell lacks hard-integrity fields: {missing}")
                hard = {key: float(final_log[f"env/{key}"]) for key in HARD_INTEGRITY_KEYS}
                if any(not math.isfinite(v) or v != 0.0 for v in hard.values()):
                    raise BridgeFailure(f"cell hard-integrity failure: {hard}")
                for key in ("statmatch_term", "demo_episodes"):
                    value = float(final_log.get(f"env/{key}", float("nan")))
                    if not math.isfinite(value) or value != 0.0:
                        raise BridgeFailure(f"cell is not a natural kickoff completion: {key}={value}")
                backend.save_weights(runner, str(after))
                validate_serialized_weights(
                    before, after, str(plan["checkpoint_sha256"]))
                cell_results.append({**cell, "completed_full_games": target,
                                     "rollouts": rollouts, "hard_integrity": hard,
                                     "effective_config_sha256": effective_config_sha256})
            finally:
                backend.close(runner)
    if sha256_file(checkpoint) != plan["checkpoint_sha256"]:
        raise BridgeFailure("checkpoint bytes changed during evaluation")
    result = {
        "schema_version": 1, "arm": arm_name, "accepted": True,
        "module_sha256": module_sha, "rollout_transition_contract": actual_contract,
        "cuda_runtime_preflight": cuda_evidence, "checkpoint_sha256": plan["checkpoint_sha256"],
        "train_calls": 0, "actual_qualification_snapshot_calls": step,
        "trace": str(trace_path), "trace_bytes": trace_path.stat().st_size,
        "trace_sha256": sha256_file(trace_path), "cells": cell_results,
        "weights_before_sha256": sha256_file(before),
        "weights_after_sha256": sha256_file(after),
    }
    if startup_log_schema_path.exists():
        result["startup_log_schema_sha256"] = sha256_file(startup_log_schema_path)
    write_json_atomic(output / "WORKER_COMPLETE.json", result)
    return 0


def _load_trace(path: Path, expected_sha: str) -> list[dict[str, Any]]:
    if sha256_file(path) != expected_sha:
        raise BridgeFailure("worker trace SHA-256 mismatch")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def compare_traces(old: list[Mapping[str, Any]], new: list[Mapping[str, Any]],
                   *, atol: float, rtol: float) -> dict[str, Any]:
    if len(old) != len(new):
        raise BridgeFailure("runtime traces have different step counts")
    maxima = {field: 0.0 for field in NUMERIC_FIELDS}
    for index, (left, right) in enumerate(zip(old, new)):
        if left.get("step") != index or right.get("step") != index or left.get("cell") != right.get("cell"):
            raise BridgeFailure(f"trace alignment differs at step {index}")
        for field in EXACT_FIELDS:
            a, b = left["fields"][field], right["fields"][field]
            if (a["dtype"], a["shape"], a["sha256"]) != (b["dtype"], b["shape"], b["sha256"]):
                raise BridgeFailure(f"exact field {field} differs at step {index}")
        for field in NUMERIC_FIELDS:
            a, b = left["fields"][field], right["fields"][field]
            if a["dtype"] != b["dtype"] or a["shape"] != b["shape"]:
                raise BridgeFailure(f"numeric field {field} layout differs at step {index}")
            av = np.asarray(a["values"], dtype=np.float64)
            bv = np.asarray(b["values"], dtype=np.float64)
            error = float(np.max(np.abs(av - bv))) if av.size else 0.0
            maxima[field] = max(maxima[field], error)
            if not np.allclose(av, bv, atol=atol, rtol=rtol):
                raise BridgeFailure(f"numeric field {field} differs at step {index}: max={error}")
    return {"paired_steps": len(old), "max_abs_error": maxima,
            "exact_fields": list(EXACT_FIELDS), "numeric_fields": list(NUMERIC_FIELDS)}


def run_controller(plan_path: Path, output: Path) -> int:
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    validate_plan(plan)
    if output.exists():
        raise BridgeFailure(f"refusing to overwrite controller output: {output}")
    if sha256_file(Path(plan["checkpoint"])) != plan["checkpoint_sha256"]:
        raise BridgeFailure("checkpoint SHA-256 differs before bridge")
    output.mkdir(parents=True)
    script = Path(__file__).resolve()
    results = {}
    for arm in ("old", "new"):
        arm_output = output / arm
        subprocess.run(worker_command(script, plan_path, arm_output, arm),
                       cwd=plan["arms"][arm]["runtime_root"],
                       env=worker_environment(plan, arm), check=True)
        results[arm] = json.loads((arm_output / "WORKER_COMPLETE.json").read_text())
    if sha256_file(Path(plan["checkpoint"])) != plan["checkpoint_sha256"]:
        raise BridgeFailure("checkpoint SHA-256 differs after bridge")
    for arm, result in results.items():
        if (not result.get("accepted") or result.get("train_calls") != 0
                or result.get("module_sha256") != plan["arms"][arm]["expected_module_sha256"]
                or result.get("rollout_transition_contract") != plan["arms"][arm]["expected_contract"]
                or result.get("weights_before_sha256") != result.get("weights_after_sha256")):
            raise BridgeFailure(f"{arm} worker completion contract failed")
    old_configs = [cell.get("effective_config_sha256") for cell in results["old"]["cells"]]
    new_configs = [cell.get("effective_config_sha256") for cell in results["new"]["cells"]]
    if old_configs != new_configs or any(not SHA256_RE.fullmatch(str(item)) for item in old_configs):
        raise BridgeFailure("old and new effective cell configurations differ")
    old_trace = _load_trace(output / "old/TRACE.jsonl", results["old"]["trace_sha256"])
    new_trace = _load_trace(output / "new/TRACE.jsonl", results["new"]["trace_sha256"])
    comparison = compare_traces(old_trace, new_trace,
                                atol=float(plan["atol"]), rtol=float(plan["rtol"]))
    complete = {"schema_version": 1, "accepted": True,
                "plan_sha256": sha256_file(plan_path), "checkpoint_sha256": plan["checkpoint_sha256"],
                "arms": {name: sha256_file(output / name / "WORKER_COMPLETE.json") for name in results},
                "comparison": comparison,
                "effective_config_sha256": old_configs,
                "interpretation": "Qualification-only frozen-policy inference bridge; no lineage or promotion claim."}
    write_json_atomic(output / "BRIDGE_COMPLETE.json", complete)
    return 0


def make_plan(args: argparse.Namespace) -> dict[str, Any]:
    checkpoint = args.checkpoint.absolute()
    plan = {
        "schema_version": 1, "checkpoint": str(checkpoint),
        "checkpoint_sha256": args.checkpoint_sha256,
        "arms": {
            "old": {"runtime_root": str(args.old_runtime), "python": str(args.python),
                    "expected_module_sha256": args.old_module_sha256,
                    "expected_contract": "tail-bootstrap-v1"},
            "new": {"runtime_root": str(args.new_runtime), "python": str(args.python),
                    "expected_module_sha256": args.new_module_sha256,
                    "expected_contract": "terminal-aware-tbptt-v1"},
        },
        "styles": list(STYLES), "sides": list(SIDES), "seeds": args.seed,
        "games_per_seed": DEFAULT_GAMES_PER_SEED, "horizon": 1, "demo_reset_pct": 0,
        "policy": {"hidden_size": 512, "num_layers": 3},
        "environment_sha256": EXPECTED_ENVIRONMENT_SHA256, "cudart": str(args.cudart),
        "gpu_id": args.gpu_id, "max_decisions": args.max_decisions,
        "max_rollouts_per_cell": args.max_rollouts_per_cell,
        "max_trace_bytes": args.max_trace_bytes, "atol": args.atol, "rtol": args.rtol,
        "qualification_only": True, "lineage_promotion": False,
    }
    validate_plan(plan)
    return plan


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("--checkpoint", type=Path, required=True)
    freeze.add_argument("--checkpoint-sha256", required=True)
    freeze.add_argument("--old-runtime", type=Path, required=True)
    freeze.add_argument("--new-runtime", type=Path, required=True)
    freeze.add_argument("--python", type=Path, required=True)
    freeze.add_argument("--cudart", type=Path, required=True)
    freeze.add_argument("--old-module-sha256", required=True)
    freeze.add_argument("--new-module-sha256", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--seed", action="append", type=int, default=[])
    freeze.add_argument("--gpu-id", type=int, default=0)
    freeze.add_argument("--max-decisions", type=int, default=4096)
    freeze.add_argument("--max-rollouts-per-cell", type=int, default=8192)
    freeze.add_argument("--max-trace-bytes", type=int, default=DEFAULT_MAX_TRACE_BYTES)
    freeze.add_argument("--atol", type=float, default=1e-6)
    freeze.add_argument("--rtol", type=float, default=1e-6)
    run = sub.add_parser("run")
    run.add_argument("--plan", type=Path, required=True)
    run.add_argument("--output", type=Path, required=True)
    worker = sub.add_parser("worker")
    worker.add_argument("--plan", type=Path, required=True)
    worker.add_argument("--arm", choices=("old", "new"), required=True)
    worker.add_argument("--output", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "freeze":
        if not args.seed:
            args.seed = list(DEFAULT_SEEDS)
        plan = make_plan(args)
        if args.output.exists():
            raise BridgeFailure(f"refusing to overwrite plan: {args.output}")
        write_json_atomic(args.output, plan)
        print(json.dumps({"plan": str(args.output), "sha256": sha256_file(args.output)}, sort_keys=True))
        return 0
    if args.command == "worker":
        return run_worker(args.plan.absolute(), args.arm, args.output.absolute())
    return run_controller(args.plan.absolute(), args.output.absolute())


if __name__ == "__main__":
    raise SystemExit(main())
