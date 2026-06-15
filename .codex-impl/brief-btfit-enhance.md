# Brief: enhance tools/bt_fit.py per codex review of H1 (D97-A)

Repo: /Users/alexanderhuth/Code/bloodbowl-rl. Edit ONLY tools/bt_fit.py. No git state changes
(no commit). Match existing style in the file (it's already written, argparse-based,
pure-python-with-optional-numpy).

## Context
.codex-reviews/growth-plan.md reviewed tools/bt_fit.py (just landed) and flagged that "before
interpreting H1" we need, in addition to the existing decisive-only BT/Elo table:

1. **Confidence intervals** on the decisive win-rate per pairing (Wilson score interval,
   95%, no scipy — implement the closed-form Wilson formula directly) — print alongside the
   existing raw pair table.
2. **Score-based Elo** as a second table: instead of stripping draws (the current
   decisive-only BT fit), fit a SECOND Bradley-Terry-style model where each pairing's
   "win probability for A" input is simply `A_rate` directly (the raw score-rate, draws
   already split 50/50 into it per the env's scoring) — i.e. treat A_rate as an expected
   score in [0,1] and run the SAME Zermelo MM iteration but with `w_a = A_rate * total_games`
   (a float, not rounded to an int win count — the MM iteration in fit_bt already just sums
   floats via `total_wins`, so passing fractional "wins" works; you may need to relax the
   `int(round(...))` calls for THIS second fit's win/game tallies — keep the existing
   decisive-only path byte-for-byte unchanged, add a parallel path/function for the
   score-based fit reusing fit_bt with float win/game dicts built differently).
3. **Draw-rate matrix**: a simple square table (rows/cols = all present names, ordered by
   the EXISTING decisive-Elo ranking) showing `draw_rate` for each measured pairing (blank
   or "--" for unmeasured/diagonal cells).
4. **Residual table**: for ALL measured pairings (not just adjacent-in-ranking), print
   `name_i vs name_j: fit_p (decisive-Elo model) vs empirical_p vs n` — this generalizes the
   existing "adjacent fitted-vs-empirical" table to the full pairwise set, so non-transitivity
   (A>B>C>A cycles) is visible. Keep the existing adjacent-only table too (cheap, still useful
   as a quick summary) but add this full table as well, clearly labeled.

## Output structure (append after existing sections, in this order)
1. (existing) raw pair table
2. (existing) decisive-only BT/Elo ranked table — UNCHANGED
3. (existing) adjacent fitted-vs-empirical — UNCHANGED
4. NEW: full pairwise residual table (decisive-Elo model fit_p vs empirical_p vs n, for every
   measured pairing, ordered by |fit_p - empirical_p| descending so the worst-fitting/most
   non-transitive pairings surface first)
5. NEW: Wilson 95% CI per pairing — can be folded into the raw pair table as extra columns
   (`ci_lo`, `ci_hi` on `A_dec_p`) rather than a separate table, your choice — pick whichever
   keeps the raw pair table readable (if columns get too wide, make it a separate table)
6. NEW: score-based Elo ranked table (same column layout as the decisive-only table, same
   anchor/scale) — label clearly as "score-based (draws=0.5, no draw-stripping)" vs the
   existing "decisive-only (draws excluded)"
7. NEW: draw-rate matrix

## Wilson interval formula (for n trials, k successes, z=1.96 for 95%)
```
phat = k/n
denom = 1 + z^2/n
center = (phat + z^2/(2n)) / denom
half = (z * sqrt(phat*(1-phat)/n + z^2/(4*n*n))) / denom
ci = (center - half, center + half)
```
Use n=n_decisive, k=w_a (the already-computed decisive win count) from `decisive_counts`.

## Verify
- Run against the existing synthetic smoke-test CSV from the prior brief (recreate it inline:
  `printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\nA,B,0.650,0.350,0.200,100\nB,C,0.600,0.400,0.100,100\nA,C,0.700,0.300,0.300,100\n'`)
  and confirm all new sections print without crashing and look sane (e.g. Wilson CIs bracket
  the point estimates, score-based and decisive-only Elo orderings are both printed and are
  plausibly similar-but-not-identical for this 3-node example, draw-rate matrix shows the
  3 measured cells).
- `python3 tools/bt_fit.py --help` still works.

## Report back
- Diff summary (function names added/changed).
- Smoke-test output (the new sections only, can omit unchanged sections from your report).
- Any deviations.
