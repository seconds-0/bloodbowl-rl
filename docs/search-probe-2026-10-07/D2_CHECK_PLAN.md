# Pilot rule D2 before the search gate: plan for a third batch (2026-10-07)

**Status: written and committed before the third batch is run. Not a ledger entry. The search gate's entry cites this file and its result.**

## Why

The design study's pilot rule D2 (`docs/plans/search-probe-design-2026-10-07.md`, section 8) asks, before any gate, for an upper confidence bound of 10% or less on the share of the seat's deviations that are false, judged by fresh independent rollouts, with a lower bound above zero on the mean gain, intervals clustered by game, on states held out from the choice of settings. D425 set the rule aside for the whole-game comparison and said it applies again before any gate.

## What exists already (seen)

Batches 1 and 2 of this morning's tail run (`FINDINGS.md`, section 3; seeds 29100000 to 29100066, 67 games, 2,010 screened roots). A tail root is an in-scope root (turn-level or first decision after the own declaration) where the seat's rule at 16 rollouts per candidate deviates: best alternative's paired mean gain above 0.10 and above two floored standard errors. Each tail root was then played with a0 and with the alternative on 128 fresh paired rollouts (rollout indices from 1000, never used in the screen). The tool stores each rollout's shaped return to the end of the searcher's own team turn (`depth1`), which is the quantity the seat's rule estimates.

Counted today from `tail1/outcomes.jsonl` and `tail2/outcomes.jsonl` (sha256 `42b87a9f...`, `c83262a3...`): 29 tail roots in 22 games, 0 with a fresh mean gain at or below zero. The smallest fresh gain is 0.059, 3.6 of its own standard errors above zero. Mean fresh gain 0.146 [0.116, 0.180] (games resampled). Exact one-sided 95% upper bound on the false share: 9.8% counting roots, 12.7% counting games. The 29 control-band roots (gain between 0.02 and 0.10, same two-standard-error test) also have 0 at or below zero. So the rule is met on the root count and not on the game count, on a sample that was not planned in a committed file.

## The third batch (not yet run)

- Same tool copy as batches 1 and 2 for collection (`search_probe_diag.tail2_launched.py`, sha256 `ea8a3a79...`; its collection code equals the committed tool's at `9202210`, the differences are in the report step), the play harness as of commit `9202210`, the same compiled library (`f870d015...`), chain 55 (`f6ba3b44...`) under m1 against itself on sampling offset 1, reward manifest `r0_poss_half`, gamma 0.999.
- Games 67 to 199 of seed block 29100000 (seeds 29100067 to 29100199, 133 games), as two processes over games 67 to 132 and 133 to 199. 15 roots per class per game, 16 screening rollouts, 4 candidates, 128 fresh paired rollouts to the end of the match for every tail root (cap 200, so none is left out) and for an equal number of control-band roots.
- No extension and no fourth batch.

## The count, fixed now

A tail root is **false** when the mean over its 128 fresh pairs of `depth1`(alternative) minus `depth1`(a0) is at or below zero.

D2 is **met** when all three hold:
1. Third batch alone, counting roots: the exact one-sided 95% upper bound on the false share is 10% or less.
2. All three batches, counting games (a game with any false tail root is a false game, out of the games that have a tail root): the same bound is 10% or less.
3. Third batch alone: the 95% lower bound of the mean fresh gain over tail roots, games resampled (2,000 replicates, generator seed 0), is above zero.

If D2 is not met the search gate is not registered on this rule setting, and a new ledger entry decides what follows.

## Limits, stated now

- The reference is 128 fresh paired rollouts, not the 256 the study named. Each root's own standard error is reported.
- Roots come from plain self-play trajectories of chain 55 + m1, one deviation at a time. A seat that has already deviated, or that plays chain 37 or chain 46, visits other states.
- The count is about the evaluator (shaped return plus the value head to the end of the own turn). It says nothing about wins; the gate is the judge of that.
- The tool also plays every selected root to the end of the match. Those win-score and touchdown numbers are reported as exploratory, as in `FINDINGS.md`, and enter nothing.
