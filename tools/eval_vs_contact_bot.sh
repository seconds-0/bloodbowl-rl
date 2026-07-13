#!/usr/bin/env bash
# eval_vs_contact_bot.sh - measure a frozen champion's ABSOLUTE strength against
# the deterministic contact-bot opponent (AWAY/team 1), the first non-self-play
# signal. The final dashboard must expose team0/team1 TD and block splits so
# team0=champion engagement is not hidden by the bot's contact volume.
#
#   bash tools/eval_vs_contact_bot.sh <CHECKPOINT.bin> [STEPS] [LOG]
#       CHECKPOINT  torch state_dict .bin (training-side format).
#       STEPS       measurement length, default 8M.
#       LOG         output path, default /tmp/contact_bot_eval.log
# Environment:
#       BOT_TYPE     0 = contact bot (default), 1 = cage/offense bot
#       BOT_TEAM     0 = HOME, 1 = AWAY (default)
#       EVAL_EPISODES optional explicit final-policy game count. When unset,
#                     retain the Puffer config value.
#       MIN_EVAL_GAMES acceptance floor; defaults to EVAL_EPISODES when that
#                     override is set, otherwise 1.
set -euo pipefail
CKPT="${1:?usage: eval_vs_contact_bot.sh <checkpoint.bin> [steps] [log]}"
STEPS="${2:-8000000}"
LOG="${3:-/tmp/contact_bot_eval.log}"
BOT_TYPE="${BOT_TYPE:-0}"
BOT_TEAM="${BOT_TEAM:-1}"
SEED="${SEED:-42}"
EVAL_EPISODES="${EVAL_EPISODES:-}"
MIN_EVAL_GAMES="${MIN_EVAL_GAMES:-${EVAL_EPISODES:-1}}"
for _ in 1 2 3; do [ $# -gt 0 ] && shift; done
if [ $# -ne 0 ]; then
  echo "trailing Puffer overrides are not allowed by this scripted-eval contract" >&2
  exit 1
fi
case "$STEPS:$SEED" in
  *[!0-9:]*) echo "STEPS and SEED must be non-negative integers" >&2; exit 1 ;;
esac
[ "$STEPS" -gt 0 ] || { echo "STEPS must be positive" >&2; exit 1; }
if [ -n "$EVAL_EPISODES" ]; then
  case "$EVAL_EPISODES" in
    *[!0-9]*) echo "EVAL_EPISODES must be a positive integer" >&2; exit 1 ;;
  esac
  [ "$EVAL_EPISODES" -gt 0 ] || {
    echo "EVAL_EPISODES must be a positive integer" >&2; exit 1; }
fi
case "$MIN_EVAL_GAMES" in
  *[!0-9]*) echo "MIN_EVAL_GAMES must be a positive integer" >&2; exit 1 ;;
esac
[ "$MIN_EVAL_GAMES" -gt 0 ] || {
  echo "MIN_EVAL_GAMES must be a positive integer" >&2; exit 1; }
case "$BOT_TYPE" in
  0|1) ;;
  *) echo "BOT_TYPE must be 0 (contact) or 1 (cage offense)" >&2; exit 1 ;;
esac
case "$BOT_TEAM" in
  0|1) ;;
  *) echo "BOT_TEAM must be 0 (HOME) or 1 (AWAY)" >&2; exit 1 ;;
esac
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

case "$CKPT" in /*) ;; *) CKPT="$PWD/$CKPT" ;; esac
case "$LOG"  in /*) ;; *) LOG="$PWD/$LOG"   ;; esac
[ -f "$CKPT" ] || { echo "checkpoint not found: $CKPT" >&2; exit 1; }
[ ! -e "$LOG" ] || { echo "refusing to overwrite existing log: $LOG" >&2; exit 1; }

PUFFER_BIN="$ROOT/vendor/PufferLib/.venv/bin/puffer"
PYBIN="$ROOT/vendor/PufferLib/.venv/bin/python"
[ -x "$PUFFER_BIN" ] || { echo "vendored puffer entrypoint missing: $PUFFER_BIN" >&2; exit 1; }
[ -x "$PYBIN" ] || { echo "vendored Python missing: $PYBIN" >&2; exit 1; }
"$PYBIN" - "$CKPT" <<'PY' || {
import sys, torch
state = torch.load(sys.argv[1], map_location="cpu", weights_only=False)
assert isinstance(state, dict) and state, "checkpoint is not a nonempty state dict"
PY
  echo "checkpoint is not a trusted torch state_dict: $CKPT" >&2
  echo "convert/select the *_torch.bin artifact; native flat blobs cannot use --slowly" >&2
  exit 1
}

if ! "$ROOT/tools/install_puffer_env.sh" --check "$ROOT/vendor/PufferLib"; then
  echo "stale PufferLib bloodbowl snapshot; reinstall before eval:" >&2
  echo "  $ROOT/tools/install_puffer_env.sh $ROOT/vendor/PufferLib" >&2
  exit 1
fi
grep -q 'if i == 96:' "$ROOT/vendor/PufferLib/pufferlib/pufferl.py" || {
  echo "Puffer dashboard patch missing; interval n/late metrics would be hidden" >&2
  exit 1
}
grep -q 'PUFFER_ENV_JSON' "$ROOT/vendor/PufferLib/pufferlib/pufferl.py" || {
  echo "Puffer machine-readable metric patch missing; long names would be lossy" >&2
  exit 1
}
grep -q "'_puffer_final_reprint'" "$ROOT/vendor/PufferLib/pufferlib/pufferl.py" || {
  echo "Puffer phase/cumulative/reprint metadata patch missing" >&2
  exit 1
}
grep -q 'metrics.setdefault' "$ROOT/vendor/PufferLib/pufferlib/pufferl.py" || {
  echo "Puffer dynamic metric-key patch missing; final eval may crash" >&2
  echo "rerun tools/install_puffer_env.sh before evaluation" >&2
  exit 1
}
"$PYBIN" - <<'PY' || {
from pufferlib import _C
assert getattr(_C, "env_name", None) == "bloodbowl"
assert bool(getattr(_C, "gpu", False))
assert int(_C.precision_bytes) == 4
PY
  echo "torch evaluation requires the bloodbowl GPU fp32 build" >&2
  exit 1
}

. "$ROOT/tools/cpu_cap.sh"

cd "$ROOT/vendor/PufferLib"
echo "measuring $CKPT vs scripted bot type=$BOT_TYPE team=$BOT_TEAM over $STEPS steps -> $LOG" >&2
CMD=("$PUFFER_BIN" train bloodbowl --slowly --selfplay.enabled 0 \
  --seed "$SEED" --train.seed "$SEED" --env.seed "$SEED" \
  --load-model-path "$CKPT" \
  --tag contact-bot-eval \
  --train.total-timesteps "$STEPS" \
  --train.learning-rate 0.000000000001 \
  --train.bc-coef 0 \
  --env.demo-reset-pct 0 \
  --env.scripted-opponent 1 \
  --env.scripted-opponent-type "$BOT_TYPE" \
  --env.scripted-opponent-team "$BOT_TEAM" \
  --vec.total-agents 256 --vec.num-threads "${OMP_NUM_THREADS:-8}" \
  --train.minibatch-size 2048)
[ -n "$EVAL_EPISODES" ] && \
  CMD+=(--eval-episodes "$EVAL_EPISODES")

CKPT_SHA="$(sha256sum "$CKPT" | awk '{print $1}')"
CONFIG_SHA="$(sha256sum config/bloodbowl.ini | awk '{print $1}')"
MODULE_PATH="$("$PYBIN" -c 'from pufferlib import _C; print(_C.__file__)')"
[ -f "$MODULE_PATH" ] || { echo "imported pufferlib module missing: $MODULE_PATH" >&2; exit 1; }
MODULE_SHA="$(sha256sum "$MODULE_PATH" | awk '{print $1}')"
PUFFERL_SHA="$(sha256sum pufferlib/pufferl.py | awk '{print $1}')"
LAUNCHER_SHA="$(sha256sum "$ROOT/tools/eval_vs_contact_bot.sh" | awk '{print $1}')"
"$PYBIN" - "$CKPT" "$CKPT_SHA" "$STEPS" "$SEED" "$CONFIG_SHA" "$MODULE_SHA" \
  "$BOT_TYPE" "$BOT_TEAM" "$EVAL_EPISODES" "$MIN_EVAL_GAMES" \
  "$PUFFERL_SHA" "$LAUNCHER_SHA" "${CMD[@]}" <<'PY' > "$LOG"
import json, sys
(checkpoint, checkpoint_sha, steps, seed, config_sha, module_sha,
 bot_type, bot_team, eval_episodes, min_eval_games, pufferl_sha,
 launcher_sha, *command) = sys.argv[1:]
print("BB_EVAL_MANIFEST " + json.dumps({
    "schema_version": 1,
    "mode": "scripted_bot_frozen",
    "backend": "torch",
    "checkpoint": checkpoint,
    "checkpoint_sha256": checkpoint_sha,
    "requested_train_steps": int(steps),
    "seed": int(seed),
    "config_sha256": config_sha,
    "compiled_module_sha256": module_sha,
    "pufferl_sha256": pufferl_sha,
    "launcher_sha256": launcher_sha,
    "bot_type": int(bot_type),
    "bot_team": int(bot_team),
    "eval_episodes": int(eval_episodes) if eval_episodes else None,
    "min_eval_games": int(min_eval_games),
    "command": command,
}, sort_keys=True, allow_nan=False))
PY
"${CMD[@]}" >> "$LOG" 2>&1

"$PYBIN" - "$ROOT" "$LOG" "$MIN_EVAL_GAMES" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/tools")
from game_stats import dashboard_windows, weighted_dashboard

log, minimum = sys.argv[2], int(sys.argv[3])
windows = dashboard_windows(log)
if not windows:
    raise SystemExit("scripted eval produced no telemetry windows")
if any(int(window.get("_puffer_schema", 0)) < 2 for window in windows):
    raise SystemExit("scripted eval contains pre-schema-2 telemetry")
finals = [
    window for window in windows
    if window.get("_puffer_final_reprint", 0) > 0
    and window.get("_puffer_phase_eval", 0) > 0
]
if len(finals) != 1:
    raise SystemExit(
        f"scripted eval requires one final eval reprint, found {len(finals)}")
completed = finals[0].get("_puffer_eval_episodes_completed", 0)
if completed < minimum:
    raise SystemExit(
        f"scripted eval cumulative gate failed: {completed:g} < {minimum}")
values = weighted_dashboard(log)
games = values.get("n", 0)
if games < minimum:
    raise SystemExit(f"scripted eval sample too small: {games:g} < {minimum}")
integrity = (
    "reward_clip_episodes", "reward_nonfinite_episodes", "error_episodes",
    "demo_episodes", "demo_fallbacks",
)
bad = {key: values.get(key, 0) for key in integrity if values.get(key, 0) != 0}
if bad:
    raise SystemExit(f"scripted eval integrity gate failed: {bad}")
print(f"validated scripted eval: {games:.0f} games; cumulative gate {completed:.0f}")
PY

echo "done. contact-bot strength readout:" >&2
python3 "$ROOT/tools/contact_bot_stats.py" "$LOG" "$BOT_TEAM" >&2
echo "generic behavior comparison:  python3 $ROOT/tools/game_stats.py $LOG" >&2
