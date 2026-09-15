# Deciding-row PPO telemetry (audit B6), 2026-09-11

Branch `fix/deciding-row-telemetry-20260911`. Status: an opt-in patch. It is
verified on the Mac by `training/test_deciding_row_telemetry.py` and on the RTX
2070 rig on 2026-09-15 (results below).

## What it does

A waiting coach's rollout row has singleton `BB_A_NONE` support. That gives zero
entropy, a ratio of exactly 1 and no policy gradient, yet the stock native PPO
kernel still counts the row in its entropy, kl and clipfrac means. In self-play
this roughly halves the displayed values. `training/puffer_deciding_row_telemetry.patch`
is applied only with `BBE_DECIDING_ROW_TELEMETRY=1`. It adds these log-only
channels:

- `deciding_frac`: the share of minibatch rows where some head has more than one
  enabled action.
- `entropy_deciding`, `kl_deciding`, `clipfrac_deciding`: means over those rows.
- `explained_variance`: pooled `1 - var(ret - val) / var(ret)`.
- `grad_norm`: the mean pre-clip gradient norm per minibatch, accumulated inside
  the captured train graph right after `muon_step`.
- A `PUFFER_LOSS_JSON` line per dashboard print, with every `loss/*` value at full
  precision (non-finite values written as strings). The dashboard's loss column
  switches from `.3f` to `.3g`.

The loss and every gradient are unchanged. The stock channels keep their indices.

## Opting in and provenance

- Install with `BBE_DECIDING_ROW_TELEMETRY=1 bash tools/install_puffer_env.sh <tree>`.
  A default install reverses the patch, and `--check` requires the tree to match
  the flag.
- The patch is absent from the launchers' `puffer_patch_bundle_sha256` list, so
  that digest stays `de77f6c0…`. It does edit `src/pufferlib.cu`, so the recorded
  exact-action backend digest and the compiled module differ from a default build.
  On the rig the install recorded `c2cebf81…`, against `85fa29c0…` for the default
  tree. Environment source and the patch bundle are unchanged, so for an opted-in
  rung warm-starting from chain 9 lineage, `tools/checkpoint_lineage.py` treats this
  as a module-only difference. That calls for a `rehost` of the warm and pool
  sidecars to the opted-in module. It refuses a graft ("nothing to graft"). Once
  the S4 skip patch is also installed, the bundle digest changes and the rung
  needs `LADDER_PROFILE=graft` instead.

## Rig verification, 2026-09-15

**Verdict: the loss is unchanged, and the new channels are correct and safe to adopt.**
The rig was reached with `ssh bbrig`. Scratch trees lived under `/tmp/bbverify`, and
the live checkout was only read. Every GPU run held `kt-gpu.lock`.

- **Build.** Installed from f78c619 with `BBE_DECIDING_ROW_TELEMETRY=1`, content hash
  `3ed6899e…`, exact-action backend digest `c2cebf81…`. It compiled in 30 s with
  `--float` and `taskset -c 0-7`, and `--check` passed. `_C` imported from the scratch
  tree at precision 4. The default comparator is the same tree installed without the
  flag (digest `85fa29c0…`, the rig's recorded default).
- **Same-seed pair.** Chain 9's own argument list (2048 agents, 2 buffers, 16 threads,
  H64, minibatch 16384, 4 frozen banks x 0.12 with the contact bot at tag 4, seed 42,
  warm start `4344e588…`) plus `--train.total-timesteps 3145728` (24 training epochs),
  `--cudagraphs 10`, `--checkpoint-interval 8` and `--eval-episodes 1`. Each arm ran
  the `puffer_cuda_runtime.py` preflight and then `pufferl.main()` (a scratch driver
  that skips only the launcher manifest publication). A hook on `print_dashboard`
  recorded every `loss/*` value as `float.hex()`. Each arm took about 38 s.

### Bit identity

- **Checkpoint bytes.** All 5 checkpoints are byte-identical between default and
  opt-in (steps 131072, 1179648, 2228224, 3145728 and the post-eval 3276800;
  `74fcbe33…`, `1c559cd0…`, `a097a47a…`, `65a7e0d4…` x2). Graph capture happens at
  epoch 10, so identity holds across the captured train graph.
- **Stock losses.** `policy`, `value`, `entropy`, `kl`, `old_kl`, `clipfrac` and
  `total` are bit-identical on all 30 dashboard records from training epoch 0 through
  the final reprint (24 training epochs, 5 eval epochs, final reprint), and the log
  schedule is identical.
- **The startup panel differs.** This is the one panel printed right after
  `create_pufferl`, at agent_steps 0, and all 7 stock keys differ (for example
  clipfrac 0.063157 default versus 0.063107 opt-in). It holds no training data.
  `create_pufferl` zeroes `losses_puf`, then runs `cudagraphs + 1` warmup rollouts and
  `train_impl` calls to capture the graphs. Those run on the freshly initialized policy
  before `load_weights`, and the code restores the saved weights and momentum
  afterwards but never clears the loss accumulator. A determinism control settles it:
  a second default run against the first gives the same result. All 7 stock keys
  differ only on this startup panel (clipfrac 0.063157 versus 0.063756), every other
  record is bit-identical, and so are all 5 checkpoints. The startup panel is not
  reproducible even within one build, so its opt-in difference is not the patch.
  Don't read that panel as training telemetry in any build.

### New channels

- **PUFFER_LOSS_JSON.** 31 lines, 0 unparseable, each equal to the captured
  `flat_logs` value for value. The default log carries none. Keys: the stock 7 plus
  `deciding_frac`, `entropy_deciding`, `kl_deciding`, `clipfrac_deciding`,
  `explained_variance`, `grad_norm` and the `_puffer_*` metadata.
- **Deciding-row means.** `entropy_deciding` equals `entropy / deciding_frac` with a
  relative error of 0.0 on every training record (3e-8 on the startup panel).
  `deciding_frac` read 0.459-0.507, so the stock entropy, kl and clipfrac are about
  half the deciding-row means, as audit B6 said. For example, epoch 0 reads entropy
  0.239 against `entropy_deciding` 0.471.
- **Small-value precision.** Across training epochs kl read 5e-6 to 1.8e-3 and
  clipfrac 3e-5 to 1.2e-3. The old `.3f` dashboard printed these as 0.000 or 0.001,
  and the JSON line keeps them at full precision.
- **grad_norm.** `muon_norm_reduce` leaves the sum of squares in `muon.grad_norm_ptr`
  (`muon_clip_norm` takes its `sqrtf`), so the channel is the true pre-clip L2 norm.
  Per-epoch means read 1.34-11.36, median 1.82, against `max_grad_norm` 1.5. Clipping
  engages on most minibatches of this warm continuation, which is plausible and the
  kind of thing the channel exists to show. One epoch (15) spiked to 11.4.
- **explained_variance.** 0.81-0.90 on training epochs.
- **live_integrity_guard.** `tools/live_integrity_guard.py --complete-log` accepted
  both logs with rc 0, 23 panels each and latest agent_steps 3,145,728. It ignores the
  `PUFFER_LOSS_JSON` line.

### Recurrent CUDA qualification on the opt-in build

`tools/qualify_recurrent_cuda.py run --puffer-root <telemetry tree>` with throughput at
2048 agents, 2 buffers, 16 threads, H64 and 512 x 3: **accepted**, all 5 gates, in 22 s.

| Gate | Result |
|---|---|
| construction_state | accepted |
| graph_parity (graph-off vs graph-on) | max abs 0.0 on actions, logprobs, values, masks, observations, rewards, terminals and both decoder outputs (atol 1e-6) |
| terminal_reset | max abs 0.0 everywhere |
| ratio | max abs(ratio - 1) 1.43e-6 (atol 2e-5), frozen rows never selected |
| throughput | 187,587 SPS |

### Adopting it

The patch stays out of `puffer_patch_bundle_sha256`, so on its own an opted-in rung
keeps bundle `de77f6c0…`. The compiled module and backend digest change, so the warm
and pool sidecars need a `rehost` (see "Opting in and provenance"). Adopting it
together with the S4 scripted-bank skip changes the bundle digest, and that rung needs
`LADDER_PROFILE=graft`.
