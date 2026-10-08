#!/usr/bin/env python3
"""Merge, accept and score the search-distillation gate from PLAN.json. Nothing is scored unless acceptance passes.

  python score_from_plan.py --expect-sha256 <sha256 of PLAN.json>

Order:
  1. refuse unless PLAN.json hashes to the committed value and the scripts
     beside it hash to the values the plan records;
  2. refuse unless the harness worktree is clean at the plan's commit. This
     comes before anything of the harness is imported or run: the merge, the
     acceptance tools, the statistics and the contrasts all run its code, so a
     file changed after play would change the reading;
  3. refuse unless every shard's manifest file exists (the run is complete);
     then check EVERY shard's own manifest (for a local rehearsal, the run's):
     it has an entry for every registered checkpoint player and no other, each
     entry has the registered blob hash, and its producer and compatibility
     blocks are the registered sidecar's. The merge keeps
     only the first shard's entry for a checkpoint and compares the others by
     blob hash, so this has to be done shard by shard, before the merge;
  4. merge the shards (skipped when the run directory exists already, which is
     the merge-free path of a local rehearsal);
  5. run accept_from_plan.py (the stock acceptance tool, the mask checks, the
     search acceptance tool and the sidecar check);
  6. only on GATE-ACCEPTED, MASKS-ACCEPTED, SEARCH-ACCEPTED and
     SIDECARS-ACCEPTED write the tournament report, the paired contrast sets,
     the reading and the diagnostics the plan names.
Steps 1 and 2, and a shard manifest that does not exist yet, are refusals,
not readings: they are about this machine's scripts and worktree or about a
run that is not complete, nothing of the run has been read when they fail, no
reading is written, and the scorer is run again once the scripts and the
worktree are the registered ones and every shard is in. If a manifest that
exists is wrong (step 3), or step 4 or 5 fails, the run's own records were
rejected: reading.json is written with the reading Unread and the
reason (in the run directory when it exists, else beside this script) and the
exit code is not zero.

The reading is applied here, by the plan's rule, to the registered arm's two
contrasts and to nothing else: Unread, Negative, Positive, Flat, Inconclusive,
first match in that order. A contrast file that is missing, or whose point or
interval is not two finite ends, gives Unread. The other arms' contrasts are
printed as a descriptive dose-response and carry no label. --shard-dir
SHARD=NAME reads a shard from another directory under the output root (a
relaunched shard); the default is the shard's own name.
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


def git(root, *args):
    return subprocess.run(["git", "-C", root, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def worktree_problem(root, commit):
    """Why the harness worktree may not be used for scoring, or None: it must be
    a git worktree whose HEAD is the plan's commit, with nothing modified,
    staged or untracked."""
    try:
        head = git(root, "rev-parse", "HEAD")
        dirty = git(root, "status", "--porcelain")
    except (subprocess.CalledProcessError, OSError) as exc:
        return f"{root} is not a readable git worktree ({exc})"
    if head != commit:
        return f"{root} is at {head}, the plan's harness commit is {commit}"
    if dirty:
        return f"{root} is not clean: {dirty.splitlines()[0]}"
    return None


def registered_sidecars(plan):
    """{checkpoint name: sidecar object} from the local files, each held to the
    plan's sidecar hash first. Raises SystemExit when one is not the registered file."""
    out = {}
    for name, path in plan["checkpoint_paths"].items():
        sidecar = path + ".lineage.json"
        if not os.path.isfile(sidecar) or sha256_file(sidecar) != plan["sidecars_sha256"][name]:
            raise SystemExit(f"{sidecar} is not the registered sidecar of {name}")
        with open(sidecar) as f:
            out[name] = json.load(f)
    return out


def manifest_problems(manifest_path, plan, sidecars, where):
    """One run's manifest (a shard's, before the merge) against the plan: it has
    an entry for every registered checkpoint player and for no other, each
    entry has the registered blob hash, and its producer and compatibility
    blocks are the registered sidecar's."""
    try:
        with open(manifest_path) as f:
            manifest = json.load(f)
    except (OSError, ValueError) as exc:
        return [f"{where}: no readable manifest ({exc})"]
    problems = []
    entries = manifest.get("checkpoints") or {}
    if not entries:
        problems.append(f"{where}: the manifest lists no checkpoint")
    # Every shard plays every pair, so every registered checkpoint player must
    # be in every manifest: an entry that is absent here would be supplied by
    # another shard in the merge and never checked for this one.
    absent = sorted(player for player, spec in plan["players"].items()
                    if "checkpoint" in spec and player not in entries)
    if absent:
        problems.append(f"{where}: the manifest has no checkpoint entry for {absent}")
    for player, got in entries.items():
        spec = plan["players"].get(player)
        if not spec or "checkpoint" not in spec:
            problems.append(f"{where}: {player} is not a registered checkpoint player")
            continue
        name = spec["checkpoint"]
        side = sidecars[name]
        if (got or {}).get("sha256") != plan["checkpoints_sha256"][name]:
            problems.append(f"{where}: {player} played a blob that is not the registered {name}")
        if (got or {}).get("producer") != side.get("producer") or \
                (got or {}).get("compatibility") != side.get("compatibility"):
            problems.append(f"{where}: {player}'s producer or compatibility block is not the "
                            f"registered sidecar's ({name})")
    return problems


def write_unread(main_dir, here, plan, reason):
    """Leave reading.json = Unread with the reason: in the run directory when it
    exists, else beside this script. Returns the message to exit with."""
    where = main_dir if os.path.isdir(main_dir) else here
    with open(os.path.join(where, "reading.json"), "w") as f:
        json.dump({"reading": "Unread", "reason": reason, "rule": plan.get("reading"),
                   "note": "nothing was scored"}, f, indent=1)
    return (f"READING: Unread ({reason}); nothing scored; "
            f"{os.path.join(where, 'reading.json')} says so")


def interval_row(path):
    """(point, lo, hi) from a contrast file, or (None, None, None) when the file
    is missing or its point or interval is not what the reading needs."""
    try:
        with open(path) as f:
            c = json.load(f)
        point, interval = c["decisive_elo_diff"], c["decisive_elo_diff_ci95"]
        if not isinstance(interval, (list, tuple)) or len(interval) != 2:
            raise ValueError("the interval is not two ends")
        row = (point, interval[0], interval[1])
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in row):
            raise ValueError("a value is not a number")
        return row
    except (OSError, KeyError, TypeError, ValueError):
        return (None, None, None)


def reading(contrasts, rule):
    """The gate's label from the registered arm's contrasts: a list of
    (point, lo, hi) per opponent. First match in the plan's order."""
    values = [v for c in contrasts for v in c]
    if len(contrasts) != 2 or any(v is None or isinstance(v, bool)
                                  or not isinstance(v, (int, float))
                                  or not math.isfinite(v) for v in values):
        return "Unread"
    if any(lo > hi for _p, lo, hi in contrasts):
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

    def unread(reason):
        raise SystemExit(write_unread(main_dir, HERE, plan, reason))

    # Before anything of the harness is imported or run.
    problem = worktree_problem(root, plan["harness_commit"])
    if problem:
        raise SystemExit(f"REFUSED, no reading: the harness worktree is not the registered one: "
                         f"{problem}. Nothing was imported, merged, read or scored. Restore the "
                         "worktree to the plan's commit, clean, and run this again.")
    # Every shard's own manifest, before the merge drops all but the first.
    sidecars = registered_sidecars(plan)
    if plan.get("local_rehearsal"):
        if not os.path.isdir(main_dir):
            raise SystemExit(f"{main_dir} does not exist: play the rehearsal first "
                             "(play_local_from_plan.py)")
        manifests = {"the run": os.path.join(main_dir, "manifest.json")}
    else:
        manifests = {shard: os.path.join(out_root, shard_dirs.get(shard, shard), "main",
                                         "manifest.json") for shard in sorted(plan["shards"])}
    # A manifest file that does not exist is a shard that has not been played
    # or fetched (or a relaunched shard's directory that was not named with
    # --shard-dir): the run is not complete, nothing of it has been read, and
    # that is a refusal. A manifest that exists and is wrong is the run's own
    # record, and gives Unread below.
    absent = [f"{where} ({path})" for where, path in manifests.items() if not os.path.isfile(path)]
    if absent:
        raise SystemExit("REFUSED, no reading: the run is not complete, there is no manifest "
                         f"for {'; '.join(absent)}. Nothing was merged, read or scored. Run "
                         "this again when every shard is in (a relaunched shard's directory is "
                         "named with --shard-dir).")
    found = [p for where, path in manifests.items()
             for p in manifest_problems(path, plan, sidecars, where)]
    if found:
        unread("a shard's manifest does not hold the registered checkpoints: "
               + "; ".join(found[:6]))
    print(f"MANIFESTS-CHECKED {len(manifests)} manifest(s): every player's blob hash, producer "
          "and compatibility blocks are the registered ones", flush=True)
    if not os.path.isdir(main_dir):
        merge = [py, os.path.join(root, "tools", "droplet_tournament.py"), "merge", "--out", main_dir]
        for shard in sorted(plan["shards"]):
            merge += ["--shard", os.path.join(out_root, shard_dirs.get(shard, shard), "main")]
        if run(merge).returncode != 0:
            unread("the merge of the shards failed")
    r = run([py, os.path.join(HERE, plan["acceptance"]["script"]), plan_path, main_dir,
             "--expect-sha256", args.expect_sha256], capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    tokens = ["GATE-ACCEPTED", "MASKS-ACCEPTED", "SEARCH-ACCEPTED", "SIDECARS-ACCEPTED"]
    if r.returncode != 0 or any(token not in r.stdout for token in tokens):
        unread("the merged run is not accepted")
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
        row = interval_row(os.path.join(run_dir, f"{opp}_contrast.json"))
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
