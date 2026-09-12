#!/usr/bin/env python3
"""Frozen-policy, per-game evaluation against Blood Bowl scripted bots.

This module deliberately calls only the Puffer rollout and evaluation-log APIs.
It never calls the training entrypoint or backend.train().  One native env is
used so each cumulative-log increment can be losslessly converted to one game.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
from pathlib import PurePosixPath
import subprocess
import struct
import sys
import time
from typing import Any, Iterable


STYLE_IDS = {"contact": 0, "cage": 1}
SIDE_IDS = {"home": 0, "away": 1}
RESULTS = {-1: "loss", 0: "draw", 1: "win"}
UINT64_MASK = (1 << 64) - 1
ROLLOUT_TRANSITION_CONTRACT = "terminal-aware-tbptt-v1"
HISTORICAL_ROLLOUT_TRANSITION_CONTRACT = "tail-bootstrap-v1"
ENTROPY_SCHEDULE_CONTRACT = "cosine-update-index-over-total-updates-fp32-v1"
SOURCE_CLOSURE_ROOTS = (
    "puffer/bloodbowl",
    "engine/include/bb",
    "engine/src",
)
CANONICAL_SOURCE_LINKS = {
    "puffer/bloodbowl/bb": "../../engine/include/bb",
    "puffer/bloodbowl/engine": "../../engine/src",
    "engine/src/bb": "../include/bb",
}
PER_GAME_METRICS = (
    "perf", "tds_t0", "tds_t1", "score_diff", "episode_length",
    "reward_clip_episodes", "reward_nonfinite_episodes",
    "reward_clip_terminal_samples_per_episode",
    "reward_clip_nonterminal_samples_per_episode",
    "reward_clipped_samples_per_episode", "reward_clip_excess",
    "reward_nonfinite_samples_per_episode",
    "reward_component_nonfinite_samples_per_episode",
    "error_episodes", "demo_episodes", "demo_fallbacks", "illegal_frac",
)
INTEGRITY_METRICS = PER_GAME_METRICS[5:]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(Path(path).rglob("*")):
        if child.is_symlink() or (not child.is_dir() and not child.is_file()):
            raise RuntimeError(f"runtime tree contains unsupported entry: {child}")
        if child.is_dir():
            continue
        relative = child.relative_to(path).as_posix()
        digest.update(relative.encode()); digest.update(b"\0")
        digest.update(str(child.stat().st_size).encode()); digest.update(b"\0")
        digest.update(sha256_file(child).encode()); digest.update(b"\n")
    return digest.hexdigest()


def load_backend_source_registry(path: Path) -> tuple[str, ...]:
    """Load the ordered path list used to compile and identify Puffer."""
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        raise RuntimeError("compiled backend source registry is empty")
    result = []
    seen = set()
    for line_number, relative in enumerate(lines, 1):
        candidate = PurePosixPath(relative)
        if (not relative or candidate.is_absolute()
                or candidate.as_posix() != relative
                or any(part in ("", ".", "..") for part in candidate.parts)):
            raise RuntimeError(
                f"unsafe compiled backend source at line {line_number}: {relative!r}")
        if relative in seen:
            raise RuntimeError(f"duplicate compiled backend source: {relative}")
        seen.add(relative)
        result.append(relative)
    return tuple(result)


def backend_source_hash(puffer_root: Path, sources: Iterable[str]) -> str:
    """Match install_puffer_env.sh's ordered `sha256sum | sha256sum` digest."""
    payload = b"".join(
        f"{sha256_file(puffer_root / relative)}  {relative}\n".encode()
        for relative in sources
    )
    return hashlib.sha256(payload).hexdigest()


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def _validate_real_directory(root: Path, relative: str) -> Path:
    current = root
    if current.is_symlink() or not current.is_dir():
        raise RuntimeError(f"source closure root is not a real directory: {root}")
    for part in PurePosixPath(relative).parts:
        current = current / part
        if current.is_symlink() or not current.is_dir():
            raise RuntimeError(
                f"source closure parent is missing, non-directory, or symlink: {current}")
    return current


def source_closure(root: Path) -> dict[str, Any]:
    """Recompute the closed model-facing source identity without link traversal."""
    root = root.absolute()
    directories = {
        relative: _validate_real_directory(root, relative)
        for relative in SOURCE_CLOSURE_ROOTS
    }
    actual_links: dict[str, str] = {}
    entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source_relative, directory in directories.items():
        for child in sorted(directory.rglob("*")):
            relative = child.relative_to(root).as_posix()
            if child.is_symlink():
                actual_links[relative] = os.readlink(child)
                continue
            if child.is_dir():
                continue
            if not child.is_file():
                raise RuntimeError(
                    f"source closure contains an unsupported entry: {child}")
            if relative in seen:
                raise RuntimeError(f"duplicate source closure file: {relative}")
            seen.add(relative)
            entries.append({
                "path": relative,
                "bytes": child.stat().st_size,
                "sha256": sha256_file(child),
            })
    if actual_links != CANONICAL_SOURCE_LINKS:
        raise RuntimeError(f"canonical source links mismatch: {actual_links!r}")
    root_resolved = root.resolve()
    for relative, target in CANONICAL_SOURCE_LINKS.items():
        link = root / relative
        expected = (root_resolved / Path(relative).parent / target).resolve()
        if (os.readlink(link) != target or link.resolve() != expected
                or root_resolved not in expected.parents):
            raise RuntimeError(f"canonical source link was retargeted: {relative}")
    entries.sort(key=lambda entry: entry["path"])
    digest = hashlib.sha256()
    for entry in entries:
        digest.update(entry["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(entry["bytes"]).encode("ascii"))
        digest.update(b"\0")
        digest.update(entry["sha256"].encode("ascii"))
        digest.update(b"\n")
    return {
        "roots": list(SOURCE_CLOSURE_ROOTS),
        "canonical_links": dict(CANONICAL_SOURCE_LINKS),
        "files": len(entries),
        "bytes": sum(entry["bytes"] for entry in entries),
        "sha256": digest.hexdigest(),
        "entries": entries,
    }


def validate_source_closures(*, runtime_root: Path, snapshot_root: Path,
                             expected_sha256: str) -> dict[str, Any]:
    if (len(expected_sha256) != 64
            or any(character not in "0123456789abcdef"
                   for character in expected_sha256)):
        raise RuntimeError("expected source closure SHA-256 is invalid")
    runtime = source_closure(runtime_root)
    snapshot = source_closure(snapshot_root)
    if runtime != snapshot:
        raise RuntimeError("runtime and snapshot source closures differ")
    if runtime["sha256"] != expected_sha256:
        raise RuntimeError("source closure SHA-256 mismatch")
    return runtime


def cumulative_delta(current_mean: float, current_n: int,
                     previous_mean: float, previous_n: int) -> float:
    added = current_n - previous_n
    if added != 1:
        raise RuntimeError(
            f"per-game evaluation requires exactly one new game, got {added}")
    return current_mean * current_n - previous_mean * previous_n


def exact_integer_total_from_float32_mean(mean: float, n: int) -> int:
    """Invert the native one-env integer sum / float32 count without a tolerance.

    Integer additions are exact below 2**24. Require the proposed sum to
    reproduce the observed float32 mean and neither adjacent sum to do so.
    This contract is for integer episode lengths, never integrity fractions.
    """
    if not math.isfinite(mean) or mean < 0 or n < 0 or n >= 2**24:
        raise RuntimeError("native count outside exact float32 reconstruction range")
    if n == 0:
        if mean != 0:
            raise RuntimeError("nonzero native mean with no completed games")
        return 0
    total = round(mean * n)
    if total < 0 or total >= 2**24:
        raise RuntimeError("native integer total outside exact float32 range")
    def emitted(value: int) -> float:
        return struct.unpack("f", struct.pack("f", value / n))[0]
    if emitted(total) != mean:
        raise RuntimeError("native episode length mean does not encode an integer total")
    if emitted(total - 1) == mean or emitted(total + 1) == mean:
        raise RuntimeError("native episode length mean is ambiguous")
    return total


def game_from_cumulative(*, logs: dict[str, Any], previous: dict[str, float],
                         bot_team: int, style: str, base_seed: int,
                         checkpoint_sha256: str,
                         runtime_identity_sha256: str,
                         max_decisions: int) -> dict[str, Any]:
    required = ("env/n", *(f"env/{key}" for key in PER_GAME_METRICS))
    missing = [key for key in required if key not in logs]
    if missing:
        raise RuntimeError(f"native evaluation log is missing required fields: {missing}")
    n = int(logs["env/n"])
    previous_n = int(previous.get("n", 0))
    values = {}
    for key in PER_GAME_METRICS:
        values[key] = cumulative_delta(
            float(logs[f"env/{key}"]), n,
            float(previous.get(key, 0.0)), previous_n)
    nonfinite = {key: value for key, value in values.items()
                 if not math.isfinite(value)}
    if nonfinite:
        raise RuntimeError(f"game metrics are non-finite: {sorted(nonfinite)}")

    home_tds = int(round(values["tds_t0"]))
    away_tds = int(round(values["tds_t1"]))
    if abs(values["tds_t0"] - home_tds) > 1e-4 or abs(values["tds_t1"] - away_tds) > 1e-4:
        raise RuntimeError("cumulative TD metrics did not decode to integral scores")
    home_outcome = (home_tds > away_tds) - (home_tds < away_tds)
    expected_home_perf = 1.0 if home_outcome > 0 else 0.5 if home_outcome == 0 else 0.0
    if abs(values["perf"] - expected_home_perf) > 1e-4:
        raise RuntimeError("terminal perf disagrees with the decoded home/away score")
    if abs(values["score_diff"] - (home_tds - away_tds)) > 1e-4:
        raise RuntimeError("score_diff disagrees with the decoded home/away score")
    bad_integrity = {key: values[key] for key in INTEGRITY_METRICS
                     if values[key] != 0.0}
    if bad_integrity:
        raise RuntimeError(f"game failed integrity gates: {bad_integrity}")
    length_mean = float(logs["env/episode_length"])
    previous_length_mean = float(previous.get("episode_length", 0.0))
    decisions = (
        exact_integer_total_from_float32_mean(length_mean, n)
        - exact_integer_total_from_float32_mean(previous_length_mean, previous_n))
    if decisions < 0:
        raise RuntimeError("native cumulative episode length decreased")
    if decisions >= max_decisions:
        raise RuntimeError(
            f"game reached max_decisions={max_decisions}; W/D/L is truncated")
    learner_team = 1 - bot_team
    learner_tds, opponent_tds = ((home_tds, away_tds) if learner_team == 0
                                 else (away_tds, home_tds))
    outcome = (learner_tds > opponent_tds) - (learner_tds < opponent_tds)
    episode = n
    identity = {
        "checkpoint_sha256": checkpoint_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        "style": style,
        "learner_side": "home" if learner_team == 0 else "away",
        "base_seed": base_seed,
        "episode": episode,
    }
    return {
        "schema_version": 1,
        **identity,
        "trace_identity": canonical_sha256(identity),
        # bbe_reset_match increments episode before seeding the first game.
        "game_rng_seed": (base_seed + episode * 7919) & UINT64_MASK,
        "procgen_rng_seed": (base_seed * 2654435761 + episode) & UINT64_MASK,
        "decisions": decisions,
        "length_reconstruction": {
            "contract": "unique-integer-total-float32-division-v1",
            "current_mean": length_mean, "current_n": n,
            "previous_mean": previous_length_mean, "previous_n": previous_n,
        },
        "learner_team": learner_team,
        "bot_team": bot_team,
        "home_tds": home_tds,
        "away_tds": away_tds,
        "learner_tds": learner_tds,
        "opponent_tds": opponent_tds,
        "td_diff": learner_tds - opponent_tds,
        "result": RESULTS[outcome],
        "match_points": 1.0 if outcome > 0 else 0.5 if outcome == 0 else 0.0,
    }


def update_previous(previous: dict[str, float], logs: dict[str, Any]) -> None:
    previous["n"] = float(logs.get("env/n", 0))
    for key in PER_GAME_METRICS:
        previous[key] = float(logs.get(f"env/{key}", 0.0))


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = list(records)
    counts = {name: sum(row["result"] == name for row in rows)
              for name in ("win", "draw", "loss")}
    n = len(rows)
    return {
        "games": n,
        **counts,
        "win_rate": counts["win"] / n if n else None,
        "draw_rate": counts["draw"] / n if n else None,
        "loss_rate": counts["loss"] / n if n else None,
        "match_score": sum(row["match_points"] for row in rows) / n if n else None,
        "mean_td_diff": sum(row["td_diff"] for row in rows) / n if n else None,
    }


def configure_args(args: dict[str, Any], *, learner_side: str, style: str,
                   seed: int, max_decisions: int) -> dict[str, Any]:
    bot_team = 1 - SIDE_IDS[learner_side]
    args["reset_state"] = False
    args["seed"] = seed
    args.setdefault("nccl_id", b"")
    args["train"]["seed"] = seed
    args["train"]["horizon"] = 1
    args["train"]["minibatch_size"] = 2
    # Native construction allocates training buffers even for rollout-only use.
    # A fractional training replay ratio truncates this single minibatch to zero.
    args["train"]["replay_ratio"] = 1.0
    args["vec"]["num_buffers"] = 1
    args["vec"]["total_agents"] = 2
    args["vec"]["num_frozen_banks"] = 0
    args["vec"]["frozen_bank_pct"] = 0.0
    args.setdefault("selfplay", {})["enabled"] = 0
    args["env"].update({
        "seed": seed,
        "max_decisions": max_decisions,
        "demo_reset_pct": 0.0,
        "scripted_opponent": 1,
        "scripted_opponent_type": STYLE_IDS[style],
        "scripted_opponent_team": bot_team,
        "scripted_bank_tag": 0,
        "scripted_bank_mask": 0,
    })
    return args


def json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"effective config contains unsupported {type(value).__name__}")


def load_config_without_runner_cli(pufferl: Any) -> dict[str, Any]:
    saved = sys.argv
    try:
        sys.argv = [saved[0]]
        return pufferl.load_config("bloodbowl")
    finally:
        sys.argv = saved


def run_cell(*, pufferl: Any, backend: Any, args: dict[str, Any], checkpoint: Path,
             checkpoint_sha256: str, runtime_identity_sha256: str, style: str,
             learner_side: str, seed: int, games: int, max_decisions: int,
             max_rollouts_per_game: int, max_seconds_per_cell: float,
             on_game: Any) -> list[dict[str, Any]]:
    bot_team = 1 - SIDE_IDS[learner_side]
    runner = backend.create_pufferl(args)
    try:
        backend.load_weights(runner, str(checkpoint))
        backend.set_evaluation_mode(runner, True)
        previous = {"n": 0.0, **{key: 0.0 for key in PER_GAME_METRICS}}
        records = []
        cell_started = time.monotonic()
        rollouts_since_game = 0
        while len(records) < games:
            if time.monotonic() - cell_started > max_seconds_per_cell:
                raise TimeoutError(
                    f"cell exceeded {max_seconds_per_cell:g} seconds")
            if rollouts_since_game >= max_rollouts_per_game:
                raise TimeoutError(
                    f"game exceeded {max_rollouts_per_game} rollout steps")
            backend.rollouts(runner)
            rollouts_since_game += 1
            logs = dict(pufferl.unroll_nested_dict(backend.eval_log(runner)))
            n = int(logs.get("env/n", 0))
            if n == int(previous["n"]):
                continue
            row = game_from_cumulative(
                logs=logs, previous=previous, bot_team=bot_team, style=style,
                base_seed=seed, checkpoint_sha256=checkpoint_sha256,
                runtime_identity_sha256=runtime_identity_sha256,
                max_decisions=max_decisions)
            on_game(row)
            records.append(row)
            update_previous(previous, logs)
            rollouts_since_game = 0
        return records
    finally:
        backend.close(runner)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--games-per-cell", required=True, type=int)
    parser.add_argument("--max-decisions", type=int, default=4096)
    parser.add_argument("--max-rollouts-per-game", type=int, default=8192)
    parser.add_argument("--max-seconds-per-cell", type=float, default=3600.0)
    parser.add_argument("--gpu-id", type=int, default=0)
    parser.add_argument("--seed", action="append", required=True, type=int)
    parser.add_argument("--style", action="append", choices=STYLE_IDS,
                        default=None)
    parser.add_argument("--learner-side", action="append", choices=SIDE_IDS,
                        default=None)
    parser.add_argument("--allow-qualification", action="store_true",
                        help="accept a qualification-only checkpoint sidecar")
    parser.add_argument(
        "--rollout-transition-contract", default=ROLLOUT_TRANSITION_CONTRACT,
        choices=(ROLLOUT_TRANSITION_CONTRACT, HISTORICAL_ROLLOUT_TRANSITION_CONTRACT),
        help="pin inference memory semantics; the historical contract requires a bridge reason")
    parser.add_argument("--source-snapshot-root", required=True, type=Path)
    parser.add_argument("--source-closure-sha256", required=True)
    parser.add_argument(
        "--runtime-root", type=Path,
        help="explicit runtime repository root; defaults to this evaluator's repository")
    parser.add_argument(
        "--runtime-bridge-reason",
        help="evaluate on a different compiled module without rewriting lineage; "
             "the reason and both identities are frozen in the manifest")
    return parser.parse_args(argv)


def validate_memory_contract(actual: str, expected: str, bridge_reason: str | None) -> None:
    if expected not in (ROLLOUT_TRANSITION_CONTRACT, HISTORICAL_ROLLOUT_TRANSITION_CONTRACT):
        raise RuntimeError("unsupported inference rollout-transition contract")
    if actual != expected:
        raise RuntimeError("compiled rollout-transition contract is wrong")
    if expected == HISTORICAL_ROLLOUT_TRANSITION_CONTRACT and not (bridge_reason or '').strip():
        raise RuntimeError("historical inference memory contract requires a runtime bridge reason")


def external_helper_paths(evaluator_path: Path) -> dict[str, Path]:
    tools = evaluator_path.resolve().parent
    paths = {"checkpoint_lineage": tools / "checkpoint_lineage.py"}
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise RuntimeError(f"external evaluator helper is missing: {missing}")
    return paths


def main(argv: list[str] | None = None) -> int:
    cli = parse_args(argv)
    if (cli.games_per_cell <= 0 or cli.max_decisions <= 0 or cli.gpu_id < 0 or
            cli.max_rollouts_per_game <= 0 or cli.max_seconds_per_cell <= 0 or
            any(seed < 0 or seed > UINT64_MASK for seed in cli.seed)):
        raise SystemExit(
            "game and bound arguments must be positive; seeds must be uint64")
    checkpoint = cli.checkpoint.resolve()
    output = cli.output.resolve()
    if not checkpoint.is_file():
        raise SystemExit(f"checkpoint not found: {checkpoint}")
    if output.exists():
        raise SystemExit(f"refusing to overwrite output: {output}")

    evaluator_path = Path(__file__).resolve()
    root = (cli.runtime_root.resolve() if cli.runtime_root is not None
            else evaluator_path.parents[1])
    if not root.is_dir() or root.is_symlink():
        raise SystemExit("runtime-root must be an existing real directory")
    source_identity = validate_source_closures(
        runtime_root=root,
        snapshot_root=cli.source_snapshot_root.resolve(),
        expected_sha256=cli.source_closure_sha256)
    vendor = root / "vendor/PufferLib"
    subprocess.run(
        ["/usr/bin/bash", str(root / "tools/install_puffer_env.sh"),
         "--check", str(vendor)],
        cwd=root, check=True)
    visible = os.environ.get("CUDA_VISIBLE_DEVICES")
    if visible not in (None, "", str(cli.gpu_id)):
        raise SystemExit(
            f"CUDA_VISIBLE_DEVICES={visible!r} conflicts with --gpu-id={cli.gpu_id}")
    os.environ["CUDA_VISIBLE_DEVICES"] = str(cli.gpu_id)
    sys.path.insert(0, str(root / "tools"))
    from puffer_cuda_runtime import (
        begin_cuda_runtime_preflight, finish_cuda_runtime_preflight,
        validate_cuda_runtime_evidence,
    )
    cuda_runtime, cuda_evidence = begin_cuda_runtime_preflight()
    sys.path.insert(0, str(root / "vendor" / "PufferLib"))
    from pufferlib import _C as backend
    from pufferlib import pufferl
    cuda_evidence = finish_cuda_runtime_preflight(cuda_runtime, cuda_evidence)
    validate_cuda_runtime_evidence(cuda_evidence)
    helpers = external_helper_paths(evaluator_path)
    # The historical runtime's lineage helper predates recurrent-contract
    # validation. Re-select the evaluator package after importing the runtime's
    # CUDA helper and native backend, then prove both helper origins explicitly.
    sys.path.insert(0, str(evaluator_path.parent))
    lineage_module = importlib.import_module("checkpoint_lineage")
    if Path(lineage_module.__file__).resolve() != helpers["checkpoint_lineage"]:
        raise SystemExit("evaluation helper import escaped the external pinned package")
    lineage_digest = lineage_module.lineage_digest
    validate_lineage = lineage_module.validate_lineage
    sha256 = sha256_file

    if not bool(getattr(backend, "gpu", False)):
        raise SystemExit("frozen scripted evaluation requires native CUDA")
    if int(getattr(backend, "precision_bytes", 0)) != 4:
        raise SystemExit("frozen scripted evaluation requires an fp32 build")
    if getattr(backend, "env_name", None) != "bloodbowl":
        raise SystemExit("imported native module is not bloodbowl")
    validate_memory_contract(
        getattr(backend, "rollout_transition_contract", None),
        cli.rollout_transition_contract, cli.runtime_bridge_reason)
    if getattr(
        backend, "entropy_schedule_contract", None
    ) != ENTROPY_SCHEDULE_CONTRACT:
        raise SystemExit("compiled entropy-schedule contract is wrong")

    checkpoint_sha = sha256_file(checkpoint)
    module = Path(backend.__file__).resolve()
    module_sha = sha256_file(module)
    backend_registry = root / "training/puffer_compiled_backend_sources.txt"
    backend_sources = load_backend_source_registry(backend_registry)
    on_disk_backend_sha = backend_source_hash(
        root / "vendor/PufferLib", backend_sources)
    compiled_backend_sha = str(
        getattr(backend, "exact_action_source_hash", "<missing>"))
    if compiled_backend_sha != on_disk_backend_sha:
        raise SystemExit(
            "compiled module differs from the canonical backend source digest")
    installed_environment_sha = (
        root / "vendor/PufferLib/ocean/bloodbowl/.content_hash"
    ).read_text(encoding="utf-8").strip()
    compiled_environment_sha = str(
        getattr(backend, "environment_source_hash", "<missing>"))
    if compiled_environment_sha != installed_environment_sha:
        raise SystemExit(
            "compiled module differs from the installed environment source digest")
    if cli.runtime_bridge_reason is not None:
        cli.runtime_bridge_reason = cli.runtime_bridge_reason.strip()
        if not cli.runtime_bridge_reason or len(cli.runtime_bridge_reason) > 200:
            raise SystemExit("runtime-bridge-reason must contain 1..200 characters")
    expected_runtime = None if cli.runtime_bridge_reason else {
        "compiled_module_sha256": module_sha}
    lineage = validate_lineage(
        checkpoint, expected=expected_runtime,
        require_eligible=False, recurrent_contract_mode="inference")
    if not cli.allow_qualification and not lineage['ancestry']['eligible']:
        raise SystemExit("qualification-only checkpoint requires --allow-qualification")
    identity = {
        "source_closure_sha256": source_identity["sha256"],
        "source_closure_roots": source_identity["roots"],
        "source_closure_files": source_identity["files"],
        "source_closure_bytes": source_identity["bytes"],
        "canonical_source_links": source_identity["canonical_links"],
        "source_snapshot_root": str(cli.source_snapshot_root.resolve()),
        "conversion_config_sha256": sha256(root / "puffer/config/bloodbowl.ini"),
        "config_tree_sha256": tree_sha256(root / "vendor/PufferLib/config"),
        "default_config_sha256": sha256(root / "vendor/PufferLib/config/default.ini"),
        "env_config_sha256": sha256(root / "vendor/PufferLib/config/bloodbowl.ini"),
        "compiled_module_path": str(module),
        "compiled_module_sha256": module_sha,
        "compiled_backend_source_registry_sha256": sha256_file(backend_registry),
        "compiled_backend_sources": list(backend_sources),
        "compiled_backend_sources_sha256": on_disk_backend_sha,
        "compiled_backend_sha256": compiled_backend_sha,
        "installed_environment_source_sha256": installed_environment_sha,
        "compiled_environment_source_sha256": compiled_environment_sha,
        "rollout_transition_contract": str(backend.rollout_transition_contract),
        "entropy_schedule_contract": str(backend.entropy_schedule_contract),
        "package_init_sha256": sha256(root / "vendor/PufferLib/pufferlib/__init__.py"),
        "pufferl_sha256": sha256(root / "vendor/PufferLib/pufferlib/pufferl.py"),
        "models_sha256": sha256(root / "vendor/PufferLib/pufferlib/models.py"),
        "native_backend_sha256": sha256(root / "vendor/PufferLib/src/pufferlib.cu"),
        "native_bindings_sha256": sha256(root / "vendor/PufferLib/src/bindings.cu"),
        "native_vecenv_sha256": sha256(root / "vendor/PufferLib/src/vecenv.h"),
        "eval_runner_path": str(evaluator_path),
        "eval_runner_sha256": sha256_file(evaluator_path),
        "external_checkpoint_lineage_path": str(helpers["checkpoint_lineage"]),
        "external_checkpoint_lineage_sha256": sha256_file(
            helpers["checkpoint_lineage"]),
        "runtime_root": str(root),
    }
    identity_sha = canonical_sha256(identity)
    styles = cli.style or list(STYLE_IDS)
    sides = cli.learner_side or list(SIDE_IDS)
    if (len(set(cli.seed)) != len(cli.seed) or
            len(set(styles)) != len(styles) or
            len(set(sides)) != len(sides)):
        raise SystemExit("duplicate seeds, styles, or learner sides are not allowed")
    cells = [{"style": style, "learner_side": side, "seed": seed}
             for style in styles for side in sides for seed in cli.seed]
    base_args = load_config_without_runner_cli(pufferl)
    effective_configs = []
    for cell in cells:
        configured = configure_args(
            copy.deepcopy(base_args), max_decisions=cli.max_decisions, **cell)
        effective_configs.append({**cell, "args": json_safe(configured)})
    manifest = {
        "schema_version": 1,
        "mode": "native_frozen_scripted_per_game",
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": checkpoint_sha,
        "checkpoint_lineage_sha256": lineage_digest(lineage),
        "checkpoint_qualification_only": bool(
            lineage.get("ancestry", {}).get("qualification_only")),
        "checkpoint_implementation": lineage.get("implementation"),
        "checkpoint_rollout_transition_contract": lineage.get(
            "compatibility", {}).get("rollout_transition_contract"),
        "runtime_bridge_reason": cli.runtime_bridge_reason,
        "games_per_cell": cli.games_per_cell,
        "max_decisions": cli.max_decisions,
        "max_rollouts_per_game": cli.max_rollouts_per_game,
        "max_seconds_per_cell": cli.max_seconds_per_cell,
        "cells": cells,
        "effective_configs": effective_configs,
        "runtime_identity": identity,
        "runtime_identity_sha256": identity_sha,
        "cuda_runtime_evidence": cuda_evidence,
        "argv": sys.argv,
    }
    output.mkdir(parents=True)
    (output / "MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n")

    records: list[dict[str, Any]] = []
    expected_games = len(cells) * cli.games_per_cell
    progress_path = output / "PROGRESS.json"
    completed_count = 0

    def atomic_progress(last_row: dict[str, Any]) -> None:
        progress = {
            "schema_version": 1,
            "completed_games": completed_count,
            "expected_games": expected_games,
            "last_trace_identity": last_row["trace_identity"],
        }
        temporary = progress_path.with_suffix(".json.tmp")
        with temporary.open("w") as progress_sink:
            progress_sink.write(
                json.dumps(progress, indent=2, sort_keys=True) + "\n")
            progress_sink.flush()
            os.fsync(progress_sink.fileno())
        os.replace(temporary, progress_path)

    with (output / "GAMES.jsonl").open("x") as sink:
        for cell in cells:
            args = configure_args(
                copy.deepcopy(base_args), max_decisions=cli.max_decisions,
                **cell)

            def write_game(row: dict[str, Any]) -> None:
                nonlocal completed_count
                sink.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
                sink.flush()
                os.fsync(sink.fileno())
                completed_count += 1
                atomic_progress(row)

            rows = run_cell(
                pufferl=pufferl, backend=backend, args=args,
                checkpoint=checkpoint, checkpoint_sha256=checkpoint_sha,
                runtime_identity_sha256=identity_sha, games=cli.games_per_cell,
                max_decisions=cli.max_decisions,
                max_rollouts_per_game=cli.max_rollouts_per_game,
                max_seconds_per_cell=cli.max_seconds_per_cell,
                on_game=write_game,
                **cell)
            records.extend(rows)
    per_cell = []
    for cell in cells:
        subset = [row for row in records
                  if row["style"] == cell["style"]
                  and row["learner_side"] == cell["learner_side"]
                  and row["base_seed"] == cell["seed"]]
        per_cell.append({**cell, **summarize(subset)})
    complete = {
        "schema_version": 1,
        "manifest_sha256": sha256_file(output / "MANIFEST.json"),
        "games_sha256": sha256_file(output / "GAMES.jsonl"),
        "expected_games": expected_games,
        "aggregate": summarize(records),
        "per_cell": per_cell,
    }
    (output / "COMPLETE.json").write_text(
        json.dumps(complete, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print(json.dumps(complete, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
