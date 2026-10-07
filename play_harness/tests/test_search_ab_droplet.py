"""tools/search_ab_droplet.py with the DigitalOcean API, ssh and git all faked.

As in test_droplet_tournament.py, the autouse fixture fails any real urlopen or
subprocess call. The lifecycle tests replace the droplet tool's network-facing
pieces (Api, Remote, create, wait, poll, teardown) and check what this tool
does around them: the spend guard, what is uploaded, what is fetched on
success and on every failure, and that teardown always runs.
"""
import hashlib
import json
import os
import signal
import subprocess
from types import SimpleNamespace

import pytest

from play_harness import tournament as T
from tools import search_ab_droplet as SD

from .test_reward_manifest import FIXTURE, FIXTURE_SHA256
from .test_search_ab import fake, make_plan, write_plan

# The runner imports its two siblings as top-level modules; these are those.
DT, AB = SD.DT, SD.AB
COMMIT = T._git_head()
BLOB = "0000002999975936.bin"


@pytest.fixture(autouse=True)
def no_network(monkeypatch, lib):
    def refuse(*args, **kwargs):
        raise AssertionError(f"network or subprocess use in a unit test: {args[:1]}")
    monkeypatch.setattr(DT.urllib.request, "urlopen", refuse)
    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)
    monkeypatch.setattr(SD.DT, "git", lambda *a: COMMIT if a[0] == "rev-parse" else "")
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP)}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.fixture
def setup(tmp_path):
    """A plan with two shards, the checkpoint it names, and the run arguments."""
    blob = tmp_path / BLOB
    blob.write_bytes(b"checkpoint bytes")
    (tmp_path / (BLOB + ".lineage.json")).write_text("{}")
    plan = make_plan(
        source_commit=COMMIT,
        checkpoint_sha256=hashlib.sha256(b"checkpoint bytes").hexdigest(),
        arms=[{"name": "plain", "delta": None}, {"name": "s10", "delta": 0.1}],
        identity={"arm": "identity", "seeds_per_shard": 2},
        shards=[{"name": "sa", "seed_start": 100, "seed_count": 2},
                {"name": "sb", "seed_start": 200, "seed_count": 2}])
    path, sha = write_plan(tmp_path, plan)
    base = ["run", "--name", "ab", "--plan", path, "--expect-sha256", sha,
            "--checkpoint", str(blob), "--manifest", FIXTURE, "--max-hours", "2",
            "--max-total-usd", "3", "--out-root", str(tmp_path / "out"),
            "--state-root", str(tmp_path / "state")]
    return SimpleNamespace(plan=plan, path=path, sha=sha, blob=str(blob), base=base,
                           tmp=tmp_path, out=tmp_path / "out" / "ab")


# ---- scripts and arguments ----------------------------------------------------------------
def test_the_job_script_plays_the_shard_then_checksums_and_writes_exit_atomically():
    argv = SD.play_argv("f" * 64, "sa", "/srv/bb/checkpoints/a/x.bin", 8)
    script = SD.job_script(argv)
    assert f"{DT.REMOTE_PY} tools/search_ab.py play --plan {SD.REMOTE_PLAN} " \
           f"--expect-sha256 {'f' * 64} --shard sa" in script
    assert f"--manifest {SD.REMOTE_MANIFEST} --processes 8 --out-dir {DT.REMOTE_OUT}" in script
    assert "export OMP_NUM_THREADS=1" in script
    assert f"echo tournament > {DT.REMOTE_RUN}/STAGE" in script        # what DT.poll reads
    assert f"> {DT.REMOTE_RUN}/tournament.log 2>&1 || finish $?" in script
    assert f"test -f {DT.REMOTE_OUT}/COMPLETE.json || finish 3" in script
    assert "sha256sum games.jsonl run.json COMPLETE.json machine.json plan.json > SHA256SUMS" \
        in script
    assert f"EXIT.tmp && mv {DT.REMOTE_RUN}/EXIT.tmp {DT.REMOTE_RUN}/EXIT" in script
    assert script.rstrip().endswith("finish 0")


def test_the_play_arguments_are_accepted_by_the_real_parser():
    argv = SD.play_argv("f" * 64, "sa", "/srv/bb/checkpoints/a/x.bin", 8)
    args = AB.build_parser().parse_args(argv)
    assert (args.plan, args.expect_sha256, args.shard) == (SD.REMOTE_PLAN, "f" * 64, "sa")
    assert (args.processes, args.out_dir, args.manifest) == (8, DT.REMOTE_OUT, SD.REMOTE_MANIFEST)


def test_the_sync_carries_the_tool_and_what_it_imports():
    assert set(DT.SYNC_PATHS) < set(SD.SYNC_PATHS)
    synced = tuple(p.rstrip("/") for p in SD.SYNC_PATHS)
    for name in AB.CODE_FILES:
        assert any(name == p or name.startswith(p + "/") for p in synced), name
    assert SD.run_name("ab", "sa") == "ab-sa"
    with pytest.raises(DT.RunnerError):
        SD.run_name("ab", "x" * 60)


def test_the_spend_guard_counts_every_shard_at_its_full_hours():
    assert SD.total_ceiling(["a", "b", "c"], 2.0, 0.25) == pytest.approx(1.5)
    assert SD.budget_refusal(["a", "b", "c"], 2.0, 0.25, 1.5) is None
    refusal = SD.budget_refusal(["a", "b", "c"], 2.0, 0.25, 1.49)
    assert "3 shard(s) x 2.0 h x $0.25000/h = $1.50" in refusal and "Nothing was created" in refusal


# ---- before any network call ----------------------------------------------------------------
def test_a_dry_run_prints_the_plan_of_action_and_touches_nothing(setup, capsys):
    assert SD.main(setup.base + ["--dry-run"]) == 0
    text = capsys.readouterr().out
    assert "DRY RUN: nothing is created" in text
    assert f"plan test ({setup.sha})" in text and f"commit {COMMIT}" in text
    assert "shard sa: droplet bb-harness-ab-sa, 12 games (identity, plain, s10)" in text
    assert "shard sb: droplet bb-harness-ab-sb, 12 games" in text
    assert f"--expect-sha256 {setup.sha} --shard sa" in text
    assert "tools/search_ab.py" in text and "spend guard: 2 shard(s) x 2.0 h" in text
    assert not os.path.exists(setup.tmp / "out") and not os.path.exists(setup.tmp / "state")
    # With a price, the dry run applies the guard as the real run would.
    assert SD.main(setup.base + ["--dry-run", "--assume-hourly", "0.5"]) == 0
    assert "= $2.00 of $3.0 allowed" in capsys.readouterr().out
    assert SD.main(setup.base + ["--dry-run", "--assume-hourly", "1.0"]) == 1
    assert "above --max-total-usd 3.0" in capsys.readouterr().err
    assert SD.main(setup.base + ["--dry-run", "--shard", "sb"]) == 0
    text = capsys.readouterr().out
    assert "shard sb" in text and "shard sa" not in text


def test_run_refuses_what_does_not_match_the_plan_before_any_network_call(setup, monkeypatch,
                                                                         capsys):
    def refused(extra, needle, replace=None):
        argv = list(setup.base)
        for flag, value in (replace or {}).items():
            argv[argv.index(flag) + 1] = value
        assert SD.main(argv + extra) == 1, extra
        assert needle in capsys.readouterr().err, needle

    refused([], "not the expected", {"--expect-sha256": "0" * 64})
    refused(["--shard", "sc"], "no shard 'sc'")
    refused(["--shard", "sa", "--shard", "sa"], "named twice")
    assert SD.main([a if a != "ab" else "Bad_Name" for a in setup.base]) == 1
    assert "--name must be lowercase" in capsys.readouterr().err
    other = setup.tmp / "other.bin"
    other.write_bytes(b"another checkpoint")
    (setup.tmp / "other.bin.lineage.json").write_text("{}")
    refused([], "not the plan's checkpoint", {"--checkpoint": str(other)})
    bare = setup.tmp / "bare.bin"
    bare.write_bytes(b"checkpoint bytes")
    refused([], "missing", {"--checkpoint": str(bare)})          # no lineage sidecar
    os.makedirs(setup.tmp / "plan2")
    path2, sha2 = write_plan(setup.tmp / "plan2",
                             dict(setup.plan, reward_manifest_sha256="1" * 64))
    refused([], "not the plan's reward manifest", {"--plan": path2, "--expect-sha256": sha2})
    monkeypatch.setattr(SD.DT, "git", lambda *a: "9" * 40 if a[0] == "rev-parse" else "")
    refused([], "is not the plan's source_commit")
    monkeypatch.setattr(SD.DT, "git", lambda *a: COMMIT if a[0] == "rev-parse" else " M x.py")
    refused([], "uncommitted changes")
    monkeypatch.setattr(SD.DT, "git", lambda *a: COMMIT if a[0] == "rev-parse" else "")
    monkeypatch.setattr(SD.AB, "code_sha256", lambda: "8" * 64)
    refused([], "does not hash to the plan's code_sha256")
    monkeypatch.undo()
    monkeypatch.setattr(SD.DT, "git", lambda *a: COMMIT if a[0] == "rev-parse" else "")
    refused(["--resume-from", str(setup.tmp)], "relaunches one shard")
    (setup.tmp / "run.json").write_text(json.dumps({"plan_sha256": setup.sha, "shard": "sb"}))
    (setup.tmp / "games.jsonl").write_text("")
    refused(["--shard", "sa", "--resume-from", str(setup.tmp)], "is not shard sa of this plan")
    os.makedirs(setup.out / "sa.failed")
    refused([], "already exists")
    assert not os.path.exists(setup.tmp / "state")


# ---- the lifecycle, faked -------------------------------------------------------------------
class FakeApi:
    def __init__(self, price=0.5, existing=0, limit=10):
        self.price, self.existing, self.limit = price, existing, limit

    def get(self, path):
        if path.startswith("/sizes"):
            return {"sizes": [{"slug": DT.DEFAULT_SIZE, "available": True,
                               "regions": [DT.DEFAULT_REGION], "price_hourly": self.price,
                               "vcpus": 8, "memory": 16384}]}
        if path == "/account":
            return {"account": {"droplet_limit": self.limit}}
        return {"droplets": [{"id": i} for i in range(self.existing)]}


class FakeRemote:
    files = {}            # droplet path -> bytes, what the "droplet" holds
    log = []              # every call, in order

    def __init__(self, state_dir, ip):
        self.ip = ip

    def run(self, command, check=True, timeout=600, stdin_text=None):
        FakeRemote.log.append(("run", command, stdin_text))
        return SimpleNamespace(stdout="started\n", returncode=0)

    def script(self, text, log_name, timeout):
        FakeRemote.log.append(("script", log_name, text))
        machine = {"cpu_model": "fake", "nproc": 8, "cc": "cc", "torch": "2.14.0",
                   "library_sha256": "c" * 64, "source_commit": COMMIT}
        return SimpleNamespace(stdout=json.dumps(machine) + "\nBUILD_OK\n", returncode=0)

    def put(self, local, remote, timeout=1800):
        with open(local, "rb") as f:
            FakeRemote.log.append(("put", remote, f.read()))

    def get(self, remote, local, check=True, timeout=1800):
        FakeRemote.log.append(("get", remote, None))
        if remote not in FakeRemote.files:
            if check:
                raise DT.RunnerError(f"scp from droplet failed: {remote}")
            return False
        with open(local, "wb") as f:
            f.write(FakeRemote.files[remote])
        return True


def droplet_output(setup, shard, drop=0, tamper=False):
    """What a droplet that played `shard` holds in its output directory."""
    tasks = AB.shard_tasks(setup.plan, shard)
    records = [fake(setup.plan, setup.sha, key) for key in tasks[:len(tasks) - drop]]
    out = {"games.jsonl": "".join(json.dumps(r) + "\n" for r in records).encode(),
           "run.json": json.dumps({"schema": AB.RUN_SCHEMA, "plan_sha256": setup.sha,
                                   "plan_name": "test", "shard": shard}).encode(),
           "COMPLETE.json": b"{}", "plan.json": open(setup.path, "rb").read(),
           "machine.json": json.dumps({"source_commit": COMMIT}).encode()}
    sums = "".join(f"{hashlib.sha256(data).hexdigest()}  {name}\n" for name, data in out.items())
    if tamper:
        out["games.jsonl"] += b"\n"
    out["SHA256SUMS"] = sums.encode()
    files = {f"{DT.REMOTE_OUT}/{name}": data for name, data in out.items()}
    files[f"{DT.REMOTE_RUN}/tournament.log"] = b"12/12 done\n"
    return files


@pytest.fixture
def faked(monkeypatch, setup):
    calls = SimpleNamespace(teardown=[], status=0, created=[], api=FakeApi(), poll=lambda: 0)
    FakeRemote.files, FakeRemote.log = droplet_output(setup, "sa"), []

    def create_droplet(api, state, name, region, size, fingerprint):
        calls.created.append(name)
        state.write("droplet-id", 77)
        return 77

    def teardown(api, state, name):
        calls.teardown.append(name)
        state.write("cost", "0.25")
        state.clear("droplet-id")
        return True

    def print_status(api):
        calls.status += 1
        print(f"droplets tagged {DT.TAG}: 0")

    def poll(remote, tasks, deadline, stale_seconds):
        calls.poll_args = (tasks, stale_seconds)
        return calls.poll()

    def archive(commit, path):
        with open(path, "wb") as f:
            f.write(b"archive of " + commit.encode())

    monkeypatch.setattr(SD.DT, "Api", lambda token: calls.api)
    monkeypatch.setattr(SD.DT, "read_token", lambda env_file=None: "token")
    monkeypatch.setattr(SD.DT, "create_key", lambda api, state, name: "aa:bb")
    monkeypatch.setattr(SD.DT, "create_droplet", create_droplet)
    monkeypatch.setattr(SD.DT, "wait_active", lambda api, droplet_id: "10.0.0.1")
    monkeypatch.setattr(SD.DT, "wait_ssh", lambda remote: None)
    monkeypatch.setattr(SD.DT, "Remote", FakeRemote)
    monkeypatch.setattr(SD.DT, "poll", poll)
    monkeypatch.setattr(SD.DT, "teardown", teardown)
    monkeypatch.setattr(SD.DT, "print_status", print_status)
    monkeypatch.setattr(SD, "make_archive", archive)
    return calls


def test_one_shard_is_created_played_fetched_verified_and_destroyed(setup, faked, capsys):
    assert SD.main(setup.base + ["--shard", "sa"]) == 0
    text = capsys.readouterr().out
    assert faked.created == ["ab-sa"] and faked.teardown == ["ab-sa"]
    assert faked.status == 2                                   # the listing, before and after
    assert text.index("tagged droplets before") < text.index("shard sa: 12 games on 8") \
        < text.index("tagged droplets after")
    assert "spend guard: 1 shard(s) x 2.0 h x $0.50000/h" in text
    out = setup.out / "sa"
    assert sorted(os.listdir(out)) == ["COMPLETE.json", "SHA256SUMS", "droplet_run.json",
                                       "games.jsonl", "machine.json", "plan.json", "run.json",
                                       "tournament.log"]
    result = json.load(open(out / "droplet_run.json"))
    assert result["games"] == 12 and result["cost"] == 0.25 and result["processes"] == 8
    assert result["plan_sha256"] == setup.sha and result["commit"] == COMMIT
    puts = {remote: data for kind, remote, data in FakeRemote.log if kind == "put"}
    assert puts[SD.REMOTE_PLAN] == open(setup.path, "rb").read()
    assert puts[SD.REMOTE_MANIFEST] == open(FIXTURE, "rb").read()
    blob = DT.remote_checkpoint_path("a", setup.blob)
    assert puts[blob] == b"checkpoint bytes" and blob + ".lineage.json" in puts
    assert puts[f"{DT.REMOTE_ROOT}/src.tar.gz"] == b"archive of " + COMMIT.encode()
    job = next(text for kind, command, text in FakeRemote.log
               if kind == "run" and command.endswith("job.sh"))
    assert f"--expect-sha256 {setup.sha} --shard sa --checkpoint {blob}" in job
    assert "--processes 8" in job
    assert faked.poll_args == (12, 1800)
    scripts = [name for kind, name, _ in FakeRemote.log if kind == "script"]
    assert scripts == ["setup.log", "build.log"]
    # Nothing of the token reaches a script, a command or a file that was sent.
    assert all(b"token" not in (data if isinstance(data, bytes) else str(data).encode())
               for _, _, data in FakeRemote.log if data)
    # The fetched directory is what `report` reads.
    assert len(AB.load_records(str(out / "games.jsonl"))) == 12


def test_the_spend_guard_and_a_full_account_stop_the_run_before_anything_is_created(
        setup, faked, capsys):
    faked.api = FakeApi(price=0.8)                             # 2 shards x 2 h x 0.8 = 3.20
    assert SD.main(setup.base) == 1
    assert "= $3.20, above --max-total-usd 3.0. Nothing was created" in capsys.readouterr().err
    assert faked.created == [] and faked.teardown == [] and faked.status == 0
    assert not os.path.exists(setup.out)
    # One shard fits the same budget.
    faked.api = FakeApi(price=0.8, existing=10, limit=10)
    assert SD.main(setup.base + ["--shard", "sa"]) == 1
    err = capsys.readouterr().err
    assert "BLOCKER" in err and "Do not delete another project's droplet" in err
    assert faked.created == [] and faked.teardown == []
    # Room for one, two asked for: still a blocker.
    faked.api = FakeApi(price=0.5, existing=9, limit=10)
    assert SD.main(setup.base) == 1
    assert "this run needs 2 more" in capsys.readouterr().err and faked.created == []


def _raise(exc):
    raise exc


@pytest.mark.parametrize("how", ["timeout", "job", "verify", "interrupt"])
def test_every_failure_keeps_the_records_so_far_and_still_destroys_the_droplet(
        setup, faked, capsys, how):
    partial = droplet_output(setup, "sa", drop=5)
    if how == "timeout":
        FakeRemote.files = partial
        faked.poll = lambda: _raise(DT.RunnerError("the run passed --max-hours; giving up"))
    elif how == "job":
        FakeRemote.files = partial
        faked.poll = lambda: 3
    elif how == "verify":
        FakeRemote.files = droplet_output(setup, "sa", tamper=True)
    else:
        FakeRemote.files = partial
        faked.poll = lambda: _raise(DT.Interrupted("signal 2"))
    code = SD.main(setup.base + ["--shard", "sa"])
    captured = capsys.readouterr()
    assert code == (130 if how == "interrupt" else 1)
    assert faked.teardown == ["ab-sa"]                         # on every one of them
    assert faked.status == 2                                   # the listing after, too
    assert not os.path.exists(setup.out / "sa")
    failed = setup.out / "sa.failed"
    kept = AB.load_records(str(failed / "games.jsonl"))
    assert len(kept) == (12 if how == "verify" else 7)
    assert json.load(open(failed / "run.json"))["shard"] == "sa"
    assert f"relaunch with --resume-from {failed}" in captured.out
    needle = {"timeout": "passed --max-hours", "job": "droplet job exited 3",
              "verify": "verification failed", "interrupt": "INTERRUPTED"}[how]
    assert needle in captured.err


def test_a_failure_before_the_droplet_answers_still_tears_down(setup, faked, monkeypatch, capsys):
    monkeypatch.setattr(SD.DT, "wait_ssh",
                        lambda remote: _raise(DT.RunnerError("ssh never came up")))
    assert SD.main(setup.base + ["--shard", "sa"]) == 1
    assert faked.teardown == ["ab-sa"] and "ssh never came up" in capsys.readouterr().err
    faked.teardown.clear()
    monkeypatch.setattr(SD.DT, "create_key",
                        lambda api, state, name: _raise(DT.RunnerError("key refused")))
    assert SD.main(setup.base + ["--shard", "sb"]) == 1
    assert faked.teardown == ["ab-sb"]                         # teardown reconciles from state


def test_keep_leaves_the_droplet_and_says_so(setup, faked, capsys):
    assert SD.main(setup.base + ["--shard", "sa", "--keep"]) == 0
    assert faked.teardown == []
    assert "STILL BILLING" in capsys.readouterr().out
    assert "cost" not in json.load(open(setup.out / "sa" / "droplet_run.json"))


def test_a_relaunch_uploads_the_finished_games_and_plays_only_the_rest(setup, faked, capsys):
    earlier = setup.tmp / "earlier"
    earlier.mkdir()
    done = droplet_output(setup, "sa", drop=5)
    (earlier / "games.jsonl").write_bytes(done[f"{DT.REMOTE_OUT}/games.jsonl"])
    (earlier / "run.json").write_bytes(done[f"{DT.REMOTE_OUT}/run.json"])
    assert SD.main(setup.base + ["--shard", "sa", "--resume-from", str(earlier)]) == 0
    order = [(kind, remote) for kind, remote, _ in FakeRemote.log]
    games = order.index(("put", f"{DT.REMOTE_OUT}/games.jsonl"))
    launch = next(i for i, (kind, what) in enumerate(order)
                  if kind == "run" and "nohup setsid bash" in what)
    assert games < launch and ("put", f"{DT.REMOTE_OUT}/run.json") in order[:launch]
    uploaded = next(data for kind, remote, data in FakeRemote.log
                    if kind == "put" and remote.endswith("/games.jsonl"))
    assert uploaded == (earlier / "games.jsonl").read_bytes()  # byte for byte, not rewritten
    assert json.load(open(setup.out / "sa" / "droplet_run.json"))["resumed_from"] == str(earlier)


def test_several_shards_run_as_children_each_with_its_own_teardown(setup, faked, monkeypatch,
                                                                    capsys):
    spawned = []

    class Child:
        def __init__(self, argv, **kwargs):
            spawned.append(argv)
            self.pid, self.code = 1000 + len(spawned), 0 if "sa" in argv else self.fail

        fail = 0

        def wait(self):
            return self.code

        def poll(self):
            return self.code

    monkeypatch.setattr(SD.subprocess, "Popen", Child)
    assert SD.main(setup.base) == 0
    assert faked.status == 2 and faked.created == []           # the children create, not us
    assert len(spawned) == 2
    for argv, shard in zip(spawned, ("sa", "sb")):
        child = SD.build_parser().parse_args(argv[2:])
        assert child.child and child.shard == [shard] and child.name == "ab"
        assert (child.expect_sha256, child.max_hours, child.max_total_usd) == (setup.sha, 2.0, 3.0)
        assert child.plan == setup.path and child.checkpoint == setup.blob
    assert sorted(os.listdir(setup.out)) == ["sa.runner.log", "sb.runner.log"]
    text = capsys.readouterr().out
    assert "spend guard: 2 shard(s) x 2.0 h x $0.50000/h = $2.00 of $3.0 allowed" in text
    # One child failing fails the run; the listing is still printed after.
    Child.fail = 1
    spawned.clear()
    for name in os.listdir(setup.out):
        os.remove(setup.out / name)
    assert SD.main(setup.base) == 1
    assert faked.status == 4


def test_a_child_runs_its_shard_without_repeating_the_guard_or_the_listing(setup, faked):
    assert SD.main(setup.base + ["--shard", "sa", "--child", "--max-total-usd", "0.01"]) == 0
    assert faked.created == ["ab-sa"] and faked.teardown == ["ab-sa"] and faked.status == 0
