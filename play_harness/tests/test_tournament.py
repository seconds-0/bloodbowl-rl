"""Policy-vs-policy tournament runner: every-step recurrence on both seats,
side swap, determinism and integrity aborts."""
import json
import os

import pytest
import torch

from play_harness import engine as E
from play_harness import tournament as T
from play_harness.policy import NONE_TUPLE, PolicySeat, random_policy

from .conftest import CHAIN25


@pytest.fixture(scope="module")
def policies():
    return {"A": random_policy(seed=1, scale=0.05), "B": random_policy(seed=2, scale=0.05)}


class RecordingSeat(PolicySeat):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.log = []

    def step(self, obs, support, deciding):
        before = self.state.clone()
        out = super().step(obs, support, deciding)
        self.log.append({"deciding": deciding, "before": before, "after": self.state.clone()})
        return out


def recording_factory(made):
    def factory(policy, seat, mode="sample", seed=0):
        s = RecordingSeat(policy, seat, mode=mode, seed=seed)
        made.append(s)
        return s
    return factory


def _essential(rec):
    return {k: v for k, v in rec.items() if k not in ("seconds", "pid")}


def test_both_seats_step_on_every_c_step(policies):
    made = []
    rec, seats = T.play_match(policies["A"], policies["B"], engine_seed=11,
                              seat_factory=recording_factory(made))
    assert rec["natural"] and not any(rec["integrity"].values())
    home, away = made
    assert seats == (home, away)
    assert len(home.log) == len(away.log) == rec["c_steps"] == home.forwards == away.forwards
    for h, a in zip(home.log, away.log):
        assert h["deciding"] != a["deciding"]          # exactly one coach decides per step
    for s in made:
        assert torch.count_nonzero(s.log[0]["before"]) == 0   # fresh state per match
        waiting = [e for e in s.log if not e["deciding"]]
        assert len(waiting) > 50
        assert all(not torch.equal(e["before"], e["after"]) for e in waiting)
    assert rec["decisions"][0] + rec["decisions"][1] == rec["c_steps"]


def test_fresh_state_and_generator_each_match(policies):
    made = []
    first, _ = T.play_match(policies["A"], policies["B"], 12, seat_factory=recording_factory(made))
    second, _ = T.play_match(policies["A"], policies["B"], 12, seat_factory=recording_factory(made))
    assert all(torch.count_nonzero(s.log[0]["before"]) == 0 for s in made)
    assert _essential(first) == _essential(second)


def test_side_swap_reuses_seeds_and_swaps_policies(policies):
    made = []
    legs = {leg: T.pair_game(policies, "A", "B", 3, leg, seed0=500,
                             seat_factory=recording_factory(made)) for leg in T.LEGS}
    a_home, b_home = legs["A_home"], legs["B_home"]
    assert a_home["engine_seed"] == b_home["engine_seed"] == 503
    assert a_home["team_ids"] == b_home["team_ids"]           # rosters stay with the side
    assert a_home["sampling_seeds"] == b_home["sampling_seeds"]
    assert (a_home["home"], a_home["away"]) == ("A", "B")
    assert (b_home["home"], b_home["away"]) == ("B", "A")
    # the seats really carried the swapped policies
    assert made[0].policy is policies["A"] and made[1].policy is policies["B"]
    assert made[2].policy is policies["B"] and made[3].policy is policies["A"]
    assert (a_home["a_td"], a_home["b_td"]) == tuple(a_home["score"])
    assert (b_home["a_td"], b_home["b_td"]) == tuple(reversed(b_home["score"]))
    for rec in legs.values():
        expect = "W" if rec["a_td"] > rec["b_td"] else ("D" if rec["a_td"] == rec["b_td"] else "L")
        assert rec["result_a"] == expect
    assert a_home["action_trail_sha256"] != b_home["action_trail_sha256"]


def test_fixed_seed_is_deterministic_and_seed_matters(policies):
    one = T.pair_game(policies, "A", "B", 0, "B_home", seed0=77)
    two = T.pair_game(policies, "A", "B", 0, "B_home", seed0=77)
    other = T.pair_game(policies, "A", "B", 1, "B_home", seed0=77)
    assert _essential(one) == _essential(two)
    assert one["action_trail_sha256"] != other["action_trail_sha256"]


def test_argmax_mode_reaches_the_seats(policies):
    made = []
    rec = T.pair_game(policies, "A", "B", 0, "A_home", seed0=91, mode="argmax",
                      seat_factory=recording_factory(made))
    assert rec["mode"] == "argmax" and all(s.mode == "argmax" for s in made)
    again = T.pair_game(policies, "A", "B", 0, "A_home", seed0=91, mode="argmax")
    assert _essential(rec) == _essential(again)


def test_schedule_interleaves_pairs_and_legs():
    tasks = T.schedule(["x", "y", "z"], 4, seed0=0)
    assert len(tasks) == 3 * 4
    assert tasks[:6] == [("x", "y", 0, "A_home"), ("x", "y", 0, "B_home"),
                         ("x", "z", 0, "A_home"), ("x", "z", 0, "B_home"),
                         ("y", "z", 0, "A_home"), ("y", "z", 0, "B_home")]
    assert {t[2] for t in tasks[6:]} == {1}
    with pytest.raises(ValueError):
        T.schedule(["x", "y"], 3, seed0=0)


class SkippingSeat(PolicySeat):
    """Learner-only stepping: the D388 bridge bug the runner must refuse."""

    def step(self, obs, support, deciding):
        if not deciding:
            return {"tuple": NONE_TUPLE, "logprob": 0.0, "value": 0.0, "logits": None}
        return super().step(obs, support, deciding)


class OutOfSupportSeat(PolicySeat):
    def step(self, obs, support, deciding):
        out = super().step(obs, support, deciding)
        if deciding:
            out["tuple"] = (E.A["END_TURN"], 7, 7)
        return out


@pytest.mark.parametrize("factory", [SkippingSeat, OutOfSupportSeat])
def test_contract_violations_abort(policies, factory):
    with pytest.raises(T.IntegrityError):
        T.play_match(policies["A"], policies["B"], 13, seat_factory=factory)


def test_check_record_flags_violations():
    good = {"natural": True, "integrity": {k: 0 for k in T.HARD_COUNTERS},
            "forwards": [10, 10], "c_steps": 10}
    assert T.check_record(good) == []
    assert T.check_record({**good, "forwards": [10, 9]})
    assert T.check_record({**good, "natural": False})
    assert T.check_record({**good, "integrity": {**good["integrity"], "illegal": 1}})


@pytest.mark.skipif(not os.path.exists(CHAIN25), reason="chain 25 checkpoint not present")
def test_cli_pool_writes_records_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("OMP_NUM_THREADS", "1")
    out = tmp_path / "run"
    args = ["--checkpoint", f"c25a={CHAIN25}", "--checkpoint", f"c25b={CHAIN25}",
            "--games-per-pair", "2", "--workers", "1", "--seed0", "4242", "--out-dir", str(out)]
    assert T.main(args) == 0
    games = [json.loads(line) for line in open(out / "games.jsonl")]
    assert sorted(g["leg"] for g in games) == ["A_home", "B_home"]
    assert all(T.check_record(g) == [] for g in games)
    assert (out / "COMPLETE.json").exists()
    assert T.main(args) == 0                                # resume plays nothing new
    assert len(open(out / "games.jsonl").readlines()) == 2
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    with pytest.raises(SystemExit):
        T.main(args)
