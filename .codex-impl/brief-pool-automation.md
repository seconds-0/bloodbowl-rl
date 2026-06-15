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
