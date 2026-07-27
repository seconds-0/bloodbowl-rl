#!/usr/bin/env python3
"""Validate and install the fail-closed Blood Bowl state-bank contract.

This module deliberately separates parsing from authorization.  The schemas
and byte-level reconciliation are implemented now, but the production
producer allowlist is the literal empty set.  Consequently, no bank can be
installed for training by this tranche.  There is no command-line or
environment-variable escape hatch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import struct
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Collection, Mapping, NoReturn


FILTER_SCHEMA = "bloodbowl-strict-filter-manifest-v2"
PRODUCER_SCHEMA = "bloodbowl-state-bank-producer-v1"
TRAINING_SCHEMA = "bloodbowl-state-bank-training-contract-v1"
AUTHORIZATION_SCHEMA = "bloodbowl-state-bank-authorization-v1"
VALIDATION_SCHEMA = "bloodbowl-state-bank-validation-v2"
STRATA_SCHEMA = "bloodbowl-legacy-state-bank-strata-v1"
PRODUCTION_AUTHORIZED_PRODUCER_KINDS: frozenset[str] = frozenset()

BBS_HEADER = struct.Struct("<4sIII")
BBS_META = struct.Struct("<IIBB2s")
BBS_MAGIC = b"BBS1"
BBS_VERSION = 1
MAX_BBS_BYTES = 256 << 20
MAX_MANIFEST_BYTES = 4 << 20
MAX_RECORDS = 1_000_000
MAX_PATH_BYTES = 4096
MAX_ENVIRONMENT_SOURCE_FILES = 100_000
AUTHORED_SOURCE_NAMESPACE = 0xA0000000
AUTHORED_SOURCE_MASK = 0xF0000000

SHA256_RE = re.compile(r"[0-9a-f]{64}")
FINGERPRINT_RE = re.compile(r"0x[0-9a-f]{8}")
CANONICAL_POSITIVE_DECIMAL_RE = re.compile(r"[1-9][0-9]*")
DEFINE_STRING_RE = re.compile(r'^#define[ \t]+([A-Z][A-Z0-9_]*)[ \t]+"([^"]*)"[ \t]*$')
DEFINE_INTEGER_RE = re.compile(
    r"^#define[ \t]+([A-Z][A-Z0-9_]*)[ \t]+([0-9]+)(?:[uUlL]*)[ \t]*$"
)

STATE_BANK_MACROS = (
    "PUFFER_STATE_BANK_CONTRACT_SCHEMA",
    "PUFFER_STATE_BANK_PRODUCER_SCHEMA",
    "PUFFER_STATE_BANK_AUTHORIZATION_SCHEMA",
    "PUFFER_STATE_BANK_STRATA_SCHEMA",
    "PUFFER_STATE_BANK_COMPILED_KIND",
    "PUFFER_STATE_BANK_KIND_NAME",
    "PUFFER_STATE_BANK_RULESET",
    "PUFFER_STATE_BANK_BBS_SHA256",
    "PUFFER_STATE_BANK_PRODUCER_MANIFEST_SHA256",
    "PUFFER_STATE_BANK_TRAINING_CONTRACT_SHA256",
    "PUFFER_STATE_BANK_PRODUCER_ENGINE_SOURCE_SHA256",
    "PUFFER_STATE_BANK_LOADER_ENGINE_SOURCE_SHA256",
    "PUFFER_STATE_BANK_BBS_BYTES",
    "PUFFER_STATE_BANK_RECORDS",
    "PUFFER_STATE_BANK_BBS_VERSION",
    "PUFFER_STATE_BANK_MATCH_SIZE",
    "PUFFER_STATE_BANK_ENGINE_FINGERPRINT",
    "PUFFER_STATE_BANK_CONTRACT_IDENTITY",
    "PUFFER_STATE_BANK_BBS_PATH",
    "PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH",
    "PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH",
)

BASE_BUILD_MACROS = (
    "PUFFER_EXACT_ACTION_SOURCE_HASH",
    "PUFFER_ENV_SOURCE_HASH",
    "PUFFER_OBSERVATION_ABI",
    "PUFFER_OBSERVATION_VERSION",
    "PUFFER_ACTION_ABI",
)

NO_BANK_STATE_FIELDS: dict[str, str | int] = {
    "contract_schema": "none",
    "producer_schema": "none",
    "authorization_schema": "none",
    "strata_schema": STRATA_SCHEMA,
    "kind_value": 0,
    "kind": "none",
    "ruleset": "none",
    "bank_sha256": "unused",
    "producer_manifest_sha256": "unused",
    "training_contract_sha256": "unused",
    "producer_engine_source_sha256": "unused",
    "loader_engine_source_sha256": "unused",
    "bytes": 0,
    "records": 0,
    "bbs_version": 0,
    "match_size": 0,
    "engine_fingerprint": 0,
    "contract_identity": "none",
    "bank_path": "unused",
    "producer_manifest_path": "unused",
    "training_contract_path": "unused",
}

STATE_FIELD_TO_MACRO = {
    "contract_schema": "PUFFER_STATE_BANK_CONTRACT_SCHEMA",
    "producer_schema": "PUFFER_STATE_BANK_PRODUCER_SCHEMA",
    "authorization_schema": "PUFFER_STATE_BANK_AUTHORIZATION_SCHEMA",
    "strata_schema": "PUFFER_STATE_BANK_STRATA_SCHEMA",
    "kind_value": "PUFFER_STATE_BANK_COMPILED_KIND",
    "kind": "PUFFER_STATE_BANK_KIND_NAME",
    "ruleset": "PUFFER_STATE_BANK_RULESET",
    "bank_sha256": "PUFFER_STATE_BANK_BBS_SHA256",
    "producer_manifest_sha256": "PUFFER_STATE_BANK_PRODUCER_MANIFEST_SHA256",
    "training_contract_sha256": "PUFFER_STATE_BANK_TRAINING_CONTRACT_SHA256",
    "producer_engine_source_sha256": "PUFFER_STATE_BANK_PRODUCER_ENGINE_SOURCE_SHA256",
    "loader_engine_source_sha256": "PUFFER_STATE_BANK_LOADER_ENGINE_SOURCE_SHA256",
    "bytes": "PUFFER_STATE_BANK_BBS_BYTES",
    "records": "PUFFER_STATE_BANK_RECORDS",
    "bbs_version": "PUFFER_STATE_BANK_BBS_VERSION",
    "match_size": "PUFFER_STATE_BANK_MATCH_SIZE",
    "engine_fingerprint": "PUFFER_STATE_BANK_ENGINE_FINGERPRINT",
    "contract_identity": "PUFFER_STATE_BANK_CONTRACT_IDENTITY",
    "bank_path": "PUFFER_STATE_BANK_BBS_PATH",
    "producer_manifest_path": "PUFFER_STATE_BANK_PRODUCER_MANIFEST_PATH",
    "training_contract_path": "PUFFER_STATE_BANK_TRAINING_CONTRACT_PATH",
}

MODULE_STATE_FIELD_NAMES = {
    "contract_schema": "state_bank_contract_schema",
    "producer_schema": "state_bank_producer_schema",
    "authorization_schema": "state_bank_authorization_schema",
    "strata_schema": "state_bank_strata_schema",
    "kind_value": "state_bank_kind",
    "kind": "state_bank_kind_name",
    "ruleset": "state_bank_ruleset",
    "bank_sha256": "state_bank_bbs_sha256",
    "producer_manifest_sha256": "state_bank_producer_manifest_sha256",
    "training_contract_sha256": "state_bank_training_contract_sha256",
    "producer_engine_source_sha256": "state_bank_producer_engine_source_sha256",
    "loader_engine_source_sha256": "state_bank_loader_engine_source_sha256",
    "bytes": "state_bank_bbs_bytes",
    "records": "state_bank_records",
    "bbs_version": "state_bank_bbs_version",
    "match_size": "state_bank_match_size",
    "engine_fingerprint": "state_bank_engine_fingerprint",
    "contract_identity": "state_bank_contract_identity",
    "bank_path": "state_bank_bbs_path",
    "producer_manifest_path": "state_bank_producer_manifest_path",
    "training_contract_path": "state_bank_training_contract_path",
}

LAUNCHER_CONTRACT_FIELDS = (
    "contract_schema",
    "producer_schema",
    "kind",
    "kind_value",
    "ruleset",
    "bank_sha256",
    "producer_manifest_sha256",
    "training_contract_sha256",
    "producer_engine_source_sha256",
    "loader_engine_source_sha256",
    "records",
    "bytes",
    "environment_source_sha256",
    "strata_schema",
    "strata_family",
    "strata_threshold",
    "strata_eligible_records",
    "strata_sha256",
)

SELECTOR_FAMILY_BOUNDS = {
    "uniform": 0,
    "endzone-maxdist": 25,
    "pickup-maxdist": 25,
    "postkick-maxturn": 8,
    "pass-maxrange": 25,
}


class StateBankContractError(RuntimeError):
    """A stable, fail-closed state-bank contract failure."""

    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


def _fail(code: str, detail: str) -> NoReturn:
    raise StateBankContractError(code, detail)


@dataclass(frozen=True)
class _DestinationTemporaryBinding:
    descriptor: int
    device: int
    inode: int


def _require_exact_keys(
    value: Any, expected: Collection[str], location: str
) -> dict[str, Any]:
    if not isinstance(value, dict):
        _fail("SCHEMA_TYPE", f"{location} must be an object")
    expected_set = set(expected)
    observed = set(value)
    missing = sorted(expected_set - observed)
    unknown = sorted(observed - expected_set)
    if missing or unknown:
        _fail(
            "SCHEMA_KEYS",
            f"{location} keys differ; missing={missing}, unknown={unknown}",
        )
    return value


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            _fail("JSON_DUPLICATE_KEY", f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def parse_json_bytes(payload: bytes, label: str) -> dict[str, Any]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        _fail("JSON_UTF8", f"{label} is not UTF-8: {exc}")
    if text.startswith("\ufeff"):
        _fail("JSON_UTF8", f"{label} must not contain a UTF-8 BOM")
    try:
        value = json.loads(
            text,
            object_pairs_hook=_json_pairs,
            parse_constant=lambda token: _fail(
                "JSON_NONFINITE", f"{label} contains {token}"
            ),
        )
    except StateBankContractError:
        raise
    except (json.JSONDecodeError, UnicodeError) as exc:
        _fail("JSON_SYNTAX", f"{label} is malformed JSON: {exc}")
    if not isinstance(value, dict):
        _fail("SCHEMA_TYPE", f"{label} root must be an object")
    return value


def _require_literal(value: Any, expected: Any, location: str) -> None:
    if type(value) is not type(expected) or value != expected:
        _fail("SCHEMA_VALUE", f"{location} must equal {expected!r}")


def _require_nonempty_string(value: Any, location: str) -> str:
    if not isinstance(value, str) or not value:
        _fail("SCHEMA_TYPE", f"{location} must be a nonempty string")
    return value


def _require_sha256(value: Any, location: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        _fail(
            "SHA256_FORMAT",
            f"{location} must be 64 lowercase hexadecimal characters",
        )
    return value


def _require_positive_int(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _fail("SCHEMA_INTEGER", f"{location} must be a positive JSON integer")
    return value


def _require_nonnegative_int(value: Any, location: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        _fail(
            "SCHEMA_INTEGER",
            f"{location} must be a nonnegative JSON integer",
        )
    return value


def _require_string_array(value: Any, location: str) -> list[str]:
    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, str) or not item for item in value)
    ):
        _fail(
            "SCHEMA_TYPE",
            f"{location} must be a nonempty array of nonempty strings",
        )
    return value


def _validate_format(value: Any, location: str) -> dict[str, Any]:
    result = _require_exact_keys(
        value,
        ("magic", "version", "match_size", "engine_fingerprint"),
        location,
    )
    _require_literal(result["magic"], "BBS1", f"{location}.magic")
    _require_literal(result["version"], 1, f"{location}.version")
    _require_positive_int(result["match_size"], f"{location}.match_size")
    fingerprint = result["engine_fingerprint"]
    if (
        not isinstance(fingerprint, str)
        or FINGERPRINT_RE.fullmatch(fingerprint) is None
        or fingerprint == "0x00000000"
    ):
        _fail(
            "FINGERPRINT_FORMAT",
            f"{location}.engine_fingerprint must be canonical nonzero hex",
        )
    return result


def _validate_bank(value: Any, location: str) -> dict[str, Any]:
    result = _require_exact_keys(
        value, ("sha256", "bytes", "records", "format"), location
    )
    _require_sha256(result["sha256"], f"{location}.sha256")
    byte_count = _require_positive_int(result["bytes"], f"{location}.bytes")
    records = _require_positive_int(result["records"], f"{location}.records")
    if byte_count > MAX_BBS_BYTES:
        _fail("BBS_TOO_LARGE", f"{location}.bytes exceeds {MAX_BBS_BYTES}")
    if records > MAX_RECORDS:
        _fail("BBS_TOO_MANY_RECORDS", f"{location}.records exceeds {MAX_RECORDS}")
    fmt = _validate_format(result["format"], f"{location}.format")
    expected = BBS_HEADER.size + records * (BBS_META.size + fmt["match_size"])
    if expected != byte_count:
        _fail(
            "BBS_SIZE_COUNT",
            f"{location}.bytes is {byte_count}, expected {expected}",
        )
    return result


def _validate_producer_envelope(
    value: Any, location: str = "producer_manifest"
) -> dict[str, Any]:
    result = _require_exact_keys(
        value,
        (
            "schema",
            "artifact_role",
            "bank_kind",
            "ruleset",
            "training_eligible",
            "bank",
            "producer",
        ),
        location,
    )
    _require_literal(result["schema"], PRODUCER_SCHEMA, f"{location}.schema")
    if result["artifact_role"] not in (
        "analysis-only",
        "structural-proof",
        "training-bank",
    ):
        _fail("SCHEMA_VALUE", f"{location}.artifact_role is unknown")
    if result["bank_kind"] not in ("strict-replay", "authored-scenario"):
        _fail("SCHEMA_VALUE", f"{location}.bank_kind is unknown")
    _require_literal(result["ruleset"], "BB2025", f"{location}.ruleset")
    if type(result["training_eligible"]) is not bool:
        _fail("SCHEMA_TYPE", f"{location}.training_eligible must be boolean")
    _validate_bank(result["bank"], f"{location}.bank")
    producer = _require_exact_keys(
        result["producer"],
        ("kind", "producer_engine_source_sha256"),
        f"{location}.producer",
    )
    _require_nonempty_string(producer["kind"], f"{location}.producer.kind")
    engine_hash = producer["producer_engine_source_sha256"]
    if engine_hash is not None:
        _require_sha256(
            engine_hash,
            f"{location}.producer.producer_engine_source_sha256",
        )
    return result


def _validate_histogram(value: Any, records: int, location: str) -> None:
    if not isinstance(value, dict) or not value:
        _fail("SCHEMA_TYPE", f"{location} must be a nonempty object")
    total = 0
    for key, count in value.items():
        if (
            not isinstance(key, str)
            or CANONICAL_POSITIVE_DECIMAL_RE.fullmatch(key) is None
        ):
            _fail("SCHEMA_VALUE", f"{location} has noncanonical key {key!r}")
        total += _require_positive_int(count, f"{location}.{key}")
    if total != records:
        _fail(
            "MANIFEST_RECONCILE",
            f"{location} totals {total}, expected {records}",
        )


def _validate_filter_file(
    value: Any, location: str, *, selected: bool
) -> dict[str, Any]:
    keys = ("path", "bytes", "sha256", "records", "replay_ids")
    if selected:
        keys += ("half_histogram", "turn_histogram")
    result = _require_exact_keys(value, keys, location)
    _require_nonempty_string(result["path"], f"{location}.path")
    _require_positive_int(result["bytes"], f"{location}.bytes")
    _require_sha256(result["sha256"], f"{location}.sha256")
    records = _require_positive_int(result["records"], f"{location}.records")
    _require_positive_int(result["replay_ids"], f"{location}.replay_ids")
    if selected:
        _validate_histogram(
            result["half_histogram"], records, f"{location}.half_histogram"
        )
        _validate_histogram(
            result["turn_histogram"], records, f"{location}.turn_histogram"
        )
    return result


def validate_filter_manifest(value: Any) -> dict[str, Any]:
    """Validate the complete closed strict-filter v2 analysis manifest."""

    result = _require_exact_keys(
        value,
        (
            "schema",
            "schema_version",
            "tool",
            "command",
            "format",
            "input",
            "allowlist",
            "output",
            "selected_ids",
            "excluded",
            "limitations",
            "artifact",
        ),
        "producer_manifest",
    )
    _require_literal(result["schema"], FILTER_SCHEMA, "producer_manifest.schema")
    _require_literal(result["schema_version"], 2, "producer_manifest.schema_version")
    tool = _require_exact_keys(
        result["tool"], ("path", "sha256"), "producer_manifest.tool"
    )
    _require_nonempty_string(tool["path"], "producer_manifest.tool.path")
    _require_sha256(tool["sha256"], "producer_manifest.tool.sha256")
    _require_string_array(result["command"], "producer_manifest.command")
    fmt = _require_exact_keys(
        result["format"],
        (
            "magic",
            "version",
            "match_size",
            "engine_fingerprint",
            "record_count_is_file_size_derived",
        ),
        "producer_manifest.format",
    )
    _require_literal(
        fmt["record_count_is_file_size_derived"],
        True,
        "producer_manifest.format.record_count_is_file_size_derived",
    )
    normalized_fmt = _validate_format(
        {
            key: fmt[key]
            for key in ("magic", "version", "match_size", "engine_fingerprint")
        },
        "producer_manifest.format",
    )
    input_file = _validate_filter_file(
        result["input"], "producer_manifest.input", selected=True
    )
    output_file = _validate_filter_file(
        result["output"], "producer_manifest.output", selected=True
    )
    allowlist = _require_exact_keys(
        result["allowlist"],
        (
            "path",
            "bytes",
            "sha256",
            "ids_total",
            "ids_matched",
            "ids_unmatched",
        ),
        "producer_manifest.allowlist",
    )
    _require_nonempty_string(allowlist["path"], "producer_manifest.allowlist.path")
    _require_positive_int(allowlist["bytes"], "producer_manifest.allowlist.bytes")
    _require_sha256(allowlist["sha256"], "producer_manifest.allowlist.sha256")
    for key in ("ids_total", "ids_matched"):
        _require_positive_int(allowlist[key], f"producer_manifest.allowlist.{key}")
    _require_nonnegative_int(
        allowlist["ids_unmatched"],
        "producer_manifest.allowlist.ids_unmatched",
    )
    selected_ids = _require_exact_keys(
        result["selected_ids"],
        ("path", "bytes", "sha256", "count"),
        "producer_manifest.selected_ids",
    )
    _require_nonempty_string(
        selected_ids["path"], "producer_manifest.selected_ids.path"
    )
    _require_positive_int(selected_ids["bytes"], "producer_manifest.selected_ids.bytes")
    _require_sha256(selected_ids["sha256"], "producer_manifest.selected_ids.sha256")
    _require_positive_int(selected_ids["count"], "producer_manifest.selected_ids.count")
    excluded = _require_exact_keys(
        result["excluded"],
        ("records", "replay_ids", "replay_id_values"),
        "producer_manifest.excluded",
    )
    _require_nonnegative_int(excluded["records"], "producer_manifest.excluded.records")
    _require_nonnegative_int(
        excluded["replay_ids"], "producer_manifest.excluded.replay_ids"
    )
    replay_values = excluded["replay_id_values"]
    if not isinstance(replay_values, list):
        _fail(
            "SCHEMA_TYPE",
            "producer_manifest.excluded.replay_id_values must be an array",
        )
    previous = 0
    for index, replay_id in enumerate(replay_values):
        current = _require_positive_int(
            replay_id,
            f"producer_manifest.excluded.replay_id_values[{index}]",
        )
        if current > 0xFFFFFFFF or current <= previous:
            _fail(
                "SCHEMA_VALUE",
                "producer_manifest.excluded.replay_id_values must be strictly "
                "increasing uint32 values",
            )
        previous = current
    _require_string_array(result["limitations"], "producer_manifest.limitations")
    artifact = _validate_producer_envelope(
        result["artifact"], "producer_manifest.artifact"
    )
    _require_literal(
        artifact["artifact_role"],
        "analysis-only",
        "producer_manifest.artifact.artifact_role",
    )
    _require_literal(
        artifact["bank_kind"],
        "strict-replay",
        "producer_manifest.artifact.bank_kind",
    )
    _require_literal(
        artifact["training_eligible"],
        False,
        "producer_manifest.artifact.training_eligible",
    )
    _require_literal(
        artifact["producer"]["kind"],
        "strict-bb2025-filter-v2",
        "producer_manifest.artifact.producer.kind",
    )
    _require_literal(
        artifact["producer"]["producer_engine_source_sha256"],
        None,
        "producer_manifest.artifact.producer.producer_engine_source_sha256",
    )

    expected_input_bytes = BBS_HEADER.size + input_file["records"] * (
        BBS_META.size + normalized_fmt["match_size"]
    )
    expected_output_bytes = BBS_HEADER.size + output_file["records"] * (
        BBS_META.size + normalized_fmt["match_size"]
    )
    checks = (
        (input_file["bytes"], expected_input_bytes, "input bytes"),
        (output_file["bytes"], expected_output_bytes, "output bytes"),
        (
            input_file["records"],
            output_file["records"] + excluded["records"],
            "record partition",
        ),
        (
            input_file["replay_ids"],
            output_file["replay_ids"] + excluded["replay_ids"],
            "replay-ID partition",
        ),
        (
            len(replay_values),
            excluded["replay_ids"],
            "excluded replay-ID values",
        ),
        (
            allowlist["ids_total"],
            allowlist["ids_matched"] + allowlist["ids_unmatched"],
            "allowlist partition",
        ),
        (
            allowlist["ids_matched"],
            selected_ids["count"],
            "selected-ID count",
        ),
        (
            output_file["replay_ids"],
            selected_ids["count"],
            "output replay-ID count",
        ),
        (artifact["bank"]["bytes"], output_file["bytes"], "artifact bytes"),
        (artifact["bank"]["records"], output_file["records"], "artifact records"),
        (
            artifact["bank"]["sha256"],
            output_file["sha256"],
            "artifact SHA-256",
        ),
        (artifact["bank"]["format"], normalized_fmt, "artifact format"),
    )
    for observed, expected, label in checks:
        if observed != expected:
            _fail(
                "MANIFEST_RECONCILE",
                f"producer_manifest {label} mismatch: {observed!r} != " f"{expected!r}",
            )
    return result


def parse_producer_manifest(payload: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    root = parse_json_bytes(payload, "producer manifest")
    if root.get("schema") == FILTER_SCHEMA:
        validated = validate_filter_manifest(root)
        return validated, validated["artifact"]
    if root.get("schema") == PRODUCER_SCHEMA:
        return root, _validate_producer_envelope(root)
    _fail("PRODUCER_SCHEMA", "unknown producer-manifest schema")


def validate_training_contract(value: Any) -> dict[str, Any]:
    result = _require_exact_keys(
        value,
        (
            "schema",
            "artifact_role",
            "bank_kind",
            "ruleset",
            "training_eligible",
            "bank",
            "producer_manifest",
            "loader",
            "authorization",
        ),
        "training_contract",
    )
    _require_literal(result["schema"], TRAINING_SCHEMA, "training_contract.schema")
    _require_literal(
        result["artifact_role"],
        "training-bank",
        "training_contract.artifact_role",
    )
    _require_literal(
        result["bank_kind"], "strict-replay", "training_contract.bank_kind"
    )
    _require_literal(result["ruleset"], "BB2025", "training_contract.ruleset")
    _require_literal(
        result["training_eligible"],
        True,
        "training_contract.training_eligible",
    )
    _validate_bank(result["bank"], "training_contract.bank")
    producer = _require_exact_keys(
        result["producer_manifest"],
        ("sha256", "schema", "producer_engine_source_sha256"),
        "training_contract.producer_manifest",
    )
    _require_sha256(producer["sha256"], "training_contract.producer_manifest.sha256")
    _require_literal(
        producer["schema"],
        PRODUCER_SCHEMA,
        "training_contract.producer_manifest.schema",
    )
    _require_sha256(
        producer["producer_engine_source_sha256"],
        "training_contract.producer_manifest.producer_engine_source_sha256",
    )
    loader = _require_exact_keys(
        result["loader"],
        ("engine_source_sha256",),
        "training_contract.loader",
    )
    _require_sha256(
        loader["engine_source_sha256"],
        "training_contract.loader.engine_source_sha256",
    )
    authorization = _require_exact_keys(
        result["authorization"],
        ("schema", "decision"),
        "training_contract.authorization",
    )
    _require_literal(
        authorization["schema"],
        AUTHORIZATION_SCHEMA,
        "training_contract.authorization.schema",
    )
    _require_nonempty_string(
        authorization["decision"], "training_contract.authorization.decision"
    )
    return result


def read_bounded_file(path: Path, limit: int, label: str) -> bytes:
    """Read one exact regular file without following the final symlink."""

    encoded = os.fsencode(path)
    if len(encoded) + 1 > MAX_PATH_BYTES:
        _fail("PATH_TOO_LONG", f"{label} path exceeds {MAX_PATH_BYTES} bytes")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NONBLOCK", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _fail("FILE_OPEN", f"cannot open {label} {path}: {exc}")
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            _fail("FILE_TYPE", f"{label} is not a regular file")
        if info.st_size < 0 or info.st_size > limit:
            _fail("FILE_TOO_LARGE", f"{label} exceeds {limit} bytes")
        chunks: list[bytes] = []
        remaining = info.st_size
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                _fail("FILE_SHORT_READ", f"{label} became shorter while reading")
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail("FILE_GREW", f"{label} grew while reading")
        after = os.fstat(descriptor)
        if (
            after.st_dev != info.st_dev
            or after.st_ino != info.st_ino
            or after.st_size != info.st_size
        ):
            _fail("FILE_CHANGED", f"{label} changed while reading")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_engine_source_entries(root: Path) -> list[tuple[bytes, bytes]]:
    """Read one race-checked image of the engine source tree."""

    root = Path(root)
    canonical_alias = root / "engine/src/bb"
    if (
        not canonical_alias.is_symlink()
        or os.readlink(canonical_alias) != "../include/bb"
    ):
        _fail(
            "ENGINE_SOURCE_TREE",
            "engine/src/bb must be the exact ../include/bb convenience symlink",
        )
    entries: list[tuple[bytes, bytes]] = []
    seen: set[bytes] = set()
    for relative_root in (Path("engine/include/bb"), Path("engine/src")):
        directory = root / relative_root
        if not directory.is_dir() or directory.is_symlink():
            _fail("ENGINE_SOURCE_TREE", f"missing real directory {directory}")
        for current, directories, filenames in os.walk(
            directory, topdown=True, followlinks=False
        ):
            current_path = Path(current)
            for name in list(directories):
                child = current_path / name
                if child.is_symlink():
                    if (
                        child == canonical_alias
                        and os.readlink(child) == "../include/bb"
                    ):
                        # This tracked compiler-convenience alias is the sole
                        # exception: its real target is already hashed once as
                        # engine/include/bb.  Removing it from os.walk also
                        # prevents duplicate logical content.
                        directories.remove(name)
                        continue
                    _fail("ENGINE_SOURCE_TREE", f"symlink is forbidden: {child}")
            for name in filenames:
                child = current_path / name
                if child.is_symlink():
                    _fail("ENGINE_SOURCE_TREE", f"symlink is forbidden: {child}")
                info = child.stat(follow_symlinks=False)
                if not stat.S_ISREG(info.st_mode):
                    _fail(
                        "ENGINE_SOURCE_TREE",
                        f"nonregular engine source is forbidden: {child}",
                    )
                relative = child.relative_to(root).as_posix()
                try:
                    relative_bytes = relative.encode("utf-8")
                except UnicodeEncodeError as exc:
                    _fail(
                        "ENGINE_SOURCE_TREE",
                        f"invalid UTF-8 engine path {relative!r}: {exc}",
                    )
                if relative_bytes in seen:
                    _fail(
                        "ENGINE_SOURCE_TREE",
                        f"duplicate logical engine path {relative!r}",
                    )
                seen.add(relative_bytes)
                entries.append(
                    (
                        relative_bytes,
                        read_bounded_file(child, MAX_BBS_BYTES, "engine source file"),
                    )
                )
    if not entries:
        _fail("ENGINE_SOURCE_TREE", "engine source tree is empty")
    return entries


def _engine_source_entries_sha256(
    entries: Collection[tuple[bytes, bytes]],
) -> str:
    digest = hashlib.sha256(b"bloodbowl-engine-source-v1\0")
    for relative_bytes, payload in sorted(entries, key=lambda item: item[0]):
        digest.update(struct.pack("<Q", len(relative_bytes)))
        digest.update(relative_bytes)
        digest.update(struct.pack("<Q", len(payload)))
        digest.update(payload)
    return digest.hexdigest()


def engine_source_sha256(root: str | Path) -> str:
    """Hash the exact engine source tree using the v1 binary framing."""

    return _engine_source_entries_sha256(_read_engine_source_entries(Path(root)))


def _validate_environment_relative_path(relative: bytes) -> None:
    """Reject names whose ``sha256sum`` presentation is not canonical."""

    if (
        not relative
        or relative.startswith(b"/")
        or b"\\" in relative
        or b"\n" in relative
        or b"\r" in relative
        or b"\0" in relative
    ):
        _fail(
            "ENVIRONMENT_SOURCE_TREE",
            f"unsafe environment source path {relative!r}",
        )
    components = relative.split(b"/")
    if any(component in (b"", b".", b"..") for component in components):
        _fail(
            "ENVIRONMENT_SOURCE_TREE",
            f"noncanonical environment source path {relative!r}",
        )
    if len(b"./" + relative) > MAX_PATH_BYTES:
        _fail(
            "ENVIRONMENT_SOURCE_TREE",
            f"environment source path exceeds {MAX_PATH_BYTES} bytes",
        )


def _read_environment_source_file(
    path: bytes,
    expected: os.stat_result,
    relative: bytes,
) -> bytes:
    """Read a regular ``find -L`` target and reconcile the followed inode."""

    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        _fail(
            "ENVIRONMENT_SOURCE_TREE",
            f"cannot open environment source file {relative!r}: {exc}",
        )
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or before.st_dev != expected.st_dev
            or before.st_ino != expected.st_ino
            or before.st_size != expected.st_size
            or before.st_mtime_ns != expected.st_mtime_ns
            or before.st_ctime_ns != expected.st_ctime_ns
        ):
            _fail(
                "ENVIRONMENT_SOURCE_TREE",
                f"environment source path changed before read: {relative!r}",
            )
        if before.st_size > MAX_BBS_BYTES:
            _fail(
                "ENVIRONMENT_SOURCE_TREE",
                f"environment source file exceeds {MAX_BBS_BYTES} bytes: "
                f"{relative!r}",
            )
        chunks: list[bytes] = []
        remaining = before.st_size
        while remaining:
            chunk = os.read(descriptor, min(1 << 20, remaining))
            if not chunk:
                _fail(
                    "ENVIRONMENT_SOURCE_TREE",
                    f"environment source file became shorter: {relative!r}",
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        if os.read(descriptor, 1):
            _fail(
                "ENVIRONMENT_SOURCE_TREE",
                f"environment source file grew while reading: {relative!r}",
            )
        after = os.fstat(descriptor)
        try:
            path_after = os.stat(path, follow_symlinks=True)
        except OSError as exc:
            _fail(
                "ENVIRONMENT_SOURCE_TREE",
                f"environment source path vanished after read "
                f"{relative!r}: {exc}",
            )
        identities = (
            (
                before.st_dev,
                before.st_ino,
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ),
            (
                after.st_dev,
                after.st_ino,
                after.st_size,
                after.st_mtime_ns,
                after.st_ctime_ns,
            ),
            (
                path_after.st_dev,
                path_after.st_ino,
                path_after.st_size,
                path_after.st_mtime_ns,
                path_after.st_ctime_ns,
            ),
        )
        if identities[0] != identities[1] or identities[0] != identities[2]:
            _fail(
                "ENVIRONMENT_SOURCE_TREE",
                f"environment source path changed while reading: {relative!r}",
            )
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_environment_source_entries(
    environment_root: str | Path,
) -> list[tuple[bytes, bytes]]:
    """Read the legacy ``find -L`` environment closure without shell escaping."""

    root = Path(environment_root)
    if not root.is_dir() or root.is_symlink():
        _fail(
            "ENVIRONMENT_SOURCE_TREE",
            f"environment root must be a real directory: {root}",
        )
    root_bytes = os.fsencode(os.path.abspath(root))
    entries: list[tuple[bytes, bytes]] = []
    seen_paths: set[bytes] = set()

    try:
        root_info = os.stat(root_bytes, follow_symlinks=True)
    except OSError as exc:
        _fail(
            "ENVIRONMENT_SOURCE_TREE",
            f"cannot stat environment root {root}: {exc}",
        )

    def walk(
        directory: bytes,
        logical_components: tuple[bytes, ...],
        ancestor_directories: frozenset[tuple[int, int]],
    ) -> None:
        try:
            children = list(os.scandir(directory))
        except OSError as exc:
            _fail(
                "ENVIRONMENT_SOURCE_TREE",
                f"cannot enumerate environment source directory "
                f"{os.fsdecode(directory)!r}: {exc}",
            )
        for child in children:
            name = child.name
            if not isinstance(name, bytes):
                name = os.fsencode(name)
            relative = b"/".join((*logical_components, name))
            _validate_environment_relative_path(relative)
            try:
                info = child.stat(follow_symlinks=True)
            except OSError as exc:
                _fail(
                    "ENVIRONMENT_SOURCE_TREE",
                    f"cannot stat environment source path {relative!r}: {exc}",
                )
            identity = (info.st_dev, info.st_ino)
            if stat.S_ISDIR(info.st_mode):
                if identity in ancestor_directories:
                    _fail(
                        "ENVIRONMENT_SOURCE_TREE",
                        f"directory symlink cycle at {relative!r}",
                    )
                walk(
                    child.path,
                    (*logical_components, name),
                    ancestor_directories | frozenset((identity,)),
                )
                continue
            if not stat.S_ISREG(info.st_mode):
                _fail(
                    "ENVIRONMENT_SOURCE_TREE",
                    f"nonregular environment source is forbidden: {relative!r}",
                )
            if relative in (b".content_hash", b"state_bank_build.h"):
                continue
            if relative in seen_paths:
                _fail(
                    "ENVIRONMENT_SOURCE_TREE",
                    f"duplicate logical environment path {relative!r}",
                )
            seen_paths.add(relative)
            if len(entries) >= MAX_ENVIRONMENT_SOURCE_FILES:
                _fail(
                    "ENVIRONMENT_SOURCE_TREE",
                    "environment source file count exceeds "
                    f"{MAX_ENVIRONMENT_SOURCE_FILES}",
                )
            entries.append(
                (
                    b"./" + relative,
                    _read_environment_source_file(
                        child.path,
                        info,
                        relative,
                    ),
                )
            )

    walk(
        root_bytes,
        (),
        frozenset(((root_info.st_dev, root_info.st_ino),)),
    )
    if not entries:
        _fail("ENVIRONMENT_SOURCE_TREE", "environment source tree is empty")
    return entries


def _environment_source_entries_sha256(
    entries: Collection[tuple[bytes, bytes]],
) -> str:
    """Reproduce ``find -L | sort -z | sha256sum | sha256sum`` exactly."""

    digest = hashlib.sha256()
    for relative, payload in sorted(entries, key=lambda item: item[0]):
        digest.update(hashlib.sha256(payload).hexdigest().encode("ascii"))
        digest.update(b"  ")
        digest.update(relative)
        digest.update(b"\n")
    return digest.hexdigest()


def environment_source_sha256(environment_root: str | Path) -> str:
    """Hash the complete dereferenced Blood Bowl environment source closure."""

    return _environment_source_entries_sha256(
        _read_environment_source_entries(environment_root)
    )


def inspect_bbs(payload: bytes, *, validate_metadata: bool) -> dict[str, Any]:
    if len(payload) < BBS_HEADER.size:
        _fail("BBS_HEADER", "truncated BBS1 header")
    magic, version, match_size, fingerprint = BBS_HEADER.unpack_from(payload)
    if magic != BBS_MAGIC:
        _fail("BBS_MAGIC", f"bad BBS magic {magic!r}")
    if version != BBS_VERSION:
        _fail("BBS_VERSION", f"unsupported BBS version {version}")
    if match_size <= 0:
        _fail("BBS_MATCH_SIZE", "BBS match size must be positive")
    if fingerprint == 0:
        _fail("BBS_FINGERPRINT", "BBS engine fingerprint must be nonzero")
    record_size = BBS_META.size + match_size
    body_bytes = len(payload) - BBS_HEADER.size
    if body_bytes % record_size:
        _fail("BBS_PARTIAL_RECORD", "BBS has a partial or trailing record")
    records = body_bytes // record_size
    if records <= 0:
        _fail("BBS_EMPTY", "BBS contains no records")
    if records > MAX_RECORDS:
        _fail("BBS_TOO_MANY_RECORDS", f"BBS exceeds {MAX_RECORDS} records")
    if validate_metadata:
        offset = BBS_HEADER.size
        for index in range(records):
            source_id, _command, half, turn, padding = BBS_META.unpack_from(
                payload, offset
            )
            if source_id == 0:
                _fail("BBS_METADATA", f"record {index} has zero source ID")
            if source_id & AUTHORED_SOURCE_MASK == AUTHORED_SOURCE_NAMESPACE:
                _fail(
                    "BBS_AUTHORED_NAMESPACE",
                    f"strict record {index} uses authored source namespace",
                )
            if padding != b"\0\0":
                _fail("BBS_METADATA", f"record {index} has nonzero padding")
            if not 1 <= half <= 3 or not 1 <= turn <= 8:
                _fail(
                    "BBS_METADATA",
                    f"record {index} has invalid half/turn {half}/{turn}",
                )
            offset += record_size
    return {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "records": records,
        "format": {
            "magic": "BBS1",
            "version": version,
            "match_size": match_size,
            "engine_fingerprint": f"0x{fingerprint:08x}",
        },
    }


def _reconcile_request(
    *,
    kind: str,
    bank: Mapping[str, Any],
    producer_sha256: str,
    producer: Mapping[str, Any],
    training: Mapping[str, Any],
    current_loader_sha256: str,
) -> None:
    if kind == "authored-scenario":
        _fail(
            "AUTHORED_NOT_IMPLEMENTED",
            "authored state-bank publishing is not implemented",
        )
    if kind != "strict-replay":
        _fail("BANK_KIND", f"unsupported state-bank kind {kind!r}")
    if producer["bank_kind"] == "authored-scenario":
        _fail(
            "AUTHORED_NOT_IMPLEMENTED",
            "authored producer manifests are never training-authorized",
        )
    checks = (
        (producer["bank_kind"], kind, "producer bank kind"),
        (training["bank_kind"], kind, "training bank kind"),
        (producer["ruleset"], training["ruleset"], "ruleset"),
        (producer["bank"], bank, "producer/BBS identity"),
        (training["bank"], bank, "training/BBS identity"),
        (
            training["producer_manifest"]["sha256"],
            producer_sha256,
            "producer-manifest SHA-256",
        ),
        (
            training["producer_manifest"]["producer_engine_source_sha256"],
            producer["producer"]["producer_engine_source_sha256"],
            "producer engine source SHA-256",
        ),
        (
            training["loader"]["engine_source_sha256"],
            current_loader_sha256,
            "loader engine source SHA-256",
        ),
    )
    for observed, expected, label in checks:
        if observed != expected:
            _fail(
                "CONTRACT_RECONCILE",
                f"{label} mismatch: {observed!r} != {expected!r}",
            )
    if (
        producer["artifact_role"] != "training-bank"
        or producer["training_eligible"] is not True
        or producer["producer"]["producer_engine_source_sha256"] is None
    ):
        _fail(
            "PRODUCER_NOT_TRAINING_ELIGIBLE",
            "producer manifest is analysis/proof-only or lacks producer engine "
            "identity",
        )


def _validate_request(
    *,
    bank_path: Path,
    bank_sha256: str,
    producer_manifest_path: Path,
    producer_manifest_sha256: str,
    training_contract_path: Path,
    training_contract_sha256: str,
    kind: str,
    engine_root: Path,
    authorized_producer_kinds: Collection[str],
    validate_metadata: bool,
) -> dict[str, Any]:
    for value, label in (
        (bank_sha256, "bank"),
        (producer_manifest_sha256, "producer manifest"),
        (training_contract_sha256, "training contract"),
    ):
        _require_sha256(value, f"external {label} SHA-256")
    bank_payload = read_bounded_file(bank_path, MAX_BBS_BYTES, "BBS")
    producer_payload = read_bounded_file(
        producer_manifest_path, MAX_MANIFEST_BYTES, "producer manifest"
    )
    training_payload = read_bounded_file(
        training_contract_path, MAX_MANIFEST_BYTES, "training contract"
    )
    observed_hashes = (
        (hashlib.sha256(bank_payload).hexdigest(), bank_sha256, "BBS"),
        (
            hashlib.sha256(producer_payload).hexdigest(),
            producer_manifest_sha256,
            "producer manifest",
        ),
        (
            hashlib.sha256(training_payload).hexdigest(),
            training_contract_sha256,
            "training contract",
        ),
    )
    for observed, expected, label in observed_hashes:
        if observed != expected:
            _fail(
                "EXTERNAL_SHA256_MISMATCH",
                f"{label} SHA-256 {observed} != reviewed pin {expected}",
            )
    _producer_root, producer = parse_producer_manifest(producer_payload)
    training = validate_training_contract(
        parse_json_bytes(training_payload, "training contract")
    )
    bank = inspect_bbs(bank_payload, validate_metadata=False)
    current_loader_hash = engine_source_sha256(engine_root)
    _reconcile_request(
        kind=kind,
        bank=bank,
        producer_sha256=producer_manifest_sha256,
        producer=producer,
        training=training,
        current_loader_sha256=current_loader_hash,
    )
    producer_kind = producer["producer"]["kind"]
    if producer_kind not in authorized_producer_kinds:
        _fail(
            "NO_AUTHORIZED_PRODUCER",
            f"producer kind {producer_kind!r} is not production-authorized",
        )
    if validate_metadata:
        inspect_bbs(bank_payload, validate_metadata=True)
    return {
        "contract_schema": training["schema"],
        "producer_schema": producer["schema"],
        "authorization_schema": training["authorization"]["schema"],
        "kind": kind,
        "kind_value": 1,
        "ruleset": training["ruleset"],
        "bank_sha256": bank_sha256,
        "producer_manifest_sha256": producer_manifest_sha256,
        "training_contract_sha256": training_contract_sha256,
        "producer_engine_source_sha256": producer["producer"][
            "producer_engine_source_sha256"
        ],
        "loader_engine_source_sha256": current_loader_hash,
        "records": bank["records"],
        "bytes": bank["bytes"],
        "bbs_version": bank["format"]["version"],
        "match_size": bank["format"]["match_size"],
        "engine_fingerprint": int(bank["format"]["engine_fingerprint"][2:], 16),
    }


def validate_artifact_request(**kwargs: Any) -> dict[str, Any]:
    """Production validator: its authorization set is unconditionally empty."""

    return _validate_request(
        **kwargs,
        # Keep this literal here.  Even rebinding the exported diagnostic
        # constant in an importing process cannot turn the production entry
        # point into the private test collaborator.
        authorized_producer_kinds=frozenset(),
        validate_metadata=False,
    )


def _validate_request_for_test(
    *, authorized_producer_kind: str, **kwargs: Any
) -> dict[str, Any]:
    """Private collaborator for suffix tests; no CLI reaches this function."""

    return _validate_request(
        **kwargs,
        authorized_producer_kinds=frozenset((authorized_producer_kind,)),
        validate_metadata=True,
    )


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_CLOEXEC", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write(
    path: Path, payload: bytes, *, expected_sha256: str | None = None
) -> None:
    previous_existed = os.path.lexists(path)
    previous_payload = (
        read_bounded_file(
            path,
            max(MAX_BBS_BYTES, len(payload), 1),
            "previous destination",
        )
        if previous_existed
        else None
    )
    temporary = _prepare_destination_temporary(
        path, payload, expected_sha256=expected_sha256
    )
    published = False
    try:
        _publish_destination_temporary(
            temporary,
            path,
            payload=payload,
            expected_sha256=expected_sha256,
        )
        published = True
        _fsync_directory(path.parent)
    except BaseException:
        if published:
            _restore_previous_authority(
                path,
                existed=previous_existed,
                payload=previous_payload,
            )
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _prepare_destination_temporary(
    path: Path, payload: bytes, *, expected_sha256: str | None = None
) -> Path:
    """Write, file-fsync, and rehash a destination-local temporary."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as target:
            target.write(payload)
            target.flush()
            os.fsync(target.fileno())
        _verify_destination_temporary(
            temporary, payload, expected_sha256=expected_sha256
        )
        return temporary
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def _verify_destination_temporary(
    temporary: Path,
    payload: bytes,
    *,
    expected_sha256: str | None = None,
) -> None:
    """Require a staged temporary to remain byte-exact and hash-exact."""

    binding = _open_verified_destination_temporary(
        temporary,
        payload,
        expected_sha256=expected_sha256,
    )
    os.close(binding.descriptor)


def _verify_destination_descriptor(
    descriptor: int,
    payload: bytes,
    *,
    expected_sha256: str | None,
    label: str,
    expected_device: int | None = None,
    expected_inode: int | None = None,
) -> os.stat_result:
    try:
        os.lseek(descriptor, 0, os.SEEK_SET)
        before = os.fstat(descriptor)
    except OSError as exc:
        _fail(
            "DESTINATION_SHA256",
            f"cannot inspect {label}: {exc}",
        )
    if not stat.S_ISREG(before.st_mode):
        _fail("DESTINATION_SHA256", f"{label} is not a regular file")
    if (
        expected_device is not None
        and expected_inode is not None
        and (before.st_dev != expected_device or before.st_ino != expected_inode)
    ):
        _fail(
            "DESTINATION_SHA256",
            f"{label} inode differs from the verified temporary",
        )
    if before.st_size != len(payload):
        _fail(
            "DESTINATION_SHA256",
            f"{label} size {before.st_size} != {len(payload)}",
        )
    chunks: list[bytes] = []
    remaining = len(payload)
    while remaining:
        try:
            chunk = os.read(descriptor, min(1 << 20, remaining))
        except OSError as exc:
            _fail("DESTINATION_SHA256", f"cannot read {label}: {exc}")
        if not chunk:
            _fail("DESTINATION_SHA256", f"{label} became shorter while reading")
        chunks.append(chunk)
        remaining -= len(chunk)
    try:
        if os.read(descriptor, 1):
            _fail("DESTINATION_SHA256", f"{label} grew while reading")
        after = os.fstat(descriptor)
    except OSError as exc:
        _fail("DESTINATION_SHA256", f"cannot finish reading {label}: {exc}")
    if (
        after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        _fail("DESTINATION_SHA256", f"{label} changed while being verified")
    observed_payload = b"".join(chunks)
    if observed_payload != payload:
        _fail(
            "DESTINATION_SHA256",
            f"{label} differs from its staged payload",
        )
    observed_sha256 = hashlib.sha256(observed_payload).hexdigest()
    expected = expected_sha256 or hashlib.sha256(payload).hexdigest()
    if observed_sha256 != expected:
        _fail(
            "DESTINATION_SHA256",
            f"{label} SHA-256 {observed_sha256} != {expected}",
        )
    try:
        verified = os.fstat(descriptor)
    except OSError as exc:
        _fail("DESTINATION_SHA256", f"cannot finish verifying {label}: {exc}")
    if (
        not stat.S_ISREG(verified.st_mode)
        or verified.st_dev != after.st_dev
        or verified.st_ino != after.st_ino
        or verified.st_size != after.st_size
        or verified.st_mtime_ns != after.st_mtime_ns
        or verified.st_ctime_ns != after.st_ctime_ns
    ):
        _fail("DESTINATION_SHA256", f"{label} changed while being verified")
    return verified


def _require_published_destination_path(
    path: Path,
    binding: _DestinationTemporaryBinding,
    verified: os.stat_result,
) -> None:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError as exc:
        _fail(
            "DESTINATION_SHA256",
            f"published destination path inode cannot be inspected: {exc}",
        )
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_dev != binding.device
        or info.st_ino != binding.inode
        or info.st_dev != verified.st_dev
        or info.st_ino != verified.st_ino
        or info.st_size != verified.st_size
        or info.st_mtime_ns != verified.st_mtime_ns
        or info.st_ctime_ns != verified.st_ctime_ns
    ):
        _fail(
            "DESTINATION_SHA256",
            "published destination path inode or metadata differs from "
            "verified descriptor",
        )


def _open_verified_destination_temporary(
    temporary: Path,
    payload: bytes,
    *,
    expected_sha256: str | None,
) -> _DestinationTemporaryBinding:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(temporary, flags)
    except OSError as exc:
        _fail(
            "DESTINATION_SHA256",
            f"cannot open destination temporary: {exc}",
        )
    try:
        info = _verify_destination_descriptor(
            descriptor,
            payload,
            expected_sha256=expected_sha256,
            label="destination temporary",
        )
    except BaseException:
        os.close(descriptor)
        raise
    return _DestinationTemporaryBinding(
        descriptor=descriptor,
        device=info.st_dev,
        inode=info.st_ino,
    )


def _publish_destination_temporary(
    temporary: Path,
    path: Path,
    *,
    payload: bytes,
    expected_sha256: str | None = None,
) -> None:
    """Publish and reconcile one expected destination-local temporary."""

    binding = _open_verified_destination_temporary(
        temporary,
        payload,
        expected_sha256=expected_sha256,
    )
    previous_existed = os.path.lexists(path)
    previous_payload = (
        read_bounded_file(
            path,
            max(MAX_BBS_BYTES, len(payload), 1),
            "previous destination",
        )
        if previous_existed
        else None
    )
    replaced = False
    try:
        os.replace(temporary, path)
        replaced = True
        flags = (
            os.O_RDONLY
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NONBLOCK", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            published_descriptor = os.open(path, flags)
        except OSError as exc:
            _fail(
                "DESTINATION_SHA256",
                f"cannot open published destination: {exc}",
            )
        try:
            verified = _verify_destination_descriptor(
                published_descriptor,
                payload,
                expected_sha256=expected_sha256,
                expected_device=binding.device,
                expected_inode=binding.inode,
                label="published destination",
            )
            _require_published_destination_path(path, binding, verified)
        finally:
            os.close(published_descriptor)
    except BaseException:
        if replaced:
            _restore_previous_authority(
                path,
                existed=previous_existed,
                payload=previous_payload,
            )
        raise
    finally:
        os.close(binding.descriptor)


def _restore_previous_authority(
    path: Path, *, existed: bool, payload: bytes | None
) -> None:
    """Best-effort rollback after a caught post-authority publication error."""

    temporary: Path | None = None
    try:
        if existed:
            if payload is None:
                raise AssertionError("existing authority payload was not captured")
            temporary = _prepare_destination_temporary(
                path,
                payload,
                expected_sha256=hashlib.sha256(payload).hexdigest(),
            )
            # Bypass the injectable forward-publication seam: rollback must
            # remain possible while that seam is deliberately failing.
            os.replace(temporary, path)
            temporary = None
        else:
            try:
                path.unlink()
            except FileNotFoundError:
                pass
        _fsync_directory(path.parent)
    finally:
        if temporary is not None:
            try:
                temporary.unlink()
            except OSError:
                pass


def render_no_bank_header(
    *,
    exact_action_source_hash: str,
    environment_source_hash: str,
    observation_abi: str,
    observation_version: int,
) -> bytes:
    _require_sha256(exact_action_source_hash, "exact-action source hash")
    _require_sha256(environment_source_hash, "environment source hash")
    if (
        not isinstance(observation_abi, str)
        or re.fullmatch(r"obs-v[1-9][0-9]*", observation_abi) is None
    ):
        _fail("OBSERVATION_ABI", "observation ABI must be canonical obs-vN")
    if (
        isinstance(observation_version, bool)
        or not isinstance(observation_version, int)
        or observation_version <= 0
        or observation_abi != f"obs-v{observation_version}"
    ):
        _fail("OBSERVATION_ABI", "observation version disagrees with ABI")
    lines = [
        "#pragma once",
        f'#define PUFFER_EXACT_ACTION_SOURCE_HASH "{exact_action_source_hash}"',
        f'#define PUFFER_ENV_SOURCE_HASH "{environment_source_hash}"',
        f'#define PUFFER_OBSERVATION_ABI "{observation_abi}"',
        f"#define PUFFER_OBSERVATION_VERSION {observation_version}",
        '#define PUFFER_ACTION_ABI "exact-joint-v1"',
    ]
    for field, macro in STATE_FIELD_TO_MACRO.items():
        value = NO_BANK_STATE_FIELDS[field]
        if isinstance(value, str):
            lines.append(f'#define {macro} "{value}"')
        else:
            lines.append(f"#define {macro} {value}")
    return ("\n".join(lines) + "\n").encode("ascii")


def _render_bank_header_for_test(
    fields: Mapping[str, Any],
    *,
    exact_action_source_hash: str,
    environment_source_hash: str,
    observation_abi: str,
    observation_version: int,
) -> bytes:
    """Render a strict header only for the private transaction collaborator."""

    # Reuse validation for the shared environment lineage fields.
    render_no_bank_header(
        exact_action_source_hash=exact_action_source_hash,
        environment_source_hash=environment_source_hash,
        observation_abi=observation_abi,
        observation_version=observation_version,
    )
    state_fields = _complete_compiled_fields(fields)
    lines = [
        "#pragma once",
        f'#define PUFFER_EXACT_ACTION_SOURCE_HASH "{exact_action_source_hash}"',
        f'#define PUFFER_ENV_SOURCE_HASH "{environment_source_hash}"',
        f'#define PUFFER_OBSERVATION_ABI "{observation_abi}"',
        f"#define PUFFER_OBSERVATION_VERSION {observation_version}",
        '#define PUFFER_ACTION_ABI "exact-joint-v1"',
    ]
    for field, macro in STATE_FIELD_TO_MACRO.items():
        value = state_fields[field]
        if isinstance(value, str):
            lines.append(f'#define {macro} "{value}"')
        else:
            lines.append(f"#define {macro} {value}")
    return ("\n".join(lines) + "\n").encode("ascii")


def _complete_compiled_fields(fields: Mapping[str, Any]) -> dict[str, str | int]:
    state_fields: dict[str, str | int] = {
        "contract_schema": fields["contract_schema"],
        "producer_schema": fields["producer_schema"],
        "authorization_schema": fields["authorization_schema"],
        "strata_schema": STRATA_SCHEMA,
        "kind_value": fields["kind_value"],
        "kind": fields["kind"],
        "ruleset": fields["ruleset"],
        "bank_sha256": fields["bank_sha256"],
        "producer_manifest_sha256": fields["producer_manifest_sha256"],
        "training_contract_sha256": fields["training_contract_sha256"],
        "producer_engine_source_sha256": fields["producer_engine_source_sha256"],
        "loader_engine_source_sha256": fields["loader_engine_source_sha256"],
        "bytes": fields["bytes"],
        "records": fields["records"],
        "bbs_version": fields["bbs_version"],
        "match_size": fields["match_size"],
        "engine_fingerprint": fields["engine_fingerprint"],
        "bank_path": "resources/bloodbowl/state_bank.bbs",
        "producer_manifest_path": "resources/bloodbowl/state_bank.producer.json",
        "training_contract_path": "resources/bloodbowl/state_bank.contract.json",
    }
    state_fields["contract_identity"] = compiled_contract_identity(state_fields)
    return state_fields


def compiled_contract_identity(fields: Mapping[str, Any]) -> str:
    """Return the unique identity of every compiled field except itself."""

    identity_fields = {
        field: fields[field]
        for field in STATE_FIELD_TO_MACRO
        if field != "contract_identity"
    }
    identity_payload = json.dumps(
        identity_fields, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    return hashlib.sha256(
        b"bloodbowl-state-bank-compiled-identity-v1\0" + identity_payload
    ).hexdigest()


def _require_json_uint32(value: Any, location: str) -> int:
    result = _require_nonnegative_int(value, location)
    if result > 0xFFFFFFFF:
        _fail("ENGINE_VALIDATOR", f"{location} exceeds uint32")
    return result


def _require_selector_request(
    family: Any,
    threshold: Any,
    *,
    location: str,
) -> tuple[str, int]:
    if not isinstance(family, str) or family not in SELECTOR_FAMILY_BOUNDS:
        _fail(
            "SELECTOR_FAMILY",
            f"{location}.family must be one of "
            f"{tuple(SELECTOR_FAMILY_BOUNDS)!r}",
        )
    if isinstance(threshold, bool) or not isinstance(threshold, int):
        _fail(
            "SELECTOR_THRESHOLD",
            f"{location}.threshold must be an exact integer",
        )
    maximum = SELECTOR_FAMILY_BOUNDS[family]
    if threshold < 0 or threshold > maximum:
        _fail(
            "SELECTOR_THRESHOLD",
            f"{location}.threshold for {family} must be in [0,{maximum}]",
        )
    return family, threshold


_ENGINE_VALIDATOR_CFLAGS = (
    "-std=c11",
    "-O2",
    "-g",
    "-Wall",
    "-Wextra",
    "-Werror",
    "-Wno-unused-function",
)


def _trusted_system_c_compiler() -> Path:
    """Resolve a compiler from fixed system paths, never caller environment."""

    for candidate in (
        Path("/usr/bin/clang"),
        Path("/usr/bin/cc"),
        Path("/usr/bin/gcc"),
        Path("/bin/cc"),
    ):
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_file() and os.access(resolved, os.X_OK):
            return resolved
    _fail(
        "ENGINE_VALIDATOR_BUILD",
        "no trusted system C compiler exists at a fixed system path",
    )


def _engine_validator_subprocess_environment(build_root: Path) -> dict[str, str]:
    """Return a minimal environment without build or loader injection hooks."""

    try:
        system_path = os.confstr("CS_PATH")
    except (AttributeError, OSError, ValueError):
        system_path = None
    if not system_path:
        system_path = "/usr/bin:/bin"
    return {
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": system_path,
        "TMPDIR": str(build_root),
    }


def _write_snapshot_file(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        _fail(
            "ENGINE_SOURCE_SNAPSHOT",
            f"cannot create private snapshot file {path}: {exc}",
        )
    try:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                _fail(
                    "ENGINE_SOURCE_SNAPSHOT",
                    f"short write while creating private snapshot file {path}",
                )
            offset += written
        os.fsync(descriptor)
    except OSError as exc:
        _fail(
            "ENGINE_SOURCE_SNAPSHOT",
            f"cannot write private snapshot file {path}: {exc}",
        )
    finally:
        os.close(descriptor)


def _render_engine_validator_build_header(
    environment_source_sha256: str,
) -> bytes:
    """Render the only generated input to the two pinned source closures."""

    _require_sha256(
        environment_source_sha256,
        "validator environment source SHA-256",
    )
    lines = [
        "#pragma once",
        f'#define PUFFER_ENV_SOURCE_HASH "{environment_source_sha256}"',
    ]
    for field, macro in STATE_FIELD_TO_MACRO.items():
        value = NO_BANK_STATE_FIELDS[field]
        if isinstance(value, str):
            lines.append(f'#define {macro} "{value}"')
        else:
            lines.append(f"#define {macro} {value}")
    return ("\n".join(lines) + "\n").encode("ascii")


def _snapshot_engine_source(
    source_root: Path,
    snapshot_root: Path,
    *,
    expected_sha256: str,
) -> None:
    """Materialize engine bytes whose reconstructed tree hashes to the pin."""

    try:
        snapshot_root.mkdir(mode=0o700)
        (snapshot_root / "engine/include/bb").mkdir(parents=True)
        (snapshot_root / "engine/src").mkdir(parents=True)
    except OSError as exc:
        _fail(
            "ENGINE_SOURCE_SNAPSHOT",
            f"cannot create private engine snapshot: {exc}",
        )
    entries = _read_engine_source_entries(source_root)
    for relative_bytes, payload in entries:
        relative = Path(relative_bytes.decode("utf-8"))
        _write_snapshot_file(snapshot_root / relative, payload)
    alias = snapshot_root / "engine/src/bb"
    try:
        alias.symlink_to("../include/bb")
    except OSError as exc:
        _fail(
            "ENGINE_SOURCE_SNAPSHOT",
            f"cannot create canonical engine/src/bb snapshot alias: {exc}",
        )
    observed_sha256 = engine_source_sha256(snapshot_root)
    if observed_sha256 != expected_sha256:
        _fail(
            "ENGINE_SOURCE_SNAPSHOT",
            f"snapshot engine source SHA-256 {observed_sha256} != "
            f"claimed loader SHA-256 {expected_sha256}",
        )


def _snapshot_environment_source(
    source_environment_root: Path,
    snapshot_environment_root: Path,
    *,
    expected_sha256: str,
) -> None:
    """Materialize and rehash the complete dereferenced environment closure."""

    entries = _read_environment_source_entries(source_environment_root)
    try:
        snapshot_environment_root.mkdir(parents=True)
    except OSError as exc:
        _fail(
            "ENVIRONMENT_SOURCE_SNAPSHOT",
            f"cannot create private environment snapshot: {exc}",
        )
    for relative, payload in entries:
        logical = relative[2:]
        _write_snapshot_file(
            snapshot_environment_root / os.fsdecode(logical),
            payload,
        )
    observed_sha256 = environment_source_sha256(snapshot_environment_root)
    if observed_sha256 != expected_sha256:
        _fail(
            "ENVIRONMENT_SOURCE_SNAPSHOT",
            f"snapshot environment source SHA-256 {observed_sha256} != "
            f"installed PUFFER_ENV_SOURCE_HASH {expected_sha256}",
        )


def _freeze_snapshot_tree(snapshot_root: Path) -> None:
    directories = [snapshot_root]
    files: list[Path] = []
    for current, names, filenames in os.walk(
        snapshot_root, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        for name in list(names):
            path = current_path / name
            if path.is_symlink():
                names.remove(name)
            else:
                directories.append(path)
        for name in filenames:
            path = current_path / name
            if not path.is_symlink():
                files.append(path)
    try:
        for path in files:
            path.chmod(0o400)
        for path in reversed(directories):
            path.chmod(0o500)
    except OSError as exc:
        _fail(
            "ENGINE_SOURCE_SNAPSHOT",
            f"cannot make private validator snapshot read-only: {exc}",
        )


def _thaw_snapshot_tree(snapshot_root: Path) -> None:
    """Best-effort permission restoration so TemporaryDirectory can remove it."""

    try:
        snapshot_root.chmod(0o700)
    except OSError:
        return
    for current, names, filenames in os.walk(
        snapshot_root, topdown=True, followlinks=False
    ):
        current_path = Path(current)
        for name in names:
            path = current_path / name
            if not path.is_symlink():
                try:
                    path.chmod(0o700)
                except OSError:
                    pass
        for name in filenames:
            path = current_path / name
            if not path.is_symlink():
                try:
                    path.chmod(0o600)
                except OSError:
                    pass


def _run_engine_validator(
    *,
    repo_root: Path,
    request: Mapping[str, Any],
    fields: Mapping[str, Any],
    contract_identity: str,
    environment_source_sha256: str,
    selector_family: str,
    selector_threshold: int,
) -> dict[str, Any]:
    """Build and execute a source-pinned engine-linked validator snapshot."""

    _require_sha256(
        environment_source_sha256,
        "installed PUFFER_ENV_SOURCE_HASH",
    )
    selector_family, selector_threshold = _require_selector_request(
        selector_family,
        selector_threshold,
        location="engine_validator.selector",
    )
    with tempfile.TemporaryDirectory(
        prefix="bloodbowl-state-bank-validator-"
    ) as isolated_workspace_name:
        isolated_workspace = Path(isolated_workspace_name)
        isolated_source = isolated_workspace / "source"
        isolated_build = isolated_workspace / "build"
        _snapshot_engine_source(
            repo_root,
            isolated_source,
            expected_sha256=str(fields["loader_engine_source_sha256"]),
        )
        _snapshot_environment_source(
            repo_root / "puffer/bloodbowl",
            isolated_source / "puffer/bloodbowl",
            expected_sha256=environment_source_sha256,
        )
        _write_snapshot_file(
            isolated_source / "puffer/bloodbowl/state_bank_build.h",
            _render_engine_validator_build_header(
                environment_source_sha256
            ),
        )
        try:
            isolated_build.mkdir(mode=0o700)
            _freeze_snapshot_tree(isolated_source)
            helper = isolated_build / "state_bank_validate"
            compiler = _trusted_system_c_compiler()
            subprocess_environment = (
                _engine_validator_subprocess_environment(isolated_build)
            )
            build = subprocess.run(
                [
                    str(compiler),
                    *_ENGINE_VALIDATOR_CFLAGS,
                    "-I",
                    str(isolated_source / "engine/include"),
                    "-I",
                    str(isolated_source / "puffer/bloodbowl"),
                    str(
                        isolated_source
                        / "puffer/bloodbowl/state_bank_validate.c"
                    ),
                    "-o",
                    str(helper),
                    "-lm",
                ],
                cwd=isolated_source,
                env=subprocess_environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
                timeout=120,
            )
            if build.returncode != 0:
                _fail(
                    "ENGINE_VALIDATOR_BUILD",
                    "state-bank validator build failed: " f"{build.stdout.strip()}",
                )
            if (
                not helper.is_file()
                or helper.is_symlink()
                or not os.access(helper, os.X_OK)
            ):
                _fail(
                    "ENGINE_VALIDATOR_BUILD",
                    "isolated compiler did not produce an executable regular "
                    f"helper at {helper}",
                )
            command = [
                str(helper),
                "--kind",
                str(fields["kind"]),
                "--bank",
                str(request["bank_path"]),
                "--bank-sha256",
                str(fields["bank_sha256"]),
                "--producer-manifest",
                str(request["producer_manifest_path"]),
                "--producer-manifest-sha256",
                str(fields["producer_manifest_sha256"]),
                "--training-contract",
                str(request["training_contract_path"]),
                "--training-contract-sha256",
                str(fields["training_contract_sha256"]),
                "--bytes",
                str(fields["bytes"]),
                "--records",
                str(fields["records"]),
                "--producer-engine-source-sha256",
                str(fields["producer_engine_source_sha256"]),
                "--loader-engine-source-sha256",
                str(fields["loader_engine_source_sha256"]),
                "--environment-source-sha256",
                environment_source_sha256,
                "--contract-identity",
                contract_identity,
                "--selector-family",
                selector_family,
                "--selector-threshold",
                str(selector_threshold),
            ]
            validation = subprocess.run(
                command,
                cwd=isolated_source,
                env=subprocess_environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
                timeout=120,
            )
        finally:
            _thaw_snapshot_tree(isolated_source)
    if validation.returncode != 0:
        diagnostic = validation.stderr.decode("utf-8", "replace").strip()
        _fail(
            "ENGINE_VALIDATOR_REJECTED",
            f"engine-linked validator exited {validation.returncode}: " f"{diagnostic}",
        )
    if validation.stderr:
        _fail(
            "ENGINE_VALIDATOR",
            "successful engine-linked validator emitted stderr",
        )
    result = parse_json_bytes(validation.stdout, "engine validator output")
    result = _require_exact_keys(
        result,
        (
            "schema",
            "kind",
            "kind_value",
            "bank_sha256",
            "producer_manifest_sha256",
            "training_contract_sha256",
            "producer_engine_source_sha256",
            "loader_engine_source_sha256",
            "contract_identity",
            "bytes",
            "records",
            "bbs_version",
            "match_size",
            "engine_fingerprint",
            "source_id_min",
            "source_id_max",
            "command_min",
            "command_max",
            "legal_actions_min",
            "legal_actions_max",
            "environment_source_sha256",
            "strata_schema",
            "strata_family",
            "strata_threshold",
            "strata_eligible_records",
            "strata_sha256",
        ),
        "engine_validation",
    )
    expected = {
        "schema": VALIDATION_SCHEMA,
        "kind": fields["kind"],
        "kind_value": fields["kind_value"],
        "bank_sha256": fields["bank_sha256"],
        "producer_manifest_sha256": fields["producer_manifest_sha256"],
        "training_contract_sha256": fields["training_contract_sha256"],
        "producer_engine_source_sha256": fields["producer_engine_source_sha256"],
        "loader_engine_source_sha256": fields["loader_engine_source_sha256"],
        "contract_identity": contract_identity,
        "bytes": fields["bytes"],
        "records": fields["records"],
        "bbs_version": fields["bbs_version"],
        "match_size": fields["match_size"],
        "engine_fingerprint": fields["engine_fingerprint"],
        "environment_source_sha256": environment_source_sha256,
        "strata_schema": STRATA_SCHEMA,
        "strata_family": selector_family,
        "strata_threshold": selector_threshold,
    }
    for field, expected_value in expected.items():
        if type(result[field]) is not type(expected_value) or (
            result[field] != expected_value
        ):
            _fail(
                "ENGINE_VALIDATOR_RECONCILE",
                f"engine validator {field} {result[field]!r} != " f"{expected_value!r}",
            )
    source_min = _require_json_uint32(
        result["source_id_min"], "engine_validation.source_id_min"
    )
    source_max = _require_json_uint32(
        result["source_id_max"], "engine_validation.source_id_max"
    )
    command_min = _require_json_uint32(
        result["command_min"], "engine_validation.command_min"
    )
    command_max = _require_json_uint32(
        result["command_max"], "engine_validation.command_max"
    )
    legal_min = _require_positive_int(
        result["legal_actions_min"], "engine_validation.legal_actions_min"
    )
    legal_max = _require_positive_int(
        result["legal_actions_max"], "engine_validation.legal_actions_max"
    )
    eligible_records = _require_positive_int(
        result["strata_eligible_records"],
        "engine_validation.strata_eligible_records",
    )
    _require_sha256(result["strata_sha256"], "engine_validation.strata_sha256")
    if (
        source_min == 0
        or source_min > source_max
        or source_min & AUTHORED_SOURCE_MASK == AUTHORED_SOURCE_NAMESPACE
        or source_max & AUTHORED_SOURCE_MASK == AUTHORED_SOURCE_NAMESPACE
        or command_min > command_max
        or legal_min > legal_max
        or eligible_records > fields["records"]
        or (
            selector_family == "uniform"
            and eligible_records != fields["records"]
        )
    ):
        _fail(
            "ENGINE_VALIDATOR",
            "engine validator emitted impossible metadata/legal-action bounds",
        )
    return result


def _stage_authorized_request_for_test(
    puffer_root: str | Path,
    *,
    authorized_producer_kind: str,
    exact_action_source_hash: str,
    environment_source_hash: str,
    observation_abi: str,
    observation_version: int,
    **request: Any,
) -> dict[str, Any]:
    """Exercise the dormant two-phase publication suffix; never a CLI."""

    fields = _validate_request_for_test(
        authorized_producer_kind=authorized_producer_kind, **request
    )
    compiled_fields = _complete_compiled_fields(fields)
    _run_engine_validator(
        repo_root=Path(request["engine_root"]),
        request=request,
        fields=fields,
        contract_identity=str(compiled_fields["contract_identity"]),
        environment_source_sha256=environment_source_hash,
        selector_family="uniform",
        selector_threshold=0,
    )
    bank_payload = read_bounded_file(Path(request["bank_path"]), MAX_BBS_BYTES, "BBS")
    producer_payload = read_bounded_file(
        Path(request["producer_manifest_path"]),
        MAX_MANIFEST_BYTES,
        "producer manifest",
    )
    contract_payload = read_bounded_file(
        Path(request["training_contract_path"]),
        MAX_MANIFEST_BYTES,
        "training contract",
    )
    payloads = (
        (
            "state_bank.bbs",
            bank_payload,
            str(request["bank_sha256"]),
        ),
        (
            "state_bank.producer.json",
            producer_payload,
            str(request["producer_manifest_sha256"]),
        ),
        (
            "state_bank.contract.json",
            contract_payload,
            str(request["training_contract_sha256"]),
        ),
    )
    root = Path(puffer_root)
    resource_directory = root / "resources/bloodbowl"
    ocean_directory = root / "ocean/bloodbowl"
    source_directory = root / "src"
    for directory in (resource_directory, ocean_directory, source_directory):
        directory.mkdir(parents=True, exist_ok=True)
    authority = source_directory / "exact_action_build_hash.h"
    bridge = (
        "#pragma once\n" '#include "../../src/exact_action_build_hash.h"\n'
    ).encode("ascii")
    header = _render_bank_header_for_test(
        fields,
        exact_action_source_hash=exact_action_source_hash,
        environment_source_hash=environment_source_hash,
        observation_abi=observation_abi,
        observation_version=observation_version,
    )
    staged: list[tuple[Path, Path, bytes, str | None]] = []
    previous_destinations: dict[Path, tuple[bool, bytes | None]] = {}
    published_destinations: list[Path] = []
    try:
        # Phase one: every destination-local temporary is complete, file
        # fsynced, and independently rehashed before the first publication.
        for name, payload, expected_sha256 in payloads:
            destination = resource_directory / name
            staged.append(
                (
                    _prepare_destination_temporary(
                        destination,
                        payload,
                        expected_sha256=expected_sha256,
                    ),
                    destination,
                    payload,
                    expected_sha256,
                )
            )
        bridge_destination = ocean_directory / "state_bank_build.h"
        staged.append(
            (
                _prepare_destination_temporary(bridge_destination, bridge),
                bridge_destination,
                bridge,
                None,
            )
        )
        staged.append(
            (
                _prepare_destination_temporary(authority, header),
                authority,
                header,
                None,
            )
        )

        for _temporary, destination, payload, _expected_sha256 in staged:
            existed = os.path.lexists(destination)
            previous_destinations[destination] = (
                existed,
                (
                    read_bounded_file(
                        destination,
                        max(MAX_BBS_BYTES, len(payload), 1),
                        "previous staged destination",
                    )
                    if existed
                    else None
                ),
            )

        # Rehash the complete staged set together.  This catches mutation of
        # an earlier temporary while a later one was still being prepared.
        for temporary, _destination, payload, expected_sha256 in staged:
            _verify_destination_temporary(
                temporary,
                payload,
                expected_sha256=expected_sha256,
            )

        # Phase two: data first, then its directory; bridge next, then its
        # directory; the sole generated authority and its directory last.
        for temporary, destination, payload, expected_sha256 in staged[:3]:
            _publish_destination_temporary(
                temporary,
                destination,
                payload=payload,
                expected_sha256=expected_sha256,
            )
            published_destinations.append(destination)
        _fsync_directory(resource_directory)
        _publish_destination_temporary(
            staged[3][0],
            staged[3][1],
            payload=staged[3][2],
            expected_sha256=staged[3][3],
        )
        published_destinations.append(staged[3][1])
        _fsync_directory(ocean_directory)
        _publish_destination_temporary(
            staged[4][0],
            staged[4][1],
            payload=staged[4][2],
            expected_sha256=staged[4][3],
        )
        published_destinations.append(staged[4][1])
        _fsync_directory(source_directory)
    except BaseException:
        for destination in reversed(published_destinations):
            existed, previous_payload = previous_destinations[destination]
            _restore_previous_authority(
                destination,
                existed=existed,
                payload=previous_payload,
            )
        raise
    finally:
        for temporary, _destination, _payload, _expected_sha256 in staged:
            try:
                temporary.unlink()
            except OSError:
                pass
    return fields


def install_no_bank_contract(
    puffer_root: str | Path,
    *,
    exact_action_source_hash: str,
    environment_source_hash: str,
    observation_abi: str,
    observation_version: int,
) -> None:
    """Publish the exact no-bank transaction, generated authority last."""

    puffer_root = Path(puffer_root)
    resource_directory = puffer_root / "resources/bloodbowl"
    ocean_directory = puffer_root / "ocean/bloodbowl"
    source_directory = puffer_root / "src"
    for directory in (resource_directory, ocean_directory, source_directory):
        directory.mkdir(parents=True, exist_ok=True)
    for name in (
        "state_bank.bbs",
        "state_bank.producer.json",
        "state_bank.contract.json",
    ):
        try:
            (resource_directory / name).unlink()
        except FileNotFoundError:
            pass
    _fsync_directory(resource_directory)
    bridge = (
        "#pragma once\n" '#include "../../src/exact_action_build_hash.h"\n'
    ).encode("ascii")
    _atomic_write(ocean_directory / "state_bank_build.h", bridge)
    header = render_no_bank_header(
        exact_action_source_hash=exact_action_source_hash,
        environment_source_hash=environment_source_hash,
        observation_abi=observation_abi,
        observation_version=observation_version,
    )
    _atomic_write(source_directory / "exact_action_build_hash.h", header)


def parse_generated_header(path: str | Path) -> dict[str, str | int]:
    payload = read_bounded_file(Path(path), MAX_MANIFEST_BYTES, "build header")
    try:
        text = payload.decode("ascii")
    except UnicodeDecodeError as exc:
        _fail("BUILD_HEADER", f"build header is not ASCII: {exc}")
    lines = text.splitlines()
    if not lines or lines[0] != "#pragma once":
        _fail("BUILD_HEADER", "build header must begin with exact #pragma once")
    macros: dict[str, str | int] = {}
    for line in lines[1:]:
        string_match = DEFINE_STRING_RE.fullmatch(line)
        integer_match = DEFINE_INTEGER_RE.fullmatch(line)
        if string_match:
            name, value = string_match.groups()
        elif integer_match:
            name, raw_value = integer_match.groups()
            value = int(raw_value)
        else:
            _fail("BUILD_HEADER", f"unrecognized build-header line {line!r}")
        if name in macros:
            _fail("BUILD_HEADER", f"duplicate build macro {name}")
        macros[name] = value
    expected = set(BASE_BUILD_MACROS + STATE_BANK_MACROS)
    missing = sorted(expected - set(macros))
    unknown = sorted(set(macros) - expected)
    if missing or unknown:
        _fail(
            "BUILD_HEADER",
            f"build macros differ; missing={missing}, unknown={unknown}",
        )
    return macros


def show_installed(puffer_root: str | Path) -> dict[str, str | int]:
    root = Path(puffer_root)
    macros = parse_generated_header(root / "src/exact_action_build_hash.h")
    return {field: macros[macro] for field, macro in STATE_FIELD_TO_MACRO.items()}


def contract_from_module(module: Any) -> dict[str, str | int]:
    """Read the exact state-bank surface exported by a Puffer ``_C`` module."""

    result: dict[str, str | int] = {}
    for field, attribute in MODULE_STATE_FIELD_NAMES.items():
        if not hasattr(module, attribute):
            _fail("MODULE_CONTRACT", f"compiled module lacks {attribute}")
        value = getattr(module, attribute)
        expected = NO_BANK_STATE_FIELDS[field]
        if isinstance(expected, int):
            if isinstance(value, bool) or not isinstance(value, int):
                _fail(
                    "MODULE_CONTRACT",
                    f"compiled module {attribute} must be an integer",
                )
            result[field] = int(value)
        else:
            if not isinstance(value, str):
                _fail(
                    "MODULE_CONTRACT",
                    f"compiled module {attribute} must be a string",
                )
            result[field] = value
    return result


def check_no_bank_install(puffer_root: str | Path) -> dict[str, str | int]:
    root = Path(puffer_root)
    resource_directory = root / "resources/bloodbowl"
    present = [
        str(resource_directory / name)
        for name in (
            "state_bank.bbs",
            "state_bank.producer.json",
            "state_bank.contract.json",
        )
        if os.path.lexists(resource_directory / name)
    ]
    if present:
        _fail("STALE_STATE_BANK", f"no-bank install retains artifacts: {present}")
    expected_bridge = (
        "#pragma once\n" '#include "../../src/exact_action_build_hash.h"\n'
    ).encode("ascii")
    bridge = read_bounded_file(
        root / "ocean/bloodbowl/state_bank_build.h",
        MAX_MANIFEST_BYTES,
        "state-bank header bridge",
    )
    if bridge != expected_bridge:
        _fail("BUILD_HEADER", "installed state-bank bridge is not exact")
    observed = show_installed(root)
    if observed != NO_BANK_STATE_FIELDS:
        _fail(
            "BUILD_HEADER",
            f"installed state-bank contract is not NONE: {observed!r}",
        )
    return observed


def validate_installed(
    *,
    puffer_root: Path,
    kind: str,
    bank_sha256: str,
    producer_manifest_sha256: str,
    training_contract_sha256: str,
    selector_family: str,
    selector_threshold: int,
) -> dict[str, Any]:
    selector_family, selector_threshold = _require_selector_request(
        selector_family,
        selector_threshold,
        location="validate_installed.selector",
    )
    try:
        puffer_root = Path(puffer_root).resolve(strict=True)
    except OSError as exc:
        _fail(
            "PUFFER_ROOT",
            f"cannot resolve installed Puffer root {puffer_root!s}: {exc}",
        )
    macros = parse_generated_header(
        puffer_root / "src/exact_action_build_hash.h"
    )
    fields = {
        field: macros[macro] for field, macro in STATE_FIELD_TO_MACRO.items()
    }
    if fields["kind_value"] == 0:
        _fail("NO_BANK_CONTRACT", "installed Puffer build has no state bank")
    request = {
        "bank_path": puffer_root / str(fields["bank_path"]),
        "bank_sha256": bank_sha256,
        "producer_manifest_path":
            puffer_root / str(fields["producer_manifest_path"]),
        "producer_manifest_sha256": producer_manifest_sha256,
        "training_contract_path":
            puffer_root / str(fields["training_contract_path"]),
        "training_contract_sha256": training_contract_sha256,
        "kind": kind,
        "engine_root": Path(__file__).resolve().parents[1],
    }
    result = validate_artifact_request(**request)
    expected_compiled = _complete_compiled_fields(result)
    for field, value in expected_compiled.items():
        if fields[field] != value:
            _fail(
                "COMPILED_CONTRACT_MISMATCH",
                f"compiled {field} {fields[field]!r} != {value!r}",
            )
    environment_hash = macros["PUFFER_ENV_SOURCE_HASH"]
    _require_sha256(environment_hash, "installed PUFFER_ENV_SOURCE_HASH")
    validation = _run_engine_validator(
        repo_root=Path(request["engine_root"]),
        request=request,
        fields=result,
        contract_identity=str(expected_compiled["contract_identity"]),
        environment_source_sha256=environment_hash,
        selector_family=selector_family,
        selector_threshold=selector_threshold,
    )
    launcher_result = dict(result)
    for field in (
        "environment_source_sha256",
        "strata_schema",
        "strata_family",
        "strata_threshold",
        "strata_eligible_records",
        "strata_sha256",
    ):
        launcher_result[field] = validation[field]
    return {
        field: launcher_result[field] for field in LAUNCHER_CONTRACT_FIELDS
    }


def _add_request_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--kind", required=True)
    parser.add_argument("--bank", type=Path, required=True)
    parser.add_argument("--bank-sha256", required=True)
    parser.add_argument("--producer-manifest", type=Path, required=True)
    parser.add_argument("--producer-manifest-sha256", required=True)
    parser.add_argument("--training-contract", type=Path, required=True)
    parser.add_argument("--training-contract-sha256", required=True)
    parser.add_argument("--engine-root", type=Path, required=True)


def _canonical_cli_uint(raw: str) -> int:
    if re.fullmatch(r"(?:0|[1-9][0-9]*)", raw) is None:
        raise argparse.ArgumentTypeError(
            "must be a canonical nonnegative decimal integer"
        )
    return int(raw)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate_request_parser = subparsers.add_parser("validate-request")
    _add_request_arguments(validate_request_parser)
    validate_installed_parser = subparsers.add_parser("validate-installed")
    validate_installed_parser.add_argument("--puffer-root", type=Path, required=True)
    validate_installed_parser.add_argument("--kind", required=True)
    validate_installed_parser.add_argument("--bank-sha256", required=True)
    validate_installed_parser.add_argument("--producer-manifest-sha256", required=True)
    validate_installed_parser.add_argument("--training-contract-sha256", required=True)
    validate_installed_parser.add_argument(
        "--selector-family",
        choices=tuple(SELECTOR_FAMILY_BOUNDS),
        action="append",
        required=True,
    )
    validate_installed_parser.add_argument(
        "--selector-threshold",
        type=_canonical_cli_uint,
        action="append",
        required=True,
    )
    show_parser = subparsers.add_parser("show-installed")
    show_parser.add_argument("--puffer-root", type=Path, required=True)
    check_parser = subparsers.add_parser("check-no-bank")
    check_parser.add_argument("--puffer-root", type=Path, required=True)
    install_parser = subparsers.add_parser("install-no-bank")
    install_parser.add_argument("--puffer-root", type=Path, required=True)
    install_parser.add_argument("--exact-action-source-hash", required=True)
    install_parser.add_argument("--environment-source-hash", required=True)
    install_parser.add_argument("--observation-abi", required=True)
    install_parser.add_argument("--observation-version", type=int, required=True)
    engine_parser = subparsers.add_parser("engine-source-sha256")
    engine_parser.add_argument("--root", type=Path, required=True)
    environment_parser = subparsers.add_parser("environment-source-sha256")
    environment_parser.add_argument("--root", type=Path, required=True)
    environment_parser.add_argument("--plain", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "validate-installed":
        if len(args.selector_family) != 1 or len(args.selector_threshold) != 1:
            parser.error(
                "validate-installed requires exactly one selector family "
                "and threshold"
            )
        args.selector_family = args.selector_family[0]
        args.selector_threshold = args.selector_threshold[0]
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "validate-request":
            result = validate_artifact_request(
                bank_path=args.bank,
                bank_sha256=args.bank_sha256,
                producer_manifest_path=args.producer_manifest,
                producer_manifest_sha256=args.producer_manifest_sha256,
                training_contract_path=args.training_contract,
                training_contract_sha256=args.training_contract_sha256,
                kind=args.kind,
                engine_root=args.engine_root,
            )
        elif args.command == "validate-installed":
            result = validate_installed(
                puffer_root=args.puffer_root,
                kind=args.kind,
                bank_sha256=args.bank_sha256,
                producer_manifest_sha256=args.producer_manifest_sha256,
                training_contract_sha256=args.training_contract_sha256,
                selector_family=args.selector_family,
                selector_threshold=args.selector_threshold,
            )
        elif args.command == "show-installed":
            result = show_installed(args.puffer_root)
        elif args.command == "check-no-bank":
            result = check_no_bank_install(args.puffer_root)
        elif args.command == "install-no-bank":
            install_no_bank_contract(
                args.puffer_root,
                exact_action_source_hash=args.exact_action_source_hash,
                environment_source_hash=args.environment_source_hash,
                observation_abi=args.observation_abi,
                observation_version=args.observation_version,
            )
            result = check_no_bank_install(args.puffer_root)
        elif args.command == "engine-source-sha256":
            result = {"engine_source_sha256": engine_source_sha256(args.root)}
        elif args.command == "environment-source-sha256":
            environment_hash = environment_source_sha256(args.root)
            if args.plain:
                print(environment_hash)
                return 0
            result = {"environment_source_sha256": environment_hash}
        else:  # pragma: no cover - argparse owns the command set
            raise AssertionError(args.command)
    except (OSError, StateBankContractError, ValueError) as exc:
        print(f"state-bank contract failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
