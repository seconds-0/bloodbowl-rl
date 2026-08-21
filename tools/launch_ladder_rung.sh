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
# guard. The screen fixes both, publishes <PREFIX>-<LADDER_ARM>-s<SEED>.result.json
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
#   LADDER_CHAIN_LR_SCALE (default 1; D245 proposed 0.1 to resume a chain near
#     the warm rung's final LR/entropy, but the 2026-08-20 audit F1 found 0.1
#     freezes training under Muon, so leave it at 1 unless experimenting)
#   PREFIX (default ladder-d<RUNG>-s<SEED>-<STAMP>)  STAMP  OUT  C
#   DEADLINE_HOURS (default 36)
#   SCRIPTED_BANK_TAG (default 0)  SCRIPTED_BOT_TYPE (default 0)
#     -- scripted bank: bank (tag-1)'s seat is played by the contact (0) or
#        offense (1) bot in that bank's envs; forwarded to the screen and
#        recorded in LADDER_RUNG_COMPLETE.json. 0 = ordinary rung.
#   LADDER_PROFILE (default ladder-rung; `graft` and `bridge` allowed)
#     -- graft: this rung is the reviewed lineage bridge across a build change
#        (SCREEN_PROFILE=graft). Requires GRAFT_FROM_SOURCE_SHA256,
#        GRAFT_FROM_PATCH_BUNDLE_SHA256 and GRAFT_REASON, forwarded to the
#        screen. Same one-arm shape and tag, so the completion marker is
#        published exactly like a rung's, plus the graft declaration.
#     -- bridge: this rung warm-starts from an OUT-OF-LINEAGE raw blob with no
#        sidecar (SCREEN_PROFILE=bridge; docs/audit-2026-08-20.md F2). WARM is
#        the raw obs-v4/obs-v5-era checkpoint. Requires BRIDGE_WARM_SHA256
#        (sha256sum of WARM), BRIDGE_WARM_OBS_VERSION (4|5), BRIDGE_PROVENANCE
#        and BRIDGE_REASON, forwarded to the screen and recorded in the
#        completion marker under `bridge`.

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
SCRIPTED_BANK_TAG="${SCRIPTED_BANK_TAG:-0}"
SCRIPTED_BOT_TYPE="${SCRIPTED_BOT_TYPE:-0}"
LADDER_PROFILE="${LADDER_PROFILE:-ladder-rung}"
GRAFT_FROM_SOURCE_SHA256="${GRAFT_FROM_SOURCE_SHA256:-}"
GRAFT_FROM_PATCH_BUNDLE_SHA256="${GRAFT_FROM_PATCH_BUNDLE_SHA256:-}"
GRAFT_REASON="${GRAFT_REASON:-}"
BRIDGE_WARM_SHA256="${BRIDGE_WARM_SHA256:-}"
BRIDGE_WARM_OBS_VERSION="${BRIDGE_WARM_OBS_VERSION:-}"
BRIDGE_PROVENANCE="${BRIDGE_PROVENANCE:-}"
BRIDGE_REASON="${BRIDGE_REASON:-}"
if [ "$LADDER_PROFILE" != "graft" ] && \
   [ -n "$GRAFT_FROM_SOURCE_SHA256$GRAFT_FROM_PATCH_BUNDLE_SHA256$GRAFT_REASON" ]; then
  echo "GRAFT_FROM_SOURCE_SHA256/GRAFT_FROM_PATCH_BUNDLE_SHA256/GRAFT_REASON require LADDER_PROFILE=graft" >&2
  exit 1
fi
if [ "$LADDER_PROFILE" != "bridge" ] && \
   [ -n "$BRIDGE_WARM_SHA256$BRIDGE_WARM_OBS_VERSION$BRIDGE_PROVENANCE$BRIDGE_REASON" ]; then
  echo "BRIDGE_WARM_SHA256/BRIDGE_WARM_OBS_VERSION/BRIDGE_PROVENANCE/BRIDGE_REASON require LADDER_PROFILE=bridge" >&2
  exit 1
fi
case "$LADDER_PROFILE" in
  ladder-rung)
    ;;
  graft)
    : "${GRAFT_FROM_SOURCE_SHA256:?GRAFT_FROM_SOURCE_SHA256 is required for LADDER_PROFILE=graft}"
    : "${GRAFT_FROM_PATCH_BUNDLE_SHA256:?GRAFT_FROM_PATCH_BUNDLE_SHA256 is required for LADDER_PROFILE=graft}"
    : "${GRAFT_REASON:?GRAFT_REASON is required for LADDER_PROFILE=graft}"
    ;;
  bridge)
    : "${BRIDGE_WARM_SHA256:?BRIDGE_WARM_SHA256 is required for LADDER_PROFILE=bridge}"
    : "${BRIDGE_WARM_OBS_VERSION:?BRIDGE_WARM_OBS_VERSION is required for LADDER_PROFILE=bridge}"
    : "${BRIDGE_PROVENANCE:?BRIDGE_PROVENANCE is required for LADDER_PROFILE=bridge}"
    : "${BRIDGE_REASON:?BRIDGE_REASON is required for LADDER_PROFILE=bridge}"
    ;;
  *)
    echo "LADDER_PROFILE must be ladder-rung, graft or bridge, got '$LADDER_PROFILE'" >&2
    exit 1
    ;;
esac
# The screen refuses GRAFT_* on any profile but graft and BRIDGE_* on any
# profile but bridge, so forward each set only there; the shared knobs go on
# every profile.
GRAFT_ENV=()
if [ "$LADDER_PROFILE" = "graft" ]; then
  GRAFT_ENV=(GRAFT_FROM_SOURCE_SHA256="$GRAFT_FROM_SOURCE_SHA256" \
             GRAFT_FROM_PATCH_BUNDLE_SHA256="$GRAFT_FROM_PATCH_BUNDLE_SHA256" \
             GRAFT_REASON="$GRAFT_REASON")
elif [ "$LADDER_PROFILE" = "bridge" ]; then
  GRAFT_ENV=(BRIDGE_WARM_SHA256="$BRIDGE_WARM_SHA256" \
             BRIDGE_WARM_OBS_VERSION="$BRIDGE_WARM_OBS_VERSION" \
             BRIDGE_PROVENANCE="$BRIDGE_PROVENANCE" \
             BRIDGE_REASON="$BRIDGE_REASON")
fi
# Rung-shaped profiles run ONE arm at SEED; the arm is LADDER_ARM (s_both by
# default, see run_reward_screen.sh), and the screen names the result after
# it, so the marker must be derived from the same value. A hardcoded s_both
# here silently failed to publish the first r0 rung (D256).
LADDER_ARM="${LADDER_ARM:-s_both}"
TAG="${PREFIX}-${LADDER_ARM}-s${SEED}"

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
echo "  bot    scripted_bank_tag=$SCRIPTED_BANK_TAG scripted_bot_type=$SCRIPTED_BOT_TYPE"
echo "  profile $LADDER_PROFILE"
[ "$LADDER_PROFILE" != "graft" ] || \
  echo "  graft  from source=$GRAFT_FROM_SOURCE_SHA256 patch=$GRAFT_FROM_PATCH_BUNDLE_SHA256 reason=$GRAFT_REASON"
[ "$LADDER_PROFILE" != "bridge" ] || \
  echo "  bridge warm_sha256=$BRIDGE_WARM_SHA256 obs_version=$BRIDGE_WARM_OBS_VERSION provenance=$BRIDGE_PROVENANCE reason=$BRIDGE_REASON"
echo "  bank   $(sha256sum "$C/vendor/PufferLib/resources/bloodbowl/state_bank.bbs" 2>/dev/null | cut -c1-16)"
echo "  out    $OUT"
echo "  screen $SCREEN_DIR"

# The screen blocks until the arm is accepted (or fails closed) and writes
# SCREEN_COMPLETE.json itself; there is no detached-launch race to guard here.
# It also owns the live integrity guard, the trainer wrapper's atomic status,
# and the acceptance gate. Bound by a wall-clock deadline so a wedged trainer
# cannot hold the campaign forever.
timeout --signal=TERM --kill-after=120 "$((DEADLINE_HOURS * 3600))" \
  env ${GRAFT_ENV[@]+"${GRAFT_ENV[@]}"} \
      SCREEN_PROFILE="$LADDER_PROFILE" PREFIX="$PREFIX" OUT_DIR="$SCREEN_DIR" \
      STEPS="$STEPS" WARM="$WARM" POOL="$POOL" \
      EXPECTED_POOL_HASH="$EXPECTED_POOL_HASH" \
      LADDER_ENDZONE_MAXDIST="$RUNG" LADDER_RESET_PCT="$RESET_PCT" \
      LADDER_SEED="$SEED" LADDER_CHAIN_LR_SCALE="${LADDER_CHAIN_LR_SCALE:-1}" \
      LADDER_ARM="$LADDER_ARM" \
      SCRIPTED_BANK_TAG="$SCRIPTED_BANK_TAG" \
      SCRIPTED_BOT_TYPE="$SCRIPTED_BOT_TYPE" \
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

# D244: an accepted-but-collapsed rung must not become lineage. The screen's
# acceptance gate is an integrity gate (counters, floors, schema); it says
# nothing about whether the policy still plays. When the warm came from a rung
# with the SAME start distribution (WARM_MARKER: same rung + reset_pct), refuse
# to publish if this rung's eval tds fell below LADDER_REGRESSION_FLOOR times
# the warm rung's eval tds. Different start distributions are not comparable
# (CLAUDE.md), so the gate is skipped there. A refused rung leaves no marker;
# the supervisor retries into a fresh attempt dir and halts at its cap, which
# is the desired outcome for a collapsed lineage -- stop and page.
WARM_MARKER="${WARM_MARKER:-}"
LADDER_REGRESSION_FLOOR="${LADDER_REGRESSION_FLOOR:-0.5}"

# Publish the rung marker only from the screen's own accepted result, so the
# checkpoint path recorded here is the one whose lineage sidecar was written.
python3 - "$RESULT" "$OUT/LADDER_RUNG_COMPLETE.json" "$RUNG" "$RESET_PCT" \
    "$STEPS" "$SEED" "$WARM" "$EXPECTED_POOL_HASH" "$PREFIX" \
    "$WARM_MARKER" "$LADDER_REGRESSION_FLOOR" \
    "$SCRIPTED_BANK_TAG" "$SCRIPTED_BOT_TYPE" "$LADDER_PROFILE" \
    "$GRAFT_FROM_SOURCE_SHA256" "$GRAFT_FROM_PATCH_BUNDLE_SHA256" \
    "$GRAFT_REASON" \
    "$BRIDGE_WARM_SHA256" "$BRIDGE_WARM_OBS_VERSION" "$BRIDGE_PROVENANCE" \
    "$BRIDGE_REASON" <<'PY'
import json, os, sys
(result_path, out_path, rung, reset_pct, steps, seed, warm, pool_hash, prefix,
 warm_marker, floor,
 scripted_bank_tag, scripted_bot_type, profile, graft_source, graft_patch,
 graft_reason, bridge_warm_sha256, bridge_warm_obs_version, bridge_provenance,
 bridge_reason) = sys.argv[1:]
result = json.load(open(result_path, encoding="utf-8"))
if not result.get("acceptance_pass"):
    raise SystemExit(f"result is not accepted: {result_path}")
regression = None
if warm_marker and os.path.isfile(warm_marker):
    wm = json.load(open(warm_marker, encoding="utf-8"))
    same_dist = (int(wm.get("rung", -1)) == int(rung) and
                 abs(float(wm.get("reset_pct", -1)) - float(reset_pct)) < 1e-9)
    warm_tds = wm.get("eval_tds")
    if same_dist and isinstance(warm_tds, (int, float)) and warm_tds > 0:
        this_tds = float(result["eval_metrics"]["tds"])
        regression = {"warm_marker": warm_marker, "warm_eval_tds": warm_tds,
                      "eval_tds": this_tds, "floor": float(floor)}
        if this_tds < float(floor) * float(warm_tds):
            raise SystemExit(
                f"REGRESSION GATE: eval tds {this_tds:.4f} < {float(floor)} x warm "
                f"rung tds {warm_tds:.4f} ({warm_marker}); refusing to publish "
                "this rung as lineage (D244)")
payload = {
    "prefix": prefix,
    "tag": result["tag"],
    "rung": int(rung),
    "reset_pct": float(reset_pct),
    "scripted_bank_tag": int(scripted_bank_tag),
    "scripted_bot_type": int(scripted_bot_type),
    "chain_lr_scale": float(os.environ.get("LADDER_CHAIN_LR_SCALE", "1")),
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
    "eval_tds": float(result["eval_metrics"]["tds"]),
    "eval_perf": float(result["eval_metrics"]["perf"]),
    "regression_gate": regression,
    "trainer_exit": 0,
    "profile": profile,
    "arm": os.environ.get("LADDER_ARM", "s_both"),
}
if profile == "graft":
    payload["graft"] = {
        "from_source_sha256": graft_source,
        "from_patch_bundle_sha256": graft_patch,
        "reason": graft_reason,
    }
if profile == "bridge":
    # The marker is what the next stage reads to chain from; naming the raw
    # warm here keeps the out-of-lineage origin visible at the campaign
    # level, not only inside the sidecar's ancestry.bridged_from.
    payload["bridge"] = {
        "warm_sha256": bridge_warm_sha256,
        "warm_observation_version": int(bridge_warm_obs_version),
        "provenance": bridge_provenance,
        "reason": bridge_reason,
    }
with open(out_path, "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)
    handle.write("\n")
print("wrote", out_path)
PY
