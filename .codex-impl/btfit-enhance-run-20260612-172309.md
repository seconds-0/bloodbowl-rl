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
session id: 019ebe5c-7a36-7231-9209-9e1db8526324
--------
user
# Brief: enhance tools/bt_fit.py per codex review of H1 (D97-A)

Repo: /Users/alexanderhuth/Code/bloodbowl-rl. Edit ONLY tools/bt_fit.py. No git state changes
(no commit). Match existing style in the file (it's already written, argparse-based,
pure-python-with-optional-numpy).

## Context
.codex-reviews/growth-plan.md reviewed tools/bt_fit.py (just landed) and flagged that "before
interpreting H1" we need, in addition to the existing decisive-only BT/Elo table:

1. **Confidence intervals** on the decisive win-rate per pairing (Wilson score interval,
   95%, no scipy — implement the closed-form Wilson formula directly) — print alongside the
   existing raw pair table.
2. **Score-based Elo** as a second table: instead of stripping draws (the current
   decisive-only BT fit), fit a SECOND Bradley-Terry-style model where each pairing's
   "win probability for A" input is simply `A_rate` directly (the raw score-rate, draws
   already split 50/50 into it per the env's scoring) — i.e. treat A_rate as an expected
   score in [0,1] and run the SAME Zermelo MM iteration but with `w_a = A_rate * total_games`
   (a float, not rounded to an int win count — the MM iteration in fit_bt already just sums
   floats via `total_wins`, so passing fractional "wins" works; you may need to relax the
   `int(round(...))` calls for THIS second fit's win/game tallies — keep the existing
   decisive-only path byte-for-byte unchanged, add a parallel path/function for the
   score-based fit reusing fit_bt with float win/game dicts built differently).
3. **Draw-rate matrix**: a simple square table (rows/cols = all present names, ordered by
   the EXISTING decisive-Elo ranking) showing `draw_rate` for each measured pairing (blank
   or "--" for unmeasured/diagonal cells).
4. **Residual table**: for ALL measured pairings (not just adjacent-in-ranking), print
   `name_i vs name_j: fit_p (decisive-Elo model) vs empirical_p vs n` — this generalizes the
   existing "adjacent fitted-vs-empirical" table to the full pairwise set, so non-transitivity
   (A>B>C>A cycles) is visible. Keep the existing adjacent-only table too (cheap, still useful
   as a quick summary) but add this full table as well, clearly labeled.

## Output structure (append after existing sections, in this order)
1. (existing) raw pair table
2. (existing) decisive-only BT/Elo ranked table — UNCHANGED
3. (existing) adjacent fitted-vs-empirical — UNCHANGED
4. NEW: full pairwise residual table (decisive-Elo model fit_p vs empirical_p vs n, for every
   measured pairing, ordered by |fit_p - empirical_p| descending so the worst-fitting/most
   non-transitive pairings surface first)
5. NEW: Wilson 95% CI per pairing — can be folded into the raw pair table as extra columns
   (`ci_lo`, `ci_hi` on `A_dec_p`) rather than a separate table, your choice — pick whichever
   keeps the raw pair table readable (if columns get too wide, make it a separate table)
6. NEW: score-based Elo ranked table (same column layout as the decisive-only table, same
   anchor/scale) — label clearly as "score-based (draws=0.5, no draw-stripping)" vs the
   existing "decisive-only (draws excluded)"
7. NEW: draw-rate matrix

## Wilson interval formula (for n trials, k successes, z=1.96 for 95%)
```
phat = k/n
denom = 1 + z^2/n
center = (phat + z^2/(2n)) / denom
half = (z * sqrt(phat*(1-phat)/n + z^2/(4*n*n))) / denom
ci = (center - half, center + half)
```
Use n=n_decisive, k=w_a (the already-computed decisive win count) from `decisive_counts`.

## Verify
- Run against the existing synthetic smoke-test CSV from the prior brief (recreate it inline:
  `printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\nA,B,0.650,0.350,0.200,100\nB,C,0.600,0.400,0.100,100\nA,C,0.700,0.300,0.300,100\n'`)
  and confirm all new sections print without crashing and look sane (e.g. Wilson CIs bracket
  the point estimates, score-based and decisive-only Elo orderings are both printed and are
  plausibly similar-but-not-identical for this 3-node example, draw-rate matrix shows the
  3 measured cells).
- `python3 tools/bt_fit.py --help` still works.

## Report back
- Diff summary (function names added/changed).
- Smoke-test output (the new sections only, can omit unchanged sections from your report).
- Any deviations.
deprecated: `[features].collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml. See https://developers.openai.com/codex/config-basic#feature-flags for details.
codex
I’ll keep this tightly scoped to `tools/bt_fit.py` and first read the existing script plus the review note so the additions land in the file’s current idiom.
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
    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
    anchor_elo = raw_elo[anchor]
    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
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

exec
/bin/zsh -lc 'rg -n "bt_fit|H1|D97-A|Wilson|draw-rate|residual" .codex-reviews/growth-plan.md' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 112ms:
18:H1 (already running, cheap): anchored round-robin Bradley-Terry/Elo ladder across 7 lineage caps {bc_v4, kickoff8, v5contested, gen1, gen2, gen3, league1} via tools/anchored_ladder.sh + tools/bt_fit.py (just committed), to put all prior pairwise win-rate claims (70%/55%/dead-heat) onto an absolute scale -- motivated by the observation that D96's bank-scores stayed flat (~0.08) while Elo climbed +140, suggesting possible style-convergence/draw-inflation rather than true differentiation.
20:H2 (lead bet, japan slot when gen-4 caps ~21:00): rebuild the league pool as a 'hall of champions' -- full zoo seeds {bc_v4, kickoff8/9 caps, v5-contested, gen1-4 caps, league-1, league-2 caps}, swap_winrate 0.55, live snapshot feeding (snapshot_interval 200-500M), 30B, warm from whichever cap H1's ladder crowns strongest. Rationale: league Elo never plateaued (84.9->224.3 over 30B) vs ratchet's compressing margin.
26:ADVERSARIAL QUESTIONS: (1) Is H1's BT/Elo fit methodologically sound for deciding 'which cap is strongest' to warm-start H2 from -- any failure modes specific to a 7-node complete graph with games already played at DIFFERENT training depths (gen1/gen2/gen3 are NOT step-matched to bc_v4/kickoff8/v5contested/league1)? (2) Does H2's pool composition risk the same 'near-mirror, high-draw-rate' signal starvation D56/D91 already diagnosed, given gen1-4+league1-2 are all closely related lineages? (3) Is H3's 15B budget sufficient given D45's caveat that exploiting a frozen target took 10B and FAILED against an old weak prior -- are today's caps different enough that 15B is now plausible, or is this underbudgeted? (4) Is the decision rule (50% vs 60% threshold on ONE gen-4-vs-gen-3 tournament, itself only ~1200 decisive games) statistically robust enough to retire an entire lineage, or does it need the H1 ladder's corroboration first? (5) Any internal inconsistency between the three memos' recommendations or with D90-D97 doctrine? Be specific and adversarial -- this commits ~1-2 days of GPU-box time across two boxes.
46:### H1 — Anchored cross-generation Elo ladder (diagnostic, run first, ~free)
54:- **(b) Mechanism:** one arm combining both: `league_preseed` pool seeded with the full zoo {bc_v4, kickoff-8/9 caps, v5-contested, gen-1..4 caps, league-1/2 caps}, `swap_winrate 0.55`, `snapshot_interval 200–500M` (live snapshots keep entering, as league-1 did → 36+ entries), warm from the strongest cap per H1. Optionally weight freshness via `num_frozen_banks`/`frozen_bank_pct` so a meaningful slice of envs always faces the newest pool entries (the ratchet's concentrated-pressure ingredient) while the rest rotate the zoo (the league's diversity ingredient).
55:- **(c) Prediction:** hybrid cap beats BOTH gen-4 and league-2 caps >55% decisive at matched +30B, and its H1-ladder Elo gain per 30B exceeds gen-4's. If it merely ties, diversity-vs-freshness is not the bottleneck → capacity/horizon levers (H5/H6) promote.
77:- **(a) Data pattern:** the D35/D45/D53 lever ladder (sequence context > bigger policy > more data) has been dormant since obs-v4 moved the ceiling. If H1's ladder shows absolute gains decelerating under BOTH regimes and H2/H3 don't restore slope, the 3.8M-param MinGRU policy is the next suspect — saturation with diverse opponents and adequate horizon is the capacity signature.
79:- **(c) Prediction:** at matched 30B-from-comparable-start, the wider policy's H1-ladder Elo slope exceeds the 512 lineage's *current* slope (not its historical early slope).
98:2. **H1, the anchored cross-gen Elo ladder** — overnight round-robin. It converts every subsequent verdict from pairwise-relative to absolute, and it adjudicates between "saturating strength" and "converging styles" before we spend a single GPU-day on the wrong fix. H7's TDs-conceded probe rides along on the same eval session.
101:1. **japan → H2 hybrid league-3** (lead bet): full-zoo pool + live snapshots + swap 0.55, warm from whatever H1 crowns champion; fold in H4's skillup 6/2/0.20 **only if** league-2 passes tonight's exam. This is the highest-EV slot: it directly tests the one mechanism (diversity + freshness combined) that the D96 dead heat and D97 flattening jointly point at, using shipped machinery.
102:2. **ballhawk → H3 champion-exploiter** (15B, then its cap feeds H2's pool): cheapest direct attack on the saturation mechanism, and its failure mode is itself informative (an unexploitable champion promotes H5/H6). When it caps at 15B, ballhawk's back half of the day picks up either the H5 γ-twin or a second hybrid seed, steered by the H1 ladder + gen-4 verdict.
104:Decision rule already pre-registered in D97 stands: if gen-4-vs-gen-3 ≈ 50%, the ratchet retires as a lineage and both boxes go to the hybrid program (H2 + H3); if gen-4 surprises at >60%, keep one ratchet slot and run H2 on the other — the H1 ladder arbitrates either way.
109:/bin/zsh -lc "rg --files tools | rg 'anchored_ladder|bt_fit'" in /Users/alexanderhuth/Code/bloodbowl-rl
112:tools/bt_fit.py
138:/bin/zsh -lc "sed -n '1,260p' tools/bt_fit.py" in /Users/alexanderhuth/Code/bloodbowl-rl
578:/bin/zsh -lc 'rg -n "Bradley|Elo|bt_fit|anchored|draw|decisive|swap_winrate|snapshot_interval|league_preseed|frozen_bank" -S .' in /Users/alexanderhuth/Code/bloodbowl-rl
585:./DECISIONS.md:58:**D38 — THE UNMASKED-SAMPLER BUG: the torch backend never applied action masks; every BC-anchored run played via decode fallback (illegal_frac 1.000).** Found chasing synthesis+C's blocks 0.000 AND blitzes 0.000 at 200M (exact zeros — structure, not behavior). Mechanism: bc_pretrain (and the bc_acc aux loss) train/score MASK-RESTRICTED logits; the torch backend samples RAW logits (masks were CUDA-only); the BC policy never had to learn raw-logit legality, so on-policy it sampled ~100% illegal and bbe_decode's fallback (same-type → legal[0]) played a MOVE-biased shadow policy. Measured: bc_v3b lr~0 probe — unmasked: illegal 0.999, blocks 0.000, blitzes 0.000; MASKED: illegal 0.235 (residual = joint arg×sq misses across independent head masks), blocks 12.4/ep, blocks_thrown 13.6/ep, blitzes 2.8/ep — HUMAN-RANGE contact from the same weights. Fix (training/torch_pufferl_bcreg.patch + puffer_dict_capacity.patch regenerated): bindings expose vec action_mask (cpu+gpu); torch_pufferl applies per-head masked_fill(-inf) BEFORE rollout sampling, stores masks in experience, and re-applies at train-time recompute (mask-consistent ratios/entropy; all-zero head row guard). REINTERPRETATIONS: D33's knowledge-behavior gap = largely this artifact; D32/synthesis-v4 "anchor holds" results stand as experiments but measured fallback-shadow dynamics (their tds/pickups arose through legal[0]-snapping, with PPO slowly re-learning legality in raw logits); the avoidance-basin conclusions (D26-D28, CUDA, masked) unaffected; D34's Profile C result (CUDA, masked) unaffected. Unmasked synthesis+C control killed at ~300M (preserved in log); SYNTHESIS+C-MASKED relaunched 16:25 PDT — the first torch run whose behavior and knowledge share a distribution. Viewer inherits the fix (same patch) — on-screen play is now the real policy.
751:./tools/bt_fit.py:2:"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
752:./tools/bt_fit.py:4:100%-draw pairings carry no Bradley-Terry information, so they remain visible
753:./tools/bt_fit.py:30:        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
754:./tools/bt_fit.py:40:                draw = float(row["draw_rate"])
755:./tools/bt_fit.py:52:                "draw": draw,
756:./tools/bt_fit.py:59:def decisive_counts(rows):
757:./tools/bt_fit.py:74:        denom = 1.0 - row["draw"]
758:./tools/bt_fit.py:76:            skipped.append((a, b, "all draws"))
759:./tools/bt_fit.py:78:        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
760:./tools/bt_fit.py:80:        n_decisive = int(round(row["total"] * denom))
761:./tools/bt_fit.py:81:        if n_decisive <= 0:
762:./tools/bt_fit.py:82:            skipped.append((a, b, "zero decisive games after rounding"))
763:./tools/bt_fit.py:84:        w_a = int(round(n_decisive * p_a))
764:./tools/bt_fit.py:85:        w_a = max(0, min(n_decisive, w_a))
765:./tools/bt_fit.py:86:        w_b = n_decisive - w_a
766:./tools/bt_fit.py:90:        games[frozenset((a, b))] += n_decisive
767:./tools/bt_fit.py:96:            "n": n_decisive,
768:./tools/bt_fit.py:97:            "p_a": w_a / n_decisive,
769:./tools/bt_fit.py:103:def row_decisive_summary(row):
770:./tools/bt_fit.py:104:    denom = 1.0 - row["draw"]
771:./tools/bt_fit.py:107:    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
772:./tools/bt_fit.py:109:    n_decisive = int(round(row["total"] * denom))
773:./tools/bt_fit.py:110:    if n_decisive <= 0:
774:./tools/bt_fit.py:112:    w_a = int(round(n_decisive * p_a))
775:./tools/bt_fit.py:113:    w_a = max(0, min(n_decisive, w_a))
776:./tools/bt_fit.py:114:    return n_decisive, w_a, n_decisive - w_a, p_a
777:./tools/bt_fit.py:187:        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
778:./tools/bt_fit.py:188:    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
779:./tools/bt_fit.py:189:    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
780:./tools/bt_fit.py:191:                    help="Elo display scale, default 400")
781:./tools/bt_fit.py:201:    names, wins, games, raw, skipped = decisive_counts(rows)
782:./tools/bt_fit.py:202:    total_decisive = {
783:./tools/bt_fit.py:206:    excluded = [name for name in names if total_decisive[name] <= 0]
784:./tools/bt_fit.py:208:        warn(f"excluding {name}: zero decisive games vs everyone")
785:./tools/bt_fit.py:214:        raise SystemExit("need at least two connected anchors with decisive games")
786:./tools/bt_fit.py:221:        warn("decisive graph is disconnected; fitting largest component only: "
787:./tools/bt_fit.py:239:    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
788:./tools/bt_fit.py:242:        summary = row_decisive_summary(row)
789:./tools/bt_fit.py:244:            decisive_s, p_s = "skip", "--"
790:./tools/bt_fit.py:246:            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
791:./tools/bt_fit.py:248:              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
792:./tools/bt_fit.py:249:              f"{decisive_s:>11}{p_s:>10}")
793:./tools/bt_fit.py:252:    print(f"anchor: {anchor} = 0.0 Elo")
794:./tools/bt_fit.py:255:    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
795:./tools/bt_fit.py:258:        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
796:./tools/bt_fit.py:261:    print("adjacent fitted-vs-empirical decisive win rates")
855:/bin/zsh -lc "sed -n '260,360p' tools/bt_fit.py" in /Users/alexanderhuth/Code/bloodbowl-rl
2051:/bin/zsh -lc "nl -ba tools/anchored_ladder.sh | sed -n '90,165p'; nl -ba tools/bt_fit.py | sed -n '70,100p'; nl -ba vendor/PufferLib/pufferlib/pufferl.py | sed -n '560,590p'" in /Users/alexanderhuth/Code/bloodbowl-rl
2197:1. `H1` is useful, but not sufficient as a single “crown the strongest cap” oracle unless you add uncertainty, residual checks, and draw-aware reporting.
2200:4. The gen-4 retirement rule should require corroboration from `H1` or a repeat/expanded tournament if the result lands in the 53-58% decisive gray zone.
2201:5. There is a real metric-reading hazard: `puffer match` prints `A`/`B` as score rates, not decisive win rates. The new `bt_fit.py` handles this correctly, but some D95-D97 prose appears to have read those numbers too literally.
2203:I would proceed, but with guardrails: run `H1`, run `H2` with a bank-limit-aware pool, run `H3` with checkpointed go/no-go evaluations, and make “retire ratchet” a two-signal decision rather than a one-tournament edict.
2205:**1. H1 BT/Elo Soundness**
2207:`H1` is directionally sound for creating an absolute-ish cross-generation scoreboard. The tooling does the right basic conversion from `puffer match` score rates to decisive rates:
2209:[tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:74) computes:
2234:Failure modes specific to `H1`:
2236:- **No uncertainty intervals.** The current `bt_fit.py` reports point estimates only. With about 1200 decisive games, a 55-59% decisive result has a rough 95% half-width around 2.8 percentage points for a single pair. In Elo terms, small top gaps can be noise. If H1 crowns gen-4 by 10-25 Elo, that is not a crown; it is a shrug with decimals.
2242:- **BT assumes transitivity.** Blood Bowl policies can be stylistic. A beats B, B beats C, C beats A is plausible, especially across macro/stepwise, league/ratchet, and old-prior lineages. A 7-node complete graph is actually small enough to inspect residuals manually. The “adjacent fitted-vs-empirical” table in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:261) helps, but I would also look at the full residual matrix. If residuals are large or cyclic, do not crown one cap. Seed the pool with the top cluster.
2244:- **Different training depths are not a problem for current strength, but are a problem for causal claims.** For “which cap is strongest today?” it is fine that `gen1`, `gen2`, `gen3`, `bc_v4`, `kickoff8`, and `league1` are not step-matched. A checkpoint is a checkpoint. But you cannot use that same ladder to claim “this regime had better per-step learning” unless comparisons are step-matched or normalized. H1 can choose a warm start; it cannot by itself adjudicate training efficiency.
2246:- **The default H1 set is incomplete for tonight’s decision unless `gen4` and `league2` are included.** [tools/anchored_ladder.sh](/Users/alexanderhuth/Code/bloodbowl-rl/tools/anchored_ladder.sh:41) has `EXTRA_ANCHORS`, so this is operationally easy. But “warm H2 from the H1 champion” only makes sense if the two newly capped arms are in the ladder.
2248:- **Slot/color bias is probably handled.** `pufferl.match()` fixes A to slot 0 and B to slot 1, but the env randomizes slot-to-color per env according to the comment at [vendor/PufferLib/pufferlib/pufferl.py](/Users/alexanderhuth/Code/bloodbowl-rl/vendor/PufferLib/pufferlib/pufferl.py:563). So I do not see a side-assignment flaw in H1.
2250:My recommendation: use H1 to choose among a **top cluster**, not a single champion, unless the top gap is comfortably outside noise and residuals are boring. If top two are within about 30 Elo or there are obvious nontransitive residuals, warm H2 from the newest/top-regime cap and rely on the pool to carry the diversity.
2288:Bank 7: H1 oddball/top residual opponent, not necessarily strongest
2306:On `snapshot_interval`: 200-500M is reasonable, but lower intervals can create a rapidly expanding pool of near-duplicates. If sampling prefers recent snapshots too heavily, the zoo becomes a mirror again. If sampling prefers stale snapshots too heavily, the learner farms obsolete opponents. I would start at 500M unless H1/H2 diagnostics show the live pool is under-biting.
2336:3. `v5-contested` only if H1 says it is not catastrophically below the current top or if the point is explicitly a style-injection seed, not a candidate exploiter
2357:If gen4-vs-gen3 <= ~53% decisive and H1 shows gen4 not clearly above gen3/league2:
2365:    Use H1 ladder and league2-vs-gen3 as tie-breakers.
2366:    Prefer H2 lead + optional short gen5 only if H1 says ratchet still has absolute slope.
2383:- **H1 timing vs H2 launch timing.** The memo says H1 is overnight/free, while H2 is supposed to launch when gen-4 caps around 21:00. If H1 has not included `gen4` and `league2` and finished enough pairings, “warm from H1’s champion” is unavailable. Solution: either wait for the top-cluster part of H1, or warm from the winner of the immediate regime gates and update later.
2391:- **D97 slope call may be numerically suspect.** If the quoted `A=0.550 draw=0.419` is exact, the decisive rate is about 58.6%, not 55%. That does not restore the 70% slope, but it weakens “near plateau.” Before tonight’s decision, recalculate D95-D97 decisive rates from raw CSV/logs using the same formula as `bt_fit.py`.
2399:1. Finish or partially finish H1 with `gen4` and `league2` included via `EXTRA_ANCHORS`.
2400:2. Before interpreting H1, print:
2404:   - full pair residuals
2405:   - draw-rate matrix
2410:   - H1 shows no meaningful absolute gain, and
2421:1. `H1` is useful, but not sufficient as a single “crown the strongest cap” oracle unless you add uncertainty, residual checks, and draw-aware reporting.
2424:4. The gen-4 retirement rule should require corroboration from `H1` or a repeat/expanded tournament if the result lands in the 53-58% decisive gray zone.
2425:5. There is a real metric-reading hazard: `puffer match` prints `A`/`B` as score rates, not decisive win rates. The new `bt_fit.py` handles this correctly, but some D95-D97 prose appears to have read those numbers too literally.
2427:I would proceed, but with guardrails: run `H1`, run `H2` with a bank-limit-aware pool, run `H3` with checkpointed go/no-go evaluations, and make “retire ratchet” a two-signal decision rather than a one-tournament edict.
2429:**1. H1 BT/Elo Soundness**
2431:`H1` is directionally sound for creating an absolute-ish cross-generation scoreboard. The tooling does the right basic conversion from `puffer match` score rates to decisive rates:
2433:[tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:74) computes:
2458:Failure modes specific to `H1`:
2460:- **No uncertainty intervals.** The current `bt_fit.py` reports point estimates only. With about 1200 decisive games, a 55-59% decisive result has a rough 95% half-width around 2.8 percentage points for a single pair. In Elo terms, small top gaps can be noise. If H1 crowns gen-4 by 10-25 Elo, that is not a crown; it is a shrug with decimals.
2466:- **BT assumes transitivity.** Blood Bowl policies can be stylistic. A beats B, B beats C, C beats A is plausible, especially across macro/stepwise, league/ratchet, and old-prior lineages. A 7-node complete graph is actually small enough to inspect residuals manually. The “adjacent fitted-vs-empirical” table in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:261) helps, but I would also look at the full residual matrix. If residuals are large or cyclic, do not crown one cap. Seed the pool with the top cluster.
2468:- **Different training depths are not a problem for current strength, but are a problem for causal claims.** For “which cap is strongest today?” it is fine that `gen1`, `gen2`, `gen3`, `bc_v4`, `kickoff8`, and `league1` are not step-matched. A checkpoint is a checkpoint. But you cannot use that same ladder to claim “this regime had better per-step learning” unless comparisons are step-matched or normalized. H1 can choose a warm start; it cannot by itself adjudicate training efficiency.
2470:- **The default H1 set is incomplete for tonight’s decision unless `gen4` and `league2` are included.** [tools/anchored_ladder.sh](/Users/alexanderhuth/Code/bloodbowl-rl/tools/anchored_ladder.sh:41) has `EXTRA_ANCHORS`, so this is operationally easy. But “warm H2 from the H1 champion” only makes sense if the two newly capped arms are in the ladder.
2472:- **Slot/color bias is probably handled.** `pufferl.match()` fixes A to slot 0 and B to slot 1, but the env randomizes slot-to-color per env according to the comment at [vendor/PufferLib/pufferlib/pufferl.py](/Users/alexanderhuth/Code/bloodbowl-rl/vendor/PufferLib/pufferlib/pufferl.py:563). So I do not see a side-assignment flaw in H1.
2474:My recommendation: use H1 to choose among a **top cluster**, not a single champion, unless the top gap is comfortably outside noise and residuals are boring. If top two are within about 30 Elo or there are obvious nontransitive residuals, warm H2 from the newest/top-regime cap and rely on the pool to carry the diversity.
2512:Bank 7: H1 oddball/top residual opponent, not necessarily strongest
2530:On `snapshot_interval`: 200-500M is reasonable, but lower intervals can create a rapidly expanding pool of near-duplicates. If sampling prefers recent snapshots too heavily, the zoo becomes a mirror again. If sampling prefers stale snapshots too heavily, the learner farms obsolete opponents. I would start at 500M unless H1/H2 diagnostics show the live pool is under-biting.
2560:3. `v5-contested` only if H1 says it is not catastrophically below the current top or if the point is explicitly a style-injection seed, not a candidate exploiter
2581:If gen4-vs-gen3 <= ~53% decisive and H1 shows gen4 not clearly above gen3/league2:
2589:    Use H1 ladder and league2-vs-gen3 as tie-breakers.
2590:    Prefer H2 lead + optional short gen5 only if H1 says ratchet still has absolute slope.
2607:- **H1 timing vs H2 launch timing.** The memo says H1 is overnight/free, while H2 is supposed to launch when gen-4 caps around 21:00. If H1 has not included `gen4` and `league2` and finished enough pairings, “warm from H1’s champion” is unavailable. Solution: either wait for the top-cluster part of H1, or warm from the winner of the immediate regime gates and update later.
2615:- **D97 slope call may be numerically suspect.** If the quoted `A=0.550 draw=0.419` is exact, the decisive rate is about 58.6%, not 55%. That does not restore the 70% slope, but it weakens “near plateau.” Before tonight’s decision, recalculate D95-D97 decisive rates from raw CSV/logs using the same formula as `bt_fit.py`.
2623:1. Finish or partially finish H1 with `gen4` and `league2` included via `EXTRA_ANCHORS`.
2624:2. Before interpreting H1, print:
2628:   - full pair residuals
2629:   - draw-rate matrix
2634:   - H1 shows no meaningful absolute gain, and

codex
The file is small and already has the decisive path factored cleanly. I’ve confirmed the review’s asks line up with this script’s current BT implementation, so I’m going to add helper functions around the existing path rather than disturb the current decisive-only behavior.
exec
/bin/zsh -lc "sed -n '260,380p' tools/bt_fit.py" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
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

    if excluded:
        print()
        print("excluded zero-information anchors: " + ", ".join(excluded))


if __name__ == "__main__":
    main()

codex
I’m about to edit `tools/bt_fit.py`: add Wilson math, score-count construction, reusable Elo anchoring/display, full residual printing, and draw-matrix printing. I’ll leave the existing decisive ranked table and adjacent summary text/shape intact.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..6aebcd041456060f268796cf22c7bd4855c0bdb6
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,93 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    names = [name for name in ordered if any(name in pair for pair in draw_by_pair)]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +355,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +394,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..6aebcd041456060f268796cf22c7bd4855c0bdb6
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,93 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    names = [name for name in ordered if any(name in pair for pair in draw_by_pair)]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +355,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +394,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

codex
The patch is in. I’m running the required smoke checks now, with an eye on numeric sanity as well as whether the new tables stay readable in plain terminal output.
exec
/bin/zsh -lc 'python3 tools/bt_fit.py --help' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
usage: bt_fit.py [-h] [--anchor ANCHOR] [--scale SCALE] csv_path

Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.

positional arguments:
  csv_path         CSV from tools/anchored_ladder.sh

options:
  -h, --help       show this help message and exit
  --anchor ANCHOR  rating anchor pinned to Elo 0
  --scale SCALE    Elo display scale, default 400

exec
/bin/zsh -lc 'tmp=$(mktemp); printf '"'nameA,nameB,A_rate,B_rate,draw_rate,total_games\\nA,B,0.650,0.350,0.200,100\\nB,C,0.600,0.400,0.100,100\\nA,C,0.700,0.300,0.300,100\\n' > \""'$tmp"; python3 tools/bt_fit.py "$tmp"; rm "$tmp"' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
raw pair table
pair                                  A_rate   B_rate     draw   decisive   A_dec_p
-----------------------------------------------------------------------------------
A vs B                                 0.650    0.350    0.200         80     0.688
B vs C                                 0.600    0.400    0.100         90     0.611
A vs C                                 0.700    0.300    0.300         70     0.786

anchor: A = 0.0 Elo
scale: 400

name                   elo    raw_strength    decisive_games
------------------------------------------------------------
A                      0.0         1.73779               150
B                   -140.1        0.775708               170
C                   -221.2        0.486504               160

adjacent fitted-vs-empirical decisive win rates
pair                                    fit_p   empirical_p       n
-------------------------------------------------------------------
A > B                                   0.691         0.688      80
B > C                                   0.615         0.611      90

full pairwise residuals (decisive-Elo model)
pair                                    fit_p   empirical_p       n   abs_err
-----------------------------------------------------------------------------
A vs C                                  0.781         0.786      70     0.004
A vs B                                  0.691         0.688      80     0.004
B vs C                                  0.615         0.611      90     0.003

Wilson 95% CI per pairing on decisive A win-rate
pair                                  A_dec_p     ci_lo     ci_hi       n
-------------------------------------------------------------------------
A vs B                                  0.688     0.579     0.778      80
B vs C                                  0.611     0.508     0.705      90
A vs C                                  0.786     0.676     0.866      70

score-based Elo ranked table (draws=0.5, no draw-stripping)
name                   elo    raw_strength       score_games
------------------------------------------------------------
A                      0.0         1.52089               200
B                    -97.5        0.867801               200
C                   -158.3         0.61131               200

draw-rate matrix
               A       B       C
A             --   0.200   0.300
B          0.200      --   0.100
C          0.300   0.100      --

diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..6aebcd041456060f268796cf22c7bd4855c0bdb6
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,93 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    names = [name for name in ordered if any(name in pair for pair in draw_by_pair)]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +355,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +394,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

codex
The smoke test passes on the requested CSV: Wilson intervals bracket the decisive points, the score-based ladder is distinct from the decisive ladder, and the matrix shows the three measured draw rates. I’m doing one final syntax/diff pass so I can report exactly what changed.
exec
/bin/zsh -lc 'git diff -- tools/bt_fit.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37..6aebcd0 100755
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@ def decisive_counts(rows):
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@ def row_decisive_summary(row):
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,93 @@ def empirical_between(stronger, weaker, wins, games):
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    names = [name for name in ordered if any(name in pair for pair in draw_by_pair)]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +355,7 @@ def main():
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +394,39 @@ def main():
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

exec
/bin/zsh -lc 'python3 -m py_compile tools/bt_fit.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
exec
/bin/zsh -lc 'git status --short' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
 M tools/bt_fit.py
?? .codex-impl/
?? training/bc_v1.bin
?? training/bc_v15.bin
?? training/bc_v2.bin
?? training/bc_v2_cuda.bin
?? training/bc_v3b.bin

diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..6aebcd041456060f268796cf22c7bd4855c0bdb6
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,93 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    names = [name for name in ordered if any(name in pair for pair in draw_by_pair)]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +355,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +394,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

codex
One small compliance tweak surfaced in the diff pass: the draw matrix should include every name present in the CSV, not only names that survived the decisive fit. I’m adjusting that so decisive-ranked names come first and any zero-information names are appended in input order.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..9023fb1a946ffe18ba74cfa3144549f4e12ac845
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,94 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered, all_names):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    ordered_set = set(ordered)
+    names = list(ordered) + [name for name in all_names if name not in ordered_set]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +356,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +395,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered, names)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..9023fb1a946ffe18ba74cfa3144549f4e12ac845
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,94 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered, all_names):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    ordered_set = set(ordered)
+    names = list(ordered) + [name for name in all_names if name not in ordered_set]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +356,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +395,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered, names)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

exec
/bin/zsh -lc 'python3 -m py_compile tools/bt_fit.py' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
exec
/bin/zsh -lc 'python3 tools/bt_fit.py --help' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
usage: bt_fit.py [-h] [--anchor ANCHOR] [--scale SCALE] csv_path

Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.

positional arguments:
  csv_path         CSV from tools/anchored_ladder.sh

options:
  -h, --help       show this help message and exit
  --anchor ANCHOR  rating anchor pinned to Elo 0
  --scale SCALE    Elo display scale, default 400

exec
/bin/zsh -lc 'tmp=$(mktemp); printf '"'nameA,nameB,A_rate,B_rate,draw_rate,total_games\\nA,B,0.650,0.350,0.200,100\\nB,C,0.600,0.400,0.100,100\\nA,C,0.700,0.300,0.300,100\\n' > \""'$tmp"; python3 tools/bt_fit.py "$tmp"; rm "$tmp"' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
raw pair table
pair                                  A_rate   B_rate     draw   decisive   A_dec_p
-----------------------------------------------------------------------------------
A vs B                                 0.650    0.350    0.200         80     0.688
B vs C                                 0.600    0.400    0.100         90     0.611
A vs C                                 0.700    0.300    0.300         70     0.786

anchor: A = 0.0 Elo
scale: 400

name                   elo    raw_strength    decisive_games
------------------------------------------------------------
A                      0.0         1.73779               150
B                   -140.1        0.775708               170
C                   -221.2        0.486504               160

adjacent fitted-vs-empirical decisive win rates
pair                                    fit_p   empirical_p       n
-------------------------------------------------------------------
A > B                                   0.691         0.688      80
B > C                                   0.615         0.611      90

full pairwise residuals (decisive-Elo model)
pair                                    fit_p   empirical_p       n   abs_err
-----------------------------------------------------------------------------
A vs C                                  0.781         0.786      70     0.004
A vs B                                  0.691         0.688      80     0.004
B vs C                                  0.615         0.611      90     0.003

Wilson 95% CI per pairing on decisive A win-rate
pair                                  A_dec_p     ci_lo     ci_hi       n
-------------------------------------------------------------------------
A vs B                                  0.688     0.579     0.778      80
B vs C                                  0.611     0.508     0.705      90
A vs C                                  0.786     0.676     0.866      70

score-based Elo ranked table (draws=0.5, no draw-stripping)
name                   elo    raw_strength       score_games
------------------------------------------------------------
A                      0.0         1.52089               200
B                    -97.5        0.867801               200
C                   -158.3         0.61131               200

draw-rate matrix
               A       B       C
A             --   0.200   0.300
B          0.200      --   0.100
C          0.300   0.100      --

diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..9023fb1a946ffe18ba74cfa3144549f4e12ac845
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,94 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered, all_names):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    ordered_set = set(ordered)
+    names = list(ordered) + [name for name in all_names if name not in ordered_set]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +356,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +395,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered, names)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

exec
/bin/zsh -lc "nl -ba tools/bt_fit.py | sed -n '95,180p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
    95	            "w_b": w_b,
    96	            "n": n_decisive,
    97	            "p_a": w_a / n_decisive,
    98	        }
    99	
   100	    return names, wins, games, raw, skipped
   101	
   102	
   103	def score_counts(rows):
   104	    names = []
   105	    seen = set()
   106	    wins = defaultdict(float)
   107	    games = defaultdict(float)
   108	    skipped = []
   109	
   110	    for row in rows:
   111	        a, b = row["a"], row["b"]
   112	        for name in (a, b):
   113	            if name not in seen:
   114	                seen.add(name)
   115	                names.append(name)
   116	
   117	        total = float(row["total"])
   118	        if total <= 0:
   119	            skipped.append((a, b, "zero total games"))
   120	            continue
   121	
   122	        w_a = max(0.0, min(total, row["a_rate"] * total))
   123	        w_b = max(0.0, min(total, row["b_rate"] * total))
   124	        wins[(a, b)] += w_a
   125	        wins[(b, a)] += w_b
   126	        games[frozenset((a, b))] += total
   127	
   128	    return names, wins, games, skipped
   129	
   130	
   131	def row_decisive_summary(row):
   132	    denom = 1.0 - row["draw"]
   133	    if denom <= EPS:
   134	        return None
   135	    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
   136	    p_a = max(0.0, min(1.0, p_a))
   137	    n_decisive = int(round(row["total"] * denom))
   138	    if n_decisive <= 0:
   139	        return None
   140	    w_a = int(round(n_decisive * p_a))
   141	    w_a = max(0, min(n_decisive, w_a))
   142	    return n_decisive, w_a, n_decisive - w_a, p_a
   143	
   144	
   145	def wilson_interval(k, n, z=1.96):
   146	    if n <= 0:
   147	        return None
   148	    phat = k / n
   149	    denom = 1.0 + z * z / n
   150	    center = (phat + z * z / (2.0 * n)) / denom
   151	    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
   152	    return center - half, center + half
   153	
   154	
   155	def connected_components(fit_names, games):
   156	    graph = {name: set() for name in fit_names}
   157	    for pair, n in games.items():
   158	        if n <= 0 or len(pair) != 2:
   159	            continue
   160	        a, b = tuple(pair)
   161	        if a in graph and b in graph:
   162	            graph[a].add(b)
   163	            graph[b].add(a)
   164	
   165	    comps = []
   166	    unseen = set(fit_names)
   167	    while unseen:
   168	        start = unseen.pop()
   169	        comp = []
   170	        q = deque([start])
   171	        while q:
   172	            cur = q.popleft()
   173	            comp.append(cur)
   174	            for nxt in graph[cur]:
   175	                if nxt in unseen:
   176	                    unseen.remove(nxt)
   177	                    q.append(nxt)
   178	        comps.append(comp)
   179	    return comps
   180	

exec
/bin/zsh -lc "nl -ba tools/bt_fit.py | sed -n '220,330p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   220	    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
   221	
   222	
   223	def anchored_elo(fit_names, pi, anchor, scale):
   224	    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
   225	    anchor_elo = raw_elo[anchor]
   226	    return {name: raw_elo[name] - anchor_elo for name in fit_names}
   227	
   228	
   229	def full_residuals(raw, fit_names, pi):
   230	    fit_set = set(fit_names)
   231	    residuals = []
   232	    for pair_raw in raw.values():
   233	        a, b = pair_raw["a"], pair_raw["b"]
   234	        if a not in fit_set or b not in fit_set:
   235	            continue
   236	        fit_p = pi[a] / (pi[a] + pi[b])
   237	        empirical_p = pair_raw["p_a"]
   238	        residuals.append({
   239	            "a": a,
   240	            "b": b,
   241	            "fit_p": fit_p,
   242	            "empirical_p": empirical_p,
   243	            "n": pair_raw["n"],
   244	            "abs_err": abs(fit_p - empirical_p),
   245	        })
   246	    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
   247	
   248	
   249	def print_score_table(rows, anchor, scale, decisive_order):
   250	    score_names, score_wins, score_games, score_skipped = score_counts(rows)
   251	    total_score_games = {
   252	        name: sum(n for pair, n in score_games.items() if name in pair)
   253	        for name in score_names
   254	    }
   255	    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
   256	    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
   257	    if len(fit_score_names) < 2 or anchor not in fit_score_names:
   258	        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
   259	        print("skipped: need at least two score-connected anchors including anchor")
   260	        return
   261	
   262	    comps = connected_components(fit_score_names, score_games)
   263	    if len(comps) > 1:
   264	        keep = set(max(comps, key=len))
   265	        fit_score_names = [name for name in fit_score_names if name in keep]
   266	        if anchor not in fit_score_names:
   267	            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
   268	            print("skipped: anchor is not in the largest score-connected component")
   269	            return
   270	
   271	    score_pi = fit_bt(fit_score_names, score_wins, score_games)
   272	    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
   273	    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
   274	    ordered = sorted(
   275	        fit_score_names,
   276	        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
   277	        reverse=True,
   278	    )
   279	
   280	    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
   281	    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
   282	    print("-" * 60)
   283	    for name in ordered:
   284	        print(f"{name:<16}{score_elo[name]:>10.1f}"
   285	              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
   286	    for a, b, why in score_skipped:
   287	        warn(f"skipping {a} vs {b} for score fit: {why}")
   288	
   289	
   290	def print_draw_matrix(rows, ordered, all_names):
   291	    draw_by_pair = {}
   292	    for row in rows:
   293	        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
   294	
   295	    ordered_set = set(ordered)
   296	    names = list(ordered) + [name for name in all_names if name not in ordered_set]
   297	    width = max(8, max(len(name) for name in names) + 1) if names else 8
   298	    print("draw-rate matrix")
   299	    print(" " * width + "".join(f"{name:>{width}}" for name in names))
   300	    for a in names:
   301	        cells = []
   302	        for b in names:
   303	            if a == b:
   304	                cells.append("--")
   305	            else:
   306	                draw = draw_by_pair.get(frozenset((a, b)))
   307	                cells.append("--" if draw is None else f"{draw:.3f}")
   308	        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
   309	
   310	
   311	def main():
   312	    ap = argparse.ArgumentParser(
   313	        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
   314	    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
   315	    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
   316	    ap.add_argument("--scale", type=float, default=400.0,
   317	                    help="Elo display scale, default 400")
   318	    args = ap.parse_args()
   319	
   320	    if np is None:
   321	        warn("numpy unavailable; using pure Python math fallback")
   322	
   323	    rows = parse_rows(args.csv_path)
   324	    if not rows:
   325	        raise SystemExit("no CSV rows found")
   326	
   327	    names, wins, games, raw, skipped = decisive_counts(rows)
   328	    total_decisive = {
   329	        name: sum(n for pair, n in games.items() if name in pair)
   330	        for name in names

exec
/bin/zsh -lc "nl -ba tools/bt_fit.py | sed -n '380,450p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
   380	    print("-" * 60)
   381	    for name in ordered:
   382	        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
   383	
   384	    print()
   385	    print("adjacent fitted-vs-empirical decisive win rates")
   386	    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
   387	    print("-" * 67)
   388	    for i in range(len(ordered) - 1):
   389	        hi, lo = ordered[i], ordered[i + 1]
   390	        fit_p = pi[hi] / (pi[hi] + pi[lo])
   391	        emp = empirical_between(hi, lo, wins, games)
   392	        if emp is None:
   393	            emp_s, n_s = "--", "--"
   394	        else:
   395	            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
   396	        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
   397	
   398	    print()
   399	    print("full pairwise residuals (decisive-Elo model)")
   400	    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
   401	    print("-" * 77)
   402	    for r in full_residuals(raw, fit_names, pi):
   403	        print(f"{r['a'] + ' vs ' + r['b']:<35}"
   404	              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
   405	              f"{r['n']:>8}{r['abs_err']:>10.3f}")
   406	
   407	    print()
   408	    print("Wilson 95% CI per pairing on decisive A win-rate")
   409	    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
   410	    print("-" * 73)
   411	    for row in rows:
   412	        summary = row_decisive_summary(row)
   413	        if summary is None:
   414	            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
   415	        else:
   416	            n_decisive, w_a, _, _ = summary
   417	            ci = wilson_interval(w_a, n_decisive)
   418	            p_s = f"{w_a / n_decisive:.3f}"
   419	            lo_s = f"{ci[0]:.3f}"
   420	            hi_s = f"{ci[1]:.3f}"
   421	            n_s = str(n_decisive)
   422	        print(f"{row['a'] + ' vs ' + row['b']:<35}"
   423	              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
   424	
   425	    print()
   426	    print_score_table(rows, anchor, args.scale, ordered)
   427	
   428	    print()
   429	    print_draw_matrix(rows, ordered, names)
   430	
   431	    if excluded:
   432	        print()
   433	        print("excluded zero-information anchors: " + ", ".join(excluded))
   434	
   435	
   436	if __name__ == "__main__":
   437	    main()

exec
/bin/zsh -lc 'git diff --name-only' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
tools/bt_fit.py

diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..9023fb1a946ffe18ba74cfa3144549f4e12ac845
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,94 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered, all_names):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    ordered_set = set(ordered)
+    names = list(ordered) + [name for name in all_names if name not in ordered_set]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +356,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +395,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered, names)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

codex
Implemented the H1 diagnostics in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:103), with edits limited to that file and no git state changes beyond the working-tree modification.

**Diff Summary**

Added:

- `score_counts()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:103)
  Builds the parallel score-based BT inputs using fractional wins:
  `w_a = A_rate * total_games`, `w_b = B_rate * total_games`.

- `wilson_interval()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:145)
  Closed-form Wilson 95% interval, no scipy.

- `anchored_elo()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:223)
  Small helper to reuse the existing anchor/scale logic for both decisive and score-based fits.

- `full_residuals()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:229)
  Produces all measured decisive pair residuals, sorted by `abs(fit_p - empirical_p)` descending.

- `print_score_table()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:249)
  Prints the score-based Elo table labeled as `draws=0.5, no draw-stripping`.

- `print_draw_matrix()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:290)
  Prints a square draw-rate matrix ordered first by decisive Elo ranking, then any unranked names in input order.

Changed:

- Replaced the inline decisive Elo anchoring calculation with `anchored_elo()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:356).
- Appended the new output sections after the existing adjacent table in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:398).
- Left the existing raw pair table, decisive-only ranked table, and adjacent fitted-vs-empirical section shape/text intact.

**Verification**

Passed:

```bash
python3 -m py_compile tools/bt_fit.py
python3 tools/bt_fit.py --help
```

Also ran the requested smoke CSV inline.

New sections from the smoke-test output:

```text
full pairwise residuals (decisive-Elo model)
pair                                    fit_p   empirical_p       n   abs_err
-----------------------------------------------------------------------------
A vs C                                  0.781         0.786      70     0.004
A vs B                                  0.691         0.688      80     0.004
B vs C                                  0.615         0.611      90     0.003

Wilson 95% CI per pairing on decisive A win-rate
pair                                  A_dec_p     ci_lo     ci_hi       n
-------------------------------------------------------------------------
A vs B                                  0.688     0.579     0.778      80
B vs C                                  0.611     0.508     0.705      90
A vs C                                  0.786     0.676     0.866      70

score-based Elo ranked table (draws=0.5, no draw-stripping)
name                   elo    raw_strength       score_games
------------------------------------------------------------
A                      0.0         1.52089               200
B                    -97.5        0.867801               200
C                   -158.3         0.61131               200

draw-rate matrix
               A       B       C
A             --   0.200   0.300
B          0.200      --   0.100
C          0.300   0.100      --
```

The Wilson intervals bracket the point estimates, and the score-based ladder is plausibly similar but less spread than the decisive-only ladder on this 3-node example.

**Deviations**

No functional deviations from the brief. One label clarification: the score-based table keeps the same four-column layout as the decisive table, but the last column is named `score_games` instead of `decisive_games` because that fit uses total games, including draws as half-score signal.
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
index c763d37a722b5f2fa5a58b1bc15f19b85456289d..9023fb1a946ffe18ba74cfa3144549f4e12ac845
--- a/tools/bt_fit.py
+++ b/tools/bt_fit.py
@@ -100,6 +100,34 @@
     return names, wins, games, raw, skipped
 
 
+def score_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        total = float(row["total"])
+        if total <= 0:
+            skipped.append((a, b, "zero total games"))
+            continue
+
+        w_a = max(0.0, min(total, row["a_rate"] * total))
+        w_b = max(0.0, min(total, row["b_rate"] * total))
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += total
+
+    return names, wins, games, skipped
+
+
 def row_decisive_summary(row):
     denom = 1.0 - row["draw"]
     if denom <= EPS:
@@ -114,6 +142,16 @@
     return n_decisive, w_a, n_decisive - w_a, p_a
 
 
+def wilson_interval(k, n, z=1.96):
+    if n <= 0:
+        return None
+    phat = k / n
+    denom = 1.0 + z * z / n
+    center = (phat + z * z / (2.0 * n)) / denom
+    half = (z * math.sqrt(phat * (1.0 - phat) / n + z * z / (4.0 * n * n))) / denom
+    return center - half, center + half
+
+
 def connected_components(fit_names, games):
     graph = {name: set() for name in fit_names}
     for pair, n in games.items():
@@ -182,6 +220,94 @@
     return wins.get((stronger, weaker), 0.0) / n, int(round(n))
 
 
+def anchored_elo(fit_names, pi, anchor, scale):
+    raw_elo = {name: scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    return {name: raw_elo[name] - anchor_elo for name in fit_names}
+
+
+def full_residuals(raw, fit_names, pi):
+    fit_set = set(fit_names)
+    residuals = []
+    for pair_raw in raw.values():
+        a, b = pair_raw["a"], pair_raw["b"]
+        if a not in fit_set or b not in fit_set:
+            continue
+        fit_p = pi[a] / (pi[a] + pi[b])
+        empirical_p = pair_raw["p_a"]
+        residuals.append({
+            "a": a,
+            "b": b,
+            "fit_p": fit_p,
+            "empirical_p": empirical_p,
+            "n": pair_raw["n"],
+            "abs_err": abs(fit_p - empirical_p),
+        })
+    return sorted(residuals, key=lambda r: r["abs_err"], reverse=True)
+
+
+def print_score_table(rows, anchor, scale, decisive_order):
+    score_names, score_wins, score_games, score_skipped = score_counts(rows)
+    total_score_games = {
+        name: sum(n for pair, n in score_games.items() if name in pair)
+        for name in score_names
+    }
+    score_excluded = [name for name in score_names if total_score_games[name] <= 0]
+    fit_score_names = [name for name in score_names if name not in set(score_excluded)]
+    if len(fit_score_names) < 2 or anchor not in fit_score_names:
+        print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+        print("skipped: need at least two score-connected anchors including anchor")
+        return
+
+    comps = connected_components(fit_score_names, score_games)
+    if len(comps) > 1:
+        keep = set(max(comps, key=len))
+        fit_score_names = [name for name in fit_score_names if name in keep]
+        if anchor not in fit_score_names:
+            print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+            print("skipped: anchor is not in the largest score-connected component")
+            return
+
+    score_pi = fit_bt(fit_score_names, score_wins, score_games)
+    score_elo = anchored_elo(fit_score_names, score_pi, anchor, scale)
+    decisive_rank = {name: i for i, name in enumerate(decisive_order)}
+    ordered = sorted(
+        fit_score_names,
+        key=lambda name: (score_elo[name], -decisive_rank.get(name, len(decisive_rank))),
+        reverse=True,
+    )
+
+    print("score-based Elo ranked table (draws=0.5, no draw-stripping)")
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'score_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{score_elo[name]:>10.1f}"
+              f"{score_pi[name]:>16.6g}{total_score_games[name]:>18.0f}")
+    for a, b, why in score_skipped:
+        warn(f"skipping {a} vs {b} for score fit: {why}")
+
+
+def print_draw_matrix(rows, ordered, all_names):
+    draw_by_pair = {}
+    for row in rows:
+        draw_by_pair[frozenset((row["a"], row["b"]))] = row["draw"]
+
+    ordered_set = set(ordered)
+    names = list(ordered) + [name for name in all_names if name not in ordered_set]
+    width = max(8, max(len(name) for name in names) + 1) if names else 8
+    print("draw-rate matrix")
+    print(" " * width + "".join(f"{name:>{width}}" for name in names))
+    for a in names:
+        cells = []
+        for b in names:
+            if a == b:
+                cells.append("--")
+            else:
+                draw = draw_by_pair.get(frozenset((a, b)))
+                cells.append("--" if draw is None else f"{draw:.3f}")
+        print(f"{a:<{width}}" + "".join(f"{cell:>{width}}" for cell in cells))
+
+
 def main():
     ap = argparse.ArgumentParser(
         description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
@@ -230,9 +356,7 @@
         raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
 
     pi = fit_bt(fit_names, wins, games)
-    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
-    anchor_elo = raw_elo[anchor]
-    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    elo = anchored_elo(fit_names, pi, anchor, args.scale)
     ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
 
     print("raw pair table")
@@ -271,6 +395,39 @@
             emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
         print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
 
+    print()
+    print("full pairwise residuals (decisive-Elo model)")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}{'abs_err':>10}")
+    print("-" * 77)
+    for r in full_residuals(raw, fit_names, pi):
+        print(f"{r['a'] + ' vs ' + r['b']:<35}"
+              f"{r['fit_p']:>10.3f}{r['empirical_p']:>14.3f}"
+              f"{r['n']:>8}{r['abs_err']:>10.3f}")
+
+    print()
+    print("Wilson 95% CI per pairing on decisive A win-rate")
+    print(f"{'pair':<35}{'A_dec_p':>10}{'ci_lo':>10}{'ci_hi':>10}{'n':>8}")
+    print("-" * 73)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            p_s, lo_s, hi_s, n_s = "--", "--", "--", "--"
+        else:
+            n_decisive, w_a, _, _ = summary
+            ci = wilson_interval(w_a, n_decisive)
+            p_s = f"{w_a / n_decisive:.3f}"
+            lo_s = f"{ci[0]:.3f}"
+            hi_s = f"{ci[1]:.3f}"
+            n_s = str(n_decisive)
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{p_s:>10}{lo_s:>10}{hi_s:>10}{n_s:>8}")
+
+    print()
+    print_score_table(rows, anchor, args.scale, ordered)
+
+    print()
+    print_draw_matrix(rows, ordered, names)
+
     if excluded:
         print()
         print("excluded zero-information anchors: " + ", ".join(excluded))

tokens used
78,111
Implemented the H1 diagnostics in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:103), with edits limited to that file and no git state changes beyond the working-tree modification.

**Diff Summary**

Added:

- `score_counts()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:103)
  Builds the parallel score-based BT inputs using fractional wins:
  `w_a = A_rate * total_games`, `w_b = B_rate * total_games`.

- `wilson_interval()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:145)
  Closed-form Wilson 95% interval, no scipy.

- `anchored_elo()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:223)
  Small helper to reuse the existing anchor/scale logic for both decisive and score-based fits.

- `full_residuals()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:229)
  Produces all measured decisive pair residuals, sorted by `abs(fit_p - empirical_p)` descending.

- `print_score_table()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:249)
  Prints the score-based Elo table labeled as `draws=0.5, no draw-stripping`.

- `print_draw_matrix()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:290)
  Prints a square draw-rate matrix ordered first by decisive Elo ranking, then any unranked names in input order.

Changed:

- Replaced the inline decisive Elo anchoring calculation with `anchored_elo()` in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:356).
- Appended the new output sections after the existing adjacent table in [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py:398).
- Left the existing raw pair table, decisive-only ranked table, and adjacent fitted-vs-empirical section shape/text intact.

**Verification**

Passed:

```bash
python3 -m py_compile tools/bt_fit.py
python3 tools/bt_fit.py --help
```

Also ran the requested smoke CSV inline.

New sections from the smoke-test output:

```text
full pairwise residuals (decisive-Elo model)
pair                                    fit_p   empirical_p       n   abs_err
-----------------------------------------------------------------------------
A vs C                                  0.781         0.786      70     0.004
A vs B                                  0.691         0.688      80     0.004
B vs C                                  0.615         0.611      90     0.003

Wilson 95% CI per pairing on decisive A win-rate
pair                                  A_dec_p     ci_lo     ci_hi       n
-------------------------------------------------------------------------
A vs B                                  0.688     0.579     0.778      80
B vs C                                  0.611     0.508     0.705      90
A vs C                                  0.786     0.676     0.866      70

score-based Elo ranked table (draws=0.5, no draw-stripping)
name                   elo    raw_strength       score_games
------------------------------------------------------------
A                      0.0         1.52089               200
B                    -97.5        0.867801               200
C                   -158.3         0.61131               200

draw-rate matrix
               A       B       C
A             --   0.200   0.300
B          0.200      --   0.100
C          0.300   0.100      --
```

The Wilson intervals bracket the point estimates, and the score-based ladder is plausibly similar but less spread than the decisive-only ladder on this 3-node example.

**Deviations**

No functional deviations from the brief. One label clarification: the score-based table keeps the same four-column layout as the decisive table, but the last column is named `score_games` instead of `decisive_games` because that fit uses total games, including draws as half-score signal.
