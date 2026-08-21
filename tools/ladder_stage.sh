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
#   POOL_KEEP=<n> banks kept from PREV_POOL incl. the anchor (default 3)
#   POOL_ANCHOR=<ckpt> weak-anchor bank that never rotates (default: PREV_POOL's
#     bank 0; D244)
#   LADDER_CHAIN_LR_SCALE  forwarded to launch_ladder_rung.sh when set (D244)
#   SCRIPTED_BANK_TAG / SCRIPTED_BOT_TYPE  scripted bank for this rung
#     (forwarded to launch_ladder_rung.sh only when set; unset = ordinary rung)
#   LADDER_PROFILE=graft + GRAFT_FROM_SOURCE_SHA256 / GRAFT_FROM_PATCH_BUNDLE_SHA256
#     / GRAFT_REASON  make this stage the reviewed lineage bridge across a
#     build change (forwarded like SCRIPTED_*; unset = ordinary rung)
#   LADDER_PROFILE=bridge + BRIDGE_WARM_SHA256 / BRIDGE_WARM_OBS_VERSION /
#     BRIDGE_PROVENANCE / BRIDGE_REASON  make this stage the reviewed warm
#     start from an OUT-OF-LINEAGE raw blob (docs/audit-2026-08-20.md F2).
#     A bridge is always a FIRST rung: WARM is the raw obs-v4/obs-v5-era
#     checkpoint with no sidecar, PREV_POOL is an eligible obs-v6 pool, and
#     PREV_COMPLETE must be unset (a chained rung's warm has a sidecar, and a
#     sidecar-bearing warm is refused by the bridge on purpose).
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
POOL_ANCHOR="${POOL_ANCHOR:-}"
PREV_COMPLETE="${PREV_COMPLETE:-}"
PREV_POOL="${PREV_POOL:-}"
WARM="${WARM:-}"
PIN="${PIN:-}"
LADDER_PROFILE="${LADDER_PROFILE:-ladder-rung}"
case "$LADDER_PROFILE" in
  ladder-rung|graft) ;;
  bridge)
    # The raw warm has no marker and no sidecar to chain from; the bridge is
    # the entry point of a chain, never a link inside one.
    if [ -n "$PREV_COMPLETE" ]; then
      echo "LADDER_PROFILE=bridge is a first rung: set WARM (the raw blob) and PREV_POOL, not PREV_COMPLETE" >&2
      exit 1
    fi
    : "${BRIDGE_WARM_SHA256:?BRIDGE_WARM_SHA256 is required for LADDER_PROFILE=bridge}"
    : "${BRIDGE_WARM_OBS_VERSION:?BRIDGE_WARM_OBS_VERSION is required for LADDER_PROFILE=bridge}"
    : "${BRIDGE_PROVENANCE:?BRIDGE_PROVENANCE is required for LADDER_PROFILE=bridge}"
    : "${BRIDGE_REASON:?BRIDGE_REASON is required for LADDER_PROFILE=bridge}"
    ;;
  *)
    echo "LADDER_PROFILE must be ladder-rung, graft or bridge, got '$LADDER_PROFILE'" >&2
    exit 1
    ;;
esac

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
if [ "$LADDER_PROFILE" = "bridge" ]; then
  # The bridged warm is identified by its declared content hash, not by a
  # sidecar. Check the hash here so a stage-level typo fails before a pool is
  # built, and refuse a sidecar outright: a blob with eligible lineage belongs
  # in an ordinary rung.
  [ ! -f "$WARM.lineage.json" ] || {
    echo "bridge warm has a lineage sidecar; use LADDER_PROFILE=ladder-rung for an in-lineage warm: $WARM" >&2
    exit 1; }
  WARM_ACTUAL_SHA256="$(sha256sum "$WARM" | awk '{print $1}')"
  [ "$WARM_ACTUAL_SHA256" = "$BRIDGE_WARM_SHA256" ] || {
    echo "bridge warm $WARM has sha256 $WARM_ACTUAL_SHA256 but BRIDGE_WARM_SHA256 declares $BRIDGE_WARM_SHA256" >&2
    exit 1; }
else
  [ -f "$WARM.lineage.json" ] || { echo "warm has no lineage sidecar: $WARM" >&2; exit 1; }
fi
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
  mapfile -t SEEDS < <(python3 - "$PREV_POOL" "$WARM" "$POOL_KEEP" "$RUNG" "$POOL_ANCHOR" <<'PY'
import json, os, sys
prev_pool, warm, keep, rung, anchor = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4], sys.argv[5]
m = json.load(open(os.path.join(prev_pool, "league_seeds.json"), encoding="utf-8"))
banks = m["seeds"]
warm_real = os.path.realpath(warm)
# D244: a pool that is four near-identical recent selves is the mutually
# permissive equilibrium D166 warned about; the first r25-chain collapsed into
# the abstinence basin against exactly that pool. Bank 0 is therefore a WEAK
# ANCHOR that never rotates (POOL_ANCHOR, default = the previous pool's bank 0,
# so an anchor set once at the start of a chain is inherited by every rung);
# only the remaining banks rotate newest-first, and the previous rung's
# accepted checkpoint enters as the newest.
anchor_src = anchor if anchor else banks[0]["source"]
anchor_real = os.path.realpath(anchor_src)
anchor_name = next((b["name"] for b in banks if os.path.realpath(b["source"]) == anchor_real), "anchor")
rest = [b for b in banks if os.path.realpath(b["source"]) not in (anchor_real, warm_real)]
kept = rest[-(keep - 1):] if keep > 1 else []
out = [f"{anchor_name}={anchor_src}"] + [f"{b['name']}={b['source']}" for b in kept]
if anchor_real == warm_real:
    raise SystemExit("the weak anchor cannot also be the warm checkpoint")
name = f"rung{rung}warm"
names = {o.split('=')[0] for o in out}
i = 0
while name in names:
    i += 1
    name = f"rung{rung}warm{i}"
out.append(f"{name}={warm}")
if len(out) != 4:
    # Pad from the older end of the previous pool if the warm was already a bank.
    for b in reversed(rest[:-(keep - 1)] if keep > 1 else rest):
        if len(out) >= 4:
            break
        if b["name"] not in names:
            out.insert(1, f"{b['name']}={b['source']}")
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
# D244 regression gate input: the previous rung's marker (same-distribution
# comparison happens inside launch_ladder_rung.sh).
[ -z "$PREV_COMPLETE" ] || export WARM_MARKER="$PREV_COMPLETE"
# D245/D248 hypothesised that a chained rung (PREV_COMPLETE set) re-annealing
# LR/entropy from the top dips into passivity, and defaulted chained rungs to
# 0.1x. The 2026-08-20 audit (F1) showed the opposite failure: under Muon the
# LR IS the per-step relative change, and at 0.1x the rung-1 log had kl 0.000
# and clipfrac 0.000 on 38,206 of 38,207 updates with every game statistic
# flat over 5B steps -- "no dip" was "no movement", and every exam since
# measured the warm checkpoint, not the rung. Chained rungs therefore default
# to 1.0 (the fixed contract) like first rungs; an explicit
# LADDER_CHAIN_LR_SCALE still wins for a deliberate experiment.
if [ -n "$PREV_COMPLETE" ] && [ -z "${LADDER_CHAIN_LR_SCALE:-}" ]; then
  export LADDER_CHAIN_LR_SCALE=1.0
fi
[ -z "${LADDER_CHAIN_LR_SCALE:-}" ] || export LADDER_CHAIN_LR_SCALE
[ -z "${SCRIPTED_BANK_TAG:-}" ] || export SCRIPTED_BANK_TAG
[ -z "${SCRIPTED_BOT_TYPE:-}" ] || export SCRIPTED_BOT_TYPE
[ -z "${LADDER_PROFILE:-}" ] || export LADDER_PROFILE
[ -z "${GRAFT_FROM_SOURCE_SHA256:-}" ] || export GRAFT_FROM_SOURCE_SHA256
[ -z "${GRAFT_FROM_PATCH_BUNDLE_SHA256:-}" ] || export GRAFT_FROM_PATCH_BUNDLE_SHA256
[ -z "${GRAFT_REASON:-}" ] || export GRAFT_REASON
[ -z "${BRIDGE_WARM_SHA256:-}" ] || export BRIDGE_WARM_SHA256
[ -z "${BRIDGE_WARM_OBS_VERSION:-}" ] || export BRIDGE_WARM_OBS_VERSION
[ -z "${BRIDGE_PROVENANCE:-}" ] || export BRIDGE_PROVENANCE
[ -z "${BRIDGE_REASON:-}" ] || export BRIDGE_REASON
case "$LADDER_PROFILE" in
  graft)
    echo "  profile ${LADDER_PROFILE} graft_from=${GRAFT_FROM_SOURCE_SHA256:-}/${GRAFT_FROM_PATCH_BUNDLE_SHA256:-} reason=${GRAFT_REASON:-}" ;;
  bridge)
    echo "  profile ${LADDER_PROFILE} warm_sha256=${BRIDGE_WARM_SHA256} obs_version=${BRIDGE_WARM_OBS_VERSION} provenance=${BRIDGE_PROVENANCE} reason=${BRIDGE_REASON}" ;;
  *)
    echo "  profile ${LADDER_PROFILE}" ;;
esac
[ -z "${SCRIPTED_BANK_TAG:-}${SCRIPTED_BOT_TYPE:-}" ] || \
  echo "  bot  scripted_bank_tag=${SCRIPTED_BANK_TAG:-0} scripted_bot_type=${SCRIPTED_BOT_TYPE:-0}"
export POOL="$POOL_OUT/pool"
export DEADLINE_HOURS="${DEADLINE_HOURS:-40}"
exec bash tools/launch_ladder_rung.sh
