#!/usr/bin/env python3
"""Run a restart-validating scripted transfer matrix for a reward screen.

A completed possession/gain screen supplies four arms and two seeds; a paired
confirmation supplies R0 and one candidate. This runner converts each accepted
native checkpoint to Torch, freezes every input and conversion hash, then
evaluates every arm against both scripted opponent styles in both team
orientations. Existing artifacts are reused only after full validation; partial
or drifted artifacts fail closed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import analyze_reward_candidate_transfer as candidate_transfer
import analyze_reward_screen


FULL_ARMS = ("both", "possession_only", "gain_only", "neither")
SEEDS = (42, 43)
BOT_TYPES = (0, 1)
BOT_TEAMS = (0, 1)
EXPECTED_NATIVE_BYTES = 16_066_560


class RunnerError(ValueError):
    pass


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
        raise RunnerError(f"invalid {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RunnerError(f"{label} must be a JSON object: {path}")
    return value


def run_checked(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command, text=True, stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT, check=False, **kwargs,
    )
    if result.returncode != 0:
        raise RunnerError(
            f"command exited {result.returncode}: {command!r}\n"
            f"{result.stdout[-4000:]}")
    return result


def screen_checkpoints(
    screen_dir: Path, expected_sha: str,
) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    report = analyze_reward_screen.analyze_screen(
        screen_dir, analyze_reward_screen.DEFAULT_METRICS,
        expected_screen_sha=expected_sha,
    )
    if not report["screen"]["completion"].get("present"):
        raise RunnerError("source screen has no verified completion proof")
    profile = report["screen"]["profile"]
    if profile == "possession-gain":
        arms = FULL_ARMS
    elif profile == "paired-confirmation":
        candidate = report["screen"].get("candidate_arm")
        if candidate not in FULL_ARMS[1:]:
            raise RunnerError("paired source screen has an invalid candidate")
        arms = ("both", candidate)
    else:
        raise RunnerError(
            "candidate transfer requires a possession-gain or "
            "paired-confirmation screen"
        )
    prefix = report["screen"]["prefix"]
    checkpoints: dict[str, dict[str, Any]] = {arm: {} for arm in arms}
    for arm in arms:
        for seed in SEEDS:
            result_path = screen_dir / f"{prefix}-{arm}-s{seed}.result.json"
            result = load_object(result_path, f"screen result {arm}/seed {seed}")
            native = Path(str(result.get("checkpoint", ""))).expanduser().resolve()
            if not native.is_file():
                raise RunnerError(f"missing native checkpoint: {native}")
            if native.stat().st_size != EXPECTED_NATIVE_BYTES:
                raise RunnerError(f"wrong native checkpoint size: {native}")
            observed = sha256(native)
            if observed != result.get("checkpoint_sha256"):
                raise RunnerError(
                    f"native checkpoint hash drift for {arm}/seed {seed}")
            checkpoints[arm][str(seed)] = {
                "screen_result": str(result_path),
                "screen_result_sha256": sha256(result_path),
                "native": str(native),
                "native_bytes": native.stat().st_size,
                "native_sha256": observed,
            }
    return checkpoints, arms


def convert_checkpoints(
    root: Path, out_dir: Path, checkpoints: dict[str, dict[str, Any]],
    arms: tuple[str, ...],
) -> None:
    python = root / "vendor/PufferLib/.venv/bin/python"
    converter = root / "training/convert_checkpoint.py"
    config = root / "puffer/config/bloodbowl.ini"
    for arm in arms:
        for seed in SEEDS:
            record = checkpoints[arm][str(seed)]
            output = out_dir / "converted" / f"{arm}-s{seed}-torch.bin"
            output.parent.mkdir(parents=True, exist_ok=True)
            metadata = output.with_suffix(output.suffix + ".json")
            if output.exists() or metadata.exists():
                if not output.is_file() or not metadata.is_file():
                    raise RunnerError(f"partial conversion artifact: {output}")
                saved = load_object(metadata, "conversion metadata")
                expected = {
                    "schema_version": 1,
                    "source": record["native"],
                    "source_sha256": record["native_sha256"],
                    "converter_sha256": sha256(converter),
                    "config_sha256": sha256(config),
                    "obs_size": 2782,
                    "output": str(output),
                    "output_sha256": sha256(output),
                }
                if any(saved.get(key) != value for key, value in expected.items()):
                    raise RunnerError(f"conversion metadata drift: {metadata}")
            else:
                temporary = output.with_suffix(output.suffix + f".tmp.{os.getpid()}")
                result = run_checked([
                    str(python), str(converter), "--to-torch", record["native"],
                    "--config", str(config), "--obs-size", "2782",
                    "-o", str(temporary),
                ], cwd=root)
                if not temporary.is_file() or temporary.stat().st_size < 1_000_000:
                    raise RunnerError(f"converter produced invalid output: {temporary}")
                os.replace(temporary, output)
                atomic_json(metadata, {
                    "schema_version": 1,
                    "source": record["native"],
                    "source_sha256": record["native_sha256"],
                    "converter": str(converter),
                    "converter_sha256": sha256(converter),
                    "config": str(config),
                    "config_sha256": sha256(config),
                    "obs_size": 2782,
                    "output": str(output),
                    "output_bytes": output.stat().st_size,
                    "output_sha256": sha256(output),
                    "converter_stdout": result.stdout.strip(),
                    "created_utc": utc_now(),
                })
            record.update({
                "torch": str(output),
                "torch_bytes": output.stat().st_size,
                "torch_sha256": sha256(output),
                "conversion_metadata": str(metadata),
                "conversion_metadata_sha256": sha256(metadata),
            })


def implementation_identity(root: Path) -> dict[str, str]:
    python = root / "vendor/PufferLib/.venv/bin/python"
    module_result = run_checked([
        str(python), "-c", "from pufferlib import _C; print(_C.__file__)",
    ], cwd=root / "vendor/PufferLib")
    module = Path(module_result.stdout.strip()).resolve()
    if not module.is_file():
        raise RunnerError(f"imported module is missing: {module}")
    return {
        "config_sha256": sha256(root / "puffer/config/bloodbowl.ini"),
        "compiled_module_sha256": sha256(module),
        "pufferl_sha256": sha256(root / "vendor/PufferLib/pufferlib/pufferl.py"),
        "launcher_sha256": sha256(root / "tools/eval_vs_contact_bot.sh"),
    }


def freeze_manifest(
    path: Path, root: Path, screen_dir: Path, expected_screen_sha: str,
    checkpoints: dict[str, dict[str, Any]], arms: tuple[str, ...],
) -> dict[str, Any]:
    candidates = list(arms[1:])
    preference = [
        arm for arm in ("neither", "possession_only", "gain_only")
        if arm in candidates
    ]
    core = {
        "schema_version": 1,
        "matrix_id": path.parent.name,
        "source_screen": str(screen_dir),
        "source_screen_sha256": expected_screen_sha,
        "reference_arm": "both",
        "candidate_arms": candidates,
        # Remove both terms first; among one-term recipes prefer the settled-state
        # possession annuity over the outcome-priced gain event (D147/D178).
        "preference_order": preference,
        "seeds": list(SEEDS),
        "bot_types": list(BOT_TYPES),
        "bot_teams": list(BOT_TEAMS),
        "settings": {
            "requested_train_steps": 131_072,
            "eval_episodes": 1_000,
            "min_eval_games": 1_000,
        },
        "implementation": implementation_identity(root),
        "conversion": {
            "converter_sha256": sha256(root / "training/convert_checkpoint.py"),
            "config_sha256": sha256(root / "puffer/config/bloodbowl.ini"),
            "obs_size": 2782,
            "bias_contract": "native-to-torch zero-fills biases",
        },
        "checkpoints": checkpoints,
        "gates": {
            "mean_score_delta_min": -0.02,
            "cell_score_delta_min": -0.05,
            "max_champion_td_relative_drop": 0.20,
            "max_bot_td_relative_rise": 0.20,
        },
    }
    if path.exists():
        recorded = load_object(path, "transfer manifest")
        observed_core = {key: recorded.get(key) for key in core}
        if observed_core != core:
            raise RunnerError("existing transfer manifest differs from recomputed plan")
        return recorded
    payload = {**core, "created_utc": utc_now()}
    atomic_json(path, payload)
    return payload


def write_status(
    path: Path, state: str, completed: int, total: int, message: str,
) -> None:
    atomic_json(path, {
        "schema_version": 1, "state": state, "completed_cells": completed,
        "total_cells": total,
        "message": message, "updated_utc": utc_now(), "pid": os.getpid(),
    })


def completed_from_status(path: Path) -> int:
    if not path.is_file():
        return 0
    try:
        value = load_object(path, "transfer status").get("completed_cells", 0)
        return value if isinstance(value, int) and not isinstance(value, bool) else 0
    except (OSError, RunnerError):
        return 0


def run_matrix(root: Path, out_dir: Path, plan: dict[str, Any]) -> None:
    launcher = root / "tools/eval_vs_contact_bot.sh"
    status_path = out_dir / "TRANSFER_STATUS.json"
    completed = 0
    arms = (plan["reference_arm"], *plan["candidate_arms"])
    total = len(arms) * len(SEEDS) * len(BOT_TYPES) * len(BOT_TEAMS)
    write_status(
        status_path, "running", completed, total, "validating transfer cells"
    )
    for arm in arms:
        for seed in SEEDS:
            checkpoint = Path(plan["checkpoints"][arm][str(seed)]["torch"])
            for bot_type in BOT_TYPES:
                for bot_team in BOT_TEAMS:
                    log = out_dir / f"{arm}-s{seed}-b{bot_type}-t{bot_team}.log"
                    if log.exists():
                        candidate_transfer._validate_cell(
                            log, {**plan, "_arms": list(arms)},
                            arm, seed, bot_type, bot_team,
                        )
                    else:
                        write_status(
                            status_path, "running", completed, total,
                            f"running {arm}/seed {seed}/bot {bot_type}/team {bot_team}",
                        )
                        env = {
                            **os.environ,
                            "SEED": str(seed),
                            "BOT_TYPE": str(bot_type),
                            "BOT_TEAM": str(bot_team),
                            "EVAL_EPISODES": "1000",
                            "MIN_EVAL_GAMES": "1000",
                        }
                        result = subprocess.run(
                            ["bash", str(launcher), str(checkpoint), "131072", str(log)],
                            cwd=root, env=env, check=False,
                        )
                        if result.returncode != 0:
                            raise RunnerError(
                                f"transfer cell exited {result.returncode}: {log}")
                        candidate_transfer._validate_cell(
                            log, {**plan, "_arms": list(arms)},
                            arm, seed, bot_type, bot_team,
                        )
                    completed += 1
                    write_status(
                        status_path, "running", completed, total, "cell validated"
                    )


def complete_transfer(out_dir: Path) -> None:
    analysis_path = out_dir / "ANALYSIS.json"
    report = candidate_transfer.analyze(out_dir)
    atomic_json(analysis_path, report)
    complete_path = out_dir / "TRANSFER_COMPLETE.json"
    core = {
        "schema_version": 1,
        "transfer_manifest_sha256": sha256(out_dir / "TRANSFER_MANIFEST.json"),
        "analysis_sha256": sha256(analysis_path),
        "recommended_confirmation_arm": report["recommendation"]["arm"],
        "cells": [
            {"log": row["log"], "sha256": row["log_sha256"]}
            for row in report["runs"]
        ],
    }
    if complete_path.exists():
        recorded = load_object(complete_path, "transfer completion")
        if {key: recorded.get(key) for key in core} != core:
            raise RunnerError("existing transfer completion is stale")
    else:
        atomic_json(complete_path, {**core, "completed_utc": utc_now()})
    write_status(
        out_dir / "TRANSFER_STATUS.json", "complete", len(report["runs"]),
        len(report["runs"]),
        f"matrix complete; confirmation candidate={report['recommendation']['arm']}",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--screen-dir", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, required=True)
    parser.add_argument("--expected-screen-sha", required=True)
    parser.add_argument("--plan-only", action="store_true")
    args = parser.parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    screen_dir = args.screen_dir.expanduser().resolve()
    out_dir = args.out_dir.expanduser().resolve()
    arms = FULL_ARMS
    out_dir.mkdir(parents=True, exist_ok=True)
    lock_path = out_dir / ".transfer.lock"
    try:
        with lock_path.open("a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise RunnerError("another transfer runner holds the lock") from exc
            checkpoints, arms = screen_checkpoints(
                screen_dir, args.expected_screen_sha.lower())
            # Share the exact one-GPU lock used by reward training. Requiring a
            # completed source screen above prevents stealing the lock during a
            # brief inter-arm gap.
            gpu_lock_path = Path("/tmp/bloodbowl-rl-reward-ablation.lock")
            with gpu_lock_path.open("a+") as gpu_lock:
                try:
                    fcntl.flock(gpu_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as exc:
                    raise RunnerError(
                        "training/evaluation GPU lock is already held") from exc
                convert_checkpoints(root, out_dir, checkpoints, arms)
                plan = freeze_manifest(
                    out_dir / "TRANSFER_MANIFEST.json", root, screen_dir,
                    args.expected_screen_sha.lower(), checkpoints, arms,
                )
                if args.plan_only:
                    print(
                        "TRANSFER PLAN VERIFIED: "
                        f"{out_dir / 'TRANSFER_MANIFEST.json'}")
                    return 0
                run_matrix(root, out_dir, plan)
                complete_transfer(out_dir)
                print(f"TRANSFER COMPLETE: {out_dir}")
                return 0
    except (OSError, RunnerError, ValueError,
            analyze_reward_screen.AnalysisError,
            candidate_transfer.TransferError) as exc:
        status_path = out_dir / "TRANSFER_STATUS.json"
        write_status(
            status_path,
            "failed",
            completed_from_status(status_path),
            len(arms) * len(SEEDS) * len(BOT_TYPES) * len(BOT_TEAMS),
            str(exc),
        )
        print(f"candidate-transfer runner failed: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
