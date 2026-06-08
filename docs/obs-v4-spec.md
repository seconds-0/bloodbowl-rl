# Obs-v4: decision-support planes (information parity with the FUMBBL UI)

**Motivation (D46/D52 chain, Alex 2026-06-07):** the agent's block-tier
distribution is wildly inhuman (2d:2d-red ≈ 1.9:1 vs human 46:1) and flat
across training. Root cause hypothesis: FUMBBL's UI shows a human the dice
count ("2D", "1D against") *before* they commit, so the BC corpus encodes
decisions made WITH that information — while obs-v3 gives only raw material
(ST bytes, positions, TZ planes) and demands the network derive three-way
relational arithmetic (ST compare + assist count + marking) implicitly.
Same story for movement: players see dodge/GFI/pickup target numbers in the
UI. Obs-v4 restores parity. This is decision-support, not strategy
injection: every value is public information a competent human computes (or
reads off the screen) before every roll.

## Layout

Obs-v3 (1612B): `32×24B players | 16B ball/ctx | 48B scalars | 2×390B TZ planes`
Obs-v4 (2782B): v3 + three appended 390B planes (26×15, uint8):

### Planes A1/A2 — block outcome probabilities (offsets 1612 / 2002)

(Upgraded from dice-tier codes per Alex: dice counts hide skill
interactions — 2d-with-Tackle vs 2d-into-Dodge are the same tier but very
different rolls. `bb_blockev` computes the exact closed-form outcome
distribution with full skill handling — Block/Wrestle/Tackle/Dodge/MB/
Claws/Brawler/Dauntless/Fend, owner-optimal die choice — panel-validated
against 25-matchup MC, so we publish true probabilities, not estimates.)

Filled only when the pending decision selects a block/blitz target or
declares against an adjacent foe. For each candidate defender square:

- **A1**: `round(255 × P(defender ends knocked down))`
- **A2**: `round(255 × P(attacker ends knocked down))` — the both-down /
  skulls risk a single percentage would hide (a Blockless 2d can be high
  on BOTH planes; the policy must see both sides of the coin).

Computed by `bb_block_ev` with no-team-reroll, frenzy-pending parameters
(deterministic, rule-grounded baseline). All other bytes 0.

### Plane B — move success (offset 2392)

Filled only for the pending MOVE decision's acting player. For each legal
destination square, `round(255 × P(success of stepping there))` where P
multiplies the step's dodge test (if leaving TZs), GFI (if beyond MA,
incl. Blizzard), and pickup (if the ball sits there) — each from
`bb_test_target` with the live modifier stack, the d6 success probability
of the resulting target. Squares not reachable this step: 0. A 255 means
a free step; a 84 means ~2/6. This teaches "AG4 elves dodge freely, AG2
orcs don't" as a *readable feature* instead of a stat-table memorization,
and prices pickup-in-traffic exactly where the scrum standoff lives.

## What deliberately stays OUT

- No VALUES — injury EV, turnover cost, positional worth. The line:
  outcome PROBABILITIES are roll information (what the dice will do);
  weighting outcomes is the policy's job (what they're worth). Planes
  carry only the former.
- No reroll-adjusted compound probabilities — reroll use is itself a
  decision the policy owns.
- Heads/masks unchanged (30/33/391). Engine state untouched — pure
  encoder change; bank fingerprint (bb_match layout) unaffected.

## Compatibility & rollout

- `BBE_OBS_SIZE` 1612 → 2392 is compile-time: old torch checkpoints are
  input-shape incompatible. Obs-v4 is therefore a NEW LINEAGE boundary:
  - re-extract BC pairs (same 12K-replay corpus, lockstep replayer picks
    up the new encoder automatically) → `bc_v4` anchor retrain;
  - running obs-v3 arms keep their current builds until natural retirement;
  - first v4 arm launches as an A/B against the equivalent v3 lineage
    (same rewards/curriculum stage) — the measurable claims:
    (1) `block_2dred_frac` falls toward the human 0.017 reference,
    (2) bc_v4 val-exact beats bc_v3b's 0.371 (the corpus is more
        learnable when the information its decisions used is visible),
    (3) dodge-attempt demographics shift toward high-AG players.

## Validation

- Unit tests: scripted scenarios → expected A1/A2 bytes (Tackle-vs-Dodge
  asymmetry, Block-vs-Blockless both-down risk, assists incl. Horns,
  marked-assist cancellation); AG/TZ/weather grids → expected plane-B
  bytes; planes all zero for non-applicable decision types.
- Differential: A1/A2 vs 100K-roll MC per scripted matchup (reuse the
  blockev-mc harness tolerance) + plane fill consistency with the block
  proc's own nd at CHOOSE_DIE for 10K random blocks.
- Perf gate: obs encode budget stays <2µs (planes fill only on their
  decision types; default path is two extra memsets).
