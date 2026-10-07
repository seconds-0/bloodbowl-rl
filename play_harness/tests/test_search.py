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
        self.log.append({"team": team, "tuple": tup, "rewards": eng.last_rewards(),
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


def _search_inputs(sampling_seed, step, n, k):
    """Seeds and generators for n rollouts of each of k candidates (common random
    numbers: rollout j of every candidate shares its seeds)."""
    dice = [S.rollout_seed(sampling_seed, step, j, "dice") for _ in range(k) for j in range(n)]
    gens = [(torch.Generator().manual_seed(S.rollout_seed(sampling_seed, step, j, "own")),
             torch.Generator().manual_seed(S.rollout_seed(sampling_seed, step, j, "opponent")))
            for _ in range(k) for j in range(n)]
    return dice, gens


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
            dice, gens = _search_inputs(5, game.steps, 2, 1)
            clones = [_real_dice_clone(game.eng)] + [
                game.eng.clone_for_search(seed, S.SEARCH_DICE_STREAM) for seed in dice]
            oracle = (_generator_copy(game.seats[searcher].generator),
                      _generator_copy(game.seats[1 - searcher].generator))
            batch = rollouts.run(
                game.eng, game.seats[searcher].state, game.seats[1 - searcher].state,
                [outs[team]["tuple"], other, other], None, [oracle] + gens,
                after_declare=_flags(game, searcher), clones=clones, record=True)
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
            k = min(4, len(tuples))
            firsts = [E.unpack_tuple(t) for t in tuples[:k] for _ in range(4)]
            dice, gens = _search_inputs(game.seats[0].seed, game.steps, 4, k)
            batch = rollouts.run(game.eng, own, opp, firsts, dice, gens,
                                 after_declare=_flags(game, 0))
            _assert_untouched(game, before)
            assert game.seats[0].state is own and game.seats[1].state is opp
            assert torch.equal(own, copies[0]) and torch.equal(opp, copies[1])
            assert np.isfinite(batch.returns).all() and batch.count(S.STOP_REJECTED) == 0
            # The same search again is the same search: nothing carried over.
            dice, gens = _search_inputs(game.seats[0].seed, game.steps, 4, k)
            again = rollouts.run(game.eng, own, opp, firsts, dice, gens,
                                 after_declare=_flags(game, 0))
            assert np.array_equal(batch.returns, again.returns)
            assert batch.forward_rows == again.forward_rows > 0
            searched += 1
        game.apply(team, outs)
    # And the game then goes on as the unsearched game does.
    plain = Game((net, net), 7300, rewards)
    plain.play(game.steps + 50)
    game.play(50)
    assert [e["tuple"] for e in game.log] == [e["tuple"] for e in plain.log]


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
    firsts = [E.unpack_tuple(t) for t in tuples[:2] for _ in range(4)]
    rollouts = S.Rollouts(net, 0)

    def search():
        dice, gens = _search_inputs(game.seats[0].seed, game.steps, 4, 2)
        return rollouts.run(game.eng, game.seats[0].state, shadow, firsts, dice, gens)

    with_seat = search()
    real_opponent, game.seats[1] = game.seats[1], Raiser()
    with pytest.raises(AssertionError):
        game.seats[1].state
    without = search()
    assert np.array_equal(with_seat.returns, without.returns)
    assert np.isfinite(without.returns).all()
    assert without.engine_steps == with_seat.engine_steps > len(firsts)
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
    return rollouts.run(root, state, state, [trail[start]["tuple"]], None, generators,
                        clones=[_real_dice_clone(root)], record=True)


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


def test_a_rollout_that_ends_on_the_decision_cap_is_rejected(rewards):
    seat = 0
    seed, trail, td = _first_touchdown(rewards, seat)
    start = td - 9
    root = _replayed(seed, rewards, trail, start, max_decisions=start + 4)
    batch = _scripted_rollout(root, seat, trail, start)
    assert batch.stops == [S.STOP_REJECTED] and batch.count(S.STOP_REJECTED) == 1
    assert math.isnan(batch.returns[0])
    assert batch.steps[0] == 4 and batch.bootstraps[0] == 0.0


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
    firsts = [E.unpack_tuple(t) for t in tuples[:2] for _ in range(6)]
    batches = []
    for g in games:
        dice, gens = _search_inputs(g.seats[0].seed, g.steps, 6, 2)
        batches.append(S.Rollouts(net, 0).run(g.eng, g.seats[0].state, g.seats[1].state,
                                              firsts, dice, gens, record=True))
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
    assert code.count("last_rewards()") == 1 and "last_rewards()[seat]" in code
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
    for kwargs in ({"seat": 2}, {"seat": 0, "gamma": 0.0}, {"seat": 0, "gamma": 1.5},
                   {"seat": 0, "max_steps": 0}, {"seat": 0, "masks": ("m9",)},
                   {"seat": 0, "temperature": 0.0}):
        with pytest.raises(ValueError):
            S.Rollouts(net, **kwargs)
    eng = E.Engine(3)
    state = net.initial_state(1)
    first = [eng.legal()[0].tuple]
    with pytest.raises(ValueError):
        S.Rollouts(net, 0).run(eng, state, state, first, [1, 2], [(None, None)])
    with pytest.raises(ValueError):
        S.Rollouts(net, 0).run(eng, state, state, first, [1], [])
    with pytest.raises(E.CloneRefused):
        finished = E.Engine(4)
        rng = random.Random(4)
        while finished.step(*rng.choice(finished.legal()).tuple) != E.STEP_TERMINAL:
            pass
        S.Rollouts(net, 0).run(finished, state, state, first, [1], [(None, None)])
