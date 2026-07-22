# Recurrent CUDA qualification

Status: D225 same-process CUDA initialization correction, 2026-07-22. This plan does not
authorize a trainer launch, checkpoint promotion, or reuse of any qualification
output as training ancestry.

The throughput predecessor remains exact commit
`afc8008933548438ca93c41341f5f08fdd294386`. The control runner and candidate
must use the same newly merged D225 commit in separate clean checkouts.

The D224-era `predecessor-throughput-v2` and
`predecessor-throughput-v3` identities both rejected at native construction
before a transition or timed rollout. They are closed evidence, not retry
targets, and no third capture is permitted under their process initialization
contract. A new timed identity is allowed only after D225 is merged and a
construction-only target integration accepts in a fresh process.

## Purpose

The recurrent evaluation repair is source-verified but its decisive guarantees
depend on the real CUDA runtime. Before a repaired backend can receive even a
disposable training budget, one executable gate must prove those guarantees on
the target GPU and emit an immutable, machine-readable verdict. A missing,
malformed, non-finite, incomplete, drifted, or nonzero hard-integrity result is
a failure. There is no tolerated invalid-transition rate.

## Small native evidence surface

Add an explicit frozen-row priority mask after the exact-action and recurrent
patches, then add one qualification-only evidence patch.
It exposes two bounded operations and no alternate action or reward path:

1. `qualification_recurrent_state(pufferl, clear=False)` synchronizes and reports every
   primary and frozen bank/buffer by element count, nonzero count, non-finite
   count, and maximum absolute value. `clear=True` first uses the production
   zero operation on every state tensor; this is the paired terminal-reset
   control and must be reported explicitly.
2. `qualification_snapshot(pufferl)` copies only a size-bounded qualification rollout's
   observations, actions, values, log probabilities, terminals, and effective
   action masks, current decoder output, PPO's most recent recomputed ratio
   tensor, and selected source-row indices to raw byte arrays with explicit
   dtype/shape metadata. It rejects oversized snapshots rather than risking an
   unbounded host allocation. The ratio runner uses a disposable
   `learning_rate=0` object, hashes saved weights before and after the real train
   call, and requires byte-identical weights. Momentum mutation is irrelevant
   because the object is immediately destroyed.

Both patches are part of the installed backend hash and compiled-module identity.
The priority normalizer assigns exactly zero probability to every frozen-bank
row even when `prio_alpha=0` (where zero advantage alone would otherwise produce
`0^0 == 1`), and computes importance weights over the eligible learner population.
The installer must fail if any surface is absent. None of these functions is
called by ordinary training, evaluation, match, or BBTV paths.

## Executable checks

The runner launches isolated subprocesses so allocator state, graph capture,
environment state, and RNG state cannot leak between cells. Every cell records
the imported module path and SHA-256, compiled backend/environment identities,
observation/action ABIs, effective configuration, seed, precision, elapsed
time, and output hashes.
Schema 3 records backend identity on two axes. The role-correct
`backend_sources_sha256` reproduces the source registry that generated the
native module's compiled attribute: the immutable predecessor's historical
registry omits `pufferlib/selfplay.py`, while the candidate's current registry
includes it. Independently, `runtime_sources_sha256` always hashes the complete
current runtime closure, including `selfplay.py`, for both roles. Both are
mandatory and recomputed from disk on every validation. This authenticates the
historical module without creating a runtime drift exemption. Each cell also
uses `tools/puffer_cuda_runtime.py` as a mandatory same-process boundary before
importing `pufferlib._C`. The boundary loads and retains the exact resolved
`libcudart.so.12`, requires `cudaGetDeviceCount` to return `cudaSuccess` with
a positive count before import, repeats the call after import, and requires the
unchanged positive count. It records the resolved library path and SHA-256,
both calls, and `CUDA_VISIBLE_DEVICES`. Validation requires this evidence in
every cell; predecessor and candidate throughput must use the same library hash
and device count. A probe in another process is not initialization evidence for
the worker. The actual Puffer trainer enters through the same source-controlled
wrapper before importing the ordinary CLI, so qualification and training
cannot silently use different CUDA bring-up semantics. Failed processes
terminate and are not repaired or reused.
Before any behavioral cell, the operator must freeze and pass the clean control-
runner commit; the clean candidate source root and commit; and the candidate
module, backend-source, and environment SHA-256 values. The candidate Puffer
tree must be the vendored tree inside that exact source checkout, and that
checkout's own installer drift check must accept it.
The executable freezes the predecessor and candidate roles to the full commits
named below; operator-supplied alternatives or swapped roles fail. It rejects
the protected recovery root, requires the control-runner, predecessor, and
candidate checkout roots to be pairwise distinct, and keeps outputs outside
each source checkout.
The runner compares those declared values to independently observed files and
compiled attributes; a self-consistent but unexpected build is therefore not
accepted. Qualification is fp32-only: BF16 storage rounds the behavior log
probability before PPO recomputation, so an unchanged policy cannot satisfy a
strict near-unity ratio gate without a separately designed quantization-aware
contract.

### 1. Construction state

Construct a graph-enabled backend with a primary policy and at least one frozen
bank. Immediately require every bank/buffer to have:

- the expected positive element count;
- zero non-finite elements;
- zero nonzero elements; and
- `max_abs == 0.0`.

This directly catches graph-warmup state contamination in either primary or
frozen storage.

### 2. Graph-on/off first-rollout parity

Run graph-enabled and graph-disabled subprocesses with identical module,
configuration, weights, environment seed, and policy seed. Compare the complete
bounded first-rollout snapshot. Discrete observations, actions, terminals, and
effective masks must be exactly equal. Values and log probabilities must be
finite and equal within a declared precision-specific absolute tolerance. Any
shape, dtype, key, identity, or provenance mismatch fails. Decoder comparisons
contain exactly the recorded active prefix for each bank; inactive primary
allocation rows are reported separately and never enter parity comparisons.

### 3. First-post-terminal reset parity

Use `max_decisions=1` and `horizon=1`, enter persistent evaluation mode, and run
two same-seed subprocesses:

- automatic cell: rollout 1, verify every active primary/frozen state is
  nonzero, then rollout 2;
- control cell: rollout 1, verify nonzero state, clear every state through
   `qualification_recurrent_state(clear=True)`, verify exact zero, then rollout 2.

The first action ends each game, so rollout 2 consumes terminal flags alongside
the next games' initial observations. The automatic cell exercises the
unconditionally captured production terminal reset; the control has the same
environment and sampling RNG but arrives with explicitly zero state. Require
the complete rollout-2 snapshots to match under the same rules as graph parity,
and require terminal `1` for every row. Include both primary and frozen rows.

### 4. Zero-update rollout/recompute ratio

On a disposable graph-enabled backend, collect an ordinary training rollout,
save the weights, and execute the real PPO train path with learning rate zero.
After each call, collect PPO's selected indices and recomputed ratios. Aggregate
deterministic calls until every primary source row is covered or a frozen call
limit is reached. Require:

- every ratio element is finite;
- `abs(ratio - 1)` is within the declared strict tolerance;
- every primary rollout row is covered at least once;
- no frozen row is selected;
- saved weights before and after are byte-identical; and
- the attempt/count/coverage contract exactly matches the report.

Priority replay samples with replacement, so a single minibatch is not an
exhaustive proof. The explicit selected indices and deterministic bounded loop
turn that limitation into a fail-closed coverage gate.

### 5. Throughput

Measure a frozen number of warmup and timed rollouts in fresh graph-enabled
subprocesses using the target production shape. Compare decisions per second to
an immutable report from the immediately preceding exact-action backend on the
same idle host and configuration. The production graph boundary is exact:
every graph-enabled cell uses `cudagraphs=10`, matching the frozen
Puffer/canary default, while only the explicit graph-off parity cell may use
`-1`. Zero is not a boolean false value; it captures the first execution before
CUDA library lazy initialization and is rejected before backend load. The
predecessor is accepted only through the
exact hashed `preceding_exact_action_throughput_baseline` wrapper and its confined,
hashed cell record. Its clean source root and commit plus
module/backend/runtime/environment hashes must be predeclared
when captured and again when consumed; arbitrary throughput JSON or an
unplanned old exact-action binary is invalid. Require matching
the control-runner commit/hash and rehash the predecessor module binary on every
consumption/validation, in addition to rerunning its source-local installer
check. Also require matching
host/GPU/config/precision and obs-v5/exact-joint/environment identity, zero
values across the complete 16-key control hard-integrity registry in every
transition-executing cell. The construction cell performs no transition and is
therefore the sole telemetry exemption. Require no more than the predeclared material
regression fraction. Graph-disabled execution is already exercised by the
mandatory correctness-parity cell; it is not a substitute for the
preceding-backend throughput control.

## Output and verdict

Write cell artifacts first, then one atomic `QUALIFICATION.json` containing all
input/output hashes and a top-level `accepted` boolean. Acceptance is the AND of
all mandatory checks. The validator independently recomputes every digest and
numeric predicate from the cell artifacts; it never trusts the boolean alone.
On any exception, timeout, signal, missing cell, drift, or failed predicate,
write a nonzero failure record if possible and exit nonzero.

Qualification checkpoints and mutated optimizer state are disposable. The
qualification directory must contain a literal `qualification_only: true` and
must be rejected by checkpoint-lineage admission.

The merged control checkout must fail closed if asked to launch the
`exact-action-canary`. The sole
`a52fc6e2f4ece5a7ff16bb4791e3aca4dd72f2e3` attempt and all of its authorities
are permanently rejected. No current checkout is authorized to launch a
replacement; only a separate reviewed post-qualification change may name its
exact commit, registry, manifest, unit, and one-shot authority.

## Target execution order

The occupied recovery runtime is not the throughput predecessor. It predates
obs-v5/exact-joint execution, emits nonzero repaired-action telemetry, and its
run manifest does not record the required observation/action ABI. Preserve it
as historical experiment evidence, but never pass its module hash to
`capture-throughput`.

1. The post-recovery predecessor is already built in its isolated checkout and
   its own pinned Puffer tree at exact commit
   `afc8008933548438ca93c41341f5f08fdd294386`. Revalidate that existing fp32
   build and use it read-only: it must report obs-v5,
   exact-joint-v1, matching compiled backend/environment hashes, the frozen
   complete runtime digest, and no qualification surface. D225 does not
   authorize reinstalling or rebuilding it. If the existing tree is absent or
   drifted, stop for a separate reviewed reconstruction plan.
2. In a separate clean candidate checkout at the same newly merged D225 commit
   as the clean control runner, install the full candidate patch stack into
   that checkout's own `vendor/PufferLib`, rebuild in fp32, and run that
   commit's installer drift check. The candidate Puffer tree is explicitly
   different from the predecessor tree and the control-runner tree.
3. Before any throughput timing, run one bounded construction-only integration
   against the fresh candidate entry path on the target. It must record an
   accepted pre-import probe, successful native import, accepted post-import
   probe, exact CUDART path/hash, positive unchanged device count, and
   successful backend construction. It executes no transition and creates no
   throughput or scientific result. Close and hash the two-file output, then
   run `validate-construction` twice from fresh processes in the unchanged
   control checkout. Failure closes that identity; do not repair the process
   or proceed to timing.
   The executable contract also requires this exact gate path/hash in both
   `capture-throughput` and full `run`; each revalidates it before output or
   worker dispatch, and the baseline/final artifacts bind the same reference.
   The predecessor capture also passes the complete frozen predecessor
   declaration into the timed worker. That same process validates its imported
   module, compiled backend, complete runtime sources, environment, ABI,
   precision, role, and Puffer root before backend construction, warmup, or a
   rollout; the parent repeats the identity check after the worker returns.
4. Use a third clean control-runner checkout at the merged commit containing
   this lineage contract. Freeze its commit and runner hash. From that checkout,
   run `capture-throughput` against only the isolated predecessor tree, passing
   `--predecessor-source-root`, full
   `--expected-predecessor-source-commit`, both predecessor module/backend
   digests, the independently frozen complete predecessor runtime digest, and
   `--expected-environment-sha256`. Keep the output outside all
   source checkouts. Do not modify or reuse the recovery Puffer tree.
   The first schema-3 attempt failed before timing because its runner compared
   the historical compiled attribute to the expanded runtime registry. Preserve
   that rejected empty output and use an entirely new output directory after
   the D225 correction; never retry or overwrite v2 or v3.
5. From the same unchanged control-runner checkout, run
   `qualify_recurrent_cuda.py run` against only the candidate Puffer tree. Pass
   `--candidate-source-root`, full `--expected-source-commit`, the baseline,
   all candidate hashes, and the full predecessor source/module/backend/runtime
   expectations. Independently pass `--predecessor-source-root`; it must be
   the exact same root revalidated from the baseline artifact and is protected
   from success and failure output before baseline validation begins. Output
   must be a new external directory.
6. Run `qualify_recurrent_cuda.py validate <QUALIFICATION.json>` from that same
   unchanged control-runner checkout. The validator rechecks both source roots,
   both commits, both source-local Puffer paths, both installer checks, every
   runtime hash, and the runner commit/hash.
   Only that independently recomputed accepted verdict authorizes the separate
   disposable 50M canary.

## Test-first order

1. Add pure runner-validator tests for exact/float snapshot comparison, state
   coverage, terminal coverage, ratio coverage, weight identity, throughput
   provenance, malformed/non-finite inputs, and atomic all-gates acceptance.
2. Add source-contract tests for both bindings, bounded copies, installer
   ordering/identity, and ordinary-path non-use.
3. Implement the frozen-row priority mask, qualification patch, and exact
   reverse-applicability installer checks so marker-only stale patches fail.
4. Implement the subprocess runner and independent artifact validator.
5. Apply the exact-action, recurrent-state, frozen-priority, and qualification
   patches to a fresh pinned Puffer tree; compile and run the
   CPU/source suites locally.
6. After the immutable live boundary only, build in a fresh isolated checkout
   on the RTX 2070, capture the preceding-backend throughput control, and run
   this qualification. Do not start the 50M canary unless every gate passes.

## Explicitly out of scope

- changing rewards, observations, action support, rules, optimizer settings,
  or the active recovery run;
- deploying, rebuilding, or restarting the current trainer or BBTV;
- exposing arbitrary device pointers or mutation of weights, observations,
  environment state, actions, terminals, or RNG state;
- treating source-marker tests as CUDA evidence;
- accepting sampled-only PPO ratios without explicit complete row coverage; or
- using qualification output as a warm start, scientific result, or promotion
  input.
