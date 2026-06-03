#!/usr/bin/env python3
"""normalize_replay.py — FUMBBL replay JSON -> normalized JSONL.

Parses a cached replay (gzipped JSON, see .claude/skills/fumbbl-data
reference/replay-anatomy.md) into a flat, ordered JSONL stream:

  meta       one record: teams, rosters (id/name/race/coach), game options,
             receiving-team detection, command count
  formation  one record per setup segment: the LAST
             fieldModelSetPlayerCoordinate per player while turnMode=="setup"
             (on-pitch coords only; off-pitch x codes dugout boxes).
             Segment 0 of half 1 is the initial kickoff formation.
  dice       every dice-bearing report from reportList.reports, in command
             order, labelled with reportId + extracted roll values
  action     coach decisions visible in reports (playerAction, blockChoice,
             selectBlitzTarget, receiveChoice, apothecaryChoice, skillUse,
             coinThrow)
  event      game-flow markers (startHalf, turnEnd incl. KO-recovery rolls,
             foul/referee, pushback, block, handOver)
  move       fieldModelSetPlayerCoordinate outside setup (player trajectory)
  ball       fieldModelSetBallCoordinate (list-valued changes only)
  state      fieldModelSetPlayerState, split into base (& 0xFF, authoritative
             per vendor/ffb PlayerState.java) and flag bits
  coverage   one trailing record: per-reportId counts, handled vs skipped vs
             unknown

Every record carries (cmd, half, turn, mode) game-clock context maintained
from gameSetHalf / gameSetTurnMode / turnDataSetTurnNr model changes.

HONEST GAPS — what this normalizer does NOT yet handle:
  * Pre-match inducements/prayers/cards: cardsAndInducementsBought is counted
    but not decoded; turnData inducementSet / prayerState are untouched.
  * gameSetDialogParameter model changes are skipped (dialog decisions must be
    inferred from reports; same limitation as vendor/fumbbl_replays).
  * playerState FLAG bits are emitted raw, not interpreted (base state only
    is decoded); the stale CSV table in the Python package is NOT used.
  * Report types outside HANDLED/KNOWN_SKIPPED below are counted as unknown.
    Reports with roll-like fields are still emitted (kind="dice",
    untyped=true) so no dice silently vanish; the rest are dropped. Expect
    unknowns for mechanics absent from our sample games (interceptions,
    throw team-mate, chainsaw, stab, wizards, secret weapons, prayers, ...).
  * Model changes other than the coordinate/state/clock ones above are
    ignored (~69 UI-noise ids: move squares, track numbers, dice
    decorations, pushback squares, ...).
  * No action-level LOCKSTEP reconstruction: this emits an observation
    stream, it does not replay commands through the engine. The replay
    differential (validation layer 7) is the next milestone.

Usage:
  python3 validation/normalize_replay.py --all              # whole cache
  python3 validation/normalize_replay.py 1684902            # by replay id
  python3 validation/normalize_replay.py path/to/replay.json[.gz]
Output: validation/normalized/<replayId>.jsonl (+ coverage summary on stdout).
"""

import argparse
import collections
import glob
import gzip
import json
import os
import sys

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "replay_cache")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "normalized")

# --- report-type registry -----------------------------------------------------
# d6-test family: {playerId, successful, roll, minimumRoll, reRolled, ...}
# (names verified against the 2022 example replay AND 20 live 2026 BB2025-era
# Competitive replays; live FUMBBL emits many reportIds beyond the ones in the
# skill's documented sample)
D6_TEST_REPORTS = {
    "goForItRoll", "pickUpRoll", "dodgeRoll", "catchRoll", "confusionRoll",
    "passRoll", "interceptionRoll", "jumpRoll", "leapRoll", "jumpUpRoll",
    "standUpRoll", "alwaysHungryRoll", "regenerationRoll", "safeThrowRoll",
    "rightStuffRoll", "landingRoll", "chainsawRoll", "ttmRoll",
    "swarmingPlayersRoll", "escapeRoll", "lookIntoMyEyesRoll",
    "balefulHexRoll", "animalSavageryRoll", "trapDoorRoll",
    "stabRoll", "bribesRoll", "projectileVomitRoll", "hypnoticGazeRoll",
    # observed live 2026-06 (same {playerId, successful, roll, minimumRoll}
    # shape, sometimes with extra fields kept via the optional list below):
    "foulAppearanceRoll", "steadyFootingRoll", "dauntlessRoll",
    "gettingEvenRoll", "tentaclesShadowingRoll", "projectileVomit",
    "throwTeamMateRoll", "pickMeUp", "throwAtStallingPlayer",
    "spellEffectRoll", "dodgySnackRoll", "teamCaptainRoll", "mascotUsed",
}

# reportId -> output kind for everything we extract structurally.
HANDLED = {
    "blockRoll": "dice", "blockChoice": "action", "injury": "dice",
    "reRoll": "dice", "blockReRoll": "dice", "skillUse": "action",
    "kickoffResult": "dice",
    "kickoffScatter": "dice", "scatterBall": "dice", "scatterPlayer": "dice",
    "throwIn": "dice", "weather": "dice",
    "coinThrow": "action", "receiveChoice": "action", "fanFactor": "dice",
    "startHalf": "event", "turnEnd": "event", "apothecaryRoll": "dice",
    "apothecaryChoice": "action", "officiousRefRoll": "dice",
    "kickoffOfficiousRef": "dice", "cheeringFans": "dice",
    "dedicatedFans": "dice", "extraReRoll": "dice", "winnings": "dice",
    "playerAction": "action", "selectBlitzTarget": "action",
    "foul": "event", "referee": "event", "pushback": "event",
    "block": "event", "handOver": "event",
    # kickoff-event + pre-match rolls observed live 2026-06:
    "prayerRoll": "dice", "argueTheCall": "dice", "quickSnapRoll": "dice",
    "blitzRoll": "dice", "solidDefenceRoll": "dice",
    "kickoffDodgySnack": "dice", "kickoffPitchInvasion": "dice",
    "masterChefRoll": "dice", "secretWeaponBan": "dice",
    # dice-free flow markers observed live 2026-06 (passthrough payload):
    "stallerDetected": "event", "leader": "event", "kickoffTimeout": "event",
    "inducement": "event", "animalSavagery": "event", "raiseDead": "event",
    "hitAndRun": "event", "brilliantCoachingReRoll": "event",
    "briberyAndCorruptionReRoll": "event",
}
HANDLED.update({rid: "dice" for rid in D6_TEST_REPORTS})

# Known report types we deliberately do not extract (no dice / not needed for
# formations+dice+actions). Counted in coverage as skipped_known.
KNOWN_SKIPPED = {
    "mostValuablePlayers", "fumbblResultUpload", "cardsAndInducementsBought",
    "playerEvent", "gameOptions", "spectators", "timeoutEnforced",
    "freePettyCash", "prayersAndInducementsBought",
    "kickoffSequenceActivationsCount", "kickoffSequenceActivationsExhausted",
}

# Keys whose presence marks an UNKNOWN report as dice-bearing -> still emitted.
ROLLISH_KEYS = ("roll", "blockRoll", "armorRoll", "injuryRoll", "casualtyRoll",
                "rollHome", "rollAway", "weatherRoll", "kickoffRoll", "rolls",
                "minimumRoll")


def extract_report(rep):
    """Return the normalized payload for a handled report (rep minus noise)."""
    rid = rep["reportId"]
    if rid in D6_TEST_REPORTS:
        out = {k: rep.get(k) for k in
               ("playerId", "successful", "roll", "minimumRoll", "reRolled")}
        for k in ("rollModifiers", "passingDistance", "passResult",
                  "confusionSkill", "hailMaryPass", "bomb", "defenderId",
                  "thrownPlayerId", "strength", "keyword", "skill", "teamId",
                  "specialEffect"):
            if rep.get(k):
                out[k] = rep[k]
        return out
    if rid == "blockRoll":
        return {k: rep.get(k) for k in ("choosingTeamId", "blockRoll", "defenderId")}
    if rid == "blockChoice":
        nd = rep.get("nrOfDice", 0)
        return {"nrOfDice": abs(nd), "defenderChooses": nd < 0,
                "blockRoll": rep.get("blockRoll"), "diceIndex": rep.get("diceIndex"),
                "blockResult": rep.get("blockResult"), "defenderId": rep.get("defenderId")}
    if rid == "injury":
        return {k: rep.get(k) for k in
                ("defenderId", "attackerId", "injuryType", "armorBroken",
                 "armorRoll", "injuryRoll", "casualtyRoll", "seriousInjury",
                 "injury", "armorModifiers", "injuryModifiers",
                 "casualtyModifiers")}
    if rid == "reRoll":
        return {k: rep.get(k) for k in
                ("playerId", "reRollSource", "successful", "roll")}
    if rid == "skillUse":
        return {k: rep.get(k) for k in ("playerId", "skill", "used", "skillUse")}
    if rid == "kickoffResult":
        return {k: rep.get(k) for k in ("kickoffResult", "kickoffRoll")}
    if rid == "kickoffScatter":
        return {k: rep.get(k) for k in
                ("ballCoordinateEnd", "scatterDirection", "rollScatterDirection",
                 "rollScatterDistance")}
    if rid == "scatterBall":
        return {k: rep.get(k) for k in ("directionArray", "rolls", "gustOfWind")}
    if rid == "scatterPlayer":
        return {k: rep.get(k) for k in
                ("startCoordinate", "endCoordinate", "directionArray", "rolls")}
    if rid == "throwIn":
        return {k: rep.get(k) for k in ("direction", "directionRoll", "distanceRoll")}
    if rid == "blockReRoll":
        return {k: rep.get(k) for k in ("playerId", "blockRoll", "reRollSource")}
    if rid == "prayerRoll":
        return {k: rep.get(k) for k in ("roll", "teamName", "homeTeam")}
    if rid == "argueTheCall":
        return {k: rep.get(k) for k in
                ("playerId", "roll", "successful", "coachBanned", "staysOnPitch")}
    if rid in ("quickSnapRoll", "blitzRoll", "solidDefenceRoll"):
        return {k: rep.get(k) for k in ("teamId", "nrOfPlayers", "roll")}
    if rid in ("kickoffDodgySnack", "kickoffPitchInvasion"):
        return {k: rep.get(k) for k in
                ("rollHome", "rollAway", "amount", "playerIds")}
    if rid == "masterChefRoll":
        return {k: rep.get(k) for k in ("teamId", "masterChefRoll", "reRollsStolen")}
    if rid == "secretWeaponBan":
        return {k: rep.get(k) for k in ("playerIds", "rolls", "banArray")}
    if rid == "weather":
        return {k: rep.get(k) for k in ("weather", "weatherRoll")}
    if rid == "coinThrow":
        return {k: rep.get(k) for k in ("coach", "coinThrowHeads", "coinChoiceHeads")}
    if rid == "receiveChoice":
        return {k: rep.get(k) for k in ("teamId", "receiveChoice")}
    if rid == "fanFactor":
        return {k: rep.get(k) for k in
                ("teamId", "dedicatedFans", "dedicatedFansRoll", "dedicatedFansResult")}
    if rid == "startHalf":
        return {"half": rep.get("half")}
    if rid == "turnEnd":
        return {k: rep.get(k) for k in
                ("playerIdTouchdown", "knockoutRecoveryArray",
                 "heatExhaustionArray", "heatRoll")}
    if rid == "apothecaryRoll":
        return {k: rep.get(k) for k in
                ("playerId", "casualtyRoll", "playerState", "seriousInjury")}
    if rid == "apothecaryChoice":
        return {k: rep.get(k) for k in ("playerId", "playerState", "seriousInjury")}
    if rid in ("officiousRefRoll",):
        return {k: rep.get(k) for k in ("playerId", "roll")}
    if rid == "kickoffOfficiousRef":
        return {k: rep.get(k) for k in ("rollHome", "rollAway", "playerIdsHit")}
    if rid in ("cheeringFans", "extraReRoll"):
        return {k: rep.get(k) for k in ("teamId", "rollHome", "rollAway")}
    if rid == "dedicatedFans":
        return {k: rep.get(k) for k in
                ("rollHome", "rollAway", "dedicatedFansModifierHome",
                 "dedicatedFansModifierAway")}
    if rid == "winnings":
        return {k: rep.get(k) for k in ("winningsHome", "winningsAway")}
    if rid == "playerAction":
        return {k: rep.get(k) for k in ("actingPlayerId", "playerAction")}
    if rid == "selectBlitzTarget":
        return {k: rep.get(k) for k in ("attackerId", "defenderId")}
    if rid in ("foul", "block", "handOver"):
        return {k: v for k, v in rep.items() if k != "reportId"}
    if rid == "referee":
        return {k: rep.get(k) for k in ("foulingPlayerBanned", "underScrutiny")}
    if rid == "pushback":
        return {k: rep.get(k) for k in ("defenderId", "pushbackMode")}
    # Fallback for HANDLED ids without a bespoke extractor: pass through.
    return {k: v for k, v in rep.items() if k != "reportId"}


def load_replay(spec):
    """spec: replay id, or a path to .json / .json.gz."""
    if os.path.exists(spec):
        path = spec
    else:
        path = os.path.join(CACHE_DIR, f"replay_{spec}.json.gz")
        if not os.path.exists(path):
            raise FileNotFoundError(f"no cached replay for {spec!r} ({path})")
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8") as f:
        return json.load(f), path


def team_meta(team):
    return {
        "teamId": team.get("teamId"),
        "teamName": team.get("teamName"),
        "coach": team.get("coach"),
        "race": team.get("race"),
        "reRolls": team.get("reRolls"),
        "apothecaries": team.get("apothecaries"),
        "fanFactor": team.get("fanFactor"),
        "teamValue": team.get("teamValue"),
        "players": [
            {"playerId": p.get("playerId"), "playerNr": p.get("playerNr"),
             "name": p.get("playerName"), "positionId": p.get("positionId"),
             "ma": p.get("movement"), "st": p.get("strength"),
             "ag": p.get("agility"), "pa": p.get("passing"),
             "av": p.get("armour"), "skills": p.get("skillArray", [])}
            for p in team.get("playerArray", [])
        ],
    }


def normalize(replay, replay_id):
    """Yields normalized records (dicts) in order."""
    game = replay.get("game", {})
    commands = replay.get("gameLog", {}).get("commandArray", [])

    coverage = collections.Counter()
    kinds = {"handled": collections.Counter(),
             "skipped_known": collections.Counter(),
             "unknown_with_dice": collections.Counter(),
             "unknown_skipped": collections.Counter()}

    # Receiving-team detection (skill: replay-anatomy "Receiving-team
    # detection"): gameSetHomeFirstOffense seen while still in the parser's
    # startGame filler mode => home receives.
    home_first_offense = None
    receive_choice = None

    half, mode, turn = 0, "startGame", 0
    setup_segment = -1
    setup_coords = {}    # playerId -> [x, y] (current segment, on-pitch only)
    in_setup = False
    records = []

    def flush_setup(cmd_nr):
        nonlocal setup_coords
        if setup_coords:
            records.append({
                "type": "formation", "cmd": cmd_nr, "half": half,
                "segment": setup_segment,
                "players": dict(setup_coords),
            })
        setup_coords = {}

    for cmd in commands:
        if cmd.get("netCommandId") != "serverModelSync":
            coverage["__netCommand_" + str(cmd.get("netCommandId"))] += 1
            continue
        cmd_nr = cmd.get("commandNr")

        for ch in (cmd.get("modelChangeList") or {}).get("modelChangeArray", []):
            cid = ch.get("modelChangeId")
            key = ch.get("modelChangeKey")
            val = ch.get("modelChangeValue")
            if cid == "gameSetHalf":
                half = val
            elif cid == "gameSetTurnMode":
                if val == "setup" and not in_setup:
                    in_setup = True
                    setup_segment += 1
                    setup_coords = {}
                elif val != "setup" and in_setup:
                    in_setup = False
                    flush_setup(cmd_nr)
                mode = val
            elif cid == "turnDataSetTurnNr":
                turn = val
            elif cid == "gameSetHomeFirstOffense" and mode == "startGame":
                home_first_offense = bool(val)
            elif cid == "fieldModelSetPlayerCoordinate":
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    x, y = val
                    if in_setup:
                        if 0 <= x <= 25:          # on-pitch; off-pitch = dugout
                            setup_coords[key] = [x, y]
                        else:
                            setup_coords.pop(key, None)
                    else:
                        records.append({"type": "move", "cmd": cmd_nr,
                                        "half": half, "turn": turn,
                                        "mode": mode, "player": key,
                                        "to": [x, y]})
            elif cid == "fieldModelSetBallCoordinate":
                if isinstance(val, (list, tuple)) and len(val) == 2:
                    records.append({"type": "ball", "cmd": cmd_nr, "half": half,
                                    "turn": turn, "mode": mode,
                                    "at": [val[0], val[1]]})
            elif cid == "fieldModelSetPlayerState":
                if isinstance(val, int):
                    records.append({"type": "state", "cmd": cmd_nr,
                                    "half": half, "turn": turn, "mode": mode,
                                    "player": key, "base": val & 0xFF,
                                    "flags": val & ~0xFF})
            # everything else: UI noise / not yet modelled (see module doc)

        for rep in (cmd.get("reportList") or {}).get("reports", []):
            rid = rep.get("reportId")
            coverage[rid] += 1
            if rid in HANDLED:
                kinds["handled"][rid] += 1
                rec = {"type": HANDLED[rid], "cmd": cmd_nr, "half": half,
                       "turn": turn, "mode": mode, "report": rid}
                rec.update(extract_report(rep))
                records.append(rec)
                if rid == "receiveChoice":
                    receive_choice = {"teamId": rep.get("teamId"),
                                      "receive": rep.get("receiveChoice")}
            elif rid in KNOWN_SKIPPED:
                kinds["skipped_known"][rid] += 1
            elif any(k in rep for k in ROLLISH_KEYS):
                kinds["unknown_with_dice"][rid] += 1
                rec = {"type": "dice", "cmd": cmd_nr, "half": half,
                       "turn": turn, "mode": mode, "report": rid,
                       "untyped": True}
                rec.update({k: v for k, v in rep.items() if k != "reportId"})
                records.append(rec)
            else:
                kinds["unknown_skipped"][rid] += 1

    if in_setup:                       # replay ended mid-setup (shouldn't)
        flush_setup(None)

    meta = {
        "type": "meta",
        "replayId": replay_id,
        "gameId": game.get("gameId"),
        "finished": game.get("finished"),
        "concededLegally": game.get("concededLegally"),
        "homeFirstOffense": home_first_offense,
        "receiveChoice": receive_choice,
        "score": {"home": (game.get("gameResult", {}).get("teamResultHome") or {}).get("score"),
                  "away": (game.get("gameResult", {}).get("teamResultAway") or {}).get("score")},
        "teamHome": team_meta(game.get("teamHome", {})),
        "teamAway": team_meta(game.get("teamAway", {})),
        "gameOptions": {o.get("gameOptionId"): o.get("gameOptionValue")
                        for o in (game.get("gameOptions", {}) or {})
                        .get("gameOptionArray", [])},
        "nCommands": len(commands),
    }
    cov = {
        "type": "coverage",
        "report_counts": dict(coverage),
        "handled": dict(kinds["handled"]),
        "skipped_known": dict(kinds["skipped_known"]),
        "unknown_with_dice": dict(kinds["unknown_with_dice"]),
        "unknown_skipped": dict(kinds["unknown_skipped"]),
        "handled_types": len(kinds["handled"]),
        "skipped_known_types": len(kinds["skipped_known"]),
        "unknown_types": len(kinds["unknown_with_dice"]) + len(kinds["unknown_skipped"]),
    }
    return [meta] + records + [cov], cov


def process(spec, quiet=False):
    replay, path = load_replay(spec)
    base = os.path.basename(path)
    replay_id = (base.replace("replay_", "").replace(".json.gz", "")
                 .replace(".json", ""))
    records, cov = normalize(replay, replay_id)
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{replay_id}.jsonl")
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if not quiet:
        n_dice = sum(1 for r in records if r.get("type") == "dice")
        n_form = sum(1 for r in records if r.get("type") == "formation")
        n_act = sum(1 for r in records if r.get("type") == "action")
        print(f"{replay_id}: {len(records)} records -> {out_path}")
        print(f"  formations={n_form} dice={n_dice} actions={n_act}  "
              f"report types: {cov['handled_types']} handled, "
              f"{cov['skipped_known_types']} known-skipped, "
              f"{cov['unknown_types']} unknown")
        for bucket in ("unknown_with_dice", "unknown_skipped"):
            if cov[bucket]:
                print(f"  {bucket}: {cov[bucket]}")
    return cov


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("specs", nargs="*",
                    help="replay ids or paths to replay .json/.json.gz files")
    ap.add_argument("--all", action="store_true",
                    help="normalize every replay in validation/replay_cache/")
    args = ap.parse_args()

    specs = list(args.specs)
    if args.all:
        specs += sorted(glob.glob(os.path.join(CACHE_DIR, "replay_*.json.gz")))
    if not specs:
        ap.error("give replay ids/paths or --all")

    agg = collections.Counter()
    buckets = {b: collections.Counter() for b in
               ("handled", "skipped_known", "unknown_with_dice", "unknown_skipped")}
    for spec in specs:
        cov = process(spec)
        agg.update(cov["report_counts"])
        for b in buckets:
            buckets[b].update(cov[b])

    if len(specs) > 1:
        total = sum(agg.values())
        handled = sum(buckets["handled"].values())
        print(f"\n=== aggregate over {len(specs)} replays ===")
        print(f"reports: {total} total, {handled} handled "
              f"({100.0 * handled / max(total, 1):.1f}%), "
              f"{sum(buckets['skipped_known'].values())} known-skipped, "
              f"{sum(buckets['unknown_with_dice'].values())} unknown-with-dice (emitted untyped), "
              f"{sum(buckets['unknown_skipped'].values())} unknown-skipped")
        print(f"report types: {len(buckets['handled'])} handled, "
              f"{len(buckets['skipped_known'])} known-skipped, "
              f"{len(buckets['unknown_with_dice']) + len(buckets['unknown_skipped'])} unknown")
        for b in ("unknown_with_dice", "unknown_skipped"):
            if buckets[b]:
                print(f"{b}: {dict(buckets[b].most_common())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
