#!/usr/bin/env python
"""Round-trip tests for convert_checkpoint.py (torch <-> CUDA flat blob).

Run with the PufferLib venv:
  vendor/PufferLib/.venv/bin/python training/test_convert_checkpoint.py

Covers:
  1. layout totals: the current obs-v6 semantic ABI / obs-v4+v5 shared shape
     (16,066,560 bytes for obs 2782), the obs-v3 lineage (13,670,400 bytes for obs 1612), and the
     legacy obs-v2 lineage, which must match the real CUDA-backend artifact
     byte-for-byte (12,072,960 bytes for obs 832 / heads (30,33,391) /
     hidden 512 / 3 layers). Real blob path:
     training/checkpoints/cuda_real_*.bin or $CUDA_CKPT (obs-v2 lineage);
     round-trip tests fall back to a synthetic 2782-byte-shape blob if absent.
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
    BIAS_KEYS, DEFAULT_CONFIG, DEFAULT_OBS_SIZE, LEGACY_OBS_SIZE, OBS_V3_SIZE,
    cuda_layout, cuda_to_torch, read_policy_arch, torch_to_cuda,
    torch_weight_keys)

HIDDEN, NUM_LAYERS = read_policy_arch(DEFAULT_CONFIG)
ENTRIES, TOTAL = cuda_layout(HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
_, OBS_V3_TOTAL = cuda_layout(HIDDEN, NUM_LAYERS, OBS_V3_SIZE, ACT_SIZES)
_, LEGACY_TOTAL = cuda_layout(HIDDEN, NUM_LAYERS, LEGACY_OBS_SIZE, ACT_SIZES)


def find_real_blob():
    if os.environ.get("CUDA_CKPT"):
        return os.environ["CUDA_CKPT"]
    hits = sorted(glob.glob(os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "checkpoints", "cuda_real_*.bin")))
    return hits[0] if hits else None


def test_layout_matches_real_artifact():
    """Current and historical layout counts; obs-v2 matches real artifact."""
    assert TOTAL == 4_016_640, TOTAL  # 512x2782 + 455x512 + 3 x 1536x512
    assert OBS_V3_TOTAL == 3_417_600, OBS_V3_TOTAL  # 512x1612 + ...
    # Legacy obs-v2 lineage (832): pinned to the real GPU-run artifact.
    assert LEGACY_TOTAL == 3_018_240, LEGACY_TOTAL  # 512x832 + ...
    path = find_real_blob()
    if path is None:
        print("  (no real CUDA blob found — sizes pinned to 16,066,560 / "
              "13,670,400 / 12,072,960)")
        return
    nbytes = os.path.getsize(path)
    assert nbytes == LEGACY_TOTAL * 4, (nbytes, LEGACY_TOTAL * 4)
    print(f"  real artifact {os.path.basename(path)}: {nbytes} bytes == "
          f"{LEGACY_TOTAL} fp32 (obs-v2 lineage)  OK")


def load_blob():
    """(blob, src, obs_size): real artifacts are obs-v2 lineage (832);
    the synthetic fallback exercises the current 2782-byte default layout."""
    path = find_real_blob()
    if path is not None:
        return np.fromfile(path, dtype="<f4"), path, LEGACY_OBS_SIZE
    rng = np.random.default_rng(7)
    return rng.standard_normal(TOTAL).astype("<f4"), "<synthetic>", \
        DEFAULT_OBS_SIZE


def test_cuda_torch_cuda_byte_identical():
    blob, src, obs_size = load_blob()
    sd = cuda_to_torch(blob, HIDDEN, NUM_LAYERS, obs_size, ACT_SIZES)
    back = torch_to_cuda(sd, HIDDEN, NUM_LAYERS, obs_size, ACT_SIZES)
    assert blob.tobytes() == back.tobytes(), "cuda->torch->cuda not byte-identical"
    print(f"  cuda -> torch -> cuda byte-identical ({src}, obs {obs_size}, "
          f"{blob.nbytes} bytes)  OK")


def test_converted_state_dict_loads_and_forwards():
    blob, src, obs_size = load_blob()
    sd = cuda_to_torch(blob, HIDDEN, NUM_LAYERS, obs_size, ACT_SIZES)
    policy, _ = load_policy_like_trainer(DEFAULT_CONFIG, obs_size)
    policy.load_state_dict(sd)  # strict=True: keys must match exactly
    policy.eval()
    obs = torch.randint(0, 256, (8, obs_size), dtype=torch.uint8,
                        generator=torch.Generator().manual_seed(0))
    with torch.no_grad():
        state = policy.initial_state(obs.shape[0], device="cpu")
        logits, values, _ = policy.forward_eval(obs, state)
    assert tuple(logit.shape for logit in logits) == \
        tuple((8, n) for n in ACT_SIZES), [logit.shape for logit in logits]
    assert all(torch.isfinite(logit).all() for logit in logits)
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
