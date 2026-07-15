#!/usr/bin/env python3
"""Build a provenance-pinned S1-S6 coverage report from a BBS1 state bank.

The C scanner owns engine-state validation and classification. This layer owns
hash pinning, deterministic aggregation, invariant checks, and transactional
publication. The records JSONL and report are fsynced before the manifest is
published as the final commit marker. Existing destinations are never replaced.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence


SHA256_RE = re.compile(r"[0-9a-f]{64}")
PRIMARY_BUCKETS = ("s1", "s2", "s3", "s4", "s5", "s6")
TURN_BANDS = (("1-2", 1, 2), ("3-4", 3, 4), ("5-8", 5, 8))
DEFAULT_SPLIT_KEY = "bb2025-strict-scenarios-v1"
DEFAULT_CAP = 3
CANONICAL_TURN_HISTOGRAM = {
    1: 8026,
    2: 3975,
    3: 1798,
    4: 857,
    5: 395,
    6: 185,
    7: 87,
    8: 25,
}
CANONICAL_BALL_STATE_HISTOGRAM = {1: 5312, 2: 10036}
APPROXIMATION_REGISTER = (
    "derived-pre-negatrait",
    "reach-no-jump",
    "contest-static-next-turn",
    "pickup-components-not-target-number",
    "s3-opportunity-only",
    "geometric-score-horizon",
    "s6-fixed-direct-blocks",
    "s6-one-move-zero-roll-only",
    "opening-censored",
)


class ScenarioCoverageError(RuntimeError):
    """A fail-closed scenario coverage or provenance-contract violation."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_expected_sha(value: str, label: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise ScenarioCoverageError(
            f"{label} expected SHA-256 is not lowercase hex"
        )


def _histogram(values: Iterable[int]) -> dict[str, int]:
    counts = Counter(values)
    return {str(key): counts[key] for key in sorted(counts)}


def _metric(rows: Sequence[Mapping[str, int]], cap: int) -> dict[str, int]:
    per_replay = Counter(row["replay_id"] for row in rows)
    return {
        "capped_records": sum(min(count, cap) for count in per_replay.values()),
        "records": len(rows),
        "replays": len(per_replay),
    }


def _turn_band(turn: int) -> str:
    for name, first, last in TURN_BANDS:
        if first <= turn <= last:
            return name
    raise ScenarioCoverageError(f"turn out of report range: {turn}")


def _split_for_replay(replay_id: int, split_key: str) -> str:
    digest = hashlib.sha256(f"{split_key}:{replay_id}".encode("ascii")).digest()
    draw = int.from_bytes(digest[:8], "big") % 10_000
    if draw < 7000:
        return "train"
    if draw < 8500:
        return "validation"
    return "test"


def _flag_definitions() -> dict[str, Callable[[Mapping[str, int]], bool]]:
    return {
        "s1": lambda row: row["s1"] == 1,
        "s1_sure_hands": lambda row: row["s1"] == 1
        and row["s1_has_sure_hands"] == 1,
        "s1_ball_tackle_zones": lambda row: row["s1"] == 1
        and row["s1_ball_tackle_zones"] > 0,
        "s2": lambda row: row["s2"] == 1,
        "s2_zero_roll_contest": lambda row: row["s2"] == 1
        and row["s2_cheapest_dodges"] == 0
        and row["s2_cheapest_gfis"] == 0,
        "s2_roll_required": lambda row: row["s2"] == 1
        and row["s2_cheapest_dodges"] + row["s2_cheapest_gfis"] > 0,
        "s3": lambda row: row["s3"] == 1,
        "s3_pickup_risk": lambda row: row["s3"] == 1
        and bool(row["s3_risk_mask"] & 4),
        "s3_block_risk": lambda row: row["s3"] == 1
        and bool(row["s3_risk_mask"] & 1),
        "s3_dodge_risk": lambda row: row["s3"] == 1
        and bool(row["s3_risk_mask"] & 2),
        "s4": lambda row: row["s4"] == 1,
        "s4_full": lambda row: row["s4_full"] == 1,
        "s4_soft": lambda row: row["s4_soft"] == 1,
        "s4_r6v1_full": lambda row: row["s4_r6v1_full"] == 1,
        "s4_r6v1_soft": lambda row: row["s4_r6v1_soft"] == 1,
        "s5": lambda row: row["s5"] == 1,
        "s5_horizon_1": lambda row: row["s5"] == 1
        and row["s5_horizon"] == 1,
        "s5_horizon_2": lambda row: row["s5"] == 1
        and row["s5_horizon"] == 2,
        "s6a": lambda row: row["s6a"] == 1,
        "s6b": lambda row: row["s6b"] == 1,
        "s6_dynamic_blocks": lambda row: row["s6_dynamic_blocks"] > 0,
        "s6": lambda row: row["s6"] == 1,
        "none": lambda row: not any(row[name] == 1 for name in PRIMARY_BUCKETS),
    }


REQUIRED_INTEGER_FIELDS = (
    "active_team",
    "ball_state",
    "command",
    "eligible_players",
    "half",
    "record_index",
    "replay_id",
    "s1",
    "s1_ball_tackle_zones",
    "s1_cheapest_dodges",
    "s1_cheapest_gfis",
    "s1_has_sure_hands",
    "s1_recoverers",
    "s2",
    "s2_cheapest_dodges",
    "s2_cheapest_gfis",
    "s2_opponent_reachers",
    "s3",
    "s3_risk_mask",
    "s3_zero_roll_players",
    "s4",
    "s4_full",
    "s4_r6v1_full",
    "s4_r6v1_soft",
    "s4_soft",
    "s5",
    "s5_carrier_marked",
    "s5_horizon",
    "s5_team_threats_1turn",
    "s5_team_threats_2turn",
    "s6",
    "s6_class_changing_moves",
    "s6_dynamic_blocks",
    "s6_fixed_class_mask",
    "s6a",
    "s6b",
    "team_id_0",
    "team_id_1",
    "turn",
    "weather",
)
BOOLEAN_FIELDS = (
    "s1",
    "s1_has_sure_hands",
    "s2",
    "s3",
    "s4",
    "s4_full",
    "s4_r6v1_full",
    "s4_r6v1_soft",
    "s4_soft",
    "s5",
    "s5_carrier_marked",
    "s6",
    "s6a",
    "s6b",
)


def _validate_rows(rows: Sequence[Mapping[str, int]]) -> None:
    if not rows:
        raise ScenarioCoverageError("scanner produced no records")
    for expected_index, row in enumerate(rows):
        missing = [field for field in REQUIRED_INTEGER_FIELDS if field not in row]
        if missing:
            raise ScenarioCoverageError(
                f"scanner record {expected_index} missing fields: {missing}"
            )
        for field in REQUIRED_INTEGER_FIELDS:
            value = row[field]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ScenarioCoverageError(
                    f"scanner record {expected_index} field {field} is not an integer"
                )
        if row["record_index"] != expected_index:
            raise ScenarioCoverageError(
                f"record index mismatch at {expected_index}: "
                f"{row['record_index']}"
            )
        if row["replay_id"] <= 0:
            raise ScenarioCoverageError(
                f"nonpositive replay ID at record {expected_index}"
            )
        if row["half"] <= 0 or not 1 <= row["turn"] <= 8:
            raise ScenarioCoverageError(
                f"half/turn out of range at record {expected_index}"
            )
        for field in BOOLEAN_FIELDS:
            if row[field] not in (0, 1):
                raise ScenarioCoverageError(
                    f"scanner record {expected_index} field {field} is not 0/1"
                )
        if row["s2"] and not row["s1"]:
            raise ScenarioCoverageError(f"S2 without S1 at record {expected_index}")
        if row["s4"] and row["s5"]:
            raise ScenarioCoverageError(
                f"S4 and S5 overlap at record {expected_index}"
            )
        if row["s6"] != int(bool(row["s6a"] or row["s6b"])):
            raise ScenarioCoverageError(
                f"S6 union mismatch at record {expected_index}"
            )


def summarize_rows(
    rows: Sequence[Mapping[str, int]],
    *,
    split_key: str = DEFAULT_SPLIT_KEY,
    cap: int = DEFAULT_CAP,
) -> dict[str, Any]:
    """Validate scanner rows and return deterministic descriptive coverage."""
    if not split_key or not split_key.isascii():
        raise ScenarioCoverageError("split key must be nonempty ASCII")
    if cap <= 0:
        raise ScenarioCoverageError("per-replay cap must be positive")
    _validate_rows(rows)
    definitions = _flag_definitions()
    row_list = list(rows)

    turn_bands: dict[str, dict[str, int]] = {}
    for name, _first, _last in TURN_BANDS:
        selected = [row for row in row_list if _turn_band(row["turn"]) == name]
        turn_bands[name] = _metric(selected, cap)

    coverage: dict[str, Any] = {}
    for name, predicate in definitions.items():
        selected = [row for row in row_list if predicate(row)]
        coverage[name] = {
            "overall": _metric(selected, cap),
            "turn_bands": {
                band: _metric(
                    [row for row in selected if _turn_band(row["turn"]) == band],
                    cap,
                )
                for band, _first, _last in TURN_BANDS
            },
        }

    pairwise: dict[str, dict[str, int]] = {}
    for left, right in itertools.combinations(PRIMARY_BUCKETS, 2):
        selected = [
            row for row in row_list if row[left] == 1 and row[right] == 1
        ]
        pairwise[f"{left}&{right}"] = _metric(selected, cap)

    splits: dict[str, Any] = {}
    for split in ("train", "validation", "test"):
        replay_ids = sorted(
            {
                row["replay_id"]
                for row in row_list
                if _split_for_replay(row["replay_id"], split_key) == split
            }
        )
        replay_set = set(replay_ids)
        selected = [row for row in row_list if row["replay_id"] in replay_set]
        splits[split] = {
            **_metric(selected, cap),
            "coverage": {
                name: _metric([row for row in selected if predicate(row)], cap)
                for name, predicate in definitions.items()
            },
            "replay_id_values": replay_ids,
        }

    race_pairs: dict[str, Any] = {}
    pairs = sorted(
        {
            tuple(sorted((row["team_id_0"], row["team_id_1"])))
            for row in row_list
        }
    )
    for first, second in pairs:
        selected = [
            row
            for row in row_list
            if tuple(sorted((row["team_id_0"], row["team_id_1"])))
            == (first, second)
        ]
        race_pairs[f"{first}-{second}"] = {
            **_metric(selected, cap),
            "coverage": {
                name: _metric(
                    [row for row in selected if definitions[name](row)], cap
                )
                for name in PRIMARY_BUCKETS
            },
        }

    return {
        "schema_version": 1,
        "anomalies": {
            "nonsequential_record_index": 0,
            "s2_without_s1": 0,
            "s4_and_s5_overlap": 0,
            "s6_union_mismatch": 0,
        },
        "approximation_register": list(APPROXIMATION_REGISTER),
        "ball_state_histogram": _histogram(
            row["ball_state"] for row in row_list
        ),
        "coverage": coverage,
        "denominators": _metric(row_list, cap),
        "half_histogram": _histogram(row["half"] for row in row_list),
        "pairwise_overlaps": pairwise,
        "race_pairs": race_pairs,
        "splits": splits,
        "thresholds": {
            "per_replay_cap": cap,
            "replay_split_hash": "sha256(first-8-bytes-big-endian) modulo 10000",
            "replay_split_key": split_key,
            "replay_split_thresholds": {
                "test": [8500, 10000],
                "train": [0, 7000],
                "validation": [7000, 8500],
            },
        },
        "turn_bands": turn_bands,
        "turn_histogram": _histogram(row["turn"] for row in row_list),
    }


def _new_temporary(destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    return Path(name)


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("wb") as target:
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _load_filter_manifest(path: Path, payload: bytes) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ScenarioCoverageError(f"cannot read filter manifest {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScenarioCoverageError("filter manifest root is not an object")
    return value


def _git_identity(repo_root: Path) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for label, revision in (("head", "HEAD"), ("tree", "HEAD^{tree}")):
        result = subprocess.run(
            ["git", "rev-parse", revision],
            cwd=repo_root,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode != 0:
            raise ScenarioCoverageError(
                f"cannot resolve git {label}: {result.stderr.strip()}"
            )
        values[label] = result.stdout.strip()
    status = subprocess.run(
        [
            "git",
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
            "--",
            "engine",
        ],
        cwd=repo_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if status.returncode != 0:
        raise ScenarioCoverageError(
            f"cannot inspect engine git state: {status.stderr.strip()}"
        )
    if status.stdout:
        raise ScenarioCoverageError(
            "tracked engine sources differ from the recorded git tree"
        )
    values["tracked_engine_clean"] = True
    return values


def _check_expected_histogram(
    observed: Mapping[str, int], expected: Mapping[int, int], label: str
) -> None:
    normalized = {str(key): value for key, value in sorted(expected.items())}
    if dict(observed) != normalized:
        raise ScenarioCoverageError(
            f"{label} histogram mismatch: {dict(observed)} != {normalized}"
        )


def _read_scanner_rows(path: Path) -> list[dict[str, int]]:
    rows: list[dict[str, int]] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as source:
            for line_number, line in enumerate(source, 1):
                if not line.endswith("\n"):
                    raise ScenarioCoverageError(
                        f"scanner JSON line {line_number} lacks newline"
                    )
                if len(line) > 128 * 1024:
                    raise ScenarioCoverageError(
                        f"scanner JSON line {line_number} is implausibly large"
                    )
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ScenarioCoverageError(
                        f"scanner JSON parse failure at line {line_number}: {exc}"
                    ) from exc
                if not isinstance(value, dict):
                    raise ScenarioCoverageError(
                        f"scanner JSON line {line_number} is not an object"
                    )
                canonical = json.dumps(
                    value, separators=(",", ":"), sort_keys=True
                ) + "\n"
                if line != canonical:
                    raise ScenarioCoverageError(
                        f"scanner JSON line {line_number} is not canonical"
                    )
                rows.append(value)
    except (OSError, UnicodeError) as exc:
        raise ScenarioCoverageError(f"cannot read scanner output: {exc}") from exc
    return rows


def generate_scenario_report(
    *,
    bank_path: str | Path,
    filter_manifest_path: str | Path,
    scanner_path: str | Path,
    scanner_sources: Mapping[str | Path, str],
    records_path: str | Path,
    report_path: str | Path,
    manifest_path: str | Path,
    expected_bank_sha256: str,
    expected_filter_manifest_sha256: str,
    expected_scanner_sha256: str,
    expected_records: int,
    expected_replay_ids: int,
    expected_half_histogram: Mapping[int, int],
    expected_turn_histogram: Mapping[int, int],
    expected_ball_state_histogram: Mapping[int, int] | None = None,
    command: list[str],
    split_key: str = DEFAULT_SPLIT_KEY,
    cap: int = DEFAULT_CAP,
    repo_root: str | Path | None = None,
    compiler: str = "cc",
    compiler_flags: str = "-std=c11 -O2 -g -Wall -Wextra -Werror",
) -> dict[str, Any]:
    bank_path = Path(bank_path).expanduser().resolve()
    filter_manifest_path = Path(filter_manifest_path).expanduser().resolve()
    scanner_path = Path(scanner_path).expanduser().resolve()
    records_path = Path(records_path).expanduser().resolve()
    report_path = Path(report_path).expanduser().resolve()
    manifest_path = Path(manifest_path).expanduser().resolve()
    resolved_sources = {
        Path(path).expanduser().resolve(): expected
        for path, expected in scanner_sources.items()
    }
    destinations = (records_path, report_path, manifest_path)
    all_paths = (
        bank_path,
        filter_manifest_path,
        scanner_path,
        *resolved_sources,
        *destinations,
    )
    if len(set(all_paths)) != len(all_paths):
        raise ScenarioCoverageError("input, scanner, source, and output paths must be distinct")
    if not bank_path.is_file():
        raise ScenarioCoverageError(f"bank is not a file: {bank_path}")
    if not filter_manifest_path.is_file():
        raise ScenarioCoverageError(
            f"filter manifest is not a file: {filter_manifest_path}"
        )
    if not scanner_path.is_file() or not os.access(scanner_path, os.X_OK):
        raise ScenarioCoverageError(f"scanner is not an executable file: {scanner_path}")
    if not resolved_sources:
        raise ScenarioCoverageError("at least one scanner source pin is required")
    if len({path.parent for path in destinations}) != 1:
        raise ScenarioCoverageError("all output paths must share one directory")
    output_directory = records_path.parent
    if not output_directory.is_dir():
        raise ScenarioCoverageError(
            f"output directory does not exist: {output_directory}"
        )
    for destination in destinations:
        if destination.exists():
            raise ScenarioCoverageError(f"output already exists: {destination}")
    if not command or not all(isinstance(item, str) and item for item in command):
        raise ScenarioCoverageError("command must be a nonempty string array")
    if expected_records <= 0 or expected_replay_ids <= 0:
        raise ScenarioCoverageError("expected counts must be positive")

    for value, label in (
        (expected_bank_sha256, "bank"),
        (expected_filter_manifest_sha256, "filter manifest"),
        (expected_scanner_sha256, "scanner"),
    ):
        _validate_expected_sha(value, label)
    for source, expected in resolved_sources.items():
        _validate_expected_sha(expected, f"scanner source {source}")
        if not source.is_file():
            raise ScenarioCoverageError(f"scanner source is not a file: {source}")

    bank_sha = sha256(bank_path)
    if bank_sha != expected_bank_sha256:
        raise ScenarioCoverageError(
            f"bank SHA-256 mismatch: {bank_sha} != {expected_bank_sha256}"
        )
    try:
        filter_manifest_payload = filter_manifest_path.read_bytes()
    except OSError as exc:
        raise ScenarioCoverageError(
            f"cannot read filter manifest {filter_manifest_path}: {exc}"
        ) from exc
    filter_manifest_sha = hashlib.sha256(filter_manifest_payload).hexdigest()
    if filter_manifest_sha != expected_filter_manifest_sha256:
        raise ScenarioCoverageError(
            "filter manifest SHA-256 mismatch: "
            f"{filter_manifest_sha} != {expected_filter_manifest_sha256}"
        )
    scanner_sha = sha256(scanner_path)
    if scanner_sha != expected_scanner_sha256:
        raise ScenarioCoverageError(
            f"scanner SHA-256 mismatch: {scanner_sha} != {expected_scanner_sha256}"
        )
    source_entries: list[dict[str, str]] = []
    for source, expected in sorted(resolved_sources.items(), key=lambda item: str(item[0])):
        observed = sha256(source)
        if observed != expected:
            raise ScenarioCoverageError(
                f"scanner source SHA-256 mismatch for {source}: {observed} != {expected}"
            )
        source_entries.append({"path": str(source), "sha256": observed})

    filter_manifest = _load_filter_manifest(
        filter_manifest_path, filter_manifest_payload
    )
    try:
        filter_output = filter_manifest["output"]
        filter_format = filter_manifest["format"]
    except (KeyError, TypeError) as exc:
        raise ScenarioCoverageError("filter manifest lacks output/format contract") from exc
    if filter_output.get("sha256") != bank_sha:
        raise ScenarioCoverageError("filter manifest output does not bind the bank SHA-256")
    if filter_output.get("records") != expected_records:
        raise ScenarioCoverageError("filter manifest record count mismatch")
    if filter_output.get("replay_ids") != expected_replay_ids:
        raise ScenarioCoverageError("filter manifest replay-ID count mismatch")
    _check_expected_histogram(
        filter_output.get("half_histogram", {}),
        expected_half_histogram,
        "filter manifest half",
    )
    _check_expected_histogram(
        filter_output.get("turn_histogram", {}),
        expected_turn_histogram,
        "filter manifest turn",
    )

    if repo_root is None:
        repo_root = Path(__file__).resolve().parent.parent
    repo_root = Path(repo_root).expanduser().resolve()
    git_identity = _git_identity(repo_root)
    tool_path = Path(__file__).resolve()
    tool_sha = sha256(tool_path)

    temporaries: list[Path] = []
    published: list[tuple[Path, Path]] = []
    committed = False
    try:
        temporary_records = _new_temporary(records_path)
        temporaries.append(temporary_records)
        temporary_report = _new_temporary(report_path)
        temporaries.append(temporary_report)
        temporary_manifest = _new_temporary(manifest_path)
        temporaries.append(temporary_manifest)

        with temporary_records.open("wb") as target:
            process = subprocess.run(
                [str(scanner_path), str(bank_path)],
                stdout=target,
                stderr=subprocess.PIPE,
                check=False,
            )
            target.flush()
            os.fsync(target.fileno())
        if process.returncode != 0:
            stderr = process.stderr.decode("utf-8", errors="replace")[:4096]
            raise ScenarioCoverageError(
                f"scanner failed with status {process.returncode}: {stderr.strip()}"
            )
        if sha256(bank_path) != bank_sha:
            raise ScenarioCoverageError("bank changed while scanner was running")
        if sha256(filter_manifest_path) != filter_manifest_sha:
            raise ScenarioCoverageError(
                "filter manifest changed while scanner was running"
            )
        if sha256(scanner_path) != scanner_sha:
            raise ScenarioCoverageError(
                "scanner binary changed while scanner was running"
            )
        for source, expected in resolved_sources.items():
            if sha256(source) != expected:
                raise ScenarioCoverageError(
                    f"scanner source changed while scanner was running: {source}"
                )
        if sha256(tool_path) != tool_sha:
            raise ScenarioCoverageError(
                "report tool changed while scanner was running"
            )

        rows = _read_scanner_rows(temporary_records)
        report = summarize_rows(rows, split_key=split_key, cap=cap)
        if report["denominators"]["records"] != expected_records:
            raise ScenarioCoverageError(
                "scanner record count mismatch: "
                f"{report['denominators']['records']} != {expected_records}"
            )
        if report["denominators"]["replays"] != expected_replay_ids:
            raise ScenarioCoverageError(
                "scanner replay-ID count mismatch: "
                f"{report['denominators']['replays']} != {expected_replay_ids}"
            )
        _check_expected_histogram(
            report["half_histogram"], expected_half_histogram, "scanner half"
        )
        _check_expected_histogram(
            report["turn_histogram"], expected_turn_histogram, "scanner turn"
        )
        if expected_ball_state_histogram is not None:
            _check_expected_histogram(
                report["ball_state_histogram"],
                expected_ball_state_histogram,
                "scanner ball-state",
            )

        report_payload = (
            json.dumps(report, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_bytes(temporary_report, report_payload)
        records_sha = sha256(temporary_records)
        report_sha = sha256(temporary_report)
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "command": command,
            "filter_manifest": {
                "path": str(filter_manifest_path),
                "sha256": filter_manifest_sha,
            },
            "format": filter_format,
            "git": git_identity,
            "input": {
                "ball_state_histogram": report["ball_state_histogram"],
                "bytes": bank_path.stat().st_size,
                "half_histogram": report["half_histogram"],
                "path": str(bank_path),
                "records": expected_records,
                "replay_ids": expected_replay_ids,
                "sha256": bank_sha,
                "turn_histogram": report["turn_histogram"],
            },
            "invariants": {
                "anomalies": report["anomalies"],
                "approximation_register": report["approximation_register"],
                "ball_state_reconciled_to_independent_pickup_probe":
                    expected_ball_state_histogram is not None,
                "overlap_relations": [
                    "s2 is a subset of s1",
                    "s4 and s5 are disjoint",
                    "s6 is the union of s6a and s6b",
                ],
            },
            "outputs": {
                "records": {
                    "bytes": temporary_records.stat().st_size,
                    "path": str(records_path),
                    "sha256": records_sha,
                },
                "report": {
                    "bytes": temporary_report.stat().st_size,
                    "path": str(report_path),
                    "sha256": report_sha,
                },
            },
            "scanner": {
                "binary": {"path": str(scanner_path), "sha256": scanner_sha},
                "build": {"compiler": compiler, "flags": compiler_flags},
                "sources": source_entries,
            },
            "thresholds": report["thresholds"],
            "tool": {"path": str(tool_path), "sha256": tool_sha},
        }
        manifest_payload = (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_bytes(temporary_manifest, manifest_payload)

        for temporary, destination in (
            (temporary_records, records_path),
            (temporary_report, report_path),
        ):
            published.append((temporary, destination))
            os.link(temporary, destination)
        _fsync_directory(output_directory)
        published.append((temporary_manifest, manifest_path))
        os.link(temporary_manifest, manifest_path)
        _fsync_directory(output_directory)
        committed = True
        for path in temporaries:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            _fsync_directory(output_directory)
        except OSError:
            pass
        return manifest
    except BaseException:
        if not committed:
            for temporary, destination in reversed(published):
                try:
                    if destination.samefile(temporary):
                        destination.unlink()
                except OSError:
                    pass
        for path in temporaries:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            _fsync_directory(output_directory)
        except OSError:
            pass
        raise


def _parse_source_pin(value: str) -> tuple[Path, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("scanner source pin must be PATH=SHA256")
    path, expected = value.rsplit("=", 1)
    if not path or SHA256_RE.fullmatch(expected) is None:
        raise argparse.ArgumentTypeError("scanner source pin must be PATH=SHA256")
    return Path(path), expected


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("bank", type=Path)
    parser.add_argument("--filter-manifest", type=Path, required=True)
    parser.add_argument("--scanner", type=Path, required=True)
    parser.add_argument(
        "--scanner-source", type=_parse_source_pin, action="append", required=True
    )
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expect-bank-sha256", required=True)
    parser.add_argument("--expect-filter-manifest-sha256", required=True)
    parser.add_argument("--expect-scanner-sha256", required=True)
    parser.add_argument("--expect-records", type=int, default=15348)
    parser.add_argument("--expect-replay-ids", type=int, default=5328)
    parser.add_argument("--split-key", default=DEFAULT_SPLIT_KEY)
    parser.add_argument("--per-replay-cap", type=int, default=DEFAULT_CAP)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--compiler", default="cc")
    parser.add_argument(
        "--compiler-flags", default="-std=c11 -O2 -g -Wall -Wextra -Werror"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw_argv)
    command = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve())]
    command.extend(raw_argv)
    try:
        manifest = generate_scenario_report(
            bank_path=args.bank,
            filter_manifest_path=args.filter_manifest,
            scanner_path=args.scanner,
            scanner_sources=dict(args.scanner_source),
            records_path=args.records,
            report_path=args.report,
            manifest_path=args.manifest,
            expected_bank_sha256=args.expect_bank_sha256,
            expected_filter_manifest_sha256=args.expect_filter_manifest_sha256,
            expected_scanner_sha256=args.expect_scanner_sha256,
            expected_records=args.expect_records,
            expected_replay_ids=args.expect_replay_ids,
            expected_half_histogram={1: args.expect_records},
            expected_turn_histogram=CANONICAL_TURN_HISTOGRAM,
            expected_ball_state_histogram=CANONICAL_BALL_STATE_HISTOGRAM,
            command=command,
            split_key=args.split_key,
            cap=args.per_replay_cap,
            repo_root=args.repo_root,
            compiler=args.compiler,
            compiler_flags=args.compiler_flags,
        )
    except (OSError, ScenarioCoverageError, ValueError) as exc:
        print(f"scenario coverage failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "manifest": str(Path(args.manifest).resolve()),
                "records_sha256": manifest["outputs"]["records"]["sha256"],
                "report_sha256": manifest["outputs"]["report"]["sha256"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
