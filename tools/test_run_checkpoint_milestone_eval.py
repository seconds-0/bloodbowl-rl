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
                "name": "alpha",
                "path": "/tmp/alpha.bin",
                "bytes": milestone.EXPECTED_NATIVE_BYTES,
                "sha256": "a" * 64,
            },
            {
                "name": "beta",
                "path": "/tmp/beta.bin",
                "bytes": milestone.EXPECTED_NATIVE_BYTES,
                "sha256": "b" * 64,
            },
        ]
        targets = [0, 1_000, 2_000, 4_000]
        checkpoints = {
            "42": [
                {
                    "training_seed": 42,
                    "target_steps": target,
                    "embedded_steps": target if target else 0,
                    "native": f"/tmp/{target}.bin",
                    "native_bytes": milestone.EXPECTED_NATIVE_BYTES,
                    "native_sha256": f"{index + 1:064x}",
                    "source": "warm" if target == 0 else "interval",
                }
                for index, target in enumerate(targets)
            ]
        }
        plan = {
            "schema_version": 1,
            "matrix_id": "test-matrix",
            "training_seeds": [42],
            "target_steps": targets,
            "games_per_cell": 1_000,
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
                "games_requested": 1_000,
                "games": 1_000,
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
                {0: 0.40, 1_000: 0.50, 2_000: 0.51, 4_000: 0.505},
            )
            report = milestone.analyze(directory)
            self.assertEqual(report["cell_count"], 16)
            self.assertEqual(report["total_games"], 16_000)
            points = report["trajectories"]["42"]
            self.assertAlmostEqual(points[2]["score_delta_warm"], 0.11)
            nomination = report["stage_b_nominations"]["42"]
            self.assertEqual(nomination["target_steps"], 1_000)
            self.assertFalse(nomination["exploratory"])

    def test_nonzero_integrity_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            plan = self.synthetic_plan(directory)
            self.write_cells(
                directory,
                plan,
                {0: 0.40, 1_000: 0.50, 2_000: 0.51, 4_000: 0.505},
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
                {0: 0.40, 1_000: 0.50, 2_000: 0.51, 4_000: 0.505},
            )
            milestone.complete(directory)
            completion = directory / "MILESTONE_EVAL_COMPLETE.json"
            report = milestone.validate_completion(
                completion, milestone.sha256(completion)
            )
            self.assertEqual(report["total_games"], 16_000)
            first = directory / milestone.expected_cells(plan)[0]["path"]
            cell = json.loads(first.read_text(encoding="utf-8"))
            cell["focal_score"] += 0.01
            first.write_text(
                json.dumps(cell, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            with self.assertRaises(milestone.MilestoneEvalError):
                milestone.validate_completion(completion)

    def test_terminal_is_fixed_nominee_when_curve_never_plateaus_early(self):
        points = [
            {"target_steps": 0, "embedded_steps": 0, "macro_score": 0.4},
            {"target_steps": 1, "embedded_steps": 1, "macro_score": 0.50},
            {"target_steps": 2, "embedded_steps": 2, "macro_score": 0.53},
            {"target_steps": 4, "embedded_steps": 4, "macro_score": 0.56},
        ]
        nomination = milestone.nominate(points)
        # The terminal point satisfies the fixed rule vacuously; this keeps a
        # monotonically rising curve on its exact final checkpoint.
        self.assertEqual(nomination["target_steps"], 4)
        self.assertFalse(nomination["exploratory"])

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
