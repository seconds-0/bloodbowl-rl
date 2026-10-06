#!/usr/bin/env bash
# Stage b3_chain54 of campaign longrun-20261002: chain 42's rung trained under no_early_end_turn, on the b3
# checkout. Control: chain 42 (warm chain 41, seed 42, pool cc9b201e, bot on tag 4, standard recipe).
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || [ -f "$B3_IDENTITY_PASS" ] || { echo "b3_chain54: no identity pass marker ($B3_IDENTITY_PASS); run b3_identity.sh first" >&2; exit 2; }
CANARY_PASS="$C/runs/ladder-d${RUNG}-${B3_CANARY_STAMP}/EXAM_VERDICT_PASS.json"
[ "${PLAN_ONLY:-0}" = "1" ] || [ -f "$CANARY_PASS" ] || { echo "b3_chain54: the canary has no passing verdict ($CANARY_PASS); run b3_canary54.sh first" >&2; exit 2; }
export SEED=42 STAMP="$B3_RUNG_STAMP"
export PREV_COMPLETE="$B3_CHAIN41_MARKER"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
export EXPECTED_POOL_HASH="$B3_POOL_HASH"
export LADDER_NO_EARLY_END_TURN=1
# A paired arm never stops itself. Chain 42's drift-guard floor was registered on exams without the rule.
export EXAM_RULE=none
exec bash "$C/tools/chain_stage.sh"
