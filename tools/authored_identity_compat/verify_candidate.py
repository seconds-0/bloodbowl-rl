#!/usr/bin/env python3
"""Verify one candidate tree against the immutable authored recipe oracle."""

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


ENGINE_SOURCES = (
    "bb_blockev.c",
    "bb_hooks.c",
    "bb_match.c",
    "bb_procgen.c",
    "bb_reachability.c",
    "bb_replay.c",
    "bb_rng.c",
    "bb_skills.c",
    "gen_skills.c",
    "gen_tables.c",
    "gen_teams.c",
    "proc_ball.c",
    "proc_block.c",
    "proc_match.c",
    "proc_move.c",
    "proc_table.c",
    "proc_test.c",
    "proc_ttm.c",
    "proc_turn.c",
    "skills_agility.c",
    "skills_core.c",
    "skills_devious_traits.c",
    "skills_mutation_passing.c",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(command: list[str], *, timeout: int, cwd: Path | None = None) -> None:
    process = subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    try:
        output, _ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        output, _ = process.communicate()
        raise RuntimeError(
            f"command exceeded {timeout}s: {' '.join(command)}\n{output}"
        )
    if process.returncode != 0:
        raise RuntimeError(
            f"command failed ({process.returncode}): {' '.join(command)}\n"
            f"{output}"
        )


def validate_file(path: Path, expected: dict[str, object]) -> None:
    require(path.is_file(), f"missing oracle output: {path.name}")
    require(path.stat().st_size == expected["length"],
            f"{path.name} length differs")
    require(sha256(path) == expected["sha256"],
            f"{path.name} digest differs")
    magic = expected.get("magic")
    if magic is not None:
        require(path.read_bytes()[:8] == str(magic).encode("ascii"),
                f"{path.name} magic differs")


def compile_probe(
    compiler: str,
    candidate: Path,
    trusted: Path,
    probe_name: str,
    binary: Path,
    sanitizer: bool,
) -> None:
    candidate_engine = candidate / "engine" / "src"
    actual = tuple(sorted(path.name for path in candidate_engine.glob("*.c")))
    require(actual == tuple(sorted(ENGINE_SOURCES)),
            "candidate engine source allowlist differs")
    flags = [
        "-std=c11",
        "-O1" if sanitizer else "-O2",
        "-g",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-fno-lto",
        f"-I{candidate / 'engine' / 'include'}",
        f"-I{candidate / 'tools'}",
    ]
    if sanitizer:
        flags.extend(("-fsanitize=address,undefined", "-fno-omit-frame-pointer"))
    sources = [
        trusted / probe_name,
        candidate / "tools" / "authored_drill.c",
        candidate / "tools" / "authored_identity.c",
        candidate / "tools" / "authored_writer_gates.c",
    ]
    sources.extend(candidate_engine / name for name in ENGINE_SOURCES)
    for source in sources:
        require(source.is_file(), f"missing compile input: {source}")
    run([compiler, *flags, *(str(path) for path in sources), "-o", str(binary)],
        timeout=60)


def compare_directories(left: Path, right: Path, names: object) -> None:
    for name in names:
        require((left / name).read_bytes() == (right / name).read_bytes(),
                f"sanitizer output differs for {name}")


def verify_writer_interposition(
    compiler: str, candidate: Path, trusted: Path, work: Path
) -> None:
    if not sys.platform.startswith("linux"):
        print("writer --wrap interposition deferred to required Linux CI")
        return
    binary = work / "writer-interpose-bin"
    link_map = work / "writer-interpose.map"
    engine = candidate / "engine" / "src"
    command = [
        compiler,
        "-std=c11",
        "-O2",
        "-g",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-fno-lto",
        f"-I{candidate / 'engine' / 'include'}",
        f"-I{candidate / 'tools'}",
        str(trusted / "writer_interpose_probe.c"),
        str(candidate / "tools" / "authored_drill.c"),
        str(candidate / "tools" / "authored_identity.c"),
        str(candidate / "tools" / "authored_writer_gates.c"),
        *(str(engine / name) for name in ENGINE_SOURCES),
        "-Wl,--wrap=ad_authored_fresh_admission_gate",
        "-Wl,--wrap=ad_authored_resumable_admission_gate",
        "-Wl,--wrap=ad_authored_continuation_gate",
        "-Wl,--wrap=fwrite",
        f"-Wl,-Map,{link_map}",
        "-o",
        str(binary),
    ]
    run(command, timeout=60)
    link_text = link_map.read_text(encoding="utf-8", errors="replace")
    for symbol in (
        "__wrap_ad_authored_fresh_admission_gate",
        "__wrap_ad_authored_resumable_admission_gate",
        "__wrap_ad_authored_continuation_gate",
        "ad_authored_fresh_admission_gate",
        "ad_authored_resumable_admission_gate",
        "ad_authored_continuation_gate",
        "__wrap_fwrite",
        "fwrite",
    ):
        require(symbol in link_text, f"link map lacks interposed symbol: {symbol}")
    run([str(binary)], timeout=60)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--compiler", default=os.environ.get("CC", "clang"))
    args = parser.parse_args()
    candidate = args.candidate.resolve()
    trusted = Path(__file__).resolve().parent
    fixture_path = trusted.parent / "authored_recipe_oracle.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    require(fixture["schema"] == "bloodbowl-authored-recipe-oracle-v1",
            "unknown authored oracle schema")
    require(fixture["proof_record_count"] == 26, "proof count differs")

    for relative, expected_hash in fixture["authority_files"].items():
        authority_path = trusted.parent.parent / relative
        require(authority_path.is_file(), f"missing authority file: {relative}")
        require(sha256(authority_path) == expected_hash,
                f"authority file digest differs: {relative}")

    compiler = shutil.which(args.compiler)
    require(compiler is not None, f"compiler not found: {args.compiler}")
    run([
        sys.executable,
        str(trusted / "ast_check.py"),
        str(candidate),
        str(fixture_path),
        str(trusted / "recipe_probe.c"),
        "--compiler",
        compiler,
    ], timeout=60)
    with tempfile.TemporaryDirectory(prefix="authored-identity-verify-") as raw:
        work = Path(raw)
        optimized_recipe = work / "recipe-opt"
        sanitized_recipe = work / "recipe-san"
        optimized_gate = work / "gate-opt"
        sanitized_gate = work / "gate-san"
        optimized_identity = work / "identity-opt"
        sanitized_identity = work / "identity-san"
        artifact = work / "artifact"
        for directory in (
            optimized_recipe,
            sanitized_recipe,
            optimized_gate,
            sanitized_gate,
            optimized_identity,
            sanitized_identity,
            artifact,
        ):
            directory.mkdir()

        recipe_opt_bin = work / "recipe-opt-bin"
        recipe_san_bin = work / "recipe-san-bin"
        compile_probe(compiler, candidate, trusted, "recipe_probe.c",
                      recipe_opt_bin, False)
        compile_probe(compiler, candidate, trusted, "recipe_probe.c",
                      recipe_san_bin, True)
        run([str(recipe_opt_bin), str(optimized_recipe)], timeout=60)
        run([str(recipe_san_bin), str(sanitized_recipe)], timeout=60)
        for name, expected in fixture["recipe_streams"].items():
            validate_file(optimized_recipe / name, expected)
        compare_directories(optimized_recipe, sanitized_recipe,
                            fixture["recipe_streams"])

        gate_opt_bin = work / "gate-opt-bin"
        gate_san_bin = work / "gate-san-bin"
        compile_probe(compiler, candidate, trusted, "oracle_probe.c",
                      gate_opt_bin, False)
        compile_probe(compiler, candidate, trusted, "oracle_probe.c",
                      gate_san_bin, True)
        run([str(gate_opt_bin), str(optimized_gate)], timeout=60)
        run([str(gate_san_bin), str(sanitized_gate)], timeout=60)
        gate_streams = fixture["gate_corpus"]["streams"]
        for name, expected in gate_streams.items():
            validate_file(optimized_gate / name, expected)
        compare_directories(optimized_gate, sanitized_gate, gate_streams)

        identity_opt_bin = work / "identity-opt-bin"
        identity_san_bin = work / "identity-san-bin"
        compile_probe(compiler, candidate, trusted, "identity_probe.c",
                      identity_opt_bin, False)
        compile_probe(compiler, candidate, trusted, "identity_probe.c",
                      identity_san_bin, True)
        run([str(identity_opt_bin), str(optimized_identity)], timeout=60)
        run([str(identity_san_bin), str(sanitized_identity)], timeout=60)
        validate_file(optimized_identity / "identity.bin",
                      fixture["identity_stream"])
        compare_directories(optimized_identity, sanitized_identity,
                            ("identity.bin",))

        artifact_bin = work / "artifact-bin"
        compile_probe(compiler, candidate, trusted, "artifact_probe.c",
                      artifact_bin, False)
        run([str(artifact_bin), str(artifact)], timeout=60)
        independent = artifact / "independent.bbs"
        writer = artifact / "writer.bbs"
        raw_body = artifact / "raw.bin"
        expected_artifact = fixture["artifact"]
        require(independent.read_bytes() == writer.read_bytes(),
                "public writer differs from independent A9 encoder")
        require(independent.stat().st_size == expected_artifact["bbs_length"],
                "A9 artifact length differs")
        require(sha256(independent) == expected_artifact["bbs_sha256"],
                "A9 artifact digest differs")
        require(raw_body.stat().st_size ==
                expected_artifact["raw_body_length"],
                "A9 raw body length differs")
        require(sha256(raw_body) == expected_artifact["raw_body_sha256"],
                "A9 raw body digest differs")

        negative_bin = work / "writer-negative-bin"
        compile_probe(compiler, candidate, trusted, "writer_negative_probe.c",
                      negative_bin, False)
        run([str(negative_bin)], timeout=60)

        verify_writer_interposition(compiler, candidate, trusted, work)

    print(f"authored identity compatibility verified: {candidate}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
