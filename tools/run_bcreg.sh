#!/usr/bin/env bash
# Launch the BC-anchored training run (profile-BCreg): PPO with an auxiliary
# human-imitation CE anchor so selfplay can't erode the BC prior
# (DECISIONS.md D27; patch: training/torch_pufferl_bcreg.patch).
#
#   tools/run_bcreg.sh [extra puffer args...]
#
# Backend: the PYTORCH trainer (--slowly) on a CUDA box — torch_pufferl.py
# picks device cuda when _C is GPU-capable. The BC anchor lives only in the
# torch backend; the native CUDA trainer ignores bc_* keys. Consequences:
#   * _C must be built with ./build.sh bloodbowl --float (torch backend
#     requires fp32 precision; default CUDA build is bf16).
#   * selfplay pool is native-only -> --selfplay.enabled 0 (pure mirror
#     selfplay; both slots share the current policy).
#   * exact conditional action masks are supported by the Torch backend.
# Reward shaping: B profile (event-realized knobs, tools/train_profile.sh).
# Warm start: training/bc_v1.bin (torch state_dict, loads directly).
# BC anchor: bc_coef 1.0, cosine-annealed to 0.1 over total_timesteps.
set -euo pipefail
if [ "${ALLOW_LEGACY_BCREG:-0}" != "1" ]; then
  echo "run_bcreg.sh is a historical BBP/checkpoint-v1 reproduction only." >&2
  echo "Current exact-action training requires BBP v4; set ALLOW_LEGACY_BCREG=1 only to reproduce the rejected historical arm." >&2
  exit 1
fi
# Mac uses the repo venv; GPU boxes install into system python.
PYBIN="python3"
[ -x "vendor/PufferLib/.venv/bin/python" ] && PYBIN="vendor/PufferLib/.venv/bin/python"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/vendor/PufferLib"

bash "$ROOT/tools/install_puffer_env.sh" --check || {
  echo "stale env snapshot — run tools/install_puffer_env.sh first" >&2; exit 1; }

# BC-reg patch must be present in the vendored torch trainer (vendor/*/ is
# gitignored — a re-clone loses it). Auto-reapply from the saved diff.
if ! grep -q 'BC-regularized PPO' pufferlib/torch_pufferl.py; then
  echo "applying training/torch_pufferl_bcreg.patch to vendored torch_pufferl.py"
  git apply "$ROOT/training/torch_pufferl_bcreg.patch"
fi

# Torch backend on GPU needs a float-precision, GPU-capable _C for this env.
$PYBIN - <<'EOF' || { echo "fix: ./build.sh bloodbowl --float" >&2; exit 1; }
from pufferlib import _C
assert getattr(_C, 'env_name', None) == 'bloodbowl', f"_C built for {getattr(_C, 'env_name', None)}, not bloodbowl"
assert _C.precision_bytes == 4, "torch backend needs fp32: rebuild with ./build.sh bloodbowl --float"
assert _C.gpu, "_C is a CPU build — rebuild on the CUDA box with ./build.sh bloodbowl --float"
EOF

BC_BIN="$ROOT/training/bc_v1.bin"
[ -f "$BC_BIN" ] || { echo "missing $BC_BIN (BC warm-start checkpoint)" >&2; exit 1; }
ls "$ROOT"/validation/pairs/*.bbp >/dev/null 2>&1 || {
  echo "no .bbp shards in $ROOT/validation/pairs — run validation/extract_pairs.py" >&2; exit 1; }

# PROFILE marker for the spectator feed (same trick as train_profile.sh:
# the trainer creates its run dir within ~30s of launch).
(
  sleep 30
  d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
  [ -n "$d" ] && echo "profile-BCreg (KL-anchored)" > "${d}PROFILE"
) &

exec puffer train bloodbowl --slowly --tag profile-BCreg \
  --selfplay.enabled 0 \
  --load-model-path "$BC_BIN" \
  --train.bc-coef 1.0 \
  --train.bc-coef-anneal 1 \
  --train.bc-batch 512 \
  --train.bc-pairs-dir "$ROOT/validation/pairs" \
  --env.reward-draw -0.5 \
  --env.reward-setup-done 0.25 --env.reward-setup-autofix -0.25 \
  --env.reward-ball-gain 0.1 --env.reward-ball-loss -0.5 \
  --env.reward-injury-inflicted 0.15 --env.reward-injury-taken -0.15 \
  --env.reward-injury-value-scaled 1 \
  --env.reward-surf-taken -0.1 --env.reward-surf-inflicted 0.1 \
  --eval-episodes 200 \
  "$@"
