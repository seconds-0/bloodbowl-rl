#!/usr/bin/env python3
"""Search distillation, recipe R1: fine-tune the policy rows of the output layer
toward the search seat's labels, and write each arm back as a blob the harness plays.

Trained: decoder.decoder.weight (454 x 512). Frozen: the encoder, the three
MinGRU layers, the value row, every bias (the native blob has none). So the
decoder's input h at a decision does not depend on the trained weights, the
dataset's cached h is exact for every arm, and the loss is convex.

The loss, over the loss decisions of the training games with their weights w:

  [ lambda * sum over deviation roots of w * (-log p(label))
    + sum over the other loss decisions of w * KL(p0 || p) ] / (sum of w)

It is a deviation cross-entropy plus a preservation KL to the original policy.
It is not maximum-likelihood cloning of the seat: at a screened root where the
seat does not deviate it keeps the sampled a0, and this loss clones all of p0.
p is the exact joint distribution over the masked support (type, argument
given type, square given both) and the KL is the sum over the support's tuples
of p0 * (log p0 - log p), never three marginal KLs.

Each arm (one lambda) takes the plan's fixed number of Adam steps over fixed
chunks of the training set and keeps its last step. There is no stop rule.
An arm is written as checkpoints/<arm>/0000002999975936.bin with a lineage
sidecar the harness accepts and the trainer's lineage tool refuses, and is
then checked: it differs from the original blob only in the policy rows of the
decoder, and the harness loads it and returns the trained weights.

This tool opens train.pt and validation.pt of the dataset directory and
nothing else. It refuses a file that holds another split.

  distill_finetune.py --harness EXPORT --plan PLAN.json --expect-sha256 H \\
      --checkpoint BLOB --dataset DIR --out-dir DIR [--arm NAME ...]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402

SCHEMA = "search-distill-finetune-v1"
CURVE_POINTS = 12
CACHE_TUPLES = 20_000_000
HIDDEN, LAYERS = 512, 3


def decoder_span(hx):
    """(first, last) float index of the decoder's policy rows in the flat blob, and
    the value row's, from the converter's own layout."""
    sys.path.insert(0, hx.root)
    from training.convert_checkpoint import cuda_layout
    entries, _ = cuda_layout(HIDDEN, LAYERS, hx.E.OBS_SIZE, hx.E.ACT_SIZES)
    shape, offset = next((s, o) for n, s, o in entries if n == "decoder.weight")
    rows = sum(hx.E.ACT_SIZES)
    return (offset, offset + rows * HIDDEN - 1), (offset + rows * HIDDEN,
                                                  offset + (rows + 1) * HIDDEN - 1)


def write_blob(hx, base_blob, weight, directory, sidecar):
    """Write the original blob with its decoder policy rows replaced by `weight`
    (a float32 (454, 512) tensor), and its sidecar. Returns (blob path, blob
    sha256, sidecar sha256, floats changed) after checking what was written."""
    import torch
    from training.convert_checkpoint import cuda_to_torch, torch_to_cuda
    base = np.fromfile(base_blob, dtype="<f4")
    sd = cuda_to_torch(base, HIDDEN, LAYERS, hx.E.OBS_SIZE, hx.E.ACT_SIZES)
    if any(float(v.abs().max()) != 0.0 for key, v in sd.items() if key.endswith("bias")):
        raise SystemExit("the original blob converts with a bias that is not zero")
    if weight.dtype != torch.float32 or tuple(weight.shape) != tuple(sd["decoder.decoder.weight"].shape):
        raise SystemExit("the trained weight is not a float32 (454, 512) tensor")
    sd["decoder.decoder.weight"] = weight.clone()
    blob = torch_to_cuda(sd, HIDDEN, LAYERS, hx.E.OBS_SIZE, hx.E.ACT_SIZES)
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, C.BLOB)
    if os.path.exists(path):
        raise SystemExit(f"{path} exists; choose a fresh --out-dir")
    blob.tofile(path)
    digest = C.sha256_file(path)
    (first, last), (v_first, v_last) = decoder_span(hx)
    differ = np.flatnonzero(blob != base)
    if differ.size and (differ.min() < first or differ.max() > last):
        raise SystemExit("the written blob differs from the original outside the decoder's "
                         "policy rows")
    if os.path.getsize(path) != os.path.getsize(base_blob):
        raise SystemExit("the written blob is not the original's size")
    full = {"schema_version": 1,
            "checkpoint": {"bytes": os.path.getsize(path), "sha256": digest},
            "compatibility": {"action_abi": "exact-joint-v1", "observation_abi": "obs-v6",
                              "observation_version": 6, "policy_expansion_factor": 1,
                              "policy_hidden_size": HIDDEN, "policy_num_layers": LAYERS},
            **sidecar}
    with open(path + ".lineage.json", "w") as f:
        json.dump(full, f, sort_keys=True, separators=(",", ":"))
    policy, provenance = hx.load_policy(path)
    if provenance["checkpoint_sha256"] != digest or not torch.equal(
            policy.decoder.decoder.weight.detach(), weight):
        raise SystemExit("the harness does not load the written blob as trained")
    return path, digest, C.sha256_file(path + ".lineage.json"), int(differ.size)


def stats(data, scored):
    """Fit numbers of one dataset file under one weight matrix."""
    w, dev = data["weight"], data["label"] >= 0
    return {"label_probability": C.weighted_mean(scored["p_label"][dev], w[dev]),
            "label_probability_ge_half": C.weighted_mean(scored["p_label"][dev] >= 0.5, w[dev]),
            "tv_other": C.weighted_mean(scored["tv"][~dev], w[~dev]),
            "top_changed_other": C.weighted_mean(scored["changed"][~dev], w[~dev]),
            "deviation_roots": int(dev.sum()), "other_decisions": int((~dev).sum())}


def train(train_data, w0, lam, steps, lr, chunk, seed, log=None):
    """`steps` Adam steps on the declared loss. Returns (float32 weight, curve)."""
    import torch
    n = len(train_data["a0"])
    rng = np.random.default_rng(int(seed))
    order = rng.permutation(n)
    w0d = w0.double()
    parts = [np.sort(order[a:a + int(chunk)]) for a in range(0, n, int(chunk))]
    # A built chunk holds every tuple of its supports. They are kept while the
    # whole training set has at most CACHE_TUPLES of them, and rebuilt at each
    # use beyond that, which trades time for memory at the registered size.
    cache = int(train_data["support_ptr"][-1]) <= CACHE_TUPLES
    built = {}

    def chunk_of(i):
        if i in built:
            return built[i]
        index = parts[i]
        joint = C.Joint(C.supports_of(train_data, index))
        h = train_data["h"][index].double()
        with torch.no_grad():
            lp0 = joint.logp(h @ w0d.T)
        label_at = joint.index_of(train_data["label"][index])
        c = {"joint": joint, "h": h, "lp0": lp0, "p0": torch.exp(lp0),
             "label_at": torch.from_numpy(np.maximum(label_at, 0)),
             "dev": torch.from_numpy(label_at >= 0),
             "w": torch.from_numpy(train_data["weight"][index])}
        if cache:
            built[i] = c
        return c

    w = w0d.clone().requires_grad_(True)
    opt = torch.optim.Adam([w], lr=float(lr))
    curve, started = [], time.time()
    every = max(int(steps) // CURVE_POINTS, 1)
    sequence = []
    for step in range(int(steps) + 1):
        if not sequence:
            sequence = list(rng.permutation(len(parts)))
        c = chunk_of(int(sequence.pop()))
        lp = c["joint"].logp(c["h"] @ w.T)
        ce = -lp[c["label_at"]]
        kl = c["joint"].per_decision_sum(c["p0"] * (c["lp0"] - lp))
        loss = (float(lam) * (c["w"] * ce)[c["dev"]].sum()
                + (c["w"] * kl)[~c["dev"]].sum()) / c["w"].sum()
        if not bool(torch.isfinite(loss)):
            raise SystemExit(f"the loss is not finite at step {step}")
        if step % every == 0 or step == int(steps):
            point = {"step": step, "chunk_loss": float(loss.detach()),
                     "delta_norm": float((w.detach() - w0d).norm()),
                     "seconds": round(time.time() - started, 1)}
            curve.append(point)
            if log:
                log(point)
        if step == int(steps):
            break
        opt.zero_grad()
        loss.backward()
        opt.step()
    return w.detach().float(), curve, len(parts)


def run(args):
    plan, plan_sha = C.load_plan(args.plan, args.expect_sha256)
    hx = C.Harness(args.harness)
    if hx.commit != plan["harness_commit"]:
        raise SystemExit(f"the harness export is at {hx.commit}, the plan pins "
                         f"{plan['harness_commit']}")
    base_sha = C.sha256_file(args.checkpoint)
    if base_sha != plan["checkpoint"]["sha256"]:
        raise SystemExit(f"{args.checkpoint} is not the plan's checkpoint")
    base_sidecar = C.sha256_file(args.checkpoint + ".lineage.json")
    if base_sidecar != plan["checkpoint"]["sidecar_sha256"]:
        raise SystemExit(f"{args.checkpoint}.lineage.json is not the plan's sidecar")
    ft = plan["finetune"]
    arms = args.arm or sorted(ft["arms"], key=lambda name: ft["arms"][name])
    unknown = [a for a in arms if a not in ft["arms"]]
    if unknown:
        raise SystemExit(f"not arms of this plan: {unknown}")
    with open(os.path.join(args.dataset, "DATASET.json")) as f:
        dataset = json.load(f)
    if dataset["plan_sha256"] != plan_sha:
        raise SystemExit("the dataset was built under another plan")
    files = {}
    for split in ("train", "validation"):
        path = os.path.join(args.dataset, dataset["files"][split]["path"])
        if C.sha256_file(path) != dataset["files"][split]["sha256"]:
            raise SystemExit(f"{path} is not the file DATASET.json recorded")
        files[split] = C.open_split(path, split)
    policy, _ = hx.load_policy(args.checkpoint)
    w0 = policy.decoder.decoder.weight.detach().clone()
    os.makedirs(args.out_dir, exist_ok=True)
    summary_path = os.path.join(args.out_dir, "FINETUNE.json")
    summary = {"schema": SCHEMA, "plan_sha256": plan_sha, "recipe": ft["recipe"],
               "base_checkpoint_sha256": base_sha, "dataset": dataset["files"],
               "settings": {k: ft[k] for k in ("learning_rate", "steps", "chunk", "seed")},
               "arms": {}, **hx.versions()}
    if os.path.exists(summary_path):
        with open(summary_path) as f:
            summary = json.load(f)
        if summary.get("plan_sha256") != plan_sha:
            raise SystemExit(f"{summary_path} belongs to another plan")
    for arm in arms:
        if arm in summary["arms"]:
            raise SystemExit(f"arm {arm} is already in {summary_path}; choose a fresh --out-dir")
        lam = float(ft["arms"][arm])
        print(f"{arm}: lambda {lam}, {ft['steps']} steps at {ft['learning_rate']}", flush=True)
        t0 = time.time()
        weight, curve, chunks = train(
            files["train"], w0, lam, ft["steps"], ft["learning_rate"], ft["chunk"], ft["seed"],
            log=lambda p: print(f"  {arm} {json.dumps(p)}", flush=True))
        sidecar = {
            "ancestry": {"initialization": "offline-distill", "eligible": False,
                         "qualification_only": True, "mode": "play_harness_offline_distill",
                         "parent_checkpoint_sha256": base_sha,
                         "parent_lineage_sha256": base_sidecar,
                         "valid_under_masks": list(plan["label"]["masks"])},
            "producer": {"plan_sha256": plan_sha, "recipe": ft["recipe"], "arm": arm,
                         "lambda": lam, "learning_rate": ft["learning_rate"],
                         "steps": ft["steps"], "chunk": ft["chunk"], "seed": ft["seed"],
                         "train_file_sha256": dataset["files"]["train"]["sha256"],
                         "tool_sha256": plan["tool_sha256"], "torch": hx.torch.__version__}}
        path, digest, sidecar_sha, changed = write_blob(
            hx, args.checkpoint, weight, os.path.join(args.out_dir, "checkpoints", arm), sidecar)
        result = {"lambda": lam, "blob": os.path.relpath(path, args.out_dir),
                  "blob_sha256": digest, "sidecar_sha256": sidecar_sha,
                  "floats_changed": changed, "chunks": chunks, "curve": curve,
                  "train_seconds": round(time.time() - t0, 1)}
        for split in ("train", "validation"):
            scored = C.score(files[split], w0, weight)
            result[split] = stats(files[split], scored)
            if split == "validation":
                result["selection"] = C.selection_score(files[split], scored,
                                                        ft["selection"]["price"])
        summary["arms"][arm] = result
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=1)
        print(f"{arm}: blob {digest[:12]} sidecar {sidecar_sha[:12]}; training label "
              f"probability {result['train']['label_probability']:.3f}, training change "
              f"elsewhere {result['train']['tv_other']:.4f}; {result['train_seconds']} s",
              flush=True)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--checkpoint", required=True, help="the plan's original checkpoint blob")
    ap.add_argument("--dataset", required=True, help="the dataset tool's output directory")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--arm", action="append", default=[],
                    help="train only this arm (default: every arm of the plan)")
    return run(ap.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
