#!/usr/bin/env python3
"""Diagnostic only. Recomputes, for every screened root of the non-reserve games of
accepted shards, what distill_dataset.py compares (a0's log-probability and the
candidate list) and records the differences instead of stopping at the first one.
It writes no dataset, reads no label, no gain and no judgment, and prints nothing
about them. --dtype float64 runs the network in float64 as a reference.
"""
import argparse, json, math, os, sys, time
import numpy as np

ap = argparse.ArgumentParser()
ap.add_argument("--tools", required=True)
ap.add_argument("--harness", required=True)
ap.add_argument("--plan", required=True)
ap.add_argument("--expect-sha256", required=True)
ap.add_argument("--checkpoint", required=True)
ap.add_argument("--shard-dir", action="append", default=[])
ap.add_argument("--out", required=True)
ap.add_argument("--batch-games", type=int, default=32)
ap.add_argument("--games", default="", help="comma list of game ids; default all non-reserve")
ap.add_argument("--dtype", default="float32")
ap.add_argument("--slice", default="0/1", help="i/n: every n-th game from the i-th (parallel runs)")
args = ap.parse_args()
sys.dont_write_bytecode = True
sys.path.insert(0, args.tools)
import distill_common as C
import distill_accept as A
import distill_dataset as DS

plan, plan_sha = C.load_plan(args.plan, args.expect_sha256)
shard_dirs = dict(i.split("=", 1) for i in args.shard_dir)
problems, summaries = A.accept(plan, plan_sha, shard_dirs)
assert not problems, problems
hx = C.Harness(args.harness)
assert hx.commit == plan["harness_commit"]
policy, _ = hx.load_policy(args.checkpoint)
torch = hx.torch
if args.dtype == "float64":
    policy = policy.double()
feats = DS.Features(hx, policy)
E, S = hx.E, hx.S
restrict_support = hx.P.restrict_support
label = plan["label"]
seed0, masks, k = int(label["seed0"]), tuple(label["masks"]), int(label["candidates"])
games, roots = [], {}
for shard, d in shard_dirs.items():
    games += A.read_jsonl(os.path.join(d, "games.jsonl"))
    for r in A.read_jsonl(os.path.join(d, "roots.jsonl")):
        roots.setdefault(r["game"], []).append(
            {key: r[key] for key in ("game", "step", "a0", "a0_logprob", "tuples", "cap_rejected",
                                     "kickoff_turn", "class", "flags", "support")})
games.sort(key=lambda g: g["game"])
only = {int(x) for x in args.games.split(",") if x}
todo = [g for g in games if C.split_of(g["engine_seed"], seed0) != "reserve"
        and (not only or g["game"] in only)]
_i, _n = (int(v) for v in args.slice.split("/"))
todo = todo[_i::_n]
out = open(args.out, "w")
started = time.time()
for at in range(0, len(todo), args.batch_games):
    batch = todo[at:at + args.batch_games]
    rows, wanted, supports_at = [], [], []
    for g in batch:
        a = g["seat"]
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
                support, _ = restrict_support(supports[a], masks, declared)
                keep[step] = np.asarray(support, dtype=np.int64)
            if team == a:
                declared = g["trail"][step][1] == E.A["DECLARE"]
        for key in ("obs_sha256", "final_digest", "score"):
            assert end[key] == g[key], (g["game"], key)
        rows.append(np.stack(obs_rows))
        wanted.append(sorted(root_at))
        supports_at.append(keep)
    got = feats.run(rows, wanted)
    for g, at_steps, keep in zip(batch, got, supports_at):
        for r in roots.get(g["game"], []):
            if r["cap_rejected"]:
                continue
            _, logits = at_steps[r["step"]]
            tuples, logps = S.joint_log_probabilities(logits, keep[r["step"]], 1.0)
            a0 = E.pack_tuple(*r["a0"])
            order = S.candidate_order(tuples, a0, k)
            cands = [list(E.unpack_tuple(tuples[i])) for i in order]
            same = cands == [list(t) for t in r["tuples"]]
            fatal = False
            if not same:
                at_tuple = {int(t): float(lp) for t, lp in zip(tuples, logps)}
                recorded = [E.pack_tuple(*t) for t in r["tuples"]]
                floor = min(float(logps[i]) for i in order[1:])
                fatal = bool(recorded[0] != a0 or len(recorded) != len(cands) or any(
                    t not in at_tuple or at_tuple[t] < floor - DS.LOGPROB_TOLERANCE
                    for t in recorded[1:]))
                # how far below the recomputed floor the worst recorded candidate sits
                worst = max((floor - at_tuple.get(t, -math.inf)) for t in recorded[1:]) \
                    if recorded[0] == a0 and len(recorded) == len(cands) else math.inf
            else:
                worst = 0.0
            out.write(json.dumps({
                "game": g["game"], "seed": g["engine_seed"], "step": r["step"],
                "steps_in_game": len(g["trail"]), "split": C.split_of(g["engine_seed"], seed0),
                "logp": float(logps[order[0]]), "recorded": r["a0_logprob"],
                "top_logp": float(logps[0]), "support": int(len(keep[r["step"]])),
                "kickoff": bool(r["kickoff_turn"]), "class": r["class"],
                "cands_same": same, "cands_fatal": fatal, "cands_worst": worst}) + "\n")
    print(f"{min(at + args.batch_games, len(todo))}/{len(todo)} games, {time.time()-started:.0f} s",
          flush=True)
out.close()
