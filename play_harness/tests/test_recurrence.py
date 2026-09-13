"""Native evaluation-mode recurrence: one forward per c_step, reset per match.

D388 recorded chain 9 at 0.22 TD/game through a bridge that stepped the
recurrent policy only on its own decisions, against 0.40 native. These tests
pin the harness to the native contract.
"""
import torch

from play_harness.drivers import CoverageDriver, play_to_completion
from play_harness.policy import PolicySeat
from play_harness.session import GameSession


class RecordingSeat(PolicySeat):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.log = []

    def step(self, obs, support, deciding):
        before = self.state.clone()
        out = super().step(obs, support, deciding)
        self.log.append({"deciding": deciding, "before": before, "after": self.state.clone(),
                         "obs": obs.copy(), "logits": out["logits"]})
        return out


def _played_session(best_policy, human_seat=0, seed=31):
    policy, prov = best_policy
    seat = RecordingSeat(policy, 1 - human_seat, mode="sample", seed=4, provenance=prov)
    session = GameSession(seat, human_seat=human_seat, seed=seed)
    play_to_completion(session, CoverageDriver(seed=seed))
    return session, seat


def test_policy_state_advances_on_waiting_coach_steps(best_policy):
    session, seat = _played_session(best_policy)
    assert session.over and session.result["natural_completion"]
    assert seat.forwards == session.version == len(seat.log) == len(session.trace)
    waiting = [e for e in seat.log if not e["deciding"]]
    deciding = [e for e in seat.log if e["deciding"]]
    assert len(waiting) > 100 and len(deciding) > 100
    for entry in waiting:
        assert not torch.equal(entry["before"], entry["after"])
    humans = [r for r in session.trace if r["actor"] == "human"]
    assert all(r["policy_forward"] == r["step"] + 1 for r in session.trace)
    assert len(humans) == len(waiting)


def test_state_resets_once_at_match_start(best_policy):
    _, seat = _played_session(best_policy, human_seat=1, seed=32)
    assert torch.count_nonzero(seat.log[0]["before"]) == 0
    assert all(torch.count_nonzero(e["before"]) > 0 for e in seat.log[1:])
    seat.reset_match()
    assert torch.count_nonzero(seat.state) == 0 and seat.forwards == 0


def test_learner_only_stepping_is_a_different_policy(best_policy):
    """Control: skipping waiting-coach forwards changes the decision logits."""
    session, seat = _played_session(best_policy, seed=33)
    policy = seat.policy
    every = policy.initial_state(1)
    learner_only = policy.initial_state(1)
    worst_every, worst_learner = 0.0, 0.0
    for entry in seat.log:
        x = torch.from_numpy(entry["obs"]).reshape(1, -1)
        logits_every, _, every = policy.forward_eval(x, every)
        if entry["deciding"]:
            logits_lo, _, learner_only = policy.forward_eval(x, learner_only)
            ref = torch.from_numpy(entry["logits"])
            worst_every = max(worst_every, float((logits_every[0] - ref).abs().max()))
            worst_learner = max(worst_learner, float((logits_lo[0] - ref).abs().max()))
    assert worst_every == 0.0
    assert worst_learner > 1e-3
