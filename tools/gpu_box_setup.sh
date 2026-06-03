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

echo "=== [4/5] standalone benchmark (sanity + throughput) ==="
./build.sh bloodbowl --fast
./bloodbowl 64

echo "=== [5/5] CUDA training backend ==="
./build.sh bloodbowl

echo
echo "ready. smoke run:"
echo "  cd vendor/PufferLib && puffer train bloodbowl --train.total-timesteps 20000000"
