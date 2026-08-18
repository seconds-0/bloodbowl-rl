#!/usr/bin/env python3
"""The backplay ladder rung must run as a screen so it publishes lineage.

Two July 2026 rung-6 runs went through the bare per-arm launcher and produced
5B-step checkpoints that could not warm-start rung 9: eligible lineage sidecars
are written only by run_reward_screen.sh's materialize_result after the
acceptance gate, and the bare launcher also attached no live integrity guard.
These tests pin the contract of the SCREEN_PROFILE=ladder-rung route and of the
rung launcher that drives it. They exercise the real scripts up to the point of
artifact I/O and assert on specific messages, never on exit status alone.
"""

from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "tools/run_reward_screen.sh"
RUNG = ROOT / "tools/launch_ladder_rung.sh"


def run(script, env):
    merged = os.environ.copy()
    for key in ("LADDER_ENDZONE_MAXDIST", "LADDER_RESET_PCT", "LADDER_SEED",
                "WARM", "POOL", "CANDIDATE_ARM"):
        merged.pop(key, None)
    merged.update(env)
    return subprocess.run(
        ["bash", str(script)], cwd=ROOT, env=merged, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=120,
    )


BASE = {
    "WARM": "missing.bin",
    "POOL": "missing-pool",
    "STEPS": "5000000000",
    "SCREEN_PROFILE": "ladder-rung",
    "EXPECTED_POOL_HASH": "0" * 64,
}


class LadderRungProfileTests(unittest.TestCase):
    def test_profile_is_listed_and_single_arm_on_the_corrected_reward(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("ladder-rung", source)
        self.assertRegex(
            source,
            r"ladder-rung\)\n(?:.*\n)*?\s+arms=\(s_both\)\n\s+seeds=\(\"\$LADDER_SEED\"\)",
        )

    def test_rung_requires_explicit_maxdist(self):
        result = run(SCREEN, {**BASE, "LADDER_RESET_PCT": "0.5",
                              "LADDER_SEED": "42"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires LADDER_ENDZONE_MAXDIST", result.stderr)
        self.assertNotIn("missing warm checkpoint", result.stderr)

    def test_rung_requires_explicit_reset_pct(self):
        result = run(SCREEN, {**BASE, "LADDER_ENDZONE_MAXDIST": "9",
                              "LADDER_SEED": "42"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires LADDER_RESET_PCT", result.stderr)

    def test_rung_requires_explicit_seed(self):
        result = run(SCREEN, {**BASE, "LADDER_ENDZONE_MAXDIST": "9",
                              "LADDER_RESET_PCT": "0.5"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("requires LADDER_SEED", result.stderr)

    def test_rung_rejects_bad_knob_values(self):
        for knobs, message in (
            ({"LADDER_ENDZONE_MAXDIST": "-3", "LADDER_RESET_PCT": "0.5",
              "LADDER_SEED": "42"}, "requires LADDER_ENDZONE_MAXDIST"),
            ({"LADDER_ENDZONE_MAXDIST": "9", "LADDER_RESET_PCT": "1.5",
              "LADDER_SEED": "42"}, "requires LADDER_RESET_PCT"),
            ({"LADDER_ENDZONE_MAXDIST": "9", "LADDER_RESET_PCT": "0.5",
              "LADDER_SEED": "s42"}, "requires LADDER_SEED"),
            # A case glob `0.[0-9]*` would accept this; it must not.
            ({"LADDER_ENDZONE_MAXDIST": "9", "LADDER_RESET_PCT": "0.5garbage",
              "LADDER_SEED": "42"}, "requires LADDER_RESET_PCT"),
            # Non-canonical seeds die 5B steps later in checkpoint_lineage.
            ({"LADDER_ENDZONE_MAXDIST": "9", "LADDER_RESET_PCT": "0.5",
              "LADDER_SEED": "042"}, "requires LADDER_SEED"),
        ):
            result = run(SCREEN, {**BASE, **knobs})
            self.assertNotEqual(result.returncode, 0, knobs)
            self.assertIn(message, result.stderr, knobs)

    def test_uniform_and_kickoff_rungs_are_accepted_by_the_profile_validator(self):
        # maxdist 0 (uniform) and reset_pct 0 (kickoff graduation) are legal
        # rungs; they must get PAST the knob validator and fail later on the
        # deliberately missing warm checkpoint instead.
        for knobs in ({"LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0.5"},
                      {"LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0"}):
            result = run(SCREEN, {**BASE, **knobs, "LADDER_SEED": "42"})
            self.assertNotEqual(result.returncode, 0, knobs)
            self.assertNotIn("ladder-rung requires", result.stderr, knobs)
            self.assertIn("missing warm checkpoint", result.stderr, knobs)

    def test_rung_is_a_lineage_v6_profile_and_rejects_candidate_inputs(self):
        result = run(SCREEN, {**BASE, "LADDER_ENDZONE_MAXDIST": "9",
                              "LADDER_RESET_PCT": "0.5", "LADDER_SEED": "42",
                              "CANDIDATE_ARM": "gain_only"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate transfer inputs are only valid", result.stderr)
        result = run(SCREEN, {**BASE, "LADDER_ENDZONE_MAXDIST": "9",
                              "LADDER_RESET_PCT": "0.5", "LADDER_SEED": "42"})
        self.assertNotEqual(result.returncode, 0)
        # lineage-v6 branch: warm/pool are REQUIRED, not forbidden.
        self.assertIn("missing warm checkpoint", result.stderr)

    def test_ladder_knobs_are_refused_on_every_other_profile(self):
        result = run(SCREEN, {
            "WARM": "missing.bin", "POOL": "missing-pool",
            "STEPS": "12000000000", "SCREEN_PROFILE": "control-final",
            "LADDER_ENDZONE_MAXDIST": "9",
        })
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only valid with SCREEN_PROFILE=ladder-rung", result.stderr)

    def test_screen_passes_ladder_knobs_only_to_rung_arms_and_records_them(self):
        source = SCREEN.read_text(encoding="utf-8")
        # Per-arm launcher receives the knobs from the rung profile only.
        self.assertIn('if [ "$SCREEN_PROFILE" = "ladder-rung" ]; then\n'
                      '      LADDER_ENV=(LADDER_ENDZONE_MAXDIST=', source)
        self.assertIn('env ${LADDER_ENV[@]+"${LADDER_ENV[@]}"}', source)
        # And the SCREEN_MANIFEST contract names the rung.
        self.assertIn('contract["ladder"] = {', source)
        self.assertIn('"endzone_maxdist": int(os.environ["LADDER_ENDZONE_MAXDIST"])',
                      source)

    def test_screen_gates_curriculum_activity_and_manifest_reuse(self):
        source = SCREEN.read_text(encoding="utf-8")
        # A rung whose bank never loaded is a kickoff run with clean counters;
        # the acceptance gate must refuse it rather than publish it as lineage.
        self.assertIn('"kind": "curriculum_inactive"', source)
        self.assertIn('observed_demo = phase_metrics["train"].get("demo_episodes")',
                      source)
        # A relaunch into an OUT_DIR holding a different plan must fail closed.
        self.assertIn("SCREEN_MANIFEST.json already exists with a different contract",
                      source)

    def test_rung_launcher_drives_the_screen_profile_not_the_bare_arm(self):
        source = RUNG.read_text(encoding="utf-8")
        # Reboot-safe: the screen runs in a numbered attempt directory so a dead
        # partial arm cannot wedge the stage; the marker stays at OUT.
        self.assertIn("pick_screen_dir()", source)
        self.assertIn('OUT_DIR="$SCREEN_DIR"', source)
        self.assertIn('"$OUT/LADDER_RUNG_COMPLETE.json"', source)
        self.assertIn("SCREEN_PROFILE=ladder-rung", source)
        self.assertIn('bash "$C/tools/run_reward_screen.sh"', source)
        self.assertNotIn('bash "$C/tools/run_reward_ablation.sh"', source)
        # The completion marker is derived from the screen's accepted result,
        # which is where the lineage sidecar path/digest come from.
        self.assertIn('result["checkpoint_lineage_sha256"]', source)
        self.assertIn('if not result.get("acceptance_pass")', source)

    def test_rung_launcher_refuses_missing_inputs_before_launch(self):
        env = os.environ.copy()
        for key in ("RUNG", "WARM", "POOL", "EXPECTED_POOL_HASH"):
            env.pop(key, None)
        env["C"] = str(ROOT)
        result = subprocess.run(
            ["bash", str(RUNG)], cwd=ROOT, env=env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
            timeout=60,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RUNG is required", result.stdout)


if __name__ == "__main__":
    unittest.main()
