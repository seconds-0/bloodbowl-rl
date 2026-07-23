import contextlib
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "exact_action_canary_authority.py"


def load_module():
    spec = importlib.util.spec_from_file_location(
        "exact_action_canary_authority", MODULE_PATH
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ExactActionCanaryAuthorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.a = load_module()

    def make_git_source(self, root: Path) -> tuple[str, str]:
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True)
        subprocess.run(
            ["git", "config", "user.email", "authority-test@example.invalid"],
            cwd=root,
            check=True,
        )
        subprocess.run(
            ["git", "config", "user.name", "Authority Test"],
            cwd=root,
            check=True,
        )
        tracked = root / "tracked.txt"
        tracked.write_text("candidate\n", encoding="utf-8")
        subprocess.run(["git", "add", "tracked.txt"], cwd=root, check=True)
        subprocess.run(
            ["git", "commit", "-q", "-m", "candidate"], cwd=root, check=True
        )
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        tree = subprocess.run(
            ["git", "rev-parse", "HEAD^{tree}"],
            cwd=root,
            check=True,
            text=True,
            capture_output=True,
        ).stdout.strip()
        return commit, tree

    def make_qualification(self, temp: Path):
        source = temp / "candidate"
        source.mkdir()
        commit, tree = self.make_git_source(source)
        runner = temp / "qualification-runner"
        subprocess.run(
            ["git", "clone", "-q", str(source), str(runner)], check=True
        )
        puffer = source / "vendor" / "PufferLib"
        module = puffer / "pufferlib" / "_C.test.so"
        module.parent.mkdir(parents=True)
        module.write_bytes(b"compiled-module")
        cudart = temp / "libcudart.so.12.4.127"
        cudart.write_bytes(b"cudart")
        qualification_root = temp / "qualification"
        qualification_root.mkdir()

        runtime = {
            "schema_version": 1,
            "cuda_visible_devices": "0",
            "library": {
                "requested_soname": "libcudart.so.12",
                "resolved_path": str(cudart),
                "sha256": sha(cudart),
            },
            "before_extension_import": {
                "stage": "before_extension_import",
                "return_code": 0,
                "error_name": "cudaSuccess",
                "error_string": "no error",
                "device_count": 1,
            },
            "after_extension_import": {
                "stage": "after_extension_import",
                "return_code": 0,
                "error_name": "cudaSuccess",
                "error_string": "no error",
                "device_count": 1,
            },
        }
        identity = {
            "compiled_env": "bloodbowl",
            "precision_bytes": 4,
            "observation_abi": "obs-v5",
            "observation_version": 5,
            "action_abi": "exact-joint-v1",
            "qualification_surface": True,
            "puffer_root": str(puffer),
            "module": str(module),
            "module_sha256": sha(module),
            "backend_sources_sha256": "b" * 64,
            "compiled_backend_sha256": "b" * 64,
            "runtime_sources_sha256": "b" * 64,
            "environment_sha256": "e" * 64,
            "installed_snapshot_sha256": "e" * 64,
        }
        hard_zero = {key: 0.0 for key in self.a.HARD_INTEGRITY_KEYS}
        cells = []
        for index, name in enumerate(self.a.REQUIRED_CELL_NAMES):
            record = qualification_root / f"{name}.json"
            payload = {
                "schema_version": 3,
                "kind": name,
                "accepted": True,
                "qualification_only": True,
                "identity": identity,
                "cuda_runtime_preflight": runtime,
            }
            if name == "throughput":
                payload["throughput"] = {
                    "hard_integrity": hard_zero,
                    "hard_integrity_zero": True,
                }
            elif name != "construction":
                payload["hard_integrity"] = hard_zero
                payload["hard_integrity_zero"] = True
            record.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )
            has_separate_artifact = name not in {"construction", "throughput"}
            cells.append(
                {
                    "name": name,
                    "kind": name,
                    "record": str(record),
                    "record_sha256": sha(record),
                    "artifact": str(record) if has_separate_artifact else None,
                    "artifact_sha256": sha(record) if has_separate_artifact else None,
                }
            )

        construction_gate = qualification_root / "CONSTRUCTION_GATE.json"
        construction_gate.write_text("{}\n", encoding="utf-8")
        baseline = qualification_root / "THROUGHPUT_BASELINE.json"
        baseline.write_text("{}\n", encoding="utf-8")
        baseline_cell = qualification_root / "throughput-baseline.json"
        baseline_cell.write_text("{}\n", encoding="utf-8")
        qualification = qualification_root / "QUALIFICATION.json"
        payload = {
            "schema_version": 3,
            "qualification_only": True,
            "accepted": True,
            "failed_gates": [],
            "mandatory_gates": list(self.a.MANDATORY_QUALIFICATION_GATES),
            "gates": {
                name: {"accepted": True}
                for name in self.a.MANDATORY_QUALIFICATION_GATES
            },
            "runner_source_commit": commit,
            "runner_sha256": "a" * 64,
            "candidate_source": {
                "role": "candidate",
                "source_root": str(source),
                "source_commit": commit,
                "puffer_root": str(puffer),
                "installer_check_sha256": "c" * 64,
            },
            "expected_candidate": {
                "source_commit": commit,
                "module_sha256": identity["module_sha256"],
                "backend_sha256": identity["backend_sources_sha256"],
                "environment_sha256": identity["environment_sha256"],
            },
            "identity": identity,
            "construction_gate": {
                "path": str(construction_gate),
                "sha256": sha(construction_gate),
            },
            "throughput_baseline": {
                "path": str(baseline),
                "sha256": sha(baseline),
                "cell_record": str(baseline_cell),
                "cell_record_sha256": sha(baseline_cell),
            },
            "cells": cells,
        }
        qualification.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return source, runner, commit, tree, qualification, runtime

    def test_accepted_qualification_is_recomputed_and_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, runner, commit, tree, qualification, runtime = self.make_qualification(
                Path(tmp).resolve()
            )
            with mock.patch.object(self.a, "_run_qualification_validator"):
                observed = self.a.validate_qualification(
                    qualification,
                    source_root=source,
                    qualification_runner_root=runner,
                )
            self.assertEqual(observed["source"]["commit"], commit)
            self.assertEqual(observed["source"]["tree"], tree)
            self.assertEqual(observed["qualification"]["sha256"], sha(qualification))
            self.assertEqual(observed["cuda_runtime"], runtime)
            self.assertEqual(observed["hard_integrity_keys"], list(self.a.HARD_INTEGRITY_KEYS))

    def test_fresh_validator_runs_from_distinct_bound_runner_with_candidate_python(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            candidate = root / "candidate"
            runner = root / "qualification-runner"
            qualification = root / "QUALIFICATION.json"
            marker = root / "validator-ran"
            python = candidate / "vendor" / "PufferLib" / ".venv" / "bin" / "python"
            validator = runner / "tools" / "qualify_recurrent_cuda.py"
            python.parent.mkdir(parents=True)
            validator.parent.mkdir(parents=True)
            qualification.write_text("{}\n", encoding="utf-8")
            python.symlink_to(Path(sys.executable).resolve())
            validator.write_text(
                "import pathlib, sys\n"
                f"assert pathlib.Path.cwd() == pathlib.Path({str(runner)!r})\n"
                "assert sys.argv[1] == 'validate'\n"
                f"assert pathlib.Path(sys.argv[2]) == pathlib.Path({str(qualification)!r})\n"
                f"pathlib.Path({str(marker)!r}).write_text('accepted\\n')\n",
                encoding="utf-8",
            )
            self.a._run_qualification_validator(
                qualification,
                source_root=candidate,
                qualification_runner_root=runner,
            )
            self.assertEqual(marker.read_text(encoding="utf-8"), "accepted\n")

            same = root / "same"
            same.mkdir()
            source, _, _, _, produced, _ = self.make_qualification(same)
            with self.assertRaisesRegex(
                self.a.AuthorityError, "runner and candidate.*must differ"
            ):
                self.a.validate_qualification(
                    produced,
                    source_root=source,
                    qualification_runner_root=source,
                )

    def test_every_qualification_identity_or_zero_budget_drift_rejects(self):
        mutations = {
            "schema": lambda p: p.__setitem__("schema_version", 2),
            "accepted": lambda p: p.__setitem__("accepted", False),
            "failed_gate": lambda p: p.__setitem__("failed_gates", ["ratio"]),
            "missing_gate": lambda p: p["gates"].pop("ratio"),
            "wrong_source": lambda p: p["candidate_source"].__setitem__(
                "source_commit", "0" * 40
            ),
            "wrong_module": lambda p: p["expected_candidate"].__setitem__(
                "module_sha256", "0" * 64
            ),
            "wrong_abi": lambda p: p["identity"].__setitem__(
                "action_abi", "marginal"
            ),
            "eligible_runtime": lambda p: p["identity"].__setitem__(
                "qualification_surface", False
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                source, runner, _, _, qualification, _ = self.make_qualification(
                    Path(tmp).resolve()
                )
                payload = json.loads(qualification.read_text(encoding="utf-8"))
                mutate(payload)
                qualification.write_text(
                    json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
                )
                with mock.patch.object(self.a, "_run_qualification_validator"), \
                        self.assertRaises(self.a.AuthorityError):
                    self.a.validate_qualification(
                        qualification,
                        source_root=source,
                        qualification_runner_root=runner,
                    )

        for cell_name in ("graph-off", "throughput"):
            for key in self.a.HARD_INTEGRITY_KEYS:
                with self.subTest(cell=cell_name, hard_integrity_key=key), \
                    tempfile.TemporaryDirectory() as tmp:
                    source, runner, _, _, qualification, _ = self.make_qualification(
                        Path(tmp).resolve()
                    )
                    payload = json.loads(
                        qualification.read_text(encoding="utf-8")
                    )
                    cell = next(
                        item for item in payload["cells"]
                        if item["name"] == cell_name
                    )
                    record_path = Path(cell["record"])
                    record = json.loads(record_path.read_text(encoding="utf-8"))
                    integrity = (
                        record["throughput"]
                        if cell_name == "throughput"
                        else record
                    )
                    integrity["hard_integrity"][key] = 1e-12
                    record_path.write_text(
                        json.dumps(record, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    cell["record_sha256"] = sha(record_path)
                    if cell["artifact"] is not None:
                        cell["artifact_sha256"] = sha(record_path)
                    qualification.write_text(
                        json.dumps(payload, sort_keys=True) + "\n",
                        encoding="utf-8",
                    )
                    with mock.patch.object(
                        self.a, "_run_qualification_validator"
                    ), self.assertRaisesRegex(
                        self.a.AuthorityError, f"hard-integrity.*{key}"
                    ):
                        self.a.validate_qualification(
                            qualification,
                            source_root=source,
                            qualification_runner_root=runner,
                        )

    def test_plan_output_requires_exact_regular_manifest_and_released_empty_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve() / "screen"
            output.mkdir()
            manifest = output / "SCREEN_MANIFEST.json"
            manifest.write_text("{}\n", encoding="utf-8")
            lock = output / ".screen.lock"
            lock.write_bytes(b"")
            inventory = self.a.validate_plan_output(output)
            self.assertEqual(
                [entry["path"] for entry in inventory],
                [".screen.lock", "SCREEN_MANIFEST.json"],
            )
            self.assertEqual(inventory[0]["sha256"], hashlib.sha256(b"").hexdigest())

            extra = output / "unexpected"
            extra.write_text("no\n", encoding="utf-8")
            with self.assertRaises(self.a.AuthorityError):
                self.a.validate_plan_output(output)
            extra.unlink()

            fd = lock.open("rb")
            fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            try:
                with self.assertRaisesRegex(self.a.AuthorityError, "held"):
                    self.a.validate_plan_output(output)
            finally:
                fd.close()

            lock.unlink()
            lock.symlink_to(manifest)
            with self.assertRaisesRegex(self.a.AuthorityError, "regular"):
                self.a.validate_plan_output(output)

    def test_cli_does_not_normalize_relative_authority_paths(self):
        with self.assertRaisesRegex(self.a.AuthorityError, "exact absolute"):
            self.a.main(
                [
                    "validate-qualification",
                    "relative/QUALIFICATION.json",
                    "--source-root",
                    "relative/candidate",
                    "--qualification-runner-root",
                    "relative/qualification-runner",
                ]
            )

    def test_systemd_unit_is_one_shot_disabled_contract_with_double_escaping(self):
        paths = self.a.UnitPaths(
            source_root=Path("/work/candidate"),
            qualification_runner_root=Path("/work/qualification-runner"),
            qualification=Path("/evidence/qualification/QUALIFICATION.json"),
            output=Path("/evidence/canary"),
            launch_authorization=Path("/evidence/auth/CANARY_LAUNCH_AUTHORIZATION.json"),
            launch_authorization_sha=Path("/evidence/auth/CANARY_LAUNCH_AUTHORIZATION.sha256"),
        )
        unit = self.a.render_systemd_unit(paths)
        self.assertIn("Type=oneshot", unit)
        self.assertIn("Restart=no", unit)
        self.assertIn("KillMode=control-group", unit)
        self.assertIn("TimeoutStartSec=7200", unit)
        self.assertIn("ARM_DETACH=0", unit)
        self.assertIn("PLAN_ONLY=0", unit)
        self.assertIn("STEPS=50000000", unit)
        self.assertIn("POLL_SECONDS=30", unit)
        self.assertIn("/usr/bin/env -u WARM -u POOL", unit)
        self.assertIn('$$(/usr/local/bin/nvidia-smi', unit)
        self.assertIn('/usr/bin/printf "%%s" "$${out}"', unit)
        self.assertNotIn('/usr/bin/printf "%s" "$${out}"', unit)
        self.assertNotIn("Restart=always", unit)
        self.assertNotIn("WantedBy=", unit)

        consumption = (
            paths.launch_authorization.parent
            / "CANARY_LAUNCH_CONSUMPTION.json"
        )
        consumption_sha = consumption.with_suffix(".sha256")
        prestarts = [
            line for line in unit.splitlines() if line.startswith("ExecStartPre=")
        ]
        self.assertEqual(len(prestarts), 3)
        self.assertIn(" consume-launch ", prestarts[0])
        self.assertIn(
            f"--authorization {paths.launch_authorization}", prestarts[0]
        )
        self.assertIn(f"--sha256-file {paths.launch_authorization_sha}", prestarts[0])
        self.assertIn(f"--destination {consumption}", prestarts[0])
        self.assertIn("qualify_recurrent_cuda.py validate", prestarts[1])
        self.assertIn("nvidia-smi --query-compute-apps", prestarts[2])
        execstart = next(
            line for line in unit.splitlines() if line.startswith("ExecStart=")
        )
        self.assertIn(f"CANARY_LAUNCH_CONSUMPTION={consumption}", execstart)
        self.assertIn(
            f"CANARY_LAUNCH_CONSUMPTION_SHA256_FILE={consumption_sha}",
            execstart,
        )

    def test_launch_authorization_consumption_is_atomic_and_exactly_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            launch = root / "CANARY_LAUNCH_AUTHORIZATION.json"
            launch.write_text("{}\n", encoding="utf-8")
            launch_sha = launch.with_suffix(".sha256")
            launch_digest = sha(launch)
            launch_sha.write_text(
                f"{launch_digest}  {launch.name}\n", encoding="ascii"
            )
            output = root / "authorized-screen"
            consumption = root / "CANARY_LAUNCH_CONSUMPTION.json"
            accepted = {
                "kind": self.a.LAUNCH_KIND,
                "authorization_sha256": launch_digest,
                "qualification_only": True,
                "plan_output": {"path": str(output)},
                "systemd": {"maximum_starts": 1},
            }
            with mock.patch.object(
                self.a, "validate_launch_authorization", return_value=accepted
            ) as validate:
                digest = self.a.consume_launch_authorization(
                    authorization=launch,
                    sha256_file=launch_sha,
                    destination=consumption,
                )
                validate.assert_called_once_with(
                    launch, sha256_file=launch_sha
                )
            before = consumption.read_bytes()
            payload = json.loads(before)
            self.assertEqual(digest, sha(consumption))
            self.assertEqual(
                payload["kind"], "exact_action_canary_launch_consumption"
            )
            self.assertEqual(payload["launch_authorization"]["path"], str(launch))
            self.assertEqual(
                payload["launch_authorization"]["sha256"], launch_digest
            )
            self.assertEqual(payload["plan_output"], str(output))
            self.assertEqual(payload["attempt"], 1)
            self.assertEqual(payload["maximum_starts"], 1)
            self.assertTrue(consumption.with_suffix(".sha256").is_file())
            with mock.patch.object(
                self.a, "validate_launch_authorization", return_value=accepted
            ):
                validated = self.a.validate_launch_consumption(
                    consumption,
                    consumption_sha256_file=consumption.with_suffix(".sha256"),
                    authorization=launch,
                    authorization_sha256_file=launch_sha,
                )
            self.assertEqual(
                validated["launch_consumption"]["sha256"], sha(consumption)
            )

            with mock.patch.object(
                self.a, "validate_launch_authorization", return_value=accepted
            ), self.assertRaisesRegex(self.a.AuthorityError, "already|consum"):
                self.a.consume_launch_authorization(
                    authorization=launch,
                    sha256_file=launch_sha,
                    destination=consumption,
                )
            self.assertEqual(consumption.read_bytes(), before)

    def test_concurrent_launch_consumers_leave_exactly_one_intact_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            launch = root / "CANARY_LAUNCH_AUTHORIZATION.json"
            launch.write_text("{}\n", encoding="utf-8")
            launch_sha = launch.with_suffix(".sha256")
            launch_digest = sha(launch)
            launch_sha.write_text(
                f"{launch_digest}  {launch.name}\n", encoding="ascii"
            )
            consumption = root / "CANARY_LAUNCH_CONSUMPTION.json"
            accepted = {
                "kind": self.a.LAUNCH_KIND,
                "authorization_sha256": launch_digest,
                "qualification_only": True,
                "plan_output": {"path": str(root / "authorized-screen")},
                "systemd": {"maximum_starts": 1},
            }
            barrier = threading.Barrier(2)

            def validate(*args, **kwargs):
                barrier.wait(timeout=5)
                return accepted

            outcomes = []

            def consume():
                try:
                    outcomes.append((
                        "success", self.a.consume_launch_authorization(
                            authorization=launch,
                            sha256_file=launch_sha,
                            destination=consumption,
                        )
                    ))
                except BaseException as exc:
                    outcomes.append(("error", type(exc), str(exc)))

            with mock.patch.object(
                self.a, "validate_launch_authorization", side_effect=validate
            ):
                threads = [threading.Thread(target=consume) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(outcomes), 2)
            successes = [item for item in outcomes if item[0] == "success"]
            errors = [item for item in outcomes if item[0] == "error"]
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(errors), 1)
            self.assertIs(errors[0][1], self.a.AuthorityError)
            self.assertTrue(consumption.is_file())
            self.assertEqual(sha(consumption), successes[0][1])
            self.assertTrue(consumption.with_suffix(".sha256").is_file())
            with mock.patch.object(
                self.a, "validate_launch_authorization", return_value=accepted
            ):
                observed = self.a.validate_launch_consumption(
                    consumption,
                    consumption_sha256_file=consumption.with_suffix(".sha256"),
                    authorization=launch,
                    authorization_sha256_file=launch_sha,
                )
            self.assertEqual(
                observed["launch_consumption"]["sha256"], successes[0][1]
            )

    def test_launch_consumption_survives_post_publish_durability_failures(self):
        def fail_directory_fsync(real_fsync):
            def fsync(fd):
                if stat.S_ISDIR(self.a.os.fstat(fd).st_mode):
                    raise OSError("forced directory fsync failure")
                return real_fsync(fd)

            return fsync

        for failure in ("directory_open", "directory_fsync"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                launch = root / "CANARY_LAUNCH_AUTHORIZATION.json"
                launch.write_text("{}\n", encoding="utf-8")
                launch_sha = launch.with_suffix(".sha256")
                launch_digest = sha(launch)
                launch_sha.write_text(
                    f"{launch_digest}  {launch.name}\n", encoding="ascii"
                )
                consumption = root / "CANARY_LAUNCH_CONSUMPTION.json"
                accepted = {
                    "kind": self.a.LAUNCH_KIND,
                    "authorization_sha256": launch_digest,
                    "qualification_only": True,
                    "plan_output": {"path": str(root / "authorized-screen")},
                    "systemd": {"maximum_starts": 1},
                }
                if failure == "directory_open":
                    durability_failure = mock.patch.object(
                        self.a.os,
                        "open",
                        side_effect=OSError("forced directory open failure"),
                    )
                else:
                    durability_failure = mock.patch.object(
                        self.a.os,
                        "fsync",
                        side_effect=fail_directory_fsync(self.a.os.fsync),
                    )

                with mock.patch.object(
                    self.a, "validate_launch_authorization", return_value=accepted
                ), durability_failure, self.assertRaisesRegex(
                    self.a.AuthorityError, "cannot publish authority atomically"
                ):
                    self.a.consume_launch_authorization(
                        authorization=launch,
                        sha256_file=launch_sha,
                        destination=consumption,
                    )

                self.assertTrue(consumption.is_file())
                self.assertTrue(consumption.with_suffix(".sha256").is_file())
                with mock.patch.object(
                    self.a, "validate_launch_authorization", return_value=accepted
                ), self.assertRaisesRegex(
                    self.a.AuthorityError, "already consumed"
                ):
                    self.a.consume_launch_authorization(
                        authorization=launch,
                        sha256_file=launch_sha,
                        destination=consumption,
                    )

    def test_authority_files_use_exclusive_atomic_creation(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp).resolve() / "AUTH.json"
            payload = {"schema_version": 1, "kind": "test"}
            digest = self.a.write_authority(destination, payload)
            self.assertEqual(digest, sha(destination))
            self.assertEqual(
                (destination.with_suffix(".sha256")).read_text(encoding="ascii"),
                f"{digest}  {destination.name}\n",
            )
            before = destination.read_bytes()
            with self.assertRaisesRegex(self.a.AuthorityError, "already exists"):
                self.a.write_authority(destination, payload)
            self.assertEqual(destination.read_bytes(), before)

    def test_concurrent_unit_publishers_leave_exactly_one_intact_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            source = root / "candidate"
            runner = root / "runner"
            output = root / "plan-output"
            authority_root = root / "authority"
            for directory in (source, runner, output, authority_root):
                directory.mkdir()
            qualification = root / "QUALIFICATION.json"
            qualification.write_text("{}\n", encoding="utf-8")
            launch = authority_root / "CANARY_LAUNCH_AUTHORIZATION.json"
            paths = self.a.UnitPaths(
                source_root=source,
                qualification_runner_root=runner,
                qualification=qualification,
                output=output,
                launch_authorization=launch,
                launch_authorization_sha=launch.with_suffix(".sha256"),
            )
            destination = authority_root / self.a.CANARY_UNIT_NAME
            barrier = threading.Barrier(2)

            def token_hex(_):
                barrier.wait(timeout=5)
                return f"{threading.get_ident():016x}"[-16:]

            outcomes = []

            def publish():
                try:
                    outcomes.append(("success", self.a.write_unit(destination, paths)))
                except BaseException as exc:
                    outcomes.append(("error", type(exc), str(exc)))

            with mock.patch.object(
                self.a.secrets, "token_hex", side_effect=token_hex
            ):
                threads = [threading.Thread(target=publish) for _ in range(2)]
                for thread in threads:
                    thread.start()
                for thread in threads:
                    thread.join(timeout=10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
            self.assertEqual(len(outcomes), 2)
            successes = [item for item in outcomes if item[0] == "success"]
            errors = [item for item in outcomes if item[0] == "error"]
            self.assertEqual(len(successes), 1)
            self.assertEqual(len(errors), 1)
            self.assertIs(errors[0][1], self.a.AuthorityError)
            self.assertTrue(destination.is_file())
            self.assertEqual(
                sha(destination),
                successes[0][1],
            )
            self.assertEqual(destination.read_text(encoding="utf-8"), self.a.render_systemd_unit(paths))

    def make_plan_prerequisites(self, temp: Path):
        source, runner, commit, tree, qualification, runtime = self.make_qualification(temp)
        recovery_verification, recovery_inventory = self.make_recovery_evidence(temp)
        predecessor = qualification.parent
        authority_root = temp / "authority"
        authority_root.mkdir()
        screen_output = temp / "exact-action-canary-50m-s42-v4"
        plan_authorization = authority_root / "CANARY_PLAN_AUTHORIZATION.json"
        return {
            "source": source,
            "qualification_runner": runner,
            "commit": commit,
            "tree": tree,
            "qualification": qualification,
            "runtime": runtime,
            "recovery_verification": recovery_verification,
            "recovery_inventory": recovery_inventory,
            "predecessor": predecessor,
            "authority_root": authority_root,
            "screen_output": screen_output,
            "plan_authorization": plan_authorization,
            "plan_authorization_sha": plan_authorization.with_suffix(".sha256"),
        }

    def make_recovery_evidence(self, temp: Path) -> tuple[Path, Path]:
        queue_id = self.a.EXPECTED_RECOVERY_QUEUE_ID
        queue_dir = f"runs/{queue_id}"
        records = []

        def add(relative: str, *, size: int = 1, digest: str | None = None):
            records.append(
                {
                    "path": relative,
                    "bytes": size,
                    "mode": 0o644,
                    "sha256": digest
                    or hashlib.sha256(relative.encode("utf-8")).hexdigest(),
                }
            )

        add(
            f"{queue_dir}/QUEUE_PLAN.json",
            digest=self.a.EXPECTED_RECOVERY_PLAN_SHA256,
        )
        add(f"{queue_dir}/QUEUE_STATE.json")
        add(f"{queue_dir}/work/full-control/SCREEN_COMPLETE.json")
        selection = "runs/bbtv-follow/selection.json"
        add(selection)
        bindings = []
        for seed in (42, 43, 44):
            prefix = f"{queue_dir}/work/full-control/recovery-both-s{seed}"
            result = f"{prefix}.result.json"
            log = f"{prefix}.log"
            checkpoint = f"vendor/PufferLib/checkpoints/bloodbowl/{seed}/model.bin"
            run_manifest = (
                f"vendor/PufferLib/checkpoints/bloodbowl/{seed}/RUN_MANIFEST.json"
            )
            add(result)
            add(log)
            add(checkpoint, size=16_066_560)
            add(run_manifest)
            by_path = {record["path"]: record for record in records}
            bindings.append(
                {
                    "seed": seed,
                    "result": result,
                    "result_sha256": by_path[result]["sha256"],
                    "log": log,
                    "log_sha256": by_path[log]["sha256"],
                    "checkpoint": checkpoint,
                    "checkpoint_bytes": by_path[checkpoint]["bytes"],
                    "checkpoint_sha256": by_path[checkpoint]["sha256"],
                    "run_manifest": run_manifest,
                    "run_manifest_sha256": by_path[run_manifest]["sha256"],
                }
            )
        records.sort(key=lambda record: record["path"])
        by_path = {record["path"]: record for record in records}
        inventory_identity = self.a.recovery_preservation.canonical_hash(records)
        inventory_payload = {
            "schema_version": 1,
            "kind": self.a.recovery_preservation.KIND,
            "generated_utc": "2026-07-22T12:32:40+00:00",
            "source_recovery_root": self.a.EXPECTED_RECOVERY_ROOT,
            "queue_dir": queue_dir,
            "queue_id": queue_id,
            "queue_plan_sha256": self.a.EXPECTED_RECOVERY_PLAN_SHA256,
            "queue_state_sha256": by_path[f"{queue_dir}/QUEUE_STATE.json"][
                "sha256"
            ],
            "screen_complete_sha256": by_path[
                f"{queue_dir}/work/full-control/SCREEN_COMPLETE.json"
            ]["sha256"],
            "bbtv_selection": selection,
            "bbtv_selection_sha256": by_path[selection]["sha256"],
            "result_bindings": bindings,
            "files": records,
            "file_count": len(records),
            "total_bytes": sum(record["bytes"] for record in records),
            "inventory_sha256": inventory_identity,
        }
        inventory = temp / "recovery-inventory.json"
        inventory.write_text(
            json.dumps(inventory_payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        verification_payload = {
            "accepted": True,
            "file_count": inventory_payload["file_count"],
            "total_bytes": inventory_payload["total_bytes"],
            "inventory_sha256": inventory_identity,
        }
        verification = temp / "gate6-verifier.stdout"
        verification.write_text(
            json.dumps(verification_payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return verification, inventory

    def authority_evidence(self, paths):
        manifest = json.loads(paths["recovery_inventory"].read_text(encoding="utf-8"))
        stack = contextlib.ExitStack()
        stack.enter_context(
            mock.patch.object(self.a, "_run_qualification_validator")
        )
        stack.enter_context(
            mock.patch.multiple(
                self.a,
                EXPECTED_RECOVERY_VERIFICATION_SHA256=sha(
                    paths["recovery_verification"]
                ),
                EXPECTED_RECOVERY_INVENTORY_FILE_SHA256=sha(
                    paths["recovery_inventory"]
                ),
                EXPECTED_RECOVERY_INVENTORY_IDENTITY=manifest[
                    "inventory_sha256"
                ],
                EXPECTED_RECOVERY_FILE_COUNT=manifest["file_count"],
                EXPECTED_RECOVERY_TOTAL_BYTES=manifest["total_bytes"],
            )
        )
        return stack

    def test_plan_authorization_freezes_and_revalidates_current_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_plan_prerequisites(Path(tmp).resolve())
            with self.authority_evidence(paths):
                digest = self.a.freeze_plan_authorization(
                    destination=paths["plan_authorization"],
                    qualification=paths["qualification"],
                    source_root=paths["source"],
                    qualification_runner_root=paths["qualification_runner"],
                    screen_output=paths["screen_output"],
                    recovery_verification=paths["recovery_verification"],
                    recovery_inventory=paths["recovery_inventory"],
                    predecessor_root=paths["predecessor"],
                )
                observed = self.a.validate_plan_authorization(
                    paths["plan_authorization"],
                    sha256_file=paths["plan_authorization_sha"],
                    source_root=paths["source"],
                    require_output_absent=True,
                )
            self.assertEqual(digest, sha(paths["plan_authorization"]))
            self.assertEqual(observed["kind"], self.a.PLAN_KIND)
            self.assertEqual(observed["source"]["commit"], paths["commit"])
            self.assertEqual(
                observed["screen"]["output"], str(paths["screen_output"])
            )
            self.assertEqual(
                observed["cuda_runtime"]["library"]["sha256"],
                paths["runtime"]["library"]["sha256"],
            )
            self.assertFalse(paths["screen_output"].exists())

            paths["recovery_verification"].write_text(
                "{\"accepted\":false}\n", encoding="utf-8"
            )
            with self.authority_evidence(paths), \
                    self.assertRaisesRegex(self.a.AuthorityError, "recovery"):
                self.a.validate_plan_authorization(
                    paths["plan_authorization"],
                    sha256_file=paths["plan_authorization_sha"],
                    source_root=paths["source"],
                    require_output_absent=True,
                )

    def test_plan_authorization_rejects_unstructured_recovery_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_plan_prerequisites(Path(tmp).resolve())
            paths["recovery_verification"].write_text(
                "{\"accepted\":true}\n", encoding="utf-8"
            )
            with self.authority_evidence(paths), \
                    self.assertRaisesRegex(
                        self.a.AuthorityError, "recovery preservation"
                    ):
                self.a.freeze_plan_authorization(
                    destination=paths["plan_authorization"],
                    qualification=paths["qualification"],
                    source_root=paths["source"],
                    qualification_runner_root=paths["qualification_runner"],
                    screen_output=paths["screen_output"],
                    recovery_verification=paths["recovery_verification"],
                    recovery_inventory=paths["recovery_inventory"],
                    predecessor_root=paths["predecessor"],
                )

    def test_plan_authorization_rejects_structured_recovery_mismatches(self):
        mutations = {
            "verifier_file_count": lambda verdict, manifest: verdict.__setitem__(
                "file_count", manifest["file_count"] + 1
            ),
            "verifier_total_bytes": lambda verdict, manifest: verdict.__setitem__(
                "total_bytes", manifest["total_bytes"] + 1
            ),
            "verifier_inventory": lambda verdict, manifest: verdict.__setitem__(
                "inventory_sha256", "0" * 64
            ),
            "inventory_queue_id": lambda verdict, manifest: manifest.__setitem__(
                "queue_id", "structured-but-wrong-queue"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                paths = self.make_plan_prerequisites(Path(tmp).resolve())
                verdict = json.loads(
                    paths["recovery_verification"].read_text(encoding="utf-8")
                )
                manifest = json.loads(
                    paths["recovery_inventory"].read_text(encoding="utf-8")
                )
                mutate(verdict, manifest)
                paths["recovery_verification"].write_text(
                    json.dumps(verdict, sort_keys=True) + "\n", encoding="utf-8"
                )
                paths["recovery_inventory"].write_text(
                    json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
                with self.authority_evidence(paths), self.assertRaisesRegex(
                    self.a.AuthorityError, "recovery preservation"
                ):
                    self.a.freeze_plan_authorization(
                        destination=paths["plan_authorization"],
                        qualification=paths["qualification"],
                        source_root=paths["source"],
                        qualification_runner_root=paths["qualification_runner"],
                        screen_output=paths["screen_output"],
                        recovery_verification=paths["recovery_verification"],
                        recovery_inventory=paths["recovery_inventory"],
                        predecessor_root=paths["predecessor"],
                    )

    def write_plan_output(self, paths):
        output = paths["screen_output"]
        output.mkdir()
        plan_sha = sha(paths["plan_authorization"])
        contract = {
            "screen_profile": "exact-action-canary",
            "qualification_only": True,
            "bootstrap": {
                "mode": "fresh-v5-qualification",
                "observation_abi": "obs-v5",
                "observation_version": 5,
                "action_abi": "exact-joint-v1",
                "initialization": "fresh",
                "warm_lineage_sha256": "",
                "pool_lineage_bundle_sha256": "",
            },
            "prefix": self.a.CANARY_PREFIX,
            "out_dir": str(output),
            "requested_steps": self.a.CANARY_STEPS,
            "final_steps": 49_938_432,
            "rollout_quantum": 131_072,
            "schedule": [{"index": 1, "arm": "both", "seed": 42}],
            "settings": {
                "minibatch_size": "16384",
                "arm_detach": "0",
                "num_frozen_banks": "0",
                "frozen_bank_pct": "0",
                "native_precision_bytes": "4",
            },
            "warm": None,
            "pool": None,
            "error_budget": {
                "contamination_budget": 0,
                "detection_poll_seconds": 30,
                "max_panel_silence_seconds": 180,
                "hard_integrity_keys": list(self.a.HARD_INTEGRITY_KEYS),
            },
            "canary_authority": {
                "plan_authorization": str(paths["plan_authorization"]),
                "plan_authorization_sha256": plan_sha,
                "qualification": str(paths["qualification"]),
                "qualification_sha256": sha(paths["qualification"]),
                "cuda_runtime_library_path": paths["runtime"]["library"][
                    "resolved_path"
                ],
                "cuda_runtime_library_sha256": paths["runtime"]["library"][
                    "sha256"
                ],
                "cuda_runtime_device_count": 1,
            },
        }
        (output / "SCREEN_MANIFEST.json").write_text(
            json.dumps(
                {"schema_version": 1, "contract": contract},
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        (output / ".screen.lock").write_bytes(b"")

    def freeze_plan(self, paths):
        with self.authority_evidence(paths):
            return self.a.freeze_plan_authorization(
                destination=paths["plan_authorization"],
                qualification=paths["qualification"],
                source_root=paths["source"],
                qualification_runner_root=paths["qualification_runner"],
                screen_output=paths["screen_output"],
                recovery_verification=paths["recovery_verification"],
                recovery_inventory=paths["recovery_inventory"],
                predecessor_root=paths["predecessor"],
            )

    def make_frozen_launch(self, temp: Path):
        paths = self.make_plan_prerequisites(temp)
        self.freeze_plan(paths)
        self.write_plan_output(paths)
        stopped = paths["authority_root"] / "stopped-validation"
        stopped.mkdir()
        launch = paths["authority_root"] / "CANARY_LAUNCH_AUTHORIZATION.json"
        launch_sha = launch.with_suffix(".sha256")
        unit = paths["authority_root"] / self.a.CANARY_UNIT_NAME
        self.a.write_unit(
            unit,
            self.a.UnitPaths(
                source_root=paths["source"],
                qualification_runner_root=paths["qualification_runner"],
                qualification=paths["qualification"],
                output=paths["screen_output"],
                launch_authorization=launch,
                launch_authorization_sha=launch_sha,
            ),
        )
        with self.authority_evidence(paths):
            self.a.freeze_launch_authorization(
                destination=launch,
                plan_authorization=paths["plan_authorization"],
                plan_sha256_file=paths["plan_authorization_sha"],
                source_root=paths["source"],
                unit=unit,
                stopped_validation_output=stopped,
            )
        paths.update({
            "stopped": stopped,
            "launch": launch,
            "launch_sha": launch_sha,
            "unit": unit,
        })
        return paths

    def test_frozen_launch_is_consumed_and_revalidated_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_frozen_launch(Path(tmp).resolve())
            consumption = paths["launch"].with_name(
                self.a.CANARY_LAUNCH_CONSUMPTION_NAME
            )
            with self.authority_evidence(paths):
                digest = self.a.consume_launch_authorization(
                    authorization=paths["launch"],
                    sha256_file=paths["launch_sha"],
                    destination=consumption,
                )
                observed = self.a.validate_launch_consumption(
                    consumption,
                    consumption_sha256_file=consumption.with_suffix(".sha256"),
                    authorization=paths["launch"],
                    authorization_sha256_file=paths["launch_sha"],
                )
            self.assertEqual(digest, sha(consumption))
            self.assertEqual(
                observed["launch_consumption"]["sha256"], digest
            )
            self.assertEqual(
                observed["plan_output"]["path"], str(paths["screen_output"])
            )
            with self.authority_evidence(paths), self.assertRaisesRegex(
                self.a.AuthorityError, "already consumed"
            ):
                self.a.consume_launch_authorization(
                    authorization=paths["launch"],
                    sha256_file=paths["launch_sha"],
                    destination=consumption,
                )

    def test_frozen_plan_rejects_current_dependency_drift(self):
        def qualification_drift(paths):
            paths["qualification"].write_bytes(
                paths["qualification"].read_bytes() + b"\n"
            )

        def module_drift(paths):
            qualification = json.loads(
                paths["qualification"].read_text(encoding="utf-8")
            )
            Path(qualification["identity"]["module"]).write_bytes(b"drifted")

        def cudart_drift(paths):
            Path(paths["runtime"]["library"]["resolved_path"]).write_bytes(
                b"drifted"
            )

        def source_drift(paths):
            (paths["source"] / "tracked.txt").write_text(
                "drifted\n", encoding="utf-8"
            )

        def sidecar_drift(paths):
            paths["plan_authorization_sha"].write_text(
                f"{'0' * 64}  {paths['plan_authorization'].name}\n",
                encoding="ascii",
            )

        mutations = {
            "qualification": qualification_drift,
            "compiled_module": module_drift,
            "cudart": cudart_drift,
            "tracked_source": source_drift,
            "plan_digest_sidecar": sidecar_drift,
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                paths = self.make_plan_prerequisites(Path(tmp).resolve())
                self.freeze_plan(paths)
                mutate(paths)
                with self.authority_evidence(paths), self.assertRaises(
                    self.a.AuthorityError
                ):
                    self.a.validate_plan_authorization(
                        paths["plan_authorization"],
                        sha256_file=paths["plan_authorization_sha"],
                        source_root=paths["source"],
                        require_output_absent=True,
                    )

    def test_plan_and_launch_validation_reject_relative_authority_references(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_plan_prerequisites(Path(tmp).resolve())
            self.freeze_plan(paths)
            with self.assertRaisesRegex(self.a.AuthorityError, "exact absolute"):
                self.a.validate_plan_authorization(
                    Path("relative/CANARY_PLAN_AUTHORIZATION.json"),
                    sha256_file=paths["plan_authorization_sha"],
                    source_root=paths["source"],
                    require_output_absent=True,
                )

        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_frozen_launch(Path(tmp).resolve())
            with self.assertRaisesRegex(self.a.AuthorityError, "exact absolute"):
                self.a.validate_launch_authorization(
                    Path("relative/CANARY_LAUNCH_AUTHORIZATION.json"),
                    sha256_file=paths["launch_sha"],
                )

    def test_frozen_launch_rejects_plan_output_authority_and_unit_drift(self):
        def manifest_drift(paths):
            manifest = paths["screen_output"] / "SCREEN_MANIFEST.json"
            manifest.write_bytes(manifest.read_bytes() + b"\n")

        def lock_drift(paths):
            (paths["screen_output"] / ".screen.lock").write_bytes(b"not empty")

        def plan_authority_drift(paths):
            payload = json.loads(
                paths["plan_authorization"].read_text(encoding="utf-8")
            )
            payload["created_utc"] = "2099-01-01T00:00:00+00:00"
            paths["plan_authorization"].write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            digest = sha(paths["plan_authorization"])
            paths["plan_authorization_sha"].write_text(
                f"{digest}  {paths['plan_authorization'].name}\n",
                encoding="ascii",
            )

        def unit_drift(paths):
            paths["unit"].write_bytes(paths["unit"].read_bytes() + b"\n")

        mutations = {
            "screen_manifest": manifest_drift,
            "screen_lock": lock_drift,
            "plan_authority": plan_authority_drift,
            "canonical_unit": unit_drift,
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                paths = self.make_frozen_launch(Path(tmp).resolve())
                mutate(paths)
                with self.authority_evidence(paths), self.assertRaises(
                    self.a.AuthorityError
                ):
                    self.a.validate_launch_authorization(
                        paths["launch"], sha256_file=paths["launch_sha"]
                    )

        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_frozen_launch(Path(tmp).resolve())
            lock = paths["screen_output"] / ".screen.lock"
            with lock.open("rb") as handle:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                with self.authority_evidence(paths), self.assertRaisesRegex(
                    self.a.AuthorityError, "held"
                ):
                    self.a.validate_launch_authorization(
                        paths["launch"], sha256_file=paths["launch_sha"]
                    )

        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_frozen_launch(Path(tmp).resolve())
            launch = json.loads(paths["launch"].read_text(encoding="utf-8"))
            launch["plan_authorization"]["path"] = "relative/PLAN.json"
            paths["launch"].write_text(
                json.dumps(launch, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            launch_digest = sha(paths["launch"])
            paths["launch_sha"].write_text(
                f"{launch_digest}  {paths['launch'].name}\n", encoding="ascii"
            )
            with self.assertRaisesRegex(self.a.AuthorityError, "exact absolute"):
                self.a.validate_launch_authorization(
                    paths["launch"], sha256_file=paths["launch_sha"]
                )

    def test_launch_authorization_binds_plan_unit_and_empty_stopped_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_plan_prerequisites(Path(tmp).resolve())
            with self.authority_evidence(paths):
                self.a.freeze_plan_authorization(
                    destination=paths["plan_authorization"],
                    qualification=paths["qualification"],
                    source_root=paths["source"],
                    qualification_runner_root=paths["qualification_runner"],
                    screen_output=paths["screen_output"],
                    recovery_verification=paths["recovery_verification"],
                    recovery_inventory=paths["recovery_inventory"],
                    predecessor_root=paths["predecessor"],
                )
            self.write_plan_output(paths)
            stopped = paths["authority_root"] / "stopped-validation"
            stopped.mkdir()
            launch = paths["authority_root"] / "CANARY_LAUNCH_AUTHORIZATION.json"
            launch_sha = launch.with_suffix(".sha256")
            unit_path = paths["authority_root"] / self.a.CANARY_UNIT_NAME
            unit_paths = self.a.UnitPaths(
                source_root=paths["source"],
                qualification_runner_root=paths["qualification_runner"],
                qualification=paths["qualification"],
                output=paths["screen_output"],
                launch_authorization=launch,
                launch_authorization_sha=launch_sha,
            )
            self.a.write_unit(unit_path, unit_paths)
            with self.authority_evidence(paths):
                digest = self.a.freeze_launch_authorization(
                    destination=launch,
                    plan_authorization=paths["plan_authorization"],
                    plan_sha256_file=paths["plan_authorization_sha"],
                    source_root=paths["source"],
                    unit=unit_path,
                    stopped_validation_output=stopped,
                )
                observed = self.a.validate_launch_authorization(
                    launch, sha256_file=launch_sha
                )
            self.assertEqual(digest, sha(launch))
            self.assertEqual(observed["kind"], self.a.LAUNCH_KIND)
            self.assertEqual(observed["unit"]["name"], self.a.CANARY_UNIT_NAME)
            self.assertEqual(observed["unit"]["sha256"], sha(unit_path))
            self.assertEqual(observed["plan_output"]["manifest_sha256"], sha(
                paths["screen_output"] / "SCREEN_MANIFEST.json"
            ))
            self.assertFalse(observed["eligibility"]["checkpoint_ancestry"])
            self.assertFalse(observed["eligibility"]["reward_evidence"])

            (stopped / "unexpected").write_text("no\n", encoding="utf-8")
            with self.authority_evidence(paths), \
                    self.assertRaisesRegex(self.a.AuthorityError, "stopped"):
                self.a.validate_launch_authorization(
                    launch, sha256_file=launch_sha
                )


if __name__ == "__main__":
    unittest.main()
