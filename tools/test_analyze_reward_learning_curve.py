#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import analyze_reward_learning_curve as curve


def panel(step, n, **updates):
    value = {
        "_puffer_agent_steps": step,
        "_puffer_backend_native": 1,
        "_puffer_env_cumulative": 0,
        "_puffer_epoch": step // 10,
        "_puffer_final_reprint": 0,
        "_puffer_phase_eval": 0,
        "_puffer_schema": 2,
        "n": n,
        "hist_n_bank_0": 1.0,
        "hist_score_bank_0": 0.5,
    }
    value.update({metric: 0.0 for metric in curve.MEAN_METRICS})
    value.update({metric: 0.0 for metric in curve.INTEGRITY_METRICS})
    value.update(updates)
    return value


def write_log(path, panels):
    text = "startup noise\n"
    for value in panels:
        text += "PufferLib 4.0\nPUFFER_ENV_JSON "
        text += json.dumps(value, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return text


class RewardLearningCurveTests(unittest.TestCase):
    def test_historical_score_restores_panel_episode_weights(self):
        # The second panel represents three times as many completed episodes.
        # Correct: games=(1*10 + .5*30)=25; score=(.5*10 + .4*30)=17.
        # Weighting panel ratios only by hist_n would incorrectly report 0.6.
        panels = [
            panel(100, 10, tds=1.0, hist_n_bank_0=1.0, hist_score_bank_0=0.5),
            panel(
                200,
                30,
                tds=3.0,
                hist_n_bank_0=0.5,
                hist_score_bank_0=0.4,
                reward_clip_episodes=0.1,
            ),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.log"
            raw = write_log(path, panels)
            report = curve.analyze_log(
                path,
                max_step=200,
                window_steps=100,
                expected_sha256=hashlib.sha256(raw.encode()).hexdigest(),
            )

        overall = report["overall"]
        self.assertEqual(overall["panel_count"], 2)
        self.assertEqual(overall["episode_count"], 40)
        self.assertAlmostEqual(overall["episode_weighted_means"]["tds"], 2.5)
        pool = overall["static_training_pool"]
        self.assertAlmostEqual(pool["games"], 25.0)
        self.assertAlmostEqual(pool["score_sum"], 17.0)
        self.assertAlmostEqual(pool["score"], 0.68)
        self.assertAlmostEqual(overall["integrity_totals"]["reward_clip_episodes"], 3.0)
        self.assertEqual(report["endpoints"]["first"]["data"]["episode_count"], 10)
        self.assertEqual(report["endpoints"]["last"]["data"]["episode_count"], 30)

    def test_skips_startup_final_reprint_and_eval_panels(self):
        startup = panel(0, 0)
        train = panel(100, 4, tds=1.25)
        final = panel(100, 4, tds=99.0, _puffer_final_reprint=1)
        evaluation = panel(
            110,
            20,
            tds=77.0,
            _puffer_phase_eval=1,
            _puffer_env_cumulative=1,
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.log"
            write_log(path, [startup, train, final, evaluation])
            report = curve.analyze_log(path, window_steps=100)

        self.assertEqual(report["source"]["machine_panels_seen"], 4)
        self.assertEqual(report["source"]["eligible_train_panels_seen"], 1)
        self.assertEqual(report["overall"]["episode_count"], 4)
        self.assertEqual(report["overall"]["episode_weighted_means"]["tds"], 1.25)

    def test_requires_exact_requested_max_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.log"
            write_log(path, [panel(100, 2), panel(200, 2)])
            with self.assertRaisesRegex(ValueError, "exact max step 150 is absent"):
                curve.analyze_log(path, max_step=150, window_steps=100)

    def test_explicit_nominal_endpoint_excludes_checkpoint_overshoot(self):
        panels = [panel(100, 2), panel(200, 3), panel(205, 5)]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "train.log"
            write_log(path, panels)
            report = curve.analyze_log(
                path,
                max_step=205,
                endpoint_step=200,
                window_steps=100,
            )

        last = report["endpoints"]["last"]
        self.assertEqual(last["start_step_exclusive"], 100)
        self.assertEqual(last["end_step_inclusive"], 200)
        self.assertEqual(last["data"]["episode_count"], 3)

    def test_rejects_schema1_and_nonmonotonic_train_panels(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "schema1.log"
            write_log(path, [panel(100, 2, _puffer_schema=1)])
            with self.assertRaisesRegex(ValueError, "requires schema 2"):
                curve.analyze_log(path, window_steps=100)

            path = Path(tmp) / "backwards.log"
            write_log(path, [panel(200, 2), panel(100, 2)])
            with self.assertRaisesRegex(ValueError, "not strictly increasing"):
                curve.analyze_log(path, window_steps=100)

    def test_rejects_mismatched_hash_and_bank_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "hash.log"
            write_log(path, [panel(100, 2)])
            with self.assertRaisesRegex(ValueError, "source SHA-256 mismatch"):
                curve.analyze_log(path, window_steps=100, expected_sha256="0" * 64)

            broken = panel(100, 2)
            del broken["hist_score_bank_0"]
            path = Path(tmp) / "bank.log"
            write_log(path, [broken])
            with self.assertRaisesRegex(ValueError, "absent or mismatched"):
                curve.analyze_log(path, window_steps=100)

    def test_rejects_marker_and_bank_set_schema_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "marker.log"
            write_log(path, [panel(100, 2, _puffer_final_reprint=-1)])
            with self.assertRaisesRegex(ValueError, "exact non-negative integer"):
                curve.analyze_log(path, window_steps=100)

            second = panel(200, 2)
            second["hist_n_bank_1"] = 0.0
            second["hist_score_bank_1"] = 0.0
            path = Path(tmp) / "banks.log"
            write_log(path, [panel(100, 2), second])
            with self.assertRaisesRegex(ValueError, "bank ID set changed"):
                curve.analyze_log(path, window_steps=100)


if __name__ == "__main__":
    unittest.main()
