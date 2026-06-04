#!/usr/bin/env python
"""bc_pretrain.py — behavioral-cloning pretraining from FUMBBL .bbp pairs.

Supervised warm-start for PPO: loads the (obs, mask, action) records that
`bb_lockstep --dump-pairs` extracted from real FUMBBL replays
(validation/extract_pairs.py; format documented in tools/bb_lockstep.c and
validation/README.md), builds THE SAME policy the trainer uses, and trains
masked cross-entropy on the three action heads (type 30 | arg 33 | sq 391).

Policy construction mirrors pufferlib.torch_pufferl.load_policy exactly —
the classes come from pufferlib.models and the hyperparameters from the
[policy]/[torch] sections of config/bloodbowl.ini layered over PufferLib's
default.ini, so the checkpoint state_dict is key-for-key what
PuffeRL.save_weights writes and `puffer train bloodbowl --load-model-path
<bc.bin>` warm-starts from it directly. The save->load round-trip through
the real pufferlib.torch_pufferl.PuffeRL.load_weights is verified after
every save.

Loss: per head, logits are masked with the record's stored 454-bit legality
mask (additive -1e9 on illegal entries) before softmax; the three CE terms
are summed. Reported: per-head accuracy (masked argmax == target) and top-1
legal-action match (all three heads correct at once).

BACKEND NOTE: this matches the TORCH backend's checkpoint layout
(PuffeRL.save_weights == torch.save(state_dict)); `puffer train ... --slowly
--load-model-path bc.bin` (and any CPU-only _C build, where load_policy
reads it at create time) warm-starts directly. The CUDA backend's
save/load_weights (src/bindings.cu) is a raw flat-fp32 master_weights blob
in CUDA parameter order — convert with training/convert_checkpoint.py
(`--to-cuda bc.bin -o bc_cuda.bin`) and warm-start the native backend via
the local load_model_path patch in pufferl.py. Note the CUDA layers carry
no bias terms, so the converter drops the torch biases (warned).

v0 LIMITATION — iid samples, zero recurrent state: each record is treated
as an independent sample and the MinGRU state is zeroed, so the network
only learns the zero-state map obs->action. Sequence-BC (replay-ordered
windows carrying recurrent state, matching PPO's rollout treatment) is v1;
it needs the same shards, just grouped by (replay_id, agent) and sorted by
cmd — the fields are already in the records.

Run with the PufferLib venv (torch):
  vendor/PufferLib/.venv/bin/python training/bc_pretrain.py
  vendor/PufferLib/.venv/bin/python training/bc_pretrain.py \\
      --steps 500 --batch-size 256 --device cpu --out training/checkpoints/bc.bin
"""

import argparse
import ast
import configparser
import glob
import os
import struct
import sys
import types

import numpy as np
import torch
import torch.nn.functional as F

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "vendor", "PufferLib"))

import pufferlib  # noqa: E402
import pufferlib.models  # noqa: E402

# Mirrors ACT_SIZES in puffer/bloodbowl/binding.c (asserted against the .bbp
# header's mask_size below — the shards only pin the sum).
ACT_SIZES = (30, 33, 391)
MAGIC, VERSION = b"BBP1", 1
HEADER_LEN = 16

REC_DTYPE = np.dtype([
    ("replay", "<u4"), ("cmd", "<u4"), ("agent", "u1"), ("pad", "u1", (3,)),
    ("obs", "u1", (832,)), ("mask", "u1", (454,)),
    ("type", "u1"), ("arg", "u1"), ("sq", "<u2"),
])


def load_shards(pair_dir):
    paths = sorted(glob.glob(os.path.join(pair_dir, "*.bbp")))
    if not paths:
        raise SystemExit(f"no .bbp shards in {pair_dir} — "
                         "run validation/extract_pairs.py first")
    shards, obs_size, mask_size = [], None, None
    for p in paths:
        with open(p, "rb") as f:
            raw = f.read()
        magic, ver, osz, msz = struct.unpack("<4sIII", raw[:HEADER_LEN])
        if magic != MAGIC or ver != VERSION:
            raise SystemExit(f"{p}: bad header {magic} v{ver}")
        if obs_size is None:
            obs_size, mask_size = osz, msz
            if (osz, msz) != (832, 454):
                raise SystemExit(f"{p}: obs/mask {osz}/{msz} unsupported by "
                                 "REC_DTYPE (832/454)")
        elif (osz, msz) != (obs_size, mask_size):
            raise SystemExit(f"{p}: header mismatch across shards")
        shards.append(np.frombuffer(raw[HEADER_LEN:], dtype=REC_DTYPE))
    recs = np.concatenate(shards)
    assert sum(ACT_SIZES) == mask_size, (ACT_SIZES, mask_size)
    return recs, obs_size, mask_size


def load_policy_like_trainer(config_path, obs_size):
    """pufferlib.torch_pufferl.load_policy minus the vec (sizes from .bbp)."""
    default_ini = os.path.join(os.path.dirname(os.path.dirname(
        os.path.realpath(pufferlib.__file__))), "config", "default.ini")
    p = configparser.ConfigParser()
    read = p.read([default_ini, config_path])
    if len(read) != 2:
        raise SystemExit(f"config read failed: wanted {default_ini} + "
                         f"{config_path}, got {read}")

    def section(name):
        out = {}
        for k, v in p[name].items():
            try:
                out[k] = ast.literal_eval(v)
            except (ValueError, SyntaxError):
                out[k] = v
        return out

    policy_kwargs = section("policy")
    torch_cfg = section("torch")
    network_cls = getattr(pufferlib.models, torch_cfg["network"])
    encoder_cls = getattr(pufferlib.models, torch_cfg["encoder"])
    decoder_cls = getattr(pufferlib.models, torch_cfg["decoder"])
    network = network_cls(**policy_kwargs)
    encoder = encoder_cls(obs_size, policy_kwargs["hidden_size"])
    decoder = decoder_cls(ACT_SIZES, policy_kwargs["hidden_size"])
    policy = pufferlib.models.Policy(encoder, decoder, network)
    desc = (f"{torch_cfg['encoder']} -> {torch_cfg['network']}"
            f"(hidden={policy_kwargs['hidden_size']}, "
            f"layers={policy_kwargs.get('num_layers')}) -> "
            f"{torch_cfg['decoder']}{ACT_SIZES}")
    return policy, desc


def split_by_replay(recs, val_frac, seed):
    rids = np.unique(recs["replay"])
    rng = np.random.default_rng(seed)
    rng.shuffle(rids)
    n_val = max(1, round(val_frac * len(rids)))
    val_ids = set(rids[:n_val].tolist())
    val_m = np.isin(recs["replay"], list(val_ids))
    return recs[~val_m], recs[val_m], sorted(val_ids)


def to_tensors(recs, device):
    obs = torch.from_numpy(np.ascontiguousarray(recs["obs"])).to(device)
    mask = torch.from_numpy(np.ascontiguousarray(recs["mask"])).to(device).bool()
    tgt = torch.stack([
        torch.from_numpy(recs["type"].astype(np.int64)),
        torch.from_numpy(recs["arg"].astype(np.int64)),
        torch.from_numpy(recs["sq"].astype(np.int64)),
    ], dim=1).to(device)
    return obs, mask, tgt


def forward_heads(policy, obs, device):
    """iid forward at zero recurrent state (the v0 limitation above)."""
    state = policy.initial_state(obs.shape[0], device=device)
    logits, _values, _state = policy.forward_eval(obs, state)
    return logits  # tuple of (B,30), (B,33), (B,391)


def masked_losses(logits, mask, tgt):
    """Per-head CE over mask-restricted logits; returns (loss, head_hits)."""
    off, losses, hits = 0, [], []
    for h, n in enumerate(ACT_SIZES):
        m = mask[:, off:off + n]
        off += n
        lg = logits[h].masked_fill(~m, -1e9)
        losses.append(F.cross_entropy(lg, tgt[:, h]))
        hits.append(lg.argmax(dim=1) == tgt[:, h])
    return sum(losses), hits


@torch.no_grad()
def evaluate(policy, obs, mask, tgt, device, batch=2048):
    policy.eval()
    tot, loss_sum = 0, 0.0
    head_hit = [0, 0, 0]
    exact_hit = 0
    for i in range(0, obs.shape[0], batch):
        o, m, t = obs[i:i + batch], mask[i:i + batch], tgt[i:i + batch]
        logits = forward_heads(policy, o, device)
        loss, hits = masked_losses(logits, m, t)
        loss_sum += loss.item() * o.shape[0]
        exact = torch.ones_like(hits[0])
        for h in range(3):
            head_hit[h] += hits[h].sum().item()
            exact &= hits[h]
        exact_hit += exact.sum().item()
        tot += o.shape[0]
    policy.train()
    return (loss_sum / tot, [h / tot for h in head_hit], exact_hit / tot)


def verify_roundtrip(out_path, obs_size, config_path, trained_policy, probe_obs):
    """Save->load through the REAL torch backend loader, then compare."""
    from pufferlib.torch_pufferl import PuffeRL
    fresh, _ = load_policy_like_trainer(config_path, obs_size)
    shim = types.SimpleNamespace(device="cpu", policy=fresh)
    PuffeRL.load_weights(shim, out_path)  # torch.load + module.-strip + load_state_dict
    ref = {k: v.detach().cpu() for k, v in trained_policy.state_dict().items()}
    got = fresh.state_dict()
    assert set(ref) == set(got), "state_dict key mismatch after round-trip"
    pdiff = max((ref[k].float() - got[k].float()).abs().max().item()
                for k in ref)
    trained_cpu, _ = load_policy_like_trainer(config_path, obs_size)
    trained_cpu.load_state_dict(ref)
    with torch.no_grad():
        a = forward_heads(trained_cpu, probe_obs.cpu(), "cpu")
        b = forward_heads(fresh, probe_obs.cpu(), "cpu")
    ldiff = max((x - y).abs().max().item() for x, y in zip(a, b))
    return pdiff, ldiff


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--pairs-dir", default=os.path.join(ROOT, "validation", "pairs"))
    ap.add_argument("--config", default=os.path.join(ROOT, "puffer", "config",
                                                     "bloodbowl.ini"))
    ap.add_argument("--out", default=os.path.join(ROOT, "training", "checkpoints",
                                                  "bc_bloodbowl.bin"))
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="auto",
                    help="auto (mps if available, else cpu) | cpu | mps | cuda")
    ap.add_argument("--log-every", type=int, default=25)
    args = ap.parse_args()

    device = args.device
    if device == "auto":
        device = "mps" if torch.backends.mps.is_available() else "cpu"
    torch.manual_seed(args.seed)

    recs, obs_size, mask_size = load_shards(args.pairs_dir)
    train_r, val_r, val_ids = split_by_replay(recs, args.val_frac, args.seed)
    print(f"pairs: {len(recs)} from {len(np.unique(recs['replay']))} replays "
          f"(obs {obs_size}B, mask {mask_size}b) | split BY REPLAY: "
          f"{len(train_r)} train / {len(val_r)} val (held out: {val_ids})")

    policy, desc = load_policy_like_trainer(args.config, obs_size)
    policy = policy.to(device).train()
    n_params = sum(p.numel() for p in policy.parameters())
    print(f"policy: {desc} | {n_params:,} params | device {device}")

    tr_obs, tr_mask, tr_tgt = to_tensors(train_r, device)
    va_obs, va_mask, va_tgt = to_tensors(val_r, device)
    opt = torch.optim.Adam(policy.parameters(), lr=args.lr)
    gen = torch.Generator().manual_seed(args.seed)

    first_loss = last_loss = None
    for step in range(args.steps):
        idx = torch.randint(0, tr_obs.shape[0], (args.batch_size,), generator=gen)
        logits = forward_heads(policy, tr_obs[idx], device)
        loss, hits = masked_losses(logits, tr_mask[idx], tr_tgt[idx])
        opt.zero_grad()
        loss.backward()
        opt.step()
        if first_loss is None:
            first_loss = loss.item()
        last_loss = loss.item()
        if step % args.log_every == 0 or step == args.steps - 1:
            exact = (hits[0] & hits[1] & hits[2]).float().mean().item()
            accs = [h.float().mean().item() for h in hits]
            print(f"step {step:4d} | loss {loss.item():7.4f} | "
                  f"acc type/arg/sq {accs[0]:.3f}/{accs[1]:.3f}/{accs[2]:.3f} | "
                  f"exact {exact:.3f}")

    v_loss, v_accs, v_exact = evaluate(policy, va_obs, va_mask, va_tgt, device)
    t_loss, t_accs, t_exact = evaluate(policy, tr_obs, tr_mask, tr_tgt, device)
    print(f"final train | loss {t_loss:.4f} | acc type/arg/sq "
          f"{t_accs[0]:.3f}/{t_accs[1]:.3f}/{t_accs[2]:.3f} | exact {t_exact:.3f}")
    print(f"final  val  | loss {v_loss:.4f} | acc type/arg/sq "
          f"{v_accs[0]:.3f}/{v_accs[1]:.3f}/{v_accs[2]:.3f} | exact {v_exact:.3f}")
    print(f"loss curve: {first_loss:.4f} -> {last_loss:.4f}")

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    # Exactly PuffeRL.save_weights: torch.save(policy.state_dict(), path).
    torch.save(policy.state_dict(), args.out)
    print(f"saved {args.out} ({os.path.getsize(args.out)} bytes)")

    probe = va_obs[:8] if len(va_obs) else tr_obs[:8]
    pdiff, ldiff = verify_roundtrip(args.out, obs_size, args.config, policy, probe)
    print(f"round-trip: pufferlib.torch_pufferl.PuffeRL.load_weights OK — "
          f"max param diff {pdiff:.3e}, max logit diff {ldiff:.3e}")
    if pdiff != 0.0:
        raise SystemExit("round-trip params differ — checkpoint NOT trainer-compatible")


if __name__ == "__main__":
    main()
