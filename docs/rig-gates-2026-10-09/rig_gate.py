#!/usr/bin/env python3
"""Play a registered gate plan on the training rig, beside the trainer, at the lowest priority.

  python rig_gate.py start   PLAN.json --expect-sha256 <sha256 of PLAN.json> [--workers N] [--dry-run]
  python rig_gate.py status  PLAN.json
  python rig_gate.py collect PLAN.json --expect-sha256 <sha256 of PLAN.json>

This replaces launch_from_plan.py and `tools/droplet_tournament.py run` for gates played without
cloud machines. It creates no cloud resource and reads no cloud token. What it keeps from the
droplet runner, by importing that tool from the harness worktree at the plan's commit: the job
script, the shim build and machine record, the tournament command line, and the whole of the
copied-run verification (sha256 sums, manifest, schedule, integrity counters). A shard directory it
publishes has the files a droplet shard has, so the merge, acceptance and scoring scripts are used
unchanged.

start    refuses unless the plan hashes to --expect-sha256, every name in it is a plain name, the
         plan registers this file by its sha256 as its launch script, both checkouts are clean at
         their commits, every checkpoint blob has its registered sha256, no shard has a local
         directory, the rig has memory and disk to spare at that moment, and the gate's directory
         on the rig can be created new (one atomic mkdir). rig_start.json is written beside the
         plan before anything is launched, so a gate whose queue was launched can always be
         collected. Then: one isolated venv (CPU-only torch, so the gate cannot touch the GPU;
         made under its own lock), the pinned commit's sources, the checkpoints (re-hashed on the
         rig), the shim build, one job script per shard, and ONE detached queue. The queue raises
         its own out-of-memory score to the maximum, so the kernel prefers it and its workers as
         victims if memory runs out, waits for a rig-wide lock (so gates play one at a time), and
         plays the shards one after another. The lock is inherited by each job and its tournament
         process, so it stays held for as long as either lives. Nothing stays running on this
         machine. A start that fails is not re-entered: the gate is started again under a new
         name, from a new plan.
collect  refuses unless the harness worktree is still clean at the plan's commit and the runner it
         imports is the file `start` hashed. It copies each finished shard to
         <out_root>/<shard>/main.partial, verifies it exactly as the droplet runner verifies a
         copied run, and only then renames it to <out_root>/<shard>/main.
         Exit 0 when every shard is published, 4 while the queue is waiting or playing, 1 on a
         failure, a dead queue included.
status   prints each shard's stage, game count and log age, whether the queue is alive, and the
         sum of the resident memory of the gate's processes. It changes nothing.

Every command this tool runs on the rig, file transfers included, runs under `nice -n 19` and
`ionice -c 3`. It deletes nothing, on either machine. On the rig it writes under
/home/rache/bbgate; the only writes outside are uv's own cache when the venv is first made and the
compiler's temporary files.
"""
import argparse
import hashlib
import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys
import time

BLOB = "0000002999975936.bin"
HOST = "bbrig"
RIG_ROOT = "/home/rache/bbgate"
RIG_PY = RIG_ROOT + "/venv/bin/python"
RIG_LOCK = RIG_ROOT + "/queue.lock"
DEFAULT_WORKERS = 6
MIN_MEM_AVAILABLE_MB = 4000
MIN_DISK_FREE_GB = 20
LOW = "env -u BBPLAY_BUILD_DIR -u BBPLAY_LIB nice -n 19 ionice -c 3"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
PLAYER_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")
SSH_OPTS = ["-o", "ConnectTimeout=15", "-o", "BatchMode=yes", "-o", "ServerAliveInterval=15",
            "-o", "ServerAliveCountMax=8", "-o", "LogLevel=ERROR"]


class GateError(RuntimeError):
    pass


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---- the plan -------------------------------------------------------------------
def name_problems(plan):
    """Every name that reaches a path or a shell line on the rig must be a plain name."""
    problems = []
    if not NAME_RE.fullmatch(str(plan.get("gate", ""))):
        problems.append(f"gate name {plan.get('gate')!r} must match {NAME_RE.pattern}")
    for shard in plan.get("shards", {}):
        if not NAME_RE.fullmatch(str(shard)):
            problems.append(f"shard name {shard!r} must match {NAME_RE.pattern}")
    for name, spec in plan.get("players", {}).items():
        if not PLAYER_RE.fullmatch(str(name)):
            problems.append(f"player name {name!r} must match {PLAYER_RE.pattern}")
        if "checkpoint" in spec and not PLAYER_RE.fullmatch(str(spec["checkpoint"])):
            problems.append(f"checkpoint name {spec['checkpoint']!r} must match {PLAYER_RE.pattern}")
        for mask in spec.get("masks") or []:
            if not PLAYER_RE.fullmatch(str(mask)):
                problems.append(f"mask name {mask!r} must match {PLAYER_RE.pattern}")
    for chain in plan.get("checkpoints_sha256", {}):
        if not PLAYER_RE.fullmatch(str(chain)):
            problems.append(f"checkpoint key {chain!r} must match {PLAYER_RE.pattern}")
    return problems


def load_plan(path, expect=None):
    got = sha256_file(path)
    if expect is not None and got != expect.lower():
        raise GateError(f"plan hashes to {got}, not {expect}; nothing done")
    with open(path) as f:
        plan = json.load(f)
    problems = name_problems(plan)
    if problems:
        raise GateError("the plan's names are not usable; nothing done:\n  " + "\n  ".join(problems))
    return plan, got


def runner_path(plan):
    return os.path.join(os.path.expanduser(plan["harness_worktree"]), "tools", "droplet_tournament.py")


def load_runner(plan):
    """The droplet runner at the plan's commit, as a module. Only its machine-free parts are used."""
    spec = importlib.util.spec_from_file_location("droplet_tournament_pinned", runner_path(plan))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def worktree_problems(plan):
    problems = []
    root = os.path.expanduser(plan["harness_worktree"])
    if git(root, "rev-parse", "HEAD") != plan["harness_commit"]:
        problems.append(f"{root} is not at {plan['harness_commit']}")
    if git(root, "status", "--porcelain"):
        problems.append(f"{root} is not clean")
    return problems


def preflight(plan):
    """launch_from_plan.py's checks, unchanged."""
    problems = worktree_problems(plan)
    main = os.path.expanduser(plan["main_checkout"])
    if git(main, "rev-parse", "HEAD") != plan["main_checkout_commit"]:
        problems.append(f"{main} is not at {plan['main_checkout_commit']}")
    if git(main, "status", "--porcelain"):
        problems.append(f"{main} is not clean")
    store = os.path.expanduser(plan["checkpoint_store"])
    for chain, sha in plan["checkpoints_sha256"].items():
        path = os.path.join(store, chain, BLOB)
        if not os.path.isfile(path) or not os.path.isfile(path + ".lineage.json"):
            problems.append(f"missing {path} or its lineage sidecar")
        elif sha256_file(path) != sha:
            problems.append(f"{path} is not the registered {chain}")
    listed = sorted(p for pairs in plan["shards"].values() for p in pairs)
    if listed != sorted(",".join(str(x) for x in p) for p in plan["pairs"]):
        problems.append("the shards do not cover the registered pairs exactly once")
    launch = plan.get("launch") or {}
    if launch.get("runner_sha256") != sha256_file(runner_path(plan)):
        problems.append(f"{runner_path(plan)} is not the runner the plan registers")
    if launch.get("script") != "rig_gate.py" or launch.get("script_sha256") != sha256_file(os.path.abspath(__file__)):
        problems.append("the plan does not register this rig_gate.py by its sha256 as its launch script")
    return problems


def shard_spec(plan, shard, runner):
    """What one shard plays: checkpoints (name -> local blob), bots, pairs, extra tournament args."""
    store = os.path.expanduser(plan["checkpoint_store"])
    raw = [p.split(",") for p in plan["shards"][shard]]
    names = []
    for a, b, _n in raw:
        for name in (a, b):
            if name not in names:
                names.append(name)
    checkpoints, bots, extra = {}, {}, []
    for name in names:
        spec = plan["players"][name]
        if "bot" in spec:
            bots[name] = spec["bot"]
            continue
        checkpoints[name] = os.path.join(store, spec["checkpoint"], BLOB)
        if spec.get("masks"):
            extra += ["--mask", f"{name}={','.join(spec['masks'])}"]
    pairs = runner.plan_pairs([runner.parse_pair(",".join(p)) for p in raw],
                              set(checkpoints) | set(bots), None)
    sha = {name: plan["checkpoints_sha256"][plan["players"][name]["checkpoint"]] for name in checkpoints}
    return {"checkpoints": checkpoints, "bots": bots, "pairs": pairs, "extra": extra,
            "checkpoint_sha": sha, "tasks": runner.expected_tasks(pairs)}


# ---- rig paths ------------------------------------------------------------------
def gate_root(plan):
    name = str(plan.get("gate", ""))
    if not NAME_RE.fullmatch(name):
        raise GateError(f"gate name {name!r} must match {NAME_RE.pattern}")
    return f"{RIG_ROOT}/{name}"


def run_dir(plan, shard):
    if not NAME_RE.fullmatch(str(shard)):
        raise GateError(f"shard name {shard!r} must match {NAME_RE.pattern}")
    return f"{gate_root(plan)}/run-{shard}"


def point(runner, plan, run):
    """Aim the runner's script generators at this gate's directories on the rig."""
    root = gate_root(plan)
    runner.REMOTE_ROOT = root
    runner.REMOTE_SRC = root + "/src"
    runner.REMOTE_RUN = run
    runner.REMOTE_OUT = run + "/main"
    runner.REMOTE_PY = RIG_PY


def setup_script(torch, numpy):
    return f"""#!/bin/bash
set -euo pipefail
exec 8>> {RIG_ROOT}/setup.lock
flock 8
if [ ! -x {RIG_PY} ]; then
  "$HOME/.local/bin/uv" venv --quiet --python 3.12 {RIG_ROOT}/venv
  "$HOME/.local/bin/uv" pip install --quiet --python {RIG_PY} numpy=={numpy}
  "$HOME/.local/bin/uv" pip install --quiet --python {RIG_PY} --index-url https://download.pytorch.org/whl/cpu torch=={torch}
fi
{RIG_PY} -c 'import torch, numpy; assert torch.__version__.split("+")[0] == "{torch}", torch.__version__; assert numpy.__version__ == "{numpy}", numpy.__version__; assert not torch.cuda.is_available(); print("torch", torch.__version__, "numpy", numpy.__version__)'
echo SETUP_OK
"""


def queue_script(plan, shards):
    """One shard after another, one gate at a time.

    The queue first makes itself and everything it starts the kernel's first choice if memory
    runs out (the trainer is never chosen before it), then waits for the rig-wide lock. Each job
    and its tournament process inherit descriptor 9, so the lock is held for as long as either
    lives, even if this script is killed. The first failure stops the queue."""
    root = gate_root(plan)
    lines = ["#!/bin/bash", "set -uo pipefail",
             f"echo $$ > {root}/QUEUE_PID",
             f"echo 1000 > /proc/$$/oom_score_adj || {{ echo oom_score_adj > {root}/QUEUE_FAILED; exit 8; }}",
             "unset BBPLAY_BUILD_DIR BBPLAY_LIB",
             "export CUDA_VISIBLE_DEVICES=",
             f"exec 9>> {RIG_LOCK}",
             f"date +%s > {root}/QUEUE_WAITING",
             f"flock 9 || {{ echo lock > {root}/QUEUE_FAILED; exit 9; }}",
             f"date +%s > {root}/QUEUE_STARTED"]
    for shard in shards:
        run = run_dir(plan, shard)
        lines.append(f"bash {run}/job.sh > {run}/job.log 2>&1 < /dev/null "
                     f"|| {{ echo {shard} > {root}/QUEUE_FAILED; exit 1; }}")
    lines.append(f"echo done > {root}/QUEUE_DONE")
    return "\n".join(lines) + "\n"


def admission_problems(text):
    """`text` is two lines from the rig: MemAvailable in kB, free disk in GB."""
    try:
        mem_kb, disk_gb = (int(x) for x in text.split()[:2])
    except ValueError:
        return [f"cannot read the rig's memory and disk from {text!r}"], None
    problems = []
    if mem_kb // 1024 < MIN_MEM_AVAILABLE_MB:
        problems.append(f"the rig has {mem_kb // 1024} MB available, under {MIN_MEM_AVAILABLE_MB}")
    if disk_gb < MIN_DISK_FREE_GB:
        problems.append(f"the rig has {disk_gb} GB of disk free, under {MIN_DISK_FREE_GB}")
    return problems, {"mem_available_mb": mem_kb // 1024, "disk_free_gb": disk_gb}


# ---- ssh ------------------------------------------------------------------------
class Rig:
    """Every command on the rig, transfers included, runs at the lowest CPU and I/O priority."""

    def __init__(self, host=HOST):
        self.host = host

    def _ssh(self, command, **kw):
        return subprocess.run(["ssh", *SSH_OPTS, self.host, f"{LOW} bash -c {shlex.quote(command)}"], **kw)

    def run(self, command, check=True, timeout=600, stdin_text=None):
        proc = self._ssh(command, input=stdin_text,
                         stdin=None if stdin_text is not None else subprocess.DEVNULL,
                         capture_output=True, text=True, timeout=timeout)
        if check and proc.returncode != 0:
            raise GateError(f"rig command failed ({proc.returncode}): {command[:100]}\n"
                            f"{proc.stdout[-2000:]}{proc.stderr[-2000:]}")
        return proc

    def script(self, text, log_path, timeout):
        return self.run(f"bash -s 2>&1 | tee {shlex.quote(log_path)}; exit ${{PIPESTATUS[0]}}",
                        stdin_text=text, timeout=timeout)

    def put(self, local, remote, timeout=1800):
        with open(local, "rb") as f:
            proc = self._ssh(f"cat > {shlex.quote(remote)}", stdin=f, capture_output=True, timeout=timeout)
        if proc.returncode != 0:
            raise GateError(f"upload to the rig failed: {local}\n{proc.stderr[-1000:]!r}")

    def get(self, remote, local, check=True, timeout=1800):
        proc = self._ssh(f"cat {shlex.quote(remote)}", stdin=subprocess.DEVNULL, capture_output=True,
                         timeout=timeout)
        if proc.returncode != 0:
            if check:
                raise GateError(f"download from the rig failed: {remote}\n{proc.stderr[-1000:]!r}")
            return False
        with open(local, "wb") as f:
            f.write(proc.stdout)
        return True


def queue_state(rig, plan):
    """waiting, playing, done, failed:<what>, dead (launched and gone with no end marker), or absent."""
    root = gate_root(plan)
    out = rig.run(
        f"if [ -e {root}/QUEUE_DONE ]; then echo done; "
        f"elif [ -e {root}/QUEUE_FAILED ]; then echo failed:$(cat {root}/QUEUE_FAILED); "
        f"elif [ ! -e {root}/QUEUE_PID ]; then echo absent; "
        f"elif ! kill -0 $(cat {root}/QUEUE_PID) 2>/dev/null; then echo dead; "
        f"elif [ -e {root}/QUEUE_STARTED ]; then echo playing; else echo waiting; fi",
        check=False, timeout=60).stdout.strip()
    return out or "unreachable"


# ---- commands -------------------------------------------------------------------
def cmd_start(args):
    plan, plan_sha = load_plan(args.plan, args.expect_sha256)
    problems = preflight(plan)
    if problems:
        raise GateError("nothing started:\n  " + "\n  ".join(problems))
    if not 1 <= args.workers <= 8:
        raise GateError("--workers must be in 1..8")
    runner = load_runner(plan)
    shards = sorted(plan["shards"])
    out_root = os.path.expanduser(plan["out_root"])
    for shard in shards:
        if os.path.exists(os.path.join(out_root, shard)):
            raise GateError(f"{shard} already has a directory under {out_root}; nothing started")
    specs = {shard: shard_spec(plan, shard, runner) for shard in shards}
    root, commit = gate_root(plan), plan["harness_commit"]
    here = os.path.dirname(os.path.abspath(args.plan))
    if os.path.exists(os.path.join(here, "rig_start.json")):
        raise GateError("rig_start.json already exists beside the plan; this gate was started")
    jobs = {}
    for shard in shards:
        s = specs[shard]
        point(runner, plan, run_dir(plan, shard))
        argv = runner.tournament_argv(s["checkpoints"], s["bots"], s["pairs"], plan["seed0"],
                                      args.workers, out_dir=runner.REMOTE_OUT, extra=s["extra"],
                                      games_per_worker=plan["games_per_worker"])
        jobs[shard] = runner.job_script(argv, args.workers)
    queue = queue_script(plan, shards)
    if args.dry_run:
        for shard in shards:
            print(f"--- {shard}: {specs[shard]['tasks']} games\n{jobs[shard]}")
        print("--- queue\n" + queue)
        return 0

    rig = Rig(args.host)
    probe = rig.run("awk '/^MemAvailable:/ {print $2}' /proc/meminfo; "
                    "df -BG --output=avail /home/rache | tail -1 | tr -dc 0-9; echo").stdout
    problems, headroom = admission_problems(probe)
    if problems:
        raise GateError("nothing started:\n  " + "\n  ".join(problems))
    made = rig.run(f"mkdir -p {RIG_ROOT} && mkdir {root} && echo made", check=False)
    if made.stdout.strip() != "made":
        raise GateError(f"{root} already exists on the rig (or cannot be made); nothing started")
    started = {"schema": "bbplay-rig-start-v3", "gate": plan["gate"], "plan_sha256": plan_sha,
               "host": args.host, "rig_root": root, "workers": args.workers, "nice": 19,
               "commit": commit, "shards": shards, "runner_sha256": sha256_file(runner_path(plan)),
               "rig_gate_sha256": sha256_file(os.path.abspath(__file__)), "headroom_at_start": headroom,
               "started_local": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    with open(os.path.join(here, "rig_start.json"), "w") as f:
        json.dump(started, f, indent=1)
    log(f"gate {plan['gate']}: {sum(s['tasks'] for s in specs.values())} games in {len(shards)} "
        f"shards, {args.workers} workers at nice 19, commit {commit[:12]}; rig has "
        f"{headroom['mem_available_mb']} MB available and {headroom['disk_free_gb']} GB of disk free")
    rig.run(f"mkdir -p {root}/src {root}/build")
    rig.script(setup_script(runner.TORCH_VERSION, runner.NUMPY_VERSION), f"{root}/build/setup.log",
               timeout=1800)
    archive = os.path.join(here, "rig_src.tar.gz")
    with open(archive, "wb") as f:
        subprocess.run(["git", "-C", os.path.expanduser(plan["harness_worktree"]), "archive",
                        "--format=tar.gz", commit, "--", *runner.SYNC_PATHS], check=True, stdout=f)
    rig.put(archive, f"{root}/src.tar.gz")
    rig.run(f"tar -xzf {root}/src.tar.gz -C {root}/src && echo {commit} > {root}/src/SOURCE_COMMIT")
    point(runner, plan, root + "/build")
    uploaded = {}
    for shard in shards:
        for name, local in specs[shard]["checkpoints"].items():
            target = runner.remote_checkpoint_path(name, local)
            if target in uploaded:
                continue
            rig.run(f"mkdir -p {shlex.quote(os.path.dirname(target))}")
            rig.put(local, target)
            rig.put(local + ".lineage.json", target + ".lineage.json")
            got = rig.run(f"sha256sum {shlex.quote(target)}").stdout.split()[0]
            if got != specs[shard]["checkpoint_sha"][name]:
                raise GateError(f"{name} on the rig hashes to {got}; nothing started")
            uploaded[target] = got
    log(f"synced commit {commit[:12]} and {len(uploaded)} checkpoint(s), each re-hashed on the rig")
    built = rig.script(runner.build_script(commit), f"{root}/build/build.log", timeout=900)
    machine = json.loads([l for l in built.stdout.splitlines() if l.startswith("{")][-1])
    log(f"shim built: {machine['cpu_model']}, {machine['cc']}, python {machine['python']}, "
        f"torch {machine['torch']}, library {machine['library_sha256'][:12]}")
    for shard in shards:
        run = run_dir(plan, shard)
        rig.run(f"mkdir -p {run} && cp {root}/build/machine.json {run}/machine.json")
        rig.run(f"cat > {run}/job.sh", stdin_text=jobs[shard])
    rig.run(f"cat > {root}/queue.sh", stdin_text=queue)
    with open(os.path.join(here, "rig_machine.json"), "w") as f:
        json.dump(machine, f, indent=1)
    rig.run(f"nohup setsid bash {root}/queue.sh > {root}/queue.log 2>&1 < /dev/null & echo started",
            timeout=60)
    time.sleep(3)
    state = queue_state(rig, plan)
    log(f"queue launched on {args.host} under nohup: {state}. `status` to look, `collect` when it is done")
    return 0 if state in ("waiting", "playing", "done") else 1


def shard_state(rig, plan, shard):
    run = run_dir(plan, shard)
    probe = (f"cat {run}/EXIT 2>/dev/null || echo -; cat {run}/STAGE 2>/dev/null || echo -; "
             f"wc -l < {run}/main/games.jsonl 2>/dev/null || echo 0; "
             f"echo $(( $(date +%s) - $(stat -c %Y {run}/tournament.log 2>/dev/null || date +%s) )); "
             f"tail -n 1 {run}/tournament.log 2>/dev/null | cut -c1-160")
    lines = rig.run(probe, check=False, timeout=60).stdout.splitlines()
    lines += ["-"] * (5 - len(lines))
    return {"exit": lines[0].strip(), "stage": lines[1].strip(), "games": lines[2].strip(),
            "age": lines[3].strip(), "tail": lines[4].strip()}


def cmd_status(args):
    plan, _ = load_plan(args.plan)
    rig, root = Rig(args.host), gate_root(plan)
    runner = load_runner(plan)
    for shard in sorted(plan["shards"]):
        st = shard_state(rig, plan, shard)
        tasks = shard_spec(plan, shard, runner)["tasks"]
        print(f"{shard}: exit {st['exit']} stage {st['stage']} games {st['games']}/{tasks} "
              f"log age {st['age']} s | {st['tail']}")
    print("queue:", queue_state(rig, plan))
    marks = rig.run(
        f"pid=$(cat {root}/QUEUE_PID 2>/dev/null); "
        f"if [ -n \"$pid\" ]; then ps -s $pid -o rss= 2>/dev/null | "
        f"awk '{{s+=$1; n+=1}} END {{printf \"gate processes: %d, resident memory summed: %d MB\\n\", n, s/1024}}'; fi; "
        f"awk '/^MemAvailable:/ {{printf \"rig memory available: %d MB\\n\", $2/1024}}' /proc/meminfo",
        check=False)
    print(marks.stdout.strip())
    return 0


def cmd_collect(args):
    plan, plan_sha = load_plan(args.plan, args.expect_sha256)
    here = os.path.dirname(os.path.abspath(args.plan))
    with open(os.path.join(here, "rig_start.json")) as f:
        started = json.load(f)
    if started["plan_sha256"] != plan_sha:
        raise GateError("rig_start.json was written for another plan")
    problems = worktree_problems(plan)
    if sha256_file(runner_path(plan)) != started["runner_sha256"]:
        problems.append(f"{runner_path(plan)} is not the file `start` hashed")
    if problems:
        raise GateError("nothing collected; the verification code is not the plan's:\n  "
                        + "\n  ".join(problems))
    runner = load_runner(plan)
    rig = Rig(args.host)
    out_root = os.path.expanduser(plan["out_root"])
    pending, failed = [], []
    for shard in sorted(plan["shards"]):
        out_dir = os.path.join(out_root, shard, "main")
        if os.path.isdir(out_dir):
            log(f"{shard}: already published (not checked again here; the merge re-checks it)")
            continue
        st, run = shard_state(rig, plan, shard), run_dir(plan, shard)
        if st["exit"] == "-":
            pending.append(shard)
            log(f"{shard}: not finished (stage {st['stage']}, {st['games']} games)")
            continue
        if st["exit"] != "0":
            failed.append(shard)
            fail_dir = out_dir + ".failed"
            os.makedirs(fail_dir, exist_ok=True)
            for fname in ("job.log", "tournament.log", "report.txt", "EXIT", "STAGE"):
                rig.get(f"{run}/{fname}", os.path.join(fail_dir, fname), check=False, timeout=120)
            log(f"{shard}: the job exited {st['exit']}; logs are in {fail_dir}")
            continue
        spec = shard_spec(plan, shard, runner)
        partial = out_dir + ".partial"
        os.makedirs(partial, exist_ok=True)
        for fname in runner.RESULT_FILES + runner.EXTRA_FILES:
            rig.get(f"{run}/main/{fname}", os.path.join(partial, fname))
        for fname in ("tournament.log", "job.log", "cpu-before", "cpu-after", "STARTED",
                      "STATS_STARTED", "STATS_DONE"):
            rig.get(f"{run}/{fname}", os.path.join(partial, fname), check=False)
        with open(os.path.join(partial, "SHA256SUMS")) as f:
            sums = runner.parse_sha256sums(f.read())
        problems = runner.verify_files(partial, sums)
        with open(os.path.join(partial, "manifest.json")) as f:
            manifest = json.load(f)
        with open(os.path.join(partial, "COMPLETE.json")) as f:
            complete = json.load(f)
        with open(os.path.join(partial, "games.jsonl")) as f:
            games = [json.loads(line) for line in f if line.strip()]
        problems += runner.verify_run(manifest, complete, games, plan["harness_commit"],
                                      spec["checkpoint_sha"], spec["pairs"], plan["seed0"],
                                      bots=spec["bots"], games_per_worker=plan["games_per_worker"])
        bad = {k: v for k, v in runner.integrity_totals(games).items() if v}
        if bad:
            problems.append(f"nonzero integrity counters: {bad}")
        if problems:
            failed.append(shard)
            log(f"{shard}: verification failed; left in {partial}:\n  " + "\n  ".join(problems))
            continue
        with open(os.path.join(partial, "machine.json")) as f:
            machine = json.load(f)
        result = {"schema": "bbplay-rig-run-v1", "name": shard, "host": started["host"],
                  "workers": started["workers"], "nice": started["nice"],
                  "games_per_worker": plan["games_per_worker"], "commit": plan["harness_commit"],
                  "machine": machine, "tasks": spec["tasks"],
                  "games_per_second_wall": complete.get("games_per_second_wall"),
                  "tournament_wall_seconds": complete.get("wall_seconds"), "sha256": sums}
        with open(os.path.join(partial, "rig_run.json"), "w") as f:
            json.dump(result, f, indent=1)
        os.rename(partial, out_dir)
        log(f"{shard}: verified {len(sums)} files by sha256, the manifest, {len(games)} games and "
            f"zero integrity counters; {result['games_per_second_wall']} games/s wall")
    if failed:
        log(f"FAILED: {failed}")
        return 1
    if pending:
        state = queue_state(rig, plan)
        if state in ("waiting", "playing"):
            log(f"queue {state}; not finished: {pending}")
            return 4
        log(f"the queue is {state} and these shards did not finish: {pending}. Nothing more will "
            "be played; a new entry decides about them")
        return 1
    log("every shard is published; score with score_from_plan.py")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--host", default=HOST)
    sub = ap.add_subparsers(dest="command", required=True)
    start = sub.add_parser("start")
    start.add_argument("plan")
    start.add_argument("--expect-sha256", required=True)
    start.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    start.add_argument("--dry-run", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("plan")
    collect = sub.add_parser("collect")
    collect.add_argument("plan")
    collect.add_argument("--expect-sha256", required=True)
    args = ap.parse_args(argv)
    try:
        return {"start": cmd_start, "status": cmd_status, "collect": cmd_collect}[args.command](args)
    except GateError as exc:
        print(f"rig_gate: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
