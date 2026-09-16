"""Engine scripted bots through the shim: the scripted step and the bot picks."""
import os
import random

import pytest

from play_harness import engine as E

from .conftest import ROOT

KINDS = ("contact", "offense")


# ---- shim ---------------------------------------------------------------------------
@pytest.mark.parametrize("kind", KINDS)
@pytest.mark.parametrize("seed", [3, 4])
def test_step_scripted_equals_submitting_the_picked_tuple(lib, kind, seed):
    """c_step's scripted branch applies exactly the engine pick: same dice, same state,
    same rewards and counters as submitting that pick's tuple on a twin session."""
    bt = E.BOT_TYPES[kind]
    a, b = E.Engine(seed, lib=lib), E.Engine(seed, lib=lib)
    steps = 0
    while True:
        assert a.digest() == b.digest()
        team = a.decision_team
        idx = a.scripted_bot_index(bt)
        assert idx >= 0 and idx == b.scripted_bot_index(bt)
        tup = a.legal()[idx].tuple
        ra, rb = a.step_scripted(bt, team), b.step(*tup)
        steps += 1
        assert ra == rb
        assert a.last_action() == b.last_action()
        assert a.last_rewards() == b.last_rewards()
        if ra == E.STEP_TERMINAL:
            break
        assert ra == E.STEP_OK and steps < 100_000
    assert steps > 200
    fa, fb = a.final_match(), b.final_match()
    assert bytes(fa) == bytes(fb)
    assert a.counters() == b.counters()
    assert a.stall_counts() == b.stall_counts()
    assert a.digest() == b.digest()


def test_scripted_step_leaves_the_env_unscripted(lib):
    """After a scripted step the env must decode submitted tuples again. If the
    scripted fields stayed set, the bot would override team 0's random tuples."""
    rng = random.Random(9)
    a, b = E.Engine(21, lib=lib), E.Engine(21, lib=lib)
    bt = E.BOT_TYPES["offense"]
    team = a.decision_team
    tup = a.legal()[a.scripted_bot_index(bt)].tuple
    assert a.step_scripted(bt, team) == b.step(*tup) == E.STEP_OK
    overridden = 0
    for _ in range(400):
        assert a.digest() == b.digest()
        legal = a.legal()
        choices = [x for x in legal if a.tuple_index(*x.tuple) == x.index]
        pick = rng.choice(choices)
        bot = a.scripted_bot_index(bt)
        overridden += bot != pick.index
        ra, rb = a.step(*pick.tuple), b.step(*pick.tuple)
        assert ra == rb
        if ra == E.STEP_TERMINAL:
            break
    assert overridden > 20            # the random coach really departs from the bot


def test_scripted_step_refusals_leave_state_untouched(lib):
    eng = E.Engine(8, lib=lib)
    before = eng.digest()
    team = eng.decision_team
    assert eng.step_scripted(7, team) == E.STEP_BAD_BOT
    assert eng.step_scripted(-1, team) == E.STEP_BAD_BOT
    assert eng.step_scripted(E.BOT_TYPES["offense"], 1 - team) == E.STEP_NOT_BOT_TURN
    assert eng.step_scripted(E.BOT_TYPES["contact"], 2) == E.STEP_NOT_BOT_TURN
    assert eng.scripted_bot_index(5) == -2
    assert eng.digest() == before and eng.counters()["steps"] == 0
    assert eng.contact_bot_index() == eng.scripted_bot_index(E.BOT_TYPES["contact"]) >= 0
    while eng.step_scripted(E.BOT_TYPES["contact"], eng.decision_team) != E.STEP_TERMINAL:
        pass
    assert eng.step_scripted(E.BOT_TYPES["contact"], eng.decision_team) == E.STEP_OVER


def test_contact_and_offense_bots_are_different_policies(lib):
    differ = 0
    for seed in (1, 2, 3):
        eng = E.Engine(seed, lib=lib)
        for _ in range(3000):
            c, o = (eng.scripted_bot_index(E.BOT_TYPES[k]) for k in KINDS)
            differ += c != o
            if eng.step_scripted(E.BOT_TYPES["offense"], eng.decision_team) == E.STEP_TERMINAL:
                break
    assert differ > 50


def test_engine_bot_table_matches_the_env_config():
    ini = open(os.path.join(ROOT, "puffer", "config", "bloodbowl.ini")).read()
    assert "0 = contact bot, 1 = bashy cage-advance offense bot" in ini
    assert E.BOT_TYPES == {"contact": 0, "offense": 1}
    env = open(os.path.join(ROOT, "puffer", "bloodbowl", "bloodbowl.h")).read()
    assert ("act = env->scripted_opponent_type == 1\n"
            "                      ? bbe_offense_bot_pick(m, env->legal, env->n_legal)\n"
            "                      : bbe_contact_bot_pick(m, env->legal, env->n_legal);") in env
    shim = open(os.path.join(ROOT, "play_harness", "native", "bbplay.c")).read()
    for fn in E.BOT_PICK_FUNCTIONS.values():
        assert fn in shim
