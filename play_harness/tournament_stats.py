"""Summaries for tournament game records: pair tables, Wilson CIs, Bradley-Terry.

  .venv/bin/python -m play_harness.tournament_stats --run-dir <dir> [--json out.json]

Pair rows are from A's perspective (A is the first name of the pair). The
decisive-game win share drops draws. The Bradley-Terry fit uses decisive games
only; strengths are reported on the Elo scale (400 / ln 10 per logit) anchored
at mean zero, with standard errors from the observed Fisher information and a
nonparametric bootstrap that resamples games within each pair (rank
frequencies, 95% percentile intervals).
"""
from __future__ import annotations

import argparse
import json
import math
import os
from collections import defaultdict

import numpy as np

ELO = 400.0 / math.log(10.0)


def wilson(k, n, z=1.959963984540054):
    """Wilson score interval for k successes in n trials."""
    if n <= 0:
        return (float("nan"), float("nan"))
    p = k / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def load_games(run_dir):
    with open(os.path.join(run_dir, "games.jsonl")) as f:
        return [json.loads(line) for line in f if line.strip()]


def _side_split(games):
    w = sum(g["result_a"] == "W" for g in games)
    d = sum(g["result_a"] == "D" for g in games)
    l_ = sum(g["result_a"] == "L" for g in games)
    n = len(games)
    return {"games": n, "W": w, "D": d, "L": l_,
            "a_td_per_game": sum(g["a_td"] for g in games) / n if n else float("nan"),
            "b_td_per_game": sum(g["b_td"] for g in games) / n if n else float("nan"),
            "decisive": w + l_, "a_win_share": w / (w + l_) if w + l_ else float("nan")}


def pair_table(games):
    by_pair = defaultdict(list)
    for g in games:
        by_pair[tuple(g["pair"])].append(g)
    rows = []
    for (a, b), gs in by_pair.items():
        row = {"a": a, "b": b, **_side_split(gs)}
        row["ci95"] = wilson(row["W"], row["decisive"])
        row["a_home"] = _side_split([g for g in gs if g["leg"] == "A_home"])
        row["b_home"] = _side_split([g for g in gs if g["leg"] == "B_home"])
        rows.append(row)
    return rows


def win_matrix(games, names):
    """wins[i, j] = decisive games player i won against player j."""
    idx = {n: i for i, n in enumerate(names)}
    wins = np.zeros((len(names), len(names)))
    for g in games:
        a, b = g["pair"]
        if g["result_a"] == "W":
            wins[idx[a], idx[b]] += 1
        elif g["result_a"] == "L":
            wins[idx[b], idx[a]] += 1
    return wins


def bt_fit(wins, iters=10_000, tol=1e-12):
    """Bradley-Terry MLE by the MM algorithm (Hunter 2004). Returns log-strengths, mean 0."""
    n = wins.shape[0]
    games = wins + wins.T
    seen, stack = {0}, [0]
    while stack:
        for j in np.nonzero(games[stack.pop()])[0]:
            if int(j) not in seen:
                seen.add(int(j))
                stack.append(int(j))
    if len(seen) != n:
        raise ValueError("the pair graph is not connected: strengths in different "
                         "components are not comparable")
    total_wins = wins.sum(axis=1)
    if np.any(total_wins == 0) or np.any(total_wins == games.sum(axis=1)):
        raise ValueError("a player with no decisive wins or no decisive losses has no finite MLE")
    p = np.ones(n)
    for _ in range(iters):
        denom = (games / (p[:, None] + p[None, :])).sum(axis=1)
        new = total_wins / denom
        new /= math.exp(np.log(new).mean())
        if np.max(np.abs(new - p)) < tol:
            p = new
            break
        p = new
    theta = np.log(p)
    return theta - theta.mean()


def bt_standard_errors(wins, theta):
    """SEs of mean-zero log-strengths from the observed Fisher information."""
    games = wins + wins.T
    diff = theta[:, None] - theta[None, :]
    q = 1.0 / (1.0 + np.exp(-diff))
    w = games * q * (1 - q)
    info = np.diag(w.sum(axis=1)) - w
    cov = np.linalg.pinv(info)          # minimum-norm inverse = mean-zero constraint
    return np.sqrt(np.clip(np.diag(cov), 0, None)), cov


def bootstrap(games, names, reps=2000, seed=0):
    """Resample games within each pair; refit BT. Returns thetas (reps x n)."""
    rng = np.random.default_rng(seed)
    idx = {n: i for i, n in enumerate(names)}
    counts = defaultdict(lambda: np.zeros(3))          # A wins, draws, A losses per pair
    for g in games:
        counts[tuple(g["pair"])]["WDL".index(g["result_a"])] += 1
    out = []
    for _ in range(reps):
        wins = np.zeros((len(names), len(names)))
        for (a, b), c in counts.items():
            n = int(c.sum())
            w, _, l_ = rng.multinomial(n, c / n)       # same law as resampling the pair's games
            wins[idx[a], idx[b]] += w
            wins[idx[b], idx[a]] += l_
        try:
            out.append(bt_fit(wins))
        except ValueError:
            continue
    return np.array(out)


def ranking(games, names=None, reps=2000, seed=0):
    names = names or sorted({n for g in games for n in g["pair"]})
    wins = win_matrix(games, names)
    theta = bt_fit(wins)
    se, _ = bt_standard_errors(wins, theta)
    boots = bootstrap(games, names, reps=reps, seed=seed)
    ranks = (-boots).argsort(axis=1).argsort(axis=1) + 1 if len(boots) else None
    score = defaultdict(lambda: [0.0, 0])
    for g in games:
        a, b = g["pair"]
        pts = {"W": 1.0, "D": 0.5, "L": 0.0}[g["result_a"]]
        score[a][0] += pts
        score[a][1] += 1
        score[b][0] += 1.0 - pts
        score[b][1] += 1
    rows = []
    for i, name in enumerate(names):
        row = {"name": name, "elo": float(theta[i] * ELO), "elo_se": float(se[i] * ELO),
               "decisive_wins": int(wins[i].sum()), "decisive_losses": int(wins[:, i].sum()),
               "score_rate": score[name][0] / score[name][1]}
        if ranks is not None:
            row["elo_boot_ci95"] = [float(np.percentile(boots[:, i], 2.5) * ELO),
                                    float(np.percentile(boots[:, i], 97.5) * ELO)]
            row["rank_freq"] = {int(r): float((ranks[:, i] == r).mean())
                                for r in range(1, len(names) + 1)}
        rows.append(row)
    rows.sort(key=lambda r: -r["elo"])
    return {"names": names, "rows": rows, "bootstrap_reps": int(len(boots))}


SCORE = {"W": 1.0, "D": 0.5, "L": 0.0}


def leg_pairs(games):
    """{pair: [(A score in leg A_home, A score in leg B_home), ...]} over complete seeds."""
    legs = defaultdict(dict)
    for g in games:
        legs[(tuple(g["pair"]), g["engine_seed"])][g["leg"]] = SCORE[g["result_a"]]
    out = defaultdict(list)
    for (pair, _), d in sorted(legs.items()):
        if "A_home" in d and "B_home" in d:
            out[pair].append((d["A_home"], d["B_home"]))
    return dict(out)


def _corr(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    denom = math.sqrt(float((x * x).sum() * (y * y).sum()))
    return float((x * y).sum() / denom) if denom > 0 else float("nan")


def leg_correlation(games):
    """Correlation of A's score (W 1, D 0.5, L 0) across the two legs of one seed.

    within_pair_centred subtracts each pair's own leg means before pooling, so
    strength gaps between pairs cannot pass for dependence between legs. This is
    the intraclass correlation that sets the design effect 1 + r of a two-leg
    cluster. pooled_uncentred is the Pearson correlation over all pairs pooled
    with no within-pair centring; the round robin doc first reported that one.
    """
    xs, ys, xc, yc, per_pair = [], [], [], [], {}
    for pair, rows in leg_pairs(games).items():
        a = np.array(rows, dtype=float)
        cx, cy = a[:, 0] - a[:, 0].mean(), a[:, 1] - a[:, 1].mean()
        xs.extend(a[:, 0])
        ys.extend(a[:, 1])
        xc.extend(cx)
        yc.extend(cy)
        per_pair[pair] = _corr(cx, cy)
    xs, ys = np.array(xs), np.array(ys)
    return {"within_pair_centred": _corr(xc, yc),
            "pooled_uncentred": _corr(xs - xs.mean(), ys - ys.mean()),
            "seeds": len(xc), "per_pair": per_pair}


def elo_from_share(p):
    """Elo gap implied by a share p (decisive share or draw-inclusive score)."""
    p = np.clip(np.asarray(p, dtype=float), 1e-12, 1 - 1e-12)
    return ELO * np.log(p / (1 - p))


def _shares(c):
    """(decisive share, draw-inclusive score rate) from W/D/L counts on the last axis."""
    c = np.asarray(c, dtype=float)
    w, d, l_ = c[..., 0], c[..., 1], c[..., 2]
    with np.errstate(invalid="ignore", divide="ignore"):
        return w / (w + l_), (w + 0.5 * d) / (w + d + l_)


def _ci(x):
    x = np.asarray(x, dtype=float)
    x = x[np.isfinite(x)]
    return [float(np.percentile(x, 2.5)), float(np.percentile(x, 97.5))] if x.size else \
        [float("nan")] * 2


# ---- seed-cluster bootstrap ---------------------------------------------------
def cluster_counts(games, key=lambda g: tuple(g["pair"])):
    """W/D/L counts per (engine seed, cell). Returns (seeds, cells, counts[S, K, 3]).

    Every pair and both legs of a game index share one engine seed, so the
    seed is the unit of dependence; key(g) names the cell (None drops a game).
    """
    keyed = [(g, key(g)) for g in games]
    seeds = sorted({g["engine_seed"] for g, k in keyed if k is not None})
    cells = sorted({k for _, k in keyed if k is not None})
    si = {s: i for i, s in enumerate(seeds)}
    ci = {c: i for i, c in enumerate(cells)}
    counts = np.zeros((len(seeds), len(cells), 3))
    for g, k in keyed:
        if k is not None:
            counts[si[g["engine_seed"]], ci[k], "WDL".index(g["result_a"])] += 1
    return seeds, cells, counts


def bootstrap_cluster_counts(counts, reps=2000, seed=0):
    """Resample seeds with replacement; a drawn seed brings all its cells and legs."""
    rng = np.random.default_rng(seed)
    n = counts.shape[0]
    out = np.empty((reps,) + counts.shape[1:])
    for r in range(reps):
        mult = np.bincount(rng.integers(0, n, n), minlength=n).astype(float)
        out[r] = np.tensordot(mult, counts, axes=1)
    return out


def seed_cluster_bootstrap(games, names=None, reps=2000, seed=0):
    """Pair shares, score rates and Elo gaps with seed-cluster percentile intervals,
    plus Bradley-Terry strengths when the pair graph is connected."""
    names = names or sorted({n for g in games for n in g["pair"]})
    seeds, pairs, counts = cluster_counts(games)
    boots = bootstrap_cluster_counts(counts, reps, seed)
    point = counts.sum(axis=0)
    rows = []
    for k, (a, b) in enumerate(pairs):
        share, score = _shares(boots[:, k])
        p_share, p_score = _shares(point[k])
        rows.append({
            "a": a, "b": b, "seeds": int((counts[:, k].sum(axis=-1) > 0).sum()),
            "games": int(point[k].sum()), "W": int(point[k, 0]), "D": int(point[k, 1]),
            "L": int(point[k, 2]),
            "decisive_share": float(p_share), "decisive_share_ci95": _ci(share),
            "score_rate": float(p_score), "score_rate_ci95": _ci(score),
            "elo_decisive": float(elo_from_share(p_share)),
            "elo_decisive_ci95": _ci(elo_from_share(share)),
            "elo_decisive_se": float(np.nanstd(elo_from_share(share))),
            "elo_score": float(elo_from_share(p_score)),
            "elo_score_ci95": _ci(elo_from_share(score)),
            "elo_score_se": float(np.nanstd(elo_from_share(score))),
            "p_a_ahead": float(np.mean(share > 0.5)),
        })
    out = {"names": names, "seeds": len(seeds), "reps": int(reps), "pairs": rows}
    idx = {n: i for i, n in enumerate(names)}
    thetas = []
    for rep in boots:
        wins = np.zeros((len(names), len(names)))
        for k, (a, b) in enumerate(pairs):
            wins[idx[a], idx[b]] += rep[k, 0]
            wins[idx[b], idx[a]] += rep[k, 2]
        try:
            thetas.append(bt_fit(wins))
        except ValueError:
            continue
    if thetas:
        th = np.array(thetas)
        out["bt"] = {"reps": len(th), "elo_se": {n: float(th[:, i].std() * ELO) for n, i in idx.items()},
                     "elo_ci95": {n: _ci(th[:, i] * ELO) for n, i in idx.items()},
                     "p_ahead": {a: {b: float(np.mean(th[:, idx[a]] > th[:, idx[b]]))
                                     for b in names if b != a} for a in names}}
    return out


# ---- model fit ----------------------------------------------------------------
def chi2_sf(x, k):
    """Chi-square upper tail Q(k/2, x/2) by series / Lentz continued fraction."""
    a, x = 0.5 * k, 0.5 * float(x)
    if k <= 0:
        raise ValueError("degrees of freedom must be positive")
    if x <= 0:
        return 1.0
    log_front = -x + a * math.log(x) - math.lgamma(a)
    if x < a + 1:
        ap, term, total = a, 1.0 / a, 1.0 / a
        for _ in range(100_000):
            ap += 1
            term *= x / ap
            total += term
            if abs(term) < abs(total) * 1e-16:
                break
        return min(1.0, max(0.0, 1.0 - total * math.exp(log_front)))
    tiny = 1e-300
    b = x + 1 - a
    c, d = 1 / tiny, 1 / b
    h = d
    for i in range(1, 100_000):
        an = -i * (i - a)
        b += 2
        d = an * d + b
        d = tiny if abs(d) < tiny else d
        c = b + an / c
        c = tiny if abs(c) < tiny else c
        d = 1 / d
        delta = d * c
        h *= delta
        if abs(delta - 1) < 1e-16:
            break
    return min(1.0, max(0.0, math.exp(log_front) * h))


def bt_misfit(wins, names, theta=None):
    """Pearson and deviance goodness of fit of Bradley-Terry to the decisive pair counts.

    df = observed pairs - (players - 1). Games are treated as independent: with
    the negative within-seed leg correlation this is slightly conservative.
    """
    theta = bt_fit(wins) if theta is None else theta
    rows, chi2, dev = [], 0.0, 0.0
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            n = wins[i, j] + wins[j, i]
            if n == 0:
                continue
            p = 1.0 / (1.0 + math.exp(theta[j] - theta[i]))
            w = wins[i, j]
            z = (w - n * p) / math.sqrt(n * p * (1 - p))
            chi2 += z * z
            for obs, exp_ in ((w, n * p), (n - w, n * (1 - p))):
                if obs > 0:
                    dev += 2 * obs * math.log(obs / exp_)
            rows.append({"a": names[i], "b": names[j], "decisive": int(n),
                         "observed": float(w / n), "predicted": float(p), "z": float(z)})
    df = len(rows) - (len(names) - 1)
    return {"chi2": chi2, "deviance": dev, "df": df,
            "p": chi2_sf(chi2, df) if df > 0 else float("nan"),
            "p_deviance": chi2_sf(dev, df) if df > 0 else float("nan"), "rows": rows}


def kendall_tau(x, y):
    n = len(x)
    s = 0
    for i in range(n):
        for j in range(i + 1, n):
            s += np.sign(x[i] - x[j]) * np.sign(y[i] - y[j])
    return s / (n * (n - 1) / 2)


def spearman_rho(x, y):
    rx = np.argsort(np.argsort(x))
    ry = np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def markdown_tables(games, rank):
    lines = ["| A | B | games | A W / D / L | A TD/g | B TD/g | decisive | A win share | 95% CI "
             "| A home W/D/L (A TD, B TD) | B home W/D/L (A TD, B TD) |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(pair_table(games), key=lambda r: (r["a"], r["b"])):
        ah, bh = r["a_home"], r["b_home"]
        lines.append(
            f"| {r['a']} | {r['b']} | {r['games']} | {r['W']} / {r['D']} / {r['L']} "
            f"| {r['a_td_per_game']:.3f} | {r['b_td_per_game']:.3f} | {r['decisive']} "
            f"| {r['a_win_share']:.3f} | [{r['ci95'][0]:.3f}, {r['ci95'][1]:.3f}] "
            f"| {ah['W']}/{ah['D']}/{ah['L']} ({ah['a_td_per_game']:.2f}, {ah['b_td_per_game']:.2f}) "
            f"| {bh['W']}/{bh['D']}/{bh['L']} ({bh['a_td_per_game']:.2f}, {bh['b_td_per_game']:.2f}) |")
    lines += ["", "| rank | checkpoint | Elo (BT, mean 0) | SE | bootstrap 95% | P(rank 1) "
              "| decisive W-L | score rate |", "|---|---|---|---|---|---|---|---|"]
    for i, r in enumerate(rank["rows"], 1):
        ci = r.get("elo_boot_ci95", [float("nan")] * 2)
        p1 = r.get("rank_freq", {}).get(1, float("nan"))
        lines.append(f"| {i} | {r['name']} | {r['elo']:+.1f} | {r['elo_se']:.1f} "
                     f"| [{ci[0]:+.1f}, {ci[1]:+.1f}] | {p1:.3f} "
                     f"| {r['decisive_wins']}-{r['decisive_losses']} | {r['score_rate']:.3f} |")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--reps", type=int, default=2000)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    games = load_games(args.run_dir)
    rank = ranking(games, reps=args.reps)
    print(markdown_tables(games, rank))
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"pairs": pair_table(games), "ranking": rank}, f, indent=1)


if __name__ == "__main__":
    main()
