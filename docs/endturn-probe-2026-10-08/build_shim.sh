#!/usr/bin/env bash
# Build the probe's engine library: the harness shim (bbplay.c, unchanged) plus
# endturn_shim.c's read-only accessors. Flags are play_harness/native/build.sh's.
#
#   build_shim.sh HARNESS_EXPORT OUT_DIR
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HARNESS="$(cd "$1" && pwd)"
OUT_DIR="$2"
mkdir -p "$OUT_DIR"
case "$(uname -s)" in
  Darwin) EXT=dylib ;;
  *) EXT=so ;;
esac
CC="${CC:-cc}"
"$CC" -std=c11 -O2 -g -ffp-contract=off -fPIC -shared \
  -Wall -Wextra -Wno-unused-function \
  -I"$HARNESS/engine/include" -I"$HARNESS/puffer/bloodbowl" \
  -I"$HARNESS/play_harness/native" \
  "$HERE/endturn_shim.c" \
  -o "$OUT_DIR/libbbprobe.$EXT" -lm
echo "$OUT_DIR/libbbprobe.$EXT"
