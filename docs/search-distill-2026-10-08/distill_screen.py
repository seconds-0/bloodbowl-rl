#!/usr/bin/env python3
"""Search distillation, the label tool: plain self-play games of one checkpoint
under its masks, with the search seat's own computation run at a sample of the
decisions the seat would search.

One checkpoint plays itself (seat B on sampling offset 1, both seats under the
plan's masks, T=1, kick-off starts, the training reward manifest). Seat A is
HOME in even games and AWAY in odd ones. At seat A's decisions in the seat's
scope (class `turn`: an ACTIVATE is legal after masks; class `after_declare`:
the first own decision after the own DECLARE) with two or more legal actions it
keeps a root: a search clone, both recurrent states (A's own view and A's
network on the opponent's row), the logits, the masked support and the action
plain play sampled (a0). Per game it keeps `per_class` roots per class, a
uniform sample of that game's searchable decisions of the class (a reservoir,
drawn exactly as tools/search_probe_diag.py draws it, so the 2026-10-07 screens
regenerate root for root). It also notes a uniform sample of seat A's other
multi-action decisions (step numbers only; they need no rollouts).

After the game every kept root is screened as the seat screens it:
  candidates  a0, then the other legal joint actions with the highest policy
              probability, min(candidates, support size) in all
  rollouts    `screen_rollouts` of each through play_harness.search.Rollouts.
              evaluate on common random numbers, seeds from A's sampling seed,
              the engine step and the rollout index (the seat's own seeds)
  the rule    play_harness.search.deviation(returns, delta)
A root where any screening rollout ends on the decision cap its clone
inherited is a cap rejection, as for the seat: counted, never a label.
A deviation root is then judged on `judge_pairs` fresh rollout pairs of a0
against the label (rollout indices from `judge_first_index`, never used by the
screen, same horizon). A judgment index where either rollout ends on the
inherited cap is dropped for both and counted; a label with fewer than
`judge_min_pairs` pairs left is recorded as unjudged. It stays a label.

A decision inside a kick-off Blitz turn is a root like any other and is
flagged (`kickoff_turn`, D439's stack rule): the seat that was gated searched
those decisions too, with a rollout that runs to the end of its next real turn.

Integrity is fail-fast (INTEGRITY_CHECKS). Any failure stops the worker with a
non-zero exit, the run writes FAILED.json and no COMPLETE.json, and the shard
is not accepted. The harness is used from an export of the pinned commit and
is not modified.

  distill_screen.py run --harness EXPORT --plan PLAN.json --expect-sha256 H \\
      --shard NAME --checkpoint BLOB --out-dir DIR [--processes 1]
"""
from __future__ import annotations

import argparse
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
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402

SCHEMA_ROOT = "search-distill-root-v1"
SCHEMA_GAME = "search-distill-game-v1"
SCHEMA_OTHER = "search-distill-other-v1"
SCHEMA_COMPLETE = "search-distill-complete-v1"
SETTING_KEYS = ("seed0", "per_class", "other_per_game", "candidates", "screen_rollouts",
                "delta", "judge_pairs", "judge_first_index", "judge_min_pairs", "masks")
# Every integrity check a game of this tool runs. Any failure is fatal to the shard.
INTEGRITY_CHECKS = (
    "real game: the engine's return code on every step",
    "real game: hard counters after every step and at the end (illegal, "
    "projection_collision, error_episodes, rejected_submissions, precheck_collisions)",
    "real game: both seats' logits and values finite on every step",
    "real game: the opponent-view state and value finite on every step",
    "real game: both seats' emitted rewards finite and within the clip threshold on "
    "every step",
    "real game: no mask fallback",
    "real game: the game ends in a natural match end (STATUS_MATCH_OVER), not on the "
    "decision cap",
    "rollouts: the engine's return code and status on every step",
    "rollouts: the same hard counters of every clone at its rollout's end",
    "rollouts: both seats' emitted rewards finite and within the clip threshold on "
    "every step",
    "rollouts: logits and values finite on every forward",
    "rollouts: the accumulated return finite",
    "rollouts: no mask fallback, and an action selectable at every decision",
    "rollouts: no rollout fails; a rollout stops on a turn end, the match end, the "
    "200-step cut-off or the inherited decision cap",
    "search: every return the deviation rule reads is finite",
)
OTHER_SALT = 0x0D15711


def rnd(x, digits=9):
    return np.round(np.asarray(x, dtype=np.float64), digits).tolist()


class Labeler:
    """The harness, one checkpoint and the label settings, loaded once per process."""

    def __init__(self, harness, checkpoint, settings):
        self.hx = hx = C.Harness(harness)
        self.E, self.S, self.T, self.torch = hx.E, hx.S, hx.T, hx.torch
        self.policy, self.provenance = hx.load_policy(checkpoint)
        self.s = dict(settings)
        self.masks = tuple(self.s["masks"])
        if not self.masks:
            raise SystemExit("the label tool plays under at least one mask (the seat's own rule)")
        self.rollouts = [self.S.Rollouts(self.policy, seat, masks=self.masks,
                                         reward_limit=hx.reward_limit) for seat in (0, 1)]

    def close(self):
        for r in self.rollouts:
            r.close()

    # ---- one real game ----------------------------------------------------------------
    def play_game(self, engine_seed, a, select="reservoir", until_step=None, keep_steps=None):
        """One plain self-play game with seat A on side `a`, under the real-game
        integrity checks.

        select      "reservoir": the registered sample (per_class roots per class).
                    "all": every searchable in-scope decision is a root (tests).
                    "steps": only the decisions at engine steps in `keep_steps` (tests).
        until_step  stop before applying this engine step and return the game
                    unfinished (tests); the natural-end checks are then skipped.
        """
        E, S, T, torch, hx = self.E, self.S, self.T, self.torch, self.hx
        MaskedPolicySeat, restrict_support = hx.P.MaskedPolicySeat, hx.P.restrict_support
        per_class, other_cap = int(self.s["per_class"]), int(self.s["other_per_game"])
        seeds = [T.sampling_seed(engine_seed, side) for side in (0, 1)]
        seeds[1 - a] = (seeds[1 - a] + T.SEED_OFFSET_STRIDE) % (1 << 62)
        seats = [MaskedPolicySeat(self.policy, side, seed=seeds[side], masks=self.masks)
                 for side in (0, 1)]
        for seat in seats:
            seat.reset_match()
        eng = E.Engine(engine_seed, rewards=hx.manifest["rewards"])
        shadow = self.policy.initial_state(1)
        pick = random.Random(engine_seed)                   # as tools/search_probe_diag.py
        pick_other = random.Random((int(engine_seed) << 1) ^ OTHER_SALT)
        kept = {c: [] for c in C.SCOPE}
        counts = {"in_scope": {c: 0 for c in C.SCOPE}, "single_action": {c: 0 for c in C.SCOPE},
                  "searchable": {c: 0 for c in C.SCOPE}, "kickoff_turn": {c: 0 for c in C.SCOPE},
                  "own_decisions": 0, "other_searchable": 0, "kickoff_turn_own_decisions": 0}
        other, trail = [], []
        obs_hash = [hashlib.sha256(), hashlib.sha256()]
        step, finished = 0, False

        def bad(what):
            raise C.IntegrityError(f"real game, engine seed {engine_seed}, step {step}: {what}")

        try:
            while True:
                if until_step is not None and step >= until_step:
                    break
                team = eng.decision_team
                was_declare = seats[a]._after_declare
                obs = [eng.obs(0), eng.obs(1)]
                supports = [eng.joint_support(0), eng.joint_support(1)]
                for row in (0, 1):
                    obs_hash[row].update(obs[row].tobytes())
                try:
                    outs = [seats[s].step(obs[s], supports[s], s == team) for s in (0, 1)]
                except (ValueError, AssertionError, RuntimeError) as exc:
                    bad(f"a seat could not select: {exc}")
                if not all(np.isfinite(o["logits"]).all() and math.isfinite(o["value"])
                           for o in outs):
                    bad("a seat's logit or value is not finite")
                # A's network on the opponent's row, every step: the state the seat
                # holds for its opponent model.
                _, value, shadow = self.policy.forward_eval(
                    torch.from_numpy(obs[1 - a]).reshape(1, -1), shadow)
                if not bool(torch.isfinite(shadow).all() and torch.isfinite(value).all()):
                    bad("the opponent-view state or value is not finite")
                if team == a:
                    counts["own_decisions"] += 1
                    support, _ = restrict_support(supports[a], self.masks, was_declare)
                    cls = S.decision_class({int(t) & 1023 for t in support}, was_declare)
                    kickoff = C.in_kickoff_turn(E, eng.match())
                    counts["kickoff_turn_own_decisions"] += int(kickoff)
                    if cls in C.SCOPE:
                        counts["in_scope"][cls] += 1
                        if len(support) < 2:
                            counts["single_action"][cls] += 1
                        else:
                            counts["searchable"][cls] += 1
                            counts["kickoff_turn"][cls] += int(kickoff)
                            seen = counts["searchable"][cls]
                            if select == "reservoir":
                                slot = len(kept[cls]) if len(kept[cls]) < per_class \
                                    else pick.randrange(seen)
                                keep = slot < per_class
                            elif select == "all":
                                slot, keep = len(kept[cls]), True
                            else:
                                slot, keep = len(kept[cls]), step in (keep_steps or ())
                            if keep:
                                root = {
                                    "class": cls, "step": step, "kickoff_turn": bool(kickoff),
                                    "clone": eng.clone_for_search(0, S.SEARCH_DICE_STREAM),
                                    "own": seats[a].state.clone(), "opp": shadow.clone(),
                                    "logits": outs[a]["logits"].copy(),
                                    "support": np.asarray(support).copy(),
                                    "a0": tuple(int(v) for v in outs[a]["tuple"]),
                                    "a0_logprob": float(outs[a]["logprob"]),
                                    "flags": (bool(was_declare),
                                              bool(seats[1 - a]._after_declare))}
                                if slot < len(kept[cls]):
                                    kept[cls][slot]["clone"].close()
                                    kept[cls][slot] = root
                                else:
                                    kept[cls].append(root)
                    elif len(support) >= 2:
                        counts["other_searchable"] += 1
                        slot = len(other) if len(other) < other_cap \
                            else pick_other.randrange(counts["other_searchable"])
                        if slot < other_cap:
                            if slot < len(other):
                                other[slot] = step
                            else:
                                other.append(step)
                action = tuple(int(v) for v in outs[team]["tuple"])
                trail.append([int(team), action[0], action[1], action[2]])
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
                if max(abs(r) for r in rewards) > hx.reward_limit:
                    bad(f"a reward of {max(rewards, key=abs)} is beyond the clip threshold "
                        f"{hx.reward_threshold}")
                if rc == E.STEP_TERMINAL:
                    finished = True
                    break
            out = {"kept": kept, "other": sorted(other), "counts": counts, "trail": trail,
                   "steps": step, "seeds": seeds, "seed": seeds[a], "finished": finished,
                   "seat_state": seats[a].state.clone(), "shadow": shadow.clone()}
            if finished:
                final = eng.final_match()
                if final is None or final.status != E.STATUS_MATCH_OVER:
                    bad("the game did not end in a natural match end (engine status "
                        f"{None if final is None else int(final.status)})")
                counters = eng.counters()
                integrity = {key: int(counters[key]) for key in T.HARD_COUNTERS}
                if any(integrity.values()):
                    bad(f"integrity counters at the end {integrity}")
                fallbacks = sum(v["fallback"] for seat in seats for v in seat.mask_stats.values())
                if fallbacks:
                    bad(f"a mask gave way {fallbacks} time(s)")
                out.update(integrity=integrity, final_status=int(final.status),
                           final_digest=f"{eng.digest():016x}",
                           score=[int(final.score[0]), int(final.score[1])],
                           team_ids=[int(final.team_id[0]), int(final.team_id[1])],
                           obs_sha256=[h.hexdigest() for h in obs_hash],
                           own_turns=int(final.turns_completed[a]))
            for cls in C.SCOPE:
                kept[cls].sort(key=lambda r: r["step"])
            return out
        finally:
            eng.close()

    # ---- one root, as the seat sees it --------------------------------------------------
    def candidates(self, root):
        """(candidate tuples, their log-probabilities, a0's rank, support size): a0
        first, then the other legal joint actions by policy probability, ties in
        packed order. The seat's own two calls."""
        E, S = self.E, self.S
        tuples, logps = S.joint_log_probabilities(root["logits"], root["support"], 1.0)
        order = S.candidate_order(tuples, E.pack_tuple(*root["a0"]), int(self.s["candidates"]))
        return ([E.unpack_tuple(tuples[i]) for i in order], [float(logps[i]) for i in order],
                int(order[0]) + 1, int(len(tuples)))

    def screen(self, root, a, seed, where):
        """The seat's screen and rule at one root, then the fresh judgment of a
        deviation. Returns the record's fields; raises IntegrityError on a
        failed rollout or a return that is not finite."""
        S = self.S
        cands, logps, rank, support_size = self.candidates(root)
        n = int(self.s["screen_rollouts"])
        batch = self.rollouts[a].evaluate(root["clone"], root["own"], root["opp"], cands, n,
                                          seed, root["step"], after_declare=root["flags"])
        if batch.count(S.STOP_ERROR):
            raise C.IntegrityError(f"{where}: a screening rollout failed: {batch.errors[0][1]}")
        stops = {s: batch.count(s) for s in S.STOPS}
        out = {"tuples": [list(c) for c in cands], "logps": rnd(logps), "a0_rank": rank,
               "support_size": support_size, "rollouts": n, "stops": stops,
               "rollout_engine_steps": int(batch.engine_steps),
               "cap_rejected": bool(stops[S.STOP_CAP]), "deviate": False, "best": None,
               "gain": None, "se": None, "label": None, "returns": None, "judgment": None}
        if out["cap_rejected"]:
            return out
        try:
            deviate, best, gain, se = S.deviation(batch.returns, float(self.s["delta"]))
        except ValueError as exc:
            raise C.IntegrityError(f"{where}: the deviation rule could not be applied: {exc}")
        out.update(returns=[[float(v) for v in row] for row in batch.returns],
                   deviate=bool(deviate), best=int(best), gain=float(gain), se=float(se))
        if not deviate:
            return out
        label = tuple(int(v) for v in cands[best])
        out["label"] = list(label)
        pairs, first = int(self.s["judge_pairs"]), int(self.s["judge_first_index"])
        judge = self.rollouts[a].evaluate(root["clone"], root["own"], root["opp"],
                                          [cands[0], label], pairs, seed, root["step"],
                                          after_declare=root["flags"], first_index=first)
        if judge.count(S.STOP_ERROR):
            raise C.IntegrityError(f"{where}: a judgment rollout failed: {judge.errors[0][1]}")
        valid = np.isfinite(judge.returns).all(axis=0)
        capped = int(judge.count(S.STOP_CAP))
        if int((~valid).sum()) > capped or (capped == 0 and not valid.all()):
            raise C.IntegrityError(f"{where}: a judgment return is not finite without a cap stop")
        d = judge.returns[1, valid] - judge.returns[0, valid]
        kept = int(valid.sum())
        judged = kept >= int(self.s["judge_min_pairs"])
        fresh = float(d.mean()) if kept else None
        fresh_se = float(d.std(ddof=1) / math.sqrt(kept)) if kept > 1 else None
        out["rollout_engine_steps"] += int(judge.engine_steps)
        out["judgment"] = {
            "first_index": first, "pairs": pairs, "kept_pairs": kept,
            "dropped_pairs": pairs - kept, "capped_rollouts": capped, "judged": bool(judged),
            "stops": {s: judge.count(s) for s in S.STOPS},
            "returns": [[None if not np.isfinite(v) else float(v) for v in row]
                        for row in judge.returns],
            "fresh_gain": fresh, "fresh_se": fresh_se,
            "false": bool(judged and fresh <= 0.0),
            "confirmed": bool(judged and fresh_se is not None and fresh > 2.0 * fresh_se)}
        return out


def run_game(lab, game, shard, sink_roots, sink_other):
    """Play, screen and judge one game; write its roots and its other-decision
    sample; return its game record."""
    seed0 = int(lab.s["seed0"])
    engine_seed, a = seed0 + game, game % 2
    t0 = time.time()
    g = lab.play_game(engine_seed, a)
    t_play = time.time() - t0
    kept, counts = g["kept"], g["counts"]
    totals = {"roots": 0, "deviation": 0, "cap_rejected": 0, "false": 0, "confirmed": 0,
              "unjudged": 0, "dropped_pairs": 0, "kickoff_turn_roots": 0, "engine_steps": 0}
    try:
        for cls in C.SCOPE:
            for root in kept[cls]:
                where = f"engine seed {engine_seed}, step {root['step']} ({cls})"
                rec = lab.screen(root, a, g["seed"], where)
                j = rec["judgment"]
                totals["roots"] += 1
                totals["deviation"] += int(rec["deviate"])
                totals["cap_rejected"] += int(rec["cap_rejected"])
                totals["kickoff_turn_roots"] += int(root["kickoff_turn"])
                totals["engine_steps"] += rec.pop("rollout_engine_steps")
                if j:
                    totals["false"] += int(j["false"])
                    totals["confirmed"] += int(j["confirmed"])
                    totals["unjudged"] += int(not j["judged"])
                    totals["dropped_pairs"] += j["dropped_pairs"]
                sink_roots.write(json.dumps({
                    "schema": SCHEMA_ROOT, "shard": shard, "game": game,
                    "engine_seed": engine_seed, "seat": a, "step": root["step"], "class": cls,
                    "kickoff_turn": root["kickoff_turn"],
                    "searchable": counts["searchable"][cls], "kept": len(kept[cls]),
                    "flags": list(root["flags"]),
                    "support": [int(t) for t in root["support"]],
                    "a0": list(root["a0"]), "a0_logprob": float(np.round(root["a0_logprob"], 9)),
                    **rec}) + "\n")
    finally:
        for cls in C.SCOPE:
            for root in kept[cls]:
                root["clone"].close()
    sink_roots.flush()
    for step in g["other"]:
        sink_other.write(json.dumps({"schema": SCHEMA_OTHER, "shard": shard, "game": game,
                                     "engine_seed": engine_seed, "seat": a, "step": step,
                                     "searchable": counts["other_searchable"],
                                     "kept": len(g["other"])}) + "\n")
    sink_other.flush()
    return {"schema": SCHEMA_GAME, "shard": shard, "game": game, "engine_seed": engine_seed,
            "seat": a, "sampling_seeds": g["seeds"], "team_ids": g["team_ids"],
            "score": g["score"], "steps": g["steps"], "final_status": g["final_status"],
            "natural": True, "integrity": g["integrity"], "final_digest": g["final_digest"],
            "obs_sha256": g["obs_sha256"], "trail_sha256": C.trail_sha256(g["trail"]),
            "trail": g["trail"], "counts": counts,
            "kept": {c: len(kept[c]) for c in C.SCOPE}, "other_kept": len(g["other"]),
            "root_lines": totals["roots"], "deviation_roots": totals["deviation"],
            "cap_rejected_roots": totals["cap_rejected"], "false_labels": totals["false"],
            "confirmed_labels": totals["confirmed"], "unjudged_labels": totals["unjudged"],
            "dropped_judgment_pairs": totals["dropped_pairs"],
            "kickoff_turn_roots": totals["kickoff_turn_roots"],
            "rollout_engine_steps": totals["engine_steps"],
            "seconds": {"play": round(t_play, 2), "total": round(time.time() - t0, 2)}}


# ---- the run -----------------------------------------------------------------------------
def settle(args):
    plan, args.plan_sha256 = C.load_plan(args.plan, args.expect_sha256)
    shards = {s["name"]: s for s in plan["shards"]}
    if args.shard not in shards:
        raise SystemExit(f"the plan has no shard {args.shard!r}; it has {sorted(shards)}")
    args.first_game, args.games = int(shards[args.shard]["first_game"]), \
        int(shards[args.shard]["games"])
    args.checkpoint_sha256 = C.sha256_file(args.checkpoint)
    if args.checkpoint_sha256 != plan["checkpoint"]["sha256"]:
        raise SystemExit(f"{args.checkpoint} is not the plan's {plan['checkpoint']['name']}")
    with open(os.path.join(os.path.abspath(args.harness), "SOURCE_COMMIT")) as f:
        args.harness_commit = f.read().strip()
    if args.harness_commit != plan["harness_commit"]:
        raise SystemExit(f"the harness export is at {args.harness_commit}, the plan pins "
                         f"{plan['harness_commit']}")
    if list(INTEGRITY_CHECKS) != plan["integrity_checks"]:
        raise SystemExit("this tool's integrity checks are not the plan's list")
    args.settings = {key: plan["label"][key] for key in SETTING_KEYS}
    args.plan_obj = plan
    return args


def cmd_worker(args):
    args = settle(args)
    lab = Labeler(args.harness, args.checkpoint, args.settings)
    if lab.hx.manifest["sha256"] != args.plan_obj["reward_manifest_sha256"]:
        raise SystemExit("the reward manifest is not the plan's")
    for key in ("gamma", "max_rollout_steps"):
        have = {"gamma": lab.S.GAMMA, "max_rollout_steps": lab.S.MAX_ROLLOUT_STEPS}[key]
        if have != args.plan_obj["label"][key]:
            raise SystemExit(f"the harness's {key} is {have}, the plan says "
                             f"{args.plan_obj['label'][key]}")
    if tuple(lab.S.SCOPE) != tuple(args.plan_obj["label"]["scope"]):
        raise SystemExit("the harness's search scope is not the plan's")
    tag = f"w{args.index}"
    games = [args.first_game + g for g in range(args.games) if g % args.of == args.index]
    with open(os.path.join(args.out_dir, f"roots.{tag}.jsonl"), "x") as sink_roots, \
            open(os.path.join(args.out_dir, f"other.{tag}.jsonl"), "x") as sink_other, \
            open(os.path.join(args.out_dir, f"games.{tag}.jsonl"), "x") as sink_games:
        if args.index == 0:
            with open(os.path.join(args.out_dir, "meta.w0.json"), "w") as f:
                json.dump({"library_sha256": lab.hx.library_sha256,
                           "reward_manifest": lab.hx.manifest["name"],
                           "reward_manifest_sha256": lab.hx.manifest["sha256"],
                           "reward_clip_threshold": lab.hx.reward_threshold,
                           "search_gamma": lab.S.GAMMA,
                           "max_rollout_steps": lab.S.MAX_ROLLOUT_STEPS,
                           "scope": list(lab.S.SCOPE), **lab.hx.versions()}, f, indent=1)
        for game in games:
            try:
                record = run_game(lab, game, args.shard, sink_roots, sink_other)
            except C.IntegrityError as exc:
                print(f"INTEGRITY: {exc}", flush=True)
                return 2
            sink_games.write(json.dumps(record) + "\n")
            sink_games.flush()
            print(f"{tag} game {game}: {record['root_lines']} roots, "
                  f"{record['seconds']['total']} s", flush=True)
    lab.close()
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
        json.dump({"shard": args.shard, "worker_exit_codes": codes, "reasons": reasons,
                   "seconds": round(time.time() - started, 1)}, f, indent=1)
    raise SystemExit(f"{args.shard}: NOT COMPLETE, worker exit codes {codes}: "
                     + ("; ".join(reasons) or f"see worker*.log in {args.out_dir}"))


def cmd_run(args):
    args = settle(args)
    os.makedirs(args.out_dir, exist_ok=True)
    for name in ("roots.jsonl", "games.jsonl", "other.jsonl", "COMPLETE.json", "FAILED.json",
                 "roots.w0.jsonl"):
        if os.path.exists(os.path.join(args.out_dir, name)):
            raise SystemExit(f"{args.out_dir} already holds {name}; choose a fresh --out-dir")
    processes = max(1, min(int(args.processes), args.games))
    started = time.time()
    children = []
    for index in range(processes):
        log = open(os.path.join(args.out_dir, f"worker{index}.log"), "w")
        argv = [sys.executable, os.path.abspath(__file__), "worker", "--index", str(index),
                "--of", str(processes), "--harness", args.harness, "--plan", args.plan,
                "--expect-sha256", args.expect_sha256, "--shard", args.shard,
                "--checkpoint", args.checkpoint, "--out-dir", args.out_dir]
        children.append((subprocess.Popen(
            argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            env={**os.environ, "OMP_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1"}), log))
    game_files = [os.path.join(args.out_dir, f"games.w{i}.jsonl") for i in range(processes)]
    last, shown = 0.0, -1
    while True:
        codes = [child.poll() for child, _ in children]
        if any(code not in (None, 0) for code in codes):
            fail_run(args, children, codes, started)            # fail fast: stop the rest
        if all(code == 0 for code in codes):
            break
        time.sleep(1.0)
        if time.time() - last >= args.heartbeat:
            last = time.time()
            done = count_lines(game_files)
            # A line only when a game has finished since the last one: a runner that
            # watches this output for progress then sees a hung worker as silence.
            if done != shown:
                shown = done
                print(f"{args.shard}: {done}/{args.games} games, "
                      f"{time.time() - started:.0f} s", flush=True)
    for _, log in children:
        log.close()
    merged = {}
    for kind in ("games", "roots", "other"):
        rows = []
        for i in range(processes):
            with open(os.path.join(args.out_dir, f"{kind}.w{i}.jsonl")) as f:
                rows += [json.loads(line) for line in f]
        merged[kind] = rows
    games, roots, other = merged["games"], merged["roots"], merged["other"]
    games.sort(key=lambda r: r["game"])
    roots.sort(key=lambda r: (r["game"], C.SCOPE.index(r["class"]), r["step"]))
    other.sort(key=lambda r: (r["game"], r["step"]))
    if [g["game"] for g in games] != list(range(args.first_game, args.first_game + args.games)):
        raise SystemExit("the workers did not return every game exactly once")
    for kind, rows in (("games", games), ("roots", roots), ("other", other)):
        with open(os.path.join(args.out_dir, f"{kind}.jsonl"), "w") as f:
            f.writelines(json.dumps(r) + "\n" for r in rows)
    with open(os.path.join(args.out_dir, "meta.w0.json")) as f:
        meta = json.load(f)
    seconds = time.time() - started
    total = lambda key: sum(g[key] for g in games)  # noqa: E731
    complete = {
        "schema": SCHEMA_COMPLETE, "shard": args.shard, "plan_sha256": args.plan_sha256,
        "checkpoint": args.plan_obj["checkpoint"]["name"],
        "checkpoint_sha256": args.checkpoint_sha256, "harness_commit": args.harness_commit,
        "tool_sha256": C.tool_sha256(), **meta, "settings": args.settings,
        "integrity_checks": list(INTEGRITY_CHECKS), "first_game": args.first_game,
        "games": len(games), "natural_games": sum(bool(g["natural"]) for g in games),
        "error_rollouts": 0, "root_lines": len(roots), "other_lines": len(other),
        "deviation_roots": total("deviation_roots"),
        "cap_rejected_roots": total("cap_rejected_roots"),
        "false_labels": total("false_labels"), "confirmed_labels": total("confirmed_labels"),
        "unjudged_labels": total("unjudged_labels"),
        "dropped_judgment_pairs": total("dropped_judgment_pairs"),
        "kickoff_turn_roots": total("kickoff_turn_roots"),
        "games_with_kickoff_turn_decision": sum(
            1 for g in games if sum(g["counts"]["kickoff_turn"].values())),
        "rollout_engine_steps": total("rollout_engine_steps"),
        "processes": processes, "wall_seconds": round(seconds, 1),
        "play_seconds": round(sum(g["seconds"]["play"] for g in games), 1),
        "worker_seconds": round(sum(g["seconds"]["total"] for g in games), 1),
        "roots_sha256": C.sha256_file(os.path.join(args.out_dir, "roots.jsonl")),
        "games_sha256": C.sha256_file(os.path.join(args.out_dir, "games.jsonl")),
        "other_sha256": C.sha256_file(os.path.join(args.out_dir, "other.jsonl"))}
    with open(os.path.join(args.out_dir, "COMPLETE.json"), "w") as f:
        json.dump(complete, f, indent=1)
    with open(args.plan, "rb") as src, open(os.path.join(args.out_dir, "plan.json"), "wb") as dst:
        dst.write(src.read())
    names = ("roots.jsonl", "games.jsonl", "other.jsonl", "COMPLETE.json", "plan.json")
    with open(os.path.join(args.out_dir, "SHA256SUMS"), "w") as f:
        for name in names:
            f.write(f"{C.sha256_file(os.path.join(args.out_dir, name))}  {name}\n")
    print(f"{args.shard}: done, {len(games)} games, {len(roots)} roots, "
          f"{complete['deviation_roots']} deviation roots, {complete['cap_rejected_roots']} cap "
          f"rejections, {complete['kickoff_turn_roots']} kick-off turn roots, "
          f"{seconds:.0f} s wall on {processes} process(es)", flush=True)
    return 0


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="command", required=True)
    for name, func in (("run", cmd_run), ("worker", cmd_worker)):
        sp = sub.add_parser(name)
        sp.add_argument("--harness", required=True, help="an export of the harness at its pin")
        sp.add_argument("--plan", required=True)
        sp.add_argument("--expect-sha256", required=True)
        sp.add_argument("--shard", required=True)
        sp.add_argument("--checkpoint", required=True)
        sp.add_argument("--out-dir", required=True)
        if name == "run":
            sp.add_argument("--processes", type=int, default=1)
            sp.add_argument("--heartbeat", type=float, default=60.0)
        else:
            sp.add_argument("--index", type=int, required=True)
            sp.add_argument("--of", type=int, required=True)
        sp.set_defaults(func=func)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
