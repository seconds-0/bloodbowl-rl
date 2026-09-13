from play_harness.drivers import RandomDriver, ScriptedActionsDriver, play_to_completion
from play_harness.policy import PolicySeat
from play_harness.session import GameSession, replay_trace


def _session(best_policy, driver, policy_seed=3, seed=41, human_seat=0):
    policy, prov = best_policy
    seat = PolicySeat(policy, 1 - human_seat, mode="sample", seed=policy_seed, provenance=prov)
    session = GameSession(seat, human_seat=human_seat, seed=seed, home_team=6, away_team=7)
    play_to_completion(session, driver)
    return session


def _essential(trace):
    return [(r["step"], r["actor"], tuple(r["tuple"]), r["digest"], r.get("policy_logprob"))
            for r in trace]


def test_same_seed_and_human_actions_reproduce_the_trace(best_policy):
    first = _session(best_policy, RandomDriver(seed=9))
    human_actions = [r["action"] for r in first.trace if r["actor"] == "human"]
    second = _session(best_policy, ScriptedActionsDriver(human_actions))
    assert first.over and second.over
    assert _essential(first.trace) == _essential(second.trace)
    assert first.result == second.result


def test_recorded_trace_replays_on_a_fresh_engine(best_policy):
    session = _session(best_policy, RandomDriver(seed=10), seed=42, human_seat=1)
    assert replay_trace(session.header(), session.trace) is None
    tampered = [dict(r) for r in session.trace]
    tampered[50] = {**tampered[50], "digest": "0" * 16}
    assert replay_trace(session.header(), tampered)[0] == 50


def test_policy_sampling_seed_matters(best_policy):
    a = _session(best_policy, RandomDriver(seed=12), policy_seed=1, seed=43)
    b = _session(best_policy, RandomDriver(seed=12), policy_seed=2, seed=43)
    assert _essential(a.trace) != _essential(b.trace)
