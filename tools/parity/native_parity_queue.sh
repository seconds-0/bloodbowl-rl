#!/usr/bin/env bash
# Torch-vs-native parity recorder queue (rig RTX 2070), D399/D400 open item.
#
# Waits until chain 34's exam has finished (EXAMS_DONE_C34_BOTH_SEEDS in
# /home/rache/exam_c34.log, chain 34 unit and exam waiter inactive, and no
# trainer or exam process running), takes the shared kt-gpu.lock, records
# chain 30 through the native CUDA policy with tools/parity/record_native.py,
# releases the lock on every exit path, writes $OUT/RESULT_COMPLETE.json and
# prints QUEUE-PARITY-DONE.
#
# Runs (both seats of envs 0-3 in each run):
#   md4096_s42  seed 42, default decision budget, 1000 steps (natural terminals)
#   md150_s43   seed 43, max_decisions 150, 600 steps (frequent truncation terminals)
#
# Never writes into the live checkout: the live venv interpreter and _C are used
# read-only, the checkpoint is copied into $OUT, the shim builds into $OUT/build.
# GPU phase (after the lock) is capped at MAX_GPU_SEC (default 1200 s).
#
# DRY_RUN=1: CPU only. Same gate and lock code, but the recorder uses its numpy
# backend, the lock is a scratch file, and OUT / LOCK / EXAM_LOG / TRAIN_UNIT /
# WAIT_UNIT / CONSUMER_PATTERN / PGREP_X / GATE_POLLS / POLL_SEC / LOCK_WAIT /
# MAX_GPU_SEC / DRY_STEPS / RECORDER_EXTRA may be overridden. With DRY_RUN=0
# none of those overrides is accepted.
set -uo pipefail

DRY_RUN=${DRY_RUN:-0}
PARITY=/home/rache/bbparity
LIVE=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
LIVE_PY=$LIVE/vendor/PufferLib/.venv/bin/python        # read-only use
OCEAN=$LIVE/vendor/PufferLib/ocean/bloodbowl            # the env TU _C compiled
NV=$LIVE/vendor/PufferLib/.venv/lib/python3.11/site-packages/nvidia
# The rig's system cuBLAS 12.4 leaves a WSL process with no CUDA device; resolve
# every CUDA library from the venv the 4.0 trainer uses.
NATIVE_LD_LIBRARY_PATH=$NV/cuda_runtime/lib:$NV/cublas/lib:$NV/curand/lib:$NV/cusolver/lib:$NV/cusparse/lib:$NV/nvjitlink/lib:$NV/nccl/lib:$NV/cudnn/lib
# The source tree this script was installed in (src, src-v2, ...).
SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
CKPT_LIVE=$LIVE/vendor/PufferLib/checkpoints/bloodbowl/1789413829676/0000002999975936.bin
EXPECT_SHA=41ecd998b45613f7cb5e3b7a92b85811473abadc9f099f4baa9f307b42a6dc0b
LOCK_TAG=bloodbowl-rl:parity-native-20260916-v2
EXAM_MARKER=EXAMS_DONE_C34_BOTH_SEEDS
REAL_LOCK=/home/rache/kt-e2e/kt-gpu.lock
REAL_EXAM_LOG=/home/rache/exam_c34.log
REAL_TRAIN_UNIT=r0chain34-cont30-rr1.service
REAL_WAIT_UNIT=exam-c34-waiter.service
REAL_CONSUMERS='[p]uffer_cuda_runtime.py train|[p]uffer train|[e]val_vs_contact_bot|[r]ecord_native.py --backend native'
RUNS=("md4096_s42 42 1000 4096" "md150_s43 43 600 150")

if [ "$DRY_RUN" = 1 ]; then
    OUT=${OUT:-$PARITY/dryrun/default}
    L=${LOCK:-$OUT/dry-gpu.lock}
    EXAM_LOG=${EXAM_LOG:-$OUT/fake_exam_c34.log}
    TRAIN_UNIT=${TRAIN_UNIT:-$REAL_TRAIN_UNIT}
    WAIT_UNIT=${WAIT_UNIT:-$REAL_WAIT_UNIT}
    CONSUMERS=${CONSUMER_PATTERN:-$REAL_CONSUMERS}
    PGREP_X=${PGREP_X-puffer}
    GATE_POLLS=${GATE_POLLS:-30}
    POLL_SEC=${POLL_SEC:-1}
    LOCK_WAIT=${LOCK_WAIT:-60}
    MAX_GPU_SEC=${MAX_GPU_SEC:-120}
    DRY_STEPS=${DRY_STEPS:-120}
    RUNS=("dry_md4096_s42 42 $DRY_STEPS 4096" "dry_md60_s43 43 $DRY_STEPS 60")
    BACKEND=dry-run
else
    for v in OUT LOCK EXAM_LOG TRAIN_UNIT WAIT_UNIT CONSUMER_PATTERN PGREP_X GATE_POLLS \
             POLL_SEC LOCK_WAIT MAX_GPU_SEC DRY_STEPS RECORDER_EXTRA UNIT_STATE_DIR; do
        if [ -n "${!v+x}" ]; then
            echo "QUEUE-ABORT $v may only be overridden with DRY_RUN=1" >&2
            exit 6
        fi
    done
    OUT=$PARITY/native-20260916
    L=$REAL_LOCK
    EXAM_LOG=$REAL_EXAM_LOG
    TRAIN_UNIT=$REAL_TRAIN_UNIT
    WAIT_UNIT=$REAL_WAIT_UNIT
    CONSUMERS=$REAL_CONSUMERS
    PGREP_X=puffer
    GATE_POLLS=1440        # 60 s polls -> 24 h bound
    POLL_SEC=60
    LOCK_WAIT=7200
    MAX_GPU_SEC=1200
    BACKEND=native
fi
RECORDER_EXTRA=${RECORDER_EXTRA:-}
UNIT_STATE_DIR=${UNIT_STATE_DIR:-}

# Refuse any output path inside the live checkout, and a dry run on the real lock.
live_real=$(realpath -m "$LIVE")
for p in "$OUT" "$L" "$SRC"; do
    case "$(realpath -m "$p")/" in
        "$live_real"/*)
            echo "QUEUE-ABORT $p resolves inside the live checkout $LIVE" >&2
            exit 6 ;;
    esac
done
if [ "$DRY_RUN" = 1 ] && [ "$(realpath -m "$L")" = "$(realpath -m "$REAL_LOCK")" ]; then
    echo "QUEUE-ABORT a dry run may not take the shared kt-gpu.lock" >&2
    exit 6
fi
if [ -e "$OUT/RESULT_COMPLETE.json" ]; then
    echo "QUEUE-ABORT $OUT/RESULT_COMPLETE.json already exists; refusing to overwrite a finished result" >&2
    exit 2
fi
mkdir -p "$OUT"
QLOG=$OUT/queue.log
log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$QLOG"; }

LOCKED=0
CHILD=
release_lock() {
    local rc=$1
    if [ "$LOCKED" = 1 ]; then
        flock -u 9 2>/dev/null || true
        exec 9>&- 2>/dev/null || true
        echo "$(date -u +%FT%TZ) $$ released(exit $rc) $LOCK_TAG" >> "$L.log"
        LOCKED=0
        log "lock released (exit $rc)"
    fi
}
on_exit() {
    local rc=$?
    release_lock "$rc"
}
on_signal() {
    local sig=$1 code=$2
    log "QUEUE-ABORT signal $sig"
    if [ -n "$CHILD" ] && kill -0 "$CHILD" 2>/dev/null; then
        kill -TERM "$CHILD" 2>/dev/null
        wait "$CHILD" 2>/dev/null
    fi
    exit "$code"
}
trap on_exit EXIT
trap 'on_signal INT 130' INT
trap 'on_signal TERM 143' TERM
trap 'on_signal HUP 129' HUP

log "queue start pid=$$ dry_run=$DRY_RUN backend=$BACKEND out=$OUT lock=$L"
log "gate: exam_log=$EXAM_LOG marker=$EXAM_MARKER units=$TRAIN_UNIT,$WAIT_UNIT consumers=$CONSUMERS"

# ------------------------------------------------------------- 0. preflight
fail() { log "QUEUE-ABORT $2"; exit "$1"; }
[ -x "$LIVE_PY" ] || fail 7 "live venv interpreter missing: $LIVE_PY"
[ -f "$SRC/tools/parity/record_native.py" ] || fail 7 "recorder missing under $SRC"
[ -f "$OCEAN/bloodbowl.h" ] || fail 7 "env snapshot missing: $OCEAN"
mkdir -p "$OUT/build"
if [ ! -f "$OUT/build/libbbplay.so" ]; then
    log "building the bbplay shim from $OCEAN (CPU, nice 19)"
    if ! nice -n 19 cc -std=c11 -O2 -g -ffp-contract=off -fPIC -shared \
            -Wall -Wextra -Wno-unused-function \
            -I"$LIVE/engine/include" -I"$OCEAN" \
            "$SRC/play_harness/native/bbplay.c" -o "$OUT/build/libbbplay.so.tmp" -lm \
            >> "$QLOG" 2>&1; then
        fail 7 "bbplay shim build failed"
    fi
    mv "$OUT/build/libbbplay.so.tmp" "$OUT/build/libbbplay.so"
fi
log "shim sha256 $(sha256sum "$OUT/build/libbbplay.so" | cut -d' ' -f1)"
log "env snapshot bloodbowl.h $(sha256sum "$OCEAN/bloodbowl.h" | cut -d' ' -f1) binding.c $(sha256sum "$OCEAN/binding.c" | cut -d' ' -f1)"
if [ ! -f "$OUT/c30.bin" ]; then
    nice -n 19 cp "$CKPT_LIVE" "$OUT/c30.bin.tmp" && mv "$OUT/c30.bin.tmp" "$OUT/c30.bin" \
        || fail 7 "checkpoint copy failed"
fi
have_sha=$(sha256sum "$OUT/c30.bin" | cut -d' ' -f1)
[ "$have_sha" = "$EXPECT_SHA" ] || fail 7 "checkpoint sha256 $have_sha != $EXPECT_SHA"
log "checkpoint copy verified $have_sha"

# ------------------------------------------------------------- 1. wait gate
unit_state() {
    # Dry runs may stand in a file for a unit's state (UNIT_STATE_DIR/<unit>).
    if [ -n "$UNIT_STATE_DIR" ] && [ -f "$UNIT_STATE_DIR/$1" ]; then
        cat "$UNIT_STATE_DIR/$1"
        return
    fi
    systemctl --user is-active "$1" 2>/dev/null || true
}
gpu_consumers() {
    { pgrep -f "$CONSUMERS"
      [ -n "$PGREP_X" ] && pgrep -x "$PGREP_X"; } 2>/dev/null | sort -u | tr '\n' ' '
}
is_active() { case "$1" in active|activating|reloading|deactivating) return 0 ;; esac; return 1; }
last=""
ready=0
for i in $(seq 1 "$GATE_POLLS"); do
    ts=$(unit_state "$TRAIN_UNIT"); ws=$(unit_state "$WAIT_UNIT")
    if grep -q "$EXAM_MARKER" "$EXAM_LOG" 2>/dev/null; then mk=1; else mk=0; fi
    cons=$(gpu_consumers)
    state="train=$ts waiter=$ws marker=$mk consumers=[${cons}]"
    if [ "$state" != "$last" ]; then log "gate poll $i: $state"; last=$state; fi
    if ! is_active "$ts" && ! is_active "$ws"; then
        if [ "$mk" = 1 ] && [ -z "$cons" ]; then ready=1; break; fi
        if [ "$mk" = 0 ]; then
            fail 3 "chain 34 unit and exam waiter both inactive without $EXAM_MARKER; no GPU work"
        fi
    fi
    sleep "$POLL_SEC" &
    CHILD=$!
    wait "$CHILD"
    CHILD=
done
[ "$ready" = 1 ] || fail 4 "gate not satisfied after $GATE_POLLS polls"
log "gate open: $EXAM_MARKER present, units inactive, no trainer or exam running"

# ------------------------------------------------------------- 2. GPU lock
exec 9>>"$L"
flock -w "$LOCK_WAIT" 9 &
CHILD=$!
wait "$CHILD"
lock_rc=$?
CHILD=
# flock on an inherited fd from a background child still locks the open file
# description this shell holds, so the lock stays held after the child exits.
[ "$lock_rc" = 0 ] || fail 75 "$L busy for ${LOCK_WAIT}s"
LOCKED=1
echo "$(date -u +%FT%TZ) $$ acquired(lock=$L) $LOCK_TAG (~20 min GPU cap)" >> "$L.log"
log "lock acquired $L"
cons=$(gpu_consumers)
[ -z "$cons" ] || fail 5 "GPU consumer appeared after lock: $cons"
if [ "$DRY_RUN" != 1 ]; then
    nvidia-smi --query-gpu=name,memory.used,memory.total,temperature.gpu,utilization.gpu \
        --format=csv,noheader >> "$QLOG" 2>&1 || true
fi

# ------------------------------------------------------------- 3. record
DEADLINE=$(( $(date +%s) + MAX_GPU_SEC ))
read -r -a EXTRA <<< "$RECORDER_EXTRA"
for spec in "${RUNS[@]}"; do
    read -r name seed steps md <<< "$spec"
    remaining=$(( DEADLINE - $(date +%s) ))
    [ "$remaining" -gt 0 ] || fail 124 "GPU cap of ${MAX_GPU_SEC}s reached before run $name"
    log "run $name: seed=$seed steps=$steps max_decisions=$md backend=$BACKEND (cap ${remaining}s)"
    if [ "$BACKEND" = native ]; then
        cmd=(env CUDA_VISIBLE_DEVICES=0 LD_LIBRARY_PATH="$NATIVE_LD_LIBRARY_PATH"
             OMP_NUM_THREADS=4 PYTHONDONTWRITEBYTECODE=1 BBPLAY_LIB="$OUT/build/libbbplay.so"
             nice -n 10 "$LIVE_PY" "$SRC/tools/parity/record_native.py" --backend native
             --live "$LIVE" --num-threads 4)
    else
        cmd=(env OMP_NUM_THREADS=1 PYTHONDONTWRITEBYTECODE=1 BBPLAY_LIB="$OUT/build/libbbplay.so"
             nice -n 19 "$LIVE_PY" "$SRC/tools/parity/record_native.py" --backend dry-run
             --live "$LIVE")
    fi
    cmd+=(--checkpoint "$OUT/c30.bin" --expect-sha256 "$EXPECT_SHA" --out "$OUT/$name"
          --trace "$name" --seed "$seed" --steps "$steps" --max-decisions "$md"
          --envs 0,1,2,3 "${EXTRA[@]}")
    timeout --kill-after=30 "$remaining" "${cmd[@]}" >> "$OUT/$name.log" 2>&1 &
    CHILD=$!
    wait "$CHILD"
    rc=$?
    CHILD=
    log "run $name: rc=$rc $(tail -1 "$OUT/$name.log" | cut -c1-300)"
    if [ "$rc" = 124 ] || [ "$rc" = 137 ]; then
        fail 124 "run $name hit the ${MAX_GPU_SEC}s GPU cap"
    fi
    [ "$rc" = 0 ] || fail "$rc" "run $name failed rc=$rc (see $OUT/$name.log)"
done

# ------------------------------------------------------------- 4. summary
# Publication is part of success: the job reports done only once
# RESULT_COMPLETE.json exists, and the lock is released after that check (a
# publication failure releases through the EXIT trap with its own code).
"$LIVE_PY" - "$OUT" "$DRY_RUN" "$0" "$SRC" "${RUNS[@]}" <<'PY' | tee -a "$QLOG"
import hashlib, json, os, sys, time
out, dry, script, src, *runs = sys.argv[1:]
def sha(p):
    return hashlib.sha256(open(p, "rb").read()).hexdigest()
doc = {"schema": "bbplay-native-parity-queue-v1", "dry_run": dry == "1",
       "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
       "queue_script_sha256": sha(script), "runs": {}}
src_commit = os.path.join(src, "SOURCE_COMMIT")
doc["source_commit"] = open(src_commit).read().strip() if os.path.exists(src_commit) else None
for spec in runs:
    name = spec.split()[0]
    run = json.load(open(os.path.join(out, name, "RUN.json")))
    doc["runs"][name] = {"fixtures": len(run["fixtures"]),
                         "consistency_violations": run["consistency_violations"],
                         "ms_per_step": run["ms_per_step"],
                         "terminal_steps": sum(f["terminal_steps"] for f in run["fixtures"]),
                         "backend": run["backend"],
                         "module_sha256": run.get("provenance", {}).get("module_sha256")}
tmp = os.path.join(out, "RESULT_COMPLETE.json.tmp")
with open(tmp, "w") as f:
    json.dump(doc, f, indent=1, sort_keys=True)
os.replace(tmp, os.path.join(out, "RESULT_COMPLETE.json"))
print(json.dumps(doc["runs"], sort_keys=True))
PY
summary_rc=${PIPESTATUS[0]}
[ "$summary_rc" = 0 ] || fail 8 "result publication failed rc=$summary_rc; no RESULT_COMPLETE.json"
[ -f "$OUT/RESULT_COMPLETE.json" ] || fail 8 "RESULT_COMPLETE.json missing after publication"
release_lock 0
log "QUEUE-PARITY-DONE result=$OUT/RESULT_COMPLETE.json"
echo QUEUE-PARITY-DONE
