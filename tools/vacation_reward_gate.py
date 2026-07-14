#!/usr/bin/env python3
"""Fail-closed two-lineage gate for unattended reward confirmation.

Both the main and second-ancestry paired screens must pass self-play
non-inferiority, scripted-opponent transfer, and learned-anchor transfer before
the predeclared long final screens may start.  A rejection writes diagnostic
evidence beside (not at) the success path and exits nonzero.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import sys
from pathlib import Path
from typing import Any

import analyze_reward_candidate_transfer
import analyze_reward_screen
import run_reward_learned_transfer


SCHEMA_VERSION = 1
CONFIG_KEYS = {
    "schema_version",
    "candidate_arm",
    "confirmation_steps",
    "mean_perf_delta_min",
    "seed_perf_delta_min",
    "max_candidate_td_relative_drop",
}
SCRIPTED_CONTRACT_KEYS = (
    "seeds",
    "bot_types",
    "bot_teams",
    "settings",
    "implementation",
    "orchestration_files",
    "conversion",
    "gates",
)
LEARNED_CONTRACT_KEYS = (
    "training_seeds",
    "orientations",
    "games_per_cell",
    "anchor_config",
    "anchor_config_sha256",
    "anchors",
    "gates",
    "implementation",
)


class GateError(ValueError):
    pass


class GateRejected(GateError):
    def __init__(self, report: dict[str, Any]):
        super().__init__("vacation reward gate rejected the candidate")
        self.report = report


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(
        destination.suffix + f".tmp.{os.getpid()}"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GateError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise GateError(f"{label} must be a JSON object: {path}")
    return value


def finite(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GateError(f"{label} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise GateError(f"{label} must be finite")
    return parsed


def validate_config(path: Path) -> dict[str, Any]:
    config = load_object(path, "vacation gate config")
    if set(config) != CONFIG_KEYS:
        raise GateError("vacation gate config has unknown or missing fields")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise GateError("unsupported vacation gate config schema")
    candidate = config.get("candidate_arm")
    if candidate not in ("possession_only", "gain_only", "neither"):
        raise GateError("vacation gate config has invalid candidate_arm")
    if config.get("confirmation_steps") != 1_000_000_000:
        raise GateError("confirmation_steps must be the reviewed 1B budget")
    for key in CONFIG_KEYS - {
        "schema_version", "candidate_arm", "confirmation_steps"
    }:
        config[key] = finite(config.get(key), key)
    if not 0 <= config["max_candidate_td_relative_drop"] <= 1:
        raise GateError("max_candidate_td_relative_drop must be in [0,1]")
    return config


def validate_screen(
    complete_path: Path, config: dict[str, Any], lineage: str
) -> tuple[dict[str, Any], list[str]]:
    complete_path = complete_path.expanduser().resolve()
    if complete_path.name != "SCREEN_COMPLETE.json":
        raise GateError(f"{lineage} screen artifact has the wrong name")
    completion = load_object(complete_path, f"{lineage} screen completion")
    expected_manifest_sha = completion.get("screen_manifest_sha256")
    report = analyze_reward_screen.analyze_screen(
        complete_path.parent,
        ("perf", "tds", "draw_rate"),
        expected_screen_sha=expected_manifest_sha,
    )
    screen = report["screen"]
    if (
        screen["profile"] != "paired-confirmation"
        or screen.get("candidate_arm") != config["candidate_arm"]
        or screen.get("requested_steps") != config["confirmation_steps"]
        or not screen["completion"].get("present")
        or screen["completion"].get("sha256") != sha256(complete_path)
    ):
        raise GateError(f"{lineage} paired screen identity mismatch")
    effect = report["across_seeds"]["effects"]["perf"][
        "candidate_minus_both"
    ]
    seed_deltas = effect["values_by_seed"]
    cell_summaries = report["across_seeds"]["cell_summaries"]
    reference_tds = finite(
        cell_summaries["both"]["tds"]["mean"],
        f"{lineage} reference TD mean",
    )
    candidate_tds = finite(
        cell_summaries[config["candidate_arm"]]["tds"]["mean"],
        f"{lineage} candidate TD mean",
    )
    td_relative_drop = (
        (reference_tds - candidate_tds) / reference_tds
        if reference_tds > 0
        else (0.0 if candidate_tds >= reference_tds else math.inf)
    )
    failures = []
    if effect["mean"] < config["mean_perf_delta_min"]:
        failures.append("mean_perf_delta")
    if min(seed_deltas.values()) < config["seed_perf_delta_min"]:
        failures.append("seed_perf_delta")
    if td_relative_drop > config["max_candidate_td_relative_drop"]:
        failures.append("candidate_td_relative_drop")
    return {
        "path": str(complete_path),
        "sha256": sha256(complete_path),
        "manifest_sha256": screen["manifest_sha256"],
        "requested_steps": screen["requested_steps"],
        "final_steps": screen["final_steps"],
        "perf_candidate_minus_both": effect,
        "reference_tds_mean": reference_tds,
        "candidate_tds_mean": candidate_tds,
        "candidate_td_relative_drop": td_relative_drop,
        "failures": failures,
    }, failures


def validate_scripted(
    complete_path: Path,
    screen: dict[str, Any],
    config: dict[str, Any],
    lineage: str,
) -> dict[str, Any]:
    complete_path = complete_path.expanduser().resolve()
    evidence = analyze_reward_candidate_transfer.validate_completion_evidence(
        complete_path,
        expected_complete_sha=sha256(complete_path),
        expected_candidate=config["candidate_arm"],
    )
    manifest = load_object(evidence["transfer_manifest"], "transfer manifest")
    source_screen = Path(str(manifest.get("source_screen", ""))).resolve()
    if source_screen != Path(screen["path"]).parent:
        raise GateError(f"{lineage} scripted transfer uses another screen")
    if manifest.get("source_screen_sha256") != screen["manifest_sha256"]:
        raise GateError(f"{lineage} scripted transfer screen hash mismatch")
    contract = {key: manifest.get(key) for key in SCRIPTED_CONTRACT_KEYS}
    if any(value is None for value in contract.values()):
        raise GateError(f"{lineage} scripted transfer contract is incomplete")
    return {
        "path": str(complete_path),
        "sha256": sha256(complete_path),
        "contract_identity": contract,
        **evidence,
    }


def validate_learned(
    complete_path: Path,
    screen: dict[str, Any],
    config: dict[str, Any],
    lineage: str,
) -> tuple[dict[str, Any], list[str]]:
    complete_path = complete_path.expanduser().resolve()
    report = run_reward_learned_transfer.validate_completion(complete_path)
    if report.get("candidate_arm") != config["candidate_arm"]:
        raise GateError(f"{lineage} learned transfer candidate mismatch")
    if report.get("source_screen_complete_sha256") != screen["sha256"]:
        raise GateError(f"{lineage} learned transfer uses another screen")
    failures = []
    if not report.get("eligible_for_longer_confirmation"):
        failures.extend(
            f"learned_{failure}" for failure in report.get("gate_failures", [])
        )
        if not failures:
            failures.append("learned_transfer_ineligible")
    manifest_record = report.get("learned_transfer_manifest")
    if not isinstance(manifest_record, dict):
        raise GateError(f"{lineage} learned transfer omitted its manifest")
    manifest = load_object(
        Path(str(manifest_record.get("path", ""))),
        f"{lineage} learned transfer manifest",
    )
    if manifest.get("games_per_cell") != 4096:
        raise GateError(f"{lineage} learned transfer is not the reviewed 4096 games")
    anchor_config_sha = manifest.get("anchor_config_sha256")
    if (
        not isinstance(anchor_config_sha, str)
        or len(anchor_config_sha) != 64
        or any(char not in "0123456789abcdef" for char in anchor_config_sha)
    ):
        raise GateError(f"{lineage} learned transfer anchor config SHA is invalid")
    anchors = manifest.get("anchors")
    if not isinstance(anchors, list) or not anchors:
        raise GateError(f"{lineage} learned transfer has no anchor identity")
    anchor_identity = [
        [record.get("name"), record.get("sha256")]
        for record in anchors
        if isinstance(record, dict)
    ]
    if len(anchor_identity) != len(anchors):
        raise GateError(f"{lineage} learned transfer anchors are malformed")
    if len(anchor_identity) != 4 or any(
        not isinstance(name, str)
        or not isinstance(digest, str)
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
        for name, digest in anchor_identity
    ):
        raise GateError(f"{lineage} learned transfer anchor identity is invalid")
    contract = {key: manifest.get(key) for key in LEARNED_CONTRACT_KEYS}
    if any(value is None for value in contract.values()):
        raise GateError(f"{lineage} learned transfer contract is incomplete")
    return {
        "path": str(complete_path),
        "sha256": sha256(complete_path),
        "eligible_for_longer_confirmation": report.get(
            "eligible_for_longer_confirmation"
        ),
        "gate_failures": report.get("gate_failures"),
        "mean_score_delta": report["paired_candidate_minus_reference"][
            "summary"
        ]["mean"],
        "worst_training_seed_mean": min(
            value["mean"]
            for value in report["paired_candidate_minus_reference"][
                "by_training_seed"
            ].values()
        ),
        "games_per_cell": manifest["games_per_cell"],
        "anchor_config_sha256": anchor_config_sha,
        "anchor_identity": anchor_identity,
        "gates": manifest.get("gates"),
        "implementation": manifest.get("implementation"),
        "training_seeds": manifest.get("training_seeds"),
        "orientations": manifest.get("orientations"),
        "contract_identity": contract,
    }, failures


def build_report(
    config_path: Path,
    *,
    main_screen: Path,
    main_scripted: Path,
    main_learned: Path,
    second_screen: Path,
    second_scripted: Path,
    second_learned: Path,
) -> dict[str, Any]:
    config_path = config_path.expanduser().resolve()
    config = validate_config(config_path)
    lineages = {}
    all_failures = []
    inputs = (
        ("main", main_screen, main_scripted, main_learned),
        ("second", second_screen, second_scripted, second_learned),
    )
    for lineage, screen_path, scripted_path, learned_path in inputs:
        screen, screen_failures = validate_screen(screen_path, config, lineage)
        scripted = validate_scripted(scripted_path, screen, config, lineage)
        learned, learned_failures = validate_learned(
            learned_path, screen, config, lineage
        )
        failures = [*screen_failures, *learned_failures]
        all_failures.extend(f"{lineage}:{failure}" for failure in failures)
        lineages[lineage] = {
            "screen": screen,
            "scripted_transfer": scripted,
            "learned_transfer": learned,
            "failures": failures,
        }
    for transfer_name in ("scripted_transfer", "learned_transfer"):
        main_contract = lineages["main"][transfer_name].get("contract_identity")
        second_contract = lineages["second"][transfer_name].get(
            "contract_identity"
        )
        if main_contract != second_contract:
            raise GateError(
                f"{transfer_name.replace('_', '-')} contract differs between "
                "the two lineages"
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "analysis": "two_lineage_vacation_reward_gate",
        "candidate_arm": config["candidate_arm"],
        "config": {
            "path": str(config_path),
            "sha256": sha256(config_path),
            "contract": config,
        },
        "lineages": lineages,
        "passed": not all_failures,
        "failures": all_failures,
        "warning": (
            "Passing authorizes only the already-declared long confirmation. "
            "It does not promote a production reward."
        ),
    }


def write_gate(output: Path, report: dict[str, Any]) -> None:
    if not report["passed"]:
        raise GateRejected(report)
    core = {**report, "completed_utc": utc_now()}
    if output.exists():
        recorded = load_object(output, "vacation gate completion")
        comparable = {key: recorded.get(key) for key in report}
        if comparable != report:
            raise GateError("existing vacation gate completion is stale")
    else:
        atomic_json(output, core)


def validate_completion(path: str | Path) -> dict[str, Any]:
    path = Path(path).expanduser().resolve()
    recorded = load_object(path, "vacation gate completion")
    if recorded.get("schema_version") != SCHEMA_VERSION or not recorded.get("passed"):
        raise GateError("vacation gate completion is not a passing schema-1 proof")
    config_record = recorded.get("config")
    lineages = recorded.get("lineages")
    if not isinstance(config_record, dict) or not isinstance(lineages, dict):
        raise GateError("vacation gate completion structure is incomplete")
    try:
        regenerated = build_report(
            Path(config_record["path"]),
            main_screen=Path(lineages["main"]["screen"]["path"]),
            main_scripted=Path(
                lineages["main"]["scripted_transfer"]["path"]
            ),
            main_learned=Path(
                lineages["main"]["learned_transfer"]["path"]
            ),
            second_screen=Path(lineages["second"]["screen"]["path"]),
            second_scripted=Path(
                lineages["second"]["scripted_transfer"]["path"]
            ),
            second_learned=Path(
                lineages["second"]["learned_transfer"]["path"]
            ),
        )
    except (KeyError, TypeError) as exc:
        raise GateError("vacation gate completion paths are malformed") from exc
    comparable = {key: recorded.get(key) for key in regenerated}
    if comparable != regenerated:
        raise GateError("vacation gate completion differs from regenerated evidence")
    return regenerated


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--main-screen", type=Path)
    parser.add_argument("--main-scripted", type=Path)
    parser.add_argument("--main-learned", type=Path)
    parser.add_argument("--second-screen", type=Path)
    parser.add_argument("--second-scripted", type=Path)
    parser.add_argument("--second-learned", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.validate:
            if any(
                value is not None
                for value in (
                    args.config,
                    args.main_screen,
                    args.main_scripted,
                    args.main_learned,
                    args.second_screen,
                    args.second_scripted,
                    args.second_learned,
                    args.output,
                )
            ):
                parser.error("--validate cannot be combined")
            print(
                json.dumps(
                    validate_completion(args.validate),
                    indent=2,
                    sort_keys=True,
                    allow_nan=False,
                )
            )
            return 0
        required = {
            "config": args.config,
            "main_screen": args.main_screen,
            "main_scripted": args.main_scripted,
            "main_learned": args.main_learned,
            "second_screen": args.second_screen,
            "second_scripted": args.second_scripted,
            "second_learned": args.second_learned,
            "output": args.output,
        }
        missing = [key for key, value in required.items() if value is None]
        if missing:
            parser.error("missing required arguments: " + ", ".join(missing))
        report = build_report(
            args.config,
            main_screen=args.main_screen,
            main_scripted=args.main_scripted,
            main_learned=args.main_learned,
            second_screen=args.second_screen,
            second_scripted=args.second_scripted,
            second_learned=args.second_learned,
        )
        write_gate(args.output, report)
        print(f"VACATION GATE PASSED: {args.output}")
        return 0
    except GateRejected as exc:
        if args.output is not None:
            rejected = args.output.with_name("GATE_REJECTED.json")
            atomic_json(rejected, {**exc.report, "rejected_utc": utc_now()})
            print(f"VACATION GATE REJECTED: {rejected}", file=sys.stderr)
        return 3
    except (
        OSError,
        GateError,
        analyze_reward_screen.AnalysisError,
        analyze_reward_candidate_transfer.TransferError,
        run_reward_learned_transfer.LearnedTransferError,
        ValueError,
    ) as exc:
        print(f"vacation reward gate failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
