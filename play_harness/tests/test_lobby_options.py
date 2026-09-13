"""Lobby options: validation, roster modes, sides, and the checkpoint listing."""
import copy
import json
import os
import shutil

import pytest
import torch

from play_harness import game as G

torch.set_num_threads(2)


def _loader(best_policy):
    def load(path, kernel="native"):
        return best_policy
    return load


def _controller(best_policy, tmp_path, **raw):
    opts = G.normalize_options(raw)
    return G.GameController(opts, policy_loader=_loader(best_policy), games_dir=str(tmp_path),
                            save_records=False)


# ---- normalize_options -----------------------------------------------------
def test_defaults():
    for raw in (None, {}):
        opts = G.normalize_options(raw)
        seed = opts.pop("seed")
        assert isinstance(seed, int) and not isinstance(seed, bool)
        assert 1 <= seed <= G.SEED_MAX
        assert opts == {"checkpoint": G.DEFAULT_CHECKPOINT, "roster_mode": "random",
                        "human_team": None, "bot_team": None, "human_side": "home",
                        "mode": "sample", "think_ms": 600, "clock_mode": "display",
                        "clock_seconds": 240, "kernel": "native"}
    assert json.loads(json.dumps(G.normalize_options({"seed": 5}))) == G.normalize_options({"seed": 5})


def test_accepted_boundaries():
    opts = G.normalize_options({"roster_mode": "both", "human_team": 0, "bot_team": 29,
                                "human_side": "random", "mode": "argmax", "think_ms": 5000,
                                "clock_mode": "soft", "clock_seconds": 1800, "seed": G.SEED_MAX,
                                "kernel": "torch"})
    assert (opts["human_team"], opts["bot_team"], opts["seed"]) == (0, 29, G.SEED_MAX)
    assert opts["think_ms"] == 5000 and opts["clock_seconds"] == 1800 and opts["kernel"] == "torch"
    opts = G.normalize_options({"think_ms": 0, "clock_seconds": 15, "seed": 1})
    assert (opts["think_ms"], opts["clock_seconds"], opts["seed"]) == (0, 15, 1)
    assert G.normalize_options({"seed": " 42 "})["seed"] == 42
    assert G.normalize_options({"seed": ""})["seed"] >= 1
    assert G.normalize_options({"think_ms": 12.7})["think_ms"] == 12
    assert G.normalize_options({"kernel": "cuda"})["kernel"] == "native"
    mine = G.normalize_options({"roster_mode": "mine", "human_team": 3, "bot_team": 99})
    assert mine["human_team"] == 3 and mine["bot_team"] is None
    rnd = G.normalize_options({"roster_mode": "random", "human_team": 99, "bot_team": "x"})
    assert rnd["human_team"] is None and rnd["bot_team"] is None


BAD_OPTIONS = [
    ({"roster_mode": "draft"}, "bad_roster_mode"),
    ({"roster_mode": None}, "bad_roster_mode"),
    ({"roster_mode": "both", "bot_team": 3}, "bad_human_team"),
    ({"roster_mode": "both", "human_team": 3}, "bad_bot_team"),
    ({"roster_mode": "mine"}, "bad_human_team"),
    ({"roster_mode": "both", "human_team": 30, "bot_team": 1}, "bad_human_team"),
    ({"roster_mode": "both", "human_team": 1, "bot_team": 30}, "bad_bot_team"),
    ({"roster_mode": "mine", "human_team": 30}, "bad_human_team"),
    ({"roster_mode": "mine", "human_team": -1}, "bad_human_team"),
    ({"roster_mode": "both", "human_team": True, "bot_team": 1}, "bad_human_team"),
    ({"roster_mode": "both", "human_team": 1, "bot_team": False}, "bad_bot_team"),
    ({"roster_mode": "mine", "human_team": "3"}, "bad_human_team"),
    ({"roster_mode": "mine", "human_team": 3.0}, "bad_human_team"),
    ({"human_side": "left"}, "bad_human_side"),
    ({"human_side": 0}, "bad_human_side"),
    ({"mode": "greedy"}, "bad_mode"),
    ({"think_ms": -1}, "bad_think_ms"),
    ({"think_ms": 5001}, "bad_think_ms"),
    ({"think_ms": True}, "bad_think_ms"),
    ({"think_ms": "600"}, "bad_think_ms"),
    ({"clock_mode": "hard"}, "bad_clock_mode"),
    ({"clock_seconds": 14}, "bad_clock_seconds"),
    ({"clock_seconds": 14.9}, "bad_clock_seconds"),
    ({"clock_seconds": 1801}, "bad_clock_seconds"),
    ({"clock_seconds": False}, "bad_clock_seconds"),
    ({"clock_seconds": "240"}, "bad_clock_seconds"),
    ({"seed": 0}, "bad_seed"),
    ({"seed": "0"}, "bad_seed"),
    ({"seed": -5}, "bad_seed"),
    ({"seed": "-5"}, "bad_seed"),
    ({"seed": 2 ** 31}, "bad_seed"),
    ({"seed": True}, "bad_seed"),
    ({"seed": 1.5}, "bad_seed"),
    ({"seed": "abc"}, "bad_seed"),
]


@pytest.mark.parametrize("raw,reason", BAD_OPTIONS,
                         ids=[f"{i}-{r}" for i, (_, r) in enumerate(BAD_OPTIONS)])
def test_bad_options_are_rejected(raw, reason):
    with pytest.raises(G.OptionError) as info:
        G.normalize_options(dict(raw, seed=raw.get("seed", 7)))
    assert str(info.value) == reason
    assert isinstance(info.value, ValueError)


def test_checkpoint_must_be_listed_and_valid():
    good = {"path": "/ck/good.bin", "ok": True}
    broken = {"path": "/ck/broken.bin", "ok": False}
    listing = [good, broken]
    assert G.normalize_options({"checkpoint": "/ck/good.bin", "seed": 3},
                               checkpoints=listing)["checkpoint"] == "/ck/good.bin"
    with pytest.raises(G.OptionError, match="^unknown_checkpoint$"):
        G.normalize_options({"checkpoint": "/ck/other.bin", "seed": 3}, checkpoints=listing)
    with pytest.raises(G.OptionError, match="^unknown_checkpoint$"):
        G.normalize_options({"seed": 3}, checkpoints=listing)
    with pytest.raises(G.OptionError, match="^unknown_checkpoint$"):
        G.normalize_options({"seed": 3}, checkpoints=[])
    with pytest.raises(G.OptionError, match="^checkpoint_lineage_invalid$"):
        G.normalize_options({"checkpoint": "/ck/broken.bin", "seed": 3}, checkpoints=listing)
    # Without a listing the path is passed through (the loader validates it).
    assert G.normalize_options({"checkpoint": "/ck/other.bin", "seed": 3})["checkpoint"] == \
        "/ck/other.bin"


# ---- roster modes through the controller ------------------------------------
def test_random_roster_mode_uses_procgen_teams(best_policy, tmp_path):
    for seed in (3, 4):
        gc = _controller(best_policy, tmp_path, roster_mode="random", seed=seed)
        s = gc.session
        assert s.params["home_team"] == -1 and s.params["away_team"] == -1
        assert gc.match_params["home_team"] == -1 and gc.match_params["away_team"] == -1
        teams = s.state()["teams"]
        assert all(0 <= t["id"] < 30 for t in teams)
        assert s.params["seed"] == seed


@pytest.mark.parametrize("side,human_seat", [("home", 0), ("away", 1)])
def test_both_roster_mode_seats_the_chosen_teams(best_policy, tmp_path, side, human_seat):
    gc = _controller(best_policy, tmp_path, roster_mode="both", human_team=12, bot_team=21,
                     human_side=side, seed=9)
    s = gc.session
    assert s.human_seat == human_seat and s.seat.seat == 1 - human_seat
    want = {human_seat: 12, 1 - human_seat: 21}
    assert s.params["home_team"] == want[0] and s.params["away_team"] == want[1]
    teams = s.state()["teams"]
    assert teams[human_seat]["id"] == 12
    assert teams[1 - human_seat]["id"] == 21
    assert gc.match_params["side"] == side
    assert gc.header()["match"]["human_seat"] == human_seat


@pytest.mark.parametrize("side,human_seat", [("home", 0), ("away", 1)])
def test_mine_roster_mode_gives_the_bot_a_procgen_team(best_policy, tmp_path, side, human_seat):
    gc = _controller(best_policy, tmp_path, roster_mode="mine", human_team=5, human_side=side,
                     seed=13)
    s = gc.session
    assert s.human_seat == human_seat
    key = ("home_team", "away_team")
    assert s.params[key[human_seat]] == 5
    assert s.params[key[1 - human_seat]] == -1
    assert s.state()["teams"][human_seat]["id"] == 5


def test_random_human_side_is_deterministic_in_the_seed(best_policy, tmp_path):
    sides = set()
    for seed in range(1, 41):
        opts = G.normalize_options({"human_side": "random", "seed": seed})
        first = G.resolve_match(opts)
        again = G.resolve_match(G.normalize_options({"human_side": "random", "seed": seed}))
        assert first == again
        assert first["side"] in ("home", "away")
        assert first["human_seat"] == (0 if first["side"] == "home" else 1)
        sides.add(first["side"])
    assert sides == {"home", "away"}
    for seed in (1, 2, 3, 4):
        gc = _controller(best_policy, tmp_path, human_side="random", seed=seed)
        assert gc.session.human_seat == G.resolve_match(gc.options)["human_seat"]


def test_resolve_match_is_pure():
    opts = G.normalize_options({"roster_mode": "both", "human_team": 2, "bot_team": 4,
                                "human_side": "away", "seed": 777})
    frozen = copy.deepcopy(opts)
    a = G.resolve_match(opts)
    b = G.resolve_match(opts)
    assert a == b and a is not b
    assert opts == frozen
    assert a == {"human_seat": 1, "side": "away", "home_team": 4, "away_team": 2,
                 "engine_seed": 777, "policy_seed": (777 * 2654435761 + 97) % G.SEED_MAX}
    other = G.resolve_match(dict(opts, seed=778))
    assert other["policy_seed"] != a["policy_seed"]
    assert 0 <= a["policy_seed"] < G.SEED_MAX


# ---- checkpoint listing ------------------------------------------------------
def test_list_checkpoints_requires_a_matching_sidecar(tmp_path):
    src = G.DEFAULT_CHECKPOINT
    if not os.path.exists(src) or not os.path.exists(src + ".lineage.json"):
        pytest.skip("chain 25 checkpoint not present")
    with open(src + ".lineage.json") as f:
        lineage = json.load(f)

    def place(name, fn, sidecar):
        d = tmp_path / name
        d.mkdir()
        path = d / fn
        shutil.copyfile(src, path)
        if sidecar is not None:
            (d / (fn + ".lineage.json")).write_text(json.dumps(sidecar))
        return str(path)

    bare = place("bare", "0000000000000100.bin", None)
    wrong = copy.deepcopy(lineage)
    wrong["checkpoint"]["sha256"] = "0" * 64
    wrong_sha = place("wrongsha", "0000000000000200.bin", wrong)
    v5 = copy.deepcopy(lineage)
    v5["compatibility"]["observation_version"] = 5
    old_obs = place("obsv5", "0000000000000300.bin", v5)
    good = place("good", "0000000000000400.bin", lineage)

    found = {c["path"]: c for c in G.list_checkpoints([str(tmp_path)])}
    assert bare not in found
    assert set(found) == {wrong_sha, old_obs, good}
    assert found[wrong_sha]["ok"] is False and found[wrong_sha]["sha8"] is None
    assert "sha256" in found[wrong_sha]["error"]
    assert found[old_obs]["ok"] is False and "observation_version" in found[old_obs]["error"]
    assert found[good]["ok"] is True and found[good]["error"] is None
    assert found[good]["sha8"] == "109c55d3"
    assert found[good]["step"] == 400 and found[good]["name"] == "good"
    assert found[good]["obs"] == "obs-v6" and found[good]["action_abi"] == "exact-joint-v1"
    listing = G.list_checkpoints([str(tmp_path)])
    with pytest.raises(G.OptionError, match="^checkpoint_lineage_invalid$"):
        G.normalize_options({"checkpoint": wrong_sha, "seed": 1}, checkpoints=listing)
    with pytest.raises(G.OptionError, match="^unknown_checkpoint$"):
        G.normalize_options({"checkpoint": bare, "seed": 1}, checkpoints=listing)
    assert G.normalize_options({"checkpoint": good, "seed": 1},
                               checkpoints=listing)["checkpoint"] == good
    assert G.list_checkpoints([str(tmp_path / "missing")]) == []
