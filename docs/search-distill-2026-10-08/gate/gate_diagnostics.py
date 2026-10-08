#!/usr/bin/env python3
"""Per-side behaviour diagnostics of a gate run, for the pairs the plan names.

  python gate_diagnostics.py PLAN.json RUN_DIR

Run only after acceptance. Descriptive: it applies no reading. For every pair
in plan["diagnostics"]["pairs"] and each side (A is the first name of the
pair) it reports, from the per-side counts in games.jsonl:

  empty activations per team turn   act_empty / team_turns (the first choice
                                    after the declaration was END_ACTIVATION)
  activations per team turn         activations / team_turns
  non-empty activations per team    (activations - act_empty) / team_turns
  turn
  blocks per team turn              block_targets / team_turns (a block is
                                    counted when its target is chosen)
  turnovers per team turn           turnovers / team_turns (the engine's count
                                    of team turns that ended with the turnover
                                    latch set)
  decisions per game                the side's own decisions; engine steps per
                                    game (both sides) is given once per pair
  touchdowns per game
  mean log-probability per decision sum of logprob over sum of decisions,
                                    under the distribution the seat sampled
                                    from (a masked seat's is renormalized over
                                    what the mask left); none for a bot

Rates are ratios of sums over the pair's games. A minus B carries a 95%
percentile interval from resampling engine seeds (a drawn seed brings both
legs), 2,000 replicates, generator seed 0. Writes RUN_DIR/diagnostics.json.

For every entry of plan["diagnostics"]["search_pairs"] ({"search": [S, X],
"control": [C, X]}) it also reports what the search seat did, summed over the
searched pair's games: searched decisions and deviations per game by class,
the deviation types, the mean and median predicted gain at a deviation, cap
rejections, rollouts cut off at the step limit, and the seconds per game of
the searched pair against the control pair (their ratio is the slowdown).
"""
import json
import os
import sys

import numpy as np

REPS, SEED = 2000, 0
# name -> (numerator, denominator); "games" means per game
METRICS = (
    ("empty_activations_per_team_turn", "act_empty", "team_turns"),
    ("activations_per_team_turn", "activations", "team_turns"),
    ("non_empty_activations_per_team_turn", "act_nonempty", "team_turns"),
    ("blocks_per_team_turn", "block_targets", "team_turns"),
    ("turnovers_per_team_turn", "turnovers", "team_turns"),
    ("decisions_per_game", "decisions", "games"),
    ("touchdowns_per_game", "td", "games"),
    ("mean_logprob_per_decision", "logprob", "policy_decisions"),
)
KEYS = sorted({k for _n, num, den in METRICS for k in (num, den)})


def side_counts(g, side):
    b = g["behaviour"][side]
    scripted = (g.get("modes") or [None, None])[side] == "scripted"
    return {"act_empty": b["act_empty"], "activations": b["activations"],
            "act_nonempty": b["activations"] - b["act_empty"],
            "block_targets": b["block_targets"], "turnovers": b["turnovers"],
            "team_turns": b["team_turns"], "decisions": g["decisions"][side],
            "td": g["score"][side], "games": 1,
            "logprob": 0.0 if scripted else g["logprob_sum"][side],
            "policy_decisions": 0 if scripted else g["decisions"][side]}


def pair_table(games):
    seeds = sorted({g["engine_seed"] for g in games})
    index = {s: i for i, s in enumerate(seeds)}
    col = {k: i for i, k in enumerate(KEYS)}
    sums = np.zeros((2, len(seeds), len(KEYS)))             # [A or B, seed, key]
    for g in games:
        a_side = 0 if g["leg"] == "A_home" else 1
        for who, side in ((0, a_side), (1, 1 - a_side)):
            counts = side_counts(g, side)
            for k in KEYS:
                sums[who, index[g["engine_seed"]], col[k]] += counts[k]
    rng = np.random.default_rng(SEED)
    n = len(seeds)
    boots = np.empty((REPS, 2, len(KEYS)))
    for r in range(REPS):
        mult = np.bincount(rng.integers(0, n, n), minlength=n).astype(float)
        boots[r] = np.tensordot(sums, mult, axes=([1], [0]))
    point = sums.sum(axis=1)

    def rate(total, num, den):
        with np.errstate(invalid="ignore", divide="ignore"):
            return total[..., col[num]] / total[..., col[den]]

    rows = {}
    for name, num, den in METRICS:
        a, b = (float(rate(point[w], num, den)) for w in (0, 1))
        diff = rate(boots[:, 0], num, den) - rate(boots[:, 1], num, den)
        diff = diff[np.isfinite(diff)]
        rows[name] = {
            "a": a if np.isfinite(a) else None, "b": b if np.isfinite(b) else None,
            "a_minus_b": a - b if np.isfinite(a - b) else None,
            "a_minus_b_ci95": [float(v) for v in np.percentile(diff, [2.5, 97.5])]
            if diff.size else None}
    return rows, len(seeds)


def search_table(games, search_pair, control_pair):
    name = search_pair[0]
    sg = [g for g in games if tuple(g["pair"]) == tuple(search_pair)]
    cg = [g for g in games if tuple(g["pair"]) == tuple(control_pair)]
    if not sg or not cg:
        raise SystemExit(f"no games for {search_pair} or {control_pair}")
    out = {"search": list(search_pair), "control": list(control_pair), "games": len(sg),
           "searched": {}, "deviations": {}, "deviation_types": {}, "rollouts": 0,
           "cutoff_rollouts": 0, "cap_rejected_decisions": 0, "cap_rejected_rollouts": 0,
           "search_seconds": 0.0}
    gains, no_deviation = [], 0
    for g in sg:
        side = (g["home"], g["away"]).index(name)
        st = g["search_stats"][side]
        for c, v in st["searched"].items():
            out["searched"][c] = out["searched"].get(c, 0) + v
        for c, v in st["deviations"].items():
            out["deviations"][c] = out["deviations"].get(c, 0) + v
        for k, v in st["deviation_types"].items():
            out["deviation_types"][k] = out["deviation_types"].get(k, 0) + v
        for k in ("rollouts", "cutoff_rollouts", "cap_rejected_decisions", "cap_rejected_rollouts"):
            out[k] += st[k]
        out["search_seconds"] += g["search_seconds"][side]
        gains += st["predicted_gains"]
        no_deviation += not sum(st["deviations"].values())
    n = len(sg)
    searched, deviations = sum(out["searched"].values()), sum(out["deviations"].values())
    out.update({
        "searched_per_game": searched / n, "deviations_per_game": deviations / n,
        "deviation_share_of_searched": deviations / searched if searched else None,
        "games_without_deviation": no_deviation,
        "mean_predicted_gain": float(np.mean(gains)) if gains else None,
        "median_predicted_gain": float(np.median(gains)) if gains else None,
        "seconds_per_game": sum(g["seconds"] for g in sg) / n,
        "control_seconds_per_game": sum(g["seconds"] for g in cg) / len(cg),
        "search_seconds_per_game": out["search_seconds"] / n})
    out["slowdown"] = out["seconds_per_game"] / out["control_seconds_per_game"]
    print(f"search seat {name} against {search_pair[1]}: {n} games, "
          f"{out['searched_per_game']:.1f} searched decisions and {out['deviations_per_game']:.2f} "
          f"deviations a game ({100 * deviations / max(searched, 1):.2f}% of searched), "
          f"{no_deviation} games without a deviation")
    for c in sorted(out["searched"]):
        print(f"  class {c}: {out['searched'][c] / n:.1f} searched, "
              f"{out['deviations'].get(c, 0) / n:.2f} deviations a game")
    if gains:
        print(f"  predicted gain at a deviation: mean {out['mean_predicted_gain']:.3f}, "
              f"median {out['median_predicted_gain']:.3f}")
    print(f"  cap-rejected decisions {out['cap_rejected_decisions']}, cutoff rollouts "
          f"{out['cutoff_rollouts']} of {out['rollouts']}")
    print(f"  seconds a game {out['seconds_per_game']:.1f} (search {out['search_seconds_per_game']:.1f}) "
          f"against {out['control_seconds_per_game']:.1f} for {control_pair[0]}: slowdown "
          f"{out['slowdown']:.1f}")
    for k, v in sorted(out["deviation_types"].items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {v:6d}  {k}")
    return out


def main():
    plan_path, run_dir = sys.argv[1], sys.argv[2]
    with open(plan_path) as f:
        plan = json.load(f)
    with open(os.path.join(run_dir, "games.jsonl")) as f:
        games = [json.loads(line) for line in f if line.strip()]
    out = {"what": __doc__.split("\n\n")[0], "reps": REPS, "generator_seed": SEED, "pairs": []}
    for a, b in plan["diagnostics"]["pairs"]:
        pg = [g for g in games if tuple(g["pair"]) == (a, b)]
        if not pg:
            raise SystemExit(f"no games for pair {a},{b}")
        rows, seeds = pair_table(pg)
        w = sum(g["result_a"] == "W" for g in pg)
        d = sum(g["result_a"] == "D" for g in pg)
        entry = {"a": a, "b": b, "games": len(pg), "seed_clusters": seeds,
                 "W": w, "D": d, "L": len(pg) - w - d,
                 "engine_steps_per_game": sum(g["c_steps"] for g in pg) / len(pg),
                 "metrics": rows}
        out["pairs"].append(entry)
        print(f"{a} (A) against {b} (B): {len(pg)} games, {entry['engine_steps_per_game']:.1f} "
              f"engine steps a game")
        for name, r in rows.items():
            fmt = lambda v: "n/a" if v is None else f"{v:.4f}"  # noqa: E731
            ci = r["a_minus_b_ci95"]
            print(f"  {name:34s} A {fmt(r['a'])}  B {fmt(r['b'])}  A-B {fmt(r['a_minus_b'])}"
                  + (f" [{ci[0]:.4f}, {ci[1]:.4f}]" if ci and r["a_minus_b"] is not None else ""))
    out["search"] = [search_table(games, e["search"], e["control"])
                     for e in plan["diagnostics"].get("search_pairs") or []]
    with open(os.path.join(run_dir, "diagnostics.json"), "w") as f:
        json.dump(out, f, indent=1)


if __name__ == "__main__":
    main()
