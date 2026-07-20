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

    def test_discovery_across_roots_prefers_newest_run_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            old_root = base / "old"
            new_root = base / "new"
            old_root.mkdir()
            new_root.mkdir()
            warm = base / "warm.bin"
            warm.write_bytes(b"w" * 16)
            old = old_root / "1001"
            old.mkdir()
            write_manifest(old, tag="old-root", seed=42, warm=warm)
            (old / "0000000000000100.bin").write_bytes(b"a" * 16)
            new = new_root / "1002"
            new.mkdir()
            write_manifest(new, tag="new-root", seed=43, warm=warm)
            (new / "0000000000000050.bin").write_bytes(b"b" * 16)

            candidates = follow_latest.discover_candidates_across_roots(
                [old_root, new_root]
            )

        self.assertEqual(candidates[-1].tag, "new-root")
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

    def test_conversion_label_preserves_step_digest_and_prunable_suffix(self):
        candidate = SimpleNamespace(
            tag="vacation-" + "very-long-arm-name-" * 8,
            step=1_598_160_896,
        )

        label = follow_latest._conversion_label(candidate, "a" * 64)

        self.assertLessEqual(len(label), 96)
        self.assertTrue(
            label.endswith(
                "-step001598160896-aaaaaaaaaa_torch.bin"
            )
        )
        self.assertTrue(Path(label).match("*_torch.bin"))

    def test_server_command_forwards_sample_mode(self):
        args = SimpleNamespace(
            server_python=Path("viewer-python"),
            server_script=Path("server.py"),
            port=8787,
            pace=0.6,
            games_per_cycle=2,
            sample=True,
        )

        sampled = follow_latest.server_command(
            args, Path("learner.bin"), Path("baseline.bin")
        )
        args.sample = False
        greedy = follow_latest.server_command(
            args, Path("learner.bin"), Path("baseline.bin")
        )

        self.assertEqual(sampled[-1], "--sample")
        self.assertNotIn("--sample", greedy)

    def test_server_cycle_hides_training_gpu_from_child(self):
        subprocess_result = mock.Mock(returncode=0)
        with mock.patch.dict(
            follow_latest.os.environ,
            {"CUDA_VISIBLE_DEVICES": "0", "BBTV_TEST_VALUE": "preserved"},
            clear=True,
        ), mock.patch.object(
            follow_latest.subprocess, "run", return_value=subprocess_result
        ) as run:
            result = follow_latest.run_server_cycle(
                ["viewer-python", "server.py"],
                cwd=Path("stream_backend"),
                pythonpath=Path("cpu-viewer"),
                timeout_seconds=12.5,
            )

        self.assertIs(result, subprocess_result)
        run.assert_called_once_with(
            ["viewer-python", "server.py"],
            cwd=Path("stream_backend"),
            env={
                "CUDA_VISIBLE_DEVICES": "",
                "BBTV_TEST_VALUE": "preserved",
                "PYTHONPATH": "cpu-viewer",
            },
            check=False,
            timeout=12.5,
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
            server_pythonpath = root / "cpu-viewer"
            (server_pythonpath / "pufferlib").mkdir(parents=True)
            with mock.patch.object(
                    follow_latest.argparse.ArgumentParser, "error",
                    side_effect=AssertionError):
                args = follow_latest.parse_args([
                    "--checkpoint-root", str(checkpoint_root),
                    "--checkpoint-root", str(root / "future-checkpoints"),
                    "--state-dir", str(root / "state"),
                    "--converter-python", str(venv_python),
                    "--converter-script", str(script),
                    "--config", str(script),
                    "--server-python", str(venv_python),
                    "--server-pythonpath", str(server_pythonpath),
                    "--server-script", str(script),
                    "--sample",
                ])
        self.assertEqual(args.converter_python, venv_python.absolute())
        self.assertNotEqual(args.converter_python, real_python.resolve())
        self.assertEqual(
            args.checkpoint_roots,
            [checkpoint_root.resolve(), (root / "future-checkpoints").resolve()],
        )
        self.assertTrue(args.sample)

    def test_recovery_follower_reads_both_roots_and_writes_new_state(self):
        root = Path(__file__).resolve().parents[1]
        override = (root / "stream_backend/bbstream-follow-latest.conf").read_text(
            encoding="utf-8"
        )
        launcher = (root / "stream_backend/run_follow_latest.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "bloodbowl-rl-audit/vendor/PufferLib/checkpoints/bloodbowl:",
            override,
        )
        self.assertIn(
            "bloodbowl-rl-recovery-20260719/vendor/PufferLib/checkpoints/bloodbowl",
            override,
        )
        self.assertIn(
            "BBTV_STATE_DIR=%h/bloodbowl-rl-recovery-20260719/runs/bbtv-follow",
            override,
        )
        self.assertIn("BBTV_ROOT=%h/bloodbowl-rl", override)
        self.assertIn(
            "ExecStart=%h/bloodbowl-rl-recovery-20260719/stream_backend/"
            "run_follow_latest.sh",
            override,
        )
        self.assertIn('SCRIPT_ROOT="$(cd ', launcher)
        self.assertIn('ROOT=${BBTV_ROOT:-"$SCRIPT_ROOT"}', launcher)
        self.assertIn(
            'STATE_DIR=${BBTV_STATE_DIR:-"$RECOVERY_ROOT/runs/bbtv-follow"}',
            launcher,
        )
        self.assertNotIn(
            'STATE_DIR=${BBTV_STATE_DIR:-"$AUDIT_ROOT/runs/bbtv-follow"}',
            launcher,
        )
        self.assertIn(
            '"$SCRIPT_ROOT/stream_backend/follow_latest.py"', launcher
        )
        self.assertIn('"${CHECKPOINT_ARGS[@]}"', launcher)
        self.assertIn('--state-dir "$STATE_DIR"', launcher)


if __name__ == "__main__":
    unittest.main()
