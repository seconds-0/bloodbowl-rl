#!/usr/bin/env python3
"""Validate a frozen runtime plan against its pinned PLAN_ONLY manifest."""

import argparse
import hashlib
import json
from pathlib import Path


class IdentityError(ValueError):
    pass


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path, label: str) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise IdentityError(f"{label} is unreadable or malformed: {exc}") from exc
    if not isinstance(value, dict):
        raise IdentityError(f"{label} must be a JSON object")
    return value


def validate(plan_path: Path, manifest_path: Path | None = None) -> dict:
    plan_path = Path(plan_path)
    plan = load_object(plan_path, "plan")
    pin = plan.get("pinned_files", {}).get("actual_plan_only_manifest")
    if not isinstance(pin, dict) or not isinstance(pin.get("path"), str):
        raise IdentityError("plan is missing the actual PLAN_ONLY manifest pin")
    expected_sha = pin.get("sha256")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise IdentityError("PLAN_ONLY manifest pin has an invalid SHA-256")
    declared_path = Path(pin["path"])
    if not declared_path.is_absolute():
        raise IdentityError("PLAN_ONLY manifest pin path must be absolute")
    candidate = Path(manifest_path) if manifest_path is not None else declared_path
    actual_sha = sha256(candidate)
    if actual_sha != expected_sha:
        raise IdentityError("PLAN_ONLY manifest bytes do not match the plan pin")
    manifest = load_object(candidate, "PLAN_ONLY manifest")
    implementation = manifest.get("contract", {}).get("implementation")
    if not isinstance(implementation, dict):
        raise IdentityError("PLAN_ONLY manifest lacks contract.implementation")
    if plan.get("screen_implementation") != implementation:
        plan_impl = plan.get("screen_implementation")
        keys = sorted(
            key
            for key in set(plan_impl if isinstance(plan_impl, dict) else {}) | set(implementation)
            if not isinstance(plan_impl, dict) or plan_impl.get(key) != implementation.get(key)
        )
        raise IdentityError(
            "plan screen_implementation differs from pinned PLAN_ONLY manifest: "
            + ", ".join(keys)
        )
    return {
        "accepted": True,
        "plan": str(plan_path.resolve()),
        "plan_only_manifest": str(candidate.resolve()),
        "plan_only_manifest_sha256": actual_sha,
        "screen_implementation": implementation,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("plan", type=Path)
    parser.add_argument("--manifest", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate(args.plan, args.manifest), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except IdentityError as exc:
        print(f"runtime plan identity rejected: {exc}", file=__import__("sys").stderr)
        raise SystemExit(1)
