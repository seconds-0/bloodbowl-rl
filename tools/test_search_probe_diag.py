#!/usr/bin/env python3
"""The statistics of tools/search_probe_diag.py on synthetic returns."""
import unittest

import numpy as np

import search_probe_diag as D


def make_root(game, cls, a0, alts, n=128, noise=0.05, seed=0, shared=0.0):
    """A root whose candidate means are known: row 0 is a0. `shared` is noise
    common to every candidate of a rollout index (what common dice give)."""
    rng = np.random.default_rng(seed)
    common = rng.normal(0.0, shared, n) if shared else np.zeros(n)
    means = np.array([a0] + list(alts))[:, None]
    returns = means + common + rng.normal(0.0, noise, (len(means), n))
    return {"game": game, "class": cls, "returns": returns, "a0_rank": 1,
            "types": ["END_ACTIVATION"] + ["BLOCK_TARGET"] * len(alts)}


class Halves(unittest.TestCase):
    def test_the_two_halves_are_disjoint_and_cover_the_rollouts(self):
        a, b = D.halves(128)
        self.assertEqual((len(a), len(b)), (64, 64))
        self.assertFalse(set(a) & set(b))
        a, b = D.halves(9)
        self.assertEqual((list(a), list(b)), ([0, 1, 2, 3], [4, 5, 6, 7]))

    def test_rejected_rollouts_drop_the_whole_index(self):
        returns = np.arange(12, dtype=float).reshape(3, 4)
        returns[1, 2] = np.nan
        clean = D.clean_returns(returns)
        self.assertEqual(clean.shape, (3, 3))
        self.assertEqual(list(clean[0]), [0.0, 1.0, 3.0])

    def test_paired_gain_is_the_mean_difference_with_its_standard_error(self):
        returns = np.array([[1.0, 2.0, 3.0, 4.0], [1.5, 2.5, 3.5, 4.5], [0.0, 4.0, 2.0, 6.0]])
        mean, se = D.paired_gain(returns, np.arange(4))
        np.testing.assert_allclose(mean, [0.5, 0.5])
        d = np.array([-1.0, 2.0, -1.0, 2.0])
        np.testing.assert_allclose(se, [0.0, d.std(ddof=1) / 2.0])


class Headroom(unittest.TestCase):
    def test_selection_and_judgment_use_different_halves(self):
        # The alternative wins by 1.0 on half A and loses by 1.0 on half B.
        returns = np.zeros((2, 8))
        returns[1, :4], returns[1, 4:] = 1.0, -1.0
        head = D.root_headroom(returns, delta=0.02)
        self.assertEqual((head["gain_a"], head["gain_b"]), (1.0, -1.0))
        self.assertFalse(head["headroom"])
        self.assertEqual(head["rule_gain"], -1.0)      # the rule deviated and paid for it

    def test_a_real_gain_is_found_and_a_null_is_not(self):
        real = D.root_headroom(make_root(0, "turn", 1.0, [1.1, 0.9], seed=1)["returns"])
        self.assertEqual(real["best"], 0)
        self.assertTrue(real["headroom"])
        self.assertAlmostEqual(real["rule_gain"], 0.1, delta=0.03)
        null = D.root_headroom(make_root(0, "turn", 1.0, [1.0, 1.0], seed=2)["returns"])
        self.assertFalse(null["headroom"])

    def test_selection_does_not_bias_the_judged_gain(self):
        """With no true gain anywhere, the best of three on half A looks good on
        half A and averages to nothing on half B."""
        heads = [D.root_headroom(make_root(0, "turn", 1.0, [1.0] * 3, n=32, seed=s)["returns"])
                 for s in range(400)]
        self.assertGreater(np.mean([h["gain_a"] for h in heads]), 0.006)
        self.assertLess(abs(np.mean([h["gain_b"] for h in heads])), 0.004)

    def test_the_rule_plays_a0_below_the_margin(self):
        returns = np.zeros((2, 8))
        returns[1] = 0.01                                # better, but by less than delta
        head = D.root_headroom(returns, delta=0.02)
        self.assertEqual(head["rule_gain"], 0.0)
        self.assertFalse(head["headroom"])


class Rule(unittest.TestCase):
    def test_a_large_gain_is_always_taken_and_never_false(self):
        returns = make_root(0, "turn", 1.0, [1.5], noise=0.02, seed=3)["returns"]
        for floor in (False, True):
            sim = D.simulate_rule(returns, 8, floor=floor, resamples=100)
            self.assertEqual((sim["deviations"], sim["false"]), (100, 0))
            self.assertAlmostEqual(sim["gain"] / 100, 0.5, delta=0.02)

    def test_noise_deviations_are_counted_false_when_half_b_disagrees(self):
        # No true gain; big noise. Deviations happen at n = 8, and about half of the
        # roots have a half-B gain at or below zero.
        false = deviations = 0
        for s in range(200):
            sim = D.simulate_rule(make_root(0, "turn", 1.0, [1.0] * 3, noise=0.3, seed=s)["returns"],
                                  8, resamples=50, rng=np.random.default_rng(s))
            false += sim["false"]
            deviations += sim["deviations"]
        self.assertGreater(deviations, 100)
        self.assertGreater(false / deviations, 0.3)
        self.assertLess(false / deviations, 0.7)

    def test_the_floor_stops_a_constant_small_sample_difference(self):
        """The reviewer's case: a difference of +0.04 nine times in ten and -0.36
        once (mean zero). Eight draws are often all +0.04, with a sample standard
        error of zero. The floor uses the candidates' own spread instead."""
        rng = np.random.default_rng(5)
        base = rng.normal(1.0, 0.2, 128)
        d = np.where(np.arange(128) % 10 == 9, -0.36, 0.04)
        returns = np.stack([base, base + d])
        plain = D.simulate_rule(returns, 8, floor=False, resamples=400)
        floored = D.simulate_rule(returns, 8, floor=True, resamples=400)
        self.assertGreater(plain["deviations"], 100)             # about 0.9 ** 8 of the draws
        self.assertEqual(floored["deviations"], 0)

    def test_n_cannot_exceed_half_a(self):
        with self.assertRaises(ValueError):
            D.simulate_rule(np.zeros((2, 16)), 9)


class Pairing(unittest.TestCase):
    def test_shared_noise_cancels_in_the_paired_difference(self):
        root = make_root(0, "turn", 1.0, [1.0], n=4000, noise=0.05, shared=0.5, seed=7)
        paired, unpaired = D.variance_pairing(root["returns"])
        self.assertAlmostEqual(paired[0], 2 * 0.05 ** 2, delta=0.001)
        self.assertAlmostEqual(unpaired[0], 2 * (0.5 ** 2 + 0.05 ** 2), delta=0.05)


class Bootstrap(unittest.TestCase):
    def test_the_point_is_the_ratio_of_sums(self):
        point, lo, hi, upper = D.ratio_bootstrap([0, 0, 1, 2], [1, 0, 1, 1], [1, 1, 1, 1])
        self.assertEqual(point, 0.75)
        self.assertLessEqual(lo, point)
        self.assertLessEqual(point, hi)
        self.assertLessEqual(upper, hi)

    def test_clusters_are_resampled_whole(self):
        # Every game is all ones or all zeros: resampling games moves the share in
        # steps of a whole game; resampling roots would not reach 0 or 1.
        games = np.repeat(np.arange(4), 50)
        values = np.repeat([1.0, 1.0, 0.0, 0.0], 50)
        point, lo, hi, _ = D.ratio_bootstrap(games, values, np.ones(200), reps=4000)
        self.assertEqual(point, 0.5)
        self.assertEqual((lo, hi), (0.0, 1.0))
        spread = D.ratio_bootstrap(np.arange(200), values, np.ones(200), reps=4000)
        self.assertGreater(spread[1], 0.4)
        self.assertLess(spread[2], 0.6)

    def test_an_empty_denominator_is_nan(self):
        point, lo, hi, upper = D.ratio_bootstrap([0, 1], [0, 0], [0, 0])
        self.assertTrue(all(np.isnan(v) for v in (point, lo, hi, upper)))


class Report(unittest.TestCase):
    def roots(self):
        roots = []
        for game in range(12):
            # One class has a real gain in a third of its roots; the others have none.
            gain = 0.2 if game % 3 == 0 else 0.0
            roots.append(make_root(game, "after_declare", 1.0, [1.0 + gain, 0.9], seed=game))
            roots.append(make_root(game, "turn", 1.0, [1.0, 0.99], seed=100 + game))
            roots.append(make_root(game, "declare", 1.0, [0.9], seed=200 + game))
        return roots

    def test_the_tables_recover_what_was_planted(self):
        summary = D.analyze_roots(self.roots(), resamples=50, reps=500)
        self.assertEqual((summary["roots"], summary["games"]), (36, 12))
        head = summary["headroom"]
        self.assertAlmostEqual(head["after_declare"]["share"][0], 4 / 12, delta=0.01)
        self.assertEqual(head["declare"]["share"][0], 0.0)
        self.assertAlmostEqual(head["after_declare"]["rule_gain"][0], 0.2 / 3, delta=0.02)
        self.assertAlmostEqual(head["all"]["share"][0], 4 / 36, delta=0.03)
        winners = [w for w in summary["winners"] if w["class"] == "after_declare"]
        self.assertEqual((winners[0]["a0"], winners[0]["alternative"]),
                         ("END_ACTIVATION", "BLOCK_TARGET"))
        self.assertGreaterEqual(winners[0]["headroom"], 4)
        rows = {(r["n"], r["floor"]): r for r in summary["rule"]["after_declare"]}
        self.assertEqual(set(rows), {(n, f) for n in D.RULE_SIZES for f in (False, True)})
        self.assertAlmostEqual(rows[(32, False)]["deviation_rate"][0], 1 / 3, delta=0.1)
        self.assertLess(rows[(32, False)]["false_rate"][0], 0.2)
        where = summary["concentration"]
        self.assertEqual((where["a0_top_all"], where["deviating"], where["a0_top_deviating"],
                          where["games_with_a_deviation"]), (36, 4, 4, 4))
        self.assertAlmostEqual(where["top3_share_of_gain"], 0.75, delta=0.1)
        text = D.format_report(summary)
        for heading in ("D1 headroom", "D2 the deviation rule", "D4 variance"):
            self.assertIn(heading, text)

    def test_single_candidate_and_tiny_roots_are_skipped(self):
        roots = self.roots()
        roots.append({"game": 99, "class": "turn", "returns": np.ones((1, 128)),
                      "types": ["ACTIVATE"]})
        roots.append({"game": 99, "class": "turn", "returns": np.ones((2, 2)),
                      "types": ["ACTIVATE", "ACTIVATE"]})
        self.assertEqual(D.analyze_roots(roots, resamples=10, reps=50)["roots"], 36)

    def test_the_class_of_a_decision(self):
        A = {"ACTIVATE": 6, "DECLARE": 7}
        self.assertEqual(D.decision_class({6, 8}, False, A), "turn")
        self.assertEqual(D.decision_class({7}, True, A), "declare")
        self.assertEqual(D.decision_class({9, 19}, True, A), "after_declare")
        self.assertIsNone(D.decision_class({9, 19}, False, A))


def make_outcome(game, cls, group, gain=0.0, n=64, seed=0, predicted=0.0, missing=()):
    """An outcome record with a planted win-score gain of `gain`: a0 wins half its
    rollouts, and the alternative lifts a share 4 * gain of them by half a point,
    which only counts where a0 had lost. The two candidates share a0's results,
    as common dice would."""
    rng = np.random.default_rng(seed)
    base = (rng.random(n) > 0.5).astype(float)
    lift = rng.random(n) < abs(gain) * 4
    alt = np.clip(base + np.sign(gain) * 0.5 * lift, 0.0, 1.0)
    win = np.stack([base, alt])
    td = np.stack([base * 2 - 1, alt * 2 - 1])
    d1_td = np.stack([np.zeros(n), np.full(n, 0.02)])
    d1_other = np.stack([np.full(n, 0.01), np.full(n, 0.03)])
    d1_value = np.stack([rng.normal(1.0, 0.05, n), rng.normal(1.0 + predicted, 0.05, n)])
    depth1 = d1_td + d1_other + d1_value
    metrics = {"win_score": win, "win": (win == 1).astype(float),
               "loss": (win == 0).astype(float), "td_diff": td, "depth1": depth1,
               "depth2": depth1 + 0.01, "depth1_touchdown": d1_td, "depth1_other": d1_other,
               "depth1_value": d1_value}
    metrics = {m: v.tolist() for m, v in metrics.items()}
    for c, j in missing:
        for m in metrics:
            metrics[m][c][j] = None
    return {"schema": D.OUTCOME_SCHEMA, "game": game, "class": cls, "set": group, "step": seed,
            "types": ["ACTIVATE", "ACTIVATE"], "declared": None,
            "predicted": {"gain_a": predicted, "gain_b": predicted, "gain_all": predicted},
            "description": [f"root {seed}"], "metrics": metrics}


class Selection(unittest.TestCase):
    def roots(self, flag_b=1.0):
        roots = []
        for game in range(20):
            for i, cls in enumerate(D.CLASSES):
                planted = 0.2 if (game % 4 == 0 and cls != "declare") else 0.0
                root = make_root(game, cls, 1.0, [1.0 + planted, 0.95], seed=10 * game + i)
                root["step"] = 100 + i
                # Half B can say anything: it must not move the selection.
                root["returns"][1, 64:] *= flag_b
                roots.append(root)
        return roots

    def test_flagged_is_the_rule_on_half_a_and_control_is_a_balanced_fixed_draw(self):
        chosen = D.select_outcome_roots(self.roots())
        flagged = [r for r in chosen if r["set"] == "flagged"]
        control = [r for r in chosen if r["set"] == "control"]
        self.assertEqual({r["key"][:2] for r in flagged},
                         {(g, c) for g in range(0, 20, 4) for c in ("turn", "after_declare")})
        self.assertTrue(all(r["alt"] == 1 and r["gain_a"] > D.DELTA for r in flagged))
        self.assertEqual(len(control), len(flagged))
        self.assertFalse({r["key"] for r in flagged} & {r["key"] for r in control})
        per_class = [sum(r["key"][1] == c for r in control) for c in D.CLASSES]
        self.assertEqual(per_class, [4, 3, 3])
        self.assertTrue(all(r["gain_a"] <= D.DELTA for r in control))
        again = D.select_outcome_roots(self.roots())
        self.assertEqual([(r["key"], r["set"], r["alt"]) for r in chosen],
                         [(r["key"], r["set"], r["alt"]) for r in again])
        other = D.select_outcome_roots(self.roots(), seed=1)
        self.assertNotEqual({r["key"] for r in control},
                            {r["key"] for r in other if r["set"] == "control"})

    def test_the_selection_never_reads_half_b(self):
        plain = D.select_outcome_roots(self.roots())
        spoiled = D.select_outcome_roots(self.roots(flag_b=-3.0))
        self.assertEqual([(r["key"], r["set"], r["alt"], r["gain_a"]) for r in plain],
                         [(r["key"], r["set"], r["alt"], r["gain_a"]) for r in spoiled])
        self.assertNotEqual([r["gain_b"] for r in plain], [r["gain_b"] for r in spoiled])

    def test_a_class_that_runs_short_is_topped_up(self):
        roots = [r for r in self.roots() if r["class"] != "declare" or r["game"] < 1]
        chosen = D.select_outcome_roots(roots)
        control = [r for r in chosen if r["set"] == "control"]
        self.assertEqual(len(control), 10)
        self.assertEqual(sum(r["key"][1] == "declare" for r in control), 1)


class Outcomes(unittest.TestCase):
    def test_a_rollout_index_missing_for_one_candidate_is_dropped_for_both(self):
        record = make_outcome(0, "turn", "flagged", n=8, missing=[(1, 3)])
        diffs, values, excluded = D.outcome_differences(record)
        self.assertEqual((excluded, len(diffs["win_score"]), values["win_score"].shape),
                         (1, 7, (2, 7)))
        whole, _, none = D.outcome_differences(make_outcome(0, "turn", "flagged", n=8))
        self.assertEqual(none, 0)
        np.testing.assert_array_equal(diffs["td_diff"], np.delete(whole["td_diff"], 3))

    def test_the_tables_recover_a_planted_win_gain_and_a_null(self):
        records = []
        for game in range(30):
            records.append(make_outcome(game, D.CLASSES[game % 3], "flagged", gain=0.1, n=128,
                                        seed=game, predicted=0.05 + 0.01 * (game % 5)))
            records.append(make_outcome(game, D.CLASSES[game % 3], "control", gain=0.0,
                                        seed=1000 + game))
        summary = D.analyze_outcomes(records, reps=400)
        self.assertEqual((summary["roots"], summary["games"]), (60, 30))
        flagged, control = summary["sets"]["flagged"], summary["sets"]["control"]
        point, lo, hi, _ = flagged["all"]["win_score"]
        self.assertAlmostEqual(point, 0.1, delta=0.02)
        self.assertGreater(lo, 0.05)
        self.assertEqual(control["all"]["win_score"][0], 0.0)
        self.assertEqual(flagged["turn"]["roots"], 10)
        self.assertGreater(flagged["all"]["changed"], 0.15)
        # The depth-1 gain is the sum of its three parts.
        cell = flagged["all"]
        self.assertAlmostEqual(cell["depth1"][0], cell["depth1_touchdown"][0]
                               + cell["depth1_other"][0] + cell["depth1_value"][0], places=9)
        self.assertAlmostEqual(cell["depth1_touchdown"][0], 0.02, places=9)
        self.assertAlmostEqual(cell["depth2"][0], cell["depth1"][0], places=9)
        # Shared result noise cancels in the pair; nothing is shared in the control's
        # constant difference.
        self.assertLess(summary["pairing"]["flagged"]["win_score"], 0.5)
        self.assertEqual([r["predicted"]["gain_b"] for r in summary["largest"]], [0.09] * 3)
        listed = summary["flagged_roots"]
        self.assertEqual(len(listed), 30)
        self.assertEqual([r["predicted"] for r in listed],
                         sorted((r["predicted"] for r in listed), reverse=True))
        self.assertAlmostEqual(np.mean([r["a0_win_score"] for r in listed]), 0.5, delta=0.05)
        self.assertEqual(set(summary["correlation"]), {"all", "flagged", "control"})
        self.assertEqual(len(summary["correlation"]["flagged"]["first_run_td"]), 6)
        text = D.format_outcome_report(summary)
        for heading in ("Realized, to the end of the match", "The evaluator's view",
                        "Does the predicted gain track", "root 4", "Every flagged root",
                        "realized touchdown difference"):
            self.assertIn(heading, text)

    def test_correlation_and_slope_with_a_cluster_bootstrap(self):
        rng = np.random.default_rng(0)
        x = rng.normal(0, 1, 60)
        games = np.repeat(np.arange(20), 3)
        r, lo, hi, slope, s_lo, s_hi = D.cluster_correlation(games, x, 2.0 * x, reps=300)
        self.assertAlmostEqual(r, 1.0, places=9)
        self.assertAlmostEqual(slope, 2.0, places=9)
        self.assertAlmostEqual(s_lo, 2.0, places=6)
        r, lo, hi, slope, s_lo, s_hi = D.cluster_correlation(games, x, rng.normal(0, 1, 60),
                                                             reps=300)
        self.assertLess(lo, 0.0)
        self.assertGreater(hi, 0.0)
        r, lo, hi, slope, _, _ = D.cluster_correlation(games, x, np.zeros(60), reps=50)
        self.assertTrue(np.isnan(r) and np.isnan(lo))

    def test_outcome_metrics_read_the_marks(self):
        from types import SimpleNamespace
        gamma = 0.5
        batch = SimpleNamespace(
            stops=["terminal", "terminal", "rejected", "terminal"],
            scores=np.array([[[2, 1], [1, 1]], [[-1, -1], [0, 3]]]),
            rewards=np.array([[1.0, 0.3], [0.0, -1.2]]),
            touchdowns=np.array([[0.4, 0.0], [0.0, -0.8]]),
            marks=[[(2, 0.3, 0.4, 1.0), (4, 0.5, 0.4, 2.0), (6, 0.9, 0.4, 3.0)],
                   [(3, 0.2, 0.0, 0.8)], [], []])
        got = D.outcome_metrics(batch, 2, 2, gamma)
        # Two marks: depth 1 from the first, depth 2 from the second.
        self.assertEqual(got["win_score"][0][0], 1.0)
        self.assertEqual(got["td_diff"][0][0], 1.0)
        self.assertAlmostEqual(got["depth1"][0][0], 0.3 + gamma ** 2 * 1.0)
        self.assertAlmostEqual(got["depth2"][0][0], 0.5 + gamma ** 4 * 2.0)
        self.assertEqual((got["depth1_touchdown"][0][0], got["depth1_value"][0][0]), (0.4, 0.25))
        self.assertAlmostEqual(got["depth1_other"][0][0], -0.1)
        # One mark: the match ended before a second own turn end, so depth 2 is all
        # the reward the rollout collected.
        self.assertEqual((got["win_score"][0][1], got["win"][0][1], got["loss"][0][1]),
                         (0.5, 0.0, 0.0))
        self.assertEqual(got["depth2"][0][1], 0.3)
        # Rejected: nothing. No mark at all: the match ended inside the turn.
        self.assertTrue(all(got[m][1][0] is None for m in D.OUTCOME_METRICS))
        self.assertEqual((got["loss"][1][1], got["td_diff"][1][1]), (1.0, -3.0))
        self.assertEqual((got["depth1"][1][1], got["depth1_touchdown"][1][1],
                          got["depth1_value"][1][1]), (-1.2, -0.8, 0.0))
        self.assertAlmostEqual(got["depth1_other"][1][1], -0.4)


if __name__ == "__main__":
    unittest.main()
