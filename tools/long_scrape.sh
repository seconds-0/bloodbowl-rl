#!/usr/bin/env bash
# Long-running gentle FUMBBL replay pull (Alex-approved, 2026-06-04).
# Grows the curated cache by ~250/cycle with a 30-min idle gap between
# cycles, re-discovering daily games each pass. 2.0s request throttle inside
# the fetcher. Stop: pkill -f long_scrape (the fetcher is resumable; the
# manifest dedupes).
set -uo pipefail
cd ~/bloodbowl-rl
TARGET=400
while true; do
  TARGET=$((TARGET + 250))
  echo "[$(date -u +%F' '%T)] cycle -> target $TARGET" >> /tmp/long_scrape.log
  python3 validation/fetch_replays.py --count "$TARGET" --refresh-discovery >> /tmp/long_scrape.log 2>&1
  echo "[$(date -u +%F' '%T)] cache: $(python3 validation/fetch_replays.py --status 2>/dev/null | head -1)" >> /tmp/long_scrape.log
  sleep 1800
done
