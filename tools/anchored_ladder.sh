#!/usr/bin/env bash
# anchored_ladder.sh — run an all-pairs checkpoint ladder and append match CSV.
#
# Usage:
#   tools/anchored_ladder.sh [checkpoint_dir] [--resume]
#
# Environment:
#   CHECKPOINT_DIR   default checkpoint directory if no positional dir is given
#   EXTRA_ANCHORS    space-separated name=filename pairs appended to defaults
#   GAMES            games per pairing, default 2048
#   OUT              output CSV, default /tmp/anchored_ladder.csv
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CHECKPOINT_DIR="${CHECKPOINT_DIR:-training}"
RESUME=0

while [ $# -gt 0 ]; do
  case "$1" in
    --resume)
      RESUME=1
      shift
      ;;
    -h|--help)
      sed -n '2,14p' "$0"
      exit 0
      ;;
    *)
      CHECKPOINT_DIR="$1"
      shift
      ;;
  esac
done

case "$CHECKPOINT_DIR" in
  /*) ;;
  *) CHECKPOINT_DIR="$ROOT/$CHECKPOINT_DIR" ;;
esac

GAMES="${GAMES:-2048}"
OUT="${OUT:-/tmp/anchored_ladder.csv}"
case "$OUT" in
  /*) ;;
  *) OUT="$PWD/$OUT" ;;
esac

names=(
  bc_v4
  kickoff8
  v5contested
  gen1
  gen2
  gen3
  league1
)
files=(
  bc_v4_cuda.bin
  v4k8_cap.bin
  v5_contested_cap.bin
  v4_contested_cap.bin
  v4_contested2_cap.bin
  v4_contested3_cap.bin
  league_cap.bin
)

if [ -n "${EXTRA_ANCHORS:-}" ]; then
  for pair in $EXTRA_ANCHORS; do
    case "$pair" in
      *=*)
        names+=("${pair%%=*}")
        files+=("${pair#*=}")
        ;;
      *)
        echo "warning: ignoring malformed EXTRA_ANCHORS entry: $pair" >&2
        ;;
    esac
  done
fi

present_names=()
present_paths=()
for i in "${!names[@]}"; do
  path="$CHECKPOINT_DIR/${files[$i]}"
  if [ -f "$path" ]; then
    present_names+=("${names[$i]}")
    present_paths+=("$path")
  else
    echo "warning: missing anchor ${names[$i]} at $path; skipping" >&2
  fi
done

if [ "${#present_names[@]}" -lt 2 ]; then
  echo "need at least two present anchors under $CHECKPOINT_DIR" >&2
  exit 1
fi

total_pairs=$(( ${#present_names[@]} * (${#present_names[@]} - 1) / 2 ))
mkdir -p "$(dirname "$OUT")"
if [ "$RESUME" -eq 0 ] || [ ! -f "$OUT" ]; then
  printf 'nameA,nameB,A_rate,B_rate,draw_rate,total_games\n' > "$OUT"
fi

already_done() {
  local a="$1"
  local b="$2"
  [ "$RESUME" -eq 1 ] || return 1
  [ -f "$OUT" ] || return 1
  awk -F, -v a="$a" -v b="$b" '
    NR > 1 && (($1 == a && $2 == b) || ($1 == b && $2 == a)) { found = 1 }
    END { exit found ? 0 : 1 }
  ' "$OUT"
}

cd "$HOME/bloodbowl-rl"
. rig-env.sh 2>/dev/null
export PATH="$HOME/bloodbowl-rl/vendor/PufferLib/.venv/bin:$PATH"
cd vendor/PufferLib

run_count=0
pair_index=0
for i in "${!present_names[@]}"; do
  for ((j = i + 1; j < ${#present_names[@]}; j++)); do
    pair_index=$((pair_index + 1))
    name_a="${present_names[$i]}"
    name_b="${present_names[$j]}"
    path_a="${present_paths[$i]}"
    path_b="${present_paths[$j]}"

    if already_done "$name_a" "$name_b"; then
      echo "[$pair_index/$total_pairs] $name_a vs $name_b -> skipped (resume)"
      continue
    fi

    log="$(mktemp "${TMPDIR:-/tmp}/anchored_ladder.XXXXXX")"
    if ! puffer match bloodbowl \
      --load-model-path "$path_a" \
      --load-enemy-model-path "$path_b" \
      --num-games "$GAMES" \
      --env.macro-moves 0 \
      > "$log" 2>&1; then
      echo "puffer match failed for $name_a vs $name_b; log follows:" >&2
      cat "$log" >&2
      rm -f "$log"
      exit 1
    fi

    final_line="$(
      tr '\r' '\n' < "$log" |
        awk '/games=[0-9]+\/[0-9]+/ { line = $0 } END { print line }'
    )"
    rm -f "$log"
    if [ -z "$final_line" ]; then
      echo "could not parse final games= line for $name_a vs $name_b" >&2
      exit 1
    fi

    parsed="$(
      printf '%s\n' "$final_line" |
        sed -E 's/.*games=([0-9]+)\/[0-9]+.*A=([0-9.]+).*B=([0-9.]+).*draw=([0-9.]+).*/\2,\3,\4,\1/'
    )"
    if [ "$parsed" = "$final_line" ]; then
      echo "could not parse rates from final line for $name_a vs $name_b: $final_line" >&2
      exit 1
    fi

    printf '%s,%s,%s\n' "$name_a" "$name_b" "$parsed" >> "$OUT"
    IFS=, read -r a_rate b_rate draw_rate total_games <<< "$parsed"
    run_count=$((run_count + 1))
    echo "[$pair_index/$total_pairs] $name_a vs $name_b -> A=$a_rate B=$b_rate draw=$draw_rate"
  done
done

echo "csv: $OUT"
echo "summary: ran $run_count pairings (${#present_names[@]} anchors present, $total_pairs unordered pairs total)"
