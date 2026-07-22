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
SELFPLAY_LEAGUE_PATCH="$ROOT/training/selfplay_league.patch"

# Content hash of a tree with symlinks dereferenced (the puffer/bloodbowl
# engine/ and bb/ links reach into engine/src and engine/include/bb, so any
# engine change changes the hash). Relative paths keep source and snapshot
# hashes comparable.
if command -v sha256sum >/dev/null 2>&1; then SHA256="sha256sum"; else SHA256="shasum -a 256"; fi
snapshot_hash() {
    (cd "$1" && find -L . -type f ! -name .content_hash -print0 | LC_ALL=C sort -z \
        | xargs -0 $SHA256 | $SHA256 | awk '{print $1}')
}

# Hash every source that defines exact-action transport, sampling, or recurrent
# evaluation semantics. The installer writes this digest into a generated
# header; both native and CPU extension modules expose the compiled value.
# --check then compares current sources, generated header, and imported module.
exact_backend_hash() {
    (
        cd "$PUFFER"
        for rel in \
            pufferlib/pufferl.py \
            pufferlib/selfplay.py \
            pufferlib/torch_pufferl.py \
            src/bindings.cu \
            src/bindings_cpu.cpp \
            src/kernels.cu \
            src/pufferlib.cu \
            src/vecenv.h; do
            [ -f "$rel" ] || exit 1
            $SHA256 "$rel"
        done | $SHA256 | awk '{print $1}'
    )
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
    for marker in 'if i == 160:' 'PUFFER_ENV_JSON' \
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
    if [ ! -f "$SELFPLAY_LEAGUE_PATCH" ] || \
       ! grep -Fq 'Patch copy: training/selfplay_league.patch' \
           "$PUFFER/pufferlib/selfplay.py" || \
       ! git -C "$PUFFER" apply --reverse --check --no-index \
           "$SELFPLAY_LEAGUE_PATCH"; then
        echo "drift check: installed selfplay league patch is missing or stale" >&2
        echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
        exit 1
    fi
    for exact_marker in \
        'sample_joint_logits' \
        'joint_action_offsets' \
        'Exact sequential support'; do
        if ! grep -R -Fq "$exact_marker" \
            "$PUFFER/pufferlib/torch_pufferl.py" \
            "$PUFFER/src/vecenv.h" "$PUFFER/src/pufferlib.cu"; then
            echo "drift check: exact-action backend marker missing: $exact_marker" >&2
            echo "  fix: run tools/install_puffer_env.sh $PUFFER" >&2
            exit 1
        fi
    done
    for recurrent_contract in \
        'src/pufferlib.cu:reset_recurrent_state_on_terminal' \
        'src/bindings.cu:set_evaluation_mode' \
        'pufferlib/torch_pufferl.py:pending_terminals'; do
        recurrent_file="${recurrent_contract%%:*}"
        recurrent_marker="${recurrent_contract#*:}"
        if ! grep -Fq "$recurrent_marker" "$PUFFER/$recurrent_file"; then
            echo "drift check: recurrent evaluation marker missing: $recurrent_marker" >&2
            echo "  fix: run tools/install_puffer_env.sh $PUFFER" >&2
            exit 1
        fi
    done
    for qualification_marker in \
        'eligible_agents' \
        'qualification_recurrent_state' \
        'qualification_snapshot'; do
        if ! grep -R -Fq "$qualification_marker" \
            "$PUFFER/src/pufferlib.cu" "$PUFFER/src/bindings.cu"; then
            echo "drift check: recurrent CUDA qualification marker missing: $qualification_marker" >&2
            echo "  fix: run tools/install_puffer_env.sh $PUFFER" >&2
            exit 1
        fi
    done
    for exact_patch in \
        "$ROOT/training/puffer_recurrent_cuda_qualification.patch" \
        "$ROOT/training/puffer_frozen_prio_mask.patch"; do
        if ! git -C "$PUFFER" apply --reverse --check --no-index "$exact_patch"; then
            echo "drift check: installed qualification patch is stale: $exact_patch" >&2
            echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
            exit 1
        fi
    done
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
    current_backend_hash="$(exact_backend_hash)" || {
        echo "drift check: exact-action backend sources are incomplete" >&2
        exit 1
    }
    header_backend_hash="$(sed -n \
        's/^#define PUFFER_EXACT_ACTION_SOURCE_HASH "\([0-9a-f]*\)"$/\1/p' \
        "$PUFFER/src/exact_action_build_hash.h" 2>/dev/null || true)"
    header_environment_hash="$(sed -n \
        's/^#define PUFFER_ENV_SOURCE_HASH "\([0-9a-f]*\)"$/\1/p' \
        "$PUFFER/src/exact_action_build_hash.h" 2>/dev/null || true)"
    header_observation_abi="$(sed -n \
        's/^#define PUFFER_OBSERVATION_ABI "\([^"]*\)"$/\1/p' \
        "$PUFFER/src/exact_action_build_hash.h" 2>/dev/null || true)"
    header_observation_version="$(sed -n \
        's/^#define PUFFER_OBSERVATION_VERSION \([0-9][0-9]*\)$/\1/p' \
        "$PUFFER/src/exact_action_build_hash.h" 2>/dev/null || true)"
    header_action_abi="$(sed -n \
        's/^#define PUFFER_ACTION_ABI "\([^"]*\)"$/\1/p' \
        "$PUFFER/src/exact_action_build_hash.h" 2>/dev/null || true)"
    compiled_contract="$(cd "$PUFFER" && "$PYBIN" -c \
        'from pufferlib import _C; print(getattr(_C, "exact_action_source_hash", "<missing>"), getattr(_C, "environment_source_hash", "<missing>"), getattr(_C, "observation_abi", "<missing>"), getattr(_C, "observation_version", "<missing>"), getattr(_C, "action_abi", "<missing>"))' \
        2>/dev/null || true)"
    read -r compiled_backend_hash compiled_environment_hash \
        compiled_observation_abi compiled_observation_version \
        compiled_action_abi <<< "$compiled_contract"
    if [ "$current_backend_hash" != "$header_backend_hash" ] || \
       [ "$current_backend_hash" != "$compiled_backend_hash" ]; then
        echo "drift check: exact-action source/module digest mismatch" >&2
        echo "  sources: $current_backend_hash" >&2
        echo "  header:  ${header_backend_hash:-<missing>}" >&2
        echo "  module:  ${compiled_backend_hash:-<missing>}" >&2
        echo "  fix: reinstall, then rebuild PufferLib for bloodbowl" >&2
        exit 1
    fi
    if [ "$want" != "$header_environment_hash" ] || \
       [ "$want" != "$compiled_environment_hash" ] || \
       [ "$header_observation_abi" != "obs-v5" ] || \
       [ "$compiled_observation_abi" != "obs-v5" ] || \
       [ "$header_observation_version" != "5" ] || \
       [ "$compiled_observation_version" != "5" ] || \
       [ "$header_action_abi" != "exact-joint-v1" ] || \
       [ "$compiled_action_abi" != "exact-joint-v1" ]; then
        echo "drift check: compiled observation/action lineage mismatch" >&2
        echo "  environment source: $want" >&2
        echo "  header/module source: ${header_environment_hash:-<missing>} / ${compiled_environment_hash:-<missing>}" >&2
        echo "  header/module obs ABI: ${header_observation_abi:-<missing>} / ${compiled_observation_abi:-<missing>}" >&2
        echo "  header/module obs: ${header_observation_version:-<missing>} / ${compiled_observation_version:-<missing>}" >&2
        echo "  header/module action: ${header_action_abi:-<missing>} / ${compiled_action_abi:-<missing>}" >&2
        echo "  fix: reinstall, then rebuild PufferLib for bloodbowl" >&2
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

# Blood Bowl's my_log currently emits 123 keys, and vecenv appends "n" after
# the env binding returns. Keep the vendored dict allocations comfortably above
# that so adding telemetry does not resurrect the historical heap overflow.
for f in "$PUFFER/src/bindings.cu" "$PUFFER/src/bindings_cpu.cpp" "$PUFFER/src/pufferlib.cu"; do
    [ -f "$f" ] || continue
    perl -0pi -e \
        's/create_dict\((32|64|96|128|160)\)(\s*;\s*\/\/ bloodbowl my_log emits )[^\n]*/create_dict(160)$2 123 keys + "n"; keep headroom/g;
         s/create_dict\((32|64|96|128)\);/create_dict(160);/g' "$f"
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
# Bowl emits 123 plus vecenv's `n`; without this patch, later correctness and
# behavior telemetry exists in C but never reaches evaluation logs.
DASHBOARD_PY="$PUFFER/pufferlib/pufferl.py"
if [ -f "$DASHBOARD_PY" ] && grep -q 'if i == 30:' "$DASHBOARD_PY"; then
    if git -C "$PUFFER" apply "$ROOT/training/pufferl_env_dashboard_limit.patch"; then
        echo "applied:   training/pufferl_env_dashboard_limit.patch -> pufferlib/pufferl.py"
    else
        echo "warning: dashboard-limit patch did not apply; later Blood Bowl metrics will be hidden" >&2
    fi
fi
if [ -f "$DASHBOARD_PY" ] && grep -q 'if i == 96:' "$DASHBOARD_PY"; then
    perl -pi -e 's/if i == 96:/if i == 160:/' "$DASHBOARD_PY"
    echo "upgraded:  Puffer dashboard capacity 96 -> 160 metrics"
fi
if [ -f "$DASHBOARD_PY" ] && ! grep -q 'if i == 160:' "$DASHBOARD_PY"; then
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

# Selfplay bank initialization is a training-semantic runtime surface. Install
# its optional league-preseed branch centrally even for fresh runs: the empty
# league_preseed path remains upstream-equivalent, while every runner and
# provenance bundle can now require one exact Puffer runtime. A marker is only
# diagnostic; full reverse applicability proves the complete patch is present.
if [ ! -f "$SELFPLAY_LEAGUE_PATCH" ]; then
    echo "error: missing training/selfplay_league.patch" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$SELFPLAY_LEAGUE_PATCH" \
        2>/dev/null; then
    : # Exact patch is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$SELFPLAY_LEAGUE_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$SELFPLAY_LEAGUE_PATCH"
    echo "applied:   training/selfplay_league.patch -> pufferlib/selfplay.py"
else
    echo "error: selfplay league patch is neither applicable nor already applied" >&2
    exit 1
fi
if ! grep -Fq 'Patch copy: training/selfplay_league.patch' \
        "$PUFFER/pufferlib/selfplay.py" || \
   ! git -C "$PUFFER" apply --reverse --check --no-index \
       "$SELFPLAY_LEAGUE_PATCH"; then
    echo "error: installed selfplay league patch is incomplete" >&2
    exit 1
fi

# Exact semantic action identity. This extends the generic vec interface with
# a transient ragged joint-support buffer; native and Torch rollout sampling
# turn it into the same selected conditional masks already stored by PPO.
# Apply after the dashboard/trusted-load patches because the saved patch is
# based on that fully installed Puffer tree.
EXACT_PATCH="$ROOT/training/puffer_exact_joint_actions.patch"
if [ -f "$EXACT_PATCH" ] && \
   ! grep -q 'sample_joint_logits' "$TORCH_PUFFERL_PY"; then
    if git -C "$PUFFER" apply "$EXACT_PATCH"; then
        echo "applied:   exact joint-action sampling -> Puffer native/Torch backends"
    else
        echo "error: exact joint-action patch did not apply" >&2
        exit 1
    fi
fi
if ! grep -q 'sample_joint_logits' "$TORCH_PUFFERL_PY" || \
   ! grep -q 'joint_action_offsets' "$PUFFER/src/vecenv.h" || \
   ! grep -q 'Exact sequential support' "$PUFFER/src/pufferlib.cu"; then
    echo "error: exact joint-action backend support is incomplete" >&2
    exit 1
fi

# Recurrent evaluation contract. Apply only after exact-action support because
# both patches extend the same native and Torch rollout paths.
RECURRENT_PATCH="$ROOT/training/puffer_recurrent_eval_state.patch"
if [ -f "$RECURRENT_PATCH" ] && \
   ! grep -q 'reset_recurrent_state_rows' "$TORCH_PUFFERL_PY"; then
    if git -C "$PUFFER" apply "$RECURRENT_PATCH"; then
        echo "applied:   recurrent evaluation-state boundaries -> Puffer native/Torch backends"
    else
        echo "error: recurrent evaluation-state patch did not apply" >&2
        exit 1
    fi
fi
if ! grep -q 'reset_recurrent_state_on_terminal' "$PUFFER/src/pufferlib.cu" || \
   ! grep -q 'set_evaluation_mode' "$PUFFER/src/bindings.cu" || \
   ! grep -q 'pending_terminals' "$TORCH_PUFFERL_PY"; then
    echo "error: recurrent evaluation-state support is incomplete" >&2
    exit 1
fi

# Frozen PPO rows must be mathematically ineligible for priority sampling;
# zero advantages are insufficient when alpha=0 because pow(0, 0) is one.
FROZEN_PRIO_PATCH="$ROOT/training/puffer_frozen_prio_mask.patch"
if [ -f "$FROZEN_PRIO_PATCH" ] && \
   ! grep -q 'eligible_agents' "$PUFFER/src/pufferlib.cu"; then
    if git -C "$PUFFER" apply --no-index "$FROZEN_PRIO_PATCH"; then
        echo "applied:   exact frozen-row exclusion -> prioritized PPO sampler"
    else
        echo "error: frozen-row priority-mask patch did not apply" >&2
        exit 1
    fi
elif [ -f "$FROZEN_PRIO_PATCH" ] && \
     ! git -C "$PUFFER" apply --reverse --check --no-index "$FROZEN_PRIO_PATCH"; then
    echo "error: installed frozen-row priority-mask patch is stale" >&2
    echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
    exit 1
fi
if ! grep -q 'eligible_agents' "$PUFFER/src/pufferlib.cu"; then
    echo "error: exact frozen-row exclusion is incomplete" >&2
    exit 1
fi

# Read-only CUDA qualification evidence. Apply last: it inspects the exact
# rollout, recurrent, and PPO tensors produced by the preceding semantic
# patches, and therefore belongs to the same compiled backend identity.
QUALIFICATION_PATCH="$ROOT/training/puffer_recurrent_cuda_qualification.patch"
if [ -f "$QUALIFICATION_PATCH" ] && \
   ! grep -q 'qualification_recurrent_state' "$PUFFER/src/bindings.cu"; then
    if git -C "$PUFFER" apply --no-index "$QUALIFICATION_PATCH"; then
        echo "applied:   bounded recurrent CUDA qualification evidence -> Puffer native backend"
    else
        echo "error: recurrent CUDA qualification patch did not apply" >&2
        exit 1
    fi
elif [ -f "$QUALIFICATION_PATCH" ] && \
     ! git -C "$PUFFER" apply --reverse --check --no-index "$QUALIFICATION_PATCH"; then
    echo "error: installed recurrent CUDA qualification patch is stale" >&2
    echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
    exit 1
fi
if ! grep -q 'qualification_recurrent_state' "$PUFFER/src/bindings.cu" || \
   ! grep -q 'qualification_snapshot' "$PUFFER/src/bindings.cu"; then
    echo "error: recurrent CUDA qualification evidence is incomplete" >&2
    exit 1
fi

EXACT_BACKEND_HASH="$(exact_backend_hash)" || {
    echo "error: could not hash exact-action backend sources" >&2
    exit 1
}
INSTALLED_SOURCE_HASH="$(cat "$DST/.content_hash")"
printf '#pragma once\n#define PUFFER_EXACT_ACTION_SOURCE_HASH "%s"\n#define PUFFER_ENV_SOURCE_HASH "%s"\n#define PUFFER_OBSERVATION_ABI "obs-v5"\n#define PUFFER_OBSERVATION_VERSION 5\n#define PUFFER_ACTION_ABI "exact-joint-v1"\n' \
    "$EXACT_BACKEND_HASH" "$INSTALLED_SOURCE_HASH" \
    > "$PUFFER/src/exact_action_build_hash.h"
echo "recorded:   exact-action backend digest $EXACT_BACKEND_HASH"

echo "installed: $DST"
echo "           $PUFFER/config/bloodbowl.ini"
echo "build:     cd $PUFFER && ./build.sh bloodbowl          # CUDA training backend"
echo "           cd $PUFFER && ./build.sh bloodbowl --fast   # standalone benchmark"
