#!/usr/bin/env bash
# Check out the `data` branch into ./data-branch as a git worktree.
# Usage: data_worktree.sh create|require
#   create  - make an orphan `data` branch if it does not exist yet (collector)
#   require - do nothing if it does not exist (gap-check, compaction)
# Writes has_data=true|false to $GITHUB_OUTPUT.
set -euo pipefail
mode="${1:?usage: data_worktree.sh create|require}"
out="${GITHUB_OUTPUT:-/dev/null}"

if git fetch --no-tags --depth=1 origin data 2>/dev/null; then
  git worktree add -B data data-branch FETCH_HEAD
elif [ "$mode" = "create" ]; then
  git worktree add --detach data-branch
  git -C data-branch checkout -q --orphan data
  git -C data-branch rm -rf -q . 2>/dev/null || true
else
  echo "::notice::no data branch yet; collection has not started"
  echo "has_data=false" >> "$out"
  exit 0
fi
echo "has_data=true" >> "$out"
