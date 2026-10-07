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

SearchSeat puts the search into a tournament seat. It is a MaskedPolicySeat
that, at a decision in scope, draws a0 exactly as plain play draws it, rolls a0
and the policy's next most probable actions out through Rollouts.evaluate, and
plays the best alternative only when the deviation rule passes. Its decisions
are those of tools/search_ab.py, which measured the setting (D426); the tests
hold the two to the same games. What the seat adds is the opponent-view state:
in a tournament the opponent may be another network or a scripted bot, so the
seat keeps its own network's recurrent state on the opponent's observation row
(the shadow), forwarded once per engine step, and never reads the other seat.
"""
from __future__ import annotations

import hashlib
import math
import os
import struct
import time
from dataclasses import dataclass, field

import numpy as np
import torch

from . import engine as E
from .policy import (MaskedPolicySeat, check_masks, check_temperature, restrict_support,
                     select_joint)

GAMMA = 0.999
MAX_ROLLOUT_STEPS = 200
# The dice stream id of every rollout clone. Any id but the real stream's would
# do; rollouts differ by seed.
SEARCH_DICE_STREAM = 2
assert SEARCH_DICE_STREAM != E.REAL_DICE_STREAM

# How a rollout ended. After each engine step the checks run in this order: the
# match ended (or the step failed), the searcher's team turn ended, max_steps.
STOP_TURN = "turn"            # the searcher's team turn ended: bootstrapped
STOP_TERMINAL = "terminal"    # the match ended: terminal reward, no bootstrap
STOP_CUTOFF = "cutoff"        # max_steps reached: bootstrapped, and counted
STOP_CAP = "cap"              # the clone hit the decision cap it inherited: no return
STOP_ERROR = "error"          # an integrity failure inside the rollout: no return
STOPS = (STOP_TURN, STOP_TERMINAL, STOP_CUTOFF, STOP_CAP, STOP_ERROR)
# The two that leave a rollout without a return (nan). They are different things:
# a cap ending is a property of where the real game stands, an error never is.
REJECTED = (STOP_CAP, STOP_ERROR)
# The env's and the shim's hard-integrity counters (Engine.counters). Every one
# must be zero in a clone when its rollout ends.
HARD_COUNTERS = ("illegal", "projection_collision", "error_episodes",
                 "rejected_submissions", "precheck_collisions")

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
    tuples, logp = joint_log_probabilities(logits, support, temperature)
    return tuples, np.exp(logp)


def joint_log_probabilities(logits, support, temperature=1.0):
    """joint_probabilities in log space: (packed tuples, log-probabilities), in
    the same order. Finite for finite logits, where the probability of an
    action the policy all but rules out underflows to zero."""
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
    return packed[order].astype(np.uint32), logp[order]


def played_logprob(logp):
    """The log-probability recorded for an action the search played in place of
    a0: log(exp(logp)), the value records have always carried, or logp itself
    where exp(logp) underflows to zero and its log would be -inf."""
    with np.errstate(divide="ignore"):
        value = float(np.log(np.exp(logp)))
    return value if math.isfinite(value) else float(logp)


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
    errors: list = field(default_factory=list)   # (rollout, what failed) per STOP_ERROR
    engine_steps: int = 0
    forward_rows: int = 0
    trails: list = field(default_factory=list)   # record=True: [(team, tuple, reward)]

    def count(self, stop):
        return sum(1 for s in self.stops if s == stop)

    @property
    def rejected(self):
        """Rollouts without a return: decision-cap endings and errors."""
        return sum(1 for s in self.stops if s in REJECTED)


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
    reward_limit    when given, a step reward larger in magnitude is an error:
                    the env's reward design cannot emit it (its clip threshold).

    A rollout ends in STOP_ERROR, with no return, on any integrity failure: the
    engine refuses a step or reports an error, a logit, a value, either seat's
    reward or the accumulated return is not finite, a mask had to give way, no
    action can be selected, or one of HARD_COUNTERS is nonzero in the clone when
    its rollout ends.
    """

    def __init__(self, policy, seat, masks=("m1",), opponent_masks=None, gamma=GAMMA,
                 max_steps=MAX_ROLLOUT_STEPS, temperature=1.0, horizon=HORIZON_TURN,
                 reward_limit=None):
        if seat not in (0, 1):
            raise ValueError("seat must be 0 (HOME) or 1 (AWAY)")
        if horizon not in (HORIZON_TURN, HORIZON_MATCH):
            raise ValueError(f"unknown horizon {horizon!r}")
        self.horizon = horizon
        self.reward_limit = None if reward_limit is None else float(reward_limit)
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

        def fail(b, what):
            out.stops[b], out.returns[b] = STOP_ERROR, np.nan
            out.errors.append((b, what))

        def apply(b, action):
            """One engine step of rollout b; files it under running or waiting_value."""
            clone = clones[b]
            view = 0 if clone.decision_team == seat else 1
            rc = clone.step(*action)
            out.engine_steps += 1
            if rc < 0:
                return fail(b, f"the engine refused {tuple(action)}: rc={rc}")
            rewards = clone.last_rewards()
            # Both seats' rewards are checked; only the searcher's is counted.
            if not all(np.isfinite(r) for r in rewards):
                return fail(b, "a reward that is not finite")
            if self.reward_limit is not None and \
                    max(abs(r) for r in rewards) > self.reward_limit:
                return fail(b, f"a reward of {max(rewards, key=abs)} beyond the limit "
                               f"{self.reward_limit}")
            reward = rewards[seat]
            before = score[b]
            final = clone.final_match() if rc == E.STEP_TERMINAL else None
            score[b] = (int(final.score[0]), int(final.score[1])) if final else clone.score()
            scored = (score[b][seat] - before[seat]) - (score[b][1 - seat] - before[1 - seat])
            out.rewards[b] += discount[b] * reward
            out.touchdowns[b] += discount[b] * reward_td * scored
            discount[b] *= self.gamma
            out.steps[b] += 1
            if not np.isfinite(out.rewards[b]):
                return fail(b, "an accumulated return that is not finite")
            declared[b][view] = action[0] == _DECLARE
            if record:
                out.trails[b].append((rows[view], tuple(int(v) for v in action), reward))
            if rc == E.STEP_TERMINAL:
                if final.status == E.STATUS_MATCH_OVER:
                    out.stops[b], out.returns[b] = STOP_TERMINAL, out.rewards[b]
                    out.scores[b] = score[b][seat], score[b][1 - seat]
                elif final.status == E.STATUS_DECISION and \
                        not clone.counters()["error_episodes"]:
                    # The env ends an episode that is still at a decision only at
                    # its decision budget, which the clone inherited part-spent.
                    out.stops[b], out.returns[b] = STOP_CAP, np.nan
                else:
                    fail(b, f"the match ended in engine status {int(final.status)}")
                return
            if clone.status != E.STATUS_DECISION:
                return fail(b, f"engine status {clone.status} after a step")
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
            finite = (torch.isfinite(logits).all(dim=1) & torch.isfinite(value)).tolist()
            for i, b in enumerate(own_rows):
                if turn_end[b] is not None and finite[i]:
                    out.marks[b].append(turn_end[b] + (float(value[i]),))
                turn_end[b] = None
            for i, b in enumerate(step_value, start=len(step_running)):
                if not finite[i]:
                    fail(b, "a value or logit that is not finite")
                    continue
                out.bootstraps[b] = float(value[i])
                out.returns[b] = out.rewards[b] + discount[b] * out.bootstraps[b]
                if not np.isfinite(out.returns[b]):
                    fail(b, "an accumulated return that is not finite")
            for i, b in enumerate(step_running):
                if not (finite[i] and finite[len(own_rows) + i]):
                    fail(b, "a value or logit that is not finite")
                    continue
                clone = clones[b]
                view = 0 if clone.decision_team == seat else 1
                row = i if view == 0 else len(own_rows) + i
                support = clone.joint_support(rows[view])
                if self.masks[view]:
                    support, events = restrict_support(support, self.masks[view],
                                                       declared[b][view])
                    if any(fallback for _, _, fallback in events.values()):
                        fail(b, "a mask had to give way")
                        continue
                try:
                    action, _, _ = select_joint(logits[row], support, "sample",
                                                generators[b][view],
                                                temperature=self.temperature)
                except (ValueError, AssertionError, RuntimeError) as exc:
                    fail(b, f"no action could be selected: {exc}")
                    continue
                apply(b, action)
        for b, clone in enumerate(clones):
            if out.stops[b] != STOP_ERROR:
                counters = clone.counters()
                nonzero = {name: counters[name] for name in HARD_COUNTERS if counters[name]}
                if nonzero:
                    fail(b, f"hard counters {nonzero}")
        return out


# ---- the search seat's setting ------------------------------------------------------------
# One setting was measured (D426) and is what a seat plays: k, n and delta are
# arguments, everything else below is fixed and travels with them in the
# tournament manifest and in every game record.
CLASSES = ("turn", "declare", "after_declare")
# Searched: the turn-level choice (an ACTIVATE is legal) and the first own
# decision after the own DECLARE. Never the DECLARE itself.
SCOPE = ("turn", "after_declare")
DEFAULT_K = 4
DEFAULT_N = 16
DEFAULT_DELTA = 0.10
REWARD_MANIFEST = "r0_poss_half"
# The digest tools/reward_manifest.py prints for the manifest chain 55 trained on.
REWARD_MANIFEST_SHA256 = "433c792018acdc01f8c7168e824c9389bf99df2307d3260283b7877df3f69d5c"
REWARD_MANIFEST_PATH = os.path.join(E.ROOT, "puffer", "config", "rewards",
                                    REWARD_MANIFEST + ".json")
SE_FLOOR = "sqrt(mean over candidates of per-rollout return variance / n)"
CANDIDATES = "a0, then the others by policy probability, ties in packed-tuple order"
OPPONENT_MODEL = "the seat's own network on the opponent's row, under the seat's own masks"
SETTING_KEYS = ("scope", "k", "n", "delta", "max_rollout_steps", "horizon", "gamma",
                "reward_manifest", "reward_manifest_sha256", "opponent_model", "candidates",
                "se_floor")
# Every integrity check a searched game runs, by the names tools/search_ab.py
# records. In a tournament a failure of any of them aborts the run (the
# tournament's contract), so a record that exists passed them all. A scripted
# bot has no logits or value: the third check covers the policy seats.
INTEGRITY_CHECKS = (
    "real game: the engine's return code on every step",
    "real game: hard counters after every step and at the end (illegal, "
    "projection_collision, error_episodes, rejected_submissions, precheck_collisions)",
    "real game: both seats' logits and values finite on every step",
    "real game: the opponent-view state and value finite on every step (search arms)",
    "real game: both seats' emitted rewards finite and within the clip threshold on every step",
    "real game: no mask fallback",
    "rollouts: the engine's return code and status on every step",
    "rollouts: the same hard counters of every clone at its rollout's end",
    "rollouts: both seats' emitted rewards finite and within the clip threshold on every step",
    "rollouts: logits and values finite on every forward",
    "rollouts: the accumulated return finite",
    "rollouts: no mask fallback, and an action selectable at every decision",
    "search: every return the deviation rule reads is finite",
)
PITCH_REACH = 25.0          # BB_PITCH_LEN - 1, as in bbe_reward_clip_threshold


class SearchIntegrityError(RuntimeError):
    """An integrity failure the search seat found: in a rollout clone, in the
    opponent-view state, or in the returns the deviation rule read."""


def search_setting(k=DEFAULT_K, n=DEFAULT_N, delta=DEFAULT_DELTA):
    """The complete setting of a search seat, as the manifest and the records
    carry it. delta is a finite float >= 0, or infinity: the search runs at
    every decision in scope and never deviates (the identity setting)."""
    if isinstance(k, bool) or not isinstance(k, int) or k < 2:
        raise ValueError(f"search k must be an integer >= 2, got {k!r}")
    if isinstance(n, bool) or not isinstance(n, int) or n < 2:
        raise ValueError(f"search n must be an integer >= 2, got {n!r}")
    if delta == "inf":
        delta = math.inf
    if isinstance(delta, bool) or not isinstance(delta, (int, float)) or \
            math.isnan(delta) or delta < 0.0:
        raise ValueError(f"search delta must be a number >= 0 or inf, got {delta!r}")
    return {"scope": list(SCOPE), "k": k, "n": n,
            "delta": float(delta) if math.isfinite(delta) else "inf",
            "max_rollout_steps": MAX_ROLLOUT_STEPS, "horizon": HORIZON_TURN, "gamma": GAMMA,
            "reward_manifest": REWARD_MANIFEST, "reward_manifest_sha256": REWARD_MANIFEST_SHA256,
            "opponent_model": OPPONENT_MODEL, "candidates": CANDIDATES, "se_floor": SE_FLOOR}


def parse_setting(text):
    """'default' (k 4, n 16, delta 0.10) or 'k:n:delta', delta a number or inf."""
    text = str(text).strip()
    if text == "default":
        return search_setting()
    parts = text.split(":")
    if len(parts) != 3:
        raise ValueError(f"a search setting is 'default' or k:n:delta, got {text!r}")
    try:
        k, n = int(parts[0]), int(parts[1])
        delta = math.inf if parts[2] == "inf" else float(parts[2])
    except ValueError:
        raise ValueError(f"a search setting is 'default' or k:n:delta, got {text!r}")
    return search_setting(k, n, delta)


def check_setting(setting):
    """Raise ValueError unless `setting` is exactly a search_setting(); return it.
    Scope, cutoff, horizon, gamma, reward manifest and opponent model are not
    arguments: a dict that names other values is refused, not obeyed."""
    if not isinstance(setting, dict) or set(setting) != set(SETTING_KEYS):
        raise ValueError(f"a search setting has exactly the keys {list(SETTING_KEYS)}")
    want = search_setting(setting["k"], setting["n"], setting["delta"])
    differ = sorted(key for key in SETTING_KEYS if setting[key] != want[key])
    if differ:
        raise ValueError(f"search setting: {differ} differ from the one setting this seat "
                         f"plays ({ {key: want[key] for key in differ} })")
    return want


_MANIFESTS = {}


def pinned_reward_manifest(lib=None, path=REWARD_MANIFEST_PATH):
    """The reward manifest a searched game is paid under, loaded once per
    process and refused unless it hashes to REWARD_MANIFEST_SHA256."""
    if path not in _MANIFESTS:
        manifest = E.load_reward_manifest(path, lib)
        if manifest["sha256"] != REWARD_MANIFEST_SHA256:
            raise ValueError(f"{path} hashes to {manifest['sha256']}, the search is pinned to "
                             f"{REWARD_MANIFEST} = {REWARD_MANIFEST_SHA256}")
        _MANIFESTS[path] = manifest
    return _MANIFESTS[path]


def reward_clip_threshold(rewards):
    """bbe_reward_clip_threshold (bloodbowl.h) for a reward table: the largest
    magnitude the reward design can emit on one step."""
    objective = abs(rewards["reward_td"]) + max(abs(rewards["reward_win"]),
                                                abs(rewards["reward_draw"]))
    fetch = PITCH_REACH * abs(rewards["reward_dist_ball"])
    carry = PITCH_REACH * abs(rewards["reward_dist_endzone"])
    if rewards["reward_dist_pbrs_gamma"] > 0.0:
        return objective + fetch + carry
    return max(objective, fetch, carry)


# ---- the decision ---------------------------------------------------------------------------
def decision_class(types, after_declare):
    """The class of a decision from the action types on offer after masks, or
    None: 'turn' when an ACTIVATE is legal, 'declare' when a DECLARE is,
    'after_declare' for the first own decision after the own DECLARE."""
    if E.A["ACTIVATE"] in types:
        return "turn"
    if _DECLARE in types:
        return "declare"
    return "after_declare" if after_declare else None


def action_label(action):
    """An action's type, with the declared kind for a DECLARE."""
    name = E.ACTION_TYPES[action[0]]
    if name == "DECLARE" and action[1] < len(E.ACT_KINDS):
        return f"DECLARE:{E.ACT_KINDS[action[1]]}"
    return name


def candidate_order(tuples, a0, k):
    """Indices into joint_probabilities' output (most probable first, ties in
    packed order): a0, then the first k - 1 of the rest."""
    first = int(np.flatnonzero(np.asarray(tuples) == a0)[0])
    return [first] + [i for i in range(len(tuples)) if i != first][:k - 1]


def deviation(returns, delta):
    """The deviation rule on (candidates, rollouts) returns, row 0 = a0.

    Returns (deviate, best alternative as a row index, its paired mean gain over
    a0, the standard error). The gain is the mean over the shared rollout indices
    of G(alternative) - G(a0). The standard error is that difference's, but never
    less than SE_FLOOR. Deviate when the gain exceeds delta and two standard
    errors. An infinite delta never deviates. A return that is not finite is an
    error here, never dropped.

    The arithmetic repeats tools/search_ab.py decide() and
    tools/search_probe_diag.py screen_stats() operation for operation, so both
    give the same floats; test_search_seat.py holds them equal.
    """
    returns = np.asarray(returns, dtype=np.float64)
    if returns.ndim != 2 or returns.shape[0] < 2 or returns.shape[1] < 2:
        raise ValueError("the deviation rule needs two candidates and two rollouts")
    if not np.isfinite(returns).all():
        raise ValueError("a return is not finite")
    # Selects every column. Kept because it fixes the array layout the sums
    # below run over, and with it their rounding (screen_stats does the same).
    returns = returns[:, np.isfinite(returns).all(axis=0)]
    n = returns.shape[1]
    index = np.arange(n)
    d = returns[1:, index] - returns[0, index]
    mean, se = d.mean(axis=1), d.std(axis=1, ddof=1) / np.sqrt(n)
    best = int(np.argmax(mean))
    floor = np.sqrt(returns.var(axis=1, ddof=1).mean() / n)
    gain, error = float(mean[best]), float(max(se[best], floor))
    return bool(gain > delta and gain > 2.0 * error), 1 + best, gain, error


# ---- the seat -------------------------------------------------------------------------------
class SearchSeat(MaskedPolicySeat):
    """A masked policy seat that searches at its decisions in scope.

    At an own decision of class SCOPE with two or more legal actions after masks:
      1. a0 is drawn exactly as the plain masked seat draws it, from the seat's
         own generator. Nothing else ever draws from that generator.
      2. Candidates: a0, then the k - 1 other legal joint actions the policy
         gives the highest probability (CANDIDATES).
      3. n rollouts of each through Rollouts.evaluate, common random numbers
         across candidates, both sides played by this seat's network under this
         seat's masks (OPPONENT_MODEL).
      4. deviation(): play the best alternative only when its paired mean gain
         over a0 exceeds delta and two standard errors; otherwise play a0.
    A rollout that ends on the decision cap its clone inherited is a cap
    rejection: the decision plays a0 and is counted. An integrity failure in a
    rollout raises SearchIntegrityError.

    The opponent-view state (the shadow). Rollouts need this network's recurrent
    state on the opponent's row. The seat cannot take it from the opponent, who
    may be another network or a scripted bot, so it runs its own network on the
    opponent's observation once per engine step, from a zero state at the start
    of the match. That is the same forward a plain seat of this network would
    make in the opponent's chair, so against the same checkpoint the shadow
    equals the opponent's real state bit for bit, and against any other
    opponent it is this network's reading of that opponent's view. The engine
    encodes both observation rows on every step, a bot's included, so nothing
    changes when the opponent is a scripted bot: the shadow is kept the same way,
    and inside a rollout the bot's decisions are modelled by this network.

    The seat is bound to its match's engine after construction (bind): it reads
    the opponent's observation and the last applied action from it and copies it
    for rollouts. It never steps it, and it never touches the other seat.

    Counted apart from the plain seat's bookkeeping: `forwards` stays one per
    engine step; shadow forwards and rollout forward rows are in `stats`.
    """

    def __init__(self, policy, seat, mode="sample", seed=0, provenance=None, temperature=1.0,
                 masks=(), search=None):
        self.search = check_setting(search)
        if mode != "sample":
            raise ValueError("a search seat samples: a0 is the action plain play draws")
        if check_temperature(temperature) != 1.0:
            raise ValueError("a search seat plays at temperature 1")
        if not check_masks(masks):
            raise ValueError("a search seat plays under at least one action mask "
                             "(the measured setting is m1)")
        super().__init__(policy, seat, mode=mode, seed=seed, provenance=provenance,
                         temperature=temperature, masks=masks)
        self.scope = tuple(self.search["scope"])
        self.k, self.n = self.search["k"], self.search["n"]
        self.delta = math.inf if self.search["delta"] == "inf" else float(self.search["delta"])
        self.engine = None
        self.rollouts = None
        self.reward_limit = None
        self._reset_search()

    def _reset_search(self):
        self.shadow = self.policy.initial_state(1)
        self._opponent_declared = False
        self.search_seconds = 0.0
        self.stats = {
            "in_scope": {c: 0 for c in self.scope}, "searched": {c: 0 for c in self.scope},
            "deviations": {c: 0 for c in self.scope}, "deviation_types": {},
            "predicted_gains": [], "rollouts": 0, "rollout_steps": 0, "rollout_forward_rows": 0,
            "cap_rejected_rollouts": 0, "cap_rejected_decisions": 0, "cutoff_rollouts": 0,
            "error_rollouts": 0, "shadow_forwards": 0}

    def reset_match(self):
        super().reset_match()
        self._reset_search()

    def bind(self, engine, manifest):
        """Attach the match's real session, which must pay `manifest`, the
        reward manifest this seat's setting pins."""
        if engine.is_clone:
            raise ValueError("a search seat is bound to the real session, not a clone")
        if manifest["sha256"] != self.search["reward_manifest_sha256"]:
            raise ValueError(f"reward manifest {manifest['sha256']} is not the search "
                             f"setting's {self.search['reward_manifest_sha256']}")
        paid, want = engine.reward_table(), manifest["rewards"]
        if set(paid) != set(want) or \
                any(np.float32(paid[name]) != np.float32(want[name]) for name in want):
            raise ValueError("the session does not pay the search's reward manifest")
        self.close()
        self.engine = engine
        self.reward_limit = reward_clip_threshold(want) * (1.0 + 1e-6)
        self.rollouts = Rollouts(self.policy, self.seat, masks=self.masks,
                                 gamma=self.search["gamma"],
                                 max_steps=self.search["max_rollout_steps"],
                                 temperature=self.temperature, horizon=self.search["horizon"],
                                 reward_limit=self.reward_limit)

    def close(self):
        if self.rollouts is not None:
            self.rollouts.close()
        self.rollouts = None
        self.engine = None

    def _watch(self):
        """Once per engine step, before the seat's own selection: note whether
        the opponent's last decision was a DECLARE (what mask m2 reads for the
        opponent model), and forward the shadow on the opponent's row."""
        agent, last = self.engine.last_action()
        if agent == 1 - self.seat:
            self._opponent_declared = last[0] == _DECLARE
        obs = self.engine.obs(1 - self.seat)
        _, value, self.shadow = self.policy.forward_eval(
            torch.from_numpy(obs).reshape(1, -1), self.shadow)
        self.stats["shadow_forwards"] += 1
        if not bool(torch.isfinite(self.shadow).all() and torch.isfinite(value).all()):
            raise SearchIntegrityError("the opponent-view state is not finite")

    def decide(self, logits, support, deciding):
        if self.engine is None:
            raise RuntimeError("a search seat decides only when bound to its match's engine")
        declared = self._after_declare               # as the masks read it at this decision
        self._watch()
        action, logprob = super().decide(logits, support, deciding)       # a0, as plain play
        if not deciding:
            return action, logprob
        support, _ = restrict_support(support, self.masks, declared)
        cls = decision_class({int(t) & 1023 for t in support}, declared)
        if cls not in self.scope:
            return action, logprob
        stats = self.stats
        stats["in_scope"][cls] += 1
        if len(support) < 2:
            return action, logprob
        stats["searched"][cls] += 1
        started = time.perf_counter()
        tuples, logps = joint_log_probabilities(logits, support, self.temperature)
        order = candidate_order(tuples, E.pack_tuple(*action), self.k)
        candidates = [E.unpack_tuple(tuples[i]) for i in order]
        batch = self.rollouts.evaluate(
            self.engine, self.state, self.shadow, candidates, self.n, self.seed,
            self.forwards - 1, after_declare=(declared, self._opponent_declared))
        self.search_seconds += time.perf_counter() - started
        stats["rollouts"] += len(candidates) * self.n
        stats["rollout_steps"] += batch.engine_steps
        stats["rollout_forward_rows"] += batch.forward_rows
        stats["cutoff_rollouts"] += batch.count(STOP_CUTOFF)
        caps, errors = batch.count(STOP_CAP), batch.count(STOP_ERROR)
        if errors:
            stats["error_rollouts"] += errors
            raise SearchIntegrityError(f"a rollout failed at engine step {self.forwards - 1}: "
                                       f"{batch.errors[0][1]}")
        if caps:
            stats["cap_rejected_rollouts"] += caps
            stats["cap_rejected_decisions"] += 1
            return action, logprob
        try:
            deviate, best, gain, _ = deviation(batch.returns, self.delta)
        except ValueError as exc:
            raise SearchIntegrityError(f"the deviation rule could not be applied at engine "
                                       f"step {self.forwards - 1}: {exc}")
        if not deviate:
            return action, logprob
        played = tuple(int(v) for v in candidates[best])
        key = f"{cls}: {action_label(action)} -> {action_label(played)}"
        stats["deviation_types"][key] = stats["deviation_types"].get(key, 0) + 1
        stats["deviations"][cls] += 1
        stats["predicted_gains"].append(round(gain, 6))
        self._after_declare = played[0] == _DECLARE
        # The log-probability the policy gave the action played, under the same
        # masked support a0 was drawn from.
        return played, played_logprob(logps[order[best]])
