#!/usr/bin/env python3

import struct
import tempfile
import unittest
from pathlib import Path

from validation import extract_pairs


class ExtractedPairLineageTests(unittest.TestCase):
    def write_shard(
            self,
            root: Path,
            version: int,
            *,
            obs_size: int = 2782,
            mask_size: int = 454,
    ) -> Path:
        path = root / "25.bbp"
        mask = bytearray(mask_size)
        mask[0] = 1
        mask[30] = 1
        mask[63] = 1
        record = (
            struct.pack("<IIB3x", 25, 7, 0)
            + bytes(obs_size)
            + bytes(mask)
            + struct.pack("<BBH", 0, 0, 0)
        )
        path.write_bytes(
            struct.pack(
                "<4sIII", b"BBP1", version, obs_size, mask_size)
            + record
        )
        return path

    def test_current_v6_shard_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_shard(Path(tmp), version=6)
            self.assertEqual(extract_pairs.validate_shard(path), 1)

    def test_stale_v5_writer_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_shard(Path(tmp), version=5)
            with self.assertRaisesRegex(
                    ValueError, "must emit BBP v6/2782/454"):
                extract_pairs.validate_shard(path)

    def test_v6_label_with_wrong_observation_size_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_shard(Path(tmp), version=6, obs_size=8)
            with self.assertRaisesRegex(
                    ValueError, "must emit BBP v6/2782/454"):
                extract_pairs.validate_shard(path)

    def test_v6_label_with_wrong_mask_size_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_shard(Path(tmp), version=6, mask_size=453)
            with self.assertRaisesRegex(
                    ValueError, "must emit BBP v6/2782/454"):
                extract_pairs.validate_shard(path)


if __name__ == "__main__":
    unittest.main()
