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
            "mode": "native_fresh_v6_qualification",
            "seed": "42",
            "observation_abi": "obs-v6",
            "observation_version": "6",
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
        manifest["initialization"] = "lineage-v6"
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
        # screen. Nothing could mint the first eligible checkpoint, so obs-v6
        # could never train -- measured on the training host as zero
        # .lineage.json files in existence.
        def manifest_with(**over):
            m = json.loads(self.run_manifest.read_text(encoding="utf-8"))
            m.update(over)
            self.run_manifest.write_text(
                json.dumps(m, sort_keys=True) + "\n", encoding="utf-8")

        # Declared genesis: fresh AND eligible, published by the screen.
        manifest_with(qualification_only="0", initialization="fresh",
                      mode="native_fresh_v6_genesis")
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
                      mode="native_fresh_v6_qualification")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "declared genesis"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest,
                allow_eligible_publication=True)

        # Genesis is ancestry by definition, so it may not claim to be
        # qualification-only at the same time.
        manifest_with(qualification_only="1", initialization="fresh",
                      mode="native_fresh_v6_genesis")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "not qualification-only"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest,
                allow_eligible_publication=True)

        # Genesis must actually be fresh; it cannot relabel a warm-started run.
        manifest_with(qualification_only="0", initialization="lineage-v6",
                      mode="native_fresh_v6_genesis")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "must use fresh"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest,
                allow_eligible_publication=True)

        # And genesis still cannot self-publish: only accepted screen result
        # materialization may mint eligible lineage.
        manifest_with(qualification_only="0", initialization="fresh",
                      mode="native_fresh_v6_genesis")
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
            "initialization": "lineage-v6",
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
        16,066,560-byte checkpoint, different semantics. This is the exact
        shape that cost a 12B-step run across v4/v5, and blob size cannot see
        it, so the declared observation version must be checked explicitly."""
        payload, sidecar = self.create()
        # Precondition: the blob is EXACTLY the size the current ABI demands,
        # so any refusal below cannot have come from the size check.
        self.assertEqual(self.checkpoint.stat().st_size,
                         checkpoint_lineage.EXPECTED_CHECKPOINT_BYTES)
        self.assertEqual(payload["compatibility"]["observation_abi"], "obs-v6")
        self.assertEqual(payload["compatibility"]["observation_version"], 6)

        for abi, version in (("obs-v5", 5), ("obs-v5", 6), ("obs-v6", 5)):
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
                                    "observation_abi must be obs-v6"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, stale_manifest)

        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["observation_version"] = "5"
        stale_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "observation_version must be 6"):
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
        manifest["initialization"] = "lineage-v6"
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
            "mode": "native_fresh_v6_qualification",
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
    of an otherwise ordinary lineage-v6 payload published on the NEW build."""

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
            "observation_abi": "obs-v6",
            "observation_version": "6",
            "action_abi": "exact-joint-v1",
            "initialization": "lineage-v6",
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
        # Published on the NEW build's digests, ordinary lineage-v6 otherwise.
        self.assertEqual(payload["implementation"], self.expected())
        self.assertEqual(payload["ancestry"]["initialization"], "lineage-v6")
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
                   initialization="fresh", mode="native_fresh_v6_genesis",
                   warm_lineage_sha256="", pool_lineage_bundle_sha256="")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "lineage-v6"):
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

    # --- more than one declared old build -----------------------------------
    TWO = {
        "graft_from_source_sha256": "a" * 64 + "," + "d" * 64,
        "graft_from_module_sha256": "b" * 64 + "," + "e" * 64,
        "graft_from_patch_bundle_sha256": "c" * 64 + "," + "f" * 64,
        "graft_from_warm_lineage_sha256": "5" * 64,
        "graft_reason": "D242",
    }

    def test_one_declared_build_publishes_the_sidecar_it_always_did(self):
        # The single-pair sidecar is pinned whole: same keys, same values, no
        # list key, so its canonical bytes cannot move.
        self.write(**self.OLD)
        payload = self.create()
        self.assertEqual(payload["ancestry"], {
            "initialization": "lineage-v6",
            "mode": "native_static_pool_reward_ablation",
            "qualification_only": False,
            "eligible": True,
            "warm_lineage_sha256": "5" * 64,
            "pool_lineage_bundle_sha256": "6" * 64,
            "grafted_from": {
                "warm_lineage_sha256": "5" * 64,
                "source_sha256": "a" * 64,
                "compiled_module_sha256": "b" * 64,
                "puffer_patch_bundle_sha256": "c" * 64,
                "reason": "D242",
            },
        })
        self.assertEqual(
            checkpoint_lineage.canonical_bytes(payload["ancestry"]),
            b'{"eligible":true,"grafted_from":{"compiled_module_sha256":"'
            + b"b" * 64 + b'","puffer_patch_bundle_sha256":"' + b"c" * 64
            + b'","reason":"D242","source_sha256":"' + b"a" * 64
            + b'","warm_lineage_sha256":"' + b"5" * 64
            + b'"},"initialization":"lineage-v6","mode":'
            b'"native_static_pool_reward_ablation",'
            b'"pool_lineage_bundle_sha256":"' + b"6" * 64
            + b'","qualification_only":false,"warm_lineage_sha256":"'
            + b"5" * 64 + b'"}\n')

    def test_two_declared_builds_are_both_recorded_in_declared_order(self):
        self.write(**self.TWO)
        payload = self.create()
        # The first pair keeps the existing field and shape ...
        self.assertEqual(payload["ancestry"]["grafted_from"], {
            "warm_lineage_sha256": "5" * 64,
            "source_sha256": "a" * 64,
            "compiled_module_sha256": "b" * 64,
            "puffer_patch_bundle_sha256": "c" * 64,
            "reason": "D242",
        })
        # ... and every further pair is listed beside it.
        self.assertEqual(payload["ancestry"]["grafted_from_also"], [{
            "source_sha256": "d" * 64,
            "compiled_module_sha256": "e" * 64,
            "puffer_patch_bundle_sha256": "f" * 64,
        }])
        sidecar = checkpoint_lineage.sidecar_path(self.checkpoint)
        checkpoint_lineage.write_lineage(sidecar, payload)
        observed = checkpoint_lineage.validate_lineage(
            self.checkpoint, sidecar, expected=self.expected(),
            require_eligible=True)
        self.assertEqual(observed, payload)

        three = {**self.TWO,
                 "graft_from_source_sha256": ",".join(("d" * 64, "a" * 64, "7" * 64)),
                 "graft_from_module_sha256": ",".join(("e" * 64, "b" * 64, "8" * 64)),
                 "graft_from_patch_bundle_sha256": ",".join(("f" * 64, "c" * 64, "9" * 64))}
        self.write(**three)
        payload = self.create()
        self.assertEqual(payload["ancestry"]["grafted_from"]["source_sha256"],
                         "d" * 64)
        self.assertEqual(
            [entry["source_sha256"]
             for entry in payload["ancestry"]["grafted_from_also"]],
            ["a" * 64, "7" * 64])
        self.assertEqual(
            [entry["compiled_module_sha256"]
             for entry in payload["ancestry"]["grafted_from_also"]],
            ["b" * 64, "8" * 64])

    def test_declared_lists_of_different_lengths_are_refused(self):
        for key, short, message in (
            ("graft_from_source_sha256", "a" * 64, "read pairwise"),
            ("graft_from_patch_bundle_sha256", "c" * 64, "read pairwise"),
            ("graft_from_module_sha256", "b" * 64, "one module per"),
        ):
            self.write(**{**self.TWO, key: short})
            with self.assertRaisesRegex(checkpoint_lineage.LineageError, message):
                self.create()

    def test_malformed_declared_lists_are_refused(self):
        for key in ("graft_from_source_sha256", "graft_from_module_sha256",
                    "graft_from_patch_bundle_sha256"):
            good = self.TWO[key]
            for bad in (good + ",", "," + good, good.replace(",", ", "),
                        good.replace(",", ";"), good.replace(",", ",,"),
                        good[:64] + "," + "Z" * 64):
                self.write(**{**self.TWO, key: bad})
                with self.assertRaisesRegex(checkpoint_lineage.LineageError, key):
                    self.create()

    def test_a_build_declared_twice_is_refused(self):
        self.write(**{**self.TWO,
                      "graft_from_source_sha256": "a" * 64 + "," + "a" * 64,
                      "graft_from_patch_bundle_sha256": "c" * 64 + "," + "c" * 64})
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "same old build twice"):
            self.create()
        # Same source under two patch bundles is two builds.
        self.write(**{**self.TWO,
                      "graft_from_source_sha256": "a" * 64 + "," + "a" * 64})
        self.create()

    def test_any_declared_build_equal_to_the_new_build_is_a_refused_no_op(self):
        for position in (0, 1):
            sources = ["a" * 64, "d" * 64]
            patches = ["c" * 64, "f" * 64]
            sources[position], patches[position] = "1" * 64, "3" * 64
            self.write(**{**self.TWO,
                          "graft_from_source_sha256": ",".join(sources),
                          "graft_from_patch_bundle_sha256": ",".join(patches)})
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "no-op.*rehost"):
                self.create()

    def test_validate_refuses_malformed_grafted_from_also_in_the_sidecar(self):
        self.write(**self.TWO)
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

        check(lambda b: b["ancestry"].__setitem__("grafted_from_also", {}),
              "non-empty list")
        check(lambda b: b["ancestry"].__setitem__("grafted_from_also", []),
              "non-empty list")
        check(lambda b: b["ancestry"].__setitem__("grafted_from_also", ["x"]),
              r"grafted_from_also\[0\] must be an object")
        check(lambda b: b["ancestry"]["grafted_from_also"][0].pop("source_sha256"),
              "exactly")
        check(lambda b: b["ancestry"]["grafted_from_also"][0].__setitem__(
            "reason", "D242"), "exactly")
        check(lambda b: b["ancestry"]["grafted_from_also"][0].__setitem__(
            "compiled_module_sha256", "Z" * 64),
            r"grafted_from_also\[0\].compiled_module_sha256")
        # The first build again, or one listed twice.
        check(lambda b: b["ancestry"]["grafted_from_also"][0].update(
            source_sha256="a" * 64, puffer_patch_bundle_sha256="c" * 64),
            "repeats an old build")
        check(lambda b: b["ancestry"]["grafted_from_also"].append(
            dict(b["ancestry"]["grafted_from_also"][0])), "repeats an old build")
        check(lambda b: b["ancestry"].pop("grafted_from"),
              "grafted_from_also requires ancestry.grafted_from")

    def test_validate_refuses_grafted_from_on_fresh_lineage(self):
        self.write(initialization="fresh", mode="native_fresh_v6_genesis",
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

    # --- more than one declared old build -----------------------------------
    # Builds as (source, module, patch): FIRST = (a, b, c), SECOND = (d, e, f),
    # this build = (1, 2, 3).
    FIRST = ("a" * 64, "b" * 64, "c" * 64)
    SECOND = ("d" * 64, "e" * 64, "f" * 64)

    def two(self, sidecars, builds=None):
        builds = builds or (self.FIRST, self.SECOND)
        return self.bridge(
            sidecars, old_source=",".join(build[0] for build in builds),
            old_patch=",".join(build[2] for build in builds))

    def test_one_pair_still_returns_one_bare_module(self):
        old = self.payload(*self.FIRST)
        result = self.bridge([("warm", old), ("bank0", old)])
        self.assertEqual(result, "b" * 64)
        self.assertNotIn(",", result)

    def test_two_declared_builds_both_present_return_both_modules_in_order(self):
        first, second = self.payload(*self.FIRST), self.payload(*self.SECOND)
        new = self.payload(*(self.NEW[key] for key in (
            "source_sha256", "compiled_module_sha256",
            "puffer_patch_bundle_sha256")))
        # The paired rung's shape: warm from the second old build, a pool
        # holding the first old build's anchor and the second's rungs.
        sidecars = [("warm", second), ("bank0", first), ("bank1", first),
                    ("bank2", second), ("bank3", second)]
        self.assertEqual(self.two(sidecars), "b" * 64 + "," + "e" * 64)
        # Declared the other way round, the modules follow the declaration.
        self.assertEqual(self.two(sidecars, (self.SECOND, self.FIRST)),
                         "e" * 64 + "," + "b" * 64)
        # A later rung on the third build: its own checkpoints join the two.
        self.assertEqual(self.two([("warm", new), ("bank0", first),
                                   ("bank1", second), ("bank2", second),
                                   ("bank3", new)]),
                         "b" * 64 + "," + "e" * 64)

    def test_two_declared_one_absent_is_refused(self):
        first = self.payload(*self.FIRST)
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "no sidecar binds declared old build source dddddddddddd"):
            self.two([("warm", first)] + [(f"bank{i}", first) for i in range(4)])
        second = self.payload(*self.SECOND)
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "no sidecar binds declared old build source aaaaaaaaaaaa"):
            self.two([("warm", second), ("bank0", second)])

    def test_an_undeclared_third_build_is_refused(self):
        first, second = self.payload(*self.FIRST), self.payload(*self.SECOND)
        third = self.payload("7" * 64, "8" * 64, "9" * 64)
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "bank2 binds neither this build nor any of the 2 declared old builds"):
            self.two([("warm", second), ("bank0", first), ("bank1", second),
                      ("bank2", third), ("bank3", second)])
        # A declared source under an undeclared patch bundle is undeclared too.
        crossed = self.payload(self.FIRST[0], "8" * 64, self.SECOND[2])
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "bank0 binds neither"):
            self.two([("warm", second), ("bank0", crossed), ("bank1", first)])

    def test_mismatched_list_lengths_are_refused(self):
        first, second = self.payload(*self.FIRST), self.payload(*self.SECOND)
        sidecars = [("warm", second), ("bank0", first)]
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "lists 2 old build.*lists 1.*pairwise"):
            self.bridge(sidecars, old_source="a" * 64 + "," + "d" * 64,
                        old_patch="c" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "lists 1 old build.*lists 2.*pairwise"):
            self.bridge(sidecars, old_source="a" * 64,
                        old_patch="c" * 64 + "," + "f" * 64)
        for bad in ("a" * 64 + ",", "a" * 64 + ", " + "d" * 64):
            with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                        "old_source_sha256"):
                self.bridge(sidecars, old_source=bad,
                            old_patch="c" * 64 + "," + "f" * 64)

    def test_each_declared_build_must_share_one_module(self):
        first, second = self.payload(*self.FIRST), self.payload(*self.SECOND)
        second_rehosted = self.payload(self.SECOND[0], "9" * 64, self.SECOND[2])
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError,
                "declared old build source dddddddddddd.*different compiled modules"):
            self.two([("warm", second), ("bank0", first),
                      ("bank1", second_rehosted)])
        # Two builds with two different modules is the whole point, not a clash.
        self.assertEqual(self.two([("warm", second), ("bank0", first)]),
                         "b" * 64 + "," + "e" * 64)

    def test_declaring_this_build_among_several_is_refused(self):
        first = self.payload(*self.FIRST)
        this = (self.NEW["source_sha256"], self.NEW["compiled_module_sha256"],
                self.NEW["puffer_patch_bundle_sha256"])
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "nothing to graft.*rehost"):
            self.two([("warm", first)], (self.FIRST, this))

    def test_a_build_declared_twice_is_refused(self):
        first = self.payload(*self.FIRST)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "same old build twice"):
            self.two([("warm", first)], (self.FIRST, self.FIRST))

    def test_several_declared_and_nothing_old_is_the_same_no_op(self):
        new = self.payload("1" * 64, "2" * 64, "3" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "no-op.*rehost"):
            self.two([("warm", new), ("bank0", new)])


class BridgeLineageTests(unittest.TestCase):
    """A bridge warm-starts from an OUT-OF-LINEAGE raw blob with no sidecar.

    The run manifest declares initialization=bridge plus the four bridge_*
    keys (all or none), an EMPTY warm_lineage_sha256 (there is no warm
    sidecar) and a NON-empty pool bundle digest (the banks are ordinary
    eligible obs-v6 sidecars). The sidecar records ancestry.bridged_from and
    is itself eligible ancestry for later lineage-v6 rungs."""

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
            "observation_abi": "obs-v6",
            "observation_version": "6",
            "action_abi": "exact-joint-v1",
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
        # Published on THIS build's digests and obs-v6, like any arm.
        self.assertEqual(payload["implementation"], self.expected())
        self.assertEqual(payload["compatibility"]["observation_version"], 6)
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
        # Same gate as lineage-v6: a bridge output is eligible, so only the
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
        # the manifest was assembled for lineage-v6 and mislabelled.
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
        self.write(initialization="lineage-v6", warm_lineage_sha256="5" * 64)
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "only valid with bridge initialization"):
            self.create()
        self.write(initialization="fresh", mode="native_fresh_v6_genesis",
                   pool_lineage_bundle_sha256="")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "only valid with bridge initialization"):
            self.create()
        # And a bridge cannot be qualification-only or declared genesis.
        self.write(qualification_only="1", mode="native_fresh_v6_qualification")
        with self.assertRaisesRegex(checkpoint_lineage.LineageError,
                                    "fresh initialization"):
            self.create()
        self.write(mode="native_fresh_v6_genesis")
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
        # bridged_from on a lineage-v6 or genesis sidecar is refused outright.
        check(lambda b: b["ancestry"].update(
            initialization="lineage-v6", warm_lineage_sha256="5" * 64),
            "only bridge lineage may record bridged_from")
        check(lambda b: b["ancestry"].update(
            initialization="fresh", mode="native_fresh_v6_genesis",
            pool_lineage_bundle_sha256=""),
            "only bridge lineage may record bridged_from")
        # grafted_from never belongs on a bridge (well-formed, so the
        # initialization rule is what refuses it, not the digest shape).
        check(lambda b: b["ancestry"].__setitem__("grafted_from", {
            "warm_lineage_sha256": "5" * 64, "source_sha256": "a" * 64,
            "compiled_module_sha256": "b" * 64,
            "puffer_patch_bundle_sha256": "c" * 64, "reason": "D242"}),
            "only lineage-v6 lineage may be grafted")

    def test_a_later_lineage_v6_rung_can_warm_from_the_bridge_output(self):
        # The bridge output is ordinary eligible ancestry: the next rung names
        # its sidecar digest as warm_lineage_sha256 under lineage-v6, and the
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
        manifest.update(initialization="lineage-v6",
                        warm_lineage_sha256=bridge_digest,
                        pool_lineage_bundle_sha256="7" * 64)
        next_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        next_payload = checkpoint_lineage.lineage_from_run_manifest(
            next_checkpoint, next_manifest, allow_eligible_publication=True)
        self.assertEqual(next_payload["ancestry"]["initialization"], "lineage-v6")
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
        # create refuses eligible publication from the CLI, like lineage-v6.
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


if __name__ == "__main__":
    unittest.main()
