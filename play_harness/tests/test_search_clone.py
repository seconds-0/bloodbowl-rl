"""The native surface a decision-time search stands on (bbplay.c, search clones).

  T1   a clone given the source's dice and actions stays equal to it in every
       readable respect, and nothing done to a clone changes its source;
  T2   a clone does not depend on the source's dice: two roots that differ only
       in the real stream give bit-identical clone trajectories;
  T2b  a clone's stream is not the source's, and the real stream's id is refused;
  T8   a clone that reaches the end of the match pays the terminal reward, then
       refuses steps and observations;
  T9   the real session's stalling tally and this thread's stalling sink are the
       same with and without clone stepping, failures included; a crowd roll is
       counted once, in the session that rolled it.

Dice reach a clone only through Engine._test_copy_dice_from, the test hook.
"""
import random

import numpy as np
import pytest

from play_harness import engine as E

from .test_reward_manifest import FIXTURE

STREAM = 2          # any id but the real stream's


@pytest.fixture(scope="module")
def rewards(lib):
    return E.load_reward_manifest(FIXTURE, lib)["rewards"]


def _readable(eng):
    """Everything a seat or a search can read from a session at a decision."""
    return {
        "digest": eng.digest(), "env_digest": eng.env_digest(),
        "status": eng.status, "team": eng.decision_team,
        "obs": [eng.obs(a).tobytes() for a in (0, 1)],
        "mask": [eng.mask(a).tobytes() for a in (0, 1)],
        "support": [eng.joint_support(a).tobytes() for a in (0, 1)],
        "legal": eng.legal(), "counters": eng.counters(), "stall": eng.stall_counts(),
        "rewards": eng.last_rewards(), "last_action": eng.last_action(),
    }


def _advance(eng, rng, steps):
    """`steps` random legal actions; returns the tuples applied (stops at the end)."""
    trail = []
    for _ in range(steps):
        tup = rng.choice(eng.legal()).tuple
        trail.append(tup)
        if eng.step(*tup) == E.STEP_TERMINAL:
            break
    return trail


def _real_dice_clone(source, clone=None):
    if clone is None:
        clone = source.clone_for_search(0, STREAM)
    else:
        clone.copy_from(source, 0, STREAM)
    clone._test_copy_dice_from(source)
    return clone


# ---- T1 ---------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", range(301, 309))
def test_t1_a_clone_with_the_same_dice_and_actions_stays_equal_to_its_source(rewards, seed):
    source = E.Engine(seed, rewards=rewards)
    rng, side = random.Random(seed), random.Random(seed + 1)
    clone = _real_dice_clone(source)
    scratch = source.clone_for_search(seed, STREAM)
    steps = 0
    while True:
        if steps % 89 == 0:
            # A clone taken here, played on its own dice, leaves the source as it was.
            before = _readable(source)
            scratch.copy_from(source, seed * 1000 + steps, STREAM)
            _advance(scratch, side, 40)
            assert _readable(source) == before
            # And a fresh copy of the source, mid-game, is the source again.
            _real_dice_clone(source, clone)
        assert _readable(clone) == _readable(source), (seed, steps)
        tup = rng.choice(source.legal()).tuple
        rc = source.step(*tup)
        assert clone.step(*tup) == rc and rc in (E.STEP_OK, E.STEP_TERMINAL)
        steps += 1
        if rc == E.STEP_TERMINAL:
            break
    assert clone.last_rewards() == source.last_rewards()
    assert bytes(clone.final_match()) == bytes(source.final_match())
    assert clone.counters() == source.counters()
    assert clone.stall_counts() == source.stall_counts()
    assert steps > 300
    for eng in (clone, scratch, source):
        eng.close()


def test_t1_a_clone_is_a_separate_session(rewards):
    source = E.Engine(77, rewards=rewards)
    _advance(source, random.Random(1), 150)
    clone = source.clone_for_search(5, STREAM)
    assert clone.is_clone and not source.is_clone
    assert clone.reward_table() == source.reward_table()
    assert bytes(clone.match()) == bytes(source.match())
    before = _readable(source)
    clone.close()                                   # freeing a clone is not the source's end
    assert _readable(source) == before
    again = source.clone_for_search(5, STREAM)
    grandchild = again.clone_for_search(6, STREAM)   # a clone can be cloned
    _advance(grandchild, random.Random(2), 30)
    assert _readable(source) == before
    assert again.digest() == source.clone_for_search(5, STREAM).digest()


# ---- T2 ---------------------------------------------------------------------------------
def _clone_trajectory(root, dice_seed, steps=80):
    clone = root.clone_for_search(dice_seed, STREAM)
    rng = random.Random(dice_seed)
    out = [clone.env_digest()]
    for _ in range(steps):
        rc = clone.step(*rng.choice(clone.legal()).tuple)
        out.append((rc, clone.last_rewards(),
                    clone.env_digest() if rc == E.STEP_OK else bytes(clone.final_match())))
        if rc != E.STEP_OK:
            break
    clone.close()
    return out


@pytest.mark.parametrize("seed,warmup", [(401, 60), (402, 250), (403, 500), (404, 700)])
def test_t2_clones_do_not_depend_on_the_real_dice_stream(rewards, seed, warmup):
    trail = _advance(E.Engine(seed, rewards=rewards), random.Random(seed), warmup)
    roots = [E.Engine(seed, rewards=rewards) for _ in range(2)]
    for root in roots:
        for tup in trail:
            assert root.step(*tup) == E.STEP_OK
    elsewhere = E.Engine(seed + 5000)
    _advance(elsewhere, random.Random(0), 33)
    assert roots[0].digest() == roots[1].digest()
    roots[1]._test_copy_dice_from(elsewhere)             # same match, another real stream
    assert roots[0].digest() != roots[1].digest()
    assert bytes(roots[0].match()) == bytes(roots[1].match())
    runs = [[_clone_trajectory(root, j) for j in range(6)] for root in roots]
    assert runs[0] == runs[1]
    # The dice a clone does roll matter: other seeds give other games.
    assert len({repr(run) for run in runs[0]}) > 1
    # Positive control: the same comparison through the test hook, which does carry
    # the real stream, tells the two roots apart at once.
    leaky = [_real_dice_clone(root).digest() for root in roots]
    assert leaky[0] != leaky[1]


# ---- T2b --------------------------------------------------------------------------------
def test_t2b_a_clone_never_holds_the_source_stream(rewards, lib):
    source = E.Engine(55, rewards=rewards)
    _advance(source, random.Random(3), 120)
    for seed in (0, 55, source.seed, source.seed + source.episode * 7919):
        for stream in (0, 2, 3, 2 ** 63, 2 ** 64 - 1):
            clone = source.clone_for_search(seed, stream)
            assert bytes(clone.match()) == bytes(source.match())
            assert clone.digest() != source.digest()             # so the stream differs
            clone.close()
    # PCG32 uses (stream << 1) | 1: the top bit of the id does not name a new stream.
    for stream in (E.REAL_DICE_STREAM, E.REAL_DICE_STREAM + 2 ** 63):
        with pytest.raises(E.CloneRefused, match="real dice stream"):
            source.clone_for_search(9, stream)
        assert lib.bbp_clone_refusal(source._ptr, stream) == -2
    clone = source.clone_for_search(9, STREAM)
    with pytest.raises(E.CloneRefused, match="real dice stream"):
        clone.copy_from(source, 9, E.REAL_DICE_STREAM)
    with pytest.raises(E.CloneRefused, match="real dice stream"):
        clone.clone_for_search(9, E.REAL_DICE_STREAM)            # a clone's clone too
    with pytest.raises(E.CloneRefused, match="must be a clone"):
        source.copy_from(clone, 9, STREAM)                       # never onto a real session
    with pytest.raises(E.CloneRefused, match="must be a clone"):
        clone.copy_from(clone, 9, STREAM)
    before = clone.digest()
    with pytest.raises(E.CloneRefused):
        clone.copy_from(source, 9, E.REAL_DICE_STREAM)
    assert clone.digest() == before                              # a refused copy changes nothing


def test_the_dice_hook_is_the_only_export_that_copies_a_stream():
    """A source check on the shim: which exports make or overwrite a session, and
    where a dice stream is ever assigned."""
    import os
    import re
    from .conftest import ROOT
    shim = open(os.path.join(ROOT, "play_harness", "native", "bbplay.c")).read()
    makers = set(re.findall(r"^bbp_session\* (bbp_\w+)\(", shim, flags=re.M))
    assert makers == {"bbp_create", "bbp_create_rewards", "bbp_clone_for_search"}
    writers = set(re.findall(r"^(?!static)\w+ (bbp_\w+)\(bbp_session\* dst", shim, flags=re.M))
    assert writers == {"bbp_copy_into", "bbp_test_copy_dice"}
    # Two whole-session copies: the reseeding one behind both clone exports, and the
    # UI lookahead, which frees its copy and hands back a legal list only.
    assert len(re.findall(r"memcpy\(\w+, \w+, sizeof\(bbp_session\)\)", shim)) == 2
    assert shim.count("memcpy(dst, src, sizeof(bbp_session));\n    bbp_wire(dst);\n"
                      "    dst->clone = 1;") == 1
    assert len(re.findall(r"env\.rng = ", shim)) == 1                # the test hook
    assert all(name.startswith("bbp_test_")
               for name in re.findall(r"\b(bbp_\w*test\w*)\(", shim))


def test_only_tests_reach_the_test_hooks():
    """engine.py wraps the hooks; no other module of the package names them."""
    import glob
    import os
    from .conftest import ROOT
    package = os.path.join(ROOT, "play_harness")
    sources = [p for p in glob.glob(os.path.join(package, "**", "*.py"), recursive=True)
               if os.sep + "tests" + os.sep not in p]
    assert len(sources) > 10
    for path in sources:
        text = open(path).read()
        if os.path.basename(path) == "engine.py":
            assert text.count("_test_copy_dice_from") == 1       # its definition
            assert text.count("bbp_test_copy_dice") == 3         # signature, call, docstring
        else:
            assert "test_copy_dice" not in text and "_test_stall" not in text, path


# ---- T8 ---------------------------------------------------------------------------------
@pytest.mark.parametrize("seed", [501, 502, 503])
def test_t8_a_clone_that_ends_the_match_pays_the_terminal_reward_and_stops(rewards, seed):
    full = E.Engine(seed, rewards=rewards)
    trail = _advance(full, random.Random(seed), 100_000)
    final = full.final_match()
    assert final.status == E.STATUS_MATCH_OVER
    real = E.Engine(seed, rewards=rewards)
    for tup in trail[:-25]:
        assert real.step(*tup) == E.STEP_OK
    before = _readable(real)
    clone = _real_dice_clone(real)
    paid = [0.0, 0.0]
    for i, tup in enumerate(trail[-25:]):
        rc = clone.step(*tup)
        assert rc == (E.STEP_TERMINAL if i == 24 else E.STEP_OK)
    assert clone.last_rewards() == full.last_rewards()
    # The terminal emission is the result (and a touchdown, if that ended it).
    result = [0.6, -0.6] if final.score[0] > final.score[1] else \
        [-0.6, 0.6] if final.score[0] < final.score[1] else [0.0, 0.0]
    assert any(np.allclose(clone.last_rewards(), np.add(result, [td, -td]), atol=1e-6)
               for td in (0.0, 0.4, -0.4))
    assert bytes(clone.final_match()) == bytes(final)
    assert clone.counters()["terminal"] == 1 and clone.counters()["final_status"] == 2
    # Past the end: no step, no scripted step, no observation, no mask, no copy.
    assert clone.step(*trail[-1]) == E.STEP_OVER
    assert clone.step_scripted(E.BOT_TYPES["contact"], 0) == E.STEP_OVER
    for agent in (0, 1):
        with pytest.raises(ValueError, match="past the end"):
            clone.obs(agent)
        with pytest.raises(ValueError, match="past the end"):
            clone.mask(agent)
    with pytest.raises(E.CloneRefused, match="terminal"):
        clone.clone_for_search(1, STREAM)
    with pytest.raises(E.CloneRefused, match="terminal"):
        full.clone_for_search(1, STREAM)
    # Its stream is gone too: the env's reset had reseeded it from the real seed.
    fresh = E.Engine(seed, episode=1, rewards=rewards)
    assert clone.digest() != fresh.digest()
    assert _readable(real) == before
    # The real session reads normally after its own terminal step.
    assert full.obs(0).shape == (E.OBS_SIZE,)


# ---- T9 ---------------------------------------------------------------------------------
def test_t9_stalling_counts_are_the_same_with_and_without_clone_stepping(rewards):
    seed = 601
    plain = E.Engine(seed, rewards=rewards)
    busy = E.Engine(seed, rewards=rewards)
    rng, side = random.Random(seed), random.Random(9)
    clone = busy.clone_for_search(1, STREAM)
    clone_turn_ends = 0
    steps = 0
    while True:
        # The env's reset and every c_step leave the sink on the env they ran on.
        assert busy._test_stall_attached()
        # Clone work between two real steps: fresh copies, steps, a peek, a refusal.
        clone.copy_from(busy, steps, STREAM)
        _advance(clone, side, side.randint(1, 30))
        clone_turn_ends += sum(clone.stall_counts()["turn_ends"]) \
            - sum(busy.stall_counts()["turn_ends"])
        assert clone.step(E.A["STEP"], 40, 999) in (E.STEP_REJECTED, E.STEP_OVER)
        clone.copy_from(busy, steps + 1, STREAM)
        clone.peek_legal(*clone.legal()[0].tuple)
        throwaway = busy.clone_for_search(steps, STREAM)
        _advance(throwaway, side, 3)
        throwaway.close()
        with pytest.raises(E.CloneRefused):
            busy.clone_for_search(steps, E.REAL_DICE_STREAM)
        assert busy._test_stall_attached() and not clone._test_stall_attached()
        assert busy.stall_counts() == plain.stall_counts(), steps
        tup = rng.choice(plain.legal()).tuple
        rc = plain.step(*tup)
        assert busy.step(*tup) == rc
        steps += 1
        if rc == E.STEP_TERMINAL:
            break
    assert busy.stall_counts() == plain.stall_counts()
    assert sum(plain.stall_counts()["turn_ends"]) >= 16
    assert clone_turn_ends > 0                      # the clones did record, into their own


def test_t9_the_stalling_sink_survives_a_clone_that_ends_the_match(rewards, lib):
    real = E.Engine(602, rewards=rewards)
    _advance(real, random.Random(602), 100_000)                 # to its terminal step
    replay = E.Engine(602, rewards=rewards)
    rng = random.Random(602)
    while True:
        clone = _real_dice_clone(replay)
        twin = random.Random()
        twin.setstate(rng.getstate())
        if _advance(clone, twin, 20) and clone.counters()["terminal"]:
            break
        clone.close()
        _advance(replay, rng, 15)
    assert clone.counters()["terminal"] == 1
    assert replay._test_stall_attached() and not clone._test_stall_attached()
    assert clone.step(*replay.legal()[0].tuple) == E.STEP_OVER
    assert replay._test_stall_attached()
    clone.close()
    assert replay._test_stall_attached()
    replay.close()                                             # the attached session itself
    assert lib.bbp_test_stall_attached(None) == 1              # no sink left on freed memory
    real.close()


def _stalling_trail(seed, rewards):
    """A bot game up to a real Stalling event: the coach whose carrier can score
    without dice ends the turn instead (a legal END_TURN), so the crowd rolls.
    Returns the tuples applied; the last one is that END_TURN."""
    eng = E.Engine(seed, rewards=rewards)
    kinds = (E.BOT_TYPES["offense"], E.BOT_TYPES["contact"])
    held = E.BALL_STATES.index("held")
    trail = []
    while True:
        team = eng.decision_team
        legal = eng.legal()
        ball = eng.match().ball
        end_turn = [la for la in legal if la.type_name == "END_TURN"]
        if end_turn and ball.state == held and ball.carrier >> 4 == team \
                and eng.can_score_without_dice(ball.carrier):
            rolls = sum(eng.stall_counts()["rolls"])
            trail.append(end_turn[0].tuple)
            assert eng.step(*trail[-1]) == E.STEP_OK
            if sum(eng.stall_counts()["rolls"]) > rolls:
                return trail
            continue
        trail.append(legal[eng.scripted_bot_index(kinds[team])].tuple)
        assert eng.step(*trail[-1]) == E.STEP_OK, "no stalling event in this game"


# Seed 9000: the crowd acts and the knockdown is a turnover. Seed 9004: the roll is
# consumed and forgiven. Both are real crowd dice.
@pytest.mark.parametrize("seed,acted", [(9000, 1), (9004, 0)])
def test_t9_a_crowd_roll_is_counted_once_in_the_session_that_rolled_it(rewards, seed, acted):
    trail = _stalling_trail(seed, rewards)
    plain = E.Engine(seed, rewards=rewards)
    for tup in trail:
        assert plain.step(*tup) == E.STEP_OK
    want = plain.stall_counts()
    assert sum(want["rolls"]) == 1 and sum(want["acted"]) == acted
    assert sum(want["turnovers"]) == acted
    busy = E.Engine(seed, rewards=rewards)
    for tup in trail[:-1]:
        assert busy.step(*tup) == E.STEP_OK
    before = busy.stall_counts()
    assert sum(before["rolls"]) == 0 and before != want
    # A clone on the real dice rolls the same crowd die, into its own tally.
    twin = _real_dice_clone(busy)
    assert twin.step(*trail[-1]) == E.STEP_OK
    assert twin.stall_counts() == want
    # Clones on their own dice roll their own crowd die: the roll is the rule's,
    # whether the crowd acts is the die's.
    outcomes = set()
    for dice in range(24):
        clone = busy.clone_for_search(dice, STREAM)
        assert clone.step(*trail[-1]) == E.STEP_OK
        counts = clone.stall_counts()
        assert sum(counts["rolls"]) == 1
        outcomes.add(sum(counts["acted"]))
        clone.close()
    assert outcomes == {0, 1}
    # None of it reached the real session, which then rolls its own, once.
    assert busy.stall_counts() == before and busy._test_stall_attached()
    assert busy.step(*trail[-1]) == E.STEP_OK
    assert busy.stall_counts() == want
    assert busy.digest() == plain.digest() == twin.digest()
