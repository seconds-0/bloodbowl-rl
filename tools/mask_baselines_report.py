#!/usr/bin/env python3
"""Read the m1 baseline runs for the training rung against their registered design.

  .venv/bin/python tools/mask_baselines_report.py --json out.json

The design, statistic and thresholds are in
docs/play-harness/masked-copy-baselines-2026-10-05.md, section 0; run names
and contents come from tools/mask_baselines_launch.py. This script applies
them and chooses nothing. Strength rows are tournament_stats' own; paired
contrasts are mask_followup_report.paired_contrast (engine seeds resampled as
clusters, a drawn seed bringing every pair and both legs that played it).
"""
import argparse
import hashlib
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import mask_arms_report as R  # noqa: E402
import mask_baselines_launch as L  # noqa: E402
import mask_followup_report as F  # noqa: E402

REPS = 2000
# name -> (masked or "under the rule" pair, plain pair, the runs that hold them)
CONTRASTS = {
    "42 v 41: both under m1 minus both plain":
        (("chain42m1", "chain41m1"), ("chain42", "chain41"), ("c42-c41",)),
    "chain 42 v chain 37: m1 minus plain":
        (("chain42m1", "chain37"), ("chain42", "chain37"), ("c37-42",)),
    "chain 41 v chain 37: m1 minus plain":
        (("chain41m1", "chain37"), ("chain41", "chain37"), ("c37-41",)),
    "v chain 37: chain 42 minus chain 41, both under m1":
        (("chain42m1", "chain37"), ("chain41m1", "chain37"), ("c37-42", "c37-41")),
    "v chain 37: chain 42 minus chain 41, both plain":
        (("chain42", "chain37"), ("chain41", "chain37"), ("c37-42", "c37-41")),
}
SELF = {"c42-self": "chain 42", "c47-self": "chain 47", "c48-self": "chain 48"}


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_run(run, games, manifest, run_dir=None, chain_sha=None):
    """Refuse a run that is not the registered one, played to the end.

    chain_sha maps a chain name to the sha256 its blob must have; without it
    the check is that players of one chain share a blob and chains differ."""
    seed0, pairs = L.RUNS[run]
    want_pairs = sorted([a, b, L.GAMES] for a, b in pairs)
    if sorted(manifest["pairs"]) != want_pairs:
        raise SystemExit(f"run {run}: pairs {manifest['pairs']} != {want_pairs}")
    problems = []
    if manifest.get("seed0") != seed0:
        problems.append(f"seed0 {manifest.get('seed0')} != {seed0}")
    if manifest.get("kernel") != "native" or manifest.get("games_per_worker") != 32:
        problems.append("not the native kernel at 32 games per worker")
    by_chain = {}
    for name in sorted({n for pair in pairs for n in pair}):
        chain, masks, offset = L.PLAYERS[name]
        spec = manifest["players"].get(name) or {}
        want_masks = sorted(masks.split(",")) if masks else None
        if (spec.get("masks") or None) != want_masks:
            problems.append(f"{name} masks {spec.get('masks')} != {want_masks}")
        if int(spec.get("seed_offset") or 0) != offset:
            problems.append(f"{name} sampling offset {spec.get('seed_offset')} != {offset}")
        if spec.get("mode") != "sample" or spec.get("temperature") != 1.0:
            problems.append(f"{name} is not sampled at temperature 1")
        by_chain.setdefault(chain, set()).add(manifest["checkpoints"][name]["sha256"])
    for chain, shas in by_chain.items():
        if len(shas) != 1:
            problems.append(f"players of {chain} do not share one blob")
        if chain_sha and chain_sha.get(chain) not in shas:
            problems.append(f"{chain} is not the registered blob")
    if len({next(iter(s)) for s in by_chain.values()}) != len(by_chain):
        problems.append("two chains share a blob")
    for a, b in pairs:
        same = L.PLAYERS[a][0] == L.PLAYERS[b][0]
        if same and L.PLAYERS[a][2] == L.PLAYERS[b][2]:
            problems.append(f"{a} and {b} are one checkpoint on one sampling stream")
    if run_dir is not None:
        done = os.path.join(run_dir, "COMPLETE.json")
        if not os.path.exists(done) or not json.load(open(done)).get("complete"):
            problems.append("no COMPLETE.json that says complete")
    want = {(a, b, seed0 + i, leg) for a, b in pairs for i in range(L.GAMES // 2)
            for leg in ("A_home", "B_home")}
    got = [(g["pair"][0], g["pair"][1], g["engine_seed"], g["leg"]) for g in games]
    if len(got) != len(set(got)) or set(got) != want:
        problems.append(f"games are not the {len(want)} scheduled legs")
    for g in games:
        if not g.get("natural") or any(g.get("integrity", {}).get(k, 1) for k in R.HARD_COUNTERS):
            problems.append(f"game {g['pair']} {g['game_index']} {g['leg']}: unnatural ending "
                            "or a nonzero integrity counter")
            break
    if problems:
        raise SystemExit(f"run {run}: " + "; ".join(problems))


def side_rows(games):
    """The behaviour rows for A and for B in these games."""
    out = {}
    for who in ("a", "b"):
        total = dict.fromkeys(("activations", "act_empty", "block_targets", "turnovers",
                               "team_turns"), 0)
        td = 0
        for g in games:
            side = R.side_of_a(g) if who == "a" else 1 - R.side_of_a(g)
            b = g["behaviour"][side]
            for k in total:
                total[k] += b[k]
            td += g["score"][side]
        n, turns = len(games), total["team_turns"]
        out[who] = {"activations_per_turn": total["activations"] / turns,
                    "empties_per_turn": total["act_empty"] / turns,
                    "blocks_per_game": total["block_targets"] / n,
                    "turnovers_per_turn": total["turnovers"] / turns,
                    "td_per_game": td / n}
    out["decisions_per_game"] = sum(g["c_steps"] for g in games) / len(games)
    out["draw_rate"] = sum(g["result_a"] == "D" for g in games) / len(games)
    return out


def fmt(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def print_report(out):
    print("| run | A | B | W / D / L | decisive share | decisive-Elo of A [95%] | verdict |"
          "\n|---|---|---|---|---|---|---|")
    for p in out["pairs"]:
        s = p["strength"]
        print(f"| {p['run']} | {s['a']} | {s['b']} | {s['W']} / {s['D']} / {s['L']} | "
              f"{fmt(s['decisive_share'])} | {fmt(s['elo_decisive'], 1)} "
              f"[{fmt(s['elo_decisive_ci95'][0], 1)}, {fmt(s['elo_decisive_ci95'][1], 1)}] | "
              f"{', '.join(p['verdict']) if p.get('verdict') else ''} |")
    print("\n| paired contrast | decisive-Elo [95%] | reading by the thresholds | score-rate "
          "contrast [95%] |\n|---|---|---|---|")
    for name, c in out["contrasts"].items():
        print(f"| {name} | {fmt(c['elo_contrast'], 1)} [{fmt(c['ci95'][0], 1)}, "
              f"{fmt(c['ci95'][1], 1)}] | {', '.join(c['verdict'])} | "
              f"{fmt(c['score_rate_contrast'])} [{fmt(c['score_rate_ci95'][0])}, "
              f"{fmt(c['score_rate_ci95'][1])}] |")
    print("\n| A v B | activations per turn | empties per turn | blocks per game | turnovers "
          "per turn | TD for / against (A) | draw rate | decisions per game |"
          "\n|---|---|---|---|---|---|---|---|")
    for p in out["pairs"]:
        b, s = p["behaviour"], p["strength"]

        def two(key, d=2):
            return f"{fmt(b['a'][key], d)} / {fmt(b['b'][key], d)}"
        print(f"| {s['a']} v {s['b']} | {two('activations_per_turn')} | {two('empties_per_turn')} "
              f"| {two('blocks_per_game', 1)} | {two('turnovers_per_turn', 3)} | "
              f"{fmt(b['a']['td_per_game'])} / {fmt(b['b']['td_per_game'])} | "
              f"{fmt(b['draw_rate'])} | {fmt(b['decisions_per_game'], 0)} |")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs-root", default=os.path.join(ROOT, ".play-artifacts", "tournaments"))
    ap.add_argument("--checkpoint-dir", default=L.CHECKPOINTS)
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    chains = sorted({v[0] for v in L.PLAYERS.values()})
    chain_sha = {c: sha256_file(os.path.join(args.checkpoint_dir, c, L.BLOB)) for c in chains}
    if chain_sha["chain41"] != R.CHAIN41_SHA256:
        raise SystemExit("the local chain 41 blob is not chain 41")
    loaded = {}
    for run in L.RUNS:
        run_dir = os.path.join(args.runs_root, L.run_name(run), "main")
        games, manifest = R.load(run_dir)
        check_run(run, games, manifest, run_dir=run_dir, chain_sha=chain_sha)
        loaded[run] = (games, manifest)
    out = {"schema": "mask-baselines-report-v1", "noninferior_elo": F.NONINFERIOR_ELO,
           "reps": args.reps, "checkpoint_sha256": chain_sha,
           "harness_git_head": sorted({m["harness_git_head"] for _g, m in loaded.values()}),
           "pairs": [], "contrasts": {}}
    for run, (games, _m) in loaded.items():
        rows = F.pair_rows(games, args.reps)
        for pair in L.RUNS[run][1]:
            pg = F.of_pair(games, *pair)
            entry = {"run": run, "seed0": L.RUNS[run][0], "strength": rows[tuple(pair)],
                     "behaviour": side_rows(pg)}
            if run in SELF:
                entry["verdict"] = F.verdict(*rows[tuple(pair)]["elo_decisive_ci95"])
                entry["mask_stats"] = R.mask_table(pg)
            out["pairs"].append(entry)
    for name, (first, second, runs) in CONTRASTS.items():
        games = [g for run in runs for g in loaded[run][0]]
        out["contrasts"][name] = F.paired_contrast(games, first, second, args.reps)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
    print_report(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
