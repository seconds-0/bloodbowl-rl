#!/usr/bin/env bash
# Historical disposable backplay-ladder canary, retained as an exact recipe
# record. It is retired and cannot launch.
#
# This is a CANARY in D219's sense -- never warm-start from its output, never add
# it to an opponent pool, never quote it as a reward result. Its only job is to
# answer three questions before a multi-day ladder budget is committed:
#
#   1. Historically: did the integrity counters stay zero with banked resets?
#      The new typed loader validates every candidate before publication, so a
#      future canary will consume a pre-indexed, authorized stratum instead.
#   2. Does episode_length rise off the ~137.7 floor the kickoff-only runs sit
#      at? A backplay start puts the carrier near the endzone, so if the knob is
#      really applied the episode shape must change. If episode_length stays at
#      137.7 the knob did nothing and the run is a kickoff run wearing a ladder's
#      name -- the exact silent no-op the launcher's new guards exist to prevent.
#   3. Does tds move off 0.000? Every kickoff-only run in project history is
#      scoreless (D26/D34/D40/D49, one capped at 10.1B), and the ladder is the
#      only thing that ever fixed it (D50/D67-D74).
#
# Historical rung choice: maxdist 6 was D51's backplay-s1 rung. The measured
# 313-record population is evidence for building a named stratum, not authority
# to revive runtime rejection sampling.
#
# reset_pct 0.5, not 0.9: D69 retired 0.9 as "drill saturation [that] overwrites
# game-context behavior" and D74 graduates 0.5 -> 0.25 -> 0. 0.5 is the mixed
# ratio that transferred.

# The executable tombstone intentionally leaves the historical recipe below
# unreachable as migration evidence.
# shellcheck disable=SC2317
set -uo pipefail

echo "ladder canary retired: its checkout paths and operational defaults are stale" >&2
echo "use tools/run_reward_ablation.sh with complete typed state-bank authority" >&2
echo "no checkout was inspected and no Puffer process was started" >&2
exit 2

C="${C:-/home/rache/bloodbowl-rl-qualification-candidate-10619e2}"
cd "$C" || exit 1

STAMP="${STAMP:-20260723}"
export CUDA_VISIBLE_DEVICES=0
export TAG="${TAG:-ladder-canary-d6-$STAMP}"
export STEPS="${STEPS:-50000000}"
export BOOTSTRAP_MODE=lineage-v6
export REWARD_MANIFEST="$C/puffer/config/rewards/s0_both.json"
export WARM="${WARM:-$C/vendor/PufferLib/checkpoints/bloodbowl/1784833905091/0000000049938432.bin}"
export POOL="${POOL:-$C/runs/pool-boot-20260723/pool}"
export EXPECTED_POOL_HASH="${EXPECTED_POOL_HASH:-c75d4baa2b962ce9687607a018ff6a0a0d8c74d781b5de526ee8d6503953d3ab}"

# The curriculum itself.
export LADDER_RESET_PCT=0.5
export LADDER_ENDZONE_MAXDIST=6
: "${LADDER_STATE_BANK_KIND:?LADDER_STATE_BANK_KIND is required}"
: "${EXPECTED_LADDER_STATE_BANK_SHA256:?EXPECTED_LADDER_STATE_BANK_SHA256 is required}"
: "${EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256:?EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256 is required}"
: "${EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256:?EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256 is required}"
export LADDER_STATE_BANK_KIND EXPECTED_LADDER_STATE_BANK_SHA256
export EXPECTED_LADDER_STATE_BANK_PRODUCER_MANIFEST_SHA256
export EXPECTED_LADDER_STATE_BANK_CONTRACT_SHA256

OUT="${OUT:-$C/runs/ladder-canary-$STAMP}"
mkdir -p "$OUT"
export LOG="${LOG:-$OUT/$TAG.log}"

echo "=== ladder canary ==="
echo "  tag        $TAG"
echo "  steps      $STEPS"
echo "  rung       maxdist $LADDER_ENDZONE_MAXDIST at reset_pct $LADDER_RESET_PCT"
echo "  warm       $WARM"
echo "  pool       $POOL"
echo "  bank pin   ${EXPECTED_LADDER_STATE_BANK_SHA256:0:16}"
echo "  log        $LOG"

bash "$C/tools/run_reward_ablation.sh"
launch_rc=$?
echo "LADDER_CANARY_LAUNCH_EXIT=$launch_rc"
[ "$launch_rc" -eq 0 ] || exit "$launch_rc"

# run_reward_ablation.sh DETACHES the trainer (setsid nohup; ARM_DETACH defaults
# to 1) and returns 0 as soon as the LAUNCH succeeds -- not when training
# finishes. Treating that exit code as completion published a success marker at
# 14,811,136 of 49,938,432 steps once already, with the trainer still running.
# The real signal is the trainer's own atomic status sidecar, which is what
# run_reward_screen.sh waits on too.
STATUS="${LOG}.status.json"
DEADLINE=$(( $(date +%s) + 7200 ))
while [ ! -f "$STATUS" ]; do
    if [ "$(date +%s)" -ge "$DEADLINE" ]; then
        echo "timed out after 2h waiting for $STATUS" >&2
        exit 1
    fi
    sleep 30
done

rc="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("exit_code"))' \
      "$STATUS" 2>/dev/null)"
echo "LADDER_CANARY_TRAINER_EXIT=$rc"
if [ "$rc" != "0" ]; then
    echo "trainer did not exit cleanly; publishing no completion marker" >&2
    exit 1
fi

# Only now is the canary genuinely finished.
printf '{"tag":"%s","steps":"%s","endzone_maxdist":%s,"reset_pct":%s,"log":"%s","trainer_exit":%s}\n' \
    "$TAG" "$STEPS" "$LADDER_ENDZONE_MAXDIST" "$LADDER_RESET_PCT" "$LOG" "$rc" \
    > "$OUT/LADDER_CANARY_COMPLETE.json"
echo "wrote $OUT/LADDER_CANARY_COMPLETE.json"
