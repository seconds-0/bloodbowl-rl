# F2 hand-off target-count/orientation axis tranche

## Selected tranche and why now

Expand only the authored F2 family from its single hand-off-opportunity proof
into a four-cell structural axis: active team Home or Away, crossed with exactly
one or at least two legal catch-capable hand-off targets. The current live
policy's completed evaluation panel still reports zero hand-off attempts, while
the authored bank has only one F2 template and no quota proving that hand-off
opportunities include both forced-looking and choice-rich target sets.

A read-only legal-play sweep over controller seeds 0-4095 found 2,554 F2
captures, 1,542 clean match ends, and zero unexpected failures. Coverage was
present in every proposed cell: Home/exactly-one 529,
Home/two-or-more 721, Away/exactly-one 303, and Away/two-or-more 1,001. This
supports a bounded four-cell tranche without state surgery or rare-state
search. The axis describes opportunity structure only; it does not say that a
Hand-off, or any particular target, is tactically correct.

## Success criteria

- A recipe stores its requested F2 active-side and target-count bucket as
  provenance rather than accepting an out-of-band test parameter.
- The legacy F2 recipe remains byte-deterministic and retains its existing
  semantics of at least one legal catch-capable target on either active side.
- The new recipe reaches all four required cells exactly once: Home/Away x
  exactly one/two-or-more catch-capable Hand-off targets.
- Target counting is input-preserving, begins with the complete safe BBS1
  fresh-boundary validation, follows only legal zero-die
  `ACTIVATE -> DECLARE HAND-OFF` transitions on a private copy, excludes the
  carrier and non-catch-capable players, and treats two-or-more explicitly as a
  bucket rather than silently relabeling it as exactly two.
- Every capture arises from initialized legal play, is a fresh-team-turn BBS1
  boundary, independently rediscovers byte-identically, exact-replays every
  action and die, serializes through the authored writer, reloads byte-identical
  through Puffer, and passes one-action continuation.
- A missing, duplicate, wrong-orientation, wrong-target-count, malformed raw
  state, or inert configuration on another recipe kind fails closed; the test
  never silently borrows another cell.
- Existing F1/F2/F3/F4/F5 tests and goldens, BBS ABI/fingerprint, reward
  behavior, observation shape, and action space remain unchanged.

## Fixed proof cells

Use the existing authored test recipe seeds and streams, varying only the
controller seed. Bind the exact transcript counts discovered by the legal-play
probe so drift is visible:

| Active side | Target bucket | Controller seed | Actions | Dice |
|---|---:|---:|---:|---:|
| Home | two-or-more | 2 | 27 | 9 |
| Home | exactly one | 4 | 202 | 62 |
| Away | exactly one | 8 | 27 | 10 |
| Away | two-or-more | 13 | 27 | 10 |

The order above is evidence, not part of the quota API. Tests may arrange the
four recipes canonically by side then bucket as long as the stored cell and
exact transcript counts remain explicit.

## Implementation slices

1. Add fail-first focused tests for the input-preserving target counter, stored
   F2 request, inert configuration rejection, and exact four-cell quota.
2. Append one new recipe kind and the smallest explicit target-bucket field;
   generalize active-side provenance only enough for F3 and this new F2 kind.
3. Add one exact F2 discovery endpoint and quota validator while reusing the
   existing legal-play controller, transcript, rediscovery, replay, writer,
   loader, and continuation paths.
4. Add deterministic sweep evidence and document the proven axis and residual
   gaps in `AGENTS.md`, `CLAUDE.md`, the authored-bank plan, the relevant
   validation skill, and the append-only decision ledger.

## Test and validation plan

- Focused optimized fail-first and passing tests for the F2 counter, exact
  endpoint, quota matrix, mixed writer preflight, and production loader.
- Full optimized suite: `make test`.
- Full sanitizers: `make asan`.
- Deterministic optimized and ASan/UBSan controller-seed sweeps over 0-4095,
  requiring identical cell/yield counts and zero invalid success or unexpected
  failure.
- Adversarial raw-state tests modeled on the F3 review defect: null input,
  invalid stack depths including 0, 1, 33, and 255, wrong root/top frame,
  inconsistent player/grid or carrier data, invalid side/bucket, and malformed
  recipe arrays must reject without an unchecked frame/player/grid read.
- Production-source Clang static analysis with text output, `git diff --check`,
  and committed golden resimulation through the full suite.
- Before merge: local/remote/GitHub exact-head identity, three independent
  P0-P3 reviews, and green hosted CI.

## Rollout and validation

This is CPU-only source and test work. Merge through a reviewed PR. Do not
deploy it to the occupied RTX 2070, rebuild either frozen vacation queue,
publish a BBS bank, start training from the new records, or alter BBTV.
Post-merge validation is authoritative main SHA plus CI; there is no production
rollout for this tranche.

## Risks and simplification checks

- The Hand-off declaration can expose a rules-legal No Ball target that cannot
  attempt the Catch. Preserve D198/D199's distinction: count only targets for
  which `bb_can_catch` is true, while leaving engine legality unchanged.
- Validate the complete raw boundary before reading carrier, frame, grid, or
  player-derived facts. Public quota callers are not presumed trusted.
- Append the recipe kind so existing numeric identities do not move. Require
  the new bucket field to be zero for every non-axis recipe, and retain zero
  `capture_turn` outside F3.
- Avoid a second discovery/replay engine or a generic curriculum DSL. Reuse the
  established controller, transcript, endpoint-aware replay, rediscovery,
  writer, loader, and continuation canary.
- Counting target actions must not serialize or expose a selected carrier,
  action, target, tactical label, counterfactual outcome, or behavior-cloning
  label.

## Explicitly out of scope

- target marking, receiver identity/skills/stats, scoring range, carrier
  pressure, score/clock, possession history, material, reroll budget, roster,
  and race-pair axes;
- F1, F3, F4, or F5 expansion;
- nested Hand-off target-state admission, target/action labels,
  counterfactuals, sidecars, reconciliation reports, manifests, exclusive
  publication, and train/dev/test splitting;
- reward-coefficient changes, behavioral cloning, training, evaluation,
  promotion, deployment, BBTV changes, or frozen-queue changes.

## Implementation and evidence

- Appended `AD_RECIPE_F2_EXACT_HANDOFF_TARGET_COUNT`, preserving every existing
  recipe-kind number. The new target bucket is mandatory only for that kind;
  `capture_active_team` is now shared only by the exact F2 and F3 axis kinds,
  while `capture_turn` remains F3-only. Other recipes reject inert values.
- Refactored the legacy Boolean F2 predicate onto one public input-preserving
  target counter. It starts with the complete BBS1 boundary validator, follows
  only legal zero-die activation/declaration actions on a copy, and counts only
  legal target actions whose occupant satisfies `bb_can_catch`.
- Fixed cells use controller seeds Home/one 4, Home/multiple 2, Away/one 8,
  and Away/multiple 13, with exact transcript counts 202/62, 27/9, 27/10,
  and 27/10 actions/dice respectively. Every recipe independently rediscovers,
  exact-replays, emits deterministic repeated writer bytes, reloads through the
  production Puffer path byte-identically, and passes canonical continuation.
- The structural quota requires all four cells exactly once and rejects null,
  short, duplicate, wrong-side, wrong-bucket, non-axis, and malformed captures.
  Raw-state regressions include stack depths 0, 1, 33, and 255, wrong root and
  top procedures, grid/player inconsistency, and invalid carrier data.
- Matching optimized and ASan/UBSan exact-endpoint sweeps over controller seeds
  0-4095 per cell produce Home/one 1,246, Home/multiple 994, Away/one 1,189,
  Away/multiple 1,291; complementary clean ends are 2,850, 3,102, 2,907, and
  2,805, with zero invalid success or unexpected failure.
- Full local optimized and sanitizer suites pass: 431 engine, 37 reward, 2
  contact-bot, and 10 production-loader tests. Production authored and Puffer
  translation units are clean under Clang static analysis, and the diff passes
  whitespace validation. Hosted CI and exact-head reviews remain merge gates.

Residual limitations are deliberate: the four proofs share procgen/game seeds
and establish target cardinality and orientation only. They do not establish
representative tactical diversity, the desirability of a Hand-off, or a correct
receiver, and they do not authorize a bank artifact or training use.
