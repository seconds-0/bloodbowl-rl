#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from tools import checkpoint_lineage


def digest(data):
    return hashlib.sha256(data).hexdigest()


class CheckpointLineageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.checkpoint = self.root / "policy.bin"
        self.checkpoint.write_bytes(
            b"exact-v5-policy" + b"\0" * (
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES -
                len(b"exact-v5-policy")))
        self.original_checkpoint = self.checkpoint.read_bytes()
        self.run_manifest = self.root / "RUN_MANIFEST.json"
        self.run_manifest.write_text(json.dumps({
            "schema_version": 1,
            "mode": "native_fresh_v5_qualification",
            "seed": "42",
            "observation_abi": "obs-v5",
            "observation_version": "5",
            "action_abi": "exact-joint-v1",
            "initialization": "fresh",
            "qualification_only": "1",
            "policy_hidden_size": "512",
            "policy_num_layers": "3",
            "policy_expansion_factor": "1",
            "expected_checkpoint_bytes": str(
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES),
            "source_sha256": "1" * 64,
            "compiled_module_sha256": "2" * 64,
            "puffer_patch_bundle_sha256": "3" * 64,
            "screen_manifest_sha256": "4" * 64,
            "warm_lineage_sha256": "",
            "pool_lineage_bundle_sha256": "",
        }, sort_keys=True) + "\n", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def expected(self):
        return {
            "source_sha256": "1" * 64,
            "compiled_module_sha256": "2" * 64,
            "puffer_patch_bundle_sha256": "3" * 64,
        }

    def create(self):
        payload = checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest)
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        return payload, sidecar

    def test_round_trip_binds_checkpoint_runtime_and_producer(self):
        payload, sidecar = self.create()
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=False)
        self.assertEqual(observed, payload)
        self.assertEqual(payload["checkpoint"]["sha256"],
                         digest(self.checkpoint.read_bytes()))
        self.assertEqual(payload["producer"]["run_manifest_sha256"],
                         digest(self.run_manifest.read_bytes()))
        self.assertFalse(payload["ancestry"]["eligible"])
        self.assertTrue(payload["ancestry"]["qualification_only"])
        self.assertEqual(
            sidecar.read_bytes(), checkpoint_lineage.canonical_bytes(payload))

    def test_qualification_output_is_never_eligible_ancestry(self):
        _, sidecar = self.create()
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "qualification-only"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected(),
                require_eligible=True)

    def test_eligible_nonqualification_lineage_round_trips(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["qualification_only"] = "0"
        manifest["initialization"] = "lineage-v5"
        manifest["mode"] = "native_static_pool_reward_ablation"
        manifest["warm_lineage_sha256"] = "5" * 64
        manifest["pool_lineage_bundle_sha256"] = "6" * 64
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        payload = checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest,
            allow_eligible_publication=True)
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=True)
        self.assertTrue(observed["ancestry"]["eligible"])
        self.assertEqual(observed["ancestry"]["warm_lineage_sha256"],
                         "5" * 64)

    def test_missing_malformed_and_noncanonical_sidecars_fail_closed(self):
        missing = self.root / "missing.json"
        with self.assertRaisesRegex(checkpoint_lineage.LineageError, "missing"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, missing, expected=self.expected())

        malformed = self.root / "malformed.json"
        malformed.write_text("{not json}\n", encoding="utf-8")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError, "JSON"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, malformed, expected=self.expected())

        payload, sidecar = self.create()
        sidecar.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "canonical"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected())

    def test_checkpoint_and_every_runtime_identity_are_hash_bound(self):
        _, sidecar = self.create()
        self.checkpoint.write_bytes(b"changed-policy")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "checkpoint"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected())

        self.checkpoint.write_bytes(self.original_checkpoint)
        for key in checkpoint_lineage.SHA256_KEYS:
            with self.subTest(key=key):
                expected = self.expected()
                expected[key] = "wrong" if isinstance(expected[key], str) else 999
                with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                            key):
                    checkpoint_lineage.validate_lineage(
                        self.checkpoint, sidecar, expected=expected)

    def test_frozen_compatibility_cannot_be_overridden_by_caller(self):
        _, sidecar = self.create()
        for key, value in (
            ("observation_abi", "obs-v4"),
            ("observation_version", 4),
            ("action_abi", "marginal-heads-v1"),
            ("policy_hidden_size", 999),
        ):
            with self.subTest(key=key):
                with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError,
                        "implementation digests"):
                    checkpoint_lineage.validate_lineage(
                        self.checkpoint, sidecar,
                        expected={key: value}, require_eligible=False)
                with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError,
                        "implementation digests"):
                    checkpoint_lineage._parse_expected([f"{key}={value}"])

    def test_modified_manifest_cannot_relabel_qualification_as_eligible(self):
        self.create()
        copied = self.root / "copied-policy.bin"
        copied.write_bytes(self.checkpoint.read_bytes())
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest.update({
            "mode": "native_static_pool_reward_ablation",
            "qualification_only": "0",
            "initialization": "lineage-v5",
            "warm_lineage_sha256": "5" * 64,
            "pool_lineage_bundle_sha256": "6" * 64,
        })
        relabel = self.root / "relabel.json"
        relabel.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "accepted screen result materialization"):
            checkpoint_lineage.lineage_from_run_manifest(copied, relabel)

    def test_current_checkpoint_size_is_frozen_at_create_and_validate(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["expected_checkpoint_bytes"] = "13670400"
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "expected_checkpoint_bytes must be"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest)

        manifest["expected_checkpoint_bytes"] = str(
            checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES)
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        payload, sidecar = self.create()
        self.checkpoint.write_bytes(b"legacy-sized")
        payload["checkpoint"] = {
            "bytes": self.checkpoint.stat().st_size,
            "sha256": digest(self.checkpoint.read_bytes()),
        }
        checkpoint_lineage.write_lineage(sidecar, payload, replace=True)
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "current ABI requires"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected(),
                require_eligible=False)

    def test_same_size_legacy_semantics_are_rejected(self):
        payload, sidecar = self.create()
        payload["compatibility"]["observation_abi"] = "obs-v4"
        payload["compatibility"]["observation_version"] = 4
        payload["compatibility"]["action_abi"] = "marginal-heads-v1"
        checkpoint_lineage.write_lineage(sidecar, payload, replace=True)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "observation_abi"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected())

    def test_producer_manifest_rejects_missing_or_invalid_contract_fields(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        for key, bad in (
            ("qualification_only", "maybe"),
            ("qualification_only", "0"),
            ("source_sha256", "short"),
            ("observation_version", "4"),
            ("initialization", "legacy-v4"),
        ):
            with self.subTest(key=key):
                changed = dict(manifest)
                changed[key] = bad
                self.run_manifest.write_text(
                    json.dumps(changed) + "\n", encoding="utf-8")
                with self.assertRaises(checkpoint_lineage.LineageError):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest)


if __name__ == "__main__":
    unittest.main()
