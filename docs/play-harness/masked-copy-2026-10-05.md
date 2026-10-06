# Does chain 41 lose anything if it is not allowed to stop early? (2026-10-05)

**Status: a diagnostic, not a gate. No training. Nothing here changes a default.**

## 0. Design and thresholds, written before any arm was run

This section was committed before any arm was launched. The only games played
before it were unit tests on random policies.

### Question

The human-prior audit (`docs/human-prior-v1-2026-10-05.md` on branch
`probe/lockstep-depth-20261003`) found that chain 41 activates 3.0 players a
team turn against the humans' 7.2, ends 62% of its team turns by choice with
a player still to activate, ends 39% of its Block activations that have a
target without blocking, and ends 18% of its Move activations at once. Is any
of that load-bearing? If chain 41 is simply not allowed to do it, does it get
weaker?

### Arms

Chain 41 (`0000002999975936.bin`, sha256 `b1830e23...`) against a copy of
itself that selects under action masks. The copy is player A, plain chain 41
is player B, so every number is "masked minus plain". Sampling at temperature
1, native kernel, procgen rosters, both legs of every seed (the two coaches
swap sides and rosters), 3,200 games an arm (1,600 seeds), 32 games per
worker, 8 workers, one `s-8vcpu-16gb-amd` droplet an arm through
`tools/droplet_tournament.py`.

| arm | player A | masks on A | seed block |
|---|---|---|---|
| m1 | `chain41m1` | m1 | 23000000 |
| m2 | `chain41m2` | m2 | 23100000 |
| m3 | `chain41m3` | m3 | 23200000 |
| m123 | `chain41m123` | m1, m2, m3 | 23300000 |
| control | `chain41c` | none | 23400000 |

### The masks, exactly

A mask removes one action type from the masked seat's exact joint support
when its condition holds and at least one other legal action remains. The
policy's forward, recurrent state and sampling generator are untouched; the
sampler renormalizes the policy's own distribution over what is left, head by
head, as it does over any support. The plain side is never touched.

- **m1:** END_TURN is removed when an ACTIVATE is also legal (a player who
  has not activated this turn can still be activated).
- **m2:** END_ACTIVATION is removed at the masked seat's first decision after
  its own DECLARE.
- **m3:** END_ACTIVATION is removed while a BLOCK_TARGET is legal (a declared
  Block with a target, or a Blitz standing next to one).

A mask never removes the last legal action. When it would (m2 after a
declaration that leaves nothing to do but end the activation), it gives way
and the fallback is counted. Each game records, per mask: decisions where its
condition held, decisions where it removed a type, fallbacks, and the summed
probability the unmasked policy gave the removed type (the expected number of
decisions the mask changed).

### Thresholds

The statistic is the gates' own: decisive-Elo of A over B from
`tournament_stats.seed_cluster_bootstrap`, 2,000 replicates, 95% percentile
interval, engine seeds resampled as clusters.

- **Non-inferior:** the interval's lower end is above -20.
- **Better:** the whole interval is above zero.
- **Worse:** the whole interval is below zero.
- Anything else is **inconclusive**. "Worse" and "non-inferior" can both hold
  (an interval inside (-20, 0)); both are then reported.

### Control

Plain chain 41 against plain chain 41 on the same build. Because both legs of
a seed are then the same game with the names swapped, its decisive share is
0.5 by construction and says nothing about noise. What it checks:

1. every game's action trail on the modified harness equals the same game on
   the unmodified checkout at `b0099fb` (a local slice of 64 games, same
   machine, same batch size);
2. the two legs of every seed have identical action trails;
3. no mask and no mask statistics appear in any record.

### Reported with each arm (masked side against plain side, same games)

Activations per team turn; team turns ended by choice with a player left;
block targets chosen per game (a block is counted when its target is chosen)
and those inside a Blitz; turnovers per team turn; touchdowns per game;
possession (share of the team's turns that ended with it holding the ball,
the engine's `turns_completed_held`); activations ended at once; Block
activations ended with a target on offer; the mask counts above; and the raw
decisive share by the roster class the masked copy coached (bash, agile,
hybrid, stunty). Differences carry seed-cluster 95% intervals. The behaviour
tables are descriptive and gate nothing.

### What the reading can and cannot carry, fixed in advance

- The masked copy carries recurrent state as in play, but the actions it is
  forced into are ones it would not have chosen, so from the first forced
  action on it is off the distribution of states and histories it was
  trained on. A masked copy that is **worse** therefore has two readings
  that this test cannot separate: stopping early is good play, or the policy
  plays badly in the positions that not stopping leads to because it has
  never been there. A masked copy that is **non-inferior** is the stronger
  result: the habit costs nothing to remove even without any training to
  exploit the extra activations.
- It is chain 41 against itself. A habit that is free against chain 41 may
  not be free against another opponent.
- A hard mask is not a training-time change. Nothing here says what a policy
  trained under the same rule would do.
