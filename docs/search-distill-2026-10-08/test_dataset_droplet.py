#!/usr/bin/env python3
"""Tests of distill_dataset_droplet.py's publication boundary and outcomes (D445).

No droplet and no network: the lifecycle module and the remote are stand-ins,
and the script's own order of work runs for real (fetch into OUT.partial,
classify, check, tear down, verify the cleanup, and only then publish). They
call claim_out, attempt, build_on_droplet, classify, collect and accept_shards,
and main() with preflight() replaced; preflight() itself is not run, the setup
and shim-build scripts are empty strings, and the launcher's reconcile is a
stand-in. No real signal is sent and no process is killed: a killed runner is
represented by the directory it would leave. The "remote" build is a
dataset that test_dataset_b1.py built from dev shards (--fixture: its
clean-parallel directory). No split file is deserialised.

  test_dataset_droplet.py --fixture DIR --scratch FRESH_DIR
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from types import SimpleNamespace as NS

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_dataset_droplet as M  # noqa: E402

L = M.L
RESULTS = []
SPLITS = ("train.pt", "validation.pt", "locked/test.pt")


def check(name, ok, detail):
    RESULTS.append((name, bool(ok), detail))
    print(("PASS  " if ok else "FAIL  ") + name + ": " + str(detail), flush=True)


class RunnerError(RuntimeError):
    pass


class Interrupted(BaseException):
    pass


class FakeState:
    def __init__(self, directory):
        self.dir, self.values = directory, {"cost": "0.011", "droplet-id": "424242"}
        os.makedirs(directory, exist_ok=True)

    def lock(self):
        return object()

    def write(self, key, value):
        self.values[key] = value

    def read(self, key):
        return self.values.get(key)

    def path(self, key):
        return os.path.join(self.dir, key)


class FakeRemote:
    """The droplet's side: an exit code, a build log, and the dataset directory."""

    def __init__(self, fixture, library, code=0, log="900/900 games replayed\nDATASET ...\n",
                 fail_get=None, corrupt=None):
        self.fixture, self.library, self.code, self.log = fixture, library, code, log
        self.fail_get, self.corrupt, self.fetched = fail_get, corrupt, []

    def run(self, command, check=True, timeout=600, stdin_text=None):
        if "/EXIT" in command:
            return NS(stdout=f"{self.code}\nlast line of the build log\n", returncode=0)
        return NS(stdout="started\n", returncode=0)

    def script(self, text, log_name, timeout):
        return NS(stdout=json.dumps({"cpu_model": "stand-in", "nproc": 8,
                                     "library_sha256": self.library}) + "\n")

    def put(self, local, remote, timeout=1800):
        pass

    def get(self, remote, local, check=True, timeout=1800):
        name = remote.split("/run/", 1)[1]
        if name == "build_b1.log":
            with open(local, "w") as f:
                f.write(self.log)
            return True
        fname = name[len("dataset/"):]
        if fname == self.fail_get:
            raise RunnerError(f"scp from droplet failed: {remote}")
        shutil.copyfile(os.path.join(self.fixture, fname), local)
        if fname == self.corrupt:
            with open(local, "r+b") as f:
                f.seek(100)
                byte = f.read(1)
                f.seek(100)
                f.write(bytes([byte[0] ^ 1]))
        self.fetched.append(fname)
        return True


def install(remote, teardown, keys=(), create=None):
    """Stand-ins for the lifecycle module and the launcher helpers that reach outside."""
    L.DT = NS(
        log=lambda message: None, RunnerError=RunnerError, Interrupted=Interrupted,
        create_key=lambda api, state, unique: "fingerprint",
        create_droplet=create or (lambda api, state, unique, region, size, fingerprint: 424242),
        wait_active=lambda api, droplet_id, timeout=600: "192.0.2.1",
        Remote=lambda state_dir, ip: remote, wait_ssh=lambda r, timeout=300: None,
        setup_script=lambda torch, numpy: "", build_script=lambda commit: "",
        TORCH_VERSION="t", NUMPY_VERSION="n", REMOTE_ROOT="/srv/bb", REMOTE_SRC="/srv/bb/src",
        REMOTE_RUN="/srv/bb/run", REMOTE_PY="/srv/bb/venv/bin/python",
        remote_checkpoint_path=lambda name, local: "/srv/bb/checkpoints/x.bin",
        teardown=teardown, DEFAULT_REGION="r", DEFAULT_SIZE="s", DEFAULT_ENV_FILE="env",
        droplet_name=lambda unique: "bb-harness-" + unique)
    L.make_archive = lambda repo, commit, path: None
    L.reconcile = lambda api, unique, public_key: []
    L.list_all = lambda api, path, key: list(keys)


def context(scratch, tag, plan_sha, out=None):
    out = out or os.path.join(scratch, tag, "dataset")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    return NS(api=None, state=FakeState(os.path.join(scratch, tag, f"state-{len(os.listdir(os.path.dirname(out)))}")),
              unique="dsb1-test", run_id="test", price=0.1, processes=3,
              plan={"checkpoint": {"name": "chain55"}}, plan_sha=plan_sha, commit="c0ffee",
              checkpoint="/nowhere/blob.bin", export="/nowhere", plan_path="/nowhere/plan.json",
              harness_repo="/nowhere", shard_dirs={"dev-s1": "/nowhere/s1"}, max_hours=1.0,
              out=out, partial=M.claim_out(out), poll_seconds=0)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fixture", required=True)
    ap.add_argument("--scratch", required=True, help="a directory that does not exist yet")
    args = ap.parse_args(argv)
    if os.path.exists(args.scratch):
        raise SystemExit(f"{args.scratch} exists; choose a fresh --scratch")
    os.makedirs(args.scratch)
    fixture, scratch = os.path.abspath(args.fixture), os.path.abspath(args.scratch)
    with open(os.path.join(fixture, "DATASET.json")) as f:
        meta = json.load(f)
    plan_sha, library = meta["plan_sha256"], meta["library_sha256"]

    check("classify: exit 0 is ok", M.classify(0, "anything") == "ok", "")
    check("classify: a registered check's refusal",
          M.classify(1, "Traceback ...\ndistill_common.IntegrityError: game 9 step 49: a0's "
                        "log-probability differs by 0.002") == "refused"
          and M.classify(1, "not accepted, nothing built:\n  dev-s1: ...") == "refused", "")
    check("classify: any other failure is not a refusal",
          M.classify(1, "Traceback ...\nMemoryError") == "failed"
          and M.classify(137, "") == "failed"
          and M.classify(1, "multiprocessing.pool.MaybeEncodingError: ...") == "failed", "")
    check("classify: the marks count only at the start of a line (a mention inside another "
          "line, or a provenance message, is a failure); two shards holding one game is a refusal",
          M.classify(1, "RuntimeError: while handling IntegrityError: something else") == "failed"
          and M.classify(1, "the harness export is at abc, the plan pins def") == "failed"
          and M.classify(1, "a game appears in two shards") == "refused", "")

    events = []

    def run(tag, plan=plan_sha, teardown_fails=False, out=None, clean=True, keys=(), create=None,
            before_publish=None, **remote_args):
        remote = FakeRemote(fixture, remote_args.pop("library", library), **remote_args)
        ctx = context(scratch, tag, plan, out)

        def teardown(api, state, unique):
            events.append((tag, "teardown", os.path.exists(ctx.out)))
            if teardown_fails:
                raise RunnerError("delete droplet 424242: HTTP 500")
            if before_publish:
                before_publish(ctx)
            return clean
        install(remote, teardown, keys, create)
        code = M.attempt(ctx)
        return code, ctx.out, remote

    def files(directory):
        return sorted(os.path.relpath(os.path.join(d, f), directory)
                      for d, _s, fs in os.walk(directory) for f in fs)

    code, out, remote = run("happy")
    with open(os.path.join(out, "droplet_build.json")) as f:
        built = json.load(f)
    check("success: published only after the teardown, with every file and the build record",
          code == 0 and events[-1] == ("happy", "teardown", False)
          and files(out) == sorted(M.FETCH + ("build_b1.log", "droplet_build.json"))
          and not os.path.exists(out + ".partial") and built["files"] == meta["files"]
          and built["plan_sha256"] == plan_sha and built["cost"] == 0.011,
          files(out))

    code, out, remote = run("teardown-fails", teardown_fails=True)
    check("a failed teardown after a complete, checked fetch: nothing is published (exit 1, "
          "kept as a failed attempt)",
          code == 1 and not os.path.exists(out) and not os.path.exists(out + ".partial")
          and all(os.path.exists(os.path.join(out + ".failed1", s)) for s in SPLITS),
          os.listdir(os.path.dirname(out)))

    code, out, remote = run("fetch-fails", fail_get="locked/test.pt")
    check("a fetch that fails after train and validation arrived: nothing is published "
          "(exit 1), so no downstream tool finds a dataset",
          code == 1 and not os.path.exists(out) and remote.fetched[-2:] == ["train.pt",
                                                                             "validation.pt"]
          and os.path.exists(os.path.join(out + ".failed1", "train.pt")),
          os.listdir(os.path.dirname(out)))

    code, out, remote = run("corrupt", corrupt="train.pt")
    check("a split file whose bytes do not hash to DATASET.json's value: a failed transfer "
          "(exit 1), nothing published", code == 1 and not os.path.exists(out)
          and os.path.exists(out + ".failed1"), os.listdir(os.path.dirname(out)))

    code, out, remote = run("build-crash", code=1, log="Traceback ...\nMemoryError\n")
    check("the build exits non-zero without a registered check's message: failed (exit 1), "
          "no split fetched", code == 1 and not os.path.exists(out) and remote.fetched == []
          and os.path.exists(out + ".failed1"), os.listdir(os.path.dirname(out)))

    refusal = ("Traceback ...\ndistill_common.IntegrityError: game 162 step 929: a0's "
               "log-probability differs by 0.0011378710230394162\n")
    code, out, remote = run("refused", code=1, log=refusal)
    again = None
    try:
        M.claim_out(out)
    except SystemExit as exc:
        again = str(exc)
    check("a registered check refuses on the droplet: REFUSED (exit 3), kept as OUT.refused "
          "with its reason, no split fetched, and the script will not run again for it",
          code == 3 and not os.path.exists(out) and remote.fetched == []
          and os.path.exists(os.path.join(out + ".refused", M.MARKER))
          and again is not None and "That stands" in again, again)

    code, out, remote = run("refused-and-teardown-fails", code=1, log=refusal,
                            teardown_fails=True)
    check("a refusal followed by a failed teardown is still a refusal (exit 3)",
          code == 3 and os.path.exists(out + ".refused") and not os.path.exists(out),
          os.listdir(os.path.dirname(out)))

    code, out, remote = run("other-plan", plan="0" * 64)
    check("DATASET.json names another plan: REFUSED (exit 3), nothing published",
          code == 3 and not os.path.exists(out) and os.path.exists(out + ".refused"),
          os.listdir(os.path.dirname(out)))

    code, out, remote = run("other-library", library="f" * 64)
    check("the droplet's engine library is not the dataset's: REFUSED (exit 3), nothing "
          "published", code == 3 and not os.path.exists(out) and os.path.exists(out + ".refused"),
          os.listdir(os.path.dirname(out)))

    code, out, remote = run("teardown-not-clean", clean=False)
    check("a teardown that returns without verifying the cleanup: nothing is published (exit 1)",
          code == 1 and not os.path.exists(out) and os.path.exists(out + ".failed1"),
          os.listdir(os.path.dirname(out)))

    code, out, remote = run("key-left", keys=[{"id": 7, "name": "bb-harness-dsb1-test"}])
    check("an ssh key of this run still listed after the reconcile: nothing is published "
          "(exit 1)", code == 1 and not os.path.exists(out) and os.path.exists(out + ".failed1"),
          os.listdir(os.path.dirname(out)))

    def block(ctx):                      # a file where the directory must go: the rename fails
        with open(ctx.out, "w") as f:
            f.write("in the way\n")
    code, out, remote = run("rename-fails", before_publish=block)
    check("the rename to --out-dir fails after a clean teardown: exit 1, kept as a failed "
          "attempt, no dataset directory at --out-dir",
          code == 1 and os.path.isfile(out) and not os.path.exists(out + ".partial")
          and os.path.exists(os.path.join(out + ".failed1", "DATASET.json")),
          os.listdir(os.path.dirname(out)))

    def interrupted(*_args):
        raise Interrupted("signal 15")
    code, out, remote = run("interrupted", create=interrupted)
    check("an interruption: exit 1, a failed attempt, nothing published",
          code == 1 and not os.path.exists(out) and os.path.exists(out + ".failed1")
          and events[-1][:2] == ("interrupted", "teardown"), os.listdir(os.path.dirname(out)))

    killed = os.path.join(scratch, "killed-after-refusal", "dataset")
    os.makedirs(killed + ".partial")
    with open(os.path.join(killed + ".partial", M.MARKER), "w") as f:
        f.write("the build exited 1 ...\n")
    stands = None
    try:
        M.claim_out(killed)
    except SystemExit as exc:
        stands = str(exc)
    check("a runner killed after it recorded a refusal: the next start keeps it as OUT.refused "
          "and will not run", stands is not None and "That stands" in stands
          and os.path.exists(os.path.join(killed + ".refused", M.MARKER))
          and not os.path.exists(killed + ".partial"), stands)

    died = os.path.join(scratch, "killed-midway", "dataset")
    os.makedirs(died + ".partial")
    with open(os.path.join(died + ".partial", "train.pt"), "w") as f:
        f.write("half a file\n")
    partial = M.claim_out(died)
    check("a runner killed without a refusal: the next start counts its partial as a failed "
          "attempt and starts a new one",
          os.path.exists(os.path.join(died + ".failed1", "train.pt"))
          and os.listdir(partial) == [], os.listdir(os.path.dirname(died)))

    def in_the_way(ctx):                 # a directory where the result file must be written
        os.makedirs(os.path.join(ctx.partial, "droplet_build.json"))
    code, out, remote = run("result-write-fails", before_publish=in_the_way)
    check("the result cannot be written after a clean teardown: exit 1, a failed attempt, "
          "nothing published", code == 1 and not os.path.exists(out)
          and os.path.exists(os.path.join(out + ".failed1", "DATASET.json")),
          os.listdir(os.path.dirname(out)))

    class Broken:
        def write(self, text):
            raise OSError("the stream is closed")

        def flush(self):
            raise OSError("the stream is closed")
    stderr, sys.stderr = sys.stderr, Broken()
    try:
        code, out, remote = run("stream-broken")
    finally:
        sys.stderr = stderr
    check("a report stream that cannot be written after publication: still exit 0, published",
          code == 0 and os.path.exists(os.path.join(out, "droplet_build.json"))
          and not os.path.exists(out + ".partial"), os.listdir(os.path.dirname(out)))

    real_next = M.next_failed
    M.next_failed = lambda o: os.path.join(o + ".no-such-directory", "failed1")
    try:
        code, out, remote = run("cannot-archive", fail_get="train.pt")
    finally:
        M.next_failed = real_next
    left = os.path.exists(out + ".partial")
    M.claim_out(out)
    check("a failed attempt that cannot be moved aside: exit 1, OUT.partial stays, nothing "
          "published, and the next start counts it as the failed attempt",
          code == 1 and left and not os.path.exists(os.path.join(out, "DATASET.json"))
          and os.path.exists(out + ".failed1"), os.listdir(os.path.dirname(out)))

    real_accept = M.A.accept
    said = []
    for label, stand_in in (("problems", lambda *a: (["dev-s1: a record is wrong"], [])),
                            ("unreadable", lambda *a: json.loads("{not json"))):
        M.A.accept = stand_in
        try:
            M.accept_shards({}, "0" * 64, {"dev-s1": "/nowhere"})
            said.append("accepted")
        except M.Refused as exc:
            said.append("refused")
        finally:
            M.A.accept = real_accept
    M.A.accept = lambda *a: ([], ["summary"])
    try:
        fine = M.accept_shards({}, "0" * 64, {"dev-s1": "/nowhere"})
    finally:
        M.A.accept = real_accept
    check("local shard acceptance: problems returned and a file that cannot be parsed are "
          "both refusals; clean shards pass", said == ["refused", "refused"]
          and fine == ["summary"], said)

    argv = ["--harness-export", "x", "--plan", "x", "--expect-sha256", "x", "--shard-dir", "a=b",
            "--out-dir", os.path.join(scratch, "main", "dataset"), "--max-hours", "1"]
    real_preflight = M.preflight
    codes = {}
    for label, error in (("refused", M.Refused("the shards are not accepted")),
                         ("exit", SystemExit("the plan hashes to another value")),
                         ("runner", RunnerError("the account already has 15 droplets")),
                         ("interrupt", KeyboardInterrupt())):
        def raising(a, error=error):
            raise error
        M.preflight = raising
        try:
            codes[label] = M.main(argv)
        finally:
            M.preflight = real_preflight
    codes["hours"] = M.main(argv[:-1] + ["99"])
    nothing_made = not os.path.exists(os.path.join(scratch, "main"))
    main_out = argv[argv.index("--out-dir") + 1]

    def claimed_then_interrupted(a):
        os.makedirs(os.path.dirname(main_out), exist_ok=True)
        M.claim_out(main_out)
        raise KeyboardInterrupt()
    M.preflight = claimed_then_interrupted
    try:
        after_claim = M.main(argv)
    finally:
        M.preflight = real_preflight
    stopped = os.path.isdir(main_out + ".partial")
    M.claim_out(main_out)
    check("main: an interruption just after OUT.partial is made exits 1, not 2, and the next "
          "start counts it as a failed attempt", after_claim == 1 and stopped
          and os.path.isdir(main_out + ".failed1"), after_claim)
    check("main: a refusal before anything is created exits 3; every other stop before "
          "OUT.partial exists (a check, the droplet limit, an interruption, a bad argument) "
          "exits 2 and leaves nothing",
          codes == {"refused": 3, "exit": 2, "runner": 2, "interrupt": 2, "hours": 2}
          and nothing_made, codes)

    ctx_r = context(scratch, "refused-marker-fails", plan_sha)
    install(FakeRemote(fixture, library), lambda api, state, unique: True)

    def refusing(ctx):
        M.refuse(ctx, "a registered check refused")

    def no_marker(path, *rest, **more):  # the marker, and only the marker, cannot be written
        if str(path).endswith(M.MARKER):
            raise OSError(28, "No space left on device")
        return open(path, *rest, **more)
    real_build = M.build_on_droplet
    M.build_on_droplet, M.open = refusing, no_marker
    try:
        code = M.attempt(ctx_r)
    finally:
        M.build_on_droplet = real_build
        del M.open
    check("a refusal whose marker cannot be written is still a refusal, from the process's own "
          "record (exit 3, kept as OUT.refused with no marker file and no log in it)",
          code == 3 and os.path.exists(ctx_r.out + ".refused")
          and os.listdir(ctx_r.out + ".refused") == []
          and not os.path.exists(ctx_r.out + ".failed1") and not os.path.exists(ctx_r.out),
          os.listdir(os.path.dirname(ctx_r.out)))

    logged = os.path.join(scratch, "killed-before-marker", "dataset")
    os.makedirs(logged + ".partial")
    with open(os.path.join(logged + ".partial", "build_b1.log"), "w") as f:
        f.write("128/900 games replayed, 20 s\n" + refusal)
    seen = None
    try:
        M.claim_out(logged)
    except SystemExit as exc:
        seen = str(exc)
    check("a runner killed after the build's log was fetched and before the marker: the next "
          "start reads the log and keeps the refusal", seen is not None and "That stands" in seen
          and os.path.exists(os.path.join(logged + ".refused", "build_b1.log"))
          and not os.path.exists(logged + ".partial"), seen)

    orphan = os.path.join(scratch, "no-such-parent", "deeper", "dataset")
    made = None
    try:
        M.claim_out(orphan)
    except OSError as exc:
        made = repr(exc)
    check("claim_out makes OUT.partial in one step or makes nothing",
          made is not None and not os.path.exists(os.path.join(scratch, "no-such-parent")), made)

    shared = os.path.join(scratch, "attempts", "dataset")
    codes = [run("attempts", out=shared, fail_get="train.pt")[0] for _ in range(3)]
    fourth = None
    try:
        M.claim_out(shared)
    except SystemExit as exc:
        fourth = str(exc)
    check("three failed attempts for one --out-dir, then the script refuses a fourth",
          codes == [1, 1, 1] and fourth is not None and "two replacements" in fourth
          and all(os.path.exists(f"{shared}.failed{i}") for i in (1, 2, 3)), fourth)

    shared = os.path.join(scratch, "retry", "dataset")
    first = run("retry", out=shared, fail_get="validation.pt")[0]
    second, out, remote = run("retry", out=shared)
    check("a failed attempt and then a whole replacement from the same command: published",
          first == 1 and second == 0 and os.path.exists(os.path.join(shared, "DATASET.json"))
          and os.path.exists(shared + ".failed1"), os.listdir(os.path.dirname(shared)))

    leftover = os.path.join(scratch, "leftover", "dataset")
    os.makedirs(os.path.join(leftover, "locked"))
    code, out, remote = run("leftover", out=leftover)
    check("an --out-dir that holds only empty directories (a refused registered build leaves "
          "them) is accepted", code == 0 and os.path.exists(os.path.join(leftover, "train.pt")),
          "")
    taken = None
    try:
        M.claim_out(leftover)
    except SystemExit as exc:
        taken = str(exc)
    check("an --out-dir that already holds files is refused before anything is created",
          taken is not None and "already holds files" in taken, taken)

    passed = sum(ok for _, ok, _ in RESULTS)
    print(f"{passed} of {len(RESULTS)} checks passed")
    with open(os.path.join(scratch, "RESULTS.json"), "w") as f:
        json.dump([{"test": n, "passed": ok, "detail": str(d)} for n, ok, d in RESULTS], f, indent=1)
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
