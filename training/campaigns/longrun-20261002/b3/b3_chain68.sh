#!/usr/bin/env bash
# Stage b3_chain68 of campaign longrun-20261002, on the b3 checkout: a rung of the generation after chain 58, from
# chain 63, the warm start a registered selection picked (DECISIONS.md), at GAE lambda 0.97 (the value D440 adopted;
# the shared settings give 0.95). The generation's rung at the adopted recipe. Training seed 42, standard recipe, flag
# off, bot on tag 4, the pool the ladder's rotation builds for every child of chain 63 (the anchor, chain 49, chain
# 58, and chain 63 last).
set -uo pipefail
source "$(cd "$(dirname "$0")" && pwd)/b3_common_env.sh"
# A plan-only pass trains nothing, so it may run before the gates below are met.
[ "${PLAN_ONLY:-0}" = "1" ] || b3_identity_holds || { echo "b3_chain68: the identity stage has not passed on the installed build; not training" >&2; exit 2; }
export SEED=42 STAMP=r0chain68-lam097-from63-s42-20261011
export PREV_COMPLETE="$C/runs/ladder-d0-r0chain63-lam099-from58-s42-20261008/LADDER_RUNG_COMPLETE.json"
export LADDER_CHAIN_LR_SCALE=1.0 LADDER_CHAIN_ENT_SCALE=1.0
# The pool every child of chain 63 builds, from the plan-only pass of 2026-10-10 18:49 PDT.
export EXPECTED_POOL_HASH=6a77d63a1b4cd20d78dea155aab46bebf3abd5668f7a937b85e2dacad6c5a03f
# Gamma stays 0.999.
export LADDER_GAE_LAMBDA=0.97
# D405's drift guard pinned to chain 30, applied by the stage as a collapse stop. No exam veto (D417).
export EXAM_RULE=drift-guard
export EXAM_GUARD_FLOOR_S42=0.541 EXAM_GUARD_FLOOR_S43=0.551 EXAM_GUARD_FLOOR_MEAN=0.546
exec bash "$C/tools/chain_stage.sh"
