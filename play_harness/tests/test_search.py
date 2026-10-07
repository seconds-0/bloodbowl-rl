"""The rollout core of the search probe (play_harness/search.py).

  T6   an oracle rollout, handed the real dice and copies of the real generators
       in a same-network game, reproduces the real game's next steps, rewards
       and value to the end of the searcher's turn;
  T3   a search leaves the real seats' recurrent states and generators, and the
       real session, exactly as they were;
  T1r  a scripted touchdown raises the return by 0.4 * gamma^t;
  T13  rollouts run with the real opponent seat replaced by an object that
       raises on any access;
  plus the stop rule (turn, end of match, cutoff, rejection), independence from
  the real dice at this level, the candidate probabilities and the seeds.

RowwisePolicy (test_batched_tournament.py) computes each batch row with its own
batch-1 forward, so a batched rollout and an unbatched real game round alike.
"""
import math
import os
import random

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness import search as S
from play_harness.policy import (MASKS, MaskedPolicySeat, PolicySeat, random_policy,
                                 restrict_support, select_joint)

from .conftest import ROOT
from .test_batched_tournament import RowwisePolicy
from .test_reward_manifest import FIXTURE

A = E.A


@pytest.fixture(scope="module")
def rewards(lib):
    return E.load_reward_manifest(FIXTURE, lib)["rewards"]


@pytest.fixture(scope="module")
def net(best_policy):
    """The checkpoint the suite is pointed at (BBPLAY_CHECKPOINT), else a seeded
    random network of the same shape."""
    return RowwisePolicy(best_policy[0])


class Game:
    """A real game stepped as tournament.play_match steps one: both seats forward
    on every engine step, the decider's tuple is applied. forward() and apply()
    are separate so a test can stand at the root where a search seat would."""

    def __init__(self, policies, seed, rewards, masks=(("m1",), ("m1",)), max_decisions=4096):
        self.eng = E.Engine(seed, rewards=rewards, max_decisions=max_decisions)
        self.seats = [MaskedPolicySeat(policies[s], s, masks=masks[s], seed=900 + s)
                      if masks[s] else PolicySeat(policies[s], s, seed=900 + s)
                      for s in (0, 1)]
        for seat in self.seats:
            seat.reset_match()
        self.log = []
        self.over = False

    @property
    def steps(self):
        return len(self.log)

    def forward(self):
        eng = self.eng
        team = eng.decision_team
        outs = [self.seats[s].step(eng.obs(s), eng.joint_support(s), s == team)
                for s in (0, 1)]
        return team, outs

    def apply(self, team, outs):
        eng = self.eng
        turns = eng.turns_completed()
        tup = tuple(int(v) for v in outs[team]["tuple"])
        rc = eng.step(*tup)
        assert rc in (E.STEP_OK, E.STEP_TERMINAL)
        self.over = rc == E.STEP_TERMINAL
        final = eng.final_match() if self.over else None
        self.log.append({"team": team, "tuple": tup, "rewards": eng.last_rewards(),
                         "score_before": self.log[-1]["score_after"] if self.log else (0, 0),
                         "score_after": tuple(final.score) if final else eng.score(),
                         "values": (outs[0]["value"], outs[1]["value"]),
                         "turns_before": turns,
                         "turns_after": None if self.over else eng.turns_completed(),
                         "digest_after": None if self.over else eng.digest()})

    def play(self, steps):
        for _ in range(steps):
            if self.over:
                break
            self.apply(*self.forward())


def _generator_copy(generator):
    copy = torch.Generator()
    copy.set_state(generator.get_state())
    return copy


def _real_dice_clone(eng):
    clone = eng.clone_for_search(0, S.SEARCH_DICE_STREAM)
    clone._test_copy_dice_from(eng)
    return clone


def _flags(game, searcher):
    return (getattr(game.seats[searcher], "_after_declare", False),
            getattr(game.seats[1 - searcher], "_after_declare", False))


def _seat_fingerprint(game):
    return ([s.state.clone() for s in game.seats],
            [s.generator.get_state().clone() for s in game.seats],
            [(s.forwards, s.decisions, dict(getattr(s, "mask_stats", {}).get("m1", {})))
             for s in game.seats],
            game.eng.digest(), game.eng.env_digest())


def _assert_untouched(game, before):
    states, generators, counts, digest, env_digest = before
    for seat, state, generator in zip(game.seats, states, generators):
        assert torch.equal(seat.state, state)
        assert torch.equal(seat.generator.get_state(), generator)
    assert counts == [(s.forwards, s.decisions, dict(getattr(s, "mask_stats", {}).get("m1", {})))
                      for s in game.seats]
    assert (game.eng.digest(), game.eng.env_digest()) == (digest, env_digest)


# ---- T6, T3 -----------------------------------------------------------------------------
@pytest.mark.parametrize("searcher,masks", [(0, ("m1",)), (1, ("m1",)), (0, MASKS), (1, MASKS)])
def test_t6_an_oracle_rollout_reproduces_the_real_game_to_the_end_of_the_turn(
        rewards, net, searcher, masks):
    game = Game((net, net), 7100 + searcher, rewards, masks=(masks, masks))
    rollouts = S.Rollouts(net, searcher, masks=masks)
    roots, next_root = [], 80
    while not game.over:
        team, outs = game.forward()
        # Roots alternate between the searcher's decisions and the opponent's. From
        # an opponent decision the rollout plays the opponent's turn out of the
        # opponent-view state before the searcher's turn can end.
        decider = searcher if len(roots) % 2 == 0 else 1 - searcher
        if team == decider and game.steps >= next_root and len(roots) < 8:
            next_root = game.steps + 60
            before = _seat_fingerprint(game)
            # The oracle shares a batch with ordinary rollouts of another action.
            other = E.unpack_tuple(game.eng.joint_support(team)[0])
            clones = [_real_dice_clone(game.eng)] + [
                game.eng.clone_for_search(seed, S.SEARCH_DICE_STREAM) for seed in (1, 2)]
            oracle = (_generator_copy(game.seats[searcher].generator),
                      _generator_copy(game.seats[1 - searcher].generator))
            others = [tuple(torch.Generator().manual_seed(10 * b + i) for i in (1, 2))
                      for b in (1, 2)]
            batch = rollouts._play(
                game.eng, game.seats[searcher].state, game.seats[1 - searcher].state,
                [outs[team]["tuple"], other, other], clones, [oracle] + others,
                after_declare=_flags(game, searcher), record=True)
            _assert_untouched(game, before)
            roots.append((game.steps, batch,
                          None if batch.stops[0] == S.STOP_TERMINAL else clones[0].digest()))
        game.apply(team, outs)
    assert len(roots) == 8
    stops, opponent_decisions = set(), 0
    for root, batch, digest in roots:
        steps = int(batch.steps[0])
        real = game.log[root:root + steps]
        assert batch.trails[0] == [(e["team"], e["tuple"], e["rewards"][searcher]) for e in real]
        opponent_decisions += sum(1 for e in real[1:] if e["team"] != searcher)
        # The stop is the engine's: the searcher's turn counter rose on the last step
        # and on none before it, or the match ended, or the step budget ran out.
        base = real[0]["turns_before"][searcher]
        assert all(e["turns_after"][searcher] == base for e in real[:-1])
        if real[-1]["turns_after"] is None:
            want = S.STOP_TERMINAL
        elif real[-1]["turns_after"][searcher] != base:
            want = S.STOP_TURN
        else:
            want = S.STOP_CUTOFF
            assert steps == S.MAX_ROLLOUT_STEPS
        assert batch.stops[0] == want
        stops.add(want)
        expect = sum(S.GAMMA ** t * e["rewards"][searcher] for t, e in enumerate(real))
        assert batch.rewards[0] == pytest.approx(expect, abs=1e-12)
        if want == S.STOP_TERMINAL:
            assert batch.bootstraps[0] == 0.0 and batch.returns[0] == batch.rewards[0]
        else:
            # V(s_T) is what the real seat's forward on the next step returned.
            value = game.log[root + steps]["values"][searcher]
            assert batch.bootstraps[0] == value
            assert batch.returns[0] == pytest.approx(expect + S.GAMMA ** steps * value, abs=1e-9)
            assert digest == real[-1]["digest_after"]
    assert S.STOP_TURN in stops
    assert opponent_decisions > 40


def test_t3_a_search_leaves_the_seats_and_the_session_as_they_were(rewards, net):
    game = Game((net, net), 7300, rewards)
    rollouts = S.Rollouts(net, 0)
    searched = 0
    while searched < 4:
        team, outs = game.forward()
        support, _ = restrict_support(game.eng.joint_support(team), ("m1",), False)
        if team == 0 and game.steps > 60 and len(support) >= 2 and game.steps % 25 == 0:
            before = _seat_fingerprint(game)
            own, opp = game.seats[0].state, game.seats[1].state
            copies = own.clone(), opp.clone()
            tuples, _ = S.joint_probabilities(outs[0]["logits"], support)
            candidates = [E.unpack_tuple(t) for t in tuples[:4]]
            batch = rollouts.evaluate(game.eng, own, opp, candidates, 4, game.seats[0].seed,
                                      game.steps, after_declare=_flags(game, 0))
            _assert_untouched(game, before)
            assert game.seats[0].state is own and game.seats[1].state is opp
            assert torch.equal(own, copies[0]) and torch.equal(opp, copies[1])
            assert batch.returns.shape == (len(candidates), 4)
            assert np.isfinite(batch.returns).all() and batch.rejected == 0
            # The same search again is the same search: nothing carried over.
            again = rollouts.evaluate(game.eng, own, opp, candidates, 4, game.seats[0].seed,
                                      game.steps, after_declare=_flags(game, 0))
            assert np.array_equal(batch.returns, again.returns)
            assert batch.forward_rows == again.forward_rows > 0
            searched += 1
        game.apply(team, outs)
    # And the game then goes on as the unsearched game does.
    plain = Game((net, net), 7300, rewards)
    plain.play(game.steps + 50)
    game.play(50)
    assert [e["tuple"] for e in game.log] == [e["tuple"] for e in plain.log]


@pytest.mark.parametrize("searcher", [0, 1])
def test_a_match_horizon_rollout_reproduces_the_rest_of_the_real_game(rewards, net, searcher):
    """The measuring horizon on the oracle: the same rollout loop, told to play on
    past the searcher's turn ends, replays the real game to its last step, marks
    every own turn end with the value the real seat read there, and ends with the
    real score."""
    game = Game((net, net), 7800 + searcher, rewards)
    rollouts = S.Rollouts(net, searcher, horizon=S.HORIZON_MATCH, max_steps=100_000)
    while True:
        team, outs = game.forward()
        if team == searcher and game.steps >= 150:
            break
        game.apply(team, outs)
    root = game.steps
    before = _seat_fingerprint(game)
    oracle = (_generator_copy(game.seats[searcher].generator),
              _generator_copy(game.seats[1 - searcher].generator))
    batch = rollouts._play(game.eng, game.seats[searcher].state, game.seats[1 - searcher].state,
                           [outs[team]["tuple"]], [_real_dice_clone(game.eng)], [oracle],
                           after_declare=_flags(game, searcher), record=True)
    _assert_untouched(game, before)
    game.apply(team, outs)
    game.play(100_000)
    real = game.log[root:]
    assert batch.stops == [S.STOP_TERMINAL] and batch.steps[0] == len(real) > 300
    assert batch.trails[0] == [(e["team"], e["tuple"], e["rewards"][searcher]) for e in real]
    last = real[-1]["score_after"]
    assert tuple(batch.scores[0]) == (last[searcher], last[1 - searcher])
    paid = tds = 0.0
    marks = []
    for t, e in enumerate(real):
        gained = [e["score_after"][s] - e["score_before"][s] for s in (0, 1)]
        paid += S.GAMMA ** t * e["rewards"][searcher]
        tds += S.GAMMA ** t * float(np.float32(0.4)) * (gained[searcher] - gained[1 - searcher])
        if e["turns_after"] is not None and \
                e["turns_after"][searcher] != e["turns_before"][searcher]:
            marks.append((t + 1, paid, tds, game.log[root + t + 1]["values"][searcher]))
    assert batch.returns[0] == batch.rewards[0] == pytest.approx(paid, abs=1e-9)
    assert batch.touchdowns[0] == pytest.approx(tds, abs=1e-9)
    assert len(batch.marks[0]) == len(marks) >= 8
    for got, want in zip(batch.marks[0], marks):
        assert got[0] == want[0] and got[3] == want[3]
        assert got[1:3] == pytest.approx(want[1:3], abs=1e-9)
    # The search's own horizon stops the same rollout at the first of those marks.
    assert marks[0][0] < len(real)


# ---- T13 --------------------------------------------------------------------------------
class Raiser:
    """Stands where the real opponent seat was. Any use of it is an error."""

    def __getattribute__(self, name):
        raise AssertionError(f"the search touched the real opponent seat (.{name})")


def test_t13_rollouts_never_touch_the_real_opponent_seat(rewards, net):
    other = RowwisePolicy(random_policy(seed=12, scale=0.05))
    game = Game((net, other), 7400, rewards)
    # The searcher's own view of the opponent's row, kept the way a search seat will.
    shadow = net.initial_state(1)
    while True:
        team, outs = game.forward()
        _, _, shadow = net.forward_eval(torch.from_numpy(game.eng.obs(1)).reshape(1, -1), shadow)
        support, _ = restrict_support(game.eng.joint_support(team), ("m1",), False)
        if team == 0 and game.steps > 120 and len(support) >= 2:
            break
        game.apply(team, outs)
    assert not torch.equal(shadow, game.seats[1].state)       # another network's state
    tuples, _ = S.joint_probabilities(outs[0]["logits"], support)
    candidates = [E.unpack_tuple(t) for t in tuples[:2]]
    rollouts = S.Rollouts(net, 0)
    seed, step = game.seats[0].seed, game.steps

    def search():
        return rollouts.evaluate(game.eng, game.seats[0].state, shadow, candidates, 4,
                                 seed, step)

    with_seat = search()
    real_opponent, game.seats[1] = game.seats[1], Raiser()
    with pytest.raises(AssertionError):
        game.seats[1].state
    without = search()
    assert np.array_equal(with_seat.returns, without.returns)
    assert np.isfinite(without.returns).all()
    assert without.engine_steps == with_seat.engine_steps > 8
    assert real_opponent.forwards == game.steps + 1


# ---- T1r and the stop rule, on scripted rollouts -----------------------------------------
class ScriptedPolicy:
    """A stand-in network: every row's logits name the script's next tuple, the
    value is a constant. One forward per rollout step, so a batch of one rollout
    replays the script whoever decides."""

    def __init__(self, script, value=0.25):
        self.script, self.value, self.calls = list(script), value, 0

    def initial_state(self, batch=1):
        return torch.zeros(1, batch, 1)

    def forward_eval(self, obs, state):
        n = state.shape[1]
        logits = torch.zeros(n, sum(E.ACT_SIZES))
        if self.calls < len(self.script):
            t, arg, sq = self.script[self.calls]
            logits[:, t] = logits[:, E.ACT_SIZES[0] + arg] = 60.0
            logits[:, E.ACT_SIZES[0] + E.ACT_SIZES[1] + sq] = 60.0
        self.calls += 1
        return logits, torch.full((n,), self.value), state


def _bot_game(seed, rewards, kinds=("offense", "contact")):
    """A bot game's trail: per step the decider, its tuple, both rewards, the
    score and turn counters before the step."""
    eng = E.Engine(seed, rewards=rewards)
    trail = []
    while True:
        team = eng.decision_team
        tup = eng.legal()[eng.scripted_bot_index(E.BOT_TYPES[kinds[team]])].tuple
        entry = {"team": team, "tuple": tup, "score": tuple(eng.match().score),
                 "turns": eng.turns_completed()}
        rc = eng.step(*tup)
        entry["rewards"] = eng.last_rewards()
        trail.append(entry)
        if rc == E.STEP_TERMINAL:
            return trail


def _replayed(seed, rewards, trail, upto, **kwargs):
    eng = E.Engine(seed, rewards=rewards, **kwargs)
    for entry in trail[:upto]:
        assert eng.step(*entry["tuple"]) == E.STEP_OK
    return eng


def _scripted_rollout(root, seat, trail, start, value=0.25, **kwargs):
    """One rollout from `root` that replays trail[start:] on the real dice."""
    policy = ScriptedPolicy([e["tuple"] for e in trail[start + 1:]], value)
    rollouts = S.Rollouts(policy, seat, masks=(), **kwargs)
    state = policy.initial_state(1)
    generators = [(torch.Generator().manual_seed(1), torch.Generator().manual_seed(2))]
    return rollouts._play(root, state, state, [trail[start]["tuple"]],
                          [_real_dice_clone(root)], generators, record=True)


def _first_touchdown(rewards, seat):
    for seed in range(8000, 8040):
        trail = _bot_game(seed, rewards)
        for i in range(len(trail) - 1):
            if trail[i + 1]["score"][seat] > trail[i]["score"][seat]:
                return seed, trail, i
    raise AssertionError("no touchdown in 40 bot games")


@pytest.mark.parametrize("back", [0, 3, 9])
def test_t1r_a_touchdown_raises_the_return_by_its_discounted_reward(rewards, back):
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    # The root: up to `back` steps before the touchdown, inside the same team turn.
    start = td
    while start > td - back and trail[start - 1]["turns"][seat] == trail[td]["turns"][seat]:
        start -= 1
    t = td - start
    assert t == back or back > 6
    no_td = dict(rewards, reward_td=0.0)
    batches = [_scripted_rollout(_replayed(seed, table, trail, start), seat, trail, start)
               for table in (rewards, no_td)]
    paid, unpaid = batches
    assert paid.stops == unpaid.stops == [S.STOP_TURN]        # the touchdown ends the turn
    assert paid.steps[0] == unpaid.steps[0] == t + 1
    assert [e[:2] for e in paid.trails[0]] == [(e["team"], e["tuple"])
                                               for e in trail[start:td + 1]]
    td_reward = float(np.float32(0.4))
    assert paid.returns[0] - unpaid.returns[0] == pytest.approx(td_reward * S.GAMMA ** t, abs=1e-6)
    # The whole return, term by term, from the real game's own rewards.
    real = [e["rewards"][seat] for e in trail[start:td + 1]]
    assert [e[2] for e in paid.trails[0]] == real
    expect = sum(S.GAMMA ** i * r for i, r in enumerate(real)) + S.GAMMA ** (t + 1) * 0.25
    assert paid.returns[0] == pytest.approx(expect, abs=1e-9)
    assert paid.bootstraps[0] == 0.25
    # A value-only score would have missed it: V is the same with and without.
    assert paid.bootstraps[0] == unpaid.bootstraps[0]
    # The split of the return: the touchdown's part, and the turn end it stopped at.
    assert paid.touchdowns[0] == pytest.approx(td_reward * S.GAMMA ** t, abs=1e-9)
    assert unpaid.touchdowns[0] == 0.0
    assert paid.marks == [[(t + 1, paid.rewards[0], paid.touchdowns[0], 0.25)]]
    assert (paid.scores == -1).all()                           # the match did not end


def test_the_return_is_the_searchers_own_reward_by_physical_team(rewards):
    """The same scripted steps scored for each seat: each gets its own column of
    the real rewards, on the opponent's decisions too, and the two do not mirror."""
    seed, trail, td = _first_touchdown(rewards, 0)
    start = td - 3
    batches = {}
    for seat in (0, 1):
        root = _replayed(seed, rewards, trail, start)
        batches[seat] = _scripted_rollout(root, seat, trail, start, max_steps=4)
        real = [e["rewards"][seat] for e in trail[start:start + 4]]
        assert [e[2] for e in batches[seat].trails[0]] == real
        assert batches[seat].rewards[0] == pytest.approx(
            sum(S.GAMMA ** i * r for i, r in enumerate(real)), abs=1e-12)
        # The touchdown on the fourth step is seat 0's: paid to it, charged to seat 1.
        sign = 1.0 if seat == 0 else -1.0
        assert batches[seat].touchdowns[0] == pytest.approx(
            sign * float(np.float32(0.4)) * S.GAMMA ** 3, abs=1e-9)
    # Somewhere in a game the shaped rewards are not zero-sum.
    assert any(abs(e["rewards"][0] + e["rewards"][1]) > 1e-4 for e in trail)
    deciders = {e["team"] for e in trail[td - 40:td + 40]}
    assert deciders == {0, 1}


def test_t8_a_rollout_across_the_end_of_the_match_takes_no_bootstrap(rewards):
    seat = 0
    seed, trail, _ = _first_touchdown(rewards, seat)
    last = len(trail) - 1
    start = last
    while last - start < 150 and trail[start - 1]["turns"][seat] == trail[last]["turns"][seat]:
        start -= 1
    assert last - start >= 1
    root = _replayed(seed, rewards, trail, start)
    batch = _scripted_rollout(root, seat, trail, start, value=123.0)
    assert batch.stops == [S.STOP_TERMINAL]
    assert batch.steps[0] == last - start + 1
    real = [e["rewards"][seat] for e in trail[start:]]
    assert batch.returns[0] == batch.rewards[0] == pytest.approx(
        sum(S.GAMMA ** i * r for i, r in enumerate(real)), abs=1e-12)
    assert batch.bootstraps[0] == 0.0                         # 123 was never read
    final = E.Engine(seed, rewards=rewards)
    for entry in trail:
        final.step(*entry["tuple"])
    assert tuple(batch.scores[0]) == tuple(final.final_match().score)      # seat 0 first
    assert batch.marks == [[]]                                # no turn end with a value
    assert abs(real[-1]) >= 0.59 or trail[-1]["score"][0] == trail[-1]["score"][1]


def test_a_cutoff_is_bootstrapped_and_counted(rewards):
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    start = td - 9
    assert trail[start]["turns"][seat] == trail[td]["turns"][seat]
    root = _replayed(seed, rewards, trail, start)
    batch = _scripted_rollout(root, seat, trail, start, max_steps=5)
    assert batch.stops == [S.STOP_CUTOFF] and batch.count(S.STOP_CUTOFF) == 1
    assert batch.steps[0] == 5
    real = [e["rewards"][seat] for e in trail[start:start + 5]]
    assert batch.returns[0] == pytest.approx(
        sum(S.GAMMA ** i * r for i, r in enumerate(real)) + S.GAMMA ** 5 * 0.25, abs=1e-9)


def test_a_rollout_that_ends_on_the_decision_cap_is_a_cap_rejection(rewards):
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    start = td - 9
    root = _replayed(seed, rewards, trail, start, max_decisions=start + 4)
    batch = _scripted_rollout(root, seat, trail, start)
    assert batch.stops == [S.STOP_CAP] and batch.count(S.STOP_CAP) == 1
    assert batch.rejected == 1 and batch.errors == []          # a cap ending is no error
    assert math.isnan(batch.returns[0])
    assert batch.steps[0] == 4 and batch.bootstraps[0] == 0.0


def test_the_default_cutoff_is_200_engine_steps(rewards):
    """A bot game holds stretches of more than 200 engine steps in which one team's
    turn counter does not move (setup, a kick-off, the other team's long turn). A
    rollout for that team is cut at 200, bootstrapped there and counted."""
    seed = 8005
    trail = _bot_game(seed, rewards)
    best = (0, 0, 0)
    for seat in (0, 1):
        start = 0
        for i in range(1, len(trail)):
            if trail[i]["turns"][seat] != trail[i - 1]["turns"][seat]:
                best = max(best, (i - start, start, seat))
                start = i
    length, start, seat = best
    assert length > S.MAX_ROLLOUT_STEPS == 200
    root = _replayed(seed, rewards, trail, start)
    batch = _scripted_rollout(root, seat, trail, start)                 # default max_steps
    assert batch.stops == [S.STOP_CUTOFF] and batch.count(S.STOP_CUTOFF) == 1
    assert batch.steps[0] == 200
    real = trail[start:start + 200]
    assert batch.trails[0] == [(e["team"], e["tuple"], e["rewards"][seat]) for e in real]
    expect = sum(S.GAMMA ** i * e["rewards"][seat] for i, e in enumerate(real))
    assert batch.bootstraps[0] == 0.25
    assert batch.returns[0] == pytest.approx(expect + S.GAMMA ** 200 * 0.25, abs=1e-9)
    # One step more of budget and the same rollout is not cut there.
    longer = _scripted_rollout(_replayed(seed, rewards, trail, start), seat, trail, start,
                               max_steps=201)
    assert longer.steps[0] == 201


class UniformPolicy:
    """A stand-in network: equal logits (a uniform draw over what is legal) and a
    constant value, whatever the batch."""

    def initial_state(self, batch=1):
        return torch.zeros(1, batch, 1)

    def forward_eval(self, obs, state):
        n = state.shape[1]
        return torch.zeros(n, sum(E.ACT_SIZES)), torch.full((n,), 0.25), state


@pytest.mark.parametrize("back,seat,max_steps,kinds", [
    (6, 0, 5, {S.STOP_TERMINAL, S.STOP_CUTOFF, S.STOP_ERROR}),
    (20, 1, 3, {S.STOP_TURN, S.STOP_CUTOFF, S.STOP_ERROR}),
])
def test_rows_that_stop_differently_share_a_batch(rewards, back, seat, max_steps, kinds):
    """One batch near the end of a game: rollouts that end the match, that run out
    of steps, that end the turn, and rollouts the engine refuses at their first
    action. Each row is filed under its own stop, with its own return, and is the
    rollout it would have been alone."""
    seed = 8005
    trail = _bot_game(seed, rewards)
    start = len(trail) - back
    root = _replayed(seed, rewards, trail, start)
    policy = UniformPolicy()
    state = policy.initial_state(1)
    rollouts = S.Rollouts(policy, seat, masks=(), max_steps=max_steps)
    legal, refused = trail[start]["tuple"], (A["STEP"], 40, 999)
    assert root.tuple_index(*refused) < 0
    before = (root.digest(), root.env_digest(), root.counters())
    n = 16
    batch = rollouts.evaluate(root, state, state, [legal, refused], n, 7, start, record=True)
    assert set(batch.stops) == kinds
    assert (root.digest(), root.env_digest(), root.counters()) == before
    assert batch.stops[n:] == [S.STOP_ERROR] * n                    # the refused candidate
    assert [b for b, _ in batch.errors] == list(range(n, 2 * n)) and batch.rejected == n
    assert all("refused" in what for _, what in batch.errors)
    assert np.isnan(batch.returns[1]).all() and not batch.steps[1].any()
    assert not batch.bootstraps[1].any() and batch.trails[n:] == [[]] * n
    assert np.isfinite(batch.returns[0]).all()
    assert sum(batch.count(s) for s in S.STOPS) == 2 * n
    for j in range(n):
        stop, row, steps = batch.stops[j], batch.trails[j], int(batch.steps[0, j])
        assert steps == len(row) >= 1
        paid = sum(S.GAMMA ** t * e[2] for t, e in enumerate(row))
        assert batch.rewards[0, j] == pytest.approx(paid, abs=1e-12)
        if stop == S.STOP_TERMINAL:
            assert batch.bootstraps[0, j] == 0.0 and batch.returns[0, j] == batch.rewards[0, j]
        else:
            assert steps == max_steps if stop == S.STOP_CUTOFF else steps <= max_steps
            assert batch.bootstraps[0, j] == 0.25
            assert batch.returns[0, j] == pytest.approx(paid + S.GAMMA ** steps * 0.25, abs=1e-12)
        clone = root.clone_for_search(S.rollout_seed(7, start, j, "dice"), S.SEARCH_DICE_STREAM)
        generators = [tuple(torch.Generator().manual_seed(S.rollout_seed(7, start, j, purpose))
                            for purpose in ("own", "opponent"))]
        alone = rollouts._play(root, state, state, [legal], [clone], generators, record=True)
        assert alone.stops == [stop] and alone.trails[0] == row
        assert alone.returns[0] == batch.returns[0, j]


def test_stop_precedence_is_match_end_then_turn_end_then_cutoff(rewards):
    """A turn that ends on the very step the budget runs out is a turn end, with
    one mark; a match that ends on its last turn's end is a match end."""
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    start = td - 3                                           # the touchdown is step 4
    batch = _scripted_rollout(_replayed(seed, rewards, trail, start), seat, trail, start,
                              max_steps=4)
    assert batch.stops == [S.STOP_TURN] and batch.steps[0] == 4 and len(batch.marks[0]) == 1
    shorter = _scripted_rollout(_replayed(seed, rewards, trail, start), seat, trail, start,
                                max_steps=3)
    assert shorter.stops == [S.STOP_CUTOFF] and shorter.marks == [[]]
    # The last step of a match also ends a team turn: it is the match end.
    last = len(trail) - 1
    final = _scripted_rollout(_replayed(seed, rewards, trail, last), seat, trail, last,
                              max_steps=1)
    assert final.stops == [S.STOP_TERMINAL] and final.bootstraps[0] == 0.0


class BrokenPolicy(ScriptedPolicy):
    """ScriptedPolicy whose forward number `at` returns `bad` logits or value."""

    def __init__(self, script, at, logits=None, value=None):
        super().__init__(script)
        self.at, self.bad_logits, self.bad_value = at, logits, value

    def forward_eval(self, obs, state):
        call = self.calls
        logits, value, state = super().forward_eval(obs, state)
        if call == self.at:
            if self.bad_logits is not None:
                logits[:, 0] = self.bad_logits
            if self.bad_value is not None:
                value[:] = self.bad_value
        return logits, value, state


@pytest.mark.parametrize("fault", ["logits", "value", "reward", "opponent_reward",
                                   "accumulated", "mask", "select"])
def test_an_integrity_failure_inside_a_rollout_is_an_error_not_a_rejection(
        rewards, monkeypatch, fault):
    """Each of these ends the rollout as STOP_ERROR with no return and a reason,
    never as a cap rejection or a silent fallback."""
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    start = td - 9
    root = _replayed(seed, rewards, trail, start)
    script = [e["tuple"] for e in trail[start + 1:]]
    kwargs = {}
    policy = ScriptedPolicy(script)
    if fault == "logits":
        policy = BrokenPolicy(script, at=2, logits=float("nan"))
    elif fault == "value":
        policy = BrokenPolicy(script, at=2, value=float("inf"))
    elif fault == "reward":
        kwargs["reward_limit"] = 1e-9                       # any reward at all is too large
    elif fault == "opponent_reward":
        # Seat 0 searches; seat 1's reward is not counted, and is still checked.
        monkeypatch.setattr(E.Engine, "last_rewards", lambda self: (0.0, float("nan")))
    elif fault == "accumulated":
        monkeypatch.setattr(E.Engine, "last_rewards", lambda self: (1.7e308, 0.0))
    elif fault == "mask":
        monkeypatch.setattr(S, "restrict_support",
                            lambda support, masks, after: (support, {"m1": (True, None, True)}))
        kwargs["masks"] = ("m1",)
    elif fault == "select":
        def refuse(*args, **kw):
            raise ValueError("empty exact support at head 0")
        monkeypatch.setattr(S, "select_joint", refuse)
    kwargs.setdefault("masks", ())
    rollouts = S.Rollouts(policy, seat, **kwargs)
    state = policy.initial_state(1)
    before = (root.digest(), root.env_digest(), root.counters())
    batch = rollouts._play(root, state, state, [trail[start]["tuple"]],
                           [_real_dice_clone(root)],
                           [(torch.Generator().manual_seed(1), torch.Generator().manual_seed(2))])
    assert batch.stops == [S.STOP_ERROR] and batch.count(S.STOP_CAP) == 0
    assert batch.rejected == 1 and math.isnan(batch.returns[0])
    assert len(batch.errors) == 1 and batch.errors[0][0] == 0
    needle = {"logits": "not finite", "value": "not finite", "reward": "beyond the limit",
              "opponent_reward": "a reward that is not finite",
              "accumulated": "an accumulated return that is not finite",
              "mask": "give way", "select": "no action"}[fault]
    assert needle in batch.errors[0][1]
    assert (root.digest(), root.env_digest(), root.counters()) == before
    # The same rollout without the fault is a rollout.
    monkeypatch.undo()
    clean = S.Rollouts(ScriptedPolicy(script), seat, masks=())._play(
        root, state, state, [trail[start]["tuple"]], [_real_dice_clone(root)],
        [(torch.Generator().manual_seed(1), torch.Generator().manual_seed(2))])
    assert clean.stops == [S.STOP_TURN] and clean.errors == []


@pytest.mark.parametrize("counter", S.HARD_COUNTERS)
def test_a_nonzero_hard_counter_in_a_clone_is_an_error(rewards, monkeypatch, counter):
    """The rollout itself went through; its clone's counter says something broke."""
    from play_harness import tournament as T
    assert S.HARD_COUNTERS == T.HARD_COUNTERS
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    start = td - 9
    root = _replayed(seed, rewards, trail, start)
    assert not any(root.counters()[name] for name in S.HARD_COUNTERS)
    real = E.Engine.counters
    monkeypatch.setattr(E.Engine, "counters",
                        lambda self: dict(real(self), **{counter: 1}) if self.is_clone
                        else real(self))
    batch = _scripted_rollout(root, seat, trail, start)
    assert batch.stops == [S.STOP_ERROR] and math.isnan(batch.returns[0])
    assert batch.errors == [(0, f"hard counters {{'{counter}': 1}}")]
    monkeypatch.undo()
    assert _scripted_rollout(root, seat, trail, start).stops == [S.STOP_TURN]


def test_a_reward_inside_the_limit_is_not_an_error(rewards):
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    start = td - 9
    root = _replayed(seed, rewards, trail, start)
    batch = _scripted_rollout(root, seat, trail, start, reward_limit=1.0)
    assert batch.stops == [S.STOP_TURN] and batch.errors == []


# ---- real dice, at this level -----------------------------------------------------------
def test_t2_rollout_returns_do_not_depend_on_the_real_dice_stream(rewards, net):
    games = [Game((net, net), 7500, rewards) for _ in range(2)]
    while True:
        moves = [g.forward() for g in games]
        support, _ = restrict_support(games[0].eng.joint_support(moves[0][0]), ("m1",), False)
        if moves[0][0] == 0 and games[0].steps > 150 and len(support) >= 2:
            break
        for g, move in zip(games, moves):
            g.apply(*move)
    elsewhere = E.Engine(1234)
    games[1].eng._test_copy_dice_from(elsewhere)              # same match, another stream
    assert games[0].eng.digest() != games[1].eng.digest()
    tuples, _ = S.joint_probabilities(moves[0][1][0]["logits"], support)
    candidates = [E.unpack_tuple(t) for t in tuples[:2]]
    batches = [S.Rollouts(net, 0).evaluate(g.eng, g.seats[0].state, g.seats[1].state,
                                           candidates, 6, g.seats[0].seed, g.steps,
                                           record=True)
               for g in games]
    assert np.array_equal(batches[0].returns, batches[1].returns)
    assert batches[0].trails == batches[1].trails
    assert len({tuple(t) for t in batches[0].trails}) > 1     # the rollouts did differ


def test_search_code_cannot_reach_real_dice():
    import ast
    tree = ast.parse(open(os.path.join(ROOT, "play_harness", "search.py")).read())
    for node in ast.walk(tree):                       # drop docstrings; unparse drops comments
        body = getattr(node, "body", None)
        if isinstance(body, list) and body and isinstance(body[0], ast.Expr) \
                and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
            body[0] = ast.Pass()
    code = ast.unparse(tree)
    for word in ("_test_", "bbp_", "peek_legal", ".lib", "_ptr", "REAL_DICE_STREAM)"):
        assert word not in code, word
    # One way to make a clone, on the search stream; one reward read, the searcher's.
    assert code.count("clone_for_search(") + code.count("copy_from(") == 2
    assert code.count("SEARCH_DICE_STREAM)") == 2
    # Outside tests, clones and generators are made in evaluate() and nowhere else.
    assert code.count("._play(") == 1 and code.count("torch.Generator()") == 2
    assert code.count("last_rewards()") == 1 and code.count("rewards[seat]") == 1
    assert "rewards[1 - seat]" not in code
    assert S.SEARCH_DICE_STREAM != E.REAL_DICE_STREAM


# ---- candidates and seeds ---------------------------------------------------------------
def test_joint_probabilities_are_the_samplers():
    eng = E.Engine(91)
    rng = random.Random(2)
    checked = 0
    for step in range(400):
        team = eng.decision_team
        support = eng.joint_support(team)
        if step % 9 == 0:
            gen = torch.Generator().manual_seed(step)
            logits = torch.randn(sum(E.ACT_SIZES), generator=gen) * 3.0
            for temperature in (1.0, 0.5):
                tuples, probs = S.joint_probabilities(logits, support, temperature)
                assert len(tuples) == len(set(support.tolist()))
                assert probs.sum() == pytest.approx(1.0, abs=1e-9)
                assert all(probs[i] >= probs[i + 1] for i in range(len(probs) - 1))
                by_tuple = {E.unpack_tuple(t): p for t, p in zip(tuples, probs)}
                for _ in range(5):
                    action, logprob, _ = select_joint(logits, support, "sample", gen,
                                                      temperature=temperature)
                    assert by_tuple[action] == pytest.approx(math.exp(logprob), rel=2e-5)
                # The conditional argmax is the first step of the most probable chain,
                # and has at least the probability of a uniform draw.
                assert probs[0] >= 1.0 / len(probs) - 1e-12
            checked += 1
        if eng.step(*rng.choice(eng.legal()).tuple) == E.STEP_TERMINAL:
            break
    assert checked > 30


def test_joint_probabilities_follow_the_masked_support():
    logits = torch.zeros(sum(E.ACT_SIZES))
    logits[A["END_TURN"]] = 2.0
    turn = np.asarray([E.pack_tuple(A["ACTIVATE"], 3, E.SQ_NONE),
                       E.pack_tuple(A["ACTIVATE"], 5, E.SQ_NONE),
                       E.pack_tuple(A["END_TURN"], E.ARG_NONE, E.SQ_NONE)], dtype=np.uint32)
    tuples, probs = S.joint_probabilities(logits, turn)
    p_end = math.exp(2.0) / (math.exp(2.0) + 1.0)
    assert E.unpack_tuple(tuples[0])[0] == A["END_TURN"]
    assert probs == pytest.approx([p_end, (1 - p_end) / 2, (1 - p_end) / 2])
    kept, _ = restrict_support(turn, ("m1",), False)
    tuples, probs = S.joint_probabilities(logits, kept)
    assert [E.unpack_tuple(t)[1] for t in tuples] == [3, 5]          # ties: packed order
    assert probs == pytest.approx([0.5, 0.5])
    with pytest.raises(ValueError):
        S.joint_probabilities(logits, np.asarray([], dtype=np.uint32))


def test_rollout_seeds_are_a_function_of_public_values_only():
    seeds = {S.rollout_seed(s, t, j, p) for s in (1, 2) for t in (0, 7) for j in range(3)
             for p in S.SEED_PURPOSES}
    assert len(seeds) == 2 * 2 * 3 * 3                    # every argument matters
    assert all(0 <= v < 1 << 62 for v in seeds)
    assert S.rollout_seed(1, 7, 2, "dice") == S.rollout_seed(1, 7, 2, "dice")
    torch.Generator().manual_seed(max(seeds))
    with pytest.raises(ValueError):
        S.rollout_seed(1, 7, 2, "real")


def test_rollouts_refuse_bad_settings(net):
    assert S.Rollouts(net, 0).horizon == S.HORIZON_TURN       # the search's rule is the default
    for kwargs in ({"seat": 2}, {"seat": 0, "gamma": 0.0}, {"seat": 0, "gamma": 1.5},
                   {"seat": 0, "horizon": "half"},
                   {"seat": 0, "max_steps": 0}, {"seat": 0, "masks": ("m9",)},
                   {"seat": 0, "temperature": 0.0}):
        with pytest.raises(ValueError):
            S.Rollouts(net, **kwargs)
    eng = E.Engine(3)
    state = net.initial_state(1)
    first = eng.legal()[0].tuple
    with pytest.raises(ValueError):
        S.Rollouts(net, 0).evaluate(eng, state, state, [], 4, 1, 0)
    with pytest.raises(ValueError):
        S.Rollouts(net, 0).evaluate(eng, state, state, [first], 0, 1, 0)
    with pytest.raises(E.CloneRefused):
        finished = E.Engine(4)
        rng = random.Random(4)
        while finished.step(*rng.choice(finished.legal()).tuple) != E.STEP_TERMINAL:
            pass
        S.Rollouts(net, 0).evaluate(finished, state, state, [first], 1, 1, 0)


def _generators(n):
    return [(torch.Generator().manual_seed(2 * b), torch.Generator().manual_seed(2 * b + 1))
            for b in range(n)]


def test_a_rollout_never_steps_the_root_or_a_shared_clone(rewards, net):
    """The test entry takes ready clones. It must refuse the root itself, a real
    session, one clone listed twice and a generator shared between rollouts, each
    of which would let one rollout change the real game or another rollout."""
    game = Game((net, net), 7600, rewards)
    game.play(90)
    team, outs = game.forward()
    eng, rollouts = game.eng, S.Rollouts(net, team)
    own, opp = game.seats[team].state, game.seats[1 - team].state
    first = outs[team]["tuple"]
    other_real = E.Engine(7600, rewards=rewards)       # creating it moves the stalling sink
    before = (eng.digest(), eng.env_digest(), eng.counters(), other_real._test_stall_attached())
    assert before[3]
    clone = eng.clone_for_search(1, S.SEARCH_DICE_STREAM)
    shared = torch.Generator().manual_seed(1)
    bad = [([eng], _generators(1)),
           ([other_real], _generators(1)),
           ([clone, clone], _generators(2)),
           ([clone, eng], _generators(2)),
           ([clone], [(shared, shared)]),
           ([clone, eng.clone_for_search(2, S.SEARCH_DICE_STREAM)],
            [(shared, torch.Generator()), (torch.Generator(), shared)]),
           ([clone], _generators(2))]
    for clones, generators in bad:
        with pytest.raises(ValueError):
            rollouts._play(eng, own, opp, [first] * len(clones), clones, generators)
    assert (eng.digest(), eng.env_digest(), eng.counters(),
            other_real._test_stall_attached()) == before
    assert clone.counters()["steps"] == eng.counters()["steps"]          # nothing was stepped
    # A root that is itself a clone (a stored root) is still never stepped.
    with pytest.raises(ValueError):
        S.Rollouts(net, team)._play(clone, own, opp, [first], [clone], _generators(1))
    good = rollouts._play(eng, own, opp, [first], [clone], _generators(1))
    assert good.stops[0] in S.STOPS and good.steps[0] >= 1


def test_evaluate_builds_its_own_seeds_and_shares_them_across_candidates(rewards, net):
    game = Game((net, net), 7700, rewards)
    while True:
        team, outs = game.forward()
        support, _ = restrict_support(game.eng.joint_support(team), ("m1",), False)
        if team == 0 and game.steps > 100 and len(support) >= 2:
            break
        game.apply(team, outs)
    own, opp = game.seats[0].state, game.seats[1].state
    a0 = tuple(int(v) for v in outs[0]["tuple"])
    rollouts = S.Rollouts(net, 0)
    seed, step = game.seats[0].seed, game.steps
    twice = rollouts.evaluate(game.eng, own, opp, [a0, a0], 5, seed, step, record=True)
    # Common random numbers: the same candidate twice is the same five rollouts twice,
    # and rollout j is not rollout j + 1.
    assert np.array_equal(twice.returns[0], twice.returns[1])
    assert twice.trails[:5] == twice.trails[5:]
    assert len({repr(t) for t in twice.trails[:5]}) > 1
    # The seeds are the published ones: rebuilding rollout 3 by hand gives its trail.
    clone = game.eng.clone_for_search(S.rollout_seed(seed, step, 3, "dice"), S.SEARCH_DICE_STREAM)
    by_hand = rollouts._play(
        game.eng, own, opp, [a0], [clone],
        [tuple(torch.Generator().manual_seed(S.rollout_seed(seed, step, 3, purpose))
               for purpose in ("own", "opponent"))], record=True)
    assert by_hand.trails[0] == twice.trails[3]
    assert by_hand.returns[0] == twice.returns[0, 3]
    # Rollout indices from first_index on are the same rollouts, by index.
    tail = rollouts.evaluate(game.eng, own, opp, [a0], 2, seed, step, record=True, first_index=3)
    assert tail.trails == twice.trails[3:5]
    assert np.array_equal(tail.returns[0], twice.returns[0, 3:5])
    # Another step index or sampling seed is another set of rollouts.
    moved = rollouts.evaluate(game.eng, own, opp, [a0], 5, seed, step + 1, record=True)
    assert moved.trails != twice.trails[:5]
