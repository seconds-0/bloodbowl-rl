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

# raylib's InitWindow segfaults (NULL GL proc via rlglInit) when the display
# is asleep — overnight the cycle loop was generating a crash report every
# 10 min. Gate cycles on the panel being awake; fail-safe to "awake" if the
# ioreg class ever disappears so a probe change can't brick the viewer.
display_awake() {
    local st
    st=$(ioreg -w0 -r -c IOMobileFramebufferShim 2>/dev/null \
        | grep -o '"CurrentPowerState"=[0-9]' | head -1 | grep -o '[0-9]$')
    [ -z "$st" ] || [ "$st" != "0" ]
}

# The torch-backend viewer can only load torch state_dict checkpoints. Native
# (CUDA) league runs save FLAT fp32 blobs (`invalid load key` under torch.load);
# convert those to a sibling *.torch.bin on demand. Echoes a loadable path.
resolve_loadable() {
    local ckpt="$1"
    if "$PUFFER/.venv/bin/python" -c "import torch,sys; torch.load(sys.argv[1],map_location='cpu',weights_only=False)" "$ckpt" >/dev/null 2>&1; then
        echo "$ckpt"; return 0          # already a torch checkpoint
    fi
    local out="${ckpt%.bin}.torch.bin"  # excluded from newest-selection below
    if [ ! -f "$out" ] || [ "$ckpt" -nt "$out" ]; then
        "$PUFFER/.venv/bin/python" "$ROOT/training/convert_checkpoint.py" \
            --to-torch "$ckpt" -o "$out" >/dev/null 2>&1 || return 1
    fi
    echo "$out"
}

crashes=0
while true; do
    until display_awake; do
        sleep 120
    done
    # Fetch ONLY the newest checkpoint from each remote root (a full rsync of a
    # native run dir is GBs — league9 alone has ~190 ckpts). Check BOTH roots:
    # vendor/PufferLib/checkpoints (torch-backend runs) AND the repo-root
    # checkpoints dir (native runs write there, cwd-relative — league8/9 etc.).
    # Missing the latter is why the viewer used to play stale wrong-era weights.
    SSH="ssh -p $PORT -i $HOME/.ssh/id_ed25519 -o StrictHostKeyChecking=no -o ConnectTimeout=15"
    mkdir -p checkpoints/bloodbowl/live
    for root in "vendor/PufferLib/checkpoints/bloodbowl" "checkpoints/bloodbowl"; do
        rnew=$($SSH "$HOST" "ls -t ~/bloodbowl-rl/$root/*/0*.bin 2>/dev/null | head -1" 2>/dev/null || true)
        [ -n "$rnew" ] || continue
        # Preserve the run-dir name so the PROFILE/banner lookup still works.
        rundir=$(basename "$(dirname "$rnew")")
        mkdir -p "checkpoints/bloodbowl/live/$rundir"
        rsync -az -e "$SSH" "$HOST:$rnew" "checkpoints/bloodbowl/live/$rundir/" 2>/dev/null || true
        rsync -az -e "$SSH" "$HOST:~/bloodbowl-rl/$root/$rundir/PROFILE" "checkpoints/bloodbowl/live/$rundir/" 2>/dev/null || true
    done

    # Newest SOURCE checkpoint (exclude our own *.torch.bin conversions so we
    # always reconvert from the canonical file, never a stale conversion).
    newest=$(find checkpoints/bloodbowl -name '*.bin' ! -name '*.torch.bin' -print0 2>/dev/null \
        | xargs -0 ls -t 2>/dev/null | head -1 || true)
    if [ -z "$newest" ]; then
        echo "no checkpoints yet — playing randomly initialized policy"
        load_args=()
        export BBE_BANNER="untrained (random init)"
        unset BBE_CKPT_STEPS
    else
        # Convert native->torch if needed, then load the EXPLICIT path (not
        # `latest`, which would re-resolve to the native source and crash).
        loadable=$(resolve_loadable "$newest" || true)
        if [ -z "$loadable" ]; then
            echo "(could not load/convert $newest — skipping cycle)"
            sleep 30; continue
        fi
        load_args=(--load-model-path "$loadable")
        steps=$(basename "$newest" .bin | sed 's/^0*//'); steps=${steps:-0}
        export BBE_BANNER="$(basename "$(dirname "$newest")")"
        export BBE_PROFILE="$(cat "$(dirname "$newest")/PROFILE" 2>/dev/null || echo unlabeled run)"
        export BBE_CKPT_STEPS="$steps"
        export BBE_TOTAL_STEPS="${BBE_TOTAL_STEPS:-10000000000}"
        echo "spectating: $newest$([ "$loadable" != "$newest" ] && echo ' (native->torch converted)')"
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
    # Backoff on repeated abnormal exits (segfault=139 etc.; timeout's
    # cycle-end exit 124 is the normal case) so a persistent failure can't
    # spam macOS crash reports every cycle.
    if [ "$code" -ne 0 ] && [ "$code" -ne 124 ]; then
        crashes=$((crashes + 1))
        if [ "$crashes" -ge 3 ]; then
            echo "eval exited $code x$crashes — backing off 15 min"
            sleep 900
        fi
    else
        crashes=0
    fi
done
