#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import run_reward_learned_transfer as learned


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


class LearnedTransferTests(unittest.TestCase):
    def build_matrix(self, root: Path, *, candidate_delta: float = -0.01) -> Path:
        root = Path(root)
        anchors = [
            {
                "name": name,
                "path": f"/frozen/{name}.bin",
                "bytes": learned.EXPECTED_NATIVE_BYTES,
                "sha256": digest(f"anchor-{name}"),
            }
            for name in ("league9", "turnover3")
        ]
        checkpoints = {
            arm: {
                str(seed): {
                    "native": f"/frozen/{arm}-s{seed}.bin",
                    "native_sha256": digest(f"{arm}-{seed}"),
                }
                for seed in (42, 43)
            }
            for arm in ("both", "gain_only")
        }
        plan = {
            "schema_version": 1,
            "reference_arm": "both",
            "candidate_arm": "gain_only",
            "training_seeds": [42, 43],
            "orientations": [0, 1],
            "games_per_cell": 4096,
            "anchors": anchors,
            "checkpoints": checkpoints,
            "gates": {
                "mean_score_delta_min": -0.02,
                "lower_confidence_bound_min": -0.05,
                "anchor_mean_score_delta_min": -0.05,
                "cell_score_delta_min": -0.10,
            },
            "source_screen_complete_sha256": digest("screen-complete"),
        }
        manifest = root / "LEARNED_TRANSFER_MANIFEST.json"
        write_json(manifest, plan)
        manifest_sha = learned.sha256(manifest)
        for expected in learned.expected_cells(plan):
            focal_score = 0.50 if expected["arm"] == "both" else 0.50 + candidate_delta
            checkpoint = checkpoints[expected["arm"]][
                str(expected["training_seed"])
            ]
            anchor = next(
                value for value in anchors if value["name"] == expected["anchor"]
            )
            write_json(
                root / expected["path"],
                {
                    "schema_version": 1,
                    "learned_transfer_manifest_sha256": manifest_sha,
                    "arm": expected["arm"],
                    "training_seed": expected["training_seed"],
                    "anchor": expected["anchor"],
                    "orientation": expected["orientation"],
                    "match_seed": expected["match_seed"],
                    "games_requested": 4096,
                    "games": 4096,
                    "focal_score": focal_score,
                    "opponent_score": 1.0 - focal_score,
                    "draw_rate": 0.8,
                    "focal_checkpoint_sha256": checkpoint["native_sha256"],
                    "anchor_checkpoint_sha256": anchor["sha256"],
                    "integrity": {key: 0.0 for key in learned.INTEGRITY_KEYS},
                },
            )
        return root

    def test_equal_cell_analysis_passes_declared_noninferiority_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_matrix(Path(tmp))
            report = learned.analyze(root)

        self.assertEqual(report["cell_count"], 16)
        self.assertEqual(report["total_games"], 16 * 4096)
        self.assertAlmostEqual(
            report["paired_candidate_minus_reference"]["summary"]["mean"],
            -0.01,
        )
        self.assertTrue(report["eligible_for_longer_confirmation"])
        self.assertEqual(report["gate_failures"], [])
        self.assertEqual(
            set(report["paired_candidate_minus_reference"]["by_anchor"]),
            {"league9", "turnover3"},
        )

    def test_gate_failure_is_fail_closed_and_completion_revalidates_cells(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_matrix(Path(tmp), candidate_delta=-0.06)
            learned.complete(root)
            complete = root / "LEARNED_TRANSFER_COMPLETE.json"
            report = learned.validate_completion(complete)
            self.assertFalse(report["eligible_for_longer_confirmation"])
            self.assertIn("mean_score_delta", report["gate_failures"])
            self.assertIn("lower_confidence_bound", report["gate_failures"])
            expected_sha = learned.sha256(complete)
            learned.validate_completion(complete, expected_sha256=expected_sha)

            path = root / learned.expected_cells(
                learned.load_object(
                    root / "LEARNED_TRANSFER_MANIFEST.json", "manifest"
                )
            )[0]["path"]
            cell = learned.load_object(path, "cell")
            cell["focal_score"] = 0.99
            cell["opponent_score"] = 0.01
            write_json(path, cell)
            with self.assertRaisesRegex(
                learned.LearnedTransferError,
                "stored learned-transfer analysis is stale",
            ):
                learned.validate_completion(complete)

    def test_missing_integrity_counter_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = self.build_matrix(Path(tmp))
            plan = learned.load_object(
                root / "LEARNED_TRANSFER_MANIFEST.json", "manifest"
            )
            expected = learned.expected_cells(plan)[0]
            path = root / expected["path"]
            cell = learned.load_object(path, "cell")
            del cell["integrity"][learned.INTEGRITY_KEYS[0]]
            write_json(path, cell)
            with self.assertRaisesRegex(
                learned.LearnedTransferError, "integrity fields are incomplete"
            ):
                learned.analyze(root)

    def test_anchor_config_rejects_unknown_gate_or_too_small_sample(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "anchors.json"
            write_json(
                path,
                {
                    "schema_version": 1,
                    "games_per_cell": 999,
                    "anchors": [{"unexpected": True}],
                    "gates": {},
                },
            )
            with self.assertRaisesRegex(
                learned.LearnedTransferError, "at least 1000"
            ):
                learned.validate_anchor_config(path)


if __name__ == "__main__":
    unittest.main()
