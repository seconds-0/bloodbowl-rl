#!/usr/bin/env bash
# Apply every bloodbowl-rl patch to the vendored PufferLib tree, in order.
#
#   bash tools/apply_puffer_patches.sh [vendor/PufferLib]
#   bash tools/apply_puffer_patches.sh --check [vendor/PufferLib]
#
# vendor/*/ is gitignored, so a re-clone silently drops every patch. Before this
# script the 17 patches were applied by hand from prose spread across
# .claude/skills/puffer-env-dev/SKILL.md, and a missed one is not hypothetical:
# an earlier canary died in preflight on an unapplied selfplay_league.patch, and
# two edits (warm start, scripted-training guard) were never captured as patches
# at all and existed only as untracked edits in one box checkout.
#
# Idempotent. A patch already present is left alone; a patch that neither
# applies nor is already present is a hard error. --check applies nothing and
# exits non-zero if the tree is not fully patched, which makes it usable as a
# preflight gate.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

CHECK_ONLY=0
if [ "${1:-}" = "--check" ]; then
  CHECK_ONLY=1
  shift
fi
VENDOR="${1:-$ROOT/vendor/PufferLib}"
[ -d "$VENDOR" ] || { echo "vendor tree not found: $VENDOR" >&2; exit 1; }
[ -f "$VENDOR/pufferlib/pufferl.py" ] || {
  echo "not a PufferLib tree (no pufferlib/pufferl.py): $VENDOR" >&2; exit 1; }

# Order matters. Constraints, from the skill doc and D218/D225:
#   - puffer_recurrent_eval_state    AFTER puffer_exact_joint_actions
#   - puffer_frozen_prio_mask        AFTER puffer_recurrent_eval_state
#   - puffer_recurrent_cuda_qualification  LAST
PATCHES=(
  puffer_dict_capacity
  pufferl_env_json
  pufferl_env_json_metadata_upgrade
  pufferl_env_phase_contract
  pufferl_env_dashboard_limit
  pufferl_eval_episode_gate
  pufferl_metrics_keyerror
  torch_pufferl_trusted_load
  torch_pufferl_bcreg
  sweep_match_mode_exclusion
  selfplay_league
  pufferl_scripted_training_guard
  pufferl_warm_start
  puffer_exact_joint_actions
  puffer_recurrent_eval_state
  puffer_frozen_prio_mask
  puffer_recurrent_cuda_qualification
)

# The exact markers tools/run_reward_ablation.sh greps before it will launch
# (see its preflight around lines 332-345), plus the scripted-training guard.
# Checking them here means --check fails for the same reason the launcher would,
# rather than that failure surfacing only when someone tries to start a run.
declare -a MARKERS=(
  "pufferlib/pufferl.py:Warm-started training from"
  "pufferlib/pufferl.py:if i == 160:"
  "pufferlib/pufferl.py:PUFFER_ENV_JSON"
  "pufferlib/pufferl.py:guard_scripted_training"
  "pufferlib/selfplay.py:Patch copy: training/selfplay_league.patch"
  "config/bloodbowl.ini:league_preseed"
)

applied=0 already=0 failed=0

for name in "${PATCHES[@]}"; do
  patch_file="$ROOT/training/$name.patch"
  if [ ! -f "$patch_file" ]; then
    echo "MISSING PATCH FILE  $name.patch" >&2
    failed=$((failed + 1))
    continue
  fi

  # Three states, and the order of these tests matters.
  #
  # A clean FORWARD apply is the only proof a patch is genuinely absent, so test
  # that first. A clean REVERSE apply proves it is present and untouched. When
  # both fail the patch is almost always present but has had its context
  # rewritten by a later overlapping patch -- exact_joint_actions and the
  # pufferl.py stack overlap heavily -- so treating that as "missing" produces
  # false alarms. Verified against the obs-v5 box checkout, where reverse-check
  # alone reported 9 missing patches and only 2 were really absent. In the
  # ambiguous case defer to the markers below.
  if git -C "$VENDOR" apply --check --no-index "$patch_file" 2>/dev/null; then
    if [ "$CHECK_ONLY" -eq 1 ]; then
      echo "NOT APPLIED  $name (applies cleanly, so it is genuinely absent)" >&2
      failed=$((failed + 1))
    else
      git -C "$VENDOR" apply --no-index "$patch_file"
      applied=$((applied + 1))
      printf '  applied      %s\n' "$name"
    fi
  elif git -C "$VENDOR" apply --reverse --check --no-index "$patch_file" 2>/dev/null; then
    already=$((already + 1))
    [ "$CHECK_ONLY" -eq 1 ] || printf '  present      %s\n' "$name"
  else
    already=$((already + 1))
    [ "$CHECK_ONLY" -eq 1 ] || printf '  present*     %s (context rewritten by a later patch)\n' "$name"
  fi
done

for entry in "${MARKERS[@]}"; do
  rel="${entry%%:*}"
  needle="${entry#*:}"
  if ! grep -q "$needle" "$VENDOR/$rel" 2>/dev/null; then
    echo "MISSING MARKER  $rel lacks '$needle'" >&2
    failed=$((failed + 1))
  fi
done

if [ "$failed" -ne 0 ]; then
  echo "patch state INCOMPLETE: $failed problem(s); applied=$applied present=$already" >&2
  exit 1
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  echo "patch state OK: all ${#PATCHES[@]} patches present, all markers found"
else
  echo "patch state OK: applied=$applied already-present=$already of ${#PATCHES[@]}"
fi
