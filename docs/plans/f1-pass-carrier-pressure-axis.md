# F1 Pass carrier-pressure/orientation axis tranche

## Selected tranche and why now

Expand only the authored F1 family from its single Pass-opportunity proof into
a four-cell structural axis: active team Home or Away, crossed with an open or
marked ball carrier who has a real Pass opportunity. Marking the thrower is an
unambiguous property of the serialized fresh-team-turn state and directly
affects the BB2025 Passing Ability test. It does not choose a Pass target or say
that passing is tactically correct.

A read-only legal-play sweep over controller seeds 0-4095 found 2,852 first F1
captures, 1,244 clean match ends, and zero unexpected failures. Coverage was
abundant in all proposed cells: Home/open 702, Home/marked 707, Away/open 766,
and Away/marked 677. The same probe rejected two tempting alternatives. Every
capture had multiple catch-capable teammate targets, so an exactly-one versus
multiple-receiver axis has an empty cell. Receiver marking was mixed within the
available target set in 2,809 of 2,852 captures, so bucketing a state by one
receiver would require an implicit target choice. Carrier pressure avoids both
problems and remains a state-level opportunity fact.

## Success criteria

- A recipe stores its requested F1 active-side and carrier-pressure bucket as
  provenance rather than accepting an out-of-band test parameter.
- The legacy F1 recipe remains byte-deterministic and retains its existing
  semantics: a standing, non-No-Ball, non-dash-PA active carrier can legally
  activate and declare Pass with zero dice and has at least one catch-capable
  teammate target.
- The new recipe reaches all four required cells exactly once: Home/Away x
  open/marked carrier.
- Open/marked classification is derived from the carrier's current opposition
  tackle zones through engine semantics after complete safe BBS1 boundary and
  F1 opportunity validation. It never uses a selected receiver or outcome.
- Every capture arises from initialized legal play, remains a fresh-team-turn
  BBS1 boundary, independently rediscovers byte-identically, exact-replays
  every action and die, serializes through the authored writer, reloads
  byte-identically through Puffer, and passes one-action continuation.
- Missing, duplicate, wrong-orientation, wrong-pressure, malformed raw state,
  or inert configuration on another recipe kind fails closed; tests never
  silently borrow another cell.
- Existing F1/F2/F3/F4/F5 tests and goldens, BBS ABI/fingerprint, reward
  behavior, observation shape, and action space remain unchanged.

## Fixed proof cells

Use the existing authored test recipe seeds and streams, varying only the
controller seed. Bind the exact transcript counts observed at the first legal
F1 opportunity:

| Active side | Carrier pressure | Controller seed | Actions | Dice |
|---|---|---:|---:|---:|
| Home | marked | 2 | 27 | 9 |
| Home | open | 4 | 202 | 62 |
| Away | marked | 8 | 27 | 10 |
| Away | open | 10 | 172 | 50 |

The quota API is independent of table order. Tests may arrange cells
canonically by side then pressure bucket while keeping stored provenance and
exact transcript counts explicit.

## Implementation slices

1. Add fail-first focused tests for stored F1 side/pressure provenance, exact
   four-cell quota, inert configuration rejection, and malformed raw states.
2. Append one recipe kind and the smallest explicit F1 carrier-pressure field;
   generalize active-side provenance only enough to include this exact F1 kind.
3. Add one exact F1 discovery endpoint and structural quota while reusing the
   existing BB2025-correct opportunity predicate, legal-play controller,
   transcript, rediscovery, exact replay, writer, loader, and continuation.
4. Run exact-endpoint optimized and ASan/UBSan sweeps, then document evidence
   and residual gaps in `AGENTS.md`, `CLAUDE.md`, the authored-bank plan, the
   validation skill, and the append-only decision ledger.

## Test and validation plan

- Focused optimized fail-first and passing tests for exact F1 discovery,
  carrier-pressure classification, quota, mixed writer preflight, legacy F1,
  and production loading.
- Full optimized suite: `make test`.
- Full sanitizers: `make asan`.
- Deterministic optimized and ASan/UBSan controller-seed sweeps over 0-4095 for
  every requested cell, requiring identical yield counts, stored-cell and raw
  endpoint validity, byte-exact replay, and zero invalid success or unexpected
  failure.
- Adversarial raw-state tests: null inputs, stack depths 0, 1, 33, and 255,
  wrong root/top frames, invalid carrier/grid/player relationships, invalid
  side/pressure values, and malformed recipe arrays must reject before any
  unchecked dynamic read or quota index.
- Paired endpoint tests must prove both a legal open carrier and a legal marked
  carrier retain Pass-opportunity eligibility, and reject a stored bucket flip
  that no longer matches the captured state.
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

- `bb_is_marked` means at least one opposition player currently exerts a Tackle
  Zone on the carrier; do not replace it with geometric adjacency that ignores
  stance, Distracted/No-TZ state, team, or rule hooks.
- Retain F1's PA-dash and No Ball gates from D197/D198. Carrier pressure is an
  axis layered on a real Pass opportunity, not a substitute for that predicate.
- Validate the complete raw boundary and F1 opportunity before reading or
  indexing carrier-derived facts. Public quota callers are untrusted.
- Append the recipe kind so existing numeric identities do not move. Require
  the new pressure field to be zero for every non-axis recipe, retain zero
  `capture_turn` outside F3, and retain the F2 target bucket only on exact F2.
- Avoid a second discovery/replay engine or generic curriculum DSL. Reuse the
  existing controller, transcript, endpoint-aware replay, rediscovery, writer,
  loader, and continuation canary.

## Explicitly out of scope

- receiver identity, receiver marking, target count, Pass range, interception,
  thrower PA/stat/skills, weather, score/clock, possession history, material,
  reroll budget, roster, and race-pair axes;
- F2, F3, F4, or F5 expansion;
- nested Pass-target admission, chosen action/receiver/target labels,
  counterfactuals, sidecars, reports, manifests, canonical publication, and
  train/dev/test splitting;
- reward-coefficient changes, behavior cloning, training, evaluation,
  promotion, deployment, BBTV changes, or frozen-queue changes.

## Implementation and evidence

- Appended `AD_RECIPE_F1_EXACT_PASS_CARRIER_PRESSURE`, preserving all existing
  recipe-kind numbers. The new pressure field is mandatory only for that kind;
  active-side provenance is shared only by the exact F1/F2/F3 axes, while the
  F2 target bucket and F3 turn remain kind-specific. Inert cross-kind values
  fail configuration validation.
- The exact endpoint first runs the complete input-preserving F1 Pass predicate
  and checks the requested active side, then calls `bb_is_marked` on the already
  validated carrier. It therefore inherits all fresh-boundary, carrier, PA,
  No-Ball, legal zero-die activation/declaration, and catch-capable-target gates
  without an unchecked carrier read or geometric pressure approximation.
- Fixed cells use controller seeds Home/open 4, Home/marked 2, Away/open 10,
  and Away/marked 8, with exact transcript counts 202/62, 27/9, 172/50,
  and 27/10 actions/dice respectively. Every recipe independently rediscovers,
  exact-replays, produces deterministic repeated writer bytes, reloads through
  the production Puffer path byte-identically, and passes canonical one-action
  continuation. A separately compiled parent-versus-axis comparison emits the
  identical legacy 2,268-byte F1 record with SHA-256
  `cca3e04df7a42e77854573a2dafbd342523f378e16373cf061d274ff229d4eda`.
- The four-cell quota rejects null, short, duplicate, wrong-side,
  wrong-pressure, non-axis, and malformed captures. Raw-state regressions cover
  stack depths 0, 1, 33, and 255, wrong root/top procedures, grid/player
  inconsistency, and invalid carrier data. The paired real endpoints prove both
  pressure buckets retain the complete Pass opportunity, while a stored bucket
  flip fails closed.
- Full optimized and ASan/UBSan suites pass: 432 engine, 37 reward, 2
  contact-bot, and 11 production-loader tests. Production authored and Puffer
  translation units are clean under Clang static analysis, and the diff passes
  whitespace validation. The optimized exact-endpoint sweep over controller
  seeds 0-4095 per cell yields Home/open 1,323, Home/marked 948, Away/open
  1,464, and Away/marked 996; complementary clean ends are 2,773, 3,148,
  2,632, and 3,100, with zero invalid success or unexpected failure. The
  ASan/UBSan sweep matches every count without a sanitizer finding. Hosted CI
  and exact-head reviews remain merge gates.

Residual limitations are deliberate: the fixed proofs share procgen/game
seeds and establish only orientation and carrier pressure at one real Pass
opportunity. They do not establish representative tactical diversity, whether
Pass is desirable, or which receiver/target is correct, and they authorize no
bank artifact, sidecar, publication, or training use.
