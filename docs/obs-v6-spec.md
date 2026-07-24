# Obs-v6: closing the addressable-but-invisible blind spots

Obs-v6 keeps the obs-v4/obs-v5 physical tensor shape — 2,782 `uint8` values —
and spends the 26 scalar bytes obs-v5 left permanently zero. It changes no game
rule, reward, engine state, observation size, action head, action encoding, or
BBP replay format. It is nevertheless a new policy/data lineage, and it is the
**third consecutive revision at the same size**, so the only discriminator is
`BBE_OBS_VERSION` and the provenance built on it.

Read `docs/obs-v5-spec.md` first: everything it documents still holds. This file
is the delta.

## Motivation

`docs/plans/obs-v6-blind-spot-inventory.md` audited all 13 decision procedures
for one shape: **the policy can ADDRESS a distinction in its action space that
it cannot SEE in its observation.** Two prior instances were real defects
(rolled block dice, D217; the executed-action mismatch, D218) and both
invalidated reward conclusions drawn before them. The inventory found ten more,
and the v6 batch closes them together because each observation change costs a
lineage break and shipping them piecemeal would be strictly worse.

Closed here (inventory section numbers):

- **P0-1** the PASS interception candidate list was 100% unobservable — up to 17
  distinct addressable options with zero observational content separating them,
  and the pass target square was unexposed so the ruler path was not even
  reconstructible;
- **P0-2** at every PUSH decision the block face is already gone (`resolve_face`
  pops the BLOCK frame before pushing PUSH), so whether the push was a POW, and
  whether it came from a blitz, were unrecoverable;
- **P0-3** the declared `bb_act_kind` appeared in no observation byte, at any
  window;
- **P0-4** both apothecary casualty rolls were invisible while the coach was
  asked to burn a once-per-match resource and then choose between them;
- **P1-5** the turnover latch and the Charge! context;
- **P1-6** the SETUP and kickoff placement budgets;
- **P1-7** the pending consequence square for Rush/Jump/Pass, not only Dodge;
- **P2-8** the MOVE frame's stashed target slot (the thrown team-mate);
- **P2-9** `ktm_used`, the one once-per-turn latch `s[8..13]` omitted;
- **P2-10** the ACTIVATION negatrait gate's target number.

Deliberately NOT done: giving player-valued `CHOOSE_OPTION` a spatial form
(inventory section 5, side finding 2). It would save 8 bytes but breaks the
action space and the BBP lineage on top of the observation break, inside D218's
exact-joint contract where a `bbe_decode` rejection aborts the engine. The
16-byte option table ships instead and 2 bytes of slack are accepted.

Also not done, and left as a known gap: `tools/bb_lockstep.c`, the BBP header
version table, and the BC loader still describe BBP v3 as "same-shape obs-v5".
BBP was out of scope for this revision, so a BBP v4 shard does not record which
observation revision produced it.

## Layout delta from obs-v5

Nothing moves. `BBE_OBS_SIZE` stays 2,782, so none of the three sync points
change (`BBE_OBS_SIZE` in `puffer/bloodbowl/bloodbowl.h`, `OBS_SIZE` in
`puffer/bloodbowl/binding.c`, `--obs-size` in
`training/convert_checkpoint.py`), and checkpoint input shape is preserved.

### Scalars (`BBE_SCALAR_OFF`, bytes 784–831)

`s[0..21]` are exactly as obs-v5 documents them. `s[22..47]` — obs offsets
**806–831** — were guaranteed zero in obs-v5 by `memset(o, 0, BBE_TZ_OFF)` and
now carry:

| `s[]` | Obs offset | Name | Meaning |
|---:|---:|---|---|
| 22 | 806 | `BBE_S_WINDOW_FLAGS` | proc-disambiguated window bits (below) |
| 23 | 807 | `BBE_S_ACT_KIND` | declared `bb_act_kind + 1`; 0 = no activation owns this window |
| 24 | 808 | `BBE_S_CAS_ROLL_A` | CASUALTY roll A (frame `x`); 0 outside the apothecary windows |
| 25 | 809 | `BBE_S_CAS_ROLL_B` | CASUALTY roll B (frame `y`); 0 at phase 1, where it does not exist yet |
| 26 | 810 | `BBE_S_STACK_FLAGS` | stack context bits (below) |
| 27 | 811 | `BBE_S_PLACEMENT_BUDGET` | remaining placements **+ 1**; 0 = not a placement window |
| 28 | 812 | `BBE_S_MOVE_TARGET` | MOVE frame's stashed target: ego slot + 1; 0 = no live stash |
| 29 | 813 | `BBE_S_KTM_USED` | `m->ktm_used` |
| 30–31 | 814–815 | — | **reserved, always zero** (the 2 bytes of slack) |
| 32–47 | 816–831 | `BBE_S_OPTION_TABLE` | `CHOOSE_OPTION` index → ego slot + 1; 0 = no such option, or a non-player option list |

A `_Static_assert` pins `BBE_S_OPTION_TABLE + BBE_S_OPTION_SLOTS` to the end of
the 48-byte scalar block, so the reservation cannot silently overflow into the
tackle-zone planes.

`BBE_S_WINDOW_FLAGS` bits, disambiguated by `ctx[4]` (the proc) exactly as
`ctx[8]` already is:

| Bit | Name | Source |
|---:|---|---|
| 0 | `BBE_WF_PUSH_POW` | PUSH `PSH_POW` — decides whether the pushee ends prone |
| 1 | `BBE_WF_PUSH_FROM_BLITZ` | PUSH `PSH_FROM_BLITZ` — gates Juggernaut, Fend cancellation, the Frenzy second block |
| 2 | `BBE_WF_PUSH_SF_DECLINED` | PUSH `PSH_SF_DECLINED` |
| 3 | `BBE_WF_PASS_INACCURATE` | PASS `f->data & 0x100` — interception modifier −2 vs −3 |

`PSH_CROWD` and `PSH_MOVED` are deliberately absent: both are derivable from
the board (a crowd-pushed player's `location` byte `t[2]` is no longer
`ON_PITCH`). `PSH_CHAIN` never reaches a decision and `PSH_STOOD_FIRM` skips to
a non-decision phase.

`BBE_S_STACK_FLAGS` bits:

| Bit | Name | Source |
|---:|---|---|
| 0 | `BBE_SF_TURNOVER` | `m->turnover` already latched |
| 1 | `BBE_SF_KICKOFF_CHARGE` | `bb_in_kickoff_charge` — team re-rolls are available mid-kickoff |
| 2 | `BBE_SF_KICKOFF` | `bb_in_kickoff` |

Placement budget per window: SETUP `SETUP_ACTION_BUDGET - f->data`; KICKOFF
phase 5 (Solid Defence) and 6 (Quick Snap) `f->x - popcount(f->data)`, the same
fresh-pick predicate `kickoff_legal` uses; KICKOFF phase 7 (Charge!) `f->x`.
The `+ 1` encoding keeps "budget exhausted" (1) distinct from "not a placement
window" (0), and an over-budget counter clamps to 1 rather than wrapping.

The option table is filled from the **same pure helpers the engine's legal-action
builder and apply path call** — `interception_candidates` for PASS phase 2,
`high_kick_candidates` for KICKOFF phase 4 — so index → slot cannot drift from
what `pass_apply` / `kickoff_apply` will resolve. `CASUALTY` phase 2 and `FOUL`
also use `CHOOSE_OPTION`, but their options are not players (roll A/B,
argue/accept), so the table stays zero there and `s[24]`/`s[25]` carry the
casualty case.

### Decision context (`BBE_CTX_OFF`, bytes 768–783)

Two existing bytes widen; no byte is added or moved.

`ctx[9]`/`ctx[12]` were the pending-**Dodge** destination only. They are now a
general **pending consequence square**, ego-mirrored exactly as before, filled
at every window where a frame square is both live and the consequence of the
pending decision:

| Window | Square |
|---|---|
| `TEST{DODGE,RUSH,JUMP}` under its own MOVE | the step destination |
| `TEST{PASS}` under its PASS parent | the pass target |
| `PASS` phase 2 (interception) | the pass target |
| `PUSH` phase 3 (follow-up) | the square the pushee vacated |

**Deliberately excluded, and this is the load-bearing exclusion:**
`BB_TEST_STANDUP` and the Jump-Up prone-block `BB_TEST_GENERIC`. The MA<3
stand-up and the Jump-Up block both push their TEST without writing the parent
MOVE frame's `x`/`y` (`engine/src/proc_move.c:706, 812`), so that square holds
whatever an earlier step left there. Publishing it would name a destination the
engine will never move the player to — a stale reading is worse than a zero,
because zero is honestly "not applicable" while a stale square is a lie the
policy has no way to detect. `BB_TEST_PICKUP` is excluded because it needs
nothing: the pickup square is the player's own square and the ball's, both
already visible.

`ctx[8]` carried the pending TEST target number only. It now also carries the
**ACTIVATION negatrait gate's needed roll** at the phase-2 re-roll window
(`target - modifier`, clamped to 1..7, where 7 means the gate cannot be passed).
`proc_turn.c` keeps nothing about the gate in the frame and re-derives it from
pure helpers at apply time, so the encoder calls those same helpers rather than
duplicating the modifier law.

## Compatibility and experiment rules

- Physical shape stays 2,782 and checkpoints stay 16,066,560 bytes, so blob
  size and parameter count cannot distinguish obs-v4 from obs-v5 from obs-v6.
- `BBE_OBS_VERSION` is **6**. It is the only discriminator, and source/module
  provenance is mandatory. `tools/checkpoint_lineage.py` refuses a sidecar whose
  `observation_abi`/`observation_version` disagrees with the module, as the
  first check it makes and with a message that names both fields.
- The lineage generation markers moved with the revision: `initialization`
  becomes `lineage-v6`, and the producer modes become
  `native_fresh_v6_qualification` / `native_fresh_v6_genesis`. A manifest that
  says v5 while the module says v6 is exactly the defect class this batch exists
  to close, so the two namespaces are kept in step.
- **Every obs-v5 checkpoint, sidecar, pool and curve is now out of lineage,
  including D228's accepted genesis root.** The obs-v6 lineage needs a fresh
  `genesis` root and a fresh `genesis-pool`, minted on one build, before any
  `lineage-v6` arm can launch (see D228/D230 for why the whole
  `genesis` → `build_league` → `lineage-v6` chain must run on a single build).
- Do not warm-start a v6 run from v5, compare their curves as one lineage, or
  merge their replay pairs without a separately reviewed bridge experiment.
- Re-extract behavioral-cloning observations under v6 before treating replay
  supervision as information-set matched.
- Existing live runs and BBTV viewers keep their pinned builds until normal
  retirement. This specification does not authorize deployment over them.

## Validation contract

`puffer/bloodbowl/test_observation.c` covers one test per new byte, each
asserting the live reading **and** the off-window zero, from both agent views:

- both player-valued `CHOOSE_OPTION` lists name their candidates in engine
  enumeration order, and shrink when the engine's own predicate drops a
  candidate;
- the PUSH flags carry POW/FROM_BLITZ/SF_DECLINED and never leak the derivable
  `PSH_CROWD`/`PSH_MOVED`, and a non-PUSH frame with the same `data` bits leaks
  nothing;
- the declared action kind survives a nested BLOCK/TEST window, round-trips
  every `bb_act_kind`, and is zero at the ACTIVATION DECLARE window itself,
  where `b` is still the push-time zero that would read as `BB_ACT_MOVE`;
- both casualty rolls are visible at phases 1 and 2 and at no other phase or
  proc, including the phase-0 frame whose `y` is `causer + 1`;
- the stack and budget bytes count down per window and stay zero elsewhere;
- the MOVE stash is published only under the engine's own three predicates, and
  is zero when `BB_A_JUMP` has parked a rush COUNT in the same bits;
- **the pending square is exactly zero for `BB_TEST_STANDUP` and the Jump-Up
  `BB_TEST_GENERIC`, with a positive control on the SAME frame** so the zero is
  provably the gate and not an empty fixture. The inventory calls this the one
  way the batch can silently ship a lie.
- the reserved slack bytes `s[30]`/`s[31]` are zero at every window the encoder
  handles.

Per D230, every one of these was watched to FAIL against a deliberately broken
encoder before being accepted; the mutation used for each is recorded in the
pull request. One test was rejected and rewritten on that basis: probing the
off-pitch guard with `0xFF` alone is worthless, because `0xFF + 1` truncates
back to 0 in an `unsigned char` and the test passed with the guard removed.
