#!/usr/bin/env python3
"""Execute one hash-frozen reward screen from a closed JSON configuration.

This wrapper exists for ``experiment_queue.py``: queue literals deliberately
cannot carry arbitrary strings or paths, while the existing reward-screen
launcher takes named environment variables.  The reviewed JSON file is itself
hash-pinned by the queue and this wrapper revalidates every indirect input
before invoking the ordinary audited launcher.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import analyze_reward_candidate_transfer


class FrozenScreenError(ValueError):
    pass


ALLOWED_KEYS = {
    "schema_version",
    "root",
    "profile",
    "candidate_arm",
    "steps",
    "prefix",
    "out_dir",
    "warm",
    "pool",
    "candidate_transfer",
    "require_gate",
    "implementation",
}
FILE_KEYS = {"path", "bytes", "sha256"}
TREE_KEYS = {"path", "files", "bytes", "sha256"}
IMPLEMENTATION_KEYS = {
    "launcher_sha256",
    "screen_analyzer_sha256",
    "transfer_analyzer_sha256",
}
PREFIX_PATTERN = re.compile(r"[A-Za-z0-9._-]+")


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_identity(path: Path) -> tuple[int, int, str]:
    digest = hashlib.sha256()
    count = 0
    total = 0
    for child in sorted(path.rglob("*")):
        if child.is_symlink():
            raise FrozenScreenError(f"pinned tree contains symlink: {child}")
        if child.is_dir():
            continue
        if not child.is_file():
            raise FrozenScreenError(f"pinned tree contains non-file: {child}")
        relative = child.relative_to(path).as_posix()
        size = child.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha256(child).encode("ascii"))
        digest.update(b"\n")
        count += 1
        total += size
    return count, total, digest.hexdigest()


def load(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FrozenScreenError(f"invalid frozen-screen config: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FrozenScreenError("frozen-screen config must be an object")
    return value


def need_sha(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise FrozenScreenError(f"{label} must be a lowercase SHA-256")
    return value


def under_root(path: Path, root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise FrozenScreenError(f"{label} escapes frozen root: {resolved}") from exc
    return resolved


def validate_file(record: Any, label: str) -> Path:
    if not isinstance(record, dict) or set(record) != FILE_KEYS:
        raise FrozenScreenError(f"{label} must contain path/bytes/sha256")
    path_value = record.get("path")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise FrozenScreenError(f"{label} path must be absolute")
    path = Path(path_value).resolve()
    if not path.is_file():
        raise FrozenScreenError(f"missing {label}: {path}")
    size = record.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise FrozenScreenError(f"{label} bytes must be positive")
    if path.stat().st_size != size:
        raise FrozenScreenError(f"{label} size drift: {path}")
    expected = need_sha(record.get("sha256"), f"{label} sha256")
    if sha256(path) != expected:
        raise FrozenScreenError(f"{label} SHA-256 drift: {path}")
    return path


def validate_config(path: Path) -> dict[str, Any]:
    config = load(path)
    if set(config) != ALLOWED_KEYS:
        unexpected = sorted(set(config) - ALLOWED_KEYS)
        missing = sorted(ALLOWED_KEYS - set(config))
        raise FrozenScreenError(
            f"frozen-screen config fields differ; unknown={unexpected}, missing={missing}"
        )
    if config.get("schema_version") != 1:
        raise FrozenScreenError("unsupported frozen-screen config schema")
    root_value = config.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise FrozenScreenError("root must be absolute")
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise FrozenScreenError(f"root does not exist: {root}")
    profile = config.get("profile")
    if profile not in ("paired-confirmation", "paired-final"):
        raise FrozenScreenError("frozen queue supports only paired profiles")
    candidate = config.get("candidate_arm")
    if candidate not in ("possession_only", "gain_only", "neither"):
        raise FrozenScreenError("invalid frozen candidate_arm")
    steps = config.get("steps")
    if isinstance(steps, bool) or not isinstance(steps, int) or steps <= 0:
        raise FrozenScreenError("steps must be a positive integer")
    prefix = config.get("prefix")
    if not isinstance(prefix, str) or PREFIX_PATTERN.fullmatch(prefix) is None:
        raise FrozenScreenError("prefix has unsupported characters")
    out_value = config.get("out_dir")
    if not isinstance(out_value, str) or not Path(out_value).is_absolute():
        raise FrozenScreenError("out_dir must be absolute")
    out_dir = under_root(Path(out_value), root, "out_dir")
    warm = validate_file(config.get("warm"), "warm checkpoint")
    under_root(warm, root, "warm checkpoint")
    if warm.stat().st_size != 16_066_560:
        raise FrozenScreenError("warm checkpoint has the wrong architecture size")
    pool_record = config.get("pool")
    if not isinstance(pool_record, dict) or set(pool_record) != TREE_KEYS:
        raise FrozenScreenError("pool must contain path/files/bytes/sha256")
    pool_value = pool_record.get("path")
    if not isinstance(pool_value, str) or not Path(pool_value).is_absolute():
        raise FrozenScreenError("pool path must be absolute")
    pool = under_root(Path(pool_value), root, "pool")
    if not pool.is_dir():
        raise FrozenScreenError(f"pool is missing: {pool}")
    observed_tree = tree_identity(pool)
    expected_tree = (
        pool_record.get("files"),
        pool_record.get("bytes"),
        need_sha(pool_record.get("sha256"), "pool sha256"),
    )
    if observed_tree != expected_tree:
        raise FrozenScreenError(
            f"pool tree drift: observed={observed_tree}, expected={expected_tree}"
        )
    transfer = validate_file(
        config.get("candidate_transfer"), "candidate transfer completion"
    )
    evidence = analyze_reward_candidate_transfer.validate_completion_evidence(
        transfer,
        expected_complete_sha=sha256(transfer),
        expected_candidate=candidate,
    )
    implementation = config.get("implementation")
    if not isinstance(implementation, dict) or set(implementation) != IMPLEMENTATION_KEYS:
        raise FrozenScreenError("implementation hash set is incomplete")
    source_files = {
        "launcher_sha256": root / "tools/run_reward_screen.sh",
        "screen_analyzer_sha256": root / "tools/analyze_reward_screen.py",
        "transfer_analyzer_sha256":
            root / "tools/analyze_reward_candidate_transfer.py",
    }
    for key, source in source_files.items():
        expected = need_sha(implementation.get(key), f"implementation.{key}")
        if not source.is_file() or sha256(source) != expected:
            raise FrozenScreenError(f"implementation drift: {source}")
    require_gate = config.get("require_gate")
    if not isinstance(require_gate, bool):
        raise FrozenScreenError("require_gate must be boolean")
    return {
        **config,
        "root_path": root,
        "out_path": out_dir,
        "warm_path": warm,
        "pool_path": pool,
        "transfer_path": transfer,
        "candidate_evidence": evidence,
    }


def validate_gate(path: Path, candidate: str) -> None:
    try:
        from vacation_reward_gate import validate_completion
    except ImportError as exc:
        raise FrozenScreenError("vacation gate validator is unavailable") from exc
    report = validate_completion(path)
    if report.get("candidate_arm") != candidate or not report.get("passed"):
        raise FrozenScreenError("vacation gate does not authorize this candidate")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--gate-complete", type=Path)
    args = parser.parse_args(argv)
    try:
        config = validate_config(args.config.expanduser().resolve())
        if config["require_gate"]:
            if args.gate_complete is None:
                raise FrozenScreenError("this frozen screen requires --gate-complete")
            validate_gate(args.gate_complete.expanduser().resolve(), config["candidate_arm"])
        elif args.gate_complete is not None:
            raise FrozenScreenError("unexpected --gate-complete for ungated screen")
        environment = {
            **os.environ,
            "WARM": str(config["warm_path"]),
            "POOL": str(config["pool_path"]),
            "STEPS": str(config["steps"]),
            "SCREEN_PROFILE": config["profile"],
            "CANDIDATE_ARM": config["candidate_arm"],
            "TRANSFER_COMPLETE": str(config["transfer_path"]),
            "EXPECTED_TRANSFER_SHA256": sha256(config["transfer_path"]),
            "PREFIX": config["prefix"],
            "OUT_DIR": str(config["out_path"]),
            "POLL_SECONDS": "30",
            "ARM_DETACH": "0",
        }
        result = subprocess.run(
            ["/usr/bin/bash", str(config["root_path"] / "tools/run_reward_screen.sh")],
            cwd=config["root_path"],
            env=environment,
            check=False,
        )
        return result.returncode
    except (
        OSError,
        FrozenScreenError,
        analyze_reward_candidate_transfer.TransferError,
        ValueError,
    ) as exc:
        print(f"frozen reward screen failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
