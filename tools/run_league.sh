#!/usr/bin/env bash
# Launch the heterogeneous-league run (profile-league): the frozen selfplay
# banks START as a fixed, heterogeneous set of OUR checkpoints instead of
# bootstrap-clones of the learner (docs/rl-best-practices.md hole #3 —
# league diversity must be in OBJECTIVE, not checkpoint age; AlphaStar).
#
#   tools/run_league.sh [extra puffer args...]
#
# Bank composition (seed order == bank index; selfplay.py build_perm_tags):
#   bank 0  profile-A final       passive wall (pure outcome, 10B, 0-0 basin)
#   bank 1  profile-D final       bootstrap-potential scorer (10B)
#   bank 2  BC-init               human prior (bc_v1_cuda.bin)
#   bank 3  anneal stage-1 final  50% potentials, tds 0.185 (D28)
#   bank 4  anneal graduate       stage-3 final, scaffold-free scorer (D28)
# Learner warm-starts from the graduate (same checkpoint as bank 4).
#
# Seed resolution: env override > PROFILE-marker discovery (newest run dir
# under checkpoints/bloodbowl/ whose PROFILE matches, highest-step .bin in
# it). Overrides (absolute paths to flat-fp32 CUDA .bins):
#   LEAGUE_SEED_A LEAGUE_SEED_D LEAGUE_SEED_BC
#   LEAGUE_SEED_STAGE1 LEAGUE_SEED_GRADUATE
# The anneal-chain PROFILE markers were written ad hoc on the box; if
# discovery misses, the script lists every available marker and exits.
#
# frozen_bank_pct = 0.08 math (PER-BANK slice; selfplay.py:151-163 mirrors
# pufferlib.cu:2069+, both floor(apb * pct)):
#   apb       = total_agents / num_buffers = 4096 / 2 = 2048 agent rows
#   team_size = agents_per_env / 2 = 1   (2 agents per match)
#   per bank  = floor(2048 * 0.08) = 163 frozen rows; 5 banks = 815 total,
#               under the hard cap apb/2 = 1024 (selfplay.py:159-161)
#   hist envs = 163 * 2 buffers = 326 envs per bank (1632 of 2048 envs play
#               the league, 418 envs pure selfplay)
#   learner rows = 2048 - 815 = 1233 per buffer; league-facing share
#               815/1233 ~= 66% (~AlphaStar mains' 65% non-self games)
#   min_games wall-clock: each env advances 1 env-step per 4096 global
#   steps (global_step += horizon*total_agents per epoch; every env gets
#   horizon env-steps). Worst case (episodes hit max_decisions = 4096):
#   2048 games / 326 envs = 6.3 eps/env * 4096 dec * 4096 = ~105M global
#   steps to arm a bank's winrate gate; typical episodes (~600-900
#   decisions) ~16-25M. Both are far inside opp_timeout_steps (500M) and
#   snapshot_interval (500M), so swaps are winrate-gated with >4x margin
#   even at the episode cap — the pool curriculum is live, not timeout-only.
#
# Rewards: clamp-corrected outcome values come from the ini (td 0.4, win
# 0.6); event knobs below are profile B verbatim (tools/train_profile.sh).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PUFFER="$ROOT/vendor/PufferLib"
PYBIN="python3"
[ -x "$PUFFER/.venv/bin/python" ] && PYBIN="$PUFFER/.venv/bin/python"
cd "$PUFFER"

bash "$ROOT/tools/install_puffer_env.sh" --check || {
  echo "stale env snapshot — run tools/install_puffer_env.sh first" >&2; exit 1; }

# load_config only accepts CLI args for keys present in the ini — make sure
# the installed copy has league_preseed (the --check hash covers ocean/, not
# the ini, so refresh it directly).
grep -q '^league_preseed' config/bloodbowl.ini || {
  echo "refreshing config/bloodbowl.ini (league_preseed key)"
  cp "$ROOT/puffer/config/bloodbowl.ini" config/bloodbowl.ini
}
grep -q '^league_preseed' config/bloodbowl.ini || {
  echo "config/bloodbowl.ini still lacks league_preseed — pull latest repo" >&2; exit 1; }

# League preseed patch must be present in the vendored selfplay.py
# (vendor/*/ is gitignored — a re-clone loses it). Auto-reapply.
if ! grep -q 'league_preseed' pufferlib/selfplay.py; then
  echo "applying training/selfplay_league.patch to vendored selfplay.py"
  git apply "$ROOT/training/selfplay_league.patch"
fi

# Warm start is a separate local pufferl.py patch (gitignored; see
# .claude/skills/puffer-env-dev/SKILL.md) — required for the graduate start.
grep -q 'Warm-started training from' pufferlib/pufferl.py || {
  echo "vendored pufferl.py lacks the warm-start patch (fresh re-clone?) —" >&2
  echo "reapply it per .claude/skills/puffer-env-dev/SKILL.md first" >&2; exit 1; }

# Native CUDA backend required: the selfplay pool + frozen banks are
# CUDA-only (no --slowly here).
$PYBIN - <<'EOF' || { echo "fix: ./build.sh bloodbowl (on the CUDA box)" >&2; exit 1; }
from pufferlib import _C
assert getattr(_C, 'env_name', None) == 'bloodbowl', f"_C built for {getattr(_C, 'env_name', None)}, not bloodbowl"
assert _C.gpu, "_C is a CPU build — selfplay pool/banks are CUDA-only; rebuild on the box"
EOF

# --- Seed resolution ---------------------------------------------------------
resolve_profile() {
  # $1: case-insensitive extended regex the PROFILE line 1 must match.
  # $2 (optional): exclusion regex it must NOT match.
  # Newest matching run dir wins; highest-step checkpoint inside it.
  local pat="$1" excl="${2:-}" d line best
  # shellcheck disable=SC2045  # mtime order needed; run dirs are our own
  # all-numeric/league-<stamp> names (no spaces), same pattern as
  # train_profile.sh / run_bcreg.sh.
  for d in $(ls -td checkpoints/bloodbowl/*/ 2>/dev/null); do
    [ -f "${d}PROFILE" ] || continue
    line=$(head -n1 "${d}PROFILE")
    echo "$line" | grep -Eqi -- "$pat" || continue
    if [ -n "$excl" ] && echo "$line" | grep -Eqi -- "$excl"; then continue; fi
    best=$(find "$d" -maxdepth 1 -name '[0-9]*.bin' 2>/dev/null | sort | tail -1)
    if [ -n "$best" ]; then echo "$best"; return 0; fi
  done
  return 1
}

need_seed() {  # $1 env-var name  $2 env-var value  $3 pattern  $4 exclude  $5 label
  local path="$2"
  if [ -z "$path" ]; then
    if ! path=$(resolve_profile "$3" "$4"); then
      echo "cannot resolve $5 (PROFILE pattern: $3${4:+, excluding: $4})." >&2
      echo "Available markers:" >&2
      grep -H . checkpoints/bloodbowl/*/PROFILE >&2 2>/dev/null || echo "  (none)" >&2
      echo "export $1=/abs/path/to/checkpoint.bin and re-run" >&2
      return 1
    fi
  fi
  [ -f "$path" ] || { echo "$5: $path does not exist" >&2; return 1; }
  echo "$path"
}

# Discovery heuristics (env overrides are authoritative — the anneal-chain
# markers were written ad hoc on the box). The chain ran 50% -> 25% -> 0%
# sequentially, so the NEWEST anneal-family run is the graduate; D2's
# "(anneal: bootstrap off)" cold-cut and the intermediate stages are
# excluded by pattern.
SEED_A=$(need_seed     LEAGUE_SEED_A        "${LEAGUE_SEED_A:-}"        '^profile-A' '' 'profile-A final')
SEED_D=$(need_seed     LEAGUE_SEED_D        "${LEAGUE_SEED_D:-}"        '^profile-D \(bootstrap' '' 'profile-D final')
SEED_BC="${LEAGUE_SEED_BC:-$ROOT/bc_v1_cuda.bin}"
[ -f "$SEED_BC" ] || { echo "BC-init seed missing: $SEED_BC (export LEAGUE_SEED_BC=...)" >&2; exit 1; }
SEED_S1=$(need_seed    LEAGUE_SEED_STAGE1   "${LEAGUE_SEED_STAGE1:-}"   'anneal.*50' 'anneal ?25|25 ?%|anneal:' 'anneal stage-1 final')
SEED_GRAD=$(need_seed  LEAGUE_SEED_GRADUATE "${LEAGUE_SEED_GRADUATE:-}" 'anneal|grad' 'anneal:|anneal ?50|50 ?%|anneal ?25|25 ?%' 'anneal graduate (stage-3 final)')

echo "league seeds:"
echo "  bank 0 profile-A final      $SEED_A"
echo "  bank 1 profile-D final      $SEED_D"
echo "  bank 2 BC-init              $SEED_BC"
echo "  bank 3 anneal stage-1 final $SEED_S1"
echo "  bank 4 anneal graduate      $SEED_GRAD   (also the warm start)"

# --- Build the pre-seeded pool ------------------------------------------------
LEAGUE_DIR="$PUFFER/checkpoints/bloodbowl/league-$(date +%Y%m%d-%H%M%S)"
$PYBIN "$ROOT/tools/build_league.py" --out "$LEAGUE_DIR" --seeds \
  "profile-A-final=$SEED_A" \
  "profile-D-final=$SEED_D" \
  "bc-init=$SEED_BC" \
  "anneal-stage1=$SEED_S1" \
  "anneal-graduate=$SEED_GRAD"
echo "profile-league (heterogeneous)" > "$LEAGUE_DIR/PROFILE"

# PROFILE marker for the spectator feed: the trainer creates its run dir
# shortly after launch; it is the newest dir WITHOUT a marker (the league
# dir above already has one).
(
  for _ in $(seq 1 24); do
    sleep 10
    d=$(ls -td checkpoints/bloodbowl/*/ 2>/dev/null | head -1)
    if [ -n "$d" ] && [ ! -e "${d}PROFILE" ]; then
      echo "profile-league (heterogeneous)" > "${d}PROFILE"
      break
    fi
  done
) &

exec puffer train bloodbowl --tag profile-league \
  --load-model-path "$SEED_GRAD" \
  --selfplay.league-preseed "$LEAGUE_DIR/pool" \
  --vec.num-frozen-banks 5 \
  --vec.frozen-bank-pct 0.08 \
  --selfplay.swap-winrate 0.55 \
  --selfplay.snapshot-interval 500000000 \
  --train.total-timesteps 10000000000 \
  --eval-episodes 200 \
  --env.reward-draw -0.1 \
  --env.reward-setup-done 0.25 --env.reward-setup-autofix -0.25 \
  --env.reward-ball-gain 0.1 --env.reward-ball-loss -0.2 \
  --env.reward-injury-inflicted 0.15 --env.reward-injury-taken -0.15 \
  --env.reward-injury-value-scaled 1 \
  --env.reward-surf-taken -0.1 --env.reward-surf-inflicted 0.1 \
  "$@"
