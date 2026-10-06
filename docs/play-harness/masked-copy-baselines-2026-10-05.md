# m1 baselines for the training rung (2026-10-05)

**Status: a diagnostic, not a gate. No training. Nothing here changes a default.**

## 0. Design and thresholds, written before any run was launched

This section was committed before any run of this round was launched.

### Purpose

A rung is to be trained from chain 41 with the m1 rule on the learner's seat
(END_TURN is not legal while a player can still be activated). Its control is
chain 42, the same rung without the rule, and a policy trained under the rule
must be played under it. So the rung will be read against players that carry
the play-time mask without having been trained for it. This round measures
those baselines: what the play-time mask alone does to chain 42, to the chain
42 against chain 41 comparison, and to both against the gates' held-out
comparator, chain 37; and whether the gain seen on chain 41
(`masked-copy-2026-10-05.md`, `masked-copy-followup-2026-10-05.md`) shows on
other checkpoints.

### Runs

Sampling at temperature 1, native kernel, procgen rosters, both legs of every
seed, 3,200 games a pair (1,600 seeds), 32 games per worker, one
`s-8vcpu-16gb-amd` droplet a run. `tools/mask_baselines_launch.py` holds this
table as code. A name ending in `m1` plays under m1; `m1s` is the same with
its sampling seed shifted (`--sampling-offset 1`), used wherever a checkpoint
meets itself so the two sides never share a sampling stream.

| run | seed block | pairs (A first) | asked for as |
|---|---|---|---|
| c42-self | 24500000 | chain42m1s v chain42 | arm 1 |
| c42-c41 | 24600000 | chain42m1 v chain41m1; chain42 v chain41 | arms 2 and 3 |
| c37-42 | 24700000 | chain42m1 v chain37; chain42 v chain37 | arm 4 |
| c37-41 | 24700000 | chain41m1 v chain37; chain41 v chain37 | arm 4, plus one pair |
| c47-self | 24800000 | chain47m1s v chain47 | arm 5 |
| c48-self | 24900000 | chain48m1s v chain48 | arm 5 |

c37-42 and c37-41 share one seed block on two droplets, so all four pairs
against chain 37 are on the same seeds. **One pair was not asked for:** plain
chain 41 against chain 37. It completes the square, so that the mask's effect
against chain 37 can be read for chain 41 as well as chain 42 and the plain
chain 42 minus chain 41 difference against chain 37 can be read on the same
seeds as the masked one.

### Statistic and thresholds

As in the two earlier rounds: decisive-Elo from
`tournament_stats.seed_cluster_bootstrap`, 2,000 replicates, 95% seed-cluster
percentile interval; **non-inferior** if the lower end is above -20,
**better** if the whole interval is above zero, **worse** if it is below zero,
otherwise inconclusive.

- **c42-self, c47-self, c48-self:** the thresholds apply to the decisive-Elo
  of the masked copy over its plain checkpoint.
- **Paired contrasts** (the difference of two pairs' decisive-Elo, engine
  seeds resampled as clusters, a drawn seed bringing every pair and both legs
  that played it):
  1. chain 42 v chain 41, both under m1, minus both plain;
  2. chain 42 v chain 37, m1 minus plain;
  3. chain 41 v chain 37, m1 minus plain;
  4. against chain 37, chain 42 minus chain 41, both under m1;
  5. against chain 37, chain 42 minus chain 41, both plain.
  The three labels are printed for each. For contrasts 2 and 3 they mean what
  they meant before (the mask helps or hurts). For 1, 4 and 5 they only say
  which way the chain 42 against chain 41 comparison moves.
- Each pair's own decisive-Elo and interval is reported, with the behaviour
  rows for both sides: activations per team turn, activations ended at once
  per team turn, block targets chosen per game, turnovers per team turn,
  touchdowns for and against, draw rate, decisions per game.

### What would change the recommendation, fixed here

After the follow-up I recommended one paired rung under the rule, on
conditions. That recommendation is **weakened** if the gain does not
replicate: fewer than two of the three self-pairs (chain 42, 47, 48) better,
or any of them worse without being non-inferior. It is **complicated** if
contrast 1 is not non-inferior in either direction, that is, if its interval
lies wholly outside (-20, 20): the rule would then change the control's
standing against its parent by more than the gate's own resolution, and the
rung's gate must be read on masked baselines only.

### Limits fixed in advance

A play-time mask on policies not trained under it; all checkpoints are from
one lineage; a masked copy is off its own distribution from its first forced
action; activation has side effects that m1 forces.

## 1. Result in one paragraph

The free gain replicates on all three further checkpoints: the masked copy
beats its own plain checkpoint by +37.3 (chain 42), +33.5 (chain 47) and +43.4
(chain 48), every interval above zero, as chain 41's did (+32.5). The mask
does not change the chain 42 against chain 41 comparison beyond noise: +9.4
[-4.0, 23.5] with both under m1, +15.7 [2.1, 29.2] with both plain on the
same seeds, contrast -6.3 [-24.4, 12.4]. Against chain 37 the mask lifts both
(chain 42 by +19.7, chain 41 by +42.9). The consequence for the rung: about
35 Elo comes from the mask alone, so a rule-trained rung must be read against
masked baselines.

## 2. Each pair

| run | A | B | W / D / L | decisive share | decisive-Elo of A [95%] | verdict |
|---|---|---|---|---|---|---|
| c42-self | chain 42 + m1 | chain 42 | 1030 / 1339 / 831 | 0.553 | **+37.3 [23.0, 51.8]** | better |
| c47-self | chain 47 + m1 | chain 47 | 1031 / 1319 / 850 | 0.548 | **+33.5 [20.4, 47.0]** | better |
| c48-self | chain 48 + m1 | chain 48 | 1013 / 1398 / 789 | 0.562 | **+43.4 [29.1, 57.7]** | better |
| c42-c41 | chain 42 + m1 | chain 41 + m1 | 891 / 1465 / 844 | 0.514 | +9.4 [-4.0, 23.5] | |
| c42-c41 | chain 42 | chain 41 | 1004 / 1279 / 917 | 0.523 | +15.7 [2.1, 29.2] | |
| c37-42 | chain 42 + m1 | chain 37 | 1386 / 1205 / 609 | 0.695 | +142.9 [127.6, 157.8] | |
| c37-42 | chain 42 | chain 37 | 1384 / 1135 / 681 | 0.670 | +123.2 [108.6, 138.3] | |
| c37-41 | chain 41 + m1 | chain 37 | 1443 / 1166 / 591 | 0.709 | +155.1 [140.3, 170.1] | |
| c37-41 | chain 41 | chain 37 | 1339 / 1159 / 702 | 0.656 | +112.2 [97.7, 127.2] | |

The plain chain 42 against chain 41 pair (+15.7 [2.1, 29.2]) agrees with the
registered gate's +12.5 [-1.1, 26.1] on another seed block.

## 3. Paired contrasts

| contrast | decisive-Elo [95%] | by the thresholds |
|---|---|---|
| 1. chain 42 v chain 41: both under m1 minus both plain | -6.3 [-24.4, 12.4] | inconclusive |
| 2. chain 42 v chain 37: m1 minus plain | +19.7 [0.6, 37.8] | better |
| 3. chain 41 v chain 37: m1 minus plain | +42.9 [23.2, 61.6] | better |
| 4. v chain 37: chain 42 minus chain 41, both under m1 | -12.2 [-32.5, 8.0] | inconclusive |
| 5. v chain 37: chain 42 minus chain 41, both plain | +11.0 [-9.7, 30.7] | non-inferior |

Contrast 1 covers zero and is not wholly outside (-20, 20), so by the rule in
section 0 it does not complicate the rung. Its lower end is below -20, so it
is labelled inconclusive: the data do not rule out the rule costing chain 42
up to 24 Elo of its standing against chain 41, nor adding 12.

Post hoc, not registered: the mask's gain against chain 37 is +19.7 for chain
42 and +42.9 for chain 41; their difference on the shared seeds is -23.2
[-49.9, 2.4]. That leans toward the mask helping chain 41 more than chain 42
and does not establish it.

## 4. Behaviour (A / B in the same games)

| A v B | activations per team turn | ended at once per team turn | blocks per game | turnovers per team turn | TD: A / B | draw rate | decisions per game |
|---|---|---|---|---|---|---|---|
| chain 42 + m1 v chain 42 | 6.71 / 3.18 | 2.81 / 0.68 | 10.7 / 8.3 | 0.419 / 0.344 | 0.802 / 0.711 | 0.418 | 980 |
| chain 47 + m1 v chain 47 | 6.67 / 3.11 | 2.65 / 0.68 | 9.6 / 7.3 | 0.424 / 0.348 | 0.773 / 0.692 | 0.412 | 967 |
| chain 48 + m1 v chain 48 | 6.64 / 3.08 | 2.74 / 0.64 | 10.7 / 8.1 | 0.427 / 0.348 | 0.758 / 0.655 | 0.437 | 955 |
| chain 42 + m1 v chain 41 + m1 | 6.68 / 6.85 | 2.74 / 2.89 | 11.0 / 10.4 | 0.429 / 0.414 | 0.655 / 0.641 | 0.458 | 1,204 |
| chain 42 v chain 41 | 3.07 / 3.02 | 0.68 / 0.65 | 8.3 / 7.2 | 0.336 / 0.315 | 0.802 / 0.751 | 0.400 | 717 |
| chain 42 + m1 v chain 37 | 6.59 / 3.12 | 2.74 / 0.75 | 11.0 / 7.3 | 0.416 / 0.343 | 1.121 / 0.718 | 0.377 | 963 |
| chain 42 v chain 37 | 2.93 / 2.99 | 0.57 / 0.68 | 8.3 / 7.3 | 0.334 / 0.342 | 1.188 / 0.813 | 0.355 | 718 |
| chain 41 + m1 v chain 37 | 6.71 / 3.08 | 2.89 / 0.75 | 10.6 / 7.3 | 0.412 / 0.350 | 1.087 / 0.668 | 0.364 | 951 |
| chain 41 v chain 37 | 2.84 / 2.98 | 0.57 / 0.70 | 7.5 / 7.6 | 0.312 / 0.348 | 1.145 / 0.792 | 0.362 | 697 |

"Blocks" are block targets chosen. Under m1 every checkpoint looks the same:
6.6 to 6.9 activations a team turn, 2.7 to 2.9 of them ended at once, 0.41
to 0.43 turnovers a team turn. With both sides under the rule a game is
1,204 decisions against 717 and scoring falls from 0.78 a side to 0.65. The
fallback never fired (m1 has none); m1 removed END_TURN at about 106
decisions a game on the masked side.

## 5. Does this change the view on training under the rule?

By the rule fixed in section 0 the recommendation is neither weakened (three
of three self-pairs are better) nor complicated (contrast 1 is not wholly
outside (-20, 20)). The gain is general across the four checkpoints tried,
which strengthens the case for the rung. It adds one condition and sharpens
one risk.

- **The rung must be judged against masked baselines.** A rule-trained rung
  played under the rule would beat plain chain 42 by about 37 Elo and plain
  chain 41 by about 32 without having learned anything. The comparisons that
  measure training are against chain 42 + m1 (the control, played under the
  rule) and chain 41 + m1 (its parent, played under the rule). Against chain
  37 the levels to beat are +143 [128, 158] (chain 42 + m1) and +155 [140,
  170] (chain 41 + m1), not the plain +123 and +112.
- **Under the rule the control has no visible edge over its parent.** Chain
  42 + m1 against chain 41 + m1 is +9.4 [-4.0, 23.5], and against chain 37
  the parent under the rule is level with or ahead of the control under the
  rule (155 against 143; contrast 4 is -12.2 [-32.5, 8.0]). A rung trained
  under the rule therefore starts from a parent that, with the mask, is
  already as good as the control with the mask. To read Positive it has to
  add something on top of what the mask gives for nothing.

## 6. Cost, commits, review

- Six `s-8vcpu-16gb-amd` droplets in sfo3 at the same time, 28,800 games,
  each run verified by sha256, against its manifest and with zero integrity
  counters. Lifetimes 12.9 to 26.5 minutes, **$0.30**
  (`docs/play-harness/masked-copy-baselines-2026-10-05/droplet_runs.json`);
  $0.85 for the three rounds together. The leak check after the last
  teardown shows no tagged droplet, no `bb-harness-*` key and no live local
  state; the account's five other droplets were not touched.
- All runs at commit `a6d5f3f`. No harness code changed for this round; only
  a launcher and a report were added.
