# Authored proof sidecar schema

Status: schema-design tranche only; no serializer, filesystem publication,
bank construction, training input, or deployment authorization.

## Objective and dependency

Define the canonical metadata contract that will eventually accompany the
fixed 26-record authored proof bundle without changing its reviewed BBS1 bytes.
The sidecars must join the proof-local BBS metadata
`0xA9000000..0xA9000019` to the immutable authored identity allocations
`0xAE000001..0xAE00001A`, preserve complete recipe provenance, describe the
captured decision state, and contain no action-quality label.

`docs/RECOMMENDED_ORDER.md` is absent. The live fallback order is the authored
bank plan plus D207-D213. PR #42 merged the closed identity registry and its
protected history authority as main commit
`5c0874c4766a5d819460c67b73592c29a55afbe2`. That resolves the durable join
key but does not authorize a serializer or transaction. This tranche therefore
settles schemas and hash preimages only. A later test-first implementation must
consume this plan without widening it; manifest-last filesystem publication is
another later tranche.

## Artifact boundary

The future serializer will produce two byte streams in memory:

- `records.jsonl`: one row for every BBS record, in the exact legacy proof
  schedule order; and
- `recipes.jsonl`: one row for every corresponding recipe, in the same order.

The streams are a pair. Neither is valid alone. They contain exactly 26 lines,
end every line with one LF byte, contain no blank lines, byte-order mark,
comments, trailing spaces, or terminal data after the 26th LF, and use only
ASCII bytes `0x20..0x7e` plus LF. The future transaction must bind both hashes
and the unchanged BBS hash in its manifest, but the manifest and transaction do
not exist in this tranche.

The sidecars do not replace the BBS metadata. `records.jsonl` carries both the
legacy positional `bbs_source_id` and durable `authored_source_id` so a reader
must reconcile rather than reinterpret either namespace. No AE identity is
written into the BBS1 record header.

## Canonical JSON rules

Every line is one compact JSON object with keys in the exact order declared
below. There is no insignificant whitespace. Writers emit `:` and `,` without
spaces. Arrays retain their declared order. Object keys are never sorted at
runtime; the schema owns their order. Strings use JSON double quotes and the
minimal required escapes. Current values are restricted to validated ASCII,
lowercase hexadecimal, or fixed lowercase enum tokens, so no Unicode escape is
expected in revision 1.

Numbers use the shortest base-10 integer spelling, with `0` as the only zero
spelling and no leading plus sign or zeroes. Signed values use a single leading
minus. Every `uint64_t` value is instead encoded as exactly 16 lowercase
hexadecimal characters in a JSON string, preventing loss in consumers whose
JSON number type is IEEE-754 double. SHA-256 values are exactly 64 lowercase
hexadecimal characters. The bit identity of the one floating procgen field is
encoded as exactly eight lowercase hexadecimal characters; no JSON float is
emitted.

Schema names and versions are immutable. Adding, deleting, reordering, or
reinterpreting a field requires a new schema token. A consumer must reject an
unknown token, extra or missing key, wrong key order, noncanonical scalar,
duplicate JSON key, or trailing bytes. It must never silently project a newer
row onto this schema.

### Scalar and enum authority

The following table is part of revision 1, not illustrative prose. Every
integer is a JSON number unless the table says it is a quoted hexadecimal
string. The additive sidecar authority must freeze the cited enum declarations,
the generated team catalogue, and these mappings before any serializer exists.

| Schema value | Canonical JSON and accepted domain | Derivation authority |
| --- | --- | --- |
| `u64hex` | JSON string of exactly 16 lowercase hex digits | object bits of one `uint64_t` |
| `f32bits` | JSON string of exactly 8 lowercase hex digits | `memcpy` of one finite `float` to `uint32_t`; the procgen percentage must decode in `[0.0,1.0]` |
| SHA-256 | JSON string of exactly 64 lowercase hex digits | 32 digest bytes in byte order |
| Boolean | JSON literal `true` or `false` only | reviewed predicate, never integer truthiness |
| Team side | `0` = Home, `1` = Away | `BB_HOME`, `BB_AWAY`; all other values reject |
| Team roster | `0..BB_TEAM_COUNT-1` | generated `bb_team_id` declaration and generated catalogue; `exclude_team` alone additionally permits `-1` |
| Weather | `0` sweltering, `1` sunny, `2` perfect, `3` rain, `4` blizzard | `bb_weather`; all other values reject |
| Ball state token | engine `0` -> `off-pitch`, `1` -> `ground`, `2` -> `held`, `3` -> `in-air` | `bb_ball_state`; numeric engine value is not emitted |
| Recipe kind | `0` first-team-turn, `1` legacy-F3, `2` legacy-F1, `3` legacy-F2, `4` F5, `5` F4, `6` exact-F3, `7` exact-F2, `8` exact-F1 | `ad_recipe_kind`; `AD_RECIPE_KIND_COUNT` rejects |
| F2 bucket | `0` none, `1` exactly-one, `2` two-or-more | `ad_f2_target_count_bucket` |
| F1 pressure | `0` none, `1` open, `2` marked | `ad_f1_carrier_pressure_bucket` |
| Procedure ID | integer `0..28` | exact `bb_proc` declaration: none, match, pregame, setup, kickoff, team-turn, activation, move, dodge, rush, pickup, block, push, knockdown, armour, injury, casualty, pass, catch, scatter, throw-in, handoff, foul, TTM, test, touchdown, turnover, end-drive, KO-recovery; `BB_PROC_COUNT` rejects |

The current valid record shapes are exactly procedure arrays `[1,5]` for a
fresh team-turn and `[1,5,6,7,24]` for the admitted F4 pending-Dodge window.
The generic numeric procedure range does not admit another stack shape.

Record scalar ranges and cross-field rules are exact:

- `record_index` is `0..25`; `bbs_source_id` is
  `0xA9000000 + record_index`; identity fields must equal the immutable mapper
  result; and `capture_decision_index` is `0..8191` and equals `action_count`.
- `legal_actions_count` is `1..BB_LEGAL_MAX` after packed-action uniqueness;
  `half` is exactly `1` or `2`; each turn marker is `0..8`, while the active
  team's marker is `1..8` and must satisfy the exact family/capture predicate.
  An inactive side that has not begun its first turn in a half canonically
  remains at `0`. Team-valued fields are `0` or `1`; score and
  available-reroll fields are `0..255` from their captured `uint8_t` storage.
- Each emitted player-location count is `0..16`. For each team, pitch,
  reserves, KO, casualty, sent-off, and un-emitted absent counts reconcile to
  exactly 16 validated slots. No slot may be counted twice.
- `ball_carrier` is `0..31` if and only if `ball_state` is `held`; otherwise it
  is `-1`. The carrier must be a valid on-pitch player consistent with the
  admitted boundary.
- `procedure_depth` equals the array length and is exactly `2` or `5`; the
  array must equal the corresponding frozen shape above.
- Inactive family fields are canonical: F1 `none`, F2 `none`, F3 turn `0` and
  orientation `none`, F4 empty array, and both F5 booleans `false`, except for
  fields belonging to the row's one exact primary family.

Recipe scalar ranges and cross-field rules are exact:

- All six seeds/streams and `variant_seed_u64` are `u64hex`. F3 capture turn is
  `1..8` only for exact-F3 and `0` otherwise. Capture active side is `0` or `1`
  only for exact F1/F2/F3 and is canonical `0` otherwise. F1/F2 buckets are
  their declared values only for their exact family and canonical `0`
  otherwise.
- `home_team` and `away_team` are valid, distinct roster IDs;
  `exclude_team` is `-1` or a valid roster ID and must satisfy the reviewed
  procgen exclusion contract. The additive authority pins all 30 generated
  roster IDs rather than trusting a future catalogue with the same count.
- `skillup_max_players` is `0..16`; `skillup_max_each` is `0..12`; and the
  finite decoded secondary percentage is in `[0.0,1.0]`.
- `action_count` is `0..8191`; the discovery loop rejects
  `AD_MAX_ACTIONS == 8192`, so array capacity is not an admitted inclusive
  value. `dice_count` is `0..8192`: the sink may fill its final element and
  capture before another die would overflow. Each count equals its parallel
  array lengths. Every action is a valid packed `uint32_t` legal at its replay
  step; every decision team is `0` or `1` and equals the engine decision team.
  Every die side is `1..255`, every face is `1..sides`, and exact replay
  consumes both used prefixes completely.

## `records.jsonl` revision 1

The schema token is `bloodbowl-authored-record-v1`. Each row has these keys in
this exact order:

1. `schema`: the schema token.
2. `record_index`: zero-based position in the frozen legacy proof schedule.
3. `source_kind`: literal `authored`.
4. `bbs_source_id`: unsigned proof-local A9 source ID from the BBS header.
5. `capture_decision_index`: unsigned BBS `cmd` value; it must equal the
   rediscovered recipe action count.
6. `identity_schema_version`: exactly `1`.
7. `authored_source_id`: immutable AE allocation.
8. `template_id`: immutable template allocation.
9. `template_key`: immutable canonical template key.
10. `recipe_revision`: exactly `1`.
11. `cell_id`: immutable semantic cell allocation.
12. `variant_id`: immutable template-revision variant allocation.
13. `variant_seed_u64`: 16-character lowercase hexadecimal controller/variant
    seed identity.
14. `family`: one of `f1`, `f2`, `f3`, `f4`, or `f5`, derived only from the
    identity's permitted recipe kind.
15. `boundary`: `fresh-team-turn` for F1/F2/F3/F5 or
    `pending-dodge-reroll` for F4.
16. `raw_match_sha256`: SHA-256 of exactly `sizeof(bb_match)` captured bytes.
17. `initialized_match_sha256`: SHA-256 of exactly `sizeof(bb_match)`
    initialized bytes.
18. `actions_sha256`: digest of the framed action/decision-team transcript
    defined below.
19. `dice_sha256`: digest of the framed dice transcript defined below.
20. `legal_actions_count`: count of unique legal packed actions at capture.
21. `legal_actions_sha256`: digest of the framed sorted legal-action set.
22. `half`: captured half.
23. `home_turn`: captured home turn marker.
24. `away_turn`: captured away turn marker.
25. `active_team`: captured active-team enum value.
26. `decision_team`: deciding-team enum value at capture.
27. `home_score`: captured home score.
28. `away_score`: captured away score.
29. `kicking_team`: captured kicking-team enum value.
30. `weather`: captured weather enum value.
31. `home_rerolls`: captured home rerolls available.
32. `away_rerolls`: captured away rerolls available.
33. `home_players_pitch`: valid present home players on the pitch.
34. `away_players_pitch`: valid present away players on the pitch.
35. `home_players_reserve`: valid present home players in reserve.
36. `away_players_reserve`: valid present away players in reserve.
37. `home_players_ko`: valid present home players knocked out.
38. `away_players_ko`: valid present away players knocked out.
39. `home_players_casualty`: valid present home players in casualty.
40. `away_players_casualty`: valid present away players in casualty.
41. `home_players_sent_off`: valid present home players sent off.
42. `away_players_sent_off`: valid present away players sent off.
43. `ball_state`: one of `ground`, `held`, `in-air`, or `off-pitch`, derived from the
    validated engine ball representation.
44. `ball_carrier`: player slot `0..31` when held, otherwise `-1`.
45. `procedure_depth`: validated procedure-stack depth.
46. `procedure_ids`: bottom-to-top array of numeric procedure IDs.
47. `f1_carrier_pressure`: `none`, `open`, or `marked`.
48. `f2_handoff_targets`: `none`, `one`, or `two-or-more`.
49. `f3_capture_turn`: requested second-half turn `1..8`, otherwise `0`.
50. `f3_orientation`: `none`, `home`, or `away`.
51. `f4_reroll_options`: for F4 only, an array in fixed token order `decline`,
    `dodge`, `pro`, `team`, containing exactly the available options; empty for
    every other family. The array describes legality, not preference. The
    packed-action mapping is exact: `decline` =
    `{BB_A_DECLINE_REROLL,0,0,0}`, `dodge` =
    `{BB_A_USE_REROLL,BB_RR_SKILL,BB_SK_DODGE,0}`, `pro` =
    `{BB_A_USE_REROLL,BB_RR_PRO,0,0}`, and `team` =
    `{BB_A_USE_REROLL,BB_RR_TEAM,0,0}`. Leader, another skill, duplicate
    packed actions, or another encoding rejects. The fixed F4 row derives
    exactly `decline`, `dodge`, `team`. The `pro` mapping is frozen to make the
    token unambiguous but cannot appear in this closed 26-row revision-1
    object; any expanded object requires a later schema.
52. `f5_score_without_dice`: `true` only when the reviewed exact scoring
    predicate holds on an F5 row; it is canonically `false` for every non-F5
    row. The fixed F5 proof row is rejected unless this field derives as
    `true`.
53. `f5_end_activation_legal`: `true` only when the reviewed private
    declaration probe retains End Activation on an F5 row; it is canonically
    `false` for every non-F5 row. The fixed F5 proof row is rejected unless
    this field independently derives as `true`.

No split appears in revision 1. The five template keys are also the current
five primary families, so a 70/15/15 template-group split would necessarily
assign whole families and cannot be presented as balanced or training-ready.
Split policy belongs to the later balanced-bank/general-compiler design.

No roster name, human interpretation, tactical-quality score, action, receiver,
or target selected or recommended at or after capture, separate receiver or
target label, counterfactual return, regret, value, reward, winner, or
recommended choice may appear. The historical packed action transcript is
necessary replay provenance: it stops strictly before capture, only explains
how the state was reached, and can contain historical action arguments,
receivers, and spatial targets. It is forbidden as behavior-cloning, policy,
receiver/target, or action-quality supervision.

## `recipes.jsonl` revision 1

The schema token is `bloodbowl-authored-recipe-v1`. Each row has these keys in
this exact order:

1. `schema`.
2. `record_index`.
3. `identity_schema_version`.
4. `authored_source_id`.
5. `template_id`.
6. `template_key`.
7. `recipe_revision`.
8. `cell_id`.
9. `variant_id`.
10. `variant_seed_u64`.
11. `procgen_seed_u64`.
12. `procgen_stream_u64`.
13. `game_seed_u64`.
14. `game_stream_u64`.
15. `controller_seed_u64`.
16. `controller_stream_u64`.
17. `recipe_kind`: stable numeric `ad_recipe_kind` value; revision 1 freezes
    the existing numeric enum identity as well as the template-kind mapping.
18. `capture_turn`.
19. `capture_active_team`.
20. `capture_handoff_target_bucket`.
21. `capture_pass_carrier_pressure`.
22. `home_team`.
23. `away_team`.
24. `exclude_team`.
25. `skillup_max_players`.
26. `skillup_max_each`.
27. `skillup_secondary_pct_bits`: eight lowercase hexadecimal characters.
28. `initialized_match_sha256`.
29. `raw_match_sha256`.
30. `action_count`.
31. `actions`: ordered array of unsigned packed action integers.
32. `decision_teams`: ordered array of numeric team values, exactly parallel
    to `actions`.
33. `actions_sha256`.
34. `dice_count`.
35. `dice_sides`: ordered array of unsigned die-side integers.
36. `dice_values`: ordered array of unsigned returned-face integers, exactly
    parallel to `dice_sides`.
37. `dice_sha256`.

Only the used transcript prefixes are serialized. Unused fixed-capacity recipe
storage is writer provenance and remains covered by rediscovery equality, but
it is not metadata. Counts must be nonnegative, within the reviewed recipe
caps, and equal their parallel array lengths. Every decision-team value must
match rediscovery. Every die must have valid sides and face, and the complete
transcript must be consumed by exact replay.

The recipe row deliberately repeats identity and digest fields from the record
row. A future reader must require equality rather than choosing one side as
authoritative. This catches line reordering, partial joins, and pairwise
substitution.

## Hash preimages

All multibyte integers in hash preimages are unsigned little-endian. Counts are
`uint32_t`; a value that cannot fit fails before hashing. Each domain begins
with exactly seven bytes, shown here in hexadecimal to remove C-string
ambiguity: actions `42 42 41 43 54 31 00`, dice
`42 42 44 49 45 31 00`, and legal actions
`42 42 4c 45 47 31 00`. A C implementation hashes `sizeof "BBACT1"`,
`sizeof "BBDIE1"`, or `sizeof "BBLEG1"` bytes respectively; it must not add an
explicit `\0` inside the literal and thereby hash two NUL bytes.

- `actions_sha256` hashes the seven-byte actions tag, action count, then for
  each index the packed `uint32_t` action followed by the one-byte decision
  team.
- `dice_sha256` hashes the seven-byte dice tag, dice count, then for each index
  the one-byte sides followed by the one-byte returned face.
- `legal_actions_sha256` hashes the seven-byte legal tag, unique-action count,
  then the ascending unique packed `uint32_t` actions.
- match digests hash the raw object bytes only. Their field names and the
  manifest's separate `sizeof(bb_match)` and engine fingerprint pins provide
  the domain. Hashing raw `bb_match` bytes does not claim portability across a
  different ABI or engine build.

Transcript domains are independent so an identical byte suffix cannot migrate
between actions, dice, or legal sets. The future implementation must prove the
preimages against an independent standard-library SHA-256 oracle and known
empty/single/multi-element vectors.

## Reconciliation contract

Before producing byte zero, the future serializer must:

1. build the fixed proof bundle through `ad_build_authored_proof_bundle`;
2. validate its exact 26-record composition;
3. map every recipe through `ad_identify_authored_proof_bundle`;
4. require record pointers to reference the corresponding recipe objects;
5. require each A9 BBS source ID and capture decision index to match the frozen
   legacy schedule and recipe action count;
6. reorder a validated caller permutation into serializer-owned legacy-schedule
   records, invoke the unchanged public `ad_bbs_write` exactly once for that
   complete bundle through a reviewed serializer-owned memory-backed `FILE *`
   adapter, successfully flush and close it, require the resulting BBS bytes to
   equal the frozen oracle, and discard them; this is the only permitted route
   through the ordinary writer's rediscovery, exact-replay, admission, and
   continuation authority;
7. validate the already writer-admitted captured fresh/resumable boundary
   before reading dynamic player, ball, procedure, or legal-action facts;
8. treat the successful writer call as the continuation proof rather than
   duplicating or bypassing its private checks;
9. derive each family-specific fact through the already reviewed predicate,
   never by trusting an enum label alone;
10. build all 26 typed rows and both complete JSONL byte streams in
    serializer-owned checked staging storage;
11. verify the one-to-one A9-index/AE-identity/record/recipe joins and all
    repeated-field equality; and
12. after every fallible operation, join, digest, length, and capacity check
    succeeds, perform one final non-failing `memcpy` to each disjoint caller
    output and return success. No error path exists after the first commit copy.

The memory-backed writer adapter is part of the future additive sidecar proof.
On supported POSIX hosts it uses `open_memstream` (or an authority-reviewed
equivalent with identical no-path semantics), never `tmpfile`, a pathname, or
publisher-owned storage. This preserves the pure in-memory/no-filesystem
boundary while exercising the real public writer. The serializer must not
factor, expose, duplicate, or reorder a new preflight API: D209 freezes the
existing writer and its exact shared preflight control structure. The adapter
uses an authority-pinned feature-test/declaration mode, passes owned buffer and
length pointers, requires writer success followed by successful flush/close,
then compares exactly the returned length bytes. The stream's convenience NUL
is not part of the BBS preimage. The required stream is exactly 58,568 bytes
with SHA-256
`c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1`;
the adapter frees its buffer on every applicable path before any caller-output
commit.

Inputs, outputs, scratch, and error storage must be disjoint under checked
extents. Null, count, capacity, overlap, arithmetic overflow, malformed state,
unknown identity, transcript drift, digest mismatch, or JSON capacity failure
must leave caller-owned outputs byte-for-byte unchanged. Diagnostic text is not
part of either sidecar and must never alias protected input/output storage.
This is call-level failure atomicity: no recoverable failure can expose one
sidecar without the other. It does not claim process-crash atomicity; the later
filesystem transaction must provide that separately.

The pure serializer must accept a caller permutation of recipes only if the
records and identity results establish the same complete one-to-one set. Output
order is always the immutable legacy BBS schedule, never caller order, pointer
order, source numeric sort, or template sort.

## Test-first implementation plan

The next implementation tranche starts with failing tests and does not add
filesystem writes.

1. **Canonical scalar and JSON tests.** Pin integer, `uint64_t`, enum, boolean,
   string-escape, lowercase-hex, key-order, LF, and capacity behavior. Reject
   noncanonical template keys and impossible enum/fact combinations. Pin real
   opening `home_turn`/`away_turn` pairs `1/0` and `0/1`, the active-side
   `1..8` constraint, action-count maximum `8191`, and independently permitted
   dice-count maximum `8192`.
2. **Independent hash oracle.** Add NIST SHA-256 vectors plus independent
   standard-library calculations for empty, one-element, and multi-element
   action/dice/legal preimages. Prove count framing, endianness, domains, order,
   and decision-team inclusion.
3. **Protected writer adapter and typed row builder.** First call the unchanged
   public writer once through serializer-owned memory-backed `FILE *` storage,
   compare its complete BBS stream with the frozen oracle, and discard it. Only
   after that proof and registry/pointer/source/decision-index reconciliation
   may rows derive fields from the admitted states. Test every field against
   direct engine observations. Authority fixtures must reject a serializer that
   bypasses, duplicates, moves, or substitutes the writer call.
4. **Family facts.** Mutation-test every F1/F2/F3/F4/F5 field through its public
   predicate. Ensure inactive-family fields have their canonical empty value.
   No field may be accepted merely because the recipe kind claims it.
5. **Recipe rows.** Pin every projection field and both transcript arrays.
   Reject missing/extra/reordered action, decision-team, die-side, or die-value
   data and any used-prefix/count disagreement.
6. **Pair reconciliation.** Reject line swaps, duplicate/missing AE identities,
   A9 drift, pointer drift, digest disagreement, unequal repeated fields, and
   caller permutations that do not preserve the complete set. Accept valid
   recipe permutations while emitting the frozen legacy order.
7. **Failure atomicity.** Exercise null/short/long counts, zero/one-byte-short
   capacities, checked-size overflow, every input/output/error alias direction,
   allocation failure, writer failure, and injected failure at every stage
   through the final row. Build both outputs in serializer-owned staging;
   verify no fallible operation remains once the two final copies begin. Inputs
   and both caller outputs remain byte-identical on every rejection.
8. **Determinism and preservation.** Optimized and ASan/UBSan builds must emit
   byte-identical `records.jsonl` and `recipes.jsonl` twice, while the existing
   58,568-byte BBS and 58,240-byte raw-body oracles remain unchanged.
9. **Additive authority bootstrap.** Never edit D209's immutable registry
   oracle, workflow, verifiers, or trusted probes. In a first, separately
   reviewed PR, add a new sidecar-specific oracle, candidate verifier, history
   verifier, malicious fixtures, and protected workflow with
   `pull_request_target`, `merge_group`, and main-push triggers. Each event must
   resolve and verify the exact candidate/base or before/after SHAs; merge-queue
   evidence is a pre-merge gate, while push verifies the resulting reachable
   history.

   The serializer-free bootstrap freezes a public declaration and ABI manifest,
   production source/header ownership, exact input record/recipe arrangement
   and count semantics, and the output pointer/capacity/returned-length/error
   and checked-alias contract. It also freezes the `open_memstream` adapter
   interface and feature-test mode, returned-length versus trailing-NUL rule,
   exact-once writer-call ordering, 58,568-byte BBS length/digest comparison,
   relevant ABI/layout facts, schema declaration, complete canonical oracles,
   and independent hash/preimage vectors. Trusted fixtures must include ABI,
   length/NUL, capacity/alias, writer-bypass/duplicate/reorder, oracle-mismatch,
   field omission/reinterpretation, and fallible-after-first-copy candidates.
   Length/NUL fixtures specifically reject `strlen`, filtering or stopping at
   embedded NULs, comparing `length + 1`, or including an early terminator;
   every embedded NUL within the returned `length` is ordinary BBS payload.
   The PR contains no production serializer body.

   The new protected runner inherits D210's complete isolation model: execute
   untrusted candidate code only in a fresh digest-pinned, tokenless,
   credentialless, networkless, non-root container with no capabilities or
   privilege gain; mount candidate and authority trees read-only; allow only
   bounded ephemeral scratch; use trusted compiler commands that ignore
   candidate build scripts; enforce per-phase, per-commit, and aggregate time
   limits; and forcibly tear down the container. Because a newly introduced
   `pull_request_target` workflow is not trusted from the base and cannot
   protect its own PR, bootstrap requires green ordinary CI, the exact
   digest-pinned local/native container command, and three exact-head reviews;
   the existing identity authority must also prove its frozen files unchanged.
   After merge, the new sidecar authority set and workflow become
   byte-immutable.
10. **Serializer under established authority.** Only after the additive
    authority workflow exists on the trusted base may a second PR implement
    the typed rows and canonical streams. The protected sidecar workflow must
    then verify every newly reachable serializer-bearing commit, including
    malicious candidates that omit, reorder, reinterpret, or add fields. The
    implementation may not modify either the identity authority or the new
    sidecar authority.
11. **Project gates.** Run complete optimized and sanitizer suites, static
    analysis, native Linux authority, digest-pinned container history, hosted
    CI, and three exact-head reviews. Any byte change invalidates prior reviews.

Only after both authority bootstrap and implementation are merged may a new plan design an output
directory, compiler CLI, report, counterfactual stream, or manifest-last
transaction.

## Acceptance gates for this design tranche

This schema-design tranche is complete only when:

- every field has one type, canonical encoding, derivation authority, and
  inactive-family value;
- record and recipe streams reconcile A9 proof order with AE durable identity
  without changing the BBS artifact;
- hash domains and exact byte preimages are specified independently of JSON;
- no action, receiver, or target selected or recommended at or after capture,
  and no separate receiver/target, reward, regret, outcome, value, split,
  curriculum-weight, or promotion label exists; pre-capture packed actions and
  their historical receiver/target arguments are replay provenance only and
  forbidden as learning supervision;
- failure atomicity, immutable-history authority, and test-first negative
  candidates are part of the implementation plan;
- `AGENTS.md`, `CLAUDE.md`, and the BB-validation skill repeat the sidecar
  boundary after review; and
- hosted CI plus three exact-head design reviews pass before merge.

## Explicitly out of scope

- C or Python serializer implementation, JSON library, SHA-256 implementation,
  compiler CLI, stdout protocol, or test probe that masquerades as a publisher;
- opening an output directory, temporary or final artifact files, `fsync`,
  exclusive links, aliases, manifest-last publication, or cleanup semantics;
- `authored-drills.bbs`, reports, counterfactuals, family rebalancing, search,
  quotas beyond the frozen proof object, or train/dev/test assignment;
- any state-bank loader or Puffer consumer, demo-reset path, BC/PPO input,
  staged bank, reward, evaluation, checkpoint selection, model promotion, or
  BBTV behavior; and
- any source, process, service, artifact, plan, or pin in either frozen vacation
  queue or either production checkout on the occupied RTX 2070.

This plan is metadata design only. Merging it authorizes the next serializer
implementation plan; it does not authorize publication or use.
