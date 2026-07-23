#!/usr/bin/env python3
"""Initialize CUDA before importing Puffer's native extension.

The CUDA runtime owns process-global initialization state.  On the RTX 2070
WSL target, loading the nvcc-built ``pufferlib._C`` extension before the first
runtime call can leave that process reporting ``cudaErrorNoDevice``.  The
normal trainer and the qualification worker therefore share this explicit,
fail-closed entry boundary instead of depending on incidental import order.
"""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
from typing import Any, Callable


CUDA_RUNTIME_SONAME = "libcudart.so.12"
CUDA_SUCCESS = 0
CUDA_RUNTIME_LOG_PREFIX = "PUFFER_CUDA_RUNTIME "
RUN_MANIFEST_LOG_PREFIX = "BB_RUN_MANIFEST "
MANIFEST_ENV = "PUFFER_CUDA_RUNTIME_MANIFEST"
EVIDENCE_ENV = "PUFFER_CUDA_RUNTIME_EVIDENCE"


class CudaRuntimePreflightError(RuntimeError):
    """The native CUDA process boundary could not be established exactly."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _resolved_cuda_runtime_path() -> Path:
    maps = Path("/proc/self/maps")
    try:
        candidates = {
            Path(line.split()[-1]).resolve()
            for line in maps.read_text(encoding="utf-8").splitlines()
            if line.split()
            and line.split()[-1].startswith("/")
            and Path(line.split()[-1]).name.startswith("libcudart.so.")
        }
    except (OSError, UnicodeError) as exc:
        raise CudaRuntimePreflightError(
            f"cannot resolve the loaded CUDA runtime from {maps}: {exc}"
        ) from exc
    if len(candidates) != 1:
        raise CudaRuntimePreflightError(
            "expected exactly one loaded CUDA runtime, found "
            f"{sorted(str(path) for path in candidates)}"
        )
    path = next(iter(candidates))
    if not path.is_file():
        raise CudaRuntimePreflightError(
            f"loaded CUDA runtime is not a regular file: {path}"
        )
    return path


def _cuda_text(function: Callable[[int], Any], code: int, label: str) -> str:
    try:
        raw = function(code)
    except Exception as exc:  # pragma: no cover - native ABI failure
        raise CudaRuntimePreflightError(
            f"CUDA runtime {label} lookup failed for status {code}: {exc}"
        ) from exc
    if not isinstance(raw, bytes):
        raise CudaRuntimePreflightError(
            f"CUDA runtime {label} lookup returned a non-byte value"
        )
    try:
        value = raw.decode("utf-8")
    except UnicodeError as exc:
        raise CudaRuntimePreflightError(
            f"CUDA runtime {label} is not UTF-8"
        ) from exc
    if not value:
        raise CudaRuntimePreflightError(f"CUDA runtime {label} is empty")
    return value


def _cuda_runtime_candidates() -> list[str]:
    """Prefer the CUDART that Torch itself will load, then the system soname.

    Loading the bare soname lets ldconfig win, and on this host that resolves to
    the system /usr/lib/x86_64-linux-gnu/libcudart.so.12 -> 12.4.127, while the
    venv ships the 12.8 runtime that torch 2.10.0+cu128 was built against. Once
    12.4 is in the process, importing torch dies with

        libc10_cuda.so: undefined symbol: cudaGetDriverEntryPointByVersion,
        version libcudart.so.12

    because that symbol only exists from 12.5 onward (verified: 0 occurrences in
    the 12.4 system library, 2 in the bundled one). Whose runtime gets loaded is
    the exact property this preflight exists to pin, so resolving a different one
    than the trainer uses defeats its own purpose.
    """
    candidates: list[str] = []
    # sys.prefix, not Path(sys.executable).resolve(): the venv's bin/python is a
    # symlink into uv's interpreter store, so resolving it walks straight out of
    # the venv and the bundled runtime is never found.
    roots = [Path(sys.prefix)]
    try:
        import site
        roots.extend(Path(p) for p in site.getsitepackages())
    except Exception:  # pragma: no cover - site is always present in practice
        pass
    for root in roots:
        for pattern in (
            f"lib/python3.*/site-packages/nvidia/cuda_runtime/lib/{CUDA_RUNTIME_SONAME}",
            f"nvidia/cuda_runtime/lib/{CUDA_RUNTIME_SONAME}",
        ):
            for lib in sorted(root.glob(pattern)):
                path = str(lib)
                if path not in candidates:
                    candidates.append(path)
    candidates.append(CUDA_RUNTIME_SONAME)
    return candidates


def begin_cuda_runtime_preflight() -> tuple[Any, dict[str, Any]]:
    """Initialize CUDART before any nvcc-built extension is imported."""
    try:
        runtime = None
        errors = []
        for candidate in _cuda_runtime_candidates():
            try:
                runtime = ctypes.CDLL(candidate)
                break
            except OSError as exc:
                errors.append(f"{candidate}: {exc}")
        if runtime is None:
            raise OSError("; ".join(errors) or "no CUDA runtime candidate")
        runtime.cudaGetDeviceCount.argtypes = [ctypes.POINTER(ctypes.c_int)]
        runtime.cudaGetDeviceCount.restype = ctypes.c_int
        runtime.cudaGetErrorName.argtypes = [ctypes.c_int]
        runtime.cudaGetErrorName.restype = ctypes.c_char_p
        runtime.cudaGetErrorString.argtypes = [ctypes.c_int]
        runtime.cudaGetErrorString.restype = ctypes.c_char_p
    except (AttributeError, OSError) as exc:
        raise CudaRuntimePreflightError(
            f"cannot load the required CUDA runtime {CUDA_RUNTIME_SONAME}: {exc}"
        ) from exc

    path = _resolved_cuda_runtime_path()
    evidence = {
        "schema_version": 1,
        "library": {
            "requested_soname": CUDA_RUNTIME_SONAME,
            "resolved_path": str(path),
            "sha256": _sha256(path),
        },
        "cuda_visible_devices": os.environ.get("CUDA_VISIBLE_DEVICES"),
    }
    evidence["before_extension_import"] = _probe_cuda_runtime(
        runtime, "before_extension_import"
    )
    return runtime, evidence


def _probe_cuda_runtime(runtime: Any, stage: str) -> dict[str, Any]:
    count = ctypes.c_int(-1)
    try:
        return_code = int(runtime.cudaGetDeviceCount(ctypes.byref(count)))
    except Exception as exc:  # pragma: no cover - native ABI failure
        raise CudaRuntimePreflightError(
            f"CUDA runtime probe {stage} failed: {exc}"
        ) from exc
    error_name = _cuda_text(runtime.cudaGetErrorName, return_code, "error name")
    error_string = _cuda_text(
        runtime.cudaGetErrorString, return_code, "error string"
    )
    probe = {
        "stage": stage,
        "return_code": return_code,
        "device_count": count.value,
        "error_name": error_name,
        "error_string": error_string,
    }
    if return_code != CUDA_SUCCESS or count.value <= 0:
        raise CudaRuntimePreflightError(
            f"CUDA runtime probe {stage} rejected: return_code={return_code} "
            f"device_count={count.value} {error_name}: {error_string}"
        )
    return probe


def finish_cuda_runtime_preflight(
    runtime: Any, evidence: dict[str, Any]
) -> dict[str, Any]:
    """Prove extension import preserved the already-valid CUDA runtime."""
    before = evidence.get("before_extension_import")
    if not isinstance(before, dict):
        raise CudaRuntimePreflightError(
            "CUDA runtime preflight lacks pre-import evidence"
        )
    after = _probe_cuda_runtime(runtime, "after_extension_import")
    if after["device_count"] != before.get("device_count"):
        raise CudaRuntimePreflightError(
            "CUDA device count changed across native extension import: "
            f"{before.get('device_count')} != {after['device_count']}"
        )
    completed = dict(evidence)
    completed["after_extension_import"] = after
    return completed


def validate_cuda_runtime_evidence(
    evidence: Any,
) -> dict[str, Any]:
    """Revalidate serialized pre/post-import evidence without native calls."""
    required_top_level = {
        "schema_version",
        "library",
        "cuda_visible_devices",
        "before_extension_import",
        "after_extension_import",
    }
    if (
        not isinstance(evidence, dict)
        or set(evidence) != required_top_level
        or evidence.get("schema_version") != 1
    ):
        raise CudaRuntimePreflightError("CUDA runtime evidence schema is invalid")
    library = evidence.get("library")
    if not isinstance(library, dict) or set(library) != {
        "requested_soname",
        "resolved_path",
        "sha256",
    }:
        raise CudaRuntimePreflightError("CUDA runtime library identity is missing")
    if library.get("requested_soname") != CUDA_RUNTIME_SONAME:
        raise CudaRuntimePreflightError("CUDA runtime SONAME is not frozen")
    resolved = library.get("resolved_path")
    digest = library.get("sha256")
    if not isinstance(resolved, str) or not resolved.startswith("/"):
        raise CudaRuntimePreflightError("CUDA runtime resolved path is invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise CudaRuntimePreflightError("CUDA runtime digest is invalid")
    visible_devices = evidence.get("cuda_visible_devices")
    if not isinstance(visible_devices, str) or not visible_devices:
        raise CudaRuntimePreflightError(
            "CUDA_VISIBLE_DEVICES evidence is missing or invalid"
        )
    probes = []
    for stage in ("before_extension_import", "after_extension_import"):
        probe = evidence.get(stage)
        if (
            not isinstance(probe, dict)
            or set(probe) != {
                "stage",
                "return_code",
                "device_count",
                "error_name",
                "error_string",
            }
            or probe.get("stage") != stage
        ):
            raise CudaRuntimePreflightError(
                f"CUDA runtime {stage} evidence is malformed"
            )
        return_code = probe.get("return_code")
        count = probe.get("device_count")
        if (
            isinstance(return_code, bool)
            or not isinstance(return_code, int)
            or return_code != CUDA_SUCCESS
            or isinstance(count, bool)
            or not isinstance(count, int)
            or count <= 0
            or not isinstance(probe.get("error_name"), str)
            or probe["error_name"] != "cudaSuccess"
            or not isinstance(probe.get("error_string"), str)
            or not probe["error_string"]
        ):
            raise CudaRuntimePreflightError(
                f"CUDA runtime {stage} evidence did not accept exactly"
            )
        probes.append(probe)
    if probes[0]["device_count"] != probes[1]["device_count"]:
        raise CudaRuntimePreflightError(
            "CUDA device count differs across native extension import"
        )
    return evidence


def validate_cuda_runtime_library_file(evidence: Any) -> dict[str, Any]:
    """Rehash the exact CUDART file named by serialized runtime evidence."""
    evidence = validate_cuda_runtime_evidence(evidence)
    path = Path(evidence["library"]["resolved_path"])
    if not path.is_absolute() or path.resolve() != path or not path.is_file():
        raise CudaRuntimePreflightError(
            f"CUDA runtime evidence path is not an exact current file: {path}"
        )
    if _sha256(path) != evidence["library"]["sha256"]:
        raise CudaRuntimePreflightError(
            f"CUDA runtime library digest drifted: {path}"
        )
    return evidence


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")


def _publish_runtime_evidence(
    evidence: dict[str, Any],
) -> dict[str, Any]:
    """Bind the trainer process's live evidence into its pending manifest."""
    manifest_raw = os.environ.get(MANIFEST_ENV)
    evidence_raw = os.environ.get(EVIDENCE_ENV)
    if not manifest_raw or not evidence_raw:
        raise CudaRuntimePreflightError(
            "trainer CUDA manifest/evidence paths are mandatory and must be "
            "supplied together"
        )
    manifest_path = Path(manifest_raw)
    evidence_path = Path(evidence_raw)
    if (
        not manifest_path.is_absolute()
        or manifest_path.resolve() != manifest_path
        or not manifest_path.is_file()
        or not evidence_path.is_absolute()
        or evidence_path.resolve() != evidence_path
        or not evidence_path.parent.is_dir()
        or evidence_path.exists()
    ):
        raise CudaRuntimePreflightError(
            "trainer CUDA manifest/evidence paths are not exact and fresh"
        )
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise CudaRuntimePreflightError(
            f"cannot read pending trainer manifest: {exc}"
        ) from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise CudaRuntimePreflightError("pending trainer manifest is malformed")
    wrapper_sha256 = _sha256(Path(__file__).resolve())
    expected_launcher = {
        "cuda_runtime_wrapper_sha256": wrapper_sha256,
        "cuda_runtime_evidence_status": "pending",
        "cuda_runtime_evidence_path": str(evidence_path),
        "cuda_launcher_probe_library_path": evidence["library"]["resolved_path"],
        "cuda_launcher_probe_library_sha256": evidence["library"]["sha256"],
        "cuda_launcher_probe_device_count": str(
            evidence["after_extension_import"]["device_count"]
        ),
        "cuda_launcher_probe_visible_devices": evidence["cuda_visible_devices"],
    }
    for key, expected in expected_launcher.items():
        if manifest.get(key) != expected:
            raise CudaRuntimePreflightError(
                f"trainer CUDA evidence differs from pending manifest field {key}"
            )
    payload = {
        "schema_version": 1,
        "role": "puffer_trainer_cuda_runtime",
        "wrapper_sha256": wrapper_sha256,
        "runtime_evidence": evidence,
    }
    temporary = evidence_path.with_name(
        f".{evidence_path.name}.tmp.{os.getpid()}"
    )
    if temporary.exists():
        raise CudaRuntimePreflightError(
            f"trainer CUDA evidence temporary path already exists: {temporary}"
        )
    try:
        with temporary.open("xb") as handle:
            handle.write(_json_bytes(payload))
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary, evidence_path)
    except OSError as exc:
        raise CudaRuntimePreflightError(
            f"cannot publish trainer CUDA evidence: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)

    manifest["cuda_runtime_evidence_status"] = "accepted"
    manifest["cuda_runtime_evidence"] = evidence
    manifest["cuda_runtime_evidence_sha256"] = _sha256(evidence_path)
    manifest_temporary = manifest_path.with_name(
        f".{manifest_path.name}.tmp.{os.getpid()}"
    )
    try:
        with manifest_temporary.open("xb") as handle:
            handle.write(_json_bytes(manifest))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(manifest_temporary, manifest_path)
    except OSError as exc:
        raise CudaRuntimePreflightError(
            f"cannot finalize trainer CUDA manifest: {exc}"
        ) from exc
    finally:
        manifest_temporary.unlink(missing_ok=True)
    return manifest


def _import_puffer_main() -> Callable[[], int | None]:
    from pufferlib import _C  # type: ignore  # noqa: F401
    from pufferlib.pufferl import main  # type: ignore

    return main


def _remove_script_directory_from_import_path() -> None:
    """Prevent the repository tools directory from shadowing trainer imports."""
    if not sys.path:
        return
    first = Path(sys.path[0] or os.getcwd()).resolve()
    if first == Path(__file__).resolve().parent:
        sys.path.pop(0)


def main() -> int:
    """Run the ordinary Puffer CLI behind the canonical CUDA boundary."""
    runtime, evidence = begin_cuda_runtime_preflight()
    _remove_script_directory_from_import_path()
    puffer_main = _import_puffer_main()
    evidence = finish_cuda_runtime_preflight(runtime, evidence)
    validate_cuda_runtime_evidence(evidence)
    finalized_manifest = _publish_runtime_evidence(evidence)
    print(
        CUDA_RUNTIME_LOG_PREFIX
        + json.dumps(evidence, sort_keys=True, separators=(",", ":")),
        flush=True,
    )
    print(
        RUN_MANIFEST_LOG_PREFIX
        + json.dumps(
            finalized_manifest,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ),
        flush=True,
    )
    result = puffer_main()
    return 0 if result is None else int(result)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except CudaRuntimePreflightError as exc:
        print(f"CUDA runtime preflight failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
