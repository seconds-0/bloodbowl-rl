#!/usr/bin/env python
"""human_prior_seq.py: does carrying recurrent state over a coach's own recent
decisions help predict the next human action?

One measurement for the "zero-state i.i.d. versus short sequences" choice in
docs/human-prior-v1-2026-10-05.md. Same net, data contract, split and budget
as training/human_prior.py; the only difference is that a training sample is a
WINDOW of up to --seq-len consecutive decisions of one coach, the MinGRU state
is zero at the window start and carried through it, and the loss is taken at
every position.

A window never crosses a hole: its records are consecutive in the shard
(nothing filtered out between them, both coaches counted), in one provenance
and one re-seat segment. What a record stream cannot give is what the policy
sees in play: there the net is stepped on every engine step, the waiting
coach's included, and those observations are not in the pairs.
"""

import argparse
import json
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import bc_pretrain as bc  # noqa: E402
import human_prior as hp  # noqa: E402


def build_windows(index, replay_ids, seq_len):
    """[(replay_id, provenance, local indices)] for every admitted record."""
    windows = []
    for replay_id in replay_ids:
        for provenance in (bc.PROVENANCE_PREFIX, bc.PROVENANCE_RESEAT):
            info = (index.info(replay_id) if provenance == bc.PROVENANCE_PREFIX
                    else index.reseat_info(replay_id))
            if info is None or info.record_count == 0:
                continue
            local = np.arange(info.record_count)
            physical = local if info.rows is None else info.rows
            agent = np.empty(info.record_count, dtype=np.int64)
            segment = np.empty(info.record_count, dtype=np.int64)
            for start in range(0, info.record_count, 4096):
                recs = index.read_records(
                    replay_id, local[start:start + 4096], provenance=provenance)
                agent[start:start + 4096] = recs["agent"]
                segment[start:start + 4096] = bc.record_segment(recs)
            new_run = np.r_[True, (np.diff(physical) != 1) | (np.diff(segment) != 0)]
            run = np.cumsum(new_run)
            for r in np.unique(run):
                for a in (0, 1):
                    stream = local[(run == r) & (agent == a)]
                    for start in range(0, len(stream), seq_len):
                        windows.append((replay_id, provenance, stream[start:start + seq_len]))
    return windows


def window_batch(index, windows, seq_len):
    """Padded (W, K) record block and its validity mask."""
    dtype = bc.rec_dtype(index.obs_size, index.mask_size)
    block = np.zeros((len(windows), seq_len), dtype=dtype)
    valid = np.zeros((len(windows), seq_len), dtype=bool)
    for w, (replay_id, provenance, local) in enumerate(windows):
        block[w, :len(local)] = index.read_records(replay_id, local, provenance=provenance)
        valid[w, :len(local)] = True
    return block, valid


def run_windows(policy, block, valid, grad):
    """Per-position head log-probabilities with state carried through the window."""
    n_w, seq_len = valid.shape
    state = torch.zeros(policy.num_layers, n_w, policy.hidden)
    rows = []
    for t in range(seq_len):
        obs, mask, tgt = bc.to_tensors(block[:, t], "cpu")
        if grad:
            logits, _v, state = type(policy).forward_eval.__wrapped__(
                policy, obs, state)
        else:
            logits, _v, state = policy.forward_eval(obs, state)
        # A padded position has an all-zero mask; give it one legal entry so
        # the log-softmax is finite. It is dropped by `valid` below.
        pad = ~torch.from_numpy(valid[:, t])
        if pad.any():
            mask = mask.clone()
            for off in (0, 30, 63):
                mask[pad, off] = True
        lps = hp.head_log_probs(logits, mask)
        rows.append((lps, tgt))
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pairs-dir", required=True)
    ap.add_argument("--reseat-dir", default=None)
    ap.add_argument("--replay-ids", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--harness-root", default=hp.DEFAULT_HARNESS)
    ap.add_argument("--seq-len", type=int, default=16)
    ap.add_argument("--epochs", type=float, default=4.0)
    ap.add_argument("--batch-size", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args(argv)
    torch.set_num_threads(args.threads)
    harness_policy = hp.load_harness(args.harness_root)
    os.makedirs(args.out_dir, exist_ok=True)
    replay_ids = bc.load_replay_ids(args.replay_ids)
    index = bc.ShardIndex.from_directory(
        args.pairs_dir, replay_ids=replay_ids, cache_size=1024,
        reseat_dir=args.reseat_dir)
    train_order, holdout = hp.holdout_split(replay_ids)
    nonempty = set(index.nonempty_replay_ids)
    train_w = build_windows(index, [r for r in train_order if r in nonempty], args.seq_len)
    test_w = build_windows(index, [r for r in holdout if r in nonempty], args.seq_len)
    n_train = sum(len(w[2]) for w in train_w)
    lengths = np.asarray([len(w[2]) for w in train_w])
    print(f"subset: {index.subset_label}", flush=True)
    print(f"train {n_train} records in {len(train_w)} windows (mean length "
          f"{lengths.mean():.1f}, {np.mean(lengths == args.seq_len):.2f} full); "
          f"held out {sum(len(w[2]) for w in test_w)} records", flush=True)

    # Replay-first: a replay uniformly, then one of its windows.
    by_replay = {}
    for i, w in enumerate(train_w):
        by_replay.setdefault(w[0], []).append(i)
    replay_keys = sorted(by_replay)
    per_step = max(1, args.batch_size // args.seq_len)
    steps = max(1, int(round(args.epochs * n_train / (per_step * lengths.mean()))))
    policy = hp.new_policy(harness_policy, bias_free=True, seed=args.seed)
    opt = torch.optim.AdamW([p for p in policy.parameters() if p.requires_grad], lr=args.lr)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=steps, eta_min=args.lr * 0.01)
    rng = np.random.default_rng(args.seed)
    t0 = last = time.time()
    policy.train()
    for step in range(1, steps + 1):
        picks = [train_w[rng.choice(by_replay[replay_keys[r]])]
                 for r in rng.integers(0, len(replay_keys), size=per_step)]
        block, valid = window_batch(index, picks, args.seq_len)
        rows = run_windows(policy, block, valid, grad=True)
        loss, count = 0.0, float(valid.sum())
        for t, (lps, tgt) in enumerate(rows):
            v = torch.from_numpy(valid[:, t])
            for h in range(3):
                loss = loss - lps[h].gather(1, tgt[:, h:h + 1]).squeeze(1)[v].sum()
        loss = loss / count
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        if time.time() - last > 30 or step == steps:
            last = time.time()
            print(f"step {step}/{steps} loss {loss.item():.4f} [{last - t0:.0f}s]", flush=True)
    policy.eval()

    # Held out: the same records twice, state carried and state zero.
    carried = {"lp": [], "exact": [], "replay": [], "pos": []}
    zero = {"lp": [], "exact": []}
    with torch.no_grad():
        for start in range(0, len(test_w), 256):
            chunk = test_w[start:start + 256]
            block, valid = window_batch(index, chunk, args.seq_len)
            rows = run_windows(policy, block, valid, grad=False)
            for t, (lps, tgt) in enumerate(rows):
                v = valid[:, t]
                lp = sum(lps[h].gather(1, tgt[:, h:h + 1]).squeeze(1) for h in range(3))
                hit = torch.stack([lps[h].argmax(dim=1) == tgt[:, h] for h in range(3)]).all(0)
                carried["lp"].append(lp.numpy()[v])
                carried["exact"].append(hit.numpy()[v])
                carried["replay"].append(block["replay"][:, t][v])
                carried["pos"].append(np.full(int(v.sum()), t))
            flat = block[valid]
            for i in range(0, len(flat), 4096):
                s = hp.score_records(policy, flat[i:i + 4096])
                zero["lp"].append(s["lp0"] + s["lp1"] + s["lp2"])
                zero["exact"].append(s["hit0"] & s["hit1"] & s["hit2"])
            if time.time() - last > 30:
                last = time.time()
                print(f"held-out windows {start}/{len(test_w)}", flush=True)
    carried = {k: np.concatenate(v) for k, v in carried.items()}
    zero = {k: np.concatenate(v) for k, v in zero.items()}
    result = {
        "schema": "human-prior-seq-v1", "subset": index.subset_label,
        "seq_len": args.seq_len, "steps": steps, "epochs": args.epochs,
        "train_records": n_train, "held_out_records": int(len(carried["lp"])),
        "carried": {"exact": hp.cluster_interval(carried["exact"], carried["replay"]),
                    "nll": float(-carried["lp"].mean()),
                    "exact_by_position": {
                        "0": float(carried["exact"][carried["pos"] == 0].mean()),
                        "1-3": float(carried["exact"][(carried["pos"] >= 1) & (carried["pos"] <= 3)].mean()),
                        "4+": float(carried["exact"][carried["pos"] >= 4].mean())}},
        "same_net_zero_state": {"exact": float(zero["exact"].mean()),
                                "nll": float(-zero["lp"].mean())},
        "seconds": round(time.time() - t0, 1),
    }
    print(json.dumps(result, indent=1), flush=True)
    with open(os.path.join(args.out_dir, "result.json"), "w") as f:
        json.dump(result, f, indent=1)
    index.close()
    return result


if __name__ == "__main__":
    main()
