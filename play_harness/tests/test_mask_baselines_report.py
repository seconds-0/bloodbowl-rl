"""The m1 baseline round: registered runs, run validation, behaviour rows."""
import os
import sys

import pytest

from play_harness import activations as AC
from play_harness import tournament as T

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
import mask_arms_report as R  # noqa: E402
import mask_baselines_launch as L  # noqa: E402
import mask_baselines_report as B  # noqa: E402


def game(a, b, seed, leg, a_td, b_td, a_counts=None, b_counts=None):
    a_side = 0 if leg == "A_home" else 1
    behaviour = [dict(T.new_behaviour(), **dict.fromkeys(AC.KEYS, 0), team_turns=16,
                      team_turns_holding_ball=8, turnovers=4) for _ in (0, 1)]
    behaviour[a_side].update(a_counts or {})
    behaviour[1 - a_side].update(b_counts or {})
    score = [0, 0]
    score[a_side], score[1 - a_side] = a_td, b_td
    return {"pair": [a, b], "game_index": seed, "leg": leg, "engine_seed": seed,
            "teams": ["Orc", "Wood Elf"], "score": score, "a_td": a_td, "b_td": b_td,
            "result_a": "W" if a_td > b_td else ("D" if a_td == b_td else "L"),
            "c_steps": 900, "behaviour": behaviour, "natural": True,
            "integrity": {k: 0 for k in R.HARD_COUNTERS}}


def registered(run, n=4):
    seed0, pairs = L.RUNS[run]
    games = [game(a, b, seed0 + i, leg, 1, 0) for a, b in pairs for i in range(n // 2)
             for leg in T.LEGS]
    players, checkpoints = {}, {}
    for name in {x for pair in pairs for x in pair}:
        chain, masks, offset = L.PLAYERS[name]
        players[name] = {"mode": "sample", "temperature": 1.0}
        if masks:
            players[name]["masks"] = sorted(masks.split(","))
        if offset:
            players[name]["seed_offset"] = offset
        checkpoints[name] = {"sha256": "sha-" + chain}
    manifest = {"pairs": [[a, b, n] for a, b in pairs], "seed0": seed0, "kernel": "native",
                "games_per_worker": 32, "players": players, "checkpoints": checkpoints}
    return games, manifest


def test_registered_runs_and_launch_commands():
    assert {r: v[0] for r, v in L.RUNS.items()} == {
        "c42-self": 24500000, "c42-c41": 24600000, "c37-42": 24700000, "c37-41": 24700000,
        "c47-self": 24800000, "c48-self": 24900000}
    # One checkpoint never meets itself on one sampling stream.
    for _seed, pairs in L.RUNS.values():
        for a, b in pairs:
            if L.PLAYERS[a][0] == L.PLAYERS[b][0]:
                assert L.PLAYERS[a][2] != L.PLAYERS[b][2]
    argv = L.argv_for("c42-self", "abc")
    assert "--tournament-arg=chain42m1s=m1" in argv and "--tournament-arg=chain42m1s=1" in argv
    assert "chain42m1s,chain42,3200" in argv
    argv = L.argv_for("c42-c41", "abc")
    assert "chain42m1,chain41m1,3200" in argv and "chain42,chain41,3200" in argv
    assert not any("sampling-offset" in a for a in argv)
    assert sum(a == "--tournament-arg=--mask" for a in argv) == 2


def test_a_run_must_be_the_registered_one(monkeypatch):
    monkeypatch.setattr(L, "GAMES", 4)
    shas = {c: "sha-" + c for c in ("chain37", "chain41", "chain42", "chain47", "chain48")}
    for run in L.RUNS:
        B.check_run(run, *registered(run), chain_sha=shas)
    games, manifest = registered("c42-self")
    spec = {"mode": "sample", "temperature": 1.0}
    bad = [
        dict(manifest, seed0=1),
        dict(manifest, players={**manifest["players"], "chain42m1s": dict(spec, masks=["m1"])}),
        dict(manifest, players={**manifest["players"], "chain42m1s": dict(spec, seed_offset=1)}),
        dict(manifest, checkpoints={"chain42m1s": {"sha256": "x"}, "chain42": {"sha256": "sha-chain42"}}),
        dict(manifest, games_per_worker=1),
    ]
    for broken in bad:
        with pytest.raises(SystemExit):
            B.check_run("c42-self", games, broken, chain_sha=shas)
    with pytest.raises(SystemExit):                       # another blob than the registered one
        B.check_run("c42-self", games, manifest, chain_sha=dict(shas, chain42="other"))
    with pytest.raises(SystemExit):                       # a leg missing
        B.check_run("c42-self", games[:-1], manifest, chain_sha=shas)
    with pytest.raises(SystemExit):                       # another run's games
        B.check_run("c47-self", games, manifest, chain_sha=shas)
    games, manifest = registered("c42-c41")
    same = dict(manifest, checkpoints={n: {"sha256": "one"} for n in manifest["checkpoints"]})
    with pytest.raises(SystemExit):                       # two chains, one blob
        B.check_run("c42-c41", games, same)


def test_side_rows_read_each_side_and_the_shared_game():
    games = [game("a", "b", i, leg, 2, 1, a_counts={"activations": 96, "act_empty": 32,
                                                    "block_targets": 10, "turnovers": 8},
                  b_counts={"activations": 48, "act_empty": 8, "block_targets": 6})
             for i in range(2) for leg in T.LEGS]
    rows = B.side_rows(games)
    assert rows["a"] == {"activations_per_turn": 6.0, "empties_per_turn": 2.0,
                         "blocks_per_game": 10.0, "turnovers_per_turn": 0.5, "td_per_game": 2.0}
    assert rows["b"]["activations_per_turn"] == 3.0 and rows["b"]["td_per_game"] == 1.0
    assert rows["b"]["turnovers_per_turn"] == 0.25
    assert rows["decisions_per_game"] == 900 and rows["draw_rate"] == 0.0


def test_contrasts_name_registered_pairs():
    pairs = {tuple(p) for _s, ps in L.RUNS.values() for p in ps}
    for first, second, runs in B.CONTRASTS.values():
        held = {tuple(p) for r in runs for p in L.RUNS[r][1]}
        assert first in held and second in held and held <= pairs
        assert len({L.RUNS[r][0] for r in runs}) == 1      # one seed block per contrast


def test_double_contrast_is_a_difference_of_differences():
    games = []
    for i in range(200):
        for leg in T.LEGS:
            games.append(game("a1", "x", i, leg, int(i < 120), int(i >= 120)))
            games.append(game("a0", "x", i, leg, int(i < 100), int(i >= 100)))
            games.append(game("b1", "x", i, leg, int(i < 140), int(i >= 140)))
            games.append(game("b0", "x", i, leg, int(i < 100), int(i >= 100)))
    pairs = [("a1", "x"), ("a0", "x"), ("b1", "x"), ("b0", "x")]
    got = B.double_contrast(games, pairs, reps=300)
    first = B.F.paired_contrast(games, pairs[0], pairs[1], reps=50)["elo_contrast"]
    second = B.F.paired_contrast(games, pairs[2], pairs[3], reps=50)["elo_contrast"]
    assert got["elo"] == pytest.approx(first - second) and got["elo"] < 0
    assert got["ci95"][0] < got["elo"] < got["ci95"][1]
