#!/usr/bin/env python3
"""Incrementally fail a Blood Bowl run on a hard-integrity panel.

The accepted value for every registered metric is exactly zero. This is an
operational detection guard, not a statistical analyzer: malformed telemetry,
log replacement/truncation, and a pre-existing failure artifact all fail closed.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import time
from pathlib import Path
from typing import Any


HARD_INTEGRITY_KEYS = (
    "illegal_frac",
    "reward_clip_frac",
    "reward_clip_frac_nonzero",
    "reward_clip_excess",
    "reward_nonfinite_frac",
    "reward_clip_episodes",
    "reward_nonfinite_episodes",
    "reward_component_mismatch_samples_per_episode",
    "reward_component_nonfinite_samples_per_episode",
    "error_episodes",
    "demo_fallbacks",
)
PREFIX = b"PUFFER_ENV_JSON "


class IntegrityFailure(RuntimeError):
    """A zero-budget integrity or telemetry-contract violation."""


@dataclasses.dataclass(frozen=True)
class CheckResult:
    new_panels: int
    total_panels: int
    latest_agent_steps: float | None
    offset: int


def _utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _write_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _fail(
    failure_path: Path,
    log_path: Path,
    kind: str,
    message: str,
    *,
    offset: int | None = None,
    metrics: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": kind,
        "message": message,
        "log": str(log_path.resolve()),
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
        "failed_utc": _utc_now(),
    }
    if offset is not None:
        payload["offset"] = offset
    if metrics is not None:
        payload["metrics"] = metrics
    if not failure_path.exists():
        _write_atomic(failure_path, payload)
    raise IntegrityFailure(message)


def _number(value: Any) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, (int, float))
        and math.isfinite(float(value))
    )


def check_log(
    log_path: Path,
    state_path: Path,
    failure_path: Path,
    *,
    max_panel_silence_seconds: float = 180.0,
    now: float | None = None,
    enforce_liveness: bool = True,
) -> CheckResult:
    log_path = Path(log_path)
    state_path = Path(state_path)
    failure_path = Path(failure_path)
    if (
        isinstance(max_panel_silence_seconds, bool)
        or not isinstance(max_panel_silence_seconds, (int, float))
        or not math.isfinite(float(max_panel_silence_seconds))
        or max_panel_silence_seconds <= 0
    ):
        raise ValueError("max_panel_silence_seconds must be finite and positive")
    observed_now = time.time() if now is None else float(now)
    if not math.isfinite(observed_now):
        raise ValueError("now must be finite")

    if failure_path.exists():
        raise IntegrityFailure(
            f"existing live-integrity failure requires a new run: {failure_path}"
        )
    if not log_path.is_file():
        _fail(failure_path, log_path, "log_missing", f"trainer log is missing: {log_path}")

    stat = log_path.stat()
    state: dict[str, Any]
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            _fail(
                failure_path,
                log_path,
                "guard_state_invalid",
                f"live-integrity state is unreadable: {exc}",
            )
        if state.get("schema_version") != 1:
            _fail(
                failure_path,
                log_path,
                "guard_state_invalid",
                "live-integrity state schema is not 1",
            )
        if tuple(state.get("hard_integrity_keys", ())) != HARD_INTEGRITY_KEYS:
            _fail(
                failure_path,
                log_path,
                "guard_state_invalid",
                "live-integrity state hard-key registry drifted",
            )
        if state.get("log_device") != stat.st_dev or state.get("log_inode") != stat.st_ino:
            _fail(
                failure_path,
                log_path,
                "log_replaced",
                "trainer log device/inode changed during the arm",
            )
        offset = state.get("offset")
        if isinstance(offset, bool) or not isinstance(offset, int) or offset < 0:
            _fail(
                failure_path,
                log_path,
                "guard_state_invalid",
                "live-integrity state offset is invalid",
            )
        if stat.st_size < offset:
            _fail(
                failure_path,
                log_path,
                "log_truncated",
                f"trainer log shrank from guarded offset {offset} to {stat.st_size}",
            )
        total_panels = state.get("total_panels")
        if (
            isinstance(total_panels, bool)
            or not isinstance(total_panels, int)
            or total_panels < 0
        ):
            _fail(
                failure_path,
                log_path,
                "guard_state_invalid",
                "live-integrity panel count is invalid",
            )
        latest_steps = state.get("latest_agent_steps")
        if latest_steps is not None and not _number(latest_steps):
            _fail(
                failure_path,
                log_path,
                "guard_state_invalid",
                "live-integrity latest step is invalid",
            )
        last_panel_seen = state.get("last_panel_seen_unix")
        if not _number(last_panel_seen):
            _fail(
                failure_path,
                log_path,
                "guard_state_invalid",
                "live-integrity panel-liveness timestamp is invalid",
            )
    else:
        state = {
            "schema_version": 1,
            "log_device": stat.st_dev,
            "log_inode": stat.st_ino,
            "offset": 0,
            "total_panels": 0,
            "latest_agent_steps": None,
            "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
            "last_panel_seen_unix": observed_now,
        }
        offset = 0
        total_panels = 0
        latest_steps = None
        last_panel_seen = observed_now

    new_panels = 0
    next_offset = offset
    with log_path.open("rb") as stream:
        stream.seek(offset)
        while True:
            line_start = stream.tell()
            line = stream.readline()
            if not line:
                break
            if not line.endswith(b"\n"):
                # The trainer may still be writing this record. Re-read it on
                # the next poll rather than accepting a partial JSON prefix.
                if not enforce_liveness:
                    _fail(
                        failure_path,
                        log_path,
                        "log_incomplete_tail",
                        "complete trainer log has an unterminated final log "
                        f"record at byte {line_start}",
                        offset=line_start,
                    )
                break
            next_offset = stream.tell()
            marker = line.find(PREFIX)
            if marker < 0:
                continue
            raw = line[marker + len(PREFIX):].strip()
            try:
                panel = json.loads(raw)
            except (UnicodeError, json.JSONDecodeError) as exc:
                _fail(
                    failure_path,
                    log_path,
                    "panel_malformed",
                    f"machine panel at byte {line_start} is malformed: {exc}",
                    offset=line_start,
                )
            if not isinstance(panel, dict):
                _fail(
                    failure_path,
                    log_path,
                    "panel_malformed",
                    f"machine panel at byte {line_start} is not an object",
                    offset=line_start,
                )
            schema = panel.get("_puffer_schema")
            if not _number(schema) or int(schema) < 2:
                _fail(
                    failure_path,
                    log_path,
                    "panel_schema_invalid",
                    f"machine panel at byte {line_start} lacks schema >= 2",
                    offset=line_start,
                )
            steps = panel.get("_puffer_agent_steps")
            if not _number(steps) or float(steps) < 0:
                _fail(
                    failure_path,
                    log_path,
                    "panel_steps_invalid",
                    f"machine panel at byte {line_start} has invalid agent steps",
                    offset=line_start,
                )
            # Before an episode completes, Puffer's schema-2 phase contract
            # intentionally emits only _puffer_* metadata. Consume that record
            # without resetting the integrity-panel liveness clock. Once any
            # environment metric is present, the complete hard registry is
            # mandatory.
            if not any(not key.startswith("_") for key in panel):
                continue
            missing = [key for key in HARD_INTEGRITY_KEYS if key not in panel]
            if missing:
                _fail(
                    failure_path,
                    log_path,
                    "hard_integrity_missing",
                    f"machine panel is missing hard-integrity keys: {missing}",
                    offset=line_start,
                    metrics={key: "<missing>" for key in missing},
                )
            nonfinite = {
                key: panel[key]
                for key in HARD_INTEGRITY_KEYS
                if not _number(panel[key])
            }
            if nonfinite:
                # JSON cannot atomically encode NaN/Infinity in failure
                # evidence, so preserve a stable textual representation.
                printable = {key: repr(value) for key, value in nonfinite.items()}
                _fail(
                    failure_path,
                    log_path,
                    "hard_integrity_nonfinite",
                    f"machine panel has non-finite integrity values: {printable}",
                    offset=line_start,
                    metrics=printable,
                )
            nonzero = {
                key: panel[key]
                for key in HARD_INTEGRITY_KEYS
                if float(panel[key]) != 0.0
            }
            if nonzero:
                _fail(
                    failure_path,
                    log_path,
                    "hard_integrity_nonzero",
                    f"zero-budget integrity violation: {nonzero}",
                    offset=line_start,
                    metrics=nonzero,
                )
            latest_steps = float(steps)
            last_panel_seen = observed_now
            total_panels += 1
            new_panels += 1

    if enforce_liveness:
        silence = observed_now - float(last_panel_seen)
        if silence < 0 or silence >= float(max_panel_silence_seconds):
            _fail(
                failure_path,
                log_path,
                "panel_liveness_exhausted",
                "no complete machine integrity panel for "
                f"{silence:.1f}s (budget {max_panel_silence_seconds:.1f}s)",
                offset=next_offset,
            )

    saved = {
        "schema_version": 1,
        "log_device": stat.st_dev,
        "log_inode": stat.st_ino,
        "offset": next_offset,
        "total_panels": total_panels,
        "latest_agent_steps": latest_steps,
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
        "last_panel_seen_unix": last_panel_seen,
        "updated_utc": _utc_now(),
    }
    _write_atomic(state_path, saved)
    return CheckResult(new_panels, total_panels, latest_steps, next_offset)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--failure", type=Path, required=True)
    parser.add_argument(
        "--max-panel-silence-seconds", type=float, default=180.0)
    parser.add_argument(
        "--complete-log",
        action="store_true",
        help="validate a stopped trainer's complete log without a live silence gate",
    )
    args = parser.parse_args()
    try:
        result = check_log(
            args.log,
            args.state,
            args.failure,
            max_panel_silence_seconds=args.max_panel_silence_seconds,
            enforce_liveness=not args.complete_log,
        )
    except IntegrityFailure as exc:
        print(f"LIVE INTEGRITY FAILURE: {exc}")
        return 2
    print(json.dumps(dataclasses.asdict(result), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
