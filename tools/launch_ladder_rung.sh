#!/usr/bin/env bash
# Launch one rung of the backplay curriculum ladder and wait for it to finish.
#
# The ladder (CLAUDE.md, D50/D51/D67-D74) is maxdist 6 -> 9 -> 12 -> uniform ->
# kickoff, +3 squares per rung and never more (D51: 6->12 overshot and tds went
# flat for 2.1B steps), warm-starting each rung from the previous rung's
# HIGHEST-STEP checkpoint -- not the newest by mtime, which is footgun 10.
#
# It is the only path in this project's history that ever produced a scoring
# policy. Every kickoff-only run is scoreless, including one capped at 10.1B
# steps (D26/D34/D40/D49), and the 8-arm decomposition screen reproduced that
# with tds exactly 0.000000 in all eight arms.
#
# Budget per rung is a CAP, not a target. D168 is explicit that run length is
# set by PLATEAU, not by a fixed step budget: read the behavioural curve, and if
# it is still climbing at the cap, chain a warm restart rather than calling it
# done. total-timesteps cannot be raised mid-run.
#
# A rung runs AS A ONE-ARM SCREEN (SCREEN_PROFILE=ladder-rung in
# tools/run_reward_screen.sh), not as a bare tools/run_reward_ablation.sh arm.
# The first two rung-6 runs (July 2026) went through the bare launcher and
# produced accepted-looking checkpoints that could not warm-start anything:
# eligible lineage is written only by the screen's materialize_result, after
# the acceptance gate, and the bare launcher also attaches no live integrity
# guard. The screen fixes both, publishes <PREFIX>-s_both-s<SEED>.result.json
# with the accepted checkpoint path and its lineage digest, and is safe to
# relaunch: a completed arm is re-validated, an unfinished one resumes.
#
# Required:
#   RUNG=<maxdist>              6, 9, 12 ... (0 = uniform, any banked start)
#   WARM=<checkpoint>           eligible obs-v6 lineage sidecar required
#   POOL=<pool dir>             4 banks, each with an eligible sidecar
#   EXPECTED_POOL_HASH=<sha256> printed by tools/build_league.py
# Optional:
#   STEPS (default 5000000000)  RESET_PCT (default 0.5)  SEED (default 42)
#   PREFIX (default ladder-d<RUNG>-s<SEED>-<STAMP>)  STAMP  OUT  C
#   DEADLINE_HOURS (default 36)

set -uo pipefail

C="${C:-/home/rache/bloodbowl-rl-qualification-candidate-10619e2}"
cd "$C" || exit 1

# A detached, non-interactive shell does not source the login profile, so every
# dependency has to be explicit. build.sh calls bare `python`, which only exists
# inside the venv; run_reward_ablation.sh refuses an fp32 build without
# RIG_ALLOW_FLOAT; and it refuses to start at all unless CUDA_VISIBLE_DEVICES is
# exactly "0". Each of these has already broken a launch once.
export PATH="$C/vendor/PufferLib/.venv/bin:$PATH"
export RIG_ALLOW_FLOAT=1
export CUDA_VISIBLE_DEVICES=0

: "${RUNG:?RUNG is required (backplay endzone maxdist; 0 = uniform)}"
: "${WARM:?WARM is required}"
: "${POOL:?POOL is required}"
: "${EXPECTED_POOL_HASH:?EXPECTED_POOL_HASH is required}"

STEPS="${STEPS:-5000000000}"
RESET_PCT="${RESET_PCT:-0.5}"
SEED="${SEED:-42}"
STAMP="${STAMP:-$(date +%Y%m%d)}"
PREFIX="${PREFIX:-ladder-d${RUNG}-s${SEED}-${STAMP}}"
OUT="${OUT:-$C/runs/ladder-d${RUNG}-${STAMP}}"
DEADLINE_HOURS="${DEADLINE_HOURS:-36}"
TAG="${PREFIX}-s_both-s${SEED}"

mkdir -p "$OUT"

# The screen runs in a numbered sub-directory of OUT so a host reboot or OOM
# mid-arm -- partial artifacts, no atomic status, no live trainer -- does not
# wedge the stage forever (the screen refuses such a directory by design). A
# relaunch reuses the newest attempt directory when it is still recoverable
# (a live trainer holds its lock, or the arm finished and can be materialized)
# and otherwise opens the next one. LADDER_RUNG_COMPLETE.json is always
# published to OUT itself, which is what the campaign supervisor watches.
pick_screen_dir() {
    local n=1 dir log
    while :; do
        dir="$OUT/screen-attempt$n"
        log="$dir/${TAG}.log"
        if [ ! -d "$dir" ]; then printf '%s\n' "$dir"; return; fi
        if [ -f "$dir/SCREEN_COMPLETE.json" ]; then printf '%s\n' "$dir"; return; fi
        if [ ! -f "$log" ]; then printf '%s\n' "$dir"; return; fi        # planned, never launched
        if [ -f "$log.status.json" ]; then
            # Finished. A clean exit is recoverable (the screen re-validates
            # and materializes); a non-zero exit is refused by the screen
            # forever ("cannot recover failed arm"), so open the next attempt.
            if python3 -c 'import json,sys; sys.exit(0 if int(json.load(open(sys.argv[1]))["exit_code"])==0 else 1)' "$log.status.json" 2>/dev/null; then
                printf '%s\n' "$dir"; return
            fi
            echo "screen attempt dir $dir holds a failed arm (non-zero status); opening the next" >&2
            n=$((n + 1)); continue
        fi
        if [ -f "$log.process.json" ]; then
            local pid
            pid="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["pid"])' "$log.process.json" 2>/dev/null)"
            if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
                printf '%s\n' "$dir"; return                          # trainer alive: wait on it
            fi
        fi
        echo "screen attempt dir $dir holds a dead partial arm; opening the next" >&2
        n=$((n + 1))
    done
}
SCREEN_DIR="$(pick_screen_dir)"
RESULT="$SCREEN_DIR/${TAG}.result.json"
COMPLETE="$SCREEN_DIR/SCREEN_COMPLETE.json"
mkdir -p "$SCREEN_DIR"
# Stable progress path for the campaign supervisor's staleness probe.
ln -sfn "$SCREEN_DIR/SCREEN_STATUS.json" "$OUT/SCREEN_STATUS.json"

echo "=== ladder rung ==="
echo "  prefix $PREFIX"
echo "  rung   maxdist $RUNG at reset_pct $RESET_PCT"
echo "  steps  $STEPS (CAP -- read the plateau, chain if still climbing)"
echo "  seed   $SEED"
echo "  warm   $WARM"
echo "  pool   $POOL ($EXPECTED_POOL_HASH)"
echo "  bank   $(sha256sum "$C/vendor/PufferLib/resources/bloodbowl/state_bank.bbs" 2>/dev/null | cut -c1-16)"
echo "  out    $OUT"
echo "  screen $SCREEN_DIR"

# The screen blocks until the arm is accepted (or fails closed) and writes
# SCREEN_COMPLETE.json itself; there is no detached-launch race to guard here.
# It also owns the live integrity guard, the trainer wrapper's atomic status,
# and the acceptance gate. Bound by a wall-clock deadline so a wedged trainer
# cannot hold the campaign forever.
timeout --signal=TERM --kill-after=120 "$((DEADLINE_HOURS * 3600))" \
  env SCREEN_PROFILE=ladder-rung PREFIX="$PREFIX" OUT_DIR="$SCREEN_DIR" \
      STEPS="$STEPS" WARM="$WARM" POOL="$POOL" \
      EXPECTED_POOL_HASH="$EXPECTED_POOL_HASH" \
      LADDER_ENDZONE_MAXDIST="$RUNG" LADDER_RESET_PCT="$RESET_PCT" \
      LADDER_SEED="$SEED" \
      bash "$C/tools/run_reward_screen.sh"
rc=$?
echo "LADDER_RUNG_SCREEN_EXIT=$rc"
if [ "$rc" -ne 0 ]; then
    echo "rung screen did not complete cleanly; publishing no completion marker" >&2
    exit "$rc"
fi
[ -f "$COMPLETE" ] && [ -f "$RESULT" ] || {
    echo "screen exited 0 without SCREEN_COMPLETE.json + $RESULT" >&2
    exit 1
}

# Publish the rung marker only from the screen's own accepted result, so the
# checkpoint path recorded here is the one whose lineage sidecar was written.
python3 - "$RESULT" "$OUT/LADDER_RUNG_COMPLETE.json" "$RUNG" "$RESET_PCT" \
    "$STEPS" "$SEED" "$WARM" "$EXPECTED_POOL_HASH" "$PREFIX" <<'PY'
import json, sys
result_path, out_path, rung, reset_pct, steps, seed, warm, pool_hash, prefix = sys.argv[1:]
result = json.load(open(result_path, encoding="utf-8"))
if not result.get("acceptance_pass"):
    raise SystemExit(f"result is not accepted: {result_path}")
payload = {
    "prefix": prefix,
    "tag": result["tag"],
    "rung": int(rung),
    "reset_pct": float(reset_pct),
    "steps": str(steps),
    "seed": int(seed),
    "log": result["log"],
    "warm": warm,
    "pool_hash": pool_hash,
    "checkpoint": result["checkpoint"],
    "checkpoint_sha256": result["checkpoint_sha256"],
    "checkpoint_lineage": result["checkpoint_lineage"],
    "checkpoint_lineage_sha256": result["checkpoint_lineage_sha256"],
    "result": result_path,
    "trainer_exit": 0,
}
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
print("wrote", out_path)
PY
