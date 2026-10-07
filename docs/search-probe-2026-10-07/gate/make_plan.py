#!/usr/bin/env python3
"""Write PLAN.json, PLAN.json.sha256 and SCRIPTS.sha256 for a search gate (or its smoke).

  python make_plan.py --out-dir DIR --gate NAME --registered-in TEXT --seed0 N \\
      --games-per-pair N --identity-games N --shards N --max-hours H

The scripts beside this file are copied into DIR when DIR is another directory,
so a smoke runs the same scripts as the gate. Players, pairs, contrasts and
diagnostics are fixed here: chain 55 + m1 with the search seat (S), chain 55 +
m1 (C), each against chain 37 and chain 46, and an identity pair (the search
seat at delta inf against chain 37) on the first game indexes of the first
shard. Every shard plays the same slice of game indexes for all four pairs, so
no arm is tied to a machine. The harness worktree must be clean; its head is
the registered commit, and the search setting, the integrity check list and
the reward manifest hash are read from that code.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
WORKTREE = "~/Code/bb-harness-search"
MAIN = "~/Code/bb-play-harness"
SCRIPTS = ("accept_from_plan.py", "launch_from_plan.py", "gate_diagnostics.py",
           "paired_contrasts.py", "score_from_plan.py", "make_plan.py")
CHECKPOINTS = {
    "chain55": "f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b",
    "chain37": "268f1db08ca0c2bad88293ea56b3048a2a1c3a0ea9acdf0365fc023186c0f73f",
    "chain46": "8eee9ac10f58eca57092013ac05db6f28fb5f7f2c6dc9ce850960c7bb2c7c467",
}
S, C, SINF = "c55m1s", "c55m1", "c55m1inf"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--gate", required=True)
    ap.add_argument("--registered-in", required=True)
    ap.add_argument("--seed0", type=int, required=True)
    ap.add_argument("--games-per-pair", type=int, required=True)
    ap.add_argument("--identity-games", type=int, required=True)
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--max-hours", type=float, required=True)
    ap.add_argument("--droplet-size", default="s-8vcpu-16gb-amd")
    args = ap.parse_args()

    root, main_root = os.path.expanduser(WORKTREE), os.path.expanduser(MAIN)
    if git(root, "status", "--porcelain"):
        raise SystemExit(f"{root} is not clean")
    commit = git(root, "rev-parse", "HEAD")
    sys.path.insert(0, root)
    from play_harness import search as search_module
    setting = search_module.search_setting()
    identity_setting = search_module.search_setting(delta="inf")

    seeds = args.games_per_pair // 2
    if args.games_per_pair % 2 or seeds % args.shards:
        raise SystemExit("games per pair must split evenly into the shards' index slices")
    per = seeds // args.shards
    if args.identity_games % 2 or args.identity_games // 2 > per:
        raise SystemExit("the identity games must fit the first shard's slice")
    out_dir = os.path.abspath(os.path.expanduser(args.out_dir))
    os.makedirs(out_dir, exist_ok=True)
    if out_dir != HERE:
        for name in SCRIPTS:
            shutil.copyfile(os.path.join(HERE, name), os.path.join(out_dir, name))

    players = {
        S: {"checkpoint": "chain55", "masks": ["m1"], "search": setting},
        C: {"checkpoint": "chain55", "masks": ["m1"]},
        SINF: {"checkpoint": "chain55", "masks": ["m1"], "search": identity_setting},
        "chain37": {"checkpoint": "chain37", "masks": []},
        "chain46": {"checkpoint": "chain46", "masks": []},
    }
    main_pairs = [[S, "chain37"], [C, "chain37"], [S, "chain46"], [C, "chain46"]]
    pairs = [[a, b, args.games_per_pair] for a, b in main_pairs]
    pairs.append([SINF, "chain37", args.identity_games])
    shards = {}
    for j in range(args.shards):
        entry = {"index0": j * per, "pairs": [f"{a},{b},{2 * per}" for a, b in main_pairs]}
        if j == 0:
            entry["pairs"].append(f"{SINF},chain37,{args.identity_games}")
        shards[f"{args.gate}-s{j + 1}"] = entry
    tools = os.path.join(root, "tools")
    run_dir = f"{MAIN}/.play-artifacts/tournaments/{args.gate}/main"
    plan = {
        "gate": args.gate,
        "registered_in": args.registered_in,
        "written_before_launch_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "harness_commit": commit,
        "harness_worktree": WORKTREE,
        "harness_branch": git(root, "branch", "--show-current"),
        "main_checkout": MAIN,
        "main_checkout_commit": git(main_root, "rev-parse", "HEAD"),
        "checkpoint_store": f"{MAIN}/.play-artifacts/checkpoints",
        "out_root": f"{MAIN}/.play-artifacts/tournaments",
        "log_dir": f"{MAIN}/.play-artifacts/logs",
        "run_dir": run_dir,
        "seed0": args.seed0,
        "games_per_pair": args.games_per_pair,
        "total_games": sum(n for _a, _b, n in pairs),
        "games_per_worker": 1,
        "mode": "sample",
        "kernel": "native",
        "temperature": 1.0,
        "starts": "kickoff",
        "legs": ["A_home", "B_home"],
        "mask_definition": {"m1": "END_TURN is removed from the masked seat's exact joint support "
                                  "while an ACTIVATE is also legal; the policy is renormalized over "
                                  "what is left (play_harness/policy.py restrict_support, "
                                  "MaskedPolicySeat)"},
        "players": players,
        "sampling_offsets": "none: no pair has the same checkpoint on both sides",
        "pairs": pairs,
        "pair_notes": {
            "1": f"{S} v chain37: the search seat against held-out chain 37",
            "2": f"{C} v chain37: its control on the same seeds",
            "3": f"{S} v chain46: the search seat against held-out chain 46",
            "4": f"{C} v chain46: its control on the same seeds",
            "5": f"{SINF} v chain37: identity sample, delta inf, the first game indexes of shard 1",
        },
        "checkpoints_sha256": CHECKPOINTS,
        "bots": {},
        "machine": f"DigitalOcean droplets {args.droplet_size} in sfo3, one per shard, "
                   "tools/droplet_tournament.py run at the harness commit; 8 workers, one game "
                   "per worker",
        "droplet_size": args.droplet_size,
        "max_hours": args.max_hours,
        "shards": shards,
        "launch": {
            "script": "launch_from_plan.py",
            "runner": "tools/droplet_tournament.py",
            "runner_sha256": sha256_file(os.path.join(tools, "droplet_tournament.py")),
            "rule": "refuses unless this file hashes to the committed sha256, both checkouts are "
                    "clean at their commits, every checkpoint blob has its registered sha256, the "
                    "runner is the registered one, and the shards' index slices cover every pair "
                    "exactly once from index 0"},
        "merge": "tools/droplet_tournament.py merge --out <run_dir> --shard <each shard>/main "
                 "(shards must share commit, seed block, settings, torch and compiled shim; a "
                 "pair's index slices must be disjoint and cover it from index 0 without a gap)",
        "acceptance": {
            "script": "accept_from_plan.py",
            "tool": "tools/gate_acceptance.py at the harness commit",
            "tool_sha256": sha256_file(os.path.join(tools, "gate_acceptance.py")),
            "search_tool": "tools/search_acceptance.py at the harness commit",
            "search_tool_sha256": sha256_file(os.path.join(tools, "search_acceptance.py")),
            "against": "this file, whose sha256 is committed to the ledger before launch"},
        "search": {
            "reward_manifest_sha256": search_module.REWARD_MANIFEST_SHA256,
            "integrity_checks": list(search_module.INTEGRITY_CHECKS),
            "cap_rejection_ceiling": 0.01,
            "identity": [{"search": [SINF, "chain37"], "plain": [C, "chain37"]}]},
        "scoring": {
            "script": "score_from_plan.py",
            "rule": "merge, then accept_from_plan.py, then the report, contrasts and diagnostics "
                    "only if accepted"},
        "statistic": "decisive-Elo with 95% seed-cluster intervals from "
                     "play_harness.tournament_stats (report.json, report.txt), 2,000 replicates",
        "contrasts": {
            "script": "paired_contrasts.py",
            "replicates": 2000, "generator_seed": 0,
            "sets": [{"name": f"label ({S} minus {C})", "arm": S, "control": C,
                      "opponents": ["chain37", "chain46"], "run_dir": "<run_dir>",
                      "outputs": ["chain37_contrast.json", "chain46_contrast.json"]}]},
        "diagnostics": {
            "script": "gate_diagnostics.py",
            "registered": "the style table per side for pairs 1 to 4 and the search seat's "
                          "statistics for pairs 1 and 3 against their controls",
            "pairs": main_pairs,
            "search_pairs": [{"search": [S, "chain37"], "control": [C, "chain37"]},
                             {"search": [S, "chain46"], "control": [C, "chain46"]}]},
        "reading": "labels are applied by the operator from these outputs, in the order the "
                   "ledger entry registers",
    }
    for block, key in (("launch", "script"), ("acceptance", "script"), ("scoring", "script"),
                       ("contrasts", "script"), ("diagnostics", "script")):
        plan[block]["script_sha256"] = sha256_file(os.path.join(out_dir, plan[block][key]))
    plan_path = os.path.join(out_dir, "PLAN.json")
    with open(plan_path, "w") as f:
        json.dump(plan, f, indent=1)
        f.write("\n")
    plan_sha = sha256_file(plan_path)
    with open(plan_path + ".sha256", "w") as f:
        f.write(f"{plan_sha}  PLAN.json\n")
    with open(os.path.join(out_dir, "SCRIPTS.sha256"), "w") as f:
        for name in SCRIPTS:
            f.write(f"{sha256_file(os.path.join(out_dir, name))}  {name}\n")
        f.write(f"{plan_sha}  PLAN.json\n")
    print(plan_path, plan_sha)


if __name__ == "__main__":
    main()
