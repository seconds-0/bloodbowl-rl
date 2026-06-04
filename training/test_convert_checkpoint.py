#!/usr/bin/env python
"""Round-trip tests for convert_checkpoint.py (torch <-> CUDA flat blob).

Run with the PufferLib venv:
  vendor/PufferLib/.venv/bin/python training/test_convert_checkpoint.py

Covers:
  1. layout total matches the real CUDA-backend artifact byte-for-byte
     (12,072,960 bytes for obs 832 / heads (30,33,391) / hidden 512 / 3
     layers). Real blob path: training/checkpoints/cuda_real_*.bin or
     $CUDA_CKPT; falls back to a synthetic random blob if absent.
  2. cuda -> torch -> cuda is byte-identical.
  3. the cuda->torch state_dict loads into the REAL torch policy (built
     exactly like the trainer via bc_pretrain.load_policy_like_trainer)
     and forwards a dummy uint8 obs batch to finite logits of the right
     head shapes.
  4. torch -> cuda -> torch preserves every weight bit-exactly and
     zero-fills the biases the CUDA backend cannot represent.
"""

import glob
import os
import sys

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bc_pretrain import ACT_SIZES, load_policy_like_trainer  # noqa: E402
from convert_checkpoint import (  # noqa: E402
    BIAS_KEYS, DEFAULT_CONFIG, DEFAULT_OBS_SIZE, cuda_layout, cuda_to_torch,
    read_policy_arch, torch_to_cuda, torch_weight_keys)

HIDDEN, NUM_LAYERS = read_policy_arch(DEFAULT_CONFIG)
ENTRIES, TOTAL = cuda_layout(HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)


def find_real_blob():
    if os.environ.get("CUDA_CKPT"):
        return os.environ["CUDA_CKPT"]
    hits = sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "checkpoints", "cuda_real_*.bin")))
    return hits[0] if hits else None


def test_layout_matches_real_artifact():
    """Layout float count == real CUDA save_weights file size."""
    assert TOTAL == 3_018_240, TOTAL  # 512x832 + 455x512 + 3 x 1536x512
    path = find_real_blob()
    if path is None:
        print("  (no real CUDA blob found — size pinned to 12,072,960 only)")
        return
    nbytes = os.path.getsize(path)
    assert nbytes == TOTAL * 4, (nbytes, TOTAL * 4)
    print(f"  real artifact {os.path.basename(path)}: {nbytes} bytes == "
          f"{TOTAL} fp32  OK")


def load_blob():
    path = find_real_blob()
    if path is not None:
        return np.fromfile(path, dtype="<f4"), path
    rng = np.random.default_rng(7)
    return rng.standard_normal(TOTAL).astype("<f4"), "<synthetic>"


def test_cuda_torch_cuda_byte_identical():
    blob, src = load_blob()
    sd = cuda_to_torch(blob, HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
    back = torch_to_cuda(sd, HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
    assert blob.tobytes() == back.tobytes(), "cuda->torch->cuda not byte-identical"
    print(f"  cuda -> torch -> cuda byte-identical ({src}, "
          f"{blob.nbytes} bytes)  OK")


def test_converted_state_dict_loads_and_forwards():
    blob, src = load_blob()
    sd = cuda_to_torch(blob, HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
    policy, _ = load_policy_like_trainer(DEFAULT_CONFIG, DEFAULT_OBS_SIZE)
    policy.load_state_dict(sd)  # strict=True: keys must match exactly
    policy.eval()
    obs = torch.randint(0, 256, (8, DEFAULT_OBS_SIZE), dtype=torch.uint8,
                        generator=torch.Generator().manual_seed(0))
    with torch.no_grad():
        state = policy.initial_state(obs.shape[0], device="cpu")
        logits, values, _ = policy.forward_eval(obs, state)
    assert tuple(l.shape for l in logits) == \
        tuple((8, n) for n in ACT_SIZES), [l.shape for l in logits]
    assert all(torch.isfinite(l).all() for l in logits)
    assert torch.isfinite(values).all()
    print(f"  state_dict from {src} loads strict + forwards "
          f"(heads {ACT_SIZES}, finite)  OK")


def test_torch_cuda_torch_preserves_weights():
    policy, _ = load_policy_like_trainer(DEFAULT_CONFIG, DEFAULT_OBS_SIZE)
    torch.manual_seed(3)
    for p in policy.parameters():  # make biases nonzero so the drop is real
        p.data.uniform_(-1, 1)
    ref = {k: v.detach().clone() for k, v in policy.state_dict().items()}
    blob = torch_to_cuda(ref, HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
    sd = cuda_to_torch(blob, HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
    for k in torch_weight_keys(NUM_LAYERS):
        assert torch.equal(ref[k], sd[k]), f"{k} not preserved bit-exactly"
    for k in BIAS_KEYS:
        assert torch.count_nonzero(ref[k]) > 0, f"test bias {k} was zero"
        assert torch.count_nonzero(sd[k]) == 0, f"{k} not zero-filled"
    blob2 = torch_to_cuda(sd, HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
    assert blob.tobytes() == blob2.tobytes()
    print("  torch -> cuda -> torch: weights bit-exact, biases zero-filled, "
          "re-blob byte-identical  OK")


def main():
    tests = [test_layout_matches_real_artifact,
             test_cuda_torch_cuda_byte_identical,
             test_converted_state_dict_loads_and_forwards,
             test_torch_cuda_torch_preserves_weights]
    for t in tests:
        print(f"{t.__name__}:")
        t()
    print(f"\nALL {len(tests)} TESTS PASSED")


if __name__ == "__main__":
    main()
