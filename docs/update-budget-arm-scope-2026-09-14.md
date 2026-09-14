# Scope: chain 30, the update-budget arm (replay ratio 1.0)

Written 2026-09-14, after D396. This is a launch recipe and a pre-registered
analysis. Nothing was launched.

## Summary

Chain 30 is chain 25's recipe (`/home/rache/r0chain25.sh`) with one causal
change: the trainer replay ratio goes from 0.25 to 1.0. That raises the Muon
gradient steps per 131,072-step epoch from 2 to 8. The warm marker, seed, steps,
bank count, bank share, bot, LR, reward arm, horizon (gamma 0.999, lambda 0.95),
minibatch size and pool identity all stay the same. The paired comparator is
chain 25, D396's pre-registered next arm.

The knob that makes this launchable is `LADDER_REPLAY_RATIO` on branch
`feat/ladder-replay-ratio-knob-20260914`. It is carried the way PR #99 carried
the horizon (`tools/ladder_stage.sh` -> `tools/launch_ladder_rung.sh` ->
`tools/run_reward_screen.sh` -> `tools/run_reward_ablation.sh`):

- `cfd3a8d` makes the per-arm launcher refuse any `REPLAY_RATIO` whose
  minibatch count is not whole, or that is not a plain decimal in (0,4] with
  at most three decimals. The default 0.25 passes unchanged.
- `8209f14` adds the knob to the rung screen. It is refused outside the
  ladder-rung, graft and bridge profiles. When set, it replaces the fixed
  `REPLAY_RATIO` and is recorded as `contract.ladder.replay_ratio`.
- `afb1e36` forwards it through the rung launcher. When set, the completion
  marker records `replay_ratio` from the run manifest the trainer launched
  with, and a contradicting trained value publishes nothing.
- `c4caf38` validates it in `ladder_stage.sh` before any pool is built, and
  prints the gradient steps per epoch in the stage banner.

The branch changes only `tools/`. The source digest stays `3ed6899e`, the patch
bundle `de77f6c0` and the module `d63498f6`, so no reinstall or rebuild is
needed and chain 9's lineage sidecar still binds.

## The mechanism, and which values are allowed

The native trainer counts minibatches once per epoch in
`vendor/PufferLib/src/pufferlib.cu` (the rig checkout, lines 1667-1700):

```c
int batch_size = hypers.total_agents * hypers.horizon;                   // 1668
int total_minibatches = hypers.replay_ratio * batch_size / hypers.minibatch_size;  // 1699
for (int mb = 0; mb < total_minibatches; ++mb) { ... one Muon step ... }
```

`replay_ratio` is a `float` (`pufferlib.cu:316`, set from the CLI in
`src/bindings.cu:699`). The product is float32 arithmetic, and the assignment
to `int` truncates toward zero. It is the only place the native trainer reads
the value. `torch_pufferl.py:465` has the same formula for the Torch backend.
Under the fixed contract, batch = 2048 x 64 = 131,072 and minibatch = 16,384,
so the count is `replay_ratio x 8`:

| replay_ratio | exact count | trainer runs | |
|---|---|---|---|
| 0.1 | 0.8 | 0 | trains nothing |
| 0.25 | 2 | 2 | the fixed contract since D252 |
| 0.3 | 2.4 | 2 | silently trains as 0.25 |
| 1.0 | 8 | 8 | chain 30 |
| 4.0 | 32 | 32 | the knob's ceiling |

The only exact values are the multiples of 0.125 in (0,4]: 32 values, giving 1
to 32 steps per epoch. Each k/8 is exact in float32, and 131072 x k/8 = 16384k
stays below 2^24, so the float product and quotient are exact and the cast
returns k. Every layer checks this in integer arithmetic against the batch and
minibatch it actually uses, so the checks cannot drift from the trainer.

**Minibatch and VRAM do not change at rr 1.0.** Trainer allocations are sized
by `minibatch_segments = minibatch_size / horizon` (256), `horizon` and
`total_agents` (`pufferlib.cu:2130-2172`: `policy_reg_train` at
`B_TT = 256 x 64`, `register_train_buffers`, `register_ppo_buffers`,
`register_prio_buffers`). The replay ratio only sets the loop count. The
preflight contract keeps `settings.minibatch_size` 16384. Expect chain 25's
VRAM (6.4/8 GB). That is an expectation from the code, not a measurement.

Two more things the loop body shows (read from code, not measured):

- Advantages (GAE + V-trace) are recomputed at the top of every minibatch
  (`pufferlib.cu:1702-1705`). A minibatch is then a multinomial draw of 256
  segments from the priority CDF over learner rows only (`prio_replay_cuda`,
  `multinomial_sample`), so draws are with replacement.
- At 4 banks x 0.12, 536 of 1,024 rows per buffer are learner rows (1,072
  learner segments per epoch, from the D-series bank-share comments). rr 0.25
  draws 512 segments per epoch, about 0.48x the learner segments. rr 1.0 draws
  2,048, about 1.9x, so repeated segments within an epoch become common.

## Evidence

Python suites from the repo root, `PYTHONPATH=tools python3 -m unittest ...`.
"Before" means the final branch test files run against origin/main's scripts
(ce1ad33) in a detached scratch worktree.

| suite | origin/main, own tests | branch tests vs origin/main scripts | branch |
|---|---|---|---|
| `test_ladder_knobs` | 16 OK | 20 ran, 3 failed | 20 OK |
| `test_ladder_stage` | 10 OK | 13 ran, 3 failed | 13 OK |
| `test_ladder_rung_profile` | 34 OK | 39 ran, 4 failed + 1 error | 39 OK |
| `test_graft_profile` | | | 24 OK |
| `test_bridge_profile` | | | 19 OK |
| `test_experiment_contracts` | | | 31 OK, 2 skipped |
| `test_scripted_training_guard` | | | 8 OK |

All 11 new tests that check the new behavior fail before and pass after. The
twelfth, `test_exact_ratios_pass_the_gate`, guards against over-refusal and
passes on both. Before the change, `LADDER_REPLAY_RATIO=1.0` reached the
per-arm launcher as `REPLAY_RATIO=0.25`: the knob was ignored silently.

The new tests cover these properties:

- **Refusals at every layer.** Malformed or out-of-range values are refused:
  `0`, `4.5`, `.5`, `1.`, `01`, `0.0625`, `1e0`, `nan`, padded values, and
  more. Truncating values `0.1`, `0.2`, `0.3`, `0.333`, `0.9`, `0.999`, `1.1`
  and `3.99` are refused with their own message.
- **Accepted values.** `0.125`, `0.25`, `0.5`, `1`, `1.0`, `2.375`, `4` and
  `4.000` pass. The stage banner reads 1, 2, 4, 8, 8, 19, 32 and 32 steps.
- **The count follows the launched batch.** At minibatch 32768, 0.25 passes
  and 0.125 is refused.
- **Profile gate.** The screen refuses the knob on `control-final`,
  `genesis-pool` and `possession-gain-exact`. It accepts it on graft and
  bridge, and an empty value counts as unset.
- **What reaches the trainer.** On the stand-in build, the screen hands 1.0 to
  the per-arm launcher, whose trainer argv carries `--train.replay-ratio 1.0`
  with `--train.minibatch-size 16384`. Its run-manifest pairs carry
  `replay_ratio` 1.0 and `minibatch_size` 16384. Unset, 0.25 reaches both.
- **What gets recorded.** The plan records `contract.ladder.replay_ratio` 1.0
  only when declared, and the rest of the contract equals the plain plan.
  Chain 30's knobs record gamma, gae_lambda and replay_ratio together. The
  completion marker records the trained value and refuses a contradiction.
- **The stage.** It exports the knob to the rung launcher, prints
  `update replay_ratio=... gradient_steps_per_epoch=...`, and pins its batch
  constants to the screen's `TOTAL_AGENTS x HORIZON` and `MINIBATCH_SIZE`.

**Defaults are byte-identical to origin/main.** One stand-in checkout was
planned with origin/main's `tools/`, then re-pointed at the branch's `tools/` and
planned again at the same paths:

- With the knob unset, `SCREEN_MANIFEST.json` is 5,700 bytes on both sides and
  byte-equal once two fields are masked: `created_utc`, a wall-clock stamp,
  and `implementation.screen_script_sha256`, the edited script's own digest.
- With the horizon set, the same holds at 5,750 bytes.
- The rung completion marker is raw byte-equal, 750 bytes unset and 790 bytes
  with the horizon set.
- The per-arm launcher's `CMD=(...)` and `META_ARGS=(...)` blocks are untouched,
  so the default argv and run manifest are unchanged.

## Preflight evidence (2026-09-14, branch sha c4caf38)

The preflight ran on the idle rig with the chain 25 pattern:

- A scratch clone at the branch sha was bind-mounted over the live checkout
  path in a private user+mount namespace.
- The live `vendor/PufferLib` and `runs/ladder-d0-r0chain9-20260824` were
  bind-mounted read-only, and a write probe on each was refused.
- The chain 30 env below, with `PLAN_ONLY=1`, ran through
  `tools/ladder_stage.sh`.
- Every write landed under `/tmp/bbfix-rr`. The script, the plan env and the
  log are in `/tmp/bbfix-rr/evidence/`.
- Afterwards the live checkout was still at 842969a with the same two
  untracked entries (`checkpoints/`, `logs/`), and no chain 30 dir existed
  there. GPU memory read 69 MiB before and after, and no trainer was live.

Output:

- `drift check: OK (3ed6899e...)`
- The pool was rebuilt from chain 9's pool as for chains 25 and 28:
  anchor-kickbot (3541a65a9153), rung0warm1 (cf74503db2d6), rung0warm2
  (3dfc0bfb353e), and chain 9 as rung0warm (4344e588c124).
  `pool identity sha256:
  d67d527b8004c125d9d408aad6056ffe636b8a3dd3272913e272e5b6c583c84b`
- Stage banner: `horizon gamma=0.999 gae_lambda=0.95` and
  `update replay_ratio=1.0 gradient_steps_per_epoch=8 (batch 131072 / minibatch 16384)`.
  Rung banner: `update replay_ratio=1.0`.
- `SCREEN PLAN VERIFIED`, `screen_manifest_sha256=ed8e7fd5...`, then the
  normal `PLAN_ONLY` exit 1 (`screen exited 0 without SCREEN_COMPLETE.json`)
- `contract.ladder`: arm `r0_poss_half`, gamma 0.999, gae_lambda 0.95,
  replay_ratio 1.0, LR 0.00028, ent 0.009, scripted_bank_tag 4, bot type 0
- `contract.implementation`: source `3ed6899e`, patch bundle `de77f6c0`,
  module `d63498f6`
- warm `4344e588` with lineage `fde6d7f9`, pool lineage bundle `71414ee1`,
  reward `r0_poss_half` `433c7920`, `final_steps` 2,999,975,936, settings
  2048 agents, H64, minibatch 16384

Against chain 25's own `SCREEN_MANIFEST.json`, 88 of 95 contract fields are
identical. The chain 30 contract differs in exactly these:

| field | chain 25 | chain 30 |
|---|---|---|
| `ladder.replay_ratio` | absent | 1.0 |
| `implementation.launcher_sha256` | d8101720 | e6ae1d91 (this branch) |
| `implementation.screen_script_sha256` | 108f36a7 | 09cc15fe (PR #100 + this branch) |
| `prefix`, `out_dir`, `pool.path` | chain 25 stamp | chain 30 stamp |
| `pool.manifest_sha256` | 95b88a60 | bce5a620 (timestamped seeds file) |

## SPS and wall time

The basis is chain 25's own dashboard log on the rig
(`runs/ladder-d0-r0chain25-horizon-20260912/screen-attempt1/*.log`). There are
22,997 panels. These are the medians over the 21,744 steady panels between 100M
and 2.99B steps:

| phase | median | p5-p95 |
|---|---|---|
| Evaluate (rollout) | 814 ms | 788-859 |
| - GPU | 614 ms | 602-626 |
| - Env | 176 ms | 160-207 |
| Train | 160 ms | 156-161 |
| - Misc | 15 ms | 15-15 |
| - Forward | 146 ms | 141-146 |
| SPS | 126.9K | 121.3K-130.3K |
| VRAM | 6.4/8 GB | 6.4 |
| GPU util | 86% | 83-89 |

The trainer's profile scales both train rows by the minibatch count
(`pufferlib.cu:1813-1824`). Misc is the pre-loop setup plus the last
minibatch's advantage, prioritized sampling and select-copy times the count.
Forward is the last minibatch's forward/backward/Muon step times the count.
Two minibatches at 146 ms put one at about 73 ms.

At rr 1.0 the count is 8:

- **Train phase.** Forward is about 584 ms. Misc is between 15 ms (all of it
  pre-loop) and 60 ms (all of it per minibatch). Train comes to about
  600-645 ms, consistent with D396's "about 640 ms".
- **Rollout phase.** The rollout batch shape does not change, so Evaluate
  stays about 814 ms.
- **Epoch and SPS.** An epoch goes from about 974 ms to 1,413-1,458 ms, so
  SPS drops by 31-33%, to about **85K-87K**. D396 said 25-35%.
- **Wall time.** Chain 25's process ran 23:43:13Z to 06:20:25Z, 6h37m end to
  end, including startup and the 10,000-game eval. 3B steps at 85-87K SPS is
  **about 9h30m-9h50m**, plus the same startup and eval.
- **Deadline.** `DEADLINE_HOURS` 12 would leave about two hours of margin, and
  a timeout publishes nothing. The launch script sets 16. The deadline is an
  operational bound, not part of the causal recipe, and it does not enter the
  contract.

This is a linear model of chain 25's profile, not a measurement. The in-loop
misc split and any fixed per-epoch overhead outside the profile move it
slightly.

## Launch recipe

Preconditions:

1. No trainer is live, and the previous exam is done.
2. The knob branch is merged. The live checkout
   (`/home/rache/bloodbowl-rl-qualification-candidate-10619e2`, now at 842969a)
   is moved between runs to a commit that contains it. **At 842969a the screen
   does not know `LADDER_REPLAY_RATIO`**: it would ignore the variable and train
   at 0.25 under an update-budget label. The script below refuses such a
   checkout.
3. `bash tools/install_puffer_env.sh --check` reads OK at source 3ed6899e. No
   reinstall or rebuild is needed.

`/home/rache/r0chain30.sh`:

```bash
#!/usr/bin/env bash
# Chain 30: UPDATE-BUDGET ARM. Chain 25's exact recipe (r0chain25.sh) with only
# the trainer replay ratio changed: 0.25 -> 1.0, i.e. 2 -> 8 Muon gradient steps
# per 131,072-step epoch at the same minibatch (16384). Warm = chain 9 frontier
# marker, seed 42, 3B, 4 banks x 0.12, contact bot at tag 4, LR 2.8e-4, gamma
# 0.999, lambda 0.95. Paired comparator = chain 25. Pool = chain 14/25
# composition (d67d527b). DEADLINE_HOURS 16: expect ~9h30m-9h50m at ~85-87K SPS.
# docs/update-budget-arm-scope-2026-09-14.md
set -uo pipefail
export C=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
export RUNG=0 RESET_PCT=0 SEED=42 STAMP=r0chain30-rr1-20260914 STEPS=3000000000
export PREV_COMPLETE="$C/runs/ladder-d0-r0chain9-20260824/LADDER_RUNG_COMPLETE.json"
export LADDER_ARM=r0_poss_half
export SCRIPTED_BANK_TAG=4 SCRIPTED_BOT_TYPE=0
export FROZEN_BANK_PCT=0.12
export LADDER_CHAIN_LR_SCALE=1.0
export LADDER_GAMMA=0.999 LADDER_GAE_LAMBDA=0.95
export LADDER_REPLAY_RATIO=1.0
export DEADLINE_HOURS=16 NUM_THREADS=16
cd "$C" || exit 1
# A checkout without either knob would silently train chain 25's contract under
# this label.
grep -q 'LADDER_REPLAY_RATIO' tools/run_reward_screen.sh || {
  echo "checkout lacks LADDER_REPLAY_RATIO; refusing to launch an update-budget arm" >&2; exit 1; }
grep -q 'LADDER_GAMMA' tools/run_reward_screen.sh || {
  echo "checkout lacks LADDER_GAMMA; refusing to launch a horizon arm" >&2; exit 1; }
exec bash tools/ladder_stage.sh
```

`/home/rache/r0chain30-locked.sh`, the chain 25 wrapper with the names and
expected duration changed:

```bash
#!/usr/bin/env bash
L=/home/rache/kt-e2e/kt-gpu.lock
exec 9>>"$L"
if ! flock -n 9; then echo "kt-gpu.lock busy; refusing to launch chain 30" >&2; exit 75; fi
echo "$(date -u +%FT%TZ) $$ acquired(lock=$L) bloodbowl-rl:chain30-rr1-train (long GPU run, ~10h)" >> "$L.log"
bash /home/rache/r0chain30.sh > /home/rache/r0chain30.log 2>&1
rc=$?
echo "$(date -u +%FT%TZ) $$ released(exit $rc) bloodbowl-rl:chain30-rr1-train" >> "$L.log"
exit $rc
```

Before launch, run `PLAN_ONLY=1 bash /home/rache/r0chain30.sh` on the live
checkout. It must print `SCREEN PLAN VERIFIED`, then exit 1 with `screen exited
0 without SCREEN_COMPLETE.json`. That run publishes
`runs/ladder-d0-r0chain30-rr1-20260914/{pool,POOL_IDENTITY.env,screen-attempt1/SCREEN_MANIFEST.json}`,
and the real launch reuses all three. Check four things:

- `EXPECTED_POOL_HASH=d67d527b...`
- `contract.ladder.gamma` 0.999, `gae_lambda` 0.95, `replay_ratio` 1.0
- `contract.settings.minibatch_size` 16384
- `contract.implementation` source 3ed6899e, patch bundle de77f6c0, module
  d63498f6

Launch it the way chain 25 was launched: a systemd user unit running the locked
wrapper. Within the first minutes, confirm:

- **Stage banner:** `update replay_ratio=1.0 gradient_steps_per_epoch=8 (batch
  131072 / minibatch 16384)`.
- **Arm launcher banners:** `native_precision_bytes=4 total_agents=2048
  buffers=2 threads=16 horizon=64 minibatch=16384`, and `lr=0.00028
  ent_coef=0.009 gamma=0.999 gae_lambda=0.95 replay_ratio=1.0`.
- **Run manifest:** `<log>.manifest.json` carries `"replay_ratio": "1.0"` and
  `"minibatch_size": "16384"`, and `command` includes `--train.replay-ratio
  1.0 --train.clip-coef 0.2`.
- **Hardware proof that eight minibatches run.** The dashboard's Train row
  should read about 600-650 ms, with Forward about 580 ms, against chain 25's
  160/146. The profile multiplies by the minibatch count, so this is the one
  on-device check of it. **If Train still reads about 160 ms, stop the run**:
  it is training chain 25's budget under chain 30's label.

## Pre-registered analysis

D396 fixed these readings before the knob existed.

**Comparator.** Chain 25 (`runs/ladder-d0-r0chain25-horizon-20260912`,
D392). It shares the parent (chain 9 marker), training seed 42, recipe, 3B
budget, pool identity d67d527b, horizon and minibatch size. It differs only in
the replay ratio. Its exam, as champion / conceded TD per game:

| exam seed | contact AWAY | contact HOME | offense AWAY |
|---|---|---|---|
| 42 | 0.565 / 0.417 | 0.489 / 0.417 | 0.583 / 0.317 |
| 43 | 0.571 / 0.410 | 0.522 / 0.419 | 0.596 / 0.313 |
| mean | 0.568 / 0.4135 | 0.5055 / 0.418 | 0.5895 / 0.315 |

**Exam.** Run only with no trainer up:
`SEED=42 /home/rache/rig_exam.sh "$CKPT" $C/runs/exam-c30-s42` and
`SEED=43 /home/rache/rig_exam.sh "$CKPT" $C/runs/exam-c30-s43`, where `CKPT`
is the `checkpoint` in chain 30's `LADDER_RUNG_COMPLETE.json`. That marker
must also carry `replay_ratio` 1.0. This is three cells of about 2,000 games
each, about 9 minutes for both seeds. The replay ratio does not enter the exam.

**Scoring.**

- Champion cells only, on the two-exam-seed mean, as deltas against chain 25.
- The D268 champion floor is 0.02. D277 measured champion reproducibility at
  0.011 from reseeding chain 9.
- Conceded cells and net differential are not scored from one training run.
  D277 showed reseeding alone moves conceded by up to 0.086.

**Readings, fixed in D396:**

- **Positive:** both contact champion cells beat chain 25 by more than 0.02 on
  the mean, with offense AWAY not down by more than 0.02. A seed-44 replicate
  follows before any recipe change, paired with chain 26 (0.5515 / 0.419,
  0.4975 / 0.4015, 0.5655 / 0.324).
- **Negative:** a contact champion cell is down by more than 0.02 on the mean
  and on both exam seeds.
- **Flat:** anything else. Two steps per epoch is not the binding constraint
  at this budget on one training seed.

## Caveats named in advance

D396's three:

1. **Policy drift per epoch.** More gradient steps on the same rollouts raise
   drift within an epoch. KL and clipfrac are the diagnostics, not kill
   signals. For scale, chain 25's steady panels print a median `kl` 0.000 and
   `clipfrac` 0.000 (p95 0.001) at the dashboard's three-decimal resolution.
   Expect both to rise.
2. **Wall time is the cost.** The learner phase grows from about 160 ms to
   600-645 ms per epoch, so SPS drops about 31-33% (above). The comparison is
   at equal environment steps, not equal wall-clock.
3. **LR x2 was rejected twice on warm chains (D259/D271).** This arm changes
   how often the optimizer steps on the same data, not the step size. Under
   Muon each step is a relative change of about `lr`, though, so four times
   the steps per epoch can move the weights up to four times as far per epoch
   if the steps align. A negative read could share D259/D271's mechanism, and
   this arm does not separate the two.

Also named now:

4. **The critic gets four times as many value steps per epoch** on the same
   targets. Value loss may read below chain 25's 0.011-0.014 band. That is a
   fit, not a result. The kill signals are unchanged: the live integrity
   guard's hard counters, `illegal_frac`, `error_episodes`, non-finite losses,
   a non-zero trainer exit, or a D244 eval-tds collapse at publication.
5. **Heavier replay of learner segments** (read from code, above). rr 1.0 draws
   about 1.9x the learner segments per epoch, with replacement and weighted by
   priority, so the minibatches within an epoch overlap more than at 0.25.
   Muon momentum (beta1 0.95) now accumulates over eight steps per epoch
   instead of two.
6. **Thermals.** The train share of epoch time rises from about 16% to about
   42%. Chain 25 ran 80-83 C against the 86 C alert. Watch the temperature;
   nothing here predicts it.
7. **One training seed**, and a 3B budget. Same-parent continuations from chain
   9 agreed within 0.019 across seeds 42 and 44 (D285). A flat read at 3B says
   nothing about longer runs at rr 1.0.

Not verified:

- **Throughput, VRAM and thermals.** The 85-87K SPS figure is a linear model
  of chain 25's profile. VRAM 6.4/8 GB is an expectation from the allocation
  code. Neither is measured.
- **Rig banners.** The per-arm launcher's `replay_ratio=1.0` banner and run
  manifest have not been seen on the rig: `PLAN_ONLY` stops before the per-arm
  launcher, and the Mac has no vendored Python. The argv and run-manifest pairs
  were checked by evaluating the launcher's own blocks.
- **Eight minibatches running on hardware.** Only the first-minutes Train-row
  check above confirms it.
- **The 536 learner rows per buffer** behind the replay-coverage figures come
  from the bank-share comments, not from a probe of `bank_layout`.
- **The systemd unit invocation.** Copy it from chain 25's unit; it is not
  reproduced here.
