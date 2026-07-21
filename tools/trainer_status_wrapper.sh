#!/usr/bin/env bash
# Run one trainer, forward termination to it, and publish one atomic status.
set -u

if [ "$#" -lt 3 ]; then
  echo "usage: trainer_status_wrapper.sh STATUS LOG COMMAND..." >&2
  exit 2
fi
status=$1
log=$2
shift 2

child=0
guard_pid=0
interrupted=0
guard=${LIVE_INTEGRITY_GUARD:-}
guard_python=${LIVE_INTEGRITY_PYTHON:-}
guard_state=${LIVE_INTEGRITY_STATE:-}
guard_failure=${LIVE_INTEGRITY_FAILURE:-}
guard_silence=${LIVE_INTEGRITY_MAX_SILENCE:-}
guard_poll=${LIVE_INTEGRITY_POLL_SECONDS:-}
guard_marker=${LIVE_INTEGRITY_MARKER:-${status}.guard-failed}

if [ -n "$guard" ]; then
  for value in "$guard_python" "$guard_state" "$guard_failure" \
               "$guard_silence" "$guard_poll" "$guard_marker"; do
    [ -n "$value" ] || {
      echo "embedded live-integrity watchdog configuration is incomplete" >&2
      exit 2
    }
  done
  [ ! -e "$guard_marker" ] || {
    echo "existing watchdog failure marker requires a new run: $guard_marker" >&2
    exit 2
  }
fi

forward_signal() {
  interrupted=143
  if [ "$child" -gt 0 ]; then
    kill -TERM "$child" 2>/dev/null || true
  fi
  if [ "$guard_pid" -gt 0 ]; then
    kill -TERM "$guard_pid" 2>/dev/null || true
  fi
}
trap forward_signal TERM INT

set +e
"$@" >> "$log" 2>&1 &
child=$!
if [ -n "$guard" ]; then
  (
    while kill -0 "$child" 2>/dev/null; do
      if ! "$guard_python" "$guard" \
          --log "$log" --state "$guard_state" --failure "$guard_failure" \
          --max-panel-silence-seconds "$guard_silence"; then
        : > "$guard_marker"
        kill -TERM "$child" 2>/dev/null || true
        for _ in $(seq 1 20); do
          kill -0 "$child" 2>/dev/null || exit 2
          sleep 0.25
        done
        kill -KILL "$child" 2>/dev/null || true
        exit 2
      fi
      sleep "$guard_poll"
    done
  ) >> "$log" 2>&1 &
  guard_pid=$!
fi
wait "$child"
rc=$?
if [ "$guard_pid" -gt 0 ]; then
  kill -TERM "$guard_pid" 2>/dev/null || true
  wait "$guard_pid" 2>/dev/null || true
fi
if [ -e "$guard_marker" ]; then
  rc=86
fi
if [ "$interrupted" -ne 0 ]; then
  for _ in $(seq 1 20); do
    kill -0 "$child" 2>/dev/null || break
    sleep 0.25
  done
  kill -KILL "$child" 2>/dev/null || true
  wait "$child" 2>/dev/null || true
  rc=$interrupted
fi
trap - TERM INT

tmp="${status}.tmp.$$"
printf '{"exit_code":%d,"pid":%d,"completed_utc":"%s"}\n' \
  "$rc" "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$tmp"
mv "$tmp" "$status"
exit "$rc"
