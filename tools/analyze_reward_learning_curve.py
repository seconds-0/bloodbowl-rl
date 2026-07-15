#!/usr/bin/env python3
"""Produce a provenance-bound learning-curve report from a Puffer train log.

The report is descriptive only.  In particular, the historical opponent banks
are part of training and are not a holdout or a checkpoint-selection set.

Puffer emits each environment metric as a mean over the dashboard panel's
completed episodes (``n``).  This matters twice for historical-bank score:
both ``hist_score_bank_*`` and ``hist_n_bank_*`` must be multiplied by ``n``
before panels are combined.  The reusable aggregation here encodes that rule.

Example (the frozen D187/D188 prefix):

  python3 tools/analyze_reward_learning_curve.py frozen.log \
      --expect-sha256 7fa83012f4bc9f0beb5a74d3cf7c3ea8618b93259d339ae865ee3f9246c17b5f \
      --max-step 6005587968 --endpoint-step 6000000000 \
      --window-steps 500000000 > curve.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ENV_JSON_PREFIX = b"PUFFER_ENV_JSON "
BANK_N_RE = re.compile(r"^hist_n_bank_(\d+)$")
BANK_SCORE_RE = re.compile(r"^hist_score_bank_(\d+)$")

# Every mean is combined by completed episodes, not by dashboard-panel count.
MEAN_METRICS = (
    "episode_return",
    "tds",
    "perf",
    "draw_rate",
    "score_diff",
    "possession_rate",
    "ball_fwd_adv",
    "ball_path_len",
    "illegal_frac",
    "blocks_thrown",
    "blocks_vs_carrier",
    "carrier_block_frac",
    "block_1d_frac",
    "block_2d_frac",
    "block_2dred_frac",
    "block_3d_frac",
    "gfi_attempts",
    "pass_attempts",
    "handoff_attempts",
    "historical_winrate",
)

# These are also panel means. Multiplying by n recovers a run/window total.
INTEGRITY_METRICS = (
    "reward_clip_episodes",
    "reward_clip_excess",
    "reward_clipped_samples_per_episode",
    "reward_clip_terminal_samples_per_episode",
    "reward_clip_nonterminal_samples_per_episode",
    "reward_nonfinite_episodes",
    "reward_nonfinite_samples_per_episode",
    "error_episodes",
    "demo_episodes",
    "demo_fallbacks",
)


def _finite_number(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{label} must be finite")
    return result


def _exact_nonnegative_int(value: Any, label: str) -> int:
    number = _finite_number(value, label)
    integer = int(number)
    if number != integer or integer < 0:
        raise ValueError(f"{label} must be an exact non-negative integer")
    return integer


def _clean_float(value: float) -> float:
    # Avoid reports containing the confusing JSON value -0.0.
    return 0.0 if value == 0.0 else value


@dataclass
class Aggregate:
    panel_count: int = 0
    episode_count: int = 0
    min_step: int | None = None
    max_step: int | None = None
    metric_sums: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    metric_weights: dict[str, float] = field(default_factory=lambda: defaultdict(float))
    integrity_totals: dict[str, float] = field(
        default_factory=lambda: defaultdict(float)
    )
    bank_games: dict[int, float] = field(default_factory=lambda: defaultdict(float))
    bank_scores: dict[int, float] = field(default_factory=lambda: defaultdict(float))

    def add(self, panel: dict[str, Any]) -> None:
        n = _exact_nonnegative_int(panel["n"], "panel n")
        if n <= 0:
            raise ValueError("aggregate received an empty panel")
        step = _exact_nonnegative_int(
            panel["_puffer_agent_steps"], "_puffer_agent_steps"
        )
        self.panel_count += 1
        self.episode_count += n
        self.min_step = step if self.min_step is None else min(self.min_step, step)
        self.max_step = step if self.max_step is None else max(self.max_step, step)

        for metric in MEAN_METRICS:
            if metric not in panel:
                raise ValueError(f"schema-2 train panel is missing {metric}")
            value = _finite_number(panel[metric], metric)
            self.metric_sums[metric] += value * n
            self.metric_weights[metric] += n

        for metric in INTEGRITY_METRICS:
            if metric not in panel:
                raise ValueError(f"schema-2 train panel is missing {metric}")
            value = _finite_number(panel[metric], metric)
            if value < 0.0:
                raise ValueError(f"{metric} must be non-negative")
            self.integrity_totals[metric] += value * n

        n_by_bank: dict[int, float] = {}
        score_by_bank: dict[int, float] = {}
        for key, raw_value in panel.items():
            n_match = BANK_N_RE.match(key)
            score_match = BANK_SCORE_RE.match(key)
            if n_match:
                n_by_bank[int(n_match.group(1))] = _finite_number(raw_value, key)
            elif score_match:
                score_by_bank[int(score_match.group(1))] = _finite_number(
                    raw_value, key
                )
        if not n_by_bank or set(n_by_bank) != set(score_by_bank):
            raise ValueError(
                "historical bank score/count fields are absent or mismatched"
            )
        for bank in sorted(n_by_bank):
            games_rate = n_by_bank[bank]
            score_rate = score_by_bank[bank]
            if games_rate < 0.0 or score_rate < 0.0:
                raise ValueError(f"historical bank {bank} rates must be non-negative")
            if score_rate > games_rate + 1e-6:
                raise ValueError(f"historical bank {bank} score exceeds its game count")
            # Both inputs are already divided by panel n. Restore their totals.
            self.bank_games[bank] += games_rate * n
            self.bank_scores[bank] += score_rate * n

    def report(self) -> dict[str, Any]:
        if not self.panel_count:
            raise ValueError("cannot report an empty learning-curve window")
        means = {
            metric: _clean_float(self.metric_sums[metric] / self.metric_weights[metric])
            for metric in MEAN_METRICS
        }
        bank_reports: dict[str, dict[str, float | None]] = {}
        total_games = 0.0
        total_score = 0.0
        for bank in sorted(self.bank_games):
            games = self.bank_games[bank]
            score = self.bank_scores[bank]
            total_games += games
            total_score += score
            bank_reports[str(bank)] = {
                "games": _clean_float(games),
                "score_sum": _clean_float(score),
                "score": (_clean_float(score / games) if games else None),
            }
        return {
            "panel_count": self.panel_count,
            "episode_count": self.episode_count,
            "min_step": self.min_step,
            "max_step": self.max_step,
            "episode_weighted_means": means,
            "integrity_totals": {
                metric: _clean_float(self.integrity_totals[metric])
                for metric in INTEGRITY_METRICS
            },
            "static_training_pool": {
                "games": _clean_float(total_games),
                "score_sum": _clean_float(total_score),
                "score": (
                    _clean_float(total_score / total_games) if total_games else None
                ),
                "banks": bank_reports,
                "evidence_class": "in_pool_training_diagnostic",
            },
        }


def _validate_train_panel(panel: dict[str, Any]) -> tuple[int, int] | None:
    schema = _exact_nonnegative_int(panel.get("_puffer_schema", 0), "schema")
    if schema != 2:
        raise ValueError(f"learning-curve analysis requires schema 2, got {schema}")
    if _finite_number(panel.get("_puffer_final_reprint", 0), "final marker") > 0:
        return None
    if _finite_number(panel.get("_puffer_phase_eval", 0), "phase marker") > 0:
        return None
    n = _exact_nonnegative_int(panel.get("n", 0), "panel n")
    if n == 0:
        return None
    if _finite_number(panel.get("_puffer_env_cumulative", 0), "cumulative marker") != 0:
        raise ValueError("schema-2 training panels must be independent, not cumulative")
    if _finite_number(panel.get("_puffer_backend_native", 0), "backend marker") != 1:
        raise ValueError("learning-curve analysis requires the native backend")
    step = _exact_nonnegative_int(
        panel.get("_puffer_agent_steps"), "_puffer_agent_steps"
    )
    return step, n


def analyze_log(
    path: Path,
    *,
    max_step: int | None = None,
    endpoint_step: int | None = None,
    window_steps: int = 500_000_000,
    expected_sha256: str | None = None,
) -> dict[str, Any]:
    """Stream one log into deterministic overall, endpoint, and band reports."""
    if max_step is not None and max_step <= 0:
        raise ValueError("max_step must be positive")
    if endpoint_step is not None and endpoint_step <= 0:
        raise ValueError("endpoint_step must be positive")
    if window_steps <= 0:
        raise ValueError("window_steps must be positive")
    if expected_sha256 is not None:
        expected_sha256 = expected_sha256.lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be 64 lowercase hex characters")

    digest = hashlib.sha256()
    byte_count = 0
    machine_panels = 0
    eligible_panels = 0
    observed_max_step: int | None = None
    saw_requested_max = max_step is None
    previous_step: int | None = None
    selected: list[dict[str, Any]] = []

    try:
        source = path.open("rb")
    except OSError as exc:
        raise OSError(f"cannot read learning-curve log {path}: {exc}") from exc
    with source:
        for line_number, raw_line in enumerate(source, 1):
            digest.update(raw_line)
            byte_count += len(raw_line)
            if not raw_line.startswith(ENV_JSON_PREFIX):
                continue
            machine_panels += 1
            try:
                panel = json.loads(raw_line[len(ENV_JSON_PREFIX) :])
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ValueError(
                    f"{path}:{line_number}: invalid PUFFER_ENV_JSON payload"
                ) from exc
            if not isinstance(panel, dict):
                raise ValueError(
                    f"{path}:{line_number}: machine panel is not an object"
                )
            validated = _validate_train_panel(panel)
            if validated is None:
                continue
            step, _ = validated
            eligible_panels += 1
            if previous_step is not None and step <= previous_step:
                raise ValueError(
                    f"schema-2 train steps are not strictly increasing: "
                    f"{step} after {previous_step}"
                )
            previous_step = step
            observed_max_step = step
            if max_step is not None and step == max_step:
                saw_requested_max = True
            if max_step is None or step <= max_step:
                selected.append(panel)

    actual_sha256 = digest.hexdigest()
    if expected_sha256 is not None and actual_sha256 != expected_sha256:
        raise ValueError(
            f"source SHA-256 mismatch: expected {expected_sha256}, got {actual_sha256}"
        )
    if not selected:
        raise ValueError("log has no selected schema-2 native train panels")
    if not saw_requested_max:
        raise ValueError(f"requested exact max step {max_step} is absent from the log")

    analysis_max = max_step if max_step is not None else int(observed_max_step)
    nominal_endpoint = endpoint_step if endpoint_step is not None else analysis_max
    if nominal_endpoint > analysis_max:
        raise ValueError(
            f"endpoint_step {nominal_endpoint} exceeds analysis max {analysis_max}"
        )
    if nominal_endpoint < window_steps:
        raise ValueError("endpoint_step must be at least one window_steps interval")
    overall = Aggregate()
    first = Aggregate()
    last = Aggregate()
    bands: dict[int, Aggregate] = {}
    last_floor = nominal_endpoint - window_steps
    for panel in selected:
        step = int(panel["_puffer_agent_steps"])
        overall.add(panel)
        if step <= window_steps:
            first.add(panel)
        if last_floor < step <= nominal_endpoint:
            last.add(panel)
        band_index = max(0, (step - 1) // window_steps)
        bands.setdefault(band_index, Aggregate()).add(panel)
    if not first.panel_count:
        raise ValueError("no panel falls in the first endpoint window")
    if not last.panel_count:
        raise ValueError("no panel falls in the last endpoint window")

    band_reports = []
    for index, aggregate in sorted(bands.items()):
        start_exclusive = index * window_steps
        end_inclusive = min((index + 1) * window_steps, analysis_max)
        band_reports.append(
            {
                "start_step_exclusive": start_exclusive,
                "end_step_inclusive": end_inclusive,
                "data": aggregate.report(),
            }
        )
    return {
        "schema": "bloodbowl_reward_learning_curve_v1",
        "source": {
            "path": str(path),
            "bytes": byte_count,
            "sha256": actual_sha256,
            "machine_panels_seen": machine_panels,
            "eligible_train_panels_seen": eligible_panels,
        },
        "selection": {
            "analysis_max_step": analysis_max,
            "nominal_endpoint_step": nominal_endpoint,
            "exact_max_step_required": max_step is not None,
            "window_steps": window_steps,
            "interval_convention": "start_exclusive_end_inclusive",
        },
        "evidence_warning": (
            "Historical banks are in-pool training diagnostics; this report "
            "cannot select or promote a checkpoint or reward."
        ),
        "overall": overall.report(),
        "endpoints": {
            "first": {
                "start_step_exclusive": 0,
                "end_step_inclusive": window_steps,
                "data": first.report(),
            },
            "last": {
                "start_step_exclusive": last_floor,
                "end_step_inclusive": nominal_endpoint,
                "data": last.report(),
            },
        },
        "bands": band_reports,
    }


def _positive_int(raw: str) -> int:
    value = int(raw)
    if value <= 0:
        raise argparse.ArgumentTypeError("must be a positive integer")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="Puffer training log")
    parser.add_argument(
        "--expect-sha256",
        help="fail unless the complete source file has this SHA-256",
    )
    parser.add_argument(
        "--max-step",
        type=_positive_int,
        help="require and analyze through this exact native learner step",
    )
    parser.add_argument(
        "--endpoint-step",
        type=_positive_int,
        help=(
            "nominal endpoint that defines the trailing band; exact checkpoint "
            "overshoot through --max-step is excluded from this endpoint"
        ),
    )
    parser.add_argument(
        "--window-steps",
        type=_positive_int,
        default=500_000_000,
        help="endpoint and non-overlapping band width (default: 500000000)",
    )
    parser.add_argument("--indent", type=int, default=2)
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = analyze_log(
            args.log,
            max_step=args.max_step,
            endpoint_step=args.endpoint_step,
            window_steps=args.window_steps,
            expected_sha256=args.expect_sha256,
        )
    except (OSError, ValueError) as exc:
        raise SystemExit(f"error: {exc}") from exc
    print(json.dumps(report, indent=args.indent, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
