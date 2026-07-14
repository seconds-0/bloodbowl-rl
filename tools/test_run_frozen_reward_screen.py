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


if __name__ == "__main__":
    unittest.main()
