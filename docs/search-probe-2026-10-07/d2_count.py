#!/usr/bin/env python3
"""The count of D2_CHECK_PLAN.md, from the tail batches' outcome records.

  python d2_count.py SEEN_DIR [SEEN_DIR ...] -- NEW_DIR [NEW_DIR ...]

Each directory holds a tail batch's outcomes.jsonl. A tail root is false when
the mean over its fresh pairs of depth1(alternative) minus depth1(a0) is at or
below zero. Prints the three conditions of the plan and every tail root's
fresh gain with its own standard error.
"""
import hashlib
import json
import os
import sys

import numpy as np

REPS, SEED = 2000, 0


def load(folders):
    rows = []
    for folder in folders:
        path = os.path.join(folder, "outcomes.jsonl")
        with open(path, "rb") as f:
            digest = hashlib.sha256(f.read()).hexdigest()
        with open(path) as f:
            batch = [json.loads(line) for line in f if line.strip()]
        print(f"{path}: {len(batch)} roots, sha256 {digest}")
        rows += batch
    return rows


def fresh(row):
    d1 = np.asarray(row["metrics"]["depth1"], dtype=float)
    diff = d1[1] - d1[0]
    return float(diff.mean()), float(diff.std(ddof=1) / np.sqrt(len(diff))), len(diff)


def bound(false, n):
    """Exact one-sided 95% upper bound on a share with `false` of `n` (Clopper-Pearson)."""
    if false >= n:
        return 1.0
    lo, hi = false / n, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        tail = sum(np.exp(_logpmf(k, n, mid)) for k in range(false + 1))
        lo, hi = (mid, hi) if tail > 0.05 else (lo, mid)
    return hi


def _logpmf(k, n, p):
    from math import lgamma, log
    return (lgamma(n + 1) - lgamma(k + 1) - lgamma(n - k + 1) + k * log(p) + (n - k) * log(1 - p))


def summarize(name, rows, which="tail"):
    rows = [r for r in rows if r["set"] == which]
    stats = [(r["engine_seed"], r["class"], r["predicted"]["gain_all"], *fresh(r)) for r in rows]
    false_roots = [s for s in stats if s[3] <= 0]
    games = sorted({s[0] for s in stats})
    false_games = sorted({s[0] for s in false_roots})
    by_game = {g: [s[3] for s in stats if s[0] == g] for g in games}
    rng = np.random.default_rng(SEED)
    means = []
    for _ in range(REPS):
        pick = rng.integers(0, len(games), len(games))
        means.append(np.mean([v for i in pick for v in by_game[games[i]]]))
    out = {"roots": len(stats), "false_roots": len(false_roots), "games": len(games),
           "false_games": len(false_games),
           "bound_roots": bound(len(false_roots), len(stats)),
           "bound_games": bound(len(false_games), len(games)),
           "mean_gain": float(np.mean([s[3] for s in stats])),
           "mean_gain_ci": [float(v) for v in np.percentile(means, [2.5, 97.5])],
           "pairs": sorted({s[5] for s in stats})}
    print(f"{name} ({which}): {out['roots']} roots in {out['games']} games; false roots "
          f"{out['false_roots']} (upper bound {100 * out['bound_roots']:.1f}%), false games "
          f"{out['false_games']} (upper bound {100 * out['bound_games']:.1f}%); mean fresh gain "
          f"{out['mean_gain']:.4f} [{out['mean_gain_ci'][0]:.4f}, {out['mean_gain_ci'][1]:.4f}]; "
          f"fresh pairs per root {out['pairs']}")
    return out, stats


def main():
    args = sys.argv[1:]
    split = args.index("--")
    seen, new = load(args[:split]), load(args[split + 1:])
    if {(r["engine_seed"]) for r in seen} & {(r["engine_seed"]) for r in new}:
        raise SystemExit("the batches share a game")
    new_out, new_stats = summarize("new batch", new)
    all_out, _ = summarize("all batches", seen + new)
    summarize("new batch", new, "control")
    c1 = new_out["bound_roots"] <= 0.10
    c2 = all_out["bound_games"] <= 0.10
    c3 = new_out["mean_gain_ci"][0] > 0
    print(f"condition 1 (new batch, roots, bound <= 10%): {'met' if c1 else 'NOT met'}")
    print(f"condition 2 (all batches, games, bound <= 10%): {'met' if c2 else 'NOT met'}")
    print(f"condition 3 (new batch, lower bound of the mean gain above zero): "
          f"{'met' if c3 else 'NOT met'}")
    print("D2 " + ("MET" if c1 and c2 and c3 else "NOT MET"))
    print("new batch tail roots, lowest fresh gain first:")
    for seed, cls, screen, mean, se, n in sorted(new_stats, key=lambda s: s[3]):
        print(f"  seed {seed} {cls:<13} screen {screen:.3f} fresh {mean:+.4f} se {se:.4f} n {n}")


if __name__ == "__main__":
    main()
