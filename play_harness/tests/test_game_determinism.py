"""Controller games are a pure function of the options and the human's actions."""
import json
import random

import numpy as np
import pytest
import torch

from play_harness import game as G

torch.set_num_threads(2)


def _loader(best_policy):
    def load(path, kernel="native"):
        return best_policy
    return load


def _random_driver(seed):
    rng = random.Random(seed)

    def choose(legal):
        ids = [a["id"] for a in legal["actions"]]
        ids += [row[0] for row in (legal.get("compact") or {}).get("SETUP_PLACE", [])]
        return {"action_id": rng.choice(ids), "state_version": legal["state_version"]}
    return choose


def _scripted_driver(actions):
    it = iter(actions)

    def choose(legal):
        a = next(it)
        return {"action": {"type": a[0], "arg": a[1], "x": a[2], "y": a[3]},
                "state_version": legal["state_version"]}
    return choose


def _run_game(best_policy, tmp_path, options, driver):
    gc = G.GameController(G.normalize_options(options), policy_loader=_loader(best_policy),
                          games_dir=str(tmp_path), save_records=False)
    s = gc.session
    frames = [gc.take_frames()]
    assert s.seat.forwards == s.version
    while not s.over:
        res = gc.submit(driver(s.legal()))
        assert res["ok"], res
        assert s.seat.forwards == s.version
        frames.append(gc.take_frames())
    return gc, frames


def _essential(trace):
    return [(r["step"], r["actor"], tuple(r["tuple"]), r["digest"], r.get("policy_logprob"))
            for r in trace]


def _dumps(value):
    return json.dumps(value, sort_keys=True)


@pytest.mark.parametrize("mode,side", [("sample", "home"), ("argmax", "away")])
def test_same_options_and_human_actions_reproduce_the_game(best_policy, tmp_path, mode, side):
    options = {"seed": 4242, "mode": mode, "human_side": side, "clock_mode": "off"}
    first, frames_a = _run_game(best_policy, tmp_path, options, _random_driver(8))
    human = [r["action"] for r in first.session.trace if r["actor"] == "human"]
    assert len(human) > 50
    second, frames_b = _run_game(best_policy, tmp_path, options, _scripted_driver(human))
    a, b = first.session, second.session
    assert a.over and b.over and a.result["natural_completion"]
    assert _essential(a.trace) == _essential(b.trace)
    assert a.trace == b.trace
    assert a.result == b.result
    assert _dumps(first.log) == _dumps(second.log) and first.log
    assert [len(f) for f in frames_a] == [len(f) for f in frames_b]
    views_a = [fr.get("view") for batch in frames_a for fr in batch]
    views_b = [fr.get("view") for batch in frames_b for fr in batch]
    assert sum(v is not None for v in views_a) > 100
    assert _dumps(views_a) == _dumps(views_b)
    assert _dumps(frames_a) == _dumps(frames_b)
    assert _dumps(first.over_payload()["stats"]) == _dumps(second.over_payload()["stats"])
    assert sorted(a.policy_logits) == sorted(b.policy_logits)
    for st in a.policy_logits:
        assert np.array_equal(a.policy_logits[st], b.policy_logits[st])


def test_a_different_seed_gives_a_different_game(best_policy, tmp_path):
    base = {"mode": "sample", "human_side": "home", "clock_mode": "off"}
    first, _ = _run_game(best_policy, tmp_path, dict(base, seed=4242), _random_driver(8))
    other, _ = _run_game(best_policy, tmp_path, dict(base, seed=4243), _random_driver(8))
    assert first.match_params["policy_seed"] != other.match_params["policy_seed"]
    assert _essential(first.session.trace) != _essential(other.session.trace)
    assert [r["digest"] for r in first.session.trace[:20]] != \
        [r["digest"] for r in other.session.trace[:20]]


@pytest.mark.parametrize("side,human_seat", [("home", 0), ("away", 1)])
def test_policy_steps_once_per_c_step(best_policy, tmp_path, side, human_seat):
    gc, _ = _run_game(best_policy, tmp_path,
                      {"seed": 515 + human_seat, "human_side": side, "clock_mode": "off"},
                      _random_driver(human_seat))
    s = gc.session
    assert s.human_seat == human_seat and s.seat.seat == 1 - human_seat
    assert s.result["natural_completion"] is True
    assert s.seat.forwards == s.version == len(s.trace)
    assert all(r["policy_forward"] == r["step"] + 1 for r in s.trace)
    policy_records = [r for r in s.trace if r["actor"] == "policy"]
    assert s.seat.decisions == len(policy_records)
    assert all(r["decision_team"] == 1 - human_seat for r in policy_records)
    assert all(r["decision_team"] == human_seat for r in s.trace if r["actor"] == "human")
    assert sum(1 for r in s.trace if r["actor"] == "human") > 50
