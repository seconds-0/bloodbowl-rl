"""Contract checks for exact semantic action sampling.

The runtime implementation lives in a tracked patch against the pinned
PufferLib tree. These checks keep the native rollout, Torch rollout, and PPO
recompute seams from drifting independently.
"""

from __future__ import annotations

import pathlib
import unittest

try:
    import torch
except ImportError:  # pragma: no cover - exercised in minimal CI images
    torch = None


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_exact_joint_actions.patch"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"
BINDING = ROOT / "puffer" / "bloodbowl" / "binding.c"


class ExactJointActionPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch = PATCH.read_text(encoding="utf-8")

    def test_native_sampler_builds_and_stores_selected_conditional_masks(self):
        required = (
            "// Exact sequential support.",
            "for (int p = 0; p < h; ++p)",
            "action_mask[mask_base + logits_offset + value]",
            "env.joint_action_offsets.data + sub_start",
            "mask_b.data, mask_stride_b",
        )
        for fragment in required:
            self.assertIn(fragment, self.patch)
        self.assertIn("#ifndef PRECISION_FLOAT", self.patch)
        self.assertIn("inline void cast_dispatch(precision_t* dst, const float* src", self.patch)

    def test_torch_sampler_returns_effective_mask_for_ordinary_ppo_recompute(self):
        required = (
            "def compact_joint_actions(",
            "source = offsets_long[rows] + within",
            "def sample_joint_logits(",
            "prefix &= values == selected[rows]",
            "torch.cat(masks, dim=1).to(torch.uint8)",
            "action, logprob, _, effective_mask = sample_joint_logits(",
            "action mask row has empty head support",
            "source_offsets_cpu = self.vec_joint_offsets.clone()",
        )
        for fragment in required:
            self.assertIn(fragment, self.patch)
        self.assertIn(
            "logits, mb_masks.reshape(-1, self.mask_size)",
            self.patch,
        )

    def test_torch_pointer_views_support_packed_int32_storage(self):
        self.assertIn("torch.int32:   ctypes.c_int32", self.patch)

    def test_vec_transport_is_transient_while_rollout_shape_stays_454(self):
        binding = BINDING.read_text(encoding="utf-8")
        self.assertIn("#define MY_ACTION_MASK 454", binding)
        self.assertIn("#define MY_JOINT_ACTION_MAX 4487", binding)
        self.assertIn("vec->joint_buffer_counts[buf] = cursor", binding)
        self.assertNotIn("joint_actions; // (horizon", self.patch)

    def test_installer_applies_and_checks_the_exact_backend_patch(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        self.assertIn("training/puffer_exact_joint_actions.patch", installer)
        self.assertIn("sample_joint_logits", installer)
        self.assertIn("Exact sequential support", installer)
        self.assertIn("exact joint-action backend support is incomplete", installer)

    def test_compiled_module_exports_semantic_lineage_not_only_tensor_shape(self):
        installer = INSTALLER.read_text(encoding="utf-8")
        for fragment in (
            "PUFFER_ENV_SOURCE_HASH",
            "PUFFER_OBSERVATION_VERSION",
            "PUFFER_ACTION_ABI",
            '"obs-v5"',
            '"exact-joint-v1"',
            'getattr(_C, "environment_source_hash"',
            'getattr(_C, "observation_abi"',
            'getattr(_C, "observation_version"',
            'getattr(_C, "action_abi"',
        ):
            self.assertIn(fragment, installer)
        for fragment in (
            'm.attr("environment_source_hash") = PUFFER_ENV_SOURCE_HASH;',
            'm.attr("observation_abi") = PUFFER_OBSERVATION_ABI;',
            'm.attr("observation_version") = PUFFER_OBSERVATION_VERSION;',
            'm.attr("action_abi") = PUFFER_ACTION_ABI;',
        ):
            self.assertEqual(self.patch.count(fragment), 2)

    def test_packed_interface_fails_closed_outside_supported_shape(self):
        for fragment in (
            "get_num_act_sizes() > 3",
            "sizes[h] <= 0 || sizes[h] > 1023",
            "joint actions require an action mask and at most three heads",
            "if (!action_enabled(action_mask, mask_base, logits_offset, a))",
            "if (!action_enabled(\n+                        a.action_mask, mask_base, logits_offset, j))",
            "a.grad_logits[grad_logits_base + logits_offset + j] = 0.0f;",
            "assert(enabled_count > 0);",
            "gpu_vec_step: synchronous stepping requires one buffer",
            "cpu_vec_step: synchronous stepping requires one buffer",
        ):
            self.assertIn(fragment, self.patch)
        self.assertNotIn("+        if (m == 0.0f) l = -1e4f;", self.patch)
        self.assertNotIn("+            l = -1e4f;", self.patch)

    def test_agent_permutation_refreshes_rows_before_the_first_rollout(self):
        """Repointed rows must not expose identity-layout state to sampling."""
        set_perm = self.patch.split("void static_vec_set_perm", 1)[1]
        set_perm = set_perm.split("void static_vec_set_env_tags", 1)[0]
        self.assertIn("static_vec_reset(vec);", set_perm)
        self.assertIn(
            "permutation is a one-time pre-rollout operation",
            self.patch,
        )

    def test_joint_support_is_uploaded_before_cuda_graph_sampling(self):
        """Graph warmup must never sample uninitialized ragged metadata."""
        self.assertIn(
            "+    if (vec->joint_action_max > 0) static_vec_reset(vec);\n+\n"
            "     // Cudagraph rolluts and entire training step",
            self.patch,
        )
        self.assertIn(
            "+    if (vec->joint_action_max <= 0) static_vec_reset(vec);",
            self.patch,
        )

    @unittest.skipUnless(torch is not None, "requires torch")
    def test_actual_patched_torch_sampler_matches_support_and_recompute(self):
        """Execute the added helper bodies with a reference categorical."""
        start = self.patch.index("+def apply_action_mask(")
        lines = []
        for line in self.patch[start:].splitlines():
            if not line.startswith("+"):
                break
            lines.append(line[1:])

        def sample_logits(logits, action=None):
            if isinstance(logits, torch.Tensor):
                distribution = torch.distributions.Categorical(logits=logits)
                if action is None:
                    selected = distribution.sample()
                else:
                    selected = action.reshape(logits.shape[0], -1)[:, 0].long()
                return (selected[:, None].int(),
                        distribution.log_prob(selected),
                        distribution.entropy())
            distributions = [torch.distributions.Categorical(logits=head)
                             for head in logits]
            if action is None:
                action = torch.stack([dist.sample() for dist in distributions],
                                     dim=1).int()
            logprob = torch.stack(
                [dist.log_prob(action[:, h].long())
                 for h, dist in enumerate(distributions)], dim=0).sum(dim=0)
            entropy = torch.stack(
                [dist.entropy() for dist in distributions], dim=0).sum(dim=0)
            return action, logprob, entropy

        namespace = {"torch": torch, "sample_logits": sample_logits}
        exec("\n".join(lines), namespace)
        masker = namespace["apply_action_mask"]
        compactor = namespace["compact_joint_actions"]
        sampler = namespace["sample_joint_logits"]

        logits = [torch.tensor([[1.0, 2.0, 3.0]])]
        masked = masker(
            logits, torch.tensor([[1, 0, 1]], dtype=torch.uint8), [3])
        self.assertTrue(torch.isneginf(masked[0][0, 1]))
        with self.assertRaisesRegex(RuntimeError, "empty head support"):
            masker(logits, torch.zeros((1, 3), dtype=torch.uint8), [3])

        def pack(values):
            return sum(int(value) << (10 * head)
                       for head, value in enumerate(values))

        rows = [
            [(0, 1, 2), (0, 2, 3), (1, 4, 5)],
            [(2, 6, 7), (2, 6, 8)],
        ]
        # Native buffers occupy fixed-capacity regions, and permutation can
        # make logical visitation order differ from physical row order. Prove
        # the shipped host compactor obeys authoritative row offsets rather
        # than slicing a global prefix.
        scrambled = torch.full((16,), -1, dtype=torch.int32)
        scrambled[8:11] = torch.tensor(
            [pack(values) for values in rows[0]], dtype=torch.int32)
        scrambled[0:2] = torch.tensor(
            [pack(values) for values in rows[1]], dtype=torch.int32)
        compact, compact_offsets = compactor(
            scrambled,
            torch.tensor([8, 0], dtype=torch.int32),
            torch.tensor([3, 2], dtype=torch.int32),
        )
        self.assertEqual(
            compact.tolist(),
            [pack(values) for row in rows for values in row],
        )
        self.assertEqual(compact_offsets.tolist(), [0, 3])

        packed = torch.tensor(
            [pack(values) for row in rows for values in row],
            dtype=torch.int32,
        )
        offsets = torch.tensor([0, 3], dtype=torch.int32)
        counts = torch.tensor([3, 2], dtype=torch.int32)
        torch.manual_seed(7)
        for _ in range(50):
            logits = [torch.randn(2, size) for size in (3, 10, 12)]
            action, logprob, entropy, mask = sampler(
                logits, packed, offsets, counts, [3, 10, 12])
            for row, selected in zip(rows, action.tolist()):
                self.assertIn(tuple(selected), row)
            slices = torch.split(mask.bool(), [3, 10, 12], dim=1)
            masked_logits = [head.masked_fill(~support, float("-inf"))
                             for head, support in zip(logits, slices)]
            _, recomputed_logprob, recomputed_entropy = sample_logits(
                masked_logits, action=action)
            torch.testing.assert_close(logprob, recomputed_logprob)
            torch.testing.assert_close(entropy, recomputed_entropy)

        # Arg/square are inactive singletons for both possible type choices.
        singleton_rows = [(0, 32, 390), (1, 32, 390)]
        singleton_packed = torch.tensor(
            [pack(values) for values in singleton_rows], dtype=torch.int32)
        singleton_logits = [
            torch.tensor([[0.2, -0.3]], requires_grad=True),
            torch.randn(1, 33, requires_grad=True),
            torch.randn(1, 391, requires_grad=True),
        ]
        _, logprob, entropy, _ = sampler(
            singleton_logits,
            singleton_packed,
            torch.tensor([0], dtype=torch.int32),
            torch.tensor([2], dtype=torch.int32),
            [2, 33, 391],
        )
        (logprob + entropy).sum().backward()
        self.assertEqual(torch.count_nonzero(singleton_logits[1].grad).item(), 0)
        self.assertEqual(torch.count_nonzero(singleton_logits[2].grad).item(), 0)


if __name__ == "__main__":
    unittest.main()
