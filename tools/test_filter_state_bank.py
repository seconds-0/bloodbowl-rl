#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import filter_state_bank as state_filter
import state_bank_contract
from validation import build_state_bank


HEADER = struct.Struct("<4sIII")
META = struct.Struct("<IIBB2s")


class StateBankFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.input = self.root / "mixed.bbs"
        self.allowlist = self.root / "bb2025.ids"
        self.output = self.root / "strict.bbs"
        self.selected_ids = self.root / "strict.ids"
        self.manifest = self.root / "strict.manifest.json"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def record(
        replay_id: int,
        command: int,
        half: int,
        turn: int,
        payload: bytes,
        padding: bytes = b"\0\0",
    ) -> bytes:
        return META.pack(replay_id, command, half, turn, padding) + payload

    def write_bank(
        self,
        records: list[bytes],
        *,
        magic: bytes = b"BBS1",
        version: int = 1,
        match_size: int = 4,
        fingerprint: int = 0x12345678,
        suffix: bytes = b"",
    ) -> bytes:
        payload = HEADER.pack(magic, version, match_size, fingerprint)
        payload += b"".join(records) + suffix
        self.input.write_bytes(payload)
        return payload

    def write_allowlist(self, value: str = "10\n12\n") -> None:
        self.allowlist.write_text(value, encoding="utf-8")

    def run_filter(self, **kwargs: object) -> dict[str, object]:
        command = [
            "/usr/bin/python3",
            "/repo/tools/filter_state_bank.py",
            str(self.input),
            str(self.output),
            "--allowlist",
            str(self.allowlist),
            "--selected-ids",
            str(self.selected_ids),
            "--manifest",
            str(self.manifest),
        ]
        return state_filter.filter_state_bank(
            self.input,
            self.output,
            allowlist_path=self.allowlist,
            selected_ids_path=self.selected_ids,
            manifest_path=self.manifest,
            expected_input_sha256=self.sha256(self.input),
            expected_allowlist_sha256=self.sha256(self.allowlist),
            command=command,
            **kwargs,
        )

    def test_filters_byte_exact_records_and_writes_bound_manifest(self) -> None:
        records = [
            self.record(10, 1, 1, 1, b"aaaa"),
            self.record(11, 2, 1, 2, b"bbbb"),
            self.record(10, 3, 1, 3, b"cccc"),
            self.record(12, 4, 2, 4, b"dddd"),
        ]
        source = self.write_bank(records)
        self.write_allowlist()

        result = self.run_filter(
            expected_input_records=4,
            expected_input_replay_ids=3,
            expected_selected_records=3,
            expected_selected_replay_ids=2,
        )

        expected = source[: HEADER.size] + records[0] + records[2] + records[3]
        self.assertEqual(self.output.read_bytes(), expected)
        self.assertEqual(self.selected_ids.read_text(encoding="utf-8"), "10\n12\n")
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        self.assertEqual(result, manifest)
        self.assertEqual(manifest["schema"], "bloodbowl-strict-filter-manifest-v2")
        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(
            manifest["format"],
            {
                "engine_fingerprint": "0x12345678",
                "magic": "BBS1",
                "match_size": 4,
                "record_count_is_file_size_derived": True,
                "version": 1,
            },
        )
        self.assertEqual(manifest["input"]["records"], 4)
        self.assertEqual(manifest["input"]["replay_ids"], 3)
        self.assertEqual(manifest["output"]["records"], 3)
        self.assertEqual(manifest["output"]["replay_ids"], 2)
        self.assertEqual(
            manifest["excluded"],
            {
                "records": 1,
                "replay_ids": 1,
                "replay_id_values": [11],
            },
        )
        self.assertEqual(manifest["allowlist"]["ids_total"], 2)
        self.assertEqual(manifest["allowlist"]["ids_matched"], 2)
        self.assertEqual(manifest["allowlist"]["ids_unmatched"], 0)
        self.assertEqual(manifest["output"]["half_histogram"], {"1": 2, "2": 1})
        self.assertEqual(
            manifest["output"]["turn_histogram"],
            {
                "1": 1,
                "3": 1,
                "4": 1,
            },
        )
        self.assertEqual(manifest["input"]["sha256"], self.sha256(self.input))
        self.assertEqual(manifest["output"]["sha256"], self.sha256(self.output))
        self.assertEqual(
            manifest["selected_ids"]["sha256"], self.sha256(self.selected_ids)
        )
        self.assertEqual(
            manifest["tool"]["sha256"],
            self.sha256(Path(state_filter.__file__).resolve()),
        )
        self.assertIn("half one", " ".join(manifest["limitations"]))
        self.assertEqual(
            manifest["artifact"],
            {
                "schema": "bloodbowl-state-bank-producer-v1",
                "artifact_role": "analysis-only",
                "bank_kind": "strict-replay",
                "ruleset": "BB2025",
                "training_eligible": False,
                "bank": {
                    "sha256": self.sha256(self.output),
                    "bytes": len(expected),
                    "records": 3,
                    "format": {
                        "magic": "BBS1",
                        "version": 1,
                        "match_size": 4,
                        "engine_fingerprint": "0x12345678",
                    },
                },
                "producer": {
                    "kind": "strict-bb2025-filter-v2",
                    "producer_engine_source_sha256": None,
                },
            },
        )
        self.assertEqual(
            state_bank_contract.validate_filter_manifest(manifest),
            manifest,
        )

        header, body, metadata = build_state_bank.read_shard(self.output)
        self.assertEqual(header, source[: HEADER.size])
        self.assertEqual(len(body), 3 * (META.size + 4))
        self.assertEqual(metadata, [(1, 1), (1, 3), (2, 4)])

    def test_repeated_run_at_same_paths_is_byte_deterministic(self) -> None:
        self.write_bank(
            [
                self.record(10, 1, 1, 1, b"aaaa"),
                self.record(12, 2, 1, 2, b"bbbb"),
            ]
        )
        self.write_allowlist()
        self.run_filter()
        first = tuple(
            path.read_bytes()
            for path in (self.output, self.selected_ids, self.manifest)
        )
        for path in (self.output, self.selected_ids, self.manifest):
            path.unlink()

        self.run_filter()

        second = tuple(
            path.read_bytes()
            for path in (self.output, self.selected_ids, self.manifest)
        )
        self.assertEqual(first, second)

    def test_filter_manifest_is_closed_and_cannot_claim_current_engine(self) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("10\n")
        self.run_filter()
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))

        manifest["unknown"] = 1
        with self.assertRaisesRegex(
            state_bank_contract.StateBankContractError, "SCHEMA_KEYS"
        ):
            state_bank_contract.validate_filter_manifest(manifest)
        del manifest["unknown"]

        manifest["artifact"]["producer"]["producer_engine_source_sha256"] = (
            state_bank_contract.engine_source_sha256(
                Path(__file__).resolve().parents[1]
            )
        )
        with self.assertRaisesRegex(
            state_bank_contract.StateBankContractError, "must equal None"
        ):
            state_bank_contract.validate_filter_manifest(manifest)

    def test_hash_pins_fail_before_any_output_is_created(self) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("10\n")
        with self.assertRaisesRegex(
            state_filter.StateBankError, "input SHA-256 mismatch"
        ):
            state_filter.filter_state_bank(
                self.input,
                self.output,
                allowlist_path=self.allowlist,
                selected_ids_path=self.selected_ids,
                manifest_path=self.manifest,
                expected_input_sha256="0" * 64,
                expected_allowlist_sha256=self.sha256(self.allowlist),
                command=["filter"],
            )
        self.assertFalse(self.output.exists())
        self.assertFalse(self.selected_ids.exists())
        self.assertFalse(self.manifest.exists())

        with self.assertRaisesRegex(
            state_filter.StateBankError, "allowlist SHA-256 mismatch"
        ):
            state_filter.filter_state_bank(
                self.input,
                self.output,
                allowlist_path=self.allowlist,
                selected_ids_path=self.selected_ids,
                manifest_path=self.manifest,
                expected_input_sha256=self.sha256(self.input),
                expected_allowlist_sha256="f" * 64,
                command=["filter"],
            )

    def test_detects_input_mutation_between_initial_hash_and_copy(self) -> None:
        records = [self.record(10, 1, 1, 1, b"aaaa")]
        self.write_bank(records)
        self.write_allowlist("10\n")
        expected_input_sha = self.sha256(self.input)
        expected_allowlist_sha = self.sha256(self.allowlist)
        real_sha256 = state_filter.sha256
        mutated = False

        def mutate_after_hash(path: Path) -> str:
            nonlocal mutated
            result = real_sha256(path)
            if path == self.input.resolve() and not mutated:
                mutated = True
                payload = bytearray(self.input.read_bytes())
                payload[-1] ^= 1
                self.input.write_bytes(payload)
            return result

        with mock.patch.object(state_filter, "sha256", side_effect=mutate_after_hash):
            with self.assertRaisesRegex(
                state_filter.StateBankError, "input changed after hash validation"
            ):
                state_filter.filter_state_bank(
                    self.input,
                    self.output,
                    allowlist_path=self.allowlist,
                    selected_ids_path=self.selected_ids,
                    manifest_path=self.manifest,
                    expected_input_sha256=expected_input_sha,
                    expected_allowlist_sha256=expected_allowlist_sha,
                    command=["filter"],
                )
        self.assertFalse(self.output.exists())
        self.assertFalse(self.selected_ids.exists())
        self.assertFalse(self.manifest.exists())

    def test_rejects_malformed_bank_without_leaving_outputs(self) -> None:
        cases = {
            "bad magic": lambda: self.write_bank([], magic=b"NOPE"),
            "unsupported version": lambda: self.write_bank([], version=2),
            "zero match size": lambda: self.write_bank([], match_size=0),
            "zero fingerprint": lambda: self.write_bank([], fingerprint=0),
            "partial record": lambda: self.write_bank([], suffix=b"x"),
            "zero replay ID": lambda: self.write_bank(
                [self.record(0, 1, 1, 1, b"aaaa")]
            ),
            "nonzero metadata padding": lambda: self.write_bank(
                [self.record(10, 1, 1, 1, b"aaaa", b"x\0")]
            ),
            "half out of range": lambda: self.write_bank(
                [self.record(10, 1, 0, 1, b"aaaa")]
            ),
            "turn out of range": lambda: self.write_bank(
                [self.record(10, 1, 1, 9, b"aaaa")]
            ),
        }
        self.write_allowlist("10\n")
        for message, writer in cases.items():
            with self.subTest(message=message):
                writer()
                with self.assertRaisesRegex(state_filter.StateBankError, message):
                    self.run_filter()
                self.assertFalse(self.output.exists())
                self.assertFalse(self.selected_ids.exists())
                self.assertFalse(self.manifest.exists())

    def test_allowlist_is_canonical_unique_and_bom_crlf_tolerant(self) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.allowlist.write_bytes(b"\xef\xbb\xbf10\r\n\r\n")
        self.run_filter()
        self.assertEqual(self.selected_ids.read_text(encoding="utf-8"), "10\n")
        for path in (self.output, self.selected_ids, self.manifest):
            path.unlink()

        invalid = {
            "empty": "\n\n",
            "non-numeric": "10\nabc\n",
            "out of range": "0\n",
            "non-canonical": "010\n",
            "duplicate": "10\n10\n",
        }
        for message, value in invalid.items():
            with self.subTest(message=message):
                self.write_allowlist(value)
                with self.assertRaisesRegex(state_filter.StateBankError, message):
                    self.run_filter()

    def test_refuses_aliases_existing_outputs_and_no_overlap(self) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("12\n")
        with self.assertRaisesRegex(state_filter.StateBankError, "no records selected"):
            self.run_filter()
        self.assertFalse(self.output.exists())

        self.write_allowlist("10\n")
        self.output.write_text("occupied", encoding="utf-8")
        with self.assertRaisesRegex(state_filter.StateBankError, "already exists"):
            self.run_filter()
        self.assertEqual(self.output.read_text(encoding="utf-8"), "occupied")
        self.output.unlink()

        with self.assertRaisesRegex(
            state_filter.StateBankError, "paths must be distinct"
        ):
            state_filter.filter_state_bank(
                self.input,
                self.input,
                allowlist_path=self.allowlist,
                selected_ids_path=self.selected_ids,
                manifest_path=self.manifest,
                expected_input_sha256=self.sha256(self.input),
                expected_allowlist_sha256=self.sha256(self.allowlist),
                command=["filter"],
            )

    def test_publish_failure_is_fail_clean_and_does_not_clobber_racer(self) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("10\n")
        real_link = os.link
        calls = 0

        def fail_second_link(
            source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                raise OSError("injected publish failure")
            real_link(source, destination)

        with mock.patch.object(state_filter.os, "link", side_effect=fail_second_link):
            with self.assertRaisesRegex(OSError, "injected publish failure"):
                self.run_filter()

        self.assertFalse(self.output.exists())
        self.assertFalse(self.selected_ids.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

        calls = 0

        def race_second_link(
            source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        ) -> None:
            nonlocal calls
            calls += 1
            if calls == 2:
                Path(destination).write_bytes(b"concurrent writer\n")
            real_link(source, destination)

        with mock.patch.object(state_filter.os, "link", side_effect=race_second_link):
            with self.assertRaises(FileExistsError):
                self.run_filter()

        self.assertFalse(self.output.exists())
        self.assertEqual(b"concurrent writer\n", self.selected_ids.read_bytes())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

        self.selected_ids.unlink()
        real_unlink = Path.unlink
        failed_cleanup = False

        def fail_one_post_commit_temp_unlink(
            path: Path,
            *args: object,
            **kwargs: object,
        ) -> None:
            nonlocal failed_cleanup
            if not failed_cleanup and path.name.startswith(f".{self.output.name}."):
                failed_cleanup = True
                raise PermissionError("injected post-commit cleanup failure")
            real_unlink(path, *args, **kwargs)

        with mock.patch.object(
            state_filter.Path,
            "unlink",
            new=fail_one_post_commit_temp_unlink,
        ):
            result = self.run_filter()

        self.assertTrue(failed_cleanup)
        self.assertEqual(result["output"]["sha256"], self.sha256(self.output))
        self.assertTrue(self.selected_ids.is_file())
        self.assertTrue(self.manifest.is_file())

    def test_staged_set_mutation_fails_before_first_publication(self) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("10\n")
        real_write = state_filter._write_bytes
        real_link = os.link

        for target in ("output-sha", "ids-size", "manifest-bytes"):
            with self.subTest(target=target):
                for path in (
                    self.output,
                    self.selected_ids,
                    self.manifest,
                    *self.root.glob(".*.tmp"),
                ):
                    path.unlink(missing_ok=True)
                link_calls = 0

                def count_link(*args: object, **kwargs: object) -> None:
                    nonlocal link_calls
                    link_calls += 1
                    real_link(*args, **kwargs)

                def mutate_after_manifest_write(path: Path, payload: bytes) -> None:
                    real_write(path, payload)
                    if not path.name.startswith(f".{self.manifest.name}."):
                        return
                    if target == "output-sha":
                        staged = next(self.root.glob(f".{self.output.name}.*.tmp"))
                        mutated = bytearray(staged.read_bytes())
                        mutated[-1] ^= 1
                        staged.write_bytes(mutated)
                    elif target == "ids-size":
                        staged = next(
                            self.root.glob(f".{self.selected_ids.name}.*.tmp")
                        )
                        staged.write_bytes(staged.read_bytes() + b"11\n")
                    else:
                        staged = path
                        mutated = bytearray(staged.read_bytes())
                        mutated[0] ^= 1
                        staged.write_bytes(mutated)

                with mock.patch.object(
                    state_filter,
                    "_write_bytes",
                    side_effect=mutate_after_manifest_write,
                ), mock.patch.object(state_filter.os, "link", side_effect=count_link):
                    with self.assertRaisesRegex(
                        state_filter.StateBankError, "staged .* changed"
                    ):
                        self.run_filter()
                self.assertEqual(link_calls, 0)
                self.assertFalse(self.output.exists())
                self.assertFalse(self.selected_ids.exists())
                self.assertFalse(self.manifest.exists())
                self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_first_link_source_swap_fails_clean_without_authority(self) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("10\n")
        real_link = os.link
        link_calls = 0
        swapped = False

        def swap_first_source_then_link(
            source: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            destination: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        ) -> None:
            nonlocal link_calls, swapped
            link_calls += 1
            source_path = Path(source)
            if not swapped:
                swapped = True
                payload = bytearray(source_path.read_bytes())
                payload[-1] ^= 1
                replacement = source_path.with_name(f"{source_path.name}.replacement")
                replacement.write_bytes(payload)
                replacement.chmod(0)
                os.replace(replacement, source_path)
            real_link(source, destination)

        with mock.patch.object(
            state_filter.os,
            "link",
            side_effect=swap_first_source_then_link,
        ):
            with self.assertRaisesRegex(
                state_filter.StateBankError,
                "published output changed",
            ):
                self.run_filter()

        self.assertTrue(swapped)
        self.assertEqual(link_calls, 1)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.selected_ids.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_post_link_open_failure_removes_only_verified_publication(
        self,
    ) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("10\n")
        real_open = state_filter._open_published_destination
        calls = 0

        def fail_first_destination_open(*args: object, **kwargs: object):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise state_filter.StateBankError(
                    "injected post-link destination open failure"
                )
            return real_open(*args, **kwargs)

        with mock.patch.object(
            state_filter,
            "_open_published_destination",
            side_effect=fail_first_destination_open,
        ):
            with self.assertRaisesRegex(
                state_filter.StateBankError,
                "injected post-link destination open failure",
            ):
                self.run_filter()

        self.assertEqual(calls, 1)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.selected_ids.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

        sentinel = b"competing destination\n"

        def replace_with_competitor_then_fail(binding: object, destination: Path):
            competitor = self.root / "competitor"
            competitor.write_bytes(sentinel)
            os.replace(competitor, destination)
            return real_open(binding, destination)

        with mock.patch.object(
            state_filter,
            "_open_published_destination",
            side_effect=replace_with_competitor_then_fail,
        ):
            with self.assertRaisesRegex(
                state_filter.StateBankError,
                "inode does not match verified staged file",
            ):
                self.run_filter()
        self.assertEqual(self.output.read_bytes(), sentinel)
        self.assertFalse(self.selected_ids.exists())
        self.assertFalse(self.manifest.exists())
        self.assertEqual(list(self.root.glob(".*.tmp")), [])

    def test_manifest_path_replacement_after_verification_fails_cleanly(
        self,
    ) -> None:
        self.write_bank([self.record(10, 1, 1, 1, b"aaaa")])
        self.write_allowlist("10\n")
        sentinel = b"competing manifest after verification\n"
        real_verify = state_filter._verify_published_descriptor
        replaced = False

        def replace_manifest_after_real_verify(
            binding: object,
            destination: Path,
            descriptor: int,
        ) -> os.stat_result:
            nonlocal replaced
            verified = real_verify(binding, destination, descriptor)
            if not replaced and destination.name == self.manifest.name:
                replaced = True
                competitor = self.root / "manifest-competitor"
                competitor.write_bytes(sentinel)
                os.replace(competitor, destination)
            return verified

        with mock.patch.object(
            state_filter,
            "_verify_published_descriptor",
            side_effect=replace_manifest_after_real_verify,
        ):
            with self.assertRaisesRegex(
                state_filter.StateBankError,
                "published manifest changed: destination path inode",
            ):
                self.run_filter()

        self.assertTrue(replaced)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.selected_ids.exists())
        self.assertEqual(self.manifest.read_bytes(), sentinel)
        self.assertEqual(list(self.root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
