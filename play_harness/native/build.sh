#!/usr/bin/env bash
# Build the play-harness engine shim as a shared library.
#
# -ffp-contract=off keeps float-derived observation bytes (block EV and step
# success planes) free of fused multiply-add, which clang enables by default
# on arm64. Parity against rig-recorded observations is checked by
# play_harness/tests/test_parity_fixture.py when a fixture is present.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OUT_DIR="${BBPLAY_BUILD_DIR:-$ROOT/build/play_harness}"
mkdir -p "$OUT_DIR"
case "$(uname -s)" in
  Darwin) EXT=dylib ;;
  *) EXT=so ;;
esac
CC="${CC:-cc}"
"$CC" -std=c11 -O2 -g -ffp-contract=off -fPIC -shared \
  -Wall -Wextra -Wno-unused-function \
  -I"$ROOT/engine/include" -I"$ROOT/puffer/bloodbowl" \
  "$ROOT/play_harness/native/bbplay.c" \
  -o "$OUT_DIR/libbbplay.$EXT" -lm
echo "$OUT_DIR/libbbplay.$EXT"
