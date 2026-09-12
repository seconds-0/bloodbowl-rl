import hashlib
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RunnerBackendProvenanceTests(unittest.TestCase):
    def test_registry_is_complete_and_digest_is_content_sensitive(self):
        sources = (ROOT / "training/puffer_compiled_backend_sources.txt").read_text(
            encoding="utf-8").splitlines()
        self.assertEqual(len(sources), 15)
        self.assertEqual(len(sources), len(set(sources)))
        for required in (
            "build.sh", "pufferlib/sweep.py", "src/cudnn_conv2d.cu",
            "src/models.cu", "src/muon.cu", "src/ocean.cu", "src/tensor.h",
        ):
            self.assertIn(required, sources)
        labels = b"".join(f"{'0' * 64}  {name}\n".encode() for name in sources)
        changed = b"".join(
            f"{('1' if index == 0 else '0') * 64}  {name}\n".encode()
            for index, name in enumerate(sources))
        self.assertNotEqual(hashlib.sha256(labels).digest(),
                            hashlib.sha256(changed).digest())

    def test_both_runners_fail_closed_on_backend_and_contract_mismatch(self):
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(encoding="utf-8")
        arm = (ROOT / "tools/run_reward_ablation.sh").read_text(encoding="utf-8")
        self.assertIn(
            'compiled_contract["exact_action_source_sha256"] != backend_source_sha',
            screen)
        self.assertIn(
            '[ "$COMPILED_EXACT_ACTION_SOURCE_HASH" != "$VENDOR_SOURCE_HASH" ]',
            arm)
        for contract in (
            "terminal-aware-tbptt-v1",
            "cosine-update-index-over-total-updates-fp32-v1",
        ):
            self.assertIn(contract, screen)
            self.assertIn(contract, arm)
        self.assertIn(
            'compiled_contract["environment_source_sha256"] != source_hash', screen)
        self.assertIn(
            '[ "$COMPILED_ENVIRONMENT_SOURCE_HASH" != "$SOURCE_HASH" ]', arm)

    def test_supporting_python_files_do_not_enter_canonical_registry(self):
        sources = set((
            ROOT / "training/puffer_compiled_backend_sources.txt"
        ).read_text(encoding="utf-8").splitlines())
        extras = {
            "pufferlib/__init__.py", "pufferlib/models.py", "pufferlib/muon.py",
        }
        self.assertTrue(extras.isdisjoint(sources))
        for runner in ("run_reward_screen.sh", "run_reward_ablation.sh"):
            body = (ROOT / "tools" / runner).read_text(encoding="utf-8")
            self.assertIn("supporting_python_sources_sha256", body)
            for extra in extras:
                self.assertIn(extra, body)

    def test_patch_order_and_lineage_gate_are_preserved(self):
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(encoding="utf-8")
        block = screen.split("patches = [", 1)[1].split(
            "supporting_python_sources = [", 1)[0]
        patches = re.findall(r'training/([^"/]+\.patch)', block)
        self.assertEqual(patches[-7:], [
            "puffer_rollout_transition_closure.patch",
            "puffer_entropy_schedule_parity.patch",
            "puffer_native_entropy_diagnostics.patch",
            "puffer_compact_qualification_snapshot.patch",
            "puffer_reward_clamp_range.patch",
            "puffer_terminal_aware_torch.patch",
            "puffer_terminal_aware_native.patch",
        ])
        self.assertIn("puffer_mingru_direct_recurrence_candidate.patch", patches)
        self.assertLess(
            patches.index("puffer_mingru_direct_recurrence_candidate.patch"),
            patches.index("puffer_recurrent_cuda_qualification.patch"),
        )
        self.assertNotIn("puffer_dual_forward_qualification.patch", patches)
        self.assertNotIn("puffer_mingru_direct_derivative_fixture.patch", patches)
        lineage = (ROOT / "tools/checkpoint_lineage.py").read_text(encoding="utf-8")
        keys = re.search(r"SHA256_KEYS = \((.*?)\)", lineage, re.S).group(1)
        self.assertNotIn("vendor_source_sha256", keys)
        self.assertEqual(sum(name in keys for name in (
            "source_sha256", "compiled_module_sha256",
            "puffer_patch_bundle_sha256")), 3)


if __name__ == "__main__":
    unittest.main()
