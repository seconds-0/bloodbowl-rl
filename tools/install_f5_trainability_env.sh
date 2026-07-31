#!/usr/bin/env bash
# Stage or verify the one repository-reviewed F5 qualification build role.
#
# Usage:
#   tools/install_f5_trainability_env.sh /path/to/fresh/PufferLib
#   tools/install_f5_trainability_env.sh --check /path/to/fresh/PufferLib
#
# This is deliberately separate from install_puffer_env.sh. It accepts only a
# destination Puffer tree and the check mode: fixture bytes, identities, hashes,
# role, and task fields are immutable repository literals below.
#
# --check runs the deterministic reset/reference/autoreset oracle for a CPU
# module. For a CUDA module it closes the exact authority, patch, environment,
# backend-source, and exported-metadata contracts only; CUDA runtime
# qualification is an external GPU gate and is not claimed by this script.
#
# The qualification dependency file freezes direct versions and CPU wheel
# selection, not transitive wheel bytes. Before role staging, pip resolves only
# binary distributions and the installer publishes a canonical snapshot of
# every installed distribution. Later convergence/check modes reproduce that
# name/version snapshot from the venv and fail on any such dependency drift.
# The outer foundation evidence commits its SHA and seals Python's automatic
# startup surface to one exact bootstrap/path hook that blocks the trusted base
# interpreter's sitecustomize before adding the pinned Puffer source root. This
# deliberately does not claim wheel-origin, RECORD/file-byte, or
# loose-site-packages closure; installed dependency package bytes and the base
# interpreter/stdlib remain a trusted prepared-toolchain boundary.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PINNED_PUFFER_COMMIT="9836f0d2e78889c1aaf189c04d161b6fc61a9386"
INSTALL_PYTHON="${PUFFER_INSTALL_PYTHON:-python3}"
MODE=install
PUFFER_ARG=""

while [ "$#" -gt 0 ]; do
    case "$1" in
        --check)
            [ "$MODE" = install ] || {
                echo "error: duplicate --check" >&2
                exit 2
            }
            MODE=check
            shift
            ;;
        --*)
            echo "error: unknown F5 installer option: $1" >&2
            exit 2
            ;;
        *)
            [ -z "$PUFFER_ARG" ] || {
                echo "error: multiple PufferLib paths supplied" >&2
                exit 2
            }
            PUFFER_ARG="$1"
            shift
            ;;
    esac
done

[ -n "$PUFFER_ARG" ] || {
    echo "error: an explicit fresh PufferLib path is required" >&2
    exit 2
}
command -v "$INSTALL_PYTHON" >/dev/null 2>&1 || {
    echo "error: installer Python is unavailable: $INSTALL_PYTHON" >&2
    exit 2
}
[ -f "$PUFFER_ARG/build.sh" ] || {
    echo "error: $PUFFER_ARG is not a PufferLib tree" >&2
    exit 1
}
PUFFER="$(cd "$PUFFER_ARG" && pwd -P)"
PUFFER_GIT_ROOT="$(git -C "$PUFFER" rev-parse --show-toplevel 2>/dev/null)" || {
    echo "error: $PUFFER is not a PufferLib Git worktree" >&2
    exit 1
}
PUFFER_GIT_ROOT="$(cd "$PUFFER_GIT_ROOT" && pwd -P)"
[ "$PUFFER_GIT_ROOT" = "$PUFFER" ] || {
    echo "error: PufferLib path is not the Git worktree root: $PUFFER" >&2
    exit 1
}
PUFFER_HEAD="$(git -C "$PUFFER" rev-parse --verify "HEAD^{commit}")" || {
    echo "error: PufferLib HEAD cannot be resolved" >&2
    exit 1
}
[ "$PUFFER_HEAD" = "$PINNED_PUFFER_COMMIT" ] || {
    echo "error: PufferLib HEAD must be $PINNED_PUFFER_COMMIT; found $PUFFER_HEAD" >&2
    exit 1
}

AUTHORITY="$PUFFER/src/exact_action_build_hash.h"
DST="$PUFFER/ocean/bloodbowl"
ROLE_PATCH="$ROOT/training/puffer_f5_trainability_role.patch"
LEDGER="$ROOT/training/puffer_compiled_backend_sources.txt"
QUALIFICATION_REQUIREMENTS="$ROOT/training/f5_trainability_requirements.txt"
QUALIFICATION_REQUIREMENTS_SHA256="010a1f6a785d9c7e7b421f345eeae10a177891fae7e56454111da18c0bed9aa6"
PYBIN="$PUFFER/.venv/bin/python"
DEPENDENCY_SNAPSHOT="$PUFFER/.venv/f5_trainability_distributions.json"
DEPENDENCY_SNAPSHOT_SHA256="$PUFFER/.venv/f5_trainability_distributions.sha256"

check_puffer_python_startup() {
    "$INSTALL_PYTHON" -B -I -S - "$PUFFER" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys

root = Path(sys.argv[1]).resolve(strict=True)
venv = root / ".venv"
for relative in (
    ".",
    "bin",
    "lib",
    "lib/python3.12",
        "lib/python3.12/site-packages",
):
    directory = venv if relative == "." else venv / relative
    metadata = directory.lstat()
    if directory.is_symlink() or not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit(
            f"sealed Puffer venv directory is not real: {relative}"
        )
    directory.resolve(strict=True).relative_to(venv.resolve(strict=True))

config = venv / "pyvenv.cfg"
config_metadata = config.lstat()
if (
    config.is_symlink()
    or not stat.S_ISREG(config_metadata.st_mode)
    or config_metadata.st_nlink != 1
    or config_metadata.st_size <= 0
    or config_metadata.st_size > 4096
):
    raise SystemExit("sealed Puffer pyvenv.cfg is not a bounded regular file")
values = {}
for line in config.read_text(encoding="utf-8").splitlines():
    if " = " not in line:
        raise SystemExit("sealed Puffer pyvenv.cfg has a noncanonical line")
    key, value = line.split(" = ", 1)
    if not key or key in values or not value:
        raise SystemExit(
            "sealed Puffer pyvenv.cfg has duplicate/empty fields"
        )
    values[key] = value
if set(values) != {
    "home",
    "include-system-site-packages",
    "version",
    "executable",
    "command",
}:
    raise SystemExit("sealed Puffer pyvenv.cfg field set differs")
if values["include-system-site-packages"] != "false":
    raise SystemExit("sealed Puffer venv includes system site-packages")
version = values["version"].split(".")
if (
    len(version) != 3
    or version[:2] != ["3", "12"]
    or not version[2].isdigit()
):
    raise SystemExit("sealed Puffer pyvenv.cfg is not CPython 3.12")
actual_python = (venv / "bin/python").resolve(strict=True)
if (
    Path(values["executable"]).resolve(strict=True) != actual_python
    or (Path(values["home"]) / "python3.12").resolve(strict=True)
        != actual_python
):
    raise SystemExit("sealed Puffer pyvenv.cfg base Python differs")
runtime = json.loads(subprocess.run(
    [
        str(venv / "bin/python"),
        "-B",
        "-I",
        "-S",
        "-c",
        (
            "import json,sys;"
            "print(json.dumps({"
            "'implementation':sys.implementation.name,"
            "'platlibdir':sys.platlibdir,"
            "'version':'.'.join(str(v) for v in sys.version_info[:3])"
            "},sort_keys=True,separators=(',',':')))"
        ),
    ],
    check=True,
    capture_output=True,
    text=True,
    env={"PATH": os.defpath, "LC_ALL": "C"},
).stdout)
if runtime != {
    "implementation": "cpython",
    "platlibdir": "lib",
    "version": values["version"],
}:
    raise SystemExit(
        "sealed Puffer interpreter must be exact CPython 3.12 with "
        f"platlibdir=lib: {runtime!r}"
    )

site = venv / "lib/python3.12/site-packages"
entries = {entry.name for entry in os.scandir(site)}
pth_names = {name for name in entries if name.endswith(".pth")}
forbidden = {
    name
    for name in entries
    if (
        name.endswith(".egg-link")
        or name.startswith("sitecustomize")
        or name.startswith("usercustomize")
        or name.startswith("__editable___pufferlib_4_0_0_finder")
    )
}
cache = site / "__pycache__"
cached_finders = set()
if os.path.lexists(cache):
    cache_metadata = cache.lstat()
    if cache.is_symlink() or not stat.S_ISDIR(cache_metadata.st_mode):
        raise SystemExit("sealed Puffer startup bytecode cache is not real")
    cached_finders = {
        entry.name
        for entry in os.scandir(cache)
        if entry.name.startswith("__editable___pufferlib_4_0_0_finder")
    }
if pth_names != {"pufferlib-editable.pth"} or forbidden or cached_finders:
    raise SystemExit(
        "sealed Puffer executable startup hooks differ: "
        f"pth={sorted(pth_names)!r}, forbidden={sorted(forbidden)!r}, "
        f"cached_finders={sorted(cached_finders)!r}"
    )
pth = site / "pufferlib-editable.pth"
metadata = pth.lstat()
payload = pth.read_bytes()
expected_payload = (
    "import sys;sys.modules['sitecustomize']=sys\n"
    + str(root)
    + "\n"
).encode("utf-8")
if (
    pth.is_symlink()
    or not stat.S_ISREG(metadata.st_mode)
    or metadata.st_nlink != 1
    or payload != expected_payload
):
    raise SystemExit("sealed Puffer editable path hook differs")

runtime_source = r"""
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
runtime_text = subprocess.run(
    [
        str(venv / "bin/python"),
        "-B",
        "-I",
        "-c",
        runtime_source,
    ],
    check=True,
    capture_output=True,
    text=True,
    env={
        "PATH": os.defpath,
        "LC_ALL": "C",
        "PYTHONDONTWRITEBYTECODE": "1",
    },
).stdout
runtime = json.loads(runtime_text)
if runtime_text != (
    json.dumps(
        runtime,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    + "\n"
):
    raise SystemExit("sealed Puffer startup runtime is noncanonical")
if set(runtime) != {
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
}:
    raise SystemExit("sealed Puffer startup runtime field set differs")
expected_runtime = {
    "dont_write_bytecode": True,
    "implementation": "cpython",
    "isolated": 1,
    "no_site": 0,
    "platlibdir": "lib",
    "sitecustomize_is_sys": True,
    "user_site_enabled": False,
    "version": values["version"],
}
for key, expected in expected_runtime.items():
    if type(runtime.get(key)) is not type(expected) or runtime[key] != expected:
        raise SystemExit(
            "sealed Puffer startup runtime scalar differs: "
            f"{key}={runtime.get(key)!r}"
        )
try:
    base_prefix = Path(runtime["base_prefix"]).resolve(strict=True)
    prefix = Path(runtime["prefix"]).resolve(strict=True)
except (KeyError, OSError, TypeError) as exc:
    raise SystemExit(
        f"sealed Puffer startup prefixes cannot resolve: {exc}"
    ) from exc
if prefix != venv.resolve(strict=True):
    raise SystemExit("sealed Puffer startup prefix differs")
sys_path = runtime.get("sys_path")
if (
    not isinstance(sys_path, list)
    or not sys_path
    or any(not isinstance(item, str) or not item for item in sys_path)
    or sys_path.count(str(root)) != 1
    or sys_path.count(str(site)) != 1
):
    raise SystemExit("sealed Puffer startup sys.path differs")
for item in sys_path:
    if item in {str(root), str(site)}:
        continue
    candidate = Path(item)
    if not candidate.is_absolute():
        raise SystemExit(
            f"sealed Puffer startup has a relative sys.path entry: {item!r}"
        )
    try:
        candidate.resolve(strict=False).relative_to(base_prefix)
    except ValueError as exc:
        raise SystemExit(
            "sealed Puffer startup imported a path outside the trusted "
            f"base stdlib, venv, and pinned root: {item!r}"
        ) from exc
print(
    "sealed Puffer Python startup: OK "
    f"(sha256={hashlib.sha256(payload).hexdigest()}; "
    "base_sitecustomize=blocked)"
)
PY
}

check_qualification_requirements_identity() {
    "$INSTALL_PYTHON" -B -I -S - "$QUALIFICATION_REQUIREMENTS" \
        "$QUALIFICATION_REQUIREMENTS_SHA256" <<'PY'
import hashlib
import stat
import sys
from pathlib import Path

path = Path(sys.argv[1])
expected = sys.argv[2]
try:
    metadata = path.lstat()
except OSError as exc:
    raise SystemExit(f"cannot stat sealed F5 requirements: {exc}")
if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
    raise SystemExit("sealed F5 requirements must be a regular non-link file")
try:
    payload = path.read_bytes()
except OSError as exc:
    raise SystemExit(f"cannot read sealed F5 requirements: {exc}")
observed = hashlib.sha256(payload).hexdigest()
if observed != expected:
    raise SystemExit(
        "sealed F5 requirements identity differs; "
        f"expected={expected}, observed={observed}"
    )
PY
}

check_qualification_python_platform() {
    [ -x "$PYBIN" ] || {
        echo "error: Puffer virtualenv Python is missing: $PYBIN" >&2
        return 1
    }
    "$PYBIN" -B -I - <<'PY'
import platform
import sys

machine = platform.machine().lower()
actual = (sys.implementation.name, sys.version_info[:2], sys.platform, machine)
supported = {
    ("cpython", (3, 12), "darwin", "arm64"),
    ("cpython", (3, 12), "linux", "x86_64"),
}
if actual not in supported:
    raise SystemExit(
        "sealed F5 dependency platform must be exactly CPython 3.12 on "
        f"Darwin arm64 or Linux x86_64; observed={actual!r}"
    )
PY
}

verify_qualification_direct_dependencies() {
    check_qualification_python_platform
    (cd "$PUFFER" && "$PYBIN" -B -I - "$PUFFER" <<'PY'
import importlib.metadata
import sys
from pathlib import Path

puffer_root = Path(sys.argv[1]).resolve(strict=True)
venv_root = (puffer_root / ".venv").resolve(strict=True)
sys.path.insert(0, str(puffer_root))
if Path(sys.prefix).resolve(strict=True) != venv_root:
    raise SystemExit(
        f"sealed dependencies escaped Puffer venv: {sys.prefix!r}"
    )
if sys.platform == "darwin":
    torch_version = "2.9.1"
elif sys.platform == "linux":
    torch_version = "2.9.1+cpu"
else:
    raise SystemExit(
        f"sealed F5 Torch CPU layer does not support {sys.platform!r}"
    )
expected = {
    "numpy": "2.5.1",
    "torch": torch_version,
    "rich": "15.0.0",
    "rich-argparse": "1.8.0",
}
observed = {
    name: importlib.metadata.version(name)
    for name in expected
}
if observed != expected:
    raise SystemExit(
        f"sealed F5 direct dependency versions differ; "
        f"expected={expected!r}, observed={observed!r}"
    )

import numpy
import rich
import rich_argparse
import torch
import pufferlib.torch_pufferl as torch_pufferl

if numpy.__version__ != expected["numpy"]:
    raise SystemExit("imported NumPy version differs from installed metadata")
if torch.__version__ != expected["torch"]:
    raise SystemExit("imported Torch version differs from installed metadata")
if torch.version.cuda is not None or torch.cuda.is_available() is not False:
    raise SystemExit(
        "sealed F5 dependency layer must use Torch CPU, never CUDA Torch"
    )

def require_beneath(module, root: Path, name: str) -> None:
    raw = getattr(module, "__file__", None)
    if not isinstance(raw, str):
        raise SystemExit(f"sealed dependency {name} has no module file")
    try:
        Path(raw).resolve(strict=True).relative_to(root)
    except (OSError, ValueError) as exc:
        raise SystemExit(
            f"sealed dependency {name} escaped {root}: {raw!r}"
        ) from exc

for module, name in (
    (numpy, "numpy"),
    (torch, "torch"),
    (rich, "rich"),
    (rich_argparse, "rich-argparse"),
):
    require_beneath(module, venv_root, name)
require_beneath(
    torch_pufferl,
    puffer_root / "pufferlib",
    "pufferlib.torch_pufferl",
)
print(
    "sealed F5 dependencies: OK "
    f"(numpy={observed['numpy']}; torch={observed['torch']} CPU; "
    f"rich={observed['rich']}; rich-argparse={observed['rich-argparse']})"
)
PY
    )
    (cd "$PUFFER" && "$PYBIN" -B -I -m pip \
        --isolated \
        --disable-pip-version-check \
        check)
}

qualification_dependency_snapshot() {
    local snapshot_mode="$1"
    (cd "$PUFFER" && "$PYBIN" -B -I - \
        "$snapshot_mode" \
        "$QUALIFICATION_REQUIREMENTS_SHA256" \
        "$DEPENDENCY_SNAPSHOT" \
        "$DEPENDENCY_SNAPSHOT_SHA256" <<'PY'
import hashlib
import importlib.metadata
import json
import os
import platform
import re
import stat
import sys
import sysconfig
import tempfile
from pathlib import Path

mode, requirements_sha256, snapshot_raw, digest_raw = sys.argv[1:5]
if mode not in ("publish", "verify"):
    raise SystemExit(f"invalid dependency-snapshot mode: {mode!r}")
snapshot_path = Path(snapshot_raw)
digest_path = Path(digest_raw)
venv_root = Path(sys.prefix).resolve(strict=True)
machine = platform.machine().lower()
actual_platform = (
    sys.implementation.name,
    sys.version_info[:2],
    sys.platform,
    machine,
)
supported = {
    ("cpython", (3, 12), "darwin", "arm64"),
    ("cpython", (3, 12), "linux", "x86_64"),
}
if actual_platform not in supported:
    raise SystemExit(f"unsupported dependency-snapshot platform: {actual_platform!r}")
torch_version = "2.9.1" if sys.platform == "darwin" else "2.9.1+cpu"
direct = {
    "numpy": "2.5.1",
    "rich": "15.0.0",
    "rich-argparse": "1.8.0",
    "torch": torch_version,
}

site_directories = []
for key in ("purelib", "platlib"):
    directory = Path(sysconfig.get_paths()[key]).resolve(strict=True)
    try:
        directory.relative_to(venv_root)
    except ValueError as exc:
        raise SystemExit(
            f"dependency metadata path escaped Puffer venv: {directory}"
        ) from exc
    if directory not in site_directories:
        site_directories.append(directory)

def canonical_name(value: str) -> str:
    return re.sub(r"[-_.]+", "-", value).lower()

installed = {}
for distribution in importlib.metadata.distributions(
        path=[str(path) for path in site_directories]):
    raw_name = distribution.metadata.get("Name")
    version = distribution.version
    if not isinstance(raw_name, str) or not raw_name or not version:
        raise SystemExit("installed distribution lacks a name or version")
    name = canonical_name(raw_name)
    if name in installed:
        raise SystemExit(f"duplicate installed distribution metadata: {name}")
    installed[name] = version
for name, version in direct.items():
    if installed.get(name) != version:
        raise SystemExit(
            f"direct dependency missing from complete snapshot: "
            f"{name}={installed.get(name)!r}, expected={version!r}"
        )

document = {
    "schema": "bloodbowl-f5-python-distributions-v1",
    "requirements_sha256": requirements_sha256,
    "direct_requirements": direct,
    "python": {
        "implementation": sys.implementation.name,
        "version": platform.python_version(),
    },
    "platform": {
        "sys_platform": sys.platform,
        "machine": machine,
    },
    "distributions": [
        {"name": name, "version": installed[name]}
        for name in sorted(installed)
    ],
}
payload = (
    json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )
    + "\n"
).encode("ascii")
digest = hashlib.sha256(payload).hexdigest()
digest_payload = (digest + "\n").encode("ascii")

def atomic_write(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.",
        dir=path.parent,
    )
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
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

def read_exact_regular(path: Path, limit: int, label: str) -> bytes:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SystemExit(f"cannot stat {label}: {exc}")
    if path.is_symlink() or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit(f"{label} must be a regular non-link file")
    if metadata.st_size > limit:
        raise SystemExit(f"{label} exceeds {limit} bytes")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise SystemExit(f"cannot read {label}: {exc}")

if mode == "publish":
    atomic_write(snapshot_path, payload)
    atomic_write(digest_path, digest_payload)

observed_payload = read_exact_regular(
    snapshot_path,
    1 << 20,
    "sealed dependency snapshot",
)
observed_digest = read_exact_regular(
    digest_path,
    65,
    "sealed dependency snapshot digest",
)
if observed_payload != payload:
    raise SystemExit(
        "installed distributions differ from sealed dependency snapshot"
    )
if observed_digest != digest_payload:
    raise SystemExit(
        "sealed dependency snapshot digest file is stale or noncanonical"
    )
print(
    "sealed F5 dependency snapshot: OK "
    f"(sha256={digest}; distributions={len(installed)})"
)
PY
    )
}

verify_qualification_dependencies() {
    check_puffer_python_startup
    verify_qualification_direct_dependencies
    qualification_dependency_snapshot verify
}

install_qualification_dependencies() {
    check_qualification_python_platform
    (cd "$PUFFER" && "$PYBIN" -B -I -m pip install \
        --isolated \
        --disable-pip-version-check \
        --no-input \
        --no-cache-dir \
        --no-compile \
        --requirement "$QUALIFICATION_REQUIREMENTS")
    check_puffer_python_startup
    verify_qualification_direct_dependencies
    qualification_dependency_snapshot publish
}

known_ordinary_status_only() {
    "$INSTALL_PYTHON" -B -I -S - "$PUFFER" <<'PY'
import subprocess
import sys

root = sys.argv[1]
allowed_modified = {
    "build.sh",
    "pufferlib/pufferl.py",
    "pufferlib/selfplay.py",
    "pufferlib/sweep.py",
    "pufferlib/torch_pufferl.py",
    "src/bindings.cu",
    "src/bindings_cpu.cpp",
    "src/kernels.cu",
    "src/pufferlib.cu",
    "src/vecenv.h",
    "tests/profile_kernels.cu",
}
status = subprocess.run(
    ["git", "-C", root, "status", "--porcelain=v1", "--untracked-files=all"],
    check=True,
    stdout=subprocess.PIPE,
    text=True,
).stdout.splitlines()
observed_modified = set()
unknown = []
for line in status:
    if len(line) < 4:
        unknown.append(line)
        continue
    code, path = line[:2], line[3:]
    if " -> " in path:
        unknown.append(line)
    elif code == " M" and path in allowed_modified:
        observed_modified.add(path)
    elif code == "??" and (
        path == "bloodbowl"
        or path == "config/bloodbowl.ini"
        or path == "src/exact_action_build_hash.h"
        or path.startswith("ocean/bloodbowl/")
    ):
        pass
    else:
        unknown.append(line)
missing = sorted(allowed_modified - observed_modified)
if missing or unknown:
    print(
        "F5 installer requires the exact ordinary patched worktree; "
        f"missing_modified={missing}, unknown_status={unknown}",
        file=sys.stderr,
    )
    raise SystemExit(1)
PY
}

exact_patch_stack_valid() {
    local index_dir index_path exact_patch status
    index_dir="$(mktemp -d "${TMPDIR:-/tmp}/f5-patch-index.XXXXXX")" || \
        return 1
    index_path="$index_dir/index"
    status=0
    GIT_INDEX_FILE="$index_path" git -C "$PUFFER" read-tree HEAD || status=1
    if [ "$status" -eq 0 ]; then
        GIT_INDEX_FILE="$index_path" git -C "$PUFFER" add -A || status=1
    fi
    if [ "$status" -eq 0 ]; then
        GIT_INDEX_FILE="$index_path" git -C "$PUFFER" apply \
            --cached --reverse --check "$ROLE_PATCH" || status=1
    fi
    if [ "$status" -eq 0 ]; then
        GIT_INDEX_FILE="$index_path" git -C "$PUFFER" apply \
            --cached --reverse "$ROLE_PATCH" || status=1
    fi
    if [ "$status" -eq 0 ]; then
        GIT_INDEX_FILE="$index_path" git -C "$PUFFER" apply \
            --cached --reverse --check \
            "$ROOT/training/puffer_raylib_pin.patch" || status=1
    fi
    if [ "$status" -eq 0 ]; then
        GIT_INDEX_FILE="$index_path" git -C "$PUFFER" apply \
            --cached --reverse \
            "$ROOT/training/puffer_raylib_pin.patch" || status=1
    fi
    if [ "$status" -eq 0 ]; then
        GIT_INDEX_FILE="$index_path" git -C "$PUFFER" apply \
            --cached --reverse --check \
            "$ROOT/training/puffer_portable_simd_flags.patch" || status=1
    fi
    if [ "$status" -eq 0 ]; then
        GIT_INDEX_FILE="$index_path" git -C "$PUFFER" apply \
            --cached --reverse \
            "$ROOT/training/puffer_portable_simd_flags.patch" || status=1
    fi
    if [ "$status" -eq 0 ]; then
        for exact_patch in \
            "$ROOT/training/puffer_standalone_env_include.patch" \
            "$ROOT/training/puffer_dict_capacity.patch" \
            "$ROOT/training/puffer_exact_joint_actions.patch" \
            "$ROOT/training/puffer_recurrent_eval_state.patch" \
            "$ROOT/training/puffer_rollout_transition_closure.patch" \
            "$ROOT/training/puffer_frozen_prio_mask.patch" \
            "$ROOT/training/puffer_entropy_schedule_parity.patch" \
            "$ROOT/training/puffer_recurrent_cuda_qualification.patch" \
            "$ROOT/training/puffer_reward_clamp_range.patch" \
            "$ROOT/training/pufferl_scripted_training_guard.patch" \
            "$ROOT/training/pufferl_warm_start.patch" \
            "$ROOT/training/puffer_state_bank_contract.patch" \
            "$ROOT/training/puffer_strict_environment_config.patch"; do
            if ! GIT_INDEX_FILE="$index_path" git -C "$PUFFER" apply \
                    --cached --reverse --check "$exact_patch"; then
                echo "error: stale ordinary patch beneath F5 role: $exact_patch" >&2
                status=1
                break
            fi
        done
    fi
    rm -f "$index_path" "$index_path.lock"
    rmdir "$index_dir" 2>/dev/null || true
    return "$status"
}

stage_exact_f5_authority() {
    "$INSTALL_PYTHON" -B -I -S - "$ROOT/tools" "$PUFFER" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import state_bank_contract as contract

root = Path(sys.argv[2])
authority = root / "src/exact_action_build_hash.h"
contract.check_no_bank_install(root)
macros = contract.parse_generated_header(authority)
exact = {
    "enabled": 1,
    "role": "f5-fixed-state-v1",
    "schema": "bloodbowl-trainability-task-v1",
    "qualification_only": 1,
    "match_sha256":
        "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2",
    "bbs_sha256":
        "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71",
    "bundle_sha256":
        "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1",
    "bbs_source_id": 0xA9000019,
    "authored_source_id": 0xAE00001A,
    "reference_trace_schema": "bloodbowl-f5-reference-trace-v1",
    "reference_trace_sha256":
        "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300",
    "max_decisions": 8,
    "reward_contract": "touchdown-zero-sum-only-v1",
}
for field, macro in contract.QUALIFICATION_FIELD_TO_MACRO.items():
    macros[macro] = exact[field]
lines = ["#pragma once"]
ordered = (
    contract.BASE_BUILD_MACROS
    + contract.QUALIFICATION_FIXTURE_MACROS
    + contract.STATE_BANK_MACROS
)
for macro in ordered:
    value = macros[macro]
    if isinstance(value, str):
        lines.append(f'#define {macro} "{value}"')
    else:
        lines.append(f"#define {macro} {value}")
payload = ("\n".join(lines) + "\n").encode("ascii")
contract._atomic_write(authority, payload)
if contract.show_qualification_fixture(root) != exact:
    raise SystemExit("staged F5 authority did not round-trip exactly")
if contract.show_installed(root) != contract.NO_BANK_STATE_FIELDS:
    raise SystemExit("staged F5 authority changed state-bank kind NONE")
PY
}

check_exact_f5_authority() {
    "$INSTALL_PYTHON" -B -I -S - "$ROOT/tools" "$PUFFER" <<'PY'
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import state_bank_contract as contract

root = Path(sys.argv[2])
exact = {
    "enabled": 1,
    "role": "f5-fixed-state-v1",
    "schema": "bloodbowl-trainability-task-v1",
    "qualification_only": 1,
    "match_sha256":
        "aab28e6e08184d05a6912d033899916d0228984c38c87e606ee3f2a5d25ac9f2",
    "bbs_sha256":
        "0fe8f1ea3f0470bef2c43709947d2bd3a9fd418b0b7b9d5ca93003e720702e71",
    "bundle_sha256":
        "c984e22178901539157be062764dcaff1efac345836dffb5be17a5b7537447a1",
    "bbs_source_id": 0xA9000019,
    "authored_source_id": 0xAE00001A,
    "reference_trace_schema": "bloodbowl-f5-reference-trace-v1",
    "reference_trace_sha256":
        "456e336e5eaa92e4e5fdedfb753d237a163e9a8e4e58ff09fa8979d2a91f4300",
    "max_decisions": 8,
    "reward_contract": "touchdown-zero-sum-only-v1",
}
observed = contract.show_qualification_fixture(root)
if observed != exact:
    raise SystemExit(
        f"qualification authority differs; expected={exact!r}, observed={observed!r}"
    )
if contract.show_installed(root) != contract.NO_BANK_STATE_FIELDS:
    raise SystemExit("qualification authority changed state-bank kind NONE")
PY
}

check_staged_base_authority() {
    "$INSTALL_PYTHON" -B -I -S - "$ROOT/tools" "$PUFFER" \
        "$BACKEND_HASH" "$ROOT_SOURCE_HASH" <<'PY'
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
import state_bank_contract as contract

root = Path(sys.argv[2])
expected_backend, expected_environment = sys.argv[3:5]
macros = contract.parse_generated_header(
    root / "src/exact_action_build_hash.h"
)
expected = {
    "PUFFER_EXACT_ACTION_SOURCE_HASH": expected_backend,
    "PUFFER_ENV_SOURCE_HASH": expected_environment,
    "PUFFER_OBSERVATION_ABI": "obs-v6",
    "PUFFER_OBSERVATION_VERSION": 6,
    "PUFFER_ACTION_ABI": "exact-joint-v1",
}
observed = {macro: macros[macro] for macro in expected}
if observed != expected:
    raise SystemExit(
        f"staged base authority differs; expected={expected!r}, "
        f"observed={observed!r}"
    )

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
    raise SystemExit(
        f"sealed F5 tree retains state-bank artifacts: {present!r}"
    )
bridge_path = root / "ocean/bloodbowl/state_bank_build.h"
bridge = contract.read_bounded_file(
    bridge_path,
    contract.MAX_MANIFEST_BYTES,
    "state-bank header bridge",
)
expected_bridge = (
    "#pragma once\n"
    '#include "../../src/exact_action_build_hash.h"\n'
).encode("ascii")
if bridge != expected_bridge:
    raise SystemExit("sealed F5 state-bank bridge is not exact")
PY
}

validate_staged_source_closure() {
    check_qualification_requirements_identity
    ROOT_SOURCE_HASH="$(
        "$INSTALL_PYTHON" -B -I -S "$ROOT/tools/state_bank_contract.py" \
            environment-source-sha256 --root "$ROOT/puffer/bloodbowl" --plain
    )"
    INSTALLED_SOURCE_HASH="$(
        "$INSTALL_PYTHON" -B -I -S "$ROOT/tools/state_bank_contract.py" \
            environment-source-sha256 --root "$DST" --plain
    )"
    RECORDED_SOURCE_HASH="$(cat "$DST/.content_hash" 2>/dev/null || true)"
    [ "$ROOT_SOURCE_HASH" = "$INSTALLED_SOURCE_HASH" ] && \
    [ "$ROOT_SOURCE_HASH" = "$RECORDED_SOURCE_HASH" ] || {
        echo "error: F5 installed environment snapshot is stale" >&2
        return 1
    }
    cmp -s "$ROOT/puffer/config/bloodbowl.ini" \
        "$PUFFER/config/bloodbowl.ini" || {
        echo "error: installed bloodbowl.ini is stale" >&2
        return 1
    }

    BACKEND_HASH="$(
        "$INSTALL_PYTHON" -B -I -S "$ROOT/tools/puffer_source_manifest.py" \
            --root "$PUFFER" \
            --ledger "$LEDGER" \
            --expected-count 15 \
            --require-native-extension-closure \
            --plain
    )" || {
        echo "error: F5 exact-action backend source closure is invalid" >&2
        return 1
    }
    check_staged_base_authority
}

[ -f "$ROLE_PATCH" ] || {
    echo "error: missing $ROLE_PATCH" >&2
    exit 1
}
check_puffer_python_startup
check_qualification_requirements_identity

if [ "$MODE" = "install" ]; then
    if check_exact_f5_authority >/dev/null 2>&1; then
        echo "error: F5 install requires an ordinary role-none tree; " \
             "f5-fixed-state-v1 is already staged" >&2
        echo "       use --check to validate this isolated role tree" >&2
        exit 1
    else
        # This proves a built/importable ordinary module and exact ordinary
        # source snapshot before any qualification field changes.
        /bin/bash "$ROOT/tools/install_puffer_env.sh" --check "$PUFFER"
        known_ordinary_status_only
        install_qualification_dependencies
        stage_exact_f5_authority
        echo "staged:    f5-fixed-state-v1"
    fi
    echo "authority: $AUTHORITY"
    echo "CPU build: cd $PUFFER && ./build.sh bloodbowl --cpu"
    echo "           cd $PUFFER && ./build.sh bloodbowl --fast"
    echo "verify:    $ROOT/tools/install_f5_trainability_env.sh --check $PUFFER"
    echo "CUDA:      cd $PUFFER && ./build.sh bloodbowl"
    echo "           --check validates CUDA metadata/source closure only;"
    echo "           CUDA runtime qualification remains an external GPU gate."
    echo "restore:   discard this isolated tree and recreate an ordinary one."
    exit 0
fi

known_ordinary_status_only
check_exact_f5_authority
git -C "$PUFFER" apply --reverse --check --no-index "$ROLE_PATCH" || {
    echo "error: exact F5 CPU/CUDA export patch is missing or stale" >&2
    exit 1
}
exact_patch_stack_valid || {
    echo "error: installed F5 Puffer patch stack is stale" >&2
    exit 1
}
validate_staged_source_closure
verify_qualification_dependencies
MODULE_PATH="$("$PYBIN" -B -I - "$PUFFER" <<'PY'
import sys
from pathlib import Path

puffer_root = Path(sys.argv[1]).resolve(strict=True)
sys.path.insert(0, str(puffer_root))
from pufferlib import _C

print(Path(_C.__file__).resolve(strict=True))
PY
)" || {
    echo "error: F5 Puffer module cannot be imported" >&2
    exit 1
}
[ -f "$MODULE_PATH" ] || {
    echo "error: imported F5 module is missing: $MODULE_PATH" >&2
    exit 1
}
[ "$MODULE_PATH" -nt "$AUTHORITY" ] && \
[ "$MODULE_PATH" -nt "$DST/.content_hash" ] || {
    echo "error: F5 module predates the staged authority or environment snapshot" >&2
    exit 1
}

COMPILED_GPU="$("$PYBIN" -B -I - "$PUFFER" "$ROOT/tools" \
    "$BACKEND_HASH" "$ROOT_SOURCE_HASH" <<'PY'
import sys

puffer_root, source_tools = sys.argv[1:3]
sys.path.insert(0, puffer_root)
sys.path.insert(0, source_tools)
import state_bank_contract as contract
from pufferlib import _C

expected_backend, expected_environment = sys.argv[3:5]
header = contract.show_qualification_fixture(puffer_root)
module = contract.qualification_fixture_from_module(_C)
if module != header:
    raise SystemExit(
        f"compiled F5 role differs from authority: header={header!r}, module={module!r}"
    )
if contract.contract_from_module(_C) != contract.NO_BANK_STATE_FIELDS:
    raise SystemExit("compiled F5 module changed state-bank kind NONE")
if getattr(_C, "qualification_fixture_environment_source_sha256", None) != \
        expected_environment:
    raise SystemExit("compiled F5 environment identity differs")
if getattr(_C, "environment_source_hash", None) != expected_environment:
    raise SystemExit("compiled environment source hash differs")
if getattr(_C, "exact_action_source_hash", None) != expected_backend:
    raise SystemExit("compiled backend source hash differs")
if getattr(_C, "strict_env_config_testing", None) is not False:
    raise SystemExit("compiled F5 module uses the strict-config test role")
compiled_gpu = getattr(_C, "gpu", None)
if type(compiled_gpu) is not int or compiled_gpu not in (0, 1):
    raise SystemExit(
        f"compiled F5 module has invalid backend identity: {compiled_gpu!r}"
    )
print(compiled_gpu)
PY
)"

if [ "$COMPILED_GPU" -eq 0 ]; then
    MODULE_CHECK_DIR="$(
        mktemp -d "${TMPDIR:-/tmp}/f5-module-check.XXXXXX"
    )"
    if ! "$PYBIN" -B -I "$ROOT/tools/check_f5_trainability_module.py" \
            --puffer-root "$PUFFER" \
            --output "$MODULE_CHECK_DIR/module-check.json"; then
        rm -f "$MODULE_CHECK_DIR/module-check.json"
        rmdir "$MODULE_CHECK_DIR" 2>/dev/null || true
        echo "error: F5 exact reset/reference/autoreset module oracle failed" >&2
        exit 1
    fi
    rm -f "$MODULE_CHECK_DIR/module-check.json"
    rmdir "$MODULE_CHECK_DIR" 2>/dev/null || true
    echo "F5 qualification drift check: OK (CPU exact runtime oracle; state bank NONE)"
else
    echo "F5 qualification drift check: OK (CUDA metadata/source closure; state bank NONE)"
    echo "note: deterministic foundation runtime evidence is CPU-only;" >&2
    echo "      CUDA runtime qualification remains an external GPU gate." >&2
fi
