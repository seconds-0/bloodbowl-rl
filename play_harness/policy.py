"""CPU torch inference for native obs-v6 / exact-joint-v1 MinGRU checkpoints.

Architecture (pufferlib Policy(DefaultEncoder, DefaultDecoder, MinGRU) and the
native CUDA backend, which are the same weights): Linear(2782 -> 512), three
MinGRU layers with highway output, Linear(512 -> 454) logits plus a value row.
The native layers carry no biases; training/convert_checkpoint.py zero-fills
them, which is exact.

Two gate kernels are provided:
  native  the formulas the native CUDA rollout kernel evaluates
          (vendor/PufferLib src/models.cu mingru_gate, src/kernels.cu):
          fast_sigmoid for negative candidates and the branchy lerp.
  torch   pufferlib.models.MinGRU.forward_eval (exact sigmoid, torch.lerp).
The default is native because the checkpoints were trained and examined under
native rollout. play_harness/tests/test_parity_fixture.py decides the question
against rig-recorded native log-probabilities when a fixture exists.

Recurrence contract (PolicySeat): the policy is stepped on EVERY env c_step,
including waiting-coach steps whose support is the singleton NONE tuple, and
its state is zeroed once when a natural match starts. That is the native
evaluation-mode contract (training/puffer_recurrent_eval_state.patch): state
persists across rollout calls and clears only on terminal rows.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sys

import numpy as np
import torch
import torch.nn as nn

from . import engine as E

ROOT = E.ROOT
HIDDEN = 512
LAYERS = 3
CHECKPOINT_BYTES = 16_066_560
OBS_ABI = "obs-v6"
ACTION_ABI = "exact-joint-v1"
NONE_TUPLE = (0, E.ARG_NONE, E.SQ_NONE)

_FAST_TANH_P = (-2.76076847742355e-16, 2.00018790482477e-13, -8.60467152213735e-11,
                5.12229709037114e-08, 1.48572235717979e-05, 6.37261928875436e-04,
                4.89352455891786e-03)
_FAST_TANH_Q = (1.19825839466702e-06, 1.18534705686654e-04, 2.26843463243900e-03,
                4.89352518554385e-03)


def native_fast_tanh(x):
    v1 = x.clamp(-9.0, 9.0)
    v2 = v1 * v1
    p = v2 * _FAST_TANH_P[0] + _FAST_TANH_P[1]
    for c in _FAST_TANH_P[2:]:
        p = v2 * p + c
    p = v1 * p
    q = v2 * _FAST_TANH_Q[0] + _FAST_TANH_Q[1]
    for c in _FAST_TANH_Q[2:]:
        q = v2 * q + c
    return p / q


def native_fast_sigmoid(x):
    return ((native_fast_tanh(x * 0.5) + 1.0) * 0.5).clamp(0.0, 1.0)


def native_sigmoid(x):
    z = torch.exp(-x.abs())
    return torch.where(x >= 0, 1.0 / (1.0 + z), z / (1.0 + z))


def native_lerp(a, b, w):
    diff = b - a
    return torch.where(w.abs() < 0.5, a + w * diff, b - diff * (1.0 - w))


class _Encoder(nn.Module):
    def __init__(self, obs_size, hidden):
        super().__init__()
        self.encoder = nn.Linear(obs_size, hidden)


class _Decoder(nn.Module):
    def __init__(self, hidden, logits):
        super().__init__()
        self.decoder = nn.Linear(hidden, logits)
        self.value_function = nn.Linear(hidden, 1)


class _MinGRU(nn.Module):
    def __init__(self, hidden, layers):
        super().__init__()
        self.layers = nn.ModuleList(
            [nn.Linear(hidden, 3 * hidden, bias=False) for _ in range(layers)])


class MinGRUPolicy(nn.Module):
    """State-dict compatible with pufferlib Policy(DefaultEncoder, DefaultDecoder, MinGRU)."""

    def __init__(self, obs_size=E.OBS_SIZE, hidden=HIDDEN, layers=LAYERS,
                 act_sizes=E.ACT_SIZES, kernel="native"):
        super().__init__()
        if kernel not in ("native", "torch"):
            raise ValueError(f"unknown kernel {kernel!r}")
        self.kernel = kernel
        self.hidden = hidden
        self.num_layers = layers
        self.act_sizes = tuple(act_sizes)
        self.encoder = _Encoder(obs_size, hidden)
        self.decoder = _Decoder(hidden, int(sum(act_sizes)))
        self.network = _MinGRU(hidden, layers)

    def initial_state(self, batch=1):
        return torch.zeros(self.num_layers, batch, self.hidden)

    @torch.no_grad()
    def forward_eval(self, obs, state):
        x = torch.as_tensor(obs).reshape(-1, self.encoder.encoder.in_features).float()
        if state.shape != (self.num_layers, x.shape[0], self.hidden):
            raise ValueError(f"state shape {tuple(state.shape)} does not match batch")
        h = self.encoder.encoder(x)
        new_state = []
        for i, layer in enumerate(self.network.layers):
            cand, gate, proj = layer(h).chunk(3, dim=-1)
            if self.kernel == "native":
                g = torch.where(cand >= 0, cand + 0.5, native_fast_sigmoid(cand))
                out = native_lerp(state[i], g, native_sigmoid(gate))
                hw = native_sigmoid(proj)
            else:
                g = torch.where(cand >= 0, cand + 0.5, cand.sigmoid())
                out = torch.lerp(state[i], g, gate.sigmoid())
                hw = proj.sigmoid()
            h = hw * out + (1.0 - hw) * h
            new_state.append(out)
        logits = self.decoder.decoder(h)
        value = self.decoder.value_function(h).squeeze(-1)
        return logits, value, torch.stack(new_state, 0)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_lineage(checkpoint_path):
    sidecar = checkpoint_path + ".lineage.json"
    if not os.path.exists(sidecar):
        return None
    with open(sidecar) as f:
        return json.load(f)


def verify_lineage(checkpoint_path, lineage, digest):
    """Refuse anything that is not an obs-v6 / exact-joint-v1 512x3 blob."""
    if lineage is None:
        raise ValueError(f"{checkpoint_path}: missing .lineage.json sidecar")
    compat = lineage.get("compatibility", {})
    want = {"observation_abi": OBS_ABI, "observation_version": 6,
            "action_abi": ACTION_ABI, "policy_hidden_size": HIDDEN,
            "policy_num_layers": LAYERS}
    for key, value in want.items():
        if compat.get(key) != value:
            raise ValueError(f"lineage {key}={compat.get(key)!r}, expected {value!r}")
    if lineage.get("checkpoint", {}).get("sha256") != digest:
        raise ValueError("lineage checkpoint sha256 does not match the blob")


def load_checkpoint(path, kernel="native", require_lineage=True):
    """Native flat fp32 blob -> MinGRUPolicy. Returns (policy, provenance)."""
    size = os.path.getsize(path)
    if size != CHECKPOINT_BYTES:
        raise ValueError(f"{path}: {size} bytes, obs-v6 512x3 blob is {CHECKPOINT_BYTES}")
    digest = sha256_file(path)
    lineage = read_lineage(path)
    if require_lineage:
        verify_lineage(path, lineage, digest)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)
    from training.convert_checkpoint import cuda_to_torch
    blob = np.fromfile(path, dtype="<f4")
    state_dict = cuda_to_torch(blob, HIDDEN, LAYERS, E.OBS_SIZE, E.ACT_SIZES)
    policy = MinGRUPolicy(kernel=kernel)
    policy.load_state_dict(state_dict, strict=True)
    policy.eval()
    provenance = {"checkpoint_path": os.path.abspath(path), "checkpoint_sha256": digest,
                  "lineage": lineage, "kernel": kernel, "torch": torch.__version__}
    return policy, provenance


def random_policy(seed=0, kernel="native", scale=0.02):
    """Bias-free random weights for tests (same shapes as a real checkpoint)."""
    g = torch.Generator().manual_seed(int(seed))
    policy = MinGRUPolicy(kernel=kernel)
    with torch.no_grad():
        for name, param in policy.named_parameters():
            if name.endswith(".bias"):
                param.zero_()
            else:
                param.copy_(torch.randn(param.shape, generator=g) * scale)
    policy.eval()
    return policy


def check_temperature(temperature):
    t = float(temperature)
    if not (math.isfinite(t) and t > 0.0):
        raise ValueError(f"policy temperature must be finite and > 0, got {temperature!r}")
    return t


def select_joint(logits, support, mode="sample", generator=None, temperature=1.0):
    """Sequential exact joint selection (type, arg | type, square | type,arg).

    Mirrors sample_joint_logits in training/puffer_exact_joint_actions.patch
    and the native sampler. mode='argmax' is the conditional argmax.
    temperature T divides every head's logits before masking and selection
    (T = 1 is the trained policy exactly; argmax choices do not depend on T).
    The returned logprob is under the tempered distribution that was used.
    Returns (tuple, joint logprob, per-head support masks).
    """
    temperature = check_temperature(temperature)
    logits = torch.as_tensor(logits).reshape(-1)
    if temperature != 1.0:
        logits = logits / temperature
    packed = np.asarray(support, dtype=np.int64).reshape(-1)
    if packed.size == 0:
        raise ValueError("empty joint support")
    values = [(packed >> (10 * h)) & 1023 for h in range(3)]
    prefix = np.ones(packed.shape[0], dtype=bool)
    heads = torch.split(logits, E.ACT_SIZES)
    chosen, masks = [], []
    total = 0.0
    for h, size in enumerate(E.ACT_SIZES):
        support_h = np.zeros(size, dtype=bool)
        support_h[values[h][prefix]] = True
        if not support_h.any():
            raise ValueError(f"empty exact support at head {h}")
        mask_t = torch.from_numpy(support_h)
        masked = heads[h].masked_fill(~mask_t, float("-inf"))
        logp = torch.log_softmax(masked, dim=-1)
        if mode == "argmax":
            a = int(torch.argmax(masked).item())
        elif mode == "sample":
            a = int(torch.multinomial(logp.exp(), 1, generator=generator).item())
        else:
            raise ValueError(f"unknown mode {mode!r}")
        if not support_h[a]:
            raise AssertionError("selected value outside support")
        total += float(logp[a].item())
        chosen.append(a)
        masks.append(support_h)
        prefix &= values[h] == a
    if not prefix.any():
        raise AssertionError("selected tuple outside exact joint support")
    return tuple(chosen), total, masks


def joint_logprob(logits, masks, action):
    """log p(action) under stored per-head conditional masks (parity checks)."""
    logits = torch.as_tensor(logits).reshape(-1)
    heads = torch.split(logits, E.ACT_SIZES)
    total = 0.0
    for h, size in enumerate(E.ACT_SIZES):
        m = torch.as_tensor(np.asarray(masks[h], dtype=bool))
        logp = torch.log_softmax(heads[h].masked_fill(~m, float("-inf")), dim=-1)
        total += float(logp[int(action[h])].item())
    return total


class PolicySeat:
    """One policy coach with native evaluation-mode recurrence.

    step() must be called exactly once per env c_step, whoever decides.
    """

    def __init__(self, policy, seat, mode="sample", seed=0, provenance=None, temperature=1.0):
        if seat not in (0, 1):
            raise ValueError("seat must be 0 (HOME) or 1 (AWAY)")
        self.policy = policy
        self.seat = seat
        self.mode = mode
        self.temperature = check_temperature(temperature)
        self.seed = int(seed)
        self.provenance = provenance or {}
        self.generator = torch.Generator().manual_seed(self.seed)
        self.state = policy.initial_state(1)
        self.forwards = 0
        self.decisions = 0

    def reset_match(self):
        self.state = self.policy.initial_state(1)
        self.generator = torch.Generator().manual_seed(self.seed)
        self.forwards = 0
        self.decisions = 0

    def step(self, obs, support, deciding):
        logits, value, self.state = self.policy.forward_eval(
            torch.from_numpy(np.asarray(obs, dtype=np.uint8)).reshape(1, -1), self.state)
        self.forwards += 1
        logits = logits[0]
        if deciding:
            action, logprob, _ = select_joint(logits, support, self.mode, self.generator,
                                              temperature=self.temperature)
            self.decisions += 1
        else:
            packed = np.asarray(support).reshape(-1)
            if packed.size != 1 or E.unpack_tuple(packed[0]) != NONE_TUPLE:
                raise AssertionError("waiting row must carry the singleton NONE support")
            action, logprob = NONE_TUPLE, 0.0
        return {"tuple": action, "logprob": logprob, "value": float(value[0]),
                "logits": logits.numpy().astype(np.float32, copy=True)}
