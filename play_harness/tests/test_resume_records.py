"""A resume holds every record already in games.jsonl to the manifest before it
plays anything.

A resume used to read the existing records for their task keys only, so records
of another setting, or records that fail the game contract, rode along under the
run's manifest. Each case here changes one thing in a finished run's
games.jsonl and resumes: the resume is refused, names the record, and leaves
both files as they were.

Games use seeded random networks and the engine's scripted bots; the searched
pair runs at k = 2, n = 2 as in test_search_tournament.
"""
import contextlib
import io
import json
import os

import pytest

from play_harness import tournament as T
from play_harness.policy import random_policy

from .test_search_tournament import write_blob

SEED0 = 53000


@pytest.fixture(scope="module")
def blobs(tmp_path_factory):
    folder = tmp_path_factory.mktemp("blobs")
    out = {}
    for name, seed in (("A", 1), ("S", 11)):
        os.makedirs(folder / name)
        out[name] = write_blob(folder / name, random_policy(seed=seed, scale=0.05))
    return out


def tournament(args, out, workers=1):
    """play_harness.tournament through its command line. Returns (exit code or the
    SystemExit message, what it printed)."""
    patch = pytest.MonkeyPatch()
    patch.setenv("OMP_NUM_THREADS", "1")
    patch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    text = io.StringIO()
    try:
        with contextlib.redirect_stdout(text):
            try:
                code = T.main([*args, "--workers", str(workers), "--out-dir", str(out)])
            except SystemExit as exc:
                code = str(exc)
    finally:
        patch.undo()
    return code, text.getvalue()


def plain_args(blobs):
    """A masked network, the same network on a sampling offset and at another
    temperature, and a bot: every per-side setting a record carries."""
    return ["--checkpoint", f"A={blobs['A']}", "--checkpoint", f"B={blobs['A']}",
            "--bot", "off=offense", "--pair", "A,B,4", "--pair", "B,off,2",
            "--mask", "A=m1", "--sampling-offset", "B=3", "--temperature", "B=0.9",
            "--seed0", str(SEED0)]


def searched_args(blobs):
    return ["--checkpoint", f"S={blobs['S']}", "--checkpoint", f"C={blobs['S']}",
            "--pair", "S,C,2", "--mask", "S=m1", "--mask", "C=m1", "--sampling-offset", "C=1",
            "--search", "S=2:2:0", "--seed0", str(SEED0 + 500)]


@pytest.fixture(scope="module")
def runs(tmp_path_factory, blobs):
    """Two finished runs: one without a search seat, one with."""
    folder = tmp_path_factory.mktemp("runs")
    assert tournament(plain_args(blobs), folder / "plain")[0] == 0
    assert tournament(searched_args(blobs), folder / "searched", workers=2)[0] == 0
    return folder


def read(folder):
    with open(os.path.join(str(folder), "games.jsonl")) as f:
        return [json.loads(line) for line in f]


def resume_after(runs, name, args, tmp_path, change):
    """Copy a finished run, let `change` edit its list of records in place, resume
    it. Returns (exit code or refusal, printed text, folder)."""
    folder = tmp_path / name
    os.makedirs(folder)
    for fname in ("manifest.json", "COMPLETE.json"):
        with open(runs / name / fname) as src, open(folder / fname, "w") as dst:
            dst.write(src.read())
    games = read(runs / name)
    change(games)
    with open(folder / "games.jsonl", "w") as f:
        f.writelines(g if isinstance(g, str) else json.dumps(g, separators=(",", ":")) + "\n"
                     for g in games)
    before = {fname: open(folder / fname).read() for fname in ("manifest.json", "games.jsonl")}
    code, printed = tournament(args, folder)
    if code != 0:                                       # a refusal changes neither file
        assert {fname: open(folder / fname).read() for fname in before} == before
    return code, printed, folder


def first(games, pair, leg="A_home", index=0):
    return next(g for g in games if g["pair"] == list(pair) and g["leg"] == leg
                and g["game_index"] == index)


def test_an_untouched_run_resumes_and_plays_nothing(runs, blobs, tmp_path):
    for name, args, count in (("plain", plain_args(blobs), 6), ("searched", searched_args(blobs), 2)):
        code, printed, _ = resume_after(runs, name, args, tmp_path, lambda games: None)
        assert code == 0 and f"{count} already recorded, 0 to play" in printed


def test_the_record_check_reads_what_the_harness_writes(runs):
    """On real records: no problem, and each side's settings are the player's."""
    for name in ("plain", "searched"):
        with open(runs / name / "manifest.json") as f:
            manifest = json.load(f)
        scheduled = {T.task_key(a, b, i, leg) for a, b, n in manifest["pairs"]
                     for i in range(n // 2) for leg in T.LEGS}
        games = read(runs / name)
        assert len(games) == len(scheduled)
        for game in games:
            assert T.recorded_game_problems(game, manifest, scheduled) == []
    game = first(read(runs / "plain"), ("B", "off"), "B_home")       # off HOME, B AWAY
    assert (game["bots"], game["modes"], game["temperatures"]) == \
        (["offense", None], ["scripted", "sample"], [None, 0.9])
    assert (game["masks"], game["seed_offsets"]) == ([None, None], [0, 3])
    assert first(read(runs / "plain"), ("A", "B"))["masks"] == [["m1"], None]


PLAIN_CASES = [
    # the game contract (check_record)
    (lambda g: first(g, ("A", "B")).update(natural=False), "unnatural ending"),
    (lambda g: first(g, ("A", "B"))["integrity"].update(illegal=1), "integrity"),
    (lambda g: first(g, ("A", "B")).update(forwards=[1, 1]), "forwards [1, 1]"),
    # each side's settings are its player's in the manifest
    (lambda g: first(g, ("A", "B")).update(masks=[None, None]),
     "A's masks None is not the manifest's ['m1']"),
    (lambda g: first(g, ("A", "B")).update(masks=[["m1", "m3"], None]),
     "A's masks ['m1', 'm3'] is not the manifest's ['m1']"),
    (lambda g: first(g, ("A", "B"), "B_home").update(masks=[["m1"], ["m1"]]),
     "B's masks ['m1'] is not the manifest's None"),
    (lambda g: first(g, ("A", "B")).update(seed_offsets=[0, 0]),
     "B's sampling offset 0 is not the manifest's 3"),
    (lambda g: first(g, ("A", "B")).update(seed_offsets=[3, 3]),
     "A's sampling offset 3 is not the manifest's 0"),
    (lambda g: first(g, ("A", "B")).pop("seed_offsets"),
     "B's sampling offset 0 is not the manifest's 3"),
    (lambda g: first(g, ("A", "B")).update(temperatures=[1.0, 1.0]),
     "B's temperature 1.0 is not the manifest's 0.9"),
    (lambda g: first(g, ("A", "B")).update(modes=["argmax", "sample"]),
     "A's mode 'argmax' is not the manifest's 'sample'"),
    (lambda g: first(g, ("B", "off")).update(bots=[None, "contact"]),
     "off's bot 'contact' is not the manifest's 'offense'"),
    (lambda g: first(g, ("B", "off")).update(bots=[None, None]),
     "off's bot None is not the manifest's 'offense'"),
    # the record is the scheduled game
    (lambda g: first(g, ("A", "B"), index=1).update(engine_seed=SEED0),
     f"engine seed {SEED0} is not seed0 + 1"),
    (lambda g: first(g, ("A", "B")).update(game_index=7, engine_seed=SEED0 + 7),
     "A,B game 7 A_home is not in this run's schedule"),
    (lambda g: first(g, ("A", "B")).update(pair=["A", "zz"]),
     "A,zz game 0 A_home is not in this run's schedule"),
    (lambda g: first(g, ("A", "B")).update(home="B", away="A"),
     "seats B,A are not the leg's A,B"),
    (lambda g: g.append(first(g, ("A", "B"))), "A|B|0|A_home is recorded twice"),
    (lambda g: g.append('{"pair": ["A", "B"], "game_ind\n'), "line 7: not JSON"),
    (lambda g: g.append({"pair": ["A", "B"]}), "line 7: malformed record (KeyError"),
    # a game without a searching player carries no search field
    (lambda g: first(g, ("A", "B")).update(search=[{"k": 2}, None]),
     "A's search setting {'k': 2} is not the manifest's None"),
    (lambda g: first(g, ("A", "B")).update(search_stats=[{"rollouts": 4}, None]),
     "no player of the game searches, yet it carries ['search_stats']"),
    (lambda g: first(g, ("A", "B")).update(reward_manifest_sha256="r" * 64),
     "no player of the game searches, yet it carries ['reward_manifest_sha256']"),
]


@pytest.mark.parametrize("change, needle", PLAIN_CASES)
def test_a_resume_refuses_a_record_that_is_not_a_game_of_the_run(runs, blobs, tmp_path, change,
                                                                 needle):
    code, printed, _ = resume_after(runs, "plain", plain_args(blobs), tmp_path, change)
    assert isinstance(code, str) and needle in code, code
    assert "holds 1 record(s) that are not games of this run; nothing was played" in code
    assert "to play" not in printed                      # refused before the pool starts


SEARCHED_CASES = [
    (lambda g: g[0].pop("search"), "S's search setting None is not the manifest's"),
    (lambda g: g[0].update(search=[None, None]), "S's search setting None is not the manifest's"),
    (lambda g: [s.update(n=4) for s in g[0]["search"] if s], "S's search setting"),
    (lambda g: [s.update(delta="inf") for s in g[0]["search"] if s], "S's search setting"),
    (lambda g: g[0].update(search=[g[0]["search"][0] or g[0]["search"][1]] * 2),
     "C's search setting"),
    (lambda g: g[0].update(reward_manifest_sha256="r" * 64),
     "its reward manifest is not the manifest's"),
    (lambda g: g[0].pop("reward_manifest_sha256"), "its reward manifest is not the manifest's"),
    (lambda g: g[0].update(integrity_checks=g[0]["integrity_checks"][:-1]),
     "its integrity checks are not the manifest's"),
    (lambda g: [s.update(error_rollouts=1) for s in g[0]["search_stats"] if s],
     "search statistics"),
    (lambda g: g[0].update(masks=[None, None]), "'s masks None is not the manifest's ['m1']"),
]


@pytest.mark.parametrize("change, needle", SEARCHED_CASES)
def test_a_resume_refuses_a_searched_record_that_is_not_the_manifests(runs, blobs, tmp_path,
                                                                      change, needle):
    code, _, _ = resume_after(runs, "searched", searched_args(blobs), tmp_path, change)
    assert isinstance(code, str) and needle in code, code
    assert "line 1: " in code


def test_a_refused_resume_names_the_first_few_records_and_counts_the_rest(runs, blobs, tmp_path):
    def all_wrong(games):
        for game in games:
            game["natural"] = False
    code, _, _ = resume_after(runs, "plain", plain_args(blobs), tmp_path, all_wrong)
    assert "holds 6 record(s) that are not games of this run" in code
    assert code.count("unnatural ending") == T.MAX_RESUME_PROBLEMS == 5
    assert [f"line {n}: " in code for n in range(1, 7)] == [True] * 5 + [False]
    assert code.rstrip().endswith("... and 1 more")


def test_an_interrupted_run_with_a_bad_record_plays_nothing(runs, blobs, tmp_path):
    """Half the games are there and one is wrong: the resume stops before it
    plays the other half."""
    def half_with_a_bad_one(games):
        del games[3:]
        games[1]["seed_offsets"] = [9, 9]
    code, printed, folder = resume_after(runs, "plain", plain_args(blobs), tmp_path,
                                         half_with_a_bad_one)
    assert isinstance(code, str) and "line 2: " in code and "sampling offset 9" in code
    assert len(read(folder)) == 3 and "to play" not in printed
    # With the record as it was, the same half resumes and finishes the run.
    def half(games):
        del games[3:]
    code, printed, folder = resume_after(runs, "plain", plain_args(blobs), tmp_path / "good", half)
    assert code == 0 and "6 tasks, 3 already recorded, 3 to play" in printed
    finished = {T.task_key(*g["pair"], g["game_index"], g["leg"]): g for g in read(folder)}
    for game in read(runs / "plain"):
        twin = finished[T.task_key(*game["pair"], game["game_index"], game["leg"])]
        assert {k: v for k, v in twin.items() if k not in ("seconds", "pid")} == \
            {k: v for k, v in game.items() if k not in ("seconds", "pid")}
