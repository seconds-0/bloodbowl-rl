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
#       LADDER_NO_EARLY_END_TURN  1 = run the exam under the env-layer
#                     restriction no_early_end_turn: the champion's seat cannot
#                     choose END_TURN while it has a player to activate; the
#                     bot's seat is never restricted. For a checkpoint trained
#                     under the rule, which must also be examined under it
#                     (docs/no-early-end-turn-2026-10-05.md). Unset or 0 = off:
#                     the command and the eval manifest are what they were
#                     before the knob existed.
set -euo pipefail
CKPT="${1:?usage: eval_vs_contact_bot.sh <checkpoint.bin> [steps] [log]}"
STEPS="${2:-8000000}"
LOG="${3:-/tmp/contact_bot_eval.log}"
BOT_TYPE="${BOT_TYPE:-0}"
BOT_TEAM="${BOT_TEAM:-1}"
SEED="${SEED:-42}"
EVAL_EPISODES="${EVAL_EPISODES:-}"
MIN_EVAL_GAMES="${MIN_EVAL_GAMES:-${EVAL_EPISODES:-1}}"
NO_EARLY_END_TURN="${LADDER_NO_EARLY_END_TURN:-0}"
case "$NO_EARLY_END_TURN" in
  0|1) ;;
  *) echo "LADDER_NO_EARLY_END_TURN must be 0 or 1, got '$NO_EARLY_END_TURN'" >&2; exit 1 ;;
esac
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
# The trainer below runs under the interpreter named in the entrypoint's
# shebang, not under $PYBIN. A venv made with `cp -a` keeps the shebangs of
# the venv it was copied from, and that interpreter imports the OTHER
# checkout's pufferlib and compiled env while the manifest records this
# checkout's module. Under the rule that would run the exam on a module that
# may not know the flag, so it is refused; otherwise it is reported and the
# exam runs as it always did.
ENTRY_INTERPRETER="$(head -n 1 "$PUFFER_BIN" | sed -n 's/^#![[:space:]]*//p')"
if [ "$ENTRY_INTERPRETER" = "/bin/sh" ]; then
  ENTRY_INTERPRETER="$(sed -n "2s/^'''exec' \"\([^\"]*\)\".*/\1/p" "$PUFFER_BIN")"
fi
case "$ENTRY_INTERPRETER" in
  "$ROOT/vendor/PufferLib/.venv/bin/"*) ;;
  *)
    if [ "$NO_EARLY_END_TURN" = "1" ]; then
      echo "LADDER_NO_EARLY_END_TURN=1 refused: $PUFFER_BIN runs under '$ENTRY_INTERPRETER', which is not this checkout's venv ($ROOT/vendor/PufferLib/.venv); fix the venv's entrypoint shebangs" >&2
      exit 1
    fi
    echo "warning: $PUFFER_BIN runs under '$ENTRY_INTERPRETER', not this checkout's venv ($ROOT/vendor/PufferLib/.venv): the exam imports whatever pufferlib that interpreter resolves, and the eval manifest's module hash describes this checkout instead" >&2
    ;;
esac
if [ "${NATIVE:-0}" = "1" ]; then
  # Native flat fp32 blob: size-pinned, and its lineage sidecar must validate
  # against THIS build (the obs/action semantics are only knowable from it).
  "$PYBIN" "$ROOT/tools/checkpoint_lineage.py" validate --checkpoint "$CKPT" \
      --allow-qualification >/dev/null || {
    echo "NATIVE=1 requires a native flat blob with a valid lineage sidecar: $CKPT" >&2
    exit 1
  }
else
"$PYBIN" - "$CKPT" <<'PY' || {
import sys, torch
state = torch.load(sys.argv[1], map_location="cpu", weights_only=False)
assert isinstance(state, dict) and state, "checkpoint is not a nonempty state dict"
PY
  echo "checkpoint is not a trusted torch state_dict: $CKPT" >&2
  echo "convert/select the *_torch.bin artifact; native flat blobs cannot use --slowly" >&2
  exit 1
}
fi

if ! "$ROOT/tools/install_puffer_env.sh" --check "$ROOT/vendor/PufferLib"; then
  echo "stale PufferLib bloodbowl snapshot; reinstall before eval:" >&2
  echo "  $ROOT/tools/install_puffer_env.sh $ROOT/vendor/PufferLib" >&2
  exit 1
fi
# An eval manifest without no_early_end_turn says the rule was off, which is
# only true while the installed default is 0.
INSTALLED_CONFIG="$ROOT/vendor/PufferLib/config/bloodbowl.ini"
if grep -Eq '^no_early_end_turn[[:space:]]*=' "$INSTALLED_CONFIG" 2>/dev/null; then
  grep -Eq '^no_early_end_turn[[:space:]]*=[[:space:]]*0[[:space:]]*$' "$INSTALLED_CONFIG" || {
    echo "installed config sets no_early_end_turn itself; its default must be 0 (use LADDER_NO_EARLY_END_TURN=1 so the eval manifest records the rule)" >&2
    exit 1; }
elif [ "$NO_EARLY_END_TURN" = "1" ]; then
  echo "LADDER_NO_EARLY_END_TURN=1 needs an installed config with the no_early_end_turn key; install and rebuild this checkout" >&2
  exit 1
fi
grep -q 'if i == 160:' "$ROOT/vendor/PufferLib/pufferlib/pufferl.py" || {
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
if [ "$NO_EARLY_END_TURN" = "1" ]; then
  # An env module compiled before the flag existed would read the kwarg as
  # nothing and run the exam unrestricted under a restricted label.
  "$PYBIN" - "$ROOT/vendor/PufferLib/ocean/bloodbowl/.content_hash" <<'PY' || {
import pathlib, sys
from pufferlib import _C
installed = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8").strip()
compiled = getattr(_C, "environment_source_hash", "<missing>")
assert compiled == installed, (compiled, installed)
PY
    echo "LADDER_NO_EARLY_END_TURN=1 requires the compiled env module to be built from the installed source; rebuild before the exam" >&2
    exit 1
  }
fi

. "$ROOT/tools/cpu_cap.sh"

cd "$ROOT/vendor/PufferLib"
echo "measuring $CKPT vs scripted bot type=$BOT_TYPE team=$BOT_TEAM over $STEPS steps -> $LOG" >&2
# NATIVE=1: frozen eval on the native CUDA backend from the flat fp32 blob a
# rung publishes (no torch conversion, no zero-filled biases, ~30-80x the
# torch --slowly throughput). The scripted-training guard permits this
# because learning_rate <= 1e-9 -- the scripted seat's rows are never trained
# on, so the row-exclusion the guard exists for is moot. Default 0 keeps the
# historical torch path (needed only when the input is a torch state_dict).
if [ "${NATIVE:-0}" = "1" ]; then
  CMD=("$PUFFER_BIN" train bloodbowl --selfplay.enabled 0 \
    --vec.num-frozen-banks 0 --vec.frozen-bank-pct 0 \
    --seed "$SEED" --train.seed "$SEED" --env.seed "$SEED" \
    --load-model-path "$CKPT" \
    --tag contact-bot-eval \
    --train.total-timesteps "$STEPS" \
    --train.learning-rate 0.000000000001 \
    --env.demo-reset-pct 0 \
    --env.scripted-opponent 1 \
    --env.scripted-opponent-type "$BOT_TYPE" \
    --env.scripted-opponent-team "$BOT_TEAM" \
    --vec.total-agents 2048 --vec.num-buffers 2 \
    --vec.num-threads "${OMP_NUM_THREADS:-8}" \
    --train.horizon 64 --train.minibatch-size 16384)
else
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
fi
[ -n "$EVAL_EPISODES" ] && \
  CMD+=(--eval-episodes "$EVAL_EPISODES")
if [ "$NO_EARLY_END_TURN" = "1" ]; then
  CMD+=(--env.no-early-end-turn 1)
fi

CKPT_SHA="$(sha256sum "$CKPT" | awk '{print $1}')"
"$PYBIN" - "$ROOT" "$CKPT" "$CKPT_SHA" "$STEPS" "$SEED" \
  "$BOT_TYPE" "$BOT_TEAM" "$EVAL_EPISODES" "$MIN_EVAL_GAMES" \
  "$NO_EARLY_END_TURN" "${CMD[@]}" <<'PY' > "$LOG"
import json, sys
from pathlib import Path

(root, checkpoint, checkpoint_sha, steps, seed, bot_type, bot_team,
 eval_episodes, min_eval_games, no_early_end_turn, *command) = sys.argv[1:]
sys.path.insert(0, str(Path(root) / "tools"))
from run_reward_candidate_transfer import implementation_identity

manifest = {
    "schema_version": 1,
    "mode": "scripted_bot_frozen",
    "backend": "torch",
    "checkpoint": checkpoint,
    "checkpoint_sha256": checkpoint_sha,
    "requested_train_steps": int(steps),
    "seed": int(seed),
    **implementation_identity(Path(root)),
    "bot_type": int(bot_type),
    "bot_team": int(bot_team),
    "eval_episodes": int(eval_episodes) if eval_episodes else None,
    "min_eval_games": int(min_eval_games),
    "command": command,
}
if no_early_end_turn == "1":
    # Present only when the rule is on, so an exam without it writes the
    # manifest it always did.
    manifest["no_early_end_turn"] = 1
print("BB_EVAL_MANIFEST " + json.dumps(manifest, sort_keys=True, allow_nan=False))
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
    "reward_clip_frac", "reward_clip_frac_nonzero", "reward_clip_excess",
    "reward_nonfinite_frac", "reward_clip_episodes",
    "reward_nonfinite_episodes", "error_episodes", "demo_episodes",
    "demo_fallbacks",
)
missing = [key for key in integrity if key not in values]
if missing:
    raise SystemExit(f"scripted eval missing integrity counters: {missing}")
bad = {key: values[key] for key in integrity if values[key] != 0}
if bad:
    raise SystemExit(f"scripted eval integrity gate failed: {bad}")
print(f"validated scripted eval: {games:.0f} games; cumulative gate {completed:.0f}")
PY

echo "done. contact-bot strength readout:" >&2
python3 "$ROOT/tools/contact_bot_stats.py" "$LOG" "$BOT_TEAM" >&2
echo "generic behavior comparison:  python3 $ROOT/tools/game_stats.py $LOG" >&2
