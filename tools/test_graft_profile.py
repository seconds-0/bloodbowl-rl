#!/usr/bin/env python3
"""The graft profile is the reviewed lineage bridge across a build change.

lineage-v6 refuses any warm/pool sidecar that does not bind THIS build's
source/module/patch digests. That is what keeps an obs-v4/obs-v5 checkpoint out
of an obs-v6 run, and it also means a deliberate, reviewed source or Puffer
patch-bundle change strands every existing lineage. graft-v6 (launcher) and
SCREEN_PROFILE=graft (screen) are the one sanctioned way across: each sidecar
is validated as internally consistent + eligible on its OWN recorded
implementation, then checkpoint_lineage.graft_bridge requires every one of
{warm, bank0..3} to bind either this build exactly or the old build the
operator declares with GRAFT_FROM_SOURCE_SHA256 / GRAFT_FROM_PATCH_BUNDLE_SHA256
(any module), with at least one old-build sidecar and one shared old module.
GRAFT_REASON names the review. The accepted checkpoint publishes on the NEW
build with ancestry.grafted_from. Because a sidecar may already be new-build,
the rungs AFTER a graft (new-build warm, mixed pool) stay launchable. These
tests exercise the real scripts up to the point of artifact I/O and assert on
specific messages, never exit status alone.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import tempfile
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


def scrubbed_environ():
    """Drop every knob the scripts read, so an operator's shell cannot leak in."""
    return {
        k: v for k, v in os.environ.items()
        if not k.startswith(("SCRIPTED_", "GRAFT_", "LADDER_"))
        and k not in ("WARM", "POOL", "CANDIDATE_ARM", "BOOTSTRAP_MODE",
                      "EXPECTED_POOL_HASH", "STEPS", "SCREEN_PROFILE",
                      "TAG", "REWARD_MANIFEST", "SEED", "PREFIX", "OUT_DIR")
    }


def run(script, env):
    merged = scrubbed_environ()
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
    "GRAFT_REASON": "D242",
}


class GraftLauncherTests(unittest.TestCase):
    def test_graft_v6_is_a_bootstrap_mode(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "nonsense"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("lineage-v6, or graft-v6", result.stderr)

    def test_graft_v6_requires_the_full_declaration(self):
        for missing, message in (
            ("GRAFT_FROM_SOURCE_SHA256",
             "GRAFT_FROM_SOURCE_SHA256 is required for graft-v6"),
            ("GRAFT_FROM_PATCH_BUNDLE_SHA256",
             "GRAFT_FROM_PATCH_BUNDLE_SHA256 is required for graft-v6"),
            ("GRAFT_REASON", "GRAFT_REASON is required for graft-v6"),
        ):
            env = {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6",
                   **{k: v for k, v in GRAFT_FROM.items() if k != missing}}
            result = run(LAUNCHER, env)
            self.assertNotEqual(result.returncode, 0, missing)
            self.assertIn(message, result.stderr, missing)

    def test_graft_v6_requires_well_formed_digests_and_reason(self):
        for bad in ("A" * 64, "a" * 63, "not-a-sha"):
            result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6",
                                    **GRAFT_FROM,
                                    "GRAFT_FROM_SOURCE_SHA256": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("GRAFT_FROM_SOURCE_SHA256 must be a lowercase SHA-256",
                          result.stderr, bad)
        for bad in ("   ", "x" * 201):
            result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6",
                                    **GRAFT_FROM, "GRAFT_REASON": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("GRAFT_REASON must be a non-empty string of at most 200",
                          result.stderr, bad)

    def test_graft_from_is_refused_outside_graft_v6(self):
        for mode in ("lineage-v6", "fresh-v6-genesis"):
            for knob in ("GRAFT_FROM_SOURCE_SHA256", "GRAFT_REASON"):
                env = {**LAUNCHER_BASE, "BOOTSTRAP_MODE": mode,
                       knob: GRAFT_FROM[knob]}
                if mode.startswith("fresh"):
                    env.pop("WARM"); env.pop("POOL"); env.pop("EXPECTED_POOL_HASH")
                result = run(LAUNCHER, env)
                self.assertNotEqual(result.returncode, 0, (mode, knob))
                self.assertIn("only valid with BOOTSTRAP_MODE=graft-v6",
                              result.stderr, (mode, knob))

    def test_graft_v6_gets_past_the_mode_gate_like_lineage_v6(self):
        # With everything declared, graft-v6 must reach a LATER failure (the
        # deliberately missing warm checkpoint), exactly where lineage-v6 does.
        for mode in ("graft-v6", "lineage-v6"):
            env = {**LAUNCHER_BASE, "BOOTSTRAP_MODE": mode}
            if mode == "graft-v6":
                env.update(GRAFT_FROM)
            result = run(LAUNCHER, env)
            self.assertNotEqual(result.returncode, 0, mode)
            self.assertNotIn("GRAFT_", result.stderr, mode)
            self.assertNotIn("BOOTSTRAP_MODE must be", result.stderr, mode)
            self.assertTrue(failed_later(result), (mode, result.stderr))

    def test_scripted_bank_is_allowed_with_graft_v6(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "graft-v6",
                                **GRAFT_FROM, "SCRIPTED_BANK_TAG": "2"})
        self.assertNotIn("SCRIPTED_BANK_TAG", result.stderr)
        self.assertTrue(failed_later(result), result.stderr)

    def test_launcher_uses_the_shared_graft_bridge_and_records_the_graft(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        # Only the sidecar-implementation validation differs from lineage-v6,
        # and it is the SAME function the screen plan writer calls.
        self.assertIn('graft = mode == "graft-v6"', source)
        self.assertIn("expected = None if graft else current", source)
        self.assertIn("from checkpoint_lineage import LineageError, graft_bridge",
                      source)
        self.assertIn("graft_module = graft_bridge(", source)
        self.assertIn('graft_sidecars.append((f"pool bank {index}", payload))',
                      source)
        # The five graft_from_* keys go into the run manifest, all or none.
        self.assertIn('graft_from_source_sha256 "$GRAFT_FROM_SOURCE_SHA256"', source)
        self.assertIn('graft_from_module_sha256 "$GRAFT_FROM_MODULE_SHA256"', source)
        self.assertIn('graft_from_patch_bundle_sha256 "$GRAFT_FROM_PATCH_BUNDLE_SHA256"',
                      source)
        self.assertIn('graft_from_warm_lineage_sha256 "$WARM_LINEAGE_HASH"', source)
        self.assertIn('graft_reason "$GRAFT_REASON"', source)
        # Everything else keys on POOL_MODE, so graft-v6 shares lineage-v6's
        # selfplay/pool command and initialization string.
        self.assertIn("lineage-v6|graft-v6) POOL_MODE=1 ;;", source)
        self.assertNotIn('[ "$BOOTSTRAP_MODE" != "lineage-v6" ]', source)
        self.assertNotIn('[ "$BOOTSTRAP_MODE" = "lineage-v6" ]', source)
        self.assertIn('"$([ "$POOL_MODE" != "1" ] && printf fresh || printf lineage-v6)"',
                      source)


def mint_lineage(root, checkpoint, *, source, module, patch, seed=42, fill=b"x",
                 qualification_only=False, observation_version=6):
    """Publish a lineage sidecar bound to the given build.

    Eligible lineage-v6 by default; ``qualification_only`` mints an ineligible
    fresh canary sidecar and ``observation_version`` lets a test forge an
    obs-v5-labelled sidecar (written raw, since the tool itself refuses it)."""
    import sys
    sys.path.insert(0, str(ROOT / "tools"))
    import checkpoint_lineage as cl
    checkpoint.write_bytes(fill + b"\0" * (cl.EXPECTED_CHECKPOINT_BYTES - len(fill)))
    manifest = root / (checkpoint.name + ".manifest.json")
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "mode": ("native_fresh_v6_qualification" if qualification_only
                 else "native_static_pool_reward_ablation"),
        "seed": str(seed), "observation_abi": "obs-v6",
        "observation_version": "6", "action_abi": "exact-joint-v1",
        "initialization": "fresh" if qualification_only else "lineage-v6",
        "qualification_only": "1" if qualification_only else "0",
        "policy_hidden_size": "512", "policy_num_layers": "3",
        "policy_expansion_factor": "1",
        "expected_checkpoint_bytes": str(cl.EXPECTED_CHECKPOINT_BYTES),
        "source_sha256": source, "compiled_module_sha256": module,
        "puffer_patch_bundle_sha256": patch, "screen_manifest_sha256": "4" * 64,
        "warm_lineage_sha256": "" if qualification_only else "5" * 64,
        "pool_lineage_bundle_sha256": "" if qualification_only else "6" * 64,
    }, sort_keys=True) + "\n", encoding="utf-8")
    payload = cl.lineage_from_run_manifest(
        checkpoint, manifest, allow_eligible_publication=not qualification_only)
    if observation_version != 6:
        payload["compatibility"]["observation_version"] = observation_version
        payload["compatibility"]["observation_abi"] = f"obs-v{observation_version}"
    sidecar = cl.sidecar_path(checkpoint)
    cl.write_lineage(sidecar, payload, replace=True)
    return sidecar, cl.lineage_digest(payload)


class GraftLauncherValidationTests(unittest.TestCase):
    """Run the launcher's embedded warm/pool validation against real sidecars.

    This is the one block where graft-v6 differs from lineage-v6, so it is
    exercised directly. Builds: OLD = (a, b, c), OTHER-OLD = (d, e, f),
    NEW = (1, 2, 3) as (source, module, patch)."""

    OLD = ("a" * 64, "b" * 64, "c" * 64)
    OTHER = ("d" * 64, "e" * 64, "f" * 64)
    NEW = ("1" * 64, "2" * 64, "3" * 64)

    @classmethod
    def setUpClass(cls):
        source = LAUNCHER.read_text(encoding="utf-8")
        match = re.search(
            r'"\$GRAFT_FROM_SOURCE_SHA256" "\$GRAFT_FROM_PATCH_BUNDLE_SHA256" <<\'PY\'\n'
            r"(.*?)\nPY\n  \)\n", source, re.S)
        assert match, "launcher lineage-validation heredoc not found"
        cls.block = match.group(1)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def build(self, warm_build, bank_builds, **warm_kw):
        warm = self.root / "warm.bin"
        _, warm_lineage = mint_lineage(
            self.root, warm, source=warm_build[0], module=warm_build[1],
            patch=warm_build[2], **warm_kw)
        pool = self.root / "pool"
        pool.mkdir()
        seeds = []
        for bank, build in enumerate(bank_builds):
            checkpoint = pool / f"{bank:016d}.bin"
            sidecar, digest = mint_lineage(
                pool, checkpoint, source=build[0], module=build[1],
                patch=build[2], seed=1042 + bank, fill=f"bank{bank}".encode())
            seeds.append({"bank": bank, "name": f"gen{bank}",
                          "file": checkpoint.name, "lineage_file": sidecar.name,
                          "lineage_sha256": digest})
        (pool / "league_seeds.json").write_text(
            json.dumps({"seeds": seeds}), encoding="utf-8")
        return warm, pool, warm_lineage

    def validate(self, warm, pool, mode, graft_source="", graft_patch="",
                 new=None):
        new = new or self.NEW
        return subprocess.run(
            ["python3", "-", str(ROOT), str(warm), str(pool), *new,
             mode, graft_source, graft_patch],
            input=self.block, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=120)

    def test_lineage_v6_refuses_old_build_sidecars_on_the_new_build(self):
        warm, pool, _ = self.build(self.OLD, [self.OLD] * 4)
        out = self.validate(warm, pool, "lineage-v6")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("source_sha256 lineage mismatch", out.stderr)

    def test_graft_v6_accepts_all_old_and_reports_the_old_module(self):
        warm, pool, warm_lineage = self.build(self.OLD, [self.OLD] * 4)
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertEqual(out.returncode, 0, out.stderr)
        warm_sha, bundle, module = out.stdout.split()
        self.assertEqual(warm_sha, warm_lineage)
        self.assertEqual(module, self.OLD[1])
        self.assertEqual(len(bundle), 64)

    def test_mixed_pool_after_a_graft_is_refused_by_lineage_v6_and_accepted_by_graft(self):
        # Rung N+1: warm is the accepted (new-build) graft checkpoint, the pool
        # is three old-build banks plus that new checkpoint. Without the
        # either/or rule this rung could never launch: lineage-v6 refuses the
        # old banks, and a graft that required the WARM to be old-build would
        # refuse the warm.
        warm, pool, warm_lineage = self.build(
            self.NEW, [self.OLD, self.OLD, self.OLD, self.NEW])
        out = self.validate(warm, pool, "lineage-v6")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("lineage mismatch", out.stderr)
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertEqual(out.returncode, 0, out.stderr)
        warm_sha, _, module = out.stdout.split()
        self.assertEqual(warm_sha, warm_lineage)
        self.assertEqual(module, self.OLD[1])

    def test_a_bank_from_a_different_old_build_is_refused(self):
        warm, pool, _ = self.build(
            self.NEW, [self.OLD, self.OLD, self.OTHER, self.NEW])
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("pool bank 2 binds neither this build nor the declared old build",
                      out.stderr)

    def test_old_build_sidecars_recording_different_modules_are_refused(self):
        rehosted_old = (self.OLD[0], "9" * 64, self.OLD[2])
        warm, pool, _ = self.build(self.OLD, [self.OLD, rehosted_old, self.OLD, self.OLD])
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("record different compiled modules", out.stderr)

    def test_graft_v6_refuses_a_declaration_nothing_binds(self):
        warm, pool, _ = self.build(self.OLD, [self.OLD] * 4)
        out = self.validate(warm, pool, "graft-v6", "9" * 64, self.OLD[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("warm binds neither this build nor the declared old build",
                      out.stderr)

    def test_graft_v6_with_nothing_old_is_a_refused_no_op_naming_rehost(self):
        warm, pool, _ = self.build(self.NEW, [self.NEW] * 4)
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("graft refused as a no-op", out.stderr)
        self.assertIn("rehost", out.stderr)
        # Declaring THIS build as the old build is the same refusal.
        out = self.validate(warm, pool, "graft-v6", self.NEW[0], self.NEW[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("nothing to graft", out.stderr)
        self.assertIn("rehost", out.stderr)

    def test_graft_v6_still_requires_eligible_hash_bound_sidecars(self):
        # Tamper with one pool bank's checkpoint bytes: its sidecar no longer
        # binds it, and no GRAFT_FROM declaration can paper over that.
        warm, pool, _ = self.build(self.OLD, [self.OLD] * 4)
        bank = pool / f"{2:016d}.bin"
        original = bank.read_bytes()
        bank.write_bytes(b"tampered" + original[len(b"tampered"):])
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("SHA-256 differs from lineage", out.stderr)

    def test_graft_v6_refuses_a_qualification_only_warm(self):
        warm, pool, _ = self.build(self.OLD, [self.OLD] * 4,
                                   qualification_only=True)
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("qualification-only checkpoint is not eligible ancestry",
                      out.stderr)

    def test_graft_v6_refuses_an_obs_v5_labelled_sidecar(self):
        # A graft relaxes the implementation binding, never the observation
        # lineage: obs-v5 and obs-v6 are the same 2782 bytes.
        warm, pool, _ = self.build(self.OLD, [self.OLD] * 4,
                                   observation_version=5)
        out = self.validate(warm, pool, "graft-v6", self.OLD[0], self.OLD[2])
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("observation_abi/observation_version lineage mismatch",
                      out.stderr)


SCREEN_BASE = {
    "WARM": "missing.bin",
    "POOL": "missing-pool",
    "STEPS": "5000000000",
    "SCREEN_PROFILE": "graft",
    "EXPECTED_POOL_HASH": "0" * 64,
    "LADDER_ENDZONE_MAXDIST": "9",
    "LADDER_RESET_PCT": "0.5",
    "LADDER_SEED": "42",
}


class GraftScreenProfileTests(unittest.TestCase):
    def test_profile_is_listed_and_is_one_s_both_arm_at_the_ladder_seed(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("ladder-rung, graft, paired-confirmation", source)
        self.assertRegex(
            source,
            r"\n  graft\)\n(?:.*\n)*?\s+arms=\(s_both\)\n\s+seeds=\(\"\$LADDER_SEED\"\)",
        )
        # And it is the graft-v6 bootstrap mode, never lineage-v6.
        self.assertIn('if [ "$SCREEN_PROFILE" = "graft" ]; then\n'
                      '    BOOTSTRAP_MODE=graft-v6', source)

    def test_graft_requires_the_full_declaration(self):
        for missing, message in (
            ("GRAFT_FROM_SOURCE_SHA256", "graft requires GRAFT_FROM_SOURCE_SHA256"),
            ("GRAFT_FROM_PATCH_BUNDLE_SHA256",
             "graft requires GRAFT_FROM_PATCH_BUNDLE_SHA256"),
            ("GRAFT_REASON", "graft requires GRAFT_REASON"),
        ):
            env = {**SCREEN_BASE,
                   **{k: v for k, v in GRAFT_FROM.items() if k != missing}}
            result = run(SCREEN, env)
            self.assertNotEqual(result.returncode, 0, missing)
            self.assertIn(message, result.stderr, missing)
        for bad in ("A" * 64, "a" * 63, "0x" + "a" * 62):
            result = run(SCREEN, {**SCREEN_BASE, **GRAFT_FROM,
                                  "GRAFT_FROM_PATCH_BUNDLE_SHA256": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("graft requires GRAFT_FROM_PATCH_BUNDLE_SHA256",
                          result.stderr, bad)
        for bad in ("  ", "r" * 201):
            result = run(SCREEN, {**SCREEN_BASE, **GRAFT_FROM, "GRAFT_REASON": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("graft requires GRAFT_REASON", result.stderr, bad)

    def test_graft_from_is_refused_on_every_other_profile(self):
        for profile, extra in (
            ("ladder-rung", {"LADDER_ENDZONE_MAXDIST": "9",
                             "LADDER_RESET_PCT": "0.5", "LADDER_SEED": "42"}),
            ("control-final", {}),
            ("genesis", {}),
        ):
            for knob in ("GRAFT_FROM_SOURCE_SHA256", "GRAFT_REASON"):
                env = {"WARM": "missing.bin", "POOL": "missing-pool",
                       "STEPS": "12000000000", "SCREEN_PROFILE": profile,
                       "EXPECTED_POOL_HASH": "0" * 64, **extra,
                       knob: GRAFT_FROM[knob]}
                if profile == "genesis":
                    env.pop("WARM"); env.pop("POOL")
                result = run(SCREEN, env)
                self.assertNotEqual(result.returncode, 0, (profile, knob))
                self.assertIn("only valid with SCREEN_PROFILE=graft",
                              result.stderr, (profile, knob))

    def test_graft_takes_the_rung_knobs_and_requires_them(self):
        for drop, message in (
            ("LADDER_ENDZONE_MAXDIST", "graft requires LADDER_ENDZONE_MAXDIST"),
            ("LADDER_RESET_PCT", "graft requires LADDER_RESET_PCT"),
            ("LADDER_SEED", "graft requires LADDER_SEED"),
        ):
            env = {k: v for k, v in {**SCREEN_BASE, **GRAFT_FROM}.items()
                   if k != drop}
            result = run(SCREEN, env)
            self.assertNotEqual(result.returncode, 0, drop)
            self.assertIn(message, result.stderr, drop)
        result = run(SCREEN, {**SCREEN_BASE, **GRAFT_FROM,
                              "SCRIPTED_BANK_TAG": "7"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("graft requires SCRIPTED_BANK_TAG", result.stderr)

    def test_graft_gets_past_the_profile_gate_to_the_warm_start_inputs(self):
        for knobs in ({}, {"SCRIPTED_BANK_TAG": "3", "SCRIPTED_BOT_TYPE": "1"}):
            result = run(SCREEN, {**SCREEN_BASE, **GRAFT_FROM, **knobs})
            self.assertNotEqual(result.returncode, 0, knobs)
            self.assertNotIn("graft requires", result.stderr, knobs)
            self.assertNotIn("only valid with", result.stderr, knobs)
            self.assertIn("missing warm checkpoint", result.stderr, knobs)

    def test_graft_rejects_candidate_inputs_like_a_rung(self):
        result = run(SCREEN, {**SCREEN_BASE, **GRAFT_FROM,
                              "CANDIDATE_ARM": "gain_only"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate transfer inputs are only valid", result.stderr)

    def test_plan_writer_uses_the_shared_graft_bridge_and_records_the_graft(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn('graft = profile == "graft"', source)
        self.assertIn("implementation_expected = None if graft else current_implementation",
                      source)
        self.assertIn("from checkpoint_lineage import LineageError, graft_bridge",
                      source)
        self.assertIn("old_module = graft_bridge(", source)
        # Pool banks get the same treatment in the plan writer.
        self.assertIn("expected=None, require_eligible=True)", source)
        self.assertIn('graft_sidecars.append((f"pool bank {index}", bank_payload))',
                      source)
        # Contract records the bridge (with its reason), plus the rung knobs.
        self.assertIn('contract["graft"] = graft_identity', source)
        for key in ("from_source_sha256", "from_patch_bundle_sha256",
                    "from_module_sha256", "warm_lineage_sha256", "reason"):
            self.assertIn(f'"{key}":', source)
        self.assertIn('if profile in ("ladder-rung", "graft"):', source)
        # Per-arm launcher receives the rung knobs AND the graft declaration.
        self.assertIn('elif [ "$SCREEN_PROFILE" = "graft" ]; then\n'
                      '      LADDER_ENV=(LADDER_ENDZONE_MAXDIST=', source)
        self.assertIn('GRAFT_FROM_PATCH_BUNDLE_SHA256="$GRAFT_FROM_PATCH_BUNDLE_SHA256" \\\n'
                      '                  GRAFT_REASON="$GRAFT_REASON")', source)
        # materialize_result is unchanged: the published sidecar is validated
        # against the NEW build's implementation digests.
        self.assertIn('"source_sha256": screen["implementation"]["source_sha256"],',
                      source)
        self.assertIn('lineage_from_run_manifest(\n'
                      '    checkpoint, run_manifest_path, '
                      'allow_eligible_publication=True)', source)


if __name__ == "__main__":
    unittest.main()
