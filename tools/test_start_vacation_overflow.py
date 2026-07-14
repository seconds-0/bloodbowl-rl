#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import start_vacation_overflow as starter
import validate_primary_queue_completion


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value) + "\n", encoding="utf-8")


def record(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class VacationOverflowStarterTests(unittest.TestCase):
    def basic_config(self, root: Path) -> dict:
        plan = root / "runs/overflow/QUEUE_PLAN.json"
        write_json(plan, {"plan": True})
        completion = root / "runs/overflow/configs/completion.json"
        write_json(completion, {"completion": True})
        systemctl = root / "systemctl"
        systemctl.write_text("binary", encoding="utf-8")
        return {
            "primary_queue_id": "primary",
            "overflow_queue_id": "overflow",
            "overflow_state_path": plan.parent / "QUEUE_STATE.json",
            "overflow_plan_path": plan,
            "completion_config_path": completion,
            "systemctl_path": systemctl,
            "plan": {"pinned_files": []},
            "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        }

    def test_existing_state_is_never_relaunched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config = self.basic_config(root)
            write_json(
                config["overflow_state_path"],
                {
                    "queue_id": "overflow",
                    "plan_sha256": config["plan_sha256"],
                    "state": "halted",
                },
            )
            with mock.patch.object(starter, "service_state") as service:
                message = starter.start_if_ready(config)
            self.assertIn("state=halted", message)
            service.assert_not_called()

    def test_missing_systemd_unit_is_not_treated_as_inactive(self):
        result = mock.Mock(
            returncode=4,
            stdout="inactive\n",
            stderr="Unit example.service could not be found.\n",
        )
        with mock.patch.object(starter.subprocess, "run", return_value=result):
            with self.assertRaisesRegex(starter.StartError, "cannot classify"):
                starter.service_state(Path("/usr/bin/systemctl"), "example.service")

    def test_waits_while_primary_active_and_refuses_failed_service(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.basic_config(Path(tmp).resolve())
            with mock.patch.object(
                starter, "service_state", side_effect=["inactive", "active"]
            ):
                self.assertIn("waiting", starter.start_if_ready(config))
            with mock.patch.object(starter, "service_state", return_value="failed"):
                with self.assertRaisesRegex(starter.StartError, "failed"):
                    starter.start_if_ready(config)

    def test_completion_or_pin_failure_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.basic_config(Path(tmp).resolve())
            with (
                mock.patch.object(
                    starter, "service_state", side_effect=["inactive", "inactive"]
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "validate_config",
                    return_value={},
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "completion_report",
                    side_effect=validate_primary_queue_completion.CompletionError(
                        "drift"
                    ),
                ),
            ):
                with self.assertRaisesRegex(
                    validate_primary_queue_completion.CompletionError, "drift"
                ):
                    starter.start_if_ready(config)
            with (
                mock.patch.object(
                    starter,
                    "service_state",
                    side_effect=["inactive", "inactive"],
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "validate_config",
                    return_value={},
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "completion_report",
                    return_value={},
                ),
                mock.patch.object(
                    starter.experiment_queue,
                    "pinned_files_error",
                    return_value="pin drift",
                ),
            ):
                with self.assertRaisesRegex(starter.StartError, "pin drift"):
                    starter.start_if_ready(config)

    def test_gpu_race_waits_and_success_starts_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.basic_config(Path(tmp).resolve())
            completion_config = {"nvidia_smi_path": Path("/nvidia-smi")}
            with (
                mock.patch.object(
                    validate_primary_queue_completion,
                    "validate_config",
                    return_value=completion_config,
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "completion_report",
                    return_value={},
                ),
                mock.patch.object(
                    starter.experiment_queue, "pinned_files_error", return_value=None
                ),
                mock.patch.object(
                    starter,
                    "service_state",
                    side_effect=["inactive", "inactive", "inactive", "inactive"],
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "gpu_compute_pids",
                    return_value=[123],
                ),
            ):
                self.assertIn("GPU became busy", starter.start_if_ready(config))

            start_result = mock.Mock(returncode=0, stdout="", stderr="")
            with (
                mock.patch.object(
                    validate_primary_queue_completion,
                    "validate_config",
                    return_value=completion_config,
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "completion_report",
                    return_value={},
                ),
                mock.patch.object(
                    starter.experiment_queue, "pinned_files_error", return_value=None
                ),
                mock.patch.object(
                    starter,
                    "service_state",
                    side_effect=[
                        "inactive",
                        "inactive",
                        "inactive",
                        "inactive",
                        "active",
                    ],
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "gpu_compute_pids",
                    return_value=[],
                ),
                mock.patch.object(
                    starter.subprocess, "run", return_value=start_result
                ) as run,
            ):
                message = starter.start_if_ready(config)
            self.assertIn("started experiment-queue@overflow.service", message)
            run.assert_called_once()

    def test_plan_drift_during_preflight_cannot_start(self):
        with tempfile.TemporaryDirectory() as tmp:
            config = self.basic_config(Path(tmp).resolve())
            completion_config = {"nvidia_smi_path": Path("/nvidia-smi")}
            with (
                mock.patch.object(
                    validate_primary_queue_completion,
                    "validate_config",
                    return_value=completion_config,
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "completion_report",
                    return_value={},
                ),
                mock.patch.object(
                    starter.experiment_queue, "pinned_files_error", return_value=None
                ),
                mock.patch.object(
                    starter,
                    "service_state",
                    side_effect=["inactive", "inactive", "inactive", "inactive"],
                ),
                mock.patch.object(
                    validate_primary_queue_completion,
                    "gpu_compute_pids",
                    return_value=[],
                ),
                mock.patch.object(
                    starter.experiment_queue, "sha256", return_value="0" * 64
                ),
                mock.patch.object(starter.subprocess, "run") as run,
            ):
                with self.assertRaisesRegex(starter.StartError, "plan changed"):
                    starter.start_if_ready(config)
            run.assert_not_called()

    def test_validate_config_is_closed_and_hash_binds_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            plan = root / "runs/overflow/QUEUE_PLAN.json"
            completion = root / "runs/overflow/configs/completion.json"
            systemctl = root / "systemctl"
            write_json(plan, {"plan": True})
            write_json(completion, {"completion": True})
            systemctl.write_text("binary", encoding="utf-8")
            config_path = root / "runs/overflow/OVERFLOW_WATCH.json"
            payload = {
                "schema_version": 1,
                "root": str(root),
                "primary_queue_id": "primary",
                "overflow_queue_id": "overflow",
                "completion_config": record(completion),
                "overflow_plan": record(plan),
                "overflow_state": str(plan.parent / "QUEUE_STATE.json"),
                "systemctl": record(systemctl),
                "starter": record(Path(starter.__file__).resolve()),
            }
            payload["config_sha256"] = starter.config_sha256(payload)
            write_json(config_path, payload)
            with mock.patch.object(
                starter.experiment_queue,
                "validate_plan",
                return_value=({"queue_id": "overflow"}, root, "a" * 64),
            ):
                validated = starter.validate_config(config_path)
            self.assertEqual(validated["overflow_queue_id"], "overflow")
            payload["unknown"] = True
            write_json(config_path, payload)
            with self.assertRaisesRegex(starter.StartError, "fields differ"):
                starter.validate_config(config_path)
            payload.pop("unknown")
            payload["primary_queue_id"] = "changed"
            write_json(config_path, payload)
            with self.assertRaisesRegex(starter.StartError, "identity drifted"):
                starter.validate_config(config_path)


if __name__ == "__main__":
    unittest.main()
