#!/usr/bin/env python
"""Tests for training/human_prior.py and analysis/human_prior_audit.py.

The policy class comes from the play harness checkout; tests that need it are
skipped where that checkout is absent.
"""

import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

import bc_pretrain
import human_prior as hp

sys.path.insert(0, os.path.join(hp.ROOT, "analysis"))
import human_prior_audit as audit  # noqa: E402

HARNESS = os.environ.get("BB_PLAY_HARNESS", hp.DEFAULT_HARNESS)
HAVE_HARNESS = os.path.isdir(os.path.join(HARNESS, "play_harness"))
OBS, MASK = 2782, sum(hp.ACT_SIZES)


def write_shard(path, replay_id, count, magic=b"BBP1", stamps=None, seed=0):
    """A shard of END_TURN decisions with ACTIVATE also legal."""
    rng = np.random.default_rng(seed + replay_id)
    records = np.zeros(count, dtype=bc_pretrain.rec_dtype(OBS, MASK))
    records["replay"] = replay_id
    records["cmd"] = np.arange(count)
    records["obs"] = rng.integers(0, 4, size=(count, OBS), dtype=np.uint8)
    records["obs"][:, hp.OBS_HALF] = 1
    records["obs"][:, hp.OBS_MY_TURN] = 3
    records["mask"][:, hp.T["ACTIVATE"]] = 1
    records["mask"][:, hp.T["END_TURN"]] = 1
    records["mask"][:, 30 + 32] = 1
    records["mask"][:, 63 + 390] = 1
    records["type"], records["arg"], records["sq"] = hp.T["END_TURN"], 32, 390
    if magic == b"BBR1":
        records["pad"][:, 0] = 1
        records["pad"][:, 2] = np.asarray(stamps, dtype=np.uint8)
    with open(path, "wb") as f:
        f.write(struct.pack("<4sIII", magic, 4, OBS, MASK))
        f.write(records.tobytes())


class FamilyAndSplitTests(unittest.TestCase):
    def test_declarations_are_filed_by_kind(self):
        t, k = hp.T, hp.K
        got = hp.action_family(
            [t["DECLARE"], t["DECLARE"], t["DECLARE"], t["DECLARE"], t["DECLARE"],
             t["DECLARE"], t["DECLARE"], t["STEP"], t["BLOCK_TARGET"], t["CHOOSE_DIE"],
             t["END_TURN"], t["SETUP_PLACE"], t["PASS_TARGET"], t["FOUL_TARGET"],
             t["HANDOFF_TARGET"], t["ACTIVATE"], t["APOTHECARY"]],
            [k["MOVE"], k["BLOCK"], k["BLITZ"], k["PASS"], k["HANDOFF"], k["FOUL"],
             k["STAB"], 32, 32, 1, 32, 3, 32, 32, 32, 5, 1])
        names = [hp.FAMILIES[i] for i in got]
        self.assertEqual(names, [
            "declare_move", "declare_block", "declare_blitz", "pass", "handoff",
            "foul", "declare_other", "move", "block_target", "block_die",
            "end_turn", "setup", "pass", "foul", "handoff", "activate", "other"])

    def test_turn_bands(self):
        self.assertEqual(list(hp.turn_band([0, 1, 2, 3, 4, 5, 8])),
                         [0, 1, 1, 2, 2, 3, 3])

    def test_holdout_split_is_fixed_disjoint_and_nested(self):
        ids = range(1000, 1399)
        order_a, hold_a = hp.holdout_split(ids)
        order_b, hold_b = hp.holdout_split(reversed(list(ids)))
        self.assertEqual((order_a, hold_a), (order_b, hold_b))
        self.assertEqual(len(hold_a), 60)
        self.assertEqual(len(order_a), 339)
        self.assertFalse(set(order_a) & set(hold_a))
        self.assertEqual(set(order_a) | set(hold_a), set(ids))
        self.assertTrue(set(order_a[:100]) < set(order_a[:200]))
        with self.assertRaises(SystemExit):
            hp.holdout_split(range(60))

    def test_cluster_interval_brackets_the_mean(self):
        values = np.r_[np.zeros(50), np.ones(50)]
        got = hp.cluster_interval(values, np.arange(100) // 10)
        self.assertAlmostEqual(got["mean"], 0.5)
        self.assertTrue(got["lo"] < 0.5 < got["hi"])
        self.assertEqual(got["clusters"], 10)


class SupportTests(unittest.TestCase):
    def random_support(self, rng, n_tuples):
        tuples = set()
        while len(tuples) < n_tuples:
            tuples.add((int(rng.integers(0, 4)), int(rng.integers(0, 5)),
                        int(rng.integers(0, 6))))
        return np.asarray([t | (a << 10) | (s << 20) for t, a, s in sorted(tuples)],
                          dtype=np.uint32)

    def test_joint_is_a_distribution_and_kl_behaves(self):
        rng = np.random.default_rng(0)
        supports = [self.random_support(rng, n) for n in (1, 7, 30)]
        offsets = np.r_[0, np.cumsum([len(s) for s in supports])]
        sup = audit.Support(np.concatenate(supports), offsets)
        logits_p = rng.normal(size=(3, MASK)) * 3
        logits_q = rng.normal(size=(3, MASK)) * 3
        lp, lq = sup.joint_logp(logits_p), sup.joint_logp(logits_q)
        np.testing.assert_allclose(sup.mass(lp, np.ones(len(lp), dtype=bool)), 1.0)
        np.testing.assert_allclose(sup.kl(lp, lp), 0.0, atol=1e-12)
        self.assertTrue(np.all(sup.kl(lp, lq)[1:] > 0))
        self.assertEqual(sup.kl(lp, lq)[0], 0.0)      # a forced decision
        np.testing.assert_allclose(sup.family_mass(lp).sum(axis=1), 1.0)

    @unittest.skipUnless(HAVE_HARNESS, "play harness checkout not found")
    def test_joint_matches_the_harness_sampler(self):
        policy_mod = hp.load_harness(HARNESS)
        rng = np.random.default_rng(1)
        for _ in range(20):
            support = self.random_support(rng, int(rng.integers(1, 40)))
            logits = (rng.normal(size=MASK) * 2).astype(np.float32)
            sup = audit.Support(support, np.array([0, len(support)]))
            lp = sup.joint_logp(logits[None])
            action, logprob, _masks = policy_mod.select_joint(
                torch.from_numpy(logits), support, mode="argmax")
            idx = np.flatnonzero((sup.type == action[0]) & (sup.arg == action[1])
                                 & (sup.sq == action[2]))[0]
            self.assertAlmostEqual(float(lp[idx]), logprob, places=4)

    def test_a_duplicated_tuple_carries_mass_once(self):
        packed = np.asarray([21 | (1 << 10), 21 | (1 << 10), 21 | (1 << 10) | (26 << 20)])
        sup = audit.Support(packed, np.array([0, 3]))
        self.assertEqual(sup.duplicates, 1)
        lp = sup.joint_logp(np.zeros((1, MASK)))
        np.testing.assert_allclose(np.exp(lp), [0.5, 0.5])

    def test_context_name(self):
        bits = (1 << hp.T["ACTIVATE"]) | (1 << hp.T["END_TURN"])
        self.assertEqual(audit.context_name(bits), "ACTIVATE|END_TURN")

    def test_ratio_interval(self):
        got = audit.ratio_interval(np.full(40, 0.6), np.full(40, 0.2), np.arange(40) // 4)
        self.assertAlmostEqual(got["value"], 3.0)
        self.assertAlmostEqual(got["lo"], 3.0)
        self.assertIsNone(audit.ratio_interval(np.zeros(0), np.zeros(0), np.zeros(0)))


class TurnShapeTests(unittest.TestCase):
    def test_one_turn_is_read_the_way_the_report_says(self):
        t, k = hp.T, hp.K
        turn_level = (1 << t["ACTIVATE"]) | (1 << t["END_TURN"])
        declare = 1 << t["DECLARE"]
        block_ctx = (1 << t["BLOCK_TARGET"]) | (1 << t["END_ACTIVATION"])
        move_ctx = (1 << t["STEP"]) | (1 << t["END_ACTIVATION"])
        # (legal types, type, arg, declared kind + 1)
        rows = [
            (turn_level, t["ACTIVATE"], 3, 0),
            (declare, t["DECLARE"], k["BLOCK"], 0),
            (block_ctx, t["END_ACTIVATION"], 32, k["BLOCK"] + 1),   # declared, not thrown
            (turn_level, t["ACTIVATE"], 4, 0),
            (declare, t["DECLARE"], k["BLOCK"], 0),
            (block_ctx, t["BLOCK_TARGET"], 32, k["BLOCK"] + 1),     # thrown
            (turn_level, t["ACTIVATE"], 5, 0),
            (declare, t["DECLARE"], k["MOVE"], 0),
            (move_ctx, t["STEP"], 32, k["MOVE"] + 1),
            (move_ctx, t["END_ACTIVATION"], 32, k["MOVE"] + 1),
            (turn_level, t["END_TURN"], 32, 0),
        ]
        n = len(rows)
        st = {
            "cluster": np.zeros(n, dtype=np.int64),
            # The last declaration's successor is NOT verified.
            "next_ok": np.asarray([True] * 7 + [False] + [True] * 2 + [False]),
            "seat": np.zeros(n, dtype=np.int64),
            "turn_key": np.full(n, 77), "turn": np.full(n, 2),
            "whole": np.ones(n, dtype=bool),
            "type": np.asarray([r[1] for r in rows]), "arg": np.asarray([r[2] for r in rows]),
            "act_kind": np.asarray([r[3] for r in rows]),
            "legal_types": np.asarray([r[0] for r in rows]),
            "legal_block": np.asarray([r[0] == declare and r[2] == k["BLOCK"] for r in rows]),
        }
        got = audit.turn_shape(st, {"net": np.linspace(0.0, 1.0, n)})
        self.assertEqual(got["D1"]["n"], 2)
        self.assertAlmostEqual(got["D1"]["ended_without_blocking"]["value"], 0.5)
        self.assertEqual(got["D2"]["BLOCK"]["with_verified_next_decision"], 2)
        self.assertAlmostEqual(got["D2"]["BLOCK"]["ended_at_once"]["value"], 0.5)
        self.assertEqual(got["D2"]["MOVE"]["declarations"], 1)
        self.assertEqual(got["D2"]["MOVE"]["with_verified_next_decision"], 0)
        self.assertIsNone(got["D2"]["MOVE"]["ended_at_once"])
        whole = got["D3_whole_turns"]
        self.assertEqual(whole["team_turns"], 1)
        self.assertEqual(whole["declarations_per_turn"], 3.0)
        self.assertEqual(whole["ended_by_choice_with_a_player_left"], 1.0)
        self.assertEqual(whole["block_declared_per_turn"], 2.0)
        self.assertEqual(whole["block_targets_chosen_per_turn_block_action"], 1.0)
        self.assertEqual(got["D3_other_rows"]["team_turns"], 0)
        by_depth = {r["depth"]: r for r in got["D5_end_turn_by_depth"]}
        self.assertEqual([by_depth[d]["n"] for d in ("0", "1", "2", "3")], [1, 1, 1, 1])
        self.assertEqual(by_depth["3"]["ended_turn"], 1.0)
        self.assertEqual(by_depth["0"]["ended_turn"], 0.0)
        self.assertAlmostEqual(by_depth["3"]["net"], 1.0)


class DumpCheckTests(unittest.TestCase):
    def test_a_dump_must_match_its_manifest_and_the_loaded_checkpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            np.savez(os.path.join(tmp, "chunk_0000.npz"), action=np.zeros((3, 3)))
            manifest = {"chunks": 1, "decisions": 3, "games": 1,
                        "records": [{"natural": True}],
                        "actor": {"checkpoint_sha256": "a"},
                        "shadows": {"chain9": {"checkpoint_sha256": "b"}}}
            shas = {"chain41": "a", "chain9": "b"}
            audit.check_dump(tmp, manifest, shas)
            with self.assertRaises(SystemExit):      # another acting checkpoint
                audit.check_dump(tmp, manifest, {"chain41": "x", "chain9": "b"})
            with self.assertRaises(SystemExit):      # decisions do not add up
                audit.check_dump(tmp, dict(manifest, decisions=4), shas)
            with self.assertRaises(SystemExit):      # content changed since the dump
                audit.check_dump(tmp, dict(manifest, chunk_files=[
                    {"name": "chunk_0000.npz", "sha256": "0" * 64}]), shas)
            np.savez(os.path.join(tmp, "chunk_0001.npz"), action=np.zeros((1, 3)))
            with self.assertRaises(SystemExit):      # a stale chunk from another run
                audit.check_dump(tmp, manifest, shas)


class WindowTests(unittest.TestCase):
    def test_windows_never_cross_a_hole_a_segment_or_a_coach(self):
        import human_prior_seq as seq
        with tempfile.TemporaryDirectory() as tmp:
            pairs, reseat = Path(tmp) / "pairs", Path(tmp) / "pairs_reseat"
            pairs.mkdir()
            reseat.mkdir()
            write_shard(pairs / "9.bbp", 9, 5)
            # Stamps: rows 0-2 admitted, row 3 filtered out, rows 4-6 admitted.
            write_shard(reseat / "9.bbr", 9, 7, magic=b"BBR1",
                        stamps=[1, 1, 1, 0, 1, 1, 1])
            # Second coach decides at prefix row 2; a new segment starts at
            # re-seated row 5.
            for path, row, field, value in (
                    (pairs / "9.bbp", 2, "agent", 1),
                    (reseat / "9.bbr", 5, "pad", (2, 0, 1)),
                    (reseat / "9.bbr", 6, "pad", (2, 0, 1))):
                dtype = bc_pretrain.rec_dtype(OBS, MASK)
                data = np.memmap(path, dtype=dtype, mode="r+", offset=16)
                data[field][row] = value
                data.flush()
                del data
            with bc_pretrain.ShardIndex.from_directory(
                    pairs, reseat_dir=reseat) as index:
                windows = seq.build_windows(index, [9], seq_len=3)
            got = sorted((prov, [int(i) for i in local]) for _r, prov, local in windows)
            self.assertEqual(got, [
                ("prefix", [0, 1, 3]), ("prefix", [2]), ("prefix", [4]),
                # Admitted re-seated rows are local 0-5 = physical 0,1,2,4,5,6.
                ("reseat", [0, 1, 2]), ("reseat", [3]), ("reseat", [4, 5])])


@unittest.skipUnless(HAVE_HARNESS, "play harness checkout not found")
class PriorPolicyTests(unittest.TestCase):
    def test_bias_free_policy_stays_bias_free_and_exports_exactly(self):
        policy_mod = hp.load_harness(HARNESS)
        policy = hp.new_policy(policy_mod, bias_free=True, seed=3)
        opt = torch.optim.AdamW([p for p in policy.parameters() if p.requires_grad], lr=1e-2)
        obs = torch.randint(0, 255, (8, OBS), dtype=torch.uint8)
        for _ in range(3):
            loss = hp.forward_logits(policy, obs, grad=True).logsumexp(dim=1).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
        for name, param in policy.named_parameters():
            if name.endswith(".bias"):
                self.assertEqual(float(param.abs().max()), 0.0, name)
        self.assertEqual(float(policy.decoder.value_function.weight.abs().max()), 0.0)
        policy.eval()
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "prior.bin")
            info = hp.native_export(policy, path, "test")
            self.assertEqual(info["max_abs_bias_dropped"], 0.0)
            loaded, _prov = policy_mod.load_checkpoint(path)
            want = hp.forward_logits(policy, obs)
            got = hp.forward_logits(loaded, obs)
            self.assertEqual(float((want - got).abs().max()), 0.0)

    def test_scores_use_the_record_masks(self):
        policy_mod = hp.load_harness(HARNESS)
        policy = hp.new_policy(policy_mod, seed=0).eval()
        with tempfile.TemporaryDirectory() as tmp:
            write_shard(Path(tmp) / "7.bbp", 7, 5)
            with bc_pretrain.ShardIndex.from_directory(tmp) as index:
                data = bc_pretrain.LazyReplayDataset(index, [7])
                s = hp.collect(policy, data, keep_probs=True)
        self.assertEqual(list(s["nlegal0"]), [2] * 5)
        self.assertEqual(list(s["nlegal1"]), [1] * 5)
        np.testing.assert_allclose(s["lp1"], 0.0)
        np.testing.assert_allclose(s["lp2"], 0.0)
        np.testing.assert_allclose(s["p_type"].sum(axis=1), 1.0, rtol=1e-5)
        legal = s["p_type"][:, [hp.T["ACTIVATE"], hp.T["END_TURN"]]].sum(axis=1)
        np.testing.assert_allclose(legal, 1.0, rtol=1e-5)
        self.assertEqual([hp.FAMILIES[i] for i in s["family"]], ["end_turn"] * 5)
        summary = hp.breakdown(s)
        self.assertEqual(summary["overall"]["n"], 5)
        self.assertEqual(summary["by_turn_band"]["3-4"]["n"], 5)

    def test_cli_default_reads_no_reseated_record(self):
        """The script's default subset is prefix only; asked for re-seats it
        admits stamp 1 only; and it never trains on a held-out replay."""
        with tempfile.TemporaryDirectory() as tmp:
            pairs, reseat = Path(tmp) / "pairs", Path(tmp) / "pairs_reseat"
            pairs.mkdir()
            reseat.mkdir()
            ids = list(range(500, 566))
            for rid in ids:
                write_shard(pairs / f"{rid}.bbp", rid, 2)
                write_shard(reseat / f"{rid}.bbr", rid, 3, magic=b"BBR1",
                            stamps=[1, 0, 2])
            (Path(tmp) / "ids.txt").write_text("\n".join(str(i) for i in ids))
            common = ["--pairs-dir", str(pairs), "--replay-ids", str(Path(tmp) / "ids.txt"),
                      "--harness-root", HARNESS, "--epochs", "1", "--batch-size", "8",
                      "--threads", "1"]
            plain = hp.main(common + ["--out-dir", str(Path(tmp) / "a")])
            self.assertIn("prefix records only", plain["subset"])
            self.assertEqual(plain["train"]["records"], {"prefix": 12, "reseat": 0})
            self.assertEqual(list(plain["eval"]), ["prefix"])
            scored = hp.main(common + ["--out-dir", str(Path(tmp) / "c"),
                                       "--eval-reseat-dir", str(reseat)])
            # Scoring on re-seated held-out records does not train on any.
            self.assertIn("prefix records only", scored["subset"])
            self.assertEqual(scored["train"]["records"], {"prefix": 12, "reseat": 0})
            self.assertEqual(scored["eval"]["prefix+closed_equal"]["records"],
                             {"prefix": 120, "reseat": 60})
            narrow = hp.main(common + ["--out-dir", str(Path(tmp) / "d"),
                                       "--reseat-dir", str(reseat)])
            # Held-out scoring widens to every stamp only when asked by name.
            self.assertEqual(list(narrow["eval"]), ["prefix", "prefix+closed_equal"])
            asked = hp.main(common + ["--out-dir", str(Path(tmp) / "b"),
                                      "--reseat-dir", str(reseat), "--eval-all-stamps"])
            self.assertIn("closed equal", asked["subset"])
            self.assertEqual(asked["reseat_stamps"], (1,))
            self.assertEqual(asked["train"]["records"], {"prefix": 12, "reseat": 6})
            self.assertEqual(asked["eval"]["everything"]["records"],
                             {"prefix": 120, "reseat": 180})
            self.assertEqual(asked["eval"]["prefix+closed_equal"]["records"],
                             {"prefix": 120, "reseat": 60})
            _order, holdout = hp.holdout_split(ids)
            self.assertEqual(asked["holdout"]["ids"], list(holdout))
            self.assertEqual(asked["train"]["replays"], 6)
            saved = json.load(open(Path(tmp) / "b" / "result.json"))
            self.assertIn("closed equal", saved["subset"])
            self.assertTrue(os.path.exists(Path(tmp) / "b" / "prior.bin"))


if __name__ == "__main__":
    unittest.main()
