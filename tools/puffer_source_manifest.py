#!/usr/bin/env python3
"""Validate and hash canonical Puffer source-path ledgers.

The repository has two deliberately different source closures:

* the fourteen files that define the compiled backend identity; and
* the historical twelve-file launcher/vendor identity.

Both are checked-in, ordered ledgers.  Consumers must read those ledgers
instead of carrying independent path lists, and every digest binds each file
to its relative path:

    sha256(file) + "  " + relative_path + "\n"
"""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable, Mapping


MAX_LEDGER_BYTES = 16 * 1024
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9_.-]+\Z")
_LOCAL_INCLUDE = re.compile(
    rb'^[ \t]*#[ \t]*include[ \t]*"([^"\r\n]+)"',
    re.MULTILINE,
)
NATIVE_EXTENSION_ROOTS = (
    "src/bindings.cu",
    "src/bindings_cpu.cpp",
)
GENERATED_NATIVE_INCLUDE_EXCEPTIONS = (
    "src/exact_action_build_hash.h",
)


class PufferSourceManifestError(ValueError):
    """A malformed ledger or incomplete source closure."""


def _validate_relative_source_path(relative: object, *, location: str) -> str:
    if not isinstance(relative, str):
        raise PufferSourceManifestError(
            f"Puffer source path at {location} must be a string"
        )
    if "\\" in relative or relative.startswith("/") or relative.startswith("#"):
        raise PufferSourceManifestError(
            f"unsafe Puffer source path at {location}: {relative!r}"
        )
    pure = PurePosixPath(relative)
    if (
        not relative
        or pure.is_absolute()
        or pure.as_posix() != relative
        or any(
            component in ("", ".", "..") or _SAFE_COMPONENT.fullmatch(component) is None
            for component in pure.parts
        )
    ):
        raise PufferSourceManifestError(
            f"noncanonical Puffer source path at {location}: {relative!r}"
        )
    return relative


def read_source_ledger(
    ledger: str | Path,
    *,
    expected_count: int | None = None,
) -> tuple[str, ...]:
    """Return one closed, ordered, safe relative-path ledger."""

    ledger = Path(ledger)
    try:
        raw = ledger.read_bytes()
    except OSError as exc:
        raise PufferSourceManifestError(
            f"cannot read Puffer source ledger {ledger}: {exc}"
        ) from exc
    if len(raw) > MAX_LEDGER_BYTES:
        raise PufferSourceManifestError(
            f"Puffer source ledger exceeds {MAX_LEDGER_BYTES} bytes: {ledger}"
        )
    if not raw or not raw.endswith(b"\n"):
        raise PufferSourceManifestError(
            f"Puffer source ledger must be nonempty and newline-terminated: {ledger}"
        )
    if b"\r" in raw or b"\0" in raw:
        raise PufferSourceManifestError(
            f"Puffer source ledger contains a forbidden control byte: {ledger}"
        )
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise PufferSourceManifestError(
            f"Puffer source ledger is not UTF-8: {ledger}"
        ) from exc

    entries: list[str] = []
    seen: set[str] = set()
    for line_number, relative in enumerate(text.split("\n")[:-1], 1):
        if not relative:
            raise PufferSourceManifestError(
                f"Puffer source ledger line {line_number} is blank"
            )
        relative = _validate_relative_source_path(
            relative, location=f"ledger line {line_number}"
        )
        if relative in seen:
            raise PufferSourceManifestError(
                f"duplicate Puffer source path on line {line_number}: {relative}"
            )
        seen.add(relative)
        entries.append(relative)

    if expected_count is not None and len(entries) != expected_count:
        raise PufferSourceManifestError(
            f"Puffer source ledger has {len(entries)} paths; expected "
            f"{expected_count}"
        )
    return tuple(entries)


def _regular_source_bytes(root: Path, relative: str) -> bytes:
    components = PurePosixPath(relative).parts
    directory_flags = os.O_RDONLY
    directory_flags |= getattr(os, "O_CLOEXEC", 0)
    directory_flags |= getattr(os, "O_DIRECTORY", 0)
    directory_flags |= getattr(os, "O_NOFOLLOW", 0)
    source_flags = os.O_RDONLY
    source_flags |= getattr(os, "O_CLOEXEC", 0)
    source_flags |= getattr(os, "O_NOFOLLOW", 0)
    directory_descriptors: list[int] = []
    try:
        root_descriptor = os.open(root, directory_flags)
    except OSError as exc:
        raise PufferSourceManifestError(
            f"Puffer source root is missing: {root}: {exc}"
        ) from exc
    directory_descriptors.append(root_descriptor)
    try:
        try:
            root_info = os.fstat(root_descriptor)
        except OSError as exc:
            raise PufferSourceManifestError(
                f"cannot inspect Puffer source root {root}: {exc}"
            ) from exc
        if not stat.S_ISDIR(root_info.st_mode):
            raise PufferSourceManifestError(
                f"Puffer source root must be a directory: {root}"
            )
        current = root
        for component in components[:-1]:
            current /= component
            try:
                descriptor = os.open(
                    component,
                    directory_flags,
                    dir_fd=directory_descriptors[-1],
                )
            except OSError as exc:
                raise PufferSourceManifestError(
                    "every Puffer source parent must be a real directory, "
                    f"not a symlink or other file: {current}: {exc}"
                ) from exc
            directory_descriptors.append(descriptor)
        source = current / components[-1]
        try:
            source_descriptor = os.open(
                components[-1],
                source_flags,
                dir_fd=directory_descriptors[-1],
            )
        except FileNotFoundError as exc:
            raise PufferSourceManifestError(
                f"Puffer source is missing: {source}: {exc}"
            ) from exc
        except OSError as exc:
            raise PufferSourceManifestError(
                "Puffer source must be a regular non-symlink file: "
                f"{source}: {exc}"
            ) from exc
        try:
            info = os.fstat(source_descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise PufferSourceManifestError(
                    f"Puffer source must be a regular non-symlink file: {source}"
                )
            with os.fdopen(source_descriptor, "rb", closefd=True) as handle:
                source_descriptor = -1
                payload = handle.read()
            if len(payload) != info.st_size:
                raise PufferSourceManifestError(
                    f"Puffer source size changed while reading: {source}"
                )
            return payload
        finally:
            if source_descriptor >= 0:
                os.close(source_descriptor)
    finally:
        for descriptor in reversed(directory_descriptors):
            os.close(descriptor)


def _snapshot_sources(
    root: str | Path,
    sources: Iterable[str],
) -> tuple[Path, tuple[str, ...], dict[str, bytes]]:
    root = Path(root).resolve()
    ordered: list[str] = []
    snapshots: dict[str, bytes] = {}
    observed: set[str] = set()
    for index, relative in enumerate(sources, 1):
        relative = _validate_relative_source_path(
            relative,
            location=f"source snapshot input {index}",
        )
        if relative in observed:
            raise PufferSourceManifestError(
                f"duplicate Puffer source path supplied for hashing: {relative}"
            )
        observed.add(relative)
        ordered.append(relative)
        snapshots[relative] = _regular_source_bytes(root, relative)
    if not observed:
        raise PufferSourceManifestError("Puffer source closure is empty")
    return root, tuple(ordered), snapshots


def _manifest_sha256_from_snapshots(
    sources: Iterable[str],
    snapshots: Mapping[str, bytes],
) -> str:
    digest = hashlib.sha256()
    observed = False
    for relative in sources:
        observed = True
        payload = snapshots[relative]
        digest.update(hashlib.sha256(payload).hexdigest().encode("ascii"))
        digest.update(b"  ")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\n")
    if not observed:
        raise PufferSourceManifestError("Puffer source closure is empty")
    return digest.hexdigest()


def source_manifest_sha256(root: str | Path, sources: Iterable[str]) -> str:
    """Hash one ordered source closure from exact descriptor-read snapshots."""

    _, ordered, snapshots = _snapshot_sources(root, sources)
    return _manifest_sha256_from_snapshots(ordered, snapshots)


def validate_native_extension_include_closure(
    root: str | Path,
    sources: Iterable[str],
    *,
    roots: Iterable[str] = NATIVE_EXTENSION_ROOTS,
    generated_exceptions: Iterable[str] = (
        GENERATED_NATIVE_INCLUDE_EXCEPTIONS
    ),
    _source_bytes: Mapping[str, bytes] | None = None,
) -> tuple[str, ...]:
    """Require every recursively quoted native include to be registered.

    The generated exact-action identity header is deliberately outside the
    digest it contains. It is authenticated independently by the installer,
    generated header, and imported module equality checks.
    """

    root = Path(root).resolve()
    registered = {
        _validate_relative_source_path(
            relative,
            location=f"native include registry entry {index}",
        )
        for index, relative in enumerate(sources, 1)
    }
    exceptions = {
        _validate_relative_source_path(
            relative,
            location=f"generated include exception {index}",
        )
        for index, relative in enumerate(generated_exceptions, 1)
    }
    pending = [
        _validate_relative_source_path(
            relative,
            location=f"native extension root {index}",
        )
        for index, relative in enumerate(roots, 1)
    ]
    for relative in pending:
        if relative not in registered:
            raise PufferSourceManifestError(
                f"native extension root is not registered: {relative}"
            )

    visited: set[str] = set()
    while pending:
        relative = pending.pop()
        if relative in visited:
            continue
        visited.add(relative)
        payload = (
            _source_bytes[relative]
            if _source_bytes is not None
            else _regular_source_bytes(root, relative)
        )
        for match in _LOCAL_INCLUDE.finditer(payload):
            try:
                include = match.group(1).decode("utf-8")
            except UnicodeDecodeError as exc:
                raise PufferSourceManifestError(
                    f"non-UTF-8 local include in {relative}"
                ) from exc
            if "\\" in include:
                raise PufferSourceManifestError(
                    f"noncanonical local include in {relative}: {include!r}"
                )
            include_path = PurePosixPath(include)
            if (
                include_path.is_absolute()
                or any(part in ("", ".", "..") for part in include_path.parts)
            ):
                raise PufferSourceManifestError(
                    f"unsafe local include in {relative}: {include!r}"
                )
            included = (PurePosixPath(relative).parent / include_path).as_posix()
            included = _validate_relative_source_path(
                included,
                location=f"local include in {relative}",
            )
            if included in exceptions:
                continue
            if included not in registered:
                raise PufferSourceManifestError(
                    f"unregistered local include {included!r} from {relative}"
                )
            if included not in visited:
                pending.append(included)
    return tuple(sorted(visited))


def native_extension_source_manifest_sha256(
    root: str | Path,
    sources: Iterable[str],
) -> str:
    """Validate and hash the extension closure from one coherent snapshot set."""

    root, ordered, snapshots = _snapshot_sources(root, sources)
    validate_native_extension_include_closure(
        root,
        ordered,
        _source_bytes=snapshots,
    )
    return _manifest_sha256_from_snapshots(ordered, snapshots)


def ledger_source_sha256(
    root: str | Path,
    ledger: str | Path,
    *,
    expected_count: int | None = None,
) -> str:
    return source_manifest_sha256(
        root,
        read_source_ledger(ledger, expected_count=expected_count),
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--ledger", type=Path, required=True)
    parser.add_argument("--expected-count", type=int)
    parser.add_argument(
        "--require-native-extension-closure",
        action="store_true",
    )
    parser.add_argument("--plain", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.expected_count is not None and args.expected_count <= 0:
        raise PufferSourceManifestError("expected count must be positive")
    sources = read_source_ledger(
        args.ledger,
        expected_count=args.expected_count,
    )
    value = (
        native_extension_source_manifest_sha256(args.root, sources)
        if args.require_native_extension_closure
        else source_manifest_sha256(args.root, sources)
    )
    if args.plain:
        print(value)
    else:
        print(f'{{"sha256":"{value}"}}')
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PufferSourceManifestError as exc:
        print(f"Puffer source manifest failed: {exc}", file=sys.stderr)
        raise SystemExit(2)
