#!/usr/bin/env python3
"""Offline test of distill_droplet.py's control flow. No network: the
DigitalOcean API, ssh and the harness's lifecycle calls are replaced by fakes
that record what was asked of them. The "droplet" is a finished rehearsal
directory, so the fetch and the acceptance run on real records.

  test_launcher_flow.py --plan PLAN.dev.json --expect-sha256 H \\
      --harness-export EXPORT --rehearsal DIR --shard dev --scratch FRESH_DIR

DIR is the --dir of a `distill_droplet.py rehearse` run of the same plan.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import io
import json
import os
import shutil
import signal
import sys
import time
import types
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import distill_droplet as L  # noqa: E402


class FakeApi:
    """Records every call. `droplets` and `keys` are what the account holds."""

    def __init__(self, droplets=(), keys=()):
        self.droplets, self.keys, self.calls = list(droplets), list(keys), []
        self.retries = 0
        self.page_size = L.PAGE          # what one page of a listing holds

    def get(self, path):
        self.calls.append(("GET", path))
        page = int(path.split("page=")[-1]) if "&page=" in path or "?page=" in path else 1
        size = self.page_size
        if path.startswith("/droplets"):
            return {"droplets": list(self.droplets)[(page - 1) * size:page * size]}
        if path.startswith("/account/keys"):
            return {"ssh_keys": list(self.keys)[(page - 1) * size:page * size]}
        if path.startswith("/account"):
            return {"account": {"droplet_limit": 15}}
        if path.startswith("/sizes"):
            return {"sizes": [{"slug": "s-8vcpu-16gb-amd", "available": True, "regions": ["sfo3"],
                               "price_hourly": 0.16667, "vcpus": 8}]}
        raise AssertionError(path)

    def call(self, method, path, body=None):
        self.calls.append((method, path))
        if method == "DELETE" and path.startswith("/account/keys/"):
            self.keys = [k for k in self.keys if str(k["id"]) != path.rsplit("/", 1)[1]]
        return 204, {}


# Two different ed25519 public key lines, as ssh-keygen writes them (type, body, comment).
def _key_line(fill, comment):
    blob = b"\x00\x00\x00\x0bssh-ed25519\x00\x00\x00\x20" + fill * 32
    return "ssh-ed25519 " + base64.b64encode(blob).decode() + " " + comment


OUR_PUBLIC_KEY = _key_line(b"A", "ours")
OTHER_PUBLIC_KEY = _key_line(b"B", "theirs")


def install_fakes(DT, events, rehearsal_shard, library, fail_at=None, orphan_key=False,
                  poll_rc=0, jump_at=None, jump=None):
    """Replace the lifecycle's network and ssh steps. Returns {"job": the job
    script the launcher sent}. `library` is the engine library the fake build
    reports. `jump` is called when the step `jump_at` has run (the test's way
    to let time pass inside a phase)."""
    sent = {}

    class Remote:
        def __init__(self, state_dir, ip):
            self.ip = ip

        def _step(self, what, timeout):
            events.append((what, timeout))
            if fail_at == what:
                raise DT.RunnerError(f"injected failure at {what}")
            if jump_at == what:
                jump()

        def run(self, command, check=True, timeout=600, stdin_text=None):
            self._step("run:" + command.split()[0], timeout)
            if command.startswith("cat > ") and command.endswith("/job.sh"):
                sent["job"] = stdin_text
            return types.SimpleNamespace(stdout="started\n", returncode=0)

        def script(self, text, log_name, timeout):
            self._step("script:" + log_name, timeout)
            machine = json.dumps({"cpu_model": "fake", "nproc": 8, "source_commit": "x",
                                  "library_sha256": library})
            return types.SimpleNamespace(stdout=machine + "\nBUILD_OK\n", returncode=0)

        def put(self, local, remote, timeout=1800):
            self._step("put:" + os.path.basename(remote), timeout)

        def get(self, remote, local, check=True, timeout=1800):
            self._step("get:" + os.path.relpath(remote, DT.REMOTE_RUN), timeout)
            if os.path.isfile(remote):
                shutil.copyfile(remote, local)
                return True
            return False

    def create_key(api, state, name):
        events.append(("create_key", name))
        state.write("key.pub", OUR_PUBLIC_KEY)      # the lifecycle writes the key pair first
        if orphan_key:                      # the registration happened, its answer was lost
            api.keys.append({"id": 777, "name": DT.droplet_name(name),
                             "public_key": OUR_PUBLIC_KEY})
            raise DT.RunnerError("POST /account/keys: network error after 1 attempt(s)")
        state.write("key-id", 555)
        api.keys.append({"id": 555, "name": DT.droplet_name(name), "public_key": OUR_PUBLIC_KEY})
        return "fp"

    def create_droplet(api, state, name, region, size, fingerprint):
        events.append(("create_droplet", name))
        state.write("droplet-id", 4242)
        state.write("created-at", 0)
        return 4242

    def teardown(api, state, name):
        events.append(("teardown", name))
        api.keys = [k for k in api.keys if k["id"] != 555]
        return True

    DT.Remote = Remote
    DT.create_key, DT.create_droplet, DT.teardown = create_key, create_droplet, teardown
    DT.wait_active = lambda api, droplet_id, timeout=600: events.append(("wait_active", timeout)) or "10.0.0.1"
    DT.wait_ssh = lambda remote, timeout=300: events.append(("wait_ssh", timeout))
    DT.poll = lambda remote, tasks, deadline, stale: events.append(("poll", deadline)) or poll_rc
    DT.log = lambda msg: None
    DT.REMOTE_RUN = os.path.join(rehearsal_shard, "run")
    DT.REMOTE_OUT = os.path.join(DT.REMOTE_RUN, "main")
    L.make_archive = lambda repo, commit, path: open(path, "wb").close()
    return sent


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", required=True)
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--harness-export", required=True)
    ap.add_argument("--rehearsal", required=True)
    ap.add_argument("--shard", required=True)
    ap.add_argument("--scratch", required=True)
    a = ap.parse_args(argv)
    with open(a.plan) as f:
        plan_obj = json.load(f)
    DT = L.load_dt(a.harness_export, plan_obj["lifecycle_sha256"][L.LIFECYCLE])
    if os.path.exists(a.scratch):
        raise SystemExit(f"{a.scratch} exists; give a fresh directory")
    size = {"price_hourly": 0.16667, "vcpus": 8}
    results = []

    def check(name, ok, detail=""):
        results.append(ok)
        print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))

    def args_for(tag, **over):
        ns = argparse.Namespace(
            name="t", plan=a.plan, expect_sha256=a.expect_sha256, harness_export=a.harness_export,
            harness_repo=os.path.expanduser("~/Code/bb-play-harness"),
            checkpoint_store=os.path.expanduser("~/Code/bb-play-harness/.play-artifacts/checkpoints"),
            shard=[a.shard], processes=None, size="s-8vcpu-16gb-amd", region="sfo3",
            max_hourly=1.0, max_hours=1.0, max_total_usd=1.0, stale_seconds=1800.0,
            out_root=os.path.join(a.scratch, tag, "out"), state_root=os.path.join(a.scratch, tag, "state"),
            torch=DT.TORCH_VERSION, numpy=DT.NUMPY_VERSION, keep=False, dry_run=False,
            assume_hourly=None, run_id=None, child_of=None, env_file="unused")
        for key, value in over.items():
            setattr(ns, key, value)
        return ns

    shard_dir = os.path.join(a.rehearsal, a.shard)
    with open(os.path.join(shard_dir, "run", "main", "COMPLETE.json")) as f:
        library = json.load(f)["library_sha256"]
    records = ("roots.jsonl", "games.jsonl", "other.jsonl", "COMPLETE.json")

    # 1. The whole flow on accepted records.
    events = []
    sent = install_fakes(DT, events, shard_dir, library)
    args = args_for("ok")
    ready = L.prepare(args)
    api = FakeApi()
    result = L.run_shard(args, ready, a.shard, api, size, "abc123")
    names = [e[0] for e in events]
    check("accepted shard: result written, run id and unique names recorded",
          bool(result and result["accepted"] and result["run_id"] == "abc123"
               and result["droplet_name"] == DT.droplet_name(f"t-{a.shard}-abc123")))
    blob_name = os.path.basename(ready["checkpoint"])
    order = ["create_key", "create_droplet", "wait_active", "wait_ssh", "script:setup.log",
             "put:src.tar.gz", "run:tar"] + ["put:" + f for f in L.TOOL_FILES] + \
            ["put:" + blob_name, "put:" + blob_name + ".lineage.json", "put:plan.json",
             "script:build.log", "run:cat", "run:nohup", "poll"] + \
            ["get:main/" + f for f in L.RESULT_FILES] + ["teardown"]
    at = [names.index(n) if n in names else -1 for n in order]
    check("accepted shard: the order of calls (key, create, boot, install, source, the six tool "
          "files, blob, sidecar, plan, build, job, poll, fetch, teardown)",
          -1 not in at and at == sorted(at), str([n for n, i in zip(order, at) if i < 0] or names))
    check("accepted shard: the fetch is the six result files and nothing else",
          [n for n in names if n.startswith("get:")] == ["get:main/" + f for f in L.RESULT_FILES])
    check("accepted shard: teardown ran after the fetch",
          "teardown" in names and names.index("teardown") > max(i for i, n in enumerate(names)
                                                                if n.startswith("get:")))
    check("accepted shard: account was read for a name clash before the key was made",
          api.calls[0][0] == "GET" and names.index("create_key") >= 0
          and [c for c in api.calls if c[0] != "GET"] == [], str(api.calls[:3]))
    timeouts = [t for n, t in events if isinstance(t, (int, float)) and not n == "poll"]
    check("every phase's timeout is within --max-hours less the reserve",
          max(timeouts) <= 3600 - L.TEARDOWN_RESERVE, f"largest {max(timeouts)} s")
    done = os.path.join(ready["out_root"], a.shard)
    check("records landed and droplet_run.json exists",
          os.path.isfile(os.path.join(done, "droplet_run.json"))
          and all(os.path.isfile(os.path.join(done, f)) for f in L.RESULT_FILES)
          and not os.path.exists(done + ".partial"))
    job = sent.get("job") or ""
    remote_blob = DT.remote_checkpoint_path(ready["plan"]["checkpoint"]["name"], ready["checkpoint"])
    check("the job sent: the label tool on this shard, the plan's hash, the uploaded blob, 8 "
          "processes, the lifecycle's output directory, and no library argument",
          f"{L.remote_paths()['tools']}/distill_screen.py run " in job
          and f"--shard {a.shard} " in job and f"--expect-sha256 {a.expect_sha256} " in job
          and f"--checkpoint {remote_blob} " in job and f"--out-dir {DT.REMOTE_OUT} " in job
          and "--processes 8 " in job and "--lib" not in job and ".so" not in job
          and job.rstrip().endswith("finish 0"))

    # 2. Refusals before anything is created.
    for label, api, pre in (
            ("a droplet of the run's name exists",
             FakeApi(droplets=[{"id": 1, "name": DT.droplet_name(f"t-{a.shard}-dup001"), "tags": []}]), None),
            ("an ssh key of the run's name exists",
             FakeApi(keys=[{"id": 2, "name": DT.droplet_name(f"t-{a.shard}-dup001")}]), None),
            ("local state of the run's name exists", FakeApi(), "state")):
        events = []
        install_fakes(DT, events, shard_dir, library)
        args = args_for("refuse-" + label.split()[1])
        ready = L.prepare(args)
        if pre:
            os.makedirs(os.path.join(args.state_root, f"t-{a.shard}-dup001"))
        try:
            L.run_shard(args, ready, a.shard, api, size, "dup001")
            refused = False
        except DT.RunnerError as exc:
            refused = "Nothing was created" in str(exc)
        check(f"refused, nothing created: {label}",
              refused and not events and all(c[0] == "GET" for c in api.calls))

    # 3. A failure in the middle: logs only, bounded, then teardown; no record fetched.
    for tag, fail_at, poll_rc, marker in (("fail", "script:build.log", 0, "script:build.log"),
                                          ("jobfail", None, 3, "poll")):
        events = []
        install_fakes(DT, events, shard_dir, library, fail_at=fail_at, poll_rc=poll_rc)
        args = args_for(tag)
        ready = L.prepare(args)
        api = FakeApi()
        try:
            L.run_shard(args, ready, a.shard, api, size, "fail01")
            failed = False
        except DT.RunnerError:
            failed = True
        names = [e[0] for e in events]
        after = names[names.index(marker) + 1:]
        what = "the build fails" if fail_at else "the job exits 3"
        check(f"failure ({what}): raised, then only log fetches, then teardown",
              failed and after[-1] == "teardown" and len(after) > 1
              and all(n.startswith("get:") or n.startswith("run:tail") for n in after[:-1]),
              str(after))
        check(f"failure ({what}): no record file was fetched",
              not any(n.endswith(records) for n in names)
              and not os.path.exists(os.path.join(ready["out_root"], a.shard))
              and not os.path.exists(os.path.join(ready["out_root"], a.shard) + ".partial"))
        check(f"failure ({what}): each log fetch is capped at 10 s",
              all(t <= 10 for n, t in events[names.index(marker) + 1:-1]))

    # 3b. Records that fail the acceptance: torn down, never renamed into place.
    events = []
    install_fakes(DT, events, shard_dir, "0" * 64)
    args = args_for("otherlib")
    ready = L.prepare(args)
    try:
        L.run_shard(args, ready, a.shard, FakeApi(), size, "lib001")
        message = ""
    except DT.RunnerError as exc:
        message = str(exc)
    names = [e[0] for e in events]
    check("not accepted (the records' engine library is not the one the droplet built): "
          "refused, torn down, no accepted directory",
          "NOT ACCEPTED" in message and "engine library" in message and names[-1] == "teardown"
          and not os.path.exists(os.path.join(ready["out_root"], a.shard)), message[:80])

    # 3c. Records changed after the tool hashed them: the fetched copy is refused.
    changed = os.path.join(a.scratch, "changed-records", a.shard)
    shutil.copytree(os.path.join(shard_dir, "run"), os.path.join(changed, "run"))
    with open(os.path.join(changed, "run", "main", "games.jsonl"), "a") as f:
        f.write("\n")
    events = []
    install_fakes(DT, events, changed, library)
    args = args_for("changed")
    ready = L.prepare(args)
    try:
        L.run_shard(args, ready, a.shard, FakeApi(), size, "chg001")
        message = ""
    except DT.RunnerError as exc:
        message = str(exc)
    names = [e[0] for e in events]
    check("not accepted (a record file changed after its checksum was written): refused, "
          "torn down, no accepted directory",
          "NOT ACCEPTED" in message and "games.jsonl does not hash" in message
          and names[-1] == "teardown"
          and not os.path.exists(os.path.join(ready["out_root"], a.shard)), message[:90])

    # 4. The time limit: with no time left nothing is started and the droplet is torn down.
    events = []
    install_fakes(DT, events, shard_dir, library)
    args = args_for("late", max_hours=(L.TEARDOWN_RESERVE + 0.5) / 3600.0)
    ready = L.prepare(args)
    try:
        L.run_shard(args, ready, a.shard, FakeApi(), size, "late01")
        late = False
    except DT.RunnerError as exc:
        late = "--max-hours is reached" in str(exc)
    names = [e[0] for e in events]
    check("time limit: a phase is refused once the limit less the reserve is reached, teardown runs",
          late and names[-1] == "teardown" and "poll" not in names, str(names))

    # 4b. The limit reached in the middle: the install uses up the budget, so the next
    #     phase is not started; the logs are fetched and the droplet is torn down.
    skew, real_time = [0.0], L.time
    L.time = types.SimpleNamespace(time=lambda: real_time.time() + skew[0],
                                   strftime=real_time.strftime, sleep=real_time.sleep)
    try:
        events = []
        install_fakes(DT, events, shard_dir, library, jump_at="script:setup.log",
                      jump=lambda: skew.__setitem__(0, 3600.0))
        args = args_for("late2")
        ready = L.prepare(args)
        try:
            L.run_shard(args, ready, a.shard, FakeApi(), size, "late02")
            message = ""
        except DT.RunnerError as exc:
            message = str(exc)
    finally:
        L.time = real_time
    names = [e[0] for e in events]
    after = names[names.index("script:setup.log") + 1:] if "script:setup.log" in names else []
    check("time limit in the middle: the phase after the one that used up the budget is not "
          "started; log fetches, then teardown",
          "--max-hours is reached before the source upload" in message
          and "put:src.tar.gz" not in names and after and after[-1] == "teardown"
          and all(n.startswith("get:") or n.startswith("run:tail") for n in after[:-1])
          and not any(n.endswith(records) for n in names), message[:70] + " " + str(after))

    # 5. A key registration whose answer was lost: the run's own key is removed, nothing else.
    events = []
    install_fakes(DT, events, shard_dir, library, orphan_key=True)
    args = args_for("orphan")
    ready = L.prepare(args)
    api = FakeApi(keys=[{"id": 9, "name": "bb-harness-someone-else"}])
    try:
        L.run_shard(args, ready, a.shard, api, size, "orph01")
    except DT.RunnerError:
        pass
    deleted = [c[1] for c in api.calls if c[0] == "DELETE"]
    check("orphan key: this run's key (the public key it generated) is deleted and the other "
          "key is left alone",
          deleted == ["/account/keys/777"] and [k["id"] for k in api.keys] == [9], str(deleted))

    # 5b. Ownership by public key, not by name. After a normal run a key is listed under
    #     the run's exact name with ANOTHER public key (another process made it): it is
    #     reported and left alone. One with this run's public key is deleted. And one with
    #     this run's fingerprint and no public key field is deleted too.
    unique = f"t-{a.shard}-own001"
    wanted = DT.droplet_name(unique)
    ours = L.key_identity(OUR_PUBLIC_KEY)
    api = FakeApi(keys=[{"id": 31, "name": wanted, "public_key": OTHER_PUBLIC_KEY},
                        {"id": 32, "name": wanted, "public_key": OUR_PUBLIC_KEY},
                        {"id": 33, "name": wanted, "fingerprint": ours[1]},
                        {"id": 34, "name": wanted},
                        {"id": 35, "name": "bb-harness-unrelated", "public_key": OUR_PUBLIC_KEY}])
    logged = []
    DT.log = logged.append
    foreign = L.reconcile(api, unique, OUR_PUBLIC_KEY)
    deleted = [c[1] for c in api.calls if c[0] == "DELETE"]
    check("ownership: a key of the run's name with another public key is reported and left "
          "alone; only keys holding this run's public key or fingerprint are deleted",
          deleted == ["/account/keys/32", "/account/keys/33"] and foreign == [31, 34]
          and [k["id"] for k in api.keys] == [31, 34, 35]
          and sum("LEFT ALONE" in m for m in logged) == 2, f"{deleted} {foreign}")
    api = FakeApi(keys=[{"id": 41, "name": wanted, "public_key": OUR_PUBLIC_KEY}])
    foreign = L.reconcile(api, unique, None)
    check("ownership: a run that generated no key deletes no key, whatever its name",
          foreign == [41] and not [c for c in api.calls if c[0] == "DELETE"])
    DT.log = lambda msg: None

    # 5c. Listings are read page by page: a key of the run's name on the third page is
    #     found by the name check and by the cleanup.
    api = FakeApi(keys=[{"id": i, "name": f"bb-harness-filler-{i}"} for i in range(4)]
                  + [{"id": 99, "name": wanted, "public_key": OUR_PUBLIC_KEY}])
    api.page_size = 2
    real_page, L.PAGE = L.PAGE, 2
    try:
        refusal = L.account_refusal(api, unique)
        pages = [c[1] for c in api.calls if c[1].startswith("/account/keys")]
        L.reconcile(api, unique, OUR_PUBLIC_KEY)
    finally:
        L.PAGE = real_page
    check("pagination: the key listing is read to its last page",
          "already has an ssh key" in (refusal or "") and len(pages) == 3
          and ("DELETE", "/account/keys/99") in api.calls, str(pages))

    # 6. The spend guard, the estimate and the argument checks.
    check("guard: NaN, inf, zero and negative limits are refused",
          all(L.guard_refusal(1, h, p, m) for h, p, m in (
              (float("nan"), 0.2, 1), (1, float("nan"), 1), (1, 0.2, float("nan")),
              (float("inf"), 0.2, 1), (0, 0.2, 1), (1, 0.2, -1))))
    check("guard: the total over all shards is what is compared",
          L.guard_refusal(5, 3.5, 0.16667, 2.9) is not None
          and L.guard_refusal(5, 3.5, 0.16667, 3.0) is None)
    check("guard: --max-hours below the reserve is refused", L.guard_refusal(1, 0.1, 0.2, 1) is not None)
    bad = 0
    for text in ("nan", "inf", "0", "-1"):
        try:
            L.positive(text)
        except argparse.ArgumentTypeError:
            bad += 1
    check("arguments: nan, inf, 0 and -1 are refused by the parser", bad == 4)
    toy = {"estimate": {"droplet_seconds_per_game": 66.3, "setup_seconds": 420}}
    seconds, usd = L.shard_estimate(toy, 1500, 8, 0.16667)
    few, _ = L.shard_estimate(toy, 2, 8, None)
    check("estimate: games x seconds a game / processes + setup, never more processes than games",
          abs(seconds - (420 + 1500 * 66.3 / 8)) < 1e-9 and abs(usd - seconds / 3600 * 0.16667) < 1e-9
          and abs(few - (420 + 66.3)) < 1e-9, f"{seconds:.1f} s, ${usd:.3f}")

    # 7. Cancellation while shards are being started: nothing more is started, every
    #    started child is signalled (the one whose start the signal interrupted too)
    #    and waited for.
    class FakeChild:
        made = []

        def __init__(self, argv, **_kwargs):
            self.shard = argv[argv.index("--shard") + 1]
            self.pid, self.signals, self.waited, self.code = 1000 + len(FakeChild.made), [], False, None
            FakeChild.made.append(self)
            if FakeChild.signal_at == len(FakeChild.made):
                os.kill(os.getpid(), signal.SIGINT)          # arrives before this child is recorded
                for _ in range(200):                         # let the Python-level handler run
                    if FakeChild.made[0].signals or len(FakeChild.made) == 1:
                        break
                    time.sleep(0.005)

        def poll(self):
            return self.code

        def send_signal(self, signum):
            self.signals.append(signum)
            self.code = 130

        def wait(self):
            self.waited = True
            self.code = 0 if self.code is None else self.code
            return self.code

    real_popen = L.subprocess.Popen
    shards3 = ["m1-s1", "m1-s2", "m2-s1"]
    try:
        L.subprocess.Popen = FakeChild
        for signal_at, label in ((2, "a signal during the second start"), (0, "no signal")):
            FakeChild.made, FakeChild.signal_at = [], signal_at
            args = args_for("cancel-" + str(signal_at))
            os.makedirs(args.out_root, exist_ok=True)
            codes = L.run_children(args, {"shards": shards3, "out_root": args.out_root}, "c0ffee")
            started = [c.shard for c in FakeChild.made]
            if signal_at:
                check(f"cancel ({label}): the third shard is never started",
                      started == shards3[:2] and codes[shards3[2]] is None, str(started))
                check(f"cancel ({label}): both started children are signalled and waited for",
                      all(c.signals == [signal.SIGINT] and c.waited for c in FakeChild.made),
                      str([(c.shard, c.signals, c.waited) for c in FakeChild.made]))
                check(f"cancel ({label}): the run does not count as a success",
                      not all(code == 0 for code in codes.values()), str(codes))
            else:
                check(f"cancel ({label}): all three start, none is signalled, all exit 0",
                      started == shards3 and not any(c.signals for c in FakeChild.made)
                      and all(code == 0 for code in codes.values()))
    finally:
        L.subprocess.Popen = real_popen
        signal.signal(signal.SIGINT, signal.default_int_handler)
        signal.signal(signal.SIGTERM, signal.SIG_DFL)
        signal.signal(signal.SIGHUP, signal.SIG_DFL)

    # 8. The cleanup commands carry this invocation's token file and state directory.
    args = args_for("cleanup", env_file="/some/other.env")
    ready = L.prepare(args)
    text = L.cleanup_text(args, ready, "abc123")
    check("cleanup, another --state-root: the token file is named and destroy --id is given "
          "for the recorded id file only (no id from a listing)",
          "--env-file /some/other.env" in text and "destroy --id $(cat" in text
          and "destroy --name t-" not in text and "<DROPLET_ID>" not in text
          and "ids are in the status listing" not in text
          and "Do not destroy a listed droplet by id on a guess" in text,
          text.splitlines()[3][:120])
    args = args_for("cleanup2", state_root=DT.STATE_ROOT)
    ready = L.prepare(args)
    text = L.cleanup_text(args, ready, "abc123")
    check("cleanup, the default state directory: destroy --name with the run's unique name, "
          "and no destroy by an id from a listing",
          f"destroy --name t-{a.shard}-abc123" in text
          and f"--env-file {os.path.abspath('unused')}" in text and "destroy --id" not in text)

    # 9. The hash bindings: the plan, the launcher, a tool file, the blob and its sidecar.
    def refusal_of(args):
        try:
            L.prepare(args)
            return ""
        except DT.RunnerError as exc:
            return str(exc)

    def altered_plan(tag, change):
        """A copy of the plan with one field changed, and that copy's own sha256."""
        plan = json.loads(json.dumps(plan_obj))
        change(plan)
        directory = os.path.join(a.scratch, "plans")
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"PLAN.{tag}.json")
        text = json.dumps(plan, indent=1) + "\n"
        with open(path, "w") as f:
            f.write(text)
        return {"plan": path, "expect_sha256": hashlib.sha256(text.encode()).hexdigest()}

    check("an unaltered copy of the plan is not refused (the control for the next six)",
          refusal_of(args_for("same")) == "")
    message = refusal_of(args_for("badhash", expect_sha256="0" * 64))
    check("a wrong plan hash is refused", "not to --expect-sha256" in message, message[-60:])
    for tag, label, change, phrase in (
            ("launcher", "a launcher whose hash is not the plan's",
             lambda p: p["launcher_sha256"].update({L.LAUNCHER: "0" * 64}),
             "is not the file the plan names (launcher_sha256)"),
            ("nolauncher", "a plan written before the launcher existed (a null hash)",
             lambda p: p["launcher_sha256"].update({L.LAUNCHER: None}),
             "written before the launcher existed"),
            ("tool", "a tool file whose hash is not the plan's",
             lambda p: p["tool_sha256"].update({"distill_eval.py": "0" * 64}),
             "these tool files are not the ones the plan names: ['distill_eval.py']"),
            ("blob", "a checkpoint blob whose hash is not the plan's",
             lambda p: p["checkpoint"].update({"sha256": "0" * 64}),
             "is not the plan's " + plan_obj["checkpoint"]["name"]),
            ("sidecar", "a lineage sidecar whose hash is not the plan's",
             lambda p: p["checkpoint"].update({"sidecar_sha256": "0" * 64}),
             "is not the plan's lineage sidecar"),
            ("lifecycle", "an export whose lifecycle file is not the plan's",
             lambda p: p["lifecycle_sha256"].update({L.LIFECYCLE: "0" * 64}),
             f"the export's {L.LIFECYCLE} is not the file the plan names")):
        message = refusal_of(args_for("alt-" + tag, **altered_plan(tag, change)))
        check(f"refused before anything is created: {label}", phrase in message, message[:100])

    # 9b. --keep and the default to every shard, by plan. A copy of the plan under the
    #     registered plan's name: --keep is refused, and so is a launch that names no
    #     shard. Under the dev plan's own name both are allowed.
    registered = altered_plan("registered-name",
                              lambda p: p.update({"name": L.REGISTERED_PLAN}))
    message = refusal_of(args_for("keep-reg", keep=True, **registered))
    check("refused: --keep under the registered plan", "--keep leaves a droplet billing" in message
          and "Nothing was created" in message, message[:90])
    message = refusal_of(args_for("noshard-reg", shard=None, **registered))
    check("refused: the registered plan with no --shard named",
          "name the shards with --shard" in message and "m1-s1" in message, message[:90])
    check("the registered plan with its shard named and no --keep is not refused",
          refusal_of(args_for("ok-reg", **registered)) == "")
    for other in ("search-distill-m0", "search-distill-rehearsal"):
        message = refusal_of(args_for("keep-" + other, keep=True, **altered_plan(
            "name-" + other, lambda p, other=other: p.update({"name": other}))))
        check(f"refused: --keep under the plan {other}", "--keep leaves" in message)
    check("--keep under the dev plan is allowed (dev and smoke only)",
          refusal_of(args_for("keep-dev", keep=True)) == "")

    # 10. The output directory: a directory that is not this launcher's is refused.
    args = args_for("foreign")
    os.makedirs(os.path.join(args.out_root, "t"))
    message = refusal_of(args)
    check("refused: OUT_ROOT/NAME exists and is not a run directory of this launcher",
          "no CLEANUP.txt" in message, message[-60:])
    with open(os.path.join(args.out_root, "t", "CLEANUP.txt"), "w") as f:
        f.write("an earlier run under this name\n")
    check("a run directory of this launcher (it has CLEANUP.txt) takes another shard",
          refusal_of(args) == "")
    os.makedirs(os.path.join(args.out_root, "t", a.shard + ".failed"))
    check("refused: the shard already has a .failed directory under this name",
          "already exists; pick a new --name" in refusal_of(args))

    # 11. The dry run through main(): no API object, no token read, no socket, no
    #     state or output directory; a wrong plan hash and the spend guard return 1.
    def forbidden(*_args, **_kwargs):
        raise AssertionError("a dry run reached the network or the token")

    real = (DT.Api, DT.read_token, urllib.request.urlopen)
    DT.Api, DT.read_token, urllib.request.urlopen = forbidden, forbidden, forbidden
    try:
        root = os.path.join(a.scratch, "dry")
        argv = ["--env-file", "/nonexistent.env", "run", "--name", "dry", "--plan", a.plan,
                "--expect-sha256", a.expect_sha256, "--harness-export", a.harness_export,
                "--shard", a.shard, "--max-hours", "0.5", "--max-total-usd", "0.2",
                "--out-root", os.path.join(root, "out"), "--state-root", os.path.join(root, "state"),
                "--dry-run", "--assume-hourly", "0.16667"]
        codes, texts = [], []
        for change in ({}, {"--expect-sha256": "0" * 64}, {"--max-total-usd": "0.05"}):
            this = list(argv)
            for flag, value in change.items():
                this[this.index(flag) + 1] = value
            out, err = io.StringIO(), io.StringIO()
            try:
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    codes.append(L.main(this))
            except AssertionError as exc:
                codes.append(str(exc))
            texts.append(out.getvalue() + err.getvalue())
        check("dry run: returns 0, prints the job and the cleanup commands, touches no API, "
              "token or socket and creates no directory",
              codes[0] == 0 and "distill_screen.py run" in texts[0] and "destroy --id" in texts[0]
              and not os.path.exists(root), str(codes[0]))
        check("dry run: a wrong plan hash returns 1", codes[1] == 1
              and "not to --expect-sha256" in texts[1], str(codes[1]))
        check("dry run: the spend guard returns 1 and says nothing was created",
              codes[2] == 1 and "Nothing was created" in texts[2] and not os.path.exists(root),
              str(codes[2]))
    finally:
        DT.Api, DT.read_token, urllib.request.urlopen = real
    print(f"{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
