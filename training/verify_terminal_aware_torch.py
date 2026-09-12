#!/usr/bin/env python3
'''Deterministic CPU verifier for terminal-aware-tbptt-v1 Torch helpers.'''

import argparse
import copy
import importlib.util
import json
from pathlib import Path
import unittest

import torch
import numpy as np


def load_source(path):
    spec = importlib.util.spec_from_file_location('torch_pufferl_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TinyPolicy:
    '''Inspectable recurrence; deliberately mutates input like LSTM/GRU APIs.'''

    def forward_eval(self, observation, state):
        state[0].add_(observation[:, :1].view(1, -1, 1))
        value = state[0][0, :, 0].unsqueeze(1)
        logits = torch.stack((value[:, 0], -value[:, 0]), dim=1)
        return logits, value, state


class FakeVector:
    '''Pointer-backed deterministic vector exercising the real rollout loop.'''

    def __init__(self):
        self.gpu = False
        self.total_agents = 2
        self.obs_size = 3
        self.obs_dtype = 'FloatTensor'
        self.num_atns = 2
        self.act_sizes = (3, 3)
        self.action_mask_size = 6
        self.joint_action_capacity = 0
        self._obs = np.zeros((2, 3), dtype=np.float32)
        self._rewards = np.zeros(2, dtype=np.float32)
        self._terminals = np.zeros(2, dtype=np.float32)
        # Two legal values per head, with different row-specific support.
        self._masks = np.array(
            [[1, 1, 0, 0, 1, 1], [0, 1, 1, 1, 1, 0]], dtype=np.uint8)
        self.obs_ptr = self._obs.ctypes.data
        self.rewards_ptr = self._rewards.ctypes.data
        self.terminals_ptr = self._terminals.ctypes.data
        self.action_mask_ptr = self._masks.ctypes.data
        self.joint_action_offsets_ptr = 0
        self.joint_action_counts_ptr = 0
        self.joint_actions_ptr = 0
        self.step_index = 0

    def reset(self):
        self.step_index = 0
        self._obs[:] = np.array([[1, 2, 3], [4, 5, 6]], dtype=np.float32)
        self._rewards.fill(0)
        self._terminals.fill(0)

    def cpu_step(self, _action_ptr):
        outcomes = (
            (0, 0), (1, 0), (0, 0), (0, 1),
            (0, 0), (0, 0), (1, 0), (0, 0),
        )
        terminal = outcomes[self.step_index % len(outcomes)]
        self.step_index += 1
        base = 1 + 3 * self.step_index
        self._obs[:] = np.array(
            [[base, base + 1, base + 2],
             [base + 3, base + 4, base + 5]], dtype=np.float32)
        self._rewards[:] = np.array([0.1, -0.2], dtype=np.float32)
        self._terminals[:] = terminal

    def log(self):
        return {}


def trainer_args():
    return {
        'reset_state': True,
        'world_size': 1,
        'vec': {'total_agents': 2},
        'train': {
            'horizon': 4,
            'total_timesteps': 16,
            'minibatch_size': 8,
            'replay_ratio': 1.0,
            'learning_rate': 0.0,
            'beta1': 0.9,
            'eps': 1e-8,
            'ent_coef': 0.0,
            'anneal_ent_coef': False,
            'min_ent_coef_ratio': 0.0,
            'prio_beta0': 0.0,
            'prio_alpha': 0.0,
            'clip_coef': 0.2,
            'vf_clip_coef': 0.2,
            'anneal_lr': False,
            'min_lr_ratio': 0.0,
            'gamma': 0.995,
            'gae_lambda': 0.95,
            'vtrace_rho_clip': 1.0,
            'vtrace_c_clip': 1.0,
            'vf_coef': 0.5,
            'max_grad_norm': 1.0,
        },
    }


class ContractTests(unittest.TestCase):
    module = None
    require_real_cpu_advantage = False

    def test_training_boundary_carries_and_applies_pending_terminal(self):
        m = self.module
        state = (torch.tensor([[[5.0], [7.0]]]),)
        rewards = torch.tensor([3.0, 4.0])
        terminals = torch.tensor([0.0, 1.0])
        got, got_rewards, got_terminals = m.prepare_recurrent_rollout(
            state, rewards, terminals, True, False)
        torch.testing.assert_close(got[0], torch.tensor([[[5.0], [0.0]]]))
        torch.testing.assert_close(got_rewards, rewards)
        torch.testing.assert_close(got_terminals, terminals)

    def test_two_windows_equal_uninterrupted_reference(self):
        m = self.module
        policy = TinyPolicy()
        obs = torch.tensor([[[1.0], [2.0], [3.0], [4.0]]])
        masks = torch.zeros((1, 4))
        initial = (torch.tensor([[[10.0]]]),)
        _, full_values, full_final = m.recurrent_forward_sequence(
            policy, obs, initial, masks)
        _, first_values, first_final = m.recurrent_forward_sequence(
            policy, obs[:, :2], initial, masks[:, :2])
        _, second_values, second_final = m.recurrent_forward_sequence(
            policy, obs[:, 2:], first_final, masks[:, 2:])
        torch.testing.assert_close(
            torch.cat((first_values, second_values), dim=1), full_values)
        torch.testing.assert_close(second_final[0], full_final[0])
        torch.testing.assert_close(initial[0], torch.tensor([[[10.0]]]))

    def test_midsegment_terminal_resets_only_its_row(self):
        m = self.module
        policy = TinyPolicy()
        obs = torch.tensor([
            [[1.0], [2.0], [3.0]],
            [[4.0], [5.0], [6.0]],
        ])
        masks = torch.tensor([[0.0, 1.0, 0.0], [0.0, 0.0, 0.0]])
        initial = (torch.tensor([[[10.0], [20.0]]]),)
        _, values, final = m.recurrent_forward_sequence(
            policy, obs, initial, masks)
        torch.testing.assert_close(values, torch.tensor([
            [11.0, 2.0, 5.0], [24.0, 29.0, 35.0]]))
        torch.testing.assert_close(final[0], torch.tensor([[[5.0], [35.0]]]))

    def test_terminal_cuts_gradients_from_later_outputs(self):
        m = self.module
        policy = TinyPolicy()
        obs = torch.tensor(
            [[[1.0], [2.0], [3.0], [4.0]]], requires_grad=True)
        masks = torch.tensor([[0.0, 0.0, 1.0, 0.0]])
        initial = (torch.tensor([[[10.0]]]),)
        _, values, _ = m.recurrent_forward_sequence(
            policy, obs, initial, masks)
        values[:, 3].sum().backward()
        torch.testing.assert_close(obs.grad[:, :2], torch.zeros((1, 2, 1)))
        torch.testing.assert_close(obs.grad[:, 2:], torch.ones((1, 2, 1)))

    def test_independent_state_permutation_changes_only_its_rows(self):
        m = self.module
        policy = TinyPolicy()
        obs = torch.tensor([[[1.0], [1.0]], [[2.0], [2.0]]])
        masks = torch.zeros((2, 2))
        initial = (torch.tensor([[[10.0], [30.0]]]),)
        _, expected, _ = m.recurrent_forward_sequence(
            policy, obs, initial, masks)
        permuted = m.gather_segment_initial_state(
            initial, torch.tensor([1, 0]), 2)
        _, wrong, _ = m.recurrent_forward_sequence(
            policy, obs, permuted, masks)
        self.assertFalse(torch.equal(expected[0], wrong[0]))
        self.assertFalse(torch.equal(expected[1], wrong[1]))
        torch.testing.assert_close(expected[0] - wrong[0], torch.tensor([-20.0, -20.0]))
        torch.testing.assert_close(expected[1] - wrong[1], torch.tensor([20.0, 20.0]))

    def test_tail_uses_carried_copy_and_terminal_value_zero(self):
        m = self.module
        policy = TinyPolicy()
        state = (torch.tensor([[[10.0], [20.0]]]),)
        observation = torch.tensor([[2.0], [3.0]])
        rewards = torch.tensor([1.0, 2.0])
        terminals = torch.tensor([0.0, 1.0])
        values, got_rewards, got_terminals, before = m.evaluate_recurrent_tail(
            policy, observation, state, rewards, terminals)
        torch.testing.assert_close(values, torch.tensor([12.0, 0.0]))
        torch.testing.assert_close(state[0], torch.tensor([[[10.0], [20.0]]]))
        torch.testing.assert_close(before[0], state[0])
        torch.testing.assert_close(got_rewards, rewards)
        torch.testing.assert_close(got_terminals, terminals)

    def test_segment_state_gather_follows_sampled_ownership(self):
        m = self.module
        state = (torch.tensor([[[10.0], [20.0], [30.0], [40.0]]]),)
        idx = torch.tensor([3, 1, 3])
        got = m.gather_segment_initial_state(state, idx, 4)
        torch.testing.assert_close(
            got[0], torch.tensor([[[40.0], [20.0], [40.0]]]))
        got[0][0, 0, 0] = -1
        self.assertEqual(state[0][0, 3, 0].item(), 40.0)
        with self.assertRaisesRegex(RuntimeError, 'ownership'):
            m.gather_segment_initial_state(state, idx, 5)

    def test_lifecycle_fails_closed(self):
        m = self.module
        m.require_empty_training_records(False, False)
        m.require_complete_training_records(True, True)
        for flags in ((True, False), (False, True), (True, True)):
            with self.assertRaisesRegex(RuntimeError, 'overwrite'):
                m.require_empty_training_records(*flags)
        for flags in ((False, False), (True, False), (False, True)):
            with self.assertRaisesRegex(RuntimeError, 'complete'):
                m.require_complete_training_records(*flags)

    def test_actual_pufferl_mingru_rollout_and_lr0_ppo(self):
        m = self.module
        from pufferlib import models

        torch.manual_seed(7123)
        compiled_gpu = m._C.gpu
        m._C.gpu = False
        compiled_advantage = m.compute_puff_advantage
        def cpu_fixture_advantage(values, rewards, terminals, ratio,
                tail_values, tail_rewards, tail_terminals, advantages,
                gamma, gae_lambda, vtrace_rho_clip, vtrace_c_clip):
            del terminals, ratio, tail_values, tail_rewards, tail_terminals
            del gamma, gae_lambda, vtrace_rho_clip, vtrace_c_clip
            advantages.copy_(rewards + 0.25 - values.detach())
            return advantages
        use_fixture_advantage = not hasattr(m._C, 'puff_advantage_cpu')
        if self.require_real_cpu_advantage and use_fixture_advantage:
            self.fail('required real CPU puff_advantage_cpu binding is absent')
        if use_fixture_advantage:
            m.compute_puff_advantage = cpu_fixture_advantage
        vec = FakeVector()
        policy = models.Policy(
            models.DefaultEncoder(3, hidden_size=8),
            models.DefaultDecoder((3, 3), hidden_size=8),
            models.MinGRU(8, num_layers=2),
        )
        trainer = m.PuffeRL(trainer_args(), vec, policy, verbose=False)
        original_weights = copy.deepcopy(policy.state_dict())
        optimizer_step = trainer.optimizer.step
        gradient_snapshots = []
        def checked_optimizer_step():
            grads = [p.grad.detach().clone() for p in policy.parameters()
                     if p.grad is not None]
            if not grads or any(not torch.isfinite(g).all() for g in grads):
                raise AssertionError('actual PPO gradients are missing or nonfinite')
            gradient_snapshots.append(grads)
            return optimizer_step()
        trainer.optimizer.step = checked_optimizer_step

        # Force the real prioritized sampler to select both physical rows once.
        original_multinomial = torch.multinomial
        selected = []
        def deterministic_multinomial(probs, count, replacement=True, **kwargs):
            if probs.ndim == 1 and probs.numel() == 2:
                idx = torch.arange(count, device=probs.device) % 2
                selected.append(idx.detach().clone())
                return idx
            return original_multinomial(
                probs, count, replacement=replacement, **kwargs)

        try:
            torch.multinomial = deterministic_multinomial
            trainer.rollouts()
            self.assertTrue(trainer.tail_valid)
            self.assertTrue(trainer.segment_state_valid)
            self.assertEqual(trainer.recurrent_reset_masks.T.tolist(),
                [[0.0, 0.0, 1.0, 0.0], [0.0, 0.0, 0.0, 0.0]])
            actions = trainer.actions.long()
            for t in range(4):
                for row in range(2):
                    for head in range(2):
                        self.assertEqual(int(vec._masks[
                            row, 3 * head + actions[t, row, head]]), 1)
            self.assertTrue(torch.isfinite(trainer.logprobs).all())
            self.assertGreater(trainer.logprobs.abs().max().item(), 1e-4)
            first_initial = m.clone_recurrent_state(
                trainer.segment_initial_state)
            first_final = m.clone_recurrent_state(trainer.state)
            first_tail_terminals = trainer.tail_terminals.clone()
            self.assertEqual(first_tail_terminals.tolist(), [0.0, 1.0])

            # Replay the actual collected tensors through the real two-layer
            # MinGRU and require behavior/recompute value identity.
            _, replay_values, _ = m.recurrent_forward_sequence(
                policy, trainer.observations.transpose(0, 1), first_initial,
                trainer.recurrent_reset_masks.transpose(0, 1))
            torch.testing.assert_close(
                replay_values, trainer.values.T, atol=1e-6, rtol=1e-6)
            replay_logits, _, _ = m.recurrent_forward_sequence(
                policy, trainer.observations.transpose(0, 1), first_initial,
                trainer.recurrent_reset_masks.transpose(0, 1))
            replay_logits = m.apply_action_mask(
                replay_logits,
                trainer.action_masks.transpose(0, 1).reshape(-1, 6),
                trainer.act_sizes_list)
            _, replay_lp, _ = m.sample_logits(
                replay_logits,
                action=trainer.actions.transpose(0, 1).contiguous())
            torch.testing.assert_close(
                replay_lp.reshape(2, 4), trainer.logprobs.T,
                atol=1e-6, rtol=1e-6)

            corrupted = tuple(s.clone() for s in first_initial)
            corrupted[0][:, 0].add_(10.0)
            bad_logits, _, _ = m.recurrent_forward_sequence(
                policy, trainer.observations.transpose(0, 1), corrupted,
                trainer.recurrent_reset_masks.transpose(0, 1))
            bad_logits = m.apply_action_mask(
                bad_logits,
                trainer.action_masks.transpose(0, 1).reshape(-1, 6),
                trainer.act_sizes_list)
            _, bad_lp, _ = m.sample_logits(
                bad_logits,
                action=trainer.actions.transpose(0, 1).contiguous())
            bad_lp = bad_lp.reshape(2, 4)
            self.assertGreater(
                (bad_lp[0] - trainer.logprobs.T[0]).abs().max().item(), 1e-4)
            torch.testing.assert_close(
                bad_lp[1], trainer.logprobs.T[1], atol=1e-6, rtol=1e-6)

            with self.assertRaisesRegex(RuntimeError, 'discard'):
                trainer.set_evaluation_mode(True)
            trainer.train()
            self.assertEqual(len(selected), 1)
            self.assertEqual(selected[0].tolist(), [0, 1])
            self.assertTrue(torch.isfinite(trainer.ratio).all())
            torch.testing.assert_close(
                trainer.ratio, torch.ones_like(trainer.ratio),
                atol=2e-5, rtol=0)
            self.assertTrue(all(torch.isfinite(torch.tensor(v))
                                for v in trainer.losses.values()))
            self.assertEqual(len(gradient_snapshots), 1)
            for name, before in original_weights.items():
                torch.testing.assert_close(policy.state_dict()[name], before,
                    atol=0, rtol=0)

            trainer.rollouts()
            second_initial = trainer.segment_initial_state
            for expected_carry, actual in zip(first_final, second_initial):
                torch.testing.assert_close(actual[:, 0], expected_carry[:, 0])
                torch.testing.assert_close(
                    actual[:, 1], torch.zeros_like(actual[:, 1]))
            # The boundary terminal remains visible in slot zero for both the
            # reset contract and observation-aligned GAE indexing.
            self.assertEqual(trainer.recurrent_reset_masks[0].tolist(), [0.0, 1.0])
            trainer.train()
            self.assertEqual(len(gradient_snapshots), 2)
            trainer.set_evaluation_mode(True)
            self.assertTrue(trainer.evaluation_mode)
            trainer.set_evaluation_mode(False)
            self.assertFalse(trainer.evaluation_mode)
        finally:
            torch.multinomial = original_multinomial
            if use_fixture_advantage:
                m.compute_puff_advantage = compiled_advantage
            m._C.gpu = compiled_gpu

    def test_actual_rollout_carries_nonterminal_boundary_old_runtime_regression(self):
        '''Fails semantically on the old trainer after two actual rollouts.'''
        m = self.module
        from pufferlib import models

        torch.manual_seed(8128)
        compiled_gpu = m._C.gpu
        m._C.gpu = False
        try:
            vec = FakeVector()
            policy = models.Policy(
                models.DefaultEncoder(3, hidden_size=8),
                models.DefaultDecoder((3, 3), hidden_size=8),
                models.MinGRU(8, num_layers=2),
            )
            trainer = m.PuffeRL(trainer_args(), vec, policy, verbose=False)
            trainer.rollouts()
            carried = tuple(s.detach().clone() for s in trainer.state)
            pending = trainer.pending_terminals.clone().bool()
            expected_state = tuple(torch.where(
                pending.view(1, -1, 1), torch.zeros_like(s), s)
                for s in carried)
            expected_obs = trainer.vec_obs.detach().clone()
            with torch.no_grad():
                _, expected_value, _ = policy.forward_eval(
                    expected_obs, tuple(s.clone() for s in expected_state))

            # Isolate behavior carry from the separately tested lifecycle gate.
            trainer.tail_valid = False
            if hasattr(trainer, 'segment_state_valid'):
                trainer.segment_state_valid = False
            trainer.rollouts()
            torch.testing.assert_close(
                trainer.values[0], expected_value.flatten(),
                atol=1e-6, rtol=1e-6)
        finally:
            m._C.gpu = compiled_gpu

    def test_actual_rollout_terminal_is_fresh_before_next_observation(self):
        '''Confirmed old-runtime leakage bug, independent of horizon carry.'''
        m = self.module
        from pufferlib import models

        torch.manual_seed(8675)
        compiled_gpu = m._C.gpu
        m._C.gpu = False
        try:
            vec = FakeVector()
            policy = models.Policy(
                models.DefaultEncoder(3, hidden_size=8),
                models.DefaultDecoder((3, 3), hidden_size=8),
                models.MinGRU(8, num_layers=2),
            )
            trainer = m.PuffeRL(trainer_args(), vec, policy, verbose=False)
            trainer.rollouts()
            self.assertEqual(float(trainer.terminals[2, 0]), 1.0)
            observation = trainer.observations[2, 0:1]
            zero = policy.initial_state(1, 'cpu')
            with torch.no_grad():
                _, fresh_value, _ = policy.forward_eval(observation, zero)
            torch.testing.assert_close(
                trainer.values[2, 0:1], fresh_value.flatten(),
                atol=1e-6, rtol=1e-6)
        finally:
            m._C.gpu = compiled_gpu

    def test_actual_mingru_terminal_matches_fresh_segment_and_cuts_gradient(self):
        m = self.module
        from pufferlib import models

        torch.manual_seed(991)
        policy = models.Policy(
            models.DefaultEncoder(3, hidden_size=8),
            models.DefaultDecoder((2, 2), hidden_size=8),
            models.MinGRU(8, num_layers=2),
        )
        obs = torch.randn(1, 4, 3, requires_grad=True)
        initial = (torch.randn(2, 1, 8),)
        masks = torch.tensor([[0.0, 0.0, 1.0, 0.0]])
        logits, values, final = m.recurrent_forward_sequence(
            policy, obs, initial, masks)
        fresh_logits, fresh_values, fresh_final = m.recurrent_forward_sequence(
            policy, obs[:, 2:].detach(), policy.initial_state(1, 'cpu'),
            torch.zeros((1, 2)))
        for actual, fresh in zip(
                logits if isinstance(logits, list) else [logits],
                fresh_logits if isinstance(fresh_logits, list) else [fresh_logits]):
            torch.testing.assert_close(actual.reshape(1, 4, -1)[:, 2:],
                                       fresh.reshape(1, 2, -1),
                                       atol=1e-6, rtol=1e-6)
        torch.testing.assert_close(values[:, 2:], fresh_values,
                                   atol=1e-6, rtol=1e-6)
        torch.testing.assert_close(final[0], fresh_final[0],
                                   atol=1e-6, rtol=1e-6)
        values[:, 3].sum().backward()
        torch.testing.assert_close(obs.grad[:, :2], torch.zeros_like(obs.grad[:, :2]))
        self.assertTrue(torch.isfinite(obs.grad[:, 2:]).all())
        self.assertGreater(obs.grad[:, 2:].abs().sum().item(), 0.0)

    def test_lstm_recompute_is_explicitly_unsupported_by_existing_model_api(self):
        m = self.module
        from pufferlib import models

        torch.manual_seed(144)
        policy = models.Policy(
            models.DefaultEncoder(3, hidden_size=8),
            models.DefaultDecoder((2, 2), hidden_size=8),
            models.LSTM(8, num_layers=2),
        )
        obs = torch.randn(1, 3, 3, requires_grad=True)
        initial = policy.initial_state(1, 'cpu')
        _, values, _ = m.recurrent_forward_sequence(
            policy, obs, initial, torch.tensor([[0.0, 1.0, 0.0]]))
        with self.assertRaisesRegex(RuntimeError, 'inplace operation'):
            values[:, 2].sum().backward()

    def test_continuous_distribution_recompute_preserves_shape(self):
        m = self.module
        from pufferlib import models

        torch.manual_seed(233)
        policy = models.Policy(
            models.DefaultEncoder(3, hidden_size=8),
            models.DefaultDecoder((1,), hidden_size=8),
            models.MinGRU(8, num_layers=2),
        )
        logits, values, _ = m.recurrent_forward_sequence(
            policy, torch.randn(2, 4, 3), policy.initial_state(2, 'cpu'),
            torch.zeros((2, 4)))
        self.assertIsInstance(logits, torch.distributions.Normal)
        self.assertEqual(tuple(logits.loc.shape), (8, 1))
        self.assertEqual(tuple(logits.scale.shape), (8, 1))
        self.assertEqual(tuple(values.shape), (2, 4))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--require-real-cpu-advantage', action='store_true')
    args = parser.parse_args()
    ContractTests.module = load_source(args.source.resolve())
    ContractTests.require_real_cpu_advantage = args.require_real_cpu_advantage
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ContractTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    print(json.dumps({
        'source': str(args.source.resolve()),
        'contract': getattr(ContractTests.module, 'RECURRENT_MEMORY_CONTRACT', None),
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'successful': result.wasSuccessful(),
    }, sort_keys=True))
    raise SystemExit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
