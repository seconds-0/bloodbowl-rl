#!/usr/bin/env bash
# bb_idle_guard_v2 — stop genuinely-idle Vast bb-* boxes to save money, WITHOUT
# ever false-stopping active work. Runs every 10 min (launchd). Mac-side.
#
# WHY v2 (the 2026-06-17 incident): v1 decided "idle" by SSHing each box and
# running `pgrep puffer`. Vast's SSH proxy is chronically flaky, so an
# unreachable TRAINING box read as "no trainer" -> idle -> stopped. That killed
# an active 30B run repeatedly and cost a reclaimed GPU.
#
# v2 design (adversarial Opus review + Codex review + Alex's N-consecutive-zeros):
#   1. SIGNAL = the Vast API (`vastai show instances --raw`), NO SSH. Read BOTH
#      gpu_util AND cpu_util. This env is CPU-heavy (reachability Dijkstra), so a
#      working box shows high CPU even when GPU dips; an idle box shows ~0 on both.
#   2. STALE-TELEMETRY DEFENSE: the API's gpu_util is a coarsely-cached field that
#      intermittently publishes a stale 0.0 on a fully-working box (measured 2/7
#      reads = 0.0 at 90% GPU). So a SINGLE read is untrustworthy. Each cycle we
#      take SAMPLES_PER_CHECK fresh API snapshots spaced SAMPLE_GAP_S apart.
#   3. STRICT idle invariant (Codex): a box counts "idle this check" ONLY IF it
#      was PRESENT IN EVERY snapshot AND every sample had gpu_util<=IDLE_GPU_PCT
#      AND cpu_util<=IDLE_CPU_PCT (FLOAT comparison, no truncation). Any missing
#      sample, any busy sample on EITHER signal, or unknown util => WORKING =>
#      reset. The idle/working verdict is computed in Python; bash only acts on it.
#      And: if any of the SAMPLES_PER_CHECK API calls fails, the whole cycle is
#      skipped (never decide on partial data).
#   4. SUSTAINED grace ACROSS cycles: even after an idle check, require
#      GRACE_CHECKS consecutive idle checks (~2h) before acting. Any working
#      check resets the counter to 0.
#   5. WARN-FIRST, opt-in STOP: default warn-only (desktop notification). Issues
#      `vastai stop` only if the arm-file exists, and only on checked success.
#   6. EXCLUDE unique-state boxes (japan's sole replay cache) from auto-stop.
#   7. PID-tokenized mkdir lock (no flock on macOS); the EXIT trap removes the
#      lock only if we still own it; stale lock reclaimed only if the owner PID
#      is dead or the lock is >20min old.
set -u

STATE=/tmp/bb_idle_guard_v2.state
LOG=/tmp/bb_idle_guard_v2.log
LOCK=/tmp/bb_idle_guard_v2.lock
IDLE_GPU_PCT=5            # a sample with gpu_util > this => working
IDLE_CPU_PCT=15          # a sample with cpu_util > this => working
SAMPLES_PER_CHECK=3      # fresh API snapshots per cycle; box must be idle in ALL
SAMPLE_GAP_S=15          # spacing (s) so each snapshot is a distinct cached value
WARN_CHECKS=6            # consecutive idle checks -> warn (~1h)
GRACE_CHECKS=12          # consecutive idle checks -> stop IF armed (~2h)
EXCLUDE_LABELS="bb-japan-native"          # never auto-stop (sole replay cache)
ARMED_FILE="$HOME/.bb_idle_guard_armed"   # must exist to actually STOP; else warn-only
SNAP="/tmp/bb_idle_guard_v2.snap.$$"

ts(){ date '+%F %T'; }
note(){ command -v osascript >/dev/null 2>&1 && \
  osascript -e "display notification \"$1\" with title \"bb-idle-guard\"" >/dev/null 2>&1 || true; }
cleanup(){ rm -f "$SNAP" 2>/dev/null; [ "$(cat "$LOCK/pid" 2>/dev/null)" = "$$" ] && rm -rf "$LOCK" 2>/dev/null; }

# --- PID-tokenized lock: only one cycle at a time; reclaim only if dead/stale.
acquire_lock(){
  if mkdir "$LOCK" 2>/dev/null; then echo $$ > "$LOCK/pid"; return 0; fi
  local opid age
  opid="$(cat "$LOCK/pid" 2>/dev/null)"
  age=$(( $(date +%s) - $(stat -f %m "$LOCK" 2>/dev/null || stat -c %Y "$LOCK" 2>/dev/null || echo 0) ))
  if { [ -n "$opid" ] && ! kill -0 "$opid" 2>/dev/null; } || [ "$age" -gt 1200 ]; then
    rm -rf "$LOCK" 2>/dev/null
    if mkdir "$LOCK" 2>/dev/null; then echo $$ > "$LOCK/pid"; return 0; fi
  fi
  return 1
}
acquire_lock || { echo "$(ts) lock held by a live cycle, skipping" >> "$LOG"; exit 0; }
trap cleanup EXIT
touch "$STATE"

armed=0; [ -f "$ARMED_FILE" ] && armed=1

# --- Take SAMPLES_PER_CHECK API snapshots. If ANY call fails -> skip the cycle
#     (never decide on partial data).
: > "$SNAP"
ok=0
for s in $(seq 1 "$SAMPLES_PER_CHECK"); do
  out="$(vastai show instances --raw 2>/dev/null | python3 -c "
import json,sys
try: data=json.load(sys.stdin)
except Exception: sys.exit(1)
n=0
for i in data:
    lbl=i.get('label') or ''
    if not lbl.startswith('bb-'): continue
    g=i.get('gpu_util'); c=i.get('cpu_util')
    g='nan' if g is None else g
    c='nan' if c is None else c
    print(i['id'], lbl, i.get('actual_status') or 'unknown', g, c); n+=1
sys.exit(0)
")"
  [ $? -eq 0 ] || { echo "$(ts) API snapshot $s failed, skipping cycle" >> "$LOG"; exit 0; }
  printf '%s\n' "$out" >> "$SNAP"; ok=$((ok+1))
  [ "$s" -lt "$SAMPLES_PER_CHECK" ] && sleep "$SAMPLE_GAP_S"
done

# --- Decide per-id in Python: idle ONLY IF present in ALL snapshots AND every
#     sample had gpu<=GPU AND cpu<=CPU (float). Else working. Output: id label status idle.
verdict="$(python3 - "$SNAP" "$SAMPLES_PER_CHECK" "$IDLE_GPU_PCT" "$IDLE_CPU_PCT" <<'PY'
import sys
path, need, gthr, cthr = sys.argv[1], int(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4])
inst={}
for ln in open(path):
    p=ln.split()
    if len(p)<5: continue
    i,lbl,st,gs,cs=p[0],p[1],p[2],p[3],p[4]
    try: g=float(gs); c=float(cs)
    except: g=c=float('nan')
    e=inst.setdefault(i,{'lbl':lbl,'st':st,'n':0,'idle_all':True})
    e['st']=st; e['n']+=1
    # this sample is "idle" only if both signals are valid numbers <= threshold
    import math
    sample_idle = (not math.isnan(g) and not math.isnan(c) and g<=gthr and c<=cthr)
    if not sample_idle: e['idle_all']=False
for i,e in inst.items():
    idle = 1 if (e['n']==need and e['idle_all']) else 0
    print(i, e['lbl'], e['st'], idle)
PY
)"
rm -f "$SNAP"
[ -n "$verdict" ] || { echo "$(ts) no bb-* instances, nothing to do" >> "$LOG"; exit 0; }

printf '%s\n' "$verdict" | while read -r id label status idle; do
  [ -n "$id" ] || continue

  # Not cleanly running, or Python judged it working -> clear idle state, skip.
  if [ "$status" != "running" ] || [ "$idle" != "1" ]; then
    grep -v "^$id " "$STATE" > "$STATE.$$" 2>/dev/null; mv "$STATE.$$" "$STATE" 2>/dev/null
    continue
  fi

  # Confirmed idle this check (present in all samples, all quiet): bump counter.
  miss="$(grep "^$id " "$STATE" 2>/dev/null | awk '{print $2+0}')"; miss=$(( ${miss:-0} + 1 ))
  grep -v "^$id " "$STATE" > "$STATE.$$" 2>/dev/null; mv "$STATE.$$" "$STATE" 2>/dev/null
  echo "$id $miss" >> "$STATE"
  echo "$(ts) $label ($id): idle (all $SAMPLES_PER_CHECK samples quiet) $miss/$GRACE_CHECKS" >> "$LOG"

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
        grep -v "^$id " "$STATE" > "$STATE.$$" 2>/dev/null; mv "$STATE.$$" "$STATE" 2>/dev/null
      else
        note "$label stop FAILED (API) — will retry next cycle"
        echo "$(ts) $label ($id): vastai stop FAILED, counter kept" >> "$LOG"
      fi
    else
      note "$label idle ~2h — NOT armed; stop manually or 'touch ~/.bb_idle_guard_armed'"
      echo "$(ts) $label ($id): idle $miss, NOT armed (warn-only)" >> "$LOG"
    fi
  elif [ "$miss" -ge "$WARN_CHECKS" ] && [ "$miss" -lt "$((WARN_CHECKS+1))" ]; then
    note "$label idle ~1h; stops at ~2h if armed"
  fi
done
rm -f "$STATE".[0-9]* 2>/dev/null
