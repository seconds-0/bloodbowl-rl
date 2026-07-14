#!/usr/bin/env bash
set -euo pipefail

# BBTV production launcher for the RTX 2070. The follower only consumes
# complete checkpoints from manifested reward-screen runs and never writes to
# the trainer's checkpoint tree.
ROOT=${BBTV_ROOT:-"$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"}
AUDIT_ROOT=${BBTV_AUDIT_ROOT:-"$(dirname "$ROOT")/bloodbowl-rl-audit"}
VIEWER_ROOT=${BBTV_VIEWER_ROOT:-"$(dirname "$ROOT")/bloodbowl-rl-bbtv/vendor/PufferLib"}

# Keep inference subordinate to the live trainer. The old static BBTV process
# ran at normal priority; nice/idle I/O makes the replacement less intrusive.
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
# shellcheck source=/dev/null
source "$ROOT/rig-env.sh"
export PYTHONPATH="$VIEWER_ROOT${PYTHONPATH:+:$PYTHONPATH}"

case "${BBTV_SAMPLE:-1}" in
  1) SAMPLE_ARGS=(--sample) ;;
  0) SAMPLE_ARGS=() ;;
  *)
    echo "BBTV_SAMPLE must be 0 (greedy) or 1 (sampled)" >&2
    exit 2
    ;;
esac

exec nice -n 19 ionice -c 3 \
  "$ROOT/vendor/PufferLib/.venv/bin/python" \
  "$ROOT/stream_backend/follow_latest.py" \
  --checkpoint-root "$AUDIT_ROOT/vendor/PufferLib/checkpoints/bloodbowl" \
  --state-dir "$AUDIT_ROOT/runs/bbtv-follow" \
  --converter-python "$ROOT/vendor/PufferLib/.venv/bin/python" \
  --converter-script "$AUDIT_ROOT/training/convert_checkpoint.py" \
  --config "$AUDIT_ROOT/puffer/config/bloodbowl.ini" \
  --server-python "$VIEWER_ROOT/.venv/bin/python" \
  --server-script "$ROOT/stream_backend/server.py" \
  --fallback-a "$ROOT/training/league9_torch.bin" \
  --fallback-b "$ROOT/training/league8_torch.bin" \
  --port "${BBTV_PORT:-8787}" \
  --pace "${BBTV_PACE:-0.6}" \
  --games-per-cycle "${BBTV_GAMES_PER_CYCLE:-2}" \
  --stability-seconds "${BBTV_STABILITY_SECONDS:-1}" \
  --keep-converted "${BBTV_KEEP_CONVERTED:-24}" \
  "${SAMPLE_ARGS[@]}"
