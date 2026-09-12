#!/usr/bin/env python3
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "training" / "puffer_native_entropy_diagnostics.patch"


class NativeEntropyDiagnosticsPatchTest(unittest.TestCase):
    def test_patch_is_read_only_instrumentation(self):
        text = PATCH.read_text()
        self.assertIn("qualification_entropy_gradient_state", text)
        self.assertIn("qualification_graph_execution", text)
        self.assertIn("ppo-entropy-preclip-gradient-v1", text)
        self.assertIn("qualification_execution_counts", text)
        for forbidden in ("ppo_loss_fwd_bwd(", "muon_update(",
                          "cudaGraphLaunch(", "train_impl("):
            self.assertNotIn(forbidden, text)

    def test_patch_exports_both_surfaces(self):
        text = PATCH.read_text()
        self.assertEqual(text.count('m.def("qualification_entropy_gradient_state"'), 1)
        self.assertEqual(text.count('m.def("qualification_graph_execution"'), 1)


if __name__ == "__main__":
    unittest.main()
