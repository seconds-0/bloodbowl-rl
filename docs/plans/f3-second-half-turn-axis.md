# F3 second-half turn/orientation axis tranche

## Selected tranche and why now

Expand only the authored F3 family from its single late-half proof into an
exact half-two turn axis covering turns 1 through 8 for both active-team
orientations. The strict historical replay bank contains no half-two states,
and F3 remains on the already hardened fresh-team-turn BBS1 boundary. The
authored-bank plan explicitly requires one-family-at-a-time axis expansion
after F1-F5 proofs and before canonical publication.

## Success criteria

- A recipe stores its F3 axis request as provenance rather than accepting an
  out-of-band test parameter.
- The legacy late-F3 recipe remains byte-deterministic and retains its existing
  half-two, active-turn-at-least-five semantics.
- The new exact-turn recipe reaches all 16 required cells: half two, turns 1-8,
  active team Home and Away.
- Every capture arises from initialized legal play, is a fresh-team-turn BBS1
  boundary, independently rediscovers byte-identically, exact-replays every
  action and die, serializes through the authored writer, reloads byte-identical
  through Puffer, and passes one-action continuation.
- A missing, duplicate, wrong-half, wrong-turn, or wrong-orientation cell fails
  the quota contract; the test never silently borrows another cell.
- Existing F1/F2/F3/F4/F5 tests, goldens, BBS ABI/fingerprint, reward behavior,
  observation shape, and action space remain unchanged.

## Implementation slices

1. Add fail-first focused tests for the stored F3 request and the exact 16-cell
   quota matrix.
2. Add the smallest recipe configuration and discovery endpoint needed to bind
   exact half-two turn plus active team through full rediscovery/replay.
3. Add writer and production-loader integration for the matrix without adding
   any new loader shape.
4. Add deterministic sweep evidence and document the proven axis and its
   remaining gaps in `AGENTS.md`, `CLAUDE.md`, the authored-bank plan, the
   validation skill, and the append-only decision ledger.

## Test and validation plan

- Focused optimized tests:
  `make build/bb_tests build/puffer_state_bank_tests`, then filters for the new
  F3 axis, mixed writer preflight, and production loader.
- Full optimized suite: `make test`.
- Full sanitizers: `make asan`.
- Deterministic optimized and ASan/UBSan controller-seed sweeps over a declared
  bounded range, requiring identical cell/yield counts and no invalid success.
- Production-source Clang static analysis with text output, `git diff --check`,
  and committed golden resimulation through the full suite.
- Before merge: local/remote/GitHub exact-head identity, three independent
  P0-P3 reviews, and green hosted CI.

## Rollout and validation

This is CPU-only source and test work. Merge through a reviewed PR. Do not
deploy it to the occupied RTX 2070, rebuild a frozen queue, publish a BBS bank,
or alter BBTV. Post-merge validation is authoritative main SHA plus CI; there is
no production rollout for this tranche.

## Risks and simplification checks

- A team can lose an ordinary turn after an opponent-turn touchdown; exact
  predicates must fail closed rather than relabel a later boundary.
- Axis fields must not create inert provenance values for non-axis recipes or
  renumber existing recipe kinds.
- Avoid a second discovery/replay engine. Reuse the existing controller,
  transcript, recipe-specific endpoint, rediscovery switch, writer, loader, and
  continuation canary.
- Keep the quota representation explicit and small; do not build a generic
  curriculum DSL or publication system in this tranche.

## Explicitly out of scope

- score, possession, receiving history, material, reroll-budget, roster, and
  race-pair axes;
- F1, F2, F4, or F5 axis expansion;
- sidecars, reconciliation reports, manifests, exclusive publication, and a
  train/dev/test bank split;
- counterfactual outcomes, policy labels, reward changes, behavioral cloning,
  training, evaluation, promotion, deployment, or frozen-queue changes.

## Implementation and evidence

- Added `AD_RECIPE_F3_EXACT_SECOND_HALF_TURN` after all existing recipe kinds,
  preserving their numeric identities. Its stored `capture_turn` and
  `capture_active_team` fields are mandatory only for this kind and must remain
  zero for all other recipes.
- Added one exact discovery endpoint and one structural quota validator while
  reusing the existing legal-play controller, transcript, endpoint-aware exact
  replay, rediscovery, writer preflight, production loader, and continuation
  canary. The legacy late-F3 endpoint remains half two, active turn at least 5.
- The fail-first quota test caught an incorrect 240-cell interpretation caused
  by using `BB_TEAM_COUNT`, the 30-entry roster catalogue, instead of the two
  active-side orientations. The corrected public constants define 8 turns x 2
  sides = 16 cells. Loader assertions now also guard side/turn indexing so a
  malformed load cannot turn a diagnostic failure into test undefined behavior.
- Fixed recipes use controller seeds 1000-1015 and bind exact action/dice counts
  for every cell. Each proves independent rediscovery, byte-exact replay,
  deterministic repeated writer bytes, production-loader byte identity, exact
  cell coverage, and one-action continuation; negative tests cover invalid
  turn/side, inert config on legacy recipes, missing/duplicate cells, capture
  drift, and writer failure before byte zero.
- Independent optimized and ASan/UBSan sweeps over controller seeds 0-255 for
  every cell agree: 4,088 captures, 8 clean match ends, and zero unexpected
  failures. All eight clean ends are turn-one misses (four seeds under each
  orientation); turns 2-8 capture for all 256 seeds under both orientations.
- Production `tools/authored_drill.c` and the Puffer integration translation
  unit are clean under Clang static analysis. The engine test translation unit
  reports only three pre-existing `fread`/`errno` warnings at lines 213, 871,
  and 887; no new test warning is introduced. Final full optimized and
  sanitizer counts, hosted CI, exact-head reviews, and merge identity are
  recorded at review/merge time rather than predicted here.

Residual limitations are deliberate: the fixed matrix varies controller seeds
but still shares the test recipe's procgen/game seeds and proves reachability,
not representative tactical diversity. The score, possession, receiving,
material, reroll, roster/race, and quality axes remain future separate tranches.
