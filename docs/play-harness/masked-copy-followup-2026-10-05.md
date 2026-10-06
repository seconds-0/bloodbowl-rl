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

## 1. Result in one paragraph

m1 transfers to every learned opponent and to the contact bot, and not
clearly to the offense bot. The paired contrast (chain 41 with m1 minus plain
chain 41, same seeds, same opponent) is +42.7 against chain 47, +37.8 against
chain 36, +35.2 against chain 27 and +20.9 against the contact bot, each with
an interval above zero; against the offense bot it is -14.8 [-35.9, 4.6],
inconclusive. By the rule fixed in section 0 that is **mixed**: four better,
one inconclusive. m1 with m2 is +30.2 [15.7, 44.7] over plain chain 41. Two
identical players differ by -11.1 [-25.4, 2.8]. Of the 4.2 activations a team
turn that m1 adds, 58% end at once, 37% are short moves and 5% are blocks.

## 2. The null control

Plain chain 41 against plain chain 41 with the sampling seed of one side
shifted, 3,200 games: W/D/L 880/1382/938, decisive share 0.484, **decisive-Elo
-11.1 [-25.4, 2.8]**. No seed has identical legs. The interval covers zero
and is 28 Elo wide, the same width as the masked arms' intervals, so those
intervals are an honest picture of the spread. Its behaviour differences are
all near zero (activations a team turn 2.98 against 2.97, block targets 7.33
against 7.32, touchdowns 0.73 against 0.75); two of seventeen rows have an
interval that just excludes zero (possession, Blitz declared), which is what
seventeen 95% intervals do. The both-m1 run is a second null in strength: +7.0
[-7.7, 21.0].

## 3. Transfer of m1

Each pair, chain 41's side first. Touchdowns and blocks (block targets chosen)
are per game for chain 41's side.

| opponent | chain 41 side | W / D / L | decisive share | decisive-Elo [95%] | TD for | TD against | blocks |
|---|---|---|---|---|---|---|---|
| offense bot | with m1 | 951 / 1725 / 524 | 0.645 | 103.5 [86.6, 120.8] | 0.411 | 0.275 | 11.4 |
| offense bot | plain | 1024 / 1658 / 518 | 0.664 | 118.4 [100.6, 137.1] | 0.430 | 0.279 | 7.4 |
| contact bot | with m1 | 1118 / 1448 / 634 | 0.638 | 98.5 [82.6, 115.6] | 0.560 | 0.376 | 8.1 |
| contact bot | plain | 1102 / 1393 / 705 | 0.610 | 77.6 [61.5, 94.0] | 0.542 | 0.402 | 5.4 |
| chain 27 | with m1 | 1651 / 1089 / 460 | 0.782 | 222.0 [204.5, 239.1] | 1.128 | 0.538 | 11.7 |
| chain 27 | plain | 1635 / 1007 / 558 | 0.746 | 186.8 [171.3, 202.9] | 1.190 | 0.630 | 7.9 |
| chain 36 | with m1 | 1492 / 1143 / 565 | 0.725 | 168.7 [153.7, 185.1] | 1.108 | 0.668 | 10.8 |
| chain 36 | plain | 1398 / 1144 / 658 | 0.680 | 130.9 [117.1, 144.8] | 1.172 | 0.794 | 7.6 |
| chain 47 | with m1 | 872 / 1403 / 925 | 0.485 | -10.3 [-24.5, 4.4] | 0.680 | 0.725 | 9.4 |
| chain 47 | plain | 822 / 1263 / 1115 | 0.424 | -53.0 [-67.7, -38.6] | 0.709 | 0.860 | 6.9 |

The paired contrasts, m1 minus plain:

| opponent | decisive-Elo contrast [95%] | verdict | score-rate contrast [95%] |
|---|---|---|---|
| offense bot | -14.8 [-35.9, 4.6] | inconclusive | -0.012 [-0.025, -0.001] |
| contact bot | +20.9 [2.0, 39.5] | better | +0.014 [-0.001, 0.027] |
| chain 27 | +35.2 [15.1, 56.0] | better | +0.018 [0.003, 0.033] |
| chain 36 | +37.8 [18.9, 57.0] | better | +0.029 [0.014, 0.044] |
| chain 47 | +42.7 [23.5, 60.6] | better | +0.037 [0.022, 0.052] |

Three things in the table besides the verdicts.

- **The gain is on defence, everywhere.** With m1, chain 41 concedes fewer
  touchdowns against all five opponents (most against chain 47, 0.73 against
  0.86, and chain 36, 0.67 against 0.79) and scores slightly fewer against
  the offense bot and the three chains (for example 1.11 against 1.17 with
  chain 36). Against the contact bot it scores slightly more.
- **The offense bot is the exception, and it is the opponent of the rig
  exam.** Against it m1 concedes the same (0.275 against 0.279), scores less
  (0.411 against 0.430) and draws more (0.54 of games against 0.52). The
  score-rate contrast is small and negative with an interval that just
  excludes zero. There is little defence to gain against a bot that scores
  0.28 a game.
- **Plain chain 41 loses to chain 47** here (-53 Elo); with m1 it is level
  (-10 [-24.5, 4.4]).

## 4. m1 with m2 against plain chain 41

Every player must be activated and must do at least one thing where it can.
W/D/L 979/1398/823, **decisive-Elo +30.2 [15.7, 44.7]: better.** The fallback
fired 0.16 times a game (m2 only).

| | m1 + m2 | plain |
|---|---|---|
| activations per team turn | 5.95 | 3.10 |
| team turns ended by choice with a player left | 0.000 | 0.622 |
| block targets chosen per game | 15.3 | 6.6 |
| turnovers per team turn | 0.558 | 0.309 |
| touchdowns per game | 0.766 | 0.689 |
| possession | 0.403 | 0.397 |
| activations ended at once | 0.002 | 0.209 |
| engine steps per game | 987 | |

This changes the first test's reading of m2. Alone, m2 was worse (-25.4);
with m1 it costs nothing that can be measured: m1 alone was +32.5 [18.3,
47.1] and m1 with m2 is +30.2, on different seeds. The forced first action
is harmless once the copy is also made to go through the whole team. Why it
hurts alone was not measured.

## 5. Both sides under m1

Chain 41 with m1 against chain 41 with m1, one side's sampling seed shifted.
What the game looks like when everyone plays under the rule, against the
null control (nobody under it):

| per side | both under m1 | neither (null) |
|---|---|---|
| activations per team turn | 6.87 | 2.98 |
| block targets chosen per game | 10.6 | 7.3 |
| of which inside a Blitz | 1.28 | 1.19 |
| turnovers per team turn | 0.420 | 0.318 |
| touchdowns per game | 0.581 | 0.742 |
| possession | 0.397 | 0.415 |
| activations ended at once | 0.424 | 0.219 |
| draw rate | 0.488 | 0.432 |
| engine steps per game (decisions, both sides) | 1,202 | 695 |

Scoring falls by about a fifth, draws rise from 43% to 49%, and a game takes
73% more decisions.

## 6. What the extra activations do

Per team turn, chain 41 with m1 against plain chain 41, pooled over the five
transfer runs (16,000 games each, the same opponents and seeds).

| class | with m1 | plain | m1 adds | share of what m1 adds |
|---|---|---|---|---|
| all activations | 7.18 | 2.96 | 4.22 | |
| ended at once (empty) | 3.18 | 0.74 | 2.45 | 58% |
| moved only | 3.28 | 1.74 | 1.54 | 37% |
| blocked | 0.574 | 0.374 | 0.20 | 5% |
| blitzed (a block inside a Blitz) | 0.073 | 0.071 | 0.00 | 0% |
| fouled | 0.000 | 0.000 | 0.00 | |
| passed or handed off | 0.002 | 0.001 | 0.00 | |
| ended by the engine with no choice | 0.037 | 0.020 | 0.02 | 0.4% |
| other | 0.032 | 0.025 | 0.01 | 0.2% |

Moved-only activations (807,337 with m1, 420,631 plain, player on the pitch
at both ends):

| | with m1 | plain |
|---|---|---|
| mean net displacement, squares | 2.46 | 2.98 |
| mean change in distance to the ball | -0.39 | -0.57 |
| mean change in distance from own end zone | +0.06 | +0.13 |

These rows average all moved-only activations on each side, not the added
ones alone. Solving for the added 1.54 a turn gives about 1.9 squares of net
displacement and about 0.2 squares nearer the ball each: short adjustments,
with no drift up or down the pitch. Activations that end the team turn in a
turnover go from 0.27 to 0.37 a team turn.

**Negative traits** (Bone Head, Really Stupid, Animal Savagery, Unchannelled
Fury, Take Root, Bloodlust). The harness sees skills. It cannot tell a
forced activation from one the policy would have made, so this is the
difference between the two sides.

| per game, chain 41's side | with m1 | plain |
|---|---|---|
| activations of a negative-trait player | 8.24 | 6.10 |
| came out newly Distracted or Rooted | 8.4% | 7.6% |
| those failures per game | 0.70 | 0.47 |
| the engine ended the activation with no choice | 6.7% | 4.9% |
| ended at once by choice | 23.8% | 17.4% |
| blocked or blitzed | 30.5% | 38.7% |
| the team turn ended in a turnover with this activation as its last | 12.8% | 15.8% |
| those turnovers per game | 1.05 | 0.96 |

m1 adds about 2.1 negative-trait activations a game, 0.23 more failed rolls
that leave a player Distracted or Rooted (a lost tackle zone until its next
activation), and 0.09 more turn-ending turnovers at such a player. Failed
Animal Savagery, Unchannelled Fury and Bloodlust rolls show only as
engine-ended activations or turnovers and are not counted as failures here.

## 7. Would I spend a training rung on an env-side m1 rule?

By the rule fixed in section 0 the transfer result is **mixed**, not a clean
yes: four contrasts better, the offense bot inconclusive and leaning
negative. My answer is **yes, one paired rung, on three conditions**, because
the one miss is the opponent against which there is the least to gain and
the four hits include the only peer (chain 47).

1. **Re-register the gate for that rung before it starts.** m1 trades
   touchdowns for fewer touchdowns conceded: with both sides under it,
   scoring falls by a fifth, and against the offense bot the m1 copy scores
   0.411 a game against 0.430. The exam's parent veto and floor are counts
   of touchdowns scored against the offense bot. A rung trained and examined
   under the rule can read Negative on that veto while being stronger head
   to head. Decide in advance which reading governs.
2. **Budget for longer games.** 1,202 decisions a game against 695 when both
   sides play under the rule: a fixed step budget buys about 42% fewer
   games, and a per-decision discount reaches less far into a turn.
3. **Watch the first thing that could go wrong:** 58% of what m1 adds is
   empty activations already. A policy trained under the rule, with a dense
   reward that pays nothing for the other players and charges blocks, may
   learn to make all of it empty. The activation log added here (class
   shares per team turn) is the meter; if empties per team turn climb toward
   the whole of the added activations, the rule has bought nothing.

What this test does not say: what a policy trained under the rule does, how
it does against a human, or anything about opponents outside chain 41's
lineage other than the two bots.

## 8. Cost, commits, review

- **Where it ran.** Eight `s-8vcpu-16gb-amd` droplets in sfo3 at the same
  time, each created and destroyed by `tools/droplet_tournament.py`; every
  run verified by sha256, against its manifest, and with zero integrity
  counters; 38,400 games. Lifetimes 10.7 to 21.9 minutes, **$0.40**
  (`docs/play-harness/masked-copy-followup-2026-10-05/droplet_runs.json`).
  With the first test's $0.15 the whole question cost $0.55. The leak check
  after the last teardown shows no tagged droplet, no `bb-harness-*` key and
  no live local state; the account's five other droplets were not touched.
- **All runs at commit `0f1032f`.** A 64-game slice of plain against plain on
  that code has the same action trail, score and log-probability sum in
  every game as the unmodified checkout at `b0099fb`.
