#!/usr/bin/env bash
# bb_idle_guard_v2 — stop genuinely-idle Vast bb-* boxes to save money, WITHOUT
# ever false-stopping active work. Runs every 10 min (launchd). Mac-side.
#
# WHY v2 (the 2026-06-17 incident): v1 decided "idle" by SSHing each box and
# running `pgrep puffer`. Vast's SSH proxy is chronically flaky, so an
# unreachable TRAINING box read as "no trainer" -> idle -> stopped. That killed
# an active 30B run repeatedly and cost a reclaimed GPU.
#
# v2 design (incorporates an adversarial review + Alex's N-consecutive-zeros idea):
#   1. SIGNAL = the Vast API (`vastai show instances --raw`), NO SSH. We read
#      BOTH gpu_util AND cpu_util. This env is CPU-heavy (reachability Dijkstra),
#      so a working box shows high CPU even when GPU dips; an idle box shows ~0
#      on both.
#   2. STALE-TELEMETRY DEFENSE (the critical fix): the API's gpu_util is a
#      coarsely-cached field that intermittently publishes a stale 0.0 on a
#      fully-working box (adversarial review measured 2/7 reads = 0.0 at 90% GPU).
#      So a SINGLE read is untrustworthy. Within each cycle we take SAMPLES_PER_CHECK
#      fresh API snapshots spaced SAMPLE_GAP_S apart, and a box counts as "idle
#      this check" ONLY IF EVERY sample shows BOTH gpu_util<=IDLE_GPU_PCT AND
#      cpu_util<=IDLE_CPU_PCT. ANY sample with work on EITHER signal => working
#      => reset. (Alex: "maybe it has to hit 0 three consecutive times.")
#   3. SUSTAINED grace ACROSS cycles: even after a check is "idle", require
#      GRACE_CHECKS consecutive idle checks (~2h) before acting. Any working
#      check resets the counter to 0.
#   4. WARN-FIRST, opt-in STOP: default is warn-only (desktop notification). It
#      only issues `vastai stop` if the arm-file exists. Cost of leaving an idle
#      box running (~$0.65/hr) << cost of stopping a working one (lost run +
#      GPU reclaim), so the default never pulls the trigger.
#   5. EXCLUDE unique-state boxes (japan's sole replay cache) from auto-stop.
#   6. SAFETY plumbing: flock (no overlapping cycles corrupting state); check
#      `vastai stop` exit status before announcing/clearing; do nothing on an
#      empty/failed API response (never stop blind).
set -u

STATE=/tmp/bb_idle_guard_v2.state
LOG=/tmp/bb_idle_guard_v2.log
LOCK=/tmp/bb_idle_guard_v2.lock
IDLE_GPU_PCT=5            # a single sample with gpu_util > this => working
IDLE_CPU_PCT=15          # a single sample with cpu_util > this => working
SAMPLES_PER_CHECK=3      # fresh API snapshots per cycle; ALL must be idle to count
SAMPLE_GAP_S=15          # spacing (s) so each snapshot is a distinct cached value
WARN_CHECKS=6            # consecutive idle checks -> warn (~1h)
GRACE_CHECKS=12          # consecutive idle checks -> stop IF armed (~2h)
EXCLUDE_LABELS="bb-japan-native"          # never auto-stop (sole replay cache)
ARMED_FILE="$HOME/.bb_idle_guard_armed"   # must exist to actually STOP; else warn-only

ts(){ date '+%F %T'; }
note(){ command -v osascript >/dev/null 2>&1 && \
  osascript -e "display notification \"$1\" with title \"bb-idle-guard\"" >/dev/null 2>&1 || true; }

# Single-instance lock (portable: atomic mkdir; no flock — absent on macOS).
# A stale lock (>20 min, i.e. a crashed prior cycle) is reclaimed.
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -d "$LOCK" ]; then
    age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
    if [ "$age" -gt 1200 ]; then rmdir "$LOCK" 2>/dev/null; mkdir "$LOCK" 2>/dev/null || exit 0
    else echo "$(ts) lock held, skipping cycle" >> "$LOG"; exit 0; fi
  else exit 0; fi
fi
trap 'rmdir "$LOCK" 2>/dev/null' EXIT
touch "$STATE"

armed=0; [ -f "$ARMED_FILE" ] && armed=1

# --- Collect SAMPLES_PER_CHECK API snapshots, spaced out. Accumulate per-id the
#     MAX gpu_util and MAX cpu_util seen across the samples (max defeats stale 0s).
#     Also record the last-seen status. ---
snap="/tmp/bb_idle_guard_v2.snap.$$"; : > "$snap"
got_any=0
for s in $(seq 1 "$SAMPLES_PER_CHECK"); do
  out="$(vastai show instances --raw 2>/dev/null | python3 -c "
import json,sys
try: data=json.load(sys.stdin)
except Exception: sys.exit(0)
for i in data:
    lbl=i.get('label') or ''
    if not lbl.startswith('bb-'): continue
    g=i.get('gpu_util'); c=i.get('cpu_util')
    g=-1 if g is None else g
    c=-1 if c is None else c
    print(i['id'], lbl, i.get('actual_status') or 'unknown', g, c)
")"
  [ -n "$out" ] && { got_any=1; printf '%s\n' "$out" >> "$snap"; }
  [ "$s" -lt "$SAMPLES_PER_CHECK" ] && sleep "$SAMPLE_GAP_S"
done
# API never answered this cycle -> do nothing (never stop blind).
[ "$got_any" = 1 ] || { echo "$(ts) API empty all samples, skipping cycle" >> "$LOG"; rm -f "$snap"; exit 0; }

# Reduce to one line per id: id label status max_gpu max_cpu  (max over samples).
agg="$(python3 - "$snap" <<'PY'
import sys
mx={}
for ln in open(sys.argv[1]):
    p=ln.split()
    if len(p)<5: continue
    i,lbl,st=p[0],p[1],p[2]
    try: g=float(p[3]); c=float(p[4])
    except: g=c=-1.0
    e=mx.setdefault(i,{'lbl':lbl,'st':st,'g':-1.0,'c':-1.0})
    e['st']=st                          # last-seen status
    if g>e['g']: e['g']=g
    if c>e['c']: e['c']=c
for i,e in mx.items():
    print(i,e['lbl'],e['st'],int(e['g']),int(e['c']))
PY
)"
rm -f "$snap"

printf '%s\n' "$agg" | while read -r id label status gmax cmax; do
  [ -n "$id" ] || continue

  # Not cleanly running (stopped / loading / mid-transition) -> clear state, skip.
  if [ "$status" != "running" ]; then
    grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
    continue
  fi

  # WORKING if EITHER signal shows activity in ANY sample (gmax/cmax are maxima).
  # Unknown (-1) is treated as working (never idle). This is the reset path.
  if [ "$gmax" -lt 0 ] || [ "$cmax" -lt 0 ] \
     || [ "$gmax" -gt "$IDLE_GPU_PCT" ] || [ "$cmax" -gt "$IDLE_CPU_PCT" ]; then
    grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
    continue
  fi

  # Confirmed idle this check (every sample quiet on both signals): bump counter.
  miss="$(grep "^$id " "$STATE" 2>/dev/null | awk '{print $2+0}')"; miss=$(( ${miss:-0} + 1 ))
  grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
  echo "$id $miss" >> "$STATE"
  echo "$(ts) $label ($id): idle (gpu_max ${gmax}% cpu_max ${cmax}%) $miss/$GRACE_CHECKS" >> "$LOG"

  excluded=0; for e in $EXCLUDE_LABELS; do [ "$label" = "$e" ] && excluded=1; done

  if [ "$excluded" = 1 ]; then
    [ "$miss" -ge "$WARN_CHECKS" ] && [ "$miss" -lt "$((WARN_CHECKS+1))" ] && \
      note "$label idle ~1h but EXCLUDED — stop it manually if done"
    continue
  fi

  if [ "$miss" -ge "$GRACE_CHECKS" ]; then
    if [ "$armed" = 1 ]; then
      if vastai stop instance "$id" >> "$LOG" 2>&1; then
        note "$label STOPPED after ~2h idle (gpu+cpu ~0)"
        echo "$(ts) $label ($id): STOPPED after $miss idle checks (armed)" >> "$LOG"
        grep -v "^$id " "$STATE" > "$STATE.tmp" 2>/dev/null; mv "$STATE.tmp" "$STATE" 2>/dev/null
      else
        note "$label stop FAILED (API) — will retry next cycle"
        echo "$(ts) $label ($id): vastai stop FAILED, counter kept" >> "$LOG"
      fi
    else
      note "$label idle ~2h — NOT armed; stop manually or 'touch ~/.bb_idle_guard_armed'"
      echo "$(ts) $label ($id): idle $miss, NOT armed (warn-only)" >> "$LOG"
    fi
  elif [ "$miss" -ge "$WARN_CHECKS" ] && [ "$miss" -lt "$((WARN_CHECKS+1))" ]; then
    note "$label idle ~1h (gpu_max ${gmax}% cpu_max ${cmax}%); stops at ~2h if armed"
  fi
done
rm -f "$STATE.tmp" 2>/dev/null
