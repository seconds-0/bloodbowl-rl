#!/usr/bin/env python3

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PUFFERL_SOURCE = ROOT / "vendor/PufferLib/pufferlib/pufferl.py"
VENDOR_CHECKOUT = PUFFERL_SOURCE.is_file()


def run_script(script, *args, env=None):
    merged = os.environ.copy()
    if env:
        merged.update(env)
    return subprocess.run(
        ["bash", str(ROOT / script), *map(str, args)],
        cwd=ROOT,
        env=merged,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class ExperimentContractTests(unittest.TestCase):
    def test_reward_launcher_rejects_every_trailing_override_first(self):
        result = run_script(
            "tools/run_reward_ablation.sh",
            "--train.total-timesteps", "1",
            env={
                "TAG": "contract-test",
                "REWARD_MANIFEST": "missing.json",
                "WARM": "missing.bin",
                "POOL": "missing-pool",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trailing Puffer overrides are not allowed", result.stderr)
        self.assertNotIn("missing reward manifest", result.stderr)

    def test_frozen_eval_rejects_trailing_override_before_checkpoint_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script(
                "tools/eval_game_stats.sh", "missing.bin", "1",
                Path(tmp) / "out.log", "--env.demo-reset-pct", "0.9")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("trailing Puffer overrides are not allowed", result.stderr)
        self.assertNotIn("checkpoint not found", result.stderr)

    def test_scripted_eval_rejects_invalid_bot_before_checkpoint_io(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script(
                "tools/eval_vs_contact_bot.sh", "missing.bin", "1",
                Path(tmp) / "out.log", env={"BOT_TYPE": "2", "BOT_TEAM": "1"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("BOT_TYPE must be 0", result.stderr)
        self.assertNotIn("checkpoint not found", result.stderr)

    def test_scripted_eval_bounds_and_records_explicit_eval_games(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_script(
                "tools/eval_vs_contact_bot.sh", "missing.bin", "1",
                Path(tmp) / "out.log", env={"EVAL_EPISODES": "0"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("EVAL_EPISODES must be a positive integer", result.stderr)
        self.assertNotIn("checkpoint not found", result.stderr)

        source = (ROOT / "tools/eval_vs_contact_bot.sh").read_text(
            encoding="utf-8")
        self.assertIn('CMD+=(--eval-episodes "$EVAL_EPISODES")', source)
        self.assertNotIn("--train.eval-episodes", source)
        self.assertIn('"eval_episodes":', source)
        self.assertIn('"min_eval_games":', source)
        self.assertIn('"pufferl_sha256":', source)
        self.assertIn('"launcher_sha256":', source)
        self.assertIn("_puffer_eval_episodes_completed", source)
        self.assertIn("scripted eval sample too small", source)

    @unittest.skipUnless(VENDOR_CHECKOUT, "vendored Puffer checkout unavailable")
    def test_puffer_eval_gate_accumulates_torch_intervals(self):
        source = PUFFERL_SOURCE.read_text(encoding="utf-8")
        self.assertIn(
            "eval_episodes_completed += flat_logs['env/n']", source)
        self.assertIn(
            "eval_episodes_completed = flat_logs['env/n']", source)
        self.assertIn(
            "eval_episodes_completed >= args['eval_episodes']", source)
        self.assertNotIn(
            "flat_logs['env/n'] > args['eval_episodes']", source)
        self.assertIn("metrics.setdefault(k, [[]])", source)

    def test_all_contract_scripts_bind_the_vendored_puffer_entrypoint(self):
        for relative in (
            "tools/run_reward_ablation.sh",
            "tools/eval_game_stats.sh",
            "tools/eval_vs_contact_bot.sh",
        ):
            source = (ROOT / relative).read_text(encoding="utf-8")
            self.assertIn(
                'PUFFER_BIN="$ROOT/vendor/PufferLib/.venv/bin/puffer"', source)
            self.assertNotIn("\npuffer train bloodbowl", source)

    def test_reward_screen_rejects_trailing_arguments_before_artifact_io(self):
        result = run_script("tools/run_reward_screen.sh", "--override")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("named environment variables only", result.stderr)
        self.assertNotIn("WARM is required", result.stderr)

    def test_reward_screen_freezes_and_revalidates_one_causal_plan(self):
        source = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8")
        for contract in (
            "SCREEN_MANIFEST.json",
            "SCREEN_MANIFEST_SHA256",
            "SCREEN_COMPLETE.json",
            "materialize_result validate",
            'TOTAL_AGENTS=2048',
            'MIN_EVAL_GAMES=10001',
            'DRY_RUN=0',
            'process.json',
            'acceptance_pass',
        ):
            self.assertIn(contract, source)
        self.assertNotIn('TOTAL_AGENTS="${TOTAL_AGENTS:-', source)

    def test_screen_and_arm_fail_fast_on_patch_bundle_drift(self):
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8")
        arm = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8")
        self.assertIn(
            'EXPECTED_PUFFER_PATCH_BUNDLE_SHA256="$SCREEN_PATCH_BUNDLE_SHA"',
            screen,
        )
        self.assertIn(
            'PATCH_HASH" != "$EXPECTED_PUFFER_PATCH_BUNDLE_SHA256"', arm
        )
        for patch in (
            "pufferl_env_dashboard_limit.patch",
            "pufferl_env_json.patch",
            "pufferl_env_json_metadata_upgrade.patch",
            "pufferl_env_phase_contract.patch",
            "pufferl_eval_episode_gate.patch",
            "pufferl_metrics_keyerror.patch",
            "torch_pufferl_trusted_load.patch",
        ):
            self.assertIn(patch, screen)
            self.assertIn(patch, arm)

    def test_reward_screen_has_exact_possession_gain_decomposition(self):
        source = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8")
        for arm in ("both", "possession_only", "gain_only", "neither"):
            self.assertIn(arm, source)
        self.assertIn(
            ': "${SCREEN_PROFILE:?SCREEN_PROFILE is required ', source)
        self.assertIn(': "${STEPS:?STEPS is required ', source)
        self.assertNotIn('SCREEN_PROFILE="${SCREEN_PROFILE:-', source)
        self.assertNotIn('STEPS="${STEPS:-', source)

        possession = (ROOT / "puffer/config/rewards/p1_possession_only.json")
        gain = (ROOT / "puffer/config/rewards/p2_gain_only.json")
        self.assertTrue(possession.is_file())
        self.assertTrue(gain.is_file())

    @unittest.skipUnless(VENDOR_CHECKOUT, "vendored Puffer checkout unavailable")
    def test_puffer_machine_log_uses_explicit_loop_phase_and_fresh_panels(self):
        source = PUFFERL_SOURCE.read_text(encoding="utf-8")
        self.assertIn("'_puffer_schema': 2", source)
        self.assertIn("phase_eval = epoch >= train_epochs", source)
        self.assertIn("phase_eval=phase_eval, phase_epoch=epoch", source)
        self.assertIn("if not key.startswith('env/')", source)
        self.assertNotIn("phase_eval = epoch >= train_epochs and epoch >= 0", source)

    def test_reward_launcher_publishes_exact_process_contract(self):
        source = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8")
        self.assertIn('PROCESS_FILE="${LOG}.process.json"', source)
        self.assertIn('expected_checkpoint_bytes "$EXPECT_BYTES"', source)
        self.assertIn('screen_manifest_sha256 "$SCREEN_MANIFEST_SHA256"', source)
        self.assertIn("from pufferlib import _C; print(_C.__file__)", source)
        self.assertNotIn("find pufferlib -maxdepth 1 -name '_C*.so'", source)


if __name__ == "__main__":
    unittest.main()
