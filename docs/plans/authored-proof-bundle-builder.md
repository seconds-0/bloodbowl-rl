# Authored proof-bundle builder tranche

## Selected tranche and why now

Create one production-owned deterministic in-memory builder for the already
merged 26-record
authored proof bundle. The composition validator proves that a caller-provided
set has the required 4/4/16/1/1 structure, but the two integration suites still
duplicate the fixed base configuration, cell seeds, discovery order, and
proof-local record assignment. A metadata compiler cannot safely begin from a
recipe schedule and order that exist only in test helpers. Persistent recipe
IDs, versions, variants, and the global authored-ID registry remain a separate
sidecar-schema decision; this builder must not invent a halfway identity
contract.

The repository has no `docs/RECOMMENDED_ORDER.md`, so this plan follows
`docs/plans/authored-drill-state-bank.md`, D194-D207, and the merged composition
plan. The smallest dependency before sidecar schemas or a publication
transaction is a single production-owned constructor that creates the exact
proof recipes and their BBS metadata deterministically.

This remains an in-memory proof object. It is intentionally unbalanced and is
not a canonical bank, published artifact, split, curriculum, or training input.

## Success criteria

- The exact public API is:

  ```c
  int ad_build_authored_proof_bundle(
      ad_recipe* recipes, size_t recipe_capacity,
      ad_bbs_record* records, size_t record_capacity,
      char error[AD_ERROR_CAP]);
  ```

  Both output pointers and the error buffer are required. Both capacities must
  equal 26. A null error buffer returns failure without touching either output;
  every other argument failure writes only the error buffer. The output arrays
  remain byte-for-byte unchanged. For non-null arguments, caller storage for
  the 26 recipes, 26 records, and `AD_ERROR_CAP` error bytes must be mutually
  disjoint and suitably aligned for the declared types; overlapping storage is
  outside this internal API contract.
- The builder constructs and validates in checked temporary heap storage. On
  allocation, discovery, or final-validation failure, both caller arrays remain
  byte-for-byte unchanged. Only a complete success commits output. The builder
  retains no allocation or pointer after return and clears `error[0]` on
  success.
- The builder starts from one production-owned, zero-initialized base recipe
  configuration. Every recipe fixes all common provenance fields exactly:
  `procgen_seed=0xA1170EED`, `procgen_stream=17`,
  `game_seed=0xD11CE5`, `game_stream=23`, `controller_stream=31`,
  `home_team=0`, `away_team=1`, `exclude_team=-1`, and procgen parameters
  `{skillup_max_players=4, skillup_max_each=2,
  skillup_secondary_pct=0.0f}`. Before discovery, every byte not listed above
  is canonical zero. After discovery, every family-specific configuration
  field unused by that recipe kind remains zero; discovery-owned kind, match,
  transcript, and count fields contain the deterministic discovered result. It
  uses the already proved fixed controller seeds:
  - F1 Home/open 4, Home/marked 2, Away/open 10, Away/marked 8;
  - F2 Home/one 4, Home/multiple 2, Away/one 8, Away/multiple 13;
  - F3 Home turns 1-8 at 1000-1007 and Away turns 1-8 at 1008-1015;
  - F4 seed 1 and F5 seed 410.
- Fixed proof-bundle order is F1 by side/pressure, F2 by side/target bucket, F3 by
  side/turn, F4, then F5.
- To preserve the already reviewed integration artifact, records retain the
  explicitly proof-local positional IDs `0xA9000000 + index`. These are unique
  within this 26-record proof stream and remain in the reserved `0xA`
  namespace, but they are not persistent recipe IDs, variant IDs, or suitable
  sidecar join keys. The later identity-schema tranche must allocate a
  collision-audited, versioned registry and may deliberately change whole-BBS
  metadata/hash; no existing authored ID may be silently repurposed.
- Every record points to its corresponding caller-owned recipe and stores the
  exact discovered action count as its decision index.
- The completed output passes the existing structural composition validator,
  ordinary writer rediscovery/exact-replay/admission/continuation preflight,
  production loader, byte-identity, and canonical continuation gates.
- Two independent builder calls produce byte-identical recipes, field-identical
  record metadata, and identical 58,568-byte BBS streams. A pre-refactor oracle
  generated from exact main
  `247e63121b5fe67e66a8e01cdc70557cf7d4d1c8` pins the existing whole-BBS
  SHA-256 as
  `c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1`
  and the SHA-256 over the 58,240-byte concatenation of the 26 ordered raw
  `bb_match` payloads (header and every 12-byte metadata block excluded) as
  `6991cb6100f8da218bce89ce7828479ff8efb84cbfbf8cea158f767071a213f8`.
  The builder must match both digests; this prevents the two builder-based test
  suites from becoming a self-referential preservation check.

### Frozen ordered schedule

The fail-first regression pins the complete exact-main schedule below. `H` and
`A` mean Home and Away; counts are complete transcript lengths at capture.

| Index | Cell | Controller seed | Actions | Dice |
|---:|---|---:|---:|---:|
| 0 | F1 H/open | 4 | 202 | 62 |
| 1 | F1 H/marked | 2 | 27 | 9 |
| 2 | F1 A/open | 10 | 172 | 50 |
| 3 | F1 A/marked | 8 | 27 | 10 |
| 4 | F2 H/exactly-one | 4 | 202 | 62 |
| 5 | F2 H/two-or-more | 2 | 27 | 9 |
| 6 | F2 A/exactly-one | 8 | 27 | 10 |
| 7 | F2 A/two-or-more | 13 | 27 | 10 |
| 8 | F3 H/turn-1 | 1000 | 505 | 111 |
| 9 | F3 H/turn-2 | 1001 | 329 | 95 |
| 10 | F3 H/turn-3 | 1002 | 385 | 141 |
| 11 | F3 H/turn-4 | 1003 | 408 | 123 |
| 12 | F3 H/turn-5 | 1004 | 502 | 164 |
| 13 | F3 H/turn-6 | 1005 | 607 | 168 |
| 14 | F3 H/turn-7 | 1006 | 491 | 185 |
| 15 | F3 H/turn-8 | 1007 | 571 | 180 |
| 16 | F3 A/turn-1 | 1008 | 373 | 118 |
| 17 | F3 A/turn-2 | 1009 | 439 | 101 |
| 18 | F3 A/turn-3 | 1010 | 352 | 128 |
| 19 | F3 A/turn-4 | 1011 | 495 | 149 |
| 20 | F3 A/turn-5 | 1012 | 459 | 158 |
| 21 | F3 A/turn-6 | 1013 | 562 | 147 |
| 22 | F3 A/turn-7 | 1014 | 597 | 198 |
| 23 | F3 A/turn-8 | 1015 | 598 | 204 |
| 24 | F4 pending-Dodge | 1 | 384 | 110 |
| 25 | F5 score-or-wait | 410 | 51 | 19 |

## Implementation slices

1. Add fail-first engine tests for the missing builder symbol, exact fixed
   kind/cell/base/seed/ID schedule, pointer ownership, decision indices,
   all-pairs ID uniqueness, deterministic recipes, and deterministic BBS bytes.
2. Add only the builder declaration and implementation. Reuse the existing
   discovery APIs and final composition validator; do not add a second replay,
   serializer, quota, or endpoint implementation.
3. Replace the duplicated proof-bundle construction helpers in the engine and
   production-loader tests with the public builder. Keep adversarial mutation
   tests against caller-built arrays.
4. Add sentinel-based no-write tests for nulls and all mismatched/wrong capacity
   combinations. Audit allocation, fixed discovery, and final-validation paths
   for copy-on-success atomicity. The fixed public contract cannot request an
   internal discovery failure, so do not falsely claim black-box branch
   coverage or add a callback/seed override merely to manufacture one.
5. Update the authored-bank plan, `AGENTS.md`, `CLAUDE.md`, validation skill,
   and append-only decision ledger with the exact in-memory-only boundary.

## Test and validation plan

- Focused optimized and ASan/UBSan builder tests.
- Exact schedule assertions for all 26 recipes, complete common configuration,
  family-specific fields, controller seeds, transcript action/dice counts,
  proof-local record IDs, and all-pairs ID uniqueness.
- Null recipe array, null record array, null error buffer, and independent
  recipe/record capacities 0/25/26/27, including mismatched 26/25 and 25/26;
  sentinel-filled outputs remain byte-for-byte unchanged on every reachable
  failure.
- Two complete builds compared recipe-by-recipe. Records are compared
  field-by-field: equal source ID and decision index, plus
  `records[i].recipe == &recipes[i]` for each owning array. Never `memcmp`
  pointer-bearing records or mutate outputs to normalize addresses.
- Pre-refactor exact-main evidence records the whole 58,568-byte BBS digest and
  the digest of 58,240 concatenated raw-match bytes. Head output must match both
  before the duplicated helpers are removed.
- Existing fixed-order/reversed structural composition and malformed-state
  rejection matrix remains green.
- Existing production-loader integration writes the builder output twice,
  requires exact 58,568-byte equality, reloads all 26 raw matches, and
  continues every record once.
- Full `make test` and `make asan`.
- Clang static analysis for `tools/authored_drill.c` and the production-loader
  test translation unit, plus `git diff --check`.
- Before merge: exact local/remote/GitHub head identity, three independent
  P0-P3 reviews, and green hosted CI.

## Risks and simplification checks

- Positional `0xA9...` IDs are explicitly proof-local compatibility metadata,
  not stable semantic identities. Do not let later sidecars treat them as a
  recipe/template/version/variant key.
- The builder may use one checked temporary heap allocation, frees it on every
  path, and retains no heap ownership or hidden pointer. Avoid a roughly
  1.61 MiB automatic recipe array, static scratch, or thread-unsafe storage.
- Build and validate only temporary recipes. On success, copy all 26 recipes
  first, then construct each caller record directly with
  `recipe=&recipes[i]`; never copy a temporary pointer into caller output.
  No fallible operation occurs after the first caller-output write.
- Keep fixed proof seeds fixed. A generic seed/spec DSL belongs to later axis
  expansion and would blur proof construction with canonical bank design.
- Reuse the one composition gate and ordinary writer. The builder is not a new
  trust boundary and must not make provenance checks optional.
- Do not call the output balanced, representative, canonical, or publishable.

## Explicitly out of scope

- durable recipe/template/version/variant identities, a global authored-ID
  registry, `records.jsonl`, `recipes.jsonl`, `report.json`, counterfactuals,
  transcript hashes, legal-action hashes, or any production metadata schema;
- the two test/evidence-only compatibility digests above are permitted solely
  to lock behavior across this refactor; they are not sidecars, a manifest, or
  a published bank;
- train/dev/test assignment, template grouping, family rebalancing, new axes,
  recipe search, or mutable seed/spec inputs;
- compiler CLI, output directory, filesystem transaction, `MANIFEST.json`,
  manifest-last publication, staging, or a persistent BBS artifact;
- demo-reset selection, BC, PPO, reward changes, evaluation, promotion,
  deployment, BBTV changes, or any frozen vacation-queue change.

## Rollout

This is CPU-only source/test work merged through a reviewed PR. There is no
runtime deployment. The occupied RTX 2070, frozen queues, checkpoints, BBTV
selection, and production state-bank path remain untouched.

## Implementation and evidence

- The fail-first focused build stopped on the missing
  `ad_build_authored_proof_bundle` declaration. The implemented API now checks
  both exact capacities and every pointer before output access, stages all 26
  recipes in one checked heap allocation, runs the existing complete
  composition validator, copies recipes only after success, and directly binds
  each caller record to `&recipes[i]`. No allocation or temporary pointer
  escapes, and no fallible operation follows the first caller-output write.
- The regression pins every common configuration field, fixed cell, controller
  seed, action/dice transcript count, positional A9 ID, decision index, record
  pointer, and all-pairs ID uniqueness. Sentinel tests cover null pointers plus
  every 0/25/26/27 capacity mismatch without changing caller outputs. Two
  complete builds produce byte-identical recipes and field-identical records.
- The production-loader integration now consumes the public builder rather
  than its duplicate helper. Optimized and ASan/UBSan focused tests write the
  complete stream twice, load all 26 matches byte-identically, and continue
  every state. Independent head extraction reproduces the exact-main
  58,568-byte whole-BBS SHA-256
  `c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1`
  and 58,240-byte ordered-raw-body SHA-256
  `6991cb6100f8da218bce89ce7828479ff8efb84cbfbf8cea158f767071a213f8`.
- Full optimized and ASan/UBSan suites pass: 434 engine, 37 reward, 2
  contact-bot, and 12 production-loader tests. Authored production and Puffer
  loader-test static analysis plus whitespace checks are clean. Exact-head
  independent reviews and hosted CI remain merge gates.

This closes duplicated proof construction only. It adds no durable identity
registry, metadata sidecar, compiler CLI, output transaction, bank publication,
training input, reward change, evaluation, deployment, or live-queue change.
