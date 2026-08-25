#!/usr/bin/env bash
# Run a paired native reward screen sequentially on one owned GPU.
# Seed 43 reverses seed 42's arm order to reduce time/order confounding.
#
# SCREEN_MANIFEST.json records the provenance a later analysis actually needs:
# the compiled obs-v6/exact-joint-v1 module identity, the complete reward
# manifest hashes, the Puffer patch bundle, and the warm/pool lineage. Each
# arm's acceptance evidence lands in <tag>.result.json. Restarting the screen is
# expected and safe: completed arms are re-validated, unfinished ones relaunch.
# Example (current possession/gain screen):
#   WARM=/abs/warm.bin POOL=/abs/pool STEPS=500000000 \
#     EXPECTED_POOL_HASH=<sha256> SCREEN_PROFILE=possession-gain \
#     PREFIX=possession-gain-v2 bash tools/run_reward_screen.sh
# Example (fresh pool-free exact-action canary before a long run):
#   STEPS=50000000 SCREEN_PROFILE=exact-action-canary \
#     PREFIX=exact-action-canary-50m bash tools/run_reward_screen.sh
set -euo pipefail

if [ $# -ne 0 ]; then
  echo "run_reward_screen.sh accepts configuration through named environment variables only" >&2
  exit 1
fi

LAUNCH_CWD="$PWD"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STEPS:?STEPS is required (explicit experiment budget)}"
: "${SCREEN_PROFILE:?SCREEN_PROFILE is required (distance-possession, possession-gain, possession-gain-exact, exact-action-canary, genesis, genesis-pool, ladder-rung, graft, bridge, paired-confirmation, paired-final, or control-final)}"
CANDIDATE_ARM="${CANDIDATE_ARM:-}"
TRANSFER_COMPLETE="${TRANSFER_COMPLETE:-}"
EXPECTED_TRANSFER_SHA256="${EXPECTED_TRANSFER_SHA256:-}"
PREFIX="${PREFIX:-reward-screen-v1}"
OUT_DIR="${OUT_DIR:-$ROOT/runs/reward-screens/$PREFIX}"
POLL_SECONDS="${POLL_SECONDS:-30}"
PLAN_ONLY="${PLAN_ONLY:-0}"
ARM_DETACH="${ARM_DETACH:-1}"
# ladder-rung only: the backplay curriculum knobs and the learner seed. Every
# other profile pins these to the launcher defaults (kickoff starts, seed from
# the schedule); the rung profile is the one place the start distribution is a
# declared factor. Validated below, before any artifact is touched.
LADDER_ENDZONE_MAXDIST="${LADDER_ENDZONE_MAXDIST:-}"
LADDER_RESET_PCT="${LADDER_RESET_PCT:-}"
LADDER_SEED="${LADDER_SEED:-}"
# Rung-shaped profiles (ladder-rung, graft, bridge) train ONE arm. s_both is
# the lineage reward every root and bank was minted on; `sparse` is the
# objective-only manifest (s4_sparse: td/win/draw, no dense terms) added after
# the 2026-08-20 audit measured s0_both at 94% shaping mass with a net-negative
# touchdown step. The arm is a declared factor, recorded in the contract and
# the rung marker, never inferred from the reward hash after the fact.
# `r0` is the July reward (r0_full, legacy raw-delta distance) so a bridged
# July checkpoint can be continued under the reward its critic was fitted to:
# D253 measured that switching that warm to s0_both or to sparse at LR 2.8e-4
# decays it within 500M steps, and a same-reward continuation is the control
# that separates reward mismatch from the optimizer step. `r0_dist_half` is
# the first distance-anneal step (r0_full with both raw-delta distance
# coefficients halved) for a chained rung warm-started from a fitted r0 rung.
LADDER_ARM="${LADDER_ARM:-s_both}"
case "$LADDER_ARM" in
  s_both|sparse|r0|r0_dist_half|r0_dist_quarter|r0_dist_zero|r0_dist_ball_half|r0_poss_half|r0_poss_quarter|r0_poss_zero|r0_gain_half|r0_poss_half_gain_half) ;;
  *) echo "LADDER_ARM must be s_both, sparse, r0, r0_dist_half, r0_dist_quarter, r0_dist_zero, r0_dist_ball_half, r0_poss_half, r0_poss_quarter, r0_poss_zero, r0_gain_half or r0_poss_half_gain_half, got '$LADDER_ARM'" >&2; exit 1 ;;
esac
# ladder-rung only: scripted BANK. SCRIPTED_BANK_TAG=b+1 replaces frozen bank
# b's seat with a scripted bot in that bank's envs (bloodbowl.h
# scripted_bank_tag; contact 0 / offense 1). Unset means 0 for a rung and is
# then passed and recorded EXPLICITLY, so "no bot" is a declared value.
SCRIPTED_BANK_TAG="${SCRIPTED_BANK_TAG:-}"
SCRIPTED_BOT_TYPE="${SCRIPTED_BOT_TYPE:-}"
# graft only: the reviewed lineage bridge across a source/patch-bundle change.
# The operator declares the OLD build (source + patch bundle) some of the
# warm/pool sidecars still bind, and why (GRAFT_REASON, e.g. "D242"); the
# per-arm launcher re-checks the same declaration with the same rule.
GRAFT_FROM_SOURCE_SHA256="${GRAFT_FROM_SOURCE_SHA256:-}"
GRAFT_FROM_PATCH_BUNDLE_SHA256="${GRAFT_FROM_PATCH_BUNDLE_SHA256:-}"
GRAFT_REASON="${GRAFT_REASON:-}"
# bridge only: the reviewed warm start from an OUT-OF-LINEAGE raw blob (an
# obs-v4/obs-v5-era checkpoint with no sidecar; docs/audit-2026-08-20.md F2).
# The operator declares the blob's content hash, its original observation
# version, where it came from and why; the per-arm launcher re-checks the
# declaration (hash equality against WARM included) and the published sidecar
# records it as ancestry.bridged_from.
BRIDGE_WARM_SHA256="${BRIDGE_WARM_SHA256:-}"
BRIDGE_WARM_OBS_VERSION="${BRIDGE_WARM_OBS_VERSION:-}"
BRIDGE_PROVENANCE="${BRIDGE_PROVENANCE:-}"
BRIDGE_REASON="${BRIDGE_REASON:-}"
# ladder-rung / graft / bridge only: scale the trainer's LR and entropy
# coefficient for a CHAINED warm restart. D245: a settled policy re-annealed
# from the top (0.00028 / 0.009) into a pool of >=-strength selves dips into
# passivity for ~0.5-2B steps; resuming near the warm rung's FINAL values
# (min-lr ratio 0.1 => scale 0.1) was the hypothesised fix. The 2026-08-20
# audit (F1) then found that 0.1 under Muon freezes training outright (kl and
# clipfrac 0.000 on 38,206 of 38,207 updates), so 1 is the default everywhere
# again; the knob stays for explicit experiments. 1 = the fixed contract.
LADDER_CHAIN_LR_SCALE="${LADDER_CHAIN_LR_SCALE:-1}"
# ladder-rung / graft / bridge only: scale ONLY the entropy coefficient, on
# top of LADDER_CHAIN_LR_SCALE (which scales LR and entropy together). Lets a
# chained rung probe entropy alone; 1 = the fixed contract. Same domain and
# validation as the LR scale.
LADDER_CHAIN_ENT_SCALE="${LADDER_CHAIN_ENT_SCALE:-1}"

# Fixed Stage-1 causal contract. Assign, rather than inherit, every optional
# launcher input which could alter optimization, batching, or pool allocation.
TOTAL_AGENTS=2048
NUM_BUFFERS=2
# Env-stepping thread count is a HOST property, not an optimization factor:
# it changes wall-clock only (the vec batch is TOTAL_AGENTS regardless), so it
# may be overridden per host. 16 was the RTX 2070 rig's core count; a 32-thread
# Vast box left half its CPU idle under it. Recorded in every run manifest.
NUM_THREADS="${NUM_THREADS:-16}"
case "$NUM_THREADS" in
  ''|*[!0-9]*|0) echo "NUM_THREADS must be a positive integer" >&2; exit 1 ;;
esac
# Fraction of ROWS per buffer given to EACH frozen bank; every historical env
# pairs one frozen row with one learner row, so with 4 banks the GAME share is
# about 2x the sum (0.06 x 4 = 24% of rows = 48% of games; the per-arm launcher
# prints the exact historical_game_share). Overridable because the 2026-08-20
# audit found the scripted-bot bank (one of the four) is the only opponent
# that contests the ball, and defense vs it is the exam cell that does not move
# at 0.06. Recorded in the contract settings and every run manifest.
FROZEN_BANK_PCT="${FROZEN_BANK_PCT:-0.06}"
case "$FROZEN_BANK_PCT" in
  0.0[1-9]|0.0[1-9][0-9]|0.[1-9]|0.[1-9][0-9]|0.[1-9][0-9][0-9]) ;;
  *) echo "FROZEN_BANK_PCT must be a decimal in (0.01, 0.999], got '$FROZEN_BANK_PCT'" >&2; exit 1 ;;
esac
EXPECT_BYTES=16066560
LR=0.00028
ENT_COEF=0.009
GAMMA=0.995
# Every arm this screen launches must discount at the SAME gamma its reward
# manifest claims for exact PBRS, or beta*(gamma*Phi' - Phi) is not exact and the
# distance channels quietly reacquire the bias the discounted form removes. The
# per-arm launcher asserts the pair (tools/run_reward_ablation.sh), but it only
# sees the gamma this script passes it, so a divergence here would be invisible:
# assert it once, up front, against every manifest the profile can select.
if ! python3 -c '
import json, pathlib, sys
root, gamma = pathlib.Path(sys.argv[1]), float(sys.argv[2])
bad = []
for m in sorted((root / "puffer/config/rewards").glob("*.json")):
    reward = json.loads(m.read_text(encoding="utf-8")).get("reward", {})
    claimed = reward.get("reward_dist_pbrs_gamma", 0.0)
    if claimed and abs(float(claimed) - gamma) > 1e-9:
        bad.append(f"{m.name} claims {claimed}")
if bad:
    print("; ".join(bad))
    sys.exit(1)
' "$ROOT" "$GAMMA" 2>/dev/null; then
  echo "a reward manifest declares an exact-PBRS gamma other than $GAMMA;" >&2
  echo "  the distance channels would not be exact PBRS under this screen" >&2
  exit 1
fi
GAE_LAMBDA=0.85
HORIZON=64
MINIBATCH_SIZE=16384
CHECKPOINT_STEPS=50000000
REPLAY_RATIO=0.25
CLIP_COEF=0.2
VF_COEF=1.0
VF_CLIP_COEF=0.5
MAX_GRAD_NORM=1.5
EXPECTED_POOL_HASH="${EXPECTED_POOL_HASH:-}"
NUM_FROZEN_BANKS=4
MIN_TRAIN_GAMES=1
MIN_EVAL_GAMES=10000
MAX_PANEL_SILENCE_SECONDS=180

case "$STEPS:$POLL_SECONDS" in
  *[!0-9:]*) echo "STEPS and POLL_SECONDS must be positive integers" >&2; exit 1 ;;
esac
if [ "$STEPS" -le 0 ] || [ "$POLL_SECONDS" -le 0 ] || \
   [ "$POLL_SECONDS" -gt 60 ]; then
  echo "STEPS must be positive; POLL_SECONDS must be in 1..60" >&2
  exit 1
fi
case "$PREFIX" in
  ''|*[!a-zA-Z0-9._-]*)
    echo "PREFIX must use only letters, digits, dot, underscore, or hyphen" >&2
    exit 1 ;;
esac
case "$PLAN_ONLY" in
  0|1) ;;
  *) echo "PLAN_ONLY must be 0 or 1" >&2; exit 1 ;;
esac
case "$ARM_DETACH" in
  0|1) ;;
  *) echo "ARM_DETACH must be 0 or 1" >&2; exit 1 ;;
esac
# The graft profile is a rung across a build change and the bridge profile is
# a rung from an out-of-lineage warm, so both take the rung's knobs; every
# other profile pins them.
RUNG_LIKE=0
case "$SCREEN_PROFILE" in
  ladder-rung|graft|bridge) RUNG_LIKE=1 ;;
esac
if [ "$RUNG_LIKE" != "1" ] && \
   [ -n "$LADDER_ENDZONE_MAXDIST$LADDER_RESET_PCT$LADDER_SEED" ]; then
  echo "LADDER_ENDZONE_MAXDIST, LADDER_RESET_PCT and LADDER_SEED are only valid with SCREEN_PROFILE=ladder-rung, graft or bridge" >&2
  exit 1
fi
if [ "$RUNG_LIKE" != "1" ] && \
   [ -n "$SCRIPTED_BANK_TAG$SCRIPTED_BOT_TYPE" ]; then
  echo "SCRIPTED_BANK_TAG and SCRIPTED_BOT_TYPE are only valid with SCREEN_PROFILE=ladder-rung, graft or bridge" >&2
  exit 1
fi
if [ "$SCREEN_PROFILE" != "graft" ] && \
   [ -n "$GRAFT_FROM_SOURCE_SHA256$GRAFT_FROM_PATCH_BUNDLE_SHA256$GRAFT_REASON" ]; then
  echo "GRAFT_FROM_SOURCE_SHA256, GRAFT_FROM_PATCH_BUNDLE_SHA256 and GRAFT_REASON are only valid with SCREEN_PROFILE=graft" >&2
  exit 1
fi
if [ "$SCREEN_PROFILE" != "bridge" ] && \
   [ -n "$BRIDGE_WARM_SHA256$BRIDGE_WARM_OBS_VERSION$BRIDGE_PROVENANCE$BRIDGE_REASON" ]; then
  echo "BRIDGE_WARM_SHA256, BRIDGE_WARM_OBS_VERSION, BRIDGE_PROVENANCE and BRIDGE_REASON are only valid with SCREEN_PROFILE=bridge" >&2
  exit 1
fi
if [ "$RUNG_LIKE" != "1" ] && [ "$LADDER_CHAIN_LR_SCALE" != "1" ]; then
  echo "LADDER_CHAIN_LR_SCALE is only valid with SCREEN_PROFILE=ladder-rung, graft or bridge" >&2
  exit 1
fi
# (0, 4]: below 1 is the cold-restart form; above 1 is the LR probe the 2026-08-20
# audit asked for (the native optimizer is Muon, so this scale IS the relative
# step; chess.ini runs 2x ours and default.ini 54x). At most three decimals.
case "$LADDER_CHAIN_LR_SCALE" in
  [1-4]|[1-4].[0-9]|[1-4].[0-9][0-9]|[1-4].[0-9][0-9][0-9]|0.[0-9]|0.[0-9][0-9]|0.[0-9][0-9][0-9]) ;;
  *) echo "LADDER_CHAIN_LR_SCALE must be a decimal in (0,4] with at most three decimals" >&2; exit 1 ;;
esac
case "$LADDER_CHAIN_LR_SCALE" in 4.*[1-9]*) echo "LADDER_CHAIN_LR_SCALE must be <= 4" >&2; exit 1 ;; esac
case "$LADDER_CHAIN_LR_SCALE" in 0|0.0|0.00|0.000) echo "LADDER_CHAIN_LR_SCALE must be > 0" >&2; exit 1 ;; esac
if [ "$LADDER_CHAIN_LR_SCALE" != "1" ]; then
  LR="$(python3 -c 'import sys; print(repr(float(sys.argv[1])*float(sys.argv[2])))' "$LR" "$LADDER_CHAIN_LR_SCALE")"
  ENT_COEF="$(python3 -c 'import sys; print(repr(float(sys.argv[1])*float(sys.argv[2])))' "$ENT_COEF" "$LADDER_CHAIN_LR_SCALE")"
fi
if [ "$RUNG_LIKE" != "1" ] && [ "$LADDER_CHAIN_ENT_SCALE" != "1" ]; then
  echo "LADDER_CHAIN_ENT_SCALE is only valid with SCREEN_PROFILE=ladder-rung, graft or bridge" >&2
  exit 1
fi
case "$LADDER_CHAIN_ENT_SCALE" in
  [1-4]|[1-4].[0-9]|[1-4].[0-9][0-9]|[1-4].[0-9][0-9][0-9]|0.[0-9]|0.[0-9][0-9]|0.[0-9][0-9][0-9]) ;;
  *) echo "LADDER_CHAIN_ENT_SCALE must be a decimal in (0,4] with at most three decimals" >&2; exit 1 ;;
esac
case "$LADDER_CHAIN_ENT_SCALE" in 4.*[1-9]*) echo "LADDER_CHAIN_ENT_SCALE must be <= 4" >&2; exit 1 ;; esac
case "$LADDER_CHAIN_ENT_SCALE" in 0|0.0|0.00|0.000) echo "LADDER_CHAIN_ENT_SCALE must be > 0" >&2; exit 1 ;; esac
if [ "$LADDER_CHAIN_ENT_SCALE" != "1" ]; then
  ENT_COEF="$(python3 -c 'import sys; print(repr(float(sys.argv[1])*float(sys.argv[2])))' "$ENT_COEF" "$LADDER_CHAIN_ENT_SCALE")"
fi
case "$SCREEN_PROFILE" in
  distance-possession|possession-gain|possession-gain-exact|exact-action-canary|genesis|genesis-pool|control-final|ladder-rung|graft|bridge)
    [ -z "$CANDIDATE_ARM$TRANSFER_COMPLETE$EXPECTED_TRANSFER_SHA256" ] || {
      echo "candidate transfer inputs are only valid with a paired profile" >&2
      exit 1; }
    if [ "$SCREEN_PROFILE" = "exact-action-canary" ] && \
       [ "$STEPS" -ne 50000000 ]; then
      echo "exact-action-canary requires STEPS=50000000" >&2
      exit 1
    fi
    if [ "$RUNG_LIKE" = "1" ]; then
      # A rung is a start-distribution factor, so both knobs are REQUIRED and
      # explicit; an inherited empty value must not silently train a kickoff
      # arm under a ladder label. maxdist 0 is the legitimate "uniform" rung
      # (any banked start, no endzone filter) and reset_pct 0 is the kickoff
      # graduation rung; the per-arm launcher refuses the no-op pairing
      # (maxdist>0 with reset_pct 0) so it is not repeated here.
      case "$LADDER_ENDZONE_MAXDIST" in
        ''|*[!0-9]*)
          echo "$SCREEN_PROFILE requires LADDER_ENDZONE_MAXDIST as a non-negative integer (0 = uniform bank starts)" >&2
          exit 1 ;;
      esac
      case "$LADDER_RESET_PCT" in
        0|0.0|1|1.0|0.[0-9]|0.[0-9][0-9]|0.[0-9][0-9][0-9]) ;;
        *) echo "$SCREEN_PROFILE requires LADDER_RESET_PCT as a fraction in [0,1] (at most three decimals)" >&2
           exit 1 ;;
      esac
      case "$LADDER_SEED" in
        ''|*[!0-9]*|0[0-9]*)
          echo "$SCREEN_PROFILE requires LADDER_SEED as a canonical non-negative integer" >&2
          exit 1 ;;
      esac
      # The scripted bank is optional; unset resolves to the explicit 0 the
      # per-arm launcher then records. Same domain as the launcher's own gate.
      SCRIPTED_BANK_TAG="${SCRIPTED_BANK_TAG:-0}"
      SCRIPTED_BOT_TYPE="${SCRIPTED_BOT_TYPE:-0}"
      case "$SCRIPTED_BANK_TAG" in
        0|1|2|3|4) ;;
        *) echo "$SCREEN_PROFILE requires SCRIPTED_BANK_TAG as an integer in 0..4 (0 = no scripted bank)" >&2
           exit 1 ;;
      esac
      case "$SCRIPTED_BOT_TYPE" in
        0|1) ;;
        *) echo "$SCREEN_PROFILE requires SCRIPTED_BOT_TYPE as 0 (contact) or 1 (offense)" >&2
           exit 1 ;;
      esac
    fi
    if [ "$SCREEN_PROFILE" = "graft" ]; then
      # The operator declares what is being grafted from; a graft with an
      # inherited or empty declaration would silently accept whatever old
      # build the warm sidecar happens to record.
      for digest_name in GRAFT_FROM_SOURCE_SHA256 GRAFT_FROM_PATCH_BUNDLE_SHA256; do
        if ! [[ "${!digest_name}" =~ ^[0-9a-f]{64}$ ]]; then
          echo "graft requires $digest_name as a lowercase 64-character SHA-256 digest" >&2
          exit 1
        fi
      done
      if [ -z "${GRAFT_REASON// /}" ] || [ "${#GRAFT_REASON}" -gt 200 ]; then
        echo "graft requires GRAFT_REASON as a non-empty string of at most 200 characters (e.g. the DECISIONS.md entry)" >&2
        exit 1
      fi
    fi
    if [ "$SCREEN_PROFILE" = "bridge" ]; then
      # The operator declares which raw blob is being bridged and from which
      # observation revision; an inherited or empty declaration would let any
      # same-size blob ride in under a bridge label. Shape checks here; the
      # hash equality against WARM is asserted by the plan writer and again by
      # the per-arm launcher.
      if ! [[ "$BRIDGE_WARM_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
        echo "bridge requires BRIDGE_WARM_SHA256 as a lowercase 64-character SHA-256 digest (sha256sum of WARM)" >&2
        exit 1
      fi
      case "$BRIDGE_WARM_OBS_VERSION" in
        4|5) ;;
        *) echo "bridge requires BRIDGE_WARM_OBS_VERSION as 4 or 5 (the blob's original observation version)" >&2
           exit 1 ;;
      esac
      if [ -z "${BRIDGE_PROVENANCE// /}" ] || [ "${#BRIDGE_PROVENANCE}" -gt 300 ]; then
        echo "bridge requires BRIDGE_PROVENANCE as a non-empty string of at most 300 characters (e.g. the run dir + ANALYSIS.json)" >&2
        exit 1
      fi
      if [ -z "${BRIDGE_REASON// /}" ] || [ "${#BRIDGE_REASON}" -gt 200 ]; then
        echo "bridge requires BRIDGE_REASON as a non-empty string of at most 200 characters (e.g. the DECISIONS.md entry)" >&2
        exit 1
      fi
    fi
    ;;
  paired-confirmation|paired-final)
    case "$CANDIDATE_ARM" in
      possession_only|gain_only|neither) ;;
      *) echo "$SCREEN_PROFILE requires CANDIDATE_ARM=possession_only, gain_only, or neither" >&2
         exit 1 ;;
    esac
    [ -n "$TRANSFER_COMPLETE" ] || {
      echo "$SCREEN_PROFILE requires TRANSFER_COMPLETE" >&2; exit 1; }
    if ! [[ "$EXPECTED_TRANSFER_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
      echo "$SCREEN_PROFILE requires a lowercase 64-character EXPECTED_TRANSFER_SHA256" >&2
      exit 1
    fi
    ;;
  *) echo "SCREEN_PROFILE must be distance-possession, possession-gain, possession-gain-exact, exact-action-canary, genesis, genesis-pool, ladder-rung, graft, bridge, paired-confirmation, paired-final, or control-final" >&2
     exit 1 ;;
esac

if [ "$SCREEN_PROFILE" = "exact-action-canary" ] || \
   [ "$SCREEN_PROFILE" = "genesis" ] || \
   [ "$SCREEN_PROFILE" = "genesis-pool" ]; then
  # D217/D218: v4 and v5 have the same tensor sizes. An inherited or explicitly
  # empty legacy variable must not silently authorize a same-size warm/pool.
  [ "${WARM+x}" != x ] || {
    echo "$SCREEN_PROFILE forbids WARM; qualification uses fresh obs-v6 initialization" >&2
    exit 1
  }
  [ "${POOL+x}" != x ] || {
    echo "$SCREEN_PROFILE forbids POOL; it trains fresh obs-v6 self-play" >&2
    exit 1
  }
  WARM=""
  POOL=""
  if [ "$SCREEN_PROFILE" = "genesis" ] || [ "$SCREEN_PROFILE" = "genesis-pool" ]; then
    # Same fresh, pool-free shape as the canary; the difference is that an
    # accepted genesis arm publishes ELIGIBLE lineage, which is what lets any
    # later warm/pool profile exist at all. See the mode comment in
    # tools/run_reward_ablation.sh for why this cannot be avoided.
    BOOTSTRAP_MODE=fresh-v6-genesis
  else
    BOOTSTRAP_MODE=fresh-v6-qualification
  fi
  NUM_FROZEN_BANKS=0
  FROZEN_BANK_PCT=0
  EXPECTED_POOL_HASH=""
else
  : "${WARM:?WARM is required}"
  : "${POOL:?POOL is required}"
  if [ "$SCREEN_PROFILE" = "graft" ]; then
    BOOTSTRAP_MODE=graft-v6
  elif [ "$SCREEN_PROFILE" = "bridge" ]; then
    BOOTSTRAP_MODE=bridge-v4
  else
    BOOTSTRAP_MODE=lineage-v6
  fi
fi

abspath() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "$LAUNCH_CWD/$1" ;;
  esac
}
[ -z "$WARM" ] || WARM="$(abspath "$WARM")"
[ -z "$POOL" ] || POOL="$(abspath "$POOL")"
OUT_DIR="$(abspath "$OUT_DIR")"
if [ -n "$TRANSFER_COMPLETE" ]; then
  TRANSFER_COMPLETE="$(abspath "$TRANSFER_COMPLETE")"
  [ -f "$TRANSFER_COMPLETE" ] || {
    echo "missing transfer completion: $TRANSFER_COMPLETE" >&2; exit 1; }
fi
if [ "$BOOTSTRAP_MODE" = "lineage-v6" ] || [ "$BOOTSTRAP_MODE" = "graft-v6" ] || \
   [ "$BOOTSTRAP_MODE" = "bridge-v4" ]; then
  [ -f "$WARM" ] || { echo "missing warm checkpoint: $WARM" >&2; exit 1; }
  [ -d "$POOL" ] || { echo "missing static pool: $POOL" >&2; exit 1; }
  [[ "$EXPECTED_POOL_HASH" =~ ^[0-9a-f]{64}$ ]] || {
    echo "$BOOTSTRAP_MODE screen requires the explicit current EXPECTED_POOL_HASH as a lowercase SHA-256 digest" >&2
    exit 1
  }
fi
if [ "$BOOTSTRAP_MODE" = "bridge-v4" ]; then
  # Fail here, before the lock and the plan, rather than in the plan writer:
  # the declared digest is the only identity a sidecar-less warm has, and a
  # mismatch means a different blob than the reviewed one is being bridged.
  WARM_ACTUAL_SHA256="$(sha256sum "$WARM" | awk '{print $1}')"
  if [ "$WARM_ACTUAL_SHA256" != "$BRIDGE_WARM_SHA256" ]; then
    echo "bridge warm $WARM has sha256 $WARM_ACTUAL_SHA256 but BRIDGE_WARM_SHA256 declares $BRIDGE_WARM_SHA256" >&2
    exit 1
  fi
fi
mkdir -p "$OUT_DIR"

command -v flock >/dev/null 2>&1 || {
  echo "flock is required for the one-screen contract" >&2; exit 1; }
exec 8>"$OUT_DIR/.screen.lock"
if ! flock -n 8; then
  echo "another orchestrator or its detached trainer holds $OUT_DIR/.screen.lock" >&2
  exit 1
fi

PYBIN="$ROOT/vendor/PufferLib/.venv/bin/python"
[ -x "$PYBIN" ] || { echo "vendored Python missing: $PYBIN" >&2; exit 1; }
/bin/bash "$ROOT/tools/install_puffer_env.sh" --check "$ROOT/vendor/PufferLib"

case "$SCREEN_PROFILE" in
  distance-possession)
    arms=(r0 r3 r1 r2 r2 r1 r3 r0)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  possession-gain)
    # LEGACY: these four arms are schema-1 manifests carrying the farmable
    # raw-delta distance form, so a contrast between them is confounded by how
    # much each component subsidises the distance exploit. Retained only so
    # historical curves stay reproducible; use possession-gain-exact for new work.
    arms=(both neither possession_only gain_only \
          gain_only possession_only neither both)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  possession-gain-exact)
    # The same 2x2 on corrected semantics: exact PBRS distance in all four arms
    # and a symmetric ball-gain family. Seed 43 reverses seed 42's arm order to
    # reduce time/order confounding, exactly as the legacy profile does.
    arms=(s_both s_neither s_possession_only s_gain_only \
          s_gain_only s_possession_only s_neither s_both)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  exact-action-canary)
    # Qualification only: one reward-frozen arm bounds repaired-runtime
    # exposure before any causal screen receives a long budget.
    arms=(both)
    seeds=(42)
    ;;
  genesis-pool)
    # Mint the four independent roots a lineage-v6 pool needs. Same reward and
    # recipe as `genesis`, four times, differing only by learner seed.
    #
    # Seeds are 1042-1045, NOT 42-44: those alias paired-final's seed block, and
    # a pool bank sharing a seed with a later confirmation arm invites reading a
    # coincidence as a result.
    #
    # This is a SEED-DIVERSE bootstrap pool, not a curated one. The doctrine's
    # curated composition (weak anchor, era specialist, older ratchet, latest cap)
    # cannot exist yet -- there is no history to draw from. Four from-scratch
    # policies differ by noise alone, which is the correct way to START a ladder
    # and must never later be described as curated. Replace banks as stronger
    # checkpoints appear, and do not read first-generation bank strength as
    # evidence about reward quality.
    arms=(s_both s_both s_both s_both)
    seeds=(1042 1043 1044 1045)
    ;;
  genesis)
    # One fresh arm on the CORRECTED reward, whose accepted
    # checkpoint becomes the root of the obs-v6 lineage. One arm and one seed on
    # purpose: this establishes ancestry, it does not compare anything, so a
    # second arm would only invite reading a contrast that was never controlled.
    # Deliberately `s_both`, the corrected decomposition baseline. Two rewards
    # were rejected for this role: `both` maps to r0_full, whose distance shaping
    # is the farmable raw-delta form, and `pbrs` (r4) fixes distance but still
    # ships reward_ball_loss 0.0 against reward_ball_gain 0.05, violating the
    # invariant stated in bloodbowl.h. A root cannot be corrected after the fact --
    # every descendant that warm-starts from it inherits its habits -- so it gets
    # the reward with no known defect, not merely the newest one.
    arms=(s_both)
    seeds=(42)
    ;;
  graft)
    # The reviewed lineage bridge across a source/patch-bundle change. Shaped
    # exactly like a rung -- one s_both arm at LADDER_SEED, warm + four-bank
    # pool, the rung's start-distribution and scripted-bank knobs -- but some
    # of the warm/pool sidecars were published on an OLD build, so each is
    # validated on its OWN recorded implementation (internally consistent +
    # eligible) and then must bind either this build or the operator's
    # GRAFT_FROM_* declaration (checkpoint_lineage.graft_bridge); the accepted
    # checkpoint is published on the NEW build with ancestry.grafted_from.
    # One arm, one seed: a graft is a lineage step, not a comparison, and it
    # is the only place an implementation change may enter an existing lineage.
    # It stays usable for the rungs after the bridge, whose warm is new-build
    # while the pool still carries old-build banks.
    arms=("$LADDER_ARM")
    seeds=("$LADDER_SEED")
    ;;
  bridge)
    # The reviewed warm start from an OUT-OF-LINEAGE raw blob. Shaped exactly
    # like a rung -- one s_both arm at LADDER_SEED, four-bank pool, the rung's
    # start-distribution and scripted-bank knobs -- but WARM is a sidecar-less
    # obs-v4/obs-v5-era checkpoint, identified only by the operator's
    # BRIDGE_WARM_SHA256 declaration (asserted against the file here and in
    # the per-arm launcher). The pool is NOT bridged: its banks must be
    # eligible obs-v6 sidecars on this build, exactly as lineage-v6 demands.
    # The accepted checkpoint is published with ancestry.bridged_from and is
    # ordinary eligible ancestry thereafter. One arm, one seed: a bridge is a
    # lineage entry point, not a comparison. docs/audit-2026-08-20.md F2 is
    # why it exists: the July obs-v4 R0 checkpoint plays ~6x better than the
    # obs-v6 lineage that was restarted from random weights in its place.
    arms=("$LADDER_ARM")
    seeds=("$LADDER_SEED")
    ;;
  ladder-rung)
    # One rung of the backplay curriculum ladder (6 -> 9 -> 12 -> 0 -> kickoff;
    # CLAUDE.md, D50/D51/D168) run AS A SCREEN so its accepted checkpoint is
    # published with an eligible lineage sidecar and can warm-start the next
    # rung and seed the next pool. tools/launch_ladder_rung.sh could not do
    # that: eligible lineage is only ever written by materialize_result below,
    # after the full acceptance gate (all hard-integrity counters zero in both
    # phases, game floors, schema-2 telemetry), and the rung launcher also ran
    # with no live integrity guard attached. One arm, one seed, on purpose: a
    # rung is a lineage step, not a comparison. Deliberately s_both, the same
    # corrected reward every genesis root and pool bank was minted on.
    arms=("$LADDER_ARM")
    seeds=("$LADDER_SEED")
    ;;
  paired-confirmation)
    arms=(both "$CANDIDATE_ARM" "$CANDIDATE_ARM" both)
    seeds=(42 42 43 43)
    ;;
  paired-final)
    # Three independent learner seeds spend a fixed long-run budget more
    # efficiently than extending only two seeds. Alternating order balances
    # reference/candidate exposure to wall-clock drift.
    arms=(both "$CANDIDATE_ARM" "$CANDIDATE_ARM" both both "$CANDIDATE_ARM")
    seeds=(42 42 43 43 44 44)
    ;;
  control-final)
    # A rejected simplification routes vacation compute into replicated R0
    # trajectories rather than training an objective that failed its gate.
    arms=(both both both)
    seeds=(42 43 44)
    ;;
esac
TOTAL_ARMS=${#arms[@]}
SCREEN_MANIFEST="$OUT_DIR/SCREEN_MANIFEST.json"
SCREEN_STATUS="$OUT_DIR/SCREEN_STATUS.json"
SCREEN_COMPLETE="$OUT_DIR/SCREEN_COMPLETE.json"

manifest_for() {
  case "$1" in
    r0) printf '%s\n' "$ROOT/puffer/config/rewards/r0_full.json" ;;
    # Distance anneal step 1 (chained from a fitted r0 rung): r0_full with both
    # legacy raw-delta distance coefficients halved, everything else identical.
    r0_dist_half) printf '%s\n' "$ROOT/puffer/config/rewards/r0_dist_half.json" ;;
    # Anneal steps 2 and 3: quarter, then zero (same family, reached only by
    # chaining from an accepted earlier anneal rung).
    r0_dist_quarter) printf '%s\n' "$ROOT/puffer/config/rewards/r0_dist_quarter.json" ;;
    r0_dist_zero) printf '%s\n' "$ROOT/puffer/config/rewards/r0_dist_zero.json" ;;
    # Ball-distance-only half step (endzone term intact), for when the paired
    # half step regresses a cell (D264).
    r0_dist_ball_half) printf '%s\n' "$ROOT/puffer/config/rewards/r0_dist_ball_half.json" ;;
    # Possession-annuity-only half step (ball gain and both distance terms
    # intact): the D178 decomposition, after both distance anneals lost the
    # offense-bot cell (D264/D265).
    r0_poss_half) printf '%s\n' "$ROOT/puffer/config/rewards/r0_poss_half.json" ;;
    # Possession-annuity quarter step, chained from the r0_poss_half rung only
    # if that step held on the two-seed exam.
    r0_poss_quarter) printf '%s\n' "$ROOT/puffer/config/rewards/r0_poss_quarter.json" ;;
    # Possession annuity removed, chained from the r0_poss_quarter rung only if
    # that step held on the two-seed exam (D266 accepted the half step).
    r0_poss_zero) printf '%s\n' "$ROOT/puffer/config/rewards/r0_poss_zero.json" ;;
    # Ball-gain-only half step (annuity and both distance terms intact): the
    # other half of the D178 decomposition, chained from the chain 2 frontier.
    r0_gain_half) printf '%s\n' "$ROOT/puffer/config/rewards/r0_gain_half.json" ;;
    # Ball-gain half step with the annuity at the accepted D266 half value: the
    # single-knob gain step from the chain 9 (r0_poss_half) frontier after the
    # quarter annuity step (chain 10) was rejected on the three-seed exam (D268).
    r0_poss_half_gain_half) printf '%s\n' "$ROOT/puffer/config/rewards/r0_poss_half_gain_half.json" ;;
    r1) printf '%s\n' "$ROOT/puffer/config/rewards/r1_no_distance.json" ;;
    r2) printf '%s\n' "$ROOT/puffer/config/rewards/r2_no_possession.json" ;;
    r3) printf '%s\n' "$ROOT/puffer/config/rewards/r3_minimal_block.json" ;;
    both) printf '%s\n' "$ROOT/puffer/config/rewards/r0_full.json" ;;
    # Genesis roots the lineage, so it trains on the CORRECTED distance form
    # rather than the legacy ratchet. r4 differs from r0_full in exactly one
    # declared factor, reward_dist_pbrs_gamma.
    pbrs) printf '%s\n' "$ROOT/puffer/config/rewards/r4_pbrs_distance.json" ;;
    # The corrected decomposition 2x2. All four carry the exact PBRS distance
    # form, so the possession/gain contrast is not confounded by the farmable
    # raw-delta shaping, and the ball-gain family is a symmetric gain/loss pair.
    s_both) printf '%s\n' "$ROOT/puffer/config/rewards/s0_both.json" ;;
    s_possession_only) printf '%s\n' "$ROOT/puffer/config/rewards/s1_possession_only.json" ;;
    s_gain_only) printf '%s\n' "$ROOT/puffer/config/rewards/s2_gain_only.json" ;;
    s_neither) printf '%s\n' "$ROOT/puffer/config/rewards/s3_neither.json" ;;
    # Objective-only (D252 audit arm): touchdown, win, draw; every dense term 0.
    sparse) printf '%s\n' "$ROOT/puffer/config/rewards/s4_sparse.json" ;;
    possession_only) printf '%s\n' "$ROOT/puffer/config/rewards/p1_possession_only.json" ;;
    gain_only) printf '%s\n' "$ROOT/puffer/config/rewards/p2_gain_only.json" ;;
    neither) printf '%s\n' "$ROOT/puffer/config/rewards/r2_no_possession.json" ;;
    *) echo "unknown arm: $1" >&2; return 1 ;;
  esac
}

# The bash arm/seed schedule above is the single definition; the manifest writer
# receives it rather than restating it in Python.
SCHEDULE=()
for index in "${!arms[@]}"; do
  SCHEDULE+=("${arms[$index]}:${seeds[$index]}:$(manifest_for "${arms[$index]}")")
done
SCHEDULE_TEXT="$(printf '%s\n' "${SCHEDULE[@]}")"

# One provenance record per screen: what trained, on which reward manifests,
# from which ancestry. The PPO knobs above are not mirrored here; the per-arm
# launcher writes them into every run manifest, which each result hashes.
# Command substitution, not process substitution: a failed provenance check has
# to fail the screen.
SCREEN_PLAN="$(
  env ROOT="$ROOT" PREFIX="$PREFIX" STEPS="$STEPS" OUT_DIR="$OUT_DIR" \
      SCREEN_PROFILE="$SCREEN_PROFILE" BOOTSTRAP_MODE="$BOOTSTRAP_MODE" \
      CANDIDATE_ARM="$CANDIDATE_ARM" TRANSFER_COMPLETE="$TRANSFER_COMPLETE" \
      EXPECTED_TRANSFER_SHA256="$EXPECTED_TRANSFER_SHA256" \
      WARM="$WARM" POOL="$POOL" EXPECTED_POOL_HASH="$EXPECTED_POOL_HASH" \
      SCHEDULE="$SCHEDULE_TEXT" POLL_SECONDS="$POLL_SECONDS" \
      MAX_PANEL_SILENCE_SECONDS="$MAX_PANEL_SILENCE_SECONDS" \
      TOTAL_AGENTS="$TOTAL_AGENTS" HORIZON="$HORIZON" \
      MINIBATCH_SIZE="$MINIBATCH_SIZE" EXPECT_BYTES="$EXPECT_BYTES" \
      FROZEN_BANK_PCT="$FROZEN_BANK_PCT" \
      NUM_FROZEN_BANKS="$NUM_FROZEN_BANKS" \
      MIN_TRAIN_GAMES="$MIN_TRAIN_GAMES" MIN_EVAL_GAMES="$MIN_EVAL_GAMES" \
      LADDER_ENDZONE_MAXDIST="$LADDER_ENDZONE_MAXDIST" \
      LADDER_RESET_PCT="$LADDER_RESET_PCT" \
      SCRIPTED_BANK_TAG="$SCRIPTED_BANK_TAG" \
      SCRIPTED_BOT_TYPE="$SCRIPTED_BOT_TYPE" \
      GRAFT_FROM_SOURCE_SHA256="$GRAFT_FROM_SOURCE_SHA256" \
      GRAFT_FROM_PATCH_BUNDLE_SHA256="$GRAFT_FROM_PATCH_BUNDLE_SHA256" \
      GRAFT_REASON="$GRAFT_REASON" \
      BRIDGE_WARM_SHA256="$BRIDGE_WARM_SHA256" \
      BRIDGE_WARM_OBS_VERSION="$BRIDGE_WARM_OBS_VERSION" \
      BRIDGE_PROVENANCE="$BRIDGE_PROVENANCE" \
      BRIDGE_REASON="$BRIDGE_REASON" \
      LADDER_CHAIN_LR_SCALE="$LADDER_CHAIN_LR_SCALE" LADDER_CHAIN_ENT_SCALE="$LADDER_CHAIN_ENT_SCALE" \
      LADDER_ARM="$LADDER_ARM" LR="$LR" ENT_COEF="$ENT_COEF" \
      "$PYBIN" - "$SCREEN_MANIFEST" <<'PY'
import datetime, hashlib, json, os, pathlib, subprocess, sys, sysconfig

destination = pathlib.Path(sys.argv[1])
root = pathlib.Path(os.environ["ROOT"]).resolve()
vendor = root / "vendor" / "PufferLib"
profile = os.environ["SCREEN_PROFILE"]
qualification_only = profile == "exact-action-canary"
expect_size = int(os.environ["EXPECT_BYTES"])
warm = pathlib.Path(os.environ["WARM"]).resolve() if os.environ["WARM"] else None
pool = pathlib.Path(os.environ["POOL"]).resolve() if os.environ["POOL"] else None
sys.path.insert(0, str(root / "tools"))
from reward_manifest import load_manifest
from live_integrity_guard import HARD_INTEGRITY_KEYS


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def bundle_sha(paths, labels):
    return hashlib.sha256(b"".join(
        f"{sha(path)}  {label}\n".encode()
        for path, label in zip(paths, labels))).hexdigest()


# obs-v4, obs-v5 and obs-v6 observations are all 2782 bytes, so only source
# compiled-module provenance can tell them apart; one mixup already wasted a
# 12B-step run.
environment_header = root / "puffer/bloodbowl/bloodbowl.h"
if "#define BBE_OBS_VERSION 6" not in environment_header.read_text(
        encoding="utf-8"):
    raise SystemExit("source tree does not declare obs-v6")
source_hash_path = vendor / "ocean/bloodbowl/.content_hash"
if not source_hash_path.is_file():
    raise SystemExit("installed Blood Bowl content hash is missing")
source_hash = source_hash_path.read_text(encoding="utf-8").strip()

# The imported _C, not the source tree, is what will actually train.
extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
if not extension_suffix:
    raise SystemExit("Python did not report an extension-module suffix")
module = vendor / "pufferlib" / ("_C" + extension_suffix)
if not module.is_file():
    raise SystemExit(f"current-Python compiled _C module is missing: {module}")
module_probe = subprocess.run(
    [sys.executable, "-c", """
import json
from pufferlib import _C
print(json.dumps({
    "module": _C.__file__,
    "env_name": getattr(_C, "env_name", None),
    "gpu": int(bool(getattr(_C, "gpu", False))),
    "precision_bytes": int(getattr(_C, "precision_bytes", 0)),
    "exact_action_source_sha256": getattr(
        _C, "exact_action_source_hash", "<missing>"),
    "environment_source_sha256": getattr(
        _C, "environment_source_hash", "<missing>"),
    "observation_abi": getattr(_C, "observation_abi", "<missing>"),
    "observation_version": getattr(
        _C, "observation_version", "<missing>"),
    "action_abi": getattr(_C, "action_abi", "<missing>"),
}, sort_keys=True))
"""], cwd=vendor, text=True, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, check=False)
if module_probe.returncode != 0:
    raise SystemExit(
        "could not interrogate compiled native module: " +
        module_probe.stderr.strip())
compiled_contract = json.loads(module_probe.stdout)
if pathlib.Path(compiled_contract["module"]).resolve() != module.resolve():
    raise SystemExit("imported native module differs from the probed module path")
if (
    compiled_contract["env_name"] != "bloodbowl" or
    compiled_contract["gpu"] != 1 or
    compiled_contract["precision_bytes"] != 4 or
    compiled_contract["environment_source_sha256"] != source_hash or
    compiled_contract["observation_abi"] != "obs-v6" or
    compiled_contract["observation_version"] != 6 or
    compiled_contract["action_abi"] != "exact-joint-v1" or
    len(compiled_contract["exact_action_source_sha256"]) != 64
):
    raise SystemExit(
        "compiled native module does not satisfy the obs-v6/exact-action contract")

# The per-arm launcher recomputes this bundle digest and refuses to train if it
# drifts, so the screen only has to publish the value it launched with.
patches = [
    root / "training/pufferl_env_dashboard_limit.patch",
    root / "training/pufferl_env_json.patch",
    root / "training/pufferl_env_json_metadata_upgrade.patch",
    root / "training/pufferl_env_phase_contract.patch",
    root / "training/pufferl_eval_episode_gate.patch",
    root / "training/pufferl_metrics_keyerror.patch",
    root / "training/torch_pufferl_trusted_load.patch",
    root / "training/selfplay_league.patch",
    root / "training/puffer_exact_joint_actions.patch",
    root / "training/puffer_recurrent_eval_state.patch",
    root / "training/puffer_frozen_prio_mask.patch",
    root / "training/puffer_recurrent_cuda_qualification.patch",
    # D234. Load-bearing that this is IN the bundle, not merely applied: it
    # edits pufferlib/torch_pufferl.py, which is pure Python and therefore does
    # not change compiled_module_sha256. Without this entry a post-patch run
    # could warm-start a pre-patch checkpoint and pass lineage eligibility
    # clean, because vendor_source_sha256 is recorded but never validated
    # (checkpoint_lineage.SHA256_KEYS gates only three digests). Appended at
    # the END: bundle_sha is order-sensitive and run_reward_ablation.sh must
    # recompute the identical digest.
    root / "training/puffer_reward_clamp_range.patch",
]
vendor_sources = [
    "pufferlib/__init__.py", "pufferlib/pufferl.py",
    "pufferlib/selfplay.py", "pufferlib/torch_pufferl.py",
    "pufferlib/models.py", "pufferlib/muon.py", "src/pufferlib.cu",
    "src/bindings.cu", "src/bindings_cpu.cpp", "src/kernels.cu",
    "src/vecenv.h",
]
vendor_paths = [vendor / relative for relative in vendor_sources]
patch_bundle_sha = bundle_sha(patches, [str(path) for path in patches])
vendor_source_sha = bundle_sha(vendor_paths, vendor_sources)
vendor_head_result = subprocess.run(
    ["git", "-C", str(vendor), "rev-parse", "HEAD"],
    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
vendor_head = (vendor_head_result.stdout.strip()
               if vendor_head_result.returncode == 0 else "<not-a-git-checkout>")

# load_manifest rejects an incomplete reward manifest: an omitted field is not
# the same as an explicit zero.
schedule = []
rewards = {}
for index, entry in enumerate(os.environ["SCHEDULE"].splitlines(), 1):
    arm, seed, reward_path = entry.split(":", 2)
    schedule.append({"index": index, "arm": arm, "seed": int(seed)})
    if arm not in rewards:
        reward, digest = load_manifest(reward_path)
        rewards[arm] = {
            "path": str(pathlib.Path(reward_path).resolve()),
            "name": reward["name"], "reward_sha256": digest,
            "file_sha256": sha(reward_path),
        }

rollout_quantum = int(os.environ["TOTAL_AGENTS"]) * int(os.environ["HORIZON"])
train_epochs = int(os.environ["STEPS"]) // rollout_quantum
if train_epochs <= 0:
    raise SystemExit("screen STEPS is smaller than one rollout quantum")
final_steps = train_epochs * rollout_quantum

warm_identity = None
pool_identity = None
warm_lineage_sha = ""
pool_lineage_bundle_sha = ""
# Branch on whether this screen is FRESH, not on whether it is
# qualification-only. Those were the same condition until genesis existed: a
# genesis screen is fresh (no warm start, no pool -- it is the root of the
# lineage) yet deliberately NOT qualification-only, because its accepted
# checkpoint is eligible ancestry. Keying the warm/pool binding off
# qualification_only sent genesis down the warm-start path and called .stat() on
# None. This whole fresh branch had never executed before: the canary profile was
# hard-rejected earlier in this script, so no fresh screen could reach here.
fresh = warm is None and pool is None
if warm is None or pool is None:
    if not fresh:
        raise SystemExit(
            "a fresh screen must carry neither a warm start nor a pool; got "
            f"warm={warm} pool={pool}")
else:
    from checkpoint_lineage import lineage_digest, sidecar_path, validate_lineage
    if warm.stat().st_size != expect_size:
        raise SystemExit(
            f"warm checkpoint is {warm.stat().st_size} bytes; expected {expect_size}")
    # The lineage sidecar is the only thing that keeps an obs-v4 checkpoint out
    # of an obs-v6 run. The per-arm launcher validates the four pool banks the
    # same way, against the same expectations, before it allocates GPU state.
    #
    # graft: some sidecars were published on an OLD build, so the expected
    # implementation overrides are dropped -- each sidecar must still be
    # canonical, hash-bound to its checkpoint, obs-v6/exact-joint-v1 and
    # ELIGIBLE -- and checkpoint_lineage.graft_bridge then requires each of
    # {warm, bank0..3} to bind either this build exactly or the operator's
    # GRAFT_FROM_* declaration. The per-arm launcher applies the same function.
    #
    # bridge: the warm is a RAW out-of-lineage blob with no sidecar, so the
    # warm validation is skipped on purpose (there is nothing to validate; a
    # sidecar that does exist is refused, because such a blob belongs in
    # lineage-v6). Its identity is the operator's BRIDGE_* declaration, hash
    # checked against the file. The pool is validated like lineage-v6's,
    # against THIS build, so a bridge cannot smuggle old banks in.
    graft = profile == "graft"
    bridge = profile == "bridge"
    current_implementation = {
        "source_sha256": source_hash,
        "compiled_module_sha256": sha(module),
        "puffer_patch_bundle_sha256": patch_bundle_sha,
    }
    implementation_expected = None if graft else current_implementation
    graft_identity = None
    bridge_identity = None
    warm_sha = sha(warm)
    if bridge:
        if sidecar_path(warm).exists():
            raise SystemExit(
                f"bridge warm {warm} has a lineage sidecar; a sidecar-bearing "
                "warm must go through ladder-rung (lineage-v6) or graft, not a "
                "bridge")
        declared_sha = os.environ["BRIDGE_WARM_SHA256"]
        if warm_sha != declared_sha:
            raise SystemExit(
                f"bridge warm {warm} has sha256 {warm_sha} but "
                f"BRIDGE_WARM_SHA256 declares {declared_sha}")
        warm_payload = None
        warm_lineage_sha = ""
        bridge_identity = {
            "warm_path": str(warm),
            "warm_sha256": warm_sha,
            "warm_observation_version": int(
                os.environ["BRIDGE_WARM_OBS_VERSION"]),
            "provenance": os.environ["BRIDGE_PROVENANCE"],
            "reason": os.environ["BRIDGE_REASON"],
        }
        warm_identity = {
            "path": str(warm), "bytes": warm.stat().st_size, "sha256": warm_sha,
            "lineage_path": None,
            "lineage_sha256": "",
        }
    else:
        warm_payload = validate_lineage(
            warm, sidecar_path(warm),
            expected=implementation_expected,
            require_eligible=True)
        warm_lineage_sha = lineage_digest(warm_payload)
        warm_identity = {
            "path": str(warm), "bytes": warm.stat().st_size, "sha256": warm_sha,
            "lineage_path": str(sidecar_path(warm).resolve()),
            "lineage_sha256": warm_lineage_sha,
        }
    graft_sidecars = [] if warm_payload is None else [("warm", warm_payload)]
    pool_manifest_raw = (pool / "league_seeds.json").read_bytes()
    banks = json.loads(pool_manifest_raw).get("seeds")
    if not isinstance(banks, list) or len(banks) != 4:
        raise SystemExit("screen pool must contain exactly four banks")
    if bridge:
        # lineage-v6 leaves the pool to the per-arm launcher; a bridge checks
        # it here too, because the pool is the ONLY lineage a bridge has and
        # a 5B-step arm should not be the first place a bad bank is noticed.
        for index, bank in enumerate(banks):
            bank_payload = validate_lineage(
                pool / bank["file"], pool / bank["lineage_file"],
                expected=current_implementation, require_eligible=True)
            if lineage_digest(bank_payload) != bank["lineage_sha256"]:
                raise SystemExit(
                    f"pool bank {index} lineage digest differs from manifest")
    if graft:
        # Same rule for the pool: eligible, internally consistent, on their
        # own recorded build. lineage-v6 leaves this to the per-arm launcher.
        from checkpoint_lineage import LineageError, graft_bridge
        for index, bank in enumerate(banks):
            bank_payload = validate_lineage(
                pool / bank["file"], pool / bank["lineage_file"],
                expected=None, require_eligible=True)
            if lineage_digest(bank_payload) != bank["lineage_sha256"]:
                raise SystemExit(
                    f"pool bank {index} lineage digest differs from manifest")
            graft_sidecars.append((f"pool bank {index}", bank_payload))
        declared_source = os.environ["GRAFT_FROM_SOURCE_SHA256"]
        declared_patch = os.environ["GRAFT_FROM_PATCH_BUNDLE_SHA256"]
        try:
            old_module = graft_bridge(
                graft_sidecars, current=current_implementation,
                old_source_sha256=declared_source,
                old_patch_bundle_sha256=declared_patch)
        except LineageError as exc:
            raise SystemExit(str(exc)) from exc
        graft_identity = {
            "from_source_sha256": declared_source,
            "from_patch_bundle_sha256": declared_patch,
            "from_module_sha256": old_module,
            "warm_lineage_sha256": warm_lineage_sha,
            "reason": os.environ["GRAFT_REASON"],
        }
    pool_lineage_bundle_sha = hashlib.sha256(json.dumps([
        {"bank": index, "checkpoint_sha256": bank["sha256"],
         "lineage_sha256": bank["lineage_sha256"]}
        for index, bank in enumerate(banks)
    ], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    pool_identity = {
        "path": str(pool),
        "manifest_sha256": hashlib.sha256(pool_manifest_raw).hexdigest(),
        "identity_sha256": os.environ["EXPECTED_POOL_HASH"],
        "lineage_bundle_sha256": pool_lineage_bundle_sha,
    }

launcher = root / "tools/run_reward_ablation.sh"
screen_script = root / "tools/run_reward_screen.sh"
game_stats = root / "tools/game_stats.py"
live_integrity_guard = root / "tools/live_integrity_guard.py"
checkpoint_lineage_tool = root / "tools/checkpoint_lineage.py"
status_wrapper = root / "tools/trainer_status_wrapper.sh"
contract = {
    "screen_profile": profile,
    "qualification_only": qualification_only,
    "prefix": os.environ["PREFIX"],
    "out_dir": str(pathlib.Path(os.environ["OUT_DIR"]).resolve()),
    "requested_steps": int(os.environ["STEPS"]),
    "final_steps": final_steps,
    "rollout_quantum": rollout_quantum,
    "schedule": schedule,
    "rewards": rewards,
    "warm": warm_identity,
    "pool": pool_identity,
    "bootstrap": {
        "mode": os.environ["BOOTSTRAP_MODE"],
        "observation_abi": "obs-v6",
        "observation_version": 6,
        "action_abi": "exact-joint-v1",
        # Genesis is fresh yet not qualification-only, so this must key on
        # freshness. checkpoint_lineage cross-checks initialization against the
        # producer mode, so getting this wrong fails the run at publication.
        # A bridge is warm-started yet has no warm lineage, so it is its own
        # initialization rather than lineage-v6 with a blank digest.
        "initialization": ("fresh" if fresh
                           else "bridge" if profile == "bridge"
                           else "lineage-v6"),
        "warm_lineage_sha256": warm_lineage_sha,
        "pool_lineage_bundle_sha256": pool_lineage_bundle_sha,
    },
    # Batching, architecture, and acceptance floors: the values an analysis has
    # to know to read the arms it is comparing.
    "settings": {
        "total_agents": os.environ["TOTAL_AGENTS"],
        "horizon": os.environ["HORIZON"],
        "minibatch_size": os.environ["MINIBATCH_SIZE"],
        "expected_checkpoint_bytes": os.environ["EXPECT_BYTES"],
        "frozen_bank_pct": os.environ["FROZEN_BANK_PCT"],
        "num_frozen_banks": os.environ["NUM_FROZEN_BANKS"],
        "min_train_games": os.environ["MIN_TRAIN_GAMES"],
        "min_eval_games": os.environ["MIN_EVAL_GAMES"],
        "eval_episodes": os.environ["MIN_EVAL_GAMES"],
        "native_precision_bytes": "4",
        "policy_hidden_size": "512",
        "policy_num_layers": "3",
        "policy_expansion_factor": "1",
    },
    "error_budget": {
        "contamination_budget": 0,
        "detection_poll_seconds": int(os.environ["POLL_SECONDS"]),
        "max_panel_silence_seconds": int(
            os.environ["MAX_PANEL_SILENCE_SECONDS"]),
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
    },
    # Which version of the tooling produced this screen. Recorded, not policed:
    # editing game_stats.py mid-screen is a bug to notice in review, not
    # something worth refusing to resume a multi-day run over.
    "implementation": {
        "screen_script_sha256": sha(screen_script),
        "launcher_sha256": sha(launcher),
        "game_stats_sha256": sha(game_stats),
        "live_integrity_guard_sha256": sha(live_integrity_guard),
        "checkpoint_lineage_sha256": sha(checkpoint_lineage_tool),
        "status_wrapper_sha256": sha(status_wrapper),
        "source_sha256": source_hash,
        "compiled_module": str(module.resolve()),
        "compiled_module_sha256": sha(module),
        "compiled_semantic_contract": compiled_contract,
        "puffer_patch_bundle_sha256": patch_bundle_sha,
        "vendor_head": vendor_head,
        "vendor_source_sha256": vendor_source_sha,
    },
}
if profile == "graft":
    contract["graft"] = graft_identity
if profile == "bridge":
    # The bridge identity is part of the contract so the manifest-reuse check
    # below refuses a relaunch that names a different raw blob, observation
    # version or provenance under the same OUT_DIR.
    contract["bridge"] = bridge_identity
if profile in ("ladder-rung", "graft", "bridge"):
    # The start distribution is this profile's declared factor. Recorded here so
    # a rung's SCREEN_MANIFEST says which rung it was without opening the run
    # manifest; the per-arm launcher binds the same values (plus the state-bank
    # digest) into the run manifest that the lineage sidecar hashes.
    contract["ladder"] = {
        "endzone_maxdist": int(os.environ["LADDER_ENDZONE_MAXDIST"]),
        "reset_pct": float(os.environ["LADDER_RESET_PCT"]),
        # Scripted bank: 0 = none. Recorded even when 0 so the contract says
        # which opponent the rung trained against, not merely which starts.
        "scripted_bank_tag": int(os.environ["SCRIPTED_BANK_TAG"]),
        "scripted_bot_type": int(os.environ["SCRIPTED_BOT_TYPE"]),
        "arm": os.environ["LADDER_ARM"],
        "chain_lr_scale": float(os.environ["LADDER_CHAIN_LR_SCALE"]),
        "chain_ent_scale": float(os.environ["LADDER_CHAIN_ENT_SCALE"]),
        "learning_rate": float(os.environ["LR"]),
        "ent_coef": float(os.environ["ENT_COEF"]),
    }
if profile in ("paired-confirmation", "paired-final"):
    from analyze_reward_candidate_transfer import (
        TransferError, validate_completion_evidence,
    )
    contract["candidate_arm"] = os.environ["CANDIDATE_ARM"]
    # Binds recommended_confirmation_arm, the analysis recommendation,
    # transfer_manifest_sha256, analysis_sha256, and the evaluated cell hashes,
    # so a confirmation cannot quietly run an arm the transfer study rejected.
    try:
        contract["candidate_evidence"] = validate_completion_evidence(
            pathlib.Path(os.environ["TRANSFER_COMPLETE"]).resolve(),
            expected_complete_sha=os.environ["EXPECTED_TRANSFER_SHA256"],
            expected_candidate=os.environ["CANDIDATE_ARM"],
        )
    except (OSError, TransferError, ValueError) as exc:
        raise SystemExit(f"invalid candidate transfer evidence: {exc}") from exc

# A retried screen reuses the plan it already published so its accepted arms
# keep one manifest identity -- but only if it IS the same plan. The ladder
# resolves warm/pool at launch time, so a relaunch into an OUT_DIR that holds a
# different contract must fail here rather than stamp results with a plan that
# describes another run.
if destination.exists():
    existing = json.loads(destination.read_text(encoding="utf-8"))
    if existing.get("contract") != contract:
        changed = sorted(
            key for key in set(existing.get("contract", {})) | set(contract)
            if existing.get("contract", {}).get(key) != contract.get(key))
        raise SystemExit(
            "SCREEN_MANIFEST.json already exists with a different contract "
            f"(differs in: {', '.join(changed)}); use a fresh OUT_DIR/PREFIX")
if not destination.exists():
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "schema_version": 1,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "contract": contract,
    }, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(destination)
print(sha(destination), patch_bundle_sha)
PY
)"
read -r SCREEN_MANIFEST_SHA SCREEN_PATCH_BUNDLE_SHA <<<"$SCREEN_PLAN"
if [ "$PLAN_ONLY" = "1" ]; then
  echo "SCREEN PLAN VERIFIED: $SCREEN_MANIFEST"
  echo "screen_manifest_sha256=$SCREEN_MANIFEST_SHA"
  exit 0
fi

CURRENT_ARM=""
CURRENT_SEED=""
CURRENT_INDEX=0
COMPLETED_ARMS=0

write_screen_status() {
  local state=$1 exit_code=$2 message=$3
  "$PYBIN" - "$SCREEN_STATUS" "$SCREEN_MANIFEST_SHA" "$state" \
    "$exit_code" "$CURRENT_ARM" "$CURRENT_SEED" "$CURRENT_INDEX" \
    "$COMPLETED_ARMS" "$message" "$$" <<'PY'
import datetime, json, pathlib, sys
(
    path, manifest_sha, state, exit_code, arm, seed, index,
    completed, message, pid,
) = sys.argv[1:]
payload = {
    "schema_version": 1,
    "screen_manifest_sha256": manifest_sha,
    "state": state,
    "exit_code": int(exit_code),
    "pid": int(pid),
    "current_arm": arm or None,
    "current_seed": int(seed) if seed else None,
    "current_index": int(index),
    "completed_arms": int(completed),
    "message": message,
    "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
destination = pathlib.Path(path)
temporary = destination.with_suffix(destination.suffix + ".tmp")
temporary.write_text(json.dumps(
    payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8")
temporary.replace(destination)
PY
}

screen_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    set +e
    write_screen_status failed "$rc" "screen stopped before all arms passed"
  fi
}
trap screen_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
write_screen_status running 0 "screen plan published; validating or launching arms"

materialize_result() {
  local mode=$1 arm=$2 seed=$3 tag=$4 manifest_path=$5 log=$6 result=$7
  "$PYBIN" - "$ROOT" "$mode" "$arm" "$seed" "$tag" "$manifest_path" \
    "$log" "$result" "$SCREEN_MANIFEST" "$SCREEN_MANIFEST_SHA" \
    "$MIN_TRAIN_GAMES" "$MIN_EVAL_GAMES" "$ARM_DETACH" <<'PY'
import hashlib, json, os, pathlib, sys
(
    root, mode, arm, seed, tag, reward_manifest_path, log_path, result_path,
    screen_manifest_path, screen_manifest_sha, min_train_games, min_eval_games,
    detach,
) = sys.argv[1:]
root = pathlib.Path(root).resolve()
sys.path.insert(0, str(root / "tools"))
from game_stats import (
    completed_game_requirement_met,
    dashboard_windows,
    weighted_dashboard,
)
from reward_manifest import load_manifest
from live_integrity_guard import HARD_INTEGRITY_KEYS
from checkpoint_lineage import (
    lineage_digest, lineage_from_run_manifest, sidecar_path, validate_lineage,
    write_lineage,
)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def need_file(path, label):
    path = pathlib.Path(path)
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    return path


screen = json.loads(need_file(
    screen_manifest_path, "screen manifest").read_text(encoding="utf-8"))["contract"]
log = need_file(log_path, "trainer log")
status_path = need_file(log_path + ".status.json", "trainer status")
process_path = need_file(log_path + ".process.json", "trainer process sidecar")
run_dir_path = need_file(log_path + ".run_dir", "run-directory sidecar")
run_manifest_path = need_file(log_path + ".manifest.json", "run manifest")

run_dir = pathlib.Path(run_dir_path.read_text(encoding="utf-8").strip())
if not run_dir.is_absolute() or not run_dir.is_dir():
    raise SystemExit(f"invalid run directory: {run_dir}")
# Accept a final checkpoint only out of this checkout's trainer output, never a
# production or stale run directory that happens to hold the same step number.
checkpoint_root = (root / "vendor/PufferLib/checkpoints/bloodbowl").resolve()
try:
    run_dir.resolve().relative_to(checkpoint_root)
except ValueError as exc:
    raise SystemExit(
        f"run directory is outside {checkpoint_root}: {run_dir}") from exc
run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
_, expected_reward_sha = load_manifest(reward_manifest_path)
if run_manifest.get("reward_sha256") != expected_reward_sha:
    raise SystemExit(
        f"arm {tag} trained reward {run_manifest.get('reward_sha256')}, "
        f"not this arm's {expected_reward_sha}")

status = json.loads(status_path.read_text(encoding="utf-8"))
process = json.loads(process_path.read_text(encoding="utf-8"))
if int(status["exit_code"]) != 0:
    raise SystemExit(f"trainer status is {status['exit_code']}")
if int(status["pid"]) != int(process["pid"]):
    raise SystemExit("trainer status PID differs from process sidecar")
# ARM_DETACH=0 keeps the trainer inside the queue job's process group; one that
# escapes survives the queue's cleanup and idle-bills the GPU.
expected_process_group = int(process["pid"]) if detach == "1" else os.getpgrp()
if int(process["process_group"]) != expected_process_group:
    raise SystemExit(
        "trainer process group differs from the containment contract: "
        f"{process['process_group']} != {expected_process_group}")

final_steps = int(run_manifest["final_steps"])
if final_steps != int(screen["final_steps"]):
    raise SystemExit("run final step differs from the screen plan")
checkpoint = need_file(run_dir / f"{final_steps:016d}.bin", "exact final checkpoint")
expected_bytes = int(screen["settings"]["expected_checkpoint_bytes"])
if checkpoint.stat().st_size != expected_bytes:
    raise SystemExit(
        f"final checkpoint is {checkpoint.stat().st_size} bytes; expected {expected_bytes}")

lineage_payload = lineage_from_run_manifest(
    checkpoint, run_manifest_path, allow_eligible_publication=True)
lineage_path = sidecar_path(checkpoint)
lineage_sha = lineage_digest(lineage_payload)

integrity = HARD_INTEGRITY_KEYS
required = (
    "n", "tds", "perf", "possession_rate", "blocks_thrown",
    "block_2d_frac", "block_2dred_frac", *integrity,
)
phase_metrics = {
    phase: weighted_dashboard(log, phase=phase)
    for phase in ("train", "eval")
}
failures = []
for phase, metrics in phase_metrics.items():
    missing = [key for key in required if key not in metrics]
    if missing:
        failures.append({
            "phase": phase, "kind": "missing_metrics", "metrics": missing,
        })
    nonzero = {
        key: metrics[key] for key in integrity
        if key in metrics and metrics[key] != 0.0
    }
    if nonzero:
        failures.append({
            "phase": phase, "kind": "integrity_nonzero", "metrics": nonzero,
        })
for phase, minimum in (
        ("train", int(min_train_games)), ("eval", int(min_eval_games))):
    observed = phase_metrics[phase].get("n", 0.0)
    if not completed_game_requirement_met(observed, minimum):
        failures.append({
            "phase": phase, "kind": "insufficient_games",
            "observed": observed, "minimum": minimum,
        })
# A ladder rung is only a rung if the bank actually supplied its starts. The
# per-arm launcher checks that the bank FILE exists; a bank the env rejects at
# load (fingerprint mismatch after a bb_match layout change, or zero resumable
# records) makes every reset a procgen kickoff with all counters clean, so the
# hard-integrity gate alone would accept a kickoff run as a curriculum
# checkpoint. demo_episodes is the per-episode fraction of banked starts; at
# reset_pct p the training phase must show it near p.
ladder = screen.get("ladder")
if ladder and float(ladder["reset_pct"]) > 0.0:
    expected_demo = float(ladder["reset_pct"])
    observed_demo = phase_metrics["train"].get("demo_episodes")
    if observed_demo is None or not (
            expected_demo - 0.15 <= observed_demo <= expected_demo + 0.15):
        failures.append({
            "phase": "train", "kind": "curriculum_inactive",
            "metric": "demo_episodes", "observed": observed_demo,
            "expected": expected_demo,
        })
counted_windows = [
    window for window in dashboard_windows(log)
    if window.get("n", 0.0) > 0.0 and
       window.get("_puffer_final_reprint", 0.0) <= 0.0
]
bad_schema = sorted({
    int(window.get("_puffer_schema", 0.0)) for window in counted_windows
    if int(window.get("_puffer_schema", 0.0)) < 2
})
if bad_schema:
    failures.append({
        "kind": "telemetry_schema", "observed": bad_schema, "minimum": 2,
    })

if not failures:
    if mode == "write":
        write_lineage(lineage_path, lineage_payload)
    recorded_lineage = validate_lineage(
        checkpoint, lineage_path,
        expected={
            "source_sha256": screen["implementation"]["source_sha256"],
            "compiled_module_sha256": screen["implementation"]["compiled_module_sha256"],
            "puffer_patch_bundle_sha256": screen["implementation"]["puffer_patch_bundle_sha256"],
        },
        require_eligible=not screen["qualification_only"],
    )
    if recorded_lineage != lineage_payload:
        raise SystemExit("checkpoint lineage differs from recomputed run evidence")

result = {
    "schema_version": 2,
    "trainer_complete": True,
    "acceptance_pass": not failures,
    "acceptance_failures": failures,
    "arm": arm,
    "seed": int(seed),
    "tag": tag,
    "screen_manifest_sha256": screen_manifest_sha,
    "log": str(log),
    "log_sha256": sha(log),
    "status_sha256": sha(status_path),
    "process_sha256": sha(process_path),
    "run_manifest_sha256": sha(run_manifest_path),
    "reward_sha256": expected_reward_sha,
    "checkpoint": str(checkpoint),
    "checkpoint_bytes": checkpoint.stat().st_size,
    "checkpoint_sha256": sha(checkpoint),
    "checkpoint_lineage": str(lineage_path),
    "checkpoint_lineage_sha256": lineage_sha,
    "qualification_only": screen["qualification_only"],
    "train_metrics": phase_metrics["train"],
    "eval_metrics": phase_metrics["eval"],
}
path = pathlib.Path(result_path)
if mode == "validate":
    # Acceptance was just recomputed from the log above, so the recorded
    # sidecar only has to agree about the arm it accepted.
    recorded = json.loads(path.read_text(encoding="utf-8"))
    if recorded.get("acceptance_pass") is not True:
        raise SystemExit(f"recorded result is not an accepted arm: {path}")
    if recorded.get("checkpoint_sha256") != result["checkpoint_sha256"]:
        raise SystemExit(
            f"recorded result belongs to a different checkpoint: {path}")
elif mode == "write":
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(
        result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    temporary.replace(path)
else:
    raise SystemExit(f"unknown result mode: {mode}")

print(json.dumps({
    "arm": arm, "seed": int(seed), "acceptance_pass": not failures,
    "checkpoint_sha256": result["checkpoint_sha256"],
}, sort_keys=True))
print(json.dumps({
    key: phase_metrics["eval"].get(key)
    for key in ("n", "tds", "perf", "possession_rate", "blocks_thrown",
                "block_2d_frac", "block_2dred_frac", "illegal_frac")
}, sort_keys=True))
if failures:
    raise SystemExit(
        "arm completed but failed screen acceptance: " +
        json.dumps(failures, sort_keys=True))
PY
}

terminate_current_arm() {
  local pid=$1 process_group=$2
  if [ "$ARM_DETACH" = "1" ]; then
    kill -TERM -- "-$process_group" 2>/dev/null || true
  else
    # Queue-owned screens share the queue job's process group. Signal only the
    # recorded wrapper; its TERM trap forwards to the exact trainer child.
    kill -TERM "$pid" 2>/dev/null || true
  fi
  for _ in $(seq 1 40); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.25
  done
  if [ "$ARM_DETACH" = "1" ]; then
    kill -KILL -- "-$process_group" 2>/dev/null || true
  else
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

guard_complete_log() {
  local log=$1
  "$PYBIN" "$ROOT/tools/live_integrity_guard.py" \
    --log "$log" --state "${log}.live-integrity-screen-state.json" \
    --failure "$OUT_DIR/LIVE_INTEGRITY_FAILURE.json" \
    --complete-log \
    --max-panel-silence-seconds "$MAX_PANEL_SILENCE_SECONDS"
}

wait_for_status() {
  local tag=$1 log=$2
  local process="${log}.process.json"
  [ -f "$process" ] || {
    echo "missing process sidecar after launcher returned for $tag" >&2
    return 1
  }
  local pid process_group guard_state guard_failure
  read -r pid process_group < <($PYBIN - "$process" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(int(payload["pid"]), int(payload["process_group"]))
PY
)
  # The durable watchdog is a redundant writer. Keep its incremental cursor
  # independent so overlapping polls cannot race or roll this cursor backward.
  guard_state="${log}.live-integrity-screen-state.json"
  guard_failure="$OUT_DIR/LIVE_INTEGRITY_FAILURE.json"
  while [ ! -f "${log}.status.json" ]; do
    if ! "$PYBIN" "$ROOT/tools/live_integrity_guard.py" \
        --log "$log" --state "$guard_state" --failure "$guard_failure" \
        --max-panel-silence-seconds "$MAX_PANEL_SILENCE_SECONDS"; then
      echo "hard-integrity error budget exhausted; terminating $tag" >&2
      terminate_current_arm "$pid" "$process_group"
      write_screen_status failed 1 "hard-integrity error budget exhausted"
      return 1
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
      for _ in $(seq 1 10); do
        [ -f "${log}.status.json" ] && break
        sleep 1
      done
      [ -f "${log}.status.json" ] || {
        echo "trainer wrapper $pid vanished before status publication for $tag" >&2
        tail -40 "$log" >&2 || true
        return 1
      }
      break
    fi
    steps_seen="$(grep -aoE 'Steps +[0-9.]+[KMBT]?' "$log" | tail -1 || true)"
    echo "WAIT arm=$CURRENT_ARM seed=$CURRENT_SEED ${steps_seen:-steps=starting}"
    write_screen_status running 0 "waiting for current trainer"
    sleep "$POLL_SECONDS"
  done
  guard_complete_log "$log"
}

for index in "${!arms[@]}"; do
  arm="${arms[$index]}"
  seed="${seeds[$index]}"
  manifest="$(manifest_for "$arm")"
  tag="${PREFIX}-${arm}-s${seed}"
  log="$OUT_DIR/${tag}.log"
  result="$OUT_DIR/${tag}.result.json"
  CURRENT_ARM="$arm"
  CURRENT_SEED="$seed"
  CURRENT_INDEX=$((index + 1))
  write_screen_status running 0 "validating arm artifacts"

  if [ -f "$result" ]; then
    guard_complete_log "$log"
    materialize_result validate "$arm" "$seed" "$tag" "$manifest" \
      "$log" "$result"
    COMPLETED_ARMS=$((COMPLETED_ARMS + 1))
    echo "SKIP verified arm=$arm seed=$seed result=$result"
    continue
  fi

  partial=0
  for artifact in "$log" "${log}.manifest.json" "${log}.status.json" \
                  "${log}.run_dir" "${log}.process.json"; do
    [ -e "$artifact" ] && partial=1
  done
  if [ "$partial" -eq 1 ]; then
    if [ ! -f "${log}.status.json" ]; then
      echo "incomplete arm artifacts exist without an atomic status: $log*" >&2
      echo "the screen lock proves no inherited trainer is still live" >&2
      exit 1
    fi
    exit_code="$($PYBIN - "${log}.status.json" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1], encoding="utf-8"))["exit_code"]))
PY
)"
    [ "$exit_code" -eq 0 ] || {
      echo "cannot recover failed arm=$arm seed=$seed exit=$exit_code" >&2
      tail -40 "$log" >&2 || true
      exit 1
    }
    echo "RECOVER completed detached arm=$arm seed=$seed"
  else
    echo "START index=$CURRENT_INDEX/$TOTAL_ARMS arm=$arm seed=$seed steps=$STEPS tag=$tag"
    write_screen_status running 0 "launching arm"
    LADDER_ENV=()
    if [ "$SCREEN_PROFILE" = "ladder-rung" ]; then
      LADDER_ENV=(LADDER_ENDZONE_MAXDIST="$LADDER_ENDZONE_MAXDIST" \
                  LADDER_RESET_PCT="$LADDER_RESET_PCT" \
                  SCRIPTED_BANK_TAG="$SCRIPTED_BANK_TAG" \
                  SCRIPTED_BOT_TYPE="$SCRIPTED_BOT_TYPE")
    elif [ "$SCREEN_PROFILE" = "graft" ]; then
      LADDER_ENV=(LADDER_ENDZONE_MAXDIST="$LADDER_ENDZONE_MAXDIST" \
                  LADDER_RESET_PCT="$LADDER_RESET_PCT" \
                  SCRIPTED_BANK_TAG="$SCRIPTED_BANK_TAG" \
                  SCRIPTED_BOT_TYPE="$SCRIPTED_BOT_TYPE" \
                  GRAFT_FROM_SOURCE_SHA256="$GRAFT_FROM_SOURCE_SHA256" \
                  GRAFT_FROM_PATCH_BUNDLE_SHA256="$GRAFT_FROM_PATCH_BUNDLE_SHA256" \
                  GRAFT_REASON="$GRAFT_REASON")
    elif [ "$SCREEN_PROFILE" = "bridge" ]; then
      LADDER_ENV=(LADDER_ENDZONE_MAXDIST="$LADDER_ENDZONE_MAXDIST" \
                  LADDER_RESET_PCT="$LADDER_RESET_PCT" \
                  SCRIPTED_BANK_TAG="$SCRIPTED_BANK_TAG" \
                  SCRIPTED_BOT_TYPE="$SCRIPTED_BOT_TYPE" \
                  BRIDGE_WARM_SHA256="$BRIDGE_WARM_SHA256" \
                  BRIDGE_WARM_OBS_VERSION="$BRIDGE_WARM_OBS_VERSION" \
                  BRIDGE_PROVENANCE="$BRIDGE_PROVENANCE" \
                  BRIDGE_REASON="$BRIDGE_REASON")
    fi
    env ${LADDER_ENV[@]+"${LADDER_ENV[@]}"} \
        TAG="$tag" REWARD_MANIFEST="$manifest" WARM="$WARM" POOL="$POOL" \
        BOOTSTRAP_MODE="$BOOTSTRAP_MODE" \
        STEPS="$STEPS" SEED="$seed" LOG="$log" RIG_ALLOW_FLOAT=1 \
        SCREEN_MANIFEST_SHA256="$SCREEN_MANIFEST_SHA" DRY_RUN=0 \
        EXPECTED_PUFFER_PATCH_BUNDLE_SHA256="$SCREEN_PATCH_BUNDLE_SHA" \
        TOTAL_AGENTS="$TOTAL_AGENTS" NUM_BUFFERS="$NUM_BUFFERS" \
        NUM_THREADS="$NUM_THREADS" FROZEN_BANK_PCT="$FROZEN_BANK_PCT" \
        EXPECT_BYTES="$EXPECT_BYTES" LR="$LR" ENT_COEF="$ENT_COEF" \
        GAMMA="$GAMMA" GAE_LAMBDA="$GAE_LAMBDA" HORIZON="$HORIZON" \
        MINIBATCH_SIZE="$MINIBATCH_SIZE" CHECKPOINT_STEPS="$CHECKPOINT_STEPS" \
        REPLAY_RATIO="$REPLAY_RATIO" CLIP_COEF="$CLIP_COEF" \
        VF_COEF="$VF_COEF" VF_CLIP_COEF="$VF_CLIP_COEF" \
        MAX_GRAD_NORM="$MAX_GRAD_NORM" EXPECTED_POOL_HASH="$EXPECTED_POOL_HASH" \
        DETACH="$ARM_DETACH" \
        QUEUE_OWNED="$([ "$ARM_DETACH" = "0" ] && printf 1 || printf 0)" \
        LIVE_INTEGRITY_FAILURE="$OUT_DIR/LIVE_INTEGRITY_FAILURE.json" \
        LIVE_INTEGRITY_MAX_SILENCE="$MAX_PANEL_SILENCE_SECONDS" \
        LIVE_INTEGRITY_POLL_SECONDS="$POLL_SECONDS" \
        /bin/bash "$ROOT/tools/run_reward_ablation.sh"
    wait_for_status "$tag" "$log"
  fi

  exit_code="$($PYBIN - "${log}.status.json" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1], encoding="utf-8"))["exit_code"]))
PY
)"
  if [ "$exit_code" -ne 0 ]; then
    echo "FAIL arm=$arm seed=$seed exit=$exit_code" >&2
    tail -40 "$log" >&2
    exit 1
  fi
  # Covers clean detached recovery and closes any final-log race after the
  # wrapper's atomic status publication.
  guard_complete_log "$log"
  for _ in $(seq 1 20); do
    [ -f "${log}.run_dir" ] && break
    sleep 1
  done
  [ -f "${log}.run_dir" ] || {
    echo "missing run-directory sidecar for $tag" >&2; exit 1; }
  materialize_result write "$arm" "$seed" "$tag" "$manifest" \
    "$log" "$result"
  COMPLETED_ARMS=$((COMPLETED_ARMS + 1))
  echo "DONE index=$CURRENT_INDEX/$TOTAL_ARMS arm=$arm seed=$seed result=$result"
  write_screen_status running 0 "arm accepted"

  # Status is written immediately before wrapper exit. Require the inherited
  # one-trainer lock to be released before starting the next arm.
  lock_released=0
  for _ in $(seq 1 30); do
    if flock -n /tmp/bloodbowl-rl-reward-ablation.lock -c true; then
      lock_released=1
      break
    fi
    sleep 1
  done
  [ "$lock_released" -eq 1 ] || {
    echo "trainer lock remained held after status for $tag" >&2
    exit 1
  }
done

CURRENT_ARM=""
CURRENT_SEED=""
CURRENT_INDEX=$TOTAL_ARMS

"$PYBIN" - "$SCREEN_COMPLETE" "$SCREEN_MANIFEST_SHA" "$OUT_DIR" \
  "$PREFIX" "$SCREEN_MANIFEST" <<'PY'
import datetime, hashlib, json, pathlib, sys
path, manifest_sha, out_dir, prefix, manifest_path = sys.argv[1:]
out = pathlib.Path(out_dir)
manifest = json.loads(pathlib.Path(manifest_path).read_text(encoding="utf-8"))
schedule = tuple(
    (entry["arm"], int(entry["seed"]))
    for entry in manifest["contract"]["schedule"]
)


def sha(target):
    return hashlib.sha256(pathlib.Path(target).read_bytes()).hexdigest()


results = []
for index, (arm, seed) in enumerate(schedule, 1):
    result_path = out / f"{prefix}-{arm}-s{seed}.result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("trainer_complete") or not result.get("acceptance_pass"):
        raise SystemExit(f"result is not accepted: {result_path}")
    if result.get("screen_manifest_sha256") != manifest_sha:
        raise SystemExit(f"result belongs to another screen: {result_path}")
    results.append({
        "index": index, "arm": arm, "seed": seed,
        "path": str(result_path), "sha256": sha(result_path),
        "checkpoint_sha256": result["checkpoint_sha256"],
        "checkpoint_lineage_sha256": result["checkpoint_lineage_sha256"],
    })
destination = pathlib.Path(path)
# A published completion summary keeps its bytes, so a downstream analysis that
# pinned its hash still resolves after the screen is re-validated.
if not destination.exists():
    payload = {
        "schema_version": 1,
        "screen_manifest_sha256": manifest_sha,
        "results": results,
        "completed_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
    }
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(
        payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    temporary.replace(destination)
print(f"SCREEN COMPLETE: {destination}")
PY

COMPLETED_ARMS=$TOTAL_ARMS
write_screen_status complete 0 "all $TOTAL_ARMS arms accepted and completion summary verified"
trap - EXIT INT TERM
echo "SCREEN COMPLETE: $OUT_DIR"
