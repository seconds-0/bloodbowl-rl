#!/usr/bin/env python3

import json
import hashlib
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest import mock
from pathlib import Path

import follow_latest


def write_manifest(run, *, tag, seed, warm, expected=16, rollout=4):
    warm_sha = hashlib.sha256(warm.read_bytes()).hexdigest()
    (run / "RUN_MANIFEST.json").write_text(json.dumps({
        "schema_version": 1,
        "mode": "native_static_pool_reward_ablation",
        "tag": tag,
        "seed": str(seed),
        "expected_checkpoint_bytes": str(expected),
        "rollout_quantum": str(rollout),
        "warm": str(warm),
        "warm_bytes": warm.stat().st_size,
        "warm_sha256": warm_sha,
    }), encoding="utf-8")


class FollowLatestTests(unittest.TestCase):
    def test_discovery_is_manifested_full_size_and_post_bootstrap(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            warm = root / "warm.bin"
            warm.write_bytes(b"w" * 16)
            run = root / "1001"
            run.mkdir()
            write_manifest(run, tag="arm-a", seed=42, warm=warm)
            (run / "0000000000000004.bin").write_bytes(b"i" * 16)
            (run / "0000000000000008.bin").write_bytes(b"a" * 15)
            first = run / "0000000000000012.bin"
            first.write_bytes(b"b" * 16)
            time.sleep(0.002)
            second = run / "0000000000000016.bin"
            second.write_bytes(b"c" * 16)
            unmanifested = root / "1002"
            unmanifested.mkdir()
            (unmanifested / "0000000000000099.bin").write_bytes(b"d" * 16)

            candidates = follow_latest.discover_candidates(root)

        self.assertEqual([candidate.step for candidate in candidates], [12, 16])
        self.assertEqual(candidates[-1].tag, "arm-a")
        self.assertEqual(candidates[-1].seed, 42)

    def test_discovery_prefers_newest_run_then_greatest_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            warm = root / "warm.bin"
            warm.write_bytes(b"w" * 16)
            old = root / "1001"
            old.mkdir()
            write_manifest(old, tag="old-arm", seed=42, warm=warm)
            (old / "0000000000000100.bin").write_bytes(b"a" * 16)
            new = root / "1002"
            new.mkdir()
            write_manifest(new, tag="new-arm", seed=43, warm=warm)
            (new / "0000000000000050.bin").write_bytes(b"b" * 16)
            # Touching/restoring the old run must not roll BBTV backward.
            time.sleep(0.002)
            (old / "0000000000000100.bin").touch()

            candidates = follow_latest.discover_candidates(root)

        self.assertEqual(candidates[-1].tag, "new-arm")
        self.assertEqual(candidates[-1].step, 50)

    def test_stability_gate_rejects_wrong_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "checkpoint.bin"
            path.write_bytes(b"x" * 15)
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                follow_latest.stable_native(path, 16, 0)

    def test_corrupt_cache_metadata_is_rebuilt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "native.bin"
            source.write_bytes(b"n" * 16)
            cache = root / "cache"
            cache.mkdir()
            output = cache / "policy_torch.bin"
            output.write_bytes(b"bad" * 8)
            output.with_suffix(".bin.json").write_text("{", encoding="utf-8")
            converter = root / "convert.py"
            converter.write_text("# converter", encoding="utf-8")
            config = root / "config.ini"
            config.write_text("[env]", encoding="utf-8")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"t" * 17)
                return mock.Mock(returncode=0, stdout="converted", stderr="")

            with mock.patch.object(follow_latest.subprocess, "run", fake_run):
                metadata = follow_latest.convert_native(
                    source,
                    16,
                    output.name,
                    cache,
                    Path("python"),
                    converter,
                    config,
                    0,
                    30,
                )

            rebuilt_source_sha = follow_latest.sha256_file(source)

        self.assertEqual(metadata["source_sha256"], rebuilt_source_sha)
        self.assertEqual(metadata["output_bytes"], 17)

    def test_warm_hash_must_match_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            warm = root / "warm.bin"
            warm.write_bytes(b"w" * 16)
            run = root / "1001"
            run.mkdir()
            write_manifest(run, tag="arm-a", seed=42, warm=warm)
            (run / "0000000000000012.bin").write_bytes(b"n" * 16)
            manifest_path = run / "RUN_MANIFEST.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["warm_sha256"] = "0" * 64
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            args = SimpleNamespace(
                checkpoint_root=root,
                state_dir=root / "state",
                cache_dir=root / "cache",
                stability_seconds=0,
            )

            with self.assertRaisesRegex(RuntimeError, "does not match"):
                follow_latest.prepare_pair(args)

    def test_conversion_cache_invalidates_when_config_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "native.bin"
            source.write_bytes(b"n" * 16)
            converter = root / "convert.py"
            converter.write_text("# v1", encoding="utf-8")
            config = root / "config.ini"
            config.write_text("v=1", encoding="utf-8")
            calls = []

            def fake_run(command, **_kwargs):
                calls.append(command)
                Path(command[-1]).write_bytes(b"t" * 17)
                return mock.Mock(returncode=0, stdout="converted", stderr="")

            with mock.patch.object(follow_latest.subprocess, "run", fake_run):
                for _ in range(2):
                    follow_latest.convert_native(
                        source, 16, "policy_torch.bin", root / "cache",
                        Path("python"), converter, config, 0, 30,
                    )
                config.write_text("v=2", encoding="utf-8")
                follow_latest.convert_native(
                    source, 16, "policy_torch.bin", root / "cache",
                    Path("python"), converter, config, 0, 30,
                )

        self.assertEqual(len(calls), 2)

    def test_conversion_rejects_source_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "native.bin"
            source.write_bytes(b"n" * 16)
            converter = root / "convert.py"
            converter.write_text("# converter", encoding="utf-8")
            config = root / "config.ini"
            config.write_text("[env]", encoding="utf-8")

            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b"t" * 17)
                source.write_bytes(b"m" * 16)
                return mock.Mock(returncode=0, stdout="converted", stderr="")

            with mock.patch.object(follow_latest.subprocess, "run", fake_run):
                with self.assertRaisesRegex(RuntimeError, "changed during"):
                    follow_latest.convert_native(
                        source, 16, "policy_torch.bin", root / "cache",
                        Path("python"), converter, config, 0, 30,
                    )

    def test_quarantined_candidate_reverts_to_last_successful_pair(self):
        bad = (Path("bad-a"), Path("bad-b"))
        good = (Path("good-a"), Path("good-b"))
        fallback = (Path("fallback-a"), Path("fallback-b"))

        self.assertEqual(
            follow_latest.choose_stream_pair(bad, good, {bad}, fallback),
            good,
        )
        self.assertEqual(
            follow_latest.choose_stream_pair(bad, None, {bad}, fallback),
            fallback,
        )

    def test_quarantined_last_successful_reverts_to_fallback(self):
        prepared = (Path("prepared-a"), Path("prepared-b"))
        previous = (Path("previous-a"), Path("previous-b"))
        fallback = (Path("fallback-a"), Path("fallback-b"))

        self.assertEqual(
            follow_latest.choose_stream_pair(
                prepared, previous, {prepared, previous}, fallback
            ),
            fallback,
        )

    def test_all_quarantined_pairs_are_not_relaunched(self):
        prepared = (Path("prepared-a"), Path("prepared-b"))
        previous = (Path("previous-a"), Path("previous-b"))
        fallback = (Path("fallback-a"), Path("fallback-b"))

        self.assertIsNone(
            follow_latest.choose_stream_pair(
                prepared,
                previous,
                {prepared, previous, fallback},
                fallback,
            )
        )

    def test_safe_label_removes_path_characters(self):
        self.assertEqual(
            follow_latest.safe_label("arm / seed 42:_torch.bin"),
            "arm-seed-42-_torch.bin",
        )

    def test_parser_preserves_virtualenv_python_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_python = root / "python-real"
            real_python.write_text("", encoding="utf-8")
            venv_python = root / "python-venv"
            venv_python.symlink_to(real_python)
            script = root / "script.py"
            script.write_text("", encoding="utf-8")
            checkpoint_root = root / "checkpoints"
            checkpoint_root.mkdir()
            with mock.patch.object(
                    follow_latest.argparse.ArgumentParser, "error",
                    side_effect=AssertionError):
                args = follow_latest.parse_args([
                    "--checkpoint-root", str(checkpoint_root),
                    "--state-dir", str(root / "state"),
                    "--converter-python", str(venv_python),
                    "--converter-script", str(script),
                    "--config", str(script),
                    "--server-python", str(venv_python),
                    "--server-script", str(script),
                ])
        self.assertEqual(args.converter_python, venv_python.absolute())
        self.assertNotEqual(args.converter_python, real_python.resolve())


if __name__ == "__main__":
    unittest.main()
