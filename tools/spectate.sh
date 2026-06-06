#!/usr/bin/env bash
# Live spectator: a window that endlessly streams matches played by the
# newest training checkpoint.
#
# Loop: rsync checkpoints from the GPU box -> `puffer eval` with
# --load-model-path latest (auto-resolves the newest .bin) -> restart after
# CYCLE_SECS so the next cycle picks up fresher weights. Close the window to
# stop (the renderer exits with code 7).
#
# Env knobs:
#   BBE_SSH_HOST / BBE_SSH_PORT  GPU box (default root@ssh3.vast.ai : 12464)
#   BBE_FPS                      decisions/sec playback speed (default 60)
#   CYCLE_SECS                   seconds before re-checking for newer
#                                checkpoints (default 180)
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUFFER="$ROOT/vendor/PufferLib"
HOST="${BBE_SSH_HOST:-root@ssh3.vast.ai}"
PORT="${BBE_SSH_PORT:-12464}"
FPS="${BBE_FPS:-60}"
CYCLE="${CYCLE_SECS:-600}"

cd "$PUFFER"
source .venv/bin/activate
export BBE_MEMORIAL="${BBE_MEMORIAL:-$ROOT/MEMORIAL.md}"

while true; do
    rsync -az -e "ssh -p $PORT -i $HOME/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o ConnectTimeout=15" \
        "$HOST:~/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/" \
        checkpoints/bloodbowl/ 2>/dev/null \
        || echo "(checkpoint sync failed — playing newest local weights)"

    newest=$(find checkpoints/bloodbowl -name '*.bin' -print0 2>/dev/null \
        | xargs -0 ls -t 2>/dev/null | head -1 || true)
    if [ -z "$newest" ]; then
        echo "no checkpoints yet — playing randomly initialized policy"
        load_args=()
        export BBE_BANNER="untrained (random init)"
        unset BBE_CKPT_STEPS
    else
        load_args=(--load-model-path latest)
        steps=$(basename "$newest" .bin | sed 's/^0*//'); steps=${steps:-0}
        export BBE_BANNER="$(basename "$(dirname "$newest")")"
        export BBE_PROFILE="$(cat "$(dirname "$newest")/PROFILE" 2>/dev/null || echo unlabeled run)"
        export BBE_CKPT_STEPS="$steps"
        export BBE_TOTAL_STEPS="${BBE_TOTAL_STEPS:-10000000000}"
        echo "spectating: $newest"
    fi

    timeout "$CYCLE" puffer eval bloodbowl --slowly \
        --selfplay.enabled 0 \
        --vec.total-agents 2 --vec.num-buffers 1 --vec.num-threads 1 \
        --train.minibatch-size 2 --env.render-fps "$FPS" \
        "${load_args[@]}"
    code=$?
    if [ "$code" -eq 7 ]; then
        echo "window closed — bye"
        exit 0
    fi
done
