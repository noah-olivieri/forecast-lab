# NFL Drivers weekly snapshot: design

Date: 2026-10-15. Status: approved in conversation, awaiting written-spec review.

## Purpose

Before kickoff, save NFL Drivers' upcoming-week win probabilities (`full_qb_ridge`), the
inputs they were computed from, and Kalshi and Polymarket US prices captured at the same
moment. Every record is timestamped, written once, and never overwritten. The record is
evidence that a probability existed before kickoff, so it can later be compared with the
market price available at that time (DECISIONS.md 2026-10-15).

What the user specified:
- Source: `nfl-drivers` master, `results$upcoming`, headline model `full_qb_ridge`, with
  projected starting QBs and the schedule download time.
- Rows for unplayed or canceled games have NA outcomes. Scoring filters on `!is.na(margin)`.
  `upcoming_dropped` is recorded.
- Local run, then a manual commit and a push that the user approves (option chosen in brainstorming).
- Inputs: full per-game feature rows plus provenance. If the nfl-drivers change is not ready
  before a game day, still take the snapshot in provenance-only mode with a copy of the
  2026 schedule file, rather than skipping the week.
- Counting rule (Phase C applies it; nothing here implements it): see "Which snapshot counts".
- Freshness: 6 hours. Kickoffs come from the nflverse schedule; a missing kickoff fails
  the run. No quotes still writes predictions. Both repos must be clean.

Assumptions (stated in brainstorming, not corrected):
- This is a record, not a trade. It does not fix a decision horizon, entry rule or sizing;
  those remain "not yet selected" per DECISIONS.md 2026-10-15. Each row records its own
  minutes to kickoff.
- `p_home` is P(home team wins), the convention in `src/lab/forecasts.py`. Polymarket
  quotes whose YES side is the away team are flipped into the home team's perspective.
- "Game day" is the kickoff's calendar date in US/Eastern, the convention forecast-lab
  already uses to date games.

Out of scope: scoring, settlement, paper trades, automation in GitHub Actions, any change to
the T-24h job, `forecasts/`, `config/kickoffs.json`, or `RESEARCH_PROTOCOL.md`.

## Architecture

```
nfl-drivers (R)                         forecast-lab (Python)
  Rscript run.R                           uv run python jobs/snapshot_drivers.py --drivers ../nfl-drivers
    -> data/cache/results.rds  ---------->  1. repo checks (both clean; freshness)
    -> data/cache/schedules_2026.rds        2. Rscript jobs/export_drivers.R -> temp dir (CSV + JSON)
                                            3. kickoffs from the exported schedule
                                            4. one quote capture, both venues
                                            5. rows per game -> drivers_snapshots/<date>/<ts>Z/
                                            6. print the exact `git add` paths; stop
```

Approach chosen: a forecast-lab job plus a short R exporter that lives in forecast-lab.
Rejected: reading `results.rds` with `pyreadr` (it only reads single-data-frame RDS files;
`results.rds` is a nested list), and doing the market calls in R (it would duplicate the
tested venue ingest, ticker mapping and YES-side flip).

### Units

| Unit | Job | Depends on |
|---|---|---|
| `jobs/export_drivers.R` | Read `results.rds`; write `upcoming.csv` (`full_qb_ridge` rows only, with `gameday`, `gametime`), `features.csv` (only if `results$upcoming_features` exists), `meta.json` (`created`, `schedule_downloaded`, `upcoming_dropped`) to a given directory. Base R + `jsonlite` only. | R |
| `src/lab/drivers_snapshot.py` | Pure logic: repo checks, freshness, kickoff derivation, row building, quote matching, directory writing. No network; quote capture and the R export are injected. | `lab.forecasts` helpers, `lab.ingest.nflverse.to_kickoff_utc` |
| `jobs/snapshot_drivers.py` | CLI: runs the exporter, captures quotes with `kalshi.snapshot` / `polymarket_us.snapshot`, calls the logic, prints results and paths. | the two above, `lab.ingest` |
| `.github/scripts/check_forecasts_append_only.sh` | Extended to cover `drivers_snapshots/` as well as `forecasts/`. | git |

Reused, not changed: `_tickers`, `NICKNAMES`, `flip_quote`, `current_git_sha`-style checks
from `src/lab/forecasts.py`; `to_kickoff_utc` from `src/lab/ingest/nflverse.py`.

## Data flow, step by step

1. **Repo checks** (any failure: refuse, write nothing):
   - nfl-drivers: `git status --porcelain` is empty (ignored files such as `data/cache/` and
     `report.html` do not count). Record HEAD's SHA.
   - forecast-lab: `git status --porcelain` is empty except for paths under
     `drivers_snapshots/` (outputs, not code). Record HEAD's SHA. This makes the recorded SHA
     describe the code that ran.
   - `results$created` is at or after nfl-drivers HEAD's commit time.
   - `results$code_sha` (HEAD when `run.R` ran, recorded by nfl-drivers `code_state()`) equals
     HEAD now, and `results$code_dirty` is FALSE. This is what ties the results to the code;
     the commit-time check alone cannot (amended 2026-10-16 after the Task 5 review, user's
     choice). results.rds without these fields is refused.
2. **Export**: run `Rscript jobs/export_drivers.R <results.rds> <tmpdir>`. A nonzero exit,
   missing output, or zero `full_qb_ridge` rows is a refusal. Mode is `full` when
   `features.csv` was produced, else `provenance_only`.
3. **Kickoffs** from the exported `gameday` + `gametime` (US/Eastern wall clock from the same
   schedule the model used) via `to_kickoff_utc`. If any `full_qb_ridge` row has a missing
   or unparseable `gameday` or `gametime`, the run fails and names the games. Also read
   (never write) `config/kickoffs.json`; for the pre-kickoff check use the earlier of the two
   times when both exist, and list every disagreement in `meta.json` and as a warning.
4. **Quote capture**: one capture per venue, NFL winner markets only, using the existing
   ingest code. `created_ts` is the moment capture finishes (UTC, seconds).
5. **Freshness** (checked against `created_ts`; failure: refuse, write nothing):
   `results$created` and `schedule_downloaded` must each be in
   `[created_ts - 6h, created_ts]`. Later than `created_ts` is impossible and also refused.
   Practical consequence: each game day needs its own `Rscript run.R`.
6. **Rows**, one per game:
   - Kickoff at or before `created_ts`: excluded, listed in `excluded.csv` (`game_started`).
   - Kalshi: ticker from `_tickers`; quote must have `ts_utc` within 5 minutes before
     `created_ts`, else treated as missing.
   - Polymarket US: same 5-minute rule; YES side mapped with `NICKNAMES`, flipped with
     `flip_quote` when YES is the away team. Unmappable YES side: warning, treated as missing.
   - `status`: `ok` (Kalshi present), `no_kalshi_quote` (Kalshi missing, Polymarket present),
     `no_quotes` (neither). Rows are written in every case. If no game has any quote
     (for example both captures failed), print a loud `::error`-style warning but still write
     the snapshot: the timestamped probabilities are evidence on their own.
7. **Write** the directory with exclusive create (`mkdir` without `exist_ok`); an existing
   directory is a refusal. Files are written into it only after every check passed. Then print
   the exact paths for `git add` and stop. Commit and push stay manual: unpiped
   `uv run pytest -q` and `uv run ruff check .` first (CLAUDE.md), and the user approves
   the push.

## Output layout

```
drivers_snapshots/<created_ts date in ET>/<created_ts as YYYY-MM-DDTHH-MM-SS>Z/
  predictions.csv
  excluded.csv
  meta.json
  inputs/upcoming.csv            exported full_qb_ridge rows, as nfl-drivers produced them
  inputs/features.csv            full mode only
  inputs/schedules_2026.rds      byte copy of nfl-drivers data/cache/schedules_2026.rds
```

`predictions.csv` columns (one row per game, wide across venues):
`game_id, season, week, home_team, away_team, kickoff_ts, kickoff_source_disagrees,
game_day_et, same_day, created_ts, minutes_to_kickoff, model, model_version, p_home,
pred_margin, home_qb_projected, away_qb_projected, status,
kalshi_ticker, kalshi_yes_bid, kalshi_yes_ask, kalshi_bid_size, kalshi_ask_size, kalshi_quote_ts,
poly_ticker, poly_yes_team_raw, poly_flipped, poly_yes_bid, poly_yes_ask, poly_quote_ts`

- `model` = `full_qb_ridge`; `model_version` = `nfl-drivers@<sha>`.
- `same_day` = `game_day_et` equals the ET date of `created_ts`.
- Prices are venue-reported YES dollars in the home team's perspective; a 0 bid with 0 size is
  an empty book (existing convention). Sizes are raw venue values (Polymarket has none).

`excluded.csv`: `game_id, kickoff_ts, reason`.

`meta.json`: `created_ts`, `mode`, `nfl_drivers_sha`, `forecast_lab_sha`,
`results_created`, `schedule_downloaded`, `upcoming_dropped`, `n_games`, `n_excluded`,
`kickoff_disagreements`, `capture_errors` (per venue), and SHA-256 of `results.rds`,
`schedules_2026.rds` and `pbp_2026.rds` in nfl-drivers' cache (a missing file is recorded as
`null`, not a refusal).

## Which snapshot counts (recorded rule; Phase C implements it)

For each game, the snapshot that counts is the earliest by `created_ts` among snapshots where:
`same_day` is true, `created_ts` < kickoff, and the commit that added it was received by
`origin/main` before kickoff. Earlier-day snapshots are kept as records and never count.
Game-day reruns never replace the first. Scoring uses completed games only
(`!is.na(margin)`); canceled or unplayed games are dropped and counted. The user records
this rule in DECISIONS.md in their own words before the first comparison.

## nfl-drivers change (full mode)

- In `run_all()`, before the `completed()` filtering, keep the forecast week's feature rows:
  `features_ridge[is.na(features_ridge$margin), ]` restricted to `game_id`, `season`, `week`
  and the `MODEL_SPECS$full_qb` columns, saved as `results$upcoming_features`.
- In `build_features()`, add `weather_imputed` (0/1), set before temp or wind is filled from
  medians, so the archive shows which weather values were filled in rather than forecast.
  The values themselves do not change.
- testthat: `upcoming_features` has only NA-margin games; its game IDs equal those of
  `full_qb_ridge` in `upcoming`; `weather_imputed` is 1 exactly where source temp or wind
  was NA.
- No model, feature-value or scoring change. If this is not merged before a game day, the
  snapshot runs in `provenance_only` mode.

## Refusals and warnings

Refuse, write nothing: dirty nfl-drivers tree; dirty forecast-lab tree (outside
`drivers_snapshots/`); `results$created` before nfl-drivers HEAD's commit time; freshness
breach (either timestamp); R export failure; zero `full_qb_ridge` rows; a missing or
unparseable kickoff for any `full_qb_ridge` game; target directory exists.

Write, with a status or warning: game started (excluded); no Kalshi quote; no Polymarket
quote or unmappable YES side; stale quote (treated as missing); both venues failed or no
quotes at all (`no_quotes`, loud warning); `upcoming_dropped` > 0 (printed);
kickoff disagreement with `config/kickoffs.json` (earlier time used for the check).

## Testing (pytest, no network)

The R export is faked with fixture CSV/JSON and quotes with fixture rows.
- Each refusal above, including freshness at exactly 6h (allowed) and 6h + 1s (refused).
- Started-game exclusion at the kickoff boundary (`created_ts == kickoff` is excluded).
- Earlier-of-two-kickoffs rule and the disagreement record.
- Polymarket flip and unmappable YES side.
- `no_quotes` path writes predictions and warns.
- Exclusive create: a second run into the same directory fails and leaves the first intact.
- `same_day` around ET midnight and in the 00:00-09:30 ET window for a London game.
- `full` vs `provenance_only` mode.
- Dirty-tree checks, including that untracked files under `drivers_snapshots/` are allowed.
- One test runs the real `export_drivers.R` against a small `results.rds` built in the test;
  skipped when `Rscript` is not installed (as in CI).
- Append-only guard: a commit modifying a file under `drivers_snapshots/` fails the script.
