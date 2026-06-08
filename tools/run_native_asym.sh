#!/usr/bin/env bash
# Launch a NATIVE ANCHOR-FREE ASYMMETRIC run (the production architecture,
# D57 / profile-v4-native-asym): native CUDA backend (NO --slowly, NO bc aux),
# learner vs a FROZEN teacher served from a 1-seed selfplay league pool. The
# teacher is provably immutable for the whole run (see PINNING KNOBS below;
# full proof in the 2026-06-08 pinning audit — every rotation trigger is
# unsatisfiable, so load_frozen_bank fires exactly once, at setup).
# Verified live at 2.1M SPS vs torch's 0.6M on box-1.
#
# Run ON the box from ~/bloodbowl-rl:  TAG=<name> bash tools/run_native_asym.sh
# (Mac checkouts have no CUDA build — this script refuses to launch off-box.)
#
# Contract (env vars; trailing args append LAST and override — puffer's CLI is
# last-wins, so trailing args are the override mechanism for the reward
# economy. The PINNING KNOBS are exempt: this script REFUSES trailing
# overrides of --selfplay.* / --vec.*frozen* because re-enabling teacher
# rotation silently invalidates the run):
#   TAG=<run tag>            REQUIRED. Also names the pool dir and default log.
#   TEACHER=<cuda blob>      flat-fp32 save_weights blob (NOT a torch
#                            state_dict — convert first:
#                            python training/convert_checkpoint.py --to-cuda
#                            bc_v4.bin -o bc_v4_cuda.bin   # obs-size 2782 default).
#                            Default training/bc_v4_cuda.bin. bc anchors live
#                            PER-BOX only (fleet.sh setup excludes
#                            training/*.bin) — ship box-to-box via ssh -A.
#   WARM=<cuda blob>         optional learner warm-start (--load-model-path).
#                            Same flat-fp32 format/size as TEACHER. Remember:
#                            newest mtime != highest step — read the step
#                            number in the checkpoint filename.
#   STEPS=<n>                total timesteps, default 30B. Asymmetric runs
#                            overshoot ~1.5x (known, benign).
#   LOG=<path>               default /tmp/$TAG.log
#   POOL=<dir>               league pool dir, default training/league_$TAG.
#                            Built/refreshed here from TEACHER every launch.
#   EXPECT_BYTES=<n>         teacher/warm blob size, default 16066560 = obs-v4
#                            policy (4,016,640 fp32 params). 13670400 = obs-v3
#                            lineage (input-shape INCOMPATIBLE), 12072960 =
#                            dead obs-832 lineage. Override only for a new arch.
#   SKIP_DRIFT_CHECK=1       skip the install_puffer_env.sh --check gate.
#
# Prereqs on the box (this script CHECKS or AUTO-FIXES every one of these —
# read its error messages before improvising):
#   - NATIVE build: vendor/PufferLib built WITHOUT --float (plain build =
#     bf16 native CUDA; --float is the torch/--slowly requirement and costs
#     the 4x SPS win). Probe:  cd vendor/PufferLib &&
#       python3 -c "from pufferlib import _C; print(_C.precision_bytes)"
#     -> 2 = native bf16 (correct), 4 = --float build (rebuild:
#       rm -rf build && ./build.sh bloodbowl     # NO --float, never skip rm).
#     (bindings.cu:509 exports sizeof(precision_t).)
#   - selfplay league patch applied (training/selfplay_league.patch — vendor/
#     is gitignored; lost on re-clone). Auto-reapplied below, same as
#     tools/run_league.sh. Without it selfplay.py IGNORES league_preseed and
#     bootstrap-clones the LEARNER into the bank — no teacher, run invalid.
#   - warm-start patch in vendored pufferl.py ('Warm-started training from';
#     see puffer-env-dev skill). Hard-required here when WARM is set.
#   - installed config/bloodbowl.ini has the league_preseed key (load_config
#     only accepts CLI args for keys present in the ini). Auto-refreshed.
#   - demo bank at vendor/PufferLib/resources/bloodbowl/state_bank.bbs
#     (a missing bank is SILENT — the env trains procgen-only).
set -euo pipefail
LAUNCH_CWD="$PWD"
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

: "${TAG:?TAG is required (run tag; also names the pool dir and log)}"
TEACHER="${TEACHER:-$ROOT/training/bc_v4_cuda.bin}"
STEPS="${STEPS:-30000000000}"
LOG="${LOG:-/tmp/${TAG}.log}"
POOL="${POOL:-$ROOT/training/league_${TAG}}"
EXPECT_BYTES="${EXPECT_BYTES:-16066560}"

# Relative paths would break after the cd below — anchor them to the
# invocation cwd now.
abspath() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s\n' "$LAUNCH_CWD/$1" ;; esac; }
TEACHER="$(abspath "$TEACHER")"
LOG="$(abspath "$LOG")"
POOL="$(abspath "$POOL")"
[ -n "${WARM:-}" ] && WARM="$(abspath "$WARM")"

# ---- guard: refuse trailing overrides of the pinning knobs ------------------
# Trailing args are last-wins by design (reward-economy overrides), but a
# trailing --selfplay.swap-winrate etc. would RE-ENABLE teacher rotation and
# silently invalidate the run. Economy/stage/train knobs pass through freely.
for a in "$@"; do
  case "$a" in
    --selfplay.*|--vec.num-frozen-banks*|--vec.frozen-bank-pct*)
      echo "refusing trailing arg '$a': it overrides a PINNING KNOB (teacher" >&2
      echo "immutability contract — see PINNING KNOBS comment). If you truly" >&2
      echo "want a rotating-opponent run, that is tools/run_league.sh, not this." >&2
      exit 1 ;;
  esac
done

# ---- guard: one trainer per box ([b]racket so pgrep can't match itself) ----
if pgrep -f 'puffer [t]rain' > /dev/null; then
  echo "a training run is already live on this box — kill it first:" >&2
  echo "  pkill -f 'puffer [t]rain'" >&2
  exit 1
fi

# ---- guard: this is a CUDA box, not the Mac checkout ------------------------
if ! command -v nvidia-smi >/dev/null 2>&1; then
  echo "no nvidia-smi — this launches a native CUDA training run and must run" >&2
  echo "ON a training box (/root/bloodbowl-rl), never the Mac checkout." >&2
  exit 1
fi

cd "$ROOT/vendor/PufferLib"
PYBIN="python3"
[ -x .venv/bin/python ] && PYBIN=".venv/bin/python"

# ---- guard: source-vs-snapshot drift (footgun: build compiles the snapshot,
# not your edit; a drifted puffer/bloodbowl means the .so may be stale) ----
if [ "${SKIP_DRIFT_CHECK:-0}" != "1" ]; then
  if ! bash "$ROOT/tools/install_puffer_env.sh" --check; then
    echo "puffer/bloodbowl drifted from the installed snapshot. Fix:" >&2
    echo "  bash $ROOT/tools/install_puffer_env.sh && cd $ROOT/vendor/PufferLib && rm -rf build && ./build.sh bloodbowl" >&2
    echo "(or SKIP_DRIFT_CHECK=1 if the drift is known-cosmetic)" >&2
    exit 1
  fi
fi

# ---- auto-fix: installed ini must carry the league_preseed key (load_config
# only accepts CLI args for keys present in the ini; the --check hash covers
# ocean/, not the ini) — same refresh as tools/run_league.sh ----
grep -q '^league_preseed' config/bloodbowl.ini || {
  echo "refreshing config/bloodbowl.ini (league_preseed key)"
  cp "$ROOT/puffer/config/bloodbowl.ini" config/bloodbowl.ini
}
grep -q '^league_preseed' config/bloodbowl.ini || {
  echo "config/bloodbowl.ini still lacks league_preseed — pull latest repo" >&2; exit 1; }

# ---- auto-fix: league preseed patch in the vendored selfplay.py (vendor/ is
# gitignored — a re-clone loses it; unpatched selfplay.py SILENTLY ignores
# league_preseed and banks the learner instead of the teacher) ----
if ! grep -q 'league_preseed' pufferlib/selfplay.py; then
  echo "applying training/selfplay_league.patch to vendored selfplay.py"
  git apply "$ROOT/training/selfplay_league.patch"
fi
grep -q 'league_preseed' pufferlib/selfplay.py || {
  echo "vendored selfplay.py still lacks league_preseed after git apply — fix by hand" >&2
  echo "(see .claude/skills/puffer-env-dev/SKILL.md)" >&2; exit 1; }

# ---- guard: WARM needs the warm-start patch in vendored pufferl.py ----------
# Without it --load-model-path is silently ignored and the learner starts
# FRESH (the 40s 'Warm-started' grep below is the runtime confirmation).
if [ -n "${WARM:-}" ] && ! grep -q 'Warm-started training from' pufferlib/pufferl.py; then
  echo "WARM is set but vendored pufferl.py lacks the warm-start patch" >&2
  echo "(fresh re-clone?) — reapply per .claude/skills/puffer-env-dev/SKILL.md" >&2
  exit 1
fi

# ---- guard: NATIVE bloodbowl GPU build (the .so WITHOUT --float) ------------
probe="$("$PYBIN" - <<'EOF' 2>/dev/null || true
from pufferlib import _C
print(getattr(_C, 'env_name', None), int(bool(getattr(_C, 'gpu', False))),
      int(_C.precision_bytes))
EOF
)"
read -r cenv cgpu prec <<< "${probe:-MISSING 0 0}"
if [ "$cenv" = "MISSING" ]; then
  echo "pufferlib._C not importable (python: $PYBIN) — not built? Build ON the box:" >&2
  echo "  bash $ROOT/tools/install_puffer_env.sh && cd $ROOT/vendor/PufferLib && rm -rf build && ./build.sh bloodbowl" >&2
  exit 1
elif [ "$cenv" != "bloodbowl" ]; then
  echo "_C is built for '$cenv', not bloodbowl — rebuild:  rm -rf build && ./build.sh bloodbowl" >&2
  exit 1
elif [ "$cgpu" != "1" ]; then
  echo "_C is a CPU build — the selfplay pool/frozen banks are CUDA-only; rebuild on the box" >&2
  exit 1
elif [ "$prec" = "4" ]; then
  echo "build is --float (precision_bytes=4): that's the torch/--slowly build — it forfeits the 4x SPS win." >&2
  echo "rebuild native:  cd $ROOT/vendor/PufferLib && rm -rf build && ./build.sh bloodbowl   # NO --float, never skip rm -rf build" >&2
  exit 1
elif [ "$prec" != "2" ]; then
  echo "unexpected _C.precision_bytes='$prec' (want 2 = native bf16) — investigate before launching" >&2
  exit 1
fi
echo "build: native bf16 bloodbowl GPU (_C.precision_bytes=2) — correct for this architecture"

# ---- guard: teacher blob (and optional warm blob) are sane cuda flats ------
# Why strict: pufferl_load_frozen_bank (src/pufferlib.cu:1830) only
# fprintf-warns on a size mismatch and SILENTLY KEEPS the bank's previous
# weights. The league manifest's expected_bytes (checked python-side in
# selfplay.py setup) plus these guards close that hole.
check_blob() { # $1=role $2=path
  [ -f "$2" ] || { echo "$1 blob missing: $2 (bc anchors are per-box — ship box-to-box via ssh -A)" >&2; exit 1; }
  if [ "$(head -c2 "$2")" = "PK" ]; then
    echo "$1 $2 is a zip (torch state_dict). Convert first:" >&2
    echo "  python $ROOT/training/convert_checkpoint.py --to-cuda $2 -o ${2%.bin}_cuda.bin" >&2
    exit 1
  fi
  local size; size=$(wc -c < "$2")
  if [ "$size" -ne "$EXPECT_BYTES" ]; then
    echo "$1 $2 is $size B, expected $EXPECT_BYTES (obs-v4 flat-fp32 unless EXPECT_BYTES overridden)." >&2
    echo "13670400 = obs-v3 lineage, 12072960 = dead obs-832 — both input-shape incompatible with obs-v4." >&2
    exit 1
  fi
  echo "$1: $2 ($size B)"
}
check_blob "teacher" "$TEACHER"
[ -z "${WARM:-}" ] || check_blob "warm" "$WARM"

# ---- guard: demo bank ----
BANK="resources/bloodbowl/state_bank.bbs"
[ -f "$BANK" ] || { echo "demo bank missing: $BANK (env would silently train procgen-only)" >&2; exit 1; }
bsize=$(wc -c < "$BANK")
[ "$bsize" -gt 1000000 ] || { echo "demo bank suspiciously small ($bsize B) — stale 401-replay bank?" >&2; exit 1; }
echo "bank: $BANK ($bsize B)"

# ---- build/refresh the 1-seed league pool (manifest = teacher's REAL size) -
# Layout consumed by the league_preseed branch (selfplay.py setup, local
# patch): $POOL/league_seeds.json + the seed blob it names. expected_bytes is
# written from the blob's actual byte size so the python-side check is exact.
mkdir -p "$POOL"
tbase="$(basename "$TEACHER")"
if [ "$(realpath "$TEACHER")" != "$(realpath "$POOL/$tbase" 2>/dev/null || echo /nonexistent)" ]; then
  cp -f "$TEACHER" "$POOL/$tbase"
fi
# Sweep dead learner snapshots from earlier (pre-suppression) attempts: with
# this script's pinned config, ANY 16-digit .bin here is dead weight — seeds
# are teacher-basename-named and sample_opponent never runs (audit issue 1/2;
# snapshots also collide across warm relaunches because global_step resets).
for f in "$POOL"/[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9].bin; do
  [ -e "$f" ] || continue
  [ "$(basename "$f")" = "$tbase" ] && continue   # never sweep the seed itself
  rm -f "$f" && echo "swept dead snapshot: $(basename "$f")"
done
"$PYBIN" - "$POOL" "$tbase" "$TEACHER" "$EXPECT_BYTES" <<'PY'
import datetime, hashlib, json, os, sys
pool, fname, source, expect = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
blob = open(os.path.join(pool, fname), 'rb').read()
assert len(blob) == expect, f'pool copy is {len(blob)} B, expected {expect}'
stem = fname[:-4] if fname.endswith('.bin') else fname
manifest = {
    'version': 1,
    'created': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'expected_bytes': len(blob),                  # REAL size of the blob
    'seeds': [{
        'bank': 0,
        'name': stem + '_frozen_teacher',
        'file': fname,
        'source': os.path.abspath(source),
        'bytes': len(blob),
        'sha256': hashlib.sha256(blob).hexdigest(),
    }],
}
with open(os.path.join(pool, 'league_seeds.json'), 'w') as f:
    json.dump(manifest, f, indent=2); f.write('\n')
print(f"pool: {pool} (1 seed: {fname}, sha256 {manifest['seeds'][0]['sha256'][:12]})")
PY

echo "tag=$TAG steps=$STEPS warm=${WARM:-<fresh>} log=$LOG"

# ---- launch -----------------------------------------------------------------
# PINNING KNOBS (the teacher-immutability contract — the trailing-arg guard
# above refuses overrides of any of these):
#   --selfplay.swap-winrate 1.1
#       per-game score is {1.0 win, 0.5 draw, 0.0 loss} (bloodbowl.h:1144),
#       so winrate <= 1.0 strictly; threshold 1.1 is UNSATISFIABLE — the
#       winrate swap (selfplay.py:295-297) can never fire.
#   --selfplay.opp-timeout-steps 100000000000
#       timeout swap (selfplay.py:298-300) needs 1e11 elapsed steps; the run
#       is 30B (~45B with the 1.5x overshoot) — never reached. Together these
#       leave pending_opp_path=None forever, so load_frozen_bank runs exactly
#       once, at setup, with the teacher. Eviction/Elo paths are bookkeeping
#       only and never touch bank weights (2026-06-08 pinning audit).
#   --selfplay.snapshot-interval 1000000000000
#       interval snapshots are pure dead weight under pinning (~150 x 16MB
#       into the pool dir over 30B otherwise, and warm relaunches reset
#       global_step so filenames collide across attempts). A huge interval
#       (not 0) suppresses them per the audit's guidance on the >0 gate at
#       selfplay.py:279.
#   --vec.num-frozen-banks 1
#       one bank = the teacher.
#   --vec.frozen-bank-pct 0.48
#       floor(2048 agents/buffer * 0.48) = 983 historical envs per buffer ->
#       96% of envs play learner-vs-teacher, 4% pure selfplay; 48% of agent
#       slots run the teacher (983 < apb/2 = 1024 hard cap, selfplay.py:160).
#       (team_size=1 here, so the python/C frozen-size alignment agrees
#       exactly; the audit's team_size>1 alignment caveat does not apply.)
# Architecture: NO --slowly (native CUDA backend), NO --train.bc-coef
# (anchor-free: the teacher shapes the learner only by being its opponent).
# Reward economy = settled v4 set (D42/D43/D46). ball-loss MUST stay 0 while
# the possession annuity is on (the loss-fine is measured poison). Override
# economy/stage knobs via trailing args (they append last and win).
WARM_ARGS=()
[ -n "${WARM:-}" ] && WARM_ARGS=(--load-model-path "$WARM")
# --- CPU thread cap (D59): cap BLAS/torch pools to the cgroup CPU quota, not
# the visible nproc. On shared boxes nproc can be 255 while the container
# only gets ~61 CPUs; unpinned, torch/OpenBLAS spawn nproc-wide pools and
# thrash (measured 5x SPS loss). The env-stepping OMP is independent (vec
# num_threads). Safe everywhere: caps to quota, never below 1.
_quota=0
if [ -r /sys/fs/cgroup/cpu.max ]; then            # cgroup v2
  read _q _p < /sys/fs/cgroup/cpu.max
  [ "$_q" != "max" ] && _quota=$(( _q / _p ))
fi
if [ "${_quota:-0}" -lt 1 ] && [ -r /sys/fs/cgroup/cpu/cpu.cfs_quota_us ]; then  # cgroup v1
  _q=$(cat /sys/fs/cgroup/cpu/cpu.cfs_quota_us); _p=$(cat /sys/fs/cgroup/cpu/cpu.cfs_period_us)
  [ "${_q:-0}" -gt 0 ] && _quota=$(( _q / _p ))
fi
[ "${_quota:-0}" -ge 1 ] || _quota=$(nproc)
[ "$_quota" -gt "$(nproc)" ] && _quota=$(nproc)
export OMP_NUM_THREADS="$_quota"
export OPENBLAS_NUM_THREADS="$_quota"
export MKL_NUM_THREADS="$_quota"
export NUMEXPR_NUM_THREADS="$_quota"
echo "cpu thread cap: $_quota (nproc=$(nproc), quota-derived)"

nohup puffer train bloodbowl --tag "$TAG" \
  --selfplay.enabled 1 \
  --selfplay.league-preseed "$POOL" \
  --selfplay.swap-winrate 1.1 \
  --selfplay.opp-timeout-steps 100000000000 \
  --selfplay.snapshot-interval 1000000000000 \
  --vec.num-frozen-banks 1 --vec.frozen-bank-pct 0.48 \
  ${WARM_ARGS[@]+"${WARM_ARGS[@]}"} \
  --env.reward-possession 0.03 --env.reward-ball-gain 0.05 --env.reward-ball-loss 0 \
  --env.reward-dist-ball 0.05 --env.reward-dist-endzone 0.2 \
  --env.reward-k-kd 0.03 --env.reward-k-value 0.25 --env.reward-k-ball 0.15 --env.reward-k-seq 0.01 \
  --env.demo-reset-pct 0.9 --env.demo-endzone-maxdist 9 \
  --train.total-timesteps "$STEPS" \
  "$@" > "$LOG" 2>&1 < /dev/null &
PID=$!
echo "LAUNCHED-PID-$PID log=$LOG"

# PROFILE marker for the spectator chip / run discovery. The trainer creates
# its run dir shortly after launch; tag the newest dir WITHOUT a marker (the
# run_league.sh pattern — a single-shot 'newest dir' write could land on a
# PREVIOUS run's dir and clobber its marker if the trainer is slow to start).
(
  for _ in $(seq 1 24); do
    sleep 10
    d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
    if [ -n "$d" ] && [ ! -e "${d}PROFILE" ]; then
      echo "native-asym ($TAG): native CUDA, anchor-free, frozen teacher $tbase" > "${d}PROFILE"
      break
    fi
  done
) &

# ---- liveness + sanity at 40s (read this before walking away) --------------
sleep 40
if ! kill -0 "$PID" 2>/dev/null; then
  echo "TRAINER DIED within 40s — tail of $LOG:" >&2
  tail -15 "$LOG" >&2
  exit 1
fi
# Any pufferl_load_frozen_bank stderr line = the C loader REFUSED the teacher
# and the bank holds garbage — the run is invalid even though it's alive.
if grep -a 'pufferl_load_frozen_bank' "$LOG" >&2; then
  echo "FROZEN-BANK LOAD FAILED (see above) — kill it: pkill -f 'puffer [t]rain'" >&2
  exit 1
fi
if [ -n "${WARM:-}" ] && ! grep -aq 'Warm-started' "$LOG"; then
  echo "WARNING: WARM was set but no 'Warm-started' line in $LOG — verify the learner actually warm-started" >&2
fi
grep -a 'Warm-started' "$LOG" | head -2 || true
echo "LIVE: pid $PID at 40s — teacher pinned from $POOL/$tbase"
echo "(if setup was still compiling at 40s, re-check later: grep -a pufferl_load_frozen_bank $LOG)"
