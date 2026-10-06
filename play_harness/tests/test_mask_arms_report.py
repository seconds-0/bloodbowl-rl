"""The masked-copy report: the registered verdict rule and the paired behaviour table."""
import os
import sys

import pytest

from play_harness import tournament as T

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__)))), "tools"))
import mask_arms_launch as L  # noqa: E402
import mask_arms_report as R  # noqa: E402


def game(seed, leg, a_td, b_td, a_counts=None, b_counts=None, masks=("m1",)):
    a_side = 0 if leg == "A_home" else 1
    behaviour = [dict(T.new_behaviour(), team_turns=16, team_turns_holding_ball=8, turnovers=4)
                 for _ in (0, 1)]
    behaviour[a_side].update(a_counts or {})
    behaviour[1 - a_side].update(b_counts or {})
    score = [0, 0]
    score[a_side], score[1 - a_side] = a_td, b_td
    mask_list = [None, None]
    stats = [None, None]
    if masks:
        mask_list[a_side] = sorted(masks)
        stats[a_side] = {m: {"held": 10, "applied": 4, "fallback": 1, "mass": 2.5} for m in masks}
    return {"pair": ["A", "B"], "game_index": seed, "leg": leg, "engine_seed": 1000 + seed,
            "teams": ["Orc", "Wood Elf"], "score": score, "a_td": a_td, "b_td": b_td,
            "result_a": "W" if a_td > b_td else ("D" if a_td == b_td else "L"),
            "c_steps": 700, "behaviour": behaviour, "masks": mask_list, "mask_stats": stats}


def arm(a_wins, b_wins, draws=0, **kw):
    games, seed = [], 0
    for wins, score in ((a_wins, (1, 0)), (b_wins, (0, 1)), (draws, (0, 0))):
        for _ in range(wins):
            games.append(game(seed, "A_home" if seed % 2 else "B_home", *score, **kw))
            seed += 1
    return games


def test_verdicts_follow_the_registered_thresholds():
    assert R.strength(arm(700, 300), reps=300)["verdict"] == ["better", "non-inferior"]
    assert R.strength(arm(300, 700), reps=300)["verdict"] == ["worse"]
    even = R.strength(arm(2000, 2000), reps=300)
    assert even["verdict"] == ["non-inferior"] and abs(even["elo_decisive"]) < 1e-9
    assert even["elo_decisive_ci95"][0] > -20 and even["elo_decisive_ci95"][1] < 20
    assert R.strength(arm(50, 50), reps=300)["verdict"] == ["inconclusive"]
    # Inside (-20, 0): worse and non-inferior at once, both reported.
    slight = R.strength(arm(19400, 20600), reps=300)
    assert slight["verdict"] == ["worse", "non-inferior"]


def test_behaviour_table_reads_each_side_from_its_own_seat():
    games = arm(30, 30, a_counts={"activations": 96, "block_targets": 20},
                b_counts={"activations": 48, "block_targets": 7})
    rows = {r["metric"]: r for r in R.behaviour_table(games, reps=200)}
    act = rows["activations per team turn"]
    assert (act["a"], act["b"], act["a_minus_b"]) == (6.0, 3.0, 3.0)
    assert act["ci95"] == [3.0, 3.0]
    blocks = rows["block targets chosen per game"]
    assert (blocks["a"], blocks["b"]) == (20.0, 7.0)
    assert rows["touchdowns per game"]["a"] == pytest.approx(0.5)
    assert rows["possession (turns ended holding the ball)"]["a"] == 0.5
    assert R.mask_table(games) == {"m1": {"held": 10.0, "applied": 4.0, "fallback": 1.0,
                                          "mass": 2.5}}


def registered_run(name="m1", masks=("m1",), n=8, **over):
    """A small run shaped like a registered arm (the game count is overridden)."""
    seed0 = R.REGISTERED[name][1]
    games = []
    for i in range(n // 2):
        for leg in T.LEGS:
            g = game(i, leg, 1, 0, masks=masks)
            g.update(engine_seed=seed0 + i, natural=True, integrity={k: 0 for k in R.HARD_COUNTERS})
            games.append(g)
    sha = {"sha256": R.CHAIN41_SHA256}
    spec = {"mode": "sample", "temperature": 1.0}
    manifest = {"pairs": [["A", "B", n]], "checkpoints": {"A": sha, "B": sha}, "seed0": seed0,
                "kernel": "native", "games_per_worker": 32,
                "players": {"A": dict(spec, masks=sorted(masks)) if masks else dict(spec),
                            "B": dict(spec)}}
    manifest.update(over)
    return games, manifest


def test_an_arm_must_be_the_registered_one(monkeypatch):
    monkeypatch.setattr(R, "GAMES_PER_ARM", 8)
    games, manifest = registered_run()
    R.check_arm("m1", games, manifest, ["m1"])
    R.check_arm("control", *registered_run("control", ()), [])

    def refused(name="m1", masks=("m1",), games=games, manifest=manifest):
        with pytest.raises(SystemExit):
            R.check_arm(name, games, manifest, list(masks))

    spec = {"mode": "sample", "temperature": 1.0}
    refused("m2", ("m2",))                                           # another arm's masks
    refused(manifest=dict(manifest, players={"A": dict(spec, masks=["m1"]),
                                             "B": dict(spec, masks=["m1"])}))
    refused(manifest=dict(manifest, checkpoints={"A": {"sha256": R.CHAIN41_SHA256},
                                                 "B": {"sha256": "y"}}))
    refused(manifest=dict(manifest, checkpoints={"A": {"sha256": "z"}, "B": {"sha256": "z"}}))
    refused(manifest=dict(manifest, seed0=1))                        # another seed block
    refused(manifest=dict(manifest, kernel="torch"))
    refused(manifest=dict(manifest, games_per_worker=1))
    refused(manifest=dict(manifest, players={"A": dict(spec, masks=["m1"], temperature=0.5),
                                             "B": dict(spec)}))
    refused(games=games[:-1])                                        # a leg missing
    refused(games=games + games[:1])                                 # a leg twice
    bad = [dict(g) for g in games]
    bad[0]["integrity"] = dict(bad[0]["integrity"], illegal=1)
    refused(games=bad)
    bad = [dict(g) for g in games]
    bad[0]["natural"] = False
    refused(games=bad)
    with pytest.raises(SystemExit):                                  # not played to the end
        R.check_arm("m1", games, manifest, ["m1"], run_dir="/nonexistent")
    # Outside the registered design only the structure is checked.
    R.check_arm("pilot", games, dict(manifest, games_per_worker=1), ["m1"], registered=False)


def test_control_legs_and_roster_split():
    games = [game(i, leg, 1, 0, masks=()) for i in range(4) for leg in T.LEGS]
    for g in games:
        g["action_trail_sha256"] = f"trail{g['game_index']}"
    assert R.control_checks(games) == {"seeds": 4, "seeds_with_identical_legs": 4,
                                       "records_with_a_mask": 0}
    classes = {r["class"] for r in R.roster_split(arm(6, 6), reps=50)}
    assert classes == {"bash", "agile"}


def test_launcher_arms_are_the_registered_ones():
    assert {a: v[1:] for a, v in L.ARMS.items()} == {
        "m1": ("m1", 23000000), "m2": ("m2", 23100000), "m3": ("m3", 23200000),
        "m123": ("m1,m2,m3", 23300000), "control": (None, 23400000)}
    argv = L.argv_for("m123", "abc")
    assert "--tournament-arg=--mask" in argv and "--tournament-arg=chain41m123=m1,m2,m3" in argv
    assert argv[argv.index("--seed0") + 1] == "23300000"
    assert argv[argv.index("--games-per-worker") + 1] == "32"
    assert any(a.startswith("chain41m123,chain41,3200") for a in argv)
    assert not any("mask" in a for a in L.argv_for("control", "abc")[3:] if a.startswith("--t"))
