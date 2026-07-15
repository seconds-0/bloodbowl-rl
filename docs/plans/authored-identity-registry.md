# Collision-audited authored identity registry

Status: corrected implementation plan; no sidecar, publication, training, or
deployment authorization.

## Objective and dependency

Define stable semantic identities for the 26 recipes in the fixed authored
proof bundle before any JSON sidecar can use them as join keys. Preserve the
existing proof-local `0xA9000000 + index` BBS bytes exactly. This tranche adds
an append-only allocation ledger, fixed-proof mapper, and validators only; it
does not publish a canonical bank.

`docs/RECOMMENDED_ORDER.md` is absent. The live fallback order is the authored
bank plan plus D207/D208: compose the proof, centralize its construction, then
settle template/revision/cell/variant identity before sidecar schemas or
manifest-last publication. PR #41 merged the builder as
`ca971ca201f9502f4a7317a405a6fdd3d0fe3a5c`, so identity is now the smallest
unblocked dependency.

## Identity boundary

An identity names an immutable authored recipe specification under the current
compiled template semantics. It is not a tactical label and not a promise that
raw `bb_match` bytes or transcripts are engine-version independent. Raw-state
SHA-256, transcript hashes, engine tree, ABI fingerprint, compiler identity,
and build provenance remain separate future sidecar/manifest fields.

The identity-defining configuration projection contains every field that
drives discovery:

- procgen seed and stream;
- game seed and stream;
- controller seed and stream;
- recipe kind and every applicable semantic axis request;
- home, away, and excluded teams; and
- every `bb_procgen_params` field.

Integer fields compare at their declared full width. Floating configuration
fields compare by exact object bits through `memcpy` to the matching unsigned
width, not by arithmetic equality, so `+0.0f` and `-0.0f` are distinct durable
configurations while NaN remains invalid under the existing range gate. The
ledger, pure matcher, serializer, and mutation tests use the same rule.

Initialized/captured matches, action and dice transcripts, decision-team
transcripts, their counts, and unused transcript storage are not matcher
fields. The existing writer remains responsible for rediscovery, exact replay,
and complete provenance equality. Tests must prove both sides: changing any
configuration-projection field rejects identity, while changing only
initialized bytes or unused transcript storage preserves semantic identity but
is still rejected by the writer's provenance gate.

## Normalized append-only model

Use three distinct structures so durable allocation, recipe semantics, and
legacy proof order cannot silently redefine one another.

### 1. Template allocation table

Each template receives an immutable nonzero `uint32_t template_id`, one
immutable canonical key, and one permitted revision-1 recipe kind. Initial
allocations are:

| ID | canonical key | permitted recipe kind |
|---:|---|---|
| 1 | `f1-pass-carrier-pressure` | `AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE` |
| 2 | `f2-handoff-target-count` | `AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT` |
| 3 | `f3-second-half-turn` | `AD_RECIPE_F3_EXACT_SECOND_HALF_TURN` |
| 4 | `f4-pending-dodge-reroll` | `AD_RECIPE_F4_PENDING_DODGE_REROLL` |
| 5 | `f5-score-or-wait` | `AD_RECIPE_F5_SCORE_OR_WAIT` |

Keys are NUL-terminated ASCII slugs, 1-63 bytes before the terminator, matching
`[a-z][a-z0-9-]*`, compared bytewise without locale. One ID maps to exactly one
key and one key maps to exactly one ID. Repetition through variants is normal
because variants store only the numeric template ID. Allocated keys are never
renamed or recycled; aliases are a future separately reviewed concern.

### 2. Global recipe-allocation ledger

The schema-1 checked-in ledger contains exactly the initial 26 assigned,
immutable semantic allocations. Every row owns:

- an immutable opaque 32-bit authored source ID;
- template ID;
- positive template-wide recipe revision;
- positive stable semantic cell ID;
- positive concrete variant ID;
- exact `uint64_t` variant/controller seed;
- the complete configuration projection above.

Reserve top byte `0xAE` for durable authored source allocations. The low 24
bits are an opaque nonzero allocation ordinal, initially `1..26`. Source IDs
are therefore `0xAE000001..0xAE00001A`; semantic fields are not truncated or
packed into this compatibility field. Allocation ordinals are strictly
contiguous and increasing in ledger order: the only valid next allocation
after `N` is `N+1`; gaps are not backfilled or silently reserved. All
`0x00FFFFFF` ordinals are globally
append-only across identity-schema versions. Source-ID equality alone denotes
the same immutable allocation forever; schema changes may add fields or
strengthen validation but may not reinterpret or reuse an AE value. Exhaustion
fails closed and requires a separately reviewed successor namespace or BBS
format—never wrapping, hashing, recycling, or consuming recipe revision as
overflow space.

The current initial ledger has five templates at recipe revision 1. Cell IDs
name semantic axis cells and may be shared by multiple seeded variants.
Variant IDs name concrete recipe instances and are unique within a template
revision; adding another seed to an existing cell allocates a new variant ID
and source ID without changing the old row.

The initial allocations are explicit rather than derived from proof position:

| source ordinals | template | cells / variants | controller seeds |
|---|---:|---|---|
| 1-4 | 1 | 1-4: Home/open, Home/marked, Away/open, Away/marked | 4, 2, 10, 8 |
| 5-8 | 2 | 1-4: Home/one, Home/two-plus, Away/one, Away/two-plus | 4, 2, 8, 13 |
| 9-24 | 3 | 1-8: Home turns 1-8; 9-16: Away turns 1-8 | 1000-1015 |
| 25 | 4 | cell 1, variant 1 | 1 |
| 26 | 5 | cell 1, variant 1 | 410 |

For the initial rows, variant IDs equal their listed cell IDs; that is an
allocation fact, not a derivation rule. A second seed in an existing cell gets
the next unused variant ID for that template revision. Every initial row uses
the exact common configuration: procgen seed/stream `0xA1170EED/17`, game
seed/stream `0xD11CE5/23`, controller stream `31`, Home/Away/excluded teams
`0/1/-1`, and procgen parameters `{4, 2, 0.0f}`. All inapplicable axis fields
are canonical zero.

Recipe revision is template-wide, but schema 1 and the present `ad_recipe`
representation can execute only revision 1 because neither the recipe nor
writer rediscovery carries a revision discriminator. The existing F1-F5
controllers, capture predicates, and kind dispatch are therefore permanent
revision-1 compatibility implementations for the fixed 26 recipes: they may be
refactored only when all six semantic recipe streams and the A9 whole/raw
artifact oracles remain unchanged.
Future controller, capture, axis-interpretation, or identity-semantics changes
must use new versioned functions/kinds or a separately reviewed revision-aware
recipe/compiler API that keeps revision 1 executable. The schema-1 ledger and
validator reject `recipe_revision != 1`; appending revision 2 is forbidden
until that later contract exists. Engine-only raw/transcript drift remains
future artifact provenance; it cannot silently change the frozen compatibility
builder or pass this tranche's permanent oracle.

No schema-1 row beyond the initial 26 may be allocated. A new cell, seed,
template, or revision requires the separately reviewed general row compiler to
prove discovery, exact replay, independent rediscovery, recipe-specific capture
and raw-state admission, one-action continuation where applicable, and a frozen
per-allocation oracle before its source ID becomes immutable. A versioned
replacement kind cannot enter an existing revision-1 template; it requires a
new template or the later revision-aware contract.

For each template revision, the cell projection is exactly recipe kind plus
all semantic axis fields, including canonical zero for every inapplicable axis.
Seeds, streams, teams, and procgen parameters are concrete-variant configuration,
not cell fields. The ledger validator enforces both directions:

- `(template, cell_id)` maps to exactly one cell projection across the complete
  ledger, and within each template revision one cell projection maps to exactly
  one cell ID;
- `(template, revision, variant_id)` maps to exactly one cell and one complete
  configuration projection;
- `variant_seed` equals the configuration's controller seed; and
- across the complete schema-1 ledger, two source IDs may not carry identical
  executable configuration projections, even under different templates.

Multiple variants may share a cell only when their cell projections are equal
and their complete configurations differ in an explicitly variant-defining
field. For schema 1 that field is controller seed only: rows sharing
`(template, revision, cell_id)` must be byte/field-equal in every other
configuration field, and their controller seeds must differ. Expanding
variant-defining fields or adding executable revisions requires the later
reviewed revision-aware identity/compiler contract.

The fixed-proof mapper identifies only recipes produced by the immutable
26-entry legacy schedule. It does not infer historical or future revisions
from an `ad_recipe` that contains no explicit revision discriminator. Future
compiler/currentness/lifecycle policy must use a separate schedule and API; it
must never reinterpret old allocations through this fixed matcher.

Because the schema-1 recipe API is revision-blind, template descriptors and
global executable uniqueness are enforced together. A row's recipe kind must
equal the immutable permitted revision-1 kind in its template descriptor, and
no complete executable configuration may be allocated twice by changing only
template ID, cell ID, variant ID, or source ID. Synthetic validation must reject
an F2 configuration under the F1 template, a template whose rows disagree with
its permitted kind, and the same complete configuration copied under another
template.

### 3. Frozen legacy proof schedule

A separate immutable 26-element array lists durable source IDs in the exact
legacy A9 proof order: four F1, four F2, sixteen F3, one F4, and one F5. The
builder resolves each reference through the ledger, builds from that row's
single configuration projection, and emits `0xA9000000 + proof_slot` exactly as
today. Ledger insertion, sorting, or future expansion cannot
implicitly enter or reorder this schedule.

Validation requires all 26 schedule references to resolve to assigned,
pairwise-distinct rows with exact 4/4/16/1/1 composition. The ledger is the
sole owner of semantic configuration; the schedule owns only the unavoidable
positional compatibility order. `ad_build_authored_proof_bundle` permanently
uses this schedule and remains the legacy-A9 preservation builder.

### Mechanical append-only enforcement

`tools/authored_identity_ledger.def` is the machine-readable source of truth
for template and allocation rows. C tables include it through typed macros; no
second hand-maintained runtime table exists. Under schema 1 the complete file
is byte-immutable after its initial merge; even an otherwise valid suffix is
rejected until the general row-compiler contract explicitly changes that gate.
`tools/authored_identity_legacy_proof.def` contains the 26 schedule references
and is immutable after its initial merge. A dedicated
`tools/authored_recipe_oracle.json` owns the six stream magics, lengths and
SHA-256 values, the 2,141-byte match width, and the complete recursive
declaration/stream/matcher classification manifest, plus the immutable direct
gate-corpus schemas, counts, and result digests. The declaration authority
includes the public `ad_authored_identity` field order/types, while the trusted
probe statically binds schema/count/key-cap constants and both public function
signatures. It is byte-immutable under
schema 1 through the same authority check. Expected constants are read from
this one fixture rather than duplicated as editable test goldens. The fixture
also lists and hashes every file in the self-contained trusted verifier bundle:
outer history checker, compatibility runner, independent fieldwise serializer,
AST/assignment checker, matcher/writer/A9 probe, explicit production-source
allowlist, compiler/linker invocation and link-map checker, and authority
workflow. The bundle imports only the
Python standard library and invokes named system compiler/hash tools; it does
not delegate to a candidate Makefile, script, expected-output generator, or
prebuilt binary. Production code may be refactored only while the independent
bundle reproduces the immutable fixture exactly. Changing the fixture or bundle
requires the separately reviewed revision-aware contract.

A focused Python checker parses the three data files and verifier-bundle hash
map, validates their grammar and current invariants, and compares every
authority artifact with the exact target and every newly reachable candidate
commit. Once the registry exists on the authority, every candidate commit must
contain the byte-identical ledger, legacy schedule, oracle fixture, complete
verifier bundle, and authority workflow; missing files, edited verifier logic,
edited constants/manifests, transient mutations, and otherwise-valid suffixes
all fail. For the initial addition only, the exact target and merge base must
lack the complete authority set; the first candidate commit containing any
registry file must contain the complete final reviewed set and every later
candidate commit must retain those exact bytes. Earlier candidate-only commits
may omit the entire set. A stale branch whose merge base predates registry
introduction cannot claim that exception when the exact target already has any
authority artifact.

Blob equality alone is not semantic history validation. For later changes the
outer process extracts the complete verifier bundle from the exact target SHA,
checks every bundle hash against that target's immutable fixture, and copies it
outside all candidate worktrees. During the one-time initial addition, it uses
the exact final candidate-tip bundle whose bytes are frozen at the first
introduction commit and whose head is approved by hosted CI plus three
independent exact-head reviews. It never executes verifier code from the commit
being judged.

The authority runner creates an isolated temporary worktree for every newly
reachable commit from first introduction onward and passes that path only as
untrusted production source. Each commit is evaluated in a fresh pinned Linux
container with no checkout credential, secrets, or network; all capabilities
are dropped, privilege gain is disabled, candidate and authority trees are
read-only mounts, and only an ephemeral bounded `/tmp` is writable. The
candidate cannot rewrite a later worktree or the trusted bundle, and no
writable container state survives between commits. The trusted bundle
explicitly compiles the
allowlisted candidate engine, authored-builder, registry, and matcher sources
with its own harness and build invocation. Its independent serializer consumes
recipes returned directly by the candidate builder; its AST checker parses
candidate declarations; its matcher probe calls the candidate production
primitive/API; and its independent A9 encoder hashes the candidate builder
output. It validates the three schemas, all six streams, recursive
declaration/assignment coverage, production matcher, and A9 whole/raw artifacts.
Missing or extra source files, changed API/signature, build/dependency failure,
timeout, signal, malformed output, or nonzero result fails closed.

The same trusted runtime harness calls the candidate `ad_bbs_write` on canonical
candidate-builder records and requires its complete stream to equal the
independent A9 encoding. It then copies canonical inputs, applies one excluded-
provenance mutation at a time, and requires candidate-writer failure before byte
zero with every recipe/record input byte unchanged. Cases cover initialized
state; used and unused packed actions and decision-team bytes; used and unused
die sides and values; range-valid action/dice counts; a structurally admissible
captured-state field; controller seed; and record decision index. A mutation
that cannot remain structurally admissible is separately classified and must
still fail before output. This preserves writer rediscovery, exact replay,
decision-index binding, admission, and continuation across every reachable
commit rather than trusting canonical builder output alone.

Provenance failures occur before admission, so downstream gates receive their
own production-path tests. Refactor the writer's three downstream calls through
three internal external-linkage gateway functions—fresh-boundary admission,
nested/resumable admission, and one-action continuation—defined in a separate
tools translation unit and declared only in the internal tools header. Each
gateway is a trivial forwarder to the exact current production function. The
writer calls those symbols directly; there is no callback table, table-identity
branch, local/static duplicate, or alternate write path. This does not enlarge
the installed public API.

The trusted runner compiles candidate translation units separately with LTO and
cross-TU inlining disabled, then uses trusted GNU-linker `--wrap` interposition
for the three gateway symbols. Its wrappers count and order the actual public
`ad_bbs_write` path, forward to `__real_*` on success, or independently force
failure. The trusted AST/link-map checks require unresolved cross-object calls
from the writer to exactly these gateways, their separate candidate definitions
to contain exactly one return of the designated underlying call with every
argument forwarded positionally (including the continuation null arguments),
no direct writer call to the underlying admission or continuation functions,
and successful interposition of all three symbols. The writer AST also permits
exactly five `count` uses—null/zero validation, overflow validation, allocation,
the shared preflight loop, and the output loop—requires all three gateway calls
to share the preflight loop under only the exact kind/return conditions, and
rejects extra branches or loop transfers.
Changed linkage, a local shadow, direct-call bypass, production-only branch, or
missing relocation fails before runtime evidence is accepted.

Run this matrix separately for every one of the 26 canonical records, not only
one exemplar per boundary shape. Every F1/F2/F3/F5 record must call fresh
admission exactly once, never nested admission, then continuation exactly once;
the F4 record must call nested admission exactly once, never fresh admission,
then continuation exactly once. For first, middle, nested-F4, and final records,
independently forcing the applicable admission wrapper to fail in the complete
26-record batch must reject before byte zero without calling continuation.
Allowing admission but forcing continuation to fail at each of those positions
must also reject before byte zero. Trusted `fwrite` interposition requires all
52 successful admission/continuation calls to finish before the first write
callback and zero write callbacks for every forced failure.
Additively, every one of the 26 canonical records is written alone and must call
its admission plus continuation exactly once before the first write; independently
forcing either result for every one-record case must fail with zero writes.
Representative provenance mutations cover all five families, while controller
seed and record-index mutations cover every position. These count-one and
family/index matrices ensure the fixed-bundle evidence cannot hide a selective
ordinary-writer branch. Successful forwarding wrappers must reproduce the
unwrapped public writer's exact canonical bytes. Missing, duplicate, reversed,
wrong-kind, family-selective, or bypassed calls fail. Thus removing or reordering
either downstream block for any one family cannot hide behind canonical output,
earlier rediscovery rejection, or a spy-only code path.

Forwarding to a real function does not by itself preserve that function's
rejection semantics. The trusted bundle therefore owns an independent immutable
gate corpus and expected result-stream digests, generated before production
edits from the exact parent. It calls candidate
`bb_state_bank_boundary_valid`, `bb_state_bank_resumable_valid`, and
`ad_verify_one_action_continuation` directly, without candidate fixture helpers.
For all 26 canonical captured states it records both validator booleans and the
continuation return/error plus packed action, status, dice-used, and input-byte
preservation. It then repeats those calls for every one-bit flip of every raw
`bb_match` byte, including padding, in deterministic record/byte/bit order.

Single-bit locality is supplemented by an explicit multi-field adversarial
corpus copied into the immutable trusted bundle from the current exhaustive
fresh-boundary, pending-Dodge, and continuation tests. It covers stack depth and
parent frames, status/team/procedure/enum/skill bounds, grid/player
bidirectionality, ball states, pending destination/test metadata, reroll
availability, movement/flags, decision masks, and truncated/exhausted dice.
The oracle fixture pins corpus schema/counts and separate SHA-256 digests for
fresh admission, nested admission, and the complete continuation result tuples.
Candidate code never supplies expectations or filters cases. Canonical results,
every bit-flip result stream, every curated expected accept/reject, and unchanged
inputs must reproduce exactly. An always-true, weakened, broadened, narrowed, or
otherwise drifted underlying gate therefore fails even if canonical writer
bytes and interposed call counts remain unchanged.

The outer trusted process enforces at most 64 newly reachable commits, a
60-second process-group-killing deadline per commit, and a 900-second aggregate
deadline; a larger history must be rebased/squashed before review, never partly
sampled. Worktrees are removed after each run and the final candidate is tested
again normally. Candidate replacement with `exit 0`, hard-coded expected
hashes, skipped streams/AST/matcher checks, or a stub-directed Makefile cannot
affect this external evaluator.

CI checks out full history and explicitly fetches every event authority by SHA.
The required authority job is the hash-pinned workflow in the verifier bundle.
After the initial merge, pull requests run it from protected default-branch
context with read-only workflow permissions, no persisted checkout credential
or secrets, and the candidate checked out only as untrusted read-only container
source; candidate execution receives no network or ambient GitHub environment.
Merge-group and push executions first prove their workflow
bytes equal the exact target version. Repository rules require this authority
job, so a candidate workflow edit cannot replace or skip the gate. The one-time
bootstrap PR instead requires the exact candidate workflow/bundle plus ordinary
hosted CI and three independent exact-head reviews before its reviewed bytes
become the target trust root.

Pull-request and merge-group jobs use the immutable target SHA and enumerate all
commits reachable from the tested candidate/merge result but not that target.
Push-to-main uses `github.event.before` as the exact pre-push authority and
`github.event.after` as the candidate, fetches both, requires `before` to be a
nonzero ancestor of `after`, and enumerates every newly reachable commit. A
zero `before`, force push, missing object, non-ancestor update, or incomplete
range fails closed on protected main. The final commit's first parent and branch
merge base are optional supplemental assertions, never target authorities.
Registry PRs require an up-to-date exact base or merge queue, and target-branch
movement invalidates prior evidence before guarded merge. Synthetic graph tests
reject two concurrent ordinal-27 appenders, the stale pre-introduction branch,
a batched push whose first new commit mutates an immutable blob while its final
commit retains that mutation, a transient mutate-then-revert history, a changed
oracle hash/field classification paired with a matching serializer update, and
force/non-ancestor updates. A distinct semantic-history graph introduces the
exact immutable files, transiently changes a revision-1 controller, serializer,
matcher, writer rediscovery/provenance/admission/continuation gate, or classified
declaration without touching the fixture, then reverts
at the branch tip; the per-commit compatibility run must reject the otherwise
clean merge candidate. Variants simultaneously replace a candidate command with
`exit 0`, hard-code expected hashes, skip one stream, disable AST or matcher
execution, or redirect the candidate Makefile/build to stubs; the external
authority bundle must reject every intermediate commit. The initial addition
also requires the recorded 727-commit collision audit. This full
newly-reachable semantic-history check,
the C runtime validator, and exact semantic tests jointly enforce permanence;
editable final-snapshot tests alone are not claimed to prove append-only
history.

## Public contract and ABI

The public result is numeric and self-contained:

```c
#define AD_AUTHORED_IDENTITY_SCHEMA_VERSION 1u
#define AD_AUTHORED_TEMPLATE_KEY_CAP 64u

typedef struct {
    uint64_t variant_seed;
    uint32_t identity_schema_version;
    uint32_t source_id;
    uint32_t template_id;
    uint32_t recipe_revision;
    uint32_t cell_id;
    uint32_t variant_id;
} ad_authored_identity;

const char* ad_authored_template_key(uint32_t template_id);

int ad_identify_authored_proof_bundle(
    const ad_recipe* recipes, size_t recipe_count,
    ad_authored_identity* identities, size_t identity_capacity,
    char error[AD_ERROR_CAP]);
```

The key lookup returns an immutable process-lifetime pointer to a canonical
registry string, or `NULL` for an unknown ID. Callers compare result structs
field-by-field; no public contract depends on struct padding, pointer identity,
or raw `memcmp` of successful values. Future serializers must write fields
explicitly rather than dumping this ABI.

Recipe input, identity output, and error storage are required, suitably
aligned, and mutually disjoint. Both counts must equal
`AD_AUTHORED_PROOF_BUNDLE_COUNT`. On success, `identities[i]` identifies
`recipes[i]` and `error[0] == '\0'`; the input recipe array is unchanged. Any
failure leaves the complete caller identity array and recipe input
byte-for-byte unchanged. Disjointness is checked against the safely computed
greater of each supplied and fixed array extent before null/count diagnostics
or any other write to the error buffer; an extent overflow fails silently
before touching caller storage.

Identification first runs the existing safe composition gate. It then compares
every recipe's full configuration projection field-by-field against the
fixed-schedule ledger rows and requires an exact one-to-one mapping. It rejects
unknown, duplicate, missing, ambiguous, out-of-range, or mismatched rows. It
stages all 26 numeric identities and copies them to caller storage only after
complete validation. It never indexes from an unvalidated enum or axis value.
The immutable probe changes each defining configuration field through this
public API using a structurally valid alternate value where applicable, and
requires rejection plus byte-identical recipe input and identity output. For
kind, turn, active side, hand-off bucket, and carrier pressure it additionally
swaps the corresponding captured semantics between rows so the full 26-recipe
composition gate still succeeds; rejection must therefore come from exact
identity lookup rather than an earlier quota failure. Direct projection-helper
mutations remain additive evidence rather than a substitute.

Before implementation, audit record-construction contexts—not merely matching
hex literals—in the current tree, all advertised refs, and all reachable Git
history. Also search the exact decimal AE values and checked-in BBS artifacts.
The pre-code audit covered 727 reachable commits and found authored record
allocations only in the legacy A0-A5 fixture ranges and A9 proof range. No AE
source allocation, proposed decimal value, or hidden checked-in BBS allocation
exists. `0xA1170EED` is a procgen seed, demonstrating why contextual tracing is
required. Record the reproducible commands and final counts in D209.

## Permanent revision-1 recipe oracle

The exact parent at `ca971ca201f9502f4a7317a405a6fdd3d0fe3a5c` was probed
before registry implementation with a fieldwise serializer compiled both
optimized and under ASan/UBSan. Both builds produced identical values. The
implementation must check in the serializer and the single immutable oracle
fixture as a permanent CI regression gate; these are not one-time parent/head
evidence or regenerable goldens.

Every stream starts with its eight literal ASCII magic bytes followed by the
26-record count as unsigned little-endian 32-bit. Every record then starts with
its zero-based proof index as unsigned little-endian 32-bit. All remaining
integers are explicit little-endian fixed-width values; signed C integers are
converted modulo their stated unsigned width. The procgen float is its exact
32-bit object representation, pinned here to the current IEEE-754 ABI. No C
struct padding or pointer bytes enter any stream.

- Configuration, magic `ADCFG001`: the six seed/stream values as 64-bit,
  followed by kind, the four axes, three team selectors, two procgen integers,
  and the float bits as 32-bit values. Exact length 2,508; SHA-256
  `d4f7826c3e94038762bafdab119430c3727d1d696d1b41a7adbb02473d0c868f`.
- Used actions, magic `ADACT001`: action count as 32-bit, then each used packed
  action as 32-bit immediately followed by its decision-team byte. Exact
  length 44,315; SHA-256
  `62e7312c5bcc7b17a6d597501917e61f5f292bc077013f22bf443147884ed107`.
- Used dice, magic `ADDIE001`: dice count as 32-bit, then each used die side
  immediately followed by its value, both one byte. Exact length 5,662;
  SHA-256
  `33ff55efa7d219282b6d7b3410927c5036fb5dffb3e7604067d2ac72193eaa23`.
- Canonical unused transcript storage, magic `ADUNU001`: unused-action count as
  32-bit, each unused packed action plus decision-team byte, unused-die count
  as 32-bit, then each unused side/value pair. Exact length 1,441,731;
  SHA-256
  `016f7ea2b9c3655c9c29d6b772b095c31da47144be55d1c51b16c5233967d344`.
- Initialized matches, magic `ADINI001`: exact length 55,782; SHA-256
  `fa5b06eb32fc899fd395b4331508af07ef57c2fb09da3b869ac3b3eef512aba1`.
- Captured matches, magic `ADCAP001`: exact length 55,782; SHA-256
  `4cecac27c9fd768677bc530c739321db25df9bd45af190a70bf3a9507f33c6d8`.

Each canonical match record is exactly 2,141 bytes. It serializes all 32
players in slot order: three 64-bit skill words; the five signed stat bytes;
`x`, `y`, location, stance; 16-bit flags; moved, rushes, position, star,
niggling, SPP; 16-bit skill-reroll mask; Loner and Bloodlust. It then writes
the grid in `x`-major/`y`-minor order; ball state/x/y/carrier; half, turn,
score, active team, kicking team, weather; all reroll pools and one-turn action
flags; both entries of bribes, fan factor, cheer assists, surfs, apothecaries,
and coach-ejected; all 32 frames as proc/phase/a/b/x/y plus 16-bit data; stack
top, status, decision team, turnover, 16-bit return, 32-bit step count, both
team IDs, and both entries of the three completed-turn/held/turnover counters.
The serializer must statically or dynamically prove the 2,141-byte record
length. A focused declaration-coverage test must also derive the complete
`ad_recipe` semantic graph from Clang's AST and compare declaration order,
member name, canonical type, signedness, array extent, and recursive nesting
against the immutable fixture. The graph explicitly includes
`bb_procgen_params`, `bb_match`, `bb_player`, `bb_skillset`, `bb_ball`, and
`bb_frame`. Every scalar or array element is assigned exactly once by an
explicit rule to configuration, initialized state, captured state, used/unused
action plus decision-team transcript, used/unused dice transcript, or the two
transcript counts. The configuration assignments are also cross-checked against
the fields consumed by the production pure projection matcher. Compiler padding
is the only implicit exclusion. Any pointer or newly encountered aggregate
fails until a separately reviewed semantic ownership and serialization rule is
added; addresses are never serialized.

The fixture-to-AST checker must reject an added top-level recipe scalar or axis,
a new zero-valued procgen field, a changed transcript element type or
`AD_MAX_ACTIONS`/`AD_MAX_DICE` extent, and an added nested
match/player/skillset/ball/frame field. The manifest either drives emission or
is mechanically cross-checked against a per-field stream-assignment table; an
editable list that merely describes but does not bind the serializer is not
sufficient. These gates prevent a new semantic field from occupying ABI padding
or remaining zero in the fixed recipes while escaping both oracle and matcher.

The oracle freezes the semantic contents of the fixed 26 revision-1 recipes,
including canonical unused transcript storage, but deliberately excludes
compiler-dependent padding. Any hash, length, or per-record-width drift blocks
this tranche. It does not authorize additional revision-1 allocations or claim
compatibility for unregistered seeds; schema 1 forbids rows beyond these 26.

## Test-first implementation order

1. Add focused tests that fail to compile because the exact identity type,
   key lookup, and fixed-proof mapper are absent.
2. Add the `.def` ledger/schedule plus a pure internal validator over explicit
   template, allocation, and schedule arrays. Expose its descriptor types and
   validator only through an internal tools header so tests can supply
   synthetic tables without enlarging the installed public API. Pin exact key
   bytes/grammar and the ID-key-kind bijection. Reject a row whose recipe kind
   differs from its template descriptor, zero/unknown template IDs,
   revision other than 1, zero cell/variant, zero/out-of-range or noncontiguous
   AE ordinals, duplicate source IDs, duplicate `(template, revision, variant)`
   tuples, duplicate complete executable projections anywhere in schema 1,
   including across templates, broken
   cross-ledger `(template, cell)` projection stability or revision-local
   reverse bijections, same-cell differences outside controller seed,
   seed/config disagreement, and source decode/re-encode drift.
3. Pin all 26 fixed source IDs, template/revision/cell/variant values, seeds,
   and semantic configurations. Require legacy schedule references to resolve
   uniquely and reconcile exact 4/4/16/1/1 composition.
4. Add the mapper with copy-on-success staging. Exercise the complete
   `{0,25,26,27} x {0,25,26,27}` count matrix: skip only `26/26`; all other 15
   pairs fail and preserve the complete identity sentinel. Test null recipes,
   identities, and error storage separately.
5. Extract one pure internal field-by-field configuration-projection
   equality/lookup primitive and use that exact primitive in production
   matching. Test it directly with synthetic descriptors by changing every
   projection field independently: procgen/game/controller seeds and streams,
   teams/exclusion, every procgen parameter, recipe kind, every applicable
   axis, and every canonical-zero inapplicable axis. Every single-field change
   compares unequal even when it would make a complete public recipe invalid;
   include `+0.0f` versus range-valid `-0.0f` to prove bitwise float identity.
   Separately exercise public mutations that have another fully valid value and
   distinguish composition-gate rejection from fixed-schedule matcher
   rejection; do not claim an inapplicable nonzero axis remains valid under
   `ad_recipe_config_valid`. Mutate controller seed independently for all 26
   recipes, using both another registered row's seed and previously unused
   seeds while leaving kind, axes, common configuration, and captured state
   unchanged.
6. Prove the excluded provenance boundary one field at a time. Mutate
   initialized state; one used and one unused packed action; one used and one
   unused decision-team byte; one used and one unused die-side and die-value;
   and range-valid action/dice counts. For every composition-admissible change,
   require identical field-by-field identity and writer provenance rejection.
   Also demonstrate one composition-preserving captured-state mutation if a
   safe inert field exists; otherwise document and test that captured bytes are
   excluded from equality but remain subject to the preceding structural
   composition gate, so arbitrary captured mutations are not promised success.
7. Identify canonical builder output, then apply reversal plus at least two
   nontrivial cross-family/same-family permutations. In every case require
   `identities[i]` to follow `recipes[i]`; inverse-permuted numeric fields must
   equal the canonical results. Preserve recipe input bytes on success and
   failure.
8. Check in the canonical serializer and single immutable oracle fixture above.
   Generate all six streams from the exact parent builder and require exact
   lengths, per-match semantic width, and SHA-256 values. Head reproduction of
   every category must be exact; counts plus endpoint BBS hashes are not a
   sufficient controller-compatibility oracle. Implement the recursive AST
   declaration and exact stream/matcher assignment checks, including every
   negative declaration fixture specified above. Add the trusted canonical,
   negative-provenance, and all-26 link-interposed candidate-writer probes
   specified by the authority contract; prove the real public production path.
   Generate and pin the independent direct-gate bit-flip and curated-corpus
   result digests before refactoring any production source.
9. Refactor the builder to resolve the separate frozen proof schedule through
   the ledger's configuration projection. Preserve every recipe semantic field
   covered by the six permanent streams,
   caller-owned record pointers, proof-local A9 IDs, fixed order, exact-capacity
   and allocator/composition failure atomicity. Do not add black-box
   fault-injection claims without an actual injection mechanism.
10. Reproduce the exact parent artifact: whole BBS size 58,568 and SHA-256
   `c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1`;
   ordered raw body size 58,240 and SHA-256
   `6991cb6100f8da218bce89ce7828479ff8efb84cbfbf8cea158f767071a213f8`.
11. Add the append-only checker and focused synthetic fixtures. Prove valid
    shared-cell/multiple-seed rows and reject mismatched cell projections,
    reuse of one cell ID with a different projection, reuse of one projection
    under a different cell ID in the same revision, and same-cell variants that
    change procgen/game seeds or streams, controller stream, teams, exclusion,
    or any procgen parameter. Also reject duplicate concrete configurations
    under distinct source IDs, revision other than 1, and malformed template
    keys; accept valid 1-byte and 63-byte slugs, reject a NUL-terminated
    64-character slug plus 64-byte unterminated storage, invalid ASCII/grammar,
    and empty storage. Exercise ledger deletion/rewrite/reorder, duplicate or
    backfilled ordinals, a skipped next ordinal, descending suffixes,
    namespace exhaustion, any schema-1 ordinal-27 suffix, concurrent appenders,
    stale initial-addition claims, schedule mutation, immutable oracle constant
    or manifest edits, batched and transient blob mutations, transient
    controller/serializer/matcher/declaration mutations with clean final tips,
    writer rediscovery/provenance bypass with clean final tips,
    writer admission/continuation removal or reordering with clean final tips,
    F2/F3/F5-selective gate bypasses and production-only interposition evasion,
    underlying admission/continuation weakening with unchanged writer routing,
    candidate verifier no-op/hard-code/skip/stub attempts, trusted-runner
    timeouts and malformed output, commit-count/aggregate-time exhaustion,
    zero-before and force/non-ancestor push authorities, and incomplete commit
    ranges. Include
    a range-valid wrong-family recipe kind with matching axes under another
    template, plus a complete executable configuration copied under another
    otherwise-valid template. Public key lookup returns `NULL` for `0`, the first
    unallocated production ID, and `UINT32_MAX` under ASan/UBSan; the internal
    synthetic lookup also covers a table gap.
12. Update D209, `AGENTS.md`, `CLAUDE.md`, the authored-bank plan, and the
   BB-validation skill with allocation permanence and the non-publication
   boundary.
13. Run focused and full optimized plus ASan/UBSan suites, static analysis of
    production authored code and Puffer loader integration, and
    `git diff --check`.
14. Require hosted CI and three independent exact-head reviews with no open
    P0-P3 finding before merge. Any code change invalidates SHA-specific
    evidence.

## Failure and rollback rules

- No caller-output write occurs before complete one-to-one validation.
- No semantic registry entry depends on proof slot or a truncated hash.
- Template ID/key allocation, source ID, recipe revision, cell ID, variant ID,
  seed, and configuration projection are immutable append-only facts. Old
  meanings are never edited, removed, or recycled.
- The schema-1 ledger remains exactly 26 rows and the fixed legacy schedule
  never changes. Additional allocations require the separately reviewed
  executable row compiler and per-allocation oracle. Future current/canonical
  schedules and lifecycle policy are separate APIs and reviewed artifacts, not
  mutations of this builder/mapper.
- The schema-1 oracle fixture is target-authority byte-immutable together with
  the ledger and schedule. Updating expected hashes, lengths, field assignments,
  or matcher classification to accommodate changed behavior is forbidden.
- Every newly reachable commit after registry introduction must pass the bounded
  authority-pinned compatibility bundle in isolation; no commit may validate
  itself, and a final-tip revert does not make an intermediate alternative
  meaning for an AE source ID acceptable.
- The authority bundle must execute the candidate writer, not merely encode its
  builder output independently; canonical bytes must agree and every provenance
  mutation must fail before output with immutable inputs.
- The production writer calls three cross-translation-unit gateway symbols.
  Trusted link interposition over the real public path, exact AST/link-map
  binding, and all-26 call-order/count plus forced-failure probes separately
  bind fresh admission, nested admission, and continuation before any write.
- The independent immutable direct-gate corpus and result digests bind the real
  admission and continuation behavior; forwarding/count evidence alone is not
  accepted as semantic preservation.
- Revision-1 compatibility controller, predicate, and rediscovery behavior may
  not be replaced in place. Revision greater than 1 remains forbidden until a
  version-aware recipe/compiler API preserves revision-1 execution.
- The parent configuration, action/decision-team, dice, unused-transcript,
  initialized-state, and captured-state recipe oracles plus the existing A9 BBS
  artifact are permanent preservation gates. Any byte or hash drift stops this
  tranche.
- Failure requires no runtime rollback because nothing here is deployed or
  published. Revert the feature commit if preservation or review gates cannot
  be satisfied.

## Explicitly out of scope

- `records.jsonl`, `recipes.jsonl`, reports, counterfactuals, or any sidecar
  schema/serializer;
- changing proof-record A9 metadata or publishing AE IDs into BBS;
- output directories, compiler CLI, exclusive links, fsync, manifest-last
  transactions, aliases, or canonical artifact generation;
- family rebalancing, broader axis search, train/dev/test assignment,
  replay-disjoint grouping, curriculum weights, or state-bank installation;
- any allocation beyond the fixed 26, general row compiler, or revision-aware
  recipe representation;
- labels, rewards, reward defaults, policy evaluation, checkpoint selection,
  training, deployment, BBTV behavior, or any frozen-queue mutation.

The next tranche may design sidecar schemas only after this registry is merged
and independently reviewed. Publication and training remain later, separately
authorized gates.
