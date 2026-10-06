# Shared environment for the b3 stages of campaign longrun-20261002: the no_early_end_turn arm, run from its
# own checkout (docs/no-early-end-turn-2026-10-05.md). Source me.
# The recipe lines are ../common_env.sh's, value for value. What differs: C, and the graft declaration, because
# on this build the long-run build is an old build too.
export C="${B3_C:-/home/rache/bloodbowl-rl-b3-20261006}"
export LONGRUN="${B3_LONGRUN:-/home/rache/bloodbowl-rl-longrun-20261002}"
export RUNG=0 RESET_PCT=0 STEPS=3000000000
export LADDER_ARM=r0_poss_half
export SCRIPTED_BANK_TAG=4 SCRIPTED_BOT_TYPE=0
export FROZEN_BANK_PCT=0.12
export LADDER_GAMMA=0.999 LADDER_GAE_LAMBDA=0.95
export LADDER_REPLAY_RATIO=1.0
export DEADLINE_HOURS=16 NUM_THREADS=16
# Two old builds, read pairwise: the original build (pool anchor, chain 36) and the long-run build (chains 40
# and 41). This checkout's own build is neither: its env source differs, and its patch-bundle digest differs
# from the long-run build's because that digest hashes the patch files under their absolute paths.
export LADDER_PROFILE=graft
export GRAFT_FROM_SOURCE_SHA256=3ed6899e121bbc084568d03687be79b8ce1bb0f375c5f9cdbcdc074b0eb0a68b,2ed3ffc2dcc33df0a2262cbe1f86b4742ece0983ee31d41a3b0e2cc462a01dc4
export GRAFT_FROM_PATCH_BUNDLE_SHA256=de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad,c1174af6b4a6c6a6b91df353678c69846b5c66a2f08997d18a141a5062a60bda
export GRAFT_REASON="b3 build (no_early_end_turn) over the original and long-run builds"
export PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1
export CUDA_VISIBLE_DEVICES=0
# What the b3 stages share.
export B3_IDENTITY_PASS="$C/runs/b3-identity-20261006/B3_IDENTITY_PASS.json"
export B3_CHAIN41_MARKER="$LONGRUN/runs/ladder-d0-r0chain41-cont40-rr1-20261003/LADDER_RUNG_COMPLETE.json"
export B3_POOL_HASH=cc9b201e619aab3dedb2577eeac273a3b70a346a5e87d30fa9ab432c068d3be6
export B3_CANARY_STAMP=canary54-noearlyend-from41-s42-20261006
export B3_RUNG_STAMP=r0chain54-noearlyend-from41-s42-20261006
