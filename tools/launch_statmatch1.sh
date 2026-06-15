#!/usr/bin/env bash
# launch_statmatch1.sh — D114-A statmatch1 arm: the league6 kickoff-pure reward
# economy MINUS reward_possession (zeroed) PLUS the D114 aggregate-statistic-
# matching pseudo-reward (--env.reward-statmatch-scale). The episode-end term
# -scale*||z||_2 pulls the 7-stat full-game behavioral vector toward the FIXED
# human baseline (docs/human-baseline.json). See DECISIONS.md D114 / D114-A.
#
# WHY possession is zeroed: the 0.03 possession annuity has a dense per-turn
# gradient that would dominate the joint possession_rate target in the statmatch
# vector (spec requirement — they cannot coexist).
#
# Run ON the box from ~/bloodbowl-rl. The env-var contract:
#   TAG=<run tag>        default statmatch1
#   WARM=<ckpt>          warm-start checkpoint (ladder-top per D107-A)
#   SCALE=<float>        statmatch scale (default 0.01 — calibrated: smoke
#                        measured mean ||z||~13/episode AND a base
#                        episode_return ~0.45 at kickoff (statmatch off), so
#                        0.01 gives a mean term ~-0.13 = ~0.29x of base return,
#                        squarely in the spec's 0.2-0.5x band. start small per
#                        D114 (sparse episodic credit must stay subordinate to
#                        the dense per-step rewards).
#   STEPS=<int>          total timesteps (default 5e9 — a first probe).
#   BACKEND=native|torch native = CUDA backend (rig --float build, Vast plain
#                        build); torch = --slowly (slower, only if you must).
#   POOL=<dir>           optional selfplay league-preseed pool dir. Unset =
#                        frozen-self selfplay (clean single-variable read on the
#                        REWARD change, per the launch guidance). Set it to a
#                        D111 hard-opponents pool to ALSO get the pool benefit
#                        (entangles two variables — document if you do).
#   LOG=<path>           default /tmp/<TAG>.log
#
# Kickoff-pure is MANDATORY for statmatch (the env auto-gates the term on
# demo_started==0, but we also force demo-reset-pct 0 so EVERY episode is a
# full game). reward-possession is FORCED to 0 (cannot be overridden here).
set -uo pipefail
cd "$HOME/bloodbowl-rl" || exit 1

TAG="${TAG:-statmatch1}"
SCALE="${SCALE:-0.01}"
STEPS="${STEPS:-5000000000}"
BACKEND="${BACKEND:-native}"
LOG="${LOG:-/tmp/${TAG}.log}"
WARM="${WARM:?set WARM=<ladder-top ckpt> (e.g. training/league5_cap.bin on the rig)}"

# Absolutize WARM/POOL: the launch cd's into vendor/PufferLib before invoking
# puffer, so a repo-root-relative path (training/foo.bin) would not resolve.
case "$WARM" in /*) ;; *) WARM="$HOME/bloodbowl-rl/$WARM" ;; esac
if [ -n "${POOL:-}" ]; then case "$POOL" in /*) ;; *) POOL="$HOME/bloodbowl-rl/$POOL" ;; esac; fi
[ -f "$WARM" ] || { echo "REFUSING: warm-start ckpt not found: $WARM"; exit 1; }

if pgrep -f 'puffer [t]rain' >/dev/null; then
  echo "REFUSING: a puffer train is already running on this box. pkill it first if intended."
  exit 1
fi

# Backend wiring. The rig uses the native CUDA backend on a --float build.
SLOWLY=""
if [ "$BACKEND" = "torch" ]; then SLOWLY="--slowly"; fi

# CPU cap + venv (rig has rig-env.sh; Vast boxes auto-source cpu_cap.sh).
[ -f rig-env.sh ] && . rig-env.sh 2>/dev/null
[ -f tools/cpu_cap.sh ] && . tools/cpu_cap.sh 2>/dev/null
[ -f vendor/PufferLib/.venv/bin/activate ] && . vendor/PufferLib/.venv/bin/activate 2>/dev/null

POOL_ARGS=()
if [ -n "${POOL:-}" ]; then
  POOL_ARGS=(--selfplay.league-preseed "$POOL" --vec.num-frozen-banks 8 --vec.frozen-bank-pct 0.06 --selfplay.swap-winrate 0.55 --selfplay.snapshot-interval 2000000000)
fi

cd vendor/PufferLib
echo "Launching $TAG  backend=$BACKEND  scale=$SCALE  steps=$STEPS  warm=$WARM  pool=${POOL:-frozen-self}"
nohup puffer train bloodbowl --tag "$TAG" $SLOWLY \
  --load-model-path "$WARM" \
  "${POOL_ARGS[@]}" \
  --train.total-timesteps "$STEPS" \
  --env.reward-draw 0 --env.reward-setup-done 0 --env.reward-setup-autofix 0 \
  --env.reward-injury-inflicted 0 --env.reward-injury-taken 0 --env.reward-injury-value-scaled 0 \
  --env.reward-surf-taken 0 --env.reward-surf-inflicted 0 \
  --env.reward-possession 0 \
  --env.reward-ball-gain 0.05 --env.reward-ball-loss 0 \
  --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.reward-k-kd 0.03 --env.reward-k-value 0.25 --env.reward-k-ball 0.15 --env.reward-k-seq 0.01 \
  --env.reward-rush-cost 0.015 \
  --env.reward-statmatch-scale "$SCALE" \
  --env.demo-reset-pct 0 --env.demo-endzone-maxdist 0 --env.demo-pickup-maxdist 0 \
  --env.demo-postkick-maxturn 0 \
  > "$LOG" 2>&1 &
disown
echo "PID=$! LOG=$LOG"
sleep 40
if pgrep -f 'puffer [t]rain' >/dev/null; then echo "LIVE"; else echo "TRAINER DIED — check $LOG"; tail -20 "$LOG"; fi
