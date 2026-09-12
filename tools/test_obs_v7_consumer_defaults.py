from __future__ import annotations

import inspect
import unittest

from tools import build_pool_from_ladder
from tools import freeze_opponent_composition
from tools import run_checkpoint_milestone_eval
from tools import run_reward_candidate_transfer
from tools import run_reward_learned_transfer
from tools.build_league import DEFAULT_EXPECT_BYTES
from tools.checkpoint_lineage import EXPECTED_CHECKPOINT_BYTES


class ObsV7ConsumerDefaultTests(unittest.TestCase):
    def test_active_native_consumers_share_the_lineage_size(self):
        expected = 16_207_872
        values = {
            EXPECTED_CHECKPOINT_BYTES,
            DEFAULT_EXPECT_BYTES,
            build_pool_from_ladder.DEFAULT_EXPECT_BYTES,
            run_reward_candidate_transfer.EXPECTED_NATIVE_BYTES,
            run_reward_learned_transfer.EXPECTED_NATIVE_BYTES,
            run_checkpoint_milestone_eval.EXPECTED_NATIVE_BYTES,
        }
        self.assertEqual(values, {expected})

    def test_opponent_freezer_default_tracks_the_league_builder(self):
        default = inspect.signature(
            freeze_opponent_composition.freeze
        ).parameters["expect_bytes"].default
        self.assertEqual(default, DEFAULT_EXPECT_BYTES)


if __name__ == "__main__":
    unittest.main()
