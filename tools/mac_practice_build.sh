#!/usr/bin/env bash
# Mac (Apple Silicon) practice-run build of the PufferLib torch-CPU backend
# with the bloodbowl env statically linked. NOT for real training — that's
# the Linux CUDA box. This exists to shake out env/binding/policy integration
# locally before paying for GPU time.
#
# Why not ./build.sh bloodbowl --cpu on Mac:
#   * torch ships its own libomp; linking homebrew's into _C.so makes two
#     OpenMP runtimes in-process -> segfault in __kmp_suspend_initialize_thread.
#     Fix: compile WITHOUT -fopenmp (vecenv/bindings_cpu use only `#pragma omp`,
#     no omp_* API, so pragmas degrade to single-threaded loops).
#   * Run with: puffer train bloodbowl --slowly --selfplay.enabled 0
#     (the Torch backend now consumes Blood Bowl's exact conditional masks;
#     self-play pool management remains a native/CUDA concern.)
set -euo pipefail

cd "$(dirname "$0")/../vendor/PufferLib"
source .venv/bin/activate

tools_dir="$(cd .. && pwd)"
CC=/opt/homebrew/opt/llvm/bin/clang
CXX=/opt/homebrew/opt/llvm/bin/clang++
OMP_INC=/opt/homebrew/opt/libomp/include   # for #include <omp.h> only; no lib linked
PYTHON_INCLUDE=$(python -c "import sysconfig; print(sysconfig.get_path('include'))")
PYBIND_INCLUDE=$(python -c "import pybind11; print(pybind11.get_include())")
EXT_SUFFIX=$(python -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))")

mkdir -p build
echo "[1/3] binding.c (env static lib, no OpenMP)"
$CC -c -O2 -DNDEBUG -Wall \
    -I. -Isrc -Iocean/bloodbowl -Ivendor -Iraylib-5.5_macos/include -I"$OMP_INC" \
    -DPLATFORM_DESKTOP -fvisibility=hidden -fPIC \
    ocean/bloodbowl/binding.c -o build/libstatic_bloodbowl.o
ar rcs build/libstatic_bloodbowl.a build/libstatic_bloodbowl.o

echo "[2/3] bindings_cpu.cpp (torch backend, no OpenMP)"
$CXX -c -fPIC -D_GLIBCXX_USE_CXX11_ABI=1 -DPLATFORM_DESKTOP -std=c++17 \
    -I. -Isrc -I"$PYTHON_INCLUDE" -I"$PYBIND_INCLUDE" -I"$OMP_INC" \
    -DOBS_TENSOR_T=ByteTensor -DENV_NAME=bloodbowl -DPRECISION_FLOAT -O2 \
    src/bindings_cpu.cpp -o build/bindings_cpu.o

echo "[3/3] link pufferlib/_C${EXT_SUFFIX}"
$CXX -shared -fPIC build/bindings_cpu.o build/libstatic_bloodbowl.a \
    raylib-5.5_macos/lib/libraylib.a -lm -lpthread -O2 \
    -framework Cocoa -framework OpenGL -framework IOKit -undefined dynamic_lookup \
    -o "pufferlib/_C${EXT_SUFFIX}"

echo "ok. practice run:"
echo "  cd vendor/PufferLib && source .venv/bin/activate"
echo "  puffer train bloodbowl --slowly --selfplay.enabled 0 \\"
echo "      --train.total-timesteps 100000 --vec.total-agents 128 --train.minibatch-size 2048"
