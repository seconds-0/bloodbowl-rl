#!/usr/bin/env python3
"""END_TURN probe: how one checkpoint's own critic and its shaped reward price
ending the team turn against activating one more player.

One checkpoint plays plain self-play games (no mask, T=1, kick-off starts, the
training reward manifest). At seat A's decisions of three classes it keeps a
root (a search clone, both recurrent states, the logits, the action played):

  end_turn       plain play chose END_TURN while an ACTIVATE was legal
  decline_block  plain play chose END_ACTIVATION while a BLOCK_TARGET was legal
  activate       plain play chose an ACTIVATE while END_TURN was legal

A decision made inside the engine's kick-off procedure (the kicking team's free
turn from a Blitz kick-off result) is not a root of any class: ending that turn
does not advance the completed-turn counter the rollout core stops on. Each
game's record counts the decisions left out for this reason, per class.

After the game every kept root is evaluated by rollouts of the harness's own
rollout core (play_harness.search.Rollouts) with common random numbers:

  turn arm    the action played and up to three alternatives of the other type,
              each rolled to the ACTUAL end of the searcher's team turn (or to
              the end of the match if that comes first) and scored by shaped
              reward plus the checkpoint's own value output there. The
              harness's 200-step search cut-off is not used: the step limit is
              MATCH_MAX_STEPS, which no team turn can reach, and a rollout that
              stops on it is an integrity error. (The reward part of a return
              is not stored: it is the return minus gamma^steps times the
              bootstrap.)
  forced arm  end_turn roots only: the same alternatives, but at the searcher's
              next decision that offers END_TURN and an ACTIVATE the turn is
              ended. This is "exactly one more activation".
  match arm   a sample of end_turn roots: the action played and the most
              probable ACTIVATE, each played to the end of the match. Per
              rollout: the realised discounted shaped return at three discount
              factors, the return to the first three own turn ends with the
              critic's bootstrap there, the final score, and the 28 reward
              components summed to each of those horizons.

Integrity is fail-fast (INTEGRITY_CHECKS below). Any failure stops the worker
with a non-zero exit, the run writes FAILED.json and no COMPLETE.json, and the
shard is not accepted. The one permitted loss is a rollout that ends on the
decision cap its clone inherited from the real game (the rollout core's "cap"
stop): it has no return, its rollout index is dropped for every candidate of
that root and arm, and it is counted.

The harness is used from an export of a pinned commit and is not modified.
Two things are hooked at run time, inside this process only:
  - Engine.last_rewards also reads the step's reward components (through
    endturn_shim.c's accessor) while the match arm runs;
  - search.select_joint restricts the searcher's support to END_TURN at the
    one decision the forced arm describes.
On the first root of every class in every game whose recorded turn arm lost no
rollout to the decision cap, the turn arm is computed three ways and must agree
exactly, with every value finite: by Rollouts.evaluate with both hooks removed,
by Rollouts.evaluate with both installed and idle (the record), and for
end_turn roots by this tool's own entry into Rollouts._play with both idle.

What a root's record keeps per rollout, so that the analysis can apply one
valid-index mask to every number it reports: the returns, the bootstraps, the
step counts, and what the searcher did after the root action (ACTIVATEs, a
block or not, STEPs); for the forced arm also whether the rule ended the turn.

  endturn_probe.py run --harness EXPORT --lib LIB --plan PLAN.json \\
      --expect-sha256 H --checkpoint-name chain55 --checkpoint BLOB \\
      --out-dir DIR --processes 8
"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import math
import os
import random
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SCHEMA_ROOT = "endturn-probe-root-v3"
SCHEMA_GAME = "endturn-probe-game-v2"
SCHEMA_COMPLETE = "endturn-probe-complete-v3"
CLASSES = ("end_turn", "decline_block", "activate")
GAMMAS = (0.999, 0.9995, 1.0)          # the training discount first
DEPTHS = 3                             # own turn ends followed in the match arm
# The step limit of every rollout. A real game allows 4,096 decisions and a clone
# inherits that budget part-spent, so no rollout can take this many engine steps:
# it ends on a turn end, on the match end or on the inherited decision cap first.
MATCH_MAX_STEPS = 8192
RESIDUAL_TOLERANCE = 1e-5              # |reward - sum of components| on a non-final step
TOOL_FILES = ("endturn_probe.py", "endturn_shim.c", "build_shim.sh")
SETTING_KEYS = ("seed0", "games", "rollouts", "cap_end_turn", "cap_decline_block",
                "cap_activate", "match_roots", "match_rollouts", "alternatives")
# Every integrity check a game of this probe runs. Any failure is fatal to the shard.
INTEGRITY_CHECKS = (
    "real game: the engine's return code on every step",
    "real game: hard counters after every step and at the end (illegal, "
    "projection_collision, error_episodes, rejected_submissions, precheck_collisions)",
    "real game: both seats' logits and values finite on every step",
    "real game: the opponent-view state and value finite on every step",
    "real game: both seats' emitted rewards finite and within the env's clip threshold "
    "on every step",
    "real game: the game ends in a natural match end (STATUS_MATCH_OVER), not on the "
    "decision cap",
    "rollouts: the engine's return code and status on every step",
    "rollouts: the same hard counters of every clone at its rollout's end",
    "rollouts: both seats' emitted rewards finite and within the env's clip threshold "
    "on every step",
    "rollouts: logits and values finite on every forward",
    "rollouts: the accumulated return finite",
    "rollouts: an action selectable at every decision",
    "rollouts: no rollout fails and none stops on the step limit; a turn-arm or "
    "forced-arm rollout stops on a turn end, the match end or the decision cap, a "
    "match-arm rollout on the match end or the decision cap",
    "components: on every step before a rollout's last, the 28 components sum to the "
    "step's reward within 1e-5; over a rollout, components and the final step's reward "
    "sum to the rollout core's reward total within 1e-4",
    "hooks: on the first root of each class in each game whose recorded turn arm has no "
    "capped rollout, the turn arm computed with the hooks removed, installed and idle, "
    "and (end_turn) through the tool's own entry agree exactly, every value finite; "
    "the two extra computations pass the rollout checks themselves",
    "forced arm: the turn is ended by the rule at most once in a rollout",
)


class IntegrityError(RuntimeError):
    """A failed integrity check. It ends the worker and with it the shard."""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def tool_sha256():
    return {name: sha256_file(os.path.join(HERE, name)) for name in TOOL_FILES}


def rnd(x, digits=7):
    return np.round(np.asarray(x, dtype=np.float64), digits).tolist()


# ---- the harness, loaded once per process ----------------------------------------------
class Probe:
    def __init__(self, harness, lib_path, checkpoint, manifest):
        os.environ["BBPLAY_LIB"] = os.path.abspath(lib_path)
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        harness = os.path.abspath(harness)
        if harness not in sys.path:
            sys.path.insert(0, harness)
        import torch
        torch.set_num_threads(1)
        from play_harness import engine as E
        from play_harness import search as S
        from play_harness import tournament as T
        from play_harness.policy import PolicySeat, load_checkpoint
        self.torch, self.E, self.S, self.T = torch, E, S, T
        if os.path.abspath(E.ROOT) != harness:
            raise SystemExit(f"play_harness was imported from {E.ROOT}, not from {harness}")
        before = os.path.getmtime(os.environ["BBPLAY_LIB"])
        self.lib = E.load_library()
        if os.path.getmtime(os.environ["BBPLAY_LIB"]) != before or \
                not hasattr(self.lib, "bbp_probe_reward_clip_threshold"):
            raise SystemExit("the engine library is not the probe's build (or the harness "
                             "rebuilt it as stale); run build_shim.sh after the export")
        self.n_comp = int(self.lib.bbp_probe_component_count())
        self.lib.bbp_probe_component_name.restype = ctypes.c_char_p
        self.lib.bbp_probe_component_name.argtypes = [ctypes.c_int]
        self.lib.bbp_probe_step_components.argtypes = [
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_float), ctypes.c_int]
        self.lib.bbp_probe_step_components.restype = ctypes.c_int
        self.lib.bbp_probe_reward_clip_threshold.argtypes = [ctypes.c_void_p]
        self.lib.bbp_probe_reward_clip_threshold.restype = ctypes.c_float
        self.components = [self.lib.bbp_probe_component_name(i).decode()
                           for i in range(self.n_comp)]
        self.channels = self.components + ["terminal_or_residual"]
        self.policy, self.provenance = load_checkpoint(checkpoint)
        self.manifest = E.load_reward_manifest(manifest)
        self.library_sha256 = sha256_file(os.environ["BBPLAY_LIB"])
        # The env's own design envelope for one step's reward under this manifest
        # (bbe_reward_clip_threshold), with the margin tools/search_ab.py gives it.
        scratch = E.Engine(0, rewards=self.manifest["rewards"])
        threshold = float(self.lib.bbp_probe_reward_clip_threshold(scratch._ptr))
        scratch.close()
        if not (math.isfinite(threshold) and threshold > 0):
            raise SystemExit(f"the env's reward clip threshold is {threshold}")
        self.reward_threshold = threshold
        self.reward_limit = threshold * (1.0 + 1e-6)

        class PlainSeat(PolicySeat):
            """Plain play that also remembers whether its last decision was a DECLARE."""
            _after_declare = False

            def reset_match(self):
                super().reset_match()
                self._after_declare = False

            def decide(self, logits, support, deciding):
                action, logprob = super().decide(logits, support, deciding)
                if deciding:
                    self._after_declare = action[0] == E.A["DECLARE"]
                return action, logprob
        self.PlainSeat = PlainSeat
        self._install_hooks()

    # ---- the two run-time hooks ------------------------------------------------------
    def _install_hooks(self):
        E, S, probe = self.E, self.S, self
        self.capture_on, self.capture_seat, self.capture_rows = False, 0, {}
        self.force_on, self.force_generators, self.force_applied = False, set(), {}
        n = self.n_comp
        buf = (ctypes.c_float * (2 * n))()
        original_last = E.Engine.last_rewards

        def last_rewards(engine):
            rewards = original_last(engine)
            if probe.capture_on and engine.is_clone:
                got = probe.lib.bbp_probe_step_components(engine._ptr, buf, 2 * n)
                if got != n:
                    raise RuntimeError("bbp_probe_step_components refused")
                seat = probe.capture_seat
                row = np.empty(n + 1, dtype=np.float64)
                row[:n] = buf[seat * n:(seat + 1) * n]
                row[n] = rewards[seat]
                probe.capture_rows.setdefault(id(engine), []).append(row)
            return rewards

        original_select = S.select_joint
        end_turn, activate = E.A["END_TURN"], E.A["ACTIVATE"]

        def select_joint(logits, support, mode="sample", generator=None, temperature=1.0):
            if probe.force_on and id(generator) in probe.force_generators:
                packed = np.asarray(support, dtype=np.int64).reshape(-1)
                types = packed & 1023
                if (types == end_turn).any() and (types == activate).any():
                    support = packed[types == end_turn]
                    key = id(generator)
                    probe.force_applied[key] = probe.force_applied.get(key, 0) + 1
            return original_select(logits, support, mode, generator, temperature=temperature)

        self._originals = (original_last, original_select)
        self._hooks = (last_rewards, select_joint)
        E.Engine.last_rewards, S.select_joint = self._hooks

    @contextlib.contextmanager
    def unhooked(self):
        """The harness exactly as imported: both hooks taken out for the block."""
        E, S = self.E, self.S
        E.Engine.last_rewards, S.select_joint = self._originals
        try:
            yield
        finally:
            E.Engine.last_rewards, S.select_joint = self._hooks

    def evaluate(self, rollouts, root, candidates, n, seed, forced=False, capture=False,
                 record=False):
        """Rollouts.evaluate's own body, with the hooks switched as asked. With both
        off it is the same computation as rollouts.evaluate (checked per game).
        Returns (batch, clones, searcher generators) in rollout order."""
        S, torch = self.S, self.torch
        k, n = len(candidates), int(n)
        while len(rollouts._pool) < k * n:
            rollouts._pool.append(root["clone"].clone_for_search(0, S.SEARCH_DICE_STREAM))
        seeds = [[S.rollout_seed(seed, root["step"], j, purpose) for j in range(n)]
                 for purpose in S.SEED_PURPOSES]
        clones = [rollouts._pool[c * n + j].copy_from(root["clone"], seeds[0][j],
                                                      S.SEARCH_DICE_STREAM)
                  for c in range(k) for j in range(n)]
        generators = [(torch.Generator().manual_seed(seeds[1][j]),
                       torch.Generator().manual_seed(seeds[2][j]))
                      for _ in range(k) for j in range(n)]
        firsts = [tuple(action) for action in candidates for _ in range(n)]
        self.capture_rows = {}
        self.capture_seat = rollouts.seat
        self.force_generators = {id(pair[0]) for pair in generators}
        self.force_applied = {}
        self.capture_on, self.force_on = bool(capture), bool(forced)
        try:
            out = rollouts._play(root["clone"], root["own"], root["opp"], firsts, clones,
                                 generators, root["flags"], record)
        finally:
            self.capture_on = self.force_on = False
        for name in ("returns", "rewards", "bootstraps", "steps", "touchdowns"):
            setattr(out, name, getattr(out, name).reshape(k, n))
        out.scores = out.scores.reshape(k, n, 2)
        return out, clones, [pair[0] for pair in generators]


# ---- one real game ------------------------------------------------------------------------
def in_kickoff_turn(E, match):
    """True while the engine is inside its kick-off procedure. A decision there that
    offers END_TURN and an ACTIVATE is the kicking team's free turn from a Blitz
    kick-off result. Ending that turn does not advance the engine's completed-turn
    counter, which is how the rollout core finds the end of the searcher's team turn,
    so a rollout from such a decision runs on to the end of the team's next real turn.
    No horizon this probe names applies there: such a decision is not a root."""
    kickoff = E.PROCS.index("KICKOFF")
    return any(match.stack[i].proc == kickoff for i in range(int(match.stack_top)))


def classify(E, a0, types):
    if a0[0] == E.A["END_TURN"] and E.A["ACTIVATE"] in types:
        return "end_turn"
    if a0[0] == E.A["END_ACTIVATION"] and E.A["BLOCK_TARGET"] in types:
        return "decline_block"
    if a0[0] == E.A["ACTIVATE"] and E.A["END_TURN"] in types:
        return "activate"
    return None


def play_game(p, engine_seed, a, caps):
    """One plain self-play game with seat A on side `a`, under the real-game
    integrity checks. Roots are a uniform sample without replacement of each
    class's decisions (a reservoir of the class's cap; every decision is kept
    while the class is under its cap)."""
    E, S, T, torch = p.E, p.S, p.T, p.torch
    seeds = [T.sampling_seed(engine_seed, side) for side in (0, 1)]
    seeds[1 - a] = (seeds[1 - a] + T.SEED_OFFSET_STRIDE) % (1 << 62)
    seats = [p.PlainSeat(p.policy, side, seed=seeds[side]) for side in (0, 1)]
    for seat in seats:
        seat.reset_match()
    eng = E.Engine(engine_seed, rewards=p.manifest["rewards"])
    shadow = p.policy.initial_state(1)
    pick = {c: random.Random(engine_seed * 31 + i) for i, c in enumerate(CLASSES)}
    kept = {c: [] for c in CLASSES}
    seen = {c: 0 for c in CLASSES}
    counts = {"activate": 0, "end_turn": 0, "turn_level": 0, "own_decisions": 0}
    kickoff_turn = {c: 0 for c in CLASSES}       # decisions of a class left out: a Blitz turn
    step = 0

    def bad(what):
        raise IntegrityError(f"real game, engine seed {engine_seed}, step {step}: {what}")

    while True:
        team = eng.decision_team
        was_declare = seats[a]._after_declare
        obs = [eng.obs(0), eng.obs(1)]
        supports = [eng.joint_support(0), eng.joint_support(1)]
        try:
            outs = [seats[s].step(obs[s], supports[s], s == team) for s in (0, 1)]
        except (ValueError, AssertionError, RuntimeError) as exc:
            bad(f"a seat could not select: {exc}")
        if not all(np.isfinite(o["logits"]).all() and math.isfinite(o["value"]) for o in outs):
            bad("a seat's logit or value is not finite")
        # A's network on the opponent's row, every step: the opponent model's state.
        _, value, shadow = p.policy.forward_eval(
            torch.from_numpy(obs[1 - a]).reshape(1, -1), shadow)
        if not bool(torch.isfinite(shadow).all() and torch.isfinite(value).all()):
            bad("the opponent-view state or value is not finite")
        if team == a:
            support = np.asarray(supports[a], dtype=np.int64).reshape(-1)
            types = {int(t) & 1023 for t in support}
            a0 = tuple(int(v) for v in outs[a]["tuple"])
            counts["own_decisions"] += 1
            if E.A["ACTIVATE"] in types and E.A["END_TURN"] in types:
                counts["turn_level"] += 1
            if a0[0] == E.A["ACTIVATE"]:
                counts["activate"] += 1
            if a0[0] == E.A["END_TURN"]:
                counts["end_turn"] += 1
            cls = classify(E, a0, types) if len(support) >= 2 else None
            if cls and in_kickoff_turn(E, eng.match()):
                kickoff_turn[cls] += 1
                cls = None
            if cls:
                seen[cls] += 1
                cap = caps[cls]
                slot = len(kept[cls]) if len(kept[cls]) < cap else pick[cls].randrange(seen[cls])
                if slot < cap:
                    m = eng.match()
                    root = {"cls": cls, "clone": eng.clone_for_search(0, S.SEARCH_DICE_STREAM),
                            "own": seats[a].state.clone(), "opp": shadow.clone(),
                            "logits": outs[a]["logits"].copy(), "support": support,
                            "a0": a0, "step": step, "value": outs[a]["value"],
                            "flags": (was_declare, seats[1 - a]._after_declare),
                            "clock": (int(m.half), int(m.turn[a])),
                            "score": (eng.score()[a], eng.score()[1 - a])}
                    if slot < len(kept[cls]):
                        kept[cls][slot]["clone"].close()
                        kept[cls][slot] = root
                    else:
                        kept[cls].append(root)
        action = tuple(int(v) for v in outs[team]["tuple"])
        rc = eng.step(*action)
        step += 1
        if rc not in (E.STEP_OK, E.STEP_TERMINAL):
            bad(f"the engine refused seat {team} tuple {action}: rc={rc}")
        hard = eng.counters()
        nonzero = {key: hard[key] for key in T.HARD_COUNTERS if hard[key]}
        if nonzero:
            bad(f"hard counters {nonzero}")
        rewards = eng.last_rewards()
        if not all(math.isfinite(r) for r in rewards):
            bad("a reward is not finite")
        if max(abs(r) for r in rewards) > p.reward_limit:
            bad(f"a reward of {max(rewards, key=abs)} is beyond the clip threshold "
                f"{p.reward_threshold}")
        if rc == E.STEP_TERMINAL:
            break
    final = eng.final_match()
    if final is None or final.status != E.STATUS_MATCH_OVER:
        bad("the game did not end in a natural match end (engine status "
            f"{None if final is None else int(final.status)})")
    counters = eng.counters()
    integrity = {key: int(counters[key]) for key in T.HARD_COUNTERS}
    if any(integrity.values()):
        bad(f"integrity counters at the end {integrity}")
    own_turns = int(final.turns_completed[a])
    final_score = (int(final.score[a]), int(final.score[1 - a]))
    eng.close()
    for cls in CLASSES:
        kept[cls].sort(key=lambda r: r["step"])
    return {"kept": kept, "seen": seen, "counts": counts, "kickoff_turn": kickoff_turn,
            "steps": step, "seed": seeds[a],
            "own_turns": own_turns, "final_score": final_score, "integrity": integrity}


# ---- per-root evaluation -----------------------------------------------------------------
def candidates_for(p, root, alternatives):
    """a0 first, then the most probable legal joint actions of the other type."""
    E, S = p.E, p.S
    want = {"end_turn": E.A["ACTIVATE"], "decline_block": E.A["BLOCK_TARGET"],
            "activate": E.A["END_TURN"]}[root["cls"]]
    tuples, logp = S.joint_log_probabilities(root["logits"], root["support"])
    first = int(np.flatnonzero(tuples == E.pack_tuple(*root["a0"]))[0])
    alts = [i for i in range(len(tuples)) if (int(tuples[i]) & 1023) == want][:alternatives]
    order = [first] + alts
    return ([E.unpack_tuple(tuples[i]) for i in order], [float(logp[i]) for i in order],
            first + 1, int(len(tuples)))


def audit(p, out, where, allowed):
    """Hold a batch to the probe's stop rule. Returns the number of rollouts that
    ended on the inherited decision cap, the one permitted loss."""
    S = p.S
    errors = out.count(S.STOP_ERROR)
    if errors:
        raise IntegrityError(f"{where}: {errors} rollout(s) failed: {out.errors[0][1]}")
    for stop in S.STOPS:
        if stop not in allowed and stop != S.STOP_CAP and out.count(stop):
            raise IntegrityError(f"{where}: {out.count(stop)} rollout(s) stopped on "
                                 f"'{stop}', which this arm does not allow")
    returns = np.asarray(out.returns, dtype=np.float64).reshape(-1)
    capped = np.array([s == S.STOP_CAP for s in out.stops])
    if not np.isfinite(returns[~capped]).all() or np.isfinite(returns[capped]).any():
        raise IntegrityError(f"{where}: a return is not finite, or a capped rollout has one")
    return int(capped.sum())


def dropped_indices(out):
    """Rollout indices without a return for at least one candidate."""
    return np.flatnonzero(~np.isfinite(np.asarray(out.returns)).all(axis=0)).tolist()


def continuation_stats(p, batch, k, n, seat):
    """Per candidate and rollout, over the searcher's own actions after the root
    action: the number of ACTIVATEs, whether a BLOCK_TARGET was chosen, and the
    number of STEPs. Kept per rollout: a capped rollout's trail is incomplete,
    and the analysis leaves its index out of these as it does out of the returns."""
    activate, block, step = p.E.A["ACTIVATE"], p.E.A["BLOCK_TARGET"], p.E.A["STEP"]
    acts, blocks, steps = (np.zeros((k, n), dtype=np.int64) for _ in range(3))
    for c in range(k):
        for j in range(n):
            own = [tup[0] for row, tup, _ in batch.trails[c * n + j][1:] if row == seat]
            acts[c, j], blocks[c, j], steps[c, j] = own.count(activate), int(block in own), own.count(step)
    return {"more_activations": acts.tolist(), "block": blocks.tolist(), "own_steps": steps.tolist()}


def stops_count(S, batch):
    return {stop: batch.count(stop) for stop in S.STOPS if batch.count(stop)}


def turn_arm(p, rollouts, root, cands, n, seed, where):
    S = p.S
    out = rollouts.evaluate(root["clone"], root["own"], root["opp"], cands, n, seed,
                            root["step"], after_declare=root["flags"], record=True)
    caps = audit(p, out, where + ", turn arm", (S.STOP_TURN, S.STOP_TERMINAL))
    return out, caps, {"returns": rnd(out.returns),
                       "bootstrap": rnd(out.bootstraps), "steps": out.steps.astype(int).tolist(),
                       "stops": stops_count(S, out), "dropped": dropped_indices(out),
                       **continuation_stats(p, out, len(cands), n, rollouts.seat)}


def forced_arm(p, rollouts, root, alts, n, seed, where):
    S = p.S
    out, _, gens = p.evaluate(rollouts, root, alts, n, seed, forced=True, record=True)
    caps = audit(p, out, where + ", forced arm", (S.STOP_TURN, S.STOP_TERMINAL))
    applied = np.array([p.force_applied.get(id(g), 0) for g in gens]).reshape(len(alts), n)
    if applied.max() > 1:
        raise IntegrityError(f"{where}, forced arm: the rule ended a turn "
                             f"{int(applied.max())} times in one rollout")
    return out, caps, {"returns": rnd(out.returns),
                       "bootstrap": rnd(out.bootstraps), "steps": out.steps.astype(int).tolist(),
                       "stops": stops_count(S, out), "dropped": dropped_indices(out),
                       "forced": applied.astype(int).tolist(), "forced_max": int(applied.max()),
                       **continuation_stats(p, out, len(alts), n, rollouts.seat)}


def match_arm(p, rollouts, root, cands, n, seed, turn_returns, where):
    """a0 and the first alternative to the end of the match, with the reward
    components. Reduces each rollout to scalars and each root to component means."""
    S = p.S
    out, clones, _ = p.evaluate(rollouts, root, cands, n, seed, capture=True)
    caps = audit(p, out, where + ", match arm", (S.STOP_TERMINAL,))
    k, nc = len(cands), len(p.channels)
    g_end = np.full((len(GAMMAS), k, n), np.nan)
    g_depth = np.full((DEPTHS, k, n), np.nan)
    t_depth = np.full((DEPTHS, k, n), -1, dtype=np.int64)
    comp = np.full((DEPTHS + 1, k, n, nc), np.nan)       # depth 1..3, then the match end
    marks_n = np.zeros((k, n), dtype=np.int64)
    terminal = np.zeros((k, n), dtype=bool)
    worst_sum, worst_step = 0.0, 0.0
    for c in range(k):
        for j in range(n):
            b = c * n + j
            if out.stops[b] != S.STOP_TERMINAL:
                continue
            terminal[c, j] = True
            rows = np.array(p.capture_rows.get(id(clones[b]), []))
            steps = int(out.steps[c, j])
            if rows.shape[0] != steps:
                raise IntegrityError(f"{where}, match arm: the component capture saw "
                                     f"{rows.shape[0]} steps of {steps}")
            reward = rows[:, -1]
            residual = reward - rows[:, :-1].sum(axis=1)
            if steps > 1:
                # Before the last step the env itemises the whole reward. The last
                # step ends the match and the env's reset clears its components,
                # so that step's reward is kept whole in the 29th entry.
                worst_step = max(worst_step, float(np.abs(residual[:-1]).max()))
            parts = np.concatenate([rows[:, :-1], residual[:, None]], axis=1)
            disc = rollouts.gamma ** np.arange(steps)
            cum = np.cumsum(parts * disc[:, None], axis=0)
            worst_sum = max(worst_sum, abs(float(cum[-1].sum()) - float(out.rewards[c, j])))
            for gi, gamma in enumerate(GAMMAS):
                g_end[gi, c, j] = float((reward * gamma ** np.arange(steps)).sum())
            marks = out.marks[b]
            marks_n[c, j] = len(marks)
            for d in range(DEPTHS):
                if d < len(marks):
                    t, rew, _, value = marks[d]
                    g_depth[d, c, j] = rew + rollouts.gamma ** t * value
                    t_depth[d, c, j] = t
                    comp[d, c, j] = cum[t - 1]
                else:                       # the match ended before this turn end
                    g_depth[d, c, j] = g_end[0, c, j]
                    t_depth[d, c, j] = steps
                    comp[d, c, j] = cum[-1]
            comp[DEPTHS, c, j] = cum[-1]
    if worst_step > RESIDUAL_TOLERANCE:
        raise IntegrityError(f"{where}, match arm: on a step before the last the components "
                             f"miss the reward by {worst_step}")
    if worst_sum > 1e-4:
        raise IntegrityError(f"{where}, match arm: components and final reward miss the "
                             f"rollout's reward total by {worst_sum}")
    pair = terminal.all(axis=0)                           # rollout indices valid for every candidate
    scores = out.scores.astype(np.int64)                  # (k, n, [own, opponent])
    both = min(n, turn_returns.shape[1])
    shared = pair[:both] & np.isfinite(turn_returns[:k, :both]).all(axis=0)
    depth1_gap = float(np.abs(g_depth[0, :, :both] - turn_returns[:k, :both])[:, shared].max()) \
        if shared.any() else 0.0
    record = {"candidates": [list(c) for c in cands], "rollouts": n, "valid_pairs": int(pair.sum()),
              "stops": stops_count(S, out), "dropped": np.flatnonzero(~pair).tolist(),
              "g_end": {str(g): rnd(g_end[gi]) for gi, g in enumerate(GAMMAS)},
              "g_depth": rnd(g_depth), "t_depth": t_depth.tolist(),
              "td_own": scores[:, :, 0].tolist(), "td_opp": scores[:, :, 1].tolist(),
              "steps": out.steps.astype(int).tolist(), "turn_ends": marks_n.tolist(),
              "pair_valid": pair.astype(int).tolist(),
              "check_component_sum": worst_sum, "check_step_residual": worst_step,
              "check_depth1_vs_turn_arm": depth1_gap}
    if pair.any():
        record["component_mean"] = rnd(comp[:, :, pair].mean(axis=2), 6)     # (horizon, k, channel)
        diff = comp[:, 1, pair] - comp[:, 0, pair]                            # alternative - a0
        record["component_diff_mean"] = rnd(diff.mean(axis=1), 6)
        if pair.sum() > 1:
            record["component_diff_sd"] = rnd(diff.std(axis=1, ddof=1), 6)
    return out, caps, record


def identity_check(p, rollouts, root, cands, n, seed, recorded, where, own_entry):
    """The turn arm three ways on one root: hooks removed, hooks installed and idle
    (`recorded`), and through this tool's own entry. Exact agreement, all finite.
    A root whose recorded turn arm lost a rollout to the decision cap is not
    eligible: nothing is run on it and the next root of the class is tried. The
    two extra computations are held to the turn arm's rollout checks before
    they are compared."""
    S = p.S
    if not np.isfinite(recorded.returns).all():
        return False
    with p.unhooked():
        bare = rollouts.evaluate(root["clone"], root["own"], root["opp"], cands, n, seed,
                                 root["step"], after_declare=root["flags"])
    versions = [("the hooks removed", bare)]
    if own_entry:
        versions.append(("the tool's own entry", p.evaluate(rollouts, root, cands, n, seed)[0]))
    for name, other in versions:
        audit(p, other, f"{where}, identity check with {name}", (S.STOP_TURN, S.STOP_TERMINAL))
        for field in ("returns", "rewards", "bootstraps", "steps"):
            if not np.array_equal(np.asarray(getattr(other, field)).reshape(-1),
                                  np.asarray(getattr(recorded, field)).reshape(-1)):
                raise IntegrityError(f"{where}: the turn arm with {name} differs from the "
                                     f"recorded one in {field}")
    return True


def run_game(p, game, args, rollouts_turn, rollouts_match, sink_roots):
    E = p.E
    engine_seed = args.seed0 + game
    a = game % 2
    t0 = time.time()
    caps = {"end_turn": args.cap_end_turn, "decline_block": args.cap_decline_block,
            "activate": args.cap_activate}
    g = play_game(p, engine_seed, a, caps)
    t_play = time.time() - t0
    secs = {"turn": 0.0, "forced": 0.0, "match": 0.0}
    steps = {"turn": 0, "forced": 0, "match": 0}
    capped = {"turn": 0, "forced": 0, "match": 0}
    checks = {"identity_roots": 0, "identity_eligible": 0, "component_sum_max_abs": 0.0,
              "step_residual_max_abs": 0.0, "depth1_max_abs": 0.0, "forced_max": 0}
    ends = g["kept"]["end_turn"]
    chosen = set(random.Random(engine_seed * 7919 + 1).sample(
        range(len(ends)), min(args.match_roots, len(ends))))
    root_lines = 0
    for cls in CLASSES:
        identity_done = eligible = False
        for index, root in enumerate(g["kept"][cls]):
            where = f"engine seed {engine_seed}, step {root['step']} ({cls})"
            cands, logp, rank, support = candidates_for(p, root, args.alternatives)
            base = {"schema": SCHEMA_ROOT, "checkpoint": args.checkpoint_name, "game": game,
                    "engine_seed": engine_seed, "seat": a, "step": root["step"], "class": cls,
                    "clock": list(root["clock"]), "score": list(root["score"]),
                    "support": support, "a0_rank": rank, "root_value": float(root["value"]),
                    "tuples": [list(c) for c in cands], "types": [E.ACTION_TYPES[c[0]] for c in cands],
                    "logp": logp, "seen_in_game": g["seen"][cls], "kept_in_game": len(g["kept"][cls])}
            if len(cands) < 2:
                base["skipped"] = "no alternative of the other type"
                sink_roots.write(json.dumps(base) + "\n")
                root_lines += 1
                root["clone"].close()
                continue
            t1 = time.time()
            out, lost, base["turn"] = turn_arm(p, rollouts_turn[a], root, cands, args.rollouts,
                                               g["seed"], where)
            secs["turn"] += time.time() - t1
            steps["turn"] += out.engine_steps
            capped["turn"] += lost
            eligible = eligible or bool(np.isfinite(out.returns).all())
            if not identity_done:
                identity_done = identity_check(p, rollouts_turn[a], root, cands, args.rollouts,
                                               g["seed"], out, where, cls == "end_turn")
                checks["identity_roots"] += int(identity_done)
            if cls == "end_turn":
                t1 = time.time()
                fout, lost, base["forced"] = forced_arm(p, rollouts_turn[a], root, cands[1:],
                                                        args.rollouts, g["seed"], where)
                secs["forced"] += time.time() - t1
                steps["forced"] += fout.engine_steps
                capped["forced"] += lost
                checks["forced_max"] = max(checks["forced_max"], base["forced"]["forced_max"])
                if index in chosen and args.match_rollouts > 0:
                    t1 = time.time()
                    mout, lost, base["match"] = match_arm(
                        p, rollouts_match[a], root, cands[:2], args.match_rollouts, g["seed"],
                        np.asarray(out.returns, dtype=np.float64), where)
                    secs["match"] += time.time() - t1
                    steps["match"] += mout.engine_steps
                    capped["match"] += lost
                    base["match"]["sampled_of"] = len(ends)
                    for key, name in (("component_sum_max_abs", "check_component_sum"),
                                      ("step_residual_max_abs", "check_step_residual"),
                                      ("depth1_max_abs", "check_depth1_vs_turn_arm")):
                        checks[key] = max(checks[key], base["match"][name])
            sink_roots.write(json.dumps(base) + "\n")
            sink_roots.flush()
            root_lines += 1
            root["clone"].close()
        # A class of a game is eligible when one of its roots has a turn arm with
        # no capped rollout; every eligible class must have had its identity check.
        checks["identity_eligible"] += int(eligible)
    return {"schema": SCHEMA_GAME, "checkpoint": args.checkpoint_name, "game": game,
            "engine_seed": engine_seed, "seat": a, "engine_steps": g["steps"],
            "natural": True, "invalid": [], "integrity": g["integrity"],
            "own_turns": g["own_turns"], "final_score": list(g["final_score"]),
            "counts": g["counts"], "seen": g["seen"], "kickoff_turn_decisions": g["kickoff_turn"],
            "kept": {c: len(g["kept"][c]) for c in CLASSES}, "match_roots": len(chosen),
            "root_lines": root_lines, "capped_rollouts": capped, "checks": checks,
            "seconds": {"play": round(t_play, 2), **{k: round(v, 2) for k, v in secs.items()},
                        "total": round(time.time() - t0, 2)},
            "rollout_engine_steps": steps}


# ---- commands --------------------------------------------------------------------------------
def load_plan(path, expect):
    with open(path, "rb") as f:
        raw = f.read()
    got = hashlib.sha256(raw).hexdigest()
    if got != expect:
        raise SystemExit(f"{path} hashes to {got}, not to --expect-sha256 {expect}")
    return json.loads(raw), got


def settle(args):
    """Fill the settings from the plan (and hold the inputs to it), or from the
    command line for an unregistered run."""
    harness = os.path.abspath(args.harness)
    commit_file = os.path.join(harness, "SOURCE_COMMIT")
    args.harness_commit = open(commit_file).read().strip() if os.path.exists(commit_file) else None
    args.checkpoint_sha256 = sha256_file(args.checkpoint)
    args.plan_sha256 = None
    if args.plan:
        plan, args.plan_sha256 = load_plan(args.plan, args.expect_sha256)
        want = plan["checkpoints"].get(args.checkpoint_name)
        if want is None:
            raise SystemExit(f"the plan has no checkpoint {args.checkpoint_name!r}")
        if want["sha256"] != args.checkpoint_sha256:
            raise SystemExit(f"{args.checkpoint} is not the plan's {args.checkpoint_name}")
        if args.harness_commit != plan["harness_commit"]:
            raise SystemExit(f"the harness export is at {args.harness_commit}, the plan pins "
                             f"{plan['harness_commit']}")
        if tool_sha256() != plan["tool_sha256"]:
            raise SystemExit("this tool's files do not hash to the plan's tool_sha256")
        if list(INTEGRITY_CHECKS) != plan["integrity_checks"]:
            raise SystemExit("this tool's integrity checks are not the plan's list")
        for key in SETTING_KEYS:
            setattr(args, key, plan["settings"][key])
        args.manifest_sha256_expected = plan["reward_manifest_sha256"]
        args.registered = True
    else:
        missing = [k for k in SETTING_KEYS if getattr(args, k) is None]
        if missing:
            raise SystemExit(f"without --plan these are required: {missing}")
        args.manifest_sha256_expected = None
        args.registered = False
    args.manifest = args.manifest or os.path.join(harness, "puffer", "config", "rewards",
                                                  "r0_poss_half.json")
    return args


def worker_args(args):
    out = ["--harness", args.harness, "--lib", args.lib, "--checkpoint", args.checkpoint,
           "--checkpoint-name", args.checkpoint_name, "--out-dir", args.out_dir,
           "--manifest", args.manifest]
    if args.plan:
        out += ["--plan", args.plan, "--expect-sha256", args.expect_sha256]
    else:
        for key in SETTING_KEYS:
            out += ["--" + key.replace("_", "-"), str(getattr(args, key))]
    return out


def cmd_worker(args):
    args = settle(args)
    p = Probe(args.harness, args.lib, args.checkpoint, args.manifest)
    if args.manifest_sha256_expected and p.manifest["sha256"] != args.manifest_sha256_expected:
        raise SystemExit("the reward manifest is not the plan's")
    S = p.S
    rollouts_turn = [S.Rollouts(p.policy, seat, masks=(), max_steps=MATCH_MAX_STEPS,
                                reward_limit=p.reward_limit) for seat in (0, 1)]
    rollouts_match = [S.Rollouts(p.policy, seat, masks=(), horizon=S.HORIZON_MATCH,
                                 max_steps=MATCH_MAX_STEPS, reward_limit=p.reward_limit)
                      for seat in (0, 1)]
    tag = f"w{args.index}"
    games = [g for g in range(args.games) if g % args.of == args.index]
    with open(os.path.join(args.out_dir, f"roots.{tag}.jsonl"), "x") as sink_roots, \
            open(os.path.join(args.out_dir, f"games.{tag}.jsonl"), "x") as sink_games:
        if args.index == 0:
            with open(os.path.join(args.out_dir, "meta.w0.json"), "w") as f:
                json.dump({"channels": p.channels, "library_sha256": p.library_sha256,
                           "reward_manifest": p.manifest["name"],
                           "reward_manifest_sha256": p.manifest["sha256"],
                           "reward_clip_threshold": p.reward_threshold,
                           "rollout_step_limit": MATCH_MAX_STEPS,
                           "search_gamma": S.GAMMA, "torch": p.torch.__version__,
                           "numpy": np.__version__}, f, indent=1)
        for game in games:
            try:
                record = run_game(p, game, args, rollouts_turn, rollouts_match, sink_roots)
            except IntegrityError as exc:
                print(f"INTEGRITY: {exc}", flush=True)
                return 2
            sink_games.write(json.dumps(record) + "\n")
            sink_games.flush()
            print(f"{tag} game {game}: {record['root_lines']} roots, "
                  f"{record['seconds']['total']} s", flush=True)
    return 0


def count_lines(paths):
    total = 0
    for path in paths:
        try:
            with open(path) as f:
                total += sum(1 for _ in f)
        except OSError:
            pass
    return total


def fail_run(args, children, codes, started):
    """A worker failed: stop the others, leave FAILED.json, exit non-zero."""
    for child, _ in children:
        if child.poll() is None:
            child.terminate()
    for child, log in children:
        child.wait()
        log.close()
    reasons = []
    for index in range(len(children)):
        try:
            with open(os.path.join(args.out_dir, f"worker{index}.log")) as f:
                lines = f.read().splitlines()
        except OSError:
            lines = []
        reasons += [f"worker {index}: {line}" for line in lines if line.startswith("INTEGRITY:")]
        if codes[index] not in (None, 0, 2) and lines:
            reasons.append(f"worker {index} exit {codes[index]}: {lines[-1]}")
    with open(os.path.join(args.out_dir, "FAILED.json"), "w") as f:
        json.dump({"checkpoint": args.checkpoint_name, "worker_exit_codes": codes,
                   "reasons": reasons, "seconds": round(time.time() - started, 1)}, f, indent=1)
    raise SystemExit(f"{args.checkpoint_name}: NOT COMPLETE, worker exit codes {codes}: "
                     + ("; ".join(reasons) or f"see worker*.log in {args.out_dir}"))


def cmd_run(args):
    args = settle(args)
    os.makedirs(args.out_dir, exist_ok=True)
    for name in ("roots.jsonl", "games.jsonl", "COMPLETE.json", "FAILED.json", "roots.w0.jsonl"):
        if os.path.exists(os.path.join(args.out_dir, name)):
            raise SystemExit(f"{args.out_dir} already holds {name}; choose a fresh --out-dir")
    if not hasattr(ctypes.CDLL(os.path.abspath(args.lib)), "bbp_probe_reward_clip_threshold"):
        raise SystemExit(f"{args.lib} is not the probe's build; run build_shim.sh")
    processes = max(1, min(int(args.processes), args.games))
    started = time.time()
    children = []
    for index in range(processes):
        log = open(os.path.join(args.out_dir, f"worker{index}.log"), "w")
        argv = [sys.executable, os.path.abspath(__file__), "worker", "--index", str(index),
                "--of", str(processes)] + worker_args(args)
        children.append((subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT,
                                          stdin=subprocess.DEVNULL,
                                          env={**os.environ, "OMP_NUM_THREADS": "1"}), log))
    game_files = [os.path.join(args.out_dir, f"games.w{i}.jsonl") for i in range(processes)]
    last = 0.0
    while True:
        codes = [child.poll() for child, _ in children]
        if any(code not in (None, 0) for code in codes):
            fail_run(args, children, codes, started)            # fail fast: stop the rest
        if all(code == 0 for code in codes):
            break
        time.sleep(1.0)
        if time.time() - last >= args.heartbeat:
            last = time.time()
            print(f"{args.checkpoint_name}: {count_lines(game_files)}/{args.games} games, "
                  f"{time.time() - started:.0f} s", flush=True)
    for _, log in children:
        log.close()
    games, roots = [], []
    for i in range(processes):
        with open(os.path.join(args.out_dir, f"games.w{i}.jsonl")) as f:
            games += [json.loads(line) for line in f]
        with open(os.path.join(args.out_dir, f"roots.w{i}.jsonl")) as f:
            roots += [json.loads(line) for line in f]
    games.sort(key=lambda r: r["game"])
    roots.sort(key=lambda r: (r["game"], CLASSES.index(r["class"]), r["step"]))
    if [g["game"] for g in games] != list(range(args.games)):
        raise SystemExit("the workers did not return every game exactly once")
    with open(os.path.join(args.out_dir, "games.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in games)
    with open(os.path.join(args.out_dir, "roots.jsonl"), "w") as f:
        f.writelines(json.dumps(r) + "\n" for r in roots)
    with open(os.path.join(args.out_dir, "meta.w0.json")) as f:
        meta = json.load(f)
    seconds = time.time() - started
    arms = ("turn", "forced", "match")
    steps = {arm: sum(g["rollout_engine_steps"][arm] for g in games) for arm in arms}
    capped = {arm: sum(g["capped_rollouts"][arm] for g in games) for arm in arms}
    arm_seconds = {arm: round(sum(g["seconds"][arm] for g in games), 1)
                   for arm in ("play",) + arms}
    checks = {"identity_roots": sum(g["checks"]["identity_roots"] for g in games),
              "identity_eligible": sum(g["checks"]["identity_eligible"] for g in games),
              "identity_max_abs": 0.0,       # a difference is fatal, so a finished run has none
              "component_sum_max_abs": max(g["checks"]["component_sum_max_abs"] for g in games),
              "step_residual_max_abs": max(g["checks"]["step_residual_max_abs"] for g in games),
              "depth1_max_abs": max(g["checks"]["depth1_max_abs"] for g in games),
              "forced_max": max(g["checks"]["forced_max"] for g in games)}
    complete = {"schema": SCHEMA_COMPLETE, "checkpoint": args.checkpoint_name,
                "checkpoint_sha256": args.checkpoint_sha256, "registered": args.registered,
                "plan_sha256": args.plan_sha256, "harness_commit": args.harness_commit,
                "tool_sha256": tool_sha256(), **meta,
                "settings": {k: getattr(args, k) for k in SETTING_KEYS},
                "integrity_checks": list(INTEGRITY_CHECKS),
                "games": len(games), "natural_games": sum(bool(g["natural"]) for g in games),
                "invalid_games": sum(bool(g["invalid"]) for g in games),
                "error_rollouts": 0, "step_limit_rollouts": 0, "capped_rollouts": capped,
                "root_lines": len(roots),
                "roots_by_class": {c: sum(r["class"] == c for r in roots) for c in CLASSES},
                "match_roots": sum("match" in r for r in roots),
                "processes": processes, "wall_seconds": round(seconds, 1),
                "worker_seconds": arm_seconds, "rollout_engine_steps": steps, "checks": checks,
                "roots_sha256": sha256_file(os.path.join(args.out_dir, "roots.jsonl")),
                "games_sha256": sha256_file(os.path.join(args.out_dir, "games.jsonl"))}
    with open(os.path.join(args.out_dir, "COMPLETE.json"), "w") as f:
        json.dump(complete, f, indent=1)
    print(f"{args.checkpoint_name}: done, {len(games)} games, {len(roots)} roots, "
          f"{seconds:.0f} s wall on {processes} process(es); capped rollouts {capped}; "
          f"checks {checks}", flush=True)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for name, func in (("run", cmd_run), ("worker", cmd_worker)):
        sp = sub.add_parser(name)
        sp.add_argument("--harness", required=True, help="an export of the harness at its pin")
        sp.add_argument("--lib", required=True, help="build_shim.sh's library")
        sp.add_argument("--checkpoint", required=True)
        sp.add_argument("--checkpoint-name", required=True)
        sp.add_argument("--manifest", default=None)
        sp.add_argument("--out-dir", required=True)
        sp.add_argument("--plan", default=None)
        sp.add_argument("--expect-sha256", default=None)
        for key in SETTING_KEYS:
            sp.add_argument("--" + key.replace("_", "-"), type=int, default=None)
        if name == "run":
            sp.add_argument("--processes", type=int, default=1)
            sp.add_argument("--heartbeat", type=float, default=30.0)
        else:
            sp.add_argument("--index", type=int, required=True)
            sp.add_argument("--of", type=int, required=True)
        sp.set_defaults(func=func)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    if bool(args.plan) != bool(args.expect_sha256):
        raise SystemExit("--plan and --expect-sha256 go together")
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
