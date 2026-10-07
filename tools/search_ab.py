#!/usr/bin/env python3
"""Whole-game offline A/B of the rollout search: seat A searches, seat B does not.

Everything a game depends on comes from a PLAN file, and every command takes
the plan with --expect-sha256 and refuses a file that does not hash to it.
The plan names the checkpoint and the reward manifest by hash, the code by
commit and source hash, gamma, the masks of both seats, their sampling offsets,
the search (scope, k, n, floor, cutoff), the arms, the identity sample and the
seed range of every shard. tools/search_ab_plan.example.json is an example.

The game. Both seats are one checkpoint at the plan's temperature from the
kick-off, on a session that pays the reward manifest. Every engine seed is
played in both orientations (A home, A away) under every arm:

  plain     delta null: no rollouts at all. The baseline.
  search    delta d: at each decision of seat A in scope (turn level: an
            ACTIVATE is legal; after_declare: the first own decision after
            the own DECLARE) that has two or more legal actions after masks,
            a0 is drawn exactly as plain play draws it, then a0 and the
            alternatives are rolled out through Rollouts.evaluate and the best
            alternative is played only if its paired mean gain over a0 exceeds
            d AND two standard errors. Otherwise a0 is played.
  identity  delta infinite, on the first seeds of every shard: the full search
            runs at every decision in scope and is thrown away. Its games must
            equal the plain arm's on action trail, final state and sampling
            state; `report` checks every one.

Fixed details, each held by a test:
  candidates   a0 first, then the other legal actions by policy probability,
               highest first; equal probabilities in ascending packed-tuple
               order (type | arg << 10 | square << 20). Up to k in all. With
               fewer than k legal actions, all of them. A decision with a single
               legal action is not searched and not counted as searched.
  standard     the standard error of the paired difference over the n rollout
  error        indices, but never less than
               sqrt(mean over candidates of per-rollout return variance / n).
  rollouts     stop, checked in this order after each engine step: the match
               ended (terminal reward, no value); the searcher's team turn ended
               (value read there); max_rollout_steps (value read there, counted
               as a cutoff).
  generators   a rollout's dice and sampling come from rollout_seed(A's sampling
               seed, engine step, rollout index). The search never draws from
               either real seat's generator and never reads seat B at all: the
               opponent in a rollout is A's own network on B's row.

What can go wrong, kept apart and never merged:
  invalid         an integrity failure anywhere, in the real game or in any
                  clone: an engine error or refused step, a support or
                  selection error, a logit, value, reward or return that is not
                  finite, a reward beyond the env's clip threshold, a mask that
                  had to give way, a nonzero integrity counter. The record is
                  marked invalid and `report` refuses the whole arm.
  decision cap    the real game ended on the decision cap. Recorded; `report`
                  refuses the comparison.
  cap rejection   a rollout ended on the decision cap its clone inherited. The
                  decision plays a0. Counted per game; `report` gives the share
                  of searched decisions with one and refuses an arm above the
                  plan's ceiling.
  cutoff          a rollout reached max_rollout_steps. Bootstrapped, counted,
                  allowed, reported.

What is checked for `invalid`, and where, is INTEGRITY_CHECKS below; every
record carries the list. Not covered: the env's own reward telemetry (its
clipped, non-finite and component-mismatch counters), which the shim does not
export. The checks on the rewards the env emits, for both seats, on every real
step and every rollout step, stand in for it.

One arm of one (seed, orientation) is a pure function of the plan, so results
do not depend on the number of processes or the order games finish. A shard
plays ALL arms for its own seeds, seed by seed, so a shard that dies early has
covered every arm alike. Each game is one line of games.jsonl, written when it
ends; a rerun plays only the keys that are not there and never rewrites one.

  tools/search_ab.py hashes [--checkpoint BLOB] [--manifest JSON] [--plan PLAN]
  OMP_NUM_THREADS=1 tools/search_ab.py play --plan PLAN --expect-sha256 H \\
      --shard NAME --checkpoint BLOB --out-dir DIR [--processes P]
  tools/search_ab.py report --plan PLAN --expect-sha256 H DIR [DIR ...] [--out-dir OUT]

`report` prints outcome statistics only when acceptance passes. Intervals are
percentile bootstraps (2.5 and 97.5) over engine seeds, the plan's replicate
count and generator seed: both orientations of a seed and all arms are
resampled together, so a contrast between arms is computed inside each
replicate. A replicate with no decisive game for an arm has no decisive share:
it is left out of that arm's decisive-share and Elo percentiles, and the report
says how many were. A replicate with wins and no losses (or the reverse) has a
share of 1 (or 0), which the Elo transform clips to about +4800 (or -4800). An
arm with no decisive game at all fails acceptance: its Elo is undefined. So
does a native library hash that differs between shards.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import struct
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import search_probe_diag as diag  # noqa: E402

SCHEMA = "search-ab-game-v1"
RUN_SCHEMA = "search-ab-run-v1"
PLAN_SCHEMA = "search-ab-plan-v1"
LEGS = ("A_home", "B_home")
TEST_POLICY = "test-random:"
DEFAULT_MANIFEST = os.path.join(ROOT, "puffer", "config", "rewards", "r0_poss_half.json")
# The plan must quote these two sentences: they are what this file implements.
SE_FLOOR = "sqrt(mean over candidates of per-rollout return variance / n)"
CANDIDATES = "a0, then the others by policy probability, ties in packed-tuple order"
# The sources whose bytes define what a game of this tool is.
CODE_FILES = ("play_harness/search.py", "play_harness/policy.py", "play_harness/engine.py",
              "play_harness/tournament.py", "play_harness/tournament_stats.py",
              "play_harness/native/bbplay.c", "tools/search_ab.py",
              "tools/search_probe_diag.py")
SCORE = {"W": 1.0, "D": 0.5, "L": 0.0}
# Every integrity check a game runs. Any failure marks its record invalid.
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
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SHARD_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,30}$")
PITCH_REACH = 25.0          # BB_PITCH_LEN - 1, as in bbe_reward_clip_threshold


# ---- the plan -------------------------------------------------------------------------------
def code_sha256(root=ROOT):
    h = hashlib.sha256()
    for name in CODE_FILES:
        with open(os.path.join(root, name), "rb") as f:
            data = f.read()
        h.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def validate_plan(plan):
    """Raise ValueError unless `plan` is a complete search-ab plan; return it."""
    def need(cond, what):
        if not cond:
            raise ValueError(f"plan: {what}")

    need(isinstance(plan, dict) and plan.get("schema") == PLAN_SCHEMA,
         f"schema must be {PLAN_SCHEMA}")
    known = {"schema", "name", "source_commit", "code_sha256", "checkpoint_sha256",
             "reward_manifest_sha256", "gamma", "temperature", "masks", "sampling_offsets",
             "max_decisions", "search", "arms", "identity", "shards",
             "cap_rejection_ceiling", "bootstrap"}
    need(set(plan) == known, f"keys must be exactly {sorted(known)}; "
         f"missing {sorted(known - set(plan))}, unknown {sorted(set(plan) - known)}")
    need(isinstance(plan["name"], str) and plan["name"], "name must be a string")
    need(HEX40.match(str(plan["source_commit"])), "source_commit must be a 40-hex commit")
    need(HEX64.match(str(plan["code_sha256"])), "code_sha256 must be 64 hex")
    need(HEX64.match(str(plan["checkpoint_sha256"]))
         or str(plan["checkpoint_sha256"]).startswith(TEST_POLICY),
         "checkpoint_sha256 must be 64 hex")
    need(HEX64.match(str(plan["reward_manifest_sha256"])), "reward_manifest_sha256 must be 64 hex")
    need(isinstance(plan["gamma"], float) and 0.0 < plan["gamma"] <= 1.0, "gamma in (0, 1]")
    need(plan["temperature"] == 1.0, "temperature must be 1.0")
    for key, kind in (("masks", list), ("sampling_offsets", int)):
        need(isinstance(plan[key], dict) and set(plan[key]) == {"a", "b"}
             and all(isinstance(v, kind) and not isinstance(v, bool)
                     for v in plan[key].values()), f"{key} needs entries a and b")
    need(all(o >= 0 for o in plan["sampling_offsets"].values()), "sampling offsets >= 0")
    need(isinstance(plan["max_decisions"], int) and plan["max_decisions"] > 0, "max_decisions")
    search = plan["search"]
    need(isinstance(search, dict) and set(search) == {"scope", "k", "n", "se_floor",
                                                      "candidates", "max_rollout_steps"},
         "search needs scope, k, n, se_floor, candidates, max_rollout_steps")
    need(isinstance(search["scope"], list) and search["scope"]
         and set(search["scope"]) <= set(diag.CLASSES)
         and len(set(search["scope"])) == len(search["scope"]),
         f"search.scope must be classes of {list(diag.CLASSES)}")
    need(isinstance(search["k"], int) and search["k"] >= 2, "search.k >= 2")
    need(isinstance(search["n"], int) and search["n"] >= 2, "search.n >= 2")
    need(isinstance(search["max_rollout_steps"], int) and search["max_rollout_steps"] >= 1,
         "search.max_rollout_steps >= 1")
    need(search["se_floor"] == SE_FLOOR, f"search.se_floor must read {SE_FLOOR!r}")
    need(search["candidates"] == CANDIDATES, f"search.candidates must read {CANDIDATES!r}")
    arms = plan["arms"]
    need(isinstance(arms, list) and arms, "arms must be a list")
    for arm in arms:
        need(isinstance(arm, dict) and set(arm) == {"name", "delta"}
             and isinstance(arm["name"], str) and SHARD_RE.match(arm["name"]),
             "an arm is {name, delta}, name lower-case letters, digits and dashes")
        need(arm["delta"] is None or (isinstance(arm["delta"], float)
                                      and math.isfinite(arm["delta"]) and arm["delta"] >= 0.0),
             f"arm {arm['name']}: delta is null (plain) or a finite float >= 0")
    identity = plan["identity"]
    need(isinstance(identity, dict) and set(identity) == {"arm", "seeds_per_shard"}
         and isinstance(identity["arm"], str) and SHARD_RE.match(identity["arm"])
         and isinstance(identity["seeds_per_shard"], int) and identity["seeds_per_shard"] >= 1,
         "identity is {arm, seeds_per_shard >= 1}")
    names = [arm["name"] for arm in arms] + [identity["arm"]]
    need(len(set(names)) == len(names), "arm names must differ, the identity arm's too")
    need(sum(arm["delta"] is None for arm in arms) == 1, "exactly one arm has delta null")
    shards = plan["shards"]
    need(isinstance(shards, list) and shards, "shards must be a list")
    taken = set()
    for shard in shards:
        need(isinstance(shard, dict) and set(shard) == {"name", "seed_start", "seed_count"}
             and isinstance(shard["name"], str) and SHARD_RE.match(shard["name"])
             and isinstance(shard["seed_start"], int) and isinstance(shard["seed_count"], int)
             and shard["seed_start"] >= 0 and shard["seed_count"] >= 1,
             "a shard is {name, seed_start, seed_count >= 1}")
        need(identity["seeds_per_shard"] <= shard["seed_count"],
             f"shard {shard['name']} has fewer seeds than the identity sample")
        seeds = set(range(shard["seed_start"], shard["seed_start"] + shard["seed_count"]))
        need(not (seeds & taken), f"shard {shard['name']} repeats a seed of another shard")
        taken |= seeds
    need(len({s["name"] for s in shards}) == len(shards), "shard names must differ")
    ceiling = plan["cap_rejection_ceiling"]
    need(isinstance(ceiling, float) and 0.0 <= ceiling <= 1.0, "cap_rejection_ceiling in [0, 1]")
    boot = plan["bootstrap"]
    need(isinstance(boot, dict) and set(boot) == {"reps", "seed", "quantiles"}
         and isinstance(boot["reps"], int) and boot["reps"] >= 100
         and isinstance(boot["seed"], int) and boot["quantiles"] == [2.5, 97.5],
         "bootstrap is {reps >= 100, seed, quantiles [2.5, 97.5]}")
    return plan


def load_plan(path, expect_sha256):
    """The plan at `path`, only if its bytes hash to expect_sha256: (plan, sha256)."""
    with open(path, "rb") as f:
        raw = f.read()
    digest = hashlib.sha256(raw).hexdigest()
    if digest != str(expect_sha256).strip().lower():
        raise SystemExit(f"{path} hashes to {digest}, not the expected {expect_sha256}")
    try:
        return validate_plan(json.loads(raw)), digest
    except ValueError as exc:
        raise SystemExit(str(exc))


def plan_arms(plan):
    """{name: delta} for every arm, the identity arm included (delta inf)."""
    arms = {arm["name"]: arm["delta"] for arm in plan["arms"]}
    arms[plan["identity"]["arm"]] = math.inf
    return arms


def plain_arm(plan):
    return next(arm["name"] for arm in plan["arms"] if arm["delta"] is None)


def shard_tasks(plan, shard_name):
    """The (seed, leg, arm) keys of one shard, seed by seed and orientation by
    orientation with every arm side by side; the identity arm on its first seeds."""
    shard = next((s for s in plan["shards"] if s["name"] == shard_name), None)
    if shard is None:
        raise SystemExit(f"the plan has no shard {shard_name!r}")
    names = [arm["name"] for arm in plan["arms"]]
    tasks = []
    for i in range(shard["seed_count"]):
        for leg in LEGS:
            arms = names + ([plan["identity"]["arm"]] if i < plan["identity"]["seeds_per_shard"]
                            else [])
            tasks += [(shard["seed_start"] + i, leg, arm) for arm in arms]
    return tasks


def plan_tasks(plan):
    return [task for shard in plan["shards"] for task in shard_tasks(plan, shard["name"])]


def shard_of(plan, seed):
    for shard in plan["shards"]:
        if shard["seed_start"] <= seed < shard["seed_start"] + shard["seed_count"]:
            return shard["name"]
    return None


def game_settings(plan, arm):
    """What a record states about how its game was played; `report` compares it
    with the plan field by field."""
    delta = plan_arms(plan)[arm]
    search = None
    if delta is not None:
        search = dict(plan["search"], delta=delta if math.isfinite(delta) else "inf")
    return {"gamma": plan["gamma"], "temperature": plan["temperature"], "masks": plan["masks"],
            "sampling_offsets": plan["sampling_offsets"],
            "max_decisions": plan["max_decisions"], "search": search}


# ---- the decision ---------------------------------------------------------------------------
def candidate_order(tuples, a0, k):
    """Indices into joint_probabilities' output (already most probable first, ties
    in packed order): a0, then the first k - 1 of the rest."""
    first = int(np.flatnonzero(np.asarray(tuples) == a0)[0])
    return [first] + [i for i in range(len(tuples)) if i != first][:k - 1]


def decide(returns, delta):
    """The deviation rule on (candidates, rollouts) returns, row 0 = a0.

    Returns (deviate, best alternative as a row index, its paired mean gain, the
    floored standard error). An infinite delta never deviates. A return that is
    not finite is an error here, never dropped.
    """
    returns = np.asarray(returns, dtype=np.float64)
    if not np.isfinite(returns).all():
        raise ValueError("a return is not finite")
    stats = diag.screen_stats(returns)
    deviate = bool(stats["gain"] > delta and stats["gain"] > 2.0 * stats["se"])
    return deviate, 1 + stats["best"], stats["gain"], stats["se"]


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


# ---- one game -------------------------------------------------------------------------------
class Player:
    """The harness, loaded once per process and checked against the plan."""

    def __init__(self, plan, plan_sha256, shard, checkpoint, manifest, processes=1):
        import numpy
        import torch

        from play_harness import engine as E
        from play_harness import search as S
        from play_harness import tournament as T
        from play_harness.policy import (MaskedPolicySeat, PolicySeat, load_checkpoint,
                                         random_policy, restrict_support)

        torch.set_num_threads(1)
        self.torch, self.E, self.S, self.T = torch, E, S, T
        self.MaskedPolicySeat, self.PolicySeat = MaskedPolicySeat, PolicySeat
        self.restrict_support = restrict_support
        self.plan, self.shard = plan, shard
        if str(checkpoint).startswith(TEST_POLICY):
            # Tests only: a seeded random network. Its "hash" is its name, and
            # report refuses a run played with it unless told to allow it.
            self.policy = random_policy(seed=int(checkpoint[len(TEST_POLICY):]), scale=0.05)
            checkpoint_sha = str(checkpoint)
        else:
            self.policy, provenance = load_checkpoint(checkpoint)
            checkpoint_sha = provenance["checkpoint_sha256"]
        self.manifest = E.load_reward_manifest(manifest)
        self.hashes = {"plan_sha256": plan_sha256, "checkpoint_sha256": checkpoint_sha,
                       "reward_manifest_sha256": self.manifest["sha256"],
                       "source_commit": T._git_head(), "code_sha256": code_sha256()}
        for key in ("checkpoint_sha256", "reward_manifest_sha256", "source_commit",
                    "code_sha256"):
            if self.hashes[key] != plan[key]:
                raise SystemExit(f"{key} is {self.hashes[key]}, the plan says {plan[key]}")
        lib = E.load_library()
        self.runtime = {
            "library_sha256": T.library_sha256(), "abi": int(lib.bbp_abi_version()),
            "obs_version": int(lib.bbp_obs_version()), "obs_size": int(lib.bbp_obs_size()),
            "torch": torch.__version__, "numpy": numpy.__version__,
            "python": platform.python_version(),
            "precision": str(next(self.policy.parameters()).dtype),
            "torch_threads": int(torch.get_num_threads()), "processes": int(processes),
            "hostname": platform.node(), "machine": platform.machine(),
            "kernel": platform.release()}
        self.masks = (tuple(plan["masks"]["a"]), tuple(plan["masks"]["b"]))
        self.scope = tuple(plan["search"]["scope"])
        self.reward_limit = reward_clip_threshold(self.manifest["rewards"]) * (1.0 + 1e-6)
        self.rollouts = [S.Rollouts(self.policy, seat, masks=self.masks[0],
                                    opponent_masks=self.masks[1], gamma=plan["gamma"],
                                    max_steps=plan["search"]["max_rollout_steps"],
                                    temperature=plan["temperature"],
                                    reward_limit=self.reward_limit) for seat in (0, 1)]

    def seat(self, side, role, engine_seed):
        """A real seat for physical side `side` playing role 0 (A) or 1 (B)."""
        T = self.T
        offset = self.plan["sampling_offsets"]["ab"[role]]
        seed = T.sampling_seed(engine_seed, side)
        if offset:
            seed = (seed + offset * T.SEED_OFFSET_STRIDE) % (1 << 62)
        masks = self.masks[role]
        made = self.MaskedPolicySeat(self.policy, side, seed=seed, masks=masks,
                                     temperature=self.plan["temperature"]) if masks else \
            self.PolicySeat(self.policy, side, seed=seed, temperature=self.plan["temperature"])
        made.reset_match()
        return made

    def play(self, engine_seed, leg, arm):
        """One whole game; returns its record."""
        torch, E, S, T = self.torch, self.E, self.S, self.T
        plan, scope = self.plan, self.scope
        delta = plan_arms(plan)[arm]
        search = delta is not None
        k, n = plan["search"]["k"], plan["search"]["n"]
        a = LEGS.index(leg)                                  # seat A's side
        seats = [self.seat(side, 0 if side == a else 1, engine_seed) for side in (0, 1)]
        eng = E.Engine(engine_seed, rewards=self.manifest["rewards"],
                       max_decisions=plan["max_decisions"])
        # A's own network on B's row, every step: the opponent-view state its
        # rollouts start from. A plain game has no use for it.
        shadow = self.policy.initial_state(1) if search else None
        trail = hashlib.sha256()
        in_scope = {c: 0 for c in scope}
        searched = {c: 0 for c in scope}
        deviations = {c: 0 for c in scope}
        deviation_types, gains, invalid = {}, [], []
        count = {"rollouts": 0, "rollout_steps": 0, "cap_rejected_rollouts": 0,
                 "cap_rejected_decisions": 0, "cutoff_rollouts": 0, "error_rollouts": 0}
        step, finished = 0, False
        started = time.time()

        def flag(what):
            if len(invalid) < 8:
                invalid.append(f"step {step}: {what}")

        while True:
            team = eng.decision_team
            flags = [getattr(seat, "_after_declare", False) for seat in seats]
            obs = [eng.obs(0), eng.obs(1)]
            supports = [eng.joint_support(0), eng.joint_support(1)]
            try:
                outs = [seats[s].step(obs[s], supports[s], s == team) for s in (0, 1)]
            except (ValueError, AssertionError, RuntimeError) as exc:
                flag(f"a seat could not select: {exc}")
                break
            if not all(np.isfinite(o["logits"]).all() and math.isfinite(o["value"])
                       for o in outs):
                flag("a real seat's logit or value is not finite")
            if search:
                _, value, shadow = self.policy.forward_eval(
                    torch.from_numpy(obs[1 - a]).reshape(1, -1), shadow)
                if not bool(torch.isfinite(shadow).all() and torch.isfinite(value).all()):
                    flag("the opponent-view state is not finite")
            action = tuple(int(v) for v in outs[team]["tuple"])
            if team == a:
                support, _ = self.restrict_support(supports[a], self.masks[0], flags[a])
                cls = diag.decision_class({int(t) & 1023 for t in support}, flags[a], E.A)
                if cls in scope:
                    in_scope[cls] += 1
                    if len(support) >= 2:
                        searched[cls] += 1
                    if len(support) >= 2 and search:
                        tuples, _ = S.joint_probabilities(outs[a]["logits"], support,
                                                          plan["temperature"])
                        order = candidate_order(tuples, E.pack_tuple(*action), k)
                        candidates = [E.unpack_tuple(tuples[i]) for i in order]
                        batch = self.rollouts[a].evaluate(
                            eng, seats[a].state, shadow, candidates, n, seats[a].seed, step,
                            after_declare=(flags[a], flags[1 - a]))
                        count["rollouts"] += len(candidates) * n
                        count["rollout_steps"] += batch.engine_steps
                        count["cutoff_rollouts"] += batch.count(S.STOP_CUTOFF)
                        caps, errors = batch.count(S.STOP_CAP), batch.count(S.STOP_ERROR)
                        if errors:
                            count["error_rollouts"] += errors
                            flag(f"a rollout failed: {batch.errors[0][1]}")
                        if caps:
                            count["cap_rejected_rollouts"] += caps
                            count["cap_rejected_decisions"] += 1
                        deviate = False
                        if not caps and not errors:
                            try:
                                deviate, best, gain, _ = decide(batch.returns, delta)
                            except ValueError as exc:
                                flag(f"the deviation rule could not be applied: {exc}")
                        if deviate:
                            played = tuple(int(v) for v in candidates[best])
                            key = (f"{cls}: {diag.action_label(action, E)} -> "
                                   f"{diag.action_label(played, E)}")
                            deviation_types[key] = deviation_types.get(key, 0) + 1
                            deviations[cls] += 1
                            gains.append(round(gain, 6))
                            action = played
                            if hasattr(seats[a], "_after_declare"):
                                seats[a]._after_declare = action[0] == E.A["DECLARE"]
            trail.update(struct.pack("<Biii", team, *action))
            rc = eng.step(*action)
            step += 1
            hard = eng.counters()
            if any(hard[key] for key in T.HARD_COUNTERS):
                flag(f"hard counters { {key: hard[key] for key in T.HARD_COUNTERS if hard[key]} }")
            rewards = eng.last_rewards() if rc >= 0 else (0.0, 0.0)
            if not all(math.isfinite(r) for r in rewards):
                flag("a reward is not finite")
            elif max(abs(r) for r in rewards) > self.reward_limit:
                flag(f"a reward of {max(rewards, key=abs)} is beyond the clip threshold")
            if rc == E.STEP_TERMINAL:
                finished = True
                break
            if rc != E.STEP_OK:
                flag(f"the engine refused seat {team} tuple {action}: rc={rc}")
                break
        counters = eng.counters()
        integrity = {key: counters[key] for key in T.HARD_COUNTERS}
        if any(integrity.values()):
            flag(f"integrity counters {integrity}")
        fallbacks = sum(stats["fallback"] for seat in seats
                        for stats in getattr(seat, "mask_stats", {}).values())
        if fallbacks:
            flag(f"a mask gave way {fallbacks} time(s) in the real game")
        final = eng.final_match() if finished else None
        natural = bool(final is not None and final.status == E.STATUS_MATCH_OVER)
        cap = bool(final is not None and final.status == E.STATUS_DECISION
                   and not counters["error_episodes"])
        if final is not None and not natural and not cap:
            flag(f"the match ended in engine status {int(final.status)}")
        a_td = int(final.score[a]) if final is not None else None
        b_td = int(final.score[1 - a]) if final is not None else None
        sampling = hashlib.sha256()
        for seat in seats:
            sampling.update(seat.generator.get_state().numpy().tobytes())
            sampling.update(seat.state.numpy().tobytes())
        record = {
            "schema": SCHEMA, "shard": self.shard, "engine_seed": int(engine_seed), "leg": leg,
            "arm": arm, "settings": game_settings(plan, arm),
            "result_a": None if final is None else
            "W" if a_td > b_td else "D" if a_td == b_td else "L",
            "a_td": a_td, "b_td": b_td, "c_steps": step, "natural": natural,
            "decision_cap": cap, "invalid": invalid, "integrity": integrity,
            "integrity_checks": list(INTEGRITY_CHECKS),
            "team_ids": [int(final.team_id[0]), int(final.team_id[1])] if final is not None
            else None,
            "sampling_seeds": [seat.seed for seat in seats],
            "in_scope": in_scope, "searched": searched, "deviations": deviations,
            "deviation_types": deviation_types, "predicted_gains": gains, **count,
            "seconds": round(time.time() - started, 3),
            "action_trail_sha256": trail.hexdigest(),
            "final_state_sha256": hashlib.sha256(bytes(final)).hexdigest()
            if final is not None else None,
            "sampling_state_sha256": sampling.hexdigest(),
            "hashes": self.hashes, "runtime": self.runtime}
        eng.close()
        return record


_PLAYER = None


def _worker_init(plan, plan_sha256, shard, checkpoint, manifest, processes):
    global _PLAYER
    os.environ["OMP_NUM_THREADS"] = "1"
    _PLAYER = Player(plan, plan_sha256, shard, checkpoint, manifest, processes)


def _worker_play(task):
    return _PLAYER.play(*task)


# ---- records on disk --------------------------------------------------------------------------
def record_key(record):
    return (record["engine_seed"], record["leg"], record["arm"])


def load_records(path, repair=False):
    """The records of a games.jsonl. A last line cut short by a kill is not a
    record; with repair=True it is removed, so a rerun plays that game again.
    Whole records are never rewritten."""
    if not os.path.exists(path):
        return []
    with open(path) as f:
        lines = f.read().split("\n")
    records, good = [], []
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            records.append(json.loads(line))
            good.append(line)
        except ValueError:
            if any(rest.strip() for rest in lines[i + 1:]):
                raise ValueError(f"{path}: line {i + 1} is not a record")
            if repair:
                with open(path, "w") as f:
                    f.write("".join(g + "\n" for g in good))
    return records


def append_record(path, record):
    with open(path, "a") as f:
        f.write(json.dumps(record) + "\n")
        f.flush()
        os.fsync(f.fileno())


def cmd_play(args):
    plan, plan_sha = load_plan(args.plan, args.expect_sha256)
    if args.processes < 1:
        raise SystemExit("--processes must be at least 1")
    os.environ["OMP_NUM_THREADS"] = "1"
    wanted = shard_tasks(plan, args.shard)
    os.makedirs(args.out_dir, exist_ok=True)
    games_path = os.path.join(args.out_dir, "games.jsonl")
    request = {"schema": RUN_SCHEMA, "plan_sha256": plan_sha, "plan_name": plan["name"],
               "shard": args.shard}
    run_path = os.path.join(args.out_dir, "run.json")
    if os.path.exists(run_path):
        with open(run_path) as f:
            if json.load(f) != request:
                raise SystemExit(f"{run_path} belongs to another plan or shard; "
                                 "use a fresh --out-dir")
    else:
        with open(run_path, "w") as f:
            json.dump(request, f, indent=1)
    before = load_records(games_path, repair=True)
    stale = [record_key(r) for r in before
             if r["hashes"]["plan_sha256"] != plan_sha or record_key(r) not in set(wanted)]
    if stale:
        raise SystemExit(f"{games_path} holds {len(stale)} record(s) that are not this "
                         f"shard's under this plan, first {stale[0]}")
    done = {record_key(r) for r in before}
    todo = [task for task in wanted if task not in done]
    print(f"plan {plan['name']} ({plan_sha[:12]}), shard {args.shard}: {len(wanted)} games, "
          f"{len(wanted) - len(todo)} already played, {len(todo)} to play on "
          f"{args.processes} process(es)", flush=True)
    started = time.time()
    config = (plan, plan_sha, args.shard, args.checkpoint, args.manifest, args.processes)

    def finished(record, number):
        append_record(games_path, record)
        result = f"{record['result_a']} {record['a_td']}-{record['b_td']}"
        print(f"{number}/{len(todo)} seed {record['engine_seed']} {record['leg']} "
              f"{record['arm']}: {result}, {sum(record['deviations'].values())} deviations, "
              f"{record['seconds']:.0f} s"
              + (", INVALID" if record["invalid"] else "")
              + f", elapsed {time.time() - started:.0f} s", flush=True)

    _worker_init(*config)                     # checks checkpoint, manifest and code first
    if args.processes == 1:
        for number, task in enumerate(todo, start=1):
            finished(_worker_play(task), number)
    else:
        import multiprocessing
        from concurrent.futures import ProcessPoolExecutor, as_completed
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(max_workers=args.processes, mp_context=context,
                                 initializer=_worker_init, initargs=config) as pool:
            futures = [pool.submit(_worker_play, task) for task in todo]
            for number, future in enumerate(as_completed(futures), start=1):
                finished(future.result(), number)
    records = load_records(games_path)
    if sorted(record_key(r) for r in records) != sorted(wanted):
        raise SystemExit("games.jsonl does not hold exactly the shard's games")
    with open(os.path.join(args.out_dir, "COMPLETE.json"), "w") as f:
        json.dump({"schema": RUN_SCHEMA, "plan_sha256": plan_sha, "shard": args.shard,
                   "games": len(records),
                   "wall_seconds_this_invocation": round(time.time() - started, 1),
                   "processes": args.processes}, f, indent=1)
    print(f"complete: {len(records)} games in {args.out_dir}", flush=True)
    return 0


# ---- acceptance -------------------------------------------------------------------------------
WITHIN_SHARD = ("library_sha256", "abi", "obs_version", "obs_size", "torch", "numpy", "python",
                "precision", "torch_threads", "machine")
IDENTITY_FIELDS = ("action_trail_sha256", "final_state_sha256", "sampling_state_sha256")


def accept(plan, plan_sha256, records, allow_test_policy=False):
    """The reasons these records are not an acceptable run of the plan; none = accepted."""
    problems = []
    expected = plan_tasks(plan)
    keys = [record_key(r) for r in records]
    seen = {}
    for key in keys:
        seen[key] = seen.get(key, 0) + 1
    missing = [k for k in expected if k not in seen]
    extra = sorted(set(keys) - set(expected))
    repeated = sorted(k for k, c in seen.items() if c > 1)
    if missing:
        problems.append(f"{len(missing)} planned game(s) missing, first {missing[0]}")
    if extra:
        problems.append(f"{len(extra)} game(s) the plan does not hold, first {extra[0]}")
    if repeated:
        problems.append(f"{len(repeated)} game(s) present more than once, first {repeated[0]}")
    arms = plan_arms(plan)
    for record in records:
        key = record_key(record)
        if record.get("schema") != SCHEMA:
            problems.append(f"{key}: not a {SCHEMA} record")
            continue
        for name, want in (("plan_sha256", plan_sha256),
                           ("checkpoint_sha256", plan["checkpoint_sha256"]),
                           ("reward_manifest_sha256", plan["reward_manifest_sha256"]),
                           ("source_commit", plan["source_commit"]),
                           ("code_sha256", plan["code_sha256"])):
            if record["hashes"].get(name) != want:
                problems.append(f"{key}: {name} is {record['hashes'].get(name)}, "
                                f"the plan says {want}")
        if record["arm"] in arms and record["settings"] != game_settings(plan, record["arm"]):
            problems.append(f"{key}: its settings are not the plan's")
        if record.get("integrity_checks") != list(INTEGRITY_CHECKS):
            problems.append(f"{key}: integrity_checks is not this tool's list")
        if record["shard"] != shard_of(plan, record["engine_seed"]):
            problems.append(f"{key}: played by shard {record['shard']}, the plan gives that "
                            f"seed to {shard_of(plan, record['engine_seed'])}")
    problems = _first_of_each(problems)
    if not allow_test_policy and str(plan["checkpoint_sha256"]).startswith(TEST_POLICY):
        problems.append("the plan names a test policy, not a checkpoint")
    for arm in arms:
        games = [r for r in records if r["arm"] == arm]
        bad = [r for r in games if r["invalid"]]
        if bad:
            problems.append(f"arm {arm} is UNREAD: {len(bad)} invalid game(s), first "
                            f"{record_key(bad[0])}: {bad[0]['invalid'][0]}")
        capped = [r for r in games if not r["natural"] and not r["invalid"]]
        if capped:
            problems.append(f"arm {arm}: {len(capped)} game(s) did not end naturally "
                            f"(decision cap), first {record_key(capped[0])}; no comparison")
        searched = sum(sum(r["searched"].values()) for r in games)
        rejected = sum(r["cap_rejected_decisions"] for r in games)
        if arms[arm] is not None and searched and \
                rejected / searched > plan["cap_rejection_ceiling"]:
            problems.append(f"arm {arm}: {rejected} of {searched} searched decisions had a cap "
                            f"rejection, above the ceiling {plan['cap_rejection_ceiling']}")
    for shard in plan["shards"]:
        games = [r for r in records if r["shard"] == shard["name"]]
        for name in WITHIN_SHARD:
            values = sorted({str(r["runtime"].get(name)) for r in games})
            if len(values) > 1:
                problems.append(f"shard {shard['name']}: {name} differs between its records: "
                                f"{values}")
        if any(r["runtime"].get("torch_threads") != 1 for r in games):
            problems.append(f"shard {shard['name']}: a game ran with more than one torch thread")
    libraries = sorted({str(r["runtime"].get("library_sha256")) for r in records})
    if len(libraries) > 1:
        problems.append(f"library_sha256 differs across shards: {libraries}")
    for arm in plan["arms"]:
        games = [r for r in records if r["arm"] == arm["name"]]
        if games and not any(r["result_a"] in ("W", "L") for r in games):
            problems.append(f"arm {arm['name']}: no decisive game, so its decisive Elo is "
                            "undefined")
    plain = {(r["engine_seed"], r["leg"]): r for r in records if r["arm"] == plain_arm(plan)}
    identity = [r for r in records if r["arm"] == plan["identity"]["arm"]]
    differ = [record_key(r) for r in identity
              if (r["engine_seed"], r["leg"]) in plain
              and any(r[f] != plain[(r["engine_seed"], r["leg"])][f] for f in IDENTITY_FIELDS)]
    if differ:
        problems.append(f"identity failed: {len(differ)} of {len(identity)} identity game(s) "
                        f"differ from the plain game, first {differ[0]}")
    idle = [record_key(r) for r in identity if sum(r["searched"].values()) and not r["rollouts"]]
    if idle:
        problems.append(f"identity game(s) that ran no search, first {idle[0]}")
    return problems


def _first_of_each(problems, limit=3):
    """Per-record problems repeat; keep the first few of each kind and a count."""
    kinds, out = {}, []
    for text in problems:
        kind = text.split(": ", 1)[-1].split(" is ")[0][:40]
        kinds[kind] = kinds.get(kind, 0) + 1
        if kinds[kind] <= limit:
            out.append(text)
    out += [f"... and {count - limit} more like: {kind}" for kind, count in kinds.items()
            if count > limit]
    return out


# ---- statistics (numpy and tournament_stats only) -----------------------------------------------
def summarize(plan, records):
    """Every number of the report, from accepted records."""
    from play_harness import tournament_stats as TS
    reps, rng_seed = plan["bootstrap"]["reps"], plan["bootstrap"]["seed"]
    arms = [arm["name"] for arm in plan["arms"]]
    plain = plain_arm(plan)
    seeds = sorted({r["engine_seed"] for r in records})
    row = {s: i for i, s in enumerate(seeds)}
    # One table, one row per engine seed, so one draw of seeds resamples every
    # arm and both orientations together. Columns per arm: W, D, L, the sum of
    # TD differences, games; per search arm also the sums of its paired
    # differences from the plain arm and the number of pairs.
    col = {}
    for arm in arms:
        for name in ("W", "D", "L", "td", "n", "d_score", "d_td", "pairs"):
            col[(arm, name)] = len(col)
    table = np.zeros((len(seeds), len(col)))
    by_key = {record_key(r): r for r in records}
    for r in records:
        if r["arm"] not in arms:
            continue
        i = row[r["engine_seed"]]
        table[i, col[(r["arm"], r["result_a"])]] += 1
        table[i, col[(r["arm"], "td")]] += r["a_td"] - r["b_td"]
        table[i, col[(r["arm"], "n")]] += 1
        base = by_key.get((r["engine_seed"], r["leg"], plain))
        if r["arm"] != plain and base is not None:
            table[i, col[(r["arm"], "d_score")]] += SCORE[r["result_a"]] - SCORE[base["result_a"]]
            table[i, col[(r["arm"], "d_td")]] += (r["a_td"] - r["b_td"]) \
                - (base["a_td"] - base["b_td"])
            table[i, col[(r["arm"], "pairs")]] += 1
    boots = TS.bootstrap_cluster_counts(table, reps, rng_seed)       # (reps, columns)
    total = table.sum(axis=0)

    def stat(values, point):
        return [float(point)] + TS._ci(values)

    def of(data, arm):
        g = lambda name: data[..., col[(arm, name)]]                   # noqa: E731
        with np.errstate(invalid="ignore", divide="ignore"):
            share = g("W") / (g("W") + g("L"))
            return {"score": (g("W") + 0.5 * g("D")) / g("n"), "share": share,
                    "elo": np.where(np.isfinite(share), TS.elo_from_share(share), np.nan),
                    "td": g("td") / g("n"), "d_score": g("d_score") / g("pairs"),
                    "d_td": g("d_td") / g("pairs")}

    out = {"seeds": len(seeds), "reps": reps, "arms": {}, "contrasts": {}, "identity": None}
    plain_seconds = float(np.mean([r["seconds"] for r in records if r["arm"] == plain]))
    points, draws = {a: of(total, a) for a in arms}, {a: of(boots, a) for a in arms}
    for arm in arms:
        games = [r for r in records if r["arm"] == arm]
        n = len(games)
        searched = sum(sum(g["searched"].values()) for g in games)
        types = {}
        for g in games:
            for key, c in g["deviation_types"].items():
                types[key] = types.get(key, 0) + c
        gains = [x for g in games for x in g["predicted_gains"]]
        p, d = points[arm], draws[arm]
        out["arms"][arm] = {
            "games": n, "W": int(total[col[(arm, "W")]]), "D": int(total[col[(arm, "D")]]),
            "L": int(total[col[(arm, "L")]]),
            "win_score": stat(d["score"], p["score"]),
            "decisive_share": stat(d["share"], p["share"]),
            "elo_decisive": stat(d["elo"], p["elo"]),
            "replicates_without_a_decisive_game": int((~np.isfinite(d["share"])).sum()),
            "td_diff": stat(d["td"], p["td"]),
            "a_td": sum(g["a_td"] for g in games) / n, "b_td": sum(g["b_td"] for g in games) / n,
            "searched_per_game": {c: sum(g["searched"][c] for g in games) / n
                                  for c in plan["search"]["scope"]},
            "deviations_per_game": {c: sum(g["deviations"][c] for g in games) / n
                                    for c in plan["search"]["scope"]},
            "deviation_types": dict(sorted(types.items(), key=lambda kv: -kv[1])),
            "mean_predicted_gain": float(np.mean(gains)) if gains else None,
            "rollouts_per_game": sum(g["rollouts"] for g in games) / n,
            "rollout_steps_per_game": sum(g["rollout_steps"] for g in games) / n,
            "cap_rejected_decisions": sum(g["cap_rejected_decisions"] for g in games),
            "cap_rejection_share": (sum(g["cap_rejected_decisions"] for g in games) / searched)
            if searched else 0.0,
            "cutoff_rollouts": sum(g["cutoff_rollouts"] for g in games),
            "cutoff_share": (sum(g["cutoff_rollouts"] for g in games)
                             / max(sum(g["rollouts"] for g in games), 1)),
            "seconds_per_game": float(np.mean([g["seconds"] for g in games])),
            "slowdown": float(np.mean([g["seconds"] for g in games]) / plain_seconds),
            "steps_per_game": sum(g["c_steps"] for g in games) / n}
        if arm != plain:
            both = [(g, by_key[(g["engine_seed"], g["leg"], plain)]) for g in games]
            out["contrasts"][arm] = {
                "pairs": int(total[col[(arm, "pairs")]]),
                "win_score": stat(d["d_score"], p["d_score"]),
                "td_diff": stat(d["d_td"], p["d_td"]),
                # Both Elo estimates are recomputed in each replicate, then subtracted.
                "elo_decisive": stat(d["elo"] - draws[plain]["elo"], p["elo"] - points[plain]["elo"]),
                "same_result": float(np.mean([g["result_a"] == b["result_a"] for g, b in both])),
                "same_game": float(np.mean([g["action_trail_sha256"] == b["action_trail_sha256"]
                                            for g, b in both]))}
    identity = [r for r in records if r["arm"] == plan["identity"]["arm"]]
    out["identity"] = {
        "games": len(identity), "rollouts": sum(r["rollouts"] for r in identity),
        "seconds_per_game": float(np.mean([r["seconds"] for r in identity])),
        "slowdown": float(np.mean([r["seconds"] for r in identity]) / plain_seconds),
        "rollout_steps_per_game": sum(r["rollout_steps"] for r in identity) / len(identity),
        "searched_per_game": sum(sum(r["searched"].values()) for r in identity) / len(identity),
        "shards": sorted({r["shard"] for r in identity})}
    out["hosts"] = {shard["name"]: sorted({r["runtime"]["hostname"] for r in records
                                           if r["shard"] == shard["name"]})
                    for shard in plan["shards"]}
    out["libraries"] = {shard["name"]: sorted({r["runtime"]["library_sha256"] for r in records
                                               if r["shard"] == shard["name"]})
                        for shard in plan["shards"]}
    return out


def _triple(stat, digits=3):
    point, lo, hi = stat
    return f"{point:+.{digits}f} [{lo:+.{digits}f}, {hi:+.{digits}f}]"


def format_report(plan, plan_sha256, summary):
    boot = plan["bootstrap"]
    lines = [f"plan {plan['name']} ({plan_sha256}): {summary['seeds']} engine seeds, both "
             "orientations, seat A against the same checkpoint (seat B, plain)",
             f"intervals: percentile bootstrap at 2.5 and 97.5 over engine seeds, "
             f"{boot['reps']} replicates, generator seed {boot['seed']}; both orientations of a "
             "seed and all arms are resampled together", "",
             f"{'arm':<10} games  W/D/L         win score              decisive share         "
             "decisive Elo               TD difference per game"]
    for arm, cell in summary["arms"].items():
        wdl = f"{cell['W']}/{cell['D']}/{cell['L']}"
        score, share = cell["win_score"], cell["decisive_share"]
        lines.append(
            f"{arm:<10} {cell['games']:>5}  {wdl:<12}  "
            f"{score[0]:.3f} [{score[1]:.3f}, {score[2]:.3f}]   "
            f"{share[0]:.3f} [{share[1]:.3f}, {share[2]:.3f}]   "
            f"{_triple(cell['elo_decisive'], 0):<25}  {_triple(cell['td_diff'])}")
    empty = {arm: cell["replicates_without_a_decisive_game"]
             for arm, cell in summary["arms"].items()
             if cell["replicates_without_a_decisive_game"]}
    lines.append("replicates left out of decisive share and Elo for having no decisive game: "
                 + (", ".join(f"{a} {c}" for a, c in empty.items()) if empty else "none"))
    lines += ["", "Each search arm minus the plain arm (same seeds, both estimates recomputed "
              "in every replicate)",
              f"{'arm':<10} pairs  decisive Elo               win score                  "
              "TD difference              same result  same game"]
    for arm, cell in summary["contrasts"].items():
        lines.append(f"{arm:<10} {cell['pairs']:>5}  {_triple(cell['elo_decisive'], 0):<25}  "
                     f"{_triple(cell['win_score']):<25}  {_triple(cell['td_diff']):<25}  "
                     f"{cell['same_result'] * 100:>10.1f}%  {cell['same_game'] * 100:>8.1f}%")
    scope = plan["search"]["scope"]
    lines += ["", "What the search did, per game",
              f"{'arm':<10} searched {'/'.join(scope):<22} deviations {'/'.join(scope):<20} "
              "mean predicted gain  rollout steps  cap-rejected decisions  cutoff rollouts  "
              "seconds  slowdown"]
    for arm, cell in summary["arms"].items():
        s = " / ".join(f"{cell['searched_per_game'][c]:.1f}" for c in scope)
        d = " / ".join(f"{cell['deviations_per_game'][c]:.2f}" for c in scope)
        gain = "-" if cell["mean_predicted_gain"] is None else f"{cell['mean_predicted_gain']:.3f}"
        lines.append(
            f"{arm:<10} {s:<31} {d:<31} {gain:>19}  {cell['rollout_steps_per_game']:>13.0f}  "
            f"{cell['cap_rejected_decisions']:>6} ({cell['cap_rejection_share'] * 100:.2f}%)"
            f"{'':<8} {cell['cutoff_rollouts']:>6} ({cell['cutoff_share'] * 100:.2f}%)  "
            f"{cell['seconds_per_game']:>7.1f}  {cell['slowdown']:>7.1f}x")
    for arm, cell in summary["arms"].items():
        if cell["deviation_types"]:
            lines += ["", f"deviations of {arm}: " + "; ".join(
                f"{key} x{count}" for key, count in list(cell["deviation_types"].items())[:12])]
    ident = summary["identity"]
    lines += ["", f"identity: {ident['games']} game(s) of arm {plan['identity']['arm']} on "
              f"shard(s) {', '.join(ident['shards'])} equal the plain game on action trail, "
              f"final state and sampling state, with {ident['rollouts']} rollouts run and "
              f"discarded ({ident['searched_per_game']:.0f} searched decisions, "
              f"{ident['rollout_steps_per_game']:.0f} rollout steps and "
              f"{ident['seconds_per_game']:.1f} s per game, {ident['slowdown']:.1f}x plain)",
              "", "shard        games' hosts (more than one: the shard was relaunched)   "
              "native library sha256"]
    for name, hosts in summary["hosts"].items():
        lines.append(f"{name:<12} {len(hosts)}: {', '.join(hosts):<52} "
                     f"{', '.join(summary['libraries'][name])}")
    lines.append("ACCEPTANCE: PASS")
    return "\n".join(lines)


def cmd_report(args):
    plan, plan_sha = load_plan(args.plan, args.expect_sha256)
    records, sources = [], []
    for folder in args.run_dir:
        path = os.path.join(folder, "games.jsonl")
        records += load_records(path)
        with open(os.path.join(folder, "run.json")) as f:
            run = json.load(f)
        if run.get("plan_sha256") != plan_sha:
            raise SystemExit(f"{folder} was played under plan {run.get('plan_sha256')}")
        sources.append((f"{run['shard']}/games.jsonl", path))
    problems = accept(plan, plan_sha, records, allow_test_policy=args.allow_test_policy)
    if len({label for label, _ in sources}) != len(sources):
        problems.append("two directories hold the same shard")
    if problems:
        # No outcome statistic is shown for a run that is not accepted.
        text = "\n".join(["ACCEPTANCE: FAIL"] + ["  - " + p for p in problems])
        print(text)
        if args.out_dir:
            os.makedirs(args.out_dir, exist_ok=True)
            with open(os.path.join(args.out_dir, "acceptance_failed.txt"), "w") as f:
                f.write(text + "\n")
        return 2
    summary = summarize(plan, records)
    report = format_report(plan, plan_sha, summary)
    print(report)
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        with open(os.path.join(args.out_dir, "report.txt"), "w") as f:
            f.write(report + "\n")
        with open(os.path.join(args.out_dir, "report.json"), "w") as f:
            json.dump({"plan_sha256": plan_sha, "summary": summary}, f, indent=1)
        sums = [(label, path) for label, path in sources] + [
            (name, os.path.join(args.out_dir, name)) for name in ("report.txt", "report.json")]
        sums.append(("plan.json", args.plan))
        with open(os.path.join(args.out_dir, "SHA256SUMS"), "w") as f:
            for label, path in sums:
                with open(path, "rb") as src:
                    f.write(f"{hashlib.sha256(src.read()).hexdigest()}  {label}\n")
    return 0


def cmd_hashes(args):
    from play_harness import tournament as T
    out = {"source_commit": T._git_head(), "code_sha256": code_sha256()}
    if args.checkpoint:
        with open(args.checkpoint, "rb") as f:
            out["checkpoint_sha256"] = hashlib.sha256(f.read()).hexdigest()
    if args.manifest:
        from play_harness import engine as E
        out["reward_manifest_sha256"] = E.load_reward_manifest(args.manifest)["sha256"]
    if args.plan:
        with open(args.plan, "rb") as f:
            raw = f.read()
        out["plan_sha256"] = hashlib.sha256(raw).hexdigest()
        try:
            validate_plan(json.loads(raw))
            out["plan"] = "valid"
        except ValueError as exc:
            out["plan"] = str(exc)
    print(json.dumps(out, indent=1))
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("play", help="play one shard of the plan: all its arms")
    p.add_argument("--plan", required=True)
    p.add_argument("--expect-sha256", required=True, help="the plan file's sha256")
    p.add_argument("--shard", required=True)
    p.add_argument("--checkpoint", required=True, help="the blob the plan names by hash")
    p.add_argument("--manifest", default=DEFAULT_MANIFEST)
    p.add_argument("--processes", type=int, default=1)
    p.add_argument("--out-dir", required=True)
    p.set_defaults(run=cmd_play)
    r = sub.add_parser("report", help="acceptance, then statistics, over every shard")
    r.add_argument("run_dir", nargs="+", help="one output directory per shard")
    r.add_argument("--plan", required=True)
    r.add_argument("--expect-sha256", required=True)
    r.add_argument("--out-dir", default=None, help="write report.txt, report.json, SHA256SUMS")
    r.add_argument("--allow-test-policy", action="store_true", help=argparse.SUPPRESS)
    r.set_defaults(run=cmd_report)
    h = sub.add_parser("hashes", help="the hashes a plan must carry")
    h.add_argument("--checkpoint", default=None)
    h.add_argument("--manifest", default=None)
    h.add_argument("--plan", default=None)
    h.set_defaults(run=cmd_hashes)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
