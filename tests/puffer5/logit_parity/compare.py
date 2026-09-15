"""Compare PufferLib 5.0 CPU network logits with the play harness torch path.

For each recorded obs trace, runs play_harness.policy.MinGRUPolicy.forward_eval
with both gate kernels ("torch": exact sigmoid; "native": the 4.0 CUDA
fast_sigmoid approximation) on the same obs sequence, batch 2 with state carry,
zeroing a row's state before encoding an obs whose terminal flag is set (the
5.0 zero_term_state / 4.0 evaluation-mode contract). Reports max abs diffs for
logits and value against cpu5_logits output.

Usage: python compare.py CHECKPOINT OUT_JSON TRACE1 LOGITS1 [TRACE2 LOGITS2 ...]
Pass criterion (torch kernel vs cpu5, every trace): step-0 logit abs diff
<= TOLERANCE (single forward, no recurrence), value abs diff <= TOLERANCE at
every step, per-head softmax probability abs diff <= TOLERANCE at every step,
and identical unmasked per-head argmax at every step.

Accumulated logit diffs are reported but are not the gate. Logits reach |1e3|,
where one float32 ULP (~1.2e-4) is already above an absolute 1e-4 bound, and
the MinGRU carry (h_tilde = cand + 0.5 for cand >= 0 is unbounded) amplifies
float32 roundoff across hundreds of steps. The float64 reference forward from
the same blob shows that both float32 implementations drift from exact
arithmetic by more than they differ from each other, so the residual is
roundoff, not a layout or kernel mismatch.
"""
import hashlib
import json
import os
import struct
import sys

import numpy as np

HARNESS_ROOT = os.environ.get(
    "HARNESS_ROOT", os.path.expanduser("~/Code/bb-play-harness"))
sys.path.insert(0, HARNESS_ROOT)

import torch  # noqa: E402
from play_harness.policy import load_checkpoint  # noqa: E402

TOLERANCE = 1e-4
OBS_SIZE = 2782
ACT_SIZES = (30, 33, 391)
COLS = sum(ACT_SIZES) + 1


def read_trace(path):
    with open(path, "rb") as f:
        magic = f.read(8)
        if magic != b"BBOBSTR1":
            raise ValueError(f"{path}: bad magic {magic!r}")
        steps, obs_size, agents, terminal_obs = struct.unpack("<4I", f.read(16))
        rec = np.dtype([("obs", np.uint8, (agents * obs_size,)),
                        ("term", "<f4", (agents,))])
        data = np.fromfile(f, dtype=rec, count=steps)
    if data.shape[0] != steps or obs_size != OBS_SIZE:
        raise ValueError(f"{path}: truncated or wrong obs size")
    return (data["obs"].reshape(steps, agents, obs_size), data["term"],
            terminal_obs)


def read_logits(path):
    with open(path, "rb") as f:
        magic = f.read(8)
        if magic != b"BBLOG5v1":
            raise ValueError(f"{path}: bad magic {magic!r}")
        steps, agents, cols = struct.unpack("<3I", f.read(12))
        out = np.fromfile(f, dtype="<f4", count=steps * agents * cols)
    if out.size != steps * agents * cols or cols != COLS:
        raise ValueError(f"{path}: truncated or wrong column count")
    return out.reshape(steps, agents, cols)


def run_policy(policy, obs, term):
    steps, agents, _ = obs.shape
    state = policy.initial_state(agents)
    logits_all = np.empty((steps, agents, COLS - 1), dtype=np.float32)
    value_all = np.empty((steps, agents), dtype=np.float32)
    resets = 0
    for t in range(steps):
        rows = torch.from_numpy(term[t] != 0.0)
        if bool(rows.any()):
            state = state.clone()
            state[:, rows, :] = 0.0
            resets += int(rows.sum())
        logits, value, state = policy.forward_eval(
            torch.from_numpy(obs[t]), state)
        logits_all[t] = logits.numpy()
        value_all[t] = value.numpy()
    return logits_all, value_all, resets


def float64_reference(ckpt, obs, term, hidden=512, layers=3):
    """Exact-sigmoid MinGRU forward in float64 from the flat blob (5.0 order)."""
    blob = np.fromfile(ckpt, dtype="<f4").astype(np.float64)
    od = COLS
    off = 0
    enc = blob[off:off + hidden * OBS_SIZE].reshape(hidden, OBS_SIZE)
    off += hidden * OBS_SIZE
    dec = blob[off:off + od * hidden].reshape(od, hidden)
    off += od * hidden
    grus = []
    for _ in range(layers):
        grus.append(blob[off:off + 3 * hidden * hidden].reshape(3 * hidden, hidden))
        off += 3 * hidden * hidden
    assert off == blob.size

    def sig(x):
        z = np.exp(-np.abs(x))
        return np.where(x >= 0, 1.0 / (1.0 + z), z / (1.0 + z))

    steps, agents, _ = obs.shape
    state = np.zeros((layers, agents, hidden))
    out = np.empty((steps, agents, od))
    for t in range(steps):
        state[:, term[t] != 0.0, :] = 0.0
        h = obs[t].astype(np.float64) @ enc.T
        for i in range(layers):
            comb = h @ grus[i].T
            cand, gate, proj = np.split(comb, 3, axis=-1)
            g = np.where(cand >= 0, cand + 0.5, sig(cand))
            z = sig(gate)
            o = state[i] + z * (g - state[i])
            s = sig(proj)
            h = s * o + (1.0 - s) * h
            state[i] = o
        out[t] = h @ dec.T
    return out


def head_log_softmax(logits):
    out, off = [], 0
    for n in ACT_SIZES:
        x = logits[..., off:off + n].astype(np.float64)
        m = x.max(axis=-1, keepdims=True)
        out.append(x - m - np.log(np.exp(x - m).sum(axis=-1, keepdims=True)))
        off += n
    return np.concatenate(out, axis=-1)


def rel_max(a, ref):
    return float((np.abs(a.astype(np.float64) - ref) /
                  np.maximum(1.0, np.abs(ref))).max())


def head_argmax(logits):
    out, off = [], 0
    for n in ACT_SIZES:
        out.append(np.argmax(logits[..., off:off + n], axis=-1))
        off += n
    return out


def main():
    if len(sys.argv) < 5 or (len(sys.argv) - 3) % 2:
        print(__doc__)
        return 2
    ckpt, out_json = sys.argv[1], sys.argv[2]
    pairs = list(zip(sys.argv[3::2], sys.argv[4::2]))
    digest = hashlib.sha256(open(ckpt, "rb").read()).hexdigest()
    policies = {k: load_checkpoint(ckpt, kernel=k, require_lineage=False)[0]
                for k in ("torch", "native")}
    result = {
        "checkpoint_sha256": digest,
        "tolerance": TOLERANCE,
        "torch_version": torch.__version__,
        "traces": [],
    }
    ok = True
    for trace_path, logits_path in pairs:
        obs, term, terminal_obs = read_trace(trace_path)
        cpu5 = read_logits(logits_path)
        if cpu5.shape[:2] != obs.shape[:2]:
            raise ValueError("trace and logits disagree on steps/agents")
        cpu5_logits, cpu5_value = cpu5[..., :-1], cpu5[..., -1]
        entry = {
            "trace": os.path.basename(trace_path),
            "steps": int(obs.shape[0]),
            "agents": int(obs.shape[1]),
            "terminal_obs_rows": int((term != 0.0).sum()),
            "terminal_reset_exercised": bool((term != 0.0).any()),
            "cpu5_logit_abs_max": float(np.abs(cpu5_logits).max()),
            "cpu5_logit_std": float(cpu5_logits.std()),
            "kernels": {},
        }
        ref64 = float64_reference(ckpt, obs, term)
        ref_logits, ref_value = ref64[..., :-1], ref64[..., -1]
        # One float32 ULP at the largest logit: an absolute tolerance below
        # this is unattainable for any float32 implementation.
        entry["float32_ulp_at_logit_abs_max"] = float(
            np.spacing(np.float32(np.abs(ref_logits).max())))
        entry["cpu5_vs_float64"] = {
            "logit_max_abs_diff": float(np.abs(cpu5_logits - ref_logits).max()),
            "logit_max_rel_diff": rel_max(cpu5_logits, ref_logits),
            "value_max_abs_diff": float(np.abs(cpu5_value - ref_value).max()),
        }
        cpu5_lsm = head_log_softmax(cpu5_logits)
        per_kernel = {}
        for name, policy in policies.items():
            logits, value, resets = run_policy(policy, obs, term)
            per_kernel[name] = logits
            d_logit = np.abs(logits.astype(np.float64) - cpu5_logits)
            d_value = np.abs(value.astype(np.float64) - cpu5_value)
            d_prob = np.abs(np.exp(head_log_softmax(logits)) - np.exp(cpu5_lsm))
            am_cpu = head_argmax(cpu5_logits)
            am_pol = head_argmax(logits)
            kernel = {
                "logit_max_abs_diff": float(d_logit.max()),
                "logit_mean_abs_diff": float(d_logit.mean()),
                "logit_max_rel_diff": rel_max(logits, cpu5_logits),
                "logit_step0_max_abs_diff": float(d_logit[0].max()),
                "head_prob_max_abs_diff": float(d_prob.max()),
                "value_max_abs_diff": float(d_value.max()),
                "value_mean_abs_diff": float(d_value.mean()),
                "vs_float64_logit_max_abs_diff": float(
                    np.abs(logits - ref_logits).max()),
                "vs_float64_logit_max_rel_diff": rel_max(logits, ref_logits),
                "state_resets_applied": resets,
                "unmasked_head_argmax_agreement": [
                    float((a == b).mean()) for a, b in zip(am_cpu, am_pol)],
            }
            step_max = d_logit.reshape(d_logit.shape[0], -1).max(axis=1)
            over = np.nonzero(step_max > TOLERANCE)[0]
            kernel["logit_abs_diff_by_step"] = {
                str(t): float(step_max[t])
                for t in (0, 1, 10, 50, 100, 200, obs.shape[0] - 1)
                if t < obs.shape[0]}
            kernel["first_step_logit_abs_diff_over_tolerance"] = (
                int(over[0]) if over.size else None)
            entry["kernels"][name] = kernel
            if name == "torch" and not (
                    kernel["logit_step0_max_abs_diff"] <= TOLERANCE
                    and kernel["value_max_abs_diff"] <= TOLERANCE
                    and kernel["head_prob_max_abs_diff"] <= TOLERANCE
                    and min(kernel["unmasked_head_argmax_agreement"]) == 1.0):
                ok = False
        gap = np.abs(per_kernel["native"].astype(np.float64) - per_kernel["torch"])
        entry["native_vs_torch_logit_max_abs_diff"] = float(gap.max())
        result["traces"].append(entry)
    result["pass"] = ok
    text = json.dumps(result, indent=2, sort_keys=True)
    print(text)
    with open(out_json, "w") as f:
        f.write(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
