import contextlib
import fcntl
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
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
            if name != "construction":
                payload["hard_integrity"] = hard_zero
                payload["hard_integrity_zero"] = True
            record.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )
            cells.append(
                {
                    "name": name,
                    "kind": name,
                    "record": str(record),
                    "record_sha256": sha(record),
                    "artifact": str(record),
                    "artifact_sha256": sha(record),
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
        return source, commit, tree, qualification, runtime

    def test_accepted_qualification_is_recomputed_and_normalized(self):
        with tempfile.TemporaryDirectory() as tmp:
            source, commit, tree, qualification, runtime = self.make_qualification(
                Path(tmp).resolve()
            )
            with mock.patch.object(self.a, "_run_qualification_validator"):
                observed = self.a.validate_qualification(
                    qualification, source_root=source
                )
            self.assertEqual(observed["source"]["commit"], commit)
            self.assertEqual(observed["source"]["tree"], tree)
            self.assertEqual(observed["qualification"]["sha256"], sha(qualification))
            self.assertEqual(observed["cuda_runtime"], runtime)
            self.assertEqual(observed["hard_integrity_keys"], list(self.a.HARD_INTEGRITY_KEYS))

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
                source, _, _, qualification, _ = self.make_qualification(
                    Path(tmp).resolve()
                )
                payload = json.loads(qualification.read_text(encoding="utf-8"))
                mutate(payload)
                qualification.write_text(
                    json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
                )
                with mock.patch.object(self.a, "_run_qualification_validator"), \
                        self.assertRaises(self.a.AuthorityError):
                    self.a.validate_qualification(qualification, source_root=source)

        with tempfile.TemporaryDirectory() as tmp:
            source, _, _, qualification, _ = self.make_qualification(
                Path(tmp).resolve()
            )
            payload = json.loads(qualification.read_text(encoding="utf-8"))
            graph_record = Path(payload["cells"][1]["record"])
            graph = json.loads(graph_record.read_text(encoding="utf-8"))
            graph["hard_integrity"][self.a.HARD_INTEGRITY_KEYS[0]] = 1.0
            graph_record.write_text(
                json.dumps(graph, sort_keys=True) + "\n", encoding="utf-8"
            )
            payload["cells"][1]["record_sha256"] = sha(graph_record)
            payload["cells"][1]["artifact_sha256"] = sha(graph_record)
            qualification.write_text(
                json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8"
            )
            with mock.patch.object(self.a, "_run_qualification_validator"), \
                    self.assertRaisesRegex(self.a.AuthorityError, "hard-integrity"):
                self.a.validate_qualification(qualification, source_root=source)

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
                ]
            )

    def test_systemd_unit_is_one_shot_disabled_contract_with_double_escaping(self):
        paths = self.a.UnitPaths(
            source_root=Path("/work/candidate"),
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

    def make_plan_prerequisites(self, temp: Path):
        source, commit, tree, qualification, runtime = self.make_qualification(temp)
        recovery_verification, recovery_inventory = self.make_recovery_evidence(temp)
        predecessor = qualification.parent
        authority_root = temp / "authority"
        authority_root.mkdir()
        screen_output = temp / "exact-action-canary-50m-s42-v4"
        plan_authorization = authority_root / "CANARY_PLAN_AUTHORIZATION.json"
        return {
            "source": source,
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

    def test_launch_authorization_binds_plan_unit_and_empty_stopped_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self.make_plan_prerequisites(Path(tmp).resolve())
            with self.authority_evidence(paths):
                self.a.freeze_plan_authorization(
                    destination=paths["plan_authorization"],
                    qualification=paths["qualification"],
                    source_root=paths["source"],
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
