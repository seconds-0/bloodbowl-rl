#!/usr/bin/env python3
"""Build a D111 hard-opponents league pool from the live anchored ladder.

D111 turned pool composition from a hand-picked judgment call into a mechanical
step: every new 8-bank league should mix current ladder-top hard opponents,
second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
registry. This tool refits Elo from the CSV each time, applies the D111 slot
doctrine, and prints both a human audit table and ready-to-paste launch/build
snippets for operators.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set

from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows


DEFAULT_LADDER = "tools/anchored_ladder.csv"
DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
DEFAULT_ANCHOR = "gen1"
DEFAULT_CHECKPOINT_DIR = "training"
DEFAULT_EXPECT_BYTES = 16_066_560
ELO_SCALE = 400.0
POOL_BANKS = 8


class PoolError(RuntimeError):
    pass


@dataclass(frozen=True)
class Candidate:
    name: str
    elo: float
    filename: str
    b2_key: Optional[str]
    classification: str


@dataclass(frozen=True)
class Pick:
    candidate: Candidate
    slot: str


def warn(msg: str) -> None:
    print(f"warning: {msg}", file=sys.stderr)


def classify_status(status: object) -> str:
    text = str(status or "").lower().replace("non-degenerate", "")
    if "degenerate" in text or "retired" in text:
        return "DEGENERATE"
    if "floor" in text:
        return "FLOOR"
    if "diversity" in text:
        return "DIVERSITY_CANDIDATE"
    return "TIER1_CANDIDATE"


def load_registry(path: str) -> Dict[str, dict]:
    with open(path) as f:
        data = json.load(f)
    nodes = data.get("nodes")
    if not isinstance(nodes, dict):
        raise PoolError(f"{path}: missing object field 'nodes'")
    return nodes


def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
    rows = parse_rows(path)
    if not rows:
        raise PoolError(f"{path}: no CSV rows found")

    names, wins, games, _raw, skipped = decisive_counts(rows)
    total_decisive = {
        name: sum(n for pair, n in games.items() if name in pair)
        for name in names
    }
    excluded = [name for name in names if total_decisive[name] <= 0]
    for name in excluded:
        warn(f"excluding {name}: zero decisive games vs everyone")
    for a, b, why in skipped:
        warn(f"skipping {a} vs {b} for fit: {why}")

    fit_names = [name for name in names if name not in set(excluded)]
    if len(fit_names) < 2:
        raise PoolError("need at least two connected anchors with decisive games")

    comps = connected_components(fit_names, games)
    if len(comps) > 1:
        comps = sorted(comps, key=len, reverse=True)
        keep = set(comps[0])
        dropped = sorted(name for comp in comps[1:] for name in comp)
        warn("decisive graph is disconnected; fitting largest component only: "
             + ", ".join(comps[0]))
        warn("excluded disconnected anchors: " + ", ".join(dropped))
        fit_names = [name for name in fit_names if name in keep]

    if anchor not in fit_names:
        raise PoolError(f"anchor {anchor!r} is not in the fitted component")

    pi = fit_bt(fit_names, wins, games)
    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)


def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
    ladder_names = set(elo)
    registry_names = set(registry)

    for name in sorted(ladder_names - registry_names):
        warn(f"ladder node {name!r} missing from registry; skipping")
    for name in sorted(registry_names - ladder_names):
        if name.startswith("_"):
            continue
        warn(f"registry node {name!r} missing from ladder fit; skipping")

    candidates = []
    for name in sorted(ladder_names & registry_names):
        entry = registry[name]
        if not isinstance(entry, dict):
            warn(f"registry node {name!r} is not an object; skipping")
            continue
        filename = entry.get("filename")
        if not filename:
            warn(f"registry node {name!r} missing filename; skipping")
            continue
        b2_key = entry.get("b2_key")
        if b2_key is not None and not isinstance(b2_key, str):
            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
            b2_key = None
        candidates.append(Candidate(
            name=name,
            elo=elo[name],
            filename=str(filename),
            b2_key=b2_key,
            classification=classify_status(entry.get("status", "")),
        ))
    return candidates


def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
    return sorted(candidates, key=lambda c: c.elo, reverse=True)


def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
    out = []
    seen = set()
    for node in nodes or []:
        if node not in seen:
            seen.add(node)
            out.append(node)
    return out


def append_pick(
    picks: List[Pick],
    used: Set[str],
    candidate: Candidate,
    slot: str,
    cap: int = POOL_BANKS,
) -> bool:
    if candidate.name in used or len(picks) >= cap:
        return False
    picks.append(Pick(candidate, slot))
    used.add(candidate.name)
    return True


def select_pool(
    candidates: Sequence[Candidate],
    tier1_count: int,
    tier2_count: int,
    requested_diversity: int,
    include: Sequence[str],
    exclude: Sequence[str],
) -> List[Pick]:
    by_name = {c.name: c for c in candidates}
    include_nodes = unique_nodes(include)
    exclude_set = set(exclude or [])
    if len(include_nodes) > POOL_BANKS:
        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
    included_excluded = [name for name in include_nodes if name in exclude_set]
    if included_excluded:
        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))

    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
    selectable = [c for c in nondegenerate if c.name not in exclude_set]
    selectable_by_name = {c.name: c for c in selectable}

    picks: List[Pick] = []
    used: Set[str] = set()

    for name in include_nodes:
        candidate = by_name.get(name)
        if candidate is None:
            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
        if candidate.classification == "DEGENERATE":
            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
        append_pick(picks, used, candidate, "INCLUDE")

    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
    if floor_pick is None:
        warn("no FLOOR-tagged candidate available")
    else:
        append_pick(picks, used, floor_pick, "FLOOR")

    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
    tier1_pool = tier_pool[:tier1_count]
    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]

    desired_before_diversity = 1 + tier1_count + tier2_count
    remaining_after_requested = POOL_BANKS - desired_before_diversity
    if remaining_after_requested >= requested_diversity:
        diversity_count = remaining_after_requested
    else:
        diversity_count = requested_diversity
        if desired_before_diversity + requested_diversity > POOL_BANKS:
            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")

    for candidate in tier1_pool:
        append_pick(picks, used, candidate, "TIER1")
    for candidate in tier2_pool:
        append_pick(picks, used, candidate, "TIER2")

    diversity_pool = ordered_by_elo(
        c for c in selectable
        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
    )
    diversity_added = 0
    for candidate in diversity_pool:
        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
            break
        if append_pick(picks, used, candidate, "DIVERSITY"):
            diversity_added += 1

    if len(picks) < POOL_BANKS:
        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
        for candidate in fallback_pool:
            if len(picks) >= POOL_BANKS:
                break
            append_pick(picks, used, candidate, fallback_slot(candidate))

    if len(picks) < POOL_BANKS:
        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")

    return picks


def fallback_slot(candidate: Candidate) -> str:
    if candidate.classification == "FLOOR":
        return "FLOOR"
    if candidate.classification == "DIVERSITY_CANDIDATE":
        return "DIVERSITY"
    return "TIER2"


def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
    return os.path.join(checkpoint_dir, filename)


def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
    print(f"warm-start recommendation: {warmstart.name} "
          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
    print()
    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
    print("-" * 100)
    for bank, pick in enumerate(picks):
        c = pick.candidate
        b2_key = c.b2_key if c.b2_key is not None else "-"
        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
    print()
    print(f"selected banks: {len(picks)}")


def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
    print()
    missing = [
        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
        for pick in picks
        if pick.candidate.b2_key
        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
    ]
    if missing:
        print("missing checkpoint fetches:")
        for candidate, path in missing:
            print("# MISSING locally -- fetch first:")
            print("# rclone copyto "
                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
        print()

    print("build_league command:")
    print("python3 tools/build_league.py \\")
    print("  --out <PLACEHOLDER> \\")
    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
    print("  --seeds \\")
    for index, pick in enumerate(picks):
        c = pick.candidate
        path = checkpoint_path(checkpoint_dir, c.filename)
        suffix = " \\" if index != len(picks) - 1 else ""
        print(f"  {c.name}={path}{suffix}")


def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
    print()
    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="Build a D111 hard-opponents pool from anchored ladder data")
    ap.add_argument("--ladder", default=DEFAULT_LADDER,
                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
    ap.add_argument("--tier1", type=int, default=3,
                    help="number of top Elo hard-opponent slots (default 3)")
    ap.add_argument("--tier2", type=int, default=3,
                    help="number of next Elo hard-opponent slots (default 3)")
    ap.add_argument("--diversity", type=int, default=1,
                    help="minimum diversity slots (default 1)")
    ap.add_argument("--exclude", nargs="+", default=[],
                    help="nodes to exclude from pool selection")
    ap.add_argument("--include", nargs="+", default=[],
                    help="nodes to force into the pool")
    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
    ap.add_argument("--print-build-league", action="store_true",
                    help="also print a ready-to-paste build_league.py command")
    ap.add_argument("--print-launch-vars", action="store_true",
                    help="also print shell-sourceable launch variables")
    return ap.parse_args(argv)


def validate_counts(args: argparse.Namespace) -> None:
    for name in ("tier1", "tier2", "diversity"):
        value = getattr(args, name)
        if value < 0:
            raise PoolError(f"--{name} must be non-negative")


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        validate_counts(args)
        elo = fit_ladder(args.ladder, args.anchor)
        registry = load_registry(args.registry)
        candidates = candidates_from_inputs(elo, registry)
        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
        if not nondegenerate:
            raise PoolError("no non-degenerate candidates available")
        warmstart = max(nondegenerate, key=lambda c: c.elo)
        picks = select_pool(
            candidates,
            tier1_count=args.tier1,
            tier2_count=args.tier2,
            requested_diversity=args.diversity,
            include=args.include,
            exclude=args.exclude,
        )
    except PoolError as e:
        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
        return 1

    print_table(picks, warmstart, args.checkpoint_dir)
    if args.print_build_league:
        print_build_league(picks, args.checkpoint_dir)
    if args.print_launch_vars:
        print_launch_vars(warmstart, args.checkpoint_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
