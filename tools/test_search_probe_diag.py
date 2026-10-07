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


if __name__ == "__main__":
    unittest.main()
