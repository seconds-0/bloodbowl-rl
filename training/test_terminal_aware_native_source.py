from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from training.verify_terminal_aware_native_source import CONTRACT, verify


ROOT = Path(__file__).resolve().parents[1]
FROZEN = ROOT / "audit-artifacts/memory-native-20260905/frozen-source"
PATCH = ROOT / "training/puffer_terminal_aware_native.patch"
V1_PATCH = (ROOT / "audit-artifacts/memory-native-20260905/patch-history"
            / "puffer_terminal_aware_native.5498b516-v1.patch")


class TerminalAwareNativeSourceTests(unittest.TestCase):
    def test_frozen_source_reproduces_missing_contract(self) -> None:
        errors = verify(FROZEN)
        self.assertTrue(errors)
        self.assertTrue(any("compiled contract" in error for error in errors))
        self.assertTrue(any("evaluation mode" in error for error in errors))

    def test_patch_applies_and_closes_source_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            src = target / "src"
            src.mkdir()
            for name in ("models.cu", "pufferlib.cu", "bindings.cu", "bindings_cpu.cpp"):
                (src / name).write_bytes((FROZEN / name).read_bytes())
            subprocess.run(
                ["git", "apply", "--check", str(PATCH)], cwd=target, check=True
            )
            subprocess.run(["git", "apply", str(PATCH)], cwd=target, check=True)
            self.assertEqual([], verify(target))
            self.assertIn(CONTRACT, (src / "bindings.cu").read_text())
            binding_text = (src / "bindings.cu").read_text()
            self.assertNotIn("py::dict b = py::dict(meta)", binding_text)
            self.assertNotIn("py::dict ti = py::dict(meta)", binding_text)
            self.assertNotIn("py::dict tw = py::dict(meta)", binding_text)

    def test_v1_snapshot_dictionary_alias_is_reproduced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)
            src = target / "src"
            src.mkdir()
            for name in ("models.cu", "pufferlib.cu", "bindings.cu", "bindings_cpu.cpp"):
                (src / name).write_bytes((FROZEN / name).read_bytes())
            subprocess.run(["git", "apply", str(V1_PATCH)], cwd=target, check=True)
            errors = verify(target)
            self.assertTrue(any("aliases behavior/tail dictionaries" in e for e in errors))


if __name__ == "__main__":
    unittest.main()
