"""Bounded, deterministic reward-screen result and completion evidence."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_SCREEN_EVIDENCE_BYTES = 16 * 1024 * 1024
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


class ScreenEvidenceContractError(ValueError):
    """Screen evidence is missing, mutable, malformed, or cross-screen."""


@dataclass(frozen=True)
class _FileIdentity:
    device: int
    inode: int


@dataclass(frozen=True)
class _VerifiedFile:
    identity: _FileIdentity
    size: int
    mtime_ns: int
    ctime_ns: int


def _readonly_nofollow(path: Path, label: str) -> int:
    if not hasattr(os, "O_NOFOLLOW"):
        raise ScreenEvidenceContractError(
            "platform cannot publish screen evidence without no-follow opens"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        return os.open(path, flags)
    except OSError as exc:
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            f"cannot open {label}: {exc}"
        ) from exc


def _verify_open_bytes(
    descriptor: int,
    raw: bytes,
    label: str,
    *,
    expected_identity: _FileIdentity | None = None,
) -> _VerifiedFile:
    os.lseek(descriptor, 0, os.SEEK_SET)
    before = os.fstat(descriptor)
    identity = _FileIdentity(before.st_dev, before.st_ino)
    if not stat.S_ISREG(before.st_mode):
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            f"{label} is not regular"
        )
    if expected_identity is not None and identity != expected_identity:
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            f"{label} inode changed"
        )
    if before.st_size != len(raw):
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            f"{label} size changed"
        )
    chunks: list[bytes] = []
    remaining = len(raw)
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise ScreenEvidenceContractError(
                "linked screen evidence differs from verified temporary: "
                f"{label} became shorter"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: " f"{label} grew"
        )
    after = os.fstat(descriptor)
    if (
        after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            f"{label} changed while read"
        )
    observed = b"".join(chunks)
    if (
        observed != raw
        or hashlib.sha256(observed).digest() != hashlib.sha256(raw).digest()
    ):
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            f"{label} bytes or SHA-256 changed"
        )
    verified = os.fstat(descriptor)
    if (
        not stat.S_ISREG(verified.st_mode)
        or verified.st_dev != after.st_dev
        or verified.st_ino != after.st_ino
        or verified.st_size != after.st_size
        or verified.st_mtime_ns != after.st_mtime_ns
        or verified.st_ctime_ns != after.st_ctime_ns
    ):
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            f"{label} changed while verified"
        )
    return _VerifiedFile(
        identity=identity,
        size=verified.st_size,
        mtime_ns=verified.st_mtime_ns,
        ctime_ns=verified.st_ctime_ns,
    )


def _require_verified_destination_path(
    destination: Path,
    verified: _VerifiedFile,
) -> None:
    try:
        info = destination.stat(follow_symlinks=False)
    except OSError as exc:
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            "destination path inode changed after verification: "
            f"cannot inspect: {exc}"
        ) from exc
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_dev != verified.identity.device
        or info.st_ino != verified.identity.inode
        or info.st_size != verified.size
        or info.st_mtime_ns != verified.mtime_ns
        or info.st_ctime_ns != verified.ctime_ns
    ):
        raise ScreenEvidenceContractError(
            "linked screen evidence differs from verified temporary: "
            "destination path inode changed after verification or metadata differs"
        )


def _path_has_identity(path: Path, identity: _FileIdentity) -> bool:
    try:
        info = path.stat(follow_symlinks=False)
    except OSError:
        return False
    return (
        stat.S_ISREG(info.st_mode)
        and info.st_dev == identity.device
        and info.st_ino == identity.inode
    )


def _publish_verified_link(temporary: Path, destination: Path, raw: bytes) -> None:
    staged_descriptor = _readonly_nofollow(temporary, "staged file")
    owned_identities: set[_FileIdentity] = set()
    try:
        staged_identity = _verify_open_bytes(
            staged_descriptor, raw, "staged file"
        ).identity
        owned_identities.add(staged_identity)
        os.link(temporary, destination)
        try:
            linked_source_info = temporary.stat(follow_symlinks=False)
            if stat.S_ISREG(linked_source_info.st_mode):
                owned_identities.add(
                    _FileIdentity(
                        linked_source_info.st_dev,
                        linked_source_info.st_ino,
                    )
                )
        except OSError:
            pass
        destination_descriptor = _readonly_nofollow(destination, "destination")
        try:
            destination_info = os.fstat(destination_descriptor)
            destination_identity = _FileIdentity(
                destination_info.st_dev, destination_info.st_ino
            )
            source_descriptor = _readonly_nofollow(temporary, "linked source")
            try:
                source_info = os.fstat(source_descriptor)
                source_identity = _FileIdentity(source_info.st_dev, source_info.st_ino)
                if destination_identity == source_identity:
                    owned_identities.add(destination_identity)
                if (
                    destination_identity != staged_identity
                    or source_identity != staged_identity
                ):
                    raise ScreenEvidenceContractError(
                        "linked screen evidence differs from verified temporary: "
                        "source or destination inode changed"
                    )
                verified_destination = _verify_open_bytes(
                    destination_descriptor,
                    raw,
                    "destination",
                    expected_identity=staged_identity,
                )
                _require_verified_destination_path(
                    destination,
                    verified_destination,
                )
            finally:
                os.close(source_descriptor)
        finally:
            os.close(destination_descriptor)
    except BaseException:
        for identity in owned_identities:
            if _path_has_identity(destination, identity):
                try:
                    destination.unlink()
                except OSError:
                    pass
                break
        raise
    finally:
        os.close(staged_descriptor)


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ScreenEvidenceContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ScreenEvidenceContractError(f"non-finite JSON constant: {value}")


def _need_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ScreenEvidenceContractError(f"{label} must be a lowercase SHA-256 digest")
    return value


def _deterministic_json(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                indent=2,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            + b"\n"
        )
    except (TypeError, ValueError) as exc:
        raise ScreenEvidenceContractError(
            f"screen evidence is not deterministic JSON: {exc}"
        ) from exc


def _read_regular(
    path: str | os.PathLike[str],
    label: str,
    *,
    maximum_bytes: int = MAX_SCREEN_EVIDENCE_BYTES,
) -> bytes:
    target = Path(path)
    descriptor: int | None = None
    if not hasattr(os, "O_NOFOLLOW"):
        raise ScreenEvidenceContractError(
            f"platform cannot safely open {label} without following symlinks"
        )
    try:
        flags = os.O_RDONLY | os.O_NOFOLLOW
        flags |= getattr(os, "O_CLOEXEC", 0)
        descriptor = os.open(target, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ScreenEvidenceContractError(
                f"{label} must be a regular non-symlink file: {target}"
            )
        if metadata.st_size < 0 or metadata.st_size > maximum_bytes:
            raise ScreenEvidenceContractError(
                f"{label} exceeds its {maximum_bytes}-byte bound: {target}"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            raw = source.read(maximum_bytes + 1)
        if len(raw) != metadata.st_size or len(raw) > maximum_bytes:
            raise ScreenEvidenceContractError(
                f"{label} changed while it was being read: {target}"
            )
        return raw
    except ScreenEvidenceContractError:
        raise
    except OSError as exc:
        raise ScreenEvidenceContractError(
            f"could not safely read {label}: {target}: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)


def _load_json_bytes(raw: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except ScreenEvidenceContractError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScreenEvidenceContractError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ScreenEvidenceContractError(f"{label} must be a JSON object")
    return value


def _load_json(
    path: str | os.PathLike[str],
    label: str,
    *,
    maximum_bytes: int = MAX_SCREEN_EVIDENCE_BYTES,
) -> tuple[dict[str, Any], bytes]:
    raw = _read_regular(path, label, maximum_bytes=maximum_bytes)
    return _load_json_bytes(raw, label), raw


def read_screen_evidence_bytes(
    path: str | os.PathLike[str],
    label: str,
    *,
    maximum_bytes: int = MAX_SCREEN_EVIDENCE_BYTES,
) -> bytes:
    """Public bounded/no-follow byte reader for downstream consumers."""

    return _read_regular(path, label, maximum_bytes=maximum_bytes)


def load_screen_evidence_json(
    path: str | os.PathLike[str],
    label: str,
    *,
    maximum_bytes: int = MAX_SCREEN_EVIDENCE_BYTES,
) -> tuple[dict[str, Any], bytes]:
    """Parse duplicate-free JSON from the exact bounded bytes returned."""

    return _load_json(path, label, maximum_bytes=maximum_bytes)


def _atomic_publish(destination: Path, raw: bytes) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(raw)
            temporary.flush()
            os.fsync(temporary.fileno())
        _publish_verified_link(Path(temporary_name), destination, raw)
        os.unlink(temporary_name)
        temporary_name = None
        directory_descriptor = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    except OSError as exc:
        raise ScreenEvidenceContractError(
            f"could not publish screen evidence: {destination}: {exc}"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass


def load_frozen_screen_contract(
    manifest_path: str | os.PathLike[str],
    expected_sha256: str,
) -> dict[str, Any]:
    """Load the deterministic v2 screen plan through its frozen byte identity."""

    expected = _need_sha256(expected_sha256, "screen manifest SHA-256")
    payload, raw = _load_json(manifest_path, "screen manifest")
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ScreenEvidenceContractError(
            "screen manifest bytes differ from frozen SHA"
        )
    if set(payload) != {"schema_version", "contract"}:
        raise ScreenEvidenceContractError(
            "screen manifest has an open or incomplete envelope"
        )
    version = payload["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 2:
        raise ScreenEvidenceContractError(
            "screen manifest schema_version must be integer 2"
        )
    contract = payload["contract"]
    if not isinstance(contract, dict):
        raise ScreenEvidenceContractError("screen manifest contract must be an object")
    if _deterministic_json(payload) != raw:
        raise ScreenEvidenceContractError(
            "screen manifest bytes are not the deterministic v2 encoding"
        )
    return contract


def load_run_manifest_for_screen(
    run_manifest_path: str | os.PathLike[str],
    screen_manifest_sha256: str,
) -> dict[str, Any]:
    """Load one arm manifest and prove it belongs to the current screen."""

    expected = _need_sha256(screen_manifest_sha256, "screen manifest SHA-256")
    manifest, _raw = _load_json(run_manifest_path, "run manifest")
    if manifest.get("screen_manifest_sha256") != expected:
        raise ScreenEvidenceContractError("run manifest belongs to another screen")
    return manifest


def publish_or_validate_result(
    result_path: str | os.PathLike[str],
    recomputed_result: dict[str, Any],
    mode: str,
) -> None:
    """Publish a result once, or require exact recomputed evidence on retry."""

    if not isinstance(recomputed_result, dict):
        raise ScreenEvidenceContractError("recomputed screen result must be an object")
    raw = _deterministic_json(recomputed_result)
    if len(raw) > MAX_SCREEN_EVIDENCE_BYTES:
        raise ScreenEvidenceContractError(
            "recomputed screen result exceeds the evidence bound"
        )
    destination = Path(result_path)
    if mode == "validate":
        try:
            existing = _read_regular(
                destination,
                "recorded screen result",
                maximum_bytes=max(len(raw), 1),
            )
        except ScreenEvidenceContractError as exc:
            raise ScreenEvidenceContractError(
                f"recorded result differs from recomputed screen evidence: "
                f"{destination}"
            ) from exc
        if existing != raw:
            raise ScreenEvidenceContractError(
                f"recorded result differs from recomputed screen evidence: "
                f"{destination}"
            )
        return
    if mode != "write":
        raise ScreenEvidenceContractError(f"unknown result mode: {mode}")
    if destination.exists() or destination.is_symlink():
        raise ScreenEvidenceContractError(
            f"refusing to overwrite existing screen result: {destination}"
        )
    _atomic_publish(destination, raw)


def freeze_screen_completion(
    destination: str | os.PathLike[str],
    manifest_path: str | os.PathLike[str],
    manifest_sha256: str,
    out_dir: str | os.PathLike[str],
    prefix: str,
) -> None:
    """Recompute and freeze the complete accepted-result set for one screen."""

    manifest_sha = _need_sha256(manifest_sha256, "screen manifest SHA-256")
    contract = load_frozen_screen_contract(manifest_path, manifest_sha)
    if not isinstance(prefix, str) or not prefix:
        raise ScreenEvidenceContractError("screen prefix must be nonempty")
    if contract.get("prefix") != prefix:
        raise ScreenEvidenceContractError(
            "completion prefix differs from the frozen screen"
        )
    schedule = contract.get("schedule")
    if not isinstance(schedule, list):
        raise ScreenEvidenceContractError("frozen screen schedule must be an array")

    out = Path(out_dir)
    results: list[dict[str, Any]] = []
    for expected_index, entry in enumerate(schedule, 1):
        if not isinstance(entry, dict):
            raise ScreenEvidenceContractError(
                "frozen screen schedule entry must be an object"
            )
        arm = entry.get("arm")
        seed = entry.get("seed")
        index = entry.get("index")
        if not isinstance(arm, str) or not arm:
            raise ScreenEvidenceContractError(
                "frozen screen arm must be a nonempty string"
            )
        if (
            isinstance(seed, bool)
            or not isinstance(seed, int)
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index != expected_index
        ):
            raise ScreenEvidenceContractError(
                "frozen screen schedule has a noncanonical index or seed"
            )
        result_path = out / f"{prefix}-{arm}-s{seed}.result.json"
        result, result_raw = _load_json(result_path, "screen result")
        if result.get("trainer_complete") is not True:
            raise ScreenEvidenceContractError(
                f"result is not trainer-complete: {result_path}"
            )
        if result.get("acceptance_pass") is not True:
            raise ScreenEvidenceContractError(f"result is not accepted: {result_path}")
        for field, value in (
            ("arm", arm),
            ("seed", seed),
            ("tag", f"{prefix}-{arm}-s{seed}"),
            ("screen_manifest_sha256", manifest_sha),
        ):
            if result.get(field) != value:
                raise ScreenEvidenceContractError(
                    f"result {field} differs from the frozen screen: " f"{result_path}"
                )
        checkpoint_sha = _need_sha256(
            result.get("checkpoint_sha256"),
            f"result checkpoint SHA-256 for {arm}/seed {seed}",
        )
        lineage_sha = _need_sha256(
            result.get("checkpoint_lineage_sha256"),
            f"result checkpoint-lineage SHA-256 for {arm}/seed {seed}",
        )
        results.append(
            {
                "index": expected_index,
                "arm": arm,
                "seed": seed,
                "path": str(result_path),
                "sha256": hashlib.sha256(result_raw).hexdigest(),
                "checkpoint_sha256": checkpoint_sha,
                "checkpoint_lineage_sha256": lineage_sha,
            }
        )

    payload = {
        "schema_version": 2,
        "screen_manifest_sha256": manifest_sha,
        "results": results,
    }
    raw = _deterministic_json(payload)
    target = Path(destination)
    if target.exists() or target.is_symlink():
        try:
            existing = _read_regular(
                target,
                "existing screen completion",
                maximum_bytes=max(len(raw), 1),
            )
        except ScreenEvidenceContractError as exc:
            raise ScreenEvidenceContractError(
                "existing screen completion differs from recomputed results"
            ) from exc
        if existing != raw:
            raise ScreenEvidenceContractError(
                "existing screen completion differs from recomputed results"
            )
        return
    _atomic_publish(target, raw)
