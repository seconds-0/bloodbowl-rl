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
    merged = {k: v for k, v in os.environ.items()
              if not k.startswith(("LADDER_", "SCRIPTED_", "GRAFT_"))
              and k not in ("WARM", "POOL", "CANDIDATE_ARM", "STEPS",
                            "SCREEN_PROFILE", "EXPECTED_POOL_HASH", "PREFIX",
                            "OUT_DIR")}
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

    RUNG_OK = {"LADDER_ENDZONE_MAXDIST": "9", "LADDER_RESET_PCT": "0.5",
               "LADDER_SEED": "42"}

    def test_scripted_bank_knobs_are_refused_on_every_other_profile(self):
        for knob in ("SCRIPTED_BANK_TAG", "SCRIPTED_BOT_TYPE"):
            result = run(SCREEN, {
                "WARM": "missing.bin", "POOL": "missing-pool",
                "STEPS": "12000000000", "SCREEN_PROFILE": "control-final",
                knob: "0",
            })
            self.assertNotEqual(result.returncode, 0, knob)
            self.assertIn("SCRIPTED_BANK_TAG and SCRIPTED_BOT_TYPE are only "
                          "valid with SCREEN_PROFILE=ladder-rung", result.stderr, knob)

    def test_rung_validates_scripted_bank_knobs(self):
        for knobs, message in (
            ({"SCRIPTED_BANK_TAG": "5"}, "requires SCRIPTED_BANK_TAG"),
            ({"SCRIPTED_BANK_TAG": "-1"}, "requires SCRIPTED_BANK_TAG"),
            ({"SCRIPTED_BANK_TAG": "01"}, "requires SCRIPTED_BANK_TAG"),
            ({"SCRIPTED_BOT_TYPE": "2"}, "requires SCRIPTED_BOT_TYPE"),
            ({"SCRIPTED_BOT_TYPE": "contact"}, "requires SCRIPTED_BOT_TYPE"),
        ):
            result = run(SCREEN, {**BASE, **self.RUNG_OK, **knobs})
            self.assertNotEqual(result.returncode, 0, knobs)
            self.assertIn(message, result.stderr, knobs)
        # Legal values, and the unset default, get past the validator and fail
        # later on the deliberately missing warm checkpoint.
        for knobs in ({}, {"SCRIPTED_BANK_TAG": "0"},
                      {"SCRIPTED_BANK_TAG": "4", "SCRIPTED_BOT_TYPE": "1"},
                      {"SCRIPTED_BANK_TAG": "1", "SCRIPTED_BOT_TYPE": "0"}):
            result = run(SCREEN, {**BASE, **self.RUNG_OK, **knobs})
            self.assertNotEqual(result.returncode, 0, knobs)
            self.assertNotIn("SCRIPTED_B", result.stderr, knobs)
            self.assertIn("missing warm checkpoint", result.stderr, knobs)

    def test_screen_passes_and_records_scripted_bank_knobs_explicitly(self):
        source = SCREEN.read_text(encoding="utf-8")
        # Unset resolves to the explicit 0 inside the rung branch only.
        self.assertIn('SCRIPTED_BANK_TAG="${SCRIPTED_BANK_TAG:-0}"', source)
        self.assertIn('SCRIPTED_BOT_TYPE="${SCRIPTED_BOT_TYPE:-0}"', source)
        # Passed to the per-arm launcher with the other rung knobs.
        self.assertIn('LADDER_RESET_PCT="$LADDER_RESET_PCT" \\\n'
                      '                  SCRIPTED_BANK_TAG="$SCRIPTED_BANK_TAG" \\\n'
                      '                  SCRIPTED_BOT_TYPE="$SCRIPTED_BOT_TYPE")', source)
        # Recorded as ints in the contract, unconditionally for a rung.
        self.assertIn('"scripted_bank_tag": int(os.environ["SCRIPTED_BANK_TAG"])',
                      source)
        self.assertIn('"scripted_bot_type": int(os.environ["SCRIPTED_BOT_TYPE"])',
                      source)

    def test_rung_launcher_and_stage_forward_scripted_bank_knobs(self):
        source = RUNG.read_text(encoding="utf-8")
        self.assertIn('SCRIPTED_BANK_TAG="${SCRIPTED_BANK_TAG:-0}"', source)
        self.assertIn('SCRIPTED_BOT_TYPE="${SCRIPTED_BOT_TYPE:-0}"', source)
        self.assertIn('SCRIPTED_BANK_TAG="$SCRIPTED_BANK_TAG" \\\n'
                      '      SCRIPTED_BOT_TYPE="$SCRIPTED_BOT_TYPE" \\\n'
                      '      bash "$C/tools/run_reward_screen.sh"', source)
        self.assertIn('"scripted_bank_tag": int(scripted_bank_tag)', source)
        self.assertIn('"scripted_bot_type": int(scripted_bot_type)', source)
        stage = (ROOT / "tools/ladder_stage.sh").read_text(encoding="utf-8")
        self.assertIn('[ -z "${SCRIPTED_BANK_TAG:-}" ] || export SCRIPTED_BANK_TAG',
                      stage)
        self.assertIn('[ -z "${SCRIPTED_BOT_TYPE:-}" ] || export SCRIPTED_BOT_TYPE',
                      stage)

    def _rung_env(self, **over):
        env = os.environ.copy()
        for key in list(env):
            if key.startswith(("LADDER_", "GRAFT_", "SCRIPTED_")):
                env.pop(key)
        env.update({"C": str(ROOT), "RUNG": "9", "WARM": "missing.bin",
                    "POOL": "missing-pool", "EXPECTED_POOL_HASH": "0" * 64,
                    "OUT": "/nonexistent/never-created"})
        env.update(over)
        return env

    def _run_rung(self, **over):
        return subprocess.run(
            ["bash", str(RUNG)], cwd=ROOT, env=self._rung_env(**over), text=True,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
            timeout=60)

    def test_rung_launcher_validates_ladder_profile_and_graft_declaration(self):
        result = self._run_rung(LADDER_PROFILE="bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LADDER_PROFILE must be ladder-rung or graft", result.stdout)
        # Default profile refuses a stray graft declaration.
        for knob in ("GRAFT_FROM_SOURCE_SHA256", "GRAFT_REASON"):
            result = self._run_rung(**{knob: "x"})
            self.assertNotEqual(result.returncode, 0, knob)
            self.assertIn("require LADDER_PROFILE=graft", result.stdout, knob)
        # graft requires all three.
        for missing, message in (
            ("GRAFT_FROM_SOURCE_SHA256", "GRAFT_FROM_SOURCE_SHA256 is required"),
            ("GRAFT_FROM_PATCH_BUNDLE_SHA256",
             "GRAFT_FROM_PATCH_BUNDLE_SHA256 is required"),
            ("GRAFT_REASON", "GRAFT_REASON is required"),
        ):
            declared = {"GRAFT_FROM_SOURCE_SHA256": "a" * 64,
                        "GRAFT_FROM_PATCH_BUNDLE_SHA256": "b" * 64,
                        "GRAFT_REASON": "D242"}
            declared.pop(missing)
            result = self._run_rung(LADDER_PROFILE="graft", **declared)
            self.assertNotEqual(result.returncode, 0, missing)
            self.assertIn(message, result.stdout, missing)

    def test_rung_launcher_forwards_the_profile_and_graft_and_marks_the_same_result(self):
        source = RUNG.read_text(encoding="utf-8")
        self.assertIn('LADDER_PROFILE="${LADDER_PROFILE:-ladder-rung}"', source)
        self.assertIn('SCREEN_PROFILE="$LADDER_PROFILE"', source)
        self.assertNotIn("env SCREEN_PROFILE=ladder-rung", source)
        self.assertIn('env ${GRAFT_ENV[@]+"${GRAFT_ENV[@]}"}', source)
        self.assertIn('GRAFT_REASON="$GRAFT_REASON")', source)
        # One TAG for both profiles: the screen names a graft arm exactly like
        # a rung arm (s_both at SEED), so RESULT/COMPLETE resolve unchanged and
        # LADDER_RUNG_COMPLETE.json is published the same way.
        self.assertEqual(source.count('TAG="${PREFIX}-s_both-s${SEED}"'), 1)
        self.assertIn('RESULT="$SCREEN_DIR/${TAG}.result.json"', source)
        self.assertIn('"profile": profile,', source)
        self.assertIn('if profile == "graft":\n    payload["graft"] = {', source)
        stage = (ROOT / "tools/ladder_stage.sh").read_text(encoding="utf-8")
        for knob in ("LADDER_PROFILE", "GRAFT_FROM_SOURCE_SHA256",
                     "GRAFT_FROM_PATCH_BUNDLE_SHA256", "GRAFT_REASON"):
            self.assertIn(f'[ -z "${{{knob}:-}}" ] || export {knob}', stage)

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
