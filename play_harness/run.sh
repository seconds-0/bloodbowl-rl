#!/usr/bin/env bash
# Start the Blood Bowl play harness on http://127.0.0.1:8790/ (loopback only).
# Builds the engine shim when it is missing or older than its sources.
#   play_harness/run.sh [--port 8790] [--checkpoint-dir DIR]
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="${BBPLAY_PYTHON:-$ROOT/.venv/bin/python}"
if [ ! -x "$PY" ]; then
  PY="$(command -v python3)"
fi
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-2}"
cd "$ROOT"
exec "$PY" -m play_harness "$@"
