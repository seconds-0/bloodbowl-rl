# Typed, hash-pinned, fail-closed state-bank contract

Status: completed and adversarially clean 2026-07-27

Base: `7d0e9df`

Adversarial verdicts:

- provenance/installer/test-contract review: **APPROVE**, no P0/P1 blockers;
- C runtime/config/native-test review: **APPROVE**, no P0/P1 blockers.

Kimi review is waived for this and subsequent items by the user's explicit
instruction on 2026-07-27.

Watched-fail evidence captured before production edits:

- missing required bank: child exited normally after reaching a procedural
  decision with `demo_started=0`, rather than aborting;
- mixed valid/invalid two-record BBS: loader published the one-record valid
  subset;
- selector miss: child used the sole nonqualifying record after 256 attempts,
  set `demo_started=1`, and left `demo_fallbacks=0`;
- shell contract: five test methods produced 17 focused failures covering four
  absent caller-authority values, TOFU digest assignment, seven absent typed
  installer options, implicit legacy-bank staging, and absent no-bank cleanup.

## Objective

Make a requested state-bank curriculum an exact startup contract rather than
an optional file lookup.

After this tranche, the native runtime can use banked resets only when all of
the following identities agree:

- the operator-declared bank kind;
- an externally supplied SHA-256 pin for the complete manifest;
- an externally supplied SHA-256 pin for the BBS bytes;
- the manifest's training role, source ruleset, producer kind, byte count,
  record count, BBS header, and engine-source identity;
- the generated contract compiled into the standalone/Puffer environment;
- the exact manifest and BBS bytes staged beside that environment; and
- every record's metadata namespace and structural resumability.

Any mismatch, missing file, short read, trailing byte, malformed record, wrong
kind, or incompatible second process-local request aborts before a worker can
step or a procedural fallback can masquerade as the requested curriculum.

This tranche keeps BBS1 bytes unchanged. It adds an external typed manifest,
preserves BBS metadata at runtime, and makes installation and launch identity
explicit. Production admission is deliberately disabled in this tranche:
the production producer-kind allowlist is the empty set because no current
artifact has trustworthy from-source producer evidence. The runtime contract
is exercised with an immutable generated-header integration fixture, while
every production installer invocation containing bank arguments fails with
`NO_AUTHORIZED_PRODUCER`.

## Confirmed defects

The current trust boundary loses information at every stage:

1. `tools/filter_state_bank.py` publishes strong source, allowlist, output, and
   count evidence, but neither installation nor runtime consumes its manifest.
2. `tools/install_puffer_env.sh` implicitly copies the edition-blind
   `validation/states/bank.bbs`, uses an ordinary `cp`, and leaves an old
   destination in place when the implicit source is absent.
3. `tools/run_reward_ablation.sh` hashes whatever file happens to be staged.
   That is an observed/TOFU value, not a reviewed expected identity.
4. `bbe_state_bank_load()` treats missing, incompatible, malformed, unreadable,
   empty, and allocation-failed banks as “curriculum off.”
5. The loader breaks on a short record read, drops invalid records, and
   publishes any valid prefix/subset. The resulting sampling distribution can
   differ from the reviewed artifact while training continues.
6. BBS metadata is discarded after load, preventing type checks and record
   attribution.
7. Direct Puffer and standalone entry points bypass the strongest shell guard.
8. The four selector loops use the last random record after 256 misses, even if
   it does not satisfy the requested predicate, while `demo_fallbacks` remains
   zero.
9. The process-global once flag is set before load success and does not bind the
   result to a remembered contract identity.

The current `bb_state_bank_resumable_valid()` gate remains valuable. It proves
that a raw match is safe to resume; it does not prove artifact identity,
edition, producer, training authorization, or content integrity.

## Scope boundary

In scope:

- one exact producer-manifest schema plus a separate strict-replay training
  authorization contract;
- an explicit distinction between `training-bank`, `analysis-only`, and
  `structural-proof` artifacts;
- an exact strict BB2025 filter manifest that remains `analysis-only`;
- explicit, externally supplied training-contract, producer-manifest, and BBS
  SHA-256 pins;
- a dependency-free C SHA-256 implementation with independent known vectors;
- a same-open/same-buffer, exact-size, exact-count, all-or-nothing C loader;
- process-wide contract identity and incompatible-second-request rejection;
- preserved source ID, command, half, and turn metadata;
- kind-specific source-ID and structural-boundary checks;
- required-bank startup failure in vector, scalar, and standalone paths;
- exact state-bank-specific configuration validation at the C binding;
- explicit, transactional installer staging and bank-aware `--check`;
- primary launcher expected-pin validation and complete run-manifest identity;
- exact compiled-contract exports from both Puffer extension backends and the
  installed standalone;
- conditional bank-field validation before checkpoint lineage can be minted;
- removal of implicit ambiguous-bank staging;
- a temporary fail-closed bridge that rejects every nonzero selector until the
  next tranche implements exact pre-indexed strata;
- documentation, deterministic validation, sanitizer validation, clean
  installation, module/standalone validation, and default FNV preservation.

Out of scope:

- exact selector index construction or sampling; that is the next tranche;
- selector weights, curriculum schedules, capability labels, or reward changes;
- publishing or training on the 26-record authored proof bundle;
- enabling authored state banks at all; enum value 2 is reserved but rejected
  by validator, installer, binding, and runtime in this tranche;
- declaring or promoting the existing D191 strict artifact as training-ready;
- claiming a new producer-engine identity for unchanged historical BBS bytes;
- completing the authored serializer, sidecars, balance report, or publisher;
- hardening `validation/build_state_bank.py` into the future exact
  producer-manifest publisher;
- changing BBS1 bytes, `bb_match`, observation v6, exact-joint-v1, BBP v6, or
  checkpoint bytes;
- broad validation of every unrelated environment kwarg;
- replacing raw `bb_match` serialization with a portable field schema;
- mutating any active training checkout, queue, checkpoint, or corpus;
- launching training;
- pre-indexed selector telemetry or paired-side diagnostics.

The selector bridge is intentional. A typed loader is not honestly
“curriculum-safe” while an impossible or thin selector can silently draw from
the wrong tier. The runtime contract supports uniform bank resets, exercised
only by the immutable native integration fixture in this tranche. Production
bank installation remains disabled. Nonuniform selectors abort with an exact
“pre-indexed strata required” diagnostic until the next item removes that
bridge.

## Producer and training-authorization contracts

Producer evidence and training authorization are deliberately separate.
Hashing a manifest proves which bytes were approved; it does not make a
self-asserted producer claim true.

`tools/filter_state_bank.py` emits an exact
`bloodbowl-strict-filter-manifest-v2` analysis manifest. Its complete schema is
closed: duplicate, missing, and unknown keys are rejected at every object
level. The root has exactly `schema`, `schema_version`, `tool`, `command`,
`format`, `input`, `allowlist`, `output`, `selected_ids`, `excluded`,
`limitations`, and `artifact`. The pre-existing nested objects retain exactly
their current keys:

- `tool`: `path`, `sha256`;
- `format`: `magic`, `version`, `match_size`, `engine_fingerprint`,
  `record_count_is_file_size_derived`;
- `input`: `path`, `bytes`, `sha256`, `records`, `replay_ids`,
  `half_histogram`, `turn_histogram`;
- `allowlist`: `path`, `bytes`, `sha256`, `ids_total`, `ids_matched`,
  `ids_unmatched`;
- `output`: `path`, `bytes`, `sha256`, `records`, `replay_ids`,
  `half_histogram`, `turn_histogram`;
- `selected_ids`: `path`, `bytes`, `sha256`, `count`;
- `excluded`: `records`, `replay_ids`, `replay_id_values`; and
- `artifact`: exactly the objects and fields shown below.

`command` and `limitations` are nonempty arrays of nonempty strings;
`replay_id_values` is a strictly increasing array of positive JSON integers;
histogram keys are canonical positive decimal strings and values are positive
JSON integers; paths are nonempty strings; hashes and scalar counts use the
canonical rules below. The existing output/count/histogram relationships are
reconciled rather than merely type-checked. It adds the root textual schema
and the analysis artifact envelope:

```json
{
  "schema": "bloodbowl-strict-filter-manifest-v2",
  "schema_version": 2,
  "artifact": {
    "schema": "bloodbowl-state-bank-producer-v1",
    "artifact_role": "analysis-only",
    "bank_kind": "strict-replay",
    "ruleset": "BB2025",
    "training_eligible": false,
    "bank": {
      "sha256": "<64 lowercase hexadecimal characters>",
      "bytes": 34563712,
      "records": 15348,
      "format": {
        "magic": "BBS1",
        "version": 1,
        "match_size": 2240,
        "engine_fingerprint": "0x12345678"
      }
    },
    "producer": {
      "kind": "strict-bb2025-filter-v2",
      "producer_engine_source_sha256": null
    }
  }
}
```

The historical D191 source bank has no manifest proving the exact engine source
that originally serialized its raw `bb_match` bytes. Filtering it today may
record the filter/loader source used today, but
`producer_engine_source_sha256` remains JSON `null`. It is therefore
unpromotable. Regenerating only the manifest must never write the current
engine digest into that field.

A future from-source producer transaction must define a new literal producer
kind and its complete producer-specific closed schema while binding the raw BBS
writer binary/source, normalized replay inputs, strict BB2025 edition evidence,
output bytes/counts, and transaction. No such kind or producer-specific schema
is defined or accepted in this tranche. Hardening that producer is a separate
reviewed item.

The installable artifact is a separate exact
`bloodbowl-state-bank-training-contract-v1` manifest:

```json
{
  "schema": "bloodbowl-state-bank-training-contract-v1",
  "artifact_role": "training-bank",
  "bank_kind": "strict-replay",
  "ruleset": "BB2025",
  "training_eligible": true,
  "bank": {
    "sha256": "<reviewed BBS SHA-256>",
    "bytes": 34563712,
    "records": 15348,
    "format": {
      "magic": "BBS1",
      "version": 1,
      "match_size": 2240,
      "engine_fingerprint": "0x12345678"
    }
  },
  "producer_manifest": {
    "sha256": "<reviewed producer-manifest SHA-256>",
    "schema": "bloodbowl-state-bank-producer-v1",
    "producer_engine_source_sha256": "<non-null producer engine SHA-256>"
  },
  "loader": {
    "engine_source_sha256": "<current loader engine SHA-256>"
  },
  "authorization": {
    "schema": "bloodbowl-state-bank-authorization-v1",
    "decision": "<reviewed immutable decision/reference>"
  }
}
```

Every object in this contract rejects duplicate, missing, and unknown keys.
The producer manifest is supplied and pinned separately. The shared validator
parses the closed common artifact envelope and reconciles every duplicated
bank, format, engine, output, and count field before authorization. It accepts
no producer-specific fields unless a future reviewed producer kind defines
their exact closed schema. A pinned opaque payload or self-declared engine hash
never becomes producer authority.

Exact recognized contract/envelope values:

| Field | Allowed values |
|---|---|
| training schema | `bloodbowl-state-bank-training-contract-v1` |
| producer schema | `bloodbowl-state-bank-producer-v1` |
| authorization schema | `bloodbowl-state-bank-authorization-v1` |
| `artifact_role` | `training-bank` |
| `bank_kind` | `strict-replay` |
| `ruleset` | `BB2025` |

Exact production producer authorization in this tranche:

| Field | Allowed values |
|---|---|
| producer `kind` | none; the allowlist is the empty set |

Thus every production bank-argument installer invocation reaches a stable
`NO_AUTHORIZED_PRODUCER` rejection after bounded reads, external digest checks,
closed common-schema validation, and cross-file reconciliation. There is no
literal production producer token, hidden escape hatch, environment switch,
or `--test-only` production mode.

Consistency rules:

- installation requires the literal training role and boolean;
- analysis/proof producer manifests are never directly stageable;
- a training contract requires a non-null, exact producer-engine source hash;
- loader-engine identity is separate and must equal the current source;
- the current D191 filter manifest cannot satisfy the producer requirement;
- authored kind is rejected before schema or namespace can be used to bless it;
- all hashes are exact lowercase SHA-256 strings;
- all counts are positive JSON integers, never floats or booleans;
- `bank.bytes` must equal
  `16 + records * (12 + match_size)` without overflow;
- every duplicated bank field must agree across BBS, producer, and training
  contract;
- the BBS fields must equal the actual file and current loader ABI.

The engine-source hash is not an invocation of Git or a platform `sha256sum`
text format. Version 1 hashes the domain
`bloodbowl-engine-source-v1\0`, followed by every regular file under
`engine/include/bb` and `engine/src` in bytewise-sorted POSIX-relative path
order. Each entry is encoded as an unsigned little-endian 64-bit path length,
the UTF-8 relative path bytes, an unsigned little-endian 64-bit content
length, and the exact content bytes. One repository convenience symlink is
excluded only after exact verification: `engine/src/bb` must be a symlink whose
raw target is `../include/bb`; its real files are already hashed once through
`engine/include/bb`. Every other symlink, nonregular entry, duplicate logical
path, invalid UTF-8 path, or empty tree is rejected. The same Python
implementation is used by the filter, installer, and installer check.
The C runtime does not need to walk a source tree: the validated value is
compiled into its generated contract, while the existing BBS match-size and
fingerprint checks remain the raw-ABI gate.

`tools/filter_state_bank.py` has no option that emits `training-bank`. A future
authorization tool may construct a candidate training contract from a
qualifying exact producer transaction, but it never derives the expected
training-contract pin. Installation and launch require that full SHA from the
operator as the external reviewed authority.

This tranche defines and tests the strict training contract and common
producer envelope but publishes no production training bank. Focused native
tests use a deterministic `test-strict-fixture-v1` producer/contract fixture
compiled into a dedicated integration binary; the production producer
allowlist does not contain that token, so the production installer rejects it.
The current D191 BBS SHA may remain unchanged under analysis regeneration, but
no new manifest claims that those bytes were produced by the current engine.

## Numeric kind and generated build contract

The runtime enum is:

```c
typedef enum {
    BBE_STATE_BANK_NONE = 0,
    BBE_STATE_BANK_STRICT_REPLAY = 1,
    BBE_STATE_BANK_AUTHORED_SCENARIO = 2,
} bbe_state_bank_kind;
```

`state_bank_kind` is a numeric Puffer kwarg because the current dictionary
bridge carries only doubles. It must be finite and integral. Production accepts
only 0 or 1 in this tranche; value 2 is reserved and fails with an explicit
“authored publisher not implemented” diagnostic. A value such as 1.5 must
never truncate to 1.

The tracked `ocean/bloodbowl/state_bank_build.h` is a no-bank fallback in the
repository. Installation replaces it with a deterministic bridge that includes
the single generated authority at `src/exact_action_build_hash.h`; it does not
duplicate contract values. That generated authority records:

- training-contract and producer-manifest schemas;
- numeric and textual kind;
- ruleset;
- exact BBS, complete training-contract, and complete producer-manifest
  SHA-256;
- distinct producer-engine and loader-engine source SHA-256 values;
- bytes and records;
- BBS version, match size, and engine fingerprint; and
- one unique compiled contract-identity string.

The generated bank header is deliberately outside the environment source hash:
code identity and input-data identity are separate fields in run provenance.
A dedicated Puffer patch exports every generated field from both CPU and CUDA
`_C` modules. The installed standalone exposes the same fields through a
machine-readable `--state-bank-contract` mode.

`--check` compares header, staged files, current source, every exported `_C`
field, and standalone metadata field-for-field. Mtime is only an additional
staleness check; substring presence is not acceptance evidence.

The production contract constants are immutable. Native parser tests do not
mutate them. Instead, the loader core is a pure, nonfatal
`load_candidate(request, output)` seam that receives an explicit immutable
request and publishes only into caller-owned temporary output. The production
require wrapper constructs that request only from compiled constants and is
the sole code allowed to publish process-global state. Tests can exercise exact
hash/count/error behavior with a test fixture request while the tracked header
remains `NONE`.

A second integration binary exercises the production wrapper itself against an
immutable generated strict test contract:

1. a deterministic C fixture writer creates an ordinary-boundary BBS from the
   current engine;
2. a Python generator uses `hashlib` to write test-only producer/contract files
   and a contract header under `build/test_state_bank_contract/`;
3. the integration binary is compiled with an explicit
   `BBE_STATE_BANK_BUILD_HEADER` override naming that generated header; and
4. every fatal case forks from a parent whose process-global status is
   `UNTRIED`.

That binary covers valid uniform reset, exact missing-file stage, selector
bridge, READY reuse, path conflict, global publication, and failure
idempotence. The test-only producer token/header is rejected by production
Python validation and cannot be passed to `install_puffer_env.sh`. The Makefile
explicitly depends on the SHA header, fallback header, fixture writer,
generated fixture files, and both test sources.

## State-bank-specific configuration invariants

The authoritative C binding, not only a launcher, validates the original
double values before any float or integer conversion:

- `demo_reset_pct` is finite and in `[0, 1]`;
- a positive reset percentage that would become `0.0f` after conversion is
  rejected rather than silently becoming kickoff-only;
- `state_bank_kind` is an exact enum integer;
- all selector kwargs are exact nonnegative integers;
- at most one selector is nonzero;
- a selector with zero reset percentage is rejected as inert;
- a bank kind with zero reset percentage is rejected as inert;
- positive reset percentage requires a nonzero kind;
- when reset percentage is positive, the nonzero requested kind must equal the
  compiled contract kind;
- positive reset percentage requires a successfully loaded bank;
- banked resets require the raw `exclude_team`, `force_home_team`, and
  `force_away_team` doubles to be exactly `-1.0`; NaN, fractional values, and
  values that merely cast to `-1` are rejected because the bank path ignores
  those constraints; and
- until pre-indexing lands, every nonzero selector is rejected after the above
  consistency checks with the bridge diagnostic.

A compiled build may contain a bank while a particular environment requests
`demo_reset_pct=0` and `state_bank_kind=0`; this is the supported kickoff-only
evaluation path and must not open the bank.

`my_vec_init()` applies and validates kwargs before requiring the process-wide
bank, but still completes the load before returning environments to any worker.
`my_init()` applies the same invariant. Standalone `c_reset` retains a lazy
required-load guard so direct callers cannot bypass it.

## Runtime loader contract

The loader is split into:

1. a pure, nonfatal candidate loader that takes an explicit immutable request,
   allocates temporary output, and returns a stable reason code without touching
   globals; and
2. a production require wrapper whose request is constructed only from the
   immutable generated build contract and whose successful result is the only
   path that publishes process-global arrays.

The wrapper retains an explicit status and failure reason:

```text
UNTRIED -> READY
UNTRIED -> FAILED
READY + same contract -> READY
READY/FAILED + different contract -> fatal conflict
```

It never marks a failed load as an empty optional curriculum, and it never
publishes a partial bank.

The process-global identity tuple is exact:

- compiled contract-identity string;
- numeric kind;
- BBS, training-contract, and producer-manifest SHA-256 values;
- producer- and loader-engine SHA-256 values;
- byte/count/header fields; and
- exact byte strings for the BBS, training-contract, and producer-manifest
  paths.

Paths are routing identity, not scientific lineage, but changing a path after
the first require is conservatively treated as a different process-local
request even when content hashes match. The wrapper copies every path into
bounded owned storage before returning; it never retains `argv`, environment,
or test-buffer pointers. `FAILED + same request` repeats the stored fatal
reason without retry. Different requests report an identity conflict.

All vector/scalar binding loads occur before workers are returned. A C11
atomic-flag lock also serializes the lazy standalone/direct-`c_reset` wrapper,
so concurrent first resets cannot race the status, arrays, or owned identity.
The pure candidate seam itself is caller-owned and reentrant.

Hard resource limits:

- maximum BBS bytes: 256 MiB (the historical strict-analysis bank is about
  35 MiB, while the loader transiently owns both raw and aligned copies);
- maximum records: 1,000,000;
- maximum training-contract bytes: 4 MiB;
- maximum producer-manifest bytes: 4 MiB; and
- maximum path bytes including NUL: 4,096.

Every input is opened without following a final symlink where the platform
supports it, verified from the same descriptor as a regular file, and bounded
before allocation. `SIZE_MAX`, `INT_MAX`, record-size multiplication, and
header-plus-body addition are checked independently. Tests hit declared values
at, below, and above each boundary without allocating the maximum file.

Required load sequence:

1. Validate the compiled contract is complete and matches the environment's
   requested kind.
2. Reject reserved authored kind unconditionally in production.
3. Open the training contract once, hash its exact bounded bytes, require exact
   EOF, and compare with the compiled training-contract pin.
4. Do the same for the exact producer manifest and its independent pin.
5. Open the BBS file once.
6. Require the compiled positive byte and record bounds before allocation.
7. Read exactly the expected BBS bytes into one temporary buffer, reject short
   read or trailing growth, and hash those exact bytes.
8. Compare the exact BBS SHA-256 before interpreting raw matches.
9. Validate BBS magic/version/match-size/fingerprint against both the compiled
   contract and current engine.
10. Reconcile exact file length and record count with overflow-safe arithmetic.
11. Parse metadata sequentially from that same immutable buffer.
12. `memcpy` each raw match into aligned temporary `bb_match` storage before
    validation; never cast the BBS record offset (28 modulo typical alignment)
    to `bb_match*`.
13. Validate every metadata row and aligned raw `bb_match`.
14. Generate legal actions into a bounded `BB_LEGAL_MAX` buffer for every
    admitted match and require a positive, in-range count. A decision-status
    stack with no legal surface is not publishable.
15. Populate temporary metadata and match arrays without compaction.
16. Publish both arrays, count, kind, and exact identity only after all records
    pass.
17. Emit one bounded startup line with kind, all three artifact hashes, and
    count.

Kind checks:

- strict replay requires a positive source ID outside the reserved `0xA...`
  authored namespace and requires `bb_state_bank_boundary_valid()`;
- authored scenario is reserved and rejected in production;
- the test-only candidate seam may structurally exercise authored records, but
  cannot publish globals or satisfy installer/launch authority;
- metadata half/turn/padding and match half/active-turn reconciliation remain
  mandatory;
- `cmd` is preserved as provenance, not interpreted as an action label.

The loader keeps:

```c
typedef struct {
    uint32_t source_id;
    uint32_t command;
    uint8_t half;
    uint8_t turn;
} bbe_state_bank_meta;
```

No action recommendation, replay outcome, scenario class, split, or weight is
introduced.

After an authorized uniform draw, the copied record must still be a live
decision with a nonempty stack. Any impossible post-load violation aborts as
memory/invariant corruption. The current “increment `demo_fallbacks` and
procgen” branch is removed. The only legitimate procedural reset when a valid
bank contract is active is the explicit probability draw that chooses the
nonbank path.

`c_reset` invokes a stored-field curriculum validator before `bbe_reset_match`,
so direct C callers cannot bypass finite/range/mutual-exclusion/kind checks.
Binding entry points additionally validate original raw doubles before casts.
For standalone `--demo`, the driver explicitly initializes
`exclude_team`, `force_home_team`, and `force_away_team` to `-1`; it does not
change those static-zero defaults for ordinary FNV mode.

## SHA-256 contract

Add a small dependency-free implementation used only for input integrity.
Tests use independent literal vectors, including at least:

- empty input;
- `"abc"`;
- a multi-block standard vector;
- incremental chunk boundaries around 55/56/63/64/65 bytes; and
- one fixture BBS digest computed with Python `hashlib`, recorded as a literal.

The tests must not obtain their expected digest from the production C
implementation.

## Installer contract

Exact installed targets are:

```text
resources/bloodbowl/state_bank.bbs
resources/bloodbowl/state_bank.producer.json
resources/bloodbowl/state_bank.contract.json
ocean/bloodbowl/state_bank_build.h
src/exact_action_build_hash.h
```

The generated authority contains those three literal default resource paths.
The production process identity compares the exact effective byte strings
after any standalone override; it does not call `realpath` or silently collapse
aliases.

Reserved bank-argument form:

```text
tools/install_puffer_env.sh \
  --state-bank-kind strict-replay \
  --state-bank /absolute/or/repo/path/state_bank.bbs \
  --state-bank-sha256 <reviewed-bank-sha256> \
  --state-bank-producer-manifest /path/producer.manifest.json \
  --state-bank-producer-manifest-sha256 <reviewed-producer-sha256> \
  --state-bank-contract /path/training.contract.json \
  --state-bank-contract-sha256 <reviewed-training-contract-sha256> \
  [path-to-pufferlib]
```

All seven bank arguments are all-or-none. In this tranche, a complete set is
read and validated through producer authorization, then always fails with
`NO_AUTHORIZED_PRODUCER` because the production producer-kind allowlist is
empty. `--check` accepts no source bank arguments and validates the installed
no-bank transaction plus compiled module. There is no production
bank-installed success state in this tranche.

Install with no bank arguments means an explicit no-bank build:

- remove only the exact known staged bank/producer/contract targets;
- publish the generated no-bank header last;
- never inspect or copy `validation/states/bank.bbs`;
- never preserve a stale staged transaction.

Reserved future bank transaction, with the implemented prefix used to prove
fail-closed producer rejection:

1. Read the bank, complete producer manifest, and complete training contract
   into separately bounded immutable bytes.
2. Compare all three externally supplied pins.
3. Strictly validate the closed common producer envelope and reject any
   duplicate, missing, unknown, or producer-specific key.
4. Strictly validate the complete training contract and reconcile every
   duplicated value.
5. Look up producer `kind` in the production authorization allowlist. In this
   tranche the set is empty, so return `NO_AUTHORIZED_PRODUCER` here and do not
   create any destination temporary or mutate installed state.

The following transaction suffix is specified now but remains unreachable
production code until a later reviewed tranche defines and authorizes one
literal from-source producer kind:

6. Require a training-eligible strict-replay training role, non-null producer
   engine identity, and current loader engine identity.
7. Validate BBS header, bytes, count, metadata namespace, and bounds in Python.
8. Invoke a freshly current engine-linked `state_bank_validate` helper with the
   same external pins. It uses the production candidate loader and emits
   machine-readable exact count/header/namespace/structural/legal-action
   results. Python reconciles its output. The helper is rebuilt from the exact
   source/dependency graph for install; `--check` requires its binary newer
   than every dependency. Since both layers require the same content pins,
   a split-open mutation cannot make different bytes pass.
9. Create and fsync temporary destination files on the target filesystem.
10. Rehash destination temporaries.
11. Publish bank, producer manifest, and training contract, then fsync
    `resources/bloodbowl`.
12. Publish/fsync the deterministic ocean bridge, then fsync
    `ocean/bloodbowl`.
13. Publish the sole generated authority header last, then fsync `src`.

Publishing and durably syncing the single generated authority last ensures an
interrupted install cannot authorize an incomplete new transaction. An older
authority paired with changed/missing data fails closed; a new authority is
never durably published before its exact data and include bridge. No-bank
install removes the three exact data files, fsyncs the resource directory,
publishes/fsyncs the bridge, then publishes/fsyncs the no-bank authority.
Failure/crash injection tests cover every publication and directory-fsync
boundary.

The shared Python validator owns manifest parsing and the fail-closed
authorization decision so the installer and launcher cannot drift into
separate schema interpretations. Transaction-suffix code is exercised in this
tranche only by a private unit-test collaborator passed directly to the shared
staging function; it is not reachable from the production CLI, environment,
configuration, or generated contract. The public installer always uses the
empty immutable allowlist.

`--check` requires:

- a revised snapshot hash that excludes exactly `.content_hash` and the
  out-of-band `state_bank_build.h`, recomputes both the repository source tree
  and installed snapshot, and requires
  `root == installed == recorded == compiled_environment_source`;
- installed config identity;
- exact no-bank state: no staged bank/producer/contract, no-bank authority, and
  no-bank bridge;
- current engine-source identity;
- current module newer than the environment snapshot and both generated
  headers;
- every compiled `_C` contract field exactly equal to both headers and live
  files;
- installed standalone machine metadata exactly equal to the same values; and
- all existing exact-action/observation/backend checks.

## Launcher and run-manifest contract

When `LADDER_RESET_PCT > 0`, `tools/run_reward_ablation.sh` requires, rather
than derives:

```text
LADDER_STATE_BANK_KIND
EXPECTED_LADDER_STATE_BANK_SHA256
EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256
EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256
```

The shared validator compares those values with the generated compiled
contract and staged bytes before any expensive preflight. The C runtime
independently rechecks the same exact bytes at initialization, closing the
launcher-to-runtime mutation window.

The command adds `--env.state-bank-kind 1`. Authored value 2 is never emitted.

The run manifest records:

```text
ladder_state_bank_contract_schema
ladder_state_bank_producer_schema
ladder_state_bank_kind
ladder_state_bank_ruleset
ladder_state_bank_sha256
ladder_state_bank_producer_manifest_sha256
ladder_state_bank_contract_sha256
ladder_state_bank_producer_engine_source_sha256
ladder_state_bank_loader_engine_source_sha256
ladder_state_bank_records
ladder_state_bank_bytes
```

For reset percentage zero, the exact inactive values and JSON scalar types are:

| Field | Exact value |
|---|---|
| contract schema | string `"none"` |
| producer schema | string `"none"` |
| kind | string `"none"` |
| ruleset | string `"none"` |
| BBS SHA | string `"unused"` |
| producer-manifest SHA | string `"unused"` |
| training-contract SHA | string `"unused"` |
| producer-engine SHA | string `"unused"` |
| loader-engine SHA | string `"unused"` |
| records | integer `0` |
| bytes | integer `0` |

No expected bank variables are permitted or required for the inactive form.

The launcher must never assign an expected digest from an observed file. The
complete run manifest is SHA-bound into checkpoint lineage, and this tranche
also updates `checkpoint_lineage.py` to validate the conditional field set
before minting lineage:

- positive reset percentage requires every active field, exact types, schemas,
  hashes, kind, positive bytes/counts, and internal reconciliation;
- zero reset percentage requires the complete inactive table above;
- a legacy/banked manifest missing the fields cannot mint lineage;
- deleting or mutating any field is a focused negative test.

No checkpoint-lineage schema bump is needed because the sidecar already commits
to the complete producer run-manifest SHA.

Every current bank-positive/raw-copy entry point has an explicit disposition:

- `tools/run_reward_ablation.sh`: migrate to the shared validator and required
  external pins; uniform resets only until pre-indexing;
- `tools/launch_ladder_canary.sh` and `tools/launch_ladder_rung.sh`: remove
  observed-hash printing, require/pass the external pins, and fail at the
  selector bridge before invoking Puffer until the next tranche;
- `tools/run_synthesis_c.sh` and `tools/run_native_asym.sh`: historical
  hard-coded positive-reset launchers; fail before `puffer` with a typed-bank
  migration diagnostic rather than using their raw size/presence checks;
- `tools/setup_arm.sh`: stop copying a raw BBS alone; no bank transfer occurs
  without the complete three-artifact transaction and explicit pins;
- `tools/fleet.sh` and `tools/gpu_box_setup.sh`: no implicit resource bank is
  authoritative; installation with no bank clears exact staged targets;
- `puffer/config/bloodbowl.ini`, `validation/README.md`, `CLAUDE.md`, and
  `docs/drills-design.md`: remove silent-fallback/implicit-stage guidance and
  describe the analysis-only and disabled-selector boundaries; and
- `validation/build_state_bank.py`: remains an analysis/raw builder and is
  explicitly documented as unable to produce a training contract.

Source/behavior tests enumerate those files and prove every positive-reset
launcher either supplies kind plus all three external pins through the shared
validator or exits before the `puffer` command. Runtime validation remains the
final backstop for direct `puffer train`, `puffer sweep`, or an unenumerated
caller.

The installed Puffer standalone keeps path overrides only as location
overrides:
`--demo --bank-kind strict-replay --bank <path>
--bank-producer-manifest <path> --bank-contract <path>` is all-or-nothing and
must still match the digests compiled into that executable. Supplying a path
never supplies or replaces authority. Repository-native standalone builds use
the tracked no-bank header and cannot enable demo mode.

## Watched-fail tests before production edits

The first edit after plan approval is tests only. At minimum, capture these
failures against the base:

### 1. Missing required bank reaches procgen

In `test_state_bank.c`, fork a child, configure `demo_reset_pct=1`, point the
current loader at a nonexistent path, and call real `c_reset`.

Expected contract: child aborts before a match/observation exists.

Base watched result: child exits normally with `demo_started=0` after a
procedural kickoff.

This base-observable test uses only existing globals/API. After the refactor, a
second fixture-authorized child test supplies a complete strict test request
and asserts the stable `BANK_OPEN` failure reason, so an earlier
compiled-`NONE` or missing-kind abort cannot make the regression pass
vacuously.

### 2. Mixed valid/invalid file is compacted

Write a two-record BBS with one valid boundary and one invalid metadata or
structural record.

Expected contract: zero records are committed and required startup aborts.

Base watched result: `bbe_state_bank_n == 1`; the valid subset is published.

After the refactor, the same two-record bytes are passed to the pure candidate
loader under an otherwise valid strict test request. It must return the exact
record-validation reason and leave caller output empty.

### 3. Selector miss is reported as a banked success

Write one valid boundary that cannot satisfy a nonzero endzone selector,
configure reset percentage one, and call real reset in a child.

Expected bridge contract: abort with the pre-index requirement.

Base watched result: the sole nonqualifying state is selected after 256 misses,
`demo_started == 1`, and fallback telemetry remains zero.

After the refactor, a fully authorized test fixture reaches
configuration/reset and asserts the exact `INDEXED_STRATA_REQUIRED` diagnostic;
compiled kind, loaded bank, and requested kind are asserted valid first.

### 4. Launcher invents its expected digest

Add a precise source test requiring caller-supplied expected BBS,
producer-manifest, and training-contract pins whenever reset percentage is
positive.

Expected contract: staged data without external expected pins is rejected.

Base watched result: the source assigns
`LADDER_STATE_BANK_SHA256="$(sha256sum ...)"`. The watched assertion targets
that exact current-hash-to-authority assignment and does not depend on a bank
being present.

### 5. Installer has an implicit edition-blind source

Add an exact installer-source test requiring no-bank install semantics and
all-or-none explicit bank arguments.

Expected contract: no code path references the ambiguous default bank.

Base watched result: the source contains the exact
`validation/states/bank.bbs` conditional and copy block. This red does not
require a fake Puffer tree whose unrelated patch preflights could mask it.

The watched-fail log must show the assertion and current behavior, not only a
compile error for a not-yet-created API.

## Complete focused test matrix

### Manifest and shared-validator negatives

- absent bank, producer manifest, or training contract;
- malformed JSON, duplicate JSON keys, and missing or unknown keys at every
  recognized level;
- unknown training, producer, authorization schema, role, kind, or ruleset;
- an `analysis-only` or `structural-proof` producer manifest requested directly
  for training;
- absent/null producer-engine identity;
- producer-engine identity falsely replaced with the current loader identity;
- loader-engine identity different from current source;
- mismatch between producer output and training-contract bank fields;
- unknown or unvalidated producer-specific top-level fields;
- the current authored-proof producer/token presented as a training bank;
- any authored-scenario training contract, even with A-namespace bytes and
  external pins;
- uppercase, short, long, or nonhex SHA;
- wrong external producer, training-contract, or bank SHA;
- wrong BBS bytes, count, magic, version, match size, or fingerprint;
- zero records, partial record, and trailing data;
- strict metadata containing an authored source ID;
- source or staged destination mutation during validation;
- injected failure at every data/header publication and directory-fsync
  boundary leaves no newly accepted contract.

### Runtime negatives

- requested bank with compiled kind none;
- env kind missing, fractional, unknown, or different from compiled kind;
- reserved authored kind;
- missing producer manifest, training contract, or bank;
- producer, contract, or bank content mutation after launcher validation;
- short producer/contract read, short BBS read, and trailing BBS growth;
- wrong compiled bytes/count/header contract;
- exact/under/over manifest, bank-byte, record, path, `SIZE_MAX`, and `INT_MAX`
  resource boundaries;
- zero source ID, nonzero padding, bad half/turn, or match mismatch;
- one invalid record in an otherwise valid bank rejects all;
- strict bank containing an authored-only nested Dodge state;
- second process-local initialization with different kind/hash/path identity;
- same request after failure repeats the stable reason and does not retry;
- concurrent first require calls cannot race or double-publish;
- unaligned BBS record offsets are copied to aligned match storage before
  access;
- selector with zero reset percentage;
- bank kind with zero reset percentage;
- bank with forced/excluded team constraints;
- nonzero selector rejected by the temporary bridge.

Every required-load failure leaves no published arrays and terminates startup.

### Runtime successes

- valid small strict fixture loads exact order, metadata, and match bytes;
- authored proof bytes may be structurally checked only through the
  nonproduction candidate/engine seam and can never publish production globals;
- same process-local contract is idempotently reusable;
- multiple environments share immutable records without cross-env mutation;
- reset percentage one with uniform selection always sets `demo_started`;
- reset percentage zero/kind none never opens the bank, even if stale files
  physically exist;
- default procgen trajectory remains deterministic.

### Configuration, installer, launcher, and provenance

- raw-double and stored-field finite/integral/range/mutual-exclusion cases,
  including positive-to-zero float underflow and NaN/fractional forced-team
  sentinels;
- explicit no-bank install removes only stale exact targets;
- incomplete bank arguments fail before artifact I/O;
- complete correctly pinned/schematized bank arguments fail with
  `NO_AUTHORIZED_PRODUCER` and leave the installed no-bank transaction
  byte-identical;
- the isolated staging-function collaborator proves the future transaction
  suffix without adding a production CLI/configuration bypass;
- no-bank `--check` succeeds and any staged bank artifact fails;
- wrong source pin cannot become authorized by being observed;
- isolated staged bank/producer/contract temporaries are byte-identical to
  their fixture source before publication;
- module predating the generated bank header fails;
- any single exported module/standalone contract-field mismatch fails;
- primary launcher emits the numeric env kind and all run-manifest fields;
- zero-reset launcher emits the canonical inactive form;
- checkpoint lineage rejects every missing, wrongly typed, or mutated active
  bank field and every noncanonical inactive value;
- every enumerated legacy launcher/transfer path is migrated or stops before
  `puffer`;
- shell syntax and source-level tests prove no current-hash-to-expected
  assignment remains.

## Validation gates

After implementation and review:

1. Focused optimized C state-bank/SHA tests.
2. Focused ASan/UBSan C state-bank/SHA tests.
3. Full optimized engine, Puffer reward, contact-bot, state-bank, observation,
   and BBP writer suites.
4. The same full native suite under ASan/UBSan.
5. Full Python tools tests, including strict filter, installer helper, launcher,
   reward manifests, generated contracts, and existing lineage tests.
6. Shell syntax, generated-source checks, static analysis, and
   `git diff --check`.
7. Explicit no-bank clean install into the pinned Puffer tree, rebuild,
   `--check`, module import, and installed standalone
   `--state-bank-contract` metadata.
8. Run the immutable generated-header native integration binary twice: valid
   strict uniform reset produces identical start identity, every requested
   reset is banked, and fallback is zero.
9. Mutate the immutable integration fixture's BBS, producer manifest, and
   training contract independently; prove the production require wrapper
   rejects each at the exact stage.
10. Prove a complete, correctly pinned production bank invocation returns
    `NO_AUTHORIZED_PRODUCER`, creates no destination temporary, and leaves a
    prior no-bank installation byte-identical. Separately exercise the dormant
    transaction suffix through a private staging-function test collaborator;
    prove that no CLI option, environment variable, generated header, or
    runtime configuration can select that collaborator. There is no positive
    production Puffer bank install/demo gate in this tranche because no current
    artifact has qualifying producer-engine provenance.
11. Default seed-42, 100-episode FNV twice. With reset percentage zero it must
    remain `ea1d720e69f5a491`, 26,251 steps, and zero illegal actions.
12. Record exact Puffer commit, source, bank contract, backend, module,
    standalone, and deterministic hashes.

## Version and lineage decision

- BBS remains `BBS1` version 1.
- `bb_match`, engine fingerprint algorithm, observation v6/2782, action
  exact-joint-v1, BBP v6, reward semantics, and checkpoint bytes do not change.
- Add `bloodbowl-strict-filter-manifest-v2`,
  `bloodbowl-state-bank-producer-v1`,
  `bloodbowl-state-bank-training-contract-v1`, and
  `bloodbowl-state-bank-authorization-v1`.
- Production producer-kind authorization is explicitly empty; the only fixture
  token is `test-strict-fixture-v1`, scoped to the native integration/test
  collaborator and rejected by production.
- No observation, action, BBS, BBP, or checkpoint-lineage schema bump.
- Environment source and compiled module/standalone hashes change.
- Exact-action semantics remain unchanged, but the backend source digest must
  change because the compiled contract exports edit both `src/bindings.cu` and
  `src/bindings_cpu.cpp`, which are inside `exact_backend_hash()`'s closure.
  Recompute and re-record that digest in every affected manifest, generated
  source assertion, and test; do not weaken or normalize the hash to preserve
  its previous value.
- An analysis-only refilter of the existing strict BBS should retain
  `bcd9daf55ac5d177f48160092f17a9b4978da877455b830ba33a9c1b5ba84d22`;
  its filter-manifest digest changes, but it remains unpromotable because its
  original producer-engine identity is unknown.
- Legacy noncurriculum runs remain compatible.
- Legacy raw-bank curriculum launches are intentionally incompatible.
- Existing artifacts are never silently relabeled, overwritten, or staged.

## Required adversarial review blockers

The plan is not approved if any of the following remains:

- an “expected” digest is derived from the staged file;
- C can fall back to procgen after a requested-bank failure;
- a valid prefix/subset can be published;
- hashing and parsing use different opens or mutable byte streams;
- the authored proof can satisfy the training-bank contract;
- unchanged historical bytes can acquire a newly claimed producer-engine
  identity;
- opaque producer-specific claims are accepted without exact schema
  reconciliation;
- a non-indexed selector remains live during the bridge;
- only the shell launcher validates the contract;
- an install with no bank can retain an old authorized transaction;
- a second process-local request can silently inherit a different contract;
- NaN/fractional/out-of-range state-bank config can bypass the gate;
- production require/reset behavior is tested only through mutable globals or a
  pure parser seam rather than the immutable generated-header integration
  binary;
- module/standalone compiled identity is inferred from mtime or strings rather
  than exported fields;
- a banked run can mint checkpoint lineage with missing/inconsistent contract
  fields;
- tests derive their hash oracle from the implementation under test;
- a format/observation/action bump is made without byte-layout need; or
- the tranche mutates or launches any active training asset.

After this plan receives explicit adversarial approval, implementation begins
with the watched-fail tests and advances only after their red behavior is
observed.

## Completion record — 2026-07-27

The tranche is complete. The final frozen-tree adversarial review reported
**CLEAN**, with no open P0, P1, or P2 finding. Kimi review was waived by the
user for this and all subsequent work. One accidental Kimi invocation was
terminated immediately, before it produced or supplied a review; none of its
output was used.

### Implemented contract

- The C loader consumes an exact compiled request and uses bounded,
  `O_NOFOLLOW`, same-open reads for the producer manifest, training contract,
  and BBS bytes. SHA-256, BBS header, exact length/count, metadata namespace,
  structural boundary, and legal-action checks all succeed before one
  immutable candidate is published.
- A requested bank can no longer become procedural fallback. Missing,
  malformed, mutated, partially valid, incompatible, or differently pinned
  requests fail startup. Process state is `UNTRIED`, `READY`, or `FAILED`;
  one exact failed request is stable and a different second request conflicts.
- Uniform reset sampling is unbiased. Nonzero legacy selectors stop at the
  explicit pre-indexed-strata bridge, so the old 256-attempt rejection loop
  cannot report a nonqualifying state as a banked success.
- The strict filter emits the closed v2 analysis manifest. Producer evidence
  and training authorization remain separate, and the production
  producer-kind allowlist is the literal empty set.
- No-bank installation is canonical and removes stale exact bank authority.
  The private future-bank collaborator publishes five files transactionally
  with authority last and rolls back every earlier publication on failure.
- Every Python publisher retains verified descriptors and inode identity,
  post-verifies exact destination bytes, and establishes a final no-follow
  pathname snapshot matching regular-file type, device, inode, size,
  `mtime_ns`, and `ctime_ns` from the post-hash descriptor snapshot. Failed
  transactions remove only their own inode and preserve a genuine competitor.
- Engine validation uses an immutable private snapshot of the exact engine
  source closure. The generated header, CPU/CUDA extension, and standalone
  expose and reconcile the same 20 state-bank contract fields.
- Primary launchers require external kind and three SHA-256 pins for an active
  bank, emit the canonical inactive form otherwise, and carry the complete
  identity into checkpoint lineage. Legacy launch paths stop before checkout,
  provisioning, or Puffer startup.
- Screen manifests, results, completion evidence, and analyzers use closed,
  deterministic, exclusively published contracts with exact cross-screen
  recomputation.
- Pinned PufferLib standalone builds now receive the required environment-root
  include path through the exact
  `training/puffer_standalone_env_include.patch`; installer application,
  reverse applicability, and drift checks cover the patch and `build.sh`.

### Review remediation

The implementation/review loop found and closed:

- caller-lifetime path ownership and malformed-request fingerprinting in C;
- modulo-biased uniform sampling;
- a validator that could otherwise inspect mutable live engine source;
- source swaps at hard-link and rename publication boundaries;
- post-link open failures that could leave transaction residue;
- rollback that could delete a competing destination;
- destination pathname replacement after descriptor verification;
- same-inode, same-size mutation during descriptor verification; and
- the pinned PufferLib standalone compiler's missing `-I"$SRC_DIR"`.

The remaining platform limit is explicit: portable hard-link/rename APIs
cannot prevent a same-user process from mutating an inode after the final
publication snapshot and before a later consumer opens it. Consumers still
validate the pinned bytes. Within each publisher, the final snapshot is the
documented publication linearization point.

### Validation evidence

- Watched failures were captured before implementation for missing-bank
  procedural fallback, valid-subset publication, selector miss, TOFU launcher
  authority, and implicit installer staging.
- Full Python tools suite: **316 passed, 2 expected skips**.
- Training suite under the Puffer virtual environment: **95 passed,
  1 expected skip**.
- Focused final publication/adversarial suite: **173 passed,
  3 expected skips**.
- Optimized native suite: **618 named tests passed**, plus the BBP writer and
  standalone argument/contract gates.
- ASan/UBSan native suite: the same **618 named tests passed**, with no
  sanitizer diagnostic.
- Generated-header integration: **14/14 cases passed twice**, including
  singular concurrent publication and exact independent mutation rejection
  for the BBS, producer manifest, and training contract.
- Default seed-42 standalone, twice at 100 episodes:
  FNV `ea1d720e69f5a491`, 26,251 steps, and `illegal_frac 0.0000`.
- Relevant Python files pass `ruff check` and `py_compile`; the eight
  publication/contract files also pass `ruff format --check`. Modified shell
  scripts pass `bash -n` and `shellcheck --severity=warning`.
  `git diff --check` passes.
- A build under an absolute external build path passed the full native matrix.
- A fresh exact-pin PufferLib install at
  `9836f0d2e78889c1aaf189c04d161b6fc61a9386` passed the CPU extension build,
  `./build.sh bloodbowl --fast`, installer `--check`, all 20 no-bank field
  comparisons, and the installed standalone FNV gate. The Apple Silicon host
  required only an isolated clone-local compiler/OpenMP platform shim; that
  shim is not repository content.

Recorded identities:

- engine source:
  `0fc21a6b46f536e09b972299290e48f34aa290e7894bf113443cbb1c0c4d9bc6`;
- exact-action backend:
  `ed6f8cac77709b64c363eafd0d1f320f1fe9aab87342305b19d28ee719a232aa`;
- installed environment/drift identity:
  `f9ecefd331578e9243c8b4523107bbf4366b2d8d57d08a2883d2fc9f1d740bd1`;
- installed CPU module:
  `1806c34ae7d780ad8aed33800323e6fe58db9e95a8dd90cac4eeb7d076e9805d`;
- installed standalone:
  `5048c17fb88b5d425e8eed814f810c510272a6e15614ce9bd20dd4755847f980`;
- generated compiled-contract header:
  `361a310a02749b5a46fc5f1d07da69e8d9d46b109e8b8b1d24886a856c809a29`.
