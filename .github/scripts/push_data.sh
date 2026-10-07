#!/usr/bin/env bash
# Commit changes under snapshots/ in ./data-branch and push to origin/data (retrying on races).
# Stages by explicit path only. Usage: push_data.sh "commit message"
set -euo pipefail
msg="${1:?usage: push_data.sh \"commit message\"}"
cd data-branch
git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"
git add -A snapshots
if git diff --cached --quiet; then
  echo "nothing to commit"
  exit 0
fi
git commit -q -m "$msg"
for attempt in 1 2 3; do
  if git push origin HEAD:data; then
    exit 0
  fi
  echo "push rejected (attempt $attempt); rebasing"
  git pull --rebase origin data
done
echo "::error::could not push to data after 3 attempts"
exit 1
