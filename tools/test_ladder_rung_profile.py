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
              if not k.startswith(("LADDER_", "SCRIPTED_", "GRAFT_", "BRIDGE_"))
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
            r"ladder-rung\)\n(?:.*\n)*?\s+arms=\(\"\$LADDER_ARM\"\)\n\s+seeds=\(\"\$LADDER_SEED\"\)",
        )

    def test_arm_knob_defaults_to_s_both_and_maps_sparse_to_s4(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn('LADDER_ARM="${LADDER_ARM:-s_both}"', source)
        self.assertIn("s_both|sparse|r0|r0_dist_half) ;;", source)
        self.assertRegex(
            source,
            r"sparse\) printf '%s\\n' \"\$ROOT/puffer/config/rewards/s4_sparse.json\"")
        self.assertIn('"arm": os.environ["LADDER_ARM"]', source)

    def test_frozen_bank_pct_is_overridable_and_validated(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn('FROZEN_BANK_PCT="${FROZEN_BANK_PCT:-0.06}"', source)
        self.assertNotIn("\nFROZEN_BANK_PCT=0.06\n", source)
        result = run(SCREEN, {**BASE, "LADDER_ENDZONE_MAXDIST": "6",
                              "LADDER_RESET_PCT": "0.5", "LADDER_SEED": "42",
                              "FROZEN_BANK_PCT": "abc"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FROZEN_BANK_PCT must be a decimal", result.stderr)
        result = run(SCREEN, {**BASE, "LADDER_ENDZONE_MAXDIST": "6",
                              "LADDER_RESET_PCT": "0.5", "LADDER_SEED": "42",
                              "FROZEN_BANK_PCT": "1.5"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("FROZEN_BANK_PCT must be a decimal", result.stderr)

    def test_rung_rejects_unknown_arm(self):
        result = run(SCREEN, {**BASE, "LADDER_ENDZONE_MAXDIST": "6",
                              "LADDER_RESET_PCT": "0.5", "LADDER_SEED": "42",
                              "LADDER_ARM": "r9"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LADDER_ARM must be s_both, sparse, r0 or r0_dist_half", result.stderr)

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
            if key.startswith(("LADDER_", "GRAFT_", "SCRIPTED_", "BRIDGE_")):
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

    BRIDGE_OK = {"BRIDGE_WARM_SHA256": "4e97ba4f" + "0" * 56,
                 "BRIDGE_WARM_OBS_VERSION": "4",
                 "BRIDGE_PROVENANCE": "runs/reward-transfer-20260713-v1 ANALYSIS.json",
                 "BRIDGE_REASON": "audit-2026-08-20 F2"}

    def test_rung_launcher_validates_ladder_profile_and_graft_declaration(self):
        result = self._run_rung(LADDER_PROFILE="bogus")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("LADDER_PROFILE must be ladder-rung, graft or bridge",
                      result.stdout)
        # Default profile refuses a stray graft declaration.
        for knob in ("GRAFT_FROM_SOURCE_SHA256", "GRAFT_REASON"):
            result = self._run_rung(**{knob: "x"})
            self.assertNotEqual(result.returncode, 0, knob)
            self.assertIn("require LADDER_PROFILE=graft", result.stdout, knob)
        # And a stray bridge declaration, on the default AND on graft.
        for profile in ({}, {"LADDER_PROFILE": "graft",
                             "GRAFT_FROM_SOURCE_SHA256": "a" * 64,
                             "GRAFT_FROM_PATCH_BUNDLE_SHA256": "b" * 64,
                             "GRAFT_REASON": "D242"}):
            for knob in ("BRIDGE_WARM_SHA256", "BRIDGE_REASON"):
                result = self._run_rung(**profile, **{knob: self.BRIDGE_OK[knob]})
                self.assertNotEqual(result.returncode, 0, (profile, knob))
                self.assertIn("require LADDER_PROFILE=bridge", result.stdout,
                              (profile, knob))
        # bridge refuses a graft declaration and requires all four of its own.
        result = self._run_rung(LADDER_PROFILE="bridge", **self.BRIDGE_OK,
                                GRAFT_REASON="D242")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("require LADDER_PROFILE=graft", result.stdout)
        for missing in self.BRIDGE_OK:
            declared = dict(self.BRIDGE_OK)
            declared.pop(missing)
            result = self._run_rung(LADDER_PROFILE="bridge", **declared)
            self.assertNotEqual(result.returncode, 0, missing)
            self.assertIn(f"{missing} is required for LADDER_PROFILE=bridge",
                          result.stdout, missing)
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
        # One TAG shape for every rung-shaped profile: the screen names the arm
        # <PREFIX>-<LADDER_ARM>-s<SEED>, so RESULT/COMPLETE must be derived from
        # the same LADDER_ARM the screen received. A hardcoded s_both here made
        # the first r0 rung complete its screen and then fail to publish its
        # marker (D256).
        self.assertEqual(source.count('TAG="${PREFIX}-${LADDER_ARM}-s${SEED}"'), 1)
        self.assertNotIn('TAG="${PREFIX}-s_both-s${SEED}"', source)
        self.assertIn('LADDER_ARM="${LADDER_ARM:-s_both}"', source)
        self.assertIn('LADDER_ARM="$LADDER_ARM" \\', source)
        self.assertIn('RESULT="$SCREEN_DIR/${TAG}.result.json"', source)
        self.assertIn('"profile": profile,', source)
        self.assertIn('if profile == "graft":\n    payload["graft"] = {', source)
        # The bridge rides the same forwarding array (only one of the two
        # declarations is ever set) and marks its identity next to graft's.
        self.assertIn('elif [ "$LADDER_PROFILE" = "bridge" ]; then\n'
                      '  GRAFT_ENV=(BRIDGE_WARM_SHA256="$BRIDGE_WARM_SHA256" \\\n',
                      source)
        self.assertIn('BRIDGE_REASON="$BRIDGE_REASON")', source)
        self.assertIn('if profile == "bridge":', source)
        self.assertIn('payload["bridge"] = {', source)
        stage = (ROOT / "tools/ladder_stage.sh").read_text(encoding="utf-8")
        for knob in ("LADDER_PROFILE", "GRAFT_FROM_SOURCE_SHA256",
                     "GRAFT_FROM_PATCH_BUNDLE_SHA256", "GRAFT_REASON",
                     "BRIDGE_WARM_SHA256", "BRIDGE_WARM_OBS_VERSION",
                     "BRIDGE_PROVENANCE", "BRIDGE_REASON"):
            self.assertIn(f'[ -z "${{{knob}:-}}" ] || export {knob}', stage)
        # Audit F1: chained rungs no longer default to the frozen 0.1 scale.
        self.assertIn('export LADDER_CHAIN_LR_SCALE=1.0', stage)
        self.assertNotIn('export LADDER_CHAIN_LR_SCALE=0.1', stage)

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


    def test_regression_gate_refuses_a_collapsed_same_distribution_rung(self):
        # D244: the screen's acceptance gate is an integrity gate; a policy that
        # collapsed into the abstinence basin still passes it. The marker step
        # refuses to publish when eval tds fell below the floor times the warm
        # rung's tds AND the two rungs share a start distribution.
        source = RUNG.read_text(encoding="utf-8")
        match = re.search(
            r'"\$WARM_MARKER" "\$LADDER_REGRESSION_FLOOR" \\\n'
            r'    "\$SCRIPTED_BANK_TAG" "\$SCRIPTED_BOT_TYPE" "\$LADDER_PROFILE" \\\n'
            r'    "\$GRAFT_FROM_SOURCE_SHA256" "\$GRAFT_FROM_PATCH_BUNDLE_SHA256" \\\n'
            r'    "\$GRAFT_REASON" \\\n'
            r'    "\$BRIDGE_WARM_SHA256" "\$BRIDGE_WARM_OBS_VERSION" "\$BRIDGE_PROVENANCE" \\\n'
            r'    "\$BRIDGE_REASON" <<\'PY\'\n(.*?)\nPY\n',
            source, re.S)
        self.assertIsNotNone(match, "marker/regression block not found")
        code = match.group(1)
        import json, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            res = tmp / "r.json"
            base = {"acceptance_pass": True, "tag": "t", "log": "l",
                    "checkpoint": "c", "checkpoint_sha256": "s",
                    "checkpoint_lineage": "cl", "checkpoint_lineage_sha256": "cls",
                    "eval_metrics": {"tds": 0.10, "perf": 0.48}}
            wm = tmp / "wm.json"
            wm.write_text(json.dumps({"rung": 0, "reset_pct": 0.25, "eval_tds": 0.695}))
            out = tmp / "m.json"

            def run(rung, reset, marker, tds, profile="ladder-rung",
                    bridge=("", "", "", "")):
                d = dict(base); d["eval_metrics"] = {"tds": tds, "perf": 0.5}
                res.write_text(json.dumps(d))
                return subprocess.run(
                    ["python3", "-", str(res), str(out), rung, reset, "5000000000",
                     "43", "w", "p", "pfx", marker, "0.5",
                     "0", "0", profile, "", "", "", *bridge],
                    input=code, text=True, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, check=False)

            r = run("0", "0.25", str(wm), 0.10)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("REGRESSION GATE", r.stderr)
            r = run("0", "0.25", str(wm), 0.60)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(out.read_text())["regression_gate"]["warm_eval_tds"], 0.695)
            self.assertEqual(json.loads(out.read_text())["eval_tds"], 0.6)
            # Both sides' marker fields survive the merge.
            marker = json.loads(out.read_text())
            for key in ("scripted_bank_tag", "scripted_bot_type", "profile",
                        "chain_lr_scale", "eval_perf", "regression_gate"):
                self.assertIn(key, marker)
            # A different start distribution is not comparable: gate skipped.
            r = run("0", "0", str(wm), 0.10)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertIsNone(json.loads(out.read_text())["regression_gate"])
            # An old-format marker without eval_tds: gate skipped, not crashed.
            wm.write_text(json.dumps({"rung": 0, "reset_pct": 0.25}))
            r = run("0", "0.25", str(wm), 0.10)
            self.assertEqual(r.returncode, 0, r.stderr)
            # A bridge marker records the raw warm's identity next to the
            # accepted result; a rung marker carries no bridge key at all.
            self.assertNotIn("bridge", json.loads(out.read_text()))
            r = run("0", "0", "", 0.30, profile="bridge",
                    bridge=("4" * 64, "4", "runs/reward-transfer-20260713-v1",
                            "audit-2026-08-20 F2"))
            self.assertEqual(r.returncode, 0, r.stderr)
            marker = json.loads(out.read_text())
            self.assertEqual(marker["profile"], "bridge")
            self.assertEqual(marker["bridge"], {
                "warm_sha256": "4" * 64, "warm_observation_version": 4,
                "provenance": "runs/reward-transfer-20260713-v1",
                "reason": "audit-2026-08-20 F2"})
            self.assertNotIn("graft", marker)


if __name__ == "__main__":
    unittest.main()


class LadderChainLrScaleTests(unittest.TestCase):
    def test_scale_is_rung_only_and_validated(self):
        base = {"WARM": "missing.bin", "POOL": "missing-pool", "STEPS": "5000000000",
                "EXPECTED_POOL_HASH": "0" * 64}
        r = run(SCREEN, {**base, "SCREEN_PROFILE": "control-final",
                         "LADDER_CHAIN_LR_SCALE": "0.1"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("only valid with SCREEN_PROFILE=ladder-rung", r.stderr)
        # graft is rung-like: the scale is accepted there too.
        r = run(SCREEN, {**base, "SCREEN_PROFILE": "graft",
                         "LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0.25",
                         "LADDER_SEED": "43", "LADDER_CHAIN_LR_SCALE": "0.1"})
        self.assertNotIn("LADDER_CHAIN_LR_SCALE is only valid", r.stderr)
        for bad in ("0", "0.1x", "4.5", "5", "0.0001"):
            r = run(SCREEN, {**base, "SCREEN_PROFILE": "ladder-rung",
                             "LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0.25",
                             "LADDER_SEED": "43", "LADDER_CHAIN_LR_SCALE": bad})
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("LADDER_CHAIN_LR_SCALE must be", r.stderr, bad)
        # LR probes above 1 (audit F3: Muon, lr is the relative step) are valid.
        for good in ("1.5", "2", "2.0", "4"):
            r = run(SCREEN, {**base, "SCREEN_PROFILE": "ladder-rung",
                             "LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0.25",
                             "LADDER_SEED": "43", "LADDER_CHAIN_LR_SCALE": good})
            self.assertNotIn("LADDER_CHAIN_LR_SCALE must be", r.stderr, good)
        # A valid scale passes the validator and fails later on the warm file.
        r = run(SCREEN, {**base, "SCREEN_PROFILE": "ladder-rung",
                         "LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0.25",
                         "LADDER_SEED": "43", "LADDER_CHAIN_LR_SCALE": "0.1"})
        self.assertIn("missing warm checkpoint", r.stderr)
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn('"chain_lr_scale": float(os.environ["LADDER_CHAIN_LR_SCALE"])', source)
        self.assertIn('"learning_rate": float(os.environ["LR"])', source)


class LadderChainEntScaleTests(unittest.TestCase):
    def test_ent_scale_is_rung_only_validated_and_entropy_only(self):
        base = {"WARM": "missing.bin", "POOL": "missing-pool", "STEPS": "5000000000",
                "EXPECTED_POOL_HASH": "0" * 64}
        rung = {**base, "SCREEN_PROFILE": "ladder-rung", "LADDER_ENDZONE_MAXDIST": "0",
                "LADDER_RESET_PCT": "0.25", "LADDER_SEED": "43"}
        r = run(SCREEN, {**base, "SCREEN_PROFILE": "control-final",
                         "LADDER_CHAIN_ENT_SCALE": "2"})
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("LADDER_CHAIN_ENT_SCALE is only valid with SCREEN_PROFILE=ladder-rung", r.stderr)
        for bad in ("0", "0.1x", "4.5", "5", "0.0001"):
            r = run(SCREEN, {**rung, "LADDER_CHAIN_ENT_SCALE": bad})
            self.assertNotEqual(r.returncode, 0, bad)
            self.assertIn("LADDER_CHAIN_ENT_SCALE must be", r.stderr, bad)
        for good in ("0.5", "1.5", "2", "2.0", "4"):
            r = run(SCREEN, {**rung, "LADDER_CHAIN_ENT_SCALE": good})
            self.assertNotIn("LADDER_CHAIN_ENT_SCALE must be", r.stderr, good)
            self.assertIn("missing warm checkpoint", r.stderr, good)
        source = SCREEN.read_text(encoding="utf-8")
        # The entropy scale multiplies ENT_COEF only, after the joint LR scale,
        # and is recorded in the screen manifest beside the LR scale.
        self.assertIn('"chain_ent_scale": float(os.environ["LADDER_CHAIN_ENT_SCALE"])', source)
        lr_block = source.index('"$LR" "$LADDER_CHAIN_LR_SCALE"')
        ent_block = source.index('"$ENT_COEF" "$LADDER_CHAIN_ENT_SCALE"')
        self.assertLess(lr_block, ent_block)
        self.assertNotIn('"$LR" "$LADDER_CHAIN_ENT_SCALE"', source)
        launcher = RUNG.read_text(encoding="utf-8")
        self.assertIn('LADDER_CHAIN_ENT_SCALE="${LADDER_CHAIN_ENT_SCALE:-1}"', launcher)
        self.assertIn('"chain_ent_scale": float(os.environ.get("LADDER_CHAIN_ENT_SCALE", "1"))', launcher)
        stage = (ROOT / "tools/ladder_stage.sh").read_text(encoding="utf-8")
        self.assertIn('[ -z "${LADDER_CHAIN_ENT_SCALE:-}" ] || export LADDER_CHAIN_ENT_SCALE', stage)
