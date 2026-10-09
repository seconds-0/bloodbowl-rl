#!/usr/bin/env python3
"""Tests of rig_gate.py's own logic. No network, no rig: run with `python3 test_rig_gate.py`."""
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rig_gate as R  # noqa: E402

WORKTREE = os.path.expanduser("~/Code/bb-harness-masks")
PLAN = {
    "gate": "t-gate-1", "harness_worktree": WORKTREE, "checkpoint_store": "/store", "seed0": 100,
    "games_per_worker": 32,
    "players": {"a": {"checkpoint": "chainA", "masks": []}, "b": {"checkpoint": "chainB", "masks": []},
                "am": {"checkpoint": "chainA", "masks": ["m1"]}, "bot": {"bot": "offense", "masks": []}},
    "checkpoints_sha256": {"chainA": "aa", "chainB": "bb"},
    "pairs": [["a", "b", 64], ["am", "bot", 32]],
    "shards": {"t-gate-1-s1": ["a,b,64"], "t-gate-1-s2": ["am,bot,32"]},
}


def check(name, cond):
    print(("ok   " if cond else "FAIL ") + name)
    return bool(cond)


def main():
    ok = True
    runner = R.load_runner(PLAN)
    saved = (runner.REMOTE_ROOT, runner.REMOTE_SRC, runner.REMOTE_RUN, runner.REMOTE_OUT, runner.REMOTE_PY)

    s1 = R.shard_spec(PLAN, "t-gate-1-s1", runner)
    ok &= check("plain shard: two checkpoints by local blob path, no bots, no extra args",
                s1["checkpoints"] == {"a": "/store/chainA/" + R.BLOB, "b": "/store/chainB/" + R.BLOB}
                and s1["bots"] == {} and s1["extra"] == [] and s1["pairs"] == [("a", "b", 64)]
                and s1["tasks"] == 64 and s1["checkpoint_sha"] == {"a": "aa", "b": "bb"})
    s2 = R.shard_spec(PLAN, "t-gate-1-s2", runner)
    ok &= check("masked player and bot: mask passed as a tournament argument, bot not uploaded, hash by checkpoint",
                s2["checkpoints"] == {"am": "/store/chainA/" + R.BLOB} and s2["bots"] == {"bot": "offense"}
                and s2["extra"] == ["--mask", "am=m1"] and s2["checkpoint_sha"] == {"am": "aa"})

    ok &= check("gate root and run directory are under the rig root",
                R.gate_root(PLAN) == R.RIG_ROOT + "/t-gate-1"
                and R.run_dir(PLAN, "t-gate-1-s1") == R.RIG_ROOT + "/t-gate-1/run-t-gate-1-s1")
    for bad in ("", "a b", "x;rm", "../up", "UPPER"):
        try:
            R.gate_root({"gate": bad})
            ok &= check(f"gate name {bad!r} refused", False)
        except R.GateError:
            ok &= check(f"gate name {bad!r} refused", True)

    R.point(runner, PLAN, R.run_dir(PLAN, "t-gate-1-s2"))
    argv = runner.tournament_argv(s2["checkpoints"], s2["bots"], s2["pairs"], PLAN["seed0"], 6,
                                  out_dir=runner.REMOTE_OUT, extra=s2["extra"], games_per_worker=32)
    job = runner.job_script(argv, 6)
    root = R.RIG_ROOT + "/t-gate-1"
    ok &= check("job script plays from the gate's sources with the rig venv and writes into the shard's run directory",
                f"cd {root}/src" in job and R.RIG_PY + " -m play_harness.tournament" in job
                and f"--out-dir {root}/run-t-gate-1-s2/main" in job and "BBPLAY_MAX_WORKERS=6" in job
                and f"--checkpoint am={root}/checkpoints/am/{R.BLOB}" in job and "--bot bot=offense" in job
                and "--mask am=m1" in job and "--games-per-worker 32" in job and "/srv/bb" not in job)
    build = runner.build_script("c" * 40)
    ok &= check("build script uses the gate's directories, never the droplet's", "/srv/bb" not in build
                and f"cd {root}/src" in build)

    queue = R.queue_script(PLAN, ["t-gate-1-s1", "t-gate-1-s2"])
    lines = queue.splitlines()
    ok &= check("queue records its pid, then makes itself the first choice of the out-of-memory killer",
                lines[2] == f"echo $$ > {root}/QUEUE_PID" and lines[3].startswith("echo 1000 > /proc/$$/oom_score_adj || "))
    ok &= check("queue clears inherited build variables and hides the GPU",
                lines[4] == "unset BBPLAY_BUILD_DIR BBPLAY_LIB" and lines[5] == "export CUDA_VISIBLE_DEVICES=")
    ok &= check("queue opens the rig-wide lock without truncating it and WAITS for it (gates take turns)",
                lines[6] == f"exec 9>> {R.RIG_LOCK}" and lines[8].startswith("flock 9 || ") and "flock -n" not in queue)
    ok &= check("jobs inherit the lock: no job line closes descriptor 9", "9>&-" not in queue)
    ok &= check("queue plays shards in order, stops at the first failure, marks the end",
                "run-t-gate-1-s1/job.sh" in lines[10] and "run-t-gate-1-s2/job.sh" in lines[11]
                and all("QUEUE_FAILED; exit 1" in l for l in lines[10:12])
                and lines[12] == f"echo done > {root}/QUEUE_DONE")

    bad_plans = {
        "shard name with a shell metacharacter": {"shards": {"s1;touch x": ["a,b,64"]}},
        "shard name with a path component": {"shards": {"../s1": ["a,b,64"]}},
        "player name that is a parent directory": {"players": {"..": {"checkpoint": "chainA", "masks": []}}},
        "player name with a slash": {"players": {"a/b": {"checkpoint": "chainA", "masks": []}}},
        "checkpoint name with a path component": {"players": {"a": {"checkpoint": "../chainA", "masks": []}}},
        "mask name with a space": {"players": {"a": {"checkpoint": "chainA", "masks": ["m1 x"]}}},
        "gate name in capitals": {"gate": "GATE"},
    }
    for what, change in bad_plans.items():
        ok &= check(f"refused: {what}", len(R.name_problems({**PLAN, **change})) >= 1)
    ok &= check("the test plan's own names are accepted", R.name_problems(PLAN) == [])
    try:
        R.run_dir(PLAN, "x/../y")
        ok &= check("run_dir refuses a shard name with a path component", False)
    except R.GateError:
        ok &= check("run_dir refuses a shard name with a path component", True)

    for what, change in {"gate name with a trailing newline": {"gate": "t-gate-1\n"},
                         "shard name with a trailing newline": {"shards": {"t-gate-1-s1\n": ["a,b,64"]}},
                         "player name with a trailing newline": {"players": {"a\n": {"checkpoint": "chainA", "masks": []}}},
                         "checkpoint key with a path component": {"checkpoints_sha256": {"../chainA": "aa"}},
                         "checkpoint key that is absolute": {"checkpoints_sha256": {"/etc/x": "aa"}}}.items():
        ok &= check(f"refused: {what}", len(R.name_problems({**PLAN, **change})) >= 1)

    calls = []
    real_run = R.subprocess.run

    def fake_run(argv, **kw):
        calls.append(argv)
        return types.SimpleNamespace(returncode=0, stdout="" if kw.get("text") else b"", stderr="")
    R.subprocess.run = fake_run
    try:
        rig = R.Rig("nohost")
        rig.run("echo hi")
        rig.script("echo script", "/home/rache/bbgate/x/build/setup.log", timeout=5)
        with tempfile.NamedTemporaryFile() as tf:
            rig.put(tf.name, "/home/rache/bbgate/x/file")
            rig.get("/home/rache/bbgate/x/file", tf.name + ".got")
        R.queue_state(rig, PLAN)
    finally:
        R.subprocess.run = real_run
    ok &= check("every command sent to the rig, uploads and downloads included, is wrapped at the lowest CPU and I/O priority",
                len(calls) == 5 and all(c[0] == "ssh" and c[-2] == "nohost"
                                        and c[-1].startswith(R.LOW + " bash -c ") for c in calls)
                and R.LOW.endswith("nice -n 19 ionice -c 3") and "-u BBPLAY_BUILD_DIR" in R.LOW)
    ok &= check("no transfer uses scp or sftp, and the script's tee is inside the wrapper",
                "tee" in calls[1][-1] and calls[1][-1].index(R.LOW) < calls[1][-1].index("tee"))
    try:
        os.remove(tf.name + ".got")
    except OSError:
        pass
    probs, head = R.admission_problems("10407936\n581\n")
    ok &= check("admission: enough memory and disk passes", probs == [] and head == {"mem_available_mb": 10164, "disk_free_gb": 581})
    probs, _ = R.admission_problems("2048000\n581\n")
    ok &= check("admission: under 4,000 MB available refuses", len(probs) == 1 and "MB available" in probs[0])
    probs, _ = R.admission_problems("10407936\n12\n")
    ok &= check("admission: under 20 GB of disk refuses", len(probs) == 1 and "disk" in probs[0])
    probs, _ = R.admission_problems("garbage")
    ok &= check("admission: unreadable probe refuses", len(probs) == 1)

    setup = R.setup_script("2.14.0", "2.5.3")
    ok &= check("setup installs CPU-only torch into the isolated venv and asserts no CUDA",
                "download.pytorch.org/whl/cpu" in setup and "torch==2.14.0" in setup
                and "assert not torch.cuda.is_available()" in setup and R.RIG_ROOT + "/venv" in setup
                and "apt" not in setup and "sudo" not in setup)

    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "PLAN.json")
        with open(path, "w") as f:
            json.dump(PLAN, f)
        sha = R.sha256_file(path)
        plan, got = R.load_plan(path, sha)
        ok &= check("plan loads when its hash matches", got == sha and plan["gate"] == "t-gate-1")
        try:
            R.load_plan(path, "0" * 64)
            ok &= check("plan refused on a hash mismatch", False)
        except R.GateError:
            ok &= check("plan refused on a hash mismatch", True)
        args = types.SimpleNamespace(plan=path, expect_sha256="0" * 64, workers=6, dry_run=True, host="nohost")
        ok &= check("start exits 2 and does nothing on a hash mismatch",
                    R.main(["start", path, "--expect-sha256", "0" * 64, "--dry-run"]) == 2)

    src = open(os.path.join(HERE, "rig_gate.py")).read()
    ok &= check("the runner has no re-entry path and no scp", "--continue" not in src.split('"""')[2]
                and '"scp"' not in src)
    ok &= check("start writes rig_start.json before it prepares or launches anything on the rig",
                src.index('"rig_start.json"), "w")') < src.index("rig.script(setup_script("))
    ok &= check("the venv is made under its own lock", "flock 8" in R.setup_script("2.14.0", "2.5.3"))
    plan_ok = {**PLAN, "main_checkout": WORKTREE, "main_checkout_commit": "x", "harness_commit": "x",
               "checkpoints_sha256": {}, "launch": {"script": "launch_from_plan.py", "script_sha256": "0",
                                                    "runner_sha256": "0"}}
    probs = R.preflight(plan_ok)
    ok &= check("preflight refuses a plan that does not register this rig_gate.py as its launch script",
                any("does not register this rig_gate.py" in p for p in probs)
                and any("is not the runner the plan registers" in p for p in probs))
    ok &= check("the runner makes no cloud call and deletes nothing",
                all(word not in src for word in ("digitalocean.com", "urllib", "read_token", "os.remove",
                                                 "shutil.rmtree", "rm -", "unlink")))
    ok &= check("collect checks the worktree and the runner's hash before it imports the verifier",
                src.index("worktree_problems(plan)", src.index("def cmd_collect")) < src.index("runner = load_runner(plan)", src.index("def cmd_collect"))
                and "started[\"runner_sha256\"]" in src)
    ok &= check("rig_run.json is written before the shard is renamed into place",
                src.index('"rig_run.json"') < src.index("os.rename(partial, out_dir)"))
    (runner.REMOTE_ROOT, runner.REMOTE_SRC, runner.REMOTE_RUN, runner.REMOTE_OUT, runner.REMOTE_PY) = saved
    print("ALL OK" if ok else "FAILURES")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
