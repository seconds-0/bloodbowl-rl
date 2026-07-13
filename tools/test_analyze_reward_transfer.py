#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import analyze_reward_transfer as transfer


class RewardTransferAnalyzerTests(unittest.TestCase):
    def write_cell(self, root, arm, seed, bot_type, bot_team):
        score = 0.4 if arm == "r0" else 0.6
        champion_team = 1 - bot_team
        manifest = {
            "schema_version": 1,
            "mode": "scripted_bot_frozen",
            "checkpoint_sha256": transfer.EXPECTED_CHECKPOINT_SHA[(arm, seed)],
            "requested_train_steps": transfer.EXPECTED_STEPS,
            "seed": seed,
            "config_sha256": transfer.EXPECTED_CONFIG_SHA,
            "compiled_module_sha256": transfer.EXPECTED_MODULE_SHA,
            "pufferl_sha256": transfer.EXPECTED_PUFFERL_SHA,
            "launcher_sha256": transfer.EXPECTED_LAUNCHER_SHA,
            "bot_type": bot_type,
            "bot_team": bot_team,
            "eval_episodes": transfer.EXPECTED_GAMES,
            "min_eval_games": transfer.EXPECTED_GAMES,
            "command": [
                "puffer", "train", "bloodbowl",
                "--train.total-timesteps", str(transfer.EXPECTED_STEPS),
                "--eval-episodes", str(transfer.EXPECTED_GAMES),
                "--seed", str(seed), "--train.seed", str(seed),
                "--env.seed", str(seed),
                "--env.scripted-opponent-type", str(bot_type),
                "--env.scripted-opponent-team", str(bot_team),
            ],
        }
        panel = {
            "_puffer_schema": 2,
            "_puffer_phase_eval": 1,
            "_puffer_env_cumulative": 0,
            "_puffer_final_reprint": 0,
            "_puffer_eval_episodes_completed": transfer.EXPECTED_GAMES,
            "n": transfer.EXPECTED_GAMES,
            "slot_0_score": score if champion_team == 0 else 1 - score,
            "slot_1_score": score if champion_team == 1 else 1 - score,
            "draw_rate": 0.4,
            "tds_t0": 1.0 if champion_team == 0 else 0.5,
            "tds_t1": 1.0 if champion_team == 1 else 0.5,
            "blocks_thrown_t0": 8.0 if champion_team == 0 else 10.0,
            "blocks_thrown_t1": 8.0 if champion_team == 1 else 10.0,
            "reward_clip_episodes": 0,
            "reward_nonfinite_episodes": 0,
            "error_episodes": 0,
            "demo_episodes": 0,
            "demo_fallbacks": 0,
        }
        final = dict(panel, _puffer_final_reprint=1)
        path = root / f"{arm}-s{seed}-b{bot_type}-t{bot_team}.log"
        path.write_text(
            transfer.MANIFEST_PREFIX + json.dumps(manifest) + "\n"
            "PufferLib 4.0\nPUFFER_ENV_JSON " + json.dumps(panel) + "\n"
            "PufferLib 4.0\nPUFFER_ENV_JSON " + json.dumps(final) + "\n",
            encoding="utf-8",
        )

    def test_exact_matrix_and_paired_contrast(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for arm in transfer.ARMS:
                for seed in transfer.SEEDS:
                    for bot_type in transfer.BOT_TYPES:
                        for bot_team in transfer.BOT_TEAMS:
                            self.write_cell(
                                root, arm, seed, bot_type, bot_team)
            report = transfer.analyze(root)

        self.assertEqual(report["cell_count"], 16)
        self.assertEqual(report["equal_weighted_games"], 16_000)
        paired = report["paired_r2_minus_r0"]
        self.assertAlmostEqual(
            paired["summary"]["champion_score"]["mean"], 0.2)
        self.assertEqual(paired["positive_cells"]["champion_score"], 8)
        self.assertAlmostEqual(
            paired["summary"]["champion_tds"]["mean"], 0.0)

    def test_missing_cell_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(transfer.TransferError, "missing transfer"):
                transfer.analyze(tmp)


if __name__ == "__main__":
    unittest.main()
