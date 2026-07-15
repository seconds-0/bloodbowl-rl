#!/usr/bin/env python3

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


TOOLS = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS))

import run_checkpoint_milestone_eval as milestone  # noqa: E402


ZERO_INTEGRITY = {key: 0.0 for key in milestone.INTEGRITY_KEYS}


class MilestoneEvalTests(unittest.TestCase):
    def test_resolve_target_uses_greatest_step_not_above_target(self):
        rows = [
            (100, Path("100.bin")),
            (200, Path("200.bin")),
            (300, Path("300.bin")),
        ]
        self.assertEqual(
            milestone.resolve_target(rows, 250, 60),
            (200, Path("200.bin")),
        )
        with self.assertRaisesRegex(
            milestone.MilestoneEvalError, "gap exceeds contract"
        ):
            milestone.resolve_target(rows, 250, 49)
        with self.assertRaisesRegex(
            milestone.MilestoneEvalError, "no checkpoint exists"
        ):
            milestone.resolve_target(rows, 50, 60)

    def test_expected_cells_reuses_match_seed_across_milestones(self):
        plan = {
            "training_seeds": [42, 43],
            "target_steps": [0, 1_000, 2_000],
            "anchors": [
                {"name": "alpha"},
                {"name": "beta"},
            ],
            "orientations": [0, 1],
        }
        rows = milestone.expected_cells(plan)
        self.assertEqual(len(rows), 2 * 3 * 2 * 2)
        stratum = [
            row
            for row in rows
            if row["training_seed"] == 42
            and row["anchor"] == "alpha"
            and row["orientation"] == 1
        ]
        self.assertEqual(
            {row["match_seed"] for row in stratum},
            {30_001},
        )
        self.assertEqual(
            {row["target_steps"] for row in stratum},
            {0, 1_000, 2_000},
        )

    def synthetic_plan(self, directory: Path) -> dict:
        anchors = [
            {
                "name": name,
                "path": f"/tmp/{name}.bin",
                "bytes": milestone.EXPECTED_NATIVE_BYTES,
                "sha256": checkpoint_sha,
            }
            for name, checkpoint_sha in milestone.FIXED_ANCHOR_SHA256.items()
        ]
        targets = list(milestone.FIXED_TARGET_STEPS)
        checkpoints = {
            str(seed): [
                {
                    "training_seed": seed,
                    "target_steps": target,
                    "embedded_steps": target if target else 0,
                    "native": f"/tmp/s{seed}-{target}.bin",
                    "native_bytes": milestone.EXPECTED_NATIVE_BYTES,
                    "native_sha256": f"{seed * 100 + index + 1:064x}",
                    "source": "warm" if target == 0 else "interval",
                }
                for index, target in enumerate(targets)
            ]
            for seed in milestone.CONTROL_SEEDS
        }
        plan = {
            "schema_version": 1,
            "matrix_id": "test-matrix",
            "profile": "control-final",
            "training_seeds": list(milestone.CONTROL_SEEDS),
            "target_steps": targets,
            "max_target_gap_steps": milestone.FIXED_MAX_TARGET_GAP_STEPS,
            "games_per_cell": milestone.FIXED_GAMES_PER_CELL,
            "orientations": [0, 1],
            "anchors": anchors,
            "checkpoints": checkpoints,
            "implementation": {},
            "screen_complete_sha256": "c" * 64,
        }
        (directory / "MILESTONE_EVAL_MANIFEST.json").write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return plan

    def write_cells(self, directory: Path, plan: dict, scores: dict[int, float]):
        manifest_sha = milestone.sha256(directory / "MILESTONE_EVAL_MANIFEST.json")
        for expected in milestone.expected_cells(plan):
            checkpoint = milestone.checkpoint_record(
                plan, expected["training_seed"], expected["target_steps"]
            )
            anchor = next(
                row for row in plan["anchors"] if row["name"] == expected["anchor"]
            )
            score = scores[expected["target_steps"]]
            cell = {
                "schema_version": 1,
                "milestone_eval_manifest_sha256": manifest_sha,
                "training_seed": expected["training_seed"],
                "target_steps": expected["target_steps"],
                "embedded_steps": checkpoint["embedded_steps"],
                "anchor": expected["anchor"],
                "orientation": expected["orientation"],
                "match_seed": expected["match_seed"],
                "games_requested": milestone.FIXED_GAMES_PER_CELL,
                "games": milestone.FIXED_GAMES_PER_CELL,
                "focal_score": score,
                "opponent_score": 1.0 - score,
                "draw_rate": 0.4,
                "focal_win_rate": score - 0.2,
                "focal_loss_rate": 0.8 - score,
                "focal_tds": 1.0 + score,
                "opponent_tds": 1.5 - score,
                "focal_checkpoint_sha256": checkpoint["native_sha256"],
                "anchor_checkpoint_sha256": anchor["sha256"],
                "implementation": {},
                "integrity": dict(ZERO_INTEGRITY),
            }
            (directory / expected["path"]).write_text(
                json.dumps(cell, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )

    def test_analysis_applies_fixed_plateau_nomination(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = self.synthetic_plan(directory)
            self.write_cells(
                directory,
                plan,
                {
                    0: 0.40,
                    1_000_000_000: 0.50,
                    2_000_000_000: 0.51,
                    4_000_000_000: 0.505,
                    6_000_000_000: 0.505,
                    8_000_000_000: 0.505,
                    10_000_000_000: 0.505,
                    12_000_000_000: 0.505,
                },
            )
            report = milestone.analyze(directory)
            self.assertEqual(report["cell_count"], 192)
            self.assertEqual(report["total_games"], 393_216)
            points = report["trajectories"]["42"]
            self.assertAlmostEqual(points[2]["score_delta_warm"], 0.11)
            nomination = report["stage_b_nominations"]["42"]
            self.assertEqual(nomination["target_steps"], 1_000_000_000)
            self.assertFalse(nomination["exploratory"])
            aggregate = report["aggregate_trajectory"][2]
            self.assertAlmostEqual(aggregate["score_delta_warm"]["mean"], 0.11)
            self.assertEqual(aggregate["score"]["clusters"], 3)

    def test_exact_cluster_bootstrap_uses_all_seed_resamples(self):
        summary = milestone.exact_cluster_bootstrap([0.4, 0.5, 0.6])
        self.assertAlmostEqual(summary["mean"], 0.5)
        self.assertEqual(summary["clusters"], 3)
        self.assertEqual(summary["exact_resamples"], 27)
        self.assertLess(summary["lower_95"], 0.5)
        self.assertGreater(summary["upper_95"], 0.5)

    def test_nonzero_integrity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = self.synthetic_plan(directory)
            self.write_cells(
                directory,
                plan,
                {target: 0.5 for target in milestone.FIXED_TARGET_STEPS},
            )
            expected = milestone.expected_cells(plan)[0]
            path = directory / expected["path"]
            cell = json.loads(path.read_text(encoding="utf-8"))
            cell["integrity"]["reward_clip_episodes"] = 1.0
            path.write_text(
                json.dumps(cell, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(
                milestone.MilestoneEvalError, "integrity counters nonzero"
            ):
                milestone.validate_cell(path, plan, expected)

    def test_completion_revalidates_manifest_analysis_and_every_cell(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = self.synthetic_plan(directory)
            self.write_cells(
                directory,
                plan,
                {target: 0.5 for target in milestone.FIXED_TARGET_STEPS},
            )
            milestone.complete(directory)
            completion = directory / "MILESTONE_EVAL_COMPLETE.json"
            with mock.patch.object(milestone, "verify_plan_sources"):
                report = milestone.validate_completion(
                    completion, milestone.sha256(completion)
                )
            self.assertEqual(report["total_games"], 393_216)
            first = directory / milestone.expected_cells(plan)[0]["path"]
            cell = json.loads(first.read_text(encoding="utf-8"))
            cell["focal_score"] += 0.01
            first.write_text(
                json.dumps(cell, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with mock.patch.object(milestone, "verify_plan_sources"):
                with self.assertRaises(milestone.MilestoneEvalError):
                    milestone.validate_completion(completion)

    def test_plan_contract_rejects_reordered_anchor_seed_strata(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = self.synthetic_plan(directory)
            plan["anchors"].reverse()
            with self.assertRaisesRegex(
                milestone.MilestoneEvalError, "anchor contract drifted"
            ):
                milestone.validate_plan_contract(plan)

    def test_nonterminal_fallback_remains_distinct_from_terminal(self):
        points = [
            {"target_steps": 0, "embedded_steps": 0, "macro_score": 0.4},
            {"target_steps": 1, "embedded_steps": 1, "macro_score": 0.50},
            {"target_steps": 2, "embedded_steps": 2, "macro_score": 0.53},
            {"target_steps": 4, "embedded_steps": 4, "macro_score": 0.56},
        ]
        nomination = milestone.nominate(points)
        self.assertEqual(nomination["target_steps"], 2)
        self.assertTrue(nomination["exploratory"])

    def test_idle_gpu_gate_fails_closed_on_existing_owner(self):
        with mock.patch.object(
            milestone.subprocess,
            "run",
            return_value=SimpleNamespace(
                returncode=0, stdout="431596, python\n453879, python\n"
            ),
        ):
            with self.assertRaisesRegex(
                milestone.MilestoneEvalError, "GPU is not exclusive"
            ):
                milestone.require_idle_gpu()

    def test_idle_gpu_gate_accepts_empty_compute_inventory(self):
        with mock.patch.object(
            milestone.subprocess,
            "run",
            return_value=SimpleNamespace(returncode=0, stdout=""),
        ):
            milestone.require_idle_gpu()

    def test_idle_gpu_gate_requires_bbtv_to_be_explicitly_quiesced(self):
        with mock.patch.object(
            milestone.subprocess,
            "run",
            side_effect=[
                SimpleNamespace(returncode=0, stdout=""),
                SimpleNamespace(
                    returncode=0,
                    stdout="453879 python stream_backend/follow_latest.py\n",
                ),
            ],
        ):
            with self.assertRaisesRegex(
                milestone.MilestoneEvalError, "BBTV follower is active"
            ):
                milestone.require_idle_gpu()


if __name__ == "__main__":
    unittest.main()
