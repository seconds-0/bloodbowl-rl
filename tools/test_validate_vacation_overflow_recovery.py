#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import game_stats
import validate_vacation_overflow_recovery as recovery


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def record(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class VacationOverflowRecoveryValidationTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, dict[str, Path], dict]:
        prior_root = root / "prior"
        recovery_root = root / "recovery"
        recovery_root.mkdir(parents=True)
        queue_dir = prior_root / "runs" / recovery.PRIOR_QUEUE_ID
        screen_dir = queue_dir / "work/final-third"
        checkpoint = (
            prior_root / "vendor/PufferLib/checkpoints/bloodbowl/1784448368863/"
            "0000011999903744.bin"
        )
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"checkpoint fixture")

        plan = write_json(
            queue_dir / "QUEUE_PLAN.json",
            {
                "schema_version": 1,
                "queue_id": recovery.PRIOR_QUEUE_ID,
                "root": str(prior_root.resolve()),
                "jobs": [
                    {"id": "primary-completion-gate", "resume_safe": True},
                    {
                        "id": "final-third-control",
                        "resume_safe": False,
                        "success": {"path": str(screen_dir / "SCREEN_COMPLETE.json")},
                    },
                ],
            },
        )
        plan_sha = record(plan)["sha256"]
        state = write_json(
            queue_dir / "QUEUE_STATE.json",
            {
                "schema_version": 1,
                "queue_id": recovery.PRIOR_QUEUE_ID,
                "plan_sha256": plan_sha,
                "state": "halted",
                "current_job": "final-third-control",
                "message": (
                    "job final-third-control exited 1; later jobs were not run"
                ),
                "jobs": [
                    {
                        "id": "primary-completion-gate",
                        "state": "complete",
                        "exit_code": 0,
                        "success_sha256": recovery.PRIMARY_SUCCESS_SHA256,
                    },
                    {
                        "id": "final-third-control",
                        "state": "failed",
                        "exit_code": 1,
                    },
                ],
            },
        )
        prefix = f"{recovery.PRIOR_QUEUE_ID}-final-third-control"
        manifest = write_json(
            screen_dir / "SCREEN_MANIFEST.json",
            {
                "schema_version": 1,
                "contract": {
                    "screen_profile": "control-final",
                    "prefix": prefix,
                    "out_dir": str(screen_dir.resolve()),
                    "requested_steps": 12_000_000_000,
                    "final_steps": 11_999_903_744,
                    "rollout_quantum": 131_072,
                    "schedule": [
                        {"arm": "both", "index": 1, "seed": 42},
                        {"arm": "both", "index": 2, "seed": 43},
                        {"arm": "both", "index": 3, "seed": 44},
                    ],
                    "settings": {
                        "eval_episodes": "10000",
                        "min_eval_games": "10001",
                    },
                    "warm": {"sha256": recovery.NETBLOCK_SHA256},
                    "rewards": {"both": {"reward_sha256": recovery.R0_REWARD_SHA256}},
                },
            },
        )
        manifest_sha = record(manifest)["sha256"]
        status = write_json(
            screen_dir / "SCREEN_STATUS.json",
            {
                "schema_version": 1,
                "state": "failed",
                "current_index": 1,
                "current_arm": "both",
                "current_seed": 42,
                "completed_arms": 0,
                "exit_code": 1,
                "screen_manifest_sha256": manifest_sha,
                "message": "screen stopped before all arms passed",
            },
        )
        clean = {name: 0.0 for name in recovery.INTEGRITY_KEYS}
        result = write_json(
            screen_dir / f"{prefix}-both-s42.result.json",
            {
                "schema_version": 2,
                "tag": f"{prefix}-both-s42",
                "arm": "both",
                "seed": 42,
                "trainer_complete": True,
                "acceptance_pass": False,
                "acceptance_failures": [
                    {
                        "phase": "eval",
                        "kind": "insufficient_games",
                        "observed": 10000.0,
                        "minimum": 10001,
                    }
                ],
                "screen_manifest_sha256": manifest_sha,
                "reward_sha256": recovery.R0_REWARD_SHA256,
                "checkpoint": str(checkpoint.resolve()),
                "checkpoint_bytes": checkpoint.stat().st_size,
                "checkpoint_sha256": record(checkpoint)["sha256"],
                "log": str(screen_dir / f"{prefix}-both-s42.log"),
                "log_sha256": "a" * 64,
                "train_metrics": {"n": 100.0, **clean},
                "eval_metrics": {"n": 10000.0, **clean},
            },
        )
        launcher = Path(__file__).resolve().parents[1] / "tools/run_reward_screen.sh"
        helper = Path(game_stats.__file__).resolve()
        paths = {
            "plan": plan,
            "state": state,
            "manifest": manifest,
            "status": status,
            "result": result,
            "checkpoint": checkpoint,
            "launcher": launcher,
            "game_stats": helper,
            "screen_dir": screen_dir,
            "recovery_root": recovery_root,
            "prior_root": prior_root,
        }
        reviewed = {
            name: {
                "bytes": record(paths[name])["bytes"],
                "sha256": record(paths[name])["sha256"],
            }
            for name in recovery.PRIOR_FILE_KEYS
        }
        config = {
            "schema_version": 1,
            "recovery_root": str(recovery_root.resolve()),
            "prior_queue_id": recovery.PRIOR_QUEUE_ID,
            "prior_plan": record(plan),
            "prior_state": record(state),
            "prior_screen_manifest": record(manifest),
            "prior_screen_status": record(status),
            "prior_result": record(result),
            "prior_checkpoint": record(checkpoint),
            "corrected_launcher": record(launcher),
            "corrected_game_stats": record(helper),
            "warning": recovery.WARNING,
        }
        config_path = write_json(recovery_root / "RECOVERY_PREFLIGHT.json", config)
        return config_path, paths, reviewed

    def rebind(
        self,
        config_path: Path,
        config_key: str,
        reviewed: dict,
        reviewed_key: str,
        path: Path,
    ) -> None:
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config[config_key] = record(path)
        write_json(config_path, config)
        reviewed[reviewed_key] = {
            "bytes": path.stat().st_size,
            "sha256": record(path)["sha256"],
        }

    def test_exact_terminal_evidence_authorizes_only_fresh_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, paths, reviewed = self.make_fixture(Path(tmp))
            with (
                mock.patch.object(recovery, "REVIEWED_PRIOR_ROOT", paths["prior_root"]),
                mock.patch.object(recovery, "REVIEWED_PRIOR_FILES", reviewed),
            ):
                config = recovery.validate_config(config_path)
                report = recovery.recovery_report(config)
            self.assertEqual(report["prior_queue_id"], recovery.PRIOR_QUEUE_ID)
            self.assertEqual(report["observed_eval_games"], 10000)
            self.assertEqual(report["old_minimum_eval_games"], 10001)
            self.assertEqual(report["new_minimum_eval_games"], 10000)
            self.assertEqual(report["unstarted_seeds"], [43, 44])
            self.assertEqual(report["warning"], recovery.WARNING)

    def test_rejects_any_other_acceptance_failure_or_nonzero_integrity(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, paths, reviewed = self.make_fixture(Path(tmp))
            result = json.loads(paths["result"].read_text(encoding="utf-8"))
            result["acceptance_failures"].append(
                {"phase": "eval", "kind": "integrity_nonzero"}
            )
            write_json(paths["result"], result)
            self.rebind(
                config_path,
                "prior_result",
                reviewed,
                "result",
                paths["result"],
            )
            with (
                mock.patch.object(recovery, "REVIEWED_PRIOR_ROOT", paths["prior_root"]),
                mock.patch.object(recovery, "REVIEWED_PRIOR_FILES", reviewed),
            ):
                config = recovery.validate_config(config_path)
                with self.assertRaisesRegex(
                    recovery.RecoveryEvidenceError, "only terminal failure"
                ):
                    recovery.recovery_report(config)

            result["acceptance_failures"] = [recovery.EXPECTED_FAILURE]
            result["train_metrics"]["error_episodes"] = 1.0
            write_json(paths["result"], result)
            self.rebind(
                config_path,
                "prior_result",
                reviewed,
                "result",
                paths["result"],
            )
            with (
                mock.patch.object(recovery, "REVIEWED_PRIOR_ROOT", paths["prior_root"]),
                mock.patch.object(recovery, "REVIEWED_PRIOR_FILES", reviewed),
            ):
                config = recovery.validate_config(config_path)
                with self.assertRaisesRegex(
                    recovery.RecoveryEvidenceError, "integrity metric"
                ):
                    recovery.recovery_report(config)

    def test_rejects_completion_or_any_seed_43_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, paths, reviewed = self.make_fixture(Path(tmp))
            with (
                mock.patch.object(recovery, "REVIEWED_PRIOR_ROOT", paths["prior_root"]),
                mock.patch.object(recovery, "REVIEWED_PRIOR_FILES", reviewed),
            ):
                config = recovery.validate_config(config_path)
                write_json(paths["screen_dir"] / "SCREEN_COMPLETE.json", {})
                with self.assertRaisesRegex(
                    recovery.RecoveryEvidenceError, "completion proof exists"
                ):
                    recovery.recovery_report(config)
                (paths["screen_dir"] / "SCREEN_COMPLETE.json").unlink()
                prefix = f"{recovery.PRIOR_QUEUE_ID}-final-third-control"
                write_json(paths["screen_dir"] / f"{prefix}-both-s43.result.json", {})
                with self.assertRaisesRegex(
                    recovery.RecoveryEvidenceError, "seed 43 result exists"
                ):
                    recovery.recovery_report(config)

    def test_rejects_nonterminal_state_or_changed_old_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, paths, reviewed = self.make_fixture(Path(tmp))
            state = json.loads(paths["state"].read_text(encoding="utf-8"))
            state["state"] = "complete"
            write_json(paths["state"], state)
            self.rebind(config_path, "prior_state", reviewed, "state", paths["state"])
            with (
                mock.patch.object(recovery, "REVIEWED_PRIOR_ROOT", paths["prior_root"]),
                mock.patch.object(recovery, "REVIEWED_PRIOR_FILES", reviewed),
            ):
                config = recovery.validate_config(config_path)
                with self.assertRaisesRegex(
                    recovery.RecoveryEvidenceError, "not the exact terminal halt"
                ):
                    recovery.recovery_report(config)

    def test_write_and_validate_proof_recompute_live_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            config_path, paths, reviewed = self.make_fixture(Path(tmp))
            proof = paths["recovery_root"] / "proof/RECOVERY_AUTHORIZED.json"
            with (
                mock.patch.object(recovery, "REVIEWED_PRIOR_ROOT", paths["prior_root"]),
                mock.patch.object(recovery, "REVIEWED_PRIOR_FILES", reviewed),
            ):
                self.assertEqual(
                    recovery.main(
                        [
                            "--config",
                            str(config_path),
                            "--write-proof",
                            str(proof),
                        ]
                    ),
                    0,
                )
                self.assertEqual(
                    recovery.main(
                        [
                            "--config",
                            str(config_path),
                            "--validate-proof",
                            str(proof),
                        ]
                    ),
                    0,
                )
                payload = json.loads(proof.read_text(encoding="utf-8"))
                payload["observed_eval_games"] = 9999
                write_json(proof, payload)
                self.assertEqual(
                    recovery.main(
                        [
                            "--config",
                            str(config_path),
                            "--validate-proof",
                            str(proof),
                        ]
                    ),
                    2,
                )


if __name__ == "__main__":
    unittest.main()
