#!/usr/bin/env python
"""human_prior.py: train and score a human-imitation prior on replay pairs.

Offline only. Nothing here is wired into the trainer.

The net is the CURRENT policy architecture (Linear 2782 -> 512, three MinGRU
layers, heads 30 | 33 | 391) built from the play harness's own torch class
(play_harness.policy.MinGRUPolicy, native gate kernel), so the forward that is
trained is the forward the harness plays and the parity doc checked against the
native trainer. By default it is trained BIAS-FREE: the three bias vectors are
zero and frozen, so training/convert_checkpoint.py turns the result into a
native flat fp32 blob with nothing dropped, and the harness loads that blob
through the same loader as an RL checkpoint.

Records are scored i.i.d. at zero recurrent state (see the report for why).

Data contract (AGENTS.md, "Replay and BC contract"): the split is by replay
ID; re-seated records are read only with --reseat-dir and only for the span
stamps in --reseat-stamps (default 1, closed-equal); every result file and
every printed result names the subset.

  <harness>/.venv/bin/python training/human_prior.py \\
      --pairs-dir runs/x/shards/pairs --reseat-dir runs/x/shards/pairs_reseat \\
      --replay-ids runs/reseat-20261005/ids.txt --out-dir runs/x/prior_default
"""

import argparse
import hashlib
import json
import os
import sys
import time

import numpy as np
import torch

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import bc_pretrain as bc  # noqa: E402
from convert_checkpoint import torch_to_cuda  # noqa: E402

DEFAULT_HARNESS = os.path.expanduser("~/Code/bb-play-harness")
ACT_SIZES = bc.ACT_SIZES
HIDDEN, LAYERS = 512, 3
HOLDOUT_REPLAYS = 60
SPLIT_SEED = 20261005
OBS_HALF, OBS_MY_TURN = 784, 785

ACTION_NAMES = (
    "NONE", "SETUP_PLACE", "SETUP_REMOVE", "SETUP_DONE", "KICK_TARGET",
    "TOUCHBACK", "ACTIVATE", "DECLARE", "END_TURN", "STEP", "STAND_UP", "JUMP",
    "BLOCK_TARGET", "PASS_TARGET", "HANDOFF_TARGET", "FOUL_TARGET",
    "TTM_TARGET", "SECURE_BALL", "PICKUP_DECLINE", "END_ACTIVATION",
    "CHOOSE_DIE", "PUSH_SQUARE", "FOLLOW_UP", "USE_REROLL", "DECLINE_REROLL",
    "USE_SKILL", "DECLINE_SKILL", "APOTHECARY", "CHOOSE_OPTION",
    "SPECIAL_TARGET",
)
T = {name: i for i, name in enumerate(ACTION_NAMES)}
ACT_KINDS = ("MOVE", "BLOCK", "BLITZ", "PASS", "HANDOFF", "FOUL", "TTM",
             "SECURE_BALL", "STAB", "GAZE", "KTM", "CHAINSAW", "BREATHE_FIRE",
             "VOMIT")
K = {name: i for i, name in enumerate(ACT_KINDS)}

FAMILIES = (
    "setup", "activate", "end_turn", "declare_move", "declare_block",
    "declare_blitz", "pass", "handoff", "foul", "declare_other", "move",
    "block_target", "block_die", "push_follow", "reroll_skill", "other",
)
FAMILY_INDEX = {name: i for i, name in enumerate(FAMILIES)}
_TYPE_FAMILY = {
    "SETUP_PLACE": "setup", "SETUP_REMOVE": "setup", "SETUP_DONE": "setup",
    "KICK_TARGET": "setup", "TOUCHBACK": "setup",
    "ACTIVATE": "activate", "END_TURN": "end_turn",
    "STEP": "move", "STAND_UP": "move", "JUMP": "move",
    "END_ACTIVATION": "move", "SECURE_BALL": "move", "PICKUP_DECLINE": "move",
    "BLOCK_TARGET": "block_target", "PASS_TARGET": "pass",
    "HANDOFF_TARGET": "handoff", "FOUL_TARGET": "foul",
    "CHOOSE_DIE": "block_die", "PUSH_SQUARE": "push_follow",
    "FOLLOW_UP": "push_follow", "USE_REROLL": "reroll_skill",
    "DECLINE_REROLL": "reroll_skill", "USE_SKILL": "reroll_skill",
    "DECLINE_SKILL": "reroll_skill",
}
_KIND_FAMILY = {"MOVE": "declare_move", "BLOCK": "declare_block",
                "BLITZ": "declare_blitz", "PASS": "pass", "HANDOFF": "handoff",
                "FOUL": "foul"}


def action_family(action_type, arg):
    """Family index of each (type, arg): a declaration is filed by its kind."""
    action_type = np.asarray(action_type, dtype=np.int64)
    arg = np.asarray(arg, dtype=np.int64)
    by_type = np.full(len(ACTION_NAMES), FAMILY_INDEX["other"], dtype=np.int64)
    for name, family in _TYPE_FAMILY.items():
        by_type[T[name]] = FAMILY_INDEX[family]
    out = by_type[action_type]
    declare = action_type == T["DECLARE"]
    by_kind = np.full(64, FAMILY_INDEX["declare_other"], dtype=np.int64)
    for name, family in _KIND_FAMILY.items():
        by_kind[K[name]] = FAMILY_INDEX[family]
    out = np.where(declare, by_kind[np.minimum(arg, 63)], out)
    return out


def turn_band(turn):
    """0 set-up and kick-off (turn 0), 1 turns 1-2, 2 turns 3-4, 3 turns 5-8+."""
    turn = np.asarray(turn, dtype=np.int64)
    return np.where(turn <= 0, 0, np.where(turn <= 2, 1, np.where(turn <= 4, 2, 3)))


TURN_BANDS = ("0 (set-up, kick-off)", "1-2", "3-4", "5-8")


def holdout_split(replay_ids, n_holdout=HOLDOUT_REPLAYS, seed=SPLIT_SEED):
    """(train order, held-out IDs). Replay-disjoint, deterministic.

    The train order is a fixed shuffle: a learning curve takes its first N
    IDs, so the 100-replay set is inside the 200-replay set.
    """
    ids = np.asarray(sorted(set(int(x) for x in replay_ids)), dtype=np.int64)
    if len(ids) <= n_holdout:
        raise SystemExit(f"{len(ids)} replays cannot hold out {n_holdout}")
    rng = np.random.default_rng(seed)
    rng.shuffle(ids)
    holdout = tuple(sorted(int(x) for x in ids[:n_holdout]))
    train_order = tuple(int(x) for x in ids[n_holdout:])
    return train_order, holdout


def load_harness(harness_root):
    root = os.path.abspath(harness_root)
    if root not in sys.path:
        sys.path.insert(1, root)
    from play_harness import policy as harness_policy
    return harness_policy


def new_policy(harness_policy, bias_free=True, seed=0, kernel="native"):
    """A fresh policy. bias_free zeroes and freezes every bias (native layers
    carry none). The value row is zeroed and frozen either way: an imitation
    net has no value estimate and must not look as if it had one."""
    torch.manual_seed(seed)
    policy = harness_policy.MinGRUPolicy(kernel=kernel)
    with torch.no_grad():
        policy.decoder.value_function.weight.zero_()
        policy.decoder.value_function.bias.zero_()
        policy.decoder.value_function.weight.requires_grad_(False)
        policy.decoder.value_function.bias.requires_grad_(False)
        if bias_free:
            for name, param in policy.named_parameters():
                if name.endswith(".bias"):
                    param.zero_()
                    param.requires_grad_(False)
    return policy


def forward_logits(policy, obs, grad=False):
    """Logits at ZERO recurrent state for a batch of observations."""
    state = torch.zeros(policy.num_layers, obs.shape[0], policy.hidden,
                        device=obs.device)
    if grad:
        # forward_eval is wrapped in no_grad; the undecorated function is the
        # same code with gradients.
        logits, _value, _state = type(policy).forward_eval.__wrapped__(
            policy, obs, state)
    else:
        logits, _value, _state = policy.forward_eval(obs, state)
    return logits


def head_log_probs(logits, mask):
    """Per-head log-softmax under the record's conditional masks."""
    out, off = [], 0
    for size in ACT_SIZES:
        m = mask[:, off:off + size]
        out.append(torch.log_softmax(
            logits[:, off:off + size].masked_fill(~m, float("-inf")), dim=1))
        off += size
    return out


@torch.no_grad()
def score_records(policy, records, device="cpu"):
    """Teacher-forced scores of one batch of records (numpy arrays)."""
    obs, mask, tgt = bc.to_tensors(records, device)
    logits = forward_logits(policy, obs)
    lps = head_log_probs(logits, mask)
    out = {}
    off = 0
    for h, size in enumerate(ACT_SIZES):
        lp = lps[h]
        out[f"lp{h}"] = lp.gather(1, tgt[:, h:h + 1]).squeeze(1).numpy()
        out[f"hit{h}"] = (lp.argmax(dim=1) == tgt[:, h]).numpy()
        out[f"conf{h}"] = lp.max(dim=1).values.exp().numpy()
        out[f"nlegal{h}"] = mask[:, off:off + size].sum(dim=1).numpy()
        off += size
    out["p_type"] = lps[0].exp().numpy()
    out["p_arg"] = lps[1].exp().numpy()
    return out


def record_fields(records):
    """The grouping fields every table uses."""
    segment = bc.record_segment(records)
    return {
        "replay": np.asarray(records["replay"], dtype=np.int64),
        "type": np.asarray(records["type"], dtype=np.int64),
        "arg": np.asarray(records["arg"], dtype=np.int64),
        "family": action_family(records["type"], records["arg"]),
        "half": np.asarray(records["obs"][:, OBS_HALF], dtype=np.int64),
        "turn": np.asarray(records["obs"][:, OBS_MY_TURN], dtype=np.int64),
        "reseat": segment > 0,
        "stamp": np.where(segment > 0, bc.record_stamp(records), 255),
    }


def collect(policy, dataset, batch=4096, keep_probs=False, progress=None):
    """Score every record of a lazy dataset; returns concatenated arrays."""
    parts = {}
    done = 0
    t0 = time.time()
    for records in dataset.iter_record_batches(batch):
        row = score_records(policy, records)
        row.update(record_fields(records))
        if keep_probs:
            off = ACT_SIZES[0]
            row["mask_type"] = np.asarray(records["mask"][:, :off], dtype=bool)
            row["mask_arg"] = np.asarray(
                records["mask"][:, off:off + ACT_SIZES[1]], dtype=bool)
        else:
            row.pop("p_type")
            row.pop("p_arg")
        for key, value in row.items():
            parts.setdefault(key, []).append(value)
        done += len(records)
        if progress and time.time() - t0 > 20:
            t0 = time.time()
            print(f"  {progress}: scored {done}/{len(dataset)}", flush=True)
    return {key: np.concatenate(value) for key, value in parts.items()}


def cluster_interval(values, clusters, n_boot=1000, seed=0):
    """Mean of `values` with a 95% interval from resampling whole clusters."""
    values = np.asarray(values, dtype=np.float64)
    if len(values) == 0:
        return None
    ids, inverse = np.unique(clusters, return_inverse=True)
    sums = np.bincount(inverse, weights=values, minlength=len(ids))
    counts = np.bincount(inverse, minlength=len(ids)).astype(np.float64)
    rng = np.random.default_rng(seed)
    pick = rng.integers(0, len(ids), size=(n_boot, len(ids)))
    boot = sums[pick].sum(axis=1) / np.maximum(counts[pick].sum(axis=1), 1.0)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return {"mean": float(values.mean()), "lo": float(lo), "hi": float(hi),
            "n": int(len(values)), "clusters": int(len(ids))}


def summarize(s, where=None, intervals=False):
    """Accuracy, likelihood and calibration of the scored records in `where`."""
    sel = np.ones(len(s["replay"]), dtype=bool) if where is None else where
    n = int(sel.sum())
    if n == 0:
        return {"n": 0}
    exact = s["hit0"][sel] & s["hit1"][sel] & s["hit2"][sel]
    lp = s["lp0"][sel] + s["lp1"][sel] + s["lp2"][sel]
    out = {
        "n": n,
        "replays": int(len(np.unique(s["replay"][sel]))),
        "exact": float(exact.mean()),
        "nll": float(-lp.mean()),
        "mean_p_human": float(np.exp(lp).mean()),
    }
    for h, name in enumerate(("type", "arg", "square")):
        choice = sel & (s[f"nlegal{h}"] > 1)
        out[f"acc_{name}"] = float(s[f"hit{h}"][sel].mean())
        out[f"n_{name}_choice"] = int(choice.sum())
        if choice.any():
            # Rows where the head has two or more legal values.
            out[f"acc_{name}_choice"] = float(s[f"hit{h}"][choice].mean())
            out[f"mean_p_{name}_choice"] = float(np.exp(s[f"lp{h}"][choice]).mean())
            out[f"conf_{name}_choice"] = float(s[f"conf{h}"][choice].mean())
    if intervals:
        out["exact_interval"] = cluster_interval(exact, s["replay"][sel])
    return out


def breakdown(s):
    """The report's tables for one scored evaluation set."""
    out = {"overall": summarize(s, intervals=True)}
    out["by_family"] = {
        name: summarize(s, s["family"] == i) for i, name in enumerate(FAMILIES)}
    out["by_half"] = {
        str(h): summarize(s, s["half"] == h) for h in (1, 2)}
    band = turn_band(s["turn"])
    out["by_turn_band"] = {
        name: summarize(s, band == i) for i, name in enumerate(TURN_BANDS)}
    out["by_provenance"] = {
        "prefix": summarize(s, ~s["reseat"]),
        "reseat": summarize(s, s["reseat"]),
    }
    for stamp in bc.KNOWN_STAMPS:
        sel = s["reseat"] & (s["stamp"] == stamp)
        if sel.any():
            out["by_provenance"][f"reseat_stamp_{stamp}"] = summarize(s, sel)
    # Top-label calibration of the type head, teacher-forced, where it has a
    # choice: mean confidence against accuracy in ten confidence bins.
    choice = s["nlegal0"] > 1
    conf, hit = s["conf0"][choice], s["hit0"][choice]
    bins = np.minimum((conf * 10).astype(int), 9)
    ece, rows = 0.0, []
    for b in range(10):
        m = bins == b
        if m.any():
            rows.append({"bin": b, "n": int(m.sum()), "confidence": float(conf[m].mean()),
                         "accuracy": float(hit[m].mean())})
            ece += m.mean() * abs(conf[m].mean() - hit[m].mean())
    out["type_head_calibration"] = {"ece": float(ece), "bins": rows}
    return out


def native_export(policy, out_path, note):
    """Write the native flat blob and a lineage sidecar the harness accepts."""
    sd = {k: v.detach().cpu() for k, v in policy.state_dict().items()}
    max_bias = max(float(v.abs().max()) for k, v in sd.items() if k.endswith(".bias"))
    blob = torch_to_cuda(sd, HIDDEN, LAYERS, 2782, ACT_SIZES)
    blob.astype("<f4").tofile(out_path)
    digest = hashlib.sha256(open(out_path, "rb").read()).hexdigest()
    lineage = {
        "schema_version": 1,
        "ancestry": {"eligible": False, "initialization": "human-imitation",
                     "mode": "offline_imitation_prior", "note": note},
        "checkpoint": {"bytes": os.path.getsize(out_path), "sha256": digest},
        "compatibility": {
            "action_abi": "exact-joint-v1", "observation_abi": "obs-v6",
            "observation_version": 6, "policy_expansion_factor": 1,
            "policy_hidden_size": HIDDEN, "policy_num_layers": LAYERS},
    }
    with open(out_path + ".lineage.json", "w") as f:
        json.dump(lineage, f)
    return {"path": out_path, "sha256": digest, "max_abs_bias_dropped": max_bias}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pairs-dir", required=True)
    ap.add_argument("--reseat-dir", default=None,
                    help="re-seated BBR1 shards; without it none is read")
    ap.add_argument("--reseat-stamps", default=None,
                    help="comma-separated span stamps (default 1, closed-equal)")
    ap.add_argument("--eval-reseat-dir", default=None,
                    help="re-seated shards for HELD-OUT SCORING only (default: "
                         "--reseat-dir). Lets a prefix-only net be scored on the "
                         "same held-out sets as the others; never trained on")
    ap.add_argument("--eval-all-stamps", action="store_true",
                    help="also score the held-out replays on re-seated records of "
                         "EVERY span stamp (0 to 4). A named measurement (the "
                         "subset comparison), never a default")
    ap.add_argument("--replay-ids", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--harness-root", default=DEFAULT_HARNESS)
    ap.add_argument("--train-replays", type=int, default=0,
                    help="use the first N replays of the train order (0 = all)")
    ap.add_argument("--dev-replays", type=int, default=0,
                    help="take the LAST N replays of the train order out of "
                         "training and score them during the run")
    ap.add_argument("--epochs", type=float, default=6.0,
                    help="training budget in passes over the training records")
    ap.add_argument("--batch-size", type=int, default=1024)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--weight-decay", type=float, default=0.0)
    ap.add_argument("--sampling", choices=("replay-first", "record-weighted"),
                    default="replay-first")
    ap.add_argument("--with-bias", action="store_true",
                    help="train the three bias vectors (NOT native-convertible)")
    ap.add_argument("--eval-every", type=int, default=500)
    ap.add_argument("--skip-holdout-eval", action="store_true",
                    help="selection runs: score the dev set only, so no "
                         "held-out number exists to be tempted by")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--threads", type=int, default=2)
    args = ap.parse_args(argv)

    torch.set_num_threads(args.threads)
    harness_policy = load_harness(args.harness_root)
    os.makedirs(args.out_dir, exist_ok=True)
    stamps = (None if args.reseat_stamps is None
              else [int(v) for v in args.reseat_stamps.split(",") if v])
    replay_ids = bc.load_replay_ids(args.replay_ids)

    # Three views of the same replays: the training subset, and the three
    # evaluation subsets every model is scored on.
    index = bc.ShardIndex.from_directory(
        args.pairs_dir, replay_ids=replay_ids, cache_size=1024,
        reseat_dir=args.reseat_dir, reseat_stamps=stamps)
    bc.require_exact_action_lineage(index)
    eval_indexes = {"prefix": bc.ShardIndex.from_directory(
        args.pairs_dir, replay_ids=replay_ids, cache_size=64)}
    eval_reseat = args.eval_reseat_dir or args.reseat_dir
    if eval_reseat:
        eval_indexes["prefix+closed_equal"] = bc.ShardIndex.from_directory(
            args.pairs_dir, replay_ids=replay_ids, cache_size=64,
            reseat_dir=eval_reseat)
        if args.eval_all_stamps:
            eval_indexes["everything"] = bc.ShardIndex.from_directory(
                args.pairs_dir, replay_ids=replay_ids, cache_size=64,
                reseat_dir=eval_reseat, reseat_stamps=bc.KNOWN_STAMPS)

    train_order, holdout = holdout_split(replay_ids)
    dev_ids = train_order[len(train_order) - args.dev_replays:] if args.dev_replays else ()
    pool = train_order[:len(train_order) - args.dev_replays]
    if args.train_replays:
        if args.train_replays > len(pool):
            raise SystemExit(f"--train-replays {args.train_replays} > {len(pool)} available")
        pool = pool[:args.train_replays]
    assert not set(pool) & set(holdout) and not set(dev_ids) & set(holdout)
    assert not set(pool) & set(dev_ids)
    nonempty = set(index.nonempty_replay_ids)
    train_ids = [r for r in pool if r in nonempty]
    train = bc.LazyReplayDataset(index, train_ids)
    dev = (bc.LazyReplayDataset(index, [r for r in dev_ids if r in nonempty])
           if dev_ids else None)

    steps = max(1, int(round(args.epochs * len(train) / args.batch_size)))
    print(f"subset: {index.subset_label}", flush=True)
    print(f"train: {len(train_ids)} replays ({len(pool)} requested), "
          f"{train.provenance_counts} records | dev {len(dev_ids)} replays | "
          f"held out {len(holdout)} replays (never trained) | "
          f"{steps} steps of {args.batch_size} = {args.epochs} epochs", flush=True)

    policy = new_policy(harness_policy, bias_free=not args.with_bias, seed=args.seed)
    params = [p for p in policy.parameters() if p.requires_grad]
    opt = torch.optim.AdamW(params, lr=args.lr, weight_decay=args.weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(
        opt, T_max=steps, eta_min=args.lr * 0.01)
    rng = np.random.default_rng(args.seed)
    mode = "replay" if args.sampling == "replay-first" else "record"
    curve = []
    t0 = last = time.time()
    policy.train()
    for step in range(1, steps + 1):
        records = train.sample_records(args.batch_size, rng, mode=mode)
        obs, mask, tgt = bc.to_tensors(records, "cpu")
        logits = forward_logits(policy, obs, grad=True)
        loss, hits = bc.masked_losses(torch.split(logits, ACT_SIZES, dim=1), mask, tgt)
        opt.zero_grad()
        loss.backward()
        opt.step()
        sched.step()
        now = time.time()
        if now - last > 30 or step == steps:
            last = now
            exact = (hits[0] & hits[1] & hits[2]).float().mean().item()
            print(f"step {step}/{steps} loss {loss.item():.4f} batch exact {exact:.3f} "
                  f"[{now - t0:.0f}s]", flush=True)
        if dev is not None and (step % args.eval_every == 0 or step == steps):
            row = summarize(collect(policy, dev))
            row.update(step=step, epochs=round(step * args.batch_size / len(train), 3))
            curve.append(row)
            print(f"  dev @ step {step} ({row['epochs']} epochs): exact {row['exact']:.4f} "
                  f"nll {row['nll']:.4f}", flush=True)
    policy.eval()

    torch.save(policy.state_dict(), os.path.join(args.out_dir, "prior.pt"))
    export = None
    if not args.with_bias:
        export = native_export(
            policy, os.path.join(args.out_dir, "prior.bin"),
            f"human prior; {index.subset_label}; {len(train_ids)} training replays")

    result = {
        "schema": "human-prior-run-v1",
        "subset": index.subset_label,
        "reseat_stamps": index.reseat_stamps,
        "train": {"replays": len(train_ids), "records": train.provenance_counts,
                  "ids_sha256": bc.replay_ids_sha256(train_ids)},
        "dev": {"replays": len(dev_ids)},
        "holdout": {"replays": len(holdout), "ids": list(holdout),
                    "ids_sha256": bc.replay_ids_sha256(holdout)},
        "config": {k: getattr(args, k) for k in (
            "epochs", "batch_size", "lr", "weight_decay", "sampling", "with_bias",
            "seed", "train_replays", "dev_replays")},
        "steps": steps, "bias_free": not args.with_bias, "recurrent_state": "zero, i.i.d.",
        "dev_curve": curve, "native_export": export,
        "seconds": round(time.time() - t0, 1),
        "eval": {},
    }
    if args.skip_holdout_eval:
        for eval_index in eval_indexes.values():
            eval_index.close()
        eval_indexes = {}
    if args.eval_all_stamps and "everything" not in eval_indexes and not args.skip_holdout_eval:
        raise SystemExit("--eval-all-stamps needs --reseat-dir or --eval-reseat-dir")
    for name, eval_index in eval_indexes.items():
        ids = [r for r in holdout if r in set(eval_index.nonempty_replay_ids)]
        data = bc.LazyReplayDataset(eval_index, ids)
        scored = collect(policy, data, progress=f"held-out {name}")
        result["eval"][name] = {"subset": eval_index.subset_label,
                                "records": data.provenance_counts,
                                **breakdown(scored)}
        o = result["eval"][name]["overall"]
        print(f"held-out [{name}] n={o['n']} exact {o['exact']:.4f} "
              f"type/arg/sq {o['acc_type']:.3f}/{o['acc_arg']:.3f}/{o['acc_square']:.3f} "
              f"nll {o['nll']:.4f} mean p(human) {o['mean_p_human']:.4f}", flush=True)
        eval_index.close()
    print(f"trained on: {index.subset_label}", flush=True)
    index.close()
    with open(os.path.join(args.out_dir, "result.json"), "w") as f:
        json.dump(result, f, indent=1)
    return result


if __name__ == "__main__":
    main()
