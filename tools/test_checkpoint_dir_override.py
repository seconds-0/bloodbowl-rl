from pathlib import Path
import os
import re
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CheckpointDirectoryOverrideTests(unittest.TestCase):
    def setUp(self):
        self.arm = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8")
        self.screen = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8")

    def arm_env(self, log, checkpoint_dir):
        return {
            "PATH": os.environ["PATH"],
            "TAG": "checkpoint-path-test",
            "REWARD_MANIFEST": str(ROOT / "puffer/config/rewards/r0_full.json"),
            "BOOTSTRAP_MODE": "fresh-v7-qualification",
            "LOG": str(log),
            "CHECKPOINT_DIR": str(checkpoint_dir),
        }

    def test_arm_passes_and_records_the_effective_absolute_directory(self):
        self.assertIn('--checkpoint-dir "$CHECKPOINT_DIR"', self.arm)
        self.assertIn('checkpoint_dir "$CHECKPOINT_DIR"', self.arm)
        self.assertIn('CHECKPOINT_ROOT="$CHECKPOINT_DIR/bloodbowl"', self.arm)
        self.assertNotIn('find checkpoints/bloodbowl ', self.arm)
        self.assertNotIn('for directory in checkpoints/bloodbowl/', self.arm)

    def test_arm_routes_puffer_json_logs_beside_the_owned_arm_log(self):
        self.assertIn('PUFFER_LOG_DIR="${LOG}.puffer-logs"', self.arm)
        self.assertIn('--log-dir "$PUFFER_LOG_DIR"', self.arm)
        self.assertIn('puffer_log_dir "$PUFFER_LOG_DIR"', self.arm)
        checkpoint_position = self.arm.index('--checkpoint-dir "$CHECKPOINT_DIR"')
        log_position = self.arm.index('--log-dir "$PUFFER_LOG_DIR"')
        self.assertLess(checkpoint_position, log_position)

    def test_puffer_log_root_rejects_file_and_symlink_collisions(self):
        self.assertIn(
            'Puffer log directory must not be a symbolic link', self.arm)
        self.assertIn(
            'Puffer log directory exists and is not a directory', self.arm)
        for collision in ("file", "symlink"):
            with self.subTest(collision=collision), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                log = root / "screen" / "arm.log"
                log.parent.mkdir()
                puffer_logs = Path(str(log) + ".puffer-logs")
                if collision == "file":
                    puffer_logs.write_text("collision")
                    expected = "exists and is not a directory"
                else:
                    target = root / "elsewhere"
                    target.mkdir()
                    puffer_logs.symlink_to(target, target_is_directory=True)
                    expected = "must not be a symbolic link"
                result = subprocess.run(
                    ["bash", str(ROOT / "tools/run_reward_ablation.sh")],
                    cwd=ROOT, env=self.arm_env(log, root / "checkpoints"),
                    text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)

    def test_screen_propagates_one_directory_to_launch_and_acceptance(self):
        self.assertIn('CHECKPOINT_DIR="$CHECKPOINT_DIR"', self.screen)
        self.assertIn('"checkpoint_dir": (os.environ["CHECKPOINT_DIR"] or',
                      self.screen)
        self.assertIn('pathlib.Path(checkpoint_dir) / "bloodbowl"', self.screen)
        self.assertIn(
            'arm checkpoint directory differs from the screen contract',
            self.screen)
        self.assertIn('screen manifest checkpoint directory differs', self.screen)
        self.assertNotIn(
            'root / "vendor/PufferLib/checkpoints/bloodbowl"', self.screen)

    def test_both_entrypoints_reject_relative_and_root_overrides(self):
        for source in (self.arm, self.screen):
            self.assertRegex(source, re.compile(
                r'CHECKPOINT_DIR must be an absolute path'))
            self.assertIn('CHECKPOINT_DIR must not be the filesystem root', source)
            self.assertIn(
                'CHECKPOINT_DIR must not resolve to the filesystem root', source)

    def test_actual_discovery_helpers_ignore_legacy_and_existing_decoys(self):
        match = re.search(
            r'# CHECKPOINT_DISCOVERY_HELPERS_BEGIN\n(.*?)'
            r'# CHECKPOINT_DISCOVERY_HELPERS_END', self.arm, re.S)
        self.assertIsNotNone(match)
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            legacy = temporary / "canonical" / "bloodbowl"
            override = temporary / "owned" / "bloodbowl"
            legacy.mkdir(parents=True)
            override.mkdir(parents=True)
            (legacy / "decoy-canonical").mkdir()
            (override / "existing-owned").mkdir()
            before = temporary / "before.txt"
            script = match.group(1) + r'''
snapshot_checkpoint_runs "$1" "$2"
mkdir "$1/new-owned"
new_checkpoint_runs "$1" "$2"
'''
            result = subprocess.run(
                ["bash", "-c", script, "checkpoint-test", str(override),
                 str(before)], text=True, capture_output=True, check=True)
            self.assertEqual(
                result.stdout.splitlines(), [str(override / "new-owned")])
            self.assertNotIn("decoy-canonical", result.stdout)
            self.assertNotIn("existing-owned", result.stdout)

    def test_actual_screen_entrypoint_rejects_relative_override_before_work(self):
        result = subprocess.run(
            ["bash", str(ROOT / "tools/run_reward_screen.sh")],
            cwd=ROOT, env={
                "PATH": os.environ["PATH"],
                "STEPS": "1",
                "SCREEN_PROFILE": "exact-action-canary",
                "CHECKPOINT_DIR": "relative/checkpoints",
            }, text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CHECKPOINT_DIR must be an absolute path", result.stderr)

    def test_actual_screen_entrypoint_rejects_symlinked_bloodbowl_root(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            checkpoint_dir = temporary / "checkpoints"
            target = temporary / "target"
            checkpoint_dir.mkdir()
            target.mkdir()
            (checkpoint_dir / "bloodbowl").symlink_to(target,
                                                       target_is_directory=True)
            result = subprocess.run(
                ["bash", str(ROOT / "tools/run_reward_screen.sh")],
                cwd=ROOT, env={
                    "PATH": os.environ["PATH"],
                    "STEPS": "1",
                    "SCREEN_PROFILE": "exact-action-canary",
                    "CHECKPOINT_DIR": str(checkpoint_dir),
                }, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("checkpoint root must not be a symbolic link",
                          result.stderr)

    def test_unset_override_preserves_the_legacy_vendor_default(self):
        self.assertIn(
            'CHECKPOINT_DIR="$ROOT/vendor/PufferLib/checkpoints"', self.arm)
        self.assertIn(
            '${CHECKPOINT_DIR:-$ROOT/vendor/PufferLib/checkpoints}', self.screen)


if __name__ == "__main__":
    unittest.main()
