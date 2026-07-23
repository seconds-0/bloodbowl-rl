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
: "${STEPS:?STEPS is required (explicit experiment budget)}"
: "${SCREEN_PROFILE:?SCREEN_PROFILE is required (distance-possession, possession-gain, exact-action-canary, paired-confirmation, paired-final, or control-final)}"
CANDIDATE_ARM="${CANDIDATE_ARM:-}"
TRANSFER_COMPLETE="${TRANSFER_COMPLETE:-}"
EXPECTED_TRANSFER_SHA256="${EXPECTED_TRANSFER_SHA256:-}"
PREFIX="${PREFIX:-reward-screen-v1}"
OUT_DIR="${OUT_DIR:-$ROOT/runs/reward-screens/$PREFIX}"
POLL_SECONDS="${POLL_SECONDS:-30}"
PLAN_ONLY="${PLAN_ONLY:-0}"
ARM_DETACH="${ARM_DETACH:-1}"
CANARY_PLAN_AUTHORIZATION="${CANARY_PLAN_AUTHORIZATION:-}"
CANARY_PLAN_AUTHORIZATION_SHA256_FILE="${CANARY_PLAN_AUTHORIZATION_SHA256_FILE:-}"
CANARY_LAUNCH_AUTHORIZATION="${CANARY_LAUNCH_AUTHORIZATION:-}"
CANARY_LAUNCH_AUTHORIZATION_SHA256_FILE="${CANARY_LAUNCH_AUTHORIZATION_SHA256_FILE:-}"
CANARY_LAUNCH_CONSUMPTION="${CANARY_LAUNCH_CONSUMPTION:-}"
CANARY_LAUNCH_CONSUMPTION_SHA256_FILE="${CANARY_LAUNCH_CONSUMPTION_SHA256_FILE:-}"
CANARY_PLAN_AUTHORIZATION_PATH=""
CANARY_PLAN_AUTHORIZATION_SHA256=""
CANARY_QUALIFICATION_PATH=""
CANARY_QUALIFICATION_SHA256=""
CANARY_CUDA_RUNTIME_LIBRARY_PATH=""
CANARY_CUDA_RUNTIME_LIBRARY_SHA256=""
CANARY_CUDA_RUNTIME_DEVICE_COUNT=""
CANARY_LAUNCH_AUTHORIZATION_PATH=""
CANARY_LAUNCH_AUTHORIZATION_SHA256=""
CANARY_LAUNCH_CONSUMPTION_PATH=""
CANARY_LAUNCH_CONSUMPTION_SHA256=""
CANARY_AUTHORIZED_OUTPUT=""
CANARY_LIVE_INVOCATION=""
CANARY_LIVE_INVOCATION_SHA256=""

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
EXPECTED_POOL_HASH="${EXPECTED_POOL_HASH:-}"
NUM_FROZEN_BANKS=4
MIN_TRAIN_GAMES=1
MIN_EVAL_GAMES=10000
MAX_PANEL_SILENCE_SECONDS=180

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
case "$ARM_DETACH" in
  0|1) ;;
  *) echo "ARM_DETACH must be 0 or 1" >&2; exit 1 ;;
esac
case "$SCREEN_PROFILE" in
  distance-possession|possession-gain|exact-action-canary|control-final)
    [ -z "$CANDIDATE_ARM$TRANSFER_COMPLETE$EXPECTED_TRANSFER_SHA256" ] || {
      echo "candidate transfer inputs are only valid with a paired profile" >&2
      exit 1; }
    if [ "$SCREEN_PROFILE" = "exact-action-canary" ] && \
       [ "$STEPS" -ne 50000000 ]; then
      echo "exact-action-canary requires STEPS=50000000" >&2
      exit 1
    fi
    ;;
  paired-confirmation|paired-final)
    case "$CANDIDATE_ARM" in
      possession_only|gain_only|neither) ;;
      *) echo "$SCREEN_PROFILE requires CANDIDATE_ARM=possession_only, gain_only, or neither" >&2
         exit 1 ;;
    esac
    [ -n "$TRANSFER_COMPLETE" ] || {
      echo "$SCREEN_PROFILE requires TRANSFER_COMPLETE" >&2; exit 1; }
    if ! [[ "$EXPECTED_TRANSFER_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
      echo "$SCREEN_PROFILE requires a lowercase 64-character EXPECTED_TRANSFER_SHA256" >&2
      exit 1
    fi
    ;;
  *) echo "SCREEN_PROFILE must be distance-possession, possession-gain, exact-action-canary, paired-confirmation, paired-final, or control-final" >&2
     exit 1 ;;
esac

if [ "$SCREEN_PROFILE" = "exact-action-canary" ]; then
  # D217/D218: v4 and v5 have the same tensor sizes. An inherited or explicitly
  # empty legacy variable must not silently authorize a same-size warm/pool.
  [ "${WARM+x}" != x ] || {
    echo "exact-action-canary forbids WARM; qualification uses fresh obs-v5 initialization" >&2
    exit 1
  }
  [ "${POOL+x}" != x ] || {
    echo "exact-action-canary forbids POOL; qualification uses fresh obs-v5 self-play" >&2
    exit 1
  }
  WARM=""
  POOL=""
  BOOTSTRAP_MODE=fresh-v5-qualification
  NUM_FROZEN_BANKS=0
  FROZEN_BANK_PCT=0
  EXPECTED_POOL_HASH=""
else
  : "${WARM:?WARM is required}"
  : "${POOL:?POOL is required}"
  BOOTSTRAP_MODE=lineage-v5
fi

abspath() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s\n' "$LAUNCH_CWD/$1" ;;
  esac
}
[ -z "$WARM" ] || WARM="$(abspath "$WARM")"
[ -z "$POOL" ] || POOL="$(abspath "$POOL")"
OUT_DIR="$(abspath "$OUT_DIR")"
if [ -n "$TRANSFER_COMPLETE" ]; then
  TRANSFER_COMPLETE="$(abspath "$TRANSFER_COMPLETE")"
  [ -f "$TRANSFER_COMPLETE" ] || {
    echo "missing transfer completion: $TRANSFER_COMPLETE" >&2; exit 1; }
fi
if [ "$BOOTSTRAP_MODE" = "lineage-v5" ]; then
  [ -f "$WARM" ] || { echo "missing warm checkpoint: $WARM" >&2; exit 1; }
  [ -d "$POOL" ] || { echo "missing static pool: $POOL" >&2; exit 1; }
  [ -n "$EXPECTED_POOL_HASH" ] || {
    echo "lineage-v5 screen requires the explicit current EXPECTED_POOL_HASH" >&2
    exit 1
  }
  [[ "$EXPECTED_POOL_HASH" =~ ^[0-9a-f]{64}$ ]] || {
    echo "EXPECTED_POOL_HASH must be a lowercase SHA-256 digest" >&2
    exit 1
  }
fi

# A replacement canary is authorized only by the two-phase evidence tool. The
# validator runs before mkdir/flock so a missing or drifted authority cannot
# create or alter the requested output identity.
if [ "$SCREEN_PROFILE" = "exact-action-canary" ]; then
  AUTHORITY_TOOL="$ROOT/tools/exact_action_canary_authority.py"
  AUTHORITY_PYBIN="$ROOT/vendor/PufferLib/.venv/bin/python"
  if [ "$PLAN_ONLY" = "1" ]; then
    [ -z "$CANARY_LAUNCH_AUTHORIZATION$CANARY_LAUNCH_AUTHORIZATION_SHA256_FILE$CANARY_LAUNCH_CONSUMPTION$CANARY_LAUNCH_CONSUMPTION_SHA256_FILE" ] || {
      echo "exact-action canary plan-only forbids live launch authorization or consumption evidence before output creation" >&2
      exit 1
    }
    [ -n "$CANARY_PLAN_AUTHORIZATION" ] || {
      echo "CANARY_PLAN_AUTHORIZATION is required before output creation" >&2
      exit 1
    }
    [ -n "$CANARY_PLAN_AUTHORIZATION_SHA256_FILE" ] || {
      echo "CANARY_PLAN_AUTHORIZATION_SHA256_FILE is required before output creation" >&2
      exit 1
    }
    [ -f "$AUTHORITY_TOOL" ] || {
      echo "exact-action canary authority tool is missing before output creation" >&2
      exit 1
    }
    [ -x "$AUTHORITY_PYBIN" ] || {
      echo "exact-action canary candidate Python is missing before output creation" >&2
      exit 1
    }
    AUTHORITY_JSON="$($AUTHORITY_PYBIN -B "$AUTHORITY_TOOL" validate-plan \
      --authorization "$CANARY_PLAN_AUTHORIZATION" \
      --sha256-file "$CANARY_PLAN_AUTHORIZATION_SHA256_FILE" \
      --source-root "$ROOT" --require-output-absent)"
  else
    [ -z "$CANARY_PLAN_AUTHORIZATION$CANARY_PLAN_AUTHORIZATION_SHA256_FILE" ] || {
      echo "exact-action canary live launch accepts only the frozen launch authorization" >&2
      exit 1
    }
    [ -n "$CANARY_LAUNCH_AUTHORIZATION" ] || {
      echo "CANARY_LAUNCH_AUTHORIZATION is required before output creation" >&2
      exit 1
    }
    [ -n "$CANARY_LAUNCH_AUTHORIZATION_SHA256_FILE" ] || {
      echo "CANARY_LAUNCH_AUTHORIZATION_SHA256_FILE is required before output creation" >&2
      exit 1
    }
    [ -n "$CANARY_LAUNCH_CONSUMPTION" ] || {
      echo "CANARY_LAUNCH_CONSUMPTION is required before output creation" >&2
      exit 1
    }
    [ -n "$CANARY_LAUNCH_CONSUMPTION_SHA256_FILE" ] || {
      echo "CANARY_LAUNCH_CONSUMPTION_SHA256_FILE is required before output creation" >&2
      exit 1
    }
    [ -f "$AUTHORITY_TOOL" ] || {
      echo "exact-action canary authority tool is missing before output creation" >&2
      exit 1
    }
    [ -x "$AUTHORITY_PYBIN" ] || {
      echo "exact-action canary candidate Python is missing before output creation" >&2
      exit 1
    }
    AUTHORITY_JSON="$($AUTHORITY_PYBIN -B "$AUTHORITY_TOOL" validate-consumption \
      --consumption "$CANARY_LAUNCH_CONSUMPTION" \
      --consumption-sha256-file "$CANARY_LAUNCH_CONSUMPTION_SHA256_FILE" \
      --authorization "$CANARY_LAUNCH_AUTHORIZATION" \
      --authorization-sha256-file "$CANARY_LAUNCH_AUTHORIZATION_SHA256_FILE")"
  fi
  {
    IFS= read -r CANARY_PLAN_AUTHORIZATION_PATH
    IFS= read -r CANARY_PLAN_AUTHORIZATION_SHA256
    IFS= read -r CANARY_QUALIFICATION_PATH
    IFS= read -r CANARY_QUALIFICATION_SHA256
    IFS= read -r CANARY_CUDA_RUNTIME_LIBRARY_PATH
    IFS= read -r CANARY_CUDA_RUNTIME_LIBRARY_SHA256
    IFS= read -r CANARY_CUDA_RUNTIME_DEVICE_COUNT
    IFS= read -r CANARY_LAUNCH_AUTHORIZATION_PATH
    IFS= read -r CANARY_LAUNCH_AUTHORIZATION_SHA256
    IFS= read -r CANARY_LAUNCH_CONSUMPTION_PATH
    IFS= read -r CANARY_LAUNCH_CONSUMPTION_SHA256
    IFS= read -r CANARY_AUTHORIZED_OUTPUT
  } < <("$AUTHORITY_PYBIN" - "$AUTHORITY_JSON" \
      "$CANARY_PLAN_AUTHORIZATION" "$CANARY_LAUNCH_AUTHORIZATION" <<'PY'
import json, sys
payload = json.loads(sys.argv[1])
if payload["kind"] == "exact_action_canary_plan_authorization":
    plan_path = sys.argv[2]
    plan_sha = payload["authorization_sha256"]
    launch_path = ""
    launch_sha = ""
    consumption_path = ""
    consumption_sha = ""
    output = payload["screen"]["output"]
else:
    plan_path = payload["plan_authorization"]["path"]
    plan_sha = payload["plan_authorization"]["sha256"]
    launch_path = sys.argv[3]
    launch_sha = payload["authorization_sha256"]
    consumption_path = payload["launch_consumption"]["path"]
    consumption_sha = payload["launch_consumption"]["sha256"]
    output = payload["plan_output"]["path"]
runtime = payload["cuda_runtime"]
print(plan_path)
print(plan_sha)
print(payload["qualification"]["path"])
print(payload["qualification"]["sha256"])
print(runtime["library"]["resolved_path"])
print(runtime["library"]["sha256"])
print(runtime["after_extension_import"]["device_count"])
print(launch_path)
print(launch_sha)
print(consumption_path)
print(consumption_sha)
print(output)
PY
  )
  [ "$OUT_DIR" = "$CANARY_AUTHORIZED_OUTPUT" ] || {
    echo "exact-action canary OUT_DIR differs from the authorized output" >&2
    exit 1
  }
  [ "$PREFIX" = "exact-action-canary-50m-s42-v4" ] || {
    echo "exact-action canary requires PREFIX=exact-action-canary-50m-s42-v4" >&2
    exit 1
  }
  [ "$ARM_DETACH" = "0" ] || {
    echo "exact-action canary requires ARM_DETACH=0" >&2
    exit 1
  }
fi
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
if [ "$SCREEN_PROFILE" = "exact-action-canary" ]; then
  CANARY_LIVE_INVOCATION="$OUT_DIR/CANARY_LIVE_INVOCATION.json"
  CANARY_LIVE_INVOCATION_SHA256="$($PYBIN - \
    "$CANARY_LIVE_INVOCATION" "$CANARY_LAUNCH_AUTHORIZATION_PATH" \
    "$CANARY_LAUNCH_AUTHORIZATION_SHA256" \
    "$CANARY_LAUNCH_CONSUMPTION_PATH" \
    "$CANARY_LAUNCH_CONSUMPTION_SHA256" "$OUT_DIR" <<'PY'
import datetime, hashlib, json, os, pathlib, sys

destination = pathlib.Path(sys.argv[1])
payload = {
    "schema_version": 1,
    "kind": "exact_action_canary_live_invocation",
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "qualification_only": True,
    "launch_authorization": {
        "path": sys.argv[2],
        "sha256": sys.argv[3],
    },
    "launch_consumption": {
        "path": sys.argv[4],
        "sha256": sys.argv[5],
    },
    "plan_output": sys.argv[6],
    "attempt": 1,
    "maximum_starts": 1,
}
raw = (json.dumps(
    payload, indent=2, sort_keys=True, allow_nan=False
) + "\n").encode("utf-8")
try:
    with destination.open("xb") as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
except FileExistsError as exc:
    raise SystemExit(
        "exact-action canary live invocation was already claimed"
    ) from exc
try:
    directory_fd = os.open(destination.parent, os.O_RDONLY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
except OSError as exc:
    raise SystemExit(
        "exact-action canary live invocation claim durability failed; "
        "the claim remains consumed"
    ) from exc
print(hashlib.sha256(raw).hexdigest())
PY
  )"
fi
/bin/bash "$ROOT/tools/install_puffer_env.sh" --check "$ROOT/vendor/PufferLib"

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
  exact-action-canary)
    # Qualification only: one reward-frozen arm bounds repaired-runtime
    # exposure before any causal screen receives a long budget.
    arms=(both)
    seeds=(42)
    ;;
  paired-confirmation)
    arms=(both "$CANDIDATE_ARM" "$CANDIDATE_ARM" both)
    seeds=(42 42 43 43)
    ;;
  paired-final)
    # Three independent learner seeds spend a fixed long-run budget more
    # efficiently than extending only two seeds. Alternating order balances
    # reference/candidate exposure to wall-clock drift.
    arms=(both "$CANDIDATE_ARM" "$CANDIDATE_ARM" both both "$CANDIDATE_ARM")
    seeds=(42 42 43 43 44 44)
    ;;
  control-final)
    # A rejected simplification routes vacation compute into replicated R0
    # trajectories rather than training an objective that failed its gate.
    arms=(both both both)
    seeds=(42 43 44)
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
    "$EXPECTED_TRANSFER_SHA256" "$ARM_DETACH" "$POLL_SECONDS" \
    "$MAX_PANEL_SILENCE_SECONDS" "$BOOTSTRAP_MODE" \
    "$NUM_FROZEN_BANKS" "$CANARY_PLAN_AUTHORIZATION_PATH" \
    "$CANARY_PLAN_AUTHORIZATION_SHA256" "$CANARY_QUALIFICATION_PATH" \
    "$CANARY_QUALIFICATION_SHA256" "$CANARY_CUDA_RUNTIME_LIBRARY_PATH" \
    "$CANARY_CUDA_RUNTIME_LIBRARY_SHA256" \
    "$CANARY_CUDA_RUNTIME_DEVICE_COUNT" <<'PY'
import datetime, hashlib, json, pathlib, subprocess, sys, sysconfig

(
    manifest_path, root_path, prefix, steps, out_dir, warm_path, pool_path,
    total_agents, num_buffers, num_threads, frozen_bank_pct, expect_bytes,
    learning_rate, ent_coef, gamma, gae_lambda, horizon, minibatch_size,
    checkpoint_steps, replay_ratio, clip_coef, vf_coef, vf_clip_coef,
    max_grad_norm, expected_pool_hash, min_train_games, min_eval_games,
    screen_profile, candidate_arm, transfer_complete_path,
    expected_transfer_sha, arm_detach, poll_seconds, max_panel_silence_seconds,
    bootstrap_mode, num_frozen_banks, canary_plan_authorization,
    canary_plan_authorization_sha256, canary_qualification,
    canary_qualification_sha256, canary_cuda_runtime_library_path,
    canary_cuda_runtime_library_sha256, canary_cuda_runtime_device_count,
) = sys.argv[1:]
root = pathlib.Path(root_path).resolve()
vendor = root / "vendor" / "PufferLib"
warm = pathlib.Path(warm_path).resolve() if warm_path else None
pool = pathlib.Path(pool_path).resolve() if pool_path else None
destination = pathlib.Path(manifest_path)
qualification_only = screen_profile == "exact-action-canary"
if qualification_only != (bootstrap_mode == "fresh-v5-qualification"):
    raise SystemExit("qualification profile/bootstrap mode mismatch")
environment_header = root / "puffer/bloodbowl/bloodbowl.h"
if "#define BBE_OBS_VERSION 5" not in environment_header.read_text(
        encoding="utf-8"):
    raise SystemExit("source tree does not declare obs-v5")

def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

def sha256sum_bundle(paths, labels):
    payload = b"".join(
        f"{sha(path)}  {label}\n".encode()
        for path, label in zip(paths, labels)
    )
    return hashlib.sha256(payload).hexdigest()

def tree_sha256(path):
    path = pathlib.Path(path)
    if not path.is_dir():
        raise SystemExit(f"runtime tree is missing: {path}")
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or (not child.is_dir() and not child.is_file()):
            raise SystemExit(f"runtime tree contains unsupported entry: {child}")
        if child.is_dir():
            continue
        relative = child.relative_to(path).as_posix()
        size = child.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(size).encode("ascii"))
        digest.update(b"\0")
        digest.update(sha(child).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()

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
    "num_frozen_banks": num_frozen_banks,
    "arm_detach": arm_detach,
}

expect_size = int(expect_bytes)
if qualification_only:
    if warm is not None or pool is not None or int(num_frozen_banks) != 0:
        raise SystemExit("fresh qualification cannot carry warm/pool/frozen banks")
    pool_raw = b""
    pool_identity = ""
    bank_identity = []
else:
    if warm is None or pool is None or int(num_frozen_banks) != 4:
        raise SystemExit("lineage-v5 screen requires warm and four-bank pool")
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
        lineage_file = seed.get("lineage_file")
        if not isinstance(lineage_file, str) or not lineage_file:
            raise SystemExit(f"pool bank {index} lacks lineage_file")
        lineage_manifest_sha = seed.get("lineage_sha256")
        if (not isinstance(lineage_manifest_sha, str) or
                len(lineage_manifest_sha) != 64):
            raise SystemExit(f"pool bank {index} lacks lineage_sha256")
        bank_identity.append({
            "bank": index, "name": seed.get("name"), "file": str(path),
            "bytes": size, "sha256": digest,
            "lineage_file": str((pool / lineage_file).resolve()),
            "manifest_lineage_sha256": lineage_manifest_sha,
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
from analyze_reward_candidate_transfer import (
    TransferError, validate_completion_evidence,
)
from live_integrity_guard import HARD_INTEGRITY_KEYS
from checkpoint_lineage import (
    lineage_digest, sidecar_path, validate_lineage,
)
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
elif screen_profile == "exact-action-canary":
    if int(steps) != 50_000_000:
        raise SystemExit("exact-action-canary requires exactly 50M requested steps")
    reward_files = {
        "both": root / "puffer/config/rewards/r0_full.json",
    }
    arm_order = ("both",)
    schedule_seeds = (42,)
elif screen_profile == "control-final":
    reward_files = {
        "both": root / "puffer/config/rewards/r0_full.json",
    }
    arm_order = ("both", "both", "both")
    schedule_seeds = (42, 43, 44)
elif screen_profile in ("paired-confirmation", "paired-final"):
    allowed = {"possession_only", "gain_only", "neither"}
    if candidate_arm not in allowed:
        raise SystemExit(f"invalid {screen_profile} candidate")
    all_reward_files = {
        "both": root / "puffer/config/rewards/r0_full.json",
        "possession_only": root / "puffer/config/rewards/p1_possession_only.json",
        "gain_only": root / "puffer/config/rewards/p2_gain_only.json",
        "neither": root / "puffer/config/rewards/r2_no_possession.json",
    }
    reward_files = {
        arm: all_reward_files[arm] for arm in ("both", candidate_arm)
    }
    if screen_profile == "paired-confirmation":
        arm_order = ("both", candidate_arm, candidate_arm, "both")
        schedule_seeds = (42, 42, 43, 43)
    else:
        arm_order = (
            "both", candidate_arm, candidate_arm,
            "both", "both", candidate_arm,
        )
        schedule_seeds = (42, 42, 43, 43, 44, 44)
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
source_hash = source_hash_path.read_text(encoding="utf-8").strip()
module_probe = subprocess.run(
    [sys.executable, "-c", """
import json
from pufferlib import _C
print(json.dumps({
    "module": _C.__file__,
    "env_name": getattr(_C, "env_name", None),
    "gpu": int(bool(getattr(_C, "gpu", False))),
    "precision_bytes": int(getattr(_C, "precision_bytes", 0)),
    "exact_action_source_sha256": getattr(
        _C, "exact_action_source_hash", "<missing>"),
    "environment_source_sha256": getattr(
        _C, "environment_source_hash", "<missing>"),
    "observation_abi": getattr(_C, "observation_abi", "<missing>"),
    "observation_version": getattr(
        _C, "observation_version", "<missing>"),
    "action_abi": getattr(_C, "action_abi", "<missing>"),
}, sort_keys=True))
"""], cwd=vendor, text=True, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE, check=False)
if module_probe.returncode != 0:
    raise SystemExit(
        "could not interrogate compiled native module: " +
        module_probe.stderr.strip())
compiled_contract = json.loads(module_probe.stdout)
if pathlib.Path(compiled_contract["module"]).resolve() != module.resolve():
    raise SystemExit("imported native module differs from frozen module path")
if (
    compiled_contract["env_name"] != "bloodbowl" or
    compiled_contract["gpu"] != 1 or
    compiled_contract["precision_bytes"] != 4 or
    compiled_contract["environment_source_sha256"] != source_hash or
    compiled_contract["observation_abi"] != "obs-v5" or
    compiled_contract["observation_version"] != 5 or
    compiled_contract["action_abi"] != "exact-joint-v1" or
    len(compiled_contract["exact_action_source_sha256"]) != 64
):
    raise SystemExit(
        "compiled native module does not satisfy the frozen obs-v5/exact-action contract")

patches = [
    root / "training/pufferl_env_dashboard_limit.patch",
    root / "training/pufferl_env_json.patch",
    root / "training/pufferl_env_json_metadata_upgrade.patch",
    root / "training/pufferl_env_phase_contract.patch",
    root / "training/pufferl_eval_episode_gate.patch",
    root / "training/pufferl_metrics_keyerror.patch",
    root / "training/torch_pufferl_trusted_load.patch",
    root / "training/selfplay_league.patch",
    root / "training/puffer_exact_joint_actions.patch",
    root / "training/puffer_recurrent_eval_state.patch",
    root / "training/puffer_frozen_prio_mask.patch",
    root / "training/puffer_recurrent_cuda_qualification.patch",
]
vendor_sources = [
    "pufferlib/__init__.py", "pufferlib/pufferl.py",
    "pufferlib/selfplay.py", "pufferlib/torch_pufferl.py",
    "pufferlib/models.py", "pufferlib/muon.py", "src/pufferlib.cu",
    "src/bindings.cu", "src/bindings_cpu.cpp", "src/kernels.cu",
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

warm_identity = None
pool_lineage_bundle_sha = ""
if not qualification_only:
    expected_lineage = {
        "source_sha256": source_hash,
        "compiled_module_sha256": sha(module),
        "puffer_patch_bundle_sha256": patch_bundle_sha,
    }
    warm_payload = validate_lineage(
        warm, sidecar_path(warm), expected=expected_lineage,
        require_eligible=True)
    warm_identity = {
        "path": str(warm), "bytes": warm.stat().st_size, "sha256": sha(warm),
        "lineage_path": str(sidecar_path(warm).resolve()),
        "lineage_sha256": lineage_digest(warm_payload),
    }
    pool_lineages = []
    for bank in bank_identity:
        payload = validate_lineage(
            bank["file"], bank["lineage_file"], expected=expected_lineage,
            require_eligible=True)
        bank["lineage_sha256"] = lineage_digest(payload)
        if bank["lineage_sha256"] != bank["manifest_lineage_sha256"]:
            raise SystemExit(
                f"pool bank {bank['bank']} lineage digest differs from manifest")
        pool_lineages.append({
            "bank": bank["bank"], "checkpoint_sha256": bank["sha256"],
            "lineage_sha256": bank["lineage_sha256"],
        })
    pool_lineage_bundle_sha = hashlib.sha256(json.dumps(
        pool_lineages, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

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
historical_share = (
    int(num_frozen_banks) * per_bank / ((total // buffers) / 2.0)
    if int(num_frozen_banks) else 0.0
)

schedule = [
    {"index": index + 1, "arm": arm, "seed": seed}
    for index, (arm, seed) in enumerate(zip(
        arm_order, schedule_seeds))
]
launcher = root / "tools/run_reward_ablation.sh"
screen_script = root / "tools/run_reward_screen.sh"
game_stats = root / "tools/game_stats.py"
live_integrity_guard = root / "tools/live_integrity_guard.py"
checkpoint_lineage_tool = root / "tools/checkpoint_lineage.py"
status_wrapper = root / "tools/trainer_status_wrapper.sh"
cuda_runtime_wrapper = root / "tools/puffer_cuda_runtime.py"
canary_authority_tool = root / "tools/exact_action_canary_authority.py"
contract = {
    "screen_profile": screen_profile,
    "qualification_only": qualification_only,
    "bootstrap": {
        "mode": bootstrap_mode,
        "observation_abi": "obs-v5",
        "observation_version": 5,
        "action_abi": "exact-joint-v1",
        "initialization": "fresh" if qualification_only else "lineage-v5",
        "warm_lineage_sha256": (
            "" if warm_identity is None else warm_identity["lineage_sha256"]),
        "pool_lineage_bundle_sha256": pool_lineage_bundle_sha,
    },
    "prefix": prefix,
    "out_dir": str(pathlib.Path(out_dir).resolve()),
    "requested_steps": int(steps),
    "final_steps": final_steps,
    "rollout_quantum": rollout_quantum,
    "schedule": schedule,
    "settings": settings,
    "warm": warm_identity,
    "pool": None if qualification_only else {
        "path": str(pool),
        "manifest_sha256": hashlib.sha256(pool_raw).hexdigest(),
        "identity_sha256": pool_identity,
        "lineage_bundle_sha256": pool_lineage_bundle_sha,
        "banks": bank_identity,
        "rows_per_bank": per_bank,
        "historical_game_share": str(historical_share),
    },
    "rewards": rewards,
    "error_budget": {
        "contamination_budget": 0,
        "detection_poll_seconds": int(poll_seconds),
        "max_panel_silence_seconds": int(max_panel_silence_seconds),
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
    },
    "implementation": {
        "screen_script_sha256": sha(screen_script),
        "game_stats_sha256": sha(game_stats),
        "live_integrity_guard_sha256": sha(live_integrity_guard),
        "checkpoint_lineage_sha256": sha(checkpoint_lineage_tool),
        "status_wrapper_sha256": sha(status_wrapper),
        "cuda_runtime_wrapper_sha256": sha(cuda_runtime_wrapper),
        "canary_authority_tool_sha256": sha(canary_authority_tool),
        "launcher_sha256": sha(launcher),
        "candidate_transfer_analyzer_sha256": sha(
            root / "tools/analyze_reward_candidate_transfer.py"),
        "source_sha256": source_hash_path.read_text().strip(),
        "config_sha256": sha(config),
        "config_tree_sha256": tree_sha256(vendor / "config"),
        "default_config_sha256": sha(vendor / "config/default.ini"),
        "compiled_module": str(module.resolve()),
        "compiled_module_bytes": module.stat().st_size,
        "compiled_module_sha256": sha(module),
        "compiled_semantic_contract": compiled_contract,
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
if qualification_only:
    canary_authority = {
        "plan_authorization": str(
            pathlib.Path(canary_plan_authorization).resolve()),
        "plan_authorization_sha256": canary_plan_authorization_sha256,
        "qualification": str(pathlib.Path(canary_qualification).resolve()),
        "qualification_sha256": canary_qualification_sha256,
        "cuda_runtime_library_path": str(
            pathlib.Path(canary_cuda_runtime_library_path).resolve()),
        "cuda_runtime_library_sha256": canary_cuda_runtime_library_sha256,
        "cuda_runtime_device_count": int(canary_cuda_runtime_device_count),
    }
    for key in (
        "plan_authorization_sha256",
        "qualification_sha256",
        "cuda_runtime_library_sha256",
    ):
        value = canary_authority[key]
        if len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise SystemExit(f"canary authority {key} is not a SHA-256 digest")
    if canary_authority["cuda_runtime_device_count"] <= 0:
        raise SystemExit("canary authority CUDA device count must be positive")
    contract["canary_authority"] = canary_authority
elif any((
    canary_plan_authorization,
    canary_plan_authorization_sha256,
    canary_qualification,
    canary_qualification_sha256,
    canary_cuda_runtime_library_path,
    canary_cuda_runtime_library_sha256,
    canary_cuda_runtime_device_count,
)):
    raise SystemExit("non-canary screen cannot carry canary authority")
if screen_profile in ("paired-confirmation", "paired-final"):
    contract["candidate_arm"] = candidate_arm
    transfer_complete = pathlib.Path(transfer_complete_path).resolve()
    # The shared validator binds recommended_confirmation_arm, analysis
    # recommendation, transfer_manifest_sha256, analysis_sha256, and the exact
    # evaluated cell hashes.
    try:
        contract["candidate_evidence"] = validate_completion_evidence(
            transfer_complete,
            expected_complete_sha=expected_transfer_sha,
            expected_candidate=candidate_arm,
        )
    except (OSError, TransferError, ValueError) as exc:
        raise SystemExit(f"invalid candidate transfer evidence: {exc}") from exc

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

CANARY_LAUNCH_RECORD=""
CANARY_LAUNCH_RECORD_SHA256=""
if [ "$SCREEN_PROFILE" = "exact-action-canary" ]; then
  CANARY_LAUNCH_RECORD="$OUT_DIR/CANARY_LAUNCH_RECORD.json"
  [ ! -e "$CANARY_LAUNCH_RECORD" ] || {
    echo "refusing to reuse exact-action canary launch record: $CANARY_LAUNCH_RECORD" >&2
    exit 1
  }
  "$PYBIN" - "$CANARY_LAUNCH_RECORD" "$CANARY_LAUNCH_AUTHORIZATION_PATH" \
    "$CANARY_LAUNCH_AUTHORIZATION_SHA256" "$CANARY_LAUNCH_CONSUMPTION_PATH" \
    "$CANARY_LAUNCH_CONSUMPTION_SHA256" "$CANARY_LIVE_INVOCATION" \
    "$CANARY_LIVE_INVOCATION_SHA256" "$CANARY_PLAN_AUTHORIZATION_PATH" \
    "$CANARY_PLAN_AUTHORIZATION_SHA256" "$CANARY_QUALIFICATION_PATH" \
    "$CANARY_QUALIFICATION_SHA256" "$SCREEN_MANIFEST" \
    "$SCREEN_MANIFEST_SHA" <<'PY'
import datetime, json, os, pathlib, sys
(
    destination_raw, launch_path, launch_sha, consumption_path, consumption_sha,
    live_invocation, live_invocation_sha, plan_path, plan_sha,
    qualification_path, qualification_sha, manifest_path, manifest_sha,
) = sys.argv[1:]
destination = pathlib.Path(destination_raw)
payload = {
    "schema_version": 1,
    "kind": "exact_action_canary_launch_record",
    "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "qualification_only": True,
    "eligible": False,
    "reward_evidence_eligible": False,
    "launch_authorization": launch_path,
    "launch_authorization_sha256": launch_sha,
    "launch_consumption": consumption_path,
    "launch_consumption_sha256": consumption_sha,
    "live_invocation": live_invocation,
    "live_invocation_sha256": live_invocation_sha,
    "plan_authorization": plan_path,
    "plan_authorization_sha256": plan_sha,
    "qualification": qualification_path,
    "qualification_sha256": qualification_sha,
    "screen_manifest": manifest_path,
    "screen_manifest_sha256": manifest_sha,
}
temporary = destination.with_name(f".{destination.name}.tmp.{os.getpid()}")
try:
    with temporary.open("xb") as handle:
        handle.write((json.dumps(
            payload, indent=2, sort_keys=True, allow_nan=False) + "\n"
        ).encode("utf-8"))
        handle.flush()
        os.fsync(handle.fileno())
    os.link(temporary, destination)
finally:
    temporary.unlink(missing_ok=True)
PY
  CANARY_LAUNCH_RECORD_SHA256="$(sha256sum "$CANARY_LAUNCH_RECORD" | awk '{print $1}')"
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
import hashlib, json, os, pathlib, sys
(
    root, mode, arm, seed, tag, reward_manifest_path, warm_path, pool_path,
    requested_steps, log_path, result_path, screen_manifest_path,
    screen_manifest_sha, min_train_games, min_eval_games,
) = sys.argv[1:]
root = pathlib.Path(root).resolve()

def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()

screen_manifest_file = pathlib.Path(screen_manifest_path)
if not screen_manifest_file.is_file():
    raise SystemExit(f"missing screen manifest: {screen_manifest_file}")
if sha(screen_manifest_file) != screen_manifest_sha:
    raise SystemExit("screen manifest content changed after plan freeze")
screen = json.loads(screen_manifest_file.read_text(encoding="utf-8"))["contract"]
game_stats_path = root / "tools/game_stats.py"
if (
    not game_stats_path.is_file()
    or sha(game_stats_path)
    != screen["implementation"]["game_stats_sha256"]
):
    raise SystemExit("game_stats.py changed after screen plan freeze")
live_integrity_guard_path = root / "tools/live_integrity_guard.py"
if (
    not live_integrity_guard_path.is_file()
    or sha(live_integrity_guard_path)
    != screen["implementation"]["live_integrity_guard_sha256"]
):
    raise SystemExit("live_integrity_guard.py changed after screen plan freeze")
checkpoint_lineage_path = root / "tools/checkpoint_lineage.py"
if (
    not checkpoint_lineage_path.is_file()
    or sha(checkpoint_lineage_path)
    != screen["implementation"]["checkpoint_lineage_sha256"]
):
    raise SystemExit("checkpoint_lineage.py changed after screen plan freeze")
cuda_runtime_wrapper_path = root / "tools/puffer_cuda_runtime.py"
if (
    not cuda_runtime_wrapper_path.is_file()
    or sha(cuda_runtime_wrapper_path)
    != screen["implementation"]["cuda_runtime_wrapper_sha256"]
):
    raise SystemExit("puffer_cuda_runtime.py changed after screen plan freeze")
canary_authority_tool_path = root / "tools/exact_action_canary_authority.py"
if (
    not canary_authority_tool_path.is_file()
    or sha(canary_authority_tool_path)
    != screen["implementation"]["canary_authority_tool_sha256"]
):
    raise SystemExit(
        "exact_action_canary_authority.py changed after screen plan freeze"
    )

sys.path.insert(0, str(root / "tools"))
from game_stats import (
    completed_game_requirement_met,
    dashboard_windows,
    weighted_dashboard,
)
from reward_manifest import load_manifest
from live_integrity_guard import HARD_INTEGRITY_KEYS

error_budget = screen.get("error_budget")
if not isinstance(error_budget, dict):
    raise SystemExit("screen lacks a frozen error budget")
if error_budget.get("contamination_budget") != 0:
    raise SystemExit("screen contamination budget is not zero")
if tuple(error_budget.get("hard_integrity_keys", ())) != HARD_INTEGRITY_KEYS:
    raise SystemExit("screen hard-integrity registry drifted")

def need_file(path, label):
    path = pathlib.Path(path)
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    return path

log = need_file(log_path, "trainer log")
status_path = need_file(log_path + ".status.json", "trainer status")
process_path = need_file(log_path + ".process.json", "trainer process sidecar")
run_dir_path = need_file(log_path + ".run_dir", "run-directory sidecar")
run_manifest_path = need_file(log_path + ".manifest.json", "run manifest")
screen_manifest_file = need_file(screen_manifest_path, "screen manifest")

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
canary_launch = None
if screen["qualification_only"]:
    authority = screen.get("canary_authority")
    if not isinstance(authority, dict):
        raise SystemExit("fresh qualification screen lacks canary authority")
    launch_record_path = need_file(
        screen_manifest_file.parent / "CANARY_LAUNCH_RECORD.json",
        "canary launch record",
    )
    canary_launch = json.loads(
        launch_record_path.read_text(encoding="utf-8")
    )
    expected_launch_record = {
        "schema_version": 1,
        "kind": "exact_action_canary_launch_record",
        "qualification_only": True,
        "eligible": False,
        "reward_evidence_eligible": False,
        "plan_authorization": authority["plan_authorization"],
        "plan_authorization_sha256": authority["plan_authorization_sha256"],
        "qualification": authority["qualification"],
        "qualification_sha256": authority["qualification_sha256"],
        "screen_manifest_sha256": screen_manifest_sha,
    }
    for key, expected in expected_launch_record.items():
        if canary_launch.get(key) != expected:
            raise SystemExit(f"canary launch record {key} drifted")
    if pathlib.Path(canary_launch["screen_manifest"]).resolve() != screen_manifest_file.resolve():
        raise SystemExit("canary launch record screen manifest path drifted")
    if not pathlib.Path(canary_launch["launch_authorization"]).is_absolute():
        raise SystemExit("canary launch authorization path is not absolute")
    if len(canary_launch["launch_authorization_sha256"]) != 64:
        raise SystemExit("canary launch authorization digest is malformed")
    launch_authorization_file = need_file(
        canary_launch["launch_authorization"], "canary launch authorization"
    )
    if launch_authorization_file.is_symlink() or sha(
        launch_authorization_file
    ) != canary_launch["launch_authorization_sha256"]:
        raise SystemExit("canary launch authorization file drifted")
    launch_authorization_sidecar = need_file(
        launch_authorization_file.with_suffix(".sha256"),
        "canary launch authorization digest sidecar",
    )
    if launch_authorization_sidecar.is_symlink() or launch_authorization_sidecar.read_text(
        encoding="ascii"
    ) != (
        f"{canary_launch['launch_authorization_sha256']}  "
        f"{launch_authorization_file.name}\n"
    ):
        raise SystemExit("canary launch authorization digest sidecar drifted")
    launch_authorization = json.loads(
        launch_authorization_file.read_text(encoding="utf-8")
    )
    if (
        launch_authorization.get("schema_version") != 1
        or launch_authorization.get("kind")
        != "exact_action_canary_launch_authorization"
        or launch_authorization.get("qualification_only") is not True
        or launch_authorization.get("plan_authorization")
        != {
            "path": authority["plan_authorization"],
            "sha256": authority["plan_authorization_sha256"],
            "sha256_file": str(pathlib.Path(
                authority["plan_authorization"]
            ).with_suffix(".sha256")),
        }
        or launch_authorization.get("qualification")
        != {
            "path": authority["qualification"],
            "sha256": authority["qualification_sha256"],
            "inventory": launch_authorization.get("qualification", {}).get(
                "inventory"
            ),
            "runner_sha256": launch_authorization.get("qualification", {}).get(
                "runner_sha256"
            ),
            "construction_gate": launch_authorization.get(
                "qualification", {}
            ).get("construction_gate"),
            "throughput_baseline": launch_authorization.get(
                "qualification", {}
            ).get("throughput_baseline"),
        }
        or launch_authorization.get("plan_output", {}).get("path")
        != str(screen_manifest_file.parent)
        or launch_authorization.get("eligibility")
        != {
            "qualification_only": True,
            "checkpoint_ancestry": False,
            "reward_evidence": False,
            "promotion": False,
            "bbtv_follower": False,
        }
    ):
        raise SystemExit("canary launch authorization contract drifted")
    expected_consumption_path = launch_authorization_file.with_name(
        "CANARY_LAUNCH_CONSUMPTION.json"
    )
    if canary_launch.get("launch_consumption") != str(expected_consumption_path):
        raise SystemExit("canary launch consumption path is not canonical")
    consumption_file = need_file(
        expected_consumption_path, "canary launch consumption"
    )
    if consumption_file.is_symlink() or sha(consumption_file) != canary_launch.get(
        "launch_consumption_sha256"
    ):
        raise SystemExit("canary launch consumption file drifted")
    consumption_sidecar = need_file(
        consumption_file.with_suffix(".sha256"),
        "canary launch consumption digest sidecar",
    )
    if consumption_sidecar.is_symlink() or consumption_sidecar.read_text(
        encoding="ascii"
    ) != (
        f"{canary_launch['launch_consumption_sha256']}  "
        f"{consumption_file.name}\n"
    ):
        raise SystemExit("canary launch consumption digest sidecar drifted")
    consumption = json.loads(consumption_file.read_text(encoding="utf-8"))
    if (
        consumption.get("schema_version") != 1
        or consumption.get("kind") != "exact_action_canary_launch_consumption"
        or consumption.get("qualification_only") is not True
        or consumption.get("launch_authorization", {}).get("path")
        != str(launch_authorization_file)
        or consumption.get("launch_authorization", {}).get("sha256")
        != canary_launch["launch_authorization_sha256"]
        or consumption.get("launch_authorization", {}).get("sha256_file")
        != str(launch_authorization_sidecar)
        or consumption.get("plan_authorization")
        != launch_authorization.get("plan_authorization")
        or consumption.get("qualification")
        != launch_authorization.get("qualification")
        or consumption.get("plan_output") != str(screen_manifest_file.parent)
        or consumption.get("attempt") != 1
        or consumption.get("maximum_starts") != 1
        or consumption.get("eligibility")
        != launch_authorization.get("eligibility")
    ):
        raise SystemExit("canary launch consumption contract drifted")
    expected_live_invocation_path = (
        screen_manifest_file.parent / "CANARY_LIVE_INVOCATION.json"
    )
    if canary_launch.get("live_invocation") != str(
        expected_live_invocation_path
    ):
        raise SystemExit("canary live invocation path is not canonical")
    live_invocation_file = need_file(
        expected_live_invocation_path, "canary live invocation"
    )
    if live_invocation_file.is_symlink() or sha(
        live_invocation_file
    ) != canary_launch.get("live_invocation_sha256"):
        raise SystemExit("canary live invocation file drifted")
    live_invocation = json.loads(
        live_invocation_file.read_text(encoding="utf-8")
    )
    if live_invocation != {
        "schema_version": 1,
        "kind": "exact_action_canary_live_invocation",
        "created_utc": live_invocation.get("created_utc"),
        "qualification_only": True,
        "launch_authorization": {
            "path": str(launch_authorization_file),
            "sha256": canary_launch["launch_authorization_sha256"],
        },
        "launch_consumption": {
            "path": str(consumption_file),
            "sha256": canary_launch["launch_consumption_sha256"],
        },
        "plan_output": str(screen_manifest_file.parent),
        "attempt": 1,
        "maximum_starts": 1,
    } or not isinstance(live_invocation.get("created_utc"), str):
        raise SystemExit("canary live invocation contract drifted")
expected_contract = {
    "mode": ("native_fresh_v5_qualification"
             if screen["qualification_only"]
             else "native_static_pool_reward_ablation"),
    "tag": tag,
    "seed": str(int(seed)),
    "bootstrap_mode": screen["bootstrap"]["mode"],
    "initialization": screen["bootstrap"]["initialization"],
    "qualification_only": "1" if screen["qualification_only"] else "0",
    "observation_abi": "obs-v5",
    "observation_version": "5",
    "action_abi": "exact-joint-v1",
    "policy_hidden_size": screen["settings"]["policy_hidden_size"],
    "policy_num_layers": screen["settings"]["policy_num_layers"],
    "policy_expansion_factor": screen["settings"]["policy_expansion_factor"],
    "requested_steps": str(int(requested_steps)),
    "reward_sha256": expected_reward_sha,
    "native_precision_bytes": "4",
    "screen_manifest_sha256": screen_manifest_sha,
    "warm_sha256": "" if screen["warm"] is None else screen["warm"]["sha256"],
    "warm_lineage_sha256": screen["bootstrap"]["warm_lineage_sha256"],
    "pool_identity_sha256": (
        "" if screen["pool"] is None else screen["pool"]["identity_sha256"]),
    "pool_manifest_sha256": (
        "" if screen["pool"] is None else screen["pool"]["manifest_sha256"]),
    "pool_lineage_bundle_sha256": screen["bootstrap"]["pool_lineage_bundle_sha256"],
    "source_sha256": screen["implementation"]["source_sha256"],
    "config_sha256": screen["implementation"]["config_sha256"],
    "config_tree_sha256": screen["implementation"]["config_tree_sha256"],
    "default_config_sha256": screen["implementation"]["default_config_sha256"],
    "compiled_module_sha256": screen["implementation"]["compiled_module_sha256"],
    "compiled_exact_action_source_sha256": screen["implementation"]["compiled_semantic_contract"]["exact_action_source_sha256"],
    "compiled_environment_source_sha256": screen["implementation"]["compiled_semantic_contract"]["environment_source_sha256"],
    "compiled_observation_abi": screen["implementation"]["compiled_semantic_contract"]["observation_abi"],
    "compiled_observation_version": screen["implementation"]["compiled_semantic_contract"]["observation_version"],
    "compiled_action_abi": screen["implementation"]["compiled_semantic_contract"]["action_abi"],
    "launcher_sha256": screen["implementation"]["launcher_sha256"],
    "status_wrapper_sha256": screen["implementation"]["status_wrapper_sha256"],
    "live_integrity_guard_sha256": screen["implementation"]["live_integrity_guard_sha256"],
    "checkpoint_lineage_sha256": screen["implementation"]["checkpoint_lineage_sha256"],
    "live_integrity_max_silence": str(
        screen["error_budget"]["max_panel_silence_seconds"]),
    "live_integrity_poll_seconds": str(
        screen["error_budget"]["detection_poll_seconds"]),
    "puffer_patch_bundle_sha256": screen["implementation"]["puffer_patch_bundle_sha256"],
    "vendor_head": screen["implementation"]["vendor_head"],
    "vendor_source_sha256": screen["implementation"]["vendor_source_sha256"],
    "historical_game_share": (
        "0" if screen["pool"] is None else screen["pool"]["historical_game_share"]),
    "frozen_bank_pct": screen["settings"]["frozen_bank_pct"],
    "num_frozen_banks": screen["settings"]["num_frozen_banks"],
    "expected_pool_hash": screen["settings"]["expected_pool_hash"],
    "warm_bytes": "0" if screen["warm"] is None else str(screen["warm"]["bytes"]),
    "checkpoint_interval": screen["derived"]["checkpoint_interval"],
}
if canary_launch is not None:
    authority = screen["canary_authority"]
    expected_contract.update({
        "canary_launch_authorization": canary_launch["launch_authorization"],
        "expected_canary_launch_authorization_sha256": canary_launch[
            "launch_authorization_sha256"],
        "canary_launch_consumption": canary_launch["launch_consumption"],
        "canary_launch_consumption_sha256": canary_launch[
            "launch_consumption_sha256"],
        "canary_qualification": authority["qualification"],
        "canary_qualification_sha256": authority["qualification_sha256"],
        "canary_launch_record": str(launch_record_path),
        "canary_launch_record_sha256": sha(launch_record_path),
        "expected_cuda_runtime_library_path": authority[
            "cuda_runtime_library_path"],
        "expected_cuda_runtime_library_sha256": authority[
            "cuda_runtime_library_sha256"],
        "expected_cuda_runtime_device_count": str(authority[
            "cuda_runtime_device_count"]),
    })
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
if screen["qualification_only"]:
    if run_manifest["warm"] or run_manifest["pool"]:
        raise SystemExit("fresh qualification run manifest contains warm/pool paths")
else:
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
detach = screen["settings"].get("arm_detach")
if detach not in ("0", "1"):
    raise SystemExit(f"screen has invalid arm_detach setting: {detach!r}")
expected_process_group = (
    int(process["pid"]) if detach == "1" else os.getpgrp()
)
if int(process["process_group"]) != expected_process_group:
    raise SystemExit(
        "trainer process group differs from the frozen containment contract: "
        f"{process['process_group']} != {expected_process_group}"
    )

final_steps = int(run_manifest["final_steps"])
if final_steps != int(screen["final_steps"]):
    raise SystemExit("run final step differs from frozen screen plan")
checkpoint = need_file(run_dir / f"{final_steps:016d}.bin", "exact final checkpoint")
expected_bytes = int(run_manifest["expected_checkpoint_bytes"])
if checkpoint.stat().st_size != expected_bytes:
    raise SystemExit(
        f"final checkpoint is {checkpoint.stat().st_size} bytes; expected {expected_bytes}")

from checkpoint_lineage import (
    lineage_digest, lineage_from_run_manifest, sidecar_path, validate_lineage,
    write_lineage,
)
lineage_payload = lineage_from_run_manifest(
    checkpoint, run_manifest_path, allow_eligible_publication=True)
lineage_path = sidecar_path(checkpoint)
lineage_sha = lineage_digest(lineage_payload)

integrity = HARD_INTEGRITY_KEYS
required = (
    "n", "tds", "perf", "possession_rate", "blocks_thrown",
    "block_2d_frac", "block_2dred_frac", *integrity,
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
    if not completed_game_requirement_met(observed, minimum):
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

if not failures:
    if mode == "write":
        write_lineage(lineage_path, lineage_payload)
    recorded_lineage = validate_lineage(
        checkpoint, lineage_path,
        expected={
            "source_sha256": screen["implementation"]["source_sha256"],
            "compiled_module_sha256": screen["implementation"]["compiled_module_sha256"],
            "puffer_patch_bundle_sha256": screen["implementation"]["puffer_patch_bundle_sha256"],
        },
        require_eligible=not screen["qualification_only"],
    )
    if recorded_lineage != lineage_payload:
        raise SystemExit("checkpoint lineage differs from recomputed run evidence")

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
    "run_manifest": str(run_manifest_path),
    "run_manifest_sha256": sha(run_manifest_path),
    "reward_sha256": expected_reward_sha,
    "checkpoint": str(checkpoint),
    "checkpoint_bytes": checkpoint.stat().st_size,
    "checkpoint_sha256": sha(checkpoint),
    "checkpoint_lineage": str(lineage_path),
    "checkpoint_lineage_sha256": lineage_sha,
    "qualification_only": screen["qualification_only"],
    "train_metrics": phase_metrics["train"],
    "eval_metrics": phase_metrics["eval"],
}
if canary_launch is not None:
    result.update({
        "canary_launch_record_sha256": sha(launch_record_path),
        "canary_launch_authorization_sha256": canary_launch[
            "launch_authorization_sha256"],
        "canary_launch_consumption": canary_launch["launch_consumption"],
        "canary_launch_consumption_sha256": canary_launch[
            "launch_consumption_sha256"],
        "canary_qualification_sha256": screen["canary_authority"][
            "qualification_sha256"],
        "expected_cuda_runtime_library_sha256": screen[
            "canary_authority"]["cuda_runtime_library_sha256"],
        "expected_cuda_runtime_device_count": screen[
            "canary_authority"]["cuda_runtime_device_count"],
    })
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

terminate_current_arm() {
  local pid=$1 process_group=$2
  if [ "$ARM_DETACH" = "1" ]; then
    kill -TERM -- "-$process_group" 2>/dev/null || true
  else
    # Queue-owned screens share the queue job's process group. Signal only the
    # recorded wrapper; its TERM trap forwards to the exact trainer child.
    kill -TERM "$pid" 2>/dev/null || true
  fi
  for _ in $(seq 1 40); do
    kill -0 "$pid" 2>/dev/null || return 0
    sleep 0.25
  done
  if [ "$ARM_DETACH" = "1" ]; then
    kill -KILL -- "-$process_group" 2>/dev/null || true
  else
    kill -KILL "$pid" 2>/dev/null || true
  fi
}

guard_complete_log() {
  local log=$1
  "$PYBIN" "$ROOT/tools/live_integrity_guard.py" \
    --log "$log" --state "${log}.live-integrity-screen-state.json" \
    --failure "$OUT_DIR/LIVE_INTEGRITY_FAILURE.json" \
    --complete-log \
    --max-panel-silence-seconds "$MAX_PANEL_SILENCE_SECONDS"
}

wait_for_status() {
  local tag=$1 log=$2
  local process="${log}.process.json"
  [ -f "$process" ] || {
    echo "missing process sidecar after launcher returned for $tag" >&2
    return 1
  }
  local pid process_group guard_state guard_failure
  read -r pid process_group < <($PYBIN - "$process" <<'PY'
import json, sys
payload = json.load(open(sys.argv[1], encoding="utf-8"))
print(int(payload["pid"]), int(payload["process_group"]))
PY
)
  # The durable watchdog is a redundant writer. Keep its incremental cursor
  # independent so overlapping polls cannot race or roll this cursor backward.
  guard_state="${log}.live-integrity-screen-state.json"
  guard_failure="$OUT_DIR/LIVE_INTEGRITY_FAILURE.json"
  while [ ! -f "${log}.status.json" ]; do
    if ! "$PYBIN" "$ROOT/tools/live_integrity_guard.py" \
        --log "$log" --state "$guard_state" --failure "$guard_failure" \
        --max-panel-silence-seconds "$MAX_PANEL_SILENCE_SECONDS"; then
      echo "hard-integrity error budget exhausted; terminating $tag" >&2
      terminate_current_arm "$pid" "$process_group"
      write_screen_status failed 1 "hard-integrity error budget exhausted"
      return 1
    fi
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
  guard_complete_log "$log"
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
    guard_complete_log "$log"
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
        BOOTSTRAP_MODE="$BOOTSTRAP_MODE" \
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
        DETACH="$ARM_DETACH" \
        QUEUE_OWNED="$([ "$ARM_DETACH" = "0" ] && printf 1 || printf 0)" \
        LIVE_INTEGRITY_FAILURE="$OUT_DIR/LIVE_INTEGRITY_FAILURE.json" \
        LIVE_INTEGRITY_MAX_SILENCE="$MAX_PANEL_SILENCE_SECONDS" \
        LIVE_INTEGRITY_POLL_SECONDS="$POLL_SECONDS" \
        EXPECTED_CUDA_RUNTIME_LIBRARY_PATH="$CANARY_CUDA_RUNTIME_LIBRARY_PATH" \
        EXPECTED_CUDA_RUNTIME_LIBRARY_SHA256="$CANARY_CUDA_RUNTIME_LIBRARY_SHA256" \
        EXPECTED_CUDA_RUNTIME_DEVICE_COUNT="$CANARY_CUDA_RUNTIME_DEVICE_COUNT" \
        CANARY_LAUNCH_AUTHORIZATION="$CANARY_LAUNCH_AUTHORIZATION_PATH" \
        CANARY_LAUNCH_AUTHORIZATION_SHA256="$CANARY_LAUNCH_AUTHORIZATION_SHA256" \
        CANARY_LAUNCH_CONSUMPTION="$CANARY_LAUNCH_CONSUMPTION_PATH" \
        CANARY_LAUNCH_CONSUMPTION_SHA256="$CANARY_LAUNCH_CONSUMPTION_SHA256" \
        CANARY_QUALIFICATION="$CANARY_QUALIFICATION_PATH" \
        CANARY_QUALIFICATION_SHA256="$CANARY_QUALIFICATION_SHA256" \
        CANARY_LAUNCH_RECORD="$CANARY_LAUNCH_RECORD" \
        CANARY_LAUNCH_RECORD_SHA256="$CANARY_LAUNCH_RECORD_SHA256" \
        /bin/bash "$ROOT/tools/run_reward_ablation.sh"
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
  # Covers clean detached recovery and closes any final-log race after the
  # wrapper's atomic status publication.
  guard_complete_log "$log"
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
        "checkpoint_lineage_sha256": result["checkpoint_lineage_sha256"],
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
