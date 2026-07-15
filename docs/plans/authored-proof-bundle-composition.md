# Authored proof-bundle composition tranche

## Selected tranche and why now

Compose the already merged authored proof recipes into one explicit structural
contract without creating a canonical bank or any training artifact. The
bundle contains exactly 26 primary-family records:

- four exact F1 Pass carrier-pressure/orientation cells;
- four exact F2 Hand-off target-count/orientation cells;
- sixteen exact F3 half-two turn/orientation cells;
- one F4 pending-Dodge reroll opportunity; and
- one F5 score-now-versus-Stall opportunity.

The repository has no `docs/RECOMMENDED_ORDER.md`, so this plan uses
`docs/plans/authored-drill-state-bank.md` and decisions D194-D206 as the
authoritative fallback. Their test-first order requires proof recipes and
single-family axes before canonical build/publication. Those prerequisites now
exist; the smallest next dependency is a composition/quota gate that can later
be shared by sidecar and transaction layers.

This is deliberately called a proof bundle, not a bank. Its family counts are
4/4/16/1/1 and are therefore not the count-balanced curriculum promised by the
eventual authored-bank plan. Passing this gate must not be interpreted as
representative tactical coverage or authorization to publish, stage, or train.

## Success criteria

- One public validator accepts exactly the 26 supported proof records and no
  other count or recipe-kind mix.
- The validator is order-independent and assigns each physical recipe to
  exactly one primary family by its exact recipe kind. Opportunity overlap in
  the captured state does not duplicate a record across families.
- F1, F2, and F3 subsets pass their existing complete axis validators rather
  than reimplementing those cell predicates or quota shapes.
- The one F4 recipe passes the complete pending-Dodge validator and the one F5
  recipe passes the complete score-or-wait validator. Both also satisfy their
  exact recipe configuration, including inert fields for other families.
- Every recipe receives complete safe configuration and endpoint validation
  before it is copied into a subset or used to derive a dynamic index.
- Missing, duplicate, extra, legacy-single-proof, unknown-kind, cross-family
  field drift, wrong endpoint, malformed raw state, or count mismatch fails
  closed without reading outside the caller's declared array.
- The ordinary authored writer remains the only provenance/replay/admission/
  continuation gate. Composition validation does not weaken or replace writer
  rediscovery, exact replay, BBS boundary validation, or continuation.
- Existing numeric recipe identities, `bb_match` ABI/fingerprint, legacy BBS
  bytes, reward behavior, observation shape, and action space remain unchanged.

## Implementation slices

1. Add a fail-first engine test that builds all 26 records through existing
   legal discovery APIs, validates canonical and reversed order, and rejects
   count, kind, duplicate-family, axis-cell, endpoint, and raw-state drift.
2. Add only the bundle-count constant and one validator API. Partition by exact
   recipe kind into fixed local F1/F2/F3 arrays plus one F4 and one F5 pointer;
   reject every unsupported kind.
3. Reuse the existing F1/F2/F3 axis validators and exact F4/F5 predicates.
   Keep this structural layer independent of serialization and filesystem I/O.
4. Add a production-loader integration test that writes the validated 26
   recipes through the unchanged authored writer, reloads all records
   byte-identically, and proves one-action continuation for every record.
5. Document the proof-bundle distinction and remaining publication/training
   gaps in `AGENTS.md`, `CLAUDE.md`, the authored-bank plan, validation skill,
   and append-only decision ledger.

## Test and validation plan

- Focused optimized fail-first and passing engine/loader tests.
- Canonical, reversed, and deterministic repeated composition validation.
- Negative matrix: null, 0/25/27 counts, duplicate F1/F2/F3 cell, missing F4,
  missing F5, legacy F1/F2/F3 recipe kinds, unknown/negative kind, wrong active
  side or bucket/pressure, malformed F4/F5 endpoint, stack depths 0/1/33/255,
  and grid/player/carrier inconsistency.
- Full `make test` and `make asan`.
- Clang static analysis of production authored and Puffer translation units,
  plus `git diff --check`.
- Parent-versus-head legacy F1 and F2 BBS byte comparisons remain unchanged;
  no new BBS format or fingerprint is introduced.
- Before merge: local/remote/GitHub exact-head identity, three independent
  P0-P3 reviews, and green hosted CI.

## Rollout and validation

This is CPU-only source/test work. Merge through a reviewed PR. Do not add a
compiler CLI, write `records.jsonl` or `recipes.jsonl`, publish a manifest
transaction, create a canonical BBS bank, stage demo resets, train, evaluate,
deploy to the occupied RTX 2070, or change BBTV. Post-merge validation is the
authoritative main SHA and CI; there is no live rollout for this tranche.

## Risks and simplification checks

- Do not call a 4/4/16/1/1 bundle balanced. F3 intentionally dominates because
  this layer composes proofs, not curriculum quotas.
- Do not infer F1/F2/F4/F5 membership from overlapping captured-state facts.
  Primary family comes only from the exact recipe kind, preventing silent
  double counting.
- Validate exact kind/configuration before any subset copy or index. Public
  callers and raw captures are untrusted.
- Do not duplicate the three axis validators or create a generic quota DSL.
  Fixed typed arrays and one explicit switch keep the contract auditable.
- Do not perform filesystem I/O here. Exclusive manifest-last publication is a
  later transaction tranche with different failure modes and tests.

## Explicitly out of scope

- balanced per-family/axis quotas beyond the 26 existing proofs;
- score/clock/material/reroll/roster/race/receiver/range/interception axes;
- nested Pass/Hand-off targets or additional reroll procedures;
- metadata schemas, sidecars, counterfactuals, reports, compiler CLI, output
  directories, exclusive publication, or `MANIFEST.json`;
- train/dev/test assignment, canonical bank construction, demo-reset staging,
  behavior cloning, PPO training, reward changes, evaluation, promotion,
  deployment, BBTV changes, or frozen-queue changes.

## Implementation and evidence

- Added one fixed `AD_AUTHORED_PROOF_BUNDLE_COUNT` and one public structural
  validator. It first requires the exact count, validates every recipe's
  complete kind-specific configuration, partitions by exact recipe kind into
  heap-backed typed subsets, rejects unsupported/excess/duplicate families,
  then delegates F1/F2/F3 to their existing complete axis validators and F4/F5
  to their exact opportunity predicates.
- Canonical and reversed order both pass. Negative coverage rejects null,
  0/25/27 counts, duplicate axis cells, missing F4/F5, legacy and out-of-range
  kinds, wrong side/pressure/target bucket/turn, stack depths 0/1/33/255,
  grid/player inconsistency, and malformed F4/F5 endpoints.
- The production-loader integration legally rediscovers all 26 fixed recipes,
  validates composition, writes them through the unchanged provenance-gated
  BBS writer, proves identical whole-bundle bytes on a second write, reloads
  every raw match byte-identically, and proves canonical one-action
  continuation for each record. No compiler CLI, sidecar, report, manifest,
  output directory, or persistent bank artifact exists.
- Full optimized and ASan/UBSan suites pass: 433 engine, 37 reward, 2
  contact-bot, and 12 production-loader tests. Production authored and Puffer
  translation units are clean under Clang static analysis, and the diff passes
  whitespace validation. Hosted CI and exact-head reviews remain merge gates.

Residual limitations are the point of the tranche: the bundle is composed from
the current fixed proof seeds, F3 dominates its family counts, and no metadata,
split, diversity, balance, publication, or training contract has been added.
