#!/usr/bin/env bash
# 2070 rig babysitter — keeps an experiment running 100% of the time and
# self-heals. Cron runs this every 30 min. It dispatches the resident Claude
# with full project context; Claude decides: relaunch at cap, advance the
# ladder, diagnose a crash, or note progress. All actions logged.
#
# Doctrine (Alex): flagship training runs on the remote vast boxes; THIS box
# (RTX 2070, ~190K SPS, free) stays 100% occupied with EXPERIMENTS. A training
# arm should always be live.
set -uo pipefail
cd "$HOME/bloodbowl-rl" || exit 1
source "$HOME/.bbrl_token" 2>/dev/null
export PATH="$HOME/.local/bin:$PATH"
LOG="$HOME/bloodbowl-rl/rig-babysitter.log"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

# never run two babysitters at once
exec 9>"$HOME/.babysitter.lock"
flock -n 9 || { echo "[$STAMP] locked, skip" >>"$LOG"; exit 0; }

TRAINER=$(pgrep -fc "[p]uffer_cuda_runtime.py train|[p]uffer train" 2>/dev/null || echo 0)
echo "[$STAMP] tick: puffer_train_procs=$TRAINER" >>"$LOG"

PROMPT='You are the resident babysitter for the Blood Bowl RL rig (RTX 2070, ~190K SPS, a FREE experiment node). Read CLAUDE.md and the tail of DECISIONS.md for current program state and doctrine. CONTEXT: flagship training runs on remote vast boxes (NOT here); THIS box must stay 100% occupied with EXPERIMENTS (Alex directive) — a training arm should always be live. Before any puffer command: `source rig-env.sh` then activate vendor/PufferLib/.venv; this rig uses the --float build (precision_bytes=4, Turing sm_75) and the NATIVE backend (no --slowly, it is faster here). CHECK: is a `puffer train` process running (pgrep -fc "[p]uffer_cuda_runtime.py train|[p]uffer train") AND is its newest /tmp/*.log advancing (mtime < 10 min)? If YES: log one status line (tag, steps, key metric) and exit. If NO / stale / crashed: to simply resume the CURRENT experiment, run `bash tools/rig_relaunch.sh` (it holds the exact rig recipe — RIG_ALLOW_FLOAT, the passing ladder, warm from the newest ckpt by step number — and is idempotent). Only hand-craft a launch when ADVANCING the ladder (e.g. the run capped at 15B and its from-kickoff eval says graduate: lower demo_reset_pct toward 0) or starting a NEW queued experiment, per DECISIONS doctrine (pure-ladder curricula that GRADUATE to kickoff; reset-pct drills are RETIRED per D69). The rig uses --float so any hand launch needs RIG_ALLOW_FLOAT=1. Append a 2-3 line summary of what you found and did to rig-babysitter.log. Be decisive and act now; do not ask questions.'

claude -p "$PROMPT" >>"$LOG" 2>&1
echo "[$STAMP] tick done" >>"$LOG"
