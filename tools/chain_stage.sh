#!/usr/bin/env bash
# One stage of an unattended training chain: one ladder rung, its scripted-bot
# exam, and a registered verdict. docs/chain-supervisor-2026-10-02.md has the
# operator view.
#
# Used as the `launch` body of a tools/campaign_supervisor.py stage. A small
# per-stage wrapper exports the environment and execs this script. It is safe
# to relaunch: every launch first reads what earlier launches left behind and
# never repeats a finished or deterministically failed step.
#
# Order of work:
#   1. Terminal-state checks (no lock needed).
#   2. Take the shared GPU lock on fd 7 and wait for it without limit. The
#      trainer inherits fd 7, so the lock follows the process that uses the GPU.
#   3. Start the one-minute GPU telemetry sampler (log only).
#   4. If the rung has no LADDER_RUNG_COMPLETE.json, run tools/ladder_stage.sh
#      as a foreground child. With EXPECTED_POOL_HASH set, a PLAN_ONLY=1 pass
#      runs first and the pool identity is compared before any training.
#   5. Run the exam cells into a new exam-attemptM directory.
#   6. tools/chain_exam_verdict.py registers the verdict.
#
# Environment for this script:
#   C STAMP                  required. C is the checkout root.
#   EXAM_RULE                required: none | drift-guard
#   EXAM_GUARD_FLOOR_S42 EXAM_GUARD_FLOOR_S43 EXAM_GUARD_FLOOR_MEAN
#                            required for drift-guard (the registered floors)
#   EXAM_GUARD_CELL          default offense_away
#   EXAM_SEEDS               default "42 43"
#   EXPECTED_POOL_HASH       optional pool identity the rung must train against
#   PLAN_ONLY=1              resolve inputs, build the pool, verify the screen
#                            plan and the pool identity, then stop. No lock, no
#                            training, no exam.
#   GPU_LOCK                 default /home/rache/kt-e2e/kt-gpu.lock
#   GPU_LOCK_WAIT_SECONDS    default 600 (one `flock -w` round; rounds repeat)
#   GPU_SAMPLE_SECONDS       default 60
#   EXAM_CELL_TIMEOUT_SECONDS  default 1800. A cell takes about 90 seconds;
#                            a hung one must fail the stage, not hold the GPU
#                            lock for ever.
#   HOST_BOOT_EPOCH          default: btime from /proc/stat
#
# Recipe for tools/ladder_stage.sh, passed through untouched. This script
# invents no recipe default. It refuses to start unless these are non-empty:
#   RUNG RESET_PCT SEED STEPS LADDER_ARM FROZEN_BANK_PCT DEADLINE_HOURS
#   NUM_THREADS, and PREV_COMPLETE or both WARM and PREV_POOL
# and unless these are set (export one empty to take the screen's fixed value
# on purpose):
#   SCRIPTED_BANK_TAG SCRIPTED_BOT_TYPE LADDER_CHAIN_LR_SCALE
#   LADDER_CHAIN_ENT_SCALE LADDER_GAMMA LADDER_GAE_LAMBDA LADDER_REPLAY_RATIO
# (the launcher scales the entropy coefficient by both chain scales, so an LR
# scale of 0.5 with the entropy scale forgotten trains at half the entropy
# coefficient without any error).
# Also passed through when set: POOL_KEEP POOL_ANCHOR NUM_FROZEN_BANKS
#   LADDER_PROFILE GRAFT_FROM_SOURCE_SHA256
#   GRAFT_FROM_PATCH_BUNDLE_SHA256 GRAFT_REASON
#   PUFFER_SKIP_SCRIPTED_BANK_FORWARD BBE_DECIDING_ROW_TELEMETRY
#   LADDER_NO_EARLY_END_TURN
# (the two GRAFT_FROM digests may each be a comma-separated list, read
# pairwise, when the warm and pool hold more than one old build).
#
# LADDER_NO_EARLY_END_TURN=1 trains the rung under the env-layer restriction
# no_early_end_turn (docs/no-early-end-turn-2026-10-05.md; not a Blood Bowl
# rule). Masked actions get no gradient, so a checkpoint trained under the rule
# is only meaningful when played under it: the exam cells of such a stage run
# with the rule on for the champion's seat (the bot's seat is never
# restricted), and EXAM_VERDICT.json records no_early_end_turn: 1. Which exam
# to run is read from the rung marker, i.e. from what the trainer received,
# and must agree with this variable: a launch that disagrees with the marker
# or with a registered verdict exits 7, also when nothing is left to run.
#
# Exit status:
#   0  verdict registered and passed (or PLAN_ONLY=1 verified)
#   2  configuration error; nothing was run
#   3  verdict registered and it did not pass. Final: no exam is run again.
#   4  the newest screen attempt failed (non-zero trainer status on this boot,
#      or a LIVE_INTEGRITY_FAILURE.json). Final: no retraining.
#   5  an exam cell failed. The next launch uses a new exam-attempt directory.
#   6  the pool identity does not match EXPECTED_POOL_HASH, or the plan-only
#      pass did not verify. Nothing was trained by this launch.
#   7  the rung marker or its checkpoint is unusable (missing file, sha256
#      mismatch), or LADDER_NO_EARLY_END_TURN disagrees with the rule the rung
#      marker or a registered verdict records
#   8  the verdict tool could not produce a verdict (missing or malformed
#      evidence). The next launch runs the exam again in a new directory.
#   143, 130, 129  stopped by TERM, INT or HUP, between steps
#   any other value is the exit status of tools/ladder_stage.sh.
set -uo pipefail

log() { printf '%s chain_stage: %s\n' "$(date -u +%FT%TZ)" "$*"; }

# --- configuration -----------------------------------------------------------
MISSING=()
for name in C STAMP EXAM_RULE RUNG RESET_PCT SEED STEPS LADDER_ARM \
            FROZEN_BANK_PCT DEADLINE_HOURS NUM_THREADS; do
  [ -n "${!name:-}" ] || MISSING+=("$name")
done
for name in SCRIPTED_BANK_TAG SCRIPTED_BOT_TYPE LADDER_CHAIN_LR_SCALE \
            LADDER_CHAIN_ENT_SCALE LADDER_GAMMA LADDER_GAE_LAMBDA \
            LADDER_REPLAY_RATIO; do
  [ -n "${!name+set}" ] || MISSING+=("$name")
done
if [ -z "${PREV_COMPLETE:-}" ] && { [ -z "${WARM:-}" ] || [ -z "${PREV_POOL:-}" ]; }; then
  MISSING+=("PREV_COMPLETE (or both WARM and PREV_POOL)")
fi
if [ "${#MISSING[@]}" -gt 0 ]; then
  log "refusing to start; unset: ${MISSING[*]}"
  exit 2
fi
case "$STAMP" in
  *[!A-Za-z0-9._-]*) log "STAMP may hold only letters, digits, dot, underscore and dash: $STAMP"; exit 2 ;;
esac
case "$RUNG" in
  *[!0-9]*) log "RUNG must be a non-negative integer: $RUNG"; exit 2 ;;
esac
[ -d "$C/tools" ] || { log "C is not a checkout root: $C"; exit 2; }

EXAM_SEEDS="${EXAM_SEEDS:-42 43}"
read -r -a SEED_LIST <<<"$EXAM_SEEDS"
[ "${#SEED_LIST[@]}" -gt 0 ] || { log "EXAM_SEEDS is empty"; exit 2; }
for seed in "${SEED_LIST[@]}"; do
  case "$seed" in
    *[!0-9]*) log "EXAM_SEEDS must be non-negative integers: $EXAM_SEEDS"; exit 2 ;;
  esac
done
EXAM_GUARD_CELL="${EXAM_GUARD_CELL:-offense_away}"
VERDICT_RULE_ARGS=(--rule "$EXAM_RULE")
if [ "$EXAM_RULE" = "drift-guard" ]; then
  for name in EXAM_GUARD_FLOOR_S42 EXAM_GUARD_FLOOR_S43 EXAM_GUARD_FLOOR_MEAN; do
    [[ "${!name:-}" =~ ^[0-9]+(\.[0-9]+)?$ ]] || {
      log "EXAM_RULE=drift-guard needs $name as a plain decimal, got '${!name:-}'"; exit 2; }
  done
  VERDICT_RULE_ARGS+=(--guard-cell "$EXAM_GUARD_CELL"
                      --guard-floor-s42 "$EXAM_GUARD_FLOOR_S42"
                      --guard-floor-s43 "$EXAM_GUARD_FLOOR_S43"
                      --guard-floor-mean "$EXAM_GUARD_FLOOR_MEAN")
elif [ "$EXAM_RULE" != "none" ]; then
  log "EXAM_RULE must be none or drift-guard, got '$EXAM_RULE'"
  exit 2
fi

LADDER_PROFILE_SEEN="${LADDER_PROFILE:-ladder-rung}"
if [ "$LADDER_PROFILE_SEEN" = "graft" ]; then
  for name in GRAFT_FROM_SOURCE_SHA256 GRAFT_FROM_PATCH_BUNDLE_SHA256 GRAFT_REASON; do
    [ -n "${!name:-}" ] || { log "LADDER_PROFILE=graft needs $name"; exit 2; }
  done
elif [ -n "${GRAFT_FROM_SOURCE_SHA256:-}${GRAFT_FROM_PATCH_BUNDLE_SHA256:-}${GRAFT_REASON:-}" ]; then
  log "GRAFT_* is set but LADDER_PROFILE is '$LADDER_PROFILE_SEEN'; the rung would refuse it"
  exit 2
fi

case "${LADDER_NO_EARLY_END_TURN:-}" in
  ''|0) NO_EARLY_END_TURN_SEEN=0 ;;
  1) NO_EARLY_END_TURN_SEEN=1 ;;
  *) log "LADDER_NO_EARLY_END_TURN must be 0 or 1, got '${LADDER_NO_EARLY_END_TURN}'"; exit 2 ;;
esac

# ladder_stage.sh sources POOL_IDENTITY.env, which assigns EXPECTED_POOL_HASH.
# Keep the caller's value under another name and never pass it down.
WANT_POOL_HASH="${EXPECTED_POOL_HASH:-}"
if [ -n "$WANT_POOL_HASH" ] && [[ ! "$WANT_POOL_HASH" =~ ^[a-f0-9]{64}$ ]]; then
  log "EXPECTED_POOL_HASH must be 64 lowercase hex characters"
  exit 2
fi
PLAN_ONLY_MODE="${PLAN_ONLY:-0}"
case "$PLAN_ONLY_MODE" in
  0|1) ;;
  *) log "PLAN_ONLY must be 0 or 1"; exit 2 ;;
esac
GPU_LOCK="${GPU_LOCK:-/home/rache/kt-e2e/kt-gpu.lock}"
GPU_LOCK_WAIT_SECONDS="${GPU_LOCK_WAIT_SECONDS:-600}"
GPU_SAMPLE_SECONDS="${GPU_SAMPLE_SECONDS:-60}"
EXAM_CELL_TIMEOUT_SECONDS="${EXAM_CELL_TIMEOUT_SECONDS:-1800}"
case "$GPU_LOCK_WAIT_SECONDS:$GPU_SAMPLE_SECONDS:$EXAM_CELL_TIMEOUT_SECONDS" in
  *[!0-9:]*|:*|*:|*::*) log "GPU_LOCK_WAIT_SECONDS, GPU_SAMPLE_SECONDS and EXAM_CELL_TIMEOUT_SECONDS must be positive integers"; exit 2 ;;
esac
for tool in flock python3 timeout; do
  command -v "$tool" >/dev/null 2>&1 || { log "$tool is required"; exit 2; }
done

# The same expression as OUT in tools/ladder_stage.sh; there is no shared
# helper, and tools/test_chain_stage.py pins the two together.
RUN_DIR="$C/runs/ladder-d${RUNG}-${STAMP}"
MARKER="$RUN_DIR/LADDER_RUNG_COMPLETE.json"
VERDICT="$RUN_DIR/EXAM_VERDICT.json"
VERDICT_PASS="$RUN_DIR/EXAM_VERDICT_PASS.json"
STATUS_FILE="$RUN_DIR/CHAIN_STAGE_STATUS.json"
LOCK_LABEL="bloodbowl-rl:chain-stage-$STAMP (rung + exam)"

cd "$C" || exit 2
mkdir -p "$RUN_DIR" || exit 2

LOCK_HELD=0
SAMPLER_PID=""

# A heartbeat for an off-box monitor. The supervisor's own progress probe is
# SCREEN_STATUS.json, which the screen writes only while the rung trains.
phase() {
  local tmp="$STATUS_FILE.tmp.$$"
  printf '{"phase":"%s","exit_code":%s,"pid":%d,"stamp":"%s","utc":"%s"}\n' \
    "$1" "${2:-null}" "$$" "$STAMP" "$(date -u +%FT%TZ)" > "$tmp" \
    && mv "$tmp" "$STATUS_FILE"
}

cleanup() {
  local rc=$?
  trap - EXIT
  # By PID only. No wait: a sampler stuck in a driver call must not hold this
  # script open, and it holds neither the lock nor a matching command line.
  if [ -n "$SAMPLER_PID" ]; then kill "$SAMPLER_PID" 2>/dev/null; fi
  if [ "$LOCK_HELD" = "1" ]; then
    printf '%s %s released(exit %s) %s\n' "$(date -u +%FT%TZ)" "$$" "$rc" \
      "$LOCK_LABEL" >> "$GPU_LOCK.log" 2>/dev/null
  fi
  phase exited "$rc"
  log "exit $rc"
  exit "$rc"
}
trap cleanup EXIT
# TERM, INT and HUP stop the stage between steps, not in the middle of one:
# bash runs a trap only after the foreground child returns. A signalled stage
# therefore never abandons a live trainer that still holds the lock, and the
# released line and the heartbeat carry the true exit status. Without these
# traps bash would die at once, run cleanup with status 0, and log a release
# while the trainer still held the lock. To stop a rung, signal the trainer
# wrapper PID (see the doc); to stop an exam, signal this script and it exits
# after the running cell.
trap 'log "caught TERM; stopping"; exit 143' TERM
trap 'log "caught INT; stopping"; exit 130' INT
trap 'log "caught HUP; stopping"; exit 129' HUP

# --- terminal states ---------------------------------------------------------
# Printed by the inspector, one line:
#   none | open N | clean N | rebooted N CODE | failed N CODE | integrity N
inspect_newest_attempt() {
  python3 - "$RUN_DIR" "${HOST_BOOT_EPOCH:-}" <<'PY'
import json, pathlib, sys

run_dir, boot_text = pathlib.Path(sys.argv[1]), sys.argv[2]
newest, n = None, 1
while (run_dir / f"screen-attempt{n}").is_dir():
    newest, n = n, n + 1
if newest is None:
    print("none")
    raise SystemExit(0)
attempt = run_dir / f"screen-attempt{newest}"
if (attempt / "LIVE_INTEGRITY_FAILURE.json").exists():
    print(f"integrity {newest}")
    raise SystemExit(0)

boot = None
try:
    if boot_text:
        boot = float(boot_text)
    else:
        for line in open("/proc/stat", encoding="ascii"):
            if line.startswith("btime "):
                boot = float(line.split()[1])
except (OSError, ValueError):
    boot = None

worst = None
statuses = sorted(attempt.glob("*.log.status.json"))
for status in statuses:
    try:
        code = int(json.loads(status.read_text(encoding="utf-8"))["exit_code"])
    except (OSError, ValueError, KeyError, TypeError):
        code = -1  # unreadable status: treat as failed
    if code != 0:
        # A status written before this boot belongs to a trainer that the
        # host took down (a clean shutdown sends TERM and the wrapper
        # records 143). Unknown boot time counts as this boot: fail closed.
        before_boot = boot is not None and status.stat().st_mtime < boot
        kind = "rebooted" if before_boot else "failed"
        if worst is None or kind == "failed":
            worst = (kind, code)
if worst is not None:
    print(f"{worst[0]} {newest} {worst[1]}")
elif statuses:
    print(f"clean {newest}")
else:
    print(f"open {newest}")
PY
}

# The rule a stage declares must be the rule its records carry. The rung marker
# says what the trainer received and the verdict says how the exam ran; a
# launch whose LADDER_NO_EARLY_END_TURN says otherwise is describing a
# different rung, whether or not anything is left to run.
check_rule_records() {
  python3 - "$NO_EARLY_END_TURN_SEEN" "$MARKER" "$VERDICT" "$VERDICT_PASS" <<'PY'
import json, os, sys

declared = int(sys.argv[1])
for path in sys.argv[2:]:
    if not os.path.isfile(path):
        continue
    try:
        record = json.load(open(path, encoding="utf-8"))
        recorded = record.get("no_early_end_turn", 0)
    except (OSError, ValueError, AttributeError) as exc:
        print(f"unreadable record {path}: {exc!r}", file=sys.stderr)
        raise SystemExit(7)
    if recorded not in (0, 1) or isinstance(recorded, bool):
        print(f"{path}: no_early_end_turn={recorded!r} is not 0 or 1",
              file=sys.stderr)
        raise SystemExit(7)
    if recorded != declared:
        print(f"RULE MISMATCH: {path} records no_early_end_turn={recorded}, "
              f"this stage declares {declared} (LADDER_NO_EARLY_END_TURN)",
              file=sys.stderr)
        raise SystemExit(7)
PY
}

terminal_checks() {
  check_rule_records || exit 7
  if [ -f "$VERDICT_PASS" ]; then
    log "verdict already registered and passed: $VERDICT_PASS"
    exit 0
  fi
  if [ -f "$VERDICT" ]; then
    log "verdict already registered and it did not pass: $VERDICT (final; no exam is run again)"
    exit 3
  fi
  # An accepted rung makes older failed attempts irrelevant.
  [ ! -f "$MARKER" ] || return 0
  local state kind attempt code
  state="$(inspect_newest_attempt)" || { log "could not inspect screen attempts under $RUN_DIR"; exit 2; }
  read -r kind attempt code <<<"$state"
  case "$kind" in
    failed)
      log "screen-attempt$attempt recorded trainer status $code on this boot; a failed run is not a host death, so no retraining"
      log "to retry on purpose: mkdir $RUN_DIR/screen-attempt$((attempt + 1)) and reset the stage's attempts"
      exit 4 ;;
    integrity)
      log "screen-attempt$attempt holds LIVE_INTEGRITY_FAILURE.json; no retraining"
      log "to retry on purpose: mkdir $RUN_DIR/screen-attempt$((attempt + 1)) and reset the stage's attempts"
      exit 4 ;;
    rebooted)
      log "screen-attempt$attempt recorded trainer status $code before this boot; treating it as a host shutdown, the rung opens the next attempt" ;;
    open)
      log "screen-attempt$attempt has no trainer status (never launched, or the host died); the rung decides whether to reuse it" ;;
    clean)
      log "screen-attempt$attempt finished with status 0 but published no marker; the rung re-validates it without retraining" ;;
    none) ;;
    *) log "unreadable attempt state: $state"; exit 2 ;;
  esac
}

# Reads the published pool identity without sourcing it.
pool_identity() {
  python3 - "$RUN_DIR/POOL_IDENTITY.env" <<'PY'
import re, sys
try:
    text = open(sys.argv[1], encoding="utf-8").read()
except OSError as exc:
    raise SystemExit(f"cannot read pool identity: {exc}")
found = re.findall(r"^EXPECTED_POOL_HASH=([a-f0-9]{64})$", text, re.M)
if len(found) != 1:
    raise SystemExit(f"{sys.argv[1]} does not hold exactly one EXPECTED_POOL_HASH")
print(found[0])
PY
}

check_pool_identity() {
  [ -n "$WANT_POOL_HASH" ] || return 0
  local have
  have="$(pool_identity)" || exit 6
  if [ "$have" != "$WANT_POOL_HASH" ]; then
    log "POOL MISMATCH: $RUN_DIR/POOL_IDENTITY.env is $have, EXPECTED_POOL_HASH is $WANT_POOL_HASH"
    exit 6
  fi
  log "pool identity matches EXPECTED_POOL_HASH ($have)"
}

# PLAN_ONLY=1 reaches tools/run_reward_screen.sh through the exported
# environment. ladder_stage.sh resolves the warm start, builds and publishes
# the pool, and the screen verifies its plan and exits 0 before any launch.
# launch_ladder_rung.sh then exits 1 because a plan publishes no result, so
# success is read from the two lines below, not from the exit status.
run_plan_pass() {
  local plan_log="$RUN_DIR/chain-plan-only.log" rc
  log "plan-only pass: resolve inputs, build the pool, verify the screen plan (no training)"
  ( unset EXPECTED_POOL_HASH; export PLAN_ONLY=1
    exec bash "$C/tools/ladder_stage.sh" ) 2>&1 | tee "$plan_log" 7>&-
  rc="${PIPESTATUS[0]}"
  if grep -q '^SCREEN PLAN VERIFIED: ' "$plan_log" \
      && grep -qx 'LADDER_RUNG_SCREEN_EXIT=0' "$plan_log"; then
    log "plan-only pass verified (ladder_stage.sh exit $rc is expected: a plan publishes no marker)"
    return 0
  fi
  log "plan-only pass did NOT verify the screen plan (ladder_stage.sh exit $rc); see $plan_log"
  return 1
}

log "stage $STAMP run_dir $RUN_DIR"
log "recipe: rung=$RUNG reset_pct=$RESET_PCT seed=$SEED steps=$STEPS arm=$LADDER_ARM profile=$LADDER_PROFILE_SEEN prev_complete=${PREV_COMPLETE:-} warm=${WARM:-}"
log "recipe: lr_scale=$LADDER_CHAIN_LR_SCALE ent_scale=$LADDER_CHAIN_ENT_SCALE gamma=$LADDER_GAMMA gae_lambda=$LADDER_GAE_LAMBDA replay_ratio=$LADDER_REPLAY_RATIO frozen_bank_pct=$FROZEN_BANK_PCT bot_tag=$SCRIPTED_BANK_TAG bot_type=$SCRIPTED_BOT_TYPE"
log "build flags: PUFFER_SKIP_SCRIPTED_BANK_FORWARD=${PUFFER_SKIP_SCRIPTED_BANK_FORWARD:-unset} BBE_DECIDING_ROW_TELEMETRY=${BBE_DECIDING_ROW_TELEMETRY:-unset}"
[ "$NO_EARLY_END_TURN_SEEN" != "1" ] || \
  log "rule: no_early_end_turn=1 for the rung and for its exam (training restriction on the learner's seats; not a Blood Bowl rule)"
log "exam: seeds=${SEED_LIST[*]} rule=$EXAM_RULE ${VERDICT_RULE_ARGS[*]:2}"

terminal_checks

if [ "$PLAN_ONLY_MODE" = "1" ]; then
  # A plan is CPU work (chain 36's was verified while chain 35 trained), so
  # this mode takes no GPU lock.
  if [ -f "$MARKER" ]; then
    log "PLAN_ONLY=1: the rung is already complete ($MARKER); nothing to plan"
  else
    phase plan-only
    run_plan_pass || exit 6
  fi
  check_pool_identity
  log "PLAN_ONLY=1: pool identity $(pool_identity || echo unreadable); stopping before any training"
  exit 0
fi

# --- GPU lock ----------------------------------------------------------------
[ -d "$(dirname "$GPU_LOCK")" ] || { log "GPU lock directory is missing: $(dirname "$GPU_LOCK")"; exit 2; }
exec 7>>"$GPU_LOCK" || { log "cannot open GPU lock $GPU_LOCK"; exit 2; }
phase waiting-gpu-lock
while :; do
  flock -w "$GPU_LOCK_WAIT_SECONDS" 7
  lock_rc=$?
  [ "$lock_rc" -ne 0 ] || break
  # 1 is flock's timeout status. Anything else is a broken lock, and looping
  # on it would spin.
  [ "$lock_rc" -eq 1 ] || { log "flock failed with status $lock_rc on $GPU_LOCK"; exit 2; }
  log "waiting on $GPU_LOCK (another GPU job holds it)"
  phase waiting-gpu-lock
done
LOCK_HELD=1
printf '%s %s acquired(lock=%s) %s\n' "$(date -u +%FT%TZ)" "$$" "$GPU_LOCK" \
  "$LOCK_LABEL" >> "$GPU_LOCK.log" 2>/dev/null \
  || log "could not append to $GPU_LOCK.log (the lock itself is held)"
log "acquired $GPU_LOCK on fd 7"

# Another launch of this stage may have finished while this one waited.
terminal_checks

# --- GPU telemetry -----------------------------------------------------------
bash "$C/tools/chain_gpu_sampler.sh" "$RUN_DIR/gpu_samples.csv" \
  "$GPU_SAMPLE_SECONDS" "$$" 7>&- &
SAMPLER_PID=$!
log "gpu sampler pid=$SAMPLER_PID every ${GPU_SAMPLE_SECONDS}s -> $RUN_DIR/gpu_samples.csv"

# --- rung --------------------------------------------------------------------
if [ ! -f "$MARKER" ]; then
  if [ -n "$WANT_POOL_HASH" ] && [ ! -f "$RUN_DIR/POOL_IDENTITY.env" ]; then
    phase plan-only
    run_plan_pass || exit 6
  fi
  check_pool_identity
fi
if [ ! -f "$MARKER" ]; then
  phase training
  log "rung start: bash tools/ladder_stage.sh"
  ( unset EXPECTED_POOL_HASH PLAN_ONLY
    exec bash "$C/tools/ladder_stage.sh" )
  rung_rc=$?
  log "rung end: ladder_stage.sh exit $rung_rc"
  [ "$rung_rc" -eq 0 ] || exit "$rung_rc"
  [ -f "$MARKER" ] || { log "ladder_stage.sh exited 0 without $MARKER"; exit 7; }
else
  log "rung already complete: $MARKER"
fi
check_pool_identity

# --- exam --------------------------------------------------------------------
phase exam
# The marker now exists whichever launch trained the rung: its record of the
# rule decides how the rung is examined.
check_rule_records || exit 7
CKPT="$(python3 - "$MARKER" "$WANT_POOL_HASH" <<'PY'
import hashlib, json, os, sys

marker_path, want_pool = sys.argv[1], sys.argv[2]
try:
    marker = json.load(open(marker_path, encoding="utf-8"))
    checkpoint = marker["checkpoint"]
    recorded = marker["checkpoint_sha256"]
except (OSError, ValueError, KeyError, TypeError) as exc:
    print(f"unusable rung marker {marker_path}: {exc!r}", file=sys.stderr)
    raise SystemExit(7)
if marker.get("trainer_exit") != 0:
    print(f"rung marker is not an accepted result: {marker_path}", file=sys.stderr)
    raise SystemExit(7)
if want_pool and marker.get("pool_hash") != want_pool:
    print(f"POOL MISMATCH: marker pool_hash {marker.get('pool_hash')}, "
          f"EXPECTED_POOL_HASH {want_pool}", file=sys.stderr)
    raise SystemExit(6)
if not isinstance(checkpoint, str) or not os.path.isfile(checkpoint):
    print(f"marker checkpoint is not a file: {checkpoint!r}", file=sys.stderr)
    raise SystemExit(7)
digest = hashlib.sha256()
with open(checkpoint, "rb") as handle:
    for block in iter(lambda: handle.read(1 << 20), b""):
        digest.update(block)
if digest.hexdigest() != recorded:
    print(f"checkpoint {checkpoint} has sha256 {digest.hexdigest()}, "
          f"the marker recorded {recorded}", file=sys.stderr)
    raise SystemExit(7)
print(checkpoint)
print(recorded)
PY
)"
marker_rc=$?
[ "$marker_rc" -eq 0 ] || exit "$marker_rc"
CKPT_SHA="${CKPT##*$'\n'}"
CKPT="${CKPT%$'\n'*}"
log "exam checkpoint $CKPT sha256 $CKPT_SHA (matches the marker)"

# Never write into an existing attempt directory: a half-written one holds
# logs that tools/eval_vs_contact_bot.sh refuses to overwrite.
EXAM_ATTEMPT=1
while [ -e "$RUN_DIR/exam-attempt$EXAM_ATTEMPT" ]; do
  EXAM_ATTEMPT=$((EXAM_ATTEMPT + 1))
done
EXAM_DIR="$RUN_DIR/exam-attempt$EXAM_ATTEMPT"
mkdir -p "$EXAM_DIR" || exit 5
log "exam start: $EXAM_DIR"

# The cells of the as-run rig_exam.sh with the exit status kept. PATH carries
# the venv as rig_exam.sh's did. OMP_NUM_THREADS is removed so tools/cpu_cap.sh
# derives the thread count as it did for the as-run exams (16 on the rig).
# `timeout` signals the cell's whole process group, so a hung eval is stopped
# with its trainer process and reads as a failed cell (status 124).
# The rule reaches the cell by this assignment alone: check_rule_records has
# tied NO_EARLY_END_TURN_SEEN to what the rung trained with, and an inherited
# value must not decide an exam.
VERDICT_EXAM_ARGS=()
if [ "$NO_EARLY_END_TURN_SEEN" = "1" ]; then
  VERDICT_EXAM_ARGS=(--no-early-end-turn 1)
  log "exam runs under no_early_end_turn=1 (the rung trained under it)"
fi
for seed in "${SEED_LIST[@]}"; do
  mkdir -p "$EXAM_DIR/s$seed" || exit 5
  for spec in "contact_away 0 1" "contact_home 0 0" "offense_away 1 1"; do
    read -r cell bot_type bot_team <<<"$spec"
    log "exam cell seed=$seed $cell (BOT_TYPE=$bot_type BOT_TEAM=$bot_team) start"
    env -u OMP_NUM_THREADS PATH="$C/vendor/PufferLib/.venv/bin:$PATH" \
        NATIVE=1 RIG_ALLOW_FLOAT=1 CUDA_VISIBLE_DEVICES=0 SEED="$seed" \
        BOT_TYPE="$bot_type" BOT_TEAM="$bot_team" EVAL_EPISODES=2000 \
        LADDER_NO_EARLY_END_TURN="$NO_EARLY_END_TURN_SEEN" \
        timeout --signal=TERM --kill-after=60 "$EXAM_CELL_TIMEOUT_SECONDS" \
        bash "$C/tools/eval_vs_contact_bot.sh" "$CKPT" 12000000 \
        "$EXAM_DIR/s$seed/$cell.log" > "$EXAM_DIR/s$seed/$cell.out" 2>&1 || {
      cell_rc=$?
      log "EXAM CELL FAILED seed=$seed $cell exit $cell_rc (124 is the ${EXAM_CELL_TIMEOUT_SECONDS}s cell timeout); no verdict. Tail of $EXAM_DIR/s$seed/$cell.out:"
      tail -n 15 "$EXAM_DIR/s$seed/$cell.out" 2>/dev/null
      exit 5
    }
    log "exam cell seed=$seed $cell done"
  done
done
printf '{"checkpoint_sha256":"%s","seeds":"%s","completed_utc":"%s"}\n' \
  "$CKPT_SHA" "${SEED_LIST[*]}" "$(date -u +%FT%TZ)" > "$EXAM_DIR/EXAM_CELLS_COMPLETE.json.tmp" \
  && mv "$EXAM_DIR/EXAM_CELLS_COMPLETE.json.tmp" "$EXAM_DIR/EXAM_CELLS_COMPLETE.json"
log "exam cells complete: $EXAM_DIR"

# --- verdict -----------------------------------------------------------------
phase verdict
python3 "$C/tools/chain_exam_verdict.py" --exam-dir "$EXAM_DIR" \
  --seeds "${SEED_LIST[@]}" "${VERDICT_RULE_ARGS[@]}" \
  --checkpoint-sha256 "$CKPT_SHA" --output-dir "$RUN_DIR" \
  ${VERDICT_EXAM_ARGS[@]+"${VERDICT_EXAM_ARGS[@]}"}
verdict_rc=$?
case "$verdict_rc" in
  0)
    [ -f "$VERDICT_PASS" ] || { log "verdict tool exited 0 without $VERDICT_PASS"; exit 8; }
    log "VERDICT PASS: $VERDICT_PASS"
    exit 0 ;;
  3)
    log "VERDICT FAIL (rule $EXAM_RULE): $VERDICT. This is final; the supervisor halts at the attempt cap."
    exit 3 ;;
  *)
    log "no verdict was registered (verdict tool exit $verdict_rc); the next launch runs the exam again"
    exit 8 ;;
esac
