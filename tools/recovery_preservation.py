#!/usr/bin/env python3
"""Build and verify an exact recovery-evidence preservation inventory.

The planner reads a stopped, atomically completed recovery queue. It writes only
one caller-selected inventory outside the recovery root. The verifier then
checks an independently copied tree against every recorded relative path, byte
count, mode, and SHA-256 value.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


SCHEMA_VERSION = 1
KIND = "bloodbowl_recovery_preservation_inventory"
COMPLETE_MESSAGE = "all queued jobs completed and validated"
EXPECTED_JOB_IDS = {"terminal-evidence-preflight", "full-control-rerun"}
EXPECTED_SEEDS = {42, 43, 44}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class PreservationError(RuntimeError):
    """The requested evidence inventory is incomplete, unstable, or invalid."""


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _strict_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            object_pairs_hook=_strict_object,
            parse_constant=_reject_constant,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise PreservationError(f"cannot read strict JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise PreservationError(f"JSON artifact is not an object: {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with Path(path).open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                digest.update(chunk)
    except OSError as exc:
        raise PreservationError(f"cannot hash {path}: {exc}") from exc
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or SHA256_RE.fullmatch(value) is None:
        raise PreservationError(f"{label} is not a lowercase SHA-256")
    return value


def _require_regular(path: Path, label: str) -> Path:
    path = Path(path)
    try:
        info = path.lstat()
    except OSError as exc:
        raise PreservationError(f"cannot inspect {label} {path}: {exc}") from exc
    if path.is_symlink() or not stat.S_ISREG(info.st_mode):
        raise PreservationError(f"{label} is not a regular non-symlink file: {path}")
    return path


def _relative_file(path: Path, root: Path, label: str) -> str:
    path = _require_regular(Path(path), label).resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise PreservationError(f"{label} escapes the recovery root: {path}") from exc
    value = relative.as_posix()
    if not value or "\n" in value or "\r" in value or "\0" in value:
        raise PreservationError(f"{label} has an unsupported relative path: {value!r}")
    return value


def _walk_regular_files(directory: Path, root: Path) -> set[str]:
    directory = Path(directory).resolve()
    files: set[str] = set()
    try:
        entries = sorted(directory.rglob("*"))
    except OSError as exc:
        raise PreservationError(f"cannot enumerate queue directory {directory}: {exc}") from exc
    for entry in entries:
        try:
            info = entry.lstat()
        except OSError as exc:
            raise PreservationError(f"cannot inspect queue entry {entry}: {exc}") from exc
        if entry.is_symlink():
            raise PreservationError(f"queue tree contains a symlink: {entry}")
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise PreservationError(f"queue tree contains a non-regular entry: {entry}")
        files.add(_relative_file(entry, root, "queue file"))
    return files


def _stable_record(root: Path, relative: str) -> tuple[dict[str, Any], tuple[int, ...]]:
    path = root / relative
    before = _require_regular(path, "inventory file").lstat()
    identity_before = (
        before.st_dev,
        before.st_ino,
        before.st_mode,
        before.st_size,
        before.st_mtime_ns,
    )
    digest = sha256(path)
    after = _require_regular(path, "inventory file").lstat()
    identity_after = (
        after.st_dev,
        after.st_ino,
        after.st_mode,
        after.st_size,
        after.st_mtime_ns,
    )
    if identity_after != identity_before:
        raise PreservationError(f"inventory file changed while hashing: {path}")
    return (
        {
            "path": relative,
            "bytes": after.st_size,
            "mode": stat.S_IMODE(after.st_mode),
            "sha256": digest,
        },
        identity_after,
    )


def _require_identity(path: Path, expected: tuple[int, ...]) -> None:
    info = _require_regular(path, "inventory file").lstat()
    observed = (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns)
    if observed != expected:
        raise PreservationError(f"inventory file changed during the complete scan: {path}")


def _validate_queue_boundary(queue_dir: Path) -> dict[str, Any]:
    plan_path = _require_regular(queue_dir / "QUEUE_PLAN.json", "queue plan")
    state_path = _require_regular(queue_dir / "QUEUE_STATE.json", "queue state")
    screen_path = _require_regular(
        queue_dir / "work" / "full-control" / "SCREEN_COMPLETE.json",
        "screen completion",
    )
    plan = load_json(plan_path)
    state = load_json(state_path)
    if plan.get("schema_version") != 1 or state.get("schema_version") != 1:
        raise PreservationError("queue plan or state schema version is unsupported")
    if state.get("state") != "complete":
        raise PreservationError("queue state is not complete")
    if state.get("current_job") is not None:
        raise PreservationError("completed queue still has a current job")
    if state.get("message") != COMPLETE_MESSAGE:
        raise PreservationError("queue completion message is not authoritative")
    if state.get("queue_id") != plan.get("queue_id") or state.get("queue_id") != queue_dir.name:
        raise PreservationError("queue identity differs across directory, plan, and state")
    plan_digest = sha256(plan_path)
    if state.get("plan_sha256") != plan_digest:
        raise PreservationError("queue state plan digest is wrong")

    plan_jobs_raw = plan.get("jobs")
    state_jobs_raw = state.get("jobs")
    if not isinstance(plan_jobs_raw, list) or not isinstance(state_jobs_raw, list):
        raise PreservationError("queue jobs are missing")
    plan_jobs = {
        job.get("id"): job
        for job in plan_jobs_raw
        if isinstance(job, dict) and isinstance(job.get("id"), str)
    }
    state_jobs = {
        job.get("id"): job
        for job in state_jobs_raw
        if isinstance(job, dict) and isinstance(job.get("id"), str)
    }
    if set(plan_jobs) != EXPECTED_JOB_IDS or set(state_jobs) != EXPECTED_JOB_IDS:
        raise PreservationError("queue job set is not the exact recovery schedule")
    if len(plan_jobs) != len(plan_jobs_raw) or len(state_jobs) != len(state_jobs_raw):
        raise PreservationError("queue jobs are malformed or duplicated")
    for job_id in sorted(EXPECTED_JOB_IDS):
        job_state = state_jobs[job_id]
        if job_state.get("state") != "complete" or job_state.get("exit_code") != 0:
            raise PreservationError(f"queue job did not complete successfully: {job_id}")
        success_digest = _require_sha256(
            job_state.get("success_sha256"), f"queue job {job_id} success digest"
        )
        success = plan_jobs[job_id].get("success")
        if not isinstance(success, dict) or not isinstance(success.get("path"), str):
            raise PreservationError(f"queue job success path is missing: {job_id}")
        success_path_raw = Path(success["path"])
        if not success_path_raw.is_absolute():
            raise PreservationError(f"queue job success path is not absolute: {job_id}")
        success_path = _require_regular(
            success_path_raw, f"queue job {job_id} success"
        ).resolve()
        try:
            success_path.relative_to(queue_dir)
        except ValueError as exc:
            raise PreservationError(f"queue job success path escapes the queue: {job_id}") from exc
        if sha256(success_path) != success_digest:
            raise PreservationError(f"queue job success artifact drifted: {job_id}")
    full_success = Path(plan_jobs["full-control-rerun"]["success"]["path"]).resolve()
    if full_success != screen_path.resolve():
        raise PreservationError("full-control success path is not SCREEN_COMPLETE.json")
    return {
        "queue_id": state["queue_id"],
        "plan_sha256": plan_digest,
        "state_sha256": sha256(state_path),
        "screen_complete_sha256": sha256(screen_path),
    }


def _result_bindings(queue_dir: Path, recovery_root: Path) -> tuple[list[dict[str, Any]], set[str]]:
    work = queue_dir / "work" / "full-control"
    result_paths = sorted(work.glob("*.result.json"))
    if len(result_paths) != 3:
        raise PreservationError(f"expected exactly three recovery results, found {len(result_paths)}")
    bindings: list[dict[str, Any]] = []
    extras: set[str] = set()
    seeds: set[int] = set()
    checkpoints: set[str] = set()
    for result_path in result_paths:
        result = load_json(result_path)
        if result.get("schema_version") != 2:
            raise PreservationError(f"result schema version is unsupported: {result_path}")
        seed = result.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed in seeds:
            raise PreservationError(f"result seed is invalid or duplicated: {result_path}")
        seeds.add(seed)
        if result.get("trainer_complete") is not True or result.get("acceptance_pass") is not True:
            raise PreservationError(f"result is not accepted and complete: {result_path}")
        if result.get("acceptance_failures") not in ([], None):
            raise PreservationError(f"accepted result records failures: {result_path}")
        checkpoint_raw = result.get("checkpoint")
        log_raw = result.get("log")
        if not isinstance(checkpoint_raw, str) or not isinstance(log_raw, str):
            raise PreservationError(f"result paths are missing: {result_path}")
        if not Path(checkpoint_raw).is_absolute() or not Path(log_raw).is_absolute():
            raise PreservationError(f"result paths are not absolute: {result_path}")
        checkpoint = _require_regular(Path(checkpoint_raw), "result checkpoint").resolve()
        log = _require_regular(Path(log_raw), "result log").resolve()
        checkpoint_rel = _relative_file(checkpoint, recovery_root, "result checkpoint")
        log_rel = _relative_file(log, recovery_root, "result log")
        try:
            log.relative_to(work.resolve())
        except ValueError as exc:
            raise PreservationError(f"result log is outside full-control work: {log}") from exc
        if checkpoint_rel in checkpoints:
            raise PreservationError(f"result checkpoint is duplicated: {checkpoint}")
        checkpoints.add(checkpoint_rel)
        expected_checkpoint_sha = _require_sha256(
            result.get("checkpoint_sha256"), "result checkpoint digest"
        )
        if result.get("checkpoint_bytes") != checkpoint.stat().st_size:
            raise PreservationError(f"result checkpoint byte count is wrong: {checkpoint}")
        expected_log_sha = _require_sha256(result.get("log_sha256"), "result log digest")

        run_manifest = _require_regular(checkpoint.parent / "RUN_MANIFEST.json", "run manifest")
        run_manifest_rel = _relative_file(run_manifest, recovery_root, "run manifest")
        expected_manifest_sha = _require_sha256(
            result.get("run_manifest_sha256"), "result run-manifest digest"
        )
        run_dir_sidecar = _require_regular(
            Path(str(log) + ".run_dir"), "run-directory sidecar"
        )
        try:
            recorded_run_dir = Path(run_dir_sidecar.read_text(encoding="utf-8").strip()).resolve()
        except (OSError, UnicodeError) as exc:
            raise PreservationError(f"cannot read run-directory sidecar: {exc}") from exc
        if recorded_run_dir != checkpoint.parent.resolve():
            raise PreservationError("result checkpoint differs from its run-directory sidecar")

        result_rel = _relative_file(result_path, recovery_root, "result")
        extras.update((checkpoint_rel, run_manifest_rel))
        bindings.append(
            {
                "seed": seed,
                "result": result_rel,
                "result_sha256": sha256(result_path),
                "log": log_rel,
                "log_sha256": expected_log_sha,
                "checkpoint": checkpoint_rel,
                "checkpoint_bytes": checkpoint.stat().st_size,
                "checkpoint_sha256": expected_checkpoint_sha,
                "run_manifest": run_manifest_rel,
                "run_manifest_sha256": expected_manifest_sha,
            }
        )
    if seeds != EXPECTED_SEEDS:
        raise PreservationError(f"result seed set is wrong: {sorted(seeds)}")
    bindings.sort(key=lambda item: item["seed"])
    return bindings, extras


def build_inventory(
    *,
    recovery_root: Path,
    queue_dir: Path,
    bbtv_selection: Path,
    extra_paths: Iterable[Path] = (),
) -> dict[str, Any]:
    recovery_root = Path(recovery_root).resolve()
    if not recovery_root.is_dir():
        raise PreservationError(f"recovery root is not a directory: {recovery_root}")
    queue_dir = Path(queue_dir).resolve()
    if not queue_dir.is_dir():
        raise PreservationError(f"queue directory is not a directory: {queue_dir}")
    try:
        queue_rel = queue_dir.relative_to(recovery_root).as_posix()
    except ValueError as exc:
        raise PreservationError("queue directory escapes the recovery root") from exc

    boundary = _validate_queue_boundary(queue_dir)
    bindings, bound_files = _result_bindings(queue_dir, recovery_root)
    queue_files = _walk_regular_files(queue_dir, recovery_root)
    selection_rel = _relative_file(bbtv_selection, recovery_root, "BBTV selection")

    selected = set(queue_files) | bound_files | {selection_rel}
    for path in extra_paths:
        selected.add(_relative_file(path, recovery_root, "extra evidence"))
    scanned = [_stable_record(recovery_root, relative) for relative in sorted(selected)]
    records = [record for record, _identity in scanned]
    identities = {
        record["path"]: identity for (record, identity) in scanned
    }
    by_path = {record["path"]: record for record in records}
    for binding in bindings:
        for path_key, digest_key in (
            ("log", "log_sha256"),
            ("checkpoint", "checkpoint_sha256"),
            ("run_manifest", "run_manifest_sha256"),
        ):
            record = by_path[binding[path_key]]
            if record["sha256"] != binding[digest_key]:
                raise PreservationError(
                    f"result-bound {path_key} digest is wrong: {binding[path_key]}"
                )
        if by_path[binding["checkpoint"]]["bytes"] != binding["checkpoint_bytes"]:
            raise PreservationError(
                f"result-bound checkpoint byte count is wrong: {binding['checkpoint']}"
            )
    if _walk_regular_files(queue_dir, recovery_root) != queue_files:
        raise PreservationError("queue file set changed while hashing")
    if _validate_queue_boundary(queue_dir) != boundary:
        raise PreservationError("queue boundary changed during the complete scan")
    final_bindings, final_bound_files = _result_bindings(queue_dir, recovery_root)
    if final_bindings != bindings or final_bound_files != bound_files:
        raise PreservationError("result bindings changed during the complete scan")
    selection = load_json(Path(bbtv_selection))
    selection_step = selection.get("step")
    if (
        selection.get("seed") != 44
        or isinstance(selection_step, bool)
        or not isinstance(selection_step, int)
        or selection_step <= 0
    ):
        raise PreservationError("final BBTV selection is not a seed-44 checkpoint")
    for relative, identity in identities.items():
        _require_identity(recovery_root / relative, identity)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND,
        "generated_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source_recovery_root": str(recovery_root),
        "queue_dir": queue_rel,
        "queue_id": boundary["queue_id"],
        "queue_plan_sha256": boundary["plan_sha256"],
        "queue_state_sha256": boundary["state_sha256"],
        "screen_complete_sha256": boundary["screen_complete_sha256"],
        "bbtv_selection": selection_rel,
        "bbtv_selection_sha256": by_path[selection_rel]["sha256"],
        "result_bindings": bindings,
        "files": records,
        "file_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "inventory_sha256": canonical_hash(records),
    }
    _validate_manifest(payload)
    return payload


def _validate_manifest(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    required_top = {
        "schema_version",
        "kind",
        "generated_utc",
        "source_recovery_root",
        "queue_dir",
        "queue_id",
        "queue_plan_sha256",
        "queue_state_sha256",
        "screen_complete_sha256",
        "bbtv_selection",
        "bbtv_selection_sha256",
        "result_bindings",
        "files",
        "file_count",
        "total_bytes",
        "inventory_sha256",
    }
    if set(manifest) != required_top:
        raise PreservationError("preservation manifest top-level schema is wrong")
    if manifest.get("schema_version") != SCHEMA_VERSION or manifest.get("kind") != KIND:
        raise PreservationError("preservation manifest identity is wrong")
    if not isinstance(manifest.get("generated_utc"), str):
        raise PreservationError("preservation generation time is missing")
    source_root = manifest.get("source_recovery_root")
    if not isinstance(source_root, str) or not Path(source_root).is_absolute():
        raise PreservationError("preservation source recovery root is not absolute")
    queue_dir = manifest.get("queue_dir")
    queue_id = manifest.get("queue_id")
    if (
        not isinstance(queue_dir, str)
        or not queue_dir
        or queue_dir.startswith("/")
        or ".." in Path(queue_dir).parts
        or Path(queue_dir).as_posix() != queue_dir
        or not isinstance(queue_id, str)
        or Path(queue_dir).name != queue_id
    ):
        raise PreservationError("preservation queue identity is wrong")
    for key in (
        "queue_plan_sha256",
        "queue_state_sha256",
        "screen_complete_sha256",
        "bbtv_selection_sha256",
        "inventory_sha256",
    ):
        _require_sha256(manifest.get(key), key)
    records = manifest.get("files")
    if not isinstance(records, list) or not records:
        raise PreservationError("preservation manifest file list is missing")
    normalized: list[dict[str, Any]] = []
    paths: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "bytes", "mode", "sha256"}:
            raise PreservationError("preservation file record schema is wrong")
        path = record.get("path")
        if (
            not isinstance(path, str)
            or not path
            or path.startswith("/")
            or "\n" in path
            or "\r" in path
            or "\0" in path
            or Path(path).as_posix() != path
            or ".." in Path(path).parts
            or path in paths
        ):
            raise PreservationError(f"preservation relative path is invalid: {path!r}")
        paths.add(path)
        size = record.get("bytes")
        mode = record.get("mode")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise PreservationError(f"preservation byte count is invalid: {path}")
        if isinstance(mode, bool) or not isinstance(mode, int) or not 0 <= mode <= 0o7777:
            raise PreservationError(f"preservation mode is invalid: {path}")
        _require_sha256(record.get("sha256"), f"preservation digest for {path}")
        normalized.append(dict(record))
    if [record["path"] for record in normalized] != sorted(paths):
        raise PreservationError("preservation file records are not path-sorted")
    if manifest.get("file_count") != len(normalized):
        raise PreservationError("preservation file count is wrong")
    if manifest.get("total_bytes") != sum(record["bytes"] for record in normalized):
        raise PreservationError("preservation total byte count is wrong")
    if manifest.get("inventory_sha256") != canonical_hash(normalized):
        raise PreservationError("preservation inventory digest is wrong")
    by_path = {record["path"]: record for record in normalized}
    authoritative_paths = {
        "queue_plan_sha256": f"{queue_dir}/QUEUE_PLAN.json",
        "queue_state_sha256": f"{queue_dir}/QUEUE_STATE.json",
        "screen_complete_sha256": (
            f"{queue_dir}/work/full-control/SCREEN_COMPLETE.json"
        ),
        "bbtv_selection_sha256": manifest.get("bbtv_selection"),
    }
    for digest_key, path in authoritative_paths.items():
        if not isinstance(path, str) or path not in by_path:
            raise PreservationError(f"authoritative preservation path is missing: {path!r}")
        if by_path[path]["sha256"] != manifest[digest_key]:
            raise PreservationError(f"authoritative preservation digest differs: {path}")

    bindings = manifest.get("result_bindings")
    binding_keys = {
        "seed",
        "result",
        "result_sha256",
        "log",
        "log_sha256",
        "checkpoint",
        "checkpoint_bytes",
        "checkpoint_sha256",
        "run_manifest",
        "run_manifest_sha256",
    }
    if not isinstance(bindings, list) or len(bindings) != 3:
        raise PreservationError("preservation result bindings are incomplete")
    seeds: set[int] = set()
    for binding in bindings:
        if not isinstance(binding, dict) or set(binding) != binding_keys:
            raise PreservationError("preservation result-binding schema is wrong")
        seed = binding.get("seed")
        if isinstance(seed, bool) or not isinstance(seed, int) or seed in seeds:
            raise PreservationError("preservation result-binding seed is invalid")
        seeds.add(seed)
        for path_key, digest_key in (
            ("result", "result_sha256"),
            ("log", "log_sha256"),
            ("checkpoint", "checkpoint_sha256"),
            ("run_manifest", "run_manifest_sha256"),
        ):
            path = binding.get(path_key)
            if not isinstance(path, str) or path not in by_path:
                raise PreservationError(f"result-bound path is missing: {path!r}")
            _require_sha256(binding.get(digest_key), f"result-bound {path_key} digest")
            if by_path[path]["sha256"] != binding[digest_key]:
                raise PreservationError(f"result-bound digest differs: {path}")
        if by_path[binding["checkpoint"]]["bytes"] != binding.get("checkpoint_bytes"):
            raise PreservationError("result-bound checkpoint byte count differs")
    if seeds != EXPECTED_SEEDS:
        raise PreservationError("preservation result-binding seed set is wrong")
    if [binding["seed"] for binding in bindings] != sorted(EXPECTED_SEEDS):
        raise PreservationError("preservation result bindings are not seed-sorted")
    return normalized


def verify_copy(manifest: Mapping[str, Any], copy_root: Path) -> dict[str, Any]:
    records = _validate_manifest(manifest)
    copy_root = Path(copy_root).resolve()
    if not copy_root.is_dir():
        raise PreservationError(f"copy root is not a directory: {copy_root}")
    observed = _walk_regular_files(copy_root, copy_root)
    expected = {record["path"] for record in records}
    if observed != expected:
        missing = sorted(expected - observed)
        extra = sorted(observed - expected)
        raise PreservationError(f"copied file set differs; missing={missing}, extra={extra}")
    identities: dict[str, tuple[int, ...]] = {}
    for record in records:
        path = copy_root / record["path"]
        actual, identity = _stable_record(copy_root, record["path"])
        if actual != record:
            raise PreservationError(f"copied file identity differs: {path}")
        identities[record["path"]] = identity
    if _walk_regular_files(copy_root, copy_root) != expected:
        raise PreservationError("copied file set changed during verification")
    for relative, identity in identities.items():
        _require_identity(copy_root / relative, identity)
    return {
        "accepted": True,
        "file_count": len(records),
        "total_bytes": sum(record["bytes"] for record in records),
        "inventory_sha256": canonical_hash(records),
    }


def write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path = Path(path)
    if path.exists():
        raise PreservationError(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    plan = subparsers.add_parser("plan", help="build an inventory from stopped evidence")
    plan.add_argument("--recovery-root", required=True, type=Path)
    plan.add_argument("--queue-dir", required=True, type=Path)
    plan.add_argument("--bbtv-selection", required=True, type=Path)
    plan.add_argument("--extra", action="append", default=[], type=Path)
    plan.add_argument("--output", required=True, type=Path)
    verify = subparsers.add_parser("verify", help="verify an exact copied file tree")
    verify.add_argument("manifest", type=Path)
    verify.add_argument("--copy-root", required=True, type=Path)
    emit = subparsers.add_parser("emit-files", help="emit NUL-delimited rsync paths")
    emit.add_argument("manifest", type=Path)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "plan":
        recovery_root = args.recovery_root.resolve()
        output = args.output.resolve()
        try:
            output.relative_to(recovery_root)
        except ValueError:
            pass
        else:
            raise PreservationError("inventory output must be outside the recovery root")
        payload = build_inventory(
            recovery_root=recovery_root,
            queue_dir=args.queue_dir,
            bbtv_selection=args.bbtv_selection,
            extra_paths=args.extra,
        )
        write_json_atomic(output, payload)
        print(json.dumps({
            "accepted": True,
            "output": str(output),
            "output_sha256": sha256(output),
            "file_count": payload["file_count"],
            "total_bytes": payload["total_bytes"],
            "inventory_sha256": payload["inventory_sha256"],
        }, sort_keys=True))
        return 0
    manifest = load_json(args.manifest)
    if args.command == "verify":
        print(json.dumps(verify_copy(manifest, args.copy_root), sort_keys=True))
        return 0
    if args.command == "emit-files":
        records = _validate_manifest(manifest)
        for record in records:
            sys.stdout.buffer.write(record["path"].encode("utf-8") + b"\0")
        return 0
    raise PreservationError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PreservationError as exc:
        print(f"recovery preservation failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
