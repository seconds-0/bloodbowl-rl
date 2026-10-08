#!/usr/bin/env python3
"""Write the search-distillation plan (PLAN.json or one of its rehearsal twins) and print its sha256.

The plan binds what PLAN.md fixes in words: the checkpoint by blob and sidecar
hash, the seed block and its shards, the label settings, the split rule, the
fine-tune's settings and its selection rule, the harness commit, the reward
manifest, the label tool's integrity checks, and by hash every tool file
(tool_sha256), the droplet launcher (launcher_sha256) and the harness's
droplet lifecycle file as exported. Every tool
refuses to run against a plan whose hash is not the one handed to it and when
any tool file is not the one the plan names. Rerun this after any edit to a
tool file or to a constant below, before the plan is committed; never after.

  make_plan.py --harness EXPORT --kind registered            # PLAN.json
  make_plan.py --harness EXPORT --kind m0                    # PLAN.m0.json, the seen block
  make_plan.py --harness EXPORT --kind rehearsal             # PLAN.rehearsal.json, 300 games
  make_plan.py --harness EXPORT --kind smoke                 # PLAN.smoke.json, 16 games
  make_plan.py --harness EXPORT --kind dev --out FILE        # a few games, for tool work

The gate has its own plan, written by gate/make_plan.py once the three blobs exist.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.dont_write_bytecode = True
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import distill_common as C  # noqa: E402

LIFECYCLE = "tools/droplet_tournament.py"
HARNESS_COMMIT = "5ab3ab6e195afbb717d7e0e7e62361a3b548fdd6"   # feat/search-probe-20261007
CHECKPOINT = ("chain55", "f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b")
# The seat's registered setting (D430): candidates, rollouts, delta, masks. The
# judgment and the samples per game are this plan's.
LABEL = {"per_class": 15, "other_per_game": 64, "candidates": 4, "screen_rollouts": 16,
         "delta": 0.10, "judge_pairs": 128, "judge_first_index": 1000, "judge_min_pairs": 64,
         "masks": ["m1"], "scope": ["turn", "after_declare"], "gamma": 0.999,
         "max_rollout_steps": 200, "cap_rejection_ceiling": 0.01}
REDUCED = {"screen_rollouts": 4, "judge_pairs": 8, "judge_min_pairs": 4}
REDUCED_STEPS = 1200          # optimizer steps of a rehearsal's fine-tune (registered: 2,400)
# name -> (seed0, [(shard, first game, games)], label overrides, purpose)
KINDS = {
    "registered": (26000000,
                   [("m1-s1", 0, 500), ("m1-s2", 500, 500)]
                   + [(f"m2-s{j + 1}", 1000 + 1500 * j, 1500) for j in range(6)],
                   {}, "PLAN.md beside this file"),
    "m0": (29100000, [("m0", 0, 200)], {},
           "milestone 0: the seen block of 2026-10-07, never evidence"),
    "rehearsal": (29980100, [("rehearsal", 0, 300)], REDUCED,
                  "the wide rehearsal at reduced rollouts and reduced fine-tune steps, never "
                  "evidence"),
    "smoke": (29980400, [("smoke", 0, 16)], {}, "droplet smoke, never evidence"),
    "dev": (29980500, [("dev", 0, 6)], REDUCED, "tool development, never evidence"),
}
OUT = {"registered": "PLAN.json", "m0": "PLAN.m0.json", "rehearsal": "PLAN.rehearsal.json",
       "smoke": "PLAN.smoke.json"}
# Recipe R1, three arms. `steps` optimizer steps over fixed chunks of at most
# `chunk` examples; at the registered size that is about 30 passes.
FINETUNE = {
    "recipe": "R1", "trained": ["decoder.decoder.weight"],
    "arms": {"c55d1l1": 1.0, "c55d1l4": 4.0, "c55d1l16": 16.0},
    "optimizer": "Adam", "learning_rate": 0.001, "steps": 2400, "chunk": 8192, "seed": 0,
    "precision": "float64 training on float32 features; the blob is float32",
    "loss": "[lambda * sum over deviation roots of w * (-log p(label)) + sum over the other "
            "loss decisions of w * KL(p0 || p)] / (sum of w); KL over the tuples of the "
            "joint support",
    "fit": {"arm": "c55d1l16", "threshold": 0.80,
            "statistic": "weighted mean probability of the label on training deviation roots"},
    "selection": {
        "statistic": "J = q * M * g - price * U on the validation games, no rollouts",
        "price": 0.016,
        "rule": "the registered arm is the eligible arm with the highest J; ties go to the "
                "smaller lambda; an arm whose J is not finite, or whose blob fails its "
                "acceptance, is not eligible; with no eligible arm there is no registered "
                "arm, the gate is not played and the plan stops unread"},
}
SECONDS = {"droplet_plain_game": 8.0, "droplet_screened_root": 1.84,
           "droplet_judgment": 7.4, "setup": 420}


def integrity_checks():
    """The label tool's own list, read from its source so the plan and the tool cannot drift."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("distill_screen_for_plan",
                                                  os.path.join(HERE, "distill_screen.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return list(module.INTEGRITY_CHECKS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", required=True, help="the export of the pinned harness commit")
    ap.add_argument("--kind", required=True, choices=sorted(KINDS))
    ap.add_argument("--store", default=os.path.expanduser(
        "~/Code/bb-play-harness/.play-artifacts/checkpoints"))
    ap.add_argument("--out", default=None)
    ap.add_argument("--games", type=int, default=None, help="dev only: the number of games")
    args = ap.parse_args(argv)
    with open(os.path.join(args.harness, "SOURCE_COMMIT")) as f:
        commit = f.read().strip()
    if commit != HARNESS_COMMIT:
        raise SystemExit(f"the export is at {commit}, the pin is {HARNESS_COMMIT}")
    name, sha = CHECKPOINT
    blob = os.path.join(args.store, name, C.BLOB)
    if not os.path.isfile(blob) or not os.path.isfile(blob + ".lineage.json"):
        raise SystemExit(f"missing {blob} or its lineage sidecar")
    if C.sha256_file(blob) != sha:
        raise SystemExit(f"{blob} does not hash to {sha}")
    seed0, shards, overrides, purpose = KINDS[args.kind]
    if args.kind == "dev" and args.games:
        shards = [("dev", 0, int(args.games))]
    elif args.games:
        raise SystemExit("--games is for --kind dev only")
    out = args.out or (os.path.join(HERE, OUT[args.kind]) if args.kind in OUT else None)
    if out is None:
        raise SystemExit("--kind dev needs --out")
    label = {"seed0": seed0, **LABEL, **overrides}
    finetune = dict(FINETUNE)
    if args.kind in ("rehearsal", "dev"):
        finetune["steps"] = REDUCED_STEPS
    games = sum(n for _, _, n in shards)
    manifest = os.path.join(args.harness, "puffer", "config", "rewards", "r0_poss_half.json")
    per_game = SECONDS["droplet_plain_game"] + 2 * label["per_class"] * \
        SECONDS["droplet_screened_root"] * label["screen_rollouts"] / 16.0 + \
        0.42 * SECONDS["droplet_judgment"] * label["judge_pairs"] / 128.0
    plan = {
        "schema": C.PLAN_SCHEMA,
        "name": f"search-distill-{args.kind}",
        "purpose": purpose,
        "harness_commit": commit,
        "harness_branch": "feat/search-probe-20261007",
        "reward_manifest": "r0_poss_half",
        "reward_manifest_sha256": "433c792018acdc01f8c7168e824c9389bf99df2307d3260283b7877df3f69d5c",
        "reward_manifest_file_sha256": C.sha256_file(manifest),
        "tool_sha256": C.tool_sha256(),
        "launcher_sha256": {C.LAUNCHER_FILE: C.sha256_file(os.path.join(HERE, C.LAUNCHER_FILE))
                            if os.path.isfile(os.path.join(HERE, C.LAUNCHER_FILE)) else None},
        "lifecycle_sha256": {LIFECYCLE: C.sha256_file(os.path.join(args.harness, LIFECYCLE))},
        "integrity_checks": integrity_checks(),
        "checkpoint": {"name": name, "sha256": sha, "blob": f"{name}/{C.BLOB}",
                       "sidecar_sha256": C.sha256_file(blob + ".lineage.json")},
        "play": {"temperature": 1.0, "starts": "kick-off",
                 "seat_a": "game index parity (even: HOME)",
                 "opponent": "the same checkpoint under the same masks, sampling seed offset "
                             "by one stride"},
        "label": label,
        "games": games,
        "shards": [{"name": n, "first_game": first, "games": count}
                   for n, first, count in shards],
        "split": {"rule": "group = ((engine seed - seed0) // 2) % 10",
                  "groups": {"train": [0, 1, 2, 3, 4, 5, 6], "validation": [7], "test": [8],
                             "reserve": [9]},
                  "reserve": "never written by the dataset tool under this plan"},
        "finetune": finetune,
        "bootstrap": {"cluster": "engine seed", "replicates": 2000, "generator_seed": 0},
        "estimate": {"droplet_seconds_per_game": round(per_game, 1),
                     "setup_seconds": SECONDS["setup"]},
    }
    text = json.dumps(plan, indent=1) + "\n"
    with open(out, "w") as f:
        f.write(text)
    print(out)
    print("sha256", hashlib.sha256(text.encode()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
