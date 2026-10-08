#!/usr/bin/env python3
"""EXPLORATORY, not registered, decides nothing: the registered R1 loss on the
milestone 1 training games, minimised with full-batch L-BFGS instead of 2,400
Adam steps, to see what the recipe does when it is run until it stops moving.
Reads the train and validation splits (never the test split, which
open_split refuses). Writes one JSON line per check to stdout.

  converge.py --harness X --plan PLAN.json --expect-sha256 H --checkpoint CK \
      --dataset DIR --lam 16 --iterations 400 --every 25
"""
import argparse, json, os, sys, time
import numpy as np
HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
sys.path.insert(0, os.path.normpath(os.path.join(HERE, "..", "..")))
import distill_common as C
import distill_finetune as F

ap = argparse.ArgumentParser()
for name in ("harness", "plan", "expect-sha256", "checkpoint", "dataset"):
    ap.add_argument("--" + name, required=True)
ap.add_argument("--lam", type=float, required=True)
ap.add_argument("--iterations", type=int, default=400)
ap.add_argument("--every", type=int, default=25)
a = ap.parse_args()
import torch
plan, plan_sha = C.load_plan(a.plan, a.expect_sha256)
hx = C.Harness(a.harness)
meta = C.dataset_meta(a.dataset)
assert meta["plan_sha256"] == plan_sha
files = {s: C.open_split(a.dataset, s, meta) for s in ("train", "validation")}
policy, _ = hx.load_policy(a.checkpoint)
w0 = policy.decoder.decoder.weight.detach().clone()
w0d = w0.double()
train = files["train"]
n = len(train["a0"])
parts, _ = F.partition(n, plan["finetune"]["chunk"], plan["finetune"]["seed"])
chunks = [F.build_chunk(train, p, w0d) for p in parts]
total = float(train["weight"].sum())
w = w0d.clone().requires_grad_(True)
opt = torch.optim.LBFGS([w], lr=1.0, max_iter=1, history_size=20, line_search_fn="strong_wolfe")
evals = [0]

def objective():
    # the declared loss over the whole training set: sum of chunk numerators over the total weight
    return sum(F.chunk_loss(c, w, a.lam, total) for c in chunks)

def closure():
    opt.zero_grad()
    loss = objective()
    loss.backward()
    evals[0] += 1
    return loss

def report(it, loss, started):
    wf = w.detach().float()
    row = {"lambda": a.lam, "iteration": it, "objective": float(loss), "gradient_norm": float(w.grad.norm()) if w.grad is not None else None,
           "delta_norm": float((w.detach() - w0d).norm()), "evaluations": evals[0], "seconds": round(time.time() - started, 1)}
    for split in ("train", "validation"):
        st = F.stats(files[split], C.score(files[split], w0, wf))
        row[split] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in st.items()}
    print(json.dumps(row), flush=True)

started = time.time()
loss = closure()
report(0, loss.detach(), started)
for it in range(1, a.iterations + 1):
    loss = opt.step(closure)
    if it % a.every == 0 or it == a.iterations:
        closure()
        report(it, loss.detach(), started)
