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
- **One exception to "ask before pushing":** the `forecast` workflow (github-actions[bot],
  `.github/scripts/push_forecasts.sh`) may push NEW files under `forecasts/` to `main` without
  asking. It never modifies or deletes one (`ci.yml` fails any commit that does). Every other
  push, including all code, workflow and config changes, still needs the user's approval.
- The pre-registered rule lives in `RESEARCH_PROTOCOL.md`. Never edit anything above its
  "Changes" section; amendments are new dated sections under "Changes".

## Layout
- `main`: code, config, `forecasts/`. `data` branch (orphan): `snapshots/hourly|weekly/*.parquet`
  written only by Actions. `data/` locally is gitignored (DuckDB + raw).
- `src/lab/ingest/{common,kalshi,polymarket_us}.py`, `jobs/snapshot_markets.py`,
  `jobs/in_window.py` (collector gate), `jobs/gapcheck.py`, `jobs/compact_weekly.py`.
- Tracked markets live in `config/markets.yaml`.

## Status
- M0 done: scaffold, config loader, DuckDB schema, Actions skeleton (gap-check, weekly compact).
- **M1 done (2026-10-07):** Kalshi + Polymarket US snapshotter live. Hourly cron (`23 * * * *`)
  is enabled; `collect.yml` is split into `gate` and `collect` jobs.
- **Thin M2 done:** nflverse ingest, `elo-538-default-v0` (untuned 538 Elo), flat home-rate and
  market-mid baselines, and the forecast logger in `src/lab/forecasts.py` (refuses
  `created_ts >= kickoff`, never overwrites a CSV, refuses a dirty `src/`). Per-game isolation,
  provenance columns and `inputs_stale` landed in cbe3677 (a golden test pins the v0 models).
- **Done on `main`:** TB@DAL T-24h pilot forecast (`forecasts/2026-10-08/`, manual, horizon
  24h07m), portfolio site launch (88a93c4), `RESEARCH_PROTOCOL.md` pre-registered (358618f).
- **Phase A workflow definitions are on `main`.** The available local Git refs
  (`main`, `origin/main`, and `forecast-auto`) point to commit `1813021`, which contains
  `jobs/forecast_t24.py` (`gate` + `run`), `forecast.yml` (cron `11,26,41,56 * * * *`),
  `ci.yml` (pytest, ruff, forecasts/ append-only guard), daily `kickoffs.yml`
  (`17 10 * * *`), and `.github/scripts/push_forecasts.sh`. GitHub Actions run
  [37861409610](https://github.com/noah-olivieri/forecast-lab/actions/runs/37861409610)
  confirms a scheduled trigger on that commit: the gate succeeded, while forecast and alert
  jobs were skipped. This verifies scheduler activation, not an issued forecast. At that run's
  23:47Z timestamp, the first eligible forecast window had not opened (GO_LIVE was 00:15Z);
  end-to-end issuance remains unverified.
  The window per game is [K-24h, K-21h); the first successful run makes the forecast; a game
  with none is MISSED. A Kalshi snapshot older than 30 min fails that game's run (retried next
  run). `GO_LIVE` is 2026-10-09T00:15Z; games with kickoff >= GO_LIVE + 24h are eligible.
- **Open issue:** one successful scheduled gate run does not establish ongoing scheduler
  reliability or a successful forecast. The external workflow-dispatch backup for BOTH
  `collect.yml` and `forecast.yml` is not set up. The user creates any account and token.
  Until reliability is confirmed, before a manual forecast run use `gh workflow run collect.yml`,
  wait for it, then `git fetch origin data`.
- Next (revised roadmap, see RESEARCH_PROTOCOL.md): verify an eligible forecast completes and
  produces its receipt; then Phase B minimal auto-settlement (ordinary games settle automatically,
  odd cases flagged); Phase C/D scoring (Brier primary, log loss secondary) on a labeled
  historical backtest plus the live sample; Phase E encompassing test vs market; then feature
  research for nfl-feature-v1. Parked: econ/M4, sportsbook ingestion, spreads, multi-sport,
  paper trading, site polish.

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
- Schedule: hourly :23 always, plus a `7,22,37,52 * * * *` cron every day that
  `jobs/in_window.py` gates. The cron strings live in `collect.yml` and as `HOURLY_CRON` /
  `WINDOW_CRON` in `in_window.py`; a test keeps them equal. Change both together.
  A gated run captures only from 45 min before to 15 min after a kickoff in `config/kickoffs.json`
  (10 min grace for late-starting runs), so international, Saturday, Friday and holiday games are
  covered. `jobs/build_kickoffs.py` builds that file from nflreadpy (nflverse ET gametime -> UTC);
  `kickoffs.yml` reruns it Tuesdays and commits to `main` only if it changed. Missing/unreadable
  file -> fixed Thu/Sun/Mon Pacific windows plus a warning. The gate is stdlib-only (runs before
  `uv sync`).
- Gap-check judges whole UTC hours, so an extra 15-minute run inside an hour counts as covering
  that hour even if the :23 run failed. Accepted weakness. A `workflow_dispatch` backup run
  covers its hour the same way, and adds a second snapshot to hours the cron also covered
  (about 68 KiB more per hour).
- Size: about 68 KiB per run (about 11 MB/week hourly) before weekly compaction.
