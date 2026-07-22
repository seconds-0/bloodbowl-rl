#!/usr/bin/env python3

import tempfile
import unittest
from pathlib import Path

import game_stats
import contact_bot_stats


class GameStatsTests(unittest.TestCase):
    def test_completed_game_requirement_is_inclusive_at_the_exact_target(self):
        self.assertFalse(game_stats.completed_game_requirement_met(9_999.0, 10_000))
        self.assertTrue(game_stats.completed_game_requirement_met(10_000.0, 10_000))
        self.assertTrue(game_stats.completed_game_requirement_met(10_001.0, 10_000))
        self.assertFalse(game_stats.completed_game_requirement_met(float("nan"), 10_000))

    def test_scripted_bot_perspective_supports_either_team(self):
        values = {
            "slot_0_score": 0.7,
            "slot_1_score": 0.3,
            "tds_t0": 1.4,
            "tds_t1": 0.6,
            "blocks_thrown_t0": 9.0,
            "blocks_thrown_t1": 5.0,
        }
        away_bot = contact_bot_stats.bot_perspective(values, bot_team=1)
        home_bot = contact_bot_stats.bot_perspective(values, bot_team=0)
        self.assertEqual(away_bot["champion_score"], 0.7)
        self.assertEqual(away_bot["bot_tds"], 0.6)
        self.assertEqual(home_bot["champion_score"], 0.3)
        self.assertEqual(home_bot["bot_tds"], 1.4)

    def test_weighted_dashboard_aggregates_episode_windows(self):
        log = """
PufferLib 4.0
│  n  10    tds  1.0  │
│  possession_rate  0.4    reward_clip_episodes  0.0  │
PufferLib 4.0
│  n  30    tds  3.0  │
│  possession_rate  0.6    reward_clip_episodes  0.1  │
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            latest = game_stats.latest_dashboard(path)
            weighted = game_stats.weighted_dashboard(path)

        self.assertEqual(latest["n"], 30.0)
        self.assertEqual(latest["tds"], 3.0)
        self.assertEqual(weighted["n"], 40.0)
        self.assertAlmostEqual(weighted["tds"], 2.5)
        self.assertAlmostEqual(weighted["possession_rate"], 0.55)
        self.assertAlmostEqual(weighted["reward_clip_episodes"], 0.075)

    def test_weighted_dashboard_skips_startup_windows_without_episodes(self):
        log = """
PufferLib 4.0
│  tds  99.0  │
PufferLib 4.0
│  n  2    tds  1.25  │
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            weighted = game_stats.weighted_dashboard(path)

        self.assertEqual(weighted["n"], 2.0)
        self.assertEqual(weighted["tds"], 1.25)

    def test_machine_json_preserves_long_unabbreviated_metric_names(self):
        log = """
PufferLib 4.0
│  n  4    reward_clip_frac_nonz…  0.5  │
PUFFER_ENV_JSON {"n": 4, "reward_clip_frac_nonzero": 0.125, "def_carrier_path_zerotz": 0.75}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            weighted = game_stats.weighted_dashboard(path)

        self.assertEqual(weighted["n"], 4.0)
        self.assertEqual(weighted["reward_clip_frac_nonzero"], 0.125)
        self.assertEqual(weighted["def_carrier_path_zerotz"], 0.75)

    def test_machine_json_ignores_rich_tail_and_explicit_final_reprint(self):
        # Puffer unconditionally prints the final dashboard a second time.
        # Text following the machine payload can differ (and previously
        # polluted the parsed dict). The explicit marker is authoritative;
        # value equality is not, because two real windows can match exactly.
        payload = '{"_puffer_final_reprint": 0, "n": 7, "tds": 1.5}'
        reprint = '{"_puffer_final_reprint": 1, "n": 7, "tds": 1.5}'
        log = f"""
PufferLib 4.0
│  n  7    tds  1.5  │
PUFFER_ENV_JSON {payload}
PufferLib 4.0
│  n  7    tds  1.5  │
PUFFER_ENV_JSON {reprint}
finished with 3 artifacts
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            weighted = game_stats.weighted_dashboard(path)

        self.assertEqual(weighted["n"], 7.0)
        self.assertEqual(weighted["tds"], 1.5)
        self.assertNotIn("with", weighted)

    def test_identical_unmarked_interval_windows_both_count(self):
        payload = '{"_puffer_final_reprint": 0, "n": 7, "tds": 1.5}'
        log = f"""
PufferLib 4.0
PUFFER_ENV_JSON {payload}
PufferLib 4.0
PUFFER_ENV_JSON {payload}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            weighted = game_stats.weighted_dashboard(path)

        self.assertEqual(weighted["n"], 14.0)
        self.assertEqual(weighted["tds"], 1.5)

    def test_native_cumulative_eval_keeps_only_final_eval_snapshot(self):
        # Native static_vec_eval_log is cumulative, unlike its resetting
        # training log. Combine independent training intervals with only the
        # final cumulative eval snapshot. The unconditional final reprint is
        # duplicated here as it is in real Puffer logs.
        log = """
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 0, "_puffer_phase_eval": 0, "n": 10, "tds": 1.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 0, "_puffer_phase_eval": 0, "n": 20, "tds": 2.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 1, "_puffer_phase_eval": 1, "_puffer_final_reprint": 0, "n": 5, "tds": 4.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 1, "_puffer_phase_eval": 1, "_puffer_final_reprint": 0, "n": 15, "tds": 6.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 1, "_puffer_phase_eval": 1, "_puffer_final_reprint": 1, "n": 15, "tds": 6.0}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            weighted = game_stats.weighted_dashboard(path)

            trained = game_stats.weighted_dashboard(path, phase="train")
            combined = game_stats.weighted_dashboard(path, phase="all")

        self.assertEqual(weighted["n"], 15.0)
        self.assertEqual(weighted["tds"], 6.0)
        self.assertEqual(trained["n"], 30.0)
        self.assertAlmostEqual(trained["tds"], (10 + 40) / 30)
        self.assertEqual(combined["n"], 45.0)
        self.assertAlmostEqual(combined["tds"], (10 + 40 + 90) / 45)

    def test_torch_eval_windows_remain_independent(self):
        log = """
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 0, "_puffer_phase_eval": 0, "n": 10, "tds": 1.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 0, "_puffer_phase_eval": 1, "n": 5, "tds": 3.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_env_cumulative": 0, "_puffer_phase_eval": 1, "n": 7, "tds": 5.0}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            weighted = game_stats.weighted_dashboard(path)

        self.assertEqual(weighted["n"], 12.0)
        self.assertAlmostEqual(weighted["tds"], (15 + 35) / 12)

    def test_schema1_repairs_the_mislabeled_final_training_panel(self):
        log = """
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 1, "_puffer_phase_eval": 0, "_puffer_env_cumulative": 0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 1, "_puffer_phase_eval": 0, "_puffer_env_cumulative": 0, "n": 10, "tds": 1.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 1, "_puffer_phase_eval": 1, "_puffer_env_cumulative": 1, "n": 4, "tds": 2.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 1, "_puffer_phase_eval": 1, "_puffer_env_cumulative": 1, "n": 5, "tds": 3.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 1, "_puffer_phase_eval": 1, "_puffer_env_cumulative": 1, "n": 15, "tds": 5.0}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 1, "_puffer_phase_eval": 1, "_puffer_env_cumulative": 1, "_puffer_final_reprint": 1, "n": 15, "tds": 5.0}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "eval.log"
            path.write_text(log, encoding="utf-8")
            trained = game_stats.weighted_dashboard(path, phase="train")
            evaluated = game_stats.weighted_dashboard(path, phase="eval")

        self.assertEqual(trained["n"], 14.0)
        self.assertAlmostEqual(trained["tds"], 18.0 / 14.0)
        self.assertEqual(evaluated["n"], 15.0)
        self.assertEqual(evaluated["tds"], 5.0)

    def test_schema2_training_only_run_has_no_eval_sample(self):
        log = """
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 2, "_puffer_phase_eval": 0, "_puffer_env_cumulative": 0, "_puffer_epoch": 0, "n": 4, "tds": 1.25}
PufferLib 4.0
PUFFER_ENV_JSON {"_puffer_schema": 2, "_puffer_phase_eval": 0, "_puffer_env_cumulative": 0, "_puffer_epoch": 0, "_puffer_final_reprint": 1, "n": 4, "tds": 1.25}
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train-only.log"
            path.write_text(log, encoding="utf-8")
            trained = game_stats.weighted_dashboard(path, phase="train")
            evaluated = game_stats.weighted_dashboard(path, phase="eval")

        self.assertEqual(trained["n"], 4.0)
        self.assertEqual(evaluated, {})


if __name__ == "__main__":
    unittest.main()
