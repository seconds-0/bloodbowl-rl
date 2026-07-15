# Deterministic authored drill state bank

Status: implementation plan; no training or deployment authorization.

## Objective

Build a small, balanced BBS1 bank of legal BB2025 states that the historical
replay bank cannot supply reliably: Pass and Hand-off decisions, second-half
and late-drive contexts, contextual reroll windows, and score-now-versus-Stall
decisions under the real Crowd Takes Action rule.

The bank is a curriculum input, not an action-label corpus. It must contain no
human or generated "best action" field that PPO/BC can consume. Optional paired
rollouts are evaluation metadata only and must be published separately from the
BBS1 bytes.

This tranche must not modify, rebuild, stage files into, or deploy over either
frozen vacation queue or the production/BBTV checkout on the occupied RTX 2070.

## Non-negotiable construction rules

1. Start every recipe with `bb_match_init_forced_p` or
   `bb_match_init_random_p` on a zero-initialized engine match.
2. Reach every captured state through `bb_advance` and legal `bb_apply`
   actions. The compiler may inspect state and legal actions to control a
   recipe, but may not write match fields, players, grid, ball, score, turn,
   half, resources, flags, status, or procedure frames.
3. Keep procgen and game randomness separate. Match initialization uses a
   seeded procgen RNG because roster generation intentionally consumes raw
   `bb_rng_next` values rather than game dice; reproduction reruns it from the
   same seed/stream and requires the initialized `bb_match` bytes to match.
   Before the first `bb_advance`, discovery attaches a sink to a separately
   seeded game RNG and records every die's sides and returned face. Exact
   replay injects those game-die faces through `bb_rng_script` and verifies the
   sides sequence as well as complete consumption.
4. Capture only `BB_STATUS_DECISION` states with a nonempty, loader-valid
   procedure stack and at least one legal action. The writer remains restricted
   to the fresh-team-turn boundary except for the exact F4 pending-Dodge recipe.
   The production loader's validator for that first supported nested shape
   requires a failed first-step, non-Rush Dodge with remaining ordinary MA,
   rejects Rooted and activation-cleared status flags, and keeps a resolved-
   Rush state out of scope via its retained `match.ret` result. No other recipe
   kind or nested procedure may substitute the broader resumable gate.
5. Regeneration must replay every action as legal, consume exactly the recorded
   dice, reproduce the captured raw `bb_match` byte-for-byte, and produce the
   same bank, sidecars, and manifest bytes on a second run.
6. Use the merged BB2025 engine and D193 Stalling semantics. Do not synthesize a
   Stalling penalty in reward code.

These constraints intentionally make generation harder. A position that a
controller cannot reach through the engine is not silently converted into a
trusted raw snapshot.

## Artifact contract

One compiler transaction publishes the following files into a new empty output
directory:

- `authored-drills.bbs`: ordinary BBS1 header and raw `bb_match` records;
- `records.jsonl`: one canonical metadata object per BBS record, in identical
  order;
- `recipes.jsonl`: the complete initialization identity, packed action
  transcript, and dice transcript for every recipe;
- `counterfactuals.jsonl`: optional paired-rollout diagnostics, never read by
  the environment or BC loader;
- `report.json`: family/axis/quota/split counts and validation totals; and
- `MANIFEST.json`: the last-published commit marker binding every input,
  executable, source, command, compiler flag, engine tree, output, and count.

Publication follows the D191/D192 discipline: temp files in the destination
directory, `fsync`, exclusive ownership-safe final links, directory `fsync`,
and manifest last. Existing outputs, aliases, source mutation, partial replay,
or any failed validation leave no committed transaction and overwrite nothing.

### Current BBS1 safety boundary

Every historical scenario scanner intentionally accepts only the shared,
structurally validated `MATCH(phase 3) -> TEAM_TURN(phase 1)` stack shape. The
authored writer requires that boundary for F1/F2/F3/F5 and selectively accepts
the exact nested F4 shape described below only when the recipe kind is F4.
Merely checking procedure
IDs is unsafe: corrupt frame parameters can become player/team indices during
legal-action enumeration. The writer also requires each record's capture
decision index to equal its exact-replayed recipe action count, so authentic
state bytes cannot be paired with false capture provenance.

The production loader and canonical one-action continuation canary now use a
separate resumable admission gate. It admits that ordinary boundary plus one
exact five-frame nested shape:
`MATCH -> TEAM_TURN -> ACTIVATION(Move) -> MOVE -> TEST(Dodge)` at the reroll
choice after a failed, first-step, non-Rush Dodge. The validator checks the
complete parent chain, active mover and grid, adjacent empty destination,
marked origin, ordinary MA remaining, absence of Rooted/Distracted/Eye Gouged,
pending-test latches, failed die, recomputed target including implemented
hooks, valid generated skill bits, and real Use/Decline legal actions. A
resolved Rush retains its success in `match.ret` and is intentionally rejected
by this first validator. The pending destination is encoded egocentrically in
observation context bytes 9/12, preventing transition-distinct reset states
from aliasing behind an identical nonspatial reroll mask. Optimized tests prove
both continuations: a successful team reroll
continues the Move, while Decline knocks the mover down, preserves the reroll,
and turns over. The Puffer integration test proves raw-byte loader identity,
TEST target plus pending-destination observation, destination-alias separation,
deciding-coach Use/Decline masks, and the waiting coach's null mask. Tackle at
the origin suppresses only the Dodge skill reroll; Team Re-roll and Pro remain
independently available under their normal rules.

The fixed authored F4 proof now reaches this window by legal initialized play,
binds its complete transcript through rediscovery and exact replay, and permits
only the F4 writer path to use resumable admission. No reroll choice, result,
regret, reward, or action-quality label is serialized. Malformed captured bytes,
controller-provenance drift, unsafe mixed batches, loader byte drift, invalid
continuation, and nondeterministic writer bytes are regression failures. Every
other nested shape remains rejected. The loader must never be widened to "any
decision state" just to make a quota pass.

### BBS metadata namespace

BBS1's 12-byte record metadata calls its first field `replay_id`, but authored
states do not come from replays. Use a reserved synthetic ID namespace with the
high nibble `0xA`, derived from the stable recipe ID and variant. `cmd` stores
the capture decision index. `records.jsonl` must declare
`source_kind="authored"` so no report can mistake these IDs for FUMBBL games.
Strict replay filters must exclude this namespace by default.

### Per-record metadata

Every `records.jsonl` row includes at least:

- schema version, record index, synthetic source ID, recipe ID/version, variant
  seed, capture decision index, and raw match SHA-256;
- family and subfamily;
- train/dev/test split assigned by recipe-template group, never by record;
- half, both turn markers, active/decision team, score, kicking team, weather,
  rerolls, material counts, ball state/carrier, and procedure stack summary;
- legal-action count and SHA-256 of the sorted packed legal actions;
- family-specific axes and predicate facts; and
- transcript and dice SHA-256 references.

The manifest records `sizeof(bb_match)` and `bbe_state_fingerprint()`, but—as
with D191/D192—those are compatibility pins, not record-integrity proof.

## Two-pass deterministic compiler

### Pass 1: discovery

For each `(recipe_template, variant_seed)`:

1. initialize a real match from its dedicated procgen seed/stream, save its raw
   bytes, and attach a dice sink to the distinct game RNG before the first
   `bb_advance`;
2. let the template controller choose only from the current legal-action set;
3. record every packed action and every returned die face;
4. evaluate pure capture predicates only at engine decision boundaries;
5. stop at the recipe's bounded decision/dice/turn budget; and
6. reject a variant if it misses its declared capture quota or enters engine
   error.

Controllers may be family-specific, but must be deterministic functions of the
current match, legal actions, stable recipe parameters, and variant seed.
Controller tie-breaking is by packed action value unless the recipe declares a
different canonical order.

### Pass 2: exact replay

Reinitialize the same match from the procgen seed/stream, require initialized
raw-byte identity, inject the Pass-1 game-dice transcript with `bb_rng_script`,
and apply the recorded action transcript. Before every action:

- require `BB_STATUS_DECISION`;
- regenerate the legal set and require an exact packed-action match;
- require the decision team and declared checkpoint identity to match; and
- capture the declared states and compare their full bytes and fact rows with
  Pass 1.

At completion, require exact action count, exact dice consumption, no sticky RNG
error, no engine error, and byte-identical capture hashes. The Pass-2 matches—not
the discovery copies—are serialized into BBS1.

Serializer preflight repeats Pass 1 from configuration-only fields before it
performs Pass 2. It requires full recipe byte identity, including initialized
and captured matches, the complete action/dice/decision-team transcripts, their
counts, and all unused transcript capacity. This independently binds the
declared procgen and game seeds, plus every controller stream actually used, to
the bytes being serialized. Recipe kinds without a controller RNG require
canonical zero controller fields so inert values cannot masquerade as evidence;
successfully replaying a caller-supplied transcript is necessary but is not, by
itself, evidence that the declared seeds generated it. The complete mixed batch
is rediscovered, replayed, boundary-validated, and continuation-checked before
the writer emits even the BBS1 header.

## Family matrix

The implemented proof layer is deliberately narrower than this eventual bank
matrix. F1 now has a four-cell fresh-turn structural axis—Home/Away active-side
orientation crossed with open/marked carrier pressure—whose captures retain
the full zero-die legal Pass-opportunity predicate. Pressure is computed with
engine Tackle-Zone semantics after safe boundary validation; no receiver is
selected and no action-quality label is created. This does not satisfy the
broader F1 matrix below and does not authorize artifact publication or training.

The implemented cross-family composition layer now accepts exactly one
26-record proof bundle: four F1 axis records, four F2 axis records, sixteen F3
axis records, one F4 proof, and one F5 proof. It is order-independent and maps a
record to its primary family only through the exact recipe kind, preventing
overlapping opportunity facts from double counting. It reuses the complete
typed family validators, while the unchanged writer remains responsible for
independent rediscovery, exact replay, safe BBS admission, and one-action
continuation. This 4/4/16/1/1 bundle is not count-balanced and does not satisfy
the family matrix below. It is neither a canonical bank nor authorization for
sidecars, manifest publication, staging, or training.

The fixed proof bundle is now constructed by one production-owned in-memory
builder rather than duplicated test helpers. It pins the complete base recipe,
26 controller seeds, transcript counts, fixed order, and the existing
proof-local `0xA9000000 + index` BBS metadata. It validates in temporary heap
storage, leaves caller outputs unchanged on failure, copies all recipes only
after complete composition succeeds, and then constructs records pointing into
the caller-owned array. The A9 values preserve the reviewed proof artifact but
are positional compatibility metadata, not stable recipe IDs, versions,
variants, or sidecar keys. Persistent identity design, sidecars, balance,
splits, publication, staging, and training remain separate reviewed work.

The first complete bank is count-balanced across five families. Thin variants
fail the build rather than borrowing excess records from an easy family.

### F1 — Pass decisions

Capture both the fresh team-turn decision and, for a subset, the Pass target
decision after a legal declaration. Cross:

- half 1/2 and turns 2–8, emphasizing turns 6–8;
- tied/ahead/behind score states;
- quick/short/long/bomb range where roster PA and weather permit;
- open/marked thrower, open/marked receiver, and interceptor present/absent;
- safe continuation versus end-of-half desperation; and
- at least three race-pair templates spanning bash, hybrid, and agility.

The capture predicate requires a standing active-team carrier, a legal Pass
declaration, and at least one legal receiver/target path. It does not label Pass
as correct.

### F2 — Hand-off decisions

Capture the team-turn and Hand-off target decisions. Cross:

- ordinary ball transfer, scoring Hand-off, and carrier-to-strong-piece transfer;
- one versus multiple legal receivers;
- receiver open/marked and carrier open/marked;
- half/turn/score/material/reroll context; and
- both team orientations.

The predicate requires a legal Hand-off declaration and real target choice. It
does not pay or label the action.

### F3 — second-half and late-drive context

Capture fresh team-turn decisions reached by playing through the real end-of-
drive and halftime procedures. Cross:

- half 2 turns 1–8, with fixed minimum quotas for turns 5–8;
- tied/ahead/behind and receiving/kicking histories;
- both possession teams plus loose ball;
- material advantage/even/disadvantage; and
- reroll budget 0/1/2+.

This family exists to de-censor context. It is not duplicated into every other
family count merely because another capture also occurs in half 2; overlap is
reported separately.

### F4 / S7 — contextual reroll windows

Capture pending `USE_REROLL`/`DECLINE_REROLL` decisions for at least:

- Dodge, Rush, Pickup, Pass, Catch, activation gate, and block-dice reroll;
- team reroll plus applicable Skill/Pro alternatives where implemented;
- early/late half, tied/ahead/behind, carrier/noncarrier, and turnover severity;
- reroll budget 1 versus 2+; and
- both native team orientations.

The state itself is the training input. A separate evaluation process may fork
the same captured state into use/decline branches with common downstream dice
and report terminal utility/regret distributions. Those diagnostics are never
copied into BBS1, observations, masks, rewards, or BC labels.

### F5 / S8 — score now versus Stall

Capture fresh team-turn and carrier-activation decisions for which
`bb_can_score_without_dice` is true. Cross:

- current team turns 1–8, preserving the exact Crowd Takes Action thresholds;
- half 1/2, tied/ahead/behind, and opponent turns remaining;
- receiving order, material advantage/even/disadvantage, and reroll budget;
- defense one-turn-score threat present/absent; and
- Steady Footing present/absent only where legal roster generation supplies it.

The bank must include both score-immediately and wait-available states, but it
must not encode which is strategically preferred. Paired common-random-number
rollouts may estimate match-value differences in `counterfactuals.jsonl` for
held-out diagnosis only. D193's real crowd roll remains part of every resumed
episode.

## Balance and split policy

- Choose a fixed record quota per family before generation. Family overlap is
  allowed but one physical record has one primary family for balancing.
- Within a family, cap every recipe template and variant seed so a single easy
  trajectory cannot dominate.
- Assign 70/15/15 train/dev/test by stable hash of the recipe-template group.
  All variants, captures, and paired counterfactual branches from a template
  stay in one split.
- Macro-report family, subfamily, half, turn band, score state, race pair,
  material, rerolls, orientation, and overlap counts. Never smooth away a thin
  cell.
- A future training bank contains train records only. Dev/test state bytes and
  every counterfactual result remain evaluation-only artifacts.

## Test-first implementation order

1. **BBS writer and validator contract.** Start with a deliberately tiny legal
   recipe. Prove header/metadata bytes, loader acceptance, exclusive
   publication, malformed transcript rejection, and deterministic rerun.
2. **Transcript engine.** Add a failing Pass-2 test for an illegal action, one
   missing/extra die, decision-team drift, sticky RNG error, and state-byte
   mismatch; then implement exact replay.
3. **No-surgery boundary.** Keep recipe controllers in a module that receives a
   `const bb_match*` and legal-action array and returns an action/capture
   decision. Only the engine owns the mutable match. Review rejects casts or
   direct writes outside initialization by engine APIs.
4. **One-action continuation.** For every emitted record, reload its raw match,
   choose a canonical legal action, apply it with a fresh bounded scripted dice
   suffix, and require a valid decision/running/terminal result rather than
   engine error. Record totals in the report.
5. **Proof recipes.** Land one deterministic F1, F2, F3, F4, and F5 recipe with
   focused semantic assertions before adding quotas or search.
6. **Axis expansion.** Add templates one family at a time. Every new template
   must first fail its quota/axis test, then satisfy it without relaxing an
   existing family.
7. **Canonical build.** Run optimized and ASan/UBSan compilers, compare all
   output bytes, run the environment loader and forced demo-reset smokes, and
   publish only the optimized transaction with both validation identities in
   its manifest.

The phase-1 writer now enforces the core of step 4 before emitting any batch:
it validates the fresh-team-turn BBS1 boundary for F1/F2/F3/F5 or the exact
pending-Dodge resumable shape for F4, selects the lowest packed legal action,
applies that action to a private copy with a 256-face all-ones scripted suffix,
and rejects RNG exhaustion or engine error. The Puffer integration test repeats
the gate on the actually reloaded record. The continuation helper and loader
accept the same separately validated pending-Dodge reroll shape. Family
compilers must still record
the reconciled per-record totals in their report and manifest.

The first F3 proof recipe uses a third, independent controller RNG stream to
play through real drives and halftime. Its fixed test trajectory reaches half
two at a fresh team-turn boundary with active-team turn 5 after 660 legal
decisions and 175 in-match dice. The test requires byte-identical independent
rediscovery, exact replay, safe serialization, production-loader byte identity,
and one-action continuation. This proves one tied-score late-second-half
template only; it does not establish F3 axis coverage, quotas, or publication.

The first F3 axis tranche now establishes exact half-two turn/orientation
coverage without replacing that legacy late-F3 proof. A separate recipe kind
stores the requested turn and active side, and only that kind may carry the
axis fields. Its structural quota contract requires exactly one fresh-team-turn
capture for each turn 1 through 8 under Home and Away active-side orientation:
16 cells, not `BB_TEAM_COUNT * 8` (the former is a 30-entry roster catalogue).
Each fixed cell uses a distinct controller seed from 1000 through 1015 and must
independently rediscover, exact-replay, serialize, reload byte-identically, and
continue for one canonical action. The quota validator rejects missing,
duplicate, mismatched, or non-axis recipes; the writer remains the authoritative
provenance/replay/admission gate. Independent optimized and ASan/UBSan sweeps of
controller seeds 0-255 across all 16 cells agree exactly: 4,088 captures, 8
clean match ends (turn-one only), and zero unexpected failures. This is only a
turn/orientation coverage proof. It does not cover score, possession, receiving
history, material, reroll budget, roster, race pair, tactical quality, sidecars,
reports, manifest-last publication, training, rewards, evaluation, or deployment.

The first F1 proof also stays at the fresh-team-turn boundary. Its fixed
trajectory reaches half two, away turn 1, tied 0-0 after 414 legal decisions and
108 in-match dice. An input-preserving validator requires a non-dash-PA,
non-No-Ball carrier, copies that state, selects the legal carrier activation and
Pass declaration, requires both transitions to consume zero dice, and requires
at least one legal Pass target occupied by a standing, tackle-zone-capable
teammate without No Ball.
The copy is discarded. The ordinary raw match necessarily retains its ball
carrier, but no separate carrier/action/target metadata, chosen action, target,
or nested frame is serialized or treated as a policy label. This proves one
opportunity template, not passing quality, F1 axis coverage, quotas, or
publication.

The first F2 proof reuses the same fixed legal trajectory and captures the same
half-two, away-turn-1, tied 0-0 fresh-team-turn boundary after 414 legal
decisions and 108 in-match dice, with away slot 23 holding the ball. Its
input-preserving private probe selects the carrier's legal activation and
Hand-off declaration, requires both transitions to consume zero dice, and
requires at least one adjacent legal target that can actually attempt the
Catch. The probe, declaration frame, target set, and any chosen target are
discarded; only the ordinary pre-activation raw state is serialized. A
Standing No Ball teammate remains rules-legal as a Hand-off target under D198,
but a target set containing only No Ball players does not satisfy this authored
transfer-opportunity predicate. This proves one Hand-off opportunity template,
not Hand-off quality, F2 axis coverage, quotas, target-window validation,
publication, or training authorization.

The first F2 axis tranche now adds exactly four fresh-team-turn cells without
replacing that legacy proof: Home/Away active-side orientation crossed with
exactly one versus two-or-more legal catch-capable Hand-off targets. A shared
input-preserving counter first applies the complete raw BBS boundary validator,
then uses a discarded private copy to perform the carrier's legal activation
and Hand-off declaration with zero dice. It counts qualifying target actions
for which `bb_can_catch` is true, preserving D198/D199's distinction between a
rules-legal No Ball Hand-off target and a target that can attempt the Catch.
The requested side and target bucket are stored in the recipe and independently
rediscovered; the target bucket must be zero for every other recipe kind, and
two-or-more is explicitly a bucket rather than exactly two. Fixed controller
seeds Home/multiple 2, Home/one 4, Away/one 8, and Away/multiple 13 bind exact
action/dice counts, replay bytes, deterministic writer bytes, loader identity,
and one-action continuation. The structural quota rejects missing, duplicate,
mismatched, non-axis, and malformed captures, including adversarial stack
depths 0, 1, 33, and 255 before any unchecked frame access. Matching optimized
and ASan/UBSan sweeps over seeds 0-4095 for every cell produce 1,246 Home/one,
994 Home/multiple, 1,189 Away/one, and 1,291 Away/multiple captures; all other
attempts end cleanly and zero fail unexpectedly. This proves reachability and
target-count/orientation structure only. Target marking, receiver identity,
scoring range, carrier pressure, score/clock, roster/race, tactical quality,
publication, training, reward changes, evaluation, and deployment remain
separate contracts.

The first F5 proof uses controller seed 410 and reaches a loader-valid half-one,
home-turn-2, tied 0-0 fresh-team-turn boundary after 51 legal decisions and 19
in-match dice. Home slot 6 holds the ball at `(19, 10)` with MA 6, exactly six
squares from its end zone. The validator uses the engine's
`bb_can_score_without_dice` predicate, which excludes any path requiring a
Dodge, Rush, compulsory activation gate, or other supported compulsory roll.
On a discarded private copy it then selects the carrier's legal activation and
Move declaration, requires zero dice, and requires End Activation to remain
legal without moving or scoring. This establishes a genuine score-now versus
Stall policy surface under D193. It does not apply either choice, enumerate or
serialize a scoring path, resolve the Crowd Takes Action roll, or label which
choice is strategically correct. This proves one F5 opportunity template, not
clock/score/threat/Steady-Footing axes, tactical quality, quotas,
counterfactuals, publication, or training authorization.

The first F4 proof uses controller seed 1 and reaches the loader's exact nested
pending-Dodge shape after 384 legal decisions and 110 in-match dice. Away slot
17 has failed a first-step, non-Rush Dodge toward `(14, 6)` on a 3+ while Team
Re-roll, Dodge, and Decline are all genuinely legal. The action transcript ends
with that Step; capture happens before any of those three choices, so neither a
reroll action nor its result is serialized. Independent rediscovery and exact
replay reproduce the raw bytes. The writer permits resumable admission only for
this recipe kind, preflights mixed boundary/F4 batches before byte zero, and
emits byte-identical records across repeated writes. The production Puffer
loader recovers the same raw state, TEST context, deciding-coach masks, waiting-
coach null mask, and one-action continuation. This proves one F4 opportunity
template only; other TEST kinds, Rush-Dodge chains, later-step Dodges, F4 axes,
quotas, counterfactuals, sidecars, publication, training, and deployment remain
unauthorized.

D198 closes the two engine/helper gaps exposed while reviewing this proof: PA-
players no longer receive Pass declaration, and `bb_can_catch` now excludes No
Ball. No Ball players cannot intercept or receive a Touchback, while an
ordinary Pass may still target their occupied square and then Bounce. A
Standing No Ball team-mate with a Tackle Zone remains a legal Hand-off target,
then automatically fails the required Catch without a catch die. The F1
verifier retains its explicit guards as defense in depth.

## Acceptance gates

The tranche is complete only when all are true:

- normal and ASan/UBSan project suites pass;
- every emitted record passes the hardened state-bank loader;
- every recipe replays every action and die exactly from initialization;
- every captured match is byte-identical across discovery, replay, second
  compiler run, and optimized/sanitized builds;
- all records pass one-action continuation without fallback or engine error;
- family and required axis quotas reconcile exactly with the report;
- train/dev/test groups are disjoint by recipe template;
- no replay outcome or counterfactual field enters the BBS, observation, mask,
  reward, or BC path;
- the manifest binds the merged Git/tree identity, clean tracked sources,
  compiler binary/sources/flags, command, specs, all sidecars, and output hashes;
  and
- PR review plus exact-head CI pass before merge.

## Future training protocol (not authorized by this plan)

When a GPU is free and a separate experiment plan is reviewed:

1. stage the exact train-bank hash into an isolated future-build checkout;
2. compare kickoff-only control against a balanced authored-bank arm with
   `demo_reset_pct <= 0.5`;
3. graduate through smaller warm-started mixtures (for example 0.50, 0.25,
   0.10) before a final-quarter kickoff-only stage at exactly 0;
4. evaluate only from kickoff (`demo_reset_pct=0`) with common seeds, both
   roles, fixed anchors, forced matchup strata, and unchanged reward; and
5. treat family metrics and BBTV as diagnostics, never promotion evidence.

Do not interrupt the vacation queues to make this happen. The current primary
and reviewed overflow already reserve the 2070's vacation capacity; authored
bank work can proceed on CPU and enter only a later source-pinned build.

## Explicit residuals

- The 454-way policy interface does not yet expose “forego this one player and
  continue the turn”; it only exposes whole-team `END_TURN`. F5 must report that
  limitation and cannot claim full Stalling policy coverage.
- Fumblerooski is not implemented, so its FAQ Stalling interaction cannot be a
  recipe axis yet.
- Steady Footing currently auto-rolls and does not expose its FAQ-permitted team
  reroll decision. F4 must not fabricate that missing window.
- The current training binding uses one process-global staged bank path. A typed
  future experiment installer must pin and stage the selected bank before
  process start; changing the live global path is outside this tranche.
