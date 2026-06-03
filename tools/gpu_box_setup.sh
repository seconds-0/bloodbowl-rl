#!/usr/bin/env bash
# One-shot setup on a freshly provisioned Vast.ai box (pytorch devel image).
# Run from the repo root on the box: bash tools/gpu_box_setup.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "=== [1/5] system deps (clang for build.sh, curl for raylib download) ==="
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq clang curl rsync libomp-dev ccache libgl1-mesa-dev > /dev/null

echo "=== [2/5] python deps (reuse image torch) ==="
cd "$ROOT/vendor/PufferLib"
pip install --no-build-isolation -q -e .

echo "=== [3/5] install bloodbowl env into PufferLib tree ==="
bash "$ROOT/tools/install_puffer_env.sh"

# build.sh's standalone (--fast/--local) path compiles ocean/bloodbowl/bloodbowl.c
# WITHOUT -I$SRC_DIR (the binding path has it), so the engine's "bb/*.h"
# header-to-header includes can't resolve. Idempotent one-line patch.
if ! grep -q 'ocean/bloodbowl' "$ROOT/vendor/PufferLib/build.sh"; then
    sed -i 's|^INCLUDES=(-I./\$RAYLIB_NAME/include -I./src -I./vendor)$|INCLUDES=(-I./$RAYLIB_NAME/include -I./src -I./vendor -I./ocean/bloodbowl)|' \
        "$ROOT/vendor/PufferLib/build.sh"
    grep -q 'ocean/bloodbowl' "$ROOT/vendor/PufferLib/build.sh" || { echo "build.sh include patch failed" >&2; exit 1; }
fi

echo "=== [4/5] standalone benchmark (sanity + throughput) ==="
./build.sh bloodbowl --fast
./bloodbowl 64

echo "=== [5/5] CUDA training backend ==="
# pytorch wheel images ship libcudnn.so.9 without the unversioned dev symlink
# that build.sh's -lcudnn link needs.
CUDNN_LIB=$(python -c "import nvidia.cudnn, os; print(os.path.join(nvidia.cudnn.__path__[0], 'lib'))" 2>/dev/null || true)
if [ -n "$CUDNN_LIB" ] && [ -f "$CUDNN_LIB/libcudnn.so.9" ] && [ ! -e "$CUDNN_LIB/libcudnn.so" ]; then
    ln -s libcudnn.so.9 "$CUDNN_LIB/libcudnn.so"
fi
./build.sh bloodbowl

echo
echo "ready. smoke run:"
echo "  cd vendor/PufferLib && puffer train bloodbowl --train.total-timesteps 20000000"
