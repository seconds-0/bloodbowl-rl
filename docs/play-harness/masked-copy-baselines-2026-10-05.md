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
