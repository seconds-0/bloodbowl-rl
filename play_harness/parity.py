"""Recurrence and environment parity fixtures (bbplay-parity-fixture-v1).

A fixture is a directory with manifest.json and steps.npz describing ONE
policy row across consecutive env c_steps, recorded by some backend (the
native CUDA evaluator on the rig, or this harness for self-tests).

manifest.json
  schema            "bbplay-parity-fixture-v1"
  backend           "native-cuda-fp32" | "bbplay-cpu" | ...
  checkpoint_sha256 blob digest (must match the policy under test)
  module_sha256     compiled _C digest when native, else null
  precision_bytes   4 for fp32 (bf16 fixtures are not parity evidence)
  kernel            gate kernel of the recorder when known ("native", "torch")
  policy_row        0 (HOME) or 1 (AWAY)
  env               {seed, episode, home_team, away_team, skillup_max_players,
                     skillup_max_each, skillup_secondary_pct, max_decisions}
                    seed is the per-env seed (vec base seed + env index)
  opponent          free text ("contact-bot", "frozen-bank:<sha>", ...)
  tolerance         {logprob, value, logits} suggested absolute tolerances

steps.npz (T = number of forwards of the policy row, in order)
  obs        uint8  (T, 2782)  policy-row observation fed to forward t
  reset      uint8  (T,)       1 when recurrent state was zeroed before forward t
  deciding   uint8  (T,)       1 when the policy row owned the decision
  masks      uint8  (T, 454)   effective conditional masks of the selected tuple
                               (the rollout mask row after exact joint sampling)
  actions    int32  (T, 3)     policy-row tuple (NONE, 32, 390 when waiting)
  logprob    f32    (T,)       joint log-probability of actions[t]
  value      f32    (T,)       value head output at forward t
  env_tuple  int32  (T, 3)     tuple c_step applied at step t (deciding row)
  logits     f32    (T, 454)   optional; raw logits when the backend exposes them
"""
from __future__ import annotations

import json
import os

import numpy as np
import torch

from . import engine as E
from .policy import PolicySeat, joint_logprob, select_joint

SCHEMA = "bbplay-parity-fixture-v1"


def load_fixture(path):
    with open(os.path.join(path, "manifest.json")) as f:
        manifest = json.load(f)
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {manifest.get('schema')!r}")
    arrays = dict(np.load(os.path.join(path, "steps.npz")))
    t = arrays["obs"].shape[0]
    for key, shape in (("obs", (t, E.OBS_SIZE)), ("reset", (t,)), ("deciding", (t,)),
                       ("masks", (t, E.MASK_SIZE)), ("actions", (t, 3)),
                       ("logprob", (t,)), ("value", (t,)), ("env_tuple", (t, 3))):
        if arrays[key].shape != shape:
            raise ValueError(f"{path}: {key} shape {arrays[key].shape}, expected {shape}")
    return manifest, arrays


def _split_masks(mask_row):
    a, b = E.ACT_SIZES[0], E.ACT_SIZES[0] + E.ACT_SIZES[1]
    return mask_row[:a].astype(bool), mask_row[a:b].astype(bool), mask_row[b:].astype(bool)


def check_policy_parity(policy, manifest, arrays):
    """Replay the recorded observation stream through the torch policy with the
    recorded reset boundaries. Returns max absolute errors."""
    state = policy.initial_state(1)
    worst = {"logprob": 0.0, "value": 0.0, "logits": 0.0}
    for t in range(arrays["obs"].shape[0]):
        if arrays["reset"][t]:
            state = policy.initial_state(1)
        obs = torch.from_numpy(arrays["obs"][t]).reshape(1, -1)
        logits, value, state = policy.forward_eval(obs, state)
        lp = joint_logprob(logits[0], _split_masks(arrays["masks"][t]), arrays["actions"][t])
        worst["logprob"] = max(worst["logprob"], abs(lp - float(arrays["logprob"][t])))
        worst["value"] = max(worst["value"], abs(float(value[0]) - float(arrays["value"][t])))
        if "logits" in arrays:
            worst["logits"] = max(worst["logits"],
                                  float((logits[0] - torch.from_numpy(arrays["logits"][t]))
                                        .abs().max()))
    return worst


def check_env_parity(manifest, arrays):
    """Rebuild the match on the bbplay shim and require byte-identical policy-row
    observations at every recorded step. Returns the first mismatching step or None."""
    env = manifest["env"]
    row = manifest["policy_row"]
    eng = E.Engine(env["seed"], episode=env.get("episode", 0),
                   home_team=env.get("home_team", -1), away_team=env.get("away_team", -1),
                   skillup_max_players=env.get("skillup_max_players", 4),
                   skillup_max_each=env.get("skillup_max_each", 2),
                   skillup_secondary_pct=env.get("skillup_secondary_pct", 0.0),
                   max_decisions=env.get("max_decisions", 4096))
    for t in range(arrays["obs"].shape[0]):
        if t > 0 and arrays["reset"][t]:
            return None  # the recorded match ended; later rows belong to a new match
        if not np.array_equal(eng.obs(row), arrays["obs"][t]):
            return t
        rc = eng.step(*arrays["env_tuple"][t])
        if rc < 0:
            return t
        if rc == E.STEP_TERMINAL:
            return None
    return None


def record_self_fixture(out_dir, policy, seed, policy_row=0, home_team=-1, away_team=-1,
                        max_steps=None, sampling_seed=0, checkpoint_sha256=None,
                        kernel=None):
    """Record a fixture from this harness (policy row vs the contact bot)."""
    eng = E.Engine(seed, home_team=home_team, away_team=away_team)
    seat = PolicySeat(policy, policy_row, mode="sample", seed=sampling_seed)
    rows = {k: [] for k in ("obs", "reset", "deciding", "masks", "actions", "logprob",
                            "value", "env_tuple", "logits")}
    t = 0
    while max_steps is None or t < max_steps:
        deciding = eng.decision_team == policy_row
        obs = eng.obs(policy_row)
        support = eng.joint_support(policy_row)
        out = seat.step(obs, support, deciding)
        _, _, masks = select_joint(out["logits"], support, mode="argmax")
        if deciding:
            # masks conditioned on the tuple actually sampled
            prefix_masks = _conditional_masks(support, out["tuple"])
            masks = prefix_masks
            tup = out["tuple"]
        else:
            tup = eng.legal()[eng.contact_bot_index()].tuple
        rows["obs"].append(obs)
        rows["reset"].append(1 if t == 0 else 0)
        rows["deciding"].append(1 if deciding else 0)
        rows["masks"].append(np.concatenate(masks).astype(np.uint8))
        rows["actions"].append(np.array(out["tuple"], dtype=np.int32))
        rows["logprob"].append(np.float32(out["logprob"]))
        rows["value"].append(np.float32(out["value"]))
        rows["env_tuple"].append(np.array(tup, dtype=np.int32))
        rows["logits"].append(out["logits"])
        rc = eng.step(*tup)
        t += 1
        if rc == E.STEP_TERMINAL:
            break
        if rc < 0:
            raise RuntimeError(f"self fixture step refused: {rc}")
    os.makedirs(out_dir, exist_ok=True)
    np.savez_compressed(os.path.join(out_dir, "steps.npz"),
                        **{k: np.stack(v) for k, v in rows.items()})
    manifest = {"schema": SCHEMA, "backend": "bbplay-cpu",
                "checkpoint_sha256": checkpoint_sha256, "module_sha256": None,
                "precision_bytes": 4, "kernel": kernel or policy.kernel,
                "policy_row": policy_row,
                "env": {"seed": int(seed), "episode": 0, "home_team": home_team,
                        "away_team": away_team, "skillup_max_players": 4,
                        "skillup_max_each": 2, "skillup_secondary_pct": 0.0,
                        "max_decisions": 4096},
                "opponent": "contact-bot",
                "tolerance": {"logprob": 1e-4, "value": 1e-4, "logits": 1e-4}}
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    return out_dir


def _conditional_masks(support, tup):
    packed = np.asarray(support, dtype=np.int64).reshape(-1)
    values = [(packed >> (10 * h)) & 1023 for h in range(3)]
    prefix = np.ones(packed.shape[0], dtype=bool)
    masks = []
    for h, size in enumerate(E.ACT_SIZES):
        m = np.zeros(size, dtype=bool)
        m[values[h][prefix]] = True
        masks.append(m)
        prefix &= values[h] == tup[h]
    return masks
