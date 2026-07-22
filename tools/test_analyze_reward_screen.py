#!/usr/bin/env python3

import hashlib
import json
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
    def build_exact_action_canary(self, root):
        root = Path(root)
        prefix = "exact-action-canary-test"
        manifest = {
            "schema_version": 1,
            "contract": {
                "prefix": prefix,
                "screen_profile": "exact-action-canary",
                "qualification_only": True,
                "bootstrap": {
                    "mode": "fresh-v5-qualification",
                    "observation_abi": "obs-v5",
                    "observation_version": 5,
                    "action_abi": "exact-joint-v1",
                    "initialization": "fresh",
                    "warm_lineage_sha256": "",
                    "pool_lineage_bundle_sha256": "",
                },
                "requested_steps": 50_000_000,
                "final_steps": 49_938_432,
                "rollout_quantum": 131_072,
                "schedule": [{"index": 1, "arm": "both", "seed": 42}],
                "settings": {
                    "expected_checkpoint_bytes": "16",
                    "frozen_bank_pct": "0",
                    "num_frozen_banks": "0",
                    "native_precision_bytes": "4",
                    "min_train_games": "1",
                    "min_eval_games": "10000",
                    "eval_episodes": "10000",
                },
                "warm": None,
                "pool": None,
                "rewards": {
                    "both": {
                        "reward_sha256": analyze_reward_screen
                        .POSSESSION_GAIN_REWARD_SHA256["both"]
                    }
                },
                "error_budget": {
                    "contamination_budget": 0,
                    "detection_poll_seconds": 30,
                    "max_panel_silence_seconds": 180,
                    "hard_integrity_keys": list(
                        HARD_INTEGRITY_KEYS
                    ),
                },
                "implementation": {
                    **{
                        field: digest(field)
                        for field in (
                            "screen_script_sha256",
                            "game_stats_sha256",
                            "live_integrity_guard_sha256",
                            "checkpoint_lineage_sha256",
                            "status_wrapper_sha256",
                            "launcher_sha256",
                            "source_sha256",
                            "compiled_module_sha256",
                            "puffer_patch_bundle_sha256",
                            "vendor_source_sha256",
                        )
                    },
                    "compiled_semantic_contract": {
                        "env_name": "bloodbowl",
                        "gpu": 1,
                        "precision_bytes": 4,
                        "observation_abi": "obs-v5",
                        "observation_version": 5,
                        "action_abi": "exact-joint-v1",
                        "exact_action_source_sha256": digest(
                            "exact-action-source"),
                        "environment_source_sha256": digest("source_sha256"),
                    }
                },
            },
        }
        manifest_path = root / "SCREEN_MANIFEST.json"
        write_json(manifest_path, manifest)
        manifest_sha = sha256(manifest_path)
        checkpoint_lineage_sha = digest("checkpoint-lineage")
        zero_metrics = {
            key: 0.0 for key in HARD_INTEGRITY_KEYS
        }
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
            "checkpoint_bytes": 16,
            "checkpoint_sha256": digest("checkpoint-both-42"),
            "checkpoint_lineage": "/remote/run/0000000049938432.bin.lineage.json",
            "checkpoint_lineage_sha256": checkpoint_lineage_sha,
            "log_sha256": digest("log-both-42"),
            "status_sha256": digest("status-both-42"),
            "process_sha256": digest("process-both-42"),
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
                "checkpoint_sha256": result["checkpoint_sha256"],
                "checkpoint_lineage_sha256": checkpoint_lineage_sha,
            }],
        })
        return manifest_sha

    def build_screen(self, root, *, completion=True):
        root = Path(root)
        prefix = "screen-test"
        schedule = [
            {"index": index, "arm": arm, "seed": seed}
            for index, (arm, seed) in enumerate(
                analyze_reward_screen.EXPECTED_SCHEDULE, 1
            )
        ]
        manifest = {
            "schema_version": 1,
            "created_utc": "2026-07-10T00:00:00+00:00",
            "contract": {
                "prefix": prefix,
                "requested_steps": 250_000_000,
                "final_steps": 249_954_304,
                "schedule": schedule,
                "settings": {"expected_checkpoint_bytes": "16"},
                "rewards": {
                    arm: {"reward_sha256": reward_sha}
                    for arm, reward_sha in
                    analyze_reward_screen.CANONICAL_REWARD_SHA256.items()
                },
            },
        }
        manifest_path = root / "SCREEN_MANIFEST.json"
        write_json(manifest_path, manifest)
        manifest_sha = sha256(manifest_path)

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
        complete_results = []
        for index, (arm, seed) in enumerate(
                analyze_reward_screen.EXPECTED_SCHEDULE, 1):
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
                "reward_sha256":
                    analyze_reward_screen.CANONICAL_REWARD_SHA256[arm],
                "checkpoint_bytes": 16,
                "checkpoint_sha256": digest(f"checkpoint-{arm}-{seed}"),
                "log_sha256": digest(f"log-{arm}-{seed}"),
                "status_sha256": digest(f"status-{arm}-{seed}"),
                "process_sha256": digest(f"process-{arm}-{seed}"),
                "run_manifest_sha256": digest(f"manifest-{arm}-{seed}"),
                "eval_metrics": {
                    "n": 10_000 + index,
                    "tds": values[(arm, seed)],
                    "perf": values[(arm, seed)] / 100.0,
                },
            }
            write_json(path, result)
            complete_results.append({
                "index": index,
                "arm": arm,
                "seed": seed,
                "path": f"/remote/screen/{name}",
                "sha256": sha256(path),
                "checkpoint_sha256": result["checkpoint_sha256"],
            })

        if completion:
            write_json(root / "SCREEN_COMPLETE.json", {
                "schema_version": 1,
                "completed_utc": "2026-07-10T01:00:00+00:00",
                "screen_manifest_sha256": manifest_sha,
                "results": complete_results,
            })
        return manifest_sha

    def test_default_metrics_surface_draw_rate(self):
        self.assertIn("draw_rate", analyze_reward_screen.DEFAULT_METRICS)
        self.assertLess(
            analyze_reward_screen.DEFAULT_METRICS.index("perf"),
            analyze_reward_screen.DEFAULT_METRICS.index("draw_rate"),
        )

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

    def test_exact_action_canary_is_independently_qualified(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_exact_action_canary(tmp)
            report = analyze_reward_screen.analyze_screen(tmp, ("tds",))

        self.assertEqual(report["analysis"], "exact_action_canary_qualification")
        self.assertEqual(report["screen"]["profile"], "exact-action-canary")
        self.assertEqual(list(report["per_seed"]), ["42"])
        self.assertEqual(report["per_seed"]["42"]["effects"]["tds"], {})
        self.assertIn("qualification-only", " ".join(report["warnings"]))

    def test_exact_action_canary_rejects_nonfresh_or_misaligned_contract(self):
        mutations = (
            (
                "warm",
                lambda contract: contract.__setitem__(
                    "warm", {"path": "/remote/forbidden.bin"}),
                "null warm/pool",
            ),
            (
                "final_steps",
                lambda contract: contract.__setitem__(
                    "final_steps", contract["final_steps"] + 1),
                "complete-rollout budget",
            ),
            (
                "action_abi",
                lambda contract: contract["bootstrap"].__setitem__(
                    "action_abi", "marginal-heads"),
                "bootstrap action_abi mismatch",
            ),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                self.build_exact_action_canary(tmp)
                manifest_path = Path(tmp) / "SCREEN_MANIFEST.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                mutate(manifest["contract"])
                write_json(manifest_path, manifest)
                with self.assertRaisesRegex(
                        analyze_reward_screen.AnalysisError, message):
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
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                self.build_exact_action_canary(tmp)
                result_path = (
                    Path(tmp) / "exact-action-canary-test-both-s42.result.json")
                result = json.loads(result_path.read_text(encoding="utf-8"))
                mutate(result)
                write_json(result_path, result)
                with self.assertRaisesRegex(
                        analyze_reward_screen.AnalysisError, message):
                    analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_exact_action_canary_requires_empty_failures_and_lineage_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.build_exact_action_canary(tmp)
            result_path = (
                Path(tmp) / "exact-action-canary-test-both-s42.result.json")
            result = json.loads(result_path.read_text(encoding="utf-8"))
            result["acceptance_failures"] = None
            write_json(result_path, result)
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

        with tempfile.TemporaryDirectory() as tmp:
            self.build_exact_action_canary(tmp)
            completion_path = Path(tmp) / "SCREEN_COMPLETE.json"
            completion = json.loads(completion_path.read_text(encoding="utf-8"))
            completion["results"][0]["checkpoint_lineage_sha256"] = "0" * 64
            write_json(completion_path, completion)
            with self.assertRaisesRegex(
                    analyze_reward_screen.AnalysisError,
                    "checkpoint lineage hash mismatch"):
                analyze_reward_screen.analyze_screen(tmp, ("tds",))

    def test_possession_gain_profile_computes_separate_main_effects(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = "possession-gain-test"
            schedule = [
                {"index": index, "arm": arm, "seed": seed}
                for index, (arm, seed) in enumerate(
                    analyze_reward_screen.POSSESSION_GAIN_SCHEDULE, 1)
            ]
            manifest = {
                "schema_version": 1,
                "contract": {
                    "prefix": prefix,
                    "screen_profile": "possession-gain",
                    "requested_steps": 500_000_000,
                    "final_steps": 499_908_608,
                    "schedule": schedule,
                    "settings": {"expected_checkpoint_bytes": "16"},
                    "rewards": {
                        arm: {"reward_sha256": reward_sha}
                        for arm, reward_sha in
                        analyze_reward_screen.POSSESSION_GAIN_REWARD_SHA256.items()
                    },
                },
            }
            manifest_path = root / "SCREEN_MANIFEST.json"
            write_json(manifest_path, manifest)
            manifest_sha = sha256(manifest_path)
            values = {
                "both": 18.0,
                "possession_only": 12.0,
                "gain_only": 13.0,
                "neither": 10.0,
            }
            for arm, seed in analyze_reward_screen.POSSESSION_GAIN_SCHEDULE:
                write_json(root / f"{prefix}-{arm}-s{seed}.result.json", {
                    "schema_version": 2,
                    "trainer_complete": True,
                    "acceptance_pass": True,
                    "acceptance_failures": [],
                    "arm": arm,
                    "seed": seed,
                    "tag": f"{prefix}-{arm}-s{seed}",
                    "screen_manifest_sha256": manifest_sha,
                    "reward_sha256":
                        analyze_reward_screen.POSSESSION_GAIN_REWARD_SHA256[arm],
                    "checkpoint_bytes": 16,
                    "checkpoint_sha256": digest(f"checkpoint-{arm}-{seed}"),
                    "log_sha256": digest(f"log-{arm}-{seed}"),
                    "status_sha256": digest(f"status-{arm}-{seed}"),
                    "process_sha256": digest(f"process-{arm}-{seed}"),
                    "run_manifest_sha256": digest(f"manifest-{arm}-{seed}"),
                    "eval_metrics": {"n": 10_001, "tds": values[arm]},
                })
            report = analyze_reward_screen.analyze_screen(root, ("tds",))

        self.assertEqual(report["screen"]["profile"], "possession-gain")
        self.assertEqual(report["per_seed"]["42"]["effects"]["tds"], {
            "possession_main": 3.5,
            "gain_main": 4.5,
            "interaction": 3.0,
        })

    def test_paired_confirmation_profile_computes_candidate_contrast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = "paired-confirmation-test"
            candidate = "gain_only"
            schedule_pairs = (
                ("both", 42), (candidate, 42),
                (candidate, 43), ("both", 43),
            )
            schedule = [
                {"index": index, "arm": arm, "seed": seed}
                for index, (arm, seed) in enumerate(schedule_pairs, 1)
            ]
            rewards = {
                arm: {
                    "reward_sha256":
                        analyze_reward_screen.POSSESSION_GAIN_REWARD_SHA256[arm]
                }
                for arm in ("both", candidate)
            }
            manifest = {
                "schema_version": 1,
                "contract": {
                    "prefix": prefix,
                    "screen_profile": "paired-confirmation",
                    "candidate_arm": candidate,
                    "requested_steps": 1_000_000_000,
                    "final_steps": 999_948_288,
                    "schedule": schedule,
                    "settings": {"expected_checkpoint_bytes": "16"},
                    "rewards": rewards,
                },
            }
            manifest_path = root / "SCREEN_MANIFEST.json"
            write_json(manifest_path, manifest)
            manifest_sha = sha256(manifest_path)
            values = {
                ("both", 42): 18.0, (candidate, 42): 17.0,
                ("both", 43): 20.0, (candidate, 43): 21.0,
            }
            for arm, seed in schedule_pairs:
                write_json(root / f"{prefix}-{arm}-s{seed}.result.json", {
                    "schema_version": 2,
                    "trainer_complete": True,
                    "acceptance_pass": True,
                    "acceptance_failures": [],
                    "arm": arm,
                    "seed": seed,
                    "tag": f"{prefix}-{arm}-s{seed}",
                    "screen_manifest_sha256": manifest_sha,
                    "reward_sha256": rewards[arm]["reward_sha256"],
                    "checkpoint_bytes": 16,
                    "checkpoint_sha256": digest(f"checkpoint-{arm}-{seed}"),
                    "log_sha256": digest(f"log-{arm}-{seed}"),
                    "status_sha256": digest(f"status-{arm}-{seed}"),
                    "process_sha256": digest(f"process-{arm}-{seed}"),
                    "run_manifest_sha256": digest(f"manifest-{arm}-{seed}"),
                    "eval_metrics": {"n": 10_001, "tds": values[(arm, seed)]},
                })

            report = analyze_reward_screen.analyze_screen(root, ("tds",))

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
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = "paired-final-test"
            candidate = "gain_only"
            schedule_pairs = (
                ("both", 42), (candidate, 42),
                (candidate, 43), ("both", 43),
                ("both", 44), (candidate, 44),
            )
            schedule = [
                {"index": index, "arm": arm, "seed": seed}
                for index, (arm, seed) in enumerate(schedule_pairs, 1)
            ]
            rewards = {
                arm: {
                    "reward_sha256":
                        analyze_reward_screen.POSSESSION_GAIN_REWARD_SHA256[arm]
                }
                for arm in ("both", candidate)
            }
            manifest_path = root / "SCREEN_MANIFEST.json"
            write_json(manifest_path, {
                "schema_version": 1,
                "contract": {
                    "prefix": prefix,
                    "screen_profile": "paired-final",
                    "candidate_arm": candidate,
                    "requested_steps": 6_000_000_000,
                    "final_steps": 5_999_951_872,
                    "schedule": schedule,
                    "settings": {"expected_checkpoint_bytes": "16"},
                    "rewards": rewards,
                },
            })
            manifest_sha = sha256(manifest_path)
            values = {
                ("both", 42): 18.0, (candidate, 42): 17.0,
                ("both", 43): 20.0, (candidate, 43): 21.0,
                ("both", 44): 22.0, (candidate, 44): 25.0,
            }
            for arm, seed in schedule_pairs:
                write_json(root / f"{prefix}-{arm}-s{seed}.result.json", {
                    "schema_version": 2,
                    "trainer_complete": True,
                    "acceptance_pass": True,
                    "acceptance_failures": [],
                    "arm": arm,
                    "seed": seed,
                    "tag": f"{prefix}-{arm}-s{seed}",
                    "screen_manifest_sha256": manifest_sha,
                    "reward_sha256": rewards[arm]["reward_sha256"],
                    "checkpoint_bytes": 16,
                    "checkpoint_sha256": digest(f"checkpoint-{arm}-{seed}"),
                    "log_sha256": digest(f"log-{arm}-{seed}"),
                    "status_sha256": digest(f"status-{arm}-{seed}"),
                    "process_sha256": digest(f"process-{arm}-{seed}"),
                    "run_manifest_sha256": digest(f"manifest-{arm}-{seed}"),
                    "eval_metrics": {"n": 10_001, "tds": values[(arm, seed)]},
                })
            report = analyze_reward_screen.analyze_screen(root, ("tds",))

        self.assertEqual(report["screen"]["profile"], "paired-final")
        self.assertEqual(list(report["per_seed"]), ["42", "43", "44"])
        across = report["across_seeds"]["effects"]["tds"][
            "candidate_minus_both"
        ]
        self.assertEqual(across["seed_count"], 3)
        self.assertEqual(across["mean"], 1.0)
        self.assertIn("n=3", " ".join(report["warnings"]))

    def test_control_final_profile_replicates_r0_across_three_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = "control-final-test"
            schedule_pairs = (("both", 42), ("both", 43), ("both", 44))
            manifest_path = root / "SCREEN_MANIFEST.json"
            write_json(manifest_path, {
                "schema_version": 1,
                "contract": {
                    "prefix": prefix,
                    "screen_profile": "control-final",
                    "requested_steps": 12_000_000_000,
                    "final_steps": 11_999_969_280,
                    "schedule": [
                        {"index": index, "arm": arm, "seed": seed}
                        for index, (arm, seed) in enumerate(schedule_pairs, 1)
                    ],
                    "settings": {"expected_checkpoint_bytes": "16"},
                    "rewards": {
                        "both": {
                            "reward_sha256": analyze_reward_screen
                            .POSSESSION_GAIN_REWARD_SHA256["both"]
                        }
                    },
                },
            })
            manifest_sha = sha256(manifest_path)
            for arm, seed in schedule_pairs:
                write_json(root / f"{prefix}-{arm}-s{seed}.result.json", {
                    "schema_version": 2,
                    "trainer_complete": True,
                    "acceptance_pass": True,
                    "acceptance_failures": [],
                    "arm": arm,
                    "seed": seed,
                    "tag": f"{prefix}-{arm}-s{seed}",
                    "screen_manifest_sha256": manifest_sha,
                    "reward_sha256": analyze_reward_screen
                    .POSSESSION_GAIN_REWARD_SHA256["both"],
                    "checkpoint_bytes": 16,
                    "checkpoint_sha256": digest(f"checkpoint-{arm}-{seed}"),
                    "log_sha256": digest(f"log-{arm}-{seed}"),
                    "status_sha256": digest(f"status-{arm}-{seed}"),
                    "process_sha256": digest(f"process-{arm}-{seed}"),
                    "run_manifest_sha256": digest(f"manifest-{arm}-{seed}"),
                    "eval_metrics": {"n": 10_001, "tds": seed / 10.0},
                })
            report = analyze_reward_screen.analyze_screen(root, ("tds",))

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


if __name__ == "__main__":
    unittest.main()
