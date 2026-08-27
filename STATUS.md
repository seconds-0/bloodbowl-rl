# Status — 2026-08-21

## Current verdict

The obs-v6 / exact-action lineage has its first reproducible scoring policy:
two independent rung-6 backplay runs (maxdist 6, reset 0.5, `s0_both`,
genesis pool `f6a6323a`, 5B steps) finished clean in July at tds 0.299 /
0.303 per episode from curriculum starts, all sixteen hard-integrity counters
zero in both phases, curves plateaued from ~2.6B on. Neither could advance the
ladder because the bare rung launcher never published eligible lineage
(D235). No production reward or default has changed; `s0_both` remains the
experimental lineage reward.

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
| chain 19 | chain 16 output (seed-43 twin of chain 9) | **r0_poss_half** (frontier reward) | 2.8e-4, bot share 0.12, contact bot, seed 43, **no knob: FILLER** | RUNNING since Aug 27 10:48 PDT (`runs/ladder-d0-r0chain19-plain-20260827`, unit `r0chain19-1787851690`), 3B, ETA about 7.5 h. Explicitly filler (D282): tests nothing, but is the seed-43 twin of the chain 14 plain control, so the pair gives a two-training-seed read on the D273/D275 plateau claim. Not a promotion candidate |
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

Verdict (revised D257): the bridged July lineage, continued under its own reward at full LR, is the live frontier; two rungs (2B + 3B) raised every champion cell twice over, and chain 1 also cut the HOME conceded rate by 0.04. Conceded AWAY is the flat cell; chain 2 doubled the bot share (0.12) and cut it. Chain 2 is the frontier: all three probes from it (LR x2, offense bot, entropy x2) lost on the exam, and training the bank seat without the contact bot gave back 0.06-0.09 conceded TD/game on the contact cells (D260). Chain 6 (plain continuation) split the cells on seed 42 (D262) and lost on the two-seed mean (D263: HOME conceded +0.043 on both seeds, no champion cell up outside noise). Every exam before D263 is the seed-42 draw and chain 2 won on that draw; its seed-43 read is lower on every champion cell, so the baseline to beat is now the chain 2 two-seed mean (0.487/0.422, 0.450/0.391, 0.577/0.340) and every challenger is examined on seeds 42 and 43. Four rungs from chain 2 under r0_full have failed to improve the exam: the recipe has plateaued, and the reward anneal began with chain 7 (r0_dist_half, both distance terms halved). Chain 7 held every contact cell inside noise on the two-seed mean but lost 0.056 on the offense-bot champion cell on both seeds (D264), so it was rejected. Chain 8 annealed the ball-distance term alone (r0_dist_ball_half) and lost the same cell by about half as much (-0.028, down on both seeds) while conceding 0.032 more at HOME (D265): at this capability the distance scaffold is still load-bearing for scoring against the uncontested opponent, so the anneal has moved to the D178 possession-vs-ball-gain decomposition; chain 9 halves the possession annuity alone (r0_poss_half) from chain 2. Chain 9 is the first accepted rung since chain 2 (D266): with the annuity halved and ball gain intact, both contact champion cells rose outside noise on both seeds (two-seed mean 0.534/0.393, 0.488/0.396, 0.575/0.336 against chain 2's 0.487/0.422, 0.450/0.391, 0.577/0.340), AWAY conceded fell, and the offense-bot cell was flat; the ball-gain term alone appears to carry the D178 defensive transfer and the per-turn holding term was over-paid. Chain 9 is the frontier and the baseline to beat is its two-seed mean; chain 10 quarters the annuity (r0_poss_quarter) from the chain 9 marker. Chain 10 (D267) came back inside the 0.02 band on every cell of the two-seed mean (0.516/0.408, 0.487/0.395, 0.581/0.353) but no cell improved and the contact AWAY champion cell fell 0.018 on both seeds, so both checkpoints are being re-examined on seed 44 and the verdict is taken on the three-seed mean: non-inferior keeps chain 10 and launches r0_poss_zero from it, a cell outside 0.02 rejects it and launches the ball-gain half step from chain 9. The seed-44 re-exam (D268) settled it: on the three-seed mean no cell crosses 0.02, but chain 10 is adverse in 14 of 17 seed-cell comparisons and its contact AWAY net TD differential is down 0.032, so the quarter annuity is read as a small real regression and chain 10 is rejected; chain 9 stays the frontier (three-seed mean 0.530/0.394, 0.484/0.395, 0.577/0.336). Later anneal steps are kept only if no cell moves against the frontier by more than 0.02 AND no cell's net differential drops by more than 0.02 on the multi-seed mean. Chain 11 (r0_poss_half_gain_half: ball gain 0.05 -> 0.025 with the annuity at the accepted 0.015) is the other half of the D178 decomposition; its two-seed exam (D269) splits the cells (contact AWAY champion -0.016 and net -0.027, offense-bot conceded -0.031 on both seeds), so a seed-44 re-exam decides it on the three-seed mean. The seed-44 read (D270) rejects it: on the three-seed mean the contact AWAY champion cell is down 0.022 (on all three seeds) and its net differential down 0.032, past both D268 thresholds, although chain 11 concedes the fewest offense-bot TDs recorded (0.304). Both anneal steps from chain 9 are rejected, the reward anneal is parked at r0_poss_half, and chain 12 retries LR x2 on the chain 9 frontier under r0_poss_half. Chain 12 lost LR x2 a second time on the seed-42 draw and the LR knob is retired (D271). Chain 13 put the OFFENSE bot in the bank seat under r0_poss_half: on the two-seed mean it concedes 0.070 / 0.063 / 0.050 more TD/game than chain 9 on the three cells with no champion cell up outside noise, and the offense-bot cell it trained against is worse on both sides (0.574/0.386 against 0.575/0.336), so it is rejected and the bank-seat bot swap is retired for the second time (D260 saw the same 0.06-0.09 conceded giveback from chain 2). Five consecutive knobs from chain 9 have failed, so chain 14 was a plain 3B continuation at frontier settings with no knob under test: the plateau control that separates "every knob tried is bad" from "the lineage is done improving" (D272). It answers the second way (D273): 3B more steps with nothing changed reproduce chain 9's training telemetry to within panel noise and lose the exam - contact AWAY champion -0.022 / -0.038 on seeds 42 and 43, contact HOME champion -0.060 on seed 42, conceded up 0.053 and 0.039 on seed 42, offense-bot cell flat. So the baseline that chains 10-13 were measured against is one that further training alone cannot beat either, and the lineage is plateaued at the recipe level rather than having been handed four bad knobs. The full two-seed exam confirms that rejection (D274: chain 14 mean 0.504/0.415, 0.444/0.410, 0.576/0.345, contact AWAY champion -0.031 and HOME -0.045, both down on both seeds). The knob screen is now over for a second reason: bot share 0.18 was never available. The launcher caps the frozen-bank share at 0.124 (four banks reserve `4*int(1024*pct)` rows of a 512-row budget) and chain 2's promoted 0.12 already sits at that ceiling, so the 0.18 rung was refused before training and no knob from the brief's list remains (D274). The campaign's own recommendation is therefore a structural change - opponent population (which now demonstrably needs an env/launcher change, not a variable), horizon, or a capability `r0_poss_half` cannot express at this policy scale. Chain 15h tests the cheapest of the three with no new code: 3B more from the chain 14 marker, i.e. cumulative 6B of frontier-settings continuation from chain 9. If it also fails to move the exam, the horizon direction is answered negatively too and the decision in front of Alex is which structural change to fund.  Chain 15h answers it negatively (D275): 6B cumulative of frontier-settings continuation lands within 0.02 of chain 14's 3B on every exam cell and still loses both contact cells to chain 9, while training-side tds keeps climbing (1.54 chain 9, 1.61 chain 14, 1.79 chain 15h) - a three-point demonstration that self-play/bank tds is not a proxy for kickoff strength. No chain 16 is launched. The knob screen and the horizon direction are both closed, chain 9 remains the frontier at 0.534/0.393, 0.488/0.396, 0.575/0.336, and the two directions left both need a decision above the loop: (a) opponent population, which needs an env/launcher change because the frozen-bank share is at its arithmetic ceiling of 0.124, or (b) a capability r0_poss_half cannot express at this policy scale. The rig is deliberately idle until Alex names one. Before that decision is put to Alex, D276 supplies the control the screen never had: every arm since the bridge has been a single run at a single training seed, so the 0.02-0.06 gaps that rejected six challengers have never been compared against the pipeline's own run-to-run variance - and two of those six (chains 14 and 15h) were pure continuations of chain 9's recipe that lost by the same margin as the knobs did, which is what a baseline reading high looks like. Chain 16 reruns chain 9 verbatim at seed 43 from chain 9's own parent marker. If merely reseeding costs as much exam as any knob did, the six rejections are underpowered rather than negative and arms need replicates before anything further is believed; if it lands inside 0.02 on every cell, chain 9's frontier status is earned and D275's structural recommendation stands on a measured noise floor. Chain 9 remains the frontier either way. Chain 16 landed (D277) and split the reading along an axis that was not pre-registered: the CHAMPION cells reproduce across independent training runs to within 0.011 (six seed-cell pairs at +0.003, +0.006, -0.006, +0.007, +0.011, -0.011; two-seed champion means +0.005, +0.008 and -0.009 against chain 9), while the CONCEDED cells move up to 0.086 on a single exam draw and +0.046 on the two-seed mean, with the contact-AWAY net differential down 0.041, from changing nothing but the training seed. So D268's uniform 0.02 thresholds are withdrawn for conceded and net; the conceded-driven rejections (chain 12 LR x2, chain 13 offense bot, and the net halves of chains 10 and 11) are retracted as underpowered rather than negative, and the two earlier "second loss" retirements of those same two knobs are two single-run draws each, not replications. The champion-driven rejections stand at 2x-5x the measured floor and moved the same direction on every seed, which includes chains 14 and 15h, so D275's finding that the horizon direction is closed and the plateau is real is unaffected. Going forward, defensive or net hypotheses need at least two training seeds per arm and a 0.05 conceded floor; scoring hypotheses can still be read from one run against 0.02. Chain 9 stays the frontier and the structural decision from D275 stands, now with a measured instrument attached to it: the campaign can resolve a hundredth of a TD/game of scoring and cannot resolve less than a twentieth of a TD/game of defense from one run. Chain 17 (D278) spends the otherwise-idle overnight GPU on the one shaping family the anneal never walked: chains 7-11 moved distance, the possession annuity and ball gain, but the block-EV terms (`reward_k_kd` 0.1, `reward_k_value` 0.5, `reward_k_ball` 0.15, `reward_k_seq` 0.03, `reward_k_turnover` 0.15) were never touched, and they are the largest remaining shaping mass in `r0_poss_half`. They enter `bloodbowl.h:3574-3625` as a linear weighted sum over pre-roll `bb_block_ev` probabilities, so the new `r0_blockev_half` arm halves all five and preserves every relative weight. It is launched with its power limits pre-registered: champion cells judged from this one training seed at a 0.02 floor against the chain 9 + chain 16 pooled mean (0.537/0.416, 0.492/0.406, 0.571/0.350), conceded and net not scored at all, and chain 18 (same arm, seed 43, from the chain 16 marker) queued as the seed-matched replicate. The structural decision from D275 is unchanged and still Alex's.

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
