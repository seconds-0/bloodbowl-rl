#!/usr/bin/env python
"""Round-trip tests for convert_checkpoint.py (torch <-> CUDA flat blob).

Run with the PufferLib venv:
  vendor/PufferLib/.venv/bin/python training/test_convert_checkpoint.py

Covers:
  1. layout totals: the current obs-v7 ABI (16,207,872 bytes for obs 2851) and historical
     obs-v6 shape (16,066,560 bytes for obs 2782), the obs-v3 lineage (13,670,400 bytes for obs 1612), and the
     legacy obs-v2 lineage, which must match the real CUDA-backend artifact
     byte-for-byte (12,072,960 bytes for obs 832 / heads (30,33,391) /
     hidden 512 / 3 layers). Real blob path:
     training/checkpoints/cuda_real_*.bin or $CUDA_CKPT (obs-v2 lineage);
     round-trip tests fall back to a synthetic 2851-byte-shape blob if absent.
  2. cuda -> torch -> cuda is byte-identical.
  3. the cuda->torch state_dict loads into the REAL torch policy (built
     exactly like the trainer via bc_pretrain.load_policy_like_trainer)
     and forwards a dummy uint8 obs batch to finite logits of the right
     head shapes.
  4. torch -> cuda -> torch preserves every weight bit-exactly and
     zero-fills the biases the CUDA backend cannot represent.
"""

import glob
import json
import os
import sys
import tempfile
import unittest

import numpy as np
import torch

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bc_pretrain import ACT_SIZES, load_policy_like_trainer  # noqa: E402
from convert_checkpoint import (  # noqa: E402
    BIAS_KEYS, DEFAULT_CONFIG, DEFAULT_OBS_SIZE, LEGACY_OBS_SIZE, OBS_V3_SIZE,
    OBS_V6_SIZE,
    cuda_layout, cuda_to_torch, read_policy_arch, torch_to_cuda,
    torch_weight_keys, migrate_v6_blob_to_v7, publish_bytes_exclusive,
    validate_v6_source_lineage)

HIDDEN, NUM_LAYERS = read_policy_arch(DEFAULT_CONFIG)
ENTRIES, TOTAL = cuda_layout(HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
_, OBS_V3_TOTAL = cuda_layout(HIDDEN, NUM_LAYERS, OBS_V3_SIZE, ACT_SIZES)
_, OBS_V6_TOTAL = cuda_layout(HIDDEN, NUM_LAYERS, OBS_V6_SIZE, ACT_SIZES)
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
    assert TOTAL == 4_051_968, TOTAL  # 512x2851 + 455x512 + 3 x 1536x512
    from tools.checkpoint_lineage import EXPECTED_CHECKPOINT_BYTES
    assert TOTAL * 4 == EXPECTED_CHECKPOINT_BYTES
    assert OBS_V6_TOTAL == 4_016_640, OBS_V6_TOTAL
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
    the synthetic fallback exercises the current 2851-byte default layout."""
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


def test_v6_to_v7_zero_extension_preserves_old_function():
    rng = np.random.default_rng(17)
    src = rng.standard_normal(OBS_V6_TOTAL).astype("<f4")
    dst = migrate_v6_blob_to_v7(src, HIDDEN, NUM_LAYERS, ACT_SIZES)
    src_entries, _ = cuda_layout(HIDDEN, NUM_LAYERS, OBS_V6_SIZE, ACT_SIZES)
    dst_entries, _ = cuda_layout(HIDDEN, NUM_LAYERS, DEFAULT_OBS_SIZE, ACT_SIZES)
    src_map = {n: (s, o) for n, s, o in src_entries}
    dst_map = {n: (s, o) for n, s, o in dst_entries}
    sw = src[:HIDDEN * OBS_V6_SIZE].reshape(HIDDEN, OBS_V6_SIZE)
    dw = dst[:HIDDEN * DEFAULT_OBS_SIZE].reshape(HIDDEN, DEFAULT_OBS_SIZE)
    assert np.array_equal(sw[:, :814], dw[:, :814])
    assert np.array_equal(sw[:, 816:], dw[:, 816:OBS_V6_SIZE])
    assert np.count_nonzero(dw[:, 814:816]) == 0
    assert np.count_nonzero(dw[:, OBS_V6_SIZE:]) == 0
    for name in src_map:
        if name == "encoder.weight":
            continue
        shape, so = src_map[name]
        _, do = dst_map[name]
        n = int(np.prod(shape))
        assert src[so:so+n].tobytes() == dst[do:do+n].tobytes()
    x6 = rng.integers(0, 256, (32, OBS_V6_SIZE), dtype=np.uint8).astype(np.float32)
    x6[:, 814:816] = 0
    x7 = np.zeros((32, DEFAULT_OBS_SIZE), dtype=np.float32)
    x7[:, :OBS_V6_SIZE] = x6
    x7[:, OBS_V6_SIZE:] = rng.integers(0, 7, (32, 69))
    # Shape-dependent BLAS kernels may round differently. The algebraic bridge
    # is exact; measure numerical agreement rather than assuming bit identity.
    np.testing.assert_allclose(x6 @ sw.T, x7 @ dw.T, rtol=2e-6, atol=2e-3)


def test_v6_migration_requires_exact_provenance_and_finite_weights():
    with tempfile.TemporaryDirectory() as tmp:
        checkpoint = os.path.join(tmp, "v6.bin")
        lineage = checkpoint + ".lineage.json"
        np.zeros(OBS_V6_TOTAL, dtype="<f4").tofile(checkpoint)
        import hashlib
        sha = hashlib.sha256(open(checkpoint, "rb").read()).hexdigest()
        payload = {
            "checkpoint": {"bytes": os.path.getsize(checkpoint), "sha256": sha},
            "compatibility": {
                "observation_abi": "obs-v6", "observation_version": 6,
                "action_abi": "exact-joint-v1", "policy_hidden_size": HIDDEN,
                "policy_num_layers": NUM_LAYERS, "policy_expansion_factor": 1,
            },
        }
        with open(lineage, "w") as f:
            json.dump(payload, f)
        validate_v6_source_lineage(checkpoint, lineage, HIDDEN, NUM_LAYERS)
        payload["compatibility"]["observation_abi"] = "obs-v5"
        with open(lineage, "w") as f:
            json.dump(payload, f)
        try:
            validate_v6_source_lineage(checkpoint, lineage, HIDDEN, NUM_LAYERS)
            assert False, "same-sized obs-v5 provenance accepted"
        except SystemExit:
            pass
        bad = np.zeros(OBS_V6_TOTAL, dtype="<f4"); bad[4] = np.nan
        try:
            migrate_v6_blob_to_v7(bad, HIDDEN, NUM_LAYERS, ACT_SIZES)
            assert False, "non-finite source accepted"
        except SystemExit:
            pass
        destination = os.path.join(tmp, "destination")
        publish_bytes_exclusive(destination, b"first")
        try:
            publish_bytes_exclusive(destination, b"second")
            assert False, "existing destination replaced"
        except FileExistsError:
            pass
        assert open(destination, "rb").read() == b"first"


def test_migration_rejects_same_size_action_head_reordering():
    # These heads have the same sum and checkpoint size, but different meanings.
    source = np.zeros(OBS_V6_TOTAL, dtype="<f4")
    with unittest.TestCase().assertRaisesRegex(SystemExit, "action heads"):
        migrate_v6_blob_to_v7(source, HIDDEN, NUM_LAYERS, (33, 30, 391))


def load_tests(loader, tests, pattern):
    # Function tests must execute under unittest discovery as well as this CLI.
    return unittest.TestSuite(unittest.FunctionTestCase(value)
                              for name, value in sorted(globals().items())
                              if name.startswith("test_") and callable(value))


def main():
    result = unittest.TextTestRunner(verbosity=2).run(load_tests(None, None, None))
    if not result.wasSuccessful():
        raise SystemExit(1)


if __name__ == "__main__":
    main()
