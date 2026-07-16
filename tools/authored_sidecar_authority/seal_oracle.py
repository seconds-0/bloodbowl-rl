#!/usr/bin/env python3
"""Seal the bootstrap oracle with every byte-immutable authority digest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


AUTHORITY_FILES = (
    "tools/authored_sidecar.h",
    "tools/authored_sidecar_authority/abi_probe.c",
    "tools/authored_sidecar_authority/build_oracle.py",
    "tools/authored_sidecar_authority/expected/records.jsonl",
    "tools/authored_sidecar_authority/expected/recipes.jsonl",
    "tools/authored_sidecar_authority/fact_probe.c",
    "tools/authored_sidecar_authority/fixture_selftest.py",
    "tools/authored_sidecar_authority/isolation_selftest.py",
    "tools/authored_sidecar_authority/malicious_fixtures.json",
    "tools/authored_sidecar_authority/seal_oracle.py",
    "tools/authored_sidecar_authority/serializer_probe.c",
    "tools/authored_sidecar_authority/source_check.py",
    "tools/authored_sidecar_authority/verify_candidate.py",
    "tools/authored_sidecar_authority/verify_history.py",
    ".github/workflows/authored-sidecar-authority.yml",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("repository", type=Path)
    parser.add_argument("unsealed", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.repository.resolve()
    oracle = json.loads(args.unsealed.read_text(encoding="utf-8"))
    if oracle["authority_files"]:
        raise RuntimeError("input oracle is already sealed")
    authority: dict[str, str] = {}
    for relative in AUTHORITY_FILES:
        path = root / relative
        if not path.is_file():
            raise RuntimeError(f"missing authority file: {relative}")
        authority[relative] = sha256(path)
    oracle["authority_files"] = authority
    args.output.write_text(json.dumps(oracle, indent=2) + "\n",
                           encoding="ascii")
    print(f"sealed {len(authority)} sidecar authority files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
