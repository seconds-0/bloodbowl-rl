#!/usr/bin/env python3
"""Freeze the serializer's security-critical source shape before it exists."""

from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import re
import sys


FORBIDDEN_CALLS = (
    "fopen", "freopen", "tmpfile", "open", "openat", "creat", "write",
    "pwrite", "system", "popen", "strlen", "strnlen", "memchr", "strchr",
    "strrchr", "strcspn", "strspn", "strpbrk", "strtok", "strtok_r",
    "strstr", "strcmp", "strncmp",
)

FORBIDDEN_ACTIVE_IDENTIFIERS = FORBIDDEN_CALLS + (
    "asm", "__asm", "__asm__", "__attribute", "__attribute__",
    "__FILE__", "bb_coin", "bb_d3", "bb_d6", "bb_d8", "bb_d16",
)

CONTROL_CALL_SPELLINGS = {
    "if", "for", "while", "switch", "return", "sizeof", "_Alignof",
}

ALLOWED_EXTERNAL_CALLS = {
    "ad_authored_allocation_by_source", "ad_authored_template_key",
    "ad_bbs_write", "ad_build_authored_proof_bundle",
    "ad_f1_pass_opportunity_valid", "ad_f2_handoff_target_count",
    "ad_f4_pending_dodge_reroll_valid", "ad_identify_authored_proof_bundle",
    "ad_recipe_projection_equal", "ad_recipe_projection_from_recipe",
    "bb_action_pack", "bb_apply", "bb_can_score_without_dice",
    "bb_is_marked", "bb_legal_actions", "bb_rng_error", "bb_rng_script",
    "bb_state_bank_dodge_reroll_valid", "calloc", "fclose", "fflush",
    "free", "isfinite", "malloc", "memcmp", "memcpy", "memmove",
    "memset", "open_memstream", "qsort", "realloc", "snprintf",
    "UINT32_C", "UINT64_C",
}

C_LANGUAGE_SUFFIXES = {
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".inc",
    ".def", ".m", ".mm", ".s",
}
SERIALIZER_REFERENCE_PATHS = {
    "tools/authored_sidecar.h",
    "tools/authored_sidecar_authority/abi_probe.c",
    "tools/authored_sidecar_authority/serializer_probe.c",
}
SERIALIZER_OWNERSHIP_FRAGMENTS = (
    "ad_serialize", "serialize_authored", "authored_sidecar", "sidecars",
)

ALLOWED_INCLUDES = {
    "authored_sidecar.h",
    "bb/bb_reachability.h",
    "bb/gen_skills.h",
    "bb/gen_teams.h",
    "errno.h",
    "inttypes.h",
    "limits.h",
    "stdbool.h",
    "stddef.h",
    "stdint.h",
    "stdio.h",
    "stdlib.h",
    "string.h",
}

SYSTEM_INCLUDES = {
    "errno.h", "inttypes.h", "limits.h", "stdbool.h", "stddef.h",
    "stdint.h", "stdio.h", "stdlib.h", "string.h",
}

PROTECTED_DEFINITIONS = (
    "ad_sidecar_sha256", "ad_sidecar_hash_actions",
    "ad_sidecar_hash_dice", "ad_sidecar_hash_legal",
    "ad_sidecar_alias_contract", "ad_sidecar_reconcile_bundle",
    "ad_sidecar_find_legal", "ad_sidecar_f5_end_activation_legal",
    "ad_sidecar_build_rows", "ad_sidecar_stage_pair",
    "ad_serialize_authored_sidecars",
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def lexical_view(text: str, *, keep_literals: bool) -> str:
    """Remove C comments without treating comment markers in literals as code.

    The returned string has exactly the same length and line layout as the
    input.  When ``keep_literals`` is false, string and character literal
    contents are masked as well, leaving only compiler-token spelling for
    identifier and call checks.
    """
    output = list(text)
    index = 0
    state = "code"
    escaped = False
    while index < len(text):
        char = text[index]
        following = text[index + 1] if index + 1 < len(text) else ""
        if state == "code":
            if char == "/" and following == "*":
                output[index] = output[index + 1] = " "
                state = "block-comment"
                index += 2
                continue
            if char == "/" and following == "/":
                output[index] = output[index + 1] = " "
                state = "line-comment"
                index += 2
                continue
            if char in ('"', "'"):
                state = "string" if char == '"' else "character"
                escaped = False
                if not keep_literals:
                    output[index] = " "
            index += 1
            continue
        if state == "block-comment":
            if char == "*" and following == "/":
                output[index] = output[index + 1] = " "
                state = "code"
                index += 2
                continue
            if char != "\n":
                output[index] = " "
            index += 1
            continue
        if state == "line-comment":
            if char == "\n":
                state = "code"
            else:
                output[index] = " "
            index += 1
            continue
        if not keep_literals and char != "\n":
            output[index] = " "
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif (state == "string" and char == '"') or (
                state == "character" and char == "'"):
            state = "code"
        index += 1
    require(state not in ("block-comment", "string", "character"),
            "unterminated comment or literal in production source")
    return "".join(output)


def strip_comments(text: str) -> str:
    return lexical_view(text, keep_literals=True)


def code_tokens(text: str) -> str:
    return lexical_view(text, keep_literals=False)


def function_definition_pattern(name: str) -> str:
    return (
        rf"^[ \t]*(?:(?:static|inline)[ \t]+)*(?:int|void)[ \t]+"
        rf"{re.escape(name)}[ \t]*\([^;{{}}]*?\)[ \t]*\{{"
    )


def function_body_bounds(text: str, name: str) -> tuple[int, int]:
    match = re.search(function_definition_pattern(name), text,
                      flags=re.M | re.S)
    require(match is not None, f"missing function definition: {name}")
    start = text.find("{", match.start())
    depth = 0
    quote: str | None = None
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if quote is not None:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in ('"', "'"):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return start + 1, index
    raise RuntimeError(f"unterminated function definition: {name}")


def function_body(text: str, name: str) -> str:
    start, end = function_body_bounds(text, name)
    return text[start:end]


def call_count(text: str, name: str) -> int:
    return len(re.findall(rf"\b{re.escape(name)}\s*\(", code_tokens(text)))


def identifier_count(text: str, name: str) -> int:
    return len(re.findall(rf"\b{re.escape(name)}\b", code_tokens(text)))


def defined_function_names(text: str) -> set[str]:
    code = code_tokens(text)
    names = set(re.findall(
        r"^[ \t]*(?:[A-Za-z_]\w*[ \t\n*]+)+([A-Za-z_]\w*)\s*"
        r"\([^;{}]*\)\s*\{", code, flags=re.M | re.S))
    return names - CONTROL_CALL_SPELLINGS


def require_closed_call_vocabulary(text: str) -> None:
    code = code_tokens(text)
    definitions = defined_function_names(code)
    calls = set(re.findall(r"\b([A-Za-z_]\w*)\s*\(", code))
    unknown = sorted(calls - definitions - ALLOWED_EXTERNAL_CALLS -
                     CONTROL_CALL_SPELLINGS)
    require(not unknown,
            f"production source call vocabulary is not closed: {unknown}")


def checked_call_position(text: str, name: str) -> int:
    match = re.search(
        rf"\bif\s*\(\s*{re.escape(name)}\s*\([^;]*?\)\s*!=\s*0\s*\)",
        code_tokens(text), flags=re.S)
    require(match is not None, f"required checked call is absent: {name}")
    return match.start()


def require_derived_result(body: str, helper: str) -> None:
    """Require a named result to flow beyond its helper-call statement."""
    code = code_tokens(body)
    match = re.search(
        rf"\b([A-Za-z_]\w*)\s*=\s*{re.escape(helper)}\s*\([^;]*\)\s*;",
        code, flags=re.S)
    require(match is not None,
            f"typed row builder ignores result from {helper}")
    variable = match.group(1)
    require(identifier_count(code[match.end():], variable) >= 1,
            f"typed row builder ignores result from {helper}")


def first_call_bounds(text: str, name: str) -> tuple[str, int, int]:
    """Return the lexical code and balanced argument bounds for a call."""
    code = code_tokens(text)
    match = re.search(rf"\b{re.escape(name)}\s*\(", code)
    require(match is not None, f"required call is absent: {name}")
    start = code.find("(", match.start())
    depth = 0
    for index in range(start, len(code)):
        if code[index] == "(":
            depth += 1
        elif code[index] == ")":
            depth -= 1
            if depth == 0:
                return code, start + 1, index
    raise RuntimeError(f"unterminated call expression: {name}")


def first_call_arguments(text: str, name: str) -> str:
    code, start, end = first_call_bounds(text, name)
    return code[start:end]


def require_row_derivation_flow(text: str, *, active: bool) -> None:
    rows = function_body(text, "ad_sidecar_build_rows")
    code = code_tokens(rows)
    prefix = "active " if active else ""
    require(call_count(rows, "bb_legal_actions") == 1,
            f"{prefix}row builder legal enumeration count differs")
    legal_assignment = re.search(
        r"\bint\s+legal_count\s*=\s*bb_legal_actions\s*\(\s*match\s*,"
        r"\s*legal_actions\s*\)\s*;", code, flags=re.S)
    require(legal_assignment is not None,
            f"{prefix}row legal enumeration is not bound to its match/buffer")
    legal_position = legal_assignment.start()
    for helper in (
        "ad_f1_pass_opportunity_valid", "ad_f2_handoff_target_count",
        "ad_f4_pending_dodge_reroll_valid", "bb_can_score_without_dice",
        "ad_sidecar_f5_end_activation_legal", "bb_is_marked",
    ):
        match = re.search(rf"\b{re.escape(helper)}\s*\(", code)
        require(match is not None and match.start() < legal_position,
                f"{prefix}row family derivation does not precede legal hashing: "
                f"{helper}")
    legal_hash_position = code.find("ad_sidecar_hash_legal", legal_position)
    require(legal_hash_position > legal_position,
            f"{prefix}legal framing does not follow enumeration")
    required_arguments = {
        "ad_sidecar_hash_actions": (
            "recipe->actions", "recipe->decision_teams",
            "recipe->action_count", "actions_digest"),
        "ad_sidecar_hash_dice": (
            "recipe->dice_sides", "recipe->dice_values",
            "recipe->dice_count", "dice_digest"),
        "ad_sidecar_hash_legal": (
            "legal_actions", "legal_count", "legal_digest"),
    }
    for helper, tokens in required_arguments.items():
        call_code, arguments_start, call_end = first_call_bounds(rows, helper)
        arguments = call_code[arguments_start:call_end]
        require(all(token in arguments for token in tokens),
                f"{prefix}row framing inputs differ: {helper}")
        digest = tokens[-1]
        require(identifier_count(call_code[call_end + 1:], digest) >= 1,
                f"{prefix}row ignores framed digest: {helper}")


def require_find_legal_contract(text: str, *, active: bool) -> None:
    body = function_body(text, "ad_sidecar_find_legal")
    code = code_tokens(body)
    prefix = "active " if active else ""
    require(call_count(body, "bb_legal_actions") == 1,
            f"{prefix}find-legal enumeration count differs")
    require(re.search(
        r"\bint\s+([A-Za-z_]\w*)\s*=\s*bb_legal_actions\s*\(\s*"
        r"match\s*,\s*([A-Za-z_]\w*)\s*\)\s*;", code, flags=re.S)
        is not None,
        f"{prefix}find-legal does not enumerate its supplied match")
    require(".type == type" in code and ".arg0 == arg" in code,
            f"{prefix}find-legal does not match both action selectors")
    require(re.search(r"\*\s*\([^)]*\)\s*action\s*=", code) is not None or
            re.search(r"\*\s*action\s*=", code) is not None,
            f"{prefix}find-legal does not return the selected action")
    returns = [value.strip() for value in re.findall(
        r"\breturn\s+([^;]+);", code)]
    require(returns and returns[-1] == "0" and "1" in returns[:-1],
            f"{prefix}find-legal success/failure returns differ")


def require_f5_flow(text: str, *, active: bool) -> None:
    f5 = function_body(text, "ad_sidecar_f5_end_activation_legal")
    code = code_tokens(f5)
    prefix = "active " if active else ""
    require(re.search(
        r"ad_sidecar_find_legal\s*\(\s*&\s*probe\s*,\s*BB_A_ACTIVATE\s*,"
        r"\s*probe\.ball\.carrier\s*,\s*&\s*action\s*\)",
        code, flags=re.S) is not None,
        f"{prefix}F5 activation lookup is not bound to the carrier")
    require(re.search(
        r"ad_sidecar_find_legal\s*\(\s*&\s*probe\s*,\s*BB_A_DECLARE\s*,"
        r"\s*BB_ACT_MOVE\s*,\s*&\s*action\s*\)", code, flags=re.S)
        is not None,
        f"{prefix}F5 declaration lookup differs")
    require(len(re.findall(
        r"bb_apply\s*\(\s*&\s*probe\s*,\s*action\s*,\s*&\s*rng\s*\)"
        r"\s*!=\s*BB_STATUS_DECISION", code, flags=re.S)) == 2,
        f"{prefix}F5 selected actions do not drive both transitions")
    require(re.search(
        r"return\s+ad_sidecar_find_legal\s*\(\s*&\s*probe\s*,\s*"
        r"BB_A_END_ACTIVATION\s*,\s*-1\s*,\s*&\s*action\s*\)\s*;",
        code, flags=re.S) is not None,
        f"{prefix}F5 final legal lookup differs")
    require(identifier_count(f5, "script_pos") >= 2 and
            len(re.findall(r"\bscript_pos\s*!=\s*0\b", code)) >= 2,
            f"{prefix}F5 helper does not prove zero-die transitions")


def require_alias_extent_stability(text: str, *, active: bool) -> None:
    alias = function_body(text, "ad_sidecar_alias_contract")
    code = code_tokens(alias)
    prefix = "active " if active else ""
    for variable in ("record_extent_count", "recipe_extent_count"):
        assignments = re.findall(
            rf"\b{variable}\s*=(?!=)", code)
        require(len(assignments) == 1,
                f"{prefix}alias extent count is reassigned: {variable}")


def require_protected_definitions(text: str) -> None:
    for helper in PROTECTED_DEFINITIONS:
        pattern = function_definition_pattern(helper)
        require(len(re.findall(pattern, text, flags=re.M | re.S)) == 1,
                f"protected function definition count differs: {helper}")
        function_body(text, helper)
    for helper in (
        "ad_sidecar_hash_actions", "ad_sidecar_hash_dice",
        "ad_sidecar_hash_legal",
    ):
        match = re.search(function_definition_pattern(helper), text,
                          flags=re.M | re.S)
        require(match is not None and
                identifier_count(match.group(0), "digest") == 1,
                f"protected hash output parameter differs: {helper}")


def check_active_text(text: str) -> None:
    """Check the compiler-active, macro-expanded protected implementation."""
    require_protected_definitions(text)
    for helper in PROTECTED_DEFINITIONS:
        body = function_body(text, helper)
        for name in FORBIDDEN_ACTIVE_IDENTIFIERS:
            require(identifier_count(body, name) == 0,
                    f"active protected body uses forbidden identifier: {name}")
    require_find_legal_contract(text, active=True)
    require_row_derivation_flow(text, active=True)
    require_alias_extent_stability(text, active=True)

    stage = function_body(text, "ad_sidecar_stage_pair")
    for name in (
        "ad_build_authored_proof_bundle",
        "ad_identify_authored_proof_bundle", "ad_sidecar_reconcile_bundle",
        "open_memstream", "ad_bbs_write", "fflush", "fclose",
        "ad_sidecar_sha256", "memcmp", "ad_sidecar_build_rows",
    ):
        require(call_count(stage, name) == 1,
                f"active stage call count differs: {name}")

    rows = function_body(text, "ad_sidecar_build_rows")
    for name in (
        "ad_f1_pass_opportunity_valid", "ad_f2_handoff_target_count",
        "ad_f4_pending_dodge_reroll_valid", "bb_can_score_without_dice",
        "ad_sidecar_f5_end_activation_legal", "bb_is_marked",
        "bb_legal_actions", "bb_action_pack", "ad_sidecar_hash_actions",
        "ad_sidecar_hash_dice", "ad_sidecar_hash_legal",
    ):
        require(call_count(rows, name) >= 1,
                f"active row-builder call is absent: {name}")
        require_derived_result(rows, name)

    alias = function_body(text, "ad_sidecar_alias_contract")
    require(call_count(alias, "ad_sidecar_checked_extent") == 7 and
            call_count(alias, "ad_sidecar_ranges_overlap") == 1,
            "active alias-contract calls differ")
    records_capacity_extent = re.search(
        r"ad_sidecar_checked_extent\s*\(\s*records_jsonl\s*,\s*"
        r"records_capacity", alias, flags=re.S)
    recipes_capacity_extent = re.search(
        r"ad_sidecar_checked_extent\s*\(\s*recipes_jsonl\s*,\s*"
        r"recipes_capacity", alias, flags=re.S)
    require(records_capacity_extent is not None and
            recipes_capacity_extent is not None,
        "active output alias extents ignore supplied capacities")

    f5 = function_body(text, "ad_sidecar_f5_end_activation_legal")
    require(call_count(f5, "ad_sidecar_find_legal") == 3 and
            call_count(f5, "bb_apply") == 2 and
            call_count(f5, "bb_rng_script") == 1 and
            call_count(f5, "bb_rng_error") >= 2,
            "active F5 private engine probe differs")
    require_f5_flow(text, active=True)

    public = function_body(text, "ad_serialize_authored_sidecars")
    public_code = code_tokens(public)
    require(call_count(public, "ad_sidecar_alias_contract") == 1 and
            call_count(public, "ad_sidecar_stage_pair") == 1 and
            call_count(public, "memcpy") == 2,
            "active public stage/commit calls differ")
    active_alias_position = checked_call_position(
        public, "ad_sidecar_alias_contract")
    for token in (
        "record_count != AD_AUTHORED_PROOF_BUNDLE_COUNT",
        "records_capacity < AD_AUTHORED_RECORDS_JSONL_LENGTH",
    ):
        require(active_alias_position < code_tokens(public).find(token),
                "active alias proof follows count/capacity handling")
    require("error[" not in code_tokens(public)[:active_alias_position],
            "active diagnostic precedes alias proof")
    records_copy = public_code.find("memcpy(records_jsonl")
    require(records_copy >= 0,
            "active public record commit copy is absent")
    tail = public_code[records_copy:]
    require(not re.search(r"\b(if|for|while|switch|goto)\b|\?", tail) and
            re.findall(r"\b([A-Za-z_]\w*)\s*\(", tail) ==
                ["memcpy", "memcpy"],
            "active public commit tail contains fallible work")


def check_text(text: str, oracle: dict[str, object]) -> None:
    uncommented = strip_comments(text)
    first_line = next(
        (line.strip() for line in text.splitlines() if line.strip()), ""
    )
    require(first_line == "#define _POSIX_C_SOURCE 200809L",
            "feature-test mode must be the first nonempty line")
    require(not re.search(
        r"^\s*#\s*(?:if|ifdef|ifndef|elif|else|endif)\b", text, flags=re.M),
        "conditional preprocessing is forbidden in production source")
    for match in re.finditer(r"^\s*#\s*(\w+)\b([^\n]*)$", text, flags=re.M):
        directive = match.group(1)
        line = match.group(0).strip()
        require(directive == "include" or
                line == "#define _POSIX_C_SOURCE 200809L",
                f"production source preprocessor directive is not frozen: "
                f"{directive}")
    includes = re.findall(r'^\s*#\s*include\s*([<"])([^>"]+)[>"]',
                          text, flags=re.M)
    require(bool(includes), "production source has no include declarations")
    for delimiter, included in includes:
        require(included in ALLOWED_INCLUDES,
                f"production source include is not frozen: {included}")
        require(included not in SYSTEM_INCLUDES or delimiter == "<",
                f"system include may be shadowed by quoted lookup: {included}")
        require(included != "authored_sidecar.h" or delimiter == '"',
                "owned ABI header must use quoted local lookup")
    for protected_name in (
        "ad_bbs_write", "open_memstream", "fflush", "fclose", "memcmp",
        "ad_sidecar_sha256", "ad_sidecar_hash_actions",
        "ad_sidecar_hash_dice", "ad_sidecar_hash_legal",
        "ad_sidecar_alias_contract", "ad_sidecar_reconcile_bundle",
        "ad_sidecar_find_legal", "ad_sidecar_f5_end_activation_legal",
        "ad_sidecar_build_rows", "ad_sidecar_stage_pair",
        "ad_serialize_authored_sidecars",
    ):
        require(not re.search(
            rf"^\s*#\s*(?:define|undef)\s+{re.escape(protected_name)}\b",
            text, flags=re.M),
            f"protected adapter symbol is macro-redefined: {protected_name}")
    for name in FORBIDDEN_ACTIVE_IDENTIFIERS:
        require(identifier_count(uncommented, name) == 0,
                f"forbidden length/filesystem call: {name}")
    require("bbs_length + 1" not in uncommented and
            "bbs_length+1" not in uncommented,
            "BBS comparison includes the convenience NUL")
    require("records_capacity + 1" not in uncommented and
            "records_capacity+1" not in uncommented and
            "recipes_capacity + 1" not in uncommented and
            "recipes_capacity+1" not in uncommented,
            "output capacity is treated as an inclusive maximum")
    require("!= '\\0'" not in uncommented and "== '\\0'" not in uncommented,
            "BBS payload is filtered or stopped at an embedded NUL")
    require(not re.search(r"\bif\s*\(\s*(?:0|false)\s*\)", uncommented),
            "required authority logic is placed in explicit dead code")

    require_protected_definitions(uncommented)

    alias = function_body(uncommented, "ad_sidecar_alias_contract")
    require_alias_extent_stability(uncommented, active=False)
    for role in (
        "records", "recipes", "records_jsonl", "records_length",
        "recipes_jsonl", "recipes_length", "error",
    ):
        require(role in alias, f"alias contract omits storage role: {role}")
    require("uintptr_t" in alias and "UINTPTR_MAX" in alias,
            "alias contract does not use checked integer extents")
    require(call_count(alias, "ad_sidecar_checked_extent") == 7,
            "alias contract must check all seven extents")
    require(call_count(alias, "ad_sidecar_ranges_overlap") == 1 and
            len(re.findall(r"\bfor\s*\(", alias)) >= 2,
            "alias contract does not compare every range pair")
    require(re.search(
        r"record_count\s*>\s*AD_AUTHORED_PROOF_BUNDLE_COUNT\s*\?\s*"
        r"record_count\s*:\s*AD_AUTHORED_PROOF_BUNDLE_COUNT",
        alias, flags=re.S) is not None,
        "record alias extent is not the greater supplied/fixed count")
    require(re.search(
        r"recipe_count\s*>\s*AD_AUTHORED_PROOF_BUNDLE_COUNT\s*\?\s*"
        r"recipe_count\s*:\s*AD_AUTHORED_PROOF_BUNDLE_COUNT",
        alias, flags=re.S) is not None,
        "recipe alias extent is not the greater supplied/fixed count")
    for pattern, message in (
        (r"ad_sidecar_checked_extent\s*\(\s*records\s*,\s*"
         r"record_extent_count\s*\*\s*sizeof\s*\*\s*records",
         "record alias extent does not cover complete elements"),
        (r"ad_sidecar_checked_extent\s*\(\s*recipes\s*,\s*"
         r"recipe_extent_count\s*\*\s*sizeof\s*\*\s*recipes",
         "recipe alias extent does not cover complete elements"),
        (r"ad_sidecar_checked_extent\s*\(\s*records_jsonl\s*,\s*"
         r"records_capacity", "record output alias extent ignores capacity"),
        (r"ad_sidecar_checked_extent\s*\(\s*recipes_jsonl\s*,\s*"
         r"recipes_capacity", "recipe output alias extent ignores capacity"),
    ):
        require(re.search(pattern, alias, flags=re.S) is not None, message)
    for pattern, message in (
        (r"record_extent_count\s*>\s*SIZE_MAX\s*/\s*sizeof\s*\*\s*records",
         "record alias extent multiplication is unchecked"),
        (r"recipe_extent_count\s*>\s*SIZE_MAX\s*/\s*sizeof\s*\*\s*recipes",
         "recipe alias extent multiplication is unchecked"),
    ):
        require(re.search(pattern, alias, flags=re.S) is not None, message)

    f5 = function_body(uncommented, "ad_sidecar_f5_end_activation_legal")
    f5_code = code_tokens(f5)
    require(call_count(f5, "ad_sidecar_find_legal") == 3 and
            call_count(f5, "bb_apply") == 2 and
            call_count(f5, "bb_rng_script") == 1 and
            call_count(f5, "bb_rng_error") >= 2,
            "F5 helper does not perform the complete private engine probe")
    require_find_legal_contract(uncommented, active=False)
    require_f5_flow(uncommented, active=False)
    for token in (
        "BB_A_ACTIVATE", "BB_A_DECLARE", "BB_ACT_MOVE",
        "BB_A_END_ACTIVATION",
    ):
        require(token in f5_code, f"F5 helper omits engine transition: {token}")
    f5_returns = re.findall(r"\breturn\s+([^;]+);", f5_code)
    require(bool(f5_returns) and
            all(expression.strip() == "0" for expression in f5_returns[:-1]) and
            "ad_sidecar_find_legal" in f5_returns[-1] and
            "BB_A_END_ACTIVATION" in f5_returns[-1],
            "F5 helper has an unproved success return path")
    require(not re.search(r"\b(?:goto|switch)\b|\?", f5_code),
            "F5 helper contains an alternate control path")

    stage = function_body(uncommented, "ad_sidecar_stage_pair")
    stage_code = code_tokens(stage)
    required_stage_calls = (
        "ad_build_authored_proof_bundle",
        "ad_identify_authored_proof_bundle",
        "ad_sidecar_reconcile_bundle",
        "open_memstream", "ad_bbs_write", "fflush", "fclose",
        "ad_sidecar_sha256", "memcmp", "ad_sidecar_build_rows",
    )
    for name in required_stage_calls:
        require(call_count(stage, name) == 1,
                f"stage must call {name} exactly once")
    positions = [
        re.search(rf"\b{re.escape(name)}\s*\(", stage_code).start()
        for name in required_stage_calls
    ]
    require(positions == sorted(positions),
            "writer adapter or row-build ordering differs")
    for name in (
        "ad_build_authored_proof_bundle", "ad_identify_authored_proof_bundle",
        "ad_sidecar_reconcile_bundle", "ad_bbs_write", "fflush", "fclose",
    ):
        require(re.search(
            rf"\bif\s*\(\s*{re.escape(name)}\s*\([^;]*?\)\s*!=\s*0\s*\)",
            stage_code, flags=re.S) is not None,
            f"required stage result is not checked: {name}")
    require(re.search(
        r"\bif\s*\(\s*\w+\s*==\s*NULL\s*\)", stage_code) is not None,
        "memory-stream open result is not checked")
    require("bbs_length != AD_SIDECAR_BBS_LENGTH" in stage_code,
            "returned BBS length is not compared exactly")
    require("bbs[" not in stage_code,
            "BBS payload bytes may only enter the length-counted digest")
    require("free(bbs)" in stage_code, "memory-stream buffer is not released")
    require("ad_sidecar_sha256(bbs, bbs_length, bbs_digest)" in stage_code,
            "BBS digest does not cover exactly the returned bytes")
    require(
        "if (memcmp(bbs_digest, AD_SIDECAR_BBS_SHA256, "
        "sizeof bbs_digest) != 0)" in stage_code,
        "BBS digest mismatch is not a required failure",
    )
    require("58568" in uncommented,
            "frozen BBS returned length is absent")
    require("c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1"
            in uncommented, "frozen BBS digest is absent")

    rows = function_body(uncommented, "ad_sidecar_build_rows")
    for name in (
        "ad_f1_pass_opportunity_valid",
        "ad_f2_handoff_target_count",
        "ad_f4_pending_dodge_reroll_valid",
        "bb_can_score_without_dice",
        "ad_sidecar_f5_end_activation_legal",
        "bb_is_marked",
        "bb_legal_actions",
        "bb_action_pack",
    ):
        require(call_count(rows, name) >= 1,
                f"typed row builder does not derive through {name}")
        require_derived_result(rows, name)
    for name in (
        "ad_sidecar_hash_actions", "ad_sidecar_hash_dice",
        "ad_sidecar_hash_legal",
    ):
        require(call_count(rows, name) >= 1,
                f"typed row builder bypasses candidate framing helper: {name}")
        require_derived_result(rows, name)
    require_row_derivation_flow(uncommented, active=False)

    public = function_body(uncommented, "ad_serialize_authored_sidecars")
    public_code = code_tokens(public)
    require("record_count != AD_AUTHORED_PROOF_BUNDLE_COUNT" in public_code and
            "recipe_count != AD_AUTHORED_PROOF_BUNDLE_COUNT" in public_code,
            "public entry does not enforce both exact input counts")
    require("records_capacity < AD_AUTHORED_RECORDS_JSONL_LENGTH" in public_code and
            "recipes_capacity < AD_AUTHORED_RECIPES_JSONL_LENGTH" in public_code,
            "public entry does not reject short capacities before staging")
    require(call_count(public, "ad_sidecar_alias_contract") == 1,
            "public entry must apply the complete alias contract once")
    require(re.search(
        r"\bif\s*\(\s*ad_sidecar_alias_contract\s*\([^;]*?\)\s*!=\s*0\s*\)",
        public_code, flags=re.S) is not None,
        "public entry does not honor alias-contract failure")
    require(call_count(public, "ad_sidecar_stage_pair") == 1,
            "public entry must stage the complete pair once")
    require(re.search(
        r"\bif\s*\(\s*ad_sidecar_stage_pair\s*\([^;]*?\)\s*!=\s*0\s*\)",
        public_code, flags=re.S) is not None,
        "public entry does not honor staging failure")
    alias_position = checked_call_position(public, "ad_sidecar_alias_contract")
    require(alias_position < public_code.find(
                "record_count != AD_AUTHORED_PROOF_BUNDLE_COUNT") and
            alias_position < public_code.find(
                "records_capacity < AD_AUTHORED_RECORDS_JSONL_LENGTH"),
            "alias safety is not established before count/capacity checks")
    require("error[" not in public_code[:alias_position],
            "diagnostic is written before alias safety is established")
    records_copy = public_code.find("memcpy(records_jsonl")
    recipes_copy = public_code.find("memcpy(recipes_jsonl")
    require(records_copy >= 0 and recipes_copy > records_copy,
            "paired caller-output copies differ")
    require(call_count(public, "memcpy") == 2,
            "public entry must contain exactly two commit copies")
    require(alias_position <
            public_code.find("ad_sidecar_stage_pair") < records_copy,
            "alias/stage/commit order differs")
    tail = public_code[records_copy:]
    require(not re.search(r"\b(if|for|while|switch|goto)\b|\?", tail),
            "fallible control flow remains after the first commit copy")
    tail_calls = re.findall(r"\b([A-Za-z_]\w*)\s*\(", tail)
    require(tail_calls == ["memcpy", "memcpy"],
            "fallible call remains after the first commit copy")
    require("*records_length" in tail and "*recipes_length" in tail and
            "error[0]" in tail and re.search(r"return\s+0\s*;", tail),
            "non-failing commit tail is incomplete")
    require("records_jsonl[" not in tail and "recipes_jsonl[" not in tail,
            "serializer writes a trailing output terminator")

    expected_keys = Counter(oracle["record_keys"])
    expected_keys.update(oracle["recipe_keys"])
    for key, expected_count in expected_keys.items():
        actual = len(re.findall(rf'"{re.escape(key)}"', uncommented))
        require(actual == expected_count,
                f"schema key literal count differs: {key} ({actual}/{expected_count})")
    for domain in ("BBACT1", "BBDIE1", "BBLEG1"):
        require(len(re.findall(rf'"{domain}"', uncommented)) == 1,
                f"hash domain literal differs: {domain}")
    for forbidden_label in (
        "recommended_action", "selected_action", "receiver_label",
        "target_label", "reward", "regret", "outcome", "value_label",
        "train_split",
    ):
        require(f'"{forbidden_label}"' not in uncommented,
                f"forbidden supervision label appears: {forbidden_label}")
    require_closed_call_vocabulary(uncommented)


def verify_candidate(candidate: Path, oracle: dict[str, object]) -> None:
    source_relative = str(oracle["production_source"])
    source = candidate / source_relative
    symbol = str(oracle["production_symbol"])
    language_files = [
        path for path in candidate.rglob("*")
        if (path.is_file() or path.is_symlink()) and
        path.suffix.lower() in C_LANGUAGE_SUFFIXES
    ]
    require(len(language_files) <= 2048,
            "candidate C-language file count exceeds audit bound")
    aggregate_size = 0
    for path in language_files:
        require(not path.is_symlink(),
                f"candidate C-language source is a symlink: {path}")
        size = path.stat().st_size
        require(size <= 2 * 1024 * 1024,
                f"candidate C source exceeds size bound: {path}")
        aggregate_size += size
        require(aggregate_size <= 64 * 1024 * 1024,
                "candidate C source aggregate exceeds audit bound")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        relative = path.relative_to(candidate).as_posix()
        mentions = identifier_count(text, symbol)
        allowed = set(SERIALIZER_REFERENCE_PATHS)
        allowed.add(source_relative)
        require(mentions == 0 or relative in allowed,
                f"serializer symbol occurs outside owned/authority paths: {relative}")
        require(relative in allowed or not any(
                    fragment in code_tokens(text)
                    for fragment in SERIALIZER_OWNERSHIP_FRAGMENTS),
                f"serializer ownership fragment occurs outside owned/authority paths: "
                f"{relative}")
    if not source.exists():
        require(not source.is_symlink(),
                "owned serializer path is a broken symlink")
        print("sidecar production source intentionally absent (bootstrap)")
        return
    require(not source.is_symlink(), "owned serializer source is a symlink")
    source_text = source.read_text(encoding="utf-8")
    require(identifier_count(source_text, symbol) >= 1,
            "owned serializer source omits its public symbol")
    check_text(source_text, oracle)
    print(f"sidecar source shape verified: {source}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("oracle", type=Path)
    args = parser.parse_args()
    oracle = json.loads(args.oracle.read_text(encoding="utf-8"))
    try:
        verify_candidate(args.candidate.resolve(), oracle)
    except RuntimeError as error:
        print(f"sidecar source check failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
