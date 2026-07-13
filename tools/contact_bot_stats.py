#!/usr/bin/env python3
# contact_bot_stats.py - contact-bot eval reader; team0=champion, team1=bot.
"""Aggregate Puffer dashboard windows and print champion-vs-contact-bot stats."""

import json
import os
import sys

from game_stats import weighted_dashboard

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASELINE = os.path.join(ROOT, "docs", "human-baseline.json")


def need(vals, key):
    if key not in vals:
        raise KeyError(key)
    return vals[key]


def bot_perspective(vals, bot_team):
    if bot_team not in (0, 1):
        raise ValueError("bot_team must be 0 or 1")
    champion_team = 1 - bot_team
    return {
        "champion_team": champion_team,
        "bot_team": bot_team,
        "champion_score": need(vals, f"slot_{champion_team}_score"),
        "bot_score": need(vals, f"slot_{bot_team}_score"),
        "champion_tds": need(vals, f"tds_t{champion_team}"),
        "bot_tds": need(vals, f"tds_t{bot_team}"),
        "champion_blocks": need(vals, f"blocks_thrown_t{champion_team}"),
        "bot_blocks": need(vals, f"blocks_thrown_t{bot_team}"),
    }


def main():
    if len(sys.argv) not in (2, 3):
        print("usage: python3 tools/contact_bot_stats.py <eval.log> [bot_team=1]", file=sys.stderr)
        return 1
    try:
        bot_team = int(sys.argv[2]) if len(sys.argv) == 3 else 1
    except ValueError:
        print("bot_team must be 0 or 1", file=sys.stderr)
        return 1
    if bot_team not in (0, 1):
        print("bot_team must be 0 or 1", file=sys.stderr)
        return 1

    vals = weighted_dashboard(sys.argv[1])
    if not vals:
        print(
            f"no completed-episode windows with visible n in {sys.argv[1]}; "
            "install the dashboard-limit patch and rerun",
            file=sys.stderr,
        )
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
    human_game_blocks = float(
        base.get("resolved_blocks_per_game_bb2025", 0.0) or 0.0)
    human_team_blocks = human_game_blocks / 2.0 if human_game_blocks > 0 else 0.0
    view = bot_perspective(vals, bot_team)
    champ_blocks = view["champion_blocks"]
    block_delta = champ_blocks - human_team_blocks if human_team_blocks else 0.0
    block_pct = 100.0 * block_delta / human_team_blocks if human_team_blocks else 0.0

    print("scripted-bot eval weighted aggregate")
    print(f"  N games: {need(vals, 'n'):.0f}")
    print(f"  champion score team{view['champion_team']}: {view['champion_score']:.3f}")
    print(f"  bot score team{view['bot_team']}:      {view['bot_score']:.3f}")
    print(f"  draw rate:                   {need(vals, 'draw_rate'):.3f}")
    print(f"  tds: champion(team{view['champion_team']}) {view['champion_tds']:.3f} | "
          f"bot(team{view['bot_team']}) {view['bot_tds']:.3f}")
    print(f"  blocks thrown: champion(team{view['champion_team']}) {champ_blocks:.3f} | "
          f"bot(team{view['bot_team']}) {view['bot_blocks']:.3f}")
    if human_team_blocks:
        print(f"  champion blocks vs human/team baseline: {champ_blocks:.3f} vs "
              f"{human_team_blocks:.3f} ({block_delta:+.3f}, {block_pct:+.0f}%)")
    else:
        print("  champion blocks vs human/team baseline: baseline unavailable")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
