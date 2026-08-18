#!/usr/bin/env bash
# One campaign stage of the backplay ladder, resolved at launch time.
#
# Used as the `launch` command of a tools/campaign_supervisor.py stage. It
# resolves its own inputs from the previous stage's published artifacts, so the
# whole ladder (6 -> 9 -> 12 -> 0 -> kickoff) can be pre-authored as a plan
# even though no rung's checkpoint exists until the previous rung finishes:
#
#   WARM  = the previous rung's ACCEPTED checkpoint, read from its
#           LADDER_RUNG_COMPLETE.json (or an explicit WARM for the first rung);
#   POOL  = a fresh 4-bank league: the previous pool's newest three banks plus
#           the previous rung's accepted checkpoint, so opponent quality rises
#           one bank per rung and the oldest genesis root retires; the pool is
#           built once per stage under runs/<OUT>/pool and its identity is
#           published to POOL_IDENTITY.env, so a relaunch of the same stage
#           reuses it (build_league.py refuses to overwrite a non-empty pool).
#
# It then runs tools/launch_ladder_rung.sh, which drives the ladder-rung screen
# profile: eligible lineage sidecar on acceptance, live integrity guard,
# atomic result, LADDER_RUNG_COMPLETE.json as the stage's success artifact.
#
# Required:
#   RUNG=<maxdist>   RESET_PCT=<frac>   SEED=<int>   STAMP=<yyyymmdd-ish>
#   PREV_COMPLETE=<path to previous rung's LADDER_RUNG_COMPLETE.json>
#     -- or, for the first rung, WARM=<eligible ckpt> and PREV_POOL=<pool dir>
#   PREV_POOL=<previous pool dir>  (defaults to dirname of PREV_COMPLETE's pool)
# Optional:
#   PIN (git ref to fetch+checkout, default: current HEAD, no checkout)
#   STEPS (default 5000000000)  C (checkout root)  DEADLINE_HOURS
#   POOL_KEEP=<n> newest banks kept from PREV_POOL (default 3)
#   SCRIPTED_BANK_TAG / SCRIPTED_BOT_TYPE  scripted bank for this rung
#     (forwarded to launch_ladder_rung.sh only when set; unset = ordinary rung)
#   LADDER_PROFILE=graft + GRAFT_FROM_SOURCE_SHA256 / GRAFT_FROM_PATCH_BUNDLE_SHA256
#     / GRAFT_REASON  make this stage the reviewed lineage bridge across a
#     build change (forwarded like SCRIPTED_*; unset = ordinary rung)
set -uo pipefail

C="${C:-/home/rache/bloodbowl-rl-qualification-candidate-10619e2}"
cd "$C" || exit 1
export PATH="$C/vendor/PufferLib/.venv/bin:$PATH"
export RIG_ALLOW_FLOAT=1
export CUDA_VISIBLE_DEVICES=0

: "${RUNG:?RUNG is required}"
: "${RESET_PCT:?RESET_PCT is required}"
: "${SEED:?SEED is required}"
: "${STAMP:?STAMP is required}"
STEPS="${STEPS:-5000000000}"
POOL_KEEP="${POOL_KEEP:-3}"
PREV_COMPLETE="${PREV_COMPLETE:-}"
PREV_POOL="${PREV_POOL:-}"
WARM="${WARM:-}"
PIN="${PIN:-}"

if [ -n "$PIN" ]; then
  echo "=== sync to $PIN ==="
  git fetch -q origin || exit 1
  git checkout -q -f "$PIN" || exit 1
fi
git log --oneline -1

# The stage must never train on a stale or drifted install. It does NOT
# rebuild: a rebuild while a sibling process imports _C is footgun 3, and the
# campaign's first stage is where a deliberate rebuild belongs.
bash tools/install_puffer_env.sh --check || {
  echo "drift check failed; refusing to run on a stale build" >&2; exit 1; }

OUT="$C/runs/ladder-d${RUNG}-${STAMP}"
mkdir -p "$OUT"

# --- resolve WARM and the previous pool -----------------------------------
if [ -n "$PREV_COMPLETE" ]; then
  [ -f "$PREV_COMPLETE" ] || { echo "missing PREV_COMPLETE: $PREV_COMPLETE" >&2; exit 1; }
  read -r WARM PREV_POOL_FROM_MARKER < <(python3 - "$PREV_COMPLETE" <<'PY'
import json, os, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
if d.get("trainer_exit") != 0 or "checkpoint_lineage_sha256" not in d:
    raise SystemExit("previous rung marker is not an accepted screen result")
# The pool the previous rung trained against lives next to its result; the
# marker records only its identity hash, so the stage passes PREV_POOL
# explicitly when it differs. Fall back to the sibling pool dir if present.
prev_out = os.path.dirname(os.path.abspath(sys.argv[1]))
pool = os.path.join(prev_out, "pool")
print(d["checkpoint"], pool if os.path.isdir(pool) else "")
PY
  ) || exit 1
  [ -n "$PREV_POOL" ] || PREV_POOL="$PREV_POOL_FROM_MARKER"
fi
: "${WARM:?WARM could not be resolved (set WARM or PREV_COMPLETE)}"
: "${PREV_POOL:?PREV_POOL could not be resolved}"
[ -f "$WARM" ] || { echo "missing warm checkpoint: $WARM" >&2; exit 1; }
[ -f "$WARM.lineage.json" ] || { echo "warm has no lineage sidecar: $WARM" >&2; exit 1; }
[ -f "$PREV_POOL/league_seeds.json" ] || { echo "no league_seeds.json in $PREV_POOL" >&2; exit 1; }

# --- build (or reuse) this rung's pool ------------------------------------
POOL_OUT="$OUT"
if [ -z "$PREV_COMPLETE" ] && [ ! -f "$POOL_OUT/POOL_IDENTITY.env" ]; then
  # First rung of a chain: there is no previous rung to promote into the pool,
  # so train against PREV_POOL exactly as published (the genesis pool).
  echo "=== first rung: reusing $PREV_POOL as-is ==="
  ln -sfn "$PREV_POOL" "$POOL_OUT/pool"
  ( cd "$PREV_POOL/.." && cat POOL_IDENTITY.env ) > "$POOL_OUT/POOL_IDENTITY.env" \
    || { echo "PREV_POOL has no published POOL_IDENTITY.env beside it" >&2; exit 1; }
fi
if [ -f "$POOL_OUT/POOL_IDENTITY.env" ]; then
  echo "=== reusing published pool for this stage ==="
else
  echo "=== building pool: newest $POOL_KEEP of $PREV_POOL + warm ==="
  mapfile -t SEEDS < <(python3 - "$PREV_POOL" "$WARM" "$POOL_KEEP" "$RUNG" <<'PY'
import json, os, sys
prev_pool, warm, keep, rung = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
m = json.load(open(os.path.join(prev_pool, "league_seeds.json"), encoding="utf-8"))
banks = m["seeds"]
kept = banks[-keep:]
warm_real = os.path.realpath(warm)
out = []
for b in kept:
    src = b["source"]
    if os.path.realpath(src) == warm_real:
        # The warm checkpoint is already a bank (a chained restart at the same
        # rung); keep the pool identical rather than duplicating it.
        continue
    out.append(f"{b['name']}={src}")
# The new bank is the previous rung's accepted checkpoint == this rung's warm.
name = f"rung{rung}warm"
names = {o.split('=')[0] for o in out}
i = 0
while name in names:
    i += 1
    name = f"rung{rung}warm{i}"
out.append(f"{name}={warm}")
if len(out) != 4:
    # Pad from the older end of the previous pool if the warm was already a bank.
    for b in reversed(banks[:-keep] if keep < len(banks) else []):
        if len(out) >= 4:
            break
        if os.path.realpath(b["source"]) != warm_real and b["name"] not in names:
            out.insert(0, f"{b['name']}={b['source']}")
if len(out) != 4:
    raise SystemExit(f"could not compose exactly four banks: {out}")
print("\n".join(out))
PY
  ) || exit 1
  python tools/build_league.py --out "$POOL_OUT" --seeds "${SEEDS[@]}" \
    | tee "$POOL_OUT/build_league.out" || { echo "BUILD_LEAGUE FAILED" >&2; exit 1; }
  grep -oE "EXPECTED_POOL_HASH=[a-f0-9]{64}" "$POOL_OUT/build_league.out" \
    | tail -1 > "$POOL_OUT/POOL_IDENTITY.env" \
    || { echo "could not extract EXPECTED_POOL_HASH" >&2; exit 1; }
fi
# shellcheck disable=SC1091
. "$POOL_OUT/POOL_IDENTITY.env"
[ -n "${EXPECTED_POOL_HASH:-}" ] || { echo "EXPECTED_POOL_HASH empty" >&2; exit 1; }
export EXPECTED_POOL_HASH

echo "=== rung $RUNG reset $RESET_PCT seed $SEED steps $STEPS ==="
echo "  warm $WARM"
echo "  pool $POOL_OUT/pool ($EXPECTED_POOL_HASH)"

export RUNG STEPS RESET_PCT SEED STAMP WARM OUT C
[ -z "${SCRIPTED_BANK_TAG:-}" ] || export SCRIPTED_BANK_TAG
[ -z "${SCRIPTED_BOT_TYPE:-}" ] || export SCRIPTED_BOT_TYPE
[ -z "${LADDER_PROFILE:-}" ] || export LADDER_PROFILE
[ -z "${GRAFT_FROM_SOURCE_SHA256:-}" ] || export GRAFT_FROM_SOURCE_SHA256
[ -z "${GRAFT_FROM_PATCH_BUNDLE_SHA256:-}" ] || export GRAFT_FROM_PATCH_BUNDLE_SHA256
[ -z "${GRAFT_REASON:-}" ] || export GRAFT_REASON
[ -z "${LADDER_PROFILE:-}" ] || \
  echo "  profile ${LADDER_PROFILE} graft_from=${GRAFT_FROM_SOURCE_SHA256:-}/${GRAFT_FROM_PATCH_BUNDLE_SHA256:-} reason=${GRAFT_REASON:-}"
[ -z "${SCRIPTED_BANK_TAG:-}${SCRIPTED_BOT_TYPE:-}" ] || \
  echo "  bot  scripted_bank_tag=${SCRIPTED_BANK_TAG:-0} scripted_bot_type=${SCRIPTED_BOT_TYPE:-0}"
export POOL="$POOL_OUT/pool"
export DEADLINE_HOURS="${DEADLINE_HOURS:-40}"
exec bash tools/launch_ladder_rung.sh
