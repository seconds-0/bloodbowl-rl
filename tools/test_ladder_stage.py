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
                           "POOL_KEEP")
              and not k.startswith(("LADDER_", "SCRIPTED_", "GRAFT_"))}
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

    def test_pool_composition_promotes_warm_and_retires_oldest(self):
        source = STAGE.read_text(encoding="utf-8")
        match = re.search(
            r"mapfile -t SEEDS < <\(python3 - \"\$PREV_POOL\" \"\$WARM\" \"\$POOL_KEEP\" \"\$RUNG\" \"\$POOL_ANCHOR\" <<'PY'\n(.*?)\nPY\n",
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
                ["python3", "-", str(prev), str(warm), "3", "9", ""],
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
                ["python3", "-", str(prev), str(warm), "3", "9", srcs[1]],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            self.assertEqual(out.stdout.strip().splitlines()[0], f"gen1={srcs[1]}")
            # The anchor may not be the warm checkpoint.
            out = subprocess.run(
                ["python3", "-", str(prev), str(warm), "3", "9", str(warm)],
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
                ["python3", "-", str(prev), str(warm), "3", "9", ""],
                input=resolver, text=True, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, check=False)
            self.assertEqual(out.returncode, 0, out.stderr)
            lines = out.stdout.strip().splitlines()
            self.assertEqual(len(lines), 4)
            self.assertEqual(sum(1 for l in lines if l.endswith(str(warm))), 1)
            self.assertTrue(lines[0].startswith("gen1="))  # anchor sticks


if __name__ == "__main__":
    unittest.main()
