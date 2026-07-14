#!/usr/bin/env python3
"""Freeze one fail-closed R0 overflow queue after the reviewed primary queue."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import experiment_queue
import freeze_vacation_queue
import run_frozen_reward_screen
import start_vacation_overflow


SCHEMA_VERSION = 1
SPEC_KEYS = {
    "schema_version",
    "queue_id",
    "root",
    "primary_plan",
    "overflow_warm",
    "pool",
    "nvidia_smi",
    "systemctl",
    "final_steps",
    "min_free_bytes",
    "min_free_inodes",
    "max_gpu_temperature_c",
}
REVIEWED_PRIMARY_QUEUE_ID = "vacation-r0-baseline-20260714-v1"
REVIEWED_PRIMARY_PLAN_SHA256 = (
    "4ee72e3c58f09786cdd3bbf78a772e8de2d9a93e21a8b065cf0c5976ecced270"
)
REVIEWED_OVERFLOW_ANCESTRY = {
    "name": "netblock",
    "bank": 2,
    "sha256": "9964cf4d4c9c2654157e898ff17327732e73c4c85a5883e7d311d8d3baade05e",
}
PRIMARY_ROUTE = "confirmation-rejected-baseline"
PRIMARY_JOB_IDS = ["final-main-control", "final-second-control"]


class OverflowFreezeError(ValueError):
    pass


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise OverflowFreezeError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise OverflowFreezeError(f"{label} must be a JSON object: {path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def absolute_file(value: Any, label: str, root: Path) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise OverflowFreezeError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OverflowFreezeError(f"{label} escapes audit root: {path}") from exc
    if not path.is_file():
        raise OverflowFreezeError(f"missing {label}: {path}")
    return path


def absolute_tree(value: Any, label: str, root: Path) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise OverflowFreezeError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise OverflowFreezeError(f"{label} escapes audit root: {path}") from exc
    if not path.is_dir():
        raise OverflowFreezeError(f"missing {label}: {path}")
    return path


def pin_for(plan: dict[str, Any], path: Path) -> dict[str, Any] | None:
    resolved = str(path.resolve())
    return next(
        (pin for pin in plan["pinned_files"] if pin.get("path") == resolved),
        None,
    )


def config_from_job(plan: dict[str, Any], job_id: str, root: Path) -> Path:
    job = next((job for job in plan["jobs"] if job.get("id") == job_id), None)
    if job is None:
        raise OverflowFreezeError(f"primary plan is missing {job_id}")
    args = experiment_queue.render_args(job["command"])
    expected_runner = root / "tools/run_frozen_reward_screen.py"
    if (
        len(args) != 4
        or Path(args[1]).resolve() != expected_runner.resolve()
        or args[2] != "--config"
    ):
        raise OverflowFreezeError(f"primary job {job_id} command drifted")
    config_path = Path(args[3]).resolve()
    if pin_for(plan, config_path) is None:
        raise OverflowFreezeError(f"primary job {job_id} config is not pinned")
    return config_path


def validate_primary_contract(
    primary_plan_path: Path,
    root: Path,
    pool: Path,
) -> tuple[dict[str, Any], dict[str, Any], str]:
    plan, plan_root, plan_sha = experiment_queue.validate_plan(primary_plan_path)
    if plan_root != root:
        raise OverflowFreezeError("primary plan uses another audit root")
    if plan.get("queue_id") != REVIEWED_PRIMARY_QUEUE_ID:
        raise OverflowFreezeError("primary plan queue ID is not reviewed")
    if plan_sha != REVIEWED_PRIMARY_PLAN_SHA256:
        raise OverflowFreezeError("primary plan SHA-256 is not reviewed")
    if [job.get("id") for job in plan["jobs"]] != PRIMARY_JOB_IDS:
        raise OverflowFreezeError("primary plan is not the reviewed two-job route")
    pin_error = experiment_queue.pinned_files_error(plan)
    if pin_error is not None:
        raise OverflowFreezeError(f"primary plan pin drift: {pin_error}")

    primary_dir = primary_plan_path.parent
    primary_spec_path = primary_dir / "VACATION_SPEC.json"
    authorization_path = primary_dir / "configs/BASELINE_AUTHORIZATION.json"
    for path, label in (
        (primary_spec_path, "primary spec"),
        (authorization_path, "primary authorization"),
    ):
        if not path.is_file() or pin_for(plan, path) is None:
            raise OverflowFreezeError(f"{label} is missing or unpinned")
    primary_spec = load_object(primary_spec_path, "primary vacation spec")
    authorization = load_object(authorization_path, "primary authorization")
    if (
        primary_spec.get("schema_version") != 2
        or primary_spec.get("queue_id") != REVIEWED_PRIMARY_QUEUE_ID
        or primary_spec.get("route") != PRIMARY_ROUTE
        or primary_spec.get("root") != str(root)
        or primary_spec.get("final_steps") != 12_000_000_000
        or primary_spec.get("pool") != str(pool)
        or primary_spec.get("anchor_config") is not None
        or primary_spec.get("main_learned_complete") is not None
    ):
        raise OverflowFreezeError("primary vacation spec is not the reviewed route")
    rejection = authorization.get("rejection")
    failures = rejection.get("failures") if isinstance(rejection, dict) else None
    if (
        authorization.get("schema_version") != 1
        or authorization.get("route") != PRIMARY_ROUTE
        or authorization.get("candidate_arm") != primary_spec.get("candidate_arm")
        or not isinstance(failures, list)
        or not failures
        or authorization.get("warning")
        != (
            "This proof authorizes only R0 baseline characterization. "
            "It does not select or promote a reward candidate."
        )
    ):
        raise OverflowFreezeError("primary rejection authorization is malformed")

    configs = []
    for job_id in PRIMARY_JOB_IDS:
        config_path = config_from_job(plan, job_id, root)
        try:
            config = run_frozen_reward_screen.validate_config(config_path)
        except (OSError, ValueError, run_frozen_reward_screen.FrozenScreenError) as exc:
            raise OverflowFreezeError(
                f"invalid primary screen config for {job_id}: {exc}"
            ) from exc
        if (
            config.get("profile") != "control-final"
            or config.get("candidate_arm") != "both"
            or config.get("steps") != 12_000_000_000
            or config.get("candidate_transfer") is not None
            or config.get("require_gate") is not False
            or config.get("pool") != freeze_vacation_queue.tree_record(pool)
        ):
            raise OverflowFreezeError(f"primary job {job_id} is not exact R0")
        configs.append(config)
    if configs[0]["warm"]["sha256"] != freeze_vacation_queue.sha256(
        Path(primary_spec["main_warm"])
    ):
        raise OverflowFreezeError("primary main warm differs from its spec")
    if (
        configs[1]["warm"]["sha256"]
        != freeze_vacation_queue.REVIEWED_SECOND_ANCESTRY["sha256"]
    ):
        raise OverflowFreezeError("primary second warm is not reviewed league9")
    return plan, authorization, plan_sha


def validate_overflow_ancestry(warm: Path, pool: Path) -> None:
    observed = freeze_vacation_queue.sha256(warm)
    if observed != REVIEWED_OVERFLOW_ANCESTRY["sha256"]:
        raise OverflowFreezeError("overflow warm is not the reviewed netblock ancestry")
    manifest = load_object(pool / "league_seeds.json", "static pool manifest")
    seeds = manifest.get("seeds")
    if not isinstance(seeds, list):
        raise OverflowFreezeError("static pool seed list is malformed")
    match = next(
        (
            seed
            for seed in seeds
            if isinstance(seed, dict)
            and seed.get("bank") == REVIEWED_OVERFLOW_ANCESTRY["bank"]
            and seed.get("name") == REVIEWED_OVERFLOW_ANCESTRY["name"]
        ),
        None,
    )
    if not isinstance(match, dict):
        raise OverflowFreezeError("static pool does not contain reviewed netblock bank")
    pool_warm = (pool / Path(str(match.get("file", ""))).name).resolve()
    if (
        pool_warm != warm
        or match.get("sha256") != observed
        or match.get("bytes") != warm.stat().st_size
    ):
        raise OverflowFreezeError("overflow warm differs from the pinned pool bank")


def validate_spec(path: Path) -> dict[str, Any]:
    spec = load_object(path, "vacation overflow spec")
    if set(spec) != SPEC_KEYS:
        raise OverflowFreezeError("overflow spec fields differ")
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise OverflowFreezeError("unsupported overflow spec schema")
    queue_id = spec.get("queue_id")
    if (
        not isinstance(queue_id, str)
        or freeze_vacation_queue.QUEUE_ID_PATTERN.fullmatch(queue_id) is None
        or queue_id == REVIEWED_PRIMARY_QUEUE_ID
    ):
        raise OverflowFreezeError("overflow queue_id is invalid")
    root_value = spec.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise OverflowFreezeError("root must be absolute")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise OverflowFreezeError(f"audit root is missing: {root}")
    primary_plan = absolute_file(spec.get("primary_plan"), "primary plan", root)
    pool = absolute_tree(spec.get("pool"), "static pool", root)
    overflow_warm = absolute_file(spec.get("overflow_warm"), "overflow warm", root)
    nvidia_value = spec.get("nvidia_smi")
    if not isinstance(nvidia_value, str) or not Path(nvidia_value).is_absolute():
        raise OverflowFreezeError("nvidia_smi must be an absolute path")
    nvidia_smi = Path(nvidia_value).expanduser().resolve()
    if not nvidia_smi.is_file():
        raise OverflowFreezeError(f"nvidia-smi is missing: {nvidia_smi}")
    systemctl_value = spec.get("systemctl")
    if not isinstance(systemctl_value, str) or not Path(systemctl_value).is_absolute():
        raise OverflowFreezeError("systemctl must be an absolute path")
    systemctl = Path(systemctl_value).expanduser().resolve()
    if not systemctl.is_file():
        raise OverflowFreezeError(f"systemctl is missing: {systemctl}")
    if spec.get("final_steps") != 12_000_000_000:
        raise OverflowFreezeError("overflow must use 12B x three-seed R0 budget")
    for key in ("min_free_bytes", "min_free_inodes"):
        value = spec.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise OverflowFreezeError(f"{key} must be a positive integer")
    thermal = spec.get("max_gpu_temperature_c")
    if (
        isinstance(thermal, bool)
        or not isinstance(thermal, (int, float))
        or not 80 <= thermal <= 91
    ):
        raise OverflowFreezeError("max_gpu_temperature_c must be in [80,91]")
    plan, authorization, plan_sha = validate_primary_contract(primary_plan, root, pool)
    validate_overflow_ancestry(overflow_warm, pool)
    primary_state = primary_plan.parent / "QUEUE_STATE.json"
    if primary_state.exists():
        state = load_object(primary_state, "primary queue state")
        if state.get("queue_id") != REVIEWED_PRIMARY_QUEUE_ID:
            raise OverflowFreezeError("primary state queue ID drifted")
        if state.get("plan_sha256") != plan_sha:
            raise OverflowFreezeError("primary state plan SHA-256 drifted")
        if state.get("state") == "halted":
            raise OverflowFreezeError("refusing overflow for a halted primary queue")
    queue_dir = root / "runs" / queue_id
    if (queue_dir / "QUEUE_STATE.json").exists():
        raise OverflowFreezeError("refusing overflow queue with existing state")
    return {
        **spec,
        "spec_path": path.resolve(),
        "root_path": root,
        "primary_plan_path": primary_plan,
        "primary_state_path": primary_state,
        "primary_plan_data": plan,
        "primary_plan_sha256": plan_sha,
        "primary_authorization": authorization,
        "overflow_warm_path": overflow_warm,
        "pool_path": pool,
        "nvidia_smi_path": nvidia_smi,
        "systemctl_path": systemctl,
        "queue_dir": queue_dir,
    }


def freeze(spec: dict[str, Any]) -> Path:
    root = spec["root_path"]
    queue_dir = spec["queue_dir"]
    config_dir = queue_dir / "configs"
    work_dir = queue_dir / "work"
    gate_dir = work_dir / "primary-completion"
    final_dir = work_dir / "final-third"
    logs_dir = queue_dir / "logs"
    for success in (
        gate_dir / "PRIMARY_COMPLETE.json",
        final_dir / "SCREEN_COMPLETE.json",
    ):
        if success.exists():
            raise OverflowFreezeError(
                f"refusing preexisting overflow success artifact: {success}"
            )
    config_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    completion_config_path = config_dir / "PRIMARY_COMPLETION_CONFIG.json"
    completion_config = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "primary_queue_id": REVIEWED_PRIMARY_QUEUE_ID,
        "primary_plan": freeze_vacation_queue.file_record(spec["primary_plan_path"]),
        "primary_state": str(spec["primary_state_path"]),
        "nvidia_smi": freeze_vacation_queue.file_record(spec["nvidia_smi_path"]),
    }
    screen_config_path = config_dir / "FINAL_THIRD_SCREEN_CONFIG.json"
    screen_config = freeze_vacation_queue.build_screen_config(
        root=root,
        profile="control-final",
        candidate="both",
        steps=spec["final_steps"],
        prefix=f"{spec['queue_id']}-final-third-control",
        out_dir=final_dir,
        warm=spec["overflow_warm_path"],
        pool=spec["pool_path"],
        transfer=None,
        require_gate=False,
    )
    for path, payload, label in (
        (completion_config_path, completion_config, "completion config"),
        (screen_config_path, screen_config, "screen config"),
    ):
        if path.exists() and load_object(path, label) != payload:
            raise OverflowFreezeError(f"existing {label} drift: {path}")
        if not path.exists():
            atomic_json(path, payload)

    primary_pins = spec["primary_plan_data"]["pinned_files"]
    pins_by_path = {pin["path"]: dict(pin) for pin in primary_pins}
    new_files = [
        root / "tools/validate_primary_queue_completion.py",
        root / "tools/start_vacation_overflow.py",
        completion_config_path,
        screen_config_path,
        spec["spec_path"],
        spec["primary_plan_path"],
        spec["overflow_warm_path"],
        spec["nvidia_smi_path"],
        spec["systemctl_path"],
    ]
    for file_path in new_files:
        resolved = file_path.resolve()
        pins_by_path.setdefault(
            str(resolved),
            freeze_vacation_queue.pin_file(
                resolved, f"vacation overflow input {resolved.name}"
            ),
        )
    pins = [pins_by_path[key] for key in sorted(pins_by_path)]
    pin_paths = [pin["path"] for pin in pins]

    python = (root / "vendor/PufferLib/.venv/bin/python").resolve()
    completion_validator = root / "tools/validate_primary_queue_completion.py"
    run_frozen = root / "tools/run_frozen_reward_screen.py"
    artifact_validator = root / "tools/validate_vacation_artifact.py"
    proof = gate_dir / "PRIMARY_COMPLETE.json"
    screen_complete = final_dir / "SCREEN_COMPLETE.json"

    def pinned(path: Path) -> dict[str, str]:
        return freeze_vacation_queue.typed_pinned(path)

    def literal(value: str) -> dict[str, str]:
        return freeze_vacation_queue.typed_literal(value)

    def mutable(path: Path) -> dict[str, str]:
        return freeze_vacation_queue.typed_mutable(path)

    jobs = [
        {
            "id": "primary-completion-gate",
            "command": [
                pinned(python),
                pinned(completion_validator),
                literal("--config"),
                pinned(completion_config_path),
                literal("--write-proof"),
                mutable(proof),
            ],
            "cwd": str(root),
            "log": str(logs_dir / "primary-completion-gate.log"),
            "success": {
                "path": str(proof),
                "validator": [
                    pinned(python),
                    pinned(completion_validator),
                    literal("--config"),
                    pinned(completion_config_path),
                    literal("--validate-proof"),
                    mutable(proof),
                ],
                "validator_timeout_seconds": 1800,
            },
            "env": {},
            "resume_safe": True,
            "max_runtime_seconds": 1800,
            "progress_not_required_reason": (
                "bounded primary completion validation under thirty minutes"
            ),
            "pinned_inputs": pin_paths,
            "mutable_paths": [str(gate_dir)],
        },
        {
            "id": "final-third-control",
            "command": [
                pinned(python),
                pinned(run_frozen),
                literal("--config"),
                pinned(screen_config_path),
            ],
            "cwd": str(root),
            "log": str(logs_dir / "final-third-control.log"),
            "success": {
                "path": str(screen_complete),
                "validator": [
                    pinned(python),
                    pinned(artifact_validator),
                    literal("--screen"),
                    pinned(screen_config_path),
                    mutable(screen_complete),
                ],
                "validator_timeout_seconds": 1800,
            },
            "env": {},
            "resume_safe": False,
            "max_runtime_seconds": 72 * 3600,
            "progress": {
                "path": str(final_dir / "SCREEN_STATUS.json"),
                "max_stale_seconds": 600,
            },
            "pinned_inputs": pin_paths,
            "mutable_paths": [str(final_dir)],
        },
    ]
    plan = {
        "schema_version": SCHEMA_VERSION,
        "queue_id": spec["queue_id"],
        "root": str(root),
        "min_free_bytes": spec["min_free_bytes"],
        "min_free_inodes": spec["min_free_inodes"],
        "poll_seconds": 30,
        "max_gpu_temperature_c": spec["max_gpu_temperature_c"],
        "base_env": {
            "HOME": str(Path.home()),
            "PATH": ("/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"),
            "PYTHONUNBUFFERED": "1",
            "TZ": "America/Los_Angeles",
        },
        "pinned_files": pins,
        "jobs": jobs,
    }
    plan_path = queue_dir / "QUEUE_PLAN.json"
    if plan_path.exists() and load_object(plan_path, "overflow plan") != plan:
        raise OverflowFreezeError("existing overflow plan differs")
    if not plan_path.exists():
        atomic_json(plan_path, plan)
    validated, validated_root, digest = experiment_queue.validate_plan(plan_path)
    if validated != plan or validated_root != root:
        raise OverflowFreezeError("overflow plan changed during validation")
    print(f"VACATION R0 OVERFLOW FROZEN: {plan_path}")
    print(f"queue_plan_sha256={digest}")
    print("jobs=2 reward=both ancestry=netblock seeds=42,43,44")
    watch_config_path = queue_dir / "OVERFLOW_WATCH.json"
    watch_config = {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "primary_queue_id": REVIEWED_PRIMARY_QUEUE_ID,
        "overflow_queue_id": spec["queue_id"],
        "completion_config": freeze_vacation_queue.file_record(completion_config_path),
        "overflow_plan": freeze_vacation_queue.file_record(plan_path),
        "overflow_state": str(queue_dir / "QUEUE_STATE.json"),
        "systemctl": freeze_vacation_queue.file_record(spec["systemctl_path"]),
        "starter": freeze_vacation_queue.file_record(
            root / "tools/start_vacation_overflow.py"
        ),
    }
    watch_config["config_sha256"] = start_vacation_overflow.config_sha256(watch_config)
    if (
        watch_config_path.exists()
        and load_object(watch_config_path, "overflow watch config") != watch_config
    ):
        raise OverflowFreezeError("existing overflow watch config differs")
    if not watch_config_path.exists():
        atomic_json(watch_config_path, watch_config)
    return plan_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec", type=Path)
    args = parser.parse_args(argv)
    try:
        spec = validate_spec(args.spec.expanduser().resolve())
        freeze(spec)
        return 0
    except (
        OSError,
        OverflowFreezeError,
        experiment_queue.QueueError,
        run_frozen_reward_screen.FrozenScreenError,
        ValueError,
    ) as exc:
        print(f"vacation overflow freeze failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
