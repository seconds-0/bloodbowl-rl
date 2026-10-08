#!/usr/bin/env bash
# Export the pinned harness commit for the search-distillation tools and build its shim.
#
#   export_harness.sh DEST [REPO]
#
# REPO is any worktree whose object store holds the commit (default
# ~/Code/bb-play-harness). Only `git archive` and `git rev-parse` run in it:
# no checkout, no index or worktree change. DEST must not exist yet. The engine
# shim is built inside DEST (play_harness/native/build.sh), so nothing is ever
# compiled into a worktree. tools/droplet_tournament.py is exported with it:
# the launcher imports the droplet lifecycle from there, held to the hash
# PLAN.json records, and its `status` and `destroy` commands are the cleanup
# that needs no runner.
set -euo pipefail
PIN=5ab3ab6e195afbb717d7e0e7e62361a3b548fdd6      # feat/search-probe-20261007
DEST="$1"
REPO="${2:-$HOME/Code/bb-play-harness}"
[ ! -e "$DEST" ] || { echo "$DEST exists" >&2; exit 1; }
test "$(git -C "$REPO" rev-parse --verify "$PIN^{commit}")" = "$PIN"
mkdir -p "$DEST"
git -C "$REPO" archive --format=tar "$PIN" -- \
    play_harness engine puffer training/convert_checkpoint.py tools/droplet_tournament.py \
    tools/gate_acceptance.py tools/search_acceptance.py \
  | tar -x -C "$DEST"
echo "$PIN" > "$DEST/SOURCE_COMMIT"
bash "$DEST/play_harness/native/build.sh" >/dev/null
echo "$DEST at $PIN"
