#!/usr/bin/env python3
"""Watched contract tests for the sealed F5 trainability foundation."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import subprocess
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
EXPECTED_FULL_BBS = (
    "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1"
)
EXPECTED_F5_BBS = (
    "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71"
)
EXPECTED_MATCH = (
    "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2"
)


class F5FoundationSourceContract(unittest.TestCase):
    def test_required_owned_surfaces_exist(self) -> None:
        for relative in (
            "puffer/bloodbowl/f5_trainability.h",
            "puffer/bloodbowl/f5_trainability_fixture.generated.h",
            "tools/f5_trainability_foundation.c",
            "tools/run_f5_trainability_foundation.py",
            "tools/verify_f5_trainability_foundation.py",
            "training/puffer_f5_trainability_role.patch",
            "training/test_f5_trainability_role.py",
        ):
            self.assertTrue((ROOT / relative).is_file(), relative)

    def test_state_bank_authorization_remains_empty(self) -> None:
        source = (ROOT / "tools/state_bank_contract.py").read_text(
            encoding="utf-8"
        )
        self.assertRegex(
            source,
            r"PRODUCTION_AUTHORIZED_PRODUCER_KINDS(?:\s*:\s*[^=\n]+)?"
            r"\s*=\s*frozenset\(\)",
        )
        self.assertIn("AUTHORED_NOT_IMPLEMENTED", source)
        self.assertNotIn("f5-fixed-state-v1", source)

    def test_ordinary_build_is_explicitly_role_none(self) -> None:
        source = (ROOT / "puffer/bloodbowl/state_bank_build.h").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '#define PUFFER_QUALIFICATION_FIXTURE_ROLE "none"', source
        )
        self.assertIn(
            "#define PUFFER_QUALIFICATION_FIXTURE_ENABLED 0", source
        )

    def test_generator_watches_complete_hashes_and_identity(self) -> None:
        source = (ROOT / "tools/f5_trainability_foundation.c").read_text(
            encoding="utf-8"
        )
        for expected in (
            EXPECTED_FULL_BBS,
            EXPECTED_F5_BBS,
            EXPECTED_MATCH,
            "0xA9000019",
            "0xAE00001A",
            "ad_build_authored_proof_bundle",
            "ad_identify_authored_proof_bundle",
        ):
            self.assertIn(expected, source)

    def test_production_launchers_reject_fixture_roles(self) -> None:
        for relative in (
            "tools/run_reward_ablation.sh",
            "tools/run_reward_screen.sh",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn("qualification_fixture_role", source, relative)
            self.assertIn("f5-fixed-state-v1", source, relative)


class F5FoundationCliContract(unittest.TestCase):
    def _load_runner(self):
        path = ROOT / "tools/run_f5_trainability_foundation.py"
        spec = importlib.util.spec_from_file_location("f5_foundation_runner", path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_runner_has_closed_schema_and_no_training_mode(self) -> None:
        module = self._load_runner()
        self.assertEqual(
            module.EVIDENCE_SCHEMA, "bloodbowl-f5-foundation-evidence-v1"
        )
        self.assertEqual(module.FIXTURE_ROLE, "f5-fixed-state-v1")
        self.assertNotIn("train", module.COMMANDS)
        self.assertNotIn("ppo", module.COMMANDS)

    def test_generator_is_byte_deterministic(self) -> None:
        binary = ROOT / "build/f5_trainability_foundation"
        subprocess.run(
            ["make", str(binary.relative_to(ROOT))],
            cwd=ROOT,
            check=True,
        )
        with tempfile.TemporaryDirectory(prefix="f5-red-") as directory:
            first = pathlib.Path(directory) / "first"
            second = pathlib.Path(directory) / "second"
            for output in (first, second):
                subprocess.run(
                    [str(binary), "generate", "--output", str(output)],
                    cwd=ROOT,
                    check=True,
                )
            first_files = {
                path.relative_to(first): path.read_bytes()
                for path in first.rglob("*")
                if path.is_file()
            }
            second_files = {
                path.relative_to(second): path.read_bytes()
                for path in second.rglob("*")
                if path.is_file()
            }
            self.assertEqual(first_files, second_files)
            descriptor = json.loads(
                (first / "task.json").read_text(encoding="ascii")
            )
            self.assertEqual(descriptor["full_bundle_sha256"], EXPECTED_FULL_BBS)
            self.assertEqual(descriptor["f5_bbs_sha256"], EXPECTED_F5_BBS)
            self.assertEqual(descriptor["raw_match_sha256"], EXPECTED_MATCH)
            self.assertEqual(
                hashlib.sha256((first / "f5.bbs").read_bytes()).hexdigest(),
                EXPECTED_F5_BBS,
            )


if __name__ == "__main__":
    unittest.main()
