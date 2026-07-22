#!/usr/bin/env bash
# eval_game_stats.sh — run a checkpoint through FULL GAMES from kickoff and
# emit a dashboard log whose per-game stats are comparable to the human
# baseline (docs/human-baseline.json). Feed the output to game_stats.py.
#
#   bash tools/eval_game_stats.sh <CHECKPOINT.bin> [STEPS] [LOG]
#       CHECKPOINT  torch state_dict .bin (the training-side format, NOT a
#                   _cuda flat blob). Run ON a box from /root/bloodbowl-rl.
#       STEPS       measurement length, default 8M (~thousands of full games
#                   at 128 agents; plenty for stable per-game averages).
#       LOG         output path, default /tmp/game_stats_eval.log
#
# Mechanism: a FROZEN measurement pass — learning-rate ~0, bc-coef 0,
# selfplay off, demo-reset-pct 0 (KICKOFF starts, the whole point — training
# arms use 0.9 curriculum starts which are NOT human-comparable). The env's
# my_log dashboard then reports true per-game tds/blocks/dodges/gfi/pickups/
# possession + the 2d tier fractions. Then:
#   python3 tools/game_stats.py <LOG>
# The analyzer weights every dashboard interval by its visible `n`; the
# installed Puffer tree must include training/pufferl_env_dashboard_limit.patch
# or the analysis fails closed instead of treating the final tiny window as the
# whole run.
set -euo pipefail
CKPT="${1:?usage: eval_game_stats.sh <checkpoint.bin> [steps] [log]}"
STEPS="${2:-8000000}"
LOG="${3:-/tmp/game_stats_eval.log}"
SEED="${SEED:-42}"
# consume the positionals so "$@" below carries ONLY trailing puffer args
for _ in 1 2 3; do [ $# -gt 0 ] && shift; done
if [ $# -ne 0 ]; then
  echo "trailing Puffer overrides are not allowed by this frozen-eval contract" >&2
  exit 1
fi
case "$STEPS:$SEED" in
  *[!0-9:]*) echo "STEPS and SEED must be non-negative integers" >&2; exit 1 ;;
esac
[ "$STEPS" -gt 0 ] || { echo "STEPS must be positive" >&2; exit 1; }
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# Anchor relative paths NOW — the cd to vendor/PufferLib below breaks them
# (same footgun as run_synthesis_c.sh's ANCHOR: the file-exists check passes
# pre-cd, then puffer FileNotFoundErrors post-cd).
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
  echo "stale PufferLib Blood Bowl snapshot; reinstall and rebuild before eval" >&2
  exit 1
fi
grep -q 'if i == 160:' "$ROOT/vendor/PufferLib/pufferlib/pufferl.py" || {
  echo "Puffer dashboard patch missing; later metrics and interval n would be hidden" >&2
  echo "run tools/install_puffer_env.sh and rerun the eval" >&2
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
"$PYBIN" - <<'PY' || {
from pufferlib import _C
assert getattr(_C, "env_name", None) == "bloodbowl"
assert bool(getattr(_C, "gpu", False))
assert int(_C.precision_bytes) == 4
PY
  echo "torch evaluation requires the bloodbowl GPU fp32 build" >&2
  exit 1
}

# Same CPU thread cap as the training launchers (D59).
. "$ROOT/tools/cpu_cap.sh"

cd "$ROOT/vendor/PufferLib"
echo "measuring $CKPT over $STEPS steps (kickoff starts, frozen) -> $LOG" >&2
# --slowly = torch backend (loads a torch state_dict). lr 1e-12 + bc-coef 0 =
# effectively frozen; demo-reset-pct 0 = full games from kickoff.
CMD=("$PUFFER_BIN" train bloodbowl --slowly --selfplay.enabled 0 \
  --seed "$SEED" --train.seed "$SEED" --env.seed "$SEED" \
  --load-model-path "$CKPT" \
  --tag game-stats-eval \
  --train.total-timesteps "$STEPS" \
  --train.learning-rate 0.000000000001 \
  --train.bc-coef 0 \
  --env.demo-reset-pct 0 \
  --vec.total-agents 256 --vec.num-threads "${OMP_NUM_THREADS:-8}" \
  --train.minibatch-size 2048)

CKPT_SHA="$(sha256sum "$CKPT" | awk '{print $1}')"
CONFIG_SHA="$(sha256sum config/bloodbowl.ini | awk '{print $1}')"
MODULE_PATH="$("$PYBIN" -c 'from pufferlib import _C; print(_C.__file__)')"
[ -f "$MODULE_PATH" ] || { echo "imported pufferlib module missing: $MODULE_PATH" >&2; exit 1; }
MODULE_SHA="$(sha256sum "$MODULE_PATH" | awk '{print $1}')"
"$PYBIN" - "$CKPT" "$CKPT_SHA" "$STEPS" "$SEED" "$CONFIG_SHA" "$MODULE_SHA" \
  "${CMD[@]}" <<'PY' > "$LOG"
import json, sys
checkpoint, checkpoint_sha, steps, seed, config_sha, module_sha, *command = sys.argv[1:]
print("BB_EVAL_MANIFEST " + json.dumps({
    "schema_version": 1,
    "mode": "kickoff_frozen_mirror",
    "backend": "torch",
    "checkpoint": checkpoint,
    "checkpoint_sha256": checkpoint_sha,
    "requested_train_steps": int(steps),
    "seed": int(seed),
    "config_sha256": config_sha,
    "compiled_module_sha256": module_sha,
    "command": command,
}, sort_keys=True, allow_nan=False))
PY
"${CMD[@]}" >> "$LOG" 2>&1

echo "done. compare with:  python3 $ROOT/tools/game_stats.py $LOG" >&2
