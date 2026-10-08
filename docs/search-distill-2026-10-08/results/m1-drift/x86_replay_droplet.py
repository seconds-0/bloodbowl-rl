#!/usr/bin/env python3
"""Diagnostic only: run diag_logp.py on one fresh droplet of the label stage's size.

It asks whether an independent x86 machine, replaying the recorded trails,
recomputes the log-probabilities the label droplets recorded. One game per
forward (as the label tool ran the seat) in 8 parallel slices, and 32 games per
forward in one process (as the dataset tool runs). It writes no dataset and
plays no game. The droplet's lifecycle is the label launcher's own (the same
calls in the same order as distill_droplet.run_shard): one droplet, the id
recorded when the create is answered, teardown on every exit path, and nothing
of any other run or project is touched.

  x86_replay_droplet.py --harness-export X --plan PLAN.json --expect-sha256 H \\
      --shard-dir NAME=DIR [...] --out DIR --max-hours 1
"""
import argparse
import json
import os
import secrets
import shlex
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TOOLS = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.dont_write_bytecode = True
sys.path.insert(0, TOOLS)
import distill_droplet as L  # noqa: E402

SLICES = 8


def job(plan_sha, blob, shard_names):
    DT = L.DT
    run, py, tools = DT.REMOTE_RUN, DT.REMOTE_PY, L.remote_paths()["tools"]
    shards = " ".join(f"--shard-dir {n}={run}/shards/{n}" for n in shard_names)
    common = (f"{py} {tools}/diag_logp.py --tools {tools} --harness {DT.REMOTE_SRC} "
              f"--plan {L.remote_paths()['plan']} --expect-sha256 {plan_sha} "
              f"--checkpoint {shlex.quote(blob)} {shards}")
    lines = ["#!/bin/bash", "set -uo pipefail", f"cd {DT.REMOTE_SRC}",
             "export OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1",
             f"mkdir -p {run}/diag", "pids=()"]
    for i in range(SLICES):
        lines.append(f"{common} --batch-games 1 --slice {i}/{SLICES} --out {run}/diag/b1.{i}.jsonl "
                     f"> {run}/diag/b1.{i}.log 2>&1 & pids+=($!)")
    lines.append(f"{common} --batch-games 32 --out {run}/diag/b32.jsonl "
                 f"> {run}/diag/b32.log 2>&1 & pids+=($!)")
    lines += ["rc=0", 'for p in "${pids[@]}"; do wait "$p" || rc=1; done',
              f"cat {run}/diag/b1.*.jsonl > {run}/diag/b1.jsonl",
              f"echo $rc > {run}/EXIT.tmp && mv {run}/EXIT.tmp {run}/EXIT"]
    return "\n".join(lines) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--harness-export", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--shard-dir", action="append", default=[], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-hours", type=float, default=1.0)
    ap.add_argument("--checkpoint-store", default=os.path.expanduser(
        "~/Code/bb-play-harness/.play-artifacts/checkpoints"))
    ap.add_argument("--harness-repo", default=os.path.expanduser("~/Code/bb-play-harness"))
    a = ap.parse_args()
    with open(a.plan) as f:
        lifecycle = json.load(f)["lifecycle_sha256"][L.LIFECYCLE]
    L.load_dt(a.harness_export, lifecycle)
    DT = L.DT
    shard_dirs = dict(item.split("=", 1) for item in a.shard_dir)
    run_id = secrets.token_hex(3)
    # prepare() runs the launcher's offline checks (plan hash, tool files, export, checkpoint).
    # The name is this diagnostic's own, so no path of the registered run is involved.
    args = argparse.Namespace(
        plan=a.plan, expect_sha256=a.expect_sha256, harness_export=a.harness_export,
        harness_repo=a.harness_repo, checkpoint_store=a.checkpoint_store, shard=["m1-s1"],
        name="x86diag", out_root=os.path.join(os.path.abspath(a.out), "launcher-check"),
        keep=False)
    ready = L.prepare(args)
    plan, plan_sha, commit = ready["plan"], ready["plan_sha"], ready["commit"]
    if os.path.exists(a.out) and os.listdir(a.out):
        raise SystemExit(f"{a.out} is not empty")
    os.makedirs(a.out, exist_ok=True)
    api = DT.Api(DT.read_token(env_file=DT.DEFAULT_ENV_FILE))
    size = DT.pick_size(api.get("/sizes?per_page=200")["sizes"], DT.DEFAULT_SIZE,
                        DT.DEFAULT_REGION, DT.MAX_HOURLY_DEFAULT)
    price = float(size["price_hourly"])
    unique = DT.validate_name(f"x86diag-{run_id}")
    limit = int(api.get("/account")["account"]["droplet_limit"])
    existing = len(L.list_all(api, "/droplets", "droplets"))
    refusal = DT.limit_refusal(existing, limit) or L.account_refusal(api, unique)
    if refusal:
        raise SystemExit(f"{refusal}. Nothing was created and nothing is deleted to make room.")
    state = DT.State(unique, root=DT.STATE_ROOT)
    if os.path.exists(state.dir):
        raise SystemExit(f"{state.dir} exists")
    lock = state.lock()
    state.write("run-id", run_id)
    state.write("price-hourly", price)
    DT.log(f"diagnostic droplet {unique}: {size['vcpus']} vCPU at ${price:.5f}/h, "
           f"--max-hours {a.max_hours}; state {state.dir}")

    def on_signal(signum, _frame):
        raise DT.Interrupted(f"signal {signum}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    clock = L.Clock(a.max_hours)
    r = L.remote_paths()
    ok = False
    try:
        fingerprint = DT.create_key(api, state, unique)
        droplet_id = DT.create_droplet(api, state, unique, DT.DEFAULT_REGION, DT.DEFAULT_SIZE,
                                       fingerprint)
        ip = DT.wait_active(api, droplet_id, timeout=clock.cap(600, "the boot"))
        state.write("ip", ip)
        remote = DT.Remote(state.dir, ip)
        DT.wait_ssh(remote, timeout=clock.cap(300, "ssh"))
        DT.log(f"droplet {droplet_id} up at {ip}; installing")
        remote.script(DT.setup_script(DT.TORCH_VERSION, DT.NUMPY_VERSION), "setup.log",
                      timeout=clock.cap(1500, "the install"))
        archive = state.path("src.tar.gz")
        L.make_archive(a.harness_repo, commit, archive)
        remote.put(archive, f"{DT.REMOTE_ROOT}/src.tar.gz", timeout=clock.cap(600, "upload"))
        remote.run(f"tar -xzf {DT.REMOTE_ROOT}/src.tar.gz -C {DT.REMOTE_SRC} && "
                   f"echo {commit} > {DT.REMOTE_SRC}/SOURCE_COMMIT", timeout=clock.cap(300, "unpack"))
        remote.run(f"mkdir -p {r['tools']}", timeout=clock.cap(60, "mkdir"))
        for fname in L.TOOL_FILES:
            remote.put(os.path.join(TOOLS, fname), f"{r['tools']}/{fname}",
                       timeout=clock.cap(120, "tool upload"))
        remote.put(os.path.join(HERE, "diag_logp.py"), f"{r['tools']}/diag_logp.py",
                   timeout=clock.cap(120, "tool upload"))
        ck = plan["checkpoint"]
        blob = DT.remote_checkpoint_path(ck["name"], ready["checkpoint"])
        remote.run(f"mkdir -p {shlex.quote(os.path.dirname(blob))}", timeout=clock.cap(60, "mkdir"))
        remote.put(ready["checkpoint"], blob, timeout=clock.cap(600, "checkpoint upload"))
        remote.put(ready["checkpoint"] + ".lineage.json", blob + ".lineage.json",
                   timeout=clock.cap(120, "sidecar upload"))
        remote.put(os.path.abspath(a.plan), r["plan"], timeout=clock.cap(120, "plan upload"))
        for name, directory in shard_dirs.items():
            remote.run(f"mkdir -p {DT.REMOTE_RUN}/shards/{name}", timeout=clock.cap(60, "mkdir"))
            for fname in L.RESULT_FILES:
                remote.put(os.path.join(directory, fname),
                           f"{DT.REMOTE_RUN}/shards/{name}/{fname}",
                           timeout=clock.cap(900, "shard upload"))
        built = remote.script(DT.build_script(commit), "build.log",
                              timeout=clock.cap(900, "the shim build"))
        machine = json.loads([l for l in built.stdout.splitlines() if l.startswith("{")][-1])
        DT.log(f"shim built: {machine}")
        remote.run(f"cat > {DT.REMOTE_RUN}/job.sh", stdin_text=job(plan_sha, blob, list(shard_dirs)),
                   timeout=clock.cap(60, "job upload"))
        remote.run(f"nohup setsid bash {DT.REMOTE_RUN}/job.sh > {DT.REMOTE_RUN}/job.log 2>&1 "
                   f"< /dev/null & echo started", timeout=clock.cap(60, "launch"))
        started = time.time()
        while True:
            if clock.left() <= 1:
                raise DT.RunnerError("--max-hours reached while the diagnostic ran")
            try:
                got = remote.run(
                    f"test -f {DT.REMOTE_RUN}/EXIT && echo FINISHED; "
                    f"tail -q -n 1 {DT.REMOTE_RUN}/diag/b1.0.log {DT.REMOTE_RUN}/diag/b32.log "
                    "2>/dev/null | tr '\\n' '|'", check=False, timeout=60).stdout.strip()
            except Exception as exc:                      # a lost poll is not the end
                got = f"poll failed: {exc}"
            DT.log(f"{time.time() - started:.0f} s: {got[:200]}")
            if got.startswith("FINISHED"):
                break
            time.sleep(30)
        for fname in ["b1.jsonl", "b32.jsonl", "b32.log"] + [f"b1.{i}.log" for i in range(SLICES)]:
            remote.get(f"{DT.REMOTE_RUN}/diag/{fname}", os.path.join(a.out, fname), check=False,
                       timeout=clock.cap(600, "the fetch"))
        remote.get(f"{DT.REMOTE_RUN}/EXIT", os.path.join(a.out, "EXIT"), check=False, timeout=60)
        with open(os.path.join(a.out, "machine.json"), "w") as f:
            json.dump({"droplet_id": droplet_id, "name": unique, "machine": machine,
                       "size": DT.DEFAULT_SIZE, "region": DT.DEFAULT_REGION,
                       "price_hourly": price}, f, indent=1)
        ok = True
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        public_key = state.read("key.pub")
        try:
            DT.teardown(api, state, unique)
            L.reconcile(api, unique, public_key)
        except BaseException:
            print(f"TEARDOWN FAILED: droplet id {state.read('droplet-id')} (state {state.dir}) may "
                  f"STILL BE BILLING. Run: python {ready['export']}/{L.LIFECYCLE} --env-file "
                  f"{DT.DEFAULT_ENV_FILE} destroy --name {unique}", file=sys.stderr, flush=True)
            raise
        DT.log(f"cost about ${float(state.read('cost') or 0.0):.3f}")
    del lock
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:        # RunnerError and the rest: the teardown has already run
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)
