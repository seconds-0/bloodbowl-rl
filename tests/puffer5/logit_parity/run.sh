#!/usr/bin/env bash
# Logit parity: PufferLib 5.0 CPU network (src/puffercpu.c) vs the play harness
# CPU torch path (play_harness/policy.py) on chain 30's checkpoint, over the
# same Blood Bowl obs sequences. Mac-local, CPU only.
#
# Env overrides: OUT, PUFFER5, CKPT, HARNESS_ROOT, PY, STEPS.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
SCRATCH=/private/tmp/claude-501/-Users-alexanderhuth/f381122e-875d-4af4-97db-856df5e9ae77/scratchpad
OUT="${OUT:-$SCRATCH/p5work/logit_parity_out}"
PUFFER5="${PUFFER5:-$SCRATCH/puffer5/repo}"
CKPT="${CKPT:-$SCRATCH/p5work/c30.bin}"
HARNESS_ROOT="${HARNESS_ROOT:-$HOME/Code/bb-play-harness}"
PY="${PY:-$HARNESS_ROOT/.venv/bin/python}"
STEPS="${STEPS:-400}"
CC="${CC:-clang}"
EXPECT_SHA=41ecd998b45613f7cb5e3b7a92b85811473abadc9f099f4baa9f307b42a6dc0b

[ -f "$PUFFER5/src/puffercpu.c" ] || { echo "missing $PUFFER5/src/puffercpu.c" >&2; exit 1; }
git -C "$PUFFER5" rev-parse HEAD | grep -q '^6ffa5b1' || {
    echo "5.0 tree is not at 6ffa5b1" >&2; exit 1; }
have_sha="$(shasum -a 256 "$CKPT" | awk '{print $1}')"
[ "$have_sha" = "$EXPECT_SHA" ] || { echo "checkpoint sha $have_sha != $EXPECT_SHA" >&2; exit 1; }

rm -rf "$OUT"
mkdir -p "$OUT"

# Env driver: same flags as the Makefile's puffer env test binaries. raylib is
# deliberately NOT on the include path, so bloodbowl.h uses its no-op renderer.
"$CC" -std=c11 -O2 -Wall -Wno-unused-function \
    -I"$ROOT/engine/include" -I"$ROOT/puffer/bloodbowl" \
    "$HERE/obs_trace.c" -o "$OUT/obs_trace" -lm
"$CC" -std=c11 -O2 -Wall -Wno-unused-function \
    -I"$PUFFER5/src" \
    "$HERE/cpu5_logits.c" -o "$OUT/cpu5_logits" -lm

# Trace A: default episode budget (no terminal in STEPS). Trace B: a
# 150-decision budget truncates matches so the terminal-reset contract runs.
"$OUT/obs_trace" "$OUT/trace_default.bin" "$STEPS" 42 0
"$OUT/obs_trace" "$OUT/trace_trunc150.bin" "$STEPS" 42 150
"$OUT/cpu5_logits" "$CKPT" "$OUT/trace_default.bin" "$OUT/cpu5_default.bin"
"$OUT/cpu5_logits" "$CKPT" "$OUT/trace_trunc150.bin" "$OUT/cpu5_trunc150.bin"

OMP_NUM_THREADS=4 HARNESS_ROOT="$HARNESS_ROOT" "$PY" -c "import torch; torch.set_num_threads(4)" >/dev/null
OMP_NUM_THREADS=4 MKL_NUM_THREADS=4 HARNESS_ROOT="$HARNESS_ROOT" "$PY" "$HERE/compare.py" \
    "$CKPT" "$HERE/RESULT.json" \
    "$OUT/trace_default.bin" "$OUT/cpu5_default.bin" \
    "$OUT/trace_trunc150.bin" "$OUT/cpu5_trunc150.bin"
