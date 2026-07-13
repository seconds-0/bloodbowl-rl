#!/usr/bin/env python
"""convert_checkpoint.py — torch state_dict <-> CUDA flat-fp32 checkpoint.

PufferLib's two training backends save incompatible checkpoint formats:

  * TORCH backend (pufferlib/torch_pufferl.py save_weights/load_weights):
    torch.save(policy.state_dict()) — what training/bc_pretrain.py emits.
  * CUDA backend (src/bindings.cu save_weights/load_weights): a raw
    little-endian flat fp32 dump of `master_weights`, the parameter
    Allocator's buffer, with NO header — parameter identity is purely
    positional.

This tool converts between them so `puffer train bloodbowl
--load-model-path <bc_cuda.bin>` (native CUDA backend) can warm-start from
a BC-pretrained torch checkpoint, and CUDA run checkpoints can be pulled
back into torch for analysis/eval.

CUDA parameter order (traced through vendor/PufferLib source):
  policy_weights_create (src/models.cu) registers params in the order
  encoder -> decoder -> network into the params Allocator, and
  alloc_create (src/kernels.cu) lays them out in registration order:

    1. encoder.weight   (hidden, obs)        encoder_reg_params, models.cu
    2. decoder.weight   (sum(acts)+1, hidden) decoder_reg_params; row
       layout per assemble_decoder_grad: rows 0..sum(acts)-1 are the
       action-logit units (head order = action head order), the LAST row
       is the value head. No logstd row for discrete action spaces.
    3. network.weights[i] (3*hidden, hidden) for i in 0..num_layers-1,
       mingru_reg_params; column-chunk order within 3*hidden is
       (hidden, gate, proj) per the mingru_gate kernel — identical to the
       torch MinGRU's `.chunk(3, dim=-1)`.

  puf_mm computes out = x @ W^T with W stored (out_features, in_features)
  — exactly nn.Linear — so every 2-D tensor maps 1:1 with no transpose.
  Neither backend normalizes observations (raw uint8 cast to float), so
  the mapping is semantically faithful, not just shape-compatible.

ALIGNMENT INVARIANT: alloc_create aligns each tensor's offset to 16 bytes.
The flat blob is a dense concatenation ONLY if every parameter tensor's
numel is a multiple of 4 floats (16 B). True for this architecture (all
sizes are multiples of 512); asserted below so an arch change that breaks
it fails loudly instead of silently shearing the mapping.

BIASES: the torch policy's nn.Linear encoder/decoder/value layers have
bias terms; the CUDA backend's layers are pure matmuls with NO biases.
  torch -> cuda: biases are DROPPED (a warning reports each max|bias| so
    you can judge the warm-start fidelity loss).
  cuda -> torch: biases are zero-filled.

OBS-V4 LINEAGE: the default obs size is 2782 (obs v4, decision-support
planes) — 16,066,560 bytes = 4,016,640 fp32 for heads (30, 33, 391) /
hidden 512 / 3 layers. The encoder input dim is part of the parameter count,
so older checkpoints cannot be loaded into a current policy. For obs-v3
(1612; 13,670,400 bytes) or obs-v2 (832; 12,072,960 bytes) checkpoints, pass
the corresponding explicit --obs-size.

Verified against a real artifact (obs-v2 lineage): a CUDA-backend
checkpoint from a GPU training run is exactly 12,072,960 bytes =
3,018,240 fp32 = this layout's total for obs 832 / heads (30, 33, 391) /
hidden 512 / 3 layers. The cuda -> torch -> cuda round trip is
byte-identical and the converted state_dict loads + forwards in the real
torch policy (training/test_convert_checkpoint.py).

Usage (PufferLib venv python):
  vendor/PufferLib/.venv/bin/python training/convert_checkpoint.py \\
      --to-cuda training/checkpoints/bc_bloodbowl.bin -o bc_cuda.bin
  vendor/PufferLib/.venv/bin/python training/convert_checkpoint.py \\
      --to-torch checkpoints/bloodbowl/<run>/<step>.bin -o run_torch.bin
"""

import argparse
import configparser
import os
import sys

import numpy as np
import torch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Mirrors ACT_SIZES in puffer/bloodbowl/binding.c and bc_pretrain.py.
DEFAULT_ACT_SIZES = (30, 33, 391)
# BBE_OBS_SIZE (obs v4, decision-support planes). Older lineages are a
# different parameter count — convert with an explicit --obs-size:
# obs-v3 (TZ planes) = 1612, obs-v2 = 832.
DEFAULT_OBS_SIZE = 2782
OBS_V3_SIZE = 1612
LEGACY_OBS_SIZE = 832
DEFAULT_CONFIG = os.path.join(ROOT, "puffer", "config", "bloodbowl.ini")

# fp32 tensors must start 16-byte aligned for the blob to stay dense
# (alloc_create in src/kernels.cu).
ALIGN_ELEMS = 4


def read_policy_arch(config_path):
    """hidden_size / num_layers from the [policy] section of the run config."""
    p = configparser.ConfigParser()
    if not p.read([config_path]):
        raise SystemExit(f"cannot read config {config_path}")
    try:
        sec = p["policy"]
        return int(sec["hidden_size"]), int(sec["num_layers"])
    except KeyError as e:
        raise SystemExit(
            f"{config_path} lacks [policy] hidden_size/num_layers ({e}); "
            "pass --hidden-size/--num-layers explicitly")


def cuda_layout(hidden, num_layers, obs_size, act_sizes):
    """[(name, shape, offset_in_floats)] in CUDA registration order + total."""
    od = sum(act_sizes)
    entries, off = [], 0
    for name, shape in (
        [("encoder.weight", (hidden, obs_size)),
         ("decoder.weight", (od + 1, hidden))]
        + [(f"network.{i}.weight", (3 * hidden, hidden))
           for i in range(num_layers)]
    ):
        n = int(np.prod(shape))
        if n % ALIGN_ELEMS:
            raise SystemExit(
                f"{name} numel {n} not a multiple of {ALIGN_ELEMS}: the CUDA "
                "Allocator would insert alignment padding and the flat blob "
                "would no longer be a dense concatenation — converter must "
                "be taught about padding holes first (src/kernels.cu "
                "alloc_create)")
        entries.append((name, shape, off))
        off += n
    return entries, off


# torch state_dict keys (pufferlib.models Policy(DefaultEncoder,
# DefaultDecoder, MinGRU)) that carry weights mapped into the blob.
def torch_weight_keys(num_layers):
    return (["encoder.encoder.weight", "decoder.decoder.weight",
             "decoder.value_function.weight"]
            + [f"network.layers.{i}.weight" for i in range(num_layers)])


# Bias keys present in the torch policy but absent from the CUDA backend.
BIAS_KEYS = ("encoder.encoder.bias", "decoder.decoder.bias",
             "decoder.value_function.bias")


def torch_to_cuda(state_dict, hidden, num_layers, obs_size, act_sizes):
    """state_dict -> flat little-endian fp32 blob (np.ndarray)."""
    sd = {k.replace("module.", ""): v.detach().cpu().float()
          for k, v in state_dict.items()}
    expected = set(torch_weight_keys(num_layers)) | set(BIAS_KEYS)
    unexpected = sorted(set(sd) - expected)
    missing = sorted(set(torch_weight_keys(num_layers)) - set(sd))
    if unexpected or missing:
        raise SystemExit(f"state_dict mismatch — unexpected keys "
                         f"{unexpected}, missing keys {missing}; is this a "
                         "torch-backend policy checkpoint for this config?")

    entries, total = cuda_layout(hidden, num_layers, obs_size, act_sizes)
    blob = np.zeros(total, dtype="<f4")

    def put(offset, shape, tensor):
        if tuple(tensor.shape) != tuple(shape):
            raise SystemExit(f"shape mismatch at offset {offset}: blob slot "
                             f"{shape} vs tensor {tuple(tensor.shape)}")
        n = int(np.prod(shape))
        blob[offset:offset + n] = tensor.numpy().astype("<f4").ravel()

    by_name = dict((name, (shape, off)) for name, shape, off in entries)

    shape, off = by_name["encoder.weight"]
    put(off, shape, sd["encoder.encoder.weight"])

    # decoder.weight rows 0..od-1 = action logits, last row = value head
    shape, off = by_name["decoder.weight"]
    dec = torch.cat([sd["decoder.decoder.weight"],
                     sd["decoder.value_function.weight"]], dim=0)
    put(off, shape, dec)

    for i in range(num_layers):
        shape, off = by_name[f"network.{i}.weight"]
        put(off, shape, sd[f"network.layers.{i}.weight"])

    dropped = [(k, sd[k].abs().max().item()) for k in BIAS_KEYS if k in sd]
    if any(mx != 0.0 for _, mx in dropped):
        print("WARNING: CUDA backend has no bias terms — dropping:",
              file=sys.stderr)
        for k, mx in dropped:
            print(f"  {k}  max|b| = {mx:.4e}", file=sys.stderr)
    return blob


def cuda_to_torch(blob, hidden, num_layers, obs_size, act_sizes):
    """flat fp32 blob -> torch state_dict (biases zero-filled)."""
    entries, total = cuda_layout(hidden, num_layers, obs_size, act_sizes)
    if blob.size != total:
        raise SystemExit(f"blob has {blob.size} floats, layout expects "
                         f"{total} — wrong config (hidden/layers/obs/acts)?")
    od = sum(act_sizes)

    def take(name):
        shape, off = next((s, o) for n, s, o in entries if n == name)
        n = int(np.prod(shape))
        return torch.from_numpy(
            blob[off:off + n].astype(np.float32).reshape(shape).copy())

    dec = take("decoder.weight")
    sd = {
        "encoder.encoder.weight": take("encoder.weight"),
        "encoder.encoder.bias": torch.zeros(hidden),
        "decoder.decoder.weight": dec[:od].clone(),
        "decoder.decoder.bias": torch.zeros(od),
        "decoder.value_function.weight": dec[od:od + 1].clone(),
        "decoder.value_function.bias": torch.zeros(1),
    }
    for i in range(num_layers):
        sd[f"network.layers.{i}.weight"] = take(f"network.{i}.weight")
    return sd


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    direction = ap.add_mutually_exclusive_group(required=True)
    direction.add_argument("--to-cuda", metavar="TORCH_BIN",
                           help="torch state_dict checkpoint -> flat fp32 blob")
    direction.add_argument("--to-torch", metavar="CUDA_BIN",
                           help="flat fp32 blob -> torch state_dict checkpoint")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--config", default=DEFAULT_CONFIG,
                    help="run config with [policy] hidden_size/num_layers")
    ap.add_argument("--hidden-size", type=int)
    ap.add_argument("--num-layers", type=int)
    ap.add_argument("--obs-size", type=int, default=DEFAULT_OBS_SIZE,
                    help=f"encoder input dim (default {DEFAULT_OBS_SIZE} = "
                         f"obs v4; pass {OBS_V3_SIZE} for obs-v3 or "
                         f"{LEGACY_OBS_SIZE} for obs-v2 lineage checkpoints)")
    ap.add_argument("--act-sizes", default=",".join(map(str, DEFAULT_ACT_SIZES)),
                    help="comma-separated action head sizes")
    args = ap.parse_args()

    act_sizes = tuple(int(x) for x in args.act_sizes.split(","))
    if args.hidden_size and args.num_layers:
        hidden, num_layers = args.hidden_size, args.num_layers
    else:
        hidden, num_layers = read_policy_arch(args.config)
        hidden = args.hidden_size or hidden
        num_layers = args.num_layers or num_layers

    entries, total = cuda_layout(hidden, num_layers, args.obs_size, act_sizes)
    desc = (f"hidden {hidden} x{num_layers} layers, obs {args.obs_size}, "
            f"heads {act_sizes} -> {total} fp32 ({total * 4} bytes)")

    if args.to_cuda:
        # weights_only=False: our own trusted checkpoint, full-pickle (PyTorch
        # 2.6+ defaults weights_only=True, which rejects the training-state pickle).
        sd = torch.load(args.to_cuda, map_location="cpu", weights_only=False)
        blob = torch_to_cuda(sd, hidden, num_layers, args.obs_size, act_sizes)
        blob.tofile(args.out)
        print(f"torch -> cuda: {args.to_cuda} -> {args.out} ({desc})")
    else:
        nbytes = os.path.getsize(args.to_torch)
        if nbytes != total * 4:
            raise SystemExit(f"{args.to_torch} is {nbytes} bytes, layout "
                             f"expects {total * 4} ({desc})")
        blob = np.fromfile(args.to_torch, dtype="<f4")
        sd = cuda_to_torch(blob, hidden, num_layers, args.obs_size, act_sizes)
        torch.save(sd, args.out)
        print(f"cuda -> torch: {args.to_torch} -> {args.out} ({desc}; "
              "biases zero-filled)")


if __name__ == "__main__":
    main()
