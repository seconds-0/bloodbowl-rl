#!/usr/bin/env python3
"""Executable oracle for Puffer's tail-bootstrap-v1 transition contract.

The repository owns a patch against pinned PufferLib rather than a vendored
Puffer checkout. Unit tests exercise the independent scalar oracle here. CI and
local qualification call this file with the checkout-local interpreter after
building the applied Puffer CPU or CUDA extension.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Sequence
from typing import Any


CONTRACT = "tail-bootstrap-v1"


def _matrix(
    values: Sequence[Sequence[float]],
    label: str,
) -> tuple[list[list[float]], int, int]:
    rows = [[float(value) for value in row] for row in values]
    if not rows or not rows[0]:
        raise ValueError(f"{label} must be a non-empty matrix")
    horizon = len(rows[0])
    if any(len(row) != horizon for row in rows):
        raise ValueError(f"{label} rows must have equal length")
    return rows, len(rows), horizon


def _vector(
    values: Sequence[float],
    rows: int,
    label: str,
) -> list[float]:
    result = [float(value) for value in values]
    if len(result) != rows:
        raise ValueError(f"{label} must have one value per row")
    return result


def _clamp_reward(value: float) -> float:
    return max(-8.0, min(8.0, value))


def reference_advantages(
    *,
    values: Sequence[Sequence[float]],
    rewards: Sequence[Sequence[float]],
    terminals: Sequence[Sequence[float]],
    importance: Sequence[Sequence[float]],
    tail_values: Sequence[float],
    tail_rewards: Sequence[float],
    tail_terminals: Sequence[float],
    gamma: float,
    gae_lambda: float,
    rho_clip: float,
    c_clip: float,
) -> list[list[float]]:
    """Implementation used by verification; kept simple for auditability."""

    val, rows, horizon = _matrix(values, "values")
    rew, rew_rows, rew_horizon = _matrix(rewards, "rewards")
    done, done_rows, done_horizon = _matrix(terminals, "terminals")
    imp, imp_rows, imp_horizon = _matrix(importance, "importance")
    for label, shape in (
        ("rewards", (rew_rows, rew_horizon)),
        ("terminals", (done_rows, done_horizon)),
        ("importance", (imp_rows, imp_horizon)),
    ):
        if shape != (rows, horizon):
            raise ValueError(f"{label} shape differs from values")

    tail_val = _vector(tail_values, rows, "tail_values")
    tail_rew = _vector(tail_rewards, rows, "tail_rewards")
    tail_done = _vector(tail_terminals, rows, "tail_terminals")
    advantages = [[0.0] * horizon for _ in range(rows)]
    for row in range(rows):
        next_value = tail_val[row]
        next_reward = _clamp_reward(tail_rew[row])
        next_done = tail_done[row]
        trace_accumulator = 0.0
        for timestep in range(horizon - 1, -1, -1):
            nonterminal = next_done == 0.0
            rho = min(imp[row][timestep], float(rho_clip))
            trace = min(imp[row][timestep], float(c_clip))
            bootstrap = float(gamma) * next_value if nonterminal else 0.0
            delta = rho * (
                next_reward + bootstrap - val[row][timestep]
            )
            trace_accumulator = delta + (
                float(gamma)
                * float(gae_lambda)
                * trace
                * trace_accumulator
                if nonterminal
                else 0.0
            )
            advantages[row][timestep] = trace_accumulator
            next_value = val[row][timestep]
            next_reward = _clamp_reward(rew[row][timestep])
            next_done = done[row][timestep]
    return advantages


def _tensor_rows(tensor: Any) -> list[list[float]]:
    return [
        [float(value) for value in row]
        for row in tensor.detach().cpu().tolist()
    ]


def backend_advantages(
    backend: Any,
    torch: Any,
    *,
    device: str,
    values: Sequence[Sequence[float]],
    rewards: Sequence[Sequence[float]],
    terminals: Sequence[Sequence[float]],
    importance: Sequence[Sequence[float]],
    tail_values: Sequence[float],
    tail_rewards: Sequence[float],
    tail_terminals: Sequence[float],
    gamma: float,
    gae_lambda: float,
    rho_clip: float,
    c_clip: float,
) -> list[list[float]]:
    """Call the applied Puffer extension's tail-aware advantage entry point."""

    tensors = [
        torch.tensor(value, dtype=torch.float32, device=device).contiguous()
        for value in (
            values,
            rewards,
            terminals,
            importance,
            tail_values,
            tail_rewards,
            tail_terminals,
        )
    ]
    val, rew, done, imp, tail_val, tail_rew, tail_done = tensors
    advantages = torch.full_like(val, float("nan"))
    function_name = "puff_advantage" if device == "cuda" else "puff_advantage_cpu"
    function = getattr(backend, function_name)
    function(
        val.data_ptr(),
        rew.data_ptr(),
        done.data_ptr(),
        imp.data_ptr(),
        tail_val.data_ptr(),
        tail_rew.data_ptr(),
        tail_done.data_ptr(),
        advantages.data_ptr(),
        val.shape[0],
        val.shape[1],
        gamma,
        gae_lambda,
        rho_clip,
        c_clip,
    )
    if device == "cuda":
        torch.cuda.synchronize()
    return _tensor_rows(advantages)


def _assert_close(
    actual: Sequence[Sequence[float]],
    expected: Sequence[Sequence[float]],
    *,
    atol: float = 1.0e-6,
) -> None:
    if len(actual) != len(expected):
        raise AssertionError("row count differs")
    for row, (actual_row, expected_row) in enumerate(zip(actual, expected)):
        if len(actual_row) != len(expected_row):
            raise AssertionError(f"row {row} length differs")
        for timestep, (actual_value, expected_value) in enumerate(
            zip(actual_row, expected_row)
        ):
            if not math.isfinite(actual_value):
                raise AssertionError(
                    f"advantage[{row}][{timestep}] is not finite: {actual_value}"
                )
            if not math.isclose(
                actual_value,
                expected_value,
                rel_tol=0.0,
                abs_tol=atol,
            ):
                raise AssertionError(
                    f"advantage[{row}][{timestep}] differs: "
                    f"{actual_value} != {expected_value}"
                )


def verification_cases() -> list[dict[str, Any]]:
    common = {
        "gamma": 0.9,
        "gae_lambda": 0.8,
        "rho_clip": 1.0,
        "c_clip": 1.0,
    }
    terminal_cases = []
    for name, ignored_value in (
        ("terminal-tail-nan-h1", float("nan")),
        ("terminal-tail-posinf-h1", float("inf")),
        ("terminal-tail-neginf-h1", float("-inf")),
    ):
        terminal_cases.append({
            "name": name,
            "values": [[1.0]],
            "rewards": [[7.0]],
            "terminals": [[1.0]],
            "importance": [[0.5]],
            "tail_values": [ignored_value],
            "tail_rewards": [3.0],
            "tail_terminals": [1.0],
            **common,
        })
    return terminal_cases + [
        {
            "name": "positive-tail-clamp-h1",
            "values": [[1.0]],
            "rewards": [[0.0]],
            "terminals": [[0.0]],
            "importance": [[0.5]],
            "tail_values": [2.0],
            "tail_rewards": [99.0],
            "tail_terminals": [0.0],
            **common,
        },
        {
            "name": "negative-tail-clamp-h1",
            "values": [[1.0]],
            "rewards": [[0.0]],
            "terminals": [[0.0]],
            "importance": [[0.5]],
            "tail_values": [2.0],
            "tail_rewards": [-99.0],
            "tail_terminals": [0.0],
            **common,
        },
        {
            "name": "all-zero-h1",
            "values": [[0.0]],
            "rewards": [[0.0]],
            "terminals": [[0.0]],
            "importance": [[1.0]],
            "tail_values": [0.0],
            "tail_rewards": [0.0],
            "tail_terminals": [1.0],
            **common,
        },
        {
            "name": "nonterminal-tail-h1",
            "values": [[1.0]],
            "rewards": [[7.0]],
            "terminals": [[1.0]],
            "importance": [[0.5]],
            "tail_values": [2.0],
            "tail_rewards": [3.0],
            "tail_terminals": [0.0],
            **common,
        },
        {
            "name": "vector-width-h4",
            "values": [[0.5, 1.0, 1.5, 2.0]],
            "rewards": [[99.0, 0.25, -0.5, 1.0]],
            "terminals": [[1.0, 0.0, 0.0, 0.0]],
            "importance": [[0.3, 0.6, 0.8, 0.4]],
            "tail_values": [4.0],
            "tail_rewards": [2.0],
            "tail_terminals": [0.0],
            **common,
        },
        {
            "name": "bf16-vector-width-h8",
            "values": [[0.25 * value for value in range(1, 9)]],
            "rewards": [[99.0, 0.25, -0.5, 1.0, 1.25, -1.5, 2.0, -2.5]],
            "terminals": [[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]],
            "importance": [[0.3, 0.6, 0.8, 0.4, 0.7, 0.2, 0.9, 0.5]],
            "tail_values": [4.0],
            "tail_rewards": [2.0],
            "tail_terminals": [0.0],
            **common,
        },
        {
            "name": "scalar-width-h5",
            "values": [[0.5, 1.0, 1.5, 2.0, 2.5]],
            "rewards": [[99.0, 0.25, -0.5, 1.0, 1.25]],
            "terminals": [[1.0, 0.0, 0.0, 0.0, 0.0]],
            "importance": [[0.3, 0.6, 0.8, 0.4, 0.7]],
            "tail_values": [4.0],
            "tail_rewards": [2.0],
            "tail_terminals": [0.0],
            **common,
        },
    ]


def verify_backend(backend: Any, torch: Any, device: str) -> None:
    if int(getattr(backend, "precision_bytes", 0)) != 4:
        raise AssertionError(
            "rollout transition verifier requires a float32 backend"
        )
    if getattr(backend, "rollout_transition_contract", None) != CONTRACT:
        raise AssertionError(
            "compiled module does not advertise " f"{CONTRACT}"
        )
    for case in verification_cases():
        inputs = {key: value for key, value in case.items() if key != "name"}
        expected = reference_advantages(**inputs)
        actual = backend_advantages(
            backend,
            torch,
            device=device,
            **inputs,
        )
        _assert_close(actual, expected)

    # The native delayed slot-zero duplicate must not count a second time.
    first = verification_cases()[0]
    first_inputs = {key: value for key, value in first.items() if key != "name"}
    first_result = backend_advantages(
        backend,
        torch,
        device=device,
        **first_inputs,
    )
    second_inputs = {
        **first_inputs,
        "values": [[0.0]],
        "rewards": [[3.0]],
        "terminals": [[1.0]],
        "importance": [[1.0]],
        "tail_values": [0.0],
        "tail_rewards": [0.0],
        "tail_terminals": [1.0],
    }
    second_result = backend_advantages(
        backend,
        torch,
        device=device,
        **second_inputs,
    )
    if first_result[0][0] == 0.0 or second_result[0][0] != 0.0:
        raise AssertionError("tail outcome did not contribute exactly once")


def verify_torch_rollout_contract(torch: Any) -> None:
    """Exercise the patched real Torch collector with a deterministic fake vec."""

    from pufferlib.torch_pufferl import PuffeRL

    class NoopProfile:
        def mark(self, _index: int) -> None:
            pass

        def elapsed(self, _index: int, _start: int, _end: int) -> None:
            pass

    class StatefulPolicy(torch.nn.Module):
        def __init__(self, nan_values: bool = False) -> None:
            super().__init__()
            self.calls: list[tuple[Any, Any]] = []
            self.nan_values = nan_values

        def initial_state(self, batch: int, device: str = "cpu") -> tuple[Any, ...]:
            return (torch.zeros(1, batch, 1, device=device),)

        def forward_eval(self, observation: Any, state: tuple[Any, ...]):
            self.calls.append((
                observation.detach().clone(),
                state[0].detach().clone(),
            ))
            batch = observation.shape[0]
            logits = torch.tensor(
                [[100.0, -100.0]], device=observation.device
            ).expand(batch, -1)
            value = (
                observation.reshape(batch, -1)[:, :1].float()
                + 100.0 * state[0][0, :, :]
            )
            if self.nan_values:
                value = torch.full_like(value, float("nan"))
            return logits, value, (state[0] + 1.0,)

    class TensorVec:
        def __init__(self, horizon: int, terminal_at_boundary: bool) -> None:
            self.horizon = horizon
            self.terminal_at_boundary = terminal_at_boundary
            self.steps = 0
            self.observations = torch.zeros(1, 1)
            self.rewards = torch.zeros(1)
            self.terminals = torch.zeros(1)

        def cpu_step(self, _actions_ptr: int) -> None:
            self.steps += 1
            episode_step = ((self.steps - 1) % self.horizon) + 1
            at_boundary = episode_step == self.horizon
            self.rewards.fill_(3.0 if at_boundary else 0.0)
            self.terminals.fill_(
                1.0 if at_boundary and self.terminal_at_boundary else 0.0
            )
            if at_boundary and self.terminal_at_boundary:
                self.observations.zero_()
            else:
                self.observations.fill_(float(episode_step))

        def log(self) -> dict[str, float]:
            return {}

    def make_trainer(
        *,
        horizon: int,
        terminal_at_boundary: bool,
        evaluation_mode: bool,
        nan_values: bool = False,
    ) -> tuple[Any, TensorVec, StatefulPolicy]:
        vec = TensorVec(horizon, terminal_at_boundary)
        policy = StatefulPolicy(nan_values=nan_values)
        trainer = PuffeRL.__new__(PuffeRL)
        trainer.profile = NoopProfile()
        trainer.config = {"horizon": horizon}
        trainer.device = "cpu"
        trainer.total_agents = 1
        trainer.state = policy.initial_state(1)
        trainer.pending_rewards = torch.zeros(1)
        trainer.pending_terminals = torch.zeros(1)
        trainer.reset_state = True
        trainer.evaluation_mode = evaluation_mode
        trainer.vec_obs = vec.observations
        trainer.vec_rewards = vec.rewards
        trainer.vec_terminals = vec.terminals
        trainer.vec_joint_actions = None
        trainer.vec_action_mask = None
        trainer.action_masks = None
        trainer.observations = torch.zeros(horizon, 1, 1)
        trainer.actions = torch.zeros(horizon, 1, 1)
        trainer.logprobs = torch.zeros(horizon, 1)
        trainer.rewards = torch.zeros(horizon, 1)
        trainer.terminals = torch.zeros(horizon, 1)
        trainer.values = torch.zeros(horizon, 1)
        trainer.tail_rewards = torch.full((1,), float("nan"))
        trainer.tail_terminals = torch.full((1,), float("nan"))
        trainer.tail_values = torch.full((1,), float("nan"))
        trainer.policy = policy
        trainer._vec = vec
        trainer.gpu = False
        trainer.global_step = 0
        return trainer, vec, policy

    horizon = 2
    trainer, vec, policy = make_trainer(
        horizon=horizon,
        terminal_at_boundary=False,
        evaluation_mode=False,
    )
    trainer.rollouts()
    if vec.steps != horizon or trainer.global_step != horizon:
        raise AssertionError("training rollout executed an extra environment step")
    if len(policy.calls) != horizon + 1:
        raise AssertionError("training policy forward count is not horizon + 1")
    tail_observation, tail_state = policy.calls[-1]
    if float(tail_observation.item()) != float(horizon):
        raise AssertionError("tail pass did not use post-final-action observation")
    if not bool(torch.equal(tail_state, torch.zeros_like(tail_state))):
        raise AssertionError("tail pass did not use fresh zero recurrent state")
    if float(trainer.tail_rewards.item()) != 3.0:
        raise AssertionError("final reward was not captured in the training tail")
    if float(trainer.tail_terminals.item()) != 0.0:
        raise AssertionError("nonterminal training tail was marked terminal")
    if float(trainer.tail_values.item()) != float(horizon):
        raise AssertionError("tail value used live rather than zero recurrent state")
    if float(trainer.state[0].item()) != float(horizon):
        raise AssertionError("value-only tail replaced the live behavior state")

    terminal_trainer, terminal_vec, terminal_policy = make_trainer(
        horizon=horizon,
        terminal_at_boundary=True,
        evaluation_mode=False,
        nan_values=True,
    )
    terminal_trainer.rollouts()
    if terminal_vec.steps != horizon or len(terminal_policy.calls) != horizon + 1:
        raise AssertionError("terminal training rollout changed action count")
    if float(terminal_trainer.tail_terminals.item()) != 1.0:
        raise AssertionError("terminal training tail was not captured")
    if float(terminal_trainer.tail_values.item()) != 0.0:
        raise AssertionError("terminal nonfinite bootstrap was not selected to zero")

    eval_trainer, eval_vec, eval_policy = make_trainer(
        horizon=horizon,
        terminal_at_boundary=True,
        evaluation_mode=True,
    )
    eval_trainer.rollouts()
    first_calls = [
        (observation.clone(), state.clone())
        for observation, state in eval_policy.calls
    ]
    eval_trainer.rollouts()
    second_calls = eval_policy.calls[horizon:]
    if eval_vec.steps != 2 * horizon:
        raise AssertionError("evaluation rollout executed an extra environment step")
    if len(eval_policy.calls) != 2 * horizon:
        raise AssertionError("evaluation policy forward count is not horizon")
    if len(second_calls) != horizon:
        raise AssertionError("evaluation tail unexpectedly forwarded the policy")
    for first, second in zip(first_calls, second_calls):
        if not torch.equal(first[0], second[0]) or not torch.equal(
            first[1], second[1]
        ):
            raise AssertionError(
                "evaluation boundary behavior changed across identical episodes"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--device",
        choices=("cpu", "cuda"),
        default="cpu",
    )
    args = parser.parse_args()

    import torch
    from pufferlib import _C

    if args.device == "cuda" and not torch.cuda.is_available():
        raise SystemExit("CUDA verification requested but Torch CUDA is unavailable")
    verify_backend(_C, torch, args.device)
    verify_torch_rollout_contract(torch)
    print(f"rollout transition closure: OK ({args.device}; {CONTRACT})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
