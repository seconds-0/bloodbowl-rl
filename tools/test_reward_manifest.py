#!/usr/bin/env python3

import json
import re
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

        # D234: the old `abs(td) + abs(win) <= 1.0` rule existed only to fit
        # the trainer's +-1 clamp, and it was unsound anyway -- it ignored the
        # exact-PBRS terminal payback that lands on the same emission. These
        # stacks are now LEGAL: they are inside the widened guard, and it is
        # the derived envelope that has to fit, not the objective pair.
        manifest["reward"]["reward_ball_loss"] = 0.0
        manifest["reward"]["reward_td"] = 0.6
        reward_manifest.validate_manifest(manifest)

        manifest["reward"].update(reward_td=1.0, reward_win=-1.0)
        reward_manifest.validate_manifest(manifest)

        manifest["reward"].update(reward_td=1.0, reward_win=0.0,
                                  reward_draw=1.0)
        reward_manifest.validate_manifest(manifest)

    def test_derived_envelope_must_fit_the_trainer_clamp(self):
        # The replacement rule (D234): mirror bbe_reward_clip_threshold and
        # require the result to stay inside the trainer's NaN/pathology guard.
        manifest = {"schema_version": 2, "name": "envelope",
                    "reward": self.complete_reward()}
        manifest["reward"].update(reward_dist_pbrs_gamma=0.995)

        # Exactly at the guard: td 1 + win 1 + 25*(0.12 + 0.12) = 8.0.
        manifest["reward"].update(reward_td=1.0, reward_win=1.0,
                                  reward_dist_ball=0.12,
                                  reward_dist_endzone=0.12)
        # The per-channel scaffold cap bites first here, and deliberately so:
        # 25 * 0.12 = 3.0 would make one distance channel worth three matches.
        with self.assertRaisesRegex(ValueError, "full-pitch fetch potential"):
            reward_manifest.validate_manifest(manifest)

        # Keep both distance channels inside the per-channel cap and push the
        # objective pair instead: 1.0 + 1.0 + 25*(0.04 + 0.04) = 4.0, legal.
        manifest["reward"].update(reward_dist_ball=0.04,
                                  reward_dist_endzone=0.04)
        reward_manifest.validate_manifest(manifest)

        # Legacy raw delta never co-fires with the objective stack, so the
        # envelope is the max, not the sum.
        legacy = {"schema_version": 2, "name": "legacy-envelope",
                  "reward": self.complete_reward()}
        legacy["reward"].update(reward_dist_pbrs_gamma=0.0,
                                reward_td=1.0, reward_win=1.0,
                                reward_dist_ball=0.04,
                                reward_dist_endzone=0.04)
        reward_manifest.validate_manifest(legacy)

    def test_exact_pbrs_distance_coefficients_must_be_non_negative(self):
        manifest = {"schema_version": 2, "name": "negative-phi",
                    "reward": self.complete_reward()}
        # Legacy form is Phi = -k*d: historical semantics, unchanged.
        manifest["reward"].update(reward_dist_pbrs_gamma=0.0,
                                  reward_dist_ball=-0.02)
        reward_manifest.validate_manifest(manifest)

        # Exact form is Phi = k*(D_max - d), which a negative k makes <= 0 and
        # inverts every sign conclusion the channel rests on.
        manifest["reward"].update(reward_dist_pbrs_gamma=0.995)
        with self.assertRaisesRegex(
                ValueError, "reward_dist_ball.*must be >= 0"):
            reward_manifest.validate_manifest(manifest)

        manifest["reward"].update(reward_dist_ball=0.02,
                                  reward_dist_endzone=-0.04)
        with self.assertRaisesRegex(
                ValueError, "reward_dist_endzone.*must be >= 0"):
            reward_manifest.validate_manifest(manifest)

    def test_trainer_clamp_constant_agrees_with_the_env_and_the_patch(self):
        """Three copies of one number; drift makes the envelope check a lie."""
        root = Path(__file__).resolve().parents[1]
        header = (root / "puffer/bloodbowl/bloodbowl.h").read_text(
            encoding="utf-8")
        match = re.search(
            r"#define BBE_TRAINER_REWARD_CLAMP ([0-9.]+)f", header)
        self.assertIsNotNone(match)
        self.assertEqual(
            float(match.group(1)), reward_manifest.TRAINER_REWARD_CLAMP)

        patch = (root / "training/puffer_reward_clamp_range.patch").read_text(
            encoding="utf-8")
        clamp = reward_manifest.TRAINER_REWARD_CLAMP
        torch_line = f"+        rew = self.rewards.T.contiguous().clamp(" \
                     f"-{int(clamp)}, {int(clamp)})"
        self.assertIn(torch_line, patch)
        cuda_line = (f"+        rollouts.rewards.data, -{clamp:.1f}f, "
                     f"{clamp:.1f}f, numel(rollouts.rewards.shape));")
        self.assertIn(cuda_line, patch)

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
