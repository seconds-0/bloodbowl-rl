#!/usr/bin/env python3
"""Filter a BBS1 state bank through a hash-pinned replay-ID allowlist.

The BBS1 header does not contain a record count. Its four fields are magic,
version, raw ``bb_match`` size, and engine fingerprint; record count is derived
from file size. Selected records and the header are therefore copied byte for
byte. The opaque match blob is never decoded or rewritten here.

The manifest is the commit marker for the three-output transaction. Output,
selected-ID list, and manifest must share a directory; each is built and
fsynced under a temporary name, then the manifest is published last. Existing
destinations are never overwritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
from collections import Counter
from pathlib import Path
from typing import Any


HEADER = struct.Struct("<4sIII")
META = struct.Struct("<IIBB2s")
MAGIC = b"BBS1"
VERSION = 1
MAX_MATCH_SIZE = 16 * 1024 * 1024
MAX_HALF = 3
MAX_TURN = 8
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ID_RE = re.compile(r"[0-9]+")


class StateBankError(RuntimeError):
    """A fail-closed BBS or provenance-contract violation."""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _validate_expected_sha(value: str, label: str) -> None:
    if SHA256_RE.fullmatch(value) is None:
        raise StateBankError(f"{label} expected SHA-256 is not lowercase hex")


def load_allowlist(path: Path, payload: bytes | None = None) -> set[int]:
    try:
        if payload is None:
            payload = path.read_bytes()
        text = payload.decode("utf-8-sig")
    except (OSError, UnicodeError) as exc:
        raise StateBankError(f"cannot read allowlist {path}: {exc}") from exc
    replay_ids: set[int] = set()
    for line_number, raw in enumerate(text.splitlines(), 1):
        value = raw.strip()
        if not value:
            continue
        if ID_RE.fullmatch(value) is None:
            raise StateBankError(
                f"non-numeric allowlist ID at line {line_number}: {value!r}"
            )
        replay_id = int(value)
        if not 1 <= replay_id <= 0xFFFFFFFF:
            raise StateBankError(
                f"out of range allowlist ID at line {line_number}: {value!r}"
            )
        if value != str(replay_id):
            raise StateBankError(
                f"non-canonical allowlist ID at line {line_number}: {value!r}"
            )
        if replay_id in replay_ids:
            raise StateBankError(f"duplicate allowlist ID: {replay_id}")
        replay_ids.add(replay_id)
    if not replay_ids:
        raise StateBankError("empty allowlist")
    return replay_ids


def _histogram(counter: Counter[int]) -> dict[str, int]:
    return {str(key): counter[key] for key in sorted(counter)}


def _new_temporary(destination: Path) -> Path:
    descriptor, name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    return Path(name)


def _write_bytes(path: Path, payload: bytes) -> None:
    with path.open("wb") as target:
        target.write(payload)
        target.flush()
        os.fsync(target.fileno())


def _fsync_directory(path: Path) -> None:
    directory_fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _check_count(observed: int, expected: int | None, label: str) -> None:
    if expected is not None and observed != expected:
        raise StateBankError(
            f"{label} count mismatch: observed {observed}, expected {expected}"
        )


def filter_state_bank(
    input_path: str | Path,
    output_path: str | Path,
    *,
    allowlist_path: str | Path,
    selected_ids_path: str | Path,
    manifest_path: str | Path,
    expected_input_sha256: str,
    expected_allowlist_sha256: str,
    command: list[str],
    expected_input_records: int | None = None,
    expected_input_replay_ids: int | None = None,
    expected_selected_records: int | None = None,
    expected_selected_replay_ids: int | None = None,
) -> dict[str, Any]:
    input_path = Path(input_path).expanduser().resolve()
    allowlist_path = Path(allowlist_path).expanduser().resolve()
    output_path = Path(output_path).expanduser().resolve()
    selected_ids_path = Path(selected_ids_path).expanduser().resolve()
    manifest_path = Path(manifest_path).expanduser().resolve()
    all_paths = (
        input_path,
        allowlist_path,
        output_path,
        selected_ids_path,
        manifest_path,
    )
    if len(set(all_paths)) != len(all_paths):
        raise StateBankError("input, allowlist, and output paths must be distinct")
    if not input_path.is_file():
        raise StateBankError(f"input bank is not a file: {input_path}")
    if not allowlist_path.is_file():
        raise StateBankError(f"allowlist is not a file: {allowlist_path}")
    destinations = (output_path, selected_ids_path, manifest_path)
    if len({path.parent for path in destinations}) != 1:
        raise StateBankError("all output paths must share one directory")
    output_directory = output_path.parent
    if not output_directory.is_dir():
        raise StateBankError(f"output directory does not exist: {output_directory}")
    for path in destinations:
        if path.exists():
            raise StateBankError(f"output already exists: {path}")
    if not command or not all(isinstance(item, str) and item for item in command):
        raise StateBankError("command must be a nonempty string array")

    _validate_expected_sha(expected_input_sha256, "input")
    _validate_expected_sha(expected_allowlist_sha256, "allowlist")
    input_sha = sha256(input_path)
    if input_sha != expected_input_sha256:
        raise StateBankError(
            f"input SHA-256 mismatch: {input_sha} != {expected_input_sha256}"
        )
    try:
        allowlist_payload = allowlist_path.read_bytes()
    except OSError as exc:
        raise StateBankError(f"cannot read allowlist {allowlist_path}: {exc}") from exc
    allowlist_sha = hashlib.sha256(allowlist_payload).hexdigest()
    if allowlist_sha != expected_allowlist_sha256:
        raise StateBankError(
            "allowlist SHA-256 mismatch: "
            f"{allowlist_sha} != {expected_allowlist_sha256}"
        )
    allowlist = load_allowlist(allowlist_path, allowlist_payload)

    input_bytes = input_path.stat().st_size
    if input_bytes < HEADER.size:
        raise StateBankError("truncated BBS1 header")
    with input_path.open("rb") as source:
        header = source.read(HEADER.size)
    magic, version, match_size, fingerprint = HEADER.unpack(header)
    if magic != MAGIC:
        raise StateBankError(f"bad magic: {magic!r}")
    if version != VERSION:
        raise StateBankError(f"unsupported version: {version}")
    if not 0 < match_size <= MAX_MATCH_SIZE:
        raise StateBankError(
            "zero match size"
            if match_size == 0
            else f"implausible match size: {match_size}"
        )
    if fingerprint == 0:
        raise StateBankError("zero fingerprint")
    record_size = META.size + match_size
    body_bytes = input_bytes - HEADER.size
    if body_bytes % record_size:
        raise StateBankError(
            f"partial record: {body_bytes} body bytes is not divisible by "
            f"{record_size}"
        )
    input_records = body_bytes // record_size
    if input_records == 0:
        raise StateBankError("input bank has no records")

    temporaries: list[Path] = []
    published: list[tuple[Path, Path]] = []
    committed = False
    try:
        temporary_output = _new_temporary(output_path)
        temporaries.append(temporary_output)
        temporary_ids = _new_temporary(selected_ids_path)
        temporaries.append(temporary_ids)
        temporary_manifest = _new_temporary(manifest_path)
        temporaries.append(temporary_manifest)
        input_ids: set[int] = set()
        selected_ids: set[int] = set()
        excluded_ids: set[int] = set()
        input_half: Counter[int] = Counter()
        input_turn: Counter[int] = Counter()
        output_half: Counter[int] = Counter()
        output_turn: Counter[int] = Counter()
        selected_records = 0
        scan_digest = hashlib.sha256()

        with input_path.open("rb") as source, temporary_output.open("wb") as target:
            observed_header = source.read(HEADER.size)
            if observed_header != header:
                raise StateBankError("input header changed after hash validation")
            scan_digest.update(observed_header)
            target.write(header)
            for index in range(input_records):
                metadata = source.read(META.size)
                if len(metadata) != META.size:
                    raise StateBankError(f"partial record metadata at index {index}")
                scan_digest.update(metadata)
                replay_id, _command, half, turn, padding = META.unpack(metadata)
                if replay_id == 0:
                    raise StateBankError(f"zero replay ID at record {index}")
                if padding != b"\0\0":
                    raise StateBankError(f"nonzero metadata padding at record {index}")
                if not 1 <= half <= MAX_HALF:
                    raise StateBankError(f"half out of range at record {index}: {half}")
                if not 1 <= turn <= MAX_TURN:
                    raise StateBankError(f"turn out of range at record {index}: {turn}")
                match_blob = source.read(match_size)
                if len(match_blob) != match_size:
                    raise StateBankError(f"partial match blob at record {index}")
                scan_digest.update(match_blob)
                input_ids.add(replay_id)
                input_half[half] += 1
                input_turn[turn] += 1
                if replay_id in allowlist:
                    target.write(metadata)
                    target.write(match_blob)
                    selected_ids.add(replay_id)
                    output_half[half] += 1
                    output_turn[turn] += 1
                    selected_records += 1
                else:
                    excluded_ids.add(replay_id)
            if source.read(1):
                raise StateBankError("input grew after hash validation")
            target.flush()
            os.fsync(target.fileno())
        if (
            scan_digest.hexdigest() != input_sha
            or input_path.stat().st_size != input_bytes
        ):
            raise StateBankError("input changed after hash validation")

        if selected_records == 0:
            raise StateBankError("no records selected by allowlist")
        _check_count(input_records, expected_input_records, "input record")
        _check_count(len(input_ids), expected_input_replay_ids, "input replay-ID")
        _check_count(selected_records, expected_selected_records, "selected record")
        _check_count(
            len(selected_ids),
            expected_selected_replay_ids,
            "selected replay-ID",
        )

        selected_payload = "".join(
            f"{replay_id}\n" for replay_id in sorted(selected_ids)
        ).encode("ascii")
        _write_bytes(temporary_ids, selected_payload)
        output_sha = sha256(temporary_output)
        selected_ids_sha = sha256(temporary_ids)
        tool_path = Path(__file__).resolve()
        manifest: dict[str, Any] = {
            "schema_version": 1,
            "tool": {
                "path": str(tool_path),
                "sha256": sha256(tool_path),
            },
            "command": command,
            "format": {
                "magic": magic.decode("ascii"),
                "version": version,
                "match_size": match_size,
                "engine_fingerprint": f"0x{fingerprint:08x}",
                "record_count_is_file_size_derived": True,
            },
            "input": {
                "path": str(input_path),
                "bytes": input_bytes,
                "sha256": input_sha,
                "records": input_records,
                "replay_ids": len(input_ids),
                "half_histogram": _histogram(input_half),
                "turn_histogram": _histogram(input_turn),
            },
            "allowlist": {
                "path": str(allowlist_path),
                "bytes": len(allowlist_payload),
                "sha256": allowlist_sha,
                "ids_total": len(allowlist),
                "ids_matched": len(selected_ids),
                "ids_unmatched": len(allowlist - selected_ids),
            },
            "output": {
                "path": str(output_path),
                "bytes": temporary_output.stat().st_size,
                "sha256": output_sha,
                "records": selected_records,
                "replay_ids": len(selected_ids),
                "half_histogram": _histogram(output_half),
                "turn_histogram": _histogram(output_turn),
            },
            "selected_ids": {
                "path": str(selected_ids_path),
                "bytes": len(selected_payload),
                "sha256": selected_ids_sha,
                "count": len(selected_ids),
            },
            "excluded": {
                "records": input_records - selected_records,
                "replay_ids": len(excluded_ids),
                "replay_id_values": sorted(excluded_ids),
            },
            "limitations": [
                "Edition identity comes from the external replay-ID allowlist, "
                "not from BBS1 bytes.",
                "The filtered historical bank remains half one and opening "
                "censored; it does not supply late-game scenarios.",
                "Recorded replay outcomes are not labels of pre-dice action "
                "quality.",
                "A future from-source rebuild with build-time edition filtering "
                "should supersede this subset artifact.",
            ],
        }
        manifest_payload = (
            json.dumps(manifest, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8")
        _write_bytes(temporary_manifest, manifest_payload)

        # Hard-link publication is exclusive: unlike os.replace(), it cannot
        # clobber a destination created after the entry-time existence check.
        # Keep temporary links until commit so cleanup can verify inode
        # ownership before removing a published name.
        for temporary, destination in (
            (temporary_output, output_path),
            (temporary_ids, selected_ids_path),
        ):
            published.append((temporary, destination))
            os.link(temporary, destination)
        _fsync_directory(output_directory)
        published.append((temporary_manifest, manifest_path))
        os.link(temporary_manifest, manifest_path)
        _fsync_directory(output_directory)
        committed = True
        for path in temporaries:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            _fsync_directory(output_directory)
        except OSError:
            pass
        return manifest
    except BaseException:
        if not committed:
            for temporary, destination in reversed(published):
                try:
                    if destination.samefile(temporary):
                        destination.unlink()
                except OSError:
                    pass
        for path in temporaries:
            try:
                path.unlink()
            except OSError:
                pass
        try:
            _fsync_directory(output_directory)
        except OSError:
            pass
        raise


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--allowlist", type=Path, required=True)
    parser.add_argument("--selected-ids", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--expect-input-sha256", required=True)
    parser.add_argument("--expect-allowlist-sha256", required=True)
    parser.add_argument("--expect-input-records", type=int)
    parser.add_argument("--expect-input-replay-ids", type=int)
    parser.add_argument("--expect-selected-records", type=int)
    parser.add_argument("--expect-selected-replay-ids", type=int)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    args = parse_args(raw_argv)
    command = [str(Path(sys.executable).resolve()), str(Path(__file__).resolve())]
    command.extend(raw_argv)
    try:
        result = filter_state_bank(
            args.input,
            args.output,
            allowlist_path=args.allowlist,
            selected_ids_path=args.selected_ids,
            manifest_path=args.manifest,
            expected_input_sha256=args.expect_input_sha256,
            expected_allowlist_sha256=args.expect_allowlist_sha256,
            expected_input_records=args.expect_input_records,
            expected_input_replay_ids=args.expect_input_replay_ids,
            expected_selected_records=args.expect_selected_records,
            expected_selected_replay_ids=args.expect_selected_replay_ids,
            command=command,
        )
    except (OSError, StateBankError, ValueError) as exc:
        print(f"state-bank filter failed: {exc}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "manifest": str(Path(args.manifest).resolve()),
                "output_sha256": result["output"]["sha256"],
                "records": result["output"]["records"],
                "replay_ids": result["output"]["replay_ids"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
