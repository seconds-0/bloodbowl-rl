"""Shape-changing obs-v6 migration and removed raw-bridge launch contracts.

Historical bridge evidence remains in immutable manifests and analyzer fixtures.
Active launchers must not reinterpret an unlabeled v4/v5/v6 blob as obs-v7.
The typed converter/lineage route may mint only a qualification sidecar until a
separate acceptance contract exists.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ARM = ROOT / "tools/run_reward_ablation.sh"
SCREEN = ROOT / "tools/run_reward_screen.sh"
LINEAGE = ROOT / "tools/checkpoint_lineage.py"


def run(path: Path, **extra: str) -> subprocess.CompletedProcess[str]:
    env = {
        key: value for key, value in os.environ.items()
        if key not in {
            "TAG", "REWARD_MANIFEST", "BOOTSTRAP_MODE", "WARM", "POOL",
            "EXPECTED_POOL_HASH", "STEPS", "SCREEN_PROFILE",
        }
    }
    env.update({
        "TAG": "migration-contract-test",
        "REWARD_MANIFEST": "missing.json",
        "STEPS": "50000000",
        **extra,
    })
    return subprocess.run(
        ["bash", str(path)], cwd=ROOT, env=env, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
    )


class RemovedRawBridgeTests(unittest.TestCase):
    def test_arm_rejects_old_raw_bridge_mode_before_checkpoint_io(self):
        result = run(
            ARM, BOOTSTRAP_MODE="bridge-v4", WARM="missing-v4.bin",
            POOL="missing-pool", EXPECTED_POOL_HASH="0" * 64,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BOOTSTRAP_MODE must be", result.stderr)
        self.assertNotIn("missing warm checkpoint", result.stderr)

    def test_screen_rejects_old_raw_bridge_profile_before_artifact_io(self):
        result = run(SCREEN, SCREEN_PROFILE="bridge")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("legacy bridge is not valid for shape-changing obs-v7",
                      result.stderr)

    def test_migrated_checkpoint_cannot_bootstrap_training(self):
        result = run(ARM, BOOTSTRAP_MODE="migration-v6")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("qualification/evaluation only", result.stderr)
        self.assertIn("cannot publish eligible ancestry", result.stderr)


class TypedMigrationQualificationTests(unittest.TestCase):
    def test_lineage_cli_exposes_only_explicit_migration_inputs(self):
        source = LINEAGE.read_text(encoding="utf-8")
        for token in (
            '"migrate-v6"',
            '"--migration-manifest"',
            '"--source-lineage"',
            '"--target-module"',
            '"--target-source-sha256"',
            '"--target-patch-bundle-sha256"',
            '"--allow-qualification"',
            "native_obs_v6_to_v7_zero_extended",
        ):
            self.assertIn(token, source)

    def test_migration_sidecar_contract_is_ineligible_and_hash_bound(self):
        source = LINEAGE.read_text(encoding="utf-8")
        for token in (
            '"qualification_only": True',
            '"eligible": False',
            '"source_checkpoint_sha256"',
            '"source_lineage_sha256"',
            '"migration_manifest_sha256"',
            '"zeroed_columns": [814, 815]',
            '"appended_columns": [2782, 2850]',
        ):
            self.assertIn(token, source)


if __name__ == "__main__":
    unittest.main()
