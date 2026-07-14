#!/usr/bin/env python3

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import run_frozen_reward_screen as frozen


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )


class FrozenRewardScreenTests(unittest.TestCase):
    def build_config(self, root: Path) -> Path:
        (root / "tools").mkdir()
        launcher = root / "tools/run_reward_screen.sh"
        screen_analyzer = root / "tools/analyze_reward_screen.py"
        transfer_analyzer = root / "tools/analyze_reward_candidate_transfer.py"
        for path, body in (
            (launcher, "#!/bin/sh\n"),
            (screen_analyzer, "# analyzer\n"),
            (transfer_analyzer, "# transfer\n"),
        ):
            path.write_text(body, encoding="utf-8")
        warm = root / "warm.bin"
        with warm.open("wb") as handle:
            handle.truncate(16_066_560)
        pool = root / "pool"
        pool.mkdir()
        (pool / "league_seeds.json").write_text("{}\n", encoding="utf-8")
        files, size, tree_sha = frozen.tree_identity(pool)
        transfer = root / "TRANSFER_COMPLETE.json"
        write_json(transfer, {"schema_version": 1})
        config = root / "FROZEN_SCREEN.json"
        write_json(config, {
            "schema_version": 1,
            "root": str(root),
            "profile": "paired-final",
            "candidate_arm": "gain_only",
            "steps": 6_000_000_000,
            "prefix": "vacation-final-main",
            "out_dir": str(root / "runs/final-main"),
            "warm": {
                "path": str(warm),
                "bytes": warm.stat().st_size,
                "sha256": frozen.sha256(warm),
            },
            "pool": {
                "path": str(pool),
                "files": files,
                "bytes": size,
                "sha256": tree_sha,
            },
            "candidate_transfer": {
                "path": str(transfer),
                "bytes": transfer.stat().st_size,
                "sha256": frozen.sha256(transfer),
            },
            "require_gate": True,
            "implementation": {
                "launcher_sha256": frozen.sha256(launcher),
                "screen_analyzer_sha256": frozen.sha256(screen_analyzer),
                "transfer_analyzer_sha256": frozen.sha256(transfer_analyzer),
            },
        })
        return config

    def test_closed_config_revalidates_every_indirect_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.build_config(root)
            with mock.patch.object(
                frozen.analyze_reward_candidate_transfer,
                "validate_completion_evidence",
                return_value={"validated": "yes"},
            ):
                result = frozen.validate_config(config)

        self.assertEqual(result["profile"], "paired-final")
        self.assertEqual(result["steps"], 6_000_000_000)
        self.assertEqual(result["candidate_evidence"], {"validated": "yes"})

    def test_pool_tree_drift_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.build_config(root)
            (root / "pool/new-file").write_text("drift", encoding="utf-8")
            with (
                mock.patch.object(
                    frozen.analyze_reward_candidate_transfer,
                    "validate_completion_evidence",
                    return_value={},
                ),
                self.assertRaisesRegex(frozen.FrozenScreenError, "pool tree drift"),
            ):
                frozen.validate_config(config)

    def test_gate_requirement_is_explicit_and_boolean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.build_config(root)
            payload = json.loads(config.read_text())
            payload["require_gate"] = "yes"
            write_json(config, payload)
            with (
                mock.patch.object(
                    frozen.analyze_reward_candidate_transfer,
                    "validate_completion_evidence",
                    return_value={},
                ),
                self.assertRaisesRegex(
                    frozen.FrozenScreenError, "require_gate must be boolean"
                ),
            ):
                frozen.validate_config(config)

    def test_control_final_requires_no_candidate_or_gate_artifact(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self.build_config(root)
            payload = json.loads(config.read_text(encoding="utf-8"))
            payload.update({
                "profile": "control-final",
                "candidate_arm": "both",
                "steps": 12_000_000_000,
                "candidate_transfer": None,
                "require_gate": False,
            })
            write_json(config, payload)
            result = frozen.validate_config(config)

        self.assertEqual(result["profile"], "control-final")
        self.assertEqual(result["candidate_arm"], "both")
        self.assertIsNone(result["transfer_path"])

    def test_control_final_launch_omits_candidate_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = root / "config.json"
            write_json(config, {})
            validated = {
                "profile": "control-final",
                "candidate_arm": "both",
                "require_gate": False,
                "warm_path": root / "warm.bin",
                "pool_path": root / "pool",
                "steps": 12_000_000_000,
                "prefix": "control-final",
                "out_path": root / "runs/control-final",
                "root_path": root,
                "transfer_path": None,
            }
            completed = mock.Mock(returncode=0)
            with (
                mock.patch.object(frozen, "validate_config", return_value=validated),
                mock.patch.object(frozen.subprocess, "run", return_value=completed)
                as run,
            ):
                self.assertEqual(frozen.main(["--config", str(config)]), 0)

        environment = run.call_args.kwargs["env"]
        self.assertNotIn("CANDIDATE_ARM", environment)
        self.assertNotIn("TRANSFER_COMPLETE", environment)
        self.assertNotIn("EXPECTED_TRANSFER_SHA256", environment)
        self.assertEqual(environment["SCREEN_PROFILE"], "control-final")


if __name__ == "__main__":
    unittest.main()
