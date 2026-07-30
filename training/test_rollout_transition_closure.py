"""Contracts for Puffer rollout tail transition closure."""

from __future__ import annotations

import importlib.util
import math
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_rollout_transition_closure.patch"
RECURRENT_PATCH = ROOT / "training" / "puffer_recurrent_eval_state.patch"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
QUALIFIER = ROOT / "tools" / "qualify_recurrent_cuda.py"
QUALIFICATION_PATCH = (
    ROOT / "training" / "puffer_recurrent_cuda_qualification.patch"
)
SCREEN = ROOT / "tools" / "run_reward_screen.sh"
ABLATION = ROOT / "tools" / "run_reward_ablation.sh"
CI = ROOT / ".github" / "workflows" / "ci.yml"
VERIFIER = ROOT / "training" / "verify_rollout_transition_closure.py"
SCRIPTED_GUARD_PATCH = (
    ROOT / "training" / "pufferl_scripted_training_guard.patch"
)


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

    def test_native_tail_callback_count_is_exact_not_boolean(self):
        patch = self._added_patch_text()
        self.assertIn("atomicAdd(valid + buf, 1)", patch)
        self.assertNotIn("valid[buf] = 1", patch)
        self.assertIn("if (valid != 1)", patch)

    def test_native_tail_record_cannot_be_silently_overwritten(self):
        transition = self._added_patch_text()
        full_patch = self._patch_text()
        qualification = QUALIFICATION_PATCH.read_text(encoding="utf-8")
        self.assertIn(
            "rollout would overwrite an unconsumed tail record",
            transition,
        )
        self.assertIn("qualification_consume_tail", qualification)
        self.assertIn(
            "training requires one valid tail record per rollout buffer",
            transition,
        )
        for fragment in (
            "training could not read tail-record validity",
            "training CUDA execution failed",
            "cudaStreamSynchronize(train_stream)",
        ):
            self.assertIn(fragment, transition)
        train_at = full_patch.index("train_impl(pufferl);")
        consume_at = full_patch.index(
            "consume_training_tail(pufferl);",
            train_at,
        )
        self.assertLess(
            train_at,
            consume_at,
            "the binding may consume the tail only after checked training completion",
        )

    def test_native_capture_warmup_does_not_leak_loss_or_profile_state(self):
        patch = self._patch_text()
        rng_at = patch.rindex("pufferl->rng_offset_puf.data")
        losses_at = patch.index(
            "pufferl->losses_puf.data",
            rng_at,
        )
        profile_at = patch.index(
            "memset(pufferl->profile.accum",
            losses_at,
        )
        global_step_at = patch.index(
            "         pufferl->global_step = 0;",
            profile_at,
        )
        self.assertLess(rng_at, losses_at)
        self.assertLess(losses_at, profile_at)
        self.assertLess(profile_at, global_step_at)

    def test_torch_tail_record_has_fail_closed_freshness_lifecycle(self):
        patch = self._added_patch_text()
        for fragment in (
            "self.tail_valid = False",
            "if self.tail_valid:",
            "rollout would overwrite an unconsumed tail record",
            "self.tail_valid = True",
            "if not self.tail_valid:",
            "training requires one fresh tail record",
        ):
            self.assertIn(fragment, patch)
        self.assertGreaterEqual(
            patch.count("self.tail_valid = False"),
            2,
            "Torch must initialize and consume its tail freshness token",
        )

    def test_tail_reset_loop_does_not_split_recurrent_patch_context(self):
        transition = self._patch_text()
        recurrent = RECURRENT_PATCH.read_text(encoding="utf-8")

        # The recurrent reset owns its complete hunk.  The transition patch
        # anchors the tail reset after the following epoch reset instead of
        # borrowing context from (and thereby splitting) that earlier hunk.
        self.assertIn("PrecisionTensor* bs = (bank == 0)", recurrent)
        self.assertNotIn("PrecisionTensor* bs = (bank == 0)", transition)
        self.assertIn(
            "         pufferl->epoch = 0;\n"
            "+        for (int bank = 0; "
            "bank < 1 + pufferl->num_frozen_banks; bank++) {",
            transition,
        )

    def test_verifier_executes_real_torch_rollout_contract(self):
        verifier = VERIFIER.read_text(encoding="utf-8")
        for fragment in (
            "verify_torch_rollout_contract",
            "training policy forward count",
            "evaluation policy forward count",
            "fresh zero recurrent state",
            "post-final-action observation",
            "trainer.epoch = 0",
            "trainer.total_epochs = 1",
            "trainer._entropy_gradient_qualification_enabled = False",
        ):
            self.assertIn(fragment, verifier)

    def test_verifier_feeds_collector_buffers_into_real_cpu_advantage(self):
        verifier = VERIFIER.read_text(encoding="utf-8")
        body = verifier[
            verifier.index("def verify_torch_rollout_contract("):
            verifier.index("def main()")
        ]
        for fragment in (
            "compute_puff_advantage",
            "collector_advantages",
            "trainer.values.T.contiguous()",
            "trainer.rewards.T.contiguous()",
            "trainer.terminals.T.contiguous()",
            "reference_advantages(",
            "initial_state_value=7.0",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, body)

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

    def test_installer_requires_exact_puffer_git_root_and_pinned_head(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        qualifier = QUALIFIER.read_text(encoding="utf-8")
        pin = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"
        self.assertIn(f'PINNED_PUFFER_COMMIT="{pin}"', installer)
        self.assertIn(f'PINNED_PUFFER_COMMIT = "{pin}"', qualifier)
        self.assertIn("rev-parse --show-toplevel", installer)
        self.assertIn('rev-parse --verify "HEAD^{commit}"', installer)
        guard_at = installer.index("rev-parse --show-toplevel")
        check_at = installer.index('if [ "$MODE" = "check" ]; then')
        self.assertLess(guard_at, check_at)

    def test_installer_wrong_head_rejects_install_and_check_before_mutation(self):
        with tempfile.TemporaryDirectory() as temporary:
            puffer = pathlib.Path(temporary) / "PufferLib"
            puffer.mkdir()
            (puffer / "build.sh").write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
            )
            subprocess.run(
                ["git", "init", "-q", str(puffer)],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(puffer), "config", "user.name", "Test"],
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(puffer),
                    "config",
                    "user.email",
                    "test@example.invalid",
                ],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(puffer), "add", "build.sh"],
                check=True,
            )
            subprocess.run(
                ["git", "-C", str(puffer), "commit", "-qm", "wrong pin"],
                check=True,
            )
            before = subprocess.run(
                ["git", "-C", str(puffer), "status", "--porcelain"],
                check=True,
                text=True,
                capture_output=True,
            ).stdout
            for extra in ((), ("--check",)):
                completed = subprocess.run(
                    ["bash", str(INSTALLER), *extra, str(puffer)],
                    text=True,
                    capture_output=True,
                    check=False,
                )
                with self.subTest(extra=extra):
                    self.assertEqual(completed.returncode, 1)
                    self.assertIn(
                        "PufferLib HEAD must be",
                        completed.stderr,
                    )
                    self.assertFalse((puffer / "ocean" / "bloodbowl").exists())
                    after = subprocess.run(
                        ["git", "-C", str(puffer), "status", "--porcelain"],
                        check=True,
                        text=True,
                        capture_output=True,
                    ).stdout
                    self.assertEqual(after, before)

    def test_frozen_priority_patch_install_state_machine_is_exact(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        block = installer.split(
            "# Frozen PPO rows must be mathematically ineligible for priority sampling;",
            1,
        )[1].split(
            "# Bounded CUDA qualification surfaces.",
            1,
        )[0]
        for fragment in (
            'if [ ! -f "$FROZEN_PRIO_PATCH" ]; then',
            "apply --reverse --check --no-index",
            'apply --check --no-index "$FROZEN_PRIO_PATCH"',
            'apply --no-index "$FROZEN_PRIO_PATCH"',
            "neither applicable nor installed",
            "installed frozen-row priority-mask patch is incomplete",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, block)
        self.assertGreaterEqual(
            block.count("apply --reverse --check --no-index"),
            2,
        )
        self.assertNotIn(
            'if [ -f "$FROZEN_PRIO_PATCH" ] &&',
            block,
        )
        final_block = installer.split(
            "for overlapping_patch in",
            1,
        )[1].split("done", 1)[0]
        self.assertIn('"$FROZEN_PRIO_PATCH"', final_block)

    def test_exact_and_recurrent_patches_are_fail_closed_across_install(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertNotIn(
            "--unidiff-zero",
            installer,
            "semantic patches must retain ordinary git-apply context checks",
        )
        check_block = installer.split(
            'if [ "$MODE" = "check" ]; then', 1
        )[1].split("exit 0", 1)[0]
        final_block = installer.split(
            "for overlapping_patch in", 1
        )[1].split("done", 1)[0]
        state_machine_blocks = {
            "EXACT_PATCH": installer.split(
                "# Exact semantic action identity.", 1
            )[1].split("# Recurrent evaluation contract.", 1)[0],
            "RECURRENT_PATCH": installer.split(
                "# Recurrent evaluation contract.", 1
            )[1].split("# Rollout-transition closure.", 1)[0],
        }

        for patch_var in ("EXACT_PATCH", "RECURRENT_PATCH"):
            with self.subTest(patch_var=patch_var, guard="check"):
                self.assertRegex(
                    check_block,
                    rf"for exact_patch in[\s\S]*\"\${patch_var}\"",
                )
            with self.subTest(patch_var=patch_var, guard="final"):
                self.assertIn(f'"${patch_var}"', final_block)

            state_machine = state_machine_blocks[patch_var]
            for fragment in (
                f'if [ ! -f "${patch_var}" ]; then',
                "apply --reverse --check --no-index",
                f'"${patch_var}"',
                'elif git -C "$PUFFER" apply --check --no-index',
                'git -C "$PUFFER" apply --no-index',
                "neither applicable nor installed",
                "installed",
                "incomplete",
            ):
                with self.subTest(
                    patch_var=patch_var,
                    guard="state-machine",
                    fragment=fragment,
                ):
                    self.assertIn(fragment, state_machine)
            self.assertGreaterEqual(
                state_machine.count("apply --reverse --check --no-index"),
                2,
                f"{patch_var} needs pre-state and post-apply reverse checks",
            )

    def test_tail_clamp_marker_cannot_masquerade_as_rollout_reward_patch(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn(
            "'self.rewards.T.contiguous().clamp(-8, 8)'",
            installer,
        )
        reward_block = installer.split(
            "# Widen the trainer's reward clamp", 1
        )[1].split(
            "# Make the machine panel", 1
        )[0]
        self.assertIn(
            'apply --reverse --check --no-index \\\n'
            '        "$REWARD_CLAMP_PATCH"',
            reward_block,
        )
        self.assertIn(
            'apply --check --no-index \\\n'
            '        "$REWARD_CLAMP_PATCH"',
            reward_block,
        )
        self.assertNotIn(
            "if ! grep -Fq 'clamp(-8, 8)'",
            reward_block,
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

    def test_scripted_guard_recut_preserves_existing_error_precedence(self):
        patch = SCRIPTED_GUARD_PATCH.read_text(encoding="utf-8")
        cases = (
            ("def _train_worker", "backend = _resolve_backend(args)"),
            ("def _train(", "backend = _resolve_backend(args)"),
            ("def train(", "validate_config(args)"),
        )
        for function, validated_anchor in cases:
            matching_hunks = [
                block
                for block in patch.split("@@")
                if function in block and "guard_scripted_training(args)" in block
            ]
            self.assertEqual(
                len(matching_hunks),
                1,
                f"{function} must own one scripted guard hunk",
            )
            block = matching_hunks[0]
            self.assertLess(
                block.index(validated_anchor),
                block.index("guard_scripted_training(args)"),
                f"{function} guard moved before its existing validated anchor",
            )


if __name__ == "__main__":
    unittest.main()
