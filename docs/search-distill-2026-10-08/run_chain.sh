#!/usr/bin/env bash
# Run the whole chain of the search-distillation tools on this machine, in one
# process at a time, for one of the Mac-only plans: milestone 0 (the seen block)
# or the wide rehearsal. Never the registered plan, and never a droplet.
#
#   run_chain.sh m0|rehearsal RUN_NAME GATE_GAMES_PER_PAIR GATE_SEED0
#
# Steps, each timed into RUNS/RUN_NAME/CHAIN.log: the plan, the label tool, shard
# acceptance, the dataset, the three fine-tunes, the selection (Reading 1 and the
# registered arm), the held-out numbers, then a local gate rehearsal named
# distill-mac-RUN_NAME through the gate's merge-free path, its four acceptance
# checks and its scoring. Nothing that exists is overwritten: RUNS/RUN_NAME and
# the tournament directory must not exist yet.
set -euo pipefail
KIND="$1"; NAME="$2"; GATE_GAMES="$3"; GATE_SEED0="$4"
case "$KIND" in m0|rehearsal) ;; *) echo "kind is m0 or rehearsal" >&2; exit 1 ;; esac
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNS="$(cd "$HERE/../.." && pwd)/runs/search-distill-2026-10-08"
EXPORT="$RUNS/harness-5ab3ab6"
PY="$HOME/Code/bb-play-harness/.venv/bin/python"
CK="$HOME/Code/bb-play-harness/.play-artifacts/checkpoints/chain55/0000002999975936.bin"
GATE="distill-mac-$NAME"
GATE_DIR="$HOME/Code/bb-play-harness/.play-artifacts/tournaments/$GATE"
OUT="$RUNS/$NAME"
[ ! -e "$OUT" ] || { echo "$OUT exists" >&2; exit 1; }
[ ! -e "$GATE_DIR" ] || { echo "$GATE_DIR exists" >&2; exit 1; }
mkdir -p "$OUT"
export OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1
LOG="$OUT/CHAIN.log"
step() {   # step NAME COMMAND...: run, tee the output, record the wall-clock; exit 3 of `select` is a reading, not a failure
  local name="$1"; shift
  local t0; t0=$(date +%s)
  echo "== $name: $*" | tee -a "$LOG"
  set +e; "$@" 2>&1 | tee "$OUT/$name.log"; local code=${PIPESTATUS[0]}; set -e
  echo "== $name: exit $code, $(( $(date +%s) - t0 )) s" | tee -a "$LOG"
  if [ "$code" -ne 0 ] && ! { [ "$name" = select ] && [ "$code" -eq 3 ]; }; then exit "$code"; fi
}
SHARD="$KIND"
step plan "$PY" "$HERE/make_plan.py" --harness "$EXPORT" --kind "$KIND" --out "$OUT/PLAN.json"
H="$(tail -1 "$OUT/plan.log" | awk '{print $2}')"
step label "$PY" "$HERE/distill_screen.py" run --harness "$EXPORT" --plan "$OUT/PLAN.json" \
  --expect-sha256 "$H" --shard "$SHARD" --checkpoint "$CK" --out-dir "$OUT/shard" --heartbeat 300
step accept "$PY" "$HERE/distill_accept.py" --plan "$OUT/PLAN.json" --expect-sha256 "$H" \
  --shard-dir "$SHARD=$OUT/shard"
step dataset "$PY" "$HERE/distill_dataset.py" --harness "$EXPORT" --plan "$OUT/PLAN.json" \
  --expect-sha256 "$H" --checkpoint "$CK" --shard-dir "$SHARD=$OUT/shard" --out-dir "$OUT/dataset"
step finetune "$PY" "$HERE/distill_finetune.py" --harness "$EXPORT" --plan "$OUT/PLAN.json" \
  --expect-sha256 "$H" --checkpoint "$CK" --dataset "$OUT/dataset" --out-dir "$OUT/finetune"
step select "$PY" "$HERE/distill_eval.py" select --harness "$EXPORT" --plan "$OUT/PLAN.json" \
  --expect-sha256 "$H" --checkpoint "$CK" --dataset "$OUT/dataset" --finetune "$OUT/finetune"
S="$(shasum -a 256 "$OUT/finetune/SELECTION.json" | awk '{print $1}')"
step heldout "$PY" "$HERE/distill_eval.py" heldout --harness "$EXPORT" --plan "$OUT/PLAN.json" \
  --expect-sha256 "$H" --checkpoint "$CK" --dataset "$OUT/dataset" --finetune "$OUT/finetune" \
  --expect-selection-sha256 "$S"
step gateplan "$PY" "$HERE/gate/make_plan.py" --out-dir "$GATE_DIR" --gate "$GATE" \
  --registered-in "a Mac rehearsal of the gate's scripts ($KIND), never evidence" \
  --seed0 "$GATE_SEED0" --games-per-pair "$GATE_GAMES" --shards 1 --max-hours 1 \
  --finetune "$OUT/finetune" --expect-selection-sha256 "$S" --local
G="$(awk '{print $1}' "$GATE_DIR/PLAN.json.sha256")"
step gateplay "$PY" "$GATE_DIR/play_local_from_plan.py" "$GATE_DIR/PLAN.json" --expect-sha256 "$G"
step gatescore "$PY" "$GATE_DIR/score_from_plan.py" --expect-sha256 "$G"
echo "plan sha256 $H; selection sha256 $S; gate plan sha256 $G" | tee -a "$LOG"
