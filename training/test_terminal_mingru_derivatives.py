from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

import numpy as np


PATH = Path(__file__).with_name("verify_terminal_mingru_derivatives.py")
SPEC = importlib.util.spec_from_file_location("terminal_derivative_verifier", PATH)
VERIFIER = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VERIFIER)


class TerminalDerivativeVerifierTests(unittest.TestCase):
    def test_cases_cover_start_middle_consecutive_and_no_reset(self) -> None:
        stacked = np.stack(VERIFIER.CASES)
        self.assertTrue(np.any(stacked[:, :, 0] == 1))
        self.assertTrue(np.any(stacked[:, :, 1:-1] == 1))
        self.assertTrue(any(np.any(row[:-1] * row[1:]) for case in stacked for row in case))
        self.assertTrue(any(np.all(row == 0) for case in stacked for row in case))

    def test_nonfinite_native_evidence_is_rejected_after_persistence(self) -> None:
        arrays = {"grad_initial_state": np.array([0.0, np.nan], dtype=np.float32)}
        with tempfile.TemporaryDirectory() as temporary:
            artifact = VERIFIER.persist_case(Path(temporary), 0, arrays)
            with self.assertRaisesRegex(RuntimeError, "non-finite"):
                VERIFIER.require_finite(arrays, "native")
            self.assertEqual(artifact["sha256"], VERIFIER.q.sha256(Path(artifact["path"])))


if __name__ == "__main__":
    unittest.main()
