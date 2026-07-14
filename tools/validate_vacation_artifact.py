#!/usr/bin/env python3
"""Bounded semantic validators for vacation-queue success artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import analyze_reward_candidate_transfer
import analyze_reward_screen
import run_frozen_reward_screen


class ArtifactError(ValueError):
    pass


def validate_screen(config_path: Path, complete_path: Path) -> dict:
    config = run_frozen_reward_screen.validate_config(config_path.resolve())
    complete_path = complete_path.resolve()
    if complete_path != config["out_path"] / "SCREEN_COMPLETE.json":
        raise ArtifactError("screen completion path differs from frozen config")
    completion = json.loads(complete_path.read_text(encoding="utf-8"))
    manifest_sha = completion.get("screen_manifest_sha256")
    report = analyze_reward_screen.analyze_screen(
        config["out_path"],
        analyze_reward_screen.DEFAULT_METRICS,
        expected_screen_sha=manifest_sha,
    )
    screen = report["screen"]
    expected = {
        "profile": config["profile"],
        "candidate_arm": config["candidate_arm"],
        "prefix": config["prefix"],
        "requested_steps": config["steps"],
    }
    for key, value in expected.items():
        if screen.get(key) != value:
            raise ArtifactError(
                f"screen {key}={screen.get(key)!r}, expected {value!r}"
            )
    if (
        not screen["completion"].get("present")
        or screen["completion"].get("sha256")
        != run_frozen_reward_screen.sha256(complete_path)
    ):
        raise ArtifactError("screen completion proof is not exact")
    manifest = json.loads(
        (config["out_path"] / "SCREEN_MANIFEST.json").read_text(
            encoding="utf-8"
        )
    )["contract"]
    if manifest["warm"]["sha256"] != config["warm"]["sha256"]:
        raise ArtifactError("screen warm checkpoint differs from frozen config")
    if manifest["pool"]["identity_sha256"] != json.loads(
        (config["pool_path"] / "league_seeds.json").read_text(encoding="utf-8")
    ).get("identity_sha256", manifest["pool"]["identity_sha256"]):
        # Older pool manifests do not carry identity_sha256; the frozen tree
        # and screen's own ordered-bank validation remain authoritative.
        raise ArtifactError("screen pool identity differs from pool manifest")
    return report


def validate_scripted(config_path: Path, complete_path: Path) -> dict:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    candidate = config.get("candidate_arm")
    if candidate not in ("possession_only", "gain_only", "neither"):
        raise ArtifactError("validator config has invalid candidate_arm")
    return analyze_reward_candidate_transfer.validate_completion_evidence(
        complete_path,
        expected_complete_sha=run_frozen_reward_screen.sha256(complete_path),
        expected_candidate=candidate,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--screen", action="store_true")
    mode.add_argument("--scripted-transfer", action="store_true")
    parser.add_argument("config", type=Path)
    parser.add_argument("artifact", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.screen:
            report = validate_screen(args.config, args.artifact)
        else:
            report = validate_scripted(args.config, args.artifact)
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0
    except (
        OSError,
        json.JSONDecodeError,
        ArtifactError,
        run_frozen_reward_screen.FrozenScreenError,
        analyze_reward_screen.AnalysisError,
        analyze_reward_candidate_transfer.TransferError,
        ValueError,
    ) as exc:
        print(f"vacation artifact validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
