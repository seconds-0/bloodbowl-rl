#!/usr/bin/env python3
"""tools/chain_exam_verdict.py must register a verdict only from whole evidence.

The verdict gates an unattended chain, so each test asserts both the exit
status and which files exist afterwards. The synthetic cell logs have the
shape of a native scripted-bot eval log (manifest line, interval train panels,
cumulative eval panels, one final reprint), and the numbers are read back with
the same two functions the as-run readout uses.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/chain_exam_verdict.py"
sys.path.insert(0, str(ROOT / "tools"))

from contact_bot_stats import bot_perspective  # noqa: E402
from game_stats import weighted_dashboard  # noqa: E402

CELLS = (("contact_away", 0, 1), ("contact_home", 0, 0), ("offense_away", 1, 1))
CKPT_SHA = "ab" * 32
# Chain 30's registered reference floors (D405), as the caller passes them.
FLOORS = ("--guard-floor-s42", "0.541", "--guard-floor-s43", "0.551",
          "--guard-floor-mean", "0.546")


def write_cell_log(path, *, seed, bot_type, bot_team, champion_tds,
                   bot_tds=0.345, games=2010, checkpoint_sha=CKPT_SHA,
                   threads=16):
    """Write a log that game_stats reads the way it reads a real exam cell."""
    champion = 1 - bot_team
    manifest = {
        "schema_version": 1, "mode": "scripted_bot_frozen",
        "checkpoint": "/ckpt/final.bin", "checkpoint_sha256": checkpoint_sha,
        "seed": seed, "bot_type": bot_type, "bot_team": bot_team,
        "eval_episodes": 2000, "min_eval_games": 2000,
        "command": ["puffer", "train", "bloodbowl", "--seed", str(seed),
                    "--vec.num-threads", str(threads)],
    }

    def panel(n, phase_eval, cumulative, final, scale=1.0):
        payload = {
            "_puffer_schema": 2, "_puffer_phase_eval": phase_eval,
            "_puffer_env_cumulative": cumulative,
            "_puffer_final_reprint": final,
            "n": float(n),
            f"tds_t{champion}": champion_tds * scale,
            f"tds_t{bot_team}": bot_tds * scale,
            f"slot_{champion}_score": 0.6, f"slot_{bot_team}_score": 0.4,
            f"blocks_thrown_t{champion}": 7.0,
            f"blocks_thrown_t{bot_team}": 14.0,
            "draw_rate": 0.43,
        }
        return "PufferLib 4.0\nPUFFER_ENV_JSON " + json.dumps(payload) + "\n"

    text = "BB_EVAL_MANIFEST " + json.dumps(manifest, sort_keys=True) + "\n"
    # Train-phase interval panels must not leak into the eval aggregate.
    text += panel(64, 0, 0, 0, scale=3.0)
    text += panel(73, 0, 0, 0, scale=3.0)
    # Cumulative eval snapshots: only the last one counts.
    text += panel(games // 2, 1, 1, 0, scale=0.5)
    text += panel(games, 1, 1, 0)
    text += panel(games, 1, 1, 1)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


def write_exam(exam_dir, offense=None, seeds=(42, 43), **overrides):
    """Six cells; `offense` maps seed -> offense AWAY champion touchdowns."""
    offense = offense or {}
    for seed in seeds:
        for name, bot_type, bot_team in CELLS:
            tds = offense.get(seed, 0.56) if name == "offense_away" else 0.57
            write_cell_log(Path(exam_dir) / f"s{seed}" / f"{name}.log",
                           seed=seed, bot_type=bot_type, bot_team=bot_team,
                           champion_tds=tds, **overrides)


class ChainExamVerdictTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.exam = self.root / "exam-attempt1"
        self.out = self.root / "run"
        self.out.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def run_tool(self, *extra, seeds=("42", "43")):
        return subprocess.run(
            [sys.executable, str(TOOL), "--exam-dir", str(self.exam),
             "--seeds", *seeds, "--output-dir", str(self.out), *extra],
            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            check=False, timeout=60)

    def files(self):
        return sorted(path.name for path in self.out.iterdir())

    def verdict(self):
        return json.loads((self.out / "EXAM_VERDICT.json").read_text())

    def assert_no_verdict(self, result, message):
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("NO VERDICT", result.stderr)
        self.assertIn(message, result.stderr)
        self.assertEqual(self.files(), [])

    def test_rule_none_passes_on_six_valid_cells_and_records_the_readout(self):
        write_exam(self.exam, offense={42: 0.10, 43: 0.10})
        result = self.run_tool("--rule", "none")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.files(),
                         ["EXAM_VERDICT.json", "EXAM_VERDICT_PASS.json"])
        verdict = self.verdict()
        self.assertEqual(
            verdict, json.loads((self.out / "EXAM_VERDICT_PASS.json").read_text()))
        self.assertTrue(verdict["pass"])
        self.assertEqual(verdict["rule"], "none")
        self.assertIsNone(verdict["guard"])
        self.assertEqual(verdict["checkpoint_sha256"], CKPT_SHA)
        self.assertEqual(
            [(cell["seed"], cell["cell"]) for cell in verdict["cells"]],
            [(seed, name) for seed in (42, 43) for name, _, _ in CELLS])
        for cell in verdict["cells"]:
            # The same two functions the as-run readout prints from.
            view = bot_perspective(weighted_dashboard(cell["log"]),
                                   cell["bot_team"])
            self.assertEqual(cell["champion_tds"], view["champion_tds"])
            self.assertEqual(cell["bot_tds"], view["bot_tds"])
            self.assertEqual(cell["champion_score"], view["champion_score"])
            self.assertEqual(cell["bot_score"], view["bot_score"])
            self.assertEqual(cell["games"], 2010)
            self.assertEqual(cell["num_threads"], 16)
            self.assertEqual(cell["champion_team"], 1 - cell["bot_team"])
        home = verdict["cells"][1]
        self.assertEqual((home["cell"], home["champion_team"]),
                         ("contact_home", 1))
        self.assertAlmostEqual(verdict["cells"][2]["champion_tds"], 0.10)
        self.assertAlmostEqual(verdict["cells"][2]["bot_tds"], 0.345)

    def guard(self, offense, *floors):
        write_exam(self.exam, offense=offense)
        return self.run_tool("--rule", "drift-guard", *(floors or FLOORS))

    def assert_guard_passes(self, result, clauses):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.files(),
                         ["EXAM_VERDICT.json", "EXAM_VERDICT_PASS.json"])
        guard = self.verdict()["guard"]
        self.assertFalse(guard["fired"])
        self.assertEqual(guard["clauses"], clauses)

    def test_drift_guard_passes_when_only_seed_42_holds_its_floor(self):
        # Seed 43 and the mean (0.5255) are below; seed 42 is not.
        self.assert_guard_passes(
            self.guard({42: 0.541, 43: 0.510}),
            {"s42_below_floor": False, "s43_below_floor": True,
             "mean_below_floor": True})

    def test_drift_guard_passes_when_only_seed_43_holds_its_floor(self):
        # Seed 42 and the mean (0.5255) are below; seed 43 is not.
        self.assert_guard_passes(
            self.guard({42: 0.500, 43: 0.551}),
            {"s42_below_floor": True, "s43_below_floor": False,
             "mean_below_floor": True})

    def test_drift_guard_passes_when_only_the_mean_holds_its_floor(self):
        # Both seeds are below their floors; the mean floor is lower.
        self.assert_guard_passes(
            self.guard({42: 0.550, 43: 0.550},
                       "--guard-floor-s42", "0.60", "--guard-floor-s43", "0.60",
                       "--guard-floor-mean", "0.50"),
            {"s42_below_floor": True, "s43_below_floor": True,
             "mean_below_floor": False})

    def test_drift_guard_passes_on_the_chain_36_readout(self):
        result = self.guard({42: 0.5537313222885132, 43: 0.5658025741577148})
        self.assert_guard_passes(
            result, {"s42_below_floor": False, "s43_below_floor": False,
                     "mean_below_floor": False})
        self.assertAlmostEqual(self.verdict()["guard"]["mean"], 0.5597669, 6)

    def test_drift_guard_fails_only_when_all_three_clauses_hold(self):
        result = self.guard({42: 0.540, 43: 0.550})
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        # A failed rule is a registered verdict without the success artifact.
        self.assertEqual(self.files(), ["EXAM_VERDICT.json"])
        verdict = self.verdict()
        self.assertFalse(verdict["pass"])
        self.assertTrue(verdict["guard"]["fired"])
        self.assertEqual(set(verdict["guard"]["clauses"].values()), {True})
        self.assertEqual(verdict["guard"]["floors"],
                         {"s42": 0.541, "s43": 0.551, "mean": 0.546})
        self.assertIn("FAIL", result.stdout)

    def test_guard_reads_only_the_guard_cell(self):
        # Contact cells far below every floor do not fire an offense guard.
        write_exam(self.exam)
        for seed in (42, 43):
            for name, bot_type, bot_team in CELLS[:2]:
                write_cell_log(self.exam / f"s{seed}" / f"{name}.log",
                               seed=seed, bot_type=bot_type, bot_team=bot_team,
                               champion_tds=0.01)
        result = self.run_tool("--rule", "drift-guard", *FLOORS)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_missing_cell_writes_no_verdict_file(self):
        write_exam(self.exam)
        (self.exam / "s43" / "contact_home.log").unlink()
        for rule in (("--rule", "none"), ("--rule", "drift-guard", *FLOORS)):
            self.assert_no_verdict(self.run_tool(*rule), "missing cell log")

    def test_malformed_or_mismatched_evidence_writes_no_verdict_file(self):
        write_exam(self.exam)
        target = self.exam / "s42" / "offense_away.log"
        good = target.read_text(encoding="utf-8")

        # A log with a manifest but no eval panels (a cell that died early).
        target.write_text(good.splitlines()[0] + "\n", encoding="utf-8")
        self.assert_no_verdict(self.run_tool("--rule", "none"),
                               "no completed-episode eval windows")
        # No manifest line at all.
        target.write_text("\n".join(good.splitlines()[1:]) + "\n",
                          encoding="utf-8")
        self.assert_no_verdict(self.run_tool("--rule", "none"),
                               "first line is not a BB_EVAL_MANIFEST")
        # The seed 43 log copied into the seed 42 slot.
        target.write_text(
            (self.exam / "s43" / "offense_away.log").read_text(), encoding="utf-8")
        self.assert_no_verdict(self.run_tool("--rule", "none"),
                               "manifest seed=43, this cell needs 42")
        # The contact cell's log in the offense slot.
        target.write_text(
            (self.exam / "s42" / "contact_away.log").read_text(), encoding="utf-8")
        self.assert_no_verdict(self.run_tool("--rule", "none"),
                               "manifest bot_type=0, this cell needs 1")
        # One cell examined a different checkpoint.
        write_cell_log(target, seed=42, bot_type=1, bot_team=1,
                       champion_tds=0.56, checkpoint_sha="cd" * 32)
        self.assert_no_verdict(self.run_tool("--rule", "none"),
                               "cells examined different checkpoints")
        # Too few completed games.
        write_cell_log(target, seed=42, bot_type=1, bot_team=1,
                       champion_tds=0.56, games=1999)
        self.assert_no_verdict(self.run_tool("--rule", "none"),
                               "fewer than 2000")
        # A dashboard without the per-team touchdown split.
        target.write_text(good.replace("tds_t0", "tdz_t0"), encoding="utf-8")
        self.assert_no_verdict(self.run_tool("--rule", "none"),
                               "dashboard is missing 'tds_t0'")

    def test_stage_checkpoint_must_match_the_cells(self):
        write_exam(self.exam)
        self.assert_no_verdict(
            self.run_tool("--rule", "none", "--checkpoint-sha256", "ef" * 32),
            "the stage expected")
        result = self.run_tool("--rule", "none", "--checkpoint-sha256", CKPT_SHA)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_drift_guard_needs_all_floors_and_both_guard_seeds(self):
        write_exam(self.exam)
        self.assert_no_verdict(
            self.run_tool("--rule", "drift-guard", *FLOORS[:4]),
            "needs a finite --guard-floor-mean")
        self.assert_no_verdict(
            self.run_tool("--rule", "drift-guard", "--guard-floor-s42", "nan",
                          *FLOORS[2:]),
            "needs a finite --guard-floor-s42")
        self.assert_no_verdict(
            self.run_tool("--rule", "drift-guard", *FLOORS, seeds=("42",)),
            "the exam seeds must include 42 and 43")

    def test_a_registered_verdict_is_never_overwritten(self):
        write_exam(self.exam, offense={42: 0.540, 43: 0.550})
        first = self.run_tool("--rule", "drift-guard", *FLOORS)
        self.assertEqual(first.returncode, 3)
        before = (self.out / "EXAM_VERDICT.json").read_bytes()
        # A later call under a rule that would pass must not replace it.
        second = self.run_tool("--rule", "none")
        self.assertEqual(second.returncode, 2)
        self.assertIn("already registered and is final", second.stderr)
        self.assertEqual(self.files(), ["EXAM_VERDICT.json"])
        self.assertEqual((self.out / "EXAM_VERDICT.json").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
