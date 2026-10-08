#!/usr/bin/env python3
"""Launch the shards of a registered gate plan, one throwaway droplet each, detached.

  python launch_from_plan.py PLAN.json --expect-sha256 <sha256 of PLAN.json> [--dry-run] [SHARD ...]

Every argument of every shard comes from PLAN.json. A shard is a slice of game
indexes: {"index0": K, "pairs": ["A,B,N", ...]} plays N games of each listed
pair starting at game index K (engine seed = seed0 + index). Refuses to launch
unless the plan hashes to --expect-sha256 (the hash committed to the ledger),
the harness worktree is clean at the registered commit, the main harness
checkout is clean at its pinned commit, every checkpoint blob on disk has the
registered sha256, and the shards' slices cover every registered pair exactly
once, from index 0, without a gap or an overlap. Each shard is one
`tools/droplet_tournament.py run` in its own session under caffeinate; that
tool creates the droplet, verifies the run and destroys the droplet.
--dry-run prints the commands and launches nothing.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

BLOB = "0000002999975936.bin"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def shard_pairs(plan, shard):
    return [(a, b, int(n)) for a, b, n in (p.split(",") for p in plan["shards"][shard]["pairs"])]


def shard_argv(plan, shard):
    root = os.path.expanduser(plan["harness_worktree"])
    store = os.path.expanduser(plan["checkpoint_store"])
    spec = plan["shards"][shard]
    argv = ["caffeinate", "-i", sys.executable, os.path.join(root, "tools", "droplet_tournament.py"),
            "run", "--name", shard, "--seed0", str(plan["seed0"]),
            "--games-per-worker", str(plan["games_per_worker"]), "--commit", plan["harness_commit"],
            "--out-root", os.path.expanduser(plan["out_root"]), "--max-hours", str(plan["max_hours"]),
            "--size", plan["droplet_size"]]
    if int(spec["index0"]):
        argv += ["--index0", str(int(spec["index0"]))]
    pairs = shard_pairs(plan, shard)
    names = []
    for a, b, _n in pairs:
        for name in (a, b):
            if name not in names:
                names.append(name)
    for name in names:
        player = plan["players"][name]
        if "bot" in player:
            argv += ["--bot", f"{name}={player['bot']}"]
            continue
        argv += ["--checkpoint", f"{name}={os.path.join(store, player['checkpoint'], BLOB)}"]
        if player.get("masks"):
            argv += ["--tournament-arg=--mask",
                     f"--tournament-arg={name}={','.join(player['masks'])}"]
        if float(player.get("temperature", 1.0)) != 1.0:
            argv += ["--tournament-arg=--temperature",
                     f"--tournament-arg={name}={float(player['temperature'])}"]
        if player.get("search"):
            s = player["search"]
            argv += ["--search", f"{name}={s['k']}:{s['n']}:{s['delta']}"]
    for a, b, n in pairs:
        argv += ["--pair", f"{a},{b},{n}"]
    return argv


def coverage_problems(plan):
    """Every registered pair is covered by the shards' slices exactly once from index 0."""
    problems = []
    slices = {}
    for shard in plan["shards"]:
        index0 = int(plan["shards"][shard]["index0"])
        for a, b, n in shard_pairs(plan, shard):
            if n <= 0 or n % 2:
                problems.append(f"{shard}: {a},{b},{n} is not a positive even number of games")
            slices.setdefault((a, b), []).append((index0, index0 + n // 2, shard))
    want = {(a, b): int(n) for a, b, n in plan["pairs"]}
    if sorted(slices) != sorted(want):
        problems.append(f"shards cover pairs {sorted(slices)}, registered {sorted(want)}")
        return problems
    for pair, parts in sorted(slices.items()):
        at = 0
        for lo, hi, shard in sorted(parts):
            if lo != at:
                problems.append(f"{pair}: {shard} starts at index {lo}, expected {at}")
            at = hi
        if at != want[pair] // 2:
            problems.append(f"{pair}: the shards end at index {at}, registered {want[pair] // 2}")
    return problems


def preflight(plan):
    problems = []
    root = os.path.expanduser(plan["harness_worktree"])
    main = os.path.expanduser(plan["main_checkout"])
    if git(root, "rev-parse", "HEAD") != plan["harness_commit"]:
        problems.append(f"{root} is not at {plan['harness_commit']}")
    if git(root, "status", "--porcelain"):
        problems.append(f"{root} is not clean")
    if git(main, "rev-parse", "HEAD") != plan["main_checkout_commit"]:
        problems.append(f"{main} is not at {plan['main_checkout_commit']}")
    if git(main, "status", "--porcelain"):
        problems.append(f"{main} is not clean")
    store = os.path.expanduser(plan["checkpoint_store"])
    for chain, sha in plan["checkpoints_sha256"].items():
        path = os.path.join(store, chain, BLOB)
        if not os.path.isfile(path) or not os.path.isfile(path + ".lineage.json"):
            problems.append(f"missing {path} or its lineage sidecar")
        elif sha256_file(path) != sha:
            problems.append(f"{path} is not the registered {chain}")
    if sha256_file(os.path.join(root, "tools", "droplet_tournament.py")) != plan["launch"]["runner_sha256"]:
        problems.append("tools/droplet_tournament.py is not the registered runner")
    if sha256_file(os.path.abspath(__file__)) != plan["launch"]["script_sha256"]:
        problems.append("this launcher is not the registered launch script")
    return problems + coverage_problems(plan)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("plan")
    ap.add_argument("shards", nargs="*")
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--relaunch-suffix", default="",
                    help="run each named shard again under NAME+SUFFIX (droplet name and "
                         "output directory); the plan's arguments are unchanged")
    args = ap.parse_args(argv)
    got = sha256_file(args.plan)
    if got != args.expect_sha256.lower():
        raise SystemExit(f"plan hashes to {got}, not {args.expect_sha256}; nothing launched")
    with open(args.plan) as f:
        plan = json.load(f)
    problems = preflight(plan)
    if problems:
        raise SystemExit("nothing launched:\n  " + "\n  ".join(problems))
    shards = args.shards or sorted(plan["shards"])
    unknown = [s for s in shards if s not in plan["shards"]]
    if unknown:
        raise SystemExit(f"not shards of this plan: {unknown}; nothing launched")
    out_root = os.path.expanduser(plan["out_root"])
    logs = os.path.expanduser(plan["log_dir"])
    if args.relaunch_suffix and not args.shards:
        raise SystemExit("--relaunch-suffix needs the shards named; nothing launched")
    for shard in shards:
        if os.path.exists(os.path.join(out_root, shard + args.relaunch_suffix)):
            raise SystemExit(f"{shard + args.relaunch_suffix} already has a directory under "
                             f"{out_root}; nothing launched")
    for shard in shards:
        argv_ = shard_argv(plan, shard)
        argv_[argv_.index("--name") + 1] = shard + args.relaunch_suffix
        shard = shard + args.relaunch_suffix
        if args.dry_run:
            print(shard, " ".join(argv_), flush=True)
            continue
        os.makedirs(logs, exist_ok=True)
        log = open(os.path.join(logs, shard + ".log"), "ab")
        proc = subprocess.Popen(argv_, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                start_new_session=True,
                                cwd=os.path.expanduser(plan["harness_worktree"]))
        print(shard, "pid", proc.pid, flush=True)


if __name__ == "__main__":
    main()
