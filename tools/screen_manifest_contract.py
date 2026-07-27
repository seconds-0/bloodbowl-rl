"""Freeze one immutable reward-screen contract across retries."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_SCREEN_MANIFEST_BYTES = 16 * 1024 * 1024


class ScreenManifestContractError(ValueError):
    """The on-disk screen plan is malformed or differs from this retry."""


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
        raise ScreenManifestContractError(
            "platform cannot publish a screen manifest without no-follow opens"
        )
    flags = os.O_RDONLY | os.O_NOFOLLOW
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NONBLOCK", 0)
    try:
        return os.open(path, flags)
    except OSError as exc:
        raise ScreenManifestContractError(
            f"linked screen manifest differs from verified temporary: "
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
        raise ScreenManifestContractError(
            f"linked screen manifest differs from verified temporary: "
            f"{label} is not regular"
        )
    if expected_identity is not None and identity != expected_identity:
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: "
            f"{label} inode changed"
        )
    if before.st_size != len(raw):
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: "
            f"{label} size changed"
        )
    chunks: list[bytes] = []
    remaining = len(raw)
    while remaining:
        chunk = os.read(descriptor, min(1024 * 1024, remaining))
        if not chunk:
            raise ScreenManifestContractError(
                "linked screen manifest differs from verified temporary: "
                f"{label} became shorter"
            )
        chunks.append(chunk)
        remaining -= len(chunk)
    if os.read(descriptor, 1):
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: " f"{label} grew"
        )
    after = os.fstat(descriptor)
    if (
        after.st_dev != before.st_dev
        or after.st_ino != before.st_ino
        or after.st_size != before.st_size
        or after.st_mtime_ns != before.st_mtime_ns
        or after.st_ctime_ns != before.st_ctime_ns
    ):
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: "
            f"{label} changed while read"
        )
    observed = b"".join(chunks)
    if (
        observed != raw
        or hashlib.sha256(observed).digest() != hashlib.sha256(raw).digest()
    ):
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: "
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
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: "
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
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: "
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
        raise ScreenManifestContractError(
            "linked screen manifest differs from verified temporary: "
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
                    raise ScreenManifestContractError(
                        "linked screen manifest differs from verified temporary: "
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
            raise ScreenManifestContractError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ScreenManifestContractError(f"non-finite JSON constant: {value}")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ScreenManifestContractError(
            f"screen contract is not canonical JSON: {exc}"
        ) from exc


def _load_existing(path: Path) -> tuple[dict[str, Any], bytes]:
    descriptor: int | None = None
    try:
        flags = os.O_RDONLY
        flags |= getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise ScreenManifestContractError(
                "existing screen manifest must be a regular non-symlink file"
            )
        if metadata.st_size > MAX_SCREEN_MANIFEST_BYTES:
            raise ScreenManifestContractError(
                "existing screen manifest exceeds the 16 MiB bound"
            )
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            raw = source.read(MAX_SCREEN_MANIFEST_BYTES + 1)
        if len(raw) > MAX_SCREEN_MANIFEST_BYTES:
            raise ScreenManifestContractError(
                "existing screen manifest exceeds the 16 MiB bound"
            )
    except ScreenManifestContractError:
        raise
    except OSError as exc:
        raise ScreenManifestContractError(
            f"cannot safely read existing screen manifest: {exc}"
        ) from exc
    finally:
        if descriptor is not None:
            os.close(descriptor)
    try:
        payload = json.loads(
            raw,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_constant,
        )
    except ScreenManifestContractError:
        raise
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScreenManifestContractError(
            f"existing screen manifest is malformed: {exc}"
        ) from exc
    if not isinstance(payload, dict):
        raise ScreenManifestContractError(
            "existing screen manifest must be a JSON object"
        )
    if set(payload) != {"schema_version", "contract"}:
        raise ScreenManifestContractError(
            "existing screen manifest has an open or incomplete envelope"
        )
    version = payload["schema_version"]
    if isinstance(version, bool) or not isinstance(version, int) or version != 2:
        raise ScreenManifestContractError(
            "existing screen manifest schema_version must be integer 2"
        )
    if not isinstance(payload["contract"], dict):
        raise ScreenManifestContractError(
            "existing screen manifest contract must be an object"
        )
    return payload, raw


def freeze_screen_manifest(
    destination: str | os.PathLike[str],
    contract: dict[str, Any],
) -> str:
    """Create a manifest once, or prove an existing retry is byte-plan-identical."""

    if not isinstance(contract, dict):
        raise ScreenManifestContractError("screen contract must be an object")
    canonical_contract = _canonical(contract)
    payload = {
        "schema_version": 2,
        "contract": contract,
    }
    raw = (
        json.dumps(
            payload,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )
    if len(raw) > MAX_SCREEN_MANIFEST_BYTES:
        raise ScreenManifestContractError("screen manifest exceeds the 16 MiB bound")

    path = Path(destination)
    if path.exists() or path.is_symlink():
        existing_payload, existing_raw = _load_existing(path)
        if _canonical(existing_payload["contract"]) != canonical_contract:
            raise ScreenManifestContractError(
                "existing screen manifest contract differs from this retry"
            )
        if existing_raw != raw:
            raise ScreenManifestContractError(
                "existing screen manifest bytes differ from the deterministic "
                "screen manifest"
            )
        return hashlib.sha256(existing_raw).hexdigest()

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            temporary.write(raw)
            temporary.flush()
            os.fsync(temporary.fileno())
        _publish_verified_link(Path(temporary_name), path, raw)
        os.unlink(temporary_name)
        temporary_name = None
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except OSError as exc:
        raise ScreenManifestContractError(
            f"could not publish screen manifest: {exc}"
        ) from exc
    finally:
        if temporary_name is not None:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
    return hashlib.sha256(raw).hexdigest()
