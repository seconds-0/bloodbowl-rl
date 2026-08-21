#!/usr/bin/env python3
"""The bridge profile is the reviewed warm start from an OUT-OF-LINEAGE blob.

lineage-v6 requires a warm sidecar and graft-v6 re-binds one across a build
change; neither can start from a checkpoint that has no sidecar at all. The
2026-08-20 audit (docs/audit-2026-08-20.md F2) found exactly such a blob -- the
July obs-v4 R0 checkpoint -- loading unmodified on the current build and
playing ~6x better than the whole obs-v6 lineage, which had been restarted from
random weights because the tooling had no entry point for it. bridge-v4
(launcher) and SCREEN_PROFILE=bridge (screen) are that entry point, and they
are narrow on purpose: WARM is the raw blob, identified ONLY by the operator's
BRIDGE_WARM_SHA256 (asserted against the file everywhere it is read),
BRIDGE_WARM_OBS_VERSION (4|5), BRIDGE_PROVENANCE and BRIDGE_REASON; the warm is
never lineage-validated and a warm that HAS a sidecar is refused; the four pool
banks are validated exactly as lineage-v6 validates them, against THIS build;
the run manifest carries initialization=bridge, the four bridge_* keys and an
EMPTY warm_lineage_sha256, so the published sidecar records
ancestry.bridged_from and is ordinary eligible ancestry thereafter. These tests
exercise the real scripts up to the point of artifact I/O and assert on
specific messages, never exit status alone.
"""

from __future__ import annotations

import hashlib
import json
import pathlib
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.test_graft_profile import (
    LAUNCHER_BASE, GRAFT_FROM, failed_later, mint_lineage, run,
)

ROOT = Path(__file__).resolve().parents[1]
SCREEN = ROOT / "tools/run_reward_screen.sh"
LAUNCHER = ROOT / "tools/run_reward_ablation.sh"
STAGE = ROOT / "tools/ladder_stage.sh"

JULY_SHA = "4e97ba4ff72fcc71e154ca146caeab45eb7c5d9e584db42f17b07f77c72a7630"
BRIDGE = {
    "BRIDGE_WARM_SHA256": JULY_SHA,
    "BRIDGE_WARM_OBS_VERSION": "4",
    "BRIDGE_PROVENANCE": ("runs/reward-transfer-20260713-v1/checkpoints/"
                          "r0-s42-native.bin (ANALYSIS.json)"),
    "BRIDGE_REASON": "audit-2026-08-20 F2",
}


class BridgeLauncherTests(unittest.TestCase):
    def test_bridge_v4_is_a_bootstrap_mode(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "nonsense"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("graft-v6, or bridge-v4", result.stderr)

    def test_bridge_v4_requires_the_full_declaration(self):
        for missing in BRIDGE:
            env = {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                   **{k: v for k, v in BRIDGE.items() if k != missing}}
            result = run(LAUNCHER, env)
            self.assertNotEqual(result.returncode, 0, missing)
            self.assertIn(f"{missing} is required for bridge-v4", result.stderr,
                          missing)

    def test_bridge_v4_requires_well_formed_fields(self):
        for bad in ("A" * 64, "a" * 63, "not-a-sha"):
            result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                                    **BRIDGE, "BRIDGE_WARM_SHA256": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("BRIDGE_WARM_SHA256 must be a lowercase SHA-256",
                          result.stderr, bad)
        for bad in ("3", "6", "04", "v4", "4.0"):
            result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                                    **BRIDGE, "BRIDGE_WARM_OBS_VERSION": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("BRIDGE_WARM_OBS_VERSION must be 4 or 5", result.stderr,
                          bad)
        for bad in ("   ", "p" * 301):
            result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                                    **BRIDGE, "BRIDGE_PROVENANCE": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("BRIDGE_PROVENANCE must be a non-empty string of at most 300",
                          result.stderr, bad)
        for bad in ("   ", "r" * 201):
            result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                                    **BRIDGE, "BRIDGE_REASON": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("BRIDGE_REASON must be a non-empty string of at most 200",
                          result.stderr, bad)

    def test_bridge_vars_are_refused_outside_bridge_v4(self):
        for mode in ("lineage-v6", "graft-v6", "fresh-v6-genesis"):
            for knob in ("BRIDGE_WARM_SHA256", "BRIDGE_REASON"):
                env = {**LAUNCHER_BASE, "BOOTSTRAP_MODE": mode, knob: BRIDGE[knob]}
                if mode == "graft-v6":
                    env.update(GRAFT_FROM)
                if mode.startswith("fresh"):
                    env.pop("WARM"); env.pop("POOL"); env.pop("EXPECTED_POOL_HASH")
                result = run(LAUNCHER, env)
                self.assertNotEqual(result.returncode, 0, (mode, knob))
                self.assertIn("only valid with BOOTSTRAP_MODE=bridge-v4",
                              result.stderr, (mode, knob))
        # And graft vars are refused on a bridge: the two are exclusive.
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                                **BRIDGE, "GRAFT_REASON": "D242"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only valid with BOOTSTRAP_MODE=graft-v6", result.stderr)

    def test_bridge_v4_gets_past_the_mode_gate_like_lineage_v6(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                                **BRIDGE})
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("BRIDGE_", result.stderr)
        self.assertNotIn("BOOTSTRAP_MODE must be", result.stderr)
        self.assertTrue(failed_later(result), result.stderr)

    def test_scripted_bank_is_allowed_with_bridge_v4(self):
        result = run(LAUNCHER, {**LAUNCHER_BASE, "BOOTSTRAP_MODE": "bridge-v4",
                                **BRIDGE, "SCRIPTED_BANK_TAG": "2"})
        self.assertNotIn("SCRIPTED_BANK_TAG", result.stderr)
        self.assertTrue(failed_later(result), result.stderr)

    def test_launcher_asserts_the_hash_skips_warm_lineage_and_records_the_bridge(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        # Pool-backed like lineage-v6 (four banks, selfplay on, SCRIPTED_* ok).
        self.assertIn("lineage-v6|graft-v6|bridge-v4) POOL_MODE=1 ;;", source)
        # The declared digest is checked against the actual file, hard-fail.
        self.assertIn('if [ "$BOOTSTRAP_MODE" = "bridge-v4" ] && '
                      '[ "$WARM_HASH" != "$BRIDGE_WARM_SHA256" ]; then', source)
        # The warm is never lineage-validated; a sidecar-bearing warm is refused;
        # WARM_LINEAGE_HASH is published empty.
        self.assertIn('bridge = mode == "bridge-v4"', source)
        self.assertIn("if bridge:\n    # No sidecar to validate", source)
        self.assertIn('print(warm_lineage or "-", bundle, graft_module or "-")',
                      source)
        self.assertIn('[ "$WARM_LINEAGE_HASH" != "-" ] || WARM_LINEAGE_HASH=""',
                      source)
        self.assertIn('if [ "$BOOTSTRAP_MODE" = "bridge-v4" ] && '
                      '[ -n "$WARM_LINEAGE_HASH" ]; then', source)
        # Run manifest: initialization=bridge plus the four bridge_* keys.
        self.assertIn("  bridge-v4) INITIALIZATION=bridge ;;", source)
        self.assertIn('initialization "$INITIALIZATION"', source)
        self.assertIn('bridge_warm_sha256 "$BRIDGE_WARM_SHA256"', source)
        self.assertIn('bridge_warm_observation_version "$BRIDGE_WARM_OBS_VERSION"',
                      source)
        self.assertIn('bridge_provenance "$BRIDGE_PROVENANCE"', source)
        self.assertIn('bridge_reason "$BRIDGE_REASON"', source)
        self.assertIn('warm_lineage_sha256 "$WARM_LINEAGE_HASH"', source)


class BridgeLauncherValidationTests(unittest.TestCase):
    """Run the launcher's embedded warm/pool validation against real files.

    For bridge-v4 the block must skip the warm entirely and validate the four
    pool banks against THIS build (NEW = (1, 2, 3) as source, module, patch),
    exactly as lineage-v6 does; OLD = (a, b, c) banks are refused."""

    OLD = ("a" * 64, "b" * 64, "c" * 64)
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

    def build(self, bank_builds, warm_sidecar=None):
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import checkpoint_lineage as cl
        # One sub-root per build, so a test may build several fixtures.
        self.builds = getattr(self, "builds", 0) + 1
        root = self.root / f"build{self.builds}"
        root.mkdir()
        warm = root / "r0-s42-native.bin"
        if warm_sidecar is None:
            # A raw blob: right size, no sidecar, content nobody minted.
            warm.write_bytes(b"july-obs-v4" + b"\0" * (
                cl.EXPECTED_CHECKPOINT_BYTES - len(b"july-obs-v4")))
        else:
            mint_lineage(root, warm, source=warm_sidecar[0],
                         module=warm_sidecar[1], patch=warm_sidecar[2])
        pool = root / "pool"
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
        return warm, pool

    def validate(self, warm, pool, mode):
        return subprocess.run(
            ["python3", "-", str(ROOT), str(warm), str(pool), *self.NEW,
             mode, "", ""],
            input=self.block, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=120)

    def test_bridge_skips_the_warm_and_publishes_no_warm_lineage(self):
        warm, pool = self.build([self.NEW] * 4)
        out = self.validate(warm, pool, "bridge-v4")
        self.assertEqual(out.returncode, 0, out.stderr)
        warm_sha, bundle, module = out.stdout.split()
        self.assertEqual(warm_sha, "-")
        self.assertEqual(module, "-")
        self.assertEqual(len(bundle), 64)
        # The same raw warm is refused by lineage-v6: no sidecar at all.
        out = self.validate(warm, pool, "lineage-v6")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("missing checkpoint lineage", out.stderr)

    def test_bridge_refuses_a_warm_that_has_a_sidecar(self):
        warm, pool = self.build([self.NEW] * 4, warm_sidecar=self.NEW)
        out = self.validate(warm, pool, "bridge-v4")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("has a lineage sidecar", out.stderr)
        self.assertIn("lineage-v6", out.stderr)

    def test_bridge_validates_the_pool_exactly_like_lineage_v6(self):
        warm, pool = self.build([self.NEW, self.NEW, self.OLD, self.NEW])
        out = self.validate(warm, pool, "bridge-v4")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("source_sha256 lineage mismatch", out.stderr)
        # Tampered bank bytes: hash-bound sidecars still apply.
        warm, pool = self.build([self.NEW] * 4)
        bank = pool / f"{1:016d}.bin"
        original = bank.read_bytes()
        bank.write_bytes(b"tampered" + original[len(b"tampered"):])
        out = self.validate(warm, pool, "bridge-v4")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("SHA-256 differs from lineage", out.stderr)
        # A bank whose digest does not match the pool manifest.
        warm, pool = self.build([self.NEW] * 4)
        manifest = json.loads((pool / "league_seeds.json").read_text())
        manifest["seeds"][3]["lineage_sha256"] = "9" * 64
        (pool / "league_seeds.json").write_text(json.dumps(manifest))
        out = self.validate(warm, pool, "bridge-v4")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn("pool bank 3 lineage digest differs from manifest", out.stderr)


SCREEN_BASE = {
    "WARM": "missing.bin",
    "POOL": "missing-pool",
    "STEPS": "5000000000",
    "SCREEN_PROFILE": "bridge",
    "EXPECTED_POOL_HASH": "0" * 64,
    "LADDER_ENDZONE_MAXDIST": "0",
    "LADDER_RESET_PCT": "0",
    "LADDER_SEED": "42",
}


class BridgeScreenProfileTests(unittest.TestCase):
    def test_profile_is_listed_and_is_one_s_both_arm_at_the_ladder_seed(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn("ladder-rung, graft, bridge, paired-confirmation", source)
        self.assertRegex(
            source,
            r"\n  bridge\)\n(?:.*\n)*?\s+arms=\(\"\$LADDER_ARM\"\)\n\s+seeds=\(\"\$LADDER_SEED\"\)",
        )
        self.assertIn('elif [ "$SCREEN_PROFILE" = "bridge" ]; then\n'
                      '    BOOTSTRAP_MODE=bridge-v4', source)

    def test_bridge_requires_the_full_declaration(self):
        for missing in BRIDGE:
            env = {**SCREEN_BASE, **{k: v for k, v in BRIDGE.items() if k != missing}}
            result = run(SCREEN, env)
            self.assertNotEqual(result.returncode, 0, missing)
            self.assertIn(f"bridge requires {missing}", result.stderr, missing)
        for bad in ("A" * 64, "a" * 63, "0x" + "a" * 62):
            result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, "BRIDGE_WARM_SHA256": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("bridge requires BRIDGE_WARM_SHA256", result.stderr, bad)
        for bad in ("3", "6", "04", "v5"):
            result = run(SCREEN, {**SCREEN_BASE, **BRIDGE,
                                  "BRIDGE_WARM_OBS_VERSION": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("bridge requires BRIDGE_WARM_OBS_VERSION as 4 or 5",
                          result.stderr, bad)
        for bad in ("  ", "p" * 301):
            result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, "BRIDGE_PROVENANCE": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("bridge requires BRIDGE_PROVENANCE", result.stderr, bad)
        for bad in ("  ", "r" * 201):
            result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, "BRIDGE_REASON": bad})
            self.assertNotEqual(result.returncode, 0, bad)
            self.assertIn("bridge requires BRIDGE_REASON", result.stderr, bad)

    def test_bridge_vars_are_refused_on_every_other_profile(self):
        for profile, extra in (
            ("ladder-rung", {"LADDER_ENDZONE_MAXDIST": "9",
                             "LADDER_RESET_PCT": "0.5", "LADDER_SEED": "42"}),
            ("graft", {"LADDER_ENDZONE_MAXDIST": "9", "LADDER_RESET_PCT": "0.5",
                       "LADDER_SEED": "42", **GRAFT_FROM}),
            ("control-final", {}),
            ("genesis", {}),
        ):
            for knob in ("BRIDGE_WARM_SHA256", "BRIDGE_REASON"):
                env = {"WARM": "missing.bin", "POOL": "missing-pool",
                       "STEPS": "12000000000", "SCREEN_PROFILE": profile,
                       "EXPECTED_POOL_HASH": "0" * 64, **extra,
                       knob: BRIDGE[knob]}
                if profile == "genesis":
                    env.pop("WARM"); env.pop("POOL")
                result = run(SCREEN, env)
                self.assertNotEqual(result.returncode, 0, (profile, knob))
                self.assertIn("only valid with SCREEN_PROFILE=bridge",
                              result.stderr, (profile, knob))
        # And graft vars on a bridge.
        result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, "GRAFT_REASON": "D242"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("only valid with SCREEN_PROFILE=graft", result.stderr)

    def test_bridge_takes_the_rung_knobs_and_requires_them(self):
        for drop, message in (
            ("LADDER_ENDZONE_MAXDIST", "bridge requires LADDER_ENDZONE_MAXDIST"),
            ("LADDER_RESET_PCT", "bridge requires LADDER_RESET_PCT"),
            ("LADDER_SEED", "bridge requires LADDER_SEED"),
        ):
            env = {k: v for k, v in {**SCREEN_BASE, **BRIDGE}.items() if k != drop}
            result = run(SCREEN, env)
            self.assertNotEqual(result.returncode, 0, drop)
            self.assertIn(message, result.stderr, drop)
        result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, "SCRIPTED_BANK_TAG": "7"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bridge requires SCRIPTED_BANK_TAG", result.stderr)
        # LADDER_CHAIN_LR_SCALE is accepted on a bridge like on a rung.
        result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, "LADDER_CHAIN_LR_SCALE": "0.5"})
        self.assertNotIn("LADDER_CHAIN_LR_SCALE is only valid", result.stderr)

    def test_bridge_gets_past_the_profile_gate_to_the_warm_start_inputs(self):
        for knobs in ({}, {"SCRIPTED_BANK_TAG": "3", "SCRIPTED_BOT_TYPE": "1"}):
            result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, **knobs})
            self.assertNotEqual(result.returncode, 0, knobs)
            self.assertNotIn("bridge requires", result.stderr, knobs)
            self.assertNotIn("only valid with", result.stderr, knobs)
            self.assertIn("missing warm checkpoint", result.stderr, knobs)

    def test_bridge_rejects_candidate_inputs_like_a_rung(self):
        result = run(SCREEN, {**SCREEN_BASE, **BRIDGE, "CANDIDATE_ARM": "gain_only"})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate transfer inputs are only valid", result.stderr)

    def test_screen_refuses_a_declared_hash_that_does_not_match_the_warm(self):
        # Real files: the hash check runs before the lock and the plan writer,
        # so it is reachable off-box. With the RIGHT hash the screen proceeds
        # past every bridge gate to its later machinery.
        with tempfile.TemporaryDirectory() as tmp:
            warm = Path(tmp) / "r0-s42-native.bin"
            warm.write_bytes(b"july-obs-v4")
            actual = hashlib.sha256(warm.read_bytes()).hexdigest()
            pool = Path(tmp) / "pool"
            pool.mkdir()
            env = {**SCREEN_BASE, **BRIDGE, "WARM": str(warm), "POOL": str(pool),
                   "OUT_DIR": str(Path(tmp) / "out")}
            result = run(SCREEN, env)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(f"bridge warm {warm} has sha256 {actual} but "
                          f"BRIDGE_WARM_SHA256 declares {JULY_SHA}", result.stderr)
            result = run(SCREEN, {**env, "BRIDGE_WARM_SHA256": actual})
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("BRIDGE_WARM_SHA256", result.stderr)
            self.assertNotIn("missing warm checkpoint", result.stderr)
            self.assertNotIn("missing static pool", result.stderr)

    def test_plan_writer_skips_the_warm_validates_the_pool_and_records_the_bridge(self):
        source = SCREEN.read_text(encoding="utf-8")
        self.assertIn('bridge = profile == "bridge"', source)
        # Warm: no validate_lineage call on the bridge path, a sidecar is
        # refused, the declared hash is re-asserted, warm_lineage_sha is "".
        self.assertIn("    if bridge:\n        if sidecar_path(warm).exists():", source)
        self.assertIn('declared_sha = os.environ["BRIDGE_WARM_SHA256"]', source)
        self.assertIn("        warm_payload = None\n        warm_lineage_sha = \"\"",
                      source)
        # Pool: validated against THIS build, like lineage-v6's launcher does.
        self.assertIn("expected=current_implementation, require_eligible=True)",
                      source)
        # Contract: initialization=bridge, the bridge identity block, the rung
        # knobs, and the per-arm launcher receives the BRIDGE_* declaration.
        self.assertIn('else "bridge" if profile == "bridge"', source)
        self.assertIn('contract["bridge"] = bridge_identity', source)
        for key in ("warm_path", "warm_sha256", "warm_observation_version",
                    "provenance", "reason"):
            self.assertIn(f'"{key}":', source)
        self.assertIn('if profile in ("ladder-rung", "graft", "bridge"):', source)
        self.assertIn('elif [ "$SCREEN_PROFILE" = "bridge" ]; then\n'
                      '      LADDER_ENV=(LADDER_ENDZONE_MAXDIST=', source)
        self.assertIn('BRIDGE_PROVENANCE="$BRIDGE_PROVENANCE" \\\n'
                      '                  BRIDGE_REASON="$BRIDGE_REASON")', source)
        # Contract drift: the whole contract (bridge block included) must match
        # an existing SCREEN_MANIFEST.json before any arm is reused.
        self.assertIn('if existing.get("contract") != contract:', source)
        # materialize_result is unchanged: the published sidecar is created
        # from the run manifest and validated against this build's digests.
        self.assertIn('lineage_from_run_manifest(\n'
                      '    checkpoint, run_manifest_path, '
                      'allow_eligible_publication=True)', source)


class BridgeLadderTests(unittest.TestCase):
    def test_rung_launcher_and_stage_accept_and_forward_the_bridge(self):
        rung = (ROOT / "tools/launch_ladder_rung.sh").read_text(encoding="utf-8")
        self.assertIn("  bridge)\n    : \"${BRIDGE_WARM_SHA256:?", rung)
        self.assertIn('elif [ "$LADDER_PROFILE" = "bridge" ]; then\n'
                      '  GRAFT_ENV=(BRIDGE_WARM_SHA256="$BRIDGE_WARM_SHA256"', rung)
        self.assertIn('if profile == "bridge":\n', rung)
        self.assertIn('payload["bridge"] = {', rung)
        stage = STAGE.read_text(encoding="utf-8")
        self.assertIn("LADDER_PROFILE=bridge is a first rung", stage)
        self.assertIn("bridge warm has a lineage sidecar", stage)
        self.assertIn('[ "$WARM_ACTUAL_SHA256" = "$BRIDGE_WARM_SHA256" ] || {', stage)
        for knob in BRIDGE:
            self.assertIn(f'[ -z "${{{knob}:-}}" ] || export {knob}', stage)


if __name__ == "__main__":
    unittest.main()
