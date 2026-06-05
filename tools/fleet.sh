#!/usr/bin/env bash
# fleet.sh — thin fleet orchestration over the vastai CLI + ssh for the
# experiment-wave workflow (docs/fleet-playbook.md). State lives in Vast
# instance LABELS (bb-<name>), never in a local manifest that can drift.
#
#   fleet.sh search                       best cores-heavy 4090 offers
#   fleet.sh provision <name> <offer_id>  create + label an instance
#   fleet.sh ls                           fleet inventory (id, label, ssh, $)
#   fleet.sh ssh <name> [cmd...]          ssh by label
#   fleet.sh setup <name>                 rsync repo + gpu_box_setup.sh
#   fleet.sh launch <name> <tag> [args]   nohup puffer train + PROFILE marker
#   fleet.sh status                       per-box: liveness, Steps/SPS tail
#   fleet.sh collect <name>               pull checkpoints+logs to runs/<name>/
#   fleet.sh destroy <name>               destroy by label (asks)
#
# Conventions: ssh key ~/.ssh/id_ed25519; repo lands at /root/bloodbowl-rl;
# run log /tmp/<tag>.log. vastai CLI must be >= 1.0 (brew 0.4 makes zombies).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEY="$HOME/.ssh/id_ed25519"

# cpu_cores_effective is the CONTAINER allocation — the only core count that
# matters for env threading (a 224-core host can hand you a 28-core slice).
MIN_CORES="${MIN_CORES:-32}"
GPU="${GPU:-RTX_4090}"

vj() { vastai show instances --raw 2>/dev/null; }

resolve() { # name -> "id host port"
    vj | python3 -c "
import json,sys
name='bb-$1'
for i in json.load(sys.stdin):
    if i.get('label')==name and i.get('actual_status')=='running':
        print(i['id'], i.get('ssh_host',''), i.get('ssh_port',''))
        break
"
}

case "${1:?usage: fleet.sh search|provision|ls|ssh|setup|launch|status|collect|destroy}" in

search)
    vastai search offers "gpu_name=$GPU cpu_cores_effective>=$MIN_CORES \
        reliability>0.98 rentable=true" -o 'dph_total' 2>/dev/null | head -12
    echo "(provision with: fleet.sh provision <name> <offer ID>)"
    ;;

provision)
    name="${2:?name}" offer="${3:?offer_id}"
    vastai create instance "$offer" \
        --image pytorch/pytorch:2.5.1-cuda12.4-cudnn9-devel \
        --disk 80 --ssh --direct
    echo "label it once 'running': vastai label instance <new_id> bb-$name"
    echo "then: fleet.sh setup $name"
    ;;

ls)
    vj | python3 -c "
import json,sys
for i in json.load(sys.stdin):
    print(f\"{i.get('label') or '(unlabeled)':22} {i['id']:10} \"
          f\"{i.get('gpu_name','?'):10} cores={i.get('cpu_cores_effective','?'):<5} \"
          f\"{i.get('actual_status','?'):8} \${i.get('dph_total',0):.3f}/hr \"
          f\"{i.get('ssh_host','')}:{i.get('ssh_port','')}\")
"
    ;;

ssh)
    name="${2:?name}"; shift 2
    read -r _id host port <<< "$(resolve "$name")"
    [ -n "${host:-}" ] || { echo "no running instance labeled bb-$name" >&2; exit 1; }
    exec ssh -i "$KEY" -p "$port" -o StrictHostKeyChecking=no "root@$host" "$@"
    ;;

setup)
    name="${2:?name}"
    read -r _id host port <<< "$(resolve "$name")"
    [ -n "${host:-}" ] || { echo "no running instance labeled bb-$name" >&2; exit 1; }
    rsync -az -e "ssh -i $KEY -p $port -o StrictHostKeyChecking=no" \
        --exclude vendor/PufferLib/checkpoints --exclude validation/replay_cache \
        --exclude .git "$ROOT/" "root@$host:/root/bloodbowl-rl/"
    ssh -i "$KEY" -p "$port" -o StrictHostKeyChecking=no "root@$host" \
        "cd /root/bloodbowl-rl && bash tools/gpu_box_setup.sh"
    ;;

launch)
    name="${2:?name}" tag="${3:?tag}"; shift 3
    read -r _id host port <<< "$(resolve "$name")"
    [ -n "${host:-}" ] || { echo "no running instance labeled bb-$name" >&2; exit 1; }
    ssh -i "$KEY" -p "$port" -o StrictHostKeyChecking=no "root@$host" \
        "cd /root/bloodbowl-rl/vendor/PufferLib && \
         nohup puffer train bloodbowl --tag '$tag' $* > /tmp/$tag.log 2>&1 < /dev/null & \
         echo LAUNCHED-\$!; sleep 30; \
         if ! pgrep -f 'puffer [t]rain' > /dev/null; then \
             echo 'TRAINER DIED:'; tail -10 /tmp/$tag.log; exit 1; fi; \
         d=\$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1); \
         [ -n \"\$d\" ] && echo '$tag' > \"\${d}PROFILE\"; \
         echo LIVE"
    ;;

status)
    vj | python3 -c "
import json,sys
for i in json.load(sys.stdin):
    l=i.get('label')
    if l and l.startswith('bb-') and i.get('actual_status')=='running':
        print(f\"{l} {i.get('ssh_host')}:{i.get('ssh_port')}\")
" | while read -r label addr; do
        host="${addr%%:*}" port="${addr##*:}"
        # -n: don't let ssh eat the while-read loop's stdin.
        line=$(ssh -n -i "$KEY" -p "$port" -o StrictHostKeyChecking=no \
            -o ConnectTimeout=10 "root@$host" \
            'log=$(ls -t /tmp/*.log 2>/dev/null | head -1); \
             pgrep -f "puffer [t]rain" > /dev/null && st=RUNNING || st=idle; \
             vitals=$(sed "s/\x1b\[[0-9;]*[a-zA-Z]//g" "$log" 2>/dev/null | \
               grep -oaE "(Steps +[0-9.]+[BMK]|SPS +[0-9.]+[KM])" | tail -2 | tr "\n" " "); \
             echo "$st ${log##*/} $vitals"' 2>/dev/null || echo "UNREACHABLE")
        printf '%-22s %s\n' "$label" "$line"
    done
    ;;

collect)
    name="${2:?name}"
    read -r _id host port <<< "$(resolve "$name")"
    [ -n "${host:-}" ] || { echo "no running instance labeled bb-$name" >&2; exit 1; }
    mkdir -p "$ROOT/runs/$name"
    rsync -az -e "ssh -i $KEY -p $port -o StrictHostKeyChecking=no" \
        "root@$host:/root/bloodbowl-rl/vendor/PufferLib/checkpoints/bloodbowl/" \
        "$ROOT/runs/$name/checkpoints/"
    rsync -az -e "ssh -i $KEY -p $port -o StrictHostKeyChecking=no" \
        "root@$host:/tmp/*.log" "$ROOT/runs/$name/" 2>/dev/null || true
    echo "collected into runs/$name/"
    ;;

destroy)
    name="${2:?name}"
    read -r id _h _p <<< "$(resolve "$name")"
    [ -n "${id:-}" ] || { echo "no running instance labeled bb-$name" >&2; exit 1; }
    echo "destroying instance $id (bb-$name) — Ctrl-C within 5s to abort"
    sleep 5
    vastai destroy instance "$id"
    ;;

*) echo "unknown command: $1" >&2; exit 1 ;;
esac
