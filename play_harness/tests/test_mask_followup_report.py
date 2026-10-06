"""The follow-up report: the paired contrast, run validation and the activation table."""
import os
import sys

import pytest

from play_harness import activations as AC
from play_harness import tournament as T

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
import mask_arms_report as R  # noqa: E402
import mask_followup_launch as L  # noqa: E402
import mask_followup_report as F  # noqa: E402


def game(a, b, seed, leg, a_td, b_td, **counts):
    a_side = 0 if leg == "A_home" else 1
    behaviour = [dict(T.new_behaviour(), **dict.fromkeys(AC.KEYS, 0), team_turns=16,
                      team_turns_holding_ball=8, turnovers=4) for _ in (0, 1)]
    behaviour[a_side].update(counts)
    score = [0, 0]
    score[a_side], score[1 - a_side] = a_td, b_td
    return {"pair": [a, b], "game_index": seed, "leg": leg, "engine_seed": seed,
            "teams": ["Orc", "Wood Elf"], "score": score, "a_td": a_td, "b_td": b_td,
            "result_a": "W" if a_td > b_td else ("D" if a_td == b_td else "L"),
            "c_steps": 700, "behaviour": behaviour, "masks": [None, None],
            "mask_stats": [None, None], "natural": True,
            "integrity": {k: 0 for k in R.HARD_COUNTERS}}


def two_pairs(masked_wins, plain_wins, n=400):
    """Both pairs on the same seeds; A wins the first `wins` seeds of each."""
    games = []
    for i in range(n):
        for leg in T.LEGS:
            games.append(game("m", "x", i, leg, int(i < masked_wins), int(i >= masked_wins)))
            games.append(game("p", "x", i, leg, int(i < plain_wins), int(i >= plain_wins)))
    return games


def test_paired_contrast_is_the_difference_of_the_two_pairs_elo():
    games = two_pairs(240, 200)
    c = F.paired_contrast(games, ("m", "x"), ("p", "x"), reps=400)
    rows = F.pair_rows(games, reps=50)
    want = rows[("m", "x")]["elo_decisive"] - rows[("p", "x")]["elo_decisive"]
    assert c["elo_contrast"] == pytest.approx(want) and want > 60
    assert c["ci95"][0] < c["elo_contrast"] < c["ci95"][1]
    # Seeds 200..239 are the only ones where the pairs differ, so the paired
    # interval is tighter than either pair's own (two independent pairs would
    # give one about 1.4 times as wide).
    own = rows[("m", "x")]["elo_decisive_ci95"]
    assert c["ci95"][1] - c["ci95"][0] < 0.75 * (own[1] - own[0])
    assert c["verdict"] == ["better", "non-inferior"]
    assert c["score_rate_contrast"] == pytest.approx(0.1)
    same = F.paired_contrast(two_pairs(200, 200), ("m", "x"), ("p", "x"), reps=200)
    assert same["elo_contrast"] == 0 and same["ci95"] == [0.0, 0.0]
    assert same["verdict"] == ["non-inferior"]
    worse = F.paired_contrast(two_pairs(150, 250), ("m", "x"), ("p", "x"), reps=200)
    assert worse["verdict"] == ["worse"]


def test_verdict_thresholds():
    assert F.verdict(1, 30) == ["better", "non-inferior"]
    assert F.verdict(-30, -1) == ["worse"]
    assert F.verdict(-19, -1) == ["worse", "non-inferior"]
    assert F.verdict(-19, 5) == ["non-inferior"]
    assert F.verdict(-25, 5) == ["inconclusive"]


def registered(run, n=4):
    seed0, pairs = L.RUNS[run]
    games = [game(a, b, seed0 + i, leg, 1, 0) for a, b in pairs for i in range(n // 2)
             for leg in T.LEGS]
    players, checkpoints = {}, {}
    for name in {x for pair in pairs for x in pair}:
        if name in L.BOTS:
            players[name] = {"bot": name}
            continue
        chain, masks, offset = L.PLAYERS[name]
        players[name] = {"mode": "sample", "temperature": 1.0}
        if masks:
            players[name]["masks"] = sorted(masks.split(","))
        if offset:
            players[name]["seed_offset"] = offset
        checkpoints[name] = {"sha256": R.CHAIN41_SHA256 if chain == "chain41" else chain}
    manifest = {"pairs": [[a, b, n] for a, b in pairs], "seed0": seed0, "kernel": "native",
                "games_per_worker": 32, "players": players, "checkpoints": checkpoints}
    return games, manifest


def test_a_run_must_be_the_registered_one(monkeypatch):
    monkeypatch.setattr(L, "GAMES", 4)
    for run in L.RUNS:
        F.check_run(run, *registered(run))
    games, manifest = registered("null")
    broken = dict(manifest, players={**manifest["players"],
                                     "chain41b": {"mode": "sample", "temperature": 1.0}})
    with pytest.raises(SystemExit):               # the null without its shifted seed
        F.check_run("null", games, broken)
    games, manifest = registered("t-chain47")
    with pytest.raises(SystemExit):               # the wrong seed block
        F.check_run("t-chain47", games, dict(manifest, seed0=1))
    with pytest.raises(SystemExit):               # a leg missing
        F.check_run("t-chain47", games[:-1], manifest)
    with pytest.raises(SystemExit):               # the opponent is chain 41's own blob
        F.check_run("t-chain47", games, dict(manifest, checkpoints={
            **manifest["checkpoints"], "chain47": {"sha256": R.CHAIN41_SHA256}}))
    with pytest.raises(SystemExit):               # the masked player lost its mask
        F.check_run("t-chain47", games, dict(manifest, players={
            **manifest["players"], "chain41m1": {"mode": "sample", "temperature": 1.0}}))
    with pytest.raises(SystemExit):               # another run's games
        F.check_run("m12", games, manifest)


def test_launcher_runs_are_the_registered_ones():
    assert {r: v[0] for r, v in L.RUNS.items()} == {
        "t-offense": 23500000, "t-contact": 23600000, "t-chain27": 23700000,
        "t-chain36": 23800000, "t-chain47": 23900000, "m12": 24000000, "null": 24100000,
        "both-m1": 24200000}
    argv = L.argv_for("both-m1", "abc")
    assert "--tournament-arg=chain41m1b=m1" in argv and "--tournament-arg=chain41m1=m1" in argv
    assert "--tournament-arg=chain41m1b=1" in argv
    assert sum(a == "--tournament-arg=--sampling-offset" for a in argv) == 1
    argv = L.argv_for("t-offense", "abc")
    assert ["--bot", "offense=offense"] == argv[argv.index("--bot"):argv.index("--bot") + 2]
    assert "chain41m1,offense,3200" in argv and "chain41,offense,3200" in argv
    assert not any("sampling-offset" in a for a in argv)
    assert not any("mask" in a for a in L.argv_for("null", "abc") if "tournament-arg" in a)


def test_activation_breakdown_is_per_team_turn():
    games = [game("m", "x", i, leg, 1, 0, activations=64, act_empty=16, act_moved=32,
                  act_block=8, act_blitz=8, moved_measured=32, moved_displacement=128,
                  moved_d_ball=-64,
                  moved_d_own_endzone=96, neg_activations=4, neg_failed=1, neg_turnover=2,
                  act_turnover=4)
             for i in range(3) for leg in T.LEGS]
    row = F.activation_breakdown({"g": games})["g"]
    assert row["activations_per_turn"] == 4.0 and row["empty_per_turn"] == 1.0
    assert row["moved_per_turn"] == 2.0 and row["block_per_turn"] == 0.5
    assert row["moved_mean_change_distance_to_ball"] == -2.0
    assert row["moved_mean_net_displacement"] == 4.0
    assert row["moved_mean_change_distance_from_own_endzone"] == 3.0
    neg = row["negative_trait"]
    assert neg["activations_per_game"] == 4.0 and neg["came_out_distracted_or_rooted"] == 0.25
    assert neg["turn_ended_in_turnover_there"] == 0.5 and neg["failures_per_game"] == 1.0
    assert F.side_means(games)["td_for"] == 1.0 and F.side_means(games)["draw_rate"] == 0.0
