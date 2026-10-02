# Shared environment for every stage of the 2026-10-02 long run (D407). Source me.
export C=/home/rache/bloodbowl-rl-longrun-20261002
export OLD=/home/rache/bloodbowl-rl-qualification-candidate-10619e2
export RUNG=0 RESET_PCT=0 STEPS=3000000000
export LADDER_ARM=r0_poss_half
export SCRIPTED_BANK_TAG=4 SCRIPTED_BOT_TYPE=0
export FROZEN_BANK_PCT=0.12
export LADDER_GAMMA=0.999 LADDER_GAE_LAMBDA=0.95
export LADDER_REPLAY_RATIO=1.0
export DEADLINE_HOURS=16 NUM_THREADS=16
# Every existing checkpoint binds the old build, so every rung on the long-run build is a declared graft.
export LADDER_PROFILE=graft
export GRAFT_FROM_SOURCE_SHA256=3ed6899e121bbc084568d03687be79b8ce1bb0f375c5f9cdbcdc074b0eb0a68b
export GRAFT_FROM_PATCH_BUNDLE_SHA256=de77f6c0a01304292dba21ada627d535f0ccb8629bc5a96d8ddc8df1d710a3ad
export GRAFT_REASON="D407 long-run build: blitz fast path, scripted-bank forward skip, loss telemetry"
export PUFFER_SKIP_SCRIPTED_BANK_FORWARD=1 BBE_DECIDING_ROW_TELEMETRY=1
export CUDA_VISIBLE_DEVICES=0
