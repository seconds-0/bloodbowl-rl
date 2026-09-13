# Scope: chain 28, the exact-PBRS distance arm at gamma 0.999

Written 2026-09-13, after D393, while chain 27 trains. This is a launch recipe
and a pre-registered analysis. Nothing was launched.

## Summary

Chain 28 is chain 25's recipe with one change: the reward arm goes from
`r0_poss_half` to `r0_poss_half_pbrs999`. The warm marker, seed, steps, bank
count, bank share, bot, LR, horizon (gamma 0.999, lambda 0.95) and pool
identity all stay the same.

`puffer/config/rewards/r0_poss_half_pbrs999.json` (schema 2, sha `65bd2cc7`)
carries every `r0_poss_half` coefficient unchanged. Its only difference is
`reward_dist_pbrs_gamma`: absent under schema 1, which means the legacy raw
delta, and 0.999 here. `r0_poss_half`'s own digest `433c7920` is unchanged.

Chains 25 and 26 replicated a gain at gamma 0.999 over the 0.995 continuations
(D392/D393). The confound named in D391 and D393 is that `r0_poss_half`'s
distance channels are the pinned legacy raw delta, whose bias moves with gamma.
The gain therefore belongs to "horizon + distance form" jointly. Chain 28 holds
the horizon fixed and switches only the distance form, so its reading against
chain 25 isolates the distance form at gamma 0.999.

The change lives on branch `feat/pbrs999-horizon-arm-20260913`:

- `8d9f4b9` wires the arm into the screen's arm map. The screen's up-front
  reward guard held every shipped manifest to the contract gamma 0.995, so
  shipping a manifest minted at 0.999 would have refused every plan. A named
  horizon arm is now held to the gamma it declares in that sweep. The selected
  rung arm is always held to the trainer gamma, so selecting it without its
  horizon is still refused before any plan is published.
- `8aba276` adds it to the ladder arm allowlist.

The branch changes only `tools/` and `puffer/config/rewards/`.
`install_puffer_env.sh`'s `snapshot_hash` covers `puffer/bloodbowl` only, and
`bloodbowl.ini` is untouched. The source digest stays `3ed6899e`, so no
reinstall or rebuild is needed and chain 9's lineage sidecar still binds.

## What "distance form" means here

The two forms differ by more than the `(1-gamma)*Phi'` term.

- **Within a regime.** Legacy emits `Phi' - Phi` with `Phi = -k*d`. Exact PBRS
  emits `gamma*Phi' - Phi` with `Phi = k*(D_max - d)`. Their difference per
  step is `-(1-gamma)*Phi_exact(s')`. On the carry channel (k 0.04,
  `Phi <= 1.0`) that is at most 0.001 at gamma 0.999, against 0.005 at 0.995.
- **Across regime changes.** Legacy sets Phi to NaN when a regime goes
  inactive and re-anchors wherever possession resumes (D226), so a drop is
  never charged. Exact PBRS charges `-Phi` on the exit and pays `gamma*Phi` on
  re-entry. A carrier one square from the end zone who loses the ball is
  charged up to 1.0 on the carry channel. Legacy charges nothing.
- **Boundaries.** Exact PBRS emits across a score or drive boundary and pays
  back `-Phi(s_T-1)` at the terminal. Legacy skips any step where a team
  scored and emits nothing at the terminal.

So chain 28 swaps the legacy ratchet for an exact potential. Exact PBRS is
policy invariant (Ng, Harada and Russell); the ratchet is not. A flat reading
says the ratchet did not shape what chains 25/26 learned. It does not only say
the 5x-smaller bias term was harmless.

## Clamp and envelope

`bbe_reward_clip_threshold` (`puffer/bloodbowl/bloodbowl.h`) and
`tools/reward_manifest.py` compute the same envelope.

| | r0_poss_half (legacy) | r0_poss_half_pbrs999 (exact) |
|---|---|---|
| objective `td + max(win, draw)` | 1.0 | 1.0 |
| full-pitch fetch `25 * dist_ball` | 0.5 | 0.5 |
| full-pitch carry `25 * dist_endzone` | 1.0 | 1.0 |
| derived envelope (tight clip instrument) | max = **1.0** | sum = **2.5** |
| trainer clamp (`BBE_TRAINER_REWARD_CLAMP`, patch) | 8.0 | 8.0 |

On the exact path the envelope is 2.5, which leaves 5.5 of margin under the
8.0 clamp. The distance channels alone cannot put more than 1.5 on one step,
because `|gamma*Phi' - Phi| <= 25k` per channel with `Phi` in `[0, 25k]`.
Neither channel exceeds the per-channel full-pitch cap of 1.0. So the
distance channels can cause no clipping. The honest limitation in
`bloodbowl.h` still applies: the other dense channels are bounded only by
`|c| <= 1` per coefficient.

## Evidence

Python suites on the branch, from the repo root. `test_reward_manifest` runs
from `tools/`. `test_experiment_contracts` needs `PYTHONPATH=tools`, or two of
its tests error on the import, which is identical on origin/main.

| suite | before (tests only, no manifest) | after |
|---|---|---|
| `test_reward_manifest` | 19 ran, 3 errors (the new pbrs999 tests) | 19 OK |
| `test_ladder_rung_profile` | 34 ran, 3 failures + 1 error | 34 OK |
| `test_ladder_knobs` | 16 OK | 16 OK |
| `test_ladder_stage` | | 10 OK |
| `test_graft_profile` | | 24 OK |
| `test_bridge_profile` | | 19 OK |
| `test_experiment_contracts` | | 31 OK, 2 skipped |
| `test_scripted_training_guard` | | 8 OK |

With the manifest shipped but the guard unchanged, `test_ladder_rung_profile`
failed 10 tests: every contract-gamma plan was refused on
`r0_poss_half_pbrs999.json: reward_dist_pbrs_gamma (0.999) != train gamma
(0.995)`. That is the case the guard change exists for.

The new tests cover these properties:

- The manifest differs from `r0_poss_half` only in `reward_dist_pbrs_gamma`.
  It renders `r0_poss_half`'s CLI tokens in order plus one gamma token, and
  both digests are pinned.
- It resolves as `exact_pbrs` at 0.999 and is refused at 0.995, 0.998 and
  0.9995. The CLI refuses at 0.995 with empty stdout.
- The envelope numbers are as tabled above.
- On a stand-in build, the screen plans the arm at `LADDER_GAMMA=0.999`
  (`SCREEN PLAN VERIFIED`, contract arm `r0_poss_half_pbrs999`, reward sha
  `65bd2cc7`). Its contract equals chain 25's `r0_poss_half` plan except for
  the arm and reward.
- A contract-gamma plan still verifies with the 0.999 manifest shipped.
- The arm is refused at 0.995, declared or by default, before any plan is
  published.
- The per-arm launcher receives this manifest with gamma 0.999 and lambda 0.95.

Engine C tests: `make -j4 build/puffer_reward_tests` gives 51 tests, 0
failures. That includes `puffer_reward_clip_threshold_derives_both_pbrs_forms`
and the `distance_pbrs_*` tests. A scratch fixture was not committed, because
anything under `puffer/bloodbowl` would move the source digest. It includes
`test_reward_send_off.c` and adds three checks:

- `bbe_reward_clip_threshold` reads 2.5 for the full `r0_poss_half_pbrs999`
  scalars (1.0 for the legacy twin), and `bbe_validate_reward_config` accepts
  them.
- **Telescoping.** 24 random masked games from `c_reset`, 6,400 steps, with
  only the distance channels on at gamma 0.999. The maximum `|Phi|` mid-game
  was 0.52. The trainer-discounted return `sum gamma^(k-1) r_k` equalled
  `-Phi(s_1)` for every episode and agent within 1.7e-08, and no
  undiscounted episode total was positive. Discounting the same emissions at
  0.995 misses by 0.177, so the check has power. The legacy form discounted at
  0.999 misses by 0.051, and 8 of its episode totals are positive.
- 16 random games with the full scalars: max `|reward|` 0.53, 0 clipped
  samples, 0 non-finite.

## Preflight evidence (2026-09-13, branch sha 8aba276)

The preflight ran on the rig while chain 27 trained, with the chain 25 pattern:

- A scratch clone at the branch sha was bind-mounted over the live checkout
  path in a private user+mount namespace.
- The live `vendor/PufferLib` and `runs/ladder-d0-r0chain9-20260824` were
  bind-mounted read-only, and a write probe on both was refused.
- The chain 28 env ran with `PLAN_ONLY=1` through `tools/ladder_stage.sh`.
  Every write landed under `/tmp/bbfix-pbrs999`; the script and its log are in
  `/tmp/bbfix-pbrs999/evidence/`.
- Afterwards the live checkout was still at c50fbe6 with an unchanged status,
  and no chain 28 dir existed there.
- GPU memory read 5632 MiB before and after. The `_C` import registers
  functions only; `cudaGetDeviceCount` runs only when a trainer is created.

Output:

- `drift check: OK (3ed6899e...)`
- pool rebuilt from chain 9's pool as for chain 25: anchor-kickbot
  (3541a65a9153), rung0warm1 (cf74503db2d6), rung0warm2 (3dfc0bfb353e), and
  chain 9 as rung0warm (4344e588c124). `pool identity sha256:
  d67d527b8004c125d9d408aad6056ffe636b8a3dd3272913e272e5b6c583c84b`
- `horizon gamma=0.999 gae_lambda=0.95` in the stage and rung banners
- `SCREEN PLAN VERIFIED`, `screen_manifest_sha256=2abaa443...`, then the
  normal `PLAN_ONLY` exit 1 (`screen exited 0 without SCREEN_COMPLETE.json`)
- `contract.ladder`: arm `r0_poss_half_pbrs999`, gamma 0.999, gae_lambda
  0.95, LR 0.00028, ent 0.009, scripted_bank_tag 4, bot type 0
- `contract.rewards.r0_poss_half_pbrs999.reward_sha256` `65bd2cc7`
- `contract.implementation`: source `3ed6899e`, patch bundle `de77f6c0`,
  module `d63498f6`, launcher `d8101720`
- warm `4344e588` with lineage `fde6d7f9`, pool lineage bundle `71414ee1`,
  `final_steps` 2,999,975,936

Against chain 25's own `SCREEN_MANIFEST.json`, 83 of 98 contract fields are
identical. The chain 28 contract differs in exactly these:

| field | chain 25 | chain 28 |
|---|---|---|
| `ladder.arm`, `schedule[0].arm` | r0_poss_half | r0_poss_half_pbrs999 |
| `rewards` | r0_poss_half 433c7920 | r0_poss_half_pbrs999 65bd2cc7 |
| `implementation.screen_script_sha256` | 108f36a7 | 63545cbe (this branch) |
| `prefix`, `out_dir`, `pool.path` | chain 25 stamp | chain 28 stamp |
| `pool.manifest_sha256` | 95b88a60 | d761551d (timestamped seeds file) |

## Launch recipe

Preconditions:

1. Chain 27 has finished and its exam is done. No trainer is live.
2. The live checkout
   (`/home/rache/bloodbowl-rl-qualification-candidate-10619e2`, now at c50fbe6)
   moves between runs to a commit that contains this branch. **At c50fbe6 the
   screen refuses `LADDER_ARM=r0_poss_half_pbrs999`**, and the script below
   refuses such a checkout first.
3. `bash tools/install_puffer_env.sh --check` reads OK at source 3ed6899e. No
   reinstall or rebuild is needed.

`/home/rache/r0chain28.sh`:

```bash
#!/usr/bin/env bash
# Chain 28: EXACT-PBRS DISTANCE ARM AT THE HORIZON. Chain 25's exact recipe
# (r0chain25.sh) with only the reward arm changed: r0_poss_half ->
# r0_poss_half_pbrs999 (distance channels exact discounted PBRS at 0.999, every
# coefficient identical). Warm = chain 9 frontier marker, seed 42, 3B, 4 banks x
# 0.12, contact bot at tag 4, LR 2.8e-4, gamma 0.999, lambda 0.95. Paired
# comparator = chain 25. Pool = chain 14/25 composition (d67d527b).
# docs/pbrs999-arm-scope-2026-09-13.md
set -uo pipefail
export C=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
export RUNG=0 RESET_PCT=0 SEED=42 STAMP=r0chain28-pbrs999-20260913 STEPS=3000000000
export PREV_COMPLETE="$C/runs/ladder-d0-r0chain9-20260824/LADDER_RUNG_COMPLETE.json"
export LADDER_ARM=r0_poss_half_pbrs999
export SCRIPTED_BANK_TAG=4 SCRIPTED_BOT_TYPE=0
export FROZEN_BANK_PCT=0.12
export LADDER_CHAIN_LR_SCALE=1.0
export LADDER_GAMMA=0.999 LADDER_GAE_LAMBDA=0.95
export DEADLINE_HOURS=12 NUM_THREADS=16
cd "$C" || exit 1
# A checkout without the arm refuses LADDER_ARM; one without the knob would
# train at gamma 0.995 under a horizon label.
grep -q 'r0_poss_half_pbrs999' tools/run_reward_screen.sh || {
  echo "checkout lacks r0_poss_half_pbrs999; refusing to launch chain 28" >&2; exit 1; }
grep -q 'LADDER_GAMMA' tools/run_reward_screen.sh || {
  echo "checkout lacks LADDER_GAMMA; refusing to launch a horizon arm" >&2; exit 1; }
exec bash tools/ladder_stage.sh
```

`/home/rache/r0chain28-locked.sh`, the chain 25 wrapper with the names changed:

```bash
#!/usr/bin/env bash
L=/home/rache/kt-e2e/kt-gpu.lock
exec 9>>"$L"
if ! flock -n 9; then echo "kt-gpu.lock busy; refusing to launch chain 28" >&2; exit 75; fi
echo "$(date -u +%FT%TZ) $$ acquired(lock=$L) bloodbowl-rl:chain28-pbrs999-train (long GPU run, ~7h)" >> "$L.log"
bash /home/rache/r0chain28.sh > /home/rache/r0chain28.log 2>&1
rc=$?
echo "$(date -u +%FT%TZ) $$ released(exit $rc) bloodbowl-rl:chain28-pbrs999-train" >> "$L.log"
exit $rc
```

Before launch, run `PLAN_ONLY=1 bash /home/rache/r0chain28.sh` on the live
checkout. It must print `SCREEN PLAN VERIFIED`, then exit 1 with `screen exited
0 without SCREEN_COMPLETE.json`. That run publishes
`runs/ladder-d0-r0chain28-pbrs999-20260913/{pool,POOL_IDENTITY.env,screen-attempt1/SCREEN_MANIFEST.json}`,
and the real launch reuses all three. Check four things in the manifest:

- `EXPECTED_POOL_HASH=d67d527b...`
- `contract.ladder.arm` r0_poss_half_pbrs999, `gamma` 0.999, `gae_lambda` 0.95
- `contract.rewards.r0_poss_half_pbrs999.reward_sha256` 65bd2cc7
- `contract.implementation` source 3ed6899e, patch bundle de77f6c0, module
  d63498f6

Launch it the way chain 25 was launched: a systemd user unit running the
locked wrapper. Within the first minute, confirm the arm launcher's banners in
the screen log:

- `reward_distance_form=exact_pbrs train_gamma=0.999` (chain 25 read
  `legacy_raw_delta`)
- `lr=0.00028 ent_coef=0.009 gamma=0.999 gae_lambda=0.95`

`<log>.manifest.json` must also carry `"gamma": "0.999"` and
`"gae_lambda": "0.95"`, and its `command` must include `--train.gamma 0.999
--train.gae-lambda 0.95` and `--env.reward-dist-pbrs-gamma 0.999`.

## Pre-registered analysis

**Comparator.** Chain 25 (`runs/ladder-d0-r0chain25-horizon-20260912`,
D392). It shares the parent (chain 9 marker), training seed 42, recipe, 3B
budget, pool identity d67d527b and horizon. It differs only in the distance
form. Its exam, as champion / conceded TD per game:

| exam seed | contact AWAY | contact HOME | offense AWAY |
|---|---|---|---|
| 42 | 0.565 / 0.417 | 0.489 / 0.417 | 0.583 / 0.317 |
| 43 | 0.571 / 0.410 | 0.522 / 0.419 | 0.596 / 0.313 |
| mean | 0.568 / 0.4135 | 0.5055 / 0.418 | 0.5895 / 0.315 |

**Exam.** Run only with no trainer up:
`SEED=42 /home/rache/rig_exam.sh "$CKPT" $C/runs/exam-c28-s42` and
`SEED=43 /home/rache/rig_exam.sh "$CKPT" $C/runs/exam-c28-s43`, where `CKPT`
is the `checkpoint` in chain 28's `LADDER_RUNG_COMPLETE.json`. That is three
cells of about 2,000 games each, about 9 minutes for both seeds. The reward
does not enter the exam.

**Scoring.**

- Champion cells only, on the two-exam-seed mean, as deltas against chain 25.
- The D268 champion floor is 0.02. D277 measured champion reproducibility at
  0.011 from reseeding chain 9.
- Conceded cells and net differential are not scored from one training run.
  D277 showed reseeding alone moves conceded by up to 0.086, a floor near
  0.05, and net inherits that floor.

**Readings, fixed now:**

- **Loss: the legacy distance form carried part of the gain.** At least one
  champion cell (contact AWAY, contact HOME or offense AWAY) is down by more
  than 0.02 on the mean and down on both exam seeds. Chains 25/26 then belong
  to the horizon plus the legacy ratchet, and the ladder keeps `r0_poss_half`
  at 0.999. Caveat 1 below names the alternative explanation, a reward-switch
  transient at 3B.
- **Positive: exact PBRS beats the legacy form at the horizon.** Both contact
  champion cells are up by more than 0.02 on the mean and on both exam seeds,
  and offense AWAY is not down by more than 0.02. This is not a promotion. It
  queues the seed-44 replicate from the chain 9 marker, paired with chain 26
  (0.5515 / 0.419, 0.4975 / 0.4015, 0.5655 / 0.324), before any change to the
  ladder reward (D281, D288).
- **Flat: the gain is the horizon.** Anything else, and in particular every
  champion cell within 0.02 on the mean, is a flat reading. The chain 25/26
  gain is attributed to the credit horizon, and the legacy distance form did
  not carry a measurable part of it at this budget on one training seed. It
  does not switch the ladder reward by itself. It makes the exact form
  admissible for a later rung, which would remove the farmable ratchet (D226)
  at no measured cost.

## Caveats named in advance

1. **The warm critic meets a new reward stream, and chain 25's did not.**
   Chain 9's value head was fitted to legacy distance emissions at gamma
   0.995. Chain 25 changed only the discount. Chain 28 changes the discount
   and the emissions: regime exits are charged, emissions cross score and
   drive boundaries, the terminal pays back `-Phi`, and there is the
   in-regime offset. Part of 3B goes to re-fitting on that stream, so the
   comparison is not symmetric in critic mismatch. A loss at 3B could be a
   reward-switch transient rather than a worse asymptote. D253 showed a warm
   policy decaying under a reward switch; that switch, to `s0_both`, was far
   larger than this one. Expect value loss at or above chain 25's 0.011-0.014
   band early. That is not a kill signal. The kill signals are unchanged: the
   live integrity guard's hard counters, `illegal_frac`, `error_episodes`,
   non-finite losses, a non-zero trainer exit, or a D244 eval-tds collapse at
   publication.
2. **Distance form is the whole contrast**, not only the 5x-smaller bias term
   (see "What distance form means here"). Chain 28 prices ball security on
   the carry channel at up to 1.0 per drop, which the legacy ratchet never
   charged.
3. **The tight clip instrument moves from 1.0 to 2.5.** The env's derived
   threshold is the sum on the exact path. A non-terminal stack of other dense
   channels above 1.0 would count as a clip under `r0_poss_half` but not under
   this arm, so clip telemetry is not one-to-one comparable with chain 25. The
   trainer clamp is 8.0 in both runs.
4. **One training seed.** Same-parent continuations from chain 9 agreed within
   0.019 across seeds 42 and 44 (D285).
5. **Budget.** 3B is chain 25's budget. A flat read at 3B says nothing about
   longer runs under the exact form.
6. **The comparator is chain 25, not chain 27.** Chain 27 continues from the
   chain 25 marker; chain 28 starts from the chain 9 marker like chain 25.
   Chain 27's outcome does not change this reading.

Not verified:

- **Throughput.** SPS is expected to match chain 25 (123-129K, about 6h40m),
  since exact PBRS adds a few float ops per step and nothing else changes.
  This is an estimate.
- **Rig banners.** The per-arm launcher's `reward_distance_form=exact_pbrs
  train_gamma=0.999` banner has not been seen on the rig. `PLAN_ONLY` stops
  before the per-arm launcher, and the Mac has no vendored Python.
- **The exact path at gamma 0.999.** It has run only in the scratch CPU
  fixture above. The exact path itself trained on hardware at 0.995 (the D226
  canary and the s_both lineage).
- **The systemd unit invocation.** Copy it from chain 25's unit; it is not
  reproduced here.
