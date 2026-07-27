#!/usr/bin/env python3

import ast
import os
import re
import struct
import subprocess
import tempfile
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
        self.assertNotIn(6, versions)
        self.assertIn("ver not in _BC_VERSIONS", patch)
        self.assertLess(
            patch.index("ver not in _BC_VERSIONS"),
            patch.index("if hdr is None:"),
            "v5/v6 must be rejected before the historical shape-only comparison",
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
        self.assertIn("Current training requires BBP v6/2782/454", result.stderr)

    def test_rejected_torch_launcher_requires_archived_pre_v5_pairs(self):
        script = (ROOT / "tools" / "run_bcreg.sh").read_text(
            encoding="utf-8")
        self.assertIn(
            "LEGACY_BCREG_PAIRS_DIR",
            script,
            "historical reproduction must require an explicit archived "
            "v1-v4 corpus instead of reusing the current pairs directory",
        )
        self.assertNotIn(
            "run validation/extract_pairs.py",
            script,
            "the current extractor emits v6, which the frozen v1-v4 loader "
            "cannot consume",
        )
        self.assertNotIn(
            '--train.bc-pairs-dir "$ROOT/validation/pairs"',
            script,
            "the historical launcher must not silently target current pairs",
        )

    def test_rejected_torch_launcher_cannot_override_locked_pair_dir(self):
        env = os.environ.copy()
        env["ALLOW_LEGACY_BCREG"] = "1"
        env.pop("LEGACY_BCREG_PAIRS_DIR", None)
        result = subprocess.run(
            [
                "bash",
                "tools/run_bcreg.sh",
                "--train.bc-pairs-dir",
                "/tmp/unvalidated-bbp-pairs",
            ],
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "cannot override --train.bc-pairs-dir",
            result.stderr,
            "the preflighted archived corpus must be the corpus passed to the "
            "frozen trainer even when argparse receives duplicate options",
        )
        script = (ROOT / "tools" / "run_bcreg.sh").read_text(
            encoding="utf-8")
        self.assertLess(
            script.index('"$@"'),
            script.index('--train.bc-pairs-dir "$LEGACY_PAIRS"'),
            "the locked, preflighted pair directory must remain the final "
            "argparse value after all caller-supplied overrides",
        )

    def test_rejected_torch_launcher_rejects_fabricated_archived_tuple(self):
        with tempfile.TemporaryDirectory() as tmp:
            pair_dir = Path(tmp)
            (pair_dir / "25.bbp").write_bytes(
                struct.pack("<4sIII", b"BBP1", 4, 8, 454))
            env = os.environ.copy()
            env["ALLOW_LEGACY_BCREG"] = "1"
            env["LEGACY_BCREG_PAIRS_DIR"] = str(pair_dir)
            result = subprocess.run(
                ["bash", "tools/run_bcreg.sh"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertEqual(result.returncode, 1)
        self.assertIn("requires a known BBP v1-v4 tuple", result.stderr)
        self.assertIn("v4/8/454", result.stderr)


if __name__ == "__main__":
    unittest.main()
