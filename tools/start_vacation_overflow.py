#!/usr/bin/env python3
"""Idempotently start a frozen overflow queue after its primary queue succeeds."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import experiment_queue
import validate_primary_queue_completion


SCHEMA_VERSION = 1
CONFIG_KEYS = {
    "schema_version",
    "root",
    "primary_queue_id",
    "overflow_queue_id",
    "completion_config",
    "overflow_plan",
    "overflow_state",
    "systemctl",
    "starter",
    "config_sha256",
}
FILE_KEYS = {"path", "bytes", "sha256"}


class StartError(ValueError):
    pass


def config_sha256(config: dict[str, Any]) -> str:
    canonical = json.dumps(
        {key: value for key, value in config.items() if key != "config_sha256"},
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StartError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise StartError(f"{label} must be a JSON object: {path}")
    return value


def under_root(value: Any, root: Path, label: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise StartError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise StartError(f"{label} escapes audit root: {path}") from exc
    return path


def validate_file(record: Any, label: str) -> Path:
    try:
        return validate_primary_queue_completion.validate_file(record, label)
    except validate_primary_queue_completion.CompletionError as exc:
        raise StartError(str(exc)) from exc


def validate_config(path: Path) -> dict[str, Any]:
    config = load_object(path, "overflow watch config")
    if set(config) != CONFIG_KEYS:
        raise StartError("overflow watch config fields differ")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise StartError("unsupported overflow watch config schema")
    if config.get("config_sha256") != config_sha256(config):
        raise StartError("overflow watch config identity drifted")
    root_value = config.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise StartError("root must be absolute")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise StartError(f"audit root is missing: {root}")
    for key in ("primary_queue_id", "overflow_queue_id"):
        if not isinstance(config.get(key), str) or not config[key]:
            raise StartError(f"{key} must be nonempty")
    if config["primary_queue_id"] == config["overflow_queue_id"]:
        raise StartError("primary and overflow queue IDs must differ")
    completion_config = validate_file(
        config.get("completion_config"), "completion config"
    )
    overflow_plan = validate_file(config.get("overflow_plan"), "overflow plan")
    systemctl = validate_file(config.get("systemctl"), "systemctl")
    starter = validate_file(config.get("starter"), "overflow starter")
    if starter != Path(__file__).resolve():
        raise StartError("watch config names another overflow starter")
    for candidate, label in (
        (completion_config, "completion config"),
        (overflow_plan, "overflow plan"),
    ):
        under_root(str(candidate), root, label)
    overflow_state = under_root(config.get("overflow_state"), root, "overflow state")
    if overflow_state != overflow_plan.parent / "QUEUE_STATE.json":
        raise StartError("overflow state is not beside overflow plan")
    plan, plan_root, plan_sha = experiment_queue.validate_plan(overflow_plan)
    if plan_root != root:
        raise StartError("overflow plan uses another audit root")
    if plan.get("queue_id") != config["overflow_queue_id"]:
        raise StartError("overflow plan queue ID differs from watch config")
    return {
        **config,
        "root_path": root,
        "completion_config_path": completion_config,
        "overflow_plan_path": overflow_plan,
        "overflow_state_path": overflow_state,
        "systemctl_path": systemctl,
        "plan": plan,
        "plan_sha256": plan_sha,
    }


def service_state(systemctl: Path, unit: str) -> str:
    completed = subprocess.run(
        [str(systemctl), "--user", "is-active", unit],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=15,
    )
    value = completed.stdout.strip()
    active_states = {"active", "activating", "deactivating"}
    inactive_states = {"inactive", "failed"}
    if value not in active_states | inactive_states or completed.returncode not in {
        0,
        3,
    }:
        raise StartError(
            f"cannot classify {unit}: state={value!r} "
            f"exit={completed.returncode}: {completed.stderr.strip()}"
        )
    return value


def existing_overflow_state(config: dict[str, Any]) -> str | None:
    path = config["overflow_state_path"]
    if not path.exists():
        return None
    state = load_object(path, "overflow queue state")
    if state.get("queue_id") != config["overflow_queue_id"]:
        raise StartError("overflow state queue ID drifted")
    if state.get("plan_sha256") != config["plan_sha256"]:
        raise StartError("overflow state plan SHA-256 drifted")
    value = state.get("state")
    if value not in {"pending", "running", "complete", "halted"}:
        raise StartError(f"overflow state is malformed: {value!r}")
    return value


def start_if_ready(config: dict[str, Any]) -> str:
    overflow_unit = f"experiment-queue@{config['overflow_queue_id']}.service"
    primary_unit = f"experiment-queue@{config['primary_queue_id']}.service"
    existing = existing_overflow_state(config)
    if existing is not None:
        return f"overflow already has terminally owned state={existing}; no start"
    overflow_service = service_state(config["systemctl_path"], overflow_unit)
    if overflow_service in {"active", "activating", "deactivating"}:
        return f"overflow service is already {overflow_service}; no start"
    if overflow_service == "failed":
        raise StartError("overflow service is failed; refusing timer relaunch")
    primary_service = service_state(config["systemctl_path"], primary_unit)
    if primary_service in {"active", "activating", "deactivating"}:
        return f"primary service is still {primary_service}; waiting"
    if primary_service != "inactive":
        raise StartError(f"primary service is {primary_service}; refusing overflow")
    completion_config = validate_primary_queue_completion.validate_config(
        config["completion_config_path"]
    )
    validate_primary_queue_completion.completion_report(completion_config)
    pin_error = experiment_queue.pinned_files_error(config["plan"])
    if pin_error is not None:
        raise StartError(f"overflow plan pin drift: {pin_error}")
    if existing_overflow_state(config) is not None:
        return "overflow state appeared during preflight; no start"
    if service_state(config["systemctl_path"], primary_unit) != "inactive":
        return "primary service changed state during preflight; waiting"
    if service_state(config["systemctl_path"], overflow_unit) != "inactive":
        return "overflow service changed state during preflight; no start"
    # The completion report already required an empty GPU compute-process set.
    # Recheck immediately before start to close the validation/start window.
    pids = validate_primary_queue_completion.gpu_compute_pids(
        completion_config["nvidia_smi_path"]
    )
    if pids:
        return "GPU became busy during preflight; waiting"
    if existing_overflow_state(config) is not None:
        return "overflow state appeared immediately before start; no start"
    if experiment_queue.sha256(config["overflow_plan_path"]) != config["plan_sha256"]:
        raise StartError("overflow plan changed during start preflight")
    completed = subprocess.run(
        [str(config["systemctl_path"]), "--user", "start", overflow_unit],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    if completed.returncode != 0:
        raise StartError(
            "failed to start overflow service: "
            f"{completed.stderr.strip() or completed.stdout.strip()}"
        )
    state_after = service_state(config["systemctl_path"], overflow_unit)
    if state_after not in {"active", "activating"}:
        existing_after = existing_overflow_state(config)
        raise StartError(
            "overflow service did not remain active after start: "
            f"service={state_after}, state={existing_after}"
        )
    return f"started {overflow_unit}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        config = validate_config(args.config.expanduser().resolve())
        print(start_if_ready(config))
        return 0
    except validate_primary_queue_completion.PrimaryNotReady as exc:
        print(f"primary queue is not ready; waiting: {exc}")
        return 0
    except (
        OSError,
        StartError,
        experiment_queue.QueueError,
        validate_primary_queue_completion.CompletionError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        print(f"vacation overflow start failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
