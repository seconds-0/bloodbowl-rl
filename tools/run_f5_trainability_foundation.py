#!/usr/bin/env python3
"""Produce non-authoritative evidence for the sealed F5 foundation."""

from __future__ import annotations

import argparse
from fractions import Fraction
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import shutil
import stat
import subprocess
import sys
import tempfile
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
SAFE_SYSTEM_PATH = (
    "/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin:/usr/local/sbin:"
    "/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/swift/usr/bin"
)
SAFE_PASSTHROUGH_ENV_NAMES = (
    "TMPDIR",
    "TMP",
    "TEMP",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
)
EVIDENCE_SCHEMA = "bloodbowl-f5-foundation-evidence-v1"
FIXTURE_ROLE = "f5-fixed-state-v1"
COMMANDS = (
    "build",
    "generate",
    "verify",
    "c-test",
    "reference",
    "enumerate",
    "random",
    "puffer-fresh-lifecycle",
)
PUFFER_COMMIT = "9836f0d2e78889c1aaf189c04d161b6fc61a9386"
FULL_BBS_SHA256 = (
    "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1"
)
F5_BBS_SHA256 = (
    "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71"
)
MATCH_SHA256 = (
    "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2"
)
TRACE_SHA256 = (
    "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300"
)
HEADER_SHA256 = (
    "a9f506a5440f55ce92febd0fdabd16ef3604f6d5dee4f05f0c896ac47c951760"
)
DEPENDENCY_REQUIREMENTS_SHA256 = (
    "010a1f6a785d9c7e7b421f345eeae10a177891fae7e56454111da18c0bed9aa6"
)
DEPENDENCY_IDENTITY_SCOPE = (
    "canonical-installed-distribution-name-version-snapshot;"
    "not-wheel-byte-lock"
)
DEFAULT_EDITABLE_PTH_NAME = "__editable__.pufferlib-4.0.0.pth"
DEFAULT_EDITABLE_FINDER_NAME = (
    "__editable___pufferlib_4_0_0_finder.py"
)
SEALED_EDITABLE_PTH_NAME = "pufferlib-editable.pth"
SEALED_SITE_BOOTSTRAP_LINE = (
    "import sys;sys.modules['sitecustomize']=sys\n"
)
RAYLIB_INPUTS = {
    ("darwin", "arm64"): {
        "directory": "raylib-5.5_macos",
        "archive_sha256":
            "930c67b676963c6cffbd965814664523081ecbf3d30fc9df4211d0064aa6ba39",
        "library_sha256":
            "5517f19555ce6e19540ac534bb5d5bf08ba45660d14642db4878f079a9f1b7da",
    },
    ("linux", "x86_64"): {
        "directory": "raylib-5.5_linux_amd64",
        "archive_sha256":
            "3d95ef03d5b38dfa55c0a16ca122d382134b078f0e5b270b52fe7eae0549c000",
        "library_sha256":
            "3323cbf14ec6e640e19d63e230e68c3a530be3e9a9d416435eab82160e9e9ccc",
    },
}
PRISTINE_PUFFER_NATIVE_INPUT_PATHS = tuple(
    sorted(
        {"raylib-archives"}
        | {value["directory"] for value in RAYLIB_INPUTS.values()}
    )
)
FOUNDATION_CFLAGS = (
    "-std=c11 -O2 -g -Wall -Wextra -Werror -Iengine/include"
)
SAFE_TRAJECTORIES = 721
SAFE_PROBABILITY_FRACTION = Fraction(4567, 9_227_468_800)
SAFE_PROBABILITY = 4.949352957985618e-7
SELECTED_PROBABILITY_FRACTION = Fraction(1, 1_476_395_008)
SELECTED_PROBABILITY = 6.773255088112571e-10
DEFAULT_RANDOM_SEED = 245
DEFAULT_RANDOM_EPISODES = 100_000
EXPECTED_RANDOM_BASELINE = {
    "schema": "bloodbowl-f5-random-baseline-v1",
    "seed": DEFAULT_RANDOM_SEED,
    "episodes": DEFAULT_RANDOM_EPISODES,
    "decisions": 800_000,
    "agent_steps": 1_600_000,
    "successes": 0,
    "tds_t1": 0,
    "early_terminals": 0,
    "illegal": 0,
    "collisions": 0,
    "dice": 472_158,
    "test_windows": 11_396,
    "fixture_resets": DEFAULT_RANDOM_EPISODES,
    "reward_totals": [0, 0],
    "episode_lengths": [0, 0, 0, 0, 0, 0, 0, DEFAULT_RANDOM_EPISODES],
}
PRISTINE_PUFFER_OWNED_PATHS = (
    "bloodbowl",
    "config/bloodbowl.ini",
    "ocean/bloodbowl",
    "src/exact_action_build_hash.h",
)
PUFFER_ENTRYPOINT_BODY = (
    b"import sys\n"
    b"from pufferlib.pufferl import main\n"
    b"if __name__ == '__main__':\n"
    b"    if sys.argv[0].endswith('.exe'):\n"
    b"        sys.argv[0] = sys.argv[0][:-4]\n"
    b"    sys.exit(main())\n"
)
PUFFER_ENTRYPOINT_NORMALIZED = (
    b"#!<puffer-python>\n" + PUFFER_ENTRYPOINT_BODY
)
PUFFER_INTERPRETER_PROBE = r"""
import json
import sys

result = {
    "implementation": sys.implementation.name,
    "platlibdir": sys.platlibdir,
    "version": ".".join(str(value) for value in sys.version_info[:3]),
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""
PUFFER_STARTUP_RUNTIME_PROBE = r"""
import json
import site
import sitecustomize
import sys

result = {
    "base_prefix": sys.base_prefix,
    "dont_write_bytecode": bool(sys.flags.dont_write_bytecode),
    "implementation": sys.implementation.name,
    "isolated": sys.flags.isolated,
    "no_site": sys.flags.no_site,
    "platlibdir": sys.platlibdir,
    "prefix": sys.prefix,
    "sitecustomize_is_sys": sitecustomize is sys,
    "sys_path": sys.path,
    "user_site_enabled": site.ENABLE_USER_SITE,
    "version": ".".join(str(value) for value in sys.version_info[:3]),
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""
PUFFER_DISTRIBUTION_PROBE = r"""
import importlib.metadata
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

root = Path(sys.argv[1]).resolve(strict=True)
distribution = importlib.metadata.distribution("pufferlib")
direct = json.loads(distribution.read_text("direct_url.json"))
parsed = urlparse(direct["url"])
if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
    raise SystemExit("pufferlib editable source is not a local file URL")
source = Path(unquote(parsed.path)).resolve(strict=True)
result = {
    "name": distribution.metadata["Name"],
    "version": distribution.version,
    "editable": direct.get("dir_info", {}).get("editable"),
    "source_matches_pinned_root": source == root,
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""
ORDINARY_QUALIFICATION_FIXTURE = {
    "enabled": 0,
    "role": "none",
    "schema": "none",
    "qualification_only": 0,
    "match_sha256": "unused",
    "bbs_sha256": "unused",
    "bundle_sha256": "unused",
    "bbs_source_id": 0,
    "authored_source_id": 0,
    "reference_trace_schema": "none",
    "reference_trace_sha256": "unused",
    "max_decisions": 0,
    "reward_contract": "none",
}
LIFECYCLE_COMMANDS = (
    (
        "ordinary-install",
        ["/bin/bash", "tools/install_puffer_env.sh", "<pinned-puffer-root>"],
        0,
    ),
    (
        "ordinary-cpu-build",
        [
            "/usr/bin/env",
            "CC=<resolved-puffer-cc>",
            "CXX=<resolved-puffer-cxx>",
            "/bin/bash",
            "./build.sh",
            "bloodbowl",
            "--cpu",
        ],
        0,
    ),
    (
        "ordinary-fast-build",
        [
            "/usr/bin/env",
            "CC=<resolved-puffer-cc>",
            "CXX=<resolved-puffer-cxx>",
            "/bin/bash",
            "./build.sh",
            "bloodbowl",
            "--fast",
        ],
        0,
    ),
    (
        "ordinary-check",
        [
            "/bin/bash",
            "tools/install_puffer_env.sh",
            "--check",
            "<pinned-puffer-root>",
        ],
        0,
    ),
    (
        "ordinary-module-none",
        [
            "<puffer-python>",
            "-B",
            "-I",
            "<ordinary-module-role-probe-v1>",
            "<source-tools>",
            "<pinned-puffer-root>",
        ],
        0,
    ),
    (
        "f5-check-rejects-ordinary",
        [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "--check",
            "<pinned-puffer-root>",
        ],
        1,
    ),
    (
        "f5-stage",
        [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "<pinned-puffer-root>",
        ],
        0,
    ),
    (
        "f5-cpu-rebuild",
        [
            "/usr/bin/env",
            "CC=<resolved-puffer-cc>",
            "CXX=<resolved-puffer-cxx>",
            "/bin/bash",
            "./build.sh",
            "bloodbowl",
            "--cpu",
        ],
        0,
    ),
    (
        "f5-check",
        [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "--check",
            "<pinned-puffer-root>",
        ],
        0,
    ),
    (
        "f5-install-rejects-already-staged",
        [
            "/bin/bash",
            "tools/install_f5_trainability_env.sh",
            "<pinned-puffer-root>",
        ],
        1,
    ),
    (
        "f5-module-proof",
        [
            "<puffer-python>",
            "-B",
            "-I",
            "tools/check_f5_trainability_module.py",
            "--puffer-root",
            "<pinned-puffer-root>",
            "--output",
            "puffer-module.json",
        ],
        0,
    ),
    (
        "ordinary-install-rejects-f5",
        ["/bin/bash", "tools/install_puffer_env.sh", "<pinned-puffer-root>"],
        1,
    ),
    (
        "production-ablation-rejects-f5",
        [
            "/bin/bash",
            "<launcher-projection>/tools/run_reward_ablation.sh",
        ],
        1,
    ),
    (
        "production-screen-rejects-f5",
        [
            "/bin/bash",
            "<launcher-projection>/tools/run_reward_screen.sh",
        ],
        1,
    ),
)

ORDINARY_MODULE_PROBE = r"""
import hashlib
import json
import sys
from pathlib import Path

tools = Path(sys.argv[1]).resolve(strict=True)
root = Path(sys.argv[2]).resolve(strict=True)
sys.path.insert(0, str(tools))
import state_bank_contract as contract
sys.path.insert(0, str(root))
from pufferlib import _C

module = Path(_C.__file__).resolve(strict=True)
relative_module = module.relative_to(root).as_posix()
payload = module.read_bytes()
result = {
    "schema": "bloodbowl-f5-ordinary-module-v1",
    "module_path": relative_module,
    "module_sha256": hashlib.sha256(payload).hexdigest(),
    "module_contract": {
        "env_name": getattr(_C, "env_name", None),
        "gpu": int(bool(getattr(_C, "gpu", False))),
        "observation_abi": getattr(_C, "observation_abi", None),
        "observation_version": getattr(_C, "observation_version", None),
        "action_abi": getattr(_C, "action_abi", None),
        "rollout_transition_contract": getattr(
            _C, "rollout_transition_contract", None),
        "entropy_schedule_contract": getattr(
            _C, "entropy_schedule_contract", None),
        "environment_config_schema": getattr(
            _C, "environment_config_schema", None),
        "strict_env_config_testing": getattr(
            _C, "strict_env_config_testing", None),
        "exact_action_source_sha256": getattr(
            _C, "exact_action_source_hash", None),
        "environment_source_sha256": getattr(
            _C, "environment_source_hash", None),
    },
    "qualification_fixture": contract.qualification_fixture_from_module(_C),
    "state_bank": contract.contract_from_module(_C),
}
print(json.dumps(
    result,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=True,
    allow_nan=False,
))
"""

GENERATOR = ROOT / "build/f5_trainability_foundation"
C_TEST = ROOT / "build/puffer_f5_trainability_tests"
DIAGNOSTICS = ROOT / "build/f5_trainability_diagnostics"
MODULE_CHECKER = ROOT / "tools/check_f5_trainability_module.py"
ENV_CONFIG = ROOT / "training/f5_trainability_env.json"
CHECKED_FIXTURE_HEADER = (
    ROOT / "puffer/bloodbowl/f5_trainability_fixture.generated.h"
)


class FoundationRunError(RuntimeError):
    """Foundation evidence could not be produced without ambiguity."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        + "\n"
    ).encode("ascii")


def atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def run_checked(
    command: list[str],
    *,
    cwd: Path = ROOT,
    timeout: int = 300,
    capture: bool = True,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    if environment is None:
        environment = isolated_python_environment()
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=capture,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FoundationRunError(
            f"command could not run: {command!r}: {exc}"
        ) from exc
    if completed.returncode != 0:
        stdout = completed.stdout[-4000:] if completed.stdout else ""
        stderr = completed.stderr[-4000:] if completed.stderr else ""
        raise FoundationRunError(
            f"command failed ({completed.returncode}): {command!r}; "
            f"stdout={stdout!r}; stderr={stderr!r}"
        )
    return completed


def foundation_compiler() -> Path:
    raw = shutil.which("cc", path=SAFE_SYSTEM_PATH)
    if raw is None:
        raise FoundationRunError("the sealed foundation compiler cc is absent")
    try:
        compiler = Path(raw).resolve(strict=True)
    except OSError as exc:
        raise FoundationRunError(
            f"cannot resolve the sealed foundation compiler: {exc}"
        ) from exc
    if not compiler.is_file():
        raise FoundationRunError(
            f"sealed foundation compiler is not a file: {compiler}"
        )
    return compiler


def foundation_build_environment() -> dict[str, str]:
    environment = isolated_python_environment()
    environment["LC_ALL"] = "C"
    return environment


def isolated_python_environment() -> dict[str, str]:
    environment = {
        name: os.environ[name]
        for name in SAFE_PASSTHROUGH_ENV_NAMES
        if name in os.environ
    }
    environment["PATH"] = SAFE_SYSTEM_PATH
    environment["LC_ALL"] = "C"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["GIT_CONFIG_GLOBAL"] = "/dev/null"
    environment["GIT_CONFIG_NOSYSTEM"] = "1"
    return environment


def puffer_build_toolchain() -> dict[str, Any]:
    if (
        (sys.platform, platform.machine().lower())
        not in {("darwin", "arm64"), ("linux", "x86_64")}
    ):
        raise FoundationRunError(
            "fresh Puffer lifecycle supports only Darwin arm64 or Linux x86_64"
        )
    result: dict[str, Any] = {
        "schema": "bloodbowl-f5-puffer-build-toolchain-v1",
        "platform": sys.platform,
        "machine": platform.machine().lower(),
    }
    for key, command in (("cc", "clang"), ("cxx", "clang++")):
        raw = shutil.which(command, path=SAFE_SYSTEM_PATH)
        if raw is None:
            raise FoundationRunError(
                f"sealed Puffer build compiler is absent: {command}"
            )
        executable = Path(raw).resolve(strict=True)
        version = run_checked(
            [str(executable), "--version"], timeout=30
        ).stdout.splitlines()
        target = run_checked(
            [str(executable), "-dumpmachine"], timeout=30
        ).stdout.strip()
        if not version or not target or "\n" in target:
            raise FoundationRunError(
                f"sealed Puffer compiler identity is incomplete: {executable}"
            )
        result[key] = {
            "path": str(executable),
            "sha256": sha256_file(executable),
            "version": version[0],
            "target": target,
        }
    return result


def puffer_lifecycle_environment(
    puffer_root: Path, toolchain: dict[str, Any]
) -> dict[str, str]:
    environment = foundation_build_environment()
    for name in (
        "EXTRA_CFLAGS",
        "PRECISION",
        "PUFFER_STRICT_ENV_CONFIG_TESTING",
        "CUDA_HOME",
        "CUDA_PATH",
        "NVCC_ARCH",
    ):
        environment.pop(name, None)
    environment["PATH"] = SAFE_SYSTEM_PATH
    environment["PUFFER_INSTALL_PYTHON"] = str(
        Path(sys.executable).resolve(strict=True)
    )
    environment["PUFFER_BUILD_PYTHON"] = str(
        puffer_root / ".venv/bin/python"
    )
    environment["CC"] = toolchain["cc"]["path"]
    environment["CXX"] = toolchain["cxx"]["path"]
    return environment


def _startup_regular_payload(
    path: Path, *, maximum: int, label: str
) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise FoundationRunError(f"cannot inspect {label}: {exc}") from exc
    if (
        path.is_symlink()
        or not stat.S_ISREG(metadata.st_mode)
        or metadata.st_nlink != 1
        or metadata.st_size <= 0
        or metadata.st_size > maximum
    ):
        raise FoundationRunError(
            f"{label} is not a bounded singly linked regular file"
        )
    try:
        return path.read_bytes()
    except OSError as exc:
        raise FoundationRunError(f"cannot read {label}: {exc}") from exc


def _puffer_site_packages(puffer_root: Path) -> Path:
    venv = puffer_root / ".venv"
    relative_directories = (
        ".",
        "bin",
        "lib",
        "lib/python3.12",
        "lib/python3.12/site-packages",
    )
    for relative in relative_directories:
        directory = venv if relative == "." else venv / relative
        try:
            metadata = directory.lstat()
        except OSError as exc:
            raise FoundationRunError(
                f"cannot inspect Puffer venv directory {relative}: {exc}"
            ) from exc
        if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise FoundationRunError(
                f"Puffer venv directory {relative} is not a real directory"
            )
        try:
            directory.resolve(strict=True).relative_to(
                venv.resolve(strict=True)
            )
        except (OSError, ValueError) as exc:
            raise FoundationRunError(
                f"Puffer venv directory {relative} escaped its root: {exc}"
            ) from exc
    site_packages = venv / "lib/python3.12/site-packages"
    return site_packages


def _puffer_pyvenv_input(puffer_root: Path) -> dict[str, Any]:
    config_path = puffer_root / ".venv/pyvenv.cfg"
    payload = _startup_regular_payload(
        config_path, maximum=4096, label="Puffer pyvenv.cfg"
    )
    try:
        text = payload.decode("utf-8")
    except UnicodeError as exc:
        raise FoundationRunError(
            f"Puffer pyvenv.cfg is not UTF-8: {exc}"
        ) from exc
    values: dict[str, str] = {}
    for line in text.splitlines():
        if " = " not in line:
            raise FoundationRunError(
                "Puffer pyvenv.cfg contains a noncanonical line"
            )
        key, value = line.split(" = ", 1)
        if not key or key in values or not value:
            raise FoundationRunError(
                "Puffer pyvenv.cfg contains duplicate/empty fields"
            )
        values[key] = value
    expected_keys = {
        "home",
        "include-system-site-packages",
        "version",
        "executable",
        "command",
    }
    if set(values) != expected_keys:
        raise FoundationRunError(
            "Puffer pyvenv.cfg field set differs"
        )
    if values["include-system-site-packages"] != "false":
        raise FoundationRunError(
            "Puffer venv must exclude system site-packages"
        )
    version_parts = values["version"].split(".")
    if (
        len(version_parts) != 3
        or version_parts[:2] != ["3", "12"]
        or not version_parts[2].isdigit()
    ):
        raise FoundationRunError(
            "Puffer pyvenv.cfg version is not CPython 3.12"
        )
    try:
        configured_executable = Path(
            values["executable"]
        ).resolve(strict=True)
        configured_home_python = (
            Path(values["home"]) / "python3.12"
        ).resolve(strict=True)
        actual_executable = (
            puffer_root / ".venv/bin/python"
        ).resolve(strict=True)
    except OSError as exc:
        raise FoundationRunError(
            f"Puffer pyvenv.cfg base interpreter cannot resolve: {exc}"
        ) from exc
    if (
        configured_executable != actual_executable
        or configured_home_python != actual_executable
    ):
        raise FoundationRunError(
            "Puffer pyvenv.cfg base interpreter differs from venv Python"
        )
    try:
        runtime_payload = run_checked(
            [
                str(puffer_root / ".venv/bin/python"),
                "-B",
                "-I",
                "-S",
                "-c",
                PUFFER_INTERPRETER_PROBE,
            ],
            cwd=puffer_root,
            timeout=30,
        ).stdout.encode("ascii")
        runtime = json.loads(runtime_payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationRunError(
            f"sealed Puffer interpreter probe is malformed: {exc}"
        ) from exc
    expected_runtime = {
        "implementation": "cpython",
        "platlibdir": "lib",
        "version": values["version"],
    }
    if (
        runtime_payload != canonical_json(runtime)
        or runtime != expected_runtime
    ):
        raise FoundationRunError(
            "Puffer interpreter must be exact CPython 3.12 with "
            f"platlibdir=lib: {runtime!r}"
        )
    return {
        "path": ".venv/pyvenv.cfg",
        "bytes": len(payload),
        "sha256": sha256_bytes(payload),
        "include_system_site_packages": False,
        "version": values["version"],
        "implementation": runtime["implementation"],
        "platlibdir": runtime["platlibdir"],
        "base_python": str(actual_executable),
        "base_python_sha256": sha256_file(actual_executable),
    }


def _puffer_startup_entry_sets(
    site_packages: Path,
) -> tuple[set[str], set[str], set[str]]:
    try:
        names = {entry.name for entry in os.scandir(site_packages)}
    except OSError as exc:
        raise FoundationRunError(
            f"cannot enumerate Puffer site-packages: {exc}"
        ) from exc
    pth_names = {name for name in names if name.endswith(".pth")}
    forbidden = {
        name
        for name in names
        if (
            name.endswith(".egg-link")
            or name.startswith("sitecustomize")
            or name.startswith("usercustomize")
        )
    }
    finder_names = {
        name
        for name in names
        if name.startswith("__editable___pufferlib_4_0_0_finder")
    }
    cache = site_packages / "__pycache__"
    if os.path.lexists(cache):
        try:
            cache_metadata = cache.lstat()
        except OSError as exc:
            raise FoundationRunError(
                f"cannot inspect Puffer startup bytecode cache: {exc}"
            ) from exc
        if cache.is_symlink() or not stat.S_ISDIR(cache_metadata.st_mode):
            raise FoundationRunError(
                "Puffer startup bytecode cache is not a real directory"
            )
        try:
            finder_names.update(
                f"__pycache__/{entry.name}"
                for entry in os.scandir(cache)
                if entry.name.startswith(
                    "__editable___pufferlib_4_0_0_finder"
                )
            )
        except OSError as exc:
            raise FoundationRunError(
                f"cannot enumerate Puffer startup bytecode cache: {exc}"
            ) from exc
    return pth_names, forbidden, finder_names


def _puffer_startup_runtime_input(
    puffer_root: Path,
    pyvenv: dict[str, Any],
    site_packages: Path,
) -> dict[str, Any]:
    try:
        runtime_payload = run_checked(
            [
                str(puffer_root / ".venv/bin/python"),
                "-B",
                "-I",
                "-c",
                PUFFER_STARTUP_RUNTIME_PROBE,
            ],
            cwd=puffer_root,
            timeout=30,
        ).stdout.encode("ascii")
        runtime = json.loads(runtime_payload)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationRunError(
            f"sealed Puffer startup runtime probe is malformed: {exc}"
        ) from exc
    expected_keys = {
        "base_prefix",
        "dont_write_bytecode",
        "implementation",
        "isolated",
        "no_site",
        "platlibdir",
        "prefix",
        "sitecustomize_is_sys",
        "sys_path",
        "user_site_enabled",
        "version",
    }
    if (
        runtime_payload != canonical_json(runtime)
        or not isinstance(runtime, dict)
        or set(runtime) != expected_keys
    ):
        raise FoundationRunError(
            "sealed Puffer startup runtime receipt is noncanonical"
        )
    expected_scalars = {
        "dont_write_bytecode": True,
        "implementation": pyvenv["implementation"],
        "isolated": 1,
        "no_site": 0,
        "platlibdir": pyvenv["platlibdir"],
        "sitecustomize_is_sys": True,
        "user_site_enabled": False,
        "version": pyvenv["version"],
    }
    for key, expected in expected_scalars.items():
        if type(runtime[key]) is not type(expected) or runtime[key] != expected:
            raise FoundationRunError(
                "sealed Puffer startup runtime scalar differs: "
                f"{key}={runtime[key]!r}"
            )
    if (
        not isinstance(runtime["base_prefix"], str)
        or not isinstance(runtime["prefix"], str)
    ):
        raise FoundationRunError(
            "sealed Puffer startup prefixes are not strings"
        )
    try:
        base_prefix = Path(runtime["base_prefix"]).resolve(strict=True)
        prefix = Path(runtime["prefix"]).resolve(strict=True)
        expected_prefix = (puffer_root / ".venv").resolve(strict=True)
    except OSError as exc:
        raise FoundationRunError(
            f"sealed Puffer startup prefixes cannot resolve: {exc}"
        ) from exc
    if prefix != expected_prefix:
        raise FoundationRunError(
            "sealed Puffer startup prefix differs from the prepared venv"
        )
    sys_path = runtime["sys_path"]
    if (
        not isinstance(sys_path, list)
        or not sys_path
        or any(not isinstance(item, str) or not item for item in sys_path)
    ):
        raise FoundationRunError(
            "sealed Puffer startup sys.path is not a nonempty string list"
        )
    exact_root = str(puffer_root)
    exact_site_packages = str(site_packages)
    if (
        sys_path.count(exact_root) != 1
        or sys_path.count(exact_site_packages) != 1
    ):
        raise FoundationRunError(
            "sealed Puffer startup sys.path does not contain the exact "
            "Puffer root and venv site-packages once"
        )
    for item in sys_path:
        if item in {exact_root, exact_site_packages}:
            continue
        candidate = Path(item)
        if not candidate.is_absolute():
            raise FoundationRunError(
                f"sealed Puffer startup has a relative sys.path entry: {item!r}"
            )
        try:
            candidate.resolve(strict=False).relative_to(base_prefix)
        except ValueError as exc:
            raise FoundationRunError(
                "sealed Puffer startup imported a path outside the trusted "
                f"base stdlib, venv, and pinned root: {item!r}"
            ) from exc
    return {
        "schema": "bloodbowl-f5-python-startup-runtime-v1",
        "base_prefix": str(base_prefix),
        "prefix": str(prefix),
        "implementation": runtime["implementation"],
        "version": runtime["version"],
        "platlibdir": runtime["platlibdir"],
        "isolated": runtime["isolated"],
        "no_site": runtime["no_site"],
        "dont_write_bytecode": runtime["dont_write_bytecode"],
        "user_site_enabled": runtime["user_site_enabled"],
        "sitecustomize_is_sys": runtime["sitecustomize_is_sys"],
        "sys_path": sys_path,
    }


def puffer_python_startup_input(puffer_root: Path) -> dict[str, Any]:
    if "\n" in str(puffer_root) or "\r" in str(puffer_root):
        raise FoundationRunError(
            "Puffer root cannot be represented as one sealed path-hook line"
        )
    site_packages = _puffer_site_packages(puffer_root)
    pth_names, forbidden, finder_names = _puffer_startup_entry_sets(
        site_packages
    )
    if pth_names != {SEALED_EDITABLE_PTH_NAME}:
        raise FoundationRunError(
            "Puffer executable/path startup hooks are not exactly sealed: "
            f"pth={sorted(pth_names)!r}"
        )
    if forbidden or finder_names:
        raise FoundationRunError(
            "Puffer site-packages contains executable startup overrides: "
            f"forbidden={sorted(forbidden)!r}, "
            f"finder={sorted(finder_names)!r}"
        )
    pth = site_packages / SEALED_EDITABLE_PTH_NAME
    payload = _startup_regular_payload(
        pth, maximum=4096, label="sealed Puffer editable path hook"
    )
    expected_payload = (
        SEALED_SITE_BOOTSTRAP_LINE + str(puffer_root) + "\n"
    ).encode("utf-8")
    if payload != expected_payload:
        raise FoundationRunError(
            "sealed Puffer editable path hook points outside the pinned root"
        )
    relative = pth.relative_to(puffer_root).as_posix()
    pyvenv = _puffer_pyvenv_input(puffer_root)
    return {
        "schema": "bloodbowl-f5-python-startup-input-v1",
        "pyvenv": pyvenv,
        "site_packages":
            ".venv/lib/python3.12/site-packages",
        "pth_path": relative,
        "pth_bytes": len(payload),
        "pth_sha256": sha256_bytes(payload),
        "executable_pth_files": [relative],
        "base_sitecustomize_blocked": True,
        "sitecustomize_entries": [],
        "editable_finder_entries": [],
        "runtime": _puffer_startup_runtime_input(
            puffer_root, pyvenv, site_packages
        ),
    }


def seal_puffer_python_startup(puffer_root: Path) -> dict[str, Any]:
    site_packages = _puffer_site_packages(puffer_root)
    # Validate the interpreter trust root before touching any startup file.
    # In particular, a malformed pyvenv.cfg must fail without partially
    # migrating the caller's prepared environment.
    _puffer_pyvenv_input(puffer_root)
    sealed = site_packages / SEALED_EDITABLE_PTH_NAME
    if os.path.lexists(sealed):
        return puffer_python_startup_input(puffer_root)

    pth_names, forbidden, finder_names = _puffer_startup_entry_sets(
        site_packages
    )
    expected_pth_sets = (
        {DEFAULT_EDITABLE_PTH_NAME},
        {"distutils-precedence.pth", DEFAULT_EDITABLE_PTH_NAME},
    )
    allowed_finder = {DEFAULT_EDITABLE_FINDER_NAME}
    allowed_finder.update(
        name for name in finder_names if name.startswith("__pycache__/")
    )
    if (
        pth_names not in expected_pth_sets
        or forbidden
        or finder_names - allowed_finder
        or DEFAULT_EDITABLE_FINDER_NAME not in finder_names
    ):
        raise FoundationRunError(
            "prepared Puffer venv has unknown executable startup hooks: "
            f"pth={sorted(pth_names)!r}, "
            f"forbidden={sorted(forbidden)!r}, "
            f"finder={sorted(finder_names)!r}"
        )

    editable_path = site_packages / DEFAULT_EDITABLE_PTH_NAME
    validated_payloads = {
        editable_path: _startup_regular_payload(
            editable_path,
            maximum=4096,
            label="default Puffer editable startup hook",
        )
    }
    finder_path = site_packages / DEFAULT_EDITABLE_FINDER_NAME
    validated_payloads[finder_path] = _startup_regular_payload(
        finder_path,
        maximum=16 << 10,
        label="default Puffer editable finder",
    )

    paths_to_remove = [editable_path, finder_path]
    distutils_path = site_packages / "distutils-precedence.pth"
    if "distutils-precedence.pth" in pth_names:
        validated_payloads[distutils_path] = _startup_regular_payload(
            distutils_path,
            maximum=4096,
            label="default distutils startup hook",
        )
        paths_to_remove.append(distutils_path)
    cached_paths = []
    for relative in sorted(
        name for name in finder_names if name.startswith("__pycache__/")
    ):
        cached = site_packages / relative
        validated_payloads[cached] = _startup_regular_payload(
            cached,
            maximum=1 << 20,
            label="default Puffer editable finder bytecode",
        )
        cached_paths.append(cached)

    migration_paths = paths_to_remove + cached_paths
    snapshots: list[tuple[Path, Path, bytes, int]] = []
    for path in migration_paths:
        quarantine = path.with_name(
            f".{path.name}.f5-startup-quarantine"
        )
        if os.path.lexists(quarantine):
            raise FoundationRunError(
                f"prepared Puffer venv has stale startup quarantine: "
                f"{quarantine.relative_to(puffer_root)}"
            )
        snapshots.append(
            (
                path,
                quarantine,
                validated_payloads[path],
                stat.S_IMODE(path.lstat().st_mode),
            )
        )

    # Rename legacy hooks out of Python's startup namespace, then publish and
    # validate the controlled bootstrap/path hook. Any ordinary filesystem
    # exception restores
    # every original path byte-for-byte, including files whose quarantine was
    # already removed during cleanup.
    try:
        for path, quarantine, _, _ in snapshots:
            os.replace(path, quarantine)
        atomic_write(
            sealed,
            (
                SEALED_SITE_BOOTSTRAP_LINE + str(puffer_root) + "\n"
            ).encode("utf-8"),
        )
        receipt = puffer_python_startup_input(puffer_root)
        for _, quarantine, _, _ in snapshots:
            os.unlink(quarantine)
        return receipt
    except Exception as exc:
        rollback_errors: list[str] = []
        if os.path.lexists(sealed):
            try:
                os.unlink(sealed)
            except OSError as rollback_exc:
                rollback_errors.append(
                    f"cannot remove sealed hook: {rollback_exc}"
                )
        for path, quarantine, payload, mode in reversed(snapshots):
            try:
                if os.path.lexists(quarantine):
                    if os.path.lexists(path):
                        raise OSError(
                            "original and quarantine both exist"
                        )
                    os.replace(quarantine, path)
                elif not os.path.lexists(path):
                    atomic_write(path, payload)
                    os.chmod(path, mode)
                restored = _startup_regular_payload(
                    path,
                    maximum=max(len(payload), 1),
                    label="restored Puffer startup input",
                )
                if restored != payload:
                    raise OSError("restored payload differs")
            except OSError as rollback_exc:
                rollback_errors.append(
                    f"cannot restore {path.name}: {rollback_exc}"
                )
        if rollback_errors:
            raise FoundationRunError(
                "Puffer startup migration failed and rollback was "
                f"incomplete: {rollback_errors!r}"
            ) from exc
        if isinstance(exc, FoundationRunError):
            raise
        raise FoundationRunError(
            f"Puffer startup migration failed without mutation: {exc}"
        ) from exc


def puffer_raylib_input(puffer_root: Path) -> dict[str, Any]:
    expected = RAYLIB_INPUTS.get(
        (sys.platform, platform.machine().lower())
    )
    if expected is None:
        raise FoundationRunError("unsupported Raylib build-input platform")
    archive_directory = puffer_root / "raylib-archives"
    extracted_directory = puffer_root / expected["directory"]
    for directory, label in (
        (archive_directory, "Raylib archive cache"),
        (extracted_directory, "Raylib extracted input"),
    ):
        try:
            metadata = directory.lstat()
        except OSError as exc:
            raise FoundationRunError(
                f"cannot inspect {label}: {exc}"
            ) from exc
        if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
            raise FoundationRunError(f"{label} is not a real directory")

    archive_relative = (
        f"raylib-archives/{expected['directory']}.tar.gz"
    )
    library_relative = f"{expected['directory']}/lib/libraylib.a"
    identities: dict[str, tuple[int, str]] = {}
    for relative, expected_sha256, label in (
        (archive_relative, expected["archive_sha256"], "Raylib archive"),
        (library_relative, expected["library_sha256"], "Raylib library"),
    ):
        path = puffer_root / relative
        try:
            metadata = path.lstat()
        except OSError as exc:
            raise FoundationRunError(
                f"cannot inspect pinned {label}: {exc}"
            ) from exc
        if (
            path.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_nlink != 1
            or metadata.st_size <= 0
        ):
            raise FoundationRunError(
                f"pinned {label} differs from the platform pin"
            )
        observed_sha256 = sha256_file(path)
        if observed_sha256 != expected_sha256:
            raise FoundationRunError(
                f"pinned {label} differs from the platform pin"
            )
        identities[label] = (metadata.st_size, observed_sha256)
    return {
        "schema": "bloodbowl-f5-raylib-input-v2",
        "release": "5.5",
        "directory": expected["directory"],
        "archive_path": archive_relative,
        "archive_bytes": identities["Raylib archive"][0],
        "archive_sha256": identities["Raylib archive"][1],
        "library_path": library_relative,
        "library_bytes": identities["Raylib library"][0],
        "library_sha256": identities["Raylib library"][1],
    }


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_fresh_puffer_start(puffer_root: Path) -> dict[str, Any]:
    if Path(
        git_output(puffer_root, "rev-parse", "--show-toplevel")
    ).resolve(strict=True) != puffer_root:
        raise FoundationRunError(
            "Puffer root is not the pinned Git worktree root"
        )
    commit = git_output(puffer_root, "rev-parse", "HEAD")
    if commit != PUFFER_COMMIT:
        raise FoundationRunError(
            f"Puffer HEAD is {commit}; expected {PUFFER_COMMIT}"
        )
    status = git_output(
        puffer_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).splitlines()
    if status:
        raise FoundationRunError(
            "fresh Puffer lifecycle requires a pristine pinned checkout; "
            f"status={status!r}"
        )
    present = [
        relative
        for relative in PRISTINE_PUFFER_OWNED_PATHS
        if os.path.lexists(puffer_root / relative)
    ]
    compiled_modules = sorted(
        path.relative_to(puffer_root).as_posix()
        for path in (puffer_root / "pufferlib").glob("_C*")
        if os.path.lexists(path)
    )
    if present or compiled_modules:
        raise FoundationRunError(
            "fresh Puffer lifecycle found pre-existing ordinary/F5 artifacts; "
            f"owned={present!r}, modules={compiled_modules!r}"
        )
    try:
        native_inputs = sorted(
            entry.name
            for entry in os.scandir(puffer_root)
            if entry.name.startswith("raylib")
        )
    except OSError as exc:
        raise FoundationRunError(
            f"cannot inspect pristine native build inputs: {exc}"
        ) from exc
    if native_inputs:
        raise FoundationRunError(
            "fresh Puffer lifecycle found pre-existing ignored native "
            f"build inputs: {native_inputs!r}"
        )
    python = puffer_root / ".venv/bin/python"
    if not python.is_file() or not os.access(python, os.X_OK):
        raise FoundationRunError(
            "fresh Puffer lifecycle requires a prepared .venv/bin/python"
        )
    entrypoint = puffer_root / ".venv/bin/puffer"
    try:
        entrypoint_metadata = entrypoint.lstat()
    except OSError as exc:
        raise FoundationRunError(
            "fresh Puffer lifecycle requires a prepared .venv/bin/puffer"
        ) from exc
    if (
        entrypoint.is_symlink()
        or not stat.S_ISREG(entrypoint_metadata.st_mode)
        or entrypoint_metadata.st_nlink != 1
        or not os.access(entrypoint, os.X_OK)
    ):
        raise FoundationRunError(
            "prepared .venv/bin/puffer must be an executable regular "
            "non-link file"
        )
    entrypoint_payload = entrypoint.read_bytes()
    expected_entrypoint = (
        f"#!{puffer_root / '.venv/bin/python'}\n".encode("utf-8")
        + PUFFER_ENTRYPOINT_BODY
    )
    if entrypoint_payload != expected_entrypoint:
        raise FoundationRunError(
            "prepared .venv/bin/puffer differs from the exact pip "
            "pufferlib.pufferl:main console script"
        )
    startup_input = seal_puffer_python_startup(puffer_root)
    try:
        distribution = json.loads(
            run_checked(
                [
                    str(python),
                    "-B",
                    "-I",
                    "-c",
                    PUFFER_DISTRIBUTION_PROBE,
                    str(puffer_root),
                ],
                timeout=30,
            ).stdout
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationRunError(
            f"prepared pufferlib distribution probe is malformed: {exc}"
        ) from exc
    expected_distribution = {
        "name": "pufferlib",
        "version": "4.0.0",
        "editable": True,
        "source_matches_pinned_root": True,
    }
    if distribution != expected_distribution:
        raise FoundationRunError(
            "prepared pufferlib distribution is not the editable pinned "
            f"checkout: {distribution!r}"
        )
    return {
        "commit": commit,
        "git_status": [],
        "git_tree": git_output(puffer_root, "rev-parse", "HEAD^{tree}"),
        "absent_owned_paths": list(PRISTINE_PUFFER_OWNED_PATHS),
        "absent_compiled_modules": True,
        "absent_native_build_inputs": list(
            PRISTINE_PUFFER_NATIVE_INPUT_PATHS
        ),
        "prepared_venv_python": ".venv/bin/python",
        "prepared_venv_python_sha256": sha256_file(
            python.resolve(strict=True)
        ),
        "prepared_venv_puffer_entrypoint": ".venv/bin/puffer",
        "prepared_venv_puffer_entrypoint_sha256": sha256_bytes(
            entrypoint_payload
        ),
        "prepared_venv_puffer_entrypoint_normalized_sha256": sha256_bytes(
            PUFFER_ENTRYPOINT_NORMALIZED
        ),
        "prepared_venv_puffer_interpreter": ".venv/bin/python",
        "prepared_venv_puffer_interpreter_sha256": sha256_file(
            python.resolve(strict=True)
        ),
        "prepared_python_startup": startup_input,
        "prepared_pufferlib_distribution": expected_distribution,
    }


def normalize_lifecycle_output(
    value: str,
    *,
    puffer_root: Path,
    launcher_projection: Path | None = None,
) -> bytes:
    replacements = {
        str(puffer_root): "<pinned-puffer-root>",
        str(ROOT): "<source-root>",
    }
    if launcher_projection is not None:
        replacements[str(launcher_projection)] = "<launcher-projection>"
    normalized = value
    for source, replacement in sorted(
        replacements.items(), key=lambda item: len(item[0]), reverse=True
    ):
        normalized = normalized.replace(source, replacement)
    return normalized.encode("utf-8")


def run_lifecycle_step(
    stage: Path,
    *,
    sequence: int,
    step_id: str,
    command: list[str],
    normalized_command: list[str],
    expected_exit_code: int,
    cwd: Path,
    environment: dict[str, str],
    puffer_root: Path,
    launcher_projection: Path | None = None,
    timeout: int = 1800,
) -> tuple[dict[str, Any], subprocess.CompletedProcess[str]]:
    expected = LIFECYCLE_COMMANDS[sequence - 1]
    if (
        expected[0] != step_id
        or expected[1] != normalized_command
        or expected[2] != expected_exit_code
    ):
        raise FoundationRunError(
            f"internal lifecycle command drift at step {sequence}"
        )
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=environment,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise FoundationRunError(
            f"lifecycle step {step_id} could not run: {exc}"
        ) from exc
    stdout_payload = normalize_lifecycle_output(
        completed.stdout,
        puffer_root=puffer_root,
        launcher_projection=launcher_projection,
    )
    stderr_payload = normalize_lifecycle_output(
        completed.stderr,
        puffer_root=puffer_root,
        launcher_projection=launcher_projection,
    )
    stdout_relative = (
        f"puffer-lifecycle/{sequence:02d}-{step_id}.stdout.txt"
    )
    stderr_relative = (
        f"puffer-lifecycle/{sequence:02d}-{step_id}.stderr.txt"
    )
    atomic_write(stage / stdout_relative, stdout_payload)
    atomic_write(stage / stderr_relative, stderr_payload)
    if completed.returncode != expected_exit_code:
        raise FoundationRunError(
            f"lifecycle step {step_id} returned {completed.returncode}; "
            f"expected {expected_exit_code}; "
            f"stdout={completed.stdout[-3000:]!r}; "
            f"stderr={completed.stderr[-3000:]!r}"
        )
    receipt = {
        "sequence": sequence,
        "id": step_id,
        "command": normalized_command,
        "expected_exit_code": expected_exit_code,
        "exit_code": completed.returncode,
        "stdout": {
            "path": stdout_relative,
            "bytes": len(stdout_payload),
            "sha256": sha256_bytes(stdout_payload),
        },
        "stderr": {
            "path": stderr_relative,
            "bytes": len(stderr_payload),
            "sha256": sha256_bytes(stderr_payload),
        },
    }
    return receipt, completed


def copy_tracked_launcher_projection(
    destination: Path, puffer_root: Path
) -> None:
    tracked = run_checked(
        ["git", "-C", str(ROOT), "ls-files"],
        timeout=30,
    ).stdout.splitlines()
    if not tracked:
        raise FoundationRunError("tracked source projection is empty")
    for relative in tracked:
        source = ROOT / relative
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_symlink():
            target.symlink_to(os.readlink(source))
        elif source.is_file():
            shutil.copy2(source, target)
        else:
            raise FoundationRunError(
                f"tracked projection source is not a file/link: {relative}"
            )
    vendor = destination / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    (vendor / "PufferLib").symlink_to(
        puffer_root, target_is_directory=True
    )


def validate_ordinary_module_receipt(
    value: dict[str, Any], *, environment_source_sha256: str
) -> None:
    if set(value) != {
        "schema",
        "module_path",
        "module_sha256",
        "module_contract",
        "qualification_fixture",
        "state_bank",
    }:
        raise FoundationRunError("ordinary module receipt keys differ")
    contract = value["module_contract"]
    expected_contract = {
        "env_name": "bloodbowl",
        "gpu": 0,
        "observation_abi": "obs-v6",
        "observation_version": 6,
        "action_abi": "exact-joint-v1",
        "rollout_transition_contract": "tail-bootstrap-v1",
        "entropy_schedule_contract":
            "cosine-update-index-over-total-updates-fp32-v1",
        "environment_config_schema": "bloodbowl-environment-config-v1",
        "strict_env_config_testing": False,
        "environment_source_sha256": environment_source_sha256,
    }
    if (
        value["schema"] != "bloodbowl-f5-ordinary-module-v1"
        or not isinstance(value["module_path"], str)
        or not value["module_path"].startswith("pufferlib/_C.cpython-312-")
        or not value["module_path"].endswith(".so")
        or not isinstance(value["module_sha256"], str)
        or len(value["module_sha256"]) != 64
        or not isinstance(contract, dict)
        or set(contract) != set(expected_contract) | {
            "exact_action_source_sha256"
        }
        or any(contract[key] != expected for key, expected in expected_contract.items())
        or not isinstance(contract["exact_action_source_sha256"], str)
        or len(contract["exact_action_source_sha256"]) != 64
        or value["qualification_fixture"]
        != ORDINARY_QUALIFICATION_FIXTURE
        or value["state_bank"].get("kind_value") != 0
        or value["state_bank"].get("kind") != "none"
    ):
        raise FoundationRunError("ordinary compiled module is not role NONE")


def git_output(root: Path, *arguments: str) -> str:
    return run_checked(
        ["git", "-C", str(root), *arguments], timeout=30
    ).stdout.strip()


def load_json(path: Path) -> dict[str, Any]:
    try:
        raw = path.read_bytes()
        value = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationRunError(f"cannot parse {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FoundationRunError(f"{path} is not a JSON object")
    return value


def produce_puffer_lifecycle(
    stage: Path, puffer_root: Path
) -> tuple[dict[str, Any], list[list[str]]]:
    initial = validate_fresh_puffer_start(puffer_root)
    toolchain = puffer_build_toolchain()
    environment = puffer_lifecycle_environment(puffer_root, toolchain)
    steps: list[dict[str, Any]] = []
    commands: list[list[str]] = []

    def run_step(
        step_id: str,
        command: list[str],
        *,
        cwd: Path = ROOT,
        step_environment: dict[str, str] | None = None,
        launcher_projection: Path | None = None,
        timeout: int = 1800,
    ) -> subprocess.CompletedProcess[str]:
        sequence = len(steps) + 1
        expected_id, normalized, expected_exit_code = LIFECYCLE_COMMANDS[
            sequence - 1
        ]
        if expected_id != step_id:
            raise FoundationRunError(
                f"lifecycle sequence drift: {step_id} != {expected_id}"
            )
        receipt, completed = run_lifecycle_step(
            stage,
            sequence=sequence,
            step_id=step_id,
            command=command,
            normalized_command=list(normalized),
            expected_exit_code=expected_exit_code,
            cwd=cwd,
            environment=step_environment or environment,
            puffer_root=puffer_root,
            launcher_projection=launcher_projection,
            timeout=timeout,
        )
        steps.append(receipt)
        commands.append(list(normalized))
        return completed

    ordinary_installer = ROOT / "tools/install_puffer_env.sh"
    f5_installer = ROOT / "tools/install_f5_trainability_env.sh"
    puffer_python = puffer_root / ".venv/bin/python"

    run_step(
        "ordinary-install",
        ["/bin/bash", str(ordinary_installer), str(puffer_root)],
    )
    run_step(
        "ordinary-cpu-build",
        [
            "/usr/bin/env",
            f"CC={toolchain['cc']['path']}",
            f"CXX={toolchain['cxx']['path']}",
            "/bin/bash",
            str(puffer_root / "build.sh"),
            "bloodbowl",
            "--cpu",
        ],
        cwd=puffer_root,
    )
    run_step(
        "ordinary-fast-build",
        [
            "/usr/bin/env",
            f"CC={toolchain['cc']['path']}",
            f"CXX={toolchain['cxx']['path']}",
            "/bin/bash",
            str(puffer_root / "build.sh"),
            "bloodbowl",
            "--fast",
        ],
        cwd=puffer_root,
    )
    run_step(
        "ordinary-check",
        [
            "/bin/bash",
            str(ordinary_installer),
            "--check",
            str(puffer_root),
        ],
    )
    ordinary_probe = run_step(
        "ordinary-module-none",
        [
            str(puffer_python),
            "-B",
            "-I",
            "-c",
            ORDINARY_MODULE_PROBE,
            str(ROOT / "tools"),
            str(puffer_root),
        ],
        cwd=puffer_root,
    )
    try:
        ordinary_module = json.loads(ordinary_probe.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationRunError(
            f"ordinary module probe emitted malformed JSON: {exc}"
        ) from exc
    if not isinstance(ordinary_module, dict):
        raise FoundationRunError("ordinary module probe did not emit an object")
    environment_source_sha256 = (
        puffer_root / "ocean/bloodbowl/.content_hash"
    ).read_text(encoding="ascii").strip()
    validate_ordinary_module_receipt(
        ordinary_module,
        environment_source_sha256=environment_source_sha256,
    )
    atomic_write(
        stage / "ordinary-module.json", canonical_json(ordinary_module)
    )
    ordinary_authority_sha256 = sha256_file(
        puffer_root / "src/exact_action_build_hash.h"
    )
    ordinary_git_status = git_output(
        puffer_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).splitlines()

    rejected_ordinary = run_step(
        "f5-check-rejects-ordinary",
        [
            "/bin/bash",
            str(f5_installer),
            "--check",
            str(puffer_root),
        ],
    )
    if "qualification authority differs" not in rejected_ordinary.stderr:
        raise FoundationRunError(
            "dedicated F5 checker did not reject the ordinary role for the "
            "expected authority reason"
        )

    run_step(
        "f5-stage",
        ["/bin/bash", str(f5_installer), str(puffer_root)],
        timeout=3600,
    )
    puffer_python_startup_input(puffer_root)
    run_step(
        "f5-cpu-rebuild",
        [
            "/usr/bin/env",
            f"CC={toolchain['cc']['path']}",
            f"CXX={toolchain['cxx']['path']}",
            "/bin/bash",
            str(puffer_root / "build.sh"),
            "bloodbowl",
            "--cpu",
        ],
        cwd=puffer_root,
    )
    run_step(
        "f5-check",
        [
            "/bin/bash",
            str(f5_installer),
            "--check",
            str(puffer_root),
        ],
    )
    already_staged = run_step(
        "f5-install-rejects-already-staged",
        ["/bin/bash", str(f5_installer), str(puffer_root)],
    )
    if (
        "f5-fixed-state-v1 is already staged" not in already_staged.stderr
        or "use --check" not in already_staged.stderr
    ):
        raise FoundationRunError(
            "dedicated F5 installer did not reject an already-staged role "
            "through its closed install boundary"
        )
    run_step(
        "f5-module-proof",
        [
            str(puffer_python),
            "-B",
            "-I",
            str(MODULE_CHECKER),
            "--puffer-root",
            str(puffer_root),
            "--output",
            str(stage / "puffer-module.json"),
        ],
        cwd=puffer_root,
    )
    module_evidence = load_json(stage / "puffer-module.json")
    if module_evidence.get("schema") != "bloodbowl-f5-puffer-module-v1":
        raise FoundationRunError("Puffer module evidence schema differs")

    ordinary_rejection = run_step(
        "ordinary-install-rejects-f5",
        ["/bin/bash", str(ordinary_installer), str(puffer_root)],
    )
    ordinary_rejection_marker = (
        "ordinary Puffer lifecycle rejects "
        "qualification_fixture_role=f5-fixed-state-v1 (enabled=1)"
    )
    if ordinary_rejection_marker not in ordinary_rejection.stderr:
        raise FoundationRunError(
            "ordinary installer did not reject the staged F5 role early"
        )

    with tempfile.TemporaryDirectory(
        prefix="f5-launcher-projection-"
    ) as projection_directory:
        projection = Path(projection_directory).resolve(strict=True)
        copy_tracked_launcher_projection(projection, puffer_root)

        ablation_environment = isolated_python_environment()
        ablation_environment.update(
            {
                "PUFFER_INSTALL_PYTHON": str(
                    Path(sys.executable).resolve(strict=True)
                ),
                "TAG": "f5-lifecycle-rejection",
                "REWARD_MANIFEST": str(
                    projection / "puffer/config/rewards/r0_full.json"
                ),
                "BOOTSTRAP_MODE": "fresh-v6-qualification",
                "DRY_RUN": "1",
                "CUDA_VISIBLE_DEVICES": "0",
            }
        )
        ablation = run_step(
            "production-ablation-rejects-f5",
            [
                "/bin/bash",
                str(projection / "tools/run_reward_ablation.sh"),
            ],
            step_environment=ablation_environment,
            launcher_projection=projection,
        )
        if (
            ordinary_rejection_marker not in ablation.stderr
            or "production reward launcher requires an ordinary role-none "
            "Puffer build"
            not in ablation.stderr
        ):
            raise FoundationRunError(
                "production ablation launcher did not reject the staged role "
                "through its early ordinary installer subprocess"
            )

        screen_environment = isolated_python_environment()
        screen_environment.update(
            {
                "PUFFER_INSTALL_PYTHON": str(
                    Path(sys.executable).resolve(strict=True)
                ),
                "STEPS": "50000000",
                "SCREEN_PROFILE": "exact-action-canary",
                "PLAN_ONLY": "1",
            }
        )
        screen = run_step(
            "production-screen-rejects-f5",
            [
                "/bin/bash",
                str(projection / "tools/run_reward_screen.sh"),
            ],
            step_environment=screen_environment,
            launcher_projection=projection,
        )
        if (
            ordinary_rejection_marker not in screen.stderr
            or "production reward screen requires an ordinary role-none "
            "Puffer build"
            not in screen.stderr
        ):
            raise FoundationRunError(
                "production reward screen did not reject the staged role "
                "through its early ordinary installer subprocess"
            )

    module_path = Path(module_evidence["module_path"]).resolve(strict=True)
    module_relative = module_path.relative_to(puffer_root).as_posix()
    final_status = git_output(
        puffer_root,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
    ).splitlines()
    final = {
        "commit": git_output(puffer_root, "rev-parse", "HEAD"),
        "git_status": final_status,
        "git_status_sha256": sha256_bytes(canonical_json(final_status)),
        "authority_sha256": sha256_file(
            puffer_root / "src/exact_action_build_hash.h"
        ),
        "environment_snapshot_sha256": environment_source_sha256,
        "module_path": module_relative,
        "module_sha256": sha256_file(module_path),
        "qualification_fixture_enabled": True,
        "qualification_fixture_role": FIXTURE_ROLE,
        "compiled_gpu": 0,
        "state_bank_kind": 0,
        "state_bank_kind_name": "none",
    }
    lifecycle = {
        "schema": "bloodbowl-f5-puffer-lifecycle-v1",
        "puffer_commit": PUFFER_COMMIT,
        "scope": {
            "caller_designated_tree_mutated_in_place": True,
            "puffer_tree_embedded_in_evidence": False,
            "live_final_tree_required_for_verification": True,
            "cpu_foundation_only": True,
            "x86_validation": "pending-external",
            "nvidia_validation": "pending-external",
            "ppo_learning": "out-of-scope",
        },
        "source_contracts": {
            relative: sha256_file(ROOT / relative)
            for relative in (
                "tools/install_puffer_env.sh",
                "tools/install_f5_trainability_env.sh",
                "training/puffer_portable_simd_flags.patch",
                "training/puffer_raylib_pin.patch",
                "tools/run_reward_ablation.sh",
                "tools/run_reward_screen.sh",
            )
        },
        "build_toolchain": toolchain,
        "native_build_inputs": {
            "raylib": puffer_raylib_input(puffer_root),
        },
        "initial": initial,
        "ordinary": {
            "after_step": "ordinary-module-none",
            "authority_sha256": ordinary_authority_sha256,
            "environment_snapshot_sha256": environment_source_sha256,
            "git_status": ordinary_git_status,
            "git_status_sha256": sha256_bytes(
                canonical_json(ordinary_git_status)
            ),
            "module_evidence": "ordinary-module.json",
            "module_evidence_sha256": sha256_file(
                stage / "ordinary-module.json"
            ),
        },
        "steps": steps,
        "final": final,
    }
    atomic_write(
        stage / "puffer-lifecycle.json", canonical_json(lifecycle)
    )
    return lifecycle, commands


def run_json(command: list[str], *, timeout: int = 300) -> dict[str, Any]:
    completed = run_checked(command, timeout=timeout)
    try:
        value = json.loads(completed.stdout)
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise FoundationRunError(
            f"command emitted malformed JSON: {command!r}"
        ) from exc
    if not isinstance(value, dict):
        raise FoundationRunError(f"command did not emit an object: {command!r}")
    return value


def validate_task(task: dict[str, Any]) -> None:
    expected = {
        "schema": "bloodbowl-trainability-task-v1",
        "qualification_fixture_role": FIXTURE_ROLE,
        "qualification_only": True,
        "ruleset": "BB2025",
        "full_bundle_records": 26,
        "full_bundle_bytes": 58568,
        "full_bundle_sha256": FULL_BBS_SHA256,
        "f5_bbs_bytes": 2268,
        "f5_bbs_sha256": F5_BBS_SHA256,
        "raw_match_bytes": 2240,
        "raw_match_sha256": MATCH_SHA256,
        "generated_header_sha256": HEADER_SHA256,
        "proof_bundle_index": 25,
        "proof_source_id": "0xA9000019",
        "durable_source_id": "0xAE00001A",
        "template_id": 5,
        "template_key": "f5-score-or-wait",
        "recipe_revision": 1,
        "cell_id": 1,
        "variant_id": 1,
        "variant_seed": 410,
        "capture_action_count": 51,
        "capture_dice_count": 19,
        "engine_fingerprint": "0x64897cde",
        "team_count": 30,
        "skill_count": 108,
        "action_type_count": 30,
        "max_decisions": 8,
        "reference_trace_schema": "bloodbowl-f5-reference-trace-v1",
        "reference_trace_sha256": TRACE_SHA256,
    }
    for key, wanted in expected.items():
        if key not in task or type(task[key]) is not type(wanted) or task[key] != wanted:
            raise FoundationRunError(
                f"task {key} is {task.get(key)!r}; expected {wanted!r}"
            )


def validate_reference(value: dict[str, Any]) -> None:
    if set(value) != {"schema", "fixture_role", "transitions", "summary"}:
        raise FoundationRunError("reference diagnostic keys differ")
    if (
        value["schema"] != "bloodbowl-f5-reference-diagnostic-v1"
        or value["fixture_role"] != FIXTURE_ROLE
        or not isinstance(value["transitions"], list)
        or len(value["transitions"]) != 8
    ):
        raise FoundationRunError("reference diagnostic identity differs")
    for index, row in enumerate(value["transitions"], start=1):
        if not isinstance(row, dict) or row.get("decision") != index:
            raise FoundationRunError(f"reference transition {index} is malformed")
        if row.get("decision_team") != 0 or row.get("waiting_singleton") is not True:
            raise FoundationRunError(
                f"reference transition {index} has wrong team/support"
            )
        expected_rewards = [0, 0] if index < 8 else [1, -1]
        expected_terminals = [0, 0] if index < 8 else [1, 1]
        if (
            row.get("rewards") != expected_rewards
            or row.get("terminals") != expected_terminals
            or row.get("dice") != 0
            or row.get("illegal") != 0
            or row.get("collisions") != 0
        ):
            raise FoundationRunError(
                f"reference transition {index} violates transport contract"
            )
    expected_summary = {
        "completed_episodes": 1,
        "tds_t0": 1,
        "tds_t1": 0,
        "episode_length": 8,
        "dice": 0,
        "illegal": 0,
        "collisions": 0,
        "illegal_fraction": 0,
        "error_episodes": 0,
        "demo_episodes": 0,
        "state_bank_config_episodes": 0,
        "reward_samples": 16,
        "reward_nonzero_samples": 2,
        "reward_clipped_samples": 0,
        "reward_nonfinite_samples": 0,
        "reward_clip_episodes": 0,
        "reward_nonfinite_episodes": 0,
        "reward_component_touchdown": 1,
        "reward_component_residual": 0,
        "reward_component_mismatch_samples": 0,
        "reward_component_nonfinite_samples": 0,
        "reward_terminal_suppressed_signed": 0,
        "reward_terminal_suppressed_abs": 0,
        "reward_postclip_return": 1,
        "autoreset_match_sha256": MATCH_SHA256,
    }
    if value["summary"] != expected_summary:
        raise FoundationRunError("reference summary differs")


def validate_enumeration(value: dict[str, Any]) -> None:
    if set(value) != {
        "schema",
        "safe_zero_dice_trajectories",
        "safe_probability",
        "safe_probability_numerator",
        "safe_probability_denominator",
        "selected_probability",
        "selected_probability_numerator",
        "selected_probability_denominator",
        "nodes",
    }:
        raise FoundationRunError("safe enumeration keys differ")
    rational_fields = (
        "safe_probability_numerator",
        "safe_probability_denominator",
        "selected_probability_numerator",
        "selected_probability_denominator",
    )
    if any(
        type(value[field]) is not int or value[field] <= 0
        for field in rational_fields
    ):
        raise FoundationRunError(
            "safe enumeration exact rational fields are not positive integers"
        )
    if (
        value["schema"] != "bloodbowl-f5-safe-enumeration-v1"
        or value["safe_zero_dice_trajectories"] != SAFE_TRAJECTORIES
        or Fraction(
            value["safe_probability_numerator"],
            value["safe_probability_denominator"],
        )
        != SAFE_PROBABILITY_FRACTION
        or Fraction(
            value["selected_probability_numerator"],
            value["selected_probability_denominator"],
        )
        != SELECTED_PROBABILITY_FRACTION
        or value["nodes"] != 37206
        or not math.isclose(
            value["safe_probability"],
            SAFE_PROBABILITY,
            rel_tol=0.0,
            abs_tol=1e-19,
        )
        or not math.isclose(
            value["selected_probability"],
            SELECTED_PROBABILITY,
            rel_tol=0.0,
            abs_tol=1e-24,
        )
    ):
        raise FoundationRunError("safe enumeration result differs")


def validate_random(
    value: dict[str, Any], *, episodes: int, seed: int
) -> None:
    expected_keys = {
        "schema",
        "seed",
        "episodes",
        "decisions",
        "agent_steps",
        "successes",
        "tds_t1",
        "early_terminals",
        "illegal",
        "collisions",
        "dice",
        "test_windows",
        "fixture_resets",
        "reward_totals",
        "episode_lengths",
    }
    if set(value) != expected_keys:
        raise FoundationRunError("random baseline keys differ")
    if episodes != DEFAULT_RANDOM_EPISODES or seed != DEFAULT_RANDOM_SEED:
        raise FoundationRunError(
            "authoritative random baseline is frozen at 100000 episodes, "
            "seed 245"
        )
    if value != EXPECTED_RANDOM_BASELINE:
        raise FoundationRunError("frozen random baseline differs")


def artifact_manifest(stage: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for path in sorted(stage.rglob("*")):
        if path.is_file() and path.name != "evidence.json":
            relative = path.relative_to(stage).as_posix()
            result[relative] = {
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
    return result


def produce_evidence(args: argparse.Namespace) -> Path:
    artifact_dir = args.artifact_dir.absolute()
    if artifact_dir.exists() or os.path.lexists(artifact_dir):
        raise FoundationRunError(
            f"artifact directory already exists: {artifact_dir}"
        )
    artifact_dir.parent.mkdir(parents=True, exist_ok=True)
    source_commit = git_output(ROOT, "rev-parse", "HEAD")
    source_tree = git_output(ROOT, "rev-parse", "HEAD^{tree}")
    source_status = git_output(
        ROOT, "status", "--porcelain=v1", "--untracked-files=all"
    )
    if source_status and not args.allow_dirty_source:
        raise FoundationRunError(
            "source worktree is dirty; commit the reviewed implementation first"
        )

    compiler_path = foundation_compiler()
    build_environment = foundation_build_environment()
    build_command = [
        "make",
        "-B",
        f"CC={compiler_path}",
        f"CFLAGS={FOUNDATION_CFLAGS}",
        "LDFLAGS=",
        "build/f5_trainability_foundation",
        "build/puffer_f5_trainability_tests",
        "build/f5_trainability_diagnostics",
    ]
    run_checked(
        build_command,
        capture=True,
        environment=build_environment,
    )
    temporary = Path(
        tempfile.mkdtemp(prefix=".f5-foundation.", dir=artifact_dir.parent)
    )
    command_records: list[list[str]] = [
        [
            "make",
            "-B",
            "CC=<resolved-cc>",
            f"CFLAGS={FOUNDATION_CFLAGS}",
            "LDFLAGS=",
            "build/f5_trainability_foundation",
            "build/puffer_f5_trainability_tests",
            "build/f5_trainability_diagnostics",
        ]
    ]
    try:
        task_dir = temporary / "task"
        generate = [
            str(GENERATOR),
            "generate",
            "--output",
            str(task_dir),
        ]
        run_checked(generate)
        command_records.append(
            [
                "build/f5_trainability_foundation",
                "generate",
                "--output",
                "task",
            ]
        )
        verify = [str(GENERATOR), "verify", "--input", str(task_dir)]
        run_checked(verify)
        command_records.append(
            [
                "build/f5_trainability_foundation",
                "verify",
                "--input",
                "task",
            ]
        )
        task = load_json(task_dir / "task.json")
        validate_task(task)
        if (
            sha256_file(task_dir / "authored-proof-bundle.bbs")
            != FULL_BBS_SHA256
            or sha256_file(task_dir / "f5.bbs") != F5_BBS_SHA256
            or sha256_file(task_dir / "f5.match") != MATCH_SHA256
            or sha256_file(task_dir / "reference-trace.json") != TRACE_SHA256
            or sha256_file(task_dir / "f5_trainability_fixture.generated.h")
            != HEADER_SHA256
            or sha256_file(CHECKED_FIXTURE_HEADER) != HEADER_SHA256
            or (task_dir / "f5_trainability_fixture.generated.h").read_bytes()
            != CHECKED_FIXTURE_HEADER.read_bytes()
        ):
            raise FoundationRunError("generated task artifact hash differs")

        c_test = [str(C_TEST)]
        c_test_result = run_checked(c_test)
        command_records.append(["build/puffer_f5_trainability_tests"])
        atomic_write(
            temporary / "c-test.txt",
            (c_test_result.stdout + c_test_result.stderr).encode("utf-8"),
        )

        reference_command = [str(DIAGNOSTICS), "reference"]
        reference = run_json(reference_command)
        command_records.append(
            ["build/f5_trainability_diagnostics", "reference"]
        )
        validate_reference(reference)
        atomic_write(temporary / "reference.json", canonical_json(reference))

        enumeration_command = [str(DIAGNOSTICS), "enumerate"]
        enumeration = run_json(enumeration_command, timeout=600)
        command_records.append(
            ["build/f5_trainability_diagnostics", "enumerate"]
        )
        validate_enumeration(enumeration)
        atomic_write(
            temporary / "safe-enumeration.json",
            canonical_json(enumeration),
        )

        random_command = [
            str(DIAGNOSTICS),
            "random",
            "--episodes",
            str(args.random_episodes),
            "--seed",
            str(args.random_seed),
        ]
        random_baseline = run_json(random_command, timeout=900)
        command_records.append(
            [
                "build/f5_trainability_diagnostics",
                "random",
                "--episodes",
                str(args.random_episodes),
                "--seed",
                str(args.random_seed),
            ]
        )
        validate_random(
            random_baseline,
            episodes=args.random_episodes,
            seed=args.random_seed,
        )
        atomic_write(
            temporary / "random-baseline.json",
            canonical_json(random_baseline),
        )
        atomic_write(
            temporary / "environment-config.json",
            ENV_CONFIG.read_bytes(),
        )

        puffer: dict[str, Any]
        if args.puffer_root is None:
            puffer = {
                "validated": False,
                "reason": "puffer-root-not-supplied",
                "required_commit": PUFFER_COMMIT,
            }
        else:
            puffer_root = args.puffer_root.resolve(strict=True)
            lifecycle, lifecycle_commands = produce_puffer_lifecycle(
                temporary, puffer_root
            )
            command_records.extend(lifecycle_commands)
            module_evidence = load_json(temporary / "puffer-module.json")
            runtime = module_evidence.get("runtime")
            if not isinstance(runtime, dict):
                raise FoundationRunError("Puffer module runtime receipt is absent")
            receipt_keys = {
                "requirements_sha256",
                "distributions_snapshot_sha256",
                "distributions_snapshot_bytes",
                "distributions_digest_file_sha256",
                "direct_requirements",
                "torch_version",
                "torch_cuda_version",
                "torch_cuda_available",
                "torch_collector_sha256",
            }
            if not receipt_keys.issubset(runtime):
                raise FoundationRunError(
                    "Puffer module runtime receipt is incomplete"
                )
            if runtime["requirements_sha256"] != DEPENDENCY_REQUIREMENTS_SHA256:
                raise FoundationRunError(
                    "Puffer qualification requirements identity differs"
                )
            puffer = {
                "validated": True,
                "commit": git_output(puffer_root, "rev-parse", "HEAD"),
                "status": git_output(
                    puffer_root,
                    "status",
                    "--porcelain=v1",
                    "--untracked-files=all",
                ).splitlines(),
                "authority_sha256": sha256_file(
                    puffer_root / "src/exact_action_build_hash.h"
                ),
                "environment_snapshot_sha256": (
                    puffer_root / "ocean/bloodbowl/.content_hash"
                ).read_text(encoding="ascii").strip(),
                "module_evidence": "puffer-module.json",
                "module_evidence_sha256": sha256_file(
                    temporary / "puffer-module.json"
                ),
                "dependency_identity_scope": DEPENDENCY_IDENTITY_SCOPE,
                "requirements_sha256": runtime["requirements_sha256"],
                "distributions_snapshot_sha256": runtime[
                    "distributions_snapshot_sha256"
                ],
                "distributions_snapshot_bytes": runtime[
                    "distributions_snapshot_bytes"
                ],
                "distributions_digest_file_sha256": runtime[
                    "distributions_digest_file_sha256"
                ],
                "direct_requirements": runtime["direct_requirements"],
                "torch_version": runtime["torch_version"],
                "torch_cpu_only": (
                    runtime["torch_cuda_version"] is None
                    and runtime["torch_cuda_available"] is False
                ),
                "torch_collector_sha256": runtime[
                    "torch_collector_sha256"
                ],
                "lifecycle_evidence": "puffer-lifecycle.json",
                "lifecycle_evidence_sha256": sha256_file(
                    temporary / "puffer-lifecycle.json"
                ),
                "lifecycle_initial_git_tree": lifecycle["initial"]["git_tree"],
            }

        compiler_lines = run_checked(
            [str(compiler_path), "--version"],
            timeout=30,
            environment=build_environment,
        ).stdout.splitlines()
        if not compiler_lines:
            raise FoundationRunError(
                "foundation compiler did not publish a version identity"
            )
        compiler_version = compiler_lines[0]
        compiler_target = run_checked(
            [str(compiler_path), "-dumpmachine"],
            timeout=30,
            environment=build_environment,
        ).stdout.strip()
        if not compiler_target or "\n" in compiler_target:
            raise FoundationRunError(
                "foundation compiler did not publish one target identity"
            )
        evidence = {
            "schema": EVIDENCE_SCHEMA,
            "qualification_only": True,
            "fixture_role": FIXTURE_ROLE,
            "source": {
                "commit": source_commit,
                "tree": source_tree,
                "dirty": bool(source_status),
                "status": source_status.splitlines(),
            },
            "task": {
                "path": "task/task.json",
                "sha256": sha256_file(task_dir / "task.json"),
                "full_bundle_sha256": FULL_BBS_SHA256,
                "f5_bbs_sha256": F5_BBS_SHA256,
                "raw_match_sha256": MATCH_SHA256,
                "reference_trace_sha256": TRACE_SHA256,
                "generated_header_sha256": HEADER_SHA256,
            },
            "reference": {
                "path": "reference.json",
                "sha256": sha256_file(temporary / "reference.json"),
                "episodes": 1,
                "decisions": 8,
                "home_meaningful_rows": 8,
                "away_null_rows": 8,
                "agent_steps": 16,
            },
            "safe_baseline": {
                "path": "safe-enumeration.json",
                "sha256": sha256_file(temporary / "safe-enumeration.json"),
                "trajectories": SAFE_TRAJECTORIES,
                "probability": enumeration["safe_probability"],
            },
            "random_baseline": {
                "path": "random-baseline.json",
                "sha256": sha256_file(temporary / "random-baseline.json"),
                "episodes": args.random_episodes,
                "seed": args.random_seed,
                "successes": random_baseline["successes"],
            },
            "puffer": puffer,
            "binaries": {
                path.name: {
                    "bytes": path.stat().st_size,
                    "sha256": sha256_file(path),
                }
                for path in (GENERATOR, C_TEST, DIAGNOSTICS)
            },
            "platform": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "sys_platform": sys.platform,
                "python": platform.python_version(),
                "python_implementation": platform.python_implementation(),
                "python_cache_tag": sys.implementation.cache_tag,
                "compiler_executable": str(compiler_path),
                "compiler_sha256": sha256_file(compiler_path),
                "compiler_version": compiler_version,
                "compiler_target": compiler_target,
                "cflags": FOUNDATION_CFLAGS,
                "ldflags": "",
            },
            "external_gates": {
                "exact_pin_x86": "pending-external",
                "nvidia_schema11": "pending-external",
                "ppo_learning": "out-of-scope",
            },
            "commands": command_records,
            "artifacts": artifact_manifest(temporary),
        }
        atomic_write(temporary / "evidence.json", canonical_json(evidence))
        os.replace(temporary, artifact_dir)
        directory = os.open(artifact_dir.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    return artifact_dir


def exact_positive_int(raw: str, *, expected: int, label: str) -> int:
    if (
        not raw.isascii()
        or not raw.isdigit()
        or raw.startswith("0")
        or int(raw) != expected
    ):
        raise argparse.ArgumentTypeError(
            f"{label} is frozen at the canonical value {expected}"
        )
    return expected


def exact_random_episodes(raw: str) -> int:
    return exact_positive_int(
        raw,
        expected=DEFAULT_RANDOM_EPISODES,
        label="random episodes",
    )


def exact_random_seed(raw: str) -> int:
    return exact_positive_int(
        raw,
        expected=DEFAULT_RANDOM_SEED,
        label="random seed",
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument(
        "--random-episodes",
        type=exact_random_episodes,
        default=DEFAULT_RANDOM_EPISODES,
    )
    parser.add_argument(
        "--random-seed",
        type=exact_random_seed,
        default=DEFAULT_RANDOM_SEED,
    )
    parser.add_argument("--puffer-root", type=Path)
    parser.add_argument(
        "--allow-dirty-source",
        action="store_true",
        help="developer-only incomplete evidence; strict verifier rejects it",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = produce_evidence(args)
    except (FoundationRunError, OSError, subprocess.SubprocessError) as exc:
        print(f"F5 foundation run failed: {exc}", file=sys.stderr)
        return 2
    print(output)
    return 0


if __name__ == "__main__":
    if (
        sys.flags.dont_write_bytecode != 1
        or sys.flags.isolated != 1
        or sys.flags.no_site != 1
    ):
        print(
            "F5 foundation runner must be invoked with "
            "`python3 -B -I -S tools/run_f5_trainability_foundation.py ...`",
            file=sys.stderr,
        )
        raise SystemExit(2)
    raise SystemExit(main())
