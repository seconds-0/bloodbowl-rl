import copy
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "validate_runtime_plan_identity.py"
SPEC = importlib.util.spec_from_file_location("runtime_identity", MODULE)
runtime_identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(runtime_identity)
ARTIFACT = ROOT / "audit-artifacts" / "canary-recovery-plan-v9-r2-20260905"


class RuntimePlanIdentityTests(unittest.TestCase):
    def setUp(self):
        self.plan_path = ARTIFACT / "PLAN.json"
        self.manifest_path = ARTIFACT / "ACTUAL_V9_SCREEN_MANIFEST.json"

    def test_actual_v9_r2_bug_is_rejected(self):
        with self.assertRaisesRegex(
            runtime_identity.IdentityError,
            "compiled_backend_source_registry_sha256",
        ):
            runtime_identity.validate(self.plan_path, self.manifest_path)

    def test_correcting_only_registry_digest_accepts_same_pinned_manifest(self):
        plan = json.loads(self.plan_path.read_text())
        manifest = json.loads(self.manifest_path.read_text())
        plan["screen_implementation"]["compiled_backend_source_registry_sha256"] = (
            manifest["contract"]["implementation"]
            ["compiled_backend_source_registry_sha256"]
        )
        with tempfile.TemporaryDirectory() as directory:
            corrected = Path(directory) / "PLAN.json"
            corrected.write_text(json.dumps(plan))
            result = runtime_identity.validate(corrected, self.manifest_path)
        self.assertTrue(result["accepted"])
        self.assertEqual(
            result["plan_only_manifest_sha256"],
            plan["pinned_files"]["actual_plan_only_manifest"]["sha256"],
        )

    def test_manifest_byte_tampering_rejects_before_identity_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            tampered = Path(directory) / "manifest.json"
            tampered.write_text(self.manifest_path.read_text() + "\n")
            with self.assertRaisesRegex(runtime_identity.IdentityError, "bytes"):
                runtime_identity.validate(self.plan_path, tampered)

    def test_any_other_implementation_difference_rejects(self):
        plan = json.loads(self.plan_path.read_text())
        manifest = json.loads(self.manifest_path.read_text())
        plan["screen_implementation"] = copy.deepcopy(
            manifest["contract"]["implementation"]
        )
        plan["screen_implementation"]["compiled_module_sha256"] = "0" * 64
        with tempfile.TemporaryDirectory() as directory:
            changed = Path(directory) / "PLAN.json"
            changed.write_text(json.dumps(plan))
            with self.assertRaisesRegex(
                runtime_identity.IdentityError, "compiled_module_sha256"
            ):
                runtime_identity.validate(changed, self.manifest_path)


if __name__ == "__main__":
    unittest.main()
