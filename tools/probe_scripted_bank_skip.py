#!/usr/bin/env python3
"""Rig probe for the opt-in scripted-bank forward skip (audit S4).

    probe_scripted_bank_skip.py trace --puffer-root <tree> --output <json>
        [--rollouts N] -- <puffer train overrides>
    probe_scripted_bank_skip.py compare --baseline <json> --candidate <json>
    probe_scripted_bank_skip.py throughput --puffer-root <tree> --output <json>
        [--seconds 120] [--warmup-epochs 2] -- <puffer train overrides>

trace builds the trainer the way pufferl._train does (config plus overrides,
warm start, selfplay routing), runs rollouts only (no PPO update, so weights
never move), and digests every rollout tensor by bank slice. compare requires
two traces of one config to agree on observations, rewards, terminals, action
masks and env metrics, and on actions/logprobs/values of every bank except the
candidate's skipped bank, whose slice must be exactly zero. Run compare on two
default-build traces first: that control is what shows the rollout is
deterministic, so a candidate mismatch means the patch changed behavior.

throughput alternates rollouts and PPO updates over a wall-clock window and
records steps/second plus the dashboard's GPU/Env/Train split per epoch.
Every mode imports _C through the same in-process CUDA preflight as
tools/qualify_recurrent_cuda.py (D225). Nothing is written except --output.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import pathlib
import subprocess
import sys
import time
from typing import Any, Mapping, Sequence

import numpy as np

SCHEMA_VERSION = 1
PER_BANK = ("actions", "logprobs", "values")
ALL_ROWS = ("observations", "rewards", "terminals", "action_mask")
PERF_KEYS = ("rollout", "eval_gpu", "eval_env", "train_misc", "train_forward", "train")


class ProbeError(RuntimeError):
    pass


def bank_row_slices(layout: Sequence[int], agents_per_buffer: int,
                    num_buffers: int) -> list[list[tuple[int, int]]]:
    """Per bank, the global [start, end) rows it owns in each buffer."""
    layout = [int(v) for v in layout]
    if (len(layout) < 2 or layout[0] != 0 or layout[-1] != agents_per_buffer
            or any(b < a for a, b in zip(layout, layout[1:]))):
        raise ProbeError(f"bank layout {layout} does not tile {agents_per_buffer} rows")
    if num_buffers <= 0:
        raise ProbeError("num_buffers must be positive")
    return [[(f * agents_per_buffer + layout[k], f * agents_per_buffer + layout[k + 1])
             for f in range(num_buffers)] for k in range(len(layout) - 1)]


def digest_rows(array: np.ndarray, spans: Sequence[tuple[int, int]]) -> str:
    digest = hashlib.sha256()
    for start, end in spans:
        digest.update(np.ascontiguousarray(array[:, start:end]).tobytes())
    return digest.hexdigest()


def rollout_record(arrays: Mapping[str, np.ndarray], layout: Sequence[int],
                   agents_per_buffer: int, num_buffers: int) -> dict[str, Any]:
    slices = bank_row_slices(layout, agents_per_buffer, num_buffers)
    total = agents_per_buffer * num_buffers
    record: dict[str, Any] = {"all_rows": {}, "banks": []}
    for key in ALL_ROWS + PER_BANK:
        array = arrays.get(key)
        if array is None:
            raise ProbeError(f"snapshot lacks {key}")
        if array.size and (array.ndim < 2 or array.shape[1] != total):
            raise ProbeError(f"{key} shape {array.shape} is not (T, {total}, ...)")
    for key in ALL_ROWS:
        record["all_rows"][key] = digest_rows(arrays[key], [(0, total)])
    for bank, spans in enumerate(slices):
        entry: dict[str, Any] = {"bank": bank, "rows": sum(e - s for s, e in spans)}
        for key in PER_BANK:
            entry[key] = digest_rows(arrays[key], spans)
            entry[f"{key}_zero"] = all(
                not np.any(arrays[key][:, s:e]) for s, e in spans)
        record["banks"].append(entry)
    return record


def expected_skip_bank(config: Mapping[str, Any]) -> int:
    """The keying rule the patch compiles (src/scripted_bank_skip.h)."""
    env, vec = config.get("env", {}), config.get("vec", {})
    tag = int(env.get("scripted_bank_tag", 0) or 0)
    if (config.get("env_name") != "bloodbowl"
            or int(env.get("scripted_opponent", 0) or 0) == 0
            or int(env.get("scripted_opponent_team", 1)) != 1
            or not 1 <= tag <= int(vec.get("num_frozen_banks", 0) or 0)):
        return 0
    return tag


def _require_equal(label: str, left: Any, right: Any) -> None:
    if left != right:
        raise ProbeError(f"{label} differs: {left!r} != {right!r}")


def compare_traces(baseline: Mapping[str, Any], candidate: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("schema_version", "config", "bank_layout", "agents_per_buffer",
                "num_buffers", "requested_rollouts"):
        _require_equal(key, baseline.get(key), candidate.get(key))
    if baseline["skip"]["bank"] != 0:
        raise ProbeError("baseline must be a trace without the skip")
    skip = int(candidate["skip"]["bank"])
    if candidate["skip"]["binding"]:
        _require_equal("candidate skip bank vs config rule", skip,
                       expected_skip_bank(candidate["config"]))
        if skip and not candidate["skip"]["routed"]:
            raise ProbeError("candidate skip was never routing-validated")
    elif skip:
        raise ProbeError("candidate reports a skip without the binding")
    rollouts_a, rollouts_b = baseline["rollouts"], candidate["rollouts"]
    if not rollouts_a or len(rollouts_a) != len(rollouts_b):
        raise ProbeError("traces hold different rollout counts")
    compared = set()
    for index, (a, b) in enumerate(zip(rollouts_a, rollouts_b)):
        _require_equal(f"rollout {index} all-row digests", a["all_rows"], b["all_rows"])
        for bank_a, bank_b in zip(a["banks"], b["banks"], strict=True):
            bank = bank_a["bank"]
            if skip and bank == skip:
                for key in PER_BANK:
                    if not bank_b[f"{key}_zero"]:
                        raise ProbeError(f"rollout {index} skipped bank {bank} {key} not zero")
                if bank_a["values_zero"]:
                    raise ProbeError(
                        f"rollout {index} baseline bank {bank} values are zero; "
                        "the comparison cannot see the forward it removed")
                continue
            for key in PER_BANK:
                _require_equal(f"rollout {index} bank {bank} {key}", bank_a[key], bank_b[key])
            compared.add(bank)
    _require_equal("env metrics", baseline["env"], candidate["env"])
    return {"accepted": True, "rollouts": len(rollouts_a), "skip_bank": skip,
            "identical_banks": sorted(compared)}


def split_overrides(argv: Sequence[str]) -> tuple[list[str], list[str]]:
    argv = list(argv)
    if "--" in argv:
        at = argv.index("--")
        return argv[:at], argv[at + 1:]
    return argv, []


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str, sort_keys=True))


def _write_json(path: pathlib.Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                         encoding="utf-8")
    temporary.replace(path)


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_trainer(puffer_root: pathlib.Path, overrides: Sequence[str]):
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    from qualify_recurrent_cuda import _load_backend  # CUDART before _C (D225)

    _C, module, evidence = _load_backend(puffer_root)
    from pufferlib import pufferl as puffer_cli  # type: ignore
    from pufferlib import selfplay  # type: ignore

    saved = sys.argv
    sys.argv = ["puffer", *overrides]
    try:
        args = puffer_cli.load_config("bloodbowl")
    finally:
        sys.argv = saved
    puffer_cli.validate_config(args)
    puffer_cli.require_training_state_reset(args)
    puffer_cli.guard_scripted_training(args)
    pufferl = _C.create_pufferl(args)
    if args.get("load_model_path"):
        _C.load_weights(pufferl, str(args["load_model_path"]))
    selfplay.setup(pufferl, _C, args, f"probe-{os.getpid()}")
    skip = {"binding": hasattr(_C, "scripted_bank_skip"), "bank": 0, "routed": False,
            "module_attribute": bool(getattr(_C, "scripted_bank_forward_skip", False))}
    if skip["binding"]:
        state = _C.scripted_bank_skip(pufferl)
        skip.update(bank=int(state["bank"]), routed=bool(state["routed"]))
    identity = {"module": str(module), "module_sha256": _sha256(pathlib.Path(module)),
                "exact_action_source_hash": str(_C.exact_action_source_hash),
                "precision_bytes": int(_C.precision_bytes)}
    return _C, pufferl, args, skip, identity, evidence


def run_trace(options: argparse.Namespace, overrides: Sequence[str]) -> int:
    from qualify_recurrent_cuda import decode_snapshot, validate_hard_integrity

    _C, pufferl, args, skip, identity, evidence = load_trainer(
        pathlib.Path(options.puffer_root).resolve(), overrides)
    layout_state = _C.qualification_recurrent_state(pufferl, False)
    layout = [int(v) for v in layout_state["bank_layout"]]
    apb, buffers = int(layout_state["agents_per_buffer"]), int(layout_state["num_buffers"])
    rollouts = []
    for _ in range(options.rollouts):
        _C.rollouts(pufferl)
        rollouts.append(rollout_record(
            decode_snapshot(_C.qualification_snapshot(pufferl)), layout, apb, buffers))
    env = dict(_C.log(pufferl)["env"])
    payload = {
        "schema_version": SCHEMA_VERSION, "mode": "trace", "overrides": list(overrides),
        "config": _json_safe(args), "identity": identity, "cuda_runtime_preflight": evidence,
        "skip": skip, "bank_layout": layout, "agents_per_buffer": apb,
        "num_buffers": buffers, "requested_rollouts": options.rollouts,
        "rollouts": rollouts, "env": _json_safe(env),
        "hard_integrity": validate_hard_integrity(env),
    }
    _write_json(pathlib.Path(options.output), payload)
    print(json.dumps({"output": options.output, "skip": skip, "rollouts": len(rollouts)}))
    return 0


def _gpu_sample() -> dict[str, Any]:
    result = subprocess.run(
        ["nvidia-smi", "--query-gpu=temperature.gpu,power.draw,power.limit,utilization.gpu",
         "--format=csv,noheader,nounits"], text=True, capture_output=True, check=False,
        timeout=10)
    if result.returncode != 0:
        return {"error": result.stderr.strip()}
    temp, power, limit, util = (v.strip() for v in result.stdout.splitlines()[0].split(","))
    return {"temperature_c": float(temp), "power_w": float(power),
            "power_limit_w": float(limit), "utilization_percent": float(util)}


def per_epoch_split(perf: Mapping[str, Any], epochs: int) -> dict[str, float]:
    if epochs <= 0:
        raise ProbeError("no timed epochs")
    split = {f"{key}_ms": 1000.0 * float(perf[key]) / epochs for key in PERF_KEYS}
    if not all(math.isfinite(v) for v in split.values()):
        raise ProbeError("non-finite profile split")
    return split


def run_throughput(options: argparse.Namespace, overrides: Sequence[str]) -> int:
    from qualify_recurrent_cuda import validate_hard_integrity

    _C, pufferl, args, skip, identity, evidence = load_trainer(
        pathlib.Path(options.puffer_root).resolve(), overrides)
    for _ in range(options.warmup_epochs):
        _C.rollouts(pufferl)
        _C.train(pufferl)
    _C.log(pufferl)  # discard warmup accumulators
    start_step = int(pufferl.global_step)
    started = time.perf_counter()
    epochs = 0
    samples = []
    while time.perf_counter() - started < options.seconds:
        _C.rollouts(pufferl)
        _C.train(pufferl)
        epochs += 1
        if epochs % 10 == 1:
            samples.append(_gpu_sample())
    elapsed = time.perf_counter() - started
    steps = int(pufferl.global_step) - start_step
    log = _C.log(pufferl)
    env = dict(log["env"])
    payload = {
        "schema_version": SCHEMA_VERSION, "mode": "throughput", "overrides": list(overrides),
        "config": _json_safe(args), "identity": identity, "cuda_runtime_preflight": evidence,
        "skip": skip, "epochs": epochs, "steps": steps, "elapsed_seconds": elapsed,
        "steps_per_second": steps / elapsed, "split_per_epoch": per_epoch_split(log["perf"], epochs),
        "perf_seconds": _json_safe(dict(log["perf"])), "util": _json_safe(dict(log["util"])),
        "gpu_samples": samples, "hard_integrity": validate_hard_integrity(env),
    }
    _write_json(pathlib.Path(options.output), payload)
    print(json.dumps({"output": options.output, "skip": skip,
                      "steps_per_second": payload["steps_per_second"],
                      **payload["split_per_epoch"]}))
    return 0


def parse_args(argv: Sequence[str]) -> tuple[argparse.Namespace, list[str]]:
    own, overrides = split_overrides(argv)
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    commands = parser.add_subparsers(dest="command", required=True)
    trace = commands.add_parser("trace")
    trace.add_argument("--puffer-root", required=True)
    trace.add_argument("--output", required=True)
    trace.add_argument("--rollouts", type=int, default=4)
    compare = commands.add_parser("compare")
    compare.add_argument("--baseline", required=True)
    compare.add_argument("--candidate", required=True)
    throughput = commands.add_parser("throughput")
    throughput.add_argument("--puffer-root", required=True)
    throughput.add_argument("--output", required=True)
    throughput.add_argument("--seconds", type=float, default=120.0)
    throughput.add_argument("--warmup-epochs", type=int, default=2)
    options = parser.parse_args(own)
    if options.command != "compare" and not overrides:
        parser.error(f"{options.command} needs puffer train overrides after --")
    if options.command == "compare" and overrides:
        parser.error("compare takes no overrides")
    if getattr(options, "rollouts", 1) <= 0 or getattr(options, "seconds", 1.0) <= 0:
        parser.error("--rollouts and --seconds must be positive")
    return options, overrides


def main(argv: Sequence[str] | None = None) -> int:
    options, overrides = parse_args(sys.argv[1:] if argv is None else argv)
    if options.command == "compare":
        baseline = json.loads(pathlib.Path(options.baseline).read_text(encoding="utf-8"))
        candidate = json.loads(pathlib.Path(options.candidate).read_text(encoding="utf-8"))
        try:
            verdict = compare_traces(baseline, candidate)
        except ProbeError as exc:
            print(json.dumps({"accepted": False, "reason": str(exc)}))
            return 1
        print(json.dumps(verdict))
        return 0
    if options.command == "trace":
        return run_trace(options, overrides)
    return run_throughput(options, overrides)


if __name__ == "__main__":
    raise SystemExit(main())
