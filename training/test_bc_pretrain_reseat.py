#!/usr/bin/env python
"""The loader's side of the "replay-seated, observation only" contract.

AGENTS.md, "Replay and BC contract": a loader reads re-seated (BBR1) shards
only when asked to, filters on the span stamp, and by default admits spans
that closed equal to the replay (stamp 1) and nothing else.
"""

import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

import bc_pretrain


OBS = 8
MASK = sum(bc_pretrain.ACT_SIZES)


def write_shard(path, replay_id, count, *, magic=b"BBP1", version=4,
                obs_size=OBS, stamps=None, segment=1):
    """One shard; a BBR1 shard takes one span stamp per record."""
    dtype = bc_pretrain.rec_dtype(obs_size, MASK)
    records = np.zeros(count, dtype=dtype)
    records["replay"] = replay_id
    records["cmd"] = np.arange(count, dtype=np.uint32)
    records["obs"][:, 0] = np.arange(count, dtype=np.uint8)
    offset = 0
    for size in bc_pretrain.ACT_SIZES:
        records["mask"][:, offset] = 1
        offset += size
    if magic == b"BBR1":
        records["pad"][:, 0] = segment & 0xFF
        records["pad"][:, 1] = segment >> 8
        records["pad"][:, 2] = np.asarray(stamps, dtype=np.uint8)
        # Mark re-seated observations so a test can tell the two apart.
        records["obs"][:, 1] = 200 + np.asarray(stamps, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sIII", magic, version, obs_size, MASK))
        f.write(records.tobytes())


class ReseatContractTests(unittest.TestCase):
    def corpus(self, tmp):
        """Two replays: prefix shards, and re-seated shards with every stamp."""
        pairs, reseat = Path(tmp) / "pairs", Path(tmp) / "pairs_reseat"
        pairs.mkdir()
        reseat.mkdir()
        write_shard(pairs / "10.bbp", 10, 3)
        write_shard(pairs / "11.bbp", 11, 0)
        write_shard(reseat / "10.bbr", 10, 7, magic=b"BBR1",
                    stamps=[1, 0, 1, 4, 2, 3, 1])
        write_shard(reseat / "11.bbr", 11, 4, magic=b"BBR1",
                    stamps=[0, 1, 1, 2], segment=300)
        return pairs, reseat

    def all_records(self, index):
        data = bc_pretrain.LazyReplayDataset(index, index.nonempty_replay_ids)
        return data, np.concatenate(list(data.iter_record_batches(batch_size=2)))

    def test_default_reads_no_reseated_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs, _reseat = self.corpus(tmp)
            with bc_pretrain.ShardIndex.from_directory(pairs) as index:
                self.assertEqual(index.reseat_records, 0)
                self.assertEqual(index.total_records, 3)
                self.assertEqual(index.nonempty_replay_ids, (10,))
                self.assertIn("prefix records only", index.subset_label)
                _data, records = self.all_records(index)
                self.assertTrue(np.all(bc_pretrain.record_segment(records) == 0))

    def test_bbr_in_the_pairs_directory_is_never_picked_up(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs, reseat = self.corpus(tmp)
            (pairs / "10.bbr").write_bytes((reseat / "10.bbr").read_bytes())
            with bc_pretrain.ShardIndex.from_directory(pairs) as index:
                self.assertEqual(index.total_records, 3)
            # Renamed to .bbp it is refused by its magic.
            (pairs / "12.bbp").write_bytes((reseat / "10.bbr").read_bytes())
            with self.assertRaises(SystemExit):
                bc_pretrain.ShardIndex.from_directory(pairs)

    def test_asking_for_reseats_admits_closed_equal_spans_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs, reseat = self.corpus(tmp)
            with bc_pretrain.ShardIndex.from_directory(
                    pairs, reseat_dir=reseat) as index:
                self.assertEqual(index.reseat_stamps, (1,))
                self.assertEqual(index.prefix_records, 3)
                self.assertEqual(index.reseat_records, 5)
                self.assertEqual(index.nonempty_replay_ids, (10, 11))
                self.assertEqual(
                    index.reseat_stamp_counts, {0: 2, 1: 5, 2: 2, 3: 1, 4: 1})
                self.assertIn("closed equal", index.subset_label)
                data, records = self.all_records(index)
                self.assertEqual(len(records), 8)
                self.assertEqual(
                    data.provenance_counts, {"prefix": 3, "reseat": 5})
                segment = bc_pretrain.record_segment(records)
                stamp = bc_pretrain.record_stamp(records)
                self.assertEqual(int((segment == 0).sum()), 3)
                self.assertTrue(np.all(stamp[segment > 0] == 1))
                self.assertEqual(
                    sorted(set(int(v) for v in segment[segment > 0])), [1, 300])
                # Sampling can reach only admitted records, in both modes.
                rng = np.random.default_rng(0)
                for mode in ("replay", "record"):
                    sample = data.sample_records(400, rng, mode=mode)
                    seg = bc_pretrain.record_segment(sample)
                    self.assertTrue(
                        np.all(bc_pretrain.record_stamp(sample)[seg > 0] == 1))
                    self.assertTrue((seg == 0).any() and (seg > 0).any())
                    self.assertEqual(set(np.unique(sample["replay"])), {10, 11})

    def test_wider_stamp_sets_are_explicit_and_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs, reseat = self.corpus(tmp)
            with bc_pretrain.ShardIndex.from_directory(
                    pairs, reseat_dir=reseat,
                    reseat_stamps=(0, 1, 2, 3, 4)) as index:
                self.assertEqual(index.reseat_records, 11)
                self.assertIn("NOT the contract default", index.subset_label)
                _data, records = self.all_records(index)
                self.assertEqual(len(records), 14)
            with bc_pretrain.ShardIndex.from_directory(
                    pairs, reseat_dir=reseat, reseat_stamps=(1, 4)) as index:
                self.assertEqual(index.reseat_records, 6)

    def test_reseated_read_indexes_admitted_rows(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs, reseat = self.corpus(tmp)
            with bc_pretrain.ShardIndex.from_directory(
                    pairs, reseat_dir=reseat) as index:
                got = index.read_records(
                    10, np.arange(3), provenance=bc_pretrain.PROVENANCE_RESEAT)
                # Physical rows 0, 2 and 6 carry stamp 1.
                self.assertEqual([int(v) for v in got["cmd"]], [0, 2, 6])
                with self.assertRaises(IndexError):
                    index.read_records(
                        10, np.arange(4),
                        provenance=bc_pretrain.PROVENANCE_RESEAT)

    def test_stamps_without_a_directory_are_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs, _reseat = self.corpus(tmp)
            with self.assertRaises(SystemExit):
                bc_pretrain.ShardIndex.from_directory(pairs, reseat_stamps=(1,))

    def test_bad_reseat_inputs_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            pairs, reseat = self.corpus(tmp)
            with self.assertRaises(SystemExit):   # unknown stamp requested
                bc_pretrain.ShardIndex.from_directory(
                    pairs, reseat_dir=reseat, reseat_stamps=(9,))
            with self.assertRaises(SystemExit):   # empty allowlist
                bc_pretrain.ShardIndex.from_directory(
                    pairs, reseat_dir=reseat, reseat_stamps=())
            (reseat / "11.bbr").unlink()
            with self.assertRaises(SystemExit):   # a replay without its shard
                bc_pretrain.ShardIndex.from_directory(pairs, reseat_dir=reseat)
            write_shard(reseat / "11.bbr", 11, 2, magic=b"BBR1",
                        stamps=[1, 1], segment=0)
            with self.assertRaises(SystemExit):   # segment 0 is a prefix record
                bc_pretrain.ShardIndex.from_directory(pairs, reseat_dir=reseat)
            write_shard(reseat / "11.bbr", 11, 2, magic=b"BBR1", stamps=[1, 7])
            with self.assertRaises(SystemExit):   # stamp the format does not define
                bc_pretrain.ShardIndex.from_directory(pairs, reseat_dir=reseat)
            write_shard(reseat / "11.bbr", 11, 2, magic=b"BBR1", stamps=[1, 1],
                        obs_size=OBS + 1)
            with self.assertRaises(SystemExit):   # another observation lineage
                bc_pretrain.ShardIndex.from_directory(pairs, reseat_dir=reseat)
            write_shard(reseat / "11.bbr", 11, 2, magic=b"BBP1")
            with self.assertRaises(SystemExit):   # a prefix shard in disguise
                bc_pretrain.ShardIndex.from_directory(pairs, reseat_dir=reseat)
            write_shard(reseat / "11.bbr", 12, 2, magic=b"BBR1", stamps=[1, 1])
            with self.assertRaises(SystemExit):   # records of another replay
                bc_pretrain.ShardIndex.from_directory(pairs, reseat_dir=reseat)

    def test_cli_default_is_prefix_only_and_stamp_default_is_closed_equal(self):
        self.assertEqual(bc_pretrain.DEFAULT_RESEAT_STAMPS, (1,))
        self.assertEqual(bc_pretrain.normalize_reseat_stamps(None), (1,))
        self.assertIn("prefix records only",
                      bc_pretrain.reseat_subset_label(None))
        self.assertIn("closed equal", bc_pretrain.reseat_subset_label((1,)))
        self.assertIn("NOT the contract default",
                      bc_pretrain.reseat_subset_label((0, 1)))


if __name__ == "__main__":
    unittest.main()
