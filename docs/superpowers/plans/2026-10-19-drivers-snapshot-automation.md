# NFL Drivers Snapshot Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A GitHub Actions bot that takes the NFL Drivers snapshot for each kickoff slot (main `t3`, plus `t48`/`t24` timing records), runs pytest and ruff, and pushes only new files under `drivers_snapshots/` to `main`.

**Architecture:** A stdlib-only module (`src/lab/drivers_slots.py`) holds the slot rule, windows, coverage and MISSED logic. It is shared by a cheap gate script (`jobs/drivers_gate.py`, runs before any install) and by the existing `jobs/snapshot_drivers.py`, which gains `--slot/--timing` and label columns. `drivers.yml` is a gate → matrix of (slot, timing) jobs with one concurrency group per pair. A composite action sets up nfl-drivers (public repo, renv-pinned) with cached R packages and cached 2006–2025 nflverse files.

**Tech Stack:** Python 3 (uv, pytest, ruff), R 4.5.2 + renv, GitHub Actions (`actions/checkout@v7`, `astral-sh/setup-uv@v10.2.0`, `r-lib/actions/setup-r@v2.9.0`, `r-lib/actions/setup-renv@v2.9.0`, `actions/cache@v6.1.0`; the last three were verified to exist on 2026-10-19 with `gh api repos/<r>/git/ref/tags/<tag>`), git-filter-repo.

**Spec:** `docs/superpowers/specs/2026-10-19-drivers-snapshot-automation-design.md` (commit `61bd0c1`). The base spec is `docs/superpowers/specs/2026-10-15-drivers-weekly-snapshot-design.md`.

## Global Constraints

- Stage 1 (Tasks 1–10) must be live before **Sunday 2026-10-25 11:30Z** (7:30 AM ET, the first attempt for the London game PIT@NO, kickoff 13:30Z). Stage 2 (Task 11) comes after, and it's fine if it slips a week.
- Windows `[open, close)` relative to slot time `S`: `t48` S−48h to S−45h, `t24` S−24h to S−21h, `t3` S−2h to S−45min. Counting window: 3h. Slot width: a game joins if kickoff − S < 60 min. Cron every 15 min.
- `t3` → `purpose = main`. `t48`, `t24` → `purpose = timing`. A manual run (no flags) → `purpose = main`, with empty `timing` and `slot`.
- Existing rules stay: both trees clean, `results$code_sha` == nfl-drivers HEAD and not dirty, 6-hour freshness, exclusive-create `mkdir`, never overwrite, 5-minute quote rule.
- The bot pushes only NEW files under `drivers_snapshots/`. Every other push (code, workflows, docs, nfl-drivers) needs the user's approval in this session first.
- Before any push: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q` unpiped must pass, and `uv run ruff check .`. Stage by explicit path, never `git add -A`. Check that `.env` and `data/` are not staged.
- Noreply address: `283797087+noah-olivieri@users.noreply.github.com`. The private address being scrubbed is never written in this repo: commands take it from `$OLD_EMAIL` (set in the shell from `git log --format=%ae` of nfl-drivers before the rewrite).
- The private bundle lives at `~/Backups/nfl-drivers-pre-rewrite-2026-10-19.bundle`, outside both repos. It is never committed or pushed.
- Never edit `RESEARCH_PROTOCOL.md` above "Changes". Never force-push `main`.
- Code work happens on branch `drivers-auto` in forecast-lab and merges to `main` in Task 10.

## Deviation from the spec (settled while planning; tell the user at handoff)

The spec says the snapshot job "refuses if that pair's window is not open at `created_ts`". For `t3` that would refuse every run started in the last few minutes of the window: a run that starts at S−46min finishes after S−45min. Instead:
- the workflow's `check` step requires the window to be open **when the job starts**;
- `snapshot_drivers.py` refuses only if `created_ts < open` or `created_ts >= close + RUN_GRACE` (`RUN_GRACE = 45 min`, the 40-minute job timeout plus slack);
- the existing per-game kickoff check still excludes games that have started.

## Review Focus

1. **DST end (2026-11-01) and London:** slots and windows are built in UTC from `kickoffs.json`. A London 13:30Z game and a 1 PM ET game stay separate slots on both sides of the DST change. Pinned in Task 4 (`test_slots_across_dst_and_london`).
2. **A kickoff moved after a snapshot** (flex, or an updated `kickoffs.json`): coverage is judged against the current kickoff, so a snapshot that no longer falls within 3h doesn't count and the slot runs again. Pinned in Task 4 (`test_moved_kickoff_uncovers_game`).
3. **An unreadable or old-format snapshot directory** (the 2026-10-19 snapshot has no `purpose`/`slot`; a dir missing `meta.json`): it is read as `main` or skipped with a warning, and never crashes the gate. One bad directory must not stop every slot. Pinned in Task 4 (`test_read_snapshots_old_format_and_broken_dirs`).
4. **A queued duplicate run:** when a second run for the same pair starts after the first pushed, `check` prints `run=false` and the job exits 0 without running R. Pinned in Task 5 (`test_check_after_push_says_no_run`).
5. **A `t3` run that finishes after the window closes but before kickoff** still writes. A game whose kickoff has passed is excluded. Pinned in Task 6 (`test_t3_written_after_close_within_grace`, plus the existing started-game test).

---

## Stage 1: main snapshots before Sunday

### Task 1: Scrub the Gmail from nfl-drivers history and record the SHA map

Operations on the Mac, with no push. Run in `/Users/noaholivieri/Documents/nfl-drivers` unless stated otherwise.

**Files:**
- Create: `~/Backups/nfl-drivers-pre-rewrite-2026-10-19.bundle` (private, outside repos)
- Create: `/Users/noaholivieri/Documents/forecast-lab/docs/nfl-drivers-sha-map.csv`
- Create: `/Users/noaholivieri/Documents/forecast-lab/docs/nfl-drivers-sha-map.md`
- Create (scratch, not committed): `<scratchpad>/sha-map.py`

**Interfaces:**
- Produces: the rewritten nfl-drivers `master` (all SHAs new), the bundle, and the map with columns `old_sha,new_sha,old_tree,new_tree,files_differing`.

- [ ] **Step 1: Preconditions.** `git status --porcelain` is empty, and `git log --oneline | wc -l` prints 40. Record the old SHAs: `git rev-list --reverse master > <scratchpad>/old-shas.txt`.
- [ ] **Step 2: Bundle.** `mkdir -p ~/Backups && git bundle create ~/Backups/nfl-drivers-pre-rewrite-2026-10-19.bundle --all && git bundle verify ~/Backups/nfl-drivers-pre-rewrite-2026-10-19.bundle`. Expected: `... is okay`.
- [ ] **Step 3: Install filter-repo.** `uv tool install git-filter-repo` (fallback: `brew install git-filter-repo`). Then `git filter-repo --version`.
- [ ] **Step 4: Rewrite.** Write `<scratchpad>/mailmap` containing `Noah Olivieri <283797087+noah-olivieri@users.noreply.github.com> <$OLD_EMAIL>`, and `<scratchpad>/replace.txt` containing `$OLD_EMAIL==>283797087+noah-olivieri@users.noreply.github.com` (both files stay in the scratchpad). Run `git filter-repo --force --mailmap <scratchpad>/mailmap --replace-text <scratchpad>/replace.txt`. filter-repo writes `.git/filter-repo/commit-map`.
- [ ] **Step 5: Verify zero leftovers.** Each of these must print nothing:
  - `git log --all --format='%ae%n%ce%n%B' | grep -F "$OLD_EMAIL"`
  - `git log --all -p | grep -F "$OLD_EMAIL"`
  - `git grep -F "$OLD_EMAIL" $(git rev-list --all)`

  `git log --oneline | wc -l` must still print 40. filter-repo removes `origin`, which is fine because there is none.
- [ ] **Step 6: Build the map in a scratch repo,** never in nfl-drivers, so no old object can end up in the repo that gets published.
  - `git clone -q ~/Backups/nfl-drivers-pre-rewrite-2026-10-19.bundle <scratchpad>/old`
  - `git -C <scratchpad>/old fetch -q /Users/noaholivieri/Documents/nfl-drivers master:refs/rewritten`
  - Write `<scratchpad>/sha-map.py`. It reads nfl-drivers' `.git/filter-repo/commit-map` (`old new` per line, with a header) and, in `<scratchpad>/old`, computes `old_tree = rev-parse <old>^{tree}`, `new_tree = rev-parse <new>^{tree}`, and `files_differing = diff --name-only <old> <new>` (joined with `;`).
  - Write the CSV rows in commit order.
- [ ] **Step 7: Check the map.** Every `files_differing` is `DESCRIPTION` or empty, there are 40 rows, and the row with `old_sha` starting `d82858a` exists. If any other file appears, STOP and tell the user.
- [ ] **Step 8: Write `docs/nfl-drivers-sha-map.md`** (forecast-lab). Explain what the map is and why it exists: `drivers_snapshots/2026-10-19/2026-10-19T17-19-07Z/meta.json` records `d82858a…`, which isn't public. Explain how to read it: same code except `DESCRIPTION`'s email line. State its limit: the old commits are private, so this is the user's attested record and the private bundle is the evidence. Mark the text "(drafted by Claude)".
- [ ] **Step 9: Commit in forecast-lab on branch `drivers-auto`** (create it from an up-to-date `main`: `git checkout main && git pull --ff-only && git checkout -b drivers-auto`):
  ```bash
  git add docs/nfl-drivers-sha-map.csv docs/nfl-drivers-sha-map.md docs/superpowers/plans/2026-10-19-drivers-snapshot-automation.md
  git commit -m "docs: drivers automation plan; nfl-drivers old->new SHA map after the email scrub"
  ```

### Task 2: Pin R packages with renv in nfl-drivers

**Files (nfl-drivers):**
- Modify: `DESCRIPTION` (add `jsonlite` to Imports; the email is already the noreply address after Task 1)
- Create: `renv.lock`, `.Rprofile`, `renv/activate.R`, `renv/settings.json`, `renv/.gitignore` (renv generates them)
- Modify: `README.md` (one line: "Fresh checkout: `Rscript -e 'renv::restore()'` before `Rscript run.R`.")

**Interfaces:**
- Produces: `renv.lock` with R 4.5.2 and every package in DESCRIPTION Imports and Suggests, including `jsonlite`, `nflreadr`, `glmnet` and `testthat`. Running `Rscript` with cwd = nfl-drivers activates renv. Task 6 relies on this to run the exporter with pinned `jsonlite`.

- [ ] **Step 1:** `git config user.email 283797087+noah-olivieri@users.noreply.github.com` (repo-local).
- [ ] **Step 2:** Add `jsonlite` to `DESCRIPTION` Imports, with a comment line saying forecast-lab's `jobs/export_drivers.R` uses it.
- [ ] **Step 3:** `Rscript -e 'install.packages("renv", repos="https://cloud.r-project.org")'`, then in nfl-drivers `Rscript -e 'renv::init(settings = list(snapshot.type = "explicit"), bare = TRUE); renv::hydrate(); renv::snapshot(prompt = FALSE)'`. `hydrate` copies the Mac's installed versions, so no upgrades happen.
- [ ] **Step 4: Verify the lock.** `Rscript -e 'l <- jsonlite::read_json("renv.lock"); cat(l$R$Version, sort(names(l$Packages)) %in% c("jsonlite","nflreadr","glmnet","dplyr","testthat"), "\n")'`. Expected: `4.5.2`, with all five names present. Check the versions match the Mac (nflreadr 1.5.1, glmnet 5.1, dplyr 1.1.4, jsonlite 2.0.0).
- [ ] **Step 5:** Update the README line. `git status --porcelain` must show only DESCRIPTION, README.md, `.Rprofile`, `renv.lock` and `renv/` (`activate.R`, `settings.json`, `.gitignore`), and no library files.
- [ ] **Step 6: Mac end-to-end check** (about 15 min; keep the Mac awake with `caffeinate -i`). Commit first, so the code SHA is the one that runs: `git add DESCRIPTION README.md .Rprofile renv.lock renv/activate.R renv/settings.json renv/.gitignore && git commit -m "Pin R packages with renv; jsonlite for forecast-lab's exporter"`. Then run `caffeinate -i Rscript run.R`. Expected: exit 0 and a clean `git status`.
- [ ] **Step 7: Export check from nfl-drivers' cwd** (pinned jsonlite): `Rscript ../forecast-lab/jobs/export_drivers.R data/cache/results.rds <scratchpad>/export-check`. Then confirm `meta.json` has `code_sha` == `git rev-parse HEAD` and `code_dirty` false.

### Task 3: Publish nfl-drivers and push the SHA map (needs the user's approval)

- [ ] **Step 1: Ask the user** for approval to (a) create the public repo `noah-olivieri/nfl-drivers` and push `master`, and (b) nothing else yet. The forecast-lab map goes to `main` with the merge in Task 10. Show them: the commit count, the clean output of the Task 1 Step 5 greps, and the Task 1 Step 7 map check.
- [ ] **Step 2:** `gh repo create noah-olivieri/nfl-drivers --public --source . --remote origin --push`. Expected: the push succeeds. A rejection for exposing a private email means something leaked: STOP.
- [ ] **Step 3:** `gh api repos/noah-olivieri/nfl-drivers --jq .visibility` prints `public`. Also check `git ls-remote origin master` equals the local HEAD.

### Task 4: Shared slot logic `src/lab/drivers_slots.py`

Stdlib only: the gate imports it before `uv sync`.

**Files:**
- Create: `src/lab/drivers_slots.py`
- Test: `tests/test_drivers_slots.py`

**Interfaces:**
- Produces:
  - Constants: `WINDOWS: dict[str, tuple[timedelta, timedelta]] = {"t48": (48h, 45h), "t24": (24h, 21h), "t3": (2h, 45min)}` (offsets before S for open and close); `PURPOSE = {"t48": "timing", "t24": "timing", "t3": "main"}`; `SLOT_WIDTH = 60min` (exclusive); `COUNT_WINDOW = 3h`; `RUN_GRACE = 45min`; `MISSED_LOOKBACK = 6h`; `GO_LIVE_UNSET = datetime(2099,1,1,tzinfo=UTC)`; `GO_LIVE: dict[str, datetime]` with all three set to `GO_LIVE_UNSET` (Task 10 sets `t3`, Task 11 sets the others).
  - `@dataclass(frozen=True) class Slot: start: datetime; game_ids: tuple[str, ...]` with property `id -> str` (`YYYY-MM-DDTHH:MMZ`).
  - `load_kickoffs(path: Path) -> dict[str, datetime]` (same format as `config/kickoffs.json`; stdlib, so it doesn't import `lab.forecasts`).
  - `build_slots(kickoffs: dict[str, datetime]) -> list[Slot]`: sorted by kickoff; a new slot starts when kickoff − current S ≥ `SLOT_WIDTH`.
  - `find_slot(slots: list[Slot], slot_id: str) -> Slot | None`
  - `window(slot: Slot, timing: str) -> tuple[datetime, datetime]`
  - `@dataclass(frozen=True) class SnapshotRecord: path: Path; created_ts: datetime; purpose: str; timing: str | None; slot: str | None; listed: frozenset[str]`. `listed` = game_ids in `predictions.csv` plus `excluded.csv` rows whose reason ≠ `other_slot`.
  - `read_snapshots(root: Path) -> tuple[list[SnapshotRecord], list[str]]`: one record per `root/*/*/meta.json`. A missing or unreadable `meta.json`/CSV adds a warning and is skipped. Missing `purpose` means `main`.
  - `game_covered_main(game_id: str, kickoff: datetime, records) -> SnapshotRecord | None`: the earliest record with `purpose == "main"`, `kickoff − COUNT_WINDOW <= created_ts < kickoff`, and the game in `listed`.
  - `pair_covered(slot, timing, kickoffs, records) -> bool`: `t3` means every slot game has `game_covered_main`; timing means some record has `slot == slot.id` and `timing == timing`.
  - `eligible(slot, timing, go_live=GO_LIVE) -> bool`: `window(slot, timing)[0] >= go_live[timing]`.
  - `pairs_needing_run(slots, kickoffs, records, now, go_live=GO_LIVE) -> list[tuple[Slot, str]]`: eligible, `open <= now < close`, not covered. Sorted by window open.
  - `missed(slots, kickoffs, records, now, commit_time: Callable[[Path], datetime | None], go_live=GO_LIVE) -> list[str]`: one message per miss.
    - `t3`, per game: eligible slot, `now − MISSED_LOOKBACK < kickoff <= now`, and no record that both `game_covered_main` would accept and has `commit_time(record.path) < kickoff`.
    - Timing, per pair: eligible, `close + RUN_GRACE <= now < close + RUN_GRACE + MISSED_LOOKBACK`, and not `pair_covered`.
  - `check_created_ts(slot, timing, created_ts) -> str | None`: a refusal reason when `created_ts < open` or `created_ts >= close + RUN_GRACE`, else `None`.

- [ ] **Step 1: Write failing tests** in `tests/test_drivers_slots.py`. Use helpers that write `kickoffs.json` and fake snapshot dirs (`meta.json` + `predictions.csv` + `excluded.csv`) into `tmp_path`. Tests and key assertions:
  - `test_constraint_first_attempt_plus_width_within_count_window`: `WINDOWS["t3"][0] + SLOT_WIDTH <= COUNT_WINDOW`.
  - `test_build_slots_groups_405_and_425_not_715_and_815`: kickoffs at 20:05Z and 20:25Z give one slot with id `…T20:05Z`. 23:15Z and 00:15Z next day give two slots.
  - `test_slots_across_dst_and_london`: 2026-10-25 13:30Z, 17:00Z, 20:05Z, 20:25Z, 00:20Z (next day) give 4 slots. 2026-11-01 14:30Z and 18:00Z give 2 slots.
  - `test_window_boundaries_per_timing`: for S, `t3` is open at exactly S−2h and closed at exactly S−45min. `t24` covers [S−24h, S−21h). `t48` covers [S−48h, S−45h).
  - `test_main_coverage_needs_created_within_3h_and_game_listed`: a record at K−3h covers; one at K−3h−1s does not; one at K does not. A record with `purpose="timing"` never covers. A game listed only in `excluded.csv` as `no_prediction` covers; as `other_slot` it does not.
  - `test_moved_kickoff_uncovers_game`: a record at K−2h covers K, but not a moved kickoff of K+2h.
  - `test_read_snapshots_old_format_and_broken_dirs`: a dir with an old meta (no `purpose`/`slot`/`timing`) reads as `main` with `timing=None`. A dir without `meta.json` gives one warning and no record. Nothing raises.
  - `test_pairs_needing_run_open_uncovered_eligible_only`: with `go_live={"t3": past, "t48": UNSET, "t24": UNSET}`, only `t3` pairs appear. A covered pair disappears. A pair outside its window doesn't appear.
  - `test_timing_pair_covered_only_by_matching_slot_and_timing_label`: a manual record (`timing=None`) inside the t24 window doesn't cover t24.
  - `test_missed_t3_after_kickoff_and_commit_time_rule`: a game kicked off 1h ago with a qualifying record whose `commit_time` is after kickoff → missed. With `commit_time` before kickoff → not missed. A kickoff 7h ago → not reported (lookback).
  - `test_missed_timing_after_close_plus_grace`: a t24 pair is not missed at close+44min, and is missed at close+45min.
  - `test_check_created_ts_grace`: `t3` at close+10min → `None`; at close+45min → a reason; at open−1s → a reason.
- [ ] **Step 2:** `PYTHON_DOTENV_DISABLED=1 uv run pytest tests/test_drivers_slots.py -q`. Expected: FAIL (module missing).
- [ ] **Step 3:** Implement `src/lab/drivers_slots.py` per the Interfaces block, stdlib only (`csv`, `json`, `dataclasses`, `datetime`, `pathlib`). Add a test `test_module_is_stdlib_only` that parses the module with `ast` and asserts every import is from the stdlib set (mirror the existing check in `tests/test_forecast_t24.py`, if there is one; otherwise use the explicit allowlist `{"__future__","csv","json","dataclasses","datetime","pathlib","collections.abc","typing"}`).
- [ ] **Step 4:** Run the tests. Expected: PASS. Then run `uv run ruff check .`.
- [ ] **Step 5: Commit** `git add src/lab/drivers_slots.py tests/test_drivers_slots.py && git commit -m "feat: drivers slot rule, windows, coverage and MISSED logic"`.

### Task 5: Gate CLI `jobs/drivers_gate.py`

**Files:**
- Create: `jobs/drivers_gate.py`
- Test: `tests/test_drivers_gate.py`

**Interfaces:**
- Consumes: everything in Task 4.
- Produces:
  - `DRIVERS_CRON = "4,19,34,49 * * * *"` (must equal `drivers.yml`'s cron; these minutes don't collide with :07/:22/:37/:52, :11/:26/:41/:56, :23, or `17 10`).
  - `python3 jobs/drivers_gate.py gate [--now ISO]` writes `pairs=<JSON list of {"slot": id, "timing": t}>` and `missed=true|false` to `$GITHUB_OUTPUT`. It prints `::error title=Drivers snapshot MISSED::<msg>` per miss and `::warning` per unreadable snapshot. Exit 0 = fine, 1 = missed, 2 = crash.
  - `python3 jobs/drivers_gate.py check --slot ID --timing T [--now ISO]` writes `run=true|false`. Exit 0 unless it crashes. An unknown slot means `run=false` plus a warning.
  - `git_commit_time(path: Path) -> datetime | None` uses `git log --diff-filter=A -1 --format=%cI -- <path>/meta.json` and returns `None` when the file isn't committed.
  - The script puts `ROOT / "src"` on `sys.path` and imports `lab.drivers_slots`. It needs no third-party imports.

- [ ] **Step 1: Write failing tests.** Load the script with `importlib`, as `tests/test_forecast_t24.py` does. Set `GITHUB_OUTPUT` to a tmp file. Tests:
  - `test_gate_outputs_open_t3_pair_as_json`: a frozen `now` inside a t3 window with `GO_LIVE` patched → `pairs=[{"slot": "...", "timing": "t3"}]`, `missed=false`, exit 0.
  - `test_gate_reports_missed_and_exits_1`: patch `git_commit_time` to return `None` → `missed=true`, exit 1, and the `::error title=Drivers snapshot MISSED` line is printed.
  - `test_gate_with_unset_go_live_finds_nothing_and_warns`.
  - `test_gate_crash_exits_2`: a missing `kickoffs.json` gives exit 2.
  - `test_check_after_push_says_no_run`: the pair is covered by a snapshot dir in tmp → `run=false`, exit 0.
  - `test_check_unknown_slot_says_no_run`.
  - `test_git_commit_time_none_for_untracked_and_set_for_committed` (tmp git repo; reuse `make_repo`/`git` from `tests/test_drivers_snapshot.py`).
  - `test_gate_runs_with_plain_python_without_uv`: `subprocess.run([sys.executable, "-I", "jobs/drivers_gate.py", "gate", "--now", ...], env={"PATH": ..., "GITHUB_OUTPUT": tmp})` with the paths overridable through `--kickoffs`/`--snapshots` (hidden args for tests) exits 0. This proves the gate needs no installed packages.
- [ ] **Step 2:** Run the tests. Expected: FAIL.
- [ ] **Step 3:** Implement `jobs/drivers_gate.py`. Add a module docstring stating the rule and exit codes in the style of `jobs/forecast_t24.py`. Use `argparse` with hidden `--kickoffs`, `--snapshots` and `--now` for tests.
- [ ] **Step 4:** Run the tests and ruff. Expected: PASS.
- [ ] **Step 5: Commit** `git add jobs/drivers_gate.py tests/test_drivers_gate.py && git commit -m "feat: drivers snapshot gate and per-pair check"`.

### Task 6: `snapshot_drivers.py` slots, labels and exporter changes

**Files:**
- Modify: `src/lab/drivers_snapshot.py` (`PRED_COLUMNS`, `Export`, `read_export`, `build_rows`)
- Modify: `jobs/snapshot_drivers.py` (`run_export`, `take_snapshot`, `main`)
- Modify: `jobs/export_drivers.R` (add `r_version`, `r_packages` to meta.json)
- Test: `tests/test_drivers_snapshot.py`, `tests/test_snapshot_drivers_job.py`

**Interfaces:**
- Consumes: `lab.drivers_slots.{build_slots, find_slot, check_created_ts, PURPOSE, Slot}`.
- Produces:
  - `PRED_COLUMNS` gains `"purpose", "timing", "slot"` **appended at the end**.
  - `Export` gains `r_version: str | None = None` and `r_packages: dict[str, str] | None = None`, read from export `meta.json` (absent → `None`).
  - `build_rows(..., *, disagree=..., slot_games: frozenset[str] | None = None, labels: dict[str, str | None] | None = None, config_kickoffs: dict[str, datetime] | None = None)`:
    - With `slot_games`, upcoming games not in it go to `excluded` with reason `other_slot`. Slot games absent from `export.upcoming` go to `excluded` with reason `not_in_results`, using the kickoff from `config_kickoffs`.
    - Every row gets `labels` (`purpose`, `timing`, `slot`). The default is `{"purpose": "main", "timing": None, "slot": None}`.
  - `run_export(results_rds, out_dir, rscript, cwd: Path)` runs `Rscript` with `cwd=cwd` (the nfl-drivers dir), so renv activates.
  - `take_snapshot(drivers, repo, out_root, *, export_fn, capture_fn, config_kickoffs, slot_id: str | None = None, timing: str | None = None) -> Path`:
    - With `slot_id`, it finds the slot via `build_slots(config_kickoffs)` (unknown → `SnapshotRefused`). After capture it calls `check_created_ts` (reason → `SnapshotRefused`). It passes `slot_games` and labels on.
    - `meta.json` gains `purpose`, `timing`, `slot`, `r_version`, `r_packages`, and `sha256["renv.lock"]` (from `drivers / "renv.lock"`; `None` if missing).
  - CLI: `--slot` and `--timing {t48,t24,t3}` must come together (`ap.error` otherwise). Without them, behavior is unchanged.
  - `export_drivers.R`'s meta adds `r_version = R.version.string` and `r_packages`, a named list of `as.character(utils::packageVersion(p))` for `p` in `nflreadr, glmnet, dplyr, jsonlite`, with `NA` when a package isn't installed.

- [ ] **Step 1: Write failing tests:**
  - In `tests/test_drivers_snapshot.py`:
    - `test_build_rows_slot_filter_marks_other_slot_and_not_in_results`: two upcoming games, `slot_games={A, C}` with C absent from upcoming → rows=[A], excluded has B `other_slot` and C `not_in_results`.
    - `test_rows_carry_labels_and_default_to_main`.
    - `test_pred_columns_end_with_labels`: `PRED_COLUMNS[-3:] == ["purpose","timing","slot"]`.
    - `test_read_export_r_packages_optional`.
  - Extend `test_real_r_export_round_trip` to assert `ex.r_version.startswith("R version")` and `"jsonlite" in ex.r_packages`.
  - In `tests/test_snapshot_drivers_job.py`:
    - `test_slot_run_labels_meta_and_rows`: config kickoffs with HOU@JAX at 13:30Z on 2026-10-18 and T = 12:00Z (inside t3 [11:30, 12:45)) → meta `purpose=main`, `timing=t3`, `slot="2026-10-18T13:30Z"`, and `sha256` has a `renv.lock` key.
    - `test_t3_written_after_close_within_grace`: `capture_fn` returns T = 12:55Z (after close, before kickoff) → written.
    - `test_slot_run_refused_outside_window_plus_grace`: T = 11:29Z → `SnapshotRefused`, nothing written.
    - `test_unknown_slot_refused`.
    - `test_slot_and_timing_must_come_together` (`main(["--slot", "x"])` raises `SystemExit` with code 2).
    - `test_run_export_uses_drivers_cwd`: monkeypatch `subprocess.run` and assert `cwd`.
  - Update `fakes()` so the drivers repo has a committed `renv.lock`.
- [ ] **Step 2:** Run the two test files. Expected: the new tests FAIL and the old ones pass.
- [ ] **Step 3:** Implement per Interfaces. Leave `same_day` alone. Update the `snapshot_drivers.py` docstring with the slot usage.
- [ ] **Step 4:** Run the full suite unpiped, `PYTHON_DOTENV_DISABLED=1 uv run pytest -q`, and ruff. Expected: PASS, including the real-R tests on the Mac.
- [ ] **Step 5: Commit** `git add src/lab/drivers_snapshot.py jobs/snapshot_drivers.py jobs/export_drivers.R tests/test_drivers_snapshot.py tests/test_snapshot_drivers_job.py && git commit -m "feat: slot/timing labels and slot filter in the drivers snapshot"`.

### Task 7: Push script `.github/scripts/push_drivers.sh`

**Files:**
- Create: `.github/scripts/push_drivers.sh` (executable)
- Test: `tests/test_drivers_workflows.py` (new file; import the `git`, `commit_file`, `make_remote` and `clone` helpers from `tests/test_forecast_workflows.py`)

**Interfaces:**
- Produces: `push_drivers.sh SNAPSHOT_DIR LABEL`. `SNAPSHOT_DIR` must match `drivers_snapshots/<YYYY-MM-DD>/<…>Z`. The script commits every file under it, as github-actions[bot], with the message `snapshot: drivers <basename> <LABEL>\n\nrun: <run url>`. It refuses any dir outside `drivers_snapshots/`, an empty dir, or any file already in HEAD. It retries a rejected push up to 4 times with fetch and rebase, and aborts if `FETCH_HEAD` already has any of the files. It appends the commit and per-file SHA-256s to `$GITHUB_STEP_SUMMARY`. The `FORECAST_BRANCH` env override pattern becomes `DRIVERS_BRANCH`.

- [ ] **Step 1: Write failing tests** mirroring the four `push_script` tests in `tests/test_forecast_workflows.py`:
  - `test_push_drivers_pushes_only_the_snapshot_dir_and_summarises`
  - `test_push_drivers_retries_after_a_rejected_push`
  - `test_push_drivers_aborts_if_the_dir_was_already_added`
  - `test_push_drivers_refuses_outside_prefix_existing_files_and_empty_dir`
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3:** Implement it by adapting `push_forecasts.sh`. Don't change `push_forecasts.sh`.
- [ ] **Step 4:** Run them. Expected: PASS.
- [ ] **Step 5: Commit** `git add .github/scripts/push_drivers.sh tests/test_drivers_workflows.py && git commit -m "feat: push_drivers.sh, the bot's only write path for drivers_snapshots/"`.

### Task 8: Workflows `drivers.yml`, `drivers-dryrun.yml` and the composite setup action

**Files:**
- Create: `.github/actions/drivers-setup/action.yml`
- Create: `.github/workflows/drivers.yml`
- Create: `.github/workflows/drivers-dryrun.yml`
- Modify: `tests/test_drivers_workflows.py`

**Interfaces:**
- Consumes: `jobs/drivers_gate.py` (Task 5), `snapshot_drivers.py --slot/--timing` (Task 6), `push_drivers.sh` (Task 7).
- Produces:
  - **Composite `drivers-setup`.** It assumes forecast-lab is checked out at `forecast-lab/`. Steps:
    - checkout `noah-olivieri/nfl-drivers` at `master` to `nfl-drivers/` (`actions/checkout@v7`);
    - `r-lib/actions/setup-r@v2.9.0` with `r-version` read from `nfl-drivers/renv.lock` (a prior step extracts it with `python3 -c`) and `use-public-rspm: true`;
    - `r-lib/actions/setup-renv@v2.9.0` with `working-directory: nfl-drivers`, and env `RENV_CONFIG_REPOS_OVERRIDE` set to the P3M URL for the runner's Ubuntu codename, so restores use Linux binaries;
    - `actions/cache@v6.1.0` with `path: nfl-drivers/data/cache/{pbp,schedules}_20{06..25}.rds` written as explicit globs that exclude 2026, e.g. `nfl-drivers/data/cache/pbp_20[01]?.rds`, `pbp_202[0-5].rds` and the matching `schedules_` patterns, and `key: nflverse-2006-2025-v1`;
    - `Rscript -e 'install.packages("jsonlite")'` outside renv (system library, P3M binary), so forecast-lab's real-R tests can run from forecast-lab's cwd;
    - `astral-sh/setup-uv@v10.2.0` with `enable-cache: true` and `cache-dependency-glob: forecast-lab/uv.lock`, then `uv sync --frozen` in `forecast-lab` (dev deps are needed for pytest).
  - **`drivers.yml`:**
    - `on.schedule` = `[{cron: DRIVERS_CRON}]`, plus `workflow_dispatch` with no inputs; `permissions: contents: write`.
    - Job `gate` (timeout 5): checkout forecast-lab at `main` with `fetch-depth: 0` (path `forecast-lab`), then `python3 jobs/drivers_gate.py gate || [ $? -eq 1 ]`. Outputs `pairs`, `missed`.
    - Job `alert`: `if: needs.gate.outputs.missed == 'true'`, prints `::error` and exits 1.
    - Job `snapshot`: `needs: gate`, `if: needs.gate.outputs.pairs != '[]' && needs.gate.outputs.pairs != ''`, `strategy.matrix.pair: ${{ fromJSON(needs.gate.outputs.pairs) }}`, `fail-fast: false`, `timeout-minutes: 40`, `concurrency: {group: "drivers-${{ matrix.pair.slot }}-${{ matrix.pair.timing }}", cancel-in-progress: false}`. Steps:
      1. checkout forecast-lab at `main` (path `forecast-lab`, `fetch-depth: 0`);
      2. `python3 jobs/drivers_gate.py check --slot … --timing …` → output `run`; every later step has `if: steps.check.outputs.run == 'true'`;
      3. `uses: ./forecast-lab/.github/actions/drivers-setup`;
      4. `Rscript run.R` (working-directory `nfl-drivers`);
      5. `uv run --no-sync python jobs/snapshot_drivers.py --drivers ../nfl-drivers --slot … --timing …` (working-directory `forecast-lab`), parsing `wrote <dir>` into output `dir`;
      6. `PYTHON_DOTENV_DISABLED=1 uv run --no-sync pytest -q` (no pipe);
      7. `uv run --no-sync ruff check .`;
      8. `.github/scripts/push_drivers.sh "$DIR" "$TIMING slot $SLOT"`.
    - The YAML header comment explains the rule, the windows, the reason for the odd minutes, and the concurrency choice, in the style of `forecast.yml`.
  - `snapshot_drivers.py` must print a parseable `wrote drivers_snapshots/...` line. It already does; keep it.
  - **`drivers-dryrun.yml`:** `workflow_dispatch` only, `permissions: contents: read`. The same checkout and setup, then `run.R`, `snapshot_drivers.py` without flags (manual mode, written only inside the ephemeral runner), pytest and ruff. It never pushes. It writes the step timings to the summary.

- [ ] **Step 1: Write failing tests** in `tests/test_drivers_workflows.py`:
  - `test_drivers_cron_equals_the_constant`
  - `test_drivers_manual_run_has_no_inputs`: same assertions as the forecast test, with `"inputs."` absent.
  - `test_snapshot_job_matrix_concurrency_is_per_pair_without_cancel`: `group` contains both `matrix.pair.slot` and `matrix.pair.timing`, and `cancel-in-progress` is False.
  - `test_snapshot_job_runs_only_when_gate_found_pairs_and_alert_on_missed`
  - `test_every_step_after_check_is_gated_on_run`
  - `test_pytest_unpiped_and_ruff_before_push`: in step order, a pytest step whose `run` contains `pytest -q` and no `|`, then ruff, then `push_drivers.sh` last.
  - `test_checkouts_are_siblings`: forecast-lab `path: forecast-lab`, and nfl-drivers `path: nfl-drivers` in the composite action.
  - `test_nflverse_cache_never_includes_2026`: no cache path matches `pbp_2026.rds` or `schedules_2026.rds` (check with `fnmatch` against each glob).
  - `test_dryrun_never_pushes`: no `push_` scripts and `contents: read`.
  - `test_drivers_action_versions_are_the_verified_ones`: `uses` across the three files ⊆ `{"actions/checkout@v7", "astral-sh/setup-uv@v10.2.0", "r-lib/actions/setup-r@v2.9.0", "r-lib/actions/setup-renv@v2.9.0", "actions/cache@v6.1.0", "./forecast-lab/.github/actions/drivers-setup"}`.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Write the three YAML files per Interfaces.
- [ ] **Step 4:** Run the full suite unpiped and ruff. Expected: PASS. Also run `python3 -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/drivers*.yml .github/actions/drivers-setup/action.yml` (via `uv run`) to confirm the YAML parses.
- [ ] **Step 5: Commit** `git add .github/actions/drivers-setup/action.yml .github/workflows/drivers.yml .github/workflows/drivers-dryrun.yml tests/test_drivers_workflows.py && git commit -m "feat: drivers snapshot workflow, dry-run workflow and setup action"`.

### Task 9: Docs and rules

**Files:**
- Modify: `CLAUDE.md`. Rules: the third bot exception, worded like the existing two (`drivers` workflow, github-actions[bot], `.github/scripts/push_drivers.sh`, may push NEW files under `drivers_snapshots/`, never modifies or deletes). Layout: `drivers.yml`, `drivers_gate.py`, `drivers_slots.py`. Status: the NFL Drivers bullet describes the bot, the windows, `GO_LIVE`, and the manual route as the fallback (renv restore once; the run.R/snapshot steps are unchanged).
- Modify: `docs/superpowers/specs/2026-10-15-drivers-weekly-snapshot-design.md`. Add a dated note under "Which snapshot counts": "2026-10-19: this same-day rule governs week 6 only. From week 7 the rule in DECISIONS.md (2026-10-19) applies; see 2026-10-19-drivers-snapshot-automation-design.md." Delete nothing.

- [ ] **Step 1:** Make both edits.
- [ ] **Step 2:** Run the full suite unpiped and ruff (some tests read CLAUDE.md or the specs). Expected: PASS.
- [ ] **Step 3: Commit** `git add CLAUDE.md docs/superpowers/specs/2026-10-15-drivers-weekly-snapshot-design.md && git commit -m "docs: drivers bot exception, layout and status; base spec counting note"`.

### Task 10: Go live (needs the user's approval)

- [ ] **Step 1: Pick `GO_LIVE["t3"]`.** Use the next whole hour after the planned merge, as an aware UTC datetime. It must be before 2026-10-25T11:30Z. If the merge happens before 2026-10-22T22:15Z, the Thursday NE@CHI t3 window (opens 22:15Z) is eligible too. Set it in `src/lab/drivers_slots.py`, add a test `test_go_live_t3_is_set_and_before_london_first_attempt`, then run the suite, ruff, and commit.
- [ ] **Step 2: Review.** Run `git log --oneline main..drivers-auto` and `git diff --stat main...drivers-auto`, then hand off for the whole-branch review (Native execution: one fresh reviewer). Fix any findings with tests.
- [ ] **Step 3: Ask the user** for approval to merge `drivers-auto` into `main` and push. Show them the commit list, the test result, and the GO_LIVE value.
- [ ] **Step 4: Push.** `git checkout main && git pull --ff-only && git merge --no-ff drivers-auto`. Run the full suite unpiped and ruff on `main`. Check `.env` and `data/` aren't staged. Then `git push origin main`.
- [ ] **Step 5: Dry run on GitHub.** `gh workflow run drivers-dryrun.yml`, then `gh run watch <id> --exit-status`. Expected: success. Record the setup, run.R and snapshot durations from the summary. If total > 30 min, tell the user before Sunday (the 40-minute timeout and the 45-minute grace depend on it).
- [ ] **Step 6:** Run `gh workflow run drivers-dryrun.yml` again and confirm both caches hit: the setup-renv log reports a cache restore, and `actions/cache` logs `Cache restored from key: nflverse-2006-2025-v1`.
- [ ] **Step 7: Confirm the gate runs on schedule.** `gh run list --workflow drivers.yml --limit 5` shows scheduled runs exiting quickly with no matrix jobs outside windows. Tell the user the first eligible window, and remind them of the manual Thursday snapshot if `GO_LIVE["t3"]` is after the NE@CHI window.

## Stage 2: timing records (after stage 1 is live; slip a week rather than rush)

### Task 11: Enable `t48` and `t24`

**Files:**
- Modify: `src/lab/drivers_slots.py` (`GO_LIVE["t48"]`, `GO_LIVE["t24"]`)
- Modify: `tests/test_drivers_slots.py`, `CLAUDE.md` status

- [ ] **Step 1:** Choose a go-live (the next whole hour after merge) for both timings. Test: `test_go_live_timing_set_after_t3`, plus a gate test with a frozen `now` inside a t24 window that yields a `t24` pair.
- [ ] **Step 2:** Run the full suite unpiped and ruff, then commit on a branch `drivers-timing`.
- [ ] **Step 3:** Ask the user for approval, merge to `main`, run pytest and ruff on `main`, and push.
- [ ] **Step 4:** After the first t48 and t24 windows, confirm snapshots exist with `purpose=timing` and the matching `timing`/`slot` in `meta.json` and `predictions.csv`. Confirm `gh run list --workflow drivers.yml` shows no MISSED alert.
