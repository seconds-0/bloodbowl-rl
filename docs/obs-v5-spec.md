# Obs-v5: decision-window observation truth

Obs-v5 keeps obs-v4's physical tensor shape—2,782 `uint8` values—but changes
the semantic ABI of reserved context/scalar bytes and Touchback action
projection. It is therefore a new policy/data lineage even though an obs-v4
checkpoint remains shape-loadable.

## Motivation

Obs-v4 exposes declaration-time block outcome probabilities, but it did not
expose the actual rolled block-die faces at the later reroll and choose-die
windows. The engine's scripted contact bot reads those faces directly. A learned
policy therefore had less public information than both the scripted policy and
a human player, and could not realize the owner-optimal die choice assumed by
the probability planes and block-EV diagnostics.

The same audit found four related information/addressability defects:

- a generic TEST exposed its target but not the kind of roll that failed;
- movement and Rush expenditure during the active activation were hidden;
- invalid coordinates for a non-`OFF_PITCH` ball could wrap into plausible
  observation bytes; and
- square-placement Touchbacks projected every candidate onto square sentinel
  390, making distinct fallback placements impossible to select exactly.

Obs-v5 repairs only these representation contracts. It does not change a game
rule, reward, engine state, observation size, or action-head size.

## Layout delta from obs-v4

Everything documented by `docs/obs-v4-spec.md` remains unchanged except the
following previously reserved bytes.

### Decision context (`BBE_CTX_OFF`, bytes 768–783)

Bytes 9 and 12 retain D201's egocentrically mirrored pending-Dodge destination.

| Relative byte | Obs-v5 meaning |
|---:|---|
| 13 | rolled block face 0 |
| 14 | rolled block face 1 |
| 15 | rolled block face 2 |

Faces use the engine's nonzero `bb_block_die` symbols, with its internal second
Push side normalized to the first Push code because the physical die shows the
same public symbol on both sides. Zero means no die in that slot. They are
emitted only when the top frame is `BB_PROC_BLOCK` phase 1 (pool reroll
decision) or phase 2 (choose-die decision). The number of
nonzero prefix bytes is the number of rolled dice. Raw faces are public and are
identical in home and away observations; attacker/defender player slots remain
egocentrically remapped in context bytes 6 and 7.

### Scalars (`BBE_SCALAR_OFF`, bytes 784–831)

| Relative byte | Obs-v5 meaning |
|---:|---|
| 19 | active MOVE player's `moved + 1`; zero when no valid MOVE frame exists |
| 20 | active MOVE player's `rushes + 1`; zero under the same condition |
| 21 | top TEST frame's `bb_test_kind + 1`; zero outside a valid TEST frame |

The encoder finds the nearest valid MOVE frame in the active procedure stack,
so movement expenditure remains visible while a nested TEST, BLOCK, or other
resolution window is on top. Plus-one encoding distinguishes a real zero-spent
activation from absence and makes Dodge (TEST enum zero) distinguishable from
no TEST.

### Ball coordinates

Ball x/y bytes are nonzero only when the state is not `BB_BALL_OFF_PITCH` *and*
`bb_on_pitch_xy(ball.x, ball.y)` is true. Invalid coordinates cannot wrap
through the away mirror into apparent on-pitch positions.

### Touchback action projection

`BB_A_TOUCHBACK` has two disjoint exact-action forms. A normal recipient action
remains `(type=TOUCHBACK, arg=egocentric player, engine square=0,0)`, but its
inactive square head canonicalizes to sentinel 390 for both sides. When no
eligible standing recipient exists, an engine fallback action remains
`(type=TOUCHBACK, arg=sentinel, square=x,y)`; its inactive argument canonicalizes
to 32 while each legal placement has its own mirrored square-head value and
exact decoding round-trips it.

Touchbacks remain addressable. The exact-action tranche now consumes the joint
support and samples sequential conditional heads, so a policy tuple always
names an offered engine action (or an explicit macro-move env action).

## Compatibility and experiment rules

- Physical shape stays 2,782, so checkpoint blob size and network parameter
  count cannot distinguish obs-v4 from obs-v5.
- `BBE_OBS_VERSION` is 5 and source/module provenance is mandatory.
- Newly extracted replay pairs use BBP version 4 for exact conditional action
  masks. Historical BBP v3/2782 is obs-v5 with marginal action masks and
  v2/2782 is obs-v4. The BC loader includes header version in its lineage key
  and rejects mixed lineages before opening training memmaps.
- Obs-v4 weights, replay-pair observations, and training curves are not
  semantically interchangeable with obs-v5 despite shape compatibility.
- Do not warm-start a v5 run from v4, compare their curves as one lineage, or
  merge their replay pairs without a separately reviewed bridge experiment.
- Current flat checkpoints require the canonical adjacent `.lineage.json` from
  `tools/checkpoint_lineage.py`. The record binds checkpoint content,
  obs-v5/exact-joint-v1 semantics, policy shape, producer manifest,
  source/module/Puffer-patch identities, and ancestry eligibility. Blob size,
  output-head sizes, filename, and location are never lineage evidence.
- The 50M exact-action canary starts fresh with no warm checkpoint, no external
  pool, and zero frozen banks. Its lineage is qualification-only and must be
  rejected as a warm start, pool seed, promotion candidate, or causal result.
- Re-extract behavioral-cloning observations under v5 before treating replay
  supervision as information-set matched.
- Existing live v4 runs and BBTV viewers keep their pinned builds until normal
  retirement. This specification does not authorize deployment over them.

## Validation contract

`puffer/bloodbowl/test_observation.c` independently constructs and mutates
decision frames to prove:

- every block face changes the corresponding byte at phases 1 and 2, unused
  face slots are zero, and both views see identical public dice;
- every TEST kind and nested movement counter is represented while the pending
  Dodge destination continues to mirror correctly;
- valid ball coordinates mirror and invalid/off-pitch coordinates zero;
- fallback Touchback candidates have distinct home/away projections and exact
  decode, while recipient Touchbacks remain addressable.

The full optimized and ASan/UBSan suites, installed-Puffer snapshot check,
float/fast builds, and repeatable post-change FNV hash remain merge gates.
