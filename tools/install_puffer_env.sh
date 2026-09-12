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

# The observation revision is DERIVED from the header, never typed twice. The
# generated build header and the --check gate both used to carry their own
# literal, so an obs bump had to be edited in three places or the compiled
# module would advertise the previous revision -- with no symptom, because
# obs-v4 through obs-v6 were 2782 bytes; obs-v7 is 2851 bytes.
ENV_HEADER="$ROOT/puffer/bloodbowl/bloodbowl.h"
[ -f "$ENV_HEADER" ] || {
    echo "error: missing $ENV_HEADER" >&2; exit 1; }
SOURCE_OBSERVATION_VERSION="$(sed -n \
    's/^#define BBE_OBS_VERSION \([0-9][0-9]*\).*$/\1/p' "$ENV_HEADER" | head -1)"
[ -n "$SOURCE_OBSERVATION_VERSION" ] || {
    echo "error: could not read BBE_OBS_VERSION from $ENV_HEADER" >&2; exit 1; }
SOURCE_OBSERVATION_ABI="obs-v$SOURCE_OBSERVATION_VERSION"

# Only installed later patches belong in an earlier patch's shadow reverse
# check. This also permits upgrading a previously qualified runtime in place.
NATIVE_DIAGNOSTICS_REVERSE=()
COMPACT_SNAPSHOT_REVERSE=()
TERMINAL_AWARE_REVERSE=()
if grep -Fq 'm.def("qualification_entropy_gradient_state"' "$PUFFER/src/bindings.cu" 2>/dev/null; then
    NATIVE_DIAGNOSTICS_REVERSE+=("$ROOT/training/puffer_native_entropy_diagnostics.patch")
fi
if grep -Fq 'py::arg("include_rollout") = true' "$PUFFER/src/bindings.cu" 2>/dev/null; then
    COMPACT_SNAPSHOT_REVERSE+=("$ROOT/training/puffer_compact_qualification_snapshot.patch")
    NATIVE_DIAGNOSTICS_REVERSE+=("$ROOT/training/puffer_compact_qualification_snapshot.patch")
fi
if grep -Fq 'RECURRENT_MEMORY_CONTRACT = "terminal-aware-tbptt-v1"' \
        "$PUFFER/pufferlib/torch_pufferl.py" 2>/dev/null; then
    TERMINAL_AWARE_REVERSE+=("$ROOT/training/puffer_terminal_aware_torch.patch")
fi
if grep -R -Fq 'terminal-aware-tbptt-v1' \
        "$PUFFER/src/bindings.cu" "$PUFFER/src/bindings_cpu.cpp" 2>/dev/null; then
    TERMINAL_AWARE_REVERSE+=("$ROOT/training/puffer_terminal_aware_native.patch")
fi

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
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            [ -f "$rel" ] || exit 1
            $SHA256 "$rel"
        done < "$ROOT/training/puffer_compiled_backend_sources.txt"
    ) | $SHA256 | awk '{print $1}'
}

# Prove that an earlier patch is present beneath later overlapping patches
# without mutating the installed tree. The shadow contains only paths named by
# the participating patches; later patches are removed in reverse install order.
patch_reverse_checks_beneath_later() {
    local earlier_patch="$1"
    shift
    local shadow patch rel
    shadow="$(mktemp -d "${TMPDIR:-/tmp}/puffer-patch-check.XXXXXX")" || return 1
    for patch in "$earlier_patch" "$@"; do
        while IFS= read -r rel; do
            [ -n "$rel" ] || continue
            # Overlapping patches name the same file more than once. Copy its
            # final installed contents once, including from immutable runtimes.
            # Re-copying a read-only file emits a misleading permission error.
            if [ ! -f "$shadow/$rel" ]; then
                if ! mkdir -p "$shadow/$(dirname "$rel")" || \
                   ! cp "$PUFFER/$rel" "$shadow/$rel"; then
                    rm -rf "$shadow"
                    return 1
                fi
            fi
        done < <(sed -n 's|^+++ b/||p' "$patch")
    done
    local earlier_paths=() later=() include_args=() i
    while IFS= read -r rel; do
        [ -n "$rel" ] && earlier_paths+=("$rel")
    done < <(sed -n 's|^+++ b/||p' "$earlier_patch")
    for patch in "$@"; do later+=("$patch"); done
    for ((i=${#later[@]}-1; i>=0; i--)); do
        include_args=()
        for rel in "${earlier_paths[@]}"; do
            if grep -Fq "+++ b/$rel" "${later[$i]}"; then
                include_args+=("--include=$rel")
            fi
        done
        [ "${#include_args[@]}" -gt 0 ] || continue
        if ! git -C "$shadow" apply --reverse --no-index \
                "${include_args[@]}" "${later[$i]}" \
                >/dev/null 2>&1; then
            rm -rf "$shadow"
            return 1
        fi
    done
    git -C "$shadow" apply --reverse --check --no-index "$earlier_patch" \
        >/dev/null 2>&1
    local status=$?
    rm -rf "$shadow"
    return "$status"
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
    for trainer_contract in \
        'pufferlib/torch_pufferl.py:tail_observation' \
        'src/pufferlib.cu:tail_callback_wrapper' \
        'src/bindings.cu:rollout_transition_contract' \
        'pufferlib/torch_pufferl.py:ENTROPY_SCHEDULE_CONTRACT' \
        'src/pufferlib.cu:enqueue_entropy_coefficient' \
        'src/bindings.cu:entropy_schedule_contract' \
        'src/bindings.cu:qualification_entropy_gradient_state' \
        'src/bindings.cu:qualification_graph_execution' \
        'src/bindings.cu:bool include_rollout = true'; do
        trainer_file="${trainer_contract%%:*}"
        trainer_marker="${trainer_contract#*:}"
        if ! grep -Fq "$trainer_marker" "$PUFFER/$trainer_file"; then
            echo "drift check: trainer contract marker missing: $trainer_marker" >&2
            echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
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
    TERMINAL_AWARE_TORCH_PATCH="$ROOT/training/puffer_terminal_aware_torch.patch"
    TERMINAL_AWARE_NATIVE_PATCH="$ROOT/training/puffer_terminal_aware_native.patch"
    if [ ! -f "$TERMINAL_AWARE_TORCH_PATCH" ] || \
       [ ! -f "$TERMINAL_AWARE_NATIVE_PATCH" ] || \
       ! grep -Fq 'RECURRENT_MEMORY_CONTRACT = "terminal-aware-tbptt-v1"' \
            "$PUFFER/pufferlib/torch_pufferl.py" || \
       ! patch_reverse_checks_beneath_later \
            "$TERMINAL_AWARE_TORCH_PATCH" "$TERMINAL_AWARE_NATIVE_PATCH" || \
       ! git -C "$PUFFER" apply --reverse --check --no-index \
            "$TERMINAL_AWARE_NATIVE_PATCH"; then
        echo "drift check: terminal-aware recurrent patch pair is missing or stale" >&2
        echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
        exit 1
    fi
    if ! grep -Fq 'Training uses the same direct recurrence and fp32 rounding points as rollout.' \
        "$PUFFER/src/models.cu" || \
       ! grep -Fq 'state_history' "$PUFFER/src/models.cu" || \
       ! patch_reverse_checks_beneath_later \
            "$ROOT/training/puffer_mingru_direct_recurrence_candidate.patch" \
            "${TERMINAL_AWARE_REVERSE[@]}"; then
        echo "drift check: direct min-GRU recurrence patch is missing or stale" >&2
        echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
        exit 1
    fi
    if ! patch_reverse_checks_beneath_later \
            "$ROOT/training/puffer_recurrent_cuda_qualification.patch" \
            "$ROOT/training/puffer_entropy_schedule_parity.patch" \
            "${NATIVE_DIAGNOSTICS_REVERSE[@]}" \
            "$ROOT/training/pufferl_scripted_training_guard.patch" \
            "$ROOT/training/pufferl_warm_start.patch" \
            "${TERMINAL_AWARE_REVERSE[@]}"; then
        echo "drift check: qualification patch is not exact beneath later trainer patches" >&2
        echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
        exit 1
    fi
    # The two local pufferl.py patches (scripted-training guard, warm start)
    # are outside the hashed patch bundle, so their identity is only ever
    # proven here: each must reverse-apply cleanly, which a tree still carrying
    # the v1 guard (pre scripted_bank_tag) fails. Same full-tree discriminator
    # as the install path below.
    if grep -Fq 'require_training_state_reset' "$PUFFER/pufferlib/pufferl.py"; then
        for local_pufferl_patch in \
            "$ROOT/training/pufferl_scripted_training_guard.patch" \
            "$ROOT/training/pufferl_warm_start.patch"; do
            if ! git -C "$PUFFER" apply --reverse --check --no-index "$local_pufferl_patch"; then
                echo "drift check: local pufferl.py patch is missing or stale: $local_pufferl_patch" >&2
                echo "  fix: tools/install_puffer_env.sh $PUFFER (it upgrades an installed v1 guard in place)" >&2
                exit 1
            fi
        done
    fi
    # D234: BOTH backends, checked separately, and ordered LAST among the
    # marker checks -- the earlier ones carry message-ordering contracts
    # that training/test_recurrent_cuda_qualification.py asserts against a
    # partial fixture tree. A tree with only one of these
    # trains one path on truncated rewards, and the vendored tree is gitignored
    # so a re-clone drops the edit silently.
    if ! grep -Fq 'clamp(-8, 8)' "$PUFFER/pufferlib/torch_pufferl.py"; then
        echo "drift check: torch backend still clamps rewards to +-1" >&2
        echo "  fix: tools/install_puffer_env.sh $PUFFER" >&2
        exit 1
    fi
    if ! grep -Fq -- '-8.0f, 8.0f, numel(rollouts.rewards.shape)' \
        "$PUFFER/src/pufferlib.cu"; then
        echo "drift check: CUDA backend still clamps rewards to +-1" >&2
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
        'from pufferlib import _C; print(getattr(_C, "exact_action_source_hash", "<missing>"), getattr(_C, "environment_source_hash", "<missing>"), getattr(_C, "observation_abi", "<missing>"), getattr(_C, "observation_version", "<missing>"), getattr(_C, "action_abi", "<missing>"), getattr(_C, "rollout_transition_contract", "<missing>"), getattr(_C, "entropy_schedule_contract", "<missing>"))' \
        2>/dev/null || true)"
    read -r compiled_backend_hash compiled_environment_hash \
        compiled_observation_abi compiled_observation_version \
        compiled_action_abi compiled_rollout_transition_contract \
        compiled_entropy_schedule_contract <<< "$compiled_contract"
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
       [ "$header_observation_abi" != "$SOURCE_OBSERVATION_ABI" ] || \
       [ "$compiled_observation_abi" != "$SOURCE_OBSERVATION_ABI" ] || \
       [ "$header_observation_version" != "$SOURCE_OBSERVATION_VERSION" ] || \
       [ "$compiled_observation_version" != "$SOURCE_OBSERVATION_VERSION" ] || \
       [ "$header_action_abi" != "exact-joint-v1" ] || \
       [ "$compiled_action_abi" != "exact-joint-v1" ]; then
        echo "drift check: compiled observation/action lineage mismatch" >&2
        echo "  environment source: $want" >&2
        echo "  header/module source: ${header_environment_hash:-<missing>} / ${compiled_environment_hash:-<missing>}" >&2
        echo "  source obs: $SOURCE_OBSERVATION_ABI / $SOURCE_OBSERVATION_VERSION" >&2
        echo "  header/module obs ABI: ${header_observation_abi:-<missing>} / ${compiled_observation_abi:-<missing>}" >&2
        echo "  header/module obs: ${header_observation_version:-<missing>} / ${compiled_observation_version:-<missing>}" >&2
        echo "  header/module action: ${header_action_abi:-<missing>} / ${compiled_action_abi:-<missing>}" >&2
        echo "  fix: reinstall, then rebuild PufferLib for bloodbowl" >&2
        exit 1
    fi
    if [ "$compiled_rollout_transition_contract" != \
            "terminal-aware-tbptt-v1" ] || \
       [ "$compiled_entropy_schedule_contract" != \
            "cosine-update-index-over-total-updates-fp32-v1" ]; then
        echo "drift check: compiled trainer semantic contract mismatch" >&2
        echo "  rollout: ${compiled_rollout_transition_contract:-<missing>}" >&2
        echo "  entropy: ${compiled_entropy_schedule_contract:-<missing>}" >&2
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
if [ -f "$DASHBOARD_PY" ] && ! grep -q 'def _downsample_logs' "$DASHBOARD_PY"; then
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
     ! grep -q 'def _downsample_logs' "$DASHBOARD_PY"; }; then
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

# Rollout-transition closure. Install after recurrent boundary handling so the
# final executed transition and bootstrap state obey the same reset contract.
ROLLOUT_TRANSITION_PATCH="$ROOT/training/puffer_rollout_transition_closure.patch"
if [ ! -f "$ROLLOUT_TRANSITION_PATCH" ]; then
    echo "error: missing $ROLLOUT_TRANSITION_PATCH" >&2
    exit 1
fi
if grep -Fq 'tail_observation' "$TORCH_PUFFERL_PY" && \
   grep -Fq 'tail_callback_wrapper' "$PUFFER/src/pufferlib.cu"; then
    :
elif git -C "$PUFFER" apply --check --no-index "$ROLLOUT_TRANSITION_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$ROLLOUT_TRANSITION_PATCH"
    echo "applied:   rollout-transition closure -> Puffer native/Torch backends"
else
    echo "error: rollout-transition patch is neither applicable nor installed" >&2
    exit 1
fi
if ! grep -Fq 'tail_observation' "$TORCH_PUFFERL_PY" || \
   ! grep -Fq 'tail_callback_wrapper' "$PUFFER/src/pufferlib.cu"; then
    echo "error: rollout-transition closure is incomplete" >&2
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
     ! patch_reverse_checks_beneath_later \
        "$FROZEN_PRIO_PATCH" "${TERMINAL_AWARE_REVERSE[@]}"; then
    echo "error: installed frozen-row priority-mask patch is stale" >&2
    echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
    exit 1
fi
if ! grep -q 'eligible_agents' "$PUFFER/src/pufferlib.cu"; then
    echo "error: exact frozen-row exclusion is incomplete" >&2
    exit 1
fi

# Use the same direct min-GRU recurrence and fp32 rounding points for training
# that native rollout already uses. The accepted patch name is retained so its
# canonical SHA-256 continues to identify the qualification evidence.
MINGRU_DIRECT_PATCH="$ROOT/training/puffer_mingru_direct_recurrence_candidate.patch"
if [ ! -f "$MINGRU_DIRECT_PATCH" ]; then
    echo "error: missing $MINGRU_DIRECT_PATCH" >&2
    exit 1
fi
if patch_reverse_checks_beneath_later \
        "$MINGRU_DIRECT_PATCH" "${TERMINAL_AWARE_REVERSE[@]}"; then
    :
elif git -C "$PUFFER" apply --check --no-index "$MINGRU_DIRECT_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$MINGRU_DIRECT_PATCH"
    echo "applied:   direct min-GRU training recurrence -> native CUDA backend"
else
    echo "error: direct min-GRU recurrence patch is neither exact nor applicable" >&2
    exit 1
fi
if ! grep -Fq 'Training uses the same direct recurrence and fp32 rounding points as rollout.' \
        "$PUFFER/src/models.cu" || \
   ! grep -Fq 'state_history' "$PUFFER/src/models.cu"; then
    echo "error: direct min-GRU recurrence support is incomplete" >&2
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
     ! patch_reverse_checks_beneath_later \
        "$QUALIFICATION_PATCH" \
        "$ROOT/training/puffer_entropy_schedule_parity.patch" \
            "${NATIVE_DIAGNOSTICS_REVERSE[@]}" \
        "$ROOT/training/pufferl_scripted_training_guard.patch" \
        "$ROOT/training/pufferl_warm_start.patch" \
        "${TERMINAL_AWARE_REVERSE[@]}"; then
    echo "error: installed recurrent CUDA qualification patch is stale" >&2
    echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
    exit 1
fi
if ! grep -q 'qualification_recurrent_state' "$PUFFER/src/bindings.cu" || \
   ! grep -q 'qualification_snapshot' "$PUFFER/src/bindings.cu"; then
    echo "error: recurrent CUDA qualification evidence is incomplete" >&2
    exit 1
fi

# Entropy-schedule parity. Install after all native qualification hooks because
# both touch the public binding surface; the semantic patch remains part of the
# compiled identity and its transaction guard covers those hooks.
ENTROPY_SCHEDULE_PATCH="$ROOT/training/puffer_entropy_schedule_parity.patch"
if [ ! -f "$ENTROPY_SCHEDULE_PATCH" ]; then
    echo "error: missing $ENTROPY_SCHEDULE_PATCH" >&2
    exit 1
fi
if grep -Fq 'ENTROPY_SCHEDULE_CONTRACT' "$TORCH_PUFFERL_PY" && \
   grep -Fq 'enqueue_entropy_coefficient' "$PUFFER/src/pufferlib.cu"; then
    :
elif git -C "$PUFFER" apply --check --no-index "$ENTROPY_SCHEDULE_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$ENTROPY_SCHEDULE_PATCH"
    echo "applied:   entropy-schedule objective parity -> Puffer native/Torch backends"
else
    echo "error: entropy-schedule patch is neither applicable nor installed" >&2
    exit 1
fi
if ! grep -Fq 'ENTROPY_SCHEDULE_CONTRACT' "$TORCH_PUFFERL_PY" || \
   ! grep -Fq 'enqueue_entropy_coefficient' "$PUFFER/src/pufferlib.cu"; then
    echo "error: entropy-schedule objective parity is incomplete" >&2
    exit 1
fi


# Read-only native entropy and graph execution diagnostics. These accessors
# expose existing tensors/counters; they do not alter training or graph replay.
NATIVE_ENTROPY_DIAGNOSTICS_PATCH="$ROOT/training/puffer_native_entropy_diagnostics.patch"
if [ ! -f "$NATIVE_ENTROPY_DIAGNOSTICS_PATCH" ]; then
    echo "error: missing $NATIVE_ENTROPY_DIAGNOSTICS_PATCH" >&2
    exit 1
fi
if patch_reverse_checks_beneath_later "$NATIVE_ENTROPY_DIAGNOSTICS_PATCH" \
        "${COMPACT_SNAPSHOT_REVERSE[@]}" \
        "${TERMINAL_AWARE_REVERSE[@]}"; then
    :
elif git -C "$PUFFER" apply --check --no-index "$NATIVE_ENTROPY_DIAGNOSTICS_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$NATIVE_ENTROPY_DIAGNOSTICS_PATCH"
    echo "applied:   read-only entropy gradients and graph counters -> native binding"
else
    echo "error: native entropy diagnostics patch is neither exact nor applicable" >&2
    exit 1
fi

# Keep the existing snapshot default while allowing bounded diagnostics to
# omit full rollout tensors that they do not consume.
COMPACT_SNAPSHOT_PATCH="$ROOT/training/puffer_compact_qualification_snapshot.patch"
if [ ! -f "$COMPACT_SNAPSHOT_PATCH" ]; then
    echo "error: missing $COMPACT_SNAPSHOT_PATCH" >&2
    exit 1
fi
if patch_reverse_checks_beneath_later \
        "$COMPACT_SNAPSHOT_PATCH" "${TERMINAL_AWARE_REVERSE[@]}"; then
    :
elif git -C "$PUFFER" apply --check --no-index "$COMPACT_SNAPSHOT_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$COMPACT_SNAPSHOT_PATCH"
    echo "applied:   optional compact qualification snapshot -> native binding"
else
    echo "error: compact snapshot patch is neither exact nor applicable" >&2
    exit 1
fi

# Widen the trainer's reward clamp from +-1 to +-8 in BOTH backends (D234).
# Stock Puffer truncates every reward to +-1; Blood Bowl's conceding-loser
# terminal is exactly -1.0 and the exact-PBRS payback lands on the same
# emission, so legitimate rewards were being destroyed one-sidedly and PBRS
# policy invariance was void. The Torch path is what run_synthesis_c.sh trains
# on and the CUDA path is what the production screen trains on, so patching one
# is a half-fix. Applies to both files; touched last because it is a leaf edit
# on lines no other patch in the stack goes near.
REWARD_CLAMP_PATCH="$ROOT/training/puffer_reward_clamp_range.patch"
if [ ! -f "$REWARD_CLAMP_PATCH" ]; then
    echo "error: missing $REWARD_CLAMP_PATCH" >&2
    exit 1
fi
if grep -Fq 'clamp(-8, 8)' "$TORCH_PUFFERL_PY" && \
   grep -Fq -- '-8.0f, 8.0f, numel(rollouts.rewards.shape)' \
        "$PUFFER/src/pufferlib.cu"; then
    :
else
    if git -C "$PUFFER" apply --no-index "$REWARD_CLAMP_PATCH"; then
        echo "applied:   +-8 trainer reward clamp -> Puffer native/Torch backends"
    else
        echo "error: reward-clamp range patch did not apply" >&2
        exit 1
    fi
fi
# Both backends, checked independently: a one-file install silently trains the
# torch path on truncated rewards while the CUDA path is correct (or vice
# versa), and nothing downstream would distinguish the two.
if ! grep -Fq 'clamp(-8, 8)' "$TORCH_PUFFERL_PY" || \
   ! grep -Fq -- '-8.0f, 8.0f, numel(rollouts.rewards.shape)' \
        "$PUFFER/src/pufferlib.cu"; then
    echo "error: +-8 trainer reward clamp is incomplete (needs BOTH backends)" >&2
    exit 1
fi

# Make the machine panel a single write() syscall.
#
# stdout and stderr are merged into one log file by the launchers, and each has
# its own buffer, so a panel longer than the stdout buffer is flushed in pieces
# and the other stream can land in the middle -- yielding a JSON line with rich
# dashboard box-drawing characters spliced into it. Measured: 4,755 bytes at 123
# log keys, 5,330 once Stalling telemetry took it to 144, and the live integrity
# guard correctly killed a run on "malformed machine panel ... Extra data: line 1
# column 5205". A single os.write on an O_APPEND regular file cannot be split.
#
# Done as an in-place transform rather than by growing pufferl_env_json.patch,
# because that patch sits in the MIDDLE of a serial stack: adding lines to it
# shifts pufferl.py's line numbers and breaks every later patch that targets the
# same file (measured: phase-contract at :179, eval-gate at :189, recurrent
# eval-state at :289 all failed). Same reasoning as the create_dict transform
# above. Idempotent: guarded on the marker it installs.
DASHBOARD_PY="$PUFFER/pufferlib/pufferl.py"
if [ -f "$DASHBOARD_PY" ] && \
   ! grep -Fq 'os.write(sys.stdout.fileno()' "$DASHBOARD_PY"; then
    if perl -0pi -e "s/(\\n)(\\s*)print\\('PUFFER_ENV_JSON ' \\+ json\\.dumps\\(\\n\\s*env_json, sort_keys=True, allow_nan=False\\)\\)/\\1\\2_panel = 'PUFFER_ENV_JSON ' + json.dumps(\\n\\2    env_json, sort_keys=True, allow_nan=False)\\n\\2sys.stdout.flush()\\n\\2os.write(sys.stdout.fileno(), (_panel + chr(10)).encode('utf-8'))/s" \
        "$DASHBOARD_PY" && \
       grep -Fq 'os.write(sys.stdout.fileno()' "$DASHBOARD_PY"; then
        echo "applied:   atomic machine-panel write -> pufferlib/pufferl.py"
    else
        echo "error: could not make the machine panel write atomic; a split panel" >&2
        echo "       corrupts JSON and the live integrity guard will kill the run" >&2
        exit 1
    fi
fi

# Two pufferl.py edits lived only as untracked local edits inside individual box
# checkouts until they were captured as patches. vendor/*/ is gitignored, so a
# re-clone silently dropped them, and the obs-v5 checkout never had them at all:
# it could not warm-start (run_reward_ablation.sh greps for the marker below
# before it will launch) and it had no scripted-training guard. Both are applied
# applied last, after the whole exact-action stack: the scripted guard shares its
# call sites with require_training_state_reset, which puffer_recurrent_eval_state
# installs above, so cutting it against any earlier tree does not apply.
# Only a full trainer tree can host these. require_training_state_reset is
# installed by puffer_recurrent_eval_state above, whose own completeness check
# already exits non-zero on a real tree, so its presence is a sound discriminator:
# absent means this is a partial fixture tree (training/test_recurrent_cuda_-
# qualification.py builds one to exercise the selfplay state machine alone), not a
# trainer tree with drifted patches. Hard-fail on the latter, skip the former.
if grep -Fq 'require_training_state_reset' "$PUFFER/pufferlib/pufferl.py" 2>/dev/null; then
    # The retired v1 guard predates the entropy/config stack now beneath the
    # current guard. Preserve the historical patch bytes, and only upgrade an
    # installed v1 when a shadow transaction proves that reverse-v1 followed
    # by apply-current is clean. Otherwise fail before mutating the tree: an
    # old mixed stack cannot be safely rebased in place.
    GUARD_V1_PATCH="$ROOT/training/pufferl_scripted_training_guard.v1.patch"
    if [ -f "$GUARD_V1_PATCH" ] && \
       git -C "$PUFFER" apply --reverse --check --no-index "$GUARD_V1_PATCH" 2>/dev/null; then
        GUARD_CURRENT_PATCH="$ROOT/training/pufferl_scripted_training_guard.patch"
        guard_shadow="$(mktemp -d "${TMPDIR:-/tmp}/puffer-guard-upgrade.XXXXXX")"
        mkdir -p "$guard_shadow/pufferlib"
        cp "$PUFFER/pufferlib/pufferl.py" "$guard_shadow/pufferlib/pufferl.py"
        if git -C "$guard_shadow" apply --reverse --no-index "$GUARD_V1_PATCH" \
                >/dev/null 2>&1 && \
           git -C "$guard_shadow" apply --check --no-index "$GUARD_CURRENT_PATCH" \
                >/dev/null 2>&1; then
            rm -rf "$guard_shadow"
            git -C "$PUFFER" apply --reverse --no-index "$GUARD_V1_PATCH"
            echo "reversed:  $(basename "$GUARD_V1_PATCH") <- pufferlib/pufferl.py (upgrading the scripted guard)"
        else
            rm -rf "$guard_shadow"
            echo "error: installed legacy scripted-training guard v1 cannot be upgraded" >&2
            echo "  fix: recreate a fresh pinned Puffer tree and reinstall the complete current patch stack" >&2
            exit 1
        fi
    fi
    for local_pufferl_patch in \
        "$ROOT/training/pufferl_scripted_training_guard.patch" \
        "$ROOT/training/pufferl_warm_start.patch"; do
        if [ ! -f "$local_pufferl_patch" ]; then
            echo "error: missing $local_pufferl_patch" >&2
            exit 1
        fi
        if git -C "$PUFFER" apply --reverse --check --no-index \
                "$local_pufferl_patch" 2>/dev/null; then
            : # Already installed.
        elif git -C "$PUFFER" apply --check --no-index \
                "$local_pufferl_patch" 2>/dev/null; then
            git -C "$PUFFER" apply --no-index "$local_pufferl_patch"
            echo "applied:   $(basename "$local_pufferl_patch") -> pufferlib/pufferl.py"
        else
            echo "error: $(basename "$local_pufferl_patch") is neither applicable nor already applied" >&2
            exit 1
        fi
    done
    for local_marker in 'Warm-started training from' 'guard_scripted_training'; do
        if ! grep -Fq "$local_marker" "$PUFFER/pufferlib/pufferl.py"; then
            echo "error: pufferlib/pufferl.py lacks '$local_marker' after patching" >&2
            exit 1
        fi
    done
fi

# The terminal-aware recurrent-memory contract is an atomic two-backend change.
# Apply it after every older trainer patch so its preimage is the complete
# reducer-v1 runtime, and before computing the generated backend-source hash.
TERMINAL_AWARE_TORCH_PATCH="$ROOT/training/puffer_terminal_aware_torch.patch"
TERMINAL_AWARE_NATIVE_PATCH="$ROOT/training/puffer_terminal_aware_native.patch"
for terminal_aware_patch in \
        "$TERMINAL_AWARE_TORCH_PATCH" "$TERMINAL_AWARE_NATIVE_PATCH"; do
    if [ ! -f "$terminal_aware_patch" ]; then
        echo "error: missing $terminal_aware_patch" >&2
        exit 1
    fi
done
if patch_reverse_checks_beneath_later \
        "$TERMINAL_AWARE_TORCH_PATCH" "$TERMINAL_AWARE_NATIVE_PATCH"; then
    :
elif git -C "$PUFFER" apply --check --no-index \
        "$TERMINAL_AWARE_TORCH_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$TERMINAL_AWARE_TORCH_PATCH"
    echo "applied:   terminal-aware TBPTT -> Puffer Torch backend"
else
    echo "error: terminal-aware Torch patch is neither exact nor applicable" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$TERMINAL_AWARE_NATIVE_PATCH" 2>/dev/null; then
    :
elif git -C "$PUFFER" apply --check --no-index \
        "$TERMINAL_AWARE_NATIVE_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$TERMINAL_AWARE_NATIVE_PATCH"
    echo "applied:   terminal-aware TBPTT -> Puffer native backends"
else
    echo "error: terminal-aware native patch is neither exact nor applicable" >&2
    exit 1
fi
if ! grep -Fq 'RECURRENT_MEMORY_CONTRACT = "terminal-aware-tbptt-v1"' \
        "$TORCH_PUFFERL_PY" || \
   ! grep -R -Fq 'terminal-aware-tbptt-v1' \
        "$PUFFER/src/bindings.cu" "$PUFFER/src/bindings_cpu.cpp"; then
    echo "error: terminal-aware-tbptt-v1 is incomplete across backends" >&2
    exit 1
fi

EXACT_BACKEND_HASH="$(exact_backend_hash)" || {
    echo "error: could not hash exact-action backend sources" >&2
    exit 1
}
INSTALLED_SOURCE_HASH="$(cat "$DST/.content_hash")"
printf '#pragma once\n#define PUFFER_EXACT_ACTION_SOURCE_HASH "%s"\n#define PUFFER_ENV_SOURCE_HASH "%s"\n#define PUFFER_OBSERVATION_ABI "%s"\n#define PUFFER_OBSERVATION_VERSION %s\n#define PUFFER_ACTION_ABI "exact-joint-v1"\n' \
    "$EXACT_BACKEND_HASH" "$INSTALLED_SOURCE_HASH" \
    "$SOURCE_OBSERVATION_ABI" "$SOURCE_OBSERVATION_VERSION" \
    > "$PUFFER/src/exact_action_build_hash.h"
echo "recorded:   exact-action backend digest $EXACT_BACKEND_HASH"

echo "installed: $DST"
echo "           $PUFFER/config/bloodbowl.ini"
echo "build:     cd $PUFFER && ./build.sh bloodbowl          # CUDA training backend"
echo "           cd $PUFFER && ./build.sh bloodbowl --fast   # standalone benchmark"
