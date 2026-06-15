# Brief: anchored cross-generation Elo/Bradley-Terry ladder (H1, fable-5 memo)

Repo: /Users/alexanderhuth/Code/bloodbowl-rl. No git state changes (no commit/push/checkout) —
leave new files in the working tree for the architect to review and commit. Match existing
script style in tools/ (bash scripts use `set -euo pipefail`-style headers like
tools/eval_game_stats.sh; python tools use argparse like tools/parity_report.py /
tools/game_stats.py).

## Context
We have 7 checkpoints (flat-fp32 CUDA blobs, all 16,066,560 bytes, obs-v4) representing the
full lineage history: bc_v4, v4-kickoff-8, v5-contested, gen-1/gen-2/gen-3 (the contested-era
ratchet), and league-1. Every strength claim so far (D93/D95/D96/D97) has been PAIRWISE —
adjacent-generation or pool-internal. We want a round-robin tournament across all pairs,
fit to a single Bradley-Terry/Elo scale, to put every future verdict on an absolute axis.

Tournament mechanics (existing, proven — see DECISIONS.md D91/D93/D95/D97 and the puffer
match invocation pattern):
```
puffer match bloodbowl --load-model-path A.bin --load-enemy-model-path B.bin \
  --num-games 2048 --env.macro-moves 0
```
prints repeated lines like `games=N/2048  A=0.550  B=0.450  draw=0.419` as it progresses
(carriage-return-updated); the LAST such line is the final result. A/B include draws split
50/50 into each side's rate (i.e. A = (outrightA + 0.5*draws)/total, same for B, and
A+B == 1.0 always; draw is the separate draw fraction). 2048 games takes roughly 30-90s on
the 2070 (RTX 2070, torch backend, native .venv at vendor/PufferLib/.venv).

## Deliverable 1: tools/anchored_ladder.sh
A bash script, run from repo root on the 2070 rig (paths below are RIG paths under
~/bloodbowl-rl, not Mac paths — write the script to be portable, taking a checkpoint
directory as an argument or env var, default `training/`):

- Anchor set (name -> filename under the checkpoint dir, default `training/`):
  ```
  bc_v4       bc_v4_cuda.bin
  kickoff8    v4k8_cap.bin
  v5contested v5_contested_cap.bin
  gen1        v4_contested_cap.bin
  gen2        v4_contested2_cap.bin
  gen3        v4_contested3_cap.bin
  league1     league_cap.bin
  ```
  Support an optional EXTRA_ANCHORS env var: a space-separated list of `name=filename` pairs
  appended to the anchor set (so gen-4/league-2 can be added later without editing the script).
- Skip any anchor whose file doesn't exist (warn to stderr, continue) — don't hard-fail if
  gen-4/league-2 aren't there yet.
- For every UNORDERED pair {A, B} among present anchors (no self-pairs, no duplicate
  reversed pairs — C(n,2) total), run the puffer match command above with
  `--num-games ${GAMES:-2048}`, `--env.macro-moves 0`.
- Source `rig-env.sh` and put the venv on PATH first, same pattern as other rig scripts
  (`cd ~/bloodbowl-rl && . rig-env.sh 2>/dev/null; export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"`)
  — run `cd vendor/PufferLib` before invoking `puffer match`, paths to checkpoints must be
  absolute or correctly relative from there.
- Parse the LAST `games=` line robustly (the output uses `\r` to overwrite, like prior
  tournament logs — strip `\r` via `tr '\r' '\n'` and take the last matching line).
- Append one CSV row per pairing to `${OUT:-/tmp/anchored_ladder.csv}`:
  `nameA,nameB,A_rate,B_rate,draw_rate,total_games` (create the file with a header row if it
  doesn't exist; APPEND so a partial/interrupted run can resume — but for v1 just always
  start fresh unless `--resume` is passed, in which case skip pairs already present in the
  existing CSV).
- Print progress to stdout: `[k/21] nameA vs nameB -> A=... B=... draw=...` as each completes.
- At the end, print the path to the CSV and a one-line summary (total pairings run).

## Deliverable 2: tools/bt_fit.py
A small python script (argparse, stdlib + numpy only — check numpy is available in the rig
venv; if you're unsure, write it to also work with pure python lists/math if numpy import
fails, falling back gracefully with a warning printed to stderr):

- Usage: `python3 tools/bt_fit.py /tmp/anchored_ladder.csv [--anchor NAME] [--scale 400]`
- Read the CSV (columns as in Deliverable 1).
- For each row, compute the DECISIVE win probability for A:
  `p_A = (A_rate - 0.5*draw_rate) / (1 - draw_rate)` (guard divide-by-zero: if
  `1 - draw_rate` is 0 or negative/near-zero, skip that pairing for the fit but still report
  it in the raw table — note in a comment that 100%-draw pairings carry no BT information).
  Effective decisive game count: `n_decisive = round(total_games * (1 - draw_rate))`.
  Win count for A: `w_A = round(n_decisive * p_A)`, `w_B = n_decisive - w_A`.
- Fit Bradley-Terry ratings via the standard iterative MM (Zermelo) algorithm:
  initialize all ratings (as "strengths" pi_i, pi_i > 0) to 1.0; iterate
  `pi_i_new = W_i / sum_{j != i} (n_ij / (pi_i + pi_j))` where `W_i = sum_j w_ij` (total
  decisive wins of i over all opponents) and `n_ij` is decisive games between i and j; repeat
  ~200 iterations or until max relative change < 1e-9; this is a well-known closed-form-ish
  iteration, implement it directly (no scipy dependency).
- Convert strengths to Elo-like display ratings: `elo_i = scale * log10(pi_i) - scale *
  log10(pi_anchor)` where `--anchor` (default: the first row's nameA, or `bc_v4` if present)
  is pinned to elo 0 and `--scale` defaults to 400 (standard Elo log-odds scale, since
  log-odds(p) = (elo_i - elo_j) / scale * ln(10) in the standard convention — just implement
  `elo_i = scale * log10(pi_i)` for all i, then SUBTRACT the anchor's value from every rating
  so the anchor sits at 0; do not overthink the exact constant, the point is a consistent
  relative scale).
- Print a sorted table (strongest first): `name  elo  raw_strength  total_decisive_games`.
- Also print, for each consecutive pair in the SORTED table, the implied head-to-head win
  probability from the fitted ratings (`pi_i / (pi_i + pi_j)`) next to the EMPIRICAL
  decisive win rate from the raw CSV if that exact pairing was measured directly — this lets
  a human sanity-check fit-vs-measured for adjacent ratings (the gen1/gen2/gen3 chain
  especially).
- Handle disconnected pairs gracefully (if the anchor set isn't fully connected the MM
  iteration can still run as long as the WHOLE graph is connected — with C(7,2)=21 pairings
  on 7 nodes it's a complete graph so this won't happen here, but don't crash if a future
  EXTRA_ANCHORS run has fewer pairings; just note in output if any node has zero decisive
  games vs everyone — exclude it from the fit and print a warning).

## Constraints
- No engine/training code touched — these are standalone tooling scripts under tools/.
- Do not run the ladder yourself (no GPU access / this is for the 2070 rig) — just write and
  syntax-check the scripts (`bash -n tools/anchored_ladder.sh`, and run
  `python3 tools/bt_fit.py --help` plus a tiny synthetic CSV smoke test you construct
  inline — e.g. a 3-node cycle with made-up rates — to confirm bt_fit.py runs end-to-end and
  produces a sane sorted table without crashing).

## Report back
- Edit map (new files only).
- `bash -n` output for the shell script (should be silent/exit 0).
- The synthetic smoke-test invocation + its output for bt_fit.py.
- Any deviations from this brief with reasoning.
