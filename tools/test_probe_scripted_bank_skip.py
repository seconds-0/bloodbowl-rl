#!/usr/bin/env python3
"""Pure logic of tools/probe_scripted_bank_skip.py (the CUDA paths run on the rig)."""

from __future__ import annotations

import copy
import pathlib
import sys
import unittest

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import probe_scripted_bank_skip as probe  # noqa: E402

LAYOUT = [0, 4, 6, 8]  # primary, frozen bank 0 (tag 1), frozen bank 1 (tag 2)
APB, BUFFERS, T = 8, 2, 3


def config(tag=2, scripted=1, team=1, banks=2):
    return {"env_name": "bloodbowl",
            "env": {"scripted_opponent": scripted, "scripted_opponent_team": team,
                    "scripted_bank_tag": tag},
            "vec": {"num_frozen_banks": banks}}


def arrays(seed=0):
    rng = np.random.default_rng(seed)
    total = APB * BUFFERS
    return {
        "observations": rng.random((T, total, 5), dtype=np.float32),
        "rewards": rng.random((T, total), dtype=np.float32),
        "terminals": np.zeros((T, total), dtype=np.float32),
        "action_mask": np.ones((T, total, 7), dtype=np.float32),
        "actions": rng.integers(1, 5, (T, total, 3)).astype(np.float32),
        "logprobs": rng.random((T, total), dtype=np.float32) - 1.0,
        "values": rng.random((T, total), dtype=np.float32) + 0.5,
    }


def zero_bank(data, bank):
    data = {k: v.copy() for k, v in data.items()}
    for start, end in probe.bank_row_slices(LAYOUT, APB, BUFFERS)[bank]:
        for key in probe.PER_BANK:
            data[key][:, start:end] = 0.0
    return data


def trace(data_per_rollout, skip_bank=0, binding=False, routed=False, cfg=None):
    return {
        "schema_version": probe.SCHEMA_VERSION, "config": cfg or config(),
        "bank_layout": LAYOUT, "agents_per_buffer": APB, "num_buffers": BUFFERS,
        "requested_rollouts": len(data_per_rollout),
        "skip": {"bank": skip_bank, "binding": binding, "routed": routed},
        "rollouts": [probe.rollout_record(d, LAYOUT, APB, BUFFERS) for d in data_per_rollout],
        "env": {"tds": 1.0, "n": 12.0},
    }


class ProbeLogicTests(unittest.TestCase):
    def test_bank_slices_cover_every_buffer_chunk(self):
        slices = probe.bank_row_slices(LAYOUT, APB, BUFFERS)
        self.assertEqual(slices, [[(0, 4), (8, 12)], [(4, 6), (12, 14)], [(6, 8), (14, 16)]])
        for bad in ([1, 4, 8], [0, 4, 7], [0, 6, 4, 8], [0]):
            with self.assertRaises(probe.ProbeError):
                probe.bank_row_slices(bad, APB, BUFFERS)

    def test_record_isolates_bank_digests(self):
        base = arrays()
        changed = {k: v.copy() for k, v in base.items()}
        changed["actions"][1, 13, 0] += 1.0  # buffer 1, frozen bank 0
        a = probe.rollout_record(base, LAYOUT, APB, BUFFERS)
        b = probe.rollout_record(changed, LAYOUT, APB, BUFFERS)
        self.assertEqual(a["all_rows"], b["all_rows"])
        self.assertEqual([x["actions"] == y["actions"] for x, y in zip(a["banks"], b["banks"])],
                         [True, False, True])
        self.assertEqual([x["rows"] for x in a["banks"]], [8, 4, 4])
        with self.assertRaises(probe.ProbeError):
            probe.rollout_record({**base, "values": base["values"][:, :10]}, LAYOUT, APB, BUFFERS)

    def test_candidate_with_skipped_bank_is_accepted(self):
        runs = [arrays(i) for i in range(3)]
        baseline = trace(runs)
        candidate = trace([zero_bank(d, 2) for d in runs], skip_bank=2, binding=True, routed=True)
        verdict = probe.compare_traces(baseline, candidate)
        self.assertEqual(verdict, {"accepted": True, "rollouts": 3, "skip_bank": 2,
                                   "identical_banks": [0, 1]})

    def test_default_build_control_requires_every_bank_identical(self):
        runs = [arrays(i) for i in range(2)]
        verdict = probe.compare_traces(trace(runs), trace(copy.deepcopy(runs)))
        self.assertEqual(verdict["identical_banks"], [0, 1, 2])
        drifted = copy.deepcopy(runs)
        drifted[1]["logprobs"][0, 15] += 1e-6  # the would-be scripted bank
        with self.assertRaisesRegex(probe.ProbeError, "bank 2 logprobs"):
            probe.compare_traces(trace(runs), trace(drifted))

    def test_divergence_outside_the_skipped_bank_is_refused(self):
        runs = [arrays(i) for i in range(2)]
        baseline = trace(runs)
        cases = {
            "bank 1 actions": lambda d: d["actions"].__setitem__((0, 5, 1), 9.0),
            "bank 0 values": lambda d: d["values"].__setitem__((2, 9), 0.25),
            "all-row digests": lambda d: d["observations"].__setitem__((1, 14, 2), 0.5),
        }
        for label, mutate in cases.items():
            with self.subTest(label):
                data = [zero_bank(d, 2) for d in runs]
                mutate(data[1])
                candidate = trace(data, skip_bank=2, binding=True, routed=True)
                with self.assertRaisesRegex(probe.ProbeError, label):
                    probe.compare_traces(baseline, candidate)

    def test_skip_contract_violations_are_refused(self):
        runs = [arrays(0)]
        baseline = trace(runs)
        zeroed = [zero_bank(runs[0], 2)]
        with self.assertRaisesRegex(probe.ProbeError, "not zero"):
            probe.compare_traces(baseline, trace(runs, skip_bank=2, binding=True, routed=True))
        with self.assertRaisesRegex(probe.ProbeError, "never routing-validated"):
            probe.compare_traces(baseline, trace(zeroed, skip_bank=2, binding=True))
        with self.assertRaisesRegex(probe.ProbeError, "config rule"):
            probe.compare_traces(baseline, trace(zeroed, skip_bank=1, binding=True, routed=True))
        with self.assertRaisesRegex(probe.ProbeError, "without the binding"):
            probe.compare_traces(baseline, trace(zeroed, skip_bank=2))
        with self.assertRaisesRegex(probe.ProbeError, "baseline must be"):
            probe.compare_traces(trace(zeroed, skip_bank=2, binding=True, routed=True),
                                 trace(zeroed, skip_bank=2, binding=True, routed=True))
        blind = trace([zero_bank(runs[0], 2)])
        with self.assertRaisesRegex(probe.ProbeError, "cannot see"):
            probe.compare_traces(blind, trace(zeroed, skip_bank=2, binding=True, routed=True))
        other_env = trace(zeroed, skip_bank=2, binding=True, routed=True)
        other_env["env"]["tds"] = 2.0
        with self.assertRaisesRegex(probe.ProbeError, "env metrics"):
            probe.compare_traces(baseline, other_env)
        other_config = trace(zeroed, skip_bank=2, binding=True, routed=True,
                             cfg=config(banks=3))
        with self.assertRaisesRegex(probe.ProbeError, "config differs"):
            probe.compare_traces(baseline, other_config)

    def test_expected_skip_bank_mirrors_the_patch_rule(self):
        self.assertEqual(probe.expected_skip_bank(config()), 2)
        self.assertEqual(probe.expected_skip_bank(config(scripted=0)), 0)
        self.assertEqual(probe.expected_skip_bank(config(team=0)), 0)
        self.assertEqual(probe.expected_skip_bank(config(tag=0)), 0)
        self.assertEqual(probe.expected_skip_bank(config(tag=3)), 0)
        self.assertEqual(probe.expected_skip_bank({**config(), "env_name": "chess"}), 0)

    def test_cli_splits_overrides_and_validates_modes(self):
        options, overrides = probe.parse_args(
            ["trace", "--puffer-root", "/p", "--output", "o.json", "--rollouts", "3",
             "--", "--vec.total-agents", "512"])
        self.assertEqual((options.command, options.rollouts), ("trace", 3))
        self.assertEqual(overrides, ["--vec.total-agents", "512"])
        for argv in (["trace", "--puffer-root", "/p", "--output", "o"],
                     ["compare", "--baseline", "a", "--candidate", "b", "--", "--x", "1"],
                     ["throughput", "--puffer-root", "/p", "--output", "o", "--seconds", "0",
                      "--", "--x", "1"]):
            with self.assertRaises(SystemExit):
                probe.parse_args(argv)

    def test_per_epoch_split(self):
        perf = {"rollout": 10.0, "eval_gpu": 6.0, "eval_env": 2.0, "train_misc": 0.5,
                "train_forward": 1.5, "train": 2.0}
        split = probe.per_epoch_split(perf, 10)
        self.assertEqual(split["eval_gpu_ms"], 600.0)
        self.assertEqual(split["train_ms"], 200.0)
        with self.assertRaises(probe.ProbeError):
            probe.per_epoch_split(perf, 0)


if __name__ == "__main__":
    unittest.main()
