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
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
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
  > "$LOG" 2>&1

echo "done. compare with:  python3 $ROOT/tools/game_stats.py $LOG" >&2
