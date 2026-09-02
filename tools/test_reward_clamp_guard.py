"""Tests for the launch-time PBRS terminal-clamp guard.

The native suite (puffer/bloodbowl/test_reward_send_off.c) pins the ENV-side
arithmetic with hardcoded coefficients. These tests pin the two things it
cannot see: that the shipped manifests actually carry clamp-safe numbers, and
that run_reward_ablation.sh actually invokes the guard before launching.
"""

import re
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reward_clamp_guard as guard
from reward_manifest import load_manifest

ROOT = Path(__file__).resolve().parent.parent
REWARDS = ROOT / "puffer" / "config" / "rewards"
LAUNCHER = ROOT / "tools" / "run_reward_ablation.sh"


def run_guard(manifest: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "tools" / "reward_clamp_guard.py"),
         str(manifest), "--root", str(ROOT)],
        capture_output=True, text=True)


class PitchLenTest(unittest.TestCase):
    def test_reads_bb_pitch_len_from_the_engine_header(self):
        # Read, not hardcoded: a pitch resize must move the bound with it.
        self.assertEqual(guard.read_pitch_len(ROOT), 26)

    def test_header_is_the_real_definition_site(self):
        header = (ROOT / guard.PITCH_LEN_HEADER).read_text()
        self.assertIn("#define BB_PITCH_LEN 26", header)


class WorstCaseTest(unittest.TestCase):
    def test_matches_the_documented_arithmetic(self):
        reward = {"reward_dist_ball": 0.02, "reward_dist_endzone": 0.04,
                  "reward_td": 0.4}
        # (0.02 + 0.04) * 25 - 0.4 = 1.1
        self.assertAlmostEqual(guard.worst_case_terminal(reward, 26), 1.1)

    def test_clampsafe_coefficients_come_in_under_the_clamp(self):
        reward = {"reward_dist_ball": 0.015, "reward_dist_endzone": 0.025,
                  "reward_td": 0.4}
        # (0.015 + 0.025) * 25 - 0.4 = 0.6
        self.assertAlmostEqual(guard.worst_case_terminal(reward, 26), 0.6)


class GateTest(unittest.TestCase):
    def _manifest(self, **reward):
        base = {"reward_dist_ball": 0.02, "reward_dist_endzone": 0.04,
                "reward_td": 0.4, "reward_dist_pbrs_gamma": 0.995}
        base.update(reward)
        return {"name": "probe", "reward": base}

    def test_exact_pbrs_manifest_over_the_clamp_is_refused(self):
        self.assertIsNotNone(guard.check(self._manifest(), 26))

    def test_legacy_gamma_zero_path_is_exempt(self):
        # The raw-delta form emits no one-shot terminal payback and must stay
        # bit-identical, so the same coefficients must NOT be refused there.
        self.assertIsNone(
            guard.check(self._manifest(reward_dist_pbrs_gamma=0.0), 26))

    def test_missing_gamma_schema1_manifest_is_exempt(self):
        manifest = self._manifest()
        del manifest["reward"]["reward_dist_pbrs_gamma"]
        self.assertIsNone(guard.check(manifest, 26))

    def test_refusal_message_names_the_offending_numbers(self):
        message = guard.check(self._manifest(), 26)
        for token in ("0.02", "0.04", "25", "0.4", "1.100000"):
            self.assertIn(token, message)


class ShippedManifestTest(unittest.TestCase):
    def test_s0_both_is_refused(self):
        # The manifest that produced the live clipping. Its digest is quoted as
        # provenance by completed runs, so it stays on disk unchanged and is
        # refused at launch instead of edited.
        result = run_guard(REWARDS / "s0_both.json")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("can breach the PPO reward clamp", result.stderr)

    def test_s0_both_clampsafe_passes(self):
        result = run_guard(REWARDS / "s0_both_clampsafe.json")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stderr, "")

    def test_clampsafe_differs_from_s0_both_only_in_the_two_coefficients(self):
        old, _ = load_manifest(REWARDS / "s0_both.json")
        new, _ = load_manifest(REWARDS / "s0_both_clampsafe.json")
        self.assertEqual(set(old["reward"]), set(new["reward"]))
        differing = {k for k in old["reward"]
                     if old["reward"][k] != new["reward"][k]}
        self.assertEqual(differing, {"reward_dist_ball", "reward_dist_endzone"})
        # Still exact PBRS at the same gamma -- the guarantee is preserved, not
        # traded away for headroom.
        self.assertEqual(new["reward"]["reward_dist_pbrs_gamma"], 0.995)
        self.assertEqual(new["schema_version"], 2)

    def test_every_exact_pbrs_manifest_is_screened(self):
        # Documents the blast radius: every gamma>0 manifest still carrying
        # 0.02/0.04 is refused, so the whole exact-PBRS family needs reissuing,
        # not just s0_both. Schema-1 legacy manifests stay exempt.
        verdicts = {}
        for path in sorted(REWARDS.glob("*.json")):
            manifest, _ = load_manifest(path)
            gamma = manifest["reward"].get("reward_dist_pbrs_gamma", 0.0)
            if gamma > 0:
                verdicts[path.stem] = guard.check(manifest, 26) is None
        self.assertEqual(
            verdicts,
            {"r4_pbrs_distance": False, "s0_both": False,
             "s0_both_clampsafe": True, "s1_possession_only": False,
             "s2_gain_only": False, "s3_neither": False})


class LauncherWiringTest(unittest.TestCase):
    """The guard is worthless if the launcher does not call it."""

    def setUp(self):
        self.script = LAUNCHER.read_text()

    def test_launcher_invokes_the_guard(self):
        self.assertIn("tools/reward_clamp_guard.py", self.script)

    def test_guard_runs_inside_the_exact_pbrs_gate(self):
        # Must sit inside `if [ "${REWARD_PBRS_GAMMA...}" != "0" ]`, so the
        # legacy gamma==0 path is untouched.
        gate = self.script.index('if [ "${REWARD_PBRS_GAMMA:-0}" != "0" ]')
        call = self.script.index("tools/reward_clamp_guard.py")
        self.assertGreater(call, gate)
        # ...and the gate's own `fi` must come after the call.
        closing = self.script.index("\nfi\n", call)
        self.assertGreater(closing, call)

    def test_guard_runs_before_the_trainer_launches(self):
        call = self.script.index("tools/reward_clamp_guard.py")
        launch = self.script.index("CMD=(env PUFFER_CUDA_RUNTIME_MANIFEST")
        self.assertLess(call, launch)

    def test_guard_failure_aborts_the_launch(self):
        window = self.script[self.script.index("tools/reward_clamp_guard.py"):]
        window = window[:window.index("\nfi\n")]
        self.assertIn("exit 1", window)

    def test_guard_is_passed_the_manifest_being_launched(self):
        window = self.script[self.script.index("tools/reward_clamp_guard.py"):]
        window = window[:window.index("\nfi\n")]
        self.assertIn('"$REWARD_MANIFEST"', window)


if __name__ == "__main__":
    unittest.main()
