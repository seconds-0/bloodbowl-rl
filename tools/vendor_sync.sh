#!/usr/bin/env bash
# Re-clone vendored reference repos at the SHAs pinned in vendor/PINS.md.
# Usage: tools/vendor_sync.sh [--latest]   (--latest: clone HEAD and print new SHAs to update PINS.md)
set -euo pipefail
cd "$(dirname "$0")/../vendor"

declare -A REPOS=(
  [PufferLib]="PufferAI/PufferLib 9836f0d2e78889c1aaf189c04d161b6fc61a9386"
  [ffb]="christerk/ffb c98fd120229b55846b3c1c38ec279ec729d78a6f"
  [jervis-ffb]="cmelchior/jervis-ffb 2063a286da1239fb694b20302d6071012e41c484"
  [fumbbl_replays]="gsverhoeven/fumbbl_replays e73776b19f056ed62798df033ae845c73ae4d42d"
  [botbowl]="njustesen/botbowl 3e550bda3666c39efe478fb9465646af24576665"
  [BloodBowlActionCalculator]="BloodBowlDave/BloodBowlActionCalculator 5baa0ee760734735689382c44104242614ec1cef"
)

for name in "${!REPOS[@]}"; do
  read -r slug sha <<<"${REPOS[$name]}"
  if [[ ! -d "$name/.git" ]]; then
    git clone --quiet "https://github.com/$slug.git" "$name"
  fi
  if [[ "${1:-}" == "--latest" ]]; then
    git -C "$name" fetch --quiet origin && git -C "$name" checkout --quiet FETCH_HEAD
    echo "$name: $(git -C "$name" rev-parse HEAD) ($(git -C "$name" log -1 --format=%cs))"
  else
    git -C "$name" fetch --quiet --depth 1 origin "$sha" 2>/dev/null || git -C "$name" fetch --quiet origin
    git -C "$name" checkout --quiet "$sha"
    echo "$name: pinned at $sha"
  fi
done
