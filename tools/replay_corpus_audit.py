#!/usr/bin/env python3
"""Audit FUMBBL replay and behavioral-cloning corpus composition.

The replay corpus spans multiple Blood Bowl rulesets. Dates are not a safe
edition proxy: BB2020 and BB2025 games overlap. The authoritative per-game
label is the ``rulesVersion`` entry embedded in each replay's
``game.gameOptions.gameOptionArray``.

This tool joins three immutable artifacts without loading BBP record bodies:

* replay-cache ``manifest.json`` for match metadata;
* ``replay_<id>.json.gz`` for the exact rules version;
* ``<id>.bbp`` shards for observation version, byte size, and record count.

It prints aggregate JSON only; coach and team names are never emitted. Use
``--write-bb2025-ids`` to create an exact replay-id allowlist for downstream
BC/baseline/state-bank jobs.
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import re
import struct
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


BBP_HEADER = struct.Struct("<4sIII")
BBP_MAGIC = b"BBP1"
BBP_KNOWN_VERSIONS = (1, 2, 3)
RULES_RE = re.compile(
    rb'"gameOptionId"\s*:\s*"rulesVersion"\s*,\s*'
    rb'"gameOptionValue"\s*:\s*"([^"]+)"'
)


def load_manifest(path: Path) -> dict[int, dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        raw = json.load(f)
    by_replay: dict[int, dict[str, Any]] = {}
    for match in raw.values():
        replay_id = match.get("replayId")
        if replay_id is None:
            continue
        replay_id = int(replay_id)
        if replay_id in by_replay:
            raise ValueError(f"duplicate replayId {replay_id} in {path}")
        by_replay[replay_id] = match
    return by_replay


def extract_rules_version(path: Path) -> str:
    """Return the replay's exact rulesVersion, or ``UNKNOWN`` when absent."""
    with gzip.open(path, "rb") as f:
        payload = f.read()
    match = RULES_RE.search(payload)
    if match:
        return match.group(1).decode("utf-8", errors="replace")

    # Defensive fallback if FFB changes option ordering/serialization.
    replay = json.loads(payload)
    options = (
        replay.get("game", {})
        .get("gameOptions", {})
        .get("gameOptionArray", [])
    )
    for option in options:
        if option.get("gameOptionId") == "rulesVersion":
            return str(option.get("gameOptionValue", "UNKNOWN"))
    return "UNKNOWN"


def inspect_bbp(path: Path) -> dict[str, int]:
    size = path.stat().st_size
    if size < BBP_HEADER.size:
        raise ValueError(f"{path}: truncated BBP header ({size} bytes)")
    with path.open("rb") as f:
        magic, version, obs_size, mask_size = BBP_HEADER.unpack(f.read(16))
    if magic != BBP_MAGIC:
        raise ValueError(f"{path}: bad BBP magic {magic!r}")
    if version not in BBP_KNOWN_VERSIONS:
        raise ValueError(f"{path}: unsupported BBP version {version}")
    record_size = 12 + obs_size + mask_size + 4
    body_size = size - BBP_HEADER.size
    if record_size <= 0 or body_size % record_size:
        raise ValueError(
            f"{path}: {body_size} body bytes not divisible by "
            f"record size {record_size}"
        )
    return {
        "version": version,
        "obs_size": obs_size,
        "mask_size": mask_size,
        "bytes": size,
        "records": body_size // record_size,
    }


def _counter_dict(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items(), key=lambda item: (-item[1], item[0])))


def _version_summary() -> dict[str, Any]:
    return {
        "manifest_games": 0,
        "paired_games": 0,
        "zero_record_pair_shards": 0,
        "pair_records": 0,
        "pair_bytes": 0,
        "date_min": None,
        "date_max": None,
        "scored_games": 0,
        "draws": 0,
        "score_sum": 0,
        "team_sides": 0,
        "races": Counter(),
        "coach_brackets": Counter(),
    }


def audit(manifest_path: Path, replay_cache: Path, pairs_dir: Path,
          bb2025_ids_path: Path | None = None) -> dict[str, Any]:
    if not replay_cache.is_dir():
        raise FileNotFoundError(f"replay-cache directory does not exist: {replay_cache}")
    if not pairs_dir.is_dir():
        raise FileNotFoundError(f"pairs directory does not exist: {pairs_dir}")
    manifest = load_manifest(manifest_path)

    rules_by_id: dict[int, str] = {}
    missing_replay_files: list[int] = []
    for replay_id in sorted(manifest):
        replay_path = replay_cache / f"replay_{replay_id}.json.gz"
        if replay_path.is_file():
            rules_by_id[replay_id] = extract_rules_version(replay_path)
        else:
            rules_by_id[replay_id] = "MISSING_REPLAY"
            missing_replay_files.append(replay_id)

    pairs: dict[int, dict[str, int]] = {}
    header_counts: Counter[str] = Counter()
    malformed_pairs: dict[str, str] = {}
    pair_paths = sorted(pairs_dir.glob("*.bbp"))
    if not pair_paths:
        raise FileNotFoundError(f"pairs directory contains no .bbp shards: {pairs_dir}")
    for path in pair_paths:
        try:
            replay_id = int(path.stem)
            info = inspect_bbp(path)
        except (ValueError, OSError) as exc:
            malformed_pairs[path.name] = str(exc)
            continue
        if replay_id in pairs:
            raise ValueError(
                f"duplicate pair shards normalize to replay ID {replay_id}: "
                f"{path.name} and another filename")
        pairs[replay_id] = info
        header = f"v{info['version']}/obs{info['obs_size']}/mask{info['mask_size']}"
        header_counts[header] += 1

    summaries: defaultdict[str, dict[str, Any]] = defaultdict(_version_summary)
    for replay_id, match in manifest.items():
        version = rules_by_id[replay_id]
        summary = summaries[version]
        summary["manifest_games"] += 1
        date = match.get("date")
        if date:
            if summary["date_min"] is None or date < summary["date_min"]:
                summary["date_min"] = date
            if summary["date_max"] is None or date > summary["date_max"]:
                summary["date_max"] = date
        team1, team2 = match.get("team1", {}), match.get("team2", {})
        score1, score2 = team1.get("score"), team2.get("score")
        if isinstance(score1, (int, float)) and isinstance(score2, (int, float)):
            summary["scored_games"] += 1
            summary["score_sum"] += score1 + score2
            summary["draws"] += int(score1 == score2)
        for team in (team1, team2):
            summary["team_sides"] += 1
            summary["races"][str(team.get("race") or "UNKNOWN")] += 1
            summary["coach_brackets"][str(team.get("bracket") or "UNKNOWN")] += 1
        if replay_id in pairs:
            info = pairs[replay_id]
            summary["paired_games"] += 1
            summary["zero_record_pair_shards"] += int(info["records"] == 0)
            summary["pair_records"] += info["records"]
            summary["pair_bytes"] += info["bytes"]

    serial_summaries: dict[str, Any] = {}
    for version, summary in sorted(summaries.items()):
        games = summary["manifest_games"]
        scored_games = summary["scored_games"]
        serial_summaries[version] = {
            "manifest_games": games,
            "paired_games": summary["paired_games"],
            "zero_record_pair_shards": summary["zero_record_pair_shards"],
            "pair_records": summary["pair_records"],
            "pair_bytes": summary["pair_bytes"],
            "date_min": summary["date_min"],
            "date_max": summary["date_max"],
            "scored_games": scored_games,
            "draws": summary["draws"],
            "draw_rate": (summary["draws"] / scored_games
                          if scored_games else None),
            "mean_total_score": (summary["score_sum"] / scored_games
                                 if scored_games else None),
            "team_sides": summary["team_sides"],
            "races": _counter_dict(summary["races"]),
            "coach_brackets": _counter_dict(summary["coach_brackets"]),
        }

    paired_ids = set(pairs)
    manifest_ids = set(manifest)
    if bb2025_ids_path is not None:
        if missing_replay_files or malformed_pairs:
            raise ValueError(
                "refusing to write training allowlist from an incomplete "
                f"audit: {len(missing_replay_files)} missing replay file(s), "
                f"{len(malformed_pairs)} malformed pair shard(s)")
        ids = sorted(
            replay_id for replay_id in paired_ids & manifest_ids
            if rules_by_id[replay_id] == "BB2025" and
            pairs[replay_id]["records"] > 0
        )
        if not ids:
            raise ValueError("training allowlist would be empty")
        bb2025_ids_path.parent.mkdir(parents=True, exist_ok=True)
        bb2025_ids_path.write_text(
            "".join(f"{replay_id}\n" for replay_id in ids), encoding="utf-8"
        )
    total_records = sum(info["records"] for info in pairs.values())
    total_pair_bytes = sum(info["bytes"] for info in pairs.values())
    return {
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "inputs": {
            "manifest": str(manifest_path),
            "replay_cache": str(replay_cache),
            "pairs_dir": str(pairs_dir),
        },
        "manifest_games": len(manifest),
        "replay_files_found": len(manifest) - len(missing_replay_files),
        "pair_shards": len(pairs),
        "zero_record_pair_shards": sum(
            info["records"] == 0 for info in pairs.values()),
        "pair_records": total_records,
        "pair_bytes": total_pair_bytes,
        "pair_headers": _counter_dict(header_counts),
        "pair_ids_missing_manifest": sorted(paired_ids - manifest_ids),
        "manifest_ids_missing_pairs": sorted(manifest_ids - paired_ids),
        "missing_replay_files": missing_replay_files,
        "malformed_pair_shards": malformed_pairs,
        "rules_versions": serial_summaries,
    }


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--manifest",
        type=Path,
        default=root / "validation" / "replay_cache" / "manifest.json",
    )
    ap.add_argument(
        "--replay-cache",
        type=Path,
        default=root / "validation" / "replay_cache",
    )
    ap.add_argument(
        "--pairs-dir", type=Path, default=root / "validation" / "pairs"
    )
    ap.add_argument("--output", type=Path, help="also write aggregate JSON here")
    ap.add_argument(
        "--write-bb2025-ids",
        type=Path,
        help="write exact BB2025 replay IDs that also have valid BBP shards",
    )
    return ap.parse_args()


def main() -> int:
    args = parse_args()
    result = audit(
        args.manifest, args.replay_cache, args.pairs_dir,
        bb2025_ids_path=args.write_bb2025_ids,
    )
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
