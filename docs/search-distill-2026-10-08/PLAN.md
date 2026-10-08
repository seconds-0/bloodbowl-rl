# Search distillation, Test 1: plan (draft of 2026-10-08, not registered)

**Status: a draft for the operator. Nothing here is registered, no game of it has been played, no cloud resource exists for it, no tool in section 7 exists yet, and no outside reviewer has read it. It is Test 1 of `/Users/alexanderhuth/Code/bb-opt-build/docs/plans/exploration-in-training-design-2026-10-07.md` (section 4), with the five requirements of that study's section 8 item 2 applied. It adopts nothing. The measurements made while writing it are in `/Users/alexanderhuth/Code/bb-opt-build/docs/search-distill-2026-10-08/NOTES.md`. All of them are exploratory, and two of them are small fits on data that had already been seen.**

Short names used below.
- **C**: chain 55 (`f6ba3b449bf0cec15e37ba47b32b097dd513ee7dba3241b16ad90dd2a0675e0b`) played under the m1 mask, sampling at temperature 1.
- **S**: C with the search seat at the setting D430 registered and D434 read (+45.5 and +45.3 decisive-Elo over C against chain 37 and chain 46, at 48 times the cost).
- **F**: the fine-tuned copy of chain 55 this plan produces, played under m1 at plain speed.
- **A deviation root**: a decision in the seat's scope where the seat's rule deviates. **The label** there is the action the seat would play.

## 0. Shape of the plan, and where it departs from the brief

One question. Four measurements in order of weight (fit, held-out roots, a fresh screen, a match gate) on one fine-tuned checkpoint, chosen without the test games or the match games. A ladder that can stop for $0 (the 87 labels already on disk), then for about $0.40 (a fit check on about 400 new labels), before the full run of about $8.

Departures from the brief, each argued where it is used:

1. **A free step comes first.** The 6,000 roots screened on 2026-10-07 (seed block 29100000, 87 deviation roots, each already judged on 128 fresh rollout pairs) regenerate with their states on the Mac: all 6,000 screen records were reproduced in under four minutes (NOTES, measurement 5). They are seen data, so they prove the tools and set the optimiser's ranges, and nothing more.
2. **Cost.** The brief's "1,350 roots in 412 s" is a Mac figure. A droplet process with all eight busy is about six times slower per root (1.84 s against 0.31 s). 300,000 roots cost about $3.80, not about $1 (section 6).
3. **The "behaviour cloning elsewhere" term needs two changes.** It must leave out in-scope decisions that were not screened: at about 1.3% of them the seat would deviate, so cloning the original there teaches the opposite of the label. And it should include decisions outside the seat's scope (the declaration, everything inside an activation), which cost no rollouts and share the same output layer (section 3).
4. **Probability mass on the search's action is not enough to read generalisation.** A fine-tune can raise it by changing its choice wherever a pattern matches. The registered held-out statistic is the share of the seat's one-step evaluator gain that F captures, net of what F's other changes cost, judged on fresh rollouts (section 4, ii).
5. **Which parameters are trained matters more than the learning-rate grid.** Two recipes are declared: the policy rows of the output layer alone (R1), and the whole policy path on 64-step windows (R2). An exploratory fit of R1 on the 87 seen labels fitted them and changed the top action at about a tenth of held-out in-scope decisions (section 3). That is 87 labels and settles nothing, but it is why R2 is in the plan from the start and why unintended changes are valued with rollouts and not only counted.
6. **The gate is four times D430's size.** At 3,200 games a pair the F minus C interval is about plus or minus 19 Elo, which cannot tell half of the search's gain from zero. Plain games are cheap, so 12,800 games a pair (about plus or minus 9.5) cost about $2.50 (section 4, iv).
7. **Two ledger entries, not one.** The gate's plan must name F by hash, and F does not exist until the fine-tune ends. Entry A registers this plan. Entry B fixes F's hash and the gate's plan file before any gate game, as D438 did for chain 60's gate.

## 1. The question, and the claim it can support

**Question.** If states are labelled with the search seat's choice and a copy of chain 55 is fine-tuned toward those labels, does the copy (a) learn the labels, (b) reproduce the seat's choices on games it was not trained on, and (c) play stronger than C in fresh games at plain speed?

**The claim is about the recipes tested.** "Chain 55, fine-tuned by a recipe of section 3 on labels made by the D430 seat at roots of C's own self-play, does or does not (a), (b), (c), against chain 37 and chain 46."

**What a pass would mean.** (c) read Positive with (b) read Generalises: the seat's deviations carry information a plain policy can absorb from a few thousand labels and use at no cost in play. That is the condition for building search as a teacher off the rig.

**What a pass would not mean.**
- That an on-rig exploration scheme (candidate (g) of the study) would learn the same thing. It learns from single noisy samples inside PPO, not from labels chosen on 64 rollouts.
- That the gain survives further PPO training, or grows when the loop is repeated (label F, distil again).
- That F can be a warm start. F is outside the trainer's lineage (section 3, "Writing F back").
- Anything about another checkpoint (chain 58 and chain 60 need their own labels and gate), a stronger opponent, or a person.
- That any single deviation is right. D434's limits travel with this plan: the seat's evaluator is the shaped reward plus the value head, and the gates show that acting on it wins more games against two opponents.
- That F is defined without m1. Under m1 END_TURN is never offered while a player can be activated, so the fine-tune never trains that choice.

**What a fail would mean.** That these recipes, at this label count, did not do it. Section 5 names which part failed: did not fit, fitted and did not generalise, generalised and did not win.

**What a fail would not mean** (the review's item 2). That the tail cannot be learned by an online scheme, by another distillation recipe, from more labels, or from labels made on the student's own games. A labelled fine-tune can fail for reasons an online scheme does not share: label noise, coverage, the optimiser and KL settings, recurrent state, distribution shift. The plan measures the first four so that a fail says which one it was.

## 2. Data

**Checkpoint, mask and play.** C in both seats: chain 55 under m1, temperature 1, kick-off starts, reward manifest `r0_poss_half` (`433c792018acdc01f8c7168e824c9389bf99df2307d3260283b7877df3f69d5c`), gamma 0.999. Seat A is HOME in even games and AWAY in odd games. Seat B is the same network with its sampling seed offset by one stride. This is the game loop of `/Users/alexanderhuth/Code/bb-harness-search/tools/search_probe_diag.py` (`Harness.play_game`), which made the D2 counts. Harness: branch `feat/search-probe-20261007` at `5ab3ab6e195afbb717d7e0e7e62361a3b548fdd6`. Between D430's commit `06f0a5f` and this one only `tools/gate_acceptance.py` and its test changed (`git diff --stat`), so the seat and the rollout code are the gate's.

**Why self-play roots.** They are where D2 was checked (0 false deviations of 87) and where the opponent model in the rollouts is exact. Chain 37 and chain 46 stay held out as opponents: no label comes from a game against them.

**Roots.** Seat A's decisions in the seat's scope: class `turn` (an ACTIVATE is legal after masks) and class `after_declare` (the first own decision after the own DECLARE), with two or more legal actions after masks. Never the DECLARE itself. Per game, 15 roots per class, a uniform sample of that game's searchable decisions of the class (a reservoir, as in the D2 batches). Each root carries the weight (searchable decisions of the class in the game) / (roots kept).

**Why 30 roots a game and not every decision.** A plain game costs about four roots of screening, so games are nearly free. 10,000 games with 30 roots each give 10,000 independent clusters and many roster pairings. 1,550 fully screened games would give the same number of roots in a sixth of the clusters.

**The screen at a root, and the label.** Exactly the seat's computation at that decision.
- a0 is the action plain play sampled.
- The candidates are a0 and the three other legal joint actions with the highest policy probability (ties in packed order).
- 16 rollouts each through `play_harness.search.Rollouts.evaluate` on common random numbers, both sides played by chain 55 under m1, stopping at the end of A's team turn, the end of the match or 200 steps.
- Seeds from A's sampling seed, the engine step and the rollout index. Those are the seeds the seat would use at that step.
- The label rule is `play_harness.search.deviation(returns, 0.10)`: deviate to the best alternative when its paired mean gain over a0 exceeds 0.10 and two standard errors, the standard error floored as registered. A deviation root's label is that alternative.
- A root where any rollout ends on the inherited decision cap is a cap rejection, as for the seat. It is counted and enters no loss and no statistic.

**a0 is the sampled action, on purpose.** At a root where a0 was an unlikely sample and the search's choice is the policy's usual action, the label teaches nothing new. Every root stores the original policy's log-probability of a0 and of the label, and every statistic of section 4 is also printed for the "new" labels only (original probability of the label below 0.01). In the seen screens a0 is the policy's top action at 85 of the 87 deviation roots, 83% of the labels have an original probability below 1e-6 and 93% below 0.01, and the label is the most probable other action at 36 of the 87 (second at 24, third at 27). So the label is not simply the runner-up.

**Labels judged on independent rollouts.** Every deviation root gets 128 fresh rollout pairs of a0 against the label (rollout indices 1000 to 1127, never used by the screen, same horizon), run while its clone is still held. Its fresh gain is the mean over pairs. A label is **false** when its fresh gain is at or below zero (D2's definition) and **confirmed** when its fresh gain exceeds two of its own standard errors. The fine-tune trains on every label the rule produced, false ones included, because that is the seat that was gated. Every held-out statistic uses the fresh gains, never the 16 rollouts that selected the label.

**Decisions outside the scope.** Per game, 64 of seat A's other decisions with two or more legal actions (the DECLARE, and everything inside an activation), a uniform sample with weights as above. The seat never searches there, so its policy there is the original policy exactly. They need no rollouts.

**A decision inside a kick-off Blitz turn stays a root, flagged.** D437 found that ending the kicking team's free turn does not advance the completed-turn counter, so a rollout from there runs to the end of the team's next real turn. For the END_TURN probe that broke an arm whose definition needed exactly one team turn, and D439 removed such decisions. Here the choice goes the other way, for three reasons.
- The label is by definition what the registered seat does, and the seat D434 read searched those decisions with that longer horizon. A student trained without them would imitate a seat nobody gated.
- Nothing in this plan needs the horizon to be one team turn. The fresh judgment uses the same horizon as the screen, so "false" keeps its meaning.
- They are few: 27 of the 6,000 seen roots and none of the 87 seen labels; 4 of 401 in-scope decisions in two games played here.

Every root records `kickoff_turn` by D439's stack rule, each game counts them, every statistic is printed with and without them, and the reading uses all roots. The wide rehearsal (section 7) must meet them.

**Recurrent state.** Not stored, recomputed. Each game stores its engine seed, both sampling seeds and its full action trail. Replaying a trail through the engine regenerates both observation rows at every step (measured: 0.02 s a game, bytes equal to the original game's). The dataset tool runs the network over seat A's row from the first step of the match, which is how the seat came by its state (`PolicySeat`: one forward per engine step, zero state at the start). Checks:
- the replay's final digest equals the game's;
- the sha256 of the regenerated observation bytes equals the one the droplet recorded;
- at every root the recomputed a0 and candidate list are the recorded ones, and a0's log-probability agrees to 1e-3 (D435 saw 0.0012 between Mac and droplet on a whole game's sum).

For R1 the state at a root does not depend on the trained weights at all. For R2 see section 3.

**What is stored**, per shard, under the git-ignored `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/<run>/<shard>/`:
- `games.jsonl`: engine seed, A's side, sampling seeds, rosters, the action trail (team and tuple per engine step), its sha256, the sha256 of each observation row's byte stream, the final digest, the score, decisions per class and stratum, kick-off turn decisions, the integrity list.
- `roots.jsonl`: game, engine step, class, weight, `kickoff_turn`, the candidate tuples and their original log-probabilities, a0's rank, the 4 x 16 returns, stops, the rule's gain and standard error, the deviation flag; for a deviation root the 2 x 128 fresh returns and stops.
- `other.jsonl`: game, engine step and weight of each sampled out-of-scope decision.
- `COMPLETE.json`, `SHA256SUMS`, the plan copy.

**Size.** 10,000 games, 300,000 roots. At the measured deviation share (1.34% in D434, 1.46% [1.16, 1.78] in the screens) that is 4,000 to 4,400 labels, about 0.42 a game.

**Split, by game.** With `i = engine seed - 26000000`, the group is `(i // 2) % 10`: 0 to 6 train (7,000 games, about 2,900 labels), 7 validation (1,000 games, about 420), 8 test (1,000, about 420), 9 reserve (1,000, about 420). Dividing by two first keeps one HOME game and one AWAY game of seat A together, so every split has both sides. No game's roots are in two splits. The reserve is not read under this plan. It exists so that a later entry (another recipe, or more labels) has games no model was chosen on.

**Seed blocks.** All found unused on 2026-10-08 by searching `DECISIONS.md`, `docs/` and `runs/` of `/Users/alexanderhuth/Code/bb-opt-build`, the docs, tools and logs of the two harness worktrees, and every plan and manifest under `/Users/alexanderhuth/Code/bb-play-harness/.play-artifacts/tournaments`: no eight-digit number starting 252, 260, 261, 270, 271, 280, 2998 or 2999 occurs.

| Use | Engine seeds |
|---|---|
| Labels, first step (milestone 1) | 26000000 to 26000999 |
| Labels, the rest (milestone 2) | 26001000 to 26009999 |
| Fresh screen of F and of C | 27000000 to 27000666 |
| Gate | 25200000 to 25206399 |
| Rehearsals and smokes (never evidence) | 29980100 to 29989999 |
| Milestone 0 (seen data, never evidence) | 29100000 to 29100199 |

Blocks in use near these: gate blocks 20300000 to 22900000 and 25100000; probe blocks 29000000, 29100000, 29200000 and 29900000 to 29970000. Seeds 29980000 to 29980002, 29980010 and 29980011 were played plain, without rollouts, for the measurements in NOTES.

## 3. The fine-tune

**Target.** The seat's own policy: the label at a deviation root, the original policy everywhere the seat would not change it.

**Loss.** Over the loss set of the training games, with each example's weight w from section 2:

`L = [ lambda * sum over deviation roots of w * (-log p(label)) + sum over the other screened roots of w * KL(p0 || p) + sum over out-of-scope decisions of w * KL(p0 || p) ] / (sum of w)`

where p is the fine-tuned policy's exact joint distribution at the decision and p0 is chain 55's. With lambda = 1 this is maximum-likelihood cloning of the seat on the decisions seat A meets. R2 adds `mu * mean of (V - V0)^2` over the same decisions.

**Not in the loss:** in-scope decisions that were not screened (their label is unknown, and at about 1.3% of them the seat deviates), cap-rejected roots, and any decision with one legal action.

**A caution about the KL term.** Chain 55 is saturated at about 70% of decisions, so KL(p0 || p) is nearly `-log p(top action)` and has almost no gradient until the fine-tuned policy has already moved mass. It is a barrier, not a pull, and it only stands where there is a training example. The preview below shows what that costs. This is why "agreement with the original" is reported as the probability of acting differently (total variation) on games the fine-tune never saw, and valued with rollouts where it changes.

**The three heads.** The policy samples type, then argument given type, then square given both, each a softmax over the values the support allows after that prefix (`play_harness/policy.py` `select_joint`). The loss uses exactly that factorisation on the support after m1: `log p(tuple)` is the sum of the three conditional log-probabilities, as `play_harness.search.joint_log_probabilities` computes it, and the KL is taken over the tuples of the support. Inactive heads are singletons and contribute zero. Under m1 the support never holds END_TURN beside an ACTIVATE, so that choice is never trained. A test holds the training tool's log-probabilities equal to `joint_log_probabilities` and to the log-probability `select_joint` returns.

**Recipe R1: the policy rows of the output layer only.** Trained: `decoder.decoder.weight`, 454 x 512 = 232,448 weights. Frozen: the encoder, the three MinGRU layers, the value row, every bias (the native blob has none; all are zero).
- The decoder's input h at a decision does not depend on the trained weights. So the recurrent state at every root is exactly chain 55's for every setting, h is computed once and cached, and training is a linear model on 512 features.
- The critic and the trunk are byte for byte chain 55's. A search seat on F uses the same value head.
- The loss is convex in the trained weights.
- It asks one thing: whether chain 55's last layer already holds, linearly, what distinguishes a deviation root.

**Recipe R2: the whole policy path.** Trained: the encoder, the three MinGRU layers and `decoder.decoder.weight`. Frozen: the value row and every bias. Added: the value anchor with mu = 100.
- **State.** Each training window is 96 consecutive observations of the seat's own row, run from a zero state with gradients through the window. The loss is taken at loss decisions in its last 32 steps, so each has at least 64 steps of history. In a window every out-of-scope decision is scored, not only the sampled ones, since they need no label. This is how the trainer itself trains (64-step segments from a zero state; study section 1 item 7).
- **Why windows are enough.** Measured on two plain games: with a 64-step window from zero, chain 55's top action equals its full-history top action at all 1,233 multi-action decisions, and the mean total variation is 0.0001 (16 steps: 99.9%; one step, no history: 74%). Full-game backpropagation is not needed.
- **That measurement is about chain 55, not about F.** A setting is eligible only if, on validation decisions, F's top action from a 64-step window equals F's full-history top action at 99% or more, and its mean absolute value change from chain 55 is at most 0.005 (the seat's threshold is 0.10). Every reported number uses the full-history state, the way F plays.
- **A pass** is every training label's window plus ten other windows per label, drawn uniformly from the training games' steps.

**The exploratory preview of R1** (NOTES measurement 5; seen data; 66 training labels in 150 games, 21 labels in 50 held-out games; not evidence):
- R1 fits: training label probability 0.72 at lambda 1, 0.84 at lambda 4, 0.94 at lambda 16, from 0.015.
- The fit is bought with wide change elsewhere. On the held-out games the top action changed at 9% to 13% of in-scope roots that were not labels and at 4% to 8% of out-of-scope decisions. A third of the changed roots were ones the original policy was sure of (5% of all such roots changed; 41% of the open ones).
- The 21 held-out labels moved from 0.018 to between 0.05 and 0.14. That is too few to read.
- Training on half the games gave the same held-out change (12% against 12%), so in this one small comparison more games did not shrink it. A logit anchor lowered it only by giving up the fit in step.
- What I take from it: R1 can memorise; whether more labels turn memorising into a rule is exactly what the test measures; R2 must be ready; and the count of changed decisions cannot be the judge, because a change at a near-tie costs nothing and a change at a sure decision may cost a lot.

**Declared settings (provisional until milestone 0; frozen in Entry A; not changed after).**

| Recipe | lambda | Learning rate (Adam) | Passes |
|---|---|---|---|
| R1 | 1, 4, 16 | 0.001 | 30 |
| R2 | 1, 4 | 0.00001 and 0.0001 | 10 |

Seven settings in all. Minibatch 8,192 examples for R1 and 64 windows for R2, generator seed 0, one thread. A rerun must reproduce the blob byte for byte on the same machine. R1's rate comes from the preview (0.001 reaches a training label probability of 0.72 in 400 full-batch steps, 0.01 reaches 0.80 in 100). R2's rates are guesses until milestone 0 runs R2 on the seen data.

**The stop inside a setting: the score J, on validation games, no rollouts.**

`J = q * M * g - 0.016 * U`

- M: weighted mean probability the setting gives the label, over validation deviation roots.
- U: weighted mean total variation between the setting's policy and chain 55's, over validation loss decisions that are not deviation roots (screened roots and sampled out-of-scope decisions together).
- q: weighted share of deviation roots among validation loss decisions (about 0.004). g: mean fresh gain of validation labels (about 0.15).
- 0.016 is the study's measured mean cost of an alternative the policy all but rules out (study section 2C). It stands in for the price of an unintended change. It was measured at in-scope decisions only, and it ignores that many changes sit at near-ties. J picks a pass. It is not a result.

**Choosing the winner without the test games or the match games.**
1. Every setting is trained on the training games and keeps its pass with the highest J.
2. R2 settings that fail the eligibility checks above are dropped.
3. For each remaining setting's kept pass, **the captured share** (section 4, ii) is measured on the validation games with fresh rollouts (indices 3000 to 3063). This replaces J's assumed price with a measured one for the choice that matters.
4. The winner is the setting with the highest validation captured share. Ties: R1 before R2, then the smaller lambda.
5. **The validation bar:** the winner's validation captured share is 0.10 or more. If it is not, nothing is taken to the test games (Reading 2, rule 2).
6. The winner's recipe, setting, pass, blob hash and validation numbers are written to `SELECTION.json`. Its sha256 is what unlocks the test games. The test and reserve files are never given to the training tool. The gate's and the fresh screen's seeds have not been played at that point.

**Fit, and overfitting.**
- **Capacity check** (the review's "check that the fine-tune fits its training roots"): for each recipe, the largest-lambda setting's weighted mean label probability on training deviation roots, at its last pass. **FIT** is 0.80 or more. A recipe that is NOT FIT cannot be read on generalisation at all.
- **Overfitting** is seen three ways: the gap between training and validation label probability, and between training and validation U, at every pass of every setting; the stop on validation J; and a learning curve, the winner's setting retrained on the first eighth, quarter and half of the training games, with validation M, U and J at each. The learning curve is a registered diagnostic and feeds one consequence (section 5).
- Validation numbers are used for the stop and for the choice, so they are optimistic. Only the test games give the reading.

**Writing F back as a blob.** Checked on the Mac (NOTES measurements 1 and 2):
- `training/convert_checkpoint.py` `cuda_to_torch` then `torch_to_cuda` on chain 55's blob is byte-identical, and every bias is zero. A blob with only `decoder.decoder.weight` changed differs from chain 55's in floats 1,424,384 to 1,656,831 and nowhere else; the value row (1,656,832 to 1,657,343) is untouched.
- `play_harness.policy.load_checkpoint` requires 16,066,560 bytes and a `.lineage.json` sidecar whose `compatibility` block says obs-v6, observation version 6, exact-joint-v1, hidden 512, 3 layers, and whose `checkpoint.sha256` is the blob's. It checks nothing else. Without a sidecar it refuses.
- `play_harness.tournament` and `tools/droplet_tournament.py` take `name=path` and need the sidecar beside the blob. `tools/gate_acceptance.py` compares the manifest's sha256 for each player name with the plan's. A test blob with such a sidecar played four tournament games on the Mac under m1 against chain 37 (in an eight-game run beside chain 55), and the manifest recorded its hash and its sidecar's `producer` block. The acceptance tools were not run on it.
- **The sidecar F needs:** `schema_version` 1; `checkpoint` (bytes, sha256); `compatibility` (the six fields chain 55's sidecar has); `ancestry` with `initialization: "offline-distill"`, `eligible: false`, `qualification_only: true`, the parent's blob and sidecar hashes (`f6ba3b44...`, `15708a86...`) and `valid_under_masks: ["m1"]`; `producer` with the plan hash, `SELECTION.json`'s hash, the recipe and setting, the tool hashes, the torch version and the seed. It has no `implementation` block, because no trainer build produced it.
- **F is not a warm start.** The trainer's `/Users/alexanderhuth/Code/bb-opt-build/tools/checkpoint_lineage.py` refuses that sidecar (measured: "implementation must be an object"; by its code an initialization outside fresh, lineage-v6 and bridge is refused too). That is intended. Making a distilled checkpoint eligible ancestry is a lineage decision for its own entry.
- F is kept at `/Users/alexanderhuth/Code/bb-opt-build/runs/search-distill-2026-10-08/checkpoints/c55d1/0000002999975936.bin`, outside the harness's checkpoint store, so `discover_checkpoints` never offers it as a chain.

## 4. Evaluation, in order of weight

Intervals are 95% percentile bootstraps over games (engine seeds), 2,000 replicates, generator seed 0, unless the gate's own script is named.

**(i) Fit on training roots.** The capacity check of section 3 for both recipes, and for the winner: training label probability (mean, and the share at 0.5 or more) and training total variation at the other loss decisions. No size question: it is a fact about the fit.

**(ii) Held-out roots (the test games, opened once, for the winner).** F's policy at each test decision is computed with F's own state, run from the first step of the game over the regenerated observations. The game is C's, so this is F's answer to the states C met.
- **T_mass:** weighted mean probability F gives the label at test deviation roots. Also for new labels only, confirmed labels only, by class, by deviation type, and without kick-off turn roots. With about 420 test labels the interval is about plus or minus 0.05.
- **T_tv:** weighted mean total variation between F and chain 55 at the other test loss decisions, for screened roots and for out-of-scope decisions separately, the share of decisions whose top action changed, and that share among decisions the original policy was sure of (top probability 0.999999 or more).
- **The captured share, the registered statistic.** For each screened test root r (cap rejections left out):
  - the seat's value `D_r` is the label's fresh gain at a deviation root and 0 elsewhere;
  - F's value `Q_r` is `sum over a in A_r of (pF(a) - p0(a)) * (G(a) - G(a0))`. `A_r` holds every action whose probability differs by 0.01 or more between F and chain 55 (at most the eight largest differences). G is the mean return over 64 fresh rollouts on common random numbers (indices 2000 to 2063) under chain 55's evaluator: chain 55 plays both sides under m1, same horizon and cut-off as the seat. Where the label is in `A_r` its 128-pair fresh gain is used. Where `A_r` is empty `Q_r` is 0 and nothing is run.
  - **Captured share = (sum of w * Q_r) / (sum of w * D_r).** Printed with its two parts: what F gains at deviation roots, and what its changes at other roots gain or cost.
  - It is 1 if F plays the seat's labels and changes nothing else, 0 if F equals chain 55, and negative if F's changes cost more than its labels gain. Both sides are judged on rollouts that selected nothing.
  - Size: 30,000 test roots with about 420 deviations. I forecast an interval of about plus or minus 0.10 to 0.15. That is a forecast, and the run's own bootstrap replaces it.
- **Where and what, descriptive.** Two numbers that say which half failed if the captured share is low. *Where:* the area under the curve of a linear probe that predicts "deviation root" from the decoder's input, fitted on training games and scored on test games, for chain 55's features and for F's. On the seen data chain 55's features give 0.59 to 0.74 across four regularisation strengths, with 8 deviation roots among the 90 highest scores where chance gives 1.3 (NOTES measurement 5; 87 positives, the strength picked on the same folds). *What:* at test deviation roots, how often F's most probable action other than a0 is the label. For chain 55 on the seen data it is 36 of 87.
- **Out-of-scope changes** are counted (T_tv). They are also valued the same way on the sampled out-of-scope decisions of ordinary team turns and printed, descriptive only: the evaluator has been checked at in-scope decisions (D2) and nowhere else, so that number enters no rule and the gate is its judge.

**(iii) A fresh screen of F.** F under m1 against itself, and C against itself, on engine seeds 27000000 to 27000666 (667 games each, 15 roots per class, about 20,000 roots each), by the section 2 tool with the same settings. For F the rollouts and the seat's rule use F's network; under R1 its critic is chain 55's.
- Deviation share of screened roots, F against C, and the difference with its interval.
- Predicted gain found per screened root (the sum of gains at deviation roots over all screened roots), F minus C.
- Both also split by how probable a0 was, because a less sharp policy samples worse a0 more often and the search then "finds" more.
- Size: with 20,000 roots each the difference's standard error is about 0.0014, so a fall from 1.4% to 1.0% is detectable (2.8 standard errors). No fresh judgments are run here.
- It answers a different question from (ii): on F's own games, with F's own rollouts, is there less left for the search to find? That is what a second pass of a loop would start from.

**(iv) The gate, at plain speed, in D430's shape.** Registered in Entry B once F's hash exists.
- **Players.** F (sha256 fixed in Entry B) under m1 and C under m1, both sampling at temperature 1. Opponents chain 37 (`268f1db08ca0c2bad88293ea56b3048a2a1c3a0ea9acdf0365fc023186c0f73f`) and chain 46 (`8eee9ac10f58eca57092013ac05db6f28fb5f7f2c6dc9ce850960c7bb2c7c467`), plain, as in every gate since D418.
- **Pairs.** (1) F against chain 37; (2) C against chain 37; (3) F against chain 46; (4) C against chain 46. 12,800 naturally completed games each: engine seeds 25200000 to 25206399, both legs of every seed, kick-off starts, one game per worker, no sampling offsets. F and C share sampling seeds.
- **Statistic.** F minus C against chain 37 and against chain 46, decisive-Elo with 95% seed-cluster intervals, by `paired_contrasts.py` (sha256 `722ece95b24eed07f017062c4a837d44d4a49c4e97a7082fbb6fa2c37cef6002`, 2,000 replicates, generator seed 0), the script D430 and D435 used.
- **Size.** D434's contrasts and D442's gains had half-widths of 18 to 20 Elo at 3,200 games a pair. Four times the games halves that: about plus or minus 9.5. If F holds half of the search's gain (+22) each contrast clears zero with near certainty; at D430's size it would about six times in ten.
- **Machines.** Four droplets `s-8vcpu-16gb-amd`, 8 workers, each playing 1,600 seeds of all four pairs by index slice, so no arm is tied to a machine. About 3.8 hours each; time limit 6 hours.
- **One look**, as D430: runner logs only until every shard is in and the merged run has passed acceptance; no early stop, no extension.
- **Beside +45.** The gate's two contrasts are set beside D434's +45.5 and +45.3. They are on other seeds, and no interval is given for the ratio. The first 1,600 seeds' contrasts are printed too, as "at D430's size", descriptive.
- **Registered diagnostics, not gates:** W / D / L, decisive-Elo and touchdown difference of the four pairs; the D422 style table for F and C, with mean log-probability per decision (F moving toward the search seat's -0.43 or toward a tempered policy's -0.03 says which kind of change it made); the share of seed-legs where F's game is C's game. I expect that share near zero: a test blob with small noise on the output layer already played four different games of four.

## 5. Acceptance, reading rules, consequences, what is unread

**Acceptance of a label or screen shard, before any of it is used.** Modelled on `/Users/alexanderhuth/Code/bb-opt-build/docs/endturn-probe-2026-10-08/endturn_accept.py`.
- Every file matches the droplet's SHA256SUMS; the shard's plan copy hashes to the registered value; the machine built the pinned commit; `COMPLETE.json` names the plan hash, the checkpoint hash, the harness commit, the tool hashes, the reward manifest hash, the settings and the integrity list; no `FAILED.json`.
- The games are exactly the shard's engine seeds, each once, each ended in the engine's match-over status with every hard counter zero; the roots belong to those games in the counts the games recorded; every root has 4 x 16 finite returns or is a cap rejection; every deviation root has 2 x 128 fresh returns.
- No failed rollout. At most 1% of a shard's roots are cap rejections.
- The play-time integrity checks are those of `play_harness.search.INTEGRITY_CHECKS` that apply (engine return codes, the five hard counters in the real game and in every clone, finite logits, values and rewards within the clip threshold, no mask fallback, finite returns). Any failure stops the worker and the shard writes `FAILED.json`.
- One compiled library hash across all shards of a stage.
- Not checked, as in D425 to D434: the env's own reward telemetry counters, which the shim does not export.

**Acceptance of the dataset, on the Mac.** Every game's trail replays to its recorded final digest and observation hashes; every root's recomputed a0 and candidate list equal the recorded ones and a0's log-probability agrees to 1e-3; the four splits are disjoint by game and follow the rule of section 2; the label count per split is printed.

**Acceptance of F.** The blob has 16,066,560 bytes; it differs from chain 55's only in the tensors its recipe trains (for R1: floats 1,424,384 to 1,656,831; for R2 the value row is unchanged); the harness loads it and its logits equal the training tool's on 1,000 stored decisions to 1e-4; a second run of the training tool gives the same sha256; `SELECTION.json` names it.

**Acceptance of the gate.** As D435's four checks less the replay check: `tools/gate_acceptance.py` at `5ab3ab6` (pairs, counts, seed block, both legs once, one game per worker, the commit, every player's checkpoint hash including F's, sample mode at temperature 1, natural endings, integrity counters zero); `accept_from_plan.py` adapted from `/Users/alexanderhuth/Code/bb-opt-build/docs/search-probe-2026-10-07/tctl/accept_from_plan.py` (m1 on F's and C's side of every game and on no other, no sampling offset, no truncation, no mask fallback, final status, decision counts, the native kernel, `COMPLETE.json`, tool hashes); `tools/search_acceptance.py` unchanged (seats, modes, no search setting). The merge requires one commit, torch, Python and library. Relaunch as D430 fixed it: only a droplet that dies, loses contact or reaches its limit; its shard whole, once, from the same plan; at most two replacements.

**Unread, never a label:** missing, unaccepted or integrity-invalid evidence at any stage; a budget stop; a shard that fails twice. A stage that is unread stops the plan there until a new entry.

**Reading 1, fit (after milestone 1, and again after milestone 2).** First match:
1. **Unread:** dataset acceptance failed.
2. **No recipe fits:** R1 and R2 are both NOT FIT. The plan stops. It says the recipes could not fit their training roots and nothing about generalisation.
3. **Fits:** otherwise, with each recipe's result named. A recipe that is NOT FIT is dropped from the choice.

**Reading 2, held-out roots.** "Above" and "below" mean the whole interval. First match:
1. **Unread:** acceptance failed.
2. **Nothing generalised on validation:** the validation bar of section 3 is not met. The test games are not opened and no gate is played.
3. **Damaged:** the captured share on the test games is below zero. By the seat's own evaluator F is worse than chain 55 at the states C meets. No gate is played.
4. **Generalises:** the captured share is above 0.25.
5. **Does not generalise:** the captured share is below 0.25.
6. **Unclear:** anything else.

**Reading 3, the fresh screen.** First match: **less left** (the interval of F's found gain per root minus C's is below zero); **more left** (above zero); **no difference shown**. It decides nothing by itself. It qualifies the table below.

**Reading 4, the gate.** First match, on accepted evidence:
1. **Negative:** either contrast's interval entirely below zero.
2. **Positive:** both point estimates at +15 or more and both intervals entirely above zero. As in D425 and D430 this establishes gains above zero, not above +15. Why +15: it is a third of the search seat's gain, for nothing at play time; m1 was taken at +32 to +43. That is an engineering preference.
3. **Flat:** both intervals inside -15 to +15, ends included. At the expected width this can be reached.
4. **Inconclusive:** anything else.

**The gate is played** when Reading 2 is Generalises, Does not generalise or Unclear. A small captured share does not cancel it: the review asks that match results be read, and the gate costs about $2.50.

**Consequences.** Rows are read from the top, first match.

| Reading 2 | Reading 4 | What follows |
|---|---|---|
| any | Negative | F is weaker than C. The recipes are closed and the collateral numbers of Reading 2 are the first place to look. |
| Generalises | Positive | Search as a teacher is built off the rig first: a second pass (labels on F's own games, distil, gate) in its own entry. F under m1 may be proposed as a play-time option in its own entry. The on-rig scheme (g) gains one supporting fact (the labels are learnable) and still needs its own design review. |
| Unclear | Positive | As the row above, and the second pass's entry states that the held-out reading did not separate from 0.25. |
| Does not generalise | Positive | Reported as unexplained. Nothing builds on it before a replication gate on fresh seeds. |
| Generalises | Flat or Inconclusive | Not built on this evidence. F copies the seat's choices where C went, and no strength is shown. Reading 3 says which follow-up to register: "less left" points at the gap between one-step choices and match results (the next entry tests labels on the student's own games); otherwise more labels. |
| Does not generalise or Unclear | Flat or Inconclusive | These recipes are closed at this label count. If the learning curve's last doubling raised validation M by 0.05 or more without raising U, a larger label run is the next entry (the reserve games become its test). If not, distillation by imitation of this seat is closed, and (g) is not built on this evidence. The review's caution stands: this does not show an online scheme would fail. |
| Nothing generalised on validation, or Damaged | not played | As the row above, read from the learning curve. In the first case the test games stay unopened and join the reserve. |
| No recipe fits | not played | Nothing is concluded about generalisation. A new entry needs another recipe. |

Nothing is adopted under any outcome: no training recipe, warm start, play-time default or evaluation default changes.

**Unread until its time.** The test games' numbers until `SELECTION.json` is frozen. The reserve games, for the whole plan. The fresh screen's and the gate's records until their merged runs pass acceptance. Training and validation numbers are read freely. The deviation counts of the label shards are not outcomes of any comparison and may be read as they arrive.

## 6. Cost and wall-clock

Rates, and where each comes from.
- **A plain game on a droplet:** 7.5 to 8.7 s of one process with eight busy (D434, D442). On the Mac, one process: 1.1 to 1.4 s (measured here, three games).
- **A screened root on a droplet:** 1.84 s of one process with eight busy. Arithmetic: D434's searched game takes 363.8 s against 7.5 s plain, for 193.5 searched decisions. On the Mac: 0.31 s (1,350 roots in 412 s, `tail1/tail_meta.json`). The two machines differ by about six in both figures. D426's 963 rollout steps a second per busy droplet process against the Mac's 5,548 says the same.
- **A fresh judgment:** 256 rollouts, four screens' worth, 7.4 s on a droplet process.
- **A label game:** 8 + 30 x 1.84 + 0.42 x 7.4 = about 66 s of one process, so about 434 games an hour on a droplet.
- **R2 training on the Mac:** 64 windows of 64 steps, forward and backward, in 0.68 s on one thread (measured). A pass of about 32,000 windows of 96 steps is about nine minutes; four settings of ten passes are about six hours of one process.
- **Droplet:** `s-8vcpu-16gb-amd`, $0.167 an hour.

| Stage | Work | Droplet-hours | Cost |
|---|---|---|---|
| Milestone 0 and the wide rehearsal | Mac only | 0 | $0 |
| Droplet smoke | one droplet, 16 label games and 64 gate games | 0.4 | $0.07 |
| Labels, milestone 1 | 1,000 games | 2.3 | $0.38 |
| Labels, milestone 2 | 9,000 games | 20.7 | $3.46 |
| Dataset, R1, R2 | Mac (R2 may go to one droplet instead) | 0 | $0 |
| Validation and test rollouts | up to 3 screens' worth at each root where a setting differs from chain 55; one droplet, assumed | 4.5 | $0.75 |
| Fresh screen | 2 x 667 games, no judgments | 2.9 | $0.49 |
| Gate | 51,200 plain games at 8.5 s | 15.1 | $2.52 |
| **Expected total** | | **about 46** | **about $7.70** |

- **Ceiling:** $18 for everything in the plan, counted from the runners' cost lines: the label stage at six droplets and a 6 hour limit ($6.00), its two allowed replacements ($2.00), the fresh screen at two droplets and 3 hours ($1.00), the gate at four droplets and 6 hours ($4.00) with two replacements ($2.00), rollouts and R2 on droplets ($3.00).
- **Wall-clock once the tools exist.** Milestone 1: two droplets, about 1.3 hours. Milestone 2: six droplets, about 3.5 hours (four: 5.2). Dataset build: minutes (replay is 0.02 s a game; 13 million forwards at a measured 14,000 a second is a quarter of an hour). R1: minutes a setting. R2: about six hours of one Mac process. Validation rollouts: an hour or two. Test rollouts: under an hour. Fresh screen and gate together: six droplets, about 4 hours. About 16 hours of machine time; two days with reviews and entries.
- **Droplet slots.** The account allows 15, shared with other projects. No stage needs more than six. Each stage launches with what is free and at least one slot to spare; the plan and its hash do not depend on the launch order. On a quota or limit refusal nothing is deleted to make room: the launch waits.
- **Exposure** is as D436 wrote it: the time limit is enforced by the local runner, so a dead runner, a lost create or a failed delete can leave a droplet billing. The cleanup commands are written before anything is created, and the Mac is kept awake for every stage.
- **Disk:** under 1 GB of records for 10,000 games (a trail is 17 KB of JSON, 2 KB compressed, measured; a root's record is about 1.5 KB, estimated).

## 7. Tools to build

All in `/Users/alexanderhuth/Code/bb-opt-build/docs/search-distill-2026-10-08/`, beside this plan, importing the harness from a `git archive` export of `5ab3ab6` (the pattern of `/Users/alexanderhuth/Code/bb-opt-build/docs/endturn-probe-2026-10-08/export_harness.sh`). No harness worktree is changed. Each tool refuses a plan file that does not hash to the value given, and refuses when its own file is not the one the plan names.

| Tool | What it does | Reuses |
|---|---|---|
| `make_plan.py` | Writes `PLAN.json`: checkpoints by hash, seeds, shards, settings, tool hashes | the END_TURN probe's `make_plan.py` |
| `distill_screen.py` | Plays the label games, takes roots, screens them, applies the seat's rule, judges deviation roots on fresh rollouts, writes the records of section 2. Takes any blob, so it also runs the fresh screen | `tools/search_probe_diag.py` `Harness.play_game` and `screen_stats`; `play_harness.search` `Rollouts.evaluate`, `deviation`, `joint_log_probabilities`, `candidate_order`; `endturn_probe.py`'s worker pool, fail-fast checks, `in_kickoff_turn`, `COMPLETE.json` |
| `distill_droplet.py` | Launches shards on droplets from the hashed plan, fetches, verifies, tears down | `endturn_droplet.py` and the harness's `tools/droplet_tournament.py` lifecycle |
| `distill_accept.py` | Shard acceptance (section 5) | `endturn_accept.py` |
| `distill_dataset.py` | Replays every trail, checks digests and observation hashes, runs chain 55 for states, h and reference distributions, writes the split files; refuses the test split without `SELECTION.json`'s hash and the reserve split always | `play_harness.engine`, `play_harness.policy` |
| `distill_finetune.py` | R1 and R2, the declared grid, J, the stop, the eligibility checks, the blob and its sidecar | `training/convert_checkpoint.py` `torch_to_cuda` |
| `distill_eval.py` | Fit, T_mass, T_tv and the captured share with its rollouts on replayed roots, for validation (the choice, `SELECTION.json`) and for test (Reading 2); prints every rule with its numbers | `Rollouts.evaluate` |
| `distill_screen_report.py` | Reading 3 from two accepted screen runs | the bootstrap of `endturn_analyze.py` |
| Gate scripts | `make_plan.py`, `launch_from_plan.py`, `accept_from_plan.py`, `score_from_plan.py`, `gate_diagnostics.py`, `paired_contrasts.py` | byte copies of `/Users/alexanderhuth/Code/bb-opt-build/docs/search-probe-2026-10-07/tctl/` with the replay check removed from `accept_from_plan.py` |

**Tests before any registered run.**
1. **The label is the seat's.** On 20 games on the Mac, the real `SearchSeat` at the registered setting plays a searched game, and `distill_screen.py` screens every in-scope decision of the plain game on the same seeds. Up to the seat's first deviation the two see the same states, so the tool's first deviation root must be the seat's, with the same action and the same gain to the last float. The seat's later decisions cannot be compared, because its game has left the plain one.
2. **The loss is the sampler's.** The training tool's joint log-probabilities equal `joint_log_probabilities` to 1e-9 and `select_joint`'s returned log-probability on 1,000 stored decisions, large supports included (the largest seen here has 2,145 tuples).
3. **Identity.** With zero training steps the blob written is chain 55's, byte for byte, for both recipes. With R1 trained, only the declared floats differ. R2's training forward equals `forward_eval` bit for bit (measured for a scratch version).
4. **Replay.** Every rehearsal game's trail regenerates its digest and its observation hashes, on the Mac and from droplet records. Whether a droplet's observation bytes equal the Mac's has never been checked directly; this test is where it is.
5. **The test split is locked.** The training tool given a test or reserve file refuses; the evaluation tool without the selection hash refuses.
6. **Milestone 0** (section 8): the whole chain on seen data.
7. **The wide rehearsal: 300 games on the Mac** (seeds 29980100 to 29980399) at 4 screening rollouts and 8 judgment pairs, every integrity check on, then the dataset tool, two passes of each recipe, the blob, the evaluation tool with its rollouts, and a 64-game Mac tournament of the rehearsal blob against C through all three acceptance tools. About 20 minutes of one process for the games. It exists because the END_TURN probe's two-game smokes missed a situation that occurs in one game in seven (D437). 300 games meet a one-in-seven situation about 43 times and a one-in-a-hundred situation with probability 0.95. It must show kick-off turn roots, a cap rejection or an explicit count of zero, and a support above 1,000 tuples. It cannot rule out anything rarer.
8. **A droplet smoke:** one droplet, 16 label games at the registered settings and 64 gate games, launched from a hashed smoke plan, through acceptance. It is the only test of the droplet path and its timing, and it loads all eight processes (D426's lesson).
9. **The launcher's offline flow test,** as `test_launcher_flow.py` does for the END_TURN probe.

## 8. Milestone ladder

Each step names what it can show and where the plan stops.

**Milestone 0: seen data, the Mac, $0. Before Entry A.**
- Regenerate the 200 games of block 29100000 with the built tools: 6,000 roots, 87 labels with their 128-pair judgments already on disk.
- Run the whole chain: dataset, R1 at its three lambdas, R2 at its four settings, blob, sidecar, evaluation with rollouts, a Mac tournament through acceptance.
- It fixes R2's learning rates and both recipes' pass counts, and it measures R2's eligibility checks for the first time.
- It cannot show generalisation: about 20 held-out labels. Its held-out numbers are printed and enter nothing. The preview of R1 made while writing this plan is the first half of it (section 3).
- **Stop here** if the chain cannot reproduce the records, the blob identity fails, or R2's window check fails for every setting.

**Entry A** is then written: this plan with the grid frozen, `PLAN.json` hashed, the outside review applied.

**Milestone 1: 1,000 label games, about $0.38.** About 290 training labels and 42 validation labels.
- Reading 1 at this size, for both recipes. No recipe fits: **stop**, and nothing is said about generalisation.
- Validation numbers are printed and do not stop the plan. 290 labels are too few to judge generalisation, and stopping on them would be a second, unregistered reading. They are the first real look at whether more data shrinks the held-out change the preview saw, and the operator's expectation should be written before them.

**Milestone 2: 9,000 more label games, about $3.46.** Train all seven settings, Reading 1 again, validation rollouts, the choice, `SELECTION.json`. **Stop** if the validation bar is not met. Otherwise the test games, once: Reading 2. **Stop** on Damaged.

**Entry B:** F's sha256, its sidecar's, the gate's `PLAN.json` hash and the screen's shard list, fixed before any game of either.

**Milestone 3: the fresh screen and the gate together, about $3.00.** Readings 3 and 4, then the table of section 5.

**Where I would stop regardless of the outcome.** One winner, one test look, one gate. No second pass of the loop, no other checkpoint, no third recipe, no lower delta, no labels on the student's own games. Each of those is a new entry that this plan's outcome may or may not justify.

## 9. Limits

- **Two recipes, one label count, one teacher setting, one checkpoint.** The seat's scope, delta, 16 rollouts and candidates were chosen on exploratory runs (D425's limits).
- **The teacher's evaluator** is the shaped training reward plus chain 55's value head. The captured share measures agreement with that evaluator on fresh rollouts. Only the gate measures wins.
- **Labels are one-step.** Every root is one changed action on C's own trajectory, followed by C's play. Once F deviates it meets states no label covers. Reading 2 cannot see that; the fresh screen and the gate can.
- **Self-play labels, held-out opponents.** The rollouts that made the labels model the opponent with chain 55 itself. Chain 37 and chain 46 are older relatives about 190 to 200 Elo weaker than C. Nothing here is about a stronger opponent or a person.
- **The captured share covers in-scope decisions.** Changes F makes elsewhere are counted, and valued only descriptively.
- **J's price of an unintended change** (0.016) comes from the study's exploratory screens. It only picks a pass; the choice among settings and the reading use rollouts.
- **Validation is used for the stop and for the choice.** The test games correct for that. The reserve games exist because a further recipe or a second look would otherwise reuse them.
- **R2's 64-step window** is justified by a measurement on chain 55 and checked on F after the fact. R2's learning rates are guesses until milestone 0.
- **F is valid under m1 only,** and is not eligible ancestry for training.
- **False labels are trained on.** D2 found 0 false of 87 (upper bounds 3.4% counting roots and 4.4% counting games, with the limits D430 lists). The share in this run is reported from the fresh judgments.
- **The fresh screen has no fresh judgments,** so its deviations are the rule's, with the rule's selection noise, for F and C alike.
- **Acceptance checks declarations, counts and hashes.** The label arithmetic rests on the pinned code and on test 1 of section 7, which can only compare up to a game's first deviation.
- **Not measured:** the droplet rate of the label tool, the cost of the validation rollouts, the record size at full scale, and R2 in any form beyond the timing of one batch.
- **The preview is 87 seen labels.** It shaped the recipes and the statistics. It is not a result, and a reader should not take from it that R1 fails.

## OPERATOR: expectation

*(To be written by the operator before Entry A, and before milestone 1's validation numbers, so that it cannot be adjusted later. Suggested items: whether each recipe fits; which recipe wins on validation and whether the bar is met; the captured share on the test games; the fresh screen's direction; both gate contrasts and the label; which row of the consequence table.)*
