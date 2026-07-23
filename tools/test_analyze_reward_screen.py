#!/usr/bin/env python3

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import analyze_reward_screen
from live_integrity_guard import HARD_INTEGRITY_KEYS


def write_json(path, value):
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class RewardScreenAnalysisTests(unittest.TestCase):
    def build_profile_screen(
        self,
        root,
        *,
        prefix,
        schedule_pairs,
        eval_metrics,
        profile=None,
        candidate_arm=None,
        rewards=None,
        requested_steps=500_000_000,
        completion=False,
    ):
        """Write a plan plus one accepted result per scheduled (arm, seed) cell.

        ``eval_metrics`` is called with ``(index, arm, seed)`` and returns the
        cell's eval panel, so a caller only has to supply what its assertions
        actually read.
        """
        root = Path(root)
        reward_sha = rewards or {
            arm: analyze_reward_screen.POSSESSION_GAIN_REWARD_SHA256[arm]
            for arm, _ in schedule_pairs
        }
        contract = {
            "prefix": prefix,
            "requested_steps": requested_steps,
            "schedule": [
                {"index": index, "arm": arm, "seed": seed}
                for index, (arm, seed) in enumerate(schedule_pairs, 1)
            ],
            "settings": {"expected_checkpoint_bytes": "16"},
            "rewards": {
                arm: {"reward_sha256": reward}
                for arm, reward in reward_sha.items()
            },
        }
        if profile is not None:
            contract["screen_profile"] = profile
        if candidate_arm is not None:
            contract["candidate_arm"] = candidate_arm
        manifest_path = root / "SCREEN_MANIFEST.json"
        write_json(manifest_path, {"schema_version": 1, "contract": contract})
        manifest_sha = sha256(manifest_path)

        complete_results = []
        for index, (arm, seed) in enumerate(schedule_pairs, 1):
            name = f"{prefix}-{arm}-s{seed}.result.json"
            path = root / name
            result = {
                "schema_version": 2,
                "trainer_complete": True,
                "acceptance_pass": True,
                "acceptance_failures": [],
                "arm": arm,
                "seed": seed,
                "tag": f"{prefix}-{arm}-s{seed}",
                "screen_manifest_sha256": manifest_sha,
                "reward_sha256": reward_sha[arm],
                "checkpoint_bytes": 16,
                "checkpoint_sha256": digest(f"checkpoint-{arm}-{seed}"),
                "run_manifest_sha256": digest(f"manifest-{arm}-{seed}"),
                "eval_metrics": eval_metrics(index, arm, seed),
            }
            write_json(path, result)
            complete_results.append({
                "index": index,
                "arm": arm,
                "seed": seed,
                "path": f"/remote/screen/{name}",
                "sha256": sha256(path),
            })

        if completion:
            write_json(root / "SCREEN_COMPLETE.json", {
                "schema_version": 1,
                "completed_utc": "2026-07-10T01:00:00+00:00",
                "screen_manifest_sha256": manifest_sha,
                "results": complete_results,
            })
        return manifest_sha

    def build_screen(self, root, *, completion=True):
        """The 2x2 distance/possession screen used by the Job A tests."""
        values = {
            ("r0", 42): 18.0,
            ("r1", 42): 12.0,
            ("r2", 42): 13.0,
            ("r3", 42): 10.0,
            ("r0", 43): 35.0,
            ("r1", 43): 24.0,
            ("r2", 43): 26.0,
            ("r3", 43): 20.0,
        }
        return self.build_profile_screen(
            root,
            prefix="screen-test",
            schedule_pairs=analyze_reward_screen.EXPECTED_SCHEDULE,
            rewards=analyze_reward_screen.CANONICAL_REWARD_SHA256,
            requested_steps=250_000_000,
            eval_metrics=lambda index, arm, seed: {
                "n": 10_000 + index,
                "tds": values[(arm, seed)],
                "perf": values[(arm, seed)] / 100.0,
            },
            completion=completion,
        )

    def build_exact_action_canary(self, root):
        root = Path(root)
        prefix = "exact-action-canary-test"
        source_sha = digest("installed-source")
        manifest = {
            "schema_version": 1,
            "contract": {
                "prefix": prefix,
                "screen_profile": "exact-action-canary",
                "qualification_only": True,
                "bootstrap": {
                    "observation_abi": "obs-v5",
                    "observation_version": 5,
                    "action_abi": "exact-joint-v1",
                    "initialization": "fresh",
                    "warm_lineage_sha256": "",
                    "pool_lineage_bundle_sha256": "",
                },
                "requested_steps": 50_000_000,
                "final_steps": 49_938_432,
                "schedule": [{"index": 1, "arm": "both", "seed": 42}],
                "settings": {
                    "expected_checkpoint_bytes": "16066560",
                    "native_precision_bytes": "4",
                    "min_train_games": "1",
                    "min_eval_games": "10000",
                },
                "warm": None,
                "pool": None,
                "rewards": {
                    "both": {
                        "reward_sha256": analyze_reward_screen
                        .POSSESSION_GAIN_REWARD_SHA256["both"]
                    }
                },
                "implementation": {
                    "source_sha256": source_sha,
                    "compiled_module_sha256": digest("compiled-module"),
                    "compiled_semantic_contract": {
                        "env_name": "bloodbowl",
                        "precision_bytes": 4,
                        "observation_abi": "obs-v5",
                        "observation_version": 5,
                        "action_abi": "exact-joint-v1",
                        "environment_source_sha256": source_sha,
                    },
                },
            },
        }
        manifest_path = root / "SCREEN_MANIFEST.json"
        write_json(manifest_path, manifest)
        manifest_sha = sha256(manifest_path)
        checkpoint_lineage_sha = digest("checkpoint-lineage")
        zero_metrics = {key: 0.0 for key in HARD_INTEGRITY_KEYS}
        result_path = root / f"{prefix}-both-s42.result.json"
        result = {
            "schema_version": 2,
            "trainer_complete": True,
            "acceptance_pass": True,
            "acceptance_failures": [],
            "qualification_only": True,
            "arm": "both",
            "seed": 42,
            "tag": f"{prefix}-both-s42",
            "screen_manifest_sha256": manifest_sha,
            "reward_sha256": analyze_reward_screen
            .POSSESSION_GAIN_REWARD_SHA256["both"],
            "checkpoint_bytes": 16_066_560,
            "checkpoint_sha256": digest("checkpoint-both-42"),
            "checkpoint_lineage": "/remote/run/0000000049938432.bin.lineage.json",
            "checkpoint_lineage_sha256": checkpoint_lineage_sha,
            "run_manifest_sha256": digest("manifest-both-42"),
            "train_metrics": {"n": 20_000, **zero_metrics},
            "eval_metrics": {"n": 10_000, "tds": 1.0, **zero_metrics},
        }
        write_json(result_path, result)
        write_json(root / "SCREEN_COMPLETE.json", {
            "schema_version": 1,
            "screen_manifest_sha256": manifest_sha,
            "completed_utc": "2026-07-21T00:00:00+00:00",
            "results": [{
                "index": 1,
                "arm": "both",
                "seed": 42,
                "path": f"/remote/screen/{result_path.name}",
                "sha256": sha256(result_path),
            }],
        })
        return manifest_sha

    def rebind_exact_action_canary(self, root):
        """Re-bind a mutated canary plan so only the mutation can be rejected."""
        root = Path(root)
        manifest_sha = sha256(root / "SCREEN_MANIFEST.json")
        result_path = root / "exact-action-canary-test-both-s42.result.json"
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["screen_manifest_sha256"] = manifest_sha
        write_json(result_path, result)
        completion_path = root / "SCREEN_COMPLETE.json"
        completion = json.loads(completion_path.read_text(encoding="utf-8"))
        completion["screen_manifest_sha256"] = manifest_sha
        completion["results"][0]["sha256"] = sha256(result_path)
        write_json(completion_path, completion)

    def test_default_metrics_surface_draw_rate(self):
        self.assertIn("draw_rate", analyze_reward_screen.DEFAULT_METRICS)
        self.assertLess(
            analyze_reward_screen.DEFAULT_METRICS.index("perf"),
            analyze_reward_screen.DEFAULT_METRICS.index("draw_rate"),
        )

    def test_exactly_one_hard_integrity_registry_is_used(self):
        """One registry, imported from the guard that enforces it live.

        This module used to also carry a hand-copied 11-key subset and require
        screen manifests to declare exactly that list, while checking all 16
        keys on the results.  Any second copy can only drift.
        """
        registries = sorted(
            name for name in vars(analyze_reward_screen)
            if "HARD_INTEGRITY" in name
        )
        self.assertEqual(registries, ["HARD_INTEGRITY_KEYS"])
        self.assertIs(
            analyze_reward_screen.HARD_INTEGRITY_KEYS, HARD_INTEGRITY_KEYS)
        self.assertEqual(len(HARD_INTEGRITY_KEYS), 16)

    def test_valid_completed_screen_computes_factorial_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp)
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))

        self.assertTrue(report["screen"]["completion"]["present"])
        self.assertEqual(len(report["runs"]), 8)
        self.assertNotIn("checkpoint_lineage_sha256", report["runs"][0])
        self.assertEqual(report["per_seed"]["42"]["effects"]["tds"], {
            "possession_main": 3.5,
            "distance_main": 4.5,
            "interaction": 3.0,
        })
        self.assertEqual(report["per_seed"]["43"]["effects"]["tds"], {
            "possession_main": 6.5,
            "distance_main": 8.5,
            "interaction": 5.0,
        })
        across = report["across_seeds"]["effects"]["tds"]
        self.assertEqual(across["possession_main"]["mean"], 5.0)
        self.assertEqual(across["distance_main"]["mean"], 6.5)
        self.assertEqual(across["interaction"]["mean"], 4.0)
        self.assertIn("n=2", " ".join(report["warnings"]))

    def test_exact_action_canary_reports_qualification_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_exact_action_canary(tmp)
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))

        self.assertEqual(report["analysis"], "exact_action_canary_qualification")
        self.assertEqual(report["screen"]["profile"], "exact-action-canary")
        self.assertEqual(list(report["per_seed"]), ["42"])
        self.assertEqual(report["per_seed"]["42"]["effects"]["tds"], {})
        self.assertIn("qualification-only", " ".join(report["warnings"]))
        self.assertEqual(
            report["runs"][0]["checkpoint_lineage_sha256"],
            digest("checkpoint-lineage"),
        )
        rendered = analyze_reward_screen.render_text(report)
        self.assertIn("Qualification verdict", rendered)
        self.assertNotIn("2x2 effects", rendered)
        self.assertNotIn("Across 1 seeds", rendered)

    def test_exact_action_canary_rejects_contaminated_or_wrong_build(self):
        """The canary's real preconditions: fresh, obs-v5/exact-joint, fp32,
        and compiled from the installed source."""
        mutations = (
            (
                "warm_start",
                lambda contract: contract.__setitem__(
                    "warm", {"path": "/remote/forbidden.bin"}),
                "null warm/pool",
            ),
            (
                "opponent_pool",
                lambda contract: contract.__setitem__(
                    "pool", {"path": "/remote/league9"}),
                "null warm/pool",
            ),
            (
                "warm_lineage_smuggled_in",
                lambda contract: contract["bootstrap"].__setitem__(
                    "warm_lineage_sha256", digest("obs-v4-ancestor")),
                "bootstrap warm_lineage_sha256 mismatch",
            ),
            (
                "action_abi",
                lambda contract: contract["bootstrap"].__setitem__(
                    "action_abi", "marginal-heads"),
                "bootstrap action_abi mismatch",
            ),
            (
                "observation_version",
                lambda contract: contract["bootstrap"].__setitem__(
                    "observation_version", 4),
                "bootstrap observation_version mismatch",
            ),
            (
                "observation_abi",
                lambda contract: contract["bootstrap"].__setitem__(
                    "observation_abi", "obs-v4"),
                "bootstrap observation_abi mismatch",
            ),
            (
                "compiled_observation_abi",
                lambda contract: contract["implementation"][
                    "compiled_semantic_contract"].__setitem__(
                        "observation_abi", "obs-v4"),
                "compiled observation_abi mismatch",
            ),
            (
                "compiled_action_abi",
                lambda contract: contract["implementation"][
                    "compiled_semantic_contract"].__setitem__(
                        "action_abi", "marginal-heads"),
                "compiled action_abi mismatch",
            ),
            (
                "bf16_build",
                lambda contract: contract["settings"].__setitem__(
                    "native_precision_bytes", "2"),
                "must be an fp32 build",
            ),
            (
                "bf16_compiled_module",
                lambda contract: contract["implementation"][
                    "compiled_semantic_contract"].__setitem__(
                        "precision_bytes", 2),
                "compiled precision_bytes mismatch",
            ),
            (
                "stale_installed_snapshot",
                lambda contract: contract["implementation"][
                    "compiled_semantic_contract"].__setitem__(
                        "environment_source_sha256", digest("stale-snapshot")),
                "does not match the installed source identity",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                self.build_exact_action_canary(tmp)
                manifest_path = Path(tmp) / "SCREEN_MANIFEST.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest["contract"])
                write_json(manifest_path, manifest)
                self.rebind_exact_action_canary(tmp)
                with self.assertRaisesRegex(
                        analyze_reward_screen.AnalysisError, message):
                    analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_checkpoint_size_must_match_the_plan(self):
        """A checkpoint of unplanned size is a different policy shape."""
        with tempfile.TemporaryDirectory() as tmp:
            self.build_exact_action_canary(tmp)
            result_path = (
                Path(tmp) / "exact-action-canary-test-both-s42.result.json")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["checkpoint_bytes"] = 8
            write_json(result_path, result)
            self.rebind_exact_action_canary(tmp)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "checkpoint size does not match the screen plan"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_exact_action_canary_rejects_nonzero_or_missing_hard_metrics(self):
        mutations = (
            (
                "nonzero",
                lambda result: result["train_metrics"].__setitem__(
                    "illegal_frac", 1.0),
                "train_metrics.illegal_frac must be exactly zero",
            ),
            (
                "missing",
                lambda result: result["eval_metrics"].pop(
                    "reward_nonfinite_episodes"),
                "eval_metrics.reward_nonfinite_episodes must be numeric",
            ),
            (
                "non_numeric",
                lambda result: result["eval_metrics"].__setitem__(
                    "error_episodes", "0"),
                "eval_metrics.error_episodes must be numeric",
            ),
            (
                "redundant_nonzero",
                lambda result: result["train_metrics"].__setitem__(
                    "reward_clip_signed_delta", 1e-12),
                "train_metrics.reward_clip_signed_delta must be exactly zero",
            ),
            (
                "redundant_missing",
                lambda result: result["eval_metrics"].pop(
                    "reward_nonfinite_samples_per_episode"),
                "eval_metrics.reward_nonfinite_samples_per_episode must be numeric",
            ),
            (
                "short_eval",
                lambda result: result["eval_metrics"].__setitem__("n", 9_999),
                "eval_metrics.n is below the frozen minimum",
            ),
            (
                "no_train_games",
                lambda result: result["train_metrics"].__setitem__("n", 0),
                "train_metrics.n is below the frozen minimum",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                self.build_exact_action_canary(tmp)
                result_path = (
                    Path(tmp) / "exact-action-canary-test-both-s42.result.json")
                result = json.loads(result_path.read_text(encoding="utf-8"))
                mutate(result)
                write_json(result_path, result)
                self.rebind_exact_action_canary(tmp)
                with self.assertRaisesRegex(
                        analyze_reward_screen.AnalysisError, message):
                    analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_exact_action_canary_requires_failures_lineage_and_completion(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_exact_action_canary(tmp)
            result_path = (
                Path(tmp) / "exact-action-canary-test-both-s42.result.json")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["acceptance_failures"] = None
            write_json(result_path, result)
            self.rebind_exact_action_canary(tmp)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "exactly empty acceptance_failures"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

        with tempfile.TemporaryDirectory() as tmp:
            self.build_exact_action_canary(tmp)
            (Path(tmp) / "SCREEN_COMPLETE.json").unlink()
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "requires the atomic SCREEN_COMPLETE"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

        for field in ("checkpoint_lineage", "checkpoint_lineage_sha256"):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as tmp:
                self.build_exact_action_canary(tmp)
                result_path = (
                    Path(tmp) / "exact-action-canary-test-both-s42.result.json")
                result = json.loads(result_path.read_text(encoding="utf-8"))
                result.pop(field)
                write_json(result_path, result)
                self.rebind_exact_action_canary(tmp)
                with self.assertRaisesRegex(
                        analyze_reward_screen.AnalysisError,
                        "checkpoint_lineage"):
                    analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_possession_gain_profile_computes_separate_main_effects(self):
        values = {
            "both": 18.0,
            "possession_only": 12.0,
            "gain_only": 13.0,
            "neither": 10.0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.build_profile_screen(
                tmp,
                prefix="possession-gain-test",
                profile="possession-gain",
                schedule_pairs=analyze_reward_screen.POSSESSION_GAIN_SCHEDULE,
                eval_metrics=lambda index, arm, seed: {
                    "n": 10_001, "tds": values[arm]},
            )
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))

        self.assertEqual(report["screen"]["profile"], "possession-gain")
        self.assertEqual(report["per_seed"]["42"]["effects"]["tds"], {
            "possession_main": 3.5,
            "gain_main": 4.5,
            "interaction": 3.0,
        })

    def test_paired_confirmation_profile_computes_candidate_contrast(self):
        candidate = "gain_only"
        values = {
            ("both", 42): 18.0, (candidate, 42): 17.0,
            ("both", 43): 20.0, (candidate, 43): 21.0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.build_profile_screen(
                tmp,
                prefix="paired-confirmation-test",
                profile="paired-confirmation",
                candidate_arm=candidate,
                schedule_pairs=(
                    ("both", 42), (candidate, 42),
                    (candidate, 43), ("both", 43),
                ),
                eval_metrics=lambda index, arm, seed: {
                    "n": 10_001, "tds": values[(arm, seed)]},
            )
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))

        self.assertEqual(report["screen"]["profile"], "paired-confirmation")
        self.assertEqual(report["screen"]["candidate_arm"], candidate)
        self.assertEqual(report["per_seed"]["42"]["effects"]["tds"], {
            "candidate_minus_both": -1.0,
        })
        self.assertEqual(
            report["across_seeds"]["effects"]["tds"]
            ["candidate_minus_both"]["mean"],
            0.0,
        )

    def test_paired_final_profile_adds_a_balanced_third_seed(self):
        candidate = "gain_only"
        values = {
            ("both", 42): 18.0, (candidate, 42): 17.0,
            ("both", 43): 20.0, (candidate, 43): 21.0,
            ("both", 44): 22.0, (candidate, 44): 25.0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            self.build_profile_screen(
                tmp,
                prefix="paired-final-test",
                profile="paired-final",
                candidate_arm=candidate,
                schedule_pairs=(
                    ("both", 42), (candidate, 42),
                    (candidate, 43), ("both", 43),
                    ("both", 44), (candidate, 44),
                ),
                eval_metrics=lambda index, arm, seed: {
                    "n": 10_001, "tds": values[(arm, seed)]},
            )
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))

        self.assertEqual(report["screen"]["profile"], "paired-final")
        self.assertEqual(list(report["per_seed"]), ["42", "43", "44"])
        across = report["across_seeds"]["effects"]["tds"][
            "candidate_minus_both"
        ]
        self.assertEqual(across["seed_count"], 3)
        self.assertEqual(across["mean"], 1.0)
        self.assertIn("n=3", " ".join(report["warnings"]))

    def test_paired_profiles_reject_an_unpaired_seed_schedule(self):
        """Causal claims come from paired seeds; an unpaired plan is not one."""
        candidate = "gain_only"
        with tempfile.TemporaryDirectory() as tmp:
            self.build_profile_screen(
                tmp,
                prefix="paired-final-test",
                profile="paired-final",
                candidate_arm=candidate,
                schedule_pairs=(
                    ("both", 42), (candidate, 42),
                    (candidate, 43), ("both", 43),
                    ("both", 44), (candidate, 45),
                ),
                eval_metrics=lambda index, arm, seed: {
                    "n": 10_001, "tds": 1.0},
            )
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "screen schedule does not match the frozen paired contract"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_control_final_profile_replicates_r0_across_three_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_profile_screen(
                tmp,
                prefix="control-final-test",
                profile="control-final",
                schedule_pairs=(("both", 42), ("both", 43), ("both", 44)),
                requested_steps=12_000_000_000,
                eval_metrics=lambda index, arm, seed: {
                    "n": 10_001, "tds": seed / 10.0},
            )
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))

        self.assertEqual(report["analysis"], "control_reward_replication")
        self.assertEqual(report["screen"]["profile"], "control-final")
        self.assertEqual(list(report["per_seed"]), ["42", "43", "44"])
        self.assertEqual(report["per_seed"]["42"]["effects"]["tds"], {})
        self.assertEqual(report["across_seeds"]["effects"]["tds"], {})

    def test_tampered_result_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp)
            path = Path(tmp) / "screen-test-r0-s42.result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["eval_metrics"]["tds"] = 999.0
            write_json(path, result)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "result hash mismatch"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_plan_and_acceptance_mismatches_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            path = Path(tmp) / "screen-test-r3-s42.result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["acceptance_pass"] = False
            result["acceptance_failures"] = [{"kind": "clip"}]
            write_json(path, result)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "is not accepted"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            path = Path(tmp) / "screen-test-r0-s42.result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["trainer_complete"] = False
            write_json(path, result)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "trainer is not complete"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            path = Path(tmp) / "SCREEN_MANIFEST.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["contract"]["schedule"][0]["arm"] = "r1"
            write_json(path, manifest)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "screen schedule"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            path = Path(tmp) / "SCREEN_MANIFEST.json"
            manifest = json.loads(path.read_text(encoding="utf-8"))
            manifest["contract"]["requested_steps"] += 1
            write_json(path, manifest)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "screen_manifest_sha256 mismatch"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "does not match --expected-screen-sha"):
                analyze_reward_screen.analyze_screen(
                    tmp, ("tds",), expected_screen_sha="0" * 64
                )

    def test_missing_completion_is_allowed_but_warned(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))
        self.assertFalse(report["screen"]["completion"]["present"])
        self.assertIn("completion proof", " ".join(report["warnings"]))

    def test_sample_count_cannot_be_selected_as_a_factorial_metric(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "always reported as the sample count"):
                analyze_reward_screen.analyze_screen(tmp, ("n",))

    def test_missing_or_nonfinite_eval_metric_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "is missing selected eval metric 'possession_rate'"):
                analyze_reward_screen.analyze_screen(tmp, ("possession_rate",))

        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            path = Path(tmp) / "screen-test-r2-s43.result.json"
            # json.loads maps 1e999 to inf, which no mean or contrast survives.
            path.write_text(
                path.read_text(encoding="utf-8").replace(
                    '"tds": 26.0', '"tds": 1e999'),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "eval_metrics.tds must be finite"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_zero_completed_eval_games_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            path = Path(tmp) / "screen-test-r1-s42.result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["eval_metrics"]["n"] = 0
            write_json(path, result)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "eval_metrics.n must be positive"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_malformed_result_hash_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            path = Path(tmp) / "screen-test-r1-s43.result.json"
            result = json.loads(path.read_text(encoding="utf-8"))
            result["checkpoint_sha256"] = "not-a-sha256"
            write_json(path, result)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "checkpoint_sha256 must be a lowercase SHA-256"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_altered_but_internally_consistent_reward_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_screen(tmp, completion=False)
            root = Path(tmp)
            manifest_path = root / "SCREEN_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            altered_reward_sha = digest("altered-r0")
            manifest["contract"]["rewards"]["r0"][
                "reward_sha256"] = altered_reward_sha
            write_json(manifest_path, manifest)
            altered_manifest_sha = sha256(manifest_path)

            for path in root.glob("*.result.json"):
                result = json.loads(path.read_text(encoding="utf-8"))
                result["screen_manifest_sha256"] = altered_manifest_sha
                if result["arm"] == "r0":
                    result["reward_sha256"] = altered_reward_sha
                write_json(path, result)

            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "canonical factorial reward hash mismatch"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_json_cli_is_machine_readable(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_sha = self.build_screen(tmp)
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name(
                    "analyze_reward_screen.py")), tmp, "--json",
                 "--metrics", "tds", "--expected-screen-sha", manifest_sha],
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["metrics"], ["tds"])
        self.assertEqual(payload["across_seeds"]["effects"]["tds"]
                         ["interaction"]["mean"], 4.0)

    def test_module_supports_repository_package_import(self):
        result = subprocess.run(
            [sys.executable, "-c", "import tools.analyze_reward_screen"],
            cwd=Path(__file__).resolve().parent.parent,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={key: value for key, value in os.environ.items()
                 if key != "PYTHONPATH"},
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
