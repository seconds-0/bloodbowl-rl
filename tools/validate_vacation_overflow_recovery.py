#!/usr/bin/env python3
"""Validate the exact terminal overflow evidence before a fresh R0 rerun."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import game_stats
from game_stats import completed_game_requirement_met


SCHEMA_VERSION = 1
PRIOR_QUEUE_ID = "vacation-r0-overflow-20260714-v1"
REVIEWED_PRIOR_ROOT = Path("/home/rache/bloodbowl-rl-audit")
REVIEWED_RECOVERY_ROOT = Path("/home/rache/bloodbowl-rl-recovery-20260719")
PRIOR_FILE_KEYS = (
    "plan",
    "state",
    "manifest",
    "status",
    "result",
    "checkpoint",
)
REVIEWED_PRIOR_FILES = {
    "plan": {
        "bytes": 39_966,
        "sha256": "d90ee01c8c459f599c8601934f545ccb7783261edae3bcb6e9e3878036d37d3e",
    },
    "state": {
        "bytes": 1_227,
        "sha256": "42154a7f77ed4ea71a292bd4d1a391a9b10e2cb9ebd60420ceb6c8901473a34e",
    },
    "manifest": {
        "bytes": 7_055,
        "sha256": "133893835baa02e22bc781ef2e9e2a5697176ee2444b7a7859d06de6e28ea151",
    },
    "status": {
        "bytes": 377,
        "sha256": "0a7d452359f8d3564e1185c9a60832b7ac72f012b48448a5322d8c2e3d3596c8",
    },
    "result": {
        "bytes": 8_688,
        "sha256": "5f3c459dba99652cc0d8b24957563ca77ca7a16e02e1478ff10c4568e73a0a25",
    },
    "checkpoint": {
        "bytes": 16_066_560,
        "sha256": "5aff922209eabb6226282cb170ce2dfce771a11a641edfbf89220517c061b323",
    },
}
NETBLOCK_SHA256 = "9964cf4d4c9c2654157e898ff17327732e73c4c85a5883e7d311d8d3baade05e"
R0_REWARD_SHA256 = "14b718f28b2c925ea3279444dfbc679631c0cceea0f84d9e3547e3318ce6e90e"
PRIMARY_SUCCESS_SHA256 = (
    "f990f7b267bfd994b93b9f83f065f49b7eed40ed5b84b88448c367e49e2d816e"
)
EXPECTED_FAILURE = {
    "phase": "eval",
    "kind": "insufficient_games",
    "observed": 10000.0,
    "minimum": 10001,
}
INTEGRITY_KEYS = (
    "reward_clip_frac",
    "reward_clip_frac_nonzero",
    "reward_clip_excess",
    "reward_nonfinite_frac",
    "reward_clip_episodes",
    "reward_nonfinite_episodes",
    "error_episodes",
    "demo_fallbacks",
)
WARNING = (
    "This proof authorizes only a separately named, full R0 rerun from the "
    "reviewed netblock ancestry. It does not accept or reuse the rejected "
    "result, restart the prior queue, select or promote a reward, or authorize "
    "milestone evaluation."
)
CONFIG_KEYS = {
    "schema_version",
    "recovery_root",
    "prior_queue_id",
    "prior_plan",
    "prior_state",
    "prior_screen_manifest",
    "prior_screen_status",
    "prior_result",
    "prior_checkpoint",
    "corrected_launcher",
    "corrected_game_stats",
    "nvidia_smi",
    "warning",
}
FILE_KEYS = {"path", "bytes", "sha256"}


class RecoveryEvidenceError(ValueError):
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
        raise RecoveryEvidenceError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RecoveryEvidenceError(f"{label} must be a JSON object: {path}")
    return value


def atomic_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def require_sha(value: Any, label: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(char not in "0123456789abcdef" for char in value)
    ):
        raise RecoveryEvidenceError(f"{label} must be a lowercase SHA-256")
    return value


def validate_file(record: Any, label: str) -> Path:
    if not isinstance(record, dict) or set(record) != FILE_KEYS:
        raise RecoveryEvidenceError(f"{label} must contain path/bytes/sha256")
    path_value = record.get("path")
    if not isinstance(path_value, str) or not Path(path_value).is_absolute():
        raise RecoveryEvidenceError(f"{label} path must be absolute")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise RecoveryEvidenceError(f"missing {label}: {path}")
    size = record.get("bytes")
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise RecoveryEvidenceError(f"{label} bytes must be positive")
    if path.stat().st_size != size:
        raise RecoveryEvidenceError(f"{label} size drift: {path}")
    expected = require_sha(record.get("sha256"), f"{label} SHA-256")
    observed = sha256(path)
    if observed != expected:
        raise RecoveryEvidenceError(
            f"{label} SHA-256 drift: {observed} != {expected}: {path}"
        )
    return path


def require_reviewed_record(record: Any, key: str) -> Path:
    path = validate_file(record, f"prior {key}")
    reviewed = REVIEWED_PRIOR_FILES[key]
    if record["bytes"] != reviewed["bytes"] or record["sha256"] != reviewed["sha256"]:
        raise RecoveryEvidenceError(f"prior {key} is not the reviewed artifact")
    return path


def under(path: Path, root: Path, label: str) -> Path:
    resolved = path.expanduser().resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise RecoveryEvidenceError(
            f"{label} escapes recovery root: {resolved}"
        ) from exc
    return resolved


def validate_config(path: Path) -> dict[str, Any]:
    config = load_object(path, "recovery preflight config")
    if set(config) != CONFIG_KEYS:
        raise RecoveryEvidenceError("recovery preflight config fields differ")
    if config.get("schema_version") != SCHEMA_VERSION:
        raise RecoveryEvidenceError("unsupported recovery preflight schema")
    root_value = config.get("recovery_root")
    if not isinstance(root_value, str) or not Path(root_value).is_absolute():
        raise RecoveryEvidenceError("recovery_root must be absolute")
    recovery_root = Path(root_value).expanduser().resolve()
    if not recovery_root.is_dir():
        raise RecoveryEvidenceError(f"recovery root is missing: {recovery_root}")
    if recovery_root != Path(REVIEWED_RECOVERY_ROOT).expanduser().resolve():
        raise RecoveryEvidenceError("recovery root is not the reviewed exact root")
    prior_root = Path(REVIEWED_PRIOR_ROOT).expanduser().resolve()
    if (
        recovery_root == prior_root
        or recovery_root in prior_root.parents
        or prior_root in recovery_root.parents
    ):
        raise RecoveryEvidenceError("recovery root is not isolated from the prior root")
    if config.get("prior_queue_id") != PRIOR_QUEUE_ID:
        raise RecoveryEvidenceError("prior queue ID is not reviewed")
    if config.get("warning") != WARNING:
        raise RecoveryEvidenceError("recovery authorization warning differs")

    prior_paths = {
        "plan": require_reviewed_record(config["prior_plan"], "plan"),
        "state": require_reviewed_record(config["prior_state"], "state"),
        "manifest": require_reviewed_record(
            config["prior_screen_manifest"], "manifest"
        ),
        "status": require_reviewed_record(config["prior_screen_status"], "status"),
        "result": require_reviewed_record(config["prior_result"], "result"),
        "checkpoint": require_reviewed_record(config["prior_checkpoint"], "checkpoint"),
    }
    queue_dir = prior_root / "runs" / PRIOR_QUEUE_ID
    screen_dir = queue_dir / "work/final-third"
    prefix = f"{PRIOR_QUEUE_ID}-final-third-control"
    expected_paths = {
        "plan": queue_dir / "QUEUE_PLAN.json",
        "state": queue_dir / "QUEUE_STATE.json",
        "manifest": screen_dir / "SCREEN_MANIFEST.json",
        "status": screen_dir / "SCREEN_STATUS.json",
        "result": screen_dir / f"{prefix}-both-s42.result.json",
        "checkpoint": (
            prior_root / "vendor/PufferLib/checkpoints/bloodbowl/1784448368863/"
            "0000011999903744.bin"
        ),
    }
    for key, expected in expected_paths.items():
        if prior_paths[key] != expected.resolve():
            raise RecoveryEvidenceError(f"prior {key} path is not reviewed")

    launcher = validate_file(config["corrected_launcher"], "corrected launcher")
    helper = validate_file(config["corrected_game_stats"], "corrected game helper")
    nvidia_smi = validate_file(config["nvidia_smi"], "nvidia-smi")
    loaded_helper = Path(game_stats.__file__).resolve()
    if helper != loaded_helper:
        raise RecoveryEvidenceError(
            "corrected game helper differs from imported helper"
        )
    source_root = Path(__file__).resolve().parents[1]
    if launcher != (source_root / "tools/run_reward_screen.sh").resolve():
        raise RecoveryEvidenceError("corrected launcher differs from recovery source")
    launcher_text = launcher.read_text(encoding="utf-8")
    if (
        "MIN_EVAL_GAMES=10000" not in launcher_text
        or '"eval_episodes": "10000"' not in launcher_text
    ):
        raise RecoveryEvidenceError("corrected launcher lacks the 10,000-game contract")
    if (
        not completed_game_requirement_met(10000, 10000)
        or completed_game_requirement_met(9999, 10000)
        or completed_game_requirement_met(math.nan, 10000)
    ):
        raise RecoveryEvidenceError(
            "corrected completed-game boundary is not inclusive"
        )
    return {
        **config,
        "config_path": path.resolve(),
        "recovery_root_path": recovery_root,
        "prior_root_path": prior_root,
        "prior_paths": prior_paths,
        "queue_dir": queue_dir,
        "screen_dir": screen_dir,
        "prefix": prefix,
        "launcher_path": launcher,
        "game_stats_path": helper,
        "nvidia_smi_path": nvidia_smi,
    }


def gpu_compute_pids(nvidia_smi: Path) -> list[int]:
    try:
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
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RecoveryEvidenceError(
            f"nvidia-smi compute-process query could not complete: {exc}"
        ) from exc
    if completed.returncode != 0:
        raise RecoveryEvidenceError(
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
            raise RecoveryEvidenceError(
                f"nvidia-smi returned a malformed compute PID: {value!r}"
            ) from exc
        if pid <= 0:
            raise RecoveryEvidenceError(
                f"nvidia-smi returned an invalid compute PID: {pid}"
            )
        pids.append(pid)
    return sorted(set(pids))


def require_integrity_zero(metrics: Any, phase: str) -> None:
    if not isinstance(metrics, dict):
        raise RecoveryEvidenceError(f"prior {phase} metrics are missing")
    for key in INTEGRITY_KEYS:
        value = metrics.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise RecoveryEvidenceError(
                f"prior {phase} integrity metric {key} is missing"
            )
        if not math.isfinite(float(value)) or float(value) != 0.0:
            raise RecoveryEvidenceError(
                f"prior {phase} integrity metric {key} is nonzero"
            )


def recovery_report(config: dict[str, Any]) -> dict[str, Any]:
    compute_pids = gpu_compute_pids(config["nvidia_smi_path"])
    if compute_pids:
        raise RecoveryEvidenceError(
            f"GPU is not idle; compute PIDs are present: {compute_pids}"
        )
    paths = config["prior_paths"]
    plan = load_object(paths["plan"], "prior queue plan")
    expected_ids = ["primary-completion-gate", "final-third-control"]
    jobs = plan.get("jobs")
    if (
        plan.get("schema_version") != 1
        or plan.get("queue_id") != PRIOR_QUEUE_ID
        or Path(str(plan.get("root", ""))).resolve() != config["prior_root_path"]
        or not isinstance(jobs, list)
        or [job.get("id") for job in jobs if isinstance(job, dict)] != expected_ids
        or jobs[0].get("resume_safe") is not True
        or jobs[1].get("resume_safe") is not False
    ):
        raise RecoveryEvidenceError("prior plan is not the reviewed overflow route")
    expected_complete = config["screen_dir"] / "SCREEN_COMPLETE.json"
    final_success = jobs[1].get("success")
    if not isinstance(final_success, dict) or (
        Path(str(final_success.get("path", ""))).resolve() != expected_complete
    ):
        raise RecoveryEvidenceError("prior plan final success path differs")

    state = load_object(paths["state"], "prior queue state")
    state_jobs = state.get("jobs")
    terminal = (
        state.get("schema_version") == 1
        and state.get("queue_id") == PRIOR_QUEUE_ID
        and state.get("plan_sha256") == config["prior_plan"]["sha256"]
        and state.get("state") == "halted"
        and state.get("current_job") == "final-third-control"
        and state.get("message")
        == "job final-third-control exited 1; later jobs were not run"
        and isinstance(state_jobs, list)
        and len(state_jobs) == 2
        and state_jobs[0].get("id") == "primary-completion-gate"
        and state_jobs[0].get("state") == "complete"
        and state_jobs[0].get("exit_code") == 0
        and state_jobs[1].get("id") == "final-third-control"
        and state_jobs[1].get("state") == "failed"
        and state_jobs[1].get("exit_code") == 1
    )
    if not terminal:
        raise RecoveryEvidenceError("prior state is not the exact terminal halt")
    prior_success = state_jobs[0].get("success_sha256")
    if prior_success != PRIMARY_SUCCESS_SHA256:
        raise RecoveryEvidenceError("prior completion-gate proof identity differs")

    manifest = load_object(paths["manifest"], "prior screen manifest")
    contract = manifest.get("contract")
    expected_schedule = [
        {"arm": "both", "index": 1, "seed": 42},
        {"arm": "both", "index": 2, "seed": 43},
        {"arm": "both", "index": 3, "seed": 44},
    ]
    if not isinstance(contract, dict):
        raise RecoveryEvidenceError("prior screen contract is missing")
    settings = contract.get("settings")
    rewards = contract.get("rewards")
    if (
        manifest.get("schema_version") != 1
        or contract.get("screen_profile") != "control-final"
        or contract.get("prefix") != config["prefix"]
        or Path(str(contract.get("out_dir", ""))).resolve() != config["screen_dir"]
        or contract.get("requested_steps") != 12_000_000_000
        or contract.get("final_steps") != 11_999_903_744
        or contract.get("rollout_quantum") != 131_072
        or contract.get("schedule") != expected_schedule
        or not isinstance(settings, dict)
        or settings.get("eval_episodes") != "10000"
        or settings.get("min_eval_games") != "10001"
        or contract.get("warm", {}).get("sha256") != NETBLOCK_SHA256
        or not isinstance(rewards, dict)
        or rewards.get("both", {}).get("reward_sha256") != R0_REWARD_SHA256
    ):
        raise RecoveryEvidenceError("prior screen is not the exact stopped R0 contract")

    status = load_object(paths["status"], "prior screen status")
    if (
        status.get("schema_version") != 1
        or status.get("state") != "failed"
        or status.get("current_index") != 1
        or status.get("current_arm") != "both"
        or status.get("current_seed") != 42
        or status.get("completed_arms") != 0
        or status.get("exit_code") != 1
        or status.get("screen_manifest_sha256")
        != config["prior_screen_manifest"]["sha256"]
        or status.get("message") != "screen stopped before all arms passed"
    ):
        raise RecoveryEvidenceError("prior screen status is not the exact failure")

    result = load_object(paths["result"], "prior rejected result")
    checkpoint = paths["checkpoint"]
    if (
        result.get("schema_version") != 2
        or result.get("tag") != f"{config['prefix']}-both-s42"
        or result.get("arm") != "both"
        or result.get("seed") != 42
        or result.get("trainer_complete") is not True
        or result.get("acceptance_pass") is not False
        or result.get("acceptance_failures") != [EXPECTED_FAILURE]
    ):
        raise RecoveryEvidenceError(
            "10,000-versus-10,001 is not the only terminal failure"
        )
    if (
        result.get("screen_manifest_sha256")
        != config["prior_screen_manifest"]["sha256"]
        or result.get("reward_sha256") != R0_REWARD_SHA256
        or Path(str(result.get("checkpoint", ""))).resolve() != checkpoint
        or result.get("checkpoint_bytes") != config["prior_checkpoint"]["bytes"]
        or result.get("checkpoint_sha256") != config["prior_checkpoint"]["sha256"]
    ):
        raise RecoveryEvidenceError("prior result identity differs from its evidence")
    log_sha = result.get("log_sha256")
    if (
        not isinstance(result.get("log"), str)
        or require_sha(log_sha, "prior result log SHA-256") != log_sha
    ):
        raise RecoveryEvidenceError("prior result does not bind its original log")
    require_integrity_zero(result.get("train_metrics"), "train")
    require_integrity_zero(result.get("eval_metrics"), "eval")
    eval_n = result["eval_metrics"].get("n")
    if (
        isinstance(eval_n, bool)
        or not isinstance(eval_n, (int, float))
        or eval_n != 10000
    ):
        raise RecoveryEvidenceError(
            "prior evaluation did not finish exactly 10,000 games"
        )
    train_n = result["train_metrics"].get("n")
    if (
        isinstance(train_n, bool)
        or not isinstance(train_n, (int, float))
        or not math.isfinite(float(train_n))
        or train_n <= 0
    ):
        raise RecoveryEvidenceError("prior training completion metrics are invalid")

    if expected_complete.exists():
        raise RecoveryEvidenceError("prior screen completion proof exists")
    for seed in (43, 44):
        result_path = (
            config["screen_dir"] / f"{config['prefix']}-both-s{seed}.result.json"
        )
        if result_path.exists():
            raise RecoveryEvidenceError(f"prior seed {seed} result exists")

    return {
        "schema_version": SCHEMA_VERSION,
        "prior_queue_id": PRIOR_QUEUE_ID,
        "prior_plan_sha256": config["prior_plan"]["sha256"],
        "prior_state_sha256": config["prior_state"]["sha256"],
        "prior_screen_manifest_sha256": config["prior_screen_manifest"]["sha256"],
        "prior_screen_status_sha256": config["prior_screen_status"]["sha256"],
        "prior_result_sha256": config["prior_result"]["sha256"],
        "prior_checkpoint_sha256": config["prior_checkpoint"]["sha256"],
        "prior_checkpoint_bytes": config["prior_checkpoint"]["bytes"],
        "requested_steps": 12_000_000_000,
        "completed_steps": 11_999_903_744,
        "learner_seed": 42,
        "observed_eval_games": 10_000,
        "old_minimum_eval_games": 10_001,
        "new_minimum_eval_games": 10_000,
        "unstarted_seeds": [43, 44],
        "integrity_counters_zero": True,
        "prior_completion_absent": True,
        "gpu_compute_pids_empty": True,
        "result_reuse_authorized": False,
        "in_place_restart_authorized": False,
        "reward_promotion_authorized": False,
        "milestone_evaluation_authorized": False,
        "warning": WARNING,
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
        report = recovery_report(config)
        if args.write_proof is not None:
            proof = under(
                args.write_proof.expanduser().resolve(),
                config["recovery_root_path"],
                "recovery proof",
            )
            atomic_json(proof, report)
        elif args.validate_proof is not None:
            proof = under(
                args.validate_proof.expanduser().resolve(),
                config["recovery_root_path"],
                "recovery proof",
            )
            if load_object(proof, "recovery proof") != report:
                raise RecoveryEvidenceError("recovery proof differs from live evidence")
        print(json.dumps(report, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, RecoveryEvidenceError, ValueError) as exc:
        print(f"vacation overflow recovery validation failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
