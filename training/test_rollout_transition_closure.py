"""Contracts for Puffer rollout tail transition closure."""

from __future__ import annotations

import importlib.util
import math
import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_rollout_transition_closure.patch"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
QUALIFIER = ROOT / "tools" / "qualify_recurrent_cuda.py"
SCREEN = ROOT / "tools" / "run_reward_screen.sh"
ABLATION = ROOT / "tools" / "run_reward_ablation.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
VERIFIER = ROOT / "training" / "verify_rollout_transition_closure.py"


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "verify_rollout_transition_closure",
        VERIFIER,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load rollout transition verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class RolloutTransitionPlanTests(unittest.TestCase):
    def _patch_text(self) -> str:
        self.assertTrue(
            PATCH.is_file(),
            "watched fail: rollout transition closure patch is missing",
        )
        return PATCH.read_text(encoding="utf-8")

    def _added_patch_text(self) -> str:
        """Return production lines added by the patch, excluding diff headers."""
        return "\n".join(
            line[1:]
            for line in self._patch_text().splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )

    def test_independent_oracle_closes_terminal_tail(self):
        verify = _load_verifier()
        result = verify.reference_advantages(
            values=[[1.0]],
            rewards=[[7.0]],
            terminals=[[1.0]],
            importance=[[0.5]],
            tail_values=[float("nan")],
            tail_rewards=[3.0],
            tail_terminals=[1.0],
            gamma=0.9,
            gae_lambda=0.8,
            rho_clip=1.0,
            c_clip=1.0,
        )
        self.assertEqual(result, [[1.0]])
        self.assertTrue(math.isfinite(result[0][0]))

    def test_independent_oracle_uses_zero_state_bootstrap_value(self):
        verify = _load_verifier()
        result = verify.reference_advantages(
            values=[[1.0]],
            rewards=[[7.0]],
            terminals=[[1.0]],
            importance=[[0.5]],
            tail_values=[2.0],
            tail_rewards=[3.0],
            tail_terminals=[0.0],
            gamma=0.9,
            gae_lambda=0.8,
            rho_clip=1.0,
            c_clip=1.0,
        )
        self.assertAlmostEqual(result[0][0], 1.9)

    def test_independent_oracle_counts_native_slot_zero_duplicate_once(self):
        verify = _load_verifier()
        common = {
            "gamma": 1.0,
            "gae_lambda": 0.0,
            "rho_clip": 1.0,
            "c_clip": 1.0,
        }
        first = verify.reference_advantages(
            values=[[0.0]],
            rewards=[[0.0]],
            terminals=[[0.0]],
            importance=[[1.0]],
            tail_values=[0.0],
            tail_rewards=[3.0],
            tail_terminals=[1.0],
            **common,
        )
        second = verify.reference_advantages(
            values=[[0.0]],
            rewards=[[3.0]],
            terminals=[[1.0]],
            importance=[[1.0]],
            tail_values=[0.0],
            tail_rewards=[0.0],
            tail_terminals=[1.0],
            **common,
        )
        self.assertEqual(first, [[3.0]])
        self.assertEqual(second, [[0.0]])

    def test_patch_exists_before_source_contracts_run(self):
        self.assertTrue(
            PATCH.is_file(),
            "watched fail: rollout transition closure patch is missing",
        )

    def test_patch_closes_every_advantage_path(self):
        patch = self._added_patch_text()
        for fragment in (
            "tail-bootstrap-v1",
            "tail_observations",
            "tail_rewards",
            "tail_terminals",
            "tail_values",
            "tail_callback_wrapper",
            "tail_activations",
            "tail_states",
            "for (int t = horizon - 1; t >= 0; t--)",
            "rho_t * (next_reward + bootstrap -",
        ):
            self.assertIn(fragment, patch)
        self.assertGreaterEqual(
            patch.count("rho_t * (next_reward + bootstrap -"),
            3,
            "CPU, CUDA scalar, and CUDA vector paths must share V-trace law",
        )

    def test_patch_uses_zero_state_scratch_and_worker_stream_order(self):
        patch = self._patch_text()
        for fragment in (
            "puf_zero(&tail_state",
            "tail_callback(ctx, buf)",
            "cudaStreamSynchronize(stream)",
            "reset_state && !pufferl->evaluation_mode",
        ):
            self.assertIn(fragment, patch)
        tail_call = patch.index("tail_callback(ctx, buf)")
        final_sync = patch.index("cudaStreamSynchronize(stream)", tail_call)
        self.assertLess(tail_call, final_sync)

    def test_patch_branches_terminal_before_bootstrap_arithmetic(self):
        patch = self._added_patch_text()
        self.assertIn("nextnonterminal ? gamma * next_value : 0.0f", patch)
        self.assertNotIn(
            "gamma * next_value * nextnonterminal",
            patch,
            "zero times NaN/Inf is not a terminal mask",
        )

    def test_patch_owns_graph_enabled_and_disabled_teardown(self):
        patch = self._added_patch_text()
        for fragment in (
            "train_cudagraph = nullptr",
            "train_captured = false",
            "fused_rollout_cudagraphs = nullptr",
            "tail_rollout_cudagraphs = nullptr",
            "pufferl.train_captured && pufferl.train_cudagraph != nullptr",
            "if (pufferl.fused_rollout_cudagraphs != nullptr)",
            "if (pufferl.tail_rollout_cudagraphs != nullptr)",
        ):
            self.assertIn(fragment, patch)

    def test_verifier_executes_real_torch_rollout_contract(self):
        verifier = VERIFIER.read_text(encoding="utf-8")
        for fragment in (
            "verify_torch_rollout_contract",
            "training policy forward count",
            "evaluation policy forward count",
            "fresh zero recurrent state",
            "post-final-action observation",
        ):
            self.assertIn(fragment, verifier)

    def test_installer_applies_transition_between_recurrent_and_frozen(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertTrue(
            "puffer_rollout_transition_closure.patch" in installer,
            "installer is missing the rollout transition patch",
        )
        recurrent = installer.index("puffer_recurrent_eval_state.patch")
        transition = installer.index("puffer_rollout_transition_closure.patch")
        frozen = installer.index("puffer_frozen_prio_mask.patch")
        strict = installer.index("puffer_strict_environment_config.patch")
        self.assertLess(recurrent, transition)
        self.assertLess(transition, frozen)
        self.assertLess(frozen, strict)
        self.assertIn(
            'apply --reverse --check --no-index "$ROLLOUT_TRANSITION_PATCH"',
            installer,
        )

    def test_module_and_patch_identity_are_fail_closed(self):
        qualifier = QUALIFIER.read_text(encoding="utf-8")
        for fragment in (
            "ROLLOUT_TRANSITION_CONTRACT",
            "tail-bootstrap-v1",
            "rollout_transition_contract",
            "ROLLOUT_TRANSITION_PATCH",
            '"rollout_transition_patch"',
        ):
            self.assertTrue(
                fragment in qualifier,
                f"qualifier identity is missing {fragment!r}",
            )

    def test_experiment_bundles_use_the_same_causal_order(self):
        for path in (SCREEN, ABLATION):
            source = path.read_text(encoding="utf-8")
            self.assertTrue(
                "puffer_rollout_transition_closure.patch" in source,
                f"{path.name} is missing the rollout transition patch",
            )
            recurrent = source.index("puffer_recurrent_eval_state.patch")
            transition = source.index("puffer_rollout_transition_closure.patch")
            frozen = source.index("puffer_frozen_prio_mask.patch")
            self.assertLess(recurrent, transition, path.name)
            self.assertLess(transition, frozen, path.name)

    def test_ci_runs_verifier_against_built_cpu_extension(self):
        workflow = CI.read_text(encoding="utf-8")
        self.assertTrue(
            "training/verify_rollout_transition_closure.py --device cpu"
            in workflow,
            "CPU CI does not run the applied-Puffer transition verifier",
        )


if __name__ == "__main__":
    unittest.main()
