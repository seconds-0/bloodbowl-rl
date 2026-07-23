#!/usr/bin/env bash
# Run a paired native reward screen sequentially on one owned GPU.
# Seed 43 reverses seed 42's arm order to reduce time/order confounding.
#
# SCREEN_MANIFEST.json records the provenance a later analysis actually needs:
# the compiled obs-v5/exact-joint-v1 module identity, the complete reward
# manifest hashes, the Puffer patch bundle, and the warm/pool lineage. Each
# arm's acceptance evidence lands in <tag>.result.json. Restarting the screen is
# expected and safe: completed arms are re-validated, unfinished ones relaunch.
# Example (current possession/gain screen):
#   WARM=/abs/warm.bin POOL=/abs/pool STEPS=500000000 \
#     EXPECTED_POOL_HASH=<sha256> SCREEN_PROFILE=possession-gain \
#     PREFIX=possession-gain-v2 bash tools/run_reward_screen.sh
# Example (fresh pool-free exact-action canary before a long run):
#   STEPS=50000000 SCREEN_PROFILE=exact-action-canary \
#     PREFIX=exact-action-canary-50m bash tools/run_reward_screen.sh
set -euo pipefail

if [ $# -ne 0 ]; then
  echo "run_reward_screen.sh accepts configuration through named environment variables only" >&2
  exit 1
fi

LAUNCH_CWD="$PWD"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
: "${STEPS:?STEPS is required (explicit experiment budget)}"
: "${SCREEN_PROFILE:?SCREEN_PROFILE is required (distance-possession, possession-gain, possession-gain-exact, exact-action-canary, genesis, genesis-pool, paired-confirmation, paired-final, or control-final)}"
CANDIDATE_ARM="${CANDIDATE_ARM:-}"
TRANSFER_COMPLETE="${TRANSFER_COMPLETE:-}"
EXPECTED_TRANSFER_SHA256="${EXPECTED_TRANSFER_SHA256:-}"
PREFIX="${PREFIX:-reward-screen-v1}"
OUT_DIR="${OUT_DIR:-$ROOT/runs/reward-screens/$PREFIX}"
POLL_SECONDS="${POLL_SECONDS:-30}"
PLAN_ONLY="${PLAN_ONLY:-0}"
ARM_DETACH="${ARM_DETACH:-1}"

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
# Every arm this screen launches must discount at the SAME gamma its reward
# manifest claims for exact PBRS, or beta*(gamma*Phi' - Phi) is not exact and the
# distance channels quietly reacquire the bias the discounted form removes. The
# per-arm launcher asserts the pair (tools/run_reward_ablation.sh), but it only
# sees the gamma this script passes it, so a divergence here would be invisible:
# assert it once, up front, against every manifest the profile can select.
if ! python3 -c '
import json, pathlib, sys
root, gamma = pathlib.Path(sys.argv[1]), float(sys.argv[2])
bad = []
for m in sorted((root / "puffer/config/rewards").glob("*.json")):
    reward = json.loads(m.read_text(encoding="utf-8")).get("reward", {})
    claimed = reward.get("reward_dist_pbrs_gamma", 0.0)
    if claimed and abs(float(claimed) - gamma) > 1e-9:
        bad.append(f"{m.name} claims {claimed}")
if bad:
    print("; ".join(bad))
    sys.exit(1)
' "$ROOT" "$GAMMA" 2>/dev/null; then
  echo "a reward manifest declares an exact-PBRS gamma other than $GAMMA;" >&2
  echo "  the distance channels would not be exact PBRS under this screen" >&2
  exit 1
fi
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
  distance-possession|possession-gain|possession-gain-exact|exact-action-canary|genesis|genesis-pool|control-final)
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
  *) echo "SCREEN_PROFILE must be distance-possession, possession-gain, possession-gain-exact, exact-action-canary, genesis, genesis-pool, paired-confirmation, paired-final, or control-final" >&2
     exit 1 ;;
esac

if [ "$SCREEN_PROFILE" = "exact-action-canary" ] || \
   [ "$SCREEN_PROFILE" = "genesis" ] || \
   [ "$SCREEN_PROFILE" = "genesis-pool" ]; then
  # D217/D218: v4 and v5 have the same tensor sizes. An inherited or explicitly
  # empty legacy variable must not silently authorize a same-size warm/pool.
  [ "${WARM+x}" != x ] || {
    echo "$SCREEN_PROFILE forbids WARM; qualification uses fresh obs-v5 initialization" >&2
    exit 1
  }
  [ "${POOL+x}" != x ] || {
    echo "$SCREEN_PROFILE forbids POOL; it trains fresh obs-v5 self-play" >&2
    exit 1
  }
  WARM=""
  POOL=""
  if [ "$SCREEN_PROFILE" = "genesis" ] || [ "$SCREEN_PROFILE" = "genesis-pool" ]; then
    # Same fresh, pool-free shape as the canary; the difference is that an
    # accepted genesis arm publishes ELIGIBLE lineage, which is what lets any
    # later warm/pool profile exist at all. See the mode comment in
    # tools/run_reward_ablation.sh for why this cannot be avoided.
    BOOTSTRAP_MODE=fresh-v5-genesis
  else
    BOOTSTRAP_MODE=fresh-v5-qualification
  fi
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
  [[ "$EXPECTED_POOL_HASH" =~ ^[0-9a-f]{64}$ ]] || {
    echo "lineage-v5 screen requires the explicit current EXPECTED_POOL_HASH as a lowercase SHA-256 digest" >&2
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
/bin/bash "$ROOT/tools/install_puffer_env.sh" --check "$ROOT/vendor/PufferLib"

case "$SCREEN_PROFILE" in
  distance-possession)
    arms=(r0 r3 r1 r2 r2 r1 r3 r0)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  possession-gain)
    # LEGACY: these four arms are schema-1 manifests carrying the farmable
    # raw-delta distance form, so a contrast between them is confounded by how
    # much each component subsidises the distance exploit. Retained only so
    # historical curves stay reproducible; use possession-gain-exact for new work.
    arms=(both neither possession_only gain_only \
          gain_only possession_only neither both)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  possession-gain-exact)
    # The same 2x2 on corrected semantics: exact PBRS distance in all four arms
    # and a symmetric ball-gain family. Seed 43 reverses seed 42's arm order to
    # reduce time/order confounding, exactly as the legacy profile does.
    arms=(s_both s_neither s_possession_only s_gain_only \
          s_gain_only s_possession_only s_neither s_both)
    seeds=(42 42 42 42 43 43 43 43)
    ;;
  exact-action-canary)
    # Qualification only: one reward-frozen arm bounds repaired-runtime
    # exposure before any causal screen receives a long budget.
    arms=(both)
    seeds=(42)
    ;;
  genesis-pool)
    # Mint the four independent roots a lineage-v5 pool needs. Same reward and
    # recipe as `genesis`, four times, differing only by learner seed.
    #
    # Seeds are 1042-1045, NOT 42-44: those alias paired-final's seed block, and
    # a pool bank sharing a seed with a later confirmation arm invites reading a
    # coincidence as a result.
    #
    # This is a SEED-DIVERSE bootstrap pool, not a curated one. The doctrine's
    # curated composition (weak anchor, era specialist, older ratchet, latest cap)
    # cannot exist yet -- there is no history to draw from. Four from-scratch
    # policies differ by noise alone, which is the correct way to START a ladder
    # and must never later be described as curated. Replace banks as stronger
    # checkpoints appear, and do not read first-generation bank strength as
    # evidence about reward quality.
    arms=(s_both s_both s_both s_both)
    seeds=(1042 1043 1044 1045)
    ;;
  genesis)
    # One fresh arm on the CORRECTED reward, whose accepted
    # checkpoint becomes the root of the obs-v5 lineage. One arm and one seed on
    # purpose: this establishes ancestry, it does not compare anything, so a
    # second arm would only invite reading a contrast that was never controlled.
    # Deliberately `s_both`, the corrected decomposition baseline. Two rewards
    # were rejected for this role: `both` maps to r0_full, whose distance shaping
    # is the farmable raw-delta form, and `pbrs` (r4) fixes distance but still
    # ships reward_ball_loss 0.0 against reward_ball_gain 0.05, violating the
    # invariant stated in bloodbowl.h. A root cannot be corrected after the fact --
    # every descendant that warm-starts from it inherits its habits -- so it gets
    # the reward with no known defect, not merely the newest one.
    arms=(s_both)
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
    # Genesis roots the lineage, so it trains on the CORRECTED distance form
    # rather than the legacy ratchet. r4 differs from r0_full in exactly one
    # declared factor, reward_dist_pbrs_gamma.
    pbrs) printf '%s\n' "$ROOT/puffer/config/rewards/r4_pbrs_distance.json" ;;
    # The corrected decomposition 2x2. All four carry the exact PBRS distance
    # form, so the possession/gain contrast is not confounded by the farmable
    # raw-delta shaping, and the ball-gain family is a symmetric gain/loss pair.
    s_both) printf '%s\n' "$ROOT/puffer/config/rewards/s0_both.json" ;;
    s_possession_only) printf '%s\n' "$ROOT/puffer/config/rewards/s1_possession_only.json" ;;
    s_gain_only) printf '%s\n' "$ROOT/puffer/config/rewards/s2_gain_only.json" ;;
    s_neither) printf '%s\n' "$ROOT/puffer/config/rewards/s3_neither.json" ;;
    possession_only) printf '%s\n' "$ROOT/puffer/config/rewards/p1_possession_only.json" ;;
    gain_only) printf '%s\n' "$ROOT/puffer/config/rewards/p2_gain_only.json" ;;
    neither) printf '%s\n' "$ROOT/puffer/config/rewards/r2_no_possession.json" ;;
    *) echo "unknown arm: $1" >&2; return 1 ;;
  esac
}

# The bash arm/seed schedule above is the single definition; the manifest writer
# receives it rather than restating it in Python.
SCHEDULE=()
for index in "${!arms[@]}"; do
  SCHEDULE+=("${arms[$index]}:${seeds[$index]}:$(manifest_for "${arms[$index]}")")
done
SCHEDULE_TEXT="$(printf '%s\n' "${SCHEDULE[@]}")"

# One provenance record per screen: what trained, on which reward manifests,
# from which ancestry. The PPO knobs above are not mirrored here; the per-arm
# launcher writes them into every run manifest, which each result hashes.
# Command substitution, not process substitution: a failed provenance check has
# to fail the screen.
SCREEN_PLAN="$(
  env ROOT="$ROOT" PREFIX="$PREFIX" STEPS="$STEPS" OUT_DIR="$OUT_DIR" \
      SCREEN_PROFILE="$SCREEN_PROFILE" BOOTSTRAP_MODE="$BOOTSTRAP_MODE" \
      CANDIDATE_ARM="$CANDIDATE_ARM" TRANSFER_COMPLETE="$TRANSFER_COMPLETE" \
      EXPECTED_TRANSFER_SHA256="$EXPECTED_TRANSFER_SHA256" \
      WARM="$WARM" POOL="$POOL" EXPECTED_POOL_HASH="$EXPECTED_POOL_HASH" \
      SCHEDULE="$SCHEDULE_TEXT" POLL_SECONDS="$POLL_SECONDS" \
      MAX_PANEL_SILENCE_SECONDS="$MAX_PANEL_SILENCE_SECONDS" \
      TOTAL_AGENTS="$TOTAL_AGENTS" HORIZON="$HORIZON" \
      MINIBATCH_SIZE="$MINIBATCH_SIZE" EXPECT_BYTES="$EXPECT_BYTES" \
      FROZEN_BANK_PCT="$FROZEN_BANK_PCT" \
      NUM_FROZEN_BANKS="$NUM_FROZEN_BANKS" \
      MIN_TRAIN_GAMES="$MIN_TRAIN_GAMES" MIN_EVAL_GAMES="$MIN_EVAL_GAMES" \
      "$PYBIN" - "$SCREEN_MANIFEST" <<'PY'
import datetime, hashlib, json, os, pathlib, subprocess, sys, sysconfig

destination = pathlib.Path(sys.argv[1])
root = pathlib.Path(os.environ["ROOT"]).resolve()
vendor = root / "vendor" / "PufferLib"
profile = os.environ["SCREEN_PROFILE"]
qualification_only = profile == "exact-action-canary"
expect_size = int(os.environ["EXPECT_BYTES"])
warm = pathlib.Path(os.environ["WARM"]).resolve() if os.environ["WARM"] else None
pool = pathlib.Path(os.environ["POOL"]).resolve() if os.environ["POOL"] else None
sys.path.insert(0, str(root / "tools"))
from reward_manifest import load_manifest
from live_integrity_guard import HARD_INTEGRITY_KEYS


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def bundle_sha(paths, labels):
    return hashlib.sha256(b"".join(
        f"{sha(path)}  {label}\n".encode()
        for path, label in zip(paths, labels))).hexdigest()


# obs-v4 and obs-v5 observations are both 2782 bytes, so only source and
# compiled-module provenance can tell them apart; one mixup already wasted a
# 12B-step run.
environment_header = root / "puffer/bloodbowl/bloodbowl.h"
if "#define BBE_OBS_VERSION 5" not in environment_header.read_text(
        encoding="utf-8"):
    raise SystemExit("source tree does not declare obs-v5")
source_hash_path = vendor / "ocean/bloodbowl/.content_hash"
if not source_hash_path.is_file():
    raise SystemExit("installed Blood Bowl content hash is missing")
source_hash = source_hash_path.read_text(encoding="utf-8").strip()

# The imported _C, not the source tree, is what will actually train.
extension_suffix = sysconfig.get_config_var("EXT_SUFFIX")
if not extension_suffix:
    raise SystemExit("Python did not report an extension-module suffix")
module = vendor / "pufferlib" / ("_C" + extension_suffix)
if not module.is_file():
    raise SystemExit(f"current-Python compiled _C module is missing: {module}")
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
    raise SystemExit("imported native module differs from the probed module path")
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
        "compiled native module does not satisfy the obs-v5/exact-action contract")

# The per-arm launcher recomputes this bundle digest and refuses to train if it
# drifts, so the screen only has to publish the value it launched with.
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
patch_bundle_sha = bundle_sha(patches, [str(path) for path in patches])
vendor_source_sha = bundle_sha(vendor_paths, vendor_sources)
vendor_head_result = subprocess.run(
    ["git", "-C", str(vendor), "rev-parse", "HEAD"],
    text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, check=False)
vendor_head = (vendor_head_result.stdout.strip()
               if vendor_head_result.returncode == 0 else "<not-a-git-checkout>")

# load_manifest rejects an incomplete reward manifest: an omitted field is not
# the same as an explicit zero.
schedule = []
rewards = {}
for index, entry in enumerate(os.environ["SCHEDULE"].splitlines(), 1):
    arm, seed, reward_path = entry.split(":", 2)
    schedule.append({"index": index, "arm": arm, "seed": int(seed)})
    if arm not in rewards:
        reward, digest = load_manifest(reward_path)
        rewards[arm] = {
            "path": str(pathlib.Path(reward_path).resolve()),
            "name": reward["name"], "reward_sha256": digest,
            "file_sha256": sha(reward_path),
        }

rollout_quantum = int(os.environ["TOTAL_AGENTS"]) * int(os.environ["HORIZON"])
train_epochs = int(os.environ["STEPS"]) // rollout_quantum
if train_epochs <= 0:
    raise SystemExit("screen STEPS is smaller than one rollout quantum")
final_steps = train_epochs * rollout_quantum

warm_identity = None
pool_identity = None
warm_lineage_sha = ""
pool_lineage_bundle_sha = ""
# Branch on whether this screen is FRESH, not on whether it is
# qualification-only. Those were the same condition until genesis existed: a
# genesis screen is fresh (no warm start, no pool -- it is the root of the
# lineage) yet deliberately NOT qualification-only, because its accepted
# checkpoint is eligible ancestry. Keying the warm/pool binding off
# qualification_only sent genesis down the warm-start path and called .stat() on
# None. This whole fresh branch had never executed before: the canary profile was
# hard-rejected earlier in this script, so no fresh screen could reach here.
fresh = warm is None and pool is None
if warm is None or pool is None:
    if not fresh:
        raise SystemExit(
            "a fresh screen must carry neither a warm start nor a pool; got "
            f"warm={warm} pool={pool}")
else:
    from checkpoint_lineage import lineage_digest, sidecar_path, validate_lineage
    if warm.stat().st_size != expect_size:
        raise SystemExit(
            f"warm checkpoint is {warm.stat().st_size} bytes; expected {expect_size}")
    # The lineage sidecar is the only thing that keeps an obs-v4 checkpoint out
    # of an obs-v5 run. The per-arm launcher validates the four pool banks the
    # same way, against the same expectations, before it allocates GPU state.
    warm_payload = validate_lineage(
        warm, sidecar_path(warm),
        expected={
            "source_sha256": source_hash,
            "compiled_module_sha256": sha(module),
            "puffer_patch_bundle_sha256": patch_bundle_sha,
        },
        require_eligible=True)
    warm_lineage_sha = lineage_digest(warm_payload)
    warm_identity = {
        "path": str(warm), "bytes": warm.stat().st_size, "sha256": sha(warm),
        "lineage_path": str(sidecar_path(warm).resolve()),
        "lineage_sha256": warm_lineage_sha,
    }
    pool_manifest_raw = (pool / "league_seeds.json").read_bytes()
    banks = json.loads(pool_manifest_raw).get("seeds")
    if not isinstance(banks, list) or len(banks) != 4:
        raise SystemExit("screen pool must contain exactly four banks")
    pool_lineage_bundle_sha = hashlib.sha256(json.dumps([
        {"bank": index, "checkpoint_sha256": bank["sha256"],
         "lineage_sha256": bank["lineage_sha256"]}
        for index, bank in enumerate(banks)
    ], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    pool_identity = {
        "path": str(pool),
        "manifest_sha256": hashlib.sha256(pool_manifest_raw).hexdigest(),
        "identity_sha256": os.environ["EXPECTED_POOL_HASH"],
        "lineage_bundle_sha256": pool_lineage_bundle_sha,
    }

launcher = root / "tools/run_reward_ablation.sh"
screen_script = root / "tools/run_reward_screen.sh"
game_stats = root / "tools/game_stats.py"
live_integrity_guard = root / "tools/live_integrity_guard.py"
checkpoint_lineage_tool = root / "tools/checkpoint_lineage.py"
status_wrapper = root / "tools/trainer_status_wrapper.sh"
contract = {
    "screen_profile": profile,
    "qualification_only": qualification_only,
    "prefix": os.environ["PREFIX"],
    "out_dir": str(pathlib.Path(os.environ["OUT_DIR"]).resolve()),
    "requested_steps": int(os.environ["STEPS"]),
    "final_steps": final_steps,
    "rollout_quantum": rollout_quantum,
    "schedule": schedule,
    "rewards": rewards,
    "warm": warm_identity,
    "pool": pool_identity,
    "bootstrap": {
        "mode": os.environ["BOOTSTRAP_MODE"],
        "observation_abi": "obs-v5",
        "observation_version": 5,
        "action_abi": "exact-joint-v1",
        # Genesis is fresh yet not qualification-only, so this must key on
        # freshness. checkpoint_lineage cross-checks initialization against the
        # producer mode, so getting this wrong fails the run at publication.
        "initialization": "fresh" if fresh else "lineage-v5",
        "warm_lineage_sha256": warm_lineage_sha,
        "pool_lineage_bundle_sha256": pool_lineage_bundle_sha,
    },
    # Batching, architecture, and acceptance floors: the values an analysis has
    # to know to read the arms it is comparing.
    "settings": {
        "total_agents": os.environ["TOTAL_AGENTS"],
        "horizon": os.environ["HORIZON"],
        "minibatch_size": os.environ["MINIBATCH_SIZE"],
        "expected_checkpoint_bytes": os.environ["EXPECT_BYTES"],
        "frozen_bank_pct": os.environ["FROZEN_BANK_PCT"],
        "num_frozen_banks": os.environ["NUM_FROZEN_BANKS"],
        "min_train_games": os.environ["MIN_TRAIN_GAMES"],
        "min_eval_games": os.environ["MIN_EVAL_GAMES"],
        "eval_episodes": os.environ["MIN_EVAL_GAMES"],
        "native_precision_bytes": "4",
        "policy_hidden_size": "512",
        "policy_num_layers": "3",
        "policy_expansion_factor": "1",
    },
    "error_budget": {
        "contamination_budget": 0,
        "detection_poll_seconds": int(os.environ["POLL_SECONDS"]),
        "max_panel_silence_seconds": int(
            os.environ["MAX_PANEL_SILENCE_SECONDS"]),
        "hard_integrity_keys": list(HARD_INTEGRITY_KEYS),
    },
    # Which version of the tooling produced this screen. Recorded, not policed:
    # editing game_stats.py mid-screen is a bug to notice in review, not
    # something worth refusing to resume a multi-day run over.
    "implementation": {
        "screen_script_sha256": sha(screen_script),
        "launcher_sha256": sha(launcher),
        "game_stats_sha256": sha(game_stats),
        "live_integrity_guard_sha256": sha(live_integrity_guard),
        "checkpoint_lineage_sha256": sha(checkpoint_lineage_tool),
        "status_wrapper_sha256": sha(status_wrapper),
        "source_sha256": source_hash,
        "compiled_module": str(module.resolve()),
        "compiled_module_sha256": sha(module),
        "compiled_semantic_contract": compiled_contract,
        "puffer_patch_bundle_sha256": patch_bundle_sha,
        "vendor_head": vendor_head,
        "vendor_source_sha256": vendor_source_sha,
    },
}
if profile in ("paired-confirmation", "paired-final"):
    from analyze_reward_candidate_transfer import (
        TransferError, validate_completion_evidence,
    )
    contract["candidate_arm"] = os.environ["CANDIDATE_ARM"]
    # Binds recommended_confirmation_arm, the analysis recommendation,
    # transfer_manifest_sha256, analysis_sha256, and the evaluated cell hashes,
    # so a confirmation cannot quietly run an arm the transfer study rejected.
    try:
        contract["candidate_evidence"] = validate_completion_evidence(
            pathlib.Path(os.environ["TRANSFER_COMPLETE"]).resolve(),
            expected_complete_sha=os.environ["EXPECTED_TRANSFER_SHA256"],
            expected_candidate=os.environ["CANDIDATE_ARM"],
        )
    except (OSError, TransferError, ValueError) as exc:
        raise SystemExit(f"invalid candidate transfer evidence: {exc}") from exc

# A retried screen reuses the plan it already published so its accepted arms
# keep one manifest identity.
if not destination.exists():
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps({
        "schema_version": 1,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "contract": contract,
    }, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(destination)
print(sha(destination), patch_bundle_sha)
PY
)"
read -r SCREEN_MANIFEST_SHA SCREEN_PATCH_BUNDLE_SHA <<<"$SCREEN_PLAN"
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
write_screen_status running 0 "screen plan published; validating or launching arms"

materialize_result() {
  local mode=$1 arm=$2 seed=$3 tag=$4 manifest_path=$5 log=$6 result=$7
  "$PYBIN" - "$ROOT" "$mode" "$arm" "$seed" "$tag" "$manifest_path" \
    "$log" "$result" "$SCREEN_MANIFEST" "$SCREEN_MANIFEST_SHA" \
    "$MIN_TRAIN_GAMES" "$MIN_EVAL_GAMES" "$ARM_DETACH" <<'PY'
import hashlib, json, os, pathlib, sys
(
    root, mode, arm, seed, tag, reward_manifest_path, log_path, result_path,
    screen_manifest_path, screen_manifest_sha, min_train_games, min_eval_games,
    detach,
) = sys.argv[1:]
root = pathlib.Path(root).resolve()
sys.path.insert(0, str(root / "tools"))
from game_stats import (
    completed_game_requirement_met,
    dashboard_windows,
    weighted_dashboard,
)
from reward_manifest import load_manifest
from live_integrity_guard import HARD_INTEGRITY_KEYS
from checkpoint_lineage import (
    lineage_digest, lineage_from_run_manifest, sidecar_path, validate_lineage,
    write_lineage,
)


def sha(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def need_file(path, label):
    path = pathlib.Path(path)
    if not path.is_file():
        raise SystemExit(f"missing {label}: {path}")
    return path


screen = json.loads(need_file(
    screen_manifest_path, "screen manifest").read_text(encoding="utf-8"))["contract"]
log = need_file(log_path, "trainer log")
status_path = need_file(log_path + ".status.json", "trainer status")
process_path = need_file(log_path + ".process.json", "trainer process sidecar")
run_dir_path = need_file(log_path + ".run_dir", "run-directory sidecar")
run_manifest_path = need_file(log_path + ".manifest.json", "run manifest")

run_dir = pathlib.Path(run_dir_path.read_text(encoding="utf-8").strip())
if not run_dir.is_absolute() or not run_dir.is_dir():
    raise SystemExit(f"invalid run directory: {run_dir}")
# Accept a final checkpoint only out of this checkout's trainer output, never a
# production or stale run directory that happens to hold the same step number.
checkpoint_root = (root / "vendor/PufferLib/checkpoints/bloodbowl").resolve()
try:
    run_dir.resolve().relative_to(checkpoint_root)
except ValueError as exc:
    raise SystemExit(
        f"run directory is outside {checkpoint_root}: {run_dir}") from exc
run_manifest = json.loads(run_manifest_path.read_text(encoding="utf-8"))
_, expected_reward_sha = load_manifest(reward_manifest_path)
if run_manifest.get("reward_sha256") != expected_reward_sha:
    raise SystemExit(
        f"arm {tag} trained reward {run_manifest.get('reward_sha256')}, "
        f"not this arm's {expected_reward_sha}")

status = json.loads(status_path.read_text(encoding="utf-8"))
process = json.loads(process_path.read_text(encoding="utf-8"))
if int(status["exit_code"]) != 0:
    raise SystemExit(f"trainer status is {status['exit_code']}")
if int(status["pid"]) != int(process["pid"]):
    raise SystemExit("trainer status PID differs from process sidecar")
# ARM_DETACH=0 keeps the trainer inside the queue job's process group; one that
# escapes survives the queue's cleanup and idle-bills the GPU.
expected_process_group = int(process["pid"]) if detach == "1" else os.getpgrp()
if int(process["process_group"]) != expected_process_group:
    raise SystemExit(
        "trainer process group differs from the containment contract: "
        f"{process['process_group']} != {expected_process_group}")

final_steps = int(run_manifest["final_steps"])
if final_steps != int(screen["final_steps"]):
    raise SystemExit("run final step differs from the screen plan")
checkpoint = need_file(run_dir / f"{final_steps:016d}.bin", "exact final checkpoint")
expected_bytes = int(screen["settings"]["expected_checkpoint_bytes"])
if checkpoint.stat().st_size != expected_bytes:
    raise SystemExit(
        f"final checkpoint is {checkpoint.stat().st_size} bytes; expected {expected_bytes}")

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
path = pathlib.Path(result_path)
if mode == "validate":
    # Acceptance was just recomputed from the log above, so the recorded
    # sidecar only has to agree about the arm it accepted.
    recorded = json.loads(path.read_text(encoding="utf-8"))
    if recorded.get("acceptance_pass") is not True:
        raise SystemExit(f"recorded result is not an accepted arm: {path}")
    if recorded.get("checkpoint_sha256") != result["checkpoint_sha256"]:
        raise SystemExit(
            f"recorded result belongs to a different checkpoint: {path}")
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
destination = pathlib.Path(path)
# A published completion summary keeps its bytes, so a downstream analysis that
# pinned its hash still resolves after the screen is re-validated.
if not destination.exists():
    payload = {
        "schema_version": 1,
        "screen_manifest_sha256": manifest_sha,
        "results": results,
        "completed_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
    }
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
