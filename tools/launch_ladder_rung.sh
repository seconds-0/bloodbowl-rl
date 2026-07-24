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
# Required:
#   RUNG=<maxdist>              6, 9, 12 ... (0 = uniform, any banked start)
#   WARM=<checkpoint>           eligible obs-v6 lineage sidecar required
#   POOL=<pool dir>             4 banks, each with an eligible sidecar
#   EXPECTED_POOL_HASH=<sha256> printed by tools/build_league.py
# Optional:
#   STEPS (default 5000000000)  RESET_PCT (default 0.5)  SEED (default 42)
#   TAG, OUT, C, DEADLINE_HOURS (default 36)

set -uo pipefail

C="${C:-/home/rache/bloodbowl-rl-qualification-candidate-10619e2}"
cd "$C" || exit 1

# A detached, non-interactive shell does not source the login profile, so every
# dependency has to be explicit. build.sh calls bare `python`, which only exists
# inside the venv; run_reward_ablation.sh:516 refuses an fp32 build without
# RIG_ALLOW_FLOAT; and it refuses to start at all unless CUDA_VISIBLE_DEVICES is
# exactly "0". Each of these has already broken a launch once.
export PATH="$C/vendor/PufferLib/.venv/bin:$PATH"
export RIG_ALLOW_FLOAT=1
export CUDA_VISIBLE_DEVICES=0

: "${RUNG:?RUNG is required (backplay endzone maxdist)}"
: "${WARM:?WARM is required}"
: "${POOL:?POOL is required}"
: "${EXPECTED_POOL_HASH:?EXPECTED_POOL_HASH is required}"

STEPS="${STEPS:-5000000000}"
RESET_PCT="${RESET_PCT:-0.5}"
SEED="${SEED:-42}"
STAMP="${STAMP:-$(date +%Y%m%d)}"
TAG="${TAG:-ladder-d${RUNG}-s${SEED}-${STAMP}}"
OUT="${OUT:-$C/runs/ladder-d${RUNG}-${STAMP}}"
DEADLINE_HOURS="${DEADLINE_HOURS:-36}"

mkdir -p "$OUT"
LOG="${LOG:-$OUT/$TAG.log}"

export TAG STEPS SEED LOG WARM POOL EXPECTED_POOL_HASH
export BOOTSTRAP_MODE=lineage-v6
export REWARD_MANIFEST="$C/puffer/config/rewards/s0_both.json"
export LADDER_RESET_PCT="$RESET_PCT"
export LADDER_ENDZONE_MAXDIST="$RUNG"

echo "=== ladder rung ==="
echo "  tag    $TAG"
echo "  rung   maxdist $RUNG at reset_pct $RESET_PCT"
echo "  steps  $STEPS (CAP -- read the plateau, chain if still climbing)"
echo "  warm   $WARM"
echo "  pool   $POOL ($EXPECTED_POOL_HASH)"
echo "  bank   $(sha256sum "$C/vendor/PufferLib/resources/bloodbowl/state_bank.bbs" 2>/dev/null | cut -c1-16)"
echo "  log    $LOG"

bash "$C/tools/run_reward_ablation.sh"
launch_rc=$?
echo "LADDER_RUNG_LAUNCH_EXIT=$launch_rc"
[ "$launch_rc" -eq 0 ] || exit "$launch_rc"

# run_reward_ablation.sh DETACHES the trainer and returns 0 on successful LAUNCH,
# not on completion. Treating that as completion once published a success marker
# at 14.8M of 49.9M steps with the trainer still running, and a campaign
# supervisor would have advanced on it. Wait for the trainer's own atomic status
# sidecar instead -- the same signal run_reward_screen.sh waits on.
STATUS="${LOG}.status.json"
DEADLINE=$(( $(date +%s) + DEADLINE_HOURS * 3600 ))
while [ ! -f "$STATUS" ]; do
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        echo "timed out after ${DEADLINE_HOURS}h waiting for $STATUS" >&2
        exit 1
    fi
    sleep 60
done

rc="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("exit_code"))' \
      "$STATUS" 2>/dev/null)"
echo "LADDER_RUNG_TRAINER_EXIT=$rc"
if [ "$rc" != "0" ]; then
    echo "trainer did not exit cleanly; publishing no completion marker" >&2
    exit 1
fi

printf '{"tag":"%s","rung":%s,"reset_pct":%s,"steps":"%s","seed":%s,"log":"%s","warm":"%s","pool_hash":"%s","trainer_exit":%s}\n' \
    "$TAG" "$RUNG" "$RESET_PCT" "$STEPS" "$SEED" "$LOG" "$WARM" "$EXPECTED_POOL_HASH" "$rc" \
    > "$OUT/LADDER_RUNG_COMPLETE.json"
echo "wrote $OUT/LADDER_RUNG_COMPLETE.json"
