#!/usr/bin/env bash
# Launch the synthesis+C run (box-2, torch backend): everything the synthesis
# run carries — BC anchor, demo-state resets, B-profile event knobs — PLUS the
# Profile C exposure-EV transfer and sequencing charge (D34: creates the
# contact-seeking no other reward design produced; D33 mechanism).
#
# Run ON the box from ~/bloodbowl-rl:  bash tools/run_synthesis_c.sh
# Prereqs on the box:
#   - synthesis-v4 finished or killed (this script refuses to double-launch)
#   - vendor/PufferLib built with --float (torch backend requirement) and the
#     dict-capacity patch (training/puffer_dict_capacity.patch)
#   - anchor model training/bc_v3.bin (override: ANCHOR=...; PINNED, not
#     mtime-glob-resolved — panel: bc_v1/bc_v15 are dead-lineage 832-obs
#     checkpoints that an `ls -t` glob can mis-resolve to)
#   - demo bank staged at vendor/PufferLib/resources/bloodbowl/state_bank.bbs
#     (panel: a missing bank is SILENT — the env trains procgen-only)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/vendor/PufferLib"

if pgrep -f 'puffer [t]rain' > /dev/null; then
  echo "a training run is already live on this box — kill it first" >&2
  exit 1
fi

ANCHOR="${ANCHOR:-$ROOT/training/bc_v3.bin}"
[ -f "$ANCHOR" ] || { echo "anchor model missing: $ANCHOR" >&2; exit 1; }
# obs-v3 torch state_dicts are ~13.68 MB; the dead 832-obs lineage is ~12.08.
asize=$(wc -c < "$ANCHOR")
[ "$asize" -gt 13000000 ] || {
  echo "anchor $ANCHOR is $asize B — looks like a dead-lineage (obs-832) checkpoint" >&2
  exit 1
}
echo "anchor: $ANCHOR ($asize B)"

BANK="resources/bloodbowl/state_bank.bbs"
[ -f "$BANK" ] || { echo "demo bank missing: $BANK (env would silently train procgen-only)" >&2; exit 1; }
bsize=$(wc -c < "$BANK")
# 16-byte header + N x (12 + sizeof(bb_match)) records; demand a real corpus.
[ "$bsize" -gt 1000000 ] || { echo "demo bank suspiciously small ($bsize B) — stale 401-replay bank?" >&2; exit 1; }
echo "bank: $BANK ($bsize B)"

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
PID=$!
echo "LAUNCHED-PID-$PID log=$LOG"

# PROFILE marker for the spectator chip (newest run dir ~30s after launch).
(
  sleep 30
  d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
  [ -n "$d" ] && echo "profile-synthesis-c (anchor + demos + exposure-EV)" > "${d}PROFILE"
) &

# Liveness + config echo (panel: the old script reported success even when
# the nohup'd trainer died instantly on a bad warm-start).
sleep 40
if ! kill -0 "$PID" 2>/dev/null; then
  echo "TRAINER DIED within 40s — tail of $LOG:" >&2
  tail -15 "$LOG" >&2
  exit 1
fi
grep -aE "Warm-started|demo states|bc.*pairs|BC anchor" "$LOG" | head -5 || true
echo "LIVE: pid $PID at 40s — verify 'Loaded N demo states' appeared above"
