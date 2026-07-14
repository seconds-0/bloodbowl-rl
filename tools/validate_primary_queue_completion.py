#!/usr/bin/env python3
"""Prove that the exact primary vacation queue completed without evidence drift."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import experiment_queue


SCHEMA_VERSION = 1
CONFIG_KEYS = {
    "schema_version",
    "root",
    "primary_queue_id",
    "primary_plan",
    "primary_state",
    "nvidia_smi",
}
FILE_KEYS = {"path", "bytes", "sha256"}
PRIMARY_JOB_IDS = ["final-main-control", "final-second-control"]


class CompletionError(ValueError):
    pass


class PrimaryNotReady(CompletionError):
    pass


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompletionError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise CompletionError(f"{label} must be a JSON object: {path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def under_root(value: Any, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise CompletionError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise CompletionError(f"{label} escapes audit root: {path}") from exc
    return path


def validate_file(record: Any, label: str) -> Path:
    if not isinstance(record, dict) or set(record) != FILE_KEYS:
        raise CompletionError(f"{label} must contain path/bytes/sha256")
    value = record.get("path")
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise CompletionError(f"{label} path must be absolute")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise CompletionError(f"missing {label}: {path}")
    size = record.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise CompletionError(f"{label} bytes must be positive")
    if path.stat().st_size != size:
        raise CompletionError(f"{label} size drift: {path}")
    expected = record.get("sha256")
    if (
        not isinstance(expected, str)
        or len(expected) != 64
        or any(char not in "0123456789abcdef" for char in expected)
    ):
        raise CompletionError(f"{label} SHA-256 is invalid")
    observed = sha256(path)
    if observed != expected:
        raise CompletionError(
            f"{label} SHA-256 drift: {observed} != {expected}: {path}"
        )
    return path


def validate_config(path: Path) -> dict[str, Any]:
    config = load_object(path, "primary-completion config")
    if set(config) != CONFIG_KEYS:
        raise CompletionError("primary-completion config fields differ")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise CompletionError("unsupported primary-completion config schema")
    root_value = config.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise CompletionError("root must be absolute")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise CompletionError(f"audit root is missing: {root}")
    queue_id = config.get("primary_queue_id")
    if not isinstance(queue_id, str) or not queue_id:
        raise CompletionError("primary_queue_id must be nonempty")
    plan_path = validate_file(config.get("primary_plan"), "primary plan")
    under_root(str(plan_path), root, "primary plan")
    state_path = under_root(config.get("primary_state"), root, "primary state")
    if state_path != plan_path.parent / "QUEUE_STATE.json":
        raise CompletionError("primary state is not beside the primary plan")
    nvidia_smi = validate_file(config.get("nvidia_smi"), "nvidia-smi")
    plan, plan_root, plan_sha = experiment_queue.validate_plan(plan_path)
    if plan_root != root:
        raise CompletionError("primary plan uses another audit root")
    if plan.get("queue_id") != queue_id:
        raise CompletionError("primary plan queue_id differs from config")
    if [job.get("id") for job in plan["jobs"]] != PRIMARY_JOB_IDS:
        raise CompletionError("primary plan is not the exact two-job R0 queue")
    return {
        **config,
        "root_path": root,
        "plan_path": plan_path,
        "state_path": state_path,
        "nvidia_smi_path": nvidia_smi,
        "plan": plan,
        "plan_sha256": plan_sha,
    }


def gpu_compute_pids(nvidia_smi: Path) -> list[int]:
    completed = subprocess.run(
        [
            str(nvidia_smi),
            "--query-compute-apps=pid",
            "--format=csv,noheader,nounits",
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=15,
    )
    if completed.returncode != 0:
        raise CompletionError(
            "nvidia-smi compute-process query failed: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    pids: list[int] = []
    for line in completed.stdout.splitlines():
        value = line.strip()
        if not value or value in {"[Not Found]", "N/A"}:
            continue
        try:
            pid = int(value)
        except ValueError as exc:
            raise CompletionError(
                f"nvidia-smi returned a malformed compute PID: {value!r}"
            ) from exc
        if pid <= 0:
            raise CompletionError(f"nvidia-smi returned an invalid PID: {pid}")
        pids.append(pid)
    return sorted(set(pids))


def completion_report(config: dict[str, Any]) -> dict[str, Any]:
    state_path = config["state_path"]
    if not state_path.exists():
        raise PrimaryNotReady("primary queue state does not exist yet")
    state = load_object(state_path, "primary queue state")
    state_value = state.get("state")
    if state_value in {"pending", "running"}:
        raise PrimaryNotReady(f"primary queue is still {state_value}")
    if state_value != "complete":
        raise CompletionError(
            f"primary queue terminal state is {state_value!r}, not complete"
        )
    if state.get("queue_id") != config["primary_queue_id"]:
        raise CompletionError("primary state queue_id differs from config")
    if state.get("plan_sha256") != config["plan_sha256"]:
        raise CompletionError("primary state plan SHA-256 differs from plan")
    if state.get("current_job") is not None:
        raise CompletionError("complete primary state still names a current job")
    jobs = state.get("jobs")
    if not isinstance(jobs, list) or len(jobs) != len(PRIMARY_JOB_IDS):
        raise CompletionError("primary state job count differs from plan")
    records: list[dict[str, Any]] = []
    for expected_id, job, job_state in zip(
        PRIMARY_JOB_IDS, config["plan"]["jobs"], jobs
    ):
        if job.get("id") != expected_id or job_state.get("id") != expected_id:
            raise CompletionError("primary job order differs from reviewed plan")
        if job_state.get("state") != "complete":
            raise CompletionError(f"primary job {expected_id} is not complete")
        success_path = Path(job["success"]["path"]).expanduser().resolve()
        if not success_path.is_file():
            raise CompletionError(
                f"primary job {expected_id} success artifact is missing"
            )
        success_sha = sha256(success_path)
        if job_state.get("success_sha256") != success_sha:
            raise CompletionError(
                f"primary job {expected_id} recorded success SHA-256 drifted"
            )
        records.append(
            {
                "id": expected_id,
                "success": str(success_path),
                "success_sha256": success_sha,
            }
        )
    pin_error = experiment_queue.pinned_files_error(config["plan"])
    if pin_error is not None:
        raise CompletionError(f"primary pinned evidence drifted: {pin_error}")
    evidence_error = experiment_queue.completed_evidence_error(
        config["plan"],
        state,
        config["root_path"],
        minimum_free_bytes=int(config["plan"]["min_free_bytes"]),
        minimum_free_inodes=int(config["plan"]["min_free_inodes"]),
        maximum_temperature=float(config["plan"]["max_gpu_temperature_c"]),
        poll_seconds=float(config["plan"]["poll_seconds"]),
    )
    if evidence_error is not None:
        raise CompletionError(
            f"primary completed evidence failed revalidation: {evidence_error}"
        )
    compute_pids = gpu_compute_pids(config["nvidia_smi_path"])
    if compute_pids:
        raise PrimaryNotReady(
            "GPU still has compute processes after primary completion: "
            + ",".join(str(pid) for pid in compute_pids)
        )
    return {
        "schema_version": SCHEMA_VERSION,
        "primary_queue_id": config["primary_queue_id"],
        "primary_plan": str(config["plan_path"]),
        "primary_plan_sha256": config["plan_sha256"],
        "primary_state": str(state_path),
        "primary_state_sha256": sha256(state_path),
        "jobs": records,
        "gpu_compute_pids": [],
        "warning": (
            "This proof authorizes only the separately frozen R0 overflow "
            "queue. It does not select or promote a reward."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write-proof", type=Path)
    mode.add_argument("--validate-proof", type=Path)
    args = parser.parse_args(argv)
    try:
        config = validate_config(args.config.expanduser().resolve())
        report = completion_report(config)
        if args.write_proof is not None:
            proof = under_root(
                str(args.write_proof.expanduser().resolve()),
                config["root_path"],
                "completion proof",
            )
            atomic_json(proof, report)
        elif args.validate_proof is not None:
            proof = under_root(
                str(args.validate_proof.expanduser().resolve()),
                config["root_path"],
                "completion proof",
            )
            if load_object(proof, "primary completion proof") != report:
                raise CompletionError("primary completion proof differs from reality")
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0
    except PrimaryNotReady as exc:
        print(f"primary queue not ready: {exc}", file=sys.stderr)
        return 3
    except (
        OSError,
        CompletionError,
        experiment_queue.QueueError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"primary completion validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
