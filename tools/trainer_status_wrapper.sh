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
interrupted=0
forward_signal() {
  interrupted=143
  if [ "$child" -gt 0 ]; then
    kill -TERM "$child" 2>/dev/null || true
  fi
}
trap forward_signal TERM INT

set +e
"$@" >> "$log" 2>&1 &
child=$!
wait "$child"
rc=$?
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
