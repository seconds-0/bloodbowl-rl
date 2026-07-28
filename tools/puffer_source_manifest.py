#!/usr/bin/env python3
"""Validate and hash canonical Puffer source-path ledgers.

The repository has two deliberately different source closures:

* the nine files that define the compiled backend identity; and
* the historical twelve-file launcher/vendor identity.

Both are checked-in, ordered ledgers.  Consumers must read those ledgers
instead of carrying independent path lists, and every digest binds each file
to its relative path:

    sha256(file) + "  " + relative_path + "\n"
"""

from __future__ import annotations

import argparse
import hashlib
import re
import stat
import sys
from pathlib import Path, PurePosixPath
from typing import Iterable


MAX_LEDGER_BYTES = 16 * 1024
_SAFE_COMPONENT = re.compile(r"[A-Za-z0-9_.-]+\Z")


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
    current = root
    try:
        root_info = current.stat(follow_symlinks=False)
    except OSError as exc:
        raise PufferSourceManifestError(
            f"Puffer source root is missing: {root}: {exc}"
        ) from exc
    if not stat.S_ISDIR(root_info.st_mode):
        raise PufferSourceManifestError(
            f"Puffer source root must be a directory: {root}"
        )
    for component in components[:-1]:
        current /= component
        try:
            info = current.stat(follow_symlinks=False)
        except OSError as exc:
            raise PufferSourceManifestError(
                f"Puffer source parent is missing: {current}: {exc}"
            ) from exc
        if not stat.S_ISDIR(info.st_mode):
            raise PufferSourceManifestError(
                "every Puffer source parent must be a real directory, "
                f"not a symlink or other file: {current}"
            )
    source = current / components[-1]
    try:
        info = source.stat(follow_symlinks=False)
    except OSError as exc:
        raise PufferSourceManifestError(
            f"Puffer source is missing: {source}: {exc}"
        ) from exc
    if not stat.S_ISREG(info.st_mode):
        raise PufferSourceManifestError(
            f"Puffer source must be a regular non-symlink file: {source}"
        )
    try:
        return source.read_bytes()
    except OSError as exc:
        raise PufferSourceManifestError(
            f"cannot read Puffer source {source}: {exc}"
        ) from exc


def source_manifest_sha256(root: str | Path, sources: Iterable[str]) -> str:
    """Hash an already validated ordered source closure."""

    root = Path(root).resolve()
    digest = hashlib.sha256()
    observed: set[str] = set()
    for index, relative in enumerate(sources, 1):
        relative = _validate_relative_source_path(
            relative, location=f"hash input {index}"
        )
        if relative in observed:
            raise PufferSourceManifestError(
                f"duplicate Puffer source path supplied for hashing: {relative}"
            )
        observed.add(relative)
        payload = _regular_source_bytes(root, relative)
        digest.update(hashlib.sha256(payload).hexdigest().encode("ascii"))
        digest.update(b"  ")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\n")
    if not observed:
        raise PufferSourceManifestError("Puffer source closure is empty")
    return digest.hexdigest()


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
    parser.add_argument("--plain", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.expected_count is not None and args.expected_count <= 0:
        raise PufferSourceManifestError("expected count must be positive")
    value = ledger_source_sha256(
        args.root,
        args.ledger,
        expected_count=args.expected_count,
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
