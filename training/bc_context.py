#!/usr/bin/env python
"""bc_context.py - Path-A temporal-context BC screen.

Computes cheap within-turn context features from already-extracted .bbp pairs
at load time, appends them to the obs vector, and trains the same iid
zero-state policy as bc_pretrain.py. This is an accuracy screen only: the
resulting context checkpoints are not rollout-compatible until Path B adds the
winning features to the engine obs encoder and pairs are re-extracted.

Four A/B arms:
  iid                    no context, D172-compatible baseline
  structural             own activation count + team-reroll-used + player flags
  structural_last_action structural + previous 1-3 actions
  last_action_only       copycat ablation

Example:
  vendor/PufferLib/.venv/bin/python training/bc_context.py \\
      --pairs-dir validation/pairs_v4 --arm structural_last_action \\
      --expect-obs-size 2782 --head-loss legacy \\
      --steps 3000 --batch-size 256 --lr 1e-3 --cosine
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import types

import numpy as np
import torch
import torch.nn.functional as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "vendor", "PufferLib"))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bc_pretrain  # noqa: E402
from bc_context_features import (  # noqa: E402
    ACT_SIZES,
    ContextFeatureSpec,
    action_head_applicability,
    compute_context_features,
    feature_names,
    make_context_spec,
)


VAL_CHECKSUM_DTYPE = np.dtype([
    ("replay", "<u4"),
    ("cmd", "<u4"),
    ("agent", "u1"),
    ("type", "u1"),
    ("arg", "u1"),
    ("sq", "<u2"),
])


def split_by_replay_with_mask(recs, val_frac, seed):
    train_r, val_r, val_ids = bc_pretrain.split_by_replay(recs, val_frac, seed)
    val_m = np.isin(recs["replay"], val_ids)
    return train_r, val_r, val_ids, ~val_m, val_m


def validation_records_checksum(recs):
    """SHA-256 over validation (replay, cmd, agent, type, arg, sq) rows."""

    keys = np.empty(len(recs), dtype=VAL_CHECKSUM_DTYPE)
    for name in VAL_CHECKSUM_DTYPE.names:
        keys[name] = recs[name]
    return hashlib.sha256(np.ascontiguousarray(keys).view(np.uint8)).hexdigest()


def to_tensors(recs, context, device):
    obs = torch.from_numpy(np.ascontiguousarray(recs["obs"])).to(device)
    mask = torch.from_numpy(np.ascontiguousarray(recs["mask"])).to(device).bool()
    tgt = torch.stack([
        torch.from_numpy(recs["type"].astype(np.int64)),
        torch.from_numpy(recs["arg"].astype(np.int64)),
        torch.from_numpy(recs["sq"].astype(np.int64)),
    ], dim=1).to(device)
    app = torch.from_numpy(action_head_applicability(recs)).to(device).bool()
    ctx = None
    if context is not None and context.shape[1] > 0:
        ctx = torch.from_numpy(np.ascontiguousarray(context)).to(
            device=device, dtype=torch.float32)
    return obs, ctx, mask, tgt, app


def make_policy_input(obs, ctx):
    if ctx is None:
        return obs
    return torch.cat([obs.float(), ctx], dim=1)


def forward_heads(policy, obs, ctx, device):
    x = make_policy_input(obs, ctx)
    state = policy.initial_state(x.shape[0], device=device)
    logits, _values, _state = policy.forward_eval(x, state)
    return logits


def masked_losses(logits, mask, tgt, app, mode):
    """Masked CE. mode=applicable skips arg/sq where that action type ignores them."""
    off, losses, hits = 0, [], []
    for h, n in enumerate(ACT_SIZES):
        m = mask[:, off:off + n]
        off += n
        lg = logits[h].masked_fill(~m, -1e9)
        hits.append(lg.argmax(dim=1) == tgt[:, h])
        if mode == "applicable":
            keep = app[:, h]
            if keep.any():
                losses.append(F.cross_entropy(lg[keep], tgt[keep, h]))
        else:
            losses.append(F.cross_entropy(lg, tgt[:, h]))
    return sum(losses), hits


def metric_counts(hits, app, mode):
    exact = torch.ones_like(hits[0], dtype=torch.bool)
    nums, dens = [], []
    for h in range(3):
        if mode == "applicable":
            keep = app[:, h]
            exact &= (hits[h] | ~keep)
            nums.append((hits[h] & keep).sum().item())
            dens.append(keep.sum().item())
        else:
            exact &= hits[h]
            nums.append(hits[h].sum().item())
            dens.append(hits[h].numel())
    return nums, dens, exact.sum().item(), exact.numel()


@torch.no_grad()
def evaluate(policy, obs, ctx, mask, tgt, app, device, loss_mode,
             metric_mode="legacy", batch=2048):
    policy.eval()
    tot, loss_sum = 0, 0.0
    head_num = [0, 0, 0]
    head_den = [0, 0, 0]
    exact_num = 0
    exact_den = 0
    for i in range(0, obs.shape[0], batch):
        o = obs[i:i + batch]
        c = None if ctx is None else ctx[i:i + batch]
        m = mask[i:i + batch]
        t = tgt[i:i + batch]
        a = app[i:i + batch]
        logits = forward_heads(policy, o, c, device)
        loss, hits = masked_losses(logits, m, t, a, loss_mode)
        loss_sum += loss.item() * o.shape[0]
        nums, dens, ex_n, ex_d = metric_counts(hits, a, metric_mode)
        for h in range(3):
            head_num[h] += nums[h]
            head_den[h] += dens[h]
        exact_num += ex_n
        exact_den += ex_d
        tot += o.shape[0]
    policy.train()
    accs = [head_num[h] / head_den[h] if head_den[h] else float("nan")
            for h in range(3)]
    return loss_sum / tot, accs, exact_num / exact_den


def apply_last_action_dropout(ctx, spec: ContextFeatureSpec, p, gen):
    if ctx is None or p <= 0.0 or spec.last_action_slice.stop == spec.last_action_slice.start:
        return ctx
    keep = torch.rand((ctx.shape[0], 1), generator=gen) >= p
    keep = keep.to(device=ctx.device, dtype=ctx.dtype)
    out = ctx.clone()
    out[:, spec.last_action_slice] *= keep
    return out


def resolve_head_loss(arm, requested):
    if requested != "auto":
        return requested
    # Auto intentionally aliases legacy so the default A/B isolates features.
    # Use --head-loss applicable explicitly for the diagnostic masked loss.
    return "legacy"


def resolve_checkpoint_path(out_arg, arm, head_loss):
    if out_arg is None:
        return os.path.join(ROOT, "training", "checkpoints",
                            f"bc_context_{arm}_head-{head_loss}.bin")
    dirname, basename = os.path.split(out_arg)
    stem, ext = os.path.splitext(basename)
    ext = ext or ".bin"
    normalized = stem.lower().replace("_", "-")
    if f"head-{head_loss}" in normalized or f"headloss-{head_loss}" in normalized:
        return out_arg
    return os.path.join(dirname, f"{stem}_head-{head_loss}{ext}")


def write_manifest(path, data):
    manifest_path = f"{path}.manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
        f.write("\n")
    return manifest_path


def load_policy_like_trainer(config_path, input_size):
    return bc_pretrain.load_policy_like_trainer(config_path, input_size)


def verify_roundtrip(out_path, input_size, config_path, trained_policy, probe_obs):
    """Round-trip for a widened Path-A policy input."""
    from pufferlib.torch_pufferl import PuffeRL
    fresh, _ = load_policy_like_trainer(config_path, input_size)
    shim = types.SimpleNamespace(device="cpu", policy=fresh)
    PuffeRL.load_weights(shim, out_path)
    ref = {k: v.detach().cpu() for k, v in trained_policy.state_dict().items()}
    got = fresh.state_dict()
    assert set(ref) == set(got), "state_dict key mismatch after round-trip"
    pdiff = max((ref[k].float() - got[k].float()).abs().max().item()
                for k in ref)
    trained_cpu, _ = load_policy_like_trainer(config_path, input_size)
    trained_cpu.load_state_dict(ref)
    with torch.no_grad():
        a = bc_pretrain.forward_heads(trained_cpu, probe_obs.cpu(), "cpu")
        b = bc_pretrain.forward_heads(fresh, probe_obs.cpu(), "cpu")
    ldiff = max((x - y).abs().max().item() for x, y in zip(a, b))
    return pdiff, ldiff


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pairs-dir", default=os.path.join(ROOT, "validation", "pairs_v4"))
    ap.add_argument("--config", default=os.path.join(ROOT, "puffer", "config",
                                                     "bloodbowl.ini"))
    ap.add_argument("--out", default=None,
                    help="checkpoint path; head_loss is appended unless already present")
    ap.add_argument("--arm", default="iid",
                    choices=["iid", "structural", "structural_last_action",
                             "last_action_only"],
                    help="A/B preset arm")
    ap.add_argument("--features", default=None,
                    help="optional comma/+ list overriding --arm: structural,last_action")
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="auto",
                    help="auto (mps if available, else cpu) | cpu | mps | cuda")
    ap.add_argument("--log-every", type=int, default=25)
    ap.add_argument("--init", default=None,
                    help="warm-start from an existing state_dict (input width must match)")
    ap.add_argument("--cosine", action="store_true",
                    help="cosine-decay the LR to 1%% over --steps")
    ap.add_argument("--head-loss", default="legacy",
                    choices=["auto", "legacy", "applicable"],
                    help="legacy is the strict feature-ablation default; applicable is a diagnostic")
    ap.add_argument("--val-checksum", default=None,
                    help="expected validation SHA-256 over replay/cmd/agent/type/arg/sq")
    ap.add_argument("--expect-obs-size", type=int, default=2782,
                    help="abort unless shard obs size matches; use 0 to disable")
    ap.add_argument("--last-action-dropout", type=float, default=0.10,
                    help="per-sample dropout probability for the last-action feature block")
    ap.add_argument("--no-roundtrip", action="store_true",
                    help="skip save/load verification")
    args = ap.parse_args()

    device = args.device
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    torch.manual_seed(args.seed)

    spec = make_context_spec(args.arm, args.features)
    head_loss = resolve_head_loss(spec.arm, args.head_loss)
    out_path = resolve_checkpoint_path(args.out, spec.arm, head_loss)
    if args.out is not None and out_path != args.out:
        print(f"checkpoint filename includes head_loss: {args.out} -> {out_path}")
    if spec.width == 0:
        args.last_action_dropout = 0.0

    recs, obs_size, mask_size = bc_pretrain.load_shards(args.pairs_dir)
    if args.expect_obs_size and obs_size != args.expect_obs_size:
        raise SystemExit(
            f"obs-size guard failed: {args.pairs_dir} has {obs_size}B obs, "
            f"expected {args.expect_obs_size}B "
            "(pass --expect-obs-size 0 to disable or set the intended size)")
    train_r, val_r, val_ids, train_m, val_m = split_by_replay_with_mask(
        recs, args.val_frac, args.seed)
    val_checksum = validation_records_checksum(val_r)
    print(f"pairs: {len(recs)} from {len(np.unique(recs['replay']))} replays "
          f"(obs {obs_size}B, mask {mask_size}b) | split BY REPLAY: "
          f"{len(train_r)} train / {len(val_r)} val (held out: {val_ids})")
    print(f"val checksum sha256(replay,cmd,agent,type,arg,sq): {val_checksum}")
    expected_val_checksum = (args.val_checksum or "").strip().lower()
    if expected_val_checksum and expected_val_checksum != val_checksum:
        raise SystemExit(f"validation checksum mismatch: got {val_checksum}, "
                         f"expected {expected_val_checksum}")

    ctx_all = None
    input_size = obs_size
    if spec.width:
        ctx_all, input_size, spec = compute_context_features(
            recs, obs_size=obs_size, arm=args.arm, features=args.features)
    train_ctx = None if ctx_all is None else ctx_all[train_m]
    val_ctx = None if ctx_all is None else ctx_all[val_m]

    print(f"context arm: {spec.arm} | features {spec.summary()} | "
          f"input {obs_size}+{spec.width}={input_size} | "
          f"head_loss={head_loss} (requested {args.head_loss}) | "
          f"last_action_dropout={args.last_action_dropout:.2f}")
    if spec.width == 0 and head_loss == "legacy":
        print("iid compatibility: zero-width context, legacy head loss, "
              f"bc_pretrain.split_by_replay(seed={args.seed})")
    if spec.width:
        names = feature_names(spec)
        print(f"context feature names ({len(names)}): {', '.join(names[:12])}"
              f"{' ...' if len(names) > 12 else ''}")

    policy, desc = load_policy_like_trainer(args.config, input_size)
    if args.init:
        policy.load_state_dict(torch.load(args.init, map_location="cpu"))
        print(f"warm-started from {args.init}")
    policy = policy.to(device).train()
    n_params = sum(p.numel() for p in policy.parameters())
    print(f"policy: {desc} | {n_params:,} params | device {device}")

    tr_obs, tr_ctx, tr_mask, tr_tgt, tr_app = to_tensors(train_r, train_ctx, device)
    va_obs, va_ctx, va_mask, va_tgt, va_app = to_tensors(val_r, val_ctx, device)
    opt = torch.optim.Adam(policy.parameters(), lr=args.lr)
    sched = (torch.optim.lr_scheduler.CosineAnnealingLR(
                 opt, T_max=args.steps, eta_min=args.lr * 0.01)
             if args.cosine else None)
    sample_gen = torch.Generator().manual_seed(args.seed)
    dropout_gen = torch.Generator().manual_seed(args.seed + 17)

    first_loss = last_loss = None
    for step in range(args.steps):
        idx = torch.randint(0, tr_obs.shape[0], (args.batch_size,), generator=sample_gen)
        b_ctx = None if tr_ctx is None else tr_ctx[idx]
        b_ctx = apply_last_action_dropout(b_ctx, spec, args.last_action_dropout, dropout_gen)
        logits = forward_heads(policy, tr_obs[idx], b_ctx, device)
        loss, hits = masked_losses(logits, tr_mask[idx], tr_tgt[idx], tr_app[idx],
                                   head_loss)
        opt.zero_grad()
        loss.backward()
        opt.step()
        if sched is not None:
            sched.step()
        if first_loss is None:
            first_loss = loss.item()
        last_loss = loss.item()
        if step % args.log_every == 0 or step == args.steps - 1:
            nums, dens, ex_n, ex_d = metric_counts(hits, tr_app[idx], "legacy")
            accs = [nums[h] / dens[h] if dens[h] else float("nan") for h in range(3)]
            print(f"step {step:4d} | loss[{head_loss}] {loss.item():7.4f} | "
                  f"legacy acc type/arg/sq {accs[0]:.3f}/{accs[1]:.3f}/{accs[2]:.3f} | "
                  f"exact {ex_n / ex_d:.3f}")

    v_loss, v_accs, v_exact = evaluate(policy, va_obs, va_ctx, va_mask, va_tgt,
                                       va_app, device, head_loss, "legacy")
    t_loss, t_accs, t_exact = evaluate(policy, tr_obs, tr_ctx, tr_mask, tr_tgt,
                                       tr_app, device, head_loss, "legacy")
    print(f"final train legacy | loss[{head_loss}] {t_loss:.4f} | acc type/arg/sq "
          f"{t_accs[0]:.3f}/{t_accs[1]:.3f}/{t_accs[2]:.3f} | exact {t_exact:.3f}")
    print(f"final  val  legacy | head_loss={head_loss} | loss {v_loss:.4f} | "
          f"acc type/arg/sq {v_accs[0]:.3f}/{v_accs[1]:.3f}/{v_accs[2]:.3f} | "
          f"exact {v_exact:.3f}")

    va_app_exact = None
    if head_loss == "applicable":
        va_app_loss, va_app_accs, va_app_exact = evaluate(
            policy, va_obs, va_ctx, va_mask, va_tgt, va_app, device,
            "applicable", "applicable")
        print(f"final  val  applicable | loss {va_app_loss:.4f} | acc type/arg/sq "
              f"{va_app_accs[0]:.3f}/{va_app_accs[1]:.3f}/{va_app_accs[2]:.3f} | "
              f"exact {va_app_exact:.3f}")
    print(f"loss curve: {first_loss:.4f} -> {last_loss:.4f}")

    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    torch.save(policy.state_dict(), out_path)
    manifest = {
        "arm": spec.arm,
        "batch_size": args.batch_size,
        "checkpoint": out_path,
        "config": args.config,
        "context_features": feature_names(spec),
        "context_width": spec.width,
        "cosine": bool(args.cosine),
        "device": device,
        "head_loss": head_loss,
        "head_loss_requested": args.head_loss,
        "input_size": input_size,
        "last_action_dropout": args.last_action_dropout,
        "lr": args.lr,
        "mask_size": mask_size,
        "obs_size": obs_size,
        "pairs_dir": args.pairs_dir,
        "seed": args.seed,
        "steps": args.steps,
        "train_records": int(len(train_r)),
        "val_checksum": val_checksum,
        "val_frac": args.val_frac,
        "val_ids": [int(x) for x in val_ids],
        "val_records": int(len(val_r)),
        "val_exact_applicable_metric": (
            None if va_app_exact is None else float(va_app_exact)),
        "val_exact_legacy_metric": float(v_exact),
    }
    manifest_path = write_manifest(out_path, manifest)
    print(f"saved {out_path} ({os.path.getsize(out_path)} bytes)")
    print(f"saved manifest {manifest_path}")

    if not args.no_roundtrip:
        probe_obs = va_obs[:8] if len(va_obs) else tr_obs[:8]
        probe_ctx = None
        if va_ctx is not None or tr_ctx is not None:
            src_ctx = va_ctx if va_ctx is not None and len(va_ctx) else tr_ctx
            probe_ctx = src_ctx[:8]
        probe = make_policy_input(probe_obs, probe_ctx)
        pdiff, ldiff = verify_roundtrip(out_path, input_size, args.config,
                                        policy, probe)
        print(f"round-trip: pufferlib.torch_pufferl.PuffeRL.load_weights OK - "
              f"max param diff {pdiff:.3e}, max logit diff {ldiff:.3e}")
        if pdiff != 0.0:
            raise SystemExit("round-trip params differ - checkpoint NOT trainer-compatible")

    if spec.width:
        print("Path-A caveat: context features are loader-only. Treat any val-accuracy "
              "lift as a screen; rollout/Elo confirmation requires Path-B engine obs "
              "integration and re-extraction.")
    print(f"result | arm={spec.arm} | requested_head_loss={args.head_loss} | "
          f"head_loss={head_loss} | val_checksum={val_checksum} | "
          f"val_exact_legacy_metric={v_exact:.3f} | checkpoint={out_path}")


if __name__ == "__main__":
    main()
