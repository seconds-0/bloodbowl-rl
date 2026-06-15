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
session id: 019ebe53-33e2-7501-b670-3b7448b2c3a6
--------
user
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
deprecated: `[features].collab` is deprecated. Use `[features].multi_agent` instead.
Enable it with `--enable multi_agent` or `[features].multi_agent` in config.toml. See https://developers.openai.com/codex/config-basic#feature-flags for details.
codex
I’ll add the two standalone tools and keep the repo state untouched beyond new files. First I’m going to skim the existing `tools/` style so the scripts feel native here.
exec
/bin/zsh -lc "sed -n '1,220p' tools/eval_game_stats.sh" in /Users/alexanderhuth/Code/bloodbowl-rl
exec
/bin/zsh -lc "sed -n '1,220p' tools/parity_report.py" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
#!/usr/bin/env bash
# eval_game_stats.sh — run a checkpoint through FULL GAMES from kickoff and
# emit a dashboard log whose per-game stats are comparable to the human
# baseline (docs/human-baseline.json). Feed the output to game_stats.py.
#
#   bash tools/eval_game_stats.sh <CHECKPOINT.bin> [STEPS] [LOG]
#       CHECKPOINT  torch state_dict .bin (the training-side format, NOT a
#                   _cuda flat blob). Run ON a box from /root/bloodbowl-rl.
#       STEPS       measurement length, default 8M (~thousands of full games
#                   at 128 agents; plenty for stable per-game averages).
#       LOG         output path, default /tmp/game_stats_eval.log
#
# Mechanism: a FROZEN measurement pass — learning-rate ~0, bc-coef 0,
# selfplay off, demo-reset-pct 0 (KICKOFF starts, the whole point — training
# arms use 0.9 curriculum starts which are NOT human-comparable). The env's
# my_log dashboard then reports true per-game tds/blocks/dodges/gfi/pickups/
# possession + the 2d tier fractions. Then:
#   python3 tools/game_stats.py <LOG>
set -euo pipefail
CKPT="${1:?usage: eval_game_stats.sh <checkpoint.bin> [steps] [log]}"
STEPS="${2:-8000000}"
LOG="${3:-/tmp/game_stats_eval.log}"
# consume the positionals so "$@" below carries ONLY trailing puffer args
for _ in 1 2 3; do [ $# -gt 0 ] && shift; done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Anchor relative paths NOW — the cd to vendor/PufferLib below breaks them
# (same footgun as run_synthesis_c.sh's ANCHOR: the file-exists check passes
# pre-cd, then puffer FileNotFoundErrors post-cd).
case "$CKPT" in /*) ;; *) CKPT="$PWD/$CKPT" ;; esac
case "$LOG"  in /*) ;; *) LOG="$PWD/$LOG"   ;; esac
[ -f "$CKPT" ] || { echo "checkpoint not found: $CKPT" >&2; exit 1; }

# Same CPU thread cap as the training launchers (D59).
. "$ROOT/tools/cpu_cap.sh"

cd "$ROOT/vendor/PufferLib"
echo "measuring $CKPT over $STEPS steps (kickoff starts, frozen) -> $LOG" >&2
# --slowly = torch backend (loads a torch state_dict). lr 1e-12 + bc-coef 0 =
# effectively frozen; demo-reset-pct 0 = full games from kickoff.
puffer train bloodbowl --slowly --selfplay.enabled 0 \
  --load-model-path "$CKPT" \
  --tag game-stats-eval \
  --train.total-timesteps "$STEPS" \
  --train.learning-rate 0.000000000001 \
  --train.bc-coef 0 \
  --env.demo-reset-pct 0 \
  --vec.total-agents 256 --vec.num-threads "${OMP_NUM_THREADS:-8}" \
  --train.minibatch-size 2048 \
  "$@" \
  > "$LOG" 2>&1

echo "done. compare with:  python3 $ROOT/tools/game_stats.py $LOG" >&2

 succeeded in 0ms:
#!/usr/bin/env python3
"""parity_report.py — native-vs-torch A/B verdict harness (D57).

Compares two PufferLib training logs (the rich dashboard output captured to a
file) and prints a matched-step comparison table, SPS ratio, per-metric
verdicts, and wall-clock-to-target-tds projections. Pure stdlib, no deps.

CURRENT A/B (the D57 native-asym parity question):
    LOG A (native): /tmp/profile-v4-native-asym.log on box-1 (bb-japan-native)
        native CUDA backend, no bc aux, frozen bc_v4 teacher via 1-seed league
        pool, ~2.1M SPS.
    LOG B (torch):  /tmp/profile-v4-s2.log on bb-ballhawk (box-3)
        torch flagship v4_s2, maxdist 9, ~0.6M SPS.

Fetch the FULL logs to your Mac first (key ~/.ssh/id_ed25519). Full files,
not tail slices: a tail of A and a tail of B usually cover DIFFERENT step
windows, so the matched-step table comes up empty.

    scp -i ~/.ssh/id_ed25519 -P 12464 root@ssh3.vast.ai:/tmp/profile-v4-native-asym.log /tmp/native.log
    scp -i ~/.ssh/id_ed25519 -P 25430 root@ssh4.vast.ai:/tmp/profile-v4-s2.log /tmp/torch.log

Mac->ssh4 can be pathologically slow. If the second scp crawls, hop via
box-1 instead (3 commands; the -A hop needs the key in your agent):

    ssh-add ~/.ssh/id_ed25519
    ssh -A -i ~/.ssh/id_ed25519 -p 12464 root@ssh3.vast.ai \
        "scp -o StrictHostKeyChecking=no -P 25430 root@ssh4.vast.ai:/tmp/profile-v4-s2.log /tmp/torch.log"
    scp -i ~/.ssh/id_ed25519 -P 12464 root@ssh3.vast.ai:/tmp/torch.log /tmp/torch.log

Then:

    tools/parity_report.py /tmp/native.log /tmp/torch.log
    # or, if the exec bit got lost in transit:
    python3 tools/parity_report.py /tmp/native.log /tmp/torch.log

READING THE VERDICT (metric semantics, see CLAUDE.md / training-experiments):
  - tds: per-episode TDs FROM CURRICULUM STARTS. Only comparable because both
    arms run demo-endzone-maxdist 9; do NOT feed logs from different stages.
    Higher = better. PARITY within the band = the 3.5x SPS lever ships.
  - block_2dred_frac: fraction of blocks thrown at 2-dice-against. LOWER =
    better (falling = probability planes working; human 0.017). The native arm
    reading ~0.105 vs torch ~0.20 would be a major finding, not a regression.
  - gfi_attempts: informational/artifact per D46 (human 2-5/ep, agent 25-35)
    unless tournament-grounded. Lower = nominally better; weigh lightly.
  - Step counts are parsed from the dashboard's abbreviated display (e.g.
    "1.8B"), so alignment granularity is ~100M at B scale — well within the
    default 200M match tolerance.

CAVEATS for the successor:
  - The asymmetric native run overshoots total steps ~1.5x (known, benign).
  - tds parity at matched STEPS is the question; the native arm wins wall-clock
    regardless (see the per-1B wall-cost lines).
  - This reads the live dashboard frames, so a freshly relaunched log restarts
    at low steps (warm-start reloads weights but global_step resets). The
    report detects step-count regressions, warns, and uses only the final
    monotonic segment for SPS/projections; the matched-step table still uses
    everything. For a clean read, pass only the segment you want judged.

VERIFIED 2026-06-08 against the live logs on box-1/box-3 (682- and 479-frame
tails parsed; tds/block_2dred_frac/gfi_attempts/SPS all matched the dashboard)
and against rich-rendered synthetic fixtures at width 80 (no color, redirected
output) and 120 (tmux capture). Metric names are the binding.c my_log keys as
displayed by pufferl.py print_dashboard (env/ prefix stripped, %.3f).
"""
import argparse
import math
import re
import statistics
import sys

ANSI_RE = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07')
MULT = {'': 1.0, 'K': 1e3, 'M': 1e6, 'B': 1e9, 'T': 1e12}

STEPS_RE = re.compile(r'(?<![\w/])Steps\s+([0-9]+(?:\.[0-9]+)?)\s*([KMBT]?)(?![\w.])')
SPS_RE = re.compile(r'(?<![\w/])SPS\s+([0-9]+(?:\.[0-9]+)?)\s*([KMBT]?)(?![\w.])')
USER_METRICS = ('tds', 'block_2dred_frac', 'gfi_attempts')
USER_RES = {m: re.compile(r'(?<![\w/])' + re.escape(m) + r'\s+(-?[0-9]+\.[0-9]+)')
            for m in USER_METRICS}

# (display_name, higher_is_better, note)
VERDICT_SPEC = [
    ('tds', True, 'curriculum-start TDs'),
    ('block_2dred_frac', False, 'lower = planes working'),
    ('gfi_attempts', False, 'informational (D46 artifact)'),
]


def parse_log(path):
    """Return list of frame dicts: {'steps','sps','tds',...} in file order."""
    with open(path, 'r', errors='replace') as f:
        text = f.read()
    text = ANSI_RE.sub('', text).replace('\r', '\n')

    frames = []
    cur = None
    for line in text.split('\n'):
        m = STEPS_RE.search(line)
        if m:
            if cur is not None and cur.get('steps', 0) > 0:
                frames.append(cur)
            cur = {'steps': float(m.group(1)) * MULT[m.group(2)]}
            continue
        if cur is None:
            continue
        m = SPS_RE.search(line)
        if m and 'sps' not in cur:
            cur['sps'] = float(m.group(1)) * MULT[m.group(2)]
        for name, rx in USER_RES.items():
            if name not in cur:
                m2 = rx.search(line)
                if m2:
                    cur[name] = float(m2.group(1))
    if cur is not None and cur.get('steps', 0) > 0:
        frames.append(cur)
    # Drop frames with no metrics at all beyond steps (startup banners etc.)
    return [fr for fr in frames if len(fr) > 1]


def final_segment(frames):
    """(n_restarts, frames after the last steps regression).

    The dashboard's abbreviated step display is monotone non-decreasing for a
    single run, so any strict decrease means the box was relaunched and the
    log keeps both runs. Trend/SPS math should only see the final run.
    """
    start, restarts = 0, 0
    for i in range(1, len(frames)):
        if frames[i]['steps'] < frames[i - 1]['steps']:
            start, restarts = i, restarts + 1
    return restarts, frames[start:]


def nearest_frame(frames, target, tol):
    """Frame whose steps is closest to target within tol, preferring later."""
    best, best_d = None, None
    for fr in frames:
        d = abs(fr['steps'] - target)
        if d <= tol and (best_d is None or d <= best_d):
            best, best_d = fr, d
    return best


def median_sps(frames, tail=50):
    vals = [fr['sps'] for fr in frames if fr.get('sps', 0) > 0]
    if not vals:
        return 0.0
    return statistics.median(vals[-tail:])


def fmt_steps(s):
    if s >= 1e9:
        return f'{s / 1e9:.1f}B'
    if s >= 1e6:
        return f'{s / 1e6:.0f}M'
    return f'{s:.0f}'


def fmt_val(fr, key):
    if fr is None or key not in fr:
        return '--'
    return f'{fr[key]:.3f}'


def fmt_dur(seconds):
    if seconds < 0 or math.isinf(seconds) or math.isnan(seconds):
        return 'n/a'
    h = seconds / 3600.0
    if h < 1:
        return f'{seconds / 60:.0f}m'
    if h < 48:
        return f'{h:.1f}h'
    return f'{h / 24:.1f}d'


def linfit(xs, ys):
    """Least-squares slope/intercept; returns (m, b) or None."""
    n = len(xs)
    if n < 2:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx == 0:
        return None
    m = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / sxx
    return m, my - m * mx


def project_to_target(frames, target, sps):
    """(description string) for wall-clock to reach target tds."""
    pts = [(fr['steps'], fr['tds']) for fr in frames if 'tds' in fr]
    if len(pts) < 5:
        return 'insufficient tds samples (<5)'
    cur_tds = statistics.mean(v for _, v in pts[-3:])
    cur_steps = pts[-1][0]
    if cur_tds >= target:
        return f'already at target (tds {cur_tds:.3f} >= {target:.2f})'
    # Fit the most recent half of the series (>=5 points) for local trend.
    tail = pts[max(len(pts) // 2, len(pts) - 200):]
    if len(tail) < 5:
        tail = pts[-5:]
    fit = linfit([p[0] for p in tail], [p[1] for p in tail])
    if fit is None or fit[0] <= 1e-15:
        return (f'no upward tds trend in recent window '
                f'(now {cur_tds:.3f}, target {target:.2f}) — not projectable')
    m, b = fit
    steps_at_target = (target - b) / m
    remaining = steps_at_target - cur_steps
    if remaining <= 0:
        return f'trend says target imminent (now {cur_tds:.3f})'
    if sps <= 0:
        return f'+{fmt_steps(remaining)} steps needed, but no SPS parsed'
    return (f'+{fmt_steps(remaining)} steps -> ~{fmt_dur(remaining / sps)} '
            f'wall-clock (now {cur_tds:.3f}, slope {m * 1e9:.3f}/B, '
            f'sps {sps / 1e6:.2f}M)')


def main():
    ap = argparse.ArgumentParser(
        description='Native-vs-torch parity verdict from two training logs.')
    ap.add_argument('log_a', help='log A (native arm), local path')

exec
/bin/zsh -lc "sed -n '1,220p' tools/game_stats.py" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
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

exec
/bin/zsh -lc "rg --files tools | sort | sed -n '1,120p'" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 117ms:
tools/bank_pickup_probe.c
tools/bb_lockstep.c
tools/blockev_mc.c
tools/build_league.py
tools/codegen.py
tools/coverage_report.c
tools/cpu_cap.sh
tools/dist_dump.c
tools/eval_game_stats.sh
tools/fetch_docs.sh
tools/fleet.sh
tools/game_stats.py
tools/gen_goldens.c
tools/gpu_box_setup.sh
tools/human_possession.py
tools/install_puffer_env.sh
tools/long_scrape.sh
tools/mac_practice_build.sh
tools/parity_report.py
tools/per_team_baseline.py
tools/rig_babysitter.sh
tools/run_bcreg.sh
tools/run_league.sh
tools/run_native_asym.sh
tools/run_synthesis_c.sh
tools/setup_arm.sh
tools/spectate.sh
tools/stage_spectator_art.py
tools/train_profile.sh
tools/vendor_sync.sh

codex
The existing tools are pleasantly direct: strict bash headers, absolute path anchoring before `cd`, and argparse/plain stdlib Python. I’ve got enough style context; next I’m writing the new scripts with resume behavior and the BT fit/reporting in one pass.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/anchored_ladder.sh
/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py
diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..f5d278f6c12eb9da479ccb5cb10773353e0f6aac
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null || true
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..f8f4159c2be8d5b633376a88c6454fc985e23568
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,254 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, raw):
+    entry = raw.get(frozenset((stronger, weaker)))
+    if not entry:
+        return None
+    if entry["a"] == stronger:
+        return entry["w_a"] / entry["n"], entry["n"]
+    return entry["w_b"] / entry["n"], entry["n"]
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, raw)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..f5d278f6c12eb9da479ccb5cb10773353e0f6aac
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null || true
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..f8f4159c2be8d5b633376a88c6454fc985e23568
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,254 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, raw):
+    entry = raw.get(frozenset((stronger, weaker)))
+    if not entry:
+        return None
+    if entry["a"] == stronger:
+        return entry["w_a"] / entry["n"], entry["n"]
+    return entry["w_b"] / entry["n"], entry["n"]
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, raw)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

codex
The files are in place. I’m doing a quick tightening pass now: adding an explicit raw-pair table so all-draw or skipped rows are still visible, and making adjacent empirical rates use the aggregated decisive counts rather than whichever CSV row happened to come last.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py
diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..f5d278f6c12eb9da479ccb5cb10773353e0f6aac
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null || true
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..f5d278f6c12eb9da479ccb5cb10773353e0f6aac
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null || true
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

codex
Now I’m running the requested checks only: shell syntax, Python help, and a tiny synthetic CSV fit. I’ll keep the synthetic file in `/tmp` so the repo only gets the two requested tools.
exec
/bin/zsh -lc 'chmod +x tools/anchored_ladder.sh tools/bt_fit.py && bash -n tools/anchored_ladder.sh' in /Users/alexanderhuth/Code/bloodbowl-rl
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

diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..f5d278f6c12eb9da479ccb5cb10773353e0f6aac
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null || true
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

codex
`bash -n` is clean and the argparse help comes up normally. I’m running the synthetic ladder now; this exercises the draw-splitting conversion and the sorted/adjacent reporting without touching the real GPU workflow.
exec
/bin/zsh -lc "tmp=/tmp/bt_fit_smoke.csv
printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\\nA,B,0.650,0.350,0.200,100\\nB,C,0.600,0.400,0.100,100\\nA,C,0.700,0.300,0.300,100\\n' > \""'$tmp"
python3 tools/bt_fit.py "$tmp" --anchor A' in /Users/alexanderhuth/Code/bloodbowl-rl
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

diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..f5d278f6c12eb9da479ccb5cb10773353e0f6aac
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null || true
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

codex
One small rig-env detail caught my eye: I’m aligning the source step exactly with the rig-script pattern from the brief so a missing env file fails visibly on the rig instead of being quietly ignored. Then I’ll re-run the shell syntax check.
apply patch
patch: completed
/Users/alexanderhuth/Code/bloodbowl-rl/tools/anchored_ladder.sh
diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..22af03686fb4047c96e7ab9b1ac769832f3ab4c3
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..22af03686fb4047c96e7ab9b1ac769832f3ab4c3
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

codex
I’ve made that alignment. Running the quick checks once more after the patch so the final report reflects the actual files.
exec
/bin/zsh -lc 'bash -n tools/anchored_ladder.sh' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
exec
/bin/zsh -lc "tmp=/tmp/bt_fit_smoke.csv
printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\\nA,B,0.650,0.350,0.200,100\\nB,C,0.600,0.400,0.100,100\\nA,C,0.700,0.300,0.300,100\\n' > \""'$tmp"
python3 tools/bt_fit.py "$tmp" --anchor A' in /Users/alexanderhuth/Code/bloodbowl-rl
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

diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..22af03686fb4047c96e7ab9b1ac769832f3ab4c3
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

codex
The verification is clean. I’m doing one last file/status glance so I can give you an accurate edit map and call out any deviation honestly.
exec
/bin/zsh -lc "sed -n '1,260p' tools/anchored_ladder.sh" in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
#!/usr/bin/env bash
# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
#
# Usage:
#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
#
# Environment:
#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
#   GAMES            games per pairing, default 2048
#   OUT              output CSV, default /tmp/anchored_ladder.csv
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
RESUME=0

while [ $# -gt 0 ]; do
  case "$1" in
    --resume)
      RESUME=1
      shift
      ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      CHECKPOINT_DIR="$1"
      shift
      ;;
  esac
done

case "$CHECKPOINT_DIR" in
  /*) ;;
  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
esac

GAMES="${GAMES:-2048}"
OUT="${OUT:-/tmp/anchored_ladder.csv}"
case "$OUT" in
  /*) ;;
  *) OUT="$PWD/$OUT" ;;
esac

names=(
  bc_v4
  kickoff8
  v5contested
  gen1
  gen2
  gen3
  league1
)
files=(
  bc_v4_cuda.bin
  v4k8_cap.bin
  v5_contested_cap.bin
  v4_contested_cap.bin
  v4_contested2_cap.bin
  v4_contested3_cap.bin
  league_cap.bin
)

if [ -n "${EXTRA_ANCHORS:-}" ]; then
  for pair in $EXTRA_ANCHORS; do
    case "$pair" in
      *=*)
        names+=("${pair%%=*}")
        files+=("${pair#*=}")
        ;;
      *)
        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
        ;;
    esac
  done
fi

present_names=()
present_paths=()
for i in "${!names[@]}"; do
  path="$CHECKPOINT_DIR/${files[$i]}"
  if [ -f "$path" ]; then
    present_names+=("${names[$i]}")
    present_paths+=("$path")
  else
    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
  fi
done

if [ "${#present_names[@]}" -lt 2 ]; then
  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
  exit 1
fi

total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
mkdir -p "$(dirname "$OUT")"
if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
fi

already_done() {
  local a="$1"
  local b="$2"
  [ "$RESUME" -eq 1 ] || return 1
  [ -f "$OUT" ] || return 1
  awk -F, -v a="$a" -v b="$b" '
    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
    END { exit found ? 0 : 1 }
  ' "$OUT"
}

cd "$HOME/bloodbowl-rl"
. rig-env.sh 2>/dev/null
export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
cd vendor/PufferLib

run_count=0
pair_index=0
for i in "${!present_names[@]}"; do
  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
    pair_index=$((pair_index + 1))
    name_a="${present_names[$i]}"
    name_b="${present_names[$j]}"
    path_a="${present_paths[$i]}"
    path_b="${present_paths[$j]}"

    if already_done "$name_a" "$name_b"; then
      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
      continue
    fi

    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
    if ! puffer match bloodbowl \
      --load-model-path "$path_a" \
      --load-enemy-model-path "$path_b" \
      --num-games "$GAMES" \
      --env.macro-moves 0 \
      > "$log" 2>&1; then
      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
      cat "$log" >&2
      rm -f "$log"
      exit 1
    fi

    final_line="$(
      tr '\r' '\n' < "$log" |
        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
    )"
    rm -f "$log"
    if [ -z "$final_line" ]; then
      echo "could not parse final games= line for $name_a vs $name_b" >&2
      exit 1
    fi

    parsed="$(
      printf '%s\n' "$final_line" |
        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
    )"
    if [ "$parsed" = "$final_line" ]; then
      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
      exit 1
    fi

    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
    run_count=$((run_count + 1))
    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
  done
done

echo "csv: $OUT"
echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"

exec
/bin/zsh -lc 'git status --short' in /Users/alexanderhuth/Code/bloodbowl-rl
 succeeded in 0ms:
?? .codex-impl/
?? tools/anchored_ladder.sh
?? tools/bt_fit.py
?? training/bc_v1.bin
?? training/bc_v15.bin
?? training/bc_v2.bin
?? training/bc_v2_cuda.bin
?? training/bc_v3b.bin

exec
/bin/zsh -lc "sed -n '1,320p' tools/bt_fit.py" in /Users/alexanderhuth/Code/bloodbowl-rl
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

diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..22af03686fb4047c96e7ab9b1ac769832f3ab4c3
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

codex
Implemented the anchored ladder tooling as new standalone files only:

- [tools/anchored_ladder.sh](/Users/alexanderhuth/Code/bloodbowl-rl/tools/anchored_ladder.sh): all unordered present-anchor pairings, `EXTRA_ANCHORS`, missing-file warnings, fresh-by-default CSV, `--resume` skip logic, rig env/Puffer venv setup, carriage-return-safe final-line parsing, and progress/summary output.
- [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py): CSV reader, draw-stripped decisive conversion, Zermelo/MM Bradley-Terry fit, anchored Elo display, raw pair table, sorted strength table, adjacent fitted-vs-empirical sanity checks, zero-information/disconnected handling, and pure-Python fallback if `numpy` is unavailable.

I did not run the ladder, commit, push, or checkout anything. I did set both new scripts executable. `git status` also shows unrelated pre-existing untracked files (`.codex-impl/` and several `training/*.bin`) that I left untouched.

**Verification**

`bash -n tools/anchored_ladder.sh`

Output: silent, exit 0.

`python3 tools/bt_fit.py --help`

Output: argparse help printed successfully.

Synthetic smoke test invocation:

```bash
tmp=/tmp/bt_fit_smoke.csv
printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\nA,B,0.650,0.350,0.200,100\nB,C,0.600,0.400,0.100,100\nA,C,0.700,0.300,0.300,100\n' > "$tmp"
python3 tools/bt_fit.py "$tmp" --anchor A
```

Synthetic smoke test output:

```text
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
```

No intentional deviations from the brief. The one additive choice is that `bt_fit.py` prints a raw pair table before the fit, so all-draw or skipped pairings remain visible as requested.
diff --git a/tools/anchored_ladder.sh b/tools/anchored_ladder.sh
new file mode 100644
index 0000000000000000000000000000000000000000..22af03686fb4047c96e7ab9b1ac769832f3ab4c3
--- /dev/null
+++ b/tools/anchored_ladder.sh
@@ -0,0 +1,174 @@
+#!/usr/bin/env bash
+# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
+#
+# Usage:
+#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
+#
+# Environment:
+#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
+#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
+#   GAMES            games per pairing, default 2048
+#   OUT              output CSV, default /tmp/anchored_ladder.csv
+set -euo pipefail
+
+ROOT="$(cd "$(dirname "$0")/.." && pwd)"
+CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
+RESUME=0
+
+while [ $# -gt 0 ]; do
+  case "$1" in
+    --resume)
+      RESUME=1
+      shift
+      ;;
+    -h|--help)
+      sed -n '2,14p' "$0"
+      exit 0
+      ;;
+    *)
+      CHECKPOINT_DIR="$1"
+      shift
+      ;;
+  esac
+done
+
+case "$CHECKPOINT_DIR" in
+  /*) ;;
+  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
+esac
+
+GAMES="${GAMES:-2048}"
+OUT="${OUT:-/tmp/anchored_ladder.csv}"
+case "$OUT" in
+  /*) ;;
+  *) OUT="$PWD/$OUT" ;;
+esac
+
+names=(
+  bc_v4
+  kickoff8
+  v5contested
+  gen1
+  gen2
+  gen3
+  league1
+)
+files=(
+  bc_v4_cuda.bin
+  v4k8_cap.bin
+  v5_contested_cap.bin
+  v4_contested_cap.bin
+  v4_contested2_cap.bin
+  v4_contested3_cap.bin
+  league_cap.bin
+)
+
+if [ -n "${EXTRA_ANCHORS:-}" ]; then
+  for pair in $EXTRA_ANCHORS; do
+    case "$pair" in
+      *=*)
+        names+=("${pair%%=*}")
+        files+=("${pair#*=}")
+        ;;
+      *)
+        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
+        ;;
+    esac
+  done
+fi
+
+present_names=()
+present_paths=()
+for i in "${!names[@]}"; do
+  path="$CHECKPOINT_DIR/${files[$i]}"
+  if [ -f "$path" ]; then
+    present_names+=("${names[$i]}")
+    present_paths+=("$path")
+  else
+    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
+  fi
+done
+
+if [ "${#present_names[@]}" -lt 2 ]; then
+  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
+  exit 1
+fi
+
+total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
+mkdir -p "$(dirname "$OUT")"
+if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
+  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
+fi
+
+already_done() {
+  local a="$1"
+  local b="$2"
+  [ "$RESUME" -eq 1 ] || return 1
+  [ -f "$OUT" ] || return 1
+  awk -F, -v a="$a" -v b="$b" '
+    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
+    END { exit found ? 0 : 1 }
+  ' "$OUT"
+}
+
+cd "$HOME/bloodbowl-rl"
+. rig-env.sh 2>/dev/null
+export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
+cd vendor/PufferLib
+
+run_count=0
+pair_index=0
+for i in "${!present_names[@]}"; do
+  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
+    pair_index=$((pair_index + 1))
+    name_a="${present_names[$i]}"
+    name_b="${present_names[$j]}"
+    path_a="${present_paths[$i]}"
+    path_b="${present_paths[$j]}"
+
+    if already_done "$name_a" "$name_b"; then
+      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
+      continue
+    fi
+
+    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
+    if ! puffer match bloodbowl \
+      --load-model-path "$path_a" \
+      --load-enemy-model-path "$path_b" \
+      --num-games "$GAMES" \
+      --env.macro-moves 0 \
+      > "$log" 2>&1; then
+      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
+      cat "$log" >&2
+      rm -f "$log"
+      exit 1
+    fi
+
+    final_line="$(
+      tr '\r' '\n' < "$log" |
+        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
+    )"
+    rm -f "$log"
+    if [ -z "$final_line" ]; then
+      echo "could not parse final games= line for $name_a vs $name_b" >&2
+      exit 1
+    fi
+
+    parsed="$(
+      printf '%s\n' "$final_line" |
+        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
+    )"
+    if [ "$parsed" = "$final_line" ]; then
+      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
+      exit 1
+    fi
+
+    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
+    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
+    run_count=$((run_count + 1))
+    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
+  done
+done
+
+echo "csv: $OUT"
+echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
diff --git a/tools/bt_fit.py b/tools/bt_fit.py
new file mode 100644
index 0000000000000000000000000000000000000000..c763d37a722b5f2fa5a58b1bc15f19b85456289d
--- /dev/null
+++ b/tools/bt_fit.py
@@ -0,0 +1,280 @@
+#!/usr/bin/env python3
+"""Fit an anchored Bradley-Terry/Elo ladder from anchored_ladder.csv.
+
+100%-draw pairings carry no Bradley-Terry information, so they remain visible
+in the raw read but are skipped for fitting.
+"""
+import argparse
+import csv
+import math
+import sys
+from collections import defaultdict, deque
+
+try:
+    import numpy as np  # noqa: F401
+except Exception:
+    np = None
+
+
+EPS = 1e-12
+
+
+def warn(msg):
+    print(f"warning: {msg}", file=sys.stderr)
+
+
+def parse_rows(path):
+    rows = []
+    with open(path, newline="") as f:
+        reader = csv.DictReader(f)
+        required = {"nameA", "nameB", "A_rate", "B_rate", "draw_rate", "total_games"}
+        missing = required - set(reader.fieldnames or [])
+        if missing:
+            raise SystemExit(f"missing CSV columns: {', '.join(sorted(missing))}")
+        for lineno, row in enumerate(reader, start=2):
+            try:
+                a = row["nameA"].strip()
+                b = row["nameB"].strip()
+                a_rate = float(row["A_rate"])
+                b_rate = float(row["B_rate"])
+                draw = float(row["draw_rate"])
+                total = int(round(float(row["total_games"])))
+            except (TypeError, ValueError) as e:
+                raise SystemExit(f"{path}:{lineno}: bad row: {e}")
+            if not a or not b:
+                warn(f"{path}:{lineno}: skipping row with empty name")
+                continue
+            rows.append({
+                "a": a,
+                "b": b,
+                "a_rate": a_rate,
+                "b_rate": b_rate,
+                "draw": draw,
+                "total": total,
+                "lineno": lineno,
+            })
+    return rows
+
+
+def decisive_counts(rows):
+    names = []
+    seen = set()
+    wins = defaultdict(float)
+    games = defaultdict(float)
+    raw = {}
+    skipped = []
+
+    for row in rows:
+        a, b = row["a"], row["b"]
+        for name in (a, b):
+            if name not in seen:
+                seen.add(name)
+                names.append(name)
+
+        denom = 1.0 - row["draw"]
+        if denom <= EPS:
+            skipped.append((a, b, "all draws"))
+            continue
+        p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+        p_a = max(0.0, min(1.0, p_a))
+        n_decisive = int(round(row["total"] * denom))
+        if n_decisive <= 0:
+            skipped.append((a, b, "zero decisive games after rounding"))
+            continue
+        w_a = int(round(n_decisive * p_a))
+        w_a = max(0, min(n_decisive, w_a))
+        w_b = n_decisive - w_a
+
+        wins[(a, b)] += w_a
+        wins[(b, a)] += w_b
+        games[frozenset((a, b))] += n_decisive
+        raw[frozenset((a, b))] = {
+            "a": a,
+            "b": b,
+            "w_a": w_a,
+            "w_b": w_b,
+            "n": n_decisive,
+            "p_a": w_a / n_decisive,
+        }
+
+    return names, wins, games, raw, skipped
+
+
+def row_decisive_summary(row):
+    denom = 1.0 - row["draw"]
+    if denom <= EPS:
+        return None
+    p_a = (row["a_rate"] - 0.5 * row["draw"]) / denom
+    p_a = max(0.0, min(1.0, p_a))
+    n_decisive = int(round(row["total"] * denom))
+    if n_decisive <= 0:
+        return None
+    w_a = int(round(n_decisive * p_a))
+    w_a = max(0, min(n_decisive, w_a))
+    return n_decisive, w_a, n_decisive - w_a, p_a
+
+
+def connected_components(fit_names, games):
+    graph = {name: set() for name in fit_names}
+    for pair, n in games.items():
+        if n <= 0 or len(pair) != 2:
+            continue
+        a, b = tuple(pair)
+        if a in graph and b in graph:
+            graph[a].add(b)
+            graph[b].add(a)
+
+    comps = []
+    unseen = set(fit_names)
+    while unseen:
+        start = unseen.pop()
+        comp = []
+        q = deque([start])
+        while q:
+            cur = q.popleft()
+            comp.append(cur)
+            for nxt in graph[cur]:
+                if nxt in unseen:
+                    unseen.remove(nxt)
+                    q.append(nxt)
+        comps.append(comp)
+    return comps
+
+
+def fit_bt(fit_names, wins, games, max_iter=200, tol=1e-9):
+    pi = {name: 1.0 for name in fit_names}
+    total_wins = {
+        name: sum(wins.get((name, other), 0.0) for other in fit_names if other != name)
+        for name in fit_names
+    }
+
+    for _ in range(max_iter):
+        new = {}
+        max_rel = 0.0
+        for name in fit_names:
+            denom = 0.0
+            for other in fit_names:
+                if other == name:
+                    continue
+                n_ij = games.get(frozenset((name, other)), 0.0)
+                if n_ij:
+                    denom += n_ij / (pi[name] + pi[other])
+            if denom <= 0:
+                new[name] = pi[name]
+            elif total_wins[name] <= 0:
+                new[name] = EPS
+            else:
+                new[name] = max(EPS, total_wins[name] / denom)
+            max_rel = max(max_rel, abs(new[name] - pi[name]) / max(abs(pi[name]), EPS))
+        pi = new
+        mean_pi = sum(pi.values()) / len(pi)
+        if mean_pi > 0:
+            pi = {name: val / mean_pi for name, val in pi.items()}
+        if max_rel < tol:
+            break
+    return pi
+
+
+def empirical_between(stronger, weaker, wins, games):
+    n = games.get(frozenset((stronger, weaker)), 0.0)
+    if not n:
+        return None
+    return wins.get((stronger, weaker), 0.0) / n, int(round(n))
+
+
+def main():
+    ap = argparse.ArgumentParser(
+        description="Fit a Bradley-Terry/Elo ladder from anchored_ladder.csv.")
+    ap.add_argument("csv_path", help="CSV from tools/anchored_ladder.sh")
+    ap.add_argument("--anchor", help="rating anchor pinned to Elo 0")
+    ap.add_argument("--scale", type=float, default=400.0,
+                    help="Elo display scale, default 400")
+    args = ap.parse_args()
+
+    if np is None:
+        warn("numpy unavailable; using pure Python math fallback")
+
+    rows = parse_rows(args.csv_path)
+    if not rows:
+        raise SystemExit("no CSV rows found")
+
+    names, wins, games, raw, skipped = decisive_counts(rows)
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
+        raise SystemExit("need at least two connected anchors with decisive games")
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
+    anchor = args.anchor
+    if anchor is None:
+        anchor = "bc_v4" if "bc_v4" in fit_names else rows[0]["a"]
+    if anchor not in fit_names:
+        raise SystemExit(f"anchor {anchor!r} is not in the fitted component")
+
+    pi = fit_bt(fit_names, wins, games)
+    raw_elo = {name: args.scale * math.log10(pi[name]) for name in fit_names}
+    anchor_elo = raw_elo[anchor]
+    elo = {name: raw_elo[name] - anchor_elo for name in fit_names}
+    ordered = sorted(fit_names, key=lambda name: elo[name], reverse=True)
+
+    print("raw pair table")
+    print(f"{'pair':<35}{'A_rate':>9}{'B_rate':>9}{'draw':>9}{'decisive':>11}{'A_dec_p':>10}")
+    print("-" * 83)
+    for row in rows:
+        summary = row_decisive_summary(row)
+        if summary is None:
+            decisive_s, p_s = "skip", "--"
+        else:
+            decisive_s, p_s = str(summary[0]), f"{summary[3]:.3f}"
+        print(f"{row['a'] + ' vs ' + row['b']:<35}"
+              f"{row['a_rate']:>9.3f}{row['b_rate']:>9.3f}{row['draw']:>9.3f}"
+              f"{decisive_s:>11}{p_s:>10}")
+
+    print()
+    print(f"anchor: {anchor} = 0.0 Elo")
+    print(f"scale: {args.scale:g}")
+    print()
+    print(f"{'name':<16}{'elo':>10}{'raw_strength':>16}{'decisive_games':>18}")
+    print("-" * 60)
+    for name in ordered:
+        print(f"{name:<16}{elo[name]:>10.1f}{pi[name]:>16.6g}{total_decisive[name]:>18.0f}")
+
+    print()
+    print("adjacent fitted-vs-empirical decisive win rates")
+    print(f"{'pair':<35}{'fit_p':>10}{'empirical_p':>14}{'n':>8}")
+    print("-" * 67)
+    for i in range(len(ordered) - 1):
+        hi, lo = ordered[i], ordered[i + 1]
+        fit_p = pi[hi] / (pi[hi] + pi[lo])
+        emp = empirical_between(hi, lo, wins, games)
+        if emp is None:
+            emp_s, n_s = "--", "--"
+        else:
+            emp_s, n_s = f"{emp[0]:.3f}", str(emp[1])
+        print(f"{hi + ' > ' + lo:<35}{fit_p:>10.3f}{emp_s:>14}{n_s:>8}")
+
+    if excluded:
+        print()
+        print("excluded zero-information anchors: " + ", ".join(excluded))
+
+
+if __name__ == "__main__":
+    main()

tokens used
71,865
Implemented the anchored ladder tooling as new standalone files only:

- [tools/anchored_ladder.sh](/Users/alexanderhuth/Code/bloodbowl-rl/tools/anchored_ladder.sh): all unordered present-anchor pairings, `EXTRA_ANCHORS`, missing-file warnings, fresh-by-default CSV, `--resume` skip logic, rig env/Puffer venv setup, carriage-return-safe final-line parsing, and progress/summary output.
- [tools/bt_fit.py](/Users/alexanderhuth/Code/bloodbowl-rl/tools/bt_fit.py): CSV reader, draw-stripped decisive conversion, Zermelo/MM Bradley-Terry fit, anchored Elo display, raw pair table, sorted strength table, adjacent fitted-vs-empirical sanity checks, zero-information/disconnected handling, and pure-Python fallback if `numpy` is unavailable.

I did not run the ladder, commit, push, or checkout anything. I did set both new scripts executable. `git status` also shows unrelated pre-existing untracked files (`.codex-impl/` and several `training/*.bin`) that I left untouched.

**Verification**

`bash -n tools/anchored_ladder.sh`

Output: silent, exit 0.

`python3 tools/bt_fit.py --help`

Output: argparse help printed successfully.

Synthetic smoke test invocation:

```bash
tmp=/tmp/bt_fit_smoke.csv
printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\nA,B,0.650,0.350,0.200,100\nB,C,0.600,0.400,0.100,100\nA,C,0.700,0.300,0.300,100\n' > "$tmp"
python3 tools/bt_fit.py "$tmp" --anchor A
```

Synthetic smoke test output:

```text
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
```

No intentional deviations from the brief. The one additive choice is that `bt_fit.py` prints a raw pair table before the fit, so all-draw or skipped pairings remain visible as requested.
