#!/usr/bin/env python3

import struct
import tempfile
import unittest
from pathlib import Path

from validation import extract_pairs


class ExtractedPairLineageTests(unittest.TestCase):
    def write_shard(self, root: Path, version: int) -> Path:
        path = root / "25.bbp"
        obs_size = 2782
        mask_size = 454
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

    def test_current_v5_shard_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_shard(Path(tmp), version=5)
            self.assertEqual(extract_pairs.validate_shard(path), 1)

    def test_stale_v4_writer_output_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_shard(Path(tmp), version=4)
            with self.assertRaisesRegex(
                    ValueError, "must emit BBP v5/2782/454"):
                extract_pairs.validate_shard(path)


if __name__ == "__main__":
    unittest.main()
