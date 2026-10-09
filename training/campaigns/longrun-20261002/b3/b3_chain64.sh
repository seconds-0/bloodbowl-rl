#!/usr/bin/env bash
# Stage b3_chain64 of campaign longrun-20261002 (D452), on the b3 checkout: chain 62's rung against the pool of
# the generation before. Control: chain 62. Warm start chain 58, training seed 42, GAE lambda 0.97, standard
# recipe, flag off, bot on tag 4. The one factor is the pool: the anchor, chain 40, chain 41, and chain 58 last
# (chain 62's is the anchor, chain 41, chain 49, and chain 58 last). It is composed by the stage's own rule from
# the pool chain 49 trained against (the anchor, chain 36, chain 40, chain 41), read from chain 54's run
# directory on this checkout, where the same pool was built.
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || b3_identity_holds || { echo "b3_chain64: the identity stage has not passed on the installed build; not training" >&2; exit 2; }
export SEED=42 STAMP=r0chain64-pool49gen-from58-s42-20261009
export PREV_COMPLETE="$C/runs/ladder-d0-r0chain58-lam097-from49-s42-20261007/LADDER_RUNG_COMPLETE.json"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
# The one factor against chain 62: the previous pool the rotation starts from.
export PREV_POOL="$C/runs/ladder-d0-r0chain54-noearlyend-from41-s42-20261006/pool"
# The pool that rule builds, from the plan-only pass of 2026-10-09 00:51 PDT.
export EXPECTED_POOL_HASH=4dd70d0ee538af5f8de7acdaed41821f4d1bae84adad8633f7bf118f82f8e237
# As chain 62. Gamma stays 0.999.
export LADDER_GAE_LAMBDA=0.97
# D405's drift guard pinned to chain 30, applied by the stage as a collapse stop. No exam veto (D417).
export EXAM_RULE=drift-guard
export EXAM_GUARD_FLOOR_S42=0.541 EXAM_GUARD_FLOOR_S43=0.551 EXAM_GUARD_FLOOR_MEAN=0.546
exec bash "$C/tools/chain_stage.sh"
