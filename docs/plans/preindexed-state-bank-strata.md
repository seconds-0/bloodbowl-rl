# Exact preindexed state-bank strata

Status: implemented and validated 2026-07-27; adversarially approved, watched
red captured before implementation, and two independent post-implementation
reviews closed with no residual P0/P1/P2 findings

Base: `7bc96f1`

## Objective

Replace the retired 256-attempt selector loops and the temporary
nonzero-selector bridge with one exact, immutable selector index built from the
already verified state-bank candidate.

Before the first banked reset can return an observation:

- every record has been classified under the four historical selector
  predicates;
- every canonical threshold has an exact eligible prefix;
- the requested selector family and threshold are within a closed bound;
- at most one selector is active;
- the requested eligible prefix is present and nonempty; and
- the selected record is drawn uniformly from that prefix and is rechecked
  against the requested predicate before it is copied.

There is no retry loop and no fallback to another tier or to procedural
generation after the probability draw chooses a banked reset.

The exact selector population is identified by the tuple:

```text
strata predicate schema
+ compiled environment source identity
+ pinned BBS SHA-256
+ canonical selector family
+ canonical threshold
+ exact eligible count
+ ordered-record-index SHA-256
```

The exact selected record is identified by the pinned BBS SHA-256 plus its
zero-based BBS record index. The retained source ID and command metadata are
reported separately.

## Confirmed current gap

The typed state-bank tranche intentionally stops every nonzero selector:

- `bbe_state_bank_validate_config_values()` accepts integer selector values up
  to `INT_MAX`, then returns `BBE_SB_CONFIG_SELECTOR_BRIDGE`;
- `bbe_reset_match()` can draw only from all published records;
- the candidate owns matches and record metadata but no selector indices;
- checkpoint lineage rejects every active nonzero selector;
- the primary launcher rejects selectors before installed-contract
  validation;
- the historical ladder wrappers stop at the temporary bridge; and
- telemetry exposes only banked-episode and legacy-fallback counts.

The implementation immediately before the typed tranche used four
rejection-sampling loops. Each loop retried at most 256 times and then used the
last random record even when it did not satisfy the predicate. That could make
the dashboard claim the requested curriculum was active while training on a
different start distribution.

## Scope

In scope:

- exact historical predicate semantics, expressed once in C;
- a literal `bloodbowl-legacy-state-bank-strata-v1` predicate schema;
- closed selector bounds and mutual exclusion at raw-double, stored-env,
  launcher, and checkpoint-lineage boundaries;
- one stable, process-global, immutable index for every family and threshold;
- all-or-nothing index construction inside the candidate transaction;
- exact uniform sampling from a requested eligible vector;
- hard startup failure for an absent, corrupt, or empty requested stratum;
- selected-record predicate revalidation at reset;
- selector, threshold, eligible-count, BBS-record-index, and source-metadata
  telemetry;
- exact ordered-population digests and a bounded typed selection-audit surface;
- generated-header integration fixtures containing qualifying and
  nonqualifying records;
- an immutable environment-source snapshot proving that the validator's
  predicate bytes equal the generated header and installed module identity;
- exact installation and reverse-verification of Puffer's release-build
  dictionary-capacity abort before adding log keys;
- primary typed launcher and lineage support for valid selectors;
- updated configuration and environment-development documentation;
- optimized, sanitizer, deterministic, clean-install, CPU-module, and
  standalone validation.

Out of scope:

- enabling any production producer kind; the production allowlist stays the
  literal empty set;
- promoting the historical D191 strict artifact or the authored proof bundle;
- adding an index sidecar or changing BBS1 bytes;
- adding new scenario labels, selector weights, schedules, or mixtures;
- allowing more than one selector in one environment;
- changing `demo_reset_pct` semantics;
- changing observations, action support, rewards, terminals, BBP, model, or
  checkpoint bytes;
- reviving the stale historical ladder wrapper recipes as production launch
  authority;
- launching training;
- paired-side evaluation or broad validation of unrelated kwargs; those are
  subsequent reviewed items.

## Canonical selector contract

Selector zero means uniform sampling over every verified bank record. A
positive value activates exactly one of the following families.

### 1. `endzone-maxdist`

Configuration field: `demo_endzone_maxdist`

Closed range: `0..BB_PITCH_LEN-1` (`0..25` in the current engine).

For a record to have a finite metric:

- the ball is held;
- the carrier index is valid;
- the carrier is on the pitch and standing.

The metric is:

```text
abs(carrier.x - bb_endzone_x(carrier_team))
```

A record is eligible at threshold `t` exactly when its metric is at most `t`.
The carrier need not belong to the active team; this preserves the historical
backplay predicate.

### 2. `pickup-maxdist`

Configuration field: `demo_pickup_maxdist`

Closed range: `0..BB_PITCH_LEN-1` (`0..25`).

For a record to have a finite metric:

- the ball is on the ground; and
- at least one player of the active team is both on the pitch and standing.

The metric is the minimum Chebyshev distance from the loose ball to any such
player. Opponents, absent players, and nonstanding players do not qualify.

### 3. `postkick-maxturn`

Configuration field: `demo_postkick_maxturn`

Closed range: `0..BBE_STATE_BANK_MAX_TURN` (`0..8`).

`BBE_STATE_BANK_MAX_TURN` is a tranche-local named constant with value `8`,
matching `bb_match.turn`'s documented `1..8` domain and the existing typed
record validator. This tranche does not invent the nonexistent
`BB_TURNS_PER_HALF` symbol or change engine bytes merely to name this bound.

For a record to have a finite metric, the ball is on the ground. The metric is
`match.turn[match.active_team]`. Typed record validation already requires the
active team and metadata turn to be valid and equal.

### 4. `pass-maxrange`

Configuration field: `demo_pass_maxrange`

Closed range: `0..BB_PITCH_LEN-1` (`0..25`).

For a record to have a finite metric:

- the ball is held by a valid player of the active team; and
- there is a different friendly player who is on the pitch, standing, and
  strictly closer to that team's scoring endzone than the carrier.

The metric is the minimum Chebyshev distance from the carrier to any such
receiver. The carrier's stance is not an additional condition; this preserves
the exact historical passing predicate. Home/Away mirror tests must produce
the same metric.

### Predicate versioning

These are environment-code semantics, not new claims injected into the
producer manifest. The pinned bank bytes and compiled environment-source hash
therefore bind the derived population without duplicating a mutable Python
predicate or adding a BBS sidecar. Any future predicate change changes the
environment source identity and requires a separate reviewed tranche.

Name the exact semantics
`bloodbowl-legacy-state-bank-strata-v1`. “Legacy” is intentional:
`postkick-maxturn` is only an early-turn loose-ball proxy, and
`pass-maxrange` is Chebyshev/downfield geometry rather than proof that a Pass
action is currently legal. This tranche must not silently upgrade either
predicate.

Add this literal as `PUFFER_STATE_BANK_STRATA_SCHEMA` in the generated build
header and include it in compiled-contract identity reconciliation. CPU/CUDA
module attributes and standalone `--state-bank-contract` expose the same
field. This extends the compiled field surface; it does not extend the
production producer allowlist or claim that a bank is installed.

This is an exact 20-to-21 compiled-field expansion across
`STATE_BANK_MACROS`, `NO_BANK_STATE_FIELDS`, field/macro and module mappings,
the generated header, both bindings, standalone JSON, and all exact-key tests.
The repository/no-bank compiled field also contains the literal schema because
it describes a compiled capability; only the inactive run/checkpoint
descriptor uses `none`.

## Index representation and construction

Add a selector-family enum with stable numeric values:

```text
0 uniform
1 endzone-maxdist
2 pickup-maxdist
3 postkick-maxturn
4 pass-maxrange
```

The complete strata object owns one concatenated `uint32_t` allocation. Each
nonuniform family owns a checked slice of it:

- an offset and length naming its contiguous record-index vector;
- an exact total qualifying count at the family's maximum threshold; and
- a prefix-count table indexed by canonical threshold; and
- a SHA-256 digest for each canonical prefix.

The vector is bucketed by the record's minimum qualifying metric in ascending
metric order. Original BBS order is stable within each metric bucket. For
threshold `t`, the eligible vector is exactly:

```text
indices[0 : prefix_count[t]]
```

Construction uses bounded counting-sort passes:

1. compute each record's minimum metric or `INELIGIBLE`;
2. count metric buckets;
3. derive checked prefix offsets;
4. sum the four exact maximum-threshold populations with overflow checks and
   allocate one concatenated vector;
5. fill each bucket in original BBS order; and
6. reconcile totals, offsets, every index bound, and every prefix; and
7. compute and store every canonical ordered-prefix digest.

The canonical digest input is:

```text
"bloodbowl-state-bank-stratum-v1\0"
+ lowercase BBS SHA-256 ASCII
+ "\0"
+ canonical selector-family ASCII
+ "\0"
+ threshold as unsigned little-endian 32-bit
+ eligible count as unsigned little-endian 32-bit
+ each eligible zero-based BBS ordinal as unsigned little-endian 32-bit,
   in exact vector order
```

Uniform mode has family `uniform`, threshold zero, every ordinal in BBS order,
and its own digest. Independent C test code and a small Python oracle must
produce byte-identical digests.

The explicit runtime record limit remains 1,000,000. The tighter current BBS1
limit is derived from the 256 MiB byte ceiling and the 2,252-byte
`12 + sizeof(bb_match)` record:

```text
floor((268,435,456 - 16) / 2,252) = 119,198 records
```

Four `uint32_t` ordinals per effective-maximum bank require at most
1,907,168 bytes. Prefix tables and digests are fixed small arrays. Construction
still checks the explicit record limit, the byte-derived limit, `UINT32_MAX`,
and every `SIZE_MAX` multiplication/addition rather than relying on the
current structure size.

Index construction is part of `bbe_state_bank_load_candidate()`. Any overflow,
allocation failure, count mismatch, out-of-range index, or internal predicate
reconciliation failure closes the complete candidate and publishes neither
matches, metadata, nor a partial index. Candidate close, process reset, failed
require, and sanitizer tests cover every ownership path.

Publication moves the fully built index into the same process-global
`UNTRIED -> READY` transaction as matches and metadata. The structure is never
mutated after publication and is shared read-only by vector workers.

### Deterministic multi-record fixture

Replace the generated integration fixture's one-record assertion and generic
writer with a small ordered bank whose expected ordinal table is authored
independently of the index builder. For every record, the fixture source pins:

- BBS ordinal, source ID, command, half, and turn;
- expected metric or ineligible status for all four families; and
- the intended Home/Away mirror relationship where applicable.

Together the records contain qualifying and nonqualifying examples for every
family, at least one empty low threshold, a record shared by multiple families,
and Home/Away endzone/pass mirrors. The generator validates this expected table
before writing the 21-field header. Native integration, the Python digest
oracle, validator-v2, module query, standalone descriptor, and exact audit all
use the same immutable bytes but compare against independently pinned expected
ordinals and metadata.

## Configuration and startup order

Raw configuration validation rejects:

- NaN, infinity, fractions, negatives, and values above the family bound;
- more than one nonzero selector;
- a nonzero selector with zero reset probability;
- a bank kind with zero reset probability;
- a positive reset probability without the exact compiled kind; and
- the existing incompatible team constraints.

A valid positive selector no longer returns the temporary bridge error.

Use one nonfatal resolver plus one aborting wrapper at every construction
surface:

1. validate raw/stored configuration;
2. require the exact compiled bank transaction;
3. resolve the canonical selector family/threshold;
4. prove the matching published prefix exists and is nonempty;
5. record/return its exact descriptor; and
6. only then enter `bbe_reset_match()` and emit an observation.

`my_vec_init()` performs this before allocating or returning the environment
array. `my_init()` does the same for scalar Puffer construction. `c_reset()`
repeats it for standalone and direct callers.

The requested prefix is checked again in `bbe_reset_match()` because direct
callers and tests can mutate environment fields between resets. A missing,
empty, or structurally invalid descriptor aborts with a selector-specific
diagnostic. It does not consume the curriculum probability draw and does not
become procgen.

The reset hot path is O(1). Before the probability draw it checks:

- process state is `READY` and the published bank kind matches;
- the resolved family and threshold are canonical and in range;
- the family slice offset and requested prefix count are within the one
  published allocation and the bank record count; and
- the requested prefix is nonempty.

After one prefix-position draw it checks:

- the selected position lies within that prefix;
- the selected BBS ordinal is within both match and metadata arrays;
- the selected record still satisfies the requested predicate; and
- the copied/restored match retains its bounded decision/legal surface.

Full vector order, every ordinal, every prefix count, and every stored digest
are reconciled during candidate construction before publication. A fresh
source-pinned validator/standalone process reconstructs that candidate and
therefore verifies it independently. A READY module query performs only the
stated O(1) slice/count checks and copies the already verified immutable
digest; neither query nor reset recomputes an O(population) SHA-256. This
tranche does not claim that arbitrary memory corruption of an unselected
in-bounds ordinal is synchronously detected. Tests corrupt only invariants that
the stated O(1) checks deterministically cover; no corruption test depends on a
random draw reaching a bad element.

## Exact reset sampling

The existing probability draw is unchanged.

When that draw selects a banked reset:

- uniform mode uses all `bbe_state_bank_n` records exactly as before;
- nonuniform mode uses the resolved prefix count;
- `bbe_rng_uniform_below()` draws an unbiased prefix position;
- the position maps through the immutable record-index vector;
- the record index is range-checked;
- the record's current metric is recomputed and must satisfy the requested
  threshold;
- decision/stack and post-advance legal-surface checks remain mandatory; and
- any failure aborts under a distinct corruption diagnostic.

There is exactly one record-position draw. No attempt counter, last candidate,
or fallback branch remains. Selector-zero and reset-zero RNG trajectories stay
bit-identical.

## Telemetry

Retain exact per-environment fields for the most recent banked reset:

- selector family;
- selector threshold;
- eligible record count;
- zero-based BBS record index;
- record source ID; and
- record command;
- record half/turn; and
- the exact stratum digest.

The pinned BBS SHA-256 plus the record index is the selected-record identity.
Source ID and command remain attribution metadata, not authorization.

Puffer's ordinary `Log` is float-aggregated and currently has room for only 15
more keys. `static_vec_log()` divides every `Log` float by all completed
episodes before `my_log()` exports it. It cannot truthfully preserve a sequence
of SHA-256 values or 32-bit record IDs. Do not cast a hash into floats or label
an average record ordinal as an identity.

Freeze the eight new ordinary keys and their denominators:

- `demo_uniform_episode_frac_all`;
- `demo_endzone_episode_frac_all`;
- `demo_pickup_episode_frac_all`;
- `demo_postkick_episode_frac_all`;
- `demo_pass_episode_frac_all`;
- `state_bank_config_episode_frac_all`;
- `demo_selector_threshold_mean_configured`; and
- `demo_selector_eligible_mean_configured`.

The five family fields add one only when a completed episode actually began
from that family, so after Puffer aggregation each is a fraction of all
completed episodes. Their sum equals the existing `demo_episodes`.

For every completed episode whose environment has a positive typed-bank reset
configuration, regardless of whether the probability draw chose bank or
procgen, the `Log` adds one configured-episode denominator plus the requested
threshold and eligible count. `my_log()` divides the two already-averaged
numerators by the already-averaged configured-episode denominator; the common
all-episode divisor cancels. Thus the two exported means describe the requested
configuration among configured episodes and are not multiplied by
`demo_reset_pct`. If no configured episode completed in the log window, both
are zero and the exact descriptor remains available from the nonaggregating
query.

The resolved configured family, threshold, eligible count, and digest are
latched in `Bloodbowl` at reset after validation. Episode completion reads only
that latch; it never rereads mutable selector fields. Direct callers that
mutate stored fields between resets therefore cannot relabel the episode that
actually ran.

Selector/index mismatch and post-copy restore/legal-surface rejection are hard
aborts before episode completion. They are therefore not claimed as observable
trainer-log counters. Their evidence is a distinct stderr/exit diagnostic,
deterministic forked tests, and the bounded audit path. `demo_fallbacks`
remains the compatibility invariant-zero field.

Eight new keys bring the environment total from 144 to 152; Puffer appends
`n`, for 153 of the 160 slots.

Before adding these keys, replace the stale multi-purpose
`training/puffer_dict_capacity.patch` with a focused pinned patch containing
only the four reachable 160-slot log allocations (native train/eval and
generic CPU/CUDA vector logs) and the `vecenv.h` release-build capacity abort.
Its historical action-mask and float-cast hunks are already owned by other
reviewed patches and make the present bundle neither forward- nor
reverse-applicable after the current stack. Then:

- apply or reverse-verify the focused exact patch at one deterministic stack
  point, then remove the broad Perl allocation rewrite across the affected
  backend sources;
- prove its `vecenv.h` release-build capacity abort;
- verify both CPU and CUDA log dictionaries allocate 160;
- include the patch in launcher patch-bundle provenance;
- update stale installer comments from 123 to the exact 152 planned keys; and
- make clean-install tests prove the installed diagnostic and both capacities.

Add exact nonaggregating inspection paths:

- the closed engine-linked validator output becomes
  `bloodbowl-state-bank-validation-v2` and returns the environment-source
  SHA-256, strata schema, family, threshold, eligible count, and ordered-index
  SHA-256;
- the installed CPU/CUDA module exposes the schema as a compiled attribute and
  a read-only stratum-descriptor query after the process bank is `READY`;
- standalone exposes the same descriptor plus a bounded, opt-in reset audit
  that prints exact `{bank_sha256, record_index, source_id, command, half,
  turn}` tuples; and
- generated-header integration tests compare those exact tuples to the copied
  records.

No stepping-thread file I/O or unbounded per-reset production logging is added.

Validation-v2 retains every exact typed v1 field, changes only its schema
literal, and adds exactly:

```json
{
  "environment_source_sha256": "64 lowercase hex characters",
  "strata_schema": "bloodbowl-legacy-state-bank-strata-v1",
  "strata_family": "endzone-maxdist",
  "strata_threshold": 6,
  "strata_eligible_records": 123,
  "strata_sha256": "64 lowercase hex characters"
}
```

Its CLI requires exactly one `--selector-family` and one
`--selector-threshold`; duplicate, unknown, missing, noncanonical, and
out-of-range arguments fail. Python accepts the exact closed v2 key set and
types, requires the echoed family/threshold, a positive eligible count not
exceeding bank records, uniform count exactly equal to bank records, and the
exact environment identity.

### Validator source provenance

The existing validator snapshot proves the independent engine-source pin but
only copies selected Puffer inputs. That is insufficient once predicates live
in Puffer environment code.

Move the exact legacy environment snapshot/hash framing into one canonical
function in `tools/state_bank_contract.py` and make both
`install_puffer_env.sh` and the validator snapshot call it. This is contract
option A: preserve the existing digest byte-for-byte; do not introduce an
environment-hash v2 in this tranche.

The Python function exactly reproduces the existing safe-filename
`sha256sum | sha256sum` stream. It dereferences the `bb` and `engine` links,
excludes only `./.content_hash` and `./state_bank_build.h`, sorts raw POSIX
relative-path bytes including the leading `./`, then feeds the outer SHA-256
one record per file:

```text
lowercase_file_sha256_ascii + "  " + "./relative/path" + "\n"
```

Names containing backslash, LF, CR, NUL, an absolute path, or a noncanonical
component are rejected, so GNU `sha256sum` filename escaping and platform
`shasum` differences cannot create two encodings. A compatibility test runs
the legacy shell pipeline and the Python implementation on the same unchanged
safe-name tree and requires exact equality (the base tree is
`f9ecefd331578e9243c8b4523107bbf4366b2d8d57d08a2883d2fc9f1d740bd1`)
before the shell implementation is retired.

Before compiling validation-v2:

1. snapshot the complete `puffer/bloodbowl` environment closure into the
   private workspace;
2. recompute its canonical environment SHA-256 from that frozen tree using the
   same shared function the installer used for source and installed snapshots;
3. require equality with the installed/generated `PUFFER_ENV_SOURCE_HASH`;
4. retain the independent canonical engine-source reconstruction and pin;
5. generate the minimal validator `state_bank_build.h` from reconciled
   literals and that environment identity—never copy the live excluded header;
6. invoke a fixed-path system compiler with explicit flags and a minimal
   environment that carries no make, compiler/include, or loader overrides;
7. build only from the two frozen source closures plus that deterministic
   generated header; and
8. require validation-v2 to reconcile and echo its compiled environment hash
   exactly.

`validate-installed` reconciles that echo with the installed generated header
before returning a descriptor. The launcher's existing mandatory compiled
module probe must then reconcile `_C.environment_source_hash` to that same
value before it can write a manifest or launch workers. The private parity
fixture exercises both steps. Tests mutate and replace `bloodbowl.h`,
`state_bank_runtime.h`, and another validator input during snapshot/build, and
reject a mismatched installed-module environment hash. A copied-but-unhashed
predicate file is a release blocker.

### CPU/CUDA module query

The runtime state has internal linkage in the environment translation unit.
Add this narrow external C ABI wrapper in `puffer/bloodbowl/binding.c`:

```c
int my_state_bank_stratum_descriptor(
    const char *family,
    uint32_t threshold,
    uint32_t *eligible_records,
    char ordered_index_sha256[65]);
```

The C wrapper, not pybind, parses the family and enforces bounds. It acquires
the state-bank lock, rejects pre-`READY` and no-bank state, checks the family
slice/prefix against the immutable allocation, copies count and lowercase
digest into caller-owned outputs, then releases the lock.

`binding.c` carries the plain literal marker
`#define PUFFER_HAS_STATE_BANK_STRATUM_QUERY 1`. Puffer's build recipe accepts
only that exact line from the selected environment binding and passes the same
macro to both CPU and CUDA binding compilations. Both pybind patch hunks place
the same `extern "C"` declaration and export under that guard; unrelated
Puffer environments compile without a reference to a Blood Bowl-only symbol.
Because the feature decision now depends on `build.sh`, add that file to
`exact_backend_hash()`'s source closure and its completeness tests.

The Python function is frozen as:

```text
_C.state_bank_stratum_descriptor(family: str, threshold: int)
```

It accepts exactly one canonical family string (`uniform`,
`endzone-maxdist`, `pickup-maxdist`, `postkick-maxturn`, or
`pass-maxrange`) and a `PyLong_CheckExact` nonnegative integer (boolean is
rejected). It returns exactly:

```json
{
  "schema": "bloodbowl-legacy-state-bank-strata-v1",
  "family": "endzone-maxdist",
  "threshold": 6,
  "eligible_records": 123,
  "sha256": "64 lowercase hex characters"
}
```

Unknown family, wrong Python type, out-of-range threshold, pre-`READY`, and
no-bank calls raise without fabricating a descriptor. CPU runtime tests cover
pre/post-`READY`; both binding patches are source-checked for parity; an
unrelated-environment CPU build proves the feature guard; CUDA is
source/preprocess checked locally and runtime-checked when a GPU is available.

### Standalone descriptor and audit

Add two mutually exclusive, exact modes:

```text
--state-bank-descriptor FAMILY THRESHOLD
--state-bank-audit FAMILY THRESHOLD COUNT
```

Both require the existing complete typed location tuple:
`--bank-kind strict-replay`, `--bank`, `--bank-producer-manifest`, and
`--bank-contract`. Duplicate, missing, unknown, mixed-mode, and unrelated
trailing arguments exit 2. `FAMILY` uses the same five strings, `THRESHOLD`
uses the same closed bound, and `COUNT` is a canonical decimal in `1..1000`.
The loose legacy positional episode argument is not used in either mode.

Descriptor mode requires/publishes the bank and emits exactly the same closed
five-key descriptor object as the module query. Audit mode performs exactly
`COUNT` direct resets at probability one, not random-policy episodes, and
emits exactly one NDJSON object per reset:

```json
{
  "bank_sha256": "64 lowercase hex characters",
  "record_index": 7,
  "source_id": 42,
  "command": 99,
  "half": 1,
  "turn": 3
}
```

No other stdout is permitted in these modes. `--state-bank-contract` remains
the compile-time 21-field contract view and gains only the strata-schema
field; it is not a selected descriptor.

`demo_fallbacks` remains exactly zero for compatibility. Empty-stratum,
descriptor-bound, selected-index, record-predicate, and restored-decision
failures have separate hard diagnostics and never continue into training.

## Launcher and lineage

The primary `tools/run_reward_ablation.sh`:

- keeps canonical-integer and mutual-exclusion checks;
- applies the same closed family bounds as C;
- removes only the temporary pre-index bridge;
- still requires reset percentage, explicit kind, and all three caller pins;
- still validates the exact installed transaction before CUDA/worker launch;
  and
- records all four selector fields in the run manifest.

It passes one canonical family/threshold pair to `validate-installed`.
`tools/state_bank_contract.py` forwards that pair to its immutable,
source-pinned native validator snapshot and accepts only the closed v2 output.

`validate-installed` does not currently call the native validator. This
tranche makes family and threshold mandatory, performs artifact and compiled
contract reconciliation first, then invokes the frozen validator and returns
its exact descriptor fields plus the reconciled environment-source hash. It
reads `PUFFER_ENV_SOURCE_HASH` from the same exact generated header parser used
for the other base build macros. The private authorized-fixture suffix
exercises that same parsing/reconciliation function rather than a parallel
test-only parser.

`tools/checkpoint_lineage.py` applies the same per-family bounds and mutual
exclusion. A complete active typed-bank manifest may carry one nonzero valid
selector.

Every active typed-bank run, including uniform selection, adds and validates:

- `ladder_state_bank_strata_schema`;
- `ladder_state_bank_strata_family`;
- `ladder_state_bank_strata_threshold`;
- `ladder_state_bank_strata_eligible_records`; and
- `ladder_state_bank_strata_sha256`.

The primary launcher obtains these values from the exact engine-linked
validator only after the installed typed-bank contract passes authorization
and pin reconciliation; it never computes an expected digest from a mutable
shell-side file scan. Checkpoint lineage requires the descriptor to reconcile
with the selector fields and bank record count. The inactive canonical form
uses `none`, `none`, zero, zero, and `unused`.

The launcher writes threshold and eligible-record fields as JSON integers, not
shell strings. Checkpoint lineage rejects string or boolean substitutions.

No run-manifest/checkpoint schema bump is needed: schema-v1 already carried the
conditional selectors, and checkpoint lineage hashes the complete raw run
manifest. The newly required conditional descriptor closes the deliberately
blocked active-selector form before any such production lineage existed.

Production authorization remains a literal empty set. Consequently this
tranche does not claim that a public active-bank launch can succeed. A valid
selector reaches the exact installed-contract/authorization path instead of
the retired selector bridge; public authorization still fails closed. Active
validation-v2/module/standalone parity uses a separate private multi-record
authorized fixture.

The two historical ladder wrapper recipes remain executable tombstones because
they embed stale machine paths, pools, and operational defaults. Their
diagnostic changes from “waiting for pre-indexed strata” to an explicit
retirement message directing operators to the primary typed launcher. No stale
wrapper becomes launch authority in this tranche.

The legacy raw-bank launchers and setup/transfer tombstones remain blocked for
their existing provenance reasons.

## Watched-fail tests before production edits

The first edit after plan approval is tests only. Capture current behavior
against `7bc96f1`.

### 1. Qualifying selector is rejected by the bridge

Publish a test candidate with one qualifying and one nonqualifying endzone
record. Configure reset probability one and threshold six through the real
`c_reset()` path.

Expected new behavior: startup succeeds and every reset chooses the qualifying
record.

Current watched behavior: configuration aborts with
`pre-indexed state-bank strata required`.

### 2. Empty stratum has no distinct startup contract

Use the immutable generated-header integration fixture and request a threshold
with zero eligible records.

Expected new behavior: abort before observation with the exact empty-stratum
diagnostic and zero selected-record telemetry.

Current watched behavior: the generic selector bridge aborts before any
population exists.

### 3. Selector upper bounds are open

Call the pure raw-config validator with endzone/pickup/pass threshold 26 and
postkick threshold 9.

Expected new behavior: each returns its family-specific range error.

Current watched behavior: all reach the generic bridge error.

### 4. Active selector lineage cannot be minted

Provide a complete active bank manifest with one canonical selector.

Expected new behavior: valid in-range/mutually exclusive lineage is accepted;
out-of-range or multiple selectors are rejected.

Current watched behavior: every nonzero selector is rejected as
“pre-indexed strata” regardless of validity.

### 5. Primary launcher blocks a valid selector at the bridge

Add a source/behavior contract proving the valid selector passes its knob gate
and reaches installed-contract validation, while invalid bounds fail before
artifact/CUDA inspection.

Current watched behavior: a fully supplied valid selector stops at the
temporary bridge.

### 6. Validator does not bind the environment predicate bytes

Mutate a copied `state_bank_runtime.h` after the current engine-only snapshot
pin has been established.

Expected new behavior: the private full-environment snapshot hash or
post-snapshot identity check rejects the mismatch before validator output.

Current watched behavior: the selected Puffer file is copied for compilation
without reconciliation to `PUFFER_ENV_SOURCE_HASH`.

### 7. Installed dictionary capacity guard is absent

Inspect a clean exact-pinned installation.

Expected new behavior: the exact capacity patch reverse-applies, all four
reachable log dictionaries allocate 160, and `vecenv.h` contains the
release-build `dict_set: capacity` abort.

Current watched behavior: allocations are Perl-expanded, but the exact
`vecenv.h` hard-abort patch is neither applied nor reverse-verified.

The watched log must contain the observed runtime/error text, not only a
compile failure for a future helper.

### Captured red evidence — 2026-07-27

No production, fixture, generated-source, or documentation implementation was
changed before these tests ran. Both native test binaries compiled and
`git diff --check` passed.

The real-reset selector watch:

```text
$ ./build/puffer_state_bank_tests state_bank_qualifying_endzone_selector
bloodbowl: invalid state-bank configuration: pre-indexed state-bank strata required
OBSERVED qualifying endzone selector should reset successfully: child received signal 6
1 tests, 1 failures
```

The four pure-validator bound watches:

```text
$ ./build/puffer_state_bank_tests selector_rejects_upper_bound
OBSERVED ... got "pre-indexed state-bank strata required", expected
  "demo_endzone_maxdist must be an exact integer in [0,25]"
OBSERVED ... expected "demo_pickup_maxdist must be an exact integer in [0,25]"
OBSERVED ... expected "demo_postkick_maxturn must be an exact integer in [0,8]"
OBSERVED ... expected "demo_pass_maxrange must be an exact integer in [0,25]"
4 tests, 4 failures
```

The generated-header integration watch retained 13 passing cases and failed
only the new empty-prefix case:

```text
$ ./build/puffer_state_bank_contract_tests
observed empty-stratum diagnostic
  "bloodbowl: invalid state-bank configuration: pre-indexed state-bank strata required"
expected
  "bloodbowl: requested state-bank stratum is empty: endzone-maxdist=1"
1 integration failure(s)
```

The Python contract watch ran:

```text
$ python3 -m unittest \
  tools.test_checkpoint_lineage.CheckpointLineageTests.test_state_bank_active_selector_with_exact_descriptor_is_accepted \
  tools.test_checkpoint_lineage.CheckpointLineageTests.test_state_bank_selector_bounds_are_family_specific \
  tools.test_checkpoint_lineage.CheckpointLineageTests.test_state_bank_descriptor_counts_are_exact_json_integers \
  tools.test_ladder_knobs.LadderKnobTests.test_each_selector_rejects_its_first_out_of_range_value \
  tools.test_ladder_knobs.LadderKnobTests.test_valid_selector_reaches_installed_contract_validation \
  tools.test_state_bank_contract.PufferStateBankPatchTests.test_validator_binds_predicate_sources_to_installed_environment_hash \
  tools.test_puffer_log_contract.PufferLogContractTests.test_every_puffer_log_path_and_installer_pin_same_capacity
Ran 7 tests in 0.070s
FAILED (failures=15, errors=1)
```

Its failures independently exposed the active-lineage bridge, missing
family-specific launcher bounds, missing validator/environment-source
reconciliation, and the stale multi-purpose capacity patch.

## Focused test matrix

### Predicate metrics

- every family at threshold minus one, exact threshold, and threshold plus one;
- invalid ball state, carrier, team, location, or stance as applicable;
- pickup ignores opponents and nonstanding teammates and chooses the minimum;
- postkick covers turns 1 and 8;
- pass ignores the carrier, opponents, lateral/backfield receivers, absent
  players, and nonstanding receivers;
- Home/Away mirrored endzone and pass records produce equal metrics;
- historical edge semantics, including a nonstanding pass carrier, remain
  locked.

### Index construction

- exact stable bucket order and prefix counts for all thresholds;
- monotonic prefixes and exact maximum totals;
- a record appears at most once per family and in every later eligible prefix;
- one record may independently belong to multiple families;
- empty family and empty low threshold are represented without `malloc(0)`
  ambiguity;
- exact maximum record count and index type bounds;
- injected failure at every index-related temporary/final allocation closes
  every prior candidate allocation;
- candidate close and process reset free every index exactly once;
- failed candidate validation never publishes an index;
- concurrent first require publishes one complete match/metadata/index set;
- O(1) reset corruption tests cover deterministic slice/count/selected-index
  bounds and selected-predicate failure only; full unselected-vector corruption
  is a construction/inspection concern.

### Runtime selection

- selector zero preserves uniform full-bank sampling;
- every nonuniform draw belongs to the exact requested prefix;
- eligible population one always chooses that record;
- thin populations never retry and never use an ineligible record;
- empty requested prefix aborts before observation;
- out-of-allocation prefix count, selected record index, and selected predicate
  corruption each abort distinctly and deterministically;
- stored-field mutation between resets is revalidated;
- all four families succeed through real `c_reset()`;
- selector/source/index telemetry matches the copied record;
- repeated seeded runs produce identical selected-record sequences;
- default no-bank and uniform-bank trajectories remain deterministic.

### Configuration, launcher, and lineage

- nonfinite, fractional, negative, above-bound, and multiple selectors;
- positive selector with zero reset;
- active selector without complete external bank authority;
- primary launcher valid selector reaches exact installed-contract validation,
  not the old bridge;
- inactive run-manifest form remains canonical;
- one valid active selector round-trips checkpoint lineage;
- every family above its bound and every multiple-selector manifest fails;
- historical wrappers remain side-effect-free tombstones with accurate
  retirement diagnostics.

### Telemetry and installed surfaces

- binding exports every new log field;
- completed procgen episodes do not claim selector identity;
- completed uniform and family-selected episodes increment the right family;
- a mixed `demo_reset_pct` run reports family fractions over all episodes while
  threshold and eligible means remain conditioned on configured episodes;
- native validator, module query, and standalone agree on schema, family,
  threshold, eligible count, ordered-index digest, and environment-source
  identity;
- standalone prints exact selected-record tuples only in a bounded opt-in
  audit;
- installed CPU module and standalone agree on the compiled bank contract and
  strata-schema fields;
- environment source digest changes; observation/action and exact-backend
  identities change only if their actual source closures require it;
- a deterministic ordered multi-record fixture pins every record ordinal,
  source ID, command, intended family metric, Home/Away mirrors, qualifying
  and nonqualifying cases, and an empty low threshold independently of the
  runtime index builder.

## Validation gates

1. Watched failures recorded before production implementation.
2. Focused optimized predicate/index/config/reset tests.
3. Focused ASan/UBSan tests, including allocation-failure cleanup.
4. Full optimized native matrix.
5. Full native ASan/UBSan matrix.
6. Full Python tools and training suites.
7. Shell syntax and `shellcheck --severity=warning`.
8. Relevant `ruff check`, `ruff format --check`, `py_compile`, and
   `git diff --check`.
9. Generated-header integration twice with qualifying selection, empty-tier
   failure, artifact mutation failures, and singular concurrent publication.
10. Default seed-42 100-episode FNV twice:
    `ea1d720e69f5a491`, 26,251 steps, zero illegal actions.
11. Clean exact-pinned no-bank PufferLib install/rebuild/check on
    `9836f0d2e78889c1aaf189c04d161b6fc61a9386`, including the installed
    dictionary hard-abort and all four 160-slot allocations.
12. Separate private authorized multi-record fixture staging/rebuild. Exercise
    the same v2 parser/reconciliation suffix that future public authorization
    would use, then prove native-validator, CPU-module query, and standalone
    descriptor parity plus bounded exact-selection audit. CUDA is source/patch
    validated locally; no GPU training is launched.
13. Unrelated-environment CPU build proves the optional query feature guard
    does not introduce an unresolved Blood Bowl symbol.
14. Record exact engine, environment, backend, module, standalone, and
    generated-header hashes.

## Completed implementation and evidence — 2026-07-27

The watched-red commit is `fff4a1c`. The implementation preserves the
production producer allowlist as the literal empty set and adds no training
launch or active-asset mutation.

Implemented:

- exact historical metrics for all four selector families;
- one immutable, transactional, stable-prefix index built before publication;
- exact unbiased selection from the requested prefix, with selected-record
  predicate revalidation and hard empty-tier failure;
- per-episode selector provenance and aggregate Puffer telemetry;
- the independent seven-record oracle, generated-header integration, native
  validator-v2, module query, standalone descriptor, and bounded reset audit;
- full environment-source snapshot/reconciliation for validator compilation;
- exact primary-launcher and checkpoint-lineage descriptor support;
- all four reachable 160-slot Puffer log dictionaries plus the release-build
  capacity abort; and
- explicit retirement of the stale historical wrapper recipes.

The adversarial implementation reviews found and closed:

- an explicit threshold-zero selector incorrectly collapsing to public
  selector-zero/uniform behavior;
- uninitialized negative-test descriptors and short-circuit cleanup leaks;
- only the generic vector-log dictionaries, rather than all four reachable
  native train/eval dictionaries, initially receiving the larger capacity;
- validator compilation inheriting caller compiler/include/loader state;
- the frozen validator build consuming the live excluded
  `state_bank_build.h`;
- incomplete build-race coverage for the predicate and validator sources; and
- relative installed-Puffer roots becoming invalid when the native validator
  changed into its isolated working directory.

After those fixes, the independent native and Python/Puffer reviewers both
reported no residual P0, P1, or P2 issues. The required Kimi pass was omitted
only after the user explicitly authorized proceeding without it.

Validation results on the final tree:

- `make test`: 476 engine, 64 reward, 2 contact-bot, 54 state-bank,
  26 observation, generated-header integration, standalone contract/audit,
  and BBP-v6 writer checks passed;
- `ASAN_OPTIONS=detect_leaks=0 make asan`: the same complete native matrix
  passed under ASan/UBSan;
- tools: 331 tests passed, 2 skipped;
- training: 95 tests passed, 1 skipped;
- generated-header integration passed twice with zero failures;
- seed-42 masked 100-episode trajectory passed twice with FNV
  `ea1d720e69f5a491`, 26,251 steps, and zero illegal actions;
- `bash -n`, `shellcheck --severity=warning`, `py_compile`, `ruff check`,
  the new standalone test's `ruff format --check`, and `git diff --check`
  passed;
- a new checkout at PufferLib
  `9836f0d2e78889c1aaf189c04d161b6fc61a9386` accepted the final installer
  twice, both exact patches reverse-applied, the no-bank contract checked,
  all four 160-slot allocations were present, and the capacity abort was
  present;
- the compiled no-bank CPU module and standalone passed
  `install_puffer_env.sh --check`; and
- after private staging, the CPU module matched all 88 independently
  generated descriptors and the standalone passed the full descriptor,
  32-reset exact-audit, invalid-CLI, empty-tier, and compiled-contract suite.

The container's x86 emulator does not implement the AVX2 instructions emitted
by upstream's unconditional `-mavx2 -mfma` flags. The exact upstream CPU build
therefore compiled successfully but trapped at import. For executable
module/standalone validation only, an external compiler wrapper filtered those
two architecture-target flags without changing Puffer or environment source.
The resulting module and standalone passed all identity, descriptor, audit,
and drift checks. No GPU training was launched.

Final identities and artifacts:

```text
engine source
  0fc21a6b46f536e09b972299290e48f34aa290e7894bf113443cbb1c0c4d9bc6
environment source
  0e8913d9ee03159703cf4fb9d89f79b8ba541ed0a09d793af89eea9c8c365106
exact Puffer backend source
  4ef767a1374326a2cc5923064f02c40955a242651b7e8c0369e560ca0de2aa9b
private-bank CPU module
  b44a6309ffeb225d3f53795bef13a54f8132a9db42c5575b52882e43e17a5cab
private-bank Puffer standalone
  8d5d4f3dadffee07c1209b16350054cecc747b9821ca4f3ee64bd603444492f1
private installed generated authority
  37fb59b25af22d06c90bb58a06171377cc9b9b6aa58c80201143b8dedc8ac76d
local generated integration header
  b72b269babe54a4d311200f19c6435cc9ca49af2d3e79633aa89f1ecd40a61b4
seven-record BBS
  d1deac8d398b5c5888ef2a05d45ba904aeb9a6f5362129fbcaf9b8232e32a1ca
private compiled contract identity
  f87003b441b94f23a1e19598922de976e12057c870ff25b11b160fe04cdaada6
```

## Version and lineage decision

- BBS remains BBS1 version 1.
- Producer, training, and authorization schemas do not change.
- Add the derived-view schema
  `bloodbowl-legacy-state-bank-strata-v1`; it is not producer authorization.
- Production producer authorization remains empty.
- Observation v6/2782, exact-joint-v1, BBP v6, model, reward, and checkpoint
  bytes do not change.
- Run-manifest/checkpoint schema stays version 1; active bank forms gain the
  conditional exact stratum descriptor listed above.
- Environment source identity changes and therefore clean-installed module and
  standalone hashes change.
- The exact-action backend digest changes because the installed Puffer binding
  and `vecenv.h` closure gains the exact capacity guard/query integration; the
  action ABI string remains `exact-joint-v1`.
- Selector-zero and no-bank historical lineages remain behaviorally compatible.
- A nonzero-selector lineage is newly valid only when its complete typed-bank
  identity and current environment-source identity are also present.

## Required adversarial-review blockers

Implementation must not begin while any of these remains:

- an eligible population is derived lazily or by retrying during reset;
- an empty requested stratum can reach procgen or a broader tier;
- a selected record is not rechecked against the requested predicate;
- modulo sampling or the old 256-attempt loop remains;
- index construction can publish a partial family after allocation failure;
- threshold prefixes can contain duplicates, out-of-range indices, or unstable
  source ordering;
- raw config, launcher, runtime, and lineage disagree on bounds;
- Home/Away predicate semantics are not mirror-locked;
- selected-record telemetry cannot be tied to the pinned BBS record;
- an averaged float metric is presented as exact record/hash provenance;
- the ordered-index digest can be generated by a shell-side observation rather
  than the source-pinned native validator;
- the validator's frozen predicate bytes are not reconciled to the generated
  header and installed module environment-source identity;
- aggregate telemetry is mislabeled as one exact record identity;
- bank-only threshold/eligible numerators are divided by all completed
  episodes and presented as configuration values;
- a hard-aborting reset failure is claimed as an observable completed-episode
  trainer counter;
- reset claims arbitrary prefix-corruption detection without an O(1)
  deterministic invariant;
- CPU/CUDA query linkage depends on reaching a static runtime symbol directly
  or breaks unrelated Puffer environment builds;
- descriptor/audit parsers accept duplicate, unknown, noncanonical, or
  unbounded arguments;
- Puffer's release-build log dictionary can overflow without the exact
  installed hard-abort guard;
- a stale historical wrapper is silently reactivated;
- a new manifest/observation/action/checkpoint schema is invented without a
  byte-layout need;
- production producer authorization is widened;
- the implementation mutates or launches an active training asset; or
- the default FNV trajectory changes.

After explicit adversarial approval, implementation starts with the watched
tests and proceeds only after their current red behavior is recorded.
