#!/usr/bin/env python3
"""Record chain traces from the native CUDA policy for torch-vs-native parity.

Rig side of the D399/D400 parity item. The recorder runs the live PufferLib
4.0 extension (`pufferlib._C`, built --float) exactly as the frozen exam does:
eval mode with evaluation-mode recurrent state (state persists across rollout
calls and is zeroed on terminal rows by reset_recurrent_state_on_terminal),
cudagraphs=10, the exam's 2048-agent / 2-buffer layout (so every policy forward
has the exam's batch of 1024 rows), selfplay and frozen banks off. Two changes:

  * train.horizon = 1, so each rollouts() call is one forward + exact joint
    sampling + one c_step, and qualification_snapshot() exposes the decoder
    output (the raw logits and value) of that forward;
  * env.scripted_opponent = 0: the policy drives BOTH seats, so both seats'
    forwards are recorded against on-policy observation streams.

Actions come from the native sampler itself (curand, exact-joint-v1). The
recorder does not choose actions; it records what the native side chose, and
the Mac comparator replays those observations and tuples into the harness.

For every recorded env the recorder steps a CPU bbplay shim (the same env TU)
in lockstep. Its observations must equal the native rows byte for byte, which
is also how the packed joint support is recorded: the vec's support buffer is
not exposed to Python, and the shim reproduces it once observations agree.

Backends:
  native   the live _C through tools/puffer_cuda_runtime.py (D225 init order)
  dry-run  CPU stand-in: bbplay engines as the env and seeded numpy logits
           sampled with the native algorithm; exercises lockstep and writer
           code with no CUDA import at all

Output (refuses to reuse a directory that holds RUN.json):
  <out>/RUN.json                          provenance and per-fixture summary
  <out>/<trace>-env<e>-row<r>/            bbplay-parity-fixture-v1 fixtures
  <out>/MISMATCH.json                     only when lockstep fails
"""
from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # never drop __pycache__ into the live checkout

import argparse  # noqa: E402
import hashlib  # noqa: E402
import importlib.util  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import platform  # noqa: E402
import socket  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from play_harness import engine as E  # noqa: E402
from play_harness import parity as P  # noqa: E402

CUDA_LIB_NAMES = ("libcudart.so", "libcublas.so", "libcublasLt.so", "libcurand.so",
                  "libnccl.so", "libcudnn.so", "libnvJitLink.so")
EPISODE_CANDIDATES = range(0, 8)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def log(msg):
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())} {msg}", flush=True)


class RecorderFailure(RuntimeError):
    def __init__(self, kind, detail):
        super().__init__(f"{kind}: {detail}")
        self.kind = kind
        self.detail = detail


def loaded_cuda_libraries():
    libs = set()
    try:
        with open("/proc/self/maps") as f:
            for line in f:
                parts = line.split()
                if parts and parts[-1].startswith("/") and \
                        any(os.path.basename(parts[-1]).startswith(n) for n in CUDA_LIB_NAMES):
                    libs.add(os.path.realpath(parts[-1]))
    except OSError:
        pass
    return sorted(libs)


# ------------------------------------------------------------------ backends
class NativeBackend:
    kind = "native-cuda-fp32"

    def __init__(self, a):
        self.total_agents = a.total_agents
        self.num_buffers = a.num_buffers
        live = os.path.realpath(a.live)
        spec = importlib.util.spec_from_file_location(
            "puffer_cuda_runtime", os.path.join(live, "tools", "puffer_cuda_runtime.py"))
        runtime_mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(runtime_mod)
        runtime, evidence = runtime_mod.begin_cuda_runtime_preflight()
        sys.path.insert(0, os.path.join(live, "vendor", "PufferLib"))
        from pufferlib import _C  # noqa: E402  (after the CUDART probe, D225)
        evidence = runtime_mod.finish_cuda_runtime_preflight(runtime, evidence)
        runtime_mod.validate_cuda_runtime_evidence(evidence)
        from pufferlib import pufferl as PL  # noqa: E402
        self._C = _C
        module_path = os.path.realpath(_C.__file__)
        self.provenance = {
            "cuda_runtime_evidence": evidence,
            "module_path": module_path,
            "module_sha256": sha256_file(module_path),
            "env_name": getattr(_C, "env_name", None),
            "gpu": bool(getattr(_C, "gpu", False)),
            "precision_bytes": int(getattr(_C, "precision_bytes", 0)),
            "pufferl_path": os.path.realpath(PL.__file__),
            "pufferl_sha256": sha256_file(os.path.realpath(PL.__file__)),
            "cuda_runtime_wrapper_sha256": sha256_file(
                os.path.join(live, "tools", "puffer_cuda_runtime.py")),
        }
        if (self.provenance["env_name"] != "bloodbowl" or not self.provenance["gpu"]
                or self.provenance["precision_bytes"] != 4):
            raise RecorderFailure("module", f"not the bloodbowl GPU fp32 build: {self.provenance}")
        nv = os.path.join(live, "vendor", "PufferLib", ".venv", "lib", "python3.11",
                          "site-packages", "nvidia") + os.sep
        overrides = [
            "--seed", str(a.seed), "--train.seed", str(a.seed), "--env.seed", str(a.seed),
            "--load-model-path", a.checkpoint, "--tag", "parity-native",
            "--selfplay.enabled", "0", "--vec.num-frozen-banks", "0",
            "--vec.frozen-bank-pct", "0",
            "--vec.total-agents", str(a.total_agents), "--vec.num-buffers", str(a.num_buffers),
            "--vec.num-threads", str(a.num_threads),
            "--train.horizon", "1", "--train.minibatch-size", str(a.total_agents),
            "--train.learning-rate", "0.000000000001",
            "--env.demo-reset-pct", "0", "--env.scripted-opponent", "0",
            "--env.max-decisions", str(a.max_decisions),
        ]
        saved_argv = sys.argv
        sys.argv = ["record_native"] + overrides
        try:
            args = PL.load_config("bloodbowl")
        finally:
            sys.argv = saved_argv
        args["nccl_id"] = b""
        args["world_size"] = 1
        args["rank"] = 0
        args["gpu_id"] = 0
        PL.require_training_state_reset(args)
        PL.guard_scripted_training(args)
        PL.validate_config(args)
        if PL._resolve_backend(args) is not _C:
            raise RecorderFailure("module", "pufferl resolved a non-native backend")
        want = {("cudagraphs",): 10, ("policy", "hidden_size"): 512,
                ("policy", "num_layers"): 3, ("train", "horizon"): 1,
                ("vec", "num_frozen_banks"): 0, ("selfplay", "enabled"): 0,
                ("env", "scripted_opponent"): 0, ("env", "demo_reset_pct"): 0}
        for path, value in want.items():
            got = args
            for k in path:
                got = got[k]
            if got != value:
                raise RecorderFailure("config", f"{'.'.join(path)}={got!r}, expected {value!r}")
        self.provenance["overrides"] = overrides
        self.provenance["effective"] = {
            "base": {k: args[k] for k in ("seed", "cudagraphs", "reset_state", "profile")},
            "vec": dict(args["vec"]), "train": dict(args["train"]), "env": dict(args["env"]),
            "policy": dict(args["policy"]), "selfplay": dict(args["selfplay"]),
        }
        t0 = time.time()
        self.pufferl = _C.create_pufferl(args)
        _C.load_weights(self.pufferl, a.checkpoint)
        _C.set_evaluation_mode(self.pufferl, True)
        self.provenance["create_seconds"] = time.time() - t0
        libs = loaded_cuda_libraries()
        self.provenance["loaded_cuda_libraries"] = libs
        outside = [p for p in libs if not p.startswith(os.path.realpath(nv) + os.sep)]
        if outside:
            raise RecorderFailure("cuda-libraries", f"loaded outside {nv}: {outside}")

    def _tensor(self, snap, name, cols):
        t = snap["tensors"][name]
        if not t["present"] or t["dtype"] != "f32":
            raise RecorderFailure("snapshot", f"{name}: present={t['present']} dtype={t['dtype']}")
        arr = np.frombuffer(t["data"], dtype="<f4")
        if arr.size != self.total_agents * cols:
            raise RecorderFailure("snapshot", f"{name}: shape {t['shape']} is not horizon-1 x "
                                              f"{self.total_agents} x {cols}")
        return arr.reshape(self.total_agents, cols)

    def step(self, envs):
        _C = self._C
        _C.rollouts(self.pufferl)
        snap = _C.qualification_snapshot(self.pufferl)
        obs = self._tensor(snap, "observations", E.OBS_SIZE)
        actions = self._tensor(snap, "actions", 3)
        values = self._tensor(snap, "values", 1)[:, 0]
        logprobs = self._tensor(snap, "logprobs", 1)[:, 0]
        terminals = self._tensor(snap, "terminals", 1)[:, 0]
        masks = self._tensor(snap, "action_mask", E.MASK_SIZE)
        per_buffer = self.total_agents // self.num_buffers
        decoder = np.empty((self.total_agents, E.MASK_SIZE + 1), dtype=np.float32)
        seen = set()
        for entry in snap["decoder_outputs"]:
            if entry["bank"] != 0:
                continue
            b = entry["buffer"]
            t = entry["tensor"]
            arr = np.frombuffer(t["data"], dtype="<f4")
            if entry["active_rows"] != per_buffer or arr.size != per_buffer * (E.MASK_SIZE + 1):
                raise RecorderFailure("snapshot", f"decoder output buffer {b}: {t['shape']}")
            decoder[b * per_buffer:(b + 1) * per_buffer] = arr.reshape(per_buffer, -1)
            seen.add(b)
        if seen != set(range(self.num_buffers)):
            raise RecorderFailure("snapshot", f"decoder outputs for buffers {sorted(seen)}")
        out = {}
        for e in envs:
            rows = [2 * e, 2 * e + 1]
            o = obs[rows]
            if not np.all((o >= 0) & (o <= 255) & (o == np.round(o))):
                raise RecorderFailure("snapshot", f"env {e}: observations are not bytes")
            if not np.array_equal(values[rows], decoder[rows, E.MASK_SIZE]):
                raise RecorderFailure("snapshot", f"env {e}: rollout values differ from decoder")
            out[e] = {"obs": o.astype(np.uint8), "terminal": terminals[rows].copy(),
                      "actions": actions[rows].copy(), "logprob": logprobs[rows].copy(),
                      "value": values[rows].copy(), "masks": masks[rows].copy(),
                      "logits": decoder[rows, :E.MASK_SIZE].copy()}
        return out


class DryRunBackend:
    """CPU stand-in with the native sampler's algorithm (float32 inverse CDF over
    the exact support conditioned on earlier heads). No CUDA, no pufferlib."""
    kind = "dry-run-numpy"

    def __init__(self, a):
        self.a = a
        self.engines, self.episodes, self.pending = {}, {}, {}
        self.rng = np.random.default_rng(a.seed)
        self.t = 0
        self.provenance = {"module_sha256": None, "precision_bytes": 4,
                           "note": "dry run: numpy logits, bbplay engines as the env"}

    def _engine(self, e):
        return E.Engine(self.a.seed + e, episode=self.episodes[e],
                        max_decisions=self.a.max_decisions)

    @staticmethod
    def _sample(logits, support, u):
        values = P.unpack_support(support)
        prefix = np.ones(values[0].shape[0], dtype=bool)
        masks, tup, total = [], [], np.float32(0.0)
        for h, (lo, hi) in enumerate(P.HEAD_BOUNDS):
            m = np.zeros(hi - lo, dtype=bool)
            m[values[h][prefix]] = True
            x = logits[lo:hi].astype(np.float32)
            mx = x[m].max()
            lse = mx + np.log(np.exp(x[m] - mx).sum(dtype=np.float32))
            probs = np.where(m, np.exp(x - lse), 0.0).astype(np.float32)
            cum = np.cumsum(probs, dtype=np.float32)
            idx = np.nonzero(m & (u[h] < cum))[0]
            a = int(idx[0]) if idx.size else int(np.nonzero(m)[0][-1])
            total += x[a] - lse
            tup.append(a)
            masks.append(m)
            prefix &= values[h] == a
        return tuple(tup), float(total), np.concatenate(masks).astype(np.float32)

    def step(self, envs):
        if self.a.fail_at_step is not None and self.t == self.a.fail_at_step:
            raise RecorderFailure("dry-run", f"injected failure at step {self.t}")
        if self.a.dry_step_sleep:
            time.sleep(self.a.dry_step_sleep)
        out = {}
        for e in envs:
            if e not in self.engines:
                self.episodes[e] = 1
                self.engines[e] = self._engine(e)
                self.pending[e] = 0.0
            eng = self.engines[e]
            decider = eng.decision_team
            rec = {k: [] for k in ("obs", "actions", "logprob", "value", "masks", "logits")}
            for r in (0, 1):
                logits = (self.rng.normal(size=E.MASK_SIZE) * 3).astype(np.float32)
                sup = eng.joint_support(r)
                tup, lp, masks = self._sample(logits, sup, self.rng.random(3))
                rec["obs"].append(eng.obs(r))
                rec["actions"].append(np.array(tup, dtype=np.float32))
                rec["logprob"].append(lp)
                rec["value"].append(np.float32(self.rng.normal()))
                rec["masks"].append(masks)
                rec["logits"].append(logits)
            out[e] = {k: np.stack(v) if k != "logprob" else np.array(v, dtype=np.float32)
                      for k, v in rec.items()}
            out[e]["value"] = out[e]["value"].astype(np.float32)
            out[e]["terminal"] = np.array([self.pending[e]] * 2, dtype=np.float32)
            rc = eng.step(*[int(v) for v in out[e]["actions"][decider]])
            if rc < 0:
                raise RecorderFailure("dry-run", f"env {e} step refused rc={rc}")
            self.pending[e] = 1.0 if rc == E.STEP_TERMINAL else 0.0
            if rc == E.STEP_TERMINAL:
                eng.close()
                self.episodes[e] += 1
                self.engines[e] = self._engine(e)
        self.t += 1
        return out


# ------------------------------------------------------------------ lockstep
def record(a, backend):
    envs = [int(v) for v in a.envs.split(",")]
    base_env = {"home_team": -1, "away_team": -1, "skillup_max_players": 4,
                "skillup_max_each": 2, "skillup_secondary_pct": 0.0,
                "max_decisions": int(a.max_decisions)}
    shims, episodes, first_episode, expect_terminal = {}, {}, {}, {}
    matches = {e: 1 for e in envs}
    rows = {(e, r): {k: [] for k in ("obs", "reset", "terminal", "deciding", "masks", "actions",
                                     "logprob", "value", "env_tuple", "logits", "support")}
            for e in envs for r in (0, 1)}
    t_start = time.time()
    for t in range(a.steps):
        data = backend.step(envs)
        for e in envs:
            d = data[e]
            if t == 0:
                for ep in EPISODE_CANDIDATES:
                    cand = E.Engine(a.seed + e, episode=ep, max_decisions=a.max_decisions)
                    if np.array_equal(cand.obs(0), d["obs"][0]) and \
                            np.array_equal(cand.obs(1), d["obs"][1]):
                        shims[e], episodes[e], first_episode[e] = cand, ep, ep
                        break
                    cand.close()
                else:
                    raise RecorderFailure("episode-search",
                                          f"env {e}: no bbplay episode in "
                                          f"{list(EPISODE_CANDIDATES)} matches step 0")
                expect_terminal[e] = None
            eng = shims[e]
            for r in (0, 1):
                if not np.array_equal(eng.obs(r), d["obs"][r]):
                    diff = np.nonzero(eng.obs(r) != d["obs"][r])[0]
                    raise RecorderFailure("obs-mismatch", f"env {e} row {r} step {t}: "
                                                          f"{diff.size} bytes differ, first {diff[:8].tolist()}")
            flags = d["terminal"].astype(bool)
            if flags[0] != flags[1]:
                raise RecorderFailure("terminal", f"env {e} step {t}: rows disagree {flags}")
            if expect_terminal[e] is not None and bool(flags[0]) != expect_terminal[e]:
                raise RecorderFailure("terminal", f"env {e} step {t}: native terminal={flags[0]}, "
                                                  f"shim expected {expect_terminal[e]}")
            acts = d["actions"]
            if not np.array_equal(acts, np.round(acts)):
                raise RecorderFailure("actions", f"env {e} step {t}: non-integral actions")
            decider = eng.decision_team
            env_tuple = tuple(int(v) for v in acts[decider])
            for r in (0, 1):
                rec = rows[(e, r)]
                rec["obs"].append(d["obs"][r])
                rec["terminal"].append(1 if flags[r] else 0)
                rec["reset"].append(1 if (t == 0 or flags[r]) else 0)
                rec["deciding"].append(1 if decider == r else 0)
                m = d["masks"][r]
                if not np.all((m == 0) | (m == 1)):
                    raise RecorderFailure("masks", f"env {e} row {r} step {t}: non-binary mask")
                rec["masks"].append(m.astype(np.uint8))
                rec["actions"].append(acts[r].astype(np.int32))
                rec["logprob"].append(np.float32(d["logprob"][r]))
                rec["value"].append(np.float32(d["value"][r]))
                rec["env_tuple"].append(np.array(env_tuple, dtype=np.int32))
                rec["logits"].append(d["logits"][r].astype(np.float32))
                rec["support"].append(eng.joint_support(r).astype(np.uint32))
            rc = eng.step(*env_tuple)
            if rc < 0:
                raise RecorderFailure("shim-step", f"env {e} step {t}: tuple {env_tuple} rc={rc}")
            expect_terminal[e] = rc == E.STEP_TERMINAL
            if rc == E.STEP_TERMINAL:
                eng.close()
                episodes[e] += 1
                matches[e] += 1
                shims[e] = E.Engine(a.seed + e, episode=episodes[e], max_decisions=a.max_decisions)
        if (t + 1) % 100 == 0 or t + 1 == a.steps:
            log(f"step {t + 1}/{a.steps} ({(time.time() - t_start) / (t + 1) * 1e3:.1f} ms/step) "
                f"matches={[matches[e] for e in envs]}")
    elapsed = time.time() - t_start
    fixtures = []
    violations = 0
    for (e, r), rec in rows.items():
        arrays = {k: np.stack(v) for k, v in rec.items() if k != "support"}
        arrays["support"], arrays["support_offsets"] = P.pack_support(rec["support"])
        arrays["masked_logits"] = np.where(arrays["masks"].astype(bool), arrays["logits"],
                                           -np.inf).astype(np.float32)
        arrays["probs"] = P.head_probs(arrays["logits"], arrays["masks"]).astype(np.float32)
        cons = P.fixture_consistency(arrays)
        violations += cons["violations"]
        manifest = {
            "schema": P.SCHEMA, "backend": backend.kind,
            "checkpoint_sha256": a.checkpoint_sha256,
            "module_sha256": backend.provenance.get("module_sha256"),
            "precision_bytes": 4, "kernel": "native-cuda" if backend.kind.startswith("native")
            else "dry-run", "policy_row": r,
            "env": {"seed": a.seed + e, "episode": first_episode[e], **base_env},
            "opponent": "self (the same policy drives both seats)",
            "tolerance": {"logprob": P.ACCEPTANCE["logprob_max_abs_diff"],
                          "value": P.ACCEPTANCE["value_max_abs_diff"],
                          "logits": P.ACCEPTANCE["logit_step0_max_abs_diff"]},
            "trace": {"name": a.trace, "env_index": e, "base_seed": a.seed,
                      "steps": a.steps, "matches": matches[e],
                      "total_agents": a.total_agents, "num_buffers": a.num_buffers,
                      "rows": [2 * e, 2 * e + 1]},
            "consistency": cons,
        }
        out_dir = os.path.join(a.out, f"{a.trace}-env{e}-row{r}")
        P.save_fixture(out_dir, manifest, arrays)
        fixtures.append({"path": os.path.basename(out_dir), "env_index": e, "policy_row": r,
                         "matches": matches[e],
                         "terminal_steps": int(arrays["terminal"][1:].sum()),
                         "deciding_steps": int(arrays["deciding"].sum()),
                         "consistency_violations": cons["violations"],
                         "recorded_logprob_vs_recorded_logits_max_abs":
                             cons.get("recorded_logprob_vs_recorded_logits_max_abs")})
    return {"fixtures": fixtures, "consistency_violations": violations,
            "record_seconds": elapsed, "ms_per_step": elapsed / max(1, a.steps) * 1e3,
            "episodes_first": {str(e): first_episode[e] for e in envs}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--backend", choices=["native", "dry-run"], required=True)
    ap.add_argument("--live", default="/home/rache/bloodbowl-rl-qualification-candidate-10619e2")
    ap.add_argument("--checkpoint", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--steps", type=int, default=400)
    ap.add_argument("--envs", default="0,1,2,3")
    ap.add_argument("--max-decisions", type=int, default=4096)
    ap.add_argument("--total-agents", type=int, default=2048)
    ap.add_argument("--num-buffers", type=int, default=2)
    ap.add_argument("--num-threads", type=int, default=4)
    ap.add_argument("--fail-at-step", type=int, default=None, help="dry-run only")
    ap.add_argument("--dry-step-sleep", type=float, default=0.0, help="dry-run only")
    a = ap.parse_args(argv)

    live_real = os.path.realpath(a.live) + os.sep
    out_real = os.path.realpath(a.out) + os.sep
    if out_real.startswith(live_real):
        print(f"refusing to write inside the live checkout: {a.out}", file=sys.stderr)
        return 6
    if os.path.exists(os.path.join(a.out, "RUN.json")):
        print(f"refusing to overwrite a finished recording: {a.out}/RUN.json", file=sys.stderr)
        return 2
    if os.path.isdir(a.out) and os.listdir(a.out):
        print(f"refusing to write into a non-empty directory: {a.out}", file=sys.stderr)
        return 2
    if a.backend == "native" and (a.fail_at_step is not None or a.dry_step_sleep):
        print("--fail-at-step and --dry-step-sleep are dry-run only", file=sys.stderr)
        return 2
    if any(2 * int(e) + 1 >= a.total_agents // a.num_buffers for e in a.envs.split(",")):
        print("recorded envs must lie in the first buffer", file=sys.stderr)
        return 2
    digest = sha256_file(a.checkpoint)
    if digest != a.expect_sha256:
        print(f"checkpoint sha256 {digest} != expected {a.expect_sha256}", file=sys.stderr)
        return 2
    a.checkpoint_sha256 = digest
    os.makedirs(a.out, exist_ok=True)
    run = {
        "schema": "bbplay-native-parity-run-v1",
        "argv": sys.argv if argv is None else ["record_native.py"] + list(argv),
        "backend": a.backend, "host": socket.gethostname(), "platform": platform.platform(),
        "python": sys.version, "numpy": np.__version__,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "checkpoint": {"path": os.path.realpath(a.checkpoint), "sha256": digest},
        "recorder_sha256": sha256_file(os.path.abspath(__file__)),
        "parity_py_sha256": sha256_file(P.__file__),
        "engine_py_sha256": sha256_file(E.__file__),
        "bbplay_lib": os.environ.get("BBPLAY_LIB"),
        "bbplay_lib_sha256": sha256_file(os.environ["BBPLAY_LIB"])
        if os.environ.get("BBPLAY_LIB") else None,
        "env": {k: os.environ.get(k) for k in ("CUDA_VISIBLE_DEVICES", "LD_LIBRARY_PATH",
                                                "OMP_NUM_THREADS", "PYTHONDONTWRITEBYTECODE")},
        "config": {"seed": a.seed, "steps": a.steps, "envs": a.envs,
                   "max_decisions": a.max_decisions, "total_agents": a.total_agents,
                   "num_buffers": a.num_buffers, "num_threads": a.num_threads, "trace": a.trace},
    }
    if a.backend == "native":
        try:
            run["live_git_head"] = subprocess.run(
                ["git", "-C", a.live, "rev-parse", "HEAD"], capture_output=True, text=True,
                timeout=30).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            run["live_git_head"] = None
    try:
        E.load_library(build_if_missing=False)
        backend = NativeBackend(a) if a.backend == "native" else DryRunBackend(a)
        run["provenance"] = backend.provenance
        log(f"backend {backend.kind} ready; recording {a.steps} steps of envs {a.envs}")
        run.update(record(a, backend))
    except RecorderFailure as exc:
        run["failure"] = {"kind": exc.kind, "detail": exc.detail}
        with open(os.path.join(a.out, "MISMATCH.json"), "w") as f:
            json.dump(run, f, indent=1, sort_keys=True, default=str)
        log(f"RECORDER-FAIL {exc}")
        return 3
    run["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with open(os.path.join(a.out, "RUN.json"), "w") as f:
        json.dump(run, f, indent=1, sort_keys=True, default=str)
    log(f"RECORDER-DONE fixtures={len(run['fixtures'])} "
        f"consistency_violations={run['consistency_violations']} out={a.out}")
    return 4 if run["consistency_violations"] else 0


if __name__ == "__main__":
    sys.exit(main())
