#!/usr/bin/env python3
"""Merge, accept and score the search-distillation gate from PLAN.json. Nothing is scored unless acceptance passes.

  python score_from_plan.py --expect-sha256 <sha256 of PLAN.json>

Order: refuse unless PLAN.json hashes to the committed value and the scripts
beside it hash to the values the plan records; merge the shards (skipped when
the run directory exists already, which is the merge-free path of a local
rehearsal); run accept_from_plan.py (the stock acceptance tool, the mask
checks, the search acceptance tool and the sidecar check); only on
GATE-ACCEPTED, MASKS-ACCEPTED, SEARCH-ACCEPTED and SIDECARS-ACCEPTED write the
tournament report, the paired contrast sets, the reading and the diagnostics
the plan names.

The reading is applied here, by the plan's rule, to the registered arm's two
contrasts and to nothing else: Unread, Negative, Positive, Flat, Inconclusive,
first match in that order. The other arms' contrasts are printed as a
descriptive dose-response and carry no label. --shard-dir SHARD=NAME reads a
shard from another directory under the output root (a relaunched shard); the
default is the shard's own name.
"""
import argparse
import hashlib
import json
import math
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def reading(contrasts, rule):
    """The gate's label from the registered arm's contrasts: a list of
    (point, lo, hi) per opponent. First match in the plan's order."""
    values = [v for c in contrasts for v in c]
    if len(contrasts) != 2 or any(v is None or not isinstance(v, (int, float))
                                  or not math.isfinite(v) for v in values):
        return "Unread"
    if any(hi < 0.0 for _p, _lo, hi in contrasts):
        return "Negative"
    if all(p >= rule["positive_point"] and lo > 0.0 for p, lo, _hi in contrasts):
        return "Positive"
    if all(-rule["flat_bound"] <= lo and hi <= rule["flat_bound"] for _p, lo, hi in contrasts):
        return "Flat"
    return "Inconclusive"


def identical_games(games_path, arms, control, opponents):
    """Per arm and opponent: seed-legs where the arm's game has the control's action trail."""
    trails = {}
    with open(games_path) as f:
        for line in f:
            if line.strip():
                g = json.loads(line)
                trails[(g["pair"][0], g["pair"][1], g["engine_seed"], g["leg"])] = \
                    g["action_trail_sha256"]
    out = {}
    for arm in arms:
        for opp in opponents:
            keys = [k for k in trails if k[0] == arm and k[1] == opp]
            same = sum(trails.get((control, opp, k[2], k[3])) == trails[k] for k in keys)
            out[f"{arm} v {opp}"] = {"seed_legs": len(keys), "same_trail_as_control": same}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--expect-sha256", required=True)
    ap.add_argument("--shard-dir", action="append", default=[], metavar="SHARD=NAME")
    args = ap.parse_args()
    shard_dirs = dict(item.split("=", 1) for item in args.shard_dir)
    plan_path = os.path.join(HERE, "PLAN.json")
    got = sha256_file(plan_path)
    if got != args.expect_sha256.lower():
        raise SystemExit(f"plan hashes to {got}, not {args.expect_sha256}; nothing merged or scored")
    with open(plan_path) as f:
        plan = json.load(f)
    root = os.path.expanduser(plan["harness_worktree"])
    py = os.path.join(os.path.expanduser(plan["main_checkout"]), ".venv", "bin", "python")
    out_root = os.path.expanduser(plan["out_root"])
    main_dir = os.path.expanduser(plan["run_dir"])
    unknown = sorted(set(shard_dirs) - set(plan["shards"]))
    if unknown:
        raise SystemExit(f"--shard-dir names shards the plan does not have: {unknown}")
    for name, sha in ((plan["scoring"]["script"], plan["scoring"]["script_sha256"]),
                      (plan["launch"]["script"], plan["launch"]["script_sha256"]),
                      (plan["launch"]["local_script"], plan["launch"]["local_script_sha256"]),
                      (plan["acceptance"]["script"], plan["acceptance"]["script_sha256"]),
                      (plan["contrasts"]["script"], plan["contrasts"]["script_sha256"]),
                      (plan["diagnostics"]["script"], plan["diagnostics"]["script_sha256"])):
        if sha256_file(os.path.join(HERE, name)) != sha:
            raise SystemExit(f"{name} is not the registered script; nothing merged or scored")

    def run(argv, **kw):
        print("+", " ".join(argv), flush=True)
        return subprocess.run(argv, cwd=root, env={**os.environ, "OMP_NUM_THREADS": "1",
                                                   "PYTHONDONTWRITEBYTECODE": "1"}, **kw)

    if not os.path.isdir(main_dir):
        if plan.get("local_rehearsal"):
            raise SystemExit(f"{main_dir} does not exist: play the rehearsal first "
                             "(play_local_from_plan.py)")
        merge = [py, os.path.join(root, "tools", "droplet_tournament.py"), "merge", "--out", main_dir]
        for shard in sorted(plan["shards"]):
            merge += ["--shard", os.path.join(out_root, shard_dirs.get(shard, shard), "main")]
        run(merge, check=True)
    r = run([py, os.path.join(HERE, plan["acceptance"]["script"]), plan_path, main_dir,
             "--expect-sha256", args.expect_sha256], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    tokens = ["GATE-ACCEPTED", "MASKS-ACCEPTED", "SEARCH-ACCEPTED", "SIDECARS-ACCEPTED"]
    if r.returncode != 0 or any(token not in r.stdout for token in tokens):
        raise SystemExit("NOT ACCEPTED; nothing scored")
    for name in ("PLAN.json", "PLAN.json.sha256", "SCRIPTS.sha256"):
        with open(os.path.join(HERE, name), "rb") as src, open(os.path.join(main_dir, name), "wb") as dst:
            dst.write(src.read())
    r = run([py, "-m", "play_harness.tournament_stats", "--run-dir", main_dir,
             "--json", os.path.join(main_dir, "report.json")], capture_output=True, text=True, check=True)
    with open(os.path.join(main_dir, "report.txt"), "w") as f:
        f.write(r.stdout)
    label_set = None
    for s in plan["contrasts"]["sets"]:
        run_dir = s["run_dir"].replace("<run_dir>", main_dir)
        if run_dir == main_dir:
            raise SystemExit(f"contrast set {s['name']}: every set has its own sub-directory")
        os.makedirs(run_dir, exist_ok=True)
        link = os.path.join(run_dir, "games.jsonl")
        if not os.path.exists(link):
            os.link(os.path.join(main_dir, "games.jsonl"), link)
        elif not os.path.samefile(link, os.path.join(main_dir, "games.jsonl")):
            raise SystemExit(f"contrast set {s['name']}: {link} exists and is not this run's "
                             "record file; nothing more scored")
        run([py, os.path.join(HERE, plan["contrasts"]["script"]), run_dir, s["arm"], s["control"],
             *s["opponents"]], check=True)
        if s.get("label"):
            if label_set is not None:
                raise SystemExit("the plan has two label sets")
            label_set = (s, run_dir)
    if label_set is None:
        raise SystemExit("the plan has no label set")
    s, run_dir = label_set
    contrasts, shown = [], []
    for opp in s["opponents"]:
        try:
            with open(os.path.join(run_dir, f"{opp}_contrast.json")) as f:
                c = json.load(f)
            row = (c["decisive_elo_diff"], *c["decisive_elo_diff_ci95"])
        except (OSError, KeyError, TypeError, ValueError):
            row = (None, None, None)
        contrasts.append(row)
        shown.append({"opponent": opp, "decisive_elo_diff": row[0], "ci95": [row[1], row[2]]})
    label = reading(contrasts, plan["reading"])
    control = s["control"]
    arms = [x["arm"] for x in plan["contrasts"]["sets"]]
    same = identical_games(os.path.join(main_dir, "games.jsonl"), arms, control, s["opponents"])
    with open(os.path.join(main_dir, "reading.json"), "w") as f:
        json.dump({"registered_arm": s["arm"], "control": control, "contrasts": shown,
                   "rule": plan["reading"], "reading": label,
                   "games_with_the_controls_trail": same,
                   "note": "the label is the registered arm's; the other arms' contrasts are a "
                           "descriptive dose-response and carry none"}, f, indent=1)
    r = run([py, os.path.join(HERE, plan["diagnostics"]["script"]), plan_path, main_dir],
            capture_output=True, text=True, check=True)
    with open(os.path.join(main_dir, "diagnostics.txt"), "w") as f:
        f.write(r.stdout)
    for name, v in same.items():
        print(f"{name}: {v['same_trail_as_control']} of {v['seed_legs']} seed-legs have the "
              "control's action trail")
    print(f"READING ({s['arm']} minus {control}; first match of Unread, Negative, Positive, Flat, "
          f"Inconclusive): {label}", flush=True)
    print("SCORED", flush=True)


if __name__ == "__main__":
    main()
