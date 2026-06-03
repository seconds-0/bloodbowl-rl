#!/usr/bin/env bash
# Launch a training run under a named reward profile (the A/B/C experiment).
#   tools/train_profile.sh A [extra puffer args...]   # pure outcome
#   tools/train_profile.sh B [extra puffer args...]   # event-realized knobs
# Profile C (exposure-EV) is gated on B beating A — see
# docs/reward-audit-decision-time.md.
set -euo pipefail
PROFILE="${1:?usage: train_profile.sh A|B [extra args]}"
shift || true

case "$PROFILE" in
  A) ARGS=() ;; # config defaults: win/draw(0)/TD only, all shaping 0
  B) ARGS=(
       --env.reward-draw -0.5
       --env.reward-setup-done 0.25 --env.reward-setup-autofix -0.25
       --env.reward-ball-gain 0.1 --env.reward-ball-loss -0.5
       --env.reward-injury-inflicted 0.15 --env.reward-injury-taken -0.15
       --env.reward-injury-value-scaled 1
       --env.reward-surf-taken -0.1 --env.reward-surf-inflicted 0.1
     ) ;;
  *) echo "unknown profile: $PROFILE" >&2; exit 1 ;;
esac

cd "$(dirname "$0")/../vendor/PufferLib"
tools_root="$(cd .. && cd .. && pwd)"
bash "$tools_root/tools/install_puffer_env.sh" --check || {
  echo "stale env snapshot — run tools/install_puffer_env.sh first" >&2; exit 1; }

exec puffer train bloodbowl --tag "profile-$PROFILE" "${ARGS[@]}" "$@"
