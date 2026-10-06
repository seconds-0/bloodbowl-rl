#!/usr/bin/env bash
# Stage b3_chain56 of campaign longrun-20261002 (D418), on the b3 checkout: chain 55's rung trained under no_early_end_turn. Control: chain 55.
# Warm start chain 49 (the warm start since D418), training seed 42, standard recipe, the ladder's pool rotation
# from chain 49's pool: the anchor, chain 40, chain 41, and chain 49 last.
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || b3_identity_holds || { echo "b3_chain56: the identity stage has not passed on the installed build; not training" >&2; exit 2; }
[ "${PLAN_ONLY:-0}" = "1" ] || b3_canary_holds || { echo "b3_chain56: the canary has not passed on the installed build; not training" >&2; exit 2; }
export SEED=42 STAMP=r0chain56-noearlyend-from49-s42-20261006
export PREV_COMPLETE="$LONGRUN/runs/ladder-d0-r0chain49-botseat1-from41-s42-20261004/LADDER_RUNG_COMPLETE.json"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
[ -z "${B3_POOL49_HASH:-}" ] || export EXPECTED_POOL_HASH="$B3_POOL49_HASH"
export LADDER_NO_EARLY_END_TURN=1
# A paired arm under the rule never stops itself: the guard's floors were registered on exams without the rule.
export EXAM_RULE=none
exec bash "$C/tools/chain_stage.sh"
