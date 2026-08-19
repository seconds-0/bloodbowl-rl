#!/usr/bin/env python3
"""guard_scripted_training (training/pufferl_scripted_training_guard.patch).

The guard is a local pufferl.py patch, so it is tested from the patch text:
extract the function body from the '+' lines and exercise it. It must keep
refusing native learning against a global scripted opponent, and admit it only
when the bot is confined to a frozen bank (env.scripted_bank_tag in
1..vec.num_frozen_banks, selfplay.enabled=1, scripted_opponent_team=1), while
--slowly (torch row filter) and learning_rate <= 1e-9 (frozen eval) stay legal.
"""

from __future__ import annotations

import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PATCH = ROOT / "training/pufferl_scripted_training_guard.patch"


def load_guard():
    added = [line[1:] for line in PATCH.read_text(encoding="utf-8").splitlines()
             if line.startswith("+") and not line.startswith("+++")]
    source = "\n".join(added)
    start = source.index("def guard_scripted_training")
    end = source.index("\n    guard_scripted_training(args)")
    namespace = {}
    exec(compile(source[start:end], str(PATCH), "exec"), namespace)
    return namespace["guard_scripted_training"]


def args(**over):
    base = {
        "env": {"scripted_opponent": 1, "scripted_opponent_team": 1},
        "train": {"learning_rate": 0.00028},
        "selfplay": {"enabled": 1},
        "vec": {"num_frozen_banks": 4},
        "slowly": False,
    }
    for key, value in over.items():
        if isinstance(value, dict):
            base[key].update(value)
        else:
            base[key] = value
    return base


class ScriptedTrainingGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.guard = staticmethod(load_guard())

    def test_no_tag_keeps_the_original_refusal(self):
        for env in ({}, {"scripted_bank_tag": 0}):
            with self.assertRaisesRegex(RuntimeError, "unsafe on the native/CUDA backend"):
                self.guard(args(env=env))

    def test_tag_requires_selfplay_enabled(self):
        with self.assertRaisesRegex(RuntimeError, "requires selfplay.enabled=1"):
            self.guard(args(env={"scripted_bank_tag": 2}, selfplay={"enabled": 0}))

    def test_tag_above_num_frozen_banks_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "1 <= tag <= vec.num_frozen_banks"):
            self.guard(args(env={"scripted_bank_tag": 5}))
        with self.assertRaisesRegex(RuntimeError, "vec.num_frozen_banks \\(0\\)"):
            self.guard(args(env={"scripted_bank_tag": 1}, vec={"num_frozen_banks": 0}))

    def test_bot_on_team_zero_is_refused(self):
        with self.assertRaisesRegex(RuntimeError, "requires scripted_opponent_team=1"):
            self.guard(args(env={"scripted_bank_tag": 2, "scripted_opponent_team": 0}))

    def test_confined_bank_passes(self):
        for tag in (1, 4):
            self.assertIsNone(self.guard(args(env={"scripted_bank_tag": tag})))
        # String-typed config values (argparse) are tolerated like the rest.
        self.assertIsNone(self.guard(args(
            env={"scripted_bank_tag": "3", "scripted_opponent_team": "1"},
            selfplay={"enabled": "1"}, vec={"num_frozen_banks": "4"})))

    def test_slowly_torch_row_filter_still_passes(self):
        self.assertIsNone(self.guard(args(slowly=True)))
        self.assertIsNone(self.guard(args(slowly=True, env={"scripted_bank_tag": 0})))

    def test_frozen_eval_learning_rate_still_passes(self):
        for lr in (0, 1e-9, "0"):
            self.assertIsNone(self.guard(args(train={"learning_rate": lr})))

    def test_unscripted_training_is_untouched(self):
        self.assertIsNone(self.guard(args(env={"scripted_opponent": 0})))


if __name__ == "__main__":
    unittest.main()
