"""Behavioral tests for reward-screen result and completion provenance."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from screen_evidence_contract import (
    ScreenEvidenceContractError,
    freeze_screen_completion,
    load_frozen_screen_contract,
    load_run_manifest_for_screen,
    publish_or_validate_result,
)
from screen_manifest_contract import freeze_screen_manifest


def digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )


class ScreenEvidenceContractTests(unittest.TestCase):
    def make_screen(self, root: Path) -> tuple[Path, str, dict[str, object]]:
        contract: dict[str, object] = {
            "prefix": "screen",
            "schedule": [{"index": 1, "arm": "both", "seed": 42}],
        }
        manifest = root / "SCREEN_MANIFEST.json"
        manifest_sha = freeze_screen_manifest(manifest, contract)
        return manifest, manifest_sha, contract

    def result(self, manifest_sha: str) -> dict[str, object]:
        return {
            "schema_version": 2,
            "trainer_complete": True,
            "acceptance_pass": True,
            "acceptance_failures": [],
            "arm": "both",
            "seed": 42,
            "tag": "screen-both-s42",
            "screen_manifest_sha256": manifest_sha,
            "checkpoint_sha256": digest("checkpoint"),
            "checkpoint_lineage_sha256": digest("lineage"),
        }

    def test_manifest_and_run_manifest_are_hash_and_screen_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha, contract = self.make_screen(root)
            self.assertEqual(
                load_frozen_screen_contract(manifest, manifest_sha),
                contract,
            )
            with self.assertRaisesRegex(
                ScreenEvidenceContractError,
                "bytes differ from frozen SHA",
            ):
                load_frozen_screen_contract(manifest, "0" * 64)

            run_manifest = root / "arm.manifest.json"
            write_json(
                run_manifest,
                {"screen_manifest_sha256": manifest_sha},
            )
            self.assertEqual(
                load_run_manifest_for_screen(run_manifest, manifest_sha)[
                    "screen_manifest_sha256"
                ],
                manifest_sha,
            )
            write_json(
                run_manifest,
                {"screen_manifest_sha256": "1" * 64},
            )
            with self.assertRaisesRegex(
                ScreenEvidenceContractError,
                "belongs to another screen",
            ):
                load_run_manifest_for_screen(run_manifest, manifest_sha)

    def test_result_retry_requires_exact_recomputed_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest, manifest_sha, _contract = self.make_screen(root)
            result = self.result(manifest_sha)
            destination = root / "screen-both-s42.result.json"
            publish_or_validate_result(destination, result, "write")
            original = destination.read_bytes()
            publish_or_validate_result(destination, result, "validate")
            self.assertEqual(destination.read_bytes(), original)

            destination.write_bytes(b" " + original)
            with self.assertRaisesRegex(
                ScreenEvidenceContractError,
                "recorded result differs from recomputed screen evidence",
            ):
                publish_or_validate_result(destination, result, "validate")

    def test_completion_is_deterministic_and_revalidates_every_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha, _contract = self.make_screen(root)
            result_path = root / "screen-both-s42.result.json"
            result = self.result(manifest_sha)
            publish_or_validate_result(result_path, result, "write")
            completion = root / "SCREEN_COMPLETE.json"

            freeze_screen_completion(completion, manifest, manifest_sha, root, "screen")
            original = completion.read_bytes()
            freeze_screen_completion(completion, manifest, manifest_sha, root, "screen")
            self.assertEqual(completion.read_bytes(), original)
            payload = json.loads(original)
            self.assertEqual(
                set(payload),
                {"schema_version", "screen_manifest_sha256", "results"},
            )
            self.assertEqual(payload["schema_version"], 2)

            result["checkpoint_sha256"] = digest("different checkpoint")
            write_json(result_path, result)
            with self.assertRaisesRegex(
                ScreenEvidenceContractError,
                "existing screen completion differs from recomputed results",
            ):
                freeze_screen_completion(
                    completion, manifest, manifest_sha, root, "screen"
                )

    def test_oversized_or_symlink_completion_is_bounded_and_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha, _contract = self.make_screen(root)
            result_path = root / "screen-both-s42.result.json"
            publish_or_validate_result(result_path, self.result(manifest_sha), "write")
            completion = root / "SCREEN_COMPLETE.json"
            completion.write_bytes(b"x" * (17 * 1024 * 1024))
            with self.assertRaisesRegex(
                ScreenEvidenceContractError,
                "existing screen completion differs from recomputed results",
            ):
                freeze_screen_completion(
                    completion, manifest, manifest_sha, root, "screen"
                )

        if not hasattr(os, "symlink"):
            self.skipTest("symlinks unavailable")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha, _contract = self.make_screen(root)
            result_path = root / "screen-both-s42.result.json"
            publish_or_validate_result(result_path, self.result(manifest_sha), "write")
            target = root / "target.json"
            target.write_text("{}\n", encoding="utf-8")
            completion = root / "SCREEN_COMPLETE.json"
            completion.symlink_to(target)
            with self.assertRaises(ScreenEvidenceContractError):
                freeze_screen_completion(
                    completion, manifest, manifest_sha, root, "screen"
                )

    def test_racing_result_and_completion_creators_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manifest, manifest_sha, _contract = self.make_screen(root)
            sentinel = b"racing evidence owner\n"
            real_link = os.link

            result_path = root / "screen-both-s42.result.json"

            def racing_result_link(source, target):
                Path(target).write_bytes(sentinel)
                return real_link(source, target)

            with mock.patch(
                "screen_evidence_contract.os.link",
                side_effect=racing_result_link,
            ):
                with self.assertRaises(ScreenEvidenceContractError):
                    publish_or_validate_result(
                        result_path, self.result(manifest_sha), "write"
                    )
            self.assertEqual(result_path.read_bytes(), sentinel)

            result_path.unlink()
            publish_or_validate_result(result_path, self.result(manifest_sha), "write")
            completion = root / "SCREEN_COMPLETE.json"

            def racing_completion_link(source, target):
                Path(target).write_bytes(sentinel)
                return real_link(source, target)

            with mock.patch(
                "screen_evidence_contract.os.link",
                side_effect=racing_completion_link,
            ):
                with self.assertRaises(ScreenEvidenceContractError):
                    freeze_screen_completion(
                        completion, manifest, manifest_sha, root, "screen"
                    )
            self.assertEqual(completion.read_bytes(), sentinel)

    def test_same_size_result_temp_swap_inside_link_fails_without_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest, manifest_sha, _contract = self.make_screen(root)
            result_path = root / "screen-both-s42.result.json"
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
                "screen_evidence_contract.os.link",
                side_effect=swap_source_then_link,
            ):
                with self.assertRaisesRegex(
                    ScreenEvidenceContractError,
                    "linked screen evidence differs from verified temporary",
                ):
                    publish_or_validate_result(
                        result_path, self.result(manifest_sha), "write"
                    )
            self.assertTrue(swapped)
            self.assertFalse(result_path.exists())
            self.assertEqual(
                [
                    path
                    for path in root.iterdir()
                    if path.name.endswith(".tmp") or path.name.endswith(".replacement")
                ],
                [],
            )

    def test_post_link_result_open_failure_leaves_no_partial_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest, manifest_sha, _contract = self.make_screen(root)
            result_path = root / "screen-both-s42.result.json"
            import screen_evidence_contract as module

            real_open = module._readonly_nofollow

            def fail_destination_open(path, label):
                if label == "destination":
                    raise ScreenEvidenceContractError(
                        "injected destination open failure"
                    )
                return real_open(path, label)

            with mock.patch.object(
                module,
                "_readonly_nofollow",
                side_effect=fail_destination_open,
            ):
                with self.assertRaisesRegex(
                    ScreenEvidenceContractError,
                    "injected destination open failure",
                ):
                    publish_or_validate_result(
                        result_path, self.result(manifest_sha), "write"
                    )
            self.assertFalse(result_path.exists())
            self.assertEqual(
                [path for path in root.iterdir() if path.name.endswith(".tmp")],
                [],
            )

    def test_result_replacement_after_verifier_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest, manifest_sha, _contract = self.make_screen(root)
            result_path = root / "screen-both-s42.result.json"
            sentinel = b"competing result after verification\n"
            import screen_evidence_contract as module

            real_verify = module._verify_open_bytes
            replaced = False

            def replace_after_real_verify(descriptor, raw, label, **kwargs):
                nonlocal replaced
                identity = real_verify(descriptor, raw, label, **kwargs)
                if not replaced and label == "destination":
                    replaced = True
                    competitor = root / "competitor"
                    competitor.write_bytes(sentinel)
                    os.replace(competitor, result_path)
                return identity

            with mock.patch.object(
                module,
                "_verify_open_bytes",
                side_effect=replace_after_real_verify,
            ):
                with self.assertRaisesRegex(
                    ScreenEvidenceContractError,
                    "destination path inode changed after verification",
                ):
                    publish_or_validate_result(
                        result_path, self.result(manifest_sha), "write"
                    )
            self.assertTrue(replaced)
            self.assertEqual(result_path.read_bytes(), sentinel)
            self.assertEqual(
                [path for path in root.iterdir() if path.name.endswith(".tmp")],
                [],
            )

    def test_result_same_size_in_place_mutation_after_verifier_is_not_accepted(
        self,
    ):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _manifest, manifest_sha, _contract = self.make_screen(root)
            result_path = root / "screen-both-s42.result.json"
            import screen_evidence_contract as module

            real_verify = module._verify_open_bytes
            mutated = False

            def mutate_after_real_verify(descriptor, raw, label, **kwargs):
                nonlocal mutated
                verified = real_verify(descriptor, raw, label, **kwargs)
                if not mutated and label == "destination":
                    mutated = True
                    mutation_descriptor = os.open(result_path, os.O_WRONLY)
                    try:
                        os.lseek(mutation_descriptor, 0, os.SEEK_SET)
                        self.assertEqual(os.write(mutation_descriptor, b"!"), 1)
                        os.fsync(mutation_descriptor)
                    finally:
                        os.close(mutation_descriptor)
                    os.utime(result_path, ns=(0, 0))
                return verified

            with mock.patch.object(
                module,
                "_verify_open_bytes",
                side_effect=mutate_after_real_verify,
            ):
                with self.assertRaisesRegex(
                    ScreenEvidenceContractError,
                    "destination path inode changed after verification or "
                    "metadata differs",
                ):
                    publish_or_validate_result(
                        result_path, self.result(manifest_sha), "write"
                    )
            self.assertTrue(mutated)
            self.assertFalse(result_path.exists())
            self.assertEqual(
                [path for path in root.iterdir() if path.name.endswith(".tmp")],
                [],
            )


if __name__ == "__main__":
    unittest.main()
