#!/usr/bin/env python3
"""Read the masked-copy arms: strength against the registered thresholds, and
what each side did in the same games.

  .venv/bin/python tools/mask_arms_report.py --arm m1=RUN_DIR --arm m2=RUN_DIR ... \\
      [--control RUN_DIR] [--reference-slice MODIFIED_DIR UNMODIFIED_DIR] --json out.json

Each arm is one tournament run directory (games.jsonl, manifest.json) with one
pair: the masked copy as A, plain chain 41 as B. The design and the thresholds
are in docs/play-harness/masked-copy-2026-10-05.md, section 0. This script
applies them; it chooses nothing.

Intervals are seed-cluster percentile intervals (engine seeds resampled; a
seed brings both of its legs), the gates' own unit of dependence.
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from play_harness import tournament_stats as S  # noqa: E402

REPS = 2000
NONINFERIOR_ELO = -20.0

# name -> (numerator key or callable, denominator key or None for "per game")
METRICS = (
    ("activations per team turn", "activations", "team_turns"),
    ("turns ended by choice with a player left, per team turn",
     "end_turn_with_player_left", "team_turns"),
    ("block targets chosen per game", "block_targets", None),
    ("block targets inside a Blitz per game", "block_targets_blitz", None),
    ("block targets inside a Block per game", "block_targets_block", None),
    ("turnovers per team turn", "turnovers", "team_turns"),
    ("touchdowns per game", "td", None),
    ("possession (turns ended holding the ball)", "team_turns_holding_ball", "team_turns"),
    ("activations ended at once, per activation", "ended_at_once", "activations"),
    ("activations ended with a block target on offer (Block or Blitz), per game",
     "ended_with_block_target_on_offer", None),
    ("Block declared per team turn", "declared_block", "team_turns"),
    ("Blitz declared per team turn", "declared_blitz", "team_turns"),
    ("Pass declared per team turn", "declared_pass", "team_turns"),
    ("pass targets chosen per game", "pass_targets", None),
    ("foul targets chosen per game", "foul_targets", None),
    ("team turns per game", "team_turns", None),
    ("engine steps per game (both sides)", "c_steps", None),
)


def side_of_a(g):
    return 0 if g["leg"] == "A_home" else 1


def side_values(g, side):
    """One side's counts in one game, with the score and the game length added."""
    row = dict(g["behaviour"][side])
    row["td"] = g["score"][side]
    row["c_steps"] = g["c_steps"]
    row["games"] = 1
    return row


def behaviour_table(games, reps=REPS, seed=0):
    """Per metric: A's rate, B's rate and A minus B with a seed-cluster interval."""
    seeds = sorted({g["engine_seed"] for g in games})
    index = {s: i for i, s in enumerate(seeds)}
    keys = sorted({k for _n, num, den in METRICS for k in (num, den) if k} | {"games"})
    col = {k: i for i, k in enumerate(keys)}
    sums = np.zeros((2, len(seeds), len(keys)))            # [A or B, seed, key]
    for g in games:
        a = side_of_a(g)
        for who, side in ((0, a), (1, 1 - a)):
            values = side_values(g, side)
            for k in keys:
                sums[who, index[g["engine_seed"]], col[k]] += values[k]
    rng = np.random.default_rng(seed)
    n = len(seeds)
    boots = np.empty((reps, 2, len(keys)))
    for r in range(reps):
        mult = np.bincount(rng.integers(0, n, n), minlength=n).astype(float)
        boots[r] = np.tensordot(sums, mult, axes=([1], [0]))
    point = sums.sum(axis=1)

    def rate(total, num, den):
        d = total[..., col[den or "games"]]
        with np.errstate(invalid="ignore", divide="ignore"):
            return total[..., col[num]] / d

    rows = []
    for name, num, den in METRICS:
        a_rate, b_rate = (float(rate(point[w], num, den)) for w in (0, 1))
        diff = rate(boots[:, 0], num, den) - rate(boots[:, 1], num, den)
        diff = diff[np.isfinite(diff)]
        lo, hi = (np.percentile(diff, [2.5, 97.5]) if diff.size else (float("nan"),) * 2)
        rows.append({"metric": name, "a": a_rate, "b": b_rate, "a_minus_b": a_rate - b_rate,
                     "ci95": [float(lo), float(hi)]})
    return rows


def mask_table(games):
    """Per mask on A, per game: decisions where its condition held, where it
    removed a type, where it gave way, and the summed probability the unmasked
    policy gave the removed type at those decisions (on the masked copy's own
    trajectory; not a count of differences from a plain rollout). With several
    masks, a removal both m2 and m3 ask for is credited to m2 only."""
    out = {}
    for g in games:
        stats = g["mask_stats"][side_of_a(g)] or {}
        for mask, v in stats.items():
            row = out.setdefault(mask, {"held": 0, "applied": 0, "fallback": 0, "mass": 0.0})
            for k in row:
                row[k] += v[k]
    n = len(games)
    return {m: {k: v / n for k, v in row.items()} for m, row in sorted(out.items())}


def strength(games, reps=REPS):
    boot = S.seed_cluster_bootstrap(games, reps=reps)
    (row,) = boot["pairs"]
    lo, hi = row["elo_decisive_ci95"]
    verdicts = []
    if lo > 0:
        verdicts.append("better")
    if hi < 0:
        verdicts.append("worse")
    if lo > NONINFERIOR_ELO:
        verdicts.append("non-inferior")
    return {**row, "verdict": verdicts or ["inconclusive"]}


def roster_split(games, reps=REPS):
    table = S.roster_class_table(games, reps=reps, by="a")
    return [{k: r[k] for k in ("class", "games", "W", "D", "L", "decisive_share",
                               "cluster_ci95")} for r in table["rows"]]


def load(run_dir):
    games = S.load_games(run_dir)
    with open(os.path.join(run_dir, "manifest.json")) as f:
        manifest = json.load(f)
    return games, manifest


CHAIN41_SHA256 = "b1830e2312a6252006de71f2835f3459f0a13f664d83ae3128182c48cb0b303b"
REGISTERED = {  # arm -> (masks on A, seed block); section 0 of the design doc
    "m1": (["m1"], 23000000), "m2": (["m2"], 23100000), "m3": (["m3"], 23200000),
    "m1,m2,m3": (["m1", "m2", "m3"], 23300000), "control": ([], 23400000)}
GAMES_PER_ARM = 3200
HARD_COUNTERS = ("illegal", "projection_collision", "error_episodes",
                 "rejected_submissions", "precheck_collisions")


def check_arm(name, games, manifest, masks, registered=True, run_dir=None):
    """Refuse to read a run that is not the registered arm, played to the end.

    registered=False (tests, pilots) skips the checks tied to the registered
    design: chain 41's hash, the seed block and the game count."""
    problems = []
    pairs = manifest["pairs"]
    if len(pairs) != 1:
        raise SystemExit(f"arm {name}: {len(pairs)} pairs, expected one")
    a, b, n_games = pairs[0][0], pairs[0][1], pairs[0][2]
    players, checkpoints = manifest["players"], manifest["checkpoints"]
    got_a = players[a].get("masks")
    if (got_a or None) != (sorted(masks) or None):
        problems.append(f"A's masks {got_a} != {sorted(masks)}")
    if players[b].get("masks"):
        problems.append("B is masked")
    if checkpoints[a]["sha256"] != checkpoints[b]["sha256"]:
        problems.append("A and B are not the same checkpoint")
    for who in (a, b):
        if players[who].get("mode") != "sample" or players[who].get("temperature") != 1.0:
            problems.append(f"{who} is not sampled at temperature 1: {players[who]}")
    if manifest.get("kernel") != "native":
        problems.append(f"kernel {manifest.get('kernel')}")
    if registered:
        want_masks, want_seed = REGISTERED.get(name, (None, None))
        if want_masks is None or sorted(masks) != want_masks:
            problems.append(f"{name} is not a registered arm")
        if manifest.get("seed0") != want_seed:
            problems.append(f"seed0 {manifest.get('seed0')} != registered {want_seed}")
        if checkpoints[a]["sha256"] != CHAIN41_SHA256:
            problems.append("the checkpoint is not chain 41")
        if n_games != GAMES_PER_ARM or manifest.get("games_per_worker") != 32:
            problems.append(f"{n_games} games at {manifest.get('games_per_worker')} per worker")
        if run_dir is not None:
            done = os.path.join(run_dir, "COMPLETE.json")
            if not os.path.exists(done) or not json.load(open(done)).get("complete"):
                problems.append("no COMPLETE.json that says complete")
    # Every seed of the block exactly once in each leg, nothing else.
    seed0 = manifest["seed0"]
    want = {(seed0 + i, leg) for i in range(n_games // 2) for leg in ("A_home", "B_home")}
    got = [(g["engine_seed"], g["leg"]) for g in games]
    if len(got) != len(set(got)) or set(got) != want:
        problems.append(f"games are not the {len(want)} scheduled legs "
                        f"({len(got)} records, {len(set(got))} distinct)")
    for g in games:
        side = side_of_a(g)
        if (g["masks"][side] or None) != (sorted(masks) or None) or g["masks"][1 - side]:
            problems.append(f"game {g['game_index']} {g['leg']}: masks {g['masks']}")
            break
        if tuple(g["pair"]) != (a, b) or not g.get("natural") or any(
                g.get("integrity", {}).get(k, 1) for k in HARD_COUNTERS):
            problems.append(f"game {g['game_index']} {g['leg']}: wrong pair, unnatural "
                            "ending or a nonzero integrity counter")
            break
    if problems:
        raise SystemExit(f"arm {name}: " + "; ".join(problems))


def control_checks(games):
    """The control's two legs of a seed are one game with the names swapped."""
    by_seed = {}
    for g in games:
        by_seed.setdefault(g["engine_seed"], {})[g["leg"]] = g
    same = sum(1 for legs in by_seed.values()
               if len(legs) == 2 and legs["A_home"]["action_trail_sha256"]
               == legs["B_home"]["action_trail_sha256"])
    return {"seeds": len(by_seed), "seeds_with_identical_legs": same,
            "records_with_a_mask": sum(1 for g in games if any(g["masks"]))}


def slice_check(modified_dir, unmodified_dir):
    """Game by game: the modified harness against the unmodified checkout."""
    key = lambda g: (tuple(g["pair"]), g["game_index"], g["leg"])  # noqa: E731
    new = {key(g): g for g in S.load_games(modified_dir)}
    old = {key(g): g for g in S.load_games(unmodified_dir)}
    shared = sorted(set(new) & set(old))
    fields = ("action_trail_sha256", "final_digest", "score", "c_steps", "logprob_sum")
    return {"games_modified": len(new), "games_unmodified": len(old), "compared": len(shared),
            **{f"same_{f}": sum(new[k][f] == old[k][f] for k in shared) for f in fields},
            "new_record_keys": sorted(set(next(iter(new.values()))) - set(next(iter(old.values()))))}


def fmt(x, digits=3):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{digits}f}"


def print_report(out):
    for name, arm in out["arms"].items():
        s = arm["strength"]
        print(f"## {name}: masks {arm['masks'] or 'none'}, {s['games']} games, "
              f"{s['seeds']} seeds\n")
        print(f"W/D/L {s['W']}/{s['D']}/{s['L']}; decisive share {fmt(s['decisive_share'])} "
              f"[{fmt(s['decisive_share_ci95'][0])}, {fmt(s['decisive_share_ci95'][1])}]; "
              f"decisive-Elo {fmt(s['elo_decisive'], 1)} "
              f"[{fmt(s['elo_decisive_ci95'][0], 1)}, {fmt(s['elo_decisive_ci95'][1], 1)}]; "
              f"verdict: {', '.join(s['verdict'])}\n")
        print("| metric | masked (A) | plain (B) | A - B [95%] |\n|---|---|---|---|")
        for r in arm["behaviour"]:
            print(f"| {r['metric']} | {fmt(r['a'])} | {fmt(r['b'])} | {fmt(r['a_minus_b'])} "
                  f"[{fmt(r['ci95'][0])}, {fmt(r['ci95'][1])}] |")
        print()
        if arm["mask_stats"]:
            print("| mask | held per game | applied | gave way (fallback) | summed "
                  "removed-type probability |\n|---|---|---|---|---|")
            for m, v in arm["mask_stats"].items():
                print(f"| {m} | {fmt(v['held'], 2)} | {fmt(v['applied'], 2)} | "
                      f"{fmt(v['fallback'], 2)} | {fmt(v['mass'], 2)} |")
            print()
        print("| roster class A coached | games | W/D/L | decisive share [95%] |\n|---|---|---|---|")
        for r in arm["roster"]:
            print(f"| {r['class']} | {r['games']} | {r['W']}/{r['D']}/{r['L']} | "
                  f"{fmt(r['decisive_share'])} [{fmt(r['cluster_ci95'][0])}, "
                  f"{fmt(r['cluster_ci95'][1])}] |")
        print()
    for key in ("control", "reference_slice"):
        if out.get(key):
            print(f"## {key}\n\n```json\n{json.dumps(out[key], indent=1)}\n```\n")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--arm", action="append", default=[], metavar="MASKS=RUN_DIR",
                    help="e.g. m1=DIR or m1,m2,m3=DIR")
    ap.add_argument("--control", default=None, metavar="RUN_DIR")
    ap.add_argument("--reference-slice", nargs=2, default=None,
                    metavar=("MODIFIED_DIR", "UNMODIFIED_DIR"))
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    out = {"schema": "mask-arms-report-v1", "noninferior_elo": NONINFERIOR_ELO,
           "reps": args.reps, "arms": {}}
    runs = [(item.split("=", 1)[0], item.split("=", 1)[1]) for item in args.arm]
    if args.control:
        runs.append(("control", args.control))
    for name, run_dir in runs:
        masks = [] if name == "control" else name.split(",")
        games, manifest = load(run_dir)
        check_arm(name, games, manifest, masks, run_dir=run_dir)
        out["arms"][name] = {
            "masks": masks, "run_dir": os.path.relpath(run_dir, ROOT),
            "seed0": manifest["seed0"], "harness_git_head": manifest["harness_git_head"],
            "strength": strength(games, args.reps),
            "behaviour": behaviour_table(games, args.reps),
            "mask_stats": mask_table(games),
            "roster": roster_split(games, args.reps),
        }
        if name == "control":
            out["control"] = control_checks(games)
    if args.reference_slice:
        out["reference_slice"] = slice_check(*args.reference_slice)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
    print_report(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
