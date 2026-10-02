#!/usr/bin/env bash
# Append one GPU telemetry row per interval to a CSV. Log only: it never
# signals anything (review LP7: the card's fan target is 81 C, so a thermal
# abort in the 82-86 C band kills healthy rungs).
#
#   bash tools/chain_gpu_sampler.sh OUT_CSV INTERVAL_SECONDS OWNER_PID
#
# Started by tools/chain_stage.sh with `7>&-` so it never holds the GPU lock,
# and as its own file so its command line does not match the supervisor's
# `[c]hain_stage.sh` liveness pattern. It exits when OWNER_PID is gone, so a
# stage that died without running its EXIT trap leaves no sampler behind for
# longer than one interval.
set -uo pipefail

if [ "$#" -ne 3 ]; then
  echo "usage: chain_gpu_sampler.sh OUT_CSV INTERVAL_SECONDS OWNER_PID" >&2
  exit 2
fi
OUT_CSV="$1"
INTERVAL="$2"
OWNER_PID="$3"
case "$INTERVAL:$OWNER_PID" in
  *[!0-9:]*|:*|*:) echo "INTERVAL_SECONDS and OWNER_PID must be positive integers" >&2; exit 2 ;;
esac
[ "$INTERVAL" -gt 0 ] || { echo "INTERVAL_SECONDS must be positive" >&2; exit 2; }

SLEEP_PID=0
stop() {
  if [ "$SLEEP_PID" -gt 0 ]; then kill "$SLEEP_PID" 2>/dev/null; fi
  exit 0
}
trap stop TERM INT

# A wedged driver must not wedge the sampler.
QUERY=(nvidia-smi -i 0 --query-gpu=temperature.gpu,utilization.gpu,power.draw
       --format=csv,noheader,nounits)
if command -v timeout >/dev/null 2>&1; then
  QUERY=(timeout 20 "${QUERY[@]}")
fi

[ -s "$OUT_CSV" ] || echo "utc,temperature_c,utilization_pct,power_w" >> "$OUT_CSV"
while kill -0 "$OWNER_PID" 2>/dev/null; do
  row="$("${QUERY[@]}" 2>/dev/null | head -1)"
  if [ -n "$row" ]; then
    printf '%s,%s\n' "$(date -u +%FT%TZ)" "${row// /}" >> "$OUT_CSV"
  else
    printf '%s,error,,\n' "$(date -u +%FT%TZ)" >> "$OUT_CSV"
  fi
  sleep "$INTERVAL" &
  SLEEP_PID=$!
  wait "$SLEEP_PID"
  SLEEP_PID=0
done
