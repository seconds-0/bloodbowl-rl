#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import vacation_reward_gate as gate


def write_json(path: Path, payload: dict) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


class VacationRewardGateTests(unittest.TestCase):
    def make_config(self, root: Path) -> Path:
        path = root / "GATE_CONFIG.json"
        write_json(path, {
            "schema_version": 1,
            "candidate_arm": "gain_only",
            "mean_perf_delta_min": -0.02,
            "seed_perf_delta_min": -0.05,
            "max_candidate_td_relative_drop": 0.20,
        })
        return path

    def test_screen_gate_checks_mean_each_seed_and_td_retention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = gate.validate_config(self.make_config(root))
            complete = root / "SCREEN_COMPLETE.json"
            write_json(complete, {"screen_manifest_sha256": "a" * 64})
            report = {
                "screen": {
                    "profile": "paired-confirmation",
                    "candidate_arm": "gain_only",
                    "manifest_sha256": "a" * 64,
                    "requested_steps": 1_000_000_000,
                    "final_steps": 999_948_288,
                    "completion": {
                        "present": True,
                        "sha256": gate.sha256(complete),
                    },
                },
                "across_seeds": {
                    "effects": {
                        "perf": {
                            "candidate_minus_both": {
                                "values_by_seed": {"42": -0.01, "43": -0.06},
                                "mean": -0.035,
                            }
                        }
                    },
                    "cell_summaries": {
                        "both": {"tds": {"mean": 1.0}},
                        "gain_only": {"tds": {"mean": 0.7}},
                    },
                },
            }
            with mock.patch.object(
                gate.analyze_reward_screen, "analyze_screen", return_value=report
            ):
                result, failures = gate.validate_screen(
                    complete, config, "main"
                )

        self.assertEqual(
            failures,
            ["mean_perf_delta", "seed_perf_delta", "candidate_td_relative_drop"],
        )
        self.assertAlmostEqual(result["candidate_td_relative_drop"], 0.3)

    def test_two_lineage_report_requires_every_stratum(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.make_config(root)
            paths = [root / f"artifact-{index}.json" for index in range(6)]
            for path in paths:
                write_json(path, {"ok": True})

            def screen_result(path, _config, lineage):
                return ({
                    "path": str(path),
                    "sha256": gate.sha256(path),
                    "manifest_sha256": ("a" if lineage == "main" else "b") * 64,
                }, [])

            def scripted_result(path, *_args):
                return {"path": str(path), "sha256": gate.sha256(path)}

            def learned_result(path, *_args):
                return ({
                    "path": str(path),
                    "sha256": gate.sha256(path),
                    "eligible_for_longer_confirmation": True,
                    "gate_failures": [],
                    "mean_score_delta": 0.0,
                    "normal_95_lower_bound": -0.01,
                }, [])

            with (
                mock.patch.object(gate, "validate_screen", side_effect=screen_result),
                mock.patch.object(gate, "validate_scripted", side_effect=scripted_result),
                mock.patch.object(gate, "validate_learned", side_effect=learned_result),
            ):
                report = gate.build_report(
                    config,
                    main_screen=paths[0],
                    main_scripted=paths[1],
                    main_learned=paths[2],
                    second_screen=paths[3],
                    second_scripted=paths[4],
                    second_learned=paths[5],
                )

        self.assertTrue(report["passed"])
        self.assertEqual(set(report["lineages"]), {"main", "second"})
        self.assertEqual(report["candidate_arm"], "gain_only")

    def test_rejection_never_materializes_success_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "GATE_COMPLETE.json"
            report = {
                "schema_version": 1,
                "candidate_arm": "gain_only",
                "passed": False,
                "failures": ["second:learned_mean_score_delta"],
            }
            with self.assertRaises(gate.GateRejected):
                gate.write_gate(output, report)
            self.assertFalse(output.exists())

    def test_config_is_closed_and_finite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.make_config(root)
            payload = json.loads(path.read_text())
            payload["typo"] = 1
            write_json(path, payload)
            with self.assertRaisesRegex(gate.GateError, "unknown or missing"):
                gate.validate_config(path)


if __name__ == "__main__":
    unittest.main()
