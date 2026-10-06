# Masked copy, follow-up: does m1 transfer, and what does it do? (2026-10-05)

**Status: a diagnostic, not a gate. No training. Nothing here changes a default.**

## 0. Design and thresholds, written before any run was launched

This section was committed before any follow-up run was launched. The games
played before it were unit tests and local smoke slices of 16 to 64 games to
check that the commands run.

### Background

`docs/play-harness/masked-copy-2026-10-05.md`: chain 41 that may not end its
turn while a player can still be activated (mask m1) beat plain chain 41 by
+32.5 decisive-Elo [18.3, 47.1]. That was self-play. This follow-up asks
whether the gain holds against other opponents, adds the arms the first test
lacked, and counts what the extra activations do.

### Runs

Chain 41 is `0000002999975936.bin`, sha256 `b1830e23...`. Sampling at
temperature 1, native kernel, procgen rosters, both legs of every seed, 3,200
games a pair (1,600 seeds), 32 games per worker, one `s-8vcpu-16gb-amd`
droplet a run through `tools/droplet_tournament.py`. `tools/mask_followup_launch.py`
holds this table as code.

| run | seed block | pairs (A first) |
|---|---|---|
| t-offense | 23500000 | chain41m1 v offense bot; chain41 v offense bot |
| t-contact | 23600000 | chain41m1 v contact bot; chain41 v contact bot |
| t-chain27 | 23700000 | chain41m1 v chain 27; chain41 v chain 27 |
| t-chain36 | 23800000 | chain41m1 v chain 36; chain41 v chain 36 |
| t-chain47 | 23900000 | chain41m1 v chain 47; chain41 v chain 47 |
| m12 | 24000000 | chain41m12 (m1, m2) v chain41 |
| null | 24100000 | chain41b (plain, sampling offset 1) v chain41 |
| both-m1 | 24200000 | chain41m1b (m1, sampling offset 1) v chain41m1 (m1) |

`chain41m1` is chain 41 under m1; `chain41` is plain. The two pairs of a
transfer run share the run's seed block, so they play the same engine seeds
(same rosters, same dice stream) against the same opponent.

**Sampling offset.** Sampling seeds are keyed by side. With one checkpoint
under two names that makes the two legs of a seed the same game, which is why
the first test's control had a decisive share of exactly 0.5. A player with
`--sampling-offset K` has its sampling seed shifted by a fixed stride times
K, so the legs differ. Only the two runs above use it.

### Statistic and thresholds

Same statistic and the same three thresholds as the first test, on a 95%
seed-cluster percentile interval, 2,000 replicates:

- **Non-inferior:** the lower end is above -20.
- **Better:** the whole interval is above zero.
- **Worse:** the whole interval is below zero.

What the thresholds are applied to:

- **Transfer (five opponents):** the paired contrast, decisive-Elo of
  (chain41m1 v X) minus decisive-Elo of (chain41 v X). Engine seeds are
  resampled as clusters and a drawn seed brings both pairs and both legs,
  using `tournament_stats.cluster_counts` and `bootstrap_cluster_counts`, the
  functions behind every gate interval. Each pair's own decisive-Elo is
  reported beside it, with chain 41's touchdowns for and against and block
  targets chosen per game.
- **m12:** decisive-Elo of chain41m12 over plain chain 41.
- **null:** no verdict. Its decisive-Elo interval is reported as the spread
  two identical players show; it should cover zero.
- **both-m1:** no verdict. A behaviour table of the game when both sides play
  under the rule: activations per team turn, blocks, turnovers, touchdowns,
  draw rate, engine steps per game.

Named in advance: a decisive-Elo contrast is steep and noisy where a pair's
decisive share is near 0 or 1, which is possible against the bots and chain
27. The draw-inclusive score-rate contrast is printed beside it for that
reason; the verdict is still read from decisive-Elo.

### What an activation did

`play_harness/activations.py` files every activation under one class: ended
at once (empty), moved only, block, blitz, foul, pass or hand-off, ended by
the engine with no choice offered, other. For moved-only activations it
records the net displacement, the change in distance to the ball and the
change in distance from the team's own end zone. For players with a trait
that rolls on activation or declaration (Bone Head, Really Stupid, Animal
Savagery, Unchannelled Fury, Take Root, Bloodlust) it records how often they
were activated, how often they came out newly Distracted or Rooted, how
often the engine ended the activation, and how often the team turn ended in
a turnover with that activation as its last. The report gives these per team
turn for chain41m1 and for plain chain 41, pooled over the five transfer
runs, where both face the same opponents on the same seeds. The difference
between the two columns is what m1 added. The harness cannot tell a forced
activation from one the policy would have made anyway, and it sees a failed
Animal Savagery, Unchannelled Fury or Bloodlust roll only through its
consequences (an activation the engine ended, a turnover).

### The recommendation rule, fixed here

The question the transfer runs decide is whether to spend a training rung on
an env-side m1 rule.

- **Yes** if all five paired contrasts are non-inferior and at least three
  are better.
- **No** if any paired contrast is worse without being non-inferior.
- **Otherwise** mixed: said so, with which opponents went which way.

### Limits fixed in advance

- A hard mask at play time on a policy that was not trained under it. It
  says what the rule does to this policy, not what a policy trained under
  the rule would do.
- The masked copy is off its own distribution from its first forced action.
- Activation has side effects (it clears Distracted, can roll a negative
  trait, spends per-turn allowances, moves the Stalling check); m1 forces
  them.
- Chain 27 and chain 36 are chain 41's ancestors and chain 47 a sibling: the
  same lineage, not independent opponents. The bots are the only opponents
  outside it.
