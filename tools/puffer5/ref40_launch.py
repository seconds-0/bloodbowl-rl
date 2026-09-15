#!/usr/bin/env python3
"""Benchmark launcher for the PufferLib 4.0 reference build (scratch copy).

Runs the ordinary 4.0 Puffer CLI from a scratch copy of the live tree, keeping
the D225 CUDA init order that tools/puffer_cuda_runtime.py enforces: CUDART is
probed before the native extension is imported and re-probed afterwards. It
does NOT publish into a pending screen manifest (that contract needs a separate
launcher-side CUDA probe and a run directory); it writes the same evidence
object to $BENCH40_EVIDENCE instead.

It also wraps pufferl.print_dashboard so every dashboard refresh first emits
one machine-readable line:

    BENCH40_JSON {"t": <wall time>, "SPS": ..., "agent_steps": ..., "epoch": ...,
                  "perf/rollout": ..., "perf/eval_gpu": ..., ...}

with every non-env/ key of the trainer's flat logs. The original dashboard is
still printed so the probe carries the same logging overhead as a live run.

Usage (cwd = <scratch>/vendor/PufferLib, PYTHONPATH=<scratch>/vendor/PufferLib):
    REF40_TOOLS=<scratch>/tools BENCH40_EVIDENCE=/path/evidence.json \
        python ref40_launch.py train bloodbowl --tag ... [4.0 CLI flags]
"""
import json
import os
import sys
import time


def _emit(flat_logs):
    payload = {"t": time.time()}
    for key, value in flat_logs.items():
        if key.startswith("env/"):
            continue
        if isinstance(value, bool):
            payload[key] = int(value)
        elif isinstance(value, (int, float)):
            payload[key] = float(value)
    line = "BENCH40_JSON " + json.dumps(payload, sort_keys=True) + "\n"
    sys.stdout.flush()
    os.write(sys.stdout.fileno(), line.encode("utf-8"))


def main():
    tools = os.environ.get("REF40_TOOLS")
    if not tools or not os.path.isfile(os.path.join(tools, "puffer_cuda_runtime.py")):
        print("ref40_launch: REF40_TOOLS must point at the scratch tools/ dir",
              file=sys.stderr)
        return 2
    sys.path.insert(0, tools)
    import puffer_cuda_runtime as rt  # noqa: E402
    sys.path.pop(0)

    runtime, evidence = rt.begin_cuda_runtime_preflight()
    from pufferlib import _C  # noqa: F401,E402  (import after CUDART probe)
    import pufferlib  # noqa: E402
    from pufferlib import pufferl  # noqa: E402
    evidence = rt.finish_cuda_runtime_preflight(runtime, evidence)
    rt.validate_cuda_runtime_evidence(evidence)
    evidence["pufferlib_file"] = pufferlib.__file__
    evidence["extension_file"] = _C.__file__
    out = os.environ.get("BENCH40_EVIDENCE")
    if out:
        with open(out, "w") as handle:
            json.dump(evidence, handle, sort_keys=True, indent=1)
    print("BENCH40_RUNTIME " + json.dumps(evidence, sort_keys=True), flush=True)

    original = pufferl.print_dashboard

    def dashboard(args, model_size, flat_logs, *a, **kw):
        _emit(flat_logs)
        return original(args, model_size, flat_logs, *a, **kw)

    pufferl.print_dashboard = dashboard
    sys.argv = ["puffer"] + sys.argv[1:]
    result = pufferl.main()
    return 0 if result is None else int(result)


if __name__ == "__main__":
    raise SystemExit(main())
