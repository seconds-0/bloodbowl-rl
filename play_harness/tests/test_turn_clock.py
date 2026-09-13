"""The turn clock: off, display and soft modes, ending turns through legal actions only."""
import random
from collections import Counter

import pytest
import torch

from play_harness import game as G
from play_harness import narrate as N
from play_harness.policy import PolicySeat
from play_harness.session import GameSession, replay_trace

torch.set_num_threads(2)

ZERO_KEYS = ("illegal", "projection_collision", "error_episodes", "engine_rejections",
             "precheck_collisions", "api_rejections")


class FakeClock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _loader(best_policy):
    def load(path, kernel="native"):
        return best_policy
    return load


def _controller(best_policy, tmp_path, clock, **raw):
    opts = G.normalize_options(raw)
    return G.GameController(opts, policy_loader=_loader(best_policy), games_dir=str(tmp_path),
                            now=clock, save_records=False)


def _choices(legal, allow_end_turn=True):
    ids = [a["id"] for a in legal["actions"] if allow_end_turn or a["type"] != "END_TURN"]
    ids += [row[0] for row in (legal.get("compact") or {}).get("SETUP_PLACE", [])]
    return ids or [a["id"] for a in legal["actions"]]


def _play_one(gc, rng, allow_end_turn=True):
    legal = gc.session.legal()
    res = gc.submit({"action_id": rng.choice(_choices(legal, allow_end_turn)),
                     "state_version": legal["state_version"]})
    assert res["ok"], res
    return res


def _check_integrity(session):
    integrity = session.integrity()
    for key in ZERO_KEYS:
        assert integrity[key] == 0, (key, integrity)
    assert integrity["forwards"] == integrity["c_steps"] == len(session.trace)


@pytest.mark.parametrize("mode", ["off", "display"])
def test_off_and_display_modes_never_end_a_turn(best_policy, tmp_path, mode):
    clock = FakeClock()
    gc = _controller(best_policy, tmp_path, clock, clock_mode=mode, clock_seconds=15, seed=51)
    s = gc.session
    rng = random.Random(51)
    last_key = None
    turn_windows = 0
    new_turns = 0
    while not s.over:
        key = s.turn_key()
        info = gc.client_ready(s.version)
        assert info["mode"] == mode and info["seconds"] == 15
        if mode == "off" or key is None:
            assert info["running"] is False and info["used"] == 0.0
            assert info["remaining"] is None and info["warn"] is False
        else:
            turn_windows += 1
            assert info["running"] is True and info["in_turn"] is True
            if key != last_key:
                new_turns += 1
                assert info["used"] == 0.0
            before = info["used"]
            clock.advance(37.5)
            later = gc.clock_info()
            assert later["used"] == pytest.approx(before + 37.5)
            assert later["remaining"] is None and later["warn"] is False
        last_key = key
        clock.advance(10000.0)
        version = s.version
        assert gc.tick_clock() is None
        assert s.version == version
        _play_one(gc, rng)
    assert all(r["actor"] != "clock" for r in s.trace)
    assert gc.clock_events == []
    assert s.result["natural_completion"] is True
    _check_integrity(s)
    if mode == "display":
        assert turn_windows > 50 and new_turns >= 8


def test_soft_clock_ends_the_human_team_turn(best_policy, tmp_path):
    clock = FakeClock()
    seconds = 60
    gc = _controller(best_policy, tmp_path, clock, clock_mode="soft", clock_seconds=seconds,
                     seed=21, human_side="home")
    s = gc.session
    rng = random.Random(21)
    clock_steps = set()
    expiries = 0
    setup_windows = 0
    bot_turn_windows = 0
    last_key = None
    while not s.over:
        legal = s.legal()
        key = s.turn_key()
        if key is None:
            # Setup, kickoff, or a decision inside the bot's turn: the clock never runs.
            info = gc.client_ready(s.version)
            assert info["running"] is False and info["in_turn"] is False
            if legal["prompt"]["kind"] == "setup":
                setup_windows += 1
            if N.in_team_turn(s.engine.match(), 1 - s.human_seat):
                bot_turn_windows += 1
            clock.advance(100000.0)
            assert gc.tick_clock() is None
            assert s.version == legal["state_version"]
            _play_one(gc, rng, allow_end_turn=False)
            continue
        assert legal["prompt"]["kind"] != "setup"
        assert key != last_key, "a clock expiry must end the turn"
        last_key = key
        info = gc.client_ready(s.version)
        assert info["running"] is True and info["used"] == 0.0
        assert info["remaining"] == seconds and info["warn"] is False
        started = gc.clock_started
        assert started == clock.t
        for _ in range(rng.randint(0, 4)):
            if s.over or s.turn_key() != key:
                break
            clock.advance(5.0)
            assert gc.tick_clock() is None
            _play_one(gc, rng, allow_end_turn=False)
            if not s.over and s.turn_key() == key:
                assert gc.client_ready(s.version)["used"] == pytest.approx(clock.t - started)
        if s.over or s.turn_key() != key:
            continue
        assert gc.clock_started == started, "actions inside the turn must not restart the clock"
        clock.t = started + 30.0
        info = gc.clock_info()
        assert info["remaining"] == 30.0 and info["warn"] is False
        clock.t = started + seconds - 1.0
        info = gc.clock_info()
        assert info["remaining"] == 1.0 and info["warn"] is True
        version = s.version
        assert gc.tick_clock() is None
        assert s.version == version
        clock.t = started + seconds + 0.5
        before = len(s.trace)
        res = gc.tick_clock()
        assert res is not None and res["ok"] is True, res
        applied = s.trace[before:]
        assert res["applied"] == applied
        non_policy = [r for r in applied if r["actor"] != "policy"]
        assert len(non_policy) == res["clock_steps"] >= 1
        assert all(r["actor"] == "clock" and r["decision_team"] == s.human_seat
                   for r in non_policy)
        clock_steps.update(r["step"] for r in non_policy)
        assert s.over or s.turn_key() != key
        assert gc.clock_info()["running"] is False
        expiries += 1
        assert gc.clock_events[-1] == {"turn": list(key), "step": applied[0]["step"],
                                       "clock_steps": res["clock_steps"]}
        _check_integrity(s)
    assert s.result["natural_completion"] is True
    assert {r["step"] for r in s.trace if r["actor"] == "clock"} == clock_steps
    assert expiries >= 5 and len(gc.clock_events) == expiries
    assert setup_windows > 0
    _check_integrity(s)
    assert replay_trace(s.header(), s.trace) is None
    print(f"expiries={expiries} setup_windows={setup_windows} bot_turn_windows={bot_turn_windows}")


def test_soft_clock_needs_ready_and_resets_between_turns(best_policy, tmp_path):
    clock = FakeClock()
    gc = _controller(best_policy, tmp_path, clock, clock_mode="soft", clock_seconds=15,
                     seed=33, human_side="away")
    s = gc.session
    rng = random.Random(33)
    checked = 0
    last_key = None
    while not s.over and checked < 6:
        key = s.turn_key()
        legal = s.legal()
        end = next((a for a in legal["actions"] if a["type"] == "END_TURN"), None)
        if key is None or key == last_key or end is None:
            _play_one(gc, rng, allow_end_turn=False)
            continue
        last_key = key
        # No ready message yet: the clock has not started however long it has been.
        clock.advance(5000.0)
        assert gc.tick_clock() is None and gc.clock_info()["running"] is False
        # A ready message for an old state version does not start it either.
        assert gc.client_ready(s.version - 1)["running"] is False
        assert gc.tick_clock() is None
        assert gc.client_ready(s.version)["running"] is True
        clock.advance(5000.0)
        # The human ends the turn by hand before the clock is applied.
        assert gc.submit({"action_id": end["id"], "state_version": s.version})["ok"]
        assert gc.clock_started is None
        version = s.version
        assert gc.tick_clock() is None
        assert s.version == version
        checked += 1
    assert checked == 6
    assert all(r["actor"] != "clock" for r in s.trace)
    _check_integrity(s)


def _submit(session, item_id):
    res = session.submit({"action_id": item_id, "state_version": session.version})
    assert res["ok"], res


def _drive_to(session, target, rng, key):
    """Put the human in a select player, declare, or mid move window of this turn."""
    if target == "select_player":
        return
    legal = session.legal()
    activate = [a for a in legal["actions"] if a["type"] == "ACTIVATE"]
    if not activate:
        return
    _submit(session, rng.choice(activate)["id"])
    if target == "declare_action" or session.over or session.turn_key() != key:
        return
    legal = session.legal()
    moves = [a for a in legal["actions"] if a["type"] == "DECLARE" and a.get("kind") == "MOVE"]
    if legal["prompt"]["kind"] != "declare_action" or not moves:
        return
    _submit(session, moves[0]["id"])
    if session.over or session.turn_key() != key:
        return
    legal = session.legal()
    steps = [a for a in legal["actions"] if a["type"] == "STEP"]
    if legal["prompt"]["kind"] == "move" and steps:
        _submit(session, rng.choice(steps)["id"])


def test_clock_end_turn_from_several_decision_windows(best_policy):
    policy, prov = best_policy
    windows = Counter()
    turns = 0
    for seed, human_seat in ((301, 0), (302, 1), (303, 0)):
        seat = PolicySeat(policy, 1 - human_seat, mode="sample", seed=seed + 7, provenance=prov)
        s = GameSession(seat, human_seat=human_seat, seed=seed)
        rng = random.Random(seed)
        last_key = None
        while not s.over:
            key = s.turn_key()
            legal = s.legal()
            if key is None or key == last_key:
                if key is None:
                    refused = s.clock_end_turn()
                    assert refused == {"ok": False, "error": "not_your_turn",
                                       "state_version": s.version}
                _submit(s, rng.choice(_choices(legal)))
                continue
            last_key = key
            _drive_to(s, ("select_player", "declare_action", "move")[turns % 3], rng, key)
            if s.over or s.turn_key() != key:
                continue
            kind = s.legal()["prompt"]["kind"]
            before = len(s.trace)
            res = s.clock_end_turn()
            assert res["ok"] is True, res
            applied = s.trace[before:]
            assert res["applied"] == applied
            non_policy = [r for r in applied if r["actor"] != "policy"]
            assert len(non_policy) == res["clock_steps"] >= 1
            assert all(r["actor"] == "clock" and r["decision_team"] == human_seat
                       for r in non_policy)
            assert s.over or s.turn_key() != key
            windows[kind] += 1
            turns += 1
            _check_integrity(s)
        assert s.result["natural_completion"] is True, s.result
        _check_integrity(s)
        assert replay_trace(s.header(), s.trace) is None
    assert turns >= 20, turns
    for kind in ("select_player", "declare_action", "move"):
        assert windows[kind] >= 3, windows


@pytest.mark.parametrize("seed,side", [(61, "home"), (62, "away")])
def test_game_with_random_clock_expiries_completes_and_replays(best_policy, tmp_path, seed, side):
    clock = FakeClock()
    gc = _controller(best_policy, tmp_path, clock, clock_mode="soft", clock_seconds=90,
                     seed=seed, human_side=side)
    s = gc.session
    rng = random.Random(seed)
    last_key = None
    expire = False
    actions_left = 0
    expiries = 0
    while not s.over:
        key = s.turn_key()
        if key is not None and key != last_key:
            last_key = key
            assert gc.client_ready(s.version)["running"] is True
            expire = rng.random() < 0.5
            actions_left = rng.randint(0, 6)
        if key is not None and expire and actions_left == 0:
            clock.advance(91.0)
            res = gc.tick_clock()
            assert res is not None and res["ok"] is True, res
            assert s.over or s.turn_key() != key
            expiries += 1
            expire = False
            continue
        actions_left = max(0, actions_left - 1)
        assert gc.tick_clock() is None
        _play_one(gc, rng, allow_end_turn=not (key is not None and expire))
    assert s.result["natural_completion"] is True, s.result
    assert expiries >= 3 and len(gc.clock_events) == expiries
    assert any(r["actor"] == "clock" for r in s.trace)
    _check_integrity(s)
    assert replay_trace(s.header(), s.trace) is None
