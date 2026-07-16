#!/usr/bin/env python3
"""Bind recipe declarations, serializer ownership, and matcher coverage."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import subprocess


REQUIRED_TYPES = {
    "ad_authored_identity",
    "ad_recipe",
    "bb_procgen_params",
    "bb_match",
    "bb_player",
    "bb_skillset",
    "bb_ball",
    "bb_frame",
}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def walk(value: object):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def record_fields(nodes: list[dict[str, object]], type_name: str):
    typedefs = [node for node in nodes
                if node.get("kind") == "TypedefDecl" and
                node.get("name") == type_name]
    require(len(typedefs) == 1, f"expected one typedef for {type_name}")
    inner = typedefs[0].get("inner", [])
    require(isinstance(inner, list) and inner,
            f"typedef {type_name} lacks a record")
    owned = inner[0].get("ownedTagDecl", {})
    record_id = owned.get("id")
    records = [node for node in nodes
               if node.get("kind") == "RecordDecl" and
               node.get("id") == record_id and
               any(child.get("kind") == "FieldDecl"
                   for child in node.get("inner", []))]
    require(len(records) == 1, f"expected one complete record for {type_name}")
    fields = []
    for child in records[0].get("inner", []):
        if child.get("kind") != "FieldDecl":
            continue
        fields.append([child.get("name"), child.get("type", {}).get("qualType")])
    return fields


def function_body(source: str, function_name: str) -> str:
    start = source.find(function_name)
    require(start >= 0, f"matcher function is missing: {function_name}")
    brace = source.find("{", start)
    require(brace >= 0, f"matcher function has no body: {function_name}")
    depth = 0
    for index in range(brace, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[brace:index + 1]
    raise RuntimeError(f"matcher function is unterminated: {function_name}")


def unwrap_expression(node: dict[str, object]) -> dict[str, object]:
    transparent = {
        "CStyleCastExpr",
        "ImplicitCastExpr",
        "ParenExpr",
    }
    while node.get("kind") in transparent:
        inner = node.get("inner", [])
        require(isinstance(inner, list) and len(inner) == 1,
                "cast expression shape differs")
        child = inner[0]
        require(isinstance(child, dict), "cast child is not an AST node")
        node = child
    return node


def referenced_name(node: dict[str, object]) -> str | None:
    node = unwrap_expression(node)
    if node.get("kind") != "DeclRefExpr":
        return None
    referenced = node.get("referencedDecl", {})
    return referenced.get("name") if isinstance(referenced, dict) else None


def null_pointer_expression(node: dict[str, object]) -> bool:
    if node.get("kind") != "ImplicitCastExpr" or \
            node.get("castKind") != "NullToPointer":
        return False
    literals = [child for child in walk(node)
                if child.get("kind") == "IntegerLiteral"]
    references = [child for child in walk(node)
                  if child.get("kind") == "DeclRefExpr"]
    return bool(literals) and not references and all(
        child.get("value") == "0" for child in literals)


def require_exact_gateway(
    nodes: list[dict[str, object]], gateway: str, underlying: str,
    expected_arguments: list[str | None],
) -> None:
    definitions = []
    for node in nodes:
        if node.get("kind") != "FunctionDecl" or node.get("name") != gateway:
            continue
        bodies = [child for child in node.get("inner", [])
                  if child.get("kind") == "CompoundStmt"]
        if bodies:
            require(len(bodies) == 1,
                    f"gateway has multiple bodies: {gateway}")
            definitions.append((node, bodies[0]))
    require(len(definitions) == 1,
            f"expected one gateway definition: {gateway}")
    declaration, body = definitions[0]
    parameters = [child.get("name") for child in declaration.get("inner", [])
                  if child.get("kind") == "ParmVarDecl"]
    expected_parameters = [name for name in expected_arguments if name is not None]
    require(parameters == expected_parameters,
            f"gateway parameter list differs: {gateway}")
    statements = body.get("inner", [])
    require(isinstance(statements, list) and len(statements) == 1 and
            statements[0].get("kind") == "ReturnStmt",
            f"gateway is not one return statement: {gateway}")
    returned = statements[0].get("inner", [])
    require(isinstance(returned, list) and len(returned) == 1,
            f"gateway return expression differs: {gateway}")
    call = unwrap_expression(returned[0])
    require(call.get("kind") == "CallExpr",
            f"gateway does not return a direct call: {gateway}")
    call_inner = call.get("inner", [])
    require(isinstance(call_inner, list) and
            len(call_inner) == len(expected_arguments) + 1,
            f"gateway call arity differs: {gateway}")
    require(referenced_name(call_inner[0]) == underlying,
            f"gateway calls the wrong function: {gateway}")
    for index, expected in enumerate(expected_arguments):
        argument = call_inner[index + 1]
        if expected is None:
            require(null_pointer_expression(argument),
                    f"gateway argument {index} is not null: {gateway}")
        else:
            require(referenced_name(argument) == expected,
                    f"gateway argument {index} differs: {gateway}")


def json_documents(text: str) -> list[dict[str, object]]:
    decoder = json.JSONDecoder()
    documents = []
    offset = 0
    while offset < len(text):
        while offset < len(text) and text[offset].isspace():
            offset += 1
        if offset == len(text):
            break
        document, offset = decoder.raw_decode(text, offset)
        require(isinstance(document, dict), "Clang AST document is not an object")
        documents.append(document)
    return documents


def require_writer_control_flow(
    compiler: str, candidate: Path,
) -> None:
    completed = subprocess.run(
        [
            compiler,
            "-std=c11",
            f"-I{candidate / 'engine' / 'include'}",
            f"-I{candidate / 'tools'}",
            "-Xclang",
            "-ast-dump=json",
            "-Xclang",
            "-ast-dump-filter=ad_bbs_write",
            "-fsyntax-only",
            str(candidate / "tools" / "authored_drill.c"),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=60,
    )
    require(completed.returncode == 0,
            f"writer Clang AST failed: {completed.stderr}")
    definitions = []
    for document in json_documents(completed.stdout):
        if document.get("kind") != "FunctionDecl" or \
                document.get("name") != "ad_bbs_write":
            continue
        if any(child.get("kind") == "CompoundStmt"
               for child in document.get("inner", [])):
            definitions.append(document)
    require(len(definitions) == 1, "expected one writer definition")
    definition = definitions[0]
    parents: dict[int, dict[str, object]] = {}

    def index_parents(node: dict[str, object]) -> None:
        for child in node.get("inner", []):
            if isinstance(child, dict):
                parents[id(child)] = node
                index_parents(child)

    index_parents(definition)
    writer_nodes = [node for node in walk(definition)
                    if isinstance(node, dict)]

    def call_name(node: dict[str, object]) -> str | None:
        inner = node.get("inner", [])
        if node.get("kind") != "CallExpr" or not inner:
            return None
        return referenced_name(inner[0])

    gateway_names = (
        "ad_authored_fresh_admission_gate",
        "ad_authored_resumable_admission_gate",
        "ad_authored_continuation_gate",
    )
    calls = {
        name: [node for node in writer_nodes if call_name(node) == name]
        for name in gateway_names
    }
    for name, matches in calls.items():
        require(len(matches) == 1,
                f"writer gateway AST call count differs: {name}")
    for underlying in (
        "bb_state_bank_boundary_valid",
        "bb_state_bank_resumable_valid",
        "ad_verify_one_action_continuation",
    ):
        require(not any(call_name(node) == underlying for node in writer_nodes),
                f"writer AST directly calls an underlying gate: {underlying}")

    controls = {"IfStmt", "ConditionalOperator", "ForStmt", "WhileStmt",
                "DoStmt", "SwitchStmt"}

    def control_chain(node: dict[str, object]) -> list[dict[str, object]]:
        result = []
        parent = parents.get(id(node))
        while parent is not None:
            if parent.get("kind") in controls:
                result.append(parent)
            parent = parents.get(id(parent))
        return result

    fresh_chain = control_chain(calls[gateway_names[0]][0])
    resumable_chain = control_chain(calls[gateway_names[1]][0])
    continuation_chain = control_chain(calls[gateway_names[2]][0])
    require([node.get("kind") for node in fresh_chain] ==
                ["ConditionalOperator", "ForStmt"],
            "fresh gateway has unexpected conditional control")
    require([node.get("kind") for node in resumable_chain] ==
                ["ConditionalOperator", "ForStmt"],
            "resumable gateway has unexpected conditional control")
    require([node.get("kind") for node in continuation_chain] ==
                ["IfStmt", "ForStmt"],
            "continuation gateway has unexpected conditional control")
    admission_choice = fresh_chain[0]
    preflight_loop = fresh_chain[1]
    require(resumable_chain[0] is admission_choice and
            resumable_chain[1] is preflight_loop and
            continuation_chain[1] is preflight_loop,
            "writer gateways do not share one preflight loop")
    choice_inner = admission_choice.get("inner", [])
    require(len(choice_inner) == 3,
            "writer admission choice shape differs")
    choice_condition = unwrap_expression(choice_inner[0])
    require(choice_condition.get("kind") == "BinaryOperator" and
            choice_condition.get("opcode") == "==",
            "writer admission choice condition differs")
    condition_nodes = list(walk(choice_condition))
    require([node.get("name") for node in condition_nodes
             if node.get("kind") == "MemberExpr"] == ["kind"],
            "writer admission choice does not use only recipe kind")
    require([node.get("referencedDecl", {}).get("name")
             for node in condition_nodes
             if node.get("kind") == "DeclRefExpr"] ==
                ["rediscovered", "AD_RECIPE_F4_PENDING_DODGE_REROLL"],
            "writer admission choice enum differs")
    require(any(call_name(node) == "ad_authored_resumable_admission_gate"
                for node in walk(choice_inner[1])) and
            any(call_name(node) == "ad_authored_fresh_admission_gate"
                for node in walk(choice_inner[2])),
            "writer admission choice branches differ")

    continuation_if = continuation_chain[0]
    continuation_inner = continuation_if.get("inner", [])
    require(continuation_inner, "writer continuation condition is missing")
    continuation_condition = unwrap_expression(continuation_inner[0])
    require(continuation_condition.get("kind") == "BinaryOperator" and
            continuation_condition.get("opcode") == "!=",
            "writer continuation condition differs")
    require(sum(call_name(node) == "ad_authored_continuation_gate"
                for node in walk(continuation_condition)) == 1,
            "writer continuation condition call differs")
    require([node.get("value") for node in walk(continuation_condition)
             if node.get("kind") == "IntegerLiteral"] == ["0"],
            "writer continuation comparison differs")

    forbidden_flow = {"ContinueStmt", "GotoStmt", "LabelStmt", "BreakStmt"}
    require(not any(node.get("kind") in forbidden_flow for node in writer_nodes),
            "writer contains unsupported loop/control transfer")

    count_parameters = [node for node in definition.get("inner", [])
                        if node.get("kind") == "ParmVarDecl" and
                        node.get("name") == "count"]
    require(len(count_parameters) == 1, "writer count parameter differs")
    count_id = count_parameters[0].get("id")
    count_refs = [node for node in writer_nodes
                  if node.get("kind") == "DeclRefExpr" and
                  node.get("referencedDecl", {}).get("id") == count_id]
    require(len(count_refs) == 5, "writer count-use manifest differs")

    def significant_parent(node: dict[str, object]) -> dict[str, object] | None:
        parent = parents.get(id(node))
        while parent is not None and parent.get("kind") in {
                "ImplicitCastExpr", "ParenExpr", "CStyleCastExpr"}:
            parent = parents.get(id(parent))
        return parent

    count_contexts = [(significant_parent(node) or {}).get("kind")
                      for node in count_refs]
    count_opcodes = [(significant_parent(node) or {}).get("opcode")
                     for node in count_refs]
    require(count_contexts == ["BinaryOperator", "BinaryOperator", "CallExpr",
                               "BinaryOperator", "BinaryOperator"] and
            count_opcodes == ["==", ">", None, "<", "<"],
            "writer count-use contexts differ")
    require(call_name(significant_parent(count_refs[2]) or {}) == "calloc",
            "writer allocation no longer uses count directly")
    count_loops = [parents.get(id(significant_parent(node) or {}))
                   for node in count_refs[3:]]
    require(count_loops[0] is preflight_loop and
            count_loops[1] is not None and count_loops[1] is not preflight_loop and
            count_loops[1].get("kind") == "ForStmt",
            "writer count loops differ")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("fixture", type=Path)
    parser.add_argument("serializer", type=Path)
    parser.add_argument("--compiler", default="clang")
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    manifest = fixture["declaration_manifest"]
    require(set(manifest) == REQUIRED_TYPES,
            "oracle declaration type set differs")
    compiler = shutil.which(args.compiler)
    require(compiler is not None, f"compiler not found: {args.compiler}")
    command = [
        compiler,
        "-std=c11",
        f"-I{candidate / 'engine' / 'include'}",
        f"-I{candidate / 'tools'}",
        "-Xclang",
        "-ast-dump=json",
        "-fsyntax-only",
        "-x",
        "c",
        "-",
    ]
    completed = subprocess.run(
        command,
        input='#include "authored_drill.h"\n',
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=60,
    )
    require(completed.returncode == 0,
            f"Clang AST failed: {completed.stderr}")
    ast = json.loads(completed.stdout)
    nodes = [node for node in walk(ast) if isinstance(node, dict)]
    for type_name, expected_fields in manifest.items():
        actual_fields = record_fields(nodes, type_name)
        require(actual_fields == expected_fields,
                f"declaration differs for {type_name}: {actual_fields}")

    recipe_names = [name for name, _ in manifest["ad_recipe"]]
    assignments = fixture["recipe_field_assignments"]
    require(list(assignments) == recipe_names,
            "recipe stream assignment coverage/order differs")
    require(all(isinstance(category, str) and category
                for category in assignments.values()),
            "recipe stream assignment category is empty")

    serializer = args.serializer.read_text(encoding="utf-8")
    for name, _ in manifest["ad_recipe"]:
        require(f"recipe->{name}" in serializer,
                f"serializer does not bind ad_recipe.{name}")
    for name, _ in manifest["bb_procgen_params"]:
        require(f"recipe->procgen.{name}" in serializer,
                f"serializer does not bind bb_procgen_params.{name}")
    for name, _ in manifest["bb_match"]:
        require(f"match->{name}" in serializer,
                f"serializer does not bind bb_match.{name}")
    for name, _ in manifest["bb_player"]:
        require(f"player->{name}" in serializer,
                f"serializer does not bind bb_player.{name}")
    require("player->skills.w[" in serializer,
            "serializer does not bind bb_skillset.w")
    for name, _ in manifest["bb_ball"]:
        require(f"match->ball.{name}" in serializer,
                f"serializer does not bind bb_ball.{name}")
    for name, _ in manifest["bb_frame"]:
        require(f"frame->{name}" in serializer,
                f"serializer does not bind bb_frame.{name}")

    matcher_source = (candidate / "tools" / "authored_identity.c").read_text(
        encoding="utf-8")
    projection_body = function_body(
        matcher_source, "ad_recipe_projection_from_recipe")
    equality_body = function_body(matcher_source, "ad_recipe_projection_equal")
    for field in fixture["matcher_fields"]:
        recipe_reference = "recipe->" + field
        require(recipe_reference in projection_body,
                f"projection matcher does not consume {field}")
        leaf = field.rsplit(".", 1)[-1]
        require(f"->{leaf}" in equality_body or f".{leaf}" in equality_body,
                f"projection equality does not compare {field}")

    drill_source = (candidate / "tools" / "authored_drill.c").read_text(
        encoding="utf-8")
    writer_body = function_body(drill_source, "ad_bbs_write")
    for gateway in (
        "ad_authored_fresh_admission_gate",
        "ad_authored_resumable_admission_gate",
        "ad_authored_continuation_gate",
    ):
        require(writer_body.count(gateway) == 1,
                f"writer gateway call count differs: {gateway}")
    for bypass in (
        "bb_state_bank_boundary_valid",
        "bb_state_bank_resumable_valid",
        "ad_verify_one_action_continuation",
    ):
        require(bypass not in writer_body,
                f"writer directly bypasses a gateway: {bypass}")
    require("ad_authored_legacy_allocation" in
            function_body(drill_source, "ad_build_authored_proof_bundle"),
            "legacy builder does not resolve the frozen schedule")
    require_writer_control_flow(compiler, candidate)

    gateway_path = candidate / "tools" / "authored_writer_gates.c"
    gateway_completed = subprocess.run(
        [
            compiler,
            "-std=c11",
            f"-I{candidate / 'engine' / 'include'}",
            f"-I{candidate / 'tools'}",
            "-Xclang",
            "-ast-dump=json",
            "-fsyntax-only",
            str(gateway_path),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
        timeout=60,
    )
    require(gateway_completed.returncode == 0,
            f"gateway Clang AST failed: {gateway_completed.stderr}")
    gateway_ast = json.loads(gateway_completed.stdout)
    gateway_nodes = [node for node in walk(gateway_ast)
                     if isinstance(node, dict)]
    require_exact_gateway(
        gateway_nodes, "ad_authored_fresh_admission_gate",
        "bb_state_bank_boundary_valid", ["match"])
    require_exact_gateway(
        gateway_nodes, "ad_authored_resumable_admission_gate",
        "bb_state_bank_resumable_valid", ["match"])
    require_exact_gateway(
        gateway_nodes, "ad_authored_continuation_gate",
        "ad_verify_one_action_continuation",
        ["match", None, None, None, "error"])

    print("authored declaration and assignment coverage verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
