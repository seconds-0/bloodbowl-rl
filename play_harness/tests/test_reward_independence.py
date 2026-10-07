"""T12: the reward table changes what a step pays and nothing else.

A game with a search seat runs its real session under the training reward
manifest, so the search can read the trainer's per-step reward. These tests
hold that the manifest cannot change the game: the same seed and actions give
the same match and dice, observations, masks, legal list and projections,
caches, counters and stalling tally at every step, with and without it.
"""
import random

import numpy as np
import pytest

from play_harness import engine as E

from .test_reward_manifest import FIXTURE


@pytest.fixture(scope="module")
def manifest(lib):
    return E.load_reward_manifest(FIXTURE, lib)


def _same_everywhere(plain, paid, where):
    assert plain.digest() == paid.digest(), where
    assert plain.env_digest() == paid.env_digest(), where
    assert plain.status == paid.status and plain.decision_team == paid.decision_team, where
    for agent in (0, 1):
        assert np.array_equal(plain.obs(agent), paid.obs(agent)), where
        assert np.array_equal(plain.mask(agent), paid.mask(agent)), where
        assert np.array_equal(plain.joint_support(agent), paid.joint_support(agent)), where
    assert plain.legal() == paid.legal(), where
    assert plain.counters() == paid.counters(), where
    assert plain.stall_counts() == paid.stall_counts(), where
    assert plain.last_action() == paid.last_action(), where


@pytest.mark.parametrize("seed", [101, 102, 103, 104, 105, 106])
def test_a_game_is_the_same_with_and_without_the_reward_manifest(manifest, seed):
    plain = E.Engine(seed)
    paid = E.Engine(seed, rewards=manifest["rewards"])
    rng = random.Random(seed)
    shaping = objective_gap = 0.0
    steps = 0
    while True:
        _same_everywhere(plain, paid, (seed, steps))
        tup = rng.choice(plain.legal()).tuple
        rc = plain.step(*tup)
        assert paid.step(*tup) == rc and rc in (E.STEP_OK, E.STEP_TERMINAL)
        steps += 1
        r_plain, r_paid = plain.last_rewards(), paid.last_rewards()
        shaping += abs(r_paid[0] - r_plain[0]) + abs(r_paid[1] - r_plain[1])
        if rc == E.STEP_TERMINAL:
            # The terminal emission is objective plus result on both.
            objective_gap = max(abs(a - b) for a, b in zip(r_plain, r_paid))
            break
    _same_everywhere(plain, paid, (seed, "terminal"))
    assert bytes(plain.final_match()) == bytes(paid.final_match())
    assert objective_gap < 1e-6
    assert shaping > 0.1                    # the manifest did pay: the test is not vacuous
    assert steps > 300


@pytest.mark.parametrize("seed", [201, 202])
def test_a_bot_game_is_the_same_with_and_without_the_reward_manifest(manifest, seed):
    """The bots block and blitz every turn, which is where the priced block reads
    the encode-time block cache."""
    plain = E.Engine(seed)
    paid = E.Engine(seed, rewards=manifest["rewards"])
    kinds = (E.BOT_TYPES["offense"], E.BOT_TYPES["contact"])
    steps, block_pay = 0, 0.0
    while True:
        _same_everywhere(plain, paid, (seed, steps))
        team = plain.decision_team
        is_block = plain.legal()[plain.scripted_bot_index(kinds[team])].type_name == "BLOCK_TARGET"
        rc = plain.step_scripted(kinds[team], team)
        assert paid.step_scripted(kinds[team], team) == rc
        steps += 1
        if is_block:
            block_pay += abs(paid.last_rewards()[team])
        if rc == E.STEP_TERMINAL:
            break
        assert rc == E.STEP_OK
    _same_everywhere(plain, paid, (seed, "terminal"))
    assert bytes(plain.final_match()) == bytes(paid.final_match())
    assert block_pay > 0.5
