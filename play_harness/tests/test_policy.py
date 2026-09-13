import importlib.util
import json
import os
import random
import shutil

import numpy as np
import pytest
import torch

from play_harness import engine as E
from play_harness.policy import (MinGRUPolicy, joint_logprob, load_checkpoint,
                                 random_policy, select_joint)

from .conftest import CHAIN25, PUFFER_MODELS


def _obs_stream(n=400, seed=5):
    eng = E.Engine(seed, home_team=1, away_team=2)
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        out.append(eng.obs(0))
        if eng.step(*rng.choice(eng.legal()).tuple) == E.STEP_TERMINAL:
            break
    return out


def test_checkpoint_matches_pufferlib_models(chain25):
    if not os.path.exists(PUFFER_MODELS):
        pytest.skip("pufferlib models.py not available")
    policy, prov = chain25
    assert prov["checkpoint_sha256"].startswith("109c55d3")
    spec = importlib.util.spec_from_file_location("puffer_models", PUFFER_MODELS)
    pm = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pm)
    ref = pm.Policy(pm.DefaultEncoder(E.OBS_SIZE, 512),
                    pm.DefaultDecoder(list(E.ACT_SIZES), 512), pm.MinGRU(512, 3))
    ref.load_state_dict(policy.state_dict())
    ref.eval()
    torch_kernel = MinGRUPolicy(kernel="torch")
    torch_kernel.load_state_dict(policy.state_dict())
    s_ref, s_t, s_n = ref.initial_state(1, "cpu"), torch_kernel.initial_state(1), \
        policy.initial_state(1)
    worst_t, worst_n = 0.0, 0.0
    for obs in _obs_stream():
        x = torch.from_numpy(obs).reshape(1, -1)
        with torch.no_grad():
            lr, vr, s_ref = ref.forward_eval(x, s_ref)
        lt, vt, s_t = torch_kernel.forward_eval(x, s_t)
        ln, vn, s_n = policy.forward_eval(x, s_n)
        lr = torch.cat(lr, -1)
        worst_t = max(worst_t, float((lt - lr).abs().max()), float((vt - vr[:, 0]).abs().max()))
        worst_n = max(worst_n, float((ln - lr).abs().max()))
    assert worst_t == 0.0
    assert worst_n < 1e-3


def test_lineage_is_enforced(tmp_path, chain25):
    blob = tmp_path / "ck.bin"
    shutil.copy(CHAIN25, blob)
    with pytest.raises(ValueError, match="lineage"):
        load_checkpoint(str(blob))
    lineage = json.load(open(CHAIN25 + ".lineage.json"))
    lineage["compatibility"]["observation_abi"] = "obs-v5"
    json.dump(lineage, open(str(blob) + ".lineage.json", "w"))
    with pytest.raises(ValueError, match="observation_abi"):
        load_checkpoint(str(blob))


def test_select_joint_stays_inside_support():
    policy = random_policy(seed=2, scale=0.5)
    eng = E.Engine(8)
    rng = random.Random(1)
    gen = torch.Generator().manual_seed(0)
    state = policy.initial_state(1)
    windows = 0
    for _ in range(600):
        dec = eng.decision_team
        support = eng.joint_support(dec)
        legal = {E.unpack_tuple(v) for v in support}
        logits, _, state = policy.forward_eval(torch.from_numpy(eng.obs(dec)).reshape(1, -1),
                                               state)
        for _ in range(8):
            tup, lp, masks = select_joint(logits[0], support, "sample", gen)
            assert tup in legal
            assert abs(joint_logprob(logits[0], masks, tup) - lp) < 1e-5
        tup, _, _ = select_joint(logits[0], support, "argmax")
        best_type = max({t for t, _, _ in legal}, key=lambda t: float(logits[0][t]))
        assert tup[0] == best_type
        windows += 1
        if eng.step(*rng.choice(sorted(legal))) == E.STEP_TERMINAL:
            break
    assert windows > 100


def test_select_joint_rejects_empty_support():
    with pytest.raises(ValueError):
        select_joint(torch.zeros(454), np.array([], dtype=np.uint32))
