"""Regression tests for immutable reward-screen retry plans."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from screen_manifest_contract import (
    ScreenManifestContractError,
    freeze_screen_manifest,
)


class ScreenManifestContractTests(unittest.TestCase):
    def test_identical_retry_reuses_the_exact_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "SCREEN_MANIFEST.json"
            contract = {
                "screen_profile": "genesis",
                "schedule": [{"arm": "both", "seed": 42}],
                "implementation": {"compiled_semantic_contract": {"kind": 0}},
            }
            first_sha = freeze_screen_manifest(destination, contract)
            first_bytes = destination.read_bytes()
            second_sha = freeze_screen_manifest(destination, contract)
            self.assertEqual(second_sha, first_sha)
            self.assertEqual(destination.read_bytes(), first_bytes)

    def test_retry_with_changed_schedule_fails_closed_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "SCREEN_MANIFEST.json"
            original = {
                "screen_profile": "genesis",
                "schedule": [{"arm": "both", "seed": 42}],
            }
            freeze_screen_manifest(destination, original)
            before = destination.read_bytes()

            changed = {
                "screen_profile": "genesis",
                "schedule": [{"arm": "both", "seed": 43}],
            }
            with self.assertRaisesRegex(
                ScreenManifestContractError,
                "existing screen manifest contract differs",
            ):
                freeze_screen_manifest(destination, changed)
            self.assertEqual(destination.read_bytes(), before)

    def test_retry_with_changed_profile_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "SCREEN_MANIFEST.json"
            freeze_screen_manifest(
                destination,
                {"screen_profile": "genesis", "schedule": []},
            )
            with self.assertRaises(ScreenManifestContractError):
                freeze_screen_manifest(
                    destination,
                    {"screen_profile": "control-final", "schedule": []},
                )

    def test_malformed_or_open_existing_envelope_is_rejected(self):
        cases = (
            b'{"schema_version":2,"contract":{},"extra":true}\n',
            b'{"schema_version":1,"contract":{}}\n',
            b'{"schema_version":2,"contract":{},"contract":{}}\n',
            b'{"schema_version":2,"created_utc":"mutable","contract":{}}\n',
            b"not json\n",
        )
        for raw in cases:
            with self.subTest(raw=raw):
                with tempfile.TemporaryDirectory() as tmp:
                    destination = Path(tmp) / "SCREEN_MANIFEST.json"
                    destination.write_bytes(raw)
                    with self.assertRaises(ScreenManifestContractError):
                        freeze_screen_manifest(destination, {})
                    self.assertEqual(destination.read_bytes(), raw)

    def test_existing_manifest_bytes_are_exactly_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "SCREEN_MANIFEST.json"
            contract = {"screen_profile": "genesis", "schedule": []}
            freeze_screen_manifest(destination, contract)
            original = destination.read_bytes()
            destination.write_bytes(b" " + original)
            with self.assertRaisesRegex(
                ScreenManifestContractError,
                "bytes differ from the deterministic screen manifest",
            ):
                freeze_screen_manifest(destination, contract)
            self.assertEqual(destination.read_bytes(), b" " + original)

    def test_new_manifest_has_closed_deterministic_envelope(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "SCREEN_MANIFEST.json"
            freeze_screen_manifest(
                destination, {"screen_profile": "genesis", "schedule": []}
            )
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(
                set(payload),
                {"schema_version", "contract"},
            )
            self.assertEqual(payload["schema_version"], 2)
            self.assertEqual(
                destination.read_bytes(),
                json.dumps(
                    payload,
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8")
                + b"\n",
            )

    def test_concurrent_creator_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            destination = Path(tmp) / "SCREEN_MANIFEST.json"
            sentinel = b"racing manifest owner\n"
            real_link = os.link

            def racing_link(source, target):
                Path(target).write_bytes(sentinel)
                return real_link(source, target)

            with mock.patch(
                "screen_manifest_contract.os.link",
                side_effect=racing_link,
            ):
                with self.assertRaises(ScreenManifestContractError):
                    freeze_screen_manifest(
                        destination,
                        {"screen_profile": "genesis", "schedule": []},
                    )
            self.assertEqual(destination.read_bytes(), sentinel)

    def test_same_size_temp_swap_inside_link_fails_without_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "SCREEN_MANIFEST.json"
            real_link = os.link
            swapped = False

            def swap_source_then_link(source, target):
                nonlocal swapped
                source_path = Path(source)
                swapped = True
                replacement = source_path.with_name(f"{source_path.name}.replacement")
                payload = bytearray(source_path.read_bytes())
                payload[-2] ^= 1
                replacement.write_bytes(payload)
                os.replace(replacement, source_path)
                real_link(source, target)

            with mock.patch(
                "screen_manifest_contract.os.link",
                side_effect=swap_source_then_link,
            ):
                with self.assertRaisesRegex(
                    ScreenManifestContractError,
                    "linked screen manifest differs from verified temporary",
                ):
                    freeze_screen_manifest(
                        destination,
                        {"screen_profile": "genesis", "schedule": []},
                    )
            self.assertTrue(swapped)
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])
            self.assertEqual(list(root.glob("*.replacement")), [])

    def test_post_link_open_failure_cleans_owned_inode_not_competitor(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "SCREEN_MANIFEST.json"
            import screen_manifest_contract as module

            real_open = module._readonly_nofollow

            def fail_destination_open(path, label):
                if label == "destination":
                    raise ScreenManifestContractError(
                        "injected destination open failure"
                    )
                return real_open(path, label)

            with mock.patch.object(
                module,
                "_readonly_nofollow",
                side_effect=fail_destination_open,
            ):
                with self.assertRaisesRegex(
                    ScreenManifestContractError,
                    "injected destination open failure",
                ):
                    freeze_screen_manifest(
                        destination,
                        {"screen_profile": "genesis", "schedule": []},
                    )
            self.assertFalse(destination.exists())
            self.assertEqual(list(root.glob(".*.tmp")), [])

            sentinel = b"competing manifest\n"

            def replace_destination_then_fail(path, label):
                if label == "destination":
                    competitor = root / "competitor"
                    competitor.write_bytes(sentinel)
                    os.replace(competitor, path)
                    return real_open(path, label)
                return real_open(path, label)

            with mock.patch.object(
                module,
                "_readonly_nofollow",
                side_effect=replace_destination_then_fail,
            ):
                with self.assertRaisesRegex(
                    ScreenManifestContractError,
                    "source or destination inode changed",
                ):
                    freeze_screen_manifest(
                        destination,
                        {"screen_profile": "genesis", "schedule": []},
                    )
            self.assertEqual(destination.read_bytes(), sentinel)
            self.assertEqual(list(root.glob(".*.tmp")), [])

    def test_destination_replacement_after_verifier_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            destination = root / "SCREEN_MANIFEST.json"
            sentinel = b"competing manifest after verification\n"
            import screen_manifest_contract as module

            real_verify = module._verify_open_bytes
            replaced = False

            def replace_after_real_verify(descriptor, raw, label, **kwargs):
                nonlocal replaced
                identity = real_verify(descriptor, raw, label, **kwargs)
                if not replaced and label == "destination":
                    replaced = True
                    competitor = root / "competitor"
                    competitor.write_bytes(sentinel)
                    os.replace(competitor, destination)
                return identity

            with mock.patch.object(
                module,
                "_verify_open_bytes",
                side_effect=replace_after_real_verify,
            ):
                with self.assertRaisesRegex(
                    ScreenManifestContractError,
                    "destination path inode changed after verification",
                ):
                    freeze_screen_manifest(
                        destination,
                        {"screen_profile": "genesis", "schedule": []},
                    )
            self.assertTrue(replaced)
            self.assertEqual(destination.read_bytes(), sentinel)
            self.assertEqual(list(root.glob(".*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
