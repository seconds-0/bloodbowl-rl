#!/usr/bin/env python3
"""Run shards of the search-distillation plan's label tool on throwaway DigitalOcean droplets.

One droplet runs one shard (a block of games of the plan's one checkpoint). The
droplet lifecycle is the harness's tools/droplet_tournament.py, imported from
the export of the pinned commit and not copied: its tag and disposable ssh key,
its setup and build scripts, its polling, its state directory and its teardown.
The file is held to the hash the plan records before it is imported. The flow
is the END_TURN probe's launcher (docs/endturn-probe-2026-10-08/endturn_droplet.py)
with distill_screen.py in place of the probe, and it keeps that launcher's
rules:

  names      every run draws a random run id; the droplet, its ssh key and its
             local state are named NAME-SHARD-RUNID. Before anything is
             created the launcher refuses if local state of that name exists
             or the account already lists a droplet or key of that name (the
             listings are read page by page, all of them).
  ownership  what this launcher itself deletes, it deletes on evidence. An ssh
             key left behind under the run's name is deleted only when its
             public key (or fingerprint) is the one this run generated
             locally; a key of that name with another public key is reported
             and left alone. The droplet side is the inherited lifecycle's and
             is weaker: it destroys the droplet id it recorded when the create
             was answered, and after a create whose answer was lost it adopts
             a droplet by the shared tag, the exact name (which carries this
             run's random id) and a creation time after the attempt. That is
             very unlikely, not impossible, to be another process's droplet:
             another process could create the same name between the check and
             the create.
  stages     for the registered plan the shards must be named with --shard;
             there is no default to all eight, so a stage is launched on
             purpose. --keep, which leaves a droplet billing, is refused
             except for the smoke and dev plans.
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
  hashes     the launcher refuses unless the plan hashes to --expect-sha256,
             this file is the launcher the plan names (launcher_sha256), the
             six tool files beside it are the ones the plan names
             (tool_sha256), and the checkpoint blob and its lineage sidecar
             are the plan's. All of that is checked before anything is created.

What goes to the droplet: the pinned commit's synced paths (the lifecycle's
build script builds the engine shim there; this tool has no library of its
own), the six tool files (distill_common.load_plan checks all of them on the
droplet again), the plan, and the checkpoint blob with its lineage sidecar
beside it (the harness's loader requires the sidecar).

  distill_droplet.py run --name sd1 --plan PLAN.json --expect-sha256 H \\
      --harness-export EXPORT --max-hours 5 --max-total-usd 7 \\
      --shard m1-s1 --shard m1-s2 [--dry-run [--assume-hourly 0.16667]]

  distill_droplet.py rehearse --plan PLAN.dev.json --expect-sha256 H \\
      --harness-export EXPORT --shard dev --dir SCRATCH --python VENV_PYTHON

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
  python EXPORT/tools/droplet_tournament.py --env-file ENV destroy --id $(cat STATE/NAME-SHARD-RUNID/droplet-id)

Both destroy forms act on the droplet id this run recorded in its own state
directory. `destroy --name` reads the default state directory only; a run
started with another --state-root is cleaned up with the second form. The text
never tells anyone to destroy a droplet by an id taken from a listing: when a
shard's state holds no droplet id, the run recorded none, and a listed droplet
of the run's exact name is to be looked at by a person first.

`rehearse` runs the same droplet-side job script and the same acceptance on
this machine in a scratch directory, with no network call. Its source tree is
the lifecycle's synced paths and nothing else of the export, with its own build
of the shim, so a file the droplet would lack is missing there too. It tests
the script and the file lists; it is not a way to produce registered records.
"""
from __future__ import annotations

import argparse
import base64
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
import distill_accept as ACCEPT  # noqa: E402
import distill_common as C  # noqa: E402

TOOL_FILES = C.TOOL_FILES     # all six go to the droplet: load_plan checks every one there
LAUNCHER = C.LAUNCHER_FILE
LABEL_TOOL = "distill_screen.py"
LIFECYCLE = "tools/droplet_tournament.py"
# SHA256SUMS is the tool's own file and lists the five others.
RESULT_FILES = ("SHA256SUMS", "plan.json", "COMPLETE.json", "roots.jsonl", "games.jsonl",
                "other.jsonl")
FAILURE_LOGS = ("EXIT", "STAGE", "job.log", "build.log", "setup.log")
TEARDOWN_RESERVE = 300        # seconds of --max-hours kept back for the failure logs and the delete
FAILURE_FETCH_SECONDS = 45    # all the failure logs together
MIN_HOURS = 0.25
DEFAULT_PROCESSES = 8         # what a dry run assumes; a real run uses the size's vCPUs
REGISTERED_PLAN = "search-distill-registered"
KEEP_PLANS = ("search-distill-smoke", "search-distill-dev")      # the only plans --keep is for
PAGE = 200
DT = None                     # the harness's droplet_tournament, set by load_dt


def sha256_file(path):
    return C.sha256_file(path)


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
    return {"tools": DT.REMOTE_ROOT + "/distill", "plan": DT.REMOTE_RUN + "/plan.json"}


def job_script(plan_sha, shard, remote_blob, processes):
    """The detached job: the label tool for the shard, then an atomic EXIT file.
    The tool writes its records, its plan copy and its own SHA256SUMS straight
    into the lifecycle's output directory. The stage is called `tournament` and
    the log tournament.log so that the droplet tool's poll reads this job as its
    own (the tool prints a line when a game has finished since its last line,
    at most once a minute, so a hung worker shows there as a stale log)."""
    r = remote_paths()
    run, out, py = DT.REMOTE_RUN, DT.REMOTE_OUT, DT.REMOTE_PY
    argv = ["run", "--harness", DT.REMOTE_SRC, "--plan", r["plan"], "--expect-sha256", plan_sha,
            "--shard", shard, "--checkpoint", remote_blob, "--out-dir", out,
            "--processes", str(int(processes))]
    cmd = " ".join(shlex.quote(a) for a in argv)
    lines = [f"""#!/bin/bash
set -uo pipefail
cd {DT.REMOTE_SRC}
export OMP_NUM_THREADS=1
finish() {{ echo "$1" > {run}/EXIT.tmp && mv {run}/EXIT.tmp {run}/EXIT; exit "$1"; }}
echo tournament > {run}/STAGE
date -u +%s > {run}/STARTED
: > {run}/tournament.log""",
             f"{py} {r['tools']}/{LABEL_TOOL} {cmd} >> {run}/tournament.log 2>&1 || finish $?",
             f"test -f {out}/COMPLETE.json || finish 3",
             f"(cd {out} && test -f SHA256SUMS && test ! -e FAILED.json) || finish 4",
             f"echo done > {run}/STAGE",
             "finish 0"]
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
    if os.path.abspath(C.HERE) != HERE:
        raise DT.RunnerError(f"distill_common was imported from {C.HERE}, not from beside this "
                             "script")
    try:
        plan, plan_sha = C.load_plan(args.plan, args.expect_sha256)     # the six tool files too
    except SystemExit as exc:
        raise DT.RunnerError(str(exc))
    want = (plan.get("launcher_sha256") or {}).get(LAUNCHER)
    if want is None:
        raise DT.RunnerError(f"the plan names no {LAUNCHER} (launcher_sha256 is empty: it was "
                             "written before the launcher existed); rerun make_plan.py before "
                             "the plan is committed")
    if sha256_file(os.path.abspath(__file__)) != want:
        raise DT.RunnerError(f"this {LAUNCHER} is not the file the plan names (launcher_sha256); "
                             "rerun make_plan.py before the plan is committed")
    known = {s["name"]: s for s in plan["shards"]}
    if getattr(args, "keep", False) and plan["name"] not in KEEP_PLANS:
        raise DT.RunnerError(f"--keep leaves a droplet billing after the run and is refused for "
                             f"the plan {plan['name']}; it is for the smoke and dev plans only. "
                             "Nothing was created.")
    if not args.shard and plan["name"] == REGISTERED_PLAN:
        raise DT.RunnerError("the registered plan is launched one stage at a time: name the shards "
                             "with --shard (milestone 1: m1-s1 and m1-s2; milestone 2: m2-s1 to "
                             f"m2-s6). The plan has {sorted(known)}. Nothing was created.")
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
    if sha256_file(os.path.join(export, LIFECYCLE)) != plan["lifecycle_sha256"][LIFECYCLE]:
        raise DT.RunnerError(f"the export's {LIFECYCLE} is not the file the plan names")
    manifest = os.path.join(export, "puffer", "config", "rewards", plan["reward_manifest"] + ".json")
    if sha256_file(manifest) != plan["reward_manifest_file_sha256"]:
        raise DT.RunnerError(f"{manifest} is not the plan's reward manifest file")
    ck = plan["checkpoint"]
    blob = os.path.join(os.path.expanduser(args.checkpoint_store), ck["blob"])
    for p in (blob, blob + ".lineage.json"):
        if not os.path.isfile(p):
            raise DT.RunnerError(f"checkpoint: missing {p}")
    if sha256_file(blob) != ck["sha256"]:
        raise DT.RunnerError(f"{blob} is not the plan's {ck['name']}")
    if sha256_file(blob + ".lineage.json") != ck["sidecar_sha256"]:
        raise DT.RunnerError(f"{blob}.lineage.json is not the plan's lineage sidecar of "
                             f"{ck['name']}")
    out_root = os.path.abspath(os.path.join(args.out_root, name))
    if os.path.exists(out_root) and not os.path.isfile(os.path.join(out_root, "CLEANUP.txt")):
        raise DT.RunnerError(f"{out_root} already exists and is not a run directory of this "
                             "launcher (no CLEANUP.txt); pick a new --name")
    for shard in shards:
        for suffix in ("", ".failed", ".partial"):
            if os.path.exists(os.path.join(out_root, shard) + suffix):
                raise DT.RunnerError(f"{os.path.join(out_root, shard) + suffix} already exists; "
                                     "pick a new --name")
    return {"name": name, "plan": plan, "plan_sha": plan_sha, "shards": shards, "known": known,
            "commit": commit, "export": export, "checkpoint": blob, "out_root": out_root}


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
        lines.append(f"  (`destroy --name` destroys the droplet id this run recorded in "
                     f"{state_root}/<name>/droplet-id, and no other.)")
    else:
        lines.append(f"  (`destroy --name` reads {os.path.expanduser(DT.STATE_ROOT)} only and cannot "
                     f"be used: this run's state is in {state_root}.)")
    lines.append("These commands act only on droplet ids this run recorded. If a shard's state "
                 "directory holds no droplet-id file, this run recorded no droplet for it: its "
                 "create was never answered. Do not destroy a listed droplet by id on a guess. "
                 "A droplet could be this run's only if its name is exactly one of the names "
                 f"above (they end in this run id: {run_id}); look at its creation time in the "
                 "status listing and decide by hand. An ssh key of the run's name that stays "
                 "listed costs nothing.")
    return "\n".join(lines)


def shard_estimate(plan, games, processes, price):
    """(seconds, dollars or None): the games at the plan's seconds a game on one
    core, spread over the worker processes, plus the setup."""
    est = plan["estimate"]
    workers = max(1, min(int(processes), int(games)))       # the label tool's own rule
    seconds = est["setup_seconds"] + games * est["droplet_seconds_per_game"] / workers
    return seconds, None if price is None else DT.cost(seconds, price)


def describe(args, ready, run_id, price=None, vcpus=None):
    plan = ready["plan"]
    ck = plan["checkpoint"]
    processes = args.processes or vcpus or DEFAULT_PROCESSES
    remote_blob = DT.remote_checkpoint_path(ck["name"], ready["checkpoint"])
    lines = [f"plan {plan['name']} ({ready['plan_sha']})",
             f"harness commit {ready['commit']} from {args.harness_repo}; lifecycle code from "
             f"{ready['export']}/{LIFECYCLE}",
             f"size {args.size} in {args.region}, tag {DT.TAG}, image {DT.IMAGE}",
             "sync: " + ", ".join(DT.SYNC_PATHS) + "; label tool files: " + ", ".join(TOOL_FILES),
             f"checkpoint {ck['name']} ({ck['sha256']}) from {ready['checkpoint']}, with its "
             f"lineage sidecar ({ck['sidecar_sha256']})",
             f"label settings: {json.dumps(plan['label'])}",
             f"run id {run_id}: the suffix of every name this run creates"]
    total_seconds = 0.0
    for shard in ready["shards"]:
        spec = ready["known"][shard]
        games, first = int(spec["games"]), int(spec["first_game"])
        seconds, usd = shard_estimate(plan, games, processes, price)
        total_seconds += seconds
        unique = run_name(ready["name"], shard, run_id)
        lines.append(f"shard {shard}: droplet {DT.droplet_name(unique)}, games {first} to "
                     f"{first + games - 1} ({games} games), results in "
                     f"{os.path.join(ready['out_root'], shard)}")
        lines.append(f"  estimate: {seconds / 3600:.2f} h"
                     + (f", about ${usd:.2f}" if usd is not None else "")
                     + f" (the plan's {plan['estimate']['droplet_seconds_per_game']} s a game on "
                       f"one core, over {max(1, min(processes, games))} processes, plus "
                       f"{plan['estimate']['setup_seconds']} s of setup; not measured on a droplet)")
        for line in job_script(ready["plan_sha"], shard, remote_blob, processes).splitlines():
            if LABEL_TOOL in line:
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


def list_all(api, path, key):
    """Every entry of a listing, page by page (read-only calls)."""
    items, page = [], 1
    while True:
        got = api.get(f"{path}{'&' if '?' in path else '?'}per_page={PAGE}&page={page}")[key]
        items += got
        if len(got) < PAGE:
            return items
        page += 1
        if page > 250:
            raise DT.RunnerError(f"the listing {path} did not end after {page - 1} pages")


def key_identity(public_key):
    """(key body, MD5 fingerprint) of an OpenSSH public key line, or None."""
    try:
        body = str(public_key).split()[1]
        digest = hashlib.md5(base64.b64decode(body)).hexdigest()
        return body, ":".join(digest[i:i + 2] for i in range(0, 32, 2))
    except (IndexError, ValueError, TypeError):
        return None


def account_refusal(api, unique):
    """Why nothing may be created under this name, or None. Read-only calls."""
    wanted = DT.droplet_name(unique)
    if any(d.get("name") == wanted for d in list_all(api, "/droplets", "droplets")):
        return f"the account already has a droplet named {wanted}"
    if any(k.get("name") == wanted for k in list_all(api, "/account/keys", "ssh_keys")):
        return f"the account already has an ssh key named {wanted}"
    return None


def reconcile(api, unique, public_key):
    """After teardown: nothing of this run may be left. An ssh key listed under
    this run's unique name is deleted here only when it is the key this run
    generated: its public key, or its fingerprint, equals the local one
    (`public_key` is the line of the run's own key.pub, or None when the run
    never generated a key). That covers a registration whose answer was lost.
    A key of the run's name with any other public key is not this run's: it is
    reported and left alone. A droplet of this name that is still listed is
    reported, never guessed at. Returns the ids of the keys left alone."""
    wanted = DT.droplet_name(unique)
    ours = key_identity(public_key) if public_key else None
    foreign = []
    for key in list_all(api, "/account/keys", "ssh_keys"):
        if key.get("name") != wanted:
            continue
        theirs = key_identity(key.get("public_key"))
        same = ours is not None and ((theirs is not None and theirs[0] == ours[0])
                                     or key.get("fingerprint") == ours[1])
        if same:
            status, _ = api.call("DELETE", f"/account/keys/{key['id']}")
            DT.log(f"removed this run's leftover ssh key {key['id']} ({wanted}): HTTP {status}")
        else:
            foreign.append(key["id"])
            DT.log(f"an ssh key named {wanted} (id {key['id']}) does not hold the public key "
                   "this run generated: it is not this run's, and it is LEFT ALONE")
    left = [d for d in list_all(api, f"/droplets?tag_name={DT.TAG}", "droplets")
            if d.get("name") == wanted]
    if left:
        raise DT.RunnerError(f"droplet(s) named {wanted} STILL EXIST: {[d['id'] for d in left]}; "
                             "this run's recorded droplet id is in its state directory "
                             "(CLEANUP.txt); look before destroying any other")
    return foreign


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
                                  f"cat {DT.REMOTE_OUT}/FAILED.json 2>/dev/null; "
                                  f"tail -n 15 {DT.REMOTE_OUT}/worker*.log 2>/dev/null",
                                  check=False, timeout=max(2, int(min(10, left))))
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
    spec = ready["known"][shard]
    ck = plan["checkpoint"]
    out_dir = os.path.join(ready["out_root"], shard)
    tasks = int(spec["games"])
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
    result, remote, failed, public_key = None, None, True, None
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
        remote.run(f"mkdir -p {r['tools']}", timeout=clock.cap(60, "mkdir"))
        for fname in TOOL_FILES:
            remote.put(os.path.join(HERE, fname), f"{r['tools']}/{fname}",
                       timeout=clock.cap(120, "the tool upload"))
        remote_blob = DT.remote_checkpoint_path(ck["name"], ready["checkpoint"])
        remote.run(f"mkdir -p {shlex.quote(os.path.dirname(remote_blob))}",
                   timeout=clock.cap(60, "mkdir"))
        remote.put(ready["checkpoint"], remote_blob, timeout=clock.cap(600, "the checkpoint upload"))
        remote.put(ready["checkpoint"] + ".lineage.json", remote_blob + ".lineage.json",
                   timeout=clock.cap(120, "the sidecar upload"))
        remote.put(os.path.abspath(args.plan), r["plan"], timeout=clock.cap(120, "the plan upload"))
        built = remote.script(DT.build_script(commit), "build.log",
                              timeout=clock.cap(900, "the shim build"))
        machine = json.loads([l for l in built.stdout.splitlines() if l.startswith("{")][-1])
        DT.log(f"shim built: {machine['cpu_model']}, {machine['nproc']} cores")
        remote.run(f"cat > {DT.REMOTE_RUN}/job.sh",
                   stdin_text=job_script(plan_sha, shard, remote_blob, processes),
                   timeout=clock.cap(60, "the job upload"))
        remote.run(f"nohup setsid bash {DT.REMOTE_RUN}/job.sh > {DT.REMOTE_RUN}/job.log 2>&1 "
                   f"< /dev/null & echo started", timeout=clock.cap(60, "the launch"))
        t_launch = time.time()
        DT.log(f"shard {shard} launched under nohup ({t_launch - clock.start:.0f} s after create); "
               "the poll's own game count stays 0 until the tool merges its files, the count "
               "that moves is the tool's line after the bar")
        rc = DT.poll(remote, tasks, clock.soft, args.stale_seconds)
        if rc != 0:
            raise DT.RunnerError(f"droplet job exited {rc}; its logs are copied to {out_dir}.failed")
        partial = out_dir + ".partial"
        os.makedirs(partial, exist_ok=True)
        for fname in RESULT_FILES:
            remote.get(f"{DT.REMOTE_OUT}/{fname}", os.path.join(partial, fname),
                       timeout=clock.cap(1200, "the fetch"))
        problems, summary = ACCEPT.shard_problems(partial, shard, plan, plan_sha)
        if not problems and summary.get("library_sha256") != machine.get("library_sha256"):
            problems = [f"{shard}: the records name engine library "
                        f"{summary.get('library_sha256')}, the droplet's build made "
                        f"{machine.get('library_sha256')}"]
        if problems:
            raise DT.RunnerError("the shard is NOT ACCEPTED:\n  " + "\n  ".join(problems))
        DT.log(ACCEPT.accepted_line(summary))
        result = {"schema": "distill-droplet-run-v1", "name": unique, "run_id": run_id,
                  "shard": shard, "droplet_name": DT.droplet_name(unique),
                  "plan_sha256": plan_sha, "droplet_id": droplet_id, "size": args.size,
                  "region": args.region, "price_hourly": price, "vcpus": size["vcpus"],
                  "processes": processes, "commit": commit, "machine": machine,
                  "checkpoint": ck["name"], "first_game": int(spec["first_game"]),
                  "games": tasks, "accepted": True, "acceptance": summary,
                  "seconds": {"create_to_launch": round(t_launch - clock.start, 1),
                              "launch_to_done": round(time.time() - t_launch, 1)}}
        os.rename(partial, out_dir)
        failed = False
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)               # teardown must finish
        # The key this run generated, read before the teardown touches the state.
        public_key = state.read("key.pub")
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
                reconcile(api, unique, public_key)
            except BaseException:
                try:
                    recorded = state.read("droplet-id")
                    env = shlex.quote(os.path.abspath(os.path.expanduser(args.env_file)))
                    if recorded:
                        print(f"TEARDOWN FAILED: droplet {recorded}, the id this run recorded, "
                              f"may STILL BE BILLING. Run: python {ready['export']}/{LIFECYCLE} "
                              f"--env-file {env} destroy --id {recorded}"
                              f"  (see CLEANUP.txt in {ready['out_root']})",
                              file=sys.stderr, flush=True)
                    else:
                        print(f"TEARDOWN FAILED and this run recorded no droplet id for "
                              f"{unique}. A droplet named {DT.droplet_name(unique)} may exist "
                              f"and be billing: look at `python {ready['export']}/{LIFECYCLE} "
                              f"--env-file {env} status` and decide by hand "
                              f"(see CLEANUP.txt in {ready['out_root']})",
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
    print(describe(args, ready, run_id, price, int(size["vcpus"])), flush=True)
    os.makedirs(ready["out_root"], exist_ok=True)
    with open(os.path.join(ready["out_root"], "CLEANUP.txt"), "a") as f:
        f.write(f"run id {run_id}, started {time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                + cleanup_text(args, ready, run_id) + "\n\n")
    DT.log("tagged droplets before:")
    DT.print_status(api)
    limit = int(api.get("/account")["account"]["droplet_limit"])
    existing = len(list_all(api, "/droplets", "droplets"))
    refusal = DT.limit_refusal(existing + len(ready["shards"]) - 1, limit)
    if refusal:
        # The launch exits here. Nothing is deleted to make room; it is retried later.
        raise DT.RunnerError(f"{refusal} (this run needs {len(ready['shards'])} more). Nothing "
                             "was created and nothing is deleted to make room: run it again "
                             "when slots are free.")
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


def rehearsal_source(export, src, commit):
    """The droplet's source tree in the scratch directory: the lifecycle's synced
    paths and nothing else of the export (as links, so a file the tool needs
    and the droplet would not get is missing here too), SOURCE_COMMIT, and its
    own build of the engine shim by the harness's build script, which is what
    the lifecycle's build script runs on the droplet. The build writes into the
    scratch directory only; the harness names the library for the platform."""
    for rel in DT.SYNC_PATHS:
        target = os.path.join(src, rel)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.symlink(os.path.join(export, rel), target)
    with open(os.path.join(src, "SOURCE_COMMIT"), "w") as f:
        f.write(commit + "\n")
    subprocess.run(["bash", os.path.join(src, "play_harness", "native", "build.sh")], check=True,
                   stdout=subprocess.DEVNULL,
                   env={**os.environ, "BBPLAY_BUILD_DIR": os.path.join(src, "build", "play_harness")})


def cmd_rehearse(args):
    """The droplet-side job script and the acceptance, on this machine, no network.
    The scratch directory gets the droplet's layout: the synced source paths
    with their own build of the shim, copies of the six tool files, the plan,
    and the checkpoint blob and its sidecar as links beside each other. The
    shim is built once and every requested shard runs against it, as all
    droplets of one image build the same library."""
    base = os.path.abspath(args.dir)
    if os.path.exists(base):
        raise SystemExit(f"{base} exists; give a fresh --dir")
    DT.REMOTE_ROOT = base
    DT.REMOTE_SRC = base + "/src"
    DT.REMOTE_PY = os.path.abspath(args.python)
    DT.REMOTE_RUN = base + "/run"
    args.name, args.out_root = "rehearsal", base + "/fetched"
    ready = prepare(args, need_repo=False)
    rehearsal_source(ready["export"], DT.REMOTE_SRC, ready["commit"])
    tools = remote_paths()["tools"]
    os.makedirs(tools)
    for fname in TOOL_FILES:
        with open(os.path.join(HERE, fname), "rb") as src, open(f"{tools}/{fname}", "wb") as dst:
            dst.write(src.read())
    blob = DT.remote_checkpoint_path(ready["plan"]["checkpoint"]["name"], ready["checkpoint"])
    os.makedirs(os.path.dirname(blob))
    for suffix in ("", ".lineage.json"):
        os.symlink(os.path.abspath(ready["checkpoint"]) + suffix, blob + suffix)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    bad = False
    for shard in ready["shards"]:
        DT.REMOTE_RUN = f"{base}/{shard}/run"
        DT.REMOTE_OUT = DT.REMOTE_RUN + "/main"
        r = remote_paths()
        os.makedirs(DT.REMOTE_RUN)
        with open(args.plan, "rb") as src, open(r["plan"], "wb") as dst:
            dst.write(src.read())
        with open(DT.REMOTE_RUN + "/job.sh", "w") as f:
            f.write(job_script(ready["plan_sha"], shard, blob, args.processes or 1))
        code = subprocess.run(["bash", DT.REMOTE_RUN + "/job.sh"], env=env).returncode
        with open(DT.REMOTE_RUN + "/EXIT") as f:
            print(f"shard {shard}: job EXIT {f.read().strip()}, bash returned {code}")
        problems, summary = ACCEPT.shard_problems(DT.REMOTE_OUT, shard, ready["plan"],
                                                  ready["plan_sha"])
        print(f"shard {shard}: " + (f"ACCEPTED in {DT.REMOTE_OUT}\n{ACCEPT.accepted_line(summary)}"
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
                        help="repeatable; required for the registered plan (a stage is "
                             "launched on purpose); otherwise default: every shard")
        sp.add_argument("--processes", type=int, default=None,
                        help="default: the size's vCPUs for run, 1 for rehearse")
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
                HERE, "..", "..", "runs", "search-distill-2026-10-08")),
                help="default: the repository's git-ignored runs/ directory")
            sp.add_argument("--state-root", default=defaults["state_root"])
            sp.add_argument("--torch", default=defaults["torch"])
            sp.add_argument("--numpy", default=defaults["numpy"])
            sp.add_argument("--keep", action="store_true",
                            help="debugging: leave the droplet running (it keeps billing); "
                                 "refused except for the smoke and dev plans")
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
