# Chain supervisor: unattended rung, exam and verdict (2026-10-02)

Source of requirements: the launch-robustness review of 2026-10-02 (findings LP1, LP2, LP4, LP6, LP7, LP9 and the verifier's corrections). The chain is a `tools/campaign_supervisor.py` campaign whose every stage runs `tools/chain_stage.sh`. Nothing here calls a model or a network.

## What one stage does

`tools/chain_stage.sh` is configured only by environment. In order:

1. **Terminal checks, before the lock.** `EXAM_VERDICT_PASS.json` exists: exit 0. `EXAM_VERDICT.json` exists without it: exit 3, and no exam is ever run again. Otherwise, if the rung has no marker, it reads the newest `screen-attemptN`: a `LIVE_INTEGRITY_FAILURE.json`, or a non-zero `*.log.status.json` written on this boot, exits 4 without retraining. An attempt with no status (host died), or a non-zero status written before this boot (a clean shutdown sends TERM and the wrapper records 143), falls through and the rung opens the next attempt.
2. **GPU lock.** Opens `GPU_LOCK` on fd 7 and repeats `flock -w 600 7` until it has the lock. The trainer inherits fd 7. It appends `acquired(...)` and `released(exit N)` lines to `$GPU_LOCK.log`. The terminal checks run a second time once the lock is held.
3. **Telemetry.** `tools/chain_gpu_sampler.sh` appends `utc,temperature_c,utilization_pct,power_w` to `gpu_samples.csv` once a minute. Log only, no thermal kill. It runs without fd 7 and exits when the stage is gone.
4. **Rung.** With no `LADDER_RUNG_COMPLETE.json`, it runs `bash tools/ladder_stage.sh` as a foreground child (about 9.5 hours). With `EXPECTED_POOL_HASH` set and no published pool yet, it first runs the same script with `PLAN_ONLY=1`, which builds and publishes the pool and verifies the screen plan without training, then compares `POOL_IDENTITY.env`. A mismatch exits 6 before any training.
5. **Exam.** Reads the checkpoint from the marker with python json and checks its sha256. For each seed in `EXAM_SEEDS` it runs contact AWAY, contact HOME and offense AWAY exactly as the as-run `rig_exam.sh` did (`NATIVE=1 RIG_ALLOW_FLOAT=1 CUDA_VISIBLE_DEVICES=0 SEED=$s EVAL_EPISODES=2000`, 12000000 steps), each cell failing closed with exit 5. Cells go to a new `exam-attemptM/s<seed>/` directory every launch.
6. **Verdict.** `tools/chain_exam_verdict.py` reads the six logs with `contact_bot_stats.bot_perspective(game_stats.weighted_dashboard(log), bot_team)` and writes the verdict. Rule `none` passes on six valid cells. Rule `drift-guard` fails only when the guard cell's seed 42 value, seed 43 value and two-seed mean are all below their floors (strict, unrounded). Missing or malformed evidence writes no verdict file at all.

## Environment contract

| Variable | Meaning |
|---|---|
| `C`, `STAMP` | Required. Checkout root; unique per stage. Run directory is `$C/runs/ladder-d${RUNG}-${STAMP}`. |
| `EXAM_RULE` | Required: `none` or `drift-guard`. |
| `EXAM_GUARD_FLOOR_S42`, `_S43`, `_MEAN` | Required for `drift-guard`. Chain 30 reference: 0.541, 0.551, 0.546. |
| `EXAM_GUARD_CELL`, `EXAM_SEEDS` | Defaults `offense_away`, `"42 43"`. |
| `EXPECTED_POOL_HASH` | Optional. Checked before training and again against the marker. |
| `PLAN_ONLY=1` | Preflight: plan pass and pool check, then stop. Takes no lock. |
| `GPU_LOCK`, `GPU_LOCK_WAIT_SECONDS`, `GPU_SAMPLE_SECONDS` | Defaults `/home/rache/kt-e2e/kt-gpu.lock`, 600, 60. |
| `EXAM_CELL_TIMEOUT_SECONDS` | Default 1800. A cell takes about 90 seconds; a hung one fails as exit 5. |

Recipe variables go to `ladder_stage.sh` untouched, and the stage invents no default. It refuses to start (exit 2) unless these are non-empty: `RUNG RESET_PCT SEED STEPS LADDER_ARM FROZEN_BANK_PCT DEADLINE_HOURS NUM_THREADS`, and `PREV_COMPLETE` or both `WARM` and `PREV_POOL`. These must be set, and may be exported empty to take the screen's fixed value on purpose: `SCRIPTED_BANK_TAG SCRIPTED_BOT_TYPE LADDER_CHAIN_LR_SCALE LADDER_CHAIN_ENT_SCALE LADDER_GAMMA LADDER_GAE_LAMBDA LADDER_REPLAY_RATIO`. Passed through when set: `POOL_KEEP POOL_ANCHOR NUM_FROZEN_BANKS LADDER_PROFILE GRAFT_FROM_SOURCE_SHA256 GRAFT_FROM_PATCH_BUNDLE_SHA256 GRAFT_REASON PUFFER_SKIP_SCRIPTED_BANK_FORWARD BBE_DECIDING_ROW_TELEMETRY`.

The supervisor passes its whole environment to the stage (`campaign_supervisor.py` `launch_stage`), so the two build flags set in `chain-supervisor@.service` reach every drift check. Export them in the wrapper as well, so a manual run from an ssh shell sees them.

## Exit codes

| Code | Meaning | Next launch |
|---|---|---|
| 0 | Verdict registered and passed | no-op |
| 2 | Configuration error, nothing ran | same error |
| 3 | Verdict registered and failed | exit 3 again, final |
| 4 | Newest screen attempt failed on this boot, or integrity failure | exit 4 again, final |
| 5 | An exam cell failed | new exam attempt |
| 6 | Pool mismatch, or the plan pass did not verify | same result, nothing trained |
| 7 | Marker or checkpoint unusable (sha256 mismatch) | same result |
| 8 | Verdict tool found missing or malformed evidence | new exam attempt |
| 143, 130, 129 | Stopped by TERM, INT or HUP between steps | continues where it stopped |
| other | Exit status of `ladder_stage.sh` | see step 1 |

The supervisor does not read exit codes. It relaunches while the success file is missing and halts at `max_attempts`, so a final failure halts the chain within three ticks.

## Files in the run directory

`LADDER_RUNG_COMPLETE.json`, `POOL_IDENTITY.env`, `pool/`, `screen-attemptN/`, `SCREEN_STATUS.json` (from the ladder scripts); `chain-plan-only.log`; `gpu_samples.csv`; `exam-attemptM/s<seed>/<cell>.log` and `.out`, `exam-attemptM/EXAM_CELLS_COMPLETE.json`; `EXAM_VERDICT.json` (always, final) and `EXAM_VERDICT_PASS.json` (pass only, the success artifact); `CHAIN_STAGE_STATUS.json` (phase heartbeat: `waiting-gpu-lock`, `plan-only`, `training`, `exam`, `verdict`, `exited` with the exit code).

## Stage wrapper and plan

One wrapper per stage, for example `/home/rache/chain-20261002/r01.sh` (values are examples; the registered plan wins):

```bash
#!/usr/bin/env bash
set -uo pipefail
export C=/home/rache/bloodbowl-rl-longrun-20261002
export RUNG=0 RESET_PCT=0 SEED=42 STEPS=3000000000
export STAMP=<unique stamp for this stage>
export PREV_COMPLETE=<parent run dir>/LADDER_RUNG_COMPLETE.json
export LADDER_ARM=r0_poss_half SCRIPTED_BANK_TAG=4 SCRIPTED_BOT_TYPE=0
export FROZEN_BANK_PCT=0.12 LADDER_CHAIN_LR_SCALE=0.5 LADDER_CHAIN_ENT_SCALE=2.0
export LADDER_GAMMA=0.999 LADDER_GAE_LAMBDA=0.95 LADDER_REPLAY_RATIO=1.0
export DEADLINE_HOURS=16 NUM_THREADS=16
export LADDER_PROFILE=graft GRAFT_REASON="<DECISIONS entry>"
export GRAFT_FROM_SOURCE_SHA256=<old source digest>
export GRAFT_FROM_PATCH_BUNDLE_SHA256=<old patch bundle digest>
export PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1
export EXAM_RULE=drift-guard EXAM_GUARD_FLOOR_S42=0.541
export EXAM_GUARD_FLOOR_S43=0.551 EXAM_GUARD_FLOOR_MEAN=0.546
exec bash "$C/tools/chain_stage.sh"
```

Stage 2's wrapper differs in `STAMP` and names stage 1's marker as `PREV_COMPLETE`. `runs/campaigns/<id>/CAMPAIGN_PLAN.json`:

```json
{
  "schema_version": 1,
  "campaign_id": "<id>",
  "root": "/home/rache/bloodbowl-rl-longrun-20261002",
  "trainer_pgrep": "[p]uffer_cuda_runtime.py train|[p]uffer train|[c]hain_stage.sh|[l]adder_stage.sh|[r]un_reward_screen.sh|[e]val_vs_contact_bot.sh",
  "stages": [
    {"name": "r01", "launch": "bash /home/rache/chain-20261002/r01.sh",
     "success": "runs/ladder-d0-<STAMP1>/EXAM_VERDICT_PASS.json",
     "progress": "runs/ladder-d0-<STAMP1>/SCREEN_STATUS.json",
     "max_attempts": 3, "max_stale_seconds": 6000},
    {"name": "r02", "launch": "bash /home/rache/chain-20261002/r02.sh",
     "success": "runs/ladder-d0-<STAMP2>/EXAM_VERDICT_PASS.json",
     "progress": "runs/ladder-d0-<STAMP2>/SCREEN_STATUS.json",
     "max_attempts": 3, "max_stale_seconds": 6000}
  ]
}
```

`[c]hain_stage.sh` keeps a stage that is waiting on the lock alive in the supervisor's eyes, and `[e]val_vs_contact_bot.sh` covers the exam. `SCREEN_STATUS.json` is not written during the 9 minute exam or a lock wait (a Kill Team lease is up to 80 minutes), so `max_stale_seconds` is 6000. STALE is a report; the supervisor never kills.

The liveness probe is `pgrep -f`, so any command line on the rig that contains `chain_stage.sh` (an editor, a `tail`, this repo's stage tests) reads as a live stage and holds the chain at BUSY. Off-box probes must use the bracketed patterns. Each wrapper's `STAMP` must match its stage's `success` and `progress` paths; a mismatch halts the chain after the first rung, so generate the wrappers and the plan from one list.

## Halt and resume

- **Pause after the current stage:** `systemctl --user disable --now chain-supervisor@<id>.timer`. The running stage finishes and registers its verdict. Use `disable`, not `stop`: an enabled timer starts again at the next boot.
- **Stop now:** disable the timer, then send TERM to the one trainer wrapper PID in `screen-attemptN/<tag>.log.process.json`. The wrapper records status 143, the screen, rung and stage unwind, and the lock is released. The stage itself honours TERM only between steps: sent during a rung it waits for the rung and then exits 143 before the exam; sent during an exam it exits after the running cell (about 90 seconds); sent during a lock wait it exits after the current `flock` round (up to 10 minutes). Kill by PID only.
- **Resume after a stop or an exit 4:** `mkdir <run dir>/screen-attempt<N+1>` (this is the deliberate retry), set the stage's `attempts` to 0 and `halted` to false in `CAMPAIGN_STATE.json`, then `systemctl --user enable --now chain-supervisor@<id>.timer`.
- **A failed verdict cannot be resumed.** Continue only with a new stage (new `STAMP`) in the plan.
- **Preflight:** `PLAN_ONLY=1 bash r01.sh`, then `campaign_supervisor.py --plan ... --state ... --dry-run` must print `WOULD-LAUNCH`.

## Known gaps

1. A halt is silent. Nothing here alerts. An off-box check must read `CAMPAIGN_STATE.json` (`halted`, `complete`) and `CHAIN_STAGE_STATUS.json` (phase and age), and flag a `training` phase whose `SCREEN_STATUS.json` is older than 10 minutes.
2. The live integrity guard uses wall-clock time, so a host suspend of 3 minutes kills a healthy rung. That leaves `LIVE_INTEGRITY_FAILURE.json`, which this stage treats as final (exit 4, halt).
3. No mid-rung resume. A host restart costs the partial rung (review LP5, by decision).
4. A veto halts the chain. Falling back to the last passing parent is not built.
5. The supervisor's relaunch after a reboot has never run on the rig. Test it with a disposable campaign.
6. Any long-lived process that inherits fd 7 holds the GPU lock after the stage exits. The next stage then waits and the supervisor reports BUSY, never HALT.
7. The stage holds the lock for the whole rung and exam, so other GPU jobs wait up to 9.7 hours.
8. The registered gate's tournament half is off the box. Every rung is a speculative continuation until its tournament is read.
9. The plan pass is recognised by two printed lines (`SCREEN PLAN VERIFIED: ` and `LADDER_RUNG_SCREEN_EXIT=0`). A wording change in those scripts makes the stage exit 6 before training, not train unverified.
