# nfl-drivers SHA map (drafted by Claude)

`nfl-drivers-sha-map.csv` maps every nfl-drivers commit from before 2026-10-20 to its commit in
the public repo `noah-olivieri/nfl-drivers`.

**Why it exists.** Before publishing, the history was rewritten so a private email address
appears nowhere: not in commit authors or committers, and not in any version of `DESCRIPTION`.
A rewrite gives every commit a new SHA. `drivers_snapshots/2026-10-19/2026-10-19T17-19-07Z/meta.json`
records `nfl_drivers_sha` `d82858a001b2eabd6824ec71aa6d8704c51af7c2`, which doesn't exist in
the public repo. Its public equivalent is `ae2bbc507b7c06c6281d15b96fa2db7c6e14e37c`.

**Columns.**
- `old_sha`, `new_sha`: the commit before and after the rewrite.
- `old_tree`, `new_tree`: the commits' tree SHAs.
- `files_differing`: the files whose contents differ between the two commits. It is
  `DESCRIPTION` (the email line in `Authors@R`) for 38 commits and empty for the 2 commits made
  before `DESCRIPTION` contained the address. No other file differs, so each pair ran the same
  code.

**Limit.** The old commits are not public, so a third party can't recompute `old_sha` or
`old_tree`. This file is the author's attested record. The original history is kept in a private
git bundle outside both repositories as the evidence behind it.
