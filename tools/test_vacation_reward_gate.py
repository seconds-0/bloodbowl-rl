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


def scripted_contract() -> dict:
    return {
        "seeds": [42, 43],
        "bot_types": [0, 1],
        "bot_teams": [0, 1],
        "settings": {"requested_train_steps": 131_072},
        "implementation": {"compiled_module_sha256": "1" * 64},
        "orchestration_files": {"/frozen/runner.py": "2" * 64},
        "conversion": {"converter_sha256": "3" * 64},
        "gates": {"mean_score_delta_min": -0.02},
    }


def learned_contract() -> dict:
    return {
        "training_seeds": [42, 43],
        "orientations": [0, 1],
        "games_per_cell": 4096,
        "anchor_config": "/frozen/anchors.json",
        "anchor_config_sha256": "c" * 64,
        "anchors": [{"name": "league9", "sha256": "d" * 64}],
        "gates": {"mean_score_delta_min": -0.02},
        "implementation": {"compiled_module_sha256": "4" * 64},
    }


class VacationRewardGateTests(unittest.TestCase):
    def make_config(self, root: Path) -> Path:
        path = root / "GATE_CONFIG.json"
        write_json(path, {
            "schema_version": 1,
            "candidate_arm": "gain_only",
            "confirmation_steps": 1_000_000_000,
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
                return {
                    "path": str(path),
                    "sha256": gate.sha256(path),
                    "contract_identity": scripted_contract(),
                }

            def learned_result(path, *_args):
                return ({
                    "path": str(path),
                    "sha256": gate.sha256(path),
                    "eligible_for_longer_confirmation": True,
                    "gate_failures": [],
                    "mean_score_delta": 0.0,
                    "worst_training_seed_mean": -0.01,
                    "games_per_cell": 4096,
                    "anchor_config_sha256": "c" * 64,
                    "anchor_identity": [["league9", "d" * 64]],
                    "gates": {"mean_score_delta_min": -0.02},
                    "contract_identity": learned_contract(),
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

    def test_two_lineage_report_rejects_different_learned_anchors(self):
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

            def learned_result(path, _screen, _config, lineage):
                contract = learned_contract()
                contract["anchor_config_sha256"] = (
                    "c" if lineage == "main" else "d"
                ) * 64
                return ({
                    "path": str(path),
                    "sha256": gate.sha256(path),
                    "games_per_cell": 4096,
                    "anchor_config_sha256": ("c" if lineage == "main" else "d") * 64,
                    "anchor_identity": [["anchor", "e" * 64]],
                    "gates": {},
                    "contract_identity": contract,
                }, [])

            with (
                mock.patch.object(gate, "validate_screen", side_effect=screen_result),
                mock.patch.object(
                    gate, "validate_scripted",
                    side_effect=lambda path, *_args: {
                        "path": str(path),
                        "contract_identity": scripted_contract(),
                    },
                ),
                mock.patch.object(gate, "validate_learned", side_effect=learned_result),
                self.assertRaisesRegex(gate.GateError, "learned-transfer contract"),
            ):
                gate.build_report(
                    config,
                    main_screen=paths[0],
                    main_scripted=paths[1],
                    main_learned=paths[2],
                    second_screen=paths[3],
                    second_scripted=paths[4],
                    second_learned=paths[5],
                )

    def test_two_lineage_report_rejects_scripted_implementation_drift(self):
        self.assert_contract_drift_rejected("scripted")

    def test_two_lineage_report_rejects_learned_implementation_drift(self):
        self.assert_contract_drift_rejected("learned")

    def assert_contract_drift_rejected(self, transfer: str):
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

            def scripted_result(path, _screen, _config, lineage):
                contract = scripted_contract()
                if transfer == "scripted" and lineage == "second":
                    contract["implementation"] = {
                        "compiled_module_sha256": "9" * 64
                    }
                return {"path": str(path), "contract_identity": contract}

            def learned_result(path, _screen, _config, lineage):
                contract = learned_contract()
                if transfer == "learned" and lineage == "second":
                    contract["implementation"] = {
                        "compiled_module_sha256": "9" * 64
                    }
                return ({
                    "path": str(path),
                    "contract_identity": contract,
                }, [])

            with (
                mock.patch.object(gate, "validate_screen", side_effect=screen_result),
                mock.patch.object(
                    gate, "validate_scripted", side_effect=scripted_result
                ),
                mock.patch.object(gate, "validate_learned", side_effect=learned_result),
                self.assertRaisesRegex(
                    gate.GateError, f"{transfer}-transfer contract"
                ),
            ):
                gate.build_report(
                    config,
                    main_screen=paths[0],
                    main_scripted=paths[1],
                    main_learned=paths[2],
                    second_screen=paths[3],
                    second_scripted=paths[4],
                    second_learned=paths[5],
                )

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
