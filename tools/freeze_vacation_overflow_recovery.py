#!/usr/bin/env python3
"""Freeze a fresh full R0 rerun after the exact overflow terminal halt."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import experiment_queue
import freeze_vacation_queue
import run_frozen_reward_screen
import validate_vacation_overflow_recovery as recovery_validator


SCHEMA_VERSION = 1
RECOVERY_QUEUE_ID = "vacation-r0-overflow-recovery-20260719-v1"
REVIEWED_WARM_SHA256 = recovery_validator.NETBLOCK_SHA256
REVIEWED_WARM_BYTES = 16_066_560
SPEC_KEYS = {
    "schema_version",
    "queue_id",
    "root",
    "prior_plan",
    "prior_state",
    "prior_screen_manifest",
    "prior_screen_status",
    "prior_result",
    "prior_checkpoint",
    "recovery_warm",
    "pool",
    "nvidia_smi",
    "final_steps",
    "min_free_bytes",
    "min_free_inodes",
    "max_gpu_temperature_c",
}


class RecoveryFreezeError(ValueError):
    pass


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RecoveryFreezeError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecoveryFreezeError(f"{label} must be a JSON object: {path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def absolute_file(value: Any, label: str) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise RecoveryFreezeError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    if not path.is_file():
        raise RecoveryFreezeError(f"missing {label}: {path}")
    return path


def under_root_file(value: Any, label: str, root: Path) -> Path:
    path = absolute_file(value, label)
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RecoveryFreezeError(f"{label} escapes recovery root: {path}") from exc
    return path


def under_root_tree(value: Any, label: str, root: Path) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise RecoveryFreezeError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RecoveryFreezeError(f"{label} escapes recovery root: {path}") from exc
    if not path.is_dir():
        raise RecoveryFreezeError(f"missing {label}: {path}")
    return path


def preflight_payload(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "recovery_root": str(spec["root_path"]),
        "prior_queue_id": recovery_validator.PRIOR_QUEUE_ID,
        "prior_plan": freeze_vacation_queue.file_record(spec["prior_paths"]["plan"]),
        "prior_state": freeze_vacation_queue.file_record(spec["prior_paths"]["state"]),
        "prior_screen_manifest": freeze_vacation_queue.file_record(
            spec["prior_paths"]["manifest"]
        ),
        "prior_screen_status": freeze_vacation_queue.file_record(
            spec["prior_paths"]["status"]
        ),
        "prior_result": freeze_vacation_queue.file_record(
            spec["prior_paths"]["result"]
        ),
        "prior_checkpoint": freeze_vacation_queue.file_record(
            spec["prior_paths"]["checkpoint"]
        ),
        "corrected_launcher": freeze_vacation_queue.file_record(
            spec["root_path"] / "tools/run_reward_screen.sh"
        ),
        "corrected_game_stats": freeze_vacation_queue.file_record(
            spec["root_path"] / "tools/game_stats.py"
        ),
        "warning": recovery_validator.WARNING,
    }


def validate_overflow_ancestry(warm: Path, pool: Path) -> None:
    if warm.stat().st_size != REVIEWED_WARM_BYTES:
        raise RecoveryFreezeError("recovery warm has the wrong architecture size")
    observed = freeze_vacation_queue.sha256(warm)
    if observed != REVIEWED_WARM_SHA256:
        raise RecoveryFreezeError("recovery warm is not the reviewed netblock ancestry")
    manifest = load_object(pool / "league_seeds.json", "static pool manifest")
    seeds = manifest.get("seeds")
    if not isinstance(seeds, list):
        raise RecoveryFreezeError("static pool seed list is malformed")
    match = next(
        (
            seed
            for seed in seeds
            if isinstance(seed, dict)
            and seed.get("bank") == 2
            and seed.get("name") == "netblock"
        ),
        None,
    )
    if not isinstance(match, dict):
        raise RecoveryFreezeError("static pool lacks the reviewed netblock bank")
    pool_warm = (pool / Path(str(match.get("file", ""))).name).resolve()
    if (
        pool_warm != warm
        or match.get("sha256") != observed
        or match.get("bytes") != warm.stat().st_size
    ):
        raise RecoveryFreezeError("recovery warm differs from the static pool bank")


def validate_spec(path: Path) -> dict[str, Any]:
    spec = load_object(path, "vacation overflow recovery spec")
    if set(spec) != SPEC_KEYS:
        raise RecoveryFreezeError("recovery spec fields differ")
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise RecoveryFreezeError("unsupported recovery spec schema")
    if spec.get("queue_id") != RECOVERY_QUEUE_ID:
        raise RecoveryFreezeError("recovery queue ID is not reviewed")
    root_value = spec.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise RecoveryFreezeError("root must be absolute")
    root = Path(root_value).expanduser().resolve()
    if not root.is_dir():
        raise RecoveryFreezeError(f"recovery root is missing: {root}")
    prior_paths = {
        "plan": absolute_file(spec.get("prior_plan"), "prior plan"),
        "state": absolute_file(spec.get("prior_state"), "prior state"),
        "manifest": absolute_file(
            spec.get("prior_screen_manifest"), "prior screen manifest"
        ),
        "status": absolute_file(spec.get("prior_screen_status"), "prior screen status"),
        "result": absolute_file(spec.get("prior_result"), "prior result"),
        "checkpoint": absolute_file(spec.get("prior_checkpoint"), "prior checkpoint"),
    }
    warm = under_root_file(spec.get("recovery_warm"), "recovery warm", root)
    pool = under_root_tree(spec.get("pool"), "static pool", root)
    nvidia = absolute_file(spec.get("nvidia_smi"), "nvidia-smi")
    if spec.get("final_steps") != 12_000_000_000:
        raise RecoveryFreezeError("recovery must use the full 12B three-seed budget")
    for key in ("min_free_bytes", "min_free_inodes"):
        value = spec.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise RecoveryFreezeError(f"{key} must be a positive integer")
    thermal = spec.get("max_gpu_temperature_c")
    if (
        isinstance(thermal, bool)
        or not isinstance(thermal, (int, float))
        or not 80 <= thermal <= 91
    ):
        raise RecoveryFreezeError("max_gpu_temperature_c must be in [80,91]")
    validate_overflow_ancestry(warm, pool)
    queue_dir = root / "runs" / RECOVERY_QUEUE_ID
    if (queue_dir / "QUEUE_STATE.json").exists():
        raise RecoveryFreezeError("refusing recovery queue with existing state")
    validated = {
        **spec,
        "spec_path": path.resolve(),
        "root_path": root,
        "queue_dir": queue_dir,
        "prior_paths": prior_paths,
        "recovery_warm_path": warm,
        "pool_path": pool,
        "nvidia_smi_path": nvidia,
    }
    payload = preflight_payload(validated)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix="recovery-preflight-",
        dir=root,
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
    try:
        preflight = recovery_validator.validate_config(temporary.resolve())
        report = recovery_validator.recovery_report(preflight)
    finally:
        temporary.unlink(missing_ok=True)
    if (
        report.get("result_reuse_authorized") is not False
        or report.get("in_place_restart_authorized") is not False
        or report.get("reward_promotion_authorized") is not False
    ):
        raise RecoveryFreezeError("terminal evidence granted broader authority")
    return {**validated, "preflight_config": payload, "preflight_report": report}


def runtime_source_paths(
    spec: dict[str, Any], preflight_config: Path, screen_config: Path
) -> list[Path]:
    root = spec["root_path"]
    python = (root / "vendor/PufferLib/.venv/bin/python").resolve()
    module_matches = sorted((root / "vendor/PufferLib/pufferlib").glob("_C*.so"))
    if len(module_matches) != 1:
        raise RecoveryFreezeError(
            f"expected one compiled Puffer module, found {len(module_matches)}"
        )
    sources = [
        python,
        Path("/bin/bash"),
        root / "vendor/PufferLib/.venv/bin/puffer",
        root / "tools/experiment_queue.py",
        root / "tools/run_frozen_reward_screen.py",
        root / "tools/run_reward_screen.sh",
        root / "tools/run_reward_ablation.sh",
        root / "tools/analyze_reward_candidate_transfer.py",
        root / "tools/analyze_reward_screen.py",
        root / "tools/validate_vacation_artifact.py",
        root / "tools/validate_vacation_overflow_recovery.py",
        root / "tools/reward_manifest.py",
        root / "tools/install_puffer_env.sh",
        root / "tools/cpu_cap.sh",
        root / "tools/game_stats.py",
        root / "tools/contact_bot_stats.py",
        root / "tools/eval_vs_contact_bot.sh",
        root / "training/convert_checkpoint.py",
        root / "training/systemd/experiment-recovery-queue@.service",
        root / "puffer/config/bloodbowl.ini",
        root / "puffer/config/rewards/r0_full.json",
        root / "vendor/PufferLib/config/bloodbowl.ini",
        root / "vendor/PufferLib/config/default.ini",
        root / "vendor/PufferLib/pufferlib/__init__.py",
        root / "vendor/PufferLib/pufferlib/muon.py",
        root / "vendor/PufferLib/pufferlib/models.py",
        root / "vendor/PufferLib/pufferlib/pufferl.py",
        root / "vendor/PufferLib/pufferlib/selfplay.py",
        root / "vendor/PufferLib/pufferlib/torch_pufferl.py",
        root / "vendor/PufferLib/src/pufferlib.cu",
        root / "vendor/PufferLib/src/bindings.cu",
        root / "vendor/PufferLib/src/vecenv.h",
        module_matches[0],
        preflight_config,
        screen_config,
        spec["spec_path"],
        spec["recovery_warm_path"],
        spec["nvidia_smi_path"],
        *spec["prior_paths"].values(),
    ]
    sources.extend(sorted((root / "training").glob("puffer*.patch")))
    return sources


def runtime_tree_sources(spec: dict[str, Any]) -> list[tuple[Path, str]]:
    root = spec["root_path"]
    return [
        (spec["pool_path"], "static replay/league pool"),
        (root / "vendor/PufferLib/config", "Puffer configuration closure"),
        (root / "vendor/PufferLib/ocean/bloodbowl", "installed Blood Bowl source"),
    ]


def freeze(spec: dict[str, Any]) -> Path:
    root = spec["root_path"]
    queue_dir = spec["queue_dir"]
    state_path = queue_dir / "QUEUE_STATE.json"
    if state_path.exists():
        raise RecoveryFreezeError("refusing recovery queue with existing state")
    config_dir = queue_dir / "configs"
    logs_dir = queue_dir / "logs"
    proof_dir = queue_dir / "work/terminal-evidence"
    screen_dir = queue_dir / "work/full-control"
    proof = proof_dir / "RECOVERY_AUTHORIZED.json"
    screen_complete = screen_dir / "SCREEN_COMPLETE.json"
    for artifact in (proof, screen_complete):
        if artifact.exists():
            raise RecoveryFreezeError(
                f"refusing preexisting recovery artifact: {artifact}"
            )
    config_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    preflight_config_path = config_dir / "TERMINAL_EVIDENCE_PREFLIGHT.json"
    preflight = spec.get("preflight_config") or preflight_payload(spec)
    screen_config_path = config_dir / "FULL_CONTROL_SCREEN_CONFIG.json"
    screen_config = freeze_vacation_queue.build_screen_config(
        root=root,
        profile="control-final",
        candidate="both",
        steps=spec["final_steps"],
        prefix=f"{spec['queue_id']}-full-control",
        out_dir=screen_dir,
        warm=spec["recovery_warm_path"],
        pool=spec["pool_path"],
        transfer=None,
        require_gate=False,
    )
    for path, payload, label in (
        (preflight_config_path, preflight, "preflight config"),
        (screen_config_path, screen_config, "screen config"),
    ):
        if path.exists() and load_object(path, label) != payload:
            raise RecoveryFreezeError(f"existing {label} differs: {path}")
        if not path.exists():
            atomic_json(path, payload)

    pins_by_path: dict[str, dict[str, Any]] = {}
    sources = runtime_source_paths(spec, preflight_config_path, screen_config_path)
    sources.extend((preflight_config_path, screen_config_path))
    for source in sources:
        resolved = source.expanduser().resolve()
        pins_by_path.setdefault(
            str(resolved),
            freeze_vacation_queue.pin_file(
                resolved, f"vacation recovery input {resolved.name}"
            ),
        )
    for tree, role in runtime_tree_sources(spec):
        resolved = tree.expanduser().resolve()
        pins_by_path.setdefault(
            str(resolved), freeze_vacation_queue.pin_tree(resolved, role)
        )
    pins = [pins_by_path[key] for key in sorted(pins_by_path)]
    all_pin_paths = [pin["path"] for pin in pins]

    python = (root / "vendor/PufferLib/.venv/bin/python").resolve()
    recovery_tool = root / "tools/validate_vacation_overflow_recovery.py"
    run_frozen = root / "tools/run_frozen_reward_screen.py"
    artifact_validator = root / "tools/validate_vacation_artifact.py"

    def pinned(path: Path) -> dict[str, str]:
        return freeze_vacation_queue.typed_pinned(path)

    def literal(value: str) -> dict[str, str]:
        return freeze_vacation_queue.typed_literal(value)

    def mutable(path: Path) -> dict[str, str]:
        return freeze_vacation_queue.typed_mutable(path)

    jobs = [
        {
            "id": "terminal-evidence-preflight",
            "command": [
                pinned(python),
                pinned(recovery_tool),
                literal("--config"),
                pinned(preflight_config_path),
                literal("--write-proof"),
                mutable(proof),
            ],
            "cwd": str(root),
            "log": str(logs_dir / "terminal-evidence-preflight.log"),
            "success": {
                "path": str(proof),
                "validator": [
                    pinned(python),
                    pinned(recovery_tool),
                    literal("--config"),
                    pinned(preflight_config_path),
                    literal("--validate-proof"),
                    mutable(proof),
                ],
                "validator_timeout_seconds": 1800,
            },
            "env": {},
            "resume_safe": True,
            "max_runtime_seconds": 1800,
            "progress_not_required_reason": (
                "bounded terminal-evidence validation under thirty minutes"
            ),
            "pinned_inputs": all_pin_paths,
            "mutable_paths": [str(proof_dir)],
        },
        {
            "id": "full-control-rerun",
            "command": [
                pinned(python),
                pinned(run_frozen),
                literal("--config"),
                pinned(screen_config_path),
            ],
            "cwd": str(root),
            "log": str(logs_dir / "full-control-rerun.log"),
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
                "path": str(screen_dir / "SCREEN_STATUS.json"),
                "max_stale_seconds": 600,
            },
            "pinned_inputs": all_pin_paths,
            "mutable_paths": [str(screen_dir)],
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
    if plan_path.exists() and load_object(plan_path, "recovery plan") != plan:
        raise RecoveryFreezeError("existing recovery plan differs")
    if not plan_path.exists():
        atomic_json(plan_path, plan)
    validated, validated_root, digest = experiment_queue.validate_plan(plan_path)
    if validated != plan or validated_root != root:
        raise RecoveryFreezeError("recovery plan changed during validation")
    print(f"VACATION R0 RECOVERY FROZEN: {plan_path}")
    print(f"queue_plan_sha256={digest}")
    print("jobs=2 reward=both ancestry=netblock seeds=42,43,44 fresh=true")
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
        RecoveryFreezeError,
        recovery_validator.RecoveryEvidenceError,
        experiment_queue.QueueError,
        freeze_vacation_queue.FreezeError,
        run_frozen_reward_screen.FrozenScreenError,
        ValueError,
    ) as exc:
        print(f"vacation overflow recovery freeze failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
