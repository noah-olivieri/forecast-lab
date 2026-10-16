# NFL Drivers Weekly Snapshot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Before kickoff, save NFL Drivers' `full_qb_ridge` win probabilities, the inputs behind them, and Kalshi + Polymarket US quotes captured at the same moment, in a timestamped directory that is never overwritten.

**Architecture:** nfl-drivers gains `results$upcoming_features` and a `weather_imputed` flag (R). forecast-lab gains a short R exporter (`jobs/export_drivers.R`) that turns `results.rds` into CSV/JSON, a pure-logic module (`src/lab/drivers_snapshot.py`) for checks, kickoffs, quote matching and writing, and a CLI (`jobs/snapshot_drivers.py`) that runs the export and a live quote capture and wires them together. Output goes to `drivers_snapshots/`, outside `forecasts/`, covered by the append-only CI guard.

**Tech Stack:** R 4.3+ (dplyr, testthat, jsonlite), Python 3.12 (uv, pytest, polars only via existing ingest), git.

**Spec:** `docs/superpowers/specs/2026-10-15-drivers-weekly-snapshot-design.md`

## Global Constraints

- Model: `full_qb_ridge` only; `p_home` = its `pred_win` (P(home team wins)).
- Freshness: `results$created` and `schedule_downloaded` must each be in `[created_ts - 6h, created_ts]`; otherwise refuse, write nothing.
- Quote age: a quote with `ts_utc` more than 5 minutes before `created_ts` (or after it) is treated as missing.
- Kickoffs come from the exported `gameday` + `gametime` via `lab.ingest.nflverse.kickoff_dt`; a missing or unparseable time for any `full_qb_ridge` game fails the run. `config/kickoffs.json` is read, never written; the pre-kickoff check uses the earlier of the two times.
- A game with kickoff at or before `created_ts` is excluded (`game_started`).
- `status` is `ok`, `no_kalshi_quote`, or `no_quotes`; rows are written in every case; if no row has a quote, print a loud `::error` but still write.
- Both repos must be clean (`git status --porcelain` empty); forecast-lab ignores paths under `drivers_snapshots/`. `results$created` must be at or after nfl-drivers HEAD's commit time.
- Output: `drivers_snapshots/<created_ts date in ET>/<created_ts as YYYY-MM-DDTHH-MM-SS>Z/`, created exclusively; an existing directory is a refusal.
- "Game day" = kickoff's calendar date in `America/New_York`.
- Never touch `forecasts/`, `config/kickoffs.json`, `RESEARCH_PROTOCOL.md`, or the T-24h job.
- CLAUDE.md rules apply: stage by explicit path, never `git add -A`; before any push run unpiped `PYTHON_DOTENV_DISABLED=1 uv run pytest -q` and `uv run ruff check .`; every push needs the user's approval; never force-push.
- Line length 100 (ruff). Match surrounding style: module docstrings, `# fmt: skip` on aligned literals, no new dependencies.

## Review Focus

1. A `full_qb_ridge` row whose `pred_win` is NA (nfl-drivers keeps games whose starter isn't listed): excluded with reason `no_prediction`, never written with an empty `p_home`. Test in Task 6.
2. `schedule_downloaded` missing (no cached schedule file): refuse, since freshness cannot be checked. Test in Task 5.
3. Team codes that differ between nflverse and Kalshi (JAX→JAC, LA→LAR); this Sunday has HOU@JAX. The Kalshi ticker must be `KXNFLGAME-26OCT18HOUJAC-JAC`. Test in Task 6.
4. Two rows for the same ticker in one capture: treated as missing with a warning, not a crash of the whole snapshot. Test in Task 6.
5. A game after the DST change (2026-11-01): `gameday` + `gametime` in ET must convert at UTC-5, and `game_day_et` / `same_day` stay correct near ET midnight. Test in Task 5 and Task 6.

---

## File Structure

nfl-drivers (`/Users/noaholivieri/Documents/nfl-drivers`, branch `master`, no remote; prior work was committed straight to master):
- Modify `R/features.R`: add `weather_imputed` to `build_features()` output.
- Modify `R/validate.R`: add `upcoming_features()`.
- Modify `R/pipeline.R`: save `results$upcoming_features`, check it matches `upcoming`.
- Modify `tests/testthat/test-features.R`, `tests/testthat/test-validate.R`.

forecast-lab (new worktree `/Users/noaholivieri/Documents/forecast-lab-drivers`, branch `drivers-snapshot` off `origin/main`):
- Modify `.github/scripts/check_forecasts_append_only.sh`, `.github/workflows/ci.yml` (step name), `tests/test_forecast_workflows.py`: guard covers `drivers_snapshots/`.
- Create `jobs/export_drivers.R`: `results.rds` → `upcoming.csv`, `features.csv` (if present), `meta.json`.
- Create `src/lab/drivers_snapshot.py`: pure logic (no network, no R).
- Create `jobs/snapshot_drivers.py`: CLI; runs R export, captures quotes, calls the logic.
- Create `tests/test_drivers_snapshot.py`, `tests/test_snapshot_drivers_job.py`.
- Modify `CLAUDE.md`: layout + status lines.

---

### Task 1: nfl-drivers `weather_imputed` flag

**Files:**
- Modify: `/Users/noaholivieri/Documents/nfl-drivers/R/features.R` (the `dplyr::mutate(dome = ...)` before `fill_median`, and the final `dplyr::select`)
- Test: `/Users/noaholivieri/Documents/nfl-drivers/tests/testthat/test-features.R`

**Interfaces:**
- Produces: `build_features()` output gains numeric column `weather_imputed` (1 = source `temp` or `wind` was NA before median filling, else 0). No other value changes.

- [ ] **Step 1: Write the failing test** (append to `test-features.R`, and add `"weather_imputed"` to the `expect_named` list in "columns match the spec's feature table")

```r
test_that("weather_imputed marks games whose temp or wind was missing before filling", {
  s <- toy_sched()
  f <- build_features(s, toy_ratings(), toy_stadiums())
  src <- s[match(f$game_id, s$game_id), ]
  expect_equal(f$weather_imputed, as.numeric(is.na(src$temp) | is.na(src$wind)))
  expect_equal(row_of(f, "g2")$weather_imputed, 1)   # toy g2 has no weather recorded
  expect_equal(row_of(f, "g1")$weather_imputed, 0)
})
```

The edited `expect_named` call:

```r
  expect_named(feats(), c("game_id", "season", "week", "gameday", "margin", "win",
                          FEATURE_GROUPS$strength, FEATURE_GROUPS$situational,
                          FEATURE_GROUPS$qb, FEATURE_GROUPS$environment, "spread",
                          "home_qb_adj", "away_qb_adj", "qb_change_game", "weather_imputed"),
               ignore.order = TRUE)
```

- [ ] **Step 2: Run tests to verify they fail**

Run (from nfl-drivers): `Rscript -e 'testthat::test_file("tests/testthat/test-features.R")'`
Expected: FAIL in both tests (`weather_imputed` missing).

- [ ] **Step 3: Implement**

In `R/features.R`, change the mutate before `fill_median(stadium_id, season)` to:

```r
  games <- games |>
    dplyr::mutate(dome = as.numeric(roof %in% c("dome", "closed")),
                  temp = as.numeric(temp), wind = as.numeric(wind),
                  # Set before filling, so the archive shows which values are medians.
                  weather_imputed = as.numeric(is.na(temp) | is.na(wind))) |>
    fill_median(stadium_id, season) |>
    fill_median(stadium_id) |>
    fill_median(season)
```

and add `weather_imputed` to the final select:

```r
    dplyr::select(game_id, season, week, gameday, margin, win,
                  dplyr::all_of(unlist(FEATURE_GROUPS, use.names = FALSE)), spread,
                  home_qb_adj, away_qb_adj, qb_change_game, weather_imputed)
```

- [ ] **Step 4: Run the whole suite**

Run: `Rscript -e 'testthat::test_dir("tests/testthat")'`
Expected: all pass (no other test pins the exact column set; model specs select columns by name).

- [ ] **Step 5: Commit**

```bash
git -C /Users/noaholivieri/Documents/nfl-drivers add R/features.R tests/testthat/test-features.R
git -C /Users/noaholivieri/Documents/nfl-drivers commit -m "Flag games whose weather was filled from medians

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: nfl-drivers `results$upcoming_features`

**Files:**
- Modify: `/Users/noaholivieri/Documents/nfl-drivers/R/validate.R` (next to `upcoming_predictions`)
- Modify: `/Users/noaholivieri/Documents/nfl-drivers/R/pipeline.R`
- Test: `/Users/noaholivieri/Documents/nfl-drivers/tests/testthat/test-validate.R`

**Interfaces:**
- Consumes: `weather_imputed` column from Task 1.
- Produces: `upcoming_features(features, vars)` → data.frame with columns `game_id, season, week, <vars>, weather_imputed`, unplayed games only. `results$upcoming_features` = `upcoming_features(features_ridge, MODEL_SPECS$full_qb)`.

- [ ] **Step 1: Write the failing test** (append to `test-validate.R`)

```r
test_that("upcoming_features keeps only unplayed games and the model's columns", {
  f <- data.frame(game_id = c("done", "next1"), season = 2026L, week = c(5L, 6L),
                  margin = c(3, NA), win = c(1, NA), a = c(0.1, 0.2), b = c(1, 2),
                  weather_imputed = c(0, 1), extra = 9)
  out <- upcoming_features(f, c("a", "b"))
  expect_equal(out$game_id, "next1")
  expect_named(out, c("game_id", "season", "week", "a", "b", "weather_imputed"))
  expect_equal(out$weather_imputed, 1)
})

test_that("upcoming_features errors if a model column is missing", {
  f <- data.frame(game_id = "x", season = 2026L, week = 6L, margin = NA, weather_imputed = 0)
  expect_error(upcoming_features(f, "a"))
})
```

- [ ] **Step 2: Run to verify failure**

Run: `Rscript -e 'testthat::test_file("tests/testthat/test-validate.R")'`
Expected: FAIL, `could not find function "upcoming_features"`.

- [ ] **Step 3: Implement** in `R/validate.R`, directly after `upcoming_predictions()`:

```r
# Feature rows behind the forecast week's predictions: unplayed games only, with the
# model's inputs and weather_imputed, so a snapshot can archive what was predicted from.
upcoming_features <- function(features, vars) {
  cols <- c("game_id", "season", "week", vars, "weather_imputed")
  as.data.frame(features[is.na(features$margin), cols, drop = FALSE])
}
```

In `R/pipeline.R`, right after `upcoming <- upcoming_predictions(preds_all, sched_rate)` and before `features_ridge <- completed(features_ridge)`:

```r
  upcoming_feats <- upcoming_features(features_ridge, MODEL_SPECS$full_qb)
  stopifnot(setequal(upcoming_feats$game_id,
                     upcoming$game_id[upcoming$model == "full_qb_ridge"]))
```

and in the `results <- list(...)` add, after `upcoming = upcoming,`:

```r
    upcoming_features = upcoming_feats,
```

- [ ] **Step 4: Run the whole suite**

Run: `Rscript -e 'testthat::test_dir("tests/testthat")'`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git -C /Users/noaholivieri/Documents/nfl-drivers add R/validate.R R/pipeline.R tests/testthat/test-validate.R
git -C /Users/noaholivieri/Documents/nfl-drivers commit -m "Save the forecast week's full_qb feature rows in results

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

(`Rscript run.R` is not run here. The user runs it on game day; until then `results.rds` lacks `upcoming_features` and the snapshot runs in `provenance_only` mode.)

---

### Task 3: forecast-lab branch + append-only guard covers `drivers_snapshots/`

**Files:**
- Modify: `.github/scripts/check_forecasts_append_only.sh`
- Modify: `.github/workflows/ci.yml` (step name only)
- Test: `tests/test_forecast_workflows.py`

**Interfaces:**
- Produces: the guard fails on any modify/delete/rename/retype under `forecasts/`, `results/` or `drivers_snapshots/`.

- [ ] **Step 1: Create the worktree and bring the spec and plan over**

```bash
cd /Users/noaholivieri/Documents/forecast-lab
git fetch origin
git worktree add ../forecast-lab-drivers -b drivers-snapshot origin/main
cd ../forecast-lab-drivers
git cherry-pick 0751c58           # the spec
git cherry-pick "$(git log -1 --format=%H research-foundation -- docs/superpowers/plans/2026-10-15-drivers-weekly-snapshot.md)"
uv sync
```

All later forecast-lab paths are relative to `/Users/noaholivieri/Documents/forecast-lab-drivers`.

- [ ] **Step 2: Write the failing test** (in `tests/test_forecast_workflows.py`, after `test_guard_fails_on_delete`)

```python
def test_guard_fails_when_a_commit_modifies_a_drivers_snapshot(tmp_path):
    repo, base = history(tmp_path)
    path = "drivers_snapshots/2026-10-18/2026-10-18T12-00-00Z/predictions.csv"
    commit_file(repo, path, "a\n", "add snapshot")
    assert guard(repo, base, "HEAD").returncode == 0  # adding is fine
    commit_file(repo, path, "b\n", "edit snapshot")
    r = guard(repo, base, "HEAD")
    assert r.returncode == 1 and path in r.stdout + r.stderr
```

- [ ] **Step 3: Run to verify failure**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_forecast_workflows.py -k drivers_snapshot`
Expected: FAIL (second guard call returns 0).

- [ ] **Step 4: Implement** in `.github/scripts/check_forecasts_append_only.sh`:

Header comment line 2-3 becomes:

```bash
# Fail if any commit in BASE..HEAD modifies, deletes, renames or retypes an existing file under
# forecasts/, results/ or drivers_snapshots/. Adding new files is fine. Checked commit by commit
# (-m also covers merge commits), so an edit that a later commit reverts is still caught.
```

and the body:

```bash
changes="$(git log -m --no-renames --diff-filter=MDT --name-status --format= "$range" -- forecasts/ results/ drivers_snapshots/)"
if [ -n "$changes" ]; then
  echo "::error title=forecasts/, results/ and drivers_snapshots/ are append-only::existing files were changed:"
  echo "$changes"
  exit 1
fi
echo "forecasts/, results/ and drivers_snapshots/ are append-only over $range"
```

In `.github/workflows/ci.yml` rename the step (the `run:` line stays identical; a test pins it):

```yaml
      - name: forecasts/, results/ and drivers_snapshots/ are append-only (whole history)
        run: .github/scripts/check_forecasts_append_only.sh "" HEAD
```

- [ ] **Step 5: Run the workflow tests**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_forecast_workflows.py`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add .github/scripts/check_forecasts_append_only.sh .github/workflows/ci.yml tests/test_forecast_workflows.py
git commit -m "ci: make drivers_snapshots/ append-only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: R exporter and `read_export`

**Files:**
- Create: `jobs/export_drivers.R`
- Create: `src/lab/drivers_snapshot.py` (first part)
- Test: `tests/test_drivers_snapshot.py`

**Interfaces:**
- Produces:
  - `Rscript jobs/export_drivers.R RESULTS_RDS OUT_DIR` writes `OUT_DIR/upcoming.csv` (`full_qb_ridge` rows, columns as `results$upcoming`, NA as empty), `OUT_DIR/features.csv` (only if `results$upcoming_features` exists), `OUT_DIR/meta.json` `{"created": ISO-Z|null, "schedule_downloaded": ISO-Z|null, "upcoming_dropped": int|null, "n_rows": int}`. Exit nonzero on bad args or missing `results` fields.
  - `lab.drivers_snapshot`: `MODEL = "full_qb_ridge"`, `class SnapshotRefused(RuntimeError)`, `@dataclass(frozen=True) class Export(dir: Path, upcoming: list[dict[str, str]], results_created: datetime | None, schedule_downloaded: datetime | None, upcoming_dropped: int | None)` with property `mode -> "full" | "provenance_only"`, `read_export(export_dir: Path) -> Export`.

- [ ] **Step 1: Write the failing tests** (`tests/test_drivers_snapshot.py`)

```python
"""Pure logic of the NFL Drivers weekly snapshot (spec 2026-10-15). No network."""

import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from lab import drivers_snapshot as ds

REPO = Path(__file__).parent.parent
EXPORT_R = REPO / "jobs" / "export_drivers.R"
UP_COLS = [
    "model", "game_id", "season", "week", "gameday", "gametime", "away_team", "home_team",
    "away_qb_name", "home_qb_name", "spread", "pred_margin", "pred_win",
]  # fmt: skip


def up_row(game_id="2026_06_HOU_JAX", gameday="2026-10-18", gametime="09:30", away="HOU",
           home="JAX", pred_win="0.68", model="full_qb_ridge", **kw):  # fmt: skip
    row = dict(model=model, game_id=game_id, season="2026", week="6", gameday=gameday,
               gametime=gametime, away_team=away, home_team=home, away_qb_name="C.J. Stroud",
               home_qb_name="Trevor Lawrence", spread="2.5", pred_margin="5.5",
               pred_win=pred_win)  # fmt: skip
    row.update(kw)
    return row


def fake_export(tmp_path, rows, *, created="2026-10-18T10:00:00Z",
                downloaded="2026-10-18T09:00:00Z", dropped=0, features=False):  # fmt: skip
    d = tmp_path / "export"
    d.mkdir(parents=True)
    lines = [",".join(UP_COLS)] + [",".join(r[c] for c in UP_COLS) for r in rows]
    (d / "upcoming.csv").write_text("\n".join(lines) + "\n")
    if features:
        (d / "features.csv").write_text("game_id,season,week,weather_imputed\nx,2026,6,0\n")
    meta = {"created": created, "schedule_downloaded": downloaded,
            "upcoming_dropped": dropped, "n_rows": len(rows)}  # fmt: skip
    (d / "meta.json").write_text(json.dumps(meta))
    return d


def test_read_export_keeps_full_qb_ridge_rows_and_parses_times(tmp_path):
    d = fake_export(tmp_path, [up_row(), up_row(model="base")])
    ex = ds.read_export(d)
    assert [r["model"] for r in ex.upcoming] == ["full_qb_ridge"]
    assert ex.results_created == datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    assert ex.schedule_downloaded == datetime(2026, 10, 18, 9, 0, tzinfo=UTC)
    assert ex.upcoming_dropped == 0
    assert ex.mode == "provenance_only"


def test_read_export_full_mode_when_features_exist(tmp_path):
    assert ds.read_export(fake_export(tmp_path, [up_row()], features=True)).mode == "full"


def test_read_export_null_times_become_none(tmp_path):
    ex = ds.read_export(fake_export(tmp_path, [up_row()], downloaded=None))
    assert ex.schedule_downloaded is None


def test_read_export_refuses_without_model_rows(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="full_qb_ridge"):
        ds.read_export(fake_export(tmp_path, [up_row(model="base")]))


def test_read_export_refuses_incomplete_export(tmp_path):
    d = fake_export(tmp_path, [up_row()])
    (d / "meta.json").unlink()
    with pytest.raises(ds.SnapshotRefused, match="incomplete"):
        ds.read_export(d)


RSCRIPT = shutil.which("Rscript")
MAKE_RDS = """
args <- commandArgs(TRUE)
up <- data.frame(model = c("full_qb_ridge", "base"), game_id = "2026_06_HOU_JAX",
  season = 2026L, week = 6L, gameday = as.Date("2026-10-18"), gametime = "09:30",
  away_team = "HOU", home_team = "JAX", away_qb_name = c("C.J. Stroud", NA),
  home_qb_name = "Trevor Lawrence", spread = 2.5, pred_margin = 5.5, pred_win = c(0.68, 0.6))
r <- list(created = as.POSIXct("2026-10-18 10:00:00", tz = "UTC"),
  schedule_downloaded = as.POSIXct("2026-10-18 02:00:00", tz = "America/Los_Angeles"),
  upcoming_dropped = 1L, upcoming = up)
if (args[2] == "full") r$upcoming_features <- data.frame(game_id = "2026_06_HOU_JAX",
  season = 2026L, week = 6L, home = 1, weather_imputed = 1)
saveRDS(r, args[1])
"""


@pytest.mark.skipif(RSCRIPT is None, reason="Rscript not installed")
@pytest.mark.parametrize("mode", ["provenance_only", "full"])
def test_real_r_export_round_trip(tmp_path, mode):
    rds, out = tmp_path / "results.rds", tmp_path / "out"
    subprocess.run([RSCRIPT, "-e", MAKE_RDS, "--args", str(rds), mode], check=True)
    subprocess.run([RSCRIPT, str(EXPORT_R), str(rds), str(out)], check=True)
    ex = ds.read_export(out)
    assert ex.mode == mode
    assert len(ex.upcoming) == 1 and ex.upcoming[0]["away_qb_name"] == "C.J. Stroud"
    assert ex.upcoming[0]["gameday"] == "2026-10-18" and ex.upcoming[0]["gametime"] == "09:30"
    assert float(ex.upcoming[0]["pred_win"]) == pytest.approx(0.68)
    assert ex.results_created == datetime(2026, 10, 18, 10, 0, tzinfo=UTC)
    assert ex.schedule_downloaded == datetime(2026, 10, 18, 9, 0, tzinfo=UTC)  # PDT -> UTC
    assert ex.upcoming_dropped == 1


@pytest.mark.skipif(RSCRIPT is None, reason="Rscript not installed")
def test_real_r_export_fails_on_missing_fields(tmp_path):
    rds = tmp_path / "bad.rds"
    subprocess.run([RSCRIPT, "-e", f"saveRDS(list(created = Sys.time()), '{rds}')"], check=True)
    r = subprocess.run([RSCRIPT, str(EXPORT_R), str(rds), str(tmp_path / "o")],
                       capture_output=True, text=True)  # fmt: skip
    assert r.returncode != 0 and "upcoming" in r.stderr
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py`
Expected: FAIL, `ImportError: cannot import name 'drivers_snapshot'`.

- [ ] **Step 3: Write `jobs/export_drivers.R`**

```r
# Export the parts of nfl-drivers' results.rds that the weekly snapshot archives.
#   Rscript jobs/export_drivers.R RESULTS_RDS OUT_DIR
# Writes upcoming.csv (full_qb_ridge rows), features.csv (only if results has
# upcoming_features) and meta.json. Base R + jsonlite only; NA is written as empty / null.
args <- commandArgs(trailingOnly = TRUE)
if (length(args) != 2) stop("usage: export_drivers.R RESULTS_RDS OUT_DIR")
r <- readRDS(args[[1]])
need <- c("upcoming", "upcoming_dropped", "schedule_downloaded", "created")
missing <- setdiff(need, names(r))
if (length(missing)) stop("results.rds lacks: ", paste(missing, collapse = ", "))

out <- args[[2]]
dir.create(out, showWarnings = FALSE, recursive = TRUE)
iso <- function(x) {
  if (length(x) != 1 || is.na(x)) return(NA)
  format(as.POSIXct(x), "%Y-%m-%dT%H:%M:%SZ", tz = "UTC")
}
up <- as.data.frame(r$upcoming)
up <- up[up$model == "full_qb_ridge", , drop = FALSE]
up$gameday <- as.character(up$gameday)
utils::write.csv(up, file.path(out, "upcoming.csv"), row.names = FALSE, na = "")
if (!is.null(r$upcoming_features)) {
  utils::write.csv(as.data.frame(r$upcoming_features), file.path(out, "features.csv"),
                   row.names = FALSE, na = "")
}
meta <- list(created = iso(r$created), schedule_downloaded = iso(r$schedule_downloaded),
             upcoming_dropped = if (is.null(r$upcoming_dropped)) NA else as.integer(r$upcoming_dropped),
             n_rows = nrow(up))
writeLines(jsonlite::toJSON(meta, auto_unbox = TRUE, na = "null"), file.path(out, "meta.json"))
```

- [ ] **Step 4: Write the first part of `src/lab/drivers_snapshot.py`**

```python
"""NFL Drivers weekly snapshot: archive full_qb_ridge win probabilities, their inputs and
same-moment Kalshi + Polymarket US quotes (spec docs/superpowers/specs/
2026-10-15-drivers-weekly-snapshot-design.md).

Pure logic, no network and no R: jobs/snapshot_drivers.py runs the R export and the quote
capture and passes their results in. Any failed check raises SnapshotRefused before anything
is written; a snapshot directory is created exclusively and never overwritten.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

MODEL = "full_qb_ridge"


class SnapshotRefused(RuntimeError):
    """A check failed; nothing may be written."""


def _utc(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


@dataclass(frozen=True)
class Export:
    """What jobs/export_drivers.R wrote: full_qb_ridge rows as strings, plus run metadata."""

    dir: Path
    upcoming: list[dict[str, str]]
    results_created: datetime | None
    schedule_downloaded: datetime | None
    upcoming_dropped: int | None

    @property
    def mode(self) -> str:
        return "full" if (self.dir / "features.csv").exists() else "provenance_only"


def read_export(export_dir: Path) -> Export:
    meta_path, up_path = export_dir / "meta.json", export_dir / "upcoming.csv"
    if not meta_path.exists() or not up_path.exists():
        raise SnapshotRefused(f"R export incomplete in {export_dir}")
    meta = json.loads(meta_path.read_text())
    with up_path.open(newline="") as f:
        rows = [r for r in csv.DictReader(f) if r.get("model") == MODEL]
    if not rows:
        raise SnapshotRefused(f"no {MODEL} rows in results$upcoming")
    return Export(
        export_dir, rows, _utc(meta.get("created")), _utc(meta.get("schedule_downloaded")),
        meta.get("upcoming_dropped"),
    )  # fmt: skip
```

- [ ] **Step 5: Run tests**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py`
Expected: all pass locally (the two R tests run because `Rscript` is installed; in CI they skip).

- [ ] **Step 6: Commit**

```bash
git add jobs/export_drivers.R src/lab/drivers_snapshot.py tests/test_drivers_snapshot.py
git commit -m "feat(drivers): export nfl-drivers results for the weekly snapshot

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: repo checks, freshness, kickoffs

**Files:**
- Modify: `src/lab/drivers_snapshot.py`
- Test: `tests/test_drivers_snapshot.py`

**Interfaces:**
- Consumes: `Export`, `SnapshotRefused` (Task 4).
- Produces:
  - `FRESHNESS = timedelta(hours=6)`, `iso_z(ts: datetime) -> str` (`YYYY-MM-DDTHH:MM:SSZ`)
  - `clean_head(repo: Path, allow_prefix: str | None = None) -> str` (HEAD sha; refuses on any porcelain line not under `allow_prefix`)
  - `head_commit_time(repo: Path) -> datetime` (aware UTC)
  - `check_results_after_commit(results_created: datetime | None, commit_time: datetime) -> None`
  - `check_freshness(export: Export, created_ts: datetime) -> None`
  - `schedule_kickoffs(rows: list[dict[str, str]]) -> dict[str, datetime]`
  - `effective_kickoffs(schedule: dict[str, datetime], config: dict[str, datetime]) -> tuple[dict[str, datetime], list[dict[str, str]]]` (earlier time per game; disagreement records `{"game_id", "schedule", "kickoffs_json"}`)

- [ ] **Step 1: Write the failing tests** (append)

```python
import os
from datetime import timedelta

T = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)  # capture time in tests: Sunday 08:00 ET


# Fixed commit dates: results_created in the fixtures (2026-10-18) must stay after HEAD's commit
# time however late the tests run.
GIT_ENV = {**os.environ, "GIT_AUTHOR_DATE": "2026-10-01T00:00:00Z",
           "GIT_COMMITTER_DATE": "2026-10-01T00:00:00Z"}  # fmt: skip


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True,
                          text=True, env=GIT_ENV).stdout.strip()  # fmt: skip


def make_repo(tmp_path, name="r"):
    repo = tmp_path / name
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "t@example.com")
    git(repo, "config", "user.name", "t")
    (repo / "a.txt").write_text("a\n")
    git(repo, "add", "a.txt")
    git(repo, "commit", "-q", "-m", "init")
    return repo


def test_clean_head_returns_sha_for_a_clean_repo(tmp_path):
    repo = make_repo(tmp_path)
    assert ds.clean_head(repo) == git(repo, "rev-parse", "HEAD")


@pytest.mark.parametrize("dirty", ["modified", "untracked"])
def test_clean_head_refuses_dirty_repo(tmp_path, dirty):
    repo = make_repo(tmp_path)
    if dirty == "modified":
        (repo / "a.txt").write_text("b\n")  # first porcelain line starts with a space
    else:
        (repo / "new.py").write_text("x\n")
    with pytest.raises(ds.SnapshotRefused, match="uncommitted"):
        ds.clean_head(repo)


def test_clean_head_allows_untracked_snapshots_only(tmp_path):
    repo = make_repo(tmp_path)
    snap = repo / "drivers_snapshots" / "2026-10-15" / "x"
    snap.mkdir(parents=True)
    (snap / "predictions.csv").write_text("x\n")
    assert ds.clean_head(repo, allow_prefix="drivers_snapshots/")
    (repo / "a.txt").write_text("b\n")
    with pytest.raises(ds.SnapshotRefused, match="a.txt"):
        ds.clean_head(repo, allow_prefix="drivers_snapshots/")


def test_results_must_postdate_the_drivers_commit(tmp_path):
    commit_time = ds.head_commit_time(make_repo(tmp_path))
    ds.check_results_after_commit(commit_time, commit_time)
    with pytest.raises(ds.SnapshotRefused, match="before"):
        ds.check_results_after_commit(commit_time - timedelta(seconds=1), commit_time)
    with pytest.raises(ds.SnapshotRefused):
        ds.check_results_after_commit(None, commit_time)


def ex_with(tmp_path, created, downloaded):
    iso = lambda t: None if t is None else t.strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    return ds.read_export(fake_export(tmp_path, [up_row()], created=iso(created),
                                      downloaded=iso(downloaded)))  # fmt: skip


def test_freshness_allows_exactly_six_hours(tmp_path):
    ds.check_freshness(ex_with(tmp_path, T - timedelta(hours=6), T - timedelta(hours=6)), T)


@pytest.mark.parametrize("which", ["created", "downloaded"])
def test_freshness_refuses_six_hours_and_a_second(tmp_path, which):
    old, ok = T - timedelta(hours=6, seconds=1), T - timedelta(hours=1)
    ex = ex_with(tmp_path, old if which == "created" else ok, old if which == "downloaded" else ok)
    with pytest.raises(ds.SnapshotRefused, match="more than"):
        ds.check_freshness(ex, T)


def test_freshness_refuses_timestamps_after_capture(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="after capture"):
        ds.check_freshness(ex_with(tmp_path, T + timedelta(seconds=1), T), T)


def test_freshness_refuses_missing_schedule_download_time(tmp_path):  # Review Focus 2
    with pytest.raises(ds.SnapshotRefused, match="schedule_downloaded is missing"):
        ds.check_freshness(ex_with(tmp_path, T, None), T)


def test_schedule_kickoffs_convert_eastern_to_utc_across_dst():  # Review Focus 5
    k = ds.schedule_kickoffs([
        up_row(),  # 2026-10-18 09:30 EDT
        up_row(game_id="2026_09_A_B", gameday="2026-11-01", gametime="13:00"),  # EST
    ])  # fmt: skip
    assert k["2026_06_HOU_JAX"] == datetime(2026, 10, 18, 13, 30, tzinfo=UTC)
    assert k["2026_09_A_B"] == datetime(2026, 11, 1, 18, 0, tzinfo=UTC)


@pytest.mark.parametrize("gameday,gametime", [("", "13:00"), ("2026-10-18", ""),
                                              ("2026-10-18", "1pm")])  # fmt: skip
def test_schedule_kickoffs_fail_on_missing_or_bad_time(gameday, gametime):
    rows = [up_row(), up_row(game_id="2026_06_X_Y", gameday=gameday, gametime=gametime)]
    with pytest.raises(ds.SnapshotRefused, match="2026_06_X_Y"):
        ds.schedule_kickoffs(rows)


def test_effective_kickoffs_take_the_earlier_and_record_disagreements():
    a, b = datetime(2026, 10, 18, 17, tzinfo=UTC), datetime(2026, 10, 18, 20, 25, tzinfo=UTC)
    eff, dis = ds.effective_kickoffs({"g1": a, "g2": b, "g3": a},
                                     {"g1": a, "g2": b - timedelta(hours=1)})  # fmt: skip
    assert eff == {"g1": a, "g2": b - timedelta(hours=1), "g3": a}
    assert dis == [{"game_id": "g2", "schedule": "2026-10-18T20:25:00Z",
                    "kickoffs_json": "2026-10-18T19:25:00Z"}]  # fmt: skip
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py`
Expected: new tests FAIL with `AttributeError: module 'lab.drivers_snapshot' has no attribute ...`.

- [ ] **Step 3: Implement** (add to `src/lab/drivers_snapshot.py`; extend imports to `import subprocess`, `from datetime import UTC, datetime, timedelta`, `from lab.ingest.nflverse import kickoff_dt`)

```python
FRESHNESS = timedelta(hours=6)


def iso_z(ts: datetime) -> str:
    return ts.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git(repo: Path, *args: str) -> str:
    """Raw stdout (not stripped: porcelain lines start with a status column that may be a space)."""
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


def clean_head(repo: Path, allow_prefix: str | None = None) -> str:
    """HEAD's SHA; refuses if anything outside `allow_prefix` is modified or untracked."""
    out = _git(repo, "status", "--porcelain=v1", "--untracked-files=all")
    dirty = [
        line[3:] for line in out.splitlines()
        if line and not (allow_prefix and line[3:].startswith(allow_prefix))
    ]  # fmt: skip
    if dirty:
        raise SnapshotRefused(f"{repo}: uncommitted changes: {', '.join(dirty[:5])}")
    return _git(repo, "rev-parse", "HEAD").strip()


def head_commit_time(repo: Path) -> datetime:
    return datetime.fromisoformat(_git(repo, "show", "-s", "--format=%cI", "HEAD").strip())


def check_results_after_commit(results_created: datetime | None, commit_time: datetime) -> None:
    if results_created is None or results_created < commit_time:
        shown = "missing" if results_created is None else iso_z(results_created)
        raise SnapshotRefused(
            f"results$created ({shown}) is before nfl-drivers HEAD's commit time "
            f"{iso_z(commit_time)}; rerun `Rscript run.R` on this commit"
        )


def check_freshness(export: Export, created_ts: datetime) -> None:
    for name, ts in (
        ("results$created", export.results_created),
        ("schedule_downloaded", export.schedule_downloaded),
    ):
        if ts is None:
            raise SnapshotRefused(f"{name} is missing; freshness cannot be checked")
        if ts > created_ts:
            raise SnapshotRefused(f"{name} {iso_z(ts)} is after capture {iso_z(created_ts)}")
        if created_ts - ts > FRESHNESS:
            raise SnapshotRefused(
                f"{name} {iso_z(ts)} is more than {FRESHNESS} before capture {iso_z(created_ts)}"
            )


def schedule_kickoffs(rows: list[dict[str, str]]) -> dict[str, datetime]:
    """Kickoff per game from the schedule the model used; any missing or bad time refuses."""
    out, bad = {}, []
    for r in rows:
        try:
            out[r["game_id"]] = kickoff_dt(r["gameday"], r["gametime"])
        except (KeyError, TypeError, ValueError):
            bad.append(r.get("game_id") or "?")
    if bad:
        raise SnapshotRefused("no usable kickoff time for: " + ", ".join(bad))
    return out


def effective_kickoffs(
    schedule: dict[str, datetime], config: dict[str, datetime]
) -> tuple[dict[str, datetime], list[dict[str, str]]]:
    """The earlier of the schedule and config/kickoffs.json times, plus every disagreement."""
    eff, disagreements = {}, []
    for game_id, k in schedule.items():
        c = config.get(game_id)
        if c is not None and c != k:
            disagreements.append({"game_id": game_id, "schedule": iso_z(k), "kickoffs_json": iso_z(c)})
        eff[game_id] = k if c is None else min(k, c)
    return eff, disagreements
```

- [ ] **Step 4: Run tests**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py`
Expected: all pass. If `("2026-10-18", "")` does not raise in `kickoff_dt` (Python 3.12 `fromisoformat("2026-10-18T")`), add an explicit `if not r.get("gameday") or not r.get("gametime"): raise ValueError` inside the `try`, then rerun.

- [ ] **Step 5: Commit**

```bash
git add src/lab/drivers_snapshot.py tests/test_drivers_snapshot.py
git commit -m "feat(drivers): repo, freshness and kickoff checks for the weekly snapshot

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: rows and quote matching

**Files:**
- Modify: `src/lab/drivers_snapshot.py`
- Test: `tests/test_drivers_snapshot.py`

**Interfaces:**
- Consumes: `Export`, `schedule_kickoffs`, `effective_kickoffs` (Tasks 4-5); `lab.forecasts._tickers`, `NICKNAMES`, `flip_quote`; `lab.ingest.nflverse.ET`.
- Produces:
  - `QUOTE_MAX_AGE = timedelta(minutes=5)`, `PRED_COLUMNS: list[str]`, `EXCLUDED_COLUMNS = ["game_id", "kickoff_ts", "reason"]`
  - `build_rows(export: Export, kickoffs: dict[str, datetime], effective: dict[str, datetime], quotes: list[dict], created_ts: datetime, drivers_sha: str) -> tuple[list[dict], list[dict], list[str]]` (rows, excluded, warnings). `quotes` are snapshot-schema dicts (`venue`, `market_ticker`, `ts_utc`, `subtitle`, `yes_bid`, `yes_ask`, `yes_bid_size`, `yes_ask_size`).
  - `no_quotes_at_all(rows: list[dict]) -> bool`

- [ ] **Step 1: Write the failing tests** (append)

```python
def quote(venue, ticker, bid, ask, ts=T - timedelta(seconds=30), subtitle=None, size=None):
    return {"venue": venue, "market_ticker": ticker, "ts_utc": ts, "subtitle": subtitle,
            "yes_bid": bid, "yes_ask": ask, "yes_bid_size": size, "yes_ask_size": size}  # fmt: skip


K_HOU_JAX = "KXNFLGAME-26OCT18HOUJAC-JAC"  # Review Focus 3: JAX -> JAC on Kalshi
P_HOU_JAX = "aec-nfl-hou-jax-2026-10-18"


def rows_for(tmp_path, up, quotes, created=T, config=None):
    ex = ds.read_export(fake_export(tmp_path, up))
    k = ds.schedule_kickoffs(ex.upcoming)
    eff, _ = ds.effective_kickoffs(k, config or {})
    return ds.build_rows(ex, k, eff, quotes, created, "abc123")


def test_ok_row_with_both_venues_and_flipped_polymarket(tmp_path):
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68, size=100.0),
         quote("polymarket_us", P_HOU_JAX, 0.30, 0.33, subtitle="Texans")]  # YES = away
    rows, excluded, warnings = rows_for(tmp_path, [up_row()], q)
    (r,) = rows
    assert excluded == [] and warnings == []
    assert r["status"] == "ok" and r["p_home"] == 0.68 and r["pred_margin"] == 5.5
    assert r["model"] == "full_qb_ridge" and r["model_version"] == "nfl-drivers@abc123"
    assert r["kalshi_ticker"] == K_HOU_JAX and r["kalshi_yes_bid"] == 0.66
    assert r["kalshi_bid_size"] == 100.0
    assert r["poly_flipped"] is True and r["poly_yes_team_raw"] == "Texans"
    assert (r["poly_yes_bid"], r["poly_yes_ask"]) == (0.67, 0.7)  # 1 - ask, 1 - bid
    assert r["home_qb_projected"] == "Trevor Lawrence" and r["away_qb_projected"] == "C.J. Stroud"
    assert r["kickoff_ts"] == datetime(2026, 10, 18, 13, 30, tzinfo=UTC)
    assert r["minutes_to_kickoff"] == 90
    assert r["game_day_et"] == "2026-10-18" and r["same_day"] is True


def test_statuses_without_kalshi_or_any_quote(tmp_path):
    poly = [quote("polymarket_us", P_HOU_JAX, 0.6, 0.7, subtitle="Jaguars")]
    (r,), _, _ = rows_for(tmp_path, [up_row()], poly)
    assert r["status"] == "no_kalshi_quote" and r["kalshi_yes_bid"] is None
    assert r["poly_flipped"] is False and r["poly_yes_bid"] == 0.6
    rows, _, _ = rows_for(tmp_path / "b", [up_row()], [])
    assert rows[0]["status"] == "no_quotes" and ds.no_quotes_at_all(rows)


def test_stale_or_future_quotes_are_missing(tmp_path):
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68, ts=T - timedelta(minutes=5, seconds=1)),
         quote("polymarket_us", P_HOU_JAX, 0.6, 0.7, ts=T + timedelta(seconds=1),
               subtitle="Jaguars")]  # fmt: skip
    (r,), _, warnings = rows_for(tmp_path, [up_row()], q)
    assert r["status"] == "no_quotes" and len(warnings) == 2


def test_quote_exactly_five_minutes_old_is_used(tmp_path):
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68, ts=T - timedelta(minutes=5))]
    (r,), _, _ = rows_for(tmp_path, [up_row()], q)
    assert r["status"] == "ok"


def test_duplicate_ticker_rows_are_missing_with_a_warning(tmp_path):  # Review Focus 4
    q = [quote("kalshi", K_HOU_JAX, 0.66, 0.68), quote("kalshi", K_HOU_JAX, 0.1, 0.2)]
    (r,), _, warnings = rows_for(tmp_path, [up_row()], q)
    assert r["status"] == "no_quotes" and "2 kalshi rows" in warnings[0]


def test_unmappable_polymarket_side_is_missing_with_a_warning(tmp_path):
    q = [quote("polymarket_us", P_HOU_JAX, 0.6, 0.7, subtitle="Draw")]
    (r,), _, warnings = rows_for(tmp_path, [up_row()], q)
    assert r["poly_yes_bid"] is None and "Draw" in warnings[0]


def test_started_game_is_excluded_at_the_boundary(tmp_path):
    kickoff = datetime(2026, 10, 18, 13, 30, tzinfo=UTC)
    rows, excluded, _ = rows_for(tmp_path, [up_row()], [], created=kickoff)
    assert rows == [] and excluded == [
        {"game_id": "2026_06_HOU_JAX", "kickoff_ts": kickoff, "reason": "game_started"}
    ]


def test_earlier_config_kickoff_excludes_the_game(tmp_path):
    early = {"2026_06_HOU_JAX": T}  # kickoffs.json says it already started
    rows, excluded, _ = rows_for(tmp_path, [up_row()], [], config=early)
    assert rows == [] and excluded[0]["reason"] == "game_started"


def test_na_prediction_is_excluded(tmp_path):  # Review Focus 1
    rows, excluded, _ = rows_for(tmp_path, [up_row(pred_win="")], [])
    assert rows == [] and excluded[0]["reason"] == "no_prediction"


def test_same_day_is_judged_in_eastern_time(tmp_path):  # Review Focus 5
    # 03:59Z on Oct 18 is 23:59 ET on Oct 17: not the game's day.
    (r,), _, _ = rows_for(tmp_path, [up_row()], [], created=datetime(2026, 10, 18, 3, 59, tzinfo=UTC))
    assert r["same_day"] is False
    # 04:00Z is 00:00 ET Oct 18: same day, inside the London game's 00:00-09:30 ET window.
    (r,), _, _ = rows_for(tmp_path / "b", [up_row()], [],
                          created=datetime(2026, 10, 18, 4, 0, tzinfo=UTC))  # fmt: skip
    assert r["same_day"] is True


def test_rows_are_sorted_by_kickoff_and_cover_every_column(tmp_path):
    up = [up_row(game_id="2026_06_DAL_GB", away="DAL", home="GB", gametime="20:20"), up_row()]
    rows, _, _ = rows_for(tmp_path, up, [])
    assert [r["game_id"] for r in rows] == ["2026_06_HOU_JAX", "2026_06_DAL_GB"]
    assert set(rows[0]) == set(ds.PRED_COLUMNS)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py`
Expected: new tests FAIL (`build_rows` missing).

- [ ] **Step 3: Implement** (add to `src/lab/drivers_snapshot.py`; extend imports with `from lab.forecasts import NICKNAMES, _tickers, flip_quote` and `from lab.ingest.nflverse import ET, kickoff_dt`)

```python
QUOTE_MAX_AGE = timedelta(minutes=5)
KALSHI, POLYMARKET = "kalshi", "polymarket_us"

PRED_COLUMNS = [
    "game_id", "season", "week", "home_team", "away_team", "kickoff_ts",
    "kickoff_source_disagrees", "game_day_et", "same_day", "created_ts", "minutes_to_kickoff",
    "model", "model_version", "p_home", "pred_margin", "home_qb_projected",
    "away_qb_projected", "status",
    "kalshi_ticker", "kalshi_yes_bid", "kalshi_yes_ask", "kalshi_bid_size", "kalshi_ask_size",
    "kalshi_quote_ts",
    "poly_ticker", "poly_yes_team_raw", "poly_flipped", "poly_yes_bid", "poly_yes_ask",
    "poly_quote_ts",
]  # fmt: skip
EXCLUDED_COLUMNS = ["game_id", "kickoff_ts", "reason"]


def _num(text: str | None) -> float | None:
    return float(text) if text not in (None, "", "NA") else None


def _pick(quotes, venue, ticker, created_ts, game_id, warnings) -> dict | None:
    hits = [q for q in quotes if q["venue"] == venue and q["market_ticker"] == ticker]
    if len(hits) > 1:
        warnings.append(f"{game_id}: {len(hits)} {venue} rows for {ticker}; treated as missing")
        return None
    if not hits:
        return None
    q = hits[0]
    if q["ts_utc"] > created_ts or created_ts - q["ts_utc"] > QUOTE_MAX_AGE:
        warnings.append(f"{game_id}: {venue} quote at {iso_z(q['ts_utc'])} is stale; treated as missing")
        return None
    return q


def _quote_fields(r, kickoff, quotes, created_ts, warnings) -> dict:
    game_id, home, away = r["game_id"], r["home_team"], r["away_team"]
    k_ticker, p_ticker = _tickers(away, home, kickoff.astimezone(ET))
    k = _pick(quotes, KALSHI, k_ticker, created_ts, game_id, warnings)
    p = _pick(quotes, POLYMARKET, p_ticker, created_ts, game_id, warnings)
    flipped = None
    if p is not None:
        yes_team = NICKNAMES.get(p["subtitle"])
        if yes_team not in (home, away):
            warnings.append(f"{p_ticker}: cannot map YES side {p['subtitle']!r}; treated as missing")
            p = None
        else:
            flipped = yes_team == away
    p_bid, p_ask = (None, None) if p is None else (p["yes_bid"], p["yes_ask"])
    if flipped:
        p_bid, p_ask = flip_quote(p_bid, p_ask)
    kv = (lambda key: None) if k is None else (lambda key: k[key])
    return {
        "status": "ok" if k else ("no_kalshi_quote" if p else "no_quotes"),
        "kalshi_ticker": k_ticker, "kalshi_yes_bid": kv("yes_bid"), "kalshi_yes_ask": kv("yes_ask"),
        "kalshi_bid_size": kv("yes_bid_size"), "kalshi_ask_size": kv("yes_ask_size"),
        "kalshi_quote_ts": kv("ts_utc"),
        "poly_ticker": p_ticker, "poly_yes_team_raw": None if p is None else p["subtitle"],
        "poly_flipped": flipped, "poly_yes_bid": p_bid, "poly_yes_ask": p_ask,
        "poly_quote_ts": None if p is None else p["ts_utc"],
    }  # fmt: skip


def build_rows(
    export: Export,
    kickoffs: dict[str, datetime],
    effective: dict[str, datetime],
    quotes: list[dict],
    created_ts: datetime,
    drivers_sha: str,
) -> tuple[list[dict], list[dict], list[str]]:
    """One row per game still before kickoff; started or unpredicted games go to `excluded`."""
    rows, excluded, warnings = [], [], []
    capture_day = created_ts.astimezone(ET).date()
    for r in sorted(export.upcoming, key=lambda r: (kickoffs[r["game_id"]], r["game_id"])):
        game_id, kickoff = r["game_id"], kickoffs[r["game_id"]]
        if effective[game_id] <= created_ts:
            excluded.append({"game_id": game_id, "kickoff_ts": kickoff, "reason": "game_started"})
            continue
        p_home = _num(r.get("pred_win"))
        if p_home is None:
            excluded.append({"game_id": game_id, "kickoff_ts": kickoff, "reason": "no_prediction"})
            continue
        game_day = kickoff.astimezone(ET).date()
        rows.append({
            "game_id": game_id, "season": r["season"], "week": r["week"],
            "home_team": r["home_team"], "away_team": r["away_team"], "kickoff_ts": kickoff,
            "kickoff_source_disagrees": effective[game_id] != kickoff,
            "game_day_et": game_day.isoformat(), "same_day": game_day == capture_day,
            "created_ts": created_ts,
            "minutes_to_kickoff": int((kickoff - created_ts).total_seconds() // 60),
            "model": MODEL, "model_version": f"nfl-drivers@{drivers_sha}", "p_home": p_home,
            "pred_margin": _num(r.get("pred_margin")),
            "home_qb_projected": r.get("home_qb_name") or None,
            "away_qb_projected": r.get("away_qb_name") or None,
            **_quote_fields(r, kickoff, quotes, created_ts, warnings),
        })  # fmt: skip
    return rows, excluded, warnings


def no_quotes_at_all(rows: list[dict]) -> bool:
    return bool(rows) and all(r["status"] == "no_quotes" for r in rows)
```

- [ ] **Step 4: Run tests and lint**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py && uv run ruff check src/lab/drivers_snapshot.py tests/test_drivers_snapshot.py`
Expected: all pass; ruff clean (wrap any line over 100 chars).

- [ ] **Step 5: Commit**

```bash
git add src/lab/drivers_snapshot.py tests/test_drivers_snapshot.py
git commit -m "feat(drivers): build snapshot rows and match same-moment quotes

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: writing the snapshot directory

**Files:**
- Modify: `src/lab/drivers_snapshot.py`
- Test: `tests/test_drivers_snapshot.py`

**Interfaces:**
- Consumes: `PRED_COLUMNS`, `EXCLUDED_COLUMNS`, `Export` (Tasks 4, 6); `lab.forecasts._fmt` (datetime → `YYYY-MM-DDTHH:MM:SSZ`, None → "").
- Produces:
  - `snapshot_dir(out_root: Path, created_ts: datetime) -> Path`
  - `sha256_file(path: Path) -> str | None`
  - `write_snapshot(out_root: Path, created_ts: datetime, rows: list[dict], excluded: list[dict], meta: dict, export: Export, schedule_rds: Path | None) -> Path` (raises `SnapshotRefused` if the directory exists)

- [ ] **Step 1: Write the failing tests** (append)

```python
import csv as _csv


def test_snapshot_dir_is_dated_in_eastern_time(tmp_path):
    late = datetime(2026, 10, 18, 3, 30, 5, tzinfo=UTC)  # 23:30 ET on Oct 17
    assert ds.snapshot_dir(tmp_path, late) == tmp_path / "2026-10-17" / "2026-10-18T03-30-05Z"


def write(tmp_path, features=False, created=T):
    ex = ds.read_export(fake_export(tmp_path, [up_row()], features=features))
    sched = tmp_path / "schedules_2026.rds"
    sched.write_bytes(b"rds-bytes")
    rows, excluded, _ = rows_for(tmp_path / "r", [up_row()], [])
    return ds.write_snapshot(tmp_path / "out", created, rows, excluded, {"mode": ex.mode}, ex, sched)


def test_write_snapshot_writes_every_file(tmp_path):
    d = write(tmp_path, features=True)
    assert sorted(p.relative_to(d).as_posix() for p in d.rglob("*") if p.is_file()) == [
        "excluded.csv", "inputs/features.csv", "inputs/schedules_2026.rds",
        "inputs/upcoming.csv", "meta.json", "predictions.csv",
    ]  # fmt: skip
    with (d / "predictions.csv").open(newline="") as f:
        (row,) = list(_csv.DictReader(f))
    assert list(row) == ds.PRED_COLUMNS
    assert row["kickoff_ts"] == "2026-10-18T13:30:00Z" and row["kalshi_yes_bid"] == ""
    assert (d / "inputs/schedules_2026.rds").read_bytes() == b"rds-bytes"
    assert json.loads((d / "meta.json").read_text()) == {"mode": "full"}


def test_write_snapshot_provenance_only_has_no_features(tmp_path):
    d = write(tmp_path)
    assert not (d / "inputs/features.csv").exists()


def test_write_snapshot_never_overwrites(tmp_path):
    d = write(tmp_path)
    before = (d / "predictions.csv").read_bytes()
    ex = ds.read_export(tmp_path / "export")
    with pytest.raises(ds.SnapshotRefused, match="already exists"):
        ds.write_snapshot(tmp_path / "out", T, [], [], {}, ex, None)
    assert (d / "predictions.csv").read_bytes() == before


def test_sha256_file(tmp_path):
    p = tmp_path / "x"
    p.write_bytes(b"abc")
    assert ds.sha256_file(p) == (
        "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    )
    assert ds.sha256_file(tmp_path / "missing") is None
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py`
Expected: new tests FAIL (`snapshot_dir` missing).

- [ ] **Step 3: Implement** (add to `src/lab/drivers_snapshot.py`; extend imports with `import hashlib`, `import shutil`, and `_fmt` from `lab.forecasts`)

```python
def snapshot_dir(out_root: Path, created_ts: datetime) -> Path:
    et_day = created_ts.astimezone(ET).strftime("%Y-%m-%d")
    return out_root / et_day / f"{created_ts.astimezone(UTC):%Y-%m-%dT%H-%M-%S}Z"


def sha256_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, columns: list[str], rows: list[dict]) -> None:
    with path.open("x", newline="") as f:
        w = csv.writer(f)
        w.writerow(columns)
        for r in rows:
            w.writerow([_fmt(r.get(c)) for c in columns])


def write_snapshot(
    out_root: Path,
    created_ts: datetime,
    rows: list[dict],
    excluded: list[dict],
    meta: dict,
    export: Export,
    schedule_rds: Path | None,
) -> Path:
    """Create the snapshot directory exclusively and write every file into it."""
    d = snapshot_dir(out_root, created_ts)
    d.parent.mkdir(parents=True, exist_ok=True)
    try:
        d.mkdir()
    except FileExistsError:
        raise SnapshotRefused(f"{d} already exists; snapshots are never overwritten") from None
    _write_csv(d / "predictions.csv", PRED_COLUMNS, rows)
    _write_csv(d / "excluded.csv", EXCLUDED_COLUMNS, excluded)
    inputs = d / "inputs"
    inputs.mkdir()
    shutil.copyfile(export.dir / "upcoming.csv", inputs / "upcoming.csv")
    if export.mode == "full":
        shutil.copyfile(export.dir / "features.csv", inputs / "features.csv")
    if schedule_rds is not None and schedule_rds.is_file():
        shutil.copyfile(schedule_rds, inputs / schedule_rds.name)
    (d / "meta.json").write_text(json.dumps(meta, indent=1, sort_keys=True) + "\n")
    return d
```

- [ ] **Step 4: Run tests and lint**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_drivers_snapshot.py && uv run ruff check .`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/lab/drivers_snapshot.py tests/test_drivers_snapshot.py
git commit -m "feat(drivers): write snapshot directories exclusively

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: the CLI, end to end

**Files:**
- Create: `jobs/snapshot_drivers.py`
- Modify: `CLAUDE.md` (Layout and Status)
- Test: `tests/test_snapshot_drivers_job.py`

**Interfaces:**
- Consumes: everything in `lab.drivers_snapshot`; `lab.forecasts.load_kickoffs`; `lab.ingest.kalshi`, `lab.ingest.polymarket_us`.
- Produces: `take_snapshot(drivers: Path, repo: Path, out_root: Path, *, export_fn, capture_fn, config_kickoffs: dict[str, datetime]) -> Path`, where `export_fn(results_rds: Path, out_dir: Path) -> None` and `capture_fn() -> tuple[list[dict], dict[str, list[str]], datetime]` (quotes, errors per venue, `created_ts` taken when capture finished). `main(argv) -> int`: 0 written, 1 refused, 2 crash.

- [ ] **Step 1: Write the failing tests** (`tests/test_snapshot_drivers_job.py`)

```python
"""jobs/snapshot_drivers.py wiring, with the R export and quote capture faked. No network."""

import importlib.util
import json
import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from lab import drivers_snapshot as ds

JOB = Path(__file__).parent.parent / "jobs" / "snapshot_drivers.py"
spec = importlib.util.spec_from_file_location("snapshot_drivers", JOB)
sd = importlib.util.module_from_spec(spec)
sys.modules["snapshot_drivers"] = sd
spec.loader.exec_module(sd)

sys.path.insert(0, str(Path(__file__).parent))
from test_drivers_snapshot import fake_export, git, make_repo, quote, up_row  # noqa: E402

T = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)


def drivers_repo(tmp_path):
    repo = make_repo(tmp_path, "drivers")
    (repo / ".gitignore").write_text("data/cache/\n")
    git(repo, "add", ".gitignore")
    git(repo, "commit", "-q", "-m", "ignore")
    cache = repo / "data" / "cache"
    cache.mkdir(parents=True)
    for name in ("results.rds", "schedules_2026.rds", "pbp_2026.rds"):
        (cache / name).write_bytes(name.encode())
    return repo


def fakes(tmp_path, *, quotes=None, created=None, features=False):
    src = fake_export(tmp_path, [up_row()], features=features,
                      created=(created or T - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))

    def export_fn(results_rds, out_dir):
        assert results_rds.name == "results.rds"
        shutil.copytree(src, out_dir, dirs_exist_ok=True)

    def capture_fn():
        return quotes if quotes is not None else [], {"kalshi": [], "polymarket_us": []}, T

    return export_fn, capture_fn


def run(tmp_path, **kw):
    drivers = drivers_repo(tmp_path)
    lab = make_repo(tmp_path, "lab")
    export_fn, capture_fn = fakes(tmp_path, **kw)
    return sd.take_snapshot(drivers, lab, lab / "drivers_snapshots", export_fn=export_fn,
                            capture_fn=capture_fn, config_kickoffs={})  # fmt: skip


def test_end_to_end_writes_snapshot_and_meta(tmp_path):
    q = [quote("kalshi", "KXNFLGAME-26OCT18HOUJAC-JAC", 0.66, 0.68)]
    d = run(tmp_path, quotes=q)
    assert d.parent.name == "2026-10-18" and d.name == "2026-10-18T12-00-00Z"
    meta = json.loads((d / "meta.json").read_text())
    assert meta["mode"] == "provenance_only" and meta["n_games"] == 1 and meta["n_excluded"] == 0
    assert meta["created_ts"] == "2026-10-18T12:00:00Z"
    assert meta["upcoming_dropped"] == 0
    assert len(meta["nfl_drivers_sha"]) == 40 and len(meta["forecast_lab_sha"]) == 40
    assert meta["sha256"]["schedules_2026.rds"] == ds.sha256_file(
        tmp_path / "drivers/data/cache/schedules_2026.rds"
    )
    assert (d / "inputs" / "schedules_2026.rds").exists()


def test_no_quotes_still_writes(tmp_path, capsys):
    d = run(tmp_path, quotes=[])
    assert (d / "predictions.csv").exists()
    assert "::error title=No quotes" in capsys.readouterr().out


def test_stale_results_refuse_and_write_nothing(tmp_path):
    with pytest.raises(ds.SnapshotRefused, match="more than"):
        run(tmp_path, created=T - timedelta(hours=7))
    assert not (tmp_path / "lab" / "drivers_snapshots").exists()


def test_dirty_drivers_repo_refuses(tmp_path):
    drivers = drivers_repo(tmp_path)
    (drivers / "R.R").write_text("x\n")
    lab = make_repo(tmp_path, "lab")
    export_fn, capture_fn = fakes(tmp_path)
    with pytest.raises(ds.SnapshotRefused, match="uncommitted"):
        sd.take_snapshot(drivers, lab, lab / "drivers_snapshots", export_fn=export_fn,
                         capture_fn=capture_fn, config_kickoffs={})  # fmt: skip


def test_main_returns_1_on_refusal(tmp_path, monkeypatch, capsys):
    def refuse(*a, **k):
        raise ds.SnapshotRefused("nope")

    monkeypatch.setattr(sd, "take_snapshot", refuse)
    assert sd.main(["--drivers", str(tmp_path)]) == 1
    assert "::error title=Snapshot refused::nope" in capsys.readouterr().out
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_snapshot_drivers_job.py`
Expected: FAIL (`jobs/snapshot_drivers.py` does not exist).

- [ ] **Step 3: Write `jobs/snapshot_drivers.py`**

```python
"""Take one NFL Drivers weekly snapshot (spec docs/superpowers/specs/
2026-10-15-drivers-weekly-snapshot-design.md).

    uv run python jobs/snapshot_drivers.py [--drivers ../nfl-drivers] [--rscript Rscript]

Run `Rscript run.R` in nfl-drivers first (within 6 hours). Both repos must be clean. Writes
drivers_snapshots/<ET date>/<UTC time>Z/ and prints the paths to commit; it never commits or
pushes. Exit 0 = written, 1 = refused (nothing written), 2 = crash.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import traceback
from datetime import UTC, datetime
from pathlib import Path

import yaml

from lab import drivers_snapshot as ds
from lab.config import CONFIG_DIR
from lab.forecasts import load_kickoffs

ROOT = Path(__file__).resolve().parent.parent
EXPORT_R = ROOT / "jobs" / "export_drivers.R"
OUT_ROOT = ROOT / "drivers_snapshots"


def run_export(results_rds: Path, out_dir: Path, rscript: str = "Rscript") -> None:
    try:
        r = subprocess.run([rscript, str(EXPORT_R), str(results_rds), str(out_dir)],
                           capture_output=True, text=True, check=False)  # fmt: skip
    except FileNotFoundError:
        raise ds.SnapshotRefused(f"{rscript} not found") from None
    if r.returncode != 0:
        raise ds.SnapshotRefused(f"R export failed ({r.returncode}): {r.stderr.strip()[-500:]}")


def capture_quotes() -> tuple[list[dict], dict[str, list[str]], datetime]:
    """NFL winner quotes from both venues; a venue that fails records errors, never raises."""
    from lab.ingest import kalshi, polymarket_us  # lazy: network clients

    cfg = yaml.safe_load((CONFIG_DIR / "markets.yaml").read_text())
    ts = datetime.now(UTC).replace(microsecond=0)
    quotes, errors = [], {}
    for venue in (ds.KALSHI, ds.POLYMARKET):
        try:
            if venue == ds.KALSHI:
                api = kalshi.make_api()
                try:
                    rows, errs = kalshi.snapshot(api, {"nfl": cfg["kalshi"]["nfl"]}, ts)
                finally:
                    api.close()
            else:
                api = polymarket_us.make_api()
                try:
                    rows, errs = polymarket_us.snapshot(api, ts)
                finally:
                    api.close()
        except Exception as exc:  # noqa: BLE001  one venue failing must not stop the other
            rows, errs = [], [f"{type(exc).__name__}: {exc}"]
        errors[venue] = errs
        quotes += [r for r in rows if r.get("group") == "nfl" and r.get("kind") == "winner"]
    return quotes, errors, datetime.now(UTC).replace(microsecond=0)


def take_snapshot(drivers, repo, out_root, *, export_fn, capture_fn, config_kickoffs) -> Path:
    drivers_sha = ds.clean_head(drivers)
    lab_sha = ds.clean_head(repo, allow_prefix="drivers_snapshots/")
    cache = drivers / "data" / "cache"
    with tempfile.TemporaryDirectory() as tmp:
        export_fn(cache / "results.rds", Path(tmp))
        export = ds.read_export(Path(tmp))
        ds.check_results_after_commit(export.results_created, ds.head_commit_time(drivers))
        kickoffs = ds.schedule_kickoffs(export.upcoming)
        effective, disagreements = ds.effective_kickoffs(kickoffs, config_kickoffs)
        quotes, capture_errors, created_ts = capture_fn()
        ds.check_freshness(export, created_ts)
        rows, excluded, warnings = ds.build_rows(
            export, kickoffs, effective, quotes, created_ts, drivers_sha
        )
        season = max(int(r["season"]) for r in export.upcoming)
        schedule_rds = cache / f"schedules_{season}.rds"
        hashed = ("results.rds", schedule_rds.name, f"pbp_{season}.rds")
        meta = {
            "created_ts": ds.iso_z(created_ts), "mode": export.mode,
            "nfl_drivers_sha": drivers_sha, "forecast_lab_sha": lab_sha,
            "results_created": ds.iso_z(export.results_created),
            "schedule_downloaded": ds.iso_z(export.schedule_downloaded),
            "upcoming_dropped": export.upcoming_dropped,
            "n_games": len(rows), "n_excluded": len(excluded),
            "kickoff_disagreements": disagreements, "capture_errors": capture_errors,
            "sha256": {name: ds.sha256_file(cache / name) for name in hashed},
        }  # fmt: skip
        path = ds.write_snapshot(out_root, created_ts, rows, excluded, meta, export, schedule_rds)
    for w in warnings:
        print(f"::warning title=Snapshot input::{w}")
    for d in disagreements:
        print(f"::warning title=Kickoff disagreement::{d}")
    if ds.no_quotes_at_all(rows):
        print("::error title=No quotes::no game has a Kalshi or Polymarket quote; "
              f"probabilities were saved anyway (capture errors: {capture_errors})")  # fmt: skip
    if export.upcoming_dropped:
        print(f"::warning title=Upcoming dropped::nfl-drivers dropped {export.upcoming_dropped} "
              "forecast-week games with incomplete features")  # fmt: skip
    return path


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--drivers", type=Path, default=ROOT.parent / "nfl-drivers")
    ap.add_argument("--rscript", default="Rscript")
    args = ap.parse_args(argv)
    try:
        path = take_snapshot(
            args.drivers.resolve(), ROOT, OUT_ROOT,
            export_fn=lambda rds, out: run_export(rds, out, args.rscript),
            capture_fn=capture_quotes, config_kickoffs=load_kickoffs(),
        )  # fmt: skip
    except ds.SnapshotRefused as exc:
        print(f"::error title=Snapshot refused::{exc}")
        return 1
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        return 2
    files = sorted(p for p in path.rglob("*") if p.is_file())
    print(f"wrote {path.relative_to(ROOT)}")
    print("commit with:\n  git add -- " + " ".join(str(p.relative_to(ROOT)) for p in files))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
```

Note: `results_created` and `schedule_downloaded` are never None when `meta` is built (freshness passed).

- [ ] **Step 4: Run tests**

Run: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q tests/test_snapshot_drivers_job.py tests/test_drivers_snapshot.py`
Expected: all pass.

- [ ] **Step 5: Live dry check (no files kept)**

Run a real capture only, to confirm Kalshi rows carry `kind == "winner"` and HOU@JAX's tickers exist:

```bash
PYTHON_DOTENV_DISABLED=1 uv run python -c "
import importlib.util, sys
s = importlib.util.spec_from_file_location('sd', 'jobs/snapshot_drivers.py'); m = importlib.util.module_from_spec(s); s.loader.exec_module(m)
q, e, t = m.capture_quotes(); print(t, e, len(q)); print(sorted({r['market_ticker'] for r in q if 'HOU' in r['market_ticker'].upper()}))"
```

Expected: errors empty; tickers include `KXNFLGAME-26OCT18HOUJAC-JAC` and `aec-nfl-hou-jax-2026-10-18`. If Kalshi's game market `kind` is not `"winner"`, stop and report it; do not change the filter blindly.

- [ ] **Step 6: Update `CLAUDE.md`**

Under `## Layout` add:

```markdown
- `drivers_snapshots/<ET date>/<UTC time>Z/`: NFL Drivers weekly snapshots (`jobs/snapshot_drivers.py`,
  spec `docs/superpowers/specs/2026-10-15-drivers-weekly-snapshot-design.md`). Written locally,
  committed and pushed by the user; append-only like `forecasts/` (`ci.yml` guard).
```

Under `## Status` add:

```markdown
- **NFL Drivers snapshot:** on game day, `Rscript run.R` in nfl-drivers, then
  `uv run python jobs/snapshot_drivers.py` here (both repos clean; results and schedule <= 6h old).
  Push before the first kickoff it covers; the counting rule is in the spec.
```

- [ ] **Step 7: Full verification**

Run, unpiped: `PYTHON_DOTENV_DISABLED=1 uv run pytest -q` then `uv run ruff check .`
Expected: both pass.

- [ ] **Step 8: Commit**

```bash
git add jobs/snapshot_drivers.py src/lab/drivers_snapshot.py tests/test_snapshot_drivers_job.py CLAUDE.md
git commit -m "feat(drivers): snapshot_drivers job ties export, capture and writing together

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

Do not push. Merging `drivers-snapshot` into `main` and pushing need the user's approval.

---

## Game-day runbook (after merge to main; for the user)

1. `cd nfl-drivers && Rscript run.R` (must finish within 6 h of the snapshot; for Sunday's 09:30 ET game, after 03:30 ET).
2. `cd forecast-lab` on an up-to-date, clean `main`: `uv run python jobs/snapshot_drivers.py`.
3. `git add -- <printed paths>`, commit, unpiped `PYTHON_DOTENV_DISABLED=1 uv run pytest -q` and `uv run ruff check .`, then push (approved) before the first kickoff the snapshot covers.
