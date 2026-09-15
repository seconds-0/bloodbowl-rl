#!/usr/bin/env python3
"""Timed throughput probe runner for the PufferLib 4.0 vs 5.0 benchmark queue.

Stdlib only (runs under the rig's system python3). Subcommands:

  run          launch one trainer command in its own session, wait for warmup,
               measure a fixed window, sample nvidia-smi, kill at a hard
               temperature, clean up the process group, write one JSON result.
  wait-cool    poll nvidia-smi until the GPU is below a temperature (bounded).
  skip         write a result JSON for a probe that was not run.
  preflight    record host/toolchain/file identity as JSON.
  summarize    combine probe results into SUMMARY.json with ratios to a baseline.
  fake-trainer CPU-only emitter used by tests and the queue's DRY_RUN mode.

Metric sources:
  kind=ref40  trainer stdout lines "BENCH40_JSON {...}" written by
              tools/puffer5/ref40_launch.py (all non-env flat log keys: SPS,
              agent_steps, epoch, uptime, perf/*, util/*). Fallback: the 4.0
              "PUFFER_ENV_JSON {...}" panels (_puffer_agent_steps/_puffer_epoch,
              arrival time as the clock; no perf timings).
  kind=p5     one JSON object per line appended by the 5.0 port trainer to
              $PUFFER5_METRICS_JSONL.

Normalisation: both trainers report perf/* as seconds accumulated since the
previous log line. Per-epoch ms = 1000 * sum(perf/<key> over window samples
after the first) / (epoch_last - epoch_first). The window SPS is
(agent_steps_last - agent_steps_first) / (clock_last - clock_first), where the
clock is the trainer's uptime when every sample carries it, else arrival time.
"""
import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time

REF40_PREFIX = "BENCH40_JSON "
ENV_PANEL_PREFIX = "PUFFER_ENV_JSON "
SMI_QUERY = "temperature.gpu,memory.used,utilization.gpu"

# Common names for per-epoch timings, per trainer kind.
PERF_MAP = {
    "ref40": {
        "gpu_forward_ms": "perf/eval_gpu",
        "env_ms": "perf/eval_env",
        "copy_ms": "perf/eval_copy",
        "rollout_ms": "perf/rollout",
        "train_ms": "perf/train",
        "train_model_ms": "perf/train_forward",
        "train_misc_ms": "perf/train_misc",
    },
    "p5": {
        "gpu_forward_ms": "perf/eval_model",
        "env_ms": "perf/eval_env",
        "copy_ms": "perf/eval_copy",
        "rollout_ms": "perf/rollout",
        "train_ms": "perf/train",
        "train_model_ms": "perf/train_model",
        "train_misc_ms": "perf/train_misc",
    },
}


def _num(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if out == out else None  # drop NaN


def parse_ref40_line(line, arrival):
    """One stdout line of the 4.0 probe -> sample dict or None."""
    line = line.strip()
    if line.startswith(REF40_PREFIX):
        try:
            payload = json.loads(line[len(REF40_PREFIX):])
        except ValueError:
            return None
        sample = {k: v for k, v in payload.items() if _num(v) is not None}
        sample = {k: float(v) for k, v in sample.items()}
        sample["t_arrival"] = arrival
        sample["source"] = "bench40"
        if "agent_steps" not in sample:
            return None
        return sample
    if line.startswith(ENV_PANEL_PREFIX):
        try:
            payload = json.loads(line[len(ENV_PANEL_PREFIX):])
        except ValueError:
            return None
        steps = _num(payload.get("_puffer_agent_steps"))
        if steps is None or payload.get("_puffer_phase_eval"):
            return None
        sample = {"agent_steps": steps, "t_arrival": arrival, "source": "env_panel"}
        epoch = _num(payload.get("_puffer_epoch"))
        if epoch is not None:
            sample["epoch"] = epoch
        return sample
    return None


def parse_p5_line(line, arrival):
    """One JSONL line of the 5.0 metrics file -> sample dict or None."""
    line = line.strip()
    if not line:
        return None
    try:
        payload = json.loads(line)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    sample = {}
    for key, value in payload.items():
        if key.startswith("env/"):
            continue
        num = _num(value)
        if num is not None:
            sample[key] = num
    if "agent_steps" not in sample:
        return None
    sample["t_arrival"] = arrival
    sample["source"] = "p5_jsonl"
    return sample


def parse_smi(text):
    """nvidia-smi csv,noheader,nounits for SMI_QUERY -> (temp, mem_mib, util)."""
    for raw in text.splitlines():
        parts = [p.strip() for p in raw.split(",")]
        if len(parts) >= 3:
            vals = [_num(p) for p in parts[:3]]
            if all(v is not None for v in vals):
                return vals[0], vals[1], vals[2]
    return None


def query_smi(nvidia_smi, timeout=15):
    try:
        out = subprocess.run(
            [nvidia_smi, f"--query-gpu={SMI_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    return parse_smi(out.stdout)


def thermal_action(temp, kill_temp):
    return "kill" if temp is not None and temp >= kill_temp else "ok"


def warmup_end(start, warmup, samples):
    """Warmup ends at start+warmup or at the first positive-step sample, whichever
    is later. None until a positive-step sample exists."""
    first = next((s["t_arrival"] for s in samples if s.get("agent_steps", 0) > 0), None)
    if first is None:
        return None
    return max(start + warmup, first)


def window_stats(samples, w0, w1, kind):
    """Throughput and timing statistics over samples that arrived in [w0, w1]."""
    win = [s for s in samples if w0 <= s["t_arrival"] <= w1]
    out = {"samples_in_window": len(win)}
    if len(win) < 2:
        out["error"] = "fewer than 2 metric samples in the measurement window"
        return out
    first, last = win[0], win[-1]
    use_uptime = all("uptime" in s for s in win)
    clock = "uptime" if use_uptime else "t_arrival"
    dt = last[clock] - first[clock]
    dsteps = last["agent_steps"] - first["agent_steps"]
    out["clock"] = clock
    out["window_clock_seconds"] = dt
    out["window_agent_steps"] = dsteps
    out["sps_window"] = dsteps / dt if dt > 0 else None
    sps_vals = [s["SPS"] for s in win if "SPS" in s]
    out["sps_trainer_mean"] = sum(sps_vals) / len(sps_vals) if sps_vals else None
    if "epoch" in first and "epoch" in last:
        epochs = last["epoch"] - first["epoch"]
        out["epochs_in_window"] = epochs
        if epochs > 0:
            perf = {}
            keys = sorted({k for s in win[1:] for k in s if k.startswith("perf/")})
            for key in keys:
                total = sum(s.get(key, 0.0) for s in win[1:])
                perf[key] = 1000.0 * total / epochs
            out["perf_ms_per_epoch_raw"] = perf
            out["perf_ms_per_epoch"] = {
                name: perf.get(src) for name, src in PERF_MAP[kind].items()}
            out["steps_per_epoch"] = dsteps / epochs
    vram = [s["util/vram_used_gb"] for s in win if "util/vram_used_gb" in s]
    out["trainer_vram_used_gb_max"] = max(vram) if vram else None
    util = [s["util/gpu_percent"] for s in win if "util/gpu_percent" in s]
    out["trainer_gpu_percent_mean"] = sum(util) / len(util) if util else None
    return out


def _tail(path, lines=80):
    try:
        with open(path, "rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - 64000))
            data = handle.read().decode("utf-8", "replace")
    except OSError:
        return ""
    return "\n".join(data.splitlines()[-lines:])


def _resolve_binary(cmd0, cwd):
    if os.sep in cmd0:
        path = cmd0 if os.path.isabs(cmd0) else os.path.join(cwd or os.getcwd(), cmd0)
        return path if os.path.isfile(path) and os.access(path, os.X_OK) else None
    return shutil.which(cmd0)


class Tailer:
    def __init__(self, path):
        self.path = path
        self.offset = 0
        self.partial = ""

    def lines(self):
        try:
            with open(self.path, "rb") as handle:
                handle.seek(self.offset)
                data = handle.read()
                self.offset = handle.tell()
        except OSError:
            return []
        text = self.partial + data.decode("utf-8", "replace")
        parts = text.split("\n")
        self.partial = parts.pop()
        return parts


def _kill_group(proc, grace):
    reason = None
    if proc.poll() is None:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            proc.wait(timeout=grace)
            reason = "sigterm"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            proc.wait()
            reason = "sigkill"
    else:
        # Leader exited; still sweep any descendants left in the group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return reason


def run_probe(opts):
    start_wall = time.time()
    result = {
        "name": opts.name,
        "kind": opts.kind,
        "command": opts.cmd,
        "cwd": opts.cwd,
        "env_overrides": dict(e.split("=", 1) for e in opts.env),
        "warmup_seconds": opts.warmup,
        "window_seconds": opts.window,
        "kill_temp_c": opts.kill_temp,
        "log": opts.log,
        "metrics_jsonl": opts.metrics_jsonl if opts.kind == "p5" else None,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start_wall)),
    }
    if not opts.cmd:
        result.update(status="failed", reason="empty command")
        return result
    if _resolve_binary(opts.cmd[0], opts.cwd) is None:
        result.update(status="missing_binary",
                      reason=f"executable not found: {opts.cmd[0]} (cwd={opts.cwd})")
        return result
    env = dict(os.environ)
    env.update(result["env_overrides"])
    if opts.kind == "p5" and opts.metrics_jsonl:
        env["PUFFER5_METRICS_JSONL"] = opts.metrics_jsonl
        if os.path.exists(opts.metrics_jsonl):
            os.rename(opts.metrics_jsonl, opts.metrics_jsonl + f".stale.{int(start_wall)}")
    os.makedirs(os.path.dirname(os.path.abspath(opts.log)), exist_ok=True)
    log_handle = open(opts.log, "wb")
    try:
        proc = subprocess.Popen(opts.cmd, cwd=opts.cwd or None, env=env,
                                stdout=log_handle, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, start_new_session=True)
    except OSError as exc:
        log_handle.close()
        result.update(status="failed", reason=f"launch failed: {exc}")
        return result

    stop = {"signal": None}

    def _on_signal(signum, _frame):
        stop["signal"] = signum

    old_term = signal.signal(signal.SIGTERM, _on_signal)
    old_int = signal.signal(signal.SIGINT, _on_signal)

    start = time.time()
    source = opts.metrics_jsonl if opts.kind == "p5" else opts.log
    tailer = Tailer(source)
    parse = parse_p5_line if opts.kind == "p5" else parse_ref40_line
    samples, gpu = [], []
    status, reason = None, None
    w0 = w1 = None
    next_smi = start
    temp_max = None
    try:
        while True:
            now = time.time()
            for line in tailer.lines():
                sample = parse(line, now)
                if sample is not None:
                    samples.append(sample)
            if w0 is None:
                w0 = warmup_end(start, opts.warmup, samples)
                if w0 is not None:
                    w1 = w0 + opts.window
            if now >= next_smi:
                reading = query_smi(opts.nvidia_smi)
                next_smi = now + opts.sample_interval
                if reading is not None:
                    temp, mem, util = reading
                    phase = "window" if (w0 is not None and w0 <= now <= w1) else (
                        "warmup" if w0 is None or now < w0 else "post")
                    gpu.append({"t": now, "temp_c": temp, "mem_mib": mem,
                                "util_pct": util, "phase": phase})
                    temp_max = temp if temp_max is None else max(temp_max, temp)
                    if thermal_action(temp, opts.kill_temp) == "kill":
                        status = "killed_thermal"
                        reason = f"GPU temperature {temp:.0f} C >= {opts.kill_temp} C"
                        break
            if stop["signal"] is not None:
                status, reason = "interrupted", f"probe runner got signal {stop['signal']}"
                break
            rc = proc.poll()
            if rc is not None:
                status, reason = "exited_early", f"trainer exited with code {rc}"
                break
            if w0 is None and now - start > opts.startup_timeout:
                status = "startup_timeout"
                reason = f"no positive-step metric sample within {opts.startup_timeout}s"
                break
            if w1 is not None and now >= w1 + opts.grace:
                status = "ok"
                break
            time.sleep(opts.poll)
        # Drain anything that arrived just before the stop.
        now = time.time()
        for line in tailer.lines():
            sample = parse(line, now)
            if sample is not None:
                samples.append(sample)
    finally:
        kill_reason = _kill_group(proc, opts.kill_grace)
        log_handle.close()
        signal.signal(signal.SIGTERM, old_term)
        signal.signal(signal.SIGINT, old_int)

    result["status"] = status
    result["reason"] = reason
    result["kill_reason"] = kill_reason
    result["exit_code"] = proc.returncode
    result["elapsed_seconds"] = time.time() - start
    result["metric_samples_total"] = len(samples)
    result["window_start_offset_s"] = (w0 - start) if w0 is not None else None
    if w0 is not None:
        stats = window_stats(samples, w0, w1, opts.kind)
        result.update(stats)
        if status == "ok" and stats.get("error"):
            result["status"] = "insufficient_samples"
            result["reason"] = stats["error"]
    win_gpu = [g for g in gpu if g["phase"] == "window"]
    result["gpu_temp_max_c"] = temp_max
    result["gpu_temp_max_window_c"] = max((g["temp_c"] for g in win_gpu), default=None)
    result["gpu_mem_used_mib_max"] = max((g["mem_mib"] for g in gpu), default=None)
    result["gpu_util_mean_window_pct"] = (
        sum(g["util_pct"] for g in win_gpu) / len(win_gpu) if win_gpu else None)
    result["gpu_samples"] = gpu
    if result["status"] != "ok":
        result["log_tail"] = _tail(opts.log)
    return result


def cmd_run(opts):
    result = run_probe(opts)
    with open(opts.out, "w") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
    brief = {k: result.get(k) for k in (
        "name", "status", "reason", "sps_window", "sps_trainer_mean",
        "gpu_temp_max_c", "gpu_mem_used_mib_max")}
    print("PROBE_RESULT " + json.dumps(brief, sort_keys=True), flush=True)
    return 0 if result["status"] == "ok" else 1


def cmd_wait_cool(opts):
    deadline = time.time() + opts.timeout
    last = None
    while True:
        reading = query_smi(opts.nvidia_smi)
        if reading is not None:
            last = reading[0]
            if last < opts.below:
                print(json.dumps({"cool": True, "temp_c": last,
                                  "utc": time.strftime("%FT%TZ", time.gmtime())}), flush=True)
                return 0
        if time.time() >= deadline:
            print(json.dumps({"cool": False, "temp_c": last,
                              "utc": time.strftime("%FT%TZ", time.gmtime())}), flush=True)
            return 3
        time.sleep(opts.poll)


def cmd_skip(opts):
    result = {"name": opts.name, "kind": opts.kind, "status": "skipped",
              "reason": opts.reason,
              "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    with open(opts.out, "w") as handle:
        json.dump(result, handle, indent=1, sort_keys=True)
    print("PROBE_RESULT " + json.dumps(result, sort_keys=True), flush=True)
    return 0


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_text(cmd, timeout=30):
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {"returncode": out.returncode, "stdout": out.stdout.strip()[-4000:],
                "stderr": out.stderr.strip()[-2000:]}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": str(exc)}


def cmd_preflight(opts):
    record = {"utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
              "uname": os.uname()._asdict() if hasattr(os.uname(), "_asdict") else
              list(os.uname()), "files": {}, "git": {}}
    record["nvidia_smi"] = _run_text([opts.nvidia_smi,
        "--query-gpu=name,driver_version,temperature.gpu,memory.used,memory.total",
        "--format=csv,noheader"])
    record["nvcc"] = _run_text(["nvcc", "--version"])
    for item in opts.file:
        label, path = item.split("=", 1)
        entry = {"path": path, "exists": os.path.isfile(path)}
        if entry["exists"]:
            entry["sha256"] = _sha256(path)
            entry["bytes"] = os.path.getsize(path)
        record["files"][label] = entry
    for item in opts.git:
        label, path = item.split("=", 1)
        record["git"][label] = {
            "path": path,
            "head": _run_text(["git", "-C", path, "rev-parse", "HEAD"]).get("stdout"),
            "status_short": _run_text(["git", "-C", path, "status", "--short"]).get("stdout"),
        }
    if opts.df:
        usage = shutil.disk_usage(opts.df)
        record["disk"] = {"path": opts.df, "free_gb": usage.free / 1e9,
                          "total_gb": usage.total / 1e9}
    record["meminfo"] = _run_text(["free", "-m"])
    record["extra"] = dict(e.split("=", 1) for e in opts.extra)
    with open(opts.out, "w") as handle:
        json.dump(record, handle, indent=1, sort_keys=True)
    print("PREFLIGHT " + opts.out, flush=True)
    return 0


def summarize(probes, preflight, baseline):
    by_name = {p.get("name"): p for p in probes}
    base = by_name.get(baseline, {})
    base_sps = base.get("sps_window") if base.get("status") == "ok" else None
    table = []
    for p in probes:
        row = {k: p.get(k) for k in (
            "name", "kind", "status", "reason", "sps_window", "sps_trainer_mean",
            "epochs_in_window", "steps_per_epoch", "perf_ms_per_epoch",
            "trainer_vram_used_gb_max", "gpu_mem_used_mib_max",
            "gpu_util_mean_window_pct", "gpu_temp_max_c", "kill_reason", "exit_code")}
        sps = p.get("sps_window") if p.get("status") == "ok" else None
        row["sps_ratio_vs_baseline"] = (sps / base_sps) if (sps and base_sps) else None
        table.append(row)
    return {
        "schema": "bloodbowl-rl/puffer5-bench/v1",
        "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline": baseline,
        "baseline_sps_window": base_sps,
        "normalisation": (
            "sps_window = agent_steps delta / trainer uptime delta over the samples "
            "that arrived inside the measurement window; perf_ms_per_epoch = 1000 * "
            "sum of per-log-interval perf seconds after the first window sample / "
            "epoch delta"),
        "probes": table,
        "preflight": preflight,
        "probe_results": probes,
    }


def cmd_summarize(opts):
    probes = []
    for path in opts.probe:
        try:
            with open(path) as handle:
                probes.append(json.load(handle))
        except (OSError, ValueError) as exc:
            probes.append({"name": os.path.basename(path), "status": "missing_result",
                           "reason": str(exc)})
    preflight = None
    if opts.preflight:
        try:
            with open(opts.preflight) as handle:
                preflight = json.load(handle)
        except (OSError, ValueError) as exc:
            preflight = {"error": str(exc)}
    summary = summarize(probes, preflight, opts.baseline)
    with open(opts.out, "w") as handle:
        json.dump(summary, handle, indent=1, sort_keys=True)
    print("SUMMARY " + json.dumps(
        [{k: r[k] for k in ("name", "status", "sps_window", "sps_ratio_vs_baseline")}
         for r in summary["probes"]]), flush=True)
    return 0


def cmd_fake_trainer(opts):
    start = time.time()
    steps = 0.0
    epoch = 0
    last = start
    metrics = opts.metrics or os.environ.get("PUFFER5_METRICS_JSONL")
    while True:
        time.sleep(opts.interval)
        now = time.time()
        dt = now - last
        last = now
        epoch += 1
        steps += opts.sps * dt
        payload = {"SPS": opts.sps, "agent_steps": steps, "epoch": epoch,
                   "uptime": now - start, "perf/rollout": 0.6 * dt,
                   "perf/eval_env": 0.4 * dt, "perf/train": 0.4 * dt,
                   "util/vram_used_gb": 6.4, "util/gpu_percent": 95.0,
                   "env/tds": 1.5}
        if opts.kind == "ref40":
            payload["perf/eval_gpu"] = 0.2 * dt
            payload["perf/train_forward"] = 0.3 * dt
            payload["perf/train_misc"] = 0.1 * dt
            print(REF40_PREFIX + json.dumps({k: v for k, v in payload.items()
                                             if not k.startswith("env/")} | {"t": now}),
                  flush=True)
            print(ENV_PANEL_PREFIX + json.dumps({"tds": 1.5, "_puffer_agent_steps": steps,
                                                 "_puffer_epoch": epoch,
                                                 "_puffer_phase_eval": 0}), flush=True)
            print("| fake dashboard |", flush=True)
        else:
            payload["perf/eval_model"] = 0.2 * dt
            payload["perf/eval_copy"] = 0.05 * dt
            payload["perf/train_model"] = 0.3 * dt
            payload["perf/train_misc"] = 0.1 * dt
            with open(metrics, "a") as handle:
                handle.write(json.dumps(payload) + "\n")
            print(f"fake p5 epoch {epoch}", flush=True)
        if now - start >= opts.duration:
            return opts.rc


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run")
    run.add_argument("--name", required=True)
    run.add_argument("--kind", choices=("ref40", "p5"), required=True)
    run.add_argument("--log", required=True)
    run.add_argument("--out", required=True)
    run.add_argument("--metrics-jsonl")
    run.add_argument("--cwd")
    run.add_argument("--env", action="append", default=[], help="KEY=VALUE")
    run.add_argument("--warmup", type=float, default=150.0)
    run.add_argument("--window", type=float, default=120.0)
    run.add_argument("--grace", type=float, default=3.0,
                     help="extra seconds after the window to catch the last sample")
    run.add_argument("--sample-interval", type=float, default=5.0)
    run.add_argument("--poll", type=float, default=0.5)
    run.add_argument("--kill-temp", type=float, default=86.0)
    run.add_argument("--kill-grace", type=float, default=30.0)
    run.add_argument("--startup-timeout", type=float, default=900.0)
    run.add_argument("--nvidia-smi", default="nvidia-smi")
    run.add_argument("cmd", nargs=argparse.REMAINDER)
    run.set_defaults(func=cmd_run)

    cool = sub.add_parser("wait-cool")
    cool.add_argument("--below", type=float, default=58.0)
    cool.add_argument("--poll", type=float, default=15.0)
    cool.add_argument("--timeout", type=float, default=1800.0)
    cool.add_argument("--nvidia-smi", default="nvidia-smi")
    cool.set_defaults(func=cmd_wait_cool)

    skip = sub.add_parser("skip")
    skip.add_argument("--name", required=True)
    skip.add_argument("--kind", required=True)
    skip.add_argument("--reason", required=True)
    skip.add_argument("--out", required=True)
    skip.set_defaults(func=cmd_skip)

    pre = sub.add_parser("preflight")
    pre.add_argument("--out", required=True)
    pre.add_argument("--file", action="append", default=[], help="LABEL=PATH")
    pre.add_argument("--git", action="append", default=[], help="LABEL=DIR")
    pre.add_argument("--extra", action="append", default=[], help="KEY=VALUE")
    pre.add_argument("--df")
    pre.add_argument("--nvidia-smi", default="nvidia-smi")
    pre.set_defaults(func=cmd_preflight)

    summ = sub.add_parser("summarize")
    summ.add_argument("--out", required=True)
    summ.add_argument("--preflight")
    summ.add_argument("--baseline", default="ref40_rr1")
    summ.add_argument("--probe", action="append", default=[])
    summ.set_defaults(func=cmd_summarize)

    fake = sub.add_parser("fake-trainer")
    fake.add_argument("--kind", choices=("ref40", "p5"), required=True)
    fake.add_argument("--duration", type=float, default=10.0)
    fake.add_argument("--interval", type=float, default=0.3)
    fake.add_argument("--sps", type=float, default=100000.0)
    fake.add_argument("--metrics")
    fake.add_argument("--rc", type=int, default=0)
    fake.set_defaults(func=cmd_fake_trainer)
    return ap


def main(argv=None):
    opts = build_parser().parse_args(argv)
    if getattr(opts, "cmd", None) and opts.cmd[:1] == ["--"]:
        opts.cmd = opts.cmd[1:]
    return opts.func(opts)


if __name__ == "__main__":
    raise SystemExit(main())
