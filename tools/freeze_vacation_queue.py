#!/usr/bin/env python3
"""Freeze the reviewed six-day reward queue from accepted predeparture evidence.

The builder does no candidate selection.  ``candidate_arm`` must already be
confirmed by the completed main-lineage self-play, scripted, and learned-anchor
artifacts supplied in the spec.  It creates literal configs for one second-
ancestry confirmation, its two transfer strata, a two-lineage gate, and matched
three-seed long final screens.  It then emits and validates the closed typed
``QUEUE_PLAN.json`` consumed by ``experiment_queue.py``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import analyze_reward_candidate_transfer
import analyze_reward_screen
import experiment_queue
import run_reward_learned_transfer


SCHEMA_VERSION = 1
SPEC_KEYS = {
    "schema_version",
    "queue_id",
    "root",
    "candidate_arm",
    "main_warm",
    "second_warm",
    "pool",
    "anchor_config",
    "main_screen_complete",
    "main_scripted_complete",
    "main_learned_complete",
    "second_steps",
    "final_steps",
    "min_free_bytes",
    "min_free_inodes",
    "max_gpu_temperature_c",
}
QUEUE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{0,79}")


class FreezeError(ValueError):
    pass


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def atomic_json(path: str | Path, payload: dict[str, Any]) -> None:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(
        destination.suffix + f".tmp.{os.getpid()}"
    )
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, destination)


def load_object(path: str | Path, label: str) -> dict[str, Any]:
    path = Path(path)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FreezeError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise FreezeError(f"{label} must be a JSON object: {path}")
    return value


def absolute_file(value: Any, label: str, root: Path) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise FreezeError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise FreezeError(f"{label} escapes audit root: {path}") from exc
    if not path.is_file():
        raise FreezeError(f"missing {label}: {path}")
    return path


def absolute_tree(value: Any, label: str, root: Path) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise FreezeError(f"{label} must be an absolute path")
    path = Path(value).expanduser().resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise FreezeError(f"{label} escapes audit root: {path}") from exc
    if not path.is_dir():
        raise FreezeError(f"missing {label}: {path}")
    return path


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def tree_record(path: Path) -> dict[str, Any]:
    files, size, identity = experiment_queue.tree_identity(path)
    return {
        "path": str(path),
        "files": files,
        "bytes": size,
        "sha256": identity,
    }


def validate_main_screen(path: Path, candidate: str) -> dict[str, Any]:
    completion = load_object(path, "main screen completion")
    manifest_sha = completion.get("screen_manifest_sha256")
    report = analyze_reward_screen.analyze_screen(
        path.parent,
        analyze_reward_screen.DEFAULT_METRICS,
        expected_screen_sha=manifest_sha,
    )
    screen = report["screen"]
    if (
        screen["profile"] != "paired-confirmation"
        or screen.get("candidate_arm") != candidate
        or not screen["completion"].get("present")
        or screen["completion"].get("sha256") != sha256(path)
    ):
        raise FreezeError("main screen is not the exact paired candidate evidence")
    return report


def validate_spec(path: Path) -> dict[str, Any]:
    spec = load_object(path, "vacation queue spec")
    if set(spec) != SPEC_KEYS:
        raise FreezeError("vacation queue spec has unknown or missing fields")
    if spec.get("schema_version") != SCHEMA_VERSION:
        raise FreezeError("unsupported vacation queue spec schema")
    queue_id = spec.get("queue_id")
    if not isinstance(queue_id, str) or QUEUE_ID_PATTERN.fullmatch(queue_id) is None:
        raise FreezeError("queue_id has unsupported characters")
    root_value = spec.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise FreezeError("root must be absolute")
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise FreezeError(f"root does not exist: {root}")
    candidate = spec.get("candidate_arm")
    if candidate not in ("possession_only", "gain_only", "neither"):
        raise FreezeError("candidate_arm is invalid")
    if spec.get("second_steps") != 1_000_000_000:
        raise FreezeError("second_steps must be the reviewed 1B budget")
    if spec.get("final_steps") != 6_000_000_000:
        raise FreezeError("final_steps must be the reviewed 6B x three-seed budget")
    for key in ("min_free_bytes", "min_free_inodes"):
        value = spec.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise FreezeError(f"{key} must be a positive integer")
    thermal = spec.get("max_gpu_temperature_c")
    if (
        isinstance(thermal, bool)
        or not isinstance(thermal, (int, float))
        or not 80 <= thermal <= 91
    ):
        raise FreezeError("max_gpu_temperature_c must be in [80,91]")
    paths = {
        "main_warm": absolute_file(spec["main_warm"], "main warm", root),
        "second_warm": absolute_file(spec["second_warm"], "second warm", root),
        "pool": absolute_tree(spec["pool"], "static pool", root),
        "anchor_config": absolute_file(
            spec["anchor_config"], "anchor config", root
        ),
        "main_screen_complete": absolute_file(
            spec["main_screen_complete"], "main screen completion", root
        ),
        "main_scripted_complete": absolute_file(
            spec["main_scripted_complete"], "main scripted completion", root
        ),
        "main_learned_complete": absolute_file(
            spec["main_learned_complete"], "main learned completion", root
        ),
    }
    for key in ("main_warm", "second_warm"):
        if paths[key].stat().st_size != 16_066_560:
            raise FreezeError(f"{key} has the wrong architecture size")
    screen_report = validate_main_screen(paths["main_screen_complete"], candidate)
    analyze_reward_candidate_transfer.validate_completion_evidence(
        paths["main_scripted_complete"],
        expected_complete_sha=sha256(paths["main_scripted_complete"]),
        expected_candidate=candidate,
    )
    learned_report = run_reward_learned_transfer.validate_completion(
        paths["main_learned_complete"]
    )
    if (
        learned_report.get("candidate_arm") != candidate
        or learned_report.get("source_screen_complete_sha256")
        != sha256(paths["main_screen_complete"])
        or not learned_report.get("eligible_for_longer_confirmation")
    ):
        raise FreezeError("main learned transfer did not accept the candidate")
    anchor_config = run_reward_learned_transfer.validate_anchor_config(
        paths["anchor_config"]
    )
    queue_dir = root / "runs" / queue_id
    state_path = queue_dir / "QUEUE_STATE.json"
    if state_path.exists():
        raise FreezeError(f"refusing queue with existing state: {state_path}")
    return {
        **spec,
        **paths,
        "root_path": root,
        "queue_dir": queue_dir,
        "screen_report": screen_report,
        "learned_report": learned_report,
        "anchor_config_record": anchor_config,
        "spec_path": path.resolve(),
    }


def build_screen_config(
    *,
    root: Path,
    profile: str,
    candidate: str,
    steps: int,
    prefix: str,
    out_dir: Path,
    warm: Path,
    pool: Path,
    transfer: Path,
    require_gate: bool,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "root": str(root),
        "profile": profile,
        "candidate_arm": candidate,
        "steps": steps,
        "prefix": prefix,
        "out_dir": str(out_dir),
        "warm": file_record(warm),
        "pool": tree_record(pool),
        "candidate_transfer": file_record(transfer),
        "require_gate": require_gate,
        "implementation": {
            "launcher_sha256": sha256(root / "tools/run_reward_screen.sh"),
            "screen_analyzer_sha256": sha256(
                root / "tools/analyze_reward_screen.py"
            ),
            "transfer_analyzer_sha256": sha256(
                root / "tools/analyze_reward_candidate_transfer.py"
            ),
        },
    }


def pin_file(path: Path, role: str) -> dict[str, Any]:
    if not path.is_file():
        raise FreezeError(f"missing pinned {role}: {path}")
    return {
        "kind": "file",
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
        "role": role,
    }


def pin_tree(path: Path, role: str) -> dict[str, Any]:
    files, size, identity = experiment_queue.tree_identity(path)
    return {
        "kind": "tree",
        "path": str(path.resolve()),
        "files": files,
        "bytes": size,
        "sha256": identity,
        "role": role,
    }


def typed_pinned(path: Path) -> dict[str, str]:
    return {"kind": "pinned", "path": str(path.resolve())}


def typed_mutable(path: Path) -> dict[str, str]:
    return {"kind": "mutable", "path": str(path.resolve())}


def typed_artifact(job: str, path: Path) -> dict[str, str]:
    return {"kind": "artifact", "job": job, "path": str(path.resolve())}


def typed_literal(value: str) -> dict[str, str]:
    return {"kind": "literal", "value": value}


def freeze(spec: dict[str, Any]) -> Path:
    root = spec["root_path"]
    queue_dir = spec["queue_dir"]
    config_dir = queue_dir / "configs"
    logs_dir = queue_dir / "logs"
    config_dir.mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    candidate = spec["candidate_arm"]
    output_root = queue_dir / "work"
    second_dir = output_root / "second-confirmation"
    second_scripted_dir = output_root / "second-scripted-transfer"
    second_learned_dir = output_root / "second-learned-transfer"
    gate_complete = output_root / "gate" / "GATE_COMPLETE.json"
    final_main_dir = output_root / "final-main"
    final_second_dir = output_root / "final-second"
    for success in (
        second_dir / "SCREEN_COMPLETE.json",
        second_scripted_dir / "TRANSFER_COMPLETE.json",
        second_learned_dir / "LEARNED_TRANSFER_COMPLETE.json",
        gate_complete,
        final_main_dir / "SCREEN_COMPLETE.json",
        final_second_dir / "SCREEN_COMPLETE.json",
    ):
        if success.exists():
            raise FreezeError(f"refusing preexisting queue success artifact: {success}")

    configs = {
        "second": build_screen_config(
            root=root,
            profile="paired-confirmation",
            candidate=candidate,
            steps=spec["second_steps"],
            prefix=f"{spec['queue_id']}-second-confirmation",
            out_dir=second_dir,
            warm=spec["second_warm"],
            pool=spec["pool"],
            transfer=spec["main_scripted_complete"],
            require_gate=False,
        ),
        "final_main": build_screen_config(
            root=root,
            profile="paired-final",
            candidate=candidate,
            steps=spec["final_steps"],
            prefix=f"{spec['queue_id']}-final-main",
            out_dir=final_main_dir,
            warm=spec["main_warm"],
            pool=spec["pool"],
            transfer=spec["main_scripted_complete"],
            require_gate=True,
        ),
        "final_second": build_screen_config(
            root=root,
            profile="paired-final",
            candidate=candidate,
            steps=spec["final_steps"],
            prefix=f"{spec['queue_id']}-final-second",
            out_dir=final_second_dir,
            warm=spec["second_warm"],
            pool=spec["pool"],
            transfer=spec["main_scripted_complete"],
            require_gate=True,
        ),
    }
    config_paths = {}
    for name, payload in configs.items():
        destination = config_dir / f"{name.upper()}_SCREEN_CONFIG.json"
        if destination.exists() and load_object(destination, name) != payload:
            raise FreezeError(f"existing frozen config drift: {destination}")
        if not destination.exists():
            atomic_json(destination, payload)
        config_paths[name] = destination
    gate_config_path = config_dir / "GATE_CONFIG.json"
    gate_config = {
        "schema_version": SCHEMA_VERSION,
        "candidate_arm": candidate,
        "mean_perf_delta_min": -0.02,
        "seed_perf_delta_min": -0.05,
        "max_candidate_td_relative_drop": 0.20,
    }
    if gate_config_path.exists() and load_object(
        gate_config_path, "gate config"
    ) != gate_config:
        raise FreezeError("existing gate config drift")
    if not gate_config_path.exists():
        atomic_json(gate_config_path, gate_config)

    python = (root / "vendor/PufferLib/.venv/bin/python").resolve()
    source_paths = [
        python,
        root / "tools/experiment_queue.py",
        root / "tools/run_frozen_reward_screen.py",
        root / "tools/run_reward_screen.sh",
        root / "tools/run_reward_ablation.sh",
        root / "tools/run_reward_candidate_transfer.py",
        root / "tools/analyze_reward_candidate_transfer.py",
        root / "tools/analyze_reward_screen.py",
        root / "tools/run_reward_learned_transfer.py",
        root / "tools/vacation_reward_gate.py",
        root / "tools/validate_vacation_artifact.py",
        root / "tools/reward_manifest.py",
        root / "tools/install_puffer_env.sh",
        root / "tools/cpu_cap.sh",
        root / "tools/game_stats.py",
        root / "tools/contact_bot_stats.py",
        root / "tools/eval_vs_contact_bot.sh",
        root / "training/convert_checkpoint.py",
        root / "puffer/config/rewards/r0_full.json",
        root / "puffer/config/rewards/p1_possession_only.json",
        root / "puffer/config/rewards/p2_gain_only.json",
        root / "puffer/config/rewards/r2_no_possession.json",
        root / "vendor/PufferLib/config/bloodbowl.ini",
        root / "vendor/PufferLib/pufferlib/pufferl.py",
        root / "vendor/PufferLib/pufferlib/selfplay.py",
        root / "vendor/PufferLib/pufferlib/torch_pufferl.py",
        root / "vendor/PufferLib/src/pufferlib.cu",
        root / "vendor/PufferLib/src/bindings.cu",
        root / "vendor/PufferLib/src/vecenv.h",
    ]
    screen_manifest = load_object(
        spec["main_screen_complete"].parent / "SCREEN_MANIFEST.json",
        "main screen manifest",
    )
    module = Path(
        screen_manifest["contract"]["implementation"]["compiled_module"]
    ).resolve()
    source_paths.append(module)
    source_paths.extend(sorted((root / "training").glob("puffer*.patch")))
    source_paths.extend(config_paths.values())
    source_paths.append(gate_config_path)
    source_paths.append(spec["spec_path"])
    source_paths.append(spec["main_screen_complete"])
    source_paths.append(spec["main_scripted_complete"])
    source_paths.append(spec["main_learned_complete"])
    source_paths.extend((spec["main_warm"], spec["second_warm"], spec["anchor_config"]))
    source_paths.extend(
        Path(record["path"]) for record in spec["anchor_config_record"]["anchors"]
    )
    # The accepted result JSON points to each exact final native checkpoint.
    for entry in load_object(
        spec["main_screen_complete"], "main screen completion"
    )["results"]:
        result_path = spec["main_screen_complete"].parent / Path(entry["path"]).name
        result = load_object(result_path, "main screen result")
        source_paths.extend((result_path, Path(result["checkpoint"]).resolve()))

    pins_by_path: dict[str, dict[str, Any]] = {}
    for source in source_paths:
        resolved = source.resolve()
        pins_by_path.setdefault(
            str(resolved), pin_file(resolved, f"vacation input {resolved.name}")
        )
    tree_sources = [
        (spec["pool"], "static replay/league pool"),
        (spec["main_screen_complete"].parent, "main paired screen evidence"),
        (spec["main_scripted_complete"].parent, "main scripted transfer evidence"),
        (spec["main_learned_complete"].parent, "main learned transfer evidence"),
        (root / "vendor/PufferLib/ocean/bloodbowl", "installed Blood Bowl source"),
    ]
    for tree, role in tree_sources:
        pins_by_path.setdefault(str(tree.resolve()), pin_tree(tree.resolve(), role))
    pins = [pins_by_path[key] for key in sorted(pins_by_path)]
    all_pin_paths = [pin["path"] for pin in pins]

    run_frozen = root / "tools/run_frozen_reward_screen.py"
    run_scripted = root / "tools/run_reward_candidate_transfer.py"
    run_learned = root / "tools/run_reward_learned_transfer.py"
    run_gate = root / "tools/vacation_reward_gate.py"
    artifact_validator = root / "tools/validate_vacation_artifact.py"

    def job(
        *,
        job_id: str,
        command: list[dict[str, str]],
        success: Path,
        validator: list[dict[str, str]],
        mutable: list[Path],
        maximum: int,
        resume_safe: bool,
        progress: Path | None = None,
        stale: int | None = None,
    ) -> dict[str, Any]:
        payload = {
            "id": job_id,
            "command": command,
            "cwd": str(root),
            "log": str(logs_dir / f"{job_id}.log"),
            "success": {
                "path": str(success),
                "validator": validator,
                "validator_timeout_seconds": 1800,
            },
            "env": {},
            "resume_safe": resume_safe,
            "max_runtime_seconds": maximum,
            "pinned_inputs": all_pin_paths,
            "mutable_paths": [str(path) for path in mutable],
        }
        if progress is None:
            payload["progress_not_required_reason"] = (
                "bounded validation-only job under thirty minutes"
            )
        else:
            payload["progress"] = {
                "path": str(progress),
                "max_stale_seconds": stale,
            }
        return payload

    second_complete = second_dir / "SCREEN_COMPLETE.json"
    second_scripted_complete = second_scripted_dir / "TRANSFER_COMPLETE.json"
    second_learned_complete = (
        second_learned_dir / "LEARNED_TRANSFER_COMPLETE.json"
    )
    final_main_complete = final_main_dir / "SCREEN_COMPLETE.json"
    final_second_complete = final_second_dir / "SCREEN_COMPLETE.json"
    jobs = [
        job(
            job_id="second-confirmation",
            command=[
                typed_pinned(python), typed_pinned(run_frozen),
                typed_literal("--config"), typed_pinned(config_paths["second"]),
            ],
            success=second_complete,
            validator=[
                typed_pinned(python), typed_pinned(artifact_validator),
                typed_literal("--screen"), typed_pinned(config_paths["second"]),
                typed_mutable(second_complete),
            ],
            mutable=[second_dir],
            maximum=12 * 3600,
            resume_safe=False,
            progress=second_dir / "SCREEN_STATUS.json",
            stale=600,
        ),
        job(
            job_id="second-scripted-transfer",
            command=[
                typed_pinned(python), typed_pinned(run_scripted),
                typed_literal("--screen-complete"),
                typed_artifact("second-confirmation", second_complete),
                typed_literal("--out-dir"), typed_mutable(second_scripted_dir),
            ],
            success=second_scripted_complete,
            validator=[
                typed_pinned(python), typed_pinned(artifact_validator),
                typed_literal("--scripted-transfer"),
                typed_pinned(gate_config_path), typed_mutable(second_scripted_complete),
            ],
            mutable=[second_scripted_dir],
            maximum=12 * 3600,
            resume_safe=True,
            progress=second_scripted_dir / "TRANSFER_STATUS.json",
            stale=1800,
        ),
        job(
            job_id="second-learned-transfer",
            command=[
                typed_pinned(python), typed_pinned(run_learned),
                typed_literal("--screen-complete"),
                typed_artifact("second-confirmation", second_complete),
                typed_literal("--anchor-config"), typed_pinned(spec["anchor_config"]),
                typed_literal("--out-dir"), typed_mutable(second_learned_dir),
            ],
            success=second_learned_complete,
            validator=[
                typed_pinned(python), typed_pinned(run_learned),
                typed_literal("--validate-complete"),
                typed_mutable(second_learned_complete),
            ],
            mutable=[second_learned_dir],
            maximum=24 * 3600,
            resume_safe=True,
            progress=second_learned_dir / "LEARNED_TRANSFER_STATUS.json",
            stale=3600,
        ),
        job(
            job_id="two-lineage-gate",
            command=[
                typed_pinned(python), typed_pinned(run_gate),
                typed_literal("--config"), typed_pinned(gate_config_path),
                typed_literal("--main-screen"),
                typed_pinned(spec["main_screen_complete"]),
                typed_literal("--main-scripted"),
                typed_pinned(spec["main_scripted_complete"]),
                typed_literal("--main-learned"),
                typed_pinned(spec["main_learned_complete"]),
                typed_literal("--second-screen"),
                typed_artifact("second-confirmation", second_complete),
                typed_literal("--second-scripted"),
                typed_artifact("second-scripted-transfer", second_scripted_complete),
                typed_literal("--second-learned"),
                typed_artifact("second-learned-transfer", second_learned_complete),
                typed_literal("--output"), typed_mutable(gate_complete),
            ],
            success=gate_complete,
            validator=[
                typed_pinned(python), typed_pinned(run_gate),
                typed_literal("--validate"), typed_mutable(gate_complete),
            ],
            mutable=[gate_complete.parent],
            maximum=1800,
            resume_safe=True,
        ),
        job(
            job_id="final-main",
            command=[
                typed_pinned(python), typed_pinned(run_frozen),
                typed_literal("--config"), typed_pinned(config_paths["final_main"]),
                typed_literal("--gate-complete"),
                typed_artifact("two-lineage-gate", gate_complete),
            ],
            success=final_main_complete,
            validator=[
                typed_pinned(python), typed_pinned(artifact_validator),
                typed_literal("--screen"), typed_pinned(config_paths["final_main"]),
                typed_mutable(final_main_complete),
            ],
            mutable=[final_main_dir],
            maximum=72 * 3600,
            resume_safe=False,
            progress=final_main_dir / "SCREEN_STATUS.json",
            stale=600,
        ),
        job(
            job_id="final-second",
            command=[
                typed_pinned(python), typed_pinned(run_frozen),
                typed_literal("--config"), typed_pinned(config_paths["final_second"]),
                typed_literal("--gate-complete"),
                typed_artifact("two-lineage-gate", gate_complete),
            ],
            success=final_second_complete,
            validator=[
                typed_pinned(python), typed_pinned(artifact_validator),
                typed_literal("--screen"), typed_pinned(config_paths["final_second"]),
                typed_mutable(final_second_complete),
            ],
            mutable=[final_second_dir],
            maximum=72 * 3600,
            resume_safe=False,
            progress=final_second_dir / "SCREEN_STATUS.json",
            stale=600,
        ),
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
            "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
            "PYTHONUNBUFFERED": "1",
            "TZ": "America/Los_Angeles",
        },
        "pinned_files": pins,
        "jobs": jobs,
    }
    plan_path = queue_dir / "QUEUE_PLAN.json"
    if plan_path.exists() and load_object(plan_path, "queue plan") != plan:
        raise FreezeError("existing QUEUE_PLAN.json differs from recomputed plan")
    if not plan_path.exists():
        atomic_json(plan_path, plan)
    validated, validated_root, digest = experiment_queue.validate_plan(plan_path)
    if validated != plan or validated_root != root:
        raise FreezeError("queue plan changed during validation")
    print(f"VACATION QUEUE FROZEN: {plan_path}")
    print(f"queue_plan_sha256={digest}")
    print(f"jobs={len(jobs)} candidate={candidate}")
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
        FreezeError,
        experiment_queue.QueueError,
        analyze_reward_screen.AnalysisError,
        analyze_reward_candidate_transfer.TransferError,
        run_reward_learned_transfer.LearnedTransferError,
        ValueError,
    ) as exc:
        print(f"vacation queue freeze failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
