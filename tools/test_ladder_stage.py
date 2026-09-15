#!/usr/bin/env python3
"""tools/ladder_stage.sh must resolve its inputs, never invent them.

Exercises the stage script off-box up to the point where it would touch the
installed Puffer tree, asserting on the specific refusal each missing or
inconsistent input produces. The pool-composition rule (newest three banks of
the previous pool plus the previous rung's accepted checkpoint) is exercised by
running the script's embedded resolver against a synthetic previous pool.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STAGE = ROOT / "tools/ladder_stage.sh"


def run(env, cwd=None):
    merged = {k: v for k, v in os.environ.items()
              if k not in ("RUNG", "RESET_PCT", "SEED", "STAMP", "WARM",
                           "PREV_COMPLETE", "PREV_POOL", "PIN", "STEPS",
                           "POOL_KEEP", "NUM_FROZEN_BANKS")
              and not k.startswith(("LADDER_", "SCRIPTED_", "GRAFT_", "BRIDGE_"))}
    merged.update(env)
    return subprocess.run(
        ["bash", str(STAGE)], cwd=cwd or ROOT, env=merged, text=True,
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False,
        timeout=120,
    )


class LadderStageTests(unittest.TestCase):
    def test_refuses_missing_required_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = run({"C": tmp})
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("RUNG is required", out.stdout)

    def test_refuses_an_unaccepted_previous_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "LADDER_RUNG_COMPLETE.json"
            # The July bare-launcher marker shape: no lineage digest.
            marker.write_text(json.dumps({"trainer_exit": 0, "checkpoint": "x"}))
            (Path(tmp) / "tools").mkdir()
            (Path(tmp) / "tools/install_puffer_env.sh").write_text("#!/bin/bash\nexit 0\n")
            out = run({"C": tmp, "RUNG": "9", "RESET_PCT": "0.5", "SEED": "43",
                       "STAMP": "t", "PREV_COMPLETE": str(marker)})
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("previous rung marker is not an accepted screen result", out.stdout)

    def test_refuses_warm_without_lineage_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "tools").mkdir()
            (Path(tmp) / "tools/install_puffer_env.sh").write_text("#!/bin/bash\nexit 0\n")
            warm = Path(tmp) / "warm.bin"
            warm.write_bytes(b"x")
            pool = Path(tmp) / "pool"
            pool.mkdir()
            (pool / "league_seeds.json").write_text("{}")
            out = run({"C": tmp, "RUNG": "6", "RESET_PCT": "0.5", "SEED": "43",
                       "STAMP": "t", "WARM": str(warm), "PREV_POOL": str(pool)})
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("warm has no lineage sidecar", out.stdout)

    BRIDGE = {"LADDER_PROFILE": "bridge",
              "BRIDGE_WARM_OBS_VERSION": "4",
              "BRIDGE_PROVENANCE": "runs/reward-transfer-20260713-v1 ANALYSIS.json",
              "BRIDGE_REASON": "audit-2026-08-20 F2"}

    def _bridge_fixture(self, tmp, with_sidecar=False):
        (Path(tmp) / "tools").mkdir()
        (Path(tmp) / "tools/install_puffer_env.sh").write_text("#!/bin/bash\nexit 0\n")
        warm = Path(tmp) / "r0-s42-native.bin"
        warm.write_bytes(b"july-obs-v4")
        if with_sidecar:
            (Path(tmp) / "r0-s42-native.bin.lineage.json").write_text("{}")
        pool = Path(tmp) / "prev" / "pool"
        pool.mkdir(parents=True)
        (pool / "league_seeds.json").write_text("{}")
        import hashlib
        return warm, pool, hashlib.sha256(warm.read_bytes()).hexdigest()

    def test_bridge_first_rung_takes_a_raw_warm_without_a_sidecar(self):
        # A bridge is the one stage whose warm legitimately has no sidecar:
        # it must get PAST the sidecar check and fail later, on the missing
        # POOL_IDENTITY.env beside the (synthetic) previous pool.
        with tempfile.TemporaryDirectory() as tmp:
            warm, pool, sha = self._bridge_fixture(tmp)
            out = run({"C": tmp, "RUNG": "0", "RESET_PCT": "0", "SEED": "42",
                       "STAMP": "t", "WARM": str(warm), "PREV_POOL": str(pool),
                       **self.BRIDGE, "BRIDGE_WARM_SHA256": sha})
            self.assertNotEqual(out.returncode, 0)
            self.assertNotIn("warm has no lineage sidecar", out.stdout)
            self.assertIn("PREV_POOL has no published POOL_IDENTITY.env", out.stdout)

    def test_bridge_refuses_a_hash_mismatch_a_sidecar_and_a_chained_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            warm, pool, sha = self._bridge_fixture(tmp)
            base = {"C": tmp, "RUNG": "0", "RESET_PCT": "0", "SEED": "42",
                    "STAMP": "t", "WARM": str(warm), "PREV_POOL": str(pool),
                    **self.BRIDGE}
            out = run({**base, "BRIDGE_WARM_SHA256": "0" * 64})
            self.assertNotEqual(out.returncode, 0)
            self.assertIn(f"has sha256 {sha} but BRIDGE_WARM_SHA256 declares",
                          out.stdout)
            marker = Path(tmp) / "LADDER_RUNG_COMPLETE.json"
            marker.write_text(json.dumps({"trainer_exit": 0, "checkpoint": str(warm),
                                          "checkpoint_lineage_sha256": "x"}))
            out = run({**base, "BRIDGE_WARM_SHA256": sha,
                       "PREV_COMPLETE": str(marker)})
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("LADDER_PROFILE=bridge is a first rung", out.stdout)
            for missing in ("BRIDGE_WARM_OBS_VERSION", "BRIDGE_PROVENANCE",
                            "BRIDGE_REASON"):
                env = {**base, "BRIDGE_WARM_SHA256": sha}
                env.pop(missing)
                out = run(env)
                self.assertNotEqual(out.returncode, 0, missing)
                self.assertIn(f"{missing} is required for LADDER_PROFILE=bridge",
                              out.stdout, missing)
        with tempfile.TemporaryDirectory() as tmp:
            warm, pool, sha = self._bridge_fixture(tmp, with_sidecar=True)
            out = run({"C": tmp, "RUNG": "0", "RESET_PCT": "0", "SEED": "42",
                       "STAMP": "t", "WARM": str(warm), "PREV_POOL": str(pool),
                       **self.BRIDGE, "BRIDGE_WARM_SHA256": sha})
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("bridge warm has a lineage sidecar", out.stdout)

    def test_chained_rungs_default_to_the_full_lr_scale(self):
        # Audit F1: 0.1x froze training under Muon. The default is back to 1.0
        # for chained rungs; the knob survives for explicit experiments.
        source = STAGE.read_text(encoding="utf-8")
        self.assertIn('if [ -n "$PREV_COMPLETE" ] && [ -z "${LADDER_CHAIN_LR_SCALE:-}" ]; then\n'
                      '  export LADDER_CHAIN_LR_SCALE=1.0\n', source)
        self.assertNotIn("export LADDER_CHAIN_LR_SCALE=0.1", source)

    def test_pool_composition_promotes_warm_and_retires_oldest(self):
        source = STAGE.read_text(encoding="utf-8")
        match = re.search(
            r"mapfile -t SEEDS < <\(python3 - \"\$PREV_POOL\" \"\$WARM\" \"\$POOL_KEEP\" \"\$RUNG\" \"\$POOL_ANCHOR\" \"\$NUM_FROZEN_BANKS\" <<'PY'\n(.*?)\nPY\n",
            source, re.S)
        self.assertIsNotNone(match, "embedded pool resolver not found")
        resolver = match.group(1)
        with tempfile.TemporaryDirectory() as tmp:
            prev = Path(tmp) / "prevpool"
            prev.mkdir()
            srcs = []
            for i in range(4):
                p = Path(tmp) / f"gen{i}.bin"
                p.write_bytes(b"x")
                srcs.append(str(p))
            (prev / "league_seeds.json").write_text(json.dumps({"seeds": [
                {"bank": i, "name": f"gen{i}", "source": srcs[i]} for i in range(4)]}))
            warm = Path(tmp) / "rung6.bin"
            warm.write_bytes(b"y")
            out = subprocess.run(
                ["python3", "-", str(prev), str(warm), "3", "9", "", "4"],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            lines = out.stdout.strip().splitlines()
            # D244: bank 0 is the weak anchor and never rotates; the oldest
            # NON-anchor bank (gen1) is what retires.
            self.assertEqual(lines, [
                f"gen0={srcs[0]}", f"gen2={srcs[2]}", f"gen3={srcs[3]}",
                f"rung9warm={warm}",
            ])
            # An explicit anchor overrides bank 0 and is labelled as such.
            out = subprocess.run(
                ["python3", "-", str(prev), str(warm), "3", "9", srcs[1], "4"],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.strip().splitlines()[0], f"gen1={srcs[1]}")
            # The anchor may not be the warm checkpoint.
            out = subprocess.run(
                ["python3", "-", str(prev), str(warm), "3", "9", str(warm), "4"],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("cannot also be the warm", out.stderr)
            # Chained restart at the same rung: warm already a bank -> pool
            # stays four banks and does not duplicate the warm.
            (prev / "league_seeds.json").write_text(json.dumps({"seeds": [
                {"bank": 0, "name": "gen1", "source": srcs[1]},
                {"bank": 1, "name": "gen2", "source": srcs[2]},
                {"bank": 2, "name": "gen3", "source": srcs[3]},
                {"bank": 3, "name": "rung9warm", "source": str(warm)}]}))
            out = subprocess.run(
                ["python3", "-", str(prev), str(warm), "3", "9", "", "4"],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            lines = out.stdout.strip().splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(sum(1 for l in lines if l.endswith(str(warm))), 1)
            self.assertTrue(lines[0].startswith("gen1="))  # anchor sticks

    def test_pool_composition_scales_to_eight_banks(self):
        """D282 follow-up: the opponent population is the bank count, and the
        composition rule (weak anchor, newest kept, warm promoted) has to hold
        at 8 banks, the BBE_MAX_BANKS cap, exactly as it does at 4."""
        source = STAGE.read_text(encoding="utf-8")
        match = re.search(
            r"mapfile -t SEEDS < <\(python3 - \"\$PREV_POOL\" \"\$WARM\" \"\$POOL_KEEP\" \"\$RUNG\" \"\$POOL_ANCHOR\" \"\$NUM_FROZEN_BANKS\" <<'PY'\n(.*?)\nPY\n",
            source, re.S)
        self.assertIsNotNone(match, "embedded pool resolver not found")
        resolver = match.group(1)
        with tempfile.TemporaryDirectory() as tmp:
            prev = Path(tmp) / "prevpool"
            prev.mkdir()
            srcs = []
            for i in range(8):
                q = Path(tmp) / f"gen{i}.bin"
                q.write_bytes(b"x")
                srcs.append(str(q))
            (prev / "league_seeds.json").write_text(json.dumps({"seeds": [
                {"bank": i, "name": f"gen{i}", "source": srcs[i]}
                for i in range(8)]}))
            warm = Path(tmp) / "chain20.bin"
            warm.write_bytes(b"y")
            # POOL_KEEP = banks - 1: anchor + 6 newest kept + warm = 8.
            out = subprocess.run(
                ["python3", "-", str(prev), str(warm), "7", "20", "", "8"],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            lines = out.stdout.strip().splitlines()
            self.assertEqual(len(lines), 8)
            # Anchor sticks at bank 0, the oldest non-anchor (gen1) retires,
            # and the warm enters as the newest bank.
            self.assertEqual(lines[0], f"gen0={srcs[0]}")
            self.assertEqual(lines[-1], f"rung20warm={warm}")
            self.assertNotIn(f"gen1={srcs[1]}", lines)
            # A pool too small to reach the requested width fails loudly
            # rather than silently training against fewer opponents than
            # declared. Widening from the current 4-bank pool needs a one-time
            # 8-seed build; rotation alone cannot get there.
            narrow = Path(tmp) / "narrowpool"
            narrow.mkdir()
            (narrow / "league_seeds.json").write_text(json.dumps({"seeds": [
                {"bank": i, "name": f"gen{i}", "source": srcs[i]}
                for i in range(4)]}))
            out = subprocess.run(
                ["python3", "-", str(narrow), str(warm), "7", "20", "", "8"],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertNotEqual(out.returncode, 0)
            self.assertIn("could not compose exactly 8 banks", out.stderr)

    def test_bank_count_is_validated_against_the_engine_cap(self):
        source = STAGE.read_text(encoding="utf-8")
        self.assertIn('NUM_FROZEN_BANKS="${NUM_FROZEN_BANKS:-4}"', source)
        self.assertIn('POOL_KEEP="${POOL_KEEP:-$((NUM_FROZEN_BANKS - 1))}"', source)
        with tempfile.TemporaryDirectory() as tmp:
            for bad in ("0", "9", "abc"):
                result = run({"C": tmp, "RUNG": "0", "RESET_PCT": "0",
                              "SEED": "42", "STAMP": "t",
                              "NUM_FROZEN_BANKS": bad})
                self.assertNotEqual(result.returncode, 0, bad)
                self.assertIn("NUM_FROZEN_BANKS must be an integer in 1..8",
                              result.stdout, bad)

    def test_horizon_knobs_are_validated_before_a_pool_is_built_and_exported(self):
        source = STAGE.read_text(encoding="utf-8")
        for knob in ("LADDER_GAMMA", "LADDER_GAE_LAMBDA"):
            self.assertIn(f'[ -z "${{{knob}:-}}" ] || export {knob}', source)
        base = {"RUNG": "0", "RESET_PCT": "0", "SEED": "42", "STAMP": "t"}
        with tempfile.TemporaryDirectory() as tmp:
            for knob in ("LADDER_GAMMA", "LADDER_GAE_LAMBDA"):
                for bad in ("1", "0", "0.000", ".99", "0.99x", "nan", "0.9999999"):
                    result = run({"C": tmp, **base, knob: bad})
                    self.assertNotEqual(result.returncode, 0, (knob, bad))
                    self.assertIn(
                        f"{knob} must be a decimal in (0,1) with at most six decimals",
                        result.stdout, (knob, bad))
                    self.assertNotIn("drift check failed", result.stdout, (knob, bad))
            # A declared horizon clears the gate and stops later, at the drift
            # check this synthetic checkout cannot pass.
            result = run({"C": tmp, **base, "LADDER_GAMMA": "0.999",
                          "LADDER_GAE_LAMBDA": "0.95"})
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("must be a decimal in (0,1)", result.stdout)
            self.assertIn("drift check failed", result.stdout)

    def test_replay_ratio_is_validated_before_a_pool_is_built_and_exported(self):
        from tools.test_ladder_knobs import (BAD_REPLAY_RATIO_VALUES,
                                             GOOD_REPLAY_RATIO_VALUES,
                                             TRUNCATING_REPLAY_RATIO_VALUES)
        source = STAGE.read_text(encoding="utf-8")
        self.assertIn('[ -z "${LADDER_REPLAY_RATIO:-}" ] || export LADDER_REPLAY_RATIO',
                      source)
        base = {"RUNG": "0", "RESET_PCT": "0", "SEED": "42", "STAMP": "t"}
        with tempfile.TemporaryDirectory() as tmp:
            for bad in BAD_REPLAY_RATIO_VALUES:
                result = run({"C": tmp, **base, "LADDER_REPLAY_RATIO": bad})
                self.assertNotEqual(result.returncode, 0, bad)
                self.assertIn("LADDER_REPLAY_RATIO must be a decimal in (0,4] with "
                              "at most three decimals", result.stdout, bad)
                self.assertNotIn("drift check failed", result.stdout, bad)
            for bad in TRUNCATING_REPLAY_RATIO_VALUES:
                result = run({"C": tmp, **base, "LADDER_REPLAY_RATIO": bad})
                self.assertNotEqual(result.returncode, 0, bad)
                self.assertIn(f"LADDER_REPLAY_RATIO={bad} does not give a whole "
                              f"number of minibatches per epoch ({bad} x 131072 / "
                              "16384)", result.stdout, bad)
                self.assertNotIn("drift check failed", result.stdout, bad)
            # An exact ratio clears the gate and stops later, at the drift check
            # this synthetic checkout cannot pass.
            for good, _ in GOOD_REPLAY_RATIO_VALUES:
                result = run({"C": tmp, **base, "LADDER_REPLAY_RATIO": good})
                self.assertNotEqual(result.returncode, 0, good)
                self.assertNotIn("LADDER_REPLAY_RATIO", result.stdout, good)
                self.assertIn("drift check failed", result.stdout, good)

    def test_stage_batch_contract_matches_the_screen(self):
        # The stage counts gradient steps against the screen's fixed batch and
        # minibatch; a contract change there must fail here, not mislabel.
        def assigned(text, name):
            match = re.search(rf"^{name}=([0-9]+)$", text, re.MULTILINE)
            self.assertIsNotNone(match, name)
            return int(match.group(1))
        stage = STAGE.read_text(encoding="utf-8")
        screen = (ROOT / "tools/run_reward_screen.sh").read_text(encoding="utf-8")
        self.assertEqual(assigned(stage, "SCREEN_BATCH"),
                         assigned(screen, "TOTAL_AGENTS") * assigned(screen, "HORIZON"))
        self.assertEqual(assigned(stage, "SCREEN_MINIBATCH"),
                         assigned(screen, "MINIBATCH_SIZE"))

    def test_stage_banner_names_the_gradient_steps_per_epoch(self):
        from tools.test_ladder_knobs import GOOD_REPLAY_RATIO_VALUES
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "tools").mkdir()
            (root / "tools/install_puffer_env.sh").write_text("#!/bin/bash\nexit 0\n")
            # The stage execs the rung launcher last; this stub reports what
            # the stage exported to it.
            (root / "tools/launch_ladder_rung.sh").write_text(
                "#!/bin/bash\n"
                "printf 'rung launcher saw LADDER_REPLAY_RATIO=%s\\n' "
                "\"${LADDER_REPLAY_RATIO-unset}\"\n")
            warm = root / "warm.bin"
            warm.write_bytes(b"w")
            (root / "warm.bin.lineage.json").write_text("{}")
            pool = root / "prev" / "pool"
            pool.mkdir(parents=True)
            (pool / "league_seeds.json").write_text("{}")
            (root / "prev/POOL_IDENTITY.env").write_text(
                "EXPECTED_POOL_HASH=" + "d" * 64 + "\n")
            base = {"C": tmp, "RUNG": "0", "RESET_PCT": "0", "SEED": "42",
                    "WARM": str(warm), "PREV_POOL": str(pool)}
            for value, steps in GOOD_REPLAY_RATIO_VALUES:
                result = run({**base, "STAMP": f"rr-{value}",
                              "LADDER_REPLAY_RATIO": value})
                self.assertEqual(result.returncode, 0, result.stdout)
                self.assertIn(f"  update replay_ratio={value} "
                              f"gradient_steps_per_epoch={steps} "
                              "(batch 131072 / minibatch 16384)\n",
                              result.stdout, value)
                self.assertIn(f"rung launcher saw LADDER_REPLAY_RATIO={value}\n",
                              result.stdout, value)
            result = run({**base, "STAMP": "plain"})
            self.assertEqual(result.returncode, 0, result.stdout)
            self.assertNotIn("update replay_ratio", result.stdout)
            self.assertIn("rung launcher saw LADDER_REPLAY_RATIO=unset\n", result.stdout)


if __name__ == "__main__":
    unittest.main()
