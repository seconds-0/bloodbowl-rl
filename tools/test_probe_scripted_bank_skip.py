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
APB, BUFFERS, T, MASK_WIDTH = 8, 2, 3, 7


def config(tag=2, scripted=1, team=1, banks=2):
    return {"env_name": "bloodbowl",
            "env": {"scripted_opponent": scripted, "scripted_opponent_team": team,
                    "scripted_bank_tag": tag},
            "vec": {"num_frozen_banks": banks}}


def arrays(seed=0):
    rng = np.random.default_rng(seed)
    total = APB * BUFFERS
    # env_mask models the env's marginal mask (pufferlib.cu casts it into every
    # row); action_mask models what sample_logits leaves behind, the support
    # conditioned on earlier heads. That is NOT a subset of the marginal mask:
    # the exact-joint support carries values the marginal never marks (mostly
    # the virtual arg 32, measured on the rig on 2026-09-15). Bit MASK_WIDTH-1
    # plays that value here.
    env_mask = (rng.random((T, total, MASK_WIDTH)) < 0.7).astype(np.float32)
    env_mask[..., 0] = 1.0
    env_mask[..., MASK_WIDTH - 1] = 0.0
    conditional = env_mask * (rng.random((T, total, MASK_WIDTH)) < 0.4)
    conditional[..., 0] = 1.0
    conditional[..., MASK_WIDTH - 1] = (rng.random((T, total)) < 0.3).astype(np.float32)
    return {
        "observations": rng.random((T, total, 5), dtype=np.float32),
        "rewards": rng.random((T, total), dtype=np.float32),
        "terminals": np.zeros((T, total), dtype=np.float32),
        "action_mask": conditional.astype(np.float32),
        "env_mask": env_mask,
        "actions": rng.integers(1, 5, (T, total, 3)).astype(np.float32),
        "logprobs": rng.random((T, total), dtype=np.float32) - 1.0,
        "values": rng.random((T, total), dtype=np.float32) + 0.5,
    }


def zero_bank(data, bank):
    """What the skip build leaves: zero actions/logprobs/values, and the env's
    marginal mask, because the skipped slice never reaches sample_logits."""
    data = {k: v.copy() for k, v in data.items()}
    for start, end in probe.bank_row_slices(LAYOUT, APB, BUFFERS)[bank]:
        for key in probe.PER_BANK:
            data[key][:, start:end] = 0.0
        data["action_mask"][:, start:end] = data["env_mask"][:, start:end]
    return data


def trace(data_per_rollout, skip_bank=0, binding=False, routed=False, cfg=None):
    cfg = cfg or config()
    scripted = probe.expected_skip_bank(cfg)
    return {
        "schema_version": probe.SCHEMA_VERSION, "config": cfg,
        "bank_layout": LAYOUT, "agents_per_buffer": APB, "num_buffers": BUFFERS,
        "requested_rollouts": len(data_per_rollout),
        "skip": {"bank": skip_bank, "binding": binding, "routed": routed},
        "rollouts": [probe.rollout_record(d, LAYOUT, APB, BUFFERS, scripted)
                     for d in data_per_rollout],
        "env": {"tds": 1.0, "n": 12.0},
        "hard_integrity": {"zero": True, "counters": {}},
    }


def slice_mask(data, bank):
    return np.concatenate([data["action_mask"][:, s:e] for s, e in
                           probe.bank_row_slices(LAYOUT, APB, BUFFERS)[bank]], axis=1)


def mask_row_differences(candidate_runs, baseline_runs, bank):
    """Reference (widened, narrowed) (step, row) counts over every rollout."""
    widened = narrowed = 0
    for cand, base in zip(candidate_runs, baseline_runs):
        c, b = slice_mask(cand, bank) != 0, slice_mask(base, bank) != 0
        widened += int(np.count_nonzero(np.any(c & ~b, axis=-1)))
        narrowed += int(np.count_nonzero(np.any(b & ~c, axis=-1)))
    return widened, narrowed


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

    def test_record_digests_masks_per_bank_not_across_rows(self):
        base = arrays()
        changed = {k: v.copy() for k, v in base.items()}
        changed["action_mask"][2, 7, 3] = 1.0 - changed["action_mask"][2, 7, 3]  # bank 2
        a = probe.rollout_record(base, LAYOUT, APB, BUFFERS, 2)
        b = probe.rollout_record(changed, LAYOUT, APB, BUFFERS, 2)
        self.assertNotIn("action_mask", a["all_rows"])
        self.assertEqual(a["all_rows"], b["all_rows"])
        self.assertEqual([x["action_mask"] == y["action_mask"]
                          for x, y in zip(a["banks"], b["banks"])], [True, True, False])
        self.assertTrue(all(x["action_mask_binary"] for x in a["banks"]))
        self.assertEqual(a["scripted_mask"]["bank"], 2)
        self.assertEqual(a["scripted_mask"]["shape"], [T, 4, MASK_WIDTH])
        np.testing.assert_array_equal(probe.unpack_mask(a["scripted_mask"]),
                                      slice_mask(base, 2) != 0)
        self.assertNotIn("scripted_mask", probe.rollout_record(base, LAYOUT, APB, BUFFERS))
        for bad in (3, -1):
            with self.assertRaisesRegex(probe.ProbeError, "not a frozen bank"):
                probe.rollout_record(base, LAYOUT, APB, BUFFERS, bad)
        fractional = {k: v.copy() for k, v in base.items()}
        fractional["action_mask"][0, 12, 1] = 0.5  # buffer 1, frozen bank 0
        record = probe.rollout_record(fractional, LAYOUT, APB, BUFFERS, 2)
        self.assertEqual([x["action_mask_binary"] for x in record["banks"]], [True, False, True])

    def test_mask_bits_round_trip_and_refuse_corruption(self):
        rng = np.random.default_rng(7)
        array = (rng.random((5, 11, 13)) < 0.3).astype(np.float32)
        record = probe.pack_mask(array, [(0, 3), (6, 11)])
        expected = np.concatenate([array[:, 0:3], array[:, 6:11]], axis=1) != 0
        np.testing.assert_array_equal(probe.unpack_mask(record), expected)
        with self.assertRaisesRegex(probe.ProbeError, "bytes for shape"):
            probe.unpack_mask({**record, "shape": [5, 8, 14]})
        with self.assertRaisesRegex(probe.ProbeError, "malformed"):
            probe.unpack_mask({**record, "bits": "bm90IHpsaWI="})

    def test_candidate_with_skipped_bank_is_accepted(self):
        runs = [arrays(i) for i in range(3)]
        baseline = trace(runs)
        candidate = trace([zero_bank(d, 2) for d in runs], skip_bank=2, binding=True, routed=True)
        verdict = probe.compare_traces(baseline, candidate)
        widened = verdict.pop("skipped_mask_rows_widened")
        narrowed = verdict.pop("skipped_mask_rows_narrowed")
        self.assertEqual(verdict, {"accepted": True, "rollouts": 3, "skip_bank": 2,
                                   "identical_banks": [0, 1]})
        expected_widened, expected_narrowed = mask_row_differences(
            [zero_bank(d, 2) for d in runs], runs, 2)
        self.assertGreater(expected_widened, 0)
        self.assertGreater(expected_narrowed, 0)
        self.assertEqual((widened, narrowed), (expected_widened, expected_narrowed))

    def test_skipped_slice_mask_differences_are_counted_not_refused(self):
        runs = [arrays(i) for i in range(2)]
        baseline = trace(runs)
        good = [zero_bank(d, 2) for d in runs]
        rows = probe.bank_row_slices(LAYOUT, APB, BUFFERS)[2]
        # A skipped row missing a bit the baseline's conditional support holds
        # is what the rig measured (virtual arg/square values); it is counted.
        narrowed = copy.deepcopy(good)
        row = rows[1][0]  # buffer 1, first scripted row
        bit = int(np.flatnonzero(runs[1]["action_mask"][2, row])[0])
        narrowed[1]["action_mask"][2, row, bit] = 0.0
        verdict = probe.compare_traces(
            baseline, trace(narrowed, skip_bank=2, binding=True, routed=True))
        self.assertTrue(verdict["accepted"])
        self.assertEqual(
            (verdict["skipped_mask_rows_widened"], verdict["skipped_mask_rows_narrowed"]),
            mask_row_differences(narrowed, runs, 2))
        good_narrowed = mask_row_differences(good, runs, 2)[1]
        self.assertGreaterEqual(verdict["skipped_mask_rows_narrowed"], good_narrowed)
        fractional = copy.deepcopy(good)
        fractional[0]["action_mask"][0, rows[0][0], 4] = 0.5
        with self.assertRaisesRegex(probe.ProbeError, "candidate bank 2 action_mask is not binary"):
            probe.compare_traces(baseline, trace(fractional, skip_bank=2, binding=True, routed=True))
        unrecorded = trace(good, skip_bank=2, binding=True, routed=True)
        del unrecorded["rollouts"][0]["scripted_mask"]
        with self.assertRaisesRegex(probe.ProbeError, "candidate lacks bank 2 action_mask bits"):
            probe.compare_traces(baseline, unrecorded)
        stale = copy.deepcopy(baseline)
        stale["rollouts"][1]["scripted_mask"]["bank"] = 1
        with self.assertRaisesRegex(probe.ProbeError, "baseline lacks bank 2 action_mask bits"):
            probe.compare_traces(stale, trace(good, skip_bank=2, binding=True, routed=True))
        reshaped = trace(good, skip_bank=2, binding=True, routed=True)
        reshaped["rollouts"][0]["scripted_mask"] = {
            "bank": 2, **probe.pack_mask(good[0]["action_mask"][:, :, :6], rows)}
        with self.assertRaisesRegex(probe.ProbeError, "action_mask shapes differ"):
            probe.compare_traces(baseline, reshaped)

    def test_default_build_control_requires_every_bank_identical(self):
        runs = [arrays(i) for i in range(2)]
        verdict = probe.compare_traces(trace(runs), trace(copy.deepcopy(runs)))
        self.assertEqual(verdict["identical_banks"], [0, 1, 2])
        self.assertEqual(verdict["skipped_mask_rows_widened"], 0)
        self.assertEqual(verdict["skipped_mask_rows_narrowed"], 0)
        drifted = copy.deepcopy(runs)
        drifted[1]["logprobs"][0, 15] += 1e-6  # the would-be scripted bank
        with self.assertRaisesRegex(probe.ProbeError, "bank 2 logprobs"):
            probe.compare_traces(trace(runs), trace(drifted))
        widened = copy.deepcopy(runs)
        widened[0]["action_mask"][1, 6] = widened[0]["env_mask"][1, 6]
        if np.array_equal(widened[0]["action_mask"][1, 6], runs[0]["action_mask"][1, 6]):
            widened[0]["action_mask"][1, 6, 1:] = 1.0
        with self.assertRaisesRegex(probe.ProbeError, "rollout 0 bank 2 action_mask"):
            probe.compare_traces(trace(runs), trace(widened))

    def test_divergence_outside_the_skipped_bank_is_refused(self):
        runs = [arrays(i) for i in range(2)]
        baseline = trace(runs)
        cases = {
            "bank 1 actions": lambda d: d["actions"].__setitem__((0, 5, 1), 9.0),
            "bank 0 values": lambda d: d["values"].__setitem__((2, 9), 0.25),
            "bank 1 action_mask": lambda d: d["action_mask"].__setitem__(
                (1, 13, 2), 1.0 - d["action_mask"][1, 13, 2]),
            "bank 0 action_mask": lambda d: d["action_mask"].__setitem__(
                (0, 3, 6), 1.0 - d["action_mask"][0, 3, 6]),
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
        old_schema = trace(zeroed, skip_bank=2, binding=True, routed=True)
        old_schema["schema_version"] = 1
        with self.assertRaisesRegex(probe.ProbeError, "schema_version differs"):
            probe.compare_traces(baseline, old_schema)
        dirty = trace(zeroed, skip_bank=2, binding=True, routed=True)
        dirty["hard_integrity"] = {"zero": False, "error": "nonzero: x=1"}
        with self.assertRaisesRegex(probe.ProbeError, "candidate hard integrity not zero"):
            probe.compare_traces(baseline, dirty)
        unlogged = dict(baseline)
        del unlogged["hard_integrity"]
        with self.assertRaisesRegex(probe.ProbeError, "baseline hard integrity not zero"):
            probe.compare_traces(unlogged, trace(zeroed, skip_bank=2, binding=True, routed=True))

    def test_integrity_verdict_records_instead_of_raising(self):
        from qualify_recurrent_cuda import HARD_INTEGRITY_KEYS
        clean = probe.integrity_verdict({key: 0.0 for key in HARD_INTEGRITY_KEYS})
        self.assertTrue(clean["zero"])
        self.assertEqual(len(clean["counters"]), len(HARD_INTEGRITY_KEYS))
        missing = probe.integrity_verdict({})
        self.assertFalse(missing["zero"])
        self.assertIn("missing", missing["error"])
        key = HARD_INTEGRITY_KEYS[0]
        nonzero = probe.integrity_verdict({**{k: 0.0 for k in HARD_INTEGRITY_KEYS}, key: 2.0})
        self.assertFalse(nonzero["zero"])
        self.assertIn("nonzero", nonzero["error"])

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

    def test_single_gpu_args_match_what_train_sets_before_create(self):
        # pufferl.train() sets these before _train; create_pufferl reads
        # args["nccl_id"], rank, world_size and gpu_id and fails without them.
        args = probe.single_gpu_args({"train": {"gpus": 1}})
        self.assertEqual((args["world_size"], args["nccl_id"], args["rank"], args["gpu_id"]),
                         (1, "", 0, 0))
        with self.assertRaises(probe.ProbeError):
            probe.single_gpu_args({"train": {"gpus": 2}})

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
