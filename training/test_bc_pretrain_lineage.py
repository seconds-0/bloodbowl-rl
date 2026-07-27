#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from unittest import mock

TRAINING = Path(__file__).resolve().parent
sys.path.insert(0, str(TRAINING))

import bc_pretrain  # noqa: E402


class PretrainLineageEntryPointTests(unittest.TestCase):
    def run_until_lineage_gate(self, *extra_args):
        argv = [
            "bc_pretrain.py",
            "--pairs-dir",
            "/sentinel/pairs",
            "--steps",
            "1",
            "--device",
            "cpu",
            *extra_args,
        ]
        index = mock.MagicMock()
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
                bc_pretrain.ShardIndex,
                "from_directory",
                return_value=index,
        ), mock.patch.object(
                bc_pretrain,
                "require_exact_action_lineage",
                side_effect=RuntimeError("stop after lineage gate"),
        ) as gate:
            with self.assertRaisesRegex(
                    RuntimeError, "stop after lineage gate"):
                bc_pretrain.main()
        index.close.assert_called_once_with()
        return gate, index

    def test_current_cli_rejects_legacy_by_default(self):
        gate, index = self.run_until_lineage_gate()
        gate.assert_called_once_with(index, False)

    def test_legacy_cli_loading_requires_explicit_flag(self):
        gate, index = self.run_until_lineage_gate("--allow-legacy-bbp")
        gate.assert_called_once_with(index, True)


if __name__ == "__main__":
    unittest.main()
