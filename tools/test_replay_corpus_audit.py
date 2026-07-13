#!/usr/bin/env python3

import gzip
import json
import struct
import tempfile
import unittest
from pathlib import Path

import replay_corpus_audit as corpus_audit


class ReplayCorpusAuditTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> tuple[Path, Path, Path]:
        replay_cache = root / "replays"
        pairs = root / "pairs"
        replay_cache.mkdir()
        pairs.mkdir()
        manifest = {
            "100": {
                "matchId": 100,
                "replayId": 10,
                "date": "2026-04-01",
                "team1": {"race": "Human", "bracket": "Star", "score": 2},
                "team2": {"race": "Orc", "bracket": "Legend", "score": 1},
            },
            "101": {
                "matchId": 101,
                "replayId": 11,
                "date": "2026-04-01",
                "team1": {"race": "Orc", "bracket": "Legend", "score": 1},
                "team2": {"race": "Human", "bracket": "Star", "score": 1},
            },
        }
        manifest_path = replay_cache / "manifest.json"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        for replay_id, version in ((10, "BB2020"), (11, "BB2025")):
            replay = {
                "game": {
                    "gameOptions": {
                        "gameOptionArray": [
                            {"gameOptionId": "rulesVersion",
                             "gameOptionValue": version}
                        ]
                    }
                }
            }
            with gzip.open(replay_cache / f"replay_{replay_id}.json.gz", "wt") as f:
                json.dump(replay, f)

            obs_size, mask_size, records = 8, 5, replay_id - 8
            record_size = 12 + obs_size + mask_size + 4
            with (pairs / f"{replay_id}.bbp").open("wb") as f:
                f.write(struct.pack("<4sIII", b"BBP1", 2, obs_size, mask_size))
                f.write(bytes(record_size * records))
        return manifest_path, replay_cache, pairs

    def test_exact_embedded_rules_version_beats_same_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, replays, pairs = self.make_fixture(Path(tmp))
            result = corpus_audit.audit(manifest, replays, pairs)

        self.assertEqual(result["manifest_games"], 2)
        self.assertEqual(result["pair_shards"], 2)
        self.assertEqual(result["pair_records"], 5)
        self.assertEqual(result["rules_versions"]["BB2020"]["paired_games"], 1)
        self.assertEqual(result["rules_versions"]["BB2020"]["pair_records"], 2)
        self.assertEqual(result["rules_versions"]["BB2025"]["paired_games"], 1)
        self.assertEqual(result["rules_versions"]["BB2025"]["pair_records"], 3)
        self.assertEqual(result["rules_versions"]["BB2025"]["draws"], 1)

    def test_bbp_size_validation_rejects_partial_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "10.bbp"
            path.write_bytes(struct.pack("<4sIII", b"BBP1", 2, 8, 5) + b"x")
            with self.assertRaisesRegex(ValueError, "not divisible"):
                corpus_audit.inspect_bbp(path)

    def test_audit_fails_loudly_when_pairs_directory_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, replays, _pairs = self.make_fixture(Path(tmp))
            missing = Path(tmp) / "missing-pairs"
            with self.assertRaisesRegex(FileNotFoundError, "pairs directory"):
                corpus_audit.audit(manifest, replays, missing)

    def test_audit_rejects_duplicate_numeric_shard_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, replays, pairs = self.make_fixture(Path(tmp))
            (pairs / "010.bbp").write_bytes((pairs / "10.bbp").read_bytes())
            with self.assertRaisesRegex(ValueError, "duplicate pair shards"):
                corpus_audit.audit(manifest, replays, pairs)

    def test_score_rates_use_only_games_with_numeric_scores(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest_path, replays, pairs = self.make_fixture(Path(tmp))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["101"]["team1"]["score"] = None
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            replay = {
                "game": {"gameOptions": {"gameOptionArray": [{
                    "gameOptionId": "rulesVersion",
                    "gameOptionValue": "BB2020",
                }]}}
            }
            with gzip.open(replays / "replay_11.json.gz", "wt") as f:
                json.dump(replay, f)

            result = corpus_audit.audit(manifest_path, replays, pairs)

        summary = result["rules_versions"]["BB2020"]
        self.assertEqual(summary["manifest_games"], 2)
        self.assertEqual(summary["scored_games"], 1)
        self.assertEqual(summary["mean_total_score"], 3.0)
        self.assertEqual(summary["draw_rate"], 0.0)

    def test_training_allowlist_is_exact_and_requires_complete_audit(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, replays, pairs = self.make_fixture(Path(tmp))
            output = Path(tmp) / "bb2025.ids"
            corpus_audit.audit(manifest, replays, pairs,
                               bb2025_ids_path=output)
            self.assertEqual(output.read_text(encoding="utf-8"), "11\n")

            (replays / "replay_11.json.gz").unlink()
            with self.assertRaisesRegex(ValueError, "training allowlist"):
                corpus_audit.audit(manifest, replays, pairs,
                                   bb2025_ids_path=output)


if __name__ == "__main__":
    unittest.main()
