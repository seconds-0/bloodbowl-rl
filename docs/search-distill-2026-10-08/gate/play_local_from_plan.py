#!/usr/bin/env python3
"""Play a local rehearsal of the gate plan on this machine, in one process. Never the registered gate.

  python play_local_from_plan.py PLAN.json --expect-sha256 <sha256 of PLAN.json>

Only for a plan written with make_plan.py --local (its name starts with
"distill-mac-"). It plays every pair of the plan with play_harness.tournament
from the harness worktree at the registered commit, straight into the plan's
run directory, which must not exist yet: the merge-free path. One worker, the
plan's games per worker. score_from_plan.py then finds the run directory,
skips the merge, and runs the same acceptance and scoring as for the gate.

Nothing is written into the worktree: bytecode is off, and the engine library
is the one --library names (default: the harness export's own build), so the
harness never rebuilds its shim there. It refuses unless the plan hashes to
--expect-sha256, the worktree is clean at the registered commit, and every
checkpoint blob and sidecar has its registered sha256.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

# The harness export's own build of the shim (export_harness.sh), outside every worktree.
DEFAULT_LIBRARY = os.path.join(
    os.path.expanduser("~/Code/bb-opt-build/runs/search-distill-2026-10-08/harness-5ab3ab6"),
    "build", "play_harness", "libbbplay.dylib" if sys.platform == "darwin" else "libbbplay.so")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def tournament_argv(plan, python):
    argv = [python, "-m", "play_harness.tournament", "--seed0", str(plan["seed0"]),
            "--workers", "1", "--games-per-worker", str(plan["games_per_worker"]),
            "--kernel", plan["kernel"], "--out-dir", os.path.expanduser(plan["run_dir"])]
    for name, player in plan["players"].items():
        argv += ["--checkpoint", f"{name}={plan['checkpoint_paths'][player['checkpoint']]}"]
        if player.get("masks"):
            argv += ["--mask", f"{name}={','.join(player['masks'])}"]
    for a, b, n in plan["pairs"]:
        argv += ["--pair", f"{a},{b},{int(n)}"]
    return argv


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan")
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--library", default=DEFAULT_LIBRARY,
                    help="a built engine shim outside the worktree")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)
    got = sha256_file(args.plan)
    if got != args.expect_sha256.lower():
        raise SystemExit(f"plan hashes to {got}, not {args.expect_sha256}; nothing played")
    with open(args.plan) as f:
        plan = json.load(f)
    problems = []
    if not plan.get("local_rehearsal") or not plan["gate"].startswith("distill-mac-"):
        problems.append("not a local rehearsal plan (make_plan.py --local)")
    if sha256_file(os.path.abspath(__file__)) != plan["launch"]["local_script_sha256"]:
        problems.append("this script is not the one the plan names")
    root = os.path.expanduser(plan["harness_worktree"])
    if git(root, "rev-parse", "HEAD") != plan["harness_commit"]:
        problems.append(f"{root} is not at {plan['harness_commit']}")
    if git(root, "status", "--porcelain"):
        problems.append(f"{root} is not clean")
    for name, sha in plan["checkpoints_sha256"].items():
        path = plan["checkpoint_paths"][name]
        if not os.path.isfile(path) or sha256_file(path) != sha:
            problems.append(f"{path} is not the registered {name}")
        elif sha256_file(path + ".lineage.json") != plan["sidecars_sha256"][name]:
            problems.append(f"{path}.lineage.json is not the registered sidecar of {name}")
    if not os.path.isfile(args.library):
        problems.append(f"no engine library at {args.library}")
    run_dir = os.path.expanduser(plan["run_dir"])
    if os.path.exists(run_dir):
        problems.append(f"{run_dir} exists")
    if problems:
        raise SystemExit("nothing played:\n  " + "\n  ".join(problems))
    python = os.path.join(os.path.expanduser(plan["main_checkout"]), ".venv", "bin", "python")
    command = tournament_argv(plan, python)
    print("+", " ".join(command), flush=True)
    if args.dry_run:
        return 0
    env = {**os.environ, "OMP_NUM_THREADS": "1", "PYTHONDONTWRITEBYTECODE": "1",
           "BBPLAY_LIB": os.path.abspath(args.library)}
    return subprocess.run(command, cwd=root, env=env).returncode


if __name__ == "__main__":
    sys.exit(main())
