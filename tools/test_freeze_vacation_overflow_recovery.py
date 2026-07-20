#!/usr/bin/env python3

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import freeze_vacation_overflow_recovery as freezer


def write_json(path: Path, value: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return path


def write_file(path: Path, value: bytes = b"fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(value)
    return path


class VacationOverflowRecoveryFreezerTests(unittest.TestCase):
    def make_fixture(self, base: Path) -> tuple[Path, dict]:
        root = base / "recovery"
        prior_root = base / "prior"
        root.mkdir()
        root = root.resolve()
        prior_root = prior_root.resolve()
        queue_id = freezer.RECOVERY_QUEUE_ID
        prior = {
            key: write_file(prior_root / f"{key}.json")
            for key in ("plan", "state", "manifest", "status", "result")
        }
        prior["checkpoint"] = write_file(prior_root / "checkpoint.bin")
        pool = root / "pool"
        pool.mkdir()
        warm = write_file(pool / "netblock.bin", b"netblock warm")
        write_json(
            pool / "league_seeds.json",
            {
                "seeds": [
                    {
                        "bank": 2,
                        "name": "netblock",
                        "file": warm.name,
                        "bytes": warm.stat().st_size,
                        "sha256": hashlib.sha256(warm.read_bytes()).hexdigest(),
                    }
                ]
            },
        )
        nvidia = write_file(root / "nvidia-smi", b"#!/bin/sh\nexit 0\n")
        nvidia.chmod(0o755)
        python_link = root / "vendor/PufferLib/.venv/bin/python"
        python_link.parent.mkdir(parents=True)
        python_link.symlink_to(Path(sys.executable).resolve())
        sources = {
            name: write_file(root / "tools" / name)
            for name in (
                "experiment_queue.py",
                "run_frozen_reward_screen.py",
                "run_reward_screen.sh",
                "analyze_reward_screen.py",
                "analyze_reward_candidate_transfer.py",
                "validate_vacation_artifact.py",
                "validate_vacation_overflow_recovery.py",
                "game_stats.py",
            )
        }
        patches = [
            write_file(root / "training" / name) for name in freezer.PUFFER_PATCHES
        ]
        spec = {
            "schema_version": 1,
            "queue_id": queue_id,
            "root": str(root.resolve()),
            "prior_plan": str(prior["plan"].resolve()),
            "prior_state": str(prior["state"].resolve()),
            "prior_screen_manifest": str(prior["manifest"].resolve()),
            "prior_screen_status": str(prior["status"].resolve()),
            "prior_result": str(prior["result"].resolve()),
            "prior_checkpoint": str(prior["checkpoint"].resolve()),
            "recovery_warm": str(warm.resolve()),
            "pool": str(pool.resolve()),
            "nvidia_smi": str(nvidia.resolve()),
            "final_steps": 12_000_000_000,
            "min_free_bytes": 1,
            "min_free_inodes": 1,
            "max_gpu_temperature_c": 88,
        }
        spec_path = write_json(root / "RECOVERY_SPEC.json", spec)
        validated = {
            **spec,
            "spec_path": spec_path,
            "root_path": root,
            "queue_dir": root / "runs" / queue_id,
            "prior_paths": prior,
            "recovery_warm_path": warm,
            "pool_path": pool,
            "nvidia_smi_path": nvidia,
        }
        validated["test_sources"] = list(sources.values()) + patches + [
            Path(sys.executable).resolve(),
            Path("/bin/bash"),
            spec_path,
            warm,
            nvidia,
            *prior.values(),
        ]
        return spec_path, validated

    def test_validate_spec_requires_isolated_root_exact_queue_and_terminal_evidence(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            spec_path, fixture = self.make_fixture(Path(tmp))
            warm_sha = hashlib.sha256(
                fixture["recovery_warm_path"].read_bytes()
            ).hexdigest()
            with (
                mock.patch.object(freezer, "REVIEWED_WARM_SHA256", warm_sha),
                mock.patch.object(
                    freezer, "REVIEWED_RECOVERY_ROOT", fixture["root_path"]
                ),
                mock.patch.object(
                    freezer,
                    "REVIEWED_WARM_BYTES",
                    fixture["recovery_warm_path"].stat().st_size,
                ),
                mock.patch.object(
                    freezer.recovery_validator, "validate_config", return_value={}
                ) as validate_config,
                mock.patch.object(
                    freezer.recovery_validator,
                    "recovery_report",
                    return_value={
                        "result_reuse_authorized": False,
                        "in_place_restart_authorized": False,
                        "reward_promotion_authorized": False,
                    },
                ) as recovery_report,
            ):
                validated = freezer.validate_spec(spec_path)
            self.assertEqual(validated["root_path"], fixture["root_path"])
            self.assertEqual(validated["prior_paths"], fixture["prior_paths"])
            validate_config.assert_called_once()
            recovery_report.assert_called_once()

            spec = json.loads(spec_path.read_text(encoding="utf-8"))
            spec["queue_id"] = "another-queue"
            write_json(spec_path, spec)
            with self.assertRaisesRegex(freezer.RecoveryFreezeError, "queue ID"):
                freezer.validate_spec(spec_path)

            spec["queue_id"] = freezer.RECOVERY_QUEUE_ID
            write_json(spec_path, spec)
            with self.assertRaisesRegex(
                freezer.RecoveryFreezeError, "reviewed exact root"
            ):
                freezer.validate_spec(spec_path)

    def test_freeze_emits_preflight_then_full_three_seed_control_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, spec = self.make_fixture(Path(tmp))
            with (
                mock.patch.object(
                    freezer,
                    "runtime_source_paths",
                    return_value=spec["test_sources"],
                ),
                mock.patch.object(
                    freezer,
                    "runtime_tree_sources",
                    return_value=[(spec["pool_path"], "test pool")],
                ),
            ):
                plan_path = freezer.freeze(spec)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            self.assertEqual(plan["root"], str(spec["root_path"]))
            self.assertEqual(
                [job["id"] for job in plan["jobs"]],
                ["terminal-evidence-preflight", "full-control-rerun"],
            )
            self.assertTrue(plan["jobs"][0]["resume_safe"])
            self.assertFalse(plan["jobs"][1]["resume_safe"])
            self.assertEqual(plan["jobs"][1]["max_runtime_seconds"], 72 * 3600)
            self.assertEqual(plan["jobs"][1]["progress"]["max_stale_seconds"], 600)
            screen_config = json.loads(
                (
                    spec["queue_dir"] / "configs/FULL_CONTROL_SCREEN_CONFIG.json"
                ).read_text(encoding="utf-8")
            )
            self.assertEqual(screen_config["profile"], "control-final")
            self.assertEqual(screen_config["candidate_arm"], "both")
            self.assertEqual(screen_config["steps"], 12_000_000_000)
            self.assertIsNone(screen_config["candidate_transfer"])
            self.assertFalse(screen_config["require_gate"])
            prior_paths = {str(path.resolve()) for path in spec["prior_paths"].values()}
            pinned = {pin["path"] for pin in plan["pinned_files"]}
            self.assertLessEqual(prior_paths, pinned)
            patch_paths = {
                str((spec["root_path"] / "training" / name).resolve())
                for name in freezer.PUFFER_PATCHES
            }
            self.assertLessEqual(patch_paths, pinned)
            mutable = {
                value for job in plan["jobs"] for value in job.get("mutable_paths", [])
            }
            self.assertTrue(prior_paths.isdisjoint(mutable))

    def test_freeze_refuses_existing_state_success_or_plan_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, spec = self.make_fixture(Path(tmp))
            state = write_json(spec["queue_dir"] / "QUEUE_STATE.json", {})
            with self.assertRaisesRegex(freezer.RecoveryFreezeError, "existing state"):
                freezer.freeze(spec)
            state.unlink()
            success = write_json(
                spec["queue_dir"] / "work/full-control/SCREEN_COMPLETE.json", {}
            )
            with self.assertRaisesRegex(
                freezer.RecoveryFreezeError, "preexisting recovery artifact"
            ):
                freezer.freeze(spec)
            success.unlink()

    def test_recovery_service_is_bound_only_to_the_isolated_root(self):
        root = Path(__file__).resolve().parents[1]
        service = (
            root / "training/systemd/experiment-recovery-queue@.service"
        ).read_text(encoding="utf-8")
        self.assertIn("WorkingDirectory=%h/bloodbowl-rl-recovery-20260719", service)
        self.assertIn(
            "%h/bloodbowl-rl-recovery-20260719/tools/experiment_queue.py",
            service,
        )
        self.assertIn(
            "%h/bloodbowl-rl-recovery-20260719/runs/%i/QUEUE_PLAN.json",
            service,
        )
        self.assertNotIn("%h/bloodbowl-rl-audit", service)
        self.assertIn("Restart=on-failure", service)
        self.assertIn("KillMode=control-group", service)


if __name__ == "__main__":
    unittest.main()
