#!/usr/bin/env python3
"""Verify one candidate tree against the immutable sidecar authority."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import selectors
import time

from source_check import check_active_text, function_body_bounds, strip_comments


ENGINE_SOURCES = (
    "bb_blockev.c", "bb_hooks.c", "bb_match.c", "bb_procgen.c",
    "bb_reachability.c", "bb_replay.c", "bb_rng.c", "bb_skills.c",
    "gen_skills.c", "gen_tables.c", "gen_teams.c", "proc_ball.c",
    "proc_block.c", "proc_match.c", "proc_move.c", "proc_table.c",
    "proc_test.c", "proc_ttm.c", "proc_turn.c", "skills_agility.c",
    "skills_core.c", "skills_devious_traits.c", "skills_mutation_passing.c",
)
MAX_COMMAND_OUTPUT_BYTES = 4 * 1024 * 1024
ALLOWED_SERIALIZER_UNDEFINED_SYMBOLS = {
    "ad_authored_allocation_by_source", "ad_authored_template_key",
    "ad_bbs_write", "ad_build_authored_proof_bundle",
    "ad_f1_pass_opportunity_valid", "ad_f2_handoff_target_count",
    "ad_f4_pending_dodge_reroll_valid", "ad_identify_authored_proof_bundle",
    "ad_recipe_projection_equal", "ad_recipe_projection_from_recipe",
    "bb_apply", "bb_can_score_without_dice", "bb_is_marked",
    "bb_legal_actions", "bb_rng_script", "bb_state_bank_dodge_reroll_valid",
    "calloc", "fclose", "fflush", "free", "malloc", "memcmp", "memcpy",
    "memmove", "memset", "open_memstream", "qsort", "realloc", "snprintf",
}
ALLOWED_SERIALIZER_DEFINED_SYMBOLS = {
    "ad_serialize_authored_sidecars",
    "ad_sidecar_alias_contract",
    "ad_sidecar_f5_end_activation_legal",
    "ad_sidecar_hash_actions",
    "ad_sidecar_hash_dice",
    "ad_sidecar_hash_legal",
    "ad_sidecar_reconcile_bundle",
    "ad_sidecar_sha256",
}
ALLOWED_TRUSTED_CANDIDATE_PROVIDERS = ALLOWED_SERIALIZER_DEFINED_SYMBOLS | {
    "ad_authored_template_key",
    "ad_bbs_write",
    "ad_build_authored_proof_bundle",
    "ad_f1_pass_opportunity_valid",
    "ad_f2_handoff_target_count",
    "ad_f4_pending_dodge_reroll_valid",
    "ad_f5_score_or_wait_valid",
    "ad_identify_authored_proof_bundle",
    "bb_apply",
    "bb_can_score_without_dice",
    "bb_is_marked",
    "bb_legal_actions",
    "bb_rng_script",
    "bb_team_defs",
}
ALWAYS_FORBIDDEN_LINKED_CANDIDATE_SYMBOLS = ALLOWED_SERIALIZER_DEFINED_SYMBOLS | {
    "_Exit", "__chkstk_darwin", "__memcpy_chk", "__stderrp", "__stdoutp",
    "abort", "calloc", "exit", "fclose", "fflush", "fopen", "fprintf",
    "fputc", "fread", "free", "fseek", "ftell", "fwrite", "malloc",
    "memcmp", "memcpy", "memmove", "memset", "open_memstream", "qsort",
    "realloc", "snprintf", "stderr", "stdout", "strcmp", "strlen",
}
SYNTHETIC_UNUSED_FLAGS = (
    "-Wno-unused-parameter", "-Wno-unused-function",
    "-Wno-unused-variable", "-Wno-unused-const-variable",
)
SANITIZER_RUNTIME_IMPORT_PREFIXES = ("__asan_", "__ubsan_")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def run(command: list[str], *, timeout: int, cwd: Path | None = None,
        expect_success: bool = True) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(
        command, cwd=cwd, stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    streams = {process.stdout: bytearray(), process.stderr: bytearray()}
    selector = selectors.DefaultSelector()
    for stream in streams:
        require(stream is not None, "subprocess pipe is missing")
        os.set_blocking(stream.fileno(), False)
        selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + timeout
    failure: str | None = None
    while selector.get_map():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            failure = f"command exceeded {timeout}s"
            break
        for key, _ in selector.select(min(remaining, 0.25)):
            stream = key.fileobj
            chunk = os.read(stream.fileno(), 65536)
            if not chunk:
                selector.unregister(stream)
                continue
            streams[stream].extend(chunk)
            if sum(len(data) for data in streams.values()) > MAX_COMMAND_OUTPUT_BYTES:
                failure = "command exceeded bounded output allowance"
                break
        if failure is not None:
            break
    if failure is not None:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=30)
    stdout = bytes(streams[process.stdout])
    stderr = bytes(streams[process.stderr])
    if failure is not None:
        raise RuntimeError(
            f"{failure}: {' '.join(command)}\n"
            f"{(stdout + stderr).decode('utf-8', errors='replace')}"
        )
    if expect_success and process.returncode != 0:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            f"{(stdout + stderr).decode('utf-8', errors='replace')}"
        )
    if not expect_success and process.returncode == 0:
        raise RuntimeError(f"malicious command unexpectedly passed: {' '.join(command)}")
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def engine_sources(candidate: Path) -> list[Path]:
    root = candidate / "engine" / "src"
    actual = tuple(sorted(path.name for path in root.glob("*.c")))
    require(actual == tuple(sorted(ENGINE_SOURCES)),
            "candidate engine source allowlist differs")
    sources = [root / name for name in ENGINE_SOURCES]
    for source in sources:
        require(source.is_file() and not source.is_symlink(),
                f"candidate engine source is not a regular file: {source.name}")
    return sources


def flags(compiler: str, candidate: Path, sanitizer: bool) -> list[str]:
    result = [
        compiler, "-std=c11", "-O1" if sanitizer else "-O2", "-g",
        "-Wall", "-Wextra", "-Werror", "-fno-lto", "-fno-builtin",
        "-fno-stack-protector",
        "-iquote", str(candidate / "tools"),
        "-idirafter", str(candidate / "engine" / "include"),
    ]
    if sanitizer:
        result.extend((
            "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
            "-fno-sanitize-address-globals-dead-stripping",
        ))
    return result


def authored_sources(candidate: Path) -> list[Path]:
    paths = [
        candidate / "tools" / "authored_drill.c",
        candidate / "tools" / "authored_identity.c",
        candidate / "tools" / "authored_writer_gates.c",
    ]
    for path in paths:
        require(path.is_file() and not path.is_symlink(),
                f"missing or symlinked authored source: {path.name}")
    return paths


def compile_fact_probe(compiler: str, candidate: Path, trusted: Path,
                       binary: Path, sanitizer: bool) -> None:
    sources = [trusted / "fact_probe.c", *authored_sources(candidate),
               *engine_sources(candidate)]
    run([*flags(compiler, candidate, sanitizer),
         *(str(path) for path in sources), "-o", str(binary)], timeout=90)


def compile_serializer_probe(compiler: str, candidate: Path, trusted: Path,
                             binary: Path, sanitizer: bool,
                             source_override: Path | None = None,
                             synthetic_mutation: bool = False) -> None:
    source = source_override or candidate / "tools" / "authored_sidecar.c"
    require(source.is_file() and not source.is_symlink(),
            "serializer source disappeared or became a symlink")
    serializer_input: Path = source
    if synthetic_mutation:
        serializer_input = binary.with_name(binary.name + "-candidate.o")
        run([
            *flags(compiler, candidate, sanitizer), *SYNTHETIC_UNUSED_FLAGS, "-c",
            str(source), "-o", str(serializer_input),
        ], timeout=60)
    command = [
        *flags(compiler, candidate, sanitizer),
        str(trusted / "serializer_probe.c"), serializer_input,
        *authored_sources(candidate), *engine_sources(candidate),
    ]
    if sys.platform.startswith("linux"):
        for symbol in (
            "ad_build_authored_proof_bundle",
            "ad_identify_authored_proof_bundle",
            "ad_bbs_write",
            "open_memstream",
            "fflush",
            "fclose",
            "malloc",
            "calloc",
            "realloc",
            "free",
            "ad_f1_pass_opportunity_valid",
            "ad_f2_handoff_target_count",
            "ad_f4_pending_dodge_reroll_valid",
            "bb_can_score_without_dice",
            "bb_is_marked",
            "bb_legal_actions",
        ):
            command.append(f"-Wl,--wrap={symbol}")
    command.extend(("-o", str(binary)))
    run(command, timeout=90)


def replace_function_body(source_text: str, name: str, body: str) -> str:
    start, end = function_body_bounds(strip_comments(source_text), name)
    return source_text[:start] + f"\n    {body}\n" + source_text[end:]


def canonical_jsonl(rows: list[dict[str, object]]) -> bytes:
    return b"".join(
        json.dumps(row, ensure_ascii=True, allow_nan=False,
                   separators=(",", ":")).encode("ascii") + b"\n"
        for row in rows
    )


def build_transformed_expected(expected_root: Path, work: Path,
                               label: str) -> Path:
    """Build the exact successful output required from one helper mutation."""
    records_path = expected_root / "records.jsonl"
    recipes_path = expected_root / "recipes.jsonl"
    original_records = records_path.read_bytes()
    original_recipes = recipes_path.read_bytes()
    records = [json.loads(line) for line in original_records.decode(
        encoding="ascii").splitlines()]
    recipes = [json.loads(line) for line in original_recipes.decode(
        encoding="ascii").splitlines()]
    require(canonical_jsonl(records) == original_records and
            canonical_jsonl(recipes) == original_recipes,
            "canonical source JSONL differs before transformation")
    changed = 0
    zero_digest = "0" * 64
    field = {
        "actions-hash": "actions_sha256",
        "dice-hash": "dice_sha256",
        "legal-hash": "legal_actions_sha256",
    }[label]
    targets = records if label == "legal-hash" else [*records, *recipes]
    for row in targets:
        require(row[field] != zero_digest,
                f"canonical {label} digest is already zero")
        row[field] = zero_digest
        changed += 1
    expected_changes = 26 if label == "legal-hash" else 52
    require(changed == expected_changes,
            f"transformed {label} oracle change count differs")
    transformed = work / f"expected-{label}"
    transformed.mkdir()
    transformed_records = canonical_jsonl(records)
    transformed_recipes = canonical_jsonl(recipes)
    require(transformed_records != original_records,
            f"transformed {label} record oracle did not change")
    if label in ("actions-hash", "dice-hash"):
        require(transformed_recipes != original_recipes,
                f"transformed {label} recipe oracle did not change")
    else:
        require(transformed_recipes == original_recipes,
                f"transformed {label} changed unrelated recipe bytes")
    (transformed / "records.jsonl").write_bytes(transformed_records)
    (transformed / "recipes.jsonl").write_bytes(transformed_recipes)
    return transformed


def verify_synthetic_mutation_flags(compiler: str, candidate: Path,
                                    work: Path) -> None:
    """Prove only a synthetic candidate object receives the unused waiver."""
    source = work / "synthetic-unused.c"
    source.write_text(
        "static int orphan(void) { return 0; }\n"
        "static int orphan_variable = 1;\n"
        "static const int orphan_const_variable = 1;\n"
        "int main(int argc, char** argv) { return 0; }\n",
        encoding="ascii")
    run([
        *flags(compiler, candidate, False), "-c", str(source),
        "-o", str(work / "synthetic-unused-strict.o"),
    ], timeout=30, expect_success=False)
    run([
        *flags(compiler, candidate, False), *SYNTHETIC_UNUSED_FLAGS,
        "-c", str(source),
        "-o", str(work / "synthetic-unused-waived.o"),
    ], timeout=30)


def verify_public_derivation_mutations(
    compiler: str, candidate: Path, trusted: Path, work: Path,
    expected_root: Path, transformed_expected: dict[str, Path]) -> None:
    source = candidate / "tools" / "authored_sidecar.c"
    source_text = source.read_text(encoding="utf-8")
    mutations = {
        "f5": ("ad_sidecar_f5_end_activation_legal", "return 0;"),
        "actions-hash": (
            "ad_sidecar_hash_actions",
            "memset(digest, 0, 32); return 0;"),
        "dice-hash": (
            "ad_sidecar_hash_dice",
            "memset(digest, 0, 32); return 0;"),
        "legal-hash": (
            "ad_sidecar_hash_legal",
            "memset(digest, 0, 32); return 0;"),
    }
    for label, (function, body) in mutations.items():
        mutated_source = work / f"authored-sidecar-{label}.c"
        mutated_source.write_text(
            replace_function_body(source_text, function, body),
            encoding="utf-8")
        expected = (expected_root if label == "f5"
                    else transformed_expected[label])
        mode = "f5-reject" if label == "f5" else "public-only"
        for variant, sanitizer in (("optimized", False), ("sanitized", True)):
            binary = work / f"serializer-public-derivation-{label}-{variant}"
            compile_serializer_probe(
                compiler, candidate, trusted, binary, sanitizer,
                mutated_source, synthetic_mutation=True)
            run([
                str(binary), str(expected / "records.jsonl"),
                str(expected / "recipes.jsonl"), mode,
            ], timeout=180)


def compile_serializer_probe_object(compiler: str, candidate: Path,
                                    trusted: Path, output: Path,
                                    sanitizer: bool) -> None:
    run([
        *flags(compiler, candidate, sanitizer), "-c",
        str(trusted / "serializer_probe.c"), "-o", str(output),
    ], timeout=60)


def global_defined_symbols(nm: str, output: Path) -> set[str]:
    result = run([nm, "-g", str(output)], timeout=30)
    defined: set[str] = set()
    for raw_line in result.stdout.decode("utf-8", errors="strict").splitlines():
        fields = raw_line.split()
        if len(fields) < 2:
            continue
        symbol_type = fields[-2]
        if symbol_type == "U" or (
            len(fields) == 2 and symbol_type in {"w", "v"}
        ):
            continue
        name = fields[-1].split("@", 1)[0]
        if sys.platform == "darwin" and name.startswith("_"):
            name = name[1:]
        defined.add(name)
    return defined


def global_undefined_symbols(nm: str, output: Path) -> set[str]:
    result = run([nm, "-u", str(output)], timeout=30)
    undefined: set[str] = set()
    for raw_line in result.stdout.decode("utf-8", errors="strict").splitlines():
        fields = raw_line.split()
        if not fields:
            continue
        name = fields[-1].split("@", 1)[0]
        if sys.platform == "darwin" and name.startswith("_"):
            name = name[1:]
        undefined.add(name)
    return undefined


def verify_allowed_serializer_exports(nm: str, output: Path) -> None:
    defined = global_defined_symbols(nm, output)
    unexpected = sorted(defined - ALLOWED_SERIALIZER_DEFINED_SYMBOLS)
    missing = sorted(ALLOWED_SERIALIZER_DEFINED_SYMBOLS - defined)
    require(not unexpected,
            f"serializer object exports unapproved symbols: {unexpected}")
    require(not missing,
            f"serializer object omits required symbols: {missing}")


def verify_no_forbidden_linked_exports(
    nm: str, output: Path, label: str,
    trusted_imports: set[str] | None = None,
) -> None:
    defined = global_defined_symbols(nm, output)
    forbidden_symbols = ALWAYS_FORBIDDEN_LINKED_CANDIDATE_SYMBOLS | (
        trusted_imports or set()
    )
    forbidden = sorted(
        name for name in defined
        if name in forbidden_symbols or
        name.startswith(("__real_", "__wrap_", "__asan_", "__ubsan_"))
    )
    require(not forbidden,
            f"{label} defines forbidden linked symbols: {forbidden}")


def verify_serializer_object_symbols(
    compiler: str, candidate: Path, work: Path) -> None:
    source = candidate / "tools" / "authored_sidecar.c"
    nm = shutil.which("nm")
    require(nm is not None, "nm is required for serializer symbol audit")
    for label, sanitizer in (("optimized", False), ("sanitized", True)):
        output = work / f"authored-sidecar-{label}.o"
        run([*flags(compiler, candidate, sanitizer), "-c", str(source),
             "-o", str(output)], timeout=60)
        undefined = global_undefined_symbols(nm, output)
        unexpected = sorted(
            name for name in undefined
            if name not in ALLOWED_SERIALIZER_UNDEFINED_SYMBOLS and not (
                sanitizer and name.startswith(SANITIZER_RUNTIME_IMPORT_PREFIXES)
            )
        )
        require(
            not unexpected,
            f"{label} serializer object imports unapproved symbols: "
            f"{unexpected}",
        )
        verify_allowed_serializer_exports(nm, output)


def verify_serializer_export_audit_selftest(
    compiler: str, candidate: Path, work: Path) -> None:
    source = work / "serializer-export-selftest.c"
    definitions = "\n".join(
        f"void {name}(void) {{}}"
        for name in sorted(ALLOWED_SERIALIZER_DEFINED_SYMBOLS)
    )
    dangerous = (
        "__chkstk_darwin", "__memcpy_chk", "__real_memcmp", "__stderrp",
        "__stdoutp", "__wrap_memcmp", "fclose", "fflush", "fputc", "free",
        "malloc", "memcmp", "memcpy", "open_memstream",
    )
    overrides = "\n".join(f"void {name}(void) {{}}" for name in dangerous)
    source.write_text(f"{definitions}\n{overrides}\n", encoding="utf-8")
    nm = shutil.which("nm")
    require(nm is not None, "nm is required for serializer export self-test")
    for label, sanitizer in (("optimized", False), ("sanitized", True)):
        output = work / f"serializer-export-selftest-{label}.o"
        run([*flags(compiler, candidate, sanitizer), "-c", str(source),
             "-o", str(output)], timeout=60)
        defined = global_defined_symbols(nm, output)
        require(set(dangerous).issubset(defined),
                f"{label} serializer export self-test omits an override")
        try:
            verify_allowed_serializer_exports(nm, output)
        except RuntimeError as error:
            require(
                "exports unapproved symbols" in str(error),
                f"{label} serializer export self-test rejected for wrong reason",
            )
        else:
            raise RuntimeError(
                f"{label} serializer export audit accepted library overrides")
        try:
            verify_no_forbidden_linked_exports(
                nm, output, f"{label} export self-test")
        except RuntimeError as error:
            require(
                "defines forbidden linked symbols" in str(error),
                f"{label} linked export self-test rejected for wrong reason",
            )
        else:
            raise RuntimeError(
                f"{label} linked export audit accepted library overrides")

        allowed_source = work / f"serializer-allowed-exports-{label}.c"
        allowed_source.write_text(f"{definitions}\n", encoding="utf-8")
        allowed_output = work / f"serializer-allowed-exports-{label}.o"
        run([*flags(compiler, candidate, sanitizer), "-c",
             str(allowed_source), "-o", str(allowed_output)], timeout=60)
        verify_allowed_serializer_exports(nm, allowed_output)

    conditional = work / "sanitizer-export-selftest.c"
    conditional.write_text(
        "#include <stddef.h>\n"
        "#if defined(__has_feature)\n"
        "#if __has_feature(address_sanitizer)\n"
        "int memcmp(const void *left, const void *right, size_t size) {\n"
        "    (void)left; (void)right; (void)size; return 0;\n"
        "}\n"
        "#endif\n"
        "#endif\n",
        encoding="utf-8",
    )
    for label, sanitizer in (("optimized", False), ("sanitized", True)):
        conditional_output = work / f"sanitizer-export-selftest-{label}.o"
        run([*flags(compiler, candidate, sanitizer), "-c", str(conditional),
             "-o", str(conditional_output)], timeout=60)
        conditional_defined = global_defined_symbols(nm, conditional_output)
        if not sanitizer:
            require("memcmp" not in conditional_defined,
                    "optimized sanitizer export self-test unexpectedly active")
            verify_no_forbidden_linked_exports(
                nm, conditional_output, "optimized sanitizer export self-test")
            continue
        require("memcmp" in conditional_defined,
                "sanitized export self-test did not define memcmp")
        try:
            verify_no_forbidden_linked_exports(
                nm, conditional_output, "sanitized export self-test")
        except RuntimeError as error:
            require("defines forbidden linked symbols" in str(error),
                    "sanitized export self-test rejected for wrong reason")
        else:
            raise RuntimeError("sanitized linked export audit accepted memcmp")

    if sys.platform.startswith("linux"):
        unique_source = work / "gnu-unique-export-selftest.s"
        unique_source.write_text(
            ".data\n"
            ".globl memcmp\n"
            ".type memcmp, @gnu_unique_object\n"
            ".size memcmp, 8\n"
            "memcmp:\n"
            "  .quad 0\n"
            ".weak weak_undefined_canary\n"
            ".quad weak_undefined_canary\n",
            encoding="utf-8",
        )
        unique_output = work / "gnu-unique-export-selftest.o"
        run([compiler, "-c", str(unique_source), "-o", str(unique_output)],
            timeout=60)
        unique_defined = global_defined_symbols(nm, unique_output)
        require("memcmp" in unique_defined,
                "GNU-unique export self-test did not parse defined memcmp")
        require("weak_undefined_canary" not in unique_defined,
                "GNU-unique export self-test treated weak undefined as defined")
        try:
            verify_no_forbidden_linked_exports(
                nm, unique_output, "GNU-unique export self-test")
        except RuntimeError as error:
            require("defines forbidden linked symbols" in str(error),
                    "GNU-unique export self-test rejected for wrong reason")
        else:
            raise RuntimeError("linked export audit accepted GNU-unique memcmp")


def trusted_probe_imports(
    compiler: str, candidate: Path, trusted: Path, work: Path,
    sanitizer: bool,
) -> set[str]:
    nm = shutil.which("nm")
    require(nm is not None, "nm is required for trusted probe import audit")
    imports: set[str] = set()
    variant = "sanitized" if sanitizer else "optimized"
    for source_name in ("fact_probe.c", "serializer_probe.c"):
        source = trusted / source_name
        output = work / f"trusted-imports-{variant}-{source_name}.o"
        run([*flags(compiler, candidate, sanitizer), "-c", str(source),
             "-o", str(output)], timeout=60)
        imports.update(global_undefined_symbols(nm, output))
    protected = imports - ALLOWED_TRUSTED_CANDIDATE_PROVIDERS
    require(protected,
            f"{variant} trusted probes expose no protected imports")
    return protected


def verify_linked_candidate_exports(
    compiler: str, candidate: Path, trusted: Path, work: Path,
) -> None:
    nm = shutil.which("nm")
    require(nm is not None, "nm is required for linked candidate export audit")
    sources = [*authored_sources(candidate), *engine_sources(candidate)]
    for variant, sanitizer in (("optimized", False), ("sanitized", True)):
        protected = trusted_probe_imports(
            compiler, candidate, trusted, work, sanitizer)
        for number, source in enumerate(sources):
            output = work / (
                f"linked-candidate-{variant}-{number:02d}-{source.name}.o"
            )
            run([*flags(compiler, candidate, sanitizer), "-c", str(source),
                 "-o", str(output)], timeout=60)
            verify_no_forbidden_linked_exports(
                nm, output, f"{variant} {source.name}", protected)


def verify_preprocessed_source(compiler: str, candidate: Path,
                               work: Path) -> None:
    source = candidate / "tools" / "authored_sidecar.c"
    output = work / "authored-sidecar.preprocessed.c"
    run([
        *flags(compiler, candidate, False), "-E", "-P", str(source),
        "-o", str(output),
    ], timeout=60)
    require(output.is_file() and output.stat().st_size <= 16 * 1024 * 1024,
            "preprocessed serializer source exceeds audit bound")
    try:
        active = output.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise RuntimeError(
            "preprocessed serializer source is not UTF-8"
        ) from error
    check_active_text(active)


def validate_jsonl(path: Path, expected: dict[str, object],
                   expected_keys: list[str]) -> None:
    data = path.read_bytes()
    require(len(data) == expected["length"], f"{path.name} length differs")
    require(sha256_bytes(data) == expected["sha256"],
            f"{path.name} digest differs")
    require(data.endswith(b"\n") and b"\r" not in data and b"\0" not in data,
            f"{path.name} framing differs")
    require(all(byte == 0x0A or 0x20 <= byte <= 0x7E for byte in data),
            f"{path.name} byte domain differs")
    lines = data.splitlines()
    require(len(lines) == expected["line_count"],
            f"{path.name} line count differs")
    for number, line in enumerate(lines):
        row = json.loads(line, object_pairs_hook=lambda pairs: pairs)
        require([key for key, _ in row] == expected_keys,
                f"{path.name} key order differs at line {number}")
        require(len({key for key, _ in row}) == len(row),
                f"{path.name} duplicate key at line {number}")
        canonical = json.dumps(dict(row), ensure_ascii=True, allow_nan=False,
                               separators=(",", ":")).encode("ascii")
        require(canonical == line,
                f"{path.name} canonical JSON differs at line {number}")


def verify_hash_vectors(oracle: dict[str, object]) -> None:
    nist = oracle["nist_sha256"]
    require(sha256_bytes(b"") == nist["empty"] and
            sha256_bytes(b"abc") == nist["abc"] and
            sha256_bytes(b"a" * 1_000_000) == nist["million_a"],
            "NIST SHA-256 vector differs")
    expected_domains = {
        "actions": bytes.fromhex("42424143543100"),
        "dice": bytes.fromhex("42424449453100"),
        "legal": bytes.fromhex("42424c45473100"),
    }
    for name, vectors in oracle["framed_hash_vectors"].items():
        for vector in vectors:
            preimage = bytes.fromhex(vector["preimage_hex"])
            require(preimage.startswith(expected_domains[name]),
                    f"{name} hash domain differs")
            require(len(preimage) == vector["length"] and
                    sha256_bytes(preimage) == vector["sha256"],
                    f"{name} independent hash vector differs")


def verify_abi(compiler: str, candidate: Path, trusted: Path,
               work: Path) -> None:
    good = work / "abi-good.o"
    run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-iquote", str(candidate / "tools"),
        "-idirafter", str(candidate / "engine" / "include"),
        "-c", str(trusted / "abi_probe.c"), "-o", str(good),
    ], timeout=30)
    header = (candidate / "tools" / "authored_sidecar.h").read_text(
        encoding="utf-8")
    old = "const ad_bbs_record* records, size_t record_count,"
    new = "const ad_bbs_record* records, uint32_t record_count,"
    require(header.count(old) == 1, "ABI fixture anchor differs")
    bad_dir = work / "abi-malicious"
    bad_dir.mkdir()
    (bad_dir / "authored_sidecar.h").write_text(
        header.replace(old, new), encoding="utf-8")
    run([
        compiler, "-std=c11", "-Wall", "-Wextra", "-Werror",
        "-iquote", str(bad_dir),
        "-iquote", str(candidate / "tools"),
        "-idirafter", str(candidate / "engine" / "include"),
        "-c", str(trusted / "abi_probe.c"),
        "-o", str(work / "abi-bad.o"),
    ], timeout=30, expect_success=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--compiler", default=os.environ.get("CC", "clang"))
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    trusted = Path(__file__).resolve().parent
    authority_root = trusted.parent.parent
    oracle_path = trusted.parent / "authored_sidecar_oracle.json"
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    require(oracle["schema"] == "bloodbowl-authored-sidecar-authority-v1",
            "unknown sidecar authority schema")
    require(oracle["record_count"] == 26, "sidecar proof count differs")
    for relative, expected_hash in oracle["authority_files"].items():
        path = authority_root / relative
        require(path.is_file() and not path.is_symlink(),
                f"missing or symlinked authority file: {relative}")
        require(sha256(path) == expected_hash,
                f"authority file digest differs: {relative}")
    header = candidate / str(oracle["production_header"])
    require(header.is_file() and not header.is_symlink(),
            "candidate sidecar header is missing or symlinked")
    require(sha256(header) == oracle["authority_files"][oracle["production_header"]],
            "candidate sidecar public ABI differs")
    compiler = shutil.which(args.compiler)
    require(compiler is not None, f"compiler not found: {args.compiler}")
    verify_hash_vectors(oracle)
    run([
        sys.executable, str(trusted / "source_check.py"), str(candidate),
        str(oracle_path),
    ], timeout=30)
    run([
        sys.executable, str(trusted / "fixture_selftest.py"), str(oracle_path),
        str(trusted / "malicious_fixtures.json"),
    ], timeout=30)
    run([
        sys.executable, str(trusted / "isolation_selftest.py"),
    ], timeout=30)

    expected_root = trusted / "expected"
    validate_jsonl(expected_root / "records.jsonl",
                   oracle["outputs"]["records.jsonl"], oracle["record_keys"])
    validate_jsonl(expected_root / "recipes.jsonl",
                   oracle["outputs"]["recipes.jsonl"], oracle["recipe_keys"])
    with tempfile.TemporaryDirectory(prefix="authored-sidecar-verify-") as raw:
        work = Path(raw)
        transformed_expected = {
            label: build_transformed_expected(expected_root, work, label)
            for label in ("actions-hash", "dice-hash", "legal-hash")
        }
        verify_synthetic_mutation_flags(compiler, candidate, work)
        verify_serializer_export_audit_selftest(compiler, candidate, work)
        verify_linked_candidate_exports(compiler, candidate, trusted, work)
        verify_abi(compiler, candidate, trusted, work)
        fact_outputs: list[bytes] = []
        for label, sanitizer in (("optimized", False), ("sanitized", True)):
            binary = work / f"facts-{label}"
            compile_fact_probe(compiler, candidate, trusted, binary, sanitizer)
            result = run([str(binary)], timeout=120)
            facts = result.stdout
            expected_fact = oracle["fact_corpus"]
            require(len(facts) == expected_fact["length"] and
                    sha256_bytes(facts) == expected_fact["sha256"],
                    f"{label} fact corpus differs")
            fact_outputs.append(facts)
            fact_path = work / f"facts-{label}.bin"
            fact_path.write_bytes(facts)
            generated = work / f"oracle-{label}"
            run([
                sys.executable, str(trusted / "build_oracle.py"),
                str(fact_path), str(generated),
            ], timeout=30)
            for name in ("records.jsonl", "recipes.jsonl"):
                require((generated / name).read_bytes() ==
                        (expected_root / name).read_bytes(),
                        f"{label} generated {name} differs")
            generated_oracle = json.loads(
                (generated / "oracle.unsealed.json").read_text(encoding="utf-8")
            )
            expected_oracle = dict(oracle)
            expected_oracle["authority_files"] = {}
            require(generated_oracle == expected_oracle,
                    f"{label} regenerated oracle metadata differs")
        require(fact_outputs[0] == fact_outputs[1],
                "optimized and sanitizer fact corpora differ")

        for label, sanitizer in (("optimized", False), ("sanitized", True)):
            compile_serializer_probe_object(
                compiler, candidate, trusted,
                work / f"serializer-probe-{label}.o", sanitizer)

        serializer_source = candidate / str(oracle["production_source"])
        if serializer_source.is_file():
            verify_preprocessed_source(compiler, candidate, work)
            verify_serializer_object_symbols(compiler, candidate, work)
            for label, sanitizer in (("optimized", False), ("sanitized", True)):
                binary = work / f"serializer-{label}"
                compile_serializer_probe(
                    compiler, candidate, trusted, binary, sanitizer)
                run([
                    str(binary), str(expected_root / "records.jsonl"),
                    str(expected_root / "recipes.jsonl"),
                ], timeout=180)
            verify_public_derivation_mutations(
                compiler, candidate, trusted, work, expected_root,
                transformed_expected)

    print(f"authored sidecar authority verified: {candidate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
