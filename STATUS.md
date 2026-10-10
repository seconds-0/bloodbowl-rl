# Status — 2026-08-21

## Current verdict

**Update 2026-09-12 (D388/D389): direction reset, chain 23 training.** From Sep 4 to Sep 11 the program ran on an uncommitted obs-v7 tree, now archived as `archive/codex-improvement-20260911`, where decisions D290-D387 live. Every model it trained scored zero learner touchdowns. A 154-agent audit found no engine, observation, reward-plumbing or evaluation bug behind that result. The cause was direction:
- Every learner started from weights that never scored.
- The imitation teacher scores 0.19 TD/game, while migrated chain 9 still scores 0.40 through the same harness.

The obs-v6 chain 9 lineage is the program again. Chain 23 launched 2026-09-12 06:42 PDT from 2ae5144 at 98-104K SPS:
- warm start: chain 9
- opponents: 8 frozen banks x 0.06, contact bot at tag 8
- reward: `r0_poss_half`, seed 42, 3B steps

The pre-registered paired analysis against chain 14 is in `docs/opponent-population-scope.md`.

**Update 2026-09-12 15:30 (D390): chain 23 is flat.** Chain 23 finished clean at 3B. Its two-seed exam lands within the 0.02 noise floor of chain 14 on all three champion cells (+0.005, -0.0045, -0.016), so it is not promoted and not rejected. It stays below the chain 9 + chain 16 frontier. Chain 9 remains the frontier. Next is a horizon arm: chain 14's exact recipe with train gamma 0.999 and GAE lambda 0.95. The ladder launch path is getting that knob now. The chain 24 seed replicate stays staged but unlaunched.

**Update 2026-09-12 16:43 (D391): chain 25 is training.** The horizon knob merged (PR #99), and chain 25 launched with chain 14's pool identity d67d527b and gamma 0.999 / lambda 0.95 confirmed in the arm banner. The exam waiter is staged. The pre-registered reading is in `docs/horizon-arm-scope-2026-09-12.md`.

**Update 2026-09-12 23:35 (D392): chain 25 reads positive.** Its two-seed exam beats chain 14 by +0.0645 on contact AWAY, +0.062 on contact HOME and +0.014 on offense AWAY, with both contact cells up on both exam seeds. It sits above the chain 9 + chain 16 frontier on all three champion cells for the first time. It is not promoted. Chain 26 replicates it at training seed 44, paired with chain 20, before any verdict.

**Update 2026-09-13 07:05 (D393): the horizon gain replicates.** Chain 26 beats chain 20 by +0.047 and +0.035 on the two contact champion cells, both up on both exam seeds. Gamma 0.999 / lambda 0.95 is now the ladder recipe, and chain 25 is the new frontier warm start. Chain 27 continues from chain 25 under the horizon recipe to test whether the continuation plateau was a horizon artifact.

**Update 2026-09-13 13:55 (D394): chain 27 is not accepted.** Chain 27 raises both contact champion cells against chain 25 (+0.035, +0.0275) but drops offense on both exam seeds (-0.0385 on the mean). Chain 25 stays the frontier. Chain 28, the exact-PBRS distance arm at gamma 0.999 paired with chain 25, launched automatically through the rig queue.

**Update 2026-09-13 20:40 (D395): chain 28 collapsed.** Switching the distance channels to exact PBRS on the chain 9 warm start halved scoring and doubled conceded touchdowns: pickup attempts fell 43% while blocks held steady. This is the D253 pattern: never switch a reward form on a warm checkpoint. The recipe stays legacy `r0_poss_half` at gamma 0.999, and chain 25 stays the frontier. Chain 29 tests a longer horizon (gamma 0.9995, lambda 0.97) on chain 25's recipe.

**Update 2026-09-14 03:30 (D396): chain 29 marginally overshoots.** Gamma 0.9995 lands below chain 25 on all three champion cells (-0.023, -0.0135, -0.0335) but still above the 0.995 continuations on contact. The dose-response peaks near 0.999, which stays the recipe. Next is the update budget: chain 25's recipe at replay_ratio 1.0 (8 gradient steps per epoch instead of 2), once the ladder gains that knob.

**Update 2026-09-14 22:15 (D397): chain 30 is flat.** Four times the gradient steps per epoch leaves the champion cells within the floor of chain 25 (+0.0025, +0.025, -0.0035) and costs about 30% SPS, so the recipe keeps replay ratio 0.25. Chain 31 is training: 8 opponent banks under the gamma 0.999 recipe, paired with chain 25.

**Update 2026-09-15 06:45 (D398): chain 31 reads negative and ambiguous.** Eight banks at 0.06 under the horizon recipe lose contact AWAY on both exam seeds (-0.053 on the mean). This may be population width or the halved bot exposure. The knob screen around chain 25 is complete: every one-factor change is flat or worse. Chain 25 stays the frontier. Next come a CPU head-to-head tournament between checkpoints and GPU verification of the opt-in throughput patches.

**Update 2026-09-15 08:30 (D399): the round robin moves the frontier.** A 21,000-game head-to-head round robin puts chains 27 and 30 about 100 decisive-Elo above chain 25; the two are tied. Chain 30 becomes the warm start. The bot exam keeps its offense veto, and a fixed anchor-panel tournament joins the gate. Both opt-in throughput patches (skip-scripted-bank-forward, deciding-row telemetry) passed GPU verification and are merged (PRs #102/#103). Chain 32 replicates chain 30's recipe at training seed 44.

**Update 2026-09-15 10:55 (D400): chain 30's gain survives every control.** In a 21,600-game follow-up, chain 30's +106 decisive-Elo gap over chain 25 is about four standard deviations above the training-seed floor (replicate pairs move 14-40 Elo). It is unchanged with argmax play (+106) and against a sharpness-matched chain 25 (+109), and it is not roster-dependent. The warm start stands.

**Update 2026-09-15 18:30 (D401): replay ratio 1.0 replicates and becomes the recipe.** Chain 32, chain 30's recipe at training seed 44, beats chain 25 by +95 decisive-Elo head to head (chain 30: +106). On the exam it lifts both contact cells over its seed-44 comparator, chain 26 (+0.038, +0.053), and the offense veto does not fire. Chain 32 vs chain 30 is +15.4, a fourth replicate pair inside the floor. Chain 30 stays the warm start. Chain 33 tests replay ratio 2.0 against chain 30 under the two-part gate.

**Update 2026-09-16 09:25 (D402): replay ratio 2.0 is negative.** Chain 33 loses 0.08-0.13 champion touchdowns per exam cell against chain 30, and the offense veto fires on both seeds. Both sides score less and draws rise. Replay ratio 1.0 stays the recipe, and chain 30 stays the warm start. Chain 34 continues chain 30 for another 3B at replay ratio 1.0, gated against a panel of chains 30, 27, 32 and 25 and the offense bot.

**Update 2026-09-16 10:40 (D403): chain 33's tournament confirms D402.** Head to head, replay ratio 2.0 holds a small edge over chain 30 (+22) and chain 32 (+19), below the +40 replicate threshold. Against the held-out offense bot it scores fewer touchdowns and a slightly lower score than chain 30 on the same seeds. Chain 32 over chain 26 is +120, so replay ratio 1.0 beats 0.25 on seed-matched pairs at both training seeds. Nothing changes: chain 30 stays the warm start and chain 34 keeps its gate.

**Update 2026-09-17 10:30 (D404): chain 34 is positive and becomes the warm start.** Continuing chain 30 for another 3B beats the parent by +53 decisive-Elo and chain 27 by +66 over 16,000 clean games. The offense veto stays clear by 0.002 on one exam seed, and every exam cell is slightly below chain 30, so the exam and the tournament disagree in sign again. Native CUDA parity passed its screen: the harness reproduces the rig's action distributions on recorded states (mean joint TV 5e-7). Chain 35 replicates the continuation at training seed 44. CPU tournaments now run off the Mac.

**Update 2026-09-17 10:45 (D405): chain 36 is queued.** A continuation from chain 34 starts on its own when chain 35's exam ends, so the GPU does not idle during the gate tournament. Its pool makes chain 30 an active learned opponent for the first time. Its gate adds a drift guard: offense AWAY may not fall more than 0.04 below chain 30.

**Update 2026-09-17 13:20 (D406): gate tournaments leave the Mac and get about 5x faster.** A droplet runner (create, run, verify, destroy) and a batched policy forward (32 games per worker) are merged in the play harness. Batched games match unbatched ones on 3,200 of 3,200 action trails against the Mac reference, with rare roundoff divergences that never changed a score. Chain 35's 22,400-game gate is budgeted at about 17 minutes and $0.17 on four droplets.

**Update 2026-10-02 (D407): trainer review, a faster build, and two learning-rate restart arms.** The rig sat idle from 2026-09-18. A two-pass review of the training code (48 findings, `docs/trainer-review-2026-10-02.md`) found no algorithmic bug in the update itself, found that the entropy coefficient has never annealed in any native run, and found that each warm restart's jump to the full learning rate costs most of a rung in in-run score. The long-run build (blitz fast path, scripted-bank forward skip, loss telemetry) trains byte-identically to the old build over 24 same-seed epochs and measured +9.7% steps per second on one clean pair. Chains 37 and 38 test a restart at half the learning rate against controls that already exist (chains 36 and 35). An on-box supervisor now runs rung, exam and the next launch without a human. Chain 35's and chain 36's gates are still unscored.

**Update 2026-10-02 12:51 (D407 amendment, D408): chain 37 is training under the on-box supervisor.** The long-run build reproduced chain 36's own first 50M steps byte for byte, and a 50M-step canary passed the whole launch path. Chain 35's gate reads Replicated (+46.0 decisive-Elo over chain 30), its edge over chain 34 is not established (+12.3, interval includes zero), so chain 34 stays the parent. Three restart-scale arms are registered: chains 37, 38 and 39, with controls 36, 35 and 34. Chain 37 runs at 99.0K steps per second. Chain 36's gate has still not run. The rig idled about 11 hours overnight because a paused supervisor was not re-enabled.

**Update 2026-10-02 22:10 (D409): chain 36 is the warm start; the half-rate restart reads Flat.** Chain 36 beats chain 34 by +77.4 decisive-Elo and becomes the warm start, the second Positive continuation in a row. Chain 37, the same rung at half the restart learning rate, is level with chain 36 head to head (+0.5, interval -12.3 to +13.6) with a smaller in-run dip. Chain 38 (the second arm) is training. Chain 40, the continuation from chain 36 on the standard recipe, runs next; chain 39 runs only if chain 38 reads Positive.

**Update 2026-10-03 07:25 (D410): the half-rate restart is not adopted; an opponent-seat arm is next.** Chain 38, the second half-rate arm, lost to its control head to head (-34.5 decisive-Elo, interval below zero) while scoring higher on every scripted-bot measure. With chain 37 Flat, restart scale 1.0 stays and chain 39 is not run. Chain 40 (continuation from chain 36) is training. Chain 46 runs after it: the same rung with the scripted bot moved to the anchor's seat, so the learner faces chains 30, 34 and 36. The owner's stated goal is a superhuman bot; `docs/plans/superhuman-roadmap-2026-10-03.md` is the proposal.

**Update 2026-10-03 16:20 (D411): chain 40 is the warm start.** The continuation from chain 36 beats its parent by +78.5 decisive-Elo and chain 27 by +176.0, the third Positive continuation in a row (after +52.7 and +77.4). Against the scripted bots it scores about the same and concedes less. Chain 46 (the opponent-seat arm, control chain 40) is training; chain 41 continues from chain 40 after it.

**Update 2026-10-04 11:10 (D412): chain 41 is the warm start; the opponent-seat change is a candidate.** Chain 41 beats chain 40 by +57.2 decisive-Elo, the fourth Positive continuation in a row. Chain 46, the same rung as chain 40 with the scripted bot in the anchor's seat, beats chain 40 by +42.2 [+28.7, +55.3], a narrow Positive. Chains 47 and 48 are the second-seed pair that decides whether the seat change becomes the recipe. Chain 42 is training.

**Update 2026-10-04 19:05 (D413): chain 42 reads Flat; chain 41 stays the warm start.** After four Positive continuations, chain 42 is +12.5 over chain 41 with an interval that includes zero. Chains 43 to 45 are not run. Chain 48, already queued, is the same continuation at another seed and will say whether the Flat replicates. Chain 47 (training) and chain 48 are the second opponent-seat pair; chain 49 follows as a third seat arm with chain 42 as its control.

**Update 2026-10-05 12:50 (D414): the seat change is not adopted and plain continuation from chain 41 reads Flat at two seeds.** The second opponent-seat pair is +9.0 with an interval that includes zero, so the scripted bot stays on bank tag 4. Chain 48 is +11.0 over chain 41, replicating chain 42's +12.5: one more rung no longer clears the +40 gate. Chain 41 stays the warm start. Chain 49 (a third seat context) is training. Chains 50 to 53 then test whether those small gains compound: only chain 53, five rungs past chain 41, is gated.

**Update 2026-10-05 21:00 (D416): the gap to human play is turn shape, and a no-training rule closes part of it.** Chain 41 activates about 3 players a team turn against a human 7 and ends its turn early in 62% of turns. Forbidding an early end of turn at play time, with no training, is worth +32 to +43 decisive-Elo on four checkpoints. Chain 54 trains one rung under that rule on a third build, with chain 42 as control, after an identity check and a canary. Also: an integrity-guard false positive halted the campaign for 27 minutes and is fixed; the exams of chains 37 to 49 ran on the original build's module because of an environment-copy defect.

**Update 2026-10-05 21:30 (D417): chain 49 is Negative by its exam veto and the strongest checkpoint by tournament.** The third seat context beats its control by +62.7 decisive-Elo and reads +182.6 against chain 37, but its exam veto fires, so the registered reading is Negative and the seat change stays not adopted. The exam veto is retired from future gates. A confirmatory gate on fresh seeds and held-out opponents decides whether chain 49 replaces chain 41 as the warm start.

**Update 2026-10-05 21:50 (D418): chain 49 is the warm start.** On fresh seeds chain 49 does better than chain 41 against three opponents neither ever met, by +60.2, +75.4 and +41.1 decisive-Elo with every interval above zero. Chain 54 is withdrawn and the compounding test is stopped unread. Three rungs from chain 49 run next on the third build: chain 55 (plain continuation and control), chain 56 (trained under the no-early-end-turn rule) and chain 57 (bot in the anchor's seat), after an identity check and a canary.

The obs-v6 / exact-action lineage has its first reproducible scoring policy:
two independent rung-6 backplay runs (maxdist 6, reset 0.5, `s0_both`,
genesis pool `f6a6323a`, 5B steps) finished clean in July at tds 0.299 /
0.303 per episode from curriculum starts, all sixteen hard-integrity counters
zero in both phases, curves plateaued from ~2.6B on. Neither could advance the
ladder because the bare rung launcher never published eligible lineage
(D235). No production reward or default has changed; `s0_both` remains the
experimental lineage reward.

**Update 2026-08-28 (D289) - the loop is out of moves and the rig is parked on a decision from Alex.**
Every direction available below the structural choice named in D275 is now
closed with a ledger entry: the shaping inventory is empty (distance D264/D265,
the possession/ball-gain decomposition D266/D267/D269/D270, the block-EV family
D278/D281, the rush fine D289 - each varied one at a time from `r0_poss_half`,
each null or negative, leaving only `reward_td` 0.4 and `reward_win` 0.6, which
are the objective); the knob screen is closed twice over (bot share at the 0.124
arithmetic ceiling D274, LR x2 rejected D259/D271, offense bot in the bank seat
rejected D260/D272, entropy D262); the horizon direction is closed (6B cumulative
continuation lands within 0.02 of 3B, D275); and plain continuation is a settled
null across two parents and four training seeds (chains 14, 19, 20, 21 -
D273/D284/D285/D287). Chain 9 remains the frontier at a pooled 0.537/0.416,
0.492/0.406, 0.571/0.350.

**The open question, which the loop cannot answer for itself:** which structural
change to fund - (a) an opponent population, which needs an env/launcher change
because the frozen-bank share is already at its 0.124 arithmetic ceiling, or (b) a
capability `r0_poss_half` cannot express at 3B and this policy scale. Until one is
named the rig is deliberately idle rather than spending 12 GPU-hours per rung to
re-measure a result five runs have already established. No production reward or
default has changed.

**Update 2026-08-27 (D283/D284).** Chain 19, a plain 3B continuation testing
nothing, came back ON the frontier (two-seed mean 0.533/0.483, 0.481/0.460,
0.581/0.393, every champion cell inside 0.02 of chain 9) while chain 14, the
same recipe at a different training seed, sat 0.029-0.037 below it. So D277's
0.011 champion-cell reproducibility floor does not extend to continuation
rungs, and the confident form of the D273/D275 plateau claim - that further
training at frontier settings reliably loses - is withdrawn. Continuation
neither reliably gains nor reliably loses, and one training run cannot resolve
a scoring change smaller than about 0.03 TD/game. The two-training-seed anneal
verdict on `r0_blockev_half` (D281) is unaffected, and no arm has beaten chain
9 outside noise. Chain 20 (seed 44 from chain 9's own marker) closes the
parent/seed confound.

**Update 2026-08-27 (D281).** The hill-climb from the July R0 warm has run 19
chained rungs. The frontier is unchanged since D266: chain 9
(`runs/ladder-d0-r0chain9-20260824`, `r0_poss_half`), two-seed exam
0.534/0.393, 0.488/0.396, 0.575/0.336. The one-family-at-a-time shaping anneal
is now finished and every family - distance, possession annuity, ball gain,
block EV - came back flat or worse on the native kickoff exam at 3B, the last
of them (`r0_blockev_half`) on a two-training-seed replicate. The knob screen
ended earlier at D274. What is left is above this loop: an opponent population
(blocked by the 0.124 frozen-bank arithmetic ceiling, needs an env/launcher
change) or a capability `r0_poss_half` cannot express. No production reward or
default has changed.

## Live campaign: `week-20260815` (RTX 2070, systemd supervisor)

Backplay ladder as one-arm screens (`SCREEN_PROFILE=ladder-rung`, PR #93):

| stage | rung | reset | warm | pool | state |
|---|---|---|---|---|---|
| 0 | sync + rebuild + plan-only | — | — | — | done 2026-08-15 03:40 PDT |
| 1 | 6 | 0.5 | genesis root gen1042 | genesis pool | **accepted** 15:43 PDT — tds 0.303, bit-exact July replicate (D236) |
| 2 | 9 | 0.5 | rung-6 accepted | gen1043-45 + rung-6 (`724f9470`) | accepted Aug 16 03:40 — tds 0.257, plateau (D237) |
| 3 | 12 | 0.5 | rung-9 accepted | gen1044-45 + rung-6/9 (`2dd42771`) | accepted Aug 16 15:18 — tds 0.335, STILL CLIMBING at cap (D237) |
| 4 | 0 (uniform) | 0.5 | rung-12 accepted | gen1045 + rung-6/9/12 (`6cbb53c9`) | accepted Aug 17 02:24 — tds 0.272, still climbing → chained |
| 4b | 0 (uniform, chain) | 0.5 | uniform accepted | rung-6/9/12/uniform (`0c9fb9ae`) | accepted Aug 17 13:5x — **tds 0.483**, still climbing (D238) |
| 5 | — | — | — | — | rig campaign HALTED; frontier moved to Vast (D238) |

Seed 43 throughout, 5B cap per rung, +3 squares per rung (D51), plateau read
per D168 between rungs. Progress: `~/bin/bbwatch` from the Mac; artifacts
under `runs/ladder-d<rung>-20260815/`; supervisor state under
`runs/campaigns/week-20260815/`.

## Live campaign: `vast-20260817` (Vast bb-ryzen1, Ryzen 9 3950X 32t + RTX 3090, $0.176/hr, ~3× the rig)

| stage | rung | reset | warm | pool | state |
|---|---|---|---|---|---|
| 1 | 0 (uniform) | 0.5 | chain accepted (rehosted) | rung-9/12/uniform/chain (`575d58f9`) | accepted Aug 17 23:01 — **tds 0.530**, still climbing (D239) |
| 1b | 0 (uniform, chain2) | 0.5 | stage-1 accepted | rung-12/uniform/chain/stage-1 (`f1f423f8`) | accepted Aug 18 06:45 — **tds 0.652**, pickups 0.91, still rising (D240) |
| 2 | 0 | 0.25 | chain2 accepted | promoted (`e138c936`) | accepted Aug 18 15:35 — **tds 0.695**, pickups 1.17, still climbing (D242) |
| 2b | 0 | 0.25 (chain) | r25 accepted | chain/stage-1/chain2/r25 (`0339ccb4`) | COLLAPSED (tds 0.10, D244) — killed at 2.06B |
| 2b-v2 | 0 | 0.25 (chain) | r25 accepted | rung-12/uniform/chain/stage-1 (`e138c936`, r25's own pool) | COLLAPSED again at 0.55B (D245) — box-1 campaign HALTED; frontier = r25 accepted (tds 0.695) |
| 3 | 0 (kickoff) | 0 | r25-chain accepted | promoted | queued |

## Live campaign: `vast2-20260818` (Vast bb-ryzen2, Ryzen 9 5950X 32t + RTX 3090, $0.241/hr) — PR #94 build

| stage | rung | reset | warm | pool | state |
|---|---|---|---|---|---|
| 1 | 0 (kickoff) + contact-bot bank 4 | 0 | chain2 accepted (graft, D243) | uniform/chain/stage-1/chain2 (`cb769c10`) | accepted Aug 18 ~22:00 — **tds 0.731 from kickoff**, vs-bot 0.21; D50 exam running |

| 2 | 0 (kickoff) + offense-bot bank 4, LR×0.1 | 0 | kickoff+bot accepted (rehost) | anchor uniform + chain/stage-1/chain2/kickoff+bot | accepted Aug 19 19:30 — tds 0.746, vs-offbot 0.42, no dip (D249) |
| 3 | 0 (kickoff) + contact-bot bank 4, LR×0.1 | 0 | offense-bot rung accepted | promoted (anchor uniform) | accepted Aug 20 02:50 — tds 0.755, gate pass (D250) |

**Box 2 destroyed Aug 20 06:40 PDT (credit exhausted). No paid boxes. Frontier checkpoint = contact rung 2 (`1787193752314`), on the Mac in `scratchpad/box2-final/box2-final.tgz` with the two before it.**

Watch: `~/bin/v2watch`. Exams: `/root/native_exam.sh <ckpt> <outdir> away home offense mirror` (~4 min). Box 1 retired Aug 19 12:09 PDT (D247).

## Hill-climb from the July R0 warm (D252+)

| arm | warm | reward | LR | state |
|---|---|---|---|---|
| bridge 1 | July R0 s42 (bridge-v4) | s0_both | 2.8e-4 | **STOPPED at 522M (D253)**: tds 0.96 -> 0.46, pickups 3.4 -> 1.4, possession 0.30 -> 0.16, blocks 15 -> 21; s0_both pulls the policy into the non-play equilibrium |
| bridge 2 | July R0 s42 (bridge-v4) | s4_sparse (td/win/draw only) | 2.8e-4 | STOPPED at 360M (D254): tds 0.93 -> 0.85 but pickups 3.1 -> 1.9, blocks 12.8 -> 4.0 |
| bridge 3 | July R0 s42 (bridge-v4) | **r0_full** (the warm's own reward) | 2.8e-4 | **DONE 2B, eval tds 1.585 (D256); exam contact 0.433/0.435 & 0.388/0.456, offense 0.508/0.345 = project records** |
| chain 1 | bridge 3 output (`1787297626522`) | r0_full | 2.8e-4 (scale 1.0) | **DONE 3B** Aug 21 11:38 PDT, `runs/ladder-d0-r0chain1-20260821`, ckpt `1787314366343/0000002999975936.bin`, eval tds 1.555 / perf 0.627 (D257); **exam contact 0.486/0.433 & 0.463/0.416, offense 0.555/0.346 = every cell a new record** |
| chain 2 | chain 1 output (`1787314366343`) | r0_full | 2.8e-4, bot share **0.12** | **DONE 3B, eval tds 1.399 (D258); exam contact 0.491/0.426 & 0.462/0.384, offense 0.578/0.345: conceded down, kept** |
| chain 3 | chain 2 output (`1787338735330`) | r0_full | 5.6e-4 (scale 2.0), bot share 0.12 | DONE 3B, eval tds 1.724 (D259); exam contact 0.456/0.484 & 0.403/0.501, offense 0.522/0.424: **worse on every cell, LR x2 rejected** |
| chain 4 | chain 2 output (`1787338735330`) | r0_full | 2.8e-4, bot share 0.12, **offense bot (type 1)** | DONE 3B Aug 23 00:50 PDT, eval tds 1.655 (D260); exam contact 0.507/0.484 & 0.441/0.471, offense 0.583/0.351: offense-bot cell flat, conceded vs the contact bot up 0.06-0.09, **offense bot rejected** |
| chain 5 | chain 2 output (`1787338735330`) | r0_full | 2.8e-4, **entropy-only x2 (`LADDER_CHAIN_ENT_SCALE=2.0`, ent_coef 0.018)**, bot share 0.12, contact bot | DONE 3B Aug 23 08:58 PDT, eval tds 1.457 (D261); exam contact 0.467/0.400 & 0.429/0.386, offense 0.537/0.322: champion down on every cell, conceded down on two, **entropy x2 rejected** |
| chain 6 | chain 2 output (`1787338735330`) | r0_full | 2.8e-4, entropy scale 1.0, bot share 0.12, contact bot (no knob) | DONE 3B Aug 23 15:57 PDT, eval tds 1.576 (D262), ckpt `1787501452582/0000002999975936.bin`; exam s42 contact 0.521/0.444 & 0.453/0.430, offense 0.563/0.329: AWAY champion up, HOME conceded up; seed-43 re-exam 0.490/0.429 & 0.451/0.437, 0.569/0.335; two-seed mean 0.506/0.437, 0.452/0.434, 0.566/0.332 vs chain 2's 0.487/0.422, 0.450/0.391, 0.577/0.340: no champion cell up outside noise, HOME conceded +0.043 on both seeds; **REJECTED, chain 2 stays the frontier** (D263) |
| chain 7 | chain 2 output (`1787338735330`) | **r0_dist_half** (dist_ball 0.01, dist_endzone 0.02) | 2.8e-4, bot share 0.12, contact bot | DONE 3B Aug 23 23:28 PDT, eval tds 1.477 (D264), ckpt `1787528715578/0000002999975936.bin`; exam s42 contact 0.510/0.412 & 0.446/0.423, offense 0.519/0.326; s43 0.489/0.419 & 0.444/0.394, 0.523/0.325; two-seed mean 0.500/0.416, 0.445/0.409, 0.521/0.326: contact cells inside noise, offense champion -0.056, **r0_dist_half rejected** |
| chain 8 | chain 2 output (`1787338735330`) | **r0_dist_ball_half** (dist_ball 0.01, dist_endzone 0.04) | 2.8e-4, bot share 0.12, contact bot | DONE 3B Aug 24 07:20 PDT, eval tds 1.492 (D265), ckpt `1787556907250/0000002999975936.bin`; exam s42 contact 0.501/0.430 & 0.460/0.430, offense 0.556/0.368; s43 0.509/0.414 & 0.465/0.415, 0.542/0.354; two-seed mean 0.505/0.422, 0.463/0.423, 0.549/0.361: contact champion inside noise (+0.018, +0.013), offense champion -0.028 (down on both seeds), HOME conceded +0.032, **r0_dist_ball_half rejected** |
| chain 9 | chain 2 output (`1787338735330`) | **r0_poss_half** (possession 0.015, ball gain 0.05, distance terms at r0_full) | 2.8e-4, bot share 0.12, contact bot | DONE 3B Aug 24 14:53 PDT, eval tds 1.534 / perf 0.609 (D266), ckpt `1787584031608/0000002999975936.bin`; exam s42 contact 0.533/0.371 & 0.499/0.389, offense 0.578/0.327; s43 0.534/0.415 & 0.476/0.402, 0.572/0.345; two-seed mean 0.534/0.393, 0.488/0.396, 0.575/0.336: both contact champion cells up outside noise on both seeds, AWAY conceded down, offense flat, **ACCEPTED: new frontier** |
| chain 10 | chain 9 output (`1787584031608`) | **r0_poss_quarter** (possession 0.0075, ball gain 0.05, distance terms at r0_full) | 2.8e-4, bot share 0.12, contact bot | DONE 3B Aug 24 22:28 PDT, eval tds 1.672 / perf 0.560 (D267), ckpt `1787611542044/0000002999975936.bin`; exam s42 contact 0.511/0.397 & 0.483/0.389, offense 0.596/0.347; s43 0.521/0.418 & 0.491/0.401, 0.565/0.358; two-seed mean 0.516/0.408, 0.487/0.395, 0.581/0.353: every cell inside 0.02 of chain 9, AWAY champion -0.018 on both seeds, nothing clearly better; s44 0.502/0.406 & 0.461/0.404, 0.573/0.358; three-seed mean 0.511/0.407, 0.478/0.398, 0.578/0.354 vs chain 9 0.530/0.394, 0.484/0.395, 0.577/0.336: no cell outside 0.02 but 14 of 17 seed-cell comparisons adverse, AWAY net differential -0.032; **REJECTED (D268), chain 9 stays the frontier** |
| chain 11 | chain 9 output (`1787584031608`) | **r0_poss_half_gain_half** (possession 0.015, ball gain 0.025, distance terms at r0_full) | 2.8e-4, bot share 0.12, contact bot | DONE 3B Aug 25 06:07 PDT, eval tds 1.542 / perf 0.599 (D269), ckpt `1787639251082/0000002999975936.bin`; exam s42 contact 0.519/0.407 & 0.479/0.366, offense 0.594/0.309; s43 0.516/0.400 & 0.473/0.397, 0.570/0.301; two-seed mean 0.518/0.404, 0.476/0.382, 0.582/0.305 vs chain 9 0.534/0.393, 0.488/0.396, 0.575/0.336: AWAY champion -0.016 and net -0.027, HOME flat, offense conceded -0.031 on both seeds; s44 0.490/0.407 & 0.466/0.375, 0.571/0.303; three-seed mean 0.508/0.405, 0.473/0.379, 0.578/0.304 vs chain 9 0.530/0.394, 0.484/0.395, 0.577/0.336: AWAY champion -0.022 (down on all three seeds) and AWAY net -0.032, offense conceded -0.032 (best offense-bot defense recorded); **REJECTED (D270), chain 9 stays the frontier** |
| chain 12 | chain 9 output (`1787584031608`) | **r0_poss_half** (frontier reward) | **5.6e-4 (scale 2.0, entropy 0.018)**, bot share 0.12, contact bot | DONE 3B Aug 25 13:44 PDT, eval tds 1.652 / perf 0.572, ckpt `1787666718643`; **REJECTED** (D271): two-seed exam worse on every cell (conceded +0.031 / +0.022 / +0.068 on the mean); LR x2 loses on the annealed frontier too, knob retired |
| chain 13 | chain 9 output (`1787584031608`) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, **offense bot (type 1) in the bank seat** | DONE 3B Aug 25 20:47 PDT, eval tds 1.719 / perf 0.585, ckpt `1787692083254`; **REJECTED** (D272): two-seed exam concedes +0.070 / +0.063 / +0.050 vs chain 9 with no champion cell up, including the offense-bot cell it trained against; bank-seat bot swap retired |
| chain 14 | chain 9 output (`1787584031608`) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, contact bot, **no knob under test (plateau control)** | DONE 3B Aug 26 03:40 PDT, eval tds 1.614 / perf 0.573, ckpt `1787716871429`; **REJECTED** (D273): exam s42 contact 0.511/0.424 & 0.439/0.428, offense 0.579/0.320; s43 contact AWAY 0.496/0.406 (other s43 cells pending); contact AWAY champion -0.022 / -0.038 on the two seeds, HOME champion -0.060 on s42, conceded +0.053 / +0.039 on s42, offense flat. A plain continuation at frontier settings does not improve the exam: the recipe is plateaued |
| chain 15 | chain 9 output (`1787584031608`) | **r0_poss_half** (frontier reward) | **bot share 0.18** (the last knob on the brief's list) | **NEVER RAN** (D274): the launcher's config guard refused it before training - four frozen banks would reserve 736 rows of a 512-row budget (`apb` 1024, `4*int(apb*pct) < apb//2`), so the share ceiling is 0.124 and chain 2's promoted 0.12 already sits at it. The knob screen is over; raising bot exposure needs a code change, not a variable |
| chain 15h | **chain 14 output** (`1787716871429`) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, contact bot, **no knob: horizon probe** (cumulative 6B of continuation from chain 9) | DONE 3B Aug 26 11:14 PDT, eval tds 1.790 / perf 0.581, ckpt `1787744102664` (sha `a9cdc325`); **REJECTED** (D275): two-seed mean 0.512/0.433, 0.450/0.409, 0.594/0.368 vs chain 9's 0.534/0.393, 0.488/0.396, 0.575/0.336 - contact AWAY champion -0.022 / net -0.062, HOME champion -0.038 / net -0.051. Against chain 14's mean every cell moves by <=0.02: 6B of continuation lands where 3B did, so the horizon direction is answered negatively and no chain 16 is launched from this recipe |
| chain 16 | **chain 2** (`ladder-d0-r0chain2-20260821`, chain 9's own parent) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, contact bot, **no knob: SEED 42 -> 43 replicate of chain 9** | COMPLETE Aug 26 19:04 PDT (`runs/ladder-d0-r0chain16-seedrep-20260826`, ckpt `1787771854045/...2999975936.bin`). Noise-floor control, not a challenger. Result (D277): champion cells reproduce to 0.011, conceded cells move up to 0.086 from reseeding alone; conceded-driven rejections retracted as underpowered, champion-driven ones stand |
| chain 17 | chain 9 output (`1787584031608`) | **r0_blockev_half** (block-EV family halved) | 2.8e-4, bot share 0.12, contact bot, seed 42 | DONE Aug 27 02:40 PDT, 3B clean (error_episodes 0, illegal_frac 0). Exam seeds 42/43: contact champion flat, offense AWAY champion 0.599 two-seed mean (+0.028). Read as a candidate positive in D279a; **that read is RETRACTED by D281** - it was one training seed, and chain 18's replicate drops the pooled offense mean to +0.010 |
| chain 18 | chain 16 output (seed-43 twin of chain 9) | r0_blockev_half | 2.8e-4, bot share 0.12, contact bot, **seed 43** | DONE Aug 27 09:44 PDT, 3B clean at the exact step cap (error_episodes 0, illegal_frac 0), eval tds 1.688 / perf 0.578, ckpt `1787824919893/...2999975936.bin`. Exam s42 contact 0.527/0.441 & 0.504/0.418, offense 0.564/0.387; s43 0.517/0.440 & 0.488/0.455, 0.560/0.390. Pooled chains 17+18 mean 0.528/0.449, 0.492/0.438, 0.581/0.394 vs the chain 9 + chain 16 baseline 0.537/0.416, 0.492/0.406, 0.571/0.350: champion deltas -0.009 / -0.001 / +0.010, no cell clears the pre-registered +0.02 floor; **`r0_blockev_half` REJECTED** (D281), chain 9 stays the frontier |
| chain 19 | chain 16 output (seed-43 twin of chain 9) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, contact bot, seed 43, **no knob: FILLER** | DONE Aug 27 17:08 PDT, 3B clean at the exact step cap (error_episodes 0, illegal_frac 0), eval tds 1.767 / perf 0.559, ckpt `1787851696289/...2999975936.bin`. Exam s42 0.519/0.484, 0.494/0.455, 0.570/0.387; s43 0.546/0.481, 0.467/0.464, 0.591/0.399. Two-seed mean 0.533/0.483, 0.481/0.460, 0.581/0.393: **every champion cell inside 0.02 of the frontier**, and +0.029 / +0.037 above chain 14, the same-recipe seed-42 continuation. Not promoted (tests no hypothesis, D282); it weakens the one-seed plateau read instead (D283/D284) |
| chain 20 | **chain 9 output** (`1787584031608`, the same parent as chain 14) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, contact bot, **SEED 44, no knob: seed-only control** | DONE Aug 28 00:08 PDT, 3B clean at the exact step cap (error_episodes 0, illegal_frac 0), eval tds 1.620 / perf 0.578, ckpt `1787876979838/...2999975936.bin`. Exam s42 0.513/0.406, 0.465/0.420, 0.559/0.340; s43 0.496/0.409, 0.460/0.388, 0.555/0.344. Two-seed mean 0.505/0.408, 0.463/0.404, 0.557/0.342: **lands on chain 14 (+0.001 / +0.019 / -0.019), not on chain 19**, so the chain 14 vs chain 19 gap is the parent and not the training seed (D285). Not promoted |
| chain 21 | **chain 16 output** (same parent as chain 19) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, contact bot, **SEED 45, no knob: parent control** | DONE Aug 28 06:55 PDT, 3B clean at the exact step cap (error_episodes 0, illegal_frac 0), eval tds 1.767 / perf 0.561, ckpt `1787901832961/...2999975936.bin`. Exam s42 0.521/0.445, 0.469/0.465, 0.549/0.416; s43 0.524/0.473, 0.480/0.451, 0.576/0.423. Two-seed mean 0.5225/0.459, 0.4745/0.458, 0.5625/0.4195: **lands on chain 19 (-0.011 / -0.007 / -0.019 champion), not on chains 14/20 (+0.019 / +0.021 contact champion)**, so continuation IS parent-dependent - but the chain 16 parent concedes 0.05-0.06 more and has the worse net differential, and every cell is still below the frontier (D287). Not promoted |
| chain 22 | **chain 9 output** (the frontier, `1787584031608`) | **r0_poss_half_rush_zero** (`reward_rush_cost` 0.015 -> 0) | 2.8e-4, bot share 0.12, contact bot, **SEED 42, knob: the last un-annealed shaping term** | DONE Aug 28 14:18 PDT, 3B clean at the exact step cap (error_episodes 0, illegal_frac 0, `reward_component_rush` exactly 0.0), eval tds 1.700 / perf 0.585, ckpt `1787926845500/...2999975936.bin`. Exam s42 0.496/0.405, 0.442/0.447, 0.560/0.358; s43 0.491/0.427, 0.474/0.434, 0.548/0.352. Two-seed mean 0.4935/0.416, 0.458/0.4405, 0.554/0.355: vs the paired chain 14 champion **-0.010 / +0.0145 / -0.0215**, both contact cells inside the 0.02 floor and the only cell clearing it moving against the knob. **REJECTED; the rush fine is exonerated and the reward anneal is finished** (D289) |
## AUDIT 2026-08-20 (D252): the obs-v6 lineage was frozen by its recipe; the July policy is ~6x better

`docs/audit-2026-08-20.md`. Chained rungs at `LADDER_CHAIN_LR_SCALE=0.1` had kl/clipfrac 0.000 on 38,206/38,207 updates (not training); the native optimizer is Muon (lr = relative step, ours 2-50x below reference); reward is 94% shaping and the TD step nets -0.56 to the scorer; training `tds` is a both-sides mixture. Campaign `rig-s42-bot-20260820` HALTED, rung 2 stopped, timers off. Next: bridge July R0 s42 onto the current build (reviewed `bridge` lineage mode) and hill-climb from there: LR probe, sparse-reward arm, bot share, entropy, gamma.

| stage | rung | warm | pool | state |
|---|---|---|---|---|
| 1 | kickoff + contact-bot bank 4, LR x0.1 (graft) | s42-kickoff (pure-pool control) | s42-kickoff pool | done Aug 20 19:13, eval tds 0.489; exam contact 0.056/1.224 AWAY, 0.046/1.224 HOME, offense 0.060/0.649 (D252: recipe was frozen) |
| 2 | kickoff + offense-bot bank 4 | stage 1 | promoted | STOPPED at 1.1B (D252) |

## Completed campaign: `rig-seed42-20260818` (RTX 2070, seed-42 replicate of the uniform chain)

| stage | rung | reset | warm | pool | state |
|---|---|---|---|---|---|
| 1 | 0 (uniform) | 0.5 | Vast stage-1 accepted (rehosted) | rung-12/uniform/chain/stage-1 (`ce9042f6`) | accepted Aug 19 00:20 — **tds 0.647** (replicates seed-43 chain2 0.652) |
| 2 | 0 | 0.25 | s42 stage-1 | anchor rung12 + chain/stage-1/s42 (`5a831aa4`) | accepted Aug 19 ~13:00 at **0.334** (hot-restart dip, half-recovered; D248) |
| 3 | 0 (kickoff) | 0, LR×0.1 | s42 r25 | promoted | accepted Aug 20 ~01:00 — tds 0.437, no dip; pure-pool control, exam pending (D250) |
| 3 | 0 (kickoff) | 0 | s42 stage-2 | promoted | queued |

## Kickoff exam (D50) — the scoreboard (TD/game vs contact bot, full games from kickoff)

| checkpoint | path | AWAY champ/bot | HOME champ/bot | mirror TD/g |
|---|---|---|---|---|
| chain2 (uniform@0.5) [torch] | D241 | 0.052 / 1.281 | 0.035 / 1.276 | 0.951 |
| r25 (→ uniform@0.25) [torch] | D246 | 0.038 / 1.150 | 0.025 / 1.211 | — |
| r25 [native] | D247 | 0.043 / 1.118 | 0.037 / 1.131 | offense-bot AWAY 0.101 / 0.587 |
| **kickoff+bot** [torch] | D246 | 0.102 / 0.997 | 0.052 / 1.065 | — |
| **kickoff+bot** [native] | D247 | **0.091 / 1.023** | **0.069 / 0.975** | **offense-bot AWAY 0.152 / 0.538** |
| **+offense-bot rung** [native] | D249 | 0.077 / 1.029 | 0.068 / 1.009 | **offense-bot AWAY 0.151 / 0.405**; mirror 0.765 |
| **+contact rung 2** [native] | D250 | **0.083 / 0.993** | **0.088 / 1.028** | offense-bot AWAY 0.160 / 0.459; mirror 0.803 |
| s42-kickoff pure-pool control (seed 42, no bot) [native] | D250 add. | 0.023 / 1.292 | 0.016 / 1.282 | offense-bot AWAY 0.027 / 0.683 |
| s42 + contact-bot rung 1 (LR x0.1, frozen recipe) [native] | D252 | 0.056 / 1.224 | 0.046 / 1.224 | offense-bot AWAY 0.060 / 0.649 |
| July R0 s42 (obs-v4 era, 2026-07-13) on the CURRENT build [native, diagnostic] | D252 | 0.354 / 0.438 | 0.346 / 0.447 | offense-bot AWAY 0.392 / 0.334 (score 0.541); 18 blocks, 6.2 pickups |
| **bridge 3 = July R0 s42 + r0_full + bot bank, 2B** [native] | D256 | **0.433 / 0.435** | **0.388 / 0.456** | **offense-bot AWAY 0.508 / 0.345** |
| **chain 1 = bridge 3 + 3B more under r0_full (bot share 0.06)** [native] | D257 | **0.486 / 0.433** | **0.463 / 0.416** | **offense-bot AWAY 0.555 / 0.346** |
| **chain 2 = +bot share 0.12, 3B** [native] | D258 | **0.491 / 0.426** | **0.462 / 0.384** | **offense-bot AWAY 0.578 / 0.345** |
| chain 3 = LR x2 (rejected) [native] | D259 | 0.456 / 0.484 | 0.403 / 0.501 | offense-bot AWAY 0.522 / 0.424 |
| chain 4 = offense bot in the bank seat (rejected) [native] | D260 | 0.507 / 0.484 | 0.441 / 0.471 | offense-bot AWAY 0.583 / 0.351 |
| chain 5 = entropy-only x2 (rejected) [native] | D261 | 0.467 / 0.400 | 0.429 / 0.386 | offense-bot AWAY 0.537 / 0.322 |
| chain 18 = r0_blockev_half seed 43, exam s42 [native] | D281 | 0.527 / 0.441 | 0.504 / 0.418 | offense-bot AWAY 0.564 / 0.387 |
| chain 18, exam s43 [native] | D281 | 0.517 / 0.440 | 0.488 / 0.455 | offense-bot AWAY 0.560 / 0.390 |
| **r0_blockev_half pooled arm mean (chains 17+18 x exam seeds 42/43)** [native] | D281 | 0.528 / 0.449 | 0.492 / 0.438 | offense-bot AWAY 0.581 / 0.394 (**rejected vs baseline 0.537/0.416, 0.492/0.406, 0.571/0.350**) |
| chain 6 = plain r0 continuation from chain 2, seed 42 [native] | D262 | 0.521 / 0.444 | 0.453 / 0.430 | offense-bot AWAY 0.563 / 0.329 |
| chain 2 seed-43 re-exam [native] | D263 | 0.482 / 0.417 | 0.438 / 0.397 | offense-bot AWAY 0.575 / 0.335 |
| chain 6 seed-43 re-exam [native] | D263 | 0.490 / 0.429 | 0.451 / 0.437 | offense-bot AWAY 0.569 / 0.335 |
| **chain 2 two-seed mean (42+43), the frontier baseline** [native] | D263 | **0.487 / 0.422** | **0.450 / 0.391** | offense-bot AWAY **0.577 / 0.340** |
| chain 6 two-seed mean (42+43) [native] | D263 | 0.506 / 0.437 | 0.452 / 0.434 | offense-bot AWAY 0.566 / 0.332 |
| chain 7 = r0_dist_half (both distance terms halved), seed 42 [native] | D264 | 0.510 / 0.412 | 0.446 / 0.423 | offense-bot AWAY 0.519 / 0.326 |
| chain 7 seed 43 [native] | D264 | 0.489 / 0.419 | 0.444 / 0.394 | offense-bot AWAY 0.523 / 0.325 |
| chain 7 two-seed mean (rejected: offense champion -0.056) [native] | D264 | 0.500 / 0.416 | 0.445 / 0.409 | offense-bot AWAY 0.521 / 0.326 |
| chain 8 = r0_dist_ball_half (ball-distance term alone halved), seed 42 [native] | D265 | 0.501 / 0.430 | 0.460 / 0.430 | offense-bot AWAY 0.556 / 0.368 |
| chain 8 seed 43 [native] | D265 | 0.509 / 0.414 | 0.465 / 0.415 | offense-bot AWAY 0.542 / 0.354 |
| chain 8 two-seed mean (rejected: offense champion -0.028 on both seeds, HOME conceded +0.032) [native] | D265 | 0.505 / 0.422 | 0.463 / 0.423 | offense-bot AWAY 0.549 / 0.361 |
| chain 9 = r0_poss_half (possession annuity alone halved), seed 42 [native] | D266 | 0.533 / 0.371 | 0.499 / 0.389 | offense-bot AWAY 0.578 / 0.327 |
| chain 9 seed 43 [native] | D266 | 0.534 / 0.415 | 0.476 / 0.402 | offense-bot AWAY 0.572 / 0.345 |
| chain 9 two-seed mean (ACCEPTED, new frontier: contact champion +0.047 / +0.038, AWAY conceded -0.029, offense flat) [native] | D266 | 0.534 / 0.393 | 0.488 / 0.396 | offense-bot AWAY 0.575 / 0.336 |
| chain 10 = r0_poss_quarter (possession annuity quartered), seed 42 [native] | D267 | 0.511 / 0.397 | 0.483 / 0.389 | offense-bot AWAY 0.596 / 0.347 |
| chain 10 seed 43 [native] | D267 | 0.521 / 0.418 | 0.491 / 0.401 | offense-bot AWAY 0.565 / 0.358 |
| chain 10 two-seed mean (inside 0.02 of chain 9 on every cell, AWAY champion -0.018 on both seeds; seed-44 re-exam of both pending) [native] | D267 | 0.516 / 0.408 | 0.487 / 0.395 | offense-bot AWAY 0.581 / 0.353 |
| chain 9 seed 44 [native] | D268 | 0.524 / 0.396 | 0.478 / 0.394 | offense-bot AWAY 0.582 / 0.337 |
| chain 10 seed 44 [native] | D268 | 0.502 / 0.406 | 0.461 / 0.404 | offense-bot AWAY 0.573 / 0.358 |
| chain 9 three-seed mean (42/43/44; FRONTIER baseline to beat) [native] | D268 | 0.530 / 0.394 | 0.484 / 0.395 | offense-bot AWAY 0.577 / 0.336 |
| chain 10 three-seed mean (REJECTED: no cell outside 0.02 but adverse in 14 of 17 seed-cell comparisons, AWAY net differential -0.032) [native] | D268 | 0.511 / 0.407 | 0.478 / 0.398 | offense-bot AWAY 0.578 / 0.354 |
| chain 11 = r0_poss_half_gain_half (ball gain halved, annuity at the accepted half), seed 42 [native] | D269 | 0.519 / 0.407 | 0.479 / 0.366 | offense-bot AWAY 0.594 / 0.309 |
| chain 11 seed 43 [native] | D269 | 0.516 / 0.400 | 0.473 / 0.397 | offense-bot AWAY 0.570 / 0.301 |
| chain 11 two-seed mean (split: contact AWAY champion -0.016 and net -0.027, offense conceded -0.031 on both seeds; seed-44 re-exam pending) [native] | D269 | 0.518 / 0.404 | 0.476 / 0.382 | offense-bot AWAY 0.582 / 0.305 |
| chain 11 seed 44 [native] | D270 | 0.490 / 0.407 | 0.466 / 0.375 | offense-bot AWAY 0.571 / 0.303 |
| chain 11 three-seed mean (REJECTED: contact AWAY champion -0.022 and net -0.032 vs chain 9; offense conceded -0.032 is the lowest recorded) [native] | D270 | 0.508 / 0.405 | 0.473 / 0.379 | offense-bot AWAY 0.578 / 0.304 |
| chain 12 = LR x2 (5.6e-4, entropy 0.018) under r0_poss_half from chain 9, seed 42 [native] | D271 | 0.516 / 0.435 | 0.468 / 0.419 | offense-bot AWAY 0.562 / 0.395 |
| chain 12 seed 43 [native] | D271 | 0.526 / 0.413 | 0.469 / 0.417 | offense-bot AWAY 0.558 / 0.412 |
| chain 12 two-seed mean (REJECTED: no cell improves on either seed, conceded +0.031 / +0.022 / +0.068 vs chain 9, net down 0.04-0.08 everywhere; LR knob retired) [native] | D271 | 0.521 / 0.424 | 0.469 / 0.418 | offense-bot AWAY 0.560 / 0.404 |
| chain 13 = offense bot (type 1) in the bank seat under r0_poss_half from chain 9, seed 42 [native] | D272 | 0.535 / 0.463 | 0.506 / 0.474 | offense-bot AWAY 0.562 / 0.379 |
| chain 13 seed 43 [native] | D272 | 0.530 / 0.463 | 0.492 / 0.443 | offense-bot AWAY 0.585 / 0.393 |
| chain 13 two-seed mean (REJECTED: conceded +0.070 / +0.063 / +0.050 vs chain 9, net down 0.05-0.07 on every cell, no champion cell up outside noise; the offense-bot cell it trained against is worse on both sides) [native] | D272 | 0.533 / 0.463 | 0.499 / 0.459 | offense-bot AWAY 0.574 / 0.386 |
| chain 14 = plateau control (plain 3B continuation, no knob) from chain 9, seed 42 [native] | D273 | 0.511 / 0.424 | 0.439 / 0.428 | offense-bot AWAY 0.579 / 0.320 |
| chain 14 seed 43 [native] | D274 | 0.496 / 0.406 | 0.448 / 0.392 | offense-bot AWAY 0.572 / 0.369 |
| chain 14 two-seed mean (REJECTED: contact AWAY champion -0.031 and HOME -0.045 vs chain 9, both down on both seeds, net differential -0.052 / -0.058; offense cell flat) [native] | D274 | 0.504 / 0.415 | 0.444 / 0.410 | offense-bot AWAY 0.576 / 0.345 |
| chain 15h = horizon probe (6B cumulative continuation from chain 9), seed 42 [native] | D275 | 0.503 / 0.415 | 0.434 / 0.412 | offense-bot AWAY 0.579 / 0.356 |
| chain 15h seed 43 [native] | D275 | 0.520 / 0.450 | 0.466 / 0.406 | offense-bot AWAY 0.609 / 0.380 |
| chain 15h two-seed mean (REJECTED: contact AWAY champion -0.022 / net -0.062 and HOME -0.038 / net -0.051 vs chain 9; within 0.02 of chain 14 on every cell, so more steps do not recover the plateau) [native] | D275 | 0.512 / 0.433 | 0.450 / 0.409 | offense-bot AWAY 0.594 / 0.368 |
| chain 16 = SEED REPLICATE of chain 9 (recipe identical, seed 42 -> 43), seed 42 [native] | D277 | 0.536 / 0.457 | 0.505 / 0.413 | offense-bot AWAY 0.572 / 0.367 |
| chain 16 seed 43 [native] | D277 | 0.541 / 0.421 | 0.487 / 0.419 | offense-bot AWAY 0.561 / 0.360 |
| chain 16 two-seed mean (NOISE FLOOR, not a challenger: champion +0.005 / +0.008 vs chain 9 = reproducible; conceded +0.046 / +0.020 and AWAY net -0.041 from reseeding alone = the conceded cells cannot be read from one run) [native] | D277 | 0.539 / 0.439 | 0.496 / 0.416 | offense-bot AWAY 0.567 / 0.364 |
| chain 17 = r0_blockev_half (block-EV family halved) from chain 9, seed 42 [native] | D279 | 0.517 / 0.432 | 0.500 / 0.434 | offense-bot AWAY 0.613 / 0.392 |
| chain 17 seed 43 [native] | D279a | 0.552 / 0.484 | 0.474 / 0.444 | offense-bot AWAY 0.585 / 0.405 |
| chain 17 two-seed mean (CANDIDATE POSITIVE, not promoted: contact champion flat at -0.003 / -0.005 and direction-inconsistent, but the OFFENSE champion cell is +0.028 vs the chain 9 + chain 16 pooled mean and up on both exam seeds, the first cell moved outside the champion floor since chain 9; conceded not scored at one training seed) [native] | D279a | 0.535 / 0.458 | 0.487 / 0.439 | offense-bot AWAY 0.599 / 0.399 |
| chain 19 = plain continuation (no knob) from chain 16, seed 43, exam s42 [native] | D283 | 0.519 / 0.484 | 0.494 / 0.455 | offense-bot AWAY 0.570 / 0.387 |
| chain 19, exam s43 [native] | D283 | 0.546 / 0.481 | 0.467 / 0.464 | offense-bot AWAY 0.591 / 0.399 |
| chain 19 two-seed mean (NOT promoted: champion cells -0.005 / -0.012 / +0.010 vs the chain 9 + chain 16 pooled mean = on the frontier, and +0.029 / +0.037 / +0.005 vs chain 14, the same-recipe seed-42 continuation; conceded up 0.048-0.068 vs chain 14, not scored) [native] | D283 | 0.533 / 0.483 | 0.481 / 0.460 | offense-bot AWAY 0.581 / 0.393 |
| chain 20 = plain continuation (no knob) from chain 9, SEED 44, exam s42 [native] | D285 | 0.513 / 0.406 | 0.465 / 0.420 | offense-bot AWAY 0.559 / 0.340 |
| chain 20, exam s43 [native] | D285 | 0.496 / 0.409 | 0.460 / 0.388 | offense-bot AWAY 0.555 / 0.344 |
| chain 20 two-seed mean (NOT promoted: +0.001 / +0.019 / -0.019 vs chain 14, the same-parent seed-42 continuation, so the seed is not the explanation for the chain 19 outlier; -0.033 / -0.030 / -0.014 vs the chain 9 + chain 16 pooled frontier, reinstating the D273/D274 plateau read on two training seeds) [native] | D285 | 0.505 / 0.408 | 0.463 / 0.404 | offense-bot AWAY 0.557 / 0.342 |
| chain 21 = plain continuation (no knob) from chain 16, SEED 45, exam s42 [native] | D287 | 0.521 / 0.445 | 0.469 / 0.465 | offense-bot AWAY 0.549 / 0.416 |
| chain 21, exam s43 [native] | D287 | 0.524 / 0.473 | 0.480 / 0.451 | offense-bot AWAY 0.576 / 0.423 |
| chain 21 two-seed mean (NOT promoted: -0.011 / -0.007 / -0.019 champion vs chain 19, its same-parent twin, so chain 19 was not one high draw; +0.019 / +0.021 contact champion vs the chain 14 / chain 20 chain-9-parent pair but +0.05 to +0.06 conceded, and net differential 0.064 / 0.017 against their 0.089-0.097 / 0.034-0.059; -0.015 / -0.018 / -0.009 champion vs the pooled frontier) [native] | D287 | 0.5225 / 0.459 | 0.4745 / 0.458 | offense-bot AWAY 0.5625 / 0.4195 |
| chain 22 = `reward_rush_cost` 0.015 -> 0 from chain 9, SEED 42, exam s42 [native] | D289 | 0.496 / 0.405 | 0.442 / 0.447 | offense-bot AWAY 0.560 / 0.358 |
| chain 22, exam s43 [native] | D289 | 0.491 / 0.427 | 0.474 / 0.434 | offense-bot AWAY 0.548 / 0.352 |
| chain 22 two-seed mean (NOT promoted: vs its paired same-parent same-seed comparator chain 14 the champion cells are -0.010 / +0.0145 / -0.0215, the two contact cells inside the 0.02 floor with opposite signs and the offense cell down on both seeds; -0.0435 / -0.034 / -0.017 champion vs the pooled frontier) [native] | D289 | 0.4935 / 0.416 | 0.458 / 0.4405 | offense-bot AWAY 0.554 / 0.355 |

Verdict (revised D257): the bridged July lineage, continued under its own reward at full LR, is the live frontier; two rungs (2B + 3B) raised every champion cell twice over, and chain 1 also cut the HOME conceded rate by 0.04. Conceded AWAY is the flat cell; chain 2 doubled the bot share (0.12) and cut it. Chain 2 is the frontier: all three probes from it (LR x2, offense bot, entropy x2) lost on the exam, and training the bank seat without the contact bot gave back 0.06-0.09 conceded TD/game on the contact cells (D260). Chain 6 (plain continuation) split the cells on seed 42 (D262) and lost on the two-seed mean (D263: HOME conceded +0.043 on both seeds, no champion cell up outside noise). Every exam before D263 is the seed-42 draw and chain 2 won on that draw; its seed-43 read is lower on every champion cell, so the baseline to beat is now the chain 2 two-seed mean (0.487/0.422, 0.450/0.391, 0.577/0.340) and every challenger is examined on seeds 42 and 43. Four rungs from chain 2 under r0_full have failed to improve the exam: the recipe has plateaued, and the reward anneal began with chain 7 (r0_dist_half, both distance terms halved). Chain 7 held every contact cell inside noise on the two-seed mean but lost 0.056 on the offense-bot champion cell on both seeds (D264), so it was rejected. Chain 8 annealed the ball-distance term alone (r0_dist_ball_half) and lost the same cell by about half as much (-0.028, down on both seeds) while conceding 0.032 more at HOME (D265): at this capability the distance scaffold is still load-bearing for scoring against the uncontested opponent, so the anneal has moved to the D178 possession-vs-ball-gain decomposition; chain 9 halves the possession annuity alone (r0_poss_half) from chain 2. Chain 9 is the first accepted rung since chain 2 (D266): with the annuity halved and ball gain intact, both contact champion cells rose outside noise on both seeds (two-seed mean 0.534/0.393, 0.488/0.396, 0.575/0.336 against chain 2's 0.487/0.422, 0.450/0.391, 0.577/0.340), AWAY conceded fell, and the offense-bot cell was flat; the ball-gain term alone appears to carry the D178 defensive transfer and the per-turn holding term was over-paid. Chain 9 is the frontier and the baseline to beat is its two-seed mean; chain 10 quarters the annuity (r0_poss_quarter) from the chain 9 marker. Chain 10 (D267) came back inside the 0.02 band on every cell of the two-seed mean (0.516/0.408, 0.487/0.395, 0.581/0.353) but no cell improved and the contact AWAY champion cell fell 0.018 on both seeds, so both checkpoints are being re-examined on seed 44 and the verdict is taken on the three-seed mean: non-inferior keeps chain 10 and launches r0_poss_zero from it, a cell outside 0.02 rejects it and launches the ball-gain half step from chain 9. The seed-44 re-exam (D268) settled it: on the three-seed mean no cell crosses 0.02, but chain 10 is adverse in 14 of 17 seed-cell comparisons and its contact AWAY net TD differential is down 0.032, so the quarter annuity is read as a small real regression and chain 10 is rejected; chain 9 stays the frontier (three-seed mean 0.530/0.394, 0.484/0.395, 0.577/0.336). Later anneal steps are kept only if no cell moves against the frontier by more than 0.02 AND no cell's net differential drops by more than 0.02 on the multi-seed mean. Chain 11 (r0_poss_half_gain_half: ball gain 0.05 -> 0.025 with the annuity at the accepted 0.015) is the other half of the D178 decomposition; its two-seed exam (D269) splits the cells (contact AWAY champion -0.016 and net -0.027, offense-bot conceded -0.031 on both seeds), so a seed-44 re-exam decides it on the three-seed mean. The seed-44 read (D270) rejects it: on the three-seed mean the contact AWAY champion cell is down 0.022 (on all three seeds) and its net differential down 0.032, past both D268 thresholds, although chain 11 concedes the fewest offense-bot TDs recorded (0.304). Both anneal steps from chain 9 are rejected, the reward anneal is parked at r0_poss_half, and chain 12 retries LR x2 on the chain 9 frontier under r0_poss_half. Chain 12 lost LR x2 a second time on the seed-42 draw and the LR knob is retired (D271). Chain 13 put the OFFENSE bot in the bank seat under r0_poss_half: on the two-seed mean it concedes 0.070 / 0.063 / 0.050 more TD/game than chain 9 on the three cells with no champion cell up outside noise, and the offense-bot cell it trained against is worse on both sides (0.574/0.386 against 0.575/0.336), so it is rejected and the bank-seat bot swap is retired for the second time (D260 saw the same 0.06-0.09 conceded giveback from chain 2). Five consecutive knobs from chain 9 have failed, so chain 14 was a plain 3B continuation at frontier settings with no knob under test: the plateau control that separates "every knob tried is bad" from "the lineage is done improving" (D272). It answers the second way (D273): 3B more steps with nothing changed reproduce chain 9's training telemetry to within panel noise and lose the exam - contact AWAY champion -0.022 / -0.038 on seeds 42 and 43, contact HOME champion -0.060 on seed 42, conceded up 0.053 and 0.039 on seed 42, offense-bot cell flat. So the baseline that chains 10-13 were measured against is one that further training alone cannot beat either, and the lineage is plateaued at the recipe level rather than having been handed four bad knobs. The full two-seed exam confirms that rejection (D274: chain 14 mean 0.504/0.415, 0.444/0.410, 0.576/0.345, contact AWAY champion -0.031 and HOME -0.045, both down on both seeds). The knob screen is now over for a second reason: bot share 0.18 was never available. The launcher caps the frozen-bank share at 0.124 (four banks reserve `4*int(1024*pct)` rows of a 512-row budget) and chain 2's promoted 0.12 already sits at that ceiling, so the 0.18 rung was refused before training and no knob from the brief's list remains (D274). The campaign's own recommendation is therefore a structural change - opponent population (which now demonstrably needs an env/launcher change, not a variable), horizon, or a capability `r0_poss_half` cannot express at this policy scale. Chain 15h tests the cheapest of the three with no new code: 3B more from the chain 14 marker, i.e. cumulative 6B of frontier-settings continuation from chain 9. If it also fails to move the exam, the horizon direction is answered negatively too and the decision in front of Alex is which structural change to fund.  Chain 15h answers it negatively (D275): 6B cumulative of frontier-settings continuation lands within 0.02 of chain 14's 3B on every exam cell and still loses both contact cells to chain 9, while training-side tds keeps climbing (1.54 chain 9, 1.61 chain 14, 1.79 chain 15h) - a three-point demonstration that self-play/bank tds is not a proxy for kickoff strength. No chain 16 is launched. The knob screen and the horizon direction are both closed, chain 9 remains the frontier at 0.534/0.393, 0.488/0.396, 0.575/0.336, and the two directions left both need a decision above the loop: (a) opponent population, which needs an env/launcher change because the frozen-bank share is at its arithmetic ceiling of 0.124, or (b) a capability r0_poss_half cannot express at this policy scale. The rig is deliberately idle until Alex names one. Before that decision is put to Alex, D276 supplies the control the screen never had: every arm since the bridge has been a single run at a single training seed, so the 0.02-0.06 gaps that rejected six challengers have never been compared against the pipeline's own run-to-run variance - and two of those six (chains 14 and 15h) were pure continuations of chain 9's recipe that lost by the same margin as the knobs did, which is what a baseline reading high looks like. Chain 16 reruns chain 9 verbatim at seed 43 from chain 9's own parent marker. If merely reseeding costs as much exam as any knob did, the six rejections are underpowered rather than negative and arms need replicates before anything further is believed; if it lands inside 0.02 on every cell, chain 9's frontier status is earned and D275's structural recommendation stands on a measured noise floor. Chain 9 remains the frontier either way. Chain 16 landed (D277) and split the reading along an axis that was not pre-registered: the CHAMPION cells reproduce across independent training runs to within 0.011 (six seed-cell pairs at +0.003, +0.006, -0.006, +0.007, +0.011, -0.011; two-seed champion means +0.005, +0.008 and -0.009 against chain 9), while the CONCEDED cells move up to 0.086 on a single exam draw and +0.046 on the two-seed mean, with the contact-AWAY net differential down 0.041, from changing nothing but the training seed. So D268's uniform 0.02 thresholds are withdrawn for conceded and net; the conceded-driven rejections (chain 12 LR x2, chain 13 offense bot, and the net halves of chains 10 and 11) are retracted as underpowered rather than negative, and the two earlier "second loss" retirements of those same two knobs are two single-run draws each, not replications. The champion-driven rejections stand at 2x-5x the measured floor and moved the same direction on every seed, which includes chains 14 and 15h, so D275's finding that the horizon direction is closed and the plateau is real is unaffected. Going forward, defensive or net hypotheses need at least two training seeds per arm and a 0.05 conceded floor; scoring hypotheses can still be read from one run against 0.02. Chain 9 stays the frontier and the structural decision from D275 stands, now with a measured instrument attached to it: the campaign can resolve a hundredth of a TD/game of scoring and cannot resolve less than a twentieth of a TD/game of defense from one run. Chain 17 (D278) spends the otherwise-idle overnight GPU on the one shaping family the anneal never walked: chains 7-11 moved distance, the possession annuity and ball gain, but the block-EV terms (`reward_k_kd` 0.1, `reward_k_value` 0.5, `reward_k_ball` 0.15, `reward_k_seq` 0.03, `reward_k_turnover` 0.15) were never touched, and they are the largest remaining shaping mass in `r0_poss_half`. They enter `bloodbowl.h:3574-3625` as a linear weighted sum over pre-roll `bb_block_ev` probabilities, so the new `r0_blockev_half` arm halves all five and preserves every relative weight. It is launched with its power limits pre-registered: champion cells judged from this one training seed at a 0.02 floor against the chain 9 + chain 16 pooled mean (0.537/0.416, 0.492/0.406, 0.571/0.350), conceded and net not scored at all, and chain 18 (same arm, seed 43, from the chain 16 marker) queued as the seed-matched replicate. The structural decision from D275 is unchanged and still Alex's. Chain 20 (D285) closes the confound D284 left open: it is chain 14's recipe and parent at a third training seed, and its two-seed mean of 0.505/0.408, 0.463/0.404, 0.557/0.342 lands on chain 14 (+0.001 / +0.019 / -0.019), not on chain 19. So the training seed does not explain the chain 14 vs chain 19 gap, four exam draws from two independent training seeds off the chain 9 parent all read about 0.50 / 0.46 on the contact champion cells against chain 9's own 0.53 / 0.49, and D273/D274's plateau finding for this parent is reinstated while D284's procedural withdrawal of the 0.02 single-run champion floor stands. The one live alternative is that continuation is parent-dependent, since chain 19's frontier-level read is a single run from the chain 16 parent; chain 21 (D286) is its seed-45 replicate from that same parent and decides between parent-dependence and a high exam draw. Chain 21 (D287) settles it: its two-seed mean of 0.5225/0.459, 0.4745/0.458, 0.5625/0.4195 lands on chain 19 (-0.011 / -0.007 / -0.019 champion, inside the measured floor) and above the chain 9 parent's continuations by +0.019 / +0.021 on the contact champion cells, so continuation is parent-dependent and chain 19 was not a high exam draw - but the same eight draws show the chain 16 parent conceding 0.05-0.06 more on every cell and holding the worse net differential (contact AWAY 0.050-0.064 against 0.089-0.097, both under chain 9's 0.121), so that lineage is a more open policy rather than a better one and earns no hypothesis rung. Every continuation from either parent still loses to chain 9, so the plateau stands on four training seeds across two parents. Chain 22 (D288) spends the rig on the one nonzero shaping coefficient in r0_poss_half no arm has ever varied: `reward_rush_cost` 0.015 -> 0 (arm `r0_poss_half_rush_zero`), from the chain 9 frontier at seed 42, paired against chain 14. The structural decision from D275 remains Alex's. Chain 22 (D289) rejects it: the two-seed mean of 0.4935/0.416, 0.458/0.4405, 0.554/0.355 puts both contact champion cells inside the 0.02 floor against chain 14 with opposite signs (-0.010 and +0.0145) and the only cell that clears the floor, offense AWAY at -0.0215, moves against the knob on both seeds, so a standing per-attempt Rush fine was not a brake on scoring and removing it costs about 0.02 TD/game of offense. That empties the shaping inventory: distance, the possession/ball-gain decomposition, the block-EV family and the rush fine have each been varied one at a time from r0_poss_half and every one is null or negative, leaving only `reward_td` 0.4 and `reward_win` 0.6, which are the objective. With the knob screen closed twice, the horizon direction closed, five plain continuations flat across two parents and four training seeds, and no reward arm ever beating the plain lineage, the loop has exhausted every direction below D275's structural decision. Chain 9 remains the frontier and the rig is deliberately idle rather than spending a sixth replicate of a settled null.

## Kickoff exam (D50) — chain2 checkpoint, 2026-08-18

Full games from kickoff, frozen, torch: vs contact bot AWAY champion **0.052** TD/g / bot 1.281 (2,017 g); vs contact bot HOME champion **0.035** / bot 1.276 (2,003 g); mirror self-play 0.951 TD/g total, possession 0.199, blocks 9.2 (human 2.2 / 0.475 / 80). Verdict D241: scores from kickoff vs itself, not under scripted contact pressure → graduation rungs need a scripted-opponent share.

Watch: `~/bin/vwatch`. Rig watch: `~/bin/bbwatch`. Cross-host moves use
`checkpoint_lineage.py rehost` (D238).

## Next after the chain

1. Kickoff graduation (reset 0.25 → 0) and the D50 exam: full-game
   tournament from kickoff vs the genesis pool + scripted contact bot
   (`tools/eval_vs_contact_bot.sh` after `training/convert_checkpoint.py`).
2. Second seed of the whole chain (seed 42) for a replicate before any claim.
3. Then the reward program resumes on a policy that can score from kickoff:
   the possession/gain decomposition (D229/D233) is uninterpretable on
   scoreless policies.

## Replay and BC state

Unchanged since 2026-07-13: 9,118 strict BB2025 replays / 1,622,231 joined
records; corpus is opening-censored; replay-first sampling is the default.

## Verification and deployment state

Rig checkout `/home/rache/bloodbowl-rl-qualification-candidate-10619e2` at
`8ecf8a6` (clean `--float` rebuild, drift check OK, genesis root and pool
re-validated against the rebuilt module). BBTV production checkout untouched.
Vast credit is exhausted (balance −$2.96); the 2070 is the only trainer.

**Update 2026-10-05 22:45 PDT (D418 amendments): the b3 build passed its identity check on the third attempt; the canary is running.** Two failed attempts came from the stage script asking the trace probe for more than the trainer's 64 MiB snapshot cap; fixed without changing the pass criteria. Chains 55 (plain), 56 (rule) and 57 (bot seat) from chain 49 follow. The registration was tightened after review: a candidate must also beat chain 49 on the held-out opponents, and a positive chain 57 makes the seat change a candidate, not an adopted change.

**Update 2026-10-06 08:55 (D419): chain 55 reads Inconclusive; chain 49 stays the warm start.** The plain continuation beats chain 49 directly by +101.3 decisive-Elo and does better than it against chain 46 (+60.9), but no improvement is established against chain 37 (-1.7 [-21.9, +19.3]) or the offense bot (-13.1 [-35.8, +8.6]). Chain 55 is the accepted control for chain 56 (training now, the rule arm) and chain 57 (the bot-seat arm).

**Update 2026-10-06 17:50 (D420, D421): chain 56, trained under the no-early-END_TURN rule, reads Inconclusive; chain 49 stays the warm start.** Played under the mask against its masked control it is +52.6 [+39.0, +68.1] directly, +26.2 [+3.1, +49.8] against chain 37 and -7.1 [-30.2, +13.6] against chain 46. Under the mask it makes 7.07 activations per team turn with 3.16 of them empty (control: 6.78 and 2.51); no increase in blocks is established. The rule stays a play-time option and is not trained under again without a new idea. Chain 57 (bot seat) is training and is the last stage in the plan.

**Update 2026-10-06 18:10 PDT (D422): chains 58 and 59 are registered to follow chain 57.** Chain 58 is chain 55's rung with GAE lambda 0.97; chain 59 is chain 55's rung at training seed 2042, to measure seed spread. Chain 55 is the control for both. The block-charge reward arm is not run: the reward pays declared blocks their expected value, so "blocks are net charged" was wrong as a general statement.


**Update 2026-10-07 02:25 PDT (D423, D424): chain 57, the bot-seat arm, reads Inconclusive; chain 49 stays the warm start; chain 58 is training.** Chain 57 beats its control chain 55 directly by +42.0 decisive-Elo [+29.7, +54.8] and does better than it against chain 46 (+24.2 [+3.3, +45.4]), but the contrast against chain 37 is +8.5 with an interval that spans zero, so the registered Positive rule is not met. The seat change stays not adopted. Against the offense bot chain 57 is below chain 55 (-35.3 [-57.4, -12.8], descriptive), and its stage exam passed the chain 30 guard with two of three clauses under their floors. All three gates of this round (chains 55, 56 and 57) beat their comparator directly and leave one held-out contrast spanning zero. Chain 58 (GAE lambda 0.97) launched at 01:12 PDT and ends at about 10:00; chain 59 (the seed replicate) follows to about 19:00. Gate cost about $0.24, five droplets, all deleted.


**Update 2026-10-07 10:05 PDT (D425, D426, D427): decision-time search reads Positive in self-play; chain 58 passed its stage and its gate is playing; chain 59 is training.**
- **Search (D425, D426).** A registered whole-game comparison: chain 55 under the m1 mask in both seats, with seat A running a rollout search at its turn-level decisions and the first decision after its own declaration (16 rollouts over the sampled action and the three most probable alternatives, deviating only for a predicted gain above 0.10). Over 1,600 games per arm the searching seat is +47 [+28, +67] decisive-Elo against the same checkpoint without search; the plain arm is -10 [-30, +11]. It deviates 2.4 times a game and costs 41 times the wall time of plain play. Label: Positive, which means the search seat is to be built into the tournament harness and gated against chain 55 + m1 and the held-out chains 37 and 46. Nothing is adopted. It is self-play, where the rollouts model the opponent exactly; the gate measures other opponents. The run was sized wrongly and seven of eight shards needed the one relaunch the registration allows; total spend $3.97.
- **Chain 58 (D427).** GAE lambda 0.97 from chain 49 passed its stage (offense AWAY 0.582 / 0.585; every exam cell at or a little below chain 55's). Its eleven-pair gate (plan sha256 `399a3a6f...`, seed block 22700000) was launched at 10:01 PDT on six droplets.
- **Chain 59** (chain 55's rung at seed 2042) launched at 10:00 PDT and should end at about 18:50 PDT. What follows it is not registered yet and must start from chain 49 (D422).


**Update 2026-10-07 10:30 PDT (D428, D429): chain 58 (GAE lambda 0.97) reads Positive, the first Positive of this round; chain 60 is registered to replicate it.**
- **Chain 58 (D428).** Directly over its control chain 55: +44.5 decisive-Elo [+30.7, +58.2]. Against the held-out opponents it does better than chain 55 by +37.9 [+17.7, +56.4] (chain 37) and +27.7 [+5.9, +49.1] (chain 46). All three clauses of the registered Positive rule hold. Lambda 0.97 is a candidate, not adopted: adoption needs a second Positive pair. Chain 58 is a warm-start candidate (both retention contrasts against chain 49 are above zero); nothing is launched from it before chain 59's gate is read. Chain 49 stays the warm start for now.
- **Style.** Chain 58 activates 3.17 players a team turn against chain 55's 2.84 (+0.33 [+0.30, +0.37]); +0.12 of that is non-empty activations, with slightly more blocks (0.474 against 0.440). Small against the human 7, but in the direction the hypothesis said.
- **Limits.** One training seed per side; the intervals cover evaluation seeds only. Pair 1 clears +40 by 4.5. The exam did not see the gain.
- **Chain 60 (D429).** Chain 59's rung with lambda 0.97 (seed 2042, from chain 49), with chain 59 as its exactly matched control. A Positive there adopts lambda 0.97. It is in the rig's plan and launches when chain 59 passes its stage, at about 18:55 PDT, ending at about 03:45 PDT on 2026-10-08. Its gate uses seed block 22900000.
- **Next readings.** Chain 59's gate tonight (seed block 22800000), then the candidate selection of D422, then the entry for what runs after chain 60.


**Update 2026-10-07 14:05 PDT (D430): the search seat is in the tournament harness and its gate against held-out opponents is playing.**
- **The gate (D430).** Chain 55 + m1 with the search seat (S) and without it (C), each against chain 37 and chain 46, 3,200 games a pair, seed block 25100000, plus a 20-game identity sample. Eight droplets launched at 14:02 PDT, each playing 200 seeds of all four pairs; about 11.5 hours, about $15.5, ceiling $30. Plan sha256 `7fb1591c...`, harness `06f0a5f`. Positive needs both paired differences S minus C above +20 with intervals above zero. One look, after the merged run passes acceptance.
- **What changed in the harness.** The search seat (`33428b3`); a pair can be split across droplets by game index (`--index0`); resume and merge check existing records; the search acceptance tool no longer passes records it should refuse. Two Codex reviews of the code, one of the entry; every blocking finding was fixed before launch. Full suite at `06f0a5f`: 1,290 passed, 11 skipped.
- **Pilot rule D2 is met** by a count fixed before the data: 58 new deviations in 133 fresh games, none false on 128 fresh rollouts (upper bound 5.0%); 87 in all three batches, none false.
- **The self-play pair is not replayed** in this gate, a disclosed departure from D425's wording. A lower-temperature control is deferred and must be read before anything further is built on search.
- **An observation for the training side, exploratory** (`docs/search-probe-2026-10-07/LOGIT_SCALE_NOTE.md`): at about seven decisions in ten the policy's first choice has probability above 0.999999, in every checkpoint from chain 25 on. Training cannot learn about actions it never samples, which may be why play stays near three activations a turn and why search helps. Not established; a design for more exploration in training comes next.
- **Rig.** Chain 59 is training (about 1.2B of 3.0B at 13:30), chain 60 follows it tonight.

**Update 2026-10-07 20:45 PDT (D431, D432, D433): chain 59 reads Inconclusive; chain 58 is the warm start; chain 61 is queued after chain 60.**
- **Chain 59 (D432)**, chain 55's rung at training seed 2042: +76.4 [+63.7, +89.5] over chain 49, held-out contrasts +11.9 [-10.1, +32.7] (chain 37) and +27.4 [+8.2, +46.6] (chain 46). Inconclusive, the same label and shape as chain 55. Gate `c59-gate-20261007`, 28,800 games accepted, about $0.22.
- **The replicate pair.** Chain 59 against chain 55 is -2.0 [-14.5, +10.7]: no difference between the two training seeds is established. Chain 58's observed +44.5 over chain 55 exceeds that gap. It is a descriptive comparison across two seed blocks, not a measured seed variance.
- **Style.** The seed change alone moved activations by +0.41 a team turn (non-empty +0.26), more than chain 58's +0.33 (+0.12) over the same control. The activation observations of D428 do not establish a reproducible lambda effect. Chain 60 against chain 59 is the matched pair.
- **Warm start.** Chains 57 and 59 are not candidates and chain 58 is, so chain 58 (`a03ed608...`) replaces chain 49. Lambda stays 0.95 in the recipe until chain 60's gate reads.
- **Chain 61 (D433)** is appended to the plan (20:40 PDT): the plain continuation from chain 58 at lambda 0.95, seed 42, pool `59a6703f...` (the anchor, chain 41, chain 49, chain 58 in the bot's seat). It is the control for arms from chain 58. Gate seed block 23000000, nine pairs, chain 59 as a descriptive third opponent. It starts when chain 60 passes (about 03:50 PDT Oct 8) and ends about 12:40.
- **The exploration lead is not ready for a rung.** A design study (`docs/plans/exploration-in-training-design-2026-10-07.md`, with Codex's review as its section 8) finds the policy saturated at most decisions and nothing in the trainer restraining logit growth, and finds the search's large gains at actions the policy almost never samples. It does not settle whether exploration limits activations a turn. Next: the search gate's reading, then committed plans for two off-rig tests. The rig's trainer has no clamp on the PPO log-ratio (the Mac's vendored tree has one); noted, not acted on.
- **Still to register:** what runs after chain 61, after chain 60's gate is read (about 04:30 PDT Oct 8).

**Update 2026-10-08 02:24 PDT (D434): the search seat's gate against held-out opponents reads Positive.**
- **Result.** Chain 55 + m1 with the search seat against the same checkpoint without it, same seeds: +45.5 decisive-Elo [+28.3, +63.4] against chain 37 and +45.3 [+27.2, +64.5] against chain 46. 12,820 games on eight droplets, accepted on all three checks (stock, masks, search), one look, no relaunch, $13.97 of a $30 ceiling, every droplet and key gone.
- **What it buys.** The setting is a play-time option on chain 55 + m1, as m1 is, at about 48 times the time of plain play (364 seconds a game against 7.5). It adopts nothing else: no recipe, warm start or evaluation default changes, and another checkpoint (chain 58 included) needs its own gate.
- **What the search does.** About 193 searched decisions and 2.6 deviations a game (1.3%); 310 and 277 of 3,200 games have none and are the control's games. Paired on seed, the seat's side scores about +0.10 touchdowns a game more and concedes about 0.03 fewer. Slightly fewer activations a team turn (6.36 against 6.57), slightly more blocks.
- **Limits.** Both opponents are older relatives about 190 to 200 Elo weaker than the control. There is no lower-temperature control yet, so sharpening alone is not ruled out as the source.
- **Next.** The lower-temperature control at plain speed, in its own entry, before anything else builds on search (a faster rollout kernel, search as a teacher, a larger budget).

**Update 2026-10-08 02:55 PDT (D435): the lower-temperature control for the search seat is registered and playing.**
- **What.** Chain 55 + m1 at temperatures 0.75, 0.5 and 0.25 (per-head tempering) and the plain control replayed, each against chain 37 and chain 46 on the search gate's seed block: eight pairs, 25,600 plain games, four droplets since 02:54, about two hours, about $1.40. Gate `tctl-gate-20261008`, plan `80dcbb55...`, harness `5ab3ab6`.
- **Reading.** Six margins (the search seat's accepted games minus each temperature arm, paired on seed). All six intervals above zero reads "search beats the three temperatures" and lets entries build on search; any interval below zero reads "a temperature is better"; anything else is "not separated". The gains of each temperature over the control are exploratory and adopt nothing.
- **Limits.** The margins reuse a gate that has been read, so this is a follow-up and not an independent confirmation. Acceptance adds a replay check: the control's 6,400 games must equal the search gate's.
- **Tooling.** The stock acceptance tool can now hold a player to a registered temperature (`ad36a16`, `5ab3ab6`). Smokes: Mac and three droplets, $0.066, including the first Mac against droplet agreement for temperatures other than 1.

**Update 2026-10-08 04:45 PDT (D436 to D441): chain 60 reads Positive on a knife edge and GAE lambda 0.97 is adopted; chain 62 is queued; the END_TURN probe failed once and is playing again.**
- **Chain 60 (D438, D440)**, chain 59's rung with lambda 0.97 at training seed 2042: +40.07 [+26.7, +54.2] over chain 59, and above it on both held-out opponents (+37.9 [+17.0, +59.8] against chain 37, +78.0 [+56.5, +99.0] against chain 46). The registered rule needs the direct gap above +40, so it reads Positive by 0.07 Elo: one decisive game the other way would read Flat. The held-out clauses are not near their edge. Gate `c60-gate-20261008`, 38,400 games accepted, $0.32.
- **Lambda 0.97 is adopted** for rungs registered from here on (D429's consequence): two Positive pairs at two training seeds, sharing one parent (chain 49), one pool and one build.
- **Style.** The activation difference of chain 58 does not repeat: chain 60 activates fewer players a team turn than chain 59 (-0.16), where chain 58 activated more than chain 55 (+0.33). What repeats at both seeds is more blocks a team turn (+0.048, +0.034) and more touchdowns a game (+0.11 both).
- **Chain 60 is a warm-start candidate**; chain 58 stays the warm start (chain 60 against chain 58: +9.8 [-4.4, +23.3], no difference established). Nothing is launched from chain 60 before a registered comparison.
- **Chain 61** (plain continuation from chain 58 at 0.95, D433) has been training since 03:30 and ends about 12:40. Its manifest differs from chain 58's only in lambda, warm start, pool and paths.
- **Chain 62 (D441)** is appended to the plan (04:42 PDT): chain 58 continued at lambda 0.97, seed 42, pool `59a6703f...`, with chain 61 as its matched control: a third lambda pair, at a second parent. Gate seed block 23100000, twelve pairs. It runs from about 12:45 to about 22:00.
- **END_TURN probe (D436, D437, D439).** The first launch is unread: its fail-fast check stopped two shards at END_TURN decisions inside a kick-off Blitz turn, where ending the turn does not advance the engine's completed-turn counter and the rollout runs on into the next real turn. The corrected probe leaves such decisions out of every class (about one in a hundred), has a regression test on the two failed games and a 120-game rehearsal, and is playing on five droplets since 04:33 on a fresh seed block (run `et2`); reading at about 07:00.
- **Still to register:** what runs after chain 62, by about 21:30 PDT, after chain 61's gate and the probe are read.

**Update 2026-10-08 05:29 PDT (D442): the temperature control reads "search beats the three temperatures".**
- **Result.** Chain 55 + m1 at temperature 0.75, 0.5 and 0.25 against chain 37 and chain 46 on the search gate's seeds: the search seat's margin over each arm is +24 to +42 decisive-Elo and all six intervals are above zero (the smallest: +24.2 [+2.7, +45.3], temperature 0.5 against chain 37). 25,600 plain games, four checks passed including the replay (the control's 6,400 games equal the search gate's), one look, $1.40 with smokes, all droplets gone.
- **Temperature itself.** Gains over plain play are +3 to +21, all six above zero as point estimates, one interval of six above zero; each arm reads Inconclusive and none is carried forward by this entry.
- **What it allows.** The bar D430 set is cleared for these arms: entries that build on search may be registered, each with its own gate. Nothing is adopted.
- **Caveat.** The margins reuse a gate that has been read, and one of them is close. A claim that search beats temperature 0.5 in particular needs a fresh-seed replay of the search seat.
- **Next on search.** A registered plan for distilling the search seat's deviations into the policy (not started).

**Update 2026-10-08 07:03 PDT (D443): the END_TURN probe is read and points at no arm.**
- **Run.** Five checkpoints (chains 55, 58, 59, 49, 60), 200 self-play games each, all five shards accepted, one look, $1.36 (probe total $1.48 with the unread first launch).
- **What it found.** Where a checkpoint ends its turn, its own critic prices the most probable further activation below ending by about 0.008 to 0.011, and that is the price of one activation (the forced arm agrees to 0.001). Played to the end of the match, the shaped return does not establish a negative margin (all five intervals span zero), and for chains 55, 58, 59 and 60 the critic's margin sits about 0.01 below the realised one.
- **Rules.** None of the three pointers holds: the realised margin is not below zero (no reward pointer), removing the discount flips only 4% to 6% of decisions (no gamma pointer), and chain 58's margin does not differ from the lambda 0.95 checkpoints beyond the seed gap (no lambda pointer). The outcome is "reported without a recommendation".
- **Also.** The critic's part of the margin is smaller in magnitude in both lambda 0.97 checkpoints than in their controls (+0.0032 [+0.0021, +0.0044] on average; no rule reads it). A choice among up to three activations has a positive judged gain at END_TURN decisions for chains 55, 58 and 60. The kick-off Blitz rule left out about 1% of decisions; chain 58 ends its Blitz turn early far more often than the others.
- **Use.** The rung after chain 62 is chosen without a pointer from the probe.

**Update 2026-10-08 13:40 PDT (D446, D447): chain 61 reads Flat; chain 58 stays the warm start; chain 62 is training.**
- **Chain 61 (D433, D446, D447)**, the plain continuation from chain 58 at lambda 0.95, seed 42: +20.5 [+6.9, +34.6] over chain 58 directly, so Flat by the registered rule (the direct gap is inside plus or minus 40). Against the held-out opponents it is not above chain 58: -31.7 [-52.9, -11.4] against chain 37 (entirely below zero; one rung, one seed, a nominal interval among three contrasts) and -8.8 [-29.9, +12.4] against chain 46. Against chain 59 (descriptive) +6.6 [-10.7, +25.3].
- **Consequences.** Chain 58 stays the warm start. Chain 61 is the accepted control for arms from chain 58 and is not a warm-start candidate.
- **Pair 7, the first meeting of chain 58 and chain 59:** chain 58 +46.8 [+33.4, +60.2].
- **Style, pair 1.** Chain 61 activates fewer players a team turn than chain 58 (2.86 against 3.24), mostly fewer empty activations, blocks slightly less, and scores slightly more (+0.04 touchdowns a game).
- **Gate.** 28,800 games, nine pairs, seed block 23000000, accepted, integrity counters zero, four droplets destroyed, about $0.22.
- **Chain 62 (D441)** launched at 12:06 PDT and should end at about 20:40, earlier than first written. Its manifest differs from chain 61's in lambda and the run's own paths; the pool identity and lineage are equal.
- **Still to register:** what runs after chain 62, by about 20:15 PDT, with the selection among warm-start candidates that D441 requires before anything is launched from chain 60, chain 61 or chain 62.

**Update 2026-10-08 13:55 PDT (D448): chain 63 is registered to follow chain 62.**
- **Chain 63:** chain 58 continued at GAE lambda 0.99, training seed 42, same pool and build. Control: chain 62 (0.97). With chain 61 (0.95) that makes three doses of the one factor that has read Positive, on one parent. It is an experimental arm beside the adopted recipe, registered before chain 62 is read, and it runs whatever chain 62 reads.
- **Gate:** fourteen pairs, seed block 23200000, the label rule of D441 with chain 62 as the control, a dose table on one seed block. It adopts nothing under any reading.
- **Expectation written down:** Positive about one chance in five.
- **Timing:** chain 62 should end about 20:40 PDT, chain 63 about 05:15 on 2026-10-09. The generation after that is chosen by a registered selection once chain 62's gate is read.

**Update 2026-10-08 14:00 PDT (D445): the distillation's first label stage is in; its dataset is rebuilt on a droplet with no rule changed.**
- **Labels.** Milestone 1's 1,000 games were accepted: 30,000 sampled decisions, 566 where the search deviates, $0.50. The stop on label speed passes.
- **What stopped.** The registered dataset build, run on the Mac, refused one decision of 27,000: the recomputed log-probability of the played action was 0.00114 from the droplet's record, against a registered 0.001. By D444 that made the fit check Unread.
- **Why.** A third droplet running one game per forward, as the label tool does, reproduced all 27,000 records to 0.0000002. Running 32 games per forward (the build's default) differs by up to 0.0006 on the droplet and 0.0011 on the Mac. The labels are sound; the build's arithmetic was not the label tool's.
- **Fix (D445).** No acceptance rule changes. The registered build runs on a droplet, one game per forward, and the dataset appears on the Mac only after every check and a verified teardown. Allocation raised from $14 to $18.50 for the extra builds.
- **Next.** The milestone 1 dataset, the fine-tune, the fit check; if it reads fit, the other 9,000 label games.

**Update 2026-10-08 14:30 PDT (D449): search distillation Test 1 stops at its first fit check.**
- **Reading 1: NOT FIT.** The dataset rebuilt on a droplet was accepted. After the registered 2,400 steps the strongest arm (lambda 16) puts 0.605 probability on its 370 training labels; the registered bar is 0.80. By the plan's rule it stops: the other 9,000 label games are not played, and there is no selection, no held-out look and no gate.
- **What it does not say.** Nothing about strength or transfer, and R1 is not closed: the weights were still moving when the fine-tune stopped.
- **Printed beside it, read by no rule.** On 100 validation games the label's probability is 0.08, 0.11 and 0.17 at lambda 1, 4 and 16, and 4.8%, 7.0% and 9.8% of other decisions change their top action.
- **Kept.** 1,000 labelled games (566 judged deviations), the dataset and the tools. The test games are unopened.
- **Spend.** About $0.70 of $18.50. Every droplet is gone.
- **Next.** A further distillation test is a new entry. Options are set down in D449 without choosing.
- **Exploratory, after D449 (not registered, decides nothing):** running the same fine-tune for 24,000 steps instead of 2,400 left the training fit where it was (about 0.60 at lambda 16, 0.42 at lambda 4), so the step budget does not look like the limit. On the validation games the label's probability drifted down with more steps. Notes: `docs/search-distill-2026-10-08/NOTES.md`, section 0000.

**Update 2026-10-09 00:50 PDT (D450, D451): chain 62 reads Inconclusive; both rungs from chain 58 are below it against the held-out opponents; chain 58 stays the warm start.**
- **Chain 62 (chain 58 at lambda 0.97) against chain 61 (0.95):** +53.4 [+40.3, +67.0] directly. Against the held-out opponents it is not above chain 61: +6.5 [-13.5, +26.8] against chain 37 and -21.8 [-42.5, -1.0] against chain 46. Label: Inconclusive. The lambda 0.97 adoption stands on its two earlier pairs.
- **Against its own parent on the held-out opponents:** chain 62 minus chain 58 is -24.7 [-44.7, -5.2] against chain 37 and -43.7 [-63.3, -23.3] against chain 46. Chain 61 minus chain 58 repeats below zero on this block (-31.2, -21.8). Chain 62 is not a warm-start candidate.
- **Head to head chain 62 wins:** +61.2 over chain 58 and +54.0 over chain 60. So the rungs from chain 58 gained against the newest checkpoints and lost against the two held-out ones. This gate does not say why (the pool rotated, and the parent differs).
- **Style:** more blocks a team turn and more touchdowns a game at lambda 0.97 a third time in plain play; activations again in no consistent direction.
- **Gate.** 38,400 games, twelve pairs, seed block 23100000, accepted, integrity counters zero, four droplets destroyed, about $0.35.
- **Chain 63 (lambda 0.99, D448)** launched at 20:53 PDT on 2026-10-08 and should end at about 05:30 on 2026-10-09. Its manifest differs from chain 62's in lambda and the run's own paths.
- **Still to register:** what runs after chain 63.

**Update 2026-10-09 00:59 PDT (D452): chain 64 is registered to follow chain 63: chain 62's rung against the previous generation's opponents.**
- **Why.** D451 found both rungs from chain 58 below it against the held-out opponents. Between that generation and the one before, the parent changed and the pool rotated (chain 40 left, chain 49 became an active opponent). Chain 64 is chain 62's rung (chain 58, lambda 0.97, seed 42) trained against the anchor, chain 40 and chain 41 instead of the anchor, chain 41 and chain 49. Control: chain 62.
- **Question.** Does it do better than chain 62 against chain 37 and chain 46? Readings: improved against both, against one, mixed, criterion not met. "Recovered" needs the rung not to be below chain 58 as well. It adopts nothing and changes no pool rule.
- **Gate:** sixteen pairs, 51,200 games, seed block 23300000, with pairs against chain 60, chain 59, chain 49 and chain 40 to show the other side.
- **Selection:** not run. Chain 60 is the only candidate and nothing is launched from it; chain 58 stays the warm start.
- **Expectation written down:** improved against chain 46 about 55 in 100, against chain 37 about 35 in 100, criterion not met about 40 in 100.
- **Timing:** chain 63 should end about 05:30 PDT, chain 64 about 14:20.

**Update 2026-10-09 01:08 PDT (D453): a descriptive panel is registered and playing beside the rig.**
- **What.** Chain 58, chain 61 and chain 62 each against eight opponents other than chain 37 and chain 46: the older line (chain 30, chain 36, chain 40), off the line (chain 38, chain 42) and chain 49's other rungs (chain 55, chain 59, chain 60). 76,800 games, seed block 23400000, plan sha256 `aa0400b3...`, about $0.70, no rig time.
- **Why.** D451's losses against the parent were measured on two opponents. The panel shows whether they also appear against these eight. It decides nothing and changes no rule.

**Update 2026-10-09 06:20 PDT (D454): no more droplets; gates play on the training rig.**
- **Instruction (Alex, 01:54 PDT):** move off DigitalOcean, use only the 2070 machine. The panel's last three shards finished on their own by 02:15; nothing of this work is on DigitalOcean.
- **How gates play now:** `docs/rig-gates-2026-10-09/rig_gate.py` plays a registered plan on the rig beside the trainer: CPU only, 6 workers at the lowest CPU and I/O priority, one gate at a time, verified with the droplet runner's own checks. Merge, acceptance, scoring and every label rule are unchanged.
- **Evidence:** four smokes replayed 2,496 records (1,280 distinct games) of chain 62's gate and every record matched the droplet's, action trail included.
- **Cost:** a gate takes about four hours instead of 35 minutes, and in the smokes the trainer ran about 13 percent slower while one played (98.7K to 86K steps a second). No cloud spend.
- **Declared:** chain 64 now trains with a gate beside it for part of its run and its control did not; D452's reading must name that.

**Update 2026-10-09 06:20 PDT (D455): the panel is read.**
- **Chain 62 against its parent chain 58:** below it against all five older or off-line opponents (chain 30: -44.8, chain 36: -35.3, chain 40: -29.4, chain 38: -50.8, chain 42: -28.8, every interval below zero) and above it against all three of chain 49's other rungs (chain 55: +57.5, chain 59: +35.4, chain 60: +72.2, every interval above zero).
- **Chain 61 against chain 58:** below against the same five (two intervals reach zero), mixed against chain 49's rungs.
- **So** the losses D451 found against chain 37 and chain 46 are not special to those two among these opponents: the rungs from chain 58 gained against their parent's own generation and lost margin against everything older. The margins against the older opponents are still large (+129 to +251 for chain 62).
- **Limits:** eight chosen relatives, one seed block, sixteen intervals. It decides nothing and changes no rule. 76,800 games, about $0.67, the last droplets this work used.

**Update 2026-10-09 06:25 PDT (D456): chain 63 passed its stage; its gate is playing on the rig; chain 64 is training.**
- **Chain 63 (chain 58 at lambda 0.99):** guard not fired, but offense AWAY 0.562 / 0.555 is below chain 62's 0.592 / 0.601 and seed 43 sits 0.004 above its floor. In-run, value loss 0.0231 against 0.0137 and explained variance 0.864 against 0.914.
- **Its gate:** fourteen pairs, 44,800 games, seed block 23200000, plan sha256 `2130467b...`, started on the rig at 06:22 PDT, about four hours.
- **Chain 64 (D452)** launched at 05:35 PDT and meets its manifest condition. It should end between 14:15 and 14:45. What follows it is registered before then.

**2026-10-09 10:59 PDT. Chain 65 is registered to follow chain 64 (D457).**
- **Chain 65:** chain 62's rung (chain 58, lambda 0.97, the standard pool) at training seed 2042. It asks whether chain 62's loss to its parent against chain 37 and chain 46 repeats at a second training seed, and it is the seed-2042 control a second-seed arm from chain 58 would need.
- **Chosen without chain 64's reading and before chain 63's gate is read** (its last shard is playing). Wrapper `b3_chain65.sh` (`34cba79`), plan-only pass at 10:54 PDT. Gate: ten pairs, 32,000 games, seed block 23500000, on the rig after chain 64's.
- **Still to do:** read chain 63's gate when its last shard ends (about 11:40 PDT); chain 64's check-in at about 15:00.

**2026-10-09 11:41 PDT. Chain 63 reads Flat by one decisive game, and it is the first rung from chain 58 above its parent against the held-out opponents (D458).**
- **Label:** +39.98 [+25.9, +54.8] over chain 62 directly; the rule needs above +40 (1007 wins to 800; 1008 would have read Positive). Both held-out contrasts are entirely above zero: +97.1 against chain 37, +71.1 against chain 46.
- **Against its parent chain 58:** +47.5 and +50.7 against the held-out opponents (chain 61 and chain 62 were below it), +77.9 head to head.
- **Under the END_TURN mask the order reverses:** chain 62 + m1 beats chain 63 + m1 by 31.0.
- **Style:** 3.98 activations a team turn against chain 62's 2.95.
- **Nothing is adopted; chain 63 is not a candidate by D448's rule; chain 58 stays the warm start.** A second lambda 0.99 pair and a selection each need their own entry. Chain 65 (D457) is the control such a pair would use.
- **The gate on the rig:** 5 h 10 min for 44,800 games (2.41 games a second), trainer 15.7% slower beside it, 2.4 GB.

**2026-10-09 11:44 PDT. A panel for chain 63 is registered and plays on the rig beside chain 64 (D459).**
- Chain 63 and chain 58, each against chain 30, chain 38, chain 40 and chain 60: eight pairs, 25,600 games, seed block 23600000, plan sha256 `38217390...`, about three hours. Descriptive: per opponent, Above its parent / Below its parent / Not separated. It decides nothing.
- It slows chain 64 by a forecast 25 minutes; chain 64's reading must give the total gate time beside it.

**2026-10-09 11:53 PDT. Chain 66 is registered to follow chain 65 (D460): a second pair for lambda 0.99.**
- **Chain 66:** chain 63's rung (chain 58, lambda 0.99) at training seed 2042; control chain 65 (lambda 0.97, seed 2042). Wrapper `b3_chain66.sh` (`656bb28`), plan-only pass at 11:48 PDT. Gate: twelve pairs, 38,400 games, seed block 23700000.
- **It adopts nothing.** If its direct pair, both held-out contrasts and both retention contrasts are entirely above zero ("Confirmed"), lambda 0.99 qualifies for one more prospective pair (adoption needs two prospective successes) and chain 63 and chain 66 become warm-start candidates.
- **The rig's order:** chain 64 (to about 15:20), chain 65 (to about 01:15 on 2026-10-10), chain 66 (to about 11:00). Gates on the rig: chain 63's panel now, then chain 64's, chain 65's, chain 66's.

**2026-10-09 14:41 PDT. The chain 63 panel is read (D461): chain 63 is above its parent against all four opponents.**
- Chain 63 minus chain 58: chain 30 +47.7 [+22.3, +72.5], chain 38 +47.7 [+23.4, +74.4], chain 40 +61.1 [+37.5, +85.1], chain 60 +85.6 [+65.2, +105.5]. Chain 62 minus chain 58 on D455's block was -44.8, -50.8, -29.4 and +72.2 against the same four. 25,600 games accepted, no cloud spend. It decides nothing.
- Descriptive: chain 63 scores about what its parent does against these four and concedes 0.12 to 0.20 fewer touchdowns a game; chain 58 against chain 60 is -18.2 [-33.0, -4.6] on this block.
- **The rig:** the panel took 2 h 30 min 20 s (2.84 games a second); the trainer ran 15.6% slower beside it. A gate or panel has played beside chain 64 for 7 h 40 min 43 s, about 79% of its run, and cost it about 71 minutes; chain 64's reading must carry that.

**2026-10-09 15:39 PDT. Chain 64 passed its stage; its gate plan is fixed and the gate plays on the rig (D462). Chain 65 is training.**
- **Chain 64** (`ccf606eb...`): exam offense AWAY 0.615 / 0.621, contact AWAY 0.560 / 0.558, contact HOME 0.504 / 0.476, above chain 62 and chain 58 on all six cells; guard not fired. In-run rows close to chain 62's (`docs/chain64-inrun-diagnostics-2026-10-09.txt`). Its training took 9 h 45 min against chain 62's 8 h 32 min, with a gate or panel beside it for 7 h 41 min.
- **Gate `c64-gate-20261009`:** sixteen pairs, 51,200 games, seed block 23300000, plan sha256 `dc1be811...`, four shards on the rig, five to six hours. Read by D452.
- **Chain 65** launched 15:32:53 and meets D457's manifest condition (14 of 277 leaves differ, all allowed). Chain 66 follows it.

**2026-10-09 21:56 PDT. A small END_TURN-mask panel for chain 63 is registered and its plan fixed before any game (D463). Chain 64's gate is scored; its reading is the next entry.**
- **Panel `m1panel63-20261009`:** chain 63 + m1 against plain chain 63, and chain 62 + m1 against plain chain 63; 6,400 games, seed block 24300000, plan sha256 `d13a985b...`, on the rig, about an hour. It decides nothing; it fills the two pairs D458 left unplayed.
- It plays beside chain 65, which chain 65's reading must count (chain 64's gate already played beside it for 4 h 56 min 39 s).
- Correction recorded: "unused" seed blocks in earlier entries meant unused by ladder plans; D416's chain 41 mask tests had played on blocks 23000000 to 24200000. No ladder gate shared a block with an earlier run of its own players.

**2026-10-09 22:02 PDT. Chain 64 reads "Criterion not met" (D464): the earlier pool did not show an improvement on chain 62 against the held-out opponents.**
- **The registered question:** chain 64 minus chain 62 is +13.7 [-7.0, +33.3] against chain 37 and -2.0 [-23.9, +18.2] against chain 46. A recovery of the lost size is excluded against chain 46 (by D451's bound of 43.7) and not against chain 37.
- **Head to head chain 64 loses to chain 62:** -76.3 [-90.6, -62.5]; the ladder's label is Negative and chain 64 is not a candidate. It is below chain 62 against chain 60 (-70.1), chain 59 (-30.0) and chain 49 (-24.9), with no difference shown against chain 40 (+1.8). Against its parent it is +9.7 [-4.0, +23.5].
- **Load:** a gate or panel played beside chain 64's training for 7 h 41 min and its control trained alone, so the comparison cannot be laid to the pool alone. Nothing is adopted; chain 58 remains the warm start.
- **The rig:** the gate took 4 h 56 min 39 s (2.88 games a second), all of it beside chain 65, whose trainer ran 15.4% slower meanwhile. D463's panel is playing.

**2026-10-09 22:40 PDT. The END_TURN-mask panel for chain 63 is read (D465). It decides nothing.**
- **Chain 62 + m1 against plain chain 63:** +27.4 [+11.9, +43.0]. With D458's pair 13 (chain 62 + m1 ahead of chain 63 + m1 by 31.0) the masked lambda 0.97 checkpoint is ahead of both other play-time players in its direct pairs. Played plain, chain 63 beats chain 62 by 40 (D458).
- **Chain 63 + m1 against plain chain 63:** +14.0 with an interval from exactly 0.0 to +28.0, so by the registered rule no effect of the mask on chain 63 is shown. D416 measured +32 to +43 on four earlier checkpoints.
- **The rig:** the panel took 39 min 2 s (2.73 games a second); the trainer ran 14.1% slower beside it. A gate or panel has played beside chain 65 for 5 h 35 min 41 s, about 51 minutes of progress lost; chain 65's reading must carry that. Chain 65 should end at about 00:52 on 2026-10-10.

**2026-10-10 01:30 PDT. Chain 65 passed its stage; its gate's plan is fixed and the gate starts on the rig (D466). Chain 66 is training.**
- **Chain 65** (chain 62's rung at training seed 2042): checkpoint `21cd2855...`, guard not fired (offense AWAY 0.631 / 0.619), above chain 62 on five of six exam cells, in-run rows close to chain 62's. A gate and a panel played beside its training for 5 h 35 min 41 s (about 51 minutes lost; it took 9 h 19 min against chain 62's 8 h 32 min); its reading must carry that.
- **Its gate:** `c65-gate-20261010`, plan sha256 `8de731141018a50df43d9df61892cc832bb02aac0d8df25bb540b5b0bce3cee1`, ten pairs, 32,000 games, seed block 23500000, three shards, about three and a quarter hours on the rig beside chain 66. Read by D457: does chain 62's loss to chain 58 against chain 37 and chain 46 repeat at a second seed.
- **Chain 66** (lambda 0.99 at seed 2042) launched 01:04:53 and meets D460's manifest condition against chain 65 (11 of 277 leaves differ, all allowed; the manifest files' own creation times resolved in D466). It should end at about 10:10 PDT, earlier than the 10:50 carried before.
- **Still to register, by about 09:30 PDT:** what the rig runs after chain 66. It is registered at this gate's reading and must not depend on chain 66's reading.

**2026-10-10 04:54 PDT. Chain 65 reads Not repeated (D467). Nothing is adopted; chain 58 remains the warm start.**
- **The registered question** (does chain 62's loss to chain 58 against the held-out opponents repeat at training seed 2042): chain 65 minus chain 58 is -17.5 [-38.5, +3.6] against chain 37 and +6.4 [-15.5, +28.1] against chain 46. Neither interval is entirely below zero, so the loss was not shown at this seed; that does not say there is none. A loss of chain 62's size is excluded against chain 46 and not against chain 37. D451's loss is now an observation at one training seed and any entry that builds on it must say so.
- **Against chain 62:** head to head -11.7 [-25.4, +2.2] (the ladder's label is Flat, no candidate); against the held-out opponents chain 65 is above chain 62, +34.2 [+13.3, +55.1] and +49.9 [+30.0, +70.2], a difference of training seed together with load. On this block chain 62 minus chain 58 is -51.7 and -43.4, the fourth block on which chain 62 is below its parent.
- **The head-to-head gain is repeated:** +59.7 over chain 58, +59.8 over chain 60.
- **Qualification:** a gate and a panel played beside chain 65's training for 5 h 35 min 41 s (about 51 minutes lost) and nothing played beside chain 62's.
- **The rig:** the gate took 2 h 59 min 24 s (2.97 games a second), all of it beside chain 66, whose trainer ran 15.3% slower meanwhile (about 27 minutes lost). Chain 66's reading must carry that.

**2026-10-10 04:54 PDT. Chain 67 is registered to follow chain 66 (D468): chain 58 at GAE lambda 0.999, training seed 42, control chain 63. It adopts nothing.**
- **Why:** nothing may start from chains 60 to 66 before a selection, and the selection waits for chain 66's reading (about 14:30), so from about 10:10 the trainer runs a stage from chain 58 or nothing. This rung is a fourth dose on one parent, pool, seed and build and asks whether the response still rises above 0.99.
- **Read by D448's rule with chain 63 as the control**, on a ten-pair gate (32,000 games, seed block 24400000). A guard trip reads Negative with no gate. A candidate only under Positive with both retention contrasts above zero. Chain 65's reading (D467) is quoted in it: two rungs of one recipe differed by 34 and 50 against the held-out opponents, so one pair cannot separate lambda from the run.
- **A recorded disagreement:** the outside reviewer would leave the trainer idle so that chain 66's reading and the selection come about two hours sooner; the operator keeps the rung. Alex may have it stopped at any time; a stopped rung is Unread.
- **If chain 66's stage fails** the halt is not reset for chain 67 without a new entry.
