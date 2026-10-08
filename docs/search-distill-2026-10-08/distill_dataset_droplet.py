#!/usr/bin/env python3
"""Search distillation: run distill_dataset_b1.py on one droplet and fetch the dataset (D445).

The dataset is built where the label tool's arithmetic is reproduced: a droplet
of the label stage's size and image, one game per forward. This script accepts
the shards locally, creates one droplet, uploads the pinned harness, the
plan-bound tools, distill_dataset_b1.py, the checkpoint, the plan and the
shards' records, runs the build, fetches DATASET.json, BUILD_B1.json and the
three split files, checks them and destroys the droplet.

Nothing appears at --out-dir until everything has succeeded. The files are
fetched into OUT.partial. Only after the build exited 0, every split file has
the hash DATASET.json records (no file is deserialised), DATASET.json names the
plan and one engine library for the build, the shards and the droplet, and the
cleanup is verified (the droplet gone, the lifecycle's teardown clean, no ssh
key of this run left), is droplet_build.json written and OUT.partial renamed
to OUT. The stage commands give the downstream tools OUT and nothing else. The
readers themselves take any directory they are handed, so that OUT.partial and
OUT.failedN are never handed to them is the operator's procedure.

The state of a milestone's --out-dir, in this order of precedence:
  REFUSED  OUT.refused exists, or a leftover OUT.partial holds the refusal's
     marker or a fetched build log with a refusal line. A registered check of
     the dataset refused: on the droplet, a
     line of the build's log that starts with one of REFUSAL_LINES (the
     registered tools' own messages: "distill_common.IntegrityError:" from
     the replay, the supports, the classes, the candidates or the 1e-3
     agreement; "not accepted, nothing built" from shard acceptance; "a game
     appears in two shards"), or a fetched DATASET.json that names another
     plan or another engine library. The build's log is fetched into
     OUT.partial before it is read, then the marker is written, then
     DATASET-REFUSED is printed, and the attempt is kept as OUT.refused, by
     this process or, if it dies, by the next start. What the next start
     can recover is what is in OUT.partial: the marker, or a refusal line in
     the fetched build log, even an incomplete one. It cannot recover a
     refusal that exists only in the run's log (the poll prints the last
     line of the droplet's log before the log is fetched) or, for the two
     refusals that come from the fetched DATASET.json, one whose process was
     killed between that check and the marker: such a leftover is archived
     as a failed attempt. So the operator reads the run's log of a failed
     attempt before any replacement, and a refusal line there stands.
     While a refusal stands this script does not begin an attempt for that
     --out-dir. A refusal and a publication cannot both exist: the script
     does not begin an attempt once either does.
  PUBLISHED  otherwise, OUT exists and holds droplet_build.json (written
     into OUT.partial before the one rename that makes OUT).
  OPEN  otherwise. OUT.failedN, and a leftover OUT.partial without the
     marker, are the failed attempts so far. An attempt begins when
     OUT.partial is made (one mkdir, the last thing this script does before
     the droplet's lifecycle starts). Whatever stops an attempt and is not a
     refusal (setup, an upload, the shim build, a worker or any other failure
     of the build process, a build that stops on a provenance message such as
     another harness commit or checkpoint, a lost connection, the time limit,
     a fetch, a transfer whose bytes do not hash, a cleanup that is not
     verified, a signal, a failure to write the result or to rename, a killed
     process) leaves it a failed attempt. The whole build may be run again
     from the same command; with three failed attempts (two replacements)
     this script does not begin another.

What one invocation reports, by exit code:
  0  it published.
  3  it observed a refusal (as above), or the shards failed acceptance on
     this machine before anything was created (problems returned, or a file
     that cannot be read or parsed; no marker, since nothing ran; it repeats
     on the same directories).
  1  its attempt failed.
  2  it did not begin an attempt and no OUT.partial exists: the arguments,
     the plan or a tool file not the registered one, the export, the
     checkpoint, an --out-dir that is already published, a standing refusal,
     three failed attempts, the account's droplet limit, an interruption
     before OUT.partial. (If this run stops before the droplet's lifecycle
     and an OUT.partial exists, its own or an earlier run's, it exits 1: an
     attempt exists and has not published.)

Not handled: a local filesystem that cannot be written (a full disk, a
permission). The directories above can then be wrong. The run's log decides
in that case, as it does for a refusal the next start could not recover: a
refusal line there is a refusal whatever is on disk.

The droplet's lifecycle calls are the label launcher's (the ones
distill_droplet.run_shard makes): one droplet, its id recorded when the create
is answered, the teardown attempted on every exit path the process survives,
and nothing of any other run or project is touched. As there, a killed
process, a create whose answer is lost or a failed delete can leave a droplet
billing; the message printed then names the recorded id and the command.
--max-hours is a time limit on the work, not a dollar cap: the teardown runs
after it.

  distill_dataset_droplet.py --harness-export X --plan PLAN.json --expect-sha256 H \\
      --shard-dir NAME=DIR [...] --out-dir DIR --max-hours N
"""
import argparse
import json
import math
import os
import secrets
import shlex
import signal
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_accept as A  # noqa: E402
import distill_common as C  # noqa: E402
import distill_droplet as L  # noqa: E402

BUILD_TOOL = "distill_dataset_b1.py"
FETCH = ("DATASET.json", "BUILD_B1.json", "train.pt", "validation.pt", "locked/test.pt")
REFUSAL_LINES = ("distill_common.IntegrityError:", "not accepted, nothing built",
                 "a game appears in two shards")
MAX_ATTEMPTS = 3
MARKER = "REFUSED.txt"


class Refused(Exception):
    """A registered check refused, or the fetched dataset is not the plan's."""


def classify(code, log_text):
    """'ok', 'refused' (a line of the log starts with a registered check's own
    message) or 'failed'."""
    if code == 0:
        return "ok"
    refused = any(line.startswith(REFUSAL_LINES) for line in log_text.splitlines())
    return "refused" if refused else "failed"


def claim_out(out):
    """Check --out-dir before anything is created and return OUT.partial, made.
    OUT must not hold a file (empty directories left by a refused build are
    removed, bottom up); an integrity rejection stands; a leftover partial is
    kept as a failed attempt; three attempts are the limit."""
    out = os.path.abspath(out)
    partial = out + ".partial"
    if leftover_refusal(partial) and not os.path.exists(out + ".refused"):
        os.rename(partial, out + ".refused")      # observed by a runner that then died
    if os.path.exists(out + ".refused"):
        raise SystemExit(f"{out}.refused exists: a build for this directory was refused by a "
                         "registered check. That stands; a new ledger entry decides what follows.")
    if os.path.exists(out):
        for dirpath, _dirs, files in os.walk(out):
            if files:
                raise SystemExit(f"{out} already holds files "
                                 f"({os.path.join(dirpath, files[0])})")
        for dirpath, _dirs, _files in os.walk(out, topdown=False):
            os.rmdir(dirpath)
    if os.path.exists(partial):
        os.rename(partial, next_failed(out))
    attempts = sum(os.path.exists(f"{out}.failed{i}") for i in range(1, MAX_ATTEMPTS + 1))
    if attempts >= MAX_ATTEMPTS:
        raise SystemExit(f"{attempts} attempts have failed for {out} (two replacements are "
                         "used). A new ledger entry decides what follows.")
    os.mkdir(partial)                 # one step: the attempt has begun, or nothing was made
    return partial


def leftover_refusal(partial):
    """True when a leftover OUT.partial shows a refusal: its marker, or a
    fetched build log with a line that starts with a registered refusal."""
    if os.path.exists(os.path.join(partial, MARKER)):
        return True
    try:
        with open(os.path.join(partial, "build_b1.log"), errors="replace") as f:
            return classify(1, f.read()) == "refused"
    except OSError:
        return False


def next_failed(out):
    i = 1
    while os.path.exists(f"{out}.failed{i}"):
        i += 1
    return f"{out}.failed{i}"


def collect(fetch, partial, plan_sha, library_sha256):
    """Fetch the build's files into `partial` and check them. `fetch(name, dest)`
    copies one file or raises. A file whose bytes do not hash to DATASET.json's
    value is a failed transfer; another plan or engine library is a refusal."""
    for fname in FETCH:
        fetch(fname, os.path.join(partial, fname))
    with open(os.path.join(partial, "DATASET.json")) as f:
        meta = json.load(f)
    bad = [s for s, spec in meta["files"].items()
           if C.sha256_file(os.path.join(partial, spec["path"])) != spec["sha256"]]
    if bad:
        raise L.DT.RunnerError(f"the fetched {bad} do not hash to DATASET.json's values")
    if meta.get("plan_sha256") != plan_sha:
        raise Refused(f"DATASET.json names plan {meta.get('plan_sha256')}, not {plan_sha}")
    if meta.get("label_library_sha256") != [library_sha256] or \
            meta.get("library_sha256") != library_sha256:
        raise Refused("the build's engine library, the label shards' and the droplet's are not "
                      f"one: {meta.get('library_sha256')}, {meta.get('label_library_sha256')}, "
                      f"{library_sha256}")
    return meta


def job(plan_sha, blob, shard_names, processes):
    DT = L.DT
    run, py, tools = DT.REMOTE_RUN, DT.REMOTE_PY, L.remote_paths()["tools"]
    shards = " ".join(f"--shard-dir {n}={run}/shards/{n}" for n in shard_names)
    return "\n".join([
        "#!/bin/bash", "set -uo pipefail", f"cd {DT.REMOTE_SRC}",
        "export OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1",
        f"{py} {tools}/{BUILD_TOOL} --harness {DT.REMOTE_SRC} --plan {L.remote_paths()['plan']} "
        f"--expect-sha256 {plan_sha} --checkpoint {shlex.quote(blob)} {shards} "
        f"--out-dir {run}/dataset --processes {int(processes)} > {run}/build_b1.log 2>&1",
        f"echo $? > {run}/EXIT.tmp && mv {run}/EXIT.tmp {run}/EXIT"]) + "\n"


def build_on_droplet(ctx):
    """The droplet's whole life. Returns the result only when the build was
    fetched and checked AND the teardown succeeded; publishes nothing itself."""
    DT = L.DT
    state, api, unique, partial = ctx.state, ctx.api, ctx.unique, ctx.partial
    plan, plan_sha, commit = ctx.plan, ctx.plan_sha, ctx.commit
    lock = state.lock()
    state.write("run-id", ctx.run_id)
    state.write("price-hourly", ctx.price)
    DT.log(f"dataset droplet {unique}: {len(ctx.shard_dirs)} shards, {ctx.processes} forward "
           f"processes at ${ctx.price:.5f}/h, --max-hours {ctx.max_hours} (a time limit: about "
           f"${ctx.max_hours * ctx.price:.2f} of droplet time); state {state.dir}")

    def on_signal(signum, _frame):
        raise DT.Interrupted(f"signal {signum}")
    for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(sig, on_signal)
    clock = L.Clock(ctx.max_hours)
    r = L.remote_paths()
    result = None
    try:
        clock.cap(60, "the ssh key")
        fingerprint = DT.create_key(api, state, unique)
        clock.cap(60, "the create")
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
        L.make_archive(ctx.harness_repo, commit, archive)
        remote.put(archive, f"{DT.REMOTE_ROOT}/src.tar.gz", timeout=clock.cap(600, "upload"))
        remote.run(f"tar -xzf {DT.REMOTE_ROOT}/src.tar.gz -C {DT.REMOTE_SRC} && "
                   f"echo {commit} > {DT.REMOTE_SRC}/SOURCE_COMMIT", timeout=clock.cap(300, "unpack"))
        remote.run(f"mkdir -p {r['tools']}", timeout=clock.cap(60, "mkdir"))
        for fname in tuple(L.TOOL_FILES) + (BUILD_TOOL,):
            remote.put(os.path.join(HERE, fname), f"{r['tools']}/{fname}",
                       timeout=clock.cap(120, "tool upload"))
        ck = plan["checkpoint"]
        blob = DT.remote_checkpoint_path(ck["name"], ctx.checkpoint)
        remote.run(f"mkdir -p {shlex.quote(os.path.dirname(blob))}", timeout=clock.cap(60, "mkdir"))
        remote.put(ctx.checkpoint, blob, timeout=clock.cap(600, "checkpoint upload"))
        remote.put(ctx.checkpoint + ".lineage.json", blob + ".lineage.json",
                   timeout=clock.cap(120, "sidecar upload"))
        remote.put(ctx.plan_path, r["plan"], timeout=clock.cap(120, "plan upload"))
        for name, directory in ctx.shard_dirs.items():
            remote.run(f"mkdir -p {DT.REMOTE_RUN}/shards/{name}", timeout=clock.cap(60, "mkdir"))
            for fname in L.RESULT_FILES:
                remote.put(os.path.join(directory, fname),
                           f"{DT.REMOTE_RUN}/shards/{name}/{fname}",
                           timeout=clock.cap(1800, "shard upload"))
        built = remote.script(DT.build_script(commit), "build.log",
                              timeout=clock.cap(900, "the shim build"))
        machine = json.loads([l for l in built.stdout.splitlines() if l.startswith("{")][-1])
        DT.log(f"shim built: {machine['cpu_model']}, {machine['nproc']} cores, library "
               f"{machine['library_sha256'][:12]}")
        remote.run(f"cat > {DT.REMOTE_RUN}/job.sh",
                   stdin_text=job(plan_sha, blob, list(ctx.shard_dirs), ctx.processes),
                   timeout=clock.cap(60, "job upload"))
        remote.run(f"nohup setsid bash {DT.REMOTE_RUN}/job.sh > {DT.REMOTE_RUN}/job.log 2>&1 "
                   f"< /dev/null & echo started", timeout=clock.cap(60, "launch"))
        started, code = time.time(), None
        while code is None:
            if clock.left() <= 1:
                raise DT.RunnerError("--max-hours reached while the build ran")
            try:
                got = remote.run(
                    f"cat {DT.REMOTE_RUN}/EXIT 2>/dev/null || echo running; "
                    f"tail -n 1 {DT.REMOTE_RUN}/build_b1.log 2>/dev/null",
                    check=False, timeout=60).stdout.strip().splitlines()
            except Exception as exc:                      # a lost poll is not the end
                got = ["running", f"poll failed: {exc}"]
            DT.log(f"{time.time() - started:.0f} s: {' | '.join(got)[:200]}")
            if got and got[0].strip().isdigit():
                code = int(got[0])
            else:
                time.sleep(ctx.poll_seconds)
        os.makedirs(os.path.join(partial, "locked"), exist_ok=True)
        log_path = os.path.join(partial, "build_b1.log")
        remote.get(f"{DT.REMOTE_RUN}/build_b1.log", log_path,
                   timeout=clock.cap(300, "the log fetch"))
        with open(log_path, errors="replace") as f:
            kind = classify(code, f.read())
        if kind == "refused":
            refuse(ctx, f"the build exited {code} on the droplet and its log names a "
                        f"registered check's refusal ({log_path})")
        if kind == "failed":
            raise DT.RunnerError(f"the build exited {code} on the droplet for a reason that is "
                                 f"not a registered check's refusal; its log is {log_path}")
        try:
            meta = collect(lambda name, dest: remote.get(f"{DT.REMOTE_RUN}/dataset/{name}", dest,
                                                         timeout=clock.cap(3600, "the fetch")),
                           partial, plan_sha, machine["library_sha256"])
        except Refused as exc:
            refuse(ctx, str(exc))
        result = {"schema": "distill-dataset-droplet-v1", "name": unique, "run_id": ctx.run_id,
                  "droplet_id": droplet_id, "droplet_name": DT.droplet_name(unique),
                  "size": DT.DEFAULT_SIZE, "region": DT.DEFAULT_REGION,
                  "price_hourly": ctx.price, "machine": machine, "processes": ctx.processes,
                  "plan_sha256": plan_sha, "commit": commit, "shards": sorted(ctx.shard_dirs),
                  "tool_sha256": C.sha256_file(os.path.join(HERE, BUILD_TOOL)),
                  "launcher_sha256": C.sha256_file(os.path.abspath(__file__)),
                  "files": meta["files"],
                  "max_a0_logprob_difference": meta["max_a0_logprob_difference"],
                  "logprob_tolerance": meta["logprob_tolerance"],
                  "build_seconds": round(time.time() - started, 1)}
    finally:
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
            signal.signal(sig, signal.SIG_IGN)
        public_key = state.read("key.pub")
        try:
            clean = DT.teardown(api, state, unique)
            L.reconcile(api, unique, public_key)
            verify_clean(api, unique, public_key, clean)
        except BaseException:
            print(f"TEARDOWN FAILED: droplet id {state.read('droplet-id')} (state {state.dir}) may "
                  f"STILL BE BILLING. Run: python {ctx.export}/{L.LIFECYCLE} --env-file "
                  f"{DT.DEFAULT_ENV_FILE} destroy --name {unique}. Nothing is published; no "
                  "other droplet is created before this one is verified gone.",
                  file=sys.stderr, flush=True)
            raise
    result["cost"] = float(state.read("cost") or 0.0)
    result["lifetime_seconds"] = round(time.time() - clock.start, 1)
    del lock
    return result


def verify_clean(api, unique, public_key, clean):
    """The cleanup is verified, or this raises: the lifecycle's teardown said
    clean (the droplet and the key verified gone), and after the reconcile no
    ssh key of this run's name is listed. (reconcile has already raised if a
    droplet of this name is still listed.)"""
    DT = L.DT
    if clean is not True:
        raise DT.RunnerError("the teardown did not verify that everything of this run is gone")
    wanted = DT.droplet_name(unique)
    left = [k.get("id") for k in L.list_all(api, "/account/keys", "ssh_keys")
            if k.get("name") == wanted]
    if left:
        raise DT.RunnerError(f"ssh key(s) named {wanted} are still listed: {left}")


def refuse(ctx, reason):
    """An integrity rejection, recorded so that a later failure cannot hide it:
    in this process's context, as a marker file in OUT.partial, and in the
    run's log. Then raise."""
    ctx.refused = True
    try:
        with open(os.path.join(ctx.partial, MARKER), "w") as f:
            f.write(reason + "\n")
    except OSError as exc:
        say(f"the refusal's marker could not be written ({exc!r}); the refusal stands")
    say(f"DATASET-REFUSED: {reason}")
    raise Refused(reason)


def accept_shards(plan, plan_sha, shard_dirs):
    """Shard acceptance on this machine. Returns the summaries, or raises
    Refused: for problems the acceptance returns and for a shard file that
    cannot be read or parsed alike."""
    try:
        problems, summaries = A.accept(plan, plan_sha, shard_dirs)
    except Exception as exc:
        raise Refused(f"the shards could not be read as accepted records: {exc!r}")
    if problems:
        raise Refused("the shards are not accepted:\n  " + "\n  ".join(problems))
    return summaries


def attempt(ctx):
    """One attempt, from an OUT.partial that claim_out has just made.
    0: published at ctx.out. 3: refused. 1: failed. What is on disk decides."""
    out, partial = ctx.out, ctx.partial
    try:
        result = build_on_droplet(ctx)
        with open(os.path.join(partial, "droplet_build.json"), "w") as f:
            json.dump(result, f, indent=1)
        os.rename(partial, out)                  # the one step that publishes
    except BaseException as exc:
        if os.path.exists(os.path.join(out, "droplet_build.json")) and \
                not os.path.exists(partial):
            return 0                             # the rename happened: published
        refused = getattr(ctx, "refused", False) or leftover_refusal(partial)
        kept = out + ".refused" if refused else next_failed(out)
        try:
            os.rename(partial, kept)
        except OSError as move:
            kept = f"{partial} (it could not be moved to {kept}: {move!r}; the next start does it)"
        say(("REFUSED (the dataset is NOT ACCEPTED" if refused else "FAILED (nothing is published")
            + f"; kept as {kept}): {exc!r}")
        return 3 if refused else 1
    say(f"DATASET-FETCHED {out}: " + "; ".join(
        f"{s}: {spec['examples']} loss decisions, {spec['labels']} labels"
        for s, spec in result["files"].items())
        + f"; largest a0 log-probability difference {result['max_a0_logprob_difference']:.2e} "
          f"(tolerance {result['logprob_tolerance']:g}); cost about ${result['cost']:.3f}")
    return 0


def say(message):
    """A report line, to both streams (the launcher's log holds both). A stream
    that cannot be written changes no outcome."""
    for stream in (sys.stderr, sys.stdout):
        try:
            print(message, file=stream, flush=True)
        except Exception:
            pass


def preflight(a):
    """Everything before a droplet exists. Returns the attempt's context, or
    raises SystemExit / RunnerError (exit 2), or Refused (exit 3: the shards)."""
    with open(a.plan) as f:
        lifecycle = json.load(f)["lifecycle_sha256"][L.LIFECYCLE]
    L.load_dt(a.harness_export, lifecycle)
    DT = L.DT
    out = os.path.abspath(a.out_dir)
    shard_dirs = dict(item.split("=", 1) for item in a.shard_dir)
    # The launcher's offline checks: plan hash, the six tool files, export, lifecycle, checkpoint.
    ready = L.prepare(argparse.Namespace(
        plan=a.plan, expect_sha256=a.expect_sha256, harness_export=a.harness_export,
        harness_repo=a.harness_repo, checkpoint_store=a.checkpoint_store,
        shard=[sorted(shard_dirs)[0]], name="dsb1",
        out_root=os.path.join(out + ".launcher-check"), keep=False))
    summaries = accept_shards(ready["plan"], ready["plan_sha"], shard_dirs)
    api = DT.Api(DT.read_token(env_file=DT.DEFAULT_ENV_FILE))
    size = DT.pick_size(api.get("/sizes?per_page=200")["sizes"], DT.DEFAULT_SIZE,
                        DT.DEFAULT_REGION, DT.MAX_HOURLY_DEFAULT)
    run_id = secrets.token_hex(3)
    unique = DT.validate_name(f"dsb1-{run_id}")
    limit = int(api.get("/account")["account"]["droplet_limit"])
    existing = len(L.list_all(api, "/droplets", "droplets"))
    refusal = DT.limit_refusal(existing, limit) or L.account_refusal(api, unique)
    if refusal:
        raise SystemExit(f"{refusal}. Nothing was created and nothing is deleted to make room; "
                         "this is not an attempt.")
    state = DT.State(unique, root=DT.STATE_ROOT)
    if os.path.exists(state.dir):
        raise SystemExit(f"{state.dir} exists")
    for summary in summaries:
        DT.log(A.accepted_line(summary))
    # claim_out is last: an attempt begins when OUT.partial exists.
    return argparse.Namespace(
        api=api, state=state, unique=unique, run_id=run_id, price=float(size["price_hourly"]),
        processes=max(1, int(size["vcpus"]) - 1),      # the parent replays the engine
        plan=ready["plan"], plan_sha=ready["plan_sha"], commit=ready["commit"],
        checkpoint=ready["checkpoint"], export=ready["export"], plan_path=os.path.abspath(a.plan),
        harness_repo=a.harness_repo, shard_dirs=shard_dirs, max_hours=a.max_hours,
        out=out, partial=claim_out(out), poll_seconds=60)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness-export", required=True)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--shard-dir", action="append", default=[], metavar="NAME=DIR", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--max-hours", type=float, required=True)
    ap.add_argument("--checkpoint-store", default=os.path.expanduser(
        "~/Code/bb-play-harness/.play-artifacts/checkpoints"))
    ap.add_argument("--harness-repo", default=os.path.expanduser("~/Code/bb-play-harness"))
    a = ap.parse_args(argv)
    try:
        if not (math.isfinite(a.max_hours) and 0.25 <= a.max_hours <= 12):
            raise SystemExit("--max-hours must be between 0.25 and 12")
        ctx = preflight(a)
    except Refused as exc:
        say(f"REFUSED (the dataset is NOT ACCEPTED; nothing was created): {exc}")
        return 3
    except BaseException as exc:                # SystemExit, RunnerError, an interruption, the rest
        partial = os.path.abspath(a.out_dir) + ".partial"
        if os.path.isdir(partial):               # this run's (stopped just after it was made) or an earlier one's
            say(f"FAILED before the droplet's lifecycle: {partial} exists and is counted as an "
                f"attempt at the next start. Nothing was created in the cloud. {exc!r}")
            return 1
        say(f"NOT STARTED (nothing was created; this is not an attempt): {exc!r}")
        return 2
    return attempt(ctx)


if __name__ == "__main__":
    sys.exit(main())
