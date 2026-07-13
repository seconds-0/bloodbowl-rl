#!/usr/bin/env python3
"""Measure human possession at genuine FUMBBL team-turn boundaries.

The environment metric is the fraction of completed team turns that end with
the active team holding the ball; a touchdown by that team counts as held.
FUMBBL's ``gameSetHomePlaying`` is not a turn-boundary signal: setup, kickoff
events, defensive choices, and between-turn cleanup toggle it several times.
Older versions of this tool counted every toggle and inflated the denominator
by roughly 3x.  This implementation opens a turn only when
``turnDataSetTurnStarted=true`` occurs in ``regular`` mode and closes it on a
subsequent ``turnEnd`` report.

BB2020 and BB2025 overlap by date in the cache.  BB2025 is the default and is
selected by each replay's embedded ``rulesVersion`` field, never by date.
"""

from __future__ import annotations

import argparse
import glob
import gzip
import json
import statistics
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CACHE = ROOT / "validation" / "replay_cache"


def side_map(game: dict[str, Any]) -> dict[str, str]:
    result = {}
    for side, key in (("home", "teamHome"), ("away", "teamAway")):
        players = (game.get(key, {}) or {}).get("playerArray", []) or []
        for player in players:
            player_id = player.get("playerId")
            if player_id is not None:
                result[str(player_id)] = side
    return result


def rules_version(game: dict[str, Any]) -> str:
    options = (
        (game.get("gameOptions", {}) or {}).get("gameOptionArray", []) or []
    )
    for option in options:
        if option.get("gameOptionId") == "rulesVersion":
            return str(option.get("gameOptionValue", "UNKNOWN"))
    return "UNKNOWN"


def _read_replay(path: Path) -> dict[str, Any]:
    if path.suffix == ".gz":
        with gzip.open(path, "rt", encoding="utf-8") as f:
            return json.load(f)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def settled_holder_side(positions: dict[str, tuple[int, int]],
                        player_side: dict[str, str], ball_x: int | None,
                        ball_y: int | None, ball_in_play: bool,
                        ball_moving: bool) -> str | None:
    if not ball_in_play or ball_moving or ball_x is None or ball_y is None:
        return None
    for player_id, position in positions.items():
        if position == (ball_x, ball_y):
            return player_side.get(player_id)
    return None


def replay_possession(path: str | Path) -> dict[str, Any] | None:
    try:
        replay = _read_replay(Path(path))
    except (OSError, json.JSONDecodeError):
        return None

    game = replay.get("game", {}) or {}
    player_side = side_map(game)
    if not player_side:
        return None

    positions: dict[str, tuple[int, int]] = {}
    ball_x = ball_y = None
    ball_moving = False
    ball_in_play = False
    turn_mode = game.get("turnMode")
    open_turn_side = None
    turn_ends = held_ends = synthetic_turn_ends = 0
    turns_by_side = {"home": 0, "away": 0}
    held_by_side = {"home": 0, "away": 0}

    commands = (replay.get("gameLog", {}) or {}).get("commandArray", []) or []
    for command in commands:
        reports = (command.get("reportList") or {}).get("reports", []) or []
        has_turn_end = any(
            report.get("reportId") == "turnEnd" for report in reports)
        mode_before = turn_mode
        holder_before = None
        if has_turn_end:
            holder_before = settled_holder_side(
                positions, player_side, ball_x, ball_y,
                ball_in_play, ball_moving)
        started_sides = []
        changes = (
            (command.get("modelChangeList") or {}).get("modelChangeArray", [])
            or []
        )
        for change in changes:
            change_id = change.get("modelChangeId", "")
            key = change.get("modelChangeKey")
            value = change.get("modelChangeValue")
            if (change_id == "fieldModelSetPlayerCoordinate" and
                    key is not None and isinstance(value, list) and
                    len(value) == 2):
                positions[str(key)] = (value[0], value[1])
            elif change_id == "fieldModelRemovePlayer" and key is not None:
                positions.pop(str(key), None)
            elif (change_id == "fieldModelSetBallCoordinate" and
                  isinstance(value, list) and len(value) == 2):
                ball_x, ball_y = value[0], value[1]
            elif change_id == "fieldModelSetBallMoving":
                ball_moving = bool(value)
            elif change_id == "fieldModelSetBallInPlay":
                ball_in_play = bool(value)
            elif change_id == "gameSetTurnMode":
                turn_mode = value
            elif (change_id == "turnDataSetTurnStarted" and value is True and
                  key in ("home", "away")):
                started_sides.append(key)

        # Use the command's resulting mode.  Kickoff Return, Charge!, setup,
        # and other mini-turns can set TurnStarted but are not team turns.
        if turn_mode == "regular":
            for side in started_sides:
                open_turn_side = side

        cleanup_transition = mode_before == "regular" and turn_mode == "setup"
        for report in reports:
            if report.get("reportId") != "turnEnd":
                continue
            if open_turn_side is None:
                synthetic_turn_ends += 1
                continue

            side = open_turn_side
            turn_ends += 1
            turns_by_side[side] += 1
            held = False
            touchdown_player = report.get("playerIdTouchdown")
            if touchdown_player is not None:
                held = player_side.get(str(touchdown_player)) == side
            else:
                holder = (holder_before if cleanup_transition else
                          settled_holder_side(
                              positions, player_side, ball_x, ball_y,
                              ball_in_play, ball_moving))
                held = holder == side
            if held:
                held_ends += 1
                held_by_side[side] += 1
            open_turn_side = None

    return {
        "rules_version": rules_version(game),
        "turn_ends": turn_ends,
        "held_ends": held_ends,
        "synthetic_turn_end_reports": synthetic_turn_ends,
        "turns_by_side": turns_by_side,
        "held_by_side": held_by_side,
    }


def load_replay_ids(path: Path) -> set[int]:
    replay_ids = set()
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            value = raw.split("#", 1)[0].strip()
            if not value:
                continue
            try:
                replay_ids.add(int(value))
            except ValueError as exc:
                raise SystemExit(
                    f"{path}:{lineno}: invalid replay ID {value!r}") from exc
    if not replay_ids:
        raise SystemExit(f"replay-ID allowlist {path} is empty")
    return replay_ids


def replay_id_from_path(path: Path) -> int:
    name = path.name
    if name.startswith("replay_"):
        name = name[len("replay_"):]
    name = name.removesuffix(".json.gz").removesuffix(".json")
    return int(name)


def audit(cache: Path, wanted_rules: str | None = "BB2025",
          replay_ids: set[int] | None = None, sample: int = 0,
          min_turns: int = 4) -> dict[str, Any]:
    if not cache.is_dir():
        raise FileNotFoundError(f"replay cache does not exist: {cache}")
    files = [Path(path) for path in glob.glob(str(cache / "replay_*.json.gz"))]
    if not files:
        raise FileNotFoundError(f"replay cache contains no replay_*.json.gz: {cache}")
    by_id = {}
    for path in files:
        replay_id = replay_id_from_path(path)
        if replay_id in by_id:
            raise ValueError(f"duplicate replay ID {replay_id} in {cache}")
        by_id[replay_id] = path
    if replay_ids is not None:
        missing = sorted(replay_ids - set(by_id))
        if missing:
            preview = ", ".join(str(value) for value in missing[:8])
            suffix = " ..." if len(missing) > 8 else ""
            raise FileNotFoundError(
                f"{len(missing)} allowlisted replay(s) missing from {cache}: "
                f"{preview}{suffix}")
        files = [by_id[replay_id] for replay_id in sorted(replay_ids)]
    else:
        files = [by_id[replay_id] for replay_id in sorted(by_id)]
    if sample:
        files = files[:sample]

    games = turns = held = synthetic = 0
    malformed = short = wrong_rules = 0
    game_rates = []
    for index, path in enumerate(files, 1):
        result = replay_possession(path)
        if result is None:
            if replay_ids is not None:
                raise ValueError(f"malformed allowlisted replay: {path}")
            malformed += 1
            continue
        if wanted_rules is not None and result["rules_version"] != wanted_rules:
            if replay_ids is not None:
                raise ValueError(
                    f"allowlisted replay {path} has rulesVersion "
                    f"{result['rules_version']!r}, expected {wanted_rules!r}")
            wrong_rules += 1
            continue
        if result["turn_ends"] < min_turns:
            short += 1
            continue
        games += 1
        turns += result["turn_ends"]
        held += result["held_ends"]
        synthetic += result["synthetic_turn_end_reports"]
        game_rates.append(result["held_ends"] / result["turn_ends"])
        if index % 500 == 0:
            print(f"  inspected {index}/{len(files)} replays", file=sys.stderr)

    if games == 0:
        raise ValueError(
            f"no qualifying {wanted_rules or 'ALL'} replays with at least "
            f"{min_turns} genuine team turns in {cache}")
    per_game_mean = statistics.fmean(game_rates) if game_rates else None
    per_game_std = statistics.pstdev(game_rates) if len(game_rates) > 1 else None
    return {
        "cache": str(cache),
        "requested_files": len(files),
        "rules_version": wanted_rules or "ALL",
        "games": games,
        "team_turns": turns,
        "held_turn_ends": held,
        "possession_rate_turn_weighted": held / turns if turns else None,
        "possession_rate_per_game_mean": per_game_mean,
        "possession_rate_per_game_std": per_game_std,
        "synthetic_turn_end_reports_excluded": synthetic,
        "malformed_replays": malformed,
        "short_replays_excluded": short,
        "other_rulesets_excluded": wrong_rules,
        "min_turns": min_turns,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--sample", type=int, default=0)
    parser.add_argument("--min-turns", type=int, default=4)
    parser.add_argument(
        "--rules-version", default="BB2025",
        help="embedded rulesVersion to include; use ALL to disable filtering")
    parser.add_argument(
        "--replay-ids", type=Path,
        help="optional exact replay-ID allowlist, one integer per line")
    parser.add_argument("--output", type=Path, help="also write JSON here")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    replay_ids = load_replay_ids(args.replay_ids) if args.replay_ids else None
    wanted_rules = None if args.rules_version.upper() == "ALL" else args.rules_version
    result = audit(
        args.cache, wanted_rules=wanted_rules, replay_ids=replay_ids,
        sample=args.sample, min_turns=args.min_turns)
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
