#!/usr/bin/env python3
"""Strict, read-only integrity audit for completed pre-exact-action recovery logs.

This lineage predates exact joint-action execution, so ``illegal_frac`` is a
historical diagnostic rather than an acceptance field. Every reward-corruption,
non-finite, component-ledger, engine-error, and demo-fallback counter that was
valid in the recovery lineage must nevertheless be present, finite, and exactly
zero in every populated machine-readable panel.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
from typing import Any, Iterable


PREFIX = b"PUFFER_ENV_JSON "
HARD_INTEGRITY_KEYS = (
    "reward_clip_frac",
    "reward_clip_frac_nonzero",
    "reward_clip_excess",
    "reward_clip_signed_delta",
    "reward_clipped_samples_per_episode",
    "reward_clip_terminal_samples_per_episode",
    "reward_clip_nonterminal_samples_per_episode",
    "reward_nonfinite_frac",
    "reward_nonfinite_samples_per_episode",
    "reward_clip_episodes",
    "reward_nonfinite_episodes",
    "reward_component_mismatch_samples_per_episode",
    "reward_component_nonfinite_samples_per_episode",
    "error_episodes",
    "demo_fallbacks",
)
HISTORICAL_DIAGNOSTIC_KEYS = ("illegal_frac",)


class AuditError(ValueError):
    """A recovery log is incomplete, malformed, or violates its zero budget."""


def _number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AuditError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise AuditError(f"{label} must be finite")
    return result


def _integer(value: Any, label: str, *, minimum: int = 0) -> int:
    number = _number(value, label)
    result = int(number)
    if number != result or result < minimum:
        raise AuditError(f"{label} must be an integer >= {minimum}")
    return result


def _binary(value: Any, label: str) -> int:
    result = _integer(value, label)
    if result not in (0, 1):
        raise AuditError(f"{label} must be 0 or 1")
    return result


def _reject_json_constant(path: Path, line_number: int, token: str) -> None:
    raise AuditError(
        f"{path}:{line_number}: invalid JSON constant in PUFFER_ENV_JSON: {token}"
    )


def _reject_duplicate_keys(
    path: Path, line_number: int, pairs: list[tuple[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AuditError(
                f"{path}:{line_number}: duplicate JSON key in "
                f"PUFFER_ENV_JSON: {key}"
            )
        result[key] = value
    return result


def _file_identity(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def scan_log(path: str | Path, *, min_eval_games: int) -> dict[str, Any]:
    path = Path(path).resolve()
    if not path.is_file():
        raise AuditError(f"recovery log is missing: {path}")
    if isinstance(min_eval_games, bool) or not isinstance(min_eval_games, int) \
            or min_eval_games <= 0:
        raise AuditError("min_eval_games must be a positive integer")
    identity_before = _file_identity(path)

    digest = hashlib.sha256()
    machine_panels = 0
    empty_panels = 0
    train_panels = 0
    eval_panels = 0
    final_reprints = 0
    maximum_eval_games = 0
    previous_steps: int | None = None
    maximum_steps = 0
    diagnostics = {
        key: {"min": None, "max": None, "nonzero_panels": 0}
        for key in HISTORICAL_DIAGNOSTIC_KEYS
    }

    with path.open("rb") as source:
        for line_number, raw_line in enumerate(source, 1):
            digest.update(raw_line)
            if not raw_line.startswith(PREFIX):
                continue
            machine_panels += 1
            try:
                text = raw_line[len(PREFIX):].decode("utf-8")
                panel = json.loads(
                    text,
                    parse_constant=lambda token: _reject_json_constant(
                        path, line_number, token
                    ),
                    object_pairs_hook=lambda pairs: _reject_duplicate_keys(
                        path, line_number, pairs
                    ),
                )
            except AuditError:
                raise
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise AuditError(
                    f"{path}:{line_number}: invalid PUFFER_ENV_JSON: {exc}"
                ) from exc
            if not isinstance(panel, dict):
                raise AuditError(
                    f"{path}:{line_number}: PUFFER_ENV_JSON is not an object"
                )

            schema = _integer(
                panel.get("_puffer_schema"),
                f"{path}:{line_number} schema",
            )
            if schema < 2:
                raise AuditError(f"{path}:{line_number}: telemetry schema {schema} < 2")
            steps = _integer(
                panel.get("_puffer_agent_steps"),
                f"{path}:{line_number} agent steps",
            )
            if previous_steps is not None and steps < previous_steps:
                raise AuditError(
                    f"{path}:{line_number}: agent steps regressed "
                    f"from {previous_steps:g} to {steps:g}"
                )
            previous_steps = steps
            maximum_steps = max(maximum_steps, steps)
            phase_eval = _binary(
                panel.get("_puffer_phase_eval"),
                f"{path}:{line_number} phase marker",
            )
            cumulative = _binary(
                panel.get("_puffer_env_cumulative"),
                f"{path}:{line_number} cumulative marker",
            )
            final_reprint = _binary(
                panel.get("_puffer_final_reprint"),
                f"{path}:{line_number} final-reprint marker",
            )
            eval_completed = _integer(
                panel.get("_puffer_eval_episodes_completed"),
                f"{path}:{line_number} completed eval games",
            )
            monitored_present = any(
                key in panel
                for key in (*HARD_INTEGRITY_KEYS, *HISTORICAL_DIAGNOSTIC_KEYS)
            )
            if "n" not in panel:
                if monitored_present or final_reprint or eval_completed:
                    raise AuditError(
                        f"{path}:{line_number}: telemetry payload lacks panel n"
                    )
                empty_panels += 1
                continue
            n = _integer(panel["n"], f"{path}:{line_number} panel n")

            has_payload = bool(
                n > 0 or monitored_present or final_reprint or eval_completed
            )
            if not has_payload:
                empty_panels += 1
                continue

            missing = [key for key in HARD_INTEGRITY_KEYS if key not in panel]
            if missing:
                raise AuditError(
                    f"{path}:{line_number}: missing hard-integrity fields: {missing}"
                )
            for key in HARD_INTEGRITY_KEYS:
                value = _number(panel[key], f"{path}:{line_number} {key}")
                if value != 0.0:
                    raise AuditError(
                        f"{path}:{line_number}: hard-integrity field {key}={value!r}"
                    )

            for key in HISTORICAL_DIAGNOSTIC_KEYS:
                if key not in panel:
                    raise AuditError(
                        f"{path}:{line_number}: missing historical diagnostic {key}"
                    )
                value = _number(panel[key], f"{path}:{line_number} {key}")
                summary = diagnostics[key]
                summary["min"] = value if summary["min"] is None else min(
                    summary["min"], value
                )
                summary["max"] = value if summary["max"] is None else max(
                    summary["max"], value
                )
                summary["nonzero_panels"] += int(value != 0.0)

            if final_reprint:
                if not phase_eval or not cumulative or n == 0:
                    raise AuditError(
                        f"{path}:{line_number}: final reprint must be a populated "
                        "cumulative eval panel"
                    )
                final_reprints += 1
            elif n > 0 and phase_eval:
                eval_panels += 1
            elif n > 0:
                train_panels += 1
            if phase_eval:
                maximum_eval_games = max(maximum_eval_games, eval_completed)

    identity_after = _file_identity(path)
    if identity_after != identity_before:
        raise AuditError(f"log changed during audit: {path}")

    if machine_panels == 0:
        raise AuditError(f"no PUFFER_ENV_JSON panels found: {path}")
    if train_panels == 0:
        raise AuditError(f"completed log has no independent train panel: {path}")
    if eval_panels == 0:
        raise AuditError(f"completed log has no independent eval panel: {path}")
    if final_reprints != 1:
        raise AuditError(
            f"completed log must have exactly one final reprint; "
            f"found {final_reprints}: {path}"
        )
    if maximum_eval_games < min_eval_games:
        raise AuditError(
            f"completed log evaluated only {maximum_eval_games} games; "
            f"requires {min_eval_games}: {path}"
        )

    return {
        "accepted": True,
        "path": str(path),
        "bytes": identity_before[2],
        "sha256": digest.hexdigest(),
        "machine_panels": machine_panels,
        "empty_panels": empty_panels,
        "train_panels": train_panels,
        "eval_panels": eval_panels,
        "final_reprints": final_reprints,
        "maximum_agent_steps": maximum_steps,
        "maximum_eval_games": maximum_eval_games,
        "historical_diagnostics": diagnostics,
    }


def audit_logs(
    paths: Iterable[str | Path], *, expected_count: int, min_eval_games: int
) -> dict[str, Any]:
    paths = [Path(path).resolve() for path in paths]
    if isinstance(expected_count, bool) or not isinstance(expected_count, int) \
            or expected_count <= 0:
        raise AuditError("expected_count must be a positive integer")
    if len(paths) != expected_count:
        raise AuditError(f"expected {expected_count} logs, received {len(paths)}")
    if len(set(paths)) != len(paths):
        raise AuditError("duplicate log path in recovery audit")
    reports = [scan_log(path, min_eval_games=min_eval_games) for path in paths]
    return {
        "schema_version": 1,
        "accepted": True,
        "lineage": "pre-exact-action-recovery",
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
        "historical_diagnostics": {
            "illegal_frac": (
                "reported but not gated for the frozen marginal-action lineage"
            )
        },
        "expected_log_count": expected_count,
        "minimum_eval_games": min_eval_games,
        "logs": reports,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("logs", nargs="+", type=Path)
    parser.add_argument("--expected-count", type=int, default=3)
    parser.add_argument("--min-eval-games", type=int, default=10000)
    args = parser.parse_args(argv)
    try:
        report = audit_logs(
            args.logs,
            expected_count=args.expected_count,
            min_eval_games=args.min_eval_games,
        )
    except (OSError, AuditError) as exc:
        print(f"recovery complete-log audit failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
