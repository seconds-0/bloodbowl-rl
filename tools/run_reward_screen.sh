#!/usr/bin/env bash
# Run a paired native reward screen sequentially on one owned GPU.
# Seed 43 reverses seed 42's arm order to reduce time/order confounding.
# The screen plan, every completed arm, and final completion summary are
# content-addressed. A restarted orchestrator can recover a cleanly completed
# detached arm, but code/config/artifact drift fails closed.
# Example (current possession/gain screen):
#   WARM=/abs/warm.bin POOL=/abs/pool STEPS=500000000 \
#     SCREEN_PROFILE=possession-gain PREFIX=possession-gain-v2 \
#     bash tools/run_reward_screen.sh
# Example (longer two-arm confirmation after transfer selects a candidate):
#   WARM=/abs/warm.bin POOL=/abs/pool STEPS=1000000000 \
#     SCREEN_PROFILE=paired-confirmation CANDIDATE_ARM=gain_only \
#     TRANSFER_COMPLETE=/abs/TRANSFER_COMPLETE.json \
#     EXPECTED_TRANSFER_SHA256=<sha256> \
#     PREFIX=gain-confirm-v1 bash tools/run_reward_screen.sh
set -euo pipefail

if [ $# -ne 0 ]; then
  echo "run_reward_screen.sh accepts configuration through named environment variables only" >&2
  exit 1
fi

LAUNCH_CWD="$PWD"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${WARM:?WARM is required}"
: "${POOL:?POOL is required}"
: "${STEPS:?STEPS is required (explicit experiment budget)}"
: "${SCREEN_PROFILE:?SCREEN_PROFILE is required (distance-possession, possession-gain, or paired-confirmation)}"
CANDIDATE_ARM="${CANDIDATE_ARM:-}"
TRANSFER_COMPLETE="${TRANSFER_COMPLETE:-}"
EXPECTED_TRANSFER_SHA256="${EXPECTED_TRANSFER_SHA256:-}"
PREFIX="${PREFIX:-reward-screen-v1}"
OUT_DIR="${OUT_DIR:-$ROOT/runs/reward-screens/$PREFIX}"
POLL_SECONDS="${POLL_SECONDS:-30}"
PLAN_ONLY="${PLAN_ONLY:-0}"

# Fixed Stage-1 causal contract. Assign, rather than inherit, every optional
# launcher input which could alter optimization, batching, or pool allocation.
TOTAL_AGENTS=2048
NUM_BUFFERS=2
NUM_THREADS=16
FROZEN_BANK_PCT=0.06
EXPECT_BYTES=16066560
LR=0.00028
ENT_COEF=0.009
GAMMA=0.995
GAE_LAMBDA=0.85
HORIZON=64
MINIBATCH_SIZE=16384
CHECKPOINT_STEPS=50000000
REPLAY_RATIO=0.25
CLIP_COEF=0.2
VF_COEF=1.0
VF_CLIP_COEF=0.5
MAX_GRAD_NORM=1.5
EXPECTED_POOL_HASH=18ec7cac858b71a6657003f454f19e232fb060f08b644c1e9e2f101076a9aac0
MIN_TRAIN_GAMES=1
MIN_EVAL_GAMES=10001

case "$STEPS:$POLL_SECONDS" in
  *[!0-9:]*) echo "STEPS and POLL_SECONDS must be positive integers" >&2; exit 1 ;;
esac
if [ "$STEPS" -le 0 ] || [ "$POLL_SECONDS" -le 0 ] || \
   [ "$POLL_SECONDS" -gt 60 ]; then
  echo "STEPS must be positive; POLL_SECONDS must be in 1..60" >&2
  exit 1
fi
case "$PREFIX" in
  ''|*[!a-zA-Z0-9._-]*)
    echo "PREFIX must use only letters, digits, dot, underscore, or hyphen" >&2
    exit 1 ;;
esac
case "$PLAN_ONLY" in
  0|1) ;;
  *) echo "PLAN_ONLY must be 0 or 1" >&2; exit 1 ;;
esac
case "$SCREEN_PROFILE" in
  distance-possession|possession-gain)
    [ -z "$CANDIDATE_ARM$TRANSFER_COMPLETE$EXPECTED_TRANSFER_SHA256" ] || {
      echo "candidate transfer inputs are only valid with paired-confirmation" >&2
      exit 1; }
    ;;
  paired-confirmation)
    case "$CANDIDATE_ARM" in
      possession_only|gain_only|neither) ;;
      *) echo "paired-confirmation requires CANDIDATE_ARM=possession_only, gain_only, or neither" >&2
         exit 1 ;;
    esac
    [ -n "$TRANSFER_COMPLETE" ] || {
      echo "paired-confirmation requires TRANSFER_COMPLETE" >&2; exit 1; }
    if ! [[ "$EXPECTED_TRANSFER_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
      echo "paired-confirmation requires a lowercase 64-character EXPECTED_TRANSFER_SHA256" >&2
      exit 1
    fi
    ;;
  *) echo "SCREEN_PROFILE must be distance-possession, possession-gain, or paired-confirmation" >&2
     exit 1 ;;
esac

abspath() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "$LAUNCH_CWD/$1" ;;
  esac
}
WARM="$(abspath "$WARM")"
POOL="$(abspath "$POOL")"
OUT_DIR="$(abspath "$OUT_DIR")"
if [ -n "$TRANSFER_COMPLETE" ]; then
  TRANSFER_COMPLETE="$(abspath "$TRANSFER_COMPLETE")"
  [ -f "$TRANSFER_COMPLETE" ] || {
    echo "missing transfer completion: $TRANSFER_COMPLETE" >&2; exit 1; }
fi
[ -f "$WARM" ] || { echo "missing warm checkpoint: $WARM" >&2; exit 1; }
[ -d "$POOL" ] || { echo "missing static pool: $POOL" >&2; exit 1; }
mkdir -p "$OUT_DIR"

command -v flock >/dev/null 2>&1 || {
  echo "flock is required for the one-screen contract" >&2; exit 1; }
exec 8>"$OUT_DIR/.screen.lock"
if ! flock -n 8; then
  echo "another orchestrator or its detached trainer holds $OUT_DIR/.screen.lock" >&2
  exit 1
fi

PYBIN="$ROOT/vendor/PufferLib/.venv/bin/python"
[ -x "$PYBIN" ] || { echo "vendored Python missing: $PYBIN" >&2; exit 1; }
bash "$ROOT/tools/install_puffer_env.sh" --check "$ROOT/vendor/PufferLib"

case "$SCREEN_PROFILE" in
  distance-possession)
    arms=(r0 r3 r1 r2 r2 r1 r3 r0)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  possession-gain)
    arms=(both neither possession_only gain_only \
          gain_only possession_only neither both)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  paired-confirmation)
    arms=(both "$CANDIDATE_ARM" "$CANDIDATE_ARM" both)
    seeds=(42 42 43 43)
    ;;
esac
TOTAL_ARMS=${#arms[@]}
SCREEN_MANIFEST="$OUT_DIR/SCREEN_MANIFEST.json"
SCREEN_STATUS="$OUT_DIR/SCREEN_STATUS.json"
SCREEN_COMPLETE="$OUT_DIR/SCREEN_COMPLETE.json"

manifest_for() {
  case "$1" in
    r0) printf '%s\n' "$ROOT/puffer/config/rewards/r0_full.json" ;;
    r1) printf '%s\n' "$ROOT/puffer/config/rewards/r1_no_distance.json" ;;
    r2) printf '%s\n' "$ROOT/puffer/config/rewards/r2_no_possession.json" ;;
    r3) printf '%s\n' "$ROOT/puffer/config/rewards/r3_minimal_block.json" ;;
    both) printf '%s\n' "$ROOT/puffer/config/rewards/r0_full.json" ;;
    possession_only) printf '%s\n' "$ROOT/puffer/config/rewards/p1_possession_only.json" ;;
    gain_only) printf '%s\n' "$ROOT/puffer/config/rewards/p2_gain_only.json" ;;
    neither) printf '%s\n' "$ROOT/puffer/config/rewards/r2_no_possession.json" ;;
    *) echo "unknown arm: $1" >&2; return 1 ;;
  esac
}

freeze_screen_manifest() {
  "$PYBIN" - "$SCREEN_MANIFEST" "$ROOT" "$PREFIX" "$STEPS" \
    "$OUT_DIR" "$WARM" "$POOL" "$TOTAL_AGENTS" "$NUM_BUFFERS" \
    "$NUM_THREADS" "$FROZEN_BANK_PCT" "$EXPECT_BYTES" "$LR" \
    "$ENT_COEF" "$GAMMA" "$GAE_LAMBDA" "$HORIZON" \
    "$MINIBATCH_SIZE" "$CHECKPOINT_STEPS" "$REPLAY_RATIO" \
    "$CLIP_COEF" "$VF_COEF" "$VF_CLIP_COEF" "$MAX_GRAD_NORM" \
    "$EXPECTED_POOL_HASH" "$MIN_TRAIN_GAMES" "$MIN_EVAL_GAMES" \
    "$SCREEN_PROFILE" "$CANDIDATE_ARM" "$TRANSFER_COMPLETE" \
    "$EXPECTED_TRANSFER_SHA256" <<'PY'
import datetime, hashlib, json, pathlib, subprocess, sys, sysconfig

(
    manifest_path, root_path, prefix, steps, out_dir, warm_path, pool_path,
    total_agents, num_buffers, num_threads, frozen_bank_pct, expect_bytes,
    learning_rate, ent_coef, gamma, gae_lambda, horizon, minibatch_size,
    checkpoint_steps, replay_ratio, clip_coef, vf_coef, vf_clip_coef,
    max_grad_norm, expected_pool_hash, min_train_games, min_eval_games,
    screen_profile, candidate_arm, transfer_complete_path,
    expected_transfer_sha,
) = sys.argv[1:]
root = pathlib.Path(root_path).resolve()
vendor = root / "vendor" / "PufferLib"
warm = pathlib.Path(warm_path).resolve()
pool = pathlib.Path(pool_path).resolve()
destination = pathlib.Path(manifest_path)

def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

def sha256sum_bundle(paths, labels):
    payload = b"".join(
        f"{sha(path)}  {label}\n".encode()
        for path, label in zip(paths, labels)
    )
    return hashlib.sha256(payload).hexdigest()

settings = {
    "total_agents": total_agents,
    "num_buffers": num_buffers,
    "num_threads": num_threads,
    "frozen_bank_pct": frozen_bank_pct,
    "expected_checkpoint_bytes": expect_bytes,
    "learning_rate": learning_rate,
    "ent_coef": ent_coef,
    "gamma": gamma,
    "gae_lambda": gae_lambda,
    "horizon": horizon,
    "minibatch_size": minibatch_size,
    "checkpoint_steps": checkpoint_steps,
    "replay_ratio": replay_ratio,
    "clip_coef": clip_coef,
    "vf_coef": vf_coef,
    "vf_clip_coef": vf_clip_coef,
    "max_grad_norm": max_grad_norm,
    "expected_pool_hash": expected_pool_hash,
    "min_train_games": min_train_games,
    "min_eval_games": min_eval_games,
    "eval_episodes": "10000",
    "native_precision_bytes": "4",
    "policy_hidden_size": "512",
    "policy_num_layers": "3",
    "policy_expansion_factor": "1",
}

expect_size = int(expect_bytes)
if warm.stat().st_size != expect_size:
    raise SystemExit(
        f"warm checkpoint is {warm.stat().st_size} bytes; expected {expect_size}")

pool_manifest_path = pool / "league_seeds.json"
pool_raw = pool_manifest_path.read_bytes()
pool_manifest = json.loads(pool_raw)
if pool_manifest.get("expected_bytes") != expect_size:
    raise SystemExit("pool expected_bytes does not match screen checkpoint size")
seeds = pool_manifest.get("seeds")
if not isinstance(seeds, list) or len(seeds) != 4:
    raise SystemExit("screen pool must contain exactly four banks")
bank_identity = []
for index, seed in enumerate(seeds):
    if seed.get("bank") != index:
        raise SystemExit(f"pool bank order mismatch at index {index}")
    path = pool / seed["file"]
    digest = sha(path)
    size = path.stat().st_size
    if size != expect_size or seed.get("bytes") != size or seed.get("sha256") != digest:
        raise SystemExit(f"pool bank contract mismatch: {path}")
    bank_identity.append({
        "bank": index, "name": seed.get("name"), "file": str(path),
        "bytes": size, "sha256": digest,
    })
identity_body = [
    {key: bank[key] for key in ("bank", "name", "bytes", "sha256")}
    for bank in bank_identity
]
pool_identity = hashlib.sha256(json.dumps(
    identity_body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
if pool_identity != expected_pool_hash:
    raise SystemExit(
        f"pool identity {pool_identity} does not match {expected_pool_hash}")

sys.path.insert(0, str(root / "tools"))
from reward_manifest import load_manifest
if screen_profile == "distance-possession":
    reward_files = {
        "r0": root / "puffer/config/rewards/r0_full.json",
        "r1": root / "puffer/config/rewards/r1_no_distance.json",
        "r2": root / "puffer/config/rewards/r2_no_possession.json",
        "r3": root / "puffer/config/rewards/r3_minimal_block.json",
    }
    arm_order = ("r0", "r3", "r1", "r2", "r2", "r1", "r3", "r0")
elif screen_profile == "possession-gain":
    reward_files = {
        "both": root / "puffer/config/rewards/r0_full.json",
        "possession_only": root / "puffer/config/rewards/p1_possession_only.json",
        "gain_only": root / "puffer/config/rewards/p2_gain_only.json",
        "neither": root / "puffer/config/rewards/r2_no_possession.json",
    }
    arm_order = (
        "both", "neither", "possession_only", "gain_only",
        "gain_only", "possession_only", "neither", "both",
    )
    schedule_seeds = (42, 42, 42, 42, 43, 43, 43, 43)
elif screen_profile == "paired-confirmation":
    allowed = {"possession_only", "gain_only", "neither"}
    if candidate_arm not in allowed:
        raise SystemExit("invalid paired-confirmation candidate")
    all_reward_files = {
        "both": root / "puffer/config/rewards/r0_full.json",
        "possession_only": root / "puffer/config/rewards/p1_possession_only.json",
        "gain_only": root / "puffer/config/rewards/p2_gain_only.json",
        "neither": root / "puffer/config/rewards/r2_no_possession.json",
    }
    reward_files = {
        arm: all_reward_files[arm] for arm in ("both", candidate_arm)
    }
    arm_order = ("both", candidate_arm, candidate_arm, "both")
    schedule_seeds = (42, 42, 43, 43)
else:
    raise SystemExit(f"unsupported screen profile: {screen_profile}")
if screen_profile == "distance-possession":
    schedule_seeds = (42, 42, 42, 42, 43, 43, 43, 43)
rewards = {}
for arm, path in reward_files.items():
    reward, digest = load_manifest(path)
    rewards[arm] = {
        "path": str(path.resolve()), "name": reward["name"],
        "reward_sha256": digest, "file_sha256": sha(path),
    }

extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
if not extension_suffix:
    raise SystemExit("Python did not report an extension-module suffix")
module = vendor / "pufferlib" / ("_C" + extension_suffix)
if not module.is_file():
    raise SystemExit(f"current-Python compiled _C module is missing: {module}")
config = vendor / "config/bloodbowl.ini"
source_hash_path = vendor / "ocean/bloodbowl/.content_hash"
if not source_hash_path.is_file():
    raise SystemExit("installed Blood Bowl content hash is missing")

patches = [
    root / "training/pufferl_env_dashboard_limit.patch",
    root / "training/pufferl_env_json.patch",
    root / "training/pufferl_env_json_metadata_upgrade.patch",
    root / "training/pufferl_env_phase_contract.patch",
    root / "training/pufferl_eval_episode_gate.patch",
    root / "training/pufferl_metrics_keyerror.patch",
    root / "training/torch_pufferl_trusted_load.patch",
]
vendor_sources = [
    "pufferlib/pufferl.py", "pufferlib/selfplay.py",
    "pufferlib/torch_pufferl.py", "src/pufferlib.cu", "src/bindings.cu",
    "src/vecenv.h",
]
vendor_paths = [vendor / relative for relative in vendor_sources]
patch_bundle_sha = sha256sum_bundle(patches, [str(path) for path in patches])
vendor_source_sha = sha256sum_bundle(vendor_paths, vendor_sources)
vendor_head_result = subprocess.run(
    ["git", "-C", str(vendor), "rev-parse", "HEAD"],
    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
vendor_head = (vendor_head_result.stdout.strip()
               if vendor_head_result.returncode == 0 else "<not-a-git-checkout>")

total = int(total_agents)
buffers = int(num_buffers)
rollout_quantum = total * int(horizon)
train_epochs = int(steps) // rollout_quantum
if train_epochs <= 0:
    raise SystemExit("screen STEPS is smaller than one rollout quantum")
final_steps = train_epochs * rollout_quantum
checkpoint_interval = (
    int(checkpoint_steps) + rollout_quantum // 2) // rollout_quantum
per_bank = int((total // buffers) * float(frozen_bank_pct))
historical_share = 4 * per_bank / ((total // buffers) / 2.0)

schedule = [
    {"index": index + 1, "arm": arm, "seed": seed}
    for index, (arm, seed) in enumerate(zip(
        arm_order, schedule_seeds))
]
launcher = root / "tools/run_reward_ablation.sh"
screen_script = root / "tools/run_reward_screen.sh"
contract = {
    "screen_profile": screen_profile,
    "prefix": prefix,
    "out_dir": str(pathlib.Path(out_dir).resolve()),
    "requested_steps": int(steps),
    "final_steps": final_steps,
    "rollout_quantum": rollout_quantum,
    "schedule": schedule,
    "settings": settings,
    "warm": {
        "path": str(warm), "bytes": warm.stat().st_size, "sha256": sha(warm),
    },
    "pool": {
        "path": str(pool),
        "manifest_sha256": hashlib.sha256(pool_raw).hexdigest(),
        "identity_sha256": pool_identity,
        "banks": bank_identity,
        "rows_per_bank": per_bank,
        "historical_game_share": str(historical_share),
    },
    "rewards": rewards,
    "implementation": {
        "screen_script_sha256": sha(screen_script),
        "launcher_sha256": sha(launcher),
        "source_sha256": source_hash_path.read_text().strip(),
        "config_sha256": sha(config),
        "compiled_module": str(module.resolve()),
        "compiled_module_bytes": module.stat().st_size,
        "compiled_module_sha256": sha(module),
        "puffer_patch_bundle_sha256": patch_bundle_sha,
        "vendor_head": vendor_head,
        "vendor_source_sha256": vendor_source_sha,
        "critical_vendor_files": {
            relative: sha(path)
            for relative, path in zip(vendor_sources, vendor_paths)
        },
        "patches": {str(path.resolve()): sha(path) for path in patches},
    },
    "derived": {
        "checkpoint_interval": str(max(checkpoint_interval, 1)),
        "historical_game_share": str(historical_share),
    },
}
if screen_profile == "paired-confirmation":
    contract["candidate_arm"] = candidate_arm
    transfer_complete = pathlib.Path(transfer_complete_path).resolve()
    if sha(transfer_complete) != expected_transfer_sha:
        raise SystemExit("transfer completion SHA-256 does not match expectation")
    transfer = json.loads(transfer_complete.read_text(encoding="utf-8"))
    if transfer.get("schema_version") != 1:
        raise SystemExit("unsupported transfer completion schema")
    if transfer.get("recommended_confirmation_arm") != candidate_arm:
        raise SystemExit("CANDIDATE_ARM differs from transfer recommendation")
    analysis_path = transfer_complete.parent / "ANALYSIS.json"
    transfer_manifest_path = transfer_complete.parent / "TRANSFER_MANIFEST.json"
    if sha(analysis_path) != transfer.get("analysis_sha256"):
        raise SystemExit("transfer analysis hash chain is invalid")
    if sha(transfer_manifest_path) != transfer.get("transfer_manifest_sha256"):
        raise SystemExit("transfer manifest hash chain is invalid")
    contract["candidate_evidence"] = {
        "transfer_complete": str(transfer_complete),
        "transfer_complete_sha256": expected_transfer_sha,
        "analysis": str(analysis_path.resolve()),
        "analysis_sha256": transfer["analysis_sha256"],
        "transfer_manifest": str(transfer_manifest_path.resolve()),
        "transfer_manifest_sha256": transfer["transfer_manifest_sha256"],
    }

if destination.exists():
    recorded = json.loads(destination.read_text(encoding="utf-8"))
    if recorded.get("schema_version") != 1 or recorded.get("contract") != contract:
        old_contract = recorded.get("contract", {})
        changed = sorted(
            key for key in set(old_contract) | set(contract)
            if old_contract.get(key) != contract.get(key))
        raise SystemExit(
            "screen plan drift; changed top-level contract fields: " +
            ", ".join(changed or ["schema_version"]))
else:
    payload = {
        "schema_version": 1,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "contract": contract,
    }
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(
        payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    temporary.replace(destination)
print(sha(destination))
PY
}

SCREEN_MANIFEST_SHA="$(freeze_screen_manifest)"
SCREEN_PATCH_BUNDLE_SHA="$($PYBIN - "$SCREEN_MANIFEST" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8"))
      ["contract"]["implementation"]["puffer_patch_bundle_sha256"])
PY
)"
grep -q 'EXPECTED_PUFFER_PATCH_BUNDLE_SHA256' \
  "$ROOT/tools/run_reward_ablation.sh" || {
    echo "reward launcher cannot enforce the frozen Puffer patch bundle" >&2
    exit 1
  }
if [ "$PLAN_ONLY" = "1" ]; then
  echo "SCREEN PLAN VERIFIED: $SCREEN_MANIFEST"
  echo "screen_manifest_sha256=$SCREEN_MANIFEST_SHA"
  exit 0
fi

CURRENT_ARM=""
CURRENT_SEED=""
CURRENT_INDEX=0
COMPLETED_ARMS=0

write_screen_status() {
  local state=$1 exit_code=$2 message=$3
  "$PYBIN" - "$SCREEN_STATUS" "$SCREEN_MANIFEST_SHA" "$state" \
    "$exit_code" "$CURRENT_ARM" "$CURRENT_SEED" "$CURRENT_INDEX" \
    "$COMPLETED_ARMS" "$message" "$$" <<'PY'
import datetime, json, pathlib, sys
(
    path, manifest_sha, state, exit_code, arm, seed, index,
    completed, message, pid,
) = sys.argv[1:]
payload = {
    "schema_version": 1,
    "screen_manifest_sha256": manifest_sha,
    "state": state,
    "exit_code": int(exit_code),
    "pid": int(pid),
    "current_arm": arm or None,
    "current_seed": int(seed) if seed else None,
    "current_index": int(index),
    "completed_arms": int(completed),
    "message": message,
    "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
destination = pathlib.Path(path)
temporary = destination.with_suffix(destination.suffix + ".tmp")
temporary.write_text(json.dumps(
    payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
    encoding="utf-8")
temporary.replace(destination)
PY
}

screen_exit() {
  local rc=$?
  if [ "$rc" -ne 0 ]; then
    set +e
    write_screen_status failed "$rc" "screen stopped before all arms passed"
  fi
}
trap screen_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
write_screen_status running 0 "screen contract frozen; validating or launching arms"

materialize_result() {
  local mode=$1 arm=$2 seed=$3 tag=$4 manifest_path=$5 log=$6 result=$7
  "$PYBIN" - "$ROOT" "$mode" "$arm" "$seed" "$tag" \
    "$manifest_path" "$WARM" "$POOL" "$STEPS" "$log" "$result" \
    "$SCREEN_MANIFEST" "$SCREEN_MANIFEST_SHA" "$MIN_TRAIN_GAMES" \
    "$MIN_EVAL_GAMES" <<'PY'
import hashlib, json, math, pathlib, sys
(
    root, mode, arm, seed, tag, reward_manifest_path, warm_path, pool_path,
    requested_steps, log_path, result_path, screen_manifest_path,
    screen_manifest_sha, min_train_games, min_eval_games,
) = sys.argv[1:]
root = pathlib.Path(root).resolve()
sys.path.insert(0, str(root / "tools"))
from game_stats import dashboard_windows, weighted_dashboard
from reward_manifest import load_manifest

def need_file(path, label):
    path = pathlib.Path(path)
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    return path

def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

log = need_file(log_path, "trainer log")
status_path = need_file(log_path + ".status.json", "trainer status")
process_path = need_file(log_path + ".process.json", "trainer process sidecar")
run_dir_path = need_file(log_path + ".run_dir", "run-directory sidecar")
run_manifest_path = need_file(log_path + ".manifest.json", "run manifest")
screen_manifest_file = need_file(screen_manifest_path, "screen manifest")
if sha(screen_manifest_file) != screen_manifest_sha:
    raise SystemExit("screen manifest content changed after plan freeze")
screen = json.loads(screen_manifest_file.read_text(encoding="utf-8"))["contract"]

run_dir = pathlib.Path(run_dir_path.read_text(encoding="utf-8").strip())
if not run_dir.is_absolute() or not run_dir.is_dir():
    raise SystemExit(f"invalid run directory: {run_dir}")
checkpoint_root = (root / "vendor/PufferLib/checkpoints/bloodbowl").resolve()
try:
    run_dir.resolve().relative_to(checkpoint_root)
except ValueError as exc:
    raise SystemExit(f"run directory is outside {checkpoint_root}: {run_dir}") from exc

run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
run_dir_manifest = need_file(run_dir / "RUN_MANIFEST.json", "run-directory manifest")
if run_dir_manifest.read_bytes() != run_manifest_path.read_bytes():
    raise SystemExit("run-directory and log-side manifests differ")
_, expected_reward_sha = load_manifest(reward_manifest_path)
expected_contract = {
    "mode": "native_static_pool_reward_ablation",
    "tag": tag,
    "seed": str(int(seed)),
    "requested_steps": str(int(requested_steps)),
    "reward_sha256": expected_reward_sha,
    "native_precision_bytes": "4",
    "screen_manifest_sha256": screen_manifest_sha,
    "warm_sha256": screen["warm"]["sha256"],
    "pool_identity_sha256": screen["pool"]["identity_sha256"],
    "pool_manifest_sha256": screen["pool"]["manifest_sha256"],
    "source_sha256": screen["implementation"]["source_sha256"],
    "config_sha256": screen["implementation"]["config_sha256"],
    "compiled_module_sha256": screen["implementation"]["compiled_module_sha256"],
    "launcher_sha256": screen["implementation"]["launcher_sha256"],
    "puffer_patch_bundle_sha256": screen["implementation"]["puffer_patch_bundle_sha256"],
    "vendor_head": screen["implementation"]["vendor_head"],
    "vendor_source_sha256": screen["implementation"]["vendor_source_sha256"],
    "historical_game_share": screen["pool"]["historical_game_share"],
    "frozen_bank_pct": screen["settings"]["frozen_bank_pct"],
    "num_frozen_banks": "4",
    "expected_pool_hash": screen["settings"]["expected_pool_hash"],
    "warm_bytes": str(screen["warm"]["bytes"]),
    "checkpoint_interval": screen["derived"]["checkpoint_interval"],
}
settings_to_manifest = {
    "total_agents": "total_agents",
    "num_buffers": "num_buffers",
    "num_threads": "num_threads",
    "horizon": "horizon",
    "minibatch_size": "minibatch_size",
    "checkpoint_steps": "checkpoint_steps",
    "learning_rate": "learning_rate",
    "ent_coef": "ent_coef",
    "gamma": "gamma",
    "gae_lambda": "gae_lambda",
    "replay_ratio": "replay_ratio",
    "clip_coef": "clip_coef",
    "vf_coef": "vf_coef",
    "vf_clip_coef": "vf_clip_coef",
    "max_grad_norm": "max_grad_norm",
    "expected_checkpoint_bytes": "expected_checkpoint_bytes",
}
for setting, field in settings_to_manifest.items():
    expected_contract[field] = screen["settings"][setting]
for key, expected in expected_contract.items():
    actual = run_manifest.get(key)
    if str(actual) != str(expected):
        raise SystemExit(
            f"run-manifest contract mismatch for {key}: {actual!r} != {expected!r}")

def same_path(actual, expected, label):
    if pathlib.Path(actual).resolve() != pathlib.Path(expected).resolve():
        raise SystemExit(
            f"run-manifest {label} mismatch: {actual!r} != {expected!r}")

same_path(run_manifest["reward_manifest"], reward_manifest_path,
          "reward_manifest")
same_path(run_manifest["warm"], warm_path, "warm")
same_path(run_manifest["pool"], pool_path, "pool")
same_path(run_manifest["compiled_module"],
          screen["implementation"]["compiled_module"], "compiled_module")

status = json.loads(status_path.read_text(encoding="utf-8"))
process = json.loads(process_path.read_text(encoding="utf-8"))
if int(status["exit_code"]) != 0:
    raise SystemExit(f"trainer status is {status['exit_code']}")
if int(status["pid"]) != int(process["pid"]):
    raise SystemExit("trainer status PID differs from process sidecar")
if int(process["process_group"]) != int(process["pid"]):
    raise SystemExit("trainer process group is not the detached wrapper PID")

final_steps = int(run_manifest["final_steps"])
if final_steps != int(screen["final_steps"]):
    raise SystemExit("run final step differs from frozen screen plan")
checkpoint = need_file(run_dir / f"{final_steps:016d}.bin", "exact final checkpoint")
expected_bytes = int(run_manifest["expected_checkpoint_bytes"])
if checkpoint.stat().st_size != expected_bytes:
    raise SystemExit(
        f"final checkpoint is {checkpoint.stat().st_size} bytes; expected {expected_bytes}")

required = (
    "n", "tds", "perf", "possession_rate", "blocks_thrown",
    "block_2d_frac", "block_2dred_frac", "illegal_frac",
    "reward_clip_frac", "reward_clip_frac_nonzero", "reward_clip_excess",
    "reward_nonfinite_frac", "reward_clip_episodes",
    "reward_nonfinite_episodes", "error_episodes", "demo_fallbacks",
)
integrity = (
    "reward_clip_frac", "reward_clip_frac_nonzero", "reward_clip_excess",
    "reward_nonfinite_frac", "reward_clip_episodes",
    "reward_nonfinite_episodes", "error_episodes", "demo_fallbacks",
)
phase_metrics = {
    phase: weighted_dashboard(log, phase=phase)
    for phase in ("train", "eval")
}
failures = []
for phase, metrics in phase_metrics.items():
    missing = [key for key in required if key not in metrics]
    if missing:
        failures.append({
            "phase": phase, "kind": "missing_metrics", "metrics": missing,
        })
    nonzero = {
        key: metrics[key] for key in integrity
        if key in metrics and metrics[key] != 0.0
    }
    if nonzero:
        failures.append({
            "phase": phase, "kind": "integrity_nonzero", "metrics": nonzero,
        })
for phase, minimum in (
        ("train", int(min_train_games)), ("eval", int(min_eval_games))):
    observed = phase_metrics[phase].get("n", 0.0)
    if not math.isfinite(observed) or observed < minimum:
        failures.append({
            "phase": phase, "kind": "insufficient_games",
            "observed": observed, "minimum": minimum,
        })
counted_windows = [
    window for window in dashboard_windows(log)
    if window.get("n", 0.0) > 0.0 and
       window.get("_puffer_final_reprint", 0.0) <= 0.0
]
bad_schema = sorted({
    int(window.get("_puffer_schema", 0.0)) for window in counted_windows
    if int(window.get("_puffer_schema", 0.0)) < 2
})
if bad_schema:
    failures.append({
        "kind": "telemetry_schema", "observed": bad_schema, "minimum": 2,
    })

result = {
    "schema_version": 2,
    "trainer_complete": True,
    "acceptance_pass": not failures,
    "acceptance_failures": failures,
    "arm": arm,
    "seed": int(seed),
    "tag": tag,
    "screen_manifest_sha256": screen_manifest_sha,
    "log": str(log),
    "log_sha256": sha(log),
    "status_sha256": sha(status_path),
    "process_sha256": sha(process_path),
    "run_manifest_sha256": sha(run_manifest_path),
    "reward_sha256": expected_reward_sha,
    "checkpoint": str(checkpoint),
    "checkpoint_bytes": checkpoint.stat().st_size,
    "checkpoint_sha256": sha(checkpoint),
    "train_metrics": phase_metrics["train"],
    "eval_metrics": phase_metrics["eval"],
}
path = pathlib.Path(result_path)
if mode == "validate":
    recorded = json.loads(path.read_text(encoding="utf-8"))
    if recorded != result:
        raise SystemExit(
            f"existing result sidecar does not match recomputed evidence: {path}")
elif mode == "write":
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(
        result, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    temporary.replace(path)
else:
    raise SystemExit(f"unknown result mode: {mode}")

print(json.dumps({
    "arm": arm, "seed": int(seed), "acceptance_pass": not failures,
    "checkpoint_sha256": result["checkpoint_sha256"],
}, sort_keys=True))
print(json.dumps({
    key: phase_metrics["eval"].get(key)
    for key in ("n", "tds", "perf", "possession_rate", "blocks_thrown",
                "block_2d_frac", "block_2dred_frac", "illegal_frac")
}, sort_keys=True))
if failures:
    raise SystemExit(
        "arm completed but failed screen acceptance: " +
        json.dumps(failures, sort_keys=True))
PY
}

wait_for_status() {
  local tag=$1 log=$2
  local process="${log}.process.json"
  [ -f "$process" ] || {
    echo "missing process sidecar after launcher returned for $tag" >&2
    return 1
  }
  local pid
  pid="$($PYBIN - "$process" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1], encoding="utf-8"))["pid"]))
PY
)"
  while [ ! -f "${log}.status.json" ]; do
    if ! kill -0 "$pid" 2>/dev/null; then
      for _ in $(seq 1 10); do
        [ -f "${log}.status.json" ] && break
        sleep 1
      done
      [ -f "${log}.status.json" ] || {
        echo "trainer wrapper $pid vanished before status publication for $tag" >&2
        tail -40 "$log" >&2 || true
        return 1
      }
      break
    fi
    steps_seen="$(grep -aoE 'Steps +[0-9.]+[KMBT]?' "$log" | tail -1 || true)"
    echo "WAIT arm=$CURRENT_ARM seed=$CURRENT_SEED ${steps_seen:-steps=starting}"
    write_screen_status running 0 "waiting for current trainer"
    sleep "$POLL_SECONDS"
  done
}

for index in "${!arms[@]}"; do
  arm="${arms[$index]}"
  seed="${seeds[$index]}"
  manifest="$(manifest_for "$arm")"
  tag="${PREFIX}-${arm}-s${seed}"
  log="$OUT_DIR/${tag}.log"
  result="$OUT_DIR/${tag}.result.json"
  CURRENT_ARM="$arm"
  CURRENT_SEED="$seed"
  CURRENT_INDEX=$((index + 1))

  current_screen_sha="$(freeze_screen_manifest)"
  [ "$current_screen_sha" = "$SCREEN_MANIFEST_SHA" ] || {
    echo "screen manifest hash changed during execution" >&2; exit 1; }
  write_screen_status running 0 "validating arm artifacts"

  if [ -f "$result" ]; then
    materialize_result validate "$arm" "$seed" "$tag" "$manifest" \
      "$log" "$result"
    COMPLETED_ARMS=$((COMPLETED_ARMS + 1))
    echo "SKIP verified arm=$arm seed=$seed result=$result"
    continue
  fi

  partial=0
  for artifact in "$log" "${log}.manifest.json" "${log}.status.json" \
                  "${log}.run_dir" "${log}.process.json"; do
    [ -e "$artifact" ] && partial=1
  done
  if [ "$partial" -eq 1 ]; then
    if [ ! -f "${log}.status.json" ]; then
      echo "incomplete arm artifacts exist without an atomic status: $log*" >&2
      echo "the screen lock proves no inherited trainer is still live" >&2
      exit 1
    fi
    exit_code="$($PYBIN - "${log}.status.json" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1], encoding="utf-8"))["exit_code"]))
PY
)"
    [ "$exit_code" -eq 0 ] || {
      echo "cannot recover failed arm=$arm seed=$seed exit=$exit_code" >&2
      tail -40 "$log" >&2 || true
      exit 1
    }
    echo "RECOVER completed detached arm=$arm seed=$seed"
  else
    echo "START index=$CURRENT_INDEX/$TOTAL_ARMS arm=$arm seed=$seed steps=$STEPS tag=$tag"
    write_screen_status running 0 "launching arm"
    env TAG="$tag" REWARD_MANIFEST="$manifest" WARM="$WARM" POOL="$POOL" \
        STEPS="$STEPS" SEED="$seed" LOG="$log" RIG_ALLOW_FLOAT=1 \
        SCREEN_MANIFEST_SHA256="$SCREEN_MANIFEST_SHA" DRY_RUN=0 \
        EXPECTED_PUFFER_PATCH_BUNDLE_SHA256="$SCREEN_PATCH_BUNDLE_SHA" \
        TOTAL_AGENTS="$TOTAL_AGENTS" NUM_BUFFERS="$NUM_BUFFERS" \
        NUM_THREADS="$NUM_THREADS" FROZEN_BANK_PCT="$FROZEN_BANK_PCT" \
        EXPECT_BYTES="$EXPECT_BYTES" LR="$LR" ENT_COEF="$ENT_COEF" \
        GAMMA="$GAMMA" GAE_LAMBDA="$GAE_LAMBDA" HORIZON="$HORIZON" \
        MINIBATCH_SIZE="$MINIBATCH_SIZE" CHECKPOINT_STEPS="$CHECKPOINT_STEPS" \
        REPLAY_RATIO="$REPLAY_RATIO" CLIP_COEF="$CLIP_COEF" \
        VF_COEF="$VF_COEF" VF_CLIP_COEF="$VF_CLIP_COEF" \
        MAX_GRAD_NORM="$MAX_GRAD_NORM" EXPECTED_POOL_HASH="$EXPECTED_POOL_HASH" \
        bash "$ROOT/tools/run_reward_ablation.sh"
    wait_for_status "$tag" "$log"
  fi

  exit_code="$($PYBIN - "${log}.status.json" <<'PY'
import json, sys
print(int(json.load(open(sys.argv[1], encoding="utf-8"))["exit_code"]))
PY
)"
  if [ "$exit_code" -ne 0 ]; then
    echo "FAIL arm=$arm seed=$seed exit=$exit_code" >&2
    tail -40 "$log" >&2
    exit 1
  fi
  for _ in $(seq 1 20); do
    [ -f "${log}.run_dir" ] && break
    sleep 1
  done
  [ -f "${log}.run_dir" ] || {
    echo "missing run-directory sidecar for $tag" >&2; exit 1; }
  materialize_result write "$arm" "$seed" "$tag" "$manifest" \
    "$log" "$result"
  COMPLETED_ARMS=$((COMPLETED_ARMS + 1))
  echo "DONE index=$CURRENT_INDEX/$TOTAL_ARMS arm=$arm seed=$seed result=$result"
  write_screen_status running 0 "arm accepted"

  # Status is written immediately before wrapper exit. Require the inherited
  # one-trainer lock to be released before starting the next arm.
  lock_released=0
  for _ in $(seq 1 30); do
    if flock -n /tmp/bloodbowl-rl-reward-ablation.lock -c true; then
      lock_released=1
      break
    fi
    sleep 1
  done
  [ "$lock_released" -eq 1 ] || {
    echo "trainer lock remained held after status for $tag" >&2
    exit 1
  }
done

CURRENT_ARM=""
CURRENT_SEED=""
CURRENT_INDEX=$TOTAL_ARMS
current_screen_sha="$(freeze_screen_manifest)"
[ "$current_screen_sha" = "$SCREEN_MANIFEST_SHA" ] || {
  echo "screen manifest hash changed before completion" >&2; exit 1; }

"$PYBIN" - "$SCREEN_COMPLETE" "$SCREEN_MANIFEST_SHA" "$OUT_DIR" \
  "$PREFIX" "$SCREEN_MANIFEST" <<'PY'
import datetime, hashlib, json, pathlib, sys
path, manifest_sha, out_dir, prefix, manifest_path = sys.argv[1:]
out = pathlib.Path(out_dir)
manifest = json.loads(pathlib.Path(manifest_path).read_text(encoding="utf-8"))
schedule = tuple(
    (entry["arm"], int(entry["seed"]))
    for entry in manifest["contract"]["schedule"]
)

def sha(target):
    return hashlib.sha256(pathlib.Path(target).read_bytes()).hexdigest()

results = []
for index, (arm, seed) in enumerate(schedule, 1):
    result_path = out / f"{prefix}-{arm}-s{seed}.result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    if not result.get("trainer_complete") or not result.get("acceptance_pass"):
        raise SystemExit(f"result is not accepted: {result_path}")
    if result.get("screen_manifest_sha256") != manifest_sha:
        raise SystemExit(f"result belongs to another screen: {result_path}")
    results.append({
        "index": index, "arm": arm, "seed": seed,
        "path": str(result_path), "sha256": sha(result_path),
        "checkpoint_sha256": result["checkpoint_sha256"],
    })
core = {
    "schema_version": 1,
    "screen_manifest_sha256": manifest_sha,
    "results": results,
}
destination = pathlib.Path(path)
if destination.exists():
    recorded = json.loads(destination.read_text(encoding="utf-8"))
    if {key: recorded.get(key) for key in core} != core:
        raise SystemExit("existing SCREEN_COMPLETE.json is stale or inconsistent")
else:
    payload = dict(core)
    payload["completed_utc"] = datetime.datetime.now(
        datetime.timezone.utc).isoformat()
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(
        payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8")
    temporary.replace(destination)
print(f"SCREEN COMPLETE: {destination}")
PY

COMPLETED_ARMS=$TOTAL_ARMS
write_screen_status complete 0 "all $TOTAL_ARMS arms accepted and completion summary verified"
trap - EXIT INT TERM
echo "SCREEN COMPLETE: $OUT_DIR"
