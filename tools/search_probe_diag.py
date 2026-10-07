#!/usr/bin/env python3
"""Offline headroom diagnostic for the search probe (design D1, D2 and D4).

Before a search seat is built: is there anything for a rollout search to find
at the decisions it would search, under the evaluator it would use?

  collect  plays one checkpoint under action masks against itself (the other
           seat on sampling offset 1) on a session that pays the training
           reward manifest. At a uniform sample of seat A's in-scope decisions
           (turn level: an ACTIVATE is legal; DECLARE; the first own decision
           after the own DECLARE) it takes a root: a search clone, both
           recurrent states (A's own view and A's network on the opponent's
           row), the root logits and the action a0 plain play sampled. The real
           game goes on with a0. After the game each root's candidates (a0, then
           the most probable other legal actions) get N rollouts each through
           play_harness.search.Rollouts.evaluate, the entry a search seat will
           call, which gives rollout j the same dice and sampling seeds for
           every candidate. Every per-rollout return is stored.
  analyze  reads the stored returns. The rollout indices are split in two
           halves: an alternative is always SELECTED on half A and JUDGED on
           half B, so nothing is judged on the samples that selected it.

  outcomes-collect, outcomes-analyze
           take the evaluator out of the judgment. In self-play the rollout
           policy IS the real continuation, so playing an action and then both
           sides on to the end of the match, many times on fresh dice, estimates
           what that one deviation does to the result. The first run's games
           are regenerated (and checked against its roots), the roots its rule
           flags and a control draw of unflagged roots are fixed before any
           outcome is seen, and a0 and the alternative are each played to the
           end of the match on common random numbers.

Nothing here is a registered experiment. The returns of collect and analyze
are the shaped training return, not wins.

  OMP_NUM_THREADS=1 .venv/bin/python tools/search_probe_diag.py collect \\
      --checkpoint <blob> --out-dir <dir>
  .venv/bin/python tools/search_probe_diag.py analyze --out-dir <dir>
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

CLASSES = ("turn", "declare", "after_declare")
DELTA = 0.02
RULE_SIZES = (8, 16, 32)
SCHEMA = "search-probe-diag-root-v1"
OUTCOME_SCHEMA = "search-probe-diag-outcome-v1"
SETS = ("flagged", "control")
# Outcome rollouts start at this rollout index: the first run's selection used
# indices from 0, so these are rollouts it never saw.
FRESH_INDEX = 1000
OUTCOME_METRICS = ("win_score", "win", "loss", "td_diff", "depth1", "depth2",
                   "depth1_touchdown", "depth1_other", "depth1_value")


# ---- statistics (numpy only) --------------------------------------------------------------
def clean_returns(returns):
    """(candidates, rollouts) returns with every rollout index dropped that any
    candidate lost to a rejected rollout (nan), so the pairing stays whole."""
    returns = np.asarray(returns, dtype=np.float64)
    return returns[:, np.isfinite(returns).all(axis=0)]


def halves(n):
    """Rollout indices of half A (selection) and half B (judgment)."""
    return np.arange(0, n // 2), np.arange(n // 2, 2 * (n // 2))


def paired_gain(returns, index):
    """Per alternative: mean and standard error of G(alternative) - G(a0) over the
    rollout indices `index`. Row 0 of `returns` is a0."""
    d = returns[1:, index] - returns[0, index]
    n = d.shape[1]
    se = d.std(axis=1, ddof=1) / np.sqrt(n) if n > 1 else np.full(d.shape[0], np.inf)
    return d.mean(axis=1), se


def root_headroom(returns, delta=DELTA):
    """One root's D1 numbers: the alternative that looks best on half A, judged on
    half B.

      best        index into the alternatives (0 = the first alternative)
      gain_a      its paired mean gain over a0 on half A (what selected it)
      gain_b      its paired mean gain over a0 on half B (the judgment)
      se_b        the standard error of gain_b
      headroom    gain_b > delta and gain_b > 2 * se_b
      rule_gain   gain_b if gain_a > delta, else 0: what "play the half-A best
                  when it beats a0 by delta, else a0" earns on half B
    """
    a, b = halves(returns.shape[1])
    mean_a, _ = paired_gain(returns, a)
    mean_b, se_b = paired_gain(returns, b)
    best = int(np.argmax(mean_a))
    gain_b, se = float(mean_b[best]), float(se_b[best])
    return {"best": best, "gain_a": float(mean_a[best]), "gain_b": gain_b, "se_b": se,
            "headroom": bool(gain_b > delta and gain_b > 2.0 * se),
            "rule_gain": gain_b if mean_a[best] > delta else 0.0}


def simulate_rule(returns, n, delta=DELTA, floor=False, resamples=200, rng=None):
    """The deviation rule at n rollouts, simulated on half A and judged on half B.

    Each resample draws n of half A's rollout indices without replacement. The
    rule looks at the alternative with the largest paired mean gain over a0 and
    deviates to it when that mean exceeds delta and two standard errors. With
    floor=True the standard error is at least sqrt(pooled variance / n), the
    pooled variance being the mean over ALL candidates of the variance of their
    n returns: a paired difference that happens to be constant in a small sample
    then no longer reads as certain.

    Returns per root: deviations (count), false (deviations whose half-B gain is
    at or below zero), gain (sum over resamples of the half-B gain of what was
    played, 0 where a0 was kept), resamples.
    """
    rng = rng or np.random.default_rng(0)
    a, b = halves(returns.shape[1])
    if n > len(a):
        raise ValueError(f"n = {n} exceeds half A ({len(a)} rollouts)")
    judge, _ = paired_gain(returns, b)
    index = np.stack([rng.permutation(a)[:n] for _ in range(resamples)])    # (R, n)
    sample = returns[:, index]                                              # (k, R, n)
    d = sample[1:] - sample[0]
    mean = d.mean(axis=2)                                                   # (k - 1, R)
    se = d.std(axis=2, ddof=1) / np.sqrt(n)
    if floor:
        pooled = sample.var(axis=2, ddof=1).mean(axis=0)                    # (R,)
        se = np.maximum(se, np.sqrt(pooled / n))
    best = mean.argmax(axis=0)
    cols = np.arange(resamples)
    deviate = (mean[best, cols] > delta) & (mean[best, cols] > 2.0 * se[best, cols])
    gains = judge[best]
    return {"deviations": int(deviate.sum()),
            "false": int((deviate & (gains <= 0.0)).sum()),
            "gain": float(gains[deviate].sum()), "resamples": resamples}


def variance_pairing(returns):
    """Per alternative: (variance of the paired difference under common random
    numbers, variance the difference would have with independent rollouts)."""
    paired = (returns[1:] - returns[0]).var(axis=1, ddof=1)
    unpaired = returns[1:].var(axis=1, ddof=1) + returns[0].var(ddof=1)
    return paired, unpaired


def ratio_bootstrap(clusters, num, den, reps=2000, seed=0):
    """sum(num) / sum(den) with a percentile bootstrap that resamples whole
    clusters (games). Returns (point, lower 2.5%, upper 97.5%, upper 95%); the
    last is a one-sided upper bound. nan where the denominator is zero."""
    clusters = np.asarray(clusters)
    num, den = np.asarray(num, dtype=np.float64), np.asarray(den, dtype=np.float64)
    names, cluster_of = np.unique(clusters, return_inverse=True)
    num_c = np.bincount(cluster_of, weights=num, minlength=len(names))
    den_c = np.bincount(cluster_of, weights=den, minlength=len(names))
    point = num_c.sum() / den_c.sum() if den_c.sum() > 0 else float("nan")
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(names), size=(reps, len(names)))
    tops, bottoms = num_c[draws].sum(axis=1), den_c[draws].sum(axis=1)
    stats = tops[bottoms > 0] / bottoms[bottoms > 0]
    if stats.size == 0:
        return point, float("nan"), float("nan"), float("nan")
    lo, hi, upper = np.percentile(stats, [2.5, 97.5, 95.0])
    return float(point), float(lo), float(hi), float(upper)


def analyze_roots(roots, delta=DELTA, sizes=RULE_SIZES, resamples=200, reps=2000, seed=0):
    """Every table of the report from stored roots.

    A root is {"game", "class", "returns" (candidates x rollouts, row 0 = a0),
    "types" (an action label per candidate)} and, for an after_declare root,
    "declared" (the kind of the activation). Roots with a single candidate are
    not searched decisions and are skipped.
    """
    rng = np.random.default_rng(seed)
    rows = []
    for root in roots:
        returns = clean_returns(root["returns"])
        if returns.shape[0] < 2 or returns.shape[1] < 4:
            continue
        head = root_headroom(returns, delta)
        paired, unpaired = variance_pairing(returns)
        rule = {(n, floor): simulate_rule(returns, n, delta, floor, resamples, rng)
                for n in sizes if n <= returns.shape[1] // 2 for floor in (False, True)}
        rows.append({"game": root["game"], "class": root["class"], "head": head, "rule": rule,
                     "context": root["class"] + (f" of {root['declared']}"
                                                 if root.get("declared") else ""),
                     "a0_type": root["types"][0], "best_type": root["types"][1 + head["best"]],
                     "a0_top": root.get("a0_rank") == 1,
                     "paired": float(paired.sum()), "unpaired": float(unpaired.sum()),
                     "ratio": float(np.median(paired / np.maximum(unpaired, 1e-12))),
                     "sd": float(returns.std(axis=1, ddof=1).mean()),
                     "dropped": int(np.asarray(root["returns"]).shape[1] - returns.shape[1])})
    out = {"delta": delta, "roots": len(rows), "games": len({r["game"] for r in rows}),
           "headroom": {}, "rule": {}, "pairing": {}, "winners": []}
    groups = {name: [r for r in rows if r["class"] == name] for name in CLASSES}
    groups["all"] = rows
    for name, group in groups.items():
        if not group:
            continue
        games = [r["game"] for r in group]
        ones = np.ones(len(group))
        out["headroom"][name] = {
            "roots": len(group),
            "share": ratio_bootstrap(games, [r["head"]["headroom"] for r in group], ones,
                                     reps, seed),
            "rule_gain": ratio_bootstrap(games, [r["head"]["rule_gain"] for r in group], ones,
                                         reps, seed),
            "rule_deviates": float(np.mean([r["head"]["gain_a"] > delta for r in group])),
            "mean_se_b": float(np.mean([r["head"]["se_b"] for r in group])),
            "mean_return_sd": float(np.mean([r["sd"] for r in group])),
        }
        out["pairing"][name] = {
            "paired_over_unpaired": float(sum(r["paired"] for r in group)
                                          / max(sum(r["unpaired"] for r in group), 1e-12)),
            "median_root_ratio": float(np.median([r["ratio"] for r in group])),
        }
        for key in sorted({k for r in group for k in r["rule"]}):
            sims = [r["rule"][key] for r in group if key in r["rule"]]
            g = [r["game"] for r in group if key in r["rule"]]
            total = np.array([s["resamples"] for s in sims], dtype=np.float64)
            dev = np.array([s["deviations"] for s in sims], dtype=np.float64)
            out["rule"].setdefault(name, []).append({
                "n": key[0], "floor": key[1],
                "deviation_rate": ratio_bootstrap(g, dev, total, reps, seed),
                "false_rate": ratio_bootstrap(g, [s["false"] for s in sims], dev, reps, seed),
                "gain": ratio_bootstrap(g, [s["gain"] for s in sims], total, reps, seed),
            })
    table = {}
    for r in rows:
        if r["head"]["gain_a"] <= delta:
            continue
        cell = table.setdefault((r["context"], r["a0_type"], r["best_type"]),
                                {"count": 0, "gain_b": 0.0, "positive": 0, "headroom": 0})
        cell["count"] += 1
        cell["gain_b"] += r["head"]["gain_b"]
        cell["positive"] += r["head"]["gain_b"] > 0.0
        cell["headroom"] += r["head"]["headroom"]
    for (cls, a0_type, best_type), cell in sorted(table.items(), key=lambda kv: -kv[1]["count"]):
        out["winners"].append({"class": cls, "a0": a0_type, "alternative": best_type,
                               "count": cell["count"], "positive_on_b": cell["positive"],
                               "headroom": cell["headroom"],
                               "mean_gain_b": cell["gain_b"] / cell["count"]})
    out["a0_types"] = {name: _counts(r["a0_type"] for r in group)
                       for name, group in groups.items() if name != "all"}
    # Where the rule's gain sits. A search that only undoes unlucky samples would
    # deviate where a0 was not the policy's most probable action; and a total made
    # of a few large roots is a thinner finding than its interval suggests.
    deviating = [r for r in rows if r["head"]["gain_a"] > delta]
    gains = sorted((r["head"]["rule_gain"] for r in deviating), reverse=True)
    out["concentration"] = {
        "a0_top_all": sum(r["a0_top"] for r in rows),
        "deviating": len(deviating),
        "a0_top_deviating": sum(r["a0_top"] for r in deviating),
        "games_with_a_deviation": len({r["game"] for r in deviating}),
        "top3_share_of_gain": float(sum(gains[:3]) / sum(gains)) if sum(gains) > 0 else 0.0,
        "largest_gains": [float(g) for g in gains[:3]],
    }
    out["dropped_rollout_indices"] = int(sum(r["dropped"] for r in rows))
    return out


def _counts(values):
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _ci(stat, digits=3, scale=1.0, unit=""):
    point, lo, hi, _ = stat
    return f"{point * scale:.{digits}f}{unit} [{lo * scale:.{digits}f}, {hi * scale:.{digits}f}]"


def format_report(summary):
    lines = [f"roots {summary['roots']} from {summary['games']} games; delta {summary['delta']}; "
             "selected on half A, judged on half B; intervals: 95% bootstrap over games", "",
             "D1 headroom", "class            roots  share with headroom    rule gain per decision  "
             "rule deviates  mean SE(B)  return SD"]
    for name, h in summary["headroom"].items():
        lines.append(f"{name:<15} {h['roots']:>6}  {_ci(h['share'], 1, 100, '%'):<21}  "
                     f"{_ci(h['rule_gain'], 4):<23} {h['rule_deviates'] * 100:>11.1f}%  "
                     f"{h['mean_se_b']:>10.4f}  {h['mean_return_sd']:>9.3f}")
    lines += ["", "D2 the deviation rule at n rollouts (resampled from half A, judged on half B)",
              "class            n   SE floor  deviations/decision    false-deviation rate "
              "(upper 95%)     gain per decision"]
    for name, rules in summary["rule"].items():
        for r in rules:
            false = r["false_rate"]
            lines.append(f"{name:<15} {r['n']:>3}  {'yes' if r['floor'] else 'no':<8}  "
                         f"{_ci(r['deviation_rate'], 1, 100, '%'):<22}  "
                         f"{false[0] * 100:5.1f}% ({false[3] * 100:5.1f}%)"
                         f"{'':<16} {_ci(r['gain'], 4)}")
    lines += ["", "D4 variance of the paired difference over the unpaired one",
              "class            pooled ratio  median root ratio"]
    for name, p in summary["pairing"].items():
        lines.append(f"{name:<15} {p['paired_over_unpaired']:>12.3f}  {p['median_root_ratio']:>17.3f}")
    lines += ["", "Roots where the half-A best beats a0 by delta: what it was",
              "decision                a0                  alternative         roots  >0 on B  "
              "headroom  mean gain on B"]
    for w in summary["winners"]:
        lines.append(f"{w['class']:<23} {w['a0']:<19} {w['alternative']:<19} {w['count']:>5}  "
                     f"{w['positive_on_b']:>7}  {w['headroom']:>8}  {w['mean_gain_b']:>14.4f}")
    c = summary["concentration"]
    lines += ["", f"a0 was the policy's most probable action at {c['a0_top_all']} of "
              f"{summary['roots']} roots and at {c['a0_top_deviating']} of the {c['deviating']} "
              "where the rule deviates",
              f"those {c['deviating']} roots come from {c['games_with_a_deviation']} games; the "
              f"three largest gains ({', '.join(f'{g:.3f}' for g in c['largest_gains'])}) are "
              f"{c['top3_share_of_gain'] * 100:.0f}% of the rule's total gain"]
    lines += ["", "a0 by class: " + json.dumps(summary["a0_types"]),
              f"rollout indices dropped for a rejected rollout: {summary['dropped_rollout_indices']}"]
    return "\n".join(lines)


def load_roots(path):
    roots = []
    with open(path) as f:
        for line in f:
            record = json.loads(line)
            if record.get("schema") == SCHEMA and len(record["returns"]) >= 2:
                roots.append(record)
    return roots


# ---- outcome statistics (numpy only) --------------------------------------------------------
def select_outcome_roots(roots, delta=DELTA, seed=0):
    """The flagged and control sets, from the first run's returns alone.

    flagged  every root where the rule deviates on half A (its best alternative
             beats a0 by more than delta there); the alternative is that best.
    control  as many roots, drawn uniformly without replacement from the other
             multi-candidate roots with a fixed seed, split evenly over the
             classes (a remainder goes to the earlier classes, a class that runs
             short is topped up from the rest); the alternative is their
             half-A best too.

    Returns [{"key": (game, class, step), "set", "alt" (candidate index),
    "gain_a", "gain_b", "gain_all"}], in the roots' order.
    """
    scored = []
    for root in roots:
        returns = clean_returns(root["returns"])
        if returns.shape[0] < 2 or returns.shape[1] < 4:
            continue
        head = root_headroom(returns, delta)
        full, _ = paired_gain(returns, np.arange(returns.shape[1]))
        scored.append({"key": (root["game"], root["class"], root["step"]),
                       "alt": 1 + head["best"], "gain_a": head["gain_a"],
                       "gain_b": head["gain_b"], "gain_all": float(full[head["best"]]),
                       "set": "flagged" if head["gain_a"] > delta else None})
    flagged = [r for r in scored if r["set"]]
    rng = np.random.default_rng(seed)
    pools = {c: [r for r in scored if not r["set"] and r["key"][1] == c] for c in CLASSES}
    want = {c: len(flagged) // len(CLASSES) + (i < len(flagged) % len(CLASSES))
            for i, c in enumerate(CLASSES)}
    short = 0
    for c in CLASSES:
        take = min(want[c], len(pools[c]))
        short += want[c] - take
        for i in sorted(rng.choice(len(pools[c]), size=take, replace=False).tolist()):
            pools[c][i]["set"] = "control"
    rest = [r for r in scored if not r["set"]]
    for i in sorted(rng.choice(len(rest), size=min(short, len(rest)), replace=False).tolist()):
        rest[i]["set"] = "control"
    return [r for r in scored if r["set"]]


def outcome_differences(record):
    """Per metric, the paired differences alternative - a0 over the rollout
    indices where both candidates ended their match naturally."""
    values = {m: np.array([[np.nan if v is None else v for v in row]
                           for row in record["metrics"][m]], dtype=np.float64)
              for m in OUTCOME_METRICS}
    valid = np.isfinite(values["win_score"]).all(axis=0)
    return {m: v[1, valid] - v[0, valid] for m, v in values.items()}, \
        {m: v[:, valid] for m, v in values.items()}, int((~valid).sum())


def cluster_correlation(clusters, x, y, reps=2000, seed=0):
    """Pearson r of x and y, the least-squares slope of y on x, and their
    percentile intervals from a bootstrap over whole clusters:
    (r, r low, r high, slope, slope low, slope high)."""
    clusters, x, y = np.asarray(clusters), np.asarray(x, float), np.asarray(y, float)

    def fit(xs, ys):
        if len(xs) < 3 or xs.std() == 0 or ys.std() == 0:
            return np.nan, np.nan
        return float(np.corrcoef(xs, ys)[0, 1]), float(np.polyfit(xs, ys, 1)[0])

    r, slope = fit(x, y)
    names = np.unique(clusters)
    members = [np.flatnonzero(clusters == n) for n in names]
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(reps):
        index = np.concatenate([members[i] for i in rng.integers(0, len(names), len(names))])
        draws.append(fit(x[index], y[index]))
    draws = np.array(draws)
    ok = np.isfinite(draws[:, 0])
    if not ok.any():
        return r, np.nan, np.nan, slope, np.nan, np.nan
    r_lo, r_hi = np.percentile(draws[ok, 0], [2.5, 97.5])
    s_lo, s_hi = np.percentile(draws[ok, 1], [2.5, 97.5])
    return r, float(r_lo), float(r_hi), slope, float(s_lo), float(s_hi)


def analyze_outcomes(records, reps=2000, seed=0, largest=3):
    """Every table of the outcome report from stored outcome records."""
    rows = []
    for record in records:
        diffs, values, excluded = outcome_differences(record)
        n = len(diffs["win_score"])
        if n < 2:
            continue
        row = {"game": record["game"], "class": record["class"], "set": record["set"],
               "step": record["step"], "n": n, "excluded": excluded,
               "types": record["types"], "declared": record.get("declared"),
               "predicted": record["predicted"], "description": record.get("description", []),
               "mean": {m: float(d.mean()) for m, d in diffs.items()},
               "se": {m: float(d.std(ddof=1) / np.sqrt(n)) for m, d in diffs.items()},
               "changed": float((diffs["win_score"] != 0).mean()),
               "a0_win_score": float(values["win_score"][0].mean()),
               "paired": {}, "unpaired": {}}
        for m in ("win_score", "td_diff", "depth1", "depth2"):
            row["paired"][m] = float(diffs[m].var(ddof=1))
            row["unpaired"][m] = float(values[m][0].var(ddof=1) + values[m][1].var(ddof=1))
        rows.append(row)
    out = {"roots": len(rows), "games": len({r["game"] for r in rows}),
           "excluded_rollout_indices": int(sum(r["excluded"] for r in rows)),
           "rollout_pairs": int(sum(r["n"] for r in rows)), "sets": {}, "pairing": {},
           "correlation": {}, "largest": [], "flagged_roots": []}
    for name in SETS:
        for cls in ("all",) + CLASSES:
            group = [r for r in rows if r["set"] == name and cls in ("all", r["class"])]
            if not group:
                continue
            games, ones = [r["game"] for r in group], np.ones(len(group))
            cell = {"roots": len(group), "games": len(set(games)),
                    "changed": float(np.mean([r["changed"] for r in group])),
                    "predicted_b": float(np.mean([r["predicted"]["gain_b"] for r in group]))}
            for m in OUTCOME_METRICS:
                cell[m] = ratio_bootstrap(games, [r["mean"][m] for r in group], ones, reps, seed)
            out["sets"].setdefault(name, {})[cls] = cell
        group = [r for r in rows if r["set"] == name]
        if group:
            out["pairing"][name] = {
                m: float(sum(r["paired"][m] for r in group)
                         / max(sum(r["unpaired"][m] for r in group), 1e-12))
                for m in ("win_score", "td_diff", "depth1", "depth2")}
    for name, group in [("all", rows)] + [(n, [r for r in rows if r["set"] == n])
                                          for n in SETS]:
        if len(group) < 3:
            continue
        games = [r["game"] for r in group]
        realized = [r["mean"]["win_score"] for r in group]
        out["correlation"][name] = {
            # The first run's judged gain is independent of these rollouts. The
            # depth-1 gain measured here shares their dice with the result.
            "first_run": cluster_correlation(games, [r["predicted"]["gain_b"] for r in group],
                                             realized, reps, seed),
            "first_run_td": cluster_correlation(
                games, [r["predicted"]["gain_b"] for r in group],
                [r["mean"]["td_diff"] for r in group], reps, seed),
            "same_rollouts": cluster_correlation(games, [r["mean"]["depth1"] for r in group],
                                                 realized, reps, seed),
            "depth2_same_rollouts": cluster_correlation(
                games, [r["mean"]["depth2"] for r in group], realized, reps, seed),
            "roots": len(group)}
    ranked = sorted(rows, key=lambda r: -r["predicted"]["gain_b"])
    for r in ranked[:largest]:
        out["largest"].append({k: r[k] for k in ("game", "class", "step", "set", "n", "types",
                                                 "declared", "predicted", "description",
                                                 "mean", "se", "changed")})
    for r in ranked:
        if r["set"] == "flagged":
            out["flagged_roots"].append({
                "decision": r["class"] + (f" of {r['declared']}" if r["declared"] else ""),
                "a0": r["types"][0], "alternative": r["types"][1],
                "predicted": r["predicted"]["gain_b"], "a0_win_score": r["a0_win_score"],
                **{m: (r["mean"][m], r["se"][m]) for m in ("depth1", "depth2", "win_score",
                                                          "td_diff")}})
    return out


def format_outcome_report(summary):
    lines = [f"{summary['roots']} roots from {summary['games']} games, "
             f"{summary['rollout_pairs']} paired full-match rollouts; "
             f"{summary['excluded_rollout_indices']} rollout indices excluded "
             "(a candidate did not end its match naturally)",
             "every number is alternative minus a0, a mean over roots; intervals: 95% "
             "bootstrap over games", ""]
    heads = (("win_score", "win score", 4), ("win", "P(win)", 4), ("loss", "P(loss)", 4),
             ("td_diff", "TD difference", 3))
    lines.append("Realized, to the end of the match")
    lines.append(f"{'set':<8} {'class':<14} roots  " + "  ".join(f"{t:<26}" for _, t, _ in heads)
                 + "  result changed")
    for name, cells in summary["sets"].items():
        for cls, cell in cells.items():
            lines.append(f"{name:<8} {cls:<14} {cell['roots']:>5}  "
                         + "  ".join(f"{_ci(cell[m], d):<26}" for m, _, d in heads)
                         + f"  {cell['changed'] * 100:5.1f}%")
    lines += ["", "The evaluator's view of the same rollouts (shaped return)",
              f"{'set':<8} {'class':<14} first run  depth 1                     "
              "depth 2                     depth 1 = touchdowns + other reward + value term"]
    for name, cells in summary["sets"].items():
        for cls, cell in cells.items():
            parts = " + ".join(f"{cell[m][0]:+.4f}" for m in
                               ("depth1_touchdown", "depth1_other", "depth1_value"))
            lines.append(f"{name:<8} {cls:<14} {cell['predicted_b']:>9.4f}  "
                         f"{_ci(cell['depth1'], 4):<26}  {_ci(cell['depth2'], 4):<26}  {parts}")
    lines += ["", "Does the predicted gain track the realized win-score gain (across roots)",
              f"{'roots':<8} {'predictor':<34} r                        "
              "win score per unit of predicted gain"]
    labels = (("first_run", "first run's judged depth-1 gain"),
              ("same_rollouts", "depth-1 gain, these rollouts"),
              ("depth2_same_rollouts", "depth-2 gain, these rollouts"))
    for name, cell in summary["correlation"].items():
        for key, label in labels:
            r, r_lo, r_hi, slope, s_lo, s_hi = cell[key]
            lines.append(f"{name:<8} {label:<34} {r:+.2f} [{r_lo:+.2f}, {r_hi:+.2f}]"
                         f"{'':<6} {slope:+.2f} [{s_lo:+.2f}, {s_hi:+.2f}]")
    lines += ["", "The same against the realized touchdown difference (first run's gain only)",
              f"{'roots':<8} r                        touchdowns per unit of predicted gain "
              "(2.5 if the gain were all touchdowns)"]
    for name, cell in summary["correlation"].items():
        r, r_lo, r_hi, slope, s_lo, s_hi = cell["first_run_td"]
        lines.append(f"{name:<8} {r:+.2f} [{r_lo:+.2f}, {r_hi:+.2f}]{'':<6} "
                     f"{slope:+.2f} [{s_lo:+.2f}, {s_hi:+.2f}]")
    lines += ["", "Variance of the paired difference over the unpaired one",
              f"{'set':<8} win score  TD difference  depth 1  depth 2"]
    for name, cell in summary["pairing"].items():
        lines.append(f"{name:<8} {cell['win_score']:>9.3f}  {cell['td_diff']:>13.3f}  "
                     f"{cell['depth1']:>7.3f}  {cell['depth2']:>7.3f}")
    lines += ["", "The largest predicted gains, one root each (mean, standard error over rollouts)"]
    for r in summary["largest"]:
        lines.append(f"game {r['game']} step {r['step']} ({r['class']}, {r['set']}, "
                     f"{r['n']} pairs): first run {r['predicted']['gain_b']:.3f}")
        for text in r["description"]:
            lines.append("    " + text)
        lines.append("    " + "; ".join(
            f"{label} {r['mean'][m]:+.3f} ({r['se'][m]:.3f})" for m, label in
            (("win_score", "win score"), ("win", "P(win)"), ("loss", "P(loss)"),
             ("td_diff", "TD difference"))))
        lines.append("    " + "; ".join(
            f"{label} {r['mean'][m]:+.3f} ({r['se'][m]:.3f})" for m, label in
            (("depth1", "depth 1"), ("depth2", "depth 2"), ("depth1_touchdown", "touchdowns"),
             ("depth1_other", "other reward"), ("depth1_value", "value term"))))
    lines += ["", "Every flagged root, largest predicted gain first (mean, standard error over "
              "rollouts)",
              f"{'decision':<23} {'a0':<15} {'alternative':<16} first run  depth 1  depth 2  "
              "win score        TD difference    a0 win score"]
    for r in summary["flagged_roots"]:
        lines.append(f"{r['decision']:<23} {r['a0']:<15} {r['alternative']:<16} "
                     f"{r['predicted']:>9.3f}  {r['depth1'][0]:>7.3f}  {r['depth2'][0]:>+7.3f}  "
                     f"{r['win_score'][0]:+.3f} ({r['win_score'][1]:.3f})   "
                     f"{r['td_diff'][0]:+.3f} ({r['td_diff'][1]:.3f})   {r['a0_win_score']:.2f}")
    return "\n".join(lines)


# ---- collection ---------------------------------------------------------------------------
def action_label(tup, E):
    """An action's type, with the declared kind for a DECLARE."""
    name = E.ACTION_TYPES[tup[0]]
    if name == "DECLARE" and tup[1] < len(E.ACT_KINDS):
        return f"DECLARE:{E.ACT_KINDS[tup[1]]}"
    return name


def decision_class(types, after_declare, A):
    """The in-scope class of a decision from the action types on offer, or None."""
    if A["ACTIVATE"] in types:
        return "turn"
    if A["DECLARE"] in types:
        return "declare"
    return "after_declare" if after_declare else None


class Harness:
    """The play harness, loaded once: modules, the checkpoint and the manifest."""

    def __init__(self, checkpoint, manifest, masks):
        import torch

        from play_harness import engine as E
        from play_harness import search as S
        from play_harness import tournament as T
        from play_harness.policy import MaskedPolicySeat, load_checkpoint, restrict_support

        torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "1")))
        self.torch, self.E, self.S, self.T = torch, E, S, T
        self.MaskedPolicySeat, self.restrict_support = MaskedPolicySeat, restrict_support
        self.masks = tuple(masks)
        self.policy, self.provenance = load_checkpoint(checkpoint)
        self.manifest = E.load_reward_manifest(manifest)

    def meta(self):
        return {"checkpoint_sha256": self.provenance["checkpoint_sha256"],
                "masks": list(self.masks), "reward_manifest": self.manifest["name"],
                "reward_manifest_sha256": self.manifest["sha256"], "gamma": self.S.GAMMA,
                "opponent_seed_offset": 1, "temperature": 1.0}

    def play_game(self, engine_seed, a, per_class, totals):
        """One real game with seat A on side `a`. Returns (roots by class, A's
        sampling seed, engine steps). A root holds a search clone taken at the
        decision, A's two recurrent states, the root logits and support, and a0."""
        torch, E, S, T = self.torch, self.E, self.S, self.T
        seeds = [T.sampling_seed(engine_seed, side) for side in (0, 1)]
        seeds[1 - a] = (seeds[1 - a] + T.SEED_OFFSET_STRIDE) % (1 << 62)
        seats = [self.MaskedPolicySeat(self.policy, side, seed=seeds[side], masks=self.masks)
                 for side in (0, 1)]
        for seat in seats:
            seat.reset_match()
        eng = E.Engine(engine_seed, rewards=self.manifest["rewards"])
        shadow = self.policy.initial_state(1)
        pick = random.Random(engine_seed)
        kept = {c: [] for c in CLASSES}
        seen = {c: 0 for c in CLASSES}
        declared = None                                     # the kind A last declared
        step = 0
        while True:
            team = eng.decision_team
            was_declare = seats[a]._after_declare
            obs = [eng.obs(0), eng.obs(1)]
            supports = [eng.joint_support(0), eng.joint_support(1)]
            outs = [seats[s].step(obs[s], supports[s], s == team) for s in (0, 1)]
            # A's own network on the opponent's row, every step: the state a
            # search seat would hold for its opponent model.
            _, _, shadow = self.policy.forward_eval(
                torch.from_numpy(obs[1 - a]).reshape(1, -1), shadow)
            if team == a:
                support, _ = self.restrict_support(supports[a], self.masks, was_declare)
                types = {int(t) & 1023 for t in support}
                cls = decision_class(types, was_declare, E.A)
                if cls is not None:
                    totals["in_scope"][cls] += 1
                    if len(support) < 2:
                        totals["single_action"][cls] += 1
                    else:
                        # Reservoir: a uniform sample of this game's searchable
                        # decisions of the class.
                        seen[cls] += 1
                        slot = len(kept[cls]) if len(kept[cls]) < per_class \
                            else pick.randrange(seen[cls])
                        if slot < per_class:
                            root = {
                                "clone": eng.clone_for_search(0, S.SEARCH_DICE_STREAM),
                                "own": seats[a].state.clone(), "opp": shadow.clone(),
                                "logits": outs[a]["logits"].copy(), "support": support,
                                "a0": tuple(int(v) for v in outs[a]["tuple"]), "step": step,
                                "declared": declared if cls == "after_declare" else None,
                                "flags": (was_declare, seats[1 - a]._after_declare)}
                            if slot < len(kept[cls]):
                                kept[cls][slot]["clone"].close()
                                kept[cls][slot] = root
                            else:
                                kept[cls].append(root)
            if team == a and outs[a]["tuple"][0] == E.A["DECLARE"]:
                declared = action_label(outs[a]["tuple"], E).split(":")[-1]
            rc = eng.step(*outs[team]["tuple"])
            step += 1
            if rc == E.STEP_TERMINAL:
                break
            if rc != E.STEP_OK:
                raise SystemExit(f"engine refused a step: rc={rc}")
        eng.close()
        return kept, seeds[a], step

    def candidates(self, root, limit):
        """a0 first, then the most probable other actions of the root's support:
        (tuples, policy probabilities, rank of a0)."""
        E = self.E
        tuples, probs = self.S.joint_probabilities(root["logits"], root["support"])
        first = int(np.flatnonzero(tuples == E.pack_tuple(*root["a0"]))[0])
        order = [first] + [i for i in range(len(tuples)) if i != first][:limit - 1]
        return ([E.unpack_tuple(tuples[i]) for i in order], [float(probs[i]) for i in order],
                first + 1, int(len(tuples)))


def new_totals(stops):
    return {"roots": 0, "engine_steps": 0, "rollout_seconds": 0.0, "games": 0,
            "in_scope": {c: 0 for c in CLASSES}, "single_action": {c: 0 for c in CLASSES},
            "stops": {s: 0 for s in stops}}


def collect(args):
    h = Harness(args.checkpoint, args.manifest, args.mask)
    E, S = h.E, h.S
    os.makedirs(args.out_dir, exist_ok=True)
    roots_path = os.path.join(args.out_dir, "roots.jsonl")
    if os.path.exists(roots_path):
        raise SystemExit(f"{roots_path} exists; choose a fresh --out-dir")
    meta = dict(h.meta(), max_rollout_steps=S.MAX_ROLLOUT_STEPS, seed0=args.seed0,
                games=args.games, per_class=args.per_class, rollouts=args.rollouts,
                candidates=args.candidates)
    rollouts = [S.Rollouts(h.policy, seat, masks=h.masks) for seat in (0, 1)]
    totals = new_totals(S.STOPS)
    started = time.time()
    with open(roots_path, "w") as sink:
        for game in range(args.games):
            if time.time() - started > args.budget_seconds:
                print(f"time budget reached before game {game}", flush=True)
                break
            engine_seed = args.seed0 + game
            a = game % 2                                    # seat A's side this game
            kept, seed, step = h.play_game(engine_seed, a, args.per_class, totals)
            for cls in CLASSES:
                for root in kept[cls]:
                    candidates, probs, rank, support = h.candidates(root, args.candidates)
                    t0 = time.time()
                    batch = rollouts[a].evaluate(
                        root["clone"], root["own"], root["opp"], candidates, args.rollouts,
                        seed, root["step"], after_declare=root["flags"])
                    totals["rollout_seconds"] += time.time() - t0
                    totals["engine_steps"] += batch.engine_steps
                    totals["roots"] += 1
                    for stop in S.STOPS:
                        totals["stops"][stop] += batch.count(stop)
                    sink.write(json.dumps({
                        "schema": SCHEMA, "game": game, "engine_seed": engine_seed, "seat": a,
                        "step": root["step"], "class": cls, "support": support,
                        "tuples": [list(c) for c in candidates],
                        "types": [action_label(c, E) for c in candidates],
                        "declared": root["declared"], "probs": probs, "a0_rank": rank,
                        "returns": [[None if not np.isfinite(v) else float(v) for v in row]
                                    for row in batch.returns],
                        "steps": batch.steps.mean(axis=1).tolist(),
                    }) + "\n")
                    sink.flush()
                    root["clone"].close()
            totals["games"] += 1
            rate = totals["engine_steps"] / max(totals["rollout_seconds"], 1e-9)
            print(f"game {game + 1}/{args.games}: {step} steps, roots so far {totals['roots']}, "
                  f"rollout steps {totals['engine_steps']} at {rate:.0f}/s, "
                  f"elapsed {time.time() - started:.0f} s", flush=True)
    meta.update(totals, seconds=round(time.time() - started, 1))
    with open(os.path.join(args.out_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print("done", json.dumps(meta), flush=True)
    return 0


def describe_root(E, clone, seat, candidates):
    """Plain lines saying what a root was and what each candidate does: the score
    and turn, where the ball is, and for each action who acts and on what."""
    m = clone.match()
    legal = {la.tuple: la for la in clone.legal()}
    held = E.BALL_STATES.index("held")
    has_ball = 1 << E.PLAYER_FLAGS.index("has_ball")
    goal = E.PITCH_LEN - 1 if seat == 0 else 0           # bb_endzone_x: HOME attacks x = 25

    def player(slot):
        p = m.players[slot]
        name = clone.position_display(m.team_id[slot >> 4], p.position_id) or f"slot {slot}"
        side = "own" if slot >> 4 == seat else "opposing"
        ball = ", carrying the ball" if p.flags & has_ball else ""
        return f"{side} {name} at ({p.x},{p.y}), {E.STANCES[p.stance]}{ball}"

    if m.ball.state == held and m.ball.carrier < E.NUM_PLAYERS:
        ball = f"held by {player(m.ball.carrier)}"
    else:
        ball = f"{E.BALL_STATES[m.ball.state]} at ({m.ball.x},{m.ball.y})"
    lines = [f"half {m.half}, own turn {m.turn[seat]}, score {m.score[seat]}-{m.score[1 - seat]}, "
             f"ball {ball}, {abs(goal - m.ball.x)} squares from the end zone the searcher attacks"]
    mover = m.stack[m.stack_top - 1].a if m.stack_top else E.NUM_PLAYERS
    for label, tup in zip(("a0", "alternative"), candidates):
        la = legal.get(tuple(tup))
        name = action_label(tup, E)
        if la is None:
            text = name
        elif la.type_name == "ACTIVATE":
            text = f"activate {player(la.arg)}"
        elif la.type_name in ("STEP", "JUMP", "BLOCK_TARGET", "PASS_TARGET", "HANDOFF_TARGET",
                              "FOUL_TARGET", "PUSH_SQUARE"):
            target = m.grid[la.x][la.y]
            text = f"{name} to ({la.x},{la.y})" + (f": {player(target - 1)}" if target else "")
        else:
            text = name
        if la is not None and la.type_name != "ACTIVATE" and mover < E.NUM_PLAYERS:
            text += f" [acting: {player(mover)}]"
        lines.append(f"{label}: {text}")
    return lines


def outcome_metrics(batch, k, n, gamma):
    """Per candidate and rollout, what the outcome report needs; None for a
    rollout that did not end its match naturally."""
    metrics = {m: [[None] * n for _ in range(k)] for m in OUTCOME_METRICS}
    for c in range(k):
        for j in range(n):
            b = c * n + j
            if batch.stops[b] != "terminal":
                continue
            own, opp = (int(v) for v in batch.scores[c, j])
            total, touchdowns = float(batch.rewards[c, j]), float(batch.touchdowns[c, j])
            marks = batch.marks[b]
            # The return as the search would have read it at the end of the own
            # turn; a match that ended first has only its collected reward.
            steps, paid, tds, value = marks[0] if marks else (0, total, touchdowns, 0.0)
            value_term = gamma ** steps * value
            deeper = marks[1] if len(marks) > 1 else None
            row = {"win_score": 1.0 if own > opp else 0.5 if own == opp else 0.0,
                   "win": float(own > opp), "loss": float(own < opp), "td_diff": float(own - opp),
                   "depth1": paid + value_term,
                   "depth2": deeper[1] + gamma ** deeper[0] * deeper[3] if deeper else total,
                   "depth1_touchdown": tds, "depth1_other": paid - tds,
                   "depth1_value": value_term}
            for m, v in row.items():
                metrics[m][c][j] = v
    return metrics


def outcomes_collect(args):
    first = load_roots(os.path.join(args.first_run, "roots.jsonl"))
    with open(os.path.join(args.first_run, "meta.json")) as f:
        first_meta = json.load(f)
    for root in first:
        root["returns"] = np.array([[np.nan if v is None else v for v in row]
                                    for row in root["returns"]], dtype=np.float64)
    selection = {r["key"]: r for r in select_outcome_roots(first, args.delta, args.selection_seed)}
    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "outcomes.jsonl")
    if os.path.exists(out_path):
        raise SystemExit(f"{out_path} exists; choose a fresh --out-dir")
    # The selection is on disk before any outcome rollout is played.
    with open(os.path.join(args.out_dir, "selection.json"), "w") as f:
        json.dump([dict(r, key=list(r["key"])) for r in selection.values()], f, indent=1)
    print(f"selection: { {s: sum(r['set'] == s for r in selection.values()) for s in SETS} }",
          flush=True)
    h = Harness(args.checkpoint, args.manifest, first_meta["masks"])
    E, S = h.E, h.S
    if h.provenance["checkpoint_sha256"] != first_meta["checkpoint_sha256"] or \
            h.manifest["sha256"] != first_meta["reward_manifest_sha256"]:
        raise SystemExit("checkpoint or reward manifest differs from the first run's")
    expected = {(r["game"], r["class"], r["step"]): r for r in first}
    rollouts = [S.Rollouts(h.policy, seat, masks=h.masks, horizon=S.HORIZON_MATCH,
                           max_steps=1_000_000) for seat in (0, 1)]
    totals = new_totals(S.STOPS)
    counts = {"flagged": args.rollouts, "control": args.control_rollouts}
    matched = 0
    started = time.time()
    with open(out_path, "w") as sink:
        for game in range(first_meta["games"]):
            engine_seed = first_meta["seed0"] + game
            a = game % 2
            kept, seed, step = h.play_game(engine_seed, a, first_meta["per_class"], totals)
            for cls in CLASSES:
                for root in kept[cls]:
                    candidates, probs, rank, support = h.candidates(root, first_meta["candidates"])
                    key = (game, cls, root["step"])
                    was = expected.get(key)
                    # The regenerated root must be the first run's root: same step
                    # and class (the key), same a0, same candidates in order.
                    if was is None or [list(c) for c in candidates] != was["tuples"] or \
                            list(root["a0"]) != was["tuples"][0] or was["seat"] != a:
                        raise SystemExit(f"regenerated root {key} is not the first run's")
                    matched += 1
                    chosen = selection.get(key)
                    if chosen is not None:
                        pair = [candidates[0], candidates[chosen["alt"]]]
                        n = counts[chosen["set"]]
                        t0 = time.time()
                        batch = rollouts[a].evaluate(
                            root["clone"], root["own"], root["opp"], pair, n, seed, root["step"],
                            after_declare=root["flags"], first_index=FRESH_INDEX)
                        totals["rollout_seconds"] += time.time() - t0
                        totals["engine_steps"] += batch.engine_steps
                        totals["roots"] += 1
                        for stop in S.STOPS:
                            totals["stops"][stop] += batch.count(stop)
                        sink.write(json.dumps({
                            "schema": OUTCOME_SCHEMA, "game": game, "engine_seed": engine_seed,
                            "seat": a, "step": root["step"], "class": cls, "set": chosen["set"],
                            "declared": root["declared"],
                            "tuples": [list(c) for c in pair],
                            "types": [action_label(c, E) for c in pair],
                            "probs": [probs[0], probs[chosen["alt"]]],
                            "predicted": {k: chosen[k] for k in ("gain_a", "gain_b", "gain_all")},
                            "description": describe_root(E, root["clone"], a, pair),
                            "mean_steps": batch.steps.mean(axis=1).tolist(),
                            "metrics": outcome_metrics(batch, 2, n, S.GAMMA),
                        }) + "\n")
                        sink.flush()
                    root["clone"].close()
            totals["games"] += 1
            rate = totals["engine_steps"] / max(totals["rollout_seconds"], 1e-9)
            print(f"game {game + 1}/{first_meta['games']}: roots matched {matched}, played "
                  f"{totals['roots']}/{len(selection)}, rollout steps {totals['engine_steps']} "
                  f"at {rate:.0f}/s, elapsed {time.time() - started:.0f} s", flush=True)
    if matched != len(first) or totals["roots"] != len(selection):
        raise SystemExit(f"matched {matched} of {len(first)} roots, played {totals['roots']} "
                         f"of {len(selection)} selected")
    meta = dict(h.meta(), first_run=os.path.abspath(args.first_run), delta=args.delta,
                selection_seed=args.selection_seed, rollouts=counts, first_index=FRESH_INDEX,
                roots_matched=matched, **totals, seconds=round(time.time() - started, 1))
    with open(os.path.join(args.out_dir, "outcomes_meta.json"), "w") as f:
        json.dump(meta, f, indent=1)
    print("done", json.dumps(meta), flush=True)
    return 0


def outcomes_analyze(args):
    with open(os.path.join(args.out_dir, "outcomes.jsonl")) as f:
        records = [json.loads(line) for line in f]
    records = [r for r in records if r.get("schema") == OUTCOME_SCHEMA]
    summary = analyze_outcomes(records, reps=args.reps)
    report = format_outcome_report(summary)
    with open(os.path.join(args.out_dir, "outcomes_summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    with open(os.path.join(args.out_dir, "outcomes_report.txt"), "w") as f:
        f.write(report + "\n")
    print(report)
    return 0


def analyze(args):
    roots = load_roots(os.path.join(args.out_dir, "roots.jsonl"))
    for root in roots:
        root["returns"] = np.array([[np.nan if v is None else v for v in row]
                                    for row in root["returns"]], dtype=np.float64)
    summary = analyze_roots(roots, delta=args.delta, resamples=args.resamples, reps=args.reps)
    report = format_report(summary)
    with open(os.path.join(args.out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=1)
    with open(os.path.join(args.out_dir, "report.txt"), "w") as f:
        f.write(report + "\n")
    print(report)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("collect")
    c.add_argument("--checkpoint", required=True)
    c.add_argument("--manifest",
                   default=os.path.join(ROOT, "puffer", "config", "rewards", "r0_poss_half.json"))
    c.add_argument("--out-dir", required=True)
    c.add_argument("--games", type=int, default=40)
    c.add_argument("--per-class", type=int, default=2, help="roots per class per game")
    c.add_argument("--rollouts", type=int, default=128, help="rollouts per candidate")
    c.add_argument("--candidates", type=int, default=4)
    c.add_argument("--mask", action="append", default=None)
    c.add_argument("--seed0", type=int, default=29_000_000)
    c.add_argument("--budget-seconds", type=float, default=3600.0,
                   help="start no new game after this long")
    c.set_defaults(run=collect)
    a = sub.add_parser("analyze")
    a.add_argument("--out-dir", required=True)
    a.add_argument("--delta", type=float, default=DELTA)
    a.add_argument("--resamples", type=int, default=200)
    a.add_argument("--reps", type=int, default=2000)
    a.set_defaults(run=analyze)
    o = sub.add_parser("outcomes-collect")
    o.add_argument("--checkpoint", required=True)
    o.add_argument("--manifest",
                   default=os.path.join(ROOT, "puffer", "config", "rewards", "r0_poss_half.json"))
    o.add_argument("--first-run", required=True, help="the collect run whose roots are replayed")
    o.add_argument("--out-dir", required=True)
    o.add_argument("--rollouts", type=int, default=128, help="per candidate, flagged roots")
    o.add_argument("--control-rollouts", type=int, default=64)
    o.add_argument("--delta", type=float, default=DELTA)
    o.add_argument("--selection-seed", type=int, default=0)
    o.set_defaults(run=outcomes_collect)
    oa = sub.add_parser("outcomes-analyze")
    oa.add_argument("--out-dir", required=True)
    oa.add_argument("--reps", type=int, default=2000)
    oa.set_defaults(run=outcomes_analyze)
    args = parser.parse_args(argv)
    if args.command == "collect":
        args.mask = args.mask or ["m1"]
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
