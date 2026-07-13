#!/usr/bin/env bash
# Install/refresh the bloodbowl env into the vendored PufferLib tree.
#
# puffer/bloodbowl/ holds the source of truth; its engine/ and bb/ symlinks
# (-> ../../engine/{src,include/bb}) are dereferenced here (cp -RL) so the
# installed ocean/bloodbowl/ is self-contained — build.sh's stock
# `-I$SRC_DIR` covers every include, no build.sh patch needed, and
# vendor/PufferLib can be rsynced to a GPU box as-is.
#
# Usage: tools/install_puffer_env.sh [path-to-pufferlib]   (default: vendor/PufferLib)
#        tools/install_puffer_env.sh --check [path-to-pufferlib]
#
# --check is the drift guard (adversarial review LOW): the GPU run compiles
# the installed snapshot, NOT engine/src — an engine edit without a re-install
# silently trains on stale rules. Run it before any build on a training box /
# in CI; exit 1 means re-run the install.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MODE=install
if [ "${1:-}" = "--check" ]; then
    MODE=check
    shift
fi
PUFFER="${1:-$ROOT/vendor/PufferLib}"

[ -f "$PUFFER/build.sh" ] || { echo "error: $PUFFER is not a PufferLib tree" >&2; exit 1; }
PUFFER="$(cd "$PUFFER" && pwd)"

DST="$PUFFER/ocean/bloodbowl"

# Content hash of a tree with symlinks dereferenced (the puffer/bloodbowl
# engine/ and bb/ links reach into engine/src and engine/include/bb, so any
# engine change changes the hash). Relative paths keep source and snapshot
# hashes comparable.
if command -v sha256sum >/dev/null 2>&1; then SHA256="sha256sum"; else SHA256="shasum -a 256"; fi
snapshot_hash() {
    (cd "$1" && find -L . -type f ! -name .content_hash -print0 | LC_ALL=C sort -z \
        | xargs -0 $SHA256 | $SHA256 | awk '{print $1}')
}

if [ "$MODE" = "check" ]; then
    [ -d "$DST" ] || { echo "drift check: $DST not installed — run tools/install_puffer_env.sh" >&2; exit 1; }
    want="$(snapshot_hash "$ROOT/puffer/bloodbowl")"
    have="$(cat "$DST/.content_hash" 2>/dev/null || echo "<none>")"
    if [ "$want" != "$have" ]; then
        echo "drift check: STALE snapshot — engine/src or puffer/bloodbowl changed since install" >&2
        echo "  source now: $want" >&2
        echo "  installed:  $have" >&2
        echo "  fix: tools/install_puffer_env.sh $PUFFER" >&2
        exit 1
    fi
    if ! cmp -s "$ROOT/puffer/config/bloodbowl.ini" "$PUFFER/config/bloodbowl.ini"; then
        echo "drift check: STALE installed bloodbowl.ini" >&2
        echo "  fix: tools/install_puffer_env.sh $PUFFER" >&2
        exit 1
    fi
    DASHBOARD_PY="$PUFFER/pufferlib/pufferl.py"
    for marker in 'if i == 96:' 'PUFFER_ENV_JSON' \
                  "'_puffer_schema': 2" "'_puffer_final_reprint'" \
                  'phase_eval=phase_eval, phase_epoch=epoch'; do
        if ! grep -Fq "$marker" "$DASHBOARD_PY"; then
            echo "drift check: missing Puffer dashboard marker: $marker" >&2
            echo "  fix: tools/install_puffer_env.sh $PUFFER" >&2
            exit 1
        fi
    done
    if ! grep -Fq 'historical full-pickle state dicts' \
        "$PUFFER/pufferlib/torch_pufferl.py"; then
        echo "drift check: trusted historical checkpoint-load patch is missing" >&2
        echo "  fix: tools/install_puffer_env.sh $PUFFER" >&2
        exit 1
    fi
    PYBIN="$PUFFER/.venv/bin/python"
    if [ ! -x "$PYBIN" ]; then
        echo "drift check: vendored Python is missing: $PYBIN" >&2
        exit 1
    fi
    current_module="$(cd "$PUFFER" && \
        "$PYBIN" -c 'from pufferlib import _C; print(_C.__file__)')"
    if [ ! -f "$current_module" ]; then
        echo "drift check: imported pufferlib/_C module is missing: $current_module" >&2
        exit 1
    fi
    if [ ! "$current_module" -nt "$DST/.content_hash" ]; then
        echo "drift check: compiled _C module predates the installed snapshot" >&2
        echo "  fix: rebuild PufferLib for bloodbowl" >&2
        exit 1
    fi
    echo "drift check: OK ($want; config/dashboard/build current)"
    exit 0
fi
rm -rf "$DST"
mkdir -p "$DST"
cp -RL "$ROOT/puffer/bloodbowl/." "$DST/"
cp "$ROOT/puffer/config/bloodbowl.ini" "$PUFFER/config/bloodbowl.ini"
# Record the source content hash for the --check drift guard.
snapshot_hash "$ROOT/puffer/bloodbowl" > "$DST/.content_hash"

# Stage FFB spectator art (optional — needs vendor/ffb and a python with yaml;
# training and the fallback circle renderer work fine without it).
if [ -d "$ROOT/vendor/ffb" ] && [ -x "$PUFFER/.venv/bin/python" ]; then
    "$PUFFER/.venv/bin/python" "$ROOT/tools/stage_spectator_art.py" || \
        echo "warning: spectator art staging failed (renderer falls back to circles)"
fi

# Stage the demo-state reset bank (optional — built by
# validation/build_state_bank.py; the env's demo_reset_pct curriculum loads
# it from resources/bloodbowl/state_bank.bbs and degrades to plain procgen
# resets when absent).
if [ -f "$ROOT/validation/states/bank.bbs" ]; then
    mkdir -p "$PUFFER/resources/bloodbowl"
    cp "$ROOT/validation/states/bank.bbs" "$PUFFER/resources/bloodbowl/state_bank.bbs"
    echo "staged:    $PUFFER/resources/bloodbowl/state_bank.bbs"
fi

# Blood Bowl's my_log currently emits 82 keys, and vecenv appends "n" after
# the env binding returns. Keep the vendored dict allocations comfortably above
# that so adding telemetry does not resurrect the historical heap overflow.
for f in "$PUFFER/src/bindings.cu" "$PUFFER/src/bindings_cpu.cpp" "$PUFFER/src/pufferlib.cu"; do
    [ -f "$f" ] || continue
    perl -0pi -e \
        's/create_dict\((32|64)\)(\s*;\s*\/\/ bloodbowl my_log emits )[^\n]*/create_dict(96)$2 82 keys + "n"; keep headroom/g;
         s/create_dict\((32|64)\);/create_dict(96);/g' "$f"
done

# Apply the match-mode sweep fix to vendored pufferlib/sweep.py (D131). Upstream
# (PufferAI/PufferLib 4.0, incl. current HEAD) omits the match_* keys from
# _params_from_puffer_sweep's skip-list, so a match-mode `puffer sweep` crashes with
# 'Param match_enemy_model_path is not a dict'. Idempotent; sweeps don't go through
# the run_*.sh scripts that apply the other patches, so wire it in here.
SWEEP_PY="$PUFFER/pufferlib/sweep.py"
if [ -f "$SWEEP_PY" ] && ! grep -q "match_enemy_model_path" "$SWEEP_PY"; then
    if git -C "$PUFFER" apply "$ROOT/training/sweep_match_mode_exclusion.patch" 2>/dev/null; then
        echo "applied:   training/sweep_match_mode_exclusion.patch -> pufferlib/sweep.py"
    else
        echo "warning: sweep_match_mode_exclusion.patch did not apply — match-mode sweeps will crash; fix by hand" >&2
    fi
    # stale bytecode would shadow the patched source (a real gotcha hit live)
    rm -f "$PUFFER/pufferlib/__pycache__/sweep.cpython-"*.pyc 2>/dev/null
fi

# Puffer's stock dashboard truncates environment metrics after 30 keys. Blood
# Bowl emits 82 plus vecenv's `n`; without this patch, later correctness and
# behavior telemetry exists in C but never reaches evaluation logs.
DASHBOARD_PY="$PUFFER/pufferlib/pufferl.py"
if [ -f "$DASHBOARD_PY" ] && grep -q 'if i == 30:' "$DASHBOARD_PY"; then
    if git -C "$PUFFER" apply "$ROOT/training/pufferl_env_dashboard_limit.patch"; then
        echo "applied:   training/pufferl_env_dashboard_limit.patch -> pufferlib/pufferl.py"
    else
        echo "warning: dashboard-limit patch did not apply; later Blood Bowl metrics will be hidden" >&2
    fi
fi
if [ -f "$DASHBOARD_PY" ] && ! grep -q 'if i == 96:' "$DASHBOARD_PY"; then
    echo "warning: Puffer dashboard still truncates Blood Bowl telemetry" >&2
fi
if [ -f "$DASHBOARD_PY" ] && ! grep -q 'PUFFER_ENV_JSON' "$DASHBOARD_PY"; then
    if git -C "$PUFFER" apply "$ROOT/training/pufferl_env_json.patch"; then
        echo "applied:   training/pufferl_env_json.patch -> pufferlib/pufferl.py"
    else
        echo "warning: machine-readable environment-log patch did not apply" >&2
    fi
fi
if [ -f "$DASHBOARD_PY" ] && grep -q 'PUFFER_ENV_JSON' "$DASHBOARD_PY" && \
   ! grep -q "'_puffer_schema': 1" "$DASHBOARD_PY" && \
   ! grep -q "'_puffer_schema': 2" "$DASHBOARD_PY"; then
    if git -C "$PUFFER" apply \
        "$ROOT/training/pufferl_env_json_metadata_upgrade.patch"; then
        echo "upgraded:  phase/cumulative/reprint metadata -> pufferlib/pufferl.py"
    else
        echo "warning: machine-log metadata upgrade did not apply" >&2
    fi
fi
if [ -f "$DASHBOARD_PY" ] && \
   ! grep -q "'_puffer_schema': 2" "$DASHBOARD_PY"; then
    if git -C "$PUFFER" apply \
        "$ROOT/training/pufferl_env_phase_contract.patch"; then
        echo "upgraded:  explicit log phase/panel semantics -> pufferlib/pufferl.py"
    else
        echo "warning: explicit log-phase contract patch did not apply" >&2
    fi
fi
if [ -f "$DASHBOARD_PY" ] && \
   ! grep -q "'_puffer_eval_episodes_completed'" "$DASHBOARD_PY"; then
    if git -C "$PUFFER" apply \
        "$ROOT/training/pufferl_eval_episode_gate.patch"; then
        echo "upgraded:  exact native/torch eval-game gate -> pufferlib/pufferl.py"
    else
        echo "warning: exact eval-game gate patch did not apply" >&2
    fi
fi
if [ -f "$DASHBOARD_PY" ] && ! grep -q 'metrics.setdefault' "$DASHBOARD_PY"; then
    if git -C "$PUFFER" apply \
        "$ROOT/training/pufferl_metrics_keyerror.patch"; then
        echo "upgraded:  dynamic post-run metric keys -> pufferlib/pufferl.py"
    else
        echo "warning: dynamic metric-key patch did not apply" >&2
    fi
fi
if [ -f "$DASHBOARD_PY" ] && \
   { ! grep -q "'_puffer_final_reprint'" "$DASHBOARD_PY" || \
     ! grep -q "'_puffer_schema': 2" "$DASHBOARD_PY" || \
     ! grep -q "'_puffer_eval_episodes_completed'" "$DASHBOARD_PY" || \
     ! grep -q 'metrics.setdefault' "$DASHBOARD_PY"; }; then
    echo "warning: full-fidelity phase/panel/reprint/eval-gate/dynamic-key support is missing" >&2
fi

# PyTorch 2.6 changed torch.load's default to weights_only=True. Historical
# Blood Bowl checkpoints are trusted local full-pickle state dicts; patch both
# policy construction and the later warm-load path explicitly and durably.
TORCH_PUFFERL_PY="$PUFFER/pufferlib/torch_pufferl.py"
if [ -f "$TORCH_PUFFERL_PY" ] && \
   ! grep -q 'historical full-pickle state dicts' "$TORCH_PUFFERL_PY"; then
    if git -C "$PUFFER" apply "$ROOT/training/torch_pufferl_trusted_load.patch"; then
        echo "applied:   trusted historical checkpoint loading -> torch_pufferl.py"
    else
        echo "warning: trusted-checkpoint load patch did not apply" >&2
    fi
fi

echo "installed: $DST"
echo "           $PUFFER/config/bloodbowl.ini"
echo "build:     cd $PUFFER && ./build.sh bloodbowl          # CUDA training backend"
echo "           cd $PUFFER && ./build.sh bloodbowl --fast   # standalone benchmark"
