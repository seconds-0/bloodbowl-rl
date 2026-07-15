#!/usr/bin/env python3
"""Continuously stream the newest stable Blood Bowl training checkpoint.

The follower is deliberately outside the trainer. It discovers only checkpoint
directories with immutable RUN_MANIFEST.json files, waits for a native blob to
be complete and stable, converts it atomically into a Torch-only viewer cache,
and starts ``server.py`` for a bounded match cycle. When the server exits after
that cycle, discovery runs again and the next match uses the newest checkpoint.

The default matchup is newest checkpoint versus that run's frozen warm-start.
This makes visual progress legible without changing training, reward state,
opponent pools, checkpoint files, or the production fallback artifacts.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import fcntl
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


@dataclasses.dataclass(frozen=True)
class Candidate:
    native_path: Path
    manifest_path: Path
    tag: str
    seed: int
    step: int
    rollout_quantum: int
    expected_bytes: int
    warm_path: Path
    warm_bytes: int
    warm_sha256: str
    run_order: int


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp.{os.getpid()}")
    with temporary.open("w", encoding="utf-8") as target:
        json.dump(value, target, indent=2, sort_keys=True, allow_nan=False)
        target.write("\n")
        target.flush()
        os.fsync(target.fileno())
    os.replace(temporary, path)


def safe_label(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-._")
    return cleaned[:96] or "checkpoint"


def _manifest_candidate(
    manifest_path: Path, native_path: Path, manifest: dict[str, Any]
) -> Candidate | None:
    try:
        if manifest.get("mode") != "native_static_pool_reward_ablation":
            return None
        if int(manifest["schema_version"]) != 1:
            return None
        expected = int(manifest["expected_checkpoint_bytes"])
        rollout = int(manifest["rollout_quantum"])
        step = int(native_path.stem)
        stat = native_path.stat()
        warm = Path(str(manifest["warm"])).expanduser().resolve()
        warm_bytes = int(manifest["warm_bytes"])
        warm_sha = str(manifest["warm_sha256"]).lower()
        run_order = int(manifest_path.parent.name)
        warm_size = warm.stat().st_size
        tag = str(manifest["tag"])
        seed = int(manifest["seed"])
    except (KeyError, TypeError, ValueError, OSError):
        return None
    if (
        stat.st_size != expected
        or step <= rollout
        or expected <= 0
        or warm_bytes <= 0
        or run_order < 0
        or not warm.is_file()
        or warm_size != warm_bytes
        or not re.fullmatch(r"[0-9a-f]{64}", warm_sha)
    ):
        return None
    return Candidate(
        native_path=native_path.resolve(),
        manifest_path=manifest_path.resolve(),
        tag=tag,
        seed=seed,
        step=step,
        rollout_quantum=rollout,
        expected_bytes=expected,
        warm_path=warm,
        warm_bytes=warm_bytes,
        warm_sha256=warm_sha,
        run_order=run_order,
    )


def discover_candidates(checkpoint_root: Path) -> list[Candidate]:
    """Return manifested, full-size, post-bootstrap native checkpoints."""
    candidates: list[Candidate] = []
    if not checkpoint_root.is_dir():
        return candidates
    for manifest_path in checkpoint_root.glob("*/RUN_MANIFEST.json"):
        try:
            manifest = load_json(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        for native_path in manifest_path.parent.glob("[0-9]*.bin"):
            candidate = _manifest_candidate(manifest_path, native_path, manifest)
            if candidate is not None:
                candidates.append(candidate)
    # Run directories are launcher-generated monotonic numeric IDs. Select the
    # newest run by that immutable identity, then its greatest completed step;
    # copying/touching an old checkpoint must never roll BBTV backward.
    return sorted(candidates, key=lambda item: (item.run_order, item.step))


def stable_native(path: Path, expected_bytes: int, seconds: float) -> os.stat_result:
    before = path.stat()
    if before.st_size != expected_bytes:
        raise RuntimeError(
            f"checkpoint size changed or is incomplete: {path} "
            f"({before.st_size} != {expected_bytes})"
        )
    if seconds > 0:
        time.sleep(seconds)
    after = path.stat()
    identity_before = (
        before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns
    )
    identity_after = (
        after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns
    )
    if identity_before != identity_after:
        raise RuntimeError(f"checkpoint changed during stability gate: {path}")
    return after


def _conversion_label(candidate: Candidate, digest: str) -> str:
    return _bounded_torch_label(
        candidate.tag,
        f"-step{candidate.step:012d}-{digest[:10]}_torch.bin",
    )


def _baseline_label(candidate: Candidate, digest: str) -> str:
    return _hashed_torch_label(f"baseline-{candidate.warm_path.stem}", digest)


def _hashed_torch_label(prefix: str, digest: str) -> str:
    suffix = f"-{digest[:10]}_torch.bin"
    return _bounded_torch_label(prefix, suffix)


def _bounded_torch_label(prefix: str, suffix: str) -> str:
    prefix_budget = 96 - len(suffix)
    bounded_prefix = safe_label(prefix)[:prefix_budget].rstrip("-._")
    return f"{bounded_prefix or 'checkpoint'}{suffix}"


def convert_native(
    source: Path,
    expected_bytes: int,
    label: str,
    cache_dir: Path,
    converter_python: Path,
    converter_script: Path,
    config_path: Path,
    stability_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    stable_native(source, expected_bytes, stability_seconds)
    source_sha = sha256_file(source)
    output = cache_dir / label
    metadata_path = output.with_suffix(output.suffix + ".json")
    conversion_identity = {
        "schema_version": 1,
        "obs_size": 2782,
        "converter_sha256": sha256_file(converter_script),
        "config_sha256": sha256_file(config_path),
    }
    if output.is_file() and metadata_path.is_file():
        try:
            metadata = load_json(metadata_path)
            if (
                metadata.get("source_sha256") == source_sha
                and metadata.get("output_sha256") == sha256_file(output)
                and metadata.get("conversion_identity") == conversion_identity
            ):
                return metadata
        except (OSError, ValueError, json.JSONDecodeError):
            # A torn metadata write should be impossible after atomic_json,
            # but manual edits or disk corruption must not pin the follower to
            # fallback forever. Rebuild the cache entry from its hashed source.
            pass

    cache_dir.mkdir(parents=True, exist_ok=True)
    temporary = cache_dir / f".{label}.tmp.{os.getpid()}"
    temporary.unlink(missing_ok=True)
    command = [
        str(converter_python),
        str(converter_script),
        "--to-torch",
        str(source),
        "--config",
        str(config_path),
        "--obs-size",
        "2782",
        "-o",
        str(temporary),
    ]
    environment = dict(os.environ)
    environment["CUDA_VISIBLE_DEVICES"] = ""
    try:
        completed = subprocess.run(
            command,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=environment,
            check=False,
            timeout=timeout_seconds,
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "checkpoint conversion failed: "
                f"{completed.stderr.strip() or completed.stdout.strip()}"
            )
        if not temporary.is_file() or temporary.stat().st_size <= expected_bytes:
            raise RuntimeError(
                f"converted checkpoint is missing or unexpectedly small: {temporary}"
            )
        stable_native(source, expected_bytes, 0)
        final_source_sha = sha256_file(source)
        if final_source_sha != source_sha:
            raise RuntimeError(f"checkpoint changed during conversion: {source}")
        output_sha = sha256_file(temporary)
        os.replace(temporary, output)
        metadata = {
            "schema_version": 1,
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "source": str(source),
            "source_bytes": expected_bytes,
            "source_sha256": source_sha,
            "output": str(output),
            "output_bytes": output.stat().st_size,
            "output_sha256": output_sha,
            "conversion_identity": conversion_identity,
            "converter_command": command,
            "converter_stdout": completed.stdout.strip(),
        }
        atomic_json(metadata_path, metadata)
        return metadata
    finally:
        temporary.unlink(missing_ok=True)


def prepare_pair(args: argparse.Namespace) -> dict[str, Any]:
    candidates = discover_candidates(args.checkpoint_root)
    if not candidates:
        raise RuntimeError("no stable post-bootstrap manifested checkpoint exists")
    current = candidates[-1]
    stable_native(current.warm_path, current.warm_bytes, args.stability_seconds)
    baseline_sha = sha256_file(current.warm_path)
    if baseline_sha != current.warm_sha256:
        raise RuntimeError(
            "frozen warm-start hash does not match run manifest: "
            f"{current.warm_path} ({baseline_sha} != {current.warm_sha256})"
        )
    current_sha = sha256_file(current.native_path)
    current_meta = convert_native(
        current.native_path,
        current.expected_bytes,
        _conversion_label(current, current_sha),
        args.cache_dir,
        args.converter_python,
        args.converter_script,
        args.config,
        args.stability_seconds,
        args.conversion_timeout_seconds,
    )
    baseline_meta = convert_native(
        current.warm_path,
        current.warm_bytes,
        _baseline_label(current, baseline_sha),
        args.cache_dir,
        args.converter_python,
        args.converter_script,
        args.config,
        args.stability_seconds,
        args.conversion_timeout_seconds,
    )
    if baseline_meta.get("source_sha256") != current.warm_sha256:
        raise RuntimeError("frozen warm-start changed during conversion")
    selection = {
        "schema_version": 1,
        "selected_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "mode": "latest_vs_frozen_warm",
        "tag": current.tag,
        "seed": current.seed,
        "step": current.step,
        "run_manifest": str(current.manifest_path),
        "checkpoint_a": current_meta,
        "checkpoint_b": baseline_meta,
    }
    atomic_json(args.state_dir / "selection.json", selection)
    return selection


def prune_cache(cache_dir: Path, selected: set[Path], keep: int) -> None:
    checkpoints = sorted(
        cache_dir.glob("*_torch.bin"),
        key=lambda path: path.stat().st_mtime_ns,
        reverse=True,
    )
    retained = 0
    for checkpoint in checkpoints:
        if checkpoint.resolve() in selected or retained < keep:
            retained += 1
            continue
        checkpoint.unlink(missing_ok=True)
        checkpoint.with_suffix(checkpoint.suffix + ".json").unlink(missing_ok=True)


def server_command(
    args: argparse.Namespace, checkpoint_a: Path, checkpoint_b: Path
) -> list[str]:
    command = [
        str(args.server_python),
        str(args.server_script),
        "--ckpt-a",
        str(checkpoint_a),
        "--ckpt-b",
        str(checkpoint_b),
        "--port",
        str(args.port),
        "--pace",
        str(args.pace),
        "--max-games",
        str(args.games_per_cycle),
    ]
    if args.sample:
        command.append("--sample")
    return command


def choose_stream_pair(
    prepared: tuple[Path, Path] | None,
    last_successful: tuple[Path, Path] | None,
    quarantined: set[tuple[Path, Path]],
    fallback: tuple[Path, Path] | None,
) -> tuple[Path, Path] | None:
    """Prefer an unquarantined candidate, then a proven pair, then fallback."""
    for pair in (prepared, last_successful, fallback):
        if pair is not None and pair not in quarantined:
            return pair
    return None


def run_forever(args: argparse.Namespace) -> int:
    args.state_dir.mkdir(parents=True, exist_ok=True)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    lock_path = args.state_dir / ".follow_latest.lock"
    with lock_path.open("w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"another BBTV follower holds {lock_path}", file=sys.stderr)
            return 2

        last_successful_pair: tuple[Path, Path] | None = None
        quarantined_pairs: set[tuple[Path, Path]] = set()
        failures = 0
        while True:
            prepared_pair: tuple[Path, Path] | None = None
            try:
                selection = prepare_pair(args)
                prepared_pair = (
                    Path(selection["checkpoint_a"]["output"]),
                    Path(selection["checkpoint_b"]["output"]),
                )
            except Exception as exc:
                print(f"BBTV discovery/conversion warning: {exc}", file=sys.stderr)

            fallback = (
                (args.fallback_a, args.fallback_b)
                if args.fallback_a and args.fallback_b
                else None
            )
            pair = choose_stream_pair(
                prepared_pair,
                last_successful_pair,
                quarantined_pairs,
                fallback,
            )
            if pair is None:
                failures += 1
                time.sleep(min(args.retry_seconds * failures, 60))
                continue

            command = server_command(args, *pair)
            status = {
                "schema_version": 1,
                "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
                "checkpoint_a": str(pair[0]),
                "checkpoint_b": str(pair[1]),
                "server_command": command,
            }
            atomic_json(args.state_dir / "server_status.json", status)
            print("BBTV FOLLOW " + json.dumps(status, sort_keys=True), flush=True)
            try:
                completed = subprocess.run(
                    command,
                    cwd=args.server_script.parent,
                    check=False,
                    timeout=args.server_timeout_seconds,
                )
                return_code = completed.returncode
            except subprocess.TimeoutExpired:
                return_code = 124
                print(
                    "BBTV server exceeded its cycle timeout; child was "
                    "terminated",
                    file=sys.stderr,
                    flush=True,
                )
            status["completed_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
            status["exit_code"] = return_code
            atomic_json(args.state_dir / "server_status.json", status)
            selected = {path.resolve() for path in pair}
            prune_cache(args.cache_dir, selected, args.keep_converted)
            if return_code != 0:
                quarantined_pairs.add(pair)
                if pair == last_successful_pair:
                    last_successful_pair = None
                failures += 1
                print(
                    f"BBTV server exited {return_code}; quarantining "
                    "that pair and reverting to the last successful stream",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(min(args.retry_seconds * failures, 60))
            else:
                last_successful_pair = pair
                failures = 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-root", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--converter-python", type=Path, required=True)
    parser.add_argument("--converter-script", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--server-python", type=Path, required=True)
    parser.add_argument("--server-script", type=Path, required=True)
    parser.add_argument("--fallback-a", type=Path)
    parser.add_argument("--fallback-b", type=Path)
    parser.add_argument("--port", type=int, default=8787)
    parser.add_argument("--pace", type=float, default=0.6)
    parser.add_argument("--games-per-cycle", type=int, default=2)
    parser.add_argument(
        "--sample",
        action="store_true",
        help="sample policy actions instead of using greedy argmax",
    )
    parser.add_argument("--stability-seconds", type=float, default=1.0)
    parser.add_argument("--retry-seconds", type=float, default=5.0)
    parser.add_argument("--conversion-timeout-seconds", type=float, default=300.0)
    parser.add_argument("--server-timeout-seconds", type=float, default=7200.0)
    parser.add_argument("--keep-converted", type=int, default=24)
    parser.add_argument(
        "--select-only",
        action="store_true",
        help="prepare and print one selection without launching server.py",
    )
    args = parser.parse_args(argv)
    args.checkpoint_root = args.checkpoint_root.expanduser().resolve()
    args.state_dir = args.state_dir.expanduser().resolve()
    args.cache_dir = (
        args.cache_dir.expanduser().resolve()
        if args.cache_dir
        else args.state_dir / "converted"
    )
    for name in ("converter_python", "server_python"):
        # Preserve venv launcher symlinks. resolve() turns ``.venv/bin/python``
        # into the bare uv-managed interpreter and silently loses site-packages.
        path = getattr(args, name).expanduser().absolute()
        if not path.is_file():
            parser.error(f"--{name.replace('_', '-')} does not exist: {path}")
        setattr(args, name, path)
    for name in ("converter_script", "config", "server_script"):
        path = getattr(args, name).expanduser().resolve()
        if not path.is_file():
            parser.error(f"--{name.replace('_', '-')} does not exist: {path}")
        setattr(args, name, path)
    for name in ("fallback_a", "fallback_b"):
        path = getattr(args, name)
        if path is not None:
            path = path.expanduser().resolve()
            if not path.is_file():
                parser.error(f"--{name.replace('_', '-')} does not exist: {path}")
            setattr(args, name, path)
    if (args.fallback_a is None) != (args.fallback_b is None):
        parser.error("--fallback-a and --fallback-b must be provided together")
    if not 1 <= args.port <= 65535:
        parser.error("--port must be in 1..65535")
    if (
        args.pace <= 0
        or args.games_per_cycle <= 0
        or args.conversion_timeout_seconds <= 0
        or args.server_timeout_seconds <= 0
    ):
        parser.error("pace, cycle size, and subprocess timeouts must be positive")
    if args.stability_seconds < 0 or args.keep_converted < 2:
        parser.error("stability must be non-negative and cache must keep >=2")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.select_only:
        try:
            selection = prepare_pair(args)
        except Exception as exc:
            print(f"BBTV selection failed: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(selection, indent=2, sort_keys=True, allow_nan=False))
        return 0
    return run_forever(args)


if __name__ == "__main__":
    raise SystemExit(main())
