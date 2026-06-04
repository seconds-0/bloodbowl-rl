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
    if [ "$want" = "$have" ]; then
        echo "drift check: OK ($want)"
        exit 0
    fi
    echo "drift check: STALE snapshot — engine/src or puffer/bloodbowl changed since install" >&2
    echo "  source now: $want" >&2
    echo "  installed:  $have" >&2
    echo "  fix: tools/install_puffer_env.sh $PUFFER" >&2
    exit 1
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

echo "installed: $DST"
echo "           $PUFFER/config/bloodbowl.ini"
echo "build:     cd $PUFFER && ./build.sh bloodbowl          # CUDA training backend"
echo "           cd $PUFFER && ./build.sh bloodbowl --fast   # standalone benchmark"
