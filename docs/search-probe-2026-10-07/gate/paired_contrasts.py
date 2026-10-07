#!/usr/bin/env python3
"""Paired contrasts (ARM vs X) minus (CTL vs X) on shared engine seeds.

The procedure that produced chain37_contrast.json in the chain 49 gate directory:
engine-seed clusters are resampled jointly (a drawn seed brings every pair and both
legs) with play_harness.tournament_stats building blocks, 2,000 replicates,
generator seed 0, 95% percentile interval. Decisive-Elo is the registered statistic;
the draw-inclusive figure is written alongside as a diagnostic.

Run from the harness root with its venv:
  OMP_NUM_THREADS=1 .venv/bin/python paired_contrasts.py RUN_DIR ARM CTL X [X ...]
Writes RUN_DIR/<X>_contrast.json for each X and prints one line per X.
"""
import json
import os
import sys

sys.path.insert(0, os.getcwd())
from play_harness import tournament_stats as ts  # noqa: E402

REPS, SEED = 2000, 0


def main():
    run_dir, arm, ctl, opponents = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
    games = ts.load_games(run_dir)
    seeds, pairs, counts = ts.cluster_counts(games)
    boots = ts.bootstrap_cluster_counts(counts, REPS, SEED)
    point = counts.sum(axis=0)
    for opp in opponents:
        ka, kc = pairs.index((arm, opp)), pairs.index((ctl, opp))
        dec_a, score_a = ts._shares(point[ka])
        dec_c, score_c = ts._shares(point[kc])
        bdec_a, bscore_a = ts._shares(boots[:, ka])
        bdec_c, bscore_c = ts._shares(boots[:, kc])
        diff = ts.elo_from_share(bdec_a) - ts.elo_from_share(bdec_c)
        sdiff = ts.elo_from_share(bscore_a) - ts.elo_from_share(bscore_c)
        out = {
            "what": f"paired contrast against {opp}: ({arm} vs {opp}) minus ({ctl} vs {opp}), engine-seed "
                    f"clusters resampled jointly (tournament_stats building blocks, reps {REPS}, seed {SEED}); "
                    "95% percentile interval",
            "arm": arm, "control": ctl, "opponent": opp, "seed_clusters": len(seeds), "reps": REPS,
            "generator_seed": SEED,
            "arm_decisive_elo": float(ts.elo_from_share(dec_a)), "control_decisive_elo": float(ts.elo_from_share(dec_c)),
            "decisive_elo_diff": float(ts.elo_from_share(dec_a) - ts.elo_from_share(dec_c)),
            "decisive_elo_diff_ci95": ts._ci(diff),
            "draw_inclusive_elo_diff": float(ts.elo_from_share(score_a) - ts.elo_from_share(score_c)),
            "draw_inclusive_elo_diff_ci95": ts._ci(sdiff),
        }
        with open(os.path.join(run_dir, f"{opp}_contrast.json"), "w") as f:
            json.dump(out, f, indent=1)
        lo, hi = out["decisive_elo_diff_ci95"]
        print(f"{arm} minus {ctl} against {opp}: decisive-Elo {out['decisive_elo_diff']:+.1f} "
              f"[{lo:+.1f}, {hi:+.1f}] (arm {out['arm_decisive_elo']:+.1f}, control "
              f"{out['control_decisive_elo']:+.1f}; {len(seeds)} seed clusters)")


if __name__ == "__main__":
    main()
