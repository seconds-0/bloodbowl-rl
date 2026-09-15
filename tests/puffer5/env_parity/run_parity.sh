#!/usr/bin/env bash
# 4.0 <-> 5.0 env parity: observation bytes, exact joint support, rewards,
# terminals and the summed episode Log, step by step under the same seeds.
#
# Runs on a Linux box with the 4.0 reference vecenv headers (copied read-only
# from the live 4.0 tree) and an installed PufferLib 5.0 tree:
#   REF40_SRC=/home/rache/bbpuffer5/ref40src \
#   PUFFER5=/home/rache/bbpuffer5/PufferLib5 \
#   OUT=/home/rache/bbpuffer5/parity bash tests/puffer5/env_parity/run_parity.sh
# CPU only: links libcudart for the 4.0 vecenv symbols but never calls CUDA.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
REF40_SRC="${REF40_SRC:?set REF40_SRC to a dir holding 4.0 vecenv.h and tensor.h}"
PUFFER5="${PUFFER5:?set PUFFER5 to an installed PufferLib 5.0 tree}"
OUT="${OUT:?set OUT}"
CC="${CC:-clang}"
CXX="${CXX:-clang++}"
NICE="nice -n 19"
mkdir -p "$OUT"

# Same flags as the 4.0 static-library compile of binding.c (-O2 -DNDEBUG
# -mavx2 -mfma, -fopenmp); no raylib on the include path (render is a no-op
# and does not touch observations).
FLAGS=(-O2 -DNDEBUG -mavx2 -mfma -fopenmp -w)
ENVSRC="$OUT/envsrc"
rm -rf "$ENVSRC"
mkdir -p "$ENVSRC"
cp -RL "$ROOT/puffer/bloodbowl/." "$ENVSRC/"
echo "env source hash: $(cd "$ENVSRC" && find -L . -type f -print0 | LC_ALL=C sort -z \
    | xargs -0 sha256sum | sha256sum | cut -c1-16)"

echo "building 4.0 reference driver"
$NICE "$CC" "${FLAGS[@]}" -I"$REF40_SRC" -I"$ENVSRC" -I"$HERE" \
    "$HERE/ref40_driver.c" -o "$OUT/ref40_driver" -lm -lcudart

echo "building 5.0 adapter driver"
$NICE "$CC" -c "${FLAGS[@]}" -I"$PUFFER5/src" -I"$PUFFER5/ocean/bloodbowl/env" \
    -I"$PUFFER5/ocean/bloodbowl/shim" "$PUFFER5/ocean/bloodbowl/bloodbowl5_env.c" \
    -o "$OUT/bloodbowl_env.o"
RAYLIB_INC="$(ls -d "$PUFFER5"/raylib-5.5_*/include 2>/dev/null | head -1 || true)"
if [ -z "$RAYLIB_INC" ]; then
    mkdir -p "$OUT/stub" && touch "$OUT/stub/raylib.h"
    RAYLIB_INC="$OUT/stub"
fi
$NICE "$CXX" -std=c++17 -O2 -fopenmp -w -I"$PUFFER5/src" -I"$PUFFER5/ocean/bloodbowl" \
    -I"$RAYLIB_INC" -I"$HERE" "$HERE/p5_driver.cpp" "$OUT/bloodbowl_env.o" \
    -o "$OUT/p5_driver" -lm

fail=0
run_case() {
    local agents="$1" steps="$2" seed="$3" maxdec="$4"
    local tag="a${agents}_s${steps}_seed${seed}_md${maxdec}"
    OMP_NUM_THREADS=4 $NICE "$OUT/ref40_driver" "$agents" "$steps" "$seed" "$maxdec" \
        "$OUT/ref40_$tag.bin" > "$OUT/ref40_$tag.fnv"
    OMP_NUM_THREADS=4 $NICE "$OUT/p5_driver" "$agents" "$steps" "$seed" "$maxdec" \
        "$OUT/p5_$tag.bin" > "$OUT/p5_$tag.fnv"
    if cmp -s "$OUT/ref40_$tag.bin" "$OUT/p5_$tag.bin"; then
        echo "PARITY OK   $tag  $(tail -1 "$OUT/p5_$tag.fnv")  bytes=$(stat -c %s "$OUT/p5_$tag.bin")"
    else
        echo "PARITY FAIL $tag"
        diff "$OUT/ref40_$tag.fnv" "$OUT/p5_$tag.fnv" | head -5
        fail=1
    fi
}
run_case 16 200 42 0
run_case 16 200 7 0
run_case 16 200 42 64
run_case 64 5000 42 0
exit "$fail"
