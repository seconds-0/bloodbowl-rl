#!/usr/bin/env python

import struct
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np
import torch

import bc_pretrain


class StreamingShardTests(unittest.TestCase):
    def write_shard(
        self,
        root: Path,
        replay_id: int,
        count: int,
        *,
        obs_size: int = 8,
        version: int = 2,
        record_replay_id: int | None = None,
    ) -> None:
        mask_size = sum(bc_pretrain.ACT_SIZES)
        dtype = bc_pretrain.rec_dtype(obs_size, mask_size)
        records = np.zeros(count, dtype=dtype)
        records["replay"] = (
            replay_id if record_replay_id is None else record_replay_id)
        records["cmd"] = np.arange(count, dtype=np.uint32)
        if obs_size:
            records["obs"][:, 0] = replay_id % 256
            if obs_size > 1:
                records["obs"][:, 1] = np.arange(count, dtype=np.uint8)
        offset = 0
        for size in bc_pretrain.ACT_SIZES:
            records["mask"][:, offset] = 1
            records["mask"][:, offset + 1] = 1
            offset += size
        with (root / f"{replay_id}.bbp").open("wb") as f:
            f.write(struct.pack(
                "<4sIII", b"BBP1", version, obs_size, mask_size))
            f.write(records.tobytes())

    def test_split_is_seeded_replay_disjoint_and_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for replay_id in range(10, 20):
                self.write_shard(root, replay_id, replay_id - 8)
            index = bc_pretrain.ShardIndex.from_directory(root, cache_size=2)

            a_train, a_val = bc_pretrain.split_replay_ids(
                index.nonempty_replay_ids, 0.3, 123)
            b_train, b_val = bc_pretrain.split_replay_ids(
                index.nonempty_replay_ids, 0.3, 123)
            c_train, c_val = bc_pretrain.split_replay_ids(
                index.nonempty_replay_ids, 0.3, 124)

            self.assertEqual((a_train, a_val), (b_train, b_val))
            self.assertNotEqual(a_val, c_val)
            self.assertFalse(set(a_train) & set(a_val))
            self.assertEqual(
                set(a_train) | set(a_val), set(index.nonempty_replay_ids))
            self.assertEqual(len(a_val), 3)
            index.close()

    def test_allowlist_missing_mixed_lineage_and_bad_replay_ids_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_shard(root, 20, 2)
            self.write_shard(root, 25, 3)

            index = bc_pretrain.ShardIndex.from_directory(
                root, replay_ids={25}, cache_size=1)
            self.assertEqual(index.replay_ids, (25,))
            self.assertEqual(index.total_records, 3)
            index.close()

            with self.assertRaisesRegex(
                    SystemExit, "missing 1 requested replay shard"):
                bc_pretrain.ShardIndex.from_directory(root, replay_ids={25, 26})

            self.write_shard(root, 30, 1, obs_size=9)
            with self.assertRaisesRegex(SystemExit, "header mismatch across shards"):
                bc_pretrain.ShardIndex.from_directory(root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_shard(root, 40, 2, record_replay_id=41)
            with self.assertRaisesRegex(SystemExit, "record replay IDs"):
                bc_pretrain.ShardIndex.from_directory(root)

    def test_malformed_headers_and_partial_records_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "10.bbp").write_bytes(b"short")
            with self.assertRaisesRegex(SystemExit, "truncated .bbp header"):
                bc_pretrain.ShardIndex.from_directory(root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "10.bbp").write_bytes(
                struct.pack("<4sIII", b"NOPE", 2, 8,
                            sum(bc_pretrain.ACT_SIZES)))
            with self.assertRaisesRegex(SystemExit, "bad header"):
                bc_pretrain.ShardIndex.from_directory(root)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "10.bbp").write_bytes(
                struct.pack("<4sIII", b"BBP1", 2, 8,
                            sum(bc_pretrain.ACT_SIZES)) + b"partial")
            with self.assertRaisesRegex(SystemExit, "whole number"):
                bc_pretrain.ShardIndex.from_directory(root)

    def test_replay_first_and_record_weighted_sampling_semantics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_shard(root, 10, 1)
            self.write_shard(root, 20, 9)
            index = bc_pretrain.ShardIndex.from_directory(root, cache_size=1)
            data = bc_pretrain.LazyReplayDataset(index, index.nonempty_replay_ids)

            replay_a = data.sample_records(
                20_000, np.random.default_rng(7), mode="replay")
            replay_b = data.sample_records(
                20_000, np.random.default_rng(7), mode="replay")
            record = data.sample_records(
                20_000, np.random.default_rng(7), mode="record")

            np.testing.assert_array_equal(replay_a, replay_b)
            replay_share = np.mean(replay_a["replay"] == 10)
            record_share = np.mean(record["replay"] == 10)
            self.assertAlmostEqual(replay_share, 0.5, delta=0.02)
            self.assertAlmostEqual(record_share, 0.1, delta=0.02)
            index.close()

    def test_open_memmap_cache_and_batches_stay_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for replay_id in range(1, 7):
                self.write_shard(root, replay_id, 3)
            index = bc_pretrain.ShardIndex.from_directory(root, cache_size=2)
            data = bc_pretrain.LazyReplayDataset(index, index.nonempty_replay_ids)

            self.assertEqual(index.cache_entries, 0)
            seen = []
            for records in data.iter_record_batches(batch_size=2):
                self.assertLessEqual(len(records), 2)
                self.assertLessEqual(index.cache_entries, 2)
                seen.extend(zip(records["replay"].tolist(),
                                records["cmd"].tolist()))

            self.assertEqual(len(seen), 18)
            self.assertEqual(index.max_cache_entries, 2)
            self.assertLessEqual(index.cache_entries, 2)
            self.assertTrue(all(
                isinstance(value, np.memmap)
                for value in index.cached_memmaps))
            index.close()
            self.assertEqual(index.cache_entries, 0)

    def test_validation_evaluation_is_batchwise(self):
        class CountingPolicy:
            def __init__(self):
                self.max_batch = 0
                self.training = True

            def eval(self):
                self.training = False

            def train(self):
                self.training = True

            def initial_state(self, _batch, device=None):
                return ()

            def forward_eval(self, obs, _state):
                self.max_batch = max(self.max_batch, obs.shape[0])
                logits = tuple(torch.zeros(
                    obs.shape[0], size, device=obs.device)
                    for size in bc_pretrain.ACT_SIZES)
                values = torch.zeros(obs.shape[0], device=obs.device)
                return logits, values, ()

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_shard(root, 10, 3)
            self.write_shard(root, 20, 4)
            index = bc_pretrain.ShardIndex.from_directory(root, cache_size=1)
            data = bc_pretrain.LazyReplayDataset(index, index.nonempty_replay_ids)
            policy = CountingPolicy()

            loss, heads, exact = bc_pretrain.evaluate_lazy(
                policy, data, "cpu", batch=2)

            self.assertLessEqual(policy.max_batch, 2)
            self.assertAlmostEqual(loss, 3 * np.log(2), places=5)
            self.assertEqual(heads, [1.0, 1.0, 1.0])
            self.assertEqual(exact, 1.0)
            self.assertTrue(policy.training)
            index.close()

    def test_auto_device_prefers_cuda_then_mps_then_cpu(self):
        with (
            mock.patch.object(torch.cuda, "is_available", return_value=True),
            mock.patch.object(torch.backends.mps, "is_available", return_value=True),
        ):
            self.assertEqual(bc_pretrain.resolve_device("auto"), "cuda")
        with (
            mock.patch.object(torch.cuda, "is_available", return_value=False),
            mock.patch.object(torch.backends.mps, "is_available", return_value=True),
        ):
            self.assertEqual(bc_pretrain.resolve_device("auto"), "mps")
        with (
            mock.patch.object(torch.cuda, "is_available", return_value=False),
            mock.patch.object(torch.backends.mps, "is_available", return_value=False),
        ):
            self.assertEqual(bc_pretrain.resolve_device("auto"), "cpu")
        self.assertEqual(bc_pretrain.resolve_device("cuda:1"), "cuda:1")


if __name__ == "__main__":
    unittest.main()
