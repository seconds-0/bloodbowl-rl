#!/usr/bin/env bash
set -euo pipefail

# BBTV production launcher for the RTX 2070. The follower only consumes
# complete checkpoints from manifested reward-screen runs and never writes to
# the trainer's checkpoint tree.
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT=${BBTV_ROOT:-"$SCRIPT_ROOT"}
AUDIT_ROOT=${BBTV_AUDIT_ROOT:-"$(dirname "$ROOT")/bloodbowl-rl-audit"}
RECOVERY_ROOT=${BBTV_RECOVERY_ROOT:-"$(dirname "$ROOT")/bloodbowl-rl-recovery-20260719"}
VIEWER_ROOT=${BBTV_VIEWER_ROOT:-"$(dirname "$ROOT")/bloodbowl-rl-bbtv-cpu/vendor/PufferLib"}
SERVER_PYTHON=${BBTV_SERVER_PYTHON:-"$(dirname "$ROOT")/bloodbowl-rl-bbtv/vendor/PufferLib/.venv/bin/python"}
CHECKPOINT_ROOTS=${BBTV_CHECKPOINT_ROOTS:-"$AUDIT_ROOT/vendor/PufferLib/checkpoints/bloodbowl:$RECOVERY_ROOT/vendor/PufferLib/checkpoints/bloodbowl"}
STATE_DIR=${BBTV_STATE_DIR:-"$RECOVERY_ROOT/runs/bbtv-follow"}

IFS=: read -r -a CHECKPOINT_ROOT_ARRAY <<< "$CHECKPOINT_ROOTS"
CHECKPOINT_ARGS=()
for checkpoint_root in "${CHECKPOINT_ROOT_ARRAY[@]}"; do
  [ -n "$checkpoint_root" ] || {
    echo "BBTV_CHECKPOINT_ROOTS contains an empty path" >&2
    exit 2
  }
  CHECKPOINT_ARGS+=(--checkpoint-root "$checkpoint_root")
done

# Keep inference subordinate to the live trainer. The old static BBTV process
# ran at normal priority; nice/idle I/O makes the replacement less intrusive.
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-4}
# shellcheck source=/dev/null
source "$ROOT/rig-env.sh"

# BBTV must not appear as a compute process: the vacation overflow gate treats
# every nvidia-smi compute PID as contention. Fail before launching the follower
# if the isolated viewer is not the expected CPU/fp32 Blood Bowl build or if
# Python imported an extension from another tree.
CUDA_VISIBLE_DEVICES="" BBTV_VIEWER_ROOT="$VIEWER_ROOT" \
  PYTHONPATH="$VIEWER_ROOT" "$SERVER_PYTHON" - <<'PY'
import os
from pathlib import Path

from pufferlib import _C

root = Path(os.environ["BBTV_VIEWER_ROOT"]).resolve()
module = Path(_C.__file__).resolve()
if module.parent != root / "pufferlib":
    raise SystemExit(f"BBTV imported _C outside viewer root: {module}")
if getattr(_C, "env_name", None) != "bloodbowl":
    raise SystemExit(f"BBTV viewer env is {_C.env_name!r}, not bloodbowl")
if bool(getattr(_C, "gpu", True)):
    raise SystemExit("BBTV viewer _C is a GPU build; expected --cpu")
if int(getattr(_C, "precision_bytes", 0)) != 4:
    raise SystemExit("BBTV viewer _C is not fp32")
print(f"BBTV CPU viewer verified: {module}", flush=True)
PY

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
  "$SCRIPT_ROOT/stream_backend/follow_latest.py" \
  "${CHECKPOINT_ARGS[@]}" \
  --state-dir "$STATE_DIR" \
  --converter-python "$ROOT/vendor/PufferLib/.venv/bin/python" \
  --converter-script "$AUDIT_ROOT/training/convert_checkpoint.py" \
  --config "$AUDIT_ROOT/puffer/config/bloodbowl.ini" \
  --server-python "$SERVER_PYTHON" \
  --server-pythonpath "$VIEWER_ROOT" \
  --server-script "$ROOT/stream_backend/server.py" \
  --fallback-a "$ROOT/training/league9_torch.bin" \
  --fallback-b "$ROOT/training/league8_torch.bin" \
  --port "${BBTV_PORT:-8787}" \
  --pace "${BBTV_PACE:-0.6}" \
  --games-per-cycle "${BBTV_GAMES_PER_CYCLE:-2}" \
  --stability-seconds "${BBTV_STABILITY_SECONDS:-1}" \
  --keep-converted "${BBTV_KEEP_CONVERTED:-24}" \
  "${SAMPLE_ARGS[@]}"
