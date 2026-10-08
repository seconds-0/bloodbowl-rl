#!/usr/bin/env python3
"""Write PLAN.json, PLAN.json.sha256 and SCRIPTS.sha256 for the search-distillation gate (or a Mac rehearsal of it).

  python make_plan.py --out-dir DIR --gate NAME --registered-in TEXT --seed0 N \\
      --games-per-pair N --shards N --max-hours H \\
      --finetune DIR --expect-selection-sha256 S [--local]

The scripts beside this file are copied into DIR when DIR is another directory,
so a rehearsal runs the same scripts as the gate. The players and pairs are
fixed here: the three fine-tuned arms of chain 55 the fine-tune directory's
SELECTION.json lists (lambda 1, 4 and 16), each under m1, and the control C
(chain 55 under m1), each against chain 37 and chain 46: eight pairs. No
player searches. Every arm is played in the batched path, 32 games per worker.
Every shard plays the same slice of game indexes for all eight pairs, so no
arm is tied to a machine.

One arm is the registered arm: SELECTION.json names it, chosen on validation
games before any gate game. Its two contrasts against C carry the label. The
other two arms are registered as a descriptive dose-response and carry none.

SELECTION.json must hash to --expect-selection-sha256. Every arm's blob and
sidecar must hash to the values it binds; both hashes go into the plan, and
the launcher and the acceptance check both again.

--local writes a plan for a rehearsal on this machine (play_local_from_plan.py):
its name must start with "distill-mac-", it has one shard, and the launcher
refuses it.
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
BLOB = "0000002999975936.bin"
SCRIPTS = ("accept_from_plan.py", "launch_from_plan.py", "play_local_from_plan.py",
           "gate_diagnostics.py", "paired_contrasts.py", "score_from_plan.py", "make_plan.py")
CHAINS = {
    "chain55": "f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b",
    "chain37": "268f1db08ca0c2bad88293ea56b3048a2a1c3a0ea9acdf0365fc023186c0f73f",
    "chain46": "8eee9ac10f58eca57092013ac05db6f28fb5f7f2c6dc9ce850960c7bb2c7c467",
}
C = "c55m1"
OPPONENTS = ("chain37", "chain46")
GAMES_PER_WORKER = 32
LOCAL_PREFIX = "distill-mac-"
READING = {
    "statistic": "the registered arm minus C against chain 37 and against chain 46, "
                 "decisive-Elo, 95% seed-cluster intervals",
    "order": ["Unread", "Negative", "Positive", "Flat", "Inconclusive"],
    "Unread": "a contrast or an end of its interval is missing or not finite",
    "Negative": "either interval entirely below zero (upper end below 0)",
    "Positive": "both point estimates at +15 or more and both intervals entirely above "
                "zero (lower end above 0)",
    "Flat": "both intervals inside -15 to +15, ends included",
    "Inconclusive": "anything else",
    "positive_point": 15.0, "flat_bound": 15.0,
}


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
    ap.add_argument("--shards", type=int, required=True)
    ap.add_argument("--max-hours", type=float, required=True)
    ap.add_argument("--finetune", required=True,
                    help="the fine-tune's output directory (SELECTION.json and checkpoints/)")
    ap.add_argument("--expect-selection-sha256", required=True)
    ap.add_argument("--droplet-size", default="s-8vcpu-16gb-amd")
    ap.add_argument("--local", action="store_true")
    args = ap.parse_args()

    if args.local != args.gate.startswith(LOCAL_PREFIX):
        raise SystemExit(f"a --local plan, and only one, is named {LOCAL_PREFIX}...")
    if args.local and args.shards != 1:
        raise SystemExit("a local rehearsal has one shard")
    root, main_root = os.path.expanduser(WORKTREE), os.path.expanduser(MAIN)
    if git(root, "status", "--porcelain"):
        raise SystemExit(f"{root} is not clean")
    commit = git(root, "rev-parse", "HEAD")
    finetune = os.path.abspath(os.path.expanduser(args.finetune))
    selection_path = os.path.join(finetune, "SELECTION.json")
    selection_sha = sha256_file(selection_path)
    if selection_sha != args.expect_selection_sha256.strip().lower():
        raise SystemExit(f"{selection_path} hashes to {selection_sha}, not to "
                         "--expect-selection-sha256")
    with open(selection_path) as f:
        selection = json.load(f)
    registered = selection.get("registered_arm")
    if selection["fit"]["reading"] != "FIT" or not registered:
        raise SystemExit("the selection has no registered arm (fit "
                         f"{selection['fit']['reading']}): no gate is played")
    if selection["base_checkpoint_sha256"] != CHAINS["chain55"]:
        raise SystemExit("the selection's arms are not fine-tunes of chain 55")
    arms = sorted(selection["arms"], key=lambda name: selection["arms"][name]["lambda"])
    ineligible = [a for a in arms if not selection["arms"][a].get("eligible")]
    if ineligible:
        raise SystemExit(f"arms that are not eligible cannot be gated: {ineligible}")

    seeds = args.games_per_pair // 2
    if args.games_per_pair % 2 or seeds % args.shards:
        raise SystemExit("games per pair must split evenly into the shards' index slices")
    per = seeds // args.shards
    store = os.path.join(main_root, ".play-artifacts", "checkpoints")
    paths = {name: os.path.join(store, name, BLOB) for name in CHAINS}
    shas = dict(CHAINS)
    for arm in arms:
        paths[arm] = os.path.join(finetune, selection["arms"][arm]["blob"])
        shas[arm] = selection["arms"][arm]["blob_sha256"]
    sidecars = {}
    for name, path in paths.items():
        if not os.path.isfile(path) or not os.path.isfile(path + ".lineage.json"):
            raise SystemExit(f"missing {path} or its lineage sidecar")
        if sha256_file(path) != shas[name]:
            raise SystemExit(f"{path} is not the registered {name}")
        sidecars[name] = sha256_file(path + ".lineage.json")
    for arm in arms:
        if sidecars[arm] != selection["arms"][arm]["sidecar_sha256"]:
            raise SystemExit(f"{arm}: the sidecar on disk is not the one the selection binds")

    out_dir = os.path.abspath(os.path.expanduser(args.out_dir))
    os.makedirs(out_dir, exist_ok=True)
    if out_dir != HERE:
        for name in SCRIPTS:
            shutil.copyfile(os.path.join(HERE, name), os.path.join(out_dir, name))

    players = {arm: {"checkpoint": arm, "masks": ["m1"]} for arm in arms}
    players[C] = {"checkpoint": "chain55", "masks": ["m1"]}
    for opp in OPPONENTS:
        players[opp] = {"checkpoint": opp, "masks": []}
    main_pairs = [[name, opp] for opp in OPPONENTS for name in arms + [C]]
    pairs = [[a, b, args.games_per_pair] for a, b in main_pairs]
    shards = {}
    for j in range(args.shards):
        shards[f"{args.gate}-s{j + 1}"] = {"index0": j * per,
                                           "pairs": [f"{a},{b},{2 * per}" for a, b in main_pairs]}
    contrast_sets = []
    for arm in arms:
        kind = "label" if arm == registered else "dose"
        contrast_sets.append({
            "name": (f"label: the registered arm {arm} minus {C}" if arm == registered else
                     f"descriptive dose-response, no label: {arm} minus {C}"),
            "arm": arm, "control": C, "opponents": list(OPPONENTS), "label": arm == registered,
            "run_dir": f"<run_dir>/{kind}_{arm}",
            "outputs": [f"{kind}_{arm}/{opp}_contrast.json" for opp in OPPONENTS]})
    tools = os.path.join(root, "tools")
    run_dir = f"{MAIN}/.play-artifacts/tournaments/{args.gate}/main"
    plan = {
        "gate": args.gate,
        "registered_in": args.registered_in,
        "local_rehearsal": bool(args.local),
        "written_before_launch_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "harness_commit": commit,
        "harness_worktree": WORKTREE,
        "harness_branch": git(root, "branch", "--show-current"),
        "main_checkout": MAIN,
        "main_checkout_commit": git(main_root, "rev-parse", "HEAD"),
        "out_root": f"{MAIN}/.play-artifacts/tournaments",
        "log_dir": f"{MAIN}/.play-artifacts/logs",
        "run_dir": run_dir,
        "seed0": args.seed0,
        "games_per_pair": args.games_per_pair,
        "total_games": sum(n for _a, _b, n in pairs),
        "games_per_worker": GAMES_PER_WORKER,
        "batching": "every arm is played in the batched path, 32 games per worker. A batch "
                    "changes float rounding in the matrix products, so a rare game differs "
                    "from its unbatched twin: D434's contrasts (one game per worker) stay a "
                    "descriptive comparison",
        "mode": "sample",
        "kernel": "native",
        "temperature": "1.0 for every player",
        "starts": "kickoff",
        "legs": ["A_home", "B_home"],
        "mask_definition": {"m1": "END_TURN is removed from the masked seat's exact joint support "
                                  "while an ACTIVATE is also legal; the policy is renormalized over "
                                  "what is left (play_harness/policy.py restrict_support, "
                                  "MaskedPolicySeat)"},
        "players": players,
        "sampling_offsets": "none: no pair has the same checkpoint on both sides",
        "pairs": pairs,
        "pair_notes": {str(i + 1): (f"{a} v {b}: " + (
            "the control, chain 55 under m1" if a == C else
            f"chain 55 fine-tuned by recipe R1 at lambda {selection['arms'][a]['lambda']}, "
            "under m1" + (" (the registered arm)" if a == registered else "")))
            for i, (a, b) in enumerate(main_pairs)},
        "selection": {"file": selection_path, "sha256": selection_sha,
                      "plan_sha256": selection["plan_sha256"], "registered_arm": registered,
                      "arms": {a: selection["arms"][a]["lambda"] for a in arms},
                      "rule": selection["rule"]},
        "checkpoints_sha256": shas,
        "sidecars_sha256": sidecars,
        "checkpoint_paths": paths,
        "bots": {},
        "machine": ("this Mac, one process (play_local_from_plan.py)" if args.local else
                    f"DigitalOcean droplets {args.droplet_size} in sfo3, one per shard, "
                    "tools/droplet_tournament.py run at the harness commit; 8 workers, 32 games "
                    "per worker"),
        "droplet_size": args.droplet_size,
        "max_hours": args.max_hours,
        "shards": shards,
        "launch": {
            "script": "launch_from_plan.py",
            "local_script": "play_local_from_plan.py",
            "local_script_sha256": sha256_file(os.path.join(out_dir, "play_local_from_plan.py")),
            "runner": "tools/droplet_tournament.py",
            "runner_sha256": sha256_file(os.path.join(tools, "droplet_tournament.py")),
            "rule": "refuses unless this file hashes to the committed sha256, both checkouts are "
                    "clean at their commits, every checkpoint blob and sidecar has its "
                    "registered sha256, the runner is the registered one, and the shards' index "
                    "slices cover every pair exactly once from index 0"},
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
            "rule": "merge, then accept_from_plan.py (four checks), then the report, the "
                    "contrasts, the reading and the diagnostics only if accepted"},
        "statistic": "decisive-Elo with 95% seed-cluster intervals from "
                     "play_harness.tournament_stats (report.json, report.txt), 2,000 replicates",
        "contrasts": {
            "script": "paired_contrasts.py",
            "replicates": 2000, "generator_seed": 0,
            "sets": contrast_sets},
        "reading": READING,
        "diagnostics": {
            "script": "gate_diagnostics.py",
            "registered": "the style table per side for the eight pairs, and the share of "
                          "seed-legs where an arm's game is C's game",
            "pairs": main_pairs,
            "search_pairs": []},
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
