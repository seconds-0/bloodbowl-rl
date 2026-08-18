#!/usr/bin/env python3
"""The graft profile is the reviewed lineage bridge across a build change.

lineage-v6 refuses any warm/pool sidecar that does not bind THIS build's
source/module/patch digests. That is what keeps an obs-v4/obs-v5 checkpoint out
of an obs-v6 run, and it also means a deliberate, reviewed source or Puffer
patch-bundle change strands every existing lineage. graft-v6 (launcher) and
SCREEN_PROFILE=graft (screen) are the one sanctioned way across: the sidecars
are validated as internally consistent + eligible on their OWN recorded
implementation, the operator declares what is being grafted from with
GRAFT_FROM_SOURCE_SHA256 / GRAFT_FROM_PATCH_BUNDLE_SHA256 (which must equal the
warm sidecar's record), and the accepted checkpoint publishes on the NEW build
with ancestry.grafted_from. These tests exercise the real scripts up to the
point of artifact I/O and assert on specific messages, never exit status alone.
"""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "tools/run_reward_screen.sh"
LAUNCHER = ROOT / "tools/run_reward_ablation.sh"
# The launcher's first failure past the mode/knob gates: on a training box the
# missing warm checkpoint, on a checkout without the vendored venv the venv.
LATER = ("missing warm checkpoint", "vendored Python missing")


def failed_later(result):
    return any(message in result.stderr for message in LATER)

SCRUB = ("LADDER_ENDZONE_MAXDIST", "LADDER_RESET_PCT", "LADDER_SEED",
         "SCRIPTED_BANK_TAG", "SCRIPTED_BOT_TYPE", "GRAFT_FROM_SOURCE_SHA256",
         "GRAFT_FROM_PATCH_BUNDLE_SHA256", "WARM", "POOL", "CANDIDATE_ARM",
         "BOOTSTRAP_MODE", "EXPECTED_POOL_HASH")


def run(script, env):
    merged = {k: v for k, v in os.environ.items() if k not in SCRUB}
    merged.update(env)
    return subprocess.run(
        ["bash", str(script)], cwd=ROOT, env=merged, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        timeout=120,
    )


LAUNCHER_BASE = {
    "TAG": "graft-launcher-test",
    "REWARD_MANIFEST": str(ROOT / "puffer/config/rewards/s0_both.json"),
    "STEPS": "1000000",
    "WARM": "missing.bin",
    "POOL": "missing-pool",
    "EXPECTED_POOL_HASH": "0" * 64,
}
GRAFT_FROM = {
    "GRAFT_FROM_SOURCE_SHA256": "a" * 64,
    "GRAFT_FROM_PATCH_BUNDLE_SHA256": "b" * 64,
}


class GraftLauncherTests(unittest.TestCase):
    def test_graft_v6_is_a_bootstrap_mode(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "nonsense"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lineage-v6, or graft-v6", result.stderr)

    def test_graft_v6_requires_both_graft_from_digests(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GRAFT_FROM_SOURCE_SHA256 is required for graft-v6",
                      result.stderr)
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6",
                                "GRAFT_FROM_SOURCE_SHA256": "a" * 64})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("GRAFT_FROM_PATCH_BUNDLE_SHA256 is required for graft-v6",
                      result.stderr)

    def test_graft_v6_requires_well_formed_digests(self):
        for bad in ("A" * 64, "a" * 63, "not-a-sha"):
            result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6",
                                    **GRAFT_FROM,
                                    "GRAFT_FROM_SOURCE_SHA256": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("GRAFT_FROM_SOURCE_SHA256 must be a lowercase SHA-256",
                          result.stderr, bad)

    def test_graft_from_is_refused_outside_graft_v6(self):
        for mode in ("lineage-v6", "fresh-v6-genesis"):
            env = {**LAUNCHER_BASE, "BOOTSTRAP_MODE": mode, **GRAFT_FROM}
            if mode.startswith("fresh"):
                env.pop("WARM"); env.pop("POOL"); env.pop("EXPECTED_POOL_HASH")
            result = run(LAUNCHER, env)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertIn("only valid with BOOTSTRAP_MODE=graft-v6",
                          result.stderr, mode)

    def test_graft_v6_gets_past_the_mode_gate_like_lineage_v6(self):
        # With everything declared, graft-v6 must reach a LATER failure (the
        # deliberately missing warm checkpoint), exactly where lineage-v6 does.
        for mode in ("graft-v6", "lineage-v6"):
            env = {**LAUNCHER_BASE, "BOOTSTRAP_MODE": mode}
            if mode == "graft-v6":
                env.update(GRAFT_FROM)
            result = run(LAUNCHER, env)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertNotIn("GRAFT_FROM", result.stderr, mode)
            self.assertNotIn("BOOTSTRAP_MODE must be", result.stderr, mode)
            self.assertTrue(failed_later(result), (mode, result.stderr))

    def test_scripted_bank_is_allowed_with_graft_v6(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6",
                                **GRAFT_FROM, "SCRIPTED_BANK_TAG": "2"})
        self.assertNotIn("SCRIPTED_BANK_TAG", result.stderr)
        self.assertTrue(failed_later(result), result.stderr)

    def test_launcher_validates_graft_sidecars_on_their_own_implementation(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        # Only the sidecar-implementation validation differs from lineage-v6.
        self.assertIn('graft = mode == "graft-v6"', source)
        self.assertIn("expected = None if graft else {", source)
        self.assertIn('if recorded["source_sha256"] != graft_source:', source)
        self.assertIn('if recorded["puffer_patch_bundle_sha256"] != graft_patch:',
                      source)
        self.assertIn('graft_module = recorded["compiled_module_sha256"]', source)
        self.assertIn("graft refused as a no-op", source)
        # The four graft_from_* keys go into the run manifest, all or none.
        self.assertIn('graft_from_source_sha256 "$GRAFT_FROM_SOURCE_SHA256"', source)
        self.assertIn('graft_from_module_sha256 "$GRAFT_FROM_MODULE_SHA256"', source)
        self.assertIn('graft_from_patch_bundle_sha256 "$GRAFT_FROM_PATCH_BUNDLE_SHA256"',
                      source)
        self.assertIn('graft_from_warm_lineage_sha256 "$WARM_LINEAGE_HASH"', source)
        # Everything else keys on POOL_MODE, so graft-v6 shares lineage-v6's
        # selfplay/pool command and initialization string.
        self.assertIn("lineage-v6|graft-v6) POOL_MODE=1 ;;", source)
        self.assertNotIn('[ "$BOOTSTRAP_MODE" != "lineage-v6" ]', source)
        self.assertNotIn('[ "$BOOTSTRAP_MODE" = "lineage-v6" ]', source)
        self.assertIn('"$([ "$POOL_MODE" != "1" ] && printf fresh || printf lineage-v6)"',
                      source)


if __name__ == "__main__":
    unittest.main()
