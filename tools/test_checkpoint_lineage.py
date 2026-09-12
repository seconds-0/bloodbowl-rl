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
            b"exact-v6-policy" + b"\0" * (
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES -
                len(b"exact-v6-policy")))
        self.original_checkpoint = self.checkpoint.read_bytes()
        self.run_manifest = self.root / "RUN_MANIFEST.json"
        self.run_manifest.write_text(json.dumps({
            "schema_version": 1,
            "mode": "native_fresh_v7_qualification",
            "seed": "42",
            "observation_abi": "obs-v7",
            "observation_version": "7",
            "action_abi": "exact-joint-v1",
            "compiled_rollout_transition_contract": "terminal-aware-tbptt-v1",
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
        self.assertEqual(
            payload["compatibility"]["rollout_transition_contract"],
            "terminal-aware-tbptt-v1")

    def test_manifest_must_explicitly_name_a_supported_recurrent_contract(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        del manifest["compiled_rollout_transition_contract"]
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "compiled_rollout_transition_contract"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest)

        manifest["compiled_rollout_transition_contract"] = "shape-is-enough-v1"
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "unsupported rollout transition"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest)

    def test_training_mode_requires_explicit_matching_recurrent_contract(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["compiled_rollout_transition_contract"] = "tail-bootstrap-v1"
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        _, sidecar = self.create()
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "rollout_transition_contract lineage mismatch"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected(),
                require_eligible=False, recurrent_contract_mode="training",
                expected_rollout_transition_contract="terminal-aware-tbptt-v1")

        payload = json.loads(sidecar.read_text(encoding="utf-8"))
        del payload["compatibility"]["rollout_transition_contract"]
        checkpoint_lineage.write_lineage(sidecar, payload, replace=True)
        for mode in ("inference", "qualification"):
            observed = checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected(),
                require_eligible=False, recurrent_contract_mode=mode)
            self.assertNotIn(
                "rollout_transition_contract", observed["compatibility"])
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "explicit rollout_transition_contract"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected(),
                require_eligible=False, recurrent_contract_mode="training",
                expected_rollout_transition_contract="terminal-aware-tbptt-v1")

    def test_terminal_aware_lineage_is_training_eligible_only_when_requested(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["compiled_rollout_transition_contract"] = \
            "terminal-aware-tbptt-v1"
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        _, sidecar = self.create()
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=False, recurrent_contract_mode="training",
            expected_rollout_transition_contract="terminal-aware-tbptt-v1")
        self.assertEqual(
            observed["compatibility"]["rollout_transition_contract"],
            "terminal-aware-tbptt-v1")

    def test_training_mode_requires_expected_contract_and_known_mode(self):
        _, sidecar = self.create()
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=False, recurrent_contract_mode="training")
        self.assertEqual(
            observed["compatibility"]["rollout_transition_contract"],
            "terminal-aware-tbptt-v1")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "invalid recurrent_contract_mode"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected(),
                require_eligible=False, recurrent_contract_mode="ambiguous")

    def test_eligible_validation_defaults_current_and_old_requires_reviewed_expectation(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest.update({
            "qualification_only": "0",
            "initialization": "lineage-v7",
            "mode": "native_static_pool_reward_ablation",
            "warm_lineage_sha256": "5" * 64,
            "pool_lineage_bundle_sha256": "6" * 64,
        })
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        payload = checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest,
            allow_eligible_publication=True)
        payload["compatibility"]["rollout_transition_contract"] = \
            "tail-bootstrap-v1"
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "rollout_transition_contract lineage mismatch"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected(),
                require_eligible=True)
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=True,
            expected_rollout_transition_contract="tail-bootstrap-v1")
        self.assertEqual(
            observed["compatibility"]["rollout_transition_contract"],
            "tail-bootstrap-v1")

    def test_old_contract_cannot_be_newly_published_as_eligible(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest.update({
            "compiled_rollout_transition_contract": "tail-bootstrap-v1",
            "qualification_only": "0",
            "initialization": "lineage-v7",
            "mode": "native_static_pool_reward_ablation",
            "warm_lineage_sha256": "5" * 64,
            "pool_lineage_bundle_sha256": "6" * 64,
        })
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "new eligible lineage publication requires"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest,
                allow_eligible_publication=True)

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
        manifest["initialization"] = "lineage-v7"
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

    def test_declared_genesis_is_the_only_eligible_fresh_lineage(self):
        # Without this exception the eligibility rules close into a loop with no
        # entry point: eligible requires non-qualification, non-qualification
        # required non-fresh initialization, non-fresh requires an eligible warm
        # checkpoint and pool, and eligible may only be published by an accepted
        # screen. Nothing could mint the first eligible checkpoint, so obs-v7
        # could never train -- measured on the training host as zero
        # .lineage.json files in existence.
        def manifest_with(**over):
            m = json.loads(self.run_manifest.read_text(encoding="utf-8"))
            m.update(over)
            self.run_manifest.write_text(
                json.dumps(m, sort_keys=True) + "\n", encoding="utf-8")

        # Declared genesis: fresh AND eligible, published by the screen.
        manifest_with(qualification_only="0", initialization="fresh",
                      mode="native_fresh_v7_genesis")
        payload = checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest,
            allow_eligible_publication=True)
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=True)
        self.assertTrue(observed["ancestry"]["eligible"])
        self.assertFalse(observed["ancestry"]["qualification_only"])

        # The exception is narrow. A fresh run that does NOT declare genesis
        # cannot become ancestry, so an ordinary canary stays ineligible even if
        # its qualification flag is flipped.
        manifest_with(qualification_only="0", initialization="fresh",
                      mode="native_fresh_v7_qualification")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "declared genesis"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest,
                allow_eligible_publication=True)

        # Genesis is ancestry by definition, so it may not claim to be
        # qualification-only at the same time.
        manifest_with(qualification_only="1", initialization="fresh",
                      mode="native_fresh_v7_genesis")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "not qualification-only"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest,
                allow_eligible_publication=True)

        # Genesis must actually be fresh; it cannot relabel a warm-started run.
        manifest_with(qualification_only="0", initialization="lineage-v7",
                      mode="native_fresh_v7_genesis")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "must use fresh"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest,
                allow_eligible_publication=True)

        # And genesis still cannot self-publish: only accepted screen result
        # materialization may mint eligible lineage.
        manifest_with(qualification_only="0", initialization="fresh",
                      mode="native_fresh_v7_genesis")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "accepted screen"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest)

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
            "initialization": "lineage-v7",
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

    def test_obs_v5_sidecar_is_refused_against_an_obs_v6_module(self):
        """The v5->v6 lineage trap: same 2782-byte observation, same
        16,203,776-byte checkpoint, different semantics. This is the exact
        shape that cost a 12B-step run across v4/v5, and blob size cannot see
        it, so the declared observation version must be checked explicitly."""
        payload, sidecar = self.create()
        # Precondition: the blob is EXACTLY the size the current ABI demands,
        # so any refusal below cannot have come from the size check.
        self.assertEqual(self.checkpoint.stat().st_size,
                         checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES)
        self.assertEqual(payload["compatibility"]["observation_abi"], "obs-v7")
        self.assertEqual(payload["compatibility"]["observation_version"], 7)

        for abi, version in (("obs-v6", 6), ("obs-v6", 7), ("obs-v7", 6)):
            with self.subTest(abi=abi, version=version):
                stale = json.loads(json.dumps(payload))
                stale["compatibility"]["observation_abi"] = abi
                stale["compatibility"]["observation_version"] = version
                checkpoint_lineage.write_lineage(sidecar, stale, replace=True)
                with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError,
                        "observation_abi/observation_version lineage mismatch"):
                    checkpoint_lineage.validate_lineage(
                        self.checkpoint, sidecar, expected=self.expected(),
                        require_eligible=False)

        # And a v5 run manifest cannot mint a v6 sidecar in the first place.
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["observation_abi"] = "obs-v5"
        stale_manifest = self.root / "stale-abi.json"
        stale_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "observation_abi must be obs-v7"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, stale_manifest)

        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["observation_version"] = "5"
        stale_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "observation_version must be 7"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, stale_manifest)

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


    def _eligible(self):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["qualification_only"] = "0"
        manifest["initialization"] = "lineage-v7"
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
        return payload, sidecar

    def test_rehost_rebinds_only_the_module_and_records_ancestry(self):
        payload, sidecar = self._eligible()
        module = self.root / "_C.so"
        module.write_bytes(b"other-host-build")
        rehosted = checkpoint_lineage.rehost_lineage(
            self.checkpoint, sidecar=sidecar, target_module=module,
            target_source_sha256="1" * 64,
            target_patch_bundle_sha256="3" * 64)
        self.assertEqual(rehosted["implementation"]["compiled_module_sha256"],
                         digest(module.read_bytes()))
        self.assertEqual(rehosted["implementation"]["source_sha256"], "1" * 64)
        self.assertEqual(rehosted["ancestry"]["rehosted_from"],
                         checkpoint_lineage.lineage_digest(payload))
        # Everything else is preserved verbatim.
        for section in ("compatibility", "producer"):
            self.assertEqual(rehosted[section], payload[section])
        self.assertEqual(rehosted["checkpoint"], payload["checkpoint"])
        # And the rehosted sidecar validates against the NEW module, not the old.
        out = self.root / "rehosted.lineage.json"
        checkpoint_lineage.write_lineage(out, rehosted)
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, out, expected={
                "source_sha256": "1" * 64,
                "compiled_module_sha256": digest(module.read_bytes()),
                "puffer_patch_bundle_sha256": "3" * 64,
            }, require_eligible=True)
        self.assertEqual(observed, rehosted)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "compiled_module_sha256 lineage mismatch"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, out, expected=self.expected(),
                require_eligible=True)

    def test_rehost_refuses_source_or_patch_drift_and_qualification(self):
        payload, sidecar = self._eligible()
        module = self.root / "_C.so"
        module.write_bytes(b"other-host-build")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "environment source differs"):
            checkpoint_lineage.rehost_lineage(
                self.checkpoint, sidecar=sidecar, target_module=module,
                target_source_sha256="9" * 64,
                target_patch_bundle_sha256="3" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "patch bundle differs"):
            checkpoint_lineage.rehost_lineage(
                self.checkpoint, sidecar=sidecar, target_module=module,
                target_source_sha256="1" * 64,
                target_patch_bundle_sha256="9" * 64)
        # Same module -> no-op refused (nothing to rehost).
        same = self.root / "same.so"
        same.write_bytes(b"x")
        payload2 = json.loads(json.dumps(payload))
        payload2["implementation"]["compiled_module_sha256"] = digest(b"x")
        side2 = self.root / "same.lineage.json"
        checkpoint_lineage.write_lineage(side2, payload2)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError, "no-op"):
            checkpoint_lineage.rehost_lineage(
                self.checkpoint, sidecar=side2, target_module=same,
                target_source_sha256="1" * 64,
                target_patch_bundle_sha256="3" * 64)
        # A qualification-only (ineligible) sidecar can never be rehosted.
        self.run_manifest.write_text(json.dumps({
            **json.loads(self.run_manifest.read_text(encoding="utf-8")),
            "qualification_only": "1", "initialization": "fresh",
            "mode": "native_fresh_v7_qualification",
            "warm_lineage_sha256": "", "pool_lineage_bundle_sha256": "",
        }, sort_keys=True) + "\n", encoding="utf-8")
        qual = checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest)
        qside = self.root / "qual.lineage.json"
        checkpoint_lineage.write_lineage(qside, qual)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "not eligible ancestry"):
            checkpoint_lineage.rehost_lineage(
                self.checkpoint, sidecar=qside, target_module=module,
                target_source_sha256="1" * 64,
                target_patch_bundle_sha256="3" * 64)

    def test_rehost_cannot_ride_a_substituted_checkpoint(self):
        _, sidecar = self._eligible()
        module = self.root / "_C.so"
        module.write_bytes(b"other-host-build")
        self.checkpoint.write_bytes(b"tampered" + b"\0" * (
            checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES - len(b"tampered")))
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "SHA-256 differs"):
            checkpoint_lineage.rehost_lineage(
                self.checkpoint, sidecar=sidecar, target_module=module,
                target_source_sha256="1" * 64,
                target_patch_bundle_sha256="3" * 64)


class GraftLineageTests(unittest.TestCase):
    """A graft bridges a warm/pool lineage across a source/patch-bundle change.

    The run manifest declares the OLD implementation (all four graft_from_*
    keys or none) and the sidecar records it as ancestry.grafted_from, on top
    of an otherwise ordinary lineage-v7 payload published on the NEW build."""

    OLD = {
        "graft_from_source_sha256": "a" * 64,
        "graft_from_module_sha256": "b" * 64,
        "graft_from_patch_bundle_sha256": "c" * 64,
        "graft_from_warm_lineage_sha256": "5" * 64,
        "graft_reason": "D242",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.checkpoint = self.root / "policy.bin"
        self.checkpoint.write_bytes(
            b"graft" + b"\0" * (
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES - len(b"graft")))
        self.run_manifest = self.root / "RUN_MANIFEST.json"
        self.base = {
            "schema_version": 1,
            "mode": "native_static_pool_reward_ablation",
            "seed": "42",
            "observation_abi": "obs-v7",
            "observation_version": "7",
            "action_abi": "exact-joint-v1",
            "compiled_rollout_transition_contract": "terminal-aware-tbptt-v1",
            "initialization": "lineage-v7",
            "qualification_only": "0",
            "policy_hidden_size": "512",
            "policy_num_layers": "3",
            "policy_expansion_factor": "1",
            "expected_checkpoint_bytes": str(
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES),
            "source_sha256": "1" * 64,
            "compiled_module_sha256": "2" * 64,
            "puffer_patch_bundle_sha256": "3" * 64,
            "screen_manifest_sha256": "4" * 64,
            "warm_lineage_sha256": "5" * 64,
            "pool_lineage_bundle_sha256": "6" * 64,
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, **over):
        manifest = dict(self.base)
        manifest.update(over)
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    def create(self):
        return checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest,
            allow_eligible_publication=True)

    def expected(self):
        return {"source_sha256": "1" * 64, "compiled_module_sha256": "2" * 64,
                "puffer_patch_bundle_sha256": "3" * 64}

    def test_graft_round_trips_and_records_the_old_build(self):
        self.write(**self.OLD)
        payload = self.create()
        self.assertEqual(payload["ancestry"]["grafted_from"], {
            "warm_lineage_sha256": "5" * 64,
            "source_sha256": "a" * 64,
            "compiled_module_sha256": "b" * 64,
            "puffer_patch_bundle_sha256": "c" * 64,
            "reason": "D242",
        })
        # Published on the NEW build's digests, ordinary lineage-v7 otherwise.
        self.assertEqual(payload["implementation"], self.expected())
        self.assertEqual(payload["ancestry"]["initialization"], "lineage-v7")
        self.assertTrue(payload["ancestry"]["eligible"])
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=True)
        self.assertEqual(observed, payload)

    def test_no_graft_keys_means_no_grafted_from(self):
        self.write()
        payload = self.create()
        self.assertNotIn("grafted_from", payload["ancestry"])

    def test_partial_graft_keys_are_refused(self):
        for drop in self.OLD:
            partial = {k: v for k, v in self.OLD.items() if k != drop}
            self.write(**partial)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "all-or-none"):
                self.create()

    def test_malformed_graft_reason_is_refused(self):
        for bad in ("", "   ", 7, None, "x" * 201):
            self.write(**{**self.OLD, "graft_reason": bad})
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "graft_reason"):
                self.create()
        self.write(**{**self.OLD, "graft_reason": "y" * 200})
        self.assertEqual(self.create()["ancestry"]["grafted_from"]["reason"],
                         "y" * 200)

    def test_malformed_graft_sha_is_refused(self):
        for key in self.OLD:
            if key == "graft_reason":
                continue
            for bad in ("", "A" * 64, "a" * 63, 7, None):
                self.write(**{**self.OLD, key: bad})
                with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                            key):
                    self.create()

    def test_graft_warm_digest_must_match_the_warm_lineage(self):
        self.write(**{**self.OLD, "graft_from_warm_lineage_sha256": "7" * 64})
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "differs from warm_lineage_sha256"):
            self.create()

    def test_graft_requires_lineage_v6_initialization(self):
        self.write(**{**self.OLD, "graft_from_warm_lineage_sha256": "5" * 64},
                   initialization="fresh", mode="native_fresh_v7_genesis",
                   warm_lineage_sha256="", pool_lineage_bundle_sha256="")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "lineage-v7"):
            self.create()

    def test_graft_onto_the_identical_source_and_patch_is_refused_as_a_no_op(self):
        # Even with a different module: that is a rehost, not a graft.
        for module in ("2" * 64, "b" * 64):
            self.write(**{**self.OLD,
                          "graft_from_source_sha256": "1" * 64,
                          "graft_from_module_sha256": module,
                          "graft_from_patch_bundle_sha256": "3" * 64})
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "no-op.*rehost"):
                self.create()
        # A source-only or patch-only change IS a graft.
        self.write(**{**self.OLD, "graft_from_source_sha256": "1" * 64})
        self.create()
        self.write(**{**self.OLD, "graft_from_patch_bundle_sha256": "3" * 64})
        self.create()

    def test_validate_refuses_malformed_grafted_from_in_the_sidecar(self):
        self.write(**self.OLD)
        payload = self.create()
        sidecar = self.root / "g.lineage.json"

        def check(mutate, message):
            broken = json.loads(json.dumps(payload))
            mutate(broken)
            checkpoint_lineage.write_lineage(sidecar, broken, replace=True)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        message):
                checkpoint_lineage.validate_lineage(
                    self.checkpoint, sidecar, expected=self.expected())

        check(lambda b: b["ancestry"].__setitem__("grafted_from", "x"),
              "must be an object")
        check(lambda b: b["ancestry"]["grafted_from"].pop("source_sha256"),
              "exactly")
        check(lambda b: b["ancestry"]["grafted_from"].__setitem__("extra", "1" * 64),
              "exactly")
        check(lambda b: b["ancestry"]["grafted_from"].__setitem__(
            "compiled_module_sha256", "Z" * 64), "grafted_from.compiled_module")
        check(lambda b: b["ancestry"]["grafted_from"].__setitem__(
            "warm_lineage_sha256", "9" * 64), "differs from")
        check(lambda b: b["ancestry"]["grafted_from"].__setitem__("reason", ""),
              "grafted_from.reason")
        check(lambda b: b["ancestry"]["grafted_from"].__setitem__(
            "reason", "r" * 201), "grafted_from.reason")

    def test_validate_refuses_grafted_from_on_fresh_lineage(self):
        self.write(initialization="fresh", mode="native_fresh_v7_genesis",
                   warm_lineage_sha256="", pool_lineage_bundle_sha256="")
        payload = self.create()
        payload["ancestry"]["grafted_from"] = {
            "warm_lineage_sha256": "", "source_sha256": "a" * 64,
            "compiled_module_sha256": "b" * 64,
            "puffer_patch_bundle_sha256": "c" * 64, "reason": "D242"}
        sidecar = self.root / "g.lineage.json"
        checkpoint_lineage.write_lineage(sidecar, payload)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "grafted_from"):
            checkpoint_lineage.validate_lineage(
                self.checkpoint, sidecar, expected=self.expected())


class GraftBridgeTests(unittest.TestCase):
    """graft_bridge is the shared launcher/screen classification of a graft."""

    NEW = {"source_sha256": "1" * 64, "compiled_module_sha256": "2" * 64,
           "puffer_patch_bundle_sha256": "3" * 64}

    @staticmethod
    def payload(source, module, patch):
        return {"implementation": {
            "source_sha256": source, "compiled_module_sha256": module,
            "puffer_patch_bundle_sha256": patch}}

    def bridge(self, sidecars, old_source="a" * 64, old_patch="c" * 64):
        return checkpoint_lineage.graft_bridge(
            sidecars, current=self.NEW, old_source_sha256=old_source,
            old_patch_bundle_sha256=old_patch)

    def test_all_old_returns_the_shared_old_module(self):
        old = self.payload("a" * 64, "b" * 64, "c" * 64)
        self.assertEqual(self.bridge([("warm", old)] + [
            (f"bank{i}", old) for i in range(4)]), "b" * 64)

    def test_mixed_pool_after_a_graft_is_accepted(self):
        # Rung N+1: warm is new-build, one bank is the new-build rung-N
        # checkpoint, three banks are still old-build.
        new = self.payload("1" * 64, "2" * 64, "3" * 64)
        old = self.payload("a" * 64, "b" * 64, "c" * 64)
        self.assertEqual(self.bridge([("warm", new), ("bank0", old),
                                      ("bank1", old), ("bank2", old),
                                      ("bank3", new)]), "b" * 64)

    def test_a_bank_from_a_different_old_build_is_refused(self):
        old = self.payload("a" * 64, "b" * 64, "c" * 64)
        other = self.payload("d" * 64, "e" * 64, "f" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "bank2 binds neither"):
            self.bridge([("warm", old), ("bank0", old), ("bank1", old),
                         ("bank2", other), ("bank3", old)])

    def test_old_build_sidecars_must_share_one_module(self):
        old = self.payload("a" * 64, "b" * 64, "c" * 64)
        rehosted = self.payload("a" * 64, "9" * 64, "c" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "different compiled modules"):
            self.bridge([("warm", old), ("bank0", rehosted)])

    def test_same_source_and_patch_with_other_module_is_a_rehost_not_a_graft(self):
        drifted = self.payload("1" * 64, "9" * 64, "3" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "binds neither.*rehost"):
            self.bridge([("warm", drifted)])

    def test_nothing_old_is_a_refused_no_op(self):
        new = self.payload("1" * 64, "2" * 64, "3" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "no-op.*rehost"):
            self.bridge([("warm", new), ("bank0", new)])

    def test_declaring_this_build_as_the_old_build_is_refused(self):
        old = self.payload("a" * 64, "b" * 64, "c" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "nothing to graft.*rehost"):
            self.bridge([("warm", old)], old_source="1" * 64,
                        old_patch="3" * 64)

    def test_malformed_digests_are_refused(self):
        old = self.payload("a" * 64, "b" * 64, "c" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "old_source_sha256"):
            self.bridge([("warm", old)], old_source="A" * 64)


@unittest.skip("raw obs-v4/v5 bridge retired: obs-v7 has a different shape")
class BridgeLineageTests(unittest.TestCase):
    """A bridge warm-starts from an OUT-OF-LINEAGE raw blob with no sidecar.

    The run manifest declares initialization=bridge plus the four bridge_*
    keys (all or none), an EMPTY warm_lineage_sha256 (there is no warm
    sidecar) and a NON-empty pool bundle digest (the banks are ordinary
    eligible obs-v7 sidecars). The sidecar records ancestry.bridged_from and
    is itself eligible ancestry for later lineage-v7 rungs."""

    JULY_SHA = "4e97ba4ff72fcc71e154ca146caeab45eb7c5d9e584db42f17b07f77c72a7630"
    BRIDGE = {
        "bridge_warm_sha256": JULY_SHA,
        "bridge_warm_observation_version": "4",
        "bridge_provenance": (
            "runs/reward-transfer-20260713-v1/checkpoints/r0-s42-native.bin "
            "(ANALYSIS.json; docs/audit-2026-08-20.md F2)"),
        "bridge_reason": "audit-2026-08-20 F2",
    }
    GRAFT = {
        "graft_from_source_sha256": "a" * 64,
        "graft_from_module_sha256": "b" * 64,
        "graft_from_patch_bundle_sha256": "c" * 64,
        "graft_from_warm_lineage_sha256": "",
        "graft_reason": "D242",
    }

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.checkpoint = self.root / "policy.bin"
        self.checkpoint.write_bytes(
            b"bridge" + b"\0" * (
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES - len(b"bridge")))
        self.run_manifest = self.root / "RUN_MANIFEST.json"
        self.base = {
            "schema_version": 1,
            "mode": "native_static_pool_reward_ablation",
            "seed": "42",
            "observation_abi": "obs-v7",
            "observation_version": "7",
            "action_abi": "exact-joint-v1",
            "compiled_rollout_transition_contract": "terminal-aware-tbptt-v1",
            "initialization": "bridge",
            "qualification_only": "0",
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
            "pool_lineage_bundle_sha256": "6" * 64,
            **self.BRIDGE,
        }

    def tearDown(self):
        self.temp.cleanup()

    def write(self, drop=(), **over):
        manifest = {k: v for k, v in self.base.items() if k not in drop}
        manifest.update(over)
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    def create(self, **kw):
        kw.setdefault("allow_eligible_publication", True)
        return checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest, **kw)

    def expected(self):
        return {"source_sha256": "1" * 64, "compiled_module_sha256": "2" * 64,
                "puffer_patch_bundle_sha256": "3" * 64}

    def test_bridge_round_trips_and_records_the_raw_warm(self):
        self.write()
        payload = self.create()
        self.assertEqual(payload["ancestry"]["initialization"], "bridge")
        self.assertTrue(payload["ancestry"]["eligible"])
        self.assertFalse(payload["ancestry"]["qualification_only"])
        self.assertEqual(payload["ancestry"]["warm_lineage_sha256"], "")
        self.assertEqual(payload["ancestry"]["pool_lineage_bundle_sha256"],
                         "6" * 64)
        self.assertEqual(payload["ancestry"]["bridged_from"], {
            "warm_checkpoint_sha256": self.JULY_SHA,
            "warm_observation_version": 4,
            "provenance": self.BRIDGE["bridge_provenance"],
            "reason": "audit-2026-08-20 F2",
        })
        self.assertNotIn("grafted_from", payload["ancestry"])
        # Published on THIS build's digests and obs-v7, like any arm.
        self.assertEqual(payload["implementation"], self.expected())
        self.assertEqual(payload["compatibility"]["observation_version"], 7)
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=True)
        self.assertEqual(observed, payload)
        # obs-v5 is the other bridgeable revision; the stored version is an int.
        self.write(bridge_warm_observation_version="5")
        self.assertEqual(
            self.create()["ancestry"]["bridged_from"]["warm_observation_version"], 5)

    def test_bridge_is_eligible_only_through_accepted_publication(self):
        # Same gate as lineage-v7: a bridge output is eligible, so only the
        # screen's materialize_result may mint it.
        self.write()
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "accepted screen"):
            self.create(allow_eligible_publication=False)

    def test_each_missing_bridge_key_is_refused(self):
        for drop in self.BRIDGE:
            self.write(drop=(drop,))
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "all-or-none"):
                self.create()
        # None at all on a bridge initialization is refused too.
        self.write(drop=tuple(self.BRIDGE))
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "requires the bridge_\\* keys"):
            self.create()

    def test_malformed_bridge_fields_are_refused(self):
        for bad in ("", "A" * 64, "a" * 63, 7, None):
            self.write(bridge_warm_sha256=bad)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "bridge_warm_sha256"):
                self.create()
        # Only obs-v4 and obs-v5 are bridgeable: v3 cannot load, v6 is in
        # lineage and must come with a sidecar.
        for bad in ("3", "6", "04", "x", "", None, True, 4.0):
            self.write(bridge_warm_observation_version=bad)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "bridge_warm_observation_version"):
                self.create()
        for bad in ("", "   ", 7, None, "p" * 301):
            self.write(bridge_provenance=bad)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "bridge_provenance"):
                self.create()
        self.write(bridge_provenance="p" * 300)
        self.assertEqual(self.create()["ancestry"]["bridged_from"]["provenance"],
                         "p" * 300)
        for bad in ("", "   ", 7, None, "r" * 201):
            self.write(bridge_reason=bad)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "bridge_reason"):
                self.create()
        self.write(bridge_reason="r" * 200)
        self.assertEqual(self.create()["ancestry"]["bridged_from"]["reason"],
                         "r" * 200)

    def test_bridge_with_a_warm_lineage_digest_is_refused(self):
        # The whole point: the bridged warm HAS no sidecar. A digest here means
        # the manifest was assembled for lineage-v7 and mislabelled.
        self.write(warm_lineage_sha256="5" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "leave warm_lineage_sha256 empty"):
            self.create()

    def test_bridge_without_a_pool_bundle_is_refused(self):
        self.write(pool_lineage_bundle_sha256="")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "requires pool_lineage_bundle_sha256"):
            self.create()

    def test_bridge_keys_on_any_other_initialization_are_refused(self):
        self.write(initialization="lineage-v7", warm_lineage_sha256="5" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "only valid with bridge initialization"):
            self.create()
        self.write(initialization="fresh", mode="native_fresh_v7_genesis",
                   pool_lineage_bundle_sha256="")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "only valid with bridge initialization"):
            self.create()
        # And a bridge cannot be qualification-only or declared genesis.
        self.write(qualification_only="1", mode="native_fresh_v7_qualification")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "fresh initialization"):
            self.create()
        self.write(mode="native_fresh_v7_genesis")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "genesis output must use fresh"):
            self.create()

    def test_graft_and_bridge_together_are_refused(self):
        self.write(**self.GRAFT)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "mutually exclusive"):
            self.create()
        # Even a partial graft declaration alongside a bridge.
        self.write(graft_reason="D242")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "mutually exclusive"):
            self.create()

    def test_validate_accepts_a_bridge_sidecar_as_eligible_ancestry(self):
        self.write()
        payload = self.create()
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        # require_eligible=True is what every launcher asks for the warm and
        # every pool bank; graft_bridge and rehost go through the same call.
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=True)
        self.assertTrue(observed["ancestry"]["eligible"])
        # A rehost of a bridge output carries bridged_from along unchanged.
        module = self.root / "other.so"
        module.write_bytes(b"module")
        rehosted = checkpoint_lineage.rehost_lineage(
            self.checkpoint, sidecar=sidecar, target_module=module,
            target_source_sha256="1" * 64, target_patch_bundle_sha256="3" * 64)
        self.assertEqual(rehosted["ancestry"]["bridged_from"],
                         payload["ancestry"]["bridged_from"])
        self.assertEqual(rehosted["ancestry"]["initialization"], "bridge")

    def test_validate_rechecks_bridged_from_shape_and_consistency(self):
        self.write()
        payload = self.create()
        sidecar = self.root / "b.lineage.json"

        def check(mutate, message):
            broken = json.loads(json.dumps(payload))
            mutate(broken)
            checkpoint_lineage.write_lineage(sidecar, broken, replace=True)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        message):
                checkpoint_lineage.validate_lineage(
                    self.checkpoint, sidecar, expected=self.expected())

        check(lambda b: b["ancestry"].pop("bridged_from"),
              "must record ancestry.bridged_from")
        check(lambda b: b["ancestry"].__setitem__("bridged_from", "x"),
              "must be an object")
        check(lambda b: b["ancestry"]["bridged_from"].pop("provenance"),
              "exactly")
        check(lambda b: b["ancestry"]["bridged_from"].__setitem__("extra", 1),
              "exactly")
        check(lambda b: b["ancestry"]["bridged_from"].__setitem__(
            "warm_checkpoint_sha256", "Z" * 64), "bridged_from.warm_checkpoint")
        check(lambda b: b["ancestry"]["bridged_from"].__setitem__(
            "warm_observation_version", 6), "bridged_from.warm_observation")
        check(lambda b: b["ancestry"]["bridged_from"].__setitem__(
            "warm_observation_version", "4"), "bridged_from.warm_observation")
        check(lambda b: b["ancestry"]["bridged_from"].__setitem__(
            "provenance", ""), "bridged_from.provenance")
        check(lambda b: b["ancestry"]["bridged_from"].__setitem__(
            "reason", "r" * 201), "bridged_from.reason")
        # A bridge sidecar that grew a warm digest is contradicting itself.
        check(lambda b: b["ancestry"].__setitem__("warm_lineage_sha256", "5" * 64),
              "leave warm_lineage_sha256 empty")
        check(lambda b: b["ancestry"].__setitem__("pool_lineage_bundle_sha256", ""),
              "bind pool ancestry")
        # bridged_from on a lineage-v7 or genesis sidecar is refused outright.
        check(lambda b: b["ancestry"].update(
            initialization="lineage-v7", warm_lineage_sha256="5" * 64),
            "only bridge lineage may record bridged_from")
        check(lambda b: b["ancestry"].update(
            initialization="fresh", mode="native_fresh_v7_genesis",
            pool_lineage_bundle_sha256=""),
            "only bridge lineage may record bridged_from")
        # grafted_from never belongs on a bridge (well-formed, so the
        # initialization rule is what refuses it, not the digest shape).
        check(lambda b: b["ancestry"].__setitem__("grafted_from", {
            "warm_lineage_sha256": "5" * 64, "source_sha256": "a" * 64,
            "compiled_module_sha256": "b" * 64,
            "puffer_patch_bundle_sha256": "c" * 64, "reason": "D242"}),
            "only lineage-v7 lineage may be grafted")

    def test_a_later_lineage_v6_rung_can_warm_from_the_bridge_output(self):
        # The bridge output is ordinary eligible ancestry: the next rung names
        # its sidecar digest as warm_lineage_sha256 under lineage-v7, and the
        # bridged_from record stays one hop back rather than being copied.
        self.write()
        bridge_payload = self.create()
        bridge_sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(bridge_sidecar, bridge_payload)
        bridge_digest = checkpoint_lineage.lineage_digest(bridge_payload)
        checkpoint_lineage.validate_lineage(
            self.checkpoint, bridge_sidecar, expected=self.expected(),
            require_eligible=True)

        next_checkpoint = self.root / "rung1.bin"
        next_checkpoint.write_bytes(
            b"rung1" + b"\0" * (
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES - len(b"rung1")))
        next_manifest = self.root / "RUNG1_MANIFEST.json"
        manifest = {k: v for k, v in self.base.items() if k not in self.BRIDGE}
        manifest.update(initialization="lineage-v7",
                        warm_lineage_sha256=bridge_digest,
                        pool_lineage_bundle_sha256="7" * 64)
        next_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        next_payload = checkpoint_lineage.lineage_from_run_manifest(
            next_checkpoint, next_manifest, allow_eligible_publication=True)
        self.assertEqual(next_payload["ancestry"]["initialization"], "lineage-v7")
        self.assertEqual(next_payload["ancestry"]["warm_lineage_sha256"],
                         bridge_digest)
        self.assertNotIn("bridged_from", next_payload["ancestry"])
        next_sidecar = checkpoint_lineage.sidecar_path(next_checkpoint)
        checkpoint_lineage.write_lineage(next_sidecar, next_payload)
        observed = checkpoint_lineage.validate_lineage(
            next_checkpoint, next_sidecar, expected=self.expected(),
            require_eligible=True)
        self.assertTrue(observed["ancestry"]["eligible"])

    def test_bridge_cli_create_and_validate(self):
        self.write()
        out = self.root / "cli.lineage.json"
        # create refuses eligible publication from the CLI, like lineage-v7.
        with self.assertRaises(SystemExit) as caught:
            checkpoint_lineage.main([
                "create", "--checkpoint", str(self.checkpoint),
                "--run-manifest", str(self.run_manifest), "--out", str(out)])
        self.assertEqual(caught.exception.code, 1)
        payload = self.create()
        checkpoint_lineage.write_lineage(out, payload)
        self.assertEqual(checkpoint_lineage.main([
            "validate", "--checkpoint", str(self.checkpoint),
            "--lineage", str(out),
            "--expect", "source_sha256=" + "1" * 64,
            "--expect", "compiled_module_sha256=" + "2" * 64,
            "--expect", "puffer_patch_bundle_sha256=" + "3" * 64]), 0)


# Real rig digests (audit critic G2): migrated chain 9 was published on the
# migration build (source 6fbd67f7, patch 425c5d5b); the terminal-aware-v2
# runtime is source 6fbd67f7, patch 4b5bdc20, module 651ffc40. The migration
# module digest is whatever the temp module file hashes to.
MIGRATION_SOURCE = "6fbd67f7201ce9830b3f282f19d3a98768ea197b8f3e5b9357991460884526f1"
MIGRATION_PATCH = "425c5d5b117c3d21e944a2380d33ee6eaaec7e4274358c15a222b3f4116c46ec"
TERMINAL_AWARE_V2 = {
    "source_sha256": MIGRATION_SOURCE,
    "compiled_module_sha256":
        "651ffc40e43e669912803e2f5bb3d3e641c34c0d8b431ab0f38f8393bbc700a3",
    "puffer_patch_bundle_sha256":
        "4b5bdc20de6de488ab3f2ce055861b91ab2cfa16bbe869f01fe206193f11c803",
}
CONTROL_BANK_SOURCE = "9581e3c53ad487cd2d3e45fc653818c735ede9e8147e3e0f649e6391d0808fd6"


def mint_migrated(root, checkpoint, *, fill, source=MIGRATION_SOURCE,
                  patch=MIGRATION_PATCH, module=None, columns=None):
    """Publish a migrate-v6 sidecar through checkpoint_lineage.migration_lineage."""
    module = module or root / "migration_module.so"
    if not module.exists():
        module.write_bytes(b"migration-build module")
    checkpoint.write_bytes(fill + b"\0" * (
        checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES - len(fill)))
    v6_sha = digest(b"v6:" + fill)
    source_lineage = root / (checkpoint.name + ".v6.lineage.json")
    source_lineage.write_bytes(checkpoint_lineage.canonical_bytes({
        "checkpoint": {"bytes": 16_000_000, "sha256": v6_sha},
        "compatibility": {"observation_abi": "obs-v6",
                          "observation_version": 6,
                          "action_abi": "exact-joint-v1"}}))
    migration_manifest = root / (checkpoint.name + ".migration.json")
    migration_manifest.write_text(json.dumps({
        "schema": "bloodbowl-checkpoint-observation-migration-v1",
        "source": {"observation_abi": "obs-v6", "observation_version": 6,
                   "observation_size": 2782, "sha256": v6_sha,
                   "lineage_sha256": digest(source_lineage.read_bytes())},
        "destination": {"observation_abi": "obs-v7", "observation_version": 7,
                        "observation_size": 2851,
                        "sha256": digest(checkpoint.read_bytes())},
        "zero_effect_inputs": columns or {
            "repurposed_v6_zero_columns": [814, 815],
            "appended_columns": [2782, 2850]},
    }), encoding="utf-8")
    payload = checkpoint_lineage.migration_lineage(
        checkpoint, migration_manifest, source_lineage, target_module=module,
        target_source_sha256=source, target_patch_bundle_sha256=patch)
    sidecar = checkpoint_lineage.sidecar_path(checkpoint)
    checkpoint_lineage.write_lineage(sidecar, payload, replace=True)
    return payload, sidecar


class MigratedGraftTests(unittest.TestCase):
    """B1/G2: migrated chain 9 enters the obs-v7 lineage only through a declared
    graft, and becomes eligible ancestry only by training a rung."""

    REASON = "B1 warm-start migrated chain 9 on terminal-aware-v2"

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.warm = self.root / "chain9-v7.bin"
        self.warm_payload, self.warm_sidecar = mint_migrated(
            self.root, self.warm, fill=b"chain9")
        self.banks = []
        for index in range(4):
            bank = self.root / f"bank{index}.bin"
            payload, _ = mint_migrated(self.root, bank,
                                       fill=f"bank{index}".encode())
            self.banks.append((bank, payload))
        self.trained = self.root / "rung1.bin"
        self.trained.write_bytes(b"trained" + b"\0" * (
            checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES - len(b"trained")))
        self.run_manifest = self.root / "RUN_MANIFEST.json"

    def tearDown(self):
        self.temp.cleanup()

    def sidecars(self):
        return [("warm", self.warm_payload)] + [
            (f"pool bank {index}", payload)
            for index, (_, payload) in enumerate(self.banks)]

    def graft_module(self, accept_migrated=True):
        return checkpoint_lineage.graft_bridge(
            self.sidecars(), current=TERMINAL_AWARE_V2,
            old_source_sha256=MIGRATION_SOURCE,
            old_patch_bundle_sha256=MIGRATION_PATCH,
            accept_migrated=accept_migrated)

    def write_manifest(self, *, migrated=True, **over):
        warm_lineage = checkpoint_lineage.lineage_digest(self.warm_payload)
        manifest = {
            "schema_version": 1,
            "mode": "native_static_pool_reward_ablation",
            "seed": "42",
            "observation_abi": "obs-v7",
            "observation_version": "7",
            "action_abi": "exact-joint-v1",
            "compiled_rollout_transition_contract": "terminal-aware-tbptt-v1",
            "initialization": "lineage-v7",
            "qualification_only": "0",
            "policy_hidden_size": "512",
            "policy_num_layers": "3",
            "policy_expansion_factor": "1",
            "expected_checkpoint_bytes": str(
                checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES),
            **TERMINAL_AWARE_V2,
            "screen_manifest_sha256": "4" * 64,
            "warm_lineage_sha256": warm_lineage,
            "pool_lineage_bundle_sha256": "6" * 64,
            "graft_from_source_sha256": MIGRATION_SOURCE,
            "graft_from_module_sha256": self.graft_module(),
            "graft_from_patch_bundle_sha256": MIGRATION_PATCH,
            "graft_from_warm_lineage_sha256": warm_lineage,
            "graft_reason": "D370",
        }
        if migrated:
            manifest["graft_migrated_reason"] = self.REASON
            manifest["graft_migrated_from"] = json.dumps(
                checkpoint_lineage.migrated_graft_records(self.sidecars()),
                sort_keys=True, separators=(",", ":"))
        manifest.update(over)
        manifest = {k: v for k, v in manifest.items() if v is not None}
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")

    def publish(self, checkpoint=None):
        return checkpoint_lineage.lineage_from_run_manifest(
            checkpoint or self.trained, self.run_manifest,
            allow_eligible_publication=True)

    def test_undeclared_migrated_sidecar_is_still_not_eligible_ancestry(self):
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "only a graft declaring GRAFT_ACCEPT_MIGRATED"):
            checkpoint_lineage.validate_lineage(
                self.warm, self.warm_sidecar, require_eligible=True)
        # Readable for qualification exactly as before.
        observed = checkpoint_lineage.validate_lineage(
            self.warm, self.warm_sidecar, require_eligible=False)
        self.assertFalse(observed["ancestry"]["eligible"])
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "zero-extended migration; declare"):
            self.graft_module(accept_migrated=False)

    def test_declared_migrated_sidecar_with_a_correct_column_audit_is_accepted(self):
        observed = checkpoint_lineage.validate_lineage(
            self.warm, self.warm_sidecar, require_eligible=True,
            accept_migrated=True)
        self.assertEqual(observed, self.warm_payload)
        self.assertEqual(observed["ancestry"]["migrated_from"]["zeroed_columns"],
                         [814, 815])
        self.assertEqual(checkpoint_lineage.main([
            "validate", "--checkpoint", str(self.warm), "--accept-migrated"]), 0)
        with self.assertRaises(SystemExit) as caught:
            checkpoint_lineage.main(["validate", "--checkpoint", str(self.warm)])
        self.assertEqual(caught.exception.code, 1)

    def test_migration_build_bridges_to_the_terminal_aware_runtime(self):
        # lineage-v7 on the target runtime refuses the migration build...
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "lineage mismatch"):
            checkpoint_lineage.validate_lineage(
                self.warm, self.warm_sidecar, expected=TERMINAL_AWARE_V2,
                require_eligible=True, accept_migrated=True)
        # ...and the declared graft bridges it, returning the migration module.
        self.assertEqual(self.graft_module(),
                         self.warm_payload["implementation"]["compiled_module_sha256"])
        # A bank migrated on another source is not the declared old build.
        other = self.root / "control.bin"
        other_payload, _ = mint_migrated(
            self.root, other, fill=b"control", source=CONTROL_BANK_SOURCE)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "pool bank 3 binds neither"):
            checkpoint_lineage.graft_bridge(
                self.sidecars()[:4] + [("pool bank 3", other_payload)],
                current=TERMINAL_AWARE_V2, old_source_sha256=MIGRATION_SOURCE,
                old_patch_bundle_sha256=MIGRATION_PATCH, accept_migrated=True)

    def test_declaration_without_a_migrated_sidecar_is_refused(self):
        eligible_old = {"implementation": {
            "source_sha256": MIGRATION_SOURCE, "compiled_module_sha256": "b" * 64,
            "puffer_patch_bundle_sha256": MIGRATION_PATCH},
            "ancestry": {"initialization": "lineage-v7"}}
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "no warm/pool sidecar is a zero-extended"):
            checkpoint_lineage.graft_bridge(
                [("warm", eligible_old)], current=TERMINAL_AWARE_V2,
                old_source_sha256=MIGRATION_SOURCE,
                old_patch_bundle_sha256=MIGRATION_PATCH, accept_migrated=True)

    def test_wrong_column_audit_is_rejected_even_when_declared(self):
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "column audit mismatch"):
            mint_migrated(self.root, self.root / "bad.bin", fill=b"bad",
                          columns={"repurposed_v6_zero_columns": [814],
                                   "appended_columns": [2782, 2850]})
        for key, bad in (("zeroed_columns", [814]),
                         ("appended_columns", [2782, 2849])):
            broken = json.loads(json.dumps(self.warm_payload))
            broken["ancestry"]["migrated_from"][key] = bad
            checkpoint_lineage.write_lineage(self.warm_sidecar, broken,
                                             replace=True)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "migration lineage column audit mismatch"):
                checkpoint_lineage.validate_lineage(
                    self.warm, self.warm_sidecar, require_eligible=True,
                    accept_migrated=True)

    def test_blob_hash_mismatch_is_rejected_even_when_declared(self):
        original = self.warm.read_bytes()
        self.warm.write_bytes(b"tampered" + original[len(b"tampered"):])
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "SHA-256 differs from lineage"):
            checkpoint_lineage.validate_lineage(
                self.warm, self.warm_sidecar, require_eligible=True,
                accept_migrated=True)

    def test_declaration_cannot_relabel_a_migration_as_eligible(self):
        broken = json.loads(json.dumps(self.warm_payload))
        broken["ancestry"].update({"eligible": True, "qualification_only": False})
        checkpoint_lineage.write_lineage(self.warm_sidecar, broken, replace=True)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "qualification-only, and ineligible"):
            checkpoint_lineage.validate_lineage(
                self.warm, self.warm_sidecar, require_eligible=True,
                accept_migrated=True)

    def test_first_trained_rung_publishes_eligible_lineage_recording_migrated_from(self):
        self.write_manifest()
        payload = self.publish()
        ancestry = payload["ancestry"]
        self.assertTrue(ancestry["eligible"])
        self.assertEqual(ancestry["initialization"], "lineage-v7")
        self.assertEqual(payload["implementation"], TERMINAL_AWARE_V2)
        self.assertEqual(ancestry["grafted_from"]["puffer_patch_bundle_sha256"],
                         MIGRATION_PATCH)
        records = ancestry["migrated_from"]["sidecars"]
        self.assertEqual(ancestry["migrated_from"]["reason"], self.REASON)
        self.assertEqual([r["label"] for r in records],
                         ["warm"] + [f"pool bank {i}" for i in range(4)])
        self.assertEqual(records[0]["checkpoint_sha256"],
                         self.warm_payload["checkpoint"]["sha256"])
        self.assertEqual(records[0]["source_checkpoint_sha256"],
                         self.warm_payload["ancestry"]["migrated_from"][
                             "source_checkpoint_sha256"])
        sidecar = checkpoint_lineage.sidecar_path(self.trained)
        checkpoint_lineage.write_lineage(sidecar, payload)
        # Materialization validates on the target build with no declaration.
        observed = checkpoint_lineage.validate_lineage(
            self.trained, sidecar, expected=TERMINAL_AWARE_V2,
            require_eligible=True)
        self.assertEqual(observed, payload)
        # The declared reason is hashed into the sidecar.
        self.write_manifest(graft_migrated_reason="a different review")
        self.assertNotEqual(checkpoint_lineage.lineage_digest(self.publish()),
                            checkpoint_lineage.lineage_digest(payload))

    def test_untrained_migrated_blob_cannot_be_published_or_promoted(self):
        self.write_manifest()
        for blob, label in ((self.warm, "warm"), (self.banks[2][0], "pool bank 2")):
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        f"migrated {label} blob itself"):
                self.publish(blob)
        # A forged sidecar that points trained ancestry at the migrated bytes.
        payload = self.publish()
        forged = json.loads(json.dumps(payload))
        forged["checkpoint"]["sha256"] = self.warm_payload["checkpoint"]["sha256"]
        forged_sidecar = self.root / "forged.lineage.json"
        checkpoint_lineage.write_lineage(forged_sidecar, forged)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "migrated warm blob itself"):
            checkpoint_lineage.validate_lineage(
                self.warm, forged_sidecar, expected=TERMINAL_AWARE_V2,
                require_eligible=True)
        # rehost is not a path around training.
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "not eligible ancestry"):
            checkpoint_lineage.rehost_lineage(
                self.warm, target_module=self.root / "migration_module.so",
                target_source_sha256=TERMINAL_AWARE_V2["source_sha256"],
                target_patch_bundle_sha256=TERMINAL_AWARE_V2[
                    "puffer_patch_bundle_sha256"])

    def test_migrated_manifest_keys_are_all_or_none_and_need_a_graft(self):
        self.write_manifest(graft_migrated_reason=None)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError, "all-or-none"):
            self.publish()
        self.write_manifest(**{key: None for key in (
            "graft_from_source_sha256", "graft_from_module_sha256",
            "graft_from_patch_bundle_sha256", "graft_from_warm_lineage_sha256",
            "graft_reason")})
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "require the graft_from_"):
            self.publish()
        for bad in ("", "{}", "[]", "not json", json.dumps([{"label": "warm"}])):
            self.write_manifest(graft_migrated_from=bad)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "graft_migrated_from"):
                self.publish()
        for bad in ("", " ", "r" * 201):
            self.write_manifest(graft_migrated_reason=bad)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "graft_migrated_reason"):
                self.publish()
        records = checkpoint_lineage.migrated_graft_records(self.sidecars())
        records[0]["lineage_sha256"] = "7" * 64
        self.write_manifest(graft_migrated_from=json.dumps(records))
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "migrated warm record differs"):
            self.publish()
        records = checkpoint_lineage.migrated_graft_records(self.sidecars())
        records[1]["label"] = "warm"
        self.write_manifest(graft_migrated_from=json.dumps(records))
        with self.assertRaisesRegex(checkpoint_lineage.LineageError, "duplicates"):
            self.publish()

    def test_validate_refuses_malformed_or_ungrafted_migrated_from(self):
        self.write_manifest()
        payload = self.publish()
        sidecar = self.root / "m.lineage.json"

        def check(mutate, message):
            broken = json.loads(json.dumps(payload))
            mutate(broken)
            checkpoint_lineage.write_lineage(sidecar, broken, replace=True)
            with self.assertRaisesRegex(checkpoint_lineage.LineageError, message):
                checkpoint_lineage.validate_lineage(
                    self.trained, sidecar, expected=TERMINAL_AWARE_V2)

        check(lambda b: b["ancestry"].pop("grafted_from"),
              "only grafted lineage-v7")
        check(lambda b: b["ancestry"]["migrated_from"].pop("reason"), "exactly")
        check(lambda b: b["ancestry"]["migrated_from"].__setitem__("sidecars", []),
              "non-empty list")
        check(lambda b: b["ancestry"]["migrated_from"]["sidecars"][0].__setitem__(
            "checkpoint_sha256", "Z" * 64), "checkpoint_sha256")
        check(lambda b: b["ancestry"]["migrated_from"].__setitem__("reason", ""),
              "migrated_from.reason")


if __name__ == "__main__":
    unittest.main()
