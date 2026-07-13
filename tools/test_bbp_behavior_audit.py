#!/usr/bin/env python3

import contextlib
import io
import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bbp_behavior_audit as behavior_audit


class BBPBehaviorAuditTests(unittest.TestCase):
    def make_record(
        self,
        replay_id: int,
        obs_size: int,
        *,
        cmd: int = 10,
        agent: int = 0,
        half: int = 1,
        turn: int = 1,
        opp_turn: int = 0,
        action_type: int = 9,
        action_arg: int = 32,
        action_square: int = 10,
        legal: bool = True,
    ) -> bytes:
        record_size = 12 + obs_size + behavior_audit.MASK_SIZE + 4
        record = bytearray(record_size)
        struct.pack_into("<II", record, 0, replay_id, cmd)
        record[8] = agent
        record[12 + behavior_audit.OBS_HALF] = half
        record[12 + behavior_audit.OBS_MY_TURN] = turn
        record[12 + behavior_audit.OBS_OPP_TURN] = opp_turn

        mask_offset = 12 + obs_size
        if legal:
            record[mask_offset + action_type] = 1
            record[mask_offset + behavior_audit.HEAD_TYPE + action_arg] = 1
            record[
                mask_offset
                + behavior_audit.HEAD_TYPE
                + behavior_audit.HEAD_ARG
                + action_square
            ] = 1
        target_offset = mask_offset + behavior_audit.MASK_SIZE
        struct.pack_into(
            "<BBH",
            record,
            target_offset,
            action_type,
            action_arg,
            action_square,
        )
        return bytes(record)

    def write_shard(
        self,
        root: Path,
        replay_id: int,
        *,
        version: int,
        obs_size: int,
        records: list[bytes],
        filename: str | None = None,
        mask_size: int = behavior_audit.MASK_SIZE,
    ) -> Path:
        path = root / (filename or f"{replay_id}.bbp")
        with path.open("wb") as f:
            f.write(struct.pack("<4sIII", b"BBP1", version, obs_size, mask_size))
            for record in records:
                f.write(record)
        return path

    def make_mixed_fixture(self, root: Path) -> Path:
        pairs = root / "pairs"
        pairs.mkdir()
        obs_v1 = 832
        obs_v2 = 2782
        self.write_shard(
            pairs,
            10,
            version=1,
            obs_size=obs_v1,
            records=[
                self.make_record(
                    10,
                    obs_v1,
                    cmd=10,
                    half=1,
                    turn=1,
                    action_type=9,
                    action_square=10,
                ),
                self.make_record(
                    10,
                    obs_v1,
                    cmd=25,
                    agent=1,
                    half=1,
                    turn=2,
                    opp_turn=1,
                    action_type=13,
                    action_square=20,
                ),
            ],
        )
        self.write_shard(
            pairs,
            11,
            version=2,
            obs_size=obs_v2,
            records=[
                self.make_record(
                    11,
                    obs_v2,
                    cmd=100,
                    half=2,
                    turn=3,
                    opp_turn=2,
                    action_type=9,
                    action_square=30,
                )
            ],
        )
        self.write_shard(
            pairs,
            12,
            version=2,
            obs_size=1612,
            records=[],
        )
        return pairs

    def test_streams_mixed_v1_v2_and_reports_depth_and_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs = self.make_mixed_fixture(Path(tmp))
            result = behavior_audit.audit(pairs, chunk_records=1)

        self.assertEqual(result["shards"], 3)
        self.assertEqual(result["zero_shards"], 1)
        self.assertEqual(result["records"], 3)
        self.assertEqual(result["headers"]["v1/obs832/mask454"], 1)
        self.assertEqual(result["headers"]["v2/obs1612/mask454"], 1)
        self.assertEqual(result["headers"]["v2/obs2782/mask454"], 1)
        self.assertEqual(result["agent_counts"], {"0": 2, "1": 1})
        self.assertEqual(result["half_counts"], {"1": 2, "2": 1})
        self.assertEqual(result["turn_counts"], {"1": 1, "2": 1, "3": 1})

        step = result["actions"]["STEP"]
        self.assertEqual(step["records"], 2)
        self.assertEqual(step["replay_coverage"], 2)
        self.assertAlmostEqual(step["replay_coverage_fraction"], 2 / 3)
        self.assertEqual(step["half_counts"], {"1": 1, "2": 1})
        self.assertEqual(result["actions"]["PASS_TARGET"]["records"], 1)
        self.assertEqual(result["actions"]["JUMP"]["records"], 0)

        self.assertEqual(result["replays"]["10"]["records"], 2)
        self.assertEqual(result["replays"]["10"]["command_span"], 15)
        self.assertEqual(result["replays"]["11"]["max_half"], 2)
        self.assertEqual(result["replays"]["11"]["max_match_turn"], 11)
        self.assertIsNone(result["replays"]["12"]["max_turn"])
        self.assertEqual(
            result["depth"]["records_per_replay"]["quantiles"]["p50"], 1
        )
        self.assertEqual(
            result["depth"]["replays_reaching_half"], {"1": 2, "2": 1}
        )
        self.assertEqual(result["depth"]["replays_reaching_turn"]["3"], 1)

    def test_exact_filter_ignores_unrequested_record_bodies_and_requires_all_ids(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pairs = self.make_mixed_fixture(root)
            # This shard has a malformed record body, but an exact audit of 11
            # must not inspect an unrequested numeric shard.
            (pairs / "10.bbp").write_bytes((pairs / "10.bbp").read_bytes() + b"x")
            result = behavior_audit.audit(pairs, replay_ids={11}, chunk_records=1)
            self.assertEqual(result["shards"], 1)
            self.assertEqual(result["records"], 1)
            self.assertEqual(set(result["replays"]), {"11"})

            with self.assertRaisesRegex(FileNotFoundError, "missing 1 requested"):
                behavior_audit.audit(pairs, replay_ids={11, 999})

    def test_replay_id_allowlist_supports_comments_and_rejects_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "ids.txt"
            path.write_text("# exact edition\n11 # keep\n\n12\n", encoding="utf-8")
            self.assertEqual(behavior_audit.load_replay_ids(path), {11, 12})
            path.write_text("# no ids\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "allowlist is empty"):
                behavior_audit.load_replay_ids(path)

    def test_record_replay_id_must_match_numeric_filename(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs = Path(tmp) / "pairs"
            pairs.mkdir()
            obs_size = 832
            self.write_shard(
                pairs,
                10,
                version=1,
                obs_size=obs_size,
                records=[self.make_record(11, obs_size)],
            )
            with self.assertRaisesRegex(ValueError, "does not match shard filename"):
                behavior_audit.audit(pairs)

    def test_selected_target_must_be_in_range_and_legal(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs = Path(tmp) / "pairs"
            pairs.mkdir()
            obs_size = 832
            self.write_shard(
                pairs,
                10,
                version=1,
                obs_size=obs_size,
                records=[self.make_record(10, obs_size, legal=False)],
            )
            with self.assertRaisesRegex(ValueError, "not legal in stored mask"):
                behavior_audit.audit(pairs)

            bad = bytearray(self.make_record(10, obs_size))
            target_offset = 12 + obs_size + behavior_audit.MASK_SIZE
            bad[target_offset] = behavior_audit.HEAD_TYPE
            self.write_shard(
                pairs,
                10,
                version=1,
                obs_size=obs_size,
                records=[bytes(bad)],
            )
            with self.assertRaisesRegex(ValueError, "target out of head range"):
                behavior_audit.audit(pairs)

    def test_header_body_and_observation_layout_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs = Path(tmp) / "pairs"
            pairs.mkdir()
            (pairs / "10.bbp").write_bytes(
                struct.pack("<4sIII", b"BBP1", 2, 832, behavior_audit.MASK_SIZE)
                + b"partial"
            )
            with self.assertRaisesRegex(ValueError, "not divisible"):
                behavior_audit.audit(pairs)

            self.write_shard(
                pairs,
                10,
                version=2,
                obs_size=100,
                records=[],
            )
            with self.assertRaisesRegex(ValueError, "too small for half/turn"):
                behavior_audit.audit(pairs)

            self.write_shard(
                pairs,
                10,
                version=2,
                obs_size=832,
                records=[],
                mask_size=100,
            )
            with self.assertRaisesRegex(ValueError, "mask size 100"):
                behavior_audit.audit(pairs)

    def test_duplicate_numeric_shards_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs = Path(tmp) / "pairs"
            pairs.mkdir()
            self.write_shard(pairs, 10, version=1, obs_size=832, records=[])
            self.write_shard(
                pairs,
                10,
                version=1,
                obs_size=832,
                records=[],
                filename="010.bbp",
            )
            with self.assertRaisesRegex(ValueError, "duplicate pair shards"):
                behavior_audit.audit(pairs)

    def test_cli_prints_parseable_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs = self.make_mixed_fixture(Path(tmp))
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                status = behavior_audit.main(
                    ["--pairs-dir", str(pairs), "--chunk-records", "1"]
                )
            result = json.loads(output.getvalue())

        self.assertEqual(status, 0)
        self.assertEqual(result["schema_version"], 1)
        self.assertEqual(result["records"], 3)


if __name__ == "__main__":
    unittest.main()
