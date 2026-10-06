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

## 1. Result in one paragraph

Not being allowed to end the turn early makes chain 41 **stronger**: m1 is
+32.5 decisive-Elo [18.3, 47.1] over plain chain 41. The other two habits
are a different matter: forbidding an activation that ends at once (m2,
-25.4 [-38.3, -12.2]) or a declared block that is not thrown (m3, -24.5
[-36.7, -11.8]) makes it **weaker**. All three together are **non-inferior**
(+14.0 [-0.4, 28.2]) with 2.4 times the blocks. So, against itself, the
short turn is not load-bearing; the unthrown blocks are, or at least the
policy cannot throw them well when made to.

## 2. Control

- **Inert when no mask is set.** A 64-game slice of the control arm (seed
  block 23400000, 2 workers, 32 games per worker) played on the unmodified
  checkout at `b0099fb` and on this branch on the same machine: 64 of 64
  games have the same action trail, final digest, score, step count and
  log-probability sum. The only difference in a record is the three new keys
  (`behaviour`, `masks`, `mask_stats`).
- **The control arm** (3,200 games on a droplet): W/D/L 948/1304/948, decisive
  share 0.500 by construction; all 1,600 seeds have identical action trails
  in their two legs; no record carries a mask. It measures no noise (see
  section 7).
- Plain chain 41 against itself, per side: 2.98 activations a team turn,
  0.61 of team turns ended by choice with a player left, 7.4 block targets a
  game, 0.32 turnovers a team turn, 0.75 touchdowns a game, possession 0.41.
  These match the audit's self-play numbers.

## 3. The four arms

Strength, masked copy (A) against plain chain 41 (B), 3,200 games and 1,600
seeds each:

| arm | W / D / L | decisive share | decisive-Elo [95%] | verdict by section 0 |
|---|---|---|---|---|
| m1: no early END_TURN | 949 / 1464 / 787 | 0.547 [0.526, 0.567] | **+32.5 [18.3, 47.1]** | better (and non-inferior) |
| m2: no activation ended at once | 890 / 1280 / 1030 | 0.464 [0.445, 0.482] | **-25.4 [-38.3, -12.2]** | worse |
| m3: no unthrown block | 899 / 1266 / 1035 | 0.465 [0.447, 0.483] | **-24.5 [-36.7, -11.8]** | worse |
| m1 + m2 + m3 | 914 / 1443 / 843 | 0.520 [0.499, 0.541] | **+14.0 [-0.4, 28.2]** | non-inferior |

Behaviour in the same games, masked side / plain side. Every masked-minus-plain
difference shown has a seed-cluster interval that excludes zero unless marked
"ns" (`docs/play-harness/masked-copy-2026-10-05/tables.md` has the intervals).
The last row is one number per arm: both sides share the game.

| | m1 | m2 | m3 | m1 + m2 + m3 |
|---|---|---|---|---|
| activations per team turn | 6.92 / 3.14 | 2.75 / 2.91 | 2.78 / 2.92 | 5.88 / 3.09 |
| team turns ended by choice with a player left | 0.000 / 0.609 | 0.544 / 0.618 | 0.559 / 0.621 | 0.000 / 0.623 |
| block targets chosen per game | 10.3 / 7.6 | 10.1 / 6.8 | 10.0 / 6.8 | 15.5 / 6.5 |
| of which inside a Blitz | 1.20 / 1.24 | 1.34 / 1.25 | 1.53 / 1.25 | 1.64 / 1.32 |
| turnovers per team turn | 0.413 / 0.327 | 0.393 / 0.309 | 0.378 / 0.307 | 0.570 / 0.310 |
| touchdowns per game | 0.679 / 0.608 | 0.740 / 0.808 | 0.752 / 0.817 | 0.703 / 0.669 |
| possession | 0.404 / 0.402 (ns) | 0.403 / 0.416 | 0.415 / 0.414 (ns) | 0.396 / 0.397 (ns) |
| activations ended at once, per activation | 0.436 / 0.223 | 0.001 / 0.205 | 0.137 / 0.203 | 0.002 / 0.212 |
| activations ended with a block target on offer, per game | 8.9 / 3.8 | 0.5 / 3.8 | 0.0 / 3.7 | 0.0 / 3.4 |
| engine steps per game (both sides) | 961 | 702 | 693 | 978 |

"Block targets chosen" is this report's count of resolved blocks: a block is
counted when its target is chosen. The row "ended with a block target on
offer" counts Block and Blitz activations together; section 0 promised the
Block ones alone and the counter does not split them (found in review, after
the arms had run).

The masks at work, per game on the masked side: decisions where the mask's
condition held, where it removed a type, where it gave way, and the summed
probability the unmasked policy gave the removed type at those decisions (on
the masked copy's own trajectory, not a count of differences from a plain
game).

| arm | mask | held | removed a type | gave way | summed removed-type probability |
|---|---|---|---|---|---|
| m1 | m1 | 109.5 | 109.5 | 0.00 | 65.3 |
| m2 | m2 | 42.7 | 42.6 | 0.05 | 7.7 |
| m3 | m3 | 10.5 | 10.5 | 0.00 | 3.0 |
| all | m1 | 93.0 | 93.0 | 0.00 | 53.7 |
| all | m2 | 91.8 | 91.6 | 0.17 | 32.8 |
| all | m3 | 16.1 | 2.4 | 0.00 | 0.7 |

The fallback (never mask the last legal action) fired only for m2, 0.05
times a game alone and 0.17 with all three. With all three, a removal both
m2 and m3 ask for is credited to m2.

Raw decisive share by the roster class the masked copy coached. This mixes
the mask's effect with roster strength, so the control row is the baseline
to read against (the same policy on both sides still wins 0.66 of decisive
games with an agile roster and 0.39 with a bash one). Different arms use
different seeds.

| roster class | control | m1 | m2 | m3 | m1 + m2 + m3 |
|---|---|---|---|---|---|
| bash (about 1,600 games) | 0.386 | 0.434 | 0.379 | 0.377 | 0.434 |
| agile (about 540) | 0.655 | 0.700 | 0.615 | 0.590 | 0.638 |
| hybrid (about 520) | 0.536 | 0.584 | 0.490 | 0.506 | 0.530 |
| stunty (about 530) | 0.618 | 0.626 | 0.513 | 0.529 | 0.599 |

Each cell's interval is about plus or minus 0.03 (bash) to 0.05.

## 4. Verdict per mask

- **m1, no early END_TURN: better.** Chain 41 loses nothing by not stopping
  early; it gains about 32 Elo against itself. It concedes fewer touchdowns
  (0.61 against the 0.75 chain 41 concedes to itself in the control arm) and
  scores slightly fewer (0.68 against 0.75), with 0.09 more turnovers a team
  turn. m1 does not force a move or a block: 44% of the masked copy's
  activations end at once. That is close to not using the player, but it is
  not the same thing as not activating it: an activation clears Distracted,
  a declaration can trigger a negative-trait roll and spends the turn's
  Blitz, Pass, Hand-off or Foul allowance, and Stalling is timed by the
  carrier's activation. So m1 changes more than the decision to stop. With
  that said: made to decide player by player, chain 41 uses about two in
  five of the extra activations (of 3.8 more a team turn, 2.3 end at once)
  and is stronger against itself. The raw share is higher than the
  control's in the bash, agile and hybrid rows and level in the stunty row.
- **m2, no activation ended at once: worse.** About 25 Elo. Blocks go from
  6.8 to 10.1 a game and turnovers from 0.31 to 0.39 a team turn; it scores
  less and concedes more.
- **m3, no unthrown block: worse.** About 25 Elo. The two masks overlap: after
  a Block declaration with a target, the first decision is the block, so m2
  forces those blocks too (10.1 and 10.0 block targets a game). They are not
  the same mask: m3 also acts later inside a Blitz (1.53 Blitz blocks a game
  against m2's 1.34) and m2 still lets 0.49 activations a game end with a
  target on offer. The results are consistent with forced blocks carrying
  most of m2's cost, and do not show it: no arm isolates the forced first
  step of a Move.
- **All three: non-inferior**, short of "better" by 0.4 Elo at the lower
  end. 15.5 blocks a game against 6.5, 5.9 activations a team turn against
  3.1, and 0.57 turnovers a team turn against 0.31.
- The roster split, as point estimates only: under m2 and m3 the bash row is
  0.38 against the control's 0.39, and the agile, hybrid and stunty rows are
  0.03 to 0.10 below the control's. No interval was computed for those
  contrasts, the arms use different seeds (so different rosters, skills and
  matchups), and a decisive share depends on a draw rate the masks change.
  A pattern to test, not a finding.

## 5. Reading, with chain 41's reward ledger

The ledger figures here were supplied with the task and are not in this
branch's artifacts: mean emitted reward per game on the learner's side over
25,611 training games of chain 41. Distance to the end zone +1.24, touchdown
+0.29, win/loss +0.23, ball gain +0.16, distance to the ball +0.13; block
sequence -0.18, rush -0.14, block turnover -0.13, block exposure -0.10. These
are contributions, not coefficients. Nothing dense pays for using the
players who are not moving the ball.

- **m1: a hypothesis the ledger suggests and this test is consistent with.**
  Under m1 the copy chooses 2.7 more block targets a game and has 0.09 more
  turnovers a team turn, and it wins more. The dense terms that exist charge
  blocks and rushes, and none pays for an extra activation, so the reward
  gives chain 41 little reason to continue a turn and some reason to stop.
  Whether the extra m1 actions actually have negative net dense reward was
  not measured (it needs the reward ledger run on the m1 games, or a reward
  ablation), and total turnovers are not block turnovers. So: the short turn
  may be a product of the reward and not of strength. Not shown.
- **m2 and m3: the charge on blocks and the match result point the same
  way** for the blocks chain 41 declares and does not throw. Two readings,
  which this test cannot separate (section 0): they are bad blocks and it
  is right to decline them, or it blocks poorly because blocks were charged
  throughout training (target, assists, die). Nothing here decides between
  them.
- **One direct interaction.** Declaring Block and then ending the activation
  costs nothing under those terms and is legal, so it is a cheap way to
  pass over a player who stands next to an opponent. Under m1 the copy does
  much more of it: Block declarations go from 0.63 to 1.13 a team turn and
  activations ended with a target on offer from 3.8 to 8.9 a game.
- **What a forced action does to the reading.** A forced action is one the
  policy gave low probability, taken with recurrent state that never saw
  such a history in training. That can make a masked copy play worse than a
  policy trained under the rule would, or differently in ways this test
  cannot sign. It is a reason not to read m2 and m3 as "blocking is bad",
  and not a reason to discount m1.

## 6. What a training-time version would look like

Only m1 survives as a candidate. m2 and m3 do not, as hard rules.

1. **An env-side legality rule: END_TURN is legal only when no ACTIVATE is.**
   It is exactly what was tested and needs no coefficient. It is a
   restriction the rulebook does not make: a coach may stop, and an empty
   activation is not a free substitute (it clears Distracted, can roll a
   negative trait, spends per-turn action allowances and moves the Stalling
   check). Behind a flag, default off, one paired rung against a control.
   What could go wrong: those activation side effects become forced, which
   matters most for rosters with negative-trait players; a policy trained
   under the rule can learn to make every extra activation an empty one,
   since nothing in the dense reward pays for using it and blocks and
   rushes are charged, and then the gain measured here does not appear;
   games get about 38% longer in engine steps (961 against 697), so
   throughput per game falls and a per-step discount reaches less far into a
   turn; frozen opponents in the pool were not trained under the rule, so
   the flag must apply per seat or to the learner only; and it changes the
   action contract, so checkpoints trained with and without it are not
   interchangeable at evaluation without saying which rule is on.
2. **A small penalty for ending the turn with a player left.** Not
   recommended. It needs a coefficient, it is a style fine of the kind the
   reward contract rejects, and the cheapest way to avoid it is empty
   activations.
3. **A human-prior term scoped to the turn-level decision** (ACTIVATE or
   END_TURN, type head only). Softer than the rule and it can be decayed,
   but it costs a second forward at those decisions and brings the
   calibration questions of the audit. This test says the hard rule at play
   time improved strength against plain chain 41 on sampled procgen rosters;
   it says nothing about a penalty's dynamics or about other opponents.

For m2 and m3 the order of work is the other way round: before any rule or
prior asks for more blocks, find out whether chain 41 blocks badly because
blocks were charged. Cheap checks: the same masks against the scripted bots
and an older chain, a roster-standardized read with intervals, and the
reward ledger run on masked games.

The exit test for any of this is the normal gate with no loss, with the
style panel next to it. A result here against a copy of itself is not a gate
result.

## 7. Cost, commits, review

- **Where it ran.** Five `s-8vcpu-16gb-amd` droplets in sfo3, one an arm, at
  the same time, each created and destroyed by `tools/droplet_tournament.py`;
  every run verified its files by sha256 and its games against the manifest
  with zero integrity counters. Lifetimes 10.1 to 12.6 minutes; **total cost
  $0.15** (`docs/play-harness/masked-copy-2026-10-05/droplet_runs.json`).
  The leak check after the last teardown shows no tagged droplet, no
  `bb-harness-*` ssh key and no local state with a live droplet. The
  account's five other droplets were not touched.
- **Arms ran at commit `abcd42e`.** The report's validation was hardened
  afterwards (`6be3d0f`); that changes no game.
- **Codex, read-only, on the hook and the report code:** no P1. It confirmed
  the unmasked path is unchanged, that the three masks match section 0 and
  never return an empty support, that removing whole types keeps an exact
  joint support, the declaration tracking across batched and unbatched
  paths, the counters and the bootstrap. Three findings, all taken: the
  report now refuses a run that is not the registered arm played to the end;
  the "ended with a block target on offer" row is named for what it counts
  (Block and Blitz); the mask sum is called a summed removed-type
  probability, with the m2-before-m3 crediting stated.
- **Codex, read-only, on the numbers:** no P1. The strength table agrees with
  the droplets' own `tournament_stats` output and the thresholds were applied
  as registered; section 0 is unchanged apart from a trailing newline. Seven
  findings, all taken in the text above: an empty activation is not a skip
  (activation side effects), so m1 is a restriction and not a free rule; the
  reward reading is a hypothesis and the ledger figures are not in this
  branch; m2 and m3 overlap but are not the same; the roster rows are point
  estimates; a lifetime rounding; the shared engine-steps row; the scope of
  "improved strength".

## 8. Where this test's design was wrong

1. **The control measures no noise.** With one checkpoint on both sides and
   sampling seeds keyed by side, the two legs of a seed are the same game,
   so the decisive share is 0.5 exactly. A useful null would have given one
   side a different sampling seed. The intervals above come from the
   seed-cluster bootstrap instead.
2. **m1 does not make the policy play, and it is not a pure "no stopping"
   rule either.** It makes the policy activate every player, with the side
   effects an activation has. "At least one action with every player" is m1
   with m2, which was only run together with m3.
3. **m2 contains most of m3.** No arm isolates the forced first step of a
   Move from the forced block of a Block.
4. **Self-play only.** Masked against plain, both chain 41. Whether m1's
   gain holds against the scripted bots, an older chain or a human is not
   known.
5. **A separate seed block per arm** makes arm-to-arm comparisons weaker
   than they needed to be: the plain side's own numbers differ between arms
   (it scores 0.61 to 0.82 a game depending on what it faces).
6. **"Resolved blocks" is a proxy** (block targets chosen), and the one
   block-specific row was promised more narrowly than the counter can give.
7. **The raw roster split** is dominated by roster strength; only the
   differences from the control row carry anything, and they come from
   different seeds.
