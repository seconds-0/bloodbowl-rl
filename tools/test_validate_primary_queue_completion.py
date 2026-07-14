#!/usr/bin/env python3

import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import experiment_queue
import validate_primary_queue_completion as validator


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def file_record(path: Path) -> dict:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


class PrimaryQueueCompletionTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        python = Path(sys.executable).resolve()
        runner = root / "runner.py"
        check = root / "check.py"
        runner.write_text("raise SystemExit(0)\n", encoding="utf-8")
        check.write_text(
            "import pathlib,sys\n"
            "raise SystemExit(0 if pathlib.Path(sys.argv[1]).is_file() else 2)\n",
            encoding="utf-8",
        )
        pins = []
        for path in (python, runner, check):
            pins.append(
                {
                    "kind": "file",
                    "path": str(path),
                    "bytes": path.stat().st_size,
                    "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                    "role": "test input",
                }
            )
        jobs = []
        state_jobs = []
        for job_id in validator.PRIMARY_JOB_IDS:
            success = root / f"{job_id}.done"
            success.write_text(job_id, encoding="utf-8")
            job = {
                "id": job_id,
                "command": [
                    {"kind": "pinned", "path": str(python)},
                    {"kind": "pinned", "path": str(runner)},
                ],
                "cwd": str(root),
                "log": str(root / f"{job_id}.log"),
                "success": {
                    "path": str(success),
                    "validator": [
                        {"kind": "pinned", "path": str(python)},
                        {"kind": "pinned", "path": str(check)},
                        {"kind": "mutable", "path": str(success)},
                    ],
                    "validator_timeout_seconds": 10,
                },
                "env": {},
                "resume_safe": False,
                "max_runtime_seconds": 60,
                "progress_not_required_reason": "bounded synthetic fixture",
                "pinned_inputs": [str(python), str(runner), str(check)],
                "mutable_paths": [str(success)],
            }
            jobs.append(job)
            state_jobs.append(
                {
                    "id": job_id,
                    "state": "complete",
                    "success_sha256": hashlib.sha256(success.read_bytes()).hexdigest(),
                }
            )
        plan = root / "primary/QUEUE_PLAN.json"
        write_json(
            plan,
            {
                "schema_version": 1,
                "queue_id": "primary-test",
                "root": str(root),
                "min_free_bytes": 1,
                "min_free_inodes": 1,
                "poll_seconds": 0.01,
                "max_gpu_temperature_c": 88,
                "base_env": {
                    key: os.environ[key]
                    for key in ("HOME", "PATH")
                    if key in os.environ
                },
                "pinned_files": pins,
                "jobs": jobs,
            },
        )
        plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
        state = plan.parent / "QUEUE_STATE.json"
        write_json(
            state,
            {
                "schema_version": 1,
                "queue_id": "primary-test",
                "plan_sha256": plan_sha,
                "state": "complete",
                "current_job": None,
                "jobs": state_jobs,
            },
        )
        nvidia_smi = root / "nvidia-smi"
        nvidia_smi.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        nvidia_smi.chmod(0o755)
        config = root / "completion.json"
        write_json(
            config,
            {
                "schema_version": 1,
                "root": str(root),
                "primary_queue_id": "primary-test",
                "primary_plan": file_record(plan),
                "primary_state": str(state),
                "nvidia_smi": file_record(nvidia_smi),
            },
        )
        return config, plan, state

    def setUp(self):
        self.temperature = mock.patch.object(
            experiment_queue, "gpu_temperature", return_value=40.0
        )
        self.temperature.start()

    def tearDown(self):
        self.temperature.stop()

    def test_writes_and_revalidates_exact_completion_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config_path, _, _ = self.make_fixture(root)
            config = validator.validate_config(config_path)
            with mock.patch.object(validator, "gpu_compute_pids", return_value=[]):
                report = validator.completion_report(config)
                proof = root / "overflow/PRIMARY_COMPLETE.json"
                validator.atomic_json(proof, report)
                self.assertEqual(json.loads(proof.read_text()), report)
                self.assertEqual(validator.completion_report(config), report)
            self.assertEqual(
                [job["id"] for job in report["jobs"]], validator.PRIMARY_JOB_IDS
            )

    def test_running_primary_is_not_ready_but_halt_is_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config_path, _, state_path = self.make_fixture(root)
            config = validator.validate_config(config_path)
            state = json.loads(state_path.read_text())
            state["state"] = "running"
            write_json(state_path, state)
            with self.assertRaises(validator.PrimaryNotReady):
                validator.completion_report(config)
            state["state"] = "halted"
            write_json(state_path, state)
            with self.assertRaisesRegex(validator.CompletionError, "not complete"):
                validator.completion_report(config)

    def test_rejects_plan_state_and_success_hash_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config_path, plan_path, state_path = self.make_fixture(root)
            config = validator.validate_config(config_path)
            state = json.loads(state_path.read_text())
            state["plan_sha256"] = "0" * 64
            write_json(state_path, state)
            with self.assertRaisesRegex(validator.CompletionError, "plan SHA-256"):
                validator.completion_report(config)
            state["plan_sha256"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
            state["jobs"][0]["success_sha256"] = "0" * 64
            write_json(state_path, state)
            with self.assertRaisesRegex(validator.CompletionError, "recorded success"):
                validator.completion_report(config)

    def test_rejects_artifact_validator_failure_and_busy_gpu(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config_path, _, _ = self.make_fixture(root)
            config = validator.validate_config(config_path)
            with mock.patch.object(
                experiment_queue,
                "completed_evidence_error",
                return_value="validator exited 2",
            ):
                with self.assertRaisesRegex(
                    validator.CompletionError, "failed revalidation"
                ):
                    validator.completion_report(config)
            with mock.patch.object(validator, "gpu_compute_pids", return_value=[99]):
                with self.assertRaisesRegex(validator.PrimaryNotReady, "compute"):
                    validator.completion_report(config)

    def test_config_is_closed_and_bound_to_state_beside_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            config_path, _, _ = self.make_fixture(root)
            payload = json.loads(config_path.read_text())
            payload["unknown"] = True
            write_json(config_path, payload)
            with self.assertRaisesRegex(validator.CompletionError, "fields differ"):
                validator.validate_config(config_path)
            payload.pop("unknown")
            payload["primary_state"] = str(root / "other-state.json")
            write_json(config_path, payload)
            with self.assertRaisesRegex(validator.CompletionError, "not beside"):
                validator.validate_config(config_path)


if __name__ == "__main__":
    unittest.main()
