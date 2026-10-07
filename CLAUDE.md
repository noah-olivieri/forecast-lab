# Forecast Lab: working notes for Claude

Paper-trading research project: models for econ and NFL event contracts vs. prediction-market
prices (Brier, calibration, simulated P&L after fees). **No real money.** Full design is in
`PLAN.md`; this file is the short list of rules and current status.

## Rules
- **Before any `git push`: run `uv run pytest -q` with no pipe (not through `tail`/`head`) and
  confirm it passes.** A pipe hides the exit code. Also run `uv run ruff check .`.
- Never read, print or log secrets. `.env` is gitignored; use `lab.config.get_secret` /
  `Secret`. If a job needs `FRED_API_KEY`, tell the user to add it as a repo secret themselves.
- Stage by explicit path, never `git add -A`. Confirm `.env` and `data/` are not staged.
- Commit author is the GitHub noreply address (repo-local `user.email`); keep it.
- Forecast proof (PLAN.md 7a): forecast CSVs go in `forecasts/`, committed and pushed to
  `main` before the event closes. The remote's receipt time is the evidence.
- Third-party GitHub Action versions must be verified to exist (`gh api repos/<r>/git/ref/tags/<tag>`)
  before use. A guessed tag (`setup-uv@v10`) failed the first real run.
- Leakage rules (PLAN.md 7): every feature function takes `as_of`; ALFRED vintages only; the
  market price compared to a forecast comes from the same snapshot.
- `main` is protected against force-push and deletion (ruleset, no bypass). Never force-push.

## Layout
- `main`: code, config, `forecasts/`. `data` branch (orphan): `snapshots/hourly|weekly/*.parquet`
  written only by Actions. `data/` locally is gitignored (DuckDB + raw).
- `src/lab/ingest/{common,kalshi,polymarket_us}.py`, `jobs/snapshot_markets.py`,
  `jobs/in_window.py` (collector gate), `jobs/gapcheck.py`, `jobs/compact_weekly.py`.
- Tracked markets live in `config/markets.yaml`.

## Status
- M0 done: scaffold, config loader, DuckDB schema, Actions skeleton (gap-check, weekly compact).
- **M1 done (2026-10-07):** Kalshi + Polymarket US snapshotter live. Manual `collect` runs
  succeeded twice and appended linear commits to `data`. Hourly cron (`5 * * * *`) is enabled.
- **Thin M2 done (5b383cf):** nflverse ingest, `elo-538-default-v0` (untuned 538 Elo), flat
  home-rate and market-mid baselines, and a forecast logger in `src/lab/forecasts.py` that refuses
  `created_ts >= kickoff`, never overwrites a CSV, and refuses a dirty `src/`.
- Kickoff windows come from `config/kickoffs.json` (`jobs/build_kickoffs.py`, refreshed weekly by
  `kickoffs.yml`).
- `collect.yml` is split into `gate` and `collect` jobs (only `collect` holds the `data-branch`
  concurrency group), verified by a manual run on 10/6.
- **Open issue:** the scheduled cron has not fired since going live on 10/6. Before every
  forecast, run `gh workflow run collect.yml`, wait for it, then `git fetch origin data`.
- Next: TB@DAL T-24h forecast Wed 10/7 at or after 5:15 PM PT, then forecast CLI, settle job, M3
  scoring/leakage tests, M4 ALFRED/BLS and Cleveland nowcast daily snapshot.
- Not yet built: forecast CLI, Cleveland Fed nowcast snapshot job, settle job. The `created_ts <
  event_close_ts` check lives in the logger, not the schema (DuckDB cannot check across tables).

## M1 decisions and caveats
- Kalshi is the system of record; Polymarket US is a secondary cross-venue reference.
- NFL series are fetched before econ. A failing series/venue becomes a warning; the job fails
  only if nothing was captured.
- Kalshi: one paginated `/markets?series_ticker&status=open` call per series (list payload has
  bid/ask/size), 5 req/s vs ~20 limit. Settled markets drop out of the open listing; the M2
  settle job resolves them.
- Polymarket US: quotes come embedded in event payloads (`/v2/leagues/nfl/events`,
  `/v1/events?categories=macro`), 5 req/s vs 25 limit. No sizes/open interest, and quotes may lag.
  Tracked: full-game winner/spread/total only; econ = macro events matching
  `polymarket_us.econ_title_regex`.
- **`event_time` is not uniform:** Polymarket NFL = true kickoff; Kalshi NFL =
  `occurrence_datetime` = expected game END (~3h after kickoff). Take kickoff from nflverse or
  Polymarket's `gameStartTime` for T-24h / T-1h cutoffs.
- Kalshi displayed sizes can be absurd (10M+ contracts at the top of book). Cap before using for
  simulated fills.
- Snapshot columns are venue-reported dollars for YES; a 0 bid with 0 size means an empty book.
- Schedule: hourly :05 always, plus a `*/15 * * * *` cron every day that `jobs/in_window.py` gates.
  A gated run captures only from 45 min before to 15 min after a kickoff in `config/kickoffs.json`
  (10 min grace for late-starting runs), so international, Saturday, Friday and holiday games are
  covered. `jobs/build_kickoffs.py` builds that file from nflreadpy (nflverse ET gametime -> UTC);
  `kickoffs.yml` reruns it Tuesdays and commits to `main` only if it changed. Missing/unreadable
  file -> fixed Thu/Sun/Mon Pacific windows plus a warning. The gate is stdlib-only (runs before
  `uv sync`).
- Gap-check judges whole UTC hours, so an extra 15-minute run inside an hour counts as covering
  that hour even if the :05 run failed. Accepted weakness.
- Size: about 68 KiB per run (about 11 MB/week hourly) before weekly compaction.
