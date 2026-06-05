#!/usr/bin/env bash
# Launch a training run under a named reward profile (the A/B/C experiment).
#   tools/train_profile.sh A [extra puffer args...]   # pure outcome
#   tools/train_profile.sh B [extra puffer args...]   # event-realized knobs
#   tools/train_profile.sh C [extra puffer args...]   # exposure-EV (v2, D33)
#   tools/train_profile.sh D [extra puffer args...]   # B + bootstrap curriculum
#                                                       (stage 1; anneal via chained run)
# A and B both converged to the 0-0 avoidance basin at 10B; D is the
# potential-ladder out of it. C (docs/reward-audit-decision-time.md, ungated
# by D33) prices block/blitz declarations by the closed-form exposure tree —
# no realized ball/injury shaping, dice outcomes carry zero weight.
set -euo pipefail
PROFILE="${1:?usage: train_profile.sh A|B [extra args]}"
shift || true

case "$PROFILE" in
  A) ARGS=() ;; # config defaults: win/draw(0)/TD only, all shaping 0
  B) ARGS=(
       --env.reward-draw -0.1
       --env.reward-setup-done 0.25 --env.reward-setup-autofix -0.25
       --env.reward-ball-gain 0.1 --env.reward-ball-loss -0.2
       --env.reward-injury-inflicted 0.15 --env.reward-injury-taken -0.15
       --env.reward-injury-value-scaled 1
       --env.reward-surf-taken -0.1 --env.reward-surf-inflicted 0.1
     ) ;;
  C) ARGS=(
       --env.reward-draw -0.1
       --env.reward-setup-done 0.25 --env.reward-setup-autofix -0.25
       --env.reward-surf-taken -0.1 --env.reward-surf-inflicted 0.1
       --env.reward-k-kd 0.06 --env.reward-k-value 0.5
       --env.reward-k-ball 0.3 --env.reward-k-seq 0.02
     ) ;; # NO realized ball/injury knobs: exposure replaces them (audit table)
  D) ARGS=(
       --env.reward-draw -0.1
       --env.reward-setup-done 0.25 --env.reward-setup-autofix -0.25
       --env.reward-ball-gain 0.1 --env.reward-ball-loss -0.2
       --env.reward-injury-inflicted 0.15 --env.reward-injury-taken -0.15
       --env.reward-injury-value-scaled 1
       --env.reward-surf-taken -0.1 --env.reward-surf-inflicted 0.1
       --env.reward-dist-ball 0.02 --env.reward-dist-endzone 0.04
     ) ;;
  *) echo "unknown profile: $PROFILE" >&2; exit 1 ;;
esac

cd "$(dirname "$0")/../vendor/PufferLib"
tools_root="$(cd .. && cd .. && pwd)"
bash "$tools_root/tools/install_puffer_env.sh" --check || {
  echo "stale env snapshot — run tools/install_puffer_env.sh first" >&2; exit 1; }

# Drop a PROFILE marker into the run directory the trainer is about to
# create (newest dir ~30s after launch) so the spectator can label the feed.
(
  sleep 30
  d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
  [ -n "$d" ] && echo "profile-$PROFILE" > "${d}PROFILE"
) &

exec puffer train bloodbowl --tag "profile-$PROFILE" "${ARGS[@]}" "$@"
