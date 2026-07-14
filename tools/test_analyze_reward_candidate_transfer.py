#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import analyze_reward_candidate_transfer as transfer
import run_reward_candidate_transfer as runner


def digest(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


class RewardCandidateTransferTests(unittest.TestCase):
    @staticmethod
    def write_completion(root: Path, report: dict) -> Path:
        analysis = root / "ANALYSIS.json"
        analysis.write_text(
            json.dumps(report, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        complete = root / "TRANSFER_COMPLETE.json"
        complete.write_text(json.dumps({
            "schema_version": 1,
            "recommended_confirmation_arm": report["recommendation"]["arm"],
            "analysis_sha256": hashlib.sha256(analysis.read_bytes()).hexdigest(),
            "transfer_manifest_sha256": report["transfer_manifest"]["sha256"],
            "cells": [
                {"log": row["log"], "sha256": row["log_sha256"]}
                for row in report["runs"]
            ],
        }, sort_keys=True) + "\n", encoding="utf-8")
        return complete

    def write_manifest(self, root: Path) -> dict:
        arms = ("both", "possession_only", "gain_only", "neither")
        (root / "training").mkdir()
        (root / "puffer/config").mkdir(parents=True)
        (root / "training/convert_checkpoint.py").write_text("# converter\n")
        (root / "puffer/config/bloodbowl.ini").write_text("[bloodbowl]\n")
        orchestration = root / "orchestration.py"
        orchestration.write_text("# frozen\n")
        implementation = {
            key: digest(key) for key in transfer.IMPLEMENTATION_KEYS
        }
        checkpoints = {
            arm: {
                str(seed): {"torch_sha256": digest(f"{arm}-{seed}")}
                for seed in (42, 43)
            }
            for arm in arms
        }
        with (
            mock.patch.object(
                runner, "implementation_identity", return_value=implementation
            ),
            mock.patch.object(
                runner,
                "orchestration_identity",
                return_value={str(orchestration): digest("# frozen\n")},
            ),
        ):
            manifest = runner.freeze_manifest(
                root / "TRANSFER_MANIFEST.json",
                root,
                root / "screen",
                "a" * 64,
                checkpoints,
                arms,
            )
        return manifest

    def write_cell(
        self, root: Path, manifest: dict, arm: str, seed: int,
        bot_type: int, bot_team: int,
    ) -> None:
        scores = {
            "both": 0.50,
            "possession_only": 0.49,
            "gain_only": 0.52,
            "neither": 0.44,
        }
        champion_tds = {
            "both": 1.0, "possession_only": 0.95,
            "gain_only": 1.05, "neither": 0.70,
        }
        bot_tds = {
            "both": 0.8, "possession_only": 0.82,
            "gain_only": 0.75, "neither": 1.1,
        }
        champion_team = 1 - bot_team
        score = scores[arm]
        settings = manifest["settings"]
        implementation = manifest["implementation"]
        eval_manifest = {
            "schema_version": 1,
            "mode": "scripted_bot_frozen",
            "checkpoint_sha256": manifest["checkpoints"][arm][str(seed)][
                "torch_sha256"],
            "requested_train_steps": settings["requested_train_steps"],
            "seed": seed,
            **implementation,
            "bot_type": bot_type,
            "bot_team": bot_team,
            "eval_episodes": settings["eval_episodes"],
            "min_eval_games": settings["min_eval_games"],
            "command": [
                "puffer", "train", "bloodbowl",
                "--train.total-timesteps",
                str(settings["requested_train_steps"]),
                "--eval-episodes", str(settings["eval_episodes"]),
                "--seed", str(seed), "--train.seed", str(seed),
                "--env.seed", str(seed),
                "--env.scripted-opponent-type", str(bot_type),
                "--env.scripted-opponent-team", str(bot_team),
            ],
        }
        panel = {
            "_puffer_schema": 2,
            "_puffer_phase_eval": 1,
            "_puffer_env_cumulative": 0,
            "_puffer_final_reprint": 0,
            "_puffer_eval_episodes_completed": settings["eval_episodes"],
            "n": settings["eval_episodes"],
            "slot_0_score": score if champion_team == 0 else 1 - score,
            "slot_1_score": score if champion_team == 1 else 1 - score,
            "draw_rate": 0.4,
            "tds_t0": (champion_tds[arm] if champion_team == 0
                       else bot_tds[arm]),
            "tds_t1": (champion_tds[arm] if champion_team == 1
                       else bot_tds[arm]),
            "blocks_thrown_t0": 8.0 if champion_team == 0 else 10.0,
            "blocks_thrown_t1": 8.0 if champion_team == 1 else 10.0,
            "reward_clip_episodes": 0,
            "reward_clip_frac": 0,
            "reward_clip_frac_nonzero": 0,
            "reward_clip_excess": 0,
            "reward_nonfinite_episodes": 0,
            "reward_nonfinite_frac": 0,
            "error_episodes": 0,
            "demo_episodes": 0,
            "demo_fallbacks": 0,
        }
        final = dict(panel, _puffer_final_reprint=1)
        path = root / f"{arm}-s{seed}-b{bot_type}-t{bot_team}.log"
        path.write_text(
            transfer.MANIFEST_PREFIX + json.dumps(eval_manifest) + "\n"
            "PufferLib 4.0\nPUFFER_ENV_JSON " + json.dumps(panel) + "\n"
            "PufferLib 4.0\nPUFFER_ENV_JSON " + json.dumps(final) + "\n",
            encoding="utf-8",
        )

    def build_matrix(self, root: Path) -> dict:
        manifest = self.write_manifest(root)
        arms = [manifest["reference_arm"], *manifest["candidate_arms"]]
        for arm in arms:
            for seed in manifest["seeds"]:
                for bot_type in manifest["bot_types"]:
                    for bot_team in manifest["bot_teams"]:
                        self.write_cell(
                            root, manifest, arm, seed, bot_type, bot_team)
        return manifest

    def test_dynamic_matrix_and_fail_closed_recommendation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_matrix(root)
            report = transfer.analyze(root)

        self.assertEqual(report["cell_count"], 32)
        self.assertEqual(report["total_games"], 32_000)
        self.assertEqual(report["recommendation"]["arm"], "possession_only")
        self.assertEqual(
            report["candidate_contrasts"]["gain_only"]["eligible"], True)
        self.assertEqual(
            report["candidate_contrasts"]["possession_only"]["eligible"], True)
        self.assertEqual(
            report["candidate_contrasts"]["neither"]["eligible"], False)

    def test_transfer_manifest_identity_is_not_shadowed_by_orchestration(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_matrix(root)
            report = transfer.analyze(root)
            manifest = root / "TRANSFER_MANIFEST.json"

            self.assertEqual(
                report["transfer_manifest"]["path"], str(manifest.resolve()))
            self.assertEqual(
                report["transfer_manifest"]["sha256"],
                hashlib.sha256(manifest.read_bytes()).hexdigest(),
            )

    def test_completion_evidence_requires_semantic_agreement(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_matrix(root)
            report = transfer.analyze(root)
            complete = self.write_completion(root, report)
            expected = hashlib.sha256(complete.read_bytes()).hexdigest()
            evidence = transfer.validate_completion_evidence(
                complete, expected_complete_sha=expected,
                expected_candidate="possession_only",
            )
            self.assertEqual(evidence["transfer_complete_sha256"], expected)

            report["recommendation"]["arm"] = "gain_only"
            analysis = root / "ANALYSIS.json"
            analysis.write_text(
                json.dumps(report, sort_keys=True) + "\n", encoding="utf-8")
            payload = json.loads(complete.read_text())
            payload["analysis_sha256"] = hashlib.sha256(
                analysis.read_bytes()).hexdigest()
            complete.write_text(json.dumps(payload, sort_keys=True) + "\n")
            expected = hashlib.sha256(complete.read_bytes()).hexdigest()
            with self.assertRaisesRegex(
                transfer.TransferError, "differs from regenerated"
            ):
                transfer.validate_completion_evidence(
                    complete, expected_complete_sha=expected,
                    expected_candidate="possession_only",
                )

    def test_self_consistent_forged_analysis_cannot_replace_cell_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_matrix(root)
            report = transfer.analyze(root)
            report["runs"] = []
            report["cell_count"] = 0
            report["total_games"] = 0
            complete = self.write_completion(root, report)
            expected = hashlib.sha256(complete.read_bytes()).hexdigest()

            with self.assertRaisesRegex(
                transfer.TransferError, "differs from regenerated"
            ):
                transfer.validate_completion_evidence(
                    complete, expected_complete_sha=expected,
                    expected_candidate="possession_only",
                )

    def test_completion_evidence_rehashes_live_cell_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_matrix(root)
            report = transfer.analyze(root)
            complete = self.write_completion(root, report)
            expected = hashlib.sha256(complete.read_bytes()).hexdigest()
            cell = root / report["runs"][0]["log"]
            cell.write_text(cell.read_text() + "tampered\n")

            with self.assertRaisesRegex(
                transfer.TransferError, "differs from regenerated"
            ):
                transfer.validate_completion_evidence(
                    complete, expected_complete_sha=expected,
                    expected_candidate="possession_only",
                )

    def test_manifest_or_cell_drift_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest = self.build_matrix(root)
            path = root / "gain_only-s42-b0-t0.log"
            text = path.read_text().replace(
                manifest["implementation"]["env_config_sha256"],
                digest("drift"),
                1,
            )
            path.write_text(text)
            with self.assertRaisesRegex(
                transfer.TransferError, "env_config_sha256"
            ):
                transfer.analyze(root)

    def test_missing_cell_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_matrix(root)
            (root / "neither-s43-b1-t1.log").unlink()
            with self.assertRaisesRegex(transfer.TransferError, "missing transfer"):
                transfer.analyze(root)

    def test_missing_integrity_counter_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.build_matrix(root)
            path = root / "both-s42-b0-t0.log"
            text = path.read_text().replace(
                '"reward_clip_excess": 0, ', "", 2
            )
            path.write_text(text)
            with self.assertRaisesRegex(
                transfer.TransferError, "missing integrity counters"
            ):
                transfer.analyze(root)


if __name__ == "__main__":
    unittest.main()
