"""Rollout core of the decision-time search probe.

A rollout is a search clone of the real session (engine.Engine.clone_for_search)
played forward by the searching seat's own network: its policy on its own
observation row for its decisions, the same network on the opponent's row as
the opponent model, both under the action masks the seat plays with. It stops
when the searcher's team turn ends and is scored by the n-step return

    G = sum over t < T of gamma^t * r_t  +  gamma^T * V(s_T)

with r_t the searcher's own training reward for engine step t (the real session
must run under the training reward manifest), V the searcher's value output on
its observation of s_T, and no V when the match ended.

What a rollout may not touch, and how that is held:
  real dice      a clone is always reseeded; the real stream's id is refused by
                 the shim. Dice seeds here come from rollout_seed, a hash of
                 public values.
  the real seats nothing here takes a seat. The caller hands over copies of the
                 two recurrent states, and sampling uses rollout-only generators.
  the opponent   its reward is never read: the shaped reward is not zero-sum,
                 so the return is the searcher's own reward on every engine
                 step, the opponent's decisions included.

Recurrence follows policy.PolicySeat: both views are forwarded on every engine
step, whoever decides. The states handed to run() are the ones AFTER the
forward on the root observation, which is where a seat stands when it decides.
"""
from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass, field

import numpy as np
import torch

from . import engine as E
from .policy import check_masks, check_temperature, restrict_support, select_joint

GAMMA = 0.999
MAX_ROLLOUT_STEPS = 200
# The dice stream id of every rollout clone. Any id but the real stream's would
# do; rollouts differ by seed.
SEARCH_DICE_STREAM = 2
assert SEARCH_DICE_STREAM != E.REAL_DICE_STREAM

STOP_TURN = "turn"            # the searcher's team turn ended: bootstrapped
STOP_TERMINAL = "terminal"    # the match ended: terminal reward, no bootstrap
STOP_CUTOFF = "cutoff"        # max_steps reached: bootstrapped, and counted
STOP_REJECTED = "rejected"    # engine error or decision cap: no return
STOPS = (STOP_TURN, STOP_TERMINAL, STOP_CUTOFF, STOP_REJECTED)

SEED_PURPOSES = ("dice", "own", "opponent")
_HEAD_OFFSETS = (0, E.ACT_SIZES[0], E.ACT_SIZES[0] + E.ACT_SIZES[1])
_DECLARE = E.A["DECLARE"]


def rollout_seed(sampling_seed, step_index, rollout_index, purpose):
    """A seed for one rollout's dice or sampling, from public values only: the
    seat's sampling seed, the engine step being searched and the rollout index.
    Every candidate at a decision shares the seeds of rollout index j (common
    random numbers)."""
    if purpose not in SEED_PURPOSES:
        raise ValueError(f"unknown seed purpose {purpose!r}")
    data = struct.pack("<qqqB", int(sampling_seed), int(step_index), int(rollout_index),
                       SEED_PURPOSES.index(purpose))
    return int.from_bytes(hashlib.blake2b(data, digest_size=8).digest(), "little") >> 2


def joint_probabilities(logits, support, temperature=1.0):
    """The probability select_joint's sampler gives each tuple of an exact joint
    support: p(type) * p(arg | type) * p(square | type, arg), every factor a
    softmax over the values the support allows after that prefix.

    Returns (packed tuples, probabilities), most probable first, ties in packed
    order. The support is the one the seat samples from, masks applied.
    """
    temperature = check_temperature(temperature)
    logits = torch.as_tensor(logits).reshape(-1).double().numpy() / temperature
    packed = np.unique(np.asarray(support, dtype=np.int64).reshape(-1))
    if packed.size == 0:
        raise ValueError("empty joint support")
    logp = np.zeros(packed.size)
    prefix = np.zeros(packed.size, dtype=np.int64)
    for h in range(3):
        value = (packed >> (10 * h)) & 1023
        # One entry per distinct (prefix, value): a value counts once in its
        # head's softmax however many tuples continue it.
        cells, cell_of = np.unique(prefix * 1024 + value, return_inverse=True)
        cell_logit = logits[_HEAD_OFFSETS[h] + cells % 1024]
        groups, group_of = np.unique(cells // 1024, return_inverse=True)
        top = np.full(groups.size, -np.inf)
        np.maximum.at(top, group_of, cell_logit)
        total = np.zeros(groups.size)
        np.add.at(total, group_of, np.exp(cell_logit - top[group_of]))
        cell_logp = cell_logit - top[group_of] - np.log(total[group_of])
        logp += cell_logp[cell_of]
        prefix = cell_of
    order = np.lexsort((packed, -logp))
    return packed[order].astype(np.uint32), np.exp(logp[order])


@dataclass
class RolloutBatch:
    """What one run() of rollouts returned, one entry per rollout."""
    returns: np.ndarray         # G; nan for a rejected rollout
    rewards: np.ndarray         # the discounted reward part of G
    bootstraps: np.ndarray      # V(s_T) as read, 0 where none was taken
    steps: np.ndarray           # engine steps applied, the first action included
    stops: list                 # one of STOPS
    engine_steps: int = 0
    forward_rows: int = 0
    trails: list = field(default_factory=list)   # record=True: [(team, tuple, reward)]

    def count(self, stop):
        return sum(1 for s in self.stops if s == stop)


class Rollouts:
    """A batch of rollouts for one searching seat.

    policy          the searcher's network. It plays both sides.
    seat            the searcher's physical team, 0 = HOME or 1 = AWAY: the row
                    it observes and the index of its reward.
    masks           action masks on the searcher's decisions (policy.MASKS).
    opponent_masks  masks on the opponent model's decisions; default: `masks`.
    """

    def __init__(self, policy, seat, masks=("m1",), opponent_masks=None, gamma=GAMMA,
                 max_steps=MAX_ROLLOUT_STEPS, temperature=1.0):
        if seat not in (0, 1):
            raise ValueError("seat must be 0 (HOME) or 1 (AWAY)")
        if not 0.0 < gamma <= 1.0:
            raise ValueError(f"gamma must be in (0, 1], got {gamma!r}")
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self.policy = policy
        self.seat = seat
        own = check_masks(masks)
        self.masks = (own, own if opponent_masks is None else check_masks(opponent_masks))
        self.gamma = float(gamma)
        self.max_steps = int(max_steps)
        self.temperature = check_temperature(temperature)
        self._pool = []

    def close(self):
        for clone in self._pool:
            clone.close()
        self._pool = []

    def _clones(self, root, dice_seeds):
        while len(self._pool) < len(dice_seeds):
            self._pool.append(root.clone_for_search(0, SEARCH_DICE_STREAM))
        return [clone.copy_from(root, seed, SEARCH_DICE_STREAM)
                for clone, seed in zip(self._pool, dice_seeds)]

    def run(self, root, own_state, opp_state, first_actions, dice_seeds, generators,
            after_declare=(False, False), clones=None, record=False):
        """Play one rollout per entry of first_actions and score each.

        root           the real session at a decision. It is copied, never stepped.
        own_state      the searcher's recurrent state after its forward on the root
        opp_state      the searcher's network on the opponent's row, likewise
                       (both (layers, 1, hidden); neither is written)
        first_actions  the tuple each rollout applies at the root
        dice_seeds     each rollout's dice seed
        generators     each rollout's (searcher, opponent) sampling generators;
                       never a seat's own generator
        after_declare  (searcher, opponent): that side's previous decision was a
                       DECLARE, as mask m2 reads it at the root
        clones         for tests: ready clones of the root, used as they are
        record         keep each rollout's (team, tuple, reward) trail
        """
        seat, n = self.seat, len(first_actions)
        if clones is None:
            if len(dice_seeds) != n:
                raise ValueError("one dice seed per rollout")
            clones = self._clones(root, dice_seeds)
        if len(clones) != n or len(generators) != n:
            raise ValueError("one clone and one generator pair per rollout")
        base_turns = root.turns_completed()[seat]
        # [0] the searcher's view, [1] the opponent's: row, state, mask flag.
        rows = (seat, 1 - seat)
        state = [own_state.repeat(1, n, 1), opp_state.repeat(1, n, 1)]
        declared = [[bool(after_declare[0]), bool(after_declare[1])] for _ in range(n)]
        out = RolloutBatch(returns=np.zeros(n), rewards=np.zeros(n), bootstraps=np.zeros(n),
                           steps=np.zeros(n, dtype=np.int64), stops=[None] * n,
                           trails=[[] for _ in range(n)] if record else [])
        discount = np.ones(n)
        running, waiting_value = [], []

        def apply(b, action):
            """One engine step of rollout b; files it under running or waiting_value."""
            clone = clones[b]
            view = 0 if clone.decision_team == seat else 1
            rc = clone.step(*action)
            out.engine_steps += 1
            if rc < 0:
                out.stops[b], out.returns[b] = STOP_REJECTED, np.nan
                return
            reward = clone.last_rewards()[seat]
            out.rewards[b] += discount[b] * reward
            discount[b] *= self.gamma
            out.steps[b] += 1
            declared[b][view] = action[0] == _DECLARE
            if record:
                out.trails[b].append((rows[view], tuple(int(v) for v in action), reward))
            if rc == E.STEP_TERMINAL:
                if clone.counters()["final_status"] == E.STATUS_MATCH_OVER:
                    out.stops[b], out.returns[b] = STOP_TERMINAL, out.rewards[b]
                else:
                    out.stops[b], out.returns[b] = STOP_REJECTED, np.nan
            elif clone.status != E.STATUS_DECISION:
                out.stops[b], out.returns[b] = STOP_REJECTED, np.nan
            elif clone.turns_completed()[seat] != base_turns:
                out.stops[b] = STOP_TURN
                waiting_value.append(b)
            elif out.steps[b] >= self.max_steps:
                out.stops[b] = STOP_CUTOFF
                waiting_value.append(b)
            else:
                running.append(b)

        for b in range(n):
            apply(b, first_actions[b])
        while running or waiting_value:
            step_running, step_value = running, waiting_value
            running, waiting_value = [], []
            # One forward: the searcher's view of every rollout still in play or
            # waiting for its bootstrap value, then the opponent's view of those
            # still in play.
            own_rows = step_running + step_value
            obs = np.stack([clones[b].obs(rows[0]) for b in own_rows]
                           + [clones[b].obs(rows[1]) for b in step_running])
            hidden = torch.cat([state[0][:, own_rows], state[1][:, step_running]], dim=1)
            logits, value, hidden = self.policy.forward_eval(torch.from_numpy(obs), hidden)
            out.forward_rows += len(obs)
            state[0][:, own_rows] = hidden[:, :len(own_rows)]
            state[1][:, step_running] = hidden[:, len(own_rows):]
            for i, b in enumerate(step_value, start=len(step_running)):
                out.bootstraps[b] = float(value[i])
                out.returns[b] = out.rewards[b] + discount[b] * out.bootstraps[b]
            for i, b in enumerate(step_running):
                clone = clones[b]
                view = 0 if clone.decision_team == seat else 1
                row = i if view == 0 else len(own_rows) + i
                support = clone.joint_support(rows[view])
                if self.masks[view]:
                    support, _ = restrict_support(support, self.masks[view], declared[b][view])
                action, _, _ = select_joint(logits[row], support, "sample",
                                            generators[b][view], temperature=self.temperature)
                apply(b, action)
        return out
