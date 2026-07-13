#!/usr/bin/env python3
"""Stream and audit a Blood Bowl behavioral-pair (BBP) corpus.

The lockstep exporter writes one ``<replay_id>.bbp`` shard per replay.  This
tool validates the artifact contract while keeping memory bounded to one
chunk of one shard plus small per-replay summaries.  It never loads the full
corpus, observations, or masks into memory.

Validated invariants:

* the 16-byte ``BBP1`` header and supported v1/v2 format version;
* body size is an exact multiple of the header-derived record size;
* every record's replay ID matches its numeric shard filename;
* agent and action targets are in range; and
* the selected type, argument, and square are legal in the stored mask.

The observation layout used by all supported Blood Bowl pair lineages keeps
``half``, egocentric ``my turn``, and ``opponent turn`` at offsets 784..786.
The JSON report includes corpus/action/turn counts, action replay coverage,
and exact per-replay prefix depth.  Use ``--replay-ids`` for an exact
allowlist; a requested-but-missing shard is an error rather than a silent
partial audit.

Examples:

  python3 tools/bbp_behavior_audit.py --pairs-dir validation/pairs_v4
  python3 tools/bbp_behavior_audit.py \
      --pairs-dir /data/pairs_v4 --replay-ids /data/bb2025.ids
"""

from __future__ import annotations

import argparse
import json
import math
import struct
from collections import Counter
from pathlib import Path
from typing import Any, Iterable


BBP_HEADER = struct.Struct("<4sIII")
BBP_MAGIC = b"BBP1"
BBP_KNOWN_VERSIONS = (1, 2)
BBP_HEADER_SIZE = BBP_HEADER.size

HEAD_TYPE = 30
HEAD_ARG = 33
HEAD_SQUARE = 391
MASK_SIZE = HEAD_TYPE + HEAD_ARG + HEAD_SQUARE

RECORD_META_SIZE = 12  # replay u32, cmd u32, agent u8, pad[3]
RECORD_TARGET_SIZE = 4  # type u8, arg u8, square u16
OBS_HALF = 784
OBS_MY_TURN = 785
OBS_OPP_TURN = 786
MIN_OBS_SIZE = OBS_OPP_TURN + 1

ACTION_NAMES = (
    "NONE",
    "SETUP_PLACE",
    "SETUP_REMOVE",
    "SETUP_DONE",
    "KICK_TARGET",
    "TOUCHBACK",
    "ACTIVATE",
    "DECLARE",
    "END_TURN",
    "STEP",
    "STAND_UP",
    "JUMP",
    "BLOCK_TARGET",
    "PASS_TARGET",
    "HANDOFF_TARGET",
    "FOUL_TARGET",
    "TTM_TARGET",
    "SECURE_BALL",
    "PICKUP_DECLINE",
    "END_ACTIVATION",
    "CHOOSE_DIE",
    "PUSH_SQUARE",
    "FOLLOW_UP",
    "USE_REROLL",
    "DECLINE_REROLL",
    "USE_SKILL",
    "DECLINE_SKILL",
    "APOTHECARY",
    "CHOOSE_OPTION",
    "SPECIAL_TARGET",
)

if len(ACTION_NAMES) != HEAD_TYPE:
    raise AssertionError("action-name table is out of sync with the type head")


def load_replay_ids(path: Path) -> frozenset[int]:
    """Load an exact replay-ID allowlist, accepting blank/commented lines."""
    replay_ids: set[int] = set()
    try:
        with path.open(encoding="utf-8") as f:
            for lineno, raw in enumerate(f, 1):
                value = raw.split("#", 1)[0].strip()
                if not value:
                    continue
                try:
                    replay_id = int(value)
                except ValueError as exc:
                    raise ValueError(
                        f"{path}:{lineno}: invalid replay ID {value!r}"
                    ) from exc
                if replay_id < 0:
                    raise ValueError(
                        f"{path}:{lineno}: replay ID must be non-negative"
                    )
                replay_ids.add(replay_id)
    except OSError as exc:
        raise OSError(f"cannot read replay-ID allowlist {path}: {exc}") from exc
    if not replay_ids:
        raise ValueError(f"replay-ID allowlist is empty: {path}")
    return frozenset(replay_ids)


def _numeric_shard_index(pairs_dir: Path) -> dict[int, Path]:
    if not pairs_dir.is_dir():
        raise FileNotFoundError(f"pairs directory does not exist: {pairs_dir}")
    paths = sorted(pairs_dir.glob("*.bbp"))
    if not paths:
        raise FileNotFoundError(
            f"pairs directory contains no .bbp shards: {pairs_dir}"
        )
    by_id: dict[int, Path] = {}
    for path in paths:
        try:
            replay_id = int(path.stem)
        except ValueError as exc:
            raise ValueError(
                f"{path}: .bbp shard filename must be a numeric replay ID"
            ) from exc
        if replay_id < 0:
            raise ValueError(f"{path}: replay ID must be non-negative")
        if replay_id in by_id:
            raise ValueError(
                "duplicate pair shards normalize to replay ID "
                f"{replay_id}: {by_id[replay_id].name} and {path.name}"
            )
        by_id[replay_id] = path
    return by_id


def _selected_paths(
    pairs_dir: Path, replay_ids: Iterable[int] | None
) -> list[tuple[int, Path]]:
    by_id = _numeric_shard_index(pairs_dir)
    if replay_ids is None:
        selected = sorted(by_id)
    else:
        requested = frozenset(int(replay_id) for replay_id in replay_ids)
        if not requested:
            raise ValueError("replay-ID filter is empty")
        if min(requested) < 0:
            raise ValueError("replay-ID filter contains a negative ID")
        missing = sorted(requested - set(by_id))
        if missing:
            preview = ", ".join(str(value) for value in missing[:8])
            suffix = " ..." if len(missing) > 8 else ""
            raise FileNotFoundError(
                f"missing {len(missing)} requested replay shard(s) in "
                f"{pairs_dir}: {preview}{suffix}"
            )
        selected = sorted(requested)
    return [(replay_id, by_id[replay_id]) for replay_id in selected]


def _linear_quantile(sorted_values: list[int], quantile: float) -> float | int:
    if not sorted_values:
        raise ValueError("cannot take a quantile of an empty sequence")
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = quantile * (len(sorted_values) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return sorted_values[lower]
    weight = position - lower
    return sorted_values[lower] * (1.0 - weight) + sorted_values[upper] * weight


def _numeric_summary(values: Iterable[int]) -> dict[str, Any]:
    ordered = sorted(int(value) for value in values)
    if not ordered:
        return {"count": 0, "sum": 0, "mean": None, "quantiles": {}}
    quantiles = {}
    for label, q in (
        ("min", 0.0),
        ("p10", 0.10),
        ("p25", 0.25),
        ("p50", 0.50),
        ("p75", 0.75),
        ("p90", 0.90),
        ("p95", 0.95),
        ("p99", 0.99),
        ("max", 1.0),
    ):
        quantiles[label] = _linear_quantile(ordered, q)
    total = sum(ordered)
    return {
        "count": len(ordered),
        "sum": total,
        "mean": total / len(ordered),
        "quantiles": quantiles,
    }


def _count_dict(counter: Counter[int]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


def _inspect_shard(
    path: Path,
    expected_replay_id: int,
    chunk_records: int,
) -> dict[str, Any]:
    size = path.stat().st_size
    if size < BBP_HEADER_SIZE:
        raise ValueError(f"{path}: truncated BBP header ({size} bytes)")
    with path.open("rb") as f:
        header = f.read(BBP_HEADER_SIZE)
        if len(header) != BBP_HEADER_SIZE:
            raise ValueError(f"{path}: truncated BBP header")
        magic, version, obs_size, mask_size = BBP_HEADER.unpack(header)
        if magic != BBP_MAGIC:
            raise ValueError(f"{path}: bad BBP magic {magic!r}")
        if version not in BBP_KNOWN_VERSIONS:
            raise ValueError(f"{path}: unsupported BBP version {version}")
        if obs_size < MIN_OBS_SIZE:
            raise ValueError(
                f"{path}: observation size {obs_size} is too small for "
                f"half/turn offsets (need at least {MIN_OBS_SIZE})"
            )
        if mask_size != MASK_SIZE:
            raise ValueError(
                f"{path}: mask size {mask_size} does not match Blood Bowl "
                f"action heads ({MASK_SIZE})"
            )

        record_size = RECORD_META_SIZE + obs_size + mask_size + RECORD_TARGET_SIZE
        body_size = size - BBP_HEADER_SIZE
        if body_size % record_size:
            raise ValueError(
                f"{path}: body {body_size}B is not divisible by record "
                f"size {record_size}"
            )
        records = body_size // record_size
        result: dict[str, Any] = {
            "records": records,
            "bytes": size,
            "version": version,
            "obs_size": obs_size,
            "mask_size": mask_size,
            "agent_counts": Counter(),
            "half_counts": Counter(),
            "turn_counts": Counter(),
            "opp_turn_counts": Counter(),
            "half_turn_counts": Counter(),
            "action_counts": Counter(),
            "action_half_counts": [Counter() for _ in range(HEAD_TYPE)],
            "action_turn_counts": [Counter() for _ in range(HEAD_TYPE)],
            "actions_seen": set(),
            "min_cmd": None,
            "max_cmd": None,
            "max_half": None,
            "max_turn": None,
            "max_match_turn": None,
        }
        if records == 0:
            return result

        mask_offset = RECORD_META_SIZE + obs_size
        target_offset = mask_offset + mask_size
        record_index = 0
        while record_index < records:
            take = min(chunk_records, records - record_index)
            expected_bytes = take * record_size
            payload = f.read(expected_bytes)
            if len(payload) != expected_bytes:
                raise ValueError(
                    f"{path}: truncated while reading record {record_index}; "
                    f"wanted {expected_bytes}B, got {len(payload)}B"
                )
            view = memoryview(payload)
            for local_index in range(take):
                index = record_index + local_index
                base = local_index * record_size
                replay_id, cmd = struct.unpack_from("<II", view, base)
                agent = view[base + 8]
                if replay_id != expected_replay_id:
                    raise ValueError(
                        f"{path} record {index}: replay ID {replay_id} does "
                        f"not match shard filename {expected_replay_id}"
                    )
                if agent >= 2:
                    raise ValueError(
                        f"{path} record {index}: agent {agent} is out of range"
                    )

                obs_base = base + RECORD_META_SIZE
                half = view[obs_base + OBS_HALF]
                turn = view[obs_base + OBS_MY_TURN]
                opp_turn = view[obs_base + OBS_OPP_TURN]

                target_base = base + target_offset
                action_type = view[target_base]
                action_arg = view[target_base + 1]
                (action_square,) = struct.unpack_from("<H", view, target_base + 2)
                if not (
                    action_type < HEAD_TYPE
                    and action_arg < HEAD_ARG
                    and action_square < HEAD_SQUARE
                ):
                    raise ValueError(
                        f"{path} record {index}: target out of head range "
                        f"(type={action_type}, arg={action_arg}, "
                        f"square={action_square})"
                    )

                mask_base = base + mask_offset
                selected = (
                    view[mask_base + action_type],
                    view[mask_base + HEAD_TYPE + action_arg],
                    view[mask_base + HEAD_TYPE + HEAD_ARG + action_square],
                )
                if not all(selected):
                    raise ValueError(
                        f"{path} record {index}: selected target is not legal "
                        f"in stored mask (type/arg/square bits={selected})"
                    )

                result["agent_counts"][agent] += 1
                result["half_counts"][half] += 1
                result["turn_counts"][turn] += 1
                result["opp_turn_counts"][opp_turn] += 1
                result["half_turn_counts"][(half, turn)] += 1
                result["action_counts"][action_type] += 1
                result["action_half_counts"][action_type][half] += 1
                result["action_turn_counts"][action_type][turn] += 1
                result["actions_seen"].add(action_type)

                result["min_cmd"] = (
                    cmd if result["min_cmd"] is None else min(result["min_cmd"], cmd)
                )
                result["max_cmd"] = (
                    cmd if result["max_cmd"] is None else max(result["max_cmd"], cmd)
                )
                result["max_half"] = (
                    half
                    if result["max_half"] is None
                    else max(result["max_half"], half)
                )
                result["max_turn"] = (
                    turn
                    if result["max_turn"] is None
                    else max(result["max_turn"], turn)
                )
                match_turn = (half - 1) * 8 + turn if half >= 1 else turn
                result["max_match_turn"] = (
                    match_turn
                    if result["max_match_turn"] is None
                    else max(result["max_match_turn"], match_turn)
                )
            record_index += take

        if f.read(1):
            raise ValueError(f"{path}: unread trailing bytes after final record")
    return result


def audit(
    pairs_dir: Path,
    replay_ids: Iterable[int] | None = None,
    chunk_records: int = 512,
) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable streaming corpus audit."""
    if chunk_records <= 0:
        raise ValueError("chunk_records must be positive")
    selected = _selected_paths(pairs_dir, replay_ids)

    header_counts: Counter[str] = Counter()
    agent_counts: Counter[int] = Counter()
    half_counts: Counter[int] = Counter()
    turn_counts: Counter[int] = Counter()
    opp_turn_counts: Counter[int] = Counter()
    half_turn_counts: Counter[tuple[int, int]] = Counter()
    action_counts: Counter[int] = Counter()
    action_half_counts = [Counter() for _ in range(HEAD_TYPE)]
    action_turn_counts = [Counter() for _ in range(HEAD_TYPE)]
    action_replay_coverage: Counter[int] = Counter()
    replays: dict[str, dict[str, Any]] = {}
    total_records = total_bytes = zero_shards = 0

    for replay_id, path in selected:
        shard = _inspect_shard(path, replay_id, chunk_records)
        records = shard["records"]
        total_records += records
        total_bytes += shard["bytes"]
        zero_shards += int(records == 0)
        header_key = (
            f"v{shard['version']}/obs{shard['obs_size']}/"
            f"mask{shard['mask_size']}"
        )
        header_counts[header_key] += 1
        agent_counts.update(shard["agent_counts"])
        half_counts.update(shard["half_counts"])
        turn_counts.update(shard["turn_counts"])
        opp_turn_counts.update(shard["opp_turn_counts"])
        half_turn_counts.update(shard["half_turn_counts"])
        action_counts.update(shard["action_counts"])
        for action_type in range(HEAD_TYPE):
            action_half_counts[action_type].update(
                shard["action_half_counts"][action_type]
            )
            action_turn_counts[action_type].update(
                shard["action_turn_counts"][action_type]
            )
        for action_type in shard["actions_seen"]:
            action_replay_coverage[action_type] += 1

        command_span = (
            None
            if shard["min_cmd"] is None
            else shard["max_cmd"] - shard["min_cmd"]
        )
        replays[str(replay_id)] = {
            "records": records,
            "bytes": shard["bytes"],
            "header": header_key,
            "min_cmd": shard["min_cmd"],
            "max_cmd": shard["max_cmd"],
            "command_span": command_span,
            "max_half": shard["max_half"],
            "max_turn": shard["max_turn"],
            "max_match_turn": shard["max_match_turn"],
        }

    shard_count = len(selected)
    actions: dict[str, Any] = {}
    for action_type, name in enumerate(ACTION_NAMES):
        count = action_counts[action_type]
        coverage = action_replay_coverage[action_type]
        actions[name] = {
            "id": action_type,
            "records": count,
            "record_fraction": count / total_records if total_records else 0.0,
            "replay_coverage": coverage,
            "replay_coverage_fraction": coverage / shard_count if shard_count else 0.0,
            "half_counts": _count_dict(action_half_counts[action_type]),
            "turn_counts": _count_dict(action_turn_counts[action_type]),
        }

    max_half_counts: Counter[int] = Counter()
    max_turn_counts: Counter[int] = Counter()
    max_match_turn_counts: Counter[int] = Counter()
    record_depths = []
    command_spans = []
    for replay in replays.values():
        record_depths.append(replay["records"])
        if replay["command_span"] is not None:
            command_spans.append(replay["command_span"])
        if replay["max_half"] is not None:
            max_half_counts[replay["max_half"]] += 1
            max_turn_counts[replay["max_turn"]] += 1
            max_match_turn_counts[replay["max_match_turn"]] += 1

    max_observed_half = max(max_half_counts, default=0)
    max_observed_turn = max(max_turn_counts, default=-1)
    depth = {
        "records_per_replay": _numeric_summary(record_depths),
        "command_span_nonzero_replays": _numeric_summary(command_spans),
        "max_half_counts_nonzero_replays": _count_dict(max_half_counts),
        "max_turn_counts_nonzero_replays": _count_dict(max_turn_counts),
        "max_match_turn_counts_nonzero_replays": _count_dict(max_match_turn_counts),
        "replays_reaching_half": {
            str(half): sum(
                count for observed, count in max_half_counts.items() if observed >= half
            )
            for half in range(1, max_observed_half + 1)
        },
        "replays_reaching_turn": {
            str(turn): sum(
                count for observed, count in max_turn_counts.items() if observed >= turn
            )
            for turn in range(0, max_observed_turn + 1)
        },
    }

    return {
        "schema_version": 1,
        "inputs": {
            "pairs_dir": str(pairs_dir),
            "exact_replay_filter": replay_ids is not None,
            "requested_replays": shard_count,
            "chunk_records": chunk_records,
        },
        "shards": shard_count,
        "zero_shards": zero_shards,
        "records": total_records,
        "bytes": total_bytes,
        "headers": {key: header_counts[key] for key in sorted(header_counts)},
        "agent_counts": _count_dict(agent_counts),
        "half_counts": _count_dict(half_counts),
        "turn_counts": _count_dict(turn_counts),
        "opponent_turn_counts": _count_dict(opp_turn_counts),
        "half_turn_counts": {
            f"half={half}/turn={turn}": half_turn_counts[(half, turn)]
            for half, turn in sorted(half_turn_counts)
        },
        "actions": actions,
        "depth": depth,
        "replays": replays,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pairs-dir",
        type=Path,
        default=root / "validation" / "pairs",
        help="directory containing numeric <replay_id>.bbp shards",
    )
    parser.add_argument(
        "--replay-ids",
        type=Path,
        help="exact replay-ID allowlist (one integer per line)",
    )
    parser.add_argument(
        "--chunk-records",
        type=int,
        default=512,
        help="records read per chunk from one shard (default: 512)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        replay_ids = load_replay_ids(args.replay_ids) if args.replay_ids else None
        result = audit(
            args.pairs_dir,
            replay_ids=replay_ids,
            chunk_records=args.chunk_records,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"bbp_behavior_audit: {exc}") from exc
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
