import json, tempfile, unittest
from pathlib import Path
from unittest.mock import Mock

from tools.freeze_opponent_composition import FreezeError, freeze


class FreezeOpponentCompositionTests(unittest.TestCase):
    def inputs(self, root):
        vals = []
        for i in range(6):
            p = root / f"p{i}.bin"
            p.write_bytes(bytes([i + 1]))
            Path(str(p) + ".lineage.json").write_text("{}")
            vals.append((f"p{i}", str(p)))
        return vals[:3], vals[3:]

    @staticmethod
    def builder(out, seeds, expect_bytes):
        pool = Path(out) / "pool"; pool.mkdir(parents=True)
        data = {"seeds": [{"name": n, "source": p} for n, p in seeds]}
        (pool / "league_seeds.json").write_text(json.dumps(data))
        return data

    def test_exact_seat_order_and_row_contract(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); shared, candidates = self.inputs(root)
            out = root / "frozen"
            plan = freeze(out, shared, candidates, builder=self.builder)
            self.assertEqual(plan["control_seats"], [
                "script-placeholder-a", "script-placeholder-b",
                "p0-copy-a", "p0-copy-b", "p1-copy-a", "p1-copy-b",
                "p2-copy-a", "p2-copy-b"])
            self.assertEqual(plan["candidate_seats"], [
                "script-placeholder-a", "script-placeholder-b",
                "p0", "p1", "p2", "p3", "p4", "p5"])
            self.assertEqual((plan["scripted_rows"], plan["learned_history_rows"],
                              plan["learner_rows"], plan["learner_mirror_rows"]),
                             (122, 366, 536, 48))
            self.assertEqual(plan["initial_screen_steps"], 100_000_000)

    def test_requires_sidecars_distinct_hashes_and_six_inputs(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); shared, candidates = self.inputs(root)
            with self.assertRaisesRegex(FreezeError, "exactly three"):
                freeze(root / "a", shared[:2], candidates, builder=self.builder)
            Path(candidates[0][1]).write_bytes(Path(shared[0][1]).read_bytes())
            with self.assertRaisesRegex(FreezeError, "distinct checkpoint hashes"):
                freeze(root / "b", shared, candidates, builder=self.builder)

    def test_failure_is_atomic_and_existing_output_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); shared, candidates = self.inputs(root)
            bad = Mock(side_effect=RuntimeError("copy failed"))
            with self.assertRaisesRegex(RuntimeError, "copy failed"):
                freeze(root / "out", shared, candidates, builder=bad)
            self.assertFalse((root / "out").exists())
            (root / "out").mkdir()
            with self.assertRaisesRegex(FreezeError, "already exists"):
                freeze(root / "out", shared, candidates, builder=self.builder)


if __name__ == "__main__": unittest.main()
