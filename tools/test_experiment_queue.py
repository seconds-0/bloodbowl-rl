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
    def setUp(self):
        self.gpu_patch = mock.patch.object(
            queue, "gpu_temperature", return_value=50.0)
        self.gpu_patch.start()

    def tearDown(self):
        self.gpu_patch.stop()

    def make_plan(self, root: Path, jobs: list[dict], **overrides) -> Path:
        executable = Path(sys.executable).resolve()
        validator_script = root / "validate_success.py"
        validator_script.write_text(
            "import pathlib,sys\n"
            "raise SystemExit(0 if pathlib.Path(sys.argv[1]).is_file() else 1)\n"
        )
        pinned_paths = {str(executable), str(validator_script.resolve())}
        producer_by_path: dict[str, str] = {}
        for job in jobs:
            command = job["command"]
            if command[:2] == [sys.executable, "-c"]:
                script = root / f"{job['id']}_command.py"
                script.write_text(command[2] + "\n")
                job["command"] = [sys.executable, str(script), *command[3:]]
                pinned_paths.add(str(script.resolve()))
            job.setdefault("resume_safe", False)
            job.setdefault("pinned_inputs", [])
            job.setdefault("max_runtime_seconds", 5)
            if "progress" not in job:
                job.setdefault(
                    "progress_not_required_reason", "bounded unit-test command"
                )
            job["success"].setdefault(
                "validator",
                [
                    sys.executable,
                    str(validator_script),
                    job["success"]["path"],
                ],
            )
            job["success"].setdefault("validator_timeout_seconds", 2)
            mutable = {
                job["log"], job["success"]["path"],
                *(job.get("mutable_paths", [])),
            }
            if "progress" in job:
                mutable.add(job["progress"]["path"])

            def typed(arguments: list[str]) -> list[dict[str, str]]:
                rendered = []
                for value in arguments:
                    resolved = str(Path(value).resolve())
                    if resolved in pinned_paths:
                        rendered.append({"kind": "pinned", "path": resolved})
                        if resolved not in job["pinned_inputs"]:
                            job["pinned_inputs"].append(resolved)
                    elif value in mutable:
                        rendered.append({"kind": "mutable", "path": value})
                    elif resolved in producer_by_path:
                        rendered.append({
                            "kind": "artifact",
                            "job": producer_by_path[resolved],
                            "path": resolved,
                        })
                    else:
                        rendered.append({"kind": "literal", "value": value})
                return rendered

            job["command"] = typed(job["command"])
            job["success"]["validator"] = typed(
                job["success"]["validator"])
            job["env"] = {
                key: typed([value])[0]
                for key, value in job.get("env", {}).items()
            }
            producer_by_path[
                str(Path(job["success"]["path"]).resolve())
            ] = job["id"]
        payload = {
            "schema_version": 1,
            "queue_id": "test-queue",
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
            "pinned_files": [
                {
                    "kind": "file", "path": value,
                    "bytes": Path(value).stat().st_size,
                    "sha256": hashlib.sha256(Path(value).read_bytes()).hexdigest(),
                    "role": "test Python executable" if Path(value) == executable
                    else "pinned test runner",
                }
                for value in sorted(pinned_paths)
            ],
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
                "assert pathlib.Path(sys.argv[2]).read_text() == 'one'; "
                "pathlib.Path(sys.argv[1]).write_text('two')",
            )
            second["command"].append(first["success"]["path"])
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

    def test_exited_wrapper_cannot_strand_same_group_child(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            failed = self.write_job(
                root,
                "orphan",
                (
                    "import pathlib,subprocess,sys; "
                    "child=subprocess.Popen(['sleep','60']); "
                    "pathlib.Path(sys.argv[1]).with_suffix('.child').write_text("
                    "str(child.pid)); raise SystemExit(7)"
                ),
            )
            plan = self.make_plan(root, [failed])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            child_pid = int((root / "orphan.child").read_text())
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)

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

            # A persisted safety halt is terminal across service restarts.
            self.assertEqual(queue.run_queue(plan, state), 0)
            observed_again = json.loads(state.read_text())
            self.assertEqual(observed_again["state"], "halted")

    def test_interrupted_unsafe_job_cannot_recover_from_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "unsafe-artifact", "raise SystemExit('must not run')"
            )
            plan = self.make_plan(root, [job])
            Path(job["success"]["path"]).touch()
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            state = root / "state.json"
            recorded = queue.new_state(json.loads(plan.read_text()), plan_sha)
            recorded["jobs"][0]["state"] = "running"
            queue.atomic_json(state, recorded)

            self.assertEqual(queue.run_queue(plan, state), 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("not resume-safe", observed["message"])

    def test_completed_job_with_missing_artifact_halts_without_rerun(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            marker = root / "reran"
            job = self.write_job(
                root, "completed",
                "import pathlib,sys; pathlib.Path('reran').touch(); "
                "pathlib.Path(sys.argv[1]).touch()",
            )
            plan = self.make_plan(root, [job])
            plan_sha = hashlib.sha256(plan.read_bytes()).hexdigest()
            state = root / "state.json"
            recorded = queue.new_state(json.loads(plan.read_text()), plan_sha)
            recorded["state"] = "running"
            recorded["jobs"][0]["state"] = "complete"
            recorded["jobs"][0]["success_sha256"] = "0" * 64
            queue.atomic_json(state, recorded)

            self.assertEqual(queue.run_queue(plan, state), 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("evidence drifted", observed["message"])
            self.assertFalse(marker.exists())

    def test_completed_queue_revalidates_artifacts_on_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "complete-restart",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('ok')",
            )
            plan = self.make_plan(root, [job])
            state = root / "state.json"
            self.assertEqual(queue.run_queue(plan, state), 0)
            self.assertEqual(json.loads(state.read_text())["state"], "complete")
            Path(job["success"]["path"]).unlink()

            self.assertEqual(queue.run_queue(plan, state), 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("evidence drifted", observed["message"])

    def test_consumer_cannot_mutate_a_predecessor_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            producer = self.write_job(
                root, "producer",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('A')",
            )
            consumer = self.write_job(
                root, "consumer",
                "import pathlib,sys; source=pathlib.Path(sys.argv[2]); "
                "value=source.read_text(); source.write_text('B'); "
                "pathlib.Path(sys.argv[1]).write_text('used-'+value)",
            )
            consumer["command"].append(producer["success"]["path"])
            plan = self.make_plan(root, [producer, consumer])
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("producer success artifact drifted", observed["message"])

    def test_hanging_validator_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root,
                "validator-timeout",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            )
            plan = self.make_plan(root, [job])
            payload = json.loads(plan.read_text())
            hanging = root / "hanging_validator.py"
            hanging.write_text("import time\ntime.sleep(60)\n")
            payload["pinned_files"].append({
                "kind": "file", "path": str(hanging),
                "bytes": hanging.stat().st_size,
                "sha256": hashlib.sha256(hanging.read_bytes()).hexdigest(),
                "role": "hanging test validator",
            })
            payload["jobs"][0]["pinned_inputs"].append(str(hanging))
            payload["jobs"][0]["success"]["validator"] = [
                {"kind": "pinned", "path": str(Path(sys.executable).resolve())},
                {"kind": "pinned", "path": str(hanging)},
            ]
            payload["jobs"][0]["success"]["validator_timeout_seconds"] = 0.02
            plan.write_text(json.dumps(payload))
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("validator timed out", observed["message"])

    def test_fast_validator_output_is_bounded_after_exit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "validator-output",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            )
            plan = self.make_plan(root, [job])
            payload = json.loads(plan.read_text())
            noisy = root / "noisy_validator.py"
            noisy.write_text(
                "import os\n"
                f"os.write(1, b'x' * ({queue.MAX_VALIDATOR_OUTPUT_BYTES} + 1))\n"
            )
            payload["pinned_files"].append({
                "kind": "file", "path": str(noisy),
                "bytes": noisy.stat().st_size,
                "sha256": hashlib.sha256(noisy.read_bytes()).hexdigest(),
                "role": "noisy test validator",
            })
            payload["jobs"][0]["pinned_inputs"].append(str(noisy))
            payload["jobs"][0]["success"]["validator"] = [
                {"kind": "pinned", "path": str(Path(sys.executable).resolve())},
                {"kind": "pinned", "path": str(noisy)},
            ]
            plan.write_text(json.dumps(payload))

            self.assertEqual(queue.run_queue(plan, root / "state.json"), 0)
            observed = json.loads((root / "state.json").read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("validator output limit exceeded", observed["message"])

    def test_unknown_guard_field_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root,
                "typo",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                max_runtime_second=5,
            )
            plan = self.make_plan(root, [job])
            with self.assertRaisesRegex(queue.QueueError, "unknown job 1 fields"):
                queue.run_queue(plan, root / "state.json")

    def test_pinned_input_drift_halts_before_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root,
                "pin-drift",
                "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
            )
            pinned = root / "reward.json"
            pinned.write_text("frozen")
            plan = self.make_plan(root, [job])
            payload = json.loads(plan.read_text())
            payload["pinned_files"].append({
                "kind": "file",
                "path": str(pinned),
                "bytes": pinned.stat().st_size,
                "sha256": hashlib.sha256(pinned.read_bytes()).hexdigest(),
                "role": "reward manifest",
            })
            plan.write_text(json.dumps(payload))
            pinned.write_text("drifted")
            state = root / "state.json"

            self.assertEqual(queue.run_queue(plan, state), 0)
            observed = json.loads(state.read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("pinned reward manifest", observed["message"])
            self.assertFalse(Path(job["success"]["path"]).exists())

    def test_directory_input_requires_and_rechecks_a_tree_pin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pool = root / "pool"
            pool.mkdir()
            (pool / "input.txt").write_text("frozen")
            job = self.write_job(
                root, "tree-pin",
                "import os,pathlib,sys; pathlib.Path(sys.argv[1]).write_text("
                "pathlib.Path(os.environ['POOL']).joinpath('input.txt').read_text())",
                env={"POOL": str(pool)},
            )
            plan = self.make_plan(root, [job])
            payload = json.loads(plan.read_text())
            files, size, identity = queue.tree_identity(pool)
            payload["pinned_files"].append({
                "kind": "tree", "path": str(pool), "files": files,
                "bytes": size, "sha256": identity, "role": "replay pool",
            })
            payload["jobs"][0]["pinned_inputs"].append(str(pool))
            payload["jobs"][0]["env"]["POOL"] = {
                "kind": "pinned", "path": str(pool),
            }
            plan.write_text(json.dumps(payload))
            (pool / "input.txt").write_text("mutated-unpinned")

            self.assertEqual(queue.run_queue(plan, root / "state.json"), 0)
            observed = json.loads((root / "state.json").read_text())
            self.assertEqual(observed["state"], "halted")
            self.assertIn("pinned replay pool", observed["message"])
            self.assertFalse(Path(job["success"]["path"]).exists())

    def test_path_bearing_literal_and_untyped_env_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "typed", "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()"
            )
            plan = self.make_plan(root, [job])
            payload = json.loads(plan.read_text())
            payload["jobs"][0]["env"] = {"POOL": str(root / "pool")}
            plan.write_text(json.dumps(payload))
            with self.assertRaisesRegex(queue.QueueError, "typed argument"):
                queue.validate_plan(plan)

            payload["jobs"][0]["env"] = {
                "POOL": {"kind": "literal", "value": str(root / "pool")}
            }
            plan.write_text(json.dumps(payload))
            with self.assertRaisesRegex(queue.QueueError, "literal must be"):
                queue.validate_plan(plan)

            for value in (
                "pool", "future_pool", "input.ini", ".", "..", "-c", "-m",
                "-e",
            ):
                (root / "pool").mkdir(exist_ok=True)
                (root / "input.ini").touch(exist_ok=True)
                payload["jobs"][0]["env"] = {
                    "POOL": {"kind": "literal", "value": value}
                }
                plan.write_text(json.dumps(payload))
                with self.subTest(value=value):
                    with self.assertRaisesRegex(queue.QueueError, "literal must be"):
                        queue.validate_plan(plan)

            payload["jobs"][0]["env"] = {}
            payload["jobs"][0]["command"][1] = {
                "kind": "literal", "value": "future_runner.py",
            }
            plan.write_text(json.dumps(payload))
            with self.assertRaisesRegex(
                queue.QueueError, "literal must be"
            ):
                queue.validate_plan(plan)

            payload["jobs"][0]["command"][1] = {
                "kind": "literal", "value": "--eval",
            }
            plan.write_text(json.dumps(payload))
            with self.assertRaisesRegex(
                queue.QueueError, "requires a pinned runner"
            ):
                queue.validate_plan(plan)

    def test_long_job_cannot_claim_progress_exemption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "long", "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()",
                max_runtime_seconds=queue.MAX_PROGRESS_EXEMPT_SECONDS + 1,
            )
            plan = self.make_plan(root, [job])
            with self.assertRaisesRegex(queue.QueueError, "progress-exemption"):
                queue.validate_plan(plan)

    def test_thermal_limit_is_mandatory(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            job = self.write_job(
                root, "thermal", "import pathlib,sys; pathlib.Path(sys.argv[1]).touch()"
            )
            plan = self.make_plan(root, [job])
            payload = json.loads(plan.read_text())
            del payload["max_gpu_temperature_c"]
            plan.write_text(json.dumps(payload))
            with self.assertRaisesRegex(queue.QueueError, "must be in 1..120"):
                queue.validate_plan(plan)

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
