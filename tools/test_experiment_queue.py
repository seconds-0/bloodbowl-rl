#!/usr/bin/env python3

import json
import hashlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import experiment_queue as queue


class ExperimentQueueTests(unittest.TestCase):
    def make_plan(self, root: Path, jobs: list[dict], **overrides) -> Path:
        payload = {
            "schema_version": 1,
            "queue_id": "test-queue",
            "root": str(root),
            "min_free_bytes": 1,
            "poll_seconds": 0.01,
            "jobs": jobs,
            **overrides,
        }
        path = root / "plan.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    @staticmethod
    def write_job(root: Path, job_id: str, body: str, **overrides) -> dict:
        success = root / f"{job_id}.done"
        return {
            "id": job_id,
            "command": [sys.executable, "-c", body, str(success)],
            "cwd": str(root),
            "log": str(root / f"{job_id}.log"),
            "success": {"path": str(success)},
            **overrides,
        }

    def test_runs_jobs_in_order_and_publishes_complete_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = self.write_job(
                root, "first",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('one')",
            )
            second = self.write_job(
                root, "second",
                "import pathlib,sys; "
                "assert pathlib.Path('first.done').read_text() == 'one'; "
                "pathlib.Path(sys.argv[1]).write_text('two')",
            )
            plan = self.make_plan(root, [first, second])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "complete")
            self.assertEqual([j["state"] for j in recorded["jobs"]],
                             ["complete", "complete"])
            self.assertEqual((root / "second.done").read_text(), "two")

    def test_existing_success_artifact_is_validated_and_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            success = root / "done"
            success.write_text("kept")
            job = {
                "id": "skip",
                "command": [sys.executable, "-c", "raise SystemExit(9)"],
                "cwd": str(root),
                "log": str(root / "skip.log"),
                "success": {"path": str(success)},
            }
            plan = self.make_plan(root, [job])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["jobs"][0]["state"], "complete")
            self.assertTrue(recorded["jobs"][0]["recovered_from_artifact"])

    def test_failure_halts_without_running_later_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed = self.write_job(root, "failed", "raise SystemExit(7)")
            later = self.write_job(
                root, "later",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            )
            plan = self.make_plan(root, [failed, later])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "halted")
            self.assertEqual(recorded["jobs"][0]["exit_code"], 7)
            self.assertEqual(recorded["jobs"][1]["state"], "pending")
            self.assertFalse((root / "later.done").exists())

    def test_plan_drift_halts_a_preexisting_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "once",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            )
            plan = self.make_plan(root, [job])
            state = root / "state.json"
            self.assertEqual(queue.run_queue(plan, state), 0)

            payload = json.loads(plan.read_text())
            payload["min_free_bytes"] = 2
            plan.write_text(json.dumps(payload), encoding="utf-8")
            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "halted")
            self.assertIn("plan SHA-256 changed", recorded["message"])

    def test_success_digest_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "digest",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('wrong')",
            )
            job["success"]["sha256"] = "0" * 64
            plan = self.make_plan(root, [job])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "halted")
            self.assertIn("success validation failed", recorded["message"])

    def test_absent_progress_file_halts_a_hung_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root,
                "hung",
                "import time; time.sleep(60)",
                progress={
                    "path": str(root / "never-created.progress"),
                    "max_stale_seconds": 0.02,
                },
            )
            plan = self.make_plan(root, [job])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "halted")
            self.assertIn("absent", recorded["message"])

    def test_max_runtime_halts_a_hung_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root,
                "bounded",
                "import time; time.sleep(60)",
                max_runtime_seconds=0.02,
            )
            plan = self.make_plan(root, [job])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "halted")
            self.assertIn("runtime guard", recorded["message"])

    def test_interrupted_non_resume_safe_job_halts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root,
                "unsafe",
                "raise SystemExit('must not run')",
            )
            plan = self.make_plan(root, [job])
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            state = root / "state.json"
            recorded = queue.new_state(json.loads(plan.read_text()), plan_sha)
            recorded["jobs"][0]["state"] = "running"
            queue.atomic_json(state, recorded)

            self.assertEqual(queue.run_queue(plan, state), 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("not resume-safe", observed["message"])

    def test_temperature_query_failure_terminates_job_and_halts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root,
                "thermal-query",
                "import time; time.sleep(60)",
            )
            plan = self.make_plan(root, [job], max_gpu_temperature_c=88)
            state = root / "state.json"

            with mock.patch.object(
                queue,
                "gpu_temperature",
                side_effect=[70.0, queue.QueueError("query unavailable")],
            ):
                self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "halted")
            self.assertIn("monitor failed closed", recorded["message"])

    def test_preexisting_stale_progress_gets_a_startup_window(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            progress = root / "progress.json"
            progress.write_text("old")
            os.utime(progress, (1, 1))
            job = self.write_job(
                root,
                "recovery",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                progress={
                    "path": str(progress),
                    "max_stale_seconds": 1,
                },
            )
            plan = self.make_plan(root, [job])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            recorded = json.loads(state.read_text())
            self.assertEqual(recorded["state"], "complete")


if __name__ == "__main__":
    unittest.main()
