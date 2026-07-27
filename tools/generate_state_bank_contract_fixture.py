#!/usr/bin/env python3
"""Generate the immutable multi-record typed-state-bank integration fixture."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
from typing import Any

import state_bank_contract


FIXTURE_SCHEMA = "bloodbowl-state-bank-fixture-v1"
EXPECTED_SCHEMA = "bloodbowl-state-bank-fixture-strata-v1"
STRATA_SCHEMA = "bloodbowl-legacy-state-bank-strata-v1"
FAMILIES = (
    "uniform",
    "endzone-maxdist",
    "pickup-maxdist",
    "postkick-maxturn",
    "pass-maxrange",
)
BOUNDS = {
    "uniform": 0,
    "endzone-maxdist": 25,
    "pickup-maxdist": 25,
    "postkick-maxturn": 8,
    "pass-maxrange": 25,
}
INELIGIBLE = -1


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical_json(value: object) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        + "\n"
    ).encode("ascii")


def c_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=True)


def strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SystemExit(f"duplicate expectation key {key!r}")
        result[key] = value
    return result


def exact_keys(value: Any, keys: tuple[str, ...], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != set(keys):
        raise SystemExit(
            f"{label} keys differ: got "
            f"{sorted(value) if isinstance(value, dict) else type(value).__name__}, "
            f"expected {sorted(keys)}"
        )
    return value


def exact_int(value: Any, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SystemExit(f"{label} must be an exact JSON integer")
    if value < minimum or value > maximum:
        raise SystemExit(f"{label} must be in [{minimum},{maximum}]")
    return value


def stratum_digest(
    bank_sha256: str,
    family: str,
    threshold: int,
    ordinals: list[int],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"bloodbowl-state-bank-stratum-v1\0")
    digest.update(bank_sha256.encode("ascii"))
    digest.update(b"\0")
    digest.update(family.encode("ascii"))
    digest.update(b"\0")
    digest.update(struct.pack("<II", threshold, len(ordinals)))
    for ordinal in ordinals:
        digest.update(struct.pack("<I", ordinal))
    return digest.hexdigest()


def parse_expectations(
    path: Path,
    *,
    bbs: bytes,
    match_size: int,
    records: int,
) -> list[dict[str, Any]]:
    try:
        document = json.loads(
            path.read_text(encoding="ascii"),
            object_pairs_hook=strict_object,
            parse_constant=lambda token: (_ for _ in ()).throw(
                SystemExit(f"nonfinite expectation token {token}")
            ),
        )
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot parse fixture expectations: {exc}") from exc
    document = exact_keys(document, ("families", "records", "schema"), "fixture")
    if document["schema"] != FIXTURE_SCHEMA:
        raise SystemExit(f"fixture schema must be {FIXTURE_SCHEMA!r}")
    if document["families"] != list(FAMILIES[1:]):
        raise SystemExit("fixture family order is not canonical")
    rows = document["records"]
    if not isinstance(rows, list) or len(rows) != records or records < 7:
        raise SystemExit(
            f"integration fixture must contain at least seven pinned records, "
            f"got {len(rows) if isinstance(rows, list) else type(rows).__name__}"
        )

    record_size = 12 + match_size
    parsed: list[dict[str, Any]] = []
    for ordinal, raw in enumerate(rows):
        row = exact_keys(
            raw,
            (
                "command",
                "expected_metrics",
                "half",
                "mirror_ordinal",
                "ordinal",
                "source_id",
                "turn",
            ),
            f"fixture.records[{ordinal}]",
        )
        if exact_int(row["ordinal"], f"record {ordinal} ordinal", 0, records - 1) != ordinal:
            raise SystemExit(f"fixture record {ordinal} ordinal is not canonical")
        source_id = exact_int(
            row["source_id"], f"record {ordinal} source_id", 1, 0xFFFFFFFF
        )
        command = exact_int(
            row["command"], f"record {ordinal} command", 0, 0xFFFFFFFF
        )
        half = exact_int(row["half"], f"record {ordinal} half", 1, 3)
        turn = exact_int(row["turn"], f"record {ordinal} turn", 1, 8)
        mirror = exact_int(
            row["mirror_ordinal"], f"record {ordinal} mirror_ordinal", -1, records - 1
        )
        metrics = row["expected_metrics"]
        if not isinstance(metrics, list) or len(metrics) != 4:
            raise SystemExit(f"record {ordinal} must pin four metrics")
        pinned_metrics: list[int] = []
        for family_index, metric in enumerate(metrics):
            family = FAMILIES[family_index + 1]
            pinned_metrics.append(
                exact_int(
                    metric,
                    f"record {ordinal} {family} metric",
                    INELIGIBLE,
                    BOUNDS[family],
                )
            )

        metadata = bbs[
            16 + ordinal * record_size : 16 + ordinal * record_size + 12
        ]
        observed_source, observed_command, observed_half, observed_turn, padding = (
            struct.unpack("<IIBB2s", metadata)
        )
        expected_metadata = (source_id, command, half, turn, b"\0\0")
        if (
            observed_source,
            observed_command,
            observed_half,
            observed_turn,
            padding,
        ) != expected_metadata:
            raise SystemExit(
                f"record {ordinal} metadata differs from authored expectation"
            )
        parsed.append(
            {
                "ordinal": ordinal,
                "source_id": source_id,
                "command": command,
                "half": half,
                "turn": turn,
                "mirror_ordinal": mirror,
                "expected_metrics": pinned_metrics,
            }
        )

    for row in parsed:
        mirror = row["mirror_ordinal"]
        if mirror < 0:
            continue
        peer = parsed[mirror]
        if peer["mirror_ordinal"] != row["ordinal"]:
            raise SystemExit("fixture mirror relation is not symmetric")
        if peer["expected_metrics"] != row["expected_metrics"]:
            raise SystemExit("fixture mirrors do not pin identical metrics")
    if not any(
        sum(metric >= 0 for metric in row["expected_metrics"]) >= 2
        for row in parsed
    ):
        raise SystemExit("fixture has no record shared by multiple families")
    if not all(
        any(row["expected_metrics"][family] < 0 for row in parsed)
        for family in range(4)
    ):
        raise SystemExit("fixture lacks a nonqualifying record for a family")
    return parsed


def expected_strata(
    rows: list[dict[str, Any]],
    bank_sha256: str,
) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    all_ordinals = [row["ordinal"] for row in rows]
    result["uniform"] = [
        {
            "threshold": 0,
            "eligible_records": len(all_ordinals),
            "ordinals": all_ordinals,
            "sha256": stratum_digest(bank_sha256, "uniform", 0, all_ordinals),
        }
    ]
    for family_index, family in enumerate(FAMILIES[1:]):
        metric_rows = sorted(
            (
                (row["expected_metrics"][family_index], row["ordinal"])
                for row in rows
                if row["expected_metrics"][family_index] >= 0
            ),
            key=lambda item: (item[0], item[1]),
        )
        descriptors: list[dict[str, Any]] = []
        for threshold in range(BOUNDS[family] + 1):
            ordinals = [
                ordinal for metric, ordinal in metric_rows if metric <= threshold
            ]
            descriptors.append(
                {
                    "threshold": threshold,
                    "eligible_records": len(ordinals),
                    "ordinals": ordinals,
                    "sha256": stratum_digest(
                        bank_sha256, family, threshold, ordinals
                    ),
                }
            )
        result[family] = descriptors

    required_empty = (
        ("endzone-maxdist", 1),
        ("pickup-maxdist", 1),
        ("postkick-maxturn", 0),
        ("pass-maxrange", 2),
    )
    for family, threshold in required_empty:
        if result[family][threshold]["eligible_records"] != 0:
            raise SystemExit(
                f"fixture must retain empty low prefix {family}={threshold}"
            )
    return result


def render_expected_header(
    rows: list[dict[str, Any]],
    strata: dict[str, list[dict[str, Any]]],
) -> str:
    lines = [
        "#ifndef BBE_TEST_STATE_BANK_FIXTURE_EXPECTED_H",
        "#define BBE_TEST_STATE_BANK_FIXTURE_EXPECTED_H",
        "",
        f"#define BBE_TEST_STATE_BANK_FIXTURE_RECORDS {len(rows)}u",
        "#define BBE_TEST_STATE_BANK_FIXTURE_FAMILIES 5u",
        "#define BBE_TEST_STATE_BANK_FIXTURE_PREFIX_CAP 26u",
        "#define BBE_TEST_STATE_BANK_FIXTURE_INELIGIBLE (-1)",
        "",
        "static const uint32_t bbe_test_fixture_source_ids[] = {",
        "    " + ", ".join(f"UINT32_C({row['source_id']})" for row in rows),
        "};",
        "static const uint32_t bbe_test_fixture_commands[] = {",
        "    " + ", ".join(f"UINT32_C({row['command']})" for row in rows),
        "};",
        "static const uint8_t bbe_test_fixture_halves[] = {",
        "    " + ", ".join(f"{row['half']}u" for row in rows),
        "};",
        "static const uint8_t bbe_test_fixture_turns[] = {",
        "    " + ", ".join(f"{row['turn']}u" for row in rows),
        "};",
        "static const int bbe_test_fixture_metrics[][4] = {",
    ]
    for row in rows:
        lines.append(
            "    {" + ", ".join(str(metric) for metric in row["expected_metrics"]) + "},"
        )
    lines.extend(
        [
            "};",
            "",
            "static const uint32_t "
            "bbe_test_fixture_prefix_counts[5][26] = {",
        ]
    )
    for family in FAMILIES:
        values = [0] * 26
        for descriptor in strata[family]:
            values[descriptor["threshold"]] = descriptor["eligible_records"]
        lines.append("    {" + ", ".join(f"{value}u" for value in values) + "},")
    lines.extend(
        [
            "};",
            "",
            "static const char "
            "bbe_test_fixture_prefix_sha256[5][26][65] = {",
        ]
    )
    for family in FAMILIES:
        values = ['""'] * 26
        for descriptor in strata[family]:
            values[descriptor["threshold"]] = c_string(descriptor["sha256"])
        lines.append("    {" + ", ".join(values) + "},")
    lines.extend(["};", "", "#endif", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bbs", type=Path, required=True)
    parser.add_argument("--expectations", type=Path, required=True)
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

    rows = parse_expectations(
        args.expectations,
        bbs=bbs,
        match_size=match_size,
        records=records,
    )
    bank_sha = sha256(bbs)
    strata = expected_strata(rows, bank_sha)

    immutable = args.out_dir / "immutable"
    active = args.out_dir / "active"
    immutable.mkdir(parents=True, exist_ok=True)
    active.mkdir(parents=True, exist_ok=True)
    immutable_bbs = immutable / "state_bank.bbs"
    if immutable_bbs != args.bbs:
        immutable_bbs.write_bytes(bbs)

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

    expected_document = {
        "bank_sha256": bank_sha,
        "families": strata,
        "records": rows,
        "schema": EXPECTED_SCHEMA,
        "strata_schema": STRATA_SCHEMA,
    }
    (args.out_dir / "state_bank_strata.expected.json").write_bytes(
        canonical_json(expected_document)
    )
    (args.out_dir / "state_bank_fixture.expected.h").write_text(
        render_expected_header(rows, strata), encoding="ascii"
    )

    # Paths are intentionally relative to the repository root, where make
    # executes the integration binary.
    def relative(path: Path) -> str:
        return path.as_posix()

    identity_fields: dict[str, str | int] = {
        "contract_schema": "bloodbowl-state-bank-training-contract-v1",
        "producer_schema": "bloodbowl-state-bank-producer-v1",
        "authorization_schema": "bloodbowl-state-bank-authorization-v1",
        "strata_schema": STRATA_SCHEMA,
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
        "strata_schema": "STRATA_SCHEMA",
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
