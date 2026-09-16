"""Recurrence and environment parity fixtures (bbplay-parity-fixture-v1).

A fixture is a directory with manifest.json and steps.npz describing ONE
policy row across consecutive env c_steps, recorded by some backend (the
native CUDA evaluator on the rig, or this harness for self-tests). A fixture
root is a directory holding several fixture directories (one per trace and
seat); find_fixtures() accepts either.

manifest.json
  schema            "bbplay-parity-fixture-v1"
  backend           "native-cuda-fp32" | "bbplay-cpu" | "dry-run-numpy" | ...
  checkpoint_sha256 blob digest (must match the policy under test)
  module_sha256     compiled _C digest when native, else null
  precision_bytes   4 for fp32 (bf16 fixtures are not parity evidence)
  kernel            gate kernel of the recorder when known ("native", "torch",
                    "native-cuda")
  policy_row        0 (HOME) or 1 (AWAY)
  env               {seed, episode, home_team, away_team, skillup_max_players,
                     skillup_max_each, skillup_secondary_pct, max_decisions}
                    seed is the per-env seed (vec base seed + env index);
                    episode is the bbplay `episode` argument of the FIRST match
                    in the trace (each later match is episode + 1)
  opponent          free text ("contact-bot", "self", ...)
  tolerance         {logprob, value, logits} suggested absolute tolerances
  trace             optional {name, env_index, base_seed, ...}

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
optional
  logits          f32    (T, 454)  raw logits of forward t
  terminal        uint8  (T,)      terminal flag delivered with obs t (the
                                   previous c_step ended a match)
  support         uint32 (N,)      packed joint support of this row, all steps
                                   concatenated (t | arg << 10 | sq << 20)
  support_offsets int64  (T+1,)    support[offsets[t]:offsets[t+1]] is step t
  masked_logits   f32    (T, 454)  logits with -inf outside masks
  probs           f32    (T, 454)  per-head softmax under masks (float64 math)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys

import numpy as np

from . import engine as E

SCHEMA = "bbplay-parity-fixture-v1"
NONE_PACKED = E.pack_tuple(0, E.ARG_NONE, E.SQ_NONE)
HEAD_BOUNDS = ((0, E.ACT_SIZES[0]),
               (E.ACT_SIZES[0], E.ACT_SIZES[0] + E.ACT_SIZES[1]),
               (E.ACT_SIZES[0] + E.ACT_SIZES[1], E.MASK_SIZE))

REQUIRED = ("obs", "reset", "deciding", "masks", "actions", "logprob", "value", "env_tuple")

# Proposed acceptance thresholds for torch-vs-native parity (see
# docs/play-harness/native-parity-2026-09-16.md for the reasons). Exact items
# are integrity checks; the probability items bound what can move outcomes.
ACCEPTANCE = {
    "env_obs_mismatch_steps": 0,          # byte-identical observations
    "consistency_violations": 0,          # masks, support, waiting rows, resets
    "joint_tv_max": 1e-3,                 # worst single decision
    "joint_tv_mean": 2e-6,                # expected per-decision divergence
    "masked_head_prob_max_abs_diff": 1e-3,
    "masked_head_argmax_agreement_min": 0.999,
    "logprob_max_abs_diff": 1e-3,
    "value_max_abs_diff": 1e-3,
    "logit_step0_max_abs_diff": 1e-3,
}
# Range of one side's touchdowns in a game used by the outcome bound
# (sum over decisions of TV bounds the trajectory TV distance).
TD_RANGE_PER_GAME = 6.0


# ----------------------------------------------------------------- format
def find_fixtures(path):
    """A fixture directory, or every fixture directory under a root (sorted)."""
    if os.path.isfile(os.path.join(path, "manifest.json")):
        return [path]
    found = []
    for dirpath, _dirs, files in os.walk(path):
        if "manifest.json" in files and "steps.npz" in files:
            found.append(dirpath)
    return sorted(found)


def validate_arrays(arrays, where="fixture"):
    missing = [k for k in REQUIRED if k not in arrays]
    if missing:
        raise ValueError(f"{where}: missing arrays {missing}")
    t = arrays["obs"].shape[0]
    shapes = {"obs": (t, E.OBS_SIZE), "reset": (t,), "deciding": (t,),
              "masks": (t, E.MASK_SIZE), "actions": (t, 3), "logprob": (t,),
              "value": (t,), "env_tuple": (t, 3), "logits": (t, E.MASK_SIZE),
              "terminal": (t,), "support_offsets": (t + 1,),
              "masked_logits": (t, E.MASK_SIZE), "probs": (t, E.MASK_SIZE)}
    for key, shape in shapes.items():
        if key in arrays and arrays[key].shape != shape:
            raise ValueError(f"{where}: {key} shape {arrays[key].shape}, expected {shape}")
    if arrays["obs"].dtype != np.uint8:
        raise ValueError(f"{where}: obs dtype {arrays['obs'].dtype}, expected uint8")
    if ("support" in arrays) != ("support_offsets" in arrays):
        raise ValueError(f"{where}: support and support_offsets must appear together")
    if "support" in arrays:
        off = arrays["support_offsets"]
        if off[0] != 0 or off[-1] != arrays["support"].shape[0] or np.any(np.diff(off) < 1):
            raise ValueError(f"{where}: support_offsets are not a monotone cover of support")
    return t


def load_fixture(path):
    with open(os.path.join(path, "manifest.json")) as f:
        manifest = json.load(f)
    if manifest.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {manifest.get('schema')!r}")
    with np.load(os.path.join(path, "steps.npz")) as npz:
        arrays = {k: npz[k] for k in npz.files}
    validate_arrays(arrays, where=path)
    return manifest, arrays


def save_fixture(out_dir, manifest, arrays, overwrite=False):
    """Write one fixture directory. Refuses to overwrite a finished fixture."""
    if manifest.get("schema") != SCHEMA:
        raise ValueError("manifest schema must be " + SCHEMA)
    validate_arrays(arrays, where=out_dir)
    if not overwrite and os.path.exists(os.path.join(out_dir, "manifest.json")):
        raise FileExistsError(f"{out_dir}: fixture already exists")
    os.makedirs(out_dir, exist_ok=True)
    tmp = os.path.join(out_dir, "steps.tmp.npz")
    np.savez_compressed(tmp, **arrays)
    os.replace(tmp, os.path.join(out_dir, "steps.npz"))
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1, sort_keys=True)
    return out_dir


def pack_support(rows):
    """List of per-step packed support arrays -> (flat uint32, offsets int64)."""
    counts = [len(r) for r in rows]
    offsets = np.zeros(len(rows) + 1, dtype=np.int64)
    np.cumsum(counts, out=offsets[1:])
    flat = (np.concatenate([np.asarray(r, dtype=np.uint32) for r in rows])
            if rows else np.zeros(0, dtype=np.uint32))
    return flat, offsets


def support_at(arrays, t):
    off = arrays["support_offsets"]
    return arrays["support"][off[t]:off[t + 1]]


# ------------------------------------------------------------------- math
def split_heads(row):
    return [row[..., a:b] for a, b in HEAD_BOUNDS]


def split_masks(mask_row):
    return [np.asarray(m).astype(bool) for m in split_heads(np.asarray(mask_row))]


def masked_log_softmax(x, mask):
    """float64 log-softmax of x over mask (last axis); -inf outside the mask."""
    x = np.asarray(x, dtype=np.float64)
    mask = np.asarray(mask, dtype=bool)
    if not mask.any(axis=-1).all():
        raise ValueError("masked_log_softmax: empty mask")
    masked = np.where(mask, x, -np.inf)
    m = masked.max(axis=-1, keepdims=True)
    with np.errstate(invalid="ignore", divide="ignore"):
        shifted = masked - m
        lse = np.log(np.exp(shifted).sum(axis=-1, keepdims=True))
        out = shifted - lse
    return np.where(mask, out, -np.inf)


def head_probs(logits, masks=None):
    """Per-head softmax (float64), concatenated to 454 columns.

    masks=None is the unmasked per-head softmax of the 5.0 logit-parity table;
    otherwise each head is normalized over its mask and is zero outside it.
    """
    logits = np.asarray(logits, dtype=np.float64)
    out = []
    for h, (a, b) in enumerate(HEAD_BOUNDS):
        x = logits[..., a:b]
        m = np.ones(x.shape, dtype=bool) if masks is None else \
            np.asarray(masks)[..., a:b].astype(bool)
        out.append(np.exp(masked_log_softmax(x, m)))
    return np.concatenate(out, axis=-1)


def per_head_tv(p, q):
    """Total-variation distance per head between two 454-column head-prob rows.
    Returns (..., 3)."""
    p = np.asarray(p, dtype=np.float64)
    q = np.asarray(q, dtype=np.float64)
    return np.stack([0.5 * np.abs(p[..., a:b] - q[..., a:b]).sum(axis=-1)
                     for a, b in HEAD_BOUNDS], axis=-1)


def unpack_support(packed):
    packed = np.asarray(packed, dtype=np.int64).reshape(-1)
    return [(packed >> (10 * h)) & 1023 for h in range(3)]


def conditional_masks(support, tup):
    """Per-head masks of the sequential exact support conditioned on tup's prefix
    (the rollout mask row sample_logits writes)."""
    values = unpack_support(support)
    prefix = np.ones(values[0].shape[0], dtype=bool)
    masks = []
    for h, size in enumerate(E.ACT_SIZES):
        m = np.zeros(size, dtype=bool)
        m[values[h][prefix]] = True
        masks.append(m)
        prefix &= values[h] == int(tup[h])
    return masks


_conditional_masks = conditional_masks  # historical name


def joint_distribution(logits, support):
    """Exact joint probability of every distinct tuple in the packed support
    under sequential sampling (type, arg | type, square | type,arg), float64.
    Returns (unique packed tuples, probabilities)."""
    uniq = np.unique(np.asarray(support, dtype=np.int64).reshape(-1))
    t, a, s = unpack_support(uniq)
    heads = split_heads(np.asarray(logits, dtype=np.float64).reshape(-1))
    probs = np.ones(uniq.shape[0], dtype=np.float64)
    # head 0 over the distinct types
    m0 = np.zeros(E.ACT_SIZES[0], dtype=bool)
    m0[t] = True
    lp0 = masked_log_softmax(heads[0], m0)
    probs *= np.exp(lp0[t])
    for ty in np.unique(t):
        rows = t == ty
        m1 = np.zeros(E.ACT_SIZES[1], dtype=bool)
        m1[a[rows]] = True
        lp1 = masked_log_softmax(heads[1], m1)
        probs[rows] *= np.exp(lp1[a[rows]])
        for ar in np.unique(a[rows]):
            rows2 = rows & (a == ar)
            m2 = np.zeros(E.ACT_SIZES[2], dtype=bool)
            m2[s[rows2]] = True
            lp2 = masked_log_softmax(heads[2], m2)
            probs[rows2] *= np.exp(lp2[s[rows2]])
    return uniq, probs


def joint_tv(logits_a, logits_b, support):
    _, pa = joint_distribution(logits_a, support)
    _, pb = joint_distribution(logits_b, support)
    return 0.5 * float(np.abs(pa - pb).sum())


def joint_logprob(logits, masks, action):
    """log p(action) under stored per-head conditional masks (float64)."""
    heads = split_heads(np.asarray(logits, dtype=np.float64).reshape(-1))
    total = 0.0
    for h in range(3):
        lp = masked_log_softmax(heads[h], np.asarray(masks[h], dtype=bool))
        total += float(lp[int(action[h])])
    return total


def head_argmax(logits, masks=None):
    logits = np.asarray(logits, dtype=np.float64)
    out = []
    for h, (a, b) in enumerate(HEAD_BOUNDS):
        x = logits[..., a:b]
        if masks is not None:
            x = np.where(np.asarray(masks)[..., a:b].astype(bool), x, -np.inf)
        out.append(np.argmax(x, axis=-1))
    return out


# ------------------------------------------------------------- consistency
def fixture_consistency(arrays):
    """Recorder self-consistency (exact items) and recorded-logit arithmetic.

    Exact: waiting rows carry the singleton NONE support and tuple; recorded
    actions lie in the support; masks equal the support conditioned on the
    recorded tuple; step 0 resets; reset equals (t == 0 or terminal).
    """
    t_steps = arrays["obs"].shape[0]
    out = {"steps": int(t_steps), "violations": 0, "details": []}

    def bad(kind, t):
        out["violations"] += 1
        if len(out["details"]) < 20:
            out["details"].append({"kind": kind, "step": int(t)})

    if t_steps and not arrays["reset"][0]:
        bad("step0_not_reset", 0)
    if "terminal" in arrays:
        want = arrays["terminal"].astype(bool).copy()
        want[0] = True
        for t in np.nonzero(want != arrays["reset"].astype(bool))[0]:
            bad("reset_differs_from_terminal", t)
    if "support" in arrays:
        for t in range(t_steps):
            sup = support_at(arrays, t)
            act = tuple(int(v) for v in arrays["actions"][t])
            packed = E.pack_tuple(*act)
            if not arrays["deciding"][t]:
                if sup.shape[0] != 1 or int(sup[0]) != NONE_PACKED or packed != NONE_PACKED:
                    bad("waiting_row_not_singleton_none", t)
            if packed not in set(int(v) for v in sup):
                bad("action_outside_support", t)
                continue
            want = np.concatenate(conditional_masks(sup, act)).astype(np.uint8)
            if not np.array_equal(want, arrays["masks"][t].astype(np.uint8)):
                bad("masks_differ_from_support", t)
    if "logits" in arrays:
        lp_diff = 0.0
        for t in range(t_steps):
            lp = joint_logprob(arrays["logits"][t], split_masks(arrays["masks"][t]),
                               arrays["actions"][t])
            lp_diff = max(lp_diff, abs(lp - float(arrays["logprob"][t])))
        out["recorded_logprob_vs_recorded_logits_max_abs"] = lp_diff
    if "probs" in arrays and "logits" in arrays:
        want = head_probs(arrays["logits"], arrays["masks"])
        out["recorded_probs_vs_recorded_logits_max_abs"] = float(
            np.abs(want - arrays["probs"].astype(np.float64)).max())
    return out


# --------------------------------------------------------------- env parity
def _engine_for(env, episode):
    return E.Engine(env["seed"], episode=episode,
                    home_team=env.get("home_team", -1), away_team=env.get("away_team", -1),
                    skillup_max_players=env.get("skillup_max_players", 4),
                    skillup_max_each=env.get("skillup_max_each", 2),
                    skillup_secondary_pct=env.get("skillup_secondary_pct", 0.0),
                    max_decisions=env.get("max_decisions", 4096))


def check_env_parity(manifest, arrays, follow_terminals=True, check_support=True):
    """Rebuild the match on the bbplay shim and require byte-identical policy-row
    observations at every recorded step. Returns the first mismatching step or None.

    With follow_terminals the next match is rebuilt as episode + 1 after each
    terminal c_step, and the recorded reset flag must mark exactly those steps.
    """
    env = manifest["env"]
    row = manifest["policy_row"]
    episode = int(env.get("episode", 0))
    eng = _engine_for(env, episode)
    have_support = check_support and "support" in arrays
    for t in range(arrays["obs"].shape[0]):
        if not np.array_equal(eng.obs(row), arrays["obs"][t]):
            return t
        if bool(eng.decision_team == row) != bool(arrays["deciding"][t]):
            return t
        if have_support:
            if not np.array_equal(np.sort(eng.joint_support(row).astype(np.int64)),
                                  np.sort(support_at(arrays, t).astype(np.int64))):
                return t
        rc = eng.step(*arrays["env_tuple"][t])
        if rc < 0:
            return t
        nxt = t + 1
        if rc == E.STEP_TERMINAL:
            if not follow_terminals:
                return None
            if nxt < arrays["obs"].shape[0] and not arrays["reset"][nxt]:
                return nxt
            episode += 1
            eng.close()
            eng = _engine_for(env, episode)
        elif nxt < arrays["obs"].shape[0] and arrays["reset"][nxt]:
            return nxt
    return None


def find_episode(manifest, arrays, candidates=range(0, 8)):
    """bbplay episode argument whose first observation matches step 0, or None."""
    env = dict(manifest["env"])
    row = manifest["policy_row"]
    for ep in candidates:
        eng = _engine_for(env, ep)
        match = np.array_equal(eng.obs(row), arrays["obs"][0])
        eng.close()
        if match:
            return ep
    return None


# ------------------------------------------------------------ policy parity
def check_policy_parity(policy, manifest, arrays):
    """Replay the recorded observation stream through the torch policy with the
    recorded reset boundaries. Returns max absolute errors."""
    import torch
    from .policy import joint_logprob as torch_joint_logprob  # float32, like the recorders
    state = policy.initial_state(1)
    worst = {"logprob": 0.0, "value": 0.0, "logits": 0.0}
    for t in range(arrays["obs"].shape[0]):
        if arrays["reset"][t]:
            state = policy.initial_state(1)
        obs = torch.from_numpy(arrays["obs"][t]).reshape(1, -1)
        logits, value, state = policy.forward_eval(obs, state)
        lp = torch_joint_logprob(logits[0], split_masks(arrays["masks"][t]),
                                 arrays["actions"][t])
        worst["logprob"] = max(worst["logprob"], abs(lp - float(arrays["logprob"][t])))
        worst["value"] = max(worst["value"], abs(float(value[0]) - float(arrays["value"][t])))
        if "logits" in arrays:
            worst["logits"] = max(worst["logits"],
                                  float((logits[0] - torch.from_numpy(arrays["logits"][t]))
                                        .abs().max()))
    return worst


def replay_policy(policy, arrays):
    """Harness forward over the recorded obs stream. Returns (logits f32 (T,454),
    value f32 (T,), resets applied)."""
    import torch
    t_steps = arrays["obs"].shape[0]
    logits_all = np.empty((t_steps, E.MASK_SIZE), dtype=np.float32)
    value_all = np.empty(t_steps, dtype=np.float32)
    state = policy.initial_state(1)
    resets = 0
    for t in range(t_steps):
        if arrays["reset"][t]:
            state = policy.initial_state(1)
            resets += 1
        logits, value, state = policy.forward_eval(
            torch.from_numpy(arrays["obs"][t]).reshape(1, -1), state)
        logits_all[t] = logits[0].numpy()
        value_all[t] = float(value[0])
    return logits_all, value_all, resets


def compare_logits(arrays, logits, value, tolerance=1e-4):
    """Metrics of harness (logits, value) against a recorded fixture. The keys of
    the 5.0 logit-parity table come first; distribution metrics follow."""
    ref = arrays["logits"].astype(np.float64)
    got = np.asarray(logits, dtype=np.float64)
    t_steps = ref.shape[0]
    d_logit = np.abs(got - ref)
    step_max = d_logit.max(axis=1)
    over = np.nonzero(step_max > tolerance)[0]
    d_value = np.abs(np.asarray(value, dtype=np.float64) - arrays["value"].astype(np.float64))
    p_ref = head_probs(ref)
    p_got = head_probs(got)
    masks = arrays["masks"]
    pm_ref = head_probs(ref, masks)
    pm_got = head_probs(got, masks)
    deciding = arrays["deciding"].astype(bool)
    am_ref, am_got = head_argmax(ref), head_argmax(got)
    amm_ref, amm_got = head_argmax(ref, masks), head_argmax(got, masks)
    tv = per_head_tv(pm_ref, pm_got)
    lp_diff = np.array([abs(joint_logprob(got[t], split_masks(masks[t]), arrays["actions"][t])
                            - float(arrays["logprob"][t])) for t in range(t_steps)])
    out = {
        "steps": int(t_steps),
        "deciding_steps": int(deciding.sum()),
        "reset_steps": int(arrays["reset"].astype(bool).sum()),
        "logit_step0_max_abs_diff": float(step_max[0]),
        "logit_max_abs_diff": float(d_logit.max()),
        "logit_mean_abs_diff": float(d_logit.mean()),
        "logit_max_rel_diff": float((d_logit / np.maximum(1.0, np.abs(ref))).max()),
        "recorded_logit_abs_max": float(np.abs(ref).max()),
        "logit_abs_diff_by_step": {str(t): float(step_max[t])
                                   for t in (0, 1, 10, 50, 100, 200, t_steps - 1)
                                   if 0 <= t < t_steps},
        "first_step_logit_abs_diff_over_tolerance": int(over[0]) if over.size else None,
        "head_prob_max_abs_diff": float(np.abs(p_got - p_ref).max()),
        "value_max_abs_diff": float(d_value.max()),
        "value_mean_abs_diff": float(d_value.mean()),
        "unmasked_head_argmax_agreement": [float((a == b).mean()) for a, b in zip(am_ref, am_got)],
        "masked_head_prob_max_abs_diff": float(np.abs(pm_got - pm_ref).max()),
        "logprob_max_abs_diff": float(lp_diff.max()),
        "logprob_mean_abs_diff": float(lp_diff.mean()),
        "masked_head_argmax_agreement": [
            float((a[deciding] == b[deciding]).mean()) if deciding.any() else 1.0
            for a, b in zip(amm_ref, amm_got)],
        "head_tv_max": [float(tv[deciding, h].max()) if deciding.any() else 0.0
                        for h in range(3)],
        "head_tv_mean": [float(tv[deciding, h].mean()) if deciding.any() else 0.0
                         for h in range(3)],
    }
    if "support" in arrays:
        jtv = np.array([joint_tv(ref[t], got[t], support_at(arrays, t))
                        for t in np.nonzero(deciding)[0]], dtype=np.float64)
        out["joint_tv_max"] = float(jtv.max()) if jtv.size else 0.0
        out["joint_tv_mean"] = float(jtv.mean()) if jtv.size else 0.0
        out["joint_tv_p99"] = float(np.quantile(jtv, 0.99)) if jtv.size else 0.0
        out["joint_tv_sum"] = float(jtv.sum())
    return out


def aggregate(entries):
    """Worst case over fixtures for max-type keys, decision-weighted means."""
    if not entries:
        return {}
    agg = {"fixtures": len(entries),
           "steps": sum(e["steps"] for e in entries),
           "deciding_steps": sum(e["deciding_steps"] for e in entries),
           "reset_steps": sum(e["reset_steps"] for e in entries)}
    for key in ("logit_step0_max_abs_diff", "logit_max_abs_diff", "logit_max_rel_diff",
                "head_prob_max_abs_diff", "value_max_abs_diff", "masked_head_prob_max_abs_diff",
                "logprob_max_abs_diff", "joint_tv_max", "joint_tv_p99", "recorded_logit_abs_max"):
        vals = [e[key] for e in entries if key in e]
        if vals:
            agg[key] = max(vals)
    for key in ("logit_mean_abs_diff", "value_mean_abs_diff", "logprob_mean_abs_diff"):
        agg[key] = sum(e[key] * e["steps"] for e in entries) / max(1, agg["steps"])
    for key in ("unmasked_head_argmax_agreement",):
        agg[key] = [min(e[key][h] for e in entries) for h in range(3)]
    agg["masked_head_argmax_agreement"] = [min(e["masked_head_argmax_agreement"][h]
                                               for e in entries) for h in range(3)]
    agg["head_tv_max"] = [max(e["head_tv_max"][h] for e in entries) for h in range(3)]
    agg["head_tv_mean"] = [
        sum(e["head_tv_mean"][h] * e["deciding_steps"] for e in entries)
        / max(1, agg["deciding_steps"]) for h in range(3)]
    if all("joint_tv_sum" in e for e in entries):
        agg["joint_tv_mean"] = sum(e["joint_tv_sum"] for e in entries) / max(1, agg["deciding_steps"])
    firsts = [e["first_step_logit_abs_diff_over_tolerance"] for e in entries
              if e["first_step_logit_abs_diff_over_tolerance"] is not None]
    agg["first_step_logit_abs_diff_over_tolerance"] = min(firsts) if firsts else None
    return agg


def outcome_bound(joint_tv_mean, decisions_per_game):
    """Upper bound on |TD per game difference| for one side from a per-decision
    mean joint TV: trajectory TV <= sum of per-decision TVs, and one side's TDs
    lie in [0, TD_RANGE_PER_GAME]."""
    return TD_RANGE_PER_GAME * decisions_per_game * joint_tv_mean


def verdict(agg, consistency_violations, env_mismatches, thresholds=ACCEPTANCE):
    checks = {
        "env_obs_mismatch_steps": env_mismatches <= thresholds["env_obs_mismatch_steps"],
        "consistency_violations": consistency_violations <= thresholds["consistency_violations"],
        "masked_head_prob_max_abs_diff":
            agg["masked_head_prob_max_abs_diff"] <= thresholds["masked_head_prob_max_abs_diff"],
        "masked_head_argmax_agreement_min":
            min(agg["masked_head_argmax_agreement"])
            >= thresholds["masked_head_argmax_agreement_min"],
        "logprob_max_abs_diff": agg["logprob_max_abs_diff"] <= thresholds["logprob_max_abs_diff"],
        "value_max_abs_diff": agg["value_max_abs_diff"] <= thresholds["value_max_abs_diff"],
        "logit_step0_max_abs_diff":
            agg["logit_step0_max_abs_diff"] <= thresholds["logit_step0_max_abs_diff"],
    }
    if "joint_tv_max" in agg:
        checks["joint_tv_max"] = agg["joint_tv_max"] <= thresholds["joint_tv_max"]
        checks["joint_tv_mean"] = agg["joint_tv_mean"] <= thresholds["joint_tv_mean"]
    return {"pass": all(checks.values()), "checks": checks}


def compare_fixtures(fixture_paths, policies, check_env=True, tolerance=1e-4):
    """Compare every fixture against every harness kernel. policies maps a kernel
    name to a loaded MinGRUPolicy. Returns the result document."""
    result = {"schema": "bbplay-parity-compare-v1", "fixtures": [], "kernels": {},
              "acceptance": dict(ACCEPTANCE)}
    per_kernel = {name: [] for name in policies}
    env_mismatches = 0
    violations = 0
    gaps = []
    for path in fixture_paths:
        manifest, arrays = load_fixture(path)
        if "logits" not in arrays:
            raise ValueError(f"{path}: fixture has no logits; cannot compare distributions")
        entry = {"path": os.path.relpath(path, os.path.dirname(fixture_paths[0])
                                         if len(fixture_paths) == 1 else
                                         os.path.commonpath(fixture_paths)),
                 "backend": manifest.get("backend"), "policy_row": manifest["policy_row"],
                 "env": manifest["env"], "trace": manifest.get("trace"),
                 "checkpoint_sha256": manifest.get("checkpoint_sha256"),
                 "precision_bytes": manifest.get("precision_bytes"),
                 "terminal_steps": int(arrays["terminal"].astype(bool)[1:].sum())
                 if "terminal" in arrays else None,
                 "kernels": {}}
        cons = fixture_consistency(arrays)
        entry["consistency"] = cons
        violations += cons["violations"]
        if check_env:
            first = check_env_parity(manifest, arrays)
            entry["env_first_mismatch_step"] = first
            env_mismatches += 0 if first is None else 1
        kernel_logits = {}
        for name, policy in policies.items():
            logits, value, resets = replay_policy(policy, arrays)
            kernel_logits[name] = logits
            metrics = compare_logits(arrays, logits, value, tolerance=tolerance)
            metrics["state_resets_applied"] = resets
            entry["kernels"][name] = metrics
            per_kernel[name].append(metrics)
        if "native" in kernel_logits and "torch" in kernel_logits:
            gap = float(np.abs(kernel_logits["native"].astype(np.float64)
                               - kernel_logits["torch"]).max())
            entry["native_vs_torch_logit_max_abs_diff"] = gap
            gaps.append(gap)
        result["fixtures"].append(entry)
    for name, entries in per_kernel.items():
        agg = aggregate(entries)
        agg["verdict"] = verdict(agg, violations, env_mismatches)
        decisions_per_game = 307.0
        if "joint_tv_mean" in agg:
            agg["td_per_game_bound"] = outcome_bound(agg["joint_tv_mean"], decisions_per_game)
        result["kernels"][name] = agg
    result["env_mismatch_fixtures"] = env_mismatches
    result["consistency_violations"] = violations
    if gaps:
        result["native_vs_torch_logit_max_abs_diff"] = max(gaps)
    return result


# --------------------------------------------------------- harness recorder
def record_self_fixture(out_dir, policy, seed, policy_row=0, home_team=-1, away_team=-1,
                        max_steps=None, sampling_seed=0, checkpoint_sha256=None,
                        kernel=None):
    """Record a fixture from this harness (policy row vs the contact bot)."""
    from .policy import PolicySeat
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
        masks = conditional_masks(support, out["tuple"])
        if deciding:
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
    return save_fixture(out_dir, manifest, {k: np.stack(v) for k, v in rows.items()},
                        overwrite=True)


def record_selfplay_trace(out_root, policy, trace_name, seed, episode=0, steps=400,
                          max_decisions=4096, sampling_seed=0, checkpoint_sha256=None,
                          overwrite=False):
    """Harness backend of the rig recorder's trace shape: one policy drives BOTH
    seats with sampling and every-step recurrence, the trace continues across
    terminals (next match = episode + 1), and one fixture per seat is written
    with logits, terminal flags, packed support, masked logits and probs."""
    from .policy import PolicySeat
    env = {"seed": int(seed), "episode": int(episode), "home_team": -1, "away_team": -1,
           "skillup_max_players": 4, "skillup_max_each": 2, "skillup_secondary_pct": 0.0,
           "max_decisions": int(max_decisions)}
    eng = _engine_for(env, episode)
    seats = [PolicySeat(policy, r, mode="sample", seed=sampling_seed + r) for r in (0, 1)]
    rows = [{k: [] for k in ("obs", "reset", "terminal", "deciding", "masks", "actions",
                             "logprob", "value", "env_tuple", "logits", "support")}
            for _ in (0, 1)]
    terminal = True
    matches = 1
    for t in range(steps):
        decider = eng.decision_team
        outs, supports = [], []
        for r in (0, 1):
            if terminal:
                seats[r].state = policy.initial_state(1)
            obs = eng.obs(r)
            sup = eng.joint_support(r)
            outs.append(seats[r].step(obs, sup, decider == r))
            supports.append(sup)
            rows[r]["obs"].append(obs)
        tup = outs[decider]["tuple"]
        for r in (0, 1):
            rec = rows[r]
            rec["reset"].append(1 if terminal else 0)
            rec["terminal"].append(1 if terminal else 0)
            rec["deciding"].append(1 if decider == r else 0)
            rec["masks"].append(np.concatenate(
                conditional_masks(supports[r], outs[r]["tuple"])).astype(np.uint8))
            rec["actions"].append(np.array(outs[r]["tuple"], dtype=np.int32))
            rec["logprob"].append(np.float32(outs[r]["logprob"]))
            rec["value"].append(np.float32(outs[r]["value"]))
            rec["env_tuple"].append(np.array(tup, dtype=np.int32))
            rec["logits"].append(outs[r]["logits"])
            rec["support"].append(supports[r])
        rc = eng.step(*tup)
        if rc < 0:
            raise RuntimeError(f"selfplay trace step {t} refused: {rc}")
        terminal = rc == E.STEP_TERMINAL
        if terminal and t + 1 < steps:
            eng.close()
            episode += 1
            matches += 1
            eng = _engine_for(env, episode)
    written = []
    for r in (0, 1):
        rec = rows[r]
        arrays = {k: np.stack(rec[k]) for k in rec if k != "support"}
        arrays["support"], arrays["support_offsets"] = pack_support(rec["support"])
        arrays["masked_logits"] = np.where(arrays["masks"].astype(bool), arrays["logits"],
                                           -np.inf).astype(np.float32)
        arrays["probs"] = head_probs(arrays["logits"], arrays["masks"]).astype(np.float32)
        manifest = {"schema": SCHEMA, "backend": "bbplay-cpu",
                    "checkpoint_sha256": checkpoint_sha256, "module_sha256": None,
                    "precision_bytes": 4, "kernel": policy.kernel, "policy_row": r,
                    "env": env, "opponent": "self (same policy both seats)",
                    "tolerance": {"logprob": 1e-3, "value": 1e-3, "logits": 1e-2},
                    "trace": {"name": trace_name, "env_index": 0, "base_seed": int(seed),
                              "steps": int(steps), "matches": matches,
                              "sampling_seed": int(sampling_seed)}}
        out_dir = os.path.join(out_root, f"{trace_name}-row{r}")
        written.append(save_fixture(out_dir, manifest, arrays, overwrite=overwrite))
    return written


# --------------------------------------------------------------------- CLI
def _fmt(v):
    if isinstance(v, float):
        return f"{v:.3g}"
    if isinstance(v, list):
        return "[" + ", ".join(_fmt(x) for x in v) + "]"
    return str(v)


TABLE_KEYS = ("logit_step0_max_abs_diff", "logit_max_abs_diff", "head_prob_max_abs_diff",
              "value_max_abs_diff", "unmasked_head_argmax_agreement",
              "masked_head_prob_max_abs_diff", "masked_head_argmax_agreement",
              "logprob_max_abs_diff", "head_tv_max", "head_tv_mean",
              "joint_tv_max", "joint_tv_mean", "joint_tv_p99", "td_per_game_bound")


def summary_table(result):
    kernels = list(result["kernels"])
    lines = ["| Metric | " + " | ".join(kernels) + " |",
             "|---|" + "---|" * len(kernels)]
    for key in TABLE_KEYS:
        if all(key in result["kernels"][k] for k in kernels):
            lines.append(f"| {key} | " + " | ".join(_fmt(result["kernels"][k][key])
                                                   for k in kernels) + " |")
    cells = []
    for k in kernels:
        v = result["kernels"][k]["verdict"]
        failed = [c for c, ok in v["checks"].items() if not ok]
        cells.append("PASS" if v["pass"] else "FAIL " + ", ".join(failed))
    lines.append("| verdict | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="python -m play_harness.parity")
    sub = ap.add_subparsers(dest="cmd", required=True)
    rec = sub.add_parser("record-selfplay", help="harness self-play trace (both seats)")
    rec.add_argument("--checkpoint", required=True)
    rec.add_argument("--kernel", default="native", choices=["native", "torch"])
    rec.add_argument("--out", required=True)
    rec.add_argument("--trace", required=True)
    rec.add_argument("--seed", type=int, required=True)
    rec.add_argument("--episode", type=int, default=0)
    rec.add_argument("--steps", type=int, default=400)
    rec.add_argument("--max-decisions", type=int, default=4096)
    rec.add_argument("--sampling-seed", type=int, default=0)
    cmp_ = sub.add_parser("compare", help="compare fixtures with harness kernels")
    cmp_.add_argument("--fixtures", required=True)
    cmp_.add_argument("--checkpoint", required=True)
    cmp_.add_argument("--kernel", action="append", choices=["native", "torch"])
    cmp_.add_argument("--out", required=True)
    cmp_.add_argument("--no-env", action="store_true")
    cmp_.add_argument("--allow-sha-mismatch", action="store_true")
    args = ap.parse_args(argv)

    from .policy import load_checkpoint
    if args.cmd == "record-selfplay":
        policy, prov = load_checkpoint(args.checkpoint, kernel=args.kernel)
        paths = record_selfplay_trace(args.out, policy, args.trace, args.seed, args.episode,
                                      args.steps, args.max_decisions, args.sampling_seed,
                                      checkpoint_sha256=prov["checkpoint_sha256"])
        print(json.dumps({"written": paths}, indent=1))
        return 0
    paths = find_fixtures(args.fixtures)
    if not paths:
        print(f"no fixtures under {args.fixtures}", file=sys.stderr)
        return 2
    kernels = args.kernel or ["torch", "native"]
    policies, digest = {}, None
    for k in kernels:
        policies[k], prov = load_checkpoint(args.checkpoint, kernel=k)
        digest = prov["checkpoint_sha256"]
    for p in paths:
        with open(os.path.join(p, "manifest.json")) as f:
            m = json.load(f)
        if m.get("checkpoint_sha256") != digest and not args.allow_sha_mismatch:
            print(f"{p}: checkpoint sha {m.get('checkpoint_sha256')} != {digest}", file=sys.stderr)
            return 2
        if m.get("precision_bytes") != 4:
            print(f"{p}: precision_bytes {m.get('precision_bytes')} is not fp32", file=sys.stderr)
            return 2
    result = compare_fixtures(paths, policies, check_env=not args.no_env)
    result["checkpoint_sha256"] = digest
    import torch
    result["torch_version"] = torch.__version__
    text = json.dumps(result, indent=1, sort_keys=True, allow_nan=False)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w") as f:
        f.write(text + "\n")
    print(summary_table(result))
    print(f"fixtures={len(paths)} env_mismatch_fixtures={result['env_mismatch_fixtures']} "
          f"consistency_violations={result['consistency_violations']} "
          f"native_vs_torch_logit_max_abs_diff="
          f"{_fmt(result.get('native_vs_torch_logit_max_abs_diff'))}")
    return 0 if all(v["verdict"]["pass"] for v in result["kernels"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
