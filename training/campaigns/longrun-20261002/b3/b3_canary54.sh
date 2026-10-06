#!/usr/bin/env bash
# Stage b3_canary54 of campaign longrun-20261002: a disposable 50M-step run of chain 54's exact launch path,
# under no_early_end_turn, on the b3 checkout. Never a warm start, a pool member or a result.
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || b3_identity_holds || { echo "b3_canary54: the identity stage has not passed on the installed build; not training" >&2; exit 2; }
export SEED=42 STAMP="$B3_CANARY_STAMP"
export STEPS=50000000
export PREV_COMPLETE="$B3_CHAIN41_MARKER"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
export EXPECTED_POOL_HASH="$B3_POOL_HASH"
export LADDER_NO_EARLY_END_TURN=1
export EXAM_RULE=none
exec bash "$C/tools/chain_stage.sh"
