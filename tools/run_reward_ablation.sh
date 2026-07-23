#!/usr/bin/env bash
# Launch one native, static-pool reward-ablation arm from a complete manifest.
#
# Required for every mode:
#   TAG=<unique arm tag>
#   REWARD_MANIFEST=<puffer/config/rewards/*.json>
#   BOOTSTRAP_MODE=fresh-v5-qualification|fresh-v5-genesis|lineage-v5
# lineage-v5 additionally requires WARM and POOL with eligible obs-v5 lineage
# sidecars. fresh-v5-qualification forbids both inputs.
#
# Optional:
#   STEPS=250000000 SEED=42 LOG=/tmp/$TAG.log
#   TOTAL_AGENTS=2048 NUM_BUFFERS=2 NUM_THREADS=<cpu cap>
#   FROZEN_BANK_PCT=0.06 EXPECT_BYTES=16066560
#   LR=0.00028 ENT_COEF=0.009 GAMMA=0.995 GAE_LAMBDA=0.85
#   HORIZON=64 MINIBATCH_SIZE=16384 CHECKPOINT_STEPS=50000000
#   RIG_ALLOW_FLOAT=1   required for native fp32 on the RTX 2070/Turing rig
#   DRY_RUN=1           validate every artifact/build contract and print the
#                       final command without starting a trainer
#
# This is a causal launcher, not a general Puffer wrapper. It refuses every
# trailing argument so argparse's last-wins behavior cannot invalidate PROFILE.
set -euo pipefail

LAUNCH_CWD="$PWD"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

: "${TAG:?TAG is required}"
: "${REWARD_MANIFEST:?REWARD_MANIFEST is required}"

if [ $# -ne 0 ]; then
  echo "trailing Puffer overrides are not allowed by this ablation contract" >&2
  exit 1
fi

: "${BOOTSTRAP_MODE:?BOOTSTRAP_MODE is required}"
case "$BOOTSTRAP_MODE" in
  fresh-v5-qualification)
    [ -z "${WARM:-}" ] || {
      echo "fresh-v5-qualification forbids WARM" >&2; exit 1; }
    [ -z "${POOL:-}" ] || {
      echo "fresh-v5-qualification forbids POOL" >&2; exit 1; }
    WARM=""
    POOL=""
    QUALIFICATION_ONLY=1
    ;;
  fresh-v5-genesis)
    # The genesis of an obs-v5 lineage. Structurally identical to the
    # qualification canary -- fresh weights, no warm start, no opponent pool --
    # and differing in exactly one respect: its accepted checkpoint publishes an
    # ELIGIBLE lineage, so it can be warm-started from and can seed a pool.
    #
    # This mode exists because without it the lineage cannot begin. Eligible
    # lineage may only be published by an accepted screen result
    # (tools/checkpoint_lineage.py), and every non-fresh profile requires an
    # already-eligible warm checkpoint plus a four-bank pool of eligible
    # checkpoints. That is a closed loop with no entry point: measured on the
    # training host, zero .lineage.json files exist anywhere, so there is no
    # ancestor to start from and no way to mint one.
    #
    # It is NOT a weaker canary. It passes the identical acceptance gate --
    # all 16 hard-integrity counters at literal zero, required metrics, the
    # completed-game floor, the telemetry-schema check, exact final checkpoint
    # size -- and it must carry a complete reward manifest like any causal arm.
    # The only thing being granted is ancestry, which every lineage needs at its
    # root; the alternative is that obs-v5 can never train at all.
    [ -z "${WARM:-}" ] || {
      echo "fresh-v5-genesis forbids WARM; genesis is by definition unancestored" >&2
      exit 1; }
    [ -z "${POOL:-}" ] || {
      echo "fresh-v5-genesis forbids POOL; there is no eligible pool to draw on yet" >&2
      exit 1; }
    WARM=""
    POOL=""
    QUALIFICATION_ONLY=0
    ;;
  lineage-v5)
    : "${WARM:?WARM is required for lineage-v5}"
    : "${POOL:?POOL is required for lineage-v5}"
    QUALIFICATION_ONLY=0
    ;;
  *)
    echo "BOOTSTRAP_MODE must be fresh-v5-qualification, fresh-v5-genesis, or lineage-v5" >&2
    exit 1
    ;;
esac

STEPS="${STEPS:-250000000}"
SEED="${SEED:-42}"
LOG="${LOG:-/tmp/${TAG}.log}"
TOTAL_AGENTS="${TOTAL_AGENTS:-2048}"
NUM_BUFFERS="${NUM_BUFFERS:-2}"
FROZEN_BANK_PCT="${FROZEN_BANK_PCT:-0.06}"
EXPECT_BYTES="${EXPECT_BYTES:-16066560}"
LR="${LR:-0.00028}"
ENT_COEF="${ENT_COEF:-0.009}"
GAMMA="${GAMMA:-0.995}"
GAE_LAMBDA="${GAE_LAMBDA:-0.85}"
HORIZON="${HORIZON:-64}"
MINIBATCH_SIZE="${MINIBATCH_SIZE:-16384}"
CHECKPOINT_STEPS="${CHECKPOINT_STEPS:-50000000}"
REPLAY_RATIO="${REPLAY_RATIO:-0.25}"
CLIP_COEF="${CLIP_COEF:-0.2}"
VF_COEF="${VF_COEF:-1.0}"
VF_CLIP_COEF="${VF_CLIP_COEF:-0.5}"
MAX_GRAD_NORM="${MAX_GRAD_NORM:-1.5}"
DETACH="${DETACH:-1}"
QUEUE_OWNED="${QUEUE_OWNED:-0}"
EXPECTED_POOL_HASH="${EXPECTED_POOL_HASH:-}"
SCREEN_MANIFEST_SHA256="${SCREEN_MANIFEST_SHA256:-}"
EXPECTED_PUFFER_PATCH_BUNDLE_SHA256="${EXPECTED_PUFFER_PATCH_BUNDLE_SHA256:-}"
LIVE_INTEGRITY_FAILURE="${LIVE_INTEGRITY_FAILURE:-}"
LIVE_INTEGRITY_MAX_SILENCE="${LIVE_INTEGRITY_MAX_SILENCE:-180}"
LIVE_INTEGRITY_POLL_SECONDS="${LIVE_INTEGRITY_POLL_SECONDS:-30}"

for digest_name in SCREEN_MANIFEST_SHA256 \
                   EXPECTED_PUFFER_PATCH_BUNDLE_SHA256; do
  digest="${!digest_name}"
  if [ -n "$digest" ] && [[ ! "$digest" =~ ^[0-9a-f]{64}$ ]]; then
    echo "$digest_name must be empty or a lowercase SHA-256 digest" >&2
    exit 1
  fi
done
case "$DETACH" in
  0|1) ;;
  *) echo "DETACH must be 0 or 1" >&2; exit 1 ;;
esac
case "$QUEUE_OWNED" in
  0|1) ;;
  *) echo "QUEUE_OWNED must be 0 or 1" >&2; exit 1 ;;
esac
case "$LIVE_INTEGRITY_MAX_SILENCE:$LIVE_INTEGRITY_POLL_SECONDS" in
  *[!0-9:]*) echo "live-integrity silence and poll budgets must be positive integers" >&2; exit 1 ;;
esac
if [ "$LIVE_INTEGRITY_MAX_SILENCE" -le 0 ] || \
   [ "$LIVE_INTEGRITY_POLL_SECONDS" -le 0 ]; then
  echo "live-integrity silence and poll budgets must be positive" >&2
  exit 1
fi
if [ -n "$SCREEN_MANIFEST_SHA256" ] && [ -z "$LIVE_INTEGRITY_FAILURE" ]; then
  echo "a screen-owned arm requires LIVE_INTEGRITY_FAILURE" >&2
  exit 1
fi
if [ "$DETACH" = "0" ] && [ "$QUEUE_OWNED" != "1" ]; then
  echo "DETACH=0 is reserved for a queue-owned process group" >&2
  exit 1
fi

abspath() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "$LAUNCH_CWD/$1" ;;
  esac
}
REWARD_MANIFEST="$(abspath "$REWARD_MANIFEST")"
[ -z "$WARM" ] || WARM="$(abspath "$WARM")"
[ -z "$POOL" ] || POOL="$(abspath "$POOL")"
LOG="$(abspath "$LOG")"

case "$STEPS:$SEED:$TOTAL_AGENTS:$NUM_BUFFERS:$EXPECT_BYTES:$HORIZON:$MINIBATCH_SIZE:$CHECKPOINT_STEPS" in
  *[!0-9:]*)
    echo "step/seed/agent/buffer/byte/horizon/minibatch/checkpoint values must be non-negative integers" >&2
    exit 1 ;;
esac
if [ "$STEPS" -le 0 ] || [ "$TOTAL_AGENTS" -le 0 ] || \
   [ "$NUM_BUFFERS" -le 0 ] || [ "$EXPECT_BYTES" -le 0 ] || \
   [ "$HORIZON" -le 0 ] || [ "$MINIBATCH_SIZE" -le 0 ] || \
   [ "$CHECKPOINT_STEPS" -le 0 ]; then
  echo "step/agent/buffer/byte/horizon/minibatch/checkpoint values must be positive" >&2
  exit 1
fi
if [ "$EXPECT_BYTES" -ne 16066560 ]; then
  echo "obs-v5/exact-joint-v1 requires EXPECT_BYTES=16066560; got $EXPECT_BYTES" >&2
  exit 1
fi
if [ $(( TOTAL_AGENTS % NUM_BUFFERS )) -ne 0 ]; then
  echo "TOTAL_AGENTS must be divisible by NUM_BUFFERS" >&2
  exit 1
fi
ROLLOUT_QUANTUM=$(( TOTAL_AGENTS * HORIZON ))
TRAIN_EPOCHS=$(( STEPS / ROLLOUT_QUANTUM ))
if [ "$TRAIN_EPOCHS" -le 0 ]; then
  echo "STEPS=$STEPS is smaller than one rollout quantum ($ROLLOUT_QUANTUM)" >&2
  exit 1
fi
FINAL_STEPS=$(( TRAIN_EPOCHS * ROLLOUT_QUANTUM ))
CHECKPOINT_INTERVAL=$(( (CHECKPOINT_STEPS + ROLLOUT_QUANTUM / 2) / ROLLOUT_QUANTUM ))
[ "$CHECKPOINT_INTERVAL" -gt 0 ] || CHECKPOINT_INTERVAL=1
OPP_TIMEOUT=$(( STEPS * 10 ))

PYBIN="$ROOT/vendor/PufferLib/.venv/bin/python"
PUFFER_BIN="$ROOT/vendor/PufferLib/.venv/bin/puffer"
CUDA_RUNTIME_WRAPPER="$ROOT/tools/puffer_cuda_runtime.py"
[ -x "$PYBIN" ] || { echo "vendored Python missing: $PYBIN" >&2; exit 1; }
[ -x "$PUFFER_BIN" ] || { echo "vendored puffer entrypoint missing: $PUFFER_BIN" >&2; exit 1; }
[ -f "$CUDA_RUNTIME_WRAPPER" ] || {
  echo "CUDA runtime wrapper missing: $CUDA_RUNTIME_WRAPPER" >&2; exit 1; }
[ "${CUDA_VISIBLE_DEVICES:-}" = "0" ] || {
  echo "CUDA_VISIBLE_DEVICES must be exactly 0" >&2; exit 1; }
if [ "$BOOTSTRAP_MODE" != "lineage-v5" ]; then
  FROZEN_BANK_PCT=0
  NUM_FROZEN_BANKS=0
  FROZEN_PER_BANK=0
  HISTORICAL_GAME_SHARE=0
  [ -z "$EXPECTED_POOL_HASH" ] || {
    echo "fresh-v5-qualification forbids EXPECTED_POOL_HASH" >&2; exit 1; }
else
  NUM_FROZEN_BANKS=4
  [ -n "$EXPECTED_POOL_HASH" ] || {
    echo "lineage-v5 requires EXPECTED_POOL_HASH" >&2; exit 1; }
  read -r FROZEN_PER_BANK HISTORICAL_GAME_SHARE < <(
    "$PYBIN" - "$TOTAL_AGENTS" "$NUM_BUFFERS" "$FROZEN_BANK_PCT" <<'PY'
import math, sys
total, buffers = map(int, sys.argv[1:3])
try:
    pct = float(sys.argv[3])
except ValueError as exc:
    raise SystemExit("FROZEN_BANK_PCT must be numeric") from exc
if not math.isfinite(pct) or pct <= 0:
    raise SystemExit("FROZEN_BANK_PCT must be finite and positive")
apb = total // buffers
per_bank = int(apb * pct)
if per_bank <= 0:
    raise SystemExit("FROZEN_BANK_PCT rounds to zero rows per bank")
total_frozen = 4 * per_bank
if total_frozen >= apb // 2:
    raise SystemExit(
        f"four banks reserve {total_frozen} rows/buffer, must be < {apb//2}")
print(per_bank, total_frozen / (apb / 2.0))
PY
  )
fi

[ -f "$REWARD_MANIFEST" ] || { echo "missing reward manifest: $REWARD_MANIFEST" >&2; exit 1; }
if [ "$BOOTSTRAP_MODE" = "lineage-v5" ]; then
  [ -f "$WARM" ] || { echo "missing warm checkpoint: $WARM" >&2; exit 1; }
  [ -f "$POOL/league_seeds.json" ] || { echo "missing $POOL/league_seeds.json" >&2; exit 1; }
fi

RUN_MANIFEST="${LOG}.manifest.json"
STATUS_FILE="${LOG}.status.json"
RUN_DIR_FILE="${LOG}.run_dir"
PROCESS_FILE="${LOG}.process.json"
GUARD_MARKER="${LOG}.guard-failed"
CUDA_RUNTIME_EVIDENCE="${LOG}.cuda-runtime.json"
for artifact in "$LOG" "$RUN_MANIFEST" "$STATUS_FILE" "$RUN_DIR_FILE" \
                "$PROCESS_FILE" "$GUARD_MARKER" "$CUDA_RUNTIME_EVIDENCE"; do
  [ ! -e "$artifact" ] || {
    echo "refusing to overwrite existing run artifact: $artifact" >&2
    exit 1
  }
done

command -v flock >/dev/null 2>&1 || {
  echo "flock is required for the one-trainer contract" >&2; exit 1; }
exec 9>/tmp/bloodbowl-rl-reward-ablation.lock
if ! flock -n 9; then
  echo "another reward-ablation launcher or inherited trainer holds the host lock" >&2
  exit 1
fi

if pgrep -f '[p]uffer_cuda_runtime.py train|[p]uffer train' >/dev/null; then
  echo "a puffer trainer is already live on this host" >&2
  pgrep -af '[p]uffer_cuda_runtime.py train|[p]uffer train' >&2 || true
  exit 1
fi
command -v nvidia-smi >/dev/null 2>&1 || {
  echo "no nvidia-smi; run this launcher on a CUDA host" >&2; exit 1; }

cd "$ROOT/vendor/PufferLib"

REWARD_ARGS=()
while IFS= read -r token; do REWARD_ARGS+=("$token"); done < <(
  "$PYBIN" "$ROOT/tools/reward_manifest.py" "$REWARD_MANIFEST" --lines)
read -r REWARD_NAME REWARD_HASH REWARD_PBRS_GAMMA < <(
  "$PYBIN" - "$ROOT" "$REWARD_MANIFEST" <<'PY'
import sys
sys.path.insert(0, sys.argv[1] + "/tools")
from reward_manifest import load_manifest
manifest, digest = load_manifest(sys.argv[2])
# 0 means the manifest is schema 1, i.e. legacy raw delta-Phi distance shaping.
print(manifest["name"], digest,
      manifest["reward"].get("reward_dist_pbrs_gamma", 0.0))
PY
)

# Exact PBRS is only exact at the gamma the trainer actually discounts with. A
# mismatch does not fail loudly -- it silently reintroduces the same class of
# bias the discounted form exists to remove -- so it is checked here, where both
# numbers are in scope, rather than left to the env which cannot see train.gamma.
if [ "${REWARD_PBRS_GAMMA:-0}" != "0" ] && [ "${REWARD_PBRS_GAMMA:-0}" != "0.0" ]; then
  if ! "$PYBIN" -c "
import sys
manifest_gamma, train_gamma = float(sys.argv[1]), float(sys.argv[2])
sys.exit(0 if abs(manifest_gamma - train_gamma) <= 1e-9 else 1)
" "$REWARD_PBRS_GAMMA" "$GAMMA"; then
    echo "reward_dist_pbrs_gamma ($REWARD_PBRS_GAMMA) != train gamma ($GAMMA):" \
         "the distance channels would not be exact PBRS under this trainer" >&2
    exit 1
  fi
fi

WARM_HASH=""
WARM_LINEAGE_HASH=""
POOL_HASH=""
POOL_BANKS=0
POOL_MANIFEST_HASH=""
POOL_LINEAGE_BUNDLE_HASH=""
warm_size=0
if [ "$BOOTSTRAP_MODE" = "lineage-v5" ]; then
  warm_size=$(wc -c < "$WARM")
  if [ "$warm_size" -ne "$EXPECT_BYTES" ]; then
    echo "warm checkpoint is $warm_size bytes; expected $EXPECT_BYTES" >&2
    exit 1
  fi

  # Validate the pool body, bank order, hashes, lineage paths, and architecture
  # before any trainer allocates GPU state.
  read -r POOL_HASH POOL_BANKS POOL_MANIFEST_HASH < <(
    "$PYBIN" - "$POOL" "$EXPECT_BYTES" <<'PY'
import hashlib, json, pathlib, sys
pool = pathlib.Path(sys.argv[1])
expect = int(sys.argv[2])
manifest_path = pool / "league_seeds.json"
manifest_raw = manifest_path.read_bytes()
manifest = json.loads(manifest_raw)
if manifest.get("expected_bytes") != expect:
    raise SystemExit(
        f"pool expected_bytes={manifest.get('expected_bytes')}, expected {expect}")
seeds = manifest.get("seeds")
if not isinstance(seeds, list) or len(seeds) != 4:
    raise SystemExit("static reward pool must contain exactly four seeds")
identity = []
seen_names = set()
seen_hashes = set()
for index, seed in enumerate(seeds):
    if seed.get("bank") != index:
        raise SystemExit(f"pool bank order mismatch at {index}: {seed.get('bank')}")
    name = seed.get("name")
    if not isinstance(name, str) or not name or name in seen_names:
        raise SystemExit(f"pool bank {index} has missing/duplicate name {name!r}")
    seen_names.add(name)
    path = pool / seed["file"]
    blob = path.read_bytes()
    digest = hashlib.sha256(blob).hexdigest()
    if len(blob) != expect:
        raise SystemExit(f"{path}: {len(blob)} bytes, expected {expect}")
    if seed.get("bytes") != len(blob) or seed.get("sha256") != digest:
        raise SystemExit(f"{path}: manifest size/hash mismatch")
    lineage_file = seed.get("lineage_file")
    if not isinstance(lineage_file, str) or not lineage_file:
        raise SystemExit(f"pool bank {index} lacks lineage_file")
    lineage_path = pool / lineage_file
    if not lineage_path.is_file():
        raise SystemExit(f"pool bank {index} lineage is missing: {lineage_path}")
    lineage_sha = seed.get("lineage_sha256")
    if not isinstance(lineage_sha, str) or len(lineage_sha) != 64:
        raise SystemExit(f"pool bank {index} lacks lineage_sha256")
    if digest in seen_hashes:
        raise SystemExit(f"pool bank {index} duplicates another checkpoint")
    seen_hashes.add(digest)
    identity.append({"bank": index, "name": name,
                     "bytes": len(blob), "sha256": digest})
canonical = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
print(hashlib.sha256(canonical).hexdigest(), len(seeds),
      hashlib.sha256(manifest_raw).hexdigest())
PY
  )
  if [ "$POOL_HASH" != "$EXPECTED_POOL_HASH" ]; then
    echo "pool identity $POOL_HASH does not match expected $EXPECTED_POOL_HASH" >&2
    exit 1
  fi
fi

if ! /bin/bash "$ROOT/tools/install_puffer_env.sh" --check; then
  echo "installed Blood Bowl snapshot is stale; install and rebuild before launch" >&2
  exit 1
fi
SOURCE_HASH="$(cat ocean/bloodbowl/.content_hash)"
grep -q '^league_preseed' config/bloodbowl.ini || {
  echo "installed config lacks league_preseed" >&2; exit 1; }
grep -Fq 'Patch copy: training/selfplay_league.patch' \
  "$ROOT/vendor/PufferLib/pufferlib/selfplay.py" || {
  echo "vendored selfplay.py lacks the selfplay league patch marker" >&2; exit 1; }
git -C "$ROOT/vendor/PufferLib" apply --reverse --check --no-index \
  "$ROOT/training/selfplay_league.patch" || {
  echo "vendored selfplay.py lacks the complete training/selfplay_league.patch" >&2; exit 1; }
grep -q 'Warm-started training from' pufferlib/pufferl.py || {
  echo "vendored pufferl.py lacks the warm-start patch" >&2; exit 1; }
grep -q 'if i == 160:' pufferlib/pufferl.py || {
  echo "vendored pufferl.py lacks the full Blood Bowl dashboard patch" >&2; exit 1; }
grep -q 'PUFFER_ENV_JSON' pufferlib/pufferl.py || {
  echo "vendored pufferl.py lacks machine-readable environment logging" >&2; exit 1; }
grep -q "'_puffer_final_reprint'" pufferlib/pufferl.py || {
  echo "vendored pufferl.py lacks phase/cumulative/reprint metadata" >&2; exit 1; }
grep -q "'_puffer_schema': 2" pufferlib/pufferl.py || {
  echo "vendored pufferl.py lacks explicit loop-phase/panel metadata" >&2; exit 1; }

probe="$($PYBIN - "$ROOT" <<'PY'
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(sys.argv[1]).resolve() / "tools"))
from puffer_cuda_runtime import (
    begin_cuda_runtime_preflight,
    finish_cuda_runtime_preflight,
    validate_cuda_runtime_evidence,
)
runtime, evidence = begin_cuda_runtime_preflight()
from pufferlib import _C
evidence = finish_cuda_runtime_preflight(runtime, evidence)
validate_cuda_runtime_evidence(evidence)
print(getattr(_C, "env_name", None), int(bool(getattr(_C, "gpu", False))),
      int(_C.precision_bytes),
      getattr(_C, "exact_action_source_hash", "<missing>"),
      getattr(_C, "environment_source_hash", "<missing>"),
      getattr(_C, "observation_abi", "<missing>"),
      getattr(_C, "observation_version", "<missing>"),
      getattr(_C, "action_abi", "<missing>"),
      pathlib.Path(_C.__file__).resolve(),
      evidence["library"]["resolved_path"],
      evidence["library"]["sha256"],
      evidence["after_extension_import"]["device_count"])
PY
)"
read -r cenv cgpu precision COMPILED_EXACT_ACTION_SOURCE_HASH \
  COMPILED_ENVIRONMENT_SOURCE_HASH COMPILED_OBSERVATION_ABI \
  COMPILED_OBSERVATION_VERSION COMPILED_ACTION_ABI MODULE_PATH \
  CUDA_RUNTIME_LIBRARY_PATH CUDA_RUNTIME_LIBRARY_SHA256 \
  CUDA_RUNTIME_DEVICE_COUNT <<< "$probe"
if [ "$cenv" != "bloodbowl" ] || [ "$cgpu" != "1" ]; then
  echo "invalid native build: env=$cenv gpu=$cgpu" >&2; exit 1
fi
if [[ ! "$COMPILED_EXACT_ACTION_SOURCE_HASH" =~ ^[0-9a-f]{64}$ ]] || \
   [ "$COMPILED_ENVIRONMENT_SOURCE_HASH" != "$SOURCE_HASH" ] || \
   [ "$COMPILED_OBSERVATION_ABI" != "obs-v5" ] || \
   [ "$COMPILED_OBSERVATION_VERSION" != "5" ] || \
   [ "$COMPILED_ACTION_ABI" != "exact-joint-v1" ]; then
  echo "compiled native module does not satisfy the obs-v5/exact-action contract" >&2
  echo "  exact-action source: ${COMPILED_EXACT_ACTION_SOURCE_HASH:-<missing>}" >&2
  echo "  environment source: ${COMPILED_ENVIRONMENT_SOURCE_HASH:-<missing>} (expected $SOURCE_HASH)" >&2
  echo "  observation: ${COMPILED_OBSERVATION_ABI:-<missing>} / ${COMPILED_OBSERVATION_VERSION:-<missing>}" >&2
  echo "  action: ${COMPILED_ACTION_ABI:-<missing>}" >&2
  exit 1
fi
if [ "${RIG_ALLOW_FLOAT:-0}" = "1" ] && [ "$precision" != "4" ]; then
  echo "RIG_ALLOW_FLOAT=1 requires the Turing fp32 build (precision_bytes=4); got $precision" >&2
  echo "rebuild with: cd $ROOT/vendor/PufferLib && ./build.sh bloodbowl --float" >&2
  exit 1
fi
if [ "$precision" = "4" ] && [ "${RIG_ALLOW_FLOAT:-0}" != "1" ]; then
  echo "native fp32 build requires RIG_ALLOW_FLOAT=1 on the Turing rig" >&2; exit 1
fi
if [ "$precision" != "2" ] && [ "$precision" != "4" ]; then
  echo "unsupported native precision_bytes=$precision" >&2; exit 1
fi

. "$ROOT/tools/cpu_cap.sh"
NUM_THREADS="${NUM_THREADS:-${OMP_NUM_THREADS:-8}}"

[ -z "$WARM" ] || WARM_HASH="$(sha256sum "$WARM" | awk '{print $1}')"
CONFIG_HASH="$(sha256sum config/bloodbowl.ini | awk '{print $1}')"
DEFAULT_CONFIG_HASH="$(sha256sum config/default.ini | awk '{print $1}')"
CONFIG_TREE_HASH="$("$PYBIN" - config <<'PY'
import hashlib, pathlib, sys

root = pathlib.Path(sys.argv[1])
digest = hashlib.sha256()
for child in sorted(root.rglob("*")):
    if child.is_symlink() or (not child.is_dir() and not child.is_file()):
        raise SystemExit(f"unsupported config-tree entry: {child}")
    if child.is_dir():
        continue
    relative = child.relative_to(root).as_posix()
    size = child.stat().st_size
    file_sha = hashlib.sha256(child.read_bytes()).hexdigest()
    digest.update(relative.encode("utf-8"))
    digest.update(b"\0")
    digest.update(str(size).encode("ascii"))
    digest.update(b"\0")
    digest.update(file_sha.encode("ascii"))
    digest.update(b"\n")
print(digest.hexdigest())
PY
)"
[ -f "$MODULE_PATH" ] || { echo "imported pufferlib module missing: $MODULE_PATH" >&2; exit 1; }
MODULE_HASH="$(sha256sum "$MODULE_PATH" | awk '{print $1}')"
LAUNCHER_HASH="$(sha256sum "$ROOT/tools/run_reward_ablation.sh" | awk '{print $1}')"
CUDA_RUNTIME_WRAPPER_HASH="$(sha256sum "$CUDA_RUNTIME_WRAPPER" | awk '{print $1}')"
STATUS_WRAPPER="$ROOT/tools/trainer_status_wrapper.sh"
STATUS_WRAPPER_HASH="$(sha256sum "$STATUS_WRAPPER" | awk '{print $1}')"
LIVE_GUARD="$ROOT/tools/live_integrity_guard.py"
LIVE_GUARD_HASH="$(sha256sum "$LIVE_GUARD" | awk '{print $1}')"
CHECKPOINT_LINEAGE_HASH="$(sha256sum "$ROOT/tools/checkpoint_lineage.py" | awk '{print $1}')"
PATCH_HASH="$({
  sha256sum "$ROOT/training/pufferl_env_dashboard_limit.patch"
  sha256sum "$ROOT/training/pufferl_env_json.patch"
  sha256sum "$ROOT/training/pufferl_env_json_metadata_upgrade.patch"
  sha256sum "$ROOT/training/pufferl_env_phase_contract.patch"
  sha256sum "$ROOT/training/pufferl_eval_episode_gate.patch"
  sha256sum "$ROOT/training/pufferl_metrics_keyerror.patch"
  sha256sum "$ROOT/training/torch_pufferl_trusted_load.patch"
  sha256sum "$ROOT/training/selfplay_league.patch"
  sha256sum "$ROOT/training/puffer_exact_joint_actions.patch"
  sha256sum "$ROOT/training/puffer_recurrent_eval_state.patch"
  sha256sum "$ROOT/training/puffer_frozen_prio_mask.patch"
  sha256sum "$ROOT/training/puffer_recurrent_cuda_qualification.patch"
} | sha256sum | awk '{print $1}')"
if [ -n "$EXPECTED_PUFFER_PATCH_BUNDLE_SHA256" ] && \
   [ "$PATCH_HASH" != "$EXPECTED_PUFFER_PATCH_BUNDLE_SHA256" ]; then
  echo "Puffer patch bundle drifted from the frozen screen contract: " \
       "$PATCH_HASH != $EXPECTED_PUFFER_PATCH_BUNDLE_SHA256" >&2
  exit 1
fi
VENDOR_HEAD="$(git rev-parse HEAD 2>/dev/null || printf '%s' '<not-a-git-checkout>')"
VENDOR_SOURCE_HASH="$({
  sha256sum pufferlib/__init__.py pufferlib/pufferl.py \
    pufferlib/selfplay.py pufferlib/torch_pufferl.py pufferlib/models.py \
    pufferlib/muon.py src/pufferlib.cu src/bindings.cu \
    src/bindings_cpu.cpp src/kernels.cu src/vecenv.h
} | sha256sum | awk '{print $1}')"

if [ "$BOOTSTRAP_MODE" = "lineage-v5" ]; then
  read -r WARM_LINEAGE_HASH POOL_LINEAGE_BUNDLE_HASH < <(
    "$PYBIN" - "$ROOT" "$WARM" "$POOL" "$SOURCE_HASH" \
      "$MODULE_HASH" "$PATCH_HASH" <<'PY'
import hashlib, json, pathlib, sys
root, warm_path, pool_path, source_sha, module_sha, patch_sha = sys.argv[1:]
sys.path.insert(0, str(pathlib.Path(root) / "tools"))
from checkpoint_lineage import lineage_digest, sidecar_path, validate_lineage

expected = {
    "source_sha256": source_sha,
    "compiled_module_sha256": module_sha,
    "puffer_patch_bundle_sha256": patch_sha,
}
warm = pathlib.Path(warm_path)
warm_payload = validate_lineage(
    warm, sidecar_path(warm), expected=expected, require_eligible=True)
pool = pathlib.Path(pool_path)
manifest = json.loads((pool / "league_seeds.json").read_text(encoding="utf-8"))
identities = []
for index, seed in enumerate(manifest["seeds"]):
    checkpoint = pool / seed["file"]
    lineage = pool / seed["lineage_file"]
    payload = validate_lineage(
        checkpoint, lineage, expected=expected, require_eligible=True)
    payload_sha = lineage_digest(payload)
    if payload_sha != seed["lineage_sha256"]:
        raise SystemExit(f"pool bank {index} lineage digest differs from manifest")
    identities.append({
        "bank": index,
        "checkpoint_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "lineage_sha256": payload_sha,
    })
bundle = hashlib.sha256(json.dumps(
    identities, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
print(lineage_digest(warm_payload), bundle)
PY
  )
fi

echo "tag=$TAG seed=$SEED requested_steps=$STEPS final_steps=$FINAL_STEPS rollout_quantum=$ROLLOUT_QUANTUM"
echo "bootstrap=$BOOTSTRAP_MODE observation_abi=obs-v5 observation_version=5 action_abi=exact-joint-v1 qualification_only=$QUALIFICATION_ONLY"
echo "reward=$REWARD_NAME reward_sha256=$REWARD_HASH"
echo "pool=$POOL pool_identity_sha256=$POOL_HASH pool_manifest_sha256=$POOL_MANIFEST_HASH banks=$POOL_BANKS pct=$FROZEN_BANK_PCT rows_per_bank=$FROZEN_PER_BANK historical_game_share=$HISTORICAL_GAME_SHARE"
echo "warm=$WARM warm_sha256=$WARM_HASH"
echo "source_sha256=$SOURCE_HASH config_sha256=$CONFIG_HASH module_sha256=$MODULE_HASH"
echo "compiled_exact_action_source_sha256=$COMPILED_EXACT_ACTION_SOURCE_HASH compiled_observation=$COMPILED_OBSERVATION_ABI/$COMPILED_OBSERVATION_VERSION compiled_action=$COMPILED_ACTION_ABI"
echo "native_precision_bytes=$precision total_agents=$TOTAL_AGENTS buffers=$NUM_BUFFERS threads=$NUM_THREADS horizon=$HORIZON minibatch=$MINIBATCH_SIZE"
echo "lr=$LR ent_coef=$ENT_COEF gamma=$GAMMA gae_lambda=$GAE_LAMBDA replay_ratio=$REPLAY_RATIO log=$LOG"

CMD=(env PUFFER_CUDA_RUNTIME_MANIFEST="$RUN_MANIFEST" \
  PUFFER_CUDA_RUNTIME_EVIDENCE="$CUDA_RUNTIME_EVIDENCE" \
  "$PYBIN" "$CUDA_RUNTIME_WRAPPER" train bloodbowl --tag "$TAG" \
  --seed "$SEED" --train.seed "$SEED" --selfplay.seed "$SEED" --env.seed "$SEED" \
  --train.gpus 1 --eval-episodes 10000 \
  --checkpoint-interval "$CHECKPOINT_INTERVAL" \
  --policy.hidden-size 512 --policy.num-layers 3 --policy.expansion-factor 1 \
  --vec.total-agents "$TOTAL_AGENTS" --vec.num-buffers "$NUM_BUFFERS" \
  --vec.num-threads "$NUM_THREADS" \
  "${REWARD_ARGS[@]}" \
  --env.demo-reset-pct 0 --env.demo-endzone-maxdist 0 \
  --env.demo-pickup-maxdist 0 --env.demo-postkick-maxturn 0 \
  --env.demo-pass-maxrange 0 \
  --train.total-timesteps "$STEPS" --train.learning-rate "$LR" \
  --train.ent-coef "$ENT_COEF" --train.gamma "$GAMMA" \
  --train.gae-lambda "$GAE_LAMBDA" --train.horizon "$HORIZON" \
  --train.minibatch-size "$MINIBATCH_SIZE" \
  --train.anneal-lr 1 --train.min-lr-ratio 0.1 \
  --train.replay-ratio "$REPLAY_RATIO" --train.clip-coef "$CLIP_COEF" \
  --train.vf-coef "$VF_COEF" --train.vf-clip-coef "$VF_CLIP_COEF" \
  --train.max-grad-norm "$MAX_GRAD_NORM" \
  --train.anneal-ent-coef 1 --train.min-ent-coef-ratio 0.1 \
  --train.update-epochs 1 --train.beta1 0.95 --train.beta2 0.999 \
  --train.eps 0.000000000001)

if [ "$BOOTSTRAP_MODE" != "lineage-v5" ]; then
  CMD+=(--selfplay.enabled 0 --vec.num-frozen-banks 0 \
    --vec.frozen-bank-pct 0)
else
  CMD+=(--selfplay.enabled 1 --selfplay.league-preseed "$POOL" \
    --selfplay.swap-winrate 1.1 --selfplay.opp-timeout-steps "$OPP_TIMEOUT" \
    --selfplay.snapshot-interval 1000000000000 \
    --vec.num-frozen-banks 4 --vec.frozen-bank-pct "$FROZEN_BANK_PCT" \
    --load-model-path "$WARM")
fi

if [ "${DRY_RUN:-0}" = "1" ]; then
  printf 'DRY-RUN command:'
  printf ' %q' "${CMD[@]}"
  printf '\n'
  exit 0
fi

META_ARGS=(
  tag "$TAG" seed "$SEED" requested_steps "$STEPS" final_steps "$FINAL_STEPS"
  bootstrap_mode "$BOOTSTRAP_MODE" initialization \
  "$([ "$QUALIFICATION_ONLY" = "1" ] && printf fresh || printf lineage-v5)" \
  qualification_only "$QUALIFICATION_ONLY" observation_abi obs-v5 \
  observation_version 5 action_abi exact-joint-v1 \
  policy_hidden_size 512 policy_num_layers 3 policy_expansion_factor 1 \
  rollout_quantum "$ROLLOUT_QUANTUM" reward_name "$REWARD_NAME"
  reward_sha256 "$REWARD_HASH" reward_manifest "$REWARD_MANIFEST"
  pool "$POOL" pool_identity_sha256 "$POOL_HASH"
  pool_manifest_sha256 "$POOL_MANIFEST_HASH"
  pool_lineage_bundle_sha256 "$POOL_LINEAGE_BUNDLE_HASH"
  historical_game_share "$HISTORICAL_GAME_SHARE"
  frozen_bank_pct "$FROZEN_BANK_PCT" num_frozen_banks "$NUM_FROZEN_BANKS"
  expected_pool_hash "$EXPECTED_POOL_HASH"
  warm "$WARM" warm_sha256 "$WARM_HASH" warm_bytes "$warm_size" \
  warm_lineage_sha256 "$WARM_LINEAGE_HASH"
  source_sha256 "$SOURCE_HASH" config_sha256 "$CONFIG_HASH"
  compiled_exact_action_source_sha256 "$COMPILED_EXACT_ACTION_SOURCE_HASH"
  compiled_environment_source_sha256 "$COMPILED_ENVIRONMENT_SOURCE_HASH"
  compiled_observation_abi "$COMPILED_OBSERVATION_ABI"
  compiled_observation_version "$COMPILED_OBSERVATION_VERSION"
  compiled_action_abi "$COMPILED_ACTION_ABI"
  config_tree_sha256 "$CONFIG_TREE_HASH"
  default_config_sha256 "$DEFAULT_CONFIG_HASH"
  compiled_module "$MODULE_PATH" compiled_module_sha256 "$MODULE_HASH"
  launcher_sha256 "$LAUNCHER_HASH" puffer_patch_bundle_sha256 "$PATCH_HASH"
  cuda_runtime_wrapper_sha256 "$CUDA_RUNTIME_WRAPPER_HASH"
  cuda_runtime_evidence_status pending
  cuda_runtime_evidence_path "$CUDA_RUNTIME_EVIDENCE"
  cuda_launcher_probe_library_path "$CUDA_RUNTIME_LIBRARY_PATH"
  cuda_launcher_probe_library_sha256 "$CUDA_RUNTIME_LIBRARY_SHA256"
  cuda_launcher_probe_device_count "$CUDA_RUNTIME_DEVICE_COUNT"
  cuda_launcher_probe_visible_devices "$CUDA_VISIBLE_DEVICES"
  status_wrapper_sha256 "$STATUS_WRAPPER_HASH"
  live_integrity_guard_sha256 "$LIVE_GUARD_HASH"
  checkpoint_lineage_sha256 "$CHECKPOINT_LINEAGE_HASH"
  live_integrity_max_silence "$LIVE_INTEGRITY_MAX_SILENCE"
  live_integrity_poll_seconds "$LIVE_INTEGRITY_POLL_SECONDS"
  vendor_head "$VENDOR_HEAD" vendor_source_sha256 "$VENDOR_SOURCE_HASH"
  native_precision_bytes "$precision" total_agents "$TOTAL_AGENTS"
  num_buffers "$NUM_BUFFERS" num_threads "$NUM_THREADS" horizon "$HORIZON"
  minibatch_size "$MINIBATCH_SIZE" checkpoint_interval "$CHECKPOINT_INTERVAL"
  checkpoint_steps "$CHECKPOINT_STEPS" learning_rate "$LR"
  ent_coef "$ENT_COEF" gamma "$GAMMA" gae_lambda "$GAE_LAMBDA"
  replay_ratio "$REPLAY_RATIO" clip_coef "$CLIP_COEF" vf_coef "$VF_COEF"
  vf_clip_coef "$VF_CLIP_COEF" max_grad_norm "$MAX_GRAD_NORM"
  expected_checkpoint_bytes "$EXPECT_BYTES"
  screen_manifest_sha256 "$SCREEN_MANIFEST_SHA256"
)
"$PYBIN" - "$RUN_MANIFEST" "${META_ARGS[@]}" -- "${CMD[@]}" <<'PY'
import json, pathlib, sys
path = pathlib.Path(sys.argv[1])
split = sys.argv.index("--", 2)
pairs = sys.argv[2:split]
if len(pairs) % 2:
    raise SystemExit("invalid run-manifest metadata pairs")
manifest = dict(zip(pairs[::2], pairs[1::2]))
manifest.update({
    "schema_version": 1,
    "mode": ("native_fresh_v5_qualification"
             if manifest["bootstrap_mode"] == "fresh-v5-qualification"
             else "native_fresh_v5_genesis"
             if manifest["bootstrap_mode"] == "fresh-v5-genesis"
             else "native_static_pool_reward_ablation"),
    "command": sys.argv[split + 1:],
})
path.write_text(json.dumps(
    manifest, indent=2, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8")
PY
"$PYBIN" - "$RUN_MANIFEST" <<'PY' > "$LOG"
import json, pathlib, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print("BB_RUN_MANIFEST_PENDING " + json.dumps(
    manifest, sort_keys=True, separators=(",", ":"), allow_nan=False))
PY

BEFORE_RUNS=$(mktemp)
find checkpoints/bloodbowl -mindepth 1 -maxdepth 1 -type d \
  -exec basename {} \; 2>/dev/null | sort > "$BEFORE_RUNS" || true
WRAPPER=(/bin/bash "$STATUS_WRAPPER" "$STATUS_FILE" "$LOG" "${CMD[@]}")
WATCHDOG_ENV=()
if [ -n "$SCREEN_MANIFEST_SHA256" ]; then
  WATCHDOG_ENV=(env \
    LIVE_INTEGRITY_GUARD="$LIVE_GUARD" \
    LIVE_INTEGRITY_PYTHON="$PYBIN" \
    LIVE_INTEGRITY_STATE="${LOG}.live-integrity-watchdog-state.json" \
    LIVE_INTEGRITY_FAILURE="$LIVE_INTEGRITY_FAILURE" \
    LIVE_INTEGRITY_MAX_SILENCE="$LIVE_INTEGRITY_MAX_SILENCE" \
    LIVE_INTEGRITY_POLL_SECONDS="$LIVE_INTEGRITY_POLL_SECONDS" \
    LIVE_INTEGRITY_MARKER="$GUARD_MARKER")
fi
if [ "$DETACH" = "1" ]; then
  setsid nohup "${WATCHDOG_ENV[@]}" "${WRAPPER[@]}" \
    > /dev/null 2>&1 < /dev/null &
else
  # Vacation queues supervise one process group. Keep the trainer in the
  # queue runner's group so runtime/thermal termination cannot strand the
  # otherwise-detached arm; systemd KillMode=control-group remains a backstop.
  "${WATCHDOG_ENV[@]}" "${WRAPPER[@]}" \
    > /dev/null 2>&1 < /dev/null &
fi
PID=$!
PROCESS_GROUP="$(ps -o pgid= -p "$PID" | tr -d ' ')"
[ -n "$PROCESS_GROUP" ] || PROCESS_GROUP=$PID
PROCESS_TMP="${PROCESS_FILE}.tmp.$$"
printf '{"pid":%d,"process_group":%d,"started_utc":"%s"}\n' \
  "$PID" "$PROCESS_GROUP" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$PROCESS_TMP"
mv "$PROCESS_TMP" "$PROCESS_FILE"
echo "LAUNCHED pid=$PID"

# Mark the exact newly created run directory without relying on mtime or a
# globally "newest" directory. One-trainer-per-host is already enforced, but
# inherited checkpoint trees can contain many old unmarked directories.
(
  for _ in $(seq 1 60); do
    sleep 2
    for directory in checkpoints/bloodbowl/*/; do
      [ -d "$directory" ] || continue
      base=$(basename "$directory")
      grep -Fxq "$base" "$BEFORE_RUNS" && continue
      if ! "$PYBIN" - "$RUN_MANIFEST" "$CUDA_RUNTIME_EVIDENCE" <<'PY'
import hashlib, json, pathlib, sys
manifest_path = pathlib.Path(sys.argv[1])
evidence_path = pathlib.Path(sys.argv[2])
if not evidence_path.is_file():
    raise SystemExit(1)
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if (
    manifest.get("cuda_runtime_evidence_status") != "accepted"
    or manifest.get("cuda_runtime_evidence_path") != str(evidence_path)
    or manifest.get("cuda_runtime_evidence_sha256")
    != hashlib.sha256(evidence_path.read_bytes()).hexdigest()
    or not isinstance(manifest.get("cuda_runtime_evidence"), dict)
):
    raise SystemExit(1)
PY
      then
        continue
      fi
      {
        echo "reward-ablation tag=$TAG"
        echo "reward=$REWARD_NAME sha256=$REWARD_HASH"
        echo "bootstrap=$BOOTSTRAP_MODE qualification_only=$QUALIFICATION_ONLY obs=obs-v5 action=exact-joint-v1"
        echo "pool=$POOL identity_sha256=$POOL_HASH manifest_sha256=$POOL_MANIFEST_HASH lineage_bundle_sha256=$POOL_LINEAGE_BUNDLE_HASH pct=$FROZEN_BANK_PCT"
        echo "warm=$WARM sha256=$WARM_HASH lineage_sha256=$WARM_LINEAGE_HASH seed=$SEED requested_steps=$STEPS final_steps=$FINAL_STEPS"
        echo "run_manifest_sha256=$(sha256sum "$RUN_MANIFEST" | awk '{print $1}')"
      } > "${directory}PROFILE"
      cp "$RUN_MANIFEST" "${directory}RUN_MANIFEST.json"
      cp "$CUDA_RUNTIME_EVIDENCE" "${directory}CUDA_RUNTIME_EVIDENCE.json"
      run_dir="$(pwd)/${directory%/}"
      tmp="${RUN_DIR_FILE}.tmp.$$"
      printf '%s\n' "$run_dir" > "$tmp"
      mv "$tmp" "$RUN_DIR_FILE"
      rm -f "$BEFORE_RUNS"
      exit 0
    done
  done
  rm -f "$BEFORE_RUNS"
  echo "warning: could not identify the new checkpoint directory for $TAG" >&2
) &
MARKER_PID=$!

terminate_group() {
  kill -TERM -- "-$PROCESS_GROUP" 2>/dev/null || true
  for _ in $(seq 1 20); do
    kill -0 "$PID" 2>/dev/null || break
    sleep 0.25
  done
  kill -KILL -- "-$PROCESS_GROUP" 2>/dev/null || true
  wait "$PID" 2>/dev/null || true
}

for _ in $(seq 1 40); do
  sleep 1
  if grep -aq 'pufferl_load_frozen_bank' "$LOG"; then
    grep -a 'pufferl_load_frozen_bank' "$LOG" >&2 || true
    echo "frozen bank load failed; terminating process group $PID" >&2
    terminate_group
    kill "$MARKER_PID" 2>/dev/null || true
    exit 1
  fi
  [ -f "$STATUS_FILE" ] && break
  kill -0 "$PID" 2>/dev/null || { sleep 1; break; }
done

if [ -f "$STATUS_FILE" ]; then
  EXIT_CODE="$($PYBIN - "$STATUS_FILE" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1], encoding="utf-8"))["exit_code"]))
PY
)"
  wait "$PID" 2>/dev/null || true
  if [ "$EXIT_CODE" -ne 0 ]; then
    kill "$MARKER_PID" 2>/dev/null || true
    echo "trainer exited early with status $EXIT_CODE; tail of $LOG:" >&2
    tail -30 "$LOG" >&2
    exit 1
  fi
  for _ in $(seq 1 10); do
    [ -f "$RUN_DIR_FILE" ] && break
    sleep 1
  done
  if [ ! -f "$RUN_DIR_FILE" ]; then
    kill "$MARKER_PID" 2>/dev/null || true
    echo "trainer exited 0 but its checkpoint directory was not identified" >&2
    exit 1
  fi
  RUN_DIR="$(cat "$RUN_DIR_FILE")"
  FINAL_CHECKPOINT="$RUN_DIR/$(printf '%016d.bin' "$FINAL_STEPS")"
  if [ ! -f "$FINAL_CHECKPOINT" ]; then
    kill "$MARKER_PID" 2>/dev/null || true
    echo "trainer exited 0 without expected final checkpoint: $FINAL_CHECKPOINT" >&2
    exit 1
  fi
  echo "COMPLETE pid=$PID final_checkpoint=$FINAL_CHECKPOINT log=$LOG"
  exit 0
fi

if ! kill -0 "$PID" 2>/dev/null; then
  kill "$MARKER_PID" 2>/dev/null || true
  echo "trainer died without an atomic status sidecar; tail of $LOG:" >&2
  tail -30 "$LOG" >&2
  exit 1
fi
grep -a 'Warm-started' "$LOG" | head -2 || {
  echo "warning: no warm-start confirmation in first 40 seconds" >&2; }
echo "LIVE pid=$PID log=$LOG"
