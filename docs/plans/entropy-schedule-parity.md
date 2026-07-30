# Entropy-schedule objective parity

Status: reviewed implementation plan, 2026-07-29. No production training,
checkpoint publication, or launcher unlock is authorized by this document.

Base: rollout-transition closure commit
`28e053ff6855caaa8d9c6a400412cca80f045155`.

This is the next P0 trainer prerequisite in the environment/trainability
program. It makes the configured entropy objective mean the same thing in
native eager, native CUDA-graph, and Torch training, and makes the applied
coefficient observable from the objective kernel rather than merely from host
configuration.

Kimi review was explicitly waived by the user. Independent research review,
adversarial plan review, self-review, and independent post-implementation
review remain mandatory.

## Why this tranche is next

Production configuration currently combines:

- a nonzero entropy coefficient;
- entropy annealing;
- a nontrivial minimum coefficient ratio; and
- native CUDA graphs.

At pinned PufferLib commit
`9836f0d2e78889c1aaf189c04d161b6fc61a9386`, those settings do not describe
one objective:

1. Native eager mode recomputes a cosine coefficient before each rollout-level
   training update.
2. Native graph mode passes that coefficient into the captured PPO kernel by
   value. Replays therefore retain the capture-time coefficient.
3. Torch always multiplies entropy by the configured base coefficient and
   ignores `anneal_ent_coef` and `min_ent_coef_ratio`.

The current CUDA qualifier intentionally sets the entropy coefficient to zero,
so it cannot see this divergence. The current constructor and launch guards
correctly prevent graph-plus-anneal production execution, but they are an
interim safety mechanism rather than a repair.

PufferLib later corroborated the native defect in upstream commit
`2753605ed53c0ed7b3bcc62d6f269b9158b8cbe2` by moving the native coefficient
to a stable device scalar. That fix is useful design evidence, not a complete
patch for this repository: it leaves Torch constant, uses an unchecked
synchronous copy, provides no compiled contract or direct kernel telemetry,
and tests only inferred aggregate graph losses.

No authored-scenario learning result is admissible until the trainer objective
itself is stable and inspectable.

## Canonical schedule contract

The compiled and logged identity is:

```text
cosine-update-index-over-total-updates-fp32-v1
```

Definitions:

```text
B = checked_exact_integer(total_agents) *
    checked_exact_integer(horizon)
N = floor(checked_exact_integer(total_timesteps) / B)
e = zero-based count of successfully completed public train calls before
    the current public train call
p = clamp(e / N, 0, 1)
c_floor_real = c_base_real * min_ratio_real

c_real(e) =
    c_base_real, if annealing is disabled
    c_floor_real
      + 0.5 * (c_base_real - c_floor_real) * (1 + cos(pi * p)),
      otherwise

c_applied(e) = round-to-nearest finite IEEE-754 binary32(c_real(e))
```

The objective, gradient, kernel telemetry, and Torch telemetry use
`c_applied`, not an unrounded host double. Evidence may retain both
`c_real` and the applied binary32 value/bits.

The established pinned-native denominator is `N`, not `N - 1`. Therefore:

- the first legal update, `e = 0`, uses the base coefficient;
- the last legal update, `e = N - 1`, remains slightly above the floor;
- a pure helper lookup at `e >= N` clamps to the floor;
- a public training call at `e >= N` is rejected before objective or
  optimizer mutation;
- `N = 1` has one legal update at the base coefficient;
- `N <= 0` is rejected before backend construction.

The post-final helper value completes the mathematical schedule and supports
oracle tests. It does not authorize an extra train call.

Disabled annealing is constant at the base for all helper indices. A zero base,
zero minimum ratio, and unit minimum ratio are valid. Negative or nonfinite
bases, nonfinite ratios, and ratios outside `[0, 1]` are invalid. The anneal
flag must be an exact Boolean or canonical integral `0`/`1`; arbitrary
truthiness is not part of this contract.

One schedule index covers one rollout followed by one successful `train()`
call. It remains constant across all PPO minibatches in that call.
`update_epochs` is currently unused by both trainers and is not a schedule
authority.

## Raw configuration and arithmetic contract

Validation must happen before native values are narrowed into `HypersT`.
Validating only the resulting `bool`, `float`, or `long` would lose evidence:
`2` becomes `true`, a large finite double can become fp32 infinity, and a
fractional timestep can truncate.

The shared Python validator and the direct native constructor must both reject:

- Boolean, fractional, negative, nonfinite, or out-of-range integer fields
  used for `total_timesteps`, `total_agents`, `horizon`, or
  `minibatch_size`;
- a noncanonical entropy-anneal flag, including `-1`, `2`, `0.5`, strings,
  and nonfinite values;
- a base coefficient that is negative, nonfinite, or not representable as a
  finite binary32 value;
- a minimum ratio that is nonfinite, outside `[0, 1]`, or not representable
  as a finite binary32 value;
- a nonfinite or negative replay ratio;
- overflow in `B = total_agents * horizon`;
- `N <= 0`;
- a nonpositive minibatch size or a minibatch size incompatible with the
  horizon/batch contract; and
- fewer than one PPO minibatch per public update.

The canonical minibatch count is:

```text
M = floor(replay_ratio_fp32 * B / minibatch_size)
```

Both backends must derive the same `M`, and construction requires `M >= 1`.
This closes the current mismatch where native advances its epoch after doing
zero PPO work while Torch later divides by zero.

Python validation uses explicit `TypeError` and `ValueError`, never `assert`,
so `python -O` cannot erase the contract. Native uses typed raw `py::handle`
readers before `cudaGetDeviceCount`, allocation, or conversion into
`HypersT`. Direct `_C.create_pufferl` callers receive the same protection.

Multi-GPU setup currently divides `total_timesteps` after the initial
high-level validation. The effective per-rank configuration must be
revalidated after that division so a globally positive budget cannot become a
zero-update rank.

## Native implementation

### Stable objective state

Add a one-element `FloatTensor` to `PPOBuffersPuf`. It remains binary32 even
when model precision is BF16, is registered before activation allocation, and
keeps one stable address for the lifetime of `PuffeRL`.

Change `PPOKernelArgs.ent_coef` from a by-value `float` to a
`const float *`. Before each eager loss execution or graph replay:

1. calculate `c_real` from the pre-update epoch;
2. explicitly round it to finite binary32;
3. store it in persistent host-side `PuffeRL` schedule state;
4. issue a checked `cudaMemcpyAsync` to the stable device scalar on the
   selected `train_stream`; and
5. only then enter graph capture, launch the captured graph, or execute the
   eager PPO path.

The update remains outside `cudaStreamBeginCapture`; capturing a by-value
payload would recreate the defect. Persistent host storage avoids an
ambiguous asynchronous-source lifetime.

The PPO kernel dereferences the pointer exactly once into one local
`const float`. That same local value is used for:

- entropy-gradient scaling;
- total-loss construction;
- the direct coefficient accumulator; and
- the direct signed entropy objective term.

Forward loss, backward gradient, and telemetry may not load independent
coefficient values.

### Successful-update commit

The current native trainer increments `epoch` before final stream
synchronization. Move the increment after successful synchronization.

Before any scalar copy, loss, optimizer, or telemetry mutation, the public
binding rejects `epoch >= total_updates`. Construction capture warmup uses the
internal implementation under an explicit warmup state and is not a public
update.

After synchronization succeeds, commit together:

- applied update index `e`;
- completed epoch `e + 1`;
- schedule-update count;
- first/last update indices and coefficients for the log interval.

An asynchronous CUDA failure leaves no successful-update record and does not
advance the epoch. The object is still treated as fatally compromised because
weights and optimizer state are not rolled back; callers may not retry it as
though it were pristine.

### Loss and schedule evidence

Extend the native loss accumulator with values produced from the one
kernel-local coefficient:

```text
entropy_coefficient_applied
entropy_objective_term = -c_applied * raw_entropy
```

Retain raw policy, value, entropy, total, KL, and clip-fraction fields. Expose
the exact number of contributing PPO minibatches rather than hiding it after
averaging.

The native interval telemetry distinguishes:

- `schedule_update_count`;
- `loss_minibatch_count`;
- `first_update_index`;
- `last_update_index`;
- `first_effective_coefficient`;
- `last_effective_coefficient`;
- the mean direct kernel coefficient;
- raw mean entropy;
- mean signed entropy objective term; and
- total-loss decomposition.

No single “current coefficient” is claimed to explain a multi-update
aggregate. If an entropy-weighted recovered coefficient is exposed, its name
states that role and it is emitted only for a finite entropy denominator
bounded away from zero.

Qualification takes one dedicated read-and-clear snapshot immediately after
each update and requires one schedule update and exactly configured `M` loss
minibatches. Production `log()` may retain interval aggregation, but its
semantics are explicit.

### Construction warmup

Initialize the device scalar to the epoch-zero applied base coefficient before
any graph warmup. After graph capture restores weights, optimizer state, and
epoch, also restore:

- the device scalar to epoch zero;
- persistent host coefficient state;
- schedule update/minibatch counts;
- first/last index sentinels;
- coefficient aggregates;
- signed entropy-term state;
- loss/schedule validity; and
- relevant graph/eager qualification counters.

The first real graph update must be accepted as `e = 0`. Tests may not discard
or heuristically ignore warmup samples.

### Native configuration and bindings

Add raw typed readers and checked arithmetic to the native constructor before
CUDA discovery. Export:

```text
entropy_schedule_contract =
    "cosine-update-index-over-total-updates-fp32-v1"
```

from both native and CPU bindings. The CPU marker authenticates the applied
semantic source stack; it is not a claim that CPU executes native CUDA graphs.

Add a bounded, read-only qualification entropy-state surface alongside the
existing all-or-none qualification surfaces. Update
`tests/profile_kernels.cu` for the stable scalar and expanded accumulator.
Where the fixture can execute on CUDA, run the same captured PPO kernel at two
scalar values and verify unchanged policy/value/raw entropy, changed direct
coefficient and entropy term, expected total change, and expected entropy
gradient change.

## Torch implementation

Add a pure helper in `torch_pufferl.py` implementing the named schedule,
validation, binary64 oracle value, and explicit binary32 applied value.

At construction:

- compute exact `total_epochs` without `max(1, ...)`;
- compute the canonical minibatch count;
- reject invalid/zero values;
- store validated base, minimum ratio, and anneal flag; and
- initialize schedule telemetry as having no applied update.

At the beginning of `train()`:

1. reject `epoch >= total_epochs`;
2. set `e = epoch`;
3. compute one binary32 coefficient tensor/value;
4. use that exact value for every minibatch.

Each minibatch accumulates:

```text
entropy_objective_term = -c_applied * entropy
total = policy + vf_coef * value + entropy_objective_term
```

Only after all minibatches, optimizer operations, and telemetry conversions
succeed does Torch advance its epoch and publish the update record. Torch
adopts explicit read-and-clear training interval semantics so evaluation logs
cannot repeatedly expose stale training loss/schedule data as fresh evidence.
Evaluation logs contain no fresh applied-update record.

The Torch gradient verifier neutralizes policy and value gradients exactly.
It observes entropy gradients before clipping through hooks, or proves a
strict non-clipping bound. With identical tensors, actions, masks, selected
minibatches, and RNG state, it verifies:

```text
gradient(c) - gradient(0) = c * independent_entropy_gradient
```

including direction and sign. A custom optimizer rejects nonfinite gradients
and unexpected `step`/`zero_grad` counts. At least one fixture exercises the
real exact-joint-action mask path with positive entropy.

## Patch-stack ownership

Create:

```text
training/puffer_entropy_schedule_parity.patch
```

Its causal position is:

```text
puffer_exact_joint_actions.patch
-> puffer_recurrent_eval_state.patch
-> puffer_rollout_transition_closure.patch
-> puffer_frozen_prio_mask.patch
-> puffer_entropy_schedule_parity.patch
-> puffer_recurrent_cuda_qualification.patch
-> puffer_reward_clamp_range.patch
-> later runtime/state/config patches
-> puffer_strict_environment_config.patch
```

The entropy patch owns production schedule semantics. The qualification patch
is recut on top of it to remove the temporary native constructor guard and add
qualification-only evidence. A later patch may not delete lines introduced by
an earlier patch, because every patch must remain exactly reverse-applicable
after the complete stack is installed.

Avoid a new shared header. The existing 14-entry compiled-source registry
already closes over:

- `pufferlib/pufferl.py`;
- `pufferlib/torch_pufferl.py`;
- `src/bindings.cu`;
- `src/bindings_cpu.cpp`; and
- `src/pufferlib.cu`.

The profile fixture remains bound by the exact entropy patch bytes. Recompute
the compiled digest/header only after all downstream overlapping patches have
been recut.

Update the installer variable, marker checks, ordinary/reverse application,
`--check` mode, final reverse-applicability loop, arm and screen patch bundles,
qualification identities, and experiment contracts in the same causal order.
A fresh complete stack must install twice without a second-run mutation, and
every individual patch must reverse-check against the final tree.

## Qualification schema 11

Entropy parity becomes a mandatory first-class gate, not an assertion hidden
inside the zero-entropy rollout or ratio gates.

Required isolated cells:

1. `native_eager_anneal_enabled`;
2. `native_graph_anneal_enabled`;
3. `native_graph_anneal_disabled`;
4. `torch_anneal_enabled`; and
5. `torch_anneal_disabled`.

An eager-disabled control may be added for complete symmetry. Cell names may
not use ambiguous “graph disabled” wording when they mean graph enabled with
annealing disabled.

Use a closed fp32 configuration with:

- `N = 20`, safely above the graph-capture warmup count;
- one rollout quantum per update;
- one PPO minibatch per update;
- zero learning rate;
- a nonzero base and materially different floor;
- finite exact-action entropy bounded away from zero;
- one fresh rollout/tail record consumed per train call; and
- one read-and-clear snapshot after each update.

Each worker writes raw JSON/NPZ arrays and identities, not pass/fail booleans.
The parent independently reconstructs:

- exact update sequence `0..N-1`;
- real-valued and applied-fp32 schedule trajectories;
- coefficient monotonicity/movement or disabled constancy;
- signed entropy-term identity;
- total-loss identity;
- exact configured minibatch count;
- exact graph/eager capture, handle, and launch-counter deltas;
- unchanged weight bytes under zero learning rate;
- tail consumption and exact global-step progression; and
- module, source, patch, Puffer pin, path, bytes, SHA-256, and nonce identity.

The parent requires pointwise schedule parity across native eager, native
graph, and Torch. It requires each backend's own loss decomposition and
gradient evidence. It does not claim general native/Torch PPO numerical
equivalence. Native eager/graph raw-loss equality is required only if the
implemented deterministic fixture demonstrates that stronger property;
otherwise use declared bounded numerical agreement plus exact schedule,
signed-term, and execution evidence.

Mutation validation must reject:

- a frozen coefficient;
- an epoch shift, duplicate, omission, or reorder;
- denominator `N - 1`;
- linear decay, missing clamp, wrong base/floor, or wrong minimum ratio;
- a disabled control that moves;
- a wrong entropy sign;
- host/device/kernel telemetry disagreement;
- forward/gradient coefficient disagreement;
- zero or nonfinite entropy;
- a wrong minibatch count;
- warmup residue in the first real sample;
- graph cells with missing handles/launches or eager execution;
- eager cells with graph execution;
- an accepted public call at `e = N`;
- a missing/wrong compiled marker;
- entropy patch or source digest drift;
- mislabeled backend/cell identity;
- stale/tampered JSON or NPZ bytes;
- replayed run/cell nonces; and
- worker-authored correctness fields.

Schema 11 remains diagnostic and writes `qualification_only: true`. A locally
constructed or even synthetically accepted receipt is not production
authority.

## Production and lineage boundary

The native constructor's temporary graph-plus-anneal guard is removed while
recutting the qualification patch so the target qualifier can execute the
repaired mechanism.

The literal shell guards in both production launchers remain unconditional in
this tranche. Status becomes a non-authorizing value such as:

```text
implemented_pending_nvidia
```

Plan and dry-run artifacts remain visibly blocked. Immutable manifests bind a
requested schedule descriptor rather than a fabricated scalar effective
coefficient:

- schedule contract;
- telemetry contract;
- base coefficient;
- anneal flag;
- minimum ratio;
- total-update count;
- `N` denominator rule;
- expected first coefficient;
- expected last legal coefficient;
- post-final floor; and
- graph warmup setting.

Actual effective coefficients belong to per-update runtime telemetry.

This tranche may add those fields to the lineage identity required of a future
checkpoint. It may not:

- make a schema-11 receipt consumable by either launcher;
- make `accepted: true` sufficient for execution;
- add a receipt-based bypass of either literal shell guard;
- alter `allow_eligible_publication`;
- publish or promote an eligible checkpoint; or
- turn the pending status into a conditional authorization.

Negative tests supply a synthetically valid same-module schema-11 receipt and
prove it cannot bypass arm/screen guards, satisfy checkpoint eligibility,
create a run artifact, or promote a checkpoint.

A later independently reviewed release-authority tranche may replace the
literal guards with an exact target-receipt gate only after real NVIDIA
evidence exists and the same-host/GPU authority question is resolved.

## Test-first implementation slices

1. Add dependency-light schedule-oracle and raw-input tests:
   - enabled/disabled schedules at negative lookup, zero, middle, `N - 1`,
     `N`, and beyond;
   - `N = 1`, zero base, zero/unit minimum ratio, monotonicity, exact
     post-final floor, and no under-floor values;
   - real-to-fp32 rounding and finite-fp32 rejection;
   - `N` versus `N - 1`;
   - malformed raw values, checked multiplication, per-rank revalidation,
     `python -O`, and direct native constructor behavior;
   - just-below-one and exact-one minibatch boundaries.
2. Add red source/patch-stack tests requiring:
   - the stable device pointer and registered f32 scalar;
   - one kernel-local dereference shared by gradient, total, coefficient, and
     signed-term evidence;
   - checked same-stream copy before capture/replay/eager execution;
   - post-sync epoch commit;
   - complete warmup scalar/telemetry reset;
   - expanded profile fixture;
   - both compiled markers;
   - installer/bundle/provenance ordering and exact reverse applicability;
   - absence of the temporary constructor guard from the recut qualification
     patch; and
   - continued presence of both literal production shell guards.
3. Add the executable Torch verifier against the exact patched source:
   - actual schedule movement over `N = 20`;
   - first/middle/last applied values;
   - within-update constancy;
   - direct signed term and total decomposition;
   - pre-clipping gradient scale/direction against a zero-base oracle;
   - exact-action positive-entropy masks;
   - disabled and zero-base controls;
   - overrun rejection;
   - zero-minibatch rejection; and
   - read-and-clear/stale-evaluation semantics.
4. Extend the CUDA qualifier to schema 11 with the five-cell raw-artifact
   matrix and parent-owned mutation suite.
5. Add launcher, manifest, lineage, and synthetic-receipt non-authorization
   tests.
6. Apply the complete ordered stack to a fresh pinned checkout, install twice,
   build available CPU/Torch surfaces, run executable tests against applied
   source, and reverse-check every patch.

Each watched regression is first demonstrated red against the pre-fix tree.
The red-test state is committed separately before implementation.

## Validation

Local and exact-install validation includes:

```text
PYTHONPATH=tools python3 -m unittest -v <focused suites>
<Puffer venv>/python -m unittest -v <Torch/executable suites>
<Puffer venv>/python training/verify_entropy_schedule_parity.py --device cpu
python3 -m unittest discover -s tools
<Puffer venv>/python -m unittest discover -s training
make test
make asan
python3 -m py_compile <modified Python>
bash -n <modified shell>
ruff check <modified Python>
shellcheck <modified shell>
YAML parse for .github/workflows/ci.yml
git diff --check
fresh exact-pin install twice
git apply --reverse --check --no-index for every installed patch
```

The exact-pin x86 CI job runs the CPU Torch verifier. Local macOS execution is
not represented as x86 CI or NVIDIA evidence.

The target run must later execute the schema-11 fp32 qualifier on NVIDIA.
Until then, native graph parity, target binary behavior, and production
release authority remain explicitly pending.

## Self-review and independent review

After implementation:

1. inspect the complete diff and patch-stack final state;
2. run bughunt in analyze-only mode against schedule, type, stream, epoch,
   telemetry, artifact, and authorization invariants;
3. run simplify in analyze-only mode, preserving deterministic single-path
   behavior and rejecting any silent fallback;
4. obtain an independent adversarial post-implementation review;
5. reproduce every substantiated finding with a failing test where feasible;
6. fix and rerun proportionate validation; and
7. record any unresolved external boundary without softening it.

## Explicitly out of scope

- Removing or bypassing either production launcher guard.
- Running production training.
- Publishing or promoting a checkpoint.
- Push, pull request, merge, or deployment.
- Provisioning paid GPU infrastructure without separate user authority.
- General learning-rate schedule repair.
- Changing the selected conditional-action entropy estimator.
- General native/Torch PPO numerical equivalence.
- BF16 qualification.
- Independent final qualification or predecessor-lineage authority.
- Authored scenarios, curriculum, reward, representation, opponent, profiling,
  or sweep changes.

This tranche is complete locally only when its code, tests, installer,
provenance, and diagnostic qualifier are accepted and committed with all
external boundaries stated accurately. It does not become production-qualified
until the later target-NVIDIA and release-authority tranches succeed.
