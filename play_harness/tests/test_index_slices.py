"""A run of the tournament that starts at a later game index (--index0).

  the flag     --index0 shifts the game indexes and the engine seeds, the manifest
               carries the key only when it is not 0, and a run without the flag
               writes what the code before the flag wrote, byte for byte;
  slices       three pairs (two networks, a network and a bot, two bots) played
               in one run and as two runs on consecutive index ranges: the same
               records;
  resume       a resume refuses another index0 and finishes an interrupted slice;
  batching     batched workers play a slice's own indexes;
  the droplet  tools/droplet_tournament.py verifies a slice against its index.

Games use seeded random networks and the engine's scripted bots.
"""
import contextlib
import io
import json
import os
import subprocess
import sys

import pytest

from play_harness import tournament as T
from play_harness.policy import random_policy
from tools import droplet_tournament as D

from .conftest import ROOT
from .test_search_tournament import write_blob

# The fields of a game record that are not the game: wall time and the worker's
# process id. Every other field must be equal between a split and an unsplit run.
NOT_THE_GAME = ("seconds", "pid")
# The last commit before --index0 existed.
BEFORE_INDEX0 = "33428b3098e74317b2c2bdd2e7fb03f516f2b969"
SEED0 = 51000
PAIRS = (("A", "B"), ("A", "off"), ("off", "con"))


@pytest.fixture(scope="module")
def blobs(tmp_path_factory):
    """Two seeded random networks as checkpoint blobs: the networks of
    test_tournament."""
    folder = tmp_path_factory.mktemp("blobs")
    out = {}
    for name, seed in (("A", 1), ("B", 2)):
        os.makedirs(folder / name)
        out[name] = write_blob(folder / name, random_policy(seed=seed, scale=0.05))
    return out


def tournament(out, *args, workers=1, code=0):
    """play_harness.tournament through its command line. Returns what it printed."""
    patch = pytest.MonkeyPatch()
    patch.setenv("OMP_NUM_THREADS", "1")
    patch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    text = io.StringIO()
    try:
        with contextlib.redirect_stdout(text):
            got = T.main([*args, "--workers", str(workers), "--out-dir", str(out)])
    finally:
        patch.undo()
    assert got == code, text.getvalue()
    return text.getvalue()


def plain_args(blobs, n, seed0=SEED0):
    return ["--checkpoint", f"A={blobs['A']}", "--checkpoint", f"B={blobs['B']}",
            "--bot", "off=offense", "--bot", "con=contact",
            *(arg for a, b in PAIRS for arg in ("--pair", f"{a},{b},{n}")),
            "--seed0", str(seed0)]


def load(folder):
    with open(os.path.join(str(folder), "manifest.json")) as f:
        manifest = json.load(f)
    with open(os.path.join(str(folder), "games.jsonl")) as f:
        return manifest, [json.loads(line) for line in f if line.strip()]


def the_game(record, ignore=NOT_THE_GAME):
    return {key: value for key, value in record.items() if key not in ignore}


def key(record):
    return (tuple(record["pair"]), record["game_index"], record["leg"])


# ---- the flag ----------------------------------------------------------------------------
def test_index0_shifts_the_schedule_and_nothing_else():
    names, pairs = ["x", "y", "z"], [("x", "y", 4), ("z", "y", 2)]
    base = T.schedule(names, None, seed0=0, pairs=pairs)
    assert T.schedule(names, None, seed0=0, pairs=pairs, index0=0) == base
    shifted = T.schedule(names, None, seed0=0, pairs=pairs, index0=10)
    assert shifted == [(a, b, i + 10, leg) for a, b, i, leg in base]
    assert shifted[:2] == [("x", "y", 10, "A_home"), ("x", "y", 10, "B_home")]
    assert [t[2] for t in shifted] == [10, 10, 10, 10, 11, 11]     # still interleaved by index
    with pytest.raises(ValueError, match="first game index"):
        T.schedule(names, None, seed0=0, pairs=pairs, index0=-1)
    # The engine seed of a task is seed0 + its index, whatever the first index is.
    assert T.pair_seating("x", "y", 12, "A_home", 500)[2] == 512
    assert T.task_key(*shifted[0]) == "x|y|10|A_home"


def test_a_negative_index0_is_refused_before_anything_is_written(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    with pytest.raises(SystemExit, match="first game index"):
        T.main(["--bot", "c=contact", "--bot", "o=offense", "--pair", "c,o,2", "--seed0", "1",
                "--workers", "1", "--out-dir", str(tmp_path / "x"), "--index0", "-1"])
    assert not (tmp_path / "x").exists()


def _old_tournament_module(folder):
    """play_harness/tournament.py as it was before --index0, as a module of its own
    beside the package it imports. Skips when the commit is not in this clone."""
    proc = subprocess.run(["git", "-C", ROOT, "show", f"{BEFORE_INDEX0}:play_harness/tournament.py"],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        pytest.skip(f"commit {BEFORE_INDEX0[:7]} is not in this clone")
    source = proc.stdout
    assert "index0" not in source
    for relative, absolute in (("from . import engine as E", "from play_harness import engine as E"),
                               ("from . import search as S", "from play_harness import search as S"),
                               ("from .activations import", "from play_harness.activations import"),
                               ("from .policy import", "from play_harness.policy import")):
        assert source.count(relative) == 1, relative
        source = source.replace(relative, absolute)
    assert "from ." not in source
    with open(os.path.join(str(folder), "tournament_before_index0.py"), "w") as f:
        f.write(source)
    return "tournament_before_index0"


def _run_module(module, args, extra_path=None):
    """Run a tournament module's main in a process of its own, from the harness root."""
    env = dict(os.environ, OMP_NUM_THREADS="1",
               PYTHONPATH=os.pathsep.join(filter(None, [extra_path, ROOT])))
    env.pop(T.GAMES_PER_WORKER_ENV, None)
    code = f"import sys, {module} as m; sys.exit(m.main(sys.argv[1:]))"
    proc = subprocess.run([sys.executable, "-c", code, *args], cwd=ROOT, env=env,
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return proc.stdout


def test_a_run_without_the_flag_writes_what_the_code_before_it_wrote(blobs, tmp_path):
    """The same command line through the tournament module of the last commit
    before --index0 and through today's: the manifest is the same bytes, and the
    records are the same keys in the same order with the same values, wall time
    and process id apart. Networks (one masked, one on a sampling offset) and bots."""
    module = _old_tournament_module(tmp_path)
    args = plain_args(blobs, 4, seed0=SEED0 + 900) + \
        ["--mask", "A=m1", "--sampling-offset", "B=3", "--workers", "1"]
    printed = {}
    for name, mod, path in (("before", module, str(tmp_path)),
                            ("now", "play_harness.tournament", None),
                            ("zero", "play_harness.tournament", None)):
        extra = ["--index0", "0"] if name == "zero" else []
        printed[name] = _run_module(mod, args + extra + ["--out-dir", str(tmp_path / name)], path)
    before = open(tmp_path / "before" / "manifest.json", "rb").read()
    assert b"index0" not in before and json.loads(before)["tasks"] == 12
    for name in ("now", "zero"):
        assert open(tmp_path / name / "manifest.json", "rb").read() == before
        old, new = (open(tmp_path / n / "games.jsonl").read().splitlines()
                    for n in ("before", name))
        assert len(old) == len(new) == 12
        for a, b in zip(old, new):
            a, b = json.loads(a), json.loads(b)
            assert list(a) == list(b)                       # the same keys in the same order
            assert the_game(a) == the_game(b)
            for field in NOT_THE_GAME:                      # and only the values of these differ
                a[field] = b[field] = 0
            assert json.dumps(a, separators=(",", ":")) == json.dumps(b, separators=(",", ":"))
        assert printed[name].splitlines()[0] == printed["before"].splitlines()[0] == \
            "12 tasks, 0 already recorded, 12 to play, 1 workers"
        assert open(tmp_path / name / "COMPLETE.json").read().count('"complete": true') == 1


# ---- slices: one run, and the same games as two runs ------------------------------------------
@pytest.fixture(scope="module")
def plain_runs(tmp_path_factory, blobs):
    """Game indexes 0..7 of three pairs in one run (16 games a pair), and as two
    runs of 8 games a pair at index0 0 and index0 4."""
    folder = tmp_path_factory.mktemp("plain")
    tournament(folder / "whole", *plain_args(blobs, 16))
    tournament(folder / "s0", *plain_args(blobs, 8))
    printed = tournament(folder / "s4", *plain_args(blobs, 8), "--index0", "4")
    assert printed.splitlines()[0] == \
        "24 tasks, 0 already recorded, 24 to play, 1 workers, game indexes from 4"
    return folder


def test_a_slice_plays_its_own_indexes_and_seeds(plain_runs):
    manifest, games = load(plain_runs / "s4")
    assert manifest["index0"] == 4 and manifest["seed0"] == SEED0 and manifest["tasks"] == 24
    assert manifest["pairs"] == [[a, b, 8] for a, b in PAIRS]
    assert sorted({g["game_index"] for g in games}) == [4, 5, 6, 7]
    assert all(g["engine_seed"] == SEED0 + g["game_index"] for g in games)
    assert all(g["sampling_seeds"][0] == T.sampling_seed(g["engine_seed"], 0) for g in games
               if g["pair"] == ["A", "B"])
    assert sorted(map(key, games)) == sorted(
        ((a, b), i, leg) for a, b in PAIRS for i in range(4, 8) for leg in T.LEGS)
    first, _ = load(plain_runs / "s0")
    assert "index0" not in first                              # the slice from 0 is a plain run
    assert {k: v for k, v in manifest.items() if k != "index0"} == first


def test_two_slices_hold_the_games_of_the_whole_run(plain_runs):
    _, whole = load(plain_runs / "whole")
    slices = load(plain_runs / "s0")[1] + load(plain_runs / "s4")[1]
    # One worker plays the schedule in order, so the two slices end to end are
    # the whole run's records in the whole run's order.
    assert [key(g) for g in slices] == [key(g) for g in whole] and len(whole) == 48
    for ours, theirs in zip(slices, whole):
        assert list(ours) == list(theirs)
        assert the_game(ours) == the_game(theirs), key(ours)
    results = {pair: "".join(g["result_a"] for g in whole if tuple(g["pair"]) == pair)
               for pair in PAIRS}
    assert all(len(r) == 16 for r in results.values())
    assert {"W", "D", "L"} <= set(results[("off", "con")])    # not a run of draws
    assert "L" in results[("A", "off")]


# ---- resume ------------------------------------------------------------------------------------
BOTS = ["--bot", "off=offense", "--bot", "con=contact", "--seed0", str(SEED0)]


def test_a_resume_refuses_another_index0(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    monkeypatch.delenv(T.GAMES_PER_WORKER_ENV, raising=False)
    tail = ["--workers", "1", "--out-dir"]
    sliced, plain = str(tmp_path / "sliced"), str(tmp_path / "plain")
    tournament(sliced, *BOTS, "--pair", "off,con,4", "--index0", "6")
    tournament(plain, *BOTS, "--pair", "off,con,4")
    before = {d: open(os.path.join(d, "games.jsonl")).read() for d in (sliced, plain)}
    for folder, other in ((sliced, ["--index0", "5"]), (sliced, ["--index0", "0"]), (sliced, []),
                          (plain, ["--index0", "6"]), (plain, ["--index0", "1"])):
        with pytest.raises(SystemExit, match="existing manifest differs on index0"):
            T.main([*BOTS, "--pair", "off,con,4", *other, *tail, folder])
    # The same index resumes and plays nothing; a manifest without the key is index 0.
    assert "4 already recorded, 0 to play" in tournament(
        sliced, *BOTS, "--pair", "off,con,4", "--index0", "6")
    assert "4 already recorded, 0 to play" in tournament(
        plain, *BOTS, "--pair", "off,con,4", "--index0", "0")
    for folder in (sliced, plain):
        assert open(os.path.join(folder, "games.jsonl")).read() == before[folder]
    assert json.load(open(os.path.join(sliced, "manifest.json")))["index0"] == 6
    assert "index0" not in json.load(open(os.path.join(plain, "manifest.json")))


def test_an_interrupted_slice_resumes_to_the_same_games(tmp_path):
    args = [*BOTS, "--pair", "off,con,8", "--index0", "6"]
    whole, cut = tmp_path / "whole", tmp_path / "cut"
    tournament(whole, *args)
    tournament(cut, *args, "--max-tasks", "3")                  # stops inside index 7
    assert len(open(cut / "games.jsonl").readlines()) == 3 and not (cut / "COMPLETE.json").exists()
    assert "8 tasks, 3 already recorded, 5 to play" in tournament(cut, *args)
    assert (cut / "COMPLETE.json").exists()
    games = [load(folder)[1] for folder in (whole, cut)]
    assert [key(g) for g in games[1]] == [key(g) for g in games[0]] == [
        (("off", "con"), i, leg) for i in range(6, 10) for leg in T.LEGS]
    assert [the_game(g) for g in games[1]] == [the_game(g) for g in games[0]]


# ---- the batched path ---------------------------------------------------------------------------
def test_a_batched_slice_plays_its_own_indexes(blobs, tmp_path):
    """Batched workers take tasks by their absolute index. Bots draw no floats, so
    their batched games are the unbatched ones exactly; a network's batched game
    is held to its index and seed only (a batch changes float rounding)."""
    args = ["--checkpoint", f"A={blobs['A']}", "--checkpoint", f"B={blobs['B']}",
            "--bot", "off=offense", "--bot", "con=contact", "--pair", "A,B,4",
            "--pair", "off,con,4", "--seed0", str(SEED0), "--index0", "4"]
    tournament(tmp_path / "batched", *args, "--games-per-worker", "4", workers=2)
    tournament(tmp_path / "one", *args)
    manifest, batched = load(tmp_path / "batched")
    _, one = load(tmp_path / "one")
    assert manifest["index0"] == 4 and manifest["games_per_worker"] == 4
    assert sorted(map(key, batched)) == sorted(map(key, one)) == sorted(
        ((a, b), i, leg) for a, b in (("A", "B"), ("off", "con")) for i in (4, 5)
        for leg in T.LEGS)
    assert all(g["engine_seed"] == SEED0 + g["game_index"] for g in batched)
    unbatched = {key(g): g for g in one}
    for game in batched:
        if game["pair"] == ["off", "con"]:
            assert the_game(game) == the_game(unbatched[key(game)])


# ---- the droplet tool: a slice is verified against its index -----------------------------------
def test_the_droplet_tool_verifies_a_slice_against_its_index(plain_runs):
    manifest, games = load(plain_runs / "s4")
    request = dict(complete={"complete": True}, commit=T._git_head(),
                   checkpoint_sha={n: c["sha256"] for n, c in manifest["checkpoints"].items()},
                   pairs=[(a, b, 8) for a, b in PAIRS], seed0=SEED0,
                   bots={"off": "offense", "con": "contact"})
    assert D.verify_run(manifest, games=games, index0=4, **request) == []
    problems = D.verify_run(manifest, games=games, **request)       # asked for index 0
    assert any("manifest index0 4 != requested 0" in p for p in problems)
    assert any("24 scheduled games missing" in p for p in problems)
    assert any("24 games outside the schedule" in p for p in problems)
    first, first_games = load(plain_runs / "s0")
    assert D.verify_run(first, games=first_games, **request) == []
    assert any("manifest index0 0 != requested 4" in p
               for p in D.verify_run(first, games=first_games, index0=4, **request))
