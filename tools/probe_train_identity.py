#!/usr/bin/env python3
"""Same-seed training identity probe for two Puffer builds.

Runs N alternating rollout + PPO epochs on one build from a fixed seed and warm
checkpoint, saves the learner weights at chosen epochs and records their
sha256. Two builds that claim to train identically (for example the default
tree against a tree with the blitz reachability fast path, the scripted-bank
forward skip or the deciding-row telemetry patch) must produce the same digest
at every saved epoch.

  probe_train_identity.py run --puffer-root TREE --output OUT.json \
      --epochs 24 --save-at 1,8,16,24 --weights-dir DIR -- <trainer overrides>
  probe_train_identity.py compare --baseline A.json --candidate B.json

The frozen banks bootstrap from the warm learner (no league preseed), so the
probe reads and writes no pool. Hold the GPU lock around `run`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import sys
from typing import Any, Sequence

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from probe_scripted_bank_skip import (  # noqa: E402
    _json_safe, _write_json, integrity_verdict, load_trainer, split_overrides)

SCHEMA_VERSION = 1


def _sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_save_at(text: str, epochs: int) -> list[int]:
    points = sorted({int(part) for part in text.split(",") if part.strip()})
    if not points or points[0] < 1 or points[-1] > epochs:
        raise SystemExit(f"--save-at must list epochs within 1..{epochs}, got {text!r}")
    return points


def run(options: argparse.Namespace, overrides: Sequence[str]) -> int:
    save_at = parse_save_at(options.save_at, options.epochs)
    weights_dir = pathlib.Path(options.weights_dir)
    weights_dir.mkdir(parents=True, exist_ok=True)
    _C, pufferl, args, skip, identity, evidence = load_trainer(
        pathlib.Path(options.puffer_root).resolve(), overrides)
    checkpoints = []
    for epoch in range(1, options.epochs + 1):
        _C.rollouts(pufferl)
        _C.train(pufferl)
        if epoch in save_at:
            path = weights_dir / f"epoch-{epoch:04d}.bin"
            _C.save_weights(pufferl, str(path))
            checkpoints.append({"epoch": epoch, "agent_steps": int(pufferl.global_step),
                                "bytes": path.stat().st_size, "sha256": _sha256(path)})
    log = _C.log(pufferl)
    losses = {key: float(value).hex() for key, value in dict(log.get("loss", {})).items()
              if isinstance(value, (int, float))}
    env = dict(log["env"])
    payload = {
        "schema_version": SCHEMA_VERSION, "mode": "train-identity",
        "overrides": list(overrides), "config": _json_safe(args), "identity": identity,
        "cuda_runtime_preflight": evidence, "skip": skip, "epochs": options.epochs,
        "checkpoints": checkpoints, "final_loss_hex": losses,
        "hard_integrity": integrity_verdict(env),
        # The env's own panel, so a run can show what the env did and not only
        # what it was asked to do (end_turn_removed under no_early_end_turn).
        "env": _json_safe(env),
    }
    _write_json(pathlib.Path(options.output), payload)
    print(json.dumps({"output": options.output, "skip": skip, "checkpoints": checkpoints,
                      "hard_integrity_zero": payload["hard_integrity"].get("zero"),
                      "episodes": env.get("n"),
                      "end_turn_removed": env.get("end_turn_removed"),
                      "truncated_episodes": env.get("truncated_episodes")}))
    return 0


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    base = {c["epoch"]: c for c in baseline["checkpoints"]}
    cand = {c["epoch"]: c for c in candidate["checkpoints"]}
    if sorted(base) != sorted(cand):
        raise SystemExit(f"saved epochs differ: {sorted(base)} vs {sorted(cand)}")
    if baseline["overrides"] != candidate["overrides"]:
        raise SystemExit("trainer overrides differ between the two runs")
    rows = [{"epoch": epoch, "agent_steps": base[epoch]["agent_steps"],
             "identical": base[epoch]["sha256"] == cand[epoch]["sha256"]
             and base[epoch]["agent_steps"] == cand[epoch]["agent_steps"],
             "baseline": base[epoch]["sha256"][:16], "candidate": cand[epoch]["sha256"][:16]}
            for epoch in sorted(base)]
    integrity = bool(baseline["hard_integrity"].get("zero")) and bool(
        candidate["hard_integrity"].get("zero"))
    stock = ("policy", "value", "entropy", "kl", "old_kl", "clipfrac", "total")
    loss_equal = all(baseline["final_loss_hex"].get(key) == candidate["final_loss_hex"].get(key)
                     for key in stock if key in baseline["final_loss_hex"])
    return {"accepted": all(row["identical"] for row in rows) and integrity,
            "checkpoints": rows, "hard_integrity_zero_both": integrity,
            "final_stock_losses_identical": loss_equal,
            "baseline_module": baseline["identity"]["module_sha256"][:16],
            "candidate_module": candidate["identity"]["module_sha256"][:16]}


def main(argv: Sequence[str] | None = None) -> int:
    own, overrides = split_overrides(list(sys.argv[1:] if argv is None else argv))
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    runner = commands.add_parser("run")
    runner.add_argument("--puffer-root", required=True)
    runner.add_argument("--output", required=True)
    runner.add_argument("--weights-dir", required=True)
    runner.add_argument("--epochs", type=int, default=24)
    runner.add_argument("--save-at", default="1,8,16,24")
    comparer = commands.add_parser("compare")
    comparer.add_argument("--baseline", required=True)
    comparer.add_argument("--candidate", required=True)
    options = parser.parse_args(own)
    if options.command == "run":
        return run(options, overrides)
    result = compare(json.loads(pathlib.Path(options.baseline).read_text()),
                     json.loads(pathlib.Path(options.candidate).read_text()))
    print(json.dumps(result))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
