#!/usr/bin/env python3
"""Freeze the reviewed six-day reward queue from predeparture evidence.

The builder does no candidate selection. A spec explicitly chooses one of
three evidence routes: an accepted candidate, an all-candidates-rejected R0
control, or R0 baseline characterization after the already-selected candidate
fails its paired confirmation. Only the accepted-candidate route can emit
candidate jobs. Both R0 routes emit the same two control-only replication
screens and can never route a rejected reward into training. The builder then
emits and validates the closed typed ``QUEUE_PLAN.json`` consumed by
``experiment_queue.py``.
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
import run_reward_candidate_transfer
import run_reward_learned_transfer
import vacation_reward_gate


SCHEMA_VERSION = 1
SPEC_SCHEMA_VERSION = 2
SPEC_KEYS = {
    "schema_version",
    "queue_id",
    "route",
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
REVIEWED_SECOND_ANCESTRY = {
    "name": "league9",
    "sha256": "359d14caa08f12362f799c4cab4f33301fc9ce2ba3dec85922abe9622670d5f5",
}
CONTROL_TRANSFER_CANDIDATES = ["possession_only", "gain_only", "neither"]
CONTROL_TRANSFER_PREFERENCE = ["neither", "possession_only", "gain_only"]
ROUTE_CANDIDATE = "candidate"
ROUTE_ALL_REJECTED = "all-candidates-rejected-control"
ROUTE_CONFIRMATION_REJECTED = "confirmation-rejected-baseline"
ROUTES = {
    ROUTE_CANDIDATE,
    ROUTE_ALL_REJECTED,
    ROUTE_CONFIRMATION_REJECTED,
}
GATE_CONFIG = {
    "schema_version": 1,
    "confirmation_steps": 1_000_000_000,
    "mean_perf_delta_min": -0.02,
    "seed_perf_delta_min": -0.05,
    "max_candidate_td_relative_drop": 0.20,
}
SCREEN_CRITICAL_VENDOR_FILES = {
    "pufferlib/__init__.py",
    "pufferlib/pufferl.py",
    "pufferlib/selfplay.py",
    "pufferlib/torch_pufferl.py",
    "pufferlib/models.py",
    "pufferlib/muon.py",
    "src/pufferlib.cu",
    "src/bindings.cu",
    "src/bindings_cpu.cpp",
    "src/kernels.cu",
    "src/vecenv.h",
}
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


def validate_main_screen(
    path: Path, candidate: str, warm: Path, pool: Path, root: Path,
    route: str,
) -> dict[str, Any]:
    root = root.resolve()
    all_rejected = route == ROUTE_ALL_REJECTED
    completion = load_object(path, "main screen completion")
    manifest_sha = completion.get("screen_manifest_sha256")
    report = analyze_reward_screen.analyze_screen(
        path.parent,
        analyze_reward_screen.DEFAULT_METRICS,
        expected_screen_sha=manifest_sha,
    )
    screen = report["screen"]
    expected_profile = "possession-gain" if all_rejected else "paired-confirmation"
    expected_steps = 500_000_000 if all_rejected else 1_000_000_000
    if (
        screen["profile"] != expected_profile
        or (not all_rejected and screen.get("candidate_arm") != candidate)
        or screen.get("requested_steps") != expected_steps
        or not screen["completion"].get("present")
        or screen["completion"].get("sha256") != sha256(path)
    ):
        label = "control fallback source" if all_rejected else "paired candidate"
        raise FreezeError(f"main screen is not the exact {label} evidence")
    manifest = load_object(path.parent / "SCREEN_MANIFEST.json", "main screen manifest")
    contract = manifest.get("contract")
    if not isinstance(contract, dict):
        raise FreezeError("main screen manifest has no contract")
    warm_record = contract.get("warm")
    pool_record = contract.get("pool")
    if (
        not isinstance(warm_record, dict)
        or warm_record.get("sha256") != sha256(warm)
    ):
        raise FreezeError("main screen does not use the declared main warm")
    pool_manifest = pool / "league_seeds.json"
    if (
        not isinstance(pool_record, dict)
        or not pool_manifest.is_file()
        or pool_record.get("manifest_sha256") != sha256(pool_manifest)
    ):
        raise FreezeError("main screen does not use the declared static pool")
    for bank in pool_record.get("banks", []):
        if not isinstance(bank, dict):
            raise FreezeError("main screen pool bank identity is malformed")
        current_bank = pool / Path(str(bank.get("file", ""))).name
        if (
            not current_bank.is_file()
            or sha256(current_bank) != bank.get("sha256")
        ):
            raise FreezeError("declared static pool differs from a main screen bank")
    implementation = contract.get("implementation")
    if not isinstance(implementation, dict):
        raise FreezeError("main screen has no implementation identity")
    source_hash = root / "vendor/PufferLib/ocean/bloodbowl/.content_hash"
    if (
        not source_hash.is_file()
        or source_hash.read_text(encoding="utf-8").strip()
        != implementation.get("source_sha256")
    ):
        raise FreezeError("installed Blood Bowl source differs from main screen")
    current_config = root / "vendor/PufferLib/config/bloodbowl.ini"
    if (
        not current_config.is_file()
        or sha256(current_config) != implementation.get("config_sha256")
    ):
        raise FreezeError("installed Puffer config differs from main screen")
    config_tree = root / "vendor/PufferLib/config"
    try:
        observed_config_tree_sha = run_reward_candidate_transfer.tree_sha256(
            config_tree
        )
    except run_reward_candidate_transfer.RunnerError as exc:
        raise FreezeError(f"invalid Puffer config tree: {exc}") from exc
    if observed_config_tree_sha != implementation.get("config_tree_sha256"):
        raise FreezeError("Puffer config tree differs from main screen")
    default_config = config_tree / "default.ini"
    if (
        not default_config.is_file()
        or sha256(default_config) != implementation.get("default_config_sha256")
    ):
        raise FreezeError("Puffer default config differs from main screen")
    module_value = implementation.get("compiled_module")
    if not isinstance(module_value, str):
        raise FreezeError("main screen compiled-module path is malformed")
    module = Path(module_value).resolve()
    try:
        module.relative_to(root)
    except ValueError as exc:
        raise FreezeError("main screen compiled module escapes audit root") from exc
    if (
        not module.is_file()
        or sha256(module) != implementation.get("compiled_module_sha256")
    ):
        raise FreezeError("compiled module differs from main screen")
    critical = implementation.get("critical_vendor_files")
    critical_names = set(critical) if isinstance(critical, dict) else set()
    if (
        not isinstance(critical, dict)
        or critical_names != SCREEN_CRITICAL_VENDOR_FILES
    ):
        raise FreezeError("main screen critical vendor identity is incomplete")
    for relative, expected in critical.items():
        current = (root / "vendor/PufferLib" / relative).resolve()
        try:
            current.relative_to(root / "vendor/PufferLib")
        except ValueError as exc:
            raise FreezeError("main screen vendor path escapes checkout") from exc
        if not current.is_file() or sha256(current) != expected:
            raise FreezeError(f"critical vendor source differs: {relative}")
    patches = implementation.get("patches")
    if not isinstance(patches, dict) or not patches:
        raise FreezeError("main screen patch identity is incomplete")
    for patch_value, expected in patches.items():
        patch = Path(patch_value).resolve()
        try:
            patch.relative_to(root)
        except ValueError as exc:
            raise FreezeError("main screen patch path escapes audit root") from exc
        if not patch.is_file() or sha256(patch) != expected:
            raise FreezeError(f"Puffer patch differs from main screen: {patch.name}")
    return report


def validate_spec(path: Path) -> dict[str, Any]:
    spec = load_object(path, "vacation queue spec")
    if spec.get("schema_version") != SPEC_SCHEMA_VERSION:
        raise FreezeError("unsupported vacation queue spec schema")
    if set(spec) != SPEC_KEYS:
        raise FreezeError("vacation queue spec has unknown or missing fields")
    queue_id = spec.get("queue_id")
    if not isinstance(queue_id, str) or QUEUE_ID_PATTERN.fullmatch(queue_id) is None:
        raise FreezeError("queue_id has unsupported characters")
    route = spec.get("route")
    if route not in ROUTES:
        raise FreezeError("vacation queue route is invalid")
    root_value = spec.get("root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise FreezeError("root must be absolute")
    root = Path(root_value).resolve()
    if not root.is_dir():
        raise FreezeError(f"root does not exist: {root}")
    candidate = spec.get("candidate_arm")
    r0_only = route != ROUTE_CANDIDATE
    if candidate not in ("both", "possession_only", "gain_only", "neither"):
        raise FreezeError("candidate_arm is invalid")
    if route == ROUTE_ALL_REJECTED and candidate != "both":
        raise FreezeError(
            "all-candidates-rejected route requires candidate_arm=both"
        )
    if route != ROUTE_ALL_REJECTED and candidate == "both":
        raise FreezeError(f"{route} requires a simplification candidate")
    if spec.get("second_steps") != 1_000_000_000:
        raise FreezeError("second_steps must be the reviewed 1B budget")
    expected_final_steps = 12_000_000_000 if r0_only else 6_000_000_000
    if spec.get("final_steps") != expected_final_steps:
        label = "12B R0" if r0_only else "6B paired"
        raise FreezeError(
            f"final_steps must be the reviewed {label} x three-seed budget"
        )
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
        "main_screen_complete": absolute_file(
            spec["main_screen_complete"], "main screen completion", root
        ),
        "main_scripted_complete": absolute_file(
            spec["main_scripted_complete"], "main scripted completion", root
        ),
    }
    if r0_only:
        if spec.get("anchor_config") is not None or spec.get(
            "main_learned_complete"
        ) is not None:
            raise FreezeError(
                "R0-only routes require null learned-transfer inputs"
            )
    else:
        paths.update({
            "anchor_config": absolute_file(
                spec["anchor_config"], "anchor config", root
            ),
            "main_learned_complete": absolute_file(
                spec["main_learned_complete"], "main learned completion", root
            ),
        })
    for key in ("main_warm", "second_warm"):
        if paths[key].stat().st_size != 16_066_560:
            raise FreezeError(f"{key} has the wrong architecture size")
    if sha256(paths["main_warm"]) == sha256(paths["second_warm"]):
        raise FreezeError("main and second ancestry warm checkpoints must differ")
    if sha256(paths["second_warm"]) != REVIEWED_SECOND_ANCESTRY["sha256"]:
        raise FreezeError(
            "second warm is not the reviewed league9 ancestry checkpoint"
        )
    screen_report = validate_main_screen(
        paths["main_screen_complete"], candidate, paths["main_warm"],
        paths["pool"], root, route,
    )
    scripted_evidence = analyze_reward_candidate_transfer.validate_completion_evidence(
        paths["main_scripted_complete"],
        expected_complete_sha=sha256(paths["main_scripted_complete"]),
        expected_candidate=candidate,
    )
    scripted_manifest = load_object(
        Path(scripted_evidence["transfer_manifest"]), "main scripted manifest"
    )
    if route == ROUTE_CONFIRMATION_REJECTED:
        main_manifest = load_object(
            paths["main_screen_complete"].parent / "SCREEN_MANIFEST.json",
            "main screen manifest",
        )
        contract = main_manifest.get("contract")
        candidate_evidence = (
            contract.get("candidate_evidence")
            if isinstance(contract, dict) else None
        )
        if candidate_evidence != scripted_evidence:
            raise FreezeError(
                "paired confirmation is not bound to the declared selection transfer"
            )
    elif (
        Path(str(scripted_manifest.get("source_screen", ""))).resolve()
        != paths["main_screen_complete"].parent
        or scripted_manifest.get("source_screen_sha256")
        != screen_report["screen"]["manifest_sha256"]
    ):
        raise FreezeError("main scripted transfer uses another paired screen")
    expected_scripted_contract = (
        run_reward_candidate_transfer.transfer_contract_identity(root)
    )
    observed_scripted_contract = {
        key: scripted_manifest.get(key) for key in expected_scripted_contract
    }
    if observed_scripted_contract != expected_scripted_contract:
        raise FreezeError(
            "main scripted transfer differs from the frozen implementation contract"
        )
    confirmation_rejection = None
    if route == ROUTE_ALL_REJECTED:
        if (
            scripted_manifest.get("reference_arm") != "both"
            or scripted_manifest.get("candidate_arms")
            != CONTROL_TRANSFER_CANDIDATES
            or scripted_manifest.get("preference_order")
            != CONTROL_TRANSFER_PREFERENCE
        ):
            raise FreezeError(
                "control fallback requires all three simplification arms"
            )
        transfer_analysis = load_object(
            Path(scripted_evidence["analysis"]), "main scripted analysis"
        )
        recommendation = transfer_analysis.get("recommendation")
        if (
            not isinstance(recommendation, dict)
            or recommendation.get("arm") != "both"
            or recommendation.get("eligible_candidates_in_preference_order") != []
        ):
            raise FreezeError(
                "control fallback is forbidden while an eligible simplification exists"
            )
        anchor_config = None
        learned_report = None
    elif route == ROUTE_CONFIRMATION_REJECTED:
        gate_config = {**GATE_CONFIG, "candidate_arm": candidate}
        try:
            confirmation_rejection, failures = vacation_reward_gate.validate_screen(
                paths["main_screen_complete"], gate_config, "main"
            )
        except (OSError, ValueError, vacation_reward_gate.GateError) as exc:
            raise FreezeError(
                f"invalid rejected confirmation evidence: {exc}"
            ) from exc
        if not failures:
            raise FreezeError("paired confirmation did not reject the candidate")
        anchor_config = None
        learned_report = None
    else:
        anchor_config = run_reward_learned_transfer.validate_anchor_config(
            paths["anchor_config"]
        )
        if anchor_config["games_per_cell"] != 4096:
            raise FreezeError(
                "anchor config must use the reviewed 4096 games per cell"
            )
        if len(anchor_config["anchors"]) != 4:
            raise FreezeError(
                "vacation learned transfer requires exactly four anchors"
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
        learned_manifest_record = learned_report.get("learned_transfer_manifest")
        if not isinstance(learned_manifest_record, dict):
            raise FreezeError("main learned transfer omitted its manifest")
        learned_manifest = load_object(
            Path(str(learned_manifest_record.get("path", ""))),
            "main learned transfer manifest",
        )
        if (
            learned_manifest.get("games_per_cell") != 4096
            or learned_manifest.get("anchor_config_sha256")
            != anchor_config["sha256"]
        ):
            raise FreezeError("main learned transfer uses another anchor contract")
        expected_learned_contract = (
            run_reward_learned_transfer.learned_contract_identity(
                root, anchor_config
            )
        )
        observed_learned_contract = {
            key: learned_manifest.get(key) for key in expected_learned_contract
        }
        if observed_learned_contract != expected_learned_contract:
            raise FreezeError(
                "main learned transfer differs from the frozen implementation contract"
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
        "r0_only": r0_only,
        "confirmation_rejection": confirmation_rejection,
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
    transfer: Path | None,
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
        "candidate_transfer": file_record(transfer) if transfer is not None else None,
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
    route = spec["route"]
    r0_only = route != ROUTE_CANDIDATE
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

    if r0_only:
        configs = {
            "final_main": build_screen_config(
                root=root,
                profile="control-final",
                candidate="both",
                steps=spec["final_steps"],
                prefix=f"{spec['queue_id']}-final-main-control",
                out_dir=final_main_dir,
                warm=spec["main_warm"],
                pool=spec["pool"],
                transfer=None,
                require_gate=False,
            ),
            "final_second": build_screen_config(
                root=root,
                profile="control-final",
                candidate="both",
                steps=spec["final_steps"],
                prefix=f"{spec['queue_id']}-final-second-control",
                out_dir=final_second_dir,
                warm=spec["second_warm"],
                pool=spec["pool"],
                transfer=None,
                require_gate=False,
            ),
        }
    else:
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
    gate_config = {**GATE_CONFIG, "candidate_arm": candidate}
    if not r0_only:
        if gate_config_path.exists() and load_object(
            gate_config_path, "gate config"
        ) != gate_config:
            raise FreezeError("existing gate config drift")
        if not gate_config_path.exists():
            atomic_json(gate_config_path, gate_config)
    authorization_path = config_dir / "BASELINE_AUTHORIZATION.json"
    if route == ROUTE_CONFIRMATION_REJECTED:
        authorization = {
            "schema_version": SCHEMA_VERSION,
            "route": route,
            "candidate_arm": candidate,
            "fixed_gate": gate_config,
            "rejection": spec["confirmation_rejection"],
            "warning": (
                "This proof authorizes only R0 baseline characterization. "
                "It does not select or promote a reward candidate."
            ),
        }
        if authorization_path.exists() and load_object(
            authorization_path, "baseline authorization"
        ) != authorization:
            raise FreezeError("existing baseline authorization drift")
        if not authorization_path.exists():
            atomic_json(authorization_path, authorization)

    python = (root / "vendor/PufferLib/.venv/bin/python").resolve()
    source_paths = [
        python,
        Path("/bin/bash"),
        root / "vendor/PufferLib/.venv/bin/puffer",
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
        root / "puffer/config/bloodbowl.ini",
        root / "puffer/config/rewards/r0_full.json",
        root / "puffer/config/rewards/p1_possession_only.json",
        root / "puffer/config/rewards/p2_gain_only.json",
        root / "puffer/config/rewards/r2_no_possession.json",
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
    if route == ROUTE_CONFIRMATION_REJECTED:
        source_paths.append(authorization_path)
    if not r0_only:
        source_paths.append(gate_config_path)
    source_paths.append(spec["spec_path"])
    source_paths.append(spec["main_screen_complete"])
    source_paths.append(spec["main_scripted_complete"])
    source_paths.extend((spec["main_warm"], spec["second_warm"]))
    if not r0_only:
        source_paths.append(spec["main_learned_complete"])
        source_paths.append(spec["anchor_config"])
        source_paths.extend(
            Path(record["path"])
            for record in spec["anchor_config_record"]["anchors"]
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
        (root / "vendor/PufferLib/config", "Puffer configuration closure"),
        (spec["main_screen_complete"].parent, "main screen evidence"),
        (spec["main_scripted_complete"].parent, "main scripted transfer evidence"),
        (root / "vendor/PufferLib/ocean/bloodbowl", "installed Blood Bowl source"),
    ]
    if not r0_only:
        tree_sources.append(
            (spec["main_learned_complete"].parent, "main learned transfer evidence")
        )
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
    if r0_only:
        jobs = [
            job(
                job_id="final-main-control",
                command=[
                    typed_pinned(python), typed_pinned(run_frozen),
                    typed_literal("--config"),
                    typed_pinned(config_paths["final_main"]),
                ],
                success=final_main_complete,
                validator=[
                    typed_pinned(python), typed_pinned(artifact_validator),
                    typed_literal("--screen"),
                    typed_pinned(config_paths["final_main"]),
                    typed_mutable(final_main_complete),
                ],
                mutable=[final_main_dir],
                maximum=72 * 3600,
                resume_safe=False,
                progress=final_main_dir / "SCREEN_STATUS.json",
                stale=600,
            ),
            job(
                job_id="final-second-control",
                command=[
                    typed_pinned(python), typed_pinned(run_frozen),
                    typed_literal("--config"),
                    typed_pinned(config_paths["final_second"]),
                ],
                success=final_second_complete,
                validator=[
                    typed_pinned(python), typed_pinned(artifact_validator),
                    typed_literal("--screen"),
                    typed_pinned(config_paths["final_second"]),
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
                "PATH": (
                    "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:"
                    "/sbin:/bin"
                ),
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
        print(f"VACATION R0 QUEUE FROZEN: {plan_path}")
        print(f"queue_plan_sha256={digest}")
        print(f"jobs={len(jobs)} route={route} reward=both")
        return plan_path
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
