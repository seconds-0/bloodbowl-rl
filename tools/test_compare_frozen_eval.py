import copy
import json
from pathlib import Path
import tempfile
import unittest

from tools.compare_frozen_eval import compare, digest, load_exam


class FrozenComparisonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def write(self, name, outcomes=(0, 1), **overrides):
        path = self.root / name
        path.mkdir()
        manifest = {"cells": [{"style": "contact", "learner_side": "home", "seed": 42}],
                    "games_per_cell": 2, "checkpoint_sha256": name,
                    "runtime_identity_sha256": "runtime"}
        manifest.update(overrides)
        games = [{"style": "contact", "learner_side": "home", "base_seed": 42,
                  "episode": i + 1, "checkpoint_sha256": name,
                  "runtime_identity_sha256": manifest["runtime_identity_sha256"],
                  "td_diff": td, "match_points": 1 if td > 0 else .5 if td == 0 else 0}
                 for i, td in enumerate(outcomes)]
        (path / "MANIFEST.json").write_text(json.dumps(manifest))
        (path / "GAMES.jsonl").write_text("\n".join(map(json.dumps, games)) + "\n")
        self.complete(path)
        return path

    def complete(self, path):
        (path / "COMPLETE.json").write_text(json.dumps({
            "manifest_sha256": digest(path / "MANIFEST.json"),
            "games_sha256": digest(path / "GAMES.jsonl"), "expected_games": 2}))

    def test_paired_results_use_match_points_not_touchdown_volume(self):
        a = self.write("a", (0, 1))
        b = self.write("b", (-1, 4))
        result = compare(a, b)
        self.assertEqual(result["aggregate"]["match_score_delta"], -.25)
        self.assertEqual(result["aggregate"]["td_diff_delta"], 1)
        self.assertEqual(result["aggregate"]["candidate_worse_games"], 1)

    def test_reordering_records_preserves_game_pairing(self):
        a = self.write("a")
        b = self.write("b")
        path = b / "GAMES.jsonl"
        path.write_text("\n".join(reversed(path.read_text().splitlines())) + "\n")
        self.complete(b)
        self.assertEqual(compare(a, b)["aggregate"]["match_score_delta"], 0)

    def test_tampering_invalidates_completed_evidence(self):
        a = self.write("a")
        with (a / "GAMES.jsonl").open("a") as out:
            out.write("{}\n")
        with self.assertRaisesRegex(ValueError, "games_sha256 mismatch"):
            load_exam(a)

    def test_duplicate_and_missing_games_fail_even_after_rehash(self):
        a = self.write("a")
        p = a / "GAMES.jsonl"
        first = p.read_text().splitlines()[0]
        p.write_text(first + "\n" + first + "\n")
        self.complete(a)
        with self.assertRaisesRegex(ValueError, "duplicate, missing, or extra"):
            load_exam(a)

    def test_mismatched_runtime_is_not_a_causal_comparison(self):
        a = self.write("a")
        b = self.write("b", runtime_identity_sha256="new-runtime")
        with self.assertRaisesRegex(ValueError, "runtime identities differ"):
            compare(a, b)

    def test_effective_config_difference_is_rejected(self):
        a = self.write("a", effective_configs={"demo_reset_pct": 0})
        b = self.write("b", effective_configs={"demo_reset_pct": .5})
        with self.assertRaisesRegex(ValueError, "configurations differ"):
            compare(a, b)

    def test_terminal_score_validation_rejects_wrong_perspective(self):
        a = self.write("a")
        p = a / "GAMES.jsonl"
        rows = [json.loads(line) for line in p.read_text().splitlines()]
        rows[1]["match_points"] = 0
        p.write_text("\n".join(map(json.dumps, rows)) + "\n")
        self.complete(a)
        with self.assertRaisesRegex(ValueError, "points disagree"):
            load_exam(a)


if __name__ == "__main__":
    unittest.main()
