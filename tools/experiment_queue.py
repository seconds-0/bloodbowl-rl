#!/usr/bin/env python3
"""Run an explicit, immutable experiment queue with fail-closed recovery.

The queue never invents a follow-up experiment. It executes command arrays from
a hash-pinned JSON plan, validates each declared success artifact, and records
all state atomically. A previously running job is retried only when its plan
explicitly says ``resume_safe: true``; otherwise an interruption halts the queue.
"""

from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


class QueueError(ValueError):
    pass


PLAN_KEYS = {
    "schema_version", "queue_id", "root", "min_free_bytes", "poll_seconds",
    "max_gpu_temperature_c", "base_env", "pinned_files", "jobs",
}
JOB_KEYS = {
    "id", "command", "cwd", "log", "success", "env", "resume_safe",
    "max_runtime_seconds", "progress", "progress_not_required_reason",
    "pinned_inputs",
}
SUCCESS_KEYS = {
    "path", "sha256", "validator", "validator_timeout_seconds",
}
PROGRESS_KEYS = {"path", "max_stale_seconds"}
PIN_KEYS = {"path", "bytes", "sha256", "role"}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueError(f"invalid {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise QueueError(f"{label} must be a JSON object: {path}")
    return value


def _absolute(value: Any, label: str, root: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise QueueError(f"{label} must be a nonempty absolute path")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise QueueError(f"{label} must be absolute: {path}")
    resolved = path.resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise QueueError(f"{label} escapes queue root {root}: {resolved}") from exc
    return resolved


def _unknown(mapping: dict[str, Any], allowed: set[str], label: str) -> None:
    unexpected = sorted(set(mapping) - allowed)
    if unexpected:
        raise QueueError(f"unknown {label} fields: {', '.join(unexpected)}")


def validate_plan(path: Path) -> tuple[dict[str, Any], Path, str]:
    try:
        raw = path.read_bytes()
        plan = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise QueueError(f"invalid queue plan {path}: {exc}") from exc
    if not isinstance(plan, dict):
        raise QueueError(f"queue plan must be a JSON object: {path}")
    plan_sha = hashlib.sha256(raw).hexdigest()
    _unknown(plan, PLAN_KEYS, "queue plan")
    if plan.get("schema_version") != 1:
        raise QueueError("queue plan schema_version must be 1")
    queue_id = plan.get("queue_id")
    if not isinstance(queue_id, str) or not queue_id:
        raise QueueError("queue_id must be a nonempty string")
    root_value = plan.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise QueueError("root must be an absolute path")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise QueueError(f"queue root does not exist: {root}")
    minimum = plan.get("min_free_bytes")
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
        raise QueueError("min_free_bytes must be a positive integer")
    poll = plan.get("poll_seconds")
    if (isinstance(poll, bool) or not isinstance(poll, (int, float)) or
            not 0 < poll <= 60):
        raise QueueError("poll_seconds must be in (0, 60]")
    maximum_temperature = plan.get("max_gpu_temperature_c")
    if maximum_temperature is not None and (
        isinstance(maximum_temperature, bool)
        or not isinstance(maximum_temperature, (int, float))
        or not 1 <= maximum_temperature <= 120
    ):
        raise QueueError("max_gpu_temperature_c must be in 1..120")
    base_env = plan.get("base_env")
    if (not isinstance(base_env, dict) or
            not all(isinstance(key, str) and key and isinstance(value, str)
                    for key, value in base_env.items())):
        raise QueueError("base_env must map nonempty strings to strings")
    pinned_files = plan.get("pinned_files")
    if not isinstance(pinned_files, list) or not pinned_files:
        raise QueueError("pinned_files must be a nonempty array")
    pinned_paths: set[str] = set()
    for index, pin in enumerate(pinned_files, 1):
        if not isinstance(pin, dict):
            raise QueueError(f"pinned file {index} must be an object")
        _unknown(pin, PIN_KEYS, f"pinned file {index}")
        pin_path = pin.get("path")
        if not isinstance(pin_path, str) or not Path(pin_path).is_absolute():
            raise QueueError(f"pinned file {index} path must be absolute")
        resolved_pin = str(Path(pin_path).expanduser().resolve())
        if resolved_pin in pinned_paths:
            raise QueueError(f"duplicate pinned file path: {resolved_pin}")
        pinned_paths.add(resolved_pin)
        size = pin.get("bytes")
        if isinstance(size, bool) or not isinstance(size, int) or size < 0:
            raise QueueError(f"pinned file {index} bytes must be nonnegative")
        expected = pin.get("sha256")
        if (not isinstance(expected, str) or len(expected) != 64 or
                any(char not in "0123456789abcdef" for char in expected)):
            raise QueueError(f"pinned file {index} sha256 is invalid")
        if not isinstance(pin.get("role"), str) or not pin["role"]:
            raise QueueError(f"pinned file {index} role must be nonempty")
    jobs = plan.get("jobs")
    if not isinstance(jobs, list) or not jobs:
        raise QueueError("jobs must be a nonempty array")
    seen: set[str] = set()
    for index, job in enumerate(jobs, 1):
        if not isinstance(job, dict):
            raise QueueError(f"job {index} must be an object")
        _unknown(job, JOB_KEYS, f"job {index}")
        job_id = job.get("id")
        if not isinstance(job_id, str) or not job_id or job_id in seen:
            raise QueueError(f"job {index} has an invalid or duplicate id")
        seen.add(job_id)
        command = job.get("command")
        if (not isinstance(command, list) or not command or
                not all(isinstance(item, str) and item for item in command)):
            raise QueueError(f"job {job_id} command must be nonempty strings")
        _absolute(job.get("cwd"), f"job {job_id} cwd", root)
        _absolute(job.get("log"), f"job {job_id} log", root)
        success = job.get("success")
        if not isinstance(success, dict):
            raise QueueError(f"job {job_id} success must be an object")
        _unknown(success, SUCCESS_KEYS, f"job {job_id} success")
        _absolute(success.get("path"), f"job {job_id} success path", root)
        expected_sha = success.get("sha256")
        if (expected_sha is not None and
                (not isinstance(expected_sha, str) or len(expected_sha) != 64 or
                 any(char not in "0123456789abcdef" for char in expected_sha))):
            raise QueueError(f"job {job_id} success sha256 is invalid")
        validator = success.get("validator")
        if (not isinstance(validator, list) or not validator or
                not all(isinstance(item, str) and item for item in validator)):
            raise QueueError(f"job {job_id} validator must be nonempty strings")
        validator_timeout = success.get("validator_timeout_seconds")
        if (isinstance(validator_timeout, bool) or
                not isinstance(validator_timeout, (int, float)) or
                validator_timeout <= 0):
            raise QueueError(
                f"job {job_id} validator_timeout_seconds must be positive")
        env = job.get("env", {})
        if (not isinstance(env, dict) or
                not all(isinstance(k, str) and isinstance(v, str)
                        for k, v in env.items())):
            raise QueueError(f"job {job_id} env must map strings to strings")
        job_pins = job.get("pinned_inputs")
        if (not isinstance(job_pins, list) or not job_pins or
                not all(isinstance(value, str) and Path(value).is_absolute()
                        for value in job_pins)):
            raise QueueError(
                f"job {job_id} pinned_inputs must be nonempty absolute paths")
        resolved_job_pins = {
            str(Path(value).expanduser().resolve()) for value in job_pins
        }
        if len(resolved_job_pins) != len(job_pins):
            raise QueueError(f"job {job_id} pinned_inputs contains duplicates")
        if not resolved_job_pins <= pinned_paths:
            missing_pins = sorted(resolved_job_pins - pinned_paths)
            raise QueueError(
                f"job {job_id} references undeclared pins: {missing_pins}")
        resume_safe = job.get("resume_safe")
        if not isinstance(resume_safe, bool):
            raise QueueError(f"job {job_id} resume_safe must be boolean")
        max_runtime = job.get("max_runtime_seconds")
        if (
            isinstance(max_runtime, bool)
            or not isinstance(max_runtime, (int, float))
            or max_runtime < 2 * poll
        ):
            raise QueueError(
                f"job {job_id} max_runtime_seconds must be at least two polls"
            )
        progress = job.get("progress")
        no_progress_reason = job.get("progress_not_required_reason")
        if (progress is None) == (no_progress_reason is None):
            raise QueueError(
                f"job {job_id} must declare exactly one of progress or "
                "progress_not_required_reason")
        if no_progress_reason is not None and (
            not isinstance(no_progress_reason, str) or not no_progress_reason.strip()
        ):
            raise QueueError(
                f"job {job_id} progress_not_required_reason must be nonempty")
        if progress is not None:
            if not isinstance(progress, dict):
                raise QueueError(f"job {job_id} progress must be an object")
            _unknown(progress, PROGRESS_KEYS, f"job {job_id} progress")
            _absolute(progress.get("path"), f"job {job_id} progress path", root)
            stale = progress.get("max_stale_seconds")
            if (isinstance(stale, bool) or not isinstance(stale, (int, float)) or
                    stale < 2 * poll):
                raise QueueError(
                    f"job {job_id} max_stale_seconds must be at least two polls")
        for executable, label in (
            (command[0], "command executable"),
            (validator[0], "validator executable"),
        ):
            if not Path(executable).is_absolute():
                raise QueueError(f"job {job_id} {label} must be absolute")
            resolved_executable = str(Path(executable).expanduser().resolve())
            if resolved_executable not in pinned_paths:
                raise QueueError(
                    f"job {job_id} {label} is not pinned: {resolved_executable}")
            if resolved_executable not in resolved_job_pins:
                raise QueueError(
                    f"job {job_id} {label} is not in pinned_inputs: "
                    f"{resolved_executable}")
        referenced_values = [*command, *validator, *env.values()]
        mutable_paths = {
            str(_absolute(job["log"], f"job {job_id} log", root)),
            str(_absolute(success["path"], f"job {job_id} success path", root)),
        }
        if progress is not None:
            mutable_paths.add(str(_absolute(
                progress["path"], f"job {job_id} progress path", root)))
        for value in referenced_values:
            candidate = Path(value).expanduser()
            if candidate.is_absolute() and candidate.is_file():
                resolved_candidate = str(candidate.resolve())
                if resolved_candidate in mutable_paths:
                    continue
                if resolved_candidate not in resolved_job_pins:
                    raise QueueError(
                        f"job {job_id} file argument is not in pinned_inputs: "
                        f"{resolved_candidate}")
    return plan, root, plan_sha


def pinned_files_error(plan: dict[str, Any]) -> str | None:
    for pin in plan["pinned_files"]:
        path = Path(pin["path"]).expanduser().resolve()
        if not path.is_file():
            return f"pinned {pin['role']} is missing: {path}"
        observed_size = path.stat().st_size
        if observed_size != pin["bytes"]:
            return (
                f"pinned {pin['role']} size drift: "
                f"{observed_size} != {pin['bytes']}: {path}"
            )
        observed_sha = sha256(path)
        if observed_sha != pin["sha256"]:
            return (
                f"pinned {pin['role']} SHA-256 drift: "
                f"{observed_sha} != {pin['sha256']}: {path}"
            )
    return None


def gpu_temperature() -> float:
    """Return the hottest NVIDIA GPU temperature, failing closed."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise QueueError(f"NVIDIA temperature query failed: {exc}") from exc
    if result.returncode != 0:
        raise QueueError(
            "NVIDIA temperature query exited "
            f"{result.returncode}: {result.stdout.strip()[-1000:]}"
        )
    try:
        temperatures = [
            float(line.strip())
            for line in result.stdout.splitlines()
            if line.strip()
        ]
    except ValueError as exc:
        raise QueueError(
            f"NVIDIA temperature query was not numeric: {result.stdout!r}"
        ) from exc
    if not temperatures:
        raise QueueError("NVIDIA temperature query returned no GPUs")
    return max(temperatures)


def success_error(
    job: dict[str, Any], root: Path, base_env: dict[str, str],
) -> str | None:
    success = job["success"]
    path = _absolute(success["path"], f"job {job['id']} success path", root)
    if not path.is_file():
        return f"success artifact is missing: {path}"
    expected = success.get("sha256")
    if expected is not None:
        observed = sha256(path)
        if observed != expected:
            return f"success SHA-256 mismatch: {observed} != {expected}"
    validator = success.get("validator")
    if validator:
        timeout = float(success["validator_timeout_seconds"])
        try:
            result = subprocess.run(
                validator,
                cwd=_absolute(job["cwd"], f"job {job['id']} cwd", root),
                env={**base_env, **job.get("env", {})},
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return f"validator timed out after {timeout:g}s"
        if result.returncode != 0:
            output = result.stdout.strip()[-2000:]
            return f"validator exited {result.returncode}: {output}"
        if expected is not None:
            observed_after = sha256(path)
            if observed_after != expected:
                return (
                    "validator mutated success artifact: "
                    f"{observed_after} != {expected}"
                )
    return None


def new_state(plan: dict[str, Any], plan_sha: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "queue_id": plan["queue_id"],
        "plan_sha256": plan_sha,
        "state": "pending",
        "message": "queue has not started",
        "created_utc": utc_now(),
        "updated_utc": utc_now(),
        "jobs": [
            {"id": job["id"], "state": "pending"}
            for job in plan["jobs"]
        ],
    }


def publish(
    state_path: Path, payload: dict[str, Any], **updates: Any
) -> None:
    payload.update(updates)
    payload["updated_utc"] = utc_now()
    atomic_json(state_path, payload)


def halt(state_path: Path, state: dict[str, Any], message: str) -> int:
    publish(state_path, state, state="halted", message=message)
    return 0


def _terminate_group(process: subprocess.Popen[Any]) -> None:
    with contextlib.suppress(ProcessLookupError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)


def monitor_process(
    process: subprocess.Popen[Any],
    *,
    root: Path,
    job: dict[str, Any],
    minimum_free_bytes: int,
    poll_seconds: float,
    maximum_temperature: float | None,
) -> str | None:
    """Monitor one process and terminate its group when a guard fails."""
    started_monotonic = time.monotonic()
    progress_signature: tuple[int, int, int] | None = None
    progress_changed_monotonic = started_monotonic
    hot_polls = 0
    while process.poll() is None:
        try:
            free = shutil.disk_usage(root).free
            if free < minimum_free_bytes:
                reason = (
                    f"disk guard tripped during {job['id']}: "
                    f"{free} < {minimum_free_bytes}"
                )
                _terminate_group(process)
                return reason
            elapsed = time.monotonic() - started_monotonic
            maximum_runtime = job.get("max_runtime_seconds")
            if (
                maximum_runtime is not None
                and elapsed > float(maximum_runtime)
            ):
                reason = (
                    f"runtime guard tripped during {job['id']}: "
                    f"{elapsed:.0f}s > {maximum_runtime}s"
                )
                _terminate_group(process)
                return reason
            if maximum_temperature is not None:
                observed_temperature = gpu_temperature()
                if observed_temperature > maximum_temperature:
                    hot_polls += 1
                else:
                    hot_polls = 0
                if hot_polls >= 3:
                    reason = (
                        f"thermal guard tripped during {job['id']}: "
                        f"{observed_temperature:.0f}C > "
                        f"{maximum_temperature}C for {hot_polls} polls"
                    )
                    _terminate_group(process)
                    return reason
            progress = job.get("progress")
            if progress:
                progress_path = _absolute(
                    progress["path"],
                    f"job {job['id']} progress path",
                    root,
                )
                if progress_path.exists():
                    if not progress_path.is_file():
                        raise QueueError(
                            f"progress artifact is not a regular file: {progress_path}")
                    stat = progress_path.stat()
                    observed_signature = (
                        stat.st_ino, stat.st_size, stat.st_mtime_ns)
                    if progress_signature is None:
                        progress_signature = observed_signature
                        progress_changed_monotonic = time.monotonic()
                    elif observed_signature != progress_signature:
                        progress_signature = observed_signature
                        progress_changed_monotonic = time.monotonic()
                    age = time.monotonic() - progress_changed_monotonic
                else:
                    age = elapsed
                if age > float(progress["max_stale_seconds"]):
                    presence = "stale" if progress_path.exists() else "absent"
                    reason = (
                        f"progress guard tripped during {job['id']}: "
                        f"{progress_path} {presence} for {age:.0f}s"
                    )
                    _terminate_group(process)
                    return reason
        except (OSError, QueueError, ValueError) as exc:
            _terminate_group(process)
            return f"monitor failed closed during {job['id']}: {exc}"
        time.sleep(poll_seconds)
    return None


def run_queue(plan_path: str | Path, state_path: str | Path) -> int:
    plan_path = Path(plan_path).expanduser().resolve()
    state_path = Path(state_path).expanduser().resolve()
    plan, root, plan_sha = validate_plan(plan_path)
    for path, label in ((plan_path, "plan path"), (state_path, "state path")):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise QueueError(f"{label} escapes queue root {root}: {path}") from exc
    lock_path = state_path.with_suffix(state_path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise QueueError(f"another queue runner holds {lock_path}") from exc

        if state_path.exists():
            state = load_object(state_path, "queue state")
            if state.get("plan_sha256") != plan_sha:
                return halt(
                    state_path, state,
                    "plan SHA-256 changed after queue state was created",
                )
            if state.get("queue_id") != plan["queue_id"]:
                return halt(state_path, state, "queue_id changed")
            if state.get("state") in ("complete", "halted"):
                return 0
        else:
            state = new_state(plan, plan_sha)
            atomic_json(state_path, state)

        if len(state.get("jobs", [])) != len(plan["jobs"]):
            return halt(state_path, state, "state job count differs from plan")

        pin_error = pinned_files_error(plan)
        if pin_error is not None:
            return halt(state_path, state, pin_error)
        publish(state_path, state, state="running", message="queue running")
        poll_seconds = float(plan.get("poll_seconds", 30))
        maximum_temperature = plan.get("max_gpu_temperature_c")
        if maximum_temperature is not None:
            observed_temperature = gpu_temperature()
            if observed_temperature > float(maximum_temperature):
                return halt(
                    state_path,
                    state,
                    "GPU temperature preflight failed: "
                    f"{observed_temperature:.0f}C > {maximum_temperature}C",
                )
        for index, job in enumerate(plan["jobs"]):
            job_state = state["jobs"][index]
            if job_state.get("id") != job["id"]:
                return halt(state_path, state, "state job order differs from plan")

            if sha256(plan_path) != plan_sha:
                return halt(state_path, state, "queue plan changed during execution")
            pin_error = pinned_files_error(plan)
            if pin_error is not None:
                return halt(state_path, state, pin_error)

            prior = job_state.get("state")
            if prior in ("failed", "halted"):
                return halt(
                    state_path, state,
                    f"job {job['id']} has terminal prior state {prior}",
                )
            if prior in ("launching", "running") and not job["resume_safe"]:
                return halt(
                    state_path, state,
                    f"job {job['id']} was interrupted and is not resume-safe",
                )

            artifact_error = success_error(job, root, plan["base_env"])
            if artifact_error is None:
                if sha256(plan_path) != plan_sha:
                    return halt(
                        state_path, state,
                        "queue plan changed during artifact validation",
                    )
                pin_error = pinned_files_error(plan)
                if pin_error is not None:
                    return halt(state_path, state, pin_error)
                job_state.update({
                    "state": "complete",
                    "recovered_from_artifact": True,
                    "completed_utc": job_state.get("completed_utc", utc_now()),
                })
                publish(
                    state_path, state,
                    message=f"validated existing success for {job['id']}",
                )
                continue

            free = shutil.disk_usage(root).free
            minimum = int(plan["min_free_bytes"])
            if free < minimum:
                return halt(
                    state_path, state,
                    f"disk preflight failed before {job['id']}: {free} < {minimum}",
                )

            log_path = _absolute(job["log"], f"job {job['id']} log", root)
            log_path.parent.mkdir(parents=True, exist_ok=True)
            cwd = _absolute(job["cwd"], f"job {job['id']} cwd", root)
            env = {**plan["base_env"], **job.get("env", {})}
            with log_path.open("a", encoding="utf-8") as log:
                log.write(
                    f"\nQUEUE JOB START {utc_now()} id={job['id']} "
                    f"plan_sha256={plan_sha}\n"
                )
                log.flush()
                job_state.update({
                    "state": "launching",
                    "launching_utc": utc_now(),
                    "recovered_from_artifact": False,
                })
                publish(
                    state_path, state,
                    message=f"launching job {job['id']}",
                    current_job=job["id"],
                )
                process: subprocess.Popen[Any] | None = None
                previous_handlers = {
                    signum: signal.getsignal(signum)
                    for signum in (signal.SIGINT, signal.SIGTERM)
                }

                def interrupt_handler(signum: int, _frame: Any) -> None:
                    raise KeyboardInterrupt(f"received signal {signum}")

                for signum in previous_handlers:
                    signal.signal(signum, interrupt_handler)
                try:
                    process = subprocess.Popen(
                        job["command"], cwd=cwd, env=env,
                        stdout=log, stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                    job_state.update({
                        "state": "running",
                        "pid": process.pid,
                        "started_utc": utc_now(),
                    })
                    publish(
                        state_path, state,
                        message=f"running job {job['id']}",
                        current_job=job["id"],
                    )
                    interrupted_reason = monitor_process(
                        process,
                        root=root,
                        job=job,
                        minimum_free_bytes=minimum,
                        poll_seconds=poll_seconds,
                        maximum_temperature=(
                            float(maximum_temperature)
                            if maximum_temperature is not None
                            else None
                        ),
                    )
                    exit_code = process.wait()
                except KeyboardInterrupt as exc:
                    if process is not None and process.poll() is None:
                        _terminate_group(process)
                    job_state["state"] = "halted"
                    return halt(
                        state_path, state,
                        f"queue interrupted during {job['id']}: {exc}",
                    )
                finally:
                    for signum, handler in previous_handlers.items():
                        signal.signal(signum, handler)

            job_state["exit_code"] = exit_code
            job_state["ended_utc"] = utc_now()
            if interrupted_reason is not None:
                job_state["state"] = "halted"
                return halt(state_path, state, interrupted_reason)
            if exit_code != 0:
                job_state["state"] = "failed"
                return halt(
                    state_path, state,
                    f"job {job['id']} exited {exit_code}; later jobs were not run",
                )
            if sha256(plan_path) != plan_sha:
                job_state["state"] = "failed"
                return halt(
                    state_path, state, "queue plan changed while job was running")
            pin_error = pinned_files_error(plan)
            if pin_error is not None:
                job_state["state"] = "failed"
                return halt(state_path, state, pin_error)
            artifact_error = success_error(job, root, plan["base_env"])
            if artifact_error is not None:
                job_state["state"] = "failed"
                return halt(
                    state_path, state,
                    f"job {job['id']} success validation failed: {artifact_error}",
                )
            if sha256(plan_path) != plan_sha:
                job_state["state"] = "failed"
                return halt(
                    state_path, state,
                    "queue plan changed during success validation",
                )
            pin_error = pinned_files_error(plan)
            if pin_error is not None:
                job_state["state"] = "failed"
                return halt(state_path, state, pin_error)
            job_state.update({"state": "complete", "completed_utc": utc_now()})
            publish(
                state_path, state,
                message=f"job {job['id']} completed and validated",
            )

        publish(
            state_path, state,
            state="complete", message="all queued jobs completed and validated",
            current_job=None, completed_utc=utc_now(),
        )
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        return run_queue(args.plan, args.state)
    except (OSError, QueueError, ValueError) as exc:
        print(f"experiment queue failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
