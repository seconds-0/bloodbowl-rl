"""Tournament summary statistics: Wilson intervals, pair splits, Bradley-Terry."""
import math

import numpy as np
import pytest

from play_harness import tournament_stats as S

LEGS = ("A_home", "B_home")


def test_wilson_matches_reference_values():
    lo, hi = S.wilson(5, 10)
    assert math.isclose(lo, 0.2366, abs_tol=1e-4) and math.isclose(hi, 0.7634, abs_tol=1e-4)
    lo, hi = S.wilson(0, 20)
    assert lo == 0.0 and math.isclose(hi, 0.1611, abs_tol=1e-4)
    assert all(math.isnan(v) for v in S.wilson(0, 0))


def _synthetic_games(theta, per_pair, rng, draw_rate=0.3):
    names = [f"p{i}" for i in range(len(theta))]
    games = []
    for i in range(len(theta)):
        for j in range(i + 1, len(theta)):
            p = 1.0 / (1.0 + math.exp(theta[j] - theta[i]))
            for k in range(per_pair):
                u = rng.random()
                res = "D" if u < draw_rate else ("W" if rng.random() < p else "L")
                games.append({"pair": [names[i], names[j]], "leg": LEGS[k % 2], "result_a": res,
                              "a_td": 1 if res == "W" else 0, "b_td": 1 if res == "L" else 0})
    return names, games


def test_bradley_terry_recovers_strengths():
    theta = np.array([0.4, 0.1, 0.0, -0.5])
    names, games = _synthetic_games(theta, 4000, np.random.default_rng(3))
    fit = S.bt_fit(S.win_matrix(games, names))
    assert np.allclose(fit, theta - theta.mean(), atol=0.06)
    se, _ = S.bt_standard_errors(S.win_matrix(games, names), fit)
    assert np.all(se > 0) and np.all(se < 0.05)
    rank = S.ranking(games, names, reps=50, seed=1)
    assert [r["name"] for r in rank["rows"]] == names
    assert rank["rows"][0]["rank_freq"][1] > 0.9


def test_bootstrap_spread_matches_fisher_standard_errors():
    theta = np.array([0.2, 0.0, -0.2])
    names, games = _synthetic_games(theta, 1500, np.random.default_rng(5))
    wins = S.win_matrix(games, names)
    se, _ = S.bt_standard_errors(wins, S.bt_fit(wins))
    boots = S.bootstrap(games, names, reps=400, seed=2)
    assert np.allclose(boots.std(axis=0), se, rtol=0.2)


def test_bradley_terry_refuses_a_winless_player():
    wins = np.array([[0, 3], [0, 0]], dtype=float)
    with pytest.raises(ValueError):
        S.bt_fit(wins)


def test_pair_table_side_splits():
    games = [
        {"pair": ["x", "y"], "leg": "A_home", "result_a": "W", "a_td": 2, "b_td": 0},
        {"pair": ["x", "y"], "leg": "B_home", "result_a": "D", "a_td": 1, "b_td": 1},
        {"pair": ["x", "y"], "leg": "B_home", "result_a": "L", "a_td": 0, "b_td": 1},
    ]
    (row,) = S.pair_table(games)
    assert (row["W"], row["D"], row["L"], row["decisive"]) == (1, 1, 1, 2)
    assert row["a_win_share"] == 0.5
    assert (row["a_home"]["W"], row["a_home"]["games"]) == (1, 1)
    assert (row["b_home"]["D"], row["b_home"]["L"], row["b_home"]["games"]) == (1, 1, 2)
    assert math.isclose(row["a_td_per_game"], 1.0) and math.isclose(row["b_td_per_game"], 2 / 3)


def _leg_games(pair, outcomes, seed0=0):
    """outcomes: list of (A result in leg A_home, A result in leg B_home), one per seed."""
    games = []
    for i, (x, y) in enumerate(outcomes):
        for leg, res in (("A_home", x), ("B_home", y)):
            games.append({"pair": list(pair), "leg": leg, "engine_seed": seed0 + i,
                          "game_index": i, "result_a": res})
    return games


def test_leg_correlation_is_centred_within_pair():
    # Inside each pair the two legs are exactly independent (p = 0.8, then 0.2),
    # so the within-pair correlation is 0. Pooling the pairs without centring
    # each one adds the between-pair strength gap and reads positive.
    strong = [("W", "W")] * 16 + [("W", "L")] * 4 + [("L", "W")] * 4 + [("L", "L")]
    weak = [("L", "L")] * 16 + [("L", "W")] * 4 + [("W", "L")] * 4 + [("W", "W")]
    games = _leg_games(("x", "y"), strong) + _leg_games(("x", "z"), weak, seed0=100)
    corr = S.leg_correlation(games)
    assert abs(corr["within_pair_centred"]) < 1e-12
    # pooled: between-pair variance 0.09 over total 0.25 -> 0.36
    assert math.isclose(corr["pooled_uncentred"], 0.36)
    assert all(abs(r) < 1e-12 for r in corr["per_pair"].values()) and corr["seeds"] == 50
    # legs that always disagree inside a pair: exactly -1 once centred
    flip = [("W", "L")] * 10 + [("L", "W")] * 10
    assert math.isclose(S.leg_correlation(_leg_games(("x", "y"), flip))["within_pair_centred"],
                        -1.0)


def test_rank_correlations():
    assert S.kendall_tau([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert S.kendall_tau([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert math.isclose(S.spearman_rho([1, 2, 3], [3, 1, 2]), -0.5)
