#!/usr/bin/env bash
# PufferLib 4.0 vs 5.0-port throughput benchmark queue (rig RTX 2070).
#
# Waits until chain 32 (unit r0chain32-rr1-s44) and its exam
# (exam-c32-waiter) are finished, takes the shared kt-gpu.lock, then runs
# timed probes, each after the GPU cools below COOL_BELOW:
#   ref40_rr1       4.0 live build (scratch copy), chain 30 layout: 4 banks x 0.12,
#                   scripted contact bot at bank tag 4, replay_ratio 1.0
#   p5_async0_rr1   5.0 port, base.async=0, replay_ratio 1.0
#   p5_async1_rr1   5.0 port, base.async=1, replay_ratio 1.0
#   (QUEUE_EXTRA=1) p5_async0_rr025, ref40_rr025
# Each probe: warmup, then a WINDOW-second measurement, hard kill at KILL_TEMP.
# Releases the lock, writes $OUT/SUMMARY.json, prints QUEUE-BENCH-DONE.
#
# Never writes into the live checkout: the 4.0 probe runs from $REF40 with the
# live venv interpreter used read-only, and all outputs land under $OUT.
#
# DRY_RUN=1: no wait gate, no lock, fake nvidia-smi, fake CPU-only trainers,
# short timings, outputs under $BENCH/dryrun.
set -uo pipefail

BENCH=${BENCH:-/home/rache/bbpuffer5/bench}
DRY_RUN=${DRY_RUN:-0}
QUEUE_EXTRA=${QUEUE_EXTRA:-0}

LIVE=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
LIVE_VENV_BIN=$LIVE/vendor/PufferLib/.venv/bin          # read-only use
LIVE_PY=$LIVE_VENV_BIN/python
REF40=${REF40:-/home/rache/bbpuffer5/ref40}
REF40_PUFFER=$REF40/vendor/PufferLib
REF40_C=$REF40_PUFFER/pufferlib/_C.cpython-311-x86_64-linux-gnu.so
P5=${P5:-/home/rache/bbpuffer5/PufferLib5}
NV=${NV:-$LIVE/vendor/PufferLib/.venv/lib/python3.11/site-packages/nvidia}
NCCL_LIB=$NV/nccl/lib
# The rig's system cuBLAS 12.4 leaves a WSL process with no CUDA device, so the
# 5.0 binary must resolve every CUDA library from the venv the 4.0 trainer uses.
P5_LD_LIBRARY_PATH=$NV/cuda_runtime/lib:$NV/cublas/lib:$NV/cusolver/lib:$NV/curand/lib:$NV/cusparse/lib:$NV/nvjitlink/lib:$NCCL_LIB
POOL=$BENCH/pool_c30
WARM=$BENCH/c30.bin
PROBE_PY=$BENCH/bench_probe.py
LAUNCH40=$BENCH/ref40_launch.py

L=/home/rache/kt-e2e/kt-gpu.lock
TRAIN_UNIT=r0chain32-rr1-s44.service
WAIT_UNIT=exam-c32-waiter.service
EXAM_LOG=/home/rache/exam_c32.log
EXAM_MARKER=EXAMS_DONE_C32_BOTH_SEEDS
GATE_POLLS=${GATE_POLLS:-1440}      # 60 s polls -> 24 h bound

WARMUP_40=${WARMUP_40:-150}
WARMUP_P5=${WARMUP_P5:-90}
WINDOW=${WINDOW:-120}
COOL_BELOW=${COOL_BELOW:-58}
KILL_TEMP=${KILL_TEMP:-86}
SAMPLE_INTERVAL=${SAMPLE_INTERVAL:-5}
COOL_POLL=${COOL_POLL:-15}
COOL_TIMEOUT=${COOL_TIMEOUT:-1800}
STARTUP_TIMEOUT=${STARTUP_TIMEOUT:-900}
REF40_TOTAL_TIMESTEPS=${REF40_TOTAL_TIMESTEPS:-3000000000}    # chain 30 schedule
P5_TOTAL_TIMESTEPS=${P5_TOTAL_TIMESTEPS:-100000000000}
NVSMI=${NVSMI:-nvidia-smi}
OUT=${OUT:-$BENCH}

if [ "$DRY_RUN" = 1 ]; then
    OUT=$BENCH/dryrun
    WARMUP_40=2; WARMUP_P5=2; WINDOW=5; SAMPLE_INTERVAL=1
    COOL_POLL=1; COOL_TIMEOUT=10; STARTUP_TIMEOUT=20
    mkdir -p "$OUT/fakebin"
    cat > "$OUT/fakebin/nvidia-smi" <<'EOF'
#!/bin/sh
case "$*" in
  *name*) echo "FAKE GPU (dry run), 0.0, 45, 1234, 8192";;
  *) echo "45, 1234, 50";;
esac
EOF
    chmod +x "$OUT/fakebin/nvidia-smi"
    NVSMI=$OUT/fakebin/nvidia-smi
fi
# Refuse any output or scratch path that resolves inside the live checkout.
live_real=$(realpath -m "$LIVE")
for p in "$OUT" "$BENCH" "$REF40" "$P5"; do
    case "$(realpath -m "$p")/" in
        "$live_real"/*)
            echo "QUEUE-ABORT $p resolves inside the live checkout $LIVE" >&2
            exit 6 ;;
    esac
done
mkdir -p "$OUT"
QLOG=$OUT/queue.log

log() { echo "$(date -u +%FT%TZ) $*" | tee -a "$QLOG"; }

LOCKED=0
release_lock() {
    local rc=$1
    if [ "$LOCKED" = 1 ]; then
        flock -u 9 2>/dev/null || true
        echo "$(date -u +%FT%TZ) $$ released(exit $rc) bloodbowl-rl:puffer5-bench" >> "$L.log"
        LOCKED=0
        log "lock released (exit $rc)"
    fi
}
on_exit() {
    local rc=$?
    release_lock "$rc"
}
trap on_exit EXIT
trap 'log "QUEUE-ABORT signal"; exit 130' INT TERM

if [ "$DRY_RUN" != 1 ] && [ -e "$OUT/SUMMARY.json" ]; then
    log "QUEUE-ABORT $OUT/SUMMARY.json already exists; refusing to overwrite a finished benchmark"
    exit 2
fi
log "queue start pid=$$ dry_run=$DRY_RUN extra=$QUEUE_EXTRA out=$OUT"

# ---------------------------------------------------------------- 1. wait gate
unit_state() { systemctl --user is-active "$1" 2>/dev/null || true; }
gpu_consumers() {
    { pgrep -f '[p]uffer_cuda_runtime.py train|[p]uffer train|[e]val_vs_contact_bot'
      pgrep -x puffer; } 2>/dev/null | sort -u | tr '\n' ' '
}
if [ "$DRY_RUN" != 1 ]; then
    last=""
    ready=0
    for i in $(seq 1 "$GATE_POLLS"); do
        ts=$(unit_state "$TRAIN_UNIT"); ws=$(unit_state "$WAIT_UNIT")
        if grep -q "$EXAM_MARKER" "$EXAM_LOG" 2>/dev/null; then mk=1; else mk=0; fi
        cons=$(gpu_consumers)
        state="train=$ts waiter=$ws marker=$mk consumers=[${cons}]"
        if [ "$state" != "$last" ]; then log "gate: $state"; last=$state; fi
        t_active=0; w_active=0
        [ "$ts" = active ] || [ "$ts" = activating ] && t_active=1
        [ "$ws" = active ] || [ "$ws" = activating ] && w_active=1
        if [ "$t_active" = 0 ] && [ "$w_active" = 0 ]; then
            if [ "$mk" = 1 ] && [ -z "$cons" ]; then ready=1; break; fi
            if [ "$mk" = 0 ]; then
                log "QUEUE-ABORT chain 32 unit and exam waiter both inactive without $EXAM_MARKER"
                exit 3
            fi
        fi
        sleep 60
    done
    if [ "$ready" != 1 ]; then
        log "QUEUE-ABORT gate not satisfied after $GATE_POLLS polls"
        exit 4
    fi
    log "gate open: chain 32 and its exam are done, no trainer running"

    # ------------------------------------------------------------ 2. GPU lock
    exec 9>>"$L"
    if ! flock -w 7200 9; then
        log "QUEUE-ABORT kt-gpu.lock busy for 2h"
        exit 75
    fi
    LOCKED=1
    echo "$(date -u +%FT%TZ) $$ acquired(lock=$L) bloodbowl-rl:puffer5-bench (~60 min)" >> "$L.log"
    log "lock acquired $L"
    cons=$(gpu_consumers)
    if [ -n "$cons" ]; then
        log "QUEUE-ABORT GPU consumer appeared after lock: $cons"
        exit 5
    fi
else
    log "DRY_RUN: skipping wait gate and lock"
fi

# ------------------------------------------------------------- 3. preflight
if [ -f "$REF40/tools/cpu_cap.sh" ]; then
    # shellcheck disable=SC1091
    . "$REF40/tools/cpu_cap.sh"
fi
python3 "$PROBE_PY" preflight --out "$OUT/preflight.json" --nvidia-smi "$NVSMI" \
    --file "ref40_C=$REF40_C" --file "p5_puffer=$P5/puffer" \
    --file "p5_bloodbowl_ini=$P5/config/bloodbowl.ini" \
    --file "warm_checkpoint=$WARM" --file "pool_manifest=$POOL/league_seeds.json" \
    --file "ref40_launch=$LAUNCH40" --file "bench_probe=$PROBE_PY" \
    --file "queue_script=$0" --file "live_py=$LIVE_PY" \
    --git "p5=$P5" --git "live=$LIVE" --df "$BENCH" \
    --extra "dry_run=$DRY_RUN" --extra "warmup_40=$WARMUP_40" \
    --extra "warmup_p5=$WARMUP_P5" --extra "window=$WINDOW" \
    --extra "cool_below=$COOL_BELOW" --extra "kill_temp=$KILL_TEMP" \
    --extra "omp_num_threads=${OMP_NUM_THREADS:-}" --extra "nccl_lib=$NCCL_LIB" \
    --extra "p5_ld_library_path=$P5_LD_LIBRARY_PATH" \
    >> "$QLOG" 2>&1 || log "preflight recorder failed (continuing)"

p5_libs_check() {
    local resolved bad
    if ! resolved=$(LD_LIBRARY_PATH="$P5_LD_LIBRARY_PATH" ldd "$P5/puffer" 2>&1); then
        log "p5 libs: ldd failed: $(echo $resolved)"
        return 1
    fi
    bad=$(printf '%s\n' "$resolved" | awk -v nv="$NV/" '
        /not found/ { print $1 " => not found"; next }
        /libcudart|libcublas|libcusolver|libcurand|libcusparse|libnvJitLink|libnccl/ {
            if (index($3, nv) != 1) print $1 " => " $3
        }')
    if [ -n "$bad" ]; then
        log "p5 libs outside $NV: $(echo $bad)"
        return 1
    fi
    log "p5 libs: every CUDA library resolves under $NV"
}
if [ "$DRY_RUN" != 1 ] && ! p5_libs_check; then
    log "QUEUE-ABORT the 5.0 binary would load CUDA libraries from outside the venv"
    exit 7
fi

# ---------------------------------------------------------------- 4. probes
REF40_ARGS=()
ref40_args() {
    local rr=$1 name=$2
    REF40_ARGS=(
        train bloodbowl --tag "bench-$name"
        --seed 42 --train.seed 42 --selfplay.seed 42 --env.seed 42 --train.gpus 1
        --eval-episodes 10000 --checkpoint-interval 1000000
        --checkpoint-dir "$OUT/ckpt-$name" --log-dir "$OUT/logs-$name"
        --policy.hidden-size 512 --policy.num-layers 3 --policy.expansion-factor 1
        --vec.total-agents 2048 --vec.num-buffers 2 --vec.num-threads 16
        --env.reward-td 0.4 --env.reward-win 0.6 --env.reward-draw 0
        --env.reward-setup-done 0 --env.reward-setup-autofix 0
        --env.reward-ball-gain 0.05 --env.reward-ball-loss 0
        --env.reward-dist-ball 0.02 --env.reward-dist-endzone 0.04
        --env.reward-injury-inflicted 0 --env.reward-injury-taken 0
        --env.reward-send-off 0 --env.reward-kickoff-touchback 0
        --env.reward-surf-taken 0 --env.reward-surf-inflicted 0
        --env.reward-k-kd 0.1 --env.reward-k-value 0.5 --env.reward-k-self-injury 0
        --env.reward-k-ball 0.15 --env.reward-k-seq 0.03 --env.reward-k-turnover 0.15
        --env.reward-possession 0.015 --env.reward-k-assist 0 --env.reward-rush-cost 0.015
        --env.reward-carrier-exposure 0 --env.reward-carrier-exposure-soft 0
        --env.reward-carrier-threat 0 --env.reward-defensive-threat 0
        --env.reward-defensive-threat-soft 0 --env.reward-statmatch-scale 0
        --env.reward-injury-value-scaled 0
        --env.demo-reset-pct 0 --env.demo-endzone-maxdist 0 --env.demo-pickup-maxdist 0
        --env.demo-postkick-maxturn 0 --env.demo-pass-maxrange 0
        --train.total-timesteps "$REF40_TOTAL_TIMESTEPS"
        --train.learning-rate 0.00028 --train.ent-coef 0.009
        --train.gamma 0.999 --train.gae-lambda 0.95 --train.horizon 64
        --train.minibatch-size 16384 --train.anneal-lr 1 --train.min-lr-ratio 0.1
        --train.replay-ratio "$rr" --train.clip-coef 0.2 --train.vf-coef 1.0
        --train.vf-clip-coef 0.5 --train.max-grad-norm 1.5 --train.anneal-ent-coef 1
        --train.min-ent-coef-ratio 0.1 --train.update-epochs 1 --train.beta1 0.95
        --train.beta2 0.999 --train.eps 0.000000000001
        --selfplay.enabled 1 --selfplay.league-preseed "$POOL"
        --selfplay.swap-winrate 1.1 --selfplay.opp-timeout-steps 30000000000
        --selfplay.snapshot-interval 1000000000000
        --vec.num-frozen-banks 4 --vec.frozen-bank-pct 0.12
        --load-model-path "$WARM"
        --env.scripted-opponent 1 --env.scripted-opponent-type 0
        --env.scripted-opponent-team 1 --env.scripted-bank-tag 4
    )
}

PROBES=()
run_probe() {   # name kind warmup cwd -- env... -- cmd...
    local name=$1 kind=$2 warmup=$3 cwd=$4
    shift 4
    local envs=()
    while [ "$#" -gt 0 ] && [ "$1" != "--" ]; do envs+=(--env "$1"); shift; done
    shift
    PROBES+=("$OUT/$name.json")
    log "probe $name: waiting for GPU below ${COOL_BELOW} C"
    if ! python3 "$PROBE_PY" wait-cool --below "$COOL_BELOW" --poll "$COOL_POLL" \
            --timeout "$COOL_TIMEOUT" --nvidia-smi "$NVSMI" >> "$QLOG" 2>&1; then
        python3 "$PROBE_PY" skip --name "$name" --kind "$kind" --out "$OUT/$name.json" \
            --reason "GPU not below ${COOL_BELOW} C after ${COOL_TIMEOUT}s" >> "$QLOG" 2>&1
        log "probe $name SKIPPED (not cool)"
        return 0
    fi
    log "probe $name: start (warmup ${warmup}s, window ${WINDOW}s)"
    python3 "$PROBE_PY" run --name "$name" --kind "$kind" \
        --log "$OUT/$name.log" --out "$OUT/$name.json" \
        --metrics-jsonl "$OUT/$name.metrics.jsonl" --cwd "$cwd" \
        --warmup "$warmup" --window "$WINDOW" --sample-interval "$SAMPLE_INTERVAL" \
        --kill-temp "$KILL_TEMP" --startup-timeout "$STARTUP_TIMEOUT" \
        --nvidia-smi "$NVSMI" "${envs[@]}" -- "$@" >> "$QLOG" 2>&1
    local rc=$?
    log "probe $name: finished rc=$rc $(grep -a 'PROBE_RESULT' "$QLOG" | tail -1 | cut -c1-400)"
    return 0
}

probe_ref40() {  # name rr
    local name=$1 rr=$2
    ref40_args "$rr" "$name"
    if [ "$DRY_RUN" = 1 ]; then
        run_probe "$name" ref40 "$WARMUP_40" "$OUT" -- \
            python3 "$PROBE_PY" fake-trainer --kind ref40 --duration 10
    else
        run_probe "$name" ref40 "$WARMUP_40" "$REF40_PUFFER" \
            "CUDA_VISIBLE_DEVICES=0" "PATH=$LIVE_VENV_BIN:$PATH" \
            "PYTHONDONTWRITEBYTECODE=1" \
            "PYTHONPATH=$REF40_PUFFER" "REF40_TOOLS=$REF40/tools" \
            "BENCH40_EVIDENCE=$OUT/$name.cuda-runtime.json" -- \
            "$LIVE_PY" "$LAUNCH40" "${REF40_ARGS[@]}"
    fi
}

probe_p5() {  # name async rr
    local name=$1 async=$2 rr=$3
    if [ "$DRY_RUN" = 1 ]; then
        run_probe "$name" p5 "$WARMUP_P5" "$OUT" -- \
            python3 "$PROBE_PY" fake-trainer --kind p5 --duration 10
    else
        run_probe "$name" p5 "$WARMUP_P5" "$P5" \
            "CUDA_VISIBLE_DEVICES=0" "LD_LIBRARY_PATH=$P5_LD_LIBRARY_PATH" -- \
            ./puffer train "--base.async=$async" \
            "--base.checkpoint_dir=$OUT/ckpt-$name" "--base.log_dir=$OUT/logs-$name" \
            --base.eval_episodes=0 --base.checkpoint_interval=1000000 \
            "--base.load_model_path=$WARM" "--selfplay.league_preseed=$POOL" \
            "--train.replay_ratio=$rr" "--train.total_timesteps=$P5_TOTAL_TIMESTEPS"
    fi
}

probe_ref40 ref40_rr1 1.0
probe_p5 p5_async0_rr1 0 1.0
probe_p5 p5_async1_rr1 1 1.0
if [ "$QUEUE_EXTRA" = 1 ]; then
    probe_p5 p5_async0_rr025 0 0.25
    probe_ref40 ref40_rr025 0.25
fi

left=$(pgrep -f '[r]ef40_launch.py train|[p]uffer train' 2>/dev/null | tr '\n' ' ')
[ -n "$left" ] && log "WARNING leftover probe processes: $left"

# ----------------------------------------------------------------- 5. summary
release_lock 0
SUMMARY_ARGS=()
for p in "${PROBES[@]}"; do SUMMARY_ARGS+=(--probe "$p"); done
python3 "$PROBE_PY" summarize --out "$OUT/SUMMARY.json" --preflight "$OUT/preflight.json" \
    --baseline ref40_rr1 "${SUMMARY_ARGS[@]}" 2>&1 | tee -a "$QLOG"
log "QUEUE-BENCH-DONE summary=$OUT/SUMMARY.json"
echo QUEUE-BENCH-DONE
