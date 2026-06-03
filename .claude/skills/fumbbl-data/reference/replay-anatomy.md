# FUMBBL Replay JSON — field-level reference

All samples extracted from real files in `vendor/fumbbl_replays/example_input/`
(match 4407782 ↔ replay 1559380, Chaos Dwarf vs Human, League div, 2022-09-25).
Inspect interactively:

```python
import gzip, json
replay = json.load(gzip.open("~/.cache/fumbbl_replays/raw/replay_files/1559380.gz"))
# or the checked-in copy:
replay = json.load(open("vendor/fumbbl_replays/example_input/1559380.json"))
```

## Match JSON (`/api/match/get/<matchId>`)

```json
{
  "id": 4407782, "replayId": 1559380,
  "tournamentId": 58323, "divisionId": 5, "division": "League",
  "scheduler": "None", "date": "2022-09-25", "time": "22:57:05",
  "gate": 0, "conceded": "None", "hasComments": "false",
  "team1": {
    "id": 1094059, "name": "[Gonzi] Scuola caoz",
    "roster": {"id": 5142, "name": "Chaos Dwarf"},
    "score": 1, "casualties": {"bh": 0, "si": 0, "rip": 0},
    "fanfactor": 0, "teamValue": 1150000, "currentTeamValue": 1150000,
    "coach": {"id": 226619, "name": "Ferra76",
              "rating": {"pre":  {"cr": 0, "bracket": "Rookie"},
                         "post": {"cr": 0, "bracket": "Rookie"}}},
    "winnings": 40000, "gate": 0, "tournamentWeight": "1150k"
  },
  "team2": { ...same shape... }
}
```

Live-verified 2026-06-02: current matches on rated divisions additionally carry
`rating.pre.r` (numeric rating) alongside `cr`/`bracket`. Treat `r` as optional.
`conceded` is `"None"` or names the conceding side.

## Replay top level

```json
{
  "gameStatus": "uploaded",
  "stepStack": {"steps": []},
  "gameLog": {"commandArray": [ ...3598 commands... ]},
  "game": { ... final game state, both teams, full rosters ... },
  "playerIds": [],
  "swarmingPlayerActual": 0,
  "passState": {"catcherId": "...", "passResult": null, ...},
  "prayerState": {"friendsWithRef": [], "molesUnderThePitch": [], ...},
  "activeEffects": {}
}
```

## `game` object keys

`gameId, scheduled, started, finished, homePlaying, half, homeFirstOffense,
setupOffense, waitingForOpponent, turnTime, gameTime, timeoutPossible,
timeoutEnforced, concessionPossible, testing, turnMode, lastTurnMode,
defenderId, lastDefenderId, defenderAction, passCoordinate, throwerId,
throwerAction, teamState, teamAway, turnDataAway, teamHome, turnDataHome,
fieldModel, actingPlayer, gameResult, gameOptions, dialogParameter,
concededLegally`

### `game.teamHome` / `game.teamAway`

`teamId, teamName, coach, race, reRolls, apothecaries, cheerleaders,
assistantCoaches, fanFactor, teamValue, treasury, baseIconPath, logoUrl,
dedicatedFans, specialRules, playerArray, roster`

Player (`playerArray[i]`):
`playerKind, playerId, playerNr, positionId, playerName, playerGender,
playerType, movement, strength, agility, passing, armour, lastingInjuries,
recoveringInjury, urlPortrait, urlIconSet, nrOfIcons, positionIconIndex,
skillArray, temporarySkillsMap, temporaryModifiersMap, temporaryPropertiesMap,
skillValuesMap, skillDisplayValuesMap, playerStatus, usedSkills`

Roster (`team*.roster`):
`rosterId, rosterName, reRollCost, maxReRolls, baseIconPath, logoUrl,
raisedPositionId, apothecary, necromancer, undead, riotousPositionId,
nameGenerator, maxBigGuys, positionArray`
— `positionArray[i]` has `positionId, positionName, shorthand, cost, urlIconSet,
skillArray` (see `extract_rosters_from_replay.py:45-72`). Includes ALL hireable
positions + star players, not just rostered ones.

### `game.turnDataHome` / `turnDataAway`

`homeData, turnStarted, turnNr, firstTurnAfterKickoff, reRolls,
rerollBrilliantCoachingOneDrive, apothecaries, blitzUsed, foulUsed, reRollUsed,
handOverUsed, passUsed, coachBanned, ktmUsed, bombUsed, leaderState,
inducementSet {inducementArray, cardsAvailable, cardsActive, cardsDeactivated,
prayers}, wanderingApothecaries, rerollPumpUpTheCrowdOneDrive, plagueDoctors`

### `game.fieldModel`

`weather, ballCoordinate, ballInPlay, ballMoving, bombCoordinate, bombMoving,
bloodspotArray, pushbackSquareArray, moveSquareArray, trackNumberArray,
diceDecorationArray, fieldMarkerArray, playerMarkerArray, playerDataArray,
trapDoors`

### `game.gameResult.teamResult{Home,Away}`

`score, conceded, raisedDead, spectators, fame, winnings, fanFactorModifier,
badlyHurtSuffered, seriousInjurySuffered, ripSuffered, spirallingExpenses,
playerResults, pettyCashFromTvDiff, pettyCashTransferred, pettyCashUsed,
teamValue, treasuryUsedOnInducements, fanFactor, dedicatedFans, penaltyScore`

### `game.gameOptions`

```json
{"gameOptionArray": [
  {"gameOptionId": "forceTreasuryToPettyCash", "gameOptionValue": "true"},
  {"gameOptionId": "spikedBall", "gameOptionValue": "false"},
  {"gameOptionId": "clawDoesNotStack", "gameOptionValue": "true"}, ...]}
```

## Command stream (`gameLog.commandArray[i]`)

```json
{"netCommandId": "serverModelSync", "commandNr": 42,
 "modelChangeList": {"modelChangeArray": [...]},
 "reportList": {"reports": [...]},
 "sound": "...", "gameTime": 123456, "turnTime": 7890}
```

`netCommandId` is `"serverModelSync"` for essentially every command
(`serverAddPlayer` exists, ignored by `parse_replay.py:109`). Times in ms.

### Model change samples (real)

```json
{"modelChangeId": "gameSetTurnMode",            "modelChangeKey": null,       "modelChangeValue": "setup"}
{"modelChangeId": "fieldModelSetPlayerState",   "modelChangeKey": "15091677", "modelChangeValue": 257}
{"modelChangeId": "fieldModelSetPlayerCoordinate","modelChangeKey": "15091677","modelChangeValue": [12, 7]}
{"modelChangeId": "fieldModelSetBallCoordinate","modelChangeKey": null,       "modelChangeValue": [19, 8]}
{"modelChangeId": "turnDataSetTurnNr",          "modelChangeKey": "away",     "modelChangeValue": 1}
```

`257 = 0x101` = STANDING (base 1) + BIT_ACTIVE (0x100).
`fieldModelSetBallCoordinate` value may be `0` or `null` — check
`hasattr(value, "__len__")` like `parse_replay.py:76`.

### modelChangeId frequency (one full game, 1559380)

```
fieldModelAddMoveSquare 6573      fieldModelRemoveMoveSquare 6573
fieldModelSetPlayerState 1424     fieldModelSetPlayerCoordinate 1268
fieldModelRemoveSkillEnhancements 993   actingPlayerSetCurrentMove 905
fieldModelAddTrackNumber 861      actingPlayerSetStrength 614
actingPlayerSetPlayerId 614       gameSetDialogParameter 403
actingPlayerSetPlayerAction 369   playerResultSetTurnsPlayed 332
actingPlayerSetOldPlayerState 307 fieldModelAddPushbackSquare 233
actingPlayerSetHasMoved 230       fieldModelAddDiceDecoration 226
gameSetLastTurnMode 192           gameSetTurnMode 192
gameSetDefenderId 170             fieldModelRemovePlayer 106
fieldModelSetBallCoordinate 104   gameSetHomePlaying 101
actingPlayerSetGoingForIt 98      actingPlayerSetHasBlocked 84
turnDataSetTurnStarted 62         turnDataSetBlitzUsed 60
actingPlayerSetStandingUp 42      turnDataSetTurnNr 34
```

Most of the high-volume ones are UI noise (move squares, track numbers, dice
decorations) — that is what `resources/IgnoreModelChange.csv` filters.

### Report samples (real, one per reportId)

```json
{"reportId": "playerAction", "actingPlayerId": "15064980", "playerAction": "block"}
{"reportId": "blockRoll", "choosingTeamId": "1092298", "blockRoll": [2, 1], "defenderId": null}
{"reportId": "blockChoice", "nrOfDice": 2, "blockRoll": [2, 1], "diceIndex": 0,
 "blockResult": "BOTH DOWN", "defenderId": "15091675",
 "suppressExtraEffectHandling": false, "showNameInReport": false, "blockRollId": 0}
{"reportId": "goForItRoll", "playerId": "15091676", "successful": true, "roll": 4,
 "minimumRoll": 2, "reRolled": false}
{"reportId": "pickUpRoll", "playerId": "15091682", "successful": true, "roll": 3,
 "minimumRoll": 3, "reRolled": false}
{"reportId": "passRoll", "playerId": "15064982", "successful": true, "roll": 3,
 "minimumRoll": 2, "reRolled": false, "passingDistance": "Quick Pass",
 "passResult": "ACCURATE", "hailMaryPass": false, "bomb": false}
{"reportId": "reRoll", "playerId": "15064984", "reRollSource": "Catch",
 "successful": true, "roll": 0}
{"reportId": "skillUse", "playerId": "15064983", "skill": "Dodge", "used": true,
 "skillUse": "avoidFalling"}
{"reportId": "injury", "defenderId": "...", "injuryType": "block",
 "armorBroken": true, "armorRoll": [5, 4], "injuryRoll": [5, 1],
 "casualtyRoll": null, "seriousInjury": null, "injury": 4,
 "attackerId": "...", "armorModifiers": ["Mighty Blow"],
 "injuryModifiers": [], "casualtyModifiers": [], "skipInjuryParts": "NONE"}
{"reportId": "turnEnd", "playerIdTouchdown": "16074189",
 "knockoutRecoveryArray": [{"playerId": "16074191", "recovering": true,
   "roll": 6, "bloodweiserBabes": 0, "reason": null}],
 "heatExhaustionArray": [], "unzapArray": [], "heatRoll": 0}
{"reportId": "weather", "weather": "Nice Weather", "weatherRoll": [5, 1]}
{"reportId": "kickoffResult", "kickoffResult": "High Kick", "kickoffRoll": [1, 4]}
```

`injury.injury` is a playerState **base** value (4 = STUNNED, 5 = KO, ...).
`blockChoice.nrOfDice < 0` ⇒ defender's coach picks the die
(`parse_blockchoice.py:6` uses `abs()`).

### All reportIds seen in one full game (with counts)

```
playerAction 307, blockRoll 92, block 91, blockChoice 84, injury 57,
turnEnd 36, selectBlitzTarget 30, goForItRoll 25, dodgeRoll 20, reRoll 15,
confusionRoll 15, catchRoll 9, scatterBall 8, kickoffScatter 4,
kickoffResult 4, pickUpRoll 3, fanFactor 2, cardsAndInducementsBought 2,
startHalf 2, apothecaryRoll 2, skillUse 2, officiousRefRoll 2, weather 1,
coinThrow 1, receiveChoice 1, apothecaryChoice 1, extraReRoll 1, pushback 1,
foul 1, referee 1, kickoffOfficiousRef 1, cheeringFans 1, passRoll 1,
handOver 1, mostValuablePlayers 1, winnings 1, dedicatedFans 1,
fumbblResultUpload 1
```

This list is per-game, not exhaustive across the ruleset: expect additional ids
in other games (interceptions, throw team-mate, wizards, chainsaw, stab,
secret weapons, prayers...). Jervis's command model
(`vendor/jervis-ffb/modules/fumbbl-net/src/commonMain/kotlin/com/jervisffb/fumbbl/net/model/reports/`)
enumerates the full set.

## turnMode values (observed)

`setup, kickoff, highKick, regular, betweenTurns, selectBlitzTarget, endGame`
— plus `startGame`, which is the parser's initial default before the first
`gameSetTurnMode` change (never emitted as a model-change value itself; the
receiving-team query `turnMode == "startGame"` relies on this filler).
(Also `quickSnap`/`blitz` kickoff-event modes exist in other games — the
package docs note "Should check for quick snap etc.",
`doc/package_internals.md:61`).

## Coordinate system

26 wide x 15 tall, `(0,0)` top-left, home half X 0-12, away half X 13-25.
Dugout pseudo-X (`resources/Coordinate.csv`):

| box | home | away |
|---|---|---|
| Reserve | -1 | 30 |
| KO | -2 | 31 |
| Badly Hurt | -3 | 32 |
| Serious Injury | -4 | 33 |
| RIP | -5 | 34 |
| Banned | -6 | 35 |
| Miss Next Game | -7 | 36 |

Setup-phase rows with X outside 0-25 mean "placed back in dugout"
(`parse_replay.py:141-145`, `to_dugout` flag).

## Receiving-team detection

- `gameSetHomeFirstOffense` present during `startGame` ⇒ home receives, else away
  (`parse_replay.py:149-156`, clunky-but-works per `package_internals.md:108`).
- Or the `receiveChoice` report: `{teamId, receiveChoice: true|false}`
  (`extract_coin_toss` / `extract_receive_choice` in `parse_replay.py:158-179`).
