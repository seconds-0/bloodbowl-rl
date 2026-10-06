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

# The build the stages are about to use: the installed env source digest and the compiled module's sha256.
# Prints "<source> <module>", or fails.
b3_current_build() {
  local module source
  module="$(ls "$C"/vendor/PufferLib/pufferlib/_C*.so 2>/dev/null)" || return 1
  [ "$(printf '%s\n' "$module" | wc -l)" -eq 1 ] || return 1
  source="$(cat "$C/vendor/PufferLib/ocean/bloodbowl/.content_hash" 2>/dev/null)" || return 1
  printf '%s %s\n' "$source" "$(sha256sum "$module" | awk '{print $1}')"
}

# A marker file is not a gate by existing. The identity pass must be for the build that is installed NOW:
# a rebuild after it passed leaves the file behind, and the supervisor, which only looks for the file,
# would not run the identity stage again.
b3_identity_holds() {
  local build
  build="$(b3_current_build)" || { echo "cannot read the installed build under $C" >&2; return 1; }
  python3 - "$B3_IDENTITY_PASS" $build <<'PY'
import json, sys
path, source, module = sys.argv[1:]
try:
    marker = json.load(open(path, encoding="utf-8"))
except (OSError, ValueError) as exc:
    print(f"no usable identity pass marker ({path}): {exc}; run b3_identity.sh first", file=sys.stderr)
    raise SystemExit(1)
if marker.get("pass") is not True or marker.get("reference_pinned") is not True:
    print(f"{path} is not a pass against the pinned digests", file=sys.stderr)
    raise SystemExit(1)
if marker.get("source_sha256") != source or marker.get("compiled_module_sha256") != module:
    print(f"{path} passed build source {marker.get('source_sha256')} module "
          f"{marker.get('compiled_module_sha256')}; the installed build is source {source} module "
          f"{module}. Run b3_identity.sh on this build.", file=sys.stderr)
    raise SystemExit(1)
PY
}

# The canary must have passed on the installed build too: its accepted checkpoint's lineage sidecar binds
# the build that produced it. And it must record no game cut by the decision cap, in training, in the
# end-of-run evaluation and in every exam cell (D416 amendment). The screen and the verdict tool refuse
# such a run themselves; this reads their records, so a canary accepted by older tools does not count.
b3_canary_holds() {
  local build run
  build="$(b3_current_build)" || { echo "cannot read the installed build under $C" >&2; return 1; }
  run="$C/runs/ladder-d${RUNG}-${B3_CANARY_STAMP}"
  python3 - "$run" $build <<'PY'
import json, sys
run, source, module = sys.argv[1:]
try:
    verdict = json.load(open(run + "/EXAM_VERDICT_PASS.json", encoding="utf-8"))
    marker = json.load(open(run + "/LADDER_RUNG_COMPLETE.json", encoding="utf-8"))
    lineage = json.load(open(marker["checkpoint_lineage"], encoding="utf-8"))
    built = lineage["implementation"]
except (OSError, ValueError, KeyError, TypeError) as exc:
    print(f"the canary has no usable passing verdict under {run}: {exc!r}; run b3_canary54.sh first",
          file=sys.stderr)
    raise SystemExit(1)
if verdict.get("pass") is not True or verdict.get("no_early_end_turn") != 1 \
        or marker.get("no_early_end_turn") != 1:
    print(f"the canary under {run} did not pass under no_early_end_turn", file=sys.stderr)
    raise SystemExit(1)
if verdict.get("checkpoint_sha256") != marker.get("checkpoint_sha256"):
    print(f"the canary's verdict and rung marker under {run} name different checkpoints", file=sys.stderr)
    raise SystemExit(1)
if built.get("source_sha256") != source or built.get("compiled_module_sha256") != module:
    print(f"the canary under {run} ran on build source {built.get('source_sha256')} module "
          f"{built.get('compiled_module_sha256')}; the installed build is source {source} module "
          f"{module}. Run the canary on this build (a new stamp).", file=sys.stderr)
    raise SystemExit(1)
try:
    result = json.load(open(marker["result"], encoding="utf-8"))
    counts = {"training": result["train_metrics"].get("truncated_episodes"),
              "end-of-run evaluation": result["eval_metrics"].get("truncated_episodes")}
    cells = verdict["cells"]
    for cell in cells:
        counts[f"exam cell s{cell['seed']} {cell['cell']}"] = cell.get("truncated_episodes")
except (OSError, ValueError, KeyError, TypeError) as exc:
    print(f"the canary under {run} has no readable truncation record: {exc!r}", file=sys.stderr)
    raise SystemExit(1)
if result.get("acceptance_pass") is not True or len(cells) != 6:
    print(f"the canary under {run} is not an accepted arm with six exam cells", file=sys.stderr)
    raise SystemExit(1)
bad = {where: count for where, count in counts.items()
       if isinstance(count, bool) or not isinstance(count, (int, float)) or count != 0}
if bad:
    print(f"the canary under {run} does not record zero truncated_episodes everywhere: {bad}. "
          "A game cut by the decision cap fails the canary; nothing is read from it.", file=sys.stderr)
    raise SystemExit(1)
PY
}
