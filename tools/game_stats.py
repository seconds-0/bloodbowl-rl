#!/usr/bin/env python3
"""game_stats.py — per-game stat tracker: read a run's dashboard and compare
to the measured human baseline (docs/human-baseline.json).

Human stats are a PLAUSIBLY-OPTIMAL REFERENCE, not a target to match. A
superhuman policy SHOULD diverge on some axes (fewer/better blocks, more
conservative ball security, optimal-carrier pickups). This tool shows the
distance AND the direction so you can tell "still learning the basics"
(converging toward human) from "diverging past human" (the superhuman signal).

CRITICAL: the per-game comparison is only valid for FULL-GAME eval from
kickoff (env demo_reset_pct = 0). Training dashboards use curriculum starts
(demo_reset_pct 0.9) — their tds/gfi/etc. are per-CURRICULUM-EPISODE and are
NOT comparable to the human per-game numbers. Use tools/eval_game_stats.sh to
produce a kickoff-start measurement log, then feed it here. This tool warns
loudly if it detects a curriculum-start log.

Usage:
    tools/eval_game_stats.sh <checkpoint> 500 > /tmp/eval.log   # produce it
    python3 tools/game_stats.py /tmp/eval.log                   # compare it
    python3 tools/game_stats.py /tmp/eval.log --raw             # no baseline, just values
"""
import json
import math
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "docs", "human-baseline.json")

# Dashboard keys we track -> (human-baseline key, "lower"/"higher"/"context",
# one-line meaning). "context" = no inherent better direction.
METRICS = [
    ("tds",                "tds_per_game_bb2025_exact", "higher", "touchdowns / game"),
    ("blocks_thrown",      "resolved_blocks_per_game_bb2025", "context", "resolved blocks / game"),
    ("block_2d_frac",      "block_2d_frac_bb2025_resolved", "higher", "share of blocks that are 2d attacker-choice"),
    ("block_2dred_frac",   "block_2dred_frac_bb2025_resolved", "lower", "share that are 2d defender-choice (red)"),
    ("block_3d_frac",      "block_3d_frac_bb2025_resolved", "higher", "share that are 3d attacker-choice"),
    ("dodge_attempts",     "dodge_tests_reached_per_game_bb2025", "context", "dodge intentions vs human tests reached"),
    ("gfi_attempts",       "rush_tests_reached_per_game_bb2025", "context", "rush intentions vs human tests reached"),
    ("pickup_attempts",    "pickup_tests_reached_per_game_bb2025", "context", "pickup intentions vs human tests reached"),
    ("pickup_success",     "pickup_success_per_game_bb2025", "higher", "successful pickups / game"),
    ("pass_attempts",      "pass_tests_reached_per_game_bb2025", "context", "pass intentions vs human tests reached"),
    ("handoff_attempts",   "handoff_per_game_bb2025", "context", "hand-offs / game"),
    ("possession_rate",    "possession_rate_bb2025_per_game_mean", "context",
     "per-game genuine-turn share ending held (TD-ends included)"),
]

# Puffer dashboard is a TWO-COLUMN box: "| key  val    key  val |". Find all
# key/number pairs per line after stripping ANSI + box-drawing bytes.
PAIR_RE = re.compile(r"([a-z_][a-z_0-9]*)\s+([-+]?\d+\.\d+|[-+]?\d+)")
ENV_JSON_PREFIX = "PUFFER_ENV_JSON "


def completed_game_requirement_met(observed, minimum):
    """Return whether a finite completed-game count meets its inclusive floor."""
    return math.isfinite(observed) and observed >= minimum


def strip_ansi(s):
    s = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", s)
    return s.replace("\u2502", " ").replace("\u2503", " ")  # box verticals


def latest_dashboard(path):
    """Return {key: float} accumulating pairs from the LAST dashboard block.
    The dashboard reprints periodically; later prints overwrite earlier keys,
    so the final dict reflects the most recent (most-converged) block."""
    vals = {}
    with open(path, errors="ignore", encoding="utf-8") as f:
        for line in f:
            for k, v in PAIR_RE.findall(strip_ansi(line)):
                try:
                    vals[k] = float(v)
                except ValueError:
                    pass
    return vals


def dashboard_windows(path):
    """Return parsed dashboard windows in file order.

    Puffer resets environment logs after each dashboard read, so each printed
    training ``env/n`` is the number of episodes in that interval. The native
    backend's eval logger is the exception: it deliberately does not reset and
    therefore emits cumulative snapshots. Machine-readable panels carry
    ``_eval_cumulative`` so :func:`weighted_dashboard` can distinguish them.

    When a full-fidelity ``PUFFER_ENV_JSON`` payload is present, use it as the
    entire environment window. Rich-rendered text is lossy and can contain
    unrelated trainer fields; text parsing remains only for legacy logs.
    """
    windows = []
    current_text = None
    current_machine = None

    def finish_window():
        payload = (current_machine if current_machine is not None
                   else current_text)
        if payload:
            windows.append(payload)

    with open(path, errors="ignore", encoding="utf-8") as f:
        for line in f:
            clean = strip_ansi(line)
            if "PufferLib 4.0" in clean:
                if current_text is not None:
                    finish_window()
                current_text = {}
                current_machine = None
            if current_text is None:
                continue
            if clean.startswith(ENV_JSON_PREFIX):
                try:
                    payload = json.loads(clean[len(ENV_JSON_PREFIX):])
                except json.JSONDecodeError:
                    continue
                machine = {}
                for key, value in payload.items():
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        machine[key] = float(value)
                current_machine = machine
                continue
            for key, value in PAIR_RE.findall(clean):
                try:
                    current_text[key] = float(value)
                except ValueError:
                    pass
    if current_text is not None:
        finish_window()
    return windows


def analysis_windows(path, phase="auto"):
    """Return independent episode samples, normalizing Puffer log semantics.

    New machine payloads explicitly mark Puffer's unconditional final reprint,
    train/eval phase, and native cumulative eval semantics. Native cumulative
    runs contribute only their final snapshot. Torch eval aliases the resetting
    training logger and remains interval-based. ``phase='auto'`` selects eval
    when phase metadata exists, otherwise train; legacy unmarked logs retain
    their historical all-window behavior because their phase is unrecoverable.
    """
    if phase not in ("auto", "train", "eval", "all"):
        raise ValueError("phase must be auto, train, eval, or all")

    # Schema 1 inferred phase from the backend's epoch counter. Both backends
    # increment that counter during train(), so the last training interval was
    # the first panel marked as eval. Complete logs include an earlier explicit
    # train panel (the startup panel is sufficient), which makes this one
    # transition repair unambiguous. Schema 2 receives phase directly from the
    # authoritative _train loop and needs no compatibility handling.
    windows = []
    saw_schema1_train = False
    repaired_schema1_boundary = False
    for original in dashboard_windows(path):
        window = original
        if int(window.get("_puffer_schema", 0.0)) == 1:
            phase_eval = window.get("_puffer_phase_eval", 0.0) > 0.0
            if not phase_eval:
                saw_schema1_train = True
            elif saw_schema1_train and not repaired_schema1_boundary:
                window = dict(window)
                window["_puffer_phase_eval"] = 0.0
                window["_puffer_env_cumulative"] = 0.0
                repaired_schema1_boundary = True
        n = window.get("n", 0.0)
        if not math.isfinite(n):
            raise ValueError("dashboard window has non-finite n")
        if n <= 0.0 or window.get("_puffer_final_reprint", 0.0) > 0.0:
            continue
        windows.append(window)

    has_phase = any("_puffer_phase_eval" in window for window in windows)
    if has_phase:
        selected = phase
        if selected == "auto":
            selected = ("eval" if any(
                window.get("_puffer_phase_eval", 0.0) > 0.0
                for window in windows) else "train")
        if selected != "all":
            want_eval = selected == "eval"
            windows = [
                window for window in windows
                if (window.get("_puffer_phase_eval", 0.0) > 0.0) == want_eval
            ]
    elif phase in ("train", "eval"):
        raise ValueError(
            f"cannot select {phase} phase from a legacy log without "
            "_puffer_phase_eval metadata")

    independent = []
    index = 0
    while index < len(windows):
        window = windows[index]
        if window.get("_puffer_env_cumulative", 0.0) <= 0.0:
            independent.append(window)
            index += 1
            continue
        end = index + 1
        while (end < len(windows) and
               windows[end].get("_puffer_env_cumulative", 0.0) > 0.0):
            end += 1
        independent.append(windows[end - 1])
        index = end
    return independent


def weighted_dashboard(path, phase="auto"):
    """Aggregate independent completed-episode windows for one selected phase."""
    windows = analysis_windows(path, phase=phase)
    if not windows:
        return {}
    result = {"n": sum(window["n"] for window in windows)}
    keys = {
        key
        for window in windows
        for key in window
        if key != "n" and not key.startswith("_")
    }
    for key in keys:
        present = [window for window in windows if key in window]
        weight = sum(window["n"] for window in present)
        if weight:
            if any(not math.isfinite(window[key]) for window in present):
                raise ValueError(f"dashboard metric {key} is non-finite")
            result[key] = sum(
                window[key] * window["n"] for window in present) / weight
    return result


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)
    vals = weighted_dashboard(args[0])
    if not vals:
        print(
            f"no completed-episode dashboard windows with visible n found in "
            f"{args[0]}; install training/pufferl_env_dashboard_limit.patch "
            "and rerun the eval",
            file=sys.stderr,
        )
        sys.exit(2)

    # Curriculum-start guard: demo_episodes > 0 in the log means curriculum
    # resets were on -> per-game numbers are NOT human-comparable.
    demo = vals.get("demo_episodes", 0.0)
    if demo and demo > 0.01:
        print("!" * 74)
        print(f"WARNING: demo_episodes={demo:.2f} > 0 — this log used CURRICULUM "
              "STARTS.\n  tds/gfi/etc. are per-curriculum-episode, NOT per full game.\n"
              "  Re-run with tools/eval_game_stats.sh (demo_reset_pct 0) for a\n"
              "  human-comparable per-game measurement.")
        print("!" * 74)

    base = {}
    if not raw and os.path.exists(BASELINE):
        base = json.load(open(BASELINE))

    print(f"\n{'metric':<20}{'OURS':>10}{'HUMAN':>10}{'delta':>10}  read")
    print("-" * 78)
    for key, bkey, direction, meaning in METRICS:
        if key not in vals:
            continue
        ours = vals[key]
        hb = base.get(bkey) if bkey else None
        if hb is None:
            print(f"{key:<20}{ours:>10.3f}{'--':>10}{'--':>10}  {meaning}")
            continue
        delta = ours - hb
        pct = 100.0 * delta / hb if hb else float("nan")
        # direction read
        if direction == "context":
            tag = "(context)"
        elif direction == "lower":
            tag = "toward human" if (delta < 0 and abs(ours - hb) < abs(0 - hb)) else ("PAST human (lower)" if ours < hb else "above human")
        else:  # higher is better
            tag = "PAST human (higher)" if ours > hb else "below human"
        print(f"{key:<20}{ours:>10.3f}{hb:>10.3f}{pct:>9.0f}%  {meaning} [{tag}]")
    print()
    if base:
        print(f"evaluation aggregate: {vals.get('n', 0):.0f} completed games")
        print(f"legacy behavior references: {base.get('_games','?')} games / "
              f"{base.get('_team_turns','?')} reported turns; see the audit warning in "
              "docs/human-baseline.json")
        print("corrected possession reference: "
              f"{base.get('_possession_bb2025_games','?')} exact-BB2025 games / "
              f"{base.get('_possession_bb2025_team_turns','?')} genuine turns")


if __name__ == "__main__":
    main()
