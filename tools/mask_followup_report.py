#!/usr/bin/env python3
"""Read the masked-copy follow-up runs against their registered design.

  .venv/bin/python tools/mask_followup_report.py --runs-root .play-artifacts/tournaments \\
      --json out.json

The design, statistic and thresholds are in
docs/play-harness/masked-copy-followup-2026-10-05.md, section 0. This script
applies them; it chooses nothing. Run names and contents come from
tools/mask_followup_launch.py.

The transfer statistic is a paired contrast: decisive-Elo of (chain 41 + m1 v
X) minus decisive-Elo of (plain chain 41 v X), the two pairs played on the
same engine seeds, with engine seeds resampled as clusters (a drawn seed
brings both pairs and both legs). It uses tournament_stats' own cluster_counts
and bootstrap_cluster_counts, the functions behind every gate interval.
"""
import argparse
import json
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import mask_arms_report as R  # noqa: E402
import mask_followup_launch as L  # noqa: E402
from play_harness import activations as AC  # noqa: E402
from play_harness import tournament_stats as S  # noqa: E402

REPS = 2000
NONINFERIOR_ELO = -20.0
TRANSFER = ("t-offense", "t-contact", "t-chain27", "t-chain36", "t-chain47")


def verdict(lo, hi):
    out = []
    if lo > 0:
        out.append("better")
    if hi < 0:
        out.append("worse")
    if lo > NONINFERIOR_ELO:
        out.append("non-inferior")
    return out or ["inconclusive"]


def check_run(run, games, manifest, run_dir=None):
    """Refuse a run that is not the registered one, played to the end."""
    seed0, pairs = L.RUNS[run]
    problems = []
    want_pairs = sorted([a, b, L.GAMES] for a, b in pairs)
    if sorted(manifest["pairs"]) != want_pairs:
        problems.append(f"pairs {manifest['pairs']} != {want_pairs}")
        raise SystemExit(f"run {run}: " + problems[0])
    if manifest.get("seed0") != seed0:
        problems.append(f"seed0 {manifest.get('seed0')} != {seed0}")
    if manifest.get("kernel") != "native" or manifest.get("games_per_worker") != 32:
        problems.append("not the native kernel at 32 games per worker")
    names = {n for pair in pairs for n in pair}
    chain41 = None
    for name in sorted(names):
        spec = manifest["players"].get(name) or {}
        if name in L.BOTS:
            if spec != {"bot": name}:
                problems.append(f"{name} is not the {name} bot: {spec}")
            continue
        chain, masks, offset = L.PLAYERS[name]
        want_masks = sorted(masks.split(",")) if masks else None
        if (spec.get("masks") or None) != want_masks:
            problems.append(f"{name} masks {spec.get('masks')} != {want_masks}")
        if int(spec.get("seed_offset") or 0) != offset:
            problems.append(f"{name} sampling offset {spec.get('seed_offset')} != {offset}")
        if spec.get("mode") != "sample" or spec.get("temperature") != 1.0:
            problems.append(f"{name} is not sampled at temperature 1")
        sha = manifest["checkpoints"][name]["sha256"]
        if chain == "chain41":
            if sha != R.CHAIN41_SHA256:
                problems.append(f"{name} is not chain 41")
            chain41 = sha
        elif sha == R.CHAIN41_SHA256:
            problems.append(f"{name} is chain 41's blob")
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


def of_pair(games, a, b):
    return [g for g in games if tuple(g["pair"]) == (a, b)]


def pair_rows(games, reps=REPS):
    """tournament_stats' own pair rows, keyed by (A, B)."""
    return {(r["a"], r["b"]): r for r in S.seed_cluster_bootstrap(games, reps=reps)["pairs"]}


def side_means(games):
    """Per game, for A in these games: touchdowns for and against, block targets, draws."""
    n = len(games)
    return {
        "games": n,
        "td_for": sum(g["a_td"] for g in games) / n,
        "td_against": sum(g["b_td"] for g in games) / n,
        "blocks": sum(g["behaviour"][R.side_of_a(g)]["block_targets"] for g in games) / n,
        "draw_rate": sum(g["result_a"] == "D" for g in games) / n,
        "c_steps": sum(g["c_steps"] for g in games) / n,
    }


def paired_contrast(games, masked, plain, reps=REPS, seed=0):
    """Elo(masked pair) - Elo(plain pair) with a seed-cluster interval."""
    _seeds, cells, counts = S.cluster_counts(games)
    k_m, k_p = cells.index(tuple(masked)), cells.index(tuple(plain))
    boots = S.bootstrap_cluster_counts(counts, reps, seed)
    point = counts.sum(axis=0)

    def elo(c):
        share, _score = S._shares(c)
        return S.elo_from_share(share)

    diff = elo(boots[:, k_m]) - elo(boots[:, k_p])
    diff = diff[np.isfinite(diff)]
    lo, hi = (float(v) for v in np.percentile(diff, [2.5, 97.5]))
    value = float(elo(point[k_m]) - elo(point[k_p]))
    # The same contrast on the draw-inclusive score rate, for pairs whose
    # decisive share sits near 1, where decisive-Elo is steep.
    def score(c):
        _share, rate = S._shares(c)
        return rate
    sdiff = score(boots[:, k_m]) - score(boots[:, k_p])
    return {"masked": list(masked), "plain": list(plain), "elo_contrast": value,
            "ci95": [lo, hi], "verdict": verdict(lo, hi), "valid_reps": int(diff.size),
            "score_rate_contrast": float(score(point[k_m]) - score(point[k_p])),
            "score_rate_ci95": [float(v) for v in np.percentile(sdiff, [2.5, 97.5])]}


def activation_breakdown(groups):
    """Per team turn, for the A side of each named group of games."""
    out = {}
    for name, games in groups.items():
        total = dict.fromkeys(AC.KEYS + ("team_turns", "activations", "turnovers"), 0)
        for g in games:
            b = g["behaviour"][R.side_of_a(g)]
            for k in total:
                total[k] += b[k]
        turns = total["team_turns"]
        row = {"games": len(games), "team_turns": turns,
               "activations_per_turn": total["activations"] / turns}
        for c in AC.CLASSES:
            row[c + "_per_turn"] = total["act_" + c] / turns
        measured = total["moved_measured"]
        row["moved_measured"] = measured
        row["moved_mean_net_displacement"] = (
            total["moved_displacement"] / measured if measured else None)
        row["moved_mean_change_distance_to_ball"] = (
            total["moved_d_ball"] / measured if measured else None)
        row["moved_mean_change_distance_from_own_endzone"] = (
            total["moved_d_own_endzone"] / measured if measured else None)
        neg = total["neg_activations"]
        row["negative_trait"] = {
            "activations_per_game": neg / len(games),
            "activations_per_turn": neg / turns,
            "came_out_distracted_or_rooted": total["neg_failed"] / neg if neg else None,
            "ended_at_once": total["neg_empty"] / neg if neg else None,
            "engine_ended_it": total["neg_no_decision"] / neg if neg else None,
            "blocked_or_blitzed": total["neg_blocked"] / neg if neg else None,
            "turn_ended_in_turnover_there": total["neg_turnover"] / neg if neg else None,
            "failures_per_game": total["neg_failed"] / len(games),
            "turnovers_there_per_game": total["neg_turnover"] / len(games),
        }
        row["activations_that_ended_the_turn_in_a_turnover_per_turn"] = (
            total["act_turnover"] / turns)
        out[name] = row
    return out


def fmt(x, d=3):
    return "n/a" if x is None or (isinstance(x, float) and not np.isfinite(x)) else f"{x:.{d}f}"


def print_report(out):
    print("## Transfer of m1\n")
    print("| opponent | pair | W/D/L | decisive share | decisive-Elo [95%] | TD for | TD against | "
          "blocks per game |\n|---|---|---|---|---|---|---|---|")
    for opp, t in out["transfer"].items():
        for who in ("masked", "plain"):
            r, m = t[who]["strength"], t[who]["means"]
            print(f"| {opp} | {r['a']} | {r['W']}/{r['D']}/{r['L']} | {fmt(r['decisive_share'])} | "
                  f"{fmt(r['elo_decisive'], 1)} [{fmt(r['elo_decisive_ci95'][0], 1)}, "
                  f"{fmt(r['elo_decisive_ci95'][1], 1)}] | {fmt(m['td_for'])} | "
                  f"{fmt(m['td_against'])} | {fmt(m['blocks'], 1)} |")
    print("\n| opponent | m1 minus plain, decisive-Elo [95%] | verdict | score-rate contrast [95%] |"
          "\n|---|---|---|---|")
    for opp, t in out["transfer"].items():
        c = t["contrast"]
        print(f"| {opp} | {fmt(c['elo_contrast'], 1)} [{fmt(c['ci95'][0], 1)}, "
              f"{fmt(c['ci95'][1], 1)}] | {', '.join(c['verdict'])} | "
              f"{fmt(c['score_rate_contrast'])} [{fmt(c['score_rate_ci95'][0])}, "
              f"{fmt(c['score_rate_ci95'][1])}] |")
    for key, title in (("m12", "m1 + m2 against plain chain 41"),
                       ("null", "Null control: plain against plain, shifted sampling seeds"),
                       ("both-m1", "Both sides under m1")):
        arm = out[key]
        s = arm["strength"]
        print(f"\n## {title}\n")
        print(f"W/D/L {s['W']}/{s['D']}/{s['L']}; decisive share {fmt(s['decisive_share'])}; "
              f"decisive-Elo {fmt(s['elo_decisive'], 1)} [{fmt(s['elo_decisive_ci95'][0], 1)}, "
              f"{fmt(s['elo_decisive_ci95'][1], 1)}]"
              + (f"; verdict: {', '.join(arm['verdict'])}" if arm.get("verdict") else "")
              + f"; draw rate {fmt(arm['means']['draw_rate'])}; "
                f"{fmt(arm['means']['c_steps'], 0)} engine steps a game\n")
        print("| metric | A | B | A - B [95%] |\n|---|---|---|---|")
        for r in arm["behaviour"]:
            print(f"| {r['metric']} | {fmt(r['a'])} | {fmt(r['b'])} | {fmt(r['a_minus_b'])} "
                  f"[{fmt(r['ci95'][0])}, {fmt(r['ci95'][1])}] |")
    print("\n## What an activation did, per team turn\n")
    groups = out["activations"]
    names = list(groups)
    print("| | " + " | ".join(names) + " |\n|---|" + "---|" * len(names))
    rows = [("activations", "activations_per_turn")] + [(c, c + "_per_turn") for c in AC.CLASSES] + [
        ("moved: mean net displacement in squares", "moved_mean_net_displacement"),
        ("moved: mean change in distance to the ball", "moved_mean_change_distance_to_ball"),
        ("moved: mean change in distance from own end zone",
         "moved_mean_change_distance_from_own_endzone"),
        ("activations that ended the turn in a turnover",
         "activations_that_ended_the_turn_in_a_turnover_per_turn")]
    for label, key in rows:
        print(f"| {label} | " + " | ".join(fmt(groups[n][key]) for n in names) + " |")
    print("\n| negative-trait activations | " + " | ".join(names) + " |\n|---|" + "---|" * len(names))
    for key in ("activations_per_game", "came_out_distracted_or_rooted", "ended_at_once",
                "engine_ended_it", "blocked_or_blitzed", "turn_ended_in_turnover_there",
                "failures_per_game", "turnovers_there_per_game"):
        print(f"| {key.replace('_', ' ')} | "
              + " | ".join(fmt(groups[n]["negative_trait"][key]) for n in names) + " |")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--runs-root", default=os.path.join(ROOT, ".play-artifacts", "tournaments"))
    ap.add_argument("--reps", type=int, default=REPS)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    loaded = {}
    for run in L.RUNS:
        run_dir = os.path.join(args.runs_root, L.run_name(run), "main")
        games, manifest = R.load(run_dir)
        check_run(run, games, manifest, run_dir=run_dir)
        loaded[run] = (games, manifest)
    out = {"schema": "mask-followup-report-v1", "noninferior_elo": NONINFERIOR_ELO,
           "reps": args.reps, "harness_git_head": sorted({m["harness_git_head"]
                                                          for _g, m in loaded.values()}),
           "transfer": {}}
    masked_all, plain_all = [], []
    for run in TRANSFER:
        games, _ = loaded[run]
        opponent = L.RUNS[run][1][0][1]
        masked, plain = (L.M1, opponent), (L.PLAIN, opponent)
        rows = pair_rows(games, args.reps)
        gm, gp = of_pair(games, *masked), of_pair(games, *plain)
        masked_all += gm
        plain_all += gp
        out["transfer"][opponent] = {
            "seed0": L.RUNS[run][0],
            "masked": {"strength": rows[masked], "means": side_means(gm)},
            "plain": {"strength": rows[plain], "means": side_means(gp)},
            "contrast": paired_contrast(games, masked, plain, args.reps),
        }
    for run in ("m12", "null", "both-m1"):
        games, _ = loaded[run]
        (row,) = pair_rows(games, args.reps).values()
        arm = {"seed0": L.RUNS[run][0], "strength": row, "means": side_means(games),
               "behaviour": R.behaviour_table(games, args.reps)}
        if run == "m12":
            arm["verdict"] = verdict(*row["elo_decisive_ci95"])
            arm["mask_stats"] = R.mask_table(games)
            arm["roster"] = R.roster_split(games, args.reps)
        out[run] = arm
    out["activations"] = activation_breakdown({
        "chain 41 + m1 (five transfer runs)": masked_all,
        "plain chain 41 (same runs)": plain_all,
        "chain 41 + m1 v chain 47": of_pair(loaded["t-chain47"][0], L.M1, "chain47"),
        "plain chain 41 v chain 47": of_pair(loaded["t-chain47"][0], L.PLAIN, "chain47"),
        "m1 + m2 v plain": loaded["m12"][0],
        "both under m1": loaded["both-m1"][0],
        "plain v plain (null)": loaded["null"][0],
    })
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, indent=1)
    print_report(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
