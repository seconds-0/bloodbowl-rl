"""Contracts for recurrent state at graph, rollout, and game boundaries."""

from __future__ import annotations

import pathlib
import unittest

try:
    import torch
except ImportError:  # pragma: no cover - minimal CI image
    torch = None


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_recurrent_eval_state.patch"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
SCREEN = ROOT / "tools" / "run_reward_screen.sh"
ARM = ROOT / "tools" / "run_reward_ablation.sh"


class RecurrentEvaluationPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = PATCH.read_text(encoding="utf-8")

    def test_graph_warmup_restores_primary_and_every_frozen_state(self):
        for fragment in (
            "for (int bank = 0; bank < 1 + pufferl->num_frozen_banks; bank++)",
            "pufferl->frozen_banks[bank - 1].buffer_states",
            "for (int b = 0; b < num_buffers; b++)",
            "puf_zero(&bs[b], pufferl->default_stream);",
        ):
            self.assertIn(fragment, self.patch)
        zero_at = self.patch.index("for (int bank = 0; bank < 1 + pufferl->num_frozen_banks")
        sync_at = self.patch.index("cudaDeviceSynchronize();", zero_at)
        epoch_at = self.patch.index("pufferl->epoch = 0;", zero_at)
        self.assertLess(zero_at, sync_at)
        self.assertLess(sync_at, epoch_at)

    def test_native_terminal_reset_is_captured_and_bank_local(self):
        for fragment in (
            "evaluation_mode_puf",
            "reset_recurrent_state_on_terminal<<<",
            "grid_size(bank_size)",
            "env.terminals.data + sub_start",
            "s_bank->shape[0]",
            "bank_size",
            "s_bank->shape[2]",
        ):
            self.assertIn(fragment, self.patch)
        callback = self.patch.split(
            'extern "C" void net_callback_wrapper', 1)[1]
        callback = callback.split("// Write policy action", 1)[0]
        self.assertLess(
            callback.index("reset_recurrent_state_on_terminal<<<"),
            callback.index("policy_forward("),
        )
        self.assertNotIn("grid_size(state_n)", callback)
        self.assertNotIn(
            "if (pufferl->evaluation_mode) {\n+            reset_recurrent",
            callback,
            "a host branch evaluated during capture would omit the eval kernel",
        )

    def test_mode_transition_clears_primary_and_frozen_state_once(self):
        for fragment in (
            "void set_evaluation_mode(",
            "if (enabled == pufferl.evaluation_mode) return;",
            "if (enabled && pufferl.global_step > 0)",
            "static_vec_reset(pufferl.vec);",
            "if enabled and self.global_step > 0:",
            "self._vec.reset()",
            "puf_zero(&pufferl.buffer_states[i]",
            "puf_zero(&pufferl.frozen_banks[b].buffer_states[i]",
            "cudaMemcpyAsync(pufferl.evaluation_mode_puf",
            'm.def("set_evaluation_mode", &set_evaluation_mode);',
        ):
            self.assertIn(fragment, self.patch)

    def test_torch_carries_pending_outcomes_and_selects_eval_reset(self):
        for fragment in (
            "self.pending_rewards",
            "self.pending_terminals",
            "prepare_recurrent_rollout",
            "self.state, self.pending_rewards, self.pending_terminals",
            "self.state = reset_recurrent_state_rows(self.state, d)",
            "self.pending_rewards = torch.as_tensor(r, device=device).clone()",
            "self.pending_terminals = torch.as_tensor(d, device=device).clone()",
        ):
            self.assertIn(fragment, self.patch)

    @unittest.skipUnless(torch is not None, "requires torch")
    def test_torch_terminal_row_helper_executes_selectively(self):
        start = self.patch.index("+def reset_recurrent_state_rows(")
        lines = []
        for line in self.patch[start:].splitlines():
            if not line.startswith("+"):
                break
            lines.append(line[1:])
        namespace = {"torch": torch}
        exec("\n".join(lines), namespace)
        reset = namespace["reset_recurrent_state_rows"]

        hidden = torch.arange(12, dtype=torch.float32).reshape(2, 3, 2) + 1
        cell = hidden + 100
        result = reset((hidden, cell), torch.tensor([0.0, 1.0, 0.0]))
        self.assertEqual(len(result), 2)
        for before, after in zip((hidden, cell), result):
            self.assertTrue(torch.equal(after[:, 0], before[:, 0]))
            self.assertTrue(torch.equal(after[:, 1], torch.zeros_like(after[:, 1])))
            self.assertTrue(torch.equal(after[:, 2], before[:, 2]))
        self.assertTrue(torch.equal(hidden[:, 1], torch.tensor([[3., 4.], [9., 10.]])))
        self.assertEqual(reset((), torch.tensor([1.0])), ())
        with self.assertRaisesRegex(RuntimeError, "recurrent state batch"):
            reset((hidden,), torch.tensor([0.0, 1.0]))

    @unittest.skipUnless(torch is not None, "requires torch")
    def test_torch_rollout_boundary_helpers_preserve_or_clear_exactly(self):
        start = self.patch.index("+def reset_recurrent_state_rows(")
        lines = []
        for line in self.patch[start:].splitlines():
            if not line.startswith("+"):
                break
            lines.append(line[1:])
        namespace = {"torch": torch}
        exec("\n".join(lines), namespace)
        reset = namespace["reset_recurrent_state_rows"]
        prepare = namespace["prepare_recurrent_rollout"]

        state = (torch.arange(12, dtype=torch.float32).reshape(2, 3, 2) + 1,)
        rewards = torch.tensor([1.0, 2.0, 3.0])
        terminals = torch.tensor([0.0, 1.0, 0.0])

        carried_state, carried_rewards, carried_terminals = prepare(
            state, rewards, terminals, reset_state=True, evaluation_mode=True)
        self.assertTrue(torch.equal(carried_state[0], state[0]))
        self.assertTrue(torch.equal(carried_rewards, rewards))
        self.assertTrue(torch.equal(carried_terminals, terminals))
        post_terminal = reset(carried_state, carried_terminals)
        self.assertTrue(torch.equal(post_terminal[0][:, 0], state[0][:, 0]))
        self.assertTrue(torch.equal(
            post_terminal[0][:, 1], torch.zeros_like(state[0][:, 1])))
        self.assertTrue(torch.equal(post_terminal[0][:, 2], state[0][:, 2]))

        cleared_state, cleared_rewards, cleared_terminals = prepare(
            state, rewards, terminals, reset_state=True, evaluation_mode=False)
        self.assertTrue(torch.equal(cleared_state[0], torch.zeros_like(state[0])))
        self.assertTrue(torch.equal(cleared_rewards, torch.zeros_like(rewards)))
        self.assertTrue(torch.equal(cleared_terminals, torch.zeros_like(terminals)))
        self.assertTrue(torch.equal(state[0][:, 1], torch.tensor([[3., 4.], [9., 10.]])))

    def test_training_rejects_persistent_state_and_all_eval_paths_select_mode(self):
        for fragment in (
            "training requires reset_state=True",
            "evaluation_mode=False",
            "backend.set_evaluation_mode(pufferl, epoch >= train_epochs)",
            "backend.set_evaluation_mode(pufferl, True)",
        ):
            self.assertIn(fragment, self.patch)
        self.assertGreaterEqual(
            self.patch.count("training requires reset_state=True"), 2)

    def test_installer_and_experiment_identity_require_recurrent_patch(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        screen = SCREEN.read_text(encoding="utf-8")
        arm = ARM.read_text(encoding="utf-8")
        for source in (installer, screen, arm):
            self.assertIn("puffer_recurrent_eval_state.patch", source)
        self.assertIn("pufferlib/pufferl.py", installer)
        for marker in (
            "reset_recurrent_state_on_terminal",
            "set_evaluation_mode",
            "pending_terminals",
        ):
            self.assertIn(marker, installer)


if __name__ == "__main__":
    unittest.main()
