import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]


class CampaignTrainerPortTests(unittest.TestCase):
    def test_rollout_port_preserves_evaluation_and_consumes_training_tail(self):
        patch = (ROOT / "training/puffer_rollout_transition_closure.patch").read_text()
        self.assertIn("and not self.evaluation_mode", patch)
        self.assertIn("if not self.tail_valid:", patch)
        self.assertIn("self.tail_valid = False", patch)
        self.assertIn("require_fresh_training_tail(pufferl);", patch)
        self.assertIn("consume_training_tail(pufferl);", patch)
        self.assertIn('rollout_transition_contract") = "tail-bootstrap-v1"', patch)

    def test_entropy_port_uses_dynamic_device_coefficient(self):
        patch = (ROOT / "training/puffer_entropy_schedule_parity.patch").read_text()
        self.assertIn("entropy_coefficient_for_update", patch)
        self.assertIn("enqueue_entropy_coefficient", patch)
        self.assertIn("effective_ent_coef", patch)
        self.assertIn("entropy_schedule_contract", patch)
        self.assertIn("clamp(-8, 8)", patch)

    def test_installer_orders_and_hashes_all_changed_sources(self):
        installer = (ROOT / "tools/install_puffer_env.sh").read_text()
        rollout = installer.index("# Rollout-transition closure")
        qualification = installer.index("# Read-only CUDA qualification evidence")
        entropy = installer.index("# Entropy-schedule parity")
        self.assertLess(rollout, qualification)
        self.assertLess(qualification, entropy)
        diagnostics = installer.index("# Read-only native entropy and graph execution diagnostics")
        compact = installer.index("# Keep the existing snapshot default")
        self.assertLess(entropy, diagnostics)
        self.assertLess(diagnostics, compact)
        registry = (ROOT / "training/puffer_compiled_backend_sources.txt").read_text()
        for source in (
            "pufferlib/pufferl.py", "pufferlib/sweep.py",
            "pufferlib/torch_pufferl.py", "src/bindings.cu",
            "src/bindings_cpu.cpp", "src/pufferlib.cu", "src/vecenv.h"):
            self.assertIn(source, registry)


if __name__ == "__main__":
    unittest.main()
