# NFL Drivers snapshot automation: design

Date: 2026-10-19. Status: agreed in conversation, awaiting the user's review of this document.
Builds on `docs/superpowers/specs/2026-10-15-drivers-weekly-snapshot-design.md` (the "base
spec"). Everything there still holds unless this document says otherwise.

Labels: the user decided anything not marked otherwise. **(my call)** marks a choice the
assistant made that the user has not yet confirmed.

## Why

Today the snapshot is taken by hand. You `git pull` in forecast-lab, run `Rscript run.R` in
nfl-drivers (about 14 minutes), run `snapshot_drivers.py`, then commit, run pytest and ruff,
and push. That takes about 25 minutes. It depends on the user remembering, being at the Mac,
and keeping the Mac plugged in and awake (it slept during earlier runs). A mistyped command has
already happened once. Early games such as the 6:30 AM PT London game are not realistic by hand.
On Sunday 2026-10-18 the snapshot was missed entirely, so none of week 6's Sunday games count.

**Success:** every kickoff slot gets a main snapshot on `main` that counts, plus timing records
at about 48h and 24h, without the user at the Mac. If anything is missed or fails, the user
hears about it.

## What the user decided

- **GitHub Actions, like the T-24h forecast bot.** The run is `run.R`, then
  `snapshot_drivers.py`, then pytest and ruff, then commit and push to `main`.
- **Main snapshots, one per kickoff slot.** The slots are London, 1 PM ET, 4 PM ET, night
  games, Thursday and Monday. Each run covers only the games that kick off in its slot. The
  first attempt is about 2 hours before the slot. The bot retries every 15 minutes until
  45 minutes before the slot, and stops once the slot has a snapshot on `main`.
- **Only one run per slot (and per timing) can be in progress at a time.**
- **Timing records** at about 48 and 24 hours before each kickoff. They are stored the same way
  and never overwritten, but marked as timing records that don't count toward the main 3-hour
  test. Their purpose is a later comparison of model vs market accuracy and line movement at
  each timing. The user approved the windows proposed in conversation (see "Timing records").
- **A failure alert.**
- **Counting rule, recorded in DECISIONS.md (2026-10-19, commit `f95a12e`):** week 6 games use
  the base spec's same-day rule. From week 7 (starting with Thursday's NE@CHI), a game's
  prediction counts only if its snapshot is a main snapshot (not a timing record), was taken
  within 3 hours before kickoff, and was on GitHub `main` before kickoff. Phase C implements
  the rule; nothing in this project scores.
- **Priority:** main snapshots must be live for Sunday 2026-10-25, starting with the London game
  (PIT@NO, 9:30 AM ET, 13:30Z). Its first attempt is at 7:30 AM ET. If the timing records
  aren't ready in time, start them the following week rather than rushing.
- **Existing rules stay:** clean trees, the nfl-drivers SHA stamp, 6-hour freshness,
  exclusive-create, and never overwrite.
- **Cache R packages and nflverse data between runs.**
- **Publish nfl-drivers** as the public repo `noah-olivieri/nfl-drivers`. Before publishing,
  scrub the Gmail address from the whole history, **including every version of
  `DESCRIPTION`**. Use the GitHub noreply address
  (`283797087+noah-olivieri@users.noreply.github.com`, the address forecast-lab already uses)
  everywhere, and save the old to new SHA map.
- **Pin the R packages with renv** so every run uses the same versions.

## Goals, non-goals, anti-goals

Goals: no missed main snapshot, including London and holiday games. Every snapshot is just as
strict and traceable as a manual one. Re-runs are cheap enough that dropped GitHub cron runs
don't matter.

Non-goals: changing the model, scoring, settlement, the T-24h forecast job, `forecasts/`,
`RESEARCH_PROTOCOL.md`, or implementing the counting rule.

Anti-goals (failures even if it "works"):
- A snapshot that passes checks but doesn't describe the code that ran. Examples: unpinned
  packages that silently differ, a dirty tree, or a SHA that can't be found later.
- The bot changing or deleting an existing file, or pushing anything outside
  `drivers_snapshots/`.
- Cached data making a snapshot stale. 2026 data must always be fresh.
- A timing record that could be mistaken for a main snapshot.
- Burning a run every 15 minutes all week. Runs happen only inside windows.

## Schedule of work

1. **Stage 1, before Sunday 2026-10-25 7:30 AM ET:** Part 1 (nfl-drivers prep and publishing),
   then Part 2 with main snapshots (`t3`) only. The labels (`purpose`, `timing`) go in from the
   start, so stage 2 changes no file format.
2. **Stage 2, when stage 1 is live, no rush:** timing records `t48` and `t24`. If they're not
   live before a week's games, they start the next week.
3. **Interim (not automation):** week 7's Thursday game NE@CHI kicks off Thursday 2026-10-22
   at 8:15 PM ET (2026-10-23 00:15Z). Unless the bot is already live, it needs a manual main
   snapshot between 5:15 and about 7:45 PM ET, with `run.R` rerun first and the push before
   kickoff. Stage 1 must not break the manual route.

## Part 1: prepare nfl-drivers (one-time, on the Mac, before the workflow exists)

Do these in order. Nothing is pushed to GitHub until all of it is done and the user approves
the push.

1. **Backup:** `git bundle create` of the current repo (all refs), stored outside both repos
   and never published (my call). It is the only remaining copy of the original commits,
   including `d82858a`.
2. **Rewrite history** with `git filter-repo`. It is not installed, so use
   `brew install git-filter-repo` or `uv tool install git-filter-repo`.
   - Author and committer emails become the noreply address (mailmap).
   - In every version of `DESCRIPTION`, the Gmail address becomes the noreply address (a
     blob/text replacement scoped to that address).
   - Afterwards, verify that `git log --all -p` and every commit message, author and committer
     contain no trace of the old address. The builder's audit found the address only in
     `DESCRIPTION` (38 of 40 commits) and in author/committer fields. A repeat check after the
     rewrite must find zero.
3. **SHA map**, saved in forecast-lab as `docs/nfl-drivers-sha-map.csv` with columns
   `old_sha, new_sha, old_tree, new_tree, files_differing`. It is committed with the user's
   approval, like any non-bot change.
   - Build `files_differing` by comparing the old and new trees (from the backup). The expected
     value is `DESCRIPTION` or empty. Anything else means the rewrite went wrong: stop.
   - Add a short header note or companion `.md` saying what the map is, why it exists (the
     2026-10-19 snapshot records `nfl-drivers@d82858a…`, which doesn't exist publicly), and
     its limit. Old commits are private, so the map is the user's attested record, not
     something a third party can recompute. The private bundle is the evidence behind it.
4. **New commits on top of the rewritten history:**
   - Repo-local `user.email` set to the noreply address, the same as forecast-lab.
   - renv: `renv::init()` / `renv::snapshot()` capturing the versions installed on the Mac now,
     covering every package in `DESCRIPTION` Imports and Suggests plus what `run.R` actually
     loads. Commit `renv.lock`, `.Rprofile` and `renv/activate.R` (renv's own `renv/.gitignore`
     keeps the library out of git). The lock records the R version, and CI uses that version.
   - README: one line on `renv::restore()` for a fresh checkout.
5. **Check on the Mac:** `renv::restore()`, then `Rscript run.R` gives a clean tree,
   `results$code_dirty == FALSE`, and a manual `snapshot_drivers.py` still succeeds. After
   this, the manual route also runs the pinned versions.
6. **Publish:** create `noah-olivieri/nfl-drivers` (public) and push `master`, with the user's
   approval.

## Part 2: the workflow (forecast-lab)

### Slots

- Built from `config/kickoffs.json`, which `kickoffs.yml` rebuilds daily.
- A slot is a group of games sorted by kickoff. The slot time `S` is its earliest kickoff. A
  game joins the slot if its kickoff is less than 60 minutes after `S`, so 4:05 and 4:25 share
  a slot and 7:15 and 8:15 do not (my call).
- **Constraint the builder must keep:** first main attempt (S − 2h) + slot width (< 60 min)
  ≤ the 3-hour counting window. So a main snapshot taken at the first attempt counts for every
  game in the slot. Changing any of these numbers needs this rechecked. A test must pin it.
- Slot ID: `S` as `YYYY-MM-DDTHH:MMZ`.

### Windows (each is `[open, close)`, relative to `S`)

| timing | purpose | opens | closes | live in |
|---|---|---|---|---|
| `t48` | timing | S − 48h | S − 45h | stage 2 |
| `t24` | timing | S − 24h | S − 21h | stage 2 |
| `t3` | main | S − 2h | S − 45min | stage 1 |

`t24` has the same window as the T-24h forecast bot. The user approved these windows. Each
snapshot also records its own `minutes_to_kickoff` per game, so exact timing is never lost.

### Covered, needs a run, MISSED

- **Main (`t3`), per game:** a game is covered when a snapshot on `main` with `purpose = main`
  has `created_ts` in `[kickoff − 3h, kickoff)` and lists the game in `predictions.csv`, or in
  `excluded.csv` with a reason other than `other_slot`. The `excluded.csv` part stops endless
  retries for a game nfl-drivers can't predict (`no_prediction`, `not_in_results`). Manual
  snapshots (no flags, so `purpose = main`) count the same as bot snapshots.
- **Timing (`t48`, `t24`), per slot:** covered when a snapshot on `main` has that `timing` and
  that `slot`. Manual snapshots never count as timing records.
- A (slot, timing) pair **needs a run** when its window is open and it is not covered.
- **MISSED:** a pair whose window closed within the last 6 hours without being covered. For
  `t3`, this also means a game whose kickoff passed with no main snapshot meeting the counting
  rule. "Received on `main` before kickoff" is approximated by the commit time of the commit
  that added the snapshot (my call; Phase C applies the real rule). The alert names the
  timing.
- **Go-live (my call):** two constants, like `GO_LIVE` in `jobs/forecast_t24.py`. One is for
  `t3` and is set when stage 1 merges. One is for timing records, unset (nothing eligible, no
  alerts) until stage 2 merges. Only windows opening after the relevant go-live are eligible
  or can be MISSED.

### Workflow `drivers.yml`

Same shape as `forecast.yml`:

- **Triggers:** cron every 15 minutes on odd minutes that don't collide with the existing
  crons (the builder picks, e.g. `4,19,34,49 * * * *`). Also `workflow_dispatch` with **no
  inputs**, so nobody selects a slot and the planned cron-job.org backup can fire it. The cron
  string is mirrored as a constant in the gate script, with a test, like `FORECAST_CRON`.
- **`gate` job:** stdlib-only Python (e.g. `jobs/drivers_slots.py gate`) that runs before any
  install. Outputs every (slot, timing) pair needing a run as a JSON list, plus `missed`. It
  exits like the forecast gate (0 fine, 1 missed recorded, 2 crash). Out-of-window runs take a
  few seconds.
- **`alert` job:** fails the run when `missed` is true, so GitHub emails.
- **`snapshot` job:** a matrix over the gate's pairs, so a slow `t3` run never starves a `t24`
  run for another slot (my call).
  - **Job-level concurrency group per pair** (`drivers-<slot id>-<timing>`,
    `cancel-in-progress: false`). This guarantees one run per slot and timing in progress.
    Different pairs may run at the same time.
  - **First step re-checks:** fetch `main`, then re-derive with the same script (`check
    --slot <id> --timing <t>`) that the window is still open and the pair still needs a run.
    Exit successfully without doing anything if not. This covers a run that waited in the
    concurrency queue while an earlier one pushed.
  - **Checkouts:** forecast-lab at `main` and nfl-drivers at `master`, as two sibling
    directories under `$GITHUB_WORKSPACE`. Neither may sit inside the other, because the
    clean-tree checks would see the other repo as untracked. Nothing the workflow writes may
    land as an untracked file in either tree. The `drivers_snapshots/` output is the one
    allowed exception, already handled by `clean_head(allow_prefix=…)`.
  - **R:** set up R at the version in `renv.lock` and restore with renv. Cache the renv
    library keyed on `renv.lock` (and OS/R version), using Linux binaries (Posit Public Package
    Manager) so a cache miss takes minutes, not an hour.
  - **nflverse cache:** `actions/cache` for `nfl-drivers/data/cache/` files for **2006–2025
    only** (pbp and schedules), with a fixed versioned key. 2026 files are never restored.
    `run.R` always re-downloads 2026 and stops if the download fails, so freshness holds.
    Several runs a week keep the cache from GitHub's 7-day eviction. On a miss, `run.R`
    downloads everything, which is slower but correct.
  - **Run:** `Rscript run.R` in nfl-drivers, then `uv run python jobs/snapshot_drivers.py
    --drivers ../nfl-drivers --slot <id> --timing <t>`.
  - **Tests:** `uv run pytest -q` (unpiped) and `uv run ruff check .`. A failure means no push.
  - **Push:** a new `.github/scripts/push_drivers.sh` modeled on `push_forecasts.sh`. It
    commits exactly the new snapshot directory's files as github-actions[bot], refuses any
    path outside `drivers_snapshots/` or any path already in HEAD, and retries a rejected push
    by rebasing (the forecast bot and other matrix jobs push to `main` too). It aborts if the
    rebased `main` already has the same path, and writes the commit and SHA-256s to the step
    summary. The builder may generalize `push_forecasts.sh` instead, as long as the forecast
    behavior and tests are unchanged.
  - **Timeout:** 40 minutes (my call). A `t3` run that starts at the last chance (S − 45min)
    and runs long still has every guard: `snapshot_drivers.py` refuses games already kicked
    off, and a push after kickoff simply doesn't count.
- **Failure alert:** any failed step fails the run, so GitHub emails. MISSED covers a pair
  that got nothing at all.
- **Cost (estimate):** about 5 slots a week × 3 timings × about 25 minutes, roughly 6 hours of
  runner time a week. That's free if both repos are public; the builder should confirm
  forecast-lab's visibility.

### Changes to `snapshot_drivers.py` / `lab.drivers_snapshot`

- New optional `--slot <id>` and `--timing t48|t24|t3`, given together or not at all.
  - With them, the job re-derives the slot's game set from `config/kickoffs.json` with the
    shared slot rule, and refuses if that pair's window is not open at `created_ts`. Upcoming
    games outside the slot go to `excluded.csv` with reason `other_slot`. Slot games missing
    from `results$upcoming` go to `excluded.csv` as `not_in_results`.
  - Without them (manual use), it behaves as today: every upcoming game, `purpose = main`,
    `timing` and `slot` empty.
- **Labels:** new columns `purpose` (`main` | `timing`), `timing` (`t48` | `t24` | `t3` | empty)
  and `slot` in `predictions.csv`. The same three keys go in `meta.json`. `t3` means
  `purpose = main`; `t48` and `t24` mean `purpose = timing`. The column order is appended at
  the end, so old snapshots stay readable (old ones have no such columns and are `main`).
- Slot rule, windows and coverage code live in one stdlib-only module that both the gate and
  the snapshot job import, so they can't disagree.
- Record the R package versions actually loaded (from the exporter or `results`) in
  `meta.json` (my call).
- `same_day` stays as a column. It drives counting for week 6 only.
- `export_drivers.R` needs `jsonlite` in whatever library `Rscript` sees when it runs from
  forecast-lab, which is outside nfl-drivers' renv project. The builder decides how (e.g. add
  `jsonlite` to nfl-drivers' renv and run the exporter with that library). It must work on the
  Mac and in CI.

### Docs and rules

- CLAUDE.md: add a third bot exception. The `drivers` workflow (github-actions[bot],
  `push_drivers.sh`) may push NEW files under `drivers_snapshots/` to `main` without asking.
  Update the Layout and the NFL Drivers status notes, which currently describe a manual
  snapshot, and keep the manual steps as the fallback.
- Base spec: add a dated note (2026-10-19) under "Which snapshot counts" saying the same-day
  rule governs week 6 only, and that from week 7 the rule in DECISIONS.md 2026-10-19 applies.
  Don't delete the old text.
- `ci.yml` already guards `drivers_snapshots/` as append-only. No change.
- Verify every third-party Action tag with `gh api repos/<r>/git/ref/tags/<tag>` before use
  (CLAUDE.md).

## Left to the builder

The exact cron minutes, script and module names, the renv/R setup Actions (with verified tags),
the cache key format, whether to generalize `push_forecasts.sh`, how the exporter finds
`jsonlite`, the filter-repo invocation, the test layout, and the order of work within each
stage. Tuning the 40-minute timeout once real runner times are measured is also the builder's.
