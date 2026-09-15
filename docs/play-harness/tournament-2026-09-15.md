# Checkpoint round robin, 2026-09-15

**Question.** Do the scripted-bot exam gains hold up against learned opponents,
and which checkpoint is actually strongest?

**Answer.**

1. **The horizon gain holds.** Every gamma 0.999 checkpoint (chains 25, 27, 30
   and 31) beats both gamma 0.995 checkpoints (chains 9 and 14) head to head,
   winning 64.6% to 82.5% of decisive games. Every one of those intervals
   excludes 0.5 by a wide margin.
2. **The strongest checkpoints are chain 30 and chain 27, not chain 25.** They
   are tied with each other: chain 27 wins 0.517 of their decisive games
   [0.483, 0.551]. Both beat chain 25 head to head (0.648 and 0.640) and sit
   about 100 Elo above it. Bradley-Terry puts chain 30 first by 7.5 Elo, with
   P(rank 1) = 0.85. That ordering comes from their results against the rest of
   the field, not from their own games against each other.
3. **Chain 31 is third**, above chain 25 by 13.8 Elo (P = 0.98). Its games
   against chain 25 alone are a tie: chain 25 wins 0.481 [0.448, 0.515].
4. **The tournament ranking does not agree with the bot exam's decisions.** It
   roughly follows the contact champion cells (Kendall tau +0.60, Spearman
   +0.77). But the exam kept chain 25 as the frontier, and the tournament says
   chains 30 and 27 are about 100 Elo stronger. The exam ranked chain 31 below
   chain 9, and here chain 31 beats chain 9 in 0.693 of decisive games. The
   offense AWAY cell, whose drop vetoed chain 27 in D394, has no rank relation
   to tournament strength (tau -0.07).

This is a descriptive CPU-harness result (see "Unverified"), not a promotion. It
bears on the ladder's acceptance rule, which is a decision for the ledger.

## Method

- **Runner.** `play_harness/tournament.py` (85143e3); statistics in
  `play_harness/tournament_stats.py` (07bbd95). Both seats are `PolicySeat`s on
  the harness shim (`puffer/bloodbowl/bloodbowl.h`, obs-v6, exact-joint-v1),
  running CPU torch with the native gate kernel. Each seat runs one MinGRU
  forward on every engine c_step, including the steps where the other coach
  decides. Both seats get fresh recurrent state and a fresh sampling generator
  at each match.
- **Sampling.** `sample`, meaning exact joint sampling as trained and examined,
  with the torch RNG. `--mode argmax` exists but was not run.
- **Rosters.** Procgen as in training (random teams; skill-up 4 draws, up to 2
  skills, primary only), fixed by the engine seed.
- **Schedule.** 6 checkpoints, 15 pairs, 1400 games per pair: game indices
  0..699 on engine seeds 20260915 + i. Each index is played twice:
  - leg `A_home`: A is HOME, B is AWAY;
  - leg `B_home`: the policies swap sides, on the same engine seed and the same
    per-side sampling seeds.

  Rosters stay with the side, so a roster or dice advantage cancels across the
  two legs. Every pair uses the same 700 seeds (common random numbers). "A" is
  the first name in each pair row, in string order, which puts `chain9` last.
- **Compute.** Mac CPU only: 4 spawn workers, `OMP_NUM_THREADS=1` each, no GPU.
- **Integrity contract.** It is enforced inside each game and re-checked in the
  parent process. Before each step:
  - the engine is at a decision;
  - the waiting seat emits the singleton NONE tuple;
  - the deciding seat's tuple is inside exact support;
  - after the step, both seats' forward counts equal the engine step count.

  At the end, the match must stop at a natural MATCH_OVER. The engine's applied
  step count must equal the runner's, the match must use fewer than 4096
  decisions, and `illegal`, `projection_collision`, `error_episodes`,
  `rejected_submissions` and `precheck_collisions` must all be zero. Any
  violation writes `ABORTED.json` and terminates the pool.
- **Statistics.**
  - Per pair: A's W/D/L, TD per game, A's share of decisive games with a Wilson
    95% interval, and both side splits.
  - Ranking: a Bradley-Terry MLE over decisive games, on the Elo scale with mean
    0. Standard errors come from the observed Fisher information. A
    2000-replicate bootstrap resamples each pair's W/D/L for percentile
    intervals and rank frequencies.

## Cost

- **Pilot** (30 games, all 15 pairs, 4 workers): 0.75 s per game on one thread
  (0.52 to 1.04 s), about 614 c_steps per game, 1.22 ms per c_step with two
  forwards, and 4.6 games/s wall including pool start-up.
- **Full run:** 21,000 games in 4168.5 s wall (69.5 min) at 5.04 games/s.
  Games took 0.79 s each on average on one thread (median 0.78 s, max 2.07 s).
- **Choosing N.** The 60-90 min budget allowed about 21,000 games, so N = 1400
  per pair. That is well above the 300 floor, so the field stayed at all six
  checkpoints.

## Checkpoints

Copied read-only from the rig
(`/home/rache/bloodbowl-rl-qualification-candidate-10619e2/vendor/PufferLib/checkpoints/bloodbowl/<dir>/0000002999975936.bin`)
with their `.lineage.json` sidecars into `.play-artifacts/checkpoints/<chain>/`.
Every sha256 was verified after copying. The harness loads the native flat fp32
blob directly: `training/convert_checkpoint.cuda_to_torch` zero-fills the
biases, which is exact. Chain 25 was already loaded this way, so there is no
separate conversion step.

| chain | rig dir | sha256 | what it is |
|---|---|---|---|
| chain9 | 1787584031608 | 4344e588 | old frontier, gamma 0.995 |
| chain14 | 1787716871429 | dde7c98b | chain 9 continuation, 0.995 |
| chain25 | 1789256596423 | 109c55d3 | frontier, gamma 0.999 / lambda 0.95 (D392, D393) |
| chain27 | 1789308028008 | 67d62bee | chain 25 continuation, not accepted (D394) |
| chain30 | 1789413829676 | 41ecd998 | chain 25 recipe at replay ratio 1.0, flat (D397) |
| chain31 | 1789448891967 | 19424479 | 8 banks x 0.06 at 0.999, negative (D398) |

## Pairwise results

Rows are from A's side. "A win share" is A's wins over decisive games. The side
split columns give W/D/L from A's side with (A TD, B TD) per game.

| A | B | games | A W / D / L | A TD/g | B TD/g | decisive | A win share | 95% CI | A home W/D/L (A TD, B TD) | B home W/D/L (A TD, B TD) |
|---|---|---|---|---|---|---|---|---|---|---|
| chain14 | chain25 | 1400 | 281 / 489 / 630 | 0.801 | 1.215 | 911 | 0.308 | [0.279, 0.339] | 152/244/304 (0.83, 1.18) | 129/245/326 (0.77, 1.25) |
| chain14 | chain27 | 1400 | 212 / 447 / 741 | 0.632 | 1.236 | 953 | 0.222 | [0.197, 0.250] | 116/223/361 (0.63, 1.20) | 96/224/380 (0.63, 1.28) |
| chain14 | chain30 | 1400 | 163 / 469 / 768 | 0.702 | 1.386 | 931 | 0.175 | [0.152, 0.201] | 96/223/381 (0.72, 1.36) | 67/246/387 (0.68, 1.42) |
| chain14 | chain31 | 1400 | 259 / 455 / 686 | 0.888 | 1.384 | 945 | 0.274 | [0.247, 0.303] | 136/226/338 (0.89, 1.37) | 123/229/348 (0.88, 1.40) |
| chain14 | chain9 | 1400 | 431 / 479 / 490 | 0.980 | 1.077 | 921 | 0.468 | [0.436, 0.500] | 213/243/244 (0.99, 1.09) | 218/236/246 (0.97, 1.07) |
| chain25 | chain27 | 1400 | 301 / 565 / 534 | 0.668 | 0.909 | 835 | 0.360 | [0.329, 0.394] | 157/285/258 (0.68, 0.90) | 144/280/276 (0.65, 0.92) |
| chain25 | chain30 | 1400 | 315 / 504 / 581 | 0.806 | 1.068 | 896 | 0.352 | [0.321, 0.383] | 153/264/283 (0.81, 1.07) | 162/240/298 (0.80, 1.07) |
| chain25 | chain31 | 1400 | 411 / 546 / 443 | 0.983 | 1.009 | 854 | 0.481 | [0.448, 0.515] | 213/268/219 (1.04, 1.02) | 198/278/224 (0.93, 1.00) |
| chain25 | chain9 | 1400 | 600 / 471 / 329 | 1.082 | 0.791 | 929 | 0.646 | [0.615, 0.676] | 307/230/163 (1.11, 0.77) | 293/241/166 (1.05, 0.81) |
| chain27 | chain30 | 1400 | 428 / 572 / 400 | 0.906 | 0.840 | 828 | 0.517 | [0.483, 0.551] | 210/299/191 (0.93, 0.84) | 218/273/209 (0.89, 0.84) |
| chain27 | chain31 | 1400 | 565 / 533 / 302 | 1.074 | 0.801 | 867 | 0.652 | [0.619, 0.683] | 303/250/147 (1.10, 0.77) | 262/283/155 (1.05, 0.83) |
| chain27 | chain9 | 1400 | 680 / 483 / 237 | 1.219 | 0.686 | 917 | 0.742 | [0.712, 0.769] | 352/238/110 (1.26, 0.68) | 328/245/127 (1.18, 0.69) |
| chain30 | chain31 | 1400 | 588 / 492 / 320 | 1.256 | 0.966 | 908 | 0.648 | [0.616, 0.678] | 316/243/141 (1.29, 0.94) | 272/249/179 (1.23, 0.99) |
| chain30 | chain9 | 1400 | 742 / 438 / 220 | 1.349 | 0.731 | 962 | 0.771 | [0.744, 0.797] | 377/219/104 (1.41, 0.75) | 365/219/116 (1.29, 0.71) |
| chain31 | chain9 | 1400 | 639 / 478 / 283 | 1.278 | 0.854 | 922 | 0.693 | [0.663, 0.722] | 330/230/140 (1.29, 0.86) | 309/248/143 (1.26, 0.85) |

The same results as a matrix: the decisive-game win share of the row
checkpoint against the column checkpoint, in ranking order.

| row vs column | chain30 | chain27 | chain31 | chain25 | chain9 | chain14 |
|---|---|---|---|---|---|---|
| chain30 | | 0.483 | 0.648 | 0.648 | 0.771 | 0.825 |
| chain27 | 0.517 | | 0.652 | 0.640 | 0.742 | 0.778 |
| chain31 | 0.352 | 0.348 | | 0.519 | 0.693 | 0.726 |
| chain25 | 0.352 | 0.360 | 0.481 | | 0.646 | 0.692 |
| chain9 | 0.229 | 0.258 | 0.307 | 0.354 | | 0.532 |
| chain14 | 0.175 | 0.222 | 0.274 | 0.308 | 0.468 | |

TD per game over all 7000 games of each checkpoint (for / against):

| chain30 | chain27 | chain31 | chain25 | chain9 | chain14 |
|---|---|---|---|---|---|
| 1.180 / 0.822 | 1.069 / 0.725 | 1.088 / 1.011 | 0.951 / 0.916 | 0.828 / 1.181 | 0.801 / 1.260 |

Draws are 31% to 41% of games per pair. Home sides win 0.516 of all decisive
games [0.508, 0.525] and score 1.004 TD per game against 0.968 for away sides.
The side splits within each pair are consistent with that small home edge.

## Ranking

Bradley-Terry over the 13,579 decisive games, on the Elo scale with mean 0:

| rank | checkpoint | Elo | SE (Fisher) | bootstrap 95% | P(rank 1) | rank frequency | decisive W-L | score rate |
|---|---|---|---|---|---|---|---|---|
| 1 | chain30 | +112.5 | 4.7 | [+103.2, +121.6] | 0.852 | 1st 0.852, 2nd 0.148 | 3079-1446 | 0.617 |
| 2 | chain27 | +105.0 | 4.8 | [+95.8, +114.5] | 0.148 | 2nd 0.852, 1st 0.148 | 2948-1452 | 0.607 |
| 3 | chain31 | +18.0 | 4.5 | [+9.4, +27.0] | 0.000 | 3rd 0.980, 4th 0.020 | 2390-2106 | 0.520 |
| 4 | chain25 | +4.2 | 4.5 | [-4.5, +13.2] | 0.000 | 4th 0.980, 3rd 0.020 | 2257-2168 | 0.506 |
| 5 | chain9 | -104.0 | 4.6 | [-113.2, -95.3] | 0.000 | 5th 1.000 | 1559-3092 | 0.391 |
| 6 | chain14 | -135.8 | 4.8 | [-145.7, -126.9] | 0.000 | 6th 1.000 | 1346-3315 | 0.359 |

The ranking splits into three tiers:

- **Top:** {chain30, chain27}.
- **Middle:** {chain31, chain25}.
- **Bottom:** chain9 above chain14. Chain 9 beats chain 14 in 0.532 of decisive
  games; chain 14's share of 0.468 has the interval [0.436, 0.500].

The top two are tied in their own games, and so are the middle two. The
bootstrap orders within a tier with P = 0.85 (top) and 0.98 (middle).

**Robustness.**

- **Model fit.** Bradley-Terry predicts all 15 pairwise shares within |z| <
  1.98. Summing z² gives 20.3 on 10 degrees of freedom (p = 0.026; deviance
  20.3, p = 0.027): a mild misfit with no intransitive cycle. The largest
  residuals are chain27 vs chain9 (predicted 0.769, observed 0.742) and chain27
  vs chain31 (0.623 vs 0.652). (`bt_misfit`, committed in efe339e.)
- **Dependence between games.** Games share seeds, so a seed-cluster bootstrap
  resamples the 700 seeds jointly across all pairs and both legs
  (`seed_cluster_bootstrap`, committed in dfb7f4a; 2000 replicates). Its pair
  intervals match the Wilson intervals within 0.006 at every endpoint, and its
  Bradley-Terry Elo SEs are 4.0 to 5.0. **Correction:** this doc first gave the
  leg correlation as -0.087. That is the Pearson correlation over all pairs
  pooled, without centring within each pair. Centred within each pair
  (`leg_correlation`, committed in ec3d633), A's score across the two legs of a
  seed correlates at **-0.207**, a roster or side effect. The negative
  dependence means treating games as independent is conservative: the
  seed-cluster intervals are about 10% narrower than Wilson. The seed-cluster
  bootstrap gives P(chain30 > chain27) = 0.87 and P(chain31 > chain25) = 0.98.
- **Follow-up.** Replicate noise floor, argmax and temperature controls, and
  roster stratification are in `tournament-followup-2026-09-15.md`.

## Against the bot exam

Scripted-bot exam champion cells (contact AWAY / contact HOME / offense AWAY).
The chain 9 row is the chain 9 + chain 16 pooled frontier, not chain 9 alone.

| chain | contact AWAY | contact HOME | offense AWAY | exam mean | exam rank (contact cells and mean) | tournament rank |
|---|---|---|---|---|---|---|
| chain27 | 0.603 | 0.533 | 0.551 | 0.562 | 1 | 2 |
| chain30 | 0.5705 | 0.5305 | 0.586 | 0.562 | 2 | 1 |
| chain25 | 0.568 | 0.5055 | 0.5895 | 0.554 | 3 | 4 |
| chain9 | 0.537 | 0.492 | 0.571 | 0.533 | 4 | 5 |
| chain31 | 0.515 | 0.484 | 0.539 | 0.513 | 5 | 3 |
| chain14 | 0.5035 | 0.4435 | 0.5755 | 0.508 | 6 | 6 |

Rank agreement between tournament Elo and each exam read:

- both contact cells give the same order: Kendall tau +0.60, Spearman +0.77;
- the three-cell mean gives the same order again: +0.60 / +0.77, with a
  bootstrap tau interval of [0.60, 0.73]. Chains 27 and 30 tie exactly on the
  mean (both cells sum to 1.687), and the contact cells order them 27 first;
- offense AWAY: tau -0.07, Spearman -0.09.

**Verdict: partial agreement on order, disagreement on the decisions.**

**Where they agree.**

- Gamma 0.999 beats gamma 0.995.
- Chains 27 and 30 rank above chain 25.
- Chain 14 is last.

**Where they disagree.**

1. **Size of the gap above chain 25.** On the contact cells, chains 27 and 30
   are only +0.0025 to +0.035 above chain 25. D394 did not accept chain 27, and
   D397 read chain 30 as flat. Head to head, both are about 100 Elo above chain
   25, winning about 64% of decisive games. That is as large as chain 25's own
   gain over chain 9 (0.646, about 108 Elo), which D393 accepted as the new
   frontier. Against learned opponents, a further 3B steps of continuation and
   4x gradient steps per epoch each bought as much as the horizon change did.
2. **Chain 31.** The exam puts it below chain 9 on all three cells, and D398
   read it as negative against chain 25. Here it beats chain 9 in 0.693 of
   decisive games, and it is tied with or slightly above chain 25.
3. **The offense AWAY veto.** The offense AWAY cell drop that rejected chain 27
   carries no rank information about strength against these opponents. Chain 27
   concedes the fewest TDs in the field (0.725 per game) and beats chain 25 in
   0.640 of decisive games.

A contrast from the gamma 0.995 lineage: chain 14 continued chain 9 for 3B more
steps and did not gain head to head. It sits slightly below chain 9 (0.468,
interval [0.436, 0.500]). At gamma 0.999 the continuation gained about 100 Elo.

## Integrity

Every clause of the contract held for all 21,000 games (15 pairs x 1400). The
run had no aborts and no duplicate tasks.

| check | result |
|---|---|
| natural endings | all MATCH_OVER, all at half 2 |
| hard counters | zero in every game: `illegal`, `projection_collision`, `error_episodes`, `rejected_submissions`, `precheck_collisions` |
| forwards per seat | exactly one per engine step for both seats in every game |
| policy decisions | seat decisions summed to the c_step count |
| volume | 26,184,518 forwards over 13,092,259 engine steps; c_steps per game 233 to 1100 |
| decision budget | at most 1100 decisions per game, against a budget of 4096 |

## Unverified

- **CPU torch vs native parity is not proven.** No rig-recorded parity fixture
  exists yet (design section 9, step 2). The harness uses the native gate
  formulas, which differ from the torch kernel by at most 3.1e-5 on chain 25
  logits. That observations from the Mac shim match the rig's gcc build byte
  for byte is also unchecked.
- **Sampling RNG.** Sampling uses torch's RNG, not curand, so only the
  distributions of these results are comparable with native runs, never
  individual games. Argmax play was not run.
- **Opponent independence.** All four gamma 0.999 chains descend from the chain
  9 warm start, and chain 27 descends from chain 25. The training frozen banks
  (pool identities d67d527b and 6ffb955b) were not checked for lineage overlap
  with these six checkpoints. "Learned opponents" means other trained
  checkpoints, not a verified held-out population.
- **Seeds.** Each chain has one training seed (chain 25's replicate chain 26 was
  not included), and the tournament used one seed list. The exam cells are
  means over two exam seeds; the tournament was not repeated.
- **Exam comparability.** The exam's roster distribution and harness differ from
  this CPU shim, and the chain 9 exam row is pooled with chain 16.

## Reproduce

```bash
OMP_NUM_THREADS=1 .venv/bin/python -m play_harness.tournament \
    --games-per-pair 1400 --workers 4 --seed0 20260915 \
    --out-dir .play-artifacts/tournaments/rr6-20260915
.venv/bin/python -m play_harness.tournament_stats \
    --run-dir .play-artifacts/tournaments/rr6-20260915
```

Raw per-game records are in
`.play-artifacts/tournaments/rr6-20260915/games.jsonl` (gitignored), next to
`manifest.json` (harness head 07bbd95, torch 2.14.0), `COMPLETE.json` and
`summary.json`. The runner resumes from `games.jsonl` and refuses to reuse an
output directory whose manifest differs.
