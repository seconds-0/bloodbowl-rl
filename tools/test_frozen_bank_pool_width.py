#!/usr/bin/env python3
"""Both pool validators must size the pool to NUM_FROZEN_BANKS.

PR #95 made the bank count settable (ladder_stage.sh builds an 8-bank pool,
run_reward_ablation.sh passes --vec.num-frozen-banks 8), but two embedded
validators still hardcoded four: the screen plan writer ("screen pool must
contain exactly four banks") and the per-arm launcher's pool-body check
("static reward pool must contain exactly four seeds"). An 8-bank rung built
by ladder_stage.sh therefore failed at the screen plan step, before any
training. These tests run the real embedded Python blocks against 8-bank and
4-bank pools and assert on specific messages, never on exit status alone. The
launcher's third 4-bank gate, the SCRIPTED_BANK_TAG range that refused chain
23's tag 8, is covered end to end in tools/test_ladder_knobs.py.
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import subprocess
import sysconfig
import tempfile
import unittest

from tools.test_graft_profile import mint_lineage

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCREEN = ROOT / "tools/run_reward_screen.sh"
LAUNCHER = ROOT / "tools/run_reward_ablation.sh"


def launcher_pool_block():
    source = LAUNCHER.read_text(encoding="utf-8")
    match = re.search(
        r'read -r POOL_HASH POOL_BANKS POOL_MANIFEST_HASH < <\(\n'
        r'    "\$PYBIN" - "\$POOL" "\$EXPECT_BYTES"(?: "\$NUM_FROZEN_BANKS")? '
        r"<<'PY'\n(.*?)\nPY\n", source, re.S)
    assert match, "launcher pool-body heredoc not found"
    return match.group(1)


def screen_plan_block():
    source = SCREEN.read_text(encoding="utf-8")
    match = re.search(
        r'"\$PYBIN" - "\$SCREEN_MANIFEST" <<\'PY\'\n(.*?)\nPY\n\)"',
        source, re.S)
    assert match, "screen plan-writer heredoc not found"
    return match.group(1)


def identity_hash(seeds):
    # tools/build_league.py's EXPECTED_POOL_HASH definition.
    identity = [{"bank": s["bank"], "name": s["name"], "bytes": s["bytes"],
                 "sha256": s["sha256"]} for s in seeds]
    return hashlib.sha256(json.dumps(
        identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class LauncherPoolWidthTests(unittest.TestCase):
    EXPECT = 64

    @classmethod
    def setUpClass(cls):
        cls.block = launcher_pool_block()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def pool(self, banks):
        pool = self.root / f"pool{banks}"
        pool.mkdir()
        seeds = []
        for bank in range(banks):
            blob = f"bank{bank}".encode().ljust(self.EXPECT, b"\0")
            (pool / f"{bank:016d}.bin").write_bytes(blob)
            (pool / f"{bank:016d}.bin.lineage.json").write_text("{}\n")
            seeds.append({
                "bank": bank, "name": f"seat{bank}", "file": f"{bank:016d}.bin",
                "bytes": len(blob), "sha256": hashlib.sha256(blob).hexdigest(),
                "lineage_file": f"{bank:016d}.bin.lineage.json",
                "lineage_sha256": "7" * 64,
            })
        (pool / "league_seeds.json").write_text(json.dumps(
            {"version": 2, "expected_bytes": self.EXPECT, "seeds": seeds}))
        return pool, seeds

    def validate(self, pool, banks):
        return subprocess.run(
            ["python3", "-", str(pool), str(self.EXPECT), str(banks)],
            input=self.block, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=120)

    def test_eight_bank_pool_passes_at_eight_banks(self):
        pool, seeds = self.pool(8)
        out = self.validate(pool, 8)
        self.assertEqual(out.returncode, 0, out.stderr)
        pool_hash, count, _ = out.stdout.split()
        self.assertEqual(count, "8")
        self.assertEqual(pool_hash, identity_hash(seeds))

    def test_four_bank_pool_still_passes_at_four_banks(self):
        pool, seeds = self.pool(4)
        out = self.validate(pool, 4)
        self.assertEqual(out.returncode, 0, out.stderr)
        pool_hash, count, _ = out.stdout.split()
        self.assertEqual(count, "4")
        self.assertEqual(pool_hash, identity_hash(seeds))

    def test_pool_width_must_equal_the_declared_bank_count(self):
        pool, _ = self.pool(8)
        out = self.validate(pool, 4)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn(
            "static reward pool must contain exactly NUM_FROZEN_BANKS=4 seeds, "
            "got 8", out.stderr)
        pool, _ = self.pool(4)
        out = self.validate(pool, 8)
        self.assertNotEqual(out.returncode, 0)
        self.assertIn(
            "static reward pool must contain exactly NUM_FROZEN_BANKS=8 seeds, "
            "got 4", out.stderr)

    def test_launcher_passes_the_bank_count_to_the_pool_check(self):
        source = LAUNCHER.read_text(encoding="utf-8")
        self.assertIn(
            '"$PYBIN" - "$POOL" "$EXPECT_BYTES" "$NUM_FROZEN_BANKS" <<\'PY\'',
            source)
        self.assertNotIn("must contain exactly four seeds", source)


class ScreenPlanPoolWidthTests(unittest.TestCase):
    """Run the real screen plan writer on a stand-in build tree.

    The stand-in build is a vendor tree whose pufferlib package exposes a fake
    `_C` carrying this build's contract, so the plan writer's module probe, warm
    lineage binding and pool check all execute on real sidecars."""

    SOURCE = "1" * 64

    @classmethod
    def setUpClass(cls):
        cls.block = screen_plan_block()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name).resolve() / "checkout"
        root = self.root
        root.mkdir()
        for name in ("tools", "puffer", "training"):
            (root / name).symlink_to(ROOT / name)
        vendor = root / "vendor/PufferLib"
        (vendor / "ocean/bloodbowl").mkdir(parents=True)
        (vendor / "ocean/bloodbowl/.content_hash").write_text(self.SOURCE + "\n")
        (vendor / "pufferlib").mkdir()
        (vendor / "src").mkdir()
        module = vendor / "pufferlib" / ("_C" + sysconfig.get_config_var("EXT_SUFFIX"))
        module.write_bytes(b"stand-in compiled module\n")
        (vendor / "pufferlib/__init__.py").write_text(
            "import types\n"
            "_C = types.ModuleType('_C')\n"
            f"_C.__file__ = {str(module)!r}\n"
            "_C.env_name = 'bloodbowl'\n"
            "_C.gpu = True\n"
            "_C.precision_bytes = 4\n"
            f"_C.exact_action_source_hash = {'8' * 64!r}\n"
            f"_C.environment_source_hash = {self.SOURCE!r}\n"
            "_C.observation_abi = 'obs-v6'\n"
            "_C.observation_version = 6\n"
            "_C.action_abi = 'exact-joint-v1'\n",
            encoding="utf-8")
        for relative in ("pufferlib/pufferl.py", "pufferlib/selfplay.py",
                         "pufferlib/torch_pufferl.py", "pufferlib/models.py",
                         "pufferlib/muon.py", "src/pufferlib.cu",
                         "src/bindings.cu", "src/bindings_cpu.cpp",
                         "src/kernels.cu", "src/vecenv.h"):
            (vendor / relative).write_text("# stand-in\n")
        self.module_sha = hashlib.sha256(module.read_bytes()).hexdigest()
        patches = re.search(r"\npatches = \[\n(.*?)\n\]\n", self.block, re.S)
        assert patches, "plan-writer patch list not found"
        paths = [root / rel for rel in
                 re.findall(r'root / "(training/[^"]+\.patch)"', patches.group(1))]
        self.patch_sha = hashlib.sha256(b"".join(
            f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p}\n".encode()
            for p in paths)).hexdigest()
        self.warm = root / "warm.bin"
        mint_lineage(root, self.warm, source=self.SOURCE, module=self.module_sha,
                     patch=self.patch_sha)

    def tearDown(self):
        self.temp.cleanup()

    def pool(self, banks):
        pool = self.root / f"pool{banks}"
        pool.mkdir()
        seeds = [{"bank": bank, "name": f"seat{bank}",
                  "file": f"{bank:016d}.bin", "bytes": 16066560,
                  "sha256": f"{bank + 10:064x}",
                  "lineage_file": f"{bank:016d}.bin.lineage.json",
                  "lineage_sha256": f"{bank + 100:064x}"}
                 for bank in range(banks)]
        (pool / "league_seeds.json").write_text(json.dumps({"seeds": seeds}))
        return pool, seeds

    def plan(self, pool, seeds, banks, tag):
        out_dir = self.root / "screen"
        out_dir.mkdir(exist_ok=True)
        destination = out_dir / f"SCREEN_MANIFEST-{banks}-{len(seeds)}.json"
        env = {k: v for k, v in os.environ.items()
               if not k.startswith(("LADDER_", "SCRIPTED_", "GRAFT_", "BRIDGE_"))}
        env.update({
            "ROOT": str(self.root), "PREFIX": "pool-width-test",
            "STEPS": "3000000000", "OUT_DIR": str(out_dir),
            "SCREEN_PROFILE": "ladder-rung", "BOOTSTRAP_MODE": "lineage-v6",
            "CANDIDATE_ARM": "", "TRANSFER_COMPLETE": "",
            "EXPECTED_TRANSFER_SHA256": "",
            "WARM": str(self.warm), "POOL": str(pool),
            "EXPECTED_POOL_HASH": identity_hash(seeds),
            "SCHEDULE": "r0_poss_half:42:"
                        + str(ROOT / "puffer/config/rewards/r0_poss_half.json"),
            "POLL_SECONDS": "30", "MAX_PANEL_SILENCE_SECONDS": "180",
            "TOTAL_AGENTS": "2048", "HORIZON": "64", "MINIBATCH_SIZE": "16384",
            "EXPECT_BYTES": "16066560", "FROZEN_BANK_PCT": "0.06",
            "NUM_FROZEN_BANKS": str(banks),
            "MIN_TRAIN_GAMES": "1", "MIN_EVAL_GAMES": "10000",
            "LADDER_ENDZONE_MAXDIST": "0", "LADDER_RESET_PCT": "0",
            "SCRIPTED_BANK_TAG": tag, "SCRIPTED_BOT_TYPE": "0",
            "GRAFT_FROM_SOURCE_SHA256": "", "GRAFT_FROM_PATCH_BUNDLE_SHA256": "",
            "GRAFT_REASON": "", "BRIDGE_WARM_SHA256": "",
            "BRIDGE_WARM_OBS_VERSION": "", "BRIDGE_PROVENANCE": "",
            "BRIDGE_REASON": "",
            "LADDER_CHAIN_LR_SCALE": "1.0", "LADDER_CHAIN_ENT_SCALE": "1",
            "LADDER_ARM": "r0_poss_half", "LR": "0.00028", "ENT_COEF": "0.009",
        })
        result = subprocess.run(
            ["python3", "-", str(destination)], input=self.block, env=env,
            cwd=self.root, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False, timeout=300)
        return result, destination

    def test_eight_bank_rung_plan_is_written(self):
        pool, seeds = self.pool(8)
        out, destination = self.plan(pool, seeds, 8, "8")
        self.assertEqual(out.returncode, 0, out.stderr)
        self.assertNotIn("exactly four banks", out.stderr)
        contract = json.loads(destination.read_text())["contract"]
        self.assertEqual(contract["settings"]["num_frozen_banks"], "8")
        self.assertEqual(contract["ladder"]["scripted_bank_tag"], 8)
        self.assertEqual(contract["pool"]["identity_sha256"], identity_hash(seeds))
        bundle = hashlib.sha256(json.dumps([
            {"bank": s["bank"], "checkpoint_sha256": s["sha256"],
             "lineage_sha256": s["lineage_sha256"]} for s in seeds
        ], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertEqual(contract["pool"]["lineage_bundle_sha256"], bundle)
        self.assertEqual(contract["bootstrap"]["pool_lineage_bundle_sha256"], bundle)

    def test_four_bank_rung_plan_is_still_written(self):
        pool, seeds = self.pool(4)
        out, destination = self.plan(pool, seeds, 4, "4")
        self.assertEqual(out.returncode, 0, out.stderr)
        contract = json.loads(destination.read_text())["contract"]
        self.assertEqual(contract["settings"]["num_frozen_banks"], "4")

    def test_plan_refuses_a_pool_whose_width_differs_from_the_bank_count(self):
        pool, seeds = self.pool(8)
        out, destination = self.plan(pool, seeds, 4, "4")
        self.assertNotEqual(out.returncode, 0)
        self.assertIn(
            "screen pool must contain exactly NUM_FROZEN_BANKS=4 banks, got 8",
            out.stderr)
        self.assertFalse(destination.exists())


if __name__ == "__main__":
    unittest.main()
