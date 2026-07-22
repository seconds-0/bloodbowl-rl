from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE = ROOT / "tools" / "recovery_preservation.py"
SPEC = importlib.util.spec_from_file_location("recovery_preservation", MODULE)
assert SPEC and SPEC.loader
rp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rp)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, payload: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return path


class RecoveryPreservationTests(unittest.TestCase):
    def fixture(self, temporary: str) -> dict[str, Path]:
        outer = Path(temporary)
        root = outer / "recovery"
        queue = root / "runs" / "vacation-r0-overflow-recovery-20260719-v1"
        work = queue / "work" / "full-control"
        terminal = write_json(
            queue / "work" / "terminal-evidence" / "RECOVERY_AUTHORIZED.json",
            {"accepted": True},
        )
        screen = write_json(work / "SCREEN_COMPLETE.json", {"accepted": True})
        plan = {
            "schema_version": 1,
            "queue_id": queue.name,
            "jobs": [
                {
                    "id": "terminal-evidence-preflight",
                    "success": {"path": str(terminal)},
                },
                {
                    "id": "full-control-rerun",
                    "success": {"path": str(screen)},
                },
            ],
        }
        plan_path = write_json(queue / "QUEUE_PLAN.json", plan)
        state = {
            "schema_version": 1,
            "queue_id": queue.name,
            "state": "complete",
            "current_job": None,
            "message": rp.COMPLETE_MESSAGE,
            "plan_sha256": digest(plan_path),
            "jobs": [
                {
                    "id": "terminal-evidence-preflight",
                    "state": "complete",
                    "exit_code": 0,
                    "success_sha256": digest(terminal),
                },
                {
                    "id": "full-control-rerun",
                    "state": "complete",
                    "exit_code": 0,
                    "success_sha256": digest(screen),
                },
            ],
        }
        write_json(queue / "QUEUE_STATE.json", state)
        for seed in (42, 43, 44):
            run_dir = root / "vendor" / "PufferLib" / "checkpoints" / "bloodbowl" / str(seed)
            checkpoint = run_dir / "0000011999903744.bin"
            checkpoint.parent.mkdir(parents=True, exist_ok=True)
            checkpoint.write_bytes(f"checkpoint-{seed}".encode())
            run_manifest = write_json(run_dir / "RUN_MANIFEST.json", {"seed": seed})
            log = work / f"full-control-both-s{seed}.log"
            log.write_bytes(f"log-{seed}\n".encode())
            (Path(str(log) + ".run_dir")).write_text(str(run_dir) + "\n", encoding="utf-8")
            result = {
                "schema_version": 2,
                "trainer_complete": True,
                "acceptance_pass": True,
                "acceptance_failures": [],
                "seed": seed,
                "log": str(log),
                "log_sha256": digest(log),
                "checkpoint": str(checkpoint),
                "checkpoint_bytes": checkpoint.stat().st_size,
                "checkpoint_sha256": digest(checkpoint),
                "run_manifest_sha256": digest(run_manifest),
            }
            write_json(work / f"full-control-both-s{seed}.result.json", result)
        selection = write_json(
            root / "runs" / "bbtv-follow" / "selection.json",
            {"seed": 44, "step": 11_999_903_744},
        )
        return {"outer": outer, "root": root, "queue": queue, "selection": selection}

    def make_inventory(self, paths: dict[str, Path]) -> dict:
        return rp.build_inventory(
            recovery_root=paths["root"],
            queue_dir=paths["queue"],
            bbtv_selection=paths["selection"],
        )

    def copy_inventory(self, paths: dict[str, Path], inventory: dict) -> Path:
        copy = paths["outer"] / "copy"
        for record in inventory["files"]:
            source = paths["root"] / record["path"]
            target = copy / record["path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        return copy

    def test_plan_and_verify_exact_copy(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            inventory = self.make_inventory(paths)
            self.assertEqual([item["seed"] for item in inventory["result_bindings"]], [42, 43, 44])
            self.assertEqual(inventory["inventory_sha256"], rp.canonical_hash(inventory["files"]))
            copy = self.copy_inventory(paths, inventory)
            result = rp.verify_copy(inventory, copy)
            self.assertTrue(result["accepted"])
            self.assertEqual(result["file_count"], inventory["file_count"])

    def test_running_or_wrong_job_set_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            state_path = paths["queue"] / "QUEUE_STATE.json"
            state = json.loads(state_path.read_text())
            state["state"] = "running"
            write_json(state_path, state)
            with self.assertRaisesRegex(rp.PreservationError, "not complete"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            plan_path = paths["queue"] / "QUEUE_PLAN.json"
            state_path = paths["queue"] / "QUEUE_STATE.json"
            plan = json.loads(plan_path.read_text())
            state = json.loads(state_path.read_text())
            plan["jobs"][0]["id"] = "other"
            state["jobs"][0]["id"] = "other"
            write_json(plan_path, plan)
            state["plan_sha256"] = digest(plan_path)
            write_json(state_path, state)
            with self.assertRaisesRegex(rp.PreservationError, "job set"):
                self.make_inventory(paths)

    def test_success_escape_relative_result_and_selection_symlink_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            plan_path = paths["queue"] / "QUEUE_PLAN.json"
            state_path = paths["queue"] / "QUEUE_STATE.json"
            plan = json.loads(plan_path.read_text())
            state = json.loads(state_path.read_text())
            outside = write_json(paths["root"] / "outside-success.json", {"accepted": True})
            plan["jobs"][0]["success"]["path"] = str(outside)
            state["jobs"][0]["success_sha256"] = digest(outside)
            write_json(plan_path, plan)
            state["plan_sha256"] = digest(plan_path)
            write_json(state_path, state)
            with self.assertRaisesRegex(rp.PreservationError, "escapes the queue"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            result_path = next((paths["queue"] / "work" / "full-control").glob("*.result.json"))
            result = json.loads(result_path.read_text())
            result["log"] = "relative.log"
            write_json(result_path, result)
            with self.assertRaisesRegex(rp.PreservationError, "not absolute"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            selection = paths["selection"]
            target = selection.with_name("selection-target.json")
            selection.replace(target)
            selection.symlink_to(target)
            with self.assertRaisesRegex(rp.PreservationError, "non-symlink"):
                self.make_inventory(paths)

    def test_result_digest_escape_and_seed_set_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            result_path = next((paths["queue"] / "work" / "full-control").glob("*.result.json"))
            result = json.loads(result_path.read_text())
            result["checkpoint_sha256"] = "0" * 64
            write_json(result_path, result)
            with self.assertRaisesRegex(rp.PreservationError, "checkpoint digest"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            result_path = next((paths["queue"] / "work" / "full-control").glob("*.result.json"))
            result = json.loads(result_path.read_text())
            outside = paths["outer"] / "outside.bin"
            outside.write_bytes(b"outside")
            result["checkpoint"] = str(outside)
            result["checkpoint_bytes"] = outside.stat().st_size
            result["checkpoint_sha256"] = digest(outside)
            write_json(result_path, result)
            with self.assertRaisesRegex(rp.PreservationError, "escapes"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            result_path = next((paths["queue"] / "work" / "full-control").glob("*s44.result.json"))
            result = json.loads(result_path.read_text())
            result["seed"] = 45
            write_json(result_path, result)
            with self.assertRaisesRegex(rp.PreservationError, "seed set"):
                self.make_inventory(paths)

    def test_copy_mutation_missing_extra_and_mode_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            inventory = self.make_inventory(paths)
            copy = self.copy_inventory(paths, inventory)
            target = copy / inventory["files"][0]["path"]
            target.write_bytes(target.read_bytes() + b"changed")
            with self.assertRaisesRegex(rp.PreservationError, "identity differs"):
                rp.verify_copy(inventory, copy)

            shutil.rmtree(copy)
            copy = self.copy_inventory(paths, inventory)
            missing = copy / inventory["files"][0]["path"]
            missing.unlink()
            with self.assertRaisesRegex(rp.PreservationError, "file set differs"):
                rp.verify_copy(inventory, copy)

            shutil.rmtree(copy)
            copy = self.copy_inventory(paths, inventory)
            target = copy / inventory["files"][0]["path"]
            target.chmod(target.stat().st_mode ^ 0o100)
            with self.assertRaisesRegex(rp.PreservationError, "identity differs"):
                rp.verify_copy(inventory, copy)

            shutil.rmtree(copy)
            copy = self.copy_inventory(paths, inventory)
            extra = copy / "extra"
            extra.write_text("extra", encoding="utf-8")
            with self.assertRaisesRegex(rp.PreservationError, "file set differs"):
                rp.verify_copy(inventory, copy)

    def test_recorded_log_digest_and_midscan_change_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            result_path = next((paths["queue"] / "work" / "full-control").glob("*.result.json"))
            result = json.loads(result_path.read_text())
            result["log_sha256"] = "0" * 64
            write_json(result_path, result)
            with self.assertRaisesRegex(rp.PreservationError, "result-bound log digest"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            original_walk = rp._walk_regular_files
            calls = 0

            def changing_walk(directory: Path, root: Path) -> set[str]:
                nonlocal calls
                result = original_walk(directory, root)
                calls += 1
                if calls == 2:
                    paths["selection"].write_text(
                        '{"seed": 44, "step": 1}\n', encoding="utf-8"
                    )
                return result

            with mock.patch.object(rp, "_walk_regular_files", side_effect=changing_walk):
                with self.assertRaisesRegex(rp.PreservationError, "changed during"):
                    self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            original_boundary = rp._validate_queue_boundary
            calls = 0

            def changing_boundary(queue_dir: Path) -> dict:
                nonlocal calls
                result = original_boundary(queue_dir)
                calls += 1
                if calls == 1:
                    terminal = (
                        paths["queue"]
                        / "work"
                        / "terminal-evidence"
                        / "RECOVERY_AUTHORIZED.json"
                    )
                    terminal.write_text('{"accepted": false}\n', encoding="utf-8")
                return result

            with mock.patch.object(
                rp, "_validate_queue_boundary", side_effect=changing_boundary
            ):
                with self.assertRaisesRegex(
                    rp.PreservationError, "success artifact drifted"
                ):
                    self.make_inventory(paths)

    def test_copy_midverification_change_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            inventory = self.make_inventory(paths)
            copy = self.copy_inventory(paths, inventory)
            first = copy / inventory["files"][0]["path"]
            original_record = rp._stable_record
            calls = 0

            def changing_record(root: Path, relative: str):
                nonlocal calls
                result = original_record(root, relative)
                calls += 1
                if calls == 2:
                    first.write_bytes(first.read_bytes() + b"changed")
                return result

            with mock.patch.object(rp, "_stable_record", side_effect=changing_record):
                with self.assertRaisesRegex(rp.PreservationError, "changed during"):
                    rp.verify_copy(inventory, copy)

    def test_authoritative_schema_and_selection_shape_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            plan_path = paths["queue"] / "QUEUE_PLAN.json"
            state_path = paths["queue"] / "QUEUE_STATE.json"
            plan = json.loads(plan_path.read_text())
            state = json.loads(state_path.read_text())
            plan["schema_version"] = 2
            write_json(plan_path, plan)
            state["plan_sha256"] = digest(plan_path)
            write_json(state_path, state)
            with self.assertRaisesRegex(rp.PreservationError, "schema version"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            result_path = next(
                (paths["queue"] / "work" / "full-control").glob("*.result.json")
            )
            result = json.loads(result_path.read_text())
            result["schema_version"] = 1
            write_json(result_path, result)
            with self.assertRaisesRegex(rp.PreservationError, "schema version"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            write_json(paths["selection"], {"seed": 44, "step": True})
            with self.assertRaisesRegex(rp.PreservationError, "seed-44 checkpoint"):
                self.make_inventory(paths)

    def test_queue_symlink_and_output_inside_recovery_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            target = paths["queue"] / "QUEUE_PLAN.json"
            (paths["queue"] / "linked-plan").symlink_to(target)
            with self.assertRaisesRegex(rp.PreservationError, "symlink"):
                self.make_inventory(paths)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            with self.assertRaisesRegex(rp.PreservationError, "outside"):
                rp.main([
                    "plan",
                    "--recovery-root", str(paths["root"]),
                    "--queue-dir", str(paths["queue"]),
                    "--bbtv-selection", str(paths["selection"]),
                    "--output", str(paths["root"] / "inventory.json"),
                ])

    def test_manifest_schema_inventory_and_strict_json_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            inventory = self.make_inventory(paths)
            inventory["inventory_sha256"] = "0" * 64
            with self.assertRaisesRegex(rp.PreservationError, "inventory digest"):
                rp.verify_copy(inventory, paths["outer"])

            malformed = paths["outer"] / "malformed.json"
            malformed.write_text('{"a": 1, "a": 2}\n', encoding="utf-8")
            with self.assertRaisesRegex(rp.PreservationError, "duplicate JSON key"):
                rp.load_json(malformed)

        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            inventory = self.make_inventory(paths)
            inventory["result_bindings"][0]["checkpoint_sha256"] = "0" * 64
            with self.assertRaisesRegex(rp.PreservationError, "result-bound digest"):
                rp._validate_manifest(inventory)

            inventory = self.make_inventory(paths)
            inventory["unexpected"] = True
            with self.assertRaisesRegex(rp.PreservationError, "top-level schema"):
                rp._validate_manifest(inventory)

    def test_cli_writes_new_external_manifest_and_emits_exact_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self.fixture(temporary)
            manifest_path = paths["outer"] / "inventory.json"
            self.assertEqual(
                rp.main([
                    "plan",
                    "--recovery-root", str(paths["root"]),
                    "--queue-dir", str(paths["queue"]),
                    "--bbtv-selection", str(paths["selection"]),
                    "--output", str(manifest_path),
                ]),
                0,
            )
            manifest = rp.load_json(manifest_path)
            completed = subprocess.run(
                [sys.executable, str(MODULE), "emit-files", str(manifest_path)],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, completed.stderr.decode())
            self.assertEqual(
                completed.stdout.split(b"\0"),
                [record["path"].encode() for record in manifest["files"]] + [b""],
            )


if __name__ == "__main__":
    unittest.main()
