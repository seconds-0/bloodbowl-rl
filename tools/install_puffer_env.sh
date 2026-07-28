#!/usr/bin/env bash
# Install/refresh the bloodbowl env into the vendored PufferLib tree.
#
# puffer/bloodbowl/ holds the source of truth; its engine/ and bb/ symlinks
# (-> ../../engine/{src,include/bb}) are dereferenced here (cp -RL) so the
# installed ocean/bloodbowl/ is self-contained. Pinned build.sh omits
# `-I$SRC_DIR` from standalone builds, so the exact tracked include patch below
# supplies it; vendor/PufferLib can then be rsynced to a GPU box as-is.
#
# Usage: tools/install_puffer_env.sh [path-to-pufferlib]   (default: vendor/PufferLib)
#        tools/install_puffer_env.sh --check [path-to-pufferlib]
#
# The seven --state-bank-* arguments below are a reserved, all-or-none form.
# They are fully parsed, hash checked, and schema reconciled, but production
# authorization is intentionally empty in this tranche, so the request always
# exits with NO_AUTHORIZED_PRODUCER before this script mutates PufferLib.
#
# --check is the drift guard (adversarial review LOW): the GPU run compiles
# the installed snapshot, NOT engine/src — an engine edit without a re-install
# silently trains on stale rules. Run it before any build on a training box /
# in CI; exit 1 means re-run the install.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PINNED_PUFFER_COMMIT="9836f0d2e78889c1aaf189c04d161b6fc61a9386"
INSTALL_PYTHON="${PUFFER_INSTALL_PYTHON:-python3}"
[ -n "$INSTALL_PYTHON" ] && command -v "$INSTALL_PYTHON" >/dev/null || {
    echo "error: installer Python is unavailable: $INSTALL_PYTHON" >&2
    exit 2
}
MODE=install
PUFFER_ARG=""
STATE_BANK_KIND=""
STATE_BANK_SOURCE=""
STATE_BANK_SHA256=""
STATE_BANK_PRODUCER_MANIFEST_SOURCE=""
STATE_BANK_PRODUCER_MANIFEST_SHA256=""
STATE_BANK_CONTRACT_SOURCE=""
STATE_BANK_CONTRACT_SHA256=""
BANK_ARGUMENT_COUNT=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --check)
            [ "$MODE" = install ] || {
                echo "error: duplicate --check" >&2; exit 2; }
            MODE=check
            shift
            ;;
        --state-bank-kind)
            [ "$#" -ge 2 ] || {
                echo "error: --state-bank-kind requires a value" >&2; exit 2; }
            [ -n "$2" ] && [ -z "$STATE_BANK_KIND" ] || {
                echo "error: duplicate or empty --state-bank-kind" >&2; exit 2; }
            STATE_BANK_KIND="$2"
            BANK_ARGUMENT_COUNT=$((BANK_ARGUMENT_COUNT + 1))
            shift 2
            ;;
        --state-bank)
            [ "$#" -ge 2 ] || {
                echo "error: --state-bank requires a value" >&2; exit 2; }
            [ -n "$2" ] && [ -z "$STATE_BANK_SOURCE" ] || {
                echo "error: duplicate or empty --state-bank" >&2; exit 2; }
            STATE_BANK_SOURCE="$2"
            BANK_ARGUMENT_COUNT=$((BANK_ARGUMENT_COUNT + 1))
            shift 2
            ;;
        --state-bank-sha256)
            [ "$#" -ge 2 ] || {
                echo "error: --state-bank-sha256 requires a value" >&2; exit 2; }
            [ -n "$2" ] && [ -z "$STATE_BANK_SHA256" ] || {
                echo "error: duplicate or empty --state-bank-sha256" >&2; exit 2; }
            STATE_BANK_SHA256="$2"
            BANK_ARGUMENT_COUNT=$((BANK_ARGUMENT_COUNT + 1))
            shift 2
            ;;
        --state-bank-producer-manifest)
            [ "$#" -ge 2 ] || {
                echo "error: --state-bank-producer-manifest requires a value" >&2
                exit 2
            }
            [ -n "$2" ] && \
                [ -z "$STATE_BANK_PRODUCER_MANIFEST_SOURCE" ] || {
                echo "error: duplicate or empty --state-bank-producer-manifest" >&2
                exit 2
            }
            STATE_BANK_PRODUCER_MANIFEST_SOURCE="$2"
            BANK_ARGUMENT_COUNT=$((BANK_ARGUMENT_COUNT + 1))
            shift 2
            ;;
        --state-bank-producer-manifest-sha256)
            [ "$#" -ge 2 ] || {
                echo "error: --state-bank-producer-manifest-sha256 requires a value" >&2
                exit 2
            }
            [ -n "$2" ] && \
                [ -z "$STATE_BANK_PRODUCER_MANIFEST_SHA256" ] || {
                echo "error: duplicate or empty --state-bank-producer-manifest-sha256" >&2
                exit 2
            }
            STATE_BANK_PRODUCER_MANIFEST_SHA256="$2"
            BANK_ARGUMENT_COUNT=$((BANK_ARGUMENT_COUNT + 1))
            shift 2
            ;;
        --state-bank-contract)
            [ "$#" -ge 2 ] || {
                echo "error: --state-bank-contract requires a value" >&2; exit 2; }
            [ -n "$2" ] && [ -z "$STATE_BANK_CONTRACT_SOURCE" ] || {
                echo "error: duplicate or empty --state-bank-contract" >&2; exit 2; }
            STATE_BANK_CONTRACT_SOURCE="$2"
            BANK_ARGUMENT_COUNT=$((BANK_ARGUMENT_COUNT + 1))
            shift 2
            ;;
        --state-bank-contract-sha256)
            [ "$#" -ge 2 ] || {
                echo "error: --state-bank-contract-sha256 requires a value" >&2
                exit 2
            }
            [ -n "$2" ] && [ -z "$STATE_BANK_CONTRACT_SHA256" ] || {
                echo "error: duplicate or empty --state-bank-contract-sha256" >&2
                exit 2
            }
            STATE_BANK_CONTRACT_SHA256="$2"
            BANK_ARGUMENT_COUNT=$((BANK_ARGUMENT_COUNT + 1))
            shift 2
            ;;
        --*)
            echo "error: unknown installer option: $1" >&2
            exit 2
            ;;
        *)
            [ -z "$PUFFER_ARG" ] || {
                echo "error: multiple PufferLib paths supplied" >&2; exit 2; }
            PUFFER_ARG="$1"
            shift
            ;;
    esac
done

if [ "$BANK_ARGUMENT_COUNT" -ne 0 ] && [ "$BANK_ARGUMENT_COUNT" -ne 7 ]; then
    echo "error: state-bank arguments are all-or-none" >&2
    exit 2
fi
if [ "$MODE" = check ] && [ "$BANK_ARGUMENT_COUNT" -ne 0 ]; then
    echo "error: --check does not accept state-bank source arguments" >&2
    exit 2
fi
if [ "$BANK_ARGUMENT_COUNT" -eq 7 ]; then
    # This call is deliberately before even validating the destination tree.
    # Its public authorization allowlist is a literal empty frozenset, so a
    # completely valid request still fails before any installation mutation.
    if "$INSTALL_PYTHON" "$ROOT/tools/state_bank_contract.py" validate-request \
        --kind "$STATE_BANK_KIND" \
        --bank "$STATE_BANK_SOURCE" \
        --bank-sha256 "$STATE_BANK_SHA256" \
        --producer-manifest "$STATE_BANK_PRODUCER_MANIFEST_SOURCE" \
        --producer-manifest-sha256 \
            "$STATE_BANK_PRODUCER_MANIFEST_SHA256" \
        --training-contract "$STATE_BANK_CONTRACT_SOURCE" \
        --training-contract-sha256 "$STATE_BANK_CONTRACT_SHA256" \
        --engine-root "$ROOT"; then
        echo "error: production state-bank authorization unexpectedly succeeded" >&2
        exit 2
    else
        status=$?
        exit "$status"
    fi
fi

PUFFER="${PUFFER_ARG:-$ROOT/vendor/PufferLib}"

[ -f "$PUFFER/build.sh" ] || { echo "error: $PUFFER is not a PufferLib tree" >&2; exit 1; }
PUFFER="$(cd "$PUFFER" && pwd -P)"
if ! PUFFER_GIT_ROOT="$(
    git -C "$PUFFER" rev-parse --show-toplevel 2>/dev/null
)"; then
    echo "error: $PUFFER is not a PufferLib Git worktree" >&2
    exit 1
fi
PUFFER_GIT_ROOT="$(cd "$PUFFER_GIT_ROOT" && pwd -P)"
if [ "$PUFFER_GIT_ROOT" != "$PUFFER" ]; then
    echo "error: PufferLib path is not the Git worktree root: $PUFFER" >&2
    exit 1
fi
if ! PUFFER_HEAD="$(
    git -C "$PUFFER" rev-parse --verify "HEAD^{commit}" 2>/dev/null
)"; then
    echo "error: PufferLib HEAD cannot be resolved" >&2
    exit 1
fi
if [ "$PUFFER_HEAD" != "$PINNED_PUFFER_COMMIT" ]; then
    echo "error: PufferLib HEAD must be $PINNED_PUFFER_COMMIT; found $PUFFER_HEAD" >&2
    exit 1
fi

DST="$PUFFER/ocean/bloodbowl"
SELFPLAY_LEAGUE_PATCH="$ROOT/training/selfplay_league.patch"
STANDALONE_INCLUDE_PATCH="$ROOT/training/puffer_standalone_env_include.patch"
EXACT_PATCH="$ROOT/training/puffer_exact_joint_actions.patch"
RECURRENT_PATCH="$ROOT/training/puffer_recurrent_eval_state.patch"
ROLLOUT_TRANSITION_PATCH="$ROOT/training/puffer_rollout_transition_closure.patch"
FROZEN_PRIO_PATCH="$ROOT/training/puffer_frozen_prio_mask.patch"
QUALIFICATION_PATCH="$ROOT/training/puffer_recurrent_cuda_qualification.patch"
REWARD_CLAMP_PATCH="$ROOT/training/puffer_reward_clamp_range.patch"
STATE_BANK_EXPORT_PATCH="$ROOT/training/puffer_state_bank_contract.patch"
STRICT_ENV_CONFIG_PATCH="$ROOT/training/puffer_strict_environment_config.patch"
COMPILED_BACKEND_LEDGER="$ROOT/training/puffer_compiled_backend_sources.txt"

# The observation revision is DERIVED from the header, never typed twice. The
# generated build header and the --check gate both used to carry their own
# literal, so an obs bump had to be edited in three places or the compiled
# module would advertise the previous revision -- with no symptom, because
# every observation revision since v4 has been 2782 bytes.
ENV_HEADER="$ROOT/puffer/bloodbowl/bloodbowl.h"
[ -f "$ENV_HEADER" ] || {
    echo "error: missing $ENV_HEADER" >&2; exit 1; }
SOURCE_OBSERVATION_VERSION="$(sed -n \
    's/^#define BBE_OBS_VERSION \([0-9][0-9]*\).*$/\1/p' "$ENV_HEADER" | head -1)"
[ -n "$SOURCE_OBSERVATION_VERSION" ] || {
    echo "error: could not read BBE_OBS_VERSION from $ENV_HEADER" >&2; exit 1; }
SOURCE_OBSERVATION_ABI="obs-v$SOURCE_OBSERVATION_VERSION"

# Content hash of a tree with symlinks dereferenced (the puffer/bloodbowl
# engine/ and bb/ links reach into engine/src and engine/include/bb, so any
# engine change changes the hash). Relative paths keep source and snapshot
# hashes comparable.
snapshot_hash() {
    "$INSTALL_PYTHON" "$ROOT/tools/state_bank_contract.py" \
        environment-source-sha256 --root "$1" --plain
}

# Hash every source that defines exact-action transport, sampling, or recurrent
# evaluation semantics. The installer writes this digest into a generated
# header; both native and CPU extension modules expose the compiled value.
# --check then compares current sources, generated header, and imported module.
exact_backend_hash() {
    "$INSTALL_PYTHON" "$ROOT/tools/puffer_source_manifest.py" \
        --root "$PUFFER" \
        --ledger "$COMPILED_BACKEND_LEDGER" \
        --expected-count 14 \
        --require-native-extension-closure \
        --plain
}

rollout_transition_sources_valid() {
    grep -Fq 'tail_observation' \
        "$PUFFER/pufferlib/torch_pufferl.py" || return 1
    grep -Fq 'tail_callback_wrapper' \
        "$PUFFER/src/pufferlib.cu" || return 1
    grep -Fq 'tail_rollout_cudagraphs' \
        "$PUFFER/src/pufferlib.cu" || return 1
    grep -Fq 'for (int t = horizon - 1; t >= 0; t--)' \
        "$PUFFER/src/bindings_cpu.cpp" || return 1
    grep -Fq 'for (int t = horizon - 1; t >= 0; t--)' \
        "$PUFFER/src/pufferlib.cu" || return 1
    for binding in \
        "$PUFFER/src/bindings.cu" \
        "$PUFFER/src/bindings_cpu.cpp"; do
        grep -Fq \
            'm.attr("rollout_transition_contract") = "tail-bootstrap-v1";' \
            "$binding" || return 1
    done
}

strict_environment_config_sources_valid() {
    local helper_definitions constructor_calls binding
    grep -Fq '#define PUFFER_HAS_STRICT_ENV_CONFIG 1' \
        "$DST/binding.c" || return 1
    grep -Fq \
        "grep -Fxq '#define PUFFER_HAS_STRICT_ENV_CONFIG 1' \"\$BINDING_SRC\"" \
        "$PUFFER/build.sh" || return 1
    grep -Fq 'STRICT_ENV_CONFIG_CFLAGS="-DPUFFER_STRICT_ENV_CONFIG=1"' \
        "$PUFFER/build.sh" || return 1
    grep -Fq 'PUFFER_STRICT_ENV_CONFIG_TESTING=1' \
        "$PUFFER/build.sh" || return 1

    helper_definitions="$(
        grep -Fh \
            'static py::dict bloodbowl_normalize_and_preflight_env(py::dict source)' \
            "$PUFFER/src/bindings.cu" "$PUFFER/src/bindings_cpu.cpp" |
            wc -l | tr -d ' '
    )"
    constructor_calls="$(
        grep -Fh \
            'env_kwargs = bloodbowl_normalize_and_preflight_env(env_kwargs);' \
            "$PUFFER/src/bindings.cu" "$PUFFER/src/bindings_cpu.cpp" |
            wc -l | tr -d ' '
    )"
    [ "$helper_definitions" -eq 2 ] || return 1
    [ "$constructor_calls" -eq 3 ] || return 1

    for binding in \
            "$PUFFER/src/bindings.cu" \
            "$PUFFER/src/bindings_cpu.cpp"; do
        grep -Fq 'PyUnicode_AsUTF8AndSize' "$binding" || return 1
        grep -Fq 'my_environment_config_preflight(' "$binding" || return 1
        grep -Fq 'm.attr("environment_config_schema")' "$binding" || return 1
        grep -Fq 'm.attr("strict_env_config_testing")' "$binding" || return 1
    done
    grep -Fq \
        'Dict* env_dict = py_dict_to_c_dict(env_kwargs.cast<py::dict>());' \
        "$PUFFER/src/bindings.cu" || return 1
}

if [ "$MODE" = "check" ]; then
    [ -d "$DST" ] || { echo "drift check: $DST not installed — run tools/install_puffer_env.sh" >&2; exit 1; }
    want="$(snapshot_hash "$ROOT/puffer/bloodbowl")"
    installed="$(snapshot_hash "$DST")"
    have="$(cat "$DST/.content_hash" 2>/dev/null || echo "<none>")"
    if [ "$want" != "$installed" ] || [ "$want" != "$have" ]; then
        echo "drift check: STALE snapshot — engine/src or puffer/bloodbowl changed since install" >&2
        echo "  source now: $want" >&2
        echo "  installed:  $installed" >&2
        echo "  recorded:   $have" >&2
        echo "  fix: tools/install_puffer_env.sh $PUFFER" >&2
        exit 1
    fi
    if ! "$INSTALL_PYTHON" "$ROOT/tools/state_bank_contract.py" check-no-bank \
        --puffer-root "$PUFFER" >/dev/null; then
        echo "drift check: installed no-bank state contract is stale" >&2
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
    if ! rollout_transition_sources_valid; then
        echo "drift check: rollout-transition closure is incomplete" >&2
        echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
        exit 1
    fi
    for qualification_marker in \
        'eligible_agents' \
        'qualification_recurrent_state' \
        'qualification_policy_weights' \
        'qualification_snapshot'; do
        if ! grep -R -Fq "$qualification_marker" \
            "$PUFFER/src/pufferlib.cu" "$PUFFER/src/bindings.cu"; then
            echo "drift check: recurrent CUDA qualification marker missing: $qualification_marker" >&2
            echo "  fix: run tools/install_puffer_env.sh $PUFFER" >&2
            exit 1
        fi
    done
    if ! strict_environment_config_sources_valid; then
        echo "drift check: strict Blood Bowl environment boundary is incomplete" >&2
        echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
        exit 1
    fi
    if ! git -C "$PUFFER" apply --reverse --check --no-index "$STANDALONE_INCLUDE_PATCH"; then
        echo "drift check: installed standalone include patch is missing or stale" >&2
        echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
        exit 1
    fi
    for exact_patch in \
        "$EXACT_PATCH" \
        "$RECURRENT_PATCH" \
        "$ROLLOUT_TRANSITION_PATCH" \
        "$FROZEN_PRIO_PATCH" \
        "$QUALIFICATION_PATCH" \
        "$REWARD_CLAMP_PATCH" \
        "$ROOT/training/pufferl_scripted_training_guard.patch" \
        "$ROOT/training/pufferl_warm_start.patch" \
        "$ROOT/training/puffer_dict_capacity.patch" \
        "$STATE_BANK_EXPORT_PATCH" \
        "$STRICT_ENV_CONFIG_PATCH"; do
        if ! git -C "$PUFFER" apply --reverse --check --no-index "$exact_patch"; then
            echo "drift check: installed exact patch is missing or stale: $exact_patch" >&2
            echo "  fix: recreate the pinned Puffer tree and reinstall the complete patch stack" >&2
            exit 1
        fi
    done
    # D234: BOTH backends, checked separately, and ordered LAST among the
    # marker checks -- the earlier ones carry message-ordering contracts
    # that training/test_recurrent_cuda_qualification.py asserts against a
    # partial fixture tree. A tree with only one of these
    # trains one path on truncated rewards, and the vendored tree is gitignored
    # so a re-clone drops the edit silently.
    if ! grep -Fq \
        'self.rewards.T.contiguous().clamp(-8, 8)' \
        "$PUFFER/pufferlib/torch_pufferl.py"; then
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
        'from pufferlib import _C; print(getattr(_C, "exact_action_source_hash", "<missing>"), getattr(_C, "environment_source_hash", "<missing>"), getattr(_C, "observation_abi", "<missing>"), getattr(_C, "observation_version", "<missing>"), getattr(_C, "action_abi", "<missing>"), getattr(_C, "rollout_transition_contract", "<missing>"), getattr(_C, "environment_config_schema", "<missing>"), getattr(_C, "strict_env_config_testing", "<missing>"))' \
        2>/dev/null || true)"
    read -r compiled_backend_hash compiled_environment_hash \
        compiled_observation_abi compiled_observation_version \
        compiled_action_abi compiled_rollout_transition_contract \
        compiled_environment_config_schema \
        compiled_strict_env_config_testing <<< "$compiled_contract"
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
       [ "$compiled_action_abi" != "exact-joint-v1" ] || \
       [ "$compiled_rollout_transition_contract" != "tail-bootstrap-v1" ] || \
       [ "$compiled_environment_config_schema" != \
            "bloodbowl-environment-config-v1" ] || \
       [ "$compiled_strict_env_config_testing" != "False" ]; then
        echo "drift check: compiled observation/action/config lineage mismatch" >&2
        echo "  environment source: $want" >&2
        echo "  header/module source: ${header_environment_hash:-<missing>} / ${compiled_environment_hash:-<missing>}" >&2
        echo "  source obs: $SOURCE_OBSERVATION_ABI / $SOURCE_OBSERVATION_VERSION" >&2
        echo "  header/module obs ABI: ${header_observation_abi:-<missing>} / ${compiled_observation_abi:-<missing>}" >&2
        echo "  header/module obs: ${header_observation_version:-<missing>} / ${compiled_observation_version:-<missing>}" >&2
        echo "  header/module action: ${header_action_abi:-<missing>} / ${compiled_action_abi:-<missing>}" >&2
        echo "  module rollout transition: ${compiled_rollout_transition_contract:-<missing>}" >&2
        echo "  module environment config: ${compiled_environment_config_schema:-<missing>}" >&2
        echo "  module strict test role: ${compiled_strict_env_config_testing:-<missing>}" >&2
        echo "  fix: reinstall, then rebuild PufferLib for bloodbowl" >&2
        exit 1
    fi
    installed_state_contract="$(
        "$INSTALL_PYTHON" "$ROOT/tools/state_bank_contract.py" show-installed \
            --puffer-root "$PUFFER"
    )"
    compiled_state_contract="$(cd "$PUFFER" && \
        "$PYBIN" - "$ROOT/tools" <<'PY'
import json
import sys

sys.path.insert(0, sys.argv[1])
import state_bank_contract
from pufferlib import _C

print(json.dumps(
    state_bank_contract.contract_from_module(_C),
    sort_keys=True,
    separators=(",", ":"),
))
PY
    )"
    if [ "$installed_state_contract" != "$compiled_state_contract" ]; then
        echo "drift check: compiled state-bank contract differs from generated authority" >&2
        echo "  header: $installed_state_contract" >&2
        echo "  module: $compiled_state_contract" >&2
        echo "  fix: reinstall, then rebuild PufferLib for bloodbowl" >&2
        exit 1
    fi
    STANDALONE="$PUFFER/bloodbowl"
    if [ ! -x "$STANDALONE" ]; then
        echo "drift check: installed standalone is missing: $STANDALONE" >&2
        echo "  fix: cd $PUFFER && ./build.sh bloodbowl --fast" >&2
        exit 1
    fi
    standalone_state_contract="$(
        "$STANDALONE" --state-bank-contract | "$INSTALL_PYTHON" -c \
            'import json,sys; print(json.dumps(json.load(sys.stdin), sort_keys=True, separators=(",", ":")))'
    )" || {
        echo "drift check: standalone state-bank metadata is malformed" >&2
        exit 1
    }
    if [ "$installed_state_contract" != "$standalone_state_contract" ]; then
        echo "drift check: standalone state-bank contract differs from generated authority" >&2
        echo "  header:     $installed_state_contract" >&2
        echo "  standalone: $standalone_state_contract" >&2
        echo "  fix: reinstall, then rebuild PufferLib for bloodbowl" >&2
        exit 1
    fi
    if [ ! "$current_module" -nt "$DST/.content_hash" ] || \
       [ ! "$current_module" -nt "$DST/state_bank_build.h" ] || \
       [ ! "$current_module" -nt "$PUFFER/src/exact_action_build_hash.h" ] || \
       [ ! "$STANDALONE" -nt "$DST/.content_hash" ] || \
       [ ! "$STANDALONE" -nt "$DST/state_bank_build.h" ] || \
       [ ! "$STANDALONE" -nt "$PUFFER/src/exact_action_build_hash.h" ]; then
        echo "drift check: compiled outputs predate the installed snapshot or generated contract" >&2
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

# PufferLib's pinned standalone build flags omit the environment root. The
# dereferenced snapshot has engine/bb/*.h headers that include bb/*.h, so local
# and fast builds need this one exact build-recipe patch. Reverse applicability
# is the durable installed-state check; a marker alone could accept a partial
# or hand-edited build.sh.
if [ ! -f "$STANDALONE_INCLUDE_PATCH" ]; then
    echo "error: missing $STANDALONE_INCLUDE_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index "$STANDALONE_INCLUDE_PATCH" 2>/dev/null; then
    : # Exact standalone include patch is already installed.
elif git -C "$PUFFER" apply --check --no-index "$STANDALONE_INCLUDE_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$STANDALONE_INCLUDE_PATCH"
    echo "applied:   standalone environment include root -> build.sh"
else
    echo "error: standalone include patch is neither applicable nor already applied" >&2
    exit 1
fi
if ! git -C "$PUFFER" apply --reverse --check --no-index "$STANDALONE_INCLUDE_PATCH"; then
    echo "error: installed standalone include patch is stale or incomplete" >&2
    exit 1
fi

# Stage FFB spectator art (optional — needs vendor/ffb and a python with yaml;
# training and the fallback circle renderer work fine without it).
if [ -d "$ROOT/vendor/ffb" ] && [ -x "$PUFFER/.venv/bin/python" ]; then
    "$PUFFER/.venv/bin/python" "$ROOT/tools/stage_spectator_art.py" || \
        echo "warning: spectator art staging failed (renderer falls back to circles)"
fi

# No bank arguments mean an explicit no-bank transaction.  Delete only the
# three contract-owned resource names.  The shared publisher repeats this
# cleanup and fsyncs the directory immediately before publishing the generated
# no-bank authority last.
STATE_BANK_RESOURCE_DIR="$PUFFER/resources/bloodbowl"
STATE_BANK_BBS_DST="$STATE_BANK_RESOURCE_DIR/state_bank.bbs"
STATE_BANK_PRODUCER_MANIFEST_DST="$STATE_BANK_RESOURCE_DIR/state_bank.producer.json"
STATE_BANK_CONTRACT_DST="$STATE_BANK_RESOURCE_DIR/state_bank.contract.json"
mkdir -p "$STATE_BANK_RESOURCE_DIR"
rm -f \
    "$STATE_BANK_BBS_DST" \
    "$STATE_BANK_PRODUCER_MANIFEST_DST" \
    "$STATE_BANK_CONTRACT_DST"

# Blood Bowl emits 152 ordinary keys and vecenv appends "n". The exact patch
# widens all four reachable dictionaries (native train/eval plus generic
# CPU/CUDA vector logs) and preserves the release-build capacity abort. It is
# applied before later overlapping backend patches.
DICT_CAPACITY_PATCH="$ROOT/training/puffer_dict_capacity.patch"
if [ ! -f "$DICT_CAPACITY_PATCH" ]; then
    echo "error: missing $DICT_CAPACITY_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$DICT_CAPACITY_PATCH" 2>/dev/null; then
    : # Exact capacity patch is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$DICT_CAPACITY_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$DICT_CAPACITY_PATCH"
    echo "applied:   exact log-dictionary capacity guard -> Puffer backends"
else
    echo "error: dictionary-capacity patch is neither applicable nor installed" >&2
    exit 1
fi
bindings_cuda_capacity_count="$(
    awk 'index($0, "create_dict(160)") { count++ }
         END { print count + 0 }' "$PUFFER/src/bindings.cu"
)"
bindings_cpu_capacity_count="$(
    awk 'index($0, "create_dict(160)") { count++ }
         END { print count + 0 }' "$PUFFER/src/bindings_cpu.cpp"
)"
pufferlib_capacity_count="$(
    awk 'index($0, "create_dict(160)") { count++ }
         END { print count + 0 }' "$PUFFER/src/pufferlib.cu"
)"
if ! git -C "$PUFFER" apply --reverse --check --no-index \
        "$DICT_CAPACITY_PATCH" || \
   [ "$bindings_cuda_capacity_count" -ne 2 ] || \
   [ "$bindings_cpu_capacity_count" -ne 1 ] || \
   [ "$pufferlib_capacity_count" -ne 1 ] || \
   ! grep -Fq 'dict_set: capacity %d exceeded' "$PUFFER/src/vecenv.h"; then
    echo "error: installed dictionary-capacity contract is incomplete" >&2
    exit 1
fi

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
# Bowl emits 152 plus vecenv's `n`; without this patch, later correctness and
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
if [ ! -f "$EXACT_PATCH" ]; then
    echo "error: missing $EXACT_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$EXACT_PATCH" 2>/dev/null; then
    : # Exact joint-action patch is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$EXACT_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$EXACT_PATCH"
    echo "applied:   exact joint-action sampling -> Puffer native/Torch backends"
else
    echo "error: exact joint-action patch is neither applicable nor installed" >&2
    exit 1
fi
if ! grep -q 'sample_joint_logits' "$TORCH_PUFFERL_PY" || \
   ! grep -q 'joint_action_offsets' "$PUFFER/src/vecenv.h" || \
   ! grep -q 'Exact sequential support' "$PUFFER/src/pufferlib.cu" || \
   ! git -C "$PUFFER" apply --reverse --check --no-index "$EXACT_PATCH"; then
    echo "error: exact joint-action backend support is incomplete" >&2
    exit 1
fi

# Recurrent evaluation contract. Apply only after exact-action support because
# both patches extend the same native and Torch rollout paths.
if [ ! -f "$RECURRENT_PATCH" ]; then
    echo "error: missing $RECURRENT_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$RECURRENT_PATCH" 2>/dev/null; then
    : # Exact recurrent evaluation-state patch is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$RECURRENT_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$RECURRENT_PATCH"
    echo "applied:   recurrent evaluation-state boundaries -> Puffer native/Torch backends"
else
    echo "error: recurrent evaluation-state patch is neither applicable nor installed" >&2
    exit 1
fi
if ! grep -q 'reset_recurrent_state_on_terminal' "$PUFFER/src/pufferlib.cu" || \
   ! grep -q 'set_evaluation_mode' "$PUFFER/src/bindings.cu" || \
   ! grep -q 'pending_terminals' "$TORCH_PUFFERL_PY" || \
   ! git -C "$PUFFER" apply --reverse --check --no-index "$RECURRENT_PATCH"; then
    echo "error: recurrent evaluation-state support is incomplete" >&2
    exit 1
fi

# Rollout-transition closure. The final post-action observation/reward/terminal
# must be valued before any PPO update, and its identity is part of the loaded
# extension contract. This patch is causally after recurrent boundary handling
# and before frozen-bank routing and qualification.
if [ ! -f "$ROLLOUT_TRANSITION_PATCH" ]; then
    echo "error: missing $ROLLOUT_TRANSITION_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$ROLLOUT_TRANSITION_PATCH" 2>/dev/null; then
    : # Exact rollout-transition patch is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$ROLLOUT_TRANSITION_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$ROLLOUT_TRANSITION_PATCH"
    echo "applied:   rollout-transition closure -> Puffer native/Torch backends"
else
    echo "error: rollout-transition patch is neither applicable nor installed" >&2
    exit 1
fi
if ! rollout_transition_sources_valid || \
   ! git -C "$PUFFER" apply --reverse --check --no-index "$ROLLOUT_TRANSITION_PATCH"; then
    echo "error: installed rollout-transition closure is incomplete" >&2
    exit 1
fi

# Frozen PPO rows must be mathematically ineligible for priority sampling;
# zero advantages are insufficient when alpha=0 because pow(0, 0) is one.
if [ ! -f "$FROZEN_PRIO_PATCH" ]; then
    echo "error: missing $FROZEN_PRIO_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$FROZEN_PRIO_PATCH" 2>/dev/null; then
    : # Exact frozen-priority patch is already installed.
elif git -C "$PUFFER" apply --check --no-index "$FROZEN_PRIO_PATCH" \
        2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$FROZEN_PRIO_PATCH"
    echo "applied:   exact frozen-row exclusion -> prioritized PPO sampler"
else
    echo "error: frozen-row priority-mask patch is neither applicable nor installed" >&2
    exit 1
fi
if ! grep -Fq 'eligible_agents' "$PUFFER/src/pufferlib.cu" || \
   ! git -C "$PUFFER" apply --reverse --check --no-index \
       "$FROZEN_PRIO_PATCH"; then
    echo "error: installed frozen-row priority-mask patch is incomplete" >&2
    exit 1
fi

# Bounded CUDA qualification surfaces. Apply after the semantic patches: most
# calls are readbacks, while recurrent-state clear and explicit tail
# consumption are narrow, named qualification mutations whose before/after
# state is validated. They belong to the same compiled backend identity.
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
   ! grep -q 'qualification_policy_weights' "$PUFFER/src/bindings.cu" || \
   ! grep -q 'qualification_snapshot' "$PUFFER/src/bindings.cu" || \
   ! grep -q 'qualification_graph_execution' "$PUFFER/src/bindings.cu" || \
   ! grep -q 'qualification_consume_tail' "$PUFFER/src/bindings.cu"; then
    echo "error: recurrent CUDA qualification evidence is incomplete" >&2
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
if [ ! -f "$REWARD_CLAMP_PATCH" ]; then
    echo "error: missing $REWARD_CLAMP_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$REWARD_CLAMP_PATCH" 2>/dev/null; then
    : # Exact two-backend reward clamp is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$REWARD_CLAMP_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$REWARD_CLAMP_PATCH"
    echo "applied:   +-8 trainer reward clamp -> Puffer native/Torch backends"
else
    echo "error: reward-clamp range patch is neither applicable nor installed" >&2
    exit 1
fi
# Both backends, checked independently: a one-file install silently trains the
# torch path on truncated rewards while the CUDA path is correct (or vice
# versa), and nothing downstream would distinguish the two.
if ! grep -Fq \
        'self.rewards.T.contiguous().clamp(-8, 8)' \
        "$TORCH_PUFFERL_PY" || \
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
# eval-state at :289 all failed). Idempotent: guarded on the marker it installs.
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

# Export every generated state-bank contract field from both extension
# backends.  This patch is part of exact_backend_hash()'s closure, so a stale
# one-backend module cannot retain the previous backend digest.
if [ ! -f "$STATE_BANK_EXPORT_PATCH" ]; then
    echo "error: missing $STATE_BANK_EXPORT_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$STATE_BANK_EXPORT_PATCH" 2>/dev/null; then
    : # Exact export patch is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$STATE_BANK_EXPORT_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$STATE_BANK_EXPORT_PATCH"
    echo "applied:   compiled state-bank contract exports -> CPU/CUDA bindings"
else
    echo "error: state-bank contract export patch is stale or incomplete" >&2
    exit 1
fi
for binding in "$PUFFER/src/bindings.cu" "$PUFFER/src/bindings_cpu.cpp"; do
    for attribute in \
        state_bank_contract_schema \
        state_bank_producer_schema \
        state_bank_authorization_schema \
        state_bank_strata_schema \
        state_bank_kind \
        state_bank_kind_name \
        state_bank_ruleset \
        state_bank_bbs_sha256 \
        state_bank_producer_manifest_sha256 \
        state_bank_training_contract_sha256 \
        state_bank_producer_engine_source_sha256 \
        state_bank_loader_engine_source_sha256 \
        state_bank_bbs_bytes \
        state_bank_records \
        state_bank_bbs_version \
        state_bank_match_size \
        state_bank_engine_fingerprint \
        state_bank_contract_identity \
        state_bank_bbs_path \
        state_bank_producer_manifest_path \
        state_bank_training_contract_path; do
        if ! grep -Fq "m.attr(\"$attribute\")" "$binding"; then
            echo "error: $(basename "$binding") lacks state-bank export $attribute" >&2
            exit 1
        fi
    done
    if ! grep -Fq 'm.def("state_bank_stratum_descriptor"' "$binding" || \
       ! grep -Fq 'PUFFER_HAS_STATE_BANK_STRATUM_QUERY' "$binding"; then
        echo "error: $(basename "$binding") lacks guarded state-bank stratum query" >&2
        exit 1
    fi
done

# Strict Blood Bowl environment normalization is deliberately the final patch
# that touches build.sh or either extension binding. It is cut against the
# complete pinned stack above, retains the normalized Python snapshot for the
# historical downstream converter, and must not invalidate any earlier exact
# patch that overlaps these three files.
if [ ! -f "$STRICT_ENV_CONFIG_PATCH" ]; then
    echo "error: missing $STRICT_ENV_CONFIG_PATCH" >&2
    exit 1
fi
if git -C "$PUFFER" apply --reverse --check --no-index \
        "$STRICT_ENV_CONFIG_PATCH" 2>/dev/null; then
    : # Exact strict environment patch is already installed.
elif git -C "$PUFFER" apply --check --no-index \
        "$STRICT_ENV_CONFIG_PATCH" 2>/dev/null; then
    git -C "$PUFFER" apply --no-index "$STRICT_ENV_CONFIG_PATCH"
    echo "applied:   strict Blood Bowl environment boundary -> CPU/CUDA bindings"
else
    echo "error: strict environment patch is neither applicable nor installed" >&2
    exit 1
fi
if ! strict_environment_config_sources_valid; then
    echo "error: installed strict Blood Bowl environment boundary is incomplete" >&2
    exit 1
fi
for overlapping_patch in \
        "$STANDALONE_INCLUDE_PATCH" \
        "$ROOT/training/puffer_dict_capacity.patch" \
        "$EXACT_PATCH" \
        "$RECURRENT_PATCH" \
        "$ROLLOUT_TRANSITION_PATCH" \
        "$FROZEN_PRIO_PATCH" \
        "$QUALIFICATION_PATCH" \
        "$STATE_BANK_EXPORT_PATCH" \
        "$STRICT_ENV_CONFIG_PATCH"; do
    if ! git -C "$PUFFER" apply --reverse --check --no-index \
            "$overlapping_patch"; then
        echo "error: final strict stack broke exact reverse applicability: $overlapping_patch" >&2
        exit 1
    fi
done

EXACT_BACKEND_HASH="$(exact_backend_hash)" || {
    echo "error: could not hash exact-action backend sources" >&2
    exit 1
}
ROOT_SOURCE_HASH="$(snapshot_hash "$ROOT/puffer/bloodbowl")"
INSTALLED_SOURCE_HASH="$(snapshot_hash "$DST")"
RECORDED_SOURCE_HASH="$(cat "$DST/.content_hash")"
if [ "$ROOT_SOURCE_HASH" != "$INSTALLED_SOURCE_HASH" ] || \
   [ "$ROOT_SOURCE_HASH" != "$RECORDED_SOURCE_HASH" ]; then
    echo "error: environment source changed during installation" >&2
    echo "  source:    $ROOT_SOURCE_HASH" >&2
    echo "  installed: $INSTALLED_SOURCE_HASH" >&2
    echo "  recorded:  $RECORDED_SOURCE_HASH" >&2
    exit 1
fi
"$INSTALL_PYTHON" "$ROOT/tools/state_bank_contract.py" install-no-bank \
    --puffer-root "$PUFFER" \
    --exact-action-source-hash "$EXACT_BACKEND_HASH" \
    --environment-source-hash "$INSTALLED_SOURCE_HASH" \
    --observation-abi "$SOURCE_OBSERVATION_ABI" \
    --observation-version "$SOURCE_OBSERVATION_VERSION" >/dev/null
echo "recorded:   exact-action backend digest $EXACT_BACKEND_HASH"

echo "installed: $DST"
echo "           $PUFFER/config/bloodbowl.ini"
echo "build:     cd $PUFFER && ./build.sh bloodbowl          # CUDA training backend"
echo "           cd $PUFFER && ./build.sh bloodbowl --fast   # standalone benchmark"
