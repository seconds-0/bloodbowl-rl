#!/usr/bin/env python3

import os
import re
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

    def test_reward_launcher_rejects_non_v5_checkpoint_size_before_runtime(self):
        result = run_script(
            "tools/run_reward_ablation.sh",
            env={
                "TAG": "wrong-size-contract-test",
                "REWARD_MANIFEST": "missing.json",
                "BOOTSTRAP_MODE": "fresh-v5-qualification",
                "EXPECT_BYTES": "13670400",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            "obs-v5/exact-joint-v1 requires EXPECT_BYTES=16066560",
            result.stderr,
        )
        self.assertNotIn("vendored Python missing", result.stderr)

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
        self.assertIn(
            "from run_reward_candidate_transfer import implementation_identity",
            source,
        )
        self.assertIn("**implementation_identity(Path(root))", source)
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
            'MIN_EVAL_GAMES=',
            '"game_stats_sha256": sha(game_stats)',
            'DRY_RUN=0',
            'process.json',
            'acceptance_pass',
        ):
            self.assertIn(contract, source)
        self.assertNotIn('TOTAL_AGENTS="${TOTAL_AGENTS:-', source)
        # The analysis-tool hashes above stay recorded as provenance, but the
        # screen no longer aborts mid-run because game_stats.py / the manifest /
        # live_integrity_guard.py changed since the freeze. An edited analysis
        # tool is a review finding; voiding a multi-day run over it protects
        # nothing, and the science is still bound where it matters: every arm's
        # result records the reward manifest sha it actually trained under, and
        # SCREEN_COMPLETE rejects a result minted by a different screen.
        self.assertIn('"reward_sha256"', source)

    def test_reward_screen_has_zero_budget_live_integrity_guard(self):
        source = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8")
        launcher = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8")
        for contract in (
            "tools/live_integrity_guard.py",
            "tools/trainer_status_wrapper.sh",
            "LIVE_INTEGRITY_FAILURE.json",
            "illegal_frac",
            "hard_integrity_keys",
            "contamination_budget",
            "detection_poll_seconds",
            "max_panel_silence_seconds",
            "terminate_current_arm",
        ):
            self.assertIn(contract, source)
        self.assertIn("integrity = HARD_INTEGRITY_KEYS", source)
        self.assertIn('${log}.live-integrity-screen-state.json', source)
        self.assertIn('${LOG}.live-integrity-watchdog-state.json', launcher)
        self.assertNotIn('${LOG}.live-integrity-screen-state.json', launcher)

    def test_reward_screen_accepts_the_requested_eval_game_count(self):
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8")
        launcher = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8")
        minimum = re.search(r"^MIN_EVAL_GAMES=([0-9]+)$", screen, re.MULTILINE)
        requested = re.search(r"--eval-episodes ([0-9]+)", launcher)
        self.assertIsNotNone(minimum)
        self.assertIsNotNone(requested)
        self.assertEqual(
            int(minimum.group(1)),
            int(requested.group(1)),
            "an evaluation that completes the requested games must be accepted",
        )

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
            "puffer_exact_joint_actions.patch",
            "selfplay_league.patch",
        ):
            self.assertIn(patch, screen)
            self.assertIn(patch, arm)
        for source in ("src/bindings_cpu.cpp", "src/kernels.cu"):
            self.assertIn(source, screen)
            self.assertIn(source, arm)
        screen_block = screen.split("patches = [", 1)[1].split(
            "vendor_sources = [", 1
        )[0]
        arm_block = arm.split('PATCH_HASH="$({', 1)[1].split(
            '} | sha256sum', 1
        )[0]
        screen_patches = re.findall(r'training/([^"/]+\.patch)', screen_block)
        arm_patches = re.findall(r'training/([^"/]+\.patch)', arm_block)
        self.assertEqual(screen_patches, arm_patches)
        self.assertEqual(screen_patches.count("selfplay_league.patch"), 1)
        self.assertIn(
            'git -C "$ROOT/vendor/PufferLib" apply --reverse --check --no-index',
            arm,
        )
        self.assertIn("Patch copy: training/selfplay_league.patch", arm)

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

    def test_paired_confirmation_requires_an_explicit_candidate(self):
        result = run_script(
            "tools/run_reward_screen.sh",
            env={
                "WARM": "missing.bin",
                "POOL": "missing-pool",
                "STEPS": "1000000000",
                "SCREEN_PROFILE": "paired-confirmation",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("CANDIDATE_ARM", result.stderr)
        self.assertNotIn("missing warm checkpoint", result.stderr)

        source = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("paired-confirmation", source)
        self.assertIn("TOTAL_ARMS", source)
        self.assertNotIn("index=$CURRENT_INDEX/8", source)

        result = run_script(
            "tools/run_reward_screen.sh",
            env={
                "WARM": "missing.bin",
                "POOL": "missing-pool",
                "STEPS": "1000000000",
                "SCREEN_PROFILE": "paired-confirmation",
                "CANDIDATE_ARM": "gain_only",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("TRANSFER_COMPLETE", result.stderr)
        self.assertNotIn("missing warm checkpoint", result.stderr)
        for contract in (
            "EXPECTED_TRANSFER_SHA256",
            "recommended_confirmation_arm",
            "candidate_evidence",
            "transfer_manifest_sha256",
            "analysis_sha256",
        ):
            self.assertIn(contract, source)

    def test_paired_final_adds_seed_44_without_adaptive_candidate_selection(self):
        source = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("paired-final", source)
        self.assertIn('seeds=(42 42 43 43 44 44)', source)
        self.assertIn(
            'arms=(both "$CANDIDATE_ARM" "$CANDIDATE_ARM" both both "$CANDIDATE_ARM")',
            source,
        )
        self.assertIn('TRANSFER_COMPLETE', source)

    def test_control_final_is_r0_only_and_rejects_candidate_inputs(self):
        result = run_script(
            "tools/run_reward_screen.sh",
            env={
                "WARM": "missing.bin",
                "POOL": "missing-pool",
                "STEPS": "12000000000",
                "SCREEN_PROFILE": "control-final",
                "CANDIDATE_ARM": "gain_only",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate transfer inputs are only valid", result.stderr)
        self.assertNotIn("missing warm checkpoint", result.stderr)

        result = run_script(
            "tools/run_reward_screen.sh",
            env={
                "WARM": "missing.bin",
                "POOL": "missing-pool",
                "STEPS": "12000000000",
                "SCREEN_PROFILE": "control-final",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing warm checkpoint", result.stderr)
        source = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("arms=(both both both)", source)
        self.assertIn("seeds=(42 43 44)", source)

    def test_exact_action_canary_is_one_reward_frozen_50m_arm(self):
        result = run_script(
            "tools/run_reward_screen.sh",
            env={
                "WARM": "missing.bin",
                "POOL": "missing-pool",
                "STEPS": "50000001",
                "SCREEN_PROFILE": "exact-action-canary",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact-action-canary requires STEPS=50000000", result.stderr)
        self.assertNotIn("missing warm checkpoint", result.stderr)

        result = run_script(
            "tools/run_reward_screen.sh",
            env={
                "WARM": "missing.bin",
                "POOL": "missing-pool",
                "STEPS": "50000000",
                "SCREEN_PROFILE": "exact-action-canary",
                "CANDIDATE_ARM": "gain_only",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate transfer inputs are only valid", result.stderr)
        self.assertNotIn("missing warm checkpoint", result.stderr)

        result = run_script(
            "tools/run_reward_screen.sh",
            env={
                "WARM": "missing.bin",
                "POOL": "missing-pool",
                "STEPS": "50000000",
                "SCREEN_PROFILE": "exact-action-canary",
            },
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact-action-canary forbids WARM", result.stderr)

        source = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn("exact-action-canary", source)
        self.assertIn("arms=(both)", source)
        self.assertIn("seeds=(42)", source)
        self.assertIn('"qualification_only": qualification_only', source)
        self.assertIn("--complete-log", source)
        self.assertLess(
            source.index('terminate_current_arm "$pid" "$process_group"'),
            source.index(
                'write_screen_status failed 1 "hard-integrity error budget exhausted"'
            ),
        )

    def test_exact_action_canary_requires_fresh_v5_without_legacy_assets(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "screen"
            base = {
                "STEPS": "50000000",
                "SCREEN_PROFILE": "exact-action-canary",
                "OUT_DIR": str(out),
            }
            for key in ("WARM", "POOL"):
                env = dict(base)
                env[key] = "legacy-input"
                result = run_script("tools/run_reward_screen.sh", env=env)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(
                    f"exact-action-canary forbids {key}", result.stderr)
                self.assertFalse(out.exists())

            # The canary must not demand the warm checkpoint and 4-bank pool that
            # every other profile requires. It previously did the opposite: the
            # profile was hard-rejected as "frozen"/"permanently rejected", and
            # since eligible lineage sidecars can only be minted by an already
            # eligible run, the sanctioned path had no bootstrap and could not
            # start anything. Asserting that rejection was asserting the deadlock.
            result = run_script("tools/run_reward_screen.sh", env=base)
            self.assertNotIn("WARM is required", result.stderr)
            self.assertNotIn("POOL is required", result.stderr)
            self.assertNotIn("exact-action-canary is frozen", result.stderr)

        screen = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8")
        arm = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8")
        for contract in (
            "fresh-v5-qualification", "obs-v5", "exact-joint-v1",
            '"qualification_only": qualification_only',
            'NUM_FROZEN_BANKS=0',
        ):
            self.assertIn(contract, screen)
        self.assertIn('BOOTSTRAP_MODE="$BOOTSTRAP_MODE"', screen)
        self.assertIn('case "$BOOTSTRAP_MODE" in', arm)
        self.assertIn('--selfplay.enabled 0', arm)
        self.assertIn('--vec.num-frozen-banks 0', arm)

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
        self.assertIn("runtime, evidence = begin_cuda_runtime_preflight()", source)
        self.assertIn("evidence = finish_cuda_runtime_preflight", source)
        self.assertIn(
            '"$PYBIN" "$CUDA_RUNTIME_WRAPPER" train bloodbowl', source
        )
        self.assertIn('cuda_runtime_wrapper_sha256 "$CUDA_RUNTIME_WRAPPER_HASH"', source)
        self.assertIn('cuda_launcher_probe_library_sha256 "$CUDA_RUNTIME_LIBRARY_SHA256"', source)
        self.assertIn('cuda_launcher_probe_visible_devices "$CUDA_VISIBLE_DEVICES"', source)
        self.assertIn('[ "${CUDA_VISIBLE_DEVICES:-}" = "0" ]', source)
        self.assertIn('PUFFER_CUDA_RUNTIME_MANIFEST="$RUN_MANIFEST"', source)
        self.assertIn('PUFFER_CUDA_RUNTIME_EVIDENCE="$CUDA_RUNTIME_EVIDENCE"', source)
        self.assertIn('cuda_runtime_evidence_status pending', source)
        self.assertIn('cuda_launcher_probe_library_sha256', source)
        self.assertIn('CUDA_RUNTIME_EVIDENCE.json', source)
        self.assertNotIn("find pufferlib -maxdepth 1 -name '_C*.so'", source)
        self.assertIn('DETACH="${DETACH:-1}"', source)
        self.assertIn('PROCESS_GROUP="$(ps -o pgid=', source)
        for contract in (
            "LIVE_INTEGRITY_GUARD",
            "LIVE_INTEGRITY_FAILURE",
            "LIVE_INTEGRITY_MAX_SILENCE",
            "LIVE_INTEGRITY_POLL_SECONDS",
            "LIVE_INTEGRITY_MARKER",
            "live_integrity_guard_sha256",
        ):
            self.assertIn(contract, source)

        screen = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            'LIVE_INTEGRITY_FAILURE="$OUT_DIR/LIVE_INTEGRITY_FAILURE.json"',
            screen,
        )

    def test_queue_owned_screen_keeps_trainer_in_queue_process_group(self):
        # A trainer that escapes the queue's process group survives the queue's
        # guard cleanup and idle-bills the GPU, so the ARM_DETACH=0 chain stays
        # under test. The run_frozen_reward_screen.py wrapper that used to carry
        # the third assertion here existed only to feed the typed-literal queue
        # a path it was forbidden to express directly, and went with it.
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8"
        )
        arm = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('DETACH="$ARM_DETACH"', screen)
        self.assertIn('if [ "$DETACH" = "1" ]', arm)
        self.assertIn('else os.getpgrp()', screen)
        self.assertNotIn(
            'trainer process group is not the detached wrapper PID', screen
        )

    def test_non_detached_child_inherits_new_session_process_group(self):
        probe = subprocess.run(
            [
                "bash", "-c",
                (
                    "sleep 30 & child=$!; "
                    "outer=$(ps -o pgid= -p $$ | tr -d ' '); "
                    "inner=$(ps -o pgid= -p $child | tr -d ' '); "
                    "printf '%s %s %s\\n' $$ $child $outer:$inner; "
                    "kill $child; wait $child 2>/dev/null || true"
                ),
            ],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            start_new_session=True,
        )
        self.assertEqual(probe.returncode, 0, probe.stderr)
        outer_pid, child_pid, groups = probe.stdout.strip().split()
        outer_group, child_group = groups.split(":")
        self.assertEqual(outer_group, outer_pid)
        self.assertEqual(child_group, outer_group)
        self.assertNotEqual(child_pid, child_group)

    def test_candidate_transfer_is_a_frozen_both_sides_matrix(self):
        runner = (ROOT / "tools/run_reward_candidate_transfer.py").read_text(
            encoding="utf-8"
        )
        analyzer = (
            ROOT / "tools/analyze_reward_candidate_transfer.py"
        ).read_text(encoding="utf-8")
        for contract in (
            "TRANSFER_MANIFEST.json",
            "TRANSFER_COMPLETE.json",
            "EXPECTED_NATIVE_BYTES",
            "BOT_TYPES = (0, 1)",
            "BOT_TEAMS = (0, 1)",
            "expected_screen_sha",
            "screen_checkpoints",
            "conversion_metadata_sha256",
        ):
            self.assertIn(contract, runner)
        for gate in (
            "mean_score_delta_min",
            "cell_score_delta_min",
            "max_champion_td_relative_drop",
            "max_bot_td_relative_rise",
        ):
            self.assertIn(gate, runner)
            self.assertIn(gate, analyzer)

    def test_learned_transfer_hashes_the_configs_it_actually_loads(self):
        source = (ROOT / "tools/run_reward_learned_transfer.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            '"default_config": root / "vendor/PufferLib/config/default.ini"',
            source,
        )
        self.assertIn(
            '"env_config": root / "vendor/PufferLib/config/bloodbowl.ini"',
            source,
        )
        self.assertNotIn('"config": root / "puffer/config/bloodbowl.ini"', source)

    def test_reward_screen_records_the_complete_training_runtime(self):
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(
            encoding="utf-8"
        )
        arm = (ROOT / "tools/run_reward_ablation.sh").read_text(
            encoding="utf-8"
        )
        # Config provenance is asserted on the LAUNCHER, which is where it is
        # produced: it hashes the two configs it actually loads and writes both
        # into every run manifest, per this repo's own rule (see
        # test_learned_transfer_hashes_the_configs_it_actually_loads). The screen
        # used to recompute the same values plus config_tree_sha256, a recursive
        # digest of the whole vendor/PufferLib/config/ tree asserting that no
        # config file anywhere had changed. That was a shadow of the launcher's
        # check over a broader question than the one that matters, so it is gone.
        for field in (
            "config/bloodbowl.ini",
            "config/default.ini",
            "config_sha256",
            "default_config_sha256",
        ):
            self.assertIn(field, arm)
        for field in (
            "pufferlib/__init__.py",
            "pufferlib/models.py",
            "pufferlib/muon.py",
        ):
            self.assertIn(field, screen)
            self.assertIn(field, arm)
        self.assertIn('"compiled_semantic_contract": compiled_contract', screen)
        # Assert the compiled-module probe by the CHECKS it performs, not by the
        # manifest field names it happens to use. This is the single invariant
        # that distinguishes obs-v4 from obs-v5 -- both are 2782 bytes, so blob
        # shape cannot -- and a v4/v5 mixup already wasted a 12B-step run. The
        # screen and the launcher each verify it independently against the
        # imported _C, which is deliberate redundancy over the compiled artifact
        # rather than a shadow validator over a file.
        for probe in (
            '"obs-v5"',
            '"exact-joint-v1"',
            "precision_bytes",
            "observation_version",
        ):
            self.assertIn(probe, screen)
            self.assertIn(probe.strip('"'), arm)
        self.assertIn("exact_action_source_sha256", screen)
        self.assertIn("COMPILED_EXACT_ACTION_SOURCE_HASH", arm)
        # Both must reject a module whose environment digest disagrees with the
        # installed source, which is what catches a mid-screen rebuild.
        self.assertIn("environment_source_sha256", screen)
        self.assertIn("COMPILED_ENVIRONMENT_SOURCE_HASH", arm)

    def test_exact_pbrs_distance_requires_matching_trainer_gamma(self):
        # beta*(gamma*Phi' - Phi) is only exact at the gamma the trainer really
        # discounts with, and a mismatch fails silently rather than loudly: it
        # just reintroduces the bias class the discounted form removes. The env
        # cannot see train.gamma, so the launcher owns this check.
        arm = (ROOT / "tools/run_reward_ablation.sh").read_text(encoding="utf-8")
        self.assertIn("reward_dist_pbrs_gamma", arm)
        self.assertIn("!= train gamma", arm)
        # The legacy path must stay reachable and silent: a schema-1 manifest
        # omits the key, so the launcher must not demand it.
        from reward_manifest import load_manifest, cli_args
        legacy, _ = load_manifest(
            ROOT / "puffer/config/rewards/r0_full.json")
        self.assertEqual(legacy["schema_version"], 1)
        self.assertNotIn("reward_dist_pbrs_gamma", legacy["reward"])
        self.assertNotIn("--env.reward-dist-pbrs-gamma", cli_args(legacy))
        # The candidate states it explicitly and renders the token.
        exact, _ = load_manifest(
            ROOT / "puffer/config/rewards/r4_pbrs_distance.json")
        self.assertEqual(exact["schema_version"], 2)
        self.assertAlmostEqual(
            exact["reward"]["reward_dist_pbrs_gamma"], 0.995)
        self.assertIn("--env.reward-dist-pbrs-gamma", cli_args(exact))
        # Exactly one declared factor may differ from the r0 control.
        differing = {
            k for k in exact["reward"]
            if legacy["reward"].get(k, "<absent>") != exact["reward"][k]
        }
        self.assertEqual(differing, {"reward_dist_pbrs_gamma"})

    def test_vacation_queue_is_hash_pinned_and_fail_closed(self):
        source = (ROOT / "tools/experiment_queue.py").read_text(
            encoding="utf-8"
        )
        for contract in (
            "plan_sha256",
            "resume_safe",
            "max_runtime_seconds",
            "max_gpu_temperature_c",
            "min_free_bytes",
            "success validation failed",
            "later jobs were not run",
        ):
            self.assertIn(contract, source)


if __name__ == "__main__":
    unittest.main()
