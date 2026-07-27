#!/usr/bin/env python3
"""Black-box contract tests for standalone state-bank descriptor/audit modes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any


DESCRIPTOR_KEYS = {
    "schema",
    "family",
    "threshold",
    "eligible_records",
    "sha256",
}
AUDIT_KEYS = {
    "bank_sha256",
    "record_index",
    "source_id",
    "command",
    "half",
    "turn",
}


def fail(message: str) -> None:
    raise AssertionError(message)


def parse_json_line(output: str, label: str) -> dict[str, Any]:
    lines = output.splitlines()
    if len(lines) != 1:
        fail(f"{label}: expected exactly one stdout line, got {lines!r}")
    value = json.loads(lines[0])
    if not isinstance(value, dict):
        fail(f"{label}: expected a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--fixture-dir", type=Path, required=True)
    args = parser.parse_args()

    expected = json.loads(
        (args.fixture_dir / "state_bank_strata.expected.json").read_text(
            encoding="ascii"
        )
    )
    active = args.fixture_dir / "active"
    typed_tuple = [
        "--bank-kind",
        "strict-replay",
        "--bank",
        str(active / "state_bank.bbs"),
        "--bank-producer-manifest",
        str(active / "state_bank.producer.json"),
        "--bank-contract",
        str(active / "state_bank.contract.json"),
    ]

    def run(arguments: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [str(args.binary), *arguments],
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    for family, descriptors in expected["families"].items():
        for descriptor in descriptors:
            completed = run(
                [
                    "--state-bank-descriptor",
                    family,
                    str(descriptor["threshold"]),
                    *typed_tuple,
                ]
            )
            if completed.returncode != 0:
                fail(
                    f"descriptor {family}={descriptor['threshold']} failed: "
                    f"{completed.stderr}"
                )
            observed = parse_json_line(
                completed.stdout,
                f"descriptor {family}={descriptor['threshold']}",
            )
            if set(observed) != DESCRIPTOR_KEYS:
                fail(f"descriptor keys differ: {sorted(observed)}")
            wanted = {
                "schema": expected["strata_schema"],
                "family": family,
                "threshold": descriptor["threshold"],
                "eligible_records": descriptor["eligible_records"],
                "sha256": descriptor["sha256"],
            }
            if observed != wanted:
                fail(
                    f"descriptor {family}={descriptor['threshold']} differs: "
                    f"{observed!r} != {wanted!r}"
                )

    audit = run(
        [
            "--state-bank-audit",
            "pass-maxrange",
            "3",
            "32",
            *typed_tuple,
        ]
    )
    if audit.returncode != 0:
        fail(f"audit failed: {audit.stderr}")
    rows = [json.loads(line) for line in audit.stdout.splitlines()]
    if len(rows) != 32:
        fail(f"audit emitted {len(rows)} rows instead of 32")
    record_by_ordinal = {row["ordinal"]: row for row in expected["records"]}
    allowed = set(expected["families"]["pass-maxrange"][3]["ordinals"])
    for row in rows:
        if not isinstance(row, dict) or set(row) != AUDIT_KEYS:
            fail(f"audit row has wrong shape: {row!r}")
        ordinal = row["record_index"]
        if isinstance(ordinal, bool) or ordinal not in allowed:
            fail(f"audit selected out-of-stratum ordinal {ordinal!r}")
        source = record_by_ordinal[ordinal]
        wanted = {
            "bank_sha256": expected["bank_sha256"],
            "record_index": ordinal,
            "source_id": source["source_id"],
            "command": source["command"],
            "half": source["half"],
            "turn": source["turn"],
        }
        if row != wanted:
            fail(f"audit metadata differs: {row!r} != {wanted!r}")

    invalid_cases = [
        ["--state-bank-descriptor", "uniform", "0"],
        ["--state-bank-descriptor", "uniform", "0", *typed_tuple, "7"],
        ["--state-bank-descriptor", "bogus", "0", *typed_tuple],
        ["--state-bank-descriptor", "uniform", "00", *typed_tuple],
        ["--state-bank-descriptor", "endzone-maxdist", "26", *typed_tuple],
        ["--state-bank-descriptor", "postkick-maxturn", "9", *typed_tuple],
        ["--state-bank-audit", "uniform", "0", "0", *typed_tuple],
        ["--state-bank-audit", "uniform", "0", "01", *typed_tuple],
        ["--state-bank-audit", "uniform", "0", "1001", *typed_tuple],
        [
            "--state-bank-descriptor",
            "uniform",
            "0",
            "--state-bank-audit",
            "uniform",
            "0",
            "1",
            *typed_tuple,
        ],
        [
            "--state-bank-descriptor",
            "uniform",
            "0",
            *typed_tuple,
            "--bank",
            str(active / "state_bank.bbs"),
        ],
        [
            "--state-bank-descriptor",
            "uniform",
            "0",
            *typed_tuple[:1],
            "authored-scenario",
            *typed_tuple[2:],
        ],
        [
            "--state-bank-descriptor",
            "uniform",
            "0",
            "--demo",
            *typed_tuple,
        ],
    ]
    for arguments in invalid_cases:
        completed = run(arguments)
        if completed.returncode != 2:
            fail(
                f"invalid CLI returned {completed.returncode}, expected 2: "
                f"{arguments!r}; stdout={completed.stdout!r}; "
                f"stderr={completed.stderr!r}"
            )
        if completed.stdout != "":
            fail(f"invalid CLI wrote stdout: {arguments!r}")

    empty_strata = [
        ("endzone-maxdist", 0),
        ("endzone-maxdist", 1),
        ("pickup-maxdist", 0),
        ("postkick-maxturn", 0),
        ("pass-maxrange", 0),
    ]
    for family, threshold in empty_strata:
        empty = run(
            [
                "--state-bank-audit",
                family,
                str(threshold),
                "1",
                *typed_tuple,
            ]
        )
        if empty.returncode == 0:
            fail(
                f"empty-stratum audit unexpectedly succeeded: " f"{family}={threshold}"
            )
        if empty.stdout != "":
            fail(f"empty-stratum audit wrote stdout: {empty.stdout!r}")
        diagnostic = (
            "bloodbowl: requested state-bank stratum is empty: "
            f"{family}={threshold}\n"
        )
        if not empty.stderr.endswith(diagnostic):
            fail(f"empty-stratum diagnostic differs: {empty.stderr!r}")

    contract = run(["--state-bank-contract"])
    if contract.returncode != 0:
        fail(f"compiled contract view failed: {contract.stderr}")
    contract_object = parse_json_line(contract.stdout, "compiled contract")
    if len(contract_object) != 21:
        fail(
            "compiled contract must remain exactly 21 fields, got "
            f"{len(contract_object)}"
        )
    if contract_object.get("strata_schema") != expected["strata_schema"]:
        fail("compiled contract strata schema differs")

    print("standalone state-bank contract: ok")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (AssertionError, json.JSONDecodeError) as error:
        print(f"standalone state-bank contract: FAIL: {error}", file=sys.stderr)
        raise SystemExit(1)
