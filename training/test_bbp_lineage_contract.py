#!/usr/bin/env python3

import ast
import os
import re
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class HistoricalBcregLineageContractTests(unittest.TestCase):
    def test_rejected_torch_loader_is_frozen_before_v5(self):
        patch = (ROOT / "training" / "torch_pufferl_bcreg.patch").read_text(
            encoding="utf-8")
        match = re.search(
            r"_BC_VERSIONS, _BC_HEADER_LEN = b'BBP1', (\([^\n]+\)), 16",
            patch,
        )
        self.assertIsNotNone(match)
        versions = ast.literal_eval(match.group(1))
        self.assertEqual(versions, (1, 2, 3, 4))
        self.assertNotIn(5, versions)
        self.assertIn("ver not in _BC_VERSIONS", patch)
        self.assertLess(
            patch.index("ver not in _BC_VERSIONS"),
            patch.index("if hdr is None:"),
            "v5 must be rejected before the historical shape-only comparison",
        )

    def test_rejected_torch_launcher_requires_legacy_opt_in(self):
        env = os.environ.copy()
        env.pop("ALLOW_LEGACY_BCREG", None)
        result = subprocess.run(
            ["bash", "tools/run_bcreg.sh"],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("historical BBP/checkpoint-v1 reproduction", result.stderr)
        self.assertIn("Current training requires BBP v5/2782/454", result.stderr)


if __name__ == "__main__":
    unittest.main()
