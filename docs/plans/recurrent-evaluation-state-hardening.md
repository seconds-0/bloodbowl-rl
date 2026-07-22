# Recurrent evaluation-state hardening

Status: source implementation locally verified, 2026-07-21; target-GPU gates
remain deployment-bound. Work is isolated from the active RTX 2070 recovery
queue and BBTV. This plan does not authorize deployment.

Base: merged `origin/main` at
`d1e200b4980f6b0dbb56200b2dfe471ecf80862b`.

## Confirmed defects

The pinned Puffer runtime mutates MinGRU state during CUDA-graph warmup and
restores weights, optimizer momentum, and RNG state but not primary or frozen
recurrent buffers. PufferLib PR 579 independently reproduces nonzero state
after construction and supplies the minimal all-bank cleanup.

Evaluation has a second boundary defect. Blood Bowl emits a terminal together
with the next game's initial observation, but persistent native evaluation
forwards that observation through the preceding game's recurrent state. Torch
instead clears state at every horizon-one call and discards the delayed reward
and terminal produced by the final action, so native and Torch evaluate
different policies.

Finally, training currently accepts `reset_state=False` even though PPO does
not preserve each sampled segment's initial recurrent state. Recomputed
probabilities therefore cannot represent the behavior trajectory in that mode.

## Bounded contract

1. After graph warmup, primary and every frozen-bank recurrent buffer is zero.
2. Entering evaluation mode after training starts fresh environments and
   clears all recurrent state once, preventing a partial training game from
   entering the evaluation panel. Thereafter state persists across arbitrary
   rollout-call boundaries, but a terminal clears the corresponding row before
   the next game's observation is evaluated.
3. The native terminal-row operation is part of every captured rollout graph
   and is controlled by a device-resident evaluation-mode flag; it cannot be
   omitted because capture happened during training mode.
4. Torch carries pending reward/terminal data across rollout calls and applies
   the same pre-forward terminal-row reset.
5. Public and worker training entry points reject `reset_state=False` before
   creating environments, files, or GPU state; both backends also reject a
   direct training call while evaluation mode is active. `eval()` and `match()`
   continue to use persistent state through explicit evaluation mode.
6. Default training behavior at mid-horizon terminals remains unchanged. A
   rollout-only reset there would diverge from PPO recomputation, which has no
   terminal mask or captured initial state. That larger repair is separate.

## Test-first slices

1. Add source-contract tests for the upstream post-warmup all-bank zero and
   its ordering before final synchronization.
2. Add executable Torch helper tests covering pending outcome persistence,
   training-boundary clearing, selective terminal-row reset, MinGRU/LSTM tuple
   symmetry, and shape rejection.
3. Add native source-contract tests for a device-resident mode flag, an
   unconditionally captured terminal-row kernel, global terminal indexing,
   bank-local state indexing, and placement before `policy_forward`.
4. Add public-loop tests proving train, evaluation phase, standalone eval, and
   match select the correct mode and persistent training is rejected.
5. Apply one recurrent patch after the exact-action patch in the installer;
   include it in patch-bundle identities and fail closed if any marker is
   missing.
6. Apply both patches to a fresh pinned Puffer checkout and run Torch behavior,
   tools/training, native, and sanitizer suites.

## Deployment-boundary acceptance

These checks are mandatory after the immutable baseline boundary, in a fresh
isolated 2070 checkout:

- imported source/module/patch identities match the frozen screen;
- primary and all frozen state checksums are exactly zero immediately after
  CUDA construction with graph capture enabled;
- graph-enabled and graph-disabled first deterministic logits/values match;
- primary and each frozen bank's first post-terminal output matches a freshly
  zeroed policy from the same observation;
- identical match results and first-game traces are independent of preceding
  match history;
- Torch/native deterministic outputs agree at ordinary and post-terminal
  boundaries;
- graph-enabled throughput has no material regression against the exact-action
  runtime on the same host and configuration;
- zero-update rollout/recompute ratios remain finite and equal within the
  existing exact-action tolerance;
- every hard integrity counter, including `illegal_frac`, remains exactly zero.

No canary or long run starts if any check fails.

## Local verification

- recurrent patch applies exactly after the current exact-action patch on a
  fresh pinned Puffer tree and the installer is idempotent;
- executable Torch boundary tests pass, including pending outcome persistence,
  selective terminal clearing, training-boundary clearing, and shape failure;
- 232 tools tests (2 dependency skips) and 38 training tests (1 dependency
  skip) pass;
- 442 engine tests and every focused Puffer test pass under optimized and
  ASan/UBSan builds;
- bash syntax, Python compilation of the applied Puffer sources, and
  `git diff --check` pass.

Correctness review removed a hidden-state-sized captured reset grid that would
have launched roughly 403 million no-op threads per current Blood Bowl training
rollout. The final kernel launches one thread per active row and writes layers ×
hidden only for terminal evaluation rows. Review also added direct-backend
training rejection while evaluation mode is active and fresh environment reset
at a nonzero-step train→eval transition.

## Explicitly out of scope

- terminal-aware PPO state capture/recomputation inside training horizons;
- reward coefficients, rules, observation/action semantics, BC anchors, pool
  generation, BBTV, or the active pre-repair experiment;
- any attempt to reuse qualification-only output as training ancestry.
