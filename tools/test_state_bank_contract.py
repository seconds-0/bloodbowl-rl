"""Watched-fail tests for the typed, hash-pinned state-bank shell contract.

These assertions intentionally exercise only interfaces that exist on the
pre-change base: the two shell entry points and their source text.  In
particular, they do not import the planned validator or name a future C API.
That makes a red result evidence of the current fail-open behavior rather than
an incidental compile/import failure.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import state_bank_contract as contract  # noqa: E402

LAUNCHER = ROOT / "tools" / "run_reward_ablation.sh"
INSTALLER = ROOT / "tools" / "install_puffer_env.sh"

BBS_HEADER = struct.Struct("<4sIII")
BBS_META = struct.Struct("<IIBB2s")


class StateBankContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.bank_path = self.directory / "bank.bbs"
        self.producer_path = self.directory / "producer.json"
        self.training_path = self.directory / "training.json"
        self.match_size = 4
        self.fingerprint = 0x12345678
        self.engine_hash = contract.engine_source_sha256(ROOT)
        self.producer_engine_hash = "a" * 64
        self.write_fixture()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def json_bytes(value: object) -> bytes:
        return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8"
        )

    @staticmethod
    def sha256(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()

    def write_fixture(
        self,
        *,
        source_id: int = 7,
        half: int = 1,
        turn: int = 1,
        padding: bytes = b"\0\0",
        producer_kind: str = "test-strict-fixture-v1",
        bank_payload: bytes | None = None,
    ) -> None:
        if bank_payload is None:
            bank_payload = BBS_HEADER.pack(
                b"BBS1", 1, self.match_size, self.fingerprint
            )
            bank_payload += BBS_META.pack(source_id, 11, half, turn, padding) + b"test"
        else:
            magic, version, self.match_size, self.fingerprint = BBS_HEADER.unpack_from(
                bank_payload
            )
            self.assertEqual(magic, b"BBS1")
            self.assertEqual(version, 1)
        self.bank_path.write_bytes(bank_payload)
        bank = {
            "sha256": self.sha256(bank_payload),
            "bytes": len(bank_payload),
            "records": 1,
            "format": {
                "magic": "BBS1",
                "version": 1,
                "match_size": self.match_size,
                "engine_fingerprint": f"0x{self.fingerprint:08x}",
            },
        }
        producer = {
            "schema": contract.PRODUCER_SCHEMA,
            "artifact_role": "training-bank",
            "bank_kind": "strict-replay",
            "ruleset": "BB2025",
            "training_eligible": True,
            "bank": copy.deepcopy(bank),
            "producer": {
                "kind": producer_kind,
                "producer_engine_source_sha256": self.producer_engine_hash,
            },
        }
        producer_payload = self.json_bytes(producer)
        self.producer_path.write_bytes(producer_payload)
        training = {
            "schema": contract.TRAINING_SCHEMA,
            "artifact_role": "training-bank",
            "bank_kind": "strict-replay",
            "ruleset": "BB2025",
            "training_eligible": True,
            "bank": copy.deepcopy(bank),
            "producer_manifest": {
                "sha256": self.sha256(producer_payload),
                "schema": contract.PRODUCER_SCHEMA,
                "producer_engine_source_sha256": self.producer_engine_hash,
            },
            "loader": {"engine_source_sha256": self.engine_hash},
            "authorization": {
                "schema": contract.AUTHORIZATION_SCHEMA,
                "decision": "unit-test decision; never production-authorized",
            },
        }
        self.training_path.write_bytes(self.json_bytes(training))

    def write_native_fixture(self) -> None:
        build = subprocess.run(
            ["make", "build/state_bank_fixture_writer"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=120,
        )
        self.assertEqual(build.returncode, 0, build.stdout)
        writer = ROOT / "build/state_bank_fixture_writer"
        result = subprocess.run(
            [str(writer), str(self.bank_path)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.write_fixture(bank_payload=self.bank_path.read_bytes())

    def request(self) -> dict[str, object]:
        return {
            "bank_path": self.bank_path,
            "bank_sha256": self.sha256(self.bank_path.read_bytes()),
            "producer_manifest_path": self.producer_path,
            "producer_manifest_sha256": self.sha256(self.producer_path.read_bytes()),
            "training_contract_path": self.training_path,
            "training_contract_sha256": self.sha256(self.training_path.read_bytes()),
            "kind": "strict-replay",
            "engine_root": ROOT,
        }

    def test_production_allowlist_is_literal_empty_and_complete_request_rejects(
        self,
    ) -> None:
        self.assertIsInstance(contract.PRODUCTION_AUTHORIZED_PRODUCER_KINDS, frozenset)
        self.assertEqual(contract.PRODUCTION_AUTHORIZED_PRODUCER_KINDS, frozenset())
        with self.assertRaisesRegex(
            contract.StateBankContractError, r"^NO_AUTHORIZED_PRODUCER:"
        ):
            contract.validate_artifact_request(**self.request())
        with mock.patch.object(
            contract,
            "PRODUCTION_AUTHORIZED_PRODUCER_KINDS",
            frozenset(("test-strict-fixture-v1",)),
        ):
            with self.assertRaisesRegex(
                contract.StateBankContractError,
                r"^NO_AUTHORIZED_PRODUCER:",
            ):
                contract.validate_artifact_request(**self.request())

    def test_installer_complete_request_reconciles_then_rejects_without_mutation(
        self,
    ) -> None:
        destination = self.directory / "not-a-puffer-tree"
        destination.mkdir()
        sentinel = destination / "sentinel"
        sentinel.write_bytes(b"unchanged")
        request = self.request()
        result = subprocess.run(
            [
                "bash",
                str(INSTALLER),
                "--state-bank-kind",
                "strict-replay",
                "--state-bank",
                str(self.bank_path),
                "--state-bank-sha256",
                str(request["bank_sha256"]),
                "--state-bank-producer-manifest",
                str(self.producer_path),
                "--state-bank-producer-manifest-sha256",
                str(request["producer_manifest_sha256"]),
                "--state-bank-contract",
                str(self.training_path),
                "--state-bank-contract-sha256",
                str(request["training_contract_sha256"]),
                str(destination),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("NO_AUTHORIZED_PRODUCER", result.stdout)
        self.assertNotIn("is not a PufferLib tree", result.stdout)
        self.assertEqual(sentinel.read_bytes(), b"unchanged")
        self.assertEqual(
            sorted(path.name for path in destination.iterdir()), ["sentinel"]
        )

    def test_all_three_external_hashes_are_lowercase_exact_and_enforced(
        self,
    ) -> None:
        for key in (
            "bank_sha256",
            "producer_manifest_sha256",
            "training_contract_sha256",
        ):
            with self.subTest(key=key):
                request = self.request()
                request[key] = "A" * 64
                with self.assertRaisesRegex(
                    contract.StateBankContractError, "SHA256_FORMAT"
                ):
                    contract.validate_artifact_request(**request)

                request[key] = "0" * 64
                with self.assertRaisesRegex(
                    contract.StateBankContractError,
                    "EXTERNAL_SHA256_MISMATCH",
                ):
                    contract.validate_artifact_request(**request)

    def test_duplicate_and_unknown_keys_fail_at_nested_levels(self) -> None:
        duplicate = b'{"schema":"x","schema":"y","artifact_role":"training-bank"}'
        with self.assertRaisesRegex(
            contract.StateBankContractError, "JSON_DUPLICATE_KEY"
        ):
            contract.parse_json_bytes(duplicate, "fixture")
        with self.assertRaisesRegex(
            contract.StateBankContractError, "JSON_DUPLICATE_KEY"
        ):
            contract.parse_json_bytes(
                b'{"outer":{"schema":"x","schema":"y"}}', "fixture"
            )

        producer = json.loads(self.producer_path.read_text(encoding="utf-8"))
        mutations = (
            (producer, "root_unknown"),
            (producer["bank"], "bank_unknown"),
            (producer["bank"]["format"], "format_unknown"),
            (producer["producer"], "producer_unknown"),
        )
        for target, key in mutations:
            with self.subTest(key=key):
                mutated = copy.deepcopy(producer)
                if target is producer:
                    mutated[key] = 1
                elif target is producer["bank"]:
                    mutated["bank"][key] = 1
                elif target is producer["bank"]["format"]:
                    mutated["bank"]["format"][key] = 1
                else:
                    mutated["producer"][key] = 1
                with self.assertRaisesRegex(
                    contract.StateBankContractError, "SCHEMA_KEYS"
                ):
                    contract.parse_producer_manifest(self.json_bytes(mutated))

        training = json.loads(self.training_path.read_text(encoding="utf-8"))
        for path in (
            (),
            ("bank",),
            ("bank", "format"),
            ("producer_manifest",),
            ("loader",),
            ("authorization",),
        ):
            with self.subTest(path=path):
                mutated = copy.deepcopy(training)
                target = mutated
                for component in path:
                    target = target[component]
                target["unknown"] = 1
                with self.assertRaisesRegex(
                    contract.StateBankContractError, "SCHEMA_KEYS"
                ):
                    contract.validate_training_contract(mutated)

    def test_missing_keys_fail_closed_at_every_contract_object_level(self) -> None:
        producer = json.loads(self.producer_path.read_text(encoding="utf-8"))
        producer_objects = (
            ((), tuple(producer)),
            (("bank",), tuple(producer["bank"])),
            (("bank", "format"), tuple(producer["bank"]["format"])),
            (("producer",), tuple(producer["producer"])),
        )
        for path, keys in producer_objects:
            for key in keys:
                with self.subTest(document="producer", path=path, key=key):
                    mutated = copy.deepcopy(producer)
                    target = mutated
                    for component in path:
                        target = target[component]
                    del target[key]
                    with self.assertRaisesRegex(
                        contract.StateBankContractError,
                        "SCHEMA_KEYS|PRODUCER_SCHEMA",
                    ):
                        contract.parse_producer_manifest(self.json_bytes(mutated))

        training = json.loads(self.training_path.read_text(encoding="utf-8"))
        training_objects = (
            ((), tuple(training)),
            (("bank",), tuple(training["bank"])),
            (("bank", "format"), tuple(training["bank"]["format"])),
            (
                ("producer_manifest",),
                tuple(training["producer_manifest"]),
            ),
            (("loader",), tuple(training["loader"])),
            (("authorization",), tuple(training["authorization"])),
        )
        for path, keys in training_objects:
            for key in keys:
                with self.subTest(document="training", path=path, key=key):
                    mutated = copy.deepcopy(training)
                    target = mutated
                    for component in path:
                        target = target[component]
                    del target[key]
                    with self.assertRaisesRegex(
                        contract.StateBankContractError, "SCHEMA_KEYS"
                    ):
                        contract.validate_training_contract(mutated)

    def test_noncanonical_numbers_roles_schemas_and_authored_kind_reject(self) -> None:
        producer = json.loads(self.producer_path.read_text(encoding="utf-8"))
        bad_values = (
            (("bank", "records"), True, "SCHEMA_INTEGER"),
            (("bank", "records"), 1.0, "SCHEMA_INTEGER"),
            (("bank", "sha256"), "A" * 64, "SHA256_FORMAT"),
            (("ruleset",), "BB2016", "SCHEMA_VALUE"),
            (("artifact_role",), "opaque", "SCHEMA_VALUE"),
        )
        for path, value, message in bad_values:
            with self.subTest(path=path, value=value):
                mutated = copy.deepcopy(producer)
                target = mutated
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                with self.assertRaisesRegex(contract.StateBankContractError, message):
                    contract.parse_producer_manifest(self.json_bytes(mutated))

        request = self.request()
        request["kind"] = "authored-scenario"
        with self.assertRaisesRegex(
            contract.StateBankContractError, "AUTHORED_NOT_IMPLEMENTED"
        ):
            contract.validate_artifact_request(**request)

        training = json.loads(self.training_path.read_text(encoding="utf-8"))
        literal_mutations = (
            (("schema",), "unknown", "SCHEMA_VALUE"),
            (("artifact_role",), "analysis-only", "SCHEMA_VALUE"),
            (("bank_kind",), "authored-scenario", "SCHEMA_VALUE"),
            (("ruleset",), "BB2016", "SCHEMA_VALUE"),
            (("training_eligible",), False, "SCHEMA_VALUE"),
            (
                ("producer_manifest", "schema"),
                "unknown",
                "SCHEMA_VALUE",
            ),
            (("authorization", "schema"), "unknown", "SCHEMA_VALUE"),
            (("authorization", "decision"), "", "SCHEMA_TYPE"),
        )
        for path, value, message in literal_mutations:
            with self.subTest(document="training", path=path):
                mutated = copy.deepcopy(training)
                target = mutated
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = value
                with self.assertRaisesRegex(contract.StateBankContractError, message):
                    contract.validate_training_contract(mutated)

    def test_bbs_header_length_count_and_metadata_are_exact(self) -> None:
        valid = self.bank_path.read_bytes()
        cases = {
            "BBS_HEADER": valid[:15],
            "BBS_MAGIC": b"NOPE" + valid[4:],
            "BBS_VERSION": valid[:4] + struct.pack("<I", 2) + valid[8:],
            "BBS_MATCH_SIZE": valid[:8] + struct.pack("<I", 0) + valid[12:],
            "BBS_FINGERPRINT": valid[:12] + struct.pack("<I", 0) + valid[16:],
            "BBS_PARTIAL_RECORD": valid + b"x",
            "BBS_EMPTY": valid[:16],
        }
        for message, payload in cases.items():
            with self.subTest(message=message):
                with self.assertRaisesRegex(contract.StateBankContractError, message):
                    contract.inspect_bbs(payload, validate_metadata=True)

        for source_id, half, turn, padding, message in (
            (0, 1, 1, b"\0\0", "BBS_METADATA"),
            (0xA0000001, 1, 1, b"\0\0", "BBS_AUTHORED_NAMESPACE"),
            (7, 0, 1, b"\0\0", "BBS_METADATA"),
            (7, 1, 9, b"\0\0", "BBS_METADATA"),
            (7, 1, 1, b"x\0", "BBS_METADATA"),
        ):
            payload = BBS_HEADER.pack(b"BBS1", 1, self.match_size, self.fingerprint)
            payload += BBS_META.pack(source_id, 0, half, turn, padding) + b"test"
            with self.subTest(metadata=(source_id, half, turn, padding)):
                with self.assertRaisesRegex(contract.StateBankContractError, message):
                    contract.inspect_bbs(payload, validate_metadata=True)

    def test_compiled_identity_commits_to_every_field_and_path(self) -> None:
        fields: dict[str, object] = {
            **contract.NO_BANK_STATE_FIELDS,
            "contract_identity": "ignored-input-value",
        }
        baseline = contract.compiled_contract_identity(fields)
        for field in contract.STATE_FIELD_TO_MACRO:
            if field == "contract_identity":
                continue
            with self.subTest(field=field):
                changed = dict(fields)
                value = changed[field]
                changed[field] = (
                    value + 1 if isinstance(value, int) else f"{value}-changed"
                )
                self.assertNotEqual(
                    contract.compiled_contract_identity(changed), baseline
                )
        changed_identity_only = dict(fields)
        changed_identity_only["contract_identity"] = "other"
        self.assertEqual(
            contract.compiled_contract_identity(changed_identity_only),
            baseline,
        )

    def test_cross_file_fields_reconcile_before_authorization(self) -> None:
        producer = json.loads(self.producer_path.read_text(encoding="utf-8"))
        producer["bank"]["records"] = 2
        producer["bank"]["bytes"] += BBS_META.size + self.match_size
        self.producer_path.write_bytes(self.json_bytes(producer))
        request = self.request()
        training = json.loads(self.training_path.read_text(encoding="utf-8"))
        training["producer_manifest"]["sha256"] = request["producer_manifest_sha256"]
        self.training_path.write_bytes(self.json_bytes(training))
        request = self.request()
        with self.assertRaisesRegex(
            contract.StateBankContractError, "CONTRACT_RECONCILE"
        ):
            contract.validate_artifact_request(**request)

    def test_analysis_and_proof_artifacts_cannot_be_training_producers(self) -> None:
        for role in ("analysis-only", "structural-proof"):
            with self.subTest(role=role):
                self.write_fixture()
                producer = json.loads(self.producer_path.read_text(encoding="utf-8"))
                producer["artifact_role"] = role
                producer["training_eligible"] = False
                if role == "analysis-only":
                    producer["producer"]["producer_engine_source_sha256"] = None
                self.producer_path.write_bytes(self.json_bytes(producer))
                request = self.request()
                training = json.loads(self.training_path.read_text(encoding="utf-8"))
                training["producer_manifest"]["sha256"] = request[
                    "producer_manifest_sha256"
                ]
                if role == "analysis-only":
                    training["producer_manifest"]["producer_engine_source_sha256"] = (
                        self.producer_engine_hash
                    )
                self.training_path.write_bytes(self.json_bytes(training))
                with self.assertRaisesRegex(
                    contract.StateBankContractError,
                    "PRODUCER_NOT_TRAINING_ELIGIBLE|CONTRACT_RECONCILE",
                ):
                    contract.validate_artifact_request(**self.request())

    def test_private_suffix_checks_metadata_and_is_not_publicly_selectable(
        self,
    ) -> None:
        result = contract._validate_request_for_test(
            authorized_producer_kind="test-strict-fixture-v1",
            **self.request(),
        )
        self.assertEqual(result["records"], 1)

        for source_id, padding, message in (
            (0, b"\0\0", "BBS_METADATA"),
            (0xA0000001, b"\0\0", "BBS_AUTHORED_NAMESPACE"),
            (7, b"x\0", "BBS_METADATA"),
        ):
            with self.subTest(source_id=source_id, padding=padding):
                self.write_fixture(source_id=source_id, padding=padding)
                with self.assertRaisesRegex(contract.StateBankContractError, message):
                    contract._validate_request_for_test(
                        authorized_producer_kind="test-strict-fixture-v1",
                        **self.request(),
                    )

        source = (ROOT / "tools/state_bank_contract.py").read_text(encoding="utf-8")
        public_parser = source.split("def parse_args", 1)[1]
        self.assertNotIn("authorized-producer", public_parser)
        self.assertNotIn("test-strict-fixture-v1", public_parser)

    def test_private_transaction_publishes_data_and_authority_last(self) -> None:
        self.write_native_fixture()
        puffer = self.directory / "puffer"
        prepared: list[tuple[Path, Path, bytes]] = []
        published: list[str] = []
        real_prepare = contract._prepare_destination_temporary
        real_publish = contract._publish_destination_temporary

        def record_prepare(
            path: Path, payload: bytes, *, expected_sha256: str | None = None
        ) -> Path:
            temporary = real_prepare(path, payload, expected_sha256=expected_sha256)
            prepared.append((temporary, path, payload))
            return temporary

        def record_publish(
            temporary: Path,
            path: Path,
            *,
            payload: bytes,
            expected_sha256: str | None = None,
        ) -> None:
            if not published:
                self.assertEqual(len(prepared), 5)
                for staged, destination, expected_payload in prepared:
                    with self.subTest(staged=destination.name):
                        self.assertTrue(staged.is_file())
                        self.assertFalse(staged.is_symlink())
                        self.assertEqual(staged.read_bytes(), expected_payload)
            published.append(path.name)
            real_publish(
                temporary,
                path,
                payload=payload,
                expected_sha256=expected_sha256,
            )

        with mock.patch.object(
            contract,
            "_prepare_destination_temporary",
            side_effect=record_prepare,
        ), mock.patch.object(
            contract,
            "_publish_destination_temporary",
            side_effect=record_publish,
        ):
            result = contract._stage_authorized_request_for_test(
                puffer,
                authorized_producer_kind="test-strict-fixture-v1",
                exact_action_source_hash="b" * 64,
                environment_source_hash="c" * 64,
                observation_abi="obs-v6",
                observation_version=6,
                **self.request(),
            )
        self.assertEqual(
            published,
            [
                "state_bank.bbs",
                "state_bank.producer.json",
                "state_bank.contract.json",
                "state_bank_build.h",
                "exact_action_build_hash.h",
            ],
        )
        self.assertEqual(result["bank_sha256"], self.request()["bank_sha256"])
        self.assertEqual(
            (puffer / "resources/bloodbowl/state_bank.bbs").read_bytes(),
            self.bank_path.read_bytes(),
        )
        installed = contract.show_installed(puffer)
        self.assertEqual(installed["kind"], "strict-replay")
        self.assertEqual(installed["kind_value"], 1)
        self.assertFalse(
            any(
                path.name.endswith(".tmp")
                for directory in (
                    puffer / "resources/bloodbowl",
                    puffer / "ocean/bloodbowl",
                    puffer / "src",
                )
                for path in directory.iterdir()
            )
        )

    def test_private_validator_build_uses_pre_mutation_engine_snapshot(
        self,
    ) -> None:
        self.write_native_fixture()
        live_repo = self.directory / "mutable-live-repo"
        shutil.copytree(ROOT / "engine", live_repo / "engine", symlinks=True)
        shutil.copytree(
            ROOT / "puffer/bloodbowl",
            live_repo / "puffer/bloodbowl",
            symlinks=True,
        )
        shutil.copy2(ROOT / "Makefile", live_repo / "Makefile")
        request = self.request()
        request["engine_root"] = live_repo
        destination = self.directory / "snapshot-race-puffer"
        real_run = contract.subprocess.run
        mutated = False

        def mutate_live_source_before_make(
            command: object, *args: object, **kwargs: object
        ) -> subprocess.CompletedProcess[object]:
            nonlocal mutated
            if (
                not mutated
                and isinstance(command, list)
                and command
                and command[0] == "make"
                and "state-bank-validate" in command
            ):
                mutated = True
                build_source = Path(str(kwargs["cwd"]))
                self.assertNotEqual(build_source, live_repo)
                self.assertEqual(
                    contract.engine_source_sha256(build_source),
                    self.engine_hash,
                )
                self.assertEqual(
                    os.readlink(build_source / "engine/src/bb"),
                    "../include/bb",
                )
                for path in (build_source, *build_source.rglob("*")):
                    if not path.is_symlink():
                        self.assertEqual(
                            path.stat().st_mode & 0o222,
                            0,
                            f"snapshot path remained writable: {path}",
                        )
                (live_repo / "engine/src/bb_rng.c").write_text(
                    "#error injected live-source mutation\n",
                    encoding="ascii",
                )
            return real_run(command, *args, **kwargs)

        with mock.patch.object(
            contract.subprocess,
            "run",
            side_effect=mutate_live_source_before_make,
        ):
            result = contract._stage_authorized_request_for_test(
                destination,
                authorized_producer_kind="test-strict-fixture-v1",
                exact_action_source_hash="b" * 64,
                environment_source_hash="c" * 64,
                observation_abi="obs-v6",
                observation_version=6,
                **request,
            )
        self.assertTrue(mutated)
        self.assertEqual(result["bank_sha256"], request["bank_sha256"])
        self.assertEqual(
            contract.show_installed(destination)["loader_engine_source_sha256"],
            self.engine_hash,
        )

    def test_engine_mutation_before_snapshot_fails_before_publication(
        self,
    ) -> None:
        live_repo = self.directory / "mutated-before-snapshot-repo"
        shutil.copytree(ROOT / "engine", live_repo / "engine", symlinks=True)
        request = self.request()
        request["engine_root"] = live_repo
        destination = self.directory / "unpublished-snapshot-race-puffer"
        real_snapshot = contract._snapshot_engine_source
        mutated = False

        def mutate_then_snapshot(
            source_root: Path,
            snapshot_root: Path,
            *,
            expected_sha256: str,
        ) -> None:
            nonlocal mutated
            mutated = True
            (source_root / "engine/src/bb_rng.c").write_text(
                "#error injected mutation before snapshot\n",
                encoding="ascii",
            )
            real_snapshot(
                source_root,
                snapshot_root,
                expected_sha256=expected_sha256,
            )

        with mock.patch.object(
            contract,
            "_snapshot_engine_source",
            side_effect=mutate_then_snapshot,
        ), mock.patch.object(contract, "_publish_destination_temporary") as publisher:
            with self.assertRaisesRegex(
                contract.StateBankContractError,
                r"^ENGINE_SOURCE_SNAPSHOT: .* != claimed loader SHA-256",
            ):
                contract._stage_authorized_request_for_test(
                    destination,
                    authorized_producer_kind="test-strict-fixture-v1",
                    exact_action_source_hash="b" * 64,
                    environment_source_hash="c" * 64,
                    observation_abi="obs-v6",
                    observation_version=6,
                    **request,
                )
        self.assertTrue(mutated)
        publisher.assert_not_called()
        self.assertFalse(destination.exists())

    def test_private_staged_mutation_fails_before_first_publication(self) -> None:
        puffer = self.directory / "mutated-staging-puffer"
        contract.install_no_bank_contract(
            puffer,
            exact_action_source_hash="b" * 64,
            environment_source_hash="c" * 64,
            observation_abi="obs-v6",
            observation_version=6,
        )
        authority = puffer / "src/exact_action_build_hash.h"
        old_authority = authority.read_bytes()
        prepared: list[Path] = []
        real_prepare = contract._prepare_destination_temporary
        real_publish = contract._publish_destination_temporary

        def mutate_earlier_temporary(
            path: Path, payload: bytes, *, expected_sha256: str | None = None
        ) -> Path:
            temporary = real_prepare(path, payload, expected_sha256=expected_sha256)
            prepared.append(temporary)
            if len(prepared) == 5:
                prepared[0].write_bytes(b"mutated after initial rehash")
            return temporary

        with mock.patch.object(contract, "_run_engine_validator"), mock.patch.object(
            contract,
            "_prepare_destination_temporary",
            side_effect=mutate_earlier_temporary,
        ), mock.patch.object(
            contract,
            "_publish_destination_temporary",
            wraps=real_publish,
        ) as publisher:
            with self.assertRaisesRegex(
                contract.StateBankContractError, "DESTINATION_SHA256"
            ):
                contract._stage_authorized_request_for_test(
                    puffer,
                    authorized_producer_kind="test-strict-fixture-v1",
                    exact_action_source_hash="d" * 64,
                    environment_source_hash="e" * 64,
                    observation_abi="obs-v6",
                    observation_version=6,
                    **self.request(),
                )
        publisher.assert_not_called()
        self.assertEqual(authority.read_bytes(), old_authority)
        self.assertEqual(contract.show_installed(puffer), contract.NO_BANK_STATE_FIELDS)
        self.assertFalse(
            any(
                path.name.endswith(".tmp")
                for directory in (
                    puffer / "resources/bloodbowl",
                    puffer / "ocean/bloodbowl",
                    puffer / "src",
                )
                for path in directory.iterdir()
            )
        )

    def test_private_publish_path_swap_fails_clean_for_every_artifact(
        self,
    ) -> None:
        for relative in (
            "resources/bloodbowl/state_bank.bbs",
            "resources/bloodbowl/state_bank.producer.json",
            "resources/bloodbowl/state_bank.contract.json",
            "ocean/bloodbowl/state_bank_build.h",
            "src/exact_action_build_hash.h",
        ):
            with self.subTest(relative=relative):
                puffer = self.directory / ("publish-swap-" + relative.replace("/", "-"))
                contract.install_no_bank_contract(
                    puffer,
                    exact_action_source_hash="b" * 64,
                    environment_source_hash="c" * 64,
                    observation_abi="obs-v6",
                    observation_version=6,
                )
                authority = puffer / "src/exact_action_build_hash.h"
                bridge = puffer / "ocean/bloodbowl/state_bank_build.h"
                previous_authority = authority.read_bytes()
                previous_bridge = bridge.read_bytes()
                target = puffer / relative
                real_replace = os.replace
                swapped = False

                def swap_source_inside_publish(
                    source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
                    destination: (str | bytes | os.PathLike[str] | os.PathLike[bytes]),
                ) -> None:
                    nonlocal swapped
                    source_path = Path(source)
                    destination_path = Path(destination)
                    if not swapped and destination_path == target:
                        swapped = True
                        replacement = source_path.with_name(
                            f"{source_path.name}.replacement"
                        )
                        payload = bytearray(source_path.read_bytes())
                        payload[-1] ^= 1
                        replacement.write_bytes(payload)
                        real_replace(replacement, source_path)
                    real_replace(source, destination)

                with mock.patch.object(
                    contract, "_run_engine_validator"
                ), mock.patch.object(
                    contract.os,
                    "replace",
                    side_effect=swap_source_inside_publish,
                ):
                    with self.assertRaisesRegex(
                        contract.StateBankContractError,
                        "DESTINATION_SHA256",
                    ):
                        contract._stage_authorized_request_for_test(
                            puffer,
                            authorized_producer_kind=("test-strict-fixture-v1"),
                            exact_action_source_hash="d" * 64,
                            environment_source_hash="e" * 64,
                            observation_abi="obs-v6",
                            observation_version=6,
                            **self.request(),
                        )
                self.assertTrue(swapped)
                self.assertEqual(authority.read_bytes(), previous_authority)
                self.assertEqual(bridge.read_bytes(), previous_bridge)
                for name in (
                    "state_bank.bbs",
                    "state_bank.producer.json",
                    "state_bank.contract.json",
                ):
                    self.assertFalse((puffer / "resources/bloodbowl" / name).exists())
                self.assertFalse(
                    any(
                        path.name.endswith(".tmp") or path.name.endswith(".replacement")
                        for directory in (
                            puffer / "resources/bloodbowl",
                            puffer / "ocean/bloodbowl",
                            puffer / "src",
                        )
                        for path in directory.iterdir()
                    )
                )

    def test_private_final_authority_path_swap_after_verifier_rolls_back(
        self,
    ) -> None:
        puffer = self.directory / "post-verify-authority-swap"
        contract.install_no_bank_contract(
            puffer,
            exact_action_source_hash="b" * 64,
            environment_source_hash="c" * 64,
            observation_abi="obs-v6",
            observation_version=6,
        )
        authority = puffer / "src/exact_action_build_hash.h"
        bridge = puffer / "ocean/bloodbowl/state_bank_build.h"
        previous_authority = authority.read_bytes()
        previous_bridge = bridge.read_bytes()
        real_verify = contract._verify_destination_descriptor
        published_calls = 0
        replaced = False

        def replace_fifth_destination_after_real_verify(
            descriptor: int,
            payload: bytes,
            **kwargs: object,
        ) -> os.stat_result:
            nonlocal published_calls, replaced
            result = real_verify(descriptor, payload, **kwargs)
            if kwargs.get("label") == "published destination":
                published_calls += 1
                if published_calls == 5:
                    replaced = True
                    competitor = puffer / "authority-competitor"
                    competitor.write_bytes(b"competing authority\n")
                    os.replace(competitor, authority)
            return result

        with mock.patch.object(contract, "_run_engine_validator"), mock.patch.object(
            contract,
            "_verify_destination_descriptor",
            side_effect=replace_fifth_destination_after_real_verify,
        ):
            with self.assertRaisesRegex(
                contract.StateBankContractError,
                "published destination path inode",
            ):
                contract._stage_authorized_request_for_test(
                    puffer,
                    authorized_producer_kind="test-strict-fixture-v1",
                    exact_action_source_hash="d" * 64,
                    environment_source_hash="e" * 64,
                    observation_abi="obs-v6",
                    observation_version=6,
                    **self.request(),
                )
        self.assertTrue(replaced)
        self.assertEqual(published_calls, 5)
        self.assertEqual(authority.read_bytes(), previous_authority)
        self.assertEqual(bridge.read_bytes(), previous_bridge)
        for name in (
            "state_bank.bbs",
            "state_bank.producer.json",
            "state_bank.contract.json",
        ):
            self.assertFalse((puffer / "resources/bloodbowl" / name).exists())

    def test_engine_helper_rejects_mutation_after_python_validation(self) -> None:
        self.write_native_fixture()
        request = self.request()
        fields = contract._validate_request_for_test(
            authorized_producer_kind="test-strict-fixture-v1",
            **request,
        )
        compiled = contract._complete_compiled_fields(fields)
        payload = bytearray(self.bank_path.read_bytes())
        payload[-1] ^= 1
        self.bank_path.write_bytes(payload)
        with self.assertRaisesRegex(
            contract.StateBankContractError, "ENGINE_VALIDATOR_REJECTED"
        ):
            contract._run_engine_validator(
                repo_root=ROOT,
                request=request,
                fields=fields,
                contract_identity=str(compiled["contract_identity"]),
            )

    def test_native_fixture_generator_satisfies_shared_python_contract(
        self,
    ) -> None:
        self.write_native_fixture()
        generated = self.directory / "generated"
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / "tools/generate_state_bank_contract_fixture.py"),
                "--bbs",
                str(self.bank_path),
                "--out-dir",
                str(generated),
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        immutable = generated / "immutable"
        bank = immutable / "state_bank.bbs"
        producer = immutable / "state_bank.producer.json"
        training = immutable / "state_bank.contract.json"
        _root, envelope = contract.parse_producer_manifest(producer.read_bytes())
        training_value = contract.validate_training_contract(
            contract.parse_json_bytes(
                training.read_bytes(), "generated training contract"
            )
        )
        self.assertEqual(envelope["bank"], training_value["bank"])
        request = {
            "bank_path": bank,
            "bank_sha256": self.sha256(bank.read_bytes()),
            "producer_manifest_path": producer,
            "producer_manifest_sha256": self.sha256(producer.read_bytes()),
            "training_contract_path": training,
            "training_contract_sha256": self.sha256(training.read_bytes()),
            "kind": "strict-replay",
            "engine_root": ROOT,
        }
        fields = contract._validate_request_for_test(
            authorized_producer_kind="test-strict-fixture-v1",
            **request,
        )
        header = (generated / "state_bank_build.generated.h").read_text(
            encoding="ascii"
        )
        compiled = {
            **fields,
            "bank_path": str(generated / "active/state_bank.bbs"),
            "producer_manifest_path": str(
                generated / "active/state_bank.producer.json"
            ),
            "training_contract_path": str(
                generated / "active/state_bank.contract.json"
            ),
        }
        expected_identity = contract.compiled_contract_identity(compiled)
        self.assertIn(
            f"#define PUFFER_STATE_BANK_CONTRACT_IDENTITY " f'"{expected_identity}"',
            header,
        )
        for macro in contract.STATE_BANK_MACROS:
            self.assertEqual(header.count(f"#define {macro} "), 1)

    def test_every_private_publication_and_fsync_failure_keeps_old_authority(
        self,
    ) -> None:
        real_publish = contract._publish_destination_temporary
        real_fsync = contract._fsync_directory

        for boundary_kind, boundary in (
            *(("publication", index) for index in range(1, 6)),
            *(("directory-fsync", index) for index in range(1, 4)),
        ):
            with self.subTest(boundary_kind=boundary_kind, boundary=boundary):
                puffer = self.directory / f"failed-{boundary_kind}-{boundary}"
                contract.install_no_bank_contract(
                    puffer,
                    exact_action_source_hash="b" * 64,
                    environment_source_hash="c" * 64,
                    observation_abi="obs-v6",
                    observation_version=6,
                )
                authority = puffer / "src/exact_action_build_hash.h"
                old_authority = authority.read_bytes()
                publication_calls = 0
                fsync_calls = 0

                def inject_publication(
                    temporary: Path,
                    path: Path,
                    *,
                    payload: bytes,
                    expected_sha256: str | None = None,
                ) -> None:
                    nonlocal publication_calls
                    publication_calls += 1
                    if boundary_kind == "publication" and publication_calls == boundary:
                        raise OSError(f"injected publication {boundary}")
                    real_publish(
                        temporary,
                        path,
                        payload=payload,
                        expected_sha256=expected_sha256,
                    )

                def inject_directory_fsync(path: Path) -> None:
                    nonlocal fsync_calls
                    fsync_calls += 1
                    if boundary_kind == "directory-fsync" and fsync_calls == boundary:
                        raise OSError(f"injected directory fsync {boundary}")
                    real_fsync(path)

                with mock.patch.object(
                    contract, "_run_engine_validator"
                ), mock.patch.object(
                    contract,
                    "_publish_destination_temporary",
                    side_effect=inject_publication,
                ), mock.patch.object(
                    contract,
                    "_fsync_directory",
                    side_effect=inject_directory_fsync,
                ):
                    with self.assertRaisesRegex(OSError, "injected"):
                        contract._stage_authorized_request_for_test(
                            puffer,
                            authorized_producer_kind=("test-strict-fixture-v1"),
                            exact_action_source_hash="d" * 64,
                            environment_source_hash="e" * 64,
                            observation_abi="obs-v6",
                            observation_version=6,
                            **self.request(),
                        )
                self.assertEqual(authority.read_bytes(), old_authority)
                self.assertEqual(
                    contract.show_installed(puffer),
                    contract.NO_BANK_STATE_FIELDS,
                )
                self.assertFalse(
                    any(
                        path.name.endswith(".tmp")
                        for directory in (
                            puffer / "resources/bloodbowl",
                            puffer / "ocean/bloodbowl",
                            puffer / "src",
                        )
                        for path in directory.iterdir()
                    )
                )

    def test_no_bank_install_removes_only_exact_artifacts_and_is_checkable(
        self,
    ) -> None:
        puffer = self.directory / "no-bank-puffer"
        resources = puffer / "resources/bloodbowl"
        resources.mkdir(parents=True)
        for name in (
            "state_bank.bbs",
            "state_bank.producer.json",
            "state_bank.contract.json",
            "keep.txt",
        ):
            (resources / name).write_text("stale", encoding="utf-8")
        contract.install_no_bank_contract(
            puffer,
            exact_action_source_hash="b" * 64,
            environment_source_hash="c" * 64,
            observation_abi="obs-v6",
            observation_version=6,
        )
        self.assertTrue((resources / "keep.txt").is_file())
        observed = contract.check_no_bank_install(puffer)
        self.assertEqual(observed, contract.NO_BANK_STATE_FIELDS)
        bridge = puffer / "ocean/bloodbowl/state_bank_build.h"
        self.assertEqual(
            bridge.read_text(encoding="ascii"),
            "#pragma once\n" '#include "../../src/exact_action_build_hash.h"\n',
        )

        (resources / "state_bank.bbs").write_bytes(b"stale")
        with self.assertRaisesRegex(
            contract.StateBankContractError, "STALE_STATE_BANK"
        ):
            contract.check_no_bank_install(puffer)

        (resources / "state_bank.bbs").unlink()
        (resources / "state_bank.bbs").symlink_to(resources / "missing-target.bbs")
        with self.assertRaisesRegex(
            contract.StateBankContractError, "STALE_STATE_BANK"
        ):
            contract.check_no_bank_install(puffer)

        (resources / "state_bank.bbs").unlink()
        authority = puffer / "src/exact_action_build_hash.h"
        authority.write_text(
            authority.read_text(encoding="ascii") + "#undef PUFFER_ACTION_ABI\n",
            encoding="ascii",
        )
        with self.assertRaisesRegex(
            contract.StateBankContractError, "unrecognized build-header line"
        ):
            contract.check_no_bank_install(puffer)

    def test_no_bank_authority_publish_swap_restores_previous_contract(
        self,
    ) -> None:
        puffer = self.directory / "no-bank-publish-swap"
        contract.install_no_bank_contract(
            puffer,
            exact_action_source_hash="b" * 64,
            environment_source_hash="c" * 64,
            observation_abi="obs-v6",
            observation_version=6,
        )
        authority = puffer / "src/exact_action_build_hash.h"
        bridge = puffer / "ocean/bloodbowl/state_bank_build.h"
        previous_authority = authority.read_bytes()
        previous_bridge = bridge.read_bytes()
        real_replace = os.replace
        swapped = False

        def swap_authority_inside_publish(
            source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        ) -> None:
            nonlocal swapped
            source_path = Path(source)
            if not swapped and Path(destination) == authority:
                swapped = True
                replacement = source_path.with_name(f"{source_path.name}.replacement")
                payload = bytearray(source_path.read_bytes())
                payload[-1] ^= 1
                replacement.write_bytes(payload)
                real_replace(replacement, source_path)
            real_replace(source, destination)

        with mock.patch.object(
            contract.os,
            "replace",
            side_effect=swap_authority_inside_publish,
        ):
            with self.assertRaisesRegex(
                contract.StateBankContractError,
                "DESTINATION_SHA256",
            ):
                contract.install_no_bank_contract(
                    puffer,
                    exact_action_source_hash="d" * 64,
                    environment_source_hash="e" * 64,
                    observation_abi="obs-v6",
                    observation_version=6,
                )
        self.assertTrue(swapped)
        self.assertEqual(authority.read_bytes(), previous_authority)
        self.assertEqual(bridge.read_bytes(), previous_bridge)
        self.assertEqual(
            contract.show_installed(puffer),
            contract.NO_BANK_STATE_FIELDS,
        )
        self.assertFalse(
            any(
                path.name.endswith(".tmp") or path.name.endswith(".replacement")
                for directory in (
                    puffer / "resources/bloodbowl",
                    puffer / "ocean/bloodbowl",
                    puffer / "src",
                )
                for path in directory.iterdir()
            )
        )

    def test_no_bank_authority_path_swap_after_verifier_restores_previous(
        self,
    ) -> None:
        puffer = self.directory / "no-bank-post-verify-swap"
        contract.install_no_bank_contract(
            puffer,
            exact_action_source_hash="b" * 64,
            environment_source_hash="c" * 64,
            observation_abi="obs-v6",
            observation_version=6,
        )
        authority = puffer / "src/exact_action_build_hash.h"
        bridge = puffer / "ocean/bloodbowl/state_bank_build.h"
        previous_authority = authority.read_bytes()
        previous_bridge = bridge.read_bytes()
        expected_new_authority = contract.render_no_bank_header(
            exact_action_source_hash="d" * 64,
            environment_source_hash="e" * 64,
            observation_abi="obs-v6",
            observation_version=6,
        )
        real_verify = contract._verify_destination_descriptor
        replaced = False

        def replace_authority_after_real_verify(
            descriptor: int,
            payload: bytes,
            **kwargs: object,
        ) -> os.stat_result:
            nonlocal replaced
            result = real_verify(descriptor, payload, **kwargs)
            if (
                not replaced
                and kwargs.get("label") == "published destination"
                and payload == expected_new_authority
            ):
                replaced = True
                competitor = puffer / "authority-competitor"
                competitor.write_bytes(b"competing authority\n")
                os.replace(competitor, authority)
            return result

        with mock.patch.object(
            contract,
            "_verify_destination_descriptor",
            side_effect=replace_authority_after_real_verify,
        ):
            with self.assertRaisesRegex(
                contract.StateBankContractError,
                "published destination path inode",
            ):
                contract.install_no_bank_contract(
                    puffer,
                    exact_action_source_hash="d" * 64,
                    environment_source_hash="e" * 64,
                    observation_abi="obs-v6",
                    observation_version=6,
                )
        self.assertTrue(replaced)
        self.assertEqual(authority.read_bytes(), previous_authority)
        self.assertEqual(bridge.read_bytes(), previous_bridge)
        self.assertEqual(
            contract.show_installed(puffer),
            contract.NO_BANK_STATE_FIELDS,
        )

    def test_validate_installed_reconciles_all_fields_but_returns_launcher_set(
        self,
    ) -> None:
        validated = contract._validate_request_for_test(
            authorized_producer_kind="test-strict-fixture-v1",
            **self.request(),
        )
        compiled: dict[str, object] = dict(validated)
        compiled.update(
            {
                "bank_path": "resources/bloodbowl/state_bank.bbs",
                "producer_manifest_path": "resources/bloodbowl/state_bank.producer.json",
                "training_contract_path": "resources/bloodbowl/state_bank.contract.json",
            }
        )
        compiled["contract_identity"] = contract.compiled_contract_identity(compiled)
        compiled = {field: compiled[field] for field in contract.STATE_FIELD_TO_MACRO}
        with mock.patch.object(
            contract, "show_installed", return_value=compiled
        ), mock.patch.object(
            contract, "validate_artifact_request", return_value=validated
        ):
            result = contract.validate_installed(
                puffer_root=self.directory,
                kind="strict-replay",
                bank_sha256=str(self.request()["bank_sha256"]),
                producer_manifest_sha256=str(
                    self.request()["producer_manifest_sha256"]
                ),
                training_contract_sha256=str(
                    self.request()["training_contract_sha256"]
                ),
            )
        self.assertEqual(tuple(result), contract.LAUNCHER_CONTRACT_FIELDS)
        self.assertEqual(set(result), set(contract.LAUNCHER_CONTRACT_FIELDS))

        for field in (
            "authorization_schema",
            "bbs_version",
            "match_size",
            "engine_fingerprint",
            "bank_path",
            "producer_manifest_path",
            "training_contract_path",
            "contract_identity",
        ):
            with self.subTest(field=field):
                drifted = dict(compiled)
                value = drifted[field]
                drifted[field] = value + 1 if isinstance(value, int) else "drift"
                with mock.patch.object(
                    contract, "show_installed", return_value=drifted
                ), mock.patch.object(
                    contract,
                    "validate_artifact_request",
                    return_value=validated,
                ):
                    with self.assertRaisesRegex(
                        contract.StateBankContractError,
                        "COMPILED_CONTRACT_MISMATCH",
                    ):
                        contract.validate_installed(
                            puffer_root=self.directory,
                            kind="strict-replay",
                            bank_sha256=str(self.request()["bank_sha256"]),
                            producer_manifest_sha256=str(
                                self.request()["producer_manifest_sha256"]
                            ),
                            training_contract_sha256=str(
                                self.request()["training_contract_sha256"]
                            ),
                        )

    def test_engine_hash_frames_paths_and_allows_only_canonical_alias(self) -> None:
        expected = hashlib.sha256(b"bloodbowl-engine-source-v1\0")
        entries: list[tuple[bytes, bytes]] = []
        for directory in (ROOT / "engine/include/bb", ROOT / "engine/src"):
            for path in directory.rglob("*"):
                if path.is_file() and not path.is_symlink():
                    relative = path.relative_to(ROOT).as_posix().encode()
                    entries.append((relative, path.read_bytes()))
        for relative, payload in sorted(entries):
            expected.update(struct.pack("<Q", len(relative)))
            expected.update(relative)
            expected.update(struct.pack("<Q", len(payload)))
            expected.update(payload)
        expected_hash = expected.hexdigest()
        self.assertEqual(contract.engine_source_sha256(ROOT), expected_hash)
        snapshot = self.directory / "exact-engine-snapshot"
        contract._snapshot_engine_source(ROOT, snapshot, expected_sha256=expected_hash)
        alias = snapshot / "engine/src/bb"
        self.assertTrue(alias.is_symlink())
        self.assertEqual(os.readlink(alias), "../include/bb")
        self.assertEqual(contract.engine_source_sha256(snapshot), expected_hash)
        self.assertEqual(
            [
                path.relative_to(snapshot).as_posix()
                for path in snapshot.rglob("*")
                if path.is_symlink()
            ],
            ["engine/src/bb"],
        )

        fake = self.directory / "engine-root"
        (fake / "engine/include/bb").mkdir(parents=True)
        (fake / "engine/src").mkdir(parents=True)
        (fake / "engine/include/bb/header.h").write_text("h", encoding="ascii")
        (fake / "engine/src/source.c").write_text("c", encoding="ascii")
        os.symlink("../include/bb", fake / "engine/src/bb")
        contract.engine_source_sha256(fake)
        os.symlink("source.c", fake / "engine/src/extra")
        with self.assertRaisesRegex(
            contract.StateBankContractError, "symlink is forbidden"
        ):
            contract.engine_source_sha256(fake)

        raced = self.directory / "raced-engine-root"
        (raced / "engine/include/bb").mkdir(parents=True)
        (raced / "engine/src").mkdir(parents=True)
        (raced / "engine/include/bb/header.h").write_text("header", encoding="ascii")
        source = raced / "engine/src/source.c"
        source.write_text("source", encoding="ascii")
        os.symlink("../include/bb", raced / "engine/src/bb")
        outside = self.directory / "outside.c"
        outside.write_text("outside", encoding="ascii")
        real_read = contract.read_bounded_file
        replaced = False

        def replace_after_enumeration(path: Path, limit: int, label: str) -> bytes:
            nonlocal replaced
            if path == source and not replaced:
                replaced = True
                source.unlink()
                source.symlink_to(outside)
            return real_read(path, limit, label)

        with mock.patch.object(
            contract, "read_bounded_file", side_effect=replace_after_enumeration
        ):
            with self.assertRaisesRegex(contract.StateBankContractError, "FILE_OPEN"):
                contract.engine_source_sha256(raced)

    def test_json_limits_and_regular_file_gate(self) -> None:
        link = self.directory / "producer-link.json"
        link.symlink_to(self.producer_path)
        with self.assertRaisesRegex(contract.StateBankContractError, "FILE_OPEN"):
            contract.read_bounded_file(
                link, contract.MAX_MANIFEST_BYTES, "producer manifest"
            )
        with mock.patch.object(
            contract.os,
            "fstat",
            return_value=os.stat_result(
                (0o100644, 0, 0, 0, 0, 0, contract.MAX_MANIFEST_BYTES + 1, 0, 0, 0)
            ),
        ):
            # Avoid relying on sparse-file behavior to exercise the exact cap.
            with self.assertRaisesRegex(
                contract.StateBankContractError, "FILE_TOO_LARGE"
            ):
                contract.read_bounded_file(
                    self.producer_path,
                    contract.MAX_MANIFEST_BYTES,
                    "producer manifest",
                )


class PufferStateBankPatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.patch_path = ROOT / "training/puffer_state_bank_contract.patch"
        cls.patch = cls.patch_path.read_text(encoding="utf-8")
        cls.installer = INSTALLER.read_text(encoding="utf-8")

    def test_patch_exports_exact_same_twenty_fields_from_cpu_and_cuda(self) -> None:
        self.assertEqual(self.patch.count("diff --git a/src/bindings"), 2)
        for field, attribute in contract.MODULE_STATE_FIELD_NAMES.items():
            macro = contract.STATE_FIELD_TO_MACRO[field]
            line = f'm.attr("{attribute}") = '
            with self.subTest(attribute=attribute):
                self.assertEqual(self.patch.count(line), 2)
                self.assertEqual(self.patch.count(macro), 2)
        self.assertNotIn("state_bank_compiled_kind", self.patch)

    def test_installer_applies_patch_before_backend_digest_and_checks_both(self):
        patch_position = self.installer.index("STATE_BANK_EXPORT_PATCH=")
        digest_position = self.installer.index(
            'EXACT_BACKEND_HASH="$(exact_backend_hash)"'
        )
        self.assertLess(patch_position, digest_position)
        for source in ("src/bindings.cu", "src/bindings_cpu.cpp"):
            self.assertIn(source, self.installer)
        self.assertIn("training/puffer_state_bank_contract.patch", self.installer)
        self.assertIn("state_bank_contract.contract_from_module(_C)", self.installer)

    def test_private_engine_validator_is_always_built_in_isolation(self) -> None:
        source = (ROOT / "tools/state_bank_contract.py").read_text(encoding="utf-8")
        validator = source.split("def _run_engine_validator(", 1)[1]
        validator = validator.split("def _stage_authorized_request_for_test(", 1)[0]
        self.assertIn("TemporaryDirectory(", validator)
        self.assertIn('f"BUILD={isolated_build}"', validator)
        self.assertIn('isolated_build / "state_bank_validate"', validator)
        self.assertNotIn('repo_root / "build/state_bank_validate"', validator)

    def test_validator_binds_predicate_sources_to_installed_environment_hash(
        self,
    ) -> None:
        source = (ROOT / "tools/state_bank_contract.py").read_text(encoding="utf-8")
        validator = source.split("def _run_engine_validator(", 1)[1]
        validator = validator.split("def _stage_authorized_request_for_test(", 1)[0]
        installed = source.split("def validate_installed(", 1)[1]
        installed = installed.split("\ndef ", 1)[0]
        self.assertIn("environment_source_sha256", validator)
        self.assertIn("_run_engine_validator(", installed)
        self.assertIn("PUFFER_ENV_SOURCE_HASH", installed)

    def test_backend_hash_closure_contains_both_changed_bindings(self) -> None:
        function = self.installer.split("exact_backend_hash() {", 1)[1]
        function = function.split("\n}", 1)[0]
        self.assertIn("src/bindings.cu", function)
        self.assertIn("src/bindings_cpu.cpp", function)

    def test_generated_authority_is_written_only_by_shared_publisher(self) -> None:
        self.assertIn('state_bank_contract.py" install-no-bank', self.installer)
        self.assertNotRegex(
            self.installer,
            r">\s*\"\$PUFFER/src/exact_action_build_hash\.h\"",
        )

    def test_snapshot_hash_excludes_only_out_of_band_exact_paths(self) -> None:
        snapshot = self.installer.split("snapshot_hash() {", 1)[1]
        snapshot = snapshot.split("\n}", 1)[0]
        self.assertIn("! -path './.content_hash'", snapshot)
        self.assertIn("! -path './state_bank_build.h'", snapshot)
        self.assertNotIn("! -name", snapshot)
        for name in (
            "ROOT_SOURCE_HASH",
            "INSTALLED_SOURCE_HASH",
            "RECORDED_SOURCE_HASH",
        ):
            self.assertIn(name, self.installer)


def executable_shell(path: Path) -> str:
    """Return shell source without full-line comments.

    Contract words in prose must not satisfy tests for executable argument
    parsing, authority checks, or cleanup.
    """

    return "\n".join(
        line
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )


def continued_commands(source: str) -> str:
    """Join backslash-continuations so one shell command is one test line."""

    return re.sub(r"\\\n[ \t]*", " ", source)


class StateBankShellContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launcher = executable_shell(LAUNCHER)
        cls.installer = executable_shell(INSTALLER)

    def test_positive_reset_requires_external_kind_and_all_three_pins(self):
        """A positive curriculum may not bootstrap trust from staged bytes."""

        required = (
            "LADDER_STATE_BANK_KIND",
            "EXPECTED_LADDER_STATE_BANK_SHA256",
            "EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256",
            "EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256",
        )
        for variable in required:
            with self.subTest(variable=variable):
                required_expansion = re.search(
                    rf"\$\{{{re.escape(variable)}:\?[^}}]+\}}",
                    self.launcher,
                )
                self.assertIsNotNone(
                    required_expansion,
                    f"{variable} is not a caller-required environment value",
                )

    def test_launcher_does_not_turn_an_observed_digest_into_authority(self):
        """The current file hash may be compared with a pin, never become it."""

        observed_to_authority = re.compile(
            r"(?m)^[ \t]*(?:EXPECTED_)?LADDER_STATE_BANK_SHA256"
            r"[ \t]*=[ \t]*.*\b(?:sha256sum|shasum)\b"
        )
        self.assertIsNone(
            observed_to_authority.search(self.launcher),
            "launcher derives state-bank authority from the file it is "
            "supposed to authenticate",
        )

    def test_installer_exposes_only_an_all_or_none_typed_bank_form(self):
        """Every artifact and reviewed digest must enter one transaction."""

        required_options = (
            "--state-bank-kind",
            "--state-bank",
            "--state-bank-sha256",
            "--state-bank-producer-manifest",
            "--state-bank-producer-manifest-sha256",
            "--state-bank-contract",
            "--state-bank-contract-sha256",
        )
        for option in required_options:
            with self.subTest(option=option):
                self.assertTrue(
                    option in self.installer,
                    f"installer does not parse required typed-bank option {option}",
                )

        # This invocation is harmless on both sides of the change: it supplies
        # no valid Puffer tree and cannot reach installation.  The important
        # behavior is that the option parser diagnoses a partial transaction
        # before treating the first option as a positional checkout path.
        result = subprocess.run(
            [
                "bash",
                str(INSTALLER),
                "--state-bank-kind",
                "strict-replay",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "state-bank arguments are all-or-none",
            result.stdout,
            "a partial typed-bank transaction did not get its own diagnostic",
        )
        self.assertNotIn(
            "is not a PufferLib tree",
            result.stdout,
            "installer misparsed a typed-bank option as the Puffer checkout",
        )

    def test_installer_never_reads_the_ambiguous_legacy_bank(self):
        """The edition-blind analysis artifact is never an install source."""

        self.assertFalse(
            "validation/states/bank.bbs" in self.installer,
            "installer still implicitly trusts and copies the legacy raw bank",
        )

    def test_no_bank_install_explicitly_removes_all_staged_artifacts(self):
        """No arguments mean a clean no-bank transaction, not stale reuse."""

        source = continued_commands(self.installer)
        removal_commands = "\n".join(
            line
            for line in source.splitlines()
            if re.match(r"^[ \t]*rm[ \t]+-f(?:[ \t]|$)", line)
        )

        targets = (
            "state_bank.bbs",
            "state_bank.producer.json",
            "state_bank.contract.json",
        )
        for target in targets:
            with self.subTest(target=target):
                # Permit either a literal destination in `rm -f` or a named
                # destination variable, while still requiring executable
                # cleanup rather than a comment describing it.
                if target in removal_commands:
                    continue
                assignment = re.search(
                    rf"(?m)^[ \t]*([A-Z][A-Z0-9_]*)=" rf"[^\n]*{re.escape(target)}",
                    source,
                )
                self.assertIsNotNone(
                    assignment,
                    f"installer has no exact destination for {target}",
                )
                variable = assignment.group(1)
                self.assertRegex(
                    removal_commands,
                    rf"\$\{{?{re.escape(variable)}\}}?",
                    f"no-bank path does not remove staged {target}",
                )


if __name__ == "__main__":
    unittest.main()
