#!/usr/bin/env python3
"""Run shards of the END_TURN probe's plan on throwaway DigitalOcean droplets.

One droplet runs one shard (the plan's shards are one checkpoint each). The
droplet lifecycle is the harness's tools/droplet_tournament.py, imported from
the export of the pinned commit and not copied: its tag and disposable ssh key,
its setup and build scripts, its polling, its state directory and its teardown.
The file is held to the hash the plan records before it is imported. The flow
is tools/search_ab_droplet.py's (D425, D430) with the probe in place of the
search A/B, and with these differences:

  names      every run draws a random run id; the droplet, its ssh key and its
             local state are named NAME-SHARD-RUNID. Before anything is
             created the launcher refuses if local state of that name exists
             or the account already lists a droplet or key of that name. That
             makes it very unlikely, not impossible, that the lifecycle's
             recovery (by tag, exact name and creation time) finds anything
             but this run's droplet: the listings read the first 200 entries
             only, and another process could create the same name between the
             check and the create.
  time       --max-hours is the budget for the droplet's life. Before each
             phase the launcher checks the time left before that limit less a
             reserve for the teardown, does not start a phase past it, and
             gives its own ssh and copy calls no longer timeout than the time
             left. The harness's own calls (the key, the create, the wait for
             boot, the poll) check a deadline between attempts and can overrun
             it inside an attempt. It is a budget, not a ceiling.
  failure    on any failure only small logs are fetched, for at most 45
             seconds in all, and then the droplet is destroyed. Records of a
             failed shard are not fetched: the plan does not read them.
  money      shards x --max-hours x the hourly price must not exceed
             --max-total-usd or nothing is created; every limit must be a
             finite positive number; a child process applies the same guard
             for the whole run.

  endturn_droplet.py run --name et1 --plan PLAN.json --expect-sha256 H \\
      --harness-export EXPORT --max-hours 3.5 --max-total-usd 3.5 \\
      [--shard chain55 ...] [--dry-run [--assume-hourly 0.16667]]

  endturn_droplet.py rehearse --plan PLAN.smoke.json --expect-sha256 H \\
      --harness-export EXPORT --shard chain55 --dir SCRATCH --python VENV_PYTHON

What the budget is and is not. When every call returns, a shard costs at most
--max-hours x price plus the teardown, which normally takes under five minutes.
That is a nominal budget. It is NOT a ceiling:
  - the harness's teardown retries each of its API calls up to 120 times (30 s
    timeout, 5 s sleep): one call can last about 70 minutes when DigitalOcean
    is slow or down, the teardown makes several calls, and the droplet bills
    until its delete is accepted;
  - if this process dies before its teardown (the machine sleeps or loses
    power, the process is killed), if a create's answer is lost and the
    droplet appears later than the recovery looks for it, or if a delete
    fails, the droplet bills until an operator destroys it.
The commands for that need only the export (and the token file this run used).
They are printed at launch and written to OUT/NAME/CLEANUP.txt before any
create:

  python EXPORT/tools/droplet_tournament.py --env-file ENV status
  python EXPORT/tools/droplet_tournament.py --env-file ENV destroy --name NAME-SHARD-RUNID
  python EXPORT/tools/droplet_tournament.py --env-file ENV destroy --id DROPLET_ID

`destroy --name` reads the default state directory only; a run started with
another --state-root is cleaned up with `destroy --id`.

`rehearse` runs the same droplet-side job script and the same acceptance on
this machine in a scratch directory, with no network call. It tests the script
and the file lists; it is not a way to produce registered records.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import secrets
import shlex
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import endturn_accept as ACCEPT  # noqa: E402

TOOL_FILES = ("endturn_probe.py", "endturn_shim.c", "build_shim.sh")
LOCAL_FILES = ("endturn_droplet.py", "endturn_accept.py")
LIFECYCLE = "tools/droplet_tournament.py"
RESULT_FILES = ACCEPT.RESULT_FILES
FAILURE_LOGS = ("EXIT", "STAGE", "job.log", "probe-build.log", "build.log", "setup.log")
TEARDOWN_RESERVE = 300        # seconds of --max-hours kept back for the failure logs and the delete
FAILURE_FETCH_SECONDS = 45    # all the failure logs together
MIN_HOURS = 0.25
DT = None                     # the harness's droplet_tournament, set by load_dt


def sha256_file(path):
    return ACCEPT.sha256_file(path)


def load_dt(export, want_sha):
    """Import tools/droplet_tournament.py from the harness export, after holding
    the file to the hash the plan records."""
    global DT
    path = os.path.join(os.path.abspath(export), LIFECYCLE)
    if not os.path.isfile(path):
        raise SystemExit(f"{path} is missing: the export must include it")
    if sha256_file(path) != want_sha:
        raise SystemExit(f"{path} is not the lifecycle file the plan names; nothing was imported")
    tools = os.path.dirname(path)
    if tools not in sys.path:
        sys.path.insert(0, tools)
    import droplet_tournament
    if os.path.abspath(droplet_tournament.__file__) != path:
        raise SystemExit("droplet_tournament was imported from somewhere else")
    DT = droplet_tournament
    return DT


def positive(text):
    value = float(text)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError(f"must be a finite number above zero, got {text!r}")
    return value


def run_name(name, shard, run_id):
    return DT.validate_name(f"{name}-{shard}-{run_id}")


def remote_paths():
    root = DT.REMOTE_ROOT
    return {"probe": root + "/probe", "lib": root + "/probe/lib/libbbprobe.so",
            "plan": DT.REMOTE_RUN + "/plan.json"}


def probe_build_script():
    """Build the probe's library after the harness shim (so it is newer than the sources)."""
    r = remote_paths()
    return f"""#!/bin/bash
set -euo pipefail
bash {r['probe']}/build_shim.sh {DT.REMOTE_SRC} {r['probe']}/lib
test -f {r['lib']}
sha256sum {r['lib']}
echo PROBE_BUILD_OK
"""


def job_script(plan_sha, checkpoints, processes):
    """The detached job: the probe for each checkpoint of the shard, checksums, then
    an atomic EXIT file. The stage is called `tournament` and the log
    tournament.log so that the droplet tool's poll reads this job as its own."""
    r = remote_paths()
    run, out, py = DT.REMOTE_RUN, DT.REMOTE_OUT, DT.REMOTE_PY
    lines = [f"""#!/bin/bash
set -uo pipefail
cd {DT.REMOTE_SRC}
export OMP_NUM_THREADS=1
finish() {{ echo "$1" > {run}/EXIT.tmp && mv {run}/EXIT.tmp {run}/EXIT; exit "$1"; }}
echo tournament > {run}/STAGE
date -u +%s > {run}/STARTED
mkdir -p {out}
: > {run}/tournament.log"""]
    names = []
    for name, remote_blob in checkpoints:
        argv = ["run", "--harness", DT.REMOTE_SRC, "--lib", r["lib"], "--plan", r["plan"],
                "--expect-sha256", plan_sha, "--checkpoint-name", name, "--checkpoint", remote_blob,
                "--out-dir", f"{out}/{name}", "--processes", str(int(processes))]
        cmd = " ".join(shlex.quote(a) for a in argv)
        lines.append(f"{py} {r['probe']}/endturn_probe.py {cmd} >> {run}/tournament.log 2>&1 "
                     f"|| finish $?")
        lines.append(f"test -f {out}/{name}/COMPLETE.json || finish 3")
        names += [f"{name}/{f}" for f in RESULT_FILES]
    lines.append(f"cp {run}/machine.json {run}/plan.json {out}/")
    lines.append(f"(cd {out} && sha256sum machine.json plan.json {' '.join(names)} > SHA256SUMS) "
                 f"|| finish 4")
    lines.append(f"echo done > {run}/STAGE")
    lines.append("finish 0")
    return "\n".join(lines) + "\n"


def make_archive(repo, commit, path):
    """The pinned commit's synced paths, straight from the object store: a
    read-only use of the repository, which may be any worktree that has the commit."""
    with open(path, "wb") as f:
        subprocess.run(["git", "-C", repo, "archive", "--format=tar.gz", commit, "--",
                        *DT.SYNC_PATHS], check=True, stdout=f)


class Clock:
    """The one time limit of a shard. `soft` leaves the reserve for teardown."""

    def __init__(self, max_hours):
        self.start = time.time()
        self.hard = self.start + max_hours * 3600.0
        self.soft = self.hard - TEARDOWN_RESERVE

    def left(self):
        return self.soft - time.time()

    def cap(self, default, what):
        """A timeout for the phase `what`: its usual one, or what is left."""
        left = self.left()
        if left <= 1:
            raise DT.RunnerError(f"--max-hours is reached before {what}; giving up so the "
                                 "droplet stops billing")
        return max(1, int(min(default, left)))


def prepare(args, need_repo=True):
    """Every check that needs no network. Returns what a run needs."""
    try:
        plan, plan_sha = ACCEPT.load_plan(args.plan, args.expect_sha256)
    except ValueError as exc:
        raise DT.RunnerError(str(exc))
    known = {s["name"]: s["checkpoints"] for s in plan["shards"]}
    shards = args.shard or list(known)
    name = DT.validate_name(args.name)
    for shard in shards:
        if shard not in known:
            raise DT.RunnerError(f"the plan has no shard {shard!r} (it has {sorted(known)})")
        run_name(name, shard, "0" * 6)                      # the name fits with a run id
    if len(set(shards)) != len(shards):
        raise DT.RunnerError("a shard is named twice")
    export = os.path.abspath(args.harness_export)
    with open(os.path.join(export, "SOURCE_COMMIT")) as f:
        commit = f.read().strip()
    if commit != plan["harness_commit"]:
        raise DT.RunnerError(f"the export is at {commit}, the plan pins {plan['harness_commit']}")
    if need_repo:
        got = subprocess.run(["git", "-C", args.harness_repo, "rev-parse", "--verify",
                              commit + "^{commit}"], capture_output=True, text=True)
        if got.returncode != 0 or got.stdout.strip() != commit:
            raise DT.RunnerError(f"{args.harness_repo} does not hold commit {commit}")
    for files, key in ((TOOL_FILES, "tool_sha256"), (LOCAL_FILES, "local_sha256")):
        for fname in files:
            if sha256_file(os.path.join(HERE, fname)) != plan[key].get(fname):
                raise DT.RunnerError(f"{fname} beside this script is not the file the plan names "
                                     f"({key}); rerun make_plan.py before the plan is committed")
    if sha256_file(os.path.join(export, LIFECYCLE)) != plan["lifecycle_sha256"][LIFECYCLE]:
        raise DT.RunnerError(f"the export's {LIFECYCLE} is not the file the plan names")
    manifest = os.path.join(export, "puffer", "config", "rewards", plan["reward_manifest"] + ".json")
    if sha256_file(manifest) != plan["reward_manifest_file_sha256"]:
        raise DT.RunnerError(f"{manifest} is not the plan's reward manifest file")
    checkpoints = {}
    for shard in shards:
        for ck in known[shard]:
            path = os.path.join(os.path.expanduser(args.checkpoint_store),
                                plan["checkpoints"][ck]["blob"])
            for p in (path, path + ".lineage.json"):
                if not os.path.isfile(p):
                    raise DT.RunnerError(f"checkpoint: missing {p}")
            if sha256_file(path) != plan["checkpoints"][ck]["sha256"]:
                raise DT.RunnerError(f"{path} is not the plan's {ck}")
            checkpoints[ck] = path
    out_root = os.path.abspath(os.path.join(args.out_root, name))
    for shard in shards:
        for suffix in ("", ".failed", ".partial"):
            if os.path.exists(os.path.join(out_root, shard) + suffix):
                raise DT.RunnerError(f"{os.path.join(out_root, shard) + suffix} already exists; "
                                     "pick a new --name")
    return {"name": name, "plan": plan, "plan_sha": plan_sha, "shards": shards, "known": known,
            "commit": commit, "export": export, "checkpoints": checkpoints, "out_root": out_root}


def guard_refusal(n_shards, max_hours, price, max_total_usd):
    for what, value in (("--max-hours", max_hours), ("the hourly price", price),
                        ("--max-total-usd", max_total_usd)):
        if not (isinstance(value, (int, float)) and math.isfinite(value) and value > 0):
            return f"{what} must be a finite number above zero, got {value!r}. Nothing was created."
    if max_hours < MIN_HOURS:
        return (f"--max-hours {max_hours} leaves no room beside the {TEARDOWN_RESERVE} s teardown "
                f"reserve; the least is {MIN_HOURS}. Nothing was created.")
    total = n_shards * max_hours * price
    if not total <= max_total_usd + 1e-9:
        return (f"{n_shards} shard(s) x {max_hours} h x ${price:.5f}/h = ${total:.2f}, above "
                f"--max-total-usd {max_total_usd}. Nothing was created.")
    return None


def cleanup_text(args, ready, run_id):
    """The commands that end this run's billing without this process, for this
    invocation's token file and state directory."""
    env_file = os.path.abspath(os.path.expanduser(args.env_file))
    tool = f"python {ready['export']}/{LIFECYCLE} --env-file {shlex.quote(env_file)}"
    state_root = os.path.abspath(os.path.expanduser(args.state_root))
    default_root = state_root == os.path.abspath(os.path.expanduser(DT.STATE_ROOT))
    lines = ["If the runner is gone, or its teardown failed, a droplet of this run may still be "
             "billing. It bills until one of these succeeds (they need only the export and the "
             "token file):",
             f"  {tool} status",
             "then, for each droplet of this run that is still listed:"]
    for shard in ready["shards"]:
        unique = run_name(ready["name"], shard, run_id)
        if default_root:
            lines.append(f"  {tool} destroy --name {unique}      # droplet "
                         f"{DT.droplet_name(unique)}; reads {state_root}/{unique}")
        else:
            lines.append(f"  {tool} destroy --id $(cat {shlex.quote(state_root)}/{unique}/droplet-id)"
                         f"      # droplet {DT.droplet_name(unique)}")
    if default_root:
        lines.append(f"  {tool} destroy --id <DROPLET_ID>      # needs no local state; ids are in "
                     "the status listing")
    else:
        lines.append(f"  (`destroy --name` reads {os.path.expanduser(DT.STATE_ROOT)} only and cannot "
                     f"be used: this run's state is in {state_root}. If a droplet-id file is "
                     "missing, take the id from the status listing. An ssh key of the run's name "
                     "that stays listed costs nothing; remove it in the console.)")
    lines.append("A droplet is this run's only if its name ends in this run id: " + run_id)
    return "\n".join(lines)


def shard_estimate(plan, shard_checkpoints, price):
    est = plan["estimate"]
    seconds = est["setup_seconds"] + len(shard_checkpoints) * plan["settings"]["games"] * \
        est["droplet_seconds_per_game"]
    return seconds, None if price is None else DT.cost(seconds, price)


def describe(args, ready, run_id, price=None):
    plan = ready["plan"]
    lines = [f"plan {plan['name']} ({ready['plan_sha']})",
             f"harness commit {ready['commit']} from {args.harness_repo}; lifecycle code from "
             f"{ready['export']}/{LIFECYCLE}",
             f"size {args.size} in {args.region}, tag {DT.TAG}, image {DT.IMAGE}",
             "sync: " + ", ".join(DT.SYNC_PATHS) + "; probe files: " + ", ".join(TOOL_FILES),
             f"settings: {json.dumps(plan['settings'])}",
             f"run id {run_id}: the suffix of every name this run creates"]
    total_seconds = 0.0
    for shard in ready["shards"]:
        cks = ready["known"][shard]
        seconds, usd = shard_estimate(plan, cks, price)
        total_seconds += seconds
        unique = run_name(ready["name"], shard, run_id)
        lines.append(f"shard {shard}: droplet {DT.droplet_name(unique)}, checkpoints "
                     f"{', '.join(cks)}, {len(cks) * plan['settings']['games']} games, results in "
                     f"{os.path.join(ready['out_root'], shard)}")
        lines.append(f"  estimate: {seconds / 3600:.2f} h"
                     + (f", about ${usd:.2f}" if usd is not None else "")
                     + f" (the plan's {plan['estimate']['droplet_seconds_per_game']} s a game, not "
                       "measured on a droplet)")
        remote = [(ck, DT.remote_checkpoint_path(ck, ready["checkpoints"][ck])) for ck in cks]
        for line in job_script(ready["plan_sha"], remote, args.processes or 8).splitlines():
            if "endturn_probe.py" in line:
                lines.append("  " + line)
    hours = f"{len(ready['shards'])} shard(s) x {args.max_hours} h"
    if price is None:
        lines.append(f"spend guard: {hours} x the hourly price (read at run time) must not exceed "
                     f"${args.max_total_usd}")
    else:
        ceiling = len(ready["shards"]) * args.max_hours * price
        lines.append(f"spend guard: {hours} x ${price:.5f}/h = ${ceiling:.2f} of "
                     f"${args.max_total_usd} allowed; estimated spend "
                     f"${total_seconds / 3600 * price:.2f}")
        lines.append(f"nominal budget, when every call returns: ${args.max_hours * price:.2f} a "
                     f"shard plus the teardown (normally under five minutes, about $0.01). This is "
                     f"not a ceiling: one teardown call can retry for about 70 minutes when the API "
                     f"is slow (about ${70 / 60 * price:.2f} a droplet for each such call), and a "
                     "dead runner, a lost create or a failed delete leaves a droplet billing until "
                     "an operator destroys it.")
    lines.append(cleanup_text(args, ready, run_id))
    return "\n".join(lines)


def account_refusal(api, unique):
    """Why nothing may be created under this name, or None. Read-only calls."""
    wanted = DT.droplet_name(unique)
    droplets = api.get("/droplets?per_page=200")["droplets"]
    if any(d.get("name") == wanted for d in droplets):
        return f"the account already has a droplet named {wanted}"
    keys = api.get("/account/keys?per_page=200")["ssh_keys"]
    if any(k.get("name") == wanted for k in keys):
        return f"the account already has an ssh key named {wanted}"
    return None


def reconcile(api, unique):
    """After teardown: nothing named for this run may be left. An ssh key of this
    run's unique name whose id never reached local state (a registration whose
    answer was lost) is deleted here; it can only be this run's, because the
    name carries the run id and no such key existed before the run. A droplet
    of this name that is still listed is reported, never guessed at."""
    wanted = DT.droplet_name(unique)
    for key in api.get("/account/keys?per_page=200")["ssh_keys"]:
        if key.get("name") == wanted:
            status, _ = api.call("DELETE", f"/account/keys/{key['id']}")
            DT.log(f"removed this run's leftover ssh key {key['id']} ({wanted}): HTTP {status}")
    left = [d for d in api.get(f"/droplets?tag_name={DT.TAG}&per_page=200")["droplets"]
            if d.get("name") == wanted]
    if left:
        raise DT.RunnerError(f"droplet(s) named {wanted} STILL EXIST: {[d['id'] for d in left]}; "
                             f"destroy with `{LIFECYCLE} destroy --id ID`")


def fetch_failure_logs(remote, directory):
    """Small logs only, 45 seconds in all, never raising: this is on the way to teardown."""
    deadline = time.time() + FAILURE_FETCH_SECONDS
    try:
        os.makedirs(directory, exist_ok=True)
        for fname in FAILURE_LOGS:
            left = deadline - time.time()
            if left < 2:
                break
            try:
                remote.get(f"{DT.REMOTE_RUN}/{fname}", os.path.join(directory, fname),
                           check=False, timeout=max(2, int(min(10, left))))
            except Exception:
                pass
        left = deadline - time.time()
        if left >= 2:
            try:
                tail = remote.run(f"tail -n 40 {DT.REMOTE_RUN}/tournament.log; "
                                  f"cat {DT.REMOTE_OUT}/*/FAILED.json 2>/dev/null", check=False,
                                  timeout=max(2, int(min(10, left))))
                with open(os.path.join(directory, "tournament.tail.log"), "w") as f:
                    f.write(tail.stdout)
            except Exception:
                pass
        return True
    except Exception:
        return False


def run_shard(args, ready, shard, api, size, run_id):
    """One droplet, one shard, teardown on every exit path. Returns the result."""
    plan, plan_sha, commit = ready["plan"], ready["plan_sha"], ready["commit"]
    unique = run_name(ready["name"], shard, run_id)
    cks = ready["known"][shard]
    out_dir = os.path.join(ready["out_root"], shard)
    tasks = len(cks) * plan["settings"]["games"]
    price = float(size["price_hourly"])
    processes = args.processes or int(size["vcpus"])
    r = remote_paths()
    state = DT.State(unique, root=args.state_root)
    if os.path.exists(state.dir):
        raise DT.RunnerError(f"local state {state.dir} already exists; a run id is used once. "
                             "Nothing was created.")
    refusal = account_refusal(api, unique)
    if refusal:
        raise DT.RunnerError(f"{refusal}. Nothing was created.")
    lock = state.lock()                                     # held until the process exits
    state.write("run-id", run_id)
    state.write("price-hourly", price)
    DT.log(f"shard {shard} as {unique}: {tasks} games on {processes} processes, "
           f"{size['vcpus']} vCPU at ${price:.5f}/h; --max-hours {args.max_hours} caps it at "
           f"about ${args.max_hours * price:.2f}")

    def on_signal(signum, _frame):
        raise DT.Interrupted(f"signal {signum}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)

    clock = Clock(args.max_hours)
    result, remote, failed = None, None, True
    try:
        clock.cap(60, "the ssh key")
        fingerprint = DT.create_key(api, state, unique)
        clock.cap(60, "the create")
        droplet_id = DT.create_droplet(api, state, unique, args.region, args.size, fingerprint)
        ip = DT.wait_active(api, droplet_id, timeout=clock.cap(600, "the droplet's boot"))
        state.write("ip", ip)
        remote = DT.Remote(state.dir, ip)
        DT.wait_ssh(remote, timeout=clock.cap(300, "ssh"))
        DT.log(f"droplet {droplet_id} up at {ip} after {time.time() - clock.start:.0f} s; installing")
        remote.script(DT.setup_script(args.torch, args.numpy), "setup.log",
                      timeout=clock.cap(1500, "the install"))
        archive = state.path("src.tar.gz")
        make_archive(args.harness_repo, commit, archive)
        remote.put(archive, f"{DT.REMOTE_ROOT}/src.tar.gz", timeout=clock.cap(600, "the source upload"))
        remote.run(f"tar -xzf {DT.REMOTE_ROOT}/src.tar.gz -C {DT.REMOTE_SRC} && "
                   f"echo {commit} > {DT.REMOTE_SRC}/SOURCE_COMMIT", timeout=clock.cap(300, "the unpack"))
        remote.run(f"mkdir -p {r['probe']} {DT.REMOTE_OUT}", timeout=clock.cap(60, "mkdir"))
        for fname in TOOL_FILES:
            remote.put(os.path.join(HERE, fname), f"{r['probe']}/{fname}",
                       timeout=clock.cap(120, "the tool upload"))
        remote_blobs = []
        for ck in cks:
            target = DT.remote_checkpoint_path(ck, ready["checkpoints"][ck])
            remote.run(f"mkdir -p {shlex.quote(os.path.dirname(target))}",
                       timeout=clock.cap(60, "mkdir"))
            remote.put(ready["checkpoints"][ck], target, timeout=clock.cap(600, "the checkpoint upload"))
            remote.put(ready["checkpoints"][ck] + ".lineage.json", target + ".lineage.json",
                       timeout=clock.cap(120, "the sidecar upload"))
            remote_blobs.append((ck, target))
        remote.put(os.path.abspath(args.plan), r["plan"], timeout=clock.cap(120, "the plan upload"))
        built = remote.script(DT.build_script(commit), "build.log",
                              timeout=clock.cap(900, "the shim build"))
        machine = json.loads([l for l in built.stdout.splitlines() if l.startswith("{")][-1])
        remote.script(probe_build_script(), "probe-build.log",
                      timeout=clock.cap(600, "the probe library build"))
        DT.log(f"shim and probe library built: {machine['cpu_model']}, {machine['nproc']} cores")
        remote.run(f"cat > {DT.REMOTE_RUN}/job.sh",
                   stdin_text=job_script(plan_sha, remote_blobs, processes),
                   timeout=clock.cap(60, "the job upload"))
        remote.run(f"nohup setsid bash {DT.REMOTE_RUN}/job.sh > {DT.REMOTE_RUN}/job.log 2>&1 "
                   f"< /dev/null & echo started", timeout=clock.cap(60, "the launch"))
        t_launch = time.time()
        DT.log(f"shard {shard} launched under nohup ({t_launch - clock.start:.0f} s after create)")
        rc = DT.poll(remote, tasks, clock.soft, args.stale_seconds)
        if rc != 0:
            raise DT.RunnerError(f"droplet job exited {rc}; its logs are copied to {out_dir}.failed")
        partial = out_dir + ".partial"
        os.makedirs(partial, exist_ok=True)
        for fname in ("SHA256SUMS", "machine.json", "plan.json"):
            remote.get(f"{DT.REMOTE_OUT}/{fname}", os.path.join(partial, fname),
                       timeout=clock.cap(120, "the fetch"))
        for ck in cks:
            os.makedirs(os.path.join(partial, ck), exist_ok=True)
            for fname in RESULT_FILES:
                remote.get(f"{DT.REMOTE_OUT}/{ck}/{fname}", os.path.join(partial, ck, fname),
                           timeout=clock.cap(1200, "the fetch"))
        problems, completes = ACCEPT.shard_problems(partial, shard, plan, plan_sha)
        if problems:
            raise DT.RunnerError("the shard is NOT ACCEPTED:\n  " + "\n  ".join(problems))
        DT.log(f"shard {shard} ACCEPTED: file hashes, provenance, integrity and game coverage "
               f"hold for {', '.join(completes)}")
        result = {"schema": "endturn-droplet-run-v2", "name": unique, "run_id": run_id,
                  "shard": shard, "droplet_name": DT.droplet_name(unique),
                  "plan_sha256": plan_sha, "droplet_id": droplet_id, "size": args.size,
                  "region": args.region, "price_hourly": price, "vcpus": size["vcpus"],
                  "processes": processes, "commit": commit, "machine": machine,
                  "checkpoints": cks, "games": tasks, "accepted": True,
                  "seconds": {"create_to_launch": round(t_launch - clock.start, 1),
                              "launch_to_done": round(time.time() - t_launch, 1)}}
        os.rename(partial, out_dir)
        failed = False
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)               # teardown must finish
        if failed and remote is not None and not args.keep:
            if fetch_failure_logs(remote, out_dir + ".failed"):
                DT.log(f"the failure's logs (what could be fetched in {FAILURE_FETCH_SECONDS} s) "
                       f"are in {out_dir}.failed; records of a failed shard are not fetched")
        if args.keep:
            DT.log(f"--keep: droplet {state.read('droplet-id')} at {state.read('ip')} is STILL "
                   f"BILLING. Then: {LIFECYCLE} destroy --name {unique}")
        else:
            try:
                DT.teardown(api, state, unique)
                reconcile(api, unique)
            except BaseException:
                try:
                    print(f"TEARDOWN FAILED: droplet {state.read('droplet-id')} may STILL BE "
                          f"BILLING. Run: python {ready['export']}/{LIFECYCLE} --env-file "
                          f"{shlex.quote(os.path.abspath(os.path.expanduser(args.env_file)))} "
                          f"destroy --id {state.read('droplet-id')}"
                          f"  (see CLEANUP.txt in {ready['out_root']})",
                          file=sys.stderr, flush=True)
                except Exception:
                    pass
                raise
            if result is not None:
                result["cost"] = float(state.read("cost") or 0.0)
                result["lifetime_seconds"] = round(time.time() - clock.start, 1)
        if result is not None:
            with open(os.path.join(out_dir, "droplet_run.json"), "w") as f:
                json.dump(result, f, indent=1)
    del lock
    DT.log(f"shard {shard}: results in {out_dir}")
    return result


def child_argv(args, shard, run_id, n_shards):
    argv = [sys.executable, os.path.abspath(__file__), "--env-file", args.env_file, "run",
            "--name", args.name, "--plan", args.plan, "--expect-sha256", args.expect_sha256,
            "--harness-export", args.harness_export, "--harness-repo", args.harness_repo,
            "--checkpoint-store", args.checkpoint_store, "--shard", shard,
            "--size", args.size, "--region", args.region, "--max-hourly", str(args.max_hourly),
            "--max-hours", str(args.max_hours), "--max-total-usd", str(args.max_total_usd),
            "--stale-seconds", str(args.stale_seconds), "--out-root", args.out_root,
            "--state-root", args.state_root, "--torch", args.torch, "--numpy", args.numpy,
            "--run-id", run_id, "--child-of", str(n_shards)]
    if args.processes:
        argv += ["--processes", str(args.processes)]
    if args.keep:
        argv.append("--keep")
    return argv


def run_children(args, ready, run_id):
    """One child process per shard. Returns {shard: exit code, or None for a
    shard that was never started}.

    The handler is installed before the first child exists. A signal marks the
    run cancelled and is passed to every child started so far; no further
    shard is started after it; a child whose start the signal interrupted is
    signalled as soon as it is recorded; and every started child is waited
    for, so each runs its own teardown."""
    os.makedirs(ready["out_root"], exist_ok=True)
    children, cancelled = {}, []

    def forward(signum, _frame):
        cancelled.append(signum)
        for child in list(children.values()):
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, forward)
    try:
        for shard in ready["shards"]:
            if cancelled:
                break
            log_path = os.path.join(ready["out_root"], f"{shard}.runner.log")
            with open(log_path, "w") as sink:
                child = subprocess.Popen(
                    child_argv(args, shard, run_id, len(ready["shards"])), stdout=sink,
                    stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            children[shard] = child
            if cancelled and child.poll() is None:           # the signal came while it was starting
                child.send_signal(signal.SIGINT)
            DT.log(f"shard {shard}: runner pid {child.pid}, log {log_path}")
    except BaseException:
        forward(signal.SIGINT, None)                         # each started child tears down
        for child in children.values():
            child.wait()
        raise
    codes = {shard: (children[shard].wait() if shard in children else None)
             for shard in ready["shards"]}
    for shard, code in codes.items():
        DT.log(f"shard {shard}: " + ("NOT STARTED (the run was cancelled)" if code is None
                                     else f"runner exited {code}"))
    if cancelled:
        DT.log(f"the run was cancelled by signal {cancelled[0]}; started shards have torn down")
    return codes


def cmd_run(args):
    ready = prepare(args)
    if args.dry_run:
        print("DRY RUN: nothing is created, no network call is made")
        print("xxxxxx below stands for the run id, six random hex digits drawn at launch")
        print(describe(args, ready, "xxxxxx", args.assume_hourly))
        if args.assume_hourly is not None:
            refusal = guard_refusal(len(ready["shards"]), args.max_hours, args.assume_hourly,
                                    args.max_total_usd)
            if refusal:
                raise DT.RunnerError(refusal)
        return 0
    api = DT.Api(DT.read_token(env_file=args.env_file))
    size = DT.pick_size(api.get("/sizes?per_page=200")["sizes"], args.size, args.region,
                        args.max_hourly)
    price = float(size["price_hourly"])
    n_shards = args.child_of or len(ready["shards"])
    refusal = guard_refusal(n_shards, args.max_hours, price, args.max_total_usd)
    if refusal:
        raise DT.RunnerError(refusal)
    if args.child_of:
        if not args.run_id or len(ready["shards"]) != 1:
            raise DT.RunnerError("a child runs one shard under its parent's run id")
        return 0 if run_shard(args, ready, ready["shards"][0], api, size, args.run_id) else 1
    run_id = secrets.token_hex(3)
    print(describe(args, ready, run_id, price), flush=True)
    os.makedirs(ready["out_root"], exist_ok=True)
    with open(os.path.join(ready["out_root"], "CLEANUP.txt"), "a") as f:
        f.write(f"run id {run_id}, started {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                + cleanup_text(args, ready, run_id) + "\n\n")
    DT.log("tagged droplets before:")
    DT.print_status(api)
    limit = int(api.get("/account")["account"]["droplet_limit"])
    existing = len(api.get("/droplets?per_page=200")["droplets"])
    refusal = DT.limit_refusal(existing + len(ready["shards"]) - 1, limit)
    if refusal:
        raise DT.RunnerError(f"{refusal} (this run needs {len(ready['shards'])} more)")
    try:
        if len(ready["shards"]) == 1:
            ok = run_shard(args, ready, ready["shards"][0], api, size, run_id) is not None
        else:
            ok = all(code == 0 for code in run_children(args, ready, run_id).values())
    finally:
        DT.log("tagged droplets after:")
        try:
            DT.print_status(api)
        except DT.RunnerError as exc:
            DT.log(f"the listing could not be read ({exc}); run `{LIFECYCLE} status` by hand")
    return 0 if ok else 1


def cmd_rehearse(args):
    """The droplet-side job script and the acceptance, on this machine, no network.
    The library is built once and every requested shard runs against it, as all
    droplets of one image build the same library."""
    base = os.path.abspath(args.dir)
    if os.path.exists(base):
        raise SystemExit(f"{base} exists; give a fresh --dir")
    DT.REMOTE_ROOT = base
    DT.REMOTE_SRC = os.path.abspath(args.harness_export)
    DT.REMOTE_PY = os.path.abspath(args.python)
    DT.REMOTE_RUN = base + "/run"
    args.name, args.out_root = "rehearsal", base + "/fetched"
    ready = prepare(args, need_repo=False)
    probe = remote_paths()["probe"]
    os.makedirs(probe)
    for fname in TOOL_FILES:
        with open(os.path.join(HERE, fname), "rb") as src, open(f"{probe}/{fname}", "wb") as dst:
            dst.write(src.read())
    subprocess.run(["bash", f"{probe}/build_shim.sh", DT.REMOTE_SRC, f"{probe}/lib"], check=True)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    bad = False
    for shard in ready["shards"]:
        DT.REMOTE_RUN = f"{base}/{shard}/run"
        DT.REMOTE_OUT = DT.REMOTE_RUN + "/main"
        r = remote_paths()
        lib = r["lib"].replace(".so", ".dylib") if sys.platform == "darwin" else r["lib"]
        os.makedirs(DT.REMOTE_RUN)
        with open(args.plan, "rb") as src, open(r["plan"], "wb") as dst:
            dst.write(src.read())
        with open(DT.REMOTE_RUN + "/machine.json", "w") as f:
            json.dump({"source_commit": ready["commit"], "host": "rehearsal"}, f)
        blobs = [(ck, ready["checkpoints"][ck]) for ck in ready["known"][shard]]
        script = job_script(ready["plan_sha"], blobs, args.processes or 1).replace(r["lib"], lib)
        with open(DT.REMOTE_RUN + "/job.sh", "w") as f:
            f.write(script)
        code = subprocess.run(["bash", DT.REMOTE_RUN + "/job.sh"], env=env).returncode
        with open(DT.REMOTE_RUN + "/EXIT") as f:
            print(f"shard {shard}: job EXIT {f.read().strip()}, bash returned {code}")
        problems, completes = ACCEPT.shard_problems(DT.REMOTE_OUT, shard, ready["plan"],
                                                    ready["plan_sha"])
        print(f"shard {shard}: " + (f"ACCEPTED ({', '.join(completes)}) in {DT.REMOTE_OUT}"
                                    if not problems else "NOT ACCEPTED:\n  " + "\n  ".join(problems)))
        bad = bad or bool(problems) or bool(code)
    return 1 if bad else 0


def build_parser(defaults):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--env-file", default=defaults["env_file"],
                    help="dotenv file holding the DigitalOcean token (the environment wins)")
    sub = ap.add_subparsers(dest="command", required=True)
    for name, func in (("run", cmd_run), ("rehearse", cmd_rehearse)):
        sp = sub.add_parser(name)
        sp.add_argument("--plan", required=True)
        sp.add_argument("--expect-sha256", required=True, help="the plan file's sha256")
        sp.add_argument("--harness-export", required=True,
                        help=f"export of the pinned harness commit, with {LIFECYCLE}")
        sp.add_argument("--checkpoint-store", default=os.path.expanduser(
            "~/Code/bb-play-harness/.play-artifacts/checkpoints"))
        sp.add_argument("--shard", action="append", default=None,
                        help="repeatable; default: every shard of the plan")
        sp.add_argument("--processes", type=int, default=None, help="default: the size's vCPUs")
        if name == "run":
            sp.add_argument("--name", required=True,
                            help="run name; a shard's results land in OUT_ROOT/NAME/SHARD")
            sp.add_argument("--harness-repo", default=os.path.expanduser("~/Code/bb-play-harness"),
                            help="any worktree whose object store has the pinned commit "
                                 "(only `git archive` and `git rev-parse` are run in it)")
            sp.add_argument("--size", default=defaults["size"])
            sp.add_argument("--region", default=defaults["region"])
            sp.add_argument("--max-hourly", type=positive, default=defaults["max_hourly"])
            sp.add_argument("--max-hours", type=positive, required=True,
                            help="per shard, the droplet's whole life: nothing is started that "
                                 "would pass it, and the droplet is destroyed when it is reached")
            sp.add_argument("--max-total-usd", type=positive, required=True,
                            help="shards x max-hours x hourly price must not exceed this")
            sp.add_argument("--stale-seconds", type=positive, default=1800)
            sp.add_argument("--out-root", default=os.path.normpath(os.path.join(
                HERE, "..", "..", "runs", "endturn-probe-2026-10-08")),
                help="default: the repository's git-ignored runs/ directory")
            sp.add_argument("--state-root", default=defaults["state_root"])
            sp.add_argument("--torch", default=defaults["torch"])
            sp.add_argument("--numpy", default=defaults["numpy"])
            sp.add_argument("--keep", action="store_true",
                            help="debugging: leave the droplet running (it keeps billing)")
            sp.add_argument("--dry-run", action="store_true",
                            help="print what would be done; create nothing, call nothing")
            sp.add_argument("--assume-hourly", type=positive, default=None,
                            help="with --dry-run: apply the spend guard at this hourly price")
            sp.add_argument("--run-id", default=None, help=argparse.SUPPRESS)
            sp.add_argument("--child-of", type=int, default=None, help=argparse.SUPPRESS)
        else:
            sp.add_argument("--dir", required=True, help="a fresh scratch directory")
            sp.add_argument("--python", required=True, help="a python with torch and numpy")
        sp.set_defaults(func=func)
    return ap


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--harness-export")
    pre.add_argument("--plan")
    known, _ = pre.parse_known_args(argv)
    if not known.harness_export or not known.plan:
        raise SystemExit("--harness-export and --plan are required (the export holds the "
                         "lifecycle code, the plan names it by hash)")
    with open(known.plan) as f:
        lifecycle = (json.load(f).get("lifecycle_sha256") or {}).get(LIFECYCLE)
    load_dt(known.harness_export, lifecycle)
    defaults = {"env_file": DT.DEFAULT_ENV_FILE, "size": DT.DEFAULT_SIZE,
                "region": DT.DEFAULT_REGION, "max_hourly": DT.MAX_HOURLY_DEFAULT,
                "state_root": DT.STATE_ROOT, "torch": DT.TORCH_VERSION, "numpy": DT.NUMPY_VERSION}
    args = build_parser(defaults).parse_args(argv)
    try:
        return args.func(args)
    except DT.RunnerError as exc:
        print(f"ERROR: {exc}", file=sys.stderr, flush=True)
        return 1
    except DT.Interrupted as exc:
        print(f"INTERRUPTED: {exc} (teardown has run)", file=sys.stderr, flush=True)
        return 130


if __name__ == "__main__":
    sys.exit(main())
