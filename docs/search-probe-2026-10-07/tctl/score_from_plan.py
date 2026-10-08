#!/usr/bin/env python3
"""Merge, accept and score a registered gate from PLAN.json. Nothing is scored unless acceptance passes.

  python score_from_plan.py --expect-sha256 <sha256 of PLAN.json>

Order: refuse unless PLAN.json hashes to the committed value and the scripts
beside it hash to the values the plan records; merge the shards; run
accept_from_plan.py (the stock acceptance tool, the mask checks and the search
acceptance tool, and the replay check when the plan has a reference run); only
on GATE-ACCEPTED, MASKS-ACCEPTED, SEARCH-ACCEPTED and, with a reference run,
REPLAY-ACCEPTED write the tournament report, the paired contrast sets and the
diagnostics the plan names. A contrast set with "reference_pairs" is computed
on this run's records plus the reference run's records of those pairs (the
reference file is hash-checked again when it is read). --shard-dir SHARD=NAME reads a shard from another directory under
the output root (a relaunched shard); the default is the shard's own name.
"""
import argparse
import hashlib
import json
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
                      (plan["acceptance"]["script"], plan["acceptance"]["script_sha256"]),
                      (plan["contrasts"]["script"], plan["contrasts"]["script_sha256"]),
                      (plan["diagnostics"]["script"], plan["diagnostics"]["script_sha256"])):
        if sha256_file(os.path.join(HERE, name)) != sha:
            raise SystemExit(f"{name} is not the registered script; nothing merged or scored")

    def run(argv, **kw):
        print("+", " ".join(argv), flush=True)
        return subprocess.run(argv, cwd=root, env={**os.environ, "OMP_NUM_THREADS": "1"}, **kw)

    if not os.path.isdir(main_dir):
        merge = [py, os.path.join(root, "tools", "droplet_tournament.py"), "merge", "--out", main_dir]
        for shard in sorted(plan["shards"]):
            merge += ["--shard", os.path.join(out_root, shard_dirs.get(shard, shard), "main")]
        run(merge, check=True)
    r = run([py, os.path.join(HERE, plan["acceptance"]["script"]), plan_path, main_dir,
             "--expect-sha256", args.expect_sha256], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    tokens = ["GATE-ACCEPTED", "MASKS-ACCEPTED", "SEARCH-ACCEPTED"]
    if plan.get("reference"):
        tokens.append("REPLAY-ACCEPTED")
    if r.returncode != 0 or any(token not in r.stdout for token in tokens):
        raise SystemExit("NOT ACCEPTED; nothing scored")
    for name in ("PLAN.json", "PLAN.json.sha256", "SCRIPTS.sha256"):
        with open(os.path.join(HERE, name), "rb") as src, open(os.path.join(main_dir, name), "wb") as dst:
            dst.write(src.read())
    r = run([py, "-m", "play_harness.tournament_stats", "--run-dir", main_dir,
             "--json", os.path.join(main_dir, "report.json")], capture_output=True, text=True, check=True)
    with open(os.path.join(main_dir, "report.txt"), "w") as f:
        f.write(r.stdout)
    for s in plan["contrasts"]["sets"]:
        run_dir = s["run_dir"].replace("<run_dir>", main_dir)
        if run_dir == main_dir and s.get("reference_pairs"):
            raise SystemExit(f"contrast set {s['name']}: reference records never go into the run directory")
        if run_dir != main_dir:
            os.makedirs(run_dir, exist_ok=True)
            link = os.path.join(run_dir, "games.jsonl")
            if s.get("reference_pairs"):
                ref = plan["reference"]
                ref_games = os.path.join(os.path.expanduser(ref["run_dir"]), "games.jsonl")
                if sha256_file(ref_games) != ref["games_sha256"]:
                    raise SystemExit(f"{ref_games} is not the registered reference record file")
                keep = {tuple(p) for p in s["reference_pairs"]}
                seeds = range(plan["seed0"], plan["seed0"] + int(plan["games_per_pair"]) // 2)
                added = 0
                with open(link + ".tmp", "w") as dst:
                    with open(os.path.join(main_dir, "games.jsonl")) as src:
                        for line in src:
                            if line.strip():
                                dst.write(line if line.endswith("\n") else line + "\n")
                    with open(ref_games) as src:
                        for line in src:
                            if not line.strip():
                                continue
                            g = json.loads(line)
                            if tuple(g["pair"]) in keep and g["engine_seed"] in seeds:
                                dst.write(line if line.endswith("\n") else line + "\n")
                                added += 1
                want_added = int(s["reference_games"])
                if added != want_added:
                    raise SystemExit(f"contrast set {s['name']}: {added} reference records, "
                                     f"{want_added} registered")
                os.replace(link + ".tmp", link)
            elif not os.path.exists(link):
                os.link(os.path.join(main_dir, "games.jsonl"), link)
            elif not os.path.samefile(link, os.path.join(main_dir, "games.jsonl")):
                raise SystemExit(f"contrast set {s['name']}: {link} exists and is not this run's "
                                 "record file; nothing more scored")
        run([py, os.path.join(HERE, plan["contrasts"]["script"]), run_dir, s["arm"], s["control"],
             *s["opponents"]], check=True)
    r = run([py, os.path.join(HERE, plan["diagnostics"]["script"]), plan_path, main_dir],
            capture_output=True, text=True, check=True)
    with open(os.path.join(main_dir, "diagnostics.txt"), "w") as f:
        f.write(r.stdout)
    print("SCORED", flush=True)


if __name__ == "__main__":
    main()
