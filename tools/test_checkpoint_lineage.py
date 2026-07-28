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
            "compiled_environment_config_schema":
                checkpoint_lineage.ENVIRONMENT_CONFIG_SCHEMA,
            "compiled_strict_env_config_testing": False,
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
            "ladder_reset_pct": "0",
            "ladder_endzone_maxdist": "0",
            "ladder_pickup_maxdist": "0",
            "ladder_postkick_maxturn": "0",
            "ladder_pass_maxrange": "0",
            **checkpoint_lineage.STATE_BANK_INACTIVE,
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

    def test_current_run_requires_production_strict_config_identity(self):
        base = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        cases = (
            ("compiled_environment_config_schema", None),
            ("compiled_environment_config_schema", "other-schema"),
            ("compiled_strict_env_config_testing", None),
            ("compiled_strict_env_config_testing", True),
            ("compiled_strict_env_config_testing", 0),
            ("compiled_strict_env_config_testing", "false"),
        )
        for key, value in cases:
            with self.subTest(key=key, value=value):
                changed = dict(base)
                if value is None:
                    del changed[key]
                else:
                    changed[key] = value
                self.run_manifest.write_text(
                    json.dumps(changed, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    checkpoint_lineage.LineageError, key
                ):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest
                    )

    def test_state_bank_inactive_form_is_complete_and_exactly_typed(self):
        base = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        for key in checkpoint_lineage.STATE_BANK_INACTIVE:
            with self.subTest(missing=key):
                changed = dict(base)
                del changed[key]
                self.run_manifest.write_text(
                    json.dumps(changed, sort_keys=True) + "\n",
                    encoding="utf-8")
                with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError, key):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest)
        for key, expected in checkpoint_lineage.STATE_BANK_INACTIVE.items():
            with self.subTest(noncanonical=key):
                changed = dict(base)
                changed[key] = (
                    False if isinstance(expected, int) else expected.upper())
                self.run_manifest.write_text(
                    json.dumps(changed, sort_keys=True) + "\n",
                    encoding="utf-8")
                with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError, key):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest)

    def test_state_bank_active_form_requires_every_identity(self):
        active = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        active.update({
            "ladder_reset_pct": "0.5",
            "ladder_state_bank_contract_schema":
                checkpoint_lineage.STATE_BANK_CONTRACT_SCHEMA,
            "ladder_state_bank_producer_schema":
                checkpoint_lineage.STATE_BANK_PRODUCER_SCHEMA,
            "ladder_state_bank_kind": checkpoint_lineage.STATE_BANK_KIND,
            "ladder_state_bank_ruleset": checkpoint_lineage.STATE_BANK_RULESET,
            "ladder_state_bank_sha256": "5" * 64,
            "ladder_state_bank_producer_manifest_sha256": "6" * 64,
            "ladder_state_bank_contract_sha256": "7" * 64,
            "ladder_state_bank_producer_engine_source_sha256": "8" * 64,
            "ladder_state_bank_loader_engine_source_sha256": "9" * 64,
            "ladder_state_bank_records": 3,
            "ladder_state_bank_bytes": 16 + 3 * (12 + 2240),
            "ladder_state_bank_strata_schema":
                checkpoint_lineage.STATE_BANK_STRATA_SCHEMA,
            "ladder_state_bank_strata_family": "uniform",
            "ladder_state_bank_strata_threshold": 0,
            "ladder_state_bank_strata_eligible_records": 3,
            "ladder_state_bank_strata_sha256": "a" * 64,
        })
        self.run_manifest.write_text(
            json.dumps(active, sort_keys=True) + "\n", encoding="utf-8")
        checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest)

        active_keys = (
            "ladder_state_bank_contract_schema",
            "ladder_state_bank_producer_schema",
            "ladder_state_bank_kind",
            "ladder_state_bank_ruleset",
            "ladder_state_bank_sha256",
            "ladder_state_bank_producer_manifest_sha256",
            "ladder_state_bank_contract_sha256",
            "ladder_state_bank_producer_engine_source_sha256",
            "ladder_state_bank_loader_engine_source_sha256",
            "ladder_state_bank_records",
            "ladder_state_bank_bytes",
            "ladder_state_bank_strata_schema",
            "ladder_state_bank_strata_family",
            "ladder_state_bank_strata_threshold",
            "ladder_state_bank_strata_eligible_records",
            "ladder_state_bank_strata_sha256",
        )
        for key in active_keys:
            with self.subTest(missing=key):
                changed = dict(active)
                del changed[key]
                self.run_manifest.write_text(
                    json.dumps(changed, sort_keys=True) + "\n",
                    encoding="utf-8")
                with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError, key):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest)

        wrong_types = {
            key: False for key in active_keys
        }
        wrong_types["ladder_state_bank_records"] = "3"
        wrong_types["ladder_state_bank_bytes"] = "6772"
        wrong_types["ladder_state_bank_strata_threshold"] = "0"
        wrong_types["ladder_state_bank_strata_eligible_records"] = "3"
        for key, wrong in wrong_types.items():
            with self.subTest(wrong_type=key):
                changed = dict(active)
                changed[key] = wrong
                self.run_manifest.write_text(
                    json.dumps(changed, sort_keys=True) + "\n",
                    encoding="utf-8")
                with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError, key):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest)

        changed = dict(active)
        changed["ladder_state_bank_bytes"] += 1
        self.run_manifest.write_text(
            json.dumps(changed, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "bytes.*records|reconcile"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest)

    def active_selector_manifest(
        self,
        selector_key="ladder_endzone_maxdist",
        threshold=6,
        family="endzone-maxdist",
    ):
        manifest = json.loads(self.run_manifest.read_text(encoding="utf-8"))
        manifest["ladder_reset_pct"] = "0.5"
        for key in checkpoint_lineage.STATE_BANK_SELECTOR_KEYS:
            manifest[key] = "0"
        manifest.update({
            "ladder_state_bank_contract_schema":
                checkpoint_lineage.STATE_BANK_CONTRACT_SCHEMA,
            "ladder_state_bank_producer_schema":
                checkpoint_lineage.STATE_BANK_PRODUCER_SCHEMA,
            "ladder_state_bank_kind": checkpoint_lineage.STATE_BANK_KIND,
            "ladder_state_bank_ruleset": checkpoint_lineage.STATE_BANK_RULESET,
            "ladder_state_bank_sha256": "5" * 64,
            "ladder_state_bank_producer_manifest_sha256": "6" * 64,
            "ladder_state_bank_contract_sha256": "7" * 64,
            "ladder_state_bank_producer_engine_source_sha256": "8" * 64,
            "ladder_state_bank_loader_engine_source_sha256": "9" * 64,
            "ladder_state_bank_records": 3,
            "ladder_state_bank_bytes": 16 + 3 * (12 + 2240),
            selector_key: str(threshold),
            "ladder_state_bank_strata_schema":
                "bloodbowl-legacy-state-bank-strata-v1",
            "ladder_state_bank_strata_family": family,
            "ladder_state_bank_strata_threshold": threshold,
            "ladder_state_bank_strata_eligible_records": 2,
            "ladder_state_bank_strata_sha256": "a" * 64,
        })
        return manifest

    def test_state_bank_active_selector_with_exact_descriptor_is_accepted(self):
        manifest = self.active_selector_manifest()
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        payload = checkpoint_lineage.lineage_from_run_manifest(
            self.checkpoint, self.run_manifest)
        self.assertEqual(
            payload["producer"]["run_manifest_sha256"],
            digest(self.run_manifest.read_bytes()),
        )

    def test_state_bank_selector_bounds_are_family_specific(self):
        cases = (
            ("ladder_endzone_maxdist", 26, "endzone-maxdist", 25),
            ("ladder_pickup_maxdist", 26, "pickup-maxdist", 25),
            ("ladder_postkick_maxturn", 9, "postkick-maxturn", 8),
            ("ladder_pass_maxrange", 26, "pass-maxrange", 25),
        )
        for key, threshold, family, maximum in cases:
            with self.subTest(key=key):
                manifest = self.active_selector_manifest(
                    selector_key=key,
                    threshold=threshold,
                    family=family,
                )
                self.run_manifest.write_text(
                    json.dumps(manifest, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    checkpoint_lineage.LineageError,
                    rf"{key}.*{maximum}",
                ):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest)

    def test_state_bank_each_family_accepts_its_closed_upper_bound(self):
        cases = (
            ("ladder_endzone_maxdist", 25, "endzone-maxdist"),
            ("ladder_pickup_maxdist", 25, "pickup-maxdist"),
            ("ladder_postkick_maxturn", 8, "postkick-maxturn"),
            ("ladder_pass_maxrange", 25, "pass-maxrange"),
        )
        for key, threshold, family in cases:
            with self.subTest(key=key):
                manifest = self.active_selector_manifest(
                    selector_key=key,
                    threshold=threshold,
                    family=family,
                )
                self.run_manifest.write_text(
                    json.dumps(manifest, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                checkpoint_lineage.lineage_from_run_manifest(
                    self.checkpoint, self.run_manifest)

    def test_state_bank_descriptor_reconciles_with_selector_and_population(self):
        mutations = (
            ("ladder_state_bank_strata_schema", "unknown", "strata_schema"),
            ("ladder_state_bank_strata_family", "pickup-maxdist", "family"),
            ("ladder_state_bank_strata_threshold", 5, "threshold"),
            ("ladder_state_bank_strata_eligible_records", 4, "eligible"),
            ("ladder_state_bank_strata_sha256", "A" * 64, "SHA-256"),
        )
        for key, wrong, message in mutations:
            with self.subTest(key=key):
                manifest = self.active_selector_manifest()
                manifest[key] = wrong
                self.run_manifest.write_text(
                    json.dumps(manifest, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.assertRaisesRegex(
                    checkpoint_lineage.LineageError, message
                ):
                    checkpoint_lineage.lineage_from_run_manifest(
                        self.checkpoint, self.run_manifest)

        manifest = self.active_selector_manifest()
        manifest["ladder_pickup_maxdist"] = "3"
        self.run_manifest.write_text(
            json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
        with self.assertRaisesRegex(
                checkpoint_lineage.LineageError, "only one"):
            checkpoint_lineage.lineage_from_run_manifest(
                self.checkpoint, self.run_manifest)

    def test_state_bank_descriptor_counts_are_exact_json_integers(self):
        for key in (
            "ladder_state_bank_strata_threshold",
            "ladder_state_bank_strata_eligible_records",
        ):
            for wrong in ("6", False):
                with self.subTest(key=key, wrong=wrong):
                    manifest = self.active_selector_manifest()
                    manifest[key] = wrong
                    self.run_manifest.write_text(
                        json.dumps(manifest, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with self.assertRaisesRegex(
                        checkpoint_lineage.LineageError,
                        rf"{key}.*JSON integer",
                    ):
                        checkpoint_lineage.lineage_from_run_manifest(
                            self.checkpoint, self.run_manifest)

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


if __name__ == "__main__":
    unittest.main()
