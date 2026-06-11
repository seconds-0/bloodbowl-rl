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
import json, os, re, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "docs", "human-baseline.json")

# Dashboard keys we track -> (human-baseline key, "lower"/"higher"/"context",
# one-line meaning). "context" = no inherent better direction.
METRICS = [
    ("tds",                "tds_per_game",        "higher",  "touchdowns / game"),
    ("blocks_thrown",      "blockRoll_per_game",  "context", "blocks thrown / game"),
    ("block_2d_frac",      "block_2d_frac",       "higher",  "share of blocks that are 2d attacker-choice"),
    ("block_2dred_frac",   "block_2dred_frac",    "lower",   "share that are 2d defender-choice (red)"),
    ("block_3d_frac",      "block_3d_frac",       "higher",  "share that are 3d attacker-choice"),
    ("dodge_attempts",     "dodgeRoll_per_game",  "context", "dodges / game"),
    ("gfi_attempts",       "goForItRoll_per_game","context", "go-for-its / game"),
    ("pickup_attempts",    "pickUpRoll_per_game", "context", "pickup attempts / game"),
    ("pickup_success",     "pickUp_success_per_game", "higher", "successful pickups / game"),
    ("pass_attempts",      "passRoll_per_game",   "context", "passes / game"),
    ("handoff_attempts",   "handoff_per_game",    "context", "hand-offs / game"),
    ("possession_rate",    "possession_rate_d90", "context", "turns ending held (incl. TD-ends, D90)"),
]

# Puffer dashboard is a TWO-COLUMN box: "| key  val    key  val |". Find all
# key/number pairs per line after stripping ANSI + box-drawing bytes.
PAIR_RE = re.compile(r"([a-z_][a-z_0-9]*)\s+([-+]?\d+\.\d+|[-+]?\d+)")


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


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(1)
    vals = latest_dashboard(args[0])
    if not vals:
        print(f"no dashboard lines found in {args[0]}", file=sys.stderr)
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
        print(f"baseline: {base.get('_games','?')} human games, "
              f"{base.get('_team_turns','?')} team-turns (docs/human-baseline.json)")


if __name__ == "__main__":
    main()
