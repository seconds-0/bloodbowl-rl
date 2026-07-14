#!/usr/bin/env python3

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import freeze_vacation_overflow as overflow
import freeze_vacation_queue


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def write_file(path: Path, value: str = "fixture\n") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8")
    return path


class VacationOverflowFreezerTests(unittest.TestCase):
    def test_primary_contract_requires_exact_route_jobs_pins_and_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            pool = root / "pool"
            pool.mkdir()
            write_json(pool / "league_seeds.json", {"seeds": []})
            main_warm = write_file(root / "main.bin", "main")
            primary_dir = root / "runs" / overflow.REVIEWED_PRIMARY_QUEUE_ID
            plan_path = primary_dir / "QUEUE_PLAN.json"
            write_json(plan_path, {"plan": True})
            spec_path = primary_dir / "VACATION_SPEC.json"
            auth_path = primary_dir / "configs/BASELINE_AUTHORIZATION.json"
            main_config = primary_dir / "configs/FINAL_MAIN_SCREEN_CONFIG.json"
            second_config = primary_dir / "configs/FINAL_SECOND_SCREEN_CONFIG.json"
            write_json(
                spec_path,
                {
                    "schema_version": 2,
                    "queue_id": overflow.REVIEWED_PRIMARY_QUEUE_ID,
                    "route": overflow.PRIMARY_ROUTE,
                    "root": str(root),
                    "candidate_arm": "neither",
                    "final_steps": 12_000_000_000,
                    "pool": str(pool),
                    "main_warm": str(main_warm),
                    "anchor_config": None,
                    "main_learned_complete": None,
                },
            )
            authorization = {
                "schema_version": 1,
                "route": overflow.PRIMARY_ROUTE,
                "candidate_arm": "neither",
                "rejection": {"failures": ["mean_perf_delta"]},
                "warning": (
                    "This proof authorizes only R0 baseline characterization. "
                    "It does not select or promote a reward candidate."
                ),
            }
            write_json(auth_path, authorization)
            write_json(main_config, {"config": "main"})
            write_json(second_config, {"config": "second"})
            pins = [
                freeze_vacation_queue.pin_file(path, "primary fixture")
                for path in (spec_path, auth_path, main_config, second_config)
            ]

            def command(config: Path) -> list[dict[str, str]]:
                return [
                    {"kind": "pinned", "path": str(root / "python")},
                    {
                        "kind": "pinned",
                        "path": str(root / "tools/run_frozen_reward_screen.py"),
                    },
                    {"kind": "literal", "value": "--config"},
                    {"kind": "pinned", "path": str(config)},
                ]

            plan = {
                "queue_id": overflow.REVIEWED_PRIMARY_QUEUE_ID,
                "pinned_files": pins,
                "jobs": [
                    {"id": "final-main-control", "command": command(main_config)},
                    {"id": "final-second-control", "command": command(second_config)},
                ],
            }
            pool_record = freeze_vacation_queue.tree_record(pool)
            configs = [
                {
                    "profile": "control-final",
                    "candidate_arm": "both",
                    "steps": 12_000_000_000,
                    "candidate_transfer": None,
                    "require_gate": False,
                    "pool": pool_record,
                    "warm": {
                        "sha256": hashlib.sha256(main_warm.read_bytes()).hexdigest()
                    },
                },
                {
                    "profile": "control-final",
                    "candidate_arm": "both",
                    "steps": 12_000_000_000,
                    "candidate_transfer": None,
                    "require_gate": False,
                    "pool": pool_record,
                    "warm": {
                        "sha256": freeze_vacation_queue.REVIEWED_SECOND_ANCESTRY[
                            "sha256"
                        ]
                    },
                },
            ]
            with (
                mock.patch.object(
                    overflow.experiment_queue,
                    "validate_plan",
                    return_value=(
                        plan,
                        root,
                        overflow.REVIEWED_PRIMARY_PLAN_SHA256,
                    ),
                ),
                mock.patch.object(
                    overflow.experiment_queue, "pinned_files_error", return_value=None
                ),
                mock.patch.object(
                    overflow.run_frozen_reward_screen,
                    "validate_config",
                    side_effect=configs,
                ),
            ):
                validated_plan, validated_auth, plan_sha = (
                    overflow.validate_primary_contract(plan_path, root, pool)
                )
                self.assertIs(validated_plan, plan)
                self.assertEqual(validated_auth, authorization)
                self.assertEqual(plan_sha, overflow.REVIEWED_PRIMARY_PLAN_SHA256)
                authorization["rejection"]["failures"] = []
                write_json(auth_path, authorization)
                with self.assertRaisesRegex(
                    overflow.OverflowFreezeError, "authorization is malformed"
                ):
                    overflow.validate_primary_contract(plan_path, root, pool)

    def make_spec_fixture(self, root: Path) -> tuple[Path, dict]:
        primary_plan = write_file(root / "runs/primary/QUEUE_PLAN.json", "{}\n")
        pool = root / "pool"
        pool.mkdir()
        warm = pool / "netblock.bin"
        warm.write_bytes(b"netblock")
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
        nvidia = write_file(root / "nvidia-smi", "#!/bin/sh\nexit 0\n")
        systemctl = write_file(root / "systemctl", "#!/bin/sh\nexit 0\n")
        nvidia.chmod(0o755)
        systemctl.chmod(0o755)
        spec = {
            "schema_version": 1,
            "queue_id": "vacation-overflow-test",
            "root": str(root),
            "primary_plan": str(primary_plan),
            "overflow_warm": str(warm),
            "pool": str(pool),
            "nvidia_smi": str(nvidia),
            "systemctl": str(systemctl),
            "final_steps": 12_000_000_000,
            "min_free_bytes": 1,
            "min_free_inodes": 1,
            "max_gpu_temperature_c": 88,
        }
        spec_path = root / "OVERFLOW_SPEC.json"
        write_json(spec_path, spec)
        return spec_path, spec

    def test_validate_spec_accepts_only_reviewed_netblock_and_primary(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            spec_path, spec = self.make_spec_fixture(root)
            warm = Path(spec["overflow_warm"])
            plan = {"pinned_files": []}
            plan_sha = "a" * 64
            with (
                mock.patch.object(
                    overflow,
                    "validate_primary_contract",
                    return_value=(plan, {"route": overflow.PRIMARY_ROUTE}, plan_sha),
                ),
                mock.patch.dict(
                    overflow.REVIEWED_OVERFLOW_ANCESTRY,
                    {"sha256": hashlib.sha256(warm.read_bytes()).hexdigest()},
                ),
            ):
                validated = overflow.validate_spec(spec_path)
            self.assertEqual(validated["primary_plan_data"], plan)
            self.assertEqual(validated["overflow_warm_path"], warm)
            self.assertEqual(validated["primary_plan_sha256"], plan_sha)

    def test_validate_spec_rejects_unknown_fields_budget_and_wrong_warm(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            spec_path, spec = self.make_spec_fixture(root)
            spec["unknown"] = True
            write_json(spec_path, spec)
            with self.assertRaisesRegex(overflow.OverflowFreezeError, "fields differ"):
                overflow.validate_spec(spec_path)
            spec.pop("unknown")
            spec["final_steps"] = 1
            write_json(spec_path, spec)
            with self.assertRaisesRegex(overflow.OverflowFreezeError, "12B"):
                overflow.validate_spec(spec_path)
            spec["final_steps"] = 12_000_000_000
            write_json(spec_path, spec)
            with mock.patch.object(
                overflow,
                "validate_primary_contract",
                return_value=({"pinned_files": []}, {}, "a" * 64),
            ):
                with self.assertRaisesRegex(
                    overflow.OverflowFreezeError, "reviewed netblock"
                ):
                    overflow.validate_spec(spec_path)

    def make_freeze_fixture(self, root: Path) -> dict:
        tools = root / "tools"
        files = {
            name: write_file(tools / name)
            for name in (
                "run_frozen_reward_screen.py",
                "validate_vacation_artifact.py",
                "validate_primary_queue_completion.py",
                "start_vacation_overflow.py",
                "run_reward_screen.sh",
                "analyze_reward_screen.py",
                "analyze_reward_candidate_transfer.py",
            )
        }
        python_link = root / "vendor/PufferLib/.venv/bin/python"
        python_link.parent.mkdir(parents=True)
        python_link.symlink_to(Path(sys.executable).resolve())
        pool = root / "pool"
        pool.mkdir()
        warm = pool / "netblock.bin"
        warm.write_bytes(b"netblock")
        write_json(pool / "league_seeds.json", {"seeds": []})
        spec_path = root / "OVERFLOW_SPEC.json"
        write_json(spec_path, {"schema_version": 1})
        primary_plan = root / "runs/primary/QUEUE_PLAN.json"
        write_json(primary_plan, {"primary": True})
        nvidia = write_file(root / "nvidia-smi")
        systemctl = write_file(root / "systemctl")
        primary_pins = [
            freeze_vacation_queue.pin_file(
                Path(sys.executable).resolve(), "test python"
            ),
            freeze_vacation_queue.pin_tree(pool, "test pool"),
        ]
        for file_path in (
            files["run_frozen_reward_screen.py"],
            files["validate_vacation_artifact.py"],
        ):
            primary_pins.append(
                freeze_vacation_queue.pin_file(file_path, "test runtime")
            )
        queue_dir = root / "runs/vacation-overflow-test"
        return {
            "schema_version": 1,
            "queue_id": "vacation-overflow-test",
            "root": str(root),
            "root_path": root,
            "primary_plan": str(primary_plan),
            "primary_plan_path": primary_plan,
            "primary_state_path": primary_plan.parent / "QUEUE_STATE.json",
            "primary_plan_data": {"pinned_files": primary_pins},
            "primary_plan_sha256": hashlib.sha256(
                primary_plan.read_bytes()
            ).hexdigest(),
            "primary_authorization": {"route": overflow.PRIMARY_ROUTE},
            "overflow_warm": str(warm),
            "overflow_warm_path": warm,
            "pool": str(pool),
            "pool_path": pool,
            "nvidia_smi": str(nvidia),
            "nvidia_smi_path": nvidia,
            "systemctl": str(systemctl),
            "systemctl_path": systemctl,
            "final_steps": 12_000_000_000,
            "min_free_bytes": 1,
            "min_free_inodes": 1,
            "max_gpu_temperature_c": 88,
            "spec_path": spec_path,
            "queue_dir": queue_dir,
        }

    def test_freeze_emits_completion_gate_then_one_control_screen(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            spec = self.make_freeze_fixture(root)
            plan_path = overflow.freeze(spec)
            plan = json.loads(plan_path.read_text())
            self.assertEqual(
                [job["id"] for job in plan["jobs"]],
                ["primary-completion-gate", "final-third-control"],
            )
            self.assertTrue(plan["jobs"][0]["resume_safe"])
            self.assertFalse(plan["jobs"][1]["resume_safe"])
            self.assertEqual(plan["jobs"][1]["max_runtime_seconds"], 72 * 3600)
            config = json.loads(
                (
                    spec["queue_dir"] / "configs/FINAL_THIRD_SCREEN_CONFIG.json"
                ).read_text()
            )
            self.assertEqual(config["profile"], "control-final")
            self.assertEqual(config["candidate_arm"], "both")
            self.assertEqual(config["steps"], 12_000_000_000)
            self.assertEqual(
                config["warm"]["sha256"],
                hashlib.sha256(spec["overflow_warm_path"].read_bytes()).hexdigest(),
            )
            self.assertIsNone(config["candidate_transfer"])
            self.assertFalse(config["require_gate"])
            watch = json.loads((spec["queue_dir"] / "OVERFLOW_WATCH.json").read_text())
            self.assertEqual(watch["overflow_queue_id"], spec["queue_id"])
            self.assertEqual(
                watch["overflow_plan"]["sha256"],
                hashlib.sha256(plan_path.read_bytes()).hexdigest(),
            )

    def test_freeze_refuses_preexisting_success_or_plan_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            spec = self.make_freeze_fixture(root)
            success = spec["queue_dir"] / "work/final-third/SCREEN_COMPLETE.json"
            write_json(success, {})
            with self.assertRaisesRegex(
                overflow.OverflowFreezeError, "preexisting overflow success"
            ):
                overflow.freeze(spec)

    def test_tracked_timer_is_bounded_persistent_and_uses_frozen_config(self):
        root = Path(__file__).resolve().parents[1]
        service = (
            root / "training/systemd/vacation-overflow-watch@.service"
        ).read_text(encoding="utf-8")
        timer = (root / "training/systemd/vacation-overflow-watch@.timer").read_text(
            encoding="utf-8"
        )
        self.assertIn("Type=oneshot", service)
        self.assertIn("TimeoutStartSec=15min", service)
        self.assertIn("tools/start_vacation_overflow.py", service)
        self.assertIn("runs/%i/OVERFLOW_WATCH.json", service)
        self.assertNotIn("Restart=", service)
        self.assertIn("OnBootSec=2min", timer)
        self.assertIn("OnUnitActiveSec=10min", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("vacation-overflow-watch@%i.service", timer)


if __name__ == "__main__":
    unittest.main()
