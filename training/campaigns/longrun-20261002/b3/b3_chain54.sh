#!/usr/bin/env bash
# Stage b3_chain54 of campaign longrun-20261002: chain 42's rung trained under no_early_end_turn, on the b3
# checkout. Control: chain 42 (warm chain 41, seed 42, pool cc9b201e, bot on tag 4, standard recipe).
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || b3_identity_holds || { echo "b3_chain54: the identity stage has not passed on the installed build; not training" >&2; exit 2; }
[ "${PLAN_ONLY:-0}" = "1" ] || b3_canary_holds || { echo "b3_chain54: the canary has not passed on the installed build; not training" >&2; exit 2; }
export SEED=42 STAMP="$B3_RUNG_STAMP"
export PREV_COMPLETE="$B3_CHAIN41_MARKER"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
export EXPECTED_POOL_HASH="$B3_POOL_HASH"
export LADDER_NO_EARLY_END_TURN=1
# A paired arm never stops itself. Chain 42's drift-guard floor was registered on exams without the rule.
export EXAM_RULE=none
exec bash "$C/tools/chain_stage.sh"
