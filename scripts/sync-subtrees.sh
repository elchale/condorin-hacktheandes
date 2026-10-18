#!/usr/bin/env bash
# Pulls the latest main of every source repository into its folder (git subtree, history kept).
# Used by .github/workflows/sync.yml; also runs by hand from the repo root: bash scripts/sync-subtrees.sh
set -euo pipefail

SUBTREES=(
  "frontend https://github.com/elchale/condorin-new-front.git"
  "backend https://github.com/elchale/condorin-backend.git"
  "detection https://github.com/sergtello/condorin-detection.git"
)

changed=0
for entry in "${SUBTREES[@]}"; do
  read -r prefix url <<<"$entry"
  before=$(git rev-parse HEAD)
  git subtree pull --prefix="$prefix" "$url" main -m "Sync $prefix from $url"
  if [ "$(git rev-parse HEAD)" != "$before" ]; then
    echo "updated: $prefix"
    changed=1
  else
    echo "up to date: $prefix"
  fi
done
echo "changed=$changed" >> "${GITHUB_OUTPUT:-/dev/null}"
