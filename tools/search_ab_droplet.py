#!/usr/bin/env python3
"""Play shards of a search A/B plan (tools/search_ab.py) on throwaway droplets.

One droplet plays one shard: all of the plan's arms for that shard's seeds. The
droplet lifecycle is tools/droplet_tournament.py's, imported, not copied: its
tag and disposable ssh key, its setup and build scripts, its polling, its state
directory and its teardown, which runs on every exit path unless --keep. A
droplet this tool made is listed and destroyed by `tools/droplet_tournament.py
status` and `destroy --name NAME-SHARD`.

  tools/search_ab_droplet.py run --name ab1 --plan PLAN --expect-sha256 H \\
      --checkpoint BLOB --shard shard-a --shard shard-b \\
      --max-hours 2 --max-total-usd 3 [--dry-run]

What `run` does, per shard: local checks (the plan's hash, the checkpoint's and
the manifest's, the commit and the code against the plan), price check and the
spend guard, one tagged droplet, CPU-only torch, `git archive` of the plan's
commit, the checkpoint and the plan, the shim built on the droplet, `search_ab
play` under nohup, polling, copy back with a SHA256SUMS, verification against
the plan, teardown, cost. With several shards each runs in its own child
process, so each has its own teardown.

The spend guard: (number of shards) x --max-hours x the size's hourly price
must not exceed --max-total-usd, or nothing is created. --max-hours also ends a
run: the droplet's records so far are fetched (NAME/SHARD.failed/games.jsonl)
and the droplet is destroyed. `--resume-from` that directory relaunches the
shard for its unfinished games only.

Every tagged droplet is listed before anything is created and again at the end.
A full account is a blocker: nothing is ever deleted to make room.
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
for path in (ROOT, HERE):
    if path not in sys.path:
        sys.path.insert(0, path)

import droplet_tournament as DT  # noqa: E402
import search_ab as AB  # noqa: E402

SYNC_PATHS = DT.SYNC_PATHS + ("tools/search_ab.py", "tools/search_probe_diag.py")
REMOTE_PLAN = DT.REMOTE_RUN + "/plan.json"
REMOTE_MANIFEST = DT.REMOTE_RUN + "/reward_manifest.json"
RESULT_FILES = ("games.jsonl", "run.json", "COMPLETE.json")
PROVENANCE_FILES = ("machine.json", "plan.json")
PARTIAL_FILES = ("games.jsonl", "run.json")
LOG_FILES = ("job.log", "tournament.log", "setup.log", "build.log", "EXIT", "STAGE")


def run_name(name, shard):
    """The droplet-tool run name of one shard: state directory and droplet name."""
    return DT.validate_name(f"{name}-{shard}")


def play_argv(plan_sha256, shard, checkpoint, processes):
    """argv after `python tools/search_ab.py`, with droplet-side paths."""
    return ["play", "--plan", REMOTE_PLAN, "--expect-sha256", plan_sha256, "--shard", shard,
            "--checkpoint", checkpoint, "--manifest", REMOTE_MANIFEST,
            "--processes", str(int(processes)), "--out-dir", DT.REMOTE_OUT]


def job_script(argv):
    """The detached job: the shard's games, checksums, then an atomic EXIT file. The
    stage is called `tournament` and the log tournament.log so that the droplet
    tool's poll reads this job as it reads its own."""
    cmd = " ".join(shlex.quote(a) for a in argv)
    names = " ".join(RESULT_FILES + PROVENANCE_FILES)
    run, out, py = DT.REMOTE_RUN, DT.REMOTE_OUT, DT.REMOTE_PY
    return f"""#!/bin/bash
set -uo pipefail
cd {DT.REMOTE_SRC}
export OMP_NUM_THREADS=1
finish() {{ echo "$1" > {run}/EXIT.tmp && mv {run}/EXIT.tmp {run}/EXIT; exit "$1"; }}
echo tournament > {run}/STAGE
date -u +%s > {run}/STARTED
{py} tools/search_ab.py {cmd} > {run}/tournament.log 2>&1 || finish $?
test -f {out}/COMPLETE.json || finish 3
cp {run}/machine.json {run}/plan.json {out}/
(cd {out} && sha256sum {names} > SHA256SUMS) || finish 4
echo done > {run}/STAGE
finish 0
"""


def total_ceiling(shards, max_hours, price_hourly):
    """What the requested shards can cost at most: each may run to --max-hours."""
    return len(shards) * float(max_hours) * float(price_hourly)


def budget_refusal(shards, max_hours, price_hourly, max_total_usd):
    total = total_ceiling(shards, max_hours, price_hourly)
    if total > max_total_usd + 1e-9:
        return (f"{len(shards)} shard(s) x {max_hours} h x ${price_hourly:.5f}/h = "
                f"${total:.2f}, above --max-total-usd {max_total_usd}. Nothing was created.")
    return None


def make_archive(commit, path):
    with open(path, "wb") as f:
        subprocess.run(["git", "-C", ROOT, "archive", "--format=tar.gz", commit, "--",
                        *SYNC_PATHS], check=True, stdout=f)


def prepare(args):
    """Every check that needs no network. Returns what a run needs."""
    name = DT.validate_name(args.name)
    try:
        plan, plan_sha = AB.load_plan(args.plan, args.expect_sha256)
    except SystemExit as exc:
        raise DT.RunnerError(str(exc))
    known = [s["name"] for s in plan["shards"]]
    shards = args.shard or known
    for shard in shards:
        if shard not in known:
            raise DT.RunnerError(f"the plan has no shard {shard!r} (it has {known})")
        run_name(name, shard)
    if len(set(shards)) != len(shards):
        raise DT.RunnerError("a shard is named twice")
    if args.resume_from and len(shards) != 1:
        raise DT.RunnerError("--resume-from relaunches one shard: name it with --shard")
    checkpoint = os.path.abspath(os.path.expanduser(args.checkpoint))
    for path in (checkpoint, checkpoint + ".lineage.json"):
        if not os.path.isfile(path):
            raise DT.RunnerError(f"checkpoint: missing {path}")
    if DT.sha256_file(checkpoint) != plan["checkpoint_sha256"]:
        raise DT.RunnerError(f"{checkpoint} is not the plan's checkpoint "
                             f"({plan['checkpoint_sha256']})")
    from play_harness import engine as E
    try:
        manifest_sha = E.load_reward_manifest(args.manifest)["sha256"]
    except (OSError, ValueError) as exc:
        raise DT.RunnerError(f"reward manifest {args.manifest}: {exc}")
    if manifest_sha != plan["reward_manifest_sha256"]:
        raise DT.RunnerError(f"{args.manifest} is not the plan's reward manifest "
                             f"({plan['reward_manifest_sha256']})")
    commit = DT.git("rev-parse", "--verify", args.commit + "^{commit}")
    if commit != plan["source_commit"]:
        raise DT.RunnerError(f"commit {commit} is not the plan's source_commit "
                             f"{plan['source_commit']}")
    dirty = DT.git("status", "--porcelain", "--", *SYNC_PATHS)
    if dirty:
        raise DT.RunnerError("uncommitted changes under the synced paths; the droplet gets "
                             f"commit {commit[:12]}:\n{dirty}")
    if AB.code_sha256() != plan["code_sha256"]:
        raise DT.RunnerError("the code at this commit does not hash to the plan's code_sha256")
    out_root = os.path.abspath(os.path.join(args.out_root, name))
    for shard in shards:
        for suffix in ("", ".failed", ".partial"):
            if os.path.exists(os.path.join(out_root, shard) + suffix):
                raise DT.RunnerError(f"{os.path.join(out_root, shard) + suffix} already "
                                     "exists; pick a new --name")
    resume = None
    if args.resume_from:
        resume = os.path.abspath(args.resume_from)
        try:
            with open(os.path.join(resume, "run.json")) as f:
                before = json.load(f)
            done = AB.load_records(os.path.join(resume, "games.jsonl"))
        except (OSError, ValueError) as exc:
            raise DT.RunnerError(f"--resume-from {resume}: {exc}")
        wanted = set(AB.shard_tasks(plan, shards[0]))
        if before.get("plan_sha256") != plan_sha or before.get("shard") != shards[0] or \
                any(AB.record_key(r) not in wanted for r in done):
            raise DT.RunnerError(f"--resume-from {resume} is not shard {shards[0]} of this plan")
    return {"name": name, "plan": plan, "plan_sha": plan_sha, "shards": shards,
            "checkpoint": checkpoint, "commit": commit, "out_root": out_root, "resume": resume,
            "tasks": {shard: AB.shard_tasks(plan, shard) for shard in shards}}


def describe(args, ready, price=None):
    """The plan of action, as text: what would be created, synced and run."""
    plan = ready["plan"]
    lines = [f"plan {plan['name']} ({ready['plan_sha']})", f"commit {ready['commit']}",
             f"checkpoint {ready['checkpoint']} ({plan['checkpoint_sha256'][:12]})",
             f"size {args.size} in {args.region}, tag {DT.TAG}, image {DT.IMAGE}",
             "sync: " + ", ".join(SYNC_PATHS)]
    for shard in ready["shards"]:
        tasks = ready["tasks"][shard]
        arms = sorted({arm for _, _, arm in tasks})
        lines.append(f"shard {shard}: droplet {DT.droplet_name(run_name(ready['name'], shard))}, "
                     f"{len(tasks)} games ({', '.join(arms)}), results in "
                     f"{os.path.join(ready['out_root'], shard)}")
        lines.append("  " + " ".join(["python", "tools/search_ab.py"] + play_argv(
            ready["plan_sha"], shard, DT.remote_checkpoint_path("a", ready["checkpoint"]),
            args.processes or 0)).replace("--processes 0", "--processes <the size's vCPUs>"))
    if ready["resume"]:
        lines.append(f"resuming from {ready['resume']}: its finished games are uploaded and "
                     "not played again")
    hours = f"{len(ready['shards'])} shard(s) x {args.max_hours} h"
    if price is None:
        lines.append(f"spend guard: {hours} x the hourly price (read at run time) must not "
                     f"exceed ${args.max_total_usd}")
    else:
        lines.append(f"spend guard: {hours} x ${price:.5f}/h = "
                     f"${total_ceiling(ready['shards'], args.max_hours, price):.2f} of "
                     f"${args.max_total_usd} allowed")
    return "\n".join(lines)


def fetch_partial(remote, directory):
    """Whatever of the logs and of the records so far can still be fetched. Never
    raises: this runs on the way to teardown."""
    try:
        os.makedirs(directory, exist_ok=True)
        for fname in LOG_FILES:
            try:
                remote.get(f"{DT.REMOTE_RUN}/{fname}", os.path.join(directory, fname),
                           check=False, timeout=120)
            except Exception:
                pass
        for fname in PARTIAL_FILES:
            try:
                remote.get(f"{DT.REMOTE_OUT}/{fname}", os.path.join(directory, fname),
                           check=False, timeout=300)
            except Exception:
                pass
        return True
    except Exception:
        return False


def verify_shard(directory, plan, plan_sha, shard, commit):
    """Problems with a fetched shard directory, against the plan."""
    with open(os.path.join(directory, "SHA256SUMS")) as f:
        sums = DT.parse_sha256sums(f.read())
    problems = DT.verify_files(directory, sums, required=RESULT_FILES + PROVENANCE_FILES)
    if DT.sha256_file(os.path.join(directory, "plan.json")) != plan_sha:
        problems.append("the droplet's plan.json is not the plan")
    with open(os.path.join(directory, "machine.json")) as f:
        if json.load(f).get("source_commit") != commit:
            problems.append("the droplet built another commit")
    records = AB.load_records(os.path.join(directory, "games.jsonl"))
    if sorted(AB.record_key(r) for r in records) != sorted(AB.shard_tasks(plan, shard)):
        problems.append("games.jsonl does not hold exactly the shard's games")
    wrong = [AB.record_key(r) for r in records
             if r["hashes"]["plan_sha256"] != plan_sha or r["shard"] != shard]
    if wrong:
        problems.append(f"{len(wrong)} record(s) of another plan or shard, first {wrong[0]}")
    invalid = [AB.record_key(r) for r in records if r["invalid"]]
    return problems, len(records), len(invalid), len(sums)


def run_shard(args, ready, shard, api, size):
    """One droplet, one shard, teardown on every exit path. Returns the result."""
    plan, plan_sha, commit = ready["plan"], ready["plan_sha"], ready["commit"]
    name = run_name(ready["name"], shard)
    out_dir = os.path.join(ready["out_root"], shard)
    tasks = len(ready["tasks"][shard])
    price = float(size["price_hourly"])
    processes = args.processes or int(size["vcpus"])
    state = DT.State(name, root=args.state_root)
    lock = state.lock()                                     # held until the process exits
    if state.read("droplet-id") or state.read("create-attempted"):
        raise DT.RunnerError(f"state already records a droplet or an unresolved create for "
                             f"{name}; run `tools/droplet_tournament.py destroy --name {name}`")
    DT.log(f"shard {shard}: {tasks} games on {processes} processes, {size['vcpus']} vCPU at "
           f"${price:.5f}/h; --max-hours {args.max_hours} caps it at about "
           f"${args.max_hours * price:.2f}")
    state.write("price-hourly", price)

    def on_signal(signum, _frame):
        raise DT.Interrupted(f"signal {signum}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)

    t_start = time.time()
    deadline = t_start + args.max_hours * 3600
    result, remote, failed = None, None, True
    try:
        fingerprint = DT.create_key(api, state, name)
        droplet_id = DT.create_droplet(api, state, name, args.region, args.size, fingerprint)
        ip = DT.wait_active(api, droplet_id)
        state.write("ip", ip)
        remote = DT.Remote(state.dir, ip)
        DT.wait_ssh(remote)
        DT.log(f"droplet {droplet_id} up at {ip} after {time.time() - t_start:.0f} s; installing")
        remote.script(DT.setup_script(args.torch, args.numpy), "setup.log", timeout=1500)
        archive = state.path("src.tar.gz")
        make_archive(commit, archive)
        remote.put(archive, f"{DT.REMOTE_ROOT}/src.tar.gz")
        remote.run(f"tar -xzf {DT.REMOTE_ROOT}/src.tar.gz -C {DT.REMOTE_SRC} && "
                   f"echo {commit} > {DT.REMOTE_SRC}/SOURCE_COMMIT")
        target = DT.remote_checkpoint_path("a", ready["checkpoint"])
        remote.run(f"mkdir -p {shlex.quote(os.path.dirname(target))} {DT.REMOTE_OUT}")
        remote.put(ready["checkpoint"], target)
        remote.put(ready["checkpoint"] + ".lineage.json", target + ".lineage.json")
        remote.put(os.path.abspath(args.plan), REMOTE_PLAN)
        remote.put(os.path.abspath(args.manifest), REMOTE_MANIFEST)
        if ready["resume"]:
            # The finished games go up first; play skips their keys and appends.
            for fname in PARTIAL_FILES:
                remote.put(os.path.join(ready["resume"], fname), f"{DT.REMOTE_OUT}/{fname}")
        built = remote.script(DT.build_script(commit), "build.log", timeout=900)
        machine = json.loads([l for l in built.stdout.splitlines() if l.startswith("{")][-1])
        DT.log(f"shim built: {machine['cpu_model']}, {machine['nproc']} cores, "
               f"library {machine['library_sha256'][:12]}")
        argv = play_argv(plan_sha, shard, target, processes)
        remote.run(f"cat > {DT.REMOTE_RUN}/job.sh", stdin_text=job_script(argv))
        remote.run(f"nohup setsid bash {DT.REMOTE_RUN}/job.sh > {DT.REMOTE_RUN}/job.log 2>&1 "
                   f"< /dev/null & echo started", timeout=60)
        t_launch = time.time()
        DT.log(f"shard {shard} launched under nohup ({t_launch - t_start:.0f} s after create)")
        rc = DT.poll(remote, tasks, deadline, args.stale_seconds)
        if rc != 0:
            raise DT.RunnerError(f"droplet job exited {rc}; logs and the records so far are "
                                 f"copied to {out_dir}.failed")
        partial = out_dir + ".partial"
        os.makedirs(partial, exist_ok=True)
        for fname in RESULT_FILES + PROVENANCE_FILES + ("SHA256SUMS",):
            remote.get(f"{DT.REMOTE_OUT}/{fname}", os.path.join(partial, fname))
        remote.get(f"{DT.REMOTE_RUN}/tournament.log", os.path.join(partial, "tournament.log"),
                   check=False)
        problems, games, invalid, files = verify_shard(partial, plan, plan_sha, shard, commit)
        if problems:
            raise DT.RunnerError("verification failed:\n  " + "\n  ".join(problems))
        DT.log(f"verified {files} files by sha256 and {games} games against the plan"
               + (f"; {invalid} INVALID game(s), which report will refuse" if invalid else ""))
        result = {"schema": "search-ab-droplet-run-v1", "name": name, "shard": shard,
                  "plan_sha256": plan_sha, "droplet_id": droplet_id, "size": args.size,
                  "region": args.region, "price_hourly": price, "vcpus": size["vcpus"],
                  "processes": processes, "commit": commit, "machine": machine, "games": games,
                  "invalid_games": invalid, "resumed_from": ready["resume"],
                  "seconds": {"create_to_launch": round(t_launch - t_start, 1),
                              "launch_to_done": round(time.time() - t_launch, 1)}}
        os.rename(partial, out_dir)
        failed = False
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)               # teardown must finish
        if failed and remote is not None:
            # Timeout, a failed job, an interrupt: keep what the droplet has played.
            if fetch_partial(remote, out_dir + ".failed"):
                DT.log(f"logs and the records so far (what could be fetched) are in "
                       f"{out_dir}.failed; relaunch with --resume-from {out_dir}.failed")
        if args.keep:
            DT.log(f"--keep: droplet {state.read('droplet-id')} at {state.read('ip')} is STILL "
                   f"BILLING. Then: tools/droplet_tournament.py destroy --name {name}")
        else:
            try:
                DT.teardown(api, state, name)
            except BaseException:
                try:
                    print(f"TEARDOWN FAILED: droplet {state.read('droplet-id')} may STILL BE "
                          f"BILLING. Run: tools/droplet_tournament.py destroy --name {name}",
                          file=sys.stderr, flush=True)
                except Exception:
                    pass
                raise
            if result is not None:
                result["cost"] = float(state.read("cost") or 0.0)
                result["lifetime_seconds"] = round(time.time() - t_start, 1)
        if result is not None:
            with open(os.path.join(out_dir, "droplet_run.json"), "w") as f:
                json.dump(result, f, indent=1)
    del lock
    DT.log(f"shard {shard}: results in {out_dir}")
    return result


def child_argv(args, shard):
    """The command line of the child process that runs one shard."""
    argv = [sys.executable, os.path.abspath(__file__), "--env-file", args.env_file, "run",
            "--name", args.name, "--plan", args.plan, "--expect-sha256", args.expect_sha256,
            "--checkpoint", args.checkpoint, "--manifest", args.manifest, "--shard", shard,
            "--size", args.size, "--region", args.region, "--max-hourly", str(args.max_hourly),
            "--max-hours", str(args.max_hours), "--max-total-usd", str(args.max_total_usd),
            "--stale-seconds", str(args.stale_seconds), "--commit", args.commit,
            "--out-root", args.out_root, "--state-root", args.state_root,
            "--torch", args.torch, "--numpy", args.numpy, "--child"]
    if args.processes:
        argv += ["--processes", str(args.processes)]
    if args.keep:
        argv.append("--keep")
    return argv


def run_children(args, ready):
    """One child process per shard; an interrupt is passed on so each tears down."""
    os.makedirs(ready["out_root"], exist_ok=True)
    children = {}
    for shard in ready["shards"]:
        log_path = os.path.join(ready["out_root"], f"{shard}.runner.log")
        with open(log_path, "w") as sink:
            children[shard] = subprocess.Popen(child_argv(args, shard), stdout=sink,
                                               stderr=subprocess.STDOUT,
                                               stdin=subprocess.DEVNULL)
        DT.log(f"shard {shard}: runner pid {children[shard].pid}, log {log_path}")

    def forward(signum, _frame):
        for child in children.values():
            if child.poll() is None:
                child.send_signal(signal.SIGINT)
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, forward)
    codes = {shard: child.wait() for shard, child in children.items()}
    for shard, code in codes.items():
        DT.log(f"shard {shard}: runner exited {code}")
    return codes


def cmd_run(args):
    ready = prepare(args)
    if args.dry_run:
        refusal = None
        if args.assume_hourly is not None:
            refusal = budget_refusal(ready["shards"], args.max_hours, args.assume_hourly,
                                     args.max_total_usd)
        print("DRY RUN: nothing is created, no network call is made")
        print(describe(args, ready, args.assume_hourly))
        if refusal:
            raise DT.RunnerError(refusal)
        return 0
    api = DT.Api(DT.read_token(env_file=args.env_file))
    size = DT.pick_size(api.get("/sizes?per_page=200")["sizes"], args.size, args.region,
                        args.max_hourly)
    price = float(size["price_hourly"])
    if args.child:
        return 0 if run_shard(args, ready, ready["shards"][0], api, size) else 1
    refusal = budget_refusal(ready["shards"], args.max_hours, price, args.max_total_usd)
    if refusal:
        raise DT.RunnerError(refusal)
    print(describe(args, ready, price), flush=True)
    DT.log("tagged droplets before:")
    DT.print_status(api)
    limit = int(api.get("/account")["account"]["droplet_limit"])
    existing = len(api.get("/droplets?per_page=200")["droplets"])
    refusal = DT.limit_refusal(existing + len(ready["shards"]) - 1, limit)
    if refusal:
        raise DT.RunnerError(f"{refusal} (this run needs {len(ready['shards'])} more)")
    try:
        if len(ready["shards"]) == 1:
            ok = run_shard(args, ready, ready["shards"][0], api, size) is not None
        else:
            ok = not any(run_children(args, ready).values())
    finally:
        DT.log("tagged droplets after:")
        try:
            DT.print_status(api)
        except DT.RunnerError as exc:
            DT.log(f"the listing could not be read ({exc}); run "
                   "`tools/droplet_tournament.py status` by hand")
    return 0 if ok else 1


def build_parser():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--env-file", default=DT.DEFAULT_ENV_FILE,
                    help=f"dotenv file holding {DT.TOKEN_VAR} (the environment wins)")
    sub = ap.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="one droplet per shard: create, play, fetch, destroy")
    run.add_argument("--name", required=True,
                     help="run name; a shard's results land in OUT_ROOT/NAME/SHARD")
    run.add_argument("--plan", required=True)
    run.add_argument("--expect-sha256", required=True, help="the plan file's sha256")
    run.add_argument("--checkpoint", required=True, help="the blob the plan names by hash")
    run.add_argument("--manifest", default=AB.DEFAULT_MANIFEST)
    run.add_argument("--shard", action="append", default=None,
                     help="repeatable; default: every shard of the plan")
    run.add_argument("--resume-from", default=None, metavar="DIR",
                     help="a shard's earlier output (games.jsonl, run.json): play only the rest")
    run.add_argument("--processes", type=int, default=None, help="default: the size's vCPUs")
    run.add_argument("--size", default=DT.DEFAULT_SIZE)
    run.add_argument("--region", default=DT.DEFAULT_REGION)
    run.add_argument("--max-hourly", type=float, default=DT.MAX_HOURLY_DEFAULT)
    run.add_argument("--max-hours", type=float, required=True,
                     help="per shard: give up, fetch the records so far, destroy the droplet")
    run.add_argument("--max-total-usd", type=float, required=True,
                     help="shards x max-hours x hourly price must not exceed this")
    run.add_argument("--stale-seconds", type=int, default=1800,
                     help="fail when the play log is silent this long")
    run.add_argument("--commit", default="HEAD")
    run.add_argument("--out-root", default=os.path.join(ROOT, ".play-artifacts", "search-ab"))
    run.add_argument("--state-root", default=DT.STATE_ROOT)
    run.add_argument("--torch", default=DT.TORCH_VERSION)
    run.add_argument("--numpy", default=DT.NUMPY_VERSION)
    run.add_argument("--keep", action="store_true",
                     help="debugging: leave the droplet running (it keeps billing)")
    run.add_argument("--dry-run", action="store_true",
                     help="print what would be done; create nothing, call nothing")
    run.add_argument("--assume-hourly", type=float, default=None,
                     help="with --dry-run: apply the spend guard at this hourly price")
    run.add_argument("--child", action="store_true", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
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
