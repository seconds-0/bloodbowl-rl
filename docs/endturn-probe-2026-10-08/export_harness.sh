#!/usr/bin/env bash
# Export the pinned harness commit for the END_TURN probe.
#
#   export_harness.sh DEST [REPO]
#
# REPO is any worktree whose object store holds the commit (default
# ~/Code/bb-play-harness). Only `git archive` and `git rev-parse` run in it:
# no checkout, no index or worktree change. DEST must not exist yet.
# tools/droplet_tournament.py is exported with it: the launcher imports the
# droplet lifecycle from there, held to the hash PLAN.json records, and its
# `status` and `destroy` commands are the cleanup that needs no runner.
set -euo pipefail
PIN=06f0a5f7e67cc9089e8edaf5fa9b97dcfe440d99      # feat/search-probe-20261007
DEST="$1"
REPO="${2:-$HOME/Code/bb-play-harness}"
[ ! -e "$DEST" ] || { echo "$DEST exists" >&2; exit 1; }
test "$(git -C "$REPO" rev-parse --verify "$PIN^{commit}")" = "$PIN"
mkdir -p "$DEST"
git -C "$REPO" archive --format=tar "$PIN" -- \
    play_harness engine puffer training/convert_checkpoint.py tools/droplet_tournament.py \
  | tar -x -C "$DEST"
echo "$PIN" > "$DEST/SOURCE_COMMIT"
echo "$DEST at $PIN"
