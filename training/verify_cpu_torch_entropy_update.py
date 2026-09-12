#!/usr/bin/env python3
"""Execute a small, deterministic entropy update through Torch PuffeRL.train.

This verifier deliberately makes a narrow claim.  It runs the selected
checkout's real CPU ``PuffeRL.train`` implementation from cloned scalar-policy
weights and proves that changing only the declared entropy coefficient changes
the gradient-driven SGD update by the independently calculated amount.  The
comparison is repeated at the first, middle, and last legal cosine-schedule
updates.  It is not a replacement for the larger CUDA/F5 qualification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from typing import Any


SCHEMA_VERSION = 1
CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"
TOTAL_UPDATES = 20
UPDATE_INDICES = (0, 10, 19)
BASE_COEFFICIENT = 0.2
MIN_RATIO = 0.1
THETA = 0.4
LEARNING_RATE = 0.05


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def expected_schedule(index: int, coefficient: float) -> float:
    floor = coefficient * MIN_RATIO
    progress = index / TOTAL_UPDATES
    real = floor + 0.5 * (coefficient - floor) * (
        1.0 + math.cos(math.pi * progress)
    )
    import struct
    return struct.unpack("<f", struct.pack("<f", real))[0]


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = args.puffer_root.resolve()
    source = root / "pufferlib" / "torch_pufferl.py"
    if not source.is_file():
        raise RuntimeError(f"missing Torch trainer source: {source}")
    sys.path.insert(0, str(root))
    from pufferlib import _C  # type: ignore
    import torch
    import pufferlib.torch_pufferl as tp  # type: ignore

    if bool(_C.gpu) or int(_C.precision_bytes) != 4:
        raise RuntimeError("verification requires a CPU float32 Puffer extension")
    if tp.ENTROPY_SCHEDULE_CONTRACT != CONTRACT:
        raise RuntimeError("unexpected entropy schedule contract")

    class Policy(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.theta = torch.nn.Parameter(torch.tensor(THETA))

        def forward(self, obs):
            rows = obs.numel()
            logits = torch.stack((self.theta.expand(rows),
                                  torch.zeros(rows)), dim=1)
            return [logits], torch.zeros(rows)

        def initial_state(self, batch_size, device):
            del batch_size, device
            return ()

        def forward_eval(self, obs, state):
            rows = obs.shape[0]
            logits = torch.stack((self.theta.expand(rows),
                                  torch.zeros(rows)), dim=1)
            return [logits], torch.zeros((rows, 1)), state

    class Profile:
        def mark(self, _index): pass
        def elapsed(self, *_args): pass

    original_advantage = tp.compute_puff_advantage
    original_multinomial = torch.multinomial

    def fixed_advantage(_val, _rew, _ter, _ratio, _tail_val, _tail_rew,
                        _tail_ter, out, _gamma, _gae, _rho, _c):
        out.copy_(torch.tensor([[1.0, -1.0]], dtype=torch.float32))
        return out

    def fixed_multinomial(input, num_samples, replacement=False, **_kwargs):
        # PuffeRL's priority sampler selects the only agent segment.  Keep all
        # other uses delegated so this fixture cannot mask an unexpected call.
        if input.ndim == 1 and input.numel() == 1 and num_samples == 1:
            return torch.zeros(1, dtype=torch.long)
        return original_multinomial(input, num_samples, replacement=replacement)

    def one(index: int, coefficient: float) -> dict[str, Any]:
        policy = Policy()
        trainer = object.__new__(tp.PuffeRL)
        trainer.profile = Profile()
        trainer.reset_state = True
        trainer.evaluation_mode = False
        trainer.epoch = index
        trainer.total_epochs = TOTAL_UPDATES
        trainer.tail_valid = True
        trainer.segment_state_valid = True
        trainer.segment_initial_state = ()
        trainer.entropy_config = {
            "base_coefficient": coefficient,
            "anneal_enabled": True,
            "min_coefficient_ratio": MIN_RATIO,
        }
        trainer.config = {
            "prio_beta0": 0.0, "prio_alpha": 0.0,
            "clip_coef": 0.2, "vf_clip_coef": 0.2,
            "learning_rate": LEARNING_RATE, "anneal_lr": False,
            "min_lr_ratio": 1.0, "gamma": 0.995,
            "gae_lambda": 0.95, "vtrace_rho_clip": 1.0,
            "vtrace_c_clip": 1.0, "vf_coef": 0.0,
            "max_grad_norm": 1.0e6,
        }
        trainer.device = torch.device("cpu")
        trainer.total_agents = 1
        trainer.minibatch_segments = 1
        trainer.num_minibatches = 1
        trainer.mask_size = 0
        trainer.act_sizes_list = [2]
        trainer.observations = torch.zeros((2, 1, 1))
        trainer.actions = torch.tensor([[[0]], [[1]]], dtype=torch.int64)
        trainer.values = torch.zeros((2, 1))
        with torch.no_grad():
            logits, _ = policy(torch.zeros((2, 1)))
            _, old_lp, _ = tp.sample_logits(logits, action=trainer.actions[:, 0])
        trainer.logprobs = old_lp.reshape(2, 1)
        trainer.rewards = torch.zeros((2, 1))
        trainer.terminals = torch.zeros((2, 1))
        trainer.recurrent_reset_masks = torch.zeros((2, 1))
        trainer.action_masks = None
        trainer.ratio = torch.ones((1, 2))
        trainer.tail_values = torch.zeros(1)
        trainer.tail_rewards = torch.zeros(1)
        trainer.tail_terminals = torch.zeros(1)
        trainer.policy = policy
        trainer.optimizer = torch.optim.SGD(policy.parameters(), lr=LEARNING_RATE)
        trainer._train_log_interval = None
        trainer._training_failed = False
        before = float(policy.theta.detach())
        tp.PuffeRL.train(trainer)
        after = float(policy.theta.detach())
        return {
            "update_index": index,
            "declared_coefficient": coefficient,
            "applied_coefficient": trainer.losses["entropy_coefficient"],
            "theta_before": before,
            "theta_after": after,
            "theta_delta": after - before,
            "entropy": trainer.losses["entropy"],
            "entropy_term": trainer.losses["entropy_term"],
            "total_loss": trainer.losses["total_loss"],
            "finite": all(math.isfinite(float(v)) for v in trainer.losses.values()),
            "tail_consumed": trainer.tail_valid is False,
            "segment_consumed": trainer.segment_state_valid is False,
            "epoch_advanced": trainer.epoch == index + 1,
        }

    tp.compute_puff_advantage = fixed_advantage
    torch.multinomial = fixed_multinomial
    try:
        cells = []
        p = 1.0 / (1.0 + math.exp(-THETA))
        entropy_derivative = p * (1.0 - p) * math.log((1.0 - p) / p)
        for index in UPDATE_INDICES:
            zero = one(index, 0.0)
            positive = one(index, BASE_COEFFICIENT)
            expected_coefficient = expected_schedule(index, BASE_COEFFICIENT)
            observed_effect = positive["theta_delta"] - zero["theta_delta"]
            expected_effect = LEARNING_RATE * expected_coefficient * entropy_derivative
            tolerance = 2.0e-7
            passed = (
                zero["finite"] and positive["finite"]
                and zero["tail_consumed"] and positive["tail_consumed"]
                and zero["segment_consumed"] and positive["segment_consumed"]
                and zero["epoch_advanced"] and positive["epoch_advanced"]
                and abs(zero["applied_coefficient"]) <= 1.0e-12
                and abs(positive["applied_coefficient"] - expected_coefficient) <= 1.0e-8
                and abs(observed_effect - expected_effect) <= tolerance
                and abs(observed_effect) > tolerance
            )
            cells.append({
                "update_index": index,
                "zero": zero,
                "positive": positive,
                "observed_entropy_update_effect": observed_effect,
                "expected_entropy_update_effect": expected_effect,
                "absolute_error": abs(observed_effect - expected_effect),
                "tolerance": tolerance,
                "passed": passed,
            })
    finally:
        tp.compute_puff_advantage = original_advantage
        torch.multinomial = original_multinomial

    extension = Path(_C.__file__).resolve()
    commit = args.puffer_git_commit
    if commit is None:
        commit = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True).stdout.strip()
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "claim": "cpu-torch-real-train-entropy-gradient-and-sgd-update-v1",
        "scope_limit": "Does not qualify CUDA/native parity or the full F5 surface.",
        "identity": {
            "verifier_sha256": sha256(Path(__file__).resolve()),
            "puffer_root": str(root), "puffer_git_commit": commit,
            "torch_pufferl_sha256": sha256(source),
            "extension_path": str(extension), "extension_sha256": sha256(extension),
            "extension_env_name": str(_C.env_name), "extension_gpu": bool(_C.gpu),
            "extension_precision_bytes": int(_C.precision_bytes),
            "torch_version": torch.__version__,
        },
        "fixture": {"theta": THETA, "learning_rate": LEARNING_RATE,
                    "total_updates": TOTAL_UPDATES, "update_indices": list(UPDATE_INDICES),
                    "base_coefficient": BASE_COEFFICIENT,
                    "min_coefficient_ratio": MIN_RATIO,
                    "minibatches_per_update": 1,
                    "forced_agent_segments": [0]},
        "cells": cells,
        "passed": all(cell["passed"] for cell in cells),
    }
    if not evidence["passed"]:
        raise RuntimeError("one or more entropy update cells failed")
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--puffer-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--puffer-git-commit")
    args = parser.parse_args()
    evidence = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": True, "output": str(args.output),
                      "cells": len(evidence["cells"])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
