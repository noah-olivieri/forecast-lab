#!/usr/bin/env bash
# Commit ONE new NFL Drivers snapshot directory and push it to main as github-actions[bot].
# Usage: push_drivers.sh drivers_snapshots/<YYYY-MM-DD>/<ts>Z LABEL
# Stages and commits exactly the files under that directory (never anything else), refuses a
# directory outside drivers_snapshots/, an empty one, or any file already tracked, retries a
# rejected push by rebasing (the forecast bot and other drivers jobs push to main too), and
# aborts if another run has meanwhile added the same files. Writes sha256 + pushed commit to
# $GITHUB_STEP_SUMMARY. Modelled on push_forecasts.sh.
set -euo pipefail
[ "$#" -eq 2 ] || { echo "usage: push_drivers.sh SNAPSHOT_DIR LABEL" >&2; exit 1; }
dir="${1%/}"
label="$2"
branch="${DRIVERS_BRANCH:-main}"
summary="${GITHUB_STEP_SUMMARY:-/dev/null}"
run_url="${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-unknown}/actions/runs/${GITHUB_RUN_ID:-local}"

sha256() {
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d' ' -f1
  else shasum -a 256 "$1" | cut -d' ' -f1; fi
}

if ! [[ "$dir" =~ ^drivers_snapshots/[0-9]{4}-[0-9]{2}-[0-9]{2}/[0-9T:-]+Z$ ]]; then
  echo "::error::refusing $dir: only drivers_snapshots/<date>/<ts>Z directories" >&2
  exit 1
fi
[ -d "$dir" ] || { echo "::error::$dir does not exist" >&2; exit 1; }

files=()
while IFS= read -r -d '' f; do files+=("$f"); done < <(find "$dir" -type f -print0 | sort -z)
[ "${#files[@]}" -gt 0 ] || { echo "::error::$dir is empty" >&2; exit 1; }
for p in "${files[@]}"; do
  if git cat-file -e "HEAD:$p" 2>/dev/null; then
    echo "::error::$p already exists in HEAD; snapshots are never modified" >&2
    exit 1
  fi
done

git config user.name "github-actions[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

git add -- "${files[@]}"
git commit -q -m "snapshot: drivers $(basename "$dir") $label

run: $run_url" -- "${files[@]}"

pushed=""
for attempt in 1 2 3 4; do
  if git push origin "HEAD:$branch"; then pushed=1; break; fi
  echo "push rejected (attempt $attempt); fetching and rebasing"
  git fetch -q origin "$branch"
  for p in "${files[@]}"; do
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
  echo "### Drivers snapshot pushed to \`$branch\` ($label)"
  echo
  echo "Commit \`$(git rev-parse HEAD)\` ($run_url)"
  echo
  echo "| file | sha256 |"
  echo "| --- | --- |"
  for p in "${files[@]}"; do echo "| \`$p\` | \`$(sha256 "$p")\` |"; done
} >> "$summary"
