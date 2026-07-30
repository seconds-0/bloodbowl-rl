# Entropy-schedule objective parity

Status: implemented and locally validated on the available source, macOS/ARM
CPU, and Torch surfaces, 2026-07-30. The exact-pin x86 CI job has not run, the
schema-11 NVIDIA matrix has not run, and neither production launcher is
unlocked. No production training, checkpoint publication, or launcher unlock
is authorized by this document.

Base: rollout-transition closure commit
`28e053ff6855caaa8d9c6a400412cca80f045155`.

This was the next P0 trainer prerequisite in the environment/trainability
program. The implemented source defines one configured entropy schedule for
native eager, native CUDA-graph, and Torch training, and makes the applied
coefficient observable from the objective rather than merely from host
configuration. Local source and CPU execution validate the shared contract;
only the pending NVIDIA matrix can establish that the compiled native eager
and graph paths execute it correctly on the target backend.

Kimi review was explicitly waived by the user. Independent research review,
adversarial plan review, self-review, and independent post-implementation
review remain mandatory.

## Why this tranche was required

The pre-tranche production configuration combined:

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

The pre-tranche schema-10 CUDA qualifier intentionally set the entropy
coefficient to zero, so it could not see this divergence. The implemented
schema-11 qualifier now defines nonzero enabled and disabled entropy cells and
parent-owned reconstruction, but it has not executed on NVIDIA. The temporary
native constructor guard has been removed so diagnostic qualification can run;
the literal production launcher guards remain unconditional.

PufferLib later corroborated the native defect in upstream commit
`2753605ed53c0ed7b3bcc62d6f269b9158b8cbe2` by moving the native coefficient
to a stable device scalar. That fix is useful design evidence, not a complete
patch for this repository: it leaves Torch constant, uses an unchecked
synchronous copy, provides no compiled contract or direct kernel telemetry,
and tests only inferred aggregate graph losses.

No authored-scenario learning result is admissible until the trainer objective
itself is stable and inspectable.

## Implemented result and local evidence

The implementation adds
`training/puffer_entropy_schedule_parity.patch`, recuts every causally later
overlapping patch, and closes installer, launcher, manifest, qualification,
and CI identities over the new artifact. Both extension bindings export:

```text
entropy_schedule_contract =
    "cosine-update-index-over-total-updates-fp32-v1"
```

The native source now owns a stable device scalar, copies the current
binary32 coefficient on the training stream before eager execution, capture,
or replay, and uses one kernel-local value for the entropy gradient, signed
entropy term, total loss, and direct telemetry. Torch computes the same
schedule once per public update and reuses it for every minibatch. Public
negative-epoch, exhausted-epoch, and zero-minibatch cases reject before the
guarded training transaction. The schema-11 qualifier and parent verifier bind
the schedule, loss decomposition, pre-clipping entropy gradient, graph/eager
execution identity, artifacts, and non-authorization boundary.

Observed local and independent evidence on 2026-07-30:

- Two fresh Git checkouts were detached at exact PufferLib commit
  `9836f0d2e78889c1aaf189c04d161b6fc61a9386`; the primary was a new network
  clone and the independent-review checkout was a fresh local shared clone.
  The primary checkout completed two installer runs and the independent
  checkout completed three.
  Every run, including the post-build state, reproduced the same six installed
  source/contract identities:
  - installed `git diff --binary`:
    `b9e9d2d16816be796fbc9c67bac42f13c83720cb847676f8eaf1f41bfd221984`;
  - installed `git status --short --untracked-files=all`:
    `1d9dd6d5b588e62d5da7456a8329be5c136e4667a84ebb34e7717b149fdbdf2f`;
  - environment:
    `6e018ac5a6b4b5cce0f004480e92d7708f7a06d6e6144ed81ea9b77e10fba015`;
  - complete installed 15-entry compiled-source closure:
    `20934ecd87c9e23fa5943ba903ec15a1c76f22bcda59d486dce1680804264dff`;
  - generated configuration:
    `7ef064026b2d098d42d12c7ca67e1dd5b8ae3c4d584f788c03916a7d6bd08f1e`;
    and
  - generated contract header:
    `774636bd5cd717b98e0925a52a083d5f07b1084a1becee5fd77912a8a434f507`.
  The installed closure is authoritative for a complete installer result. It
  intentionally differs from the narrower selected-11-patch synthetic chain,
  which omits installer-owned changes such as the atomic machine-panel write.
- The final selected artifacts passed 11 causal endpoint-tree reproductions
  and 11 actual final-stack reverse-then-forward cycles, each of which restored
  the exact final tree. An independent reviewer separately authenticated every
  forward and reverse endpoint plus the all-11 reverse-then-forward final-tree
  cycle on the selected synthetic chain; both fresh installed trees passed the
  installer's exact reverse/source-closure check. The entropy and causally
  following qualification artifacts have SHA-256 values
  `7143875f5cc651d5279d6e31b82fdf5fe7034bc804c4a436b88aef457a0e5b33`
  and
  `736d0af8b4a616a21f6afe1b1300b8b0897678b5a57b2acbb49136234a5d5b3b`.
- Both disposable checkouts built a real CPU extension and the Blood Bowl
  standalone on macOS/ARM. The primary build temporarily omitted upstream
  Puffer's x86-only AVX2/FMA flags and restored the exact installed `build.sh`
  before checking drift. The independent build used a compiler shim and did
  not edit `build.sh`. Final installer `--check` runs authenticated environment
  source, generated contracts, compiled CPU module, standalone, and freshness.
- The schema-3 executable Torch objective verifier selected the real patched
  source and real compiled CPU extension (`extension_mode=compiled`), exercised
  five enabled/disabled/zero-base cases with two minibatches each, and passed
  its independent schedule, loss, gradient, clipping, negative/exhausted
  epoch, incomplete-update poisoning, public-callable, telemetry, and identity
  checks. It reproduced both a second-minibatch failure and a post-loop
  publication failure after model/optimizer mutation, then proved that no
  retry or evidence publication could advance state or RNG. Two clean updates
  proved that the pessimistic latch clears only on final successful
  publication. Selected-source import/execute tests also proved restoration of
  SIGINT, `sys.excepthook`, warning filters, and IPython/Jupyter traceback
  hooks after both success and `BaseException`.
- Both compiled verifier runs bound the same installed `pufferl.py`
  (`22bbbe209f5d73a397863b15ecb5e76af0617143bf8bf7158381f560f957526c`)
  and `torch_pufferl.py`
  (`30e36f98951b7c38541156835f83c06e6a8b3b475b65349812313825da36daec`)
  bytes. The primary extension/evidence hashes were
  `020f0e1b57cc809b72ad079576b03246c162c94afe6ebf55d5d7ddd36bef2323`
  and
  `58c92a831172ecc5cc528cd4508928faeee158f34605b974cb400647302a925b`;
  the independent extension/evidence hashes were
  `fb2abc9867589a568743957479eea7e46328665937c10d5e65ce0865b5f713c7`
  and
  `c81b3b2a1c916190f2ff8851a6354b9c5ded27dae2dc5b1acbb99f4f665f4f49`.
  Compiled modules and evidence are run-specific ARM artifacts; their
  different hashes are not represented as a deterministic-build failure or as
  portable release authority.
- The selected exact-source entropy/Torch suite passed 92/92 tests in both
  checkouts. The combined qualification, exact-action, recurrent, and rollout
  suite passed 179/179; the strict selected-source boundary passed 7/7; and the
  compiled rollout-transition verifier passed in both checkouts.
- Five valid strict environment profiles constructed, reset, and closed
  against the real CPU extension; all 44 subprocess-isolated malformed
  profiles rejected before construction. On macOS, this exercised the exact
  construction functions rather than the Linux-only CI entry point, whose
  pinned package metadata is not satisfiable by the local Python/Torch build.
  Tool discovery passed 364 tests with 6 skips. Full training discovery under
  the selected exact root and interpreter passed 309 tests with 1 expected GPU
  skip.
- `make test` passed 476 core, 64 reward, 3 contact-bot, 55 state-bank, 22
  strict-config, 7 binding, and 26 observation tests plus the integration and
  standalone contracts. `make asan` passed the same surface with
  AddressSanitizer/UndefinedBehaviorSanitizer and leak detection disabled for
  the harness. Python compilation, Ruff, Bash syntax, YAML parsing, and
  whitespace validation passed. ShellCheck at warning severity passed; its
  default output contains only four pre-existing info/style findings.

The configured x86 CI job and its evidence upload have not been executed in
this branch. `nvcc` is unavailable on the local host, so none of the native
CUDA compilation, eager execution, graph capture/replay, or target-GPU claims
are locally satisfied.

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
- a pure helper lookup at `e < 0` clamps progress to zero and returns the base
  coefficient;
- a pure helper lookup at `e >= N` clamps to the floor;
- a public training call rejects unless `0 <= e < N`, before objective,
  optimizer, telemetry, tail, or epoch mutation;
- `N = 1` has one legal update at the base coefficient;
- `N <= 0` is rejected before backend construction.

The clamped helper values complete the mathematical schedule and support oracle
inspection. They do not authorize an out-of-range public train call.

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

The canonical minibatch count reproduces the actual runtime rounding sequence:

```text
r = round-to-nearest finite binary32(replay_ratio_real)
q_mul = binary64(binary64(r) * binary64(B))
q = binary64(q_mul / binary64(minibatch_size))
M = floor(q)
```

Both backends must derive the same `M`, and construction requires `M >= 1`.
The implementation closes the pre-tranche mismatch where native could advance
its epoch after doing zero PPO work while Torch later divided by zero.
The verifier performs those binary64 operations rather than substituting exact
rational arithmetic. At an integer boundary, ratio bits `0x3f47ea21`,
`B = 1,386,466,366`, and `minibatch_size = 1,082,714,148` produce runtime
`q == 1.0`, so the required result is `M = 1`.

Python validation uses explicit `TypeError` and `ValueError`, never `assert`,
so `python -O` cannot erase the contract. Native uses typed raw `py::handle`
readers before `cudaGetDeviceCount`, allocation, or conversion into
`HypersT`. Direct `_C.create_pufferl` callers receive the same protection.

Puffer sweep spaces may return NumPy scalar objects even when the conceptual
value is a float or integer. `Hyperparameters._fill` normalizes `np.generic`
results with `.item()` at the producer boundary. The strict public and native
validators remain strict and do not gain a general NumPy-scalar acceptance
path.

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
coefficient values. For bit-exact coefficient telemetry, exactly the global
`idx == 0` PPO row contributes the unscaled binary32 coefficient and every
other row contributes exact zero. The coefficient is never multiplied by
`inv_NT` and reconstructed by reduction.

### Successful-update commit

The pinned native trainer previously incremented `epoch` before final stream
synchronization. The tranche moves the public-update commit after successful
synchronization and treats any exception after public dispatch or during
commit as fatal.

Before any scalar copy, loss, optimizer, or telemetry mutation, the public
binding rejects `epoch < 0 || epoch >= total_updates`. Construction capture
warmup uses the internal implementation under an explicit warmup state and is
not a public update.

After synchronization succeeds, commit together:

- applied update index `e`;
- completed epoch `e + 1`;
- schedule-update count;
- first/last update indices and coefficients for the log interval.

Any failure after dispatch leaves no successful-update record and does not
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
semantics are explicit. Its interval coefficient may be a mean across
minibatches; it is not the bit-exact raw-kernel proof. Schema 11 uses one
minibatch per update and requires each raw `LOSS_ENT_COEF` value to have the
same binary32 bits as `c_applied`, including for irregular `NT = 7`.

Every supported trainer-bound native callable except cleanup shares an
idle-transaction guard. The closed manifest covers log/evaluation log,
render, rollout, evaluation-mode changes, train, save/load, frozen-bank
mutation, agent/environment routing, alignment and environment counts, Python
vector send/receive, uptime, parameter count, and all seven qualification
surfaces. `close()` is the sole callable exception. The guard checks fatal
incomplete-update state first, active no-GIL dispatch second, and pending
schedule evidence third. Fatal state therefore cannot be masked by transient
transaction state or a weaker qualification/domain error, and a racing read is
not represented as a valid empty snapshot.

`PublicEntropyTransaction` is the native commit boundary. Its constructor
performs the retryable batch/epoch preflights and activates deferred
publication. Dispatch is marked immediately before the internal trainer can
copy the schedule scalar, launch PPO work, or mutate optimizer state. Its
destructor clears deferred/pending evidence; if stack unwinding began after
dispatch, it also permanently poisons the object. `complete()` publishes the
pending entropy record only after the train path has synchronized
successfully. A commit exception performs the same poison-and-clear sequence
before rethrowing. All trainer-bound callables in the manifest check this
state before domain validation, file I/O, environment work, CUDA work, state
mutation, or publication, so an incomplete update cannot be masked by a
secondary error or represented as retryable evidence.

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
gradient change. The fixture includes an irregular `NT = 7` case and rejects a
raw coefficient that is not bit-identical to the requested binary32 scalar.
This CUDA fixture is implemented but remains unexecuted locally because
`nvcc` and NVIDIA hardware are unavailable.

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

1. reject an already poisoned object;
2. complete the retryable mode, epoch-range, and tail-record preflights
   (zero minibatches are rejected earlier during construction);
3. pessimistically arm the incomplete-update latch before RNG consumption,
   optimizer work, or other stateful training work;
4. set `e = epoch`;
5. compute one binary32 coefficient tensor/value; and
6. use that exact value for every minibatch.

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

Any `BaseException` after the latch is armed leaves the Torch object
permanently poisoned because weights, optimizer state, and RNG are not rolled
back. The latch clears only as the final action after a completely successful
update publication. Subsequent uptime/SPS/parameter queries, qualification
enable/read, evaluation-mode changes, train, rollout, log/evaluation log,
save/load, and render calls reject before clock access, validation, file or
environment work, mutation, or publication. `close()` remains available for
cleanup after the failed `train()` call has fully unwound, and loading weights
does not pretend to restore optimizer/RNG consistency. Errors from the
retryable preflights above do not poison the object.

Neither backend attempts in-process recovery. In distributed execution, one
rank's incomplete update requires termination and reconstruction of the whole
training job/process group from a trusted checkpoint; this contract does not
claim collective failure recovery.

The recovery boundary is deliberately a callable, single-threaded trainer
contract—not a claim that every Python-visible byte becomes inaccessible.
Construction, class factories, stateless helpers, and direct mutable
attributes are outside it. Torch preserves the normal public method name,
qualified name, module, and exact signature, and intentionally publishes no
standard `__wrapped__` alias; the executable verifier also proves that a
poisoned evaluation-mode call rejects before invoking the raw method's
`bool(enabled)` conversion. Deliberate closure/code/global reflection,
class monkeypatching, and manual latch mutation are outside the isolation
boundary because the caller already has arbitrary Python mutation authority.
Native `set_evaluation_mode` may have its typed secondary argument converted
by pybind before C++ body entry. After successful pybind argument binding, the
trainer cast is immediately followed by the fatal guard, which precedes raw
delegation and every trainer-state, CUDA, environment, and I/O action. Python
arity errors and other pybind conversion failures that occur before the
guarded body are therefore outside the guarantee; domain-invalid values that
reach the body, such as `max_bytes=0`, remain fatal-first. No trainer method,
including `close()`, is supported concurrently with `train()`. Cleanup is the
only callable escape after a fully unwound failure, and cleanup does not clear
or rehabilitate the fatal latch.

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

## Gradient and optimizer proof boundary

The schema-11 gradient evidence contract is:

```text
ppo-entropy-preclip-gradient-v1
```

Its native proof ends at the raw PPO pre-clipping logits gradient. It proves
that the coefficient observed by the objective produces the independently
expected entropy-gradient delta before clipping. It does **not** prove:

- native `policy_backward` parameter gradients;
- native gradient clipping;
- Muon optimizer arithmetic or state transitions;
- changed native policy parameters; or
- native/Torch optimizer-update equivalence.

The native qualification cells intentionally use zero learning rate.
Unchanged before/after weight bytes therefore prove that the diagnostic did
not mutate weights; they are not optimizer-correctness or learning evidence.

The standalone CPU Torch verifier exercises the selected Torch
`PuffeRL.train` path through `loss.backward()`, Torch's real
`clip_grad_norm_`, and the subsequent optimizer `step` call. Its recording
optimizer deliberately has learning rate zero and does not update parameters.
A separate active-clipping control proves that the step observes the clipped
gradient rather than the raw gradient. This establishes within-Torch
backward/clip/step ordering and gradient scale; it does not establish
cross-backend parameter-gradient or optimizer parity.

The verifier isolates import-time process-global changes from the selected
source. On success and on `BaseException`, it restores SIGINT,
`sys.excepthook`, warning filters, and IPython/Jupyter traceback hooks,
including deleting hook attributes that were originally absent and tolerating
a broken `get_ipython`.

Schema 11 shares genuinely measured schedule, loss, entropy, and gradient
arrays across backends. The six graph/eager execution counters are measured
native-only surfaces: native cells must emit them, and Torch cells must omit
them. Torch evidence does not synthesize zero-valued native counters.

Accordingly, “entropy parity” in this tranche means parity of the named
schedule, applied binary32 coefficient, signed entropy objective term, and
pre-clipping entropy-gradient contract. It is deliberately narrower than
general PPO, clipping, optimizer, or weight-update parity.

## Patch-stack ownership

Implemented artifact:

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
-> pufferl_scripted_training_guard.patch
-> pufferl_warm_start.patch
-> puffer_state_bank_contract.patch
-> puffer_strict_environment_config.patch
```

The authenticated selected-artifact ledger for that exact order is:

| Artifact | SHA-256 |
|---|---|
| `puffer_exact_joint_actions.patch` | `7160f385da586c67d678497d0a1f4bb6ff594d5d2a96f48bebae155c08b427d6` |
| `puffer_recurrent_eval_state.patch` | `b38acd14d455fd48aaa11ce62974ec48c2f512d60bd6bc690f41e0f9a60b6fb7` |
| `puffer_rollout_transition_closure.patch` | `c73dc50ad4b027ff2475065e78a188228e58dd9dd78639edbc36a2dbe85305c7` |
| `puffer_frozen_prio_mask.patch` | `8513747720a32e888942b5d224090a8c87a4ce62abd7a7ac78702bd31955460d` |
| `puffer_entropy_schedule_parity.patch` | `7143875f5cc651d5279d6e31b82fdf5fe7034bc804c4a436b88aef457a0e5b33` |
| `puffer_recurrent_cuda_qualification.patch` | `736d0af8b4a616a21f6afe1b1300b8b0897678b5a57b2acbb49136234a5d5b3b` |
| `puffer_reward_clamp_range.patch` | `c6517778fda72b71091995c51a260cffcbd54e68ae12f0184910e3102e52cd6a` |
| `pufferl_scripted_training_guard.patch` | `cecca6f7f495e65d2b126ed525a2275f6a283ddb9daacfde523c85b63a54c826` |
| `pufferl_warm_start.patch` | `696a577224891010bd12f90d6b3a811a39eaa1ff4026ff841a789ef51a570176` |
| `puffer_state_bank_contract.patch` | `61c8f56a08fd7b54206b3310bcd0613329af6eb329e2d5e9fa1ed694fc29f69c` |
| `puffer_strict_environment_config.patch` | `a75bf6b57a1d6d2e50af0cd89adc9f40d9c54deb7b880d21925d3287593d7679` |

The corresponding patch-only endpoint chain was committed solely to
authenticate causal application and exact trees:

| Endpoint | Commit | Tree |
|---|---|---|
| selected-stack base | `79d9ccb2a535fdf844a92eab01115ae7f2be5a05` | `10f7c3261c0db426fdcf971027dff635497e191d` |
| exact actions | `49e1a34533dc6a377562a1bcf8f73d8084709965` | `d706afc86735018f744bde746a90171e4e699c82` |
| recurrent state | `a8193a692c449d3d6d702201d6a93e94db1a93ad` | `ea75639ed2f41044c29346f8ba2c62488d8df9b9` |
| rollout closure | `3421618b79d31ff9ea33221ff14e85d95c24ca09` | `6e569078b156b8549c1cf972d19ff85b242c5ca3` |
| frozen priority | `567c0f757c9a9773b7cba0eedb65cd3e5b62244c` | `5f691092c0fffe4d39f8296d5bc7cb1aa4f47795` |
| entropy parity | `fbeb1629b7c714b282a23ee7e1e6080f306925de` | `b845961f2f9dacc083263c2f95b24c781ea91a70` |
| qualification | `034ac5a8294ee3b83f10ed809d6d2bacf9e274fa` | `36d3b655c0e8b328f56c263b6d8a267051cf2d0c` |
| reward clamp | `7ae48adc74d081be919216b09b651233e64be3ee` | `b2625b6ba44137e55e56721c1d4d69d70958bb31` |
| scripted guard | `7c325a0dba500de99cf73f464c7a4d8d293d3e03` | `96eef2a21a22fccbef378e52ef6884caf369a8d3` |
| warm start | `860818c12fa991aaee97a2558442a4949e3a74b8` | `314fcdb4966c8dbfb3e3a3d4f861decaeb2b5587` |
| state bank | `3e26b2b8fb57041e8e09d9d27deea50661b95d37` | `fd931d98ce0f6a29455fc6b9a6ea9c959d81594c` |
| final strict | `b88913cc42f3ea6199cfc6e45185879a68833ad6` | `9d5ecb2b45eee947c9a2bf035f091ef45cc1880d` |

This chain is authoritative for the selected 11 patch artifacts and their
overlap seams. The complete installed closure and identities in the evidence
section are separately authoritative for installer-owned changes outside this
patch-only chain.

The entropy patch owns production schedule semantics. The qualification patch
is recut on top of it to remove the temporary native constructor guard and add
qualification-only evidence. A later patch may not delete lines introduced by
an earlier patch in this causal trainer/binding set, because each selected
patch must remain exactly reverse-applicable after the complete stack is
installed.

Avoid a new shared header. The existing 15-entry compiled-source registry
closes over `build.sh`; four selected Python paths (`pufferlib/pufferl.py`,
`pufferlib/selfplay.py`, `pufferlib/sweep.py`, and
`pufferlib/torch_pufferl.py`); and the complete ten-file native quoted-include
closure, including `src/bindings.cu`, `src/bindings_cpu.cpp`, and
`src/pufferlib.cu`.

The profile fixture remains bound by the exact entropy patch bytes. Recompute
the compiled digest/header only after all downstream overlapping patches have
been recut.

Update the installer variable, marker checks, ordinary/reverse application,
`--check` mode, final reverse-applicability loop, arm and screen patch bundles,
qualification identities, and experiment contracts in the same causal order.
A fresh complete stack must install twice without a second-run mutation, and
the selected exact causal/overlap patch set must reverse-check against the final
tree.

## Qualification schema 11

Entropy parity becomes a mandatory first-class gate, not an assertion hidden
inside the zero-entropy rollout or ratio gates.

Five primary schedule-role artifacts are required:

1. `entropy_native_eager_annealed`;
2. `entropy_native_graph_annealed`;
3. `entropy_native_graph_anneal_disabled`;
4. `entropy_torch_annealed`; and
5. `entropy_torch_anneal_disabled`.

The sixth raw artifact, `entropy_native_eager_anneal_disabled`, is also
mandatory as the native-eager disabled-schedule and entropy-gradient control;
it is not an optional symmetry cell. Names distinguish graph execution with
annealing disabled from graph execution itself being disabled.

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
- exact native graph/eager capture, handle, and measured launch-counter
  deltas, while Torch cells contain no fabricated native counter fields;
- unchanged weight bytes under zero learning rate;
- tail consumption and exact global-step progression; and
- module, source, patch, Puffer pin, path, bytes, SHA-256, and nonce identity.

The parent requires pointwise schedule parity across native eager, native
graph, and Torch. It requires each backend's own loss decomposition and
gradient evidence. “Parity” here means the named binary32 schedule,
coefficient use, signed entropy term, and pre-clipping entropy-gradient
contract. It does not claim that native and Torch parameter gradients,
clipping, optimizer state, parameter updates, or general PPO numerics are
equivalent. Native eager/graph raw-loss equality is required only if the
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
- an implementation that accepts either `e = -1` or `e = N`;
- an upper-bound-only Torch public guard;
- a missing/wrong compiled marker;
- entropy patch or source digest drift;
- mislabeled backend/cell identity;
- stale/tampered JSON or NPZ bytes;
- replayed run/cell nonces; and
- worker-authored correctness fields.

Schema 11 remains diagnostic and writes `qualification_only: true`. A locally
constructed or even synthetically accepted receipt is not production
authority.

The standalone CPU Torch verifier proves both Torch public bounds without
mutation. Native source-contract tests require both guards locally. The
configured future target-NVIDIA matrix includes an overrun cell intended to
dynamically prove the native `e = N` boundary, but no schema-11 NVIDIA artifact
has been produced yet. This document does not imply a separate negative-epoch
GPU artifact.

## Production and lineage boundary

The native constructor's temporary graph-plus-anneal guard is removed while
recutting the qualification patch so the target qualifier can execute the
repaired mechanism.

The literal shell guards in both production launchers remain unconditional in
this tranche. Status becomes a non-authorizing value such as:

```text
implemented_pending_nvidia
```

Neither successful local CPU evidence nor the presence of schema-11 validator
code may be interpreted as satisfying those guards.

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

Slices 1–5 and the locally executable portions of slice 6 are implemented.
The list below is retained as the accepted construction record. Remote x86 CI
and target-NVIDIA execution remain open validation steps.

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
   - negative-epoch and exhaustion rejection before mutation;
   - zero-minibatch rejection; and
   - read-and-clear/stale-evaluation semantics.
4. Extend the CUDA qualifier to schema 11 with a six-artifact matrix: five
   primary schedule-role cells plus mandatory
   `entropy_native_eager_anneal_disabled` gradient control, with a
   parent-owned mutation suite.
5. Add launcher, manifest, lineage, and synthetic-receipt non-authorization
   tests.
6. Apply the complete ordered stack to a fresh pinned checkout, install twice,
   build available CPU/Torch surfaces, run executable tests against applied
   source, and reverse-check every patch in the selected 11-patch causal and
   overlap audit set. Legacy overlapping artifacts outside that selected set
   are not claimed to be independently reversible from the final tree.

The originally planned regressions were demonstrated red against the pre-fix
tree and committed separately before implementation. Later adversarial review
found incomplete-update and fatal-first defects; each was reproduced red
before repair, but those late regression tests were not separately committed.

## Validation

Local and exact-install validation includes:

```text
PYTHONPATH=tools python3 -m unittest -v <focused suites>
<Puffer venv>/python -m unittest -v <Torch/executable suites>
<Puffer venv>/python training/verify_torch_entropy_objective.py \
    --puffer-root <Puffer root>
python3 -m unittest discover -s tools
<Puffer venv>/python -m unittest discover -s training
make test
ASAN_OPTIONS=detect_leaks=0 make asan
python3 -m py_compile <modified Python>
bash -n <modified shell>
ruff check <modified Python>
shellcheck <modified shell>
YAML parse for .github/workflows/ci.yml
git diff --check
fresh exact-pin install twice
11 causal endpoint-tree checks plus 11 final-stack reverse/forward tree checks
```

The workflow is configured so the exact-pin x86 CI job builds the selected CPU
surface and runs the three selected-source entropy/Torch modules plus the
direct CPU Torch verifier. No successful x86 CI execution from this local
branch is claimed yet. Local macOS execution is not represented as x86 CI or
NVIDIA evidence.

The target run must later execute the complete schema-11 fp32 qualifier on
NVIDIA. Until then, native eager execution, native CUDA-graph capture/replay,
target compiled-binary behavior, native/Torch pre-clipping qualification on
the target, and production release authority remain explicitly pending.

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
- Authored scenarios, curriculum, reward, representation, opponent, or
  profiling changes.
- General sweep search-space, parameter-range, or optimization-strategy
  changes. Producer-boundary scalar normalization needed to preserve the
  existing strict configuration contract is part of this tranche.

This tranche is complete locally only when its code, tests, installer,
provenance, and diagnostic qualifier are accepted and committed with all
external boundaries stated accurately. It does not become production-qualified
until the later target-NVIDIA and release-authority tranches succeed.
