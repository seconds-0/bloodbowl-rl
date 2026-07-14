#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_reward_candidate_transfer as runner


class RewardCandidateTransferRunnerTests(unittest.TestCase):
    def test_paired_screen_discovers_only_reference_and_candidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            prefix = "paired"
            for arm in ("both", "gain_only"):
                for seed in (42, 43):
                    checkpoint = root / f"{arm}-{seed}.bin"
                    checkpoint.write_bytes(b"test")
                    result = {
                        "checkpoint": str(checkpoint),
                        "checkpoint_sha256": hashlib.sha256(
                            checkpoint.read_bytes()
                        ).hexdigest(),
                    }
                    (root / f"{prefix}-{arm}-s{seed}.result.json").write_text(
                        json.dumps(result), encoding="utf-8"
                    )
            report = {
                "screen": {
                    "completion": {"present": True},
                    "profile": "paired-confirmation",
                    "prefix": prefix,
                    "candidate_arm": "gain_only",
                }
            }
            with (
                mock.patch.object(
                    runner.analyze_reward_screen,
                    "analyze_screen",
                    return_value=report,
                ),
                mock.patch.object(runner, "EXPECTED_NATIVE_BYTES", 4),
            ):
                checkpoints, arms = runner.screen_checkpoints(
                    root, "0" * 64
                )

        self.assertEqual(arms, ("both", "gain_only"))
        self.assertEqual(set(checkpoints), set(arms))
        self.assertEqual(set(checkpoints["both"]), {"42", "43"})


if __name__ == "__main__":
    unittest.main()
