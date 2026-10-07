# Search probe: offline findings (2026-10-07)

**Status: three offline measurements on the Mac, no tournament, no spend, nothing registered in DECISIONS.md. All three are exploratory: no plan was committed before any of them. They decide what gets measured next, not what is adopted. Codex reviewed this file (`.codex-reviews/search-probe-findings-review.md`); its corrections are applied.** Design: `docs/plans/search-probe-design-2026-10-07.md` (section 8 holds). Code: branch `feat/search-probe-20261007` (head `9202210`), `play_harness/search.py` and `tools/search_probe_diag.py`. Reports beside this file: `headroom_report.txt`, `outcomes_report.txt`, `selection.json`, `tail_report.txt`, `tail_selection.json`. The measurements were run by an agent on the session model; the operator checked the tables below against the report files. Raw records are kept in `/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/search-diag-20261007/`. Numbers marked (agent) come from the agent's report of those raw records and are not in the report files.

All three use chain 55 (`f6ba3b44...`) with the m1 mask playing itself (second seat on sampling offset 1), T=1, kick-off starts, the real session under the `r0_poss_half` manifest, gamma 0.999. Rollouts use the same network for both sides under m1, clones reseeded, common random numbers across the candidates at a root. Candidates are the action plain play sampled (a0) and up to three other legal joint actions with the highest policy probability. "Predicted gain" is the paired mean difference in shaped n-step return to the end of the searcher's own team turn, alternative minus a0. Intervals are 95% bootstraps over games (a game's roots are resampled together); every estimate is a mean over roots, not an equal-weight mean over games.

## 1. Headroom under the evaluator (240 roots, 40 games, seeds 29000000 to 29000039)

128 rollouts per candidate. The best alternative is chosen on rollouts 0 to 63 and judged on rollouts 64 to 127. In this section and the next a root is "flagged" when its selection-half gain exceeds 0.02; that is not the two-standard-error rule a seat would use, which the next bullet list simulates separately.

| Class | Roots | Share with judged gain above 0.02 and two standard errors | Mean judged gain per searched decision of "deviate if the chosen half says so" |
|---|---|---|---|
| turn (which player to activate) | 80 | 10.0% [3.8, 16.2] | 0.0106 [0.0018, 0.0231] |
| declare (which action) | 80 | 5.0% [1.2, 10.0] | 0.0025 [0.0007, 0.0047] |
| first choice after the declaration | 80 | 16.2% [8.8, 25.0] | 0.0090 [0.0038, 0.0152] |
| all | 240 | 10.4% [7.1, 14.2] | 0.0074 [0.0033, 0.0125] |

- A touchdown is 0.4 in these units. The judging half's standard error averages 0.003.
- The deviation rule simulated at 8 rollouts per candidate deviates at 8.5% of searched decisions with 2.6% of those deviations at or below zero on the judging half (upper bound 4.6%). A standard-error floor from the pooled variance changes little.
- a0 was the policy's most probable action at 237 of 240 roots and at all 28 roots where the rule deviates. 25 of the 28 chosen alternatives had policy probability below 0.001 (agent). Lower temperature would make these choices rarer, not more likely.
- The three largest gains are 46% of the total. Where a0 ends an activation with nothing done (36 roots), the best alternative's judged gain averages about zero (agent).

## 2. Do those deviations change the result? (28 flagged roots and 28 controls, same games)

Each root played to the end of the match with a0 and with the alternative, 128 pairs for flagged roots and 64 for controls, fresh rollout indices. Flagged roots are the 28 where the rule deviates on the selection half; controls were drawn with a fixed seed from the other roots. The selection was written to a file before any outcome rollout.

| Set | Roots | Win score (W=1, D=0.5) | Touchdown difference |
|---|---|---|---|
| flagged, all | 28 | +0.0015 [-0.011, +0.017] | +0.012 [-0.025, +0.053] |
| flagged, turn | 10 | +0.002 [-0.012, +0.012] | +0.005 [-0.045, +0.061] |
| flagged, declare | 6 | -0.026 [-0.042, -0.010] | -0.049 [-0.081, -0.018] |
| flagged, after the declaration | 12 | +0.015 [-0.005, +0.047] | +0.048 [-0.022, +0.147] |
| control, all | 28 | -0.0006 [-0.009, +0.008] | -0.001 [-0.035, +0.027] |

- The predicted gain replicates on these fresh rollouts (0.064 [0.034, 0.100] against 0.063 in run 1), so it is not selection noise. It is zero touchdowns inside the turn, 0.023 other collected reward and 0.041 value term.
- No gain in match result is established for the flagged set. The interval is about plus or minus 0.014 win score per deviation, which cannot rule out a smaller effect.
- The declare class reads negative on both measures in this sample of 6 roots, which is a warning about that class and not a verdict on it. There the predicted gain is a value term of +0.046 against collected reward of -0.016, and it is gone at the next own turn.
- Of the four roots with predicted gain above 0.13, three show touchdown-difference gains (+0.21, +0.23, +0.44); two of those were in matches already won.

## 3. The tail on fresh games (2,010 roots, 67 games, seeds 29100000 to 29100066)

Set out in the operator's instruction to the agent before the run (about 04:25 PDT, in the session transcript; not in a committed or timestamped file, so the order cannot be verified from artifacts): scope is turn-level and after-declaration roots only; screen at 16 rollouts per candidate; tail = predicted gain above 0.10 and above two floored standard errors; control band = predicted gain in (0.02, 0.10] passing the same test, an equal number drawn with a fixed seed; both played to the end of the match at 128 pairs; "live" = a0's own win score between 0.1 and 0.9. The decision rule in the same instruction: build the seat with delta 0.10 and this scope if the tail's touchdown-difference interval is entirely above zero and the tail occurs at one in a hundred searched decisions or more; otherwise stop rollout search on this evaluator.

Run as two batches (1,350 roots, then 660 more to reach the requested size). By the agent's report the second batch was decided on the tail count alone, before any outcome was looked at, with the combined result declared primary then. The tool plays a batch's outcomes before it returns, so the files cannot show that. Controls were drawn within each batch.

| Set | Roots | Games | Touchdown difference | Win score |
|---|---|---|---|---|
| tail | 29 | 22 | +0.065 [+0.006, +0.122] | +0.028 [+0.006, +0.050] |
| tail, live matches | 25 | 20 | +0.064 [+0.011, +0.120] | +0.032 [+0.008, +0.057] |
| tail, turn | 16 | 16 | +0.047 [-0.021, +0.118] | +0.021 [-0.009, +0.052] |
| tail, after the declaration | 13 | 12 | +0.086 [-0.004, +0.171] | +0.036 [+0.001, +0.067] |
| control band | 29 | 25 | +0.015 [-0.016, +0.043] | +0.011 [-0.001, +0.023] |

- Frequency: the tail is 1.46% [0.92, 2.06] of searched decisions, 3.13 [1.98, 4.45] per game per seat. The band is about six times as frequent.
- The screen's predicted gain for the tail is 0.159 at 16 rollouts and 0.146 [0.116, 0.180] on fresh rollouts.
- By the instruction's rule this is the build branch: the tail's touchdown-difference interval is above zero and the frequency's point estimate clears the bar (its lower bound, 0.92%, does not). Because the rule, the threshold and the sample extension are not verifiably fixed in advance, and several measures and splits are reported, these are nominal exploratory intervals.
- It is narrow. The lower bound is +0.006. Leaving out any one game moves the tail mean between +0.050 and +0.079; without the three largest roots it is +0.034 (agent, both). Neither class clears zero on touchdown difference alone. Batch 1 alone: +0.077 [+0.003, +0.146] touchdown difference, +0.019 [-0.009, +0.046] win score (agent). The live split uses a0's win score from the same outcome rollouts, so it is descriptive.
- An illustrative extrapolation only: 3.13 tail deviations per game times +0.028 is +0.087 win score. It is not a bound in either direction. Repeated deviations change the later states and can add to or cancel each other, and the product mixes a frequency per searched decision with an unweighted mean over sampled roots.
- The 0.10 threshold was chosen after seeing run 2 (four roots above 0.13). Run 3 is on fresh games, so it is a confirmation of that choice, with one threshold and one scope tested.

## What this supports, and what it does not

- Supported: selected large-gain deviations at turn-level and after-declaration decisions showed positive average single-intervention outcomes in this self-play sample (29 roots, 22 games). Whole-game play and transfer to other opponents remain untested.
- Not supported: the design's original setting (delta 0.02, all three classes). No gain is established for it, and the declare class reads negative.
- Not measured: a seat that searches every decision in a whole game (each root here is one deviation followed by plain play); any opponent other than chain 55 itself, where the opponent model inside the rollouts is no longer exact; cost on a droplet.
- Every root comes from one checkpoint and one mask setting.

## Next step

The review's recommendation is taken: before any seat or tournament wiring, a whole-game offline comparison that uses the existing rollout core in a plain decision loop, with one seat searching at every in-scope decision of every game. That measures the interaction of repeated deviations and the real slowdown directly. It is registered in DECISIONS.md, with its plan committed and pushed before any game is played: delta 0.10 as the primary setting, the rollout count, floor, candidates, scope and cutoff, the checkpoint, manifest and runtime, fresh paired seeds in both orientations, a fixed number of completed games, one primary whole-game measure with a minimum worthwhile gain, touchdown difference as secondary, a lower-delta arm marked exploratory, a search-disabled identity check, zero-integrity acceptance and a cost ceiling. Milestone M3 (the seat inside the tournament harness) is built only if that comparison reads in favour.
