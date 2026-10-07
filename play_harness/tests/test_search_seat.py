"""The search seat (search.SearchSeat): its setting, its decision rule, and the
session it may search on. tests/test_search_tournament.py plays it.

  the setting  one setting was measured (D426). k, n and delta are arguments;
               scope, cutoff, gamma, reward manifest and opponent model are not;
  the ports    the seat's rule, candidates, classes, labels, checks and clip
               threshold are the ones tools/search_ab.py measured, value for
               value. search_ab.py is left as it was, so it stays an independent
               reference for the games D426 rests on;
  binding      a seat searches only on a real session that pays its reward
               manifest.
"""
import json
import math
import os

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness import search as S
from play_harness import tournament as T
from play_harness.policy import random_policy
from tools import search_ab as AB
from tools import search_probe_diag as diag

from .conftest import ROOT
from .test_reward_manifest import FIXTURE, FIXTURE_SHA256

M1 = ("m1",)


@pytest.fixture(scope="module")
def manifest(lib):
    return E.load_reward_manifest(FIXTURE, lib)


# ---- the setting ----------------------------------------------------------------------------
def test_the_default_setting_is_the_one_d426_measured():
    setting = S.search_setting()
    assert setting == S.parse_setting("default") == S.parse_setting("4:16:0.1")
    assert setting == {
        "scope": ["turn", "after_declare"], "k": 4, "n": 16, "delta": 0.1,
        "max_rollout_steps": 200, "horizon": "turn", "gamma": 0.999,
        "reward_manifest": "r0_poss_half", "reward_manifest_sha256": FIXTURE_SHA256,
        "opponent_model": "the seat's own network on the opponent's row, under the seat's "
                          "own masks",
        "candidates": AB.CANDIDATES, "se_floor": AB.SE_FLOOR}
    assert set(setting) == set(S.SETTING_KEYS)
    # It is the search of the plan D425 registered, with that plan's gamma and manifest.
    with open(os.path.join(ROOT, "tools", "search_ab_plan.example.json")) as f:
        plan = json.load(f)
    for key, value in plan["search"].items():
        assert setting[key] == value, key
    assert setting["gamma"] == plan["gamma"]
    assert setting["reward_manifest_sha256"] == plan["reward_manifest_sha256"]
    assert setting["delta"] == next(a["delta"] for a in plan["arms"] if a["name"] == "s10")
    assert "declare" not in setting["scope"]              # never at DECLARE
    assert json.loads(json.dumps(setting)) == setting     # as the manifest stores it


def test_a_setting_is_three_numbers_and_nothing_else_can_be_changed():
    assert S.parse_setting("2:8:0")["delta"] == 0.0
    identity = S.parse_setting("4:16:inf")
    assert identity["delta"] == "inf" and S.check_setting(identity) == identity
    assert json.loads(json.dumps(identity)) == identity   # no bare Infinity in a manifest
    for bad in ("", "4:16", "4:16:0.1:9", "1:16:0.1", "4:1:0.1", "4:16:-0.1", "4:16:nan",
                "four:16:0.1", "4.5:16:0.1", "turn:4:16:0.1"):
        with pytest.raises(ValueError):
            S.parse_setting(bad)
    with pytest.raises(ValueError):
        S.search_setting(k=True)
    for key, value in (("scope", ["turn", "declare", "after_declare"]), ("scope", ["turn"]),
                       ("max_rollout_steps", 400), ("gamma", 0.99), ("horizon", "match"),
                       ("reward_manifest_sha256", "0" * 64), ("opponent_model", "the real seat"),
                       ("candidates", "top k"), ("se_floor", "none")):
        with pytest.raises(ValueError, match=key):
            S.check_setting(dict(S.search_setting(), **{key: value}))
    with pytest.raises(ValueError, match="exactly the keys"):
        S.check_setting(dict(S.search_setting(), extra=1))
    with pytest.raises(ValueError, match="exactly the keys"):
        S.check_setting(None)


def test_the_pinned_manifest_is_the_training_manifest(lib, manifest):
    pinned = S.pinned_reward_manifest(lib)
    assert pinned["sha256"] == S.REWARD_MANIFEST_SHA256 == FIXTURE_SHA256 == manifest["sha256"]
    assert pinned["rewards"] == manifest["rewards"] and pinned["name"] == S.REWARD_MANIFEST
    assert S.pinned_reward_manifest(lib) is pinned        # loaded once per process
    other = os.path.join(ROOT, "puffer", "config", "rewards", "r0_full.json")
    with pytest.raises(ValueError, match="pinned to r0_poss_half"):
        S.pinned_reward_manifest(lib, path=other)


# ---- the ports: what the seat decides is what search_ab.py decides ---------------------------
def test_the_seat_runs_the_checks_search_ab_records():
    assert S.INTEGRITY_CHECKS == AB.INTEGRITY_CHECKS and len(S.INTEGRITY_CHECKS) == 13
    assert S.SE_FLOOR == AB.SE_FLOOR and S.CANDIDATES == AB.CANDIDATES
    assert S.HARD_COUNTERS == T.HARD_COUNTERS
    assert S.CLASSES == diag.CLASSES and set(S.SCOPE) < set(S.CLASSES)
    assert S.PITCH_REACH == AB.PITCH_REACH


def test_the_deviation_rule_is_search_abs_to_the_last_bit():
    rng = np.random.default_rng(5)
    cases = 0
    for k in (2, 3, 4):
        for n in (2, 4, 16, 32):
            for _ in range(60):
                base = rng.normal(0.4, rng.choice([0.01, 0.1, 0.5]), n)
                returns = np.stack([base] + [base * rng.choice([0.0, 1.0])
                                             + rng.normal(rng.normal(0.0, 0.15), 0.1, n)
                                             for _ in range(k - 1)])
                for delta in (0.0, 0.02, 0.10, math.inf):
                    assert S.deviation(returns, delta) == AB.decide(returns, delta)
                    cases += 1
    assert cases == 3 * 4 * 60 * 4
    # Both branches were exercised.
    base = rng.normal(1.0, 0.1, 16)
    clear = np.stack([base, base + 0.15, base + 0.05, base - 0.2])
    assert S.deviation(clear, 0.10)[:2] == (True, 1) and S.deviation(clear, 0.15)[0] is False
    assert S.deviation(clear, math.inf)[0] is False
    for bad in (float("nan"), float("inf")):
        broken = clear.copy()
        broken[2, 5] = bad
        with pytest.raises(ValueError, match="not finite"):
            S.deviation(broken, 0.10)
    with pytest.raises(ValueError, match="two candidates"):
        S.deviation(clear[:1], 0.10)


def test_candidates_classes_labels_and_the_clip_threshold_are_search_abs(manifest):
    rng = np.random.default_rng(6)
    A = E.A
    for _ in range(200):
        count = int(rng.integers(2, 12))
        support = np.unique(np.asarray(
            [E.pack_tuple(A["ACTIVATE"], int(rng.integers(0, 16)), E.SQ_NONE)
             for _ in range(count)] + [E.pack_tuple(A["END_TURN"], E.ARG_NONE, E.SQ_NONE)],
            dtype=np.uint32))
        logits = torch.from_numpy(rng.normal(0, 1, sum(E.ACT_SIZES)).round(1).astype(np.float32))
        tuples, _ = S.joint_probabilities(logits, support)
        a0 = int(tuples[int(rng.integers(0, len(tuples)))])
        for k in (2, 4):
            order = S.candidate_order(tuples, a0, k)
            assert order == AB.candidate_order(tuples, a0, k)
            assert tuples[order[0]] == a0 and len(order) == min(k, len(tuples))
    for types in ({A["ACTIVATE"], A["END_TURN"]}, {A["DECLARE"]}, {A["STEP"], A["END_ACTIVATION"]},
                  {A["ACTIVATE"], A["DECLARE"]}, {A["CHOOSE_DIE"]}, set()):
        for flag in (False, True):
            assert S.decision_class(types, flag) == diag.decision_class(types, flag, A)
    assert S.decision_class({A["STEP"]}, True) == "after_declare"
    assert S.decision_class({A["STEP"]}, False) is None
    for action in ((A["DECLARE"], 2, E.SQ_NONE), (A["DECLARE"], 31, E.SQ_NONE),
                   (A["ACTIVATE"], 3, E.SQ_NONE), (A["STEP"], E.ARG_NONE, 17)):
        assert S.action_label(action) == diag.action_label(action, E)
    rewards = manifest["rewards"]
    for table in (rewards, dict(rewards, reward_dist_pbrs_gamma=0.999),
                  dict(rewards, reward_td=0.1, reward_win=0.2)):
        assert S.reward_clip_threshold(table) == AB.reward_clip_threshold(table)


# ---- binding ----------------------------------------------------------------------------------
def test_a_seat_searches_only_on_a_session_that_pays_its_manifest(manifest):
    net = random_policy(seed=11, scale=0.05)
    seat = S.SearchSeat(net, 0, seed=1, masks=M1, search=S.search_setting(2, 2, 0.0))
    seat.reset_match()
    with pytest.raises(RuntimeError, match="bound"):
        seat.decide(torch.zeros(sum(E.ACT_SIZES)), np.zeros(1, dtype=np.uint32), False)
    unpaid = E.Engine(49000)                              # objective terms only, no shaping
    paid = E.Engine(49000, rewards=manifest["rewards"])
    try:
        with pytest.raises(ValueError, match="does not pay"):
            seat.bind(unpaid, manifest)
        with pytest.raises(ValueError, match="is not the search setting's"):
            seat.bind(paid, dict(manifest, sha256="0" * 64))
        clone = paid.clone_for_search(1, S.SEARCH_DICE_STREAM)
        with pytest.raises(ValueError, match="not a clone"):
            seat.bind(clone, manifest)
        clone.close()
        assert seat.engine is None
        seat.bind(paid, manifest)
        assert seat.engine is paid and seat.rollouts.masks == (M1, M1)
        assert seat.rollouts.gamma == 0.999 and seat.rollouts.max_steps == 200
        assert seat.rollouts.horizon == S.HORIZON_TURN and seat.rollouts.temperature == 1.0
        assert seat.reward_limit == pytest.approx(1.0 + 1e-6)
        seat.close()
        assert seat.engine is None and seat.rollouts is None
    finally:
        unpaid.close()
        paid.close()


def test_a_seat_refuses_what_the_setting_was_not_measured_with():
    net = random_policy(seed=11, scale=0.05)
    setting = S.search_setting(2, 2, 0.0)
    for kwargs, needle in ((dict(masks=()), "at least one action mask"),
                           (dict(masks=M1, mode="argmax"), "samples"),
                           (dict(masks=M1, temperature=0.5), "temperature 1"),
                           (dict(masks=("m9",)), "unknown mask"),
                           (dict(masks=M1, search=None), "exactly the keys"),
                           (dict(masks=M1, search=dict(setting, gamma=0.9)), "gamma")):
        with pytest.raises(ValueError, match=needle):
            S.SearchSeat(net, 0, **{"search": setting, **kwargs})
    seat = S.SearchSeat(net, 1, seed=7, masks=("m3", "m1"), search=S.search_setting())
    assert (seat.k, seat.n, seat.delta, seat.scope) == (4, 16, 0.1, ("turn", "after_declare"))
    assert seat.masks == ("m1", "m3") and seat.search == S.search_setting()
    assert S.SearchSeat(net, 0, masks=M1, search=S.search_setting(2, 2, math.inf)).delta == math.inf


# ---- the log-probability of a played alternative --------------------------------------------
def test_a_played_alternative_whose_probability_underflows_records_a_finite_logprob():
    """Chain 55's logits span more than a thousand, so a legal action can have a
    probability of exactly zero in a double. The seat once recorded log(0) for a
    deviation to such an action, and the game's logprob_sum was -inf."""
    logits = torch.zeros(sum(E.ACT_SIZES))
    activate, end_turn = E.A["ACTIVATE"], E.A["END_TURN"]
    logits[activate] = 900.0
    logits[end_turn] = -900.0
    support = np.asarray([E.pack_tuple(activate, 0, 0), E.pack_tuple(end_turn, 0, 0)],
                         dtype=np.uint32)
    tuples, probs = S.joint_probabilities(logits, support)
    same, logps = S.joint_log_probabilities(logits, support)
    assert list(tuples) == list(same)
    assert probs[1] == 0.0 and np.isfinite(logps).all()
    assert logps[1] == pytest.approx(-1800.0)
    assert S.played_logprob(logps[1]) == float(logps[1])
    assert np.array_equal(probs, np.exp(logps))


def test_a_played_alternative_with_a_representable_probability_records_what_it_always_did():
    for logp in (-0.25, -3.2, -40.0, -700.0):
        assert S.played_logprob(logp) == float(np.log(np.exp(logp)))
