#!/usr/bin/env bash
# Commit NEW result files and push them to main as github-actions[bot]. Same pattern as
# push_forecasts.sh, restricted to results/.
# Usage: push_results.sh results/<season>/<game_id>.csv ...
# Stages and commits exactly the paths given (never anything else), refuses a path outside
# results/ or one already tracked, retries a rejected push by rebasing, and aborts if another
# run has meanwhile added the same file. Writes sha256 + pushed commit to $GITHUB_STEP_SUMMARY.
set -euo pipefail
[ "$#" -ge 1 ] || { echo "usage: push_results.sh PATH..." >&2; exit 1; }
branch="${RESULTS_BRANCH:-main}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-unknown}/actions/runs/${GITHUB_RUN_ID:-local}"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

ids=()
for p in "$@"; do
  case "$p" in
    results/*.csv) ;;
    *) echo "::error::refusing to commit $p: only results/**/*.csv" >&2; exit 1 ;;
  esac
  [ -f "$p" ] || { echo "::error::$p does not exist" >&2; exit 1; }
  if git cat-file -e "HEAD:$p" 2>/dev/null; then
    echo "::error::$p already exists in HEAD; result files are never modified" >&2
    exit 1
  fi
  ids+=("$(basename "$p" .csv)")
done

git add -- "$@"
git commit -q -m "settle: ${ids[*]}

run: $run_url" -- "$@"

pushed=""
for attempt in 1 2 3 4; do
  if git push origin "HEAD:$branch"; then pushed=1; break; fi
  echo "push rejected (attempt $attempt); fetching and rebasing"
  git fetch -q origin "$branch"
  for p in "$@"; do
    if git cat-file -e "FETCH_HEAD:$p" 2>/dev/null; then
      echo "::error::another run already added $p; not overwriting it" >&2
      exit 1
    fi
  done
  if ! git rebase FETCH_HEAD; then
    git rebase --abort || true
    echo "::error::rebase onto origin/$branch failed" >&2
    exit 1
  fi
done
[ -n "$pushed" ] || { echo "::error::could not push to $branch after 4 attempts" >&2; exit 1; }

{
  echo "### Results pushed to \`$branch\`"
  echo
  echo "Commit \`$(git rev-parse HEAD)\` ($run_url)"
  echo
  echo "| file | sha256 |"
  echo "| --- | --- |"
  for p in "$@"; do echo "| \`$p\` | \`$(sha256 "$p")\` |"; done
} >> "$summary"
