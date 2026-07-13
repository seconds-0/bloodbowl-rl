---
name: fumbbl-data
description: Fetch, parse, audit, and train from FUMBBL data with embedded-rulesVersion filtering, replay-disjoint splits, bounded streaming BBP access, depth/action coverage checks, and polite cached API use. Use for FUMBBL endpoints, replay JSON anatomy, playerState encoding, corpus curation, BB2025 allowlists, BC sampling, human baselines, or server etiquette.
---

# FUMBBL Data: API, Replays, Curation

Read `runs/replay-audit-20260713/corpus.json`, D179–D180, and the replay sections
of `docs/reward-and-replay-audit-2026-07-09.md` before changing the corpus or BC
sampler. The current corpus is mixed-edition at the raw layer and sharply
prefix-censored; shard presence and directory names are not edition proof.

Ground truth lives in two vendored codebases (paths relative to repo root):

- `vendor/fumbbl_replays/src/fumbbl_replays/` — gsverhoeven's Python package. Fetchers (`fetch_match.py`, `fetch_replay.py`, `fetch_team.py`, `fetch_roster.py`) and a pandas-based replay parser (`parse_replay.py`, `structure_player_actions.py`, `from_steps_to_trajectories.py`).
- `vendor/jervis-ffb/modules/fumbbl-net/` — Kotlin adapter that replays FUMBBL command streams through a real rules engine (`src/commonMain/kotlin/com/jervisffb/fumbbl/net/adapter/`). Far more complete action mapping than the Python package.
- `vendor/ffb/` — the actual FFB client/server source (authoritative for encodings, e.g. `ffb-common/src/main/java/com/fumbbl/ffb/PlayerState.java`).
- Docs: `docs/vendor/fumbbl/api-notes-730.html` (cached official API doc — thin: only coach/roster/ruleset stubs documented), `vendor/fumbbl_replays/doc/fumbbl_replay_file_format.md` (replay format writeup), `vendor/fumbbl_replays/example_input/` (real match + replay JSON to test against: `4407782_match.json`, `1559380.json`).

## 1. Endpoint catalog

Base: `https://fumbbl.com/api/<component>/<command>[/<params>][/xml]`. JSON by default. No auth needed for any endpoint below. Official doc index: https://fumbbl.com/apidoc/

| Endpoint | Returns | Source |
|---|---|---|
| `GET /api/match/get/<matchId>` | Match summary incl. `replayId` | `fetch_match.py:21` |
| `GET /api/replay/get/<replayId>/gz` | Full replay, gzipped JSON (chunked transfer) | `fetch_replay.py:34` |
| `GET /api/team/get/<teamId>` | Team incl. players, treasury, TV | `fetch_team.py:23` |
| `GET /api/team/matches/<teamId>[/<beforeMatchId>]` | 25 matches/page; paginate with `lastBatch[24]['id']-1` | `fetch_match.py:41,60` |
| `GET /api/ruleset/get/<rulesetId>` | Ruleset incl. `rosters[]` (id/value pairs); 2228 = NAF BB2020 | `fetch_roster.py:118` |
| `GET /api/roster/get/<rosterId>` | Roster `positions[]` with stats/skills/icons; 5160 = star players | `fetch_roster.py:131,57` |
| `GET /api/player/get/<playerId>` | Single player details | Jervis `FumbblApi.kt:179` |
| `GET /api/coach/search/<string>` | Up to 10 `{id, value}` coach pairs (min 3 chars) | api-notes-730.html |
| `GET https://fumbbl.com/i/<iconId>.png` | Position icon sprite sheet (4 columns) | `fetch_roster.py:106` |

**Verified live 2026-06-02:** `GET https://fumbbl.com/api/match/get/<id>` returns JSON with `tournamentId`, `divisionId`/`division`, `replayId`, `conceded`, per-team: `roster.name`, `teamValue`, `score`, `casualties {bh,si,rip}`, `coach {name, rating {pre/post: {r, cr, bracket}}}`. Replay download `https://fumbbl.com/api/replay/get/<replayId>/gz` is public, no auth. (Older matches like `example_input/4407782_match.json` lack the `r` field in rating — only `cr`/`bracket`. Handle both.)

**ID disambiguation:** `matchId` (4.4M range) ≠ `replayId` (1.5M range) ≠ `teamId` ≠ `gameId`. The match API maps matchId → replayId; always fetch the match first (`fetch_replay.py` does exactly this). Jervis's websocket downloader (`fumbbl-cli/.../DownloadGameRunner.kt`) uses a *gameId* against `ws://fumbbl.com:22223/command` with `{"netCommandId":"clientReplay","gameId":...,"replayToCommandNr":0}` — that yields a different file format (raw command stream) than the REST `/api/replay/get` JSON object. Stick to REST.

Python usage end-to-end (from `fumbbl_replays.ipynb` / `fumbbl2ffgn.py`):
```python
import fumbbl_replays as fb
replay = fb.fetch_replay(match_id)          # caches ~/.cache/fumbbl_replays/raw/replay_files/<replayId>.gz
pd_replay = fb.parse_replay(replay)         # flat DataFrame of model changes + reports
roster = fb.extract_rosters_from_replay(replay)
pd_full = fb.fumbbl2ffgn(match_id)          # full pipeline -> annotated action table + pd_replay.xlsx
```

## 2. Replay JSON anatomy

Top level (`doc/fumbbl_replay_file_format.md`, confirmed against `example_input/1559380.json`):

```
{ "gameStatus": "uploaded",
  "stepStack": {"steps": []},
  "gameLog":  { "commandArray": [...] },   # the event stream (~3600 commands/game)
  "game":     { ... },                     # FINAL game state + full rosters (self-contained)
  "playerIds": [], "swarmingPlayerActual": 0,
  "passState": {...}, "prayerState": {...}, "activeEffects": {...} }
```

**For a normalizer → (initial state, action log, dice log):**

- **Initial state**: `game.teamHome` / `game.teamAway` → `teamId, coach, race, reRolls, apothecaries, fanFactor, teamValue, playerArray[], roster{positionArray[]}`. Each player: `playerId, playerNr, positionId, playerName, movement, strength, agility, passing, armour, skillArray, recoveringInjury`. NB: `game` is the **end-of-game** snapshot; starting positions must be reconstructed by replaying `commandArray` setup-phase coordinate changes (see `plot_setups.py:34` — last `fieldModelSetPlayerCoordinate` per player where `turnNr == 0 & turnMode == "setup" & Half == 1`). Rules options: `game.gameOptions.gameOptionArray` (`{gameOptionId, gameOptionValue}` pairs, e.g. `clawDoesNotStack`).
- **Action log + dice log**: every element of `gameLog.commandArray` has `netCommandId` (always `"serverModelSync"`; `serverAddPlayer` rare), `commandNr`, `gameTime`, `turnTime` (ms), and two payloads:
  - `modelChangeList.modelChangeArray[]`: `{modelChangeId, modelChangeKey, modelChangeValue}` — state deltas. Key ones (`parse_replay.py:44-90`):
    - `fieldModelSetPlayerCoordinate` — key=playerId, value=`[x, y]`
    - `fieldModelSetBallCoordinate` — value=`[x, y]` (can also be `0`/`null` — guard like `parse_replay.py:76`)
    - `fieldModelSetPlayerState` — key=playerId, value=bit-packed int (section 3)
    - `gameSetTurnMode` — value ∈ `setup, kickoff, highKick, regular, betweenTurns, selectBlitzTarget, endGame, ...` (segments phases; `startGame` is the parser's *initial default* before the first such change, never an emitted value)
    - `gameSetHalf`, `turnDataSetTurnNr` (key=`"home"|"away"`), `gameSetHomePlaying`, `gameSetHomeFirstOffense`
    - `actingPlayerSetPlayerId`, `actingPlayerSetPlayerAction`, `actingPlayerSetStandingUp`
  - `reportList.reports[]`: `{reportId, ...}` — **all dice rolls and decisions live here** (section 4).
- **Turn segmentation**: maintain running `Half` (from `gameSetHalf`), `turnMode` (from `gameSetTurnMode`), `turnNr` (from `turnDataSetTurnNr`) while scanning — exactly what `parse_replay.py:44-63` does. Player turns are bracketed by `playerAction` reports and `turnEnd` reports; team turns by `turnDataSetTurnNr` + `gameSetHomePlaying`.

**Coordinates**: 26x15 pitch, `(0,0)` top-left, `(25,14)` bottom-right. Off-pitch X codes dugout boxes (`resources/Coordinate.csv`): home RSV/KO/BH/SI/RIP/BAN/MNG = -1..-7, away = 30..36.

## 3. Bit-packed playerState encoding

From `parse_replay.py:85-90`: low 8 bits = mutually exclusive base state, bits 9+ = decorations. The Python parser keeps only the base: `tmpChange['modelChangeValue'] & 255`. Authoritative source `vendor/ffb/ffb-common/.../PlayerState.java` (`getBase()` = `id & 0xFF`):

Base (0-255): `0 UNKNOWN, 1 STANDING, 2 MOVING, 3 PRONE, 4 STUNNED, 5 KNOCKED_OUT, 6 BADLY_HURT, 7 SERIOUS_INJURY, 8 RIP, 9 RESERVE, 10 MISSING, 11 FALLING, 12 BLOCKED, 13 BANNED, 14 EXHAUSTED, 15 BEING_DRAGGED, 16 PICKED_UP, 17 HIT_ON_GROUND/FIREBALL, 18 HIT_BY_LIGHTNING, 19 HIT_BY_BOMB, 20 SETUP_PREVENTED, 21 IN_THE_AIR`

Flag bits (current FFB source): `0x100 ACTIVE, 0x200 CONFUSED, 0x400 ROOTED, 0x800 HYPNOTIZED, 0x1000 SELECTED_STAB_TARGET, 0x2000 USED_PRO, 0x4000 SELECTED_BLITZ_TARGET, 0x8000 SELECTED_BLOCK_TARGET, 0x10000 SELECTED_GAZE_TARGET, 0x20000 EYE_GOUGED, 0x40000 CHOMPED`.

**Warning — stale table in the Python package**: `resources/PlayerState.csv` and `doc/fumbbl_replay_file_format.md` list `4096 BIT_BLOODLUST, 8192 BIT_USED_PRO, 16384 BIT_BLITZ_TARGET`, which disagrees with current FFB source (`0x1000` = stab target, `0x2000` = used pro, `0x4000` = blitz target). Trust `PlayerState.java`. Example from real data: `257 = 0x101 = STANDING + ACTIVE`.

## 4. Dice rolls (reportList)

reportIds observed in `example_input/1559380.json` with real payload shapes (full samples in `reference/replay-anatomy.md`):

- `blockRoll` `{choosingTeamId, blockRoll: [2,1], defenderId}` then `blockChoice` `{nrOfDice, blockRoll, diceIndex, blockResult: "BOTH DOWN", defenderId}`. `nrOfDice` **negative ⇒ opponent chooses** (`parse_blockchoice.py:6`). Die faces 1-6 map to `['@','%','>','>','!','*']` = Skull, Both Down, Push, Push, Defender Stumbles, Pow.
- `goForItRoll` / `pickUpRoll` / `passRoll` / `dodgeRoll` / `catchRoll` / `confusionRoll`: `{playerId, successful, roll, minimumRoll, reRolled}` (passRoll adds `passingDistance, passResult, hailMaryPass, bomb`).
- `injury` `{defenderId, attackerId, armorBroken, armorRoll: [5,4], injuryRoll: [5,1], casualtyRoll, injury: <playerState base>, armorModifiers: ["Mighty Blow"], injuryModifiers}` (`parse_injury.py`).
- `reRoll` `{playerId, reRollSource: "Catch"|"Team ReRoll"|..., successful, roll}`, `skillUse` `{playerId, skill, used, skillUse}`.
- `kickoffResult` `{kickoffResult: "High Kick", kickoffRoll: [1,4]}`, `kickoffScatter` `{ballCoordinateEnd, scatterDirection (d8: N,NE,E,SE,S,SW,W,NW), rollScatterDistance}`, `weather` `{weather, weatherRoll: [5,1]}`, `coinThrow`, `receiveChoice` `{teamId, receiveChoice: bool}`, `fanFactor`, `startHalf`.
- `turnEnd` `{playerIdTouchdown, knockoutRecoveryArray: [{playerId, recovering, roll}], heatExhaustionArray, unzapArray}` (`parse_turnend.py`).
- Pre/post-match: `cardsAndInducementsBought`, `apothecaryRoll`/`apothecaryChoice`, `officiousRefRoll`, `mostValuablePlayers`, `winnings`, `dedicatedFans`, `fumbblResultUpload`.

`playerAction` reports `{actingPlayerId, playerAction: "block"|"blitzMove"|"move"|"foul"|...}` open each player activation — `structure_player_actions.py` uses them to attribute subsequent rows to the acting player.

## 5. Curation recipe for BC corpus

**Exact audited inventory (2026-07-13):**

- 15,347 raw replay manifest entries;
- 11,580 embedded BB2025 and 3,767 embedded BB2020 replays;
- 12,304 BBP shards / 2,085,330 records;
- 9,170 joined BB2025 shards / 1,622,231 records;
- 9,118 non-empty BB2025 IDs in the strict allowlist at
  `runs/replay-audit-20260713/bb2025-nonempty.ids`.

The old phrase "12,304 replays" was wrong: it counted pair shards, not verified
BB2025 games. Determine edition from the replay's embedded `rulesVersion`, never
from filenames, directories, dates, API division, or successful conversion.
Never mix BB2020 into BB2025 BC.

BBP records are observation-lineage-specific; an observation change requires
re-extraction from cached raw replay data. BBS state banks store engine states,
not observations, but still require matching engine fingerprints and strict
edition/semantic validation.

### Coverage limitations

The joined BB2025 pairs are prefix-censored by lockstep divergence. Replay
coverage falls from 9,118 at the opening to 35 at the deepest encoded turn.
Pass/handoff/foul targets combined are only 1,040 records (`0.0641%`), with no
Jump, Throw Team-Mate, or Special targets. Therefore:

- do not use flat record accuracy as evidence of whole-game competence;
- do not use this corpus alone for second-half, late-drive, comeback, stalling,
  or rare-action policy;
- report metrics by turn/drive depth and action family;
- cap setup/opening mass and add purpose-built full-game/scenario data before
  training recurrent or late-game claims.

### Streaming and splits

Use `training/bc_pretrain.py`'s bounded streaming path:

- validate BBP headers and embedded replay IDs against the strict allowlist;
- split by replay ID, never record, so one match cannot leak across splits;
- keep the evict-before-open memory-map LRU and owning minibatches;
- evaluate in batches rather than materializing the corpus;
- use replay-first sampling as the current compatibility default.

Replay-first removes long-shard dominance but does not cure opening censorship.
The next sampler should be hierarchical:

```text
replay → roster/matchup → turn or drive depth → action family
```

The full strict-corpus probe used 9,118 shards / 1,622,231 records, a
7,294/1,824 replay-disjoint split, an 8-map cache, and about 179MB measured
footprint. Do not restore the projected ~10.55GB CPU + ~5.29GB device eager
loader.

### Human baselines

Corrected genuine BB2025 team-turn possession is `173,200 / 365,449 =
0.47393754` turn-weighted; per-game mean `0.47452514`, after excluding 47,599
synthetic observations. Use it as a diagnostic only, not as a reward or BC
optimization target.

### Acquisition filters

Filter on the cheap match JSON **before** downloading any replay:

1. `division` / `divisionId` — pick the ladder you want (example file: `divisionId: 5, division: "League"`; Competitive/Blackbox are the high-signal ladders). Filter on the `division` string.
2. `conceded != "None"` ⇒ drop (rage-quits truncate the action log; also `game.concededLegally` inside the replay).
3. `tournamentId` — nonzero means tournament game; keep or drop depending on whether you want tournament-pressure play.
4. Coach strength: `team{1,2}.coach.rating.pre.{r, cr, bracket}`. Filter by `bracket` (e.g. keep "Star"/"Super Star"/"Legend") or CR threshold. League-division matches often carry `cr: 0, bracket: "Rookie"` — rating is only meaningful on rated ladders, so combine with the division filter.
5. **Per game, imitate only the higher-rated coach**: compare `pre.r` (fall back to `pre.cr`), tag that team's actions as the BC target, treat the other side as environment.
6. Dedupe by `replayId`, cache forever (`~/.cache/fumbbl_replays/` layout in `get_cache_dir.py`); a replay is immutable once uploaded.
7. Enumerate candidate matches via `/api/team/matches/<teamId>` pagination, or coach/tournament-based discovery; record `(matchId, replayId, division, TVs, CRs, conceded)` in a manifest before bulk replay download.
8. After download, inspect embedded `rulesVersion`; exclude anything not BB2025
   before conversion, allowlist construction, state-bank construction, splitting,
   or metric calculation. API metadata is only a pre-download filter.

## 6. Normalizer skeleton

Minimal scan loop for (initial state, action log, dice log) — mirrors `parse_replay.py` without pandas:

```python
import gzip, json

def normalize(replay):
    init = {side: replay["game"][side] for side in ("teamHome", "teamAway")}
    half, mode, turn = 0, "startGame", 0
    actions, dice = [], []
    for cmd in replay["gameLog"]["commandArray"]:
        if cmd["netCommandId"] != "serverModelSync":
            continue
        for ch in cmd["modelChangeList"]["modelChangeArray"]:
            cid, key, val = ch["modelChangeId"], ch["modelChangeKey"], ch["modelChangeValue"]
            if cid == "gameSetHalf": half = val
            elif cid == "gameSetTurnMode": mode = val
            elif cid == "turnDataSetTurnNr": turn = val          # key is "home"/"away"
            elif cid == "fieldModelSetPlayerCoordinate":
                actions.append((cmd["commandNr"], half, turn, mode, "coord", key, tuple(val)))
            elif cid == "fieldModelSetPlayerState":
                actions.append((cmd["commandNr"], half, turn, mode, "state", key,
                                val & 0xFF, val & ~0xFF))        # (base, flags)
            elif cid == "fieldModelSetBallCoordinate" and hasattr(val, "__len__"):
                actions.append((cmd["commandNr"], half, turn, mode, "ball", None, tuple(val)))
        for rep in cmd["reportList"]["reports"]:
            dice.append((cmd["commandNr"], half, turn, mode, rep))  # rolls + decisions
    return init, actions, dice
```

Setup formations: take the **last** coord per player within `Half == 1, turn == 0, mode == "setup"`, drop X outside 0-25 (dugout) — exactly `plot_setups.py:34-40`.

## 7. Etiquette + throttling

FUMBBL is a **volunteer-run hobby server** (Christer Kaivo-oja, self-funded). Non-negotiables:

- **≤ ~1 req/s sustained.** The vendored package sleeps 0.3 s after every request (`fetch_match.py:29`, `fetch_replay.py:42`) — treat 1 s as the polite bulk-pull rate.
- **Cache everything, never re-fetch.** Replays are immutable; match JSON is stable once played. Mirror the `~/.cache/fumbbl_replays/` pattern.
- **API only, never scrape HTML.** Web pages sit behind Anubis anti-bot (proof-of-work challenge added ~2025); scripted page hits get challenged/blocked and burn server CPU. The JSON API is the supported path.
- **Courtesy heads-up to Christer before mass pulls** (thousands of replays): FUMBBL forum or Discord. Identify yourself with a descriptive `User-Agent` (e.g. `bloodbowl-rl-research/0.1 (contact email)`).
- Replays are several MB gzipped; use `stream=True` + `iter_content` chunking (`fetch_replay.py:36-41`) and keep them gzipped on disk.
- Auth: not needed for anything in this skill. OAuth exists (`/api/oauth/token`, client-credentials — see Jervis `FumbblApi.kt:86`) but the api-notes doc itself marks auth docs as TODO.

## 8. Known gaps in the Python parser (honest list)

`vendor/fumbbl_replays` was built for *setup/visualization analysis*, not full game reconstruction:

- **Inducements/pre-match not extracted**: `cardsAndInducementsBought` report has no parser; `turnDataHome.inducementSet`, cards, prayers (`prayerState`) untouched. README "not implemented": rerolls/apo/inducements on extracted rosters.
- **Dialog decisions dropped**: `gameSetDialogParameter` model changes are explicitly skipped (`parse_replay.py:36-42`) — re-roll/apothecary/skill-use dialogs must be inferred from reports instead.
- **State flag bits discarded** (`& 255`) and the bit table is stale (section 3).
- **Rules options ignored**: nothing reads `game.gameOptions`.
- **69 modelChangeIds blanket-ignored** via `resources/IgnoreModelChange.csv` (all `playerResult*`, `actingPlayer*` details, pushback squares, dice decorations...).
- Block attribution FIXME: pushes/pows/blitz-continuation after a `blockChoice` fall under action `"none"` (`structure_player_actions.py:44`).
- `from_steps_to_trajectories.py` indexes `df.iloc[r+1]` without bounds check (IndexError risk on final row); passes/interceptions, throw-team-mate, wizard effects have no structured handling.

**What Jervis handles that the Python parser doesn't** (`fumbbl-net/.../adapter/impl/`): a real `MapperChain` that replays commands into a BB2020 rules engine — setup (coin toss, fan factor, weather, kickoff, pitch invasion), move (rush, standing up, 3 end-move variants), block (re-rolls, pushback, Side Step, Dodge-skill use, follow-up), blitz (full sub-chain), foul start, catch/pickup/bounce, injury, end turn. Its own gaps: rules hard-coded to `StandardBB2020Rules` (`FumbblReplayAdapter.kt:45`), expects websocket-log format files (not the REST replay JSON), passing/throw-in/secret-weapons mappers absent, team-special-rules conversion is `TODO` (`FumbblApi.kt:276`). Use Jervis as the *reference semantics* for action mapping; use the REST JSON as the *data source*.

See `reference/replay-anatomy.md` for full field-level payload samples taken from `example_input/1559380.json`.
