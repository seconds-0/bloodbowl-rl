"""Tournament summary statistics: Wilson intervals, pair splits, Bradley-Terry."""
import json
import math
import os

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


def test_seed_cluster_resampling_moves_whole_seeds():
    rng = np.random.default_rng(0)
    games = []
    for i in range(40):
        for pair in (("x", "y"), ("x", "z")):
            for leg in LEGS:
                games.append({"pair": list(pair), "leg": leg, "engine_seed": 900 + i,
                              "game_index": i, "result_a": "WDL"[rng.integers(3)]})
    _, cells, counts = S.cluster_counts(games, key=lambda g: (tuple(g["pair"]), g["leg"]))
    assert len(cells) == 4 and counts.shape == (40, 4, 3)
    boots = S.bootstrap_cluster_counts(counts, reps=200, seed=3)
    per_cell = boots.sum(axis=-1)                       # games per (pair, leg) per replicate
    assert np.all(per_cell == 40)                         # a drawn seed brings every pair and leg
    assert not np.all(boots == boots[0])                  # and replicates differ


def test_seed_cluster_intervals_track_leg_dependence():
    rng = np.random.default_rng(9)
    same, flip = [], []
    for i in range(600):
        r = "W" if rng.random() < 0.5 else "L"
        other = "L" if r == "W" else "W"
        same += _leg_games(("x", "y"), [(r, r)], seed0=i)
        flip += _leg_games(("x", "y"), [(r, other)], seed0=i)
    iid_se = math.sqrt(0.25 / 1200)
    boot_same = S.seed_cluster_bootstrap(same, reps=600, seed=1)["pairs"][0]
    half_width = (boot_same["decisive_share_ci95"][1] - boot_same["decisive_share_ci95"][0]) / 2
    assert math.isclose(half_width / 1.96, math.sqrt(2) * iid_se, rel_tol=0.15)
    boot_flip = S.seed_cluster_bootstrap(flip, reps=200, seed=1)["pairs"][0]
    assert boot_flip["decisive_share_ci95"] == [0.5, 0.5]


def test_score_rate_counts_draws_as_half_and_elo_scale():
    games = _leg_games(("x", "y"), [("W", "D"), ("D", "D"), ("L", "W")])
    (row,) = S.seed_cluster_bootstrap(games, reps=50)["pairs"]
    assert (row["W"], row["D"], row["L"]) == (2, 3, 1)
    assert math.isclose(row["decisive_share"], 2 / 3)
    assert math.isclose(row["score_rate"], 3.5 / 6)
    assert math.isclose(float(S.elo_from_share(0.64)), 100.0, abs_tol=0.5)
    assert float(S.elo_from_share(0.5)) == 0.0


def test_chi2_sf_reference_values():
    assert math.isclose(S.chi2_sf(3.841458820694124, 1), 0.05, abs_tol=1e-9)
    assert math.isclose(S.chi2_sf(18.307038053275146, 10), 0.05, abs_tol=1e-9)
    assert math.isclose(S.chi2_sf(20.0, 10), 0.029252688076961, abs_tol=1e-9)
    assert math.isclose(S.chi2_sf(2.0, 4), math.exp(-1.0) * 2.0, abs_tol=1e-12)
    assert S.chi2_sf(0.0, 3) == 1.0


def test_bt_misfit_passes_bt_data_and_flags_a_cycle():
    theta = np.array([0.3, 0.0, -0.3, 0.1])
    names, games = _synthetic_games(theta, 3000, np.random.default_rng(21))
    fit = S.bt_misfit(S.win_matrix(games, names), names)
    assert fit["df"] == 6 - 3 and fit["p"] > 0.01 and len(fit["rows"]) == 6
    cycle = np.array([[0, 700, 300], [300, 0, 700], [700, 300, 0]], dtype=float)
    bad = S.bt_misfit(cycle, ["a", "b", "c"])
    assert bad["df"] == 1 and bad["p"] < 1e-12 and bad["p_deviance"] < 1e-12


def test_bradley_terry_refuses_a_disconnected_pair_graph():
    wins = np.array([[0, 5, 0, 0], [4, 0, 0, 0], [0, 0, 0, 6], [0, 0, 3, 0]], dtype=float)
    with pytest.raises(ValueError, match="connected"):
        S.bt_fit(wins)


def test_power_helper_round_trips_and_matches_reference():
    mde = S.power_mde_elo(1400, 0.62)
    assert 32.0 < mde < 34.0                                      # about 30 Elo at 1400 games
    n = S.power_games_per_pair(20.0, 0.62, leg_corr=-0.207)
    assert 2900 < n < 3100 and n % 2 == 0                         # D399's ~3100 for 20 Elo
    assert S.power_mde_elo(n, 0.62, leg_corr=-0.207) <= 20.0 < \
        S.power_mde_elo(n - 40, 0.62, leg_corr=-0.207)
    assert S.power_mde_elo(1400, 0.62, leg_corr=0.5) > mde         # positive dependence costs power


def test_sharpness_pools_decisions():
    games = [{"home": "p", "away": "q", "logprob_sum": [-10.0, -3.0], "decisions": [100, 20]},
             {"home": "q", "away": "p", "logprob_sum": [-1.0, -20.0], "decisions": [10, 100]}]
    sh = S.sharpness(games)
    assert math.isclose(sh["p"]["mean_logprob"], -30.0 / 200) and sh["p"]["decisions"] == 200
    assert math.isclose(sh["q"]["mean_logprob"], -4.0 / 30)


@pytest.mark.skipif(not os.path.exists(S.GEN_TEAMS), reason="engine roster table not present")
def test_roster_classes_follow_the_rule_on_the_bb2025_spec():
    traits = S.roster_traits()
    assert len(traits) == 30
    assert {name: S.classify_roster(t) for name, t in traits.items()} == S.ROSTER_CLASS
    counts = {c: sum(v == c for v in S.ROSTER_CLASS.values()) for c in S.ROSTER_CLASSES}
    assert counts == {"agile": 5, "bash": 15, "hybrid": 5, "stunty": 5}
    assert traits["High Elf"]["lineman"]["ag"] == 2 and traits["Tomb Kings"]["lineman"]["ma"] == 5


def test_roster_class_table_uses_the_roster_a_coached():
    teams = ["High Elf", "Tomb Kings"]
    games = [{"pair": ["x", "y"], "leg": "A_home", "engine_seed": 1, "result_a": "W", "teams": teams},
             {"pair": ["x", "y"], "leg": "B_home", "engine_seed": 1, "result_a": "L", "teams": teams},
             {"pair": ["x", "y"], "leg": "A_home", "engine_seed": 2, "result_a": "W", "teams": teams},
             {"pair": ["x", "y"], "leg": "B_home", "engine_seed": 2, "result_a": "D", "teams": teams}]
    table = S.roster_class_table(games, reps=50)
    rows = {r["class"]: r for r in table["rows"]}
    assert (rows["agile"]["W"], rows["agile"]["L"]) == (2, 0)         # A coached High Elf at home
    assert (rows["bash"]["W"], rows["bash"]["D"], rows["bash"]["L"]) == (0, 1, 1)
    (contrast,) = table["contrasts"]
    assert math.isclose(contrast["agile_minus_bash"], 1.0)
    matchup = {r["class"]: r for r in S.roster_class_table(games, reps=20, by="matchup")["rows"]}
    assert set(matchup) == {"agile|bash", "bash|agile"}


def test_stats_cli_prints_and_writes_the_report(tmp_path, capsys):
    rng = np.random.default_rng(4)
    teams = ["High Elf", "Tomb Kings", "Human", "Goblin"]
    lines = []
    for i in range(40):
        for pair in (("x", "y"), ("x", "z"), ("y", "z")):
            for leg in LEGS:
                res = "WDL"[rng.integers(3)]
                home, away = pair if leg == "A_home" else pair[::-1]
                lines.append({"pair": list(pair), "leg": leg, "engine_seed": 70 + i,
                              "game_index": i, "result_a": res, "a_td": int(res == "W"),
                              "b_td": int(res == "L"), "teams": [teams[i % 4], teams[(i + 1) % 4]],
                              "home": home, "away": away, "logprob_sum": [-10.0, -12.0],
                              "decisions": [80, 90]})
    (tmp_path / "games.jsonl").write_text("\n".join(json.dumps(g) for g in lines))
    S.main(["--run-dir", str(tmp_path), "--reps", "40", "--json", str(tmp_path / "r.json")])
    out = capsys.readouterr().out
    assert "Seed-cluster bootstrap" in out and "within-pair centred" in out
    assert "misfit" in out and "| x | y | agile |" in out
    rep = json.load(open(tmp_path / "r.json"))
    assert rep["bt_misfit"]["df"] == 1 and len(rep["seed_cluster"]["pairs"]) == 3
    assert "x|y" in rep["leg_correlation"]["per_pair"]
    assert rep["sharpness"]["x"]["decisions"] == 2 * 40 * (80 + 90)    # two pairs, both legs


def test_rank_correlations():
    assert S.kendall_tau([1, 2, 3, 4], [10, 20, 30, 40]) == 1.0
    assert S.kendall_tau([1, 2, 3, 4], [40, 30, 20, 10]) == -1.0
    assert math.isclose(S.spearman_rho([1, 2, 3], [3, 1, 2]), -0.5)
