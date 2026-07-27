#!/usr/bin/env python3

import sys
import unittest
from pathlib import Path
from unittest import mock

TRAINING = Path(__file__).resolve().parent
sys.path.insert(0, str(TRAINING))

import bc_context  # noqa: E402


class ContextLineageEntryPointTests(unittest.TestCase):
    def run_until_load(self, *extra_args):
        argv = [
            "bc_context.py",
            "--pairs-dir",
            "/sentinel/pairs",
            *extra_args,
        ]
        with mock.patch.object(sys, "argv", argv), mock.patch.object(
                bc_context.bc_pretrain,
                "load_shards",
                side_effect=RuntimeError("stop after lineage call"),
        ) as load:
            with self.assertRaisesRegex(
                    RuntimeError, "stop after lineage call"):
                bc_context.main()
        return load

    def test_current_context_path_rejects_legacy_by_default(self):
        load = self.run_until_load()
        load.assert_called_once_with(
            "/sentinel/pairs", replay_ids=None, allow_legacy=False)

    def test_legacy_context_loading_requires_explicit_flag(self):
        load = self.run_until_load("--allow-legacy-bbp")
        load.assert_called_once_with(
            "/sentinel/pairs", replay_ids=None, allow_legacy=True)


if __name__ == "__main__":
    unittest.main()
