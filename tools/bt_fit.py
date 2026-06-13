#!/usr/bin/env python3
"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.

100%-draw pairings carry no Bradley-Terry information, so they remain visible
in the raw read but are skipped for fitting.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict, deque

try:
    import numpy as np  # noqa: F401
except Exception:
    np = None


EPS = 1e-12


def warn(msg):
    print(f"warning: {msg}", file=sys.stderr)


def parse_rows(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
        for lineno, row in enumerate(reader, start=2):
            try:
                a = row["nameA"].strip()
                b = row["nameB"].strip()
                a_rate = float(row["A_rate"])
                b_rate = float(row["B_rate"])
                draw = float(row["draw_rate"])
                total = int(round(float(row["total_games"])))
            except (TypeError, ValueError) as e:
                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
            if not a or not b:
                warn(f"{path}:{lineno}: skipping row with empty name")
                continue
            rows.append({
                "a": a,
                "b": b,
                "a_rate": a_rate,
                "b_rate": b_rate,
                "draw": draw,
                "total": total,
                "lineno": lineno,
            })
    return rows


def decisive_counts(rows):
    names = []
    seen = set()
    wins = defaultdict(float)
    games = defaultdict(float)
    raw = {}
    skipped = []

    for row in rows:
        a, b = row["a"], row["b"]
        for name in (a, b):
            if name not in seen:
                seen.add(name)
                names.append(name)

        denom = 1.0 - row["draw"]
        if denom <= EPS:
            skipped.append((a, b, "all draws"))
            continue
        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
        p_a = max(0.0, min(1.0, p_a))
        n_decisive = int(round(row["total"] * denom))
        if n_decisive <= 0:
            skipped.append((a, b, "zero decisive games after rounding"))
            continue
        w_a = int(round(n_decisive * p_a))
        w_a = max(0, min(n_decisive, w_a))
        w_b = n_decisive - w_a

        wins[(a, b)] += w_a
        wins[(b, a)] += w_b
        games[frozenset((a, b))] += n_decisive
        raw[frozenset((a, b))] = {
            "a": a,
            "b": b,
            "w_a": w_a,
            "w_b": w_b,
            "n": n_decisive,
            "p_a": w_a / n_decisive,
        }

    return names, wins, games, raw, skipped


def row_decisive_summary(row):
    denom = 1.0 - row["draw"]
    if denom <= EPS:
        return None
    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
    p_a = max(0.0, min(1.0, p_a))
    n_decisive = int(round(row["total"] * denom))
    if n_decisive <= 0:
        return None
    w_a = int(round(n_decisive * p_a))
    w_a = max(0, min(n_decisive, w_a))
    return n_decisive, w_a, n_decisive - w_a, p_a


def connected_components(fit_names, games):
    graph = {name: set() for name in fit_names}
    for pair, n in games.items():
        if n <= 0 or len(pair) != 2:
            continue
        a, b = tuple(pair)
        if a in graph and b in graph:
            graph[a].add(b)
            graph[b].add(a)

    comps = []
    unseen = set(fit_names)
    while unseen:
        start = unseen.pop()
        comp = []
        q = deque([start])
        while q:
            cur = q.popleft()
            comp.append(cur)
            for nxt in graph[cur]:
                if nxt in unseen:
                    unseen.remove(nxt)
                    q.append(nxt)
        comps.append(comp)
    return comps


def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
    pi = {name: 1.0 for name in fit_names}
    total_wins = {
        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
        for name in fit_names
    }

    for _ in range(max_iter):
        new = {}
        max_rel = 0.0
        for name in fit_names:
            denom = 0.0
            for other in fit_names:
                if other == name:
                    continue
                n_ij = games.get(frozenset((name, other)), 0.0)
                if n_ij:
                    denom += n_ij / (pi[name] + pi[other])
            if denom <= 0:
                new[name] = pi[name]
            elif total_wins[name] <= 0:
                new[name] = EPS
            else:
                new[name] = max(EPS, total_wins[name] / denom)
            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
        pi = new
        mean_pi = sum(pi.values()) / len(pi)
        if mean_pi > 0:
            pi = {name: val / mean_pi for name, val in pi.items()}
        if max_rel < tol:
            break
    return pi


def empirical_between(stronger, weaker, wins, games):
    n = games.get(frozenset((stronger, weaker)), 0.0)
    if not n:
        return None
    return wins.get((stronger, weaker), 0.0) / n, int(round(n))


def main():
    ap = argparse.ArgumentParser(
        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
    ap.add_argument("--scale", type=float, default=400.0,
                    help="Elo display scale, default 400")
    args = ap.parse_args()

    if np is None:
        warn("numpy unavailable; using pure Python math fallback")

    rows = parse_rows(args.csv_path)
    if not rows:
        raise SystemExit("no CSV rows found")

    names, wins, games, raw, skipped = decisive_counts(rows)
    total_decisive = {
        name: sum(n for pair, n in games.items() if name in pair)
        for name in names
    }
    excluded = [name for name in names if total_decisive[name] <= 0]
    for name in excluded:
        warn(f"excluding {name}: zero decisive games vs everyone")
    for a, b, why in skipped:
        warn(f"skipping {a} vs {b} for fit: {why}")

    fit_names = [name for name in names if name not in set(excluded)]
    if len(fit_names) < 2:
        raise SystemExit("need at least two connected anchors with decisive games")

    comps = connected_components(fit_names, games)
    if len(comps) > 1:
        comps = sorted(comps, key=len, reverse=True)
        keep = set(comps[0])
        dropped = sorted(name for comp in comps[1:] for name in comp)
        warn("decisive graph is disconnected; fitting largest component only: "
             + ", ".join(comps[0]))
        warn("excluded disconnected anchors: " + ", ".join(dropped))
        fit_names = [name for name in fit_names if name in keep]

    anchor = args.anchor
    if anchor is None:
        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
    if anchor not in fit_names:
        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")

    pi = fit_bt(fit_names, wins, games)
    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
    anchor_elo = raw_elo[anchor]
    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)

    print("raw pair table")
    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
    print("-" * 83)
    for row in rows:
        summary = row_decisive_summary(row)
        if summary is None:
            decisive_s, p_s = "skip", "--"
        else:
            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
        print(f"{row['a'] + ' vs ' + row['b']:<35}"
              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
              f"{decisive_s:>11}{p_s:>10}")

    print()
    print(f"anchor: {anchor} = 0.0 Elo")
    print(f"scale: {args.scale:g}")
    print()
    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
    print("-" * 60)
    for name in ordered:
        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")

    print()
    print("adjacent fitted-vs-empirical decisive win rates")
    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
    print("-" * 67)
    for i in range(len(ordered) - 1):
        hi, lo = ordered[i], ordered[i + 1]
        fit_p = pi[hi] / (pi[hi] + pi[lo])
        emp = empirical_between(hi, lo, wins, games)
        if emp is None:
            emp_s, n_s = "--", "--"
        else:
            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")

    if excluded:
        print()
        print("excluded zero-information anchors: " + ", ".join(excluded))


if __name__ == "__main__":
    main()
