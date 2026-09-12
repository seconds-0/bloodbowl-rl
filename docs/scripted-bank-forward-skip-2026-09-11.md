# Scripted bank forward skip (audit S4), 2026-09-11

Branch `fix/skip-scripted-bank-forward-20260911`. Status: implemented as an opt-in
patch and verified on the Mac, including a patch-apply check against the rig's real
vendored sources. It has **not** been compiled or run on CUDA yet. The rig recipe
below is still to do.

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
therefore keeps the env's marginal mask. That mask contains every projection of
the joint support, so it is a superset of the conditional mask a default build
stores, and it differs whenever a bot seat has more than one legal option.
Nothing consumes it: PPO never selects frozen rows. The existing qualification
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
on 2026-09-11; see audit B11). Stop any probe at 82 C.

### 1. Scratch trees and builds

```bash
D=/tmp/bbfix-skip-scripted-bank-forward
SRC=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
PY=$SRC/vendor/PufferLib/.venv/bin/python
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
  and a superset of the baseline's, bit for bit (the marginal mask versus the
  conditional one, see above). `skipped_mask_rows_widened` counts the (step, row)
  pairs where they differ. It should be positive, because the bot seats often have
  more than one legal option. The control reports 0.
- Every trace's `hard_integrity` is all zero.

If the control fails, the rollout is nondeterministic on this host. That is a
finding in its own right, and the candidate comparison means nothing until it is
explained.

### 3. Throughput grid at 0/1/4/8 banks

This uses the full chain 9 layout (2048 agents, H64, minibatch 16384, 16 threads)
with a 120 s timed window after 3 warmup epochs. It alternates rollouts and PPO
updates, the same phases the dashboard reports. Interleave the builds per bank count
and wait for the GPU to fall below 70 C between probes.

```bash
BANKS0=(--selfplay.enabled 0 --vec.num-frozen-banks 0 --vec.frozen-bank-pct 0
        --env.scripted-opponent 0 --env.scripted-bank-tag 0)
BANKS1=(--vec.num-frozen-banks 1 --vec.frozen-bank-pct 0.12 --env.scripted-bank-tag 1)
for n in 0 1 4 8; do
  eval "B=(\"\${BANKS$n[@]}\")"
  for arm in default skip; do
    until [ "$(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits)" -lt 70 ]; do sleep 20; done
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
