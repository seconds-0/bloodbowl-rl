#!/usr/bin/env python3
"""Search distillation: build the fine-tune's dataset from accepted label shards.

For every game of the accepted shards that is not in the reserve group:
  1. the stored action trail is replayed through a fresh engine on the game's
     seed; the final digest, the score and the sha256 of both observation rows
     must equal the game record's (so the states are the ones the label tool
     saw, on whatever machine it ran);
  2. the original checkpoint is run over seat A's observation row from the
     first step of the match, which is how the seat came by its recurrent
     state; at every screened root and every sampled out-of-scope decision the
     decoder's input h (512 numbers) and the logits are taken;
  3. at every root the masked support and the decision class are rebuilt from
     the replayed engine and must equal the record's (a recorded support is
     never trusted); then the recomputed a0 and candidate list must be the
     recorded ones and a0's log-probability must agree to 1e-3; at every
     out-of-scope decision the masked support is rebuilt from the replay too.
A loss decision is a screened root that is not a cap rejection, or a sampled
out-of-scope decision. Unscreened in-scope decisions are never in the dataset.

The split is by game: group = ((engine seed - seed0) // 2) % 10; 0 to 6 train,
7 validation, 8 test, 9 reserve. train.pt and validation.pt are written beside
DATASET.json; the test split goes to locked/test.pt, which only the evaluation
tool opens, once, with the selection's hash. The reserve group's games pass
shard acceptance like any other (they are generated and integrity-checked);
here they are counted and nothing more: no label of theirs is counted, no
feature is computed, and this tool has no option that writes them.
DATASET.json records which shards the dataset holds, so that a later step can
refuse a dataset that is not the whole plan.

  distill_dataset.py --harness EXPORT --plan PLAN.json --expect-sha256 H \\
      --checkpoint BLOB --shard-dir NAME=DIR [...] --out-dir DIR
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402
import distill_accept as A  # noqa: E402

SCHEMA = "search-distill-dataset-v1"
WRITTEN = ("train", "validation", "test")
LOGPROB_TOLERANCE = 1e-3
KIND_ROOT, KIND_OTHER = 0, 1


def split_path(out_dir, split):
    """Where a split's file lives. The reserve split has no path: it is never written."""
    if split not in WRITTEN:
        raise SystemExit(f"the {split} split is never written by this tool")
    if split == "test":
        return os.path.join(out_dir, "locked", "test.pt")
    return os.path.join(out_dir, f"{split}.pt")


class Features:
    """The original network over seat A's observation rows, several games in
    lockstep. forward_eval is called as the seats call it; the decoder's input
    is taken by a hook on the decoder, so h is exactly what produced the logits."""

    def __init__(self, hx, policy):
        self.hx, self.policy, self.torch = hx, policy, hx.torch
        self._h = None
        policy.decoder.decoder.register_forward_hook(self._hook)

    def _hook(self, module, inputs, output):
        self._h = inputs[0].detach()

    def run(self, rows, wanted):
        """rows: one (steps, obs) uint8 array per game. wanted: per game the sorted
        engine steps to keep. Returns per game {step: (h, logits)} as float32 arrays."""
        torch = self.torch
        games = len(rows)
        length = np.array([r.shape[0] for r in rows])
        state = self.policy.initial_state(games)
        out = [dict() for _ in range(games)]
        want = [set(w) for w in wanted]
        for t in range(int(length.max())):
            live = length > t
            obs = np.stack([rows[g][min(t, length[g] - 1)] for g in range(games)])
            logits, _, new_state = self.policy.forward_eval(torch.from_numpy(obs), state)
            state = torch.where(torch.from_numpy(live).reshape(1, games, 1), new_state, state)
            for g in range(games):
                if live[g] and t in want[g]:
                    out[g][t] = (self._h[g].numpy().copy(), logits[g].numpy().copy())
        return out


def build(args):
    plan, plan_sha = C.load_plan(args.plan, args.expect_sha256)
    shard_dirs = dict(item.split("=", 1) for item in args.shard_dir)
    problems, summaries = A.accept(plan, plan_sha, shard_dirs)
    if problems:
        raise SystemExit("not accepted, nothing built:\n  " + "\n  ".join(problems))
    hx = C.Harness(args.harness)
    if hx.commit != plan["harness_commit"]:
        raise SystemExit(f"the harness export is at {hx.commit}, the plan pins "
                         f"{plan['harness_commit']}")
    if A.STATUS_MATCH_OVER != hx.E.STATUS_MATCH_OVER:
        raise SystemExit("the acceptance tool's match-over status is not the engine's")
    if C.sha256_file(args.checkpoint) != plan["checkpoint"]["sha256"]:
        raise SystemExit(f"{args.checkpoint} is not the plan's checkpoint")
    policy, _ = hx.load_policy(args.checkpoint)
    feats = Features(hx, policy)
    E, S = hx.E, hx.S
    restrict_support = hx.P.restrict_support
    label = plan["label"]
    seed0, masks, k = int(label["seed0"]), tuple(label["masks"]), int(label["candidates"])
    os.makedirs(os.path.join(args.out_dir, "locked"), exist_ok=True)
    for split in WRITTEN:
        if os.path.exists(split_path(args.out_dir, split)):
            raise SystemExit(f"{split_path(args.out_dir, split)} exists; choose a fresh --out-dir")
    games, roots, other = [], {}, {}
    for shard, directory in shard_dirs.items():
        games += A.read_jsonl(os.path.join(directory, "games.jsonl"))
        for r in A.read_jsonl(os.path.join(directory, "roots.jsonl")):
            roots.setdefault(r["game"], []).append(r)
        for o in A.read_jsonl(os.path.join(directory, "other.jsonl")):
            other.setdefault(o["game"], []).append(o)
    games.sort(key=lambda g: g["game"])
    if len({g["game"] for g in games}) != len(games):
        raise SystemExit("a game appears in two shards")
    cols = {s: {key: [] for key in (
        "h", "support", "a0", "label", "weight", "kind", "cls", "kickoff", "game",
        "engine_seed", "step", "fresh_gain", "fresh_se", "judged", "false", "confirmed",
        "gain", "p0_a0", "p0_label", "p0_top")} for s in WRITTEN}
    counts = {s: {"games": 0, "roots": 0, "deviation_roots": 0, "other": 0,
                  "cap_rejected_roots": 0, "kickoff_turn_roots": 0} for s in WRITTEN}
    # The reserve group: how many games and records it holds, and nothing about its labels.
    counts["reserve"] = {"games": 0, "roots": 0, "other": 0}
    max_dlogp, reordered, rebuilt_roots, started = 0.0, 0, 0, time.time()
    todo = [g for g in games if C.split_of(g["engine_seed"], seed0) != "reserve"]
    for g in games:
        s = C.split_of(g["engine_seed"], seed0)
        counts[s]["games"] += 1
        if s == "reserve":
            counts[s]["roots"] += len(roots.get(g["game"], []))
            counts[s]["other"] += len(other.get(g["game"], []))
    for at in range(0, len(todo), args.batch_games):
        batch = todo[at:at + args.batch_games]
        rows, wanted, supports_at = [], [], []
        for g in batch:
            a = g["seat"]
            want = sorted({r["step"] for r in roots.get(g["game"], [])}
                          | {o["step"] for o in other.get(g["game"], [])})
            other_steps = {o["step"] for o in other.get(g["game"], [])}
            root_at = {r["step"]: r for r in roots.get(g["game"], [])}
            obs_rows, keep, declared = [], {}, False
            gen = C.replay(hx, g, want_rows=(a,))
            while True:
                try:
                    step, team, obs, supports = next(gen)
                except StopIteration as stop:
                    end = stop.value
                    break
                obs_rows.append(obs[a])
                if step in root_at:
                    # The record's support is not trusted: rebuild it and the class.
                    r = root_at[step]
                    support, _ = restrict_support(supports[a], masks, declared)
                    cls = S.decision_class({int(t) & 1023 for t in support}, declared)
                    if team != a or cls != r["class"] or bool(r["flags"][0]) != declared or \
                            sorted(int(t) for t in support) != sorted(int(t) for t in r["support"]):
                        raise C.IntegrityError(
                            f"game {g['game']} step {step}: the root's recorded class or masked "
                            "support is not the one the replayed engine gives")
                    keep[step] = (np.asarray(support, dtype=np.int64), cls)
                    rebuilt_roots += 1
                if step in other_steps:
                    support, _ = restrict_support(supports[a], masks, declared)
                    cls = S.decision_class({int(t) & 1023 for t in support}, declared)
                    if team != a or cls in C.SCOPE or len(support) < 2:
                        raise C.IntegrityError(
                            f"game {g['game']} step {step}: not an out-of-scope multi-action "
                            "decision of seat A on replay")
                    keep[step] = (np.asarray(support, dtype=np.int64), cls)
                if team == a:
                    declared = g["trail"][step][1] == E.A["DECLARE"]
            for key in ("obs_sha256", "final_digest", "score"):
                if end[key] != g[key]:
                    raise C.IntegrityError(f"game {g['game']} (seed {g['engine_seed']}): the "
                                           f"replay's {key} is not the record's")
            rows.append(np.stack(obs_rows))
            wanted.append(want)
            supports_at.append(keep)
        got = feats.run(rows, wanted)
        for g, at_steps, keep in zip(batch, got, supports_at):
            split = C.split_of(g["engine_seed"], seed0)
            col, cnt = cols[split], counts[split]

            def add(step, kind, cls, support, a0, lab, weight, r=None, p0=None):
                h, _ = at_steps[step]
                j = (r or {}).get("judgment") or {}
                col["h"].append(h)
                col["support"].append(np.unique(np.asarray(support, dtype=np.int64)))
                col["a0"].append(E.pack_tuple(*a0))
                col["label"].append(-1 if lab is None else E.pack_tuple(*lab))
                col["weight"].append(float(weight))
                col["kind"].append(kind)
                col["cls"].append(C.CLASS_CODES[cls])
                col["kickoff"].append(bool((r or {}).get("kickoff_turn", False)))
                col["game"].append(g["game"])
                col["engine_seed"].append(g["engine_seed"])
                col["step"].append(step)
                col["fresh_gain"].append(j.get("fresh_gain") if j.get("fresh_gain") is not None
                                         else math.nan)
                col["fresh_se"].append(j.get("fresh_se") if j.get("fresh_se") is not None
                                       else math.nan)
                col["judged"].append(bool(j.get("judged", False)))
                col["false"].append(bool(j.get("false", False)))
                col["confirmed"].append(bool(j.get("confirmed", False)))
                col["gain"].append(float((r or {}).get("gain") or math.nan))
                col["p0_a0"].append(p0[0])
                col["p0_label"].append(p0[1])
                col["p0_top"].append(p0[2])

            for r in roots.get(g["game"], []):
                cnt["roots"] += 1
                cnt["kickoff_turn_roots"] += bool(r["kickoff_turn"])
                if r["cap_rejected"]:
                    cnt["cap_rejected_roots"] += 1
                    continue
                _, logits = at_steps[r["step"]]
                support, _ = keep[r["step"]]                 # rebuilt on replay, checked above
                tuples, logps = S.joint_log_probabilities(logits, support, 1.0)
                a0 = E.pack_tuple(*r["a0"])
                order = S.candidate_order(tuples, a0, k)
                cands = [list(E.unpack_tuple(tuples[i])) for i in order]
                where = f"game {g['game']} step {r['step']}"
                if cands != [list(t) for t in r["tuples"]]:
                    # Another machine, or a batched forward, rounds the logits
                    # differently, and two alternatives within the tolerance of
                    # each other can change places. Anything else is an error.
                    at_tuple = {int(t): float(lp) for t, lp in zip(tuples, logps)}
                    recorded = [E.pack_tuple(*t) for t in r["tuples"]]
                    floor = min(float(logps[i]) for i in order[1:])
                    if recorded[0] != a0 or len(recorded) != len(cands) or any(
                            t not in at_tuple or at_tuple[t] < floor - LOGPROB_TOLERANCE
                            for t in recorded[1:]):
                        raise C.IntegrityError(f"{where}: the recomputed candidates are not "
                                               "the recorded ones")
                    reordered += 1
                dlogp = abs(float(logps[order[0]]) - float(r["a0_logprob"]))
                # the recorded value is the log of a float32 probability: compare where it is finite
                if math.isfinite(r["a0_logprob"]) and dlogp > LOGPROB_TOLERANCE:
                    raise C.IntegrityError(f"{where}: a0's log-probability differs by {dlogp}")
                max_dlogp = max(max_dlogp, dlogp if math.isfinite(dlogp) else 0.0)
                p_label = math.nan
                if r["deviate"]:
                    cnt["deviation_roots"] += 1
                    at_label = np.flatnonzero(np.asarray(tuples) == E.pack_tuple(*r["label"]))
                    p_label = float(np.exp(logps[at_label[0]]))
                add(r["step"], KIND_ROOT, r["class"], support, r["a0"],
                    r["label"] if r["deviate"] else None, r["searchable"] / r["kept"], r,
                    (float(np.exp(logps[order[0]])), p_label, float(np.exp(logps[0]))))
            for o in other.get(g["game"], []):
                cnt["other"] += 1
                support, cls = keep[o["step"]]
                _, logits = at_steps[o["step"]]
                tuples, logps = S.joint_log_probabilities(logits, support, 1.0)
                a0 = tuple(g["trail"][o["step"]][1:])
                packed = E.pack_tuple(*a0)
                at_a0 = np.flatnonzero(np.asarray(tuples) == packed)
                if at_a0.size != 1:
                    raise C.IntegrityError(f"game {g['game']} step {o['step']}: the action "
                                           "played is not in the rebuilt support")
                add(o["step"], KIND_OTHER, cls, support, a0, None, o["searchable"] / o["kept"],
                    None, (float(np.exp(logps[at_a0[0]])), math.nan, float(np.exp(logps[0]))))
        print(f"{min(at + args.batch_games, len(todo))}/{len(todo)} games replayed, "
              f"{time.time() - started:.0f} s", flush=True)
    torch = hx.torch
    files = {}
    for split in WRITTEN:
        col = cols[split]
        n = len(col["h"])
        sizes = np.array([s.size for s in col["support"]], dtype=np.int64)
        data = {
            "schema": SCHEMA, "split": split, "plan_sha256": plan_sha,
            "checkpoint_sha256": plan["checkpoint"]["sha256"],
            "h": torch.from_numpy(np.stack(col["h"]).astype(np.float32)) if n
            else torch.zeros(0, 512),
            "support": np.concatenate(col["support"]) if n else np.zeros(0, dtype=np.int64),
            "support_ptr": np.concatenate([[0], np.cumsum(sizes)]).astype(np.int64),
        }
        for key, dtype in (("a0", np.int64), ("label", np.int64), ("weight", np.float64),
                           ("kind", np.int8), ("cls", np.int8), ("kickoff", bool),
                           ("game", np.int64), ("engine_seed", np.int64), ("step", np.int64),
                           ("fresh_gain", np.float64), ("fresh_se", np.float64),
                           ("judged", bool), ("false", bool), ("confirmed", bool),
                           ("gain", np.float64), ("p0_a0", np.float64),
                           ("p0_label", np.float64), ("p0_top", np.float64)):
            data[key] = np.asarray(col[key], dtype=dtype)
        path = split_path(args.out_dir, split)
        torch.save(data, path)
        files[split] = {"path": os.path.relpath(path, args.out_dir),
                        "sha256": C.sha256_file(path), "examples": n,
                        "labels": int((data["label"] >= 0).sum())}
    meta = {"schema": SCHEMA, "plan_sha256": plan_sha,
            "checkpoint_sha256": plan["checkpoint"]["sha256"],
            "harness_commit": hx.commit, "library_sha256": hx.library_sha256,
            "label_library_sha256": sorted({s["library_sha256"] for s in summaries}),
            "shards": {s["shard"]: {"games": s["games"], "roots": s["root_lines"]}
                       for s in summaries},
            "plan_shards": [s["name"] for s in plan["shards"]],
            "complete": sorted(s["shard"] for s in summaries)
            == sorted(s["name"] for s in plan["shards"]),
            "counts": counts, "files": files,
            "reserve": "its games and records are counted above; it is never written and "
                       "its labels are not counted",
            "roots_with_support_rebuilt_and_equal": rebuilt_roots,
            "max_a0_logprob_difference": max_dlogp, "logprob_tolerance": LOGPROB_TOLERANCE,
            "roots_with_candidates_reordered_within_tolerance": reordered,
            "batch_games": args.batch_games, "seconds": round(time.time() - started, 1),
            **hx.versions()}
    with open(os.path.join(args.out_dir, "DATASET.json"), "w") as f:
        json.dump(meta, f, indent=1)
    for summary in summaries:
        print(A.accepted_line(summary))
    print("DATASET " + "; ".join(
        f"{s}: {counts[s]['games']} games, {files[s]['examples']} loss decisions, "
        f"{files[s]['labels']} labels" for s in WRITTEN)
        + f"; reserve: {counts['reserve']['games']} games, not written; largest a0 "
          f"log-probability difference {max_dlogp:.2e}, {reordered} roots with candidates "
          f"reordered within the tolerance; {rebuilt_roots} root supports rebuilt on replay and "
          f"equal to the record's; holds {len(summaries)} of the plan's {len(plan['shards'])} "
          "shards")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--checkpoint", required=True, help="the plan's original checkpoint blob")
    ap.add_argument("--shard-dir", action="append", default=[], metavar="NAME=DIR", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--batch-games", type=int, default=32,
                    help="games run through the network in lockstep")
    return build(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
