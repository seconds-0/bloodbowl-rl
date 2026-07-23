#!/usr/bin/env python3
"""Freeze and validate one replacement exact-action canary authority.

This module is deliberately not a general training launcher.  It owns the
closed plan/launch evidence contract for the single fresh 50M seed-42 canary.
Qualification and canary outputs remain ancestry- and reward-evidence-ineligible.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import stat
import subprocess
import sys
from typing import Any, Mapping

try:
    from live_integrity_guard import HARD_INTEGRITY_KEYS
    import recovery_preservation
except ModuleNotFoundError:  # Imported as tools.exact_action_canary_authority.
    from tools.live_integrity_guard import HARD_INTEGRITY_KEYS
    from tools import recovery_preservation


SCHEMA_VERSION = 1
PLAN_KIND = "exact_action_canary_plan_authorization"
LAUNCH_KIND = "exact_action_canary_launch_authorization"
CONSUMPTION_KIND = "exact_action_canary_launch_consumption"
MANDATORY_QUALIFICATION_GATES = (
    "construction_state",
    "graph_parity",
    "terminal_reset",
    "ratio",
    "throughput",
)
REQUIRED_CELL_NAMES = (
    "construction",
    "graph-off",
    "graph-on",
    "terminal-auto",
    "terminal-control",
    "ratio",
    "throughput",
)
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()
CANARY_PROFILE = "exact-action-canary"
CANARY_PREFIX = "exact-action-canary-50m-s42-v4"
CANARY_STEPS = 50_000_000
CANARY_POLL_SECONDS = 30
CANARY_ARM_DETACH = 0
CANARY_PLAN_ONLY = 0
CANARY_UNIT_NAME = "bloodbowl-exact-action-canary-50m-s42-v4.service"
CANARY_LAUNCH_CONSUMPTION_NAME = "CANARY_LAUNCH_CONSUMPTION.json"
EXPECTED_RECOVERY_ROOT = "/home/rache/bloodbowl-rl-recovery-20260719"
EXPECTED_RECOVERY_QUEUE_ID = "vacation-r0-overflow-recovery-20260719-v1"
EXPECTED_RECOVERY_PLAN_SHA256 = (
    "822bb912dbf3992c5fa6f04ddcaa5354897db10d03f2e66934b846c198b6a111"
)
EXPECTED_RECOVERY_VERIFICATION_SHA256 = (
    "53008b4176d54827d65eed58ee9b1c0efb4956710da14f294269dc4dfbead07b"
)
EXPECTED_RECOVERY_INVENTORY_FILE_SHA256 = (
    "1f0a11977c284483e2d36380b2a2a46c1734ae6b9318ea44c8d24195ff291d40"
)
EXPECTED_RECOVERY_INVENTORY_IDENTITY = (
    "d0102a612b4b295923bb875e604bd7d7863160a549d708aeb25c405b31c069d8"
)
EXPECTED_RECOVERY_FILE_COUNT = 37
EXPECTED_RECOVERY_TOTAL_BYTES = 3_493_832_521


class AuthorityError(RuntimeError):
    """A canary prerequisite or immutable-authority contract failed."""


@dataclass(frozen=True)
class UnitPaths:
    source_root: Path
    qualification_runner_root: Path
    qualification: Path
    output: Path
    launch_authorization: Path
    launch_authorization_sha: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise AuthorityError(f"cannot read {label} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise AuthorityError(f"{label} must be one JSON object: {path}")
    return payload


def _exact_absolute_file(path: Path, label: str) -> Path:
    if not path.is_absolute() or path.resolve() != path:
        raise AuthorityError(f"{label} must be an exact absolute path: {path}")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise AuthorityError(f"missing {label}: {path}") from exc
    if not stat.S_ISREG(mode) or path.is_symlink():
        raise AuthorityError(f"{label} must be a regular file: {path}")
    return path


def _exact_absolute_executable(path: Path, label: str) -> Path:
    """Accept an exact executable path, including a normal venv symlink."""
    if not path.is_absolute() or Path(os.path.abspath(path)) != path:
        raise AuthorityError(f"{label} must be an exact absolute path: {path}")
    try:
        mode = path.lstat().st_mode
        resolved = path.resolve(strict=True)
        resolved_mode = resolved.stat().st_mode
    except OSError as exc:
        raise AuthorityError(f"missing {label}: {path}") from exc
    if not (stat.S_ISREG(mode) or stat.S_ISLNK(mode)):
        raise AuthorityError(f"{label} must be a file or symlink: {path}")
    if not stat.S_ISREG(resolved_mode) or not os.access(resolved, os.X_OK):
        raise AuthorityError(
            f"{label} must resolve to a regular executable: {path}"
        )
    return path


def _exact_absolute_directory(path: Path, label: str) -> Path:
    if not path.is_absolute() or path.resolve() != path:
        raise AuthorityError(f"{label} must be an exact absolute path: {path}")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise AuthorityError(f"missing {label}: {path}") from exc
    if not stat.S_ISDIR(mode) or path.is_symlink():
        raise AuthorityError(f"{label} must be a directory: {path}")
    return path


def _git_output(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AuthorityError(
            f"git {' '.join(args)} failed for {root}: {result.stderr.strip()}"
        )
    return result.stdout.strip()


def _observe_source(root: Path) -> dict[str, str]:
    root = _exact_absolute_directory(root, "candidate source root")
    commit = _git_output(root, "rev-parse", "HEAD")
    tree = _git_output(root, "rev-parse", "HEAD^{tree}")
    dirty = _git_output(
        root, "status", "--porcelain=v1", "--untracked-files=no"
    )
    if dirty:
        raise AuthorityError("candidate source checkout has tracked changes")
    if len(commit) != 40 or len(tree) != 40:
        raise AuthorityError("candidate source commit/tree identity is malformed")
    return {"root": str(root), "commit": commit, "tree": tree}


def _require_keys(payload: Mapping[str, Any], keys: tuple[str, ...], label: str) -> None:
    missing = [key for key in keys if key not in payload]
    if missing:
        raise AuthorityError(f"{label} is missing fields: {', '.join(missing)}")


def _require_digest(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise AuthorityError(f"{label} is not a lowercase SHA-256 digest")
    return value


def _inventory(root: Path) -> list[dict[str, Any]]:
    root = _exact_absolute_directory(root, "inventory root")
    entries: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        mode = path.lstat().st_mode
        if path.is_symlink() or not stat.S_ISREG(mode):
            if stat.S_ISDIR(mode) and not path.is_symlink():
                continue
            raise AuthorityError(f"inventory contains unsupported entry: {path}")
        entries.append(
            {
                "path": relative,
                "mode": stat.S_IMODE(mode),
                "bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    return entries


def _run_qualification_validator(
    qualification: Path,
    *,
    source_root: Path,
    qualification_runner_root: Path,
) -> None:
    runner = _exact_absolute_file(
        qualification_runner_root / "tools" / "qualify_recurrent_cuda.py",
        "qualification validator",
    )
    python = _exact_absolute_executable(
        source_root / "vendor" / "PufferLib" / ".venv" / "bin" / "python",
        "candidate Python",
    )
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["CUDA_VISIBLE_DEVICES"] = "0"
    result = subprocess.run(
        [str(python), "-B", str(runner), "validate", str(qualification)],
        cwd=qualification_runner_root,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode != 0:
        raise AuthorityError(
            "fresh qualification validation failed: "
            + result.stderr.decode("utf-8", errors="replace").strip()
        )
    if result.stderr:
        raise AuthorityError("fresh qualification validation wrote stderr")


def _validate_runtime_evidence(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise AuthorityError(f"{label} CUDA runtime evidence is malformed")
    if value.get("cuda_visible_devices") != "0":
        raise AuthorityError(f"{label} CUDA_VISIBLE_DEVICES is not exactly 0")
    library = value.get("library")
    if not isinstance(library, dict):
        raise AuthorityError(f"{label} CUDA runtime library is malformed")
    path = _exact_absolute_file(
        Path(str(library.get("resolved_path", ""))),
        f"{label} CUDA runtime library",
    )
    digest = _require_digest(library.get("sha256"), f"{label} CUDART digest")
    if _sha256(path) != digest:
        raise AuthorityError(f"{label} CUDA runtime library digest drifted")
    if library.get("requested_soname") != "libcudart.so.12":
        raise AuthorityError(f"{label} CUDA runtime SONAME drifted")
    counts = []
    for stage in ("before_extension_import", "after_extension_import"):
        probe = value.get(stage)
        if (
            not isinstance(probe, dict)
            or probe.get("stage") != stage
            or probe.get("return_code") != 0
            or probe.get("error_name") != "cudaSuccess"
            or not isinstance(probe.get("device_count"), int)
            or probe["device_count"] <= 0
        ):
            raise AuthorityError(f"{label} {stage} CUDA probe did not accept")
        counts.append(probe["device_count"])
    if counts[0] != counts[1]:
        raise AuthorityError(f"{label} CUDA device count changed across import")
    return value


def _validate_identity(
    identity: Any, expected: Mapping[str, Any], source_root: Path
) -> dict[str, Any]:
    if not isinstance(identity, dict):
        raise AuthorityError("qualification candidate identity is malformed")
    exact = {
        "compiled_env": "bloodbowl",
        "precision_bytes": 4,
        "observation_abi": "obs-v5",
        "observation_version": 5,
        "action_abi": "exact-joint-v1",
        "qualification_surface": True,
        "puffer_root": str(source_root / "vendor" / "PufferLib"),
    }
    for key, required in exact.items():
        if identity.get(key) != required:
            raise AuthorityError(
                f"qualification candidate identity {key} mismatch: "
                f"{identity.get(key)!r} != {required!r}"
            )
    pairs = (
        ("module_sha256", "module_sha256"),
        ("backend_sources_sha256", "backend_sha256"),
        ("environment_sha256", "environment_sha256"),
    )
    for identity_key, expected_key in pairs:
        digest = _require_digest(
            identity.get(identity_key), f"candidate identity {identity_key}"
        )
        if digest != expected.get(expected_key):
            raise AuthorityError(
                f"qualification expected candidate {identity_key} mismatch"
            )
    if identity.get("compiled_backend_sha256") != identity.get(
        "backend_sources_sha256"
    ):
        raise AuthorityError("compiled/backend source identity mismatch")
    if identity.get("runtime_sources_sha256") != identity.get(
        "backend_sources_sha256"
    ):
        raise AuthorityError("candidate runtime/backend source identity mismatch")
    if identity.get("installed_snapshot_sha256") != identity.get(
        "environment_sha256"
    ):
        raise AuthorityError("candidate installed/environment identity mismatch")
    module = _exact_absolute_file(Path(str(identity.get("module", ""))), "module")
    if module.parent.parent.resolve() != Path(exact["puffer_root"]).resolve():
        raise AuthorityError("candidate module is outside exact Puffer root")
    if _sha256(module) != identity["module_sha256"]:
        raise AuthorityError("candidate compiled module digest drifted")
    return identity


def validate_qualification(
    qualification: Path,
    *,
    source_root: Path,
    qualification_runner_root: Path,
) -> dict[str, Any]:
    """Revalidate one accepted schema-3 qualification from current files."""
    qualification = _exact_absolute_file(qualification, "qualification")
    source_root = _exact_absolute_directory(source_root, "candidate source root")
    qualification_runner_root = _exact_absolute_directory(
        qualification_runner_root, "qualification runner source root"
    )
    if qualification_runner_root == source_root:
        raise AuthorityError(
            "qualification runner and candidate source roots must differ"
        )
    _run_qualification_validator(
        qualification,
        source_root=source_root,
        qualification_runner_root=qualification_runner_root,
    )
    source = _observe_source(source_root)
    qualification_runner = _observe_source(qualification_runner_root)
    payload = _read_json(qualification, "qualification")
    if payload.get("schema_version") != 3:
        raise AuthorityError("qualification schema must be exactly 3")
    if payload.get("qualification_only") is not True:
        raise AuthorityError("qualification must be qualification-only")
    if payload.get("accepted") is not True or payload.get("failed_gates") != []:
        raise AuthorityError("qualification is not an accepted zero-failure verdict")
    if tuple(payload.get("mandatory_gates", ())) != MANDATORY_QUALIFICATION_GATES:
        raise AuthorityError("qualification mandatory gate registry drifted")
    gates = payload.get("gates")
    if not isinstance(gates, dict) or set(gates) != set(MANDATORY_QUALIFICATION_GATES):
        raise AuthorityError("qualification mandatory gate set is incomplete")
    for name in MANDATORY_QUALIFICATION_GATES:
        if not isinstance(gates[name], dict) or gates[name].get("accepted") is not True:
            raise AuthorityError(f"qualification gate did not accept: {name}")

    candidate = payload.get("candidate_source")
    expected = payload.get("expected_candidate")
    if not isinstance(candidate, dict) or not isinstance(expected, dict):
        raise AuthorityError("qualification candidate source declaration is malformed")
    if candidate.get("role") != "candidate":
        raise AuthorityError("qualification candidate source role drifted")
    for label, observed in (
        ("candidate source root", candidate.get("source_root")),
        ("candidate Puffer root", candidate.get("puffer_root")),
    ):
        required = (
            str(source_root)
            if label == "candidate source root"
            else str(source_root / "vendor" / "PufferLib")
        )
        if observed != required:
            raise AuthorityError(f"{label} mismatch: {observed!r} != {required!r}")
    for label, observed in (
        ("candidate source commit", candidate.get("source_commit")),
        ("expected candidate commit", expected.get("source_commit")),
        ("runner source commit", payload.get("runner_source_commit")),
    ):
        if observed != source["commit"]:
            raise AuthorityError(f"{label} does not equal clean candidate HEAD")
    if qualification_runner["commit"] != payload.get("runner_source_commit"):
        raise AuthorityError(
            "qualification runner source commit does not equal recorded runner"
        )
    if qualification_runner["commit"] != source["commit"]:
        raise AuthorityError(
            "qualification runner and candidate commits must be identical"
        )
    _require_digest(payload.get("runner_sha256"), "qualification runner digest")
    _require_digest(
        candidate.get("installer_check_sha256"), "installer check digest"
    )
    identity = _validate_identity(payload.get("identity"), expected, source_root)

    for section_name, fields in (
        ("construction_gate", ("path", "sha256")),
        (
            "throughput_baseline",
            ("path", "sha256", "cell_record", "cell_record_sha256"),
        ),
    ):
        section = payload.get(section_name)
        if not isinstance(section, dict):
            raise AuthorityError(f"qualification {section_name} is malformed")
        _require_keys(section, fields, f"qualification {section_name}")
        for path_key, digest_key in zip(fields[::2], fields[1::2]):
            artifact = _exact_absolute_file(
                Path(str(section[path_key])), f"qualification {section_name} {path_key}"
            )
            if _sha256(artifact) != _require_digest(
                section[digest_key], f"qualification {section_name} {digest_key}"
            ):
                raise AuthorityError(f"qualification {section_name} artifact drifted")

    cells = payload.get("cells")
    if not isinstance(cells, list) or [cell.get("name") for cell in cells] != list(
        REQUIRED_CELL_NAMES
    ):
        raise AuthorityError("qualification cell registry/order drifted")
    runtime: dict[str, Any] | None = None
    for cell in cells:
        if not isinstance(cell, dict):
            raise AuthorityError("qualification cell declaration is malformed")
        record_path = _exact_absolute_file(
            Path(str(cell.get("record", ""))),
            f"qualification {cell.get('name')} record",
        )
        if _sha256(record_path) != _require_digest(
            cell.get("record_sha256"), f"qualification {cell.get('name')} record digest"
        ):
            raise AuthorityError(f"qualification {cell.get('name')} record drifted")
        name = str(cell.get("name"))
        expects_artifact = name not in {"construction", "throughput"}
        artifact = cell.get("artifact")
        artifact_sha256 = cell.get("artifact_sha256")
        if expects_artifact:
            artifact_path = _exact_absolute_file(
                Path(str(artifact)), f"qualification {name} artifact"
            )
            if _sha256(artifact_path) != _require_digest(
                artifact_sha256, f"qualification {name} artifact digest"
            ):
                raise AuthorityError(f"qualification {name} artifact drifted")
        elif artifact is not None or artifact_sha256 is not None:
            raise AuthorityError(
                f"qualification {name} must not declare a separate artifact"
            )
        record = _read_json(record_path, f"qualification {cell.get('name')} record")
        if record.get("accepted") is not True or record.get("qualification_only") is not True:
            raise AuthorityError(f"qualification cell did not accept: {cell.get('name')}")
        observed_runtime = _validate_runtime_evidence(
            record.get("cuda_runtime_preflight"), str(cell.get("name"))
        )
        if runtime is None:
            runtime = observed_runtime
        elif runtime != observed_runtime:
            raise AuthorityError("qualification CUDA runtime differs across cells")
        if name != "construction":
            integrity_payload = record.get("throughput") if name == "throughput" else record
            if not isinstance(integrity_payload, dict):
                raise AuthorityError(
                    f"qualification {name} hard-integrity payload is malformed"
                )
            hard = integrity_payload.get("hard_integrity")
            if not isinstance(hard, dict) or set(hard) != set(
                HARD_INTEGRITY_KEYS
            ):
                raise AuthorityError(
                    f"qualification {name} hard-integrity registry drifted"
                )
            if integrity_payload.get("hard_integrity_zero") is not True:
                raise AuthorityError(
                    f"qualification {name} hard-integrity verdict is false"
                )
            for key in HARD_INTEGRITY_KEYS:
                value = hard[key]
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or not math.isfinite(float(value))
                    or float(value) != 0.0
                ):
                    raise AuthorityError(
                        f"qualification {name} hard-integrity "
                        f"field is not exact zero: {key}"
                    )
    assert runtime is not None

    return {
        "source": source,
        "qualification_runner": qualification_runner,
        "qualification": {
            "path": str(qualification),
            "sha256": _sha256(qualification),
            "inventory": _inventory(qualification.parent),
            "runner_sha256": payload["runner_sha256"],
            "construction_gate": payload["construction_gate"],
            "throughput_baseline": payload["throughput_baseline"],
        },
        "candidate": identity,
        "cuda_runtime": runtime,
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
    }


def validate_plan_output(output: Path) -> list[dict[str, Any]]:
    """Require the launcher's closed two-regular-file plan-only output."""
    output = _exact_absolute_directory(output, "canary plan output")
    children = sorted(output.iterdir(), key=lambda path: path.name)
    if [child.name for child in children] != [".screen.lock", "SCREEN_MANIFEST.json"]:
        raise AuthorityError(
            "canary plan output must contain exactly .screen.lock and "
            "SCREEN_MANIFEST.json"
        )
    inventory = []
    for child in children:
        mode = child.lstat().st_mode
        if child.is_symlink() or not stat.S_ISREG(mode):
            raise AuthorityError(f"canary plan entry must be a regular file: {child}")
        inventory.append(
            {
                "path": child.name,
                "mode": stat.S_IMODE(mode),
                "bytes": child.stat().st_size,
                "sha256": _sha256(child),
            }
        )
    lock = output / ".screen.lock"
    if lock.stat().st_size != 0 or _sha256(lock) != EMPTY_SHA256:
        raise AuthorityError("canary plan lock must be the exact empty file")
    try:
        with lock.open("rb") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    except BlockingIOError as exc:
        raise AuthorityError("canary plan lock is still held") from exc
    after = []
    for child in sorted(output.iterdir(), key=lambda path: path.name):
        mode = child.lstat().st_mode
        if child.is_symlink() or not stat.S_ISREG(mode):
            raise AuthorityError(f"canary plan entry must be a regular file: {child}")
        after.append(
            {
                "path": child.name,
                "mode": stat.S_IMODE(mode),
                "bytes": child.stat().st_size,
                "sha256": _sha256(child),
            }
        )
    if after != inventory:
        raise AuthorityError("canary plan output changed during released-lock proof")
    return inventory


def render_systemd_unit(paths: UnitPaths) -> str:
    """Render the only one-shot systemd unit shape accepted by this tranche."""
    source = paths.source_root
    qualification_runner = paths.qualification_runner_root
    python = source / "vendor/PufferLib/.venv/bin/python"
    authority = source / "tools/exact_action_canary_authority.py"
    launcher = source / "tools/run_reward_screen.sh"
    consumption = paths.launch_authorization.with_name(
        CANARY_LAUNCH_CONSUMPTION_NAME
    )
    consumption_sha = consumption.with_suffix(".sha256")
    return f"""[Unit]
Description=Blood Bowl exact-action fresh 50M seed-42 qualification canary v4
After=default.target

[Service]
Type=oneshot
WorkingDirectory={source}
ExecStartPre={python} -B {authority} consume-launch --authorization {paths.launch_authorization} --sha256-file {paths.launch_authorization_sha} --destination {consumption}
ExecStartPre={python} -B {qualification_runner}/tools/qualify_recurrent_cuda.py validate {paths.qualification}
ExecStartPre=/usr/bin/bash -c 'set -euo pipefail; out="$$(/usr/local/bin/nvidia-smi --query-compute-apps=pid --format=csv,noheader,nounits)"; stripped="$$(/usr/bin/printf "%%s" "$${{out}}" | /usr/bin/tr -d "[:space:]")"; test -z "$${{stripped}}"'
ExecStart=/usr/bin/env -u WARM -u POOL PATH={python.parent}:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin CUDA_VISIBLE_DEVICES=0 OMP_NUM_THREADS=16 OPENBLAS_NUM_THREADS=16 MKL_NUM_THREADS=16 NUMEXPR_NUM_THREADS=16 STEPS=50000000 SCREEN_PROFILE=exact-action-canary PREFIX={CANARY_PREFIX} OUT_DIR={paths.output} POLL_SECONDS=30 PLAN_ONLY=0 ARM_DETACH=0 CANARY_LAUNCH_AUTHORIZATION={paths.launch_authorization} CANARY_LAUNCH_AUTHORIZATION_SHA256_FILE={paths.launch_authorization_sha} CANARY_LAUNCH_CONSUMPTION={consumption} CANARY_LAUNCH_CONSUMPTION_SHA256_FILE={consumption_sha} /usr/bin/bash {launcher}
Restart=no
KillMode=control-group
TimeoutStartSec=7200
TimeoutStopSec=60
SendSIGKILL=yes
UMask=0022
"""


def _file_identity(path: Path, label: str) -> dict[str, Any]:
    path = _exact_absolute_file(path, label)
    mode = path.lstat().st_mode
    return {
        "path": str(path),
        "mode": stat.S_IMODE(mode),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _validate_file_identity(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise AuthorityError(f"{label} identity is malformed")
    _require_keys(value, ("path", "mode", "bytes", "sha256"), label)
    current = _file_identity(Path(str(value["path"])), label)
    if current != value:
        raise AuthorityError(f"{label} file identity drifted")
    return value


def _validate_digest_sidecar(
    target: Path, sidecar: Path, *, label: str
) -> str:
    target = _exact_absolute_file(target, label)
    sidecar = _exact_absolute_file(sidecar, f"{label} digest sidecar")
    digest = _sha256(target)
    expected = f"{digest}  {target.name}\n"
    try:
        observed = sidecar.read_text(encoding="ascii")
    except (OSError, UnicodeError) as exc:
        raise AuthorityError(f"cannot read {label} digest sidecar: {exc}") from exc
    if observed != expected:
        raise AuthorityError(f"{label} digest sidecar mismatch")
    return digest


def _require_external_path(path: Path, source_root: Path, label: str) -> Path:
    if not path.is_absolute() or path.resolve(strict=False) != path:
        raise AuthorityError(f"{label} must be an exact absolute path: {path}")
    source_root = source_root.resolve()
    protected_root = Path("/home/rache/bloodbowl-rl-recovery-20260719")
    for forbidden, forbidden_label in (
        (source_root, "candidate source checkout"),
        (protected_root, "protected recovery root"),
    ):
        try:
            path.relative_to(forbidden)
        except ValueError:
            continue
        raise AuthorityError(f"{label} is inside the {forbidden_label}: {path}")
    return path


def _require_empty_directory(path: Path, label: str) -> Path:
    path = _exact_absolute_directory(path, label)
    if any(path.iterdir()):
        raise AuthorityError(f"{label} must be exactly empty: {path}")
    return path


def _expected_screen() -> dict[str, Any]:
    return {
        "profile": CANARY_PROFILE,
        "prefix": CANARY_PREFIX,
        "requested_steps": CANARY_STEPS,
        "final_steps": 49_938_432,
        "rollout_quantum": 131_072,
        "poll_seconds": CANARY_POLL_SECONDS,
        "arm_detach": CANARY_ARM_DETACH,
        "seed": 42,
        "arm": "both",
        "precision": "fp32",
        "observation_abi": "obs-v5",
        "observation_version": 5,
        "action_abi": "exact-joint-v1",
        "initialization": "fresh",
    }


def _validate_recovery_preservation(
    verification: Path, inventory: Path
) -> dict[str, Any]:
    verification = _exact_absolute_file(
        verification, "recovery preservation verification"
    )
    inventory = _exact_absolute_file(
        inventory, "recovery preservation inventory"
    )
    if _sha256(verification) != EXPECTED_RECOVERY_VERIFICATION_SHA256:
        raise AuthorityError("recovery preservation verification digest drifted")
    if _sha256(inventory) != EXPECTED_RECOVERY_INVENTORY_FILE_SHA256:
        raise AuthorityError("recovery preservation inventory file digest drifted")
    try:
        verdict = recovery_preservation.load_json(verification)
        manifest = recovery_preservation.load_json(inventory)
        recovery_preservation.validate_manifest(manifest)
    except recovery_preservation.PreservationError as exc:
        raise AuthorityError(f"recovery preservation evidence is invalid: {exc}") from exc
    expected_verdict = {
        "accepted": True,
        "file_count": EXPECTED_RECOVERY_FILE_COUNT,
        "total_bytes": EXPECTED_RECOVERY_TOTAL_BYTES,
        "inventory_sha256": EXPECTED_RECOVERY_INVENTORY_IDENTITY,
    }
    if verdict != expected_verdict:
        raise AuthorityError("recovery preservation verification schema drifted")
    for key, required in (
        ("schema_version", 1),
        ("kind", recovery_preservation.KIND),
        ("source_recovery_root", EXPECTED_RECOVERY_ROOT),
        ("queue_id", EXPECTED_RECOVERY_QUEUE_ID),
        ("queue_plan_sha256", EXPECTED_RECOVERY_PLAN_SHA256),
        ("file_count", EXPECTED_RECOVERY_FILE_COUNT),
        ("total_bytes", EXPECTED_RECOVERY_TOTAL_BYTES),
        ("inventory_sha256", EXPECTED_RECOVERY_INVENTORY_IDENTITY),
    ):
        if manifest.get(key) != required:
            raise AuthorityError(f"recovery preservation {key} drifted")
    return {
        "verification": _file_identity(
            verification, "recovery preservation verification"
        ),
        "inventory": _file_identity(
            inventory, "recovery preservation inventory"
        ),
        "verdict": verdict,
    }


def freeze_plan_authorization(
    *,
    destination: Path,
    qualification: Path,
    source_root: Path,
    qualification_runner_root: Path,
    screen_output: Path,
    recovery_verification: Path,
    recovery_inventory: Path,
    predecessor_root: Path,
) -> str:
    """Create the one pre-plan authority after fresh qualification validation."""
    source_root = _exact_absolute_directory(source_root, "candidate source root")
    destination = _require_external_path(
        destination, source_root, "plan authorization destination"
    )
    screen_output = _require_external_path(
        screen_output, source_root, "canary plan output"
    )
    if screen_output.exists() or screen_output.is_symlink():
        raise AuthorityError("canary plan output already exists")
    if not screen_output.parent.is_dir():
        raise AuthorityError("canary plan output parent must already exist")
    observed = validate_qualification(
        qualification,
        source_root=source_root,
        qualification_runner_root=qualification_runner_root,
    )
    recovery = _validate_recovery_preservation(
        recovery_verification, recovery_inventory
    )
    predecessor_root = _exact_absolute_directory(
        predecessor_root, "predecessor throughput root"
    )
    expected_predecessor_root = Path(
        observed["qualification"]["throughput_baseline"]["path"]
    ).parent
    if predecessor_root != expected_predecessor_root:
        raise AuthorityError(
            "predecessor root is not the accepted qualification baseline root"
        )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": PLAN_KIND,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "qualification_only": True,
        "source": observed["source"],
        "qualification_runner": observed["qualification_runner"],
        "qualification": observed["qualification"],
        "candidate": observed["candidate"],
        "cuda_runtime": observed["cuda_runtime"],
        "recovery": recovery,
        "predecessor": {
            "root": str(
                predecessor_root
            ),
            "inventory": _inventory(predecessor_root),
        },
        "screen": {
            **_expected_screen(),
            "output": str(screen_output),
        },
        "error_budget": {
            "contamination_budget": 0,
            "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
            "max_panel_silence_seconds": 180,
        },
        "eligibility": {
            "qualification_only": True,
            "checkpoint_ancestry": False,
            "reward_evidence": False,
            "promotion": False,
            "bbtv_follower": False,
        },
    }
    return write_authority(destination, payload)


def validate_plan_authorization(
    authorization: Path,
    *,
    sha256_file: Path,
    source_root: Path,
    require_output_absent: bool,
) -> dict[str, Any]:
    authorization = _exact_absolute_file(
        authorization, "canary plan authorization"
    )
    digest = _validate_digest_sidecar(
        authorization, sha256_file, label="canary plan authorization"
    )
    payload = _read_json(authorization, "canary plan authorization")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != PLAN_KIND:
        raise AuthorityError("canary plan authorization schema/kind mismatch")
    if payload.get("qualification_only") is not True:
        raise AuthorityError("canary plan authorization is not qualification-only")
    source_root = _exact_absolute_directory(source_root, "candidate source root")
    if payload.get("source", {}).get("root") != str(source_root):
        raise AuthorityError("canary plan authorization source root mismatch")
    qualification_section = payload.get("qualification")
    if not isinstance(qualification_section, dict):
        raise AuthorityError("canary plan qualification identity is malformed")
    qualification_runner = payload.get("qualification_runner")
    if not isinstance(qualification_runner, dict):
        raise AuthorityError(
            "canary plan qualification runner identity is malformed"
        )
    observed = validate_qualification(
        Path(str(qualification_section.get("path", ""))),
        source_root=source_root,
        qualification_runner_root=Path(
            str(qualification_runner.get("root", ""))
        ),
    )
    for key in (
        "source",
        "qualification_runner",
        "qualification",
        "candidate",
        "cuda_runtime",
    ):
        if payload.get(key) != observed.get(key):
            raise AuthorityError(f"canary plan {key} identity drifted")
    recovery = payload.get("recovery")
    if not isinstance(recovery, dict):
        raise AuthorityError("canary plan recovery identity is malformed")
    current_recovery = _validate_recovery_preservation(
        Path(str(recovery.get("verification", {}).get("path", ""))),
        Path(str(recovery.get("inventory", {}).get("path", ""))),
    )
    if recovery != current_recovery:
        raise AuthorityError("canary plan recovery preservation identity drifted")
    predecessor = payload.get("predecessor")
    if not isinstance(predecessor, dict):
        raise AuthorityError("canary plan predecessor identity is malformed")
    predecessor_root = _exact_absolute_directory(
        Path(str(predecessor.get("root", ""))), "predecessor throughput root"
    )
    expected_predecessor_root = Path(
        observed["qualification"]["throughput_baseline"]["path"]
    ).parent
    if predecessor_root != expected_predecessor_root:
        raise AuthorityError(
            "predecessor root is not the accepted qualification baseline root"
        )
    if predecessor.get("inventory") != _inventory(predecessor_root):
        raise AuthorityError("canary plan predecessor inventory drifted")
    screen = payload.get("screen")
    if not isinstance(screen, dict):
        raise AuthorityError("canary plan screen contract is malformed")
    output = _require_external_path(
        Path(str(screen.get("output", ""))),
        source_root,
        "canary plan output",
    )
    if screen != {**_expected_screen(), "output": str(output)}:
        raise AuthorityError("canary plan screen contract drifted")
    if require_output_absent and (output.exists() or output.is_symlink()):
        raise AuthorityError("canary plan output must be absent before plan-only")
    expected_budget = {
        "contamination_budget": 0,
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
        "max_panel_silence_seconds": 180,
    }
    if payload.get("error_budget") != expected_budget:
        raise AuthorityError("canary plan exact-zero error budget drifted")
    expected_eligibility = {
        "qualification_only": True,
        "checkpoint_ancestry": False,
        "reward_evidence": False,
        "promotion": False,
        "bbtv_follower": False,
    }
    if payload.get("eligibility") != expected_eligibility:
        raise AuthorityError("canary plan eligibility exclusions drifted")
    result = dict(payload)
    result["authorization_sha256"] = digest
    return result


def _validate_screen_manifest(
    manifest: Path, plan: Mapping[str, Any], plan_sha256: str
) -> dict[str, Any]:
    manifest = _exact_absolute_file(manifest, "canary screen manifest")
    payload = _read_json(manifest, "canary screen manifest")
    if payload.get("schema_version") != 1:
        raise AuthorityError("canary screen manifest schema drifted")
    contract = payload.get("contract")
    if not isinstance(contract, dict):
        raise AuthorityError("canary screen manifest contract is malformed")
    exact = {
        "screen_profile": CANARY_PROFILE,
        "qualification_only": True,
        "prefix": CANARY_PREFIX,
        "out_dir": plan["screen"]["output"],
        "requested_steps": CANARY_STEPS,
        "final_steps": 49_938_432,
        "rollout_quantum": 131_072,
        "schedule": [{"index": 1, "arm": "both", "seed": 42}],
        "warm": None,
        "pool": None,
    }
    for key, required in exact.items():
        if contract.get(key) != required:
            raise AuthorityError(f"canary screen manifest {key} drifted")
    bootstrap = contract.get("bootstrap")
    if bootstrap != {
        "mode": "fresh-v5-qualification",
        "observation_abi": "obs-v5",
        "observation_version": 5,
        "action_abi": "exact-joint-v1",
        "initialization": "fresh",
        "warm_lineage_sha256": "",
        "pool_lineage_bundle_sha256": "",
    }:
        raise AuthorityError("canary screen bootstrap contract drifted")
    settings = contract.get("settings")
    if not isinstance(settings, dict):
        raise AuthorityError("canary screen settings are malformed")
    required_settings = {
        "minibatch_size": "16384",
        "arm_detach": "0",
        "num_frozen_banks": "0",
        "frozen_bank_pct": "0",
        "native_precision_bytes": "4",
    }
    for key, required in required_settings.items():
        if settings.get(key) != required:
            raise AuthorityError(f"canary screen setting {key} drifted")
    if contract.get("error_budget") != {
        "contamination_budget": 0,
        "detection_poll_seconds": CANARY_POLL_SECONDS,
        "max_panel_silence_seconds": 180,
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
    }:
        raise AuthorityError("canary screen exact-zero error budget drifted")
    cuda = plan["cuda_runtime"]
    expected_authority = {
        "plan_authorization": plan["authorization_path"],
        "plan_authorization_sha256": plan_sha256,
        "qualification": plan["qualification"]["path"],
        "qualification_sha256": plan["qualification"]["sha256"],
        "cuda_runtime_library_path": cuda["library"]["resolved_path"],
        "cuda_runtime_library_sha256": cuda["library"]["sha256"],
        "cuda_runtime_device_count": cuda["after_extension_import"]["device_count"],
    }
    if contract.get("canary_authority") != expected_authority:
        raise AuthorityError("canary screen authority binding drifted")
    return payload


def write_unit(destination: Path, paths: UnitPaths) -> str:
    source_root = _exact_absolute_directory(
        paths.source_root, "candidate source root"
    )
    qualification_runner_root = _exact_absolute_directory(
        paths.qualification_runner_root, "qualification runner source root"
    )
    if qualification_runner_root == source_root:
        raise AuthorityError(
            "qualification runner and candidate source roots must differ"
        )
    qualification = _exact_absolute_file(
        paths.qualification, "qualification"
    )
    output = _exact_absolute_directory(paths.output, "canary plan output")
    launch_authorization = _require_external_path(
        paths.launch_authorization,
        source_root,
        "launch authorization destination",
    )
    launch_authorization_sha = _require_external_path(
        paths.launch_authorization_sha,
        source_root,
        "launch authorization digest destination",
    )
    paths = UnitPaths(
        source_root=source_root,
        qualification_runner_root=qualification_runner_root,
        qualification=qualification,
        output=output,
        launch_authorization=launch_authorization,
        launch_authorization_sha=launch_authorization_sha,
    )
    destination = _require_external_path(
        destination, source_root, "canary unit destination"
    )
    if not destination.parent.is_dir():
        raise AuthorityError("canary unit destination parent must already exist")
    if destination.exists() or destination.is_symlink():
        raise AuthorityError("canary unit destination already exists")
    raw = render_systemd_unit(paths).encode("utf-8")
    temporary = destination.with_name(
        f".{destination.name}.tmp.{os.getpid()}.{secrets.token_hex(8)}"
    )
    destination_published = False
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
        destination_published = True
    except OSError as exc:
        if destination_published:
            destination.unlink(missing_ok=True)
        raise AuthorityError(f"cannot publish canary unit atomically: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
    return _sha256(destination)


def freeze_launch_authorization(
    *,
    destination: Path,
    plan_authorization: Path,
    plan_sha256_file: Path,
    source_root: Path,
    unit: Path,
    stopped_validation_output: Path,
) -> str:
    source_root = _exact_absolute_directory(source_root, "candidate source root")
    destination = _require_external_path(
        destination, source_root, "launch authorization destination"
    )
    consumption = destination.with_name(CANARY_LAUNCH_CONSUMPTION_NAME)
    consumption_sha = consumption.with_suffix(".sha256")
    if (
        consumption.exists()
        or consumption.is_symlink()
        or consumption_sha.exists()
        or consumption_sha.is_symlink()
    ):
        raise AuthorityError(
            "launch consumption must be absent before launch authorization"
        )
    plan = validate_plan_authorization(
        plan_authorization,
        sha256_file=plan_sha256_file,
        source_root=source_root,
        require_output_absent=False,
    )
    plan["authorization_path"] = str(plan_authorization)
    output = Path(plan["screen"]["output"])
    inventory = validate_plan_output(output)
    manifest = output / "SCREEN_MANIFEST.json"
    _validate_screen_manifest(manifest, plan, plan["authorization_sha256"])
    stopped = _require_empty_directory(
        stopped_validation_output, "stopped-validation output"
    )
    unit = _exact_absolute_file(unit, "canonical canary unit")
    if unit.name != CANARY_UNIT_NAME:
        raise AuthorityError("canonical canary unit name drifted")
    unit_paths = UnitPaths(
        source_root=source_root,
        qualification_runner_root=Path(plan["qualification_runner"]["root"]),
        qualification=Path(plan["qualification"]["path"]),
        output=output,
        launch_authorization=destination,
        launch_authorization_sha=destination.with_suffix(".sha256"),
    )
    if unit.read_text(encoding="utf-8") != render_systemd_unit(unit_paths):
        raise AuthorityError("canonical canary unit bytes drifted")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": LAUNCH_KIND,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "qualification_only": True,
        "source": plan["source"],
        "qualification_runner": plan["qualification_runner"],
        "qualification": plan["qualification"],
        "candidate": plan["candidate"],
        "cuda_runtime": plan["cuda_runtime"],
        "plan_authorization": {
            "path": str(plan_authorization),
            "sha256": plan["authorization_sha256"],
            "sha256_file": str(plan_sha256_file),
        },
        "plan_output": {
            "path": str(output),
            "inventory": inventory,
            "manifest_sha256": _sha256(manifest),
        },
        "unit": {
            "path": str(unit),
            "name": CANARY_UNIT_NAME,
            "sha256": _sha256(unit),
        },
        "stopped_validation": {
            "path": str(stopped),
            "initially_empty": True,
        },
        "launch_consumption": {
            "path": str(consumption),
            "sha256_file": str(consumption_sha),
            "initially_absent": True,
        },
        "systemd": {
            "type": "oneshot",
            "restart": "no",
            "kill_mode": "control-group",
            "timeout_start_seconds": 7200,
            "timeout_stop_seconds": 60,
            "enabled": False,
            "maximum_starts": 1,
        },
        "command": {
            **_expected_screen(),
            "plan_only": 0,
            "warm_environment": "unset",
            "pool_environment": "unset",
            "cuda_visible_devices": "0",
            "thread_cap": 16,
        },
        "eligibility": {
            "qualification_only": True,
            "checkpoint_ancestry": False,
            "reward_evidence": False,
            "promotion": False,
            "bbtv_follower": False,
        },
    }
    return write_authority(destination, payload)


def validate_launch_authorization(
    authorization: Path, *, sha256_file: Path
) -> dict[str, Any]:
    authorization = _exact_absolute_file(
        authorization, "canary launch authorization"
    )
    digest = _validate_digest_sidecar(
        authorization, sha256_file, label="canary launch authorization"
    )
    payload = _read_json(authorization, "canary launch authorization")
    if payload.get("schema_version") != SCHEMA_VERSION or payload.get("kind") != LAUNCH_KIND:
        raise AuthorityError("canary launch authorization schema/kind mismatch")
    if payload.get("qualification_only") is not True:
        raise AuthorityError("canary launch authorization is not qualification-only")
    source = payload.get("source")
    if not isinstance(source, dict):
        raise AuthorityError("canary launch source identity is malformed")
    source_root = Path(str(source.get("root", "")))
    plan_ref = payload.get("plan_authorization")
    if not isinstance(plan_ref, dict):
        raise AuthorityError("canary launch plan authority reference is malformed")
    plan = validate_plan_authorization(
        Path(str(plan_ref.get("path", ""))),
        sha256_file=Path(str(plan_ref.get("sha256_file", ""))),
        source_root=source_root,
        require_output_absent=False,
    )
    plan["authorization_path"] = plan_ref["path"]
    if plan_ref.get("sha256") != plan["authorization_sha256"]:
        raise AuthorityError("canary launch plan authorization digest drifted")
    for key in (
        "source",
        "qualification_runner",
        "qualification",
        "candidate",
        "cuda_runtime",
    ):
        if payload.get(key) != plan.get(key):
            raise AuthorityError(f"canary launch {key} identity drifted")
    plan_output = payload.get("plan_output")
    if not isinstance(plan_output, dict):
        raise AuthorityError("canary launch plan output identity is malformed")
    output = Path(str(plan_output.get("path", "")))
    if output != Path(plan["screen"]["output"]):
        raise AuthorityError("canary launch plan output path drifted")
    inventory = validate_plan_output(output)
    if plan_output.get("inventory") != inventory:
        raise AuthorityError("canary launch plan output inventory drifted")
    manifest = output / "SCREEN_MANIFEST.json"
    if plan_output.get("manifest_sha256") != _sha256(manifest):
        raise AuthorityError("canary launch screen manifest digest drifted")
    _validate_screen_manifest(manifest, plan, plan["authorization_sha256"])
    stopped = payload.get("stopped_validation")
    if not isinstance(stopped, dict) or stopped.get("initially_empty") is not True:
        raise AuthorityError("canary launch stopped-validation identity is malformed")
    _require_empty_directory(
        Path(str(stopped.get("path", ""))), "stopped-validation output"
    )
    if payload.get("launch_consumption") != {
        "path": str(authorization.with_name(CANARY_LAUNCH_CONSUMPTION_NAME)),
        "sha256_file": str(
            authorization.with_name(CANARY_LAUNCH_CONSUMPTION_NAME).with_suffix(
                ".sha256"
            )
        ),
        "initially_absent": True,
    }:
        raise AuthorityError("canary launch consumption identity drifted")
    unit = payload.get("unit")
    if not isinstance(unit, dict):
        raise AuthorityError("canary launch unit identity is malformed")
    unit_path = _exact_absolute_file(
        Path(str(unit.get("path", ""))), "canonical canary unit"
    )
    if unit.get("name") != CANARY_UNIT_NAME or unit_path.name != CANARY_UNIT_NAME:
        raise AuthorityError("canary launch unit name drifted")
    if unit.get("sha256") != _sha256(unit_path):
        raise AuthorityError("canary launch unit digest drifted")
    expected_unit = render_systemd_unit(
        UnitPaths(
            source_root=source_root,
            qualification_runner_root=Path(
                plan["qualification_runner"]["root"]
            ),
            qualification=Path(plan["qualification"]["path"]),
            output=output,
            launch_authorization=authorization,
            launch_authorization_sha=sha256_file,
        )
    )
    if unit_path.read_text(encoding="utf-8") != expected_unit:
        raise AuthorityError("canary launch unit bytes drifted")
    if payload.get("systemd") != {
        "type": "oneshot",
        "restart": "no",
        "kill_mode": "control-group",
        "timeout_start_seconds": 7200,
        "timeout_stop_seconds": 60,
        "enabled": False,
        "maximum_starts": 1,
    }:
        raise AuthorityError("canary launch systemd contract drifted")
    if payload.get("command") != {
        **_expected_screen(),
        "plan_only": 0,
        "warm_environment": "unset",
        "pool_environment": "unset",
        "cuda_visible_devices": "0",
        "thread_cap": 16,
    }:
        raise AuthorityError("canary launch command contract drifted")
    if payload.get("eligibility") != {
        "qualification_only": True,
        "checkpoint_ancestry": False,
        "reward_evidence": False,
        "promotion": False,
        "bbtv_follower": False,
    }:
        raise AuthorityError("canary launch eligibility exclusions drifted")
    result = dict(payload)
    result["authorization_sha256"] = digest
    return result


def consume_launch_authorization(
    *, authorization: Path, sha256_file: Path, destination: Path
) -> str:
    """Irreversibly consume the sole authorized systemd start."""
    authorization = _exact_absolute_file(
        authorization, "canary launch authorization"
    )
    sha256_file = _exact_absolute_file(
        sha256_file, "canary launch authorization digest"
    )
    if not destination.is_absolute() or destination.resolve() != destination:
        raise AuthorityError(
            "launch consumption destination must be an exact absolute path"
        )
    expected_destination = authorization.with_name(
        CANARY_LAUNCH_CONSUMPTION_NAME
    )
    if destination != expected_destination:
        raise AuthorityError(
            "launch consumption destination is not the canonical sibling path"
        )
    if destination.exists() or destination.is_symlink() or destination.with_suffix(
        ".sha256"
    ).exists():
        raise AuthorityError("launch authorization was already consumed")
    launch = validate_launch_authorization(
        authorization, sha256_file=sha256_file
    )
    if launch.get("systemd", {}).get("maximum_starts") != 1:
        raise AuthorityError("launch authorization does not permit exactly one start")
    plan_output = launch.get("plan_output")
    if not isinstance(plan_output, dict) or not isinstance(
        plan_output.get("path"), str
    ):
        raise AuthorityError("launch authorization plan output is malformed")
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": CONSUMPTION_KIND,
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "qualification_only": True,
        "launch_authorization": {
            "path": str(authorization),
            "sha256": launch["authorization_sha256"],
            "sha256_file": str(sha256_file),
        },
        "plan_authorization": launch.get("plan_authorization"),
        "qualification": launch.get("qualification"),
        "plan_output": plan_output["path"],
        "attempt": 1,
        "maximum_starts": 1,
        "eligibility": launch.get("eligibility"),
    }
    return write_authority(
        destination, payload, irreversible_once_published=True
    )


def validate_launch_consumption(
    consumption: Path,
    *,
    consumption_sha256_file: Path,
    authorization: Path,
    authorization_sha256_file: Path,
) -> dict[str, Any]:
    """Validate the immutable first-start record before launcher mutation."""
    authorization = _exact_absolute_file(
        authorization, "canary launch authorization"
    )
    authorization_sha256_file = _exact_absolute_file(
        authorization_sha256_file, "canary launch authorization digest"
    )
    consumption = _exact_absolute_file(
        consumption, "canary launch consumption"
    )
    if consumption != authorization.with_name(CANARY_LAUNCH_CONSUMPTION_NAME):
        raise AuthorityError("launch consumption path is not the canonical sibling")
    consumption_digest = _validate_digest_sidecar(
        consumption,
        consumption_sha256_file,
        label="canary launch consumption",
    )
    launch = validate_launch_authorization(
        authorization, sha256_file=authorization_sha256_file
    )
    payload = _read_json(consumption, "canary launch consumption")
    if (
        payload.get("schema_version") != SCHEMA_VERSION
        or payload.get("kind") != CONSUMPTION_KIND
        or payload.get("qualification_only") is not True
    ):
        raise AuthorityError("launch consumption schema/kind drifted")
    if payload.get("launch_authorization") != {
        "path": str(authorization),
        "sha256": launch["authorization_sha256"],
        "sha256_file": str(authorization_sha256_file),
    }:
        raise AuthorityError("launch consumption authorization identity drifted")
    exact = {
        "plan_authorization": launch.get("plan_authorization"),
        "qualification": launch.get("qualification"),
        "plan_output": launch["plan_output"]["path"],
        "attempt": 1,
        "maximum_starts": 1,
        "eligibility": launch.get("eligibility"),
    }
    for key, required in exact.items():
        if payload.get(key) != required:
            raise AuthorityError(f"launch consumption {key} drifted")
    result = dict(launch)
    result["launch_consumption"] = {
        "path": str(consumption),
        "sha256": consumption_digest,
        "sha256_file": str(consumption_sha256_file),
    }
    return result


def write_authority(
    destination: Path,
    payload: Mapping[str, Any],
    *,
    irreversible_once_published: bool = False,
) -> str:
    """Create one JSON authority and digest sidecar without overwriting."""
    if not destination.is_absolute() or destination.resolve() != destination:
        raise AuthorityError("authority destination must be an exact absolute path")
    if not destination.parent.is_dir():
        raise AuthorityError("authority destination parent must already exist")
    sidecar = destination.with_suffix(".sha256")
    if destination.exists() or destination.is_symlink() or sidecar.exists() or sidecar.is_symlink():
        raise AuthorityError("authority destination or digest sidecar already exists")
    raw = _json_bytes(payload)
    digest = hashlib.sha256(raw).hexdigest()
    sidecar_raw = f"{digest}  {destination.name}\n".encode("ascii")
    nonce = f"{os.getpid()}.{secrets.token_hex(8)}"
    temporary = destination.with_name(f".{destination.name}.tmp.{nonce}")
    sidecar_temporary = sidecar.with_name(f".{sidecar.name}.tmp.{nonce}")
    destination_published = False
    sidecar_published = False
    try:
        with temporary.open("xb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        with sidecar_temporary.open("xb") as handle:
            handle.write(sidecar_raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, destination)
        destination_published = True
        os.link(sidecar_temporary, sidecar)
        sidecar_published = True
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        if not irreversible_once_published:
            if sidecar_published:
                sidecar.unlink(missing_ok=True)
            if destination_published:
                destination.unlink(missing_ok=True)
        raise AuthorityError(f"cannot publish authority atomically: {exc}") from exc
    finally:
        temporary.unlink(missing_ok=True)
        sidecar_temporary.unlink(missing_ok=True)
    return digest


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    validate = sub.add_parser("validate-qualification")
    validate.add_argument("qualification", type=Path)
    validate.add_argument("--source-root", required=True, type=Path)
    validate.add_argument(
        "--qualification-runner-root", required=True, type=Path
    )
    freeze_plan = sub.add_parser("freeze-plan")
    freeze_plan.add_argument("--destination", required=True, type=Path)
    freeze_plan.add_argument("--qualification", required=True, type=Path)
    freeze_plan.add_argument("--source-root", required=True, type=Path)
    freeze_plan.add_argument(
        "--qualification-runner-root", required=True, type=Path
    )
    freeze_plan.add_argument("--screen-output", required=True, type=Path)
    freeze_plan.add_argument("--recovery-verification", required=True, type=Path)
    freeze_plan.add_argument("--recovery-inventory", required=True, type=Path)
    freeze_plan.add_argument("--predecessor-root", required=True, type=Path)
    validate_plan = sub.add_parser("validate-plan")
    validate_plan.add_argument("--authorization", required=True, type=Path)
    validate_plan.add_argument("--sha256-file", required=True, type=Path)
    validate_plan.add_argument("--source-root", required=True, type=Path)
    validate_plan.add_argument(
        "--require-output-absent", action="store_true"
    )
    render = sub.add_parser("render-unit")
    render.add_argument("--destination", required=True, type=Path)
    render.add_argument("--source-root", required=True, type=Path)
    render.add_argument(
        "--qualification-runner-root", required=True, type=Path
    )
    render.add_argument("--qualification", required=True, type=Path)
    render.add_argument("--screen-output", required=True, type=Path)
    render.add_argument("--launch-authorization", required=True, type=Path)
    render.add_argument("--launch-authorization-sha256-file", required=True, type=Path)
    freeze_launch = sub.add_parser("freeze-launch")
    freeze_launch.add_argument("--destination", required=True, type=Path)
    freeze_launch.add_argument("--plan-authorization", required=True, type=Path)
    freeze_launch.add_argument("--plan-sha256-file", required=True, type=Path)
    freeze_launch.add_argument("--source-root", required=True, type=Path)
    freeze_launch.add_argument("--unit", required=True, type=Path)
    freeze_launch.add_argument(
        "--stopped-validation-output", required=True, type=Path
    )
    launch = sub.add_parser("validate-launch")
    launch.add_argument("--authorization", required=True, type=Path)
    launch.add_argument("--sha256-file", required=True, type=Path)
    consume = sub.add_parser("consume-launch")
    consume.add_argument("--authorization", required=True, type=Path)
    consume.add_argument("--sha256-file", required=True, type=Path)
    consume.add_argument("--destination", required=True, type=Path)
    validate_consumption = sub.add_parser("validate-consumption")
    validate_consumption.add_argument("--consumption", required=True, type=Path)
    validate_consumption.add_argument(
        "--consumption-sha256-file", required=True, type=Path
    )
    validate_consumption.add_argument(
        "--authorization", required=True, type=Path
    )
    validate_consumption.add_argument(
        "--authorization-sha256-file", required=True, type=Path
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    if args.command == "validate-qualification":
        payload = validate_qualification(
            args.qualification,
            source_root=args.source_root,
            qualification_runner_root=args.qualification_runner_root,
        )
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 0
    if args.command == "freeze-plan":
        digest = freeze_plan_authorization(
            destination=args.destination,
            qualification=args.qualification,
            source_root=args.source_root,
            qualification_runner_root=args.qualification_runner_root,
            screen_output=args.screen_output,
            recovery_verification=args.recovery_verification,
            recovery_inventory=args.recovery_inventory,
            predecessor_root=args.predecessor_root,
        )
        print(digest)
        return 0
    if args.command == "validate-plan":
        payload = validate_plan_authorization(
            args.authorization,
            sha256_file=args.sha256_file,
            source_root=args.source_root,
            require_output_absent=args.require_output_absent,
        )
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 0
    if args.command == "render-unit":
        digest = write_unit(
            args.destination,
            UnitPaths(
                source_root=args.source_root,
                qualification_runner_root=args.qualification_runner_root,
                qualification=args.qualification,
                output=args.screen_output,
                launch_authorization=args.launch_authorization,
                launch_authorization_sha=args.launch_authorization_sha256_file,
            ),
        )
        print(digest)
        return 0
    if args.command == "freeze-launch":
        digest = freeze_launch_authorization(
            destination=args.destination,
            plan_authorization=args.plan_authorization,
            plan_sha256_file=args.plan_sha256_file,
            source_root=args.source_root,
            unit=args.unit,
            stopped_validation_output=args.stopped_validation_output,
        )
        print(digest)
        return 0
    if args.command == "validate-launch":
        payload = validate_launch_authorization(
            args.authorization, sha256_file=args.sha256_file
        )
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 0
    if args.command == "consume-launch":
        digest = consume_launch_authorization(
            authorization=args.authorization,
            sha256_file=args.sha256_file,
            destination=args.destination,
        )
        print(digest)
        return 0
    if args.command == "validate-consumption":
        payload = validate_launch_consumption(
            args.consumption,
            consumption_sha256_file=args.consumption_sha256_file,
            authorization=args.authorization,
            authorization_sha256_file=args.authorization_sha256_file,
        )
        print(json.dumps(payload, sort_keys=True, allow_nan=False))
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AuthorityError as exc:
        print(f"exact-action canary authority rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
