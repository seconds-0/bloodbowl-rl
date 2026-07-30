#!/usr/bin/env python3
"""Source and exact-install contracts for the F5 qualification role."""

from __future__ import annotations

import pathlib
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training/puffer_f5_trainability_role.patch"


class F5RolePatchContract(unittest.TestCase):
    def test_patch_exports_role_in_both_bindings(self) -> None:
        source = PATCH.read_text(encoding="utf-8")
        self.assertIn("+++ b/src/bindings_cpu.cpp", source)
        self.assertIn("+++ b/src/bindings.cu", source)
        self.assertEqual(
            source.count('m.attr("qualification_fixture_role")'), 2
        )
        self.assertEqual(
            source.count('m.attr("qualification_fixture_match_sha256")'), 2
        )
        self.assertEqual(
            source.count('m.attr("qualification_fixture_bbs_sha256")'), 2
        )
        self.assertEqual(
            source.count('m.attr("qualification_fixture_max_decisions")'), 2
        )

    def test_patch_does_not_add_state_bank_authority(self) -> None:
        source = PATCH.read_text(encoding="utf-8")
        added = "\n".join(
            line[1:]
            for line in source.splitlines()
            if line.startswith("+") and not line.startswith("+++")
        )
        self.assertNotIn("test_only_allow_authored", added)
        self.assertNotIn("PRODUCTION_AUTHORIZED_PRODUCER_KINDS", added)
        self.assertNotIn("BBE_STATE_BANK_AUTHORED_SCENARIO", added)

    def test_installer_has_separate_role_checker(self) -> None:
        source = (ROOT / "tools/install_f5_trainability_env.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("f5-fixed-state-v1", source)
        self.assertIn("--check", source)
        self.assertNotIn("--fixture-path", source)
        self.assertNotIn("--fixture-sha256", source)
        self.assertNotIn("--authored-source-id", source)

    def test_standard_installer_has_no_role_enable_option(self) -> None:
        source = (ROOT / "tools/install_puffer_env.sh").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("--f5-trainability", source)
        self.assertNotIn("--qualification-fixture", source)


if __name__ == "__main__":
    unittest.main()
