#!/usr/bin/env python

import struct
import hashlib
import tempfile
import unittest
from pathlib import Path

import numpy as np

import bc_pretrain


class ReplayIdFilterTests(unittest.TestCase):
    def write_shard(self, root: Path, replay_id: int) -> None:
        obs_size = 8
        mask_size = sum(bc_pretrain.ACT_SIZES)
        dtype = bc_pretrain.rec_dtype(obs_size, mask_size)
        record = np.zeros(1, dtype=dtype)
        record["replay"] = replay_id
        record["mask"][:, 0] = 1
        record["mask"][:, bc_pretrain.ACT_SIZES[0]] = 1
        record["mask"][:, bc_pretrain.ACT_SIZES[0] + bc_pretrain.ACT_SIZES[1]] = 1
        with (root / f"{replay_id}.bbp").open("wb") as f:
            f.write(struct.pack("<4sIII", b"BBP1", 2, obs_size, mask_size))
            f.write(record.tobytes())

    def test_allowlist_excludes_other_ruleset_shards(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_shard(root, 20)
            self.write_shard(root, 25)
            ids_path = root / "bb2025.ids"
            ids_path.write_text("# exact embedded rulesVersion\n25\n", encoding="utf-8")

            replay_ids = bc_pretrain.load_replay_ids(ids_path)
            records, obs_size, mask_size = bc_pretrain.load_shards(
                root, replay_ids=replay_ids)

        self.assertEqual(replay_ids, frozenset({25}))
        self.assertEqual(
            bc_pretrain.replay_ids_sha256(replay_ids),
            hashlib.sha256(b"25\n").hexdigest())
        self.assertEqual(records["replay"].tolist(), [25])
        self.assertEqual(obs_size, 8)
        self.assertEqual(mask_size, sum(bc_pretrain.ACT_SIZES))

    def test_allowlist_fails_if_expected_shard_is_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_shard(root, 25)

            with self.assertRaisesRegex(SystemExit, "missing 1 requested replay shard"):
                bc_pretrain.load_shards(root, replay_ids={25, 26})

    def test_duplicate_numeric_shards_are_rejected_without_filter(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.write_shard(root, 25)
            (root / "025.bbp").write_bytes((root / "25.bbp").read_bytes())

            with self.assertRaisesRegex(SystemExit, "duplicate .bbp shard"):
                bc_pretrain.load_shards(root)


if __name__ == "__main__":
    unittest.main()
