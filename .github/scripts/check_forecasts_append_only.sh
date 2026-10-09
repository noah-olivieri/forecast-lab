#!/usr/bin/env bash
# Fail if any commit in BASE..HEAD modifies, deletes, renames or retypes an existing file under
# forecasts/ or results/. Adding new files is fine. Checked commit by commit (-m also covers merge
# commits), so an edit that a later commit reverts is still caught.
# Usage: check_forecasts_append_only.sh BASE [HEAD]
#   BASE empty, all zeros (new branch) or unknown -> the whole history of HEAD is checked.
set -euo pipefail
base="${1:-}"
head="${2:-HEAD}"
zeros="0000000000000000000000000000000000000000"

if [ -n "$base" ] && [ "$base" != "$zeros" ] && git cat-file -e "$base^{commit}" 2>/dev/null; then
  range="$base..$head"
else
  echo "no usable base commit; checking the whole history of $head"
  range="$head"
fi

changes="$(git log -m --no-renames --diff-filter=MDT --name-status --format= "$range" -- forecasts/ results/)"
if [ -n "$changes" ]; then
  echo "::error title=forecasts/ and results/ are append-only::existing files were changed:"
  echo "$changes"
  exit 1
fi
echo "forecasts/ and results/ are append-only over $range"
