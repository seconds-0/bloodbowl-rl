#!/usr/bin/env python3

import hashlib
import json
import tempfile
import subprocess
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

    def test_conversion_reuse_rejects_converter_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "training").mkdir()
            (root / "puffer/config").mkdir(parents=True)
            converter = root / "training/convert_checkpoint.py"
            converter.write_text("converter-v1")
            (root / "puffer/config/bloodbowl.ini").write_text("config-v1")
            checkpoints = {"both": {}}
            for seed in runner.SEEDS:
                source = root / f"source-{seed}.bin"
                source.write_bytes(b"native")
                checkpoints["both"][str(seed)] = {
                    "native": str(source),
                    "native_sha256": runner.sha256(source),
                }

            def fake_run(command, **_kwargs):
                output = Path(command[command.index("-o") + 1])
                output.write_bytes(b"x" * 1_000_001)
                return subprocess.CompletedProcess(command, 0, "converted")

            with mock.patch.object(runner, "run_checked", side_effect=fake_run):
                runner.convert_checkpoints(
                    root, root / "out", checkpoints, ("both",)
                )
                runner.convert_checkpoints(
                    root, root / "out", checkpoints, ("both",)
                )
                converter.write_text("converter-v2")
                with self.assertRaisesRegex(runner.RunnerError, "metadata drift"):
                    runner.convert_checkpoints(
                        root, root / "out", checkpoints, ("both",)
                    )

    def test_frozen_manifest_rejects_recomputed_plan_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "training").mkdir()
            (root / "puffer/config").mkdir(parents=True)
            (root / "training/convert_checkpoint.py").write_text("converter")
            (root / "puffer/config/bloodbowl.ini").write_text("config")
            manifest = root / "TRANSFER_MANIFEST.json"
            checkpoints = {
                arm: {str(seed): {"torch_sha256": "0" * 64}
                      for seed in runner.SEEDS}
                for arm in ("both", "gain_only")
            }
            with (
                mock.patch.object(
                    runner, "implementation_identity", return_value={"x": "1"}
                ),
                mock.patch.object(
                    runner, "orchestration_identity", return_value={"y": "2"}
                ),
            ):
                runner.freeze_manifest(
                    manifest, root, root / "screen", "a" * 64,
                    checkpoints, ("both", "gain_only"),
                )
                saved = json.loads(manifest.read_text())
                saved["gates"]["mean_score_delta_min"] = -0.5
                manifest.write_text(json.dumps(saved))
                with self.assertRaisesRegex(
                    runner.RunnerError, "differs from recomputed plan"
                ):
                    runner.freeze_manifest(
                        manifest, root, root / "screen", "a" * 64,
                        checkpoints, ("both", "gain_only"),
                    )


if __name__ == "__main__":
    unittest.main()
