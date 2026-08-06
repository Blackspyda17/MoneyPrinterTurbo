#!/usr/bin/env bash
# Sync the dreamiq branch with the upstream MoneyPrinterTurbo repo.
# - Updates main (fast-forward only) to match upstream/main
# - Rebases dreamiq on top of the fresh upstream/main
# Run from the repo root:  scripts/sync-upstream.sh
set -euo pipefail

cd "$(dirname "$0")/.."

echo "==> fetching upstream..."
git fetch upstream

echo "==> updating main (fast-forward)..."
git checkout main
git merge --ff-only upstream/main
git push origin main

echo "==> rebasing dreamiq onto upstream/main..."
git checkout dreamiq
if git rebase upstream/main; then
  echo "==> pushing dreamiq..."
  git push --force-with-lease origin dreamiq
  echo "OK: dreamiq rebased on $(git log -1 --format='%h %s' upstream/main)"
else
  echo "!! rebase conflicts — resolve them, then run: git rebase --continue && git push --force-with-lease origin dreamiq"
  exit 1
fi
