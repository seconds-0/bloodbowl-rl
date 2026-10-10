#!/usr/bin/env bash
# Stage b3_chain67 of campaign longrun-20261002, on the b3 checkout: chain 63's rung with GAE lambda 0.999, a fourth
# dose on one parent and seed (chain 61 is 0.95, chain 62 is 0.97, chain 63 is 0.99; the shared settings give 0.95).
# Control: chain 63. Warm start chain 58, training seed 42, standard recipe, flag off, bot on tag 4, the pool every
# child of chain 58 builds (the anchor, chain 41, chain 49, and chain 58 last).
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || b3_identity_holds || { echo "b3_chain67: the identity stage has not passed on the installed build; not training" >&2; exit 2; }
export SEED=42 STAMP=r0chain67-lam0999-from58-s42-20261010
export PREV_COMPLETE="$C/runs/ladder-d0-r0chain58-lam097-from49-s42-20261007/LADDER_RUNG_COMPLETE.json"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
# The pool every child of chain 58 builds, from the plan-only pass of 2026-10-07 20:30 PDT.
export EXPECTED_POOL_HASH=59a6703f00c8d012d5e2eb8a8a720bc9a83627ff29f4b638b86676bd2b7ee4e3
# The one factor against chain 63. Gamma stays 0.999.
export LADDER_GAE_LAMBDA=0.999
# D405's drift guard pinned to chain 30, applied by the stage as a collapse stop. No exam veto (D417).
export EXAM_RULE=drift-guard
export EXAM_GUARD_FLOOR_S42=0.541 EXAM_GUARD_FLOOR_S43=0.551 EXAM_GUARD_FLOOR_MEAN=0.546
exec bash "$C/tools/chain_stage.sh"
