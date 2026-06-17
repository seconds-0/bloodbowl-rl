#!/usr/bin/env bash
# eval_vs_contact_bot.sh - measure a frozen champion's ABSOLUTE strength against
# the deterministic contact-bot opponent (AWAY/team 1), the first non-self-play
# signal. The final dashboard must expose team0/team1 TD and block splits so
# team0=champion engagement is not hidden by the bot's contact volume.
#
#   bash tools/eval_vs_contact_bot.sh <CHECKPOINT.bin> [STEPS] [LOG]
#       CHECKPOINT  torch state_dict .bin (training-side format).
#       STEPS       measurement length, default 8M.
#       LOG         output path, default /tmp/contact_bot_eval.log
set -euo pipefail
CKPT="${1:?usage: eval_vs_contact_bot.sh <checkpoint.bin> [steps] [log]}"
STEPS="${2:-8000000}"
LOG="${3:-/tmp/contact_bot_eval.log}"
for _ in 1 2 3; do [ $# -gt 0 ] && shift; done
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

case "$CKPT" in /*) ;; *) CKPT="$PWD/$CKPT" ;; esac
case "$LOG"  in /*) ;; *) LOG="$PWD/$LOG"   ;; esac
[ -f "$CKPT" ] || { echo "checkpoint not found: $CKPT" >&2; exit 1; }

if ! "$ROOT/tools/install_puffer_env.sh" --check "$ROOT/vendor/PufferLib"; then
  echo "stale PufferLib bloodbowl snapshot; reinstall before eval:" >&2
  echo "  $ROOT/tools/install_puffer_env.sh $ROOT/vendor/PufferLib" >&2
  exit 1
fi

. "$ROOT/tools/cpu_cap.sh"

cd "$ROOT/vendor/PufferLib"
echo "measuring $CKPT vs contact bot over $STEPS steps -> $LOG" >&2
puffer train bloodbowl --slowly --selfplay.enabled 0 \
  --load-model-path "$CKPT" \
  --tag contact-bot-eval \
  --train.total-timesteps "$STEPS" \
  --train.learning-rate 0.000000000001 \
  --train.bc-coef 0 \
  --env.demo-reset-pct 0 \
  --env.scripted-opponent 1 \
  --env.scripted-opponent-team 1 \
  --vec.total-agents 256 --vec.num-threads "${OMP_NUM_THREADS:-8}" \
  --train.minibatch-size 2048 \
  "$@" \
  > "$LOG" 2>&1

echo "done. contact-bot strength readout:" >&2
python3 "$ROOT/tools/contact_bot_stats.py" "$LOG" >&2
echo "generic behavior comparison:  python3 $ROOT/tools/game_stats.py $LOG" >&2
