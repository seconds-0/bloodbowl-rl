# Scripted bank forward skip (audit S4), 2026-09-11

Branch `fix/skip-scripted-bank-forward-20260911`. Status: implemented as an opt-in
patch. Verified on the Mac, and **compiled, trace-checked and benchmarked on the RTX
2070 rig on 2026-09-15**: accepted. Skip SPS was x1.148 at 1 bank, x1.080 at 4 and
x1.061 at 8, against a 2.07% 0-bank noise band, and every trace check passed. See
"Rig verification results, 2026-09-15" below.

## What it does

In chain-9-style runs (`SCRIPTED_BANK_TAG=4`, 4 frozen banks x 0.12) and in chain 23
(`SCRIPTED_BANK_TAG=8`, 8 x 0.06), the scripted contact bot plays every seat of the
bank tagged `env.scripted_bank_tag`. `bloodbowl.h` `c_step` picks the bot action and
never decodes the sampled tuple on those seats (`bloodbowl.h:3466-3473`). The
native rollout still ran a full frozen-policy forward plus `sample_logits` for that
bank at every step, then threw the result away.

`training/puffer_skip_scripted_bank_forward.patch` (applied only with
`PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1`) makes these changes:

- `src/scripted_bank_skip.h` (new, host-only C) defines
  `scripted_bank_skip_index(is_bloodbowl, scripted_opponent, scripted_opponent_team,
  scripted_bank_tag, num_frozen_banks)`. It returns the bank loop index to skip, or
  0. It is nonzero only for Blood Bowl with `scripted_opponent != 0`,
  `scripted_opponent_team == 1` (AWAY) and `1 <= scripted_bank_tag <=
  num_frozen_banks`, and the index equals the tag, because frozen bank `b-1` is loop
  index `b` and selfplay tags its envs `b`. Global bot mode (`tag <= 0`) and every
  learned bank keep their forward.
- `create_pufferl_impl` reads those three env kwargs after the frozen banks exist
  and before CUDA graph capture, so the captured rollout graph omits the forward.
- `net_callback_wrapper` skips `reset_recurrent_state_on_terminal`,
  `policy_forward` and `sample_logits` for that loop index. It zero-fills the slice's
  rollout actions, logprobs and values, and copies the zero actions into
  `env.actions`. The slice's rollout `action_mask` is not rewritten: it keeps the
  env's marginal mask, which the rollout step casts into every row before the bank
  loop.
- `pufferl_set_env_tags` calls `scripted_bank_skip_validate` and aborts unless every
  row of the skipped slice, in every buffer, is the AWAY seat of an env tagged with
  the scripted tag, and every such seat lands in that slice.
- `rollouts()` throws if the skip is active but routing was never validated (for
  example `selfplay.enabled=0` with a scripted tag).
- `_C.scripted_bank_forward_skip = True` and
  `_C.scripted_bank_skip(pufferl) -> {"bank", "routed"}` let probes see which build
  they run.

## What stays identical, and what does not

Identical for the learner and every non-scripted bank:

- Each bank samples with its own RNG slots (`rng_states[buf] + bank_off`, one state
  per row), so skipping one slice changes no other row's draws.
- The env RNG and the bot's dice live in the CPU env and never touch trainer RNG.
- PPO never selects frozen rows (`puffer_frozen_prio_mask.patch`), and advantages
  and values are row-local, so zeroed values and logprobs on the scripted rows
  cannot reach the learner update.

So env trajectories, observations, rewards, terminals and env metrics should be
bit-identical, as should the actions, logprobs, values and rollout action masks
of every non-scripted bank. The probe below checks exactly that against a
determinism control.

Different by design: the scripted bank's rollout actions, logprobs, values, decoder
activations and recurrent state are now zero or stale, and so is its rollout
action mask. `sample_logits` rewrites each sampled row's mask with the exact-joint
support conditioned on the heads sampled before it (`src/pufferlib.cu:558-588` in
10619e2), but the skip continues before `sample_logits`. The scripted slice
therefore keeps the env's marginal mask. That mask is **not** a superset of the
conditional mask a default build stores. The joint support carries values the
marginal mask never marks, such as the virtual arg 32 that `my_pack_joint_actions`
packs for waiting and step tuples. So a skipped row can widen and narrow at the
same time. Measured on the rig on 2026-09-15 (32 rollouts, 512 agents x H8): the
scripted slice differed in 290 of 15,360 (step, row) pairs at 4 banks and 177 of
7,680 at 8 banks. Every differing row both widened and narrowed, and the type
head never differed. Most narrowed arg bits were arg 32, and the rest were real
args and squares. Nothing consumes it: PPO never selects frozen rows. The existing qualification
cells do not use a scripted tag, so they are unaffected. A new qualification cell
with a scripted tag would see a never-written decoder output for that bank.

## Opting in and provenance

- Install: `PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 bash tools/install_puffer_env.sh <tree>`
  applies it after the whole stack. Any other install reverses it, and `--check`
  refuses a stale copy.
- The default tree and default bundle are unchanged. `run_reward_screen.sh` and
  `run_reward_ablation.sh` append the patch to `puffer_patch_bundle_sha256` only
  when the vendored tree reverse-applies it. Measured on the rig's 10619e2 tree, the
  branch's arm block gives `de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad`,
  which is chain 9's recorded digest.
- An opted-in build is a **new lineage**. Chain 9's frontier checkpoint and the pop8
  pool sidecars bind the default bundle, so an opted-in rung that warm-starts from
  them has to be a graft (`LADDER_PROFILE=graft`,
  `GRAFT_FROM_PATCH_BUNDLE_SHA256=de77f6c0…`, the unchanged
  `GRAFT_FROM_SOURCE_SHA256`, and a `GRAFT_REASON` naming S4). It cannot be a
  module-only rehost. Chain 23 as queued (`/home/rache/r0chain23.sh`) is unaffected.

## Verified on the Mac

- The installed tree was rebuilt from the pin (`9836f0d2` + `tools/install_puffer_env.sh`)
  and is byte-identical to the rig's
  `/home/rache/bloodbowl-rl-qualification-candidate-10619e2/vendor/PufferLib`
  (`src/pufferlib.cu` sha `0124dbf9…`, `src/bindings.cu` `e036203b…`, and 8 more
  files). The installed env content hash `3ed6899e…` matches too.
- The patch applies to that tree and to the rig's own copies of `src/pufferlib.cu`
  and `src/bindings.cu` (`git apply --check` in `/tmp/bbfix-skip-scripted-bank-forward`).
  With it installed, the selfplay-league, frozen-prio, qualification, reward-clamp,
  scripted-guard and warm-start patches still reverse-apply. Reversing it restores
  the tree byte for byte.
- `tools/test_skip_scripted_bank_forward.py` compiles the header and runs the
  keying rule exhaustively against the `c_step` bot-seat rule. It checks routing on
  the chain 9 and chain 23 layouts (with a mirror of `selfplay.build_perm_tags`,
  cross-checked against the real one when `PUFFER_PIN_TREE` is set) and a set of
  routing violations. It pins the CUDA hunks, the env semantics, and the installer
  opt-in/`--check` blocks. With `PUFFER_PIN_TREE` it runs the full installer
  round trip.
- `tools/test_experiment_contracts.py::test_opt_in_skip_patch_joins_the_bundle_only_when_installed`
  runs both launchers' bundle blocks on a default tree and on an opted-in tree.

## Rig verification recipe

Run this only when the GPU is free. `pgrep -f '[p]uffer_cuda_runtime.py train|[p]uffer train'`
must print nothing, and neither a trainer nor a queued job may hold the GPU. Do not
touch BBTV services or the kt-e2e GPU lock. Do not write into the 10619e2 checkout.
Work only under `/tmp/bbfix-skip-scripted-bank-forward`. Record `nvidia-smi
--query-gpu=power.limit,temperature.gpu --format=csv` first (it read 175.00 W, 56 C
on 2026-09-11; see audit B11). Hold `/home/rache/kt-e2e/kt-gpu.lock` with `flock`
for each probe and log acquired/released lines in its `.log`, as the exam waiters do.
Stop any probe at 86 C and start each throughput probe below 58 C (see step 3 for
why 82 C and 70 C did not work at the chain 9 layout).

### 1. Scratch trees and builds

```bash
D=/tmp/bbfix-skip-scripted-bank-forward
SRC=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
PY=$SRC/vendor/PufferLib/.venv/bin/python
export CUDA_VISIBLE_DEVICES=0   # the CUDA preflight refuses an unset value, as the launchers export
WARM=$SRC/vendor/PufferLib/checkpoints/bloodbowl/1787584031608/0000002999975936.bin
sha256sum "$WARM"   # expect 4344e588c124f7df2c887a824e1847008a02be57e63bd423c3c0b02964258dcc
mkdir -p "$D" && cd "$D"
git clone -q --branch fix/skip-scripted-bank-forward-20260911 \
  https://github.com/seconds-0/bloodbowl-rl.git repo
for arm in default skip; do
  rsync -a --exclude .git --exclude build --exclude .venv --exclude checkpoints \
    --exclude logs --exclude experiments "$SRC/vendor/PufferLib/" "$D/$arm/"
  ln -sfn "$SRC/vendor/PufferLib/.venv" "$D/$arm/.venv"   # read-only use of the interpreter
done
(cd repo && PUFFER_SKIP_SCRIPTED_BANK_FORWARD=0 bash tools/install_puffer_env.sh "$D/default")
(cd repo && PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 bash tools/install_puffer_env.sh "$D/skip")
cat "$D"/{default,skip}/ocean/bloodbowl/.content_hash   # both 3ed6899e…, same as $SRC
PY_DIR="$(dirname "$PY")"   # build.sh calls `python` from PATH
for arm in default skip; do
  (cd "$D/$arm" && rm -rf build && PATH="$PY_DIR:$PATH" ./build.sh bloodbowl --float)
  (cd repo && bash tools/install_puffer_env.sh --check "$D/$arm")
  (cd "$D/$arm" && "$PY" -c 'from pufferlib import _C; print(_C.__file__, _C.precision_bytes, getattr(_C, "scripted_bank_forward_skip", False))')
done
```

Expect precision 4 for both builds, `False` for default and `True` for skip. Only
the skip install prints `applied:   opt-in scripted-bank forward skip`, and only the
skip `--check` prints `opt-in scripted-bank forward skip is installed`. Each build
should take under 15 minutes. Set `PY_DIR` before the loop if your shell does not
take the inline assignment.

Generate the chain 9 argument list from its manifest, dropping run-identity knobs
and the league preseed. Frozen banks then bootstrap from the warm learner into
`$D/ckpt`, and nothing is read from or written to a pool.

```bash
"$PY" - > "$D/chain9.args" <<'PY'
import json
m = json.load(open("/home/rache/bloodbowl-rl-qualification-candidate-10619e2/runs/"
    "ladder-d0-r0chain9-20260824/screen-attempt1/"
    "ladder-d0-s42-r0chain9-20260824-r0_poss_half-s42.log.manifest.json"))
argv = m["command"][m["command"].index("bloodbowl") + 1:]
drop = {"--tag", "--eval-episodes", "--checkpoint-interval", "--selfplay.league-preseed",
        "--load-model-path"}
pairs = [argv[i:i + 2] for i in range(0, len(argv), 2)]
assert all(p[0].startswith("--") and len(p) == 2 for p in pairs)
for flag, value in pairs:
    if flag not in drop:
        print(flag); print(value)
PY
mapfile -t CHAIN9 < "$D/chain9.args"
COMMON=("${CHAIN9[@]}" --load-model-path "$WARM" --checkpoint-dir "$D/ckpt")
BANKS4=(--vec.num-frozen-banks 4 --vec.frozen-bank-pct 0.12 --env.scripted-bank-tag 4)
BANKS8=(--vec.num-frozen-banks 8 --vec.frozen-bank-pct 0.06 --env.scripted-bank-tag 8)
PROBE="$D/repo/tools/probe_scripted_bank_skip.py"
```

### 2. Determinism control and action-trace equality

This uses a small layout so `qualification_snapshot` stays under its 64 MiB cap
(512 agents x horizon 8 is about 55 MiB). Traces run rollouts only, never PPO.
`--env.max-decisions 48` makes episodes end inside the trace, so terminal resets
run and the hard-integrity counters exist. Both arms use the same truncation.

```bash
SMALL=(--vec.total-agents 512 --vec.num-threads 8 --train.horizon 8 --train.minibatch-size 4096
       --env.max-decisions 48)
for n in 4 8; do
  eval "B=(\"\${BANKS$n[@]}\")"
  for run in a b; do
    "$PY" "$PROBE" trace --puffer-root "$D/default" --output "$D/trace-default-$n$run.json" \
      --rollouts 32 -- "${COMMON[@]}" "${B[@]}" "${SMALL[@]}"
  done
  "$PY" "$PROBE" trace --puffer-root "$D/skip" --output "$D/trace-skip-$n.json" \
    --rollouts 32 -- "${COMMON[@]}" "${B[@]}" "${SMALL[@]}"
  "$PY" "$PROBE" compare --baseline "$D/trace-default-${n}a.json" --candidate "$D/trace-default-${n}b.json"
  "$PY" "$PROBE" compare --baseline "$D/trace-default-${n}a.json" --candidate "$D/trace-skip-$n.json"
done
```

Pass conditions:

- The control prints `"accepted": true, "skip_bank": 0` and `identical_banks` covering
  every bank (`[0..4]`, then `[0..8]`).
- The candidate prints `"accepted": true, "skip_bank": 4` (then 8) and
  `identical_banks` `[0, 1, 2, 3]` (then `[0..7]`). The candidate trace's
  `skip.routed` is true, and the skip build's stderr shows `create_pufferl: skipping
  the policy forward for scripted bank tag N`.
- Rollout action masks are compared per bank. Every non-skipped bank must match
  the default trace exactly. For the skipped bank, both traces record the packed
  mask bits of the configured scripted slice. The candidate's bits must be binary
  and of the same shape, but no direction is required (the marginal mask versus the
  conditional one, see above). `skipped_mask_rows_widened` and
  `skipped_mask_rows_narrowed` count the (step, row) pairs where the candidate holds
  a bit the baseline lacks, or lacks one it holds. Both should be positive, and the
  control reports 0 for both.
- Every trace's `hard_integrity` is all zero.

If the control fails, the rollout is nondeterministic on this host. That is a
finding in its own right, and the candidate comparison means nothing until it is
explained.

### 3. Throughput grid at 0/1/4/8 banks

This uses the full chain 9 layout (2048 agents, H64, minibatch 16384, 16 threads)
with a 120 s timed window after 3 warmup epochs. It alternates rollouts and PPO
updates, the same phases the dashboard reports. Interleave the builds per bank count
and wait for the GPU to fall below 58 C between probes, so both arms start from
the same near-idle temperature. A 70 C start is not enough: on 2026-09-15 this
layout heated the 2070 from 65 C to 82 C in 86 s and from 57 C to 82 C in 87 s,
and every cell peaks at 80-82 C with the power cap engaged. Stop a probe at 86 C,
the rig's own alert level (ladder runs sit at 80-83 C for hours), not at 82 C.

```bash
BANKS0=(--selfplay.enabled 0 --vec.num-frozen-banks 0 --vec.frozen-bank-pct 0
        --env.scripted-opponent 0 --env.scripted-bank-tag 0)
BANKS1=(--vec.num-frozen-banks 1 --vec.frozen-bank-pct 0.12 --env.scripted-bank-tag 1)
for n in 0 1 4 8; do
  eval "B=(\"\${BANKS$n[@]}\")"
  for arm in default skip; do
    until [ "$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits)" -lt 58 ]; do sleep 20; done
    "$PY" "$PROBE" throughput --puffer-root "$D/$arm" --output "$D/tput-$arm-$n.json" \
      --seconds 120 --warmup-epochs 3 -- "${COMMON[@]}" "${B[@]}"
  done
done
"$PY" - <<'PY'
import json, glob
for path in sorted(glob.glob("/tmp/bbfix-skip-scripted-bank-forward/tput-*.json")):
    r = json.load(open(path)); s = r["split_per_epoch"]
    print(path.rsplit("/", 1)[1], round(r["steps_per_second"]), r["skip"],
          {k: round(s[k]) for k in ("eval_gpu_ms", "eval_env_ms", "train_ms", "rollout_ms")},
          max(g.get("temperature_c", 0) for g in r["gpu_samples"]))
PY
```

Record for each cell: SPS, `eval_gpu_ms` (the dashboard GPU), `eval_env_ms` (Env),
`train_ms` (Train), maximum temperature, skip state and `hard_integrity`.

Expected (INFERRED from audit S4, where 0 to 4 banks raised GPU from 261-319 ms to
604-780 ms, a fixed cost of roughly 86-115 ms per bank forward):

- At 0 banks both builds match within noise. This cell sets the noise band.
- At 1 bank the skip build's GPU time is close to the 0-bank cell.
- At 4 banks the skip build saves about one bank forward per epoch (about 86-115 ms of
  a roughly 1.08 s epoch), which is about 8-11% SPS.
- At 8 banks (never measured on hardware before) it saves one of eight forwards.

Accept S4 if the trace comparisons pass, every `hard_integrity` is zero, and skip
SPS beats default at 1, 4 and 8 banks by more than the 0-bank noise band.

### 4. Cleanup

`rm -rf /tmp/bbfix-skip-scripted-bank-forward` after the JSON results are copied off.
Nothing else was created.

## Rig verification results, 2026-09-15

**Verdict: accepted.** Every trace check passes, and skip SPS beats default at 1, 4
and 8 banks, well outside the 0-bank noise band.

Setup: `ssh bbrig`, scratch trees under `/tmp/bbverify` (the live checkout
`/home/rache/bloodbowl-rl-qualification-candidate-10619e2` at fbaec58 was only read).
The branch sha was d673a07, and both repair commits below landed during the run.
Each probe held `kt-gpu.lock`. Recorded first: 175.00 W power limit, 56 C idle.

- **Builds.** Default and skip were installed from the branch, both at content hash
  `3ed6899e…`. Exact-action backend digests are `85fa29c0…` for default (the rig's
  recorded default) and `a54985f4…` for skip. Both builds compiled (the skip CUDA
  code for the first time) in about 33 s each, with ccache off and `taskset -c 0-7`.
  Both `--check` passed, and only skip printed `opt-in scripted-bank forward skip is
  installed`. Precision is 4 for both, and `scripted_bank_forward_skip` reads False
  and True. Every module imported from its own scratch tree.
- **Warm start.** `4344e588…` as expected.

### Trace control and candidate (512 agents x H8, 32 rollouts, `max-decisions 48`)

| Comparison | accepted | identical_banks | mask rows widened / narrowed |
|---|---|---|---|
| control, 4 banks (default a vs b) | true | [0, 1, 2, 3, 4] | 0 / 0 |
| candidate, 4 banks (default a vs skip) | true | [0, 1, 2, 3] | 290 / 290 of 15,360 |
| control, 8 banks | true | [0..8] | 0 / 0 |
| candidate, 8 banks | true | [0..7] | 177 / 177 of 7,680 |

- **Routing.** The skip traces report `skip.routed: true`, and stderr shows
  `create_pufferl: skipping the policy forward for scripted bank tag 4 (frozen bank 3)`
  (then tag 8).
- **What matched.** Observations, rewards, terminals, env metrics and every
  non-skipped bank's actions, logprobs, values and masks were identical in all 32
  rollouts. The skipped slice's actions, logprobs and values were exactly zero.
  `hard_integrity` was zero on all six traces.
- **Mask differences.** Every differing mask row widened and narrowed at once. The
  type head never differed. Most narrowed arg bits were the virtual arg 32 (111 of
  the 4-bank head-1 rows), and the rest were real args and squares. See "What stays
  identical" above.
- **Comparator.** The candidate also matches default trace b.

### Throughput grid (chain 9 layout: 2048 agents, 2 buffers, 16 threads, H64, minibatch 16384)

120 s timed window after 3 warmup epochs. Each probe started below 58 C, and every
cell reached 80-82 C with the power cap engaged. "Thermal" counts the 5 s samples
that carried a thermal slowdown flag (0x20/0x40).

| Banks | Build | SPS | GPU ms | Env ms | Train ms | VRAM GB | Max C | Thermal | Integrity zero |
|---|---|---|---|---|---|---|---|---|---|
| 0 | default | 203,285 | 252.2 | 203.7 | 154.7 | 6.20 | 81 | 2 | yes |
| 0 | skip | 206,299 | 250.9 | 195.8 | 156.7 | 6.20 | 82 | 8 | yes |
| 1 | default | 177,971 | 332.6 | 210.7 | 156.5 | 6.24 | 82 | 10 | yes |
| 1 | skip | 204,251 | 245.9 | 204.6 | 157.5 | 6.23 | 82 | 8 | yes |
| 4 | default | 132,754 | 597.8 | 198.5 | 156.4 | 6.36 | 82 | 6 | yes |
| 4 | skip | 143,389 | 513.6 | 207.3 | 155.5 | 6.35 | 82 | 0 | yes |
| 8 | default | 104,671 | 852.2 | 203.5 | 154.6 | 6.47 | 81 | 1 | yes |
| 8 | skip | 111,004 | 783.2 | 202.2 | 154.6 | 6.47 | 80 | 0 | yes |

A third 0-bank default sample, started at 52 C, read 207,535 SPS. The three 0-bank
samples span 2.07% of their mean, and that is the noise band.

| Banks | skip / default SPS | GPU ms saved | Outside band |
|---|---|---|---|
| 0 | x1.015 (+1.5%) | 1 | (sets the band) |
| 1 | **x1.148 (+14.8%)** | 87 | yes |
| 4 | **x1.080 (+8.0%)** | 84 | yes |
| 8 | **x1.061 (+6.1%)** | 69 | yes |

- **Per-forward cost.** The saving is one bank forward, 69-87 ms per epoch, which
  sits at or below the audit's 86-115 ms inference. At 1 bank the skip build's GPU
  time (246 ms) returns to the 0-bank level.
- **Caveat.** Thermal-flag counts differ between cells: the 1-bank default had 10
  flagged samples to skip's 8, and the 4- and 8-bank skip cells had none. The GPU
  time saved matches one forward at each bank count, so throttling does not explain
  the gain. Still, a single 120 s window per cell is not a precise multiplier, so
  read these as roughly +15%, +8% and +6%.
- **Chain 9 reading.** Chain 9's layout (4 banks) should gain about 8% SPS, and chain
  23/31's layout (8 x 0.06) about 6%.

### What the verification fixed on this branch

- **e4cd23c.** `compare` refused every candidate: the doc's claim that the marginal
  mask is a superset of the conditional mask is false on real data. The probe now
  counts both directions and still requires binary bits of the same shape. The test
  fixture models a conditional bit the marginal lacks.
- **76ef16e.** Every trace died in the CUDA preflight ("CUDA_VISIBLE_DEVICES evidence
  is missing or invalid") because the recipe never exported the variable. The probe
  now refuses an unset value before any CUDA call, and step 1 exports
  `CUDA_VISIBLE_DEVICES=0`.
- **Recipe.** Step 3's cooldown and stop rules changed from 70 C / 82 C to 58 C /
  86 C. At 82 C four probes were killed 86-87 s in, from 57-65 C starts.

### Adopting it

An opted-in rung changes `puffer_patch_bundle_sha256` away from `de77f6c0…`, so the
next rung warm-starting from chain 9 lineage needs `LADDER_PROFILE=graft` with
`GRAFT_FROM_PATCH_BUNDLE_SHA256=de77f6c0…`, the unchanged `GRAFT_FROM_SOURCE_SHA256`,
and a `GRAFT_REASON` naming S4 (see "Opting in and provenance").

## Batching the remaining bank forwards: design (not implemented)

Not implemented. It is neither simple nor safe to change without CUDA iteration on
the rig.

The per-bank cost today: for the Blood Bowl policy (default single-matmul encoder,
3 MinGRU layers, decoder), each bank at each step launches `reset_recurrent_state_on_terminal`,
the encoder `cublasGemmEx`, 3 x (`cublasGemmEx` + `mingru_gate` + `puf_copy`), the
decoder `cublasGemmEx`, `sample_logits` and a `cast`. That is about 12 launches on
roughly 122-row slices. The audit verifier found the added time independent of row
share, so it is a fixed cost per forward.

Design:

1. **Stacked weight arena.** Allocate every frozen bank's parameters in one
   contiguous arena with a fixed per-bank stride (the banks share arch and slice size
   `frozen_size`). `pufferl_load_frozen_bank` writes into the bank's stride, and
   selfplay swaps keep using the same call. The bf16 path casts the whole arena once.
2. **One frozen span.** Frozen rows are `[bank_layout[1], agents_per_buffer)` and each
   bank owns an equal contiguous block, so one input slice of `nb x S` rows splits
   exactly into `nb` strided blocks.
3. **Strided batched matmul.** Replace each per-bank `puf_mm` with
   `cublasGemmStridedBatchedEx` (batch `nb`, input stride `S x in`, weight stride
   `out x in`, output stride `S x out`). `mingru_gate`, `puf_copy`, the terminal reset,
   `sample_logits` (RNG pointer `rng_states[buf] + bank_layout[1]`, the same per-row
   slots as today) and the `cast` are row-wise, so each runs as a single launch over
   the span. Recurrent state becomes one `[layers, nb x S, H]` tensor.
4. **Composition with S4.** When the scripted bank is the last bank (chain 9 tag 4 of
   4, chain 23 tag 8 of 8), the span shrinks to `[bank_layout[1], bank_layout[tag])`.
   A scripted bank in the middle needs two spans, or bank ordering changes.
5. **Fallback.** Keep the per-bank loop whenever banks differ in hidden size or layers
   (`match()` sets `frozen_bank_hidden_size`/`num_layers` for a different-arch enemy)
   or slice sizes differ.

Touch points: `WeightBank` creation and destruction, `pufferl_load_frozen_bank`,
`net_callback_wrapper`, the `rollouts()` and `set_evaluation_mode` state zeroing in
`bindings.cu`, and `qualification_recurrent_state`/`qualification_snapshot`, which
index per-bank states and decoder outputs and would need views into the batched
tensors. That invalidates the qualification patch context, so the stack must be
re-cut.

Why it is riskier than the skip: strided batched GEMM can pick different kernels
than per-bank GEMM, so logits are not guaranteed bit-identical. The trace-equality
check above would become a tolerance or distribution check, and the CUDA
qualification gates (graph parity, terminal reset, frozen-row exclusion) need a
rerun. INFERRED ceiling: in chain 9 the bank forwards cost about 29% of epoch time,
so skip plus batching is bounded near 1.4x SPS. The skip alone recovers one bank's
share.
