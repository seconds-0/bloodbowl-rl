#!/usr/bin/env python3
"""Offline test of endturn_droplet.py's control flow. No network: the
DigitalOcean API, ssh and the harness's lifecycle calls are replaced by fakes
that record what was asked of them. The "droplet" is a finished rehearsal
directory, so the fetch and the acceptance run on real records.

  test_launcher_flow.py --plan PLAN.smoke.json --expect-sha256 H \\
      --harness-export EXPORT --rehearsal DIR --shard chain55 --scratch FRESH_DIR

DIR is the --dir of an `endturn_droplet.py rehearse` run of the same plan.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.dont_write_bytecode = True
import endturn_droplet as L  # noqa: E402


class FakeApi:
    """Records every call. `droplets` and `keys` are what the account holds."""

    def __init__(self, droplets=(), keys=()):
        self.droplets, self.keys, self.calls = list(droplets), list(keys), []
        self.retries = 0

    def get(self, path):
        self.calls.append(("GET", path))
        if path.startswith("/droplets"):
            return {"droplets": list(self.droplets)}
        if path.startswith("/account/keys"):
            return {"ssh_keys": list(self.keys)}
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


def install_fakes(DT, events, rehearsal_shard, fail_at=None, orphan_key=False):
    """Replace the lifecycle's network and ssh steps. Returns the fake Remote class."""

    class Remote:
        def __init__(self, state_dir, ip):
            self.ip = ip

        def _step(self, what, timeout):
            events.append((what, timeout))
            if fail_at == what:
                raise DT.RunnerError(f"injected failure at {what}")

        def run(self, command, check=True, timeout=600, stdin_text=None):
            self._step("run:" + command.split()[0], timeout)
            return types.SimpleNamespace(stdout="started\n", returncode=0)

        def script(self, text, log_name, timeout):
            self._step("script:" + log_name, timeout)
            machine = json.dumps({"cpu_model": "fake", "nproc": 8, "source_commit": "x"})
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
        if orphan_key:                      # the registration happened, its answer was lost
            api.keys.append({"id": 777, "name": DT.droplet_name(name)})
            raise DT.RunnerError("POST /account/keys: network error after 1 attempt(s)")
        state.write("key-id", 555)
        api.keys.append({"id": 555, "name": DT.droplet_name(name)})
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
    DT.poll = lambda remote, tasks, deadline, stale: events.append(("poll", deadline)) or 0
    DT.log = lambda msg: None
    DT.REMOTE_RUN = os.path.join(rehearsal_shard, "run")
    DT.REMOTE_OUT = os.path.join(DT.REMOTE_RUN, "main")
    L.make_archive = lambda repo, commit, path: open(path, "wb").close()
    return Remote


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
        lifecycle = json.load(f)["lifecycle_sha256"][L.LIFECYCLE]
    DT = L.load_dt(a.harness_export, lifecycle)
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

    # 1. The whole flow on accepted records.
    events = []
    install_fakes(DT, events, shard_dir)
    args = args_for("ok")
    ready = L.prepare(args)
    api = FakeApi()
    result = L.run_shard(args, ready, a.shard, api, size, "abc123")
    names = [e[0] for e in events]
    check("accepted shard: result written, run id and unique names recorded",
          bool(result and result["accepted"] and result["run_id"] == "abc123"
               and result["droplet_name"] == DT.droplet_name(f"t-{a.shard}-abc123")))
    check("accepted shard: teardown ran after the fetch",
          "teardown" in names and names.index("teardown") > max(i for i, n in enumerate(names)
                                                                if n.startswith("get:")))
    check("accepted shard: account was read for a name clash before the key was made",
          api.calls[0][0] == "GET" and names.index("create_key") >= 0
          and [c for c in api.calls if c[0] != "GET"] == [], str(api.calls[:3]))
    timeouts = [t for n, t in events if isinstance(t, (int, float)) and not n == "poll"]
    check("every phase's timeout is within --max-hours less the reserve",
          max(timeouts) <= 3600 - L.TEARDOWN_RESERVE, f"largest {max(timeouts)} s")
    check("records landed and droplet_run.json exists",
          os.path.isfile(os.path.join(ready["out_root"], a.shard, "droplet_run.json")))

    # 2. Refusals before anything is created.
    for label, api, pre in (
            ("a droplet of the run's name exists",
             FakeApi(droplets=[{"id": 1, "name": DT.droplet_name(f"t-{a.shard}-dup001"), "tags": []}]), None),
            ("an ssh key of the run's name exists",
             FakeApi(keys=[{"id": 2, "name": DT.droplet_name(f"t-{a.shard}-dup001")}]), None),
            ("local state of the run's name exists", FakeApi(), "state")):
        events = []
        install_fakes(DT, events, shard_dir)
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
    events = []
    install_fakes(DT, events, shard_dir, fail_at="script:build.log")
    args = args_for("fail")
    ready = L.prepare(args)
    api = FakeApi()
    try:
        L.run_shard(args, ready, a.shard, api, size, "fail01")
        failed = False
    except DT.RunnerError:
        failed = True
    names = [e[0] for e in events]
    after = names[names.index("script:build.log") + 1:]
    check("failure: raised, then only log fetches, then teardown",
          failed and after[-1] == "teardown"
          and all(n.startswith("get:") or n.startswith("run:tail") for n in after[:-1]), str(after))
    check("failure: no record file was fetched",
          not any(n.endswith(("roots.jsonl", "games.jsonl", "COMPLETE.json")) for n in after))
    check("failure: each log fetch is capped at 10 s",
          all(t <= 10 for n, t in events[names.index("script:build.log") + 1:-1]))

    # 4. The time limit: with no time left nothing is started and the droplet is torn down.
    events = []
    install_fakes(DT, events, shard_dir)
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

    # 5. A key registration whose answer was lost: the run's own key is removed, nothing else.
    events = []
    install_fakes(DT, events, shard_dir, orphan_key=True)
    args = args_for("orphan")
    ready = L.prepare(args)
    api = FakeApi(keys=[{"id": 9, "name": "bb-harness-someone-else"}])
    try:
        L.run_shard(args, ready, a.shard, api, size, "orph01")
    except DT.RunnerError:
        pass
    deleted = [c[1] for c in api.calls if c[0] == "DELETE"]
    check("orphan key: this run's key is deleted and the other key is left alone",
          deleted == ["/account/keys/777"] and [k["id"] for k in api.keys] == [9], str(deleted))

    # 6. The spend guard and the argument checks.
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
    shards3 = ["chain55", "chain58", "chain59"]
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
    check("cleanup, another --state-root: the token file is named and destroy --id is given",
          "--env-file /some/other.env" in text and "destroy --id $(cat" in text
          and "destroy --name t-" not in text, text.splitlines()[3][:120])
    args = args_for("cleanup2", state_root=DT.STATE_ROOT)
    ready = L.prepare(args)
    text = L.cleanup_text(args, ready, "abc123")
    check("cleanup, the default state directory: destroy --name with the run's unique name",
          f"destroy --name t-{a.shard}-abc123" in text
          and f"--env-file {os.path.abspath('unused')}" in text)
    print(f"{sum(results)} of {len(results)} checks passed")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
