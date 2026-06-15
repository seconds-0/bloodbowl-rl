Reading additional input from stdin...
OpenAI Codex v0.139.0
--------
workdir: /Users/alexanderhuth/Code/bloodbowl-rl
model: gpt-5.5
provider: openai
approval: never
sandbox: danger-full-access
reasoning effort: medium
reasoning summaries: none
session id: 019ec84d-7ead-7560-9cd4-4df8b11aba18
--------
user
# Brief: tools/build_pool_from_ladder.py (D111 hard-opponents pool automation)

Repo: /Users/alexanderhuth/Code/bloodbowl-rl. No git state changes (no commit) — leave the
new file for the architect to review and commit. Match existing tools/ style (argparse,
docstring header explaining WHY like build_league.py's, type hints where natural).

## Context
D111 codified a "hard opponents" pool-composition doctrine: every new league pool's 8 banks
should be {2-3 TIER1 (current ladder-top by Elo), 2-3 TIER2, 1-2 DIVERSITY (stylistically
distinct lineages regardless of Elo), 1 FLOOR (gen1, the stable anchor=0 reference)}. Two new
files already exist as the durable data sources:
- `tools/anchored_ladder.csv` — the Bradley-Terry ladder's raw pairing data (columns:
  nameA,nameB,A_rate,B_rate,draw_rate,total_games — same format `tools/bt_fit.py` already
  consumes; bt_fit.py is the reference implementation for parsing this and fitting Elo).
- `docs/checkpoint_registry.json` — maps ladder node names (e.g. "gen2", "league5") to
  `b2_key` (B2 object name under `bbr:bloodbowl-rl/checkpoints/`, or null), `filename`
  (the canonical local `training/<filename>` name), `lineage` (one-line provenance),
  `elo_d109` (a STALE snapshot Elo for human reference only — the script must refit live,
  not trust this field), and `status` (free-text tag containing one of: "FLOOR anchor",
  "TIER1", "TIER2", "diversity", "degenerate"/"retired" — case-insensitive substring match
  is fine for classification, these are prose tags not an enum).

## Deliverable: tools/build_pool_from_ladder.py

### CLI
```
python3 tools/build_pool_from_ladder.py \
  [--ladder tools/anchored_ladder.csv] [--registry docs/checkpoint_registry.json] \
  [--anchor gen1] [--tier1 3] [--tier2 3] [--diversity 1] \
  [--exclude NODE [NODE ...]] [--include NODE [NODE ...]] \
  [--checkpoint-dir training] \
  [--print-build-league] [--print-launch-vars]
```

### Behavior
1. Parse the ladder CSV exactly like `tools/bt_fit.py` does (reuse its `parse_rows`,
   `decisive_counts`, `fit_bt`, `connected_components`, `anchored_elo` functions — IMPORT
   from `bt_fit` if its functions are importable without side effects when run as a module,
   otherwise reproduce the minimal subset; prefer import + check `if __name__ == '__main__'`
   guards in bt_fit.py allow safe import). Fit Elo with `--anchor` (default `gen1`).
2. Load the registry JSON. For every node present in BOTH the ladder fit AND the registry
   (warn to stderr and skip any ladder node missing from the registry, or any registry node
   not in the ladder — don't crash):
   - Classify each node's `status` string into one of: FLOOR, TIER1_CANDIDATE,
     DIVERSITY_CANDIDATE, DEGENERATE (case-insensitive substring match: "floor" ->
     FLOOR; "degenerate" or "retired" -> DEGENERATE; "diversity" -> DIVERSITY_CANDIDATE;
     everything else (incl "TIER1"/"TIER2"/unlabeled) -> TIER1_CANDIDATE — i.e. anything not
     explicitly floor/degenerate/diversity-only is eligible for the Elo-ranked tiers).
   - EXCLUDE all DEGENERATE nodes from selection entirely (they're zero-information, per
     D98 — e.g. bc_v4, v5contested per the current registry, but don't hardcode names,
     use the status tag).
3. Slot allocation (8 total banks):
   - FLOOR slot(s): take the node(s) tagged FLOOR (registry currently has exactly one:
     gen1, but don't hardcode a count of 1 — fill 1 FLOOR slot from whichever FLOOR-tagged
     node has the fitted Elo closest to 0, if multiple).
   - TIER1 slots (`--tier1`, default 3): the top-N TIER1_CANDIDATE nodes by fitted Elo
     (descending), EXCLUDING the floor pick and excluding anything in `--exclude`.
   - TIER2 slots (`--tier2`, default 3): the NEXT-N TIER1_CANDIDATE nodes by Elo after the
     TIER1 cut (i.e. ranks tier1+1 .. tier1+tier2).
   - DIVERSITY slots (`--diversity`, default 1, fill remaining slots up to 8 if more than
     tier1+tier2+floor+diversity < 8 — i.e. diversity count is `8 - 1(floor) - tier1 - tier2`
     if that's >= the requested `--diversity`, else use the requested count and leave fewer
     than 8 banks total, printing a warning): pick from DIVERSITY_CANDIDATE nodes, highest
     Elo first, breaking ties by... just Elo descending is fine, no secondary tiebreak needed.
   - `--include NODE...`: force these nodes into the pool regardless of tier classification
     (still respecting the 8-bank cap — included nodes take priority slots, computed
     allocation shrinks to fit; if `--include` alone exceeds 8, error out).
   - `--exclude NODE...`: never select these nodes for any slot.
   - If fewer than 8 total candidates exist across all categories, fill with whatever's
     available (don't pad with duplicates) and print how many banks were filled.
4. WARM-START recommendation: the single highest-Elo node overall (across ALL non-degenerate
   nodes, not just selected-pool members) — print this prominently. This is D107-A's
   "ladder-top warm-start" rule.
5. Output modes:
   - Default: print a human-readable table — bank index, node name, Elo, registry filename,
     b2_key, classification tag (FLOOR/TIER1/TIER2/DIVERSITY), and the warm-start
     recommendation at the top.
   - `--print-build-league`: ALSO print a ready-to-paste `python3 tools/build_league.py
     --out <PLACEHOLDER> --expect-bytes 16066560 --seeds \` block with one
     `bank_name=training/<filename> \` line per selected bank (bank_name = the ladder node
     name, matching the existing convention in D106-A/D109-A's pool builds — e.g.
     `gen2=training/v4_contested2_cap.bin`). Use `--checkpoint-dir` (default `training`) as
     the path prefix. Leave `<PLACEHOLDER>` literal (the caller fills in the league dir name
     + timestamp, as today).
   - `--print-launch-vars`: print `WARMSTART_FILE=training/<filename>` (resolved from the
     warm-start recommendation) as a shell-sourceable line, for use in a launch script.
6. For any selected node whose `b2_key` is non-null but whose local file
   `<checkpoint-dir>/<filename>` doesn't exist (best-effort `os.path.exists` check against
   the REPO-RELATIVE path — note this script likely runs on a remote box where
   `training/` is under `/root/bloodbowl-rl/`, so resolve relative to CWD, don't assume Mac
   paths), print a `# MISSING locally — fetch first:` comment with the rclone command
   (`rclone copyto bbr:bloodbowl-rl/checkpoints/<b2_key> training/<filename>`) ABOVE that
   bank's line in the `--print-build-league` output, so the operator can run the fetches
   before building.

## Self-test
The repo's current `tools/anchored_ladder.csv` (15 nodes, anchor=gen1) +
`docs/checkpoint_registry.json` (15 entries — note bc_v4 has `b2_key: null` and v5contested
is DEGENERATE) are real data — run the script against them with defaults
(`--tier1 3 --tier2 3 --diversity 1`, 1 floor = 8 total) and confirm:
- Floor = gen1.
- Warm-start recommendation = league5 (Elo +178.7, the current ladder-top).
- TIER1 should include league5, gen2, gen3 (the three highest non-degenerate, non-floor
  nodes per D109's fit: league5 178.7, gen2 101.2, gen3 98.3).
- bc_v4 and v5contested must NOT appear anywhere in the selected pool (DEGENERATE).
- Total selected banks == 8.

Run `python3 tools/build_pool_from_ladder.py` (defaults) and
`python3 tools/build_pool_from_ladder.py --print-build-league` and include both outputs in
your report. Also run with `--include kickoff8 --exclude exploiter1` to confirm
include/exclude override logic, and report that output too.

## Constraints
- Pure stdlib + whatever bt_fit.py already imports (no new dependencies).
- Don't modify bt_fit.py, tools/anchored_ladder.csv, or docs/checkpoint_registry.json.
- No network calls (the rclone-command suggestions are PRINTED, not executed).

## Report back
- Edit map (new file only).
- Full output of the three self-test invocations above.
- Any deviations from this brief, with reasoning.
- Anything in the ladder CSV or registry that looked inconsistent/surprising while
  implementing (do not fix, just report).
deprecated: `[features].collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml. See https://developers.openai.com/codex/config-basic#feature-flags for details.
codex
I’ll add the new tool in the existing `tools/` style, first checking `bt_fit.py` and `build_league.py` so the parser/printing conventions match the repo instead of guessing.
exec
/bin/zsh -lc "sed -n '1,220p' tools/build_league.py" in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc "sed -n '1,260p' tools/bt_fit.py" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
#!/usr/bin/env python3
"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.

100%-draw pairings carry no Bradley-Terry information, so they remain visible
in the raw read but are skipped for fitting.
"""
import argparse
import csv
import math
import sys
from collections import defaultdict, deque

try:
    import numpy as np  # noqa: F401
except Exception:
    np = None


EPS = 1e-12


def warn(msg):
    print(f"warning: {msg}", file=sys.stderr)


def parse_rows(path):
    rows = []
    with open(path, newline="") as f:
        reader = csv.DictReader(f)
        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
        for lineno, row in enumerate(reader, start=2):
            try:
                a = row["nameA"].strip()
                b = row["nameB"].strip()
                a_rate = float(row["A_rate"])
                b_rate = float(row["B_rate"])
                draw = float(row["draw_rate"])
                total = int(round(float(row["total_games"])))
            except (TypeError, ValueError) as e:
                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
            if not a or not b:
                warn(f"{path}:{lineno}: skipping row with empty name")
                continue
            rows.append({
                "a": a,
                "b": b,
                "a_rate": a_rate,
                "b_rate": b_rate,
                "draw": draw,
                "total": total,
                "lineno": lineno,
            })
    return rows


def decisive_counts(rows):
    names = []
    seen = set()
    wins = defaultdict(float)
    games = defaultdict(float)
    raw = {}
    skipped = []

    for row in rows:
        a, b = row["a"], row["b"]
        for name in (a, b):
            if name not in seen:
                seen.add(name)
                names.append(name)

        denom = 1.0 - row["draw"]
        if denom <= EPS:
            skipped.append((a, b, "all draws"))
            continue
        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
        p_a = max(0.0, min(1.0, p_a))
        n_decisive = int(round(row["total"] * denom))
        if n_decisive <= 0:
            skipped.append((a, b, "zero decisive games after rounding"))
            continue
        w_a = int(round(n_decisive * p_a))
        w_a = max(0, min(n_decisive, w_a))
        w_b = n_decisive - w_a

        wins[(a, b)] += w_a
        wins[(b, a)] += w_b
        games[frozenset((a, b))] += n_decisive
        raw[frozenset((a, b))] = {
            "a": a,
            "b": b,
            "w_a": w_a,
            "w_b": w_b,
            "n": n_decisive,
            "p_a": w_a / n_decisive,
        }

    return names, wins, games, raw, skipped


def score_counts(rows):
    names = []
    seen = set()
    wins = defaultdict(float)
    games = defaultdict(float)
    skipped = []

    for row in rows:
        a, b = row["a"], row["b"]
        for name in (a, b):
            if name not in seen:
                seen.add(name)
                names.append(name)

        total = float(row["total"])
        if total <= 0:
            skipped.append((a, b, "zero total games"))
            continue

        w_a = max(0.0, min(total, row["a_rate"] * total))
        w_b = max(0.0, min(total, row["b_rate"] * total))
        wins[(a, b)] += w_a
        wins[(b, a)] += w_b
        games[frozenset((a, b))] += total

    return names, wins, games, skipped


def row_decisive_summary(row):
    denom = 1.0 - row["draw"]
    if denom <= EPS:
        return None
    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
    p_a = max(0.0, min(1.0, p_a))
    n_decisive = int(round(row["total"] * denom))
    if n_decisive <= 0:
        return None
    w_a = int(round(n_decisive * p_a))
    w_a = max(0, min(n_decisive, w_a))
    return n_decisive, w_a, n_decisive - w_a, p_a


def wilson_interval(k, n, z=1.96):
    if n <= 0:
        return None
    phat = k / n
    denom = 1.0 + z * z / n
    center = (phat + z * z / (2.0 * n)) / denom
    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
    return center - half, center + half


def connected_components(fit_names, games):
    graph = {name: set() for name in fit_names}
    for pair, n in games.items():
        if n <= 0 or len(pair) != 2:
            continue
        a, b = tuple(pair)
        if a in graph and b in graph:
            graph[a].add(b)
            graph[b].add(a)

    comps = []
    unseen = set(fit_names)
    while unseen:
        start = unseen.pop()
        comp = []
        q = deque([start])
        while q:
            cur = q.popleft()
            comp.append(cur)
            for nxt in graph[cur]:
                if nxt in unseen:
                    unseen.remove(nxt)
                    q.append(nxt)
        comps.append(comp)
    return comps


def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
    pi = {name: 1.0 for name in fit_names}
    total_wins = {
        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
        for name in fit_names
    }

    for _ in range(max_iter):
        new = {}
        max_rel = 0.0
        for name in fit_names:
            denom = 0.0
            for other in fit_names:
                if other == name:
                    continue
                n_ij = games.get(frozenset((name, other)), 0.0)
                if n_ij:
                    denom += n_ij / (pi[name] + pi[other])
            if denom <= 0:
                new[name] = pi[name]
            elif total_wins[name] <= 0:
                new[name] = EPS
            else:
                new[name] = max(EPS, total_wins[name] / denom)
            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
        pi = new
        mean_pi = sum(pi.values()) / len(pi)
        if mean_pi > 0:
            pi = {name: val / mean_pi for name, val in pi.items()}
        if max_rel < tol:
            break
    return pi


def empirical_between(stronger, weaker, wins, games):
    n = games.get(frozenset((stronger, weaker)), 0.0)
    if not n:
        return None
    return wins.get((stronger, weaker), 0.0) / n, int(round(n))


def anchored_elo(fit_names, pi, anchor, scale):
    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
    anchor_elo = raw_elo[anchor]
    return {name: raw_elo[name] - anchor_elo for name in fit_names}


def full_residuals(raw, fit_names, pi):
    fit_set = set(fit_names)
    residuals = []
    for pair_raw in raw.values():
        a, b = pair_raw["a"], pair_raw["b"]
        if a not in fit_set or b not in fit_set:
            continue
        fit_p = pi[a] / (pi[a] + pi[b])
        empirical_p = pair_raw["p_a"]
        residuals.append({
            "a": a,
            "b": b,
            "fit_p": fit_p,
            "empirical_p": empirical_p,
            "n": pair_raw["n"],
            "abs_err": abs(fit_p - empirical_p),
        })
    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)


def print_score_table(rows, anchor, scale, decisive_order):
    score_names, score_wins, score_games, score_skipped = score_counts(rows)
    total_score_games = {
        name: sum(n for pair, n in score_games.items() if name in pair)
        for name in score_names
    }
    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
    if len(fit_score_names) < 2 or anchor not in fit_score_names:
        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
        print("skipped: need at least two score-connected anchors including anchor")
        return

 succeeded in 0ms:
#!/usr/bin/env python
"""Construct a pre-seeded heterogeneous league pool for a selfplay run.

Builds, BEFORE training, the exact on-disk pool layout that the vendored
selfplay pool consumes (vendor/PufferLib/pufferlib/selfplay.py — all line
numbers refer to the 4.0 pin, vendor/PINS.md 9836f0d):

    <out>/pool/                    selfplay.py:169
                                     pool_dir = os.path.join(
                                         args['checkpoint_dir'],
                                         args['env_name'], run_id, 'pool')
    <out>/pool/{i:016d}.bin        selfplay.py:171 and :247 name every pool
                                     entry f'{pufferl.global_step:016d}.bin'.
                                     Seeds take steps 0..N-1: a warm-started
                                     run's global_step counter restarts at 0
                                     and the first interval snapshot lands at
                                     >= snapshot_interval, so these names can
                                     never collide with run snapshots.
    <out>/pool/league_seeds.json   manifest consumed by the league_preseed
                                     branch added by
                                     training/selfplay_league.patch.

Why a patch + manifest are needed at all: stock setup() keeps pool state in
MEMORY ONLY (selfplay.py:197-211 returns the pool list; nothing on disk
indexes it) and it UNCONDITIONALLY bootstraps — selfplay.py:171-175 saves
the learner's current weights as '{global_step:016d}.bin' and loads that one
file into every frozen bank. There is no upstream path that reads a
pre-existing pool, hence training/selfplay_league.patch (skips the bootstrap
and seeds each bank from this manifest when [selfplay] league_preseed names
this pool dir).

Seed files must be CUDA flat-fp32 weight blobs — the save_weights format
(vendor/PufferLib/src/bindings.cu:180: raw fwrite of master_weights, no
header). pufferl_load_frozen_bank (vendor/PufferLib/src/pufferlib.cu:1830)
checks the byte size but only fprintf-warns and RETURNS on mismatch (the
bank silently keeps its previous weights), so this tool hard-verifies every
seed's size up front. 13,670,400 bytes = the bloodbowl policy (obs 1612 =
obs v3, heads {30,33,391}, hidden 512, 3 layers —
training/test_convert_checkpoint.py). Pre-cycle-2 (obs 832) seeds are a
dead lineage (12,072,960 bytes; archived in checkpoints-backup/) — pass
--expect-bytes 12072960 only to rebuild a historical 832 league.

Usage:
    tools/build_league.py --out <run-dir> --seeds name0=/path/a.bin \
        name1=/path/b.bin ... [--expect-bytes 13670400]

Seed order == frozen bank index (bank 0 = first --seeds entry). The patched
setup() also starts the opponent pool as exactly this list, oldest-first, so
sample_opponent's staleness weighting (selfplay.py:27-32) treats earlier
seeds as older history.
"""

import argparse
import datetime
import hashlib
import json
import os
import shutil
import sys

# Bloodbowl CUDA flat blob: 3,417,600 fp32 params (obs 1612 = obs v3 /
# heads {30,33,391} / hidden 512 / 3 layers). Size pinned by
# training/test_convert_checkpoint.py. The pre-cycle-2 obs-832 lineage
# (12,072,960 bytes, checkpoints-backup/) needs an explicit --expect-bytes.
DEFAULT_EXPECT_BYTES = 13_670_400

MANIFEST_NAME = 'league_seeds.json'


class LeagueError(RuntimeError):
    pass


def parse_seed_args(seed_args):
    '''['name=/path', ...] -> [(name, path), ...] preserving bank order.'''
    seeds = []
    names = set()
    for raw in seed_args:
        name, sep, path = raw.partition('=')
        if not sep or not name or not path:
            raise LeagueError(f'--seeds entry {raw!r} is not name=path')
        if name in names:
            raise LeagueError(f'duplicate seed name {name!r}')
        names.add(name)
        seeds.append((name, path))
    return seeds


def build_league(out_dir, seeds, expect_bytes=DEFAULT_EXPECT_BYTES):
    '''Create <out_dir>/pool with seed .bins + league_seeds.json.

    Returns the manifest dict. Raises LeagueError on any validation failure
    (missing seed, wrong size, pre-existing pool entries).
    '''
    if not seeds:
        raise LeagueError('at least one seed is required')

    # Validate sources before writing anything.
    sources = {}
    for name, path in seeds:
        if not os.path.isfile(path):
            raise LeagueError(f'seed {name!r}: {path} does not exist')
        size = os.path.getsize(path)
        if size != expect_bytes:
            raise LeagueError(
                f'seed {name!r}: {path} is {size} bytes, expected '
                f'{expect_bytes} (flat-fp32 save_weights blob — wrong arch '
                f'or a torch state_dict needing training/convert_checkpoint.py?)')
        real = os.path.realpath(path)
        if real in sources:
            print(f'warning: seed {name!r} duplicates source of '
                  f'{sources[real]!r} ({real})', file=sys.stderr)
        sources.setdefault(real, name)

    pool_dir = os.path.join(out_dir, 'pool')
    os.makedirs(pool_dir, exist_ok=True)
    leftovers = [f for f in os.listdir(pool_dir)
                 if f.endswith('.bin') or f == MANIFEST_NAME]
    if leftovers:
        raise LeagueError(
            f'{pool_dir} already contains pool entries {sorted(leftovers)} — '
            f'refusing to mix leagues; use a fresh --out dir')

    entries = []
    for bank, (name, path) in enumerate(seeds):
        # Naming convention: selfplay.py:171/:247 f'{global_step:016d}.bin'.
        fname = f'{bank:016d}.bin'
        dest = os.path.join(pool_dir, fname)
        shutil.copyfile(path, dest)
        with open(dest, 'rb') as f:
            blob = f.read()
        if len(blob) != expect_bytes:
            raise LeagueError(f'copy of seed {name!r} is {len(blob)} bytes')
        entries.append({
            'bank': bank,
            'name': name,
            'file': fname,
            'source': os.path.abspath(path),
            'bytes': len(blob),
            'sha256': hashlib.sha256(blob).hexdigest(),
        })

    manifest = {
        'version': 1,
        'created': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'expected_bytes': expect_bytes,
        'seeds': entries,
    }
    with open(os.path.join(pool_dir, MANIFEST_NAME), 'w') as f:
        json.dump(manifest, f, indent=2)
        f.write('\n')
    return manifest


def main(argv=None):
    ap = argparse.ArgumentParser(
        description='Build a pre-seeded heterogeneous selfplay league pool')
    ap.add_argument('--out', required=True,
        help='league run dir; pool/ is created inside it')
    ap.add_argument('--seeds', required=True, nargs='+', metavar='NAME=PATH',
        help='seed checkpoints in bank order (bank 0 first)')
    ap.add_argument('--expect-bytes', type=int, default=DEFAULT_EXPECT_BYTES,
        help='required size of every seed .bin (flat-fp32 blob; '
             f'default {DEFAULT_EXPECT_BYTES})')
    args = ap.parse_args(argv)

    try:
        seeds = parse_seed_args(args.seeds)
        manifest = build_league(args.out, seeds, args.expect_bytes)
    except LeagueError as e:
        print(f'build_league: {e}', file=sys.stderr)
        return 1

    pool_dir = os.path.join(args.out, 'pool')
    print(f'league pool: {pool_dir}')
    for s in manifest['seeds']:
        print(f"  bank {s['bank']}  {s['file']}  {s['name']}  "
              f"sha256 {s['sha256'][:12]}  <- {s['source']}")
    print(f"  {MANIFEST_NAME}  ({len(manifest['seeds'])} seeds, "
          f"{manifest['expected_bytes']} bytes each)")
    print('launch with: --selfplay.league-preseed ' + os.path.abspath(pool_dir)
          + f"  --vec.num-frozen-banks {len(manifest['seeds'])}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

exec
/bin/zsh -lc "head -n 20 tools/anchored_ladder.csv && sed -n '1,220p' docs/checkpoint_registry.json" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
nameA,nameB,A_rate,B_rate,draw_rate,total_games
bc_v4,kickoff8,0.201,0.799,0.402,2057
bc_v4,v5contested,0.349,0.651,0.698,2059
bc_v4,gen1,0.178,0.822,0.357,2056
bc_v4,gen2,0.135,0.865,0.271,2058
bc_v4,gen3,0.265,0.735,0.531,2048
bc_v4,league1,0.218,0.782,0.436,2059
kickoff8,v5contested,0.718,0.282,0.330,2057
kickoff8,gen1,0.371,0.629,0.328,2052
kickoff8,gen2,0.277,0.723,0.299,2051
kickoff8,gen3,0.360,0.640,0.407,2053
kickoff8,league1,0.346,0.654,0.376,2049
v5contested,gen1,0.233,0.767,0.298,2059
v5contested,gen2,0.136,0.864,0.224,2055
v5contested,gen3,0.239,0.761,0.348,2057
v5contested,league1,0.206,0.794,0.309,2056
gen1,gen2,0.369,0.631,0.337,2052
gen1,gen3,0.437,0.563,0.421,2053
gen1,league1,0.435,0.565,0.418,2057
gen2,gen3,0.530,0.470,0.404,2060
{
  "_comment": "Durable lookup table for the anchored ladder (tools/anchored_ladder.csv) and pool-building automation (tools/build_pool_from_ladder.py). Maps ladder node names to B2 checkpoint keys (bbr:bloodbowl-rl/checkpoints/<b2_key>), local training/ filenames, and one-line provenance. All entries are flat-fp32 CUDA blobs, 16066560 bytes (obs-v4, hidden 512x3, heads 30/33/391). Updated D111.",
  "_format_version": 1,
  "_ladder_csv": "tools/anchored_ladder.csv",
  "_decisions": "DECISIONS.md D90-D111 (contested era through hard-opponents doctrine)",
  "nodes": {
    "bc_v4": {
      "b2_key": null,
      "filename": "bc_v4_cuda.bin",
      "lineage": "human-imitation BC anchor",
      "elo_d109": -1571.4,
      "status": "degenerate (0% decisive vs everything, D98) -- floor candidate ONLY for BC-prior style diversity, no training signal"
    },
    "v5contested": {
      "b2_key": "v5_contested_cap.bin",
      "filename": "v5_contested_cap.bin",
      "lineage": "v5 path-actions/macro lineage, contested era",
      "elo_d109": -330.3,
      "status": "retired (macro retired D93) -- weak, near-degenerate"
    },
    "kickoff8": {
      "b2_key": "v4_kickoff9_cap.bin",
      "filename": "v4_kickoff9_cap.bin",
      "lineage": "v4 dead-teacher-era kickoff ladder, final (D92, the 9th and last dead-teacher record, tds 1.438)",
      "elo_d109": -111.5,
      "status": "diversity candidate -- old-era style, weak but stable"
    },
    "gen1": {
      "b2_key": "v4_contested_cap.bin",
      "filename": "v4_contested_cap.bin",
      "lineage": "v4-contested gen1 (D92/D93, warm=teacher=kickoff9 cap, 30B)",
      "elo_d109": 0.0,
      "status": "FLOOR anchor -- stable, non-degenerate reference point (anchor=gen1 in all ladder fits)"
    },
    "exploiter2": {
      "b2_key": "v4_exploiter2_cap.bin",
      "filename": "v4_exploiter2_cap.bin",
      "lineage": "H3 AlphaStar-exploiter, champion=exploiter1, warm=gen4 (D103, flat 0.504 vs champion)",
      "elo_d109": -31.7,
      "status": "diversity candidate -- weak overall but non-transitive (beats league4 despite -93.6 Elo gap, D107)"
    },
    "exploiter4": {
      "b2_key": "v4_exploiter4_cap.bin",
      "filename": "v4_exploiter4_cap.bin",
      "lineage": "H3 AlphaStar-exploiter, champion=league4, warm=gen1 (D108, flat 0.367 vs champion)",
      "elo_d109": 13.2,
      "status": "diversity candidate -- marginal vs gen1 warm-start, non-transitive (beats gen2/gen3 despite ~85-90 Elo gap, D108)"
    },
    "exploiter3": {
      "b2_key": "v4_exploiter3_cap.bin",
      "filename": "v4_exploiter3_cap.bin",
      "lineage": "H3 AlphaStar-exploiter, champion=exploiter1, warm=league2 (D106, flat 0.493 vs champion)",
      "elo_d109": 22.0,
      "status": "diversity candidate"
    },
    "gen2cont1": {
      "b2_key": "gen2cont1_cap.bin",
      "filename": "gen2cont1_cap.bin",
      "lineage": "ratchet-continuation diagnostic, TEACHER=WARM=gen2, exact gen2->gen3 recipe repeated (D110, regressed -57.3 Elo from gen2)",
      "elo_d109": 43.9,
      "status": "diversity candidate -- DEAD-END recipe (ratchet-vs-frozen-self from a tier1 checkpoint), retired as a warm-start/champion lineage per D110"
    },
    "league2": {
      "b2_key": "league2_cap.bin",
      "filename": "league2_cap.bin",
      "lineage": "league pool gen2, warm=league1, skillup exposure probe (D96-A/D99, lost to predecessor league1)",
      "elo_d109": 47.1,
      "status": "diversity candidate -- pool member of league5/6/6b"
    },
    "exploiter1": {
      "b2_key": "v4_exploiter1_cap.bin",
      "filename": "v4_exploiter1_cap.bin",
      "lineage": "H3 AlphaStar-exploiter, champion=gen2, warm=league1 (D102, SUCCESS: 0.587 vs champion, the only exploiter win)",
      "elo_d109": 58.0,
      "status": "TIER2/diversity -- pool member of league5/6/6b"
    },
    "league4": {
      "b2_key": "league4_cap.bin",
      "filename": "league4_cap.bin",
      "lineage": "league pool gen4, warm=league3 (D106, partial recovery from league2's dip, still below league1)",
      "elo_d109": 61.9,
      "status": "TIER2 -- superseded as a pool member by league5 in league6/6b (D109-A)"
    },
    "gen4": {
      "b2_key": "v4_contested4_cap.bin",
      "filename": "v4_contested4_cap.bin",
      "lineage": "v4-contested ratchet gen4, warm=teacher=gen3 (D100, landed within/below {gen2,gen3,league1} cluster -- ratchet plateau confirmed)",
      "elo_d109": 64.0,
      "status": "TIER2 -- pool member of league5/6/6b"
    },
    "league1": {
      "b2_key": "league_cap.bin",
      "filename": "league_cap.bin",
      "lineage": "league pool gen1, warm=v4-contested gen1 cap, first rotating-pool arm (D96, dead heat vs gen2-ratchet at matched steps)",
      "elo_d109": 77.5,
      "status": "TIER2 -- the league lineage's high-water-mark BEFORE league5 (league2-4 all below it)"
    },
    "gen3": {
      "b2_key": "v4_contested3_cap.bin",
      "filename": "v4_contested3_cap.bin",
      "lineage": "v4-contested ratchet gen3, warm=teacher=gen2 (D97/D98, the original tier1-tie with gen2 -- 6.1 Elo apart, noise-band)",
      "elo_d109": 98.3,
      "status": "TIER1/hard-opponent candidate -- pool member of league5/6/6b; warm-start for league6b (D109-A)"
    },
    "gen2": {
      "b2_key": "v4_contested2_cap.bin",
      "filename": "v4_contested2_cap.bin",
      "lineage": "v4-contested ratchet gen2, warm=teacher=gen1 (D95, the original +100 Elo jump, gen1->gen2)",
      "elo_d109": 101.2,
      "status": "TIER1/hard-opponent candidate -- pool member of league5/6/6b"
    },
    "league5": {
      "b2_key": "league5_cap.bin",
      "filename": "league5_cap.bin",
      "lineage": "league pool gen5, warm=league4, FIRST pool to include gen2+gen3 as opponents (D106-A)",
      "elo_d109": 178.7,
      "status": "TIER1/hard-opponent, ALL-TIME #1 (D109, +116.8 Elo jump from league4) -- warm-start for league6 (D109-A); the result that motivated D111's doctrine"
    }
  }
}

exec
/bin/zsh -lc 'git status --short' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
?? .codex-impl/
?? training/bc_v1.bin
?? training/bc_v15.bin
?? training/bc_v2.bin
?? training/bc_v2_cuda.bin
?? training/bc_v3b.bin

codex
`bt_fit.py` is safely importable: its fitting helpers sit above a guarded `main()`, so I can reuse the exact ladder math. I also noticed the registry has a prose “retired” tag on `gen2cont1`, which matters because the brief says substring classification, so I’ll preserve that behavior rather than special-casing intent.
exec
/bin/zsh -lc 'tail -n 90 tools/bt_fit.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
             + ", ".join(comps[0]))
        warn("excluded disconnected anchors: " + ", ".join(dropped))
        fit_names = [name for name in fit_names if name in keep]

    anchor = args.anchor
    if anchor is None:
        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
    if anchor not in fit_names:
        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")

    pi = fit_bt(fit_names, wins, games)
    elo = anchored_elo(fit_names, pi, anchor, args.scale)
    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)

    print("raw pair table")
    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
    print("-" * 83)
    for row in rows:
        summary = row_decisive_summary(row)
        if summary is None:
            decisive_s, p_s = "skip", "--"
        else:
            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
        print(f"{row['a'] + ' vs ' + row['b']:<35}"
              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
              f"{decisive_s:>11}{p_s:>10}")

    print()
    print(f"anchor: {anchor} = 0.0 Elo")
    print(f"scale: {args.scale:g}")
    print()
    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
    print("-" * 60)
    for name in ordered:
        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")

    print()
    print("adjacent fitted-vs-empirical decisive win rates")
    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
    print("-" * 67)
    for i in range(len(ordered) - 1):
        hi, lo = ordered[i], ordered[i + 1]
        fit_p = pi[hi] / (pi[hi] + pi[lo])
        emp = empirical_between(hi, lo, wins, games)
        if emp is None:
            emp_s, n_s = "--", "--"
        else:
            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")

    print()
    print("full pairwise residuals (decisive-Elo model)")
    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
    print("-" * 77)
    for r in full_residuals(raw, fit_names, pi):
        print(f"{r['a'] + ' vs ' + r['b']:<35}"
              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
              f"{r['n']:>8}{r['abs_err']:>10.3f}")

    print()
    print("Wilson 95% CI per pairing on decisive A win-rate")
    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
    print("-" * 73)
    for row in rows:
        summary = row_decisive_summary(row)
        if summary is None:
            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
        else:
            n_decisive, w_a, _, _ = summary
            ci = wilson_interval(w_a, n_decisive)
            p_s = f"{w_a / n_decisive:.3f}"
            lo_s = f"{ci[0]:.3f}"
            hi_s = f"{ci[1]:.3f}"
            n_s = str(n_decisive)
        print(f"{row['a'] + ' vs ' + row['b']:<35}"
              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")

    print()
    print_score_table(rows, anchor, args.scale, ordered)

    print()
    print_draw_matrix(rows, ordered, names)

    if excluded:
        print()
        print("excluded zero-information anchors: " + ", ".join(excluded))


if __name__ == "__main__":
    main()

exec
/bin/zsh -lc "ls -l training | sed -n '1,120p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
total 127536
-rw-r--r--@ 1 alexanderhuth  staff     14318 Jun  5 11:54 bc_pretrain.py
-rw-r--r--@ 1 alexanderhuth  staff  12080491 Jun  4 01:31 bc_v1.bin
-rw-r--r--@ 1 alexanderhuth  staff  12080506 Jun  4 15:44 bc_v15.bin
-rw-r--r--@ 1 alexanderhuth  staff  13677931 Jun  4 17:53 bc_v2.bin
-rw-r--r--@ 1 alexanderhuth  staff  13670400 Jun  4 17:53 bc_v2_cuda.bin
-rw-r--r--@ 1 alexanderhuth  staff  13678010 Jun  5 16:03 bc_v3b.bin
-rw-r--r--@ 1 alexanderhuth  staff     12113 Jun  8 09:29 convert_checkpoint.py
-rw-r--r--@ 1 alexanderhuth  staff      4876 Jun  5 16:18 puffer_dict_capacity.patch
-rw-r--r--@ 1 alexanderhuth  staff      4230 Jun  4 13:39 selfplay_league.patch
-rw-r--r--@ 1 alexanderhuth  staff      6279 Jun  4 07:37 test_bcreg_torch_pufferl.py
-rw-r--r--@ 1 alexanderhuth  staff      5808 Jun  4 17:53 test_convert_checkpoint.py
-rw-r--r--@ 1 alexanderhuth  staff     13598 Jun  4 13:39 test_selfplay_league.py
-rw-r--r--@ 1 alexanderhuth  staff     19587 Jun  7 03:14 torch_pufferl_bcreg.patch

exec
/bin/zsh -lc 'rg -n "build_pool_from_ladder|D111|hard-opponents|build_league.py --out" .' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 174ms:
./DECISIONS.md:213:**D111 — DOCTRINE: "HARD OPPONENTS" POOL-COMPOSITION PROTOCOL (codifying D109's lesson as a standing rule, not a one-off). The root cause of league1-4's non-monotonic drift was that NO league pool ever included the genuinely-strongest checkpoints as training opponents -- each generation trained against weaker/drifted descendants of itself. League5 (first pool to include gen2+gen3, the ladder-top at the time) produced the largest jump in program history (+116.8 Elo). GOING FORWARD, every new league/pool build follows this protocol:
./DECISIONS.md:225:AUTOMATION: tools/build_pool_from_ladder.py reads the committed ladder CSV + registry, applies the slot-allocation rule above (with override flags for diversity/floor picks), and emits the build_league.py seed-list + recommended warm-start -- turning "pick 8 checkpoints" from a manual judgment call into a mechanical step. Dispatching to codex now (.codex-impl/brief-pool-automation.md).
./tools/build_league.py:44:    tools/build_league.py --out <run-dir> --seeds name0=/path/a.bin \
./docs/checkpoint_registry.json:2:  "_comment": "Durable lookup table for the anchored ladder (tools/anchored_ladder.csv) and pool-building automation (tools/build_pool_from_ladder.py). Maps ladder node names to B2 checkpoint keys (bbr:bloodbowl-rl/checkpoints/<b2_key>), local training/ filenames, and one-line provenance. All entries are flat-fp32 CUDA blobs, 16066560 bytes (obs-v4, hidden 512x3, heads 30/33/391). Updated D111.",
./docs/checkpoint_registry.json:5:  "_decisions": "DECISIONS.md D90-D111 (contested era through hard-opponents doctrine)",
./docs/checkpoint_registry.json:117:      "status": "TIER1/hard-opponent, ALL-TIME #1 (D109, +116.8 Elo jump from league4) -- warm-start for league6 (D109-A); the result that motivated D111's doctrine"

codex
I’m going to create the script now. The key choices I’m baking in: import `bt_fit` directly, keep the 8-bank cap deterministic, warn rather than crash for registry/ladder mismatches, and print missing checkpoint fetch hints only as comments in the generated `build_league.py` block.
exec
/bin/zsh -lc "sed -n '220,360p' tools/bt_fit.py" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
    return wins.get((stronger, weaker), 0.0) / n, int(round(n))


def anchored_elo(fit_names, pi, anchor, scale):
    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
    anchor_elo = raw_elo[anchor]
    return {name: raw_elo[name] - anchor_elo for name in fit_names}


def full_residuals(raw, fit_names, pi):
    fit_set = set(fit_names)
    residuals = []
    for pair_raw in raw.values():
        a, b = pair_raw["a"], pair_raw["b"]
        if a not in fit_set or b not in fit_set:
            continue
        fit_p = pi[a] / (pi[a] + pi[b])
        empirical_p = pair_raw["p_a"]
        residuals.append({
            "a": a,
            "b": b,
            "fit_p": fit_p,
            "empirical_p": empirical_p,
            "n": pair_raw["n"],
            "abs_err": abs(fit_p - empirical_p),
        })
    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)


def print_score_table(rows, anchor, scale, decisive_order):
    score_names, score_wins, score_games, score_skipped = score_counts(rows)
    total_score_games = {
        name: sum(n for pair, n in score_games.items() if name in pair)
        for name in score_names
    }
    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
    if len(fit_score_names) < 2 or anchor not in fit_score_names:
        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
        print("skipped: need at least two score-connected anchors including anchor")
        return

    comps = connected_components(fit_score_names, score_games)
    if len(comps) > 1:
        keep = set(max(comps, key=len))
        fit_score_names = [name for name in fit_score_names if name in keep]
        if anchor not in fit_score_names:
            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
            print("skipped: anchor is not in the largest score-connected component")
            return

    score_pi = fit_bt(fit_score_names, score_wins, score_games)
    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
    ordered = sorted(
        fit_score_names,
        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
        reverse=True,
    )

    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
    print("-" * 60)
    for name in ordered:
        print(f"{name:<16}{score_elo[name]:>10.1f}"
              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
    for a, b, why in score_skipped:
        warn(f"skipping {a} vs {b} for score fit: {why}")


def print_draw_matrix(rows, ordered, all_names):
    draw_by_pair = {}
    for row in rows:
        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]

    ordered_set = set(ordered)
    names = list(ordered) + [name for name in all_names if name not in ordered_set]
    width = max(8, max(len(name) for name in names) + 1) if names else 8
    print("draw-rate matrix")
    print(" " * width + "".join(f"{name:>{width}}" for name in names))
    for a in names:
        cells = []
        for b in names:
            if a == b:
                cells.append("--")
            else:
                draw = draw_by_pair.get(frozenset((a, b)))
                cells.append("--" if draw is None else f"{draw:.3f}")
        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))


def main():
    ap = argparse.ArgumentParser(
        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
    ap.add_argument("--scale", type=float, default=400.0,
                    help="Elo display scale, default 400")
    args = ap.parse_args()

    if np is None:
        warn("numpy unavailable; using pure Python math fallback")

    rows = parse_rows(args.csv_path)
    if not rows:
        raise SystemExit("no CSV rows found")

    names, wins, games, raw, skipped = decisive_counts(rows)
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
        raise SystemExit("need at least two connected anchors with decisive games")

    comps = connected_components(fit_names, games)
    if len(comps) > 1:
        comps = sorted(comps, key=len, reverse=True)
        keep = set(comps[0])
        dropped = sorted(name for comp in comps[1:] for name in comp)
        warn("decisive graph is disconnected; fitting largest component only: "
             + ", ".join(comps[0]))
        warn("excluded disconnected anchors: " + ", ".join(dropped))
        fit_names = [name for name in fit_names if name in keep]

    anchor = args.anchor
    if anchor is None:
        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
    if anchor not in fit_names:
        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")

    pi = fit_bt(fit_names, wins, games)
    elo = anchored_elo(fit_names, pi, anchor, args.scale)
    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)

exec
/bin/zsh -lc "find tools -maxdepth 1 -type f -name '*.py' -print | sort | xargs -n 1 basename" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
bt_fit.py
build_league.py
codegen.py
game_stats.py
human_possession.py
parity_report.py
per_team_baseline.py
stage_spectator_art.py

codex
A small semantic wrinkle surfaced: `--exclude` says “never select,” while warm-start is not a pool slot. I’m treating excludes as pool-selection only, so the warm-start remains the ladder-top non-degenerate checkpoint exactly as D107-A says.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/build_pool_from_ladder.py
diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..3fc486e96f087c168b12be15ec6d5bdd375d5b22
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,372 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate) -> None:
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, training/{warmstart.filename})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        if c.b2_key and not os.path.exists(path):
+            print("# MISSING locally -- fetch first:")
+            print(f"# rclone copyto bbr:bloodbowl-rl/checkpoints/{c.b2_key} {path}")
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..3fc486e96f087c168b12be15ec6d5bdd375d5b22
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,372 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate) -> None:
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, training/{warmstart.filename})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        if c.b2_key and not os.path.exists(path):
+            print("# MISSING locally -- fetch first:")
+            print(f"# rclone copyto bbr:bloodbowl-rl/checkpoints/{c.b2_key} {path}")
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
The file is in place. I’m running the requested self-tests now; if the output exposes an allocation mismatch, I’ll tighten the selection logic before reporting.
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py' in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --include kickoff8 --exclude exploiter1' in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --print-build-league' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

build_league command:
python3 tools/build_league.py \
  --out <PLACEHOLDER> \
  --expect-bytes 16066560 \
  --seeds \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested_cap.bin training/v4_contested_cap.bin
  gen1=training/v4_contested_cap.bin \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league5_cap.bin training/league5_cap.bin
  league5=training/league5_cap.bin \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested2_cap.bin training/v4_contested2_cap.bin
  gen2=training/v4_contested2_cap.bin \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested3_cap.bin training/v4_contested3_cap.bin
  gen3=training/v4_contested3_cap.bin \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league_cap.bin training/league_cap.bin
  league1=training/league_cap.bin \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested4_cap.bin training/v4_contested4_cap.bin
  gen4=training/v4_contested4_cap.bin \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league4_cap.bin training/league4_cap.bin
  league4=training/league4_cap.bin \
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_exploiter1_cap.bin training/v4_exploiter1_cap.bin
  exploiter1=training/v4_exploiter1_cap.bin

 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  kickoff8         -111.5  v4_kickoff9_cap.bin        v4_kickoff9_cap.bin          INCLUDE   
   1  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   2  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   3  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   4  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   5  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   6  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   7  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     

selected banks: 8

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..3fc486e96f087c168b12be15ec6d5bdd375d5b22
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,372 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate) -> None:
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, training/{warmstart.filename})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        if c.b2_key and not os.path.exists(path):
+            print("# MISSING locally -- fetch first:")
+            print(f"# rclone copyto bbr:bloodbowl-rl/checkpoints/{c.b2_key} {path}")
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
The default self-test hits the expected Elo ordering and 8 banks. I found one practical shell-copy issue in my generated command: comments inserted inside a backslash continuation can be awkward to paste, so I’m adjusting the print shape while keeping the requested “comment above that bank line” behavior.
exec
/bin/zsh -lc "printf 'python3 -c \"import sys; print(sys.argv)\" \\\\\\n# hi \\\\\\na\\n' > /tmp/test_comments.sh && bash /tmp/test_comments.sh" in /Users/alexanderhuth/Code/bloodbowl-rl
 exited 127 in 0ms:
['-c']
/tmp/test_comments.sh: line 3: a: command not found

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..3fc486e96f087c168b12be15ec6d5bdd375d5b22
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,372 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate) -> None:
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, training/{warmstart.filename})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        if c.b2_key and not os.path.exists(path):
+            print("# MISSING locally -- fetch first:")
+            print(f"# rclone copyto bbr:bloodbowl-rl/checkpoints/{c.b2_key} {path}")
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
I’m keeping the build command itself pasteable. For missing local checkpoints, the script will now print fetch comments in a short preflight section, then emit a clean `build_league.py` command block. That is a tiny formatting deviation from the literal “above bank line” wording, but it avoids generating a command that looks pasteable and then breaks in the shell.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/build_pool_from_ladder.py
diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..06c0cefa8d9f37343450ea5278d6d87470f2f036
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..06c0cefa8d9f37343450ea5278d6d87470f2f036
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
The formatting fix is in. I’m rerunning the three requested invocations plus a syntax check so the final report has the actual outputs from the final file.
exec
/bin/zsh -lc 'python3 -m py_compile tools/build_pool_from_ladder.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --print-build-league' in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

missing checkpoint fetches:
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested_cap.bin training/v4_contested_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league5_cap.bin training/league5_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested2_cap.bin training/v4_contested2_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested3_cap.bin training/v4_contested3_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league_cap.bin training/league_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested4_cap.bin training/v4_contested4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league4_cap.bin training/league4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_exploiter1_cap.bin training/v4_exploiter1_cap.bin

build_league command:
python3 tools/build_league.py \
  --out <PLACEHOLDER> \
  --expect-bytes 16066560 \
  --seeds \
  gen1=training/v4_contested_cap.bin \
  league5=training/league5_cap.bin \
  gen2=training/v4_contested2_cap.bin \
  gen3=training/v4_contested3_cap.bin \
  league1=training/league_cap.bin \
  gen4=training/v4_contested4_cap.bin \
  league4=training/league4_cap.bin \
  exploiter1=training/v4_exploiter1_cap.bin

exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --include kickoff8 --exclude exploiter1' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  kickoff8         -111.5  v4_kickoff9_cap.bin        v4_kickoff9_cap.bin          INCLUDE   
   1  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   2  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   3  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   4  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   5  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   6  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   7  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     

selected banks: 8

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..06c0cefa8d9f37343450ea5278d6d87470f2f036
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
The requested outputs are stable now: floor is `gen1`, warm-start is `league5`, the top three hard opponents are `league5/gen2/gen3`, and the degenerate/retired nodes stay out of the selected pool. I’m doing one last repo-state check and a quick glance at the new file before I wrap it up.
exec
/bin/zsh -lc 'git status --short' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
?? .codex-impl/
?? tools/build_pool_from_ladder.py
?? training/bc_v1.bin
?? training/bc_v15.bin
?? training/bc_v2.bin
?? training/bc_v2_cuda.bin
?? training/bc_v3b.bin

exec
/bin/zsh -lc "nl -ba tools/build_pool_from_ladder.py | sed -n '1,260p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
     1	#!/usr/bin/env python3
     2	"""Build a D111 hard-opponents league pool from the live anchored ladder.
     3	
     4	D111 turned pool composition from a hand-picked judgment call into a mechanical
     5	step: every new 8-bank league should mix current ladder-top hard opponents,
     6	second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
     7	The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
     8	registry. This tool refits Elo from the CSV each time, applies the D111 slot
     9	doctrine, and prints both a human audit table and ready-to-paste launch/build
    10	snippets for operators.
    11	"""
    12	
    13	import argparse
    14	import json
    15	import os
    16	import sys
    17	from dataclasses import dataclass
    18	from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
    19	
    20	from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
    21	
    22	
    23	DEFAULT_LADDER = "tools/anchored_ladder.csv"
    24	DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
    25	DEFAULT_ANCHOR = "gen1"
    26	DEFAULT_CHECKPOINT_DIR = "training"
    27	DEFAULT_EXPECT_BYTES = 16_066_560
    28	ELO_SCALE = 400.0
    29	POOL_BANKS = 8
    30	
    31	
    32	class PoolError(RuntimeError):
    33	    pass
    34	
    35	
    36	@dataclass(frozen=True)
    37	class Candidate:
    38	    name: str
    39	    elo: float
    40	    filename: str
    41	    b2_key: Optional[str]
    42	    classification: str
    43	
    44	
    45	@dataclass(frozen=True)
    46	class Pick:
    47	    candidate: Candidate
    48	    slot: str
    49	
    50	
    51	def warn(msg: str) -> None:
    52	    print(f"warning: {msg}", file=sys.stderr)
    53	
    54	
    55	def classify_status(status: object) -> str:
    56	    text = str(status or "").lower()
    57	    if "floor" in text:
    58	        return "FLOOR"
    59	    if "degenerate" in text or "retired" in text:
    60	        return "DEGENERATE"
    61	    if "diversity" in text:
    62	        return "DIVERSITY_CANDIDATE"
    63	    return "TIER1_CANDIDATE"
    64	
    65	
    66	def load_registry(path: str) -> Dict[str, dict]:
    67	    with open(path) as f:
    68	        data = json.load(f)
    69	    nodes = data.get("nodes")
    70	    if not isinstance(nodes, dict):
    71	        raise PoolError(f"{path}: missing object field 'nodes'")
    72	    return nodes
    73	
    74	
    75	def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
    76	    rows = parse_rows(path)
    77	    if not rows:
    78	        raise PoolError(f"{path}: no CSV rows found")
    79	
    80	    names, wins, games, _raw, skipped = decisive_counts(rows)
    81	    total_decisive = {
    82	        name: sum(n for pair, n in games.items() if name in pair)
    83	        for name in names
    84	    }
    85	    excluded = [name for name in names if total_decisive[name] <= 0]
    86	    for name in excluded:
    87	        warn(f"excluding {name}: zero decisive games vs everyone")
    88	    for a, b, why in skipped:
    89	        warn(f"skipping {a} vs {b} for fit: {why}")
    90	
    91	    fit_names = [name for name in names if name not in set(excluded)]
    92	    if len(fit_names) < 2:
    93	        raise PoolError("need at least two connected anchors with decisive games")
    94	
    95	    comps = connected_components(fit_names, games)
    96	    if len(comps) > 1:
    97	        comps = sorted(comps, key=len, reverse=True)
    98	        keep = set(comps[0])
    99	        dropped = sorted(name for comp in comps[1:] for name in comp)
   100	        warn("decisive graph is disconnected; fitting largest component only: "
   101	             + ", ".join(comps[0]))
   102	        warn("excluded disconnected anchors: " + ", ".join(dropped))
   103	        fit_names = [name for name in fit_names if name in keep]
   104	
   105	    if anchor not in fit_names:
   106	        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
   107	
   108	    pi = fit_bt(fit_names, wins, games)
   109	    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
   110	
   111	
   112	def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
   113	    ladder_names = set(elo)
   114	    registry_names = set(registry)
   115	
   116	    for name in sorted(ladder_names - registry_names):
   117	        warn(f"ladder node {name!r} missing from registry; skipping")
   118	    for name in sorted(registry_names - ladder_names):
   119	        if name.startswith("_"):
   120	            continue
   121	        warn(f"registry node {name!r} missing from ladder fit; skipping")
   122	
   123	    candidates = []
   124	    for name in sorted(ladder_names & registry_names):
   125	        entry = registry[name]
   126	        if not isinstance(entry, dict):
   127	            warn(f"registry node {name!r} is not an object; skipping")
   128	            continue
   129	        filename = entry.get("filename")
   130	        if not filename:
   131	            warn(f"registry node {name!r} missing filename; skipping")
   132	            continue
   133	        b2_key = entry.get("b2_key")
   134	        if b2_key is not None and not isinstance(b2_key, str):
   135	            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
   136	            b2_key = None
   137	        candidates.append(Candidate(
   138	            name=name,
   139	            elo=elo[name],
   140	            filename=str(filename),
   141	            b2_key=b2_key,
   142	            classification=classify_status(entry.get("status", "")),
   143	        ))
   144	    return candidates
   145	
   146	
   147	def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
   148	    return sorted(candidates, key=lambda c: c.elo, reverse=True)
   149	
   150	
   151	def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
   152	    out = []
   153	    seen = set()
   154	    for node in nodes or []:
   155	        if node not in seen:
   156	            seen.add(node)
   157	            out.append(node)
   158	    return out
   159	
   160	
   161	def append_pick(
   162	    picks: List[Pick],
   163	    used: Set[str],
   164	    candidate: Candidate,
   165	    slot: str,
   166	    cap: int = POOL_BANKS,
   167	) -> bool:
   168	    if candidate.name in used or len(picks) >= cap:
   169	        return False
   170	    picks.append(Pick(candidate, slot))
   171	    used.add(candidate.name)
   172	    return True
   173	
   174	
   175	def select_pool(
   176	    candidates: Sequence[Candidate],
   177	    tier1_count: int,
   178	    tier2_count: int,
   179	    requested_diversity: int,
   180	    include: Sequence[str],
   181	    exclude: Sequence[str],
   182	) -> List[Pick]:
   183	    by_name = {c.name: c for c in candidates}
   184	    include_nodes = unique_nodes(include)
   185	    exclude_set = set(exclude or [])
   186	    if len(include_nodes) > POOL_BANKS:
   187	        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
   188	    included_excluded = [name for name in include_nodes if name in exclude_set]
   189	    if included_excluded:
   190	        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
   191	
   192	    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
   193	    selectable = [c for c in nondegenerate if c.name not in exclude_set]
   194	    selectable_by_name = {c.name: c for c in selectable}
   195	
   196	    picks: List[Pick] = []
   197	    used: Set[str] = set()
   198	
   199	    for name in include_nodes:
   200	        candidate = by_name.get(name)
   201	        if candidate is None:
   202	            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
   203	        if candidate.classification == "DEGENERATE":
   204	            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
   205	        append_pick(picks, used, candidate, "INCLUDE")
   206	
   207	    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
   208	    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
   209	    if floor_pick is None:
   210	        warn("no FLOOR-tagged candidate available")
   211	    else:
   212	        append_pick(picks, used, floor_pick, "FLOOR")
   213	
   214	    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
   215	    tier1_pool = tier_pool[:tier1_count]
   216	    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
   217	
   218	    desired_before_diversity = 1 + tier1_count + tier2_count
   219	    remaining_after_requested = POOL_BANKS - desired_before_diversity
   220	    if remaining_after_requested >= requested_diversity:
   221	        diversity_count = remaining_after_requested
   222	    else:
   223	        diversity_count = requested_diversity
   224	        if desired_before_diversity + requested_diversity > POOL_BANKS:
   225	            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
   226	
   227	    for candidate in tier1_pool:
   228	        append_pick(picks, used, candidate, "TIER1")
   229	    for candidate in tier2_pool:
   230	        append_pick(picks, used, candidate, "TIER2")
   231	
   232	    diversity_pool = ordered_by_elo(
   233	        c for c in selectable
   234	        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
   235	    )
   236	    diversity_added = 0
   237	    for candidate in diversity_pool:
   238	        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
   239	            break
   240	        if append_pick(picks, used, candidate, "DIVERSITY"):
   241	            diversity_added += 1
   242	
   243	    if len(picks) < POOL_BANKS:
   244	        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
   245	        for candidate in fallback_pool:
   246	            if len(picks) >= POOL_BANKS:
   247	                break
   248	            append_pick(picks, used, candidate, fallback_slot(candidate))
   249	
   250	    if len(picks) < POOL_BANKS:
   251	        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
   252	
   253	    return picks
   254	
   255	
   256	def fallback_slot(candidate: Candidate) -> str:
   257	    if candidate.classification == "FLOOR":
   258	        return "FLOOR"
   259	    if candidate.classification == "DIVERSITY_CANDIDATE":
   260	        return "DIVERSITY"

exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --print-launch-vars' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

WARMSTART_FILE=training/league5_cap.bin

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..06c0cefa8d9f37343450ea5278d6d87470f2f036
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
One small cleanup: I spotted an unused type import while reviewing the file, so I’m removing it before the final state.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/build_pool_from_ladder.py
diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..079f083065e9ef63de66fb6ea9da41d059923926
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..079f083065e9ef63de66fb6ea9da41d059923926
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
Cleanup is done; I’m running the syntax check one more time.
exec
/bin/zsh -lc 'python3 -m py_compile tools/build_pool_from_ladder.py && git status --short' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
?? .codex-impl/
?? tools/build_pool_from_ladder.py
?? training/bc_v1.bin
?? training/bc_v15.bin
?? training/bc_v2.bin
?? training/bc_v2_cuda.bin
?? training/bc_v3b.bin

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..079f083065e9ef63de66fb6ea9da41d059923926
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "floor" in text:
+        return "FLOOR"
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
I caught one important registry-prose edge case before finalizing: `bc_v4` contains both “degenerate” and “floor candidate” in its status, while the brief explicitly expects it excluded as degenerate. I’m giving degenerate/retired precedence over floor when both substrings appear.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/build_pool_from_ladder.py
diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..e6b99ba21257295aeddd79aaf55b1b60ca7c5121
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..e6b99ba21257295aeddd79aaf55b1b60ca7c5121
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
That precedence fix is in. I’m rerunning the required outputs once more; the visible default pool should remain the same, but the internal eligibility now matches the D98/D111 intent for `bc_v4`.
exec
/bin/zsh -lc 'python3 -m py_compile tools/build_pool_from_ladder.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py' in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --print-build-league' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
warning: no FLOOR-tagged candidate available
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   1  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   2  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   3  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   4  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   5  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   6  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 
   7  league2           +47.1  league2_cap.bin            league2_cap.bin              DIVERSITY 

selected banks: 8

missing checkpoint fetches:
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league5_cap.bin training/league5_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested2_cap.bin training/v4_contested2_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested3_cap.bin training/v4_contested3_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league_cap.bin training/league_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested4_cap.bin training/v4_contested4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league4_cap.bin training/league4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_exploiter1_cap.bin training/v4_exploiter1_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league2_cap.bin training/league2_cap.bin

build_league command:
python3 tools/build_league.py \
  --out <PLACEHOLDER> \
  --expect-bytes 16066560 \
  --seeds \
  league5=training/league5_cap.bin \
  gen2=training/v4_contested2_cap.bin \
  gen3=training/v4_contested3_cap.bin \
  league1=training/league_cap.bin \
  gen4=training/v4_contested4_cap.bin \
  league4=training/league4_cap.bin \
  exploiter1=training/v4_exploiter1_cap.bin \
  league2=training/league2_cap.bin

 succeeded in 0ms:
warning: no FLOOR-tagged candidate available
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   1  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   2  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   3  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   4  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   5  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   6  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 
   7  league2           +47.1  league2_cap.bin            league2_cap.bin              DIVERSITY 

selected banks: 8

exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --include kickoff8 --exclude exploiter1' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
warning: no FLOOR-tagged candidate available
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  kickoff8         -111.5  v4_kickoff9_cap.bin        v4_kickoff9_cap.bin          INCLUDE   
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  league2           +47.1  league2_cap.bin            league2_cap.bin              DIVERSITY 

selected banks: 8

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..e6b99ba21257295aeddd79aaf55b1b60ca7c5121
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower()
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
The registry has another prose trap: `gen1` says “non-degenerate,” which a raw substring search sees as “degenerate.” I’m normalizing that phrase away before classification so `gen1` remains the floor anchor while `bc_v4` is still excluded as degenerate.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/build_pool_from_ladder.py
diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..a81629b4f4eb1c8b4a3a5faf3f8bcbde81b49d71
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower().replace("non-degenerate", "")
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..a81629b4f4eb1c8b4a3a5faf3f8bcbde81b49d71
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower().replace("non-degenerate", "")
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
That normalization is in; rerunning the required tests again. This is the sort of tiny prose/data mismatch that makes automation worth having, honestly.
exec
/bin/zsh -lc 'python3 -m py_compile tools/build_pool_from_ladder.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py' in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --print-build-league' in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc 'python3 tools/build_pool_from_ladder.py --include kickoff8 --exclude exploiter1' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

missing checkpoint fetches:
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested_cap.bin training/v4_contested_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league5_cap.bin training/league5_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested2_cap.bin training/v4_contested2_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested3_cap.bin training/v4_contested3_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league_cap.bin training/league_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested4_cap.bin training/v4_contested4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league4_cap.bin training/league4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_exploiter1_cap.bin training/v4_exploiter1_cap.bin

build_league command:
python3 tools/build_league.py \
  --out <PLACEHOLDER> \
  --expect-bytes 16066560 \
  --seeds \
  gen1=training/v4_contested_cap.bin \
  league5=training/league5_cap.bin \
  gen2=training/v4_contested2_cap.bin \
  gen3=training/v4_contested3_cap.bin \
  league1=training/league_cap.bin \
  gen4=training/v4_contested4_cap.bin \
  league4=training/league4_cap.bin \
  exploiter1=training/v4_exploiter1_cap.bin

 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

 succeeded in 0ms:
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  kickoff8         -111.5  v4_kickoff9_cap.bin        v4_kickoff9_cap.bin          INCLUDE   
   1  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   2  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   3  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   4  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   5  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   6  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   7  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     

selected banks: 8

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..a81629b4f4eb1c8b4a3a5faf3f8bcbde81b49d71
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower().replace("non-degenerate", "")
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
The final runs match the brief’s self-test expectations now. I’ll check the worktree one last time so I can separate my one new file from the pre-existing untracked files in the report.
exec
/bin/zsh -lc 'git status --short' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
?? .codex-impl/
?? tools/build_pool_from_ladder.py
?? training/bc_v1.bin
?? training/bc_v15.bin
?? training/bc_v2.bin
?? training/bc_v2_cuda.bin
?? training/bc_v3b.bin

diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..a81629b4f4eb1c8b4a3a5faf3f8bcbde81b49d71
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower().replace("non-degenerate", "")
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

codex
Implemented [tools/build_pool_from_ladder.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/build_pool_from_ladder.py). No commit made.

**Edit Map**

Added one new file only:

`tools/build_pool_from_ladder.py`

It:

- Imports `parse_rows`, `decisive_counts`, `fit_bt`, `connected_components`, and `anchored_elo` from `tools/bt_fit.py`.
- Refits the ladder live from `tools/anchored_ladder.csv` with `gen1` anchored at `0.0`.
- Loads `docs/checkpoint_registry.json`.
- Classifies registry prose tags into floor, tier candidates, diversity candidates, and degenerate/retired exclusions.
- Selects an 8-bank D111 pool with floor, tier1, tier2, diversity, include, and exclude handling.
- Prints the ladder-top warm-start recommendation across all non-degenerate nodes.
- Emits `build_league.py` command text and missing-local-file rclone fetch comments.
- Emits `WARMSTART_FILE=...` for `--print-launch-vars`.

Validation run:

```text
python3 -m py_compile tools/build_pool_from_ladder.py
```

passed.

**Self-Test 1**

Command:

```bash
python3 tools/build_pool_from_ladder.py
```

Output:

```text
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8
```

Confirmed from this run:

- Floor is `gen1`.
- Warm-start recommendation is `league5` at `+178.7`.
- TIER1 is `league5`, `gen2`, `gen3`.
- `bc_v4` and `v5contested` do not appear.
- Total selected banks is `8`.

**Self-Test 2**

Command:

```bash
python3 tools/build_pool_from_ladder.py --print-build-league
```

Output:

```text
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

missing checkpoint fetches:
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested_cap.bin training/v4_contested_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league5_cap.bin training/league5_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested2_cap.bin training/v4_contested2_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested3_cap.bin training/v4_contested3_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league_cap.bin training/league_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested4_cap.bin training/v4_contested4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league4_cap.bin training/league4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_exploiter1_cap.bin training/v4_exploiter1_cap.bin

build_league command:
python3 tools/build_league.py \
  --out <PLACEHOLDER> \
  --expect-bytes 16066560 \
  --seeds \
  gen1=training/v4_contested_cap.bin \
  league5=training/league5_cap.bin \
  gen2=training/v4_contested2_cap.bin \
  gen3=training/v4_contested3_cap.bin \
  league1=training/league_cap.bin \
  gen4=training/v4_contested4_cap.bin \
  league4=training/league4_cap.bin \
  exploiter1=training/v4_exploiter1_cap.bin
```

**Self-Test 3**

Command:

```bash
python3 tools/build_pool_from_ladder.py --include kickoff8 --exclude exploiter1
```

Output:

```text
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  kickoff8         -111.5  v4_kickoff9_cap.bin        v4_kickoff9_cap.bin          INCLUDE   
   1  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   2  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   3  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   4  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   5  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   6  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   7  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     

selected banks: 8
```

This confirms `kickoff8` is forced in, `exploiter1` is excluded, the pool remains capped at 8, and the warm-start remains the global ladder-top `league5`.

**Deviations / Notes**

One deliberate formatting deviation: the brief asked missing-checkpoint comments to appear immediately above each affected bank line inside the `--print-build-league` output. I printed them in a `missing checkpoint fetches:` preflight section before the command instead. Reason: shell comments inside a backslash-continued command make the supposedly ready-to-paste command fragile or invalid. The generated `build_league.py` block is now cleanly pasteable, and the fetch commands are still printed directly above it.

One classification nuance: I normalized the phrase `non-degenerate` before matching `degenerate`, because the `gen1` status says “non-degenerate reference point” and must remain `FLOOR`. I also let explicit `degenerate`/`retired` take precedence over incidental floor wording, so `bc_v4` remains excluded even though its prose contains “floor candidate.”

**Registry / Ladder Surprises**

A few prose-tag wrinkles stood out:

- `bc_v4` status contains both `degenerate` and `floor candidate`; the self-test expectation makes clear it should be treated as degenerate/excluded, not as the floor.
- `gen1` status contains `non-degenerate`, which would match a naive raw substring search for `degenerate`.
- `gen2cont1` has `diversity candidate` prose but also says `retired`; with the requested retired/degenerate exclusion doctrine, it is excluded from selection.
- `exploiter1` has status `TIER2/diversity`; by substring classification it becomes a diversity candidate, which is why it fills the default diversity slot.

Worktree note: pre-existing untracked files were left untouched. Current new file from this task is only `tools/build_pool_from_ladder.py`; the other untracked entries shown by `git status` were already present or unrelated.
diff --git a/tools/build_pool_from_ladder.py b/tools/build_pool_from_ladder.py
new file mode 100644
index 0000000000000000000000000000000000000000..a81629b4f4eb1c8b4a3a5faf3f8bcbde81b49d71
--- /dev/null
+++ b/tools/build_pool_from_ladder.py
@@ -0,0 +1,384 @@
+#!/usr/bin/env python3
+"""Build a D111 hard-opponents league pool from the live anchored ladder.
+
+D111 turned pool composition from a hand-picked judgment call into a mechanical
+step: every new 8-bank league should mix current ladder-top hard opponents,
+second-tier pressure, stylistic diversity, and the stable gen1 floor anchor.
+The durable inputs are the raw Bradley-Terry pairing CSV plus the checkpoint
+registry. This tool refits Elo from the CSV each time, applies the D111 slot
+doctrine, and prints both a human audit table and ready-to-paste launch/build
+snippets for operators.
+"""
+
+import argparse
+import json
+import os
+import sys
+from dataclasses import dataclass
+from typing import Dict, Iterable, List, Optional, Sequence, Set
+
+from bt_fit import anchored_elo, connected_components, decisive_counts, fit_bt, parse_rows
+
+
+DEFAULT_LADDER = "tools/anchored_ladder.csv"
+DEFAULT_REGISTRY = "docs/checkpoint_registry.json"
+DEFAULT_ANCHOR = "gen1"
+DEFAULT_CHECKPOINT_DIR = "training"
+DEFAULT_EXPECT_BYTES = 16_066_560
+ELO_SCALE = 400.0
+POOL_BANKS = 8
+
+
+class PoolError(RuntimeError):
+    pass
+
+
+@dataclass(frozen=True)
+class Candidate:
+    name: str
+    elo: float
+    filename: str
+    b2_key: Optional[str]
+    classification: str
+
+
+@dataclass(frozen=True)
+class Pick:
+    candidate: Candidate
+    slot: str
+
+
+def warn(msg: str) -> None:
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def classify_status(status: object) -> str:
+    text = str(status or "").lower().replace("non-degenerate", "")
+    if "degenerate" in text or "retired" in text:
+        return "DEGENERATE"
+    if "floor" in text:
+        return "FLOOR"
+    if "diversity" in text:
+        return "DIVERSITY_CANDIDATE"
+    return "TIER1_CANDIDATE"
+
+
+def load_registry(path: str) -> Dict[str, dict]:
+    with open(path) as f:
+        data = json.load(f)
+    nodes = data.get("nodes")
+    if not isinstance(nodes, dict):
+        raise PoolError(f"{path}: missing object field 'nodes'")
+    return nodes
+
+
+def fit_ladder(path: str, anchor: str) -> Dict[str, float]:
+    rows = parse_rows(path)
+    if not rows:
+        raise PoolError(f"{path}: no CSV rows found")
+
+    names, wins, games, _raw, skipped = decisive_counts(rows)
+    total_decisive = {
+        name: sum(n for pair, n in games.items() if name in pair)
+        for name in names
+    }
+    excluded = [name for name in names if total_decisive[name] <= 0]
+    for name in excluded:
+        warn(f"excluding {name}: zero decisive games vs everyone")
+    for a, b, why in skipped:
+        warn(f"skipping {a} vs {b} for fit: {why}")
+
+    fit_names = [name for name in names if name not in set(excluded)]
+    if len(fit_names) < 2:
+        raise PoolError("need at least two connected anchors with decisive games")
+
+    comps = connected_components(fit_names, games)
+    if len(comps) > 1:
+        comps = sorted(comps, key=len, reverse=True)
+        keep = set(comps[0])
+        dropped = sorted(name for comp in comps[1:] for name in comp)
+        warn("decisive graph is disconnected; fitting largest component only: "
+             + ", ".join(comps[0]))
+        warn("excluded disconnected anchors: " + ", ".join(dropped))
+        fit_names = [name for name in fit_names if name in keep]
+
+    if anchor not in fit_names:
+        raise PoolError(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    return anchored_elo(fit_names, pi, anchor, ELO_SCALE)
+
+
+def candidates_from_inputs(elo: Dict[str, float], registry: Dict[str, dict]) -> List[Candidate]:
+    ladder_names = set(elo)
+    registry_names = set(registry)
+
+    for name in sorted(ladder_names - registry_names):
+        warn(f"ladder node {name!r} missing from registry; skipping")
+    for name in sorted(registry_names - ladder_names):
+        if name.startswith("_"):
+            continue
+        warn(f"registry node {name!r} missing from ladder fit; skipping")
+
+    candidates = []
+    for name in sorted(ladder_names & registry_names):
+        entry = registry[name]
+        if not isinstance(entry, dict):
+            warn(f"registry node {name!r} is not an object; skipping")
+            continue
+        filename = entry.get("filename")
+        if not filename:
+            warn(f"registry node {name!r} missing filename; skipping")
+            continue
+        b2_key = entry.get("b2_key")
+        if b2_key is not None and not isinstance(b2_key, str):
+            warn(f"registry node {name!r} has non-string b2_key; treating as missing")
+            b2_key = None
+        candidates.append(Candidate(
+            name=name,
+            elo=elo[name],
+            filename=str(filename),
+            b2_key=b2_key,
+            classification=classify_status(entry.get("status", "")),
+        ))
+    return candidates
+
+
+def ordered_by_elo(candidates: Iterable[Candidate]) -> List[Candidate]:
+    return sorted(candidates, key=lambda c: c.elo, reverse=True)
+
+
+def unique_nodes(nodes: Optional[Sequence[str]]) -> List[str]:
+    out = []
+    seen = set()
+    for node in nodes or []:
+        if node not in seen:
+            seen.add(node)
+            out.append(node)
+    return out
+
+
+def append_pick(
+    picks: List[Pick],
+    used: Set[str],
+    candidate: Candidate,
+    slot: str,
+    cap: int = POOL_BANKS,
+) -> bool:
+    if candidate.name in used or len(picks) >= cap:
+        return False
+    picks.append(Pick(candidate, slot))
+    used.add(candidate.name)
+    return True
+
+
+def select_pool(
+    candidates: Sequence[Candidate],
+    tier1_count: int,
+    tier2_count: int,
+    requested_diversity: int,
+    include: Sequence[str],
+    exclude: Sequence[str],
+) -> List[Pick]:
+    by_name = {c.name: c for c in candidates}
+    include_nodes = unique_nodes(include)
+    exclude_set = set(exclude or [])
+    if len(include_nodes) > POOL_BANKS:
+        raise PoolError(f"--include names {len(include_nodes)} nodes, but only {POOL_BANKS} banks exist")
+    included_excluded = [name for name in include_nodes if name in exclude_set]
+    if included_excluded:
+        raise PoolError("--include conflicts with --exclude for: " + ", ".join(included_excluded))
+
+    nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+    selectable = [c for c in nondegenerate if c.name not in exclude_set]
+    selectable_by_name = {c.name: c for c in selectable}
+
+    picks: List[Pick] = []
+    used: Set[str] = set()
+
+    for name in include_nodes:
+        candidate = by_name.get(name)
+        if candidate is None:
+            raise PoolError(f"--include node {name!r} is not present in both ladder and registry")
+        if candidate.classification == "DEGENERATE":
+            raise PoolError(f"--include node {name!r} is DEGENERATE/retired and excluded from selection")
+        append_pick(picks, used, candidate, "INCLUDE")
+
+    floor_pool = [c for c in selectable if c.classification == "FLOOR"]
+    floor_pick = min(floor_pool, key=lambda c: abs(c.elo)) if floor_pool else None
+    if floor_pick is None:
+        warn("no FLOOR-tagged candidate available")
+    else:
+        append_pick(picks, used, floor_pick, "FLOOR")
+
+    tier_pool = ordered_by_elo(c for c in selectable if c.classification == "TIER1_CANDIDATE")
+    tier1_pool = tier_pool[:tier1_count]
+    tier2_pool = tier_pool[tier1_count:tier1_count + tier2_count]
+
+    desired_before_diversity = 1 + tier1_count + tier2_count
+    remaining_after_requested = POOL_BANKS - desired_before_diversity
+    if remaining_after_requested >= requested_diversity:
+        diversity_count = remaining_after_requested
+    else:
+        diversity_count = requested_diversity
+        if desired_before_diversity + requested_diversity > POOL_BANKS:
+            warn("requested tier/floor/diversity counts exceed 8 banks; selection will stop at 8")
+
+    for candidate in tier1_pool:
+        append_pick(picks, used, candidate, "TIER1")
+    for candidate in tier2_pool:
+        append_pick(picks, used, candidate, "TIER2")
+
+    diversity_pool = ordered_by_elo(
+        c for c in selectable
+        if c.classification == "DIVERSITY_CANDIDATE" and c.name in selectable_by_name
+    )
+    diversity_added = 0
+    for candidate in diversity_pool:
+        if diversity_added >= diversity_count or len(picks) >= POOL_BANKS:
+            break
+        if append_pick(picks, used, candidate, "DIVERSITY"):
+            diversity_added += 1
+
+    if len(picks) < POOL_BANKS:
+        fallback_pool = ordered_by_elo(c for c in selectable if c.name not in used)
+        for candidate in fallback_pool:
+            if len(picks) >= POOL_BANKS:
+                break
+            append_pick(picks, used, candidate, fallback_slot(candidate))
+
+    if len(picks) < POOL_BANKS:
+        warn(f"filled {len(picks)} of {POOL_BANKS} banks; not enough eligible candidates")
+
+    return picks
+
+
+def fallback_slot(candidate: Candidate) -> str:
+    if candidate.classification == "FLOOR":
+        return "FLOOR"
+    if candidate.classification == "DIVERSITY_CANDIDATE":
+        return "DIVERSITY"
+    return "TIER2"
+
+
+def checkpoint_path(checkpoint_dir: str, filename: str) -> str:
+    return os.path.join(checkpoint_dir, filename)
+
+
+def print_table(picks: Sequence[Pick], warmstart: Candidate, checkpoint_dir: str) -> None:
+    warmstart_path = checkpoint_path(checkpoint_dir, warmstart.filename)
+    print(f"warm-start recommendation: {warmstart.name} "
+          f"(Elo {warmstart.elo:+.1f}, {warmstart_path})")
+    print()
+    print(f"{'bank':>4}  {'node':<14} {'elo':>8}  {'filename':<26} {'b2_key':<28} {'slot':<10}")
+    print("-" * 100)
+    for bank, pick in enumerate(picks):
+        c = pick.candidate
+        b2_key = c.b2_key if c.b2_key is not None else "-"
+        print(f"{bank:>4}  {c.name:<14} {c.elo:>+8.1f}  "
+              f"{c.filename:<26} {b2_key:<28} {pick.slot:<10}")
+    print()
+    print(f"selected banks: {len(picks)}")
+
+
+def print_build_league(picks: Sequence[Pick], checkpoint_dir: str) -> None:
+    print()
+    missing = [
+        (pick.candidate, checkpoint_path(checkpoint_dir, pick.candidate.filename))
+        for pick in picks
+        if pick.candidate.b2_key
+        and not os.path.exists(checkpoint_path(checkpoint_dir, pick.candidate.filename))
+    ]
+    if missing:
+        print("missing checkpoint fetches:")
+        for candidate, path in missing:
+            print("# MISSING locally -- fetch first:")
+            print("# rclone copyto "
+                  f"bbr:bloodbowl-rl/checkpoints/{candidate.b2_key} {path}")
+        print()
+
+    print("build_league command:")
+    print("python3 tools/build_league.py \\")
+    print("  --out <PLACEHOLDER> \\")
+    print(f"  --expect-bytes {DEFAULT_EXPECT_BYTES} \\")
+    print("  --seeds \\")
+    for index, pick in enumerate(picks):
+        c = pick.candidate
+        path = checkpoint_path(checkpoint_dir, c.filename)
+        suffix = " \\" if index != len(picks) - 1 else ""
+        print(f"  {c.name}={path}{suffix}")
+
+
+def print_launch_vars(warmstart: Candidate, checkpoint_dir: str) -> None:
+    print()
+    print(f"WARMSTART_FILE={checkpoint_path(checkpoint_dir, warmstart.filename)}")
+
+
+def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
+    ap = argparse.ArgumentParser(
+        description="Build a D111 hard-opponents pool from anchored ladder data")
+    ap.add_argument("--ladder", default=DEFAULT_LADDER,
+                    help=f"ladder CSV path (default {DEFAULT_LADDER})")
+    ap.add_argument("--registry", default=DEFAULT_REGISTRY,
+                    help=f"checkpoint registry JSON path (default {DEFAULT_REGISTRY})")
+    ap.add_argument("--anchor", default=DEFAULT_ANCHOR,
+                    help=f"Elo anchor node (default {DEFAULT_ANCHOR})")
+    ap.add_argument("--tier1", type=int, default=3,
+                    help="number of top Elo hard-opponent slots (default 3)")
+    ap.add_argument("--tier2", type=int, default=3,
+                    help="number of next Elo hard-opponent slots (default 3)")
+    ap.add_argument("--diversity", type=int, default=1,
+                    help="minimum diversity slots (default 1)")
+    ap.add_argument("--exclude", nargs="+", default=[],
+                    help="nodes to exclude from pool selection")
+    ap.add_argument("--include", nargs="+", default=[],
+                    help="nodes to force into the pool")
+    ap.add_argument("--checkpoint-dir", default=DEFAULT_CHECKPOINT_DIR,
+                    help=f"checkpoint path prefix (default {DEFAULT_CHECKPOINT_DIR})")
+    ap.add_argument("--print-build-league", action="store_true",
+                    help="also print a ready-to-paste build_league.py command")
+    ap.add_argument("--print-launch-vars", action="store_true",
+                    help="also print shell-sourceable launch variables")
+    return ap.parse_args(argv)
+
+
+def validate_counts(args: argparse.Namespace) -> None:
+    for name in ("tier1", "tier2", "diversity"):
+        value = getattr(args, name)
+        if value < 0:
+            raise PoolError(f"--{name} must be non-negative")
+
+
+def main(argv: Optional[Sequence[str]] = None) -> int:
+    args = parse_args(argv)
+    try:
+        validate_counts(args)
+        elo = fit_ladder(args.ladder, args.anchor)
+        registry = load_registry(args.registry)
+        candidates = candidates_from_inputs(elo, registry)
+        nondegenerate = [c for c in candidates if c.classification != "DEGENERATE"]
+        if not nondegenerate:
+            raise PoolError("no non-degenerate candidates available")
+        warmstart = max(nondegenerate, key=lambda c: c.elo)
+        picks = select_pool(
+            candidates,
+            tier1_count=args.tier1,
+            tier2_count=args.tier2,
+            requested_diversity=args.diversity,
+            include=args.include,
+            exclude=args.exclude,
+        )
+    except PoolError as e:
+        print(f"build_pool_from_ladder: {e}", file=sys.stderr)
+        return 1
+
+    print_table(picks, warmstart, args.checkpoint_dir)
+    if args.print_build_league:
+        print_build_league(picks, args.checkpoint_dir)
+    if args.print_launch_vars:
+        print_launch_vars(warmstart, args.checkpoint_dir)
+    return 0
+
+
+if __name__ == "__main__":
+    sys.exit(main())

tokens used
63,762
Implemented [tools/build_pool_from_ladder.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/build_pool_from_ladder.py). No commit made.

**Edit Map**

Added one new file only:

`tools/build_pool_from_ladder.py`

It:

- Imports `parse_rows`, `decisive_counts`, `fit_bt`, `connected_components`, and `anchored_elo` from `tools/bt_fit.py`.
- Refits the ladder live from `tools/anchored_ladder.csv` with `gen1` anchored at `0.0`.
- Loads `docs/checkpoint_registry.json`.
- Classifies registry prose tags into floor, tier candidates, diversity candidates, and degenerate/retired exclusions.
- Selects an 8-bank D111 pool with floor, tier1, tier2, diversity, include, and exclude handling.
- Prints the ladder-top warm-start recommendation across all non-degenerate nodes.
- Emits `build_league.py` command text and missing-local-file rclone fetch comments.
- Emits `WARMSTART_FILE=...` for `--print-launch-vars`.

Validation run:

```text
python3 -m py_compile tools/build_pool_from_ladder.py
```

passed.

**Self-Test 1**

Command:

```bash
python3 tools/build_pool_from_ladder.py
```

Output:

```text
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8
```

Confirmed from this run:

- Floor is `gen1`.
- Warm-start recommendation is `league5` at `+178.7`.
- TIER1 is `league5`, `gen2`, `gen3`.
- `bc_v4` and `v5contested` do not appear.
- Total selected banks is `8`.

**Self-Test 2**

Command:

```bash
python3 tools/build_pool_from_ladder.py --print-build-league
```

Output:

```text
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   1  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   2  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   3  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   4  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   5  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   6  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     
   7  exploiter1        +58.0  v4_exploiter1_cap.bin      v4_exploiter1_cap.bin        DIVERSITY 

selected banks: 8

missing checkpoint fetches:
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested_cap.bin training/v4_contested_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league5_cap.bin training/league5_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested2_cap.bin training/v4_contested2_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested3_cap.bin training/v4_contested3_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league_cap.bin training/league_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_contested4_cap.bin training/v4_contested4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/league4_cap.bin training/league4_cap.bin
# MISSING locally -- fetch first:
# rclone copyto bbr:bloodbowl-rl/checkpoints/v4_exploiter1_cap.bin training/v4_exploiter1_cap.bin

build_league command:
python3 tools/build_league.py \
  --out <PLACEHOLDER> \
  --expect-bytes 16066560 \
  --seeds \
  gen1=training/v4_contested_cap.bin \
  league5=training/league5_cap.bin \
  gen2=training/v4_contested2_cap.bin \
  gen3=training/v4_contested3_cap.bin \
  league1=training/league_cap.bin \
  gen4=training/v4_contested4_cap.bin \
  league4=training/league4_cap.bin \
  exploiter1=training/v4_exploiter1_cap.bin
```

**Self-Test 3**

Command:

```bash
python3 tools/build_pool_from_ladder.py --include kickoff8 --exclude exploiter1
```

Output:

```text
warm-start recommendation: league5 (Elo +178.7, training/league5_cap.bin)

bank  node                elo  filename                   b2_key                       slot      
----------------------------------------------------------------------------------------------------
   0  kickoff8         -111.5  v4_kickoff9_cap.bin        v4_kickoff9_cap.bin          INCLUDE   
   1  gen1               +0.0  v4_contested_cap.bin       v4_contested_cap.bin         FLOOR     
   2  league5          +178.7  league5_cap.bin            league5_cap.bin              TIER1     
   3  gen2             +101.2  v4_contested2_cap.bin      v4_contested2_cap.bin        TIER1     
   4  gen3              +98.3  v4_contested3_cap.bin      v4_contested3_cap.bin        TIER1     
   5  league1           +77.5  league_cap.bin             league_cap.bin               TIER2     
   6  gen4              +64.0  v4_contested4_cap.bin      v4_contested4_cap.bin        TIER2     
   7  league4           +61.9  league4_cap.bin            league4_cap.bin              TIER2     

selected banks: 8
```

This confirms `kickoff8` is forced in, `exploiter1` is excluded, the pool remains capped at 8, and the warm-start remains the global ladder-top `league5`.

**Deviations / Notes**

One deliberate formatting deviation: the brief asked missing-checkpoint comments to appear immediately above each affected bank line inside the `--print-build-league` output. I printed them in a `missing checkpoint fetches:` preflight section before the command instead. Reason: shell comments inside a backslash-continued command make the supposedly ready-to-paste command fragile or invalid. The generated `build_league.py` block is now cleanly pasteable, and the fetch commands are still printed directly above it.

One classification nuance: I normalized the phrase `non-degenerate` before matching `degenerate`, because the `gen1` status says “non-degenerate reference point” and must remain `FLOOR`. I also let explicit `degenerate`/`retired` take precedence over incidental floor wording, so `bc_v4` remains excluded even though its prose contains “floor candidate.”

**Registry / Ladder Surprises**

A few prose-tag wrinkles stood out:

- `bc_v4` status contains both `degenerate` and `floor candidate`; the self-test expectation makes clear it should be treated as degenerate/excluded, not as the floor.
- `gen1` status contains `non-degenerate`, which would match a naive raw substring search for `degenerate`.
- `gen2cont1` has `diversity candidate` prose but also says `retired`; with the requested retired/degenerate exclusion doctrine, it is excluded from selection.
- `exploiter1` has status `TIER2/diversity`; by substring classification it becomes a diversity candidate, which is why it fills the default diversity slot.

Worktree note: pre-existing untracked files were left untouched. Current new file from this task is only `tools/build_pool_from_ladder.py`; the other untracked entries shown by `git status` were already present or unrelated.
