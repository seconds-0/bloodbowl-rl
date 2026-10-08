#!/usr/bin/env python3
"""Write PLAN.json, PLAN.json.sha256 and SCRIPTS.sha256 for the temperature control (or its smoke).

  python make_plan.py --out-dir DIR --gate NAME --registered-in TEXT --seed0 N \\
      --games-per-pair N --shards N --max-hours H --reference-gate NAME

The scripts beside this file are copied into DIR when DIR is another directory,
so a smoke runs the same scripts as the gate. Players, pairs, contrasts and
diagnostics are fixed here: chain 55 + m1 at temperature 0.75 (T075), 0.5 (T05),
0.25 (T025) and 1 (C, a replay), each against chain 37 and chain 46. No player
searches. Every shard plays the same slice of game indexes for all eight pairs,
so no arm is tied to a machine.

--reference-gate names a finished search gate (or its smoke) under the output
root that played the same seed block: its accepted record file is hash-pinned
here, C's games must equal its C games (accept_from_plan.py), and its search
seat's games enter the margin contrasts (score_from_plan.py). The reference
directory is only read.
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
S, C = "c55m1s", "c55m1"
ARMS = (("c55m1t075", 0.75), ("c55m1t05", 0.5), ("c55m1t025", 0.25))
OPPONENTS = ("chain37", "chain46")
REPLAY_FIELDS = ["action_trail_sha256", "final_digest", "score", "c_steps", "decisions",
                 "engine_decisions", "team_ids", "sampling_seeds", "turns", "half", "final_status"]


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
    ap.add_argument("--reference-gate", required=True,
                    help="directory name under the output root of the search gate (or smoke) "
                         "that played this seed block")
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--max-hours", type=float, required=True)
    ap.add_argument("--droplet-size", default="s-8vcpu-16gb-amd")
    args = ap.parse_args()

    root, main_root = os.path.expanduser(WORKTREE), os.path.expanduser(MAIN)
    if git(root, "status", "--porcelain"):
        raise SystemExit(f"{root} is not clean")
    commit = git(root, "rev-parse", "HEAD")
    sys.path.insert(0, root)

    seeds = args.games_per_pair // 2
    if args.games_per_pair % 2 or seeds % args.shards:
        raise SystemExit("games per pair must split evenly into the shards' index slices")
    per = seeds // args.shards
    out_root = os.path.expanduser(f"{MAIN}/.play-artifacts/tournaments")
    ref_dir = os.path.join(out_root, args.reference_gate, "main")
    with open(os.path.join(ref_dir, "manifest.json")) as f:
        ref_manifest = json.load(f)
    with open(os.path.join(os.path.dirname(ref_dir), "PLAN.json")) as f:
        ref_plan = json.load(f)
    ref_pairs = {(a, b): int(n) for a, b, n in ref_manifest["pairs"]}
    for name in (S, C):
        for opp in OPPONENTS:
            if ref_pairs.get((name, opp), 0) < args.games_per_pair:
                raise SystemExit(f"the reference run did not play {args.games_per_pair} games of {name},{opp}")
    if ref_manifest["seed0"] != args.seed0:
        raise SystemExit(f"the reference run's seed block is {ref_manifest['seed0']}, not {args.seed0}")
    if ref_plan["players"][C] != {"checkpoint": "chain55", "masks": ["m1"]} or \
            ref_plan["checkpoints_sha256"] != CHECKPOINTS:
        raise SystemExit("the reference plan's control or checkpoints are not this plan's")
    out_dir = os.path.abspath(os.path.expanduser(args.out_dir))
    os.makedirs(out_dir, exist_ok=True)
    if out_dir != HERE:
        for name in SCRIPTS:
            shutil.copyfile(os.path.join(HERE, name), os.path.join(out_dir, name))

    players = {name: {"checkpoint": "chain55", "masks": ["m1"], "temperature": t} for name, t in ARMS}
    players[C] = {"checkpoint": "chain55", "masks": ["m1"]}
    for opp in OPPONENTS:
        players[opp] = {"checkpoint": opp, "masks": []}
    main_pairs = [[name, opp] for opp in OPPONENTS for name in [a for a, _t in ARMS] + [C]]
    pairs = [[a, b, args.games_per_pair] for a, b in main_pairs]
    shards = {}
    for j in range(args.shards):
        shards[f"{args.gate}-s{j + 1}"] = {"index0": j * per,
                                           "pairs": [f"{a},{b},{2 * per}" for a, b in main_pairs]}
    contrast_sets = []
    for name, _t in ARMS:
        tag = name[len(C):]
        contrast_sets.append({"name": f"gain ({name} minus {C})", "arm": name, "control": C,
                              "opponents": list(OPPONENTS), "run_dir": f"<run_dir>/gain_{tag}",
                              "outputs": [f"gain_{tag}/{opp}_contrast.json" for opp in OPPONENTS]})
    for name, _t in ARMS:
        tag = name[len(C):]
        contrast_sets.append({"name": f"margin ({S} of the reference run minus {name})", "arm": S,
                              "control": name, "opponents": list(OPPONENTS),
                              "run_dir": f"<run_dir>/margin_{tag}",
                              "reference_pairs": [[S, opp] for opp in OPPONENTS],
                              "reference_games": args.games_per_pair * len(OPPONENTS),
                              "outputs": [f"margin_{tag}/{opp}_contrast.json" for opp in OPPONENTS]})
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
        "temperature": "1.0 for every player whose entry in 'players' names no temperature",
        "temperature_definition": "play_harness/policy.py select_joint divides every head's logits by "
                                  "T before masking and selection: each head's conditional "
                                  "distribution is tempered, not the joint",
        "starts": "kickoff",
        "legs": ["A_home", "B_home"],
        "mask_definition": {"m1": "END_TURN is removed from the masked seat's exact joint support "
                                  "while an ACTIVATE is also legal; the policy is renormalized over "
                                  "what is left (play_harness/policy.py restrict_support, "
                                  "MaskedPolicySeat)"},
        "players": players,
        "sampling_offsets": "none: no pair has the same checkpoint on both sides",
        "pairs": pairs,
        "pair_notes": {str(i + 1): (f"{a} v {b}: " + ("the control at temperature 1, a replay of the "
                                                      "reference run's games" if a == C else
                                                      f"chain 55 + m1 at temperature {players[a]['temperature']}"))
                       for i, (a, b) in enumerate(main_pairs)},
        "reference": {
            "gate": args.reference_gate,
            "run_dir": f"{MAIN}/.play-artifacts/tournaments/{args.reference_gate}/main",
            "games_sha256": sha256_file(os.path.join(ref_dir, "games.jsonl")),
            "library_sha256": ref_manifest["library_sha256"],
            "harness_commit": ref_manifest["harness_git_head"],
            "replay": [{"pair": [C, opp], "reference_pair": [C, opp]} for opp in OPPONENTS],
            "fields": REPLAY_FIELDS,
            "rule": "every game of the replayed pairs equals the reference run's game on the same "
                    "engine seed and leg in the listed fields and in its seats; this run's compiled "
                    "library is the reference run's; reference records on engine seeds outside this "
                    "plan's block of games_per_pair / 2 seeds are not used; the reference directory "
                    "is only read"},
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
        "scoring": {
            "script": "score_from_plan.py",
            "rule": "merge, then accept_from_plan.py (four checks), then the report, contrasts and "
                    "diagnostics only if accepted"},
        "statistic": "decisive-Elo with 95% seed-cluster intervals from "
                     "play_harness.tournament_stats (report.json, report.txt), 2,000 replicates",
        "contrasts": {
            "script": "paired_contrasts.py",
            "replicates": 2000, "generator_seed": 0,
            "sets": contrast_sets},
        "diagnostics": {
            "script": "gate_diagnostics.py",
            "registered": "the style table per side for the eight pairs",
            "pairs": main_pairs,
            "search_pairs": []},
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
