#!/usr/bin/env python3
"""EXPLORATORY, not registered, decides nothing: the registered R1 fine-tune
(distill_finetune.train's loop: the same loss, chunks, seed, Adam and learning
rate) run for more than the registered 2,400 steps on the milestone 1 training
games, scored on the training and validation games every --every steps. It
reads the train and validation splits only (open_split refuses the test split).

  adam_long.py --harness X --plan PLAN.json --expect-sha256 H --checkpoint CK \
      --dataset DIR --lam 16 --steps 24000 --every 2400
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
ap.add_argument("--steps", type=int, default=24000)
ap.add_argument("--every", type=int, default=2400)
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
ft = plan["finetune"]
train = files["train"]
parts, rng = F.partition(len(train["a0"]), ft["chunk"], ft["seed"])
chunks = [F.build_chunk(train, p, w0d) for p in parts]
total = float(train["weight"].sum())
normaliser = total / len(parts)
w = w0d.clone().requires_grad_(True)
opt = torch.optim.Adam([w], lr=float(ft["learning_rate"]))
started, sequence = time.time(), []
for step in range(a.steps + 1):
    if step % a.every == 0:
        with torch.no_grad():
            full = float(sum(F.chunk_loss(c, w, a.lam, total) for c in chunks))
        wf = w.detach().float()
        row = {"lambda": a.lam, "step": step, "objective": full,
               "delta_norm": float((w.detach() - w0d).norm()), "seconds": round(time.time() - started, 1)}
        for split in ("train", "validation"):
            st = F.stats(files[split], C.score(files[split], w0, wf))
            row[split] = {k: (round(v, 5) if isinstance(v, float) else v) for k, v in st.items()}
        print(json.dumps(row), flush=True)
    if step == a.steps:
        break
    if not sequence:
        sequence = list(rng.permutation(len(parts)))
    loss = F.chunk_loss(chunks[int(sequence.pop())], w, a.lam, normaliser)
    opt.zero_grad()
    loss.backward()
    opt.step()
