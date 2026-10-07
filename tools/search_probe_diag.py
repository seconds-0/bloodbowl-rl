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

Nothing here is a registered experiment, and the returns are the shaped
training return, not wins.

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


def collect(args):
    import torch

    from play_harness import engine as E
    from play_harness import search as S
    from play_harness import tournament as T
    from play_harness.policy import MaskedPolicySeat, load_checkpoint, restrict_support

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "1")))
    masks = tuple(args.mask)
    policy, provenance = load_checkpoint(args.checkpoint)
    manifest = E.load_reward_manifest(args.manifest)
    os.makedirs(args.out_dir, exist_ok=True)
    roots_path = os.path.join(args.out_dir, "roots.jsonl")
    if os.path.exists(roots_path):
        raise SystemExit(f"{roots_path} exists; choose a fresh --out-dir")
    meta = {"checkpoint_sha256": provenance["checkpoint_sha256"], "masks": list(masks),
            "reward_manifest": manifest["name"], "reward_manifest_sha256": manifest["sha256"],
            "gamma": S.GAMMA, "max_rollout_steps": S.MAX_ROLLOUT_STEPS, "seed0": args.seed0,
            "games": args.games, "per_class": args.per_class, "rollouts": args.rollouts,
            "candidates": args.candidates, "opponent_seed_offset": 1, "temperature": 1.0}
    rollouts = [S.Rollouts(policy, seat, masks=masks) for seat in (0, 1)]
    totals = {"roots": 0, "engine_steps": 0, "rollout_seconds": 0.0, "games": 0,
              "in_scope": {c: 0 for c in CLASSES}, "single_action": {c: 0 for c in CLASSES},
              "stops": {s: 0 for s in S.STOPS}}
    started = time.time()
    with open(roots_path, "w") as sink:
        for game in range(args.games):
            if time.time() - started > args.budget_seconds:
                print(f"time budget reached before game {game}", flush=True)
                break
            engine_seed = args.seed0 + game
            a = game % 2                                    # seat A's side this game
            seeds = [T.sampling_seed(engine_seed, side) for side in (0, 1)]
            seeds[1 - a] = (seeds[1 - a] + T.SEED_OFFSET_STRIDE) % (1 << 62)
            seats = [MaskedPolicySeat(policy, side, seed=seeds[side], masks=masks)
                     for side in (0, 1)]
            for seat in seats:
                seat.reset_match()
            eng = E.Engine(engine_seed, rewards=manifest["rewards"])
            shadow = policy.initial_state(1)
            pick = random.Random(engine_seed)
            kept_roots = {c: [] for c in CLASSES}
            seen = {c: 0 for c in CLASSES}
            declared = None                                 # the kind A last declared
            step = 0
            while True:
                team = eng.decision_team
                was_declare = seats[a]._after_declare
                obs = [eng.obs(0), eng.obs(1)]
                supports = [eng.joint_support(0), eng.joint_support(1)]
                outs = [seats[s].step(obs[s], supports[s], s == team) for s in (0, 1)]
                # A's own network on the opponent's row, every step: the state a
                # search seat would hold for its opponent model.
                _, _, shadow = policy.forward_eval(
                    torch.from_numpy(obs[1 - a]).reshape(1, -1), shadow)
                if team == a:
                    support, _ = restrict_support(supports[a], masks, was_declare)
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
                            slot = len(kept_roots[cls]) if len(kept_roots[cls]) < args.per_class \
                                else pick.randrange(seen[cls])
                            if slot < args.per_class:
                                root = {
                                    "clone": eng.clone_for_search(0, S.SEARCH_DICE_STREAM),
                                    "own": seats[a].state.clone(), "opp": shadow.clone(),
                                    "logits": outs[a]["logits"].copy(), "support": support,
                                    "a0": tuple(int(v) for v in outs[a]["tuple"]), "step": step,
                                    "declared": declared if cls == "after_declare" else None,
                                    "flags": (was_declare, seats[1 - a]._after_declare)}
                                if slot < len(kept_roots[cls]):
                                    kept_roots[cls][slot]["clone"].close()
                                    kept_roots[cls][slot] = root
                                else:
                                    kept_roots[cls].append(root)
                if team == a and outs[a]["tuple"][0] == E.A["DECLARE"]:
                    declared = action_label(outs[a]["tuple"], E).split(":")[-1]
                rc = eng.step(*outs[team]["tuple"])
                step += 1
                if rc == E.STEP_TERMINAL:
                    break
                if rc != E.STEP_OK:
                    raise SystemExit(f"engine refused a step: rc={rc}")
            eng.close()
            for cls in CLASSES:
                for root in kept_roots[cls]:
                    tuples, probs = S.joint_probabilities(root["logits"], root["support"])
                    a0 = E.pack_tuple(*root["a0"])
                    order = [int(np.flatnonzero(tuples == a0)[0])]
                    order += [i for i in range(len(tuples)) if i != order[0]][:args.candidates - 1]
                    candidates = [E.unpack_tuple(tuples[i]) for i in order]
                    t0 = time.time()
                    batch = rollouts[a].evaluate(
                        root["clone"], root["own"], root["opp"], candidates, args.rollouts,
                        seeds[a], root["step"], after_declare=root["flags"])
                    totals["rollout_seconds"] += time.time() - t0
                    totals["engine_steps"] += batch.engine_steps
                    totals["roots"] += 1
                    for stop in S.STOPS:
                        totals["stops"][stop] += batch.count(stop)
                    sink.write(json.dumps({
                        "schema": SCHEMA, "game": game, "engine_seed": engine_seed, "seat": a,
                        "step": root["step"], "class": cls, "support": int(len(tuples)),
                        "tuples": [list(E.unpack_tuple(tuples[i])) for i in order],
                        "types": [action_label(c, E) for c in candidates],
                        "declared": root["declared"],
                        "probs": [float(probs[i]) for i in order],
                        "a0_rank": order[0] + 1,
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
    args = parser.parse_args(argv)
    if args.command == "collect":
        args.mask = args.mask or ["m1"]
    return args.run(args)


if __name__ == "__main__":
    sys.exit(main())
