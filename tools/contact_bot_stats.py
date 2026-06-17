#!/usr/bin/env python3
# contact_bot_stats.py - contact-bot eval reader; team0=champion, team1=bot.
"""Read the final Puffer dashboard and print champion-vs-contact-bot stats."""

import json
import os
import sys

from game_stats import latest_dashboard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "docs", "human-baseline.json")


def need(vals, key):
    if key not in vals:
        raise KeyError(key)
    return vals[key]


def main():
    if len(sys.argv) != 2:
        print("usage: python3 tools/contact_bot_stats.py <eval.log>", file=sys.stderr)
        return 1

    vals = latest_dashboard(sys.argv[1])
    if not vals:
        print(f"no dashboard lines found in {sys.argv[1]}", file=sys.stderr)
        return 2

    required = (
        "n", "slot_0_score", "slot_1_score", "draw_rate",
        "tds_t0", "tds_t1", "blocks_thrown_t0", "blocks_thrown_t1",
    )
    missing = [k for k in required if k not in vals]
    if missing:
        print("dashboard missing contact-bot fields: " + ", ".join(missing),
              file=sys.stderr)
        print("rerun with a fresh installed bloodbowl env and patched dashboard",
              file=sys.stderr)
        return 3

    base = json.load(open(BASELINE, encoding="utf-8")) if os.path.exists(BASELINE) else {}
    human_game_blocks = float(base.get("blockRoll_per_game", 0.0) or 0.0)
    human_team_blocks = human_game_blocks / 2.0 if human_game_blocks > 0 else 0.0
    champ_blocks = need(vals, "blocks_thrown_t0")
    block_delta = champ_blocks - human_team_blocks if human_team_blocks else 0.0
    block_pct = 100.0 * block_delta / human_team_blocks if human_team_blocks else 0.0

    print("contact-bot eval final dashboard")
    print(f"  N games: {need(vals, 'n'):.0f}")
    print(f"  champion score slot_0/team0: {need(vals, 'slot_0_score'):.3f}")
    print(f"  bot score slot_1/team1:      {need(vals, 'slot_1_score'):.3f}")
    print(f"  draw rate:                   {need(vals, 'draw_rate'):.3f}")
    print(f"  tds: champion(team0) {need(vals, 'tds_t0'):.3f} | "
          f"bot(team1) {need(vals, 'tds_t1'):.3f}")
    print(f"  blocks thrown: champion(team0) {champ_blocks:.3f} | "
          f"bot(team1) {need(vals, 'blocks_thrown_t1'):.3f}")
    if human_team_blocks:
        print(f"  champion blocks vs human/team baseline: {champ_blocks:.3f} vs "
              f"{human_team_blocks:.3f} ({block_delta:+.3f}, {block_pct:+.0f}%)")
    else:
        print("  champion blocks vs human/team baseline: baseline unavailable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
