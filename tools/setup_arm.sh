#!/usr/bin/env bash
# setup_arm.sh — bootstrap a freshly-provisioned Vast box into a torch
# experiment arm and launch it. One command per fleet arm:
#
#   tools/setup_arm.sh <label> <tag> [extra puffer args...]
#   e.g. tools/setup_arm.sh kzero profile-kzero \
#          --env.reward-k-kd 0 --env.reward-k-value 0 \
#          --env.reward-k-ball 0 --env.reward-k-seq 0
#
# Chain: wait for 'running' -> fleet setup (repo rsync + gpu_box_setup) ->
# --float rebuild (torch backend) -> pull the 1M-pair corpus + 15K bank +
# bc_v3b from bb-taiwan-anchor (box-to-box; needs ssh-agent forwarding with
# the key loaded: ssh-add ~/.ssh/id_ed25519) -> run_synthesis_c.sh with the
# given tag/args -> print the first vitals.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="$HOME/.ssh/id_ed25519"
LABEL="${1:?label (without bb- prefix)}"
TAG="${2:?run tag}"
shift 2

SRC_HOST=root@ssh2.vast.ai SRC_PORT=31946  # bb-taiwan-anchor (corpus home)

resolve() {
    vastai show instances --raw 2>/dev/null | python3 -c "
import json,sys
for i in json.load(sys.stdin):
    if i.get('label')=='bb-$LABEL' and i.get('actual_status')=='running':
        print(i.get('ssh_host',''), i.get('ssh_port',''))
        break
"
}

echo "[$LABEL] waiting for instance to run..."
for _ in $(seq 1 60); do
    read -r HOST PORT <<< "$(resolve)" || true
    [ -n "${HOST:-}" ] && break
    sleep 30
done
[ -n "${HOST:-}" ] || { echo "[$LABEL] never reached running" >&2; exit 1; }
echo "[$LABEL] up at $HOST:$PORT — setup"

bash "$ROOT/tools/fleet.sh" setup "$LABEL"

echo "[$LABEL] --float rebuild (torch backend)"
ssh -i "$KEY" -p "$PORT" -o StrictHostKeyChecking=no "root@$HOST" \
    "cd /root/bloodbowl-rl/vendor/PufferLib && rm -rf build && \
     ./build.sh bloodbowl --float > /tmp/build_float.log 2>&1 && \
     python -c 'from pufferlib import _C; assert _C.precision_bytes==4'"

echo "[$LABEL] pulling corpus + bank + anchor from bb-taiwan-anchor"
ssh -A -i "$KEY" -p "$SRC_PORT" -o StrictHostKeyChecking=no "$SRC_HOST" \
    "rsync -az --delete -e 'ssh -p $PORT -o StrictHostKeyChecking=no' \
         /root/bloodbowl-rl/validation/pairs/ root@$HOST:/root/bloodbowl-rl/validation/pairs/ && \
     rsync -az -e 'ssh -p $PORT -o StrictHostKeyChecking=no' \
         /root/bloodbowl-rl/validation/states/bank.bbs root@$HOST:/root/bloodbowl-rl/validation/states/bank.bbs && \
     rsync -az -e 'ssh -p $PORT -o StrictHostKeyChecking=no' \
         /root/bloodbowl-rl/vendor/PufferLib/resources/bloodbowl/state_bank.bbs \
         root@$HOST:/root/bloodbowl-rl/vendor/PufferLib/resources/bloodbowl/state_bank.bbs && \
     rsync -az -e 'ssh -p $PORT -o StrictHostKeyChecking=no' \
         /root/bloodbowl-rl/training/bc_v3b.bin root@$HOST:/root/bloodbowl-rl/training/"

echo "[$LABEL] launching $TAG"
ssh -i "$KEY" -p "$PORT" -o StrictHostKeyChecking=no "root@$HOST" \
    "cd /root/bloodbowl-rl && LOG=/tmp/$TAG.log bash tools/run_synthesis_c.sh --tag '$TAG' $* 2>&1 | tail -5"
echo "[$LABEL] DONE — log /tmp/$TAG.log on $HOST:$PORT"
