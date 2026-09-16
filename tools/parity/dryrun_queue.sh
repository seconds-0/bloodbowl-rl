#!/usr/bin/env bash
# CPU-only dry run of native_parity_queue.sh on the rig: proves the wait gate,
# the lock, release on every exit path, the overwrite refusal and the override
# refusal, with the numpy recorder backend. Never touches the GPU or the shared
# kt-gpu.lock (the queue refuses a dry run on it).
#
#   bash tools/parity/dryrun_queue.sh            # BASE defaults under /home/rache/bbparity
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
Q=$HERE/native_parity_queue.sh
BASE=${BASE:-/home/rache/bbparity/dryrun-$(date -u +%Y%m%dT%H%M%SZ)}
mkdir -p "$BASE"
RESULTS=()
FAILS=0

lock_lines() { grep -c "$1" "$2" 2>/dev/null || true; }
record() {   # name expected_rc got_rc extra_ok note
    local verdict=PASS
    if [ "$2" != "$3" ] || [ "$4" != 1 ]; then verdict=FAIL; FAILS=$((FAILS + 1)); fi
    RESULTS+=("$(printf '%-28s expect=%-4s got=%-4s %s  %s' "$1" "$2" "$3" "$verdict" "$5")")
}

# A. The live chain 34 trainer keeps the gate closed even with the marker present.
S=$BASE/A_live_trainer_blocks; mkdir -p "$S"
echo EXAMS_DONE_C34_BOTH_SEEDS > "$S/examlog"
DRY_RUN=1 OUT=$S EXAM_LOG=$S/examlog GATE_POLLS=3 POLL_SEC=2 bash "$Q" > "$S.out" 2>&1
rc=$?
ok=0; grep -q "train=active" "$S/queue.log" && grep -q "consumers=\[[0-9]" "$S/queue.log" \
    && [ ! -e "$S/dry-gpu.lock.log" ] && ok=1
record A_live_trainer_blocks 4 "$rc" "$ok" "$(grep 'gate poll' "$S/queue.log" | head -1 | cut -d' ' -f2-)"
PRE=$BASE/A_live_trainer_blocks
seed_scenario() {   # reuse A's shim build and verified checkpoint copy
    mkdir -p "$1/build"
    [ -f "$PRE/build/libbbplay.so" ] && cp "$PRE/build/libbbplay.so" "$1/build/"
    [ -f "$PRE/c30.bin" ] && cp "$PRE/c30.bin" "$1/"
}

# B. Gate opens only after the marker appears AND a consumer exits; the queue
#    waits for a lock holder, records, and releases.
S=$BASE/B_gate_lock_success; mkdir -p "$S"; seed_scenario "$S"
: > "$S/examlog"
bash -c 'exec -a parity-dry-consumer sleep 6' &
CONS=$!
( sleep 3; echo EXAMS_DONE_C34_BOTH_SEEDS >> "$S/examlog" ) &
( exec 8>>"$S/dry-gpu.lock"; flock 8; echo "$(date -u +%FT%TZ) holder acquired" >> "$S/dry-gpu.lock.log"; sleep 10; echo "$(date -u +%FT%TZ) holder released" >> "$S/dry-gpu.lock.log" ) &
HOLD=$!
sleep 1
DRY_RUN=1 OUT=$S EXAM_LOG=$S/examlog TRAIN_UNIT=parity-dry-absent-a.service \
    WAIT_UNIT=parity-dry-absent-b.service CONSUMER_PATTERN='[p]arity-dry-consumer' PGREP_X= \
    POLL_SEC=1 GATE_POLLS=60 bash "$Q" > "$S.out" 2>&1
rc=$?
wait "$CONS" "$HOLD" 2>/dev/null
ok=0
if grep -q "marker=1 consumers=\[[0-9]" "$S/queue.log" && [ -f "$S/RESULT_COMPLETE.json" ] \
    && [ "$(lock_lines 'acquired(lock=' "$S/dry-gpu.lock.log")" = 1 ] \
    && [ "$(lock_lines 'released(exit 0)' "$S/dry-gpu.lock.log")" = 1 ] \
    && awk '/holder released/{h=NR} /acquired\(lock=/{a=NR} END{exit !(h && a && a > h)}' "$S/dry-gpu.lock.log"; then
    ok=1
fi
record B_gate_lock_success 0 "$rc" "$ok" "$(tail -1 "$S/queue.log" | cut -d' ' -f2-)"

# C. A finished result is never overwritten (and no lock is taken).
before=$(lock_lines 'acquired(lock=' "$S/dry-gpu.lock.log")
DRY_RUN=1 OUT=$S EXAM_LOG=$S/examlog TRAIN_UNIT=parity-dry-absent-a.service \
    WAIT_UNIT=parity-dry-absent-b.service CONSUMER_PATTERN='[p]arity-dry-consumer' PGREP_X= \
    bash "$Q" > "$BASE/C_refuse_overwrite.out" 2>&1
rc=$?
ok=0; [ "$(lock_lines 'acquired(lock=' "$S/dry-gpu.lock.log")" = "$before" ] && ok=1
record C_refuse_overwrite 2 "$rc" "$ok" "$(tail -1 "$BASE/C_refuse_overwrite.out")"

gate_open_env() {
    echo EXAMS_DONE_C34_BOTH_SEEDS > "$1/examlog"
    echo "DRY_RUN=1 OUT=$1 EXAM_LOG=$1/examlog TRAIN_UNIT=parity-dry-absent-a.service WAIT_UNIT=parity-dry-absent-b.service CONSUMER_PATTERN=[p]arity-dry-consumer-none PGREP_X="
}

# D. Recorder failure propagates and the lock is released.
S=$BASE/D_recorder_failure; mkdir -p "$S"
env $(gate_open_env "$S") RECORDER_EXTRA="--fail-at-step 5" bash "$Q" > "$S.out" 2>&1
rc=$?
ok=0; [ "$(lock_lines 'released(exit 3)' "$S/dry-gpu.lock.log")" = 1 ] && [ ! -e "$S/RESULT_COMPLETE.json" ] && ok=1
record D_recorder_failure 3 "$rc" "$ok" "$(grep -o 'RECORDER-FAIL.*' "$S"/*.log | head -1)"

# E. The GPU cap kills a slow recorder and releases the lock.
S=$BASE/E_runtime_cap; mkdir -p "$S"
env $(gate_open_env "$S") MAX_GPU_SEC=4 DRY_STEPS=600 RECORDER_EXTRA="--dry-step-sleep 0.05" \
    bash "$Q" > "$S.out" 2>&1
rc=$?
ok=0; [ "$(lock_lines 'released(exit 124)' "$S/dry-gpu.lock.log")" = 1 ] && ok=1
record E_runtime_cap 124 "$rc" "$ok" "$(grep 'GPU cap' "$S/queue.log" | tail -1 | cut -d' ' -f2-)"

# F. SIGTERM (what systemctl stop sends) stops the recorder and releases the lock.
S=$BASE/F_sigterm; mkdir -p "$S"
env $(gate_open_env "$S") DRY_STEPS=600 RECORDER_EXTRA="--dry-step-sleep 0.05" \
    bash "$Q" > "$S.out" 2>&1 &
QPID=$!
for _ in $(seq 1 60); do grep -q 'acquired(lock=' "$S/dry-gpu.lock.log" 2>/dev/null && break; sleep 0.5; done
sleep 2
kill -TERM "$QPID"
wait "$QPID"
rc=$?
sleep 1
ok=0
[ "$(lock_lines 'released(exit 143)' "$S/dry-gpu.lock.log")" = 1 ] \
    && ! pgrep -f "[r]ecord_native.py --backend dry-run.*$S" >/dev/null && ok=1
record F_sigterm 143 "$rc" "$ok" "$(grep 'signal' "$S/queue.log" | tail -1 | cut -d' ' -f2-)"

# G. Units inactive without the marker: abort, no GPU work, no lock.
S=$BASE/G_no_marker; mkdir -p "$S"
: > "$S/examlog"
DRY_RUN=1 OUT=$S EXAM_LOG=$S/examlog TRAIN_UNIT=parity-dry-absent-a.service \
    WAIT_UNIT=parity-dry-absent-b.service CONSUMER_PATTERN='[p]arity-dry-consumer-none' PGREP_X= \
    bash "$Q" > "$S.out" 2>&1
rc=$?
ok=0; [ ! -e "$S/dry-gpu.lock.log" ] && ok=1
record G_no_marker_abort 3 "$rc" "$ok" "$(tail -1 "$S/queue.log" | cut -d' ' -f2-)"

# H. Overrides are refused outside DRY_RUN; a dry run may not take the shared lock.
DRY_RUN=0 OUT=$BASE/H_override bash "$Q" > "$BASE/H_override.out" 2>&1
rc=$?
record H_override_refused 6 "$rc" 1 "$(tail -1 "$BASE/H_override.out")"
DRY_RUN=1 OUT=$BASE/I_shared_lock LOCK=/home/rache/kt-e2e/kt-gpu.lock bash "$Q" > "$BASE/I_shared_lock.out" 2>&1
rc=$?
record I_shared_lock_refused 6 "$rc" 1 "$(tail -1 "$BASE/I_shared_lock.out")"

echo "dry run under $BASE"
printf '%s\n' "${RESULTS[@]}"
echo "--- B lock log"
cat "$BASE/B_gate_lock_success/dry-gpu.lock.log"
echo "--- B queue log"
cat "$BASE/B_gate_lock_success/queue.log"
echo "DRYRUN-FAILS=$FAILS"
exit "$FAILS"
