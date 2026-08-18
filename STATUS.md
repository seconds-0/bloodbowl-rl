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
| 2 | 0 | 0.25 | chain2 accepted | promoted (`e138c936`) | **running** since Aug 18 06:47 PDT; tds ~0.6 at 2.2B from 75% kickoff starts |
| 3 | 0 (kickoff) | 0 | stage-2 accepted | promoted | queued |

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
