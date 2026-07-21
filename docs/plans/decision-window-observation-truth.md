# Decision-window observation truth tranche

Status: implementation plan, 2026-07-20. This tranche is isolated from the
active RTX 2070 recovery run and BBTV. It does not authorize deployment,
training, checkpoint promotion, reward changes, or modification of either live
artifact tree.

Base: `origin/main` at `3fade1429f16b204a04f2380a5dfabf2006a1389`.

## Why this tranche is next

The harness audit found that the policy cannot observe the rolled block-die
faces at the decisions where it must reroll or choose one. The scripted contact
bot reads those faces directly, while obs-v4 exposes declaration-time block
probabilities computed under an owner-optimal choice the learned policy cannot
actually make from its observation. That invalidates block-quality evidence
until the information set is repaired.

The same decision-window audit found four smaller representation defects in the
same encoder/projection seam: TEST kind is hidden, movement already spent is
hidden, invalid off-pitch ball coordinates can wrap into plausible bytes, and
fallback Touchback placements collapse to the non-spatial square sentinel.
Fixing these together yields one bounded claim: public state needed to interpret
or address a currently legal decision is represented truthfully.

## Scope and compatibility

Keep the physical observation and action tensor shapes unchanged:

- observation: 2,782 bytes;
- action heads: `{30, 33, 391}`;
- mask: 454 bytes;
- engine `bb_match` layout and state-bank fingerprint: unchanged.

The semantic observation ABI becomes **obs-v5** despite retaining the obs-v4
tensor shape. Existing obs-v4 checkpoints are shape-loadable but semantically
incompatible: their formerly constant reserved inputs acquire meaning and
Touchback head projection changes. No historical v4 curve may be compared as
if it shared representation semantics, and no v4 checkpoint may be used as a
v5 warm start without a separately reviewed bridge experiment.

The 16-byte decision context retains D201's pending-Dodge coordinates at bytes
9 and 12. This tranche assigns:

- context bytes 13–15: block die faces 0–2, using the nonzero public
  `bb_block_die` symbols (the two identical Push sides normalize to one code)
  and zero for an absent die, only during BLOCK phases 1 and 2;
- scalar byte 19: active MOVE player's `moved` count plus one, zero when no
  valid MOVE frame exists;
- scalar byte 20: that player's `rushes` count plus one, under the same gate;
- scalar byte 21: top TEST kind plus one, zero outside a valid TEST frame.

The plus-one movement encoding distinguishes a real zero-spent activation from
the absence of an active mover. TEST kind also needs plus one because Dodge is
enum value zero. Block faces already use nonzero enum values, so zero remains a
natural absent-die sentinel and the dice count is the nonzero prefix length.

## Test-first slices

1. **Observation mutation contract.** Add a focused native Puffer observation
   test binary. Prove independently constructed BLOCK phase-1 and phase-2
   frames encode every rolled face; mutating any face changes the corresponding
   observation byte and not unrelated public-state bytes. Prove both agents see
   the same public faces.
2. **Nested decision context.** Prove TEST kind distinguishes Dodge, Rush,
   Pickup, Pass, Catch, Jump, Stand-up, Generic, and Loner windows while
   preserving pending-Dodge destination mirroring. Prove the nearest valid MOVE
   frame exposes movement and Rush expenditure at both MOVE and nested TEST
   decisions, with zero outside a MOVE activation.
3. **Ball-coordinate validity.** Prove on-pitch coordinates mirror exactly and
   every off-pitch or out-of-range coordinate produces zero x/y bytes for both
   agents.
4. **Touchback addressability.** Construct multiple fallback square-placement
   actions, fill the real marginal masks, and prove each action has a distinct
   square projection and exact decode round-trips the selected placement. Also
   preserve ordinary player-recipient Touchbacks.
5. **Lineage documentation.** Introduce `BBE_OBS_VERSION 5`, update binding and
   converter documentation, stamp newly extracted replay pairs as BBP v3, make
   the BC loader reject version-mixed corpora, add the obs-v5 semantic
   specification, and record the no-warm-start/no-direct-curve-comparison rule
   in `AGENTS.md` and `CLAUDE.md`.

The focused tests must fail against the unmodified encoder/projection before
implementation. Production changes remain minimal: encoder guards/assignments,
Touchback square classification, comments/constants, and build wiring for the
new test binary.

## Verification and acceptance

The tranche is acceptable only when all of the following are true:

- the new focused test fails for the intended reasons before the code change
  and passes afterward;
- `make test` passes the complete optimized engine/Puffer suite;
- `make asan` passes the same suite under ASan/UBSan;
- the standalone Puffer environment is installed from source and the installed
  snapshot check passes;
- clean Puffer float and fast builds succeed;
- two identical post-change seeded FNV runs match each other, while the new
  hash is explicitly expected to differ from the obs-v4 base because both
  observation bytes and Touchback projections changed;
- source/install diffs contain only the intended files;
- self-review confirms no reward, engine rule, `bb_match`, checkpoint tensor
  size, live run, queue, or BBTV behavior changed.

Hosted CI and review remain merge gates. Merge does not deploy this lineage to
the occupied RTX 2070. A later, separately planned v5 data/checkpoint/training
bridge is required before experiments resume.

## Explicitly out of scope

- replacing marginal per-head masks with a conditional/autoregressive action
  distribution or changing PPO's sampled-versus-executed action accounting;
- recurrent-state rollout/recompute alignment;
- Stalling implementation;
- total-domain discounted potential shaping;
- truncation/termination accounting and metric denominators;
- frozen checkpoint or demonstration-bank fail-closed loading;
- replay conversion, BC re-extraction, v5 training, live deployment, reward
  selection, checkpoint promotion, or BBTV changes.
