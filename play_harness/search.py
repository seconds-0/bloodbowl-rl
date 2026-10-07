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
  the real seats nothing here takes a seat. The caller hands over the two
                 recurrent states, which are copied, and evaluate() builds every
                 clone and every sampling generator itself from rollout_seed.
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

# Where a rollout is meant to end. The search stops at the end of the searcher's
# team turn. A rollout to the end of the match is for measurement: it shows what
# an action did to the result, with no value read into the judgment.
HORIZON_TURN = "turn"
HORIZON_MATCH = "match"

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
    touchdowns: np.ndarray      # the part of `rewards` paid for touchdowns, either way
    scores: np.ndarray          # (searcher, opponent) final score where the match
    #                             ended naturally, else -1
    # Per rollout, one entry for each end of the searcher's team turn it passed
    # with a value read there: (steps, rewards, touchdowns, V) as they stood. A
    # rollout stopped at the turn has exactly one, its own stop.
    marks: list = field(default_factory=list)
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
    horizon         HORIZON_TURN (the search's stop rule) or HORIZON_MATCH: play on
                    past the searcher's turn ends, marking each, to the end of
                    the match or max_steps.
    """

    def __init__(self, policy, seat, masks=("m1",), opponent_masks=None, gamma=GAMMA,
                 max_steps=MAX_ROLLOUT_STEPS, temperature=1.0, horizon=HORIZON_TURN):
        if seat not in (0, 1):
            raise ValueError("seat must be 0 (HOME) or 1 (AWAY)")
        if horizon not in (HORIZON_TURN, HORIZON_MATCH):
            raise ValueError(f"unknown horizon {horizon!r}")
        self.horizon = horizon
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

    def evaluate(self, root, own_state, opp_state, candidates, rollouts, sampling_seed,
                 step_index, after_declare=(False, False), record=False, first_index=0):
        """`rollouts` rollouts of every candidate action at the root, scored.

        root           the session at a decision. It is copied, never stepped.
        own_state      the searcher's recurrent state after its forward on the root
        opp_state      the searcher's network on the opponent's row, likewise
                       (both (layers, 1, hidden); neither is written)
        candidates     the tuples to compare, each applied at the root
        sampling_seed, step_index
                       the seat's sampling seed and the engine step searched:
                       with the rollout index, all a rollout's dice and sampling
                       derive from (rollout_seed)
        after_declare  (searcher, opponent): that side's previous decision was a
                       DECLARE, as mask m2 reads it at the root
        record         keep each rollout's (team, tuple, reward) trail
        first_index    the rollout index of the first rollout: another range of
                       indices is another, independent set of rollouts

        Common random numbers: rollout j of every candidate has the same dice
        seed and the same two sampling seeds. The batch's arrays come back
        shaped (candidates, rollouts); stops, marks and trails stay flat,
        candidate by candidate.
        """
        k, n = len(candidates), int(rollouts)
        if k < 1 or n < 1:
            raise ValueError("at least one candidate and one rollout")
        while len(self._pool) < k * n:
            self._pool.append(root.clone_for_search(0, SEARCH_DICE_STREAM))
        seeds = [[rollout_seed(sampling_seed, step_index, first_index + j, purpose)
                  for j in range(n)] for purpose in SEED_PURPOSES]
        clones = [self._pool[c * n + j].copy_from(root, seeds[0][j], SEARCH_DICE_STREAM)
                  for c in range(k) for j in range(n)]
        generators = [(torch.Generator().manual_seed(seeds[1][j]),
                       torch.Generator().manual_seed(seeds[2][j]))
                      for _ in range(k) for j in range(n)]
        firsts = [tuple(action) for action in candidates for _ in range(n)]
        out = self._play(root, own_state, opp_state, firsts, clones, generators,
                         after_declare, record)
        for name in ("returns", "rewards", "bootstraps", "steps", "touchdowns"):
            setattr(out, name, getattr(out, name).reshape(k, n))
        out.scores = out.scores.reshape(k, n, 2)
        return out

    def _play(self, root, own_state, opp_state, first_actions, clones, generators,
              after_declare=(False, False), record=False):
        """One rollout per entry of first_actions, on the clones and generators
        given: clones[b] is stepped, generators[b] is its (searcher, opponent)
        pair. evaluate() is the entry point; tests call this to hand a rollout
        the real dice and copies of the real generators.
        """
        seat, n = self.seat, len(first_actions)
        if len(clones) != n or len(generators) != n:
            raise ValueError("one clone and one generator pair per rollout")
        if len({id(c) for c in clones}) != n or \
                any(c is root or not c.is_clone for c in clones):
            raise ValueError("a rollout steps its own search clone, never the root")
        if len({id(g) for pair in generators for g in pair}) != 2 * n:
            raise ValueError("every rollout needs its own two generators")
        # [0] the searcher's view, [1] the opponent's: row, state, mask flag.
        rows = (seat, 1 - seat)
        state = [own_state.repeat(1, n, 1), opp_state.repeat(1, n, 1)]
        declared = [[bool(after_declare[0]), bool(after_declare[1])] for _ in range(n)]
        out = RolloutBatch(returns=np.zeros(n), rewards=np.zeros(n), bootstraps=np.zeros(n),
                           steps=np.zeros(n, dtype=np.int64), stops=[None] * n,
                           touchdowns=np.zeros(n), scores=np.full((n, 2), -1, dtype=np.int64),
                           marks=[[] for _ in range(n)],
                           trails=[[] for _ in range(n)] if record else [])
        discount = np.ones(n)
        turns = [root.turns_completed()[seat]] * n       # the searcher's counter, as last seen
        score = [root.score()] * n
        reward_td = root.reward_table()["reward_td"]
        turn_end = [None] * n                # a turn end passed, waiting for its value
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
            before = score[b]
            final = clone.final_match() if rc == E.STEP_TERMINAL else None
            score[b] = (int(final.score[0]), int(final.score[1])) if final else clone.score()
            scored = (score[b][seat] - before[seat]) - (score[b][1 - seat] - before[1 - seat])
            out.rewards[b] += discount[b] * reward
            out.touchdowns[b] += discount[b] * reward_td * scored
            discount[b] *= self.gamma
            out.steps[b] += 1
            declared[b][view] = action[0] == _DECLARE
            if record:
                out.trails[b].append((rows[view], tuple(int(v) for v in action), reward))
            if rc == E.STEP_TERMINAL:
                if final.status == E.STATUS_MATCH_OVER:
                    out.stops[b], out.returns[b] = STOP_TERMINAL, out.rewards[b]
                    out.scores[b] = score[b][seat], score[b][1 - seat]
                else:
                    out.stops[b], out.returns[b] = STOP_REJECTED, np.nan
                return
            if clone.status != E.STATUS_DECISION:
                out.stops[b], out.returns[b] = STOP_REJECTED, np.nan
                return
            now = clone.turns_completed()[seat]
            if now != turns[b]:
                turns[b] = now
                turn_end[b] = (int(out.steps[b]), float(out.rewards[b]), float(out.touchdowns[b]))
                if self.horizon == HORIZON_TURN:
                    out.stops[b] = STOP_TURN
                    waiting_value.append(b)
                    return
            if out.steps[b] >= self.max_steps:
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
            for i, b in enumerate(own_rows):
                if turn_end[b] is not None:
                    out.marks[b].append(turn_end[b] + (float(value[i]),))
                    turn_end[b] = None
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
