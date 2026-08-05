#!/usr/bin/env python3
"""Shared, standard-library-only protocol authority for the sealed F5 pilot."""

import ctypes as _ctypes
import errno as _errno
import hashlib as _hashlib
import json as _json
import math as _math
import os as _os
import re as _re
import stat as _stat
import struct as _struct
import subprocess as _subprocess


CANONICAL_SCHEMA = "bloodbowl-f5-recurrent-ppo-pilot-v1"
PROTOCOL_PATH = _os.path.abspath(
    _os.path.join(
        _os.path.dirname(__file__),
        "..",
        "training",
        "f5_recurrent_ppo_pilot.json",
    )
)
IMPLEMENTATION_PATHS = (
    ".github/workflows/ci.yml",
    "docs/plans/f5-recurrent-ppo-pilot.md",
    "tools/f5_recurrent_ppo_protocol.py",
    "tools/run_f5_recurrent_ppo_pilot.py",
    "tools/test_f5_recurrent_ppo_pilot.py",
    "tools/verify_f5_recurrent_ppo_pilot.py",
    "training/f5_recurrent_ppo_pilot.json",
)

EXPECTED_INITIAL_PARAMETER_SHA256 = (
    "61e509fc5759940cedf557ea773d3d89bff35d2897082916c80a2f65c88c8882"
)
EXPECTED_INITIAL_RAW_SHA256 = (
    "7d1a0e03f06b2f5e6142159b41a42bc07e01dca5400d8c4084ca6ea455e16007"
)
WRONG_ORDER_PARAMETER_SHA256 = (
    "97caeec26dcfefd621f5c51ea94c71254b650f66cfbbaa508fdae5dfd1514d60"
)
EXPECTED_ONE_UPDATE_PARAMETER_SHA256 = (
    "bd1410bd0725f4074d6fd63fd4e59b78ab77dbcf8dceea72261c948283a889d4"
)
EXPECTED_ONE_UPDATE_RAW_SHA256 = (
    "0eff42539736bc01d67282e1c98a864f4e76a4ef91951d9f4749d3251b60a9b8"
)

RENAME_EXCL = 0x00000004
ACL_TYPE_EXTENDED = 0x00000100

_PUBLICATION_ACK_PREFIX = b"bloodbowl-f5-publication-ack-v1 "
_PUBLICATION_RESULT_STATUSES = frozenset(
    ("published", "publication-indeterminate")
)
_PUBLICATION_MAX_FRAME_BYTES = 4096
_DARWIN_NAME_MAX = 255

_PROTOCOL_BYTES = 183769
_PROTOCOL_SHA256 = (
    "82cdcb75980a08c0231a3c371a7e6a20edc2d14debd679badb366098b465f9a1"
)
_SCHEMA_REGISTRY_SHA256 = (
    "95a7225b36877daf5877b30e6bfd2568b53bab8e2857e1e8686aa49c40032efc"
)
_PLAN_COMMIT = "5fb527d1c270bd44754b75bcbe866e5128790572"
_REGISTRY_SCHEMA = "bloodbowl-f5-schema-registry-v1"
_REGISTRY_ROOT_NAMES = frozenset(
    (
        "effective-config.json",
        "evidence-manifest.json",
        "identity.json",
        "results.json",
        "training-trace.jsonl",
        "verdict.json",
        "wilson95",
    )
)
_PROTOCOL_ROOT_NAMES = frozenset(
    (
        "artifact",
        "budget",
        "checkpoints",
        "environment",
        "evaluation",
        "execution",
        "optimizer",
        "plan_commit",
        "policy",
        "puffer",
        "runtime",
        "schema",
        "seeds",
        "source",
    )
)
_FORM_KEYS = {
    "array": frozenset(
        (
            "items",
            "kind",
            "maximum_length",
            "minimum_length",
            "ordered",
        )
    ),
    "boolean": frozenset(("kind",)),
    "enum": frozenset(("kind", "values")),
    "integer": frozenset(("kind", "maximum", "minimum")),
    "literal": frozenset(("kind", "value")),
    "null": frozenset(("kind",)),
    "number": frozenset(("finite", "kind", "maximum", "minimum")),
    "object": frozenset(("closed", "fields", "kind")),
    "ref": frozenset(("kind", "name")),
    "string": frozenset(("format", "kind")),
    "tuple": frozenset(("items", "kind")),
    "union": frozenset(("kind", "options")),
}
_FORMATS = frozenset(
    ("absolute-path", "ascii", "git-object", "relative-path", "sha256")
)


class ProtocolError(RuntimeError):
    """The candidate violated a closed F5 protocol contract."""


class RolloutAlignmentError(ProtocolError):
    """A rollout topology fault with a bounded public failure record."""

    def __init__(self, message, rollout):
        ProtocolError.__init__(self, message)
        self.rollout = rollout


def _fail(message):
    raise ProtocolError(message)


def _is_exact_int(value):
    return type(value) is int


def _is_exact_float(value):
    return type(value) is float


def _float_bits(value):
    return _struct.pack(">d", value)


def _is_negative_zero(value):
    return (
        type(value) is float
        and value == 0.0
        and _float_bits(value) == _float_bits(-0.0)
    )


def _require_ascii(value, label, printable=False, nonempty=False):
    if type(value) is not str:
        _fail(label + " must be an exact string")
    if nonempty and not value:
        _fail(label + " must not be empty")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        _fail(label + " must be ASCII")
    if printable and any(byte < 0x20 or byte > 0x7E for byte in encoded):
        _fail(label + " must be printable ASCII")
    return encoded


def _is_lower_hex(value, width):
    return (
        type(value) is str
        and len(value) == width
        and all(character in "0123456789abcdef" for character in value)
    )


def _validate_json_value(value, location="$"):
    value_type = type(value)
    if value is None or value_type in (bool, int, str):
        return
    if value_type is float:
        if not _math.isfinite(value):
            _fail(location + ": non-finite JSON number")
        if _is_negative_zero(value):
            _fail(location + ": negative-zero JSON number")
        return
    if value_type is list:
        for index, item in enumerate(value):
            _validate_json_value(item, "%s[%d]" % (location, index))
        return
    if value_type is dict:
        for key, item in value.items():
            _require_ascii(key, location + ": object key")
            _validate_json_value(item, location + "." + key)
        return
    _fail(location + ": value is not an exact JSON type")


def canonical_json_bytes(value):
    """Return the one canonical ASCII JSON representation, including one LF."""

    try:
        _validate_json_value(value)
        text = _json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return (text + "\n").encode("ascii")
    except ProtocolError:
        raise
    except (
        TypeError,
        ValueError,
        UnicodeEncodeError,
        RecursionError,
    ) as error:
        raise ProtocolError("canonical JSON serialization failed") from error


def _reject_json_constant(token):
    _fail("non-finite JSON constant is forbidden: " + token)


def _parse_json_float(token):
    value = float(token)
    if not _math.isfinite(value):
        _fail("non-finite JSON float is forbidden")
    if _is_negative_zero(value):
        _fail("negative-zero JSON float is forbidden")
    return value


def _reject_duplicate_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            _fail("duplicate JSON key: " + key)
        result[key] = value
    return result


def _parse_canonical_json(raw, label):
    if type(raw) is not bytes:
        _fail(label + ": raw JSON must be exact bytes")
    try:
        text = raw.decode("ascii")
    except UnicodeDecodeError as error:
        raise ProtocolError(label + ": JSON is not ASCII") from error
    try:
        value = _json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
            parse_float=_parse_json_float,
        )
    except ProtocolError:
        raise
    except (
        TypeError,
        ValueError,
        _json.JSONDecodeError,
        RecursionError,
    ) as error:
        raise ProtocolError(label + ": invalid JSON") from error
    if canonical_json_bytes(value) != raw:
        _fail(label + ": JSON is not canonical ASCII plus exactly one LF")
    return value


_WORKER_JOB_ORDINARY_EXCEPTIONS = (
    AttributeError,
    IndexError,
    KeyError,
    OverflowError,
    RecursionError,
    TypeError,
    UnicodeError,
    ValueError,
    _struct.error,
)


def _normalize_worker_job_field_spec(specification, label):
    if type(specification) is not dict:
        _fail(label + ": field specification must be an exact object")
    kind = specification.get("kind")
    if type(kind) is not str:
        _fail(label + ": field kind must be an exact string")
    if kind == "literal":
        if set(specification) != {"kind", "value"}:
            _fail(label + ": literal field specification keys mismatch")
        value = specification["value"]
        if type(value) is not str:
            _fail(label + ": job literal must be an exact string")
        return ("literal", value)
    if kind == "enum":
        if set(specification) != {"kind", "values"}:
            _fail(label + ": enum field specification keys mismatch")
        values = specification["values"]
        if type(values) is not list or not values:
            _fail(label + ": enum values must be a nonempty exact list")
        normalized = []
        for index, value in enumerate(values):
            if type(value) not in (int, str):
                _fail(
                    "%s: enum value %d has an unsupported exact type"
                    % (label, index)
                )
            if any(_strict_equal(value, prior) for prior in normalized):
                _fail(label + ": enum values must be type-strictly unique")
            normalized.append(value)
        return ("enum", tuple(normalized))
    if kind == "integer":
        if set(specification) != {"kind", "maximum", "minimum"}:
            _fail(label + ": integer field specification keys mismatch")
        minimum = specification["minimum"]
        maximum = specification["maximum"]
        if (
            type(minimum) is not int
            or type(maximum) is not int
            or minimum > maximum
        ):
            _fail(label + ": integer field bounds are invalid")
        return ("integer", minimum, maximum)
    if kind == "string":
        keys = set(specification)
        if keys == {"format", "kind"}:
            format_name = specification["format"]
            if format_name not in {
                "absolute-path",
                "git-object",
                "sha256",
            }:
                _fail(label + ": string field format is unsupported")
            return ("string", format_name)
        if keys == {"kind", "pattern"}:
            pattern = specification["pattern"]
            if pattern != "^[0-9a-f]{32}$" or type(pattern) is not str:
                _fail(label + ": string field pattern is unsupported")
            return ("pattern", pattern)
        _fail(label + ": string field specification keys mismatch")
    _fail(label + ": field specification kind is unsupported")


def _normalize_worker_job_schema(node, expected_fields, label):
    if type(node) is not dict or set(node) != {
        "closed",
        "field_specs",
        "fields",
        "schema",
    }:
        _fail(label + ": schema node keys mismatch")
    if node["closed"] is not True:
        _fail(label + ": schema is not closed")
    fields = node["fields"]
    field_specs = node["field_specs"]
    schema = node["schema"]
    if type(fields) is not list:
        _fail(label + ": fields must be an exact list")
    if any(type(name) is not str for name in fields):
        _fail(label + ": fields must contain exact strings")
    if len(fields) != len(set(fields)):
        _fail(label + ": fields must be unique")
    if tuple(fields) != expected_fields:
        _fail(label + ": frozen field order or membership mismatch")
    if type(field_specs) is not dict or set(field_specs) != set(fields):
        _fail(label + ": field specifications do not match fields")
    if type(schema) is not str:
        _fail(label + ": schema label must be an exact string")
    normalized = tuple(
        (
            name,
            _normalize_worker_job_field_spec(
                field_specs[name],
                label + "." + name,
            ),
        )
        for name in fields
    )
    descriptors = dict(normalized)
    if descriptors.get("schema") != ("literal", schema):
        _fail(label + ": schema label and literal descriptor disagree")
    return (schema, tuple(fields), normalized)


def _worker_job_strict_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is tuple:
        return len(left) == len(right) and all(
            _worker_job_strict_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return _strict_equal(left, right)


def _validate_worker_job_leaf(
    value,
    descriptor,
    label,
    maximum_path_bytes,
):
    kind = descriptor[0]
    if kind == "literal":
        if not _strict_equal(value, descriptor[1]):
            _fail(label + ": literal mismatch")
        return
    if kind == "enum":
        if not any(
            _strict_equal(value, member) for member in descriptor[1]
        ):
            _fail(label + ": enum mismatch")
        return
    if kind == "integer":
        if type(value) is not int:
            _fail(label + ": expected exact integer")
        if not descriptor[1] <= value <= descriptor[2]:
            _fail(label + ": integer outside frozen bounds")
        return
    if kind == "string":
        format_name = descriptor[1]
        if type(value) is not str:
            _fail(label + ": formatted value must be an exact string")
        if format_name == "absolute-path" and len(value) > maximum_path_bytes:
            _fail(label + ": absolute path exceeds the frozen byte cap")
        if format_name == "sha256" and len(value) != 64:
            _fail(label + ": string format mismatch")
        if format_name == "git-object" and len(value) != 40:
            _fail(label + ": string format mismatch")
        if not _validate_format(value, format_name):
            _fail(label + ": string format mismatch")
        if format_name == "absolute-path":
            encoded = _require_ascii(
                value,
                label,
                printable=True,
                nonempty=True,
            )
            if len(encoded) > maximum_path_bytes:
                _fail(label + ": absolute path exceeds the frozen byte cap")
        return
    if kind == "pattern":
        if not _is_lower_hex(value, 32):
            _fail(label + ": nonce pattern mismatch")
        return
    _fail(label + ": normalized field kind is unsupported")


def _worker_job_schema_descriptors(schema):
    return dict(schema[2])


def _normalize_worker_population_member(
    member,
    keys,
    descriptors,
    maximum_path_bytes,
    label,
):
    if type(member) is not dict or set(member) != set(keys):
        _fail(label + ": population member keys mismatch")
    values = []
    for key in keys:
        value = member[key]
        _validate_worker_job_leaf(
            value,
            descriptors[key],
            label + "." + key,
            maximum_path_bytes,
        )
        values.append(value)
    return tuple(values)


def _normalize_worker_job_contract(manifest):
    if type(manifest) is not dict:
        _fail("worker job manifest must be an exact object")
    execution = manifest["execution"]
    if type(execution) is not dict:
        _fail("worker job execution authority must be an exact object")
    worker_ipc = execution["worker_ipc"]
    audit = execution["audit"]
    if type(worker_ipc) is not dict or type(audit) is not dict:
        _fail("worker job execution nodes must be exact objects")
    job = worker_ipc["job"]
    if type(job) is not dict or set(job) != {
        "common_rules",
        "digest",
        "frame",
        "schemas",
        "semantic_rules",
    }:
        _fail("worker job contract root keys mismatch")

    common_rules = job["common_rules"]
    if type(common_rules) is not dict or set(common_rules) != {
        "job_nonce",
        "maximum_path_bytes",
        "path_encoding",
        "seed-budget-device-output-overrides_allowed",
    }:
        _fail("worker job common-rule keys mismatch")
    if (
        common_rules["maximum_path_bytes"] != 1024
        or type(common_rules["maximum_path_bytes"]) is not int
        or common_rules["path_encoding"]
        != "printable-canonical-absolute-ASCII"
        or type(common_rules["path_encoding"]) is not str
        or common_rules[
            "seed-budget-device-output-overrides_allowed"
        ]
        is not False
        or type(common_rules["job_nonce"]) is not dict
        or not _exact_json_equal(
            common_rules["job_nonce"],
            {
                "call": "os.urandom(16).hex()",
                "characters": 32,
                "encoding": "lowercase-hex",
            },
        )
    ):
        _fail("worker job common rules mismatch")
    maximum_path_bytes = common_rules["maximum_path_bytes"]

    frame = job["frame"]
    if type(frame) is not dict or set(frame) != {
        "canonical_ascii_json",
        "canonical_record_count",
        "eof_required",
        "final_lf",
        "length_encoding",
        "maximum_record_bytes",
        "trailing_bytes_allowed",
    }:
        _fail("worker job frame-rule keys mismatch")
    if (
        frame["canonical_ascii_json"] is not True
        or frame["canonical_record_count"] != 1
        or type(frame["canonical_record_count"]) is not int
        or frame["eof_required"] is not True
        or frame["final_lf"] is not True
        or frame["length_encoding"] != "uint32-be"
        or type(frame["length_encoding"]) is not str
        or frame["maximum_record_bytes"] != 4096
        or type(frame["maximum_record_bytes"]) is not int
        or frame["trailing_bytes_allowed"] is not False
    ):
        _fail("worker job frame rules mismatch")
    maximum_record_bytes = frame["maximum_record_bytes"]

    digest = job["digest"]
    if type(digest) is not dict or set(digest) != {
        "algorithm",
        "domain_ascii",
        "domain_terminator",
        "preimage",
    }:
        _fail("worker job digest-rule keys mismatch")
    if not _exact_json_equal(
        digest,
        {
            "algorithm": "SHA-256",
            "domain_ascii": "bloodbowl-f5-worker-job-v1",
            "domain_terminator": "NUL",
            "preimage": "domain-then-complete-canonical-job-bytes",
        },
    ):
        _fail("worker job digest rules mismatch")
    digest_domain = _require_ascii(
        digest["domain_ascii"],
        "worker job digest domain",
        printable=True,
        nonempty=True,
    )

    semantic_rules = job["semantic_rules"]
    if type(semantic_rules) is not dict or not _exact_json_equal(
        semantic_rules,
        {
            "evaluation_checkpoint_path": (
                "derived-from-artifact_root-and-checkpoint_update"
            ),
            "evaluation_checkpoint_path_supplied_in_job": False,
            "evaluation_tuple": (
                "next-exact-manifest-owned-population-member"
            ),
            "training_deadline_not_after_whole": True,
        },
    ):
        _fail("worker job semantic rules mismatch")

    schemas = job["schemas"]
    if type(schemas) is not dict or set(schemas) != {
        "evaluation",
        "training",
    }:
        _fail("worker job schema-map keys mismatch")
    training_fields = (
        "artifact_root",
        "implementation_manifest_sha256",
        "nonce",
        "protocol_sha256",
        "puffer_root",
        "schema",
        "source_commit",
        "source_root",
        "supervisor_pid",
        "training_deadline_monotonic_ns",
        "whole_deadline_monotonic_ns",
        "worker_kind",
    )
    evaluation_fields = (
        "action_seed",
        "artifact_root",
        "checkpoint_raw_sha256",
        "checkpoint_tensor_sha256",
        "checkpoint_update",
        "implementation_manifest_sha256",
        "nonce",
        "population",
        "protocol_sha256",
        "puffer_root",
        "repeat_flag",
        "schema",
        "seed_index",
        "source_commit",
        "source_root",
        "supervisor_pid",
        "whole_deadline_monotonic_ns",
        "worker_kind",
    )
    training_schema = _normalize_worker_job_schema(
        schemas["training"],
        training_fields,
        "worker job training schema",
    )
    evaluation_schema = _normalize_worker_job_schema(
        schemas["evaluation"],
        evaluation_fields,
        "worker job evaluation schema",
    )
    training_descriptors = _worker_job_schema_descriptors(training_schema)
    evaluation_descriptors = _worker_job_schema_descriptors(evaluation_schema)
    if (
        training_schema[0] != "bloodbowl-f5-training-worker-job-v1"
        or training_descriptors["worker_kind"] != ("literal", "training")
        or evaluation_schema[0]
        != "bloodbowl-f5-evaluation-worker-job-v1"
        or evaluation_descriptors["worker_kind"]
        != ("literal", "evaluation")
    ):
        _fail("worker job schema literals mismatch")

    shared_descriptor_roles = {
        "artifact_root": ("string", "absolute-path"),
        "implementation_manifest_sha256": ("string", "sha256"),
        "nonce": ("pattern", "^[0-9a-f]{32}$"),
        "protocol_sha256": ("string", "sha256"),
        "puffer_root": ("string", "absolute-path"),
        "source_commit": ("string", "git-object"),
        "source_root": ("string", "absolute-path"),
        "supervisor_pid": ("integer", 1, 2147483647),
        "whole_deadline_monotonic_ns": (
            "integer",
            1,
            9223372036854775807,
        ),
    }
    for name, expected in shared_descriptor_roles.items():
        if (
            not _worker_job_strict_equal(
                training_descriptors[name],
                expected,
            )
            or not _worker_job_strict_equal(
                evaluation_descriptors[name],
                expected,
            )
        ):
            _fail("worker job shared descriptor role mismatch: " + name)
    if not _worker_job_strict_equal(
        training_descriptors["training_deadline_monotonic_ns"],
        ("integer", 1, 9223372036854775807),
    ):
        _fail("worker training deadline descriptor mismatch")
    evaluation_fixed_roles = {
        "checkpoint_raw_sha256": ("string", "sha256"),
        "checkpoint_tensor_sha256": ("string", "sha256"),
        "population": ("enum", ("controller", "verifier")),
        "repeat_flag": ("enum", (0, 1)),
        "seed_index": ("integer", 0, 7),
    }
    for name, expected in evaluation_fixed_roles.items():
        if not _worker_job_strict_equal(
            evaluation_descriptors[name],
            expected,
        ):
            _fail("worker evaluation descriptor role mismatch: " + name)

    updates_descriptor = evaluation_descriptors["checkpoint_update"]
    seeds_descriptor = evaluation_descriptors["seed_index"]
    actions_descriptor = evaluation_descriptors["action_seed"]
    repeat_descriptor = evaluation_descriptors["repeat_flag"]
    if (
        updates_descriptor[0] != "enum"
        or actions_descriptor[0] != "enum"
        or seeds_descriptor[0] != "integer"
        or repeat_descriptor != ("enum", (0, 1))
    ):
        _fail("worker evaluation schedule descriptors mismatch")
    updates = updates_descriptor[1]
    action_seeds = actions_descriptor[1]
    seed_minimum = seeds_descriptor[1]
    seed_maximum = seeds_descriptor[2]
    if (
        not updates
        or not all(type(value) is int for value in updates)
        or not all(type(value) is int for value in action_seeds)
        or not _strict_equal(updates[0], 0)
    ):
        _fail("worker evaluation schedule enum values mismatch")
    seed_count = seed_maximum - seed_minimum + 1
    if (
        seed_count <= 0
        or seed_count != len(action_seeds)
        or (len(updates) + 1) * seed_count != 56
    ):
        _fail("worker evaluation seed/action cardinality mismatch")
    seed_indices = tuple(range(seed_minimum, seed_maximum + 1))

    evaluation_keys = (
        "action_seed",
        "checkpoint_update",
        "repeat_flag",
        "seed_index",
        "worker_kind",
    )
    expected_evaluations = []
    for update in updates:
        for position, seed_index in enumerate(seed_indices):
            expected_evaluations.append(
                (
                    action_seeds[position],
                    update,
                    0,
                    seed_index,
                    "evaluation",
                )
            )
    for position, seed_index in enumerate(seed_indices):
        expected_evaluations.append(
            (
                action_seeds[position],
                updates[0],
                1,
                seed_index,
                "evaluation",
            )
        )
    expected_evaluations = tuple(expected_evaluations)
    if len(expected_evaluations) != 56:
        _fail("worker evaluation derived population count mismatch")

    aggregation = audit["aggregation"]
    if type(aggregation) is not dict:
        _fail("worker population aggregation must be an exact object")
    controller_node = aggregation["controller"]
    verifier_node = aggregation["verifier"]
    if type(controller_node) is not dict or type(verifier_node) is not dict:
        _fail("worker population owner nodes must be exact objects")
    controller_raw = controller_node["ordered_population"]
    verifier_raw = verifier_node["ordered_population"]
    if (
        type(controller_raw) is not list
        or len(controller_raw) != 57
        or type(verifier_raw) is not list
        or len(verifier_raw) != 56
    ):
        _fail("worker population list type or count mismatch")

    training_keys = ("worker_kind",)
    controller = (
        _normalize_worker_population_member(
            controller_raw[0],
            training_keys,
            training_descriptors,
            maximum_path_bytes,
            "controller population member 0",
        ),
    ) + tuple(
        _normalize_worker_population_member(
            member,
            evaluation_keys,
            evaluation_descriptors,
            maximum_path_bytes,
            "controller population member %d" % index,
        )
        for index, member in enumerate(controller_raw[1:], start=1)
    )
    verifier = tuple(
        _normalize_worker_population_member(
            member,
            evaluation_keys,
            evaluation_descriptors,
            maximum_path_bytes,
            "verifier population member %d" % index,
        )
        for index, member in enumerate(verifier_raw)
    )
    expected_controller = (("training",),) + expected_evaluations
    if not _worker_job_strict_equal(controller, expected_controller):
        _fail("controller worker population order mismatch")
    if not _worker_job_strict_equal(verifier, expected_evaluations):
        _fail("verifier worker population order mismatch")

    return (
        maximum_record_bytes,
        maximum_path_bytes,
        digest_domain,
        training_schema,
        evaluation_schema,
        expected_controller,
        expected_evaluations,
    )


def _worker_job_contract():
    try:
        return _normalize_worker_job_contract(load_protocol_manifest())
    except ProtocolError:
        raise
    except _WORKER_JOB_ORDINARY_EXCEPTIONS as error:
        raise ProtocolError("worker job contract normalization failed") from error


def _worker_job_projection(job, keys):
    return tuple(job[key] for key in keys)


def _validated_worker_job(job, owner, ordinal, contract):
    (
        _maximum_record_bytes,
        maximum_path_bytes,
        _digest_domain,
        training_schema,
        evaluation_schema,
        controller_population,
        verifier_population,
    ) = contract
    if type(job) is not dict:
        _fail("worker job must be an exact object")
    allowed_counts = {len(training_schema[1]), len(evaluation_schema[1])}
    if len(job) not in allowed_counts:
        _fail("worker job field count mismatch")
    if any(type(key) is not str for key in job):
        _fail("worker job keys must be exact strings")

    worker_kind = job.get("worker_kind")
    schema_name = job.get("schema")
    if type(worker_kind) is not str or type(schema_name) is not str:
        _fail("worker job selectors must be exact strings")
    if worker_kind == "training":
        schema = training_schema
    elif worker_kind == "evaluation":
        schema = evaluation_schema
    else:
        _fail("worker job kind is unsupported")
    if schema_name != schema[0]:
        _fail("worker job schema and kind mismatch")

    owner_omitted = owner is None
    ordinal_omitted = ordinal is None
    if owner_omitted != ordinal_omitted:
        _fail("worker job owner and ordinal must be supplied together")
    ordered_population = None
    if not owner_omitted:
        if (
            type(owner) is not str
            or len(owner) > len("controller")
            or owner not in ("controller", "verifier")
        ):
            _fail("worker job owner is unsupported")
        if type(ordinal) is not int:
            _fail("worker job ordinal must be an exact integer")
        ordered_population = (
            controller_population
            if owner == "controller"
            else verifier_population
        )
        if not 0 <= ordinal < len(ordered_population):
            _fail("worker job ordinal is outside the population")

    if set(job) != set(schema[1]):
        _fail("worker job closed fields mismatch")
    descriptors = _worker_job_schema_descriptors(schema)
    for name in schema[1]:
        _validate_worker_job_leaf(
            job[name],
            descriptors[name],
            "worker job." + name,
            maximum_path_bytes,
        )

    if worker_kind == "training":
        if (
            job["training_deadline_monotonic_ns"]
            > job["whole_deadline_monotonic_ns"]
        ):
            _fail("worker training deadline exceeds whole deadline")
        projection = (job["worker_kind"],)
        if ordered_population is not None and not _worker_job_strict_equal(
            projection,
            ordered_population[ordinal],
        ):
            _fail("worker training job is not the exact ordered member")
    else:
        population_name = job["population"]
        if type(population_name) is not str or population_name not in {
            "controller",
            "verifier",
        }:
            _fail("worker evaluation population is unsupported")
        evaluation_keys = (
            "action_seed",
            "checkpoint_update",
            "repeat_flag",
            "seed_index",
            "worker_kind",
        )
        projection = _worker_job_projection(job, evaluation_keys)
        context_population = (
            controller_population[1:]
            if population_name == "controller"
            else verifier_population
        )
        if not any(
            _worker_job_strict_equal(projection, member)
            for member in context_population
        ):
            _fail("worker evaluation job is not a population member")
        if ordered_population is not None:
            if population_name != owner:
                _fail("worker evaluation owner and population mismatch")
            if not _worker_job_strict_equal(
                projection,
                ordered_population[ordinal],
            ):
                _fail("worker evaluation job is not the exact ordered member")
    return dict(job)


def _validated_worker_job_and_body(job, owner, ordinal, contract):
    validated = _validated_worker_job(job, owner, ordinal, contract)
    body = canonical_json_bytes(validated)
    maximum_record_bytes = contract[0]
    if not 1 <= len(body) <= maximum_record_bytes:
        _fail("worker job canonical body exceeds the frozen byte cap")
    return validated, body


def _worker_job_digest(body, contract):
    return _hashlib.sha256(contract[2] + b"\0" + body).hexdigest()


def validate_worker_job(job, *, owner=None, ordinal=None):
    """Return a fresh dict after exact worker-job validation."""

    try:
        contract = _worker_job_contract()
        validated, _body = _validated_worker_job_and_body(
            job,
            owner,
            ordinal,
            contract,
        )
        return validated
    except ProtocolError:
        raise
    except _WORKER_JOB_ORDINARY_EXCEPTIONS as error:
        raise ProtocolError("worker job validation failed") from error


def encode_worker_job(job, *, owner=None, ordinal=None):
    """Return uint32-be length followed by one validated canonical job body."""

    try:
        contract = _worker_job_contract()
        _validated, body = _validated_worker_job_and_body(
            job,
            owner,
            ordinal,
            contract,
        )
        return _struct.pack(">I", len(body)) + body
    except ProtocolError:
        raise
    except _WORKER_JOB_ORDINARY_EXCEPTIONS as error:
        raise ProtocolError("worker job encoding failed") from error


def worker_job_sha256(job, *, owner=None, ordinal=None):
    """Hash the validated canonical body, excluding its uint32 wire prefix."""

    try:
        contract = _worker_job_contract()
        _validated, body = _validated_worker_job_and_body(
            job,
            owner,
            ordinal,
            contract,
        )
        return _worker_job_digest(body, contract)
    except ProtocolError:
        raise
    except _WORKER_JOB_ORDINARY_EXCEPTIONS as error:
        raise ProtocolError("worker job digest failed") from error


def parse_worker_job_wire(wire, *, owner=None, ordinal=None):
    """Validate one complete captured job-record buffer.

    Bytes trailing within wire are rejected. This function neither reads nor
    establishes EOF on an underlying descriptor; the bounded fd reader must
    prove channel EOF separately.
    """

    try:
        if type(wire) is not bytes:
            _fail("worker job wire must be exact bytes")
        if len(wire) < 4:
            _fail("worker job wire has a short length prefix")
        declared = _struct.unpack(">I", wire[:4])[0]
        contract = _worker_job_contract()
        maximum_record_bytes = contract[0]
        if not 1 <= declared <= maximum_record_bytes:
            _fail("worker job declared length is outside the frozen cap")
        if len(wire) != 4 + declared:
            _fail("worker job wire body length or closure mismatch")
        body = wire[4:]
        document = _parse_canonical_json(body, "worker job")
        if type(document) is not dict:
            _fail("worker job top level must be an exact object")
        validated, canonical = _validated_worker_job_and_body(
            document,
            owner,
            ordinal,
            contract,
        )
        if canonical != body:
            _fail("worker job canonical body changed during validation")
        return (validated, _worker_job_digest(body, contract))
    except ProtocolError:
        raise
    except _WORKER_JOB_ORDINARY_EXCEPTIONS as error:
        raise ProtocolError("worker job wire parsing failed") from error


def _identity_tuple(metadata):
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_nlink,
        metadata.st_size,
        getattr(metadata, "st_mtime_ns", None),
        getattr(metadata, "st_ctime_ns", None),
    )


def _close_descriptor_transaction(
    descriptor,
    label,
    *,
    suppress_errors,
):
    if type(suppress_errors) is not bool:
        _fail(label + ": cleanup mode must be an exact Boolean")
    try:
        _os.close(descriptor)
    except Exception as error:
        if not suppress_errors:
            raise ProtocolError(label + ": descriptor close failed") from error


def _read_fixed_regular_file(path, expected_size, expected_mode, label):
    completed = False
    try:
        path_value = _os.fspath(path)
    except Exception as error:
        raise ProtocolError(label + ": path coercion failed") from error
    if type(path_value) is not str or not _os.path.isabs(path_value):
        _fail(label + ": path must be an absolute string path")
    try:
        before_path = _os.lstat(path_value)
    except OSError as error:
        raise ProtocolError(label + ": lstat failed") from error
    if not _stat.S_ISREG(before_path.st_mode):
        _fail(label + ": path is not a regular file")
    if before_path.st_nlink != 1:
        _fail(label + ": path must be single-link")
    if _stat.S_IMODE(before_path.st_mode) != expected_mode:
        _fail(label + ": path mode mismatch")
    if before_path.st_size != expected_size:
        _fail(label + ": path size mismatch")

    flags = _os.O_RDONLY
    flags |= getattr(_os, "O_CLOEXEC", 0)
    flags |= getattr(_os, "O_NOFOLLOW", 0)
    try:
        descriptor = _os.open(path_value, flags)
    except OSError as error:
        raise ProtocolError(label + ": no-follow open failed") from error
    try:
        before_fd = _fstat_descriptor(descriptor, label)
        if _identity_tuple(before_fd) != _identity_tuple(before_path):
            _fail(label + ": descriptor/path identity mismatch")
        chunks = []
        remaining = expected_size + 1
        while remaining:
            try:
                chunk = _os.read(descriptor, min(65536, remaining))
            except (OSError, TypeError, ValueError) as error:
                raise ProtocolError(label + ": bounded read failed") from error
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != expected_size:
            _fail(label + ": bounded read size mismatch")
        after_fd = _fstat_descriptor(descriptor, label)
        if _identity_tuple(after_fd) != _identity_tuple(before_fd):
            _fail(label + ": descriptor changed during read")
        completed = True
    finally:
        _close_descriptor_transaction(
            descriptor,
            label,
            suppress_errors=not completed,
        )
    try:
        after_path = _os.lstat(path_value)
    except OSError as error:
        raise ProtocolError(label + ": post-read lstat failed") from error
    if _identity_tuple(after_path) != _identity_tuple(before_path):
        _fail(label + ": path changed during read")
    return raw


def _is_finite_json_scalar(value):
    if value is None or type(value) in (bool, int, str):
        return True
    return (
        type(value) is float
        and _math.isfinite(value)
        and not _is_negative_zero(value)
    )


def _strict_equal(value, expected):
    if type(value) is not type(expected):
        return False
    if type(value) is float:
        return _float_bits(value) == _float_bits(expected)
    return value == expected


def _exact_json_equal(left, right):
    if type(left) is not type(right):
        return False
    if type(left) is float:
        return _float_bits(left) == _float_bits(right)
    if type(left) is list:
        return len(left) == len(right) and all(
            _exact_json_equal(a, b) for a, b in zip(left, right)
        )
    if type(left) is dict:
        return set(left) == set(right) and all(
            _exact_json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _validate_descriptor(node, definitions, location):
    if type(node) is not dict or type(node.get("kind")) is not str:
        _fail(location + ": descriptor must be a tagged object")
    kind = node["kind"]
    if kind not in _FORM_KEYS or frozenset(node) != _FORM_KEYS[kind]:
        _fail(location + ": descriptor keys are not exact")

    if kind in ("boolean", "null"):
        return
    if kind == "literal":
        if not _is_finite_json_scalar(node["value"]):
            _fail(location + ": literal is not a finite JSON scalar")
        return
    if kind == "enum":
        values = node["values"]
        if type(values) is not list or not values:
            _fail(location + ": enum must be a nonempty array")
        fingerprints = set()
        for value in values:
            if not _is_finite_json_scalar(value):
                _fail(location + ": enum contains an invalid scalar")
            fingerprint = (type(value).__name__, canonical_json_bytes(value))
            if fingerprint in fingerprints:
                _fail(location + ": enum contains a duplicate scalar")
            fingerprints.add(fingerprint)
        return
    if kind == "integer":
        for bound_name in ("minimum", "maximum"):
            bound = node[bound_name]
            if bound is not None and type(bound) is not int:
                _fail(location + ": integer bound is not an exact integer")
        if (
            node["minimum"] is not None
            and node["maximum"] is not None
            and node["minimum"] > node["maximum"]
        ):
            _fail(location + ": reversed integer bounds")
        return
    if kind == "number":
        if node["finite"] is not True:
            _fail(location + ": number descriptor must require finiteness")
        for bound_name in ("minimum", "maximum"):
            bound = node[bound_name]
            if bound is not None and (
                type(bound) is not float or not _math.isfinite(bound)
            ):
                _fail(location + ": number bound is not an exact finite float")
            if _is_negative_zero(bound):
                _fail(location + ": negative-zero number bound")
        if (
            node["minimum"] is not None
            and node["maximum"] is not None
            and node["minimum"] > node["maximum"]
        ):
            _fail(location + ": reversed number bounds")
        return
    if kind == "string":
        if node["format"] not in _FORMATS:
            _fail(location + ": unsupported string format")
        return
    if kind == "array":
        if node["ordered"] is not True:
            _fail(location + ": arrays must be ordered")
        for bound_name in ("minimum_length", "maximum_length"):
            bound = node[bound_name]
            if type(bound) is not int or bound < 0:
                _fail(location + ": invalid array length bound")
        if node["minimum_length"] > node["maximum_length"]:
            _fail(location + ": reversed array length bounds")
        _validate_descriptor(node["items"], definitions, location + ".items")
        return
    if kind == "tuple":
        if type(node["items"]) is not list:
            _fail(location + ": tuple items must be an array")
        for index, child in enumerate(node["items"]):
            _validate_descriptor(
                child,
                definitions,
                "%s.items[%d]" % (location, index),
            )
        return
    if kind == "object":
        if node["closed"] is not True or type(node["fields"]) is not dict:
            _fail(location + ": object must have a closed field map")
        for name, child in node["fields"].items():
            _require_ascii(name, location + ": field name", nonempty=True)
            _validate_descriptor(child, definitions, location + "." + name)
        return
    if kind == "union":
        options = node["options"]
        if type(options) is not list or not options:
            _fail(location + ": union must have at least one option")
        fingerprints = set()
        for index, child in enumerate(options):
            _validate_descriptor(
                child,
                definitions,
                "%s.options[%d]" % (location, index),
            )
            fingerprint = canonical_json_bytes(child)
            if fingerprint in fingerprints:
                _fail(location + ": duplicate union option")
            fingerprints.add(fingerprint)
        return
    if kind == "ref":
        name = node["name"]
        if type(name) is not str or name not in definitions:
            _fail(location + ": unresolved schema reference")
        return
    _fail(location + ": unknown descriptor kind")


def _direct_references(node):
    kind = node["kind"]
    if kind == "ref":
        return set((node["name"],))
    if kind == "array":
        return _direct_references(node["items"])
    if kind == "tuple":
        result = set()
        for child in node["items"]:
            result.update(_direct_references(child))
        return result
    if kind == "object":
        result = set()
        for child in node["fields"].values():
            result.update(_direct_references(child))
        return result
    if kind == "union":
        result = set()
        for child in node["options"]:
            result.update(_direct_references(child))
        return result
    return set()


def _validate_registry_structure(registry, require_frozen_roots):
    if type(registry) is not dict or set(registry) != {
        "definitions",
        "roots",
        "schema",
    }:
        _fail("schema registry root keys are not exact")
    if registry["schema"] != _REGISTRY_SCHEMA:
        _fail("schema registry identifier mismatch")
    definitions = registry["definitions"]
    roots = registry["roots"]
    if type(definitions) is not dict or type(roots) is not dict:
        _fail("schema definitions and roots must be objects")
    if require_frozen_roots and set(roots) != _REGISTRY_ROOT_NAMES:
        _fail("schema registry root names are not exact")

    for name, node in definitions.items():
        _require_ascii(name, "schema definition name", nonempty=True)
        _validate_descriptor(node, definitions, "definitions." + name)
    for name, node in roots.items():
        _require_ascii(name, "schema root name", nonempty=True)
        _validate_descriptor(node, definitions, "roots." + name)
        if require_frozen_roots and node["kind"] != "ref":
            _fail("schema root is not a reference: " + name)

    graph = {
        name: _direct_references(node) for name, node in definitions.items()
    }
    visit_state = {}

    def visit(name):
        state = visit_state.get(name, 0)
        if state == 1:
            _fail("schema definition cycle: " + name)
        if state == 2:
            return
        visit_state[name] = 1
        for target in graph[name]:
            visit(target)
        visit_state[name] = 2

    for name in definitions:
        visit(name)

    if require_frozen_roots:
        reachable = set()

        def mark(name):
            if name in reachable:
                return
            reachable.add(name)
            for target in graph[name]:
                mark(target)

        for root in roots.values():
            mark(root["name"])
        if reachable != set(definitions):
            _fail("schema registry contains unreachable definitions")


def validate_schema_registry(registry):
    _validate_registry_structure(registry, True)
    digest = _hashlib.sha256(canonical_json_bytes(registry)).hexdigest()
    if digest != _SCHEMA_REGISTRY_SHA256:
        _fail("schema registry raw identity mismatch")


def _validate_format(value, format_name):
    if type(value) is not str:
        return False
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        return False
    if format_name == "ascii":
        return all(0x20 <= byte <= 0x7E for byte in encoded)
    if format_name == "sha256":
        return _is_lower_hex(value, 64)
    if format_name == "git-object":
        return _is_lower_hex(value, 40)
    if format_name in ("absolute-path", "relative-path"):
        absolute = value.startswith("/")
        if (format_name == "absolute-path") != absolute:
            return False
        if "\\" in value or "\0" in value or "\n" in value:
            return False
        components = value.split("/")
        if absolute:
            components = components[1:]
        return bool(components) and all(
            component not in ("", ".", "..") for component in components
        )
    return False


def _validate_schema_value(value, descriptor, registry, location="$"):
    kind = descriptor["kind"]
    if kind == "ref":
        return _validate_schema_value(
            value,
            registry["definitions"][descriptor["name"]],
            registry,
            location,
        )
    if kind == "boolean":
        if type(value) is not bool:
            _fail(location + ": expected exact Boolean")
        return
    if kind == "null":
        if value is not None:
            _fail(location + ": expected null")
        return
    if kind == "literal":
        if not _strict_equal(value, descriptor["value"]):
            _fail(location + ": literal mismatch")
        if type(value) is float and (
            not _math.isfinite(value) or _is_negative_zero(value)
        ):
            _fail(location + ": invalid floating literal")
        return
    if kind == "enum":
        if type(value) is float and (
            not _math.isfinite(value) or _is_negative_zero(value)
        ):
            _fail(location + ": invalid floating enum member")
        if not any(
            _strict_equal(value, member) for member in descriptor["values"]
        ):
            _fail(location + ": enum mismatch")
        return
    if kind == "integer":
        if type(value) is not int:
            _fail(location + ": expected exact integer")
        minimum = descriptor["minimum"]
        maximum = descriptor["maximum"]
        if minimum is not None and value < minimum:
            _fail(location + ": integer below minimum")
        if maximum is not None and value > maximum:
            _fail(location + ": integer above maximum")
        return
    if kind == "number":
        if type(value) is not float or not _math.isfinite(value):
            _fail(location + ": expected exact finite float")
        if _is_negative_zero(value):
            _fail(location + ": negative-zero number")
        minimum = descriptor["minimum"]
        maximum = descriptor["maximum"]
        if minimum is not None and value < minimum:
            _fail(location + ": number below minimum")
        if maximum is not None and value > maximum:
            _fail(location + ": number above maximum")
        return
    if kind == "string":
        if not _validate_format(value, descriptor["format"]):
            _fail(location + ": string format mismatch")
        return
    if kind == "array":
        if type(value) is not list:
            _fail(location + ": expected array")
        if not (
            descriptor["minimum_length"]
            <= len(value)
            <= descriptor["maximum_length"]
        ):
            _fail(location + ": array length mismatch")
        for index, item in enumerate(value):
            _validate_schema_value(
                item,
                descriptor["items"],
                registry,
                "%s[%d]" % (location, index),
            )
        return
    if kind == "tuple":
        if type(value) is not list or len(value) != len(descriptor["items"]):
            _fail(location + ": tuple shape mismatch")
        for index, child in enumerate(descriptor["items"]):
            _validate_schema_value(
                value[index],
                child,
                registry,
                "%s[%d]" % (location, index),
            )
        return
    if kind == "object":
        if type(value) is not dict:
            _fail(location + ": expected object")
        fields = descriptor["fields"]
        if set(value) != set(fields):
            _fail(location + ": closed object keys mismatch")
        for name, child in fields.items():
            _validate_schema_value(
                value[name],
                child,
                registry,
                location + "." + name,
            )
        return
    if kind == "union":
        accepted = 0
        for child in descriptor["options"]:
            try:
                _validate_schema_value(value, child, registry, location)
            except ProtocolError:
                continue
            accepted += 1
        if accepted != 1:
            _fail(location + ": union did not accept exactly one branch")
        return
    _fail(location + ": unsupported schema kind")


def validate_schema(value, schema, registry):
    _validate_registry_structure(registry, False)
    _validate_descriptor(schema, registry["definitions"], "$schema")
    _validate_schema_value(value, schema, registry)


def load_protocol_manifest():
    raw = _read_fixed_regular_file(
        PROTOCOL_PATH,
        _PROTOCOL_BYTES,
        0o644,
        "F5 protocol manifest",
    )
    if _hashlib.sha256(raw).hexdigest() != _PROTOCOL_SHA256:
        _fail("F5 protocol manifest SHA-256 mismatch")
    manifest = _parse_canonical_json(raw, "F5 protocol manifest")
    if type(manifest) is not dict or set(manifest) != _PROTOCOL_ROOT_NAMES:
        _fail("F5 protocol manifest root keys mismatch")
    if manifest["schema"] != CANONICAL_SCHEMA:
        _fail("F5 protocol manifest schema mismatch")
    if manifest["plan_commit"] != _PLAN_COMMIT:
        _fail("F5 protocol manifest plan commit mismatch")
    validate_schema_registry(manifest["artifact"]["schemas"])
    return manifest


class WorkerFrameParser:
    """Pure incremental authority for one authenticated worker stdout stream."""

    def __init__(self):
        self._state = "unbound"
        self._phase = None
        self._header_wire = bytearray()
        self._header_length = None
        self._header_snapshot = None
        self._topology = None
        self._failure_topology = None
        self._job_sha256 = None
        self._nonce = None
        self._next_index = 0
        self._declared_payload_bytes = None
        self._payload_remaining = None
        self._raw_sha256 = None
        self._active_failure = False

    def _ordinary_failure(self, label, error):
        self._state = "poisoned"
        if isinstance(error, ProtocolError):
            raise error
        raise ProtocolError(label + ": parser operation failed") from error

    def _clear_session(self):
        self._phase = None
        self._header_wire = bytearray()
        self._header_length = None
        self._header_snapshot = None
        self._topology = None
        self._failure_topology = None
        self._job_sha256 = None
        self._nonce = None
        self._next_index = 0
        self._declared_payload_bytes = None
        self._payload_remaining = None
        self._raw_sha256 = None
        self._active_failure = False

    def _require_phase(self, phase):
        if self._state != "bound" or self._phase != phase:
            _fail("worker frame parser phase mismatch")

    def _header_dict(self):
        values = self._header_snapshot
        return {
            "bytes": values[0],
            "frame_index": values[1],
            "job_sha256": values[2],
            "kind": values[3],
            "logical_name": values[4],
            "nonce": values[5],
            "raw_sha256": values[6],
            "schema": values[7],
            "semantic_sha256": values[8],
        }

    def _normalize_contract(self, manifest, job, job_sha256):
        if type(manifest) is not dict or type(job) is not dict:
            _fail("worker stream authority must be exact objects")
        if not _is_lower_hex(job_sha256, 64):
            _fail("worker job digest authority is malformed")
        worker_kind = job.get("worker_kind")
        nonce = job.get("nonce")
        if worker_kind not in ("training", "evaluation") or type(
            worker_kind
        ) is not str:
            _fail("worker kind authority is malformed")
        if not _is_lower_hex(nonce, 32):
            _fail("worker nonce authority is malformed")

        worker_ipc = manifest["execution"]["worker_ipc"]
        if type(worker_ipc) is not dict or set(worker_ipc) != {
            "audit_seal",
            "failure",
            "frame",
            "invocation",
            "job",
            "result_schemas",
            "streams",
            "worker_exit_codes",
        }:
            _fail("worker IPC authority keys mismatch")

        expected_header_schema = {
            "closed": True,
            "field_specs": {
                "bytes": {
                    "kind": "integer",
                    "maximum": 16777216,
                    "minimum": 0,
                },
                "frame_index": {
                    "kind": "integer",
                    "maximum": 7,
                    "minimum": 0,
                },
                "job_sha256": {"format": "sha256", "kind": "string"},
                "kind": {
                    "kind": "enum",
                    "values": [
                        "checkpoint",
                        "evaluation-bitset",
                        "evaluation-result",
                        "training-result",
                        "training-trace",
                        "worker-failure",
                    ],
                },
                "logical_name": {"format": "ascii", "kind": "string"},
                "nonce": {
                    "kind": "string",
                    "pattern": "^[0-9a-f]{32}$",
                },
                "raw_sha256": {"format": "sha256", "kind": "string"},
                "schema": {
                    "kind": "literal",
                    "value": "bloodbowl-f5-worker-payload-header-v1",
                },
                "semantic_sha256": {
                    "format": "sha256",
                    "kind": "string",
                },
            },
            "fields": [
                "bytes",
                "frame_index",
                "job_sha256",
                "kind",
                "logical_name",
                "nonce",
                "raw_sha256",
                "schema",
                "semantic_sha256",
            ],
            "schema": "bloodbowl-f5-worker-payload-header-v1",
        }
        expected_binding_schema = {
            "closed": True,
            "field_specs": {
                "bytes": {
                    "kind": "integer",
                    "maximum": 16777216,
                    "minimum": 0,
                },
                "frame_index": {
                    "kind": "integer",
                    "maximum": 7,
                    "minimum": 0,
                },
                "logical_name": {"format": "ascii", "kind": "string"},
                "raw_sha256": {"format": "sha256", "kind": "string"},
                "semantic_sha256": {
                    "format": "sha256",
                    "kind": "string",
                },
            },
            "fields": [
                "bytes",
                "frame_index",
                "logical_name",
                "raw_sha256",
                "semantic_sha256",
            ],
        }
        expected_frame = {
            "binding_schema": expected_binding_schema,
            "header_encoding": {
                "canonical_ascii_json": True,
                "exactly_one_final_lf": True,
                "length_encoding": "uint32-be",
            },
            "header_maximum_bytes": 4096,
            "header_schema": expected_header_schema,
            "incremental_drain_chunk_maximum_bytes": 65536,
            "payload_allocation_from_unchecked_length_allowed": False,
            "payload_verification": [
                "exact-declared-byte-count",
                "raw-sha256",
                "semantic-sha256-under-kind-domain",
            ],
            "pre_payload_validation_order": [
                "canonical-header-and-exact-field-schema",
                "next-frame-index",
                "next-kind",
                "next-logical-name",
                "job-sha256-equals-request",
                "nonce-equals-request",
                "kind-specific-size-cap",
                "then-read-payload",
            ],
            "spool": "supervisor-private-temporary-file",
        }
        if not _exact_json_equal(worker_ipc["frame"], expected_frame):
            _fail("worker frame authority mismatch")

        expected_training_sequence = [
            {
                "bytes_maximum": 16777216,
                "bytes_minimum": 1,
                "frame_index": 0,
                "kind": "training-trace",
                "logical_name": "training-trace.jsonl",
                "semantic_domain": "f5-training-trace-v1",
            },
            {
                "bytes_maximum": 879900,
                "bytes_minimum": 879900,
                "frame_index": 1,
                "kind": "checkpoint",
                "logical_name": "checkpoints/update-000000.f5w",
                "semantic_domain": "f5-canonical-tensors-v1",
            },
            {
                "bytes_maximum": 879900,
                "bytes_minimum": 879900,
                "frame_index": 2,
                "kind": "checkpoint",
                "logical_name": "checkpoints/update-000512.f5w",
                "semantic_domain": "f5-canonical-tensors-v1",
            },
            {
                "bytes_maximum": 879900,
                "bytes_minimum": 879900,
                "frame_index": 3,
                "kind": "checkpoint",
                "logical_name": "checkpoints/update-001024.f5w",
                "semantic_domain": "f5-canonical-tensors-v1",
            },
            {
                "bytes_maximum": 879900,
                "bytes_minimum": 879900,
                "frame_index": 4,
                "kind": "checkpoint",
                "logical_name": "checkpoints/update-001536.f5w",
                "semantic_domain": "f5-canonical-tensors-v1",
            },
            {
                "bytes_maximum": 879900,
                "bytes_minimum": 879900,
                "frame_index": 5,
                "kind": "checkpoint",
                "logical_name": "checkpoints/update-002048.f5w",
                "semantic_domain": "f5-canonical-tensors-v1",
            },
            {
                "bytes_maximum": 879900,
                "bytes_minimum": 879900,
                "frame_index": 6,
                "kind": "checkpoint",
                "logical_name": "checkpoints/update-002956.f5w",
                "semantic_domain": "f5-canonical-tensors-v1",
            },
            {
                "bytes_maximum": 4194304,
                "bytes_minimum": 1,
                "frame_index": 7,
                "kind": "training-result",
                "logical_name": "<training-result>",
                "semantic_domain": "f5-canonical-json-v1",
            },
        ]
        expected_evaluation_sequence = [
            {
                "bytes_maximum": 4096,
                "bytes_minimum": 4096,
                "frame_index": 0,
                "kind": "evaluation-bitset",
                "logical_name": "<derived-exact-evaluation-bitset-path>",
                "logical_name_templates": {
                    "primary": (
                        "evaluation/update-{checkpoint_update:06d}/"
                        "seed-{seed_index:02d}.bits"
                    ),
                    "repeat": (
                        "evaluation/update-000000-repeat/"
                        "seed-{seed_index:02d}.bits"
                    ),
                },
                "semantic_domain": "f5-success-bitset-v1",
            },
            {
                "bytes_maximum": 4194304,
                "bytes_minimum": 1,
                "frame_index": 1,
                "kind": "evaluation-result",
                "logical_name": "<evaluation-result>",
                "semantic_domain": "f5-canonical-json-v1",
            },
        ]
        streams = worker_ipc["streams"]
        if type(streams) is not dict or set(streams) != {
            "completion",
            "evaluation",
            "stderr",
            "training",
            "validate_stdout_stderr_concurrently",
        }:
            _fail("worker stream authority keys mismatch")
        expected_training = {
            "aggregate_payload_cap": 33554432,
            "aggregate_wire_cap": 33587232,
            "closed_per_kind_maximum_sum": 26250920,
            "counter_checks_on_every_increment": True,
            "frame_sequence": expected_training_sequence,
            "success_frame_count": 8,
        }
        expected_evaluation = {
            "aggregate_payload_cap": 8388608,
            "aggregate_wire_cap": 8396808,
            "closed_per_kind_maximum_sum": 4198400,
            "counter_checks_on_every_increment": True,
            "frame_sequence": expected_evaluation_sequence,
            "success_frame_count": 2,
        }
        if not _exact_json_equal(streams["training"], expected_training):
            _fail("training stream authority mismatch")
        if not _exact_json_equal(streams["evaluation"], expected_evaluation):
            _fail("evaluation stream authority mismatch")
        if not _exact_json_equal(
            streams["completion"],
            {
                "clean_eof_and_reap_after_final_frame_seconds": 5,
                "deadline_slides_on_progress": False,
                "first_stdout_byte_fixed_deadline_seconds": 60,
            },
        ) or not _exact_json_equal(
            streams["stderr"],
            {
                "maximum_bytes": 65536,
                "required_bytes_for_typed_record": 0,
            },
        ) or streams["validate_stdout_stderr_concurrently"] is not True:
            _fail("worker auxiliary stream authority mismatch")

        expected_failure_sequence = [
            {
                "bytes_maximum": 4096,
                "bytes_minimum": 1,
                "frame_index": 0,
                "kind": "worker-failure",
                "logical_name": "<worker-failure>",
                "semantic_domain": "f5-canonical-json-v1",
            }
        ]
        failure = worker_ipc["failure"]
        if type(failure) is not dict or set(failure) != {
            "authenticated_job_required_for_frame",
            "cross_product",
            "domain_mapping",
            "failure_after_success_frame_allowed",
            "frame_sequence",
            "progress",
            "rollout",
            "schema",
            "unauthenticated_job_exit",
            "unauthenticated_job_frame_allowed",
        }:
            _fail("worker failure authority keys mismatch")
        if (
            failure["authenticated_job_required_for_frame"] is not True
            or failure["failure_after_success_frame_allowed"] is not False
            or failure["unauthenticated_job_frame_allowed"] is not False
            or not _exact_json_equal(
                failure["frame_sequence"], expected_failure_sequence
            )
        ):
            _fail("worker failure stream authority mismatch")

        if worker_kind == "training":
            topology = (
                (0, "training-trace", "training-trace.jsonl", 1, 16777216,
                 "f5-training-trace-v1"),
                (1, "checkpoint", "checkpoints/update-000000.f5w", 879900,
                 879900, "f5-canonical-tensors-v1"),
                (2, "checkpoint", "checkpoints/update-000512.f5w", 879900,
                 879900, "f5-canonical-tensors-v1"),
                (3, "checkpoint", "checkpoints/update-001024.f5w", 879900,
                 879900, "f5-canonical-tensors-v1"),
                (4, "checkpoint", "checkpoints/update-001536.f5w", 879900,
                 879900, "f5-canonical-tensors-v1"),
                (5, "checkpoint", "checkpoints/update-002048.f5w", 879900,
                 879900, "f5-canonical-tensors-v1"),
                (6, "checkpoint", "checkpoints/update-002956.f5w", 879900,
                 879900, "f5-canonical-tensors-v1"),
                (7, "training-result", "<training-result>", 1, 4194304,
                 "f5-canonical-json-v1"),
            )
        else:
            checkpoint_update = job.get("checkpoint_update")
            seed_index = job.get("seed_index")
            repeat_flag = job.get("repeat_flag")
            if (
                type(checkpoint_update) is not int
                or type(seed_index) is not int
                or type(repeat_flag) is not int
                or not 0 <= seed_index <= 7
                or repeat_flag not in (0, 1)
            ):
                _fail("evaluation topology authority is malformed")
            if repeat_flag == 1:
                logical_name = (
                    "evaluation/update-000000-repeat/seed-%02d.bits"
                    % seed_index
                )
            else:
                logical_name = (
                    "evaluation/update-%06d/seed-%02d.bits"
                    % (checkpoint_update, seed_index)
                )
            topology = (
                (0, "evaluation-bitset", logical_name, 4096, 4096,
                 "f5-success-bitset-v1"),
                (1, "evaluation-result", "<evaluation-result>", 1, 4194304,
                 "f5-canonical-json-v1"),
            )
        failure_topology = (
            0,
            "worker-failure",
            "<worker-failure>",
            1,
            4096,
            "f5-canonical-json-v1",
        )
        return topology, failure_topology, nonce

    def bind_request(self, job_wire):
        try:
            if self._state != "unbound" or type(job_wire) is not bytes:
                _fail("worker frame parser cannot bind request")
            job, job_sha256 = parse_worker_job_wire(job_wire)
            manifest = load_protocol_manifest()
            topology, failure_topology, nonce = self._normalize_contract(
                manifest,
                job,
                job_sha256,
            )
            self._state = "bound"
            self._phase = "header"
            self._header_wire = bytearray()
            self._header_length = None
            self._header_snapshot = None
            self._topology = topology
            self._failure_topology = failure_topology
            self._job_sha256 = job_sha256
            self._nonce = nonce
            self._next_index = 0
            self._declared_payload_bytes = None
            self._payload_remaining = None
            self._raw_sha256 = None
            self._active_failure = False
            return None
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("bind_request", error)

    def header_ready(self, stdout_buffer):
        try:
            if type(stdout_buffer) is not bytearray:
                _fail("worker header buffer must be exact bytearray")
            if self._state != "bound":
                _fail("worker header parser is not bound")
            _worker_frame_parser_prefix_available = len(stdout_buffer)
            if self._phase == "header-complete":
                return True
            if self._phase == "success-complete":
                if _worker_frame_parser_prefix_available == 0:
                    return False
                self._phase = "header"
            if self._phase != "header":
                _fail("worker header parser phase mismatch")
            if len(self._header_wire) < 4:
                _worker_frame_parser_prefix_take = min(
                    4 - len(self._header_wire),
                    _worker_frame_parser_prefix_available,
                )
                self._header_wire.extend(
                    stdout_buffer[:_worker_frame_parser_prefix_take]
                )
                del stdout_buffer[:_worker_frame_parser_prefix_take]
            if len(self._header_wire) < 4:
                return False
            if self._header_length is None:
                self._header_length = _struct.unpack(
                    ">I", bytes(self._header_wire)
                )[0]
                if not 1 <= self._header_length <= 4096:
                    _fail("worker header length escaped bounds")
            _worker_frame_parser_body_available = len(stdout_buffer)
            _worker_frame_parser_body_take = min(
                4 + self._header_length - len(self._header_wire),
                _worker_frame_parser_body_available,
            )
            self._header_wire.extend(
                stdout_buffer[:_worker_frame_parser_body_take]
            )
            del stdout_buffer[:_worker_frame_parser_body_take]
            if len(self._header_wire) < 4 + self._header_length:
                return False
            self._phase = "header-complete"
            return True
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("header_ready", error)

    def take_header(self, stdout_buffer):
        try:
            if type(stdout_buffer) is not bytearray:
                _fail("worker header buffer must be exact bytearray")
            self._require_phase("header-complete")
            raw = bytes(self._header_wire[4:])
            header = _parse_canonical_json(raw, "worker payload header")
            if type(header) is not dict or set(header) != {
                "bytes",
                "frame_index",
                "job_sha256",
                "kind",
                "logical_name",
                "nonce",
                "raw_sha256",
                "schema",
                "semantic_sha256",
            }:
                _fail("worker payload header keys mismatch")
            if (
                type(header["bytes"]) is not int
                or not 0 <= header["bytes"] <= 16777216
                or type(header["frame_index"]) is not int
                or not 0 <= header["frame_index"] <= 7
            ):
                _fail("worker payload header integer fields mismatch")
            if not _is_lower_hex(header["job_sha256"], 64):
                _fail("worker payload job digest is malformed")
            if not _is_lower_hex(header["raw_sha256"], 64):
                _fail("worker payload raw digest is malformed")
            if not _is_lower_hex(header["semantic_sha256"], 64):
                _fail("worker payload semantic digest is malformed")
            if not _is_lower_hex(header["nonce"], 32):
                _fail("worker payload nonce is malformed")
            if type(header["kind"]) is not str or header["kind"] not in {
                "checkpoint",
                "evaluation-bitset",
                "evaluation-result",
                "training-result",
                "training-trace",
                "worker-failure",
            }:
                _fail("worker payload kind is malformed")
            logical_name = _require_ascii(
                header["logical_name"],
                "worker payload logical name",
                printable=True,
                nonempty=True,
            )
            if len(logical_name) > 1024:
                _fail("worker payload logical name exceeds bound")
            if (
                type(header["schema"]) is not str
                or header["schema"]
                != "bloodbowl-f5-worker-payload-header-v1"
            ):
                _fail("worker payload header schema mismatch")
            self._header_snapshot = (
                header["bytes"],
                header["frame_index"],
                header["job_sha256"],
                header["kind"],
                header["logical_name"],
                header["nonce"],
                header["raw_sha256"],
                header["schema"],
                header["semantic_sha256"],
            )
            self._header_wire.clear()
            self._header_length = None
            self._phase = "declaration"
            return self._header_dict()
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("take_header", error)

    def validate_declared_frame(self, header, expected_sequence):
        try:
            self._require_phase("declaration")
            snapshot = self._header_snapshot
            if type(header) is not dict or set(header) != {
                "bytes",
                "frame_index",
                "job_sha256",
                "kind",
                "logical_name",
                "nonce",
                "raw_sha256",
                "schema",
                "semantic_sha256",
            } or any(type(key) is not str for key in header):
                _fail("worker declaration header identity mismatch")
            if (
                type(header["bytes"]) is not type(snapshot[0])
                or header["bytes"] != snapshot[0]
                or type(header["frame_index"]) is not type(snapshot[1])
                or header["frame_index"] != snapshot[1]
                or type(header["job_sha256"]) is not type(snapshot[2])
                or header["job_sha256"] != snapshot[2]
                or type(header["kind"]) is not type(snapshot[3])
                or header["kind"] != snapshot[3]
                or type(header["logical_name"]) is not type(snapshot[4])
                or header["logical_name"] != snapshot[4]
                or type(header["nonce"]) is not type(snapshot[5])
                or header["nonce"] != snapshot[5]
                or type(header["raw_sha256"]) is not type(snapshot[6])
                or header["raw_sha256"] != snapshot[6]
                or type(header["schema"]) is not type(snapshot[7])
                or header["schema"] != snapshot[7]
                or type(header["semantic_sha256"]) is not type(snapshot[8])
                or header["semantic_sha256"] != snapshot[8]
            ):
                _fail("worker declaration header identity mismatch")
            if (
                type(expected_sequence) is not list
                or len(expected_sequence) != len(self._topology)
            ):
                _fail("worker expected sequence mismatch")
            for sequence_index in range(len(self._topology)):
                sequence_entry = expected_sequence[sequence_index]
                sequence_row = self._topology[sequence_index]
                if type(sequence_entry) is not dict or set(sequence_entry) != {
                    "bytes_maximum",
                    "bytes_minimum",
                    "frame_index",
                    "kind",
                    "logical_name",
                    "semantic_domain",
                } or any(type(key) is not str for key in sequence_entry):
                    _fail("worker expected sequence mismatch")
                if (
                    type(sequence_entry["bytes_maximum"])
                    is not type(sequence_row[4])
                    or sequence_entry["bytes_maximum"] != sequence_row[4]
                    or type(sequence_entry["bytes_minimum"])
                    is not type(sequence_row[3])
                    or sequence_entry["bytes_minimum"] != sequence_row[3]
                    or type(sequence_entry["frame_index"])
                    is not type(sequence_row[0])
                    or sequence_entry["frame_index"] != sequence_row[0]
                    or type(sequence_entry["kind"])
                    is not type(sequence_row[1])
                    or sequence_entry["kind"] != sequence_row[1]
                    or type(sequence_entry["logical_name"])
                    is not type(sequence_row[2])
                    or sequence_entry["logical_name"] != sequence_row[2]
                    or type(sequence_entry["semantic_domain"])
                    is not type(sequence_row[5])
                    or sequence_entry["semantic_domain"] != sequence_row[5]
                ):
                    _fail("worker expected sequence mismatch")
            frame_index = snapshot[1]
            kind = snapshot[3]
            logical_name = snapshot[4]
            declared = snapshot[0]
            if frame_index != self._next_index:
                _fail("worker frame index mismatch")
            if kind == "worker-failure":
                expected = self._failure_topology
                if self._next_index != 0 or self._active_failure:
                    _fail("worker failure followed successful frame")
            else:
                if self._next_index >= len(self._topology):
                    _fail("worker frame exceeds success topology")
                expected = self._topology[self._next_index]
            if kind != expected[1]:
                _fail("worker frame kind mismatch")
            if logical_name != expected[2]:
                _fail("worker frame logical name mismatch")
            if snapshot[2] != self._job_sha256:
                _fail("worker frame job digest mismatch")
            if snapshot[5] != self._nonce:
                _fail("worker frame nonce mismatch")
            if not expected[3] <= declared <= expected[4]:
                _fail("worker frame declared size mismatch")
            self._declared_payload_bytes = declared
            self._payload_remaining = declared
            self._raw_sha256 = snapshot[6]
            self._active_failure = kind == "worker-failure"
            self._phase = "payload"
            return None
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("validate_declared_frame", error)

    def payload_remaining(self, declared_payload_bytes):
        try:
            self._require_phase("payload")
            if (
                type(declared_payload_bytes) is not int
                or declared_payload_bytes != self._declared_payload_bytes
            ):
                _fail("worker payload declaration mismatch")
            return self._payload_remaining > 0
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("payload_remaining", error)

    def take_payload(self, stdout_buffer, declared_payload_bytes):
        try:
            if type(stdout_buffer) is not bytearray:
                _fail("worker payload buffer must be exact bytearray")
            self._require_phase("payload")
            if (
                type(declared_payload_bytes) is not int
                or declared_payload_bytes != self._declared_payload_bytes
            ):
                _fail("worker payload declaration mismatch")
            _worker_frame_parser_available = len(stdout_buffer)
            _worker_frame_parser_take = min(
                _worker_frame_parser_available,
                self._payload_remaining,
                65536,
            )
            if _worker_frame_parser_take == 0:
                _fail("worker payload extraction made no progress")
            _worker_frame_parser_chunk = bytes(
                stdout_buffer[:_worker_frame_parser_take]
            )
            del stdout_buffer[:_worker_frame_parser_take]
            self._payload_remaining -= _worker_frame_parser_take
            return _worker_frame_parser_chunk
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("take_payload", error)

    def finish_frame(self, declared_payload_bytes, observed_raw_sha256):
        try:
            self._require_phase("payload")
            if (
                type(declared_payload_bytes) is not int
                or declared_payload_bytes != self._declared_payload_bytes
            ):
                _fail("worker frame declaration mismatch")
            if self._payload_remaining != 0:
                _fail("worker frame payload is incomplete")
            if (
                not _is_lower_hex(observed_raw_sha256, 64)
                or observed_raw_sha256 != self._raw_sha256
            ):
                _fail("worker frame raw digest mismatch")
            self._header_snapshot = None
            self._declared_payload_bytes = None
            self._payload_remaining = None
            self._raw_sha256 = None
            if self._active_failure:
                self._phase = "failure-complete"
            else:
                self._next_index += 1
                if self._next_index == len(self._topology):
                    self._phase = "success-complete"
                else:
                    self._phase = "header"
            return None
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("finish_frame", error)

    def finish_stdout(self):
        try:
            if self._state != "bound":
                _fail("worker frame parser is not bound at EOF")
            if self._phase == "success-complete":
                self._clear_session()
                self._state = "unbound"
                return None
            if self._phase == "failure-complete":
                self._clear_session()
                self._state = "failure-terminal"
                return None
            _fail("worker stdout ended before logical completion")
        except (
            ProtocolError,
            AttributeError,
            BufferError,
            IndexError,
            KeyError,
            OverflowError,
            RecursionError,
            TypeError,
            UnicodeError,
            ValueError,
            _struct.error,
        ) as error:
            return self._ordinary_failure("finish_stdout", error)


def validate_closed_keys(document, expected_keys):
    if type(document) is not dict:
        _fail("closed-key document must be an object")
    try:
        expected = set(expected_keys)
    except TypeError as error:
        raise ProtocolError("expected keys are not iterable strings") from error
    if any(type(key) is not str for key in expected):
        _fail("expected keys must be strings")
    if set(document) != expected:
        _fail("closed-key document keys mismatch")


def validate_effective_arguments(arguments):
    expected = load_protocol_manifest()["puffer"]["arguments"]
    if not _exact_json_equal(arguments, expected):
        _fail("effective Puffer arguments mismatch")


def validate_effective_config(effective, manifest):
    if type(manifest) is not dict:
        _fail("effective config protocol must be an object")
    if type(effective) is not dict or set(effective) != {
        "arguments",
        "environment",
        "protocol_sha256",
        "schema",
    }:
        _fail("effective config root keys mismatch")
    if effective["schema"] != "bloodbowl-f5-effective-config-v1":
        _fail("effective config schema mismatch")
    if not _exact_json_equal(
        effective["arguments"],
        manifest["puffer"]["arguments"],
    ):
        _fail("effective config arguments mismatch")
    expected_environment = {
        "mapping": manifest["environment"]["mapping"],
        "path": manifest["environment"]["path"],
        "sha256": manifest["environment"]["sha256"],
    }
    if not _exact_json_equal(effective["environment"], expected_environment):
        _fail("effective config environment mismatch")
    expected_protocol = _hashlib.sha256(
        canonical_json_bytes(manifest)
    ).hexdigest()
    if effective["protocol_sha256"] != expected_protocol:
        _fail("effective config protocol digest mismatch")
    registry = manifest["artifact"]["schemas"]
    validate_schema(
        effective,
        registry["roots"]["effective-config.json"],
        registry,
    )


def validate_thread_semantics(semantics):
    expected = load_protocol_manifest()["execution"]["thread_semantics"]
    if not _exact_json_equal(semantics, expected):
        _fail("thread semantics mismatch")


def derive_seed(domain):
    _require_ascii(domain, "seed domain", nonempty=True)
    manifest = load_protocol_manifest()
    domains = manifest["seeds"]["domains"]
    allowed = set(
        (
            domains["python_process"],
            domains["numpy_process"],
            domains["model_initialization"],
            domains["training_torch"],
            domains["evaluation_construction"],
        )
    )
    allowed.update(domains["evaluation_actions"])
    if domain not in allowed:
        _fail("seed domain is not frozen")
    return int.from_bytes(_hashlib.sha256(domain.encode("ascii")).digest()[:4], "big")


def masked_uniform_comparator(numerator, denominator, episodes):
    for value, label in (
        (numerator, "numerator"),
        (denominator, "denominator"),
        (episodes, "episodes"),
    ):
        if type(value) is not int:
            _fail("masked-uniform " + label + " must be an exact integer")
    if numerator <= 0 or denominator <= numerator or episodes <= 0:
        _fail("masked-uniform arguments are outside their domains")
    probability = numerator / denominator
    logarithm = _math.log1p(-probability)
    minimum = _math.ceil(_math.log(0.05) / logarithm)
    at_budget = -_math.expm1(episodes * logarithm)
    return {
        "minimum_episodes_95": minimum,
        "probability_at_budget_rounded_10": round(at_budget, 10),
    }


def git_status_sha256(raw_status):
    if type(raw_status) is not bytes:
        _fail("Git status output must be exact bytes")
    if b"\0" in raw_status or b"\r" in raw_status:
        _fail("Git status output contains a forbidden byte")
    if raw_status and not raw_status.endswith(b"\n"):
        _fail("nonempty Git status output must end with LF")
    return _hashlib.sha256(
        b"bloodbowl-f5-git-status-v1\0" + raw_status
    ).hexdigest()


def worker_environment_sha256(environment):
    expected = load_protocol_manifest()["runtime"]["worker"]["environment"]
    if not _exact_json_equal(environment, expected):
        _fail("worker environment is not the frozen twenty-key map")
    return _hashlib.sha256(
        b"bloodbowl-f5-worker-environment-v1\0"
        + canonical_json_bytes(environment)
    ).hexdigest()


def _validate_normalized_open_token(token):
    _require_ascii(token, "normalized open token", printable=True, nonempty=True)
    if token == "<absent-linux-proc-self-maps>":
        return
    roots = (
        "<artifact>",
        "<bloodbowl-source>",
        "<prepared-puffer-root>",
        "<private-runtime-scratch>",
        "<prepared-python-prefix>",
    )
    matched = None
    for root in roots:
        if token == root or token.startswith(root + "/"):
            matched = root
            break
    if matched is None:
        _fail("normalized open token has an unknown root")
    if token == matched:
        return
    suffix = token[len(matched) + 1 :]
    if (
        not suffix
        or "\\" in suffix
        or "\0" in suffix
        or "\n" in suffix
        or any(component in ("", ".", "..") for component in suffix.split("/"))
    ):
        _fail("normalized open token suffix is not canonical")


def opened_paths_sha256(paths):
    if type(paths) is not list:
        _fail("opened paths must be an exact array")
    if len(paths) > 65535:
        _fail("opened paths exceed the frozen item cap")
    for token in paths:
        _validate_normalized_open_token(token)
    if paths != sorted(set(paths)):
        _fail("opened paths must be sorted and unique")
    canonical = canonical_json_bytes(paths)
    if len(canonical) > 3145728:
        _fail("opened paths exceed the frozen canonical byte cap")
    return _hashlib.sha256(
        b"bloodbowl-f5-opened-paths-v1\0" + canonical
    ).hexdigest()


def python_rng_sha256(state):
    if type(state) is not tuple or len(state) != 3:
        _fail("Python RNG state must be an exact three-tuple")
    version, values, gaussian = state
    if version != 3 or type(version) is not int:
        _fail("Python RNG state version mismatch")
    if type(values) is not tuple or len(values) != 625:
        _fail("Python RNG state vector width mismatch")
    for value in values[:624]:
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            _fail("Python RNG state word is outside uint32")
    if type(values[624]) is not int or not 0 <= values[624] <= 624:
        _fail("Python RNG state index is outside its domain")
    if gaussian is not None and (
        type(gaussian) is not float
        or not _math.isfinite(gaussian)
        or _is_negative_zero(gaussian)
    ):
        _fail("Python RNG Gaussian cache is invalid")
    canonical = canonical_json_bytes(
        {
            "gauss": gaussian,
            "state": list(values),
            "version": version,
        }
    )
    return _hashlib.sha256(
        b"bloodbowl-f5-rng-python-v1\0" + canonical
    ).hexdigest()


def numpy_rng_sha256(state):
    if type(state) is not tuple or len(state) != 5:
        _fail("NumPy RNG state must be an exact five-tuple")
    name, keys, position, has_gauss, cached_gaussian = state
    if name != "MT19937" or type(name) is not str:
        _fail("NumPy RNG algorithm mismatch")
    if type(keys) is not tuple or len(keys) != 624:
        _fail("NumPy RNG key vector width mismatch")
    for value in keys:
        if type(value) is not int or not 0 <= value <= 0xFFFFFFFF:
            _fail("NumPy RNG key is outside uint32")
    if type(position) is not int or not 0 <= position <= 624:
        _fail("NumPy RNG position is outside its domain")
    if type(has_gauss) is not int or has_gauss not in (0, 1):
        _fail("NumPy RNG Gaussian flag is invalid")
    if (
        type(cached_gaussian) is not float
        or not _math.isfinite(cached_gaussian)
        or _is_negative_zero(cached_gaussian)
    ):
        _fail("NumPy RNG Gaussian cache is invalid")
    canonical = canonical_json_bytes(
        {
            "cached_gaussian": cached_gaussian,
            "has_gauss": has_gauss,
            "keys": list(keys),
            "name": name,
            "position": position,
        }
    )
    return _hashlib.sha256(
        b"bloodbowl-f5-rng-numpy-v1\0" + canonical
    ).hexdigest()


def torch_rng_sha256(state):
    if type(state) is not bytes or len(state) != 5056:
        _fail("Torch CPU RNG state must be exactly 5,056 bytes")
    return _hashlib.sha256(
        b"bloodbowl-f5-rng-torch-cpu-v1\0"
        + _struct.pack(">Q", len(state))
        + state
    ).hexdigest()


def _tensor_shape_and_payload(item, location):
    if type(item) is not dict or set(item) != {"name", "payload", "shape"}:
        _fail(location + ": tensor record keys mismatch")
    name_bytes = _require_ascii(
        item["name"],
        location + ": tensor name",
        printable=True,
        nonempty=True,
    )
    shape = item["shape"]
    if type(shape) not in (tuple, list) or not shape:
        _fail(location + ": tensor shape must be nonempty")
    product = 1
    dimensions = []
    for dimension in shape:
        if type(dimension) is not int or dimension <= 0:
            _fail(location + ": tensor dimension is invalid")
        if dimension > 0xFFFFFFFFFFFFFFFF:
            _fail(location + ": tensor dimension exceeds uint64")
        product *= dimension
        if product > 0x1FFFFFFFFFFFFFFF:
            _fail(location + ": tensor element count overflow")
        dimensions.append(dimension)
    payload = item["payload"]
    if type(payload) is not bytes or len(payload) != product * 4:
        _fail(location + ": tensor payload width mismatch")
    for (value,) in _struct.iter_unpack("<f", payload):
        if not _math.isfinite(value):
            _fail(location + ": tensor payload contains a non-finite float")
    return name_bytes, dimensions, payload


def canonical_tensor_sha256(tensors):
    if type(tensors) not in (list, tuple) or not tensors:
        _fail("canonical tensor input must be a nonempty sequence")
    if len(tensors) > 0xFFFFFFFF:
        _fail("canonical tensor count exceeds uint32")
    parsed = []
    for index, item in enumerate(tensors):
        name, shape, payload = _tensor_shape_and_payload(
            item,
            "tensor[%d]" % index,
        )
        parsed.append((name, shape, payload))
    names = [item[0] for item in parsed]
    if names != sorted(names) or len(set(names)) != len(names):
        _fail("canonical tensor names must be sorted and unique")

    framed = bytearray(b"f5-canonical-tensors-v1\0")
    framed.extend(_struct.pack(">I", len(parsed)))
    dtype = b"float32-le"
    for name, shape, payload in parsed:
        framed.extend(_struct.pack(">I", len(name)))
        framed.extend(name)
        framed.extend(_struct.pack(">I", len(dtype)))
        framed.extend(dtype)
        framed.extend(_struct.pack(">I", len(shape)))
        for dimension in shape:
            framed.extend(_struct.pack(">Q", dimension))
        framed.extend(_struct.pack(">Q", len(payload)))
        framed.extend(payload)
    return _hashlib.sha256(bytes(framed)).hexdigest()


def pack_success_bits(bits):
    if type(bits) not in (list, tuple):
        _fail("success bits must be an exact sequence")
    raw = bytearray((len(bits) + 7) // 8)
    for index, value in enumerate(bits):
        if type(value) is not int or value not in (0, 1):
            _fail("success bit must be exact integer zero or one")
        if value:
            raw[index // 8] |= 1 << (index % 8)
    return bytes(raw)


def unpack_success_bits(raw, *, count):
    if type(raw) is not bytes:
        _fail("packed success bits must be exact bytes")
    if type(count) is not int or count < 0:
        _fail("success-bit count must be a nonnegative exact integer")
    if len(raw) != (count + 7) // 8:
        _fail("packed success-bit width mismatch")
    if count and count % 8:
        padding_mask = 0xFF ^ ((1 << (count % 8)) - 1)
        if raw[-1] & padding_mask:
            _fail("packed success bits contain nonzero padding")
    return [
        (raw[index // 8] >> (index % 8)) & 1 for index in range(count)
    ]


def success_bitset_sha256(
    *,
    checkpoint_update,
    seed_index,
    action_seed,
    episode_count,
    repeat_flag,
    raw
):
    for value, label, maximum in (
        (checkpoint_update, "checkpoint update", 0xFFFFFFFF),
        (seed_index, "seed index", 0xFFFFFFFF),
        (action_seed, "action seed", 0xFFFFFFFF),
        (episode_count, "episode count", 0xFFFFFFFFFFFFFFFF),
    ):
        if type(value) is not int or not 0 <= value <= maximum:
            _fail(label + " is outside its unsigned framing domain")
    if type(repeat_flag) is not int or repeat_flag not in (0, 1):
        _fail("repeat flag must be exact integer zero or one")
    unpack_success_bits(raw, count=episode_count)
    framed = (
        b"f5-success-bitset-v1\0"
        + _struct.pack(">I", checkpoint_update)
        + _struct.pack(">I", seed_index)
        + _struct.pack(">I", action_seed)
        + _struct.pack(">Q", episode_count)
        + bytes((repeat_flag,))
        + raw
    )
    return _hashlib.sha256(framed).hexdigest()


def wilson95(successes, episodes):
    if (
        type(successes) is not int
        or type(episodes) is not int
        or episodes <= 0
        or successes < 0
        or successes > episodes
    ):
        _fail("Wilson counts are outside their exact integer domains")
    z_value = 1.959963984540054
    proportion = successes / episodes
    denominator = 1.0 + z_value * z_value / episodes
    center = (
        proportion + z_value * z_value / (2.0 * episodes)
    ) / denominator
    margin = z_value * _math.sqrt(
        proportion * (1.0 - proportion) / episodes
        + z_value
        * z_value
        / (4.0 * episodes * episodes)
    ) / denominator
    return [max(0.0, center - margin), min(1.0, center + margin)]


def compute_parameter_l2(current, initial):
    if type(current) is not dict or type(initial) is not dict:
        _fail("parameter telemetry inputs must be objects")
    if set(current) != set(initial):
        _fail("parameter telemetry name sets differ")
    norm_sum = 0.0
    drift_sum = 0.0
    for name in sorted(current, key=lambda value: value.encode("utf-8")):
        _require_ascii(name, "parameter name", printable=True, nonempty=True)
        current_values = current[name]
        initial_values = initial[name]
        if (
            type(current_values) not in (list, tuple)
            or type(initial_values) not in (list, tuple)
            or len(current_values) != len(initial_values)
        ):
            _fail("parameter telemetry widths differ")
        for index in range(len(current_values)):
            current_value = current_values[index]
            initial_value = initial_values[index]
            if (
                type(current_value) is not float
                or type(initial_value) is not float
                or not _math.isfinite(current_value)
                or not _math.isfinite(initial_value)
            ):
                _fail("parameter telemetry requires finite exact floats")
            norm_sum = norm_sum + current_value * current_value
            delta = current_value - initial_value
            drift_sum = drift_sum + delta * delta
    norm = _math.sqrt(norm_sum)
    drift = _math.sqrt(drift_sum)
    if not _math.isfinite(norm) or not _math.isfinite(drift):
        _fail("parameter telemetry overflowed binary64")
    return {"drift_from_initial": drift, "norm": norm}


def select_worker_supervisor_origin(
    prior_origin,
    signal_latched,
    deadline_expired,
    child_status,
    stderr_fault,
    stdout_fault,
):
    if prior_origin is not None:
        return prior_origin
    if signal_latched:
        return "handled-signal"
    if deadline_expired:
        return "whole-deadline"
    if child_status == "unrequested-signal":
        return "worker-signal"
    if child_status != "exit-0":
        return "ipc-contract"
    if stderr_fault or stdout_fault:
        return "ipc-contract"
    return None


def select_publication_supervisor_origin(
    prior_origin,
    signal_latched,
    deadline_expired,
    child_status,
    stderr_fault,
    stdout_fault,
    handoff_fault,
    handoff_zero_byte_eof,
    ack_fault,
):
    if prior_origin is not None:
        return prior_origin
    if signal_latched:
        return "handled-signal"
    if deadline_expired:
        return "whole-deadline"
    if child_status == "unrequested-signal":
        return "publication-precommit"
    if stderr_fault or stdout_fault or handoff_fault or ack_fault:
        return "publication-precommit"
    if handoff_zero_byte_eof and child_status == "exit-75":
        return "filesystem-resource"
    if child_status == "exit-75":
        return "filesystem-resource"
    if child_status != "exit-0":
        return "publication-precommit"
    if handoff_zero_byte_eof:
        return "publication-precommit"
    return None


def generate_namespace_nonce(urandom, retained_nonces):
    if not callable(urandom) or type(retained_nonces) is not set:
        _fail("namespace nonce capabilities are invalid")
    raw = urandom(16)
    if type(raw) is not bytes or len(raw) != 16:
        _fail("namespace nonce source returned the wrong shape")
    nonce = raw.hex()
    if nonce in retained_nonces:
        _fail("namespace nonce collision")
    return nonce


def paired_success_counts(initial, final):
    if type(initial) not in (list, tuple) or type(final) not in (list, tuple):
        _fail("paired success inputs must be exact sequences")
    if len(initial) != len(final):
        _fail("paired success input widths differ")
    counts = {
        "both": 0,
        "episodes": len(initial),
        "final_only": 0,
        "initial_only": 0,
        "neither": 0,
        "net_final_only": 0,
    }
    for index in range(len(initial)):
        initial_bit = initial[index]
        final_bit = final[index]
        if (
            type(initial_bit) is not int
            or initial_bit not in (0, 1)
            or type(final_bit) is not int
            or final_bit not in (0, 1)
        ):
            _fail("paired success values must be exact integer bits")
        if initial_bit and final_bit:
            counts["both"] += 1
        elif initial_bit:
            counts["initial_only"] += 1
        elif final_bit:
            counts["final_only"] += 1
        else:
            counts["neither"] += 1
    counts["net_final_only"] = (
        counts["final_only"] - counts["initial_only"]
    )
    return counts


def classify_learning_outcome(
    objective_events,
    initial_successes,
    final_successes,
):
    for value in (objective_events, initial_successes, final_successes):
        if type(value) is not int or value < 0:
            _fail("learning-outcome counts must be nonnegative exact integers")
    if objective_events == 0:
        return "exploration-inconclusive"
    if final_successes <= initial_successes:
        return "objective-observed-no-positive-final-point-estimate"
    return "positive-fixed-instance-acquisition-signal"


def validate_initial_parameter_sha256(observed_sha256):
    if not _is_lower_hex(observed_sha256, 64):
        _fail("initial parameter digest is malformed")
    if observed_sha256 != EXPECTED_INITIAL_PARAMETER_SHA256:
        _fail("initial parameter digest mismatch")


def validate_one_update_smoke_digests(observed_sha256s):
    if type(observed_sha256s) is not list or len(observed_sha256s) != 2:
        _fail("one-update smoke requires exactly two digests")
    for digest in observed_sha256s:
        if not _is_lower_hex(digest, 64):
            _fail("one-update smoke digest is malformed")
        if digest != EXPECTED_ONE_UPDATE_PARAMETER_SHA256:
            _fail("one-update smoke digest mismatch")


_TENSOR_SCHEMA = (
    ("decoder.decoder.bias", (454,), 1816),
    ("decoder.decoder.weight", (454, 64), 116224),
    ("decoder.value_function.bias", (1,), 4),
    ("decoder.value_function.weight", (1, 64), 256),
    ("encoder.encoder.bias", (64,), 256),
    ("encoder.encoder.weight", (64, 2782), 712192),
    ("network.layers.0.weight", (192, 64), 49152),
)
_CHECKPOINT_BYTES = 879900


def decode_fixed_checkpoint(raw):
    if type(raw) is not bytes or len(raw) != _CHECKPOINT_BYTES:
        _fail("fixed checkpoint must be exactly 879,900 bytes")
    decoded = []
    offset = 0
    for name, shape, size in _TENSOR_SCHEMA:
        payload = raw[offset : offset + size]
        if len(payload) != size:
            _fail("fixed checkpoint tensor slice is truncated")
        for (value,) in _struct.iter_unpack("<f", payload):
            if not _math.isfinite(value):
                _fail("fixed checkpoint contains a non-finite float")
        decoded.append(
            {
                "name": name,
                "payload": payload,
                "shape": shape,
            }
        )
        offset += size
    if offset != len(raw):
        _fail("fixed checkpoint has trailing bytes")
    return tuple(decoded)


def encode_fixed_checkpoint(tensors):
    if type(tensors) not in (list, tuple) or len(tensors) != len(_TENSOR_SCHEMA):
        _fail("fixed checkpoint tensor count mismatch")
    payloads = []
    for index, expected in enumerate(_TENSOR_SCHEMA):
        name, shape, size = expected
        item = tensors[index]
        parsed_name, parsed_shape, payload = _tensor_shape_and_payload(
            item,
            "fixed tensor[%d]" % index,
        )
        if (
            parsed_name != name.encode("ascii")
            or tuple(parsed_shape) != shape
            or len(payload) != size
        ):
            _fail("fixed checkpoint tensor schema mismatch")
        payloads.append(payload)
    raw = b"".join(payloads)
    if len(raw) != _CHECKPOINT_BYTES:
        _fail("encoded fixed checkpoint width mismatch")
    return raw


def raw_checkpoint_sha256(raw):
    decode_fixed_checkpoint(raw)
    return _hashlib.sha256(raw).hexdigest()


def read_fixed_checkpoint(path):
    path_value = _os.path.abspath(_os.fspath(path))
    raw = _read_fixed_regular_file(
        path_value,
        _CHECKPOINT_BYTES,
        0o600,
        "fixed checkpoint",
    )
    return decode_fixed_checkpoint(raw)


def _tensor_claims(tensor, expected_shape, label):
    try:
        shape = tuple(tensor.shape)
    except (AttributeError, TypeError) as error:
        raise ProtocolError(label + ": tensor has no exact shape") from error
    if shape != tuple(expected_shape):
        _fail(label + ": tensor shape mismatch")
    dtype = getattr(tensor, "dtype", None)
    if str(dtype) not in ("float32", "torch.float32"):
        _fail(label + ": tensor dtype is not float32")
    device = getattr(tensor, "device", None)
    if str(device) != "cpu":
        _fail(label + ": tensor device is not CPU")
    contiguous = getattr(tensor, "is_contiguous", None)
    if not callable(contiguous) or contiguous() is not True:
        _fail(label + ": tensor is not contiguous")


def load_fixed_checkpoint_into_policy(raw, policy, *, tensor_factory):
    decoded = decode_fixed_checkpoint(raw)
    if not callable(tensor_factory):
        _fail("fixed checkpoint tensor factory is not callable")
    state_method = getattr(policy, "state_dict", None)
    load_method = getattr(policy, "load_state_dict", None)
    if not callable(state_method) or not callable(load_method):
        _fail("policy lacks the fixed state-dict capability")
    try:
        existing = state_method()
    except Exception as error:
        raise ProtocolError("policy state_dict failed") from error
    if type(existing) is not dict:
        _fail("policy state_dict must be an exact mapping")
    expected_names = tuple(name for name, _shape, _size in _TENSOR_SCHEMA)
    if set(existing) != set(expected_names):
        _fail("policy state_dict names do not match the fixed schema")
    for name, shape, _size in _TENSOR_SCHEMA:
        _tensor_claims(existing[name], shape, "existing policy tensor " + name)

    loaded = {}
    for item, (name, shape, _size) in zip(decoded, _TENSOR_SCHEMA):
        try:
            tensor = tensor_factory(
                item["payload"],
                shape=shape,
                dtype="float32",
                device="cpu",
            )
        except Exception as error:
            raise ProtocolError("fixed checkpoint tensor factory failed") from error
        _tensor_claims(tensor, shape, "constructed policy tensor " + name)
        loaded[name] = tensor
    try:
        return load_method(loaded, strict=True)
    except Exception as error:
        raise ProtocolError("strict policy state load failed") from error


def _set_nested(document, target, value):
    components = target.split(".")
    current = document
    for component in components[:-1]:
        current = current.setdefault(component, {})
    leaf = components[-1]
    if leaf in current:
        _fail("rollout projection target collision")
    current[leaf] = value


def _positive_zero(value):
    return 0.0 if value == 0.0 else value


def _validate_completed_summary(summary):
    if type(summary) is not dict or set(summary) != {
        "decision_count",
        "matches",
        "objective_events",
        "successful_episodes",
    }:
        _fail("completed transition summary keys mismatch")
    if summary["decision_count"] != 8 or type(summary["decision_count"]) is not int:
        _fail("completed transition decision count mismatch")
    if summary["matches"] != 2048 or type(summary["matches"]) is not int:
        _fail("completed transition match count mismatch")
    objective_events = summary["objective_events"]
    if type(objective_events) is not int or objective_events < 0:
        _fail("completed transition objective count is invalid")
    successes = summary["successful_episodes"]
    if type(successes) is not list or len(successes) != summary["matches"]:
        _fail("completed transition success vector width mismatch")
    if any(type(value) is not int or value not in (0, 1) for value in successes):
        _fail("completed transition success vector is not binary")


def normalize_puffer_integrity(
    raw_log,
    *,
    completed_summary,
    endpoint_checks,
):
    manifest = load_protocol_manifest()
    authority = manifest["execution"]["rollout_log"]
    native_keys = authority["native_keys"]
    if type(raw_log) is not dict or set(raw_log) != set(native_keys):
        _fail("flat Puffer log keys mismatch")
    if type(endpoint_checks) is not dict or set(endpoint_checks) != {
        "exact_joint_action",
        "fixture_role",
        "illegal_fraction",
        "module_identity",
        "rollout_closed",
    }:
        _fail("rollout endpoint-check keys mismatch")
    if any(type(value) is not bool for value in endpoint_checks.values()):
        _fail("rollout endpoint checks must be exact Booleans")
    if not all(endpoint_checks.values()):
        _fail("rollout endpoint check failed")
    _validate_completed_summary(completed_summary)

    normalized_raw = {}
    for key in native_keys:
        value = raw_log[key]
        if type(value) is not float or not _math.isfinite(value):
            _fail("flat Puffer log value is not an exact finite float: " + key)
        normalized_raw[key] = _positive_zero(value)

    matches = completed_summary["matches"]
    if normalized_raw["n"] != float(matches):
        _fail("flat Puffer log completed count mismatch")
    result = {"integrity": {"reward_components": {}}, "objective": {}, "validation": {}}
    projected_names = set()
    for record in authority["projections"]:
        if type(record) is not dict or set(record) != {
            "native",
            "operation",
            "target",
        }:
            _fail("rollout projection descriptor is malformed")
        native = record["native"]
        operation = record["operation"]
        target = record["target"]
        projected_names.add(native)
        value = normalized_raw[native]
        if operation == "completed-count":
            if value != float(matches):
                _fail("rollout completed-count projection mismatch")
            projected = matches
        elif operation == "scale-nonnegative-integer":
            scaled = value * matches
            if (
                not _math.isfinite(scaled)
                or scaled < 0.0
                or scaled != float(int(scaled))
            ):
                _fail("rollout count projection is not exactly integral")
            projected = int(scaled)
        elif operation == "scale-finite-number":
            scaled = value * matches
            if not _math.isfinite(scaled):
                _fail("rollout scaled number is not finite")
            projected = _positive_zero(scaled)
        elif operation == "retain-nonnegative-integer":
            if value < 0.0 or value != float(int(value)):
                _fail("rollout retained count is not exactly integral")
            projected = int(value)
        elif operation == "retain-finite-number":
            projected = _positive_zero(value)
        elif operation == "require-zero":
            if value != 0.0:
                _fail("rollout hard-zero projection is nonzero")
            projected = 0
        else:
            _fail("unknown rollout projection operation")
        _set_nested(result, target, projected)

    unretained = authority["validated_unretained"]
    if projected_names & set(unretained):
        _fail("rollout projection and unretained sets overlap")
    if projected_names | set(unretained) != set(native_keys):
        _fail("rollout projection authority is incomplete")

    integrity = result["integrity"]
    integrity.update(
        {
            "config_unchanged": True,
            "environment_unchanged": True,
            "module_unchanged": True,
            "projection_collisions": 0,
            "seed_unchanged": True,
            "source_unchanged": True,
        }
    )
    objective_events = completed_summary["objective_events"]
    successful_count = sum(completed_summary["successful_episodes"])
    validation = result["validation"]

    exact_equations = (
        (result["objective"]["events"], objective_events, "objective events"),
        (validation["total_touchdowns"], objective_events, "total touchdowns"),
        (
            validation["home_episode_return"],
            float(objective_events),
            "home episode return",
        ),
        (validation["score_diff"], float(objective_events), "score difference"),
        (
            integrity["reward_components"]["touchdown"],
            float(objective_events),
            "touchdown reward component",
        ),
        (
            integrity["reward_postclip_return"],
            float(objective_events),
            "postclip reward return",
        ),
        (
            validation["reward_episode_abs_max_mean"],
            successful_count / matches,
            "successful-episode projection",
        ),
    )
    for observed, expected, label in exact_equations:
        if not _strict_equal(observed, expected):
            _fail("rollout reconciliation mismatch: " + label)

    hard_integrity = {
        "away_touchdowns": 0,
        "completed_episodes": matches,
        "demo_endzone_episodes": 0,
        "demo_episodes": 0,
        "demo_fallbacks": 0,
        "demo_pass_episodes": 0,
        "demo_pickup_episodes": 0,
        "demo_postkick_episodes": 0,
        "demo_selector_eligible_configured": 0,
        "demo_selector_threshold_configured": 0,
        "demo_uniform_episodes": 0,
        "error_episodes": 0,
        "illegal_fraction": 0.0,
        "mean_episode_length": 8.0,
        "projection_collisions": 0,
        "reward_clip_episodes": 0,
        "reward_clip_excess": 0.0,
        "reward_clip_nonterminal_samples": 0,
        "reward_clip_terminal_samples": 0,
        "reward_clipped_samples": 0,
        "reward_component_mismatch_samples": 0,
        "reward_component_nonfinite_samples": 0,
        "reward_component_residual": 0.0,
        "reward_nonfinite_episodes": 0,
        "reward_nonfinite_samples": 0,
        "reward_samples_per_episode": 16,
        "reward_terminal_suppressed_abs": 0.0,
        "reward_terminal_suppressed_signed": 0.0,
        "state_bank_config_episodes": 0,
    }
    for key, expected in hard_integrity.items():
        if not _strict_equal(integrity.get(key), expected):
            _fail("rollout hard-integrity mismatch: " + key)
    for key, value in integrity["reward_components"].items():
        expected = float(objective_events) if key == "touchdown" else 0.0
        if not _strict_equal(value, expected):
            _fail("rollout reward component mismatch: " + key)
    for key, value in validation.items():
        if key in {
            "home_episode_return",
            "reward_episode_abs_max_mean",
            "score_diff",
            "total_touchdowns",
        }:
            continue
        if value != 0:
            _fail("rollout validation hard-zero mismatch: " + key)
    return result


def _validate_transition_inputs(
    rewards,
    terminals,
    final_rewards,
    final_terminals,
):
    if type(rewards) is not list or type(terminals) is not list:
        _fail("transition rows must be exact arrays")
    if len(rewards) != 8 or len(terminals) != 8:
        _fail("transition row count mismatch")
    if type(final_rewards) is not list or type(final_terminals) is not list:
        _fail("transition final vectors must be exact arrays")
    width = len(final_rewards)
    if width == 0 or width % 2 or len(final_terminals) != width:
        _fail("transition final vector width mismatch")
    for row in rewards:
        if type(row) is not list or len(row) != width:
            _fail("transition reward matrix shape mismatch")
    for row in terminals:
        if type(row) is not list or len(row) != width:
            _fail("transition terminal matrix shape mismatch")
    for row in rewards:
        for value in row:
            if type(value) is not float or not _math.isfinite(value):
                _fail("transition reward is not an exact finite float")
    for value in final_rewards:
        if type(value) is not float or not _math.isfinite(value):
            _fail("transition final reward is not an exact finite float")
    for row in terminals:
        for value in row:
            if type(value) is not int or value not in (0, 1):
                _fail("transition terminal is not an exact integer bit")
    for value in final_terminals:
        if type(value) is not int or value not in (0, 1):
            _fail("transition final terminal is not an exact integer bit")
    return width


def parse_transition_rows(
    rewards,
    terminals,
    final_rewards,
    final_terminals,
):
    width = _validate_transition_inputs(
        rewards,
        terminals,
        final_rewards,
        final_terminals,
    )
    for row in range(8):
        for home in range(0, width, 2):
            if terminals[row][home] != terminals[row][home + 1]:
                _fail("Home/Away terminal asymmetry")
    for home in range(0, width, 2):
        if final_terminals[home] != final_terminals[home + 1]:
            _fail("Home/Away final-terminal asymmetry")
    for row in range(1, 8):
        if any(value != 0 for value in terminals[row]):
            _fail("episode terminated before the repaired final row")
    if any(value != 1 for value in final_terminals):
        _fail("repaired final row is not terminal")

    matches = width // 2
    successes = [0] * matches
    objective_events = 0
    reward_rows = list(rewards[1:8]) + [final_rewards]
    for row in reward_rows:
        for match, home in enumerate(range(0, width, 2)):
            pair = (row[home], row[home + 1])
            if pair == (0.0, 0.0):
                continue
            if pair != (1.0, -1.0):
                _fail("transition reward pair is not a Home objective event")
            objective_events += 1
            successes[match] = 1
    return {
        "decision_count": 8,
        "matches": matches,
        "objective_events": objective_events,
        "successful_episodes": successes,
    }


def _raise_rollout_alignment(check, delayed_row, agent_rows, mode):
    bitset = bytearray(512)
    unique_rows = sorted(set(agent_rows))
    for agent_row in unique_rows:
        if type(agent_row) is not int or not 0 <= agent_row < 4096:
            _fail("rollout alignment agent row is outside the fixed width")
        bitset[agent_row // 8] |= 1 << (agent_row % 8)
    rollout = {
        "agent_row_count": len(unique_rows),
        "agent_rows_bitset_hex": bytes(bitset).hex(),
        "check": check,
        "delayed_row": delayed_row,
        "mode": mode,
    }
    raise RolloutAlignmentError("rollout alignment failed: " + check, rollout)


def validate_live_rollout(collector, *, mode):
    if mode not in ("training", "evaluation") or type(mode) is not str:
        _fail("rollout mode is not frozen")
    required = ("rewards", "terminals", "env_logs", "endpoint_checks")
    if any(not hasattr(collector, name) for name in required):
        _fail("collector lacks a rollout capability")
    if mode == "training":
        if (
            not hasattr(collector, "tail_rewards")
            or not hasattr(collector, "tail_terminals")
            or hasattr(collector, "pending_rewards")
            or hasattr(collector, "pending_terminals")
        ):
            _fail("training collector final-field family mismatch")
        final_rewards = collector.tail_rewards
        final_terminals = collector.tail_terminals
    else:
        if (
            not hasattr(collector, "pending_rewards")
            or not hasattr(collector, "pending_terminals")
            or hasattr(collector, "tail_rewards")
            or hasattr(collector, "tail_terminals")
        ):
            _fail("evaluation collector final-field family mismatch")
        final_rewards = collector.pending_rewards
        final_terminals = collector.pending_terminals

    width = _validate_transition_inputs(
        collector.rewards,
        collector.terminals,
        final_rewards,
        final_terminals,
    )
    if width != 4096:
        _fail("live rollout width must be exactly 4,096 agents")

    terminal_rows = list(collector.terminals) + [final_terminals]
    for delayed_row, row in enumerate(terminal_rows):
        asymmetric = []
        for home in range(0, width, 2):
            if row[home] != row[home + 1]:
                asymmetric.extend((home, home + 1))
        if asymmetric:
            _raise_rollout_alignment(
                "home-away-terminal-asymmetry",
                delayed_row,
                asymmetric,
                mode,
            )
    if mode == "training":
        row_zero = [
            index
            for home in range(0, width, 2)
            if collector.terminals[0][home] != 0
            for index in (home, home + 1)
        ]
        if row_zero:
            _raise_rollout_alignment(
                "row-zero-canary",
                0,
                row_zero,
                mode,
            )
    for delayed_row in range(1, 8):
        early = [
            index
            for home in range(0, width, 2)
            if collector.terminals[delayed_row][home] != 0
            for index in (home, home + 1)
        ]
        if early:
            _raise_rollout_alignment(
                "early-terminal",
                delayed_row,
                early,
                mode,
            )
    tail = [
        index
        for home in range(0, width, 2)
        if final_terminals[home] != 1
        for index in (home, home + 1)
    ]
    if tail:
        _raise_rollout_alignment("tail-terminal", 8, tail, mode)

    summary = parse_transition_rows(
        collector.rewards,
        collector.terminals,
        final_rewards,
        final_terminals,
    )
    normalized = normalize_puffer_integrity(
        collector.env_logs,
        completed_summary=summary,
        endpoint_checks=collector.endpoint_checks,
    )
    result = dict(summary)
    result["integrity"] = normalized["integrity"]
    result["validation"] = normalized["validation"]
    return result


_AUDIT_CANONICAL_ARRAY_MAX_BYTES = 3145728
_CHECKPOINT_UPDATES = (0, 512, 1024, 1536, 2048, 2956)
_EVALUATION_ACTION_SEEDS = (
    2363161776,
    2079938504,
    2486426431,
    1428436532,
    3852947533,
    1935602315,
    2884042901,
    2683991200,
)
_EVIDENCE_CHECKPOINT_UPDATES = (0, 512, 1024, 1536, 2048, 2956)
_EXPECTED_SUBDIRECTORIES = (
    "checkpoints",
    "evaluation",
    "evaluation/update-000000",
    "evaluation/update-000000-repeat",
    "evaluation/update-000512",
    "evaluation/update-001024",
    "evaluation/update-001536",
    "evaluation/update-002048",
    "evaluation/update-002956",
)
_EXPECTED_JSON_ROOT_KEYS = {
    "effective-config.json": (
        "arguments",
        "environment",
        "protocol_sha256",
        "schema",
    ),
    "identity.json": (
        "audit",
        "dependencies",
        "module",
        "protocol_sha256",
        "puffer",
        "rng",
        "runtime",
        "schema",
        "source",
        "startup",
    ),
    "training-trace.jsonl": (
        "committed_epoch",
        "episodes",
        "global_agent_step",
        "losses",
        "objective",
        "parameters",
        "profile",
        "rollout",
        "schedule",
        "schema",
        "update_index",
    ),
    "results.json": (
        "checkpoint_zero_repeat",
        "evaluations",
        "learning_outcome",
        "paired_final_vs_initial",
        "protocol_sha256",
        "schema",
        "training",
    ),
    "evidence-manifest.json": (
        "completed_budget",
        "execution_status",
        "payload_count",
        "payloads",
        "protocol_sha256",
        "reserved_post_manifest_path",
        "schema",
    ),
    "verdict.json": (
        "accepted",
        "audit",
        "completed_budget",
        "evidence_manifest_sha256",
        "execution_status",
        "learning_outcome",
        "limitation",
        "module_sha256",
        "protocol_sha256",
        "puffer_commit",
        "replay",
        "schema",
        "source_commit",
    ),
}


def _build_expected_payload_paths():
    paths = [
        "protocol.json",
        "effective-config.json",
        "identity.json",
        "training-trace.jsonl",
        "results.json",
    ]
    paths.extend(
        "checkpoints/update-%06d.f5w" % (update,)
        for update in _EVIDENCE_CHECKPOINT_UPDATES
    )
    paths.extend(
        "evaluation/update-%06d/seed-%02d.bits"
        % (update, seed_index)
        for update in _EVIDENCE_CHECKPOINT_UPDATES
        for seed_index in range(8)
    )
    paths.extend(
        "evaluation/update-000000-repeat/seed-%02d.bits"
        % (seed_index,)
        for seed_index in range(8)
    )
    return tuple(sorted(paths))


_EXPECTED_PAYLOAD_PATHS = _build_expected_payload_paths()


def expected_payload_paths():
    """Return the closed, canonical payload-path authority."""

    return _EXPECTED_PAYLOAD_PATHS


def expected_subdirectories():
    """Return the closed, canonical evidence-directory authority."""

    return _EXPECTED_SUBDIRECTORIES


def _validated_relative_path_sequence(value, label):
    if type(value) not in (list, tuple):
        _fail(label + " must be an exact list or tuple")
    paths = []
    for index, path in enumerate(value):
        _require_ascii(
            path,
            "%s[%d]" % (label, index),
            printable=True,
            nonempty=True,
        )
        if not _validate_format(path, "relative-path"):
            _fail("%s[%d] is not a canonical relative path" % (label, index))
        paths.append(path)
    return tuple(paths)


def validate_evidence_path_set(files, directories, *, post_verdict):
    """Require the exact sorted pre- or post-verdict evidence topology."""

    if type(post_verdict) is not bool:
        _fail("post_verdict must be an exact Boolean")
    expected_file_count = 69 if post_verdict else 68
    if type(files) not in (list, tuple) or len(files) != expected_file_count:
        _fail("evidence file topology cardinality mismatch")
    if type(directories) not in (list, tuple) or len(directories) != 9:
        _fail("evidence directory topology cardinality mismatch")
    observed_files = _validated_relative_path_sequence(
        files,
        "evidence files",
    )
    observed_directories = _validated_relative_path_sequence(
        directories,
        "evidence directories",
    )
    expected_files = tuple(
        sorted(
            _EXPECTED_PAYLOAD_PATHS
            + ("evidence-manifest.json",)
            + (("verdict.json",) if post_verdict else ())
        )
    )
    if observed_files != expected_files:
        _fail("evidence file topology mismatch")
    if observed_directories != _EXPECTED_SUBDIRECTORIES:
        _fail("evidence directory topology mismatch")


def expected_json_root_keys(name):
    """Return the closed root-key authority for a completed JSON artifact."""

    _require_ascii(
        name,
        "JSON artifact name",
        printable=True,
        nonempty=True,
    )
    try:
        keys = _EXPECTED_JSON_ROOT_KEYS[name]
    except KeyError as error:
        raise ProtocolError("unknown completed JSON artifact") from error
    return tuple(sorted(keys))


_EVIDENCE_JSON_MAX_BYTES = 4194304
_EVIDENCE_TRACE_MAX_BYTES = 16777216
_EVIDENCE_READ_CHUNK_BYTES = 65536
_EVIDENCE_DIRECTORY_ENTRY_MAX = 9


class _DarwinStatfs(_ctypes.Structure):
    _fields_ = (
        ("f_bsize", _ctypes.c_uint32),
        ("f_iosize", _ctypes.c_int32),
        ("f_blocks", _ctypes.c_uint64),
        ("f_bfree", _ctypes.c_uint64),
        ("f_bavail", _ctypes.c_uint64),
        ("f_files", _ctypes.c_uint64),
        ("f_ffree", _ctypes.c_uint64),
        ("f_fsid", _ctypes.c_int32 * 2),
        ("f_owner", _ctypes.c_uint32),
        ("f_type", _ctypes.c_uint32),
        ("f_flags", _ctypes.c_uint32),
        ("f_fssubtype", _ctypes.c_uint32),
        ("f_fstypename", _ctypes.c_char * 16),
        ("f_mntonname", _ctypes.c_char * 1024),
        ("f_mntfromname", _ctypes.c_char * 1024),
        ("f_flags_ext", _ctypes.c_uint32),
        ("f_reserved", _ctypes.c_uint32 * 7),
    )


def _required_open_flags(*, directory):
    flags = _os.O_RDONLY
    for name in ("O_CLOEXEC", "O_NOFOLLOW"):
        value = getattr(_os, name, None)
        if type(value) is not int or value <= 0:
            _fail("required evidence open flag is unavailable: " + name)
        flags |= value
    if directory:
        value = getattr(_os, "O_DIRECTORY", None)
        if type(value) is not int or value <= 0:
            _fail("required evidence open flag is unavailable: O_DIRECTORY")
        flags |= value
    return flags


def _canonical_artifact_root(artifact_root):
    try:
        value = _os.fspath(artifact_root)
    except Exception as error:
        raise ProtocolError("artifact root is not path-like") from error
    _require_ascii(
        value,
        "artifact root",
        printable=True,
        nonempty=True,
    )
    if not _validate_format(value, "absolute-path"):
        _fail("artifact root is not a canonical absolute path")
    if _os.path.normpath(value) != value:
        _fail("artifact root contains redundant path syntax")
    return value


def _darwin_apfs_libc(root_fd):
    try:
        system_name = _os.uname().sysname
    except (AttributeError, OSError) as error:
        raise ProtocolError("Darwin host identity is unavailable") from error
    if system_name != "Darwin":
        _fail("evidence filesystem validation requires Darwin APFS")
    if _ctypes.sizeof(_DarwinStatfs) != 2168:
        _fail("Darwin statfs ABI width mismatch")
    try:
        libc = _ctypes.CDLL(None, use_errno=True)
        function = libc.fstatfs
        function.argtypes = [
            _ctypes.c_int,
            _ctypes.POINTER(_DarwinStatfs),
        ]
        function.restype = _ctypes.c_int
    except Exception as error:
        raise ProtocolError("Darwin fstatfs ABI is unavailable") from error
    record = _DarwinStatfs()
    _ctypes.set_errno(0)
    try:
        result = function(root_fd, _ctypes.byref(record))
    except Exception as error:
        raise ProtocolError("Darwin fstatfs call failed") from error
    saved_errno = _ctypes.get_errno()
    if type(result) is not int or result != 0 or saved_errno != 0:
        _fail(
            "Darwin fstatfs returned an untrusted result/errno pair "
            "(result=%r, errno=%r)" % (result, saved_errno)
        )
    filesystem_name = bytes(record.f_fstypename).split(b"\0", 1)[0]
    if filesystem_name != b"apfs":
        _fail("evidence filesystem is not APFS")
    return libc


def _stat_relative(parent_fd, name, label):
    try:
        return _os.stat(
            name,
            dir_fd=parent_fd,
            follow_symlinks=False,
        )
    except (OSError, TypeError, ValueError) as error:
        raise ProtocolError(label + ": no-follow stat failed") from error


def _fstat_descriptor(descriptor, label):
    try:
        return _os.fstat(descriptor)
    except (OSError, TypeError, ValueError) as error:
        raise ProtocolError(label + ": descriptor stat failed") from error


def _validated_directory_names(directory_fd, label):
    try:
        iterator = _os.scandir(directory_fd)
    except (OSError, TypeError) as error:
        raise ProtocolError(label + ": descriptor listing failed") from error
    validated = []
    try:
        with iterator:
            for entry in iterator:
                if len(validated) >= _EVIDENCE_DIRECTORY_ENTRY_MAX:
                    _fail(label + ": entry count exceeds the closed bound")
                try:
                    validated.append(
                        validate_public_component(
                            entry.name,
                            name_max=_DARWIN_NAME_MAX,
                        )
                    )
                except ProtocolError as error:
                    raise ProtocolError(
                        label + ": invalid entry name"
                    ) from error
    except ProtocolError:
        raise
    except (OSError, TypeError, ValueError) as error:
        raise ProtocolError(label + ": descriptor scan failed") from error
    if len(validated) != len(set(validated)):
        _fail(label + ": duplicate directory entry name")
    return tuple(sorted(validated))


def _open_snapshot_directory(parent_fd, name, named, label):
    try:
        descriptor = _os.open(
            name,
            _required_open_flags(directory=True),
            dir_fd=parent_fd,
        )
    except (OSError, TypeError, ValueError) as error:
        raise ProtocolError(label + ": no-follow directory open failed") from error
    try:
        held = _fstat_descriptor(descriptor, label)
        if not _stat.S_ISDIR(held.st_mode):
            _fail(label + ": held object is not a directory")
        if _identity_tuple(held) != _identity_tuple(named):
            _fail(label + ": named/held directory identity mismatch")
    except BaseException:
        _close_descriptor_transaction(
            descriptor,
            label,
            suppress_errors=True,
        )
        raise
    return descriptor


def _snapshot_file_bounds(path):
    if path == "protocol.json":
        return _PROTOCOL_BYTES, _PROTOCOL_BYTES
    if path == "training-trace.jsonl":
        return 1, _EVIDENCE_TRACE_MAX_BYTES
    if path.endswith(".f5w"):
        return _CHECKPOINT_BYTES, _CHECKPOINT_BYTES
    if path.endswith(".bits"):
        return 4096, 4096
    return 1, _EVIDENCE_JSON_MAX_BYTES


def _validate_declared_payload_byte_bounds(evidence_manifest):
    for entry in evidence_manifest["payloads"]:
        path = entry["path"]
        declared = entry["bytes"]
        minimum, maximum = _snapshot_file_bounds(path)
        if (
            type(declared) is not int
            or declared < minimum
            or declared > maximum
        ):
            _fail("evidence payload declared byte count is outside the bound")


def _read_snapshot_file(snapshot, path):
    parent_relative, basename = snapshot["file_parents"][path]
    parent_fd = snapshot["directory_fds"][parent_relative]
    label = "evidence file " + path
    named = _stat_relative(parent_fd, basename, label)
    classified = snapshot["file_metadata"][path]
    if _identity_tuple(named) != _identity_tuple(classified):
        _fail(label + ": entry changed after topology classification")
    if not _stat.S_ISREG(named.st_mode):
        _fail(label + ": entry is not a regular file")
    if _stat.S_IMODE(named.st_mode) != 0o600:
        _fail(label + ": mode mismatch")
    if named.st_nlink != 1:
        _fail(label + ": regular file is not single-link")
    minimum, maximum = _snapshot_file_bounds(path)
    if named.st_size < minimum or named.st_size > maximum:
        _fail(label + ": byte length is outside the trusted bound")

    try:
        descriptor = _os.open(
            basename,
            _required_open_flags(directory=False),
            dir_fd=parent_fd,
        )
    except (OSError, TypeError, ValueError) as error:
        raise ProtocolError(label + ": no-follow file open failed") from error
    completed = False
    try:
        held_before = _fstat_descriptor(descriptor, label)
        if _identity_tuple(held_before) != _identity_tuple(named):
            _fail(label + ": named/held file identity mismatch")
        require_no_extended_acl(snapshot["libc"], descriptor)
        chunks = []
        remaining = maximum + 1
        while remaining:
            try:
                chunk = _os.read(
                    descriptor,
                    min(_EVIDENCE_READ_CHUNK_BYTES, remaining),
                )
            except OSError as error:
                raise ProtocolError(label + ": bounded read failed") from error
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > maximum:
            _fail(label + ": bounded read exceeded the trusted ceiling")
        if len(raw) != held_before.st_size:
            _fail(label + ": bounded read size mismatch")
        held_after = _fstat_descriptor(descriptor, label)
        if _identity_tuple(held_after) != _identity_tuple(held_before):
            _fail(label + ": descriptor changed during read")
        completed = True
    finally:
        _close_descriptor_transaction(
            descriptor,
            label,
            suppress_errors=not completed,
        )
    named_after = _stat_relative(parent_fd, basename, label)
    if _identity_tuple(named_after) != _identity_tuple(named):
        _fail(label + ": named entry changed during read")
    return raw


def _validate_classified_file_metadata(snapshot, path):
    metadata = snapshot["file_metadata"][path]
    label = "evidence file " + path
    if not _stat.S_ISREG(metadata.st_mode):
        _fail(label + ": entry is not a regular file")
    if _stat.S_IMODE(metadata.st_mode) != 0o600:
        _fail(label + ": mode mismatch")
    if metadata.st_nlink != 1:
        _fail(label + ": regular file is not single-link")
    minimum, maximum = _snapshot_file_bounds(path)
    if metadata.st_size < minimum or metadata.st_size > maximum:
        _fail(label + ": byte length is outside the trusted bound")


def _snapshot_read_once(snapshot, path):
    if path not in snapshot["raws"]:
        snapshot["raws"][path] = _read_snapshot_file(snapshot, path)
    return snapshot["raws"][path]


def _read_snapshot_payloads(snapshot):
    for path in _EXPECTED_PAYLOAD_PATHS:
        _snapshot_read_once(snapshot, path)


def _open_evidence_snapshot(
    artifact_root,
    manifest,
    *,
    post_verdict,
    expected_verdict_sha256=None,
):
    if type(post_verdict) is not bool:
        _fail("snapshot verdict phase must be an exact Boolean")
    root = _canonical_artifact_root(artifact_root)
    try:
        root_named = _os.lstat(root)
    except OSError as error:
        raise ProtocolError("artifact root lstat failed") from error
    if not _stat.S_ISDIR(root_named.st_mode):
        _fail("artifact root is not an ordinary directory")
    if _stat.S_IMODE(root_named.st_mode) != 0o700:
        _fail("artifact root mode mismatch")
    try:
        root_fd = _os.open(root, _required_open_flags(directory=True))
    except OSError as error:
        raise ProtocolError("artifact root no-follow open failed") from error

    snapshot = {
        "directory_fds": {".": root_fd},
        "directory_metadata": {".": root_named},
        "directory_order": ["."],
        "directory_parents": {},
        "file_metadata": {},
        "file_parents": {},
        "immediate_names": {},
        "libc": None,
        "raws": {},
        "root": root,
    }
    try:
        root_held = _fstat_descriptor(root_fd, "artifact root")
        if _identity_tuple(root_held) != _identity_tuple(root_named):
            _fail("artifact root named/held identity mismatch")
        snapshot["libc"] = _darwin_apfs_libc(root_fd)

        expected_directories = frozenset(_EXPECTED_SUBDIRECTORIES)
        observed_directories = []
        observed_files = []
        unsupported = []
        queue = ["."]
        while queue:
            parent_relative = queue.pop(0)
            parent_fd = snapshot["directory_fds"][parent_relative]
            label = "artifact directory " + parent_relative
            names = _validated_directory_names(parent_fd, label)
            snapshot["immediate_names"][parent_relative] = names
            for name in names:
                relative = (
                    name
                    if parent_relative == "."
                    else parent_relative + "/" + name
                )
                named = _stat_relative(parent_fd, name, label)
                if _stat.S_ISDIR(named.st_mode):
                    observed_directories.append(relative)
                    if relative in expected_directories:
                        descriptor = _open_snapshot_directory(
                            parent_fd,
                            name,
                            named,
                            "artifact directory " + relative,
                        )
                        snapshot["directory_fds"][relative] = descriptor
                        snapshot["directory_metadata"][relative] = named
                        snapshot["directory_order"].append(relative)
                        snapshot["directory_parents"][relative] = (
                            parent_relative,
                            name,
                        )
                        queue.append(relative)
                elif _stat.S_ISREG(named.st_mode):
                    observed_files.append(relative)
                    snapshot["file_metadata"][relative] = named
                    snapshot["file_parents"][relative] = (
                        parent_relative,
                        name,
                    )
                else:
                    unsupported.append(relative)
        if unsupported:
            _fail("artifact topology contains an unsupported entry kind")
        validate_evidence_path_set(
            tuple(sorted(observed_files)),
            tuple(sorted(observed_directories)),
            post_verdict=post_verdict,
        )

        phase = "post_verdict" if post_verdict else "pre_verdict"
        try:
            expected_links = manifest["artifact"][
                "directory_link_counts"
            ][phase]
        except (KeyError, TypeError) as error:
            raise ProtocolError(
                "authenticated directory link authority is absent"
            ) from error
        if set(expected_links) != {".", *_EXPECTED_SUBDIRECTORIES}:
            _fail("authenticated directory link authority is malformed")
        for relative in (".", *_EXPECTED_SUBDIRECTORIES):
            metadata = snapshot["directory_metadata"][relative]
            held = _fstat_descriptor(
                snapshot["directory_fds"][relative],
                "artifact directory " + relative,
            )
            if _identity_tuple(held) != _identity_tuple(metadata):
                _fail("artifact directory identity drifted: " + relative)
            if _stat.S_IMODE(held.st_mode) != 0o700:
                _fail("artifact directory mode mismatch: " + relative)
            expected_link_count = expected_links[relative]
            if (
                type(expected_link_count) is not int
                or held.st_nlink != expected_link_count
            ):
                _fail("artifact directory link count mismatch: " + relative)
            require_no_extended_acl(
                snapshot["libc"],
                snapshot["directory_fds"][relative],
            )

        classified_files = list(_EXPECTED_PAYLOAD_PATHS)
        classified_files.append("evidence-manifest.json")
        if post_verdict:
            classified_files.append("verdict.json")
        for path in classified_files:
            _validate_classified_file_metadata(snapshot, path)

        first_path = (
            "verdict.json" if post_verdict else "evidence-manifest.json"
        )
        first_raw = _snapshot_read_once(snapshot, first_path)
        if post_verdict:
            observed = _hashlib.sha256(first_raw).hexdigest()
            if observed != expected_verdict_sha256:
                _fail("verdict raw SHA-256 differs from external authority")
        return snapshot
    except BaseException:
        _close_evidence_snapshot(snapshot, suppress_errors=True)
        raise


def _revalidate_evidence_snapshot(snapshot):
    for relative in snapshot["directory_order"]:
        descriptor = snapshot["directory_fds"][relative]
        label = "artifact directory " + relative
        names = _validated_directory_names(descriptor, label)
        if names != snapshot["immediate_names"][relative]:
            _fail(label + ": entry set changed during validation")
        held = _fstat_descriptor(descriptor, label)
        original = snapshot["directory_metadata"][relative]
        if _identity_tuple(held) != _identity_tuple(original):
            _fail(label + ": held identity changed during validation")
        if relative == ".":
            try:
                named = _os.lstat(snapshot["root"])
            except OSError as error:
                raise ProtocolError(
                    "artifact root postflight lstat failed"
                ) from error
        else:
            parent_relative, basename = snapshot["directory_parents"][
                relative
            ]
            named = _stat_relative(
                snapshot["directory_fds"][parent_relative],
                basename,
                label,
            )
        if _identity_tuple(named) != _identity_tuple(original):
            _fail(label + ": named identity changed during validation")
    for path in sorted(snapshot["file_metadata"]):
        parent_relative, basename = snapshot["file_parents"][path]
        named = _stat_relative(
            snapshot["directory_fds"][parent_relative],
            basename,
            "evidence file " + path,
        )
        if _identity_tuple(named) != _identity_tuple(
            snapshot["file_metadata"][path]
        ):
            _fail("evidence file identity changed during validation: " + path)


def _close_evidence_snapshot(snapshot, *, suppress_errors):
    if type(suppress_errors) is not bool:
        _fail("evidence snapshot cleanup mode must be an exact Boolean")
    first_error = None
    for relative in reversed(snapshot.get("directory_order", ())):
        descriptor = snapshot.get("directory_fds", {}).get(relative)
        if type(descriptor) is int:
            try:
                _os.close(descriptor)
            except Exception as error:
                if first_error is None:
                    first_error = error
    if first_error is not None and not suppress_errors:
        raise ProtocolError(
            "evidence snapshot descriptor cleanup failed"
        ) from first_error


def _canonical_payload_document(raw, name, registry):
    document = _parse_canonical_json(raw, "evidence payload " + name)
    try:
        schema = registry["roots"][name]
    except (KeyError, TypeError) as error:
        raise ProtocolError("payload schema root is absent: " + name) from error
    _validate_schema_value(document, schema, registry, "$" + name)
    return document


def _canonical_json_semantic_sha256(raw):
    return _hashlib.sha256(b"f5-canonical-json-v1\0" + raw).hexdigest()


def _validate_entry_semantic(entry, observed, label):
    if entry["semantic_sha256"] != observed:
        _fail(label + " semantic digest mismatch")


def _validate_identity_bindings(identity, manifest):
    if identity["protocol_sha256"] != _PROTOCOL_SHA256:
        _fail("runtime identity protocol digest mismatch")
    puffer = manifest["puffer"]
    expected_puffer = {
        "commit": puffer["base_git"]["commit"],
        "source_file_count": puffer["source_closure"]["file_count"],
        "source_manifest_sha256": puffer["source_closure"][
            "manifest_sha256"
        ],
        "status_sha256": puffer["qualified_staged_tree"][
            "status_sha256"
        ],
        "tree": puffer["base_git"]["tree"],
        "version": puffer["version"],
    }
    if not _exact_json_equal(identity["puffer"], expected_puffer):
        _fail("runtime identity Puffer binding mismatch")
    module = puffer["module"]
    expected_module = {
        "fixture_enabled": module["fixture_enabled"],
        "fixture_role": module["fixture_role"],
        "gpu_flag": module["gpu_flag"],
        "path": module["path"],
        "sha256": module["sha256"],
        "state_bank_kind": module["state_bank_kind"],
    }
    if not _exact_json_equal(identity["module"], expected_module):
        _fail("runtime identity compiled-module binding mismatch")

    rng = manifest["execution"]["rng"]
    expected_rng = {
        "numpy_after": rng["numpy"]["oracle_sha256"],
        "numpy_before": rng["numpy"]["oracle_sha256"],
        "python_after": rng["python"]["oracle_sha256"],
        "python_before": rng["python"]["oracle_sha256"],
        "torch_after": rng["torch_cpu"]["oracle_sha256"],
        "torch_before": rng["torch_cpu"]["oracle_sha256"],
    }
    if not _exact_json_equal(identity["rng"], expected_rng):
        _fail("runtime identity RNG oracle binding mismatch")

    startup = identity["startup"]
    worker_paths = startup["worker_sys_path"]
    prepared_root = worker_paths[-1]
    _require_ascii(
        prepared_root,
        "prepared Puffer root identity",
        printable=True,
        nonempty=True,
    )
    if not _validate_format(prepared_root, "absolute-path"):
        _fail("prepared Puffer root identity is not canonical")
    expected_site_packages = (
        prepared_root + "/.venv/lib/python3.12/site-packages"
    )
    if worker_paths[-2] != expected_site_packages:
        _fail("worker sys.path prepared-root relationship mismatch")

    resolved = startup["scratch_paths"]["resolved"]
    scratch_root = resolved["root"]
    _require_ascii(
        scratch_root,
        "runtime scratch root identity",
        printable=True,
        nonempty=True,
    )
    if not _validate_format(scratch_root, "absolute-path"):
        _fail("runtime scratch root identity is not canonical")
    expected_scratch = {
        "cache": scratch_root + "/cache",
        "home": scratch_root + "/home",
        "root": scratch_root,
        "tmp": scratch_root + "/tmp",
    }
    if not _exact_json_equal(resolved, expected_scratch):
        _fail("runtime scratch-path relationship mismatch")
    validate_audit_binding(identity, population="controller")


def _checkpoint_parameter_l2_from_raw(current, initial):
    if (
        type(current) is not bytes
        or type(initial) is not bytes
        or len(current) != _CHECKPOINT_BYTES
        or len(initial) != _CHECKPOINT_BYTES
    ):
        _fail("checkpoint telemetry requires two exact raw checkpoints")
    norm_sum = 0.0
    drift_sum = 0.0
    current_values = _struct.iter_unpack("<f", current)
    initial_values = _struct.iter_unpack("<f", initial)
    for current_item, initial_item in zip(current_values, initial_values):
        current_value = current_item[0]
        initial_value = initial_item[0]
        norm_sum = norm_sum + current_value * current_value
        delta = current_value - initial_value
        drift_sum = drift_sum + delta * delta
    norm = _math.sqrt(norm_sum)
    drift = _math.sqrt(drift_sum)
    if not _math.isfinite(norm) or not _math.isfinite(drift):
        _fail("checkpoint telemetry overflowed binary64")
    return {"drift_from_initial": drift, "norm": norm}


def _bitset_semantic_from_path(path, raw):
    repeat = _re.fullmatch(
        r"evaluation/update-000000-repeat/seed-([0-9]{2})\.bits",
        path,
    )
    if repeat is not None:
        update = 0
        seed_index = int(repeat.group(1))
        repeat_flag = 1
    else:
        primary = _re.fullmatch(
            r"evaluation/update-([0-9]{6})/seed-([0-9]{2})\.bits",
            path,
        )
        if primary is None:
            _fail("evidence bitset path is not in a frozen semantic domain")
        update = int(primary.group(1))
        seed_index = int(primary.group(2))
        repeat_flag = 0
    if update not in _EVIDENCE_CHECKPOINT_UPDATES:
        _fail("evidence bitset checkpoint update is not frozen")
    if seed_index < 0 or seed_index >= len(_RESULT_ACTION_SEEDS):
        _fail("evidence bitset seed index is not frozen")
    return success_bitset_sha256(
        checkpoint_update=update,
        seed_index=seed_index,
        action_seed=_RESULT_ACTION_SEEDS[seed_index],
        episode_count=32768,
        repeat_flag=repeat_flag,
        raw=raw,
    )


def _git_object_from_output(raw, label):
    if type(raw) is not bytes or len(raw) != 41 or raw[-1:] != b"\n":
        _fail(label + " output framing mismatch")
    try:
        value = raw[:-1].decode("ascii")
    except UnicodeDecodeError as error:
        raise ProtocolError(label + " output is not ASCII") from error
    if not _is_lower_hex(value, 40):
        _fail(label + " output is not a lowercase Git object")
    return value


def _validate_live_source_identity(identity):
    try:
        module_path = _os.path.abspath(_os.fspath(__file__))
    except (NameError, TypeError, ValueError) as error:
        raise ProtocolError("protocol helper source path is unavailable") from error
    if (
        _os.path.basename(module_path) != "f5_recurrent_ppo_protocol.py"
        or _os.path.basename(_os.path.dirname(module_path)) != "tools"
    ):
        _fail("protocol helper source path is outside the frozen layout")
    repository_root = _os.path.dirname(_os.path.dirname(module_path))
    built = build_implementation_manifest(repository_root)
    source = identity["source"]
    if built["sha256"] != source["implementation_manifest_sha256"]:
        _fail("live implementation-manifest digest mismatch")
    head = _git_object_from_output(
        _run_git(repository_root, ["rev-parse", "HEAD"]),
        "source HEAD",
    )
    tree = _git_object_from_output(
        _run_git(repository_root, ["rev-parse", "HEAD^{tree}"]),
        "source tree",
    )
    if source["commit"] != head or source["tree"] != tree:
        _fail("runtime identity does not bind the live source commit/tree")
    clean_status = b""
    if source["status_sha256"] != git_status_sha256(clean_status):
        _fail("runtime identity clean-status digest mismatch")
    if source["zero_bytecode"] is not True:
        _fail("runtime identity did not assert zero bytecode")
    require_zero_bytecode((repository_root,))
    final_status = _run_git(
        repository_root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
    )
    if final_status != clean_status:
        _fail("live source became dirty during evidence validation")
    return {"commit": head, "repository_root": repository_root, "tree": tree}


def _validate_evidence_core(snapshot, evidence_manifest, manifest, registry):
    if type(evidence_manifest) is not dict:
        _fail("evidence manifest must be an exact object")
    evidence_raw = snapshot["raws"]["evidence-manifest.json"]
    if canonical_json_bytes(evidence_manifest) != evidence_raw:
        _fail("on-disk evidence manifest differs from canonical input")
    disk_evidence_manifest = _parse_canonical_json(
        evidence_raw,
        "on-disk evidence manifest",
    )
    if not _exact_json_equal(disk_evidence_manifest, evidence_manifest):
        _fail("on-disk evidence manifest semantic identity mismatch")
    evidence_manifest = disk_evidence_manifest
    _validate_schema_value(
        evidence_manifest,
        registry["roots"]["evidence-manifest.json"],
        registry,
        "$evidence-manifest",
    )
    _validate_declared_payload_byte_bounds(evidence_manifest)
    if evidence_manifest["protocol_sha256"] != _PROTOCOL_SHA256:
        _fail("evidence manifest protocol digest mismatch")
    if tuple(manifest["artifact"]["payloads"]) != _EXPECTED_PAYLOAD_PATHS:
        _fail("authenticated protocol payload authority mismatch")
    entries = evidence_manifest["payloads"]
    entry_paths = tuple(entry["path"] for entry in entries)
    if entry_paths != _EXPECTED_PAYLOAD_PATHS:
        _fail("evidence payload entry order/topology mismatch")
    entries_by_path = {entry["path"]: entry for entry in entries}
    if len(entries_by_path) != len(_EXPECTED_PAYLOAD_PATHS):
        _fail("evidence payload entries are not unique")

    _read_snapshot_payloads(snapshot)
    raw_sha256 = {}
    for path in _EXPECTED_PAYLOAD_PATHS:
        entry = entries_by_path[path]
        raw = snapshot["raws"][path]
        if entry["bytes"] != len(raw):
            _fail("evidence payload byte count mismatch: " + path)
        digest = _hashlib.sha256(raw).hexdigest()
        if entry["sha256"] != digest:
            _fail("evidence payload raw digest mismatch: " + path)
        raw_sha256[path] = digest

    protocol_raw = snapshot["raws"]["protocol.json"]
    trusted_protocol_raw = canonical_json_bytes(manifest)
    if (
        protocol_raw != trusted_protocol_raw
        or len(protocol_raw) != _PROTOCOL_BYTES
        or raw_sha256["protocol.json"] != _PROTOCOL_SHA256
    ):
        _fail("artifact protocol bytes differ from tracked protocol")
    parsed_protocol = _parse_canonical_json(
        protocol_raw,
        "artifact protocol",
    )
    if not _exact_json_equal(parsed_protocol, manifest):
        _fail("artifact protocol semantic identity mismatch")
    _validate_entry_semantic(
        entries_by_path["protocol.json"],
        _canonical_json_semantic_sha256(protocol_raw),
        "artifact protocol",
    )

    effective_raw = snapshot["raws"]["effective-config.json"]
    effective = _canonical_payload_document(
        effective_raw,
        "effective-config.json",
        registry,
    )
    validate_effective_config(effective, manifest)
    _validate_entry_semantic(
        entries_by_path["effective-config.json"],
        _canonical_json_semantic_sha256(effective_raw),
        "effective config",
    )

    identity_raw = snapshot["raws"]["identity.json"]
    identity = _canonical_payload_document(
        identity_raw,
        "identity.json",
        registry,
    )
    _validate_identity_bindings(identity, manifest)
    _validate_entry_semantic(
        entries_by_path["identity.json"],
        _canonical_json_semantic_sha256(identity_raw),
        "runtime identity",
    )

    trace_raw = snapshot["raws"]["training-trace.jsonl"]
    trace_rows = validate_training_trace(trace_raw, manifest)
    _validate_entry_semantic(
        entries_by_path["training-trace.jsonl"],
        _hashlib.sha256(b"f5-training-trace-v1\0" + trace_raw).hexdigest(),
        "training trace",
    )

    checkpoint_raw = {}
    checkpoint_semantic = {}
    for update in _EVIDENCE_CHECKPOINT_UPDATES:
        path = "checkpoints/update-%06d.f5w" % (update,)
        raw = snapshot["raws"][path]
        decoded = decode_fixed_checkpoint(raw)
        semantic = canonical_tensor_sha256(decoded)
        _validate_entry_semantic(
            entries_by_path[path],
            semantic,
            "checkpoint " + str(update),
        )
        checkpoint_raw[update] = raw
        checkpoint_semantic[update] = semantic
    if raw_sha256["checkpoints/update-000000.f5w"] != (
        EXPECTED_INITIAL_RAW_SHA256
    ):
        _fail("initial checkpoint raw identity mismatch")
    if checkpoint_semantic[0] != EXPECTED_INITIAL_PARAMETER_SHA256:
        _fail("initial checkpoint canonical identity mismatch")
    initial_raw = checkpoint_raw[0]
    for update in _EVIDENCE_CHECKPOINT_UPDATES[1:]:
        parameters = trace_rows[update - 1]["parameters"]
        if parameters["canonical_sha256"] != checkpoint_semantic[update]:
            _fail("checkpoint/trace canonical digest mismatch")
        telemetry = _checkpoint_parameter_l2_from_raw(
            checkpoint_raw[update],
            initial_raw,
        )
        if not _strict_equal(parameters["norm"], telemetry["norm"]):
            _fail("checkpoint/trace parameter norm mismatch")
        if not _strict_equal(
            parameters["drift_from_initial"],
            telemetry["drift_from_initial"],
        ):
            _fail("checkpoint/trace parameter drift mismatch")

    bitsets = {}
    for path in _EXPECTED_PAYLOAD_PATHS:
        if not path.endswith(".bits"):
            continue
        raw = snapshot["raws"][path]
        semantic = _bitset_semantic_from_path(path, raw)
        _validate_entry_semantic(
            entries_by_path[path],
            semantic,
            "evaluation bitset " + path,
        )
        bitsets[path] = raw

    results_raw = snapshot["raws"]["results.json"]
    results = _canonical_payload_document(
        results_raw,
        "results.json",
        registry,
    )
    validate_results(
        results,
        manifest,
        trace_rows=trace_rows,
        bitsets=bitsets,
    )
    _validate_entry_semantic(
        entries_by_path["results.json"],
        _canonical_json_semantic_sha256(results_raw),
        "results",
    )
    source = _validate_live_source_identity(identity)
    return {
        "checkpoint_raw_sha256": {
            update: raw_sha256[
                "checkpoints/update-%06d.f5w" % (update,)
            ]
            for update in _EVIDENCE_CHECKPOINT_UPDATES
        },
        "checkpoint_semantic": checkpoint_semantic,
        "effective_config": effective,
        "evidence_manifest": evidence_manifest,
        "identity": identity,
        "results": results,
        "source": source,
        "trace_rows": trace_rows,
    }


def validate_evidence_manifest(artifact_root, evidence_manifest):
    """Validate one immutable pre-verdict artifact and its supplied manifest."""

    manifest = load_protocol_manifest()
    registry = _authenticated_manifest_registry(manifest)
    if type(evidence_manifest) is not dict:
        _fail("supplied evidence manifest must be an exact object")
    _validate_schema_value(
        evidence_manifest,
        registry["roots"]["evidence-manifest.json"],
        registry,
        "$supplied-evidence-manifest",
    )
    _validate_declared_payload_byte_bounds(evidence_manifest)
    supplied_raw = canonical_json_bytes(evidence_manifest)
    snapshot = _open_evidence_snapshot(
        artifact_root,
        manifest,
        post_verdict=False,
    )
    completed = False
    try:
        if snapshot["raws"]["evidence-manifest.json"] != supplied_raw:
            _fail("on-disk evidence manifest differs from supplied manifest")
        validated = _validate_evidence_core(
            snapshot,
            evidence_manifest,
            manifest,
            registry,
        )
        _revalidate_evidence_snapshot(snapshot)
        result = validated["evidence_manifest"]
        completed = True
        return result
    finally:
        _close_evidence_snapshot(
            snapshot,
            suppress_errors=not completed,
        )


def _validate_verdict_bindings(verdict, state, manifest, evidence_raw):
    evidence = state["evidence_manifest"]
    identity = state["identity"]
    results = state["results"]
    if verdict["evidence_manifest_sha256"] != _hashlib.sha256(
        evidence_raw
    ).hexdigest():
        _fail("verdict evidence-manifest digest mismatch")
    if (
        verdict["protocol_sha256"] != _PROTOCOL_SHA256
        or verdict["protocol_sha256"] != evidence["protocol_sha256"]
    ):
        _fail("verdict protocol binding mismatch")
    expected_module = manifest["puffer"]["module"]["sha256"]
    if (
        verdict["module_sha256"] != expected_module
        or identity["module"]["sha256"] != expected_module
    ):
        _fail("verdict compiled-module binding mismatch")
    expected_puffer = manifest["puffer"]["base_git"]["commit"]
    if (
        verdict["puffer_commit"] != expected_puffer
        or identity["puffer"]["commit"] != expected_puffer
    ):
        _fail("verdict Puffer commit binding mismatch")
    if (
        verdict["source_commit"] != identity["source"]["commit"]
        or verdict["source_commit"] != state["source"]["commit"]
    ):
        _fail("verdict live source commit binding mismatch")
    if verdict["learning_outcome"] != results["learning_outcome"]:
        _fail("verdict learning-outcome binding mismatch")
    replay = verdict["replay"]
    expected_replay = {
        "checkpoint_zero_raw_sha256": state["checkpoint_raw_sha256"][0],
        "checkpoint_zero_tensor_sha256": state["checkpoint_semantic"][0],
        "final_checkpoint_raw_sha256": state["checkpoint_raw_sha256"][2956],
        "final_checkpoint_tensor_sha256": state["checkpoint_semantic"][2956],
    }
    for name, expected in expected_replay.items():
        if replay[name] != expected:
            _fail("verdict replay binding mismatch: " + name)
    validate_audit_binding(verdict, population="verifier")


def validate_final_evidence(artifact_root, expected_verdict_sha256):
    """Validate post-verdict evidence against an external digest authority."""

    if not _is_lower_hex(expected_verdict_sha256, 64):
        _fail("expected verdict SHA-256 must be 64 lowercase hexadecimal")
    manifest = load_protocol_manifest()
    registry = _authenticated_manifest_registry(manifest)
    snapshot = _open_evidence_snapshot(
        artifact_root,
        manifest,
        post_verdict=True,
        expected_verdict_sha256=expected_verdict_sha256,
    )
    completed = False
    try:
        verdict_raw = snapshot["raws"]["verdict.json"]
        verdict = _canonical_payload_document(
            verdict_raw,
            "verdict.json",
            registry,
        )
        evidence_raw = _snapshot_read_once(
            snapshot,
            "evidence-manifest.json",
        )
        if verdict["evidence_manifest_sha256"] != _hashlib.sha256(
            evidence_raw
        ).hexdigest():
            _fail("verdict does not authenticate the evidence manifest")
        evidence = _parse_canonical_json(
            evidence_raw,
            "on-disk evidence manifest",
        )
        state = _validate_evidence_core(
            snapshot,
            evidence,
            manifest,
            registry,
        )
        _validate_verdict_bindings(
            verdict,
            state,
            manifest,
            evidence_raw,
        )
        _revalidate_evidence_snapshot(snapshot)
        completed = True
        return verdict
    finally:
        _close_evidence_snapshot(
            snapshot,
            suppress_errors=not completed,
        )


def _validate_audit_paths(paths, digest):
    observed = opened_paths_sha256(paths)
    if digest != observed:
        _fail("audit opened-path digest mismatch")
    if not paths:
        _fail("audit opened paths must contain at least one token")
    manifest = load_protocol_manifest()
    try:
        allowlist = manifest["execution"]["audit"]["allowlist"]
        exact_path_values = allowlist["exact_paths"]
        prefix_rule_values = allowlist["prefix_rules"]
    except (KeyError, TypeError) as error:
        raise ProtocolError(
            "authenticated audit allowlist is unavailable"
        ) from error
    if (
        type(allowlist) is not dict
        or allowlist.get("artifact_scope")
        != "six-checkpoint-inputs-only"
        or allowlist.get("prefix_component_boundary_required") is not True
        or allowlist.get("reject_unlisted_path_or_prefix") is not True
        or type(exact_path_values) is not list
        or type(prefix_rule_values) is not list
    ):
        _fail("authenticated audit allowlist shape mismatch")
    exact_paths = frozenset(exact_path_values)
    if len(exact_paths) != len(exact_path_values):
        _fail("authenticated audit exact paths are not unique")
    for token in exact_paths:
        _validate_normalized_open_token(token)
    prefixes = []
    for rule in prefix_rule_values:
        if type(rule) is not dict:
            _fail("authenticated audit prefix rule is not an object")
        try:
            prefix = rule["normalized_prefix"]
        except KeyError as error:
            raise ProtocolError(
                "authenticated audit prefix is unavailable"
            ) from error
        _validate_normalized_open_token(prefix)
        prefixes.append(prefix)
    if len(prefixes) != 3 or len(set(prefixes)) != len(prefixes):
        _fail("authenticated audit prefixes are not the frozen three")
    forbidden_basenames = {
        "evidence-manifest.json",
        "identity.json",
        "results.json",
        "training-trace.jsonl",
        "verdict.json",
    }
    for token in paths:
        if token not in exact_paths and not any(
            token == prefix or token.startswith(prefix + "/")
            for prefix in prefixes
        ):
            _fail("audit token is outside the authenticated allowlist")
        basename = token.rsplit("/", 1)[-1]
        if token.endswith(".bits") or basename in forbidden_basenames:
            _fail("audited worker opened a supervisor-owned output")


def _validate_training_audit_receipt(receipt):
    if type(receipt) is not dict or set(receipt) != {
        "network_attempts",
        "opened_paths",
        "opened_paths_sha256",
        "schema",
        "worker_kind",
    }:
        _fail("training audit receipt keys mismatch")
    if (
        receipt["schema"] != "bloodbowl-f5-training-worker-audit-v1"
        or receipt["worker_kind"] != "training"
        or type(receipt["network_attempts"]) is not int
        or receipt["network_attempts"] != 0
    ):
        _fail("training audit receipt identity mismatch")
    _validate_audit_paths(
        receipt["opened_paths"],
        receipt["opened_paths_sha256"],
    )


def _validate_evaluation_audit_receipt(
    receipt,
    update,
    seed_index,
    repeat_flag,
):
    if type(receipt) is not dict or set(receipt) != {
        "action_seed",
        "checkpoint_update",
        "network_attempts",
        "opened_paths",
        "opened_paths_sha256",
        "repeat_flag",
        "schema",
        "seed_index",
        "worker_kind",
    }:
        _fail("evaluation audit receipt keys mismatch")
    exact_values = (
        (receipt["action_seed"], _EVALUATION_ACTION_SEEDS[seed_index]),
        (receipt["checkpoint_update"], update),
        (receipt["network_attempts"], 0),
        (receipt["repeat_flag"], repeat_flag),
        (receipt["seed_index"], seed_index),
    )
    if any(type(observed) is not int or observed != expected for observed, expected in exact_values):
        _fail("evaluation audit receipt numeric identity mismatch")
    if (
        receipt["schema"] != "bloodbowl-f5-evaluation-worker-audit-v1"
        or receipt["worker_kind"] != "evaluation"
    ):
        _fail("evaluation audit receipt schema identity mismatch")
    _validate_audit_paths(
        receipt["opened_paths"],
        receipt["opened_paths_sha256"],
    )


def aggregate_audit_receipts(receipts, *, population):
    if type(receipts) is not list:
        _fail("audit receipts must be an exact array")
    if population not in ("controller", "verifier") or type(population) is not str:
        _fail("audit population is not frozen")
    expected_count = 57 if population == "controller" else 56
    if len(receipts) != expected_count:
        _fail("audit receipt population width mismatch")

    offset = 0
    if population == "controller":
        _validate_training_audit_receipt(receipts[0])
        offset = 1
    expected_identities = []
    for update in _CHECKPOINT_UPDATES:
        for seed_index in range(8):
            expected_identities.append((update, seed_index, 0))
    for seed_index in range(8):
        expected_identities.append((0, seed_index, 1))
    for index, identity in enumerate(expected_identities):
        _validate_evaluation_audit_receipt(
            receipts[offset + index],
            identity[0],
            identity[1],
            identity[2],
        )

    opened = set()
    network_attempts = 0
    for receipt in receipts:
        network_attempts += receipt["network_attempts"]
        opened.update(receipt["opened_paths"])
        if len(opened) > 65535:
            _fail("aggregate audit paths exceed the item cap")
    paths = sorted(opened)
    canonical = canonical_json_bytes(paths)
    if len(canonical) > _AUDIT_CANONICAL_ARRAY_MAX_BYTES:
        _fail("aggregate audit paths exceed the canonical byte cap")
    if network_attempts != 0:
        _fail("aggregate audit contains a network attempt")
    return {
        "network_attempts": 0,
        "opened_paths": paths,
        "opened_paths_sha256": opened_paths_sha256(paths),
        "worker_count": expected_count,
    }


def validate_audit_binding(document, *, population):
    if type(document) is not dict or "audit" not in document:
        _fail("audit-bearing document is malformed")
    audit = document["audit"]
    if type(audit) is not dict or set(audit) != {
        "network_attempts",
        "opened_paths",
        "opened_paths_sha256",
        "worker_count",
    }:
        _fail("aggregate audit binding keys mismatch")
    expected_count = 57 if population == "controller" else 56 if population == "verifier" else None
    if expected_count is None:
        _fail("audit binding population is not frozen")
    if (
        type(audit["worker_count"]) is not int
        or audit["worker_count"] != expected_count
        or type(audit["network_attempts"]) is not int
        or audit["network_attempts"] != 0
    ):
        _fail("aggregate audit binding counters mismatch")
    _validate_audit_paths(
        audit["opened_paths"],
        audit["opened_paths_sha256"],
    )


def implementation_manifest_sha256(entries):
    if type(entries) is not list or len(entries) != len(IMPLEMENTATION_PATHS):
        _fail("implementation manifest entry count mismatch")
    for index, expected_path in enumerate(IMPLEMENTATION_PATHS):
        entry = entries[index]
        if type(entry) is not dict or set(entry) != {
            "bytes",
            "path",
            "sha256",
        }:
            _fail("implementation manifest entry keys mismatch")
        if (
            entry["path"] != expected_path
            or type(entry["path"]) is not str
            or type(entry["bytes"]) is not int
            or entry["bytes"] < 0
            or not _is_lower_hex(entry["sha256"], 64)
        ):
            _fail("implementation manifest entry identity mismatch")
        if not _validate_format(entry["path"], "relative-path"):
            _fail("implementation manifest path is not canonical")
    canonical = canonical_json_bytes(entries)
    return _hashlib.sha256(
        b"bloodbowl-f5-implementation-manifest-v1\0" + canonical
    ).hexdigest()


def _run_git(repository_root, arguments):
    environment = {"PATH": "/usr/bin:/bin", "LANG": "C", "LC_ALL": "C"}
    try:
        completed = _subprocess.run(
            ["git", "-C", repository_root, *arguments],
            check=False,
            capture_output=True,
            env=environment,
        )
    except OSError as error:
        raise ProtocolError("Git source-identity command failed") from error
    if completed.returncode != 0 or completed.stderr:
        _fail("Git source-identity command was not clean")
    return completed.stdout


def _read_dynamic_regular_file(path, label):
    try:
        before_path = _os.lstat(path)
    except OSError as error:
        raise ProtocolError(label + ": lstat failed") from error
    if not _stat.S_ISREG(before_path.st_mode) or before_path.st_nlink != 1:
        _fail(label + ": source entry is not regular single-link")
    flags = _os.O_RDONLY | getattr(_os, "O_CLOEXEC", 0) | getattr(_os, "O_NOFOLLOW", 0)
    try:
        descriptor = _os.open(path, flags)
    except OSError as error:
        raise ProtocolError(label + ": no-follow open failed") from error
    completed = False
    try:
        before_fd = _fstat_descriptor(descriptor, label)
        if _identity_tuple(before_fd) != _identity_tuple(before_path):
            _fail(label + ": descriptor/path identity mismatch")
        chunks = []
        remaining = before_fd.st_size + 1
        while remaining:
            try:
                chunk = _os.read(descriptor, min(65536, remaining))
            except OSError as error:
                raise ProtocolError(label + ": source read failed") from error
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) != before_fd.st_size:
            _fail(label + ": source size changed during read")
        after_fd = _fstat_descriptor(descriptor, label)
        if _identity_tuple(after_fd) != _identity_tuple(before_fd):
            _fail(label + ": descriptor changed during read")
        completed = True
    finally:
        _close_descriptor_transaction(
            descriptor,
            label,
            suppress_errors=not completed,
        )
    try:
        after_path = _os.lstat(path)
    except OSError as error:
        raise ProtocolError(label + ": post-read lstat failed") from error
    if _identity_tuple(after_path) != _identity_tuple(before_path):
        _fail(label + ": path changed during read")
    return raw


def build_implementation_manifest(repository_root):
    root = _os.path.abspath(_os.fspath(repository_root))
    try:
        metadata = _os.lstat(root)
    except OSError as error:
        raise ProtocolError("implementation repository lstat failed") from error
    if not _stat.S_ISDIR(metadata.st_mode):
        _fail("implementation repository is not a directory")
    status = _run_git(
        root,
        ["status", "--porcelain=v1", "--untracked-files=all"],
    )
    if status != b"":
        _fail("implementation repository is not clean")

    entries = []
    for relative in IMPLEMENTATION_PATHS:
        path = _os.path.join(root, *relative.split("/"))
        raw = _read_dynamic_regular_file(
            path,
            "implementation source " + relative,
        )
        committed = _run_git(root, ["show", "HEAD:" + relative])
        if committed != raw:
            _fail("implementation source does not match its Git blob")
        entries.append(
            {
                "bytes": len(raw),
                "path": relative,
                "sha256": _hashlib.sha256(raw).hexdigest(),
            }
        )
    return {
        "entries": entries,
        "sha256": implementation_manifest_sha256(entries),
    }


def require_zero_bytecode(roots):
    if type(roots) not in (list, tuple) or not roots:
        _fail("bytecode roots must be a nonempty exact sequence")
    for root_value in roots:
        try:
            root = _os.path.abspath(_os.fspath(root_value))
        except Exception as error:
            raise ProtocolError("bytecode root is not path-like") from error
        try:
            metadata = _os.lstat(root)
        except OSError as error:
            raise ProtocolError("bytecode root lstat failed") from error
        if not _stat.S_ISDIR(metadata.st_mode):
            _fail("bytecode root is not a directory")

        def reject_walk_error(error):
            raise ProtocolError("bytecode traversal failed") from error

        try:
            for directory, directory_names, file_names in _os.walk(
                root,
                topdown=True,
                onerror=reject_walk_error,
                followlinks=False,
            ):
                if "__pycache__" in directory_names:
                    _fail("bytecode cache directory is forbidden")
                for name in file_names:
                    if name.endswith((".pyc", ".pyo")):
                        _fail("Python bytecode file is forbidden")
        except ProtocolError:
            raise
        except OSError as error:
            raise ProtocolError("bytecode traversal failed") from error


def _validate_audit_roots(roots):
    if type(roots) is not dict or not roots:
        _fail("audit roots must be a nonempty exact map")
    validated = []
    seen_tokens = set()
    for physical, token in roots.items():
        if type(physical) is not str or not _os.path.isabs(physical):
            _fail("audit physical root must be an absolute string")
        if physical != _os.path.normpath(physical) or "//" in physical:
            _fail("audit physical root is not canonical")
        if _os.path.realpath(physical) != physical:
            _fail("audit physical root is not its canonical real path")
        if token not in {
            "<artifact>",
            "<bloodbowl-source>",
            "<prepared-puffer-root>",
            "<private-runtime-scratch>",
            "<prepared-python-prefix>",
        }:
            _fail("audit root token is not in the frozen root domain")
        if token in seen_tokens:
            _fail("audit root token is not a unique root token")
        seen_tokens.add(token)
        validated.append((physical, token))
    return sorted(validated, key=lambda item: len(item[0]), reverse=True)


def _normalize_open_attempt_with_roots(path, mode, flags, validated_roots):
    if type(path) is not str or not _os.path.isabs(path):
        _fail("audited open path must be an absolute exact string")
    _require_ascii(path, "audited open path", printable=True, nonempty=True)
    if (
        path != _os.path.normpath(path)
        or "//" in path
        or any(component in (".", "..") for component in path.split("/"))
    ):
        _fail("audited open path is not canonical")
    if type(flags) is not int:
        _fail("audited open flags must be an exact integer")
    if mode is not None and (
        type(mode) is not str or mode not in ("r", "rb")
    ):
        _fail("audited open mode is not read-only")
    access_mask = getattr(_os, "O_ACCMODE", 3)
    if flags & access_mask != _os.O_RDONLY:
        _fail("audited open flags are not read-only")
    forbidden_flags = (
        getattr(_os, "O_CREAT", 0)
        | getattr(_os, "O_TRUNC", 0)
        | getattr(_os, "O_APPEND", 0)
        | getattr(_os, "O_EXCL", 0)
    )
    if flags & forbidden_flags:
        _fail("audited open flags request mutation")
    if path == "/proc/self/maps":
        return "<absent-linux-proc-self-maps>"
    if _os.path.realpath(path) != path:
        _fail("audited open path is not a canonical physical path")
    for physical, token in validated_roots:
        if path == physical:
            return token
        if path.startswith(physical + _os.sep):
            suffix = path[len(physical) + 1 :]
            normalized = token + "/" + suffix
            _validate_normalized_open_token(normalized)
            return normalized
    _fail("audited open path is outside every authenticated root")


def normalize_open_attempt(path, mode, flags, roots):
    return _normalize_open_attempt_with_roots(
        path,
        mode,
        flags,
        _validate_audit_roots(roots),
    )


class PythonAuditRecorder:
    """Fail-closed recorder for the post-bootstrap Python audit boundary."""

    def __init__(self, *, roots, allowed_paths):
        if type(roots) is not dict:
            _fail("audit roots must be an exact map")
        self._roots = dict(roots)
        self._validated_roots = _validate_audit_roots(self._roots)
        if type(allowed_paths) is not set:
            _fail("audit allowlist must be an exact set")
        for token in allowed_paths:
            _validate_normalized_open_token(token)
        self._allowed_paths = frozenset(allowed_paths)
        self._opened_paths = set()
        self._opened_path_wire_total = 0
        self._sealed = False

    def hook(self, event, arguments):
        if type(event) is not str or type(arguments) is not tuple:
            _fail("Python audit event shape is invalid")
        if self._sealed:
            _fail("Python audit recorder is sealed")
        if event == "open":
            if len(arguments) != 3:
                _fail("Python open audit event must have exactly three items")
            token = _normalize_open_attempt_with_roots(
                arguments[0],
                arguments[1],
                arguments[2],
                self._validated_roots,
            )
            if token not in self._allowed_paths:
                _fail("Python open attempt is outside the exact allowlist")
            if token in self._opened_paths:
                return
            if len(self._opened_paths) >= 65535:
                _fail("Python open attempts exceed the item cap")
            quoted = _json.dumps(
                token,
                allow_nan=False,
                ensure_ascii=True,
                separators=(",", ":"),
            ).encode("ascii")
            prospective_total = (
                self._opened_path_wire_total + len(quoted) + 1
            )
            prospective_size = 2 + prospective_total
            if prospective_size > _AUDIT_CANONICAL_ARRAY_MAX_BYTES:
                _fail("Python open attempts exceed the canonical byte cap")
            self._opened_paths.add(token)
            self._opened_path_wire_total = prospective_total
            return
        if event.startswith("socket."):
            _fail("Python network attempt is forbidden")
        if event in {
            "subprocess.Popen",
            "os.system",
            "os.posix_spawn",
            "pty.spawn",
        }:
            _fail("Python process creation is forbidden")
        if event in {"os.chdir", "os.fchdir"}:
            _fail("Python current-directory mutation is forbidden")

    def receipt(self):
        paths = sorted(self._opened_paths)
        return {
            "network_attempts": 0,
            "opened_paths": paths,
            "opened_paths_sha256": opened_paths_sha256(paths),
        }

    def seal(self):
        self._sealed = True


def validate_public_component(value, *, name_max):
    """Validate one closed, printable-ASCII public namespace component."""

    if not _is_exact_int(name_max) or name_max <= 0:
        _fail("public component NAME_MAX must be a positive exact integer")
    if type(value) is not str:
        _fail("public component must be an exact string")
    try:
        encoded = value.encode("ascii")
    except UnicodeEncodeError:
        _fail("public component must be ASCII")
    if not encoded or len(encoded) > name_max:
        _fail("public component length is outside the closed bound")
    if value in (".", ".."):
        _fail("dot path components are forbidden")
    if b"/" in encoded or b"\\" in encoded:
        _fail("public component contains a path separator")
    if any(byte < 0x20 or byte > 0x7E for byte in encoded):
        _fail("public component must contain only printable ASCII")
    return value


def _validate_publication_fd(fd, label):
    if not _is_exact_int(fd) or fd < 0:
        _fail(label + " must be a nonnegative exact file descriptor")
    return fd


def exclusive_rename_new(
    libc,
    source_fd,
    source_name,
    destination_fd,
    destination_name,
):
    """Use Darwin renameatx_np(RENAME_EXCL) without an overwrite fallback."""

    _validate_publication_fd(source_fd, "source directory descriptor")
    _validate_publication_fd(
        destination_fd,
        "destination directory descriptor",
    )
    validate_public_component(source_name, name_max=_DARWIN_NAME_MAX)
    validate_public_component(destination_name, name_max=_DARWIN_NAME_MAX)
    try:
        function = libc.renameatx_np
        function.argtypes = [
            _ctypes.c_int,
            _ctypes.c_char_p,
            _ctypes.c_int,
            _ctypes.c_char_p,
            _ctypes.c_uint,
        ]
        function.restype = _ctypes.c_int
    except Exception as error:
        raise ProtocolError(
            "Darwin renameatx_np is unavailable or has an unusable ABI"
        ) from error

    _ctypes.set_errno(0)
    try:
        result = function(
            source_fd,
            source_name.encode("ascii"),
            destination_fd,
            destination_name.encode("ascii"),
            RENAME_EXCL,
        )
    except Exception as error:
        raise ProtocolError("Darwin renameatx_np call failed") from error
    if type(result) is int and result == 0:
        return None
    saved_errno = _ctypes.get_errno()
    if type(result) is int and result == -1 and saved_errno == _errno.EEXIST:
        raise FileExistsError(
            saved_errno,
            "exclusive publication destination already exists",
            destination_name,
        )
    _fail(
        "Darwin renameatx_np returned an untrusted result/errno pair "
        "(result=%r, errno=%r)" % (result, saved_errno)
    )


def require_no_extended_acl(libc, fd):
    """Accept only Darwin's exact no-extended-ACL result."""

    _validate_publication_fd(fd, "ACL descriptor")
    try:
        get_acl = libc.acl_get_fd_np
        free_acl = libc.acl_free
        get_acl.argtypes = [_ctypes.c_int, _ctypes.c_int]
        get_acl.restype = _ctypes.c_void_p
        free_acl.argtypes = [_ctypes.c_void_p]
        free_acl.restype = _ctypes.c_int
    except Exception as error:
        raise ProtocolError(
            "Darwin extended-ACL functions are unavailable or unusable"
        ) from error

    _ctypes.set_errno(0)
    try:
        acl_pointer = get_acl(fd, ACL_TYPE_EXTENDED)
    except Exception as error:
        raise ProtocolError("Darwin extended-ACL query failed") from error
    saved_errno = _ctypes.get_errno()
    pointer_is_null = (
        acl_pointer is None
        or (type(acl_pointer) is int and acl_pointer == 0)
    )
    if pointer_is_null:
        if saved_errno == _errno.ENOENT:
            return None
        _fail(
            "Darwin extended-ACL query returned an ambiguous absence "
            "(errno=%r)" % (saved_errno,)
        )
    if type(acl_pointer) is not int or acl_pointer < 0:
        _fail("Darwin extended-ACL query returned a malformed pointer")

    try:
        free_result = free_acl(acl_pointer)
    except Exception as error:
        raise ProtocolError(
            "extended ACL was present and acl_free failed"
        ) from error
    if type(free_result) is not int or free_result != 0:
        _fail("extended ACL was present and acl_free rejected the object")
    _fail("extended ACL is forbidden")


def _validate_publication_record_shape(
    record,
    expected_schema,
    expected_fields,
    record_kind,
):
    _require_ascii(
        expected_schema,
        "expected publication schema",
        printable=True,
        nonempty=True,
    )
    if type(expected_fields) is not tuple or not expected_fields:
        _fail("expected publication fields must be a nonempty exact tuple")
    for field in expected_fields:
        _require_ascii(
            field,
            "expected publication field",
            printable=True,
            nonempty=True,
        )
    if (
        tuple(sorted(expected_fields)) != expected_fields
        or len(set(expected_fields)) != len(expected_fields)
    ):
        _fail("expected publication fields are not sorted and unique")
    if type(record) is not dict:
        _fail(record_kind + " publication record must be an exact object")
    for field in record:
        _require_ascii(
            field,
            record_kind + " publication field",
            printable=True,
            nonempty=True,
        )
    if tuple(sorted(record)) != expected_fields:
        _fail(record_kind + " publication record fields are not closed")
    if record.get("schema") != expected_schema:
        _fail(record_kind + " publication record schema mismatch")
    if record_kind == "handoff":
        if record.get("status") != "prospective":
            _fail("handoff publication status must be prospective")
    elif record_kind == "result":
        if (
            record.get("publication_status")
            not in _PUBLICATION_RESULT_STATUSES
        ):
            _fail("result publication status is outside the closed enum")
    else:
        _fail("unknown publication record kind")
    return record


def _publication_canonical_bytes(
    record,
    expected_schema,
    expected_fields,
    record_kind,
):
    _validate_publication_record_shape(
        record,
        expected_schema,
        expected_fields,
        record_kind,
    )
    raw = canonical_json_bytes(record)
    if not 1 <= len(raw) <= _PUBLICATION_MAX_FRAME_BYTES:
        _fail(record_kind + " publication record exceeds the byte bound")
    return raw


def encode_handoff_frame(record):
    canonical = canonical_json_bytes(record)
    if not 1 <= len(canonical) <= _PUBLICATION_MAX_FRAME_BYTES:
        _fail("handoff frame body length is outside the closed bound")
    return _struct.pack(">I", len(canonical)) + canonical


def _is_finite_publication_number(value):
    if type(value) not in (int, float) or type(value) is bool:
        return False
    try:
        return _math.isfinite(value)
    except (TypeError, ValueError, OverflowError):
        return False


def _remaining_publication_deadline(deadline, monotonic):
    if not _is_finite_publication_number(deadline):
        _fail("publication deadline must be a finite exact number")
    if not callable(monotonic):
        _fail("publication monotonic clock must be callable")
    try:
        now = monotonic()
    except Exception as error:
        raise ProtocolError("publication monotonic clock failed") from error
    if not _is_finite_publication_number(now):
        _fail("publication monotonic clock returned a non-finite number")
    remaining = deadline - now
    if remaining <= 0:
        _fail("publication channel deadline expired")
    return remaining


def _read_publication_chunk(
    read_fd,
    maximum,
    *,
    deadline,
    monotonic,
    wait_readable,
):
    if not _is_exact_int(maximum) or maximum <= 0:
        _fail("publication read width must be a positive exact integer")
    remaining = _remaining_publication_deadline(deadline, monotonic)
    if not callable(wait_readable):
        _fail("publication readiness waiter must be callable")
    try:
        ready = wait_readable(read_fd, remaining)
    except Exception as error:
        raise ProtocolError("publication readiness wait failed") from error
    if not ready:
        _fail("publication channel did not become readable before deadline")
    try:
        return _os.read(read_fd, maximum)
    except OSError as error:
        raise ProtocolError("publication channel read failed") from error


def _read_publication_exact(
    read_fd,
    size,
    *,
    deadline,
    monotonic,
    wait_readable,
):
    chunks = []
    remaining_size = size
    while remaining_size:
        chunk = _read_publication_chunk(
            read_fd,
            remaining_size,
            deadline=deadline,
            monotonic=monotonic,
            wait_readable=wait_readable,
        )
        if not chunk:
            _fail("publication channel reached EOF before the record ended")
        chunks.append(chunk)
        remaining_size -= len(chunk)
    return b"".join(chunks)


def _require_publication_eof(
    read_fd,
    *,
    deadline,
    monotonic,
    wait_readable,
):
    trailing = _read_publication_chunk(
        read_fd,
        1,
        deadline=deadline,
        monotonic=monotonic,
        wait_readable=wait_readable,
    )
    if trailing != b"":
        _fail("publication channel contains a second record or trailing byte")


def read_handoff_channel(
    read_fd,
    *,
    deadline,
    expected_schema,
    expected_fields,
    monotonic,
    wait_readable,
):
    _validate_publication_fd(read_fd, "handoff read descriptor")
    header = _read_publication_exact(
        read_fd,
        4,
        deadline=deadline,
        monotonic=monotonic,
        wait_readable=wait_readable,
    )
    body_size = _struct.unpack(">I", header)[0]
    if not 1 <= body_size <= _PUBLICATION_MAX_FRAME_BYTES:
        _fail("handoff frame declares an invalid body length")
    body = _read_publication_exact(
        read_fd,
        body_size,
        deadline=deadline,
        monotonic=monotonic,
        wait_readable=wait_readable,
    )
    _require_publication_eof(
        read_fd,
        deadline=deadline,
        monotonic=monotonic,
        wait_readable=wait_readable,
    )
    record = _parse_canonical_json(body, "handoff publication record")
    _validate_publication_record_shape(
        record,
        expected_schema,
        expected_fields,
        "handoff",
    )
    return record, body


def publication_ack(canonical_record_bytes):
    if type(canonical_record_bytes) is not bytes:
        _fail("publication ACK preimage must be exact bytes")
    if not 1 <= len(canonical_record_bytes) <= _PUBLICATION_MAX_FRAME_BYTES:
        _fail("publication ACK preimage length is outside the closed bound")
    record = _parse_canonical_json(
        canonical_record_bytes,
        "publication ACK preimage",
    )
    if type(record) is not dict:
        _fail("publication ACK preimage must encode an exact object")
    digest = _hashlib.sha256(canonical_record_bytes).hexdigest()
    return _PUBLICATION_ACK_PREFIX + digest.encode("ascii") + b"\n"


def read_publication_ack_channel(
    read_fd,
    *,
    deadline,
    canonical_record_bytes,
    monotonic,
    wait_readable,
):
    _validate_publication_fd(read_fd, "publication ACK read descriptor")
    expected = publication_ack(canonical_record_bytes)
    observed = _read_publication_exact(
        read_fd,
        len(expected),
        deadline=deadline,
        monotonic=monotonic,
        wait_readable=wait_readable,
    )
    _require_publication_eof(
        read_fd,
        deadline=deadline,
        monotonic=monotonic,
        wait_readable=wait_readable,
    )
    if observed != expected:
        _fail("publication ACK bytes do not match the bound handoff")
    return None


def _close_publication_writer(write_fd):
    try:
        _os.close(write_fd)
    except OSError as error:
        raise ProtocolError("publication result writer close failed") from error


def write_publication_result_channel(
    write_fd,
    *,
    result,
    expected_schema,
    expected_fields,
):
    _validate_publication_fd(write_fd, "publication result write descriptor")
    canonical = _publication_canonical_bytes(
        result,
        expected_schema,
        expected_fields,
        "result",
    )
    offset = 0
    try:
        while offset < len(canonical):
            written = _os.write(write_fd, canonical[offset:])
            if not _is_exact_int(written) or written <= 0:
                _fail("publication result write made no progress")
            offset += written
    except OSError as error:
        try:
            _os.close(write_fd)
        except OSError:
            pass
        raise ProtocolError("publication result write failed") from error
    except BaseException:
        try:
            _os.close(write_fd)
        except OSError:
            pass
        raise
    _close_publication_writer(write_fd)
    return canonical


def read_publication_result_channel(
    read_fd,
    *,
    deadline,
    expected_schema,
    expected_fields,
    monotonic,
    wait_readable,
):
    _validate_publication_fd(read_fd, "publication result read descriptor")
    chunks = []
    observed_size = 0
    while True:
        chunk = _read_publication_chunk(
            read_fd,
            _PUBLICATION_MAX_FRAME_BYTES + 1 - observed_size,
            deadline=deadline,
            monotonic=monotonic,
            wait_readable=wait_readable,
        )
        if not chunk:
            break
        chunks.append(chunk)
        observed_size += len(chunk)
        if observed_size > _PUBLICATION_MAX_FRAME_BYTES:
            _fail("publication result exceeds the byte bound")
    if observed_size == 0:
        _fail("publication result channel is empty")
    raw = b"".join(chunks)
    record = _parse_canonical_json(raw, "publication result record")
    _validate_publication_record_shape(
        record,
        expected_schema,
        expected_fields,
        "result",
    )
    return record


def _publish_leaf_transaction(operations):
    operations.create_temporary_new()
    operations.fchmod_temporary_0600()
    operations.require_temporary_no_acl()
    operations.write_all()
    operations.flush_temporary()
    operations.fsync_temporary_file()
    operations.validate_parent_path_before()
    operations.require_destination_absent_nofollow()
    operations.validate_source_name_identity()
    operations.rename_exclusive()
    operations.validate_parent_path_after()
    operations.reopen_destination_nofollow()
    operations.validate_destination_identity()
    operations.require_destination_no_acl()
    operations.fsync_containing_directory()


def publish_payload_leaf(
    operations,
    *,
    relative_path,
    payload,
    semantic_sha256,
):
    operations.validate_payload_semantics(
        relative_path,
        payload,
        semantic_sha256,
    )
    _publish_leaf_transaction(operations)


def publish_checkpoint_leaf(
    operations,
    *,
    update,
    raw_checkpoint,
    tensor_sha256,
):
    operations.validate_checkpoint_semantics(
        update,
        raw_checkpoint,
        tensor_sha256,
    )
    _publish_leaf_transaction(operations)


_TRACE_UPDATE_COUNT = 2956
_TRACE_MAX_BYTES = 16777216
_TRACE_ROWS_PER_UPDATE = 32768
_TRACE_EPISODES_PER_UPDATE = 2048
_TRACE_CHECKPOINT_EPOCHS = frozenset((512, 1024, 1536, 2048, 2956))
_RESULT_CHECKPOINT_UPDATES = (0, 512, 1024, 1536, 2048, 2956)
_RESULT_ACTION_SEEDS = (
    2363161776,
    2079938504,
    2486426431,
    1428436532,
    3852947533,
    1935602315,
    2884042901,
    2683991200,
)


def _authenticated_manifest_registry(manifest):
    if type(manifest) is not dict:
        _fail("supplied protocol manifest must be an exact object")
    raw = canonical_json_bytes(manifest)
    if (
        len(raw) != _PROTOCOL_BYTES
        or _hashlib.sha256(raw).hexdigest() != _PROTOCOL_SHA256
    ):
        _fail("supplied protocol manifest identity mismatch")
    try:
        registry = manifest["artifact"]["schemas"]
    except (KeyError, TypeError) as error:
        raise ProtocolError(
            "authenticated protocol manifest has no schema registry"
        ) from error
    validate_schema_registry(registry)
    return registry


def _binary32(value):
    try:
        return _struct.unpack("<f", _struct.pack("<f", value))[0]
    except (OverflowError, _struct.error) as error:
        raise ProtocolError("binary32 schedule conversion failed") from error


def _expected_schedule(update_index):
    progress = update_index / _TRACE_UPDATE_COUNT

    entropy_base = 0.02
    entropy_floor = entropy_base * 0.1
    entropy = entropy_floor + 0.5 * (
        entropy_base - entropy_floor
    ) * (1.0 + _math.cos(_math.pi * progress))
    entropy = _binary32(entropy)

    if update_index == 0:
        learning_rate = 0.0006
    else:
        learning_rate_base = 0.0006
        learning_rate_floor = learning_rate_base * 0.1
        learning_rate = learning_rate_floor + 0.5 * (
            learning_rate_base - learning_rate_floor
        ) * (1.0 + _math.cos(_math.pi * progress))
    return entropy, learning_rate


def _validate_trace_rows(rows, registry):
    if type(rows) is not list:
        _fail("training trace rows must be an exact list")
    if len(rows) != _TRACE_UPDATE_COUNT:
        _fail("training trace row count mismatch")
    row_schema = registry["roots"]["training-trace.jsonl"]

    for index, row in enumerate(rows):
        _validate_schema_value(
            row,
            row_schema,
            registry,
            "$trace[%d]" % (index,),
        )

    cumulative_events = 0
    cumulative_successes = 0
    first_event_update = None
    previous_parameter_sha256 = None
    for index, row in enumerate(rows):
        committed_epoch = index + 1
        if row["update_index"] != index:
            _fail("training trace update index sequence mismatch")
        if row["committed_epoch"] != committed_epoch:
            _fail("training trace committed epoch sequence mismatch")
        if row["global_agent_step"] != (
            committed_epoch * _TRACE_ROWS_PER_UPDATE
        ):
            _fail("training trace global agent-step equation mismatch")
        if row["episodes"]["this_update"] != _TRACE_EPISODES_PER_UPDATE:
            _fail("training trace per-update episode count mismatch")
        if row["episodes"]["cumulative"] != (
            committed_epoch * _TRACE_EPISODES_PER_UPDATE
        ):
            _fail("training trace cumulative episode equation mismatch")

        parameters = row["parameters"]
        parameter_sha256 = parameters["canonical_sha256"]
        if (
            not _is_lower_hex(parameter_sha256, 64)
            or parameter_sha256 == "0" * 64
        ):
            _fail("training trace parameter digest is a forbidden sentinel")
        if parameters["checkpoint_update"] is not (
            committed_epoch in _TRACE_CHECKPOINT_EPOCHS
        ):
            _fail("training trace checkpoint epoch schedule mismatch")

        objective = row["objective"]
        events = objective["events"]
        successes = objective["successful_episodes"]
        if successes > _TRACE_EPISODES_PER_UPDATE:
            _fail("training trace successful episodes exceed the rollout")
        if successes > 0 and events == 0:
            _fail("training trace success has no objective event")
        cumulative_events += events
        cumulative_successes += successes
        if objective["cumulative_events"] != cumulative_events:
            _fail("training trace cumulative objective events mismatch")
        if (
            objective["cumulative_successful_episodes"]
            != cumulative_successes
        ):
            _fail("training trace cumulative successful episodes mismatch")

        first_event_here = events > 0 and first_event_update is None
        if first_event_here:
            first_event_update = index
        if objective["first_update"] != first_event_update:
            _fail("training trace first objective update mismatch")
        if first_event_here:
            if index == 0:
                expected_pre_objective = EXPECTED_INITIAL_PARAMETER_SHA256
            else:
                expected_pre_objective = previous_parameter_sha256
        else:
            expected_pre_objective = None
        if (
            parameters["pre_objective_sha256"]
            != expected_pre_objective
        ):
            _fail("training trace pre-objective parameter binding mismatch")

        try:
            event_float = float(events)
        except (OverflowError, ValueError) as error:
            raise ProtocolError(
                "training trace objective event count cannot bind to float"
            ) from error
        integrity = row["rollout"]["integrity"]
        if not _strict_equal(
            integrity["reward_components"]["touchdown"],
            event_float,
        ):
            _fail("training trace touchdown/event reconciliation mismatch")
        if not _strict_equal(
            integrity["reward_postclip_return"],
            event_float,
        ):
            _fail("training trace postclip/event reconciliation mismatch")

        expected_entropy, expected_learning_rate = _expected_schedule(index)
        if not _strict_equal(
            row["schedule"]["entropy_coefficient"],
            expected_entropy,
        ):
            _fail("training trace entropy schedule mismatch")
        if not _strict_equal(
            row["schedule"]["learning_rate"],
            expected_learning_rate,
        ):
            _fail("training trace learning-rate schedule mismatch")
        previous_parameter_sha256 = parameter_sha256
    return rows


def validate_training_trace(raw, manifest):
    registry = _authenticated_manifest_registry(manifest)
    if type(raw) is not bytes:
        _fail("training trace must be exact bytes")
    if not raw or len(raw) > _TRACE_MAX_BYTES:
        _fail("training trace byte length is outside the closed bound")
    if raw[-1:] != b"\n":
        _fail("training trace must end in exactly one row LF")
    if raw.count(b"\n") != _TRACE_UPDATE_COUNT:
        _fail("training trace LF/row count mismatch")
    encoded_rows = raw.split(b"\n")
    if (
        len(encoded_rows) != _TRACE_UPDATE_COUNT + 1
        or encoded_rows[-1] != b""
    ):
        _fail("training trace framing is malformed")
    rows = []
    for index, encoded_row in enumerate(encoded_rows[:-1]):
        if not encoded_row:
            _fail("training trace contains a blank row")
        row = _parse_canonical_json(
            encoded_row + b"\n",
            "training trace row %d" % (index,),
        )
        rows.append(row)
    return _validate_trace_rows(rows, registry)


def _expected_result_bitset_paths():
    paths = []
    for update in _RESULT_CHECKPOINT_UPDATES:
        for seed_index in range(8):
            paths.append(
                "evaluation/update-%06d/seed-%02d.bits"
                % (update, seed_index)
            )
    for seed_index in range(8):
        paths.append(
            "evaluation/update-000000-repeat/seed-%02d.bits"
            % (seed_index,)
        )
    return frozenset(paths)


def _validate_result_seed(
    record,
    raw,
    *,
    update,
    seed_index,
    repeat_flag,
):
    action_seed = _RESULT_ACTION_SEEDS[seed_index]
    if record["seed_index"] != seed_index:
        _fail("evaluation seed index sequence mismatch")
    if record["action_seed"] != action_seed:
        _fail("evaluation action seed mismatch")
    if repeat_flag:
        expected_path = (
            "evaluation/update-000000-repeat/seed-%02d.bits"
            % (seed_index,)
        )
    else:
        expected_path = (
            "evaluation/update-%06d/seed-%02d.bits"
            % (update, seed_index)
        )
    if record["bitset_path"] != expected_path:
        _fail("evaluation bitset path mismatch")
    if type(raw) is not bytes or len(raw) != 4096:
        _fail("evaluation bitset has the wrong byte width")
    raw_sha256 = _hashlib.sha256(raw).hexdigest()
    if record["bitset_sha256"] != raw_sha256:
        _fail("evaluation bitset raw digest mismatch")
    semantic_sha256 = success_bitset_sha256(
        checkpoint_update=update,
        seed_index=seed_index,
        action_seed=action_seed,
        episode_count=32768,
        repeat_flag=repeat_flag,
        raw=raw,
    )
    if record["bitset_semantic_sha256"] != semantic_sha256:
        _fail("evaluation bitset semantic digest mismatch")
    bits = unpack_success_bits(raw, count=32768)
    successes = sum(bits)
    if record["successes"] != successes:
        _fail("evaluation bitset popcount mismatch")
    expected_wilson = wilson95(successes, 32768)
    if not _exact_json_equal(record["wilson95"], expected_wilson):
        _fail("evaluation seed Wilson interval mismatch")
    return bits, successes


def validate_results(results, manifest, *, trace_rows, bitsets):
    registry = _authenticated_manifest_registry(manifest)
    if type(results) is not dict:
        _fail("results must be an exact object")
    if type(trace_rows) is not list:
        _fail("results trace binding must be an exact list")
    if type(bitsets) is not dict:
        _fail("results bitsets must be an exact map")

    _validate_schema_value(
        results,
        registry["roots"]["results.json"],
        registry,
        "$results",
    )
    _validate_trace_rows(trace_rows, registry)

    for path, raw in bitsets.items():
        if type(path) is not str:
            _fail("results bitset map key must be an exact string")
        if type(raw) is not bytes:
            _fail("results bitset map value must be exact bytes")
    expected_paths = _expected_result_bitset_paths()
    if frozenset(bitsets) != expected_paths:
        _fail("results bitset path topology mismatch")

    if results["protocol_sha256"] != _PROTOCOL_SHA256:
        _fail("results protocol digest mismatch")

    primary_bits = {}
    primary_raw = {}
    aggregate_successes = {}
    evaluations = results["evaluations"]
    for checkpoint_ordinal, update in enumerate(
        _RESULT_CHECKPOINT_UPDATES
    ):
        evaluation = evaluations[checkpoint_ordinal]
        if evaluation["update"] != update:
            _fail("evaluation checkpoint order mismatch")
        seed_total = 0
        for seed_index in range(8):
            record = evaluation["seeds"][seed_index]
            expected_path = (
                "evaluation/update-%06d/seed-%02d.bits"
                % (update, seed_index)
            )
            if record["bitset_path"] != expected_path:
                _fail("evaluation bitset path mismatch")
            raw = bitsets[expected_path]
            bits, successes = _validate_result_seed(
                record,
                raw,
                update=update,
                seed_index=seed_index,
                repeat_flag=0,
            )
            seed_total += successes
            primary_raw[(update, seed_index)] = raw
            if update in (0, 2956):
                primary_bits[(update, seed_index)] = bits
        if evaluation["successes"] != seed_total:
            _fail("evaluation checkpoint success aggregate mismatch")
        expected_wilson = wilson95(seed_total, 262144)
        if not _exact_json_equal(
            evaluation["wilson95"],
            expected_wilson,
        ):
            _fail("evaluation checkpoint Wilson interval mismatch")
        aggregate_successes[update] = seed_total

    repeat = results["checkpoint_zero_repeat"]
    repeat_total = 0
    for seed_index in range(8):
        record = repeat["seeds"][seed_index]
        expected_path = (
            "evaluation/update-000000-repeat/seed-%02d.bits"
            % (seed_index,)
        )
        if record["bitset_path"] != expected_path:
            _fail("evaluation repeat bitset path mismatch")
        raw = bitsets[expected_path]
        _bits, successes = _validate_result_seed(
            record,
            raw,
            update=0,
            seed_index=seed_index,
            repeat_flag=1,
        )
        if raw != primary_raw[(0, seed_index)]:
            _fail("checkpoint-zero repeat bitset differs from primary")
        repeat_total += successes
    if repeat["successes"] != repeat_total:
        _fail("checkpoint-zero repeat success aggregate mismatch")
    if not _exact_json_equal(
        repeat["wilson95"],
        wilson95(repeat_total, 262144),
    ):
        _fail("checkpoint-zero repeat Wilson interval mismatch")
    if repeat["matches_primary"] is not True:
        _fail("checkpoint-zero repeat did not bind to primary bytes")

    initial_bits = []
    final_bits = []
    for seed_index in range(8):
        initial_bits.extend(primary_bits[(0, seed_index)])
        final_bits.extend(primary_bits[(2956, seed_index)])
    paired = paired_success_counts(initial_bits, final_bits)
    if not _exact_json_equal(
        results["paired_final_vs_initial"],
        paired,
    ):
        _fail("paired final-versus-initial counts mismatch")

    final_objective = trace_rows[-1]["objective"]
    training = results["training"]
    if training["objective_events"] != final_objective["cumulative_events"]:
        _fail("results objective-event trace binding mismatch")
    if (
        training["successful_episodes"]
        != final_objective["cumulative_successful_episodes"]
    ):
        _fail("results successful-episode trace binding mismatch")
    if training["first_objective_update"] != final_objective["first_update"]:
        _fail("results first-objective trace binding mismatch")

    learning_outcome = classify_learning_outcome(
        final_objective["cumulative_events"],
        aggregate_successes[0],
        aggregate_successes[2956],
    )
    if results["learning_outcome"] != learning_outcome:
        _fail("results learning outcome classification mismatch")
    return results
