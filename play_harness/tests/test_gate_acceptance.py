"""Tests for tools/gate_acceptance.py: a run is held to the registered plan, not to its own manifest."""
import copy
import importlib.util
import json
import os

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SPEC = importlib.util.spec_from_file_location("gate_acceptance", os.path.join(ROOT, "tools", "gate_acceptance.py"))
ga = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ga)

COMMIT = "0bf9ce01c68cad51dced047ac6767a677afa67a2"
SHA_A = "a" * 64
SHA_B = "b" * 64
SEED0 = 20700000


def plan():
    return {"seed0": SEED0, "games_per_worker": 32, "commit": COMMIT,
            "pairs": [("chainA", "chainB", 8), ("chainA", "offense", 8)],
            "checkpoints": {"chainA": SHA_A, "chainB": SHA_B}}


def manifest():
    return {"seed0": SEED0, "games_per_worker": 32, "harness_git_head": COMMIT, "mode": "sample",
            "pairs": [["chainA", "chainB", 8], ["chainA", "offense", 8]],
            "players": {"chainA": {"mode": "sample", "temperature": 1.0},
                        "chainB": {"mode": "sample", "temperature": 1.0},
                        "offense": {"bot": "offense"}},
            "checkpoints": {"chainA": {"sha256": SHA_A}, "chainB": {"sha256": SHA_B}}}


def games():
    rows = []
    for pair, modes, temps in ((["chainA", "chainB"], ["sample", "sample"], [1.0, 1.0]),
                               (["chainA", "offense"], ["sample", "scripted"], [1.0, None])):
        for i in range(4):
            for leg in ga.LEGS:
                rows.append({"pair": pair, "engine_seed": SEED0 + i, "leg": leg, "natural": True,
                             "modes": modes, "temperatures": temps,
                             "integrity": {"illegal": 0, "error_episodes": 0}})
    return rows


def write_run(tmp_path, m, g, complete=True):
    (tmp_path / "manifest.json").write_text(json.dumps(m))
    (tmp_path / "games.jsonl").write_text("".join(json.dumps(row) + "\n" for row in g))
    if complete is not None:
        (tmp_path / "COMPLETE.json").write_text(json.dumps({"complete": complete}))
    return str(tmp_path)


def test_a_run_that_matches_the_plan_is_accepted(tmp_path):
    assert ga.accept(write_run(tmp_path, manifest(), games()), plan()) == []


def test_a_merge_that_silently_dropped_a_whole_pair_is_rejected(tmp_path):
    m = manifest()
    m["pairs"] = [["chainA", "chainB", 8]]
    g = [row for row in games() if row["pair"] == ["chainA", "chainB"]]
    problems = ga.accept(write_run(tmp_path, m, g), plan())
    assert any("missing [('chainA', 'offense', 8)]" in p for p in problems)
    assert any("scheduled games missing" in p for p in problems)


@pytest.mark.parametrize("key,value,needle", [
    ("games_per_worker", 1, "games_per_worker 1 != registered 32"),
    ("seed0", SEED0 + 1, "seed0"),
    ("harness_git_head", "f" * 40, "harness commit"),
    ("mode", "argmax", "mode 'argmax'"),
])
def test_a_manifest_field_off_the_plan_is_rejected(tmp_path, key, value, needle):
    m = manifest()
    m[key] = value
    assert any(needle in p for p in ga.accept(write_run(tmp_path, m, games()), plan()))


def test_a_legacy_manifest_without_games_per_worker_counts_as_one(tmp_path):
    m = manifest()
    del m["games_per_worker"]
    assert any("games_per_worker 1" in p for p in ga.accept(write_run(tmp_path, m, games()), plan()))


def test_a_swapped_checkpoint_is_rejected(tmp_path):
    m = manifest()
    m["checkpoints"]["chainB"]["sha256"] = "c" * 64
    assert any("checkpoint chainB" in p for p in ga.accept(write_run(tmp_path, m, games()), plan()))


def test_an_unregistered_checkpoint_is_rejected(tmp_path):
    m = manifest()
    m["checkpoints"]["chainZ"] = {"sha256": "d" * 64}
    assert any("unregistered checkpoints" in p for p in ga.accept(write_run(tmp_path, m, games()), plan()))


def test_a_player_at_another_temperature_is_rejected(tmp_path):
    m = manifest()
    m["players"]["chainB"]["temperature"] = 0.75
    assert any("player chainB" in p for p in ga.accept(write_run(tmp_path, m, games()), plan()))


def test_missing_duplicate_and_out_of_block_games_are_rejected(tmp_path):
    g = games()
    dropped = g.pop(0)
    g.append(copy.deepcopy(g[0]))
    stray = copy.deepcopy(dropped)
    stray["engine_seed"] = SEED0 + 999
    g.append(stray)
    problems = ga.accept(write_run(tmp_path, manifest(), g), plan())
    assert any("scheduled games missing" in p for p in problems)
    assert any("recorded more than once" in p for p in problems)
    assert any("outside the seed block" in p for p in problems)


def test_one_leg_played_twice_instead_of_both_legs_is_rejected(tmp_path):
    g = games()
    g[1]["leg"] = g[0]["leg"]
    problems = ga.accept(write_run(tmp_path, manifest(), g), plan())
    assert any("recorded more than once" in p for p in problems)
    assert any("scheduled games missing" in p for p in problems)


def test_truncated_games_and_integrity_counters_are_rejected(tmp_path):
    g = games()
    g[0]["natural"] = False
    g[1]["integrity"]["illegal"] = 2
    problems = ga.accept(write_run(tmp_path, manifest(), g), plan())
    assert any("not a natural ending" in p for p in problems)
    assert any("integrity {'illegal': 2}" in p for p in problems)


def test_a_run_without_a_completion_record_is_rejected(tmp_path):
    assert any("COMPLETE.json is missing" in p
               for p in ga.accept(write_run(tmp_path, manifest(), games(), complete=None), plan()))


def test_the_cli_prints_a_verdict_and_sets_the_exit_code(tmp_path, capsys):
    run = write_run(tmp_path, manifest(), games())
    argv = ["--run-dir", run, "--seed0", str(SEED0), "--games-per-worker", "32", "--commit", COMMIT,
            "--pair", "chainA,chainB,8", "--pair", "chainA,offense,8",
            "--checkpoint", f"chainA={SHA_A}", "--checkpoint", f"chainB={SHA_B}"]
    assert ga.main(argv) == 0
    assert "GATE-ACCEPTED 16 games, 2 pairs" in capsys.readouterr().out
    assert ga.main(argv[:-2]) == 1
    assert "GATE-REJECTED unregistered checkpoints" in capsys.readouterr().out


# ---- registered temperatures: a plan may hold a player to a temperature other than 1 ----

def tempered_plan():
    return {**plan(), "temperatures": {"chainA": 0.5}}


def tempered_run():
    m = manifest()
    m["players"]["chainA"]["temperature"] = 0.5
    rows = []
    for pair in (["chainA", "chainB"], ["chainA", "offense"]):
        for i in range(4):
            for leg in ga.LEGS:
                home, away = pair if leg == "A_home" else pair[::-1]
                side = lambda name: (("scripted", None) if name == "offense"          # noqa: E731
                                     else ("sample", 0.5 if name == "chainA" else 1.0))
                rows.append({"pair": pair, "engine_seed": SEED0 + i, "leg": leg, "natural": True,
                             "home": home, "away": away,
                             "modes": [side(home)[0], side(away)[0]],
                             "temperatures": [side(home)[1], side(away)[1]],
                             "integrity": {"illegal": 0, "error_episodes": 0}})
    return m, rows


def test_a_run_at_its_registered_temperatures_is_accepted(tmp_path):
    m, g = tempered_run()
    assert ga.accept(write_run(tmp_path, m, g), tempered_plan()) == []


def test_a_tempered_run_is_rejected_by_a_plan_that_registers_no_temperature(tmp_path):
    m, g = tempered_run()
    problems = ga.accept(write_run(tmp_path, m, g), plan())
    assert any("player chainA is not sample mode at temperature 1.0" in p for p in problems)
    assert any("temperature 0.5" in p for p in problems)


def test_a_unit_temperature_run_is_rejected_by_a_plan_that_registers_one(tmp_path):
    problems = ga.accept(write_run(tmp_path, manifest(), games()), tempered_plan())
    assert any("player chainA is not sample mode at temperature 0.5" in p for p in problems)


def test_a_game_whose_side_played_at_another_temperature_is_rejected(tmp_path):
    m, g = tempered_run()
    g[0]["temperatures"] = [1.0, 1.0]            # chainA is home in the first game
    problems = ga.accept(write_run(tmp_path, m, g), tempered_plan())
    assert any("chainA played at temperature 1.0, registered 0.5" in p for p in problems)


def test_the_registered_temperature_belongs_to_the_player_not_to_the_side(tmp_path):
    m, g = tempered_run()
    b_home = next(row for row in g if row["pair"] == ["chainA", "chainB"] and row["leg"] == "B_home")
    assert b_home["temperatures"] == [1.0, 0.5]
    b_home["temperatures"] = [0.5, 1.0]          # the two sides' values swapped
    problems = ga.accept(write_run(tmp_path, m, g), tempered_plan())
    assert any("chainB played at temperature 0.5, registered 1.0" in p for p in problems)
    assert any("chainA played at temperature 1.0, registered 0.5" in p for p in problems)


def test_a_tempered_game_without_its_seats_is_rejected(tmp_path):
    m, g = tempered_run()
    del g[0]["home"]
    g[1]["home"], g[1]["away"] = g[1]["away"], g[1]["home"]
    problems = ga.accept(write_run(tmp_path, m, g), tempered_plan())
    assert sum("are not the pair's seats for this leg" in p for p in problems) == 2


def test_a_scripted_side_with_a_temperature_is_rejected(tmp_path):
    m, g = tempered_run()
    row = next(row for row in g if row["pair"] == ["chainA", "offense"])
    row["temperatures"] = [0.5, 1.0]
    problems = ga.accept(write_run(tmp_path, m, g), tempered_plan())
    assert any("offense played at temperature 1.0, registered None" in p for p in problems)


def test_a_checkpoint_side_recorded_as_scripted_is_rejected(tmp_path):
    m, g = tempered_run()
    g[0]["modes"], g[0]["temperatures"] = ["scripted", "sample"], [None, 1.0]     # chainA is home
    problems = ga.accept(write_run(tmp_path, m, g), tempered_plan())
    assert any("chainA played in mode 'scripted', a registered checkpoint samples" in p for p in problems)
    assert any("chainA played at temperature None, registered 0.5" in p for p in problems)


def test_a_bot_side_recorded_as_sampling_is_rejected(tmp_path):
    m, g = tempered_run()
    row = next(row for row in g if row["pair"] == ["chainA", "offense"] and row["leg"] == "A_home")
    row["modes"] = ["sample", "sample"]
    problems = ga.accept(write_run(tmp_path, m, g), tempered_plan())
    assert any("offense played in mode 'sample', a bot is scripted" in p for p in problems)


def test_a_temperature_registered_for_a_bot_or_an_unknown_player_is_rejected(tmp_path):
    m, g = tempered_run()
    bad = {**tempered_plan(), "temperatures": {"chainA": 0.5, "offense": 0.5, "chainZ": 0.5}}
    problems = ga.accept(write_run(tmp_path, m, g), bad)
    assert any("scripted bot offense" in p for p in problems)
    assert any("['chainZ']" in p for p in problems)


def test_the_cli_takes_registered_temperatures(tmp_path, capsys):
    m, g = tempered_run()
    run = write_run(tmp_path, m, g)
    argv = ["--run-dir", run, "--seed0", str(SEED0), "--games-per-worker", "32", "--commit", COMMIT,
            "--pair", "chainA,chainB,8", "--pair", "chainA,offense,8",
            "--checkpoint", f"chainA={SHA_A}", "--checkpoint", f"chainB={SHA_B}"]
    assert ga.main(argv) == 1
    assert "GATE-REJECTED" in capsys.readouterr().out
    assert ga.main(argv + ["--temperature", "chainA=0.5"]) == 0
    assert "GATE-ACCEPTED" in capsys.readouterr().out
    with pytest.raises(SystemExit):
        ga.main(argv + ["--temperature", "chainA=0"])
