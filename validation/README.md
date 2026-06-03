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
