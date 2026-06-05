#!/usr/bin/env bash
# Launch the synthesis+C run (box-2, torch backend): everything the synthesis
# run carries — BC anchor, demo-state resets, B-profile event knobs — PLUS the
# Profile C exposure-EV transfer and sequencing charge (D34: cures the
# never-blocking meta; D33 mechanism).
#
# Run ON the box from ~/bloodbowl-rl:  bash tools/run_synthesis_c.sh
# Prereqs on the box:
#   - synthesis-v4 finished or killed (this script refuses to double-launch)
#   - vendor/PufferLib built with --float (torch backend requirement) and the
#     dict-capacity patch (training/puffer_dict_capacity.patch)
#   - anchor model: $ANCHOR (default = the freshest bc_v*.bin in training/)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/vendor/PufferLib"

if pgrep -f 'puffer [t]rain' > /dev/null; then
  echo "a training run is already live on this box — kill it first" >&2
  exit 1
fi

ANCHOR="${ANCHOR:-$(ls -t "$ROOT"/training/bc_v*.bin 2>/dev/null | grep -v cuda | head -1)}"
[ -f "$ANCHOR" ] || { echo "no anchor model found (set ANCHOR=...)" >&2; exit 1; }
echo "anchor: $ANCHOR"

LOG="${LOG:-/tmp/synthesis_c.log}"
nohup puffer train bloodbowl --slowly --selfplay.enabled 0 \
  --load-model-path "$ANCHOR" \
  --tag profile-synthesis-c \
  --train.total-timesteps "${STEPS:-10000000000}" \
  --train.bc-coef 1.0 \
  --env.demo-reset-pct 0.5 \
  --vec.num-threads 20 \
  --env.reward-draw -0.1 \
  --env.reward-setup-done 0.25 --env.reward-setup-autofix -0.25 \
  --env.reward-ball-gain 0.1 --env.reward-ball-loss -0.2 \
  --env.reward-injury-inflicted 0.15 --env.reward-injury-taken -0.15 \
  --env.reward-injury-value-scaled 1 \
  --env.reward-surf-taken -0.1 --env.reward-surf-inflicted 0.1 \
  --env.reward-k-kd 0.06 --env.reward-k-value 0.5 \
  --env.reward-k-ball 0.3 --env.reward-k-seq 0.02 \
  "$@" > "$LOG" 2>&1 < /dev/null &
echo "LAUNCHED-PID-$! log=$LOG"

# PROFILE marker for the spectator chip (newest run dir ~30s after launch).
(
  sleep 30
  d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
  [ -n "$d" ] && echo "profile-synthesis-c (anchor + demos + exposure-EV)" > "${d}PROFILE"
) &
