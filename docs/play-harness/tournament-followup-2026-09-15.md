# Round robin follow-up, 2026-09-15

**Question.** An adversarial panel (DECISIONS.md D399) asked for five checks
before the 2026-09-15 round robin
([tournament-2026-09-15.md](tournament-2026-09-15.md)) could be trusted:

1. committed seed-cluster and leg-correlation code;
2. the training-seed noise floor that a gain like chain 30 over chain 25
   (+108 decisive Elo) has to exceed;
3. whether chain 30's edge survives argmax play and temperature-matched sharpness;
4. whether the edge depends on roster type;
5. a power calculation for N.

**Answer.**

1. **Chain 30's gap over chain 25 exceeds the training-seed floor by a wide
   margin.**
   - The three replicate pairs (same recipe, different training seed) are 14,
     40 and 16 decisive Elo apart. Every one of those intervals excludes zero, so
     the training seed alone moves a checkpoint by tens of Elo.
   - That puts the between-seed SD of a checkpoint difference at about 25 Elo.
   - Chain 30 over chain 25 is +106. With match noise and that seed spread
     combined, z is about 3.9. Chain 30 over chain 26 (chain 25's recipe at seed
     44) is +141.
2. **The gap survives both sharpness controls.**
   - Argmax on both seats: chain 30 over chain 25 is +106.4 [+92, +121], against
     +106.3 in sample mode.
   - Chain 25 sharpened to T = 0.75 so its per-decision logprob matches chain
     30's: chain 30 still leads by +109.3 [+95, +124].
   - Chain 27's edge over chain 25 shrinks under argmax, from +100 to +71 [+55,
     +87], but stays far above the floor.
3. **The gain is not roster-dependent at the agile/bash level.**
   - The panel's per-roster pattern is roster strength. Split by the class a coach
     played, "agile minus bash" reads +0.36 and +0.40 even for replicate pairs
     with no policy gap.
   - With roster strength fitted, chain 30 over chain 25 is similar on agile and
     bash in every condition: g_agile − g_bash is −29 (rr6), −15 (temperature)
     and +59 (argmax), all with intervals covering zero.
   - The edge on bash rosters is at least +100 in every condition.
   - Stunty rosters show the smallest edge under the controls (+63 at T = 0.75,
     +44 in argmax). That is a lead, not a finding.

This is a CPU-harness result with in-family opponents, not a promotion; see
"Unverified".

## Statistics now committed

All of these are in `play_harness/tournament_stats.py`, with tests in
`play_harness/tests/test_tournament_stats.py`.

| statistic | function | commit |
|---|---|---|
| leg correlation, centred within each pair | `leg_correlation` | ec3d633 |
| seed-cluster bootstrap: seeds resampled jointly across pairs and legs, with pair shares, draw-inclusive score rates and Elo gaps | `seed_cluster_bootstrap` | dfb7f4a |
| Bradley-Terry refuses a disconnected pair graph | `bt_fit` | 30f7983 |
| Bradley-Terry misfit (Pearson chi-square and deviance) | `bt_misfit`, `chi2_sf` | efe339e |
| seed-cluster Wald test of the misfit | `bt_misfit(games=...)` | 3f829f1 |
| power helper | `power_mde_elo`, `power_games_per_pair` | 86613ea |
| decisive-share design effect for the power helper | `decisive_design_effect` | 2f0ce9d |
| per-player decision sharpness | `sharpness` | 31aab2e |
| roster archetypes and shares by the class A coached | `ROSTER_CLASS`, `classify_roster`, `roster_class_table` | b496fc0, ac92e17 |
| roster gap model: class-specific policy gaps with roster strength fitted | `roster_gap_model` | 149d9be |
| undefined bootstrap shares are left out of the ahead frequency | `seed_cluster_bootstrap` | c88af89 |
| CLI report | `main`, `report` | af40186 |

The leg-correlation test was run against a first draft that reproduced the
round robin doc's calculation, a Pearson correlation pooled over all pairs. It
failed: on synthetic pairs whose two legs are exactly independent, that draft
read 0.36 instead of 0. Centring within each pair fixed it. On rr6 the centred
value is **-0.207** and the pooled value -0.087; the round robin doc is
corrected in 364890f.

Recomputed on rr6 with the committed code (2000 replicates):

- Seed-cluster Bradley-Terry Elo SEs are 4.0 to 5.0. P(chain30 > chain27) =
  0.87 and P(chain31 > chain25) = 0.98, as the doc said.
- Pair intervals match Wilson within 0.006 at every endpoint. The seed-cluster
  intervals are about 10% narrower, as the negative leg correlation implies.
- Bradley-Terry misfit: chi-square 20.3 on 10 df, p = 0.026; deviance 20.3,
  p = 0.027. The largest |z| is 1.98 (chain27 vs chain9); the doc said 1.93.
  The seed-cluster Wald test gives 26.8 on 10 df, **p = 0.003**. The round robin
  doc called the misfit mild; that doc now reports it as real.
- Decisive-share design effect: 0.812. The within-pair score correlation is
  -0.207, which gives a design effect of 0.793 for the score.

**Review.** A Codex review of these commits (gpt-6-astra, read-only) found six
problems. All are fixed, each with a test (18f6018, 149d9be, 2f0ce9d, 3f829f1,
c88af89 and b59268b, in the order listed):

1. A resumed run whose manifest predates per-player specs could switch
   temperatures or pairs midway. The resume check now fills in the legacy specs
   before comparing.
2. The first roster-balanced contrast pooled legs by seed matchup. That does not
   cancel roster strength on the logit scale, so it is withdrawn and replaced by
   the roster gap model (see "Roster archetypes").
3. The power helper took the score correlation as its design effect. It now
   takes the decisive-share influence design effect.
4. The misfit p-value assumed independent games. The seed-cluster Wald test was
   added; a null simulation with cross-pair seed effects measured naive
   rejections of 9-13% at a nominal 5%, and 2-5% for the Wald test.
5. Bootstrap replicates with no decisive games counted against A in the ahead
   frequency. They are now left out.
6. Extreme temperatures could produce NaN logprobs. T is now limited to
   [1e-3, 1e3].

The review also notes that `select_joint` tempers each head's conditional
softmax. That is not the joint distribution raised to 1/T.

## Method

- **Runner.** `play_harness/tournament.py` at 4a1b60a. Integrity contract,
  kernel, rosters and recurrence are unchanged from the round robin. Two
  additions:
  - `--pair A,B,N`: play chosen pairs, each with its own game count.
  - Per-player `--player-mode NAME=argmax` and `--temperature NAME=T`. One
    blob can be several players; they share the policy object, and each seat
    keeps its own state. Each game record carries per-side `modes` and
    `temperatures`, and the manifest records every player's spec.
- **Temperature** (ba61b09). `select_joint` divides every head's logits by T
  before masking and the exact joint selection. T = 1 is bit-identical to the
  trained policy, and argmax choices do not depend on T. The recorded logprob
  is under the tempered distribution that was actually sampled.
- **Seeds.** Game indices 0 to N/2 - 1 on engine seeds 20261615 + i. This block
  follows rr6's (20260915 to 20261614) with no overlap. Calibration used a
  separate block starting at 20500000. Each index is played in both legs, and
  all pairs share the same seeds.
- **Compute.** Mac CPU only, 4 spawn workers at `OMP_NUM_THREADS=1`, no GPU.
  The only rig access was read-only `scp`.

## Replicate checkpoints

Copied read-only from the rig
(`vendor/PufferLib/checkpoints/bloodbowl/<dir>/0000002999975936.bin` plus the
`.lineage.json` sidecar). Every blob's sha256 equals `checkpoint_sha256` in its
run's `LADDER_RUNG_COMPLETE.json`, and the harness loader re-verifies the
sidecar. Across the full rung records (arm, pool hash, warm start, warm marker,
gamma, lambda, lr and entropy scales, steps, bank and bot settings), each
replicate differs from its twin **only in the training seed**.

| replicate | rig dir | sha256 | twin | warm start | pool | seed (twin) |
|---|---|---|---|---|---|---|
| chain16 | 1787771854045 | 1fdcbb1e | chain9 (4344e588) | chain 2 marker (1787338735330) | 7c15fd4f | 43 (42) |
| chain20 | 1787876979838 | 61c236ec | chain14 (dde7c98b) | chain 9 marker (1787584031608) | d67d527b | 44 (42) |
| chain26 | 1789281314386 | 0ff7bfb7 | chain25 (109c55d3) | chain 9 marker (1787584031608) | d67d527b | 44 (42) |

Chain 26 also carries gamma 0.999 and lambda 0.95, as chain 25 does.

## Temperature calibration

Chain 30's sharpness in rr6 is -0.1428 over all its games (sum of logprob over
sum of decisions), and -0.1396 in its games against chain 25. Chain 25 at T = 1
is at -0.1870 overall (-0.1800 against chain 30).

To calibrate, chain 30 (T = 1) played chain 25 at T on the calibration seed
block. Both players' sharpness was measured in the same games:

| T | games | chain 25 at T | chain 30, same games |
|---|---|---|---|
| 0.74 | 400 | -0.1411 | -0.1404 |
| 0.77 | 400 | -0.1465 | -0.1404 |
| 0.80 | 200 | -0.1515 | -0.1450 |
| 0.85 | 200 | -0.1618 | -0.1432 |
| 0.90 | 200 | -0.1679 | -0.1451 |

Chain 25's sharpness is monotone in T. Interpolating linearly between 0.74 and
0.77 for chain 30's rr6 value of -0.1428 gives T = 0.753; a quadratic fit
through all five points gives the same. Matching chain 30's -0.144 in the
calibration games instead gives T = 0.759. **T = 0.75** was fixed before any
evaluation game. Its realised sharpness in the evaluation games is reported
below as a check.

## Sizing N

The power helper uses a normal approximation on the logit of the decisive
share. The two legs of a seed form a cluster of two, so the variance carries a
design effect.

N was chosen before the review with a design effect of 1 + r = 0.793, from the
score correlation. The corrected decisive-share design effect on rr6 is 0.812,
which raises every MDE by about 1%. The table uses the corrected value, with a
decisive fraction of 0.647 from rr6. Argmax games are more drawish (a 24-game
pilot drew 46%), so the argmax pair was sized at a decisive fraction of 0.54.

| games per pair | MDE at share 0.5 | at share 0.65 | argmax (decisive 0.54) |
|---|---|---|---|
| 1400 (rr6) | 29.2 | 30.6 | 31.9 |
| 2400 | 22.3 | 23.4 | 24.4 |
| 3200 | 19.3 | 20.2 | 21.1 |

MDE is the smallest decisive-Elo gap detected with 80% power in a two-sided
test at 5%. 20 Elo needs 2976 games per pair (3564 for argmax); 30 Elo needs
1322 (1584).

**Choice.** The three key pairs got 3200 games: chain 25 vs chain 26, chain 30
vs chain 25 in argmax, and chain 30 vs chain 25 at T = 0.75. That detects about
19-22 Elo. The other five pairs got 2400 (about 22-24 Elo). Total: 21,600
games.

**Cost.**
- Pilot: 72 games at 0.68-0.72 s per game on one thread, 5.0 games/s wall.
- Calibration: 1400 games in about 4.4 min wall.
- Main run: 21,600 games in 3970.2 s wall (66.2 min) at 5.44 games/s. Games
  took 0.735 s each on one thread (median 0.727 s, max 1.71 s).
- Total compute including calibration and pilot: about 71 min of the 90 min
  budget.

Nothing was dropped.

**Realised power.** Across the follow-up pairs, the centred leg correlation is
-0.225 and the decisive-share design effect 0.781.

| pair | games | decisive fraction | MDE (decisive Elo, 80% power) |
|---|---|---|---|
| chain25 vs chain26 | 3200 | 0.610 | 19.5 |
| chain30A vs chain25A (argmax) | 3200 | 0.627 | 19.2 |
| chain30 vs chain25T (T = 0.75) | 3200 | 0.643 | 19.0 |
| chain9 vs chain16 | 2400 | 0.681 | 21.3 |
| chain14 vs chain20 | 2400 | 0.619 | 22.3 |
| chain30 vs chain26 | 2400 | 0.640 | 21.9 |
| chain30 vs chain16 | 2400 | 0.714 | 20.8 |
| chain27A vs chain25A (argmax) | 2400 | 0.577 | 23.1 |

## Noise floor

Each replicate pair is one recipe at two training seeds. Rows are from A's
side, with 95% seed-cluster intervals; "draw-incl." counts a draw as half.

| pair (A first) | games | A W / D / L | A decisive share | decisive Elo | SE | score rate | draw-incl. Elo |
|---|---|---|---|---|---|---|---|
| chain25 vs chain26 (seed 42 vs 44) | 3200 | 1016 / 1248 / 936 | 0.520 [0.502, 0.540] | +14.2 [+1.1, +28.1] | 6.9 | 0.512 | +8.7 [+0.7, +17.1] |
| chain9 vs chain16 (seed 42 vs 43) | 2400 | 911 / 765 / 724 | 0.557 [0.538, 0.577] | +39.9 [+26.1, +53.6] | 7.0 | 0.539 | +27.1 [+17.7, +36.4] |
| chain14 vs chain20 (seed 42 vs 44) | 2400 | 709 / 915 / 776 | 0.477 [0.456, 0.498] | −15.7 [−30.7, −1.4] | 7.6 | 0.486 | −9.7 [−19.0, −0.9] |

**The training-seed floor.**
- All three replicate gaps exceed match noise: their intervals exclude zero.
- The RMS gap is 26.1 Elo.
- Subtracting match variance (method of moments) leaves a between-seed SD of a
  checkpoint difference of about 25 Elo.
- The largest replicate gap is 40 Elo, with an upper bound of 54.
- A gain between two single-seed checkpoints needs to clear roughly 50 Elo
  (2 SD) before the training seed is an unlikely explanation.

**Replicates against the frontier.**

| pair | run | games | A W / D / L | A decisive share | decisive Elo | SE | score rate | draw-incl. Elo |
|---|---|---|---|---|---|---|---|---|
| chain30 vs chain25 | rr6 | 1400 | 581 / 504 / 315 | 0.648 [0.620, 0.676] | +106.3 [+85.0, +127.7] | 10.9 | 0.595 | +66.8 [+53.3, +79.8] |
| chain30 vs chain26 | follow-up | 2400 | 1063 / 864 / 473 | 0.692 [0.671, 0.713] | +140.7 [+124.1, +158.5] | 8.7 | 0.623 | +87.2 [+77.1, +97.7] |
| chain30 vs chain9 | rr6 | 1400 | 742 / 438 / 220 | 0.771 [0.747, 0.795] | +211.2 [+187.7, +235.7] | 12.1 | 0.686 | +136.1 [+122.2, +150.2] |
| chain30 vs chain16 | follow-up | 2400 | 1386 / 686 / 328 | 0.809 [0.792, 0.826] | +250.4 [+232.0, +270.7] | 9.9 | 0.720 | +164.4 [+153.5, +176.1] |

**Consistency.**
- Chain 30's margin over chain 26 exceeds its margin over chain 25 by 34 Elo
  (SE 14), and chain 25 beats chain 26 by 14.
- Its margin over chain 16 exceeds its margin over chain 9 by 39 (SE 16), and
  chain 9 beats chain 16 by 40.
- So the replicate gaps carry through to a third player. They are real
  checkpoint differences, not match noise.

**Chain 30 over chain 25 against the floor.**
- The gap is +106.3 (match SE 10.9). With a 25 Elo seed spread added, the SE is
  27.4 and z = 3.9.
- Averaged over chain 25's two training seeds, chain 30's margin is +123.5
  (SE 7.0).
- The +108 decisive-Elo gain is about four seed-spread SDs and more than twice
  the largest replicate gap, so **it exceeds the training-seed floor**.
- Chain 30's own recipe is still measured at one seed. Its spread is assumed
  comparable to the three replicate pairs; D399's chain 32 measures it.

## Sharpness controls

The control games use the follow-up seed block. Each row is paired with the
sample-mode (T = 1) result for the same checkpoints from rr6.

| pair (A first) | run | games | A W / D / L | A decisive share | decisive Elo | SE | score rate | draw-incl. Elo |
|---|---|---|---|---|---|---|---|---|
| chain30 vs chain25, **argmax** | follow-up | 3200 | 1301 / 1194 / 705 | 0.649 [0.630, 0.668] | +106.4 [+92.4, +121.2] | 7.4 | 0.593 | +65.5 [+57.0, +74.3] |
| chain30 vs chain25, sample | rr6 | 1400 | 581 / 504 / 315 | 0.648 [0.620, 0.676] | +106.3 [+85.0, +127.7] | 10.9 | 0.595 | +66.8 [+53.3, +79.8] |
| chain30 vs chain25 **at T = 0.75** | follow-up | 3200 | 1343 / 1141 / 716 | 0.652 [0.633, 0.672] | +109.3 [+94.5, +124.4] | 7.5 | 0.598 | +69.0 [+60.0, +78.1] |
| chain27 vs chain25, **argmax** | follow-up | 2400 | 831 / 1016 / 553 | 0.600 [0.578, 0.623] | +70.8 [+54.7, +87.4] | 8.2 | 0.558 | +40.4 [+31.3, +49.7] |
| chain27 vs chain25, sample | rr6 | 1400 | 534 / 565 / 301 | 0.640 [0.612, 0.666] | +99.6 [+79.1, +120.1] | 10.5 | 0.583 | +58.4 [+46.4, +70.2] |

Control minus sample-mode decisive Elo:

| pair | control | change | SE | draw rate, control vs sample |
|---|---|---|---|---|
| chain30 vs chain25 | argmax | +0.1 | 13.2 | 0.373 vs 0.360 |
| chain30 vs chain25 | chain 25 at T = 0.75 | +2.9 | 13.2 | 0.357 vs 0.360 |
| chain27 vs chain25 | argmax | −28.8 | 13.3 | 0.423 vs 0.404 |

**Realised sharpness** (mean per-decision logprob in the follow-up games):

| player | sharpness |
|---|---|
| chain30 | −0.1415 |
| chain25 at T = 0.75 | −0.1444 |
| chain25 (T = 1) | −0.1844 |
| chain26 | −0.1974 |
| chain9 | −0.2240 |
| chain16 | −0.2307 |
| chain14 | −0.2563 |
| chain20 | −0.2622 |

- In the chain 30 vs chain 25T games alone, chain 25 at T = 0.75 is at −0.1444
  and chain 30 at −0.1396. So chain 25 remained 0.005 less sharp than chain 30.
  That is about 0.02 in T, and it moves the matched-sharpness verdict by far
  less than the 109 Elo gap.
- The argmax figures (chain30A −0.080, chain27A −0.087, chain25A −0.104) are
  softmax scores of the chosen tuple, not entropies.

**Verdict.**
- With both seats deterministic, chain 30's edge over chain 25 is unchanged.
- With chain 25's sampling as sharp as chain 30's, the edge is unchanged again.
- So the rank-sharpness match the panel found is not what produces chain 30's
  edge: its edge comes from which actions it prefers, not from sampling its
  choices more greedily.
- Chain 27 loses about 29 Elo of its edge in argmax (z = −2.2) but keeps +71,
  still above the floor.

## Roster archetypes

The classes come from the BB2025 roster spec that generates
`engine/src/gen_teams.c`. The "lineman" is a roster's first position allowing
12 or more players. "Heavy slots" is the total allowance of all other positions
with ST 4+, Big Guys included. The first rule that matches wins
(`classify_roster`; a test re-derives `ROSTER_CLASS` from the spec):

1. **agile:** lineman AG 2+, or a lineman with Dodge but not Stunty;
2. **stunty:** lineman has Stunty and fewer than 5 heavy slots;
3. **bash:** lineman MA 5 or less, AV 10+ or Block; or 5+ heavy slots; or 4+
   Block slots outside the lineman;
4. **hybrid:** everything else.

| class | rosters |
|---|---|
| agile (5) | Amazon, Dark Elf, Elven Union, High Elf, Wood Elf |
| bash (15) | Black Orc, Chaos Chosen, Chaos Dwarf, Dwarf, Khorne, Lizardmen, Necromantic Horror, Norse, Nurgle, Ogre, Old World Alliance, Orc, Shambling Undead, Tomb Kings, Vampire |
| hybrid (5) | Bretonnian, Chaos Renegades, Human, Imperial Nobility, Skaven |
| stunty (5) | Gnome, Goblin, Halfling, Snotling, Underworld Denizens |

Contested calls under this rule: Old World Alliance counts as bash (six Block
slots), Vampire as bash (five ST 4+ slots), Chaos Renegades as hybrid (four Big
Guys), and Ogre as bash (six ST 5 Ogres beside a Stunty lineman).

### Stratifying on the coached roster measures roster strength

The panel's per-roster figures for chain 30 against chain 25 reproduce
exactly as chain 30's decisive share, split by the roster chain 30 coached:

| roster chain 30 coached | chain 30 decisive share (decisive games) | same split, chain 9 vs chain 14 |
|---|---|---|
| Shambling Undead | 0.370 (27) | 0.250 (28) |
| Chaos Chosen | 0.375 (32) | 0.267 (30) |
| Tomb Kings | 0.381 (21) | 0.091 (22) |
| High Elf | 0.933 (30) | 0.806 (31) |
| Dark Elf | 0.927 (41) | 0.949 (39) |

Chain 9 and chain 14 are tied head to head (0.532 / 0.468), but the same split
shows the same pattern. Rosters stay with the side, so when a coach plays
High Elf the opponent plays the seed's other roster. The split therefore
measures how strong the roster is. Over all 21,000 rr6 games, whoever coaches
takes this share of decisive games:
- agile rosters 0.705, bash 0.405, hybrid 0.517, stunty 0.531;
- best Dark Elf 0.802; worst Nurgle 0.258, Tomb Kings 0.265, Shambling Undead
  0.294.

Split by A's coached class, A does better on agile than on bash in all 15 rr6
pairs, by +0.167 to +0.376. That includes chain 9 vs chain 14 (+0.221), a pair
with no policy gap to speak of.

**Roster gap model.** Pooling both legs of each seed balances roster exposure,
but it does not cancel roster strength on the logit scale. With a roster offset
h, the pooled share is (σ(g + h) + σ(g − h)) / 2, and its logit is not g. An
earlier draft read a contrast from those pooled strata; it is withdrawn.

`roster_gap_model` fits, for each pair and each decisive game:

logit P(A wins) = g[class A coaches] + s[A's roster] − s[B's roster]

It has one strength per roster, with a weak ridge. Swapped legs identify s and
mirror seeds pin g; intervals come from the seed-cluster bootstrap. On a
synthetic case with the same policy gap on every class and a strong roster
offset, a test shows the pooled-strata contrast reads about −84 Elo while the
model reads about 0.

rr6, oriented as the first-named chain over the second (decisive Elo, 95%
seed-cluster interval):

| pair | g agile | g bash | g hybrid | g stunty | g agile − g bash |
|---|---|---|---|---|---|
| chain30 over chain25 | +112 [+32, +208] | +141 [+100, +197] | +86 [+17, +172] | +120 [+50, +212] | −29 [−127, +78] |
| chain27 over chain25 | +145 [+61, +251] | +121 [+77, +181] | +188 [+103, +305] | +87 [+10, +176] | +24 [−87, +146] |
| chain25 over chain9 | −6 [−97, +87] | +138 [+100, +194] | +160 [+78, +267] | +169 [+97, +265] | −144 [−262, −43] |
| chain30 over chain9 | +172 [+84, +290] | +273 [+228, +350] | +221 [+143, +332] | +287 [+216, +409] | −101 [−235, +27] |
| chain9 over chain14 | +222 [+141, +331] | −24 [−69, +20] | +40 [−47, +124] | −21 [−98, +55] | +246 [+152, +369] |

With roster strength controlled:
- Chain 30's edge over chain 25 appears on every class at similar size, and
  g_agile − g_bash is near zero. The same holds for chain 27 over chain 25.
- The horizon gain (chain 25 over chain 9) is zero on agile rosters and about
  +140 to +170 on the other classes.
- Chain 9 and chain 14 look tied overall, but they interact strongly with roster
  class.

Of the 15 rr6 pairs, 2 have a g_agile − g_bash interval that excludes zero
(chain25/chain9 and chain14/chain9). About 0.75 would be expected by chance, so
treat the class interactions as leads, not findings.

### Follow-up pairs

**Split by the class A coached** (decisive share, seed-cluster 95% interval,
decisive games in parentheses):

| A | B | agile | bash | hybrid | stunty | agile minus bash |
|---|---|---|---|---|---|---|
| chain25 | chain26 | 0.771 [0.726, 0.814] (341) | 0.415 [0.386, 0.445] (951) | 0.497 [0.443, 0.551] (320) | 0.585 [0.531, 0.635] (340) | +0.356 [+0.301, +0.408] |
| chain9 | chain16 | 0.811 [0.763, 0.858] (275) | 0.416 [0.384, 0.448] (808) | 0.659 [0.602, 0.714] (270) | 0.617 [0.562, 0.673] (282) | +0.395 [+0.336, +0.454] |
| chain14 | chain20 | 0.736 [0.683, 0.789] (250) | 0.362 [0.328, 0.396] (735) | 0.530 [0.468, 0.593] (236) | 0.508 [0.445, 0.569] (264) | +0.374 [+0.308, +0.444] |
| chain30 | chain26 | 0.880 [0.842, 0.918] (276) | 0.606 [0.571, 0.641] (738) | 0.698 [0.639, 0.751] (252) | 0.730 [0.675, 0.782] (270) | +0.275 [+0.220, +0.327] |
| chain30 | chain16 | 0.919 [0.887, 0.949] (295) | 0.752 [0.722, 0.781] (832) | 0.846 [0.801, 0.888] (286) | 0.821 [0.776, 0.862] (301) | +0.166 [+0.123, +0.211] |
| chain30A | chain25A | 0.868 [0.831, 0.902] (370) | 0.545 [0.512, 0.574] (942) | 0.651 [0.601, 0.702] (347) | 0.695 [0.645, 0.742] (347) | +0.323 [+0.275, +0.371] |
| chain30 | chain25T | 0.833 [0.792, 0.870] (383) | 0.569 [0.538, 0.599] (1007) | 0.668 [0.611, 0.720] (304) | 0.679 [0.631, 0.725] (365) | +0.264 [+0.212, +0.312] |
| chain27A | chain25A | 0.835 [0.785, 0.883] (242) | 0.482 [0.447, 0.516] (687) | 0.603 [0.533, 0.671] (214) | 0.701 [0.641, 0.760] (241) | +0.353 [+0.291, +0.414] |

The three replicate pairs show the largest agile minus bash contrasts (+0.36 to
+0.40), and they have no policy gap to speak of. This split measures roster
strength.

**Roster gap model** (decisive Elo of A over B when A coaches the class, 95%
seed-cluster interval; every fit converged):

| A | B | g agile | g bash | g hybrid | g stunty | g agile − g bash |
|---|---|---|---|---|---|---|
| chain25 | chain26 | +28 [−32, +90] | +39 [+10, +72] | −9 [−62, +50] | +7 [−51, +59] | −10 [−82, +60] |
| chain9 | chain16 | +30 [−41, +108] | +61 [+28, +95] | +45 [−19, +113] | +62 [+5, +127] | −31 [−115, +55] |
| chain14 | chain20 | −63 [−141, +5] | −1 [−35, +30] | −16 [−84, +49] | −47 [−116, +16] | −62 [−151, +17] |
| chain30 | chain26 | +204 [+140, +286] | +157 [+124, +202] | +169 [+111, +240] | +133 [+67, +207] | +47 [−36, +137] |
| chain30 | chain16 | +250 [+181, +358] | +334 [+301, +389] | +300 [+224, +396] | +247 [+181, +336] | −84 [−176, +24] |
| chain30A | chain25A | +188 [+130, +266] | +128 [+100, +162] | +159 [+104, +222] | +44 [−10, +102] | +59 [−13, +144] |
| chain30 | chain25T | +130 [+71, +197] | +145 [+118, +179] | +140 [+82, +207] | +63 [+10, +119] | −15 [−87, +58] |
| chain27A | chain25A | +103 [+38, +184] | +91 [+57, +129] | +100 [+30, +181] | +62 [−3, +134] | +13 [−66, +100] |

### rr6 pairs

**Split by the class A coached:**

| A | B | agile | bash | hybrid | stunty | agile minus bash |
|---|---|---|---|---|---|---|
| chain14 | chain25 | 0.575 [0.496, 0.656] (146) | 0.217 [0.182, 0.253] (448) | 0.323 [0.252, 0.394] (161) | 0.308 [0.236, 0.380] (156) | +0.359 [+0.269, +0.451] |
| chain14 | chain27 | 0.440 [0.359, 0.520] (150) | 0.154 [0.126, 0.190] (473) | 0.201 [0.140, 0.262] (164) | 0.241 [0.179, 0.309] (166) | +0.286 [+0.191, +0.373] |
| chain14 | chain30 | 0.317 [0.244, 0.392] (145) | 0.124 [0.097, 0.154] (484) | 0.132 [0.078, 0.189] (151) | 0.245 [0.176, 0.313] (151) | +0.193 [+0.115, +0.273] |
| chain14 | chain31 | 0.504 [0.422, 0.585] (141) | 0.217 [0.182, 0.254] (483) | 0.240 [0.178, 0.307] (171) | 0.280 [0.211, 0.355] (150) | +0.286 [+0.197, +0.376] |
| chain14 | chain9 | 0.600 [0.521, 0.677] (160) | 0.379 [0.337, 0.423] (443) | 0.517 [0.436, 0.600] (149) | 0.533 [0.460, 0.605] (169) | +0.221 [+0.126, +0.311] |
| chain25 | chain27 | 0.600 [0.524, 0.677] (150) | 0.268 [0.229, 0.310] (403) | 0.273 [0.200, 0.348] (132) | 0.447 [0.372, 0.525] (150) | +0.332 [+0.241, +0.417] |
| chain25 | chain30 | 0.573 [0.500, 0.647] (150) | 0.257 [0.220, 0.295] (428) | 0.352 [0.280, 0.424] (165) | 0.399 [0.323, 0.476] (153) | +0.316 [+0.231, +0.399] |
| chain25 | chain31 | 0.750 [0.678, 0.820] (152) | 0.374 [0.328, 0.418] (409) | 0.455 [0.371, 0.531] (143) | 0.527 [0.450, 0.601] (150) | +0.376 [+0.286, +0.464] |
| chain25 | chain9 | 0.784 [0.718, 0.851] (167) | 0.546 [0.502, 0.590] (436) | 0.698 [0.624, 0.769] (169) | 0.720 [0.652, 0.786] (157) | +0.239 [+0.158, +0.319] |
| chain27 | chain30 | 0.694 [0.621, 0.765] (147) | 0.441 [0.392, 0.487] (397) | 0.524 [0.439, 0.603] (147) | 0.540 [0.453, 0.627] (137) | +0.253 [+0.163, +0.343] |
| chain27 | chain31 | 0.785 [0.723, 0.843] (177) | 0.568 [0.518, 0.618] (391) | 0.724 [0.655, 0.793] (152) | 0.639 [0.561, 0.713] (147) | +0.218 [+0.135, +0.296] |
| chain27 | chain9 | 0.862 [0.810, 0.910] (188) | 0.648 [0.603, 0.690] (420) | 0.794 [0.730, 0.854] (155) | 0.799 [0.732, 0.861] (154) | +0.214 [+0.144, +0.283] |
| chain30 | chain31 | 0.799 [0.735, 0.859] (174) | 0.582 [0.536, 0.627] (411) | 0.659 [0.588, 0.732] (170) | 0.641 [0.568, 0.715] (153) | +0.217 [+0.139, +0.293] |
| chain30 | chain9 | 0.876 [0.824, 0.923] (185) | 0.709 [0.667, 0.749] (436) | 0.775 [0.706, 0.834] (169) | 0.814 [0.753, 0.871] (172) | +0.167 [+0.102, +0.234] |
| chain31 | chain9 | 0.866 [0.810, 0.920] (179) | 0.618 [0.572, 0.667] (414) | 0.707 [0.639, 0.771] (167) | 0.679 [0.605, 0.750] (162) | +0.248 [+0.172, +0.319] |

**Roster gap model**, rows as stored (A is the first name in string order):

| A | B | g agile | g bash | g hybrid | g stunty | g agile − g bash |
|---|---|---|---|---|---|---|
| chain14 | chain25 | −161 [−280, −66] | −166 [−223, −130] | −201 [−316, −113] | −113 [−213, −36] | +5 [−114, +123] |
| chain14 | chain27 | −224 [−361, −139] | −248 [−320, −205] | −285 [−412, −205] | −293 [−416, −214] | +24 [−115, +137] |
| chain14 | chain30 | −246 [−377, −158] | −300 [−383, −262] | −367 [−539, −282] | −264 [−412, −173] | +55 [−66, +182] |
| chain14 | chain31 | −161 [−272, −74] | −169 [−226, −130] | −271 [−389, −186] | −180 [−281, −105] | +8 [−108, +113] |
| chain14 | chain9 | −222 [−331, −141] | +24 [−20, +69] | −40 [−124, +47] | +21 [−55, +98] | −246 [−369, −152] |
| chain25 | chain27 | −145 [−251, −61] | −121 [−181, −77] | −188 [−305, −103] | −87 [−176, −10] | −24 [−146, +87] |
| chain25 | chain30 | −112 [−208, −32] | −141 [−197, −100] | −86 [−172, −17] | −120 [−212, −50] | +29 [−78, +127] |
| chain25 | chain31 | +48 [−37, +144] | −20 [−74, +26] | −35 [−119, +49] | −38 [−125, +44] | +68 [−35, +187] |
| chain25 | chain9 | −6 [−97, +87] | +138 [+100, +194] | +160 [+78, +267] | +169 [+97, +265] | −144 [−262, −43] |
| chain27 | chain30 | −22 [−118, +69] | +50 [+1, +100] | +12 [−78, +97] | −40 [−134, +50] | −72 [−181, +35] |
| chain27 | chain31 | +101 [+9, +204] | +145 [+98, +210] | +174 [+101, +280] | +49 [−37, +142] | −44 [−161, +66] |
| chain27 | chain9 | +136 [+51, +243] | +197 [+157, +262] | +253 [+172, +372] | +250 [+166, +378] | −61 [−177, +47] |
| chain30 | chain31 | +143 [+57, +247] | +123 [+87, +176] | +92 [+11, +187] | +89 [+8, +174] | +20 [−90, +127] |
| chain30 | chain9 | +172 [+84, +290] | +273 [+228, +350] | +221 [+143, +332] | +287 [+216, +409] | −101 [−235, +27] |
| chain31 | chain9 | +127 [+20, +249] | +221 [+180, +293] | +116 [+39, +205] | +135 [+57, +237] | −94 [−239, +33] |

### Verdict on roster dependence

**Chain 30 over chain 25 is not roster-dependent at the agile/bash level.**

- g_agile − g_bash for this pair is −29 [−127, +78] in rr6, −15 [−87, +58]
  with chain 25 at T = 0.75, and +59 [−13, +144] in argmax. Against chain 26
  it is +47 [−36, +137]. All four intervals cover zero, and the signs disagree.
- The edge on bash rosters is at least +100 in every condition (lower bounds +100
  rr6, +118 T = 0.75, +100 argmax, +124 vs chain 26). The panel's reversal on
  bash rosters was roster strength: its per-roster numbers split the games by
  the roster chain 30 coached.
- Stunty rosters carry the smallest edge under both controls (+63 [+10, +119] at
  T = 0.75, +44 [−10, +102] in argmax), but not in rr6 (+120) or against chain 26
  (+133). Treat that as a lead.
- Across the 23 pairs of both runs, 2 have a g_agile − g_bash interval that
  excludes zero, both involving chain 9. About 1.2 would be expected by chance.

## Integrity

Every clause of the contract held for all 21,600 main-run games across 8 pairs,
and for the 1400 calibration games. There were no aborts and no duplicate tasks,
and every pair has exactly its planned count.

| check | result |
|---|---|
| natural endings | all MATCH_OVER (final_status 2), all at half 2 |
| hard counters | zero in every game: `illegal`, `projection_collision`, `error_episodes`, `rejected_submissions`, `precheck_collisions` |
| forwards per seat | exactly one per engine step for both seats: 26,815,164 forwards over 13,407,582 engine steps |
| policy decisions | seat decisions summed to the c_step count in every game |
| decision budget | at most 1097 decisions per game, against a budget of 4096; c_steps per game 231 to 1097 |
| calibration runs | 1400 games, all natural with zero hard counters |
| per pair | 3200 (chain25/chain26, chain30A/chain25A, chain30/chain25T) and 2400 (the rest), all complete |

## Unverified

- **CPU torch vs native parity** is still unproven. No rig-recorded parity
  fixture exists, and sampling uses torch's RNG, not curand. As in the round
  robin, only the distributions are comparable with native runs.
- **The noise floor is thin.** It has one replicate pair per recipe, three in
  total. Only chains 25 and 26 are at gamma 0.999. The training-seed spread of
  chain 30's own recipe is unmeasured; D399's chain 32 (chain 30's recipe at
  seed 44) is the direct replicate.
- **Control comparisons cross seed blocks.** The argmax and temperature games
  use the follow-up seed block, and the sample-mode baseline comes from rr6's
  block. They are independent samples, so their SEs combine in quadrature, with
  no common random numbers across the two.
- **Temperature matches the mean, not the shape.** T was chosen so chain 25's
  mean per-decision logprob matches chain 30's. The temperature tempers each
  head's conditional softmax, so the per-head entropy profile or the joint
  distribution need not match. T = 0.753 matches chain 30's rr6 value and
  T = 0.759 matches chain 30 in the calibration games; 0.75 was used.
- **Argmax mode** takes each head's conditional argmax. Its logprob figures are
  softmax scores of the chosen tuple, not the entropy of a deterministic policy.
- **The roster classes come from a heuristic rule** applied to the spec. The gap
  model assumes additive roster strength and a class-level policy gap, and
  ignores draws.
- **No held-out opponents.** The field is still in-family, and the scripted bots
  are not seated in the harness.

## Reproduce

```bash
# temperature calibration (chain 30 vs chain 25 at T, seed block 20500000)
for T in 0.74 0.77; do OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament \
  --checkpoint chain30=.play-artifacts/checkpoints/chain30/0000002999975936.bin \
  --checkpoint chain25T=.play-artifacts/checkpoints/chain25/0000002999975936.bin \
  --pair chain30,chain25T,400 --temperature chain25T=$T --workers 4 --seed0 20500000 \
  --out-dir .play-artifacts/tournaments/followup-20260915/calibration/T$T; done
# (0.80, 0.85, 0.90 at 200 games each)

# main follow-up run
CK=.play-artifacts/checkpoints; B=0000002999975936.bin
OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament \
  --checkpoint chain25=$CK/chain25/$B --checkpoint chain26=$CK/chain26/$B \
  --checkpoint chain9=$CK/chain9/$B --checkpoint chain16=$CK/chain16/$B \
  --checkpoint chain14=$CK/chain14/$B --checkpoint chain20=$CK/chain20/$B \
  --checkpoint chain30=$CK/chain30/$B --checkpoint chain30A=$CK/chain30/$B \
  --checkpoint chain25A=$CK/chain25/$B --checkpoint chain27A=$CK/chain27/$B \
  --checkpoint chain25T=$CK/chain25/$B \
  --player-mode chain30A=argmax --player-mode chain25A=argmax --player-mode chain27A=argmax \
  --temperature chain25T=0.75 \
  --pair chain25,chain26,3200 --pair chain30A,chain25A,3200 --pair chain30,chain25T,3200 \
  --pair chain9,chain16,2400 --pair chain14,chain20,2400 \
  --pair chain30,chain26,2400 --pair chain30,chain16,2400 --pair chain27A,chain25A,2400 \
  --workers 4 --seed0 20261615 --out-dir .play-artifacts/tournaments/followup-20260915/main

# statistics (both runs)
.venv/bin/python -m play_harness.tournament_stats --run-dir .play-artifacts/tournaments/followup-20260915/main \
  --json .play-artifacts/tournaments/followup-20260915/main/report-followup.json
.venv/bin/python -m play_harness.tournament_stats --run-dir .play-artifacts/tournaments/rr6-20260915 \
  --json .play-artifacts/tournaments/rr6-20260915/report-followup.json
```

The raw records, manifests and reports are under
`.play-artifacts/tournaments/followup-20260915/` (gitignored).
