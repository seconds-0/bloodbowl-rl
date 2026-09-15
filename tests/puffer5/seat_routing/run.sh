#!/usr/bin/env bash
# 5.0 league seat routing vs 4.0 selfplay.build_perm_tags.
#   PUFFER5=<installed 5.0 tree> ENV_OBJ=<build/bloodbowl_env.o> \
#   SELFPLAY40=<copy of the live 4.0 pufferlib/selfplay.py> PYTHON=<python with numpy> \
#   OUT=<scratch dir> bash tests/puffer5/seat_routing/run.sh
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
PUFFER5="${PUFFER5:?}"; ENV_OBJ="${ENV_OBJ:?}"; SELFPLAY40="${SELFPLAY40:?}"
PYTHON="${PYTHON:-python3}"; OUT="${OUT:?}"
mkdir -p "$OUT/stub" && touch "$OUT/stub/raylib.h"
"${CXX:-clang++}" -std=c++17 -O1 -w -I"$PUFFER5/src" -I"$PUFFER5/ocean/bloodbowl" \
    -I"$OUT/stub" "$HERE/p5_layout.cpp" "$ENV_OBJ" -o "$OUT/p5_layout" -lm
fail=0
# num_policies hist_policy_percent num_frozen_banks frozen_bank_pct scripted_bank_tag
for cfg in "5 0.953125 4 0.12 4" "9 0.953125 8 0.06 8" "2 0.19921875 1 0.1 1"; do
    set -- $cfg
    "$OUT/p5_layout" 2048 2 "$1" "$2" > "$OUT/layout_$1.txt"
    "$PYTHON" "$HERE/compare_layout.py" "$SELFPLAY40" "$OUT/layout_$1.txt" \
        2048 2 "$3" "$4" "$5" || fail=1
done
exit "$fail"
