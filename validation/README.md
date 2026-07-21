# validation/ — Phase 4 validation harness

Three runnable pieces of the 7-layer validation architecture
(`.claude/skills/bb-validation`):

| Piece | Layer | What it does |
|---|---|---|
| `fetch_replays.py` | 7 (data) | polite, resumable FUMBBL Competitive-replay fetcher |
| `normalize_replay.py` | 7 (data) | replay JSON → normalized JSONL (formations, dice log, actions) |
| `tools/dist_dump.c` + `conformance.py` | 2 | empirical dice-path distributions chi-squared against exact math + the ActionCalculator oracle |

All Python runs on stock `/usr/bin/python3` (3.9, stdlib only; scipy used
when present, with a built-in chi-square fallback verified against scipy to
<1e-14).

## 1. Fetching replays — `fetch_replays.py`

```sh
python3 validation/fetch_replays.py --count 30          # discover + fetch
python3 validation/fetch_replays.py --match-ids 4706858 # explicit ids
python3 validation/fetch_replays.py --status            # cache summary
```

Etiquette (FUMBBL is a volunteer-run hobby server): ≥1.1 s between network
requests, exponential backoff on 429/5xx, descriptive User-Agent with contact
address, JSON API only, everything cached forever under
`validation/replay_cache/` (gitignored; replays are immutable). Cache hits
never touch the network, so re-runs are free and resumable.

**Discovery route** (all public, no auth):

1. `GET /api/match/current` → games in progress. **API surprise** (verified
   live 2026-06-03): the `id` field here is a *game* id (~1.9M range), NOT a
   match id (~4.5M range) — only the `teams[].id` values are used.
2. `GET /api/team/matches/<teamId>` → that team's 25 most recent matches
   (full match-summary shape incl. `division`, `replayId`, `conceded`).
3. `GET /api/match/get/<matchId>` → curation metadata, cached as
   `match_<id>.json`.
4. `GET /api/replay/get/<replayId>/gz` → replay, kept gzipped as
   `replay_<id>.json.gz`.

Curation filter (fumbbl-data skill §5): `division == "Competitive"`,
`conceded == "None"`, `replayId` present. Everything fetched is indexed in
`replay_cache/manifest.json` (match id, replay id, races, coach ratings
pre-match `cr`/`bracket` — the optional `r` field is handled).

Sample run (2026-06-03): 20/20 Competitive replays fetched in one pass, zero
retries — 14 in-progress games yielded 18 Competitive team ids; 12 team pages
yielded 81 candidate matches.

## 2. Normalizing replays — `normalize_replay.py`

```sh
python3 validation/normalize_replay.py --all        # whole cache
python3 validation/normalize_replay.py 1908509      # one cached replay id
python3 validation/normalize_replay.py vendor/fumbbl_replays/example_input/1559380.json
```

Output: `validation/normalized/<replayId>.jsonl` (gitignored; regenerate at
will). Record types, in command order: `meta` (teams/rosters/options/
receiving-team detection), `formation` (one per setup segment — the LAST
`fieldModelSetPlayerCoordinate` per player during `turnMode=="setup"`,
on-pitch coords only; segment 0 = initial kickoff formation), `dice` (every
dice-bearing report with typed extraction), `action` (playerAction,
blockChoice incl. negative-`nrOfDice` → defender-chooses decoding,
selectBlitzTarget, receiveChoice, apothecaryChoice, skillUse, coinThrow),
`event` (startHalf, turnEnd incl. KO-recovery rolls, foul/referee/pushback,
inducement, raiseDead, ...), `move`/`ball`/`state` (model-change streams;
playerState split into base `& 0xFF` + raw flag bits per the authoritative
FFB `PlayerState.java`), and a trailing `coverage` record.

Coverage on the current corpus (20 live Competitive replays, 2026-06-03):

```
=== aggregate over 20 replays ===
reports: 18325 total, 18148 handled (99.0%), 172 known-skipped,
         0 unknown-with-dice (emitted untyped), 0 unknown-skipped
report types: 75 handled, 7 known-skipped, 0 unknown
```

**API surprise:** live BB2025-era replays emit many reportIds beyond the
fumbbl-data skill's documented sample (which predates BB2025), e.g.
`foulAppearanceRoll`, `dauntlessRoll`, `steadyFootingRoll`, `prayerRoll`,
`teamCaptainRoll`, `blockReRoll`, `argueTheCall`, `masterChefRoll`,
`scatterPlayer`, `throwIn`, kickoff-event rolls (`quickSnapRoll`,
`blitzRoll`, `solidDefenceRoll`, `kickoffPitchInvasion`, ...). All observed
ones are now typed-handled (shapes verified against the live data).

**Known-skipped report types (deliberate, counted):** `mostValuablePlayers`,
`fumbblResultUpload`, `cardsAndInducementsBought`,
`prayersAndInducementsBought`, `freePettyCash`,
`kickoffSequenceActivationsCount/Exhausted`.

**Honest gaps** (also in the module docstring):

- Pre-match inducements/prayers/cards are counted, not decoded
  (`inducementSet`, `prayerState` untouched).
- `gameSetDialogParameter` model changes skipped — dialog decisions are
  inferred from reports only.
- playerState flag bits emitted raw, not interpreted.
- ~69 UI-noise modelChangeIds ignored (move squares, track numbers, dice
  decorations, pushback squares...).
- Unknown-but-dice-bearing reports are still emitted (`untyped: true`) so no
  dice silently vanish; genuinely unknown dice-free reports are dropped with
  a count. Expect new ids on mechanics our 20-game corpus lacks
  (interceptions, chainsaw, stab, wizards...).
- **No action-level lockstep**: this is an observation stream, not a replay
  *through the engine*. The turn-by-turn FUMBBL differential (inject recorded
  dice + actions, diff state trajectories) is the next milestone (layer 7
  proper).

## 3. Dice conformance — `tools/dist_dump.c` + `conformance.py`

```sh
# one-shot (compiles dist_dump if needed, runs full battery):
python3 validation/conformance.py            # 60k base trials, ~2 s total
python3 validation/conformance.py --quick    # 5k smoke
# manual:
cc -std=c11 -O2 -Iengine/include tools/dist_dump.c build/main/obj/*.o -o build/dist_dump
./build/dist_dump 60000 1234 20 | python3 -m json.tool
```

`dist_dump` generates distributions directly from the engine's own dice
paths: isolated micro-simulations built with `engine/tests/bb_fixtures.h`
scripted positions, PRNG dice via `bb_rng`, every die observed through a
`bb_rng` sink, outcomes classified from resulting match *state* with a
sink-vs-state cross-check (`xcheck_mismatch`, must be 0). Scenarios: 1d/2d
blocks (face/pair histograms), `BB_PROC_ARMOUR` at AV 7–11,
`BB_PROC_INJURY` normal + `BB_SK_STUNTY`, `BB_PROC_CASUALTY` (D16 bands),
real MOVE-action dodges at AG3+ with 0/1 destination TZ, a rush (2+), and
20 full seeded random matches (`fx_pick_smart`) as a whole-engine d6 stream.

`conformance.py` chi-squares all of it against exact probabilities (fail at
p < 0.001 per battery; re-run-to-confirm protocol for near-misses), and
cross-checks six rows from `vendor/BloodBowlActionCalculator`'s 281-row test
corpus (Season3 = BB2025). Row → scenario mapping:

| InlineData row | p0 | our check |
|---|---|---|
| `"2"` | 0.83333 | rush 2+ pass rate (analytic + empirical) |
| `"2,3,4,5,6"` | 0.01543 | chained d6-test ladder (analytic; 3+/4+ factors measured by the dodge scenarios) |
| `"1D5"` | 0.83333 | 1d block, P(not skull) |
| `"2D5"` | 0.97222 | 2d block, P(not double-skull) |
| `"2D3,K8"` | 0.31250 | 2d block any-of-{both-down, stumble, pow} × AV8 break rate |
| `"2D3,K8,J8"` | 0.13021 | … × injury 8+ (KO-or-worse band) |

Sample output (full battery, seed 1234; also passes seeds 7/42/987654):

```
=== layer-2 dice conformance (alpha=0.001, chi2 impl: scipy) ===
  [PASS] block_1d faces uniform: n=60000 chi2=7.38 df=5 p=0.1938
  [PASS] block_2d joint pairs uniform: n=60000 chi2=27.31 df=35 p=0.8201
  [PASS] armour av9 break rate: n=30000 chi2=6.76 df=1 p=0.009336
  [PASS] injury normal stun/ko/cas: n=60000 chi2=2.02 df=2 p=0.3641
  [PASS] injury stunty stun/ko/bh/cas: n=90000 chi2=7.70 df=3 p=0.05274
  [PASS] casualty bands: n=60000 chi2=4.90 df=4 p=0.2978
  [PASS] dodge AG3+ 0 TZ (needs 3+): n=30000 chi2=2.05 df=1 p=0.1519
  [PASS] full-match d6 faces uniform: n=4000 chi2=5.92 df=5 p=0.3143
  [PASS] empirical 2d block 3-faces x armour8 vs row '2D3,K8':
         empirical=0.31336 oracle=0.31250 tol=0.01017
  ...
=== 44/44 checks passed ===
```

**Honest gaps (layer 2):** pass/catch/interception dice paths, kickoff
scatter geometry (d8 directions/distance), and reroll-modified compound
paths (team/skill re-rolls, Loner gates, Block/Brawler/Mighty Blow/Claws
stacks) have no micro-scenarios yet — the ActionCalculator corpus has ready
oracle rows for these (`B,P:` prefixed and `{...}` branch rows) when they are
added to `dist_dump.c`.

## What "validated" means here, and what's next

Green here means: the engine's dice marginals and the
block/armour/injury/casualty/dodge/rush outcome bands match exact rulebook
math and an independent probability oracle, and real FUMBBL Competitive
replays parse to 99% typed report coverage with formations and a complete
ordered dice log. It does **not** yet mean the engine reproduces real games
action-for-action — the layer-7 lockstep differential (normalized JSONL →
engine `bb_replay` dice-script injection → state diff per command) is the
next milestone and the reason the normalizer exists.

## Lockstep differential v0 results (2026-06-03)

First corpus run: 21 BB2025 replays replayed action-by-action through the
engine with FUMBBL's dice injected. Mean 7.3% of ops consumed before first
divergence (best replay 17.7%). Ranked divergence classes: dice_underrun (7),
state (6), illegal (6), position (1), dice_overrun (1). Top unmapped
mechanics (the v1 work queue): skill_use windows (535), moves outside
activations (268 — follow-up/push trajectories), solidDefence/quickSnap
repositioning (engine TODO per D21), chain pushes (43), unattached
apothecary rolls (36). Full report: `python3 validation/lockstep_report.py`.

### dice_underrun triage (2026-06-03)

The 7-replay `dice_underrun` class is resolved to 1; mean consumption
7.3% → 8.4%. Diagnosed with the runner's new `-v` (per-die proc-stack trace)
and `--pad N` (filler dice make the first over-demanded roll visible as an
`EXTRA` line; reported divergences unchanged). Mapper root causes fixed:

- **Kickoff free-move events** (Charge/"blitz", Quick Snap, Solid Defence,
  Kick-off Return): FFB runs `playerAction`s inside the kickoff resolution;
  mapping them as activations stole the dice attachments of the kickoff
  landing chain (event 2d6, landing bounce d8, landing catch). They are now
  dropped (`kickoff_free_action_dropped`) so kickoff dice attach to the
  KICK_TARGET act. (1907928, 1908170, partially 1907399/1907617)
- **Dodgy Snack** fully mapped: D6 home + D6 away + per losing team a victim
  pick (reconstructed from the victim's index in the slot-ordered on-pitch
  list — FFB reports the victim id, not the pick die) + the victim's D6;
  -1 MA mirrored. (1907399, 1907617)
- **`mascotUsed` re-roll**: mapped to A_USE_REROLL/RR_TEAM with the re-rolled
  pool; the FFB mascot-activation d6 is dropped (engine has no mascots).
  (1907605)
- **Frenzy second block**: the engine starts it inside the first block's
  push transition, rolling any buffered rush-for-block test there — the
  pre-block dice buffer is now drained into the push op instead of being
  dropped. (1908034)
- **Stand Firm decline**: the engine auto-applies Stand Firm; FFB lets the
  coach decline it. Declines are a genuine engine-policy divergence, now
  flagged (`stand_firm_decline_divergence`) with armour dice re-routed to
  the choose-die op. (1907617 reaches 14.9%, then diverges downstream of
  the declined push.)

Remaining genuine engine divergences (do-not-fix in the mapper; engine
kickoff-event repositioning is TODO per D21): 1907663 (Quick Snap moved a
player off the landing square — the engine attempts a phantom landing
catch; still `dice_underrun`), 1907928 (Charge free moves → `position` at
the first boundary), 1908170 (Kick-off Return move → `position`).
After: illegal (9), state (6), position (3), dice_overrun (2),
dice_underrun (1).

## Lockstep consumption campaign v1 (2026-06-04)

The corpus grew from 21 to **401 normalized replays** (the box scraper's
cache, all normalized locally). Baseline at the v0 code on the 401-replay
corpus: **mean 7.8 % ops consumed** before first divergence (the original
21-replay corpus measured 8.4 %). After the v1 mapper triage: **mean 11.9 %**
(best replay 48.2 %; 1.5× the baseline), **58 079 BC pairs (144.8
pairs/replay)** — v0 yielded 1 766 pairs over 21 replays (84/replay).

| first-divergence class | v0 baseline (401) | v1 (401) |
|---|---|---|
| illegal | 139 | 179 |
| dice_overrun | 59 | 90 |
| dice_underrun | 39 | 69 |
| state | 72 | 29 |
| position | 71 | 28 |
| ball | 21 | 6 |

(The dice classes grew because walks now reach 50 % deeper before tripping;
every replay still diverges before completion.)

Mapper/runner fixes landed (each commit carries before/after means):

- **Ball-carrier mirror**: FFB emits the ball-follows-carrier record before
  the carrier's move — the mirror no longer drops possession on it.
- **Stun rollover mirror**: the engine flips STUNNED→STUNNED_USED at the
  owner's turn start and →PRONE at that turn's end; FFB reports prone at the
  start. The mirror holds state 2 until the engine's boundary.
- **Gate negatraits**: confusionRoll re-roll chains fold into the engine's
  single inline gate die, outcome-adjusted against the engine's flat target
  (FFB applies Really Stupid's +2 helper, which the engine lacks).
- **Touchback**: ball records in mode `touchback` map to `A_TOUCHBACK`
  (player slot, or 0xFF + square).
- **Kickoff events**: Solid Defence / Quick Snap / Kick-off Return final
  positions are **baked into the setup placements** whenever the result is
  still setup-legal (the engine treats the events as no-ops, D21); Blitz!/
  Charge free activations drop wholesale with their dice. Pitch Invasion and
  Dodgy Snack map fully (slot-ordered victim picks; Pitch Invasion 2d6
  outcome-adjusted vs FFB's Dedicated Fans modifier).
- **Chain pushes**: FFB emits chained pushees innermost-first; the mapper
  buffers the links and emits the engine's decision order (parent
  `PUSH_SQUARE` arg 2, then per-pushee, deepest last with empty/crowd
  geometry mirroring `push_legal`).
- **Apothecary**: FFB's all-null `apothecaryRoll` is the decline signature
  (`StepApothecary` DO_NOT_USE); KO and casualty windows now mirror
  used-vs-declined exactly.
- **Remote fouls**: the engine only offers DECLARE FOUL with a downed
  opponent already adjacent; remote declares demote to MOVE so the approach
  walks, with the foul tail (victim injury, send-off) skip-classified.
  (Demoted-foul BC pairs record the declare as MOVE — the engine cannot
  accept FOUL there until the cycle-2 engine fix.)
- **Pick Me Up**: dice attach only when the engine's `pick_me_up` would roll
  them (prone at roll time; held-stunned players excluded; slot-ordered).
- **Star rosters**: >16-player rosters (induced stars/mercs) prioritize
  formation participants for the 16 engine slots.
- Misc: wasted Pro/Loner re-roll turnovers, single stand-up per activation,
  follow-up resolution before END_ACTIVATION, Swarming/raise-dead players as
  classified engine-unrepresentable ghosts, skillUse auto-match table.

### Genuine engine divergences discovered (cycle-2 work queue, do-not-fix in the mapper)

1. **DECLARE FOUL adjacency** (`proc_turn.c activation_legal`): the rulebook
   declares first and moves after; the engine demands an adjacent downed
   opponent at declare time. 734 fouls/corpus demoted.
2. **Negatrait gate modifiers** (`BB_SKILL_GATE`): flat targets only — no
   Really Stupid +2-helper, no team re-roll window on gate rolls.
3. **Kickoff event windows (D21)**: Solid Defence / Quick Snap / Kick-off
   Return / Blitz! are no-ops past their dice. Quick Snap steps may cross
   the LoS, so setup bake-in cannot always reconcile; Blitz! runs full
   activations (blocks, injuries) the engine never rolls.
4. **Swarming**: not implemented; setup requires exactly min(11, available).
5. **Wrestle decline** (D29 designed, unimplemented): engine auto-applies
   Wrestle on Both Down; FFB coaches may decline (`used:false` skillUse).
6. **Stand Firm decline** (v0 finding): engine auto-applies.
7. **Changing Weather → Perfect Conditions**: engine scatters the ball 3×D8
   in the air; FFB rolls one gust D8 (+landing bounce).
8. **Pick Me Up timing**: engine rolls before `turn_end`'s stun flip, so
   players FFB just rolled over are not engine candidates (they stay prone
   engine-side where FFB stood them up).
9. **Fumblerooski**: unimplemented — a deliberate ball drop diverges all
   later ball state (13 rosters in corpus carry it).
10. **Pitch Invasion fans**: engine compares raw D6s without Dedicated Fans
    (mapper outcome-adjusts).
11. **Block pool dice count**: scattered boards where the engine computes a
    different nrOfDice than FFB (ST/assist calculation) —
    `dice_underrun` at BLOCK_TARGET; needs board-level comparison
    (`BB_LOCKSTEP_BOARD=1` runner trace added for this).
12. **Apothecary result choice**: the engine consumes one new casualty die
    and auto-applies; FFB offers original-vs-new (apothecaryChoice).
13. **Mid-game roster additions** (Raise Dead) and bench overflow past 16
    slots are unrepresentable in the fixed roster.

## Cycle-2 engine campaign (2026-06-04): auto-policies become decision windows

The consumption campaign's vote drove the engine work this time (mapper
fixes only where the engine grew real windows). Baseline at v1 on the same
401-replay corpus: **mean 11.9 %**; after the cycle-2 engine windows:
**mean 12.8 %** (same runner/metric; note the metric counts skip ops as
consumed, so converting wholesale-dropped mechanics — e.g. Charge! free
activations — into real act ops *deflates* pct in unreached regions; the
rise is conservative).

| first-divergence class | v1 (401) | cycle-2 (401) |
|---|---|---|
| illegal | 179 | 174 |
| dice_overrun | 90 | 105 |
| dice_underrun | 69 | 73 |
| state | 29 | 15 |
| position | 28 | 32 |
| ball | 6 | 2 |

(Dice classes again grew because walks reach deeper before tripping.)

Genuine-divergence list status (numbers from the v1 list above):

- **2 (negatrait gates) CLOSED**: gates roll at declare time with Really
  Stupid's +2 helper and Unchannelled Fury's +2 on Block/Blitz; Take Root
  rolls only when Standing; failed gates offer the team re-roll window
  (Loner gate applies). Mapper outcome-adjusts per-die against the engine's
  modified target and emits the window acts.
- **3 (kickoff event windows, D21) CLOSED for Solid Defence / Quick Snap /
  Charge!**: SD = SETUP_PLACE/REMOVE re-setup window (off-pitch staging so
  swaps reconcile; D1/D25 budget + autofix guard); QS = one-square steps,
  cross-half legal; Charge! = real ACTIVATION machinery (free Move, one-of
  Blitz/TTM/KTM budgets, active-team handover so team re-rolls work, the
  turnover latch is the falls-end-the-event signal). *Deferred*: Kick-off
  Return (a FUMBBL BB2020-ruleset relic absent from the BB2025 mirror —
  stays a baked/classified mapper divergence), up-front Charge selection
  (we check Open lazily at activation time), TTM/KTM dice mapping (charge
  TTM activations drop, classified).
- **5 (Wrestle, D29) CLOSED**: attacker-then-defender USE/DECLINE windows at
  Both Down (FFB StepWrestle order; Distracted owners excluded); declining
  resolves the plain Both Down with the knockdown turnover.
- **6 (Stand Firm) CLOSED**: decline window on every push incl. chains; a
  chain occupant who stands firm now absorbs the parent push in place.
- **7 (Changing Weather) CLOSED**: the gust rolls per-die and stops at the
  touchback boundary (FFB rolls no further dice once the ball leaves the
  receiving half — the "1 D8" vote was the common early-exit case; the
  mirror's flat Scatter (3) over-rolls).
- **8 (Pick Me Up) CLOSED**: the incoming team's stun roll-over runs before
  the Pick-Me-Up rolls at the same boundary (FFB StepEndTurn order), helpers
  snapshot (a freshly-stood owner cannot help), Distracted owners excluded.
  Two mapper bugs fixed en route: the canonical skill name never matched
  ("Pick Me Up" vs "Pick-me-up") and the yaml-lite loader swallowed inline
  comments into display names — ALL 686 corpus pickMeUp rolls had been
  no-candidate skips.
- **10 (Pitch Invasion fans) CLOSED**: `bb_match.fan_factor[2]` (init-op
  `fans`, from FFB's dedicatedFansResult) joins the roll-off. **engine_fp
  changed** — the demo-state bank must be regenerated.
- **11 (block pool nrOfDice) root-caused**: the Defensive-cancels-Guard turn
  check was inverted (cancelled defensive Guard assists, granted offensive
  ones) — fixed, FFB's ServerUtilPlayer confirms the polarity. Residual
  cases are FFB star specials (canAddBlockDie / "Gored By The Bull" grants
  an extra block die) absent from our roster spec — documented, not
  modelled.
- **12 (apothecary result choice, D20 reversal) CLOSED**: CHOOSE_OPTION
  between the original and the apothecary's second casualty roll; the
  mapper picks the side whose band matches FFB's apothecaryChoice
  playerState.
- Open (untouched this cycle): 1 (DECLARE FOUL adjacency), 4 (Swarming),
  9 (Fumblerooski), 13 (mid-game roster additions / bench overflow).

### Top remaining blockers (v2)

- `illegal` (179): mostly step/block-target mismatches downstream of
  unbakeable kickoff repositioning and stance desyncs from items 3/5/8.
- `dice_overrun` at STEP (23): engine rolls nothing where FFB rolled a
  dodge/pickup — board/ball desync downstream effects.
- `dice_underrun` at BLOCK_TARGET (16): item 11 (assist calculus).
- Unmapped report tails: `unmapped_dice_report` 3 737,
  `block_pro_reroll` 488, `block_reroll_unmapped` 394 (Pro/skill re-rolls
  inside block pools), `scatter_player_unmapped` 777 (TTM scatters),
  `apothecary_roll_unattached` (apo rolls outside the injury windows).

## Cycle-2 integration (2026-06-04): obs v3 lands, full chain regenerated

The parked obs-v3 branch (1612-byte observation: two 390-byte tackle-zone
planes appended after the unchanged 832 layout; `.bbp` v2; selftest plane
checks; converter default 1612) was brought onto cycle-2 main and the whole
artifact chain regenerated against the cycle-2 engine. **This is a lineage
cutover**: every pre-cycle-2 checkpoint is obs-832 and can never load into
the obs-v3 policy (archived in `checkpoints-backup/`; see the obs-v3 note in
`.claude/skills/puffer-env-dev`).

Regenerated chain (401-replay corpus, this engine, this obs):

- **Lockstep**: mean consumption 12.8 % — identical to the cycle-2 campaign
  number and class breakdown (illegal 174 / dice_overrun 105 /
  dice_underrun 73 / position 32 / state 15 / ball 2): the obs encoder is
  engine-neutral, as expected.
- **BC pairs (.bbp v2)**: **70 231 pairs** (175.1 pairs/replay,
  146 227 358 B) — up from 58 079 v1 pairs; the cycle-2 decision windows
  deepen the walks.
- **Demo-state bank**: **1 057 states** (2.6 states/replay,
  `engine_fp 0x64897cde`, match_size 2240). Half/turn histogram (half 2
  still unreached — best walk stops at half-1 turn 8):
  `h1: 573/272/116/52/22/13/7/2` for turns 1–8.
- **bc_v2** (`training/bc_v2.bin`, 12 000 steps × batch 512, mps): train
  loss 3.65 → 0.70, train exact-action 0.767; **held-out-replay val: loss
  6.41, acc type/arg/sq 0.893/0.797/0.516, exact 0.324** (v0 iid-BC
  generalization gap — the documented sequence-BC follow-up, not a
  regression). save_weights round-trip: max param diff 0.0, max logit
  diff 0.0. CUDA blob (`--to-cuda`): **13 670 400 bytes** = 3 417 600 fp32,
  the exact obs-1612 layout pinned by `training/test_convert_checkpoint.py`.

Validation at the merge: engine suite 320/320; standalone driver masked +
unmasked + ASan/UBSan clean; `--selftest` (TZ-plane spot-checks, micro-stat
counter sanity) 0 failures across seeds; `--demo` against the fresh bank
resumes banked states with 0 fallbacks (ASan too); binding compiles under
build.sh-equivalent flags.

## BC pair extraction — `bb_lockstep --dump-pairs` + `extract_pairs.py`

`./build/bb_lockstep --dump-pairs <out.bbp> <script.jsonl>` additionally
writes one behavioral-cloning record per **successfully applied act/place
op** (a place op is a `BB_A_SETUP_PLACE` action) for the **deciding** coach,
using the PufferLib env's own encoders — the runner is built as a single TU
through `puffer/bloodbowl/bloodbowl.h`, so `bbe_encode_obs`/`bbe_fill_mask`
and the head projections `bbe_action_arg`/`bbe_action_sq` are byte-identical
to training. Divergence reporting is unchanged; records stop at the first
divergence (nothing past it is applied).

### `.bbp` format v3 (binary, little-endian)

v3 marks obs-v5 semantics while retaining obs-v4's 2782-byte physical shape.
Historical v2 spans obs-v3 (1612 B) and obs-v4 (2782 B); v1 carried 832 B.
Readers (`bc_pretrain.py`, `extract_pairs.py`) size records from the header and
include its version in corpus-lineage checks, so v2/2782 and v3/2782 cannot mix.

```
header (16 bytes):
  magic     char[4]  "BBP1"
  version   u32      3 (semantic obs-v5 marker)
  obs_size  u32      2782 (BBE_OBS_SIZE; same physical shape as obs-v4)
  mask_size u32      454  (BBE_MASK_SIZE = 30 + 33 + 391 head bits)
record (12 + obs_size + mask_size + 4 = 3252 bytes each):
  replay_id u32      numeric FUMBBL replay id
  cmd       u32      FUMBBL commandNr of the op
  agent     u8       deciding team (0 home / 1 away); obs, mask and action
                     targets are all in this agent's egocentric frame
  pad       u8[3]    zero
  obs       u8[2782] bbe_encode_obs at the decision, BEFORE the action
  mask      u8[454]  bbe_fill_mask legality bits, heads packed 30|33|391
  type      u8       action-type head target (bb_action_type)
  arg       u8       arg head target via bbe_action_arg (player slots
                     ego-remapped exactly like obs rows; 32 = sentinel)
  sq        u16      square head target via bbe_action_sq (y*26 + x with x
                     mirrored for the away agent; 390 = "no square")
```

The action targets are the binding's head projections of the applied
`bb_action` — what the policy heads must emit — never raw engine fields.
Invariant (asserted by `extract_pairs.py`): every record's three targets are
set in its own mask slices.

### Orchestration

```sh
make lockstep                                # build the runner (amalgamated)
python3 validation/extract_pairs.py          # map + run + dump whole corpus
python3 validation/extract_pairs.py 1907296  # one replay
```

Output: `validation/pairs/<replayId>.bbp` (gitignored; regenerate at will)
plus corpus totals (replays, pairs, pairs/replay, bytes). Consumed by
`training/bc_pretrain.py`. Current corpus (401 replays, 2026-06-04, .bbp
v2 on the cycle-2 engine): **70 231 pairs (175.1 pairs/replay)** — v1
yielded 58 079 pre-cycle-2; v0 yielded 1 766 over 21 replays. The count
grows automatically as lockstep coverage improves.

## Demo-state dump — `bb_lockstep --dump-states` + `build_state_bank.py`

`./build/bb_lockstep --dump-states <out.bbs> <script.jsonl>` additionally
writes one **raw `bb_match` snapshot** per team-turn boundary successfully
reached in lockstep: the first `BB_STATUS_DECISION` of every team turn —
which includes the first turn of every drive (post-kickoff). Records are
staged at the boundary and committed only after the next op also applies
cleanly; the mapper emits its `expect` state diff at exactly these
boundaries, so a state that diverges from FUMBBL is never banked. These are
the resume points for the env's demo-state reset curriculum
(`demo_reset_pct` — the Backplay / chess-FEN-curriculum pattern from
`docs/rl-best-practices.md` hole #2).

### `.bbs` format v1 (binary, little-endian header/meta, host-ABI blob)

```
header (16 bytes):
  magic      char[4]  "BBS1"
  version    u32      1
  match_size u32      sizeof(bb_match) of the writing build
  engine_fp  u32      bbe_state_fingerprint() — engine-compat stamp over
                      sizeof(bb_match), BB_TEAM_COUNT, BB_SKILL_COUNT,
                      BB_A_TYPE_COUNT; any drift invalidates the bank
record (12 + match_size bytes each):
  replay_id  u32      numeric FUMBBL replay id
  cmd        u32      FUMBBL commandNr of the op that reached the state
  half       u8       match.half at the dumped decision
  turn       u8       match.turn[match.active_team]
  pad        u8[2]    zero
  match      u8[match_size]  raw bb_match memcpy blob (same-arch only)
```

The blob is a host-ABI struct copy, not a portable serialization —
`match_size` + `engine_fp` are the load-time guards; the loader additionally
rejects any record whose status is not `BB_STATUS_DECISION`.

### Orchestration

```sh
make lockstep                                    # build the runner
python3 validation/build_state_bank.py           # whole corpus -> bank.bbs
python3 validation/build_state_bank.py 1907296   # specific replay id(s)
```

Output: one shard per replay at `validation/states/<replayId>.bbs` plus the
concatenated `validation/states/bank.bbs` (both gitignored; regenerate at
will), with corpus stats and a per-half/turn histogram of the banked states.
**Read the histogram**: the lockstep currently consumes ~8-18% of each replay
before first divergence, so the bank is opening-biased (mostly half 1, turns
1-3) — it deepens automatically as mapper coverage improves. Stage into the
training tree with `tools/install_puffer_env.sh` (lands at
`resources/bloodbowl/state_bank.bbs`).

### Exact-edition subset of an existing bank

The historical `bank.bbs` predates strict edition filtering: its match blobs
were generated by the current engine, but 123 records came from 42 BB2020
source replays. Loader size/fingerprint checks prove engine compatibility, not
source edition. Filter it through the exact replay-ID allowlist before any new
BB2025 scenario or curriculum work:

```sh
mkdir -p validation/states/bb2025-strict
python3 tools/filter_state_bank.py \
  validation/states/bank.bbs \
  validation/states/bb2025-strict/bank.bbs \
  --allowlist runs/replay-audit-20260713/bb2025-nonempty.ids \
  --selected-ids validation/states/bb2025-strict/selected.ids \
  --manifest validation/states/bb2025-strict/manifest.json \
  --expect-input-sha256 710c7b850ad72d5d665b3ea14b93b94f5e42cb70fb1a1d5850aa39bd3d2481c5 \
  --expect-allowlist-sha256 15d6f67852c6d556009a8f878f730c6fd6c0c45fdf77e1fd8a2b7d1b2c218585 \
  --expect-input-records 15471 \
  --expect-input-replay-ids 5370 \
  --expect-selected-records 15348 \
  --expect-selected-replay-ids 5328
```

The tool streams opaque match blobs in original order, preserves the BBS1
header and selected records byte-for-byte, pins both inputs, and publishes a
deterministic manifest last. It refuses existing/aliased outputs and removes a
partial transaction on handled error without overwriting a destination that
appears concurrently. The absence of a manifest is the fail-closed signal after
a hard crash; remove any uncommitted residue manually before retrying. All
three outputs must share one directory. The generated files are local artifacts
and remain gitignored. This removes edition contamination only: all 15,348
selected records are still from half one, with 12,001 (78.2%) on turns 1–2.
Authored fixtures remain necessary for passing, handoffs, late-game score/clock,
Stalling, and reroll-budget decisions.

### Descriptive S1–S6 coverage of the strict bank

Build the engine-linked scanner, then run the manifest-producing report layer
with the exact D191 inputs and the exact binary/source hashes from that build:

```sh
make scenario-scan
shasum -a 256 build/bank_scenario_scan
# Set this to the reviewed binary hash printed above; do not derive it inside
# the report command after review.
SCANNER_SHA256=REPLACE_WITH_REVIEWED_PLATFORM_SPECIFIC_BINARY_SHA256
mkdir -p validation/states/bb2025-strict/scenarios
python3 tools/report_scenario_coverage.py \
  validation/states/bb2025-strict/bank.bbs \
  --filter-manifest validation/states/bb2025-strict/manifest.json \
  --scanner build/bank_scenario_scan \
  --scanner-source tools/bank_scenario_scan.c=fb68615b4ee482cdf580f7d77aa1a03724502abd205736d0de4049c1571b3095 \
  --scanner-source tools/bank_scenario_scan.h=1b692c4ca7396b8f59f9740ef62cc4db2aea6ec784ba4c5c2ce767e2360f1c34 \
  --scanner-source tools/bank_scenario_predicates.c=5e4d12147adf5ed2f55bca679e6d516fa70b9de104f758e5c754af0f7d58407c \
  --scanner-source tools/bank_scenario_predicates.h=79103b277edf01aad0e3e9c9d49767edffd9a85c755d39c9e5c1dfe827ac65bb \
  --records validation/states/bb2025-strict/scenarios/records.jsonl \
  --report validation/states/bb2025-strict/scenarios/report.json \
  --manifest validation/states/bb2025-strict/scenarios/manifest.json \
  --expect-bank-sha256 bcd9daf55ac5d177f48160092f17a9b4978da877455b830ba33a9c1b5ba84d22 \
  --expect-filter-manifest-sha256 dd97785dea348c19f4e210688842ccc22ae44a00c9c9052366968e164950610d \
  --expect-scanner-sha256 "$SCANNER_SHA256"
```

The source hashes above bind the reviewed D192 sources. The scanner binary hash
is platform/build-path specific and must be frozen after that exact build; it
must not be computed implicitly by the report invocation. If scanner sources
legitimately change, rebuild, re-review, and intentionally update every
affected pin rather than bypassing a mismatch. `records.jsonl` contains
deterministic per-state facts. `report.json` publishes raw-record,
distinct-replay, and three-records-
per-replay-capped counts, turn bands, overlaps, race-pair composition, and
replay-ID-disjoint descriptive splits. The manifest is the commit marker and
is published last. Existing outputs are never overwritten.

These are overlapping, pre-negatrait opportunity predicates, not chosen-action
or outcome labels. S2/S4 use static fresh-opponent movement geometry; S3 is
ordering pressure rather than ordering quality; S5 is a straight-line score
horizon; and S6 is fixed direct-block diversity plus one selected zero-roll
move's assist sensitivity. Do not feed the records or split labels into
training without a separate reviewed sampling contract. See
`docs/plans/strict-bank-scenario-coverage.md` and D192.
