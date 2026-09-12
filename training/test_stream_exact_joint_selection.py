from __future__ import annotations

import importlib.util
import pathlib
import sys
import types
import unittest
from unittest import mock

import torch


ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO = ROOT


def load_game():
    sys.path.insert(0, str(ROOT / "stream_backend"))
    spec = importlib.util.spec_from_file_location(
        "audited_stream_game", ROOT / "stream_backend" / "game.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_canonical_backend():
    """Execute the actual helpers installed by puffer_exact_joint_actions.patch."""
    patch = (REPO / "training/puffer_exact_joint_actions.patch").read_text()
    start = patch.index("+def apply_action_mask(")
    lines = []
    for line in patch[start:].splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            lines.append(line[1:])
        elif line.startswith(" def sample_logits"):
            # sample_logits is context, not an added line. Supply the exact
            # categorical behavior required by the installed joint helper.
            break
        elif lines and line.startswith("diff --git"):
            break
    namespace = {"torch": torch}
    # The contiguous added block ends immediately before sample_logits.
    exec("\n".join(lines), namespace)

    def sample_logits(logits, action=None):
        # sample_joint_logits invokes the canonical helper once per tensor
        # head. Match torch_pufferl.sample_logits's tensor-mode shapes.
        distribution = torch.distributions.Categorical(logits=logits)
        selected = distribution.sample() if action is None else action.reshape(-1).long()
        return (selected.reshape(-1, 1).int(),
                distribution.log_prob(selected), distribution.entropy())

    namespace["sample_logits"] = sample_logits
    # sample_joint_logits resolves sample_logits from its globals at call time.
    return types.SimpleNamespace(
        apply_action_mask=namespace["apply_action_mask"],
        sample_joint_logits=namespace["sample_joint_logits"],
    )


def pack(action):
    t, a, s = action
    return t | (a << 10) | (s << 20)


class StreamExactJointSelectionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.game = load_game()
        # game.py deliberately disables all Torch symbols when its compiled
        # Puffer import is unavailable. This source-only CPU test injects the
        # installed Torch module and the canonical patched helper directly.
        cls.game.torch = torch
        cls.backend = load_canonical_backend()
        cls.support = {(1, 4, 10), (2, 5, 11)}
        cls.packed = torch.tensor(
            [pack(action) for action in sorted(cls.support)], dtype=torch.int32)

    def logits(self):
        logits = [torch.full((1, size), -20.0) for size in self.game.ACT_SIZES]
        logits[0][0, 1], logits[0][0, 2] = 1.1, 1.0
        logits[1][0, 4], logits[1][0, 5] = 1.0, 9.0
        logits[2][0, 10], logits[2][0, 11] = 9.0, 1.0
        return logits

    def test_old_independent_greedy_path_fails_witness(self):
        marginal = []
        for head, size in enumerate(self.game.ACT_SIZES):
            mask = torch.zeros((1, size), dtype=torch.bool)
            for action in self.support:
                mask[0, action[head]] = True
            marginal.append(self.logits()[head].masked_fill(~mask, float("-inf")))
        old_action = tuple(self.game.greedy_logits(marginal)[0].tolist())
        self.assertEqual(old_action, (1, 5, 10))
        self.assertNotIn(old_action, self.support)

    def test_actual_greedy_helper_conditions_each_head(self):
        action, _masked, effective = self.game.select_exact_joint_logits(
            self.logits(), self.packed, True, backend=self.backend)
        selected = tuple(action[0].tolist())
        self.assertEqual(selected, (1, 4, 10))
        self.assertIn(selected, self.support)
        self.assertEqual(tuple(effective.shape), (1, sum(self.game.ACT_SIZES)))

    def test_actual_stochastic_helper_uses_canonical_sampler_and_never_escapes(self):
        torch.manual_seed(914)
        seen = set()
        for _ in range(256):
            action, _masked, _effective = self.game.select_exact_joint_logits(
                self.logits(), self.packed, False, backend=self.backend)
            selected = tuple(action[0].tolist())
            self.assertIn(selected, self.support)
            seen.add(selected)
        self.assertEqual(seen, self.support)

    def test_missing_joint_sampler_or_metadata_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "exact-joint sampler"):
            self.game.select_exact_joint_logits(
                self.logits(), self.packed, False, backend=types.SimpleNamespace())
        with self.assertRaisesRegex(RuntimeError, "no packed joint support"):
            self.game.select_exact_joint_logits(
                self.logits(), torch.tensor([], dtype=torch.int32), False,
                backend=self.backend)

    def test_source_viewer_requires_obs_v7_semantic_identity(self):
        valid = types.SimpleNamespace(
            observation_abi="obs-v7", observation_version=7,
            action_abi="exact-joint-v1")
        self.game.validate_viewer_runtime(valid)
        for field, bad in (
                ("observation_abi", "obs-v6"),
                ("observation_version", 6),
                ("action_abi", "marginal-v1")):
            values = vars(valid).copy()
            values[field] = bad
            with self.assertRaisesRegex(RuntimeError, "viewer requires obs-v7/7"):
                self.game.validate_viewer_runtime(types.SimpleNamespace(**values))

    def test_targeted_action_context_uses_obs_v7_tail(self):
        obs = bytearray(self.game.OBS_SIZE)
        obs[self.game.dec.CTX + 4] = self.game.BB_PROC_TARGETED_ACTION
        obs[self.game.dec.TARGETED_VARIANT_OFF] = 5
        obs[self.game.dec.TARGETED_CONTEXT_OFF] = 2 | 4
        obs[self.game.dec.TARGETED_STATE_OFF] = 0x15
        obs[self.game.dec.TARGETED_ACTOR_OFF] = 4
        obs[self.game.dec.TARGETED_TARGET_OFF] = 20
        ctx = self.game._ctx_from_obs(obs)
        self.assertEqual(ctx["targeted_action_variant"], "chainsaw")
        self.assertEqual(
            ctx["targeted_action_flags"], ["from_blitz", "frenzy_second"])
        self.assertEqual(ctx["targeted_action_state"], [
            "dump_off_declined", "dump_off_pass_in_flight", "trickster_used",
        ])
        self.assertEqual(ctx["targeted_action_state_raw"], 0x15)
        self.assertEqual(ctx["targeted_action_actor"], 3)
        self.assertEqual(ctx["targeted_action_target"], 19)

    def test_match_tiny_batch_passes_real_puffer_config_validation(self):
        if self.game.pufferl_mod is None or self.game.tp is None:
            self.skipTest("installed pufferlib is unavailable")
        if not hasattr(
                self.game.pufferl_mod, "validate_entropy_schedule_config"):
            self.skipTest(
                "installed local Puffer lacks the current entropy validator; "
                "a rebuilt obs-v7 runtime must execute this test")

        captured = {}

        class ValidationComplete(Exception):
            pass

        def validate_without_constructing(args):
            self.game.pufferl_mod.validate_entropy_schedule_config(args)
            captured["horizon"] = args["train"]["horizon"]
            captured["minibatch_size"] = args["train"]["minibatch_size"]
            captured["replay_ratio"] = args["train"]["replay_ratio"]
            captured["total_agents"] = args["vec"]["total_agents"]
            raise ValidationComplete

        runtime = types.SimpleNamespace(
            observation_abi="obs-v7", observation_version=7,
            action_abi="exact-joint-v1")
        with mock.patch.object(self.game, "puffer_c", runtime), \
             mock.patch.object(
                 self.game.tp.PuffeRL, "create_pufferl",
                 side_effect=validate_without_constructing):
            with self.assertRaises(ValidationComplete):
                self.game.Match("unused-a.bin", "unused-b.bin")

        self.assertEqual(captured, {
            "horizon": 1,
            "minibatch_size": 2,
            "replay_ratio": 1.0,
            "total_agents": 2,
        })


if __name__ == "__main__":
    unittest.main()
