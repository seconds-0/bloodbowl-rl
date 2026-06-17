#!/usr/bin/env bash
# bb_idle_guard_v2 — stop genuinely-idle Vast bb-* boxes to save money, WITHOUT
# ever false-stopping active work. Runs every 10 min (launchd). Mac-side.
#
# WHY v2 (the 2026-06-17 incident): v1 decided "idle" by SSHing each box and
# running `pgrep puffer`. Vast's SSH proxy is chronically flaky, so an
# unreachable TRAINING box read as "no trainer" -> idle -> stopped. That killed
# league9 repeatedly and cost a reclaimed GPU. v2's fixes:
#   1. SIGNAL = GPU utilization from the VAST API (`vastai show instances`),
#      NOT SSH. No SSH dependency -> no flaky-SSH false positives. A working
#      trainer shows high gpu_util; a genuinely idle box shows ~0%.
#   2. HEAVY bias to NOT stop. Cost of a wrongly-running idle box (~$0.65/hr) is
#      far less than the cost of stopping a training run (lost work + the GPU
#      getting reclaimed). Any ambiguity -> leave it running.
#   3. LONG sustained-idle grace: require GRACE_CHECKS *consecutive* readings of
#      gpu_util <= IDLE_GPU_PCT before stopping (~2h). A working run (even our
#      CPU-heavy env, which still drives GPU>0) spikes util within that window.
#      A momentary low-util gap (e.g. a sweep between trials) never accumulates.
#   4. EXCLUDE boxes holding unique state (japan's sole replay cache) — never
#      auto-stop them; surface them for a manual decision instead.
#   5. OPT-IN + ALERT-FIRST: stops only when the arm-file exists; without it the
#      guard only WARNS (desktop notification). At WARN_CHECKS it warns; at
#      GRACE_CHECKS it stops (if armed). Unknown/missing gpu_util is treated as
#      "working" (never counts toward idle).
set -u

STATE=/tmp/bb_idle_guard_v2.state
LOG=/tmp/bb_idle_guard_v2.log
IDLE_GPU_PCT=5          # gpu_util <= this (percent) counts as idle for one check
WARN_CHECKS=6          # consecutive idle checks -> warn (~1h at 10-min cadence)
GRACE_CHECKS=12        # consecutive idle checks -> stop if armed (~2h)
EXCLUDE_LABELS="bb-japan-native"   # space-separated; never auto-stop these
ARMED_FILE="$HOME/.bb_idle_guard_armed"   # must exist for the guard to STOP (else warn-only)

ts(){ date '+%F %T'; }
note(){ command -v osascript >/dev/null 2>&1 && \
        osascript -e "display notification \"$1\" with title \"bb-idle-guard\"" >/dev/null 2>&1 || true; }
touch "$STATE"

armed=0; [ -f "$ARMED_FILE" ] && armed=1

# Pull id/label/status/gpu_util straight from the Vast API. No SSH.
# Missing gpu_util -> emit -1 (treated as "unknown" = working, never idle).
rows="$(vastai show instances --raw 2>/dev/null | python3 -c "
import json,sys
try: data=json.load(sys.stdin)
except Exception: sys.exit(0)
for i in data:
    lbl=i.get('label') or ''
    if not lbl.startswith('bb-'): continue
    g=i.get('gpu_util')
    g=-1 if g is None else g
    print(i['id'], lbl, i.get('actual_status') or 'unknown', g)
")"
[ -n "$rows" ] || exit 0   # API hiccup -> do nothing this cycle (never stop blind)

printf '%s\n' "$rows" | while read -r id label status gutil; do
  [ -n "$id" ] || continue

  # Not running -> clear any idle state, skip.
  if [ "$status" != "running" ]; then
    grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
    continue
  fi

  # Excluded (unique-state) box -> never auto-stop. Surface if it looks idle.
  excluded=0
  for e in $EXCLUDE_LABELS; do [ "$label" = "$e" ] && excluded=1; done

  # gpu_util as integer; unknown (-1) or > threshold => WORKING => reset.
  gi="${gutil%.*}"; case "$gi" in ''|*[!0-9-]*) gi=-1;; esac
  if [ "$gi" -lt 0 ] || [ "$gi" -gt "$IDLE_GPU_PCT" ]; then
    grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
    continue
  fi

  # Confirmed-idle this check: bump the consecutive counter.
  miss="$(grep "^$id " "$STATE" 2>/dev/null | awk '{print $2}')"; miss=$(( ${miss:-0} + 1 ))
  grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
  echo "$id $miss" >> "$STATE"
  echo "$(ts) $label ($id): gpu_util ${gi}% idle, $miss/$GRACE_CHECKS" >> "$LOG"

  if [ "$excluded" = 1 ]; then
    [ "$miss" = "$WARN_CHECKS" ] && { note "$label idle ${WARN_CHECKS}0min but EXCLUDED — stop it manually if done"; \
        echo "$(ts) $label ($id): idle but EXCLUDED (unique state) — manual stop only" >> "$LOG"; }
    continue
  fi

  if [ "$miss" -ge "$GRACE_CHECKS" ]; then
    if [ "$armed" = 1 ]; then
      vastai stop instance "$id" >> "$LOG" 2>&1
      note "$label STOPPED after ~2h idle (gpu_util ~0)"
      echo "$(ts) $label ($id): STOPPED after $miss idle checks (armed)" >> "$LOG"
      grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
    else
      note "$label idle ~2h — NOT armed, stop it manually (touch ~/.bb_idle_guard_armed to auto-stop)"
      echo "$(ts) $label ($id): idle $miss but NOT armed (warn-only)" >> "$LOG"
    fi
  elif [ "$miss" = "$WARN_CHECKS" ]; then
    note "$label idle ~1h (gpu_util ${gi}%); will stop at ~2h if armed"
  fi
done
