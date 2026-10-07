#!/usr/bin/env bash
# Stage b3_chain60 of campaign longrun-20261002 (D429), on the b3 checkout: chain 59's rung with GAE lambda 0.97
# (the shared settings give 0.95). Control: chain 59. Warm start chain 49, training seed 2042, standard recipe, flag off,
# bot on tag 4, the pool every child of chain 49 builds (the anchor, chain 40, chain 41, and chain 49 last).
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || b3_identity_holds || { echo "b3_chain60: the identity stage has not passed on the installed build; not training" >&2; exit 2; }
export SEED=2042 STAMP=r0chain60-lam097-from49-s2042-20261007
export PREV_COMPLETE="$LONGRUN/runs/ladder-d0-r0chain49-botseat1-from41-s42-20261004/LADDER_RUNG_COMPLETE.json"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
[ -z "${B3_POOL49_HASH:-}" ] || export EXPECTED_POOL_HASH="$B3_POOL49_HASH"
# The one factor against chain 59. Gamma stays 0.999.
export LADDER_GAE_LAMBDA=0.97
# D405's drift guard pinned to chain 30, applied by the stage as a collapse stop. No exam veto (D417).
export EXAM_RULE=drift-guard
export EXAM_GUARD_FLOOR_S42=0.541 EXAM_GUARD_FLOOR_S43=0.551 EXAM_GUARD_FLOOR_MEAN=0.546
exec bash "$C/tools/chain_stage.sh"
