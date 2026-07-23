#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path

import reward_manifest


class RewardManifestTests(unittest.TestCase):
    def complete_reward(self):
        reward = {key: 0.0 for key in reward_manifest.REWARD_FLOAT_KEYS}
        reward.update(reward_td=0.4, reward_win=0.6,
                      reward_injury_value_scaled=0)
        return reward

    def test_schema_boundary_keeps_historical_digests_stable(self):
        # Schema 1 must NOT carry a schema-2 key. Historical manifest digests are
        # quoted as provenance by completed experiments and in DECISIONS.md, so
        # adding a field to those files would silently invalidate every
        # reference. Schema 1 therefore *means* the legacy behaviour rather than
        # inheriting it as a default.
        legacy = {"schema_version": 1, "name": "legacy",
                  "reward": self.complete_reward()}
        legacy["reward"].pop("reward_dist_pbrs_gamma")
        validated = reward_manifest.validate_manifest(legacy)
        self.assertNotIn("reward_dist_pbrs_gamma", validated["reward"])
        self.assertNotIn("--env.reward-dist-pbrs-gamma",
                         reward_manifest.cli_args(validated))

        # A schema-1 manifest that DOES carry it is rejected, not tolerated.
        smuggled = {"schema_version": 1, "name": "smuggled",
                    "reward": self.complete_reward()}
        with self.assertRaises(ValueError) as caught:
            reward_manifest.validate_manifest(smuggled)
        self.assertIn("reward_dist_pbrs_gamma", str(caught.exception))

        # A schema-2 manifest that OMITS it is rejected too: explicit zero and
        # missing must stay distinguishable within a version.
        incomplete = {"schema_version": 2, "name": "incomplete",
                      "reward": self.complete_reward()}
        incomplete["reward"].pop("reward_dist_pbrs_gamma")
        with self.assertRaises(ValueError) as caught:
            reward_manifest.validate_manifest(incomplete)
        self.assertIn("reward_dist_pbrs_gamma", str(caught.exception))

        # And an unknown version is refused rather than silently accepted.
        for bad in (0, 3, "2", None):
            with self.assertRaises(ValueError):
                reward_manifest.validate_manifest(
                    {"schema_version": bad, "name": "v",
                     "reward": self.complete_reward()})

    def test_complete_manifest_emits_every_reward_override(self):
        manifest = {
            "schema_version": 2,
            "name": "test",
            "reward": self.complete_reward(),
        }
        validated = reward_manifest.validate_manifest(manifest)
        args = reward_manifest.cli_args(validated)

        self.assertEqual(len(args), 2 * len(reward_manifest.REQUIRED_KEYS))
        self.assertIn("--env.reward-td", args)
        self.assertEqual(args[args.index("--env.reward-td") + 1], "0.4")
        self.assertIn("--env.reward-statmatch-scale", args)

    def test_missing_key_and_unsafe_terminal_stack_are_rejected(self):
        manifest = {"schema_version": 2, "name": "bad",
                    "reward": self.complete_reward()}
        del manifest["reward"]["reward_ball_loss"]
        with self.assertRaisesRegex(ValueError, "missing reward keys"):
            reward_manifest.validate_manifest(manifest)

        manifest["reward"]["reward_ball_loss"] = 0.0
        manifest["reward"]["reward_td"] = 0.6
        with self.assertRaisesRegex(ValueError, "TD/win objective stack"):
            reward_manifest.validate_manifest(manifest)

        manifest["reward"].update(reward_td=1.0, reward_win=-1.0)
        with self.assertRaisesRegex(ValueError, "TD/win objective stack"):
            reward_manifest.validate_manifest(manifest)

        manifest["reward"].update(reward_td=1.0, reward_win=0.0,
                                  reward_draw=1.0)
        with self.assertRaisesRegex(ValueError, "TD/draw objective stack"):
            reward_manifest.validate_manifest(manifest)

    def test_incompatible_reward_families_are_rejected(self):
        manifest = {"schema_version": 2, "name": "bad",
                    "reward": self.complete_reward()}
        manifest["reward"].update(reward_carrier_threat=0.1,
                                  reward_carrier_exposure=0.1)
        with self.assertRaisesRegex(ValueError, "carrier_threat.*carrier_exposure"):
            reward_manifest.validate_manifest(manifest)

        manifest["reward"].update(reward_carrier_exposure=0.0,
                                  reward_k_assist=0.1)
        with self.assertRaisesRegex(ValueError, "carrier_threat.*k_assist"):
            reward_manifest.validate_manifest(manifest)

        manifest["reward"].update(reward_carrier_threat=0.0,
                                  reward_k_assist=0.0,
                                  reward_statmatch_scale=0.1)
        with self.assertRaisesRegex(ValueError, "statmatch.*quarantined"):
            reward_manifest.validate_manifest(manifest)

    def test_distance_potential_full_pitch_jump_must_fit_the_clamp(self):
        manifest = {"schema_version": 2, "name": "bad-carry",
                    "reward": self.complete_reward()}
        manifest["reward"]["reward_dist_endzone"] = 0.05
        with self.assertRaisesRegex(ValueError, "full-pitch carry potential"):
            reward_manifest.validate_manifest(manifest)

        manifest = {"schema_version": 2, "name": "bad-fetch",
                    "reward": self.complete_reward()}
        manifest["reward"]["reward_dist_ball"] = 0.05
        with self.assertRaisesRegex(ValueError, "full-pitch fetch potential"):
            reward_manifest.validate_manifest(manifest)

    def test_load_hash_is_canonical_not_whitespace_sensitive(self):
        manifest = {"schema_version": 2, "name": "test",
                    "reward": self.complete_reward()}
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "first.json"
            second = Path(tmp) / "second.json"
            first.write_text(json.dumps(manifest), encoding="utf-8")
            second.write_text(json.dumps(manifest, indent=4, sort_keys=True),
                              encoding="utf-8")
            _, hash1 = reward_manifest.load_manifest(first)
            _, hash2 = reward_manifest.load_manifest(second)
        self.assertEqual(hash1, hash2)


if __name__ == "__main__":
    unittest.main()
