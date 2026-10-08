#!/usr/bin/env python3
"""Write the END_TURN probe's machine-readable plan (PLAN.json) and print its sha256.

The plan binds what PLAN.md fixes in words: the checkpoints by hash, the seed
block, the sizes, the harness commit, the reward manifest, the probe's
integrity checks, and by hash every file that takes part: the three files that
run on a droplet (tool_sha256), the launcher, the acceptance rules and the
analysis (local_sha256), and the harness's droplet lifecycle file as exported
(lifecycle_sha256). The probe, the launcher and the analysis each refuse to
run against a plan whose hash is not the one handed to them, against inputs
that are not the plan's, and when their own file is not the one the plan
names. Rerun this after any edit to one of those files or to a constant below,
before the plan is committed; never after.

  make_plan.py --harness EXPORT [--store DIR] [--out PLAN.json]
  make_plan.py --harness EXPORT --smoke --out PLAN.smoke.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_FILES = ("endturn_probe.py", "endturn_shim.c", "build_shim.sh")
LOCAL_FILES = ("endturn_droplet.py", "endturn_accept.py", "endturn_analyze.py")
LIFECYCLE = "tools/droplet_tournament.py"
HARNESS_COMMIT = "06f0a5f7e67cc9089e8edaf5fa9b97dcfe440d99"   # feat/search-probe-20261007
BLOB = "0000002999975936.bin"
# name -> (sha256, what it is). chain60 is added by --with-chain60 SHA once its stage has ended.
CHECKPOINTS = {
    "chain55": ("f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b",
                "from chain 49, lambda 0.95, training seed 42"),
    "chain58": ("a03ed6084b7500cd0c09c89244a79d2ec93059c8cfd1bf98611ef03f22d6ec19",
                "from chain 49, lambda 0.97, training seed 42"),
    "chain59": ("7346125415fecb938fe76e29af4640f4496d8f44fe3d70df6ce63d509b422d12",
                "from chain 49, lambda 0.95, training seed 2042"),
    "chain49": ("a2d1d10dcea3967298e1359efdf831ebe96db19b349f3eca31c81587c7e8bce0",
                "the parent of the three"),
}
SETTINGS = {"seed0": 29960000, "games": 200, "rollouts": 64, "cap_end_turn": 24,
            "cap_decline_block": 12, "cap_activate": 4, "match_roots": 3,
            "match_rollouts": 64, "alternatives": 3}
SMOKE = {"seed0": 29940000, "games": 2, "rollouts": 16, "cap_end_turn": 24,
         "cap_decline_block": 12, "cap_activate": 4, "match_roots": 2,
         "match_rollouts": 16, "alternatives": 3}
# Seconds of one droplet (8 processes busy) per game at SETTINGS: see PLAN.md, "Cost".
DROPLET_SECONDS_PER_GAME = 32.0


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def integrity_checks():
    """The probe's own list, read from its source so the plan and the tool cannot drift."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("endturn_probe_for_plan",
                                                  os.path.join(HERE, "endturn_probe.py"))
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return list(module.INTEGRITY_CHECKS)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--harness", required=True, help="the export of the pinned harness commit")
    ap.add_argument("--store", default=os.path.expanduser(
        "~/Code/bb-play-harness/.play-artifacts/checkpoints"))
    ap.add_argument("--out", default=os.path.join(HERE, "PLAN.json"))
    ap.add_argument("--smoke", action="store_true", help="the two-game smoke plan")
    ap.add_argument("--with-chain60", default=None, metavar="SHA256",
                    help="add chain 60 (lambda 0.97, training seed 2042) by its hash")
    args = ap.parse_args(argv)
    with open(os.path.join(args.harness, "SOURCE_COMMIT")) as f:
        commit = f.read().strip()
    if commit != HARNESS_COMMIT:
        raise SystemExit(f"the export is at {commit}, the pin is {HARNESS_COMMIT}")
    checkpoints = dict(CHECKPOINTS)
    if args.with_chain60:
        checkpoints["chain60"] = (args.with_chain60, "from chain 49, lambda 0.97, training seed 2042")
    if args.smoke:
        checkpoints = {k: checkpoints[k] for k in ("chain55", "chain58")}
    for name, (sha, _) in checkpoints.items():
        path = os.path.join(args.store, name, BLOB)
        if not os.path.isfile(path) or not os.path.isfile(path + ".lineage.json"):
            raise SystemExit(f"missing {path} or its lineage sidecar")
        if sha256_file(path) != sha:
            raise SystemExit(f"{path} does not hash to {sha}")
    manifest = os.path.join(args.harness, "puffer", "config", "rewards", "r0_poss_half.json")
    plan = {
        "schema": "endturn-probe-plan-v1",
        "name": "endturn-smoke" if args.smoke else "endturn-probe-20261008",
        "purpose": "smoke, not evidence" if args.smoke else "PLAN.md beside this file",
        "harness_commit": commit,
        "harness_branch": "feat/search-probe-20261007",
        "reward_manifest": "r0_poss_half",
        "reward_manifest_sha256": "433c792018acdc01f8c7168e824c9389bf99df2307d3260283b7877df3f69d5c",
        "reward_manifest_file_sha256": sha256_file(manifest),
        "tool_sha256": {name: sha256_file(os.path.join(HERE, name)) for name in TOOL_FILES},
        "local_sha256": {name: sha256_file(os.path.join(HERE, name)) for name in LOCAL_FILES},
        "lifecycle_sha256": {LIFECYCLE: sha256_file(os.path.join(args.harness, LIFECYCLE))},
        "integrity_checks": integrity_checks(),
        "checkpoints": {name: {"sha256": sha, "blob": f"{name}/{BLOB}", "what": what}
                        for name, (sha, what) in checkpoints.items()},
        "settings": SMOKE if args.smoke else SETTINGS,
        "play": {"masks": [], "temperature": 1.0, "starts": "kick-off",
                 "seat_a": "game index parity (even: HOME)",
                 "opponent": "the same checkpoint, sampling seed offset by one stride"},
        "shards": [{"name": name, "checkpoints": [name]} for name in checkpoints],
        "bootstrap": {"cluster": "engine seed", "replicates": 2000, "generator_seed": 0},
        "estimate": {"droplet_seconds_per_game": DROPLET_SECONDS_PER_GAME,
                     "setup_seconds": 420},
    }
    text = json.dumps(plan, indent=1) + "\n"
    with open(args.out, "w") as f:
        f.write(text)
    print(args.out)
    print("sha256", hashlib.sha256(text.encode()).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
