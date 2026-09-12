# Scope: chain 25, the horizon arm (train gamma 0.999, GAE lambda 0.95)

Written 2026-09-12, after D390. This is a launch recipe and a pre-registered
analysis. Nothing was launched.

## Summary

Chain 25 is chain 14's recipe with two changes: the trainer discount goes from
0.995 to 0.999, and GAE lambda goes from 0.85 to 0.95. The warm marker, seed,
steps, bank count, bank share, bot, LR, reward arm and pool identity all stay
the same. The knob that makes this launchable is `LADDER_GAMMA` /
`LADDER_GAE_LAMBDA` on branch `feat/ladder-horizon-knob-20260912`
(`tools/ladder_stage.sh` -> `tools/launch_ladder_rung.sh` ->
`tools/run_reward_screen.sh` -> `tools/run_reward_ablation.sh`). It is a
tools-only change, so chain 9's lineage sidecar still binds.

This is not the chain 15h "horizon probe" (D274/D275). Chain 15h tested
training duration: 6B of cumulative continuation at the same discount. Chain 25
tests the credit horizon itself, which the 2026-08-20 audit (F11, plan item 6)
ranked and no run has ever varied. Every run in history used gamma in
[0.9948, 0.9976] with lambda 0.85.

| | gamma 0.995, lambda 0.85 (chain 14) | gamma 0.999, lambda 0.95 (chain 25) |
|---|---|---|
| critic horizon 1/(1-gamma) | 200 steps | 1000 steps |
| discount half-life | 138 steps | 693 steps |
| GAE window 1/(1-gamma*lambda) | 6.5 steps | 19.6 steps |
| weight of a reward 300 steps out | 0.22 | 0.74 |

For scale, the audit measured first pickup to touchdown at 179 c-steps on
average in bot-vs-bot play, and a kickoff drive at 80-180 c-steps.

## Pool identity

Chain 14 was launched by `/home/rache/r0chain14-lose.sh`: `PREV_COMPLETE` =
the chain 9 marker, `PREV_POOL` unset, `NUM_FROZEN_BANKS` unset (4), so
`POOL_KEEP` = 3. `ladder_stage.sh` resolved it this way:

- `PREV_POOL` defaults to the marker's sibling dir,
  `runs/ladder-d0-r0chain9-20260824/pool`: anchor-kickbot, rung0warm
  (735385790913), rung0warm1 (cf74503db2d6), rung0warm2 (3dfc0bfb353e).
- The composition is the weak anchor (bank 0, never rotates), then the newest
  `POOL_KEEP - 1` = 2 non-anchor banks, then the warm. rung0warm retires, and
  the chain 9 checkpoint (4344e588c124) enters under the freed name
  `rung0warm`.
- `EXPECTED_POOL_HASH` = `d67d527b8004c125d9d408aad6056ffe636b8a3dd3272913e272e5b6c583c84b`.

Chains 20 and 22 used the same env and published d67d527b as well. The chain
25 preflight built d67d527b again (below). **No pinned `PREV_POOL` is needed and
nothing has to be copied.** Leave `PREV_POOL` and `NUM_FROZEN_BANKS` unset;
chain 23/24's `/home/rache/pool-pop8-20260901` is a different pool. The
rebuild depends on the four bank sources still existing, and all four were
present on 2026-09-12:

- `/home/rache/box2/1787089970913/0000004999872512.bin`
- `vendor/PufferLib/checkpoints/bloodbowl/1787314366343/0000002999975936.bin`
- `vendor/PufferLib/checkpoints/bloodbowl/1787338735330/0000002999975936.bin`
- `vendor/PufferLib/checkpoints/bloodbowl/1787584031608/0000002999975936.bin`

`pool.manifest_sha256` differs on every build because `league_seeds.json`
carries a creation timestamp. It is not part of the identity hash.

## Launch recipe

Preconditions:

1. The knob branch is merged, and the live checkout
   (`/home/rache/bloodbowl-rl-qualification-candidate-10619e2`, now at 2ae5144)
   is moved to a commit that contains it, between runs. **At 2ae5144 the screen
   does not know `LADDER_GAMMA`: it would ignore the variable and train at
   0.995 under a horizon label.** The script below refuses such a checkout.
2. `bash tools/install_puffer_env.sh --check` reads OK at source 3ed6899e.
   The change is tools-only, so no reinstall or rebuild is needed.
3. No trainer is live, and the exam of the previous rung is done.

`/home/rache/r0chain25.sh`:

```bash
#!/usr/bin/env bash
# Chain 25: HORIZON ARM. Chain 14's exact recipe (r0chain14-lose.sh) with only
# the trainer discount and GAE lambda changed: gamma 0.995 -> 0.999, lambda
# 0.85 -> 0.95. Warm = the chain 9 frontier marker, seed 42, 3B, 4 banks x 0.12,
# contact bot at tag 4, LR 2.8e-4. Paired comparator = chain 14. Pool = chain
# 14's composition rebuilt from chain 9's pool (d67d527b).
set -uo pipefail
export C=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
export RUNG=0 RESET_PCT=0 SEED=42 STAMP=r0chain25-horizon-20260912 STEPS=3000000000
export PREV_COMPLETE="$C/runs/ladder-d0-r0chain9-20260824/LADDER_RUNG_COMPLETE.json"
export LADDER_ARM=r0_poss_half
export SCRIPTED_BANK_TAG=4 SCRIPTED_BOT_TYPE=0
export FROZEN_BANK_PCT=0.12
export LADDER_CHAIN_LR_SCALE=1.0
export LADDER_GAMMA=0.999 LADDER_GAE_LAMBDA=0.95
export DEADLINE_HOURS=12 NUM_THREADS=16
cd "$C" || exit 1
# A checkout without the knob would silently train at gamma 0.995.
grep -q 'LADDER_GAMMA' tools/run_reward_screen.sh || {
  echo "checkout lacks LADDER_GAMMA; refusing to launch a horizon arm" >&2; exit 1; }
exec bash tools/ladder_stage.sh
```

Before launch, run the live preflight with `PLAN_ONLY=1 bash
/home/rache/r0chain25.sh`. It must print `SCREEN PLAN VERIFIED`; it then exits
1 with `screen exited 0 without SCREEN_COMPLETE.json`, which is normal for
`PLAN_ONLY`. That run publishes
`runs/ladder-d0-r0chain25-horizon-20260912/{pool,POOL_IDENTITY.env,screen-attempt1/SCREEN_MANIFEST.json}`,
and the real launch reuses all three. The pool is reused through
`POOL_IDENTITY.env`. The attempt dir has no log, so it is picked again, and the
manifest is reused only if the contract is identical. Check three things in
that manifest:

- `EXPECTED_POOL_HASH=d67d527b...`
- `contract.ladder.gamma` 0.999 and `contract.ladder.gae_lambda` 0.95
- `contract.implementation` source 3ed6899e, patch bundle de77f6c0, module
  d63498f6

Launch it the way chain 23 was launched (a systemd user unit, optionally behind
`kt-gpu.lock`). Within the first minute, confirm the arm launcher's banner in
the screen log: `reward_distance_form=legacy_raw_delta train_gamma=0.999` and
`lr=0.00028 ent_coef=0.009 gamma=0.999 gae_lambda=0.95`. Also confirm that
`<log>.manifest.json` carries `"gamma": "0.999"`, `"gae_lambda": "0.95"`, and
`--train.gamma 0.999 --train.gae-lambda 0.95` in `command`.

## Preflight evidence (2026-09-12, branch sha cd9bf95)

The plan-only path ran on the rig against a scratch clone at the branch sha, so
the live checkout and `/home/rache/*.sh` were not touched. The patch bundle
digest labels each patch by absolute path. A clone at another path therefore
computes a different bundle and cannot bind chain 9's sidecar, and neither can
anything else outside the live path. The preflight therefore ran in a private
user+mount namespace:

- The clone was bind-mounted over the live checkout path.
- The live `vendor/PufferLib` and `runs/ladder-d0-r0chain9-20260824` were
  bind-mounted read-only on top.
- The chain 25 env above ran with `PLAN_ONLY=1` through `tools/ladder_stage.sh`.
- Every write landed in `/tmp/bbfix-horizon`. Afterwards the live checkout was
  still at 2ae5144 with an unchanged status, and no chain 25 dir existed there.

Output:

- `drift check: OK (3ed6899e...)`
- `pool identity sha256: d67d527b8004c125d9d408aad6056ffe636b8a3dd3272913e272e5b6c583c84b`
- `horizon gamma=0.999 gae_lambda=0.95` in both the stage and rung banners
- `SCREEN PLAN VERIFIED`, `screen_manifest_sha256=ec90d7c3...`

Against chain 14's own `SCREEN_MANIFEST.json`, the chain 25 contract differs
in exactly these fields:

| field | chain 14 | chain 25 |
|---|---|---|
| `ladder.gamma` | absent | 0.999 |
| `ladder.gae_lambda` | absent | 0.95 |
| `implementation.screen_script_sha256` | 0e5252c9 | 108f36a7 (tooling since August) |
| `implementation.launcher_sha256` | 424d9e36 | d8101720 (tooling since August) |
| `prefix`, `out_dir`, `pool.path` | chain 14 stamp | chain 25 stamp |
| `pool.manifest_sha256` | 4acc8741 | 84a312c6 (timestamped seeds file) |

Everything else is identical:

- `implementation.source_sha256` 3ed6899e, `puffer_patch_bundle_sha256`
  de77f6c0 and `compiled_module_sha256` d63498f6
- warm 4344e588 with lineage fde6d7f9
- pool identity d67d527b and lineage bundle 71414ee1
- reward `r0_poss_half` 433c7920
- `final_steps` 2,999,975,936
- every setting: 4 banks, share 0.12, 2048 agents, H64

The screen's up-front reward guard passed `r0_poss_half`, a pinned legacy
raw-delta manifest, at train gamma 0.999. On the same stand-in build, an
exact-PBRS arm (`s_both`, minted at 0.995) is refused at 0.999
(`tools/test_ladder_rung_profile.py`).

## Pre-registered analysis

**Comparator.** Chain 14 (`runs/ladder-d0-r0chain14-20260825`, D273/D274).
It shares the parent, training seed, recipe, 3B budget and pool identity, and
differs only in gamma and lambda. Its exam, as champion / conceded TD per game:

| exam seed | contact AWAY | contact HOME | offense AWAY |
|---|---|---|---|
| 42 | 0.511 / 0.424 | 0.439 / 0.428 | 0.579 / 0.320 |
| 43 | 0.496 / 0.406 | 0.448 / 0.392 | 0.572 / 0.369 |
| mean | 0.5035 / 0.415 | 0.4435 / 0.410 | 0.5755 / 0.3445 |

**Exam.** Run only with no trainer up:
`SEED=42 /home/rache/rig_exam.sh "$CKPT" $C/runs/exam-c25-s42` and
`SEED=43 /home/rache/rig_exam.sh "$CKPT" $C/runs/exam-c25-s43`, where `CKPT`
is the `checkpoint` in chain 25's `LADDER_RUNG_COMPLETE.json`. That is three
cells of about 2,000 games each, and both seeds took 9 minutes for chain 23.
The discount does not enter the exam.

**Scoring.**

- Champion cells only, on the two-exam-seed mean, as deltas against chain 14.
- The D268 champion floor is 0.02. D277 measured champion reproducibility at
  0.011 from reseeding chain 9.
- Conceded cells and net differential are not scored from one training run.
  D277 showed reseeding alone moves conceded by up to 0.086, a floor near
  0.05, and net inherits that floor.

**Readings, fixed now:**

- **Positive:** both contact champion cells are up by more than 0.02, and
  offense AWAY is not down by more than 0.02. This is *not* a promotion. It
  queues the seed-44 replicate from the chain 9 marker (chain 26), paired with
  chain 20 (0.5045 / 0.4075, 0.4625 / 0.4040, 0.5570 / 0.3420), before any
  verdict. D281 retracted a one-training-seed pass, and D288 set the same
  replicate rule.
- **Negative:** a contact champion cell is down by more than 0.02 on the mean
  and down on both exam seeds. The horizon arm is rejected at this budget.
- **Anything else is a flat null on one training seed**, not promoted and not
  rejected (the D390 wording).
- Any promotion also has to clear the absolute bar, the chain 9 + chain 16
  pooled frontier: 0.537 / 0.416, 0.492 / 0.406, 0.571 / 0.350.

**Caveats named in advance.**

1. **Critic warm start.** The warm's value head was fitted at gamma 0.995, and
   so was every ancestor's. At 0.999 the value targets change scale for any
   persistent shaping. The possession annuity (0.015 per held team turn in
   `r0_poss_half`) sums over a horizon about 5x longer. With `vf_coef` 1.0 and
   `vf_clip_coef` 0.5, the critic re-fits over many updates. **An early
   value-loss spike, or elevated value loss and noisier advantages through the
   first part of the run, is expected and is not a kill signal.** Lambda 0.95
   leans advantages toward sampled returns and away from the mis-scaled critic,
   which softens this. For reference, chain 14's dashboard value loss read
   0.003-0.004 on every panel from 131K steps to 3B, after a 0.078 startup
   panel. A chain 25 value loss well above that band early in the run is the
   re-fit, not a failure. The kill signals are unchanged: the
   live integrity guard's hard counters, `illegal_frac`, `error_episodes`,
   non-finite losses, a non-zero trainer exit, or a D244 eval-tds collapse at
   publication. The per-step reward envelope and the 8.0 clamp are unaffected,
   because gamma changes returns, not emissions.
2. **Distance bias moves with gamma.** `r0_poss_half`'s distance channels are
   the pinned legacy raw delta. Raw `Phi' - Phi` exceeds exact PBRS
   `gamma*Phi' - Phi` by `(1-gamma)*Phi'` per step, so at 0.999 that bias is 5x
   smaller. The arm changes the credit horizon and shrinks the legacy distance
   bias together. A positive read cannot be attributed to the horizon alone.
3. **Budget.** 3B is chain 14's budget. Part of it goes to re-fitting the
   critic, so a flat read at 3B says nothing about longer horizon runs.
4. **One training seed.** Same-parent continuations from chain 9 agreed within
   0.019 across seeds 42 and 44 (D285). Continuations from different parents
   differed by 0.03-0.04 (D284/D287).

## SPS and wall time

Chain 14 trained 2,999,975,936 steps from 04:01:09Z to 10:39:50Z on 2026-08-26.
That is 6h38m41s of wall time and 125.4K SPS end to end, including startup and
the 10,000-game eval phase, with a 126.0K mean over 22,995 dashboard panels.
Gamma and lambda are scalars in the advantage computation. The batch shape,
pool width, env and network do not change, so expect the same ~125K SPS: about
6h40m on an idle rig, plus about 9 minutes for the two-seed exam.
`DEADLINE_HOURS` 12 leaves ample margin. Chain 23's 98-105K SPS ran 8 banks
and does not transfer. This estimate is not measured for chain 25. VRAM and
thermal behaviour should match chain 14 (VRAM 6.3/8 GB on its first panel), and
that is also an expectation, not a measurement.
