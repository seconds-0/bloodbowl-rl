# Status — 2026-08-18

## Current verdict

The obs-v6 / exact-action lineage has its first reproducible scoring policy:
two independent rung-6 backplay runs (maxdist 6, reset 0.5, `s0_both`,
genesis pool `f6a6323a`, 5B steps) finished clean in July at tds 0.299 /
0.303 per episode from curriculum starts, all sixteen hard-integrity counters
zero in both phases, curves plateaued from ~2.6B on. Neither could advance the
ladder because the bare rung launcher never published eligible lineage
(D235). No production reward or default has changed; `s0_both` remains the
experimental lineage reward.

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

## Live campaign: `rig-seed42-20260818` (RTX 2070, seed-42 replicate of the uniform chain)

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

Verdict: opponent quality in training moves the exam; pure-pool kickoff training makes it WORSE; curriculum alone does not help.

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
