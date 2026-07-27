#!/usr/bin/env python3
"""Generate the immutable native typed-state-bank integration fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct

import state_bank_contract


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def c_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbs", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    args = parser.parse_args()

    bbs = args.bbs.read_bytes()
    if len(bbs) < 16 or bbs[:4] != b"BBS1":
        raise SystemExit("fixture writer did not produce BBS1")
    version, match_size, fingerprint = struct.unpack("<III", bbs[4:16])
    record_size = 12 + match_size
    if version != 1 or (len(bbs) - 16) % record_size != 0:
        raise SystemExit("fixture BBS header/length mismatch")
    records = (len(bbs) - 16) // record_size
    if records != 1:
        raise SystemExit(f"integration fixture must contain one record, got {records}")

    immutable = args.out_dir / "immutable"
    active = args.out_dir / "active"
    immutable.mkdir(parents=True, exist_ok=True)
    active.mkdir(parents=True, exist_ok=True)
    immutable_bbs = immutable / "state_bank.bbs"
    if immutable_bbs != args.bbs:
        immutable_bbs.write_bytes(bbs)

    bank_sha = sha256(bbs)
    producer_engine = sha256(b"test-producer-engine-source-v1")
    repository_root = Path(__file__).resolve().parents[1]
    loader_engine = state_bank_contract.engine_source_sha256(repository_root)
    producer = canonical_json(
        {
            "artifact_role": "training-bank",
            "bank": {
                "bytes": len(bbs),
                "format": {
                    "engine_fingerprint": f"0x{fingerprint:08x}",
                    "magic": "BBS1",
                    "match_size": match_size,
                    "version": version,
                },
                "records": records,
                "sha256": bank_sha,
            },
            "bank_kind": "strict-replay",
            "producer": {
                "kind": "test-strict-fixture-v1",
                "producer_engine_source_sha256": producer_engine,
            },
            "ruleset": "BB2025",
            "schema": "bloodbowl-state-bank-producer-v1",
            "training_eligible": True,
        }
    )
    producer_sha = sha256(producer)
    contract = canonical_json(
        {
            "artifact_role": "training-bank",
            "authorization": {
                "decision": "native-integration-test-only",
                "schema": "bloodbowl-state-bank-authorization-v1",
            },
            "bank": {
                "bytes": len(bbs),
                "format": {
                    "engine_fingerprint": f"0x{fingerprint:08x}",
                    "magic": "BBS1",
                    "match_size": match_size,
                    "version": version,
                },
                "records": records,
                "sha256": bank_sha,
            },
            "bank_kind": "strict-replay",
            "loader": {"engine_source_sha256": loader_engine},
            "producer_manifest": {
                "producer_engine_source_sha256": producer_engine,
                "schema": "bloodbowl-state-bank-producer-v1",
                "sha256": producer_sha,
            },
            "ruleset": "BB2025",
            "schema": "bloodbowl-state-bank-training-contract-v1",
            "training_eligible": True,
        }
    )
    contract_sha = sha256(contract)
    immutable_producer = immutable / "state_bank.producer.json"
    immutable_contract = immutable / "state_bank.contract.json"
    immutable_producer.write_bytes(producer)
    immutable_contract.write_bytes(contract)
    active_bbs = active / "state_bank.bbs"
    active_producer = active / "state_bank.producer.json"
    active_contract = active / "state_bank.contract.json"
    shutil.copyfile(immutable_bbs, active_bbs)
    shutil.copyfile(immutable_producer, active_producer)
    shutil.copyfile(immutable_contract, active_contract)

    # Paths are intentionally relative to the repository root, where make
    # executes the integration binary.
    def relative(path: Path) -> str:
        return path.as_posix()

    identity_fields: dict[str, str | int] = {
        "contract_schema": "bloodbowl-state-bank-training-contract-v1",
        "producer_schema": "bloodbowl-state-bank-producer-v1",
        "authorization_schema": "bloodbowl-state-bank-authorization-v1",
        "kind_value": 1,
        "kind": "strict-replay",
        "ruleset": "BB2025",
        "bank_sha256": bank_sha,
        "producer_manifest_sha256": producer_sha,
        "training_contract_sha256": contract_sha,
        "producer_engine_source_sha256": producer_engine,
        "loader_engine_source_sha256": loader_engine,
        "bytes": len(bbs),
        "records": records,
        "bbs_version": version,
        "match_size": match_size,
        "engine_fingerprint": fingerprint,
        "bank_path": relative(active_bbs),
        "producer_manifest_path": relative(active_producer),
        "training_contract_path": relative(active_contract),
    }
    identity_fields["contract_identity"] = (
        state_bank_contract.compiled_contract_identity(identity_fields)
    )
    field_to_macro_suffix = {
        "contract_schema": "CONTRACT_SCHEMA",
        "producer_schema": "PRODUCER_SCHEMA",
        "authorization_schema": "AUTHORIZATION_SCHEMA",
        "kind_value": "COMPILED_KIND",
        "kind": "KIND_NAME",
        "ruleset": "RULESET",
        "bank_sha256": "BBS_SHA256",
        "producer_manifest_sha256": "PRODUCER_MANIFEST_SHA256",
        "training_contract_sha256": "TRAINING_CONTRACT_SHA256",
        "producer_engine_source_sha256": "PRODUCER_ENGINE_SOURCE_SHA256",
        "loader_engine_source_sha256": "LOADER_ENGINE_SOURCE_SHA256",
        "bytes": "BBS_BYTES",
        "records": "RECORDS",
        "bbs_version": "BBS_VERSION",
        "match_size": "MATCH_SIZE",
        "engine_fingerprint": "ENGINE_FINGERPRINT",
        "contract_identity": "CONTRACT_IDENTITY",
        "bank_path": "BBS_PATH",
        "producer_manifest_path": "PRODUCER_MANIFEST_PATH",
        "training_contract_path": "TRAINING_CONTRACT_PATH",
    }
    lines = [
        "#ifndef BBE_TEST_STATE_BANK_BUILD_GENERATED_H",
        "#define BBE_TEST_STATE_BANK_BUILD_GENERATED_H",
        "",
    ]
    for field, value in identity_fields.items():
        rendered = str(value) if isinstance(value, int) else c_string(value)
        lines.append(
            f"#define PUFFER_STATE_BANK_{field_to_macro_suffix[field]} "
            f"{rendered}"
        )
    lines.extend(["", "#endif", ""])
    (args.out_dir / "state_bank_build.generated.h").write_text(
        "\n".join(lines), encoding="ascii"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
